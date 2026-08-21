"""`produce_artifacts`: the PDF for every invoice type, and the XML alongside it once
a fattura has a number.

Task 13 shipped `produce_artifacts` with no test of its own anywhere in the repo. This
file exists because of two real defects found while building the REST surface on top
of it (task 14): it returned a single `InvoiceArtifact` where every caller needs the
whole result of one call, and it could not render a proforma's PDF at all -- it always
read the frozen, `issue`-only view (`_for_export`), which a proforma never populates.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceIssue, InvoiceLineIn
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")


@pytest.fixture
def storage(tmp_path) -> LocalFileStorage:  # type: ignore[no-untyped-def]
    return LocalFileStorage(tmp_path / "documents")


@pytest.fixture
def service(db_session: Session, storage: LocalFileStorage) -> InvoiceService:
    FiscalProfileService(db_session).upsert(FiscalProfileUpsert(codice_regime="RF19"), ADMIN)
    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Humancraft di Ivan Sala",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Vittorio Veneto 12",
            cap="20124",
            comune="Milano",
            provincia="MI",
            nazione="IT",
            email="someone@example.com",
        ),
        ADMIN,
    )
    return InvoiceService(db_session, storage)


@pytest.fixture
def customer_id(db_session: Session) -> UUID:
    customer = Customer(
        ragione_sociale="Acme S.r.l.",
        partita_iva="12345678901",
        codice_sdi="ABCDEFG",
        indirizzo="Corso Italia 5",
        cap="00100",
        comune="Roma",
        provincia="RM",
        nazione="IT",
    )
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _issue(service: InvoiceService, customer_id: UUID) -> UUID:
    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            causale="Consulenza",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("1000.00"))],
        ),
        ADMIN,
    )
    return service.issue(draft.id, InvoiceIssue(), ADMIN).id


def _confirmed_proforma(service: InvoiceService, customer_id: UUID) -> UUID:
    proforma = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    service.confirm_proforma(proforma.id, ADMIN)
    return proforma.id


def test_a_confirmed_proforma_produces_only_a_pdf(
    service: InvoiceService, customer_id: UUID
) -> None:
    """A proforma is not a fiscal document (`export_xml` refuses one on the row's own
    state), but the PDF is a live view built from the current customer/emitter/fiscal
    data -- there is nothing frozen to read back, since only `issue` writes
    `snapshot`/`anno`/`numero`."""
    proforma_id = _confirmed_proforma(service, customer_id)
    artifacts = service.produce_artifacts(proforma_id, ADMIN)
    assert [a.kind for a in artifacts] == ["pdf"]
    assert artifacts[0].content_type == "application/pdf"


def test_an_issued_fattura_produces_both_the_pdf_and_the_xml(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    artifacts = service.produce_artifacts(invoice_id, ADMIN)
    assert [a.kind for a in artifacts] == ["pdf", "xml"]
    invoice = service.get(invoice_id, ADMIN)
    assert invoice.xml_hash_sha256 == artifacts[1].hash_sha256


def test_producing_artifacts_twice_is_idempotent_for_a_proforma(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    proforma_id = _confirmed_proforma(service, customer_id)
    first = service.produce_artifacts(proforma_id, ADMIN)
    second = service.produce_artifacts(proforma_id, ADMIN)
    assert first[0].hash_sha256 == second[0].hash_sha256
    versions = db_session.execute(
        text("SELECT count(*) FROM document_versions WHERE document_id = :id"),
        {"id": first[0].document_id},
    ).scalar_one()
    assert versions == 1


def test_producing_artifacts_twice_is_idempotent_for_an_issued_fattura(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    first = service.produce_artifacts(invoice_id, ADMIN)
    second = service.produce_artifacts(invoice_id, ADMIN)
    assert [a.hash_sha256 for a in first] == [a.hash_sha256 for a in second]
    for artifact in first:
        versions = db_session.execute(
            text("SELECT count(*) FROM document_versions WHERE document_id = :id"),
            {"id": artifact.document_id},
        ).scalar_one()
        assert versions == 1
