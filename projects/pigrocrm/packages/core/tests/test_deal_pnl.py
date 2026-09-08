"""§7.1's five decisions and §7.3's three states."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.errors import NotFound
from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.schemas import CostCreate, TimeEntryCreate
from pigrocrm.core.timetracking.service import TimeEntryService

READER = Actor(id=None, type="user", role="readonly")
WRITER = Actor(id=None, type="user", role="collaboratore")


def test_an_incomplete_deal_does_not_lie(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """**Criterion 6.** An open deal with 20 hours and no invoice: revenue `0.00`, margin
    percentage `null` (not `"0.00"`), state "in corso", and the accrued value in a field
    whose name is not `ricavi`.

    Zero per cent means "everything I earned went out in costs"; here nothing has been
    earned. Two different facts, and the report does not flatten them."""
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=date(2026, 3, 4),
            ore=Decimal("20.00"),
            descrizione="Sviluppo",
            tariffa_applicata=Decimal("100.000000"),
            costo_applicato=Decimal("30.000000"),
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.ricavi == Decimal("0.00")
    assert pnl.margine_percentuale is None
    assert pnl.stato == "in corso"
    assert pnl.valore_maturato == Decimal("2000.00")
    assert pnl.costo_lavoro == Decimal("600.00")
    assert pnl.margine_lordo == Decimal("-600.00")
    # The accrued value is not revenue and lives under a different heading.
    assert "valore_maturato" in pnl.model_dump() and pnl.valore_maturato != pnl.ricavi
    # `null` in the JSON too, not the string "0.00": the field is what a client reads,
    # and a serialiser that filled it in would undo the distinction above.
    assert pnl.model_dump(mode="json")["margine_percentuale"] is None


def test_costs_of_an_uninvoiced_deal_still_appear(
    db_session: Session, seeded_deal_id: UUID, seeded_category_id: UUID
) -> None:
    """the previous system's `projectCostRows` started from `offers.filter(offerKeysWithInvoices.has(...))`,
    so the expenses of a job in progress were invisible to every summary. Every deal has
    its own P&L here, invoiced or not, with the **state** beside it instead of the
    exclusion (§7.3)."""
    CostService(db_session).create(
        CostCreate(
            deal_id=seeded_deal_id,
            category_id=seeded_category_id,
            data=date(2026, 3, 1),
            importo=Decimal("500.00"),
            descrizione="Licenze",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.costi_diretti == Decimal("500.00")
    assert pnl.margine_lordo == Decimal("-500.00")


def test_labour_cost_includes_non_billable_hours(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """An internal meeting costs exactly what it would cost if it were billed, and
    excluding it would make the deal that demanded more of them look more profitable."""
    service = TimeEntryService(db_session)
    for fatturabile in (True, False):
        service.create(
            TimeEntryCreate(
                deal_id=seeded_deal_id,
                user_id=seeded_user_id,
                data=date(2026, 3, 4),
                ore=Decimal("2.00"),
                descrizione="x",
                fatturabile=fatturabile,
                tariffa_applicata=Decimal("100.000000"),
                costo_applicato=Decimal("30.000000"),
            ),
            WRITER,
        )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.costo_lavoro == Decimal("120.00")
    # But only the billable hour contributes accrued value: a non-billable hour is never
    # potential revenue.
    assert pnl.valore_maturato == Decimal("200.00")


def test_unpriced_hours_are_counted_and_excluded_never_valued_at_zero(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=date(2026, 3, 4),
            ore=Decimal("5.00"),
            descrizione="senza tariffa",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.ore_totali == Decimal("5.00")
    assert pnl.ore_senza_tariffa == 1
    assert pnl.valore_maturato == Decimal("0.00")
    assert pnl.costo_lavoro == Decimal("0.00")


def test_the_three_states(
    db_session: Session,
    seeded_deal_id: UUID,
    seeded_user_id: UUID,
    seeded_won_stage_id: UUID,
    issued_invoice_line_id: UUID,
) -> None:
    from sqlalchemy import text

    service = TimeEntryService(db_session)
    entry = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=date(2026, 3, 4),
            ore=Decimal("2.00"),
            descrizione="x",
            tariffa_applicata=Decimal("100.000000"),
        ),
        WRITER,
    )
    analytics = AnalyticsService(db_session)
    assert analytics.deal_pnl(seeded_deal_id, READER).stato == "in corso"

    deal = db_session.get(Deal, seeded_deal_id)
    assert deal is not None
    deal.pipeline_stage_id = seeded_won_stage_id
    db_session.flush()
    assert analytics.deal_pnl(seeded_deal_id, READER).stato == "da fatturare"

    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": issued_invoice_line_id, "id": entry.id},
    )
    db_session.flush()
    assert analytics.deal_pnl(seeded_deal_id, READER).stato == "chiuso"


def test_the_stamp_duty_is_not_a_deal_cost(
    db_session: Session, deal_with_bollo_invoice: UUID
) -> None:
    """Slice 3 §7.2 keeps the stamp duty out of the total and on the issuer. Making it a
    deal cost would require this slice to look inside an invoice's fiscal composition,
    which is slice 3's competence. If the user wants it in the margin they record it as
    an ordinary `cost`."""
    from sqlalchemy import text

    bollo = db_session.execute(
        text("SELECT SUM(bollo) FROM invoices WHERE deal_id = :id"),
        {"id": deal_with_bollo_invoice},
    ).scalar_one()
    assert bollo == Decimal("2.00"), "the fixture must produce an invoice bearing stamp duty"

    pnl = AnalyticsService(db_session).deal_pnl(deal_with_bollo_invoice, READER)
    assert pnl.costi_diretti == Decimal("0.00")
    # And it is not silently netted off the revenue either: `ricavi` is the imponibile,
    # whole.
    assert pnl.ricavi == Decimal("1000.00")


def test_no_path_lets_the_same_expense_in_twice(
    db_session: Session,
    seeded_deal_id: UUID,
    seeded_user_id: UUID,
    seeded_category_id: UUID,
) -> None:
    """**Criterion 4's third part.** `costs` and the labour cost are disjoint by
    construction: `costs` is money out to third parties, labour cost derives from
    `time_entries`. An external consultant who invoices you their hours is a `cost` in
    "Consulenza esterna", and their hours -- if you record them -- carry
    `costo_applicato = NULL`."""
    CostService(db_session).create(
        CostCreate(
            deal_id=seeded_deal_id,
            category_id=seeded_category_id,
            data=date(2026, 3, 1),
            importo=Decimal("1000.00"),
            descrizione="Consulente esterno",
        ),
        WRITER,
    )
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=date(2026, 3, 2),
            ore=Decimal("10.00"),
            descrizione="ore del consulente",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.costi_diretti == Decimal("1000.00")
    assert pnl.costo_lavoro == Decimal("0.00")
    assert pnl.margine_lordo == Decimal("-1000.00")


def test_margin_percentage_when_there_is_revenue(
    db_session: Session, deal_with_mixed_invoices: UUID, seeded_category_id: UUID
) -> None:
    CostService(db_session).create(
        CostCreate(
            deal_id=deal_with_mixed_invoices,
            category_id=seeded_category_id,
            data=date(2026, 3, 1),
            importo=Decimal("583.83"),
            descrizione="Licenze",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(deal_with_mixed_invoices, READER)
    assert pnl.ricavi > 0
    assert pnl.margine_percentuale is not None
    assert pnl.margine_percentuale == (pnl.margine_lordo / pnl.ricavi * Decimal(100)).quantize(
        Decimal("0.01")
    )
    # 1000.00 of margin on 1583.83 of revenue: 63.1382...% -> 63.14, two places,
    # ROUND_HALF_UP, computed once in `money.percentage_of`.
    assert pnl.margine_lordo == Decimal("1000.00")
    assert pnl.margine_percentuale == Decimal("63.14")


def test_a_deal_that_does_not_exist_is_not_an_empty_pl(db_session: Session) -> None:
    """`NotFound`, never a P&L of zeroes: a report of all-zero rows for an id nobody
    recognises is indistinguishable from a real deal on which nothing has happened."""
    missing = uuid4()
    with pytest.raises(NotFound) as caught:
        AnalyticsService(db_session).deal_pnl(missing, READER)
    assert caught.value.details["entity"] == "deal"
    assert caught.value.details["identifier"] == str(missing)


def test_a_soft_deleted_deal_is_not_readable_either(
    db_session: Session, seeded_deal_id: UUID
) -> None:
    """Same answer as `DealService.get`: the archive is reachable through the restore
    path, not through a report that would keep quoting a deal somebody archived."""
    from datetime import UTC, datetime

    deal = db_session.get(Deal, seeded_deal_id)
    assert deal is not None
    deal.deleted_at = datetime.now(UTC)
    db_session.flush()
    with pytest.raises(NotFound):
        AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
