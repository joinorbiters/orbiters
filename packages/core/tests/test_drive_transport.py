"""The Drive HTTP layer, and the two ways a token for it is obtained.

`storage/gdrive.py` used to be one class doing three jobs: signing a service-account
JWT, HTTP mechanics (retry, backoff, error decoding), and Drive placement/identity.
Slice 9 needs the middle job driven by a *user* OAuth token instead, so the first two
now live in `drive/transport.py` and this file covers them directly.

What is faked is still only the network -- `fakes/fake_drive.py` -- so URL building,
header injection, the retry schedule and the error decoding all run for real. Where a test
has to see the *headers* of a request (the whole point of a bearer token), it wraps
the fake rather than changing it: the fake records `(method, url)` only, and the spec
is explicit that the fake does not change.
"""

import io
import urllib.error
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from fakes.fake_drive import FakeDrive

from pigrocrm.core.drive.transport import (
    DriveTransport,
    ServiceAccountTokens,
    _urllib_call,
)
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.storage import GDriveStorage

PDF = b"%PDF-1.7\nfinto\n"
KEY = "acme-01234567/0199abcd/v1.pdf"

# No real RSA key is needed anywhere in this file: the signer is injected, and the
# fake answers the token endpoint without verifying the assertion -- so no private key
# material exists in this repository at all.
SERVICE_ACCOUNT_JSON = (
    '{"type":"service_account","client_email":"pigro@example.iam.gserviceaccount.com",'
    '"private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n",'
    '"token_uri":"https://oauth2.googleapis.com/token"}'
)


@dataclass
class StubTokens:
    """A `TokenProvider` that hands out a token a test can recognise on the wire."""

    value: str = "tok"

    def access_token(self) -> str:
        return self.value


@dataclass
class RecordingHttp:
    """Records the headers of every request, then delegates to the real fake.

    `FakeDrive` records `(method, url)` and nothing else, and the spec says it does not
    change ("il fake non cambia: e' il trasporto che finge"). Wrapping it keeps every
    bit of its Drive semantics while making the one thing it does not record --
    the `Authorization` header -- assertable.
    """

    inner: FakeDrive
    headers: list[dict[str, str]] = field(default_factory=list)

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        self.headers.append(dict(headers))
        return self.inner(method, url, headers, body)


# --- The bearer token reaches every request ------------------------------------------


def test_every_request_carries_the_providers_bearer_token() -> None:
    """The one thing a transport with a pluggable token provider must not get wrong:
    the token has to be on *every* call, not only the first. Asserted on the headers
    that actually reached the wire, not on the provider having been asked."""
    drive = FakeDrive()
    http = RecordingHttp(drive)
    storage = GDriveStorage(
        transport=DriveTransport(tokens=StubTokens(), http=http),
        root_folder_id=drive.root_id,
    )

    storage.put(KEY, PDF, "application/pdf")
    storage.get(KEY)
    storage.delete(KEY)

    assert http.headers  # a put/get/delete really did make requests
    assert all(h.get("Authorization") == "Bearer tok" for h in http.headers), http.headers


def test_a_download_returns_raw_bytes_rather_than_a_parsed_body() -> None:
    """`bytes()` exists because a media download is not JSON: parsing it would corrupt
    a PDF, and `json()` would raise on the first byte."""
    drive = FakeDrive()
    transport = DriveTransport(tokens=StubTokens(), http=drive)
    storage = GDriveStorage(transport=transport, root_folder_id=drive.root_id)
    storage.put(KEY, PDF, "application/pdf")
    file_id = next(f.id for f in drive.files.values() if f.name == "v1.pdf")

    payload = transport.bytes(
        "GET",
        f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
        what="download da Google Drive",
    )

    assert payload == PDF


# --- Retry, unchanged from the class this was extracted from --------------------------


def test_a_transient_failure_is_retried_and_then_succeeds() -> None:
    sleeps: list[float] = []
    drive = FakeDrive()
    drive.fail_with = [429]
    transport = DriveTransport(tokens=StubTokens(), http=drive, sleep=sleeps.append)

    parsed = transport.json(
        "GET",
        f"https://www.googleapis.com/drive/v3/files/{drive.root_id}?supportsAllDrives=true",
        what="richiesta a Google Drive",
    )

    assert parsed["id"] == drive.root_id
    assert len(sleeps) == 1


