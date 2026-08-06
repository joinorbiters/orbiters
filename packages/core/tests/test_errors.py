import pytest

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import (
    Conflict,
    DomainError,
    ImmutableField,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)


def test_errors_carry_structured_details_not_formatted_strings() -> None:
    """The same exception becomes an HTTP problem detail AND an LLM-readable message.
    That is only possible if the data stays structured."""
    err = ValidationFailed("customer", "partita_iva", "must be 11 digits", expected="11 digits")

    assert isinstance(err, DomainError)
    assert err.code == "validation_failed"
    assert err.details == {
        "entity": "customer",
        "field": "partita_iva",
        "reason": "must be 11 digits",
        "expected": "11 digits",
    }


def test_not_found_records_which_entity_and_which_id() -> None:
    err = NotFound("deal", "0199-abc")
    assert err.code == "not_found"
    assert err.details["entity"] == "deal"
    assert err.details["identifier"] == "0199-abc"


def test_conflict_accepts_arbitrary_context() -> None:
    err = Conflict("customer", "has active deals", active_deals=3)
    assert err.code == "conflict"
    assert err.details["active_deals"] == 3


def test_permission_denied_states_what_role_would_be_enough() -> None:
    err = PermissionDenied("update_deal", ["admin", "collaboratore"], "readonly")
    assert err.details["required_roles"] == ["admin", "collaboratore"]
    assert err.details["actual_role"] == "readonly"


def test_immutable_field_is_its_own_error() -> None:
    err = ImmutableField("field_definition", "field_type", "would orphan existing values")
    assert err.code == "immutable_field"


@pytest.mark.parametrize(
    ("role", "can_write", "can_administer"),
    [("admin", True, True), ("collaboratore", True, False), ("readonly", False, False)],
)
def test_actor_permissions_by_role(role: str, can_write: bool, can_administer: bool) -> None:
    actor = Actor(id=None, type="user", role=role)  # type: ignore[arg-type]
    assert actor.can_write is can_write
    assert actor.can_administer is can_administer


def test_system_actor_is_an_admin_with_no_user_id() -> None:
    actor = Actor.system()
    assert actor.type == "system"
    assert actor.id is None
    assert actor.can_administer is True
