from fastapi.testclient import TestClient

from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE

CREDENTIALS = {"email": "admin@pigro.it", "password": "supersegreta1"}


def test_login_sets_httponly_cookies(client: TestClient, admin_user) -> None:
    response = client.post("/api/auth/login", json=CREDENTIALS)
    assert response.status_code == 200
    assert ACCESS_COOKIE in response.cookies
    assert REFRESH_COOKIE in response.cookies
    # The token must never be readable by JavaScript.
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
