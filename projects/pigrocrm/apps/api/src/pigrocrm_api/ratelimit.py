"""One small token bucket per client, for the public routes of the signup.

There was no limiter anywhere in this API until ORB-173: everything else is behind a
session or a token. `POST /api/tenants/membro` is unauthenticated by design and relays
each question to the hub, so without a bucket anyone could sweep a mailing list through
it. The shape is the hub's `orbiters_api.ratelimit`, which itself came from PigroCRM's
old signup route on 2026-09-09; the two products share no code (`AGENTS.md`), so this
is a copy on purpose and deliberately tiny rather than a dependency.
"""

import threading
import time

from fastapi import HTTPException, Request, status

# A person filling in a form needs two or three attempts, not five; five a minute
# leaves room for a double click, a reload on a slow connection, and a household
# sharing one address, while making a scripted sweep of a mailing list pointless.
REQUESTS_PER_MINUTE = 5
RETRY_AFTER_SECONDS = 60
# Bounds the table: an attacker who varies `X-Forwarded-For` on every request must not
# be able to grow it without limit. Full buckets (clients that have gone quiet) are
# dropped first, and forgetting a client only hands it a fresh bucket, so an
# overflowing table makes the limiter too lenient and never locks anybody out.
MAX_TRACKED_CLIENTS = 4096

# client key -> (tokens left, when they were last counted). Per process, on purpose:
# with several workers the effective ceiling is `REQUESTS_PER_MINUTE` times the number
# of workers, which is the honest cost of not introducing shared state for a signup
# form. A real cap belongs at the reverse proxy (`limit_req`), and this is the floor
# under it, not a substitute for it.
_buckets: dict[str, tuple[float, float]] = {}
_buckets_lock = threading.Lock()


def reset_rate_limit() -> None:
    """Forgets every client. For tests, which would otherwise spend one test's budget
    on the next one, since the table lives for the life of the process."""
    with _buckets_lock:
        _buckets.clear()


def client_key(request: Request) -> str:
    """The visitor's address as far as it can be known. nginx sets `X-Real-IP` and
    appends to `X-Forwarded-For`, and the API sees the proxy's own address, so without a
    header every visitor would share one bucket. In `X-Forwarded-For` only the LAST hop
    is trusted: the first is whatever the visitor typed, and keying on it lets a script
    mint a fresh bucket per request. A speed bump against floods and sweeps, not a
    security control: a real cap is nginx's `limit_req`."""
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "sconosciuto"


def _refilled(tokens: float, last_seen: float, now: float) -> float:
    return min(
        float(REQUESTS_PER_MINUTE),
        tokens + (now - last_seen) * REQUESTS_PER_MINUTE / 60.0,
    )


def _forget_the_quiet_ones(now: float) -> None:
    for key in [
        key
        for key, (tokens, last_seen) in _buckets.items()
        if _refilled(tokens, last_seen, now) >= REQUESTS_PER_MINUTE
    ]:
        del _buckets[key]
    if len(_buckets) > MAX_TRACKED_CLIENTS:
        # Still full of active clients: keep the ones seen most recently.
        for key in sorted(_buckets, key=lambda key: _buckets[key][1])[:-MAX_TRACKED_CLIENTS]:
            del _buckets[key]


def spend_one(request: Request) -> None:
    """A token bucket per client, refilling at `REQUESTS_PER_MINUTE`."""
    key = client_key(request)
    now = time.monotonic()
    with _buckets_lock:
        tokens, last_seen = _buckets.get(key, (float(REQUESTS_PER_MINUTE), now))
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
