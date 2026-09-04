"""The REST surface of slice 9B's Drive credential, over real HTTP -- the Drive twin of
`test_gmail_router.py`.

Two claims are asserted here that no service-level test can make, because each is a
property of the *adapter* rather than of the domain:

  * an installation with no Google credentials answers "assente", not "rotto" -- and
    `GET /api/drive/account` answers **200** while saying so, exactly like
    `GET /api/gmail/account`, so the settings page can render "non disponibile" without
    the SPA treating the response as a failed query;
  * the OAuth start redirect asks Google for both Drive scopes, and never leaks the
    client secret into a URL a browser will carry.

`drive_ready` overrides the `Settings` dependency the same way `test_gmail_router.py`'s
`gmail_ready` does, and for the same reason: the rest of this suite runs with Google
unconfigured, which is the state the first tests need.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.drive.models import GoogleDriveAccount

TOKEN_KEY_B64 = "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s="  # 32 bytes of "k"
CLIENT_SECRET = "il-segreto-del-client"

# Two valid-shaped Drive ids -- `_DriveId`'s pattern wants ten to a hundred-and-
# twenty-eight url-safe base64 characters, and these are simply long enough test
# doubles, never real Drive folders.
ROOT_ID = "1AbCdEfGhIjKlMnOpQrS"
OTHER_ROOT_ID = "2ZyXwVuTsRqPoNmLkJiH"
STORAGE_ID = "3QqWwEeRrTtYyUuIiOoP"


def _configured() -> Settings:
    """The suite's own settings with the four Google variables filled in -- a copy of
    the settings `client` already installed, not a fresh `Settings(...)`, for the same
    reason `test_gmail_router.py`'s `_configured` copies rather than constructs: a
    fresh `Settings()` would sign the login cookie with a different `jwt_secret` than
    the one already on the client, and every authenticated request in this file would
    answer 401 in a way that looks like a broken auth dependency and is nothing of the
    sort.
    """
    return Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": CLIENT_SECRET,
            "google_token_key": TOKEN_KEY_B64,
            "public_url": "https://crm.example.it",
        }
    )


@pytest.fixture
def drive_ready(client: TestClient) -> Iterator[TestClient]:
    """The same client, with Google configured. Yields so the override is removed even
    when the test fails, exactly like `test_gmail_router.py`'s `gmail_ready`."""
    client.app.dependency_overrides[get_settings] = _configured
    yield client
    client.app.dependency_overrides.pop(get_settings, None)


def _second_actor(admin_client: TestClient, ruolo: str) -> TestClient:
    """A genuinely independent session, not `admin_client`'s own cookie jar. See the
    identical helper in `test_invoices_api.py`/`test_costs_api.py`: `logged_in` and a
    second role built on the same `client` fixture share one cookie jar, so requesting
    both in one test leaves exactly one login active on it for every call made under
    *either* variable for the rest of the test. `TestClient(admin_client.app)` is the
    fix already established there -- a fresh cookie jar over the same ASGI app, and
    therefore the same database session and settings overrides.
    """
    email = f"{ruolo}-{id(admin_client)}@pigro.it"
    created = admin_client.post(
        "/api/users",
        json={"email": email, "password": "supersegreta1", "nome": "Test", "ruolo": ruolo},
    )
    assert created.status_code == 201, created.text
    client = TestClient(admin_client.app, base_url="https://testserver")
    response = client.post("/api/auth/login", json={"email": email, "password": "supersegreta1"})
    assert response.status_code == 200, response.text
    return client


def _connected_account(session: Session, user_id: Any, **overrides: Any) -> GoogleDriveAccount:
    """A row in the state a user reaches after consenting. The token bytes are opaque
    on purpose -- nothing in this file decrypts them, and this suite is not the one
    that asserts they never appear on the wire (`test_gmail_router.py` already does,
    for the shared `seal`/`unseal` machinery); a one-byte placeholder is enough to
    satisfy the non-nullable columns.
    """
    account = GoogleDriveAccount(
        user_id=user_id,
        google_sub="sub-123",
        email_address="io@example.it",
        refresh_token_ciphertext=b"\x01",
        refresh_token_nonce=b"\x02",
        scopes_granted=[
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
        ],
        root_folder_ids=[],
        **{"status": "active", **overrides},
    )
    session.add(account)
    session.flush()
    return account


