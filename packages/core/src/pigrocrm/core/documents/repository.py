from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.documents.schemas import DocumentListQuery


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
        if query.cursor:
            stmt = stmt.where(Document.id > query.cursor)
        # Keyset pagination on a UUIDv7 id: ordered by creation, stable under inserts.
        return list(
            self.session.execute(stmt.order_by(Document.id).limit(query.limit + 1)).scalars()
        )
