"""Spaces: the name rules, and a real provisioning against the test container.

`provision` is exercised for what it is -- CREATE DATABASE, the repository's own Alembic
migrations to head, the first admin -- not against a database somebody pre-created. The
container `db_engine` starts is the server; the registry and the space it creates are
two more databases on it.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.errors import Conflict, ValidationFailed
from pigrocrm.core.tenants import (
    RESERVED_SLUGS,
    TenantService,
    TenantSignup,
    ensure_tenants_database,
    slugify,
    validate_slug,
)
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url


def _settings_for(engine: Engine) -> Settings:
    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(scope="module")
def settings(db_engine: Engine) -> Settings:
    return _settings_for(db_engine)


@pytest.fixture(scope="module")
def registry(settings: Settings) -> Iterator[Engine]:
    engine = ensure_tenants_database(settings)
    yield engine
    engine.dispose()


@pytest.fixture
def registry_session(registry: Engine) -> Iterator[Session]:
    session = session_factory(registry)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# --- the name --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nome", "slug"),
    [
        ("Studio Rossi", "studio-rossi"),
        ("  Caffè & Co.  ", "caffe-co"),
        ("ÀÉÎÕÜ", "aeiou"),
        ("già-ok", "gia-ok"),
        ("x" * 40, "x" * 32),
    ],
)
def test_slugify_makes_a_url_segment_out_of_a_name(nome: str, slug: str) -> None:
    assert slugify(nome) == slug


@pytest.mark.parametrize("slug", ["studio-rossi", "abc", "a1-b2", "x" * 32])
def test_well_formed_slugs_pass(slug: str) -> None:
    assert validate_slug(slug) is None


@pytest.mark.parametrize(
    "slug",
    ["ab", "-abc", "abc-", "Studio", "studio rossi", "a_b_c", "x" * 33, *sorted(RESERVED_SLUGS)],
)
def test_malformed_and_reserved_slugs_are_refused_with_a_reason(slug: str) -> None:
    reason = validate_slug(slug)
    assert reason is not None and reason


def test_the_signup_schema_refuses_a_reserved_name_before_anything_else() -> None:
    with pytest.raises(ValueError, match="riservato"):
        TenantSignup(slug="app", nome="Ada", email="ada@studio.it", password="lunghissima1")


def test_the_database_name_is_an_unquoted_identifier() -> None:
    assert tenant_database_name("studio-rossi") == "pigro_t_studio_rossi"


# --- the provisioning --------------------------------------------------------------


def _drop(settings: Settings, slug: str) -> None:
    from pigrocrm.core.db.sidecar import drop_database

    drop_database(settings, tenant_database_url(settings, tenant_database_name(slug)))


def test_provisioning_creates_a_migrated_database_with_one_admin(
    settings: Settings, registry_session: Session
) -> None:
    service = TenantService(registry_session, settings)
    slug = "prova-spazio"
    try:
        created = service.provision(
            TenantSignup(
                slug=slug, nome="Ada Lovelace", email="Ada@Studio.it", password="lunghissima1"
            )
        )
        assert created.slug == slug
        assert created.owner_email == "ada@studio.it"
        assert service.availability(slug).disponibile is False

        space = create_engine(
            tenant_database_url(settings, tenant_database_name(slug)), future=True
        )
        try:
            with space.connect() as connection:
                # The same head the CRM itself is at: `env.py` ran, not `create_all`.
                head = connection.execute(text("select version_num from alembic_version")).scalar()
                assert head is not None and head >= "0027"
                users = connection.execute(text("select email, ruolo, attivo from users")).all()
                assert users == [("ada@studio.it", "admin", True)]
                assert connection.execute(text("select count(*) from customers")).scalar() == 0
        finally:
            space.dispose()
    finally:
        _drop(settings, slug)
        registry_session.execute(text("delete from tenants where slug = :s"), {"s": slug})
        registry_session.commit()


def test_the_same_name_twice_is_a_conflict_and_leaves_the_first_space_alone(
    settings: Settings, registry_session: Session
) -> None:
    service = TenantService(registry_session, settings)
    slug = "prova-doppio"
    try:
        service.provision(
            TenantSignup(slug=slug, nome="Ada", email="ada@studio.it", password="lunghissima1")
        )
        with pytest.raises(Conflict):
            service.provision(
                TenantSignup(slug=slug, nome="Bob", email="bob@studio.it", password="lunghissima1")
            )
        space = create_engine(
            tenant_database_url(settings, tenant_database_name(slug)), future=True
        )
        try:
            with space.connect() as connection:
                assert connection.execute(text("select email from users")).scalars().all() == [
                    "ada@studio.it"
                ]
        finally:
            space.dispose()
    finally:
        _drop(settings, slug)
        registry_session.execute(text("delete from tenants where slug = :s"), {"s": slug})
        registry_session.commit()


def test_a_short_password_provisions_nothing_and_frees_the_name(
    settings: Settings, registry_session: Session
) -> None:
    service = TenantService(registry_session, settings)
    slug = "prova-corta"
    with pytest.raises(ValidationFailed):
        service.provision(
            TenantSignup(slug=slug, nome="Ada", email="ada@studio.it", password="corta")
        )
    assert service.availability(slug).disponibile is True
    assert (
        registry_session.execute(
            text("select count(*) from tenants where slug = :s"), {"s": slug}
        ).scalar()
        == 0
    )
    with create_engine(settings.database_url, future=True).connect() as connection:
        exists = connection.execute(
            text("select 1 from pg_database where datname = :n"), {"n": tenant_database_name(slug)}
        ).scalar()
    assert exists is None
