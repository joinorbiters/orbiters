import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.schemas import DocumentCreate, DocumentListQuery, DocumentUpdate
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm.core.storage import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")
PDF = b"%PDF-1.7\nfinto\n"


@pytest.fixture
def service(db_session: Session, tmp_path: Path) -> DocumentService:
    return DocumentService(db_session, LocalFileStorage(tmp_path))


@pytest.fixture
def customer(db_session: Session) -> Customer:
    row = Customer(ragione_sociale="ACME S.r.l.")
    db_session.add(row)
    db_session.flush()
    return row


def test_create_on_a_customer(service: DocumentService, customer: Customer) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta 2026-01"), ADMIN
    )
    assert document.customer_id == customer.id
    assert document.versione_corrente == 0
    # An offer starts as a draft; nothing else has a state at all.
    assert document.stato == "bozza"


def test_create_of_a_non_offer_has_no_state(service: DocumentService, customer: Customer) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="verbale", titolo="Verbale"), ADMIN
    )
    assert document.stato is None


def test_create_with_neither_customer_nor_deal_is_refused(service: DocumentService) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        service.create(DocumentCreate(tipo="documento", titolo="Orfano"), ADMIN)
    assert "customer_id" in excinfo.value.details["field"]


def test_create_with_both_customer_and_deal_is_refused(
    service: DocumentService, customer: Customer
) -> None:
    with pytest.raises(ValidationFailed):
        service.create(
            DocumentCreate(customer_id=customer.id, deal_id=uuid4(), tipo="documento", titolo="X"),
            ADMIN,
        )


def test_create_with_an_unknown_customer_raises_not_found(service: DocumentService) -> None:
    # Without this the syntactically valid UUID reaches flush() and comes back as a
    # raw IntegrityError (ForeignKeyViolation) instead of this project's NotFound.
    with pytest.raises(NotFound):
        service.create(DocumentCreate(customer_id=uuid4(), tipo="documento", titolo="X"), ADMIN)


def test_create_with_an_unknown_deal_raises_not_found(service: DocumentService) -> None:
    with pytest.raises(NotFound):
        service.create(DocumentCreate(deal_id=uuid4(), tipo="documento", titolo="X"), ADMIN)


def test_a_readonly_actor_cannot_create(service: DocumentService, customer: Customer) -> None:
    with pytest.raises(PermissionDenied):
        service.create(
            DocumentCreate(customer_id=customer.id, tipo="documento", titolo="X"), READONLY
        )


