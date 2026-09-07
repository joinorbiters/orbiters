"""The Orbiters signup list: a database of its own, one table, one idempotent write.

The container `db_engine` starts is a real Postgres server, so `ensure_orbiters_database`
is exercised for what it is -- a `CREATE DATABASE` against a server that does not have
it yet -- rather than against a database somebody pre-created for the test.
"""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.orbiters import (
    SignupCreate,
    SignupService,
    ensure_orbiters_database,
    orbiters_database_url,
)


def _settings_for(engine: Engine) -> Settings:
    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(scope="module")
def orbiters_engine(db_engine: Engine) -> Iterator[Engine]:
    engine = ensure_orbiters_database(_settings_for(db_engine))
    yield engine
    engine.dispose()


@pytest.fixture
def orbiters_session(orbiters_engine: Engine) -> Iterator[Session]:
    session = session_factory(orbiters_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("DELETE FROM signups"))
        session.commit()
        session.close()


def test_the_url_is_the_crm_server_with_only_the_database_renamed() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@db:5432/pigrocrm",
        _env_file=None,  # type: ignore[call-arg]
    )
    url = orbiters_database_url(settings)
    assert url.database == "orbiters"
    assert (url.host, url.port, url.username, url.password) == ("db", 5432, "u", "p")


def test_an_explicit_url_wins() -> None:
    settings = Settings(
        orbiters_database_url="postgresql+psycopg://x:y@altrove:5433/lista",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert orbiters_database_url(settings).database == "lista"


def test_the_database_is_created_and_the_crm_database_is_untouched(
    db_engine: Engine, orbiters_engine: Engine
) -> None:
    assert orbiters_engine.url.database == "orbiters"
    with orbiters_engine.connect() as connection:
        assert connection.execute(text("SELECT to_regclass('signups')")).scalar() == "signups"
    with db_engine.connect() as connection:
        assert connection.execute(text("SELECT to_regclass('signups')")).scalar() is None


def test_ensuring_twice_is_harmless(db_engine: Engine, orbiters_engine: Engine) -> None:
    again = ensure_orbiters_database(_settings_for(db_engine))
    try:
        with again.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
    finally:
        again.dispose()


def test_the_first_signup_is_new_and_lowercased(orbiters_session: Session) -> None:
    result = SignupService(orbiters_session).subscribe(SignupCreate(email="Ada@Studio.IT"))
    assert result.nuova is True
    assert result.email == "ada@studio.it"
    assert result.created_at.tzinfo is not None


def test_the_same_address_again_is_one_row_and_a_second_success(
    orbiters_session: Session,
) -> None:
    service = SignupService(orbiters_session)
    first = service.subscribe(SignupCreate(email="ada@studio.it"))
    second = service.subscribe(SignupCreate(email="ADA@studio.it"))
    assert second.nuova is False
    assert second.id == first.id
    assert orbiters_session.execute(text("SELECT count(*) FROM signups")).scalar() == 1


def test_an_address_that_is_not_one_is_refused_before_the_database() -> None:
    with pytest.raises(ValidationError):
        SignupCreate(email="non-e-una-email")


def test_the_list_is_newest_first_and_counts_everything(orbiters_session: Session) -> None:
    from pigrocrm.core.actor import Actor

    service = SignupService(orbiters_session)
    for address in ("prima@studio.it", "seconda@studio.it", "terza@studio.it"):
        service.subscribe(SignupCreate(email=address))
    page = service.list_recent(Actor(id=None, type="mcp", role="admin"), limit=2)
    assert page.totale == 3
    assert [item.email for item in page.iscrizioni] == ["terza@studio.it", "seconda@studio.it"]


def test_only_an_admin_may_read_the_list(orbiters_session: Session) -> None:
    from pigrocrm.core.actor import Actor
    from pigrocrm.core.errors import PermissionDenied

    with pytest.raises(PermissionDenied):
        SignupService(orbiters_session).list_recent(
            Actor(id=None, type="mcp", role="collaboratore")
        )
