"""Admins and sessions: one cookie, hashed at rest, sliding, gone on logout."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from orbiters_core.admin import AdminService
from orbiters_core.config import Settings
from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.models import AdminSession


@pytest.fixture
def admins(hub_engine: Engine, hub_session: Session) -> AdminService:
    settings = Settings(
        database_url=hub_engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )
    yield AdminService(hub_session, settings)  # type: ignore[misc]
    hub_session.rollback()
    hub_session.execute(text("DELETE FROM admin_sessions"))
    hub_session.execute(text("DELETE FROM admin_users"))
    hub_session.commit()


def test_an_admin_is_created_once_and_the_password_is_never_stored(
    admins: AdminService, hub_session: Session
) -> None:
    created = admins.create("Ivan@Orbiters.it", "Ivan", "una-password-lunga")
    assert created.email == "ivan@orbiters.it"
    stored = hub_session.execute(text("SELECT password_hash FROM admin_users")).scalar()
    assert stored and "una-password-lunga" not in stored and stored.startswith("$argon2")
    with pytest.raises(ValidationFailed):
        admins.create("ivan@orbiters.it", "Ancora", "altra-password-lunga")
    with pytest.raises(ValidationFailed):
        admins.create("corta@orbiters.it", "Corta", "breve")
    # A name that is only whitespace, or longer than the column, is refused here and not
    # left to Postgres (ORB-123 review): the CLI and the form share the rule.
    with pytest.raises(ValidationFailed) as blank:
        admins.create("vuoto@orbiters.it", "   ", "una-password-lunga")
    assert blank.value.details["field"] == "nome"
    with pytest.raises(ValidationFailed) as long_name:
        admins.create("lungo@orbiters.it", "x" * 121, "una-password-lunga")
    assert long_name.value.details["field"] == "nome"


def test_authenticate_answers_none_for_every_wrong_answer(admins: AdminService) -> None:
    admins.create("ivan@orbiters.it", "Ivan", "una-password-lunga")
    assert admins.authenticate("ivan@orbiters.it", "una-password-lunga") is not None
    assert admins.authenticate("ivan@orbiters.it", "sbagliata") is None
    assert admins.authenticate("nessuno@orbiters.it", "una-password-lunga") is None


def test_a_session_is_opaque_hashed_sliding_and_closable(
    admins: AdminService, hub_session: Session
) -> None:
    admin = admins.create("ivan@orbiters.it", "Ivan", "una-password-lunga")
    raw = admins.open_session(admin.id)
    row = hub_session.scalar(select(AdminSession))
    assert row is not None and row.token_hash != raw and len(row.token_hash) == 64
    first_deadline = row.expires_at

    # Presented, it resolves and its deadline moves forward.
    row.expires_at = first_deadline - timedelta(days=1)
    hub_session.commit()
    resolved = admins.resolve(raw)
    assert resolved is not None and resolved.email == "ivan@orbiters.it"
    hub_session.refresh(row)
    assert row.expires_at > first_deadline - timedelta(days=1)

    assert admins.resolve("qualcosaltro") is None
    assert admins.resolve(None) is None

    # Past its deadline it is forgotten on presentation.
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    hub_session.commit()
    assert admins.resolve(raw) is None
    assert hub_session.scalar(select(AdminSession)) is None

    again = admins.open_session(admin.id)
    admins.close_session(again)
    assert admins.resolve(again) is None


def test_list_names_every_admin_oldest_first_and_says_who_is_active(
    admins: AdminService, hub_session: Session
) -> None:
    # ORB-123: the admin area lists who reads it. Oldest first, so the page reads as a
    # history; `attivo` and `created_at` come along, the hash never does.
    first = admins.create("ivan@orbiters.it", "Ivan", "una-password-lunga")
    second = admins.create("lorenzo@orbiters.it", "Lorenzo", "altra-password-lunga")
    hub_session.execute(
        text("UPDATE admin_users SET attivo = false WHERE email = 'lorenzo@orbiters.it'")
    )
    hub_session.commit()
    listed = admins.list()
    assert [row.email for row in listed] == [first.email, second.email]
    assert [row.attivo for row in listed] == [True, False]
    assert all(row.created_at is not None for row in listed)
    assert not any(hasattr(row, "password_hash") for row in listed)


def test_update_changes_only_what_is_given_and_keeps_the_rules_of_create(
    admins: AdminService, hub_session: Session
) -> None:
    # ORB-129: a typo in the name, a new address, a forgotten password. Nothing given
    # means nothing changed; the rules are create's, once; the hash is never stored raw.
    ivan = admins.create("ivan@orbiters.it", "Ivan", "una-password-lunga")
    admins.create("lorenzo@orbiters.it", "Lorenzo", "altra-password-lunga")
    before = hub_session.execute(
        text("SELECT password_hash FROM admin_users WHERE nome = 'Ivan'")
    ).scalar()

    same = admins.update(ivan.id)
    assert (same.email, same.nome) == ("ivan@orbiters.it", "Ivan")

    renamed = admins.update(ivan.id, nome="  Ivan Sala  ", email="Ivan.Sala@Orbiters.it")
    assert (renamed.email, renamed.nome) == ("ivan.sala@orbiters.it", "Ivan Sala")
    assert admins.authenticate("ivan.sala@orbiters.it", "una-password-lunga") is not None

    rekeyed = admins.update(ivan.id, password="nuova-password-lunga")
    assert rekeyed.email == "ivan.sala@orbiters.it"
    after = hub_session.execute(
        text("SELECT password_hash FROM admin_users WHERE id = :id"), {"id": ivan.id}
    ).scalar()
    assert after != before and after.startswith("$argon2") and "nuova" not in after
    assert admins.authenticate("ivan.sala@orbiters.it", "una-password-lunga") is None
    assert admins.authenticate("ivan.sala@orbiters.it", "nuova-password-lunga") is not None

    # The same address on itself is fine; another admin's address is not.
    assert admins.update(ivan.id, email="IVAN.SALA@orbiters.it").email == "ivan.sala@orbiters.it"
    for kwargs, field in (
        ({"email": "lorenzo@orbiters.it"}, "email"),
        ({"nome": "  "}, "nome"),
        ({"nome": "x" * 121}, "nome"),
        ({"password": "breve"}, "password"),
    ):
        with pytest.raises(ValidationFailed) as refused:
            admins.update(ivan.id, **kwargs)
        assert refused.value.details["field"] == field, kwargs
    with pytest.raises(NotFound):
        admins.update(UUID("00000000-0000-7000-8000-000000000000"), nome="Nessuno")
