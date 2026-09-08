"""§5.2 and §6.2's invoice-side figures.

Two families of test carry the weight here.

The first is about **which column**. `da_incassare` must follow `totale` and revenue must
follow `imponibile`, and each must fail if it followed the other. Under the forfettario
regime the two columns are equal, so a test built only on the shipped default profile
cannot tell a correct implementation from a wrong one -- hence rows where they diverge,
read twice: once through this file's aggregate and once through the revenue aggregate
slice 4 already owns. That second read is what makes "these are two different figures" an
assertion instead of a claim in a docstring.

The second is about **whose today**. `data_scadenza < today` is the whole of "overdue", and
there are three plausible spellings of `today` in this codebase: `today_local()` -- the
emitter's day, and the only correct one -- `CURRENT_DATE`, which is the database server's,
and `date.today()`, which is the API container's (UTC). The two rows in
`test_overdue_is_measured_against_the_emitters_day` are chosen so that all three give
different answers, so the test names the clock rather than merely exercising it.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from orologio import OGGI_DEL_PROCESSO, OGGI_IN_ITALIA, congela
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.repository import AnalyticsRepository
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import today_local
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.invoices.repository import InvoiceRepository
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=None, type="system", role="admin")


@pytest.fixture
def customer(db_session: Session) -> Customer:
    row = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(row)
    db_session.flush()
    return row


def _invoice(
    db_session: Session,
    customer: Customer,
    *,
    tipo: str = "fattura",
    stato: str = "emessa",
    stato_pagamento: str = "da_incassare",
    imponibile: str = "1000.00",
    totale: str = "1220.00",
    data_emissione: date | None = None,
    data_scadenza: date | None = None,
    deal_id: UUID | None = None,
    anno: int | None = None,
    numero: int | None = None,
) -> Invoice:
    """One row, written directly.

    Not through `InvoiceService`: `imponibile` and `totale` are recomputed from the lines
    there and the forfettario profile the suite ships makes them equal, which is precisely
    the case these tests must be able to step outside of. `anno`/`numero` are left null by
    default -- `ck_invoices_anno_numero_together` requires them to move as a pair -- and are
    supplied only by the test that reads the revenue aggregate, which filters on `anno`.
    """
    row = Invoice(
        customer_id=customer.id,
        deal_id=deal_id,
        tipo=tipo,
        stato=stato,
        stato_pagamento=stato_pagamento,
        imponibile=Decimal(imponibile),
        imposta=Decimal("0.00"),
        bollo=Decimal("0.00"),
        totale=Decimal(totale),
        data_emissione=data_emissione or today_local(),
        data_scadenza=data_scadenza,
        anno=anno,
        numero=numero,
        tipo_documento="TD01",
        divisa="EUR",
        custom_fields={},
    )
    db_session.add(row)
    db_session.flush()
    return row


# --- da incassare -------------------------------------------------------------------


def test_da_incassare_sums_totale_over_issued_unpaid_invoices(
    db_session: Session, customer: Customer
) -> None:
    _invoice(db_session, customer, imponibile="1000.00", totale="1220.00")
    _invoice(db_session, customer, imponibile="500.00", totale="610.00")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("1830.00")


def test_an_empty_register_is_zero_with_two_decimal_places(db_session: Session) -> None:
    """`"0.00"` and not `"0"`. `coalesce(sum(...), 0)` returns the integer literal when no
    row matches, and the browser prints what it is given -- the same reason
    `AnalyticsRepository.deal_revenue` quantizes."""
    repo = InvoiceRepository(db_session)
    assert str(repo.sum_da_incassare()) == "0.00"
    assert str(repo.sum_scaduto()) == "0.00"


def test_da_incassare_follows_totale_while_revenue_follows_imponibile(
    db_session: Session, customer: Customer
) -> None:
    """The two figures over the *same* rows, read through the two aggregates that own them.

    Revenue is `Σ imponibile` (slice 4 §7.1, and this slice introduces no third meaning); a
    receivable is what must arrive in the bank, which includes VAT -- money collected on the
    State's behalf. Under the forfettario the two columns coincide and the difference is
    unobservable, so these rows are built with `imposta` folded into `totale` and the two
    answers are required to differ. An implementation that picked the wrong column for
    either figure fails here, and only here.
    """
    anno = today_local().year
    _invoice(db_session, customer, imponibile="1000.00", totale="1220.00", anno=anno, numero=1)

    receivable = InvoiceRepository(db_session).sum_da_incassare()
    revenue = AnalyticsRepository(db_session).annual_revenue(anno)
    assert receivable == Decimal("1220.00")
    assert revenue == Decimal("1000.00")
    assert receivable != revenue


def test_a_paid_invoice_is_not_a_receivable(db_session: Session, customer: Customer) -> None:
    _invoice(db_session, customer, stato_pagamento="incassato")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


def test_a_draft_or_annulled_invoice_is_not_a_receivable(
    db_session: Session, customer: Customer
) -> None:
    """An annulled invoice keeps its number and loses its claim: the struck-through page of
    a paper register. A draft was never a claim at all."""
    _invoice(db_session, customer, stato="bozza")
    _invoice(db_session, customer, stato="annullata")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


def test_a_proforma_is_not_a_receivable(db_session: Session, customer: Customer) -> None:
    """A proforma is not a fiscal document and nobody owes anything on it, `confermata`
    included -- the state closest to an emission that is not one (slice 3 §5)."""
    _invoice(db_session, customer, tipo="proforma", stato="confermata")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


def test_a_soft_deleted_invoice_is_not_a_receivable(
    db_session: Session, customer: Customer
) -> None:
    row = _invoice(db_session, customer)
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


# --- scaduto ------------------------------------------------------------------------


def test_scaduto_is_the_subset_past_its_due_date(db_session: Session, customer: Customer) -> None:
    """§5.2: "Scaduto" is a **subset** of "Da incassare", shown as one -- indented beneath
    it, never as a second addable line."""
    yesterday = today_local() - timedelta(days=1)
    tomorrow = today_local() + timedelta(days=1)
    _invoice(db_session, customer, totale="1220.00", data_scadenza=yesterday)
    _invoice(db_session, customer, totale="610.00", data_scadenza=tomorrow)

    repo = InvoiceRepository(db_session)
    assert repo.sum_scaduto() == Decimal("1220.00")
    assert repo.sum_da_incassare() == Decimal("1830.00")
    assert repo.sum_scaduto() <= repo.sum_da_incassare()


def test_an_invoice_due_today_is_not_yet_overdue(db_session: Session, customer: Customer) -> None:
    """`data_scadenza < oggi`, strictly. Due today is due today."""
    _invoice(db_session, customer, data_scadenza=today_local())
    assert InvoiceRepository(db_session).sum_scaduto() == Decimal("0.00")


def test_an_invoice_with_no_due_date_is_never_overdue(
    db_session: Session, customer: Customer
) -> None:
    """`data_scadenza` is nullable. `NULL < today` is NULL, not true -- but relying on
    three-valued logic silently is how the opposite gets implemented by accident, so it
    has a test."""
    _invoice(db_session, customer, data_scadenza=None)
    assert InvoiceRepository(db_session).sum_scaduto() == Decimal("0.00")


def test_a_paid_invoice_past_its_due_date_is_not_scaduto(
    db_session: Session, customer: Customer
) -> None:
    """ "Scaduto" is a subset of "Da incassare", which means it carries every one of that
    figure's filters and not only the date -- money already in the bank is nobody's
    arrears."""
    _invoice(
        db_session,
        customer,
        stato_pagamento="incassato",
        data_scadenza=today_local() - timedelta(days=30),
    )
    assert InvoiceRepository(db_session).sum_scaduto() == Decimal("0.00")


def test_overdue_is_measured_against_the_emitters_day(
    db_session: Session, customer: Customer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one clock, asserted at the instant where the three candidate clocks disagree.

    Frozen at 00:30 in Rome on 1 January 2026, which is 23:30 UTC on 31 December 2025. The
    two invoices below then separate every spelling of "today" this codebase could use:

      * `today_local()` -- 2026-01-01 -- makes the 31 December row overdue and the
        1 January row not. That is the answer asserted.
      * `CURRENT_DATE` is the *database server's* day, which is the real one and months
        later, so both rows would be overdue.
      * a bare `date.today()` runs in the process's zone (UTC in the API image), giving
        2025-12-31, so **neither** row would be overdue.

    Three implementations, three different totals, one assertion.
    """
    congela(monkeypatch)
    _invoice(db_session, customer, totale="1220.00", data_scadenza=OGGI_DEL_PROCESSO)
    _invoice(db_session, customer, totale="610.00", data_scadenza=OGGI_IN_ITALIA)

    repo = InvoiceRepository(db_session)
    assert repo.sum_scaduto() == Decimal("1220.00")
    assert repo.count_scadute_non_incassate() == 1


