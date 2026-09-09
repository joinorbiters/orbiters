"""Comments: what an admin or an assistant says about a row, appended and never edited.

The row's own `note` is a summary somebody overwrites; a comment is a dated, signed
remark that stays. Two methods and no third on purpose: there is no `update` and no
`delete`, so nothing in the API or the MCP server can offer one either (ORB-59).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.models import (
    AUTORE_MAX_LENGTH,
    COMMENT_ENTITY_TYPES,
    COMMENT_MAX_LENGTH,
    Comment,
    Company,
    Freelancer,
)
from orbiters_core.schemas import CommentRead, clean_multiline

ENTITY = "comment"
# The parent table per `entity_type`: what `add` looks up before it writes, so a
# comment can never point at a row that is not there.
_PARENTS: dict[str, type[Freelancer] | type[Company]] = {
    "freelancer": Freelancer,
    "company": Company,
}


class CommentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity_type: str, entity_id: UUID, testo: str, autore: str) -> CommentRead:
        """Appends one comment. The text is trimmed, may span several lines, and is at
        most `COMMENT_MAX_LENGTH` characters; the author is whoever the adapter says is
        speaking (the logged-in admin's name, or "MCP"). The row must exist: a comment
        on a freelancer that was never there is a `NotFound` naming the freelancer."""
        parent = self._parent(entity_type)
        if self.session.get(parent, entity_id) is None:
            raise NotFound(entity_type, entity_id)
        try:
            text = clean_multiline(testo, what="un testo")
        except ValueError as exc:
            raise ValidationFailed(ENTITY, "testo", str(exc)) from exc
        if len(text) > COMMENT_MAX_LENGTH:
            raise ValidationFailed(
                ENTITY, "testo", f"un commento può avere al massimo {COMMENT_MAX_LENGTH} caratteri"
            )
        author = autore.strip()
        if not author:
            raise ValidationFailed(ENTITY, "autore", "serve chi lo scrive, non solo spazi")
        if len(author) > AUTORE_MAX_LENGTH:
            raise ValidationFailed(ENTITY, "autore", f"al massimo {AUTORE_MAX_LENGTH} caratteri")
        row = Comment(entity_type=entity_type, entity_id=entity_id, testo=text, autore=author)
        self.session.add(row)
        self.session.commit()
        return CommentRead.model_validate(row)

    def list(self, entity_type: str, entity_id: UUID) -> list[CommentRead]:
        """The whole thread, newest first. No page: a thread is a handful of remarks,
        and reading half of one is worse than reading none."""
        self._parent(entity_type)
        rows = self.session.scalars(
            select(Comment)
            .where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
            .order_by(Comment.created_at.desc(), Comment.id.desc())
        ).all()
        return [CommentRead.model_validate(row) for row in rows]

    def _parent(self, entity_type: str) -> type[Freelancer] | type[Company]:
        parent = _PARENTS.get(entity_type)
        if parent is None:
            raise ValidationFailed(
                ENTITY, "entity_type", f"uno fra {', '.join(COMMENT_ENTITY_TYPES)}"
            )
        return parent