# --- absent, not broken ---------------------------------------------------------------


def test_the_account_endpoint_is_readable_even_with_google_off(logged_in: TestClient) -> None:
    response = logged_in.get("/api/drive/account")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "account": None,
        "banner": None,
        "banner_text": None,
        "missing_scopes": [],
        "configured": False,
    }


def test_a_configured_installation_with_no_drive_says_so_differently(
    logged_in: TestClient, drive_ready: TestClient
) -> None:
    payload = logged_in.get("/api/drive/account").json()
    assert payload["configured"] is True
    assert payload["account"] is None
    assert payload["banner"] is None


# --- who may call it -------------------------------------------------------------------


def test_every_drive_endpoint_requires_authentication(client: TestClient) -> None:
    for method, path in [
        ("GET", "/api/drive/account"),
        ("GET", "/api/drive/oauth/start"),
        ("GET", "/api/drive/oauth/callback"),
        ("DELETE", "/api/drive/account"),
        ("PATCH", "/api/drive/account/roots"),
    ]:
        assert client.request(method, path).status_code == 401, path


def test_a_readonly_actor_cannot_set_roots(logged_in: TestClient, drive_ready: TestClient) -> None:
    """403, not the 409 a missing account would give: `set_roots`'s `require_write`
    runs before `_present`'s presence check, so the role refusal has to be provable
    even with no row to refuse it over.

    `readonly`, not `collaboratore`: `actor.py`'s `WRITE_ROLES` is `("admin",
    "collaboratore")`, so a collaboratore actually passes this gate -- `readonly` is
    the one role `require_write` refuses, and is the same role
    `test_gmail_router.py`'s own `test_a_readonly_actor_cannot_sync` uses to prove the
    identical gate on `/api/gmail/sync`.
    """
    readonly = _second_actor(logged_in, "readonly")
    response = readonly.patch("/api/drive/account/roots", json={"root_folder_ids": [ROOT_ID]})
    assert response.status_code == 403, response.text


# --- the OAuth round trip ---------------------------------------------------------------


def test_the_start_endpoint_asks_for_both_drive_scopes_without_the_client_secret(
    logged_in: TestClient, drive_ready: TestClient
) -> None:
    response = logged_in.get("/api/drive/oauth/start", follow_redirects=False)
    assert response.status_code == 307, response.text

    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/")
    assert CLIENT_SECRET not in location
    assert "drive.readonly" in location
    assert "drive.file" in location


def test_the_callback_never_renders_the_upstream_error_to_the_browser(
    logged_in: TestClient, drive_ready: TestClient
) -> None:
    response = logged_in.get(
        "/api/drive/oauth/callback?error=access_denied", follow_redirects=False
    )
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("/app/impostazioni/drive?esito=")
    assert "access_denied" not in location


def test_a_callback_with_a_state_nobody_issued_never_reports_a_connection(
    logged_in: TestClient, drive_ready: TestClient
) -> None:
    response = logged_in.get(
        "/api/drive/oauth/callback?code=abc&state=mai-emesso", follow_redirects=False
    )
    assert response.status_code == 307, response.text
    assert response.headers["location"] == "/app/impostazioni/drive?esito=errore"


# --- the roots configuration -------------------------------------------------------------


def test_setting_roots_without_a_connected_account_is_a_conflict(
    logged_in: TestClient, drive_ready: TestClient
) -> None:
    response = logged_in.patch("/api/drive/account/roots", json={"root_folder_ids": [ROOT_ID]})
    assert response.status_code == 409, response.text


