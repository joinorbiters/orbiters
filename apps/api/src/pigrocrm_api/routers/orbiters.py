"""The one public write in the API: a signup for the Orbiters community.

No `ActorDep`, deliberately. The page that posts here is the landing, and its visitor
has no account -- that is the whole point of the form. Everything else that protects
the CRM stays where it was: this router reaches only the `orbiters` database
(`OrbitersSessionDep`), never the CRM's session, so an unauthenticated request cannot
touch a customer, a deal or an invoice through it.

Two properties follow from being public, and both live here:

- The answer is `SignupAck` -- `{"ok": true}` and a 201, the same for a first signup
  and for an address already on the list. It used to be the stored row, which turned
  this endpoint into an oracle: post somebody else's address and the response handed
  back their real nome, cognome and LinkedIn profile. The whole row is admin-gated
  (`list_orbiters_signups`) and stays that way.
- A small per-client rate limit, below. There is no limiter anywhere else in this API
  (nothing else is unauthenticated), so this is the one that exists, and it is
  deliberately tiny rather than a dependency.
"""

import threading
import time

from fastapi import APIRouter, HTTPException, Request, status

from pigrocrm.core.orbiters import SignupAck, SignupCreate, SignupService
from pigrocrm_api.deps import OrbitersSessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/orbiters", tags=["orbiters"], responses=PROBLEM_RESPONSES)

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

    nginx sets `X-Real-IP` and appends to `X-Forwarded-For` for this route
    (deploy/nginx/orbiters-proxy.conf) and the API sees the proxy's own address, so
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


@router.post("/signups", response_model=SignupAck, status_code=status.HTTP_201_CREATED)
def subscribe(data: SignupCreate, session: OrbitersSessionDep, request: Request) -> SignupAck:
    """201 and `{"ok": true}`, whether the address was new or already on the list.

    The person is on the list either way, which is the only thing the page says and the
    only thing this answers: telling a caller *which* of the two happened is telling
    them whether an address they do not own is a subscriber.
    """
    _spend_one_signup(request)
    SignupService(session).subscribe(data)
    return SignupAck()
