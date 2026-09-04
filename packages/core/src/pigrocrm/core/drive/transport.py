"""Google Drive over the stdlib, and the two ways a token for it is obtained.

No Google client library: `urllib.request` and `json` are enough for the handful of
endpoints this needs, and adding `google-api-python-client` to `packages/core` would
drag a large transitive tree into the one package the architecture test keeps
deliberately small.

**Why this is a module of its own.** `storage/gdrive.py` used to do three jobs in one
class: sign a service-account JWT to get a token, run the HTTP mechanics (retry,
backoff, error decoding, the `Authorization` header), and decide where a document
lives on Drive. Slice 9 needs the middle job driven by a *user* OAuth token -- the
refresh token on `google_drive_accounts`, renewed through the `GoogleTokenClient`
slice 5 already has -- while the placement rules stay exactly as they are (spec 5.4).
So the credential became a seam: `DriveTransport` asks a `TokenProvider` for a bearer
token and knows nothing else about it, and there are two providers,
`ServiceAccountTokens` (what every existing installation is configured with) and
`UserTokens` (the connected-account credential). The fake in `tests/fakes/fake_drive.py`
does not change, because what it fakes -- the network -- did not move.

Nothing here logs. A refresh token, a private key and a bearer token all pass through
this module, and none of them may reach an exception message, a `repr` or a traceback:
`_decode` reports Google's own `error.message` and never the request, and neither
provider has a generated `repr` that would print its own credential (which is why
`UserTokens`, being a dataclass, marks its refresh token `repr=False`).
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import UUID

import jwt

from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.tokens import GoogleTokenClient

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# Not "drive.file". That narrower scope only grants visibility into files the app
# itself created or that a user opened through an interactive picker -- neither of
# which happens for decision 4's second sanctioned setup, "a folder explicitly shared
# with [the service account]" by an admin who created it beforehand. A service
# account cannot drive a picker, so under `drive.file` that folder would simply not
# exist as far as this class could see, and every call would 404. The broad `drive`
# scope is what a service account managing a pre-existing, admin-shared root actually
# needs.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
# Operator note, not a code fix: this scope is bearer-broad -- wider than a single
# Shared-Drive deployment strictly needs, since a leaked access token would grant
# access to every Shared Drive and folder this service account can see, not only
# PigroCRM's own root. Keep the blast radius small at the Google Cloud console
# instead: share only PIGROCRM_GDRIVE_ROOT_FOLDER_ID (and nothing else) with this
# service account's address, and never reuse the same service account for any other
# integration. A `UserTokens` installation has no such note to read: its scopes are
# the ones the titolare granted on the consent screen (`DRIVE_REQUESTED_SCOPES`).
TOKEN_LIFETIME_SECONDS = 3600
# Refresh a minute early rather than discovering expiry mid-upload.
TOKEN_REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 30

# A synthetic status for "no HTTP response was ever received" (DNS failure,
# connection refused, a timeout) -- the "network connect timeout" code some proxies
# use for exactly this shape, chosen so `_call`'s retry logic and `_decode`'s error
# reporting can treat it exactly like any server-issued status, rather than needing a
# second failure channel only `_urllib_call` knows about.
NETWORK_ERROR_STATUS = 599
# 429 (rate limited) and 5xx (transient server-side failure) are worth retrying;
# anything else -- a 4xx other than 429 in particular -- is a client error that will
# not go away on its own, so retrying it only delays reporting a failure.
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, NETWORK_ERROR_STATUS})
# First attempt plus up to three retries. Exponential: 0.5s, 1s, 2s between them.
_MAX_HTTP_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 0.5
# The entity name every failure of this transport is reported under. Drive is reached
# for exactly one reason in this system -- the bytes of a document -- and the API and
# the MCP adapter both render `Conflict.details["entity"]`, so changing it would change
# what a user reads for a Google outage.
_ENTITY = "document_blob"


def _retry_delay_seconds(attempt: int) -> float:
    # `1 << attempt`, not `2**attempt`: typeshed types `int.__pow__` as returning
    # `Any` (to accommodate a negative exponent producing a float), which would make
    # this whole expression -- and this function's return value -- `Any` under mypy
    # strict mode. A left shift has no such escape hatch and stays a plain `int`.
    return _RETRY_BASE_DELAY_SECONDS * (1 << attempt)


# (method, url, headers, body) -> (status, body). Injected in tests; the default is
# `_urllib_call` below. Nothing above this seam knows what a socket is.
#
# Deliberately does not carry response headers: Google's real `Retry-After` header on
# a 429 cannot be read through this seam, so `_call`'s backoff below is a fixed
# exponential schedule, not one driven by the server's own hint. Widening this type to
# `tuple[int, bytes, dict[str, str]]` would fix that properly, but it is an interface
# every test and the fake transport already depend on; changing it is out of scope for
# a fix that has to land without breaking the contract the rest of this module was
# reviewed against. (`gmail/transport.py` made the wider choice for its own, newer
# seam, and says so.)
HttpCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]
SignAssertion = Callable[[dict[str, Any]], str]
SleepFn = Callable[[float], None]


def _urllib_call(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        # No HTTP response was ever received, so there is no real status code to
        # report -- `URLError` wraps DNS failure and connection-refused, and a bare
        # `OSError`/`TimeoutError` covers the rest. `str(exc)` names the failure
        # reason (and possibly the target host, always a googleapis.com address, never
        # sensitive) but never the request's headers or body, so no bearer token or
        # key material can reach it.
        return NETWORK_ERROR_STATUS, json.dumps({"error": {"message": str(exc)}}).encode()


def _call(
    http: HttpCall,
    sleep: SleepFn,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> tuple[int, bytes]:
    """Every HTTP call this module makes goes through here, not through `http`
    directly, so retry-with-backoff applies uniformly instead of being
    reimplemented -- or forgotten -- at each call site.

    Retries a `429` or a transient `5xx` (`_RETRYABLE_STATUSES`) with exponential
    backoff, up to `_MAX_HTTP_ATTEMPTS` attempts total, then returns whatever the
    last attempt got so the caller's own error handling (`_decode`) reports it.
    Anything else -- including a network failure normalised to
    `NETWORK_ERROR_STATUS` by `_urllib_call` -- is retried the same way, since it is
    just as transient; anything *not* in that set is returned immediately.

    A module-level function rather than a `DriveTransport` method because
    `ServiceAccountTokens` needs the identical loop for the token endpoint and cannot
    reach it through a `DriveTransport`: the transport is the thing that depends on a
    token provider, not the other way round. One loop, two callers, no duplication.
    """
    status, payload = http(method, url, headers, body)
    for attempt in range(_MAX_HTTP_ATTEMPTS - 1):
        if status not in _RETRYABLE_STATUSES:
            break
        sleep(_retry_delay_seconds(attempt))
        status, payload = http(method, url, headers, body)
    return status, payload


def _decode(status: int, payload: bytes, what: str) -> dict[str, Any]:
    """The parsed body, or a `Conflict` naming what failed and with which status.

    Google's own message is included but the raw body is not: it can carry the folder
    tree and the service-account address, neither of which belongs in a problem
    document a browser will render. Never the request headers or body either, so no
    bearer token or key material can reach an exception message from here.

    `what` travels in the details as well as in the sentence, and that is load-bearing
    rather than decorative: obtaining the token is itself an HTTP call through this
    same function, so a caller that inspects a failure -- `GDriveStorage.get` turning a
    404 into `NotFound`, `verify_root_accessible` turning any failure into "share the
    folder" -- would otherwise mistake a refused *credential* for a missing document or
    an unshared folder, and send somebody to fix the wrong thing.
    """
    if status >= 400:
        detail = ""
        try:
            detail = str(json.loads(payload.decode()).get("error", {}).get("message", ""))
        except (ValueError, AttributeError):
            detail = ""
        raise Conflict(
            _ENTITY,
            f"{what} fallita ({status}){': ' + detail if detail else ''}",
            status=status,
            what=what,
        )
    return json.loads(payload.decode()) if payload else {}


class TokenProvider(Protocol):
    """Where a bearer token for Drive comes from, and how to say it is stale.

    `forget` is not a convenience: a provider caches, and a 401 from Drive is the one
    failure a *fresh* token fixes rather than a retry with the same one (see
    `DriveTransport.json`). Both implementations cache, so both need to be told.
    """

    def access_token(self) -> str: ...

    def forget(self) -> None: ...


class ServiceAccountTokens:
    """The credential every installation configured before slice 9: a service account
    whose private key signs a JWT that Google exchanges for an access token.

    Kept as-is, deliberately -- "il service account resta supportato per chi lo aveva
    configurato" (spec 5.4). Its operational requirement has not changed either: a
    service account has no Drive storage quota of its own, so the root folder must live
    on a Shared Drive or be shared with this account's address (see
    `GDriveStorage.verify_root_accessible`).
    """

    def __init__(
        self,
        service_account_json: str,
        *,
        http: HttpCall | None = None,
        sign_assertion: SignAssertion | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._credentials: dict[str, Any] = json.loads(service_account_json)
        self._http: HttpCall = http or _urllib_call
        # Injectable so tests can prove the rest of this module -- URL building, query
        # escaping, multipart framing, error handling -- without a real RSA key ever
        # existing in this repository.
        self._sign: SignAssertion = sign_assertion or self._sign_with_private_key
        # Injectable so retry-with-backoff tests don't actually block for seconds at a
        # time; production gets real `time.sleep`.
        self._sleep: SleepFn = sleep or time.sleep
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _sign_with_private_key(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._credentials["private_key"], algorithm="RS256")

    def access_token(self) -> str:
        if self._token is not None and time.time() < self._token_expires_at:
            return self._token
        issued = int(time.time())
        assertion = self._sign(
            {
                "iss": self._credentials["client_email"],
                "scope": DRIVE_SCOPE,
                "aud": self._credentials.get("token_uri", GOOGLE_TOKEN_URL),
                "iat": issued,
                "exp": issued + TOKEN_LIFETIME_SECONDS,
            }
        )
        body = urlencode(
            {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        ).encode()
        status, payload = _call(
            self._http,
            self._sleep,
            "POST",
            self._credentials.get("token_uri", GOOGLE_TOKEN_URL),
            {"Content-Type": "application/x-www-form-urlencoded"},
            body,
        )
        parsed = _decode(status, payload, "autenticazione Google")
        self._token = str(parsed["access_token"])
        self._token_expires_at = time.time() + TOKEN_LIFETIME_SECONDS - TOKEN_REFRESH_MARGIN_SECONDS
        return self._token

    def forget(self) -> None:
        self._token = None
        self._token_expires_at = 0.0


@dataclass(frozen=True, kw_only=True)
class UserTokens:
    """The Drive credential of a connected Google account: a refresh token on
    `google_drive_accounts`, exchanged for an access token by the same
    `GoogleTokenClient` the Gmail side already uses.

    No cache of its own, on purpose. `GoogleTokenClient` already caches per account id
    on Google's own `expires_in`, and a second cache in front of it would be a second
    place a token sits, a second clock to get wrong, and a second thing `forget` would
    have to clear consistently. `forget` therefore just drops the client's entry --
    which is also what `GoogleDriveOAuthService` does on disconnect and on
    re-authorisation, for the same reason.

    `refresh_token` is `repr=False`: a dataclass has a generated `repr`, and a
    generated `repr` prints itself into every traceback that has one of these in a
    frame, into `logger.debug("%s", provider)`, and into a pytest failure dump. Same
    rule, and the same reason, as `gmail/tokens.py`'s own dataclasses.
    """

    account_id: UUID
    email_address: str
    refresh_token: str = field(repr=False)
    tokens: GoogleTokenClient

    def access_token(self) -> str:
        return self.tokens.access_token(
            account_id=self.account_id,
            email_address=self.email_address,
            refresh_token=self.refresh_token,
        )

    def forget(self) -> None:
        self.tokens.forget(self.account_id)


class DriveTransport:
    """The Drive HTTP surface: one bearer token per request, retry with backoff, and
    Google's errors turned into a `Conflict` a caller can render.

    Knows nothing about folders, keys or documents -- that is `GDriveStorage`'s job --
    and nothing about where its token comes from beyond `TokenProvider`.
    """

    def __init__(
        self,
        *,
        tokens: TokenProvider,
        http: HttpCall | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._tokens = tokens
        self._http: HttpCall = http or _urllib_call
        self._sleep: SleepFn = sleep or time.sleep

    def _attempt(
        self, method: str, url: str, body: bytes | None, content_type: str | None
    ) -> tuple[int, bytes]:
        headers = {"Authorization": f"Bearer {self._tokens.access_token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        return _call(self._http, self._sleep, method, url, headers, body)

    def _send(
        self, method: str, url: str, body: bytes | None, content_type: str | None
    ) -> tuple[int, bytes]:
        """One attempt, plus exactly one more if Drive answered 401.

        A 401 is the one failure a *fresh* token fixes: the cached one was minted
        before a revocation, a re-consent, or a scope change, and `_call`'s retry loop
        deliberately does not touch it because repeating the same request with the same
        stale token cannot succeed. So the provider is told to drop it and the request
        is made once more -- once, not in a loop: a grant that is genuinely revoked
        answers 401 to every attempt, and spinning against Google would replace a clear
        `Conflict` with an outage.
        """
        status, payload = self._attempt(method, url, body, content_type)
        if status == 401:
            self._tokens.forget()
            status, payload = self._attempt(method, url, body, content_type)
        return status, payload

    def json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        what: str,
    ) -> dict[str, Any]:
        status, payload = self._send(method, url, body, content_type)
        return _decode(status, payload, what)

    # `bytes` shadows the builtin inside this class body from here on, so this method
    # is defined last: an annotation is evaluated in the class namespace at `def` time,
    # and a later `-> bytes` would resolve to this method instead of the type (the
    # exact failure `tests/test_module_imports.py` exists to catch). The name is worth
    # it -- `transport.bytes(...)` is what the call site means -- and nothing needs to
    # be defined after it.
    def bytes(self, method: str, url: str, *, what: str) -> bytes:
        """The response body itself, undecoded: a media download is a PDF, not JSON.

        A failure is still reported through `_decode`, which raises before returning,
        so the success path here is only ever reached with real bytes in hand.
        """
        status, payload = self._send(method, url, None, None)
        if status >= 400:
            _decode(status, payload, what)
        return payload
