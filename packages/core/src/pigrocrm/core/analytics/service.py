from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.repository import AnalyticsRepository
from pigrocrm.core.analytics.schemas import DealPnl, PeriodPnl, PeriodPnlQuery, PnlTotals
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.money import ZERO_MONEY, percentage_of, sum_money
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
    this slice from computing any economic total at all -- Acme's whole P&L lived in
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


__all__ = ["AnalyticsService"]
