from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.repository import AnalyticsRepository
from pigrocrm.core.analytics.schemas import DealPnl
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.errors import NotFound
from pigrocrm.core.money import percentage_of
from pigrocrm.core.timetracking.service import TimeEntryService

ENTITY = "analytics"


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


__all__ = ["AnalyticsService"]
