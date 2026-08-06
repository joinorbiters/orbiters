import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, PermissionDenied, ValidationFailed
from pigrocrm.core.fields.schemas import FieldDefinitionCreate, FieldDefinitionUpdate
from pigrocrm.core.fields.service import FieldDefinitionService

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")


def _create(service: FieldDefinitionService, key: str = "settore", **kw):
    payload = {"entity_type": "customer", "key": key, "label": key.title(), "field_type": "text"}
    payload.update(kw)
    return service.create(FieldDefinitionCreate(**payload), ADMIN)


def test_create_returns_the_definition(db_session: Session) -> None:
    field = _create(FieldDefinitionService(db_session))
    assert field.key == "settore"
    assert field.archived is False


def test_key_is_slugified(db_session: Session) -> None:
    field = _create(FieldDefinitionService(db_session), key="  Settore Merceologico  ")
    assert field.key == "settore_merceologico"


def test_duplicate_key_on_the_same_entity_is_a_conflict(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    _create(service)
    with pytest.raises(Conflict):
        _create(service)


def test_the_same_key_on_a_different_entity_is_allowed(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    _create(service)
    other = service.create(
        FieldDefinitionCreate(
            entity_type="deal", key="settore", label="Settore", field_type="text"
        ),
        ADMIN,
    )
    assert other.entity_type == "deal"


def test_select_without_options_is_rejected(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    with pytest.raises(ValidationFailed) as exc:
        _create(service, key="stato", field_type="select", options=[])
    assert exc.value.details["field"] == "options"


def test_non_select_with_options_is_rejected(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    with pytest.raises(ValidationFailed):
        _create(service, key="nome", field_type="text", options=["a"])


def test_field_type_cannot_be_changed(db_session: Session) -> None:
    """There is no correct answer for text -> number with existing values, so the
    operation does not exist. Archive the old field and create a new one."""
    service = FieldDefinitionService(db_session)
    field = _create(service)

    assert "field_type" not in FieldDefinitionUpdate.model_fields
    # extra="forbid" turns the attempt into a pydantic ValidationError, so the
    # request never reaches the service at all.
    with pytest.raises(ValidationError):
        FieldDefinitionUpdate(field_type="number")  # type: ignore[call-arg]

    updated = service.update(field.id, FieldDefinitionUpdate(label="Nuovo"), ADMIN)
    assert updated.field_type == "text"


def test_archive_hides_the_field_but_keeps_it_readable(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    field = _create(service)
    service.archive(field.id, ADMIN)

    assert service.list("customer") == []
    archived = service.list("customer", include_archived=True)
    assert len(archived) == 1
    assert archived[0].archived is True


def test_archived_fields_are_excluded_from_specs(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    keep = _create(service, key="tenuto")
    drop = _create(service, key="archiviato")
    service.archive(drop.id, ADMIN)

    keys = [spec.key for spec in service.specs_for("customer")]
    assert keys == [keep.key]


def test_list_is_ordered_by_position_then_label(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    _create(service, key="terzo", position=2)
    _create(service, key="primo", position=0)
    _create(service, key="secondo", position=1)
    assert [f.key for f in service.list("customer")] == ["primo", "secondo", "terzo"]


def test_only_admins_change_the_schema(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    with pytest.raises(PermissionDenied) as exc:
        service.create(
            FieldDefinitionCreate(entity_type="customer", key="x", label="X", field_type="text"),
            COLLAB,
        )
    assert exc.value.details["required_roles"] == ["admin"]


def test_specs_for_returns_field_specs_usable_by_the_validator(db_session: Session) -> None:
    from pigrocrm.core.fields.validator import validate_custom_fields

    service = FieldDefinitionService(db_session)
    _create(service, key="stato", field_type="select", options=["attivo", "sospeso"])

    specs = service.specs_for("customer")
    assert validate_custom_fields("customer", specs, {"stato": "attivo"}) == {"stato": "attivo"}