def test_setting_roots_on_a_connected_account_updates_them(
    logged_in: TestClient, drive_ready: TestClient, api_session: Session, admin_user: Any
) -> None:
    _connected_account(api_session, admin_user.id)

    response = logged_in.patch(
        "/api/drive/account/roots",
        json={"root_folder_ids": [ROOT_ID, OTHER_ROOT_ID], "storage_folder_id": STORAGE_ID},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["root_folder_ids"] == [ROOT_ID, OTHER_ROOT_ID]
    assert body["storage_folder_id"] == STORAGE_ID
    # Nothing here decrypts the credential; this is the same "no token on the wire"
    # discipline `test_gmail_router.py` asserts on its own account payloads.
    assert "ciphertext" not in response.text
    assert "nonce" not in response.text


def test_a_revoked_account_may_still_have_its_roots_reconfigured(
    logged_in: TestClient, drive_ready: TestClient, api_session: Session, admin_user: Any
) -> None:
    """No `gmail_configured`-style health gate on this route: the person most likely to
    be here is the one trying to recover from exactly this state (see
    `GoogleDriveAccountService.set_roots`'s docstring)."""
    _connected_account(api_session, admin_user.id, status="revoked")

    response = logged_in.patch("/api/drive/account/roots", json={"root_folder_ids": [ROOT_ID]})
    assert response.status_code == 200, response.text
    assert response.json()["root_folder_ids"] == [ROOT_ID]


# --- disconnecting -----------------------------------------------------------------------


def test_disconnecting_then_reading_shows_the_account_as_disconnected(
    logged_in: TestClient, drive_ready: TestClient, api_session: Session, admin_user: Any
) -> None:
    _connected_account(api_session, admin_user.id)

    assert logged_in.delete("/api/drive/account").status_code == 204

    payload = logged_in.get("/api/drive/account").json()
    assert payload["account"]["status"] == "disconnected"
    assert payload["banner"] is None


def test_disconnecting_with_no_connected_account_is_a_conflict(
    logged_in: TestClient, drive_ready: TestClient
) -> None:
    response = logged_in.delete("/api/drive/account")
    assert response.status_code == 409, response.text


# --- the surface as documented -------------------------------------------------------------


def _drive_operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    found = []
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/drive"):
            continue
        for method, operation in operations.items():
            found.append((path, method, operation))
    return found


def test_no_drive_schema_on_the_wire_carries_a_credential(client: TestClient) -> None:
    """Structural, over every schema the Drive operations reference -- the same
    assertion `test_gmail_router.py` makes for Gmail's own schemas, and for the same
    reason: `GoogleDriveAccount` holds the sealed refresh token as columns, and the
    read schema exists precisely so no route can return the row directly."""
    schema = client.get("/openapi.json").json()
    components = schema["components"]["schemas"]
    forbidden = {
        "refresh_token",
        "refresh_token_ciphertext",
        "refresh_token_nonce",
        "code_verifier",
        "access_token",
        "client_secret",
        "google_token_key",
    }

    referenced: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[1]
                if name not in referenced:
                    referenced.add(name)
                    collect(components.get(name, {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    for _path, _method, operation in _drive_operations(schema):
        collect(operation)

    assert {"DriveHealth", "GoogleDriveAccountRead"} <= referenced, referenced
    for name in referenced:
        properties = components.get(name, {}).get("properties", {})
        assert not set(properties) & forbidden, f"{name} espone una credenziale"


def test_drive_router_is_mounted_and_tagged(client: TestClient) -> None:
    """A cheap guard against the one thing `main.py` requires by hand -- see its own
    module list, which is not auto-discovered from `routers/`: a router built but
    never added to that tuple would 404 every request in this whole file, and this is
    the assertion that catches it fastest."""
    schema = client.get("/openapi.json").json()
    operations = _drive_operations(schema)
    assert len(operations) >= 4, operations
    for _path, _method, operation in operations:
        assert operation.get("tags") == ["drive"]
