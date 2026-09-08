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


def _create(email: str, **extra: object) -> SignupCreate:
    """The form's three required answers. `nome` and `cognome` are not optional any
    more, so every test that only cares about the address says so through here."""
    return SignupCreate(email=email, nome="Ada", cognome="Lovelace", **extra)  # type: ignore[arg-type]


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
    result = SignupService(orbiters_session).subscribe(_create("Ada@Studio.IT"))
    assert result.nuova is True
    assert result.email == "ada@studio.it"
    assert result.created_at.tzinfo is not None


def test_the_same_address_again_is_one_row_and_a_second_success(
    orbiters_session: Session,
) -> None:
    service = SignupService(orbiters_session)
    first = service.subscribe(_create("ada@studio.it"))
    second = service.subscribe(_create("ADA@studio.it"))
    assert second.nuova is False
    assert second.id == first.id
    assert orbiters_session.execute(text("SELECT count(*) FROM signups")).scalar() == 1


def test_an_address_that_is_not_one_is_refused_before_the_database() -> None:
    with pytest.raises(ValidationError):
        _create("non-e-una-email")


def test_the_list_is_newest_first_and_counts_everything(orbiters_session: Session) -> None:
    from pigrocrm.core.actor import Actor

    service = SignupService(orbiters_session)
    for address in ("prima@studio.it", "seconda@studio.it", "terza@studio.it"):
        service.subscribe(_create(address))
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


def test_the_attribution_is_stored_with_the_first_signup_and_never_overwritten(
    orbiters_session: Session,
) -> None:
    from pigrocrm.core.orbiters import SignupUtm

    service = SignupService(orbiters_session)
    first = service.subscribe(
        _create(
            "ada@studio.it",
            utm=SignupUtm(utm_source="linkedin", utm_medium="paid-social", utm_id="{{AD_SET_ID}}"),
        )
    )
    assert (first.utm_source, first.utm_medium, first.utm_id) == (
        "linkedin",
        "paid-social",
        "{{AD_SET_ID}}",
    )
    assert first.utm_campaign is None
    again = service.subscribe(_create("ada@studio.it", utm=SignupUtm(utm_source="newsletter")))
    assert again.nuova is False
    assert again.utm_source == "linkedin"


def test_no_attribution_is_stored_as_nothing(orbiters_session: Session) -> None:
    from pigrocrm.core.actor import Actor

    service = SignupService(orbiters_session)
    service.subscribe(_create("bob@studio.it"))
    item = service.list_recent(Actor(id=None, type="mcp", role="admin")).iscrizioni[0]
    assert item.email == "bob@studio.it"
    assert item.utm_source is None and item.utm_id is None


def test_ensuring_the_database_adds_the_late_columns_to_an_older_table(
    db_engine: Engine,
) -> None:
    """The production table predates the columns: drop them, re-run the ensure, and they
    are back -- which is the whole migration this sidecar has."""
    from pigrocrm.core.orbiters.models import LATE_COLUMNS

    engine = ensure_orbiters_database(_settings_for(db_engine))
    try:
        with engine.begin() as connection:
            for column, _width in LATE_COLUMNS:
                connection.execute(text(f"ALTER TABLE signups DROP COLUMN IF EXISTS {column}"))
        again = ensure_orbiters_database(_settings_for(db_engine))
        try:
            with again.connect() as connection:
                columns = set(
                    connection.execute(
                        text(
                            "select column_name from information_schema.columns "
                            "where table_name = 'signups'"
                        )
                    ).scalars()
                )
            assert {column for column, _width in LATE_COLUMNS} <= columns
        finally:
            again.dispose()
    finally:
        engine.dispose()


def test_the_person_signs_with_a_name_and_the_name_is_trimmed(orbiters_session: Session) -> None:
    result = SignupService(orbiters_session).subscribe(
        SignupCreate(email="ada@studio.it", nome="  Ada  ", cognome=" Lovelace ")
    )
    assert (result.nome, result.cognome) == ("Ada", "Lovelace")
    assert result.linkedin_url is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_name_that_is_only_space_is_refused_before_the_database(blank: str) -> None:
    with pytest.raises(ValidationError):
        SignupCreate(email="ada@studio.it", nome=blank, cognome="Lovelace")
    with pytest.raises(ValidationError):
        SignupCreate(email="ada@studio.it", nome="Ada", cognome=blank)


def test_a_name_longer_than_the_column_is_refused() -> None:
    with pytest.raises(ValidationError):
        SignupCreate(email="ada@studio.it", nome="a" * 121, cognome="Lovelace")


def test_the_linkedin_profile_is_optional_and_kept_as_given(orbiters_session: Session) -> None:
    result = SignupService(orbiters_session).subscribe(
        _create("ada@studio.it", linkedin_url="https://www.linkedin.com/in/ada")
    )
    assert result.linkedin_url == "https://www.linkedin.com/in/ada"


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/in/ada",
        "https://notlinkedin.com/in/ada",
        "linkedin.com/in/ada",
        "javascript:alert(1)//linkedin.com/",
    ],
)
def test_a_profile_somewhere_that_is_not_linkedin_is_refused(value: str) -> None:
    with pytest.raises(ValidationError):
        _create("ada@studio.it", linkedin_url=value)


@pytest.mark.parametrize("value", ["", "   ", None])
def test_no_profile_at_all_is_stored_as_nothing(
    orbiters_session: Session, value: str | None
) -> None:
    result = SignupService(orbiters_session).subscribe(_create("ada@studio.it", linkedin_url=value))
    assert result.linkedin_url is None


def test_the_list_carries_the_name_and_the_profile(orbiters_session: Session) -> None:
    from pigrocrm.core.actor import Actor

    service = SignupService(orbiters_session)
    service.subscribe(
        SignupCreate(
            email="ada@studio.it",
            nome="Ada",
            cognome="Lovelace",
            linkedin_url="https://www.linkedin.com/in/ada",
        )
    )
    item = service.list_recent(Actor(id=None, type="mcp", role="admin")).iscrizioni[0]
    assert (item.nome, item.cognome) == ("Ada", "Lovelace")
    assert item.linkedin_url == "https://www.linkedin.com/in/ada"


def test_a_row_from_before_the_form_asked_learns_the_name_on_the_next_signup(
    orbiters_session: Session,
) -> None:
    """The twenty-four rows on the server were written when the form asked only for an
    address, so their `nome` is NULL. Someone signing up again is exactly how that gets
    filled in -- and filling an empty column overwrites nothing, which is why this is
    allowed where the attribution is not."""
    orbiters_session.execute(
        text("INSERT INTO signups (id, email) VALUES (gen_random_uuid(), 'vecchia@studio.it')")
    )
    orbiters_session.commit()
    again = SignupService(orbiters_session).subscribe(
        _create("vecchia@studio.it", linkedin_url="https://www.linkedin.com/in/ada")
    )
    assert again.nuova is False
    assert (again.nome, again.cognome) == ("Ada", "Lovelace")
    assert again.linkedin_url == "https://www.linkedin.com/in/ada"


def test_a_name_already_on_the_list_is_never_overwritten(orbiters_session: Session) -> None:
    service = SignupService(orbiters_session)
    service.subscribe(SignupCreate(email="ada@studio.it", nome="Ada", cognome="Lovelace"))
    again = service.subscribe(SignupCreate(email="ada@studio.it", nome="Qualcun", cognome="Altro"))
    assert (again.nome, again.cognome) == ("Ada", "Lovelace")
