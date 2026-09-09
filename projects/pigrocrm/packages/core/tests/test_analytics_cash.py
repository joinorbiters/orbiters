"""The year as cash (`AnalyticsService.cash_overview`) and the economic overview that
lays the fiscal estimate over it."""

from decimal import Decimal
from uuid import UUID

import pytest
from periodo_fiscale import OGGI
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.invoices.schemas import PaymentState
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage
from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.schemas import CostCreate

ADMIN = Actor(id=None, type="system", role="admin")
COLLABORATORE = Actor(id=None, type="mcp", role="collaboratore")


def _invoice_of(session: Session, line_id: UUID) -> UUID:
    invoice_id: UUID = session.execute(
        text("SELECT invoice_id FROM invoice_lines WHERE id = :line"), {"line": line_id}
    ).scalar_one()
    return invoice_id


@pytest.fixture
def cost_category_id(db_session: Session) -> UUID:
    from pigrocrm.core.timetracking.categories import CostCategoryService
    from pigrocrm.core.timetracking.schemas import CostCategoryCreate

    return (
        CostCategoryService(db_session)
        .create_cost_category(CostCategoryCreate(nome=f"Cassa test {OGGI.isoformat()}"), ADMIN)
        .id
    )


def test_the_year_adds_up_month_by_month_and_costs_are_not_revenue(
    db_session: Session,
    local_storage: LocalFileStorage,
    issued_invoice_line_id: UUID,
    cost_category_id: UUID,
) -> None:
    # The fixture already provisioned the fiscal and emitter profiles the service needs.
    service = InvoiceService(db_session, local_storage)
    invoice_id = _invoice_of(db_session, issued_invoice_line_id)
    paid = service.set_payment_state(
        invoice_id, PaymentState(stato_pagamento="incassato", data_incasso=OGGI), ADMIN
    )
    CostService(db_session).create(
        CostCreate(
            category_id=cost_category_id,
            data=OGGI,
            importo=Decimal("120.00"),
            descrizione="Hosting",
        ),
        ADMIN,
    )

    overview = AnalyticsService(db_session).cash_overview(OGGI.year, COLLABORATORE)
    assert overview.anno == OGGI.year
    assert len(overview.mesi) == 12
    month = next(m for m in overview.mesi if m.mese == OGGI.month)
    assert month.incassato == Decimal(str(paid.totale))
    assert month.costi == Decimal("120.00")
    assert month.da_incassare == Decimal("0.00")
    # Shares of the tallest stack: both present, and the stack adds up to the whole.
    assert month.quote_andamento["incassato"] > 0 and month.quote_andamento["costi"] > 0
    assert abs(month.quote_andamento["incassato"] + month.quote_andamento["costi"] - 1.0) < 1e-9
    assert sum(m.incassato for m in overview.mesi) == overview.incassato
    assert overview.proiettato == overview.incassato  # nothing pending, nothing drafted
    assert overview.lordo_effettivo == overview.incassato - Decimal("120.00")
    assert overview.lordo_proiettato == overview.lordo_effettivo


def test_an_issued_unpaid_invoice_is_projected_not_collected(
    db_session: Session, issued_invoice_line_id: UUID
) -> None:
    invoice_id = _invoice_of(db_session, issued_invoice_line_id)
    totale = db_session.execute(
        text("select totale from invoices where id = :id"), {"id": str(invoice_id)}
    ).scalar_one()
    overview = AnalyticsService(db_session).cash_overview(OGGI.year, COLLABORATORE)
    assert overview.incassato == Decimal("0.00")
    assert overview.da_incassare == Decimal(str(totale))
    assert overview.proiettato == Decimal(str(totale))


def test_a_draft_counts_as_a_draft_and_a_paid_invoice_never_twice(
    db_session: Session, draft_invoice_line_id: UUID
) -> None:
    overview = AnalyticsService(db_session).cash_overview(OGGI.year, COLLABORATORE)
    assert overview.bozze > Decimal("0.00")
    assert overview.incassato == Decimal("0.00")
    assert overview.da_incassare == Decimal("0.00")


def test_a_proforma_is_projected_in_the_month_of_its_own_date(
    db_session: Session, local_storage: LocalFileStorage, draft_invoice_line_id: UUID
) -> None:
    """ORB-63 gives a proforma a document date, and `monthly_bozze` buckets by it: a
    proforma the sender dated in another month is that month's projected money, whatever
    day it was typed in. The fattura draft beside it has no date until `issue` and stays
    in the month it was created, which is this one."""
    from datetime import date
    from decimal import Decimal as D

    from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceLineIn

    draft_id = _invoice_of(db_session, draft_invoice_line_id)
    service = InvoiceService(db_session, local_storage)
    customer_id = service.get(draft_id, ADMIN).customer_id
    altro_mese = 1 if OGGI.month != 1 else 2
    service.create(
        InvoiceCreate(
            customer_id=customer_id,
            tipo="proforma",
            data_emissione=date(OGGI.year, altro_mese, 15),
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=D("333.00"))],
        ),
        ADMIN,
    )
    overview = AnalyticsService(db_session).cash_overview(OGGI.year, COLLABORATORE)
    by_month = {m.mese: m.bozze for m in overview.mesi}
    assert by_month[altro_mese] == D("333.00")
    assert by_month[OGGI.month] == overview.bozze - D("333.00")
    assert by_month[OGGI.month] > D("0.00")


def test_the_overview_keeps_the_estimate_from_everyone_but_an_admin_with_a_profile(
    db_session: Session,
) -> None:
    service = AnalyticsService(db_session)
    assert service.economic_overview(OGGI.year, COLLABORATORE).fiscale is None
    # An admin without a fiscal profile: cash, and no estimate rather than an error.
    without = service.economic_overview(OGGI.year, ADMIN)
    assert without.fiscale is None and without.netto_effettivo is None


def test_the_estimate_follows_collected_and_projected_revenue(
    db_session: Session, issued_invoice_line_id: UUID
) -> None:
    from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
    from pigrocrm.core.fiscal.service import FiscalProfileService

    FiscalProfileService(db_session).upsert(
        FiscalProfileUpsert(
            codice_regime="RF19",
            coefficiente_redditivita=Decimal("67.00"),
            aliquota_imposta_sostitutiva=Decimal("5.00"),
            aliquota_inps=Decimal("26.07"),
        ),
        ADMIN,
    )
    overview = AnalyticsService(db_session).economic_overview(OGGI.year, ADMIN)
    assert overview.fiscale is not None and overview.fiscale_proiettato is not None
    # Nothing collected yet: the actual estimate is on zero, the projected one on the
    # issued invoice, and the two nets follow.
    assert overview.fiscale.ricavi == Decimal("0.00")
    assert overview.fiscale_proiettato.ricavi == overview.cassa.proiettato > Decimal("0.00")
    assert overview.fiscale_proiettato.totale_dovuto == (
        overview.fiscale_proiettato.imposta_sostitutiva + overview.fiscale_proiettato.contributi
    )
    assert overview.netto_proiettato == (
        overview.cassa.lordo_proiettato - overview.fiscale_proiettato.totale_dovuto
    )
    assert (
        overview.netto_effettivo == overview.cassa.lordo_effettivo - overview.fiscale.totale_dovuto
    )
