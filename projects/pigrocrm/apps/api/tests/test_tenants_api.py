"""Spaces over HTTP: signing up, and then being served from the space's own database.

The registry and every space this file creates live in the same container `api_engine`
starts. `get_settings` is overridden with that container's URL so `TenantService` and
`deps._tenant_session_factory` both derive their databases from it, and the per-process
caches in `deps` are reset around each test so a space provisioned here never outlives
the settings it was built under.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db.sidecar import drop_database
from pigrocrm.core.tenants import ensure_tenants_database
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url
from pigrocrm_api.deps import get_session, reset_session_factories
from pigrocrm_api.main import create_app
from pigrocrm_api.tenancy import split_tenant_prefix

SLUG = "studio-prova"
SIGNUP = {
    "slug": SLUG,
    "nome": "Ada Lovelace",
    "email": "ada@studio.it",
    "password": "lunghissima1",
}


@pytest.fixture
def container_settings(api_engine: Engine) -> Settings:
    return Settings(
        database_url=api_engine.url.render_as_string(hide_password=False),
        jwt_secret="test-secret-for-the-api-test-suite-only",
        cookie_secure=True,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def spaces_client(container_settings: Settings, api_engine: Engine) -> Iterator[TestClient]:
    """A client whose root database is the container's CRM database and whose spaces are
    real databases on the same server. `get_session` is deliberately *not* overridden:
    the point is that `deps` picks the database from the request."""
    reset_session_factories()
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: container_settings
    registry = ensure_tenants_database(container_settings)
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client
    finally:
        with registry.begin() as connection:
            connection.execute(text("DELETE FROM tenants"))
        registry.dispose()
        reset_session_factories()
        drop_database(
            container_settings, tenant_database_url(container_settings, tenant_database_name(SLUG))
        )
        get_settings.cache_clear()


def test_the_prefix_is_split_only_for_a_space_and_only_before_api_or_health() -> None:
    assert split_tenant_prefix("/studio/api/customers") == ("studio", "/api/customers")
    assert split_tenant_prefix("/studio/health") == ("studio", "/health")
    assert split_tenant_prefix("/api/customers") == (None, "/api/customers")
    assert split_tenant_prefix("/app/api/x") == (None, "/app/api/x")  # reserved word
    assert split_tenant_prefix("/studio/app/login") == (None, "/studio/app/login")  # not the API
    assert split_tenant_prefix("/Studio/api/x") == (None, "/Studio/api/x")  # not a slug


def test_a_reserved_or_malformed_name_is_refused_before_touching_the_server(
    spaces_client: TestClient,
) -> None:
    for slug in ("app", "ab", "Studio Rossi"):
        response = spaces_client.post("/api/tenants/", json={**SIGNUP, "slug": slug})
        assert response.status_code == 422, (slug, response.text)


def test_availability_says_why(spaces_client: TestClient) -> None:
    assert spaces_client.get("/api/tenants/app/disponibile").json() == {
        "slug": "app",
        "disponibile": False,
        "motivo": "questo nome è riservato",
    }
    assert spaces_client.get(f"/api/tenants/{SLUG}/disponibile").json()["disponibile"] is True


def test_signing_up_creates_a_space_that_serves_its_own_data(
    spaces_client: TestClient, container_settings: Settings
) -> None:
    created = spaces_client.post("/api/tenants/", json=SIGNUP)
    assert created.status_code == 201, created.text
    assert created.json()["slug"] == SLUG
    assert created.headers["Location"] == f"/{SLUG}/app/login"

    # The name is gone, and a second signup with it is a 409, not a second space.
    assert spaces_client.get(f"/api/tenants/{SLUG}/disponibile").json()["disponibile"] is False
    again = spaces_client.post("/api/tenants/", json={**SIGNUP, "email": "bob@studio.it"})
    assert again.status_code == 409, again.text

    # The space's own login, with the admin the signup created, and a cookie scoped to it.
    login = spaces_client.post(
        f"/{SLUG}/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]}
    )
    assert login.status_code == 200, login.text
    assert f"Path=/{SLUG}/" in login.headers["set-cookie"]

    # The space is empty and separate: the root's session is not this one.
    customers = spaces_client.get(f"/{SLUG}/api/customers")
    assert customers.status_code == 200, customers.text
    assert customers.json()["items"] == []

    # Gmail does not exist for a space, whatever the installation has configured: the
    # account read says "nothing connected", and connecting one is refused outright.
    assert spaces_client.get(f"/{SLUG}/api/gmail/account").json()["account"] is None
    assert spaces_client.get(f"/{SLUG}/api/gmail/oauth/start").status_code == 409

    # The root does not know this user: the same credentials are refused there.
    assert (
        spaces_client.post(
            "/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]}
        ).status_code
        == 401
    )


def test_an_unknown_space_is_a_404_not_a_server_error(spaces_client: TestClient) -> None:
    response = spaces_client.get("/nessuno-qui/api/customers")
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"


def test_the_root_still_answers_without_a_prefix(spaces_client: TestClient) -> None:
    assert spaces_client.get("/health").json() == {"status": "ok"}
    assert spaces_client.get("/api/auth/me").status_code == 401
    # The root fixture client still works on its own, overridden session.
    assert get_session is not None


def test_the_root_slug_is_the_root_itself_and_nobody_elses_name(
    container_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`PIGROCRM_ROOT_SLUG=studiorossi`: `/studiorossi/api/...` is the root database with the
    root's settings, not a space, and the name is refused to signups."""
    assert split_tenant_prefix("/studiorossi/api/auth/me", "studiorossi") == (None, "/api/auth/me")
    assert split_tenant_prefix("/studiorossi/health", "studiorossi") == (None, "/health")
    assert split_tenant_prefix("/altro/api/x", "studiorossi") == ("altro", "/api/x")
    # Cookies follow the prefix the request wore, root alias included.
    from fastapi import Request

    from pigrocrm_api.tenancy import cookie_path

    def _request(state: dict[str, str]) -> Request:
        return Request({"type": "http", "path": "/api/x", "headers": [], "state": state})

    assert cookie_path(_request({})) == "/"
    # The root under its own name keeps the root's jar: it logs in at the bare
    # `/app/login` and works under `/studiorossi/app`, and only `/` serves both.
    assert cookie_path(_request({"prefix": "studiorossi"})) == "/"
    assert cookie_path(_request({"prefix": "studio", "tenant": "studio"})) == "/studio/"
    # What login, refresh and logout clear: the root's old jar under its own name is
    # included for the root -- bare or aliased -- and never for a space.
    from pigrocrm_api.tenancy import cookie_paths_to_clear

    assert cookie_paths_to_clear(_request({}), "studiorossi") == ["/studiorossi/", "/"]
    assert cookie_paths_to_clear(_request({"prefix": "studiorossi"}), "studiorossi") == [
        "/studiorossi/",
        "/",
    ]
    assert cookie_paths_to_clear(
        _request({"prefix": "studio", "tenant": "studio"}), "studiorossi"
    ) == [
        "/studio/",
        "/",
    ]

    monkeypatch.setenv("PIGROCRM_ROOT_SLUG", "studiorossi")
    monkeypatch.setenv("PIGROCRM_DATABASE_URL", container_settings.database_url)
    monkeypatch.setenv("PIGROCRM_JWT_SECRET", container_settings.jwt_secret)
    get_settings.cache_clear()
    reset_session_factories()
    rooted = container_settings.model_copy(update={"root_slug": "studiorossi"})
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: rooted
    registry = ensure_tenants_database(rooted)
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.get("/studiorossi/health").json() == {"status": "ok"}
            assert client.get("/studiorossi/api/tenants/root").json() == {"slug": "studiorossi"}
            # The root's own login answers here, and the cookie is the root's (`Path=/`).
            assert client.get("/studiorossi/api/auth/me").status_code == 401
            # A logout under the alias clears the root's pair at `/` *and* the pair that
            # lived at `/studiorossi/` before 2026-09-09: a browser removes a cookie only
            # for a matching path, and a pair left behind kept a session alive that the
            # person had ended.
            logout = client.post("/studiorossi/api/auth/logout")
            assert logout.status_code == 204
            deletions = logout.headers.get_list("set-cookie")
            assert sum("Path=/studiorossi/;" in c for c in deletions) == 2
            assert sum("Path=/;" in c for c in deletions) == 2
            assert client.get("/api/tenants/studiorossi/disponibile").json()["motivo"] == (
                "questo nome è riservato"
            )
            refused = client.post("/api/tenants/", json={**SIGNUP, "slug": "studiorossi"})
            assert refused.status_code == 422, refused.text
    finally:
        registry.dispose()
        reset_session_factories()
        get_settings.cache_clear()


def test_the_root_space_endpoint_names_the_root_or_says_there_is_none(
    spaces_client: TestClient,
) -> None:
    assert spaces_client.get("/api/tenants/root").json() == {"slug": None}