# --- counts -------------------------------------------------------------------------


def test_count_emesse_in_periodo_counts_by_data_emissione(
    db_session: Session, customer: Customer
) -> None:
    _invoice(db_session, customer, data_emissione=date(2026, 3, 10))
    _invoice(db_session, customer, data_emissione=date(2026, 3, 31))
    _invoice(db_session, customer, data_emissione=date(2026, 4, 1))
    assert (
        InvoiceRepository(db_session).count_emesse_in_periodo(date(2026, 3, 1), date(2026, 3, 31))
        == 2
    )


def test_count_emesse_in_periodo_counts_the_same_set_revenue_sums(
    db_session: Session, customer: Customer
) -> None:
    """A count and a sum that describe different sets is the defect §5.2 is guarding
    against: "6 fatture emesse" beside a revenue figure that includes a seventh, or a
    proforma."""
    _invoice(db_session, customer, data_emissione=date(2026, 3, 10))
    _invoice(db_session, customer, data_emissione=date(2026, 3, 11), stato="bozza")
    _invoice(db_session, customer, data_emissione=date(2026, 3, 12), stato="annullata")
    _invoice(
        db_session, customer, data_emissione=date(2026, 3, 13), tipo="proforma", stato="confermata"
    )
    deleted = _invoice(db_session, customer, data_emissione=date(2026, 3, 14))
    deleted.deleted_at = datetime.now(UTC)
    db_session.flush()

    assert (
        InvoiceRepository(db_session).count_emesse_in_periodo(date(2026, 3, 1), date(2026, 3, 31))
        == 1
    )


