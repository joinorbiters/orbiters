from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from pigrocrm.core.db import decode_cursor, escape_like, keyset_predicate, order_by
from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.documents.schemas import DOCUMENT_SORTS, DocumentListQuery


class DocumentRepository:
    """A repository never commits (project rule): every method here either reads or
    flushes, and the surrounding `DocumentService` method is always the one
    transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: UUID, *, include_deleted: bool = False) -> Document | None:
        document = self.session.get(Document, document_id)
        if document is None:
            return None
        if document.deleted_at is not None and not include_deleted:
            return None
        return document

    def add(self, document: Document) -> Document:
        self.session.add(document)
        self.session.flush()
        return document

    def add_version(self, version: DocumentVersion) -> DocumentVersion:
        """Flushes -- and only flushes -- so the caller can observe (and, on the
        unique `(document_id, numero)` constraint, catch) the outcome before deciding
        whether to touch storage at all. See `DocumentService.add_version`."""
        self.session.add(version)
        self.session.flush()
        return version

    def version(self, document_id: UUID, numero: int) -> DocumentVersion | None:
        stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id, DocumentVersion.numero == numero
        )
        return self.session.execute(stmt).scalars().first()

    def versions(self, document_id: UUID) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(desc(DocumentVersion.numero))
        )
        return list(self.session.execute(stmt).scalars())

    def list(self, query: DocumentListQuery) -> list[Document]:
        stmt = select(Document).where(Document.deleted_at.is_(None))
        if query.customer_id:
            stmt = stmt.where(Document.customer_id == query.customer_id)
        if query.deal_id:
            stmt = stmt.where(Document.deal_id == query.deal_id)
        if query.tipo:
            stmt = stmt.where(Document.tipo == query.tipo)
        if query.stato:
            stmt = stmt.where(Document.stato == query.stato)
        if query.search:
            # New in slice 6. One column, so no `or_`: spec §8.1 searches `titolo` and
            # nothing else on this table -- a document's body lives in storage, not in
            # a column, and its Markdown source is explicitly out of scope.
            #
            # `escape_like` neutralises "%"/"_"/"\" in the *user's* term before it is
            # wrapped in the "%...%" this method builds; `escape="\\"` states which
            # character it used rather than relying on ILIKE's default. Task A2
            # measured that the ESCAPE clause costs `ix_documents_titolo_trgm` nothing
            # -- the planner folds it into the same constant pattern -- so it stays
            # here exactly as in the other three repositories.
            like = f"%{escape_like(query.search.lower())}%"
            stmt = stmt.where(Document.titolo.ilike(like, escape="\\"))

        # Residuo R9 -- see `CustomerRepository.list` for the reasoning.
        spec = DOCUMENT_SORTS.resolve(query.sort)
        if query.cursor:
            value, row_id = decode_cursor(spec, query.cursor)
            stmt = stmt.where(keyset_predicate(spec, query.dir, value, row_id))

        return list(
            self.session.execute(
                stmt.order_by(*order_by(spec, query.dir)).limit(query.limit + 1)
            ).scalars()
        )
