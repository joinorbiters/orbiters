"""Orbiters: the freelance community's signup list.

Deliberately a separate `DeclarativeBase` and a separate database. This is not CRM
data: nobody's customer, nobody's invoice, and not something a self-hosting titolare
should find in their own dump. See docs/superpowers/specs/2026-09-07-orbiters-landing-design.md.
"""

from pigrocrm.core.orbiters.database import ensure_orbiters_database, orbiters_database_url
from pigrocrm.core.orbiters.models import OrbitersBase, Signup
from pigrocrm.core.orbiters.schemas import (
    SignupCreate,
    SignupList,
    SignupListItem,
    SignupRead,
    SignupUtm,
)
from pigrocrm.core.orbiters.service import SignupService

__all__ = [
    "OrbitersBase",
    "Signup",
    "SignupCreate",
    "SignupList",
    "SignupListItem",
    "SignupRead",
    "SignupUtm",
    "SignupService",
    "ensure_orbiters_database",
    "orbiters_database_url",
]