def _seeded_stages(db_session: Session) -> dict[str, UUID]:
    service = PipelineService(db_session)
    service.seed_defaults(ADMIN)
    return {s.code: s.id for s in service.list() if s.code is not None}


def _deal(db_session: Session, customer: Customer, nome: str, stage_id: UUID) -> Deal:
    deal = Deal(
        nome=nome,
        customer_id=customer.id,
        pipeline_stage_id=stage_id,
        probabilita=50,
        custom_fields={},
    )
    db_session.add(deal)
    db_session.flush()
    return deal


def test_the_signal_counts_deals_invoiced_but_still_open(
    db_session: Session, customer: Customer
) -> None:
    """§6.2's second signal. A `COUNT` across a join, which §3 permits; and it counts
    **deals**, not invoices, because the drill-through lists deals -- so two invoices on one
    open deal is one signal, not two."""
    stages = _seeded_stages(db_session)
    open_deal = _deal(db_session, customer, "Aperto", stages["lead"])
    won_deal = _deal(db_session, customer, "Vinto", stages["vinto"])

    _invoice(db_session, customer, deal_id=open_deal.id)
    _invoice(db_session, customer, deal_id=open_deal.id)
    _invoice(db_session, customer, deal_id=won_deal.id)

    assert InvoiceRepository(db_session).count_deals_invoiced_not_won() == 1


