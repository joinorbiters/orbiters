"""The only module in this slice that knows a socket exists.

Shaped after `storage/gdrive.py`: `urllib.request`, no Google client library, and an
injectable seam that the fake transport replaces. What is faked is the *network*, so
URL construction, `q` construction, RFC822 assembly and error classification all run
for real in the tests -- which matters because those are precisely the parts Acme got
wrong, in code no test ever executed.

One deliberate widening over `gdrive.py`'s `HttpCall`: this seam carries **response
headers**. `gdrive.py` says in its own comment that not carrying them means Google's
`Retry-After` on a 429 is unreadable and its backoff is therefore a fixed schedule,
and that widening the type "would fix that properly" but was out of scope there. Here
it is in scope, and this is a new type rather than a change to that one, so nothing
`gdrive.py` was reviewed against moves.

Nothing in this module logs, and nothing that leaves it carries a request. The one
value that travels out of a failure is an `UpstreamFailure`: a status, a code from
Google's published vocabulary, and a number. The bearer token, the refresh token and
the client secret all pass through here, and none of them may reach an exception, a
`repr`, or a traceback.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from pigrocrm.core.gmail.errors import GoogleCallFailed, UpstreamFailure

HTTP_TIMEOUT_SECONDS = 30
# Same synthetic status and the same reasoning as gdrive.py: "no HTTP response was
# ever received" needs to travel through the one channel every other status uses,
# rather than a second failure path only the urllib adapter knows about.
NETWORK_ERROR_STATUS = 599
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, NETWORK_ERROR_STATUS})
# First attempt plus up to three retries: 0.5s, 1s, 2s.
MAX_HTTP_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 0.5
# A server-supplied Retry-After is honoured, but not unboundedly: a synchronous sync
# holding a request open for an hour because a header said so is an outage with extra
# steps. Public because the test that proves the clamp must not restate the number.
MAX_HONOURED_RETRY_AFTER_SECONDS = 30.0

# (method, url, headers, body) -> (status, body, response headers).
GmailCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes, dict[str, str]]]
SleepFn = Callable[[float], None]


def _retry_delay_seconds(attempt: int) -> float:
    # `1 << attempt`, not `2 ** attempt`: typeshed types `int.__pow__` as returning
    # `Any`, which would make this function's return type `Any` under mypy strict.
    return _RETRY_BASE_DELAY_SECONDS * (1 << attempt)


def _urllib_call(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(), dict(exc.headers.items()) if exc.headers else {}
    except (urllib.error.URLError, OSError) as exc:
        # `str(exc)` names the failure reason and possibly the target host -- always a
        # googleapis.com address, never sensitive -- but never the request's headers or
        # body, so no bearer token can reach it.
        return (
            NETWORK_ERROR_STATUS,
            json.dumps({"error": {"message": str(exc)}}).encode(),
            {},
        )


def _parse_retry_after(headers: dict[str, str]) -> float | None:
    """Seconds only. An HTTP-date is legal and Gmail does not send one, but a parser
    that raises on a legal header turns a retry into an outage.

    The name is matched case-insensitively because HTTP field names are (RFC 9110
    5.1) and no proxy in the path owes us a particular casing. Getting that wrong
    fails *quietly* -- straight back to the guessed schedule this seam was widened to
    replace -- which is why it has a test of its own.
    """
    for name, value in headers.items():
        if name.lower() != "retry-after":
            continue
        try:
            seconds = float(value.strip())
        except ValueError:
            return None
        if seconds <= 0:
            return None
        return min(seconds, MAX_HONOURED_RETRY_AFTER_SECONDS)
    return None


def _error_code(payload: bytes) -> str:
    """Google speaks two dialects and this slice touches both. The OAuth token
    endpoint answers `{"error": "invalid_grant"}` -- a bare string. The Gmail API
    answers `{"error": {"status": "UNAUTHENTICATED", ...}}` -- an object. Reading only
    one of them is how `invalid_grant` gets lost, which is the Acme defect.

    The `errors[0].reason` fallback is the older v1 shape, which the Gmail API still
    returns for some quota failures and which carries no `status` at all.
    """
    try:
        parsed = json.loads(payload.decode())
    except (ValueError, UnicodeDecodeError):
        return ""
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        status = error.get("status")
        if isinstance(status, str):
            return status
        errors = error.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            reason = errors[0].get("reason")
            if isinstance(reason, str):
                return reason
    return ""


def _decode_success(payload: bytes) -> dict[str, Any]:
    """An empty body is an empty object, not a parse error: `messages.trash` answers
    204 with nothing at all, and `json.loads(b"")` raises."""
    if not payload:
        return {}
    parsed = json.loads(payload.decode())
    if not isinstance(parsed, dict):
        # Google returns an object from every endpoint this slice calls. A bare list
        # or scalar means we are talking to something else -- a captive portal, a
        # proxy's error page that happens to be valid JSON -- and calling that a
        # success would push the surprise into whichever caller indexes the result.
        raise GoogleCallFailed(UpstreamFailure(200, "unexpected_payload", None), "risposta Google")
    return parsed


class GmailTransport:
    def __init__(self, *, http: GmailCall | None = None, sleep: SleepFn | None = None) -> None:
        self._http: GmailCall = http or _urllib_call
        # Injectable so the retry tests do not actually block for seconds.
        self._sleep: SleepFn = sleep or time.sleep

    def _call(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        what: str,
        *,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Every call goes through here so that retry-with-backoff applies uniformly
        rather than being reimplemented -- or forgotten -- at each call site.

        A 429 or a transient 5xx is retried; anything else is raised immediately,
        because a 4xx that is not a rate limit will not go away on its own and
        retrying it only delays the report. `invalid_grant` arrives as a 400 for
        exactly that reason: it is terminal, and this loop must not soften it.

        **`retry=False` exists for one caller and it is not a tuning knob.** A retry is
        safe only when a failed attempt is known to have had no effect, and that is true
        of every endpoint here except `users.messages.send`: a 599 or a 502 on a send
        means *no answer arrived*, not *nothing was sent*, and Gmail offers no idempotency
        key to make the second attempt the same operation as the first. Retrying it is
        therefore a mechanism for delivering a second copy of somebody's email to their
        client -- three of them, at this loop's four attempts -- and
        `test_gmail_reconcile.py` reproduced exactly that before this parameter existed.
        A send whose outcome is unknown is `incerto` and is resolved by asking, which is
        what `EmailSendService.reconcile` is for.
        """
        max_attempts = MAX_HTTP_ATTEMPTS if retry else 1
        for attempt in range(max_attempts):
            status, payload, response_headers = self._http(method, url, headers, body)
            if status < 400:
                return _decode_success(payload)

            failure = UpstreamFailure(
                status=status,
                error_code=_error_code(payload),
                retry_after=_parse_retry_after(response_headers),
            )
            last = attempt == max_attempts - 1
            if status not in _RETRYABLE_STATUSES or last:
                raise GoogleCallFailed(failure, what)
            # The server's own hint wins over our guess when it gave one.
            self._sleep(
                failure.retry_after
                if failure.retry_after is not None
                else _retry_delay_seconds(attempt)
            )
        raise AssertionError("unreachable: the loop either returns or raises")

    def json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
        what: str,
        retry: bool = True,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        encoded: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(body).encode()
        return self._call(method, url, headers, encoded, what, retry=retry)

    def form(self, url: str, fields: dict[str, str], *, what: str) -> dict[str, Any]:
        """POST `application/x-www-form-urlencoded`, for the OAuth token endpoint and
        nothing else. No `Authorization` header: the credentials are in the body, and
        this is the one call that carries the client secret. Nothing here logs."""
        return self._call(
            "POST",
            url,
            {"Content-Type": "application/x-www-form-urlencoded"},
            urlencode(fields).encode(),
            what,
        )
