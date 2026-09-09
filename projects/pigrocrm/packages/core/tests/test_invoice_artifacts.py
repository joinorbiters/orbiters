"""`produce_artifacts`: the PDF for every invoice type, and the XML alongside it once
a fattura has a number.

Task 13 shipped `produce_artifacts` with no test of its own anywhere in the repo. This
file exists because of two real defects found while building the REST surface on top
of it (task 14): it returned a single `InvoiceArtifact` where every caller needs the
whole result of one call, and it could not render a proforma's PDF at all -- it always
read the frozen, `issue`-only view (`_for_export`), which a proforma never populates.
"""

import subprocess
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.schemas import DocumentListQuery
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.models import Invoice
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
            ragione_sociale="Studio Rossi",
            partita_iva="01234567890",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Vittorio Veneto 12",
            cap="20124",
            comune="Milano",
            provincia="MI",
            nazione="IT",
            email="mario@example.com",
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
        cap="EC1V 9HL",
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
    # And the document's own timeline says why it went, the way a delete from the
    # documents surface would.
    kinds = [a.kind for a in ActivityService(db_session).timeline("document", pdf.document_id)]
    assert "deleted" in kinds


def test_a_proforma_consumed_between_the_read_and_the_write_is_a_conflict(
    service: InvoiceService,
    db_session: Session,
    storage: LocalFileStorage,
    customer_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race `soft_delete`'s `IntegrityError` handler was written for (ORB-57): the
    pre-check reads `confermata`, an emission consumes the proforma while the delete is
    in flight, and `ck_invoices_no_delete_once_consumed` refuses the `UPDATE`. The
    handler could never run: `ActivityService.record` flushes, so the constraint fired
    inside `record`, before the `try`, and the caller got a raw `IntegrityError` on a
    session that still needed a rollback. The refusal has to be the domain `Conflict`
    the handler promises, the session has to come back usable, and nothing of the
    delete may survive, the PDF's archiving included, since that travels in the same
    transaction.

    Emulated on the test's own connection rather than from a second session: the
    `db_session` fixture holds every row inside one outer transaction that no other
    connection can see. The raw `UPDATE` slipped in after the repository's read leaves
    the row in exactly the state a committed emission would, with the service still
    holding the stale `confermata` it read. It is undone by the rollback the handler
    performs, so afterwards the proforma reads as it did before the attempt.
    """
    proforma_id = _confirmed_proforma(service, customer_id)
    (pdf,) = service.produce_artifacts(proforma_id, ADMIN)
    documents = DocumentService(db_session, storage)
    read = service.repo.get

    def read_then_lose_the_race(invoice_id: UUID) -> Invoice | None:
        invoice = read(invoice_id)
        # What `issue` does to a proforma, reduced to the one column the CHECK reads.
        db_session.execute(
            text("UPDATE invoices SET stato = 'consumata' WHERE id = :id"), {"id": invoice_id}
        )
        return invoice

    monkeypatch.setattr(service.repo, "get", read_then_lose_the_race)
    with pytest.raises(Conflict) as caught:
        service.soft_delete(proforma_id, ADMIN)
    assert "emesso nel frattempo" in caught.value.message
    monkeypatch.undo()

    # Usable session, whole rollback: neither the invoice nor its PDF is archived.
    proforma = db_session.get(Invoice, proforma_id)
    assert proforma is not None and proforma.deleted_at is None
    assert service.get(proforma_id, ADMIN).id == proforma_id
    assert documents.get(pdf.document_id, ADMIN).id == pdf.document_id
    listed = documents.list(DocumentListQuery(customer_id=customer_id), ADMIN).items
    assert pdf.document_id in [item.id for item in listed]


# --- the accrual period and the proforma's own date on the PDF (ORB-61, ORB-63) -------


def test_the_pdf_prints_the_accrual_period_when_the_document_has_one(
    service: InvoiceService,
    customer_id: UUID,
    db_session: Session,
    storage: LocalFileStorage,
    extract_pdf_text: Callable[[LocalFileStorage, Session, UUID], str],
) -> None:
    from datetime import date

    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            causale="Consulenza",
            competenza_da=date(2026, 8, 1),
            competenza_a=date(2026, 8, 31),
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("1000.00"))],
        ),
        ADMIN,
    )
    invoice_id = service.issue(draft.id, InvoiceIssue(), ADMIN).id
    pdf, _xml = service.produce_artifacts(invoice_id, ADMIN)
    testo = extract_pdf_text(storage, db_session, pdf.document_id)
    assert "Periodo di competenza: 01/08/2026 - 31/08/2026" in testo


def test_a_document_without_a_period_prints_no_period_line(
    service: InvoiceService,
    customer_id: UUID,
    db_session: Session,
    storage: LocalFileStorage,
    extract_pdf_text: Callable[[LocalFileStorage, Session, UUID], str],
) -> None:
    invoice_id = _issue(service, customer_id)
    pdf, _xml = service.produce_artifacts(invoice_id, ADMIN)
    assert "Periodo di competenza" not in extract_pdf_text(storage, db_session, pdf.document_id)


def test_the_proforma_pdf_prints_its_own_date_and_its_period_not_the_render_day(
    service: InvoiceService,
    customer_id: UUID,
    db_session: Session,
    storage: LocalFileStorage,
    extract_pdf_text: Callable[[LocalFileStorage, Session, UUID], str],
) -> None:
    """ORB-63: PROV-2026-0002 rendered on 2026-09-09 said 2026-09-09 and would have
    said tomorrow tomorrow. The date printed is the one stored on the row, which the
    sender chose, and a re-render after moving it prints the moved date."""
    from datetime import date

    from pigrocrm.core.invoices.schemas import InvoiceUpdate

    proforma = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            tipo="proforma",
            data_emissione=date(2025, 12, 31),
            competenza_da=date(2025, 12, 1),
            competenza_a=date(2025, 12, 31),
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    (pdf,) = service.produce_artifacts(proforma.id, ADMIN)
    testo = extract_pdf_text(storage, db_session, pdf.document_id)
    assert "Data: 2025-12-31" in testo
    assert "Periodo di competenza: 01/12/2025 - 31/12/2025" in testo

    # A proforma's PDF has no expected hash (it is not a fiscal identity), so the
    # re-render lands as version 2 of the same document; `download` serves the current
    # version, which is what the customer receives, so that is what is read back here.
    service.update(proforma.id, InvoiceUpdate(data_emissione=date(2026, 1, 2)), ADMIN)
    (again,) = service.produce_artifacts(proforma.id, ADMIN)
    assert again.document_id == pdf.document_id
    assert again.version_numero == 2
    data, _, _ = service.download(proforma.id, "pdf", ADMIN)
    testo = subprocess.run(
        ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
    ).stdout.decode("utf-8", errors="replace")
    assert "Data: 2026-01-02" in testo
    assert "Data: 2025-12-31" not in testo
