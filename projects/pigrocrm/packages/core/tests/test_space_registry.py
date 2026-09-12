"""The engine-per-space registry both adapters share (ORB-170).

Real databases on the test container, as `test_tenants.py` does: the point of the
registry is which database a slug opens, which a savepoint session cannot express.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.db.sidecar import drop_database
from pigrocrm.core.errors import NotFound
from pigrocrm.core.space_settings import SpaceSettingsService, SpaceSettingsUpdate
from pigrocrm.core.tenants import (
    SpaceRegistry,
    TenantService,
    TenantSignup,
    ensure_tenants_database,
    space_base_settings,
)
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url

SLUG = "registro-prova"


@pytest.fixture(scope="module")
def settings(db_engine: Engine) -> Settings:
    return Settings(
        database_url=db_engine.url.render_as_string(hide_password=False),
        public_url="https://pigro.example",
        google_client_id="root-client.apps",
        google_client_secret="root-secret",
        google_token_key="cm9vdC1rZXktMzItYnl0ZXMtbG9uZy1lbm91Z2gtLS0=",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def provisioned(settings: Settings) -> Iterator[str]:
    registry = ensure_tenants_database(settings)
    with session_factory(registry)() as session:
        TenantService(session, settings).provision(
            TenantSignup(slug=SLUG, nome="Ada", email="ada@studio.it")
        )
    try:
        yield SLUG
    finally:
        with session_factory(registry)() as session:
            session.execute(text("delete from tenants where slug = :s"), {"s": SLUG})
            session.commit()
        drop_database(settings, tenant_database_url(settings, tenant_database_name(SLUG)))
        registry.dispose()


def test_the_root_has_no_slug_and_opens_the_configured_database(settings: Settings) -> None:
    registry = SpaceRegistry(settings)
    try:
        with registry.session_factory(None)() as session:
            db = session.execute(text("select current_database()")).scalar_one()
        assert db == settings.database_url.rsplit("/", 1)[1]
    finally:
        registry.dispose()


def test_an_unknown_slug_is_not_found(settings: Settings) -> None:
    registry = SpaceRegistry(settings)
    try:
        with pytest.raises(NotFound):
            registry.session_factory("nessuno-spazio")
    finally:
        registry.dispose()


def test_a_provisioned_slug_opens_its_own_database_once(
    settings: Settings, provisioned: str
) -> None:
    registry = SpaceRegistry(settings)
    try:
        factory = registry.session_factory(provisioned)
        assert registry.session_factory(provisioned) is factory  # built once, then kept
        with factory() as session:
            db = session.execute(text("select current_database()")).scalar_one()
        assert db == tenant_database_name(provisioned)
    finally:
        registry.dispose()


def test_space_base_settings_blank_google_and_scope_the_public_url(settings: Settings) -> None:
    space = space_base_settings(settings, "studio")
    assert space.google_client_id == ""
    assert space.google_client_secret == ""
    assert space.google_token_key == ""
    assert space.public_url == "https://pigro.example/studio"
    assert space.storage_backend == "local"
    assert space_base_settings(settings, None) is settings


def test_overrides_are_cached_for_the_ttl_and_dropped_on_invalidate(
    settings: Settings, provisioned: str
) -> None:
    registry = SpaceRegistry(settings, overrides_ttl=1000.0)
    try:
        with registry.session_factory(provisioned)() as session:
            assert registry.overrides(provisioned, session) == {}
            admin = Actor(id=None, type="system", role="admin")
            SpaceSettingsService(session, registry.settings).update(
                SpaceSettingsUpdate(mcp_full_access=True), admin, spazio=provisioned
            )
            session.commit()
            # Still the cached answer: the TTL has not run out.
            assert registry.overrides(provisioned, session) == {}
            assert registry.effective_settings(provisioned, session).mcp_full_access is False
            registry.invalidate(provisioned)
            assert registry.overrides(provisioned, session) == {"mcp_full_access": "true"}
            assert registry.effective_settings(provisioned, session).mcp_full_access is True
    finally:
        registry.dispose()


def test_a_zero_ttl_reads_the_rows_every_time(settings: Settings, provisioned: str) -> None:
    registry = SpaceRegistry(settings, overrides_ttl=0.0)
    try:
        with registry.session_factory(provisioned)() as session:
            assert registry.overrides(provisioned, session) == {}
            admin = Actor(id=None, type="system", role="admin")
            SpaceSettingsService(session, registry.settings).update(
                SpaceSettingsUpdate(mcp_full_access=True), admin, spazio=provisioned
            )
            session.commit()
            assert registry.overrides(provisioned, session) == {"mcp_full_access": "true"}
    finally:
        registry.dispose()