def test_the_signal_ignores_an_invoice_that_never_became_a_document(
    db_session: Session, customer: Customer
) -> None:
    """A draft on an open deal is the ordinary state of a deal being worked, not an
    inconsistency. Only an *issued* invoice makes "fatturato ma non vinto" true."""
    stages = _seeded_stages(db_session)
    open_deal = _deal(db_session, customer, "Aperto", stages["lead"])
    _invoice(db_session, customer, deal_id=open_deal.id, stato="bozza")
    _invoice(db_session, customer, deal_id=open_deal.id, tipo="proforma", stato="confermata")

    assert InvoiceRepository(db_session).count_deals_invoiced_not_won() == 0


def test_the_signal_ignores_a_deleted_deal_and_a_deleted_invoice(
    db_session: Session, customer: Customer
) -> None:
    stages = _seeded_stages(db_session)
    gone = _deal(db_session, customer, "Cancellato", stages["lead"])
    _invoice(db_session, customer, deal_id=gone.id)
    gone.deleted_at = datetime.now(UTC)

    still_open = _deal(db_session, customer, "Aperto", stages["lead"])
    unlinked = _invoice(db_session, customer, deal_id=still_open.id)
    unlinked.deleted_at = datetime.now(UTC)
    db_session.flush()

    assert InvoiceRepository(db_session).count_deals_invoiced_not_won() == 0


def test_the_signal_is_about_open_deals_and_not_lost_ones(
    db_session: Session, customer: Customer
) -> None:
    """`tipo = 'open'`, not `tipo <> 'won'`. The drill-through is a list of deals to go and
    win -- "the stage you forgot to move" -- and an invoiced deal parked on `perso` is a
    different problem with a different remedy, which this signal must not silently absorb.
    """
    stages = _seeded_stages(db_session)
    lost = _deal(db_session, customer, "Perso", stages["perso"])
    _invoice(db_session, customer, deal_id=lost.id)

    assert InvoiceRepository(db_session).count_deals_invoiced_not_won() == 0


def test_an_invoice_with_no_deal_is_not_a_signal(db_session: Session, customer: Customer) -> None:
    """`deal_id` is nullable and most invoices in a real register carry one; an inner join
    is what keeps the unlinked ones out, and a left join added later would count them all.
    """
    _invoice(db_session, customer, deal_id=None)
    assert InvoiceRepository(db_session).count_deals_invoiced_not_won() == 0


def test_the_overdue_signal_counts_invoices(db_session: Session, customer: Customer) -> None:
    """§6.2's fourth signal. It counts and **sends nothing** -- it is the candidate list of
    slice 5 §7.1's reminders, counted."""
    yesterday = today_local() - timedelta(days=1)
    _invoice(db_session, customer, data_scadenza=yesterday)
    _invoice(db_session, customer, data_scadenza=yesterday, stato_pagamento="incassato")
    assert InvoiceRepository(db_session).count_scadute_non_incassate() == 1


def test_the_overdue_signal_and_the_overdue_sum_are_one_predicate(
    db_session: Session, customer: Customer
) -> None:
    """The card and its drill-through are the same predicate, not two calculations. Here
    the two are a count and a sum over the same rows, so the cheapest way to keep them
    honest is to assert that every row one admits the other admits too."""
    yesterday = today_local() - timedelta(days=1)
    _invoice(db_session, customer, totale="1220.00", data_scadenza=yesterday)
    _invoice(db_session, customer, totale="610.00", data_scadenza=yesterday)
    _invoice(db_session, customer, totale="100.00", data_scadenza=today_local())
    _invoice(db_session, customer, totale="100.00", data_scadenza=None)
    _invoice(db_session, customer, totale="100.00", data_scadenza=yesterday, stato="bozza")

    repo = InvoiceRepository(db_session)
    assert repo.count_scadute_non_incassate() == 2
    assert repo.sum_scaduto() == Decimal("1830.00")


