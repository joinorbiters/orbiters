from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.fields.models import FieldDefinition


class FieldDefinitionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, field_id: UUID) -> FieldDefinition | None:
        return self.session.get(FieldDefinition, field_id)

    def get_by_key(self, entity_type: str, key: str) -> FieldDefinition | None:
        stmt = select(FieldDefinition).where(
            FieldDefinition.entity_type == entity_type, FieldDefinition.key == key
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, entity_type: str, *, include_archived: bool = False) -> list[FieldDefinition]:
        stmt = select(FieldDefinition).where(FieldDefinition.entity_type == entity_type)
        if not include_archived:
            stmt = stmt.where(FieldDefinition.archived.is_(False))
        # `id` is the tiebreaker: Postgres gives no ordering guarantee at all between
        # rows equal on both `position` and `label`, so without a final, unique key
        # the result order is undefined and can vary between two identical queries.
        stmt = stmt.order_by(FieldDefinition.position, FieldDefinition.label, FieldDefinition.id)
        return list(self.session.execute(stmt).scalars())

    def add(self, field: FieldDefinition) -> FieldDefinition:
        self.session.add(field)
        self.session.flush()
        return field
