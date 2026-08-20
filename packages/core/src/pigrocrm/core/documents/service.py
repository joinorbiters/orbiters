import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.documents.schemas import (
    ALLOWED_CONTENT_TYPES,
    DIMENSIONE_MAX,
    DocumentCreate,
    DocumentListQuery,
    DocumentPage,
    DocumentRead,
    DocumentUpdate,
    DocumentVersionRead,
)
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.storage.base import DocumentStorage

ENTITY: EntityType = "document"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_CUSTOMER_ID_FRAGMENT = 8


def slugify_folder(raw: str) -> str:
    """A customer name (or a document title) as a storage-key/filename segment.

    Mirrors `fields/schemas.slugify_key` in spirit -- NFKD, drop the combining marks,
    collapse the rest -- but joins with "-" rather than "_", because these segments
    are read by a human browsing Google Drive, which is the whole point of storing a
    slug at all.
    """
    decomposed = unicodedata.normalize("NFKD", raw)
    transliterated = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SLUG_STRIP.sub("-", transliterated.strip().lower()).strip("-") or "senza-nome"


class DocumentService:
    def __init__(self, session: Session, storage: DocumentStorage) -> None:
        self.session = session
        self.storage = storage
        self.repo = DocumentRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    # ---- owner resolution ---------------------------------------------------

    def _check_owner(self, customer_id: UUID | None, deal_id: UUID | None) -> None:
        """Exactly one owner, and it must exist.

        The database check constraint (`ck_documents_customer_xor_deal`) is the
        second line under concurrency; this is the first, and it is what turns a
        syntactically valid but unknown UUID into this project's own `NotFound`
        instead of a raw `ForeignKeyViolation` reaching the caller from `flush()`.
        """
        if (customer_id is None) == (deal_id is None):
            raise ValidationFailed(
                ENTITY,
                "customer_id",
                "un documento appartiene a un cliente oppure a un deal, mai a entrambi",
                expected="esattamente uno fra customer_id e deal_id",
            )
        if customer_id is not None and self.session.get(Customer, customer_id) is None:
            raise NotFound("customer", customer_id)
        if deal_id is not None and self.session.get(Deal, deal_id) is None:
            raise NotFound("deal", deal_id)

    def _customer_of(self, document: Document) -> Customer | None:
        if document.customer_id is not None:
            return self.session.get(Customer, document.customer_id)
        deal = self.session.get(Deal, document.deal_id) if document.deal_id else None
        return self.session.get(Customer, deal.customer_id) if deal else None

    def storage_key_for(self, document: Document, numero: int, content_type: str) -> str:
        """`{cliente-slug}-{id[:8]}/{document_id}/v{numero}{ext}`.

        The customer-id fragment is what keeps the folder stable when a customer is
        renamed -- the slug alone would send the next version into a different folder
        and orphan the earlier ones. The slug is what makes the folder legible to a
        human browsing Drive. Built entirely from validated internal pieces (a
        slugified name, a UUID's own hex digits, an integer, an extension drawn from
        `ALLOWED_CONTENT_TYPES`, never the caller's raw string) and still passed
        through `storage.put`'s own `validate_storage_key` gate before anything
        touches a filesystem -- this method's job is to produce a *sensible* key, not
        to be the security boundary itself.
        """
        customer = self._customer_of(document)
        folder = (
            f"{slugify_folder(customer.ragione_sociale)}-{str(customer.id)[:_CUSTOMER_ID_FRAGMENT]}"
            if customer
            else "senza-cliente"
        )
        return f"{folder}/{document.id}/v{numero}{ALLOWED_CONTENT_TYPES[content_type]}"

    # ---- custom fields ------------------------------------------------------

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def _update_custom_fields(self, document: Document, provided: dict[str, Any]) -> dict[str, Any]:
        """Validates only the keys the caller is touching, never the merge with what
        is stored. Identical in shape to `CustomerService._update_custom_fields`; see
        that method's docstring for the archiving contract this preserves."""
        active_by_key = {spec.key: spec for spec in self.fields.specs_for(ENTITY)}
        to_remove: set[str] = set()
        for key, value in provided.items():
            if value is not None:
                continue
            spec = active_by_key.get(key)
            if spec is not None and spec.required:
                raise ValidationFailed(
                    ENTITY, key, "campo obbligatorio", expected="un valore non vuoto"
                )
            to_remove.add(key)
        to_set = {key: value for key, value in provided.items() if value is not None}
        touched = [spec for spec in active_by_key.values() if spec.key in to_set]
        merged = {k: v for k, v in document.custom_fields.items() if k not in to_remove}
        merged.update(validate_custom_fields(ENTITY, touched, to_set))
        return merged

    # ---- documents ------------------------------------------------------------

    def create(self, data: DocumentCreate, actor: Actor) -> DocumentRead:
        actor.require_write("create_document")
        payload = data.model_dump()
        self._check_owner(payload["customer_id"], payload["deal_id"])
        # Only an offer has a state; everything else keeps NULL. A new offer starts as
        # a draft rather than stateless, so a Kanban-style state picker always has a
        # value to show.
        is_offer = payload["tipo"] == "offerta"
        payload["stato"] = (payload.get("stato") or "bozza") if is_offer else None
        payload["custom_fields"] = self._validated_custom(payload.get("custom_fields") or {})

        document = self.repo.add(Document(**payload))
        self.activities.record(
            ENTITY,
            document.id,
            "created",
            actor,
            {"titolo": document.titolo, "tipo": document.tipo},
        )
        self.session.commit()
        return DocumentRead.model_validate(document)

    def update(self, document_id: UUID, data: DocumentUpdate, actor: Actor) -> DocumentRead:
        actor.require_write("update_document")
        document = self._require(document_id)
        changes = data.model_dump(exclude_none=True, exclude={"custom_fields"})
        if data.custom_fields is not None:
            changes["custom_fields"] = self._update_custom_fields(document, data.custom_fields)
        for key, value in changes.items():
            setattr(document, key, value)
        self.activities.record(ENTITY, document.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return DocumentRead.model_validate(document)

    def get(self, document_id: UUID, actor: Actor) -> DocumentRead:
        return DocumentRead.model_validate(self._require(document_id))

    def soft_delete(self, document_id: UUID, actor: Actor) -> None:
        """Sets `deleted_at`. The stored bytes are left alone -- soft delete never
        touches storage. `delete` on the storage backends is a separate, deliberate
        act (the one that had to be fixed so it could not leave a document retrievable
        after deletion); a restore that came back without the file would not be a real
        restore, so nothing here calls it."""
        actor.require_write("delete_document")
        document = self._require(document_id)
        document.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, document.id, "deleted", actor)
        self.session.commit()

    def restore(self, document_id: UUID, actor: Actor) -> DocumentRead:
        actor.require_write("restore_document")
        document = self.repo.get(document_id, include_deleted=True)
        if document is None:
            raise NotFound(ENTITY, document_id)
        was_deleted = document.deleted_at is not None
        document.deleted_at = None
        if was_deleted:
            self.activities.record(ENTITY, document.id, "restored", actor)
        self.session.commit()
        return DocumentRead.model_validate(document)

    # ---- versions ---------------------------------------------------------------

    def _next_numero(self, document: Document) -> int:
        """The candidate version number for a new upload on `document`.

        Split out to a single, tiny method so `add_version`'s own ordering guarantee
        (below) has exactly one thing to be provably correct about, and so a test can
        force a collision deterministically -- the same technique
        `test_upsert_converts_a_true_insert_race_into_a_clean_conflict` in
        `test_emitter.py` uses on `EmitterProfileRepository.get` -- without needing
        real threads against a single savepoint-backed test session.
        """
        return document.versione_corrente + 1

    def add_version(
        self,
        document_id: UUID,
        data: bytes,
        content_type: str,
        actor: Actor,
        *,
        sorgente_markdown: str | None = None,
        template_id: UUID | None = None,
        variabili: dict[str, Any] | None = None,
    ) -> DocumentVersionRead:
        """Every change makes a version; nothing is ever overwritten (spec 4.2).

        Ordering, deliberately: the `DocumentVersion` row is flushed -- which sends
        the `INSERT` and lets Postgres enforce `uq_document_versions_document_numero`
        -- *before* a single byte reaches `storage.put`. Two callers racing to add a
        version to the same document both compute their candidate `numero` from
        `document.versione_corrente` before either has committed; under Postgres, the
        loser's `INSERT` either blocks until the winner's transaction resolves (real
        concurrency) or raises `IntegrityError` immediately against an
        already-committed row (the two-callers-in-one-process shape this project's
        own tests reproduce, see `_next_numero`). Either way, the loser's exception is
        caught and turned into `Conflict` *before* it has called `storage.put` at
        all -- so a losing racer can never overwrite the winning racer's bytes at the
        storage key both computed from the same `numero`, and a failed flush never
        burns a version number: nothing was committed, so the same `numero` is offered
        again on the next attempt.

        The reverse order (bytes first, row second -- storage.put before the insert)
        was rejected: it is exactly as safe on the *happy* path, but on the race path
        it lets the loser's `storage.put` execute and physically overwrite the
        winner's already-put bytes before the loser's own insert is rejected by the
        unique constraint -- corrupting a version that a reader may already believe is
        final. Writing the row first means storage is only ever touched once the
        number is confirmed reserved (if only within this open transaction).

        The remaining failure mode -- `storage.put` itself raising after a successful
        flush -- is handled by rolling back before propagating: without that, the
        flushed `INSERT` would still be pending in the session, and an unrelated later
        commit on this same session could persist a version row pointing at bytes
        that were never written. Rolling back trades that for the harmless outcome:
        nothing committed, the number is not burned, the session stays usable.
        """
        actor.require_write("add_document_version")
        document = self._require(document_id)
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValidationFailed(
                ENTITY,
                "content_type",
                f"tipo di file non ammesso: {content_type}",
                expected=", ".join(sorted(ALLOWED_CONTENT_TYPES)),
            )
        if not data:
            raise ValidationFailed(ENTITY, "file", "il file e' vuoto", expected="almeno un byte")
        if len(data) > DIMENSIONE_MAX:
            raise ValidationFailed(
                ENTITY,
                "dimensione",
                f"il file supera {DIMENSIONE_MAX} byte",
                expected=f"al massimo {DIMENSIONE_MAX} byte",
            )

        numero = self._next_numero(document)
        version = DocumentVersion(
            document_id=document.id,
            numero=numero,
            sorgente_markdown=sorgente_markdown,
            template_id=template_id,
            variabili=variabili,
            storage_key=self.storage_key_for(document, numero, content_type),
            content_type=content_type,
            dimensione=len(data),
            hash_sha256=hashlib.sha256(data).hexdigest(),
            creato_da=actor.id,
        )
        try:
            self.repo.add_version(version)
        except IntegrityError as exc:
            # The pre-check above (numero derived from the caller's own read of
            # versione_corrente) cannot cover two callers racing on the same
            # document: the unique constraint on (document_id, numero) is the real
            # authority. Storage was never touched -- see the docstring above.
            self.session.rollback()
            raise Conflict(
                "document_version",
                "conflitto di concorrenza sul numero di versione, riprova",
                document_id=str(document_id),
            ) from exc

        try:
            self.storage.put(version.storage_key, data, content_type)
        except Exception:
            # The row is flushed but not committed: rolling back here undoes that
            # insert too, so nothing is left pointing at bytes that were never
            # written, and the version number is free to be offered again.
            self.session.rollback()
            raise

        document.versione_corrente = numero
        self.activities.record(ENTITY, document.id, "version_added", actor, {"numero": numero})
        self.session.commit()
        return DocumentVersionRead.model_validate(version)

    def versions(self, document_id: UUID, actor: Actor) -> list[DocumentVersionRead]:
        self._require(document_id)
        return [DocumentVersionRead.model_validate(v) for v in self.repo.versions(document_id)]

    def download(
        self, document_id: UUID, numero: int | None, actor: Actor
    ) -> tuple[bytes, str, str]:
        """`(bytes, content_type, filename)`.

        The filename is built from the document's title, slugified: the title is user
        input and reaches a `Content-Disposition` header, where a quote or a newline
        would be header injection.
        """
        document = self._require(document_id)
        wanted = numero if numero is not None else document.versione_corrente
        version = self.repo.version(document_id, wanted) if wanted else None
        if version is None:
            raise NotFound("document_version", f"{document_id}#{wanted}")
        extension = ALLOWED_CONTENT_TYPES[version.content_type]
        filename = f"{slugify_folder(document.titolo)}-v{version.numero}{extension}"
        return self.storage.get(version.storage_key), version.content_type, filename

    def _require(self, document_id: UUID) -> Document:
        document = self.repo.get(document_id)
        if document is None:
            raise NotFound(ENTITY, document_id)
        return document

    # `list` must stay the last method defined in this class -- an unconditional
    # project rule (`test_module_imports.py`). Defining a method named `list` rebinds
    # that name in the *class* namespace, so any later method whose own return
    # annotation is a bare `list[...]` would resolve `list` to this method instead of
    # the builtin and fail at import time on Python 3.13.
    def list(self, query: DocumentListQuery, actor: Actor) -> DocumentPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return DocumentPage(
            items=[DocumentRead.model_validate(d) for d in items],
            next_cursor=items[-1].id if has_more and items else None,
        )
