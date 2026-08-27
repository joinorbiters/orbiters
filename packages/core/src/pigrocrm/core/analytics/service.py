from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.repository import AnalyticsRepository
from pigrocrm.core.analytics.schemas import (
    BudgetPage,
    BudgetQuery,
    BudgetVsActualRow,
    DealPnl,
    PeriodPnl,
    PeriodPnlQuery,
    PnlTotals,
)
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.money import (
    ZERO_HOURS,
    ZERO_MONEY,
    percentage_of,
    round_money,
    sum_money,
)
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.service import TimeEntryService

ENTITY = "analytics"


def _months_between(da: date, a: date) -> list[tuple[int, int]]:
    """Every (year, month) the window touches, inclusive. Iterated rather than computed
    with arithmetic on month numbers, which is where December off-by-ones live."""
    months: list[tuple[int, int]] = []
    year, month = da.year, da.month
    while (year, month) <= (a.year, a.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _comparable(estimate: Decimal | None) -> Decimal | None:
    """The estimate itself when it can be compared against, `None` when it cannot.

    An estimate is comparable only when it is present **and** greater than zero. `None`
    means nobody estimated. `0` is the state residual A14 made the only reachable spelling
    of "no estimate" before Task 4B-1 closed it, and it reads to any division as "zero
    hours estimated, infinite overrun". Both are refused as denominators here -- the
    secondary defence §9.2 requires regardless of A14.

    Returns the narrowed value rather than a `bool` on purpose: a predicate would leave
    every call site holding a `Decimal | None` that the type checker has no way to follow,
    and the usual repair for that is a `cast` or an `assert` -- an escape hatch standing
    exactly where the null this function exists to catch would come through.
    """
    if estimate is None or estimate <= 0:
        return None
    return estimate


def _totals(rows: list[tuple[Decimal, Decimal, Decimal]]) -> PnlTotals:
    """One column of `(ricavi, costi diretti, costo lavoro)` triples, summed.

    `sum_money` and not `sum()`: the rows arriving here are already rounded per deal, and
    the column total has to be the sum of the printed figures rather than the rounding of
    an exact sum -- the same rule the timesheet obeys, for the same reason (§6.2).
    """
    ricavi = sum_money([row[0] for row in rows])
    costi = sum_money([row[1] for row in rows])
    lavoro = sum_money([row[2] for row in rows])
    margine = ricavi - costi - lavoro
    return PnlTotals(
        ricavi=ricavi,
        costi_diretti=costi,
        costo_lavoro=lavoro,
        margine_lordo=margine,
        margine_percentuale=percentage_of(margine, ricavi),
        deal=len(rows),
    )


class AnalyticsService:
    """Reads only, except for `bind_time_to_invoice` (Task 4B-7).

    Every figure is computed here and returned already summed. §6 forbids the frontend of
    this slice from computing any economic total at all -- the previous system's whole P&L lived in
    `App.jsx`, with three fiscal constants and float hour sums, and moving it here is the
    final payment on the debt slice 1 §2.2 cited as the empirical justification for this
    architecture.

    No `require_write` and no `require_admin` anywhere in the read methods: a `readonly`
    actor is entitled to every figure in this file. The P&L of a deal is not more
    sensitive than the deal, the hours and the invoices it is derived from, each of which
    a reader can already list.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = AnalyticsRepository(session)
        self.deals = DealRepository(session)
        self.entries = TimeEntryService(session)

    def deal_pnl(self, deal_id: UUID, actor: Actor) -> DealPnl:
        """The rows of §7.1, each from its one stated source.

        `valore_maturato = ricavi + valore delle ore fatturabili non fatturate`. It is
        **not** revenue, enters no P&L row, and is returned in a field of its own name
        (§7.3): on an `in corso` deal it is the honest figure and the margin is
        provisional; the margin is only reportable when the state is `chiuso`.

        Which reading of "already invoiced" this uses, since task 4B-3 left two that
        deliberately differ: the **invoice-state** one, through `billed_entry_ids`, not
        the link-based one the `fatturato` list filter applies. An hour bound to a line of
        a *draft* invoice is `fatturato` in that list and still fully editable; here it
        still counts as billable-and-unbilled, because a draft is not revenue and the
        link-based reading would leave the work in neither figure -- priced, done and
        invisible until somebody pressed "issue".
        """
        deal = self.deals.get(deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)

        ricavi, fatture = self.repo.deal_revenue(deal_id)
        costi_diretti = self.repo.deal_direct_costs(deal_id)
        # Reuses 4A's own summary rather than recomputing hours here: one definition of
        # "labour cost" and one of "state", so the Ore tab and the Economia tab can never
        # disagree about the same deal.
        summary = self.entries.deal_summary(deal_id, actor)
        margine = ricavi - costi_diretti - summary.costo_lavoro

        return DealPnl(
            deal_id=deal_id,
            stato=summary.stato,
            ricavi=ricavi,
            costi_diretti=costi_diretti,
            costo_lavoro=summary.costo_lavoro,
            margine_lordo=margine,
            # `percentage_of` returns `None` for a zero denominator and performs no
            # division at all in that case, so this is the only place the question is
            # asked and there is no second answer to keep aligned.
            margine_percentuale=percentage_of(margine, ricavi),
            ore_totali=summary.ore_totali,
            ore_fatturabili_non_fatturate=summary.ore_fatturabili_non_fatturate,
            valore_maturato=ricavi + summary.valore_ore_non_fatturate,
            ore_senza_tariffa=summary.ore_senza_tariffa,
            fatture_emesse=fatture,
        )

    def period_pnl(self, query: PeriodPnlQuery, actor: Actor) -> PeriodPnl:
        """Aggregated over a date window, optionally scoped to one customer.

        Each quantity is attributed to the period by **its own** date: revenue by
        `invoices.data_emissione`, costs by `costs.data`, labour cost by
        `time_entries.data`. Not by the deal's date, which does not exist, and not by one
        common date, which none of the three has.

        Presented in **two columns** -- closed deals and deals in progress -- because
        adding a finished job's margin to a half-done one produces a figure that is
        neither, and that changes every week for reasons which are not business
        performance. The reportable number is the first, and there is deliberately no
        combined field to read by mistake.
        """
        if query.a < query.da:
            raise ValidationFailed(
                ENTITY, "a", "intervallo invertito", expected="una data non anteriore a 'da'"
            )

        revenue = self.repo.revenue_in_range(query.da, query.a, query.customer_id)
        per_deal_costs, general = self.repo.costs_in_range(query.da, query.a, query.customer_id)
        labour = self.repo.labour_cost_in_range(query.da, query.a, query.customer_id)

        chiusi: list[tuple[Decimal, Decimal, Decimal]] = []
        in_corso: list[tuple[Decimal, Decimal, Decimal]] = []
        for deal in self.repo.deals_in_range(query.da, query.a, query.customer_id):
            row = (
                revenue.get(deal.id, ZERO_MONEY),
                per_deal_costs.get(deal.id, ZERO_MONEY),
                labour.get(deal.id, ZERO_MONEY),
            )
            # The state comes from the same place the deal's own P&L gets it, so the two
            # screens can never disagree about which column a deal belongs in -- and, in
            # particular, both read "already invoiced" as the *invoice state* through
            # `billed_entry_ids`, never as the link-based `fatturato` list filter. An
            # hour bound to a line of a draft invoice is not revenue yet.
            stato = self.entries.deal_summary(deal.id, actor).stato
            (chiusi if stato == "chiuso" else in_corso).append(row)

        locks = PeriodLockService(self.session)
        # A window is only as closed as its least-closed month: reporting a quarter as
        # closed because one of its months is would be the wrong reassurance in the one
        # place it matters.
        periodo_chiuso = all(
            locks.is_closed(date(anno, mese, 1)) is not None
            for anno, mese in _months_between(query.da, query.a)
        )

        return PeriodPnl(
            da=query.da,
            a=query.a,
            customer_id=query.customer_id,
            chiusi=_totals(chiusi),
            in_corso=_totals(in_corso),
            # Never apportioned onto any deal (§7.4), and absent entirely under a
            # customer filter, because a general expense belongs to no customer.
            spese_generali=general,
            periodo_chiuso=periodo_chiuso,
            # Free: a COUNT over two columns that already exist, and the one thing a
            # reader most needs to know about an open period (§6.4).
            voci_scritte_in_ritardo=self.repo.late_entry_count(query.da, query.a),
        )

    def budget_vs_actual(self, query: BudgetQuery, actor: Actor) -> BudgetPage:
        """Estimate against actual, per deal, with the pro-rata comparison beside the
        full one rather than instead of it.

        This is the payment on an investment made in advance: `deals.ore_preventivate`
        and `deals.valore_preventivato` have existed since slice 1 -- written with a
        comment saying so -- and have never been read by anybody. The actuals are the one
        missing half.
        """
        if query.a < query.da:
            raise ValidationFailed(
                ENTITY, "a", "intervallo invertito", expected="una data non anteriore a 'da'"
            )

        revenue = self.repo.revenue_in_range(query.da, query.a, query.customer_id)
        hours = self.repo.hours_in_range(query.da, query.a, query.customer_id)
        deals = self.repo.deals_in_range(query.da, query.a, query.customer_id)

        # Keyset pagination over the already-ordered deal list rather than a second
        # database round trip: `deals_in_range` orders by `(nome, id)`, so the cursor is
        # the last id of the page.
        if query.cursor is not None:
            ids = [deal.id for deal in deals]
            if query.cursor in ids:
                deals = deals[ids.index(query.cursor) + 1 :]
        window = deals[: query.limit]
        next_cursor = window[-1].id if len(deals) > query.limit and window else None

        rows: list[BudgetVsActualRow] = []
        for deal in window:
            ore_consuntivate = hours.get(deal.id, ZERO_HOURS)
            ricavi = revenue.get(deal.id, ZERO_MONEY)
            # Narrowed to "comparable or absent" once, here, so that below there is
            # nothing left to divide by that could be null or zero.
            ore_prev = _comparable(deal.ore_preventivate)
            valore_prev = _comparable(deal.valore_preventivato)

            avanzamento = (
                percentage_of(ore_consuntivate, ore_prev) if ore_prev is not None else None
            )
            # The pro-rata needs BOTH estimate columns. With a value estimate and no hours
            # estimate there is no progress to derive it from, and inventing one from the
            # invoiced value would be circular -- the invoiced value is the quantity being
            # judged.
            pro_rata = (
                round_money(valore_prev * avanzamento / Decimal(100))
                if (valore_prev is not None and avanzamento is not None)
                else None
            )
            rows.append(
                BudgetVsActualRow(
                    deal_id=deal.id,
                    nome=deal.nome,
                    # The stored column, not the narrowed one: a deal estimated at zero
                    # hours should show the zero somebody typed. What `_comparable`
                    # governs is what may be divided by, never what may be displayed.
                    ore_preventivate=deal.ore_preventivate,
                    ore_consuntivate=ore_consuntivate,
                    valore_preventivato=deal.valore_preventivato,
                    ricavi=ricavi,
                    avanzamento_ore=avanzamento,
                    budget_pro_rata=pro_rata,
                    # Measured against the pro-rata, never the full budget: at 40% of the
                    # hours, being at 40% of the estimated value is on track, and
                    # comparing with 100% would mark every job in progress as
                    # underperforming.
                    scostamento_valore=(ricavi - pro_rata) if pro_rata is not None else None,
                    scostamento_ore=(ore_consuntivate - ore_prev if ore_prev is not None else None),
                    tariffa_media_preventivata=(
                        round_money(valore_prev / ore_prev)
                        if (ore_prev is not None and valore_prev is not None)
                        else None
                    ),
                    # The row that serves best, and the only form in which "is this client
                    # worth it?" has a numeric answer: how much was realised per hour
                    # worked, comparable even between deals of very different sizes.
                    # `None` with no hours logged, never `0.00`, which would read as
                    # "realised nothing per hour" -- the opposite of the truth on a deal
                    # invoiced without a timesheet.
                    tariffa_media_consuntivata=(
                        round_money(ricavi / ore_consuntivate) if ore_consuntivate > 0 else None
                    ),
                    non_preventivato=ore_prev is None and valore_prev is None,
                    pro_rata_non_calcolabile=valore_prev is not None and ore_prev is None,
                )
            )

        budgeted = [row for row in rows if not row.non_preventivato]
        return BudgetPage(
            items=rows,
            next_cursor=next_cursor,
            # Only over rows with an estimate: including the unestimated ones would make
            # the aggregate depend on how many deals nobody estimated.
            totale_preventivato=sum_money([row.valore_preventivato for row in budgeted]),
            totale_ricavi=sum_money([row.ricavi for row in budgeted]),
            deal_preventivati=len(budgeted),
            deal_non_preventivati=len(rows) - len(budgeted),
        )


__all__ = ["AnalyticsService"]
