from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate, UserUpdate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings, get_settings
from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE, get_session
from pigrocrm_api.main import create_app

CREDENTIALS = {"email": "admin@pigro.it", "password": "supersegreta1"}


def _create_deactivated_user(session: Session, email: str) -> None:
    """A user who authenticated correctly right up until an admin flipped `attivo`
    off -- must fail login exactly like a wrong password or an unknown email, per
    UserService.authenticate's own anti-enumeration contract."""
    users = UserService(session)
    user = users.create(
        UserCreate(email=email, password="supersegreta1", nome="Disattivato", ruolo="admin"),
        Actor.system(),
    )
    users.update(user.id, UserUpdate(attivo=False), Actor.system())


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


def test_login_with_wrong_password_is_401(client: TestClient, admin_user) -> None:
    """Authentication failing is "not authenticated" (401), not "the request body was
    unprocessable" (422) -- the same convention an invalid refresh token and an invalid
    access token already follow a few lines below and in deps.get_actor.
    UserService.authenticate raises ValidationFailed here, like it does for every
    caller of this endpoint, but the router now maps that one call site to 401 instead
    of falling through to STATUS_BY_CODE's default (422), which is still correct for
    every other endpoint's ValidationFailed."""
    response = client.post("/api/auth/login", json={**CREDENTIALS, "password": "sbagliata"})
    assert response.status_code == 401


def test_login_with_an_unknown_email_is_401(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "nessuno@pigro.it", "password": "irrilevante"}
    )
    assert response.status_code == 401


def test_login_by_a_deactivated_user_is_401(client: TestClient, api_session: Session) -> None:
    _create_deactivated_user(api_session, "disattivato@pigro.it")
    response = client.post(
        "/api/auth/login",
        json={"email": "disattivato@pigro.it", "password": "supersegreta1"},
    )
    assert response.status_code == 401


def test_login_failures_are_byte_identical_regardless_of_cause(
    client: TestClient, api_session: Session, admin_user
) -> None:
    """UserService.authenticate deliberately raises one identical error for unknown
    email, wrong password, and a deactivated user -- with a constant-time dummy hash so
    even response timing does not leak which case happened. That property is only worth
    anything if the HTTP layer preserves it all the way out: this pins the three
    responses as byte-identical, not merely "all 401", so a future change that gives
    even one of the three cases its own message would fail this test instead of quietly
    reopening the enumeration gap."""
    _create_deactivated_user(api_session, "disattivato@pigro.it")

    unknown_email = client.post(
        "/api/auth/login", json={"email": "nessuno@pigro.it", "password": "irrilevante"}
    )
    wrong_password = client.post("/api/auth/login", json={**CREDENTIALS, "password": "sbagliata"})
    deactivated_user = client.post(
        "/api/auth/login",
        json={"email": "disattivato@pigro.it", "password": "supersegreta1"},
    )

    for response in (unknown_email, wrong_password, deactivated_user):
        assert response.status_code == 401
    assert unknown_email.content == wrong_password.content == deactivated_user.content


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


def test_me_and_refresh_document_401_but_logout_does_not() -> None:
    """`me` and `refresh` both actually return 401 (see test_me_requires_authentication
    and test_refresh_with_an_invalid_refresh_token_is_401 above), but PROBLEM_RESPONSES
    (errors.py, shared by every router) only declares 403/404/409/422 -- a generated
    TypeScript client would type this response as `unknown` for exactly the status code
    a frontend auth layer branches on programmatically (session expired -> try refresh
    -> redirect to login). `logout` must NOT gain the same entry: it has no actor
    dependency and is idempotent by construction (an absent or already-invalid refresh
    cookie is simply nothing left to invalidate, per its own docstring), so it cannot
    structurally produce a 401 the way these two can -- claiming one anyway would
    misdocument a response this route never sends.

    No database fixture: building the app and reading its schema never opens a session,
    same reasoning as test_error_rendering.py's equivalent 422-shape check."""
    app = create_app()
    schema = app.openapi()

    me_responses = schema["paths"]["/api/auth/me"]["get"]["responses"]
    refresh_responses = schema["paths"]["/api/auth/refresh"]["post"]["responses"]
    logout_responses = schema["paths"]["/api/auth/logout"]["post"]["responses"]

    assert "401" not in logout_responses

    for responses in (me_responses, refresh_responses):
        assert "401" in responses
        content = responses["401"]["content"]
        assert set(content) == {"application/json"}
        body_schema = content["application/json"]["schema"]
        assert body_schema["properties"]["detail"]["type"] == "string"
        assert body_schema["required"] == ["detail"]

    # The addition is additive, not a replacement: both routes still inherit the
    # router-wide domain-error responses alongside their own new 401.
    for responses in (me_responses, refresh_responses):
        assert {"403", "404", "409", "422"} <= set(responses)


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
