"""The server half of the Orbiters signup conversion: OpenAI's Conversions API.

The browser already measures the signup through the pixel. This exists because that
event is the one that gets lost: an ad blocker, a privacy setting, a network that drops
the SDK, a tab closed before the ping leaves. A conversion the platform never hears
about is a campaign the owner cannot judge.

**The two halves are one conversion, not two.** OpenAI deduplicates on (pixel id, event
name, event id) and keeps the first arrival, so the landing generates one id per
submitted form, sends it here in the body and passes the same value to `oaiq("measure",
…, {event_id})`. Whichever arrives first counts; the other is dropped. The whole design
rests on that id being the same string on both sides, which is why the landing -- and
not this module -- makes it.

**What is sent, exactly.** The event type, the moment, the URL of the signup page, and
`{"type": "customer_action"}`. Plus, for matching: the click identifier from the landing
URL (`oppref`), the `__obref` cookie the SDK set on our own domain, and the visitor's IP
and user agent. No name, no LinkedIn profile, and the address only as a SHA-256 hash and
only if this installation switched that on (`openai_conversions_send_hashed_email`,
off by default) -- because a hash of an email is still that person's identifier, and
handing it to an ad platform is a decision for whoever runs the site, not a default.

**Nothing here can break a signup.** The row is committed before this is reached, the
call runs in a background task after the response has been sent, and every failure --
a 4xx, a timeout, a DNS error, a body that will not encode -- comes back as a
`ConversionOutcome` with `sent=False`. There is no exception path out of `send`.

Nothing logs and nothing that passes through reaches an exception argument: the API key
is a credential with write access to the conversion source, and the email hash is a
person. What may travel is a status code.
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orbiters_core.config import Settings
from orbiters_core.http import HTTP_TIMEOUT_SECONDS, NETWORK_ERROR_STATUS, HttpCall, urllib_call

# Documented endpoint. The pixel id goes in the query string, the key in the header.
CONVERSIONS_URL = "https://bzr.openai.com/v1/events"
REGISTRATION_COMPLETED = "registration_completed"
CUSTOMER_ACTION = "customer_action"
WEB = "web"

# A user agent is a header somebody else writes and it can be arbitrarily long. Cut
# rather than refused: a truncated user agent is still a matching signal, and dropping
# the event over a header would be losing the conversion to save a string.
USER_AGENT_MAX_LENGTH = 512


@dataclass(frozen=True)
class Visitor:
    """What the request knew about whoever signed up, as far as it may be passed on.

    Every field optional, because every one of them can legitimately be missing: a
    visitor who arrived without clicking an ad has no `oppref`, one whose browser
    blocked the SDK has no `obref`, and a proxy can hide the address. An event with
    none of them is still worth sending -- it is a conversion that happened -- it is
    simply harder for the platform to attribute.
    """

    oppref: str | None = None
    obref: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    # Raw address. Hashed inside `send`, and only when the installation asked for it to
    # be sent at all -- never stored, never logged, never put in an exception.
    email: str | None = None


@dataclass(frozen=True)
class ConversionOutcome:
    """Whether the platform took the event. `sent` is the only thing a caller acts on;
    `status` is there so a verification command can print something true."""

    sent: bool
    status: int
    # Present only when the answer was not a success, and only as the body OpenAI
    # returned. It carries no request data of ours.
    detail: str = ""


@dataclass
class ConversionsPixel:
    """One conversion source, addressed by its pixel id and its key.

    A dataclass rather than a service: it holds no session, reads no database and makes
    no decision about the domain. It formats one event and posts it.
    """

    pixel_id: str
    api_key: str
    http: HttpCall | None = None
    timeout_seconds: float = HTTP_TIMEOUT_SECONDS
    send_hashed_email: bool = False
    # Overridable so a test can point the whole thing at a fake without monkeypatching
    # a module constant.
    url: str = CONVERSIONS_URL
    _clock: Callable[[], float] = field(default=time.time, repr=False)

    def send(
        self,
        *,
        event_id: str,
        source_url: str,
        visitor: Visitor | None = None,
        validate_only: bool = False,
    ) -> ConversionOutcome:
        """One `registration_completed`. Never raises.

        `validate_only` asks OpenAI to check the event and not record it, which is what
        `orbiters conversions-check` uses to tell the owner whether the key works
        without inventing a conversion to find out.
        """
        body = self._body(
            event_id=event_id,
            source_url=source_url,
            visitor=visitor or Visitor(),
            validate_only=validate_only,
        )
        try:
            payload = json.dumps(body).encode()
        except (TypeError, ValueError):
            # Unreachable with the types above, and cheap to answer honestly rather
            # than to let it escape into a background task where nobody would see it.
            return ConversionOutcome(sent=False, status=0, detail="corpo non serializzabile")
        call = self.http or urllib_call
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            status, answer = call("POST", f"{self.url}?pid={self.pixel_id}", headers, payload)
        except Exception:  # noqa: BLE001 - see the module docstring: no failure escapes
            # Deliberately every exception. A background task that raises is a traceback
            # in the server's output with a bearer token in the request it was making,
            # and the alternative to catching it is not a better error -- it is a
            # signup that looks broken to nobody, because the response already went out.
            return ConversionOutcome(sent=False, status=NETWORK_ERROR_STATUS)
        if 200 <= status < 300:
            return ConversionOutcome(sent=True, status=status)
        return ConversionOutcome(sent=False, status=status, detail=_short(answer))

    # ---- the body ---------------------------------------------------------------------

    def _body(
        self, *, event_id: str, source_url: str, visitor: Visitor, validate_only: bool
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "id": event_id,
            "type": REGISTRATION_COMPLETED,
            # Milliseconds, and the platform refuses anything older than seven days or
            # more than ten minutes in the future. This is sent seconds after the row
            # was written, so the window is never a question in practice.
            "timestamp_ms": int(self._clock() * 1000),
            "source_url": source_url,
            "action_source": WEB,
            "data": {"type": CUSTOMER_ACTION},
        }
        if visitor.oppref:
            # Top level and not under `user`: it identifies the *click*, not the person,
            # and it is passed exactly as it arrived (OpenAI's own instruction).
            event["oppref"] = visitor.oppref
        user = self._user(visitor)
        if user:
            event["user"] = user
        return {"validate_only": validate_only, "events": [event]}

    def _user(self, visitor: Visitor) -> dict[str, Any]:
        """The matching signals, and only the ones this installation allows.

        Built as a dict that may end up empty, and an empty one is left out of the event
        entirely: `"user": {}` and no `user` key mean the same thing to the platform, and
        the second is the honest shape for "we know nothing about this visitor".
        """
        user: dict[str, Any] = {}
        if visitor.obref:
            user["obref"] = visitor.obref
        if visitor.ip_address:
            user["ip_address"] = visitor.ip_address
        if visitor.user_agent:
            user["user_agent"] = visitor.user_agent[:USER_AGENT_MAX_LENGTH]
        if self.send_hashed_email and visitor.email:
            user["emails_sha256"] = [hashed_email(visitor.email)]
        return user


def hashed_email(email: str) -> str:
    """SHA-256 of the address, trimmed and lowercased, as lowercase hex.

    The normalisation is OpenAI's and is not optional: they hash `ada@studio.it`, so a
    hash of `  Ada@Studio.it ` matches nothing at all. Public because the test that
    proves what leaves this process must be able to compute the expected value without
    restating the algorithm.
    """
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def pixel_from_settings(settings: Settings) -> ConversionsPixel | None:
    """The configured conversion source, or `None` on an installation that has none.

    `None` and not a disabled object: an installation that never pasted a pixel id is
    not an installation whose conversions are failing, and a caller that has to check
    for `None` is a caller that cannot forget the difference. Both halves are required
    -- an id without a key cannot post, and a key without an id has nowhere to post to.
    """
    if not settings.openai_pixel_id or not settings.openai_conversions_api_key:
        return None
    return ConversionsPixel(
        pixel_id=settings.openai_pixel_id,
        api_key=settings.openai_conversions_api_key,
        send_hashed_email=settings.openai_conversions_send_hashed_email,
    )


def _short(answer: bytes) -> str:
    """The first line of OpenAI's own error, bounded. Their words about our event, which
    is the one thing worth keeping from a refusal; it contains nothing of ours."""
    return answer.decode("utf-8", errors="replace").strip().splitlines()[0][:200] if answer else ""
