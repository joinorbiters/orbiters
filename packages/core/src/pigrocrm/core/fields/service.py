from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.fields.models import FieldDefinition
from pigrocrm.core.fields.repository import FieldDefinitionRepository
from pigrocrm.core.fields.schemas import (
    EntityType,
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
)
from pigrocrm.core.fields.types import OPTION_TYPES, FieldSpec


def _check_options(field_type: str, options: list[str]) -> None:
    if field_type in OPTION_TYPES and not options:
        raise ValidationFailed(
            "field_definition",
            "options",
            f"un campo di tipo {field_type} richiede almeno un'opzione",
            expected="una lista non vuota",
        )
    if field_type not in OPTION_TYPES and options:
        raise ValidationFailed(
            "field_definition",
            "options",
            f"un campo di tipo {field_type} non ammette opzioni",
            expected="una lista vuota",
        )


class FieldDefinitionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = FieldDefinitionRepository(session)

    def create(self, data: FieldDefinitionCreate, actor: Actor) -> FieldDefinitionRead:
        actor.require_admin("create_field_definition")
        if not data.key:
            raise ValidationFailed(
                "field_definition", "key", "chiave vuota dopo la normalizzazione"
            )
        _check_options(data.field_type, data.options)

        if self.repo.get_by_key(data.entity_type, data.key):
            raise Conflict(
                "field_definition",
                "esiste già un campo con questa chiave",
                entity_type=data.entity_type,
                key=data.key,
            )

        field = FieldDefinition(**data.model_dump())
        try:
            self.repo.add(field)
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a race between two concurrent requests:
            # there the database constraint is the only authority. The rollback is
            # mandatory — without it the session is unusable for the caller.
            self.session.rollback()
            raise Conflict(
                "field_definition",
                "esiste già un campo con questa chiave",
                entity_type=data.entity_type,
                key=data.key,
            ) from exc
        return FieldDefinitionRead.model_validate(field)

    def update(
        self, field_id: UUID, data: FieldDefinitionUpdate, actor: Actor
    ) -> FieldDefinitionRead:
        actor.require_admin("update_field_definition")
        field = self.repo.get(field_id)
        if field is None:
            raise NotFound("field_definition", field_id)

        changes = data.model_dump(exclude_none=True)
        if "options" in changes:
            _check_options(field.field_type, changes["options"])
        for key, value in changes.items():
            setattr(field, key, value)
        self.session.commit()
        return FieldDefinitionRead.model_validate(field)

    def archive(self, field_id: UUID, actor: Actor) -> FieldDefinitionRead:
        """Archive rather than delete: deleting a definition while rows still hold the
        value in JSONB produces orphan data nobody can see."""
        actor.require_admin("archive_field_definition")
        field = self.repo.get(field_id)
        if field is None:
            raise NotFound("field_definition", field_id)
        field.archived = True
        self.session.commit()
        return FieldDefinitionRead.model_validate(field)

    def specs_for(self, entity_type: EntityType) -> list[FieldSpec]:
        """The bridge to the validator and to the runtime model factory.

        Defined before `list` below: inside a class body, annotations are evaluated
        eagerly by looking the name up in the class namespace first. Once `def list`
        below has executed, the name `list` is rebound there from the builtin to that
        method, and this method's bare `list[FieldSpec]` return annotation would
        resolve to it instead — `TypeError: 'function' object is not subscriptable`.
        Defining this method first sidesteps that; do not reorder.
        """
        return [
            FieldSpec(
                key=f.key,
                label=f.label,
                field_type=f.field_type,  # type: ignore[arg-type]
                options=list(f.options),
                required=f.required,
            )
            for f in self.repo.list(entity_type)
        ]

    def list(
        self, entity_type: EntityType, *, include_archived: bool = False
    ) -> list[FieldDefinitionRead]:
        return [
            FieldDefinitionRead.model_validate(f)
            for f in self.repo.list(entity_type, include_archived=include_archived)
        ]
