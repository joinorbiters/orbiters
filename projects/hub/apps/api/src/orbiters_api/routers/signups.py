"""`POST /api/orbiters/signups`: a signup for the Orbiters community.

Public, deliberately: the page that posts here is the community site, and its visitor
has no account -- that is the whole point of the form. The path is the one the website
has always posted to; it moved here from PigroCRM's API on 2026-09-09 with its body,
its answer and its limiter unchanged, so the form and the ad conversion never noticed.

Two properties follow from being public, and both live here:

- The answer is `SignupAck` -- `{"ok": true}` and a 201, the same for a first signup
  and for an address already on the list. It used to be the stored row, which turned
  this endpoint into an oracle: post somebody else's address and the response handed
  back their real nome, cognome and LinkedIn profile. The whole row is admin-gated
  (the admin API of the hub, step 3 of its spec) and stays that way.
- A small per-client rate limit, below, deliberately tiny rather than a dependency. The
  public writes the hub grows (freelancers, companies) share it.

The one thing this route does besides writing the row is measure the ad conversion, in a
background task, after the response. `orbiters_core.conversions` says what is sent
and what deliberately is not; the reason it is here rather than in `SignupService` is
that everything it needs beyond the id -- the visitor's address, their user agent, the
`__obref` cookie -- is a property of this HTTP request and of nothing else.
"""

import ipaddress
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from orbiters_api.deps import SessionDep, SettingsDep
from orbiters_core.conversions import Visitor, pixel_from_settings
from orbiters_core.schemas import SignupAck, SignupCreate
from orbiters_core.service import SignupService

# The cookie the measurement SDK sets on our own domain. First-party, so the browser
# sends it to this endpoint too, which is the only reason the server event can carry it.
OBREF_COOKIE = "__obref"

router = APIRouter(prefix="/api/orbiters", tags=["orbiters"])

# A person filling in a form needs two or three attempts, not five; five a minute
# leaves room for a double click, a reload on a slow connection, and a household
# sharing one address, while making a scripted sweep of a mailing list pointless.
SIGNUPS_PER_MINUTE = 5
RETRY_AFTER_SECONDS = 60
# Bounds the table: an attacker who varies `X-Forwarded-For` on every request must not
# be able to grow it without limit. Full buckets (clients that have gone quiet) are
# dropped first, and forgetting a client only hands it a fresh bucket, so an
# overflowing table makes the limiter too lenient and never locks anybody out.
MAX_TRACKED_CLIENTS = 4096

# client key -> (tokens left, when they were last counted). Per process, on purpose:
# with several workers the effective ceiling is `SIGNUPS_PER_MINUTE` times the number
# of workers, which is the honest cost of not introducing shared state for a landing
# form. A real cap belongs at the reverse proxy (`limit_req`), and this is the floor
# under it, not a substitute for it.
_buckets: dict[str, tuple[float, float]] = {}
_buckets_lock = threading.Lock()


def reset_signup_rate_limit() -> None:
    """Forgets every client. For tests, which would otherwise spend one test's budget
    on the next one, since the table lives for the life of the process."""
    with _buckets_lock:
        _buckets.clear()


def _client_key(request: Request) -> str:
    """The visitor's address as far as it can be known.

    nginx sets `X-Real-IP` and appends to `X-Forwarded-For` for this route and the API
    sees the proxy's own address, so
    without reading a header every visitor would share one bucket and five signups a
    minute would be the whole world's budget. `X-Real-IP` is what nginx observed; in
    `X-Forwarded-For` only the LAST hop is — the first is whatever the visitor typed,
    and keying on it let a script mint a fresh bucket per request by changing the
    header. Still a speed bump against floods and double clicks, not a security
    control: a real cap is nginx's `limit_req`.
    """
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "sconosciuto"


def _refilled(tokens: float, last_seen: float, now: float) -> float:
    return min(
        float(SIGNUPS_PER_MINUTE),
        tokens + (now - last_seen) * SIGNUPS_PER_MINUTE / 60.0,
    )


def _forget_the_quiet_ones(now: float) -> None:
    for key in [
        key
        for key, (tokens, last_seen) in _buckets.items()
        if _refilled(tokens, last_seen, now) >= SIGNUPS_PER_MINUTE
    ]:
        del _buckets[key]
    if len(_buckets) > MAX_TRACKED_CLIENTS:
        # Still full of active clients: keep the ones seen most recently.
        for key in sorted(_buckets, key=lambda key: _buckets[key][1])[:-MAX_TRACKED_CLIENTS]:
            del _buckets[key]


def _spend_one_signup(request: Request) -> None:
    """A token bucket per client, refilling at `SIGNUPS_PER_MINUTE`."""
    key = _client_key(request)
    now = time.monotonic()
    with _buckets_lock:
        tokens, last_seen = _buckets.get(key, (float(SIGNUPS_PER_MINUTE), now))
        tokens = _refilled(tokens, last_seen, now)
        if tokens < 1.0:
            _buckets[key] = (tokens, now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Troppe richieste da qui. Riprova tra un minuto.",
                headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
            )
        _buckets[key] = (tokens - 1.0, now)
        if len(_buckets) > MAX_TRACKED_CLIENTS:
            _forget_the_quiet_ones(now)


def _visitor_ip(request: Request) -> str | None:
    """The visitor's address, or `None` when what we have is not one.

    `_client_key` above answers the same question for the rate limiter, which needs
    *a* key and is happy with `"sconosciuto"`. This one is a value forwarded to a third
    party as an IP address, so a string that is not an IP must become no field at all
    rather than nonsense in somebody else's database.
    """
    candidate = _client_key(request)
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _measure_the_conversion(data: SignupCreate, request: Request, settings: SettingsDep) -> None:
    """Schedules nothing and decides nothing: builds the event and returns.

    Called from a background task, so it runs *after* the response has been sent. Two
    things follow, and both are the point: the person who signed up never waits for
    OpenAI, and an outage there cannot turn a signup that was written into an error.
    """
    pixel = pixel_from_settings(settings)
    if pixel is None:
        return
    pixel.send(
        # The id the landing already gave the browser event, so the two are one
        # conversion. When there is none -- a client that posted without the pixel, a
        # curl -- one is invented here: it makes the event unpairable, which is correct,
        # since no browser event exists to pair it with.
        event_id=data.pixel_event_id or uuid4().hex,
        source_url=settings.signup_url,
        visitor=Visitor(
            oppref=data.oppref,
            obref=request.cookies.get(OBREF_COOKIE),
            ip_address=_visitor_ip(request),
            user_agent=request.headers.get("user-agent"),
            email=data.email,
        ),
    )


@router.post("/signups", response_model=SignupAck, status_code=status.HTTP_201_CREATED)
def subscribe(
    data: SignupCreate,
    session: SessionDep,
    request: Request,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> SignupAck:
    """201 and `{"ok": true}`, whether the address was new or already on the list.

    The person is on the list either way, which is the only thing the page says and the
    only thing this answers: telling a caller *which* of the two happened is telling
    them whether an address they do not own is a subscriber.

    The ad conversion is measured after the answer, never before it: see
    `_measure_the_conversion`. It is scheduled even for an address already on the list,
    because the browser fires its own event on the same submit and the two carry one id
    -- suppressing the server half would not remove that event, it would only remove the
    half that survives an ad blocker.
    """
    _spend_one_signup(request)
    SignupService(session).subscribe(data)
    background.add_task(_measure_the_conversion, data, request, settings)
    return SignupAck()
