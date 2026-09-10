"""PigroCRM's spaces, as the hub's admin area shows them: which exist, and whose they are.

The hub imports nothing from PigroCRM and never opens its database (DECISIONS.md,
2026-09-09). What it does is ask the CRM's own API, `GET /api/tenants/`, with the token
the CRM reads as `PIGROCRM_REGISTRY_TOKEN`, through the same HTTP seam the mail and the
pixel use. The registry knows who opened a space and when, not what is inside it, and
that is all this module claims to know too.

The one thing the hub adds is the owner: when the address that opened a space is a
`freelancers` row, the space names that member and points at their card (ORB-142).
"""

import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbiters_core.config import Settings
from orbiters_core.http import HttpCall
from orbiters_core.models import Freelancer

REGISTRY_PATH = "/api/tenants/"


class PigroUnavailable(Exception):
    """The CRM did not answer with a list: a status other than 200, or a body that is not
    the registry. The message is the sentence the admin area shows."""


class RegistryRow(BaseModel):
    """One row as PigroCRM's `TenantRead` writes it. `id` is accepted and dropped: the
    hub has no use for the CRM's key."""

    model_config = ConfigDict(extra="ignore")

    slug: str
    owner_email: str
    created_at: datetime


class PigroMember(BaseModel):
    """The hub member who owns a space, enough to name them and link their card."""

    id: UUID
    nome: str
    cognome: str


class PigroSpace(BaseModel):
    slug: str
    owner_email: str
    created_at: datetime
    # Where the space answers, for the link on the row.
    url: str
    # `None` when nobody with that address filled in the hub's wizard.
    membro: PigroMember | None


class PigroSpaceList(BaseModel):
    totale: int
    items: list[PigroSpace]


_ROWS = TypeAdapter(list[RegistryRow])


class PigroRegistry:
    """Reads the registry over HTTP and matches each owner to a member. The session is
    the hub's own; the CRM is only ever reached through `http`."""

    def __init__(self, settings: Settings, http: HttpCall) -> None:
        self.settings = settings
        self.http = http

    def list_spaces(self, session: Session) -> PigroSpaceList:
        base = self.settings.pigro_api_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.pigro_registry_token}",
            "Accept": "application/json",
        }
        try:
            status, body = self.http("GET", base + REGISTRY_PATH, headers, b"")
        except Exception as exc:  # noqa: BLE001 - a refused connection, a DNS miss, a timeout
            raise PigroUnavailable("Pigro non risponde.") from exc
        if status != 200:
            raise PigroUnavailable(f"Pigro non ha risposto ({status}).")
        try:
            rows = _ROWS.validate_python(json.loads(body))
        except (ValueError, ValidationError) as exc:
            raise PigroUnavailable("Pigro ha risposto qualcosa che non è un elenco.") from exc
        members = self._members({row.owner_email.lower() for row in rows}, session)
        return PigroSpaceList(
            totale=len(rows),
            items=[
                PigroSpace(
                    slug=row.slug,
                    owner_email=row.owner_email,
                    created_at=row.created_at,
                    url=f"{base}/{row.slug}/app/",
                    membro=members.get(row.owner_email.lower()),
                )
                for row in rows
            ],
        )

    @staticmethod
    def _members(emails: set[str], session: Session) -> dict[str, PigroMember]:
        """The members behind those addresses, by lowercased address, in one query."""
        if not emails:
            return {}
        rows = session.scalars(
            select(Freelancer).where(func.lower(Freelancer.email).in_(emails))
        ).all()
        return {
            row.email.lower(): PigroMember(id=row.id, nome=row.nome, cognome=row.cognome)
            for row in rows
        }
