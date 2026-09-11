"""The one question the CRM asks the Orbiters hub: does this address belong to a member?

The signup greets a community member by name and skips the questions the hub already
answered (spec 2026-09-12 §6.3, ORB-173). The hub is reached through its own API,
`GET /api/hub/members/lookup`, with the token the two hosts already share for the
registry of spaces in the other direction (ORB-142): `PIGROCRM_REGISTRY_TOKEN` here,
`ORBITERS_PIGRO_REGISTRY_TOKEN` there. Nothing from the hub is imported and no database
of it is opened.

Every failure is the same answer, `MemberLookup(membro=False)`: no token, no URL, a
refused connection, a timeout, a status other than 2xx, a body that is not the shape.
The community is the fast lane of the signup, never a gate, so a hub that is down must
cost the person nothing but the greeting. Nothing here logs: the only thing worth
logging would be the address, and the address is the one thing that must not reach a
log.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, ValidationError

from pigrocrm.core.config import Settings

LOOKUP_PATH = "/api/hub/members/lookup"
# Short on purpose: the wizard is waiting on this answer, and a hub that takes longer
# than this to say «member» has already cost more than the greeting is worth.
HTTP_TIMEOUT_SECONDS = 5
USER_AGENT = "pigrocrm/0.1 (+https://pigro.joinorbiters.com)"

# (method, url, headers) -> (status, body). Narrower than the Gmail and Drive seams:
# no body goes out, no response header is read, and there is no retry to inform.
HttpCall = Callable[[str, str, dict[str, str]], tuple[int, bytes]]


class MemberLookup(BaseModel):
    """What the hub says about an address: whether a freelancer with it exists, and the
    two names if so. Extra keys are ignored so the hub may grow its answer without
    breaking the signup."""

    model_config = ConfigDict(extra="ignore")

    membro: bool
    nome: str | None = None
    cognome: str | None = None


def urllib_call(method: str, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    """`urllib`, no dependency: `packages/core` declares no HTTP client and
    `test_architecture.py` would refuse one. A 4xx is a status, not an exception, so the
    caller sees «the hub refused» and «the hub answered» through one path."""
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()


def lookup_member(settings: Settings, email: str, http: HttpCall | None = None) -> MemberLookup:
    """Asks the hub whether `email` belongs to a member. Never raises: any failure is
    `MemberLookup(membro=False)`, the same answer a non-member gets."""
    token = settings.registry_token
    base = settings.hub_url.strip().rstrip("/")
    address = email.strip().lower()
    if not token or not base or not address:
        return MemberLookup(membro=False)
    url = f"{base}{LOOKUP_PATH}?{urlencode({'email': address})}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    call = http or urllib_call
    try:
        status, body = call("GET", url, headers)
    except Exception:  # noqa: BLE001 - a refused connection, a DNS miss, a timeout
        return MemberLookup(membro=False)
    if not 200 <= status < 300:
        return MemberLookup(membro=False)
    try:
        return MemberLookup.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        return MemberLookup(membro=False)
