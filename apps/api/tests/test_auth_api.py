from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings, get_settings
from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE, get_session
from pigrocrm_api.main import create_app

CREDENTIALS = {"email": "admin@pigro.it", "password": "supersegreta1"}


def test_login_sets_httponly_cookies(client: TestClient, admin_user) -> None:
    response = client.post("/api/auth/login", json=CREDENTIALS)
    assert response.status_code == 200
    assert ACCESS_COOKIE in response.cookies
    assert REFRESH_COOKIE in response.cookies
    # The token must never be readable by JavaScript.
    assert "httponly" in response.headers["set-cookie"].lower()
    # Production's default: TLS-only, so a stolen network capture cannot replay it.
    assert "secure" in response.headers["set-cookie"].lower()


def test_cookie_secure_false_omits_the_secure_attribute_for_local_dev_over_http(
    api_session: Session, admin_user
) -> None:
    """Chrome and Firefox treat `localhost` as a secure context and accept `Secure`
    cookies over plain HTTP there, but Safari does not and has no plan to -- and slice
    1B's local dev proxies through http://localhost with no TLS. Without a way to turn
    this off, login on Safari in development would look fine (200) while the browser
    silently discarded the cookie, and every later request would look unauthenticated
    with no visible error anywhere. Production's default stays secure; only an
    explicit override changes this."""
    app = create_app()
    app.dependency_overrides[get_session] = lambda: api_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        jwt_secret="test-secret-for-the-api-test-suite-only", cookie_secure=False
    )
    with TestClient(app, base_url="http://testserver") as insecure_client:
        response = insecure_client.post("/api/auth/login", json=CREDENTIALS)

    assert response.status_code == 200
    assert "secure" not in response.headers["set-cookie"].lower()
    # Still httpOnly -- turning off Secure for local HTTP must not also give up the
    # unrelated protection against JavaScript reading the cookie.
    assert "httponly" in response.headers["set-cookie"].lower()


def test_login_does_not_return_the_token_in_the_body(client: TestClient, admin_user) -> None:
    body = client.post("/api/auth/login", json=CREDENTIALS).json()
    assert "access_token" not in body
    assert body["email"] == "admin@pigro.it"


def test_login_with_wrong_password_is_422_with_a_problem_document(
    client: TestClient, admin_user
) -> None:
    response = client.post("/api/auth/login", json={**CREDENTIALS, "password": "sbagliata"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "validation_failed"
    assert "title" in problem and "detail" in problem


def test_me_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_current_user(logged_in: TestClient) -> None:
    body = logged_in.get("/api/auth/me").json()
    assert body["email"] == "admin@pigro.it"
    assert body["ruolo"] == "admin"


def test_logout_clears_the_cookies(logged_in: TestClient) -> None:
    assert logged_in.post("/api/auth/logout").status_code == 204
    assert logged_in.get("/api/auth/me").status_code == 401


def test_refresh_issues_a_new_access_cookie(logged_in: TestClient) -> None:
    response = logged_in.post("/api/auth/refresh")
    assert response.status_code == 200
    assert ACCESS_COOKIE in response.cookies


def test_refresh_with_an_invalid_refresh_token_is_401(client: TestClient) -> None:
    """A refresh token is a credential, not user-submitted form data -- an invalid or
    expired one must read as "not authenticated" (401), the same way an invalid access
    token does in get_actor, not as a generic 422 validation failure."""
    client.cookies.set(REFRESH_COOKIE, "not-a-real-jwt")
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401


def test_refresh_rotation_makes_the_old_token_unusable(logged_in: TestClient) -> None:
    """The whole point of rotation: if the old refresh token still worked after being
    used once, a copy of it -- taken at any point before rotation -- would stay usable
    for the rest of its 30-day life no matter how many times the legitimate user
    rotated past it."""
    old_refresh_token = logged_in.cookies.get(REFRESH_COOKIE)
    assert old_refresh_token is not None

    first = logged_in.post("/api/auth/refresh")
    assert first.status_code == 200

    # Simulate presenting the token again after it has already been rotated away --
    # e.g. a copy an attacker made before rotation happened.
    logged_in.cookies.set(REFRESH_COOKIE, old_refresh_token)
    replay = logged_in.post("/api/auth/refresh")
    assert replay.status_code == 401


def test_logout_invalidates_the_refresh_token_server_side(logged_in: TestClient) -> None:
    """logout must do more than empty the browser's cookie jar: the same refresh token,
    presented again after logout, must be dead server-side too -- otherwise a copy
    taken before logout stays valid for the rest of its 30-day life."""
    refresh_token = logged_in.cookies.get(REFRESH_COOKIE)
    assert refresh_token is not None

    assert logged_in.post("/api/auth/logout").status_code == 204

    logged_in.cookies.set(REFRESH_COOKIE, refresh_token)
    response = logged_in.post("/api/auth/refresh")
    assert response.status_code == 401


def test_a_personal_access_token_authenticates_too(logged_in: TestClient) -> None:
    """The same API serves the browser and the agent; only the credential differs."""
    raw = logged_in.post("/api/tokens", json={"nome": "Claude"}).json()["token"]

    bare = TestClient(logged_in.app)
    response = bare.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 200
    assert response.json()["email"] == "admin@pigro.it"


def test_an_invalid_bearer_token_is_401(client: TestClient) -> None:
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer pgc_inventato"})
    assert response.status_code == 401


def test_openapi_document_is_served(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "PigroCRM API"


# --- Coordinator follow-up on final review item 1: the NUL-byte gap was live --
# --- and reachable with zero credentials through /api/auth/login. ------------


def test_login_with_a_nul_byte_in_email_is_422_not_500(client: TestClient) -> None:
    """UserRepository.get_by_email binds `email` straight into a SELECT ... WHERE
    email = :email; psycopg refuses to adapt any string parameter containing a
    NUL byte. Before LoginRequest.email was SafeStr, this reached that query raw
    and came back as an uncaught 500 -- reachable by anyone, no cookie or PAT
    required, since login is the one endpoint that must work with zero
    credentials."""
    response = client.post(
        "/api/auth/login", json={"email": "admin\x00@pigro.it", "password": "supersegreta1"}
    )
    assert response.status_code == 422


def test_login_with_a_nul_byte_does_not_reveal_whether_the_email_exists(
    client: TestClient, admin_user
) -> None:
    """The rejection happens at the schema layer, before authenticate() runs any
    query at all -- so a malformed email that happens to match a real user and
    one that does not must produce indistinguishable responses, the same
    anti-enumeration discipline UserService.authenticate already applies via its
    dummy-hash timing defence for the ordinary wrong-password/unknown-email case."""
    existing = client.post(
        "/api/auth/login", json={"email": f"{CREDENTIALS['email']}\x00", "password": "x"}
    )
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody-at-all\x00@example.it", "password": "x"}
    )
    assert existing.status_code == unknown.status_code == 422
    existing_error, unknown_error = existing.json()["detail"][0], unknown.json()["detail"][0]
    assert existing_error["type"] == unknown_error["type"]
    assert existing_error["msg"] == unknown_error["msg"]
    assert existing_error["loc"] == unknown_error["loc"]
