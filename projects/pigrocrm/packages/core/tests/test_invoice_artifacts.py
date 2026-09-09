"""`produce_artifacts`: the PDF for every invoice type, and the XML alongside it once
a fattura has a number.

Task 13 shipped `produce_artifacts` with no test of its own anywhere in the repo. This
file exists because of two real defects found while building the REST surface on top
of it (task 14): it returned a single `InvoiceArtifact` where every caller needs the
whole result of one call, and it could not render a proforma's PDF at all -- it always
read the frozen, `issue`-only view (`_for_export`), which a proforma never populates.
"""

from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.schemas import DocumentListQuery
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import NotFound
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


def _non_resident_customer(db_session: Session) -> UUID:
    customer = Customer(
        ragione_sociale="Example Ltd",
        partita_iva="GB123456789",
        indirizzo="1 Old Street",
        cap="00000",  # the SdI convention for a foreign address; a real postcode is ORB-38
        comune="London",
        provincia="",
        nazione="GB",
    )
    db_session.add(customer)
    db_session.flush()
    return customer.id


def test_the_pdf_for_a_non_resident_customer_carries_the_7_ter_reference(
    service: InvoiceService,
    db_session: Session,
    storage: LocalFileStorage,
    extract_pdf_text: Callable[[LocalFileStorage, Session, UUID], str],
) -> None:
    """ORB-32, on the document the customer reads. The footer used to print the
    profile's domestic declaration whatever the lines said; it now prints the
    declaration the lines actually carry, so the PDF and the XML agree."""
    invoice_id = _issue(service, _non_resident_customer(db_session))
    pdf, _xml = service.produce_artifacts(invoice_id, ADMIN)
    testo = extract_pdf_text(storage, db_session, pdf.document_id)
    assert "7-ter" in testo
    assert "DPR 633/1972" in testo
    assert "L. 190/2014" not in testo


def test_the_pdf_for_an_italian_customer_keeps_the_domestic_declaration(
    service: InvoiceService,
    customer_id: UUID,
    db_session: Session,
    storage: LocalFileStorage,
    extract_pdf_text: Callable[[LocalFileStorage, Session, UUID], str],
) -> None:
    invoice_id = _issue(service, customer_id)
    pdf, _xml = service.produce_artifacts(invoice_id, ADMIN)
    testo = extract_pdf_text(storage, db_session, pdf.document_id)
    assert "L. 190/2014" in testo
    assert "7-ter" not in testo


# --- discarding a proforma takes its PDF with it (ORB-41) ---------------------------


def test_discarding_a_proforma_archives_its_pdf_and_keeps_the_bytes(
    service: InvoiceService,
    db_session: Session,
    storage: LocalFileStorage,
    customer_id: UUID,
) -> None:
    """The soft delete of a proforma used to stop at `invoices.deleted_at` and leave
    `pdf_document_id` pointing at a live row, so `list_documents` kept showing
    "Proforma PROV-... (PDF)" and its download kept working while `get_invoice` on the
    owner answered not found (ORB-41). The document goes with its owner, in the same
    transaction, and as a soft delete: the row and the stored bytes stay, so a restore
    of the document is still a real restore."""
    proforma_id = _confirmed_proforma(service, customer_id)
    (pdf,) = service.produce_artifacts(proforma_id, ADMIN)
    documents = DocumentService(db_session, storage)
    listed = documents.list(DocumentListQuery(customer_id=customer_id), ADMIN).items
    assert pdf.document_id in [item.id for item in listed]

    service.soft_delete(proforma_id, ADMIN)

    listed = documents.list(DocumentListQuery(customer_id=customer_id), ADMIN).items
    assert pdf.document_id not in [item.id for item in listed]
    with pytest.raises(NotFound):
        documents.get(pdf.document_id, ADMIN)
    # Reversible: the row is archived, not gone, and the bytes are still where the
    # version says they are.
    row = db_session.get(Document, pdf.document_id)
    assert row is not None and row.deleted_at is not None
    version = documents.repo.version(row.id, row.versione_corrente)
    assert version is not None
    assert storage.get(version.storage_key)[:5] == b"%PDF-"


def test_discarding_a_proforma_that_never_rendered_a_pdf_still_works(
    service: InvoiceService, customer_id: UUID
) -> None:
    """The common case: a draft discarded before anyone asked for its PDF has no
    document to archive, and the delete must not trip over the missing one."""
    proforma_id = _confirmed_proforma(service, customer_id)
    service.soft_delete(proforma_id, ADMIN)
    with pytest.raises(NotFound):
        service.get(proforma_id, ADMIN)