# -- one customer's receivables, the rows behind the figure -----------------------


def test_unpaid_for_customer_returns_the_rows_da_incassare_sums(
    db_session: Session, customer: Customer
) -> None:
    """The list and the total describe the same set, which is the whole reason this method
    shares `_receivable_filter()` rather than restating it.

    Asserted as an identity between the two -- the sum of the listed rows against the
    aggregate -- and not against a literal, so a clause added to one side and not the other
    fails here whichever side was edited.
    """
    _invoice(db_session, customer, totale="1220.00", data_scadenza=today_local())
    _invoice(db_session, customer, totale="610.00", data_scadenza=None)
    _invoice(db_session, customer, totale="100.00", stato_pagamento="incassato")
    _invoice(db_session, customer, totale="100.00", stato="bozza")
    _invoice(db_session, customer, totale="100.00", tipo="proforma", stato="bozza")

    repo = InvoiceRepository(db_session)
    rows = repo.unpaid_for_customer(customer.id, limit=50)
    assert sum(row.totale for row in rows) == repo.sum_da_incassare()
    assert len(rows) == 2


def test_unpaid_for_customer_excludes_another_customers_invoice(db_session: Session) -> None:
    """The one clause `sum_da_incassare` does not have. Without it the briefing for one
    customer would open with somebody else's unpaid invoices."""
    mine = Customer(ragione_sociale="Mio Cliente", nazione="IT", custom_fields={})
    theirs = Customer(ragione_sociale="Altro Cliente", nazione="IT", custom_fields={})
    db_session.add_all([mine, theirs])
    db_session.flush()
    _invoice(db_session, mine, totale="1220.00")
    _invoice(db_session, theirs, totale="999.00")

    rows = InvoiceRepository(db_session).unpaid_for_customer(mine.id, limit=50)
    assert [row.totale for row in rows] == [Decimal("1220.00")]


def test_unpaid_for_customer_excludes_a_soft_deleted_invoice(
    db_session: Session, customer: Customer
) -> None:
    row = _invoice(db_session, customer, totale="1220.00")
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert InvoiceRepository(db_session).unpaid_for_customer(customer.id, limit=50) == []


def test_unpaid_for_customer_orders_by_deadline_with_the_undated_row_last(
    db_session: Session, customer: Customer
) -> None:
    """Oldest deadline first, and the one with no deadline at the bottom.

    Nulls last is spelled out in the query rather than inherited, because Postgres's own
    default flips with the sort direction -- an ordering whose meaning changes when
    somebody reverses it is an ordering nobody can reason about. The undated row is
    inserted *first* so a query with no ordering at all, or one relying on insertion
    order, fails here.
    """
    _invoice(db_session, customer, totale="100.00", data_scadenza=None)
    _invoice(db_session, customer, totale="300.00", data_scadenza=today_local() + timedelta(days=9))
    _invoice(db_session, customer, totale="200.00", data_scadenza=today_local() - timedelta(days=9))

    rows = InvoiceRepository(db_session).unpaid_for_customer(customer.id, limit=50)
    assert [row.totale for row in rows] == [
        Decimal("200.00"),
        Decimal("300.00"),
        Decimal("100.00"),
    ]


def test_unpaid_for_customer_honours_its_limit(db_session: Session, customer: Customer) -> None:
    """The limit is required and has no default: this list is rendered into an MCP prompt,
    and its cost is paid in the model's context window on every render. A method that
    defaulted it would be spending a budget nobody set."""
    for day in range(5):
        _invoice(
            db_session,
            customer,
            totale="100.00",
            data_scadenza=today_local() + timedelta(days=day),
        )
    assert len(InvoiceRepository(db_session).unpaid_for_customer(customer.id, limit=2)) == 2