def test_a_non_transient_client_error_is_not_retried() -> None:
    def _fail_if_called(seconds: float) -> None:
        raise AssertionError(f"should not have slept {seconds}s for a non-transient error")

    drive = FakeDrive()
    drive.fail_with = [403]
    transport = DriveTransport(tokens=StubTokens(), http=drive, sleep=_fail_if_called)

    with pytest.raises(Conflict) as excinfo:
        transport.json("GET", "https://www.googleapis.com/drive/v3/files", what="richiesta")

    assert excinfo.value.details["status"] == 403


# --- ServiceAccountTokens: today's provider, unchanged behaviour ----------------------


def test_service_account_tokens_ask_for_a_token_once_and_reuse_it() -> None:
    drive = FakeDrive()
    provider = ServiceAccountTokens(
        SERVICE_ACCOUNT_JSON, http=drive, sign_assertion=lambda claims: "assertion"
    )

    assert provider.access_token() == "at-1"
    assert provider.access_token() == "at-1"
    assert drive.token_requests == 1


def test_service_account_tokens_request_the_full_drive_scope() -> None:
    """`drive.file` cannot see a folder an admin shared beforehand (decision 4's second
    sanctioned setup), and a service account cannot drive a picker to be granted one.
    The scope is therefore part of this provider's contract, not an implementation
    detail -- asserted on the claims that were actually signed."""
    signed: list[dict[str, Any]] = []

    def _sign(claims: dict[str, Any]) -> str:
        signed.append(claims)
        return "assertion"

    ServiceAccountTokens(
        SERVICE_ACCOUNT_JSON, http=FakeDrive(), sign_assertion=_sign
    ).access_token()

    assert len(signed) == 1
    assert signed[0]["scope"] == "https://www.googleapis.com/auth/drive"
    assert signed[0]["iss"] == "pigro@example.iam.gserviceaccount.com"


def test_service_account_tokens_never_print_the_credentials() -> None:
    provider = ServiceAccountTokens(
        SERVICE_ACCOUNT_JSON, http=FakeDrive(), sign_assertion=lambda claims: "assertion"
    )
    assert "PRIVATE KEY" not in repr(provider)


# --- from_service_account: the constructor the factory keeps using -------------------


def test_from_service_account_round_trips_a_document() -> None:
    """The same put/get/delete/signed_url contract the conformance suite runs, asserted
    once here too: `from_service_account` is what `storage_from_settings` calls, so it
    has to build a storage that actually works and not merely one that constructs."""
    drive = FakeDrive()
    storage = GDriveStorage.from_service_account(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id=drive.root_id,
        http=drive,
        sign_assertion=lambda claims: "assertion",
    )

    storage.put(KEY, PDF, "application/pdf")
    assert storage.get(KEY) == PDF
    assert storage.signed_url(KEY, timedelta(minutes=5)) is None
    storage.verify_root_accessible()  # does not raise

    storage.delete(KEY)
    with pytest.raises(NotFound):
        storage.get(KEY)


# --- The real transport: a failure that never produced an HTTP response at all -------
# Moved here with `_urllib_call` itself, from test_storage_conformance.py: these three
# exercise the urllib adapter directly (every other test injects a fake and never
# reaches it), and they belong beside the function rather than beside the storage class
# that no longer owns it.


def test_urllib_call_turns_a_connection_failure_into_a_synthetic_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_connection_refused(request: object, timeout: float) -> None:
        raise urllib.error.URLError(ConnectionRefusedError("connection refused"))

    monkeypatch.setattr("urllib.request.urlopen", _raise_connection_refused)

    status, payload = _urllib_call("GET", "https://www.googleapis.com/drive/v3/files", {}, None)

    assert status == 599
    assert b"refused" in payload


def test_urllib_call_turns_a_timeout_into_a_synthetic_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_timeout(request: object, timeout: float) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _raise_timeout)

    status, payload = _urllib_call("GET", "https://www.googleapis.com/drive/v3/files", {}, None)

    assert status == 599
    assert b"timed out" in payload


def test_urllib_call_still_reports_a_real_http_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a new behaviour, but never directly covered before: a real HTTP error
    response (as opposed to no response at all) must still surface its own status,
    not the synthetic network-failure one."""

    def _raise_http_error(request: object, timeout: float) -> None:
        raise urllib.error.HTTPError(
            "https://www.googleapis.com/drive/v3/files",
            403,
            "Forbidden",
            None,  # type: ignore[arg-type]
            io.BytesIO(b'{"error": {"message": "Forbidden"}}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise_http_error)

    status, _ = _urllib_call("GET", "https://www.googleapis.com/drive/v3/files", {}, None)

    assert status == 403