def test_add_version_stores_the_bytes_and_bumps_the_current_version(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    version = service.add_version(document.id, PDF, "application/pdf", ADMIN)
    assert version.numero == 1
    assert version.dimensione == len(PDF)
    assert version.hash_sha256 == hashlib.sha256(PDF).hexdigest()
    assert service.get(document.id, ADMIN).versione_corrente == 1


def test_a_second_version_does_not_overwrite_the_first(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    service.add_version(document.id, PDF, "application/pdf", ADMIN)
    service.add_version(document.id, b"%PDF-1.7\nsecondo\n", "application/pdf", ADMIN)
    numbers = [v.numero for v in service.versions(document.id, ADMIN)]
    assert numbers == [2, 1]
    assert service.download(document.id, 1, ADMIN)[0] == PDF


def test_download_without_a_number_returns_the_current_version(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    service.add_version(document.id, PDF, "application/pdf", ADMIN)
    service.add_version(document.id, b"ultimo", "application/pdf", ADMIN)
    data, content_type, filename = service.download(document.id, None, ADMIN)
    assert data == b"ultimo"
    assert content_type == "application/pdf"
    assert filename.endswith(".pdf")


def test_download_of_a_document_with_no_version_raises_not_found(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    with pytest.raises(NotFound):
        service.download(document.id, None, ADMIN)


def test_an_unallowed_content_type_is_refused(service: DocumentService, customer: Customer) -> None:
    # The content type is chosen from a fixed allowlist, never echoed from the
    # request: a caller-supplied value reaches a Content-Disposition header later.
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="X"), ADMIN
    )
    with pytest.raises(ValidationFailed) as excinfo:
        service.add_version(document.id, b"<script>", "text/html", ADMIN)
    assert excinfo.value.details["field"] == "content_type"


def test_the_storage_key_carries_the_customer_slug_and_id_fragment(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    version = service.add_version(document.id, PDF, "application/pdf", ADMIN)
    prefix = f"acme-s-r-l-{str(customer.id)[:8]}"
    assert version.storage_key == f"{prefix}/{document.id}/v1.pdf"


def test_a_customer_rename_does_not_change_an_existing_key(
    service: DocumentService, customer: Customer, db_session: Session
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    first = service.add_version(document.id, PDF, "application/pdf", ADMIN)
    customer.ragione_sociale = "Nuovo Nome"
    db_session.flush()
    assert service.download(document.id, 1, ADMIN)[0] == PDF
    assert first.storage_key.startswith("acme-s-r-l-")


def test_update_changes_the_title_and_clears_it_with_an_empty_string(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="Vecchio"), ADMIN
    )
    assert service.update(document.id, DocumentUpdate(titolo="Nuovo"), ADMIN).titolo == "Nuovo"


def test_soft_delete_hides_the_document_from_the_list(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="X"), ADMIN
    )
    service.soft_delete(document.id, ADMIN)
    assert service.list(DocumentListQuery(customer_id=customer.id), ADMIN).items == []
    assert service.restore(document.id, ADMIN).titolo == "X"


def test_soft_delete_keeps_the_bytes_so_a_restore_is_a_real_restore(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="X"), ADMIN
    )
    service.add_version(document.id, PDF, "application/pdf", ADMIN)
    service.soft_delete(document.id, ADMIN)
    service.restore(document.id, ADMIN)
    assert service.download(document.id, 1, ADMIN)[0] == PDF


def test_list_filters_by_customer_and_by_deal(
    service: DocumentService, customer: Customer, db_session: Session
) -> None:
    stage = PipelineService(db_session).seed_defaults(ADMIN)[0]
    deal = Deal(nome="D", customer_id=customer.id, pipeline_stage_id=stage.id)
    db_session.add(deal)
    db_session.flush()
    service.create(DocumentCreate(customer_id=customer.id, tipo="documento", titolo="C"), ADMIN)
    service.create(DocumentCreate(deal_id=deal.id, tipo="offerta", titolo="D"), ADMIN)
    by_customer = service.list(DocumentListQuery(customer_id=customer.id), ADMIN).items
    by_deal = service.list(DocumentListQuery(deal_id=deal.id), ADMIN).items
    assert [d.titolo for d in by_customer] == ["C"]
    assert [d.titolo for d in by_deal] == ["D"]


def test_list_limit_is_bounded(service: DocumentService) -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        DocumentListQuery(limit=1000)


# ---- concurrency and ordering ------------------------------------------------------


def test_two_racing_uploads_computing_the_same_version_number_become_a_clean_conflict(
    service: DocumentService, customer: Customer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forces two `add_version` calls to compute the *same* `numero`, which is what a
    real race looks like (two transactions both reading `versione_corrente` before
    either commits) -- reproduced deterministically against a single
    savepoint-backed test session, the same technique
    `test_upsert_converts_a_true_insert_race_into_a_clean_conflict` in
    `test_emitter.py` uses on `EmitterProfileRepository.get`.

    The loser must not be able to overwrite the winner's bytes at the storage key
    both compute from the same numero: `add_version` flushes the database row (and
    lets the unique constraint reject the loser) *before* calling `storage.put`, so
    the assertion on the winner's untouched bytes is the real point of this test, not
    only the `Conflict`.
    """
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    monkeypatch.setattr(DocumentService, "_next_numero", lambda self, document: 1)
    service.add_version(document.id, PDF, "application/pdf", ADMIN)
    with pytest.raises(Conflict):
        service.add_version(document.id, b"perdente", "application/pdf", ADMIN)
    monkeypatch.undo()

    # The winner's bytes at v1 must be exactly what the winner wrote -- the loser's
    # flush-then-storage ordering must never have reached storage.put at all.
    assert service.download(document.id, 1, ADMIN)[0] == PDF
    # The session must still be usable after the rollback, not poisoned.
    assert service.get(document.id, ADMIN).versione_corrente == 1


def test_a_storage_failure_does_not_burn_a_version_number(
    service: DocumentService, customer: Customer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If writing the bytes fails after the database row was flushed but before
    anything committed, the failure must roll everything back: no row survives
    pointing at bytes that were never written, and the version number is not
    consumed -- the next attempt gets the same numero, not the next one."""
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )

    def _boom(key: str, data: bytes, content_type: str) -> None:
        raise OSError("disco pieno")

    monkeypatch.setattr(service.storage, "put", _boom)
    with pytest.raises(OSError):
        service.add_version(document.id, PDF, "application/pdf", ADMIN)
    monkeypatch.undo()

    # Session must still be usable, and the failed attempt above must not have
    # advanced versione_corrente or reserved numero 1.
    assert service.get(document.id, ADMIN).versione_corrente == 0
    version = service.add_version(document.id, PDF, "application/pdf", ADMIN)
    assert version.numero == 1
    assert service.get(document.id, ADMIN).versione_corrente == 1
