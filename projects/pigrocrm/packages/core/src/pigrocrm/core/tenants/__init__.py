"""Spaces: one CRM per signup, one database per space.

The product stays single-tenant inside: nothing in the other packages knows what a
tenant is. This package owns the registry of spaces, the rules for their names and the
provisioning of a new database. Spec:
docs/superpowers/specs/2026-09-08-spazi-un-database-per-tenant-design.md.
"""

from pigrocrm.core.tenants.database import ensure_tenants_database, tenants_database_url
from pigrocrm.core.tenants.defaults import DefaultsReport, ensure_defaults
from pigrocrm.core.tenants.models import Tenant, TenantsBase
from pigrocrm.core.tenants.schemas import (
    RESERVED_SLUGS,
    SLUG_PATTERN,
    TenantAvailability,
    TenantRead,
    TenantSignup,
    slugify,
    validate_slug,
)
from pigrocrm.core.tenants.service import TenantService

__all__ = [
    "DefaultsReport",
    "RESERVED_SLUGS",
    "SLUG_PATTERN",
    "Tenant",
    "TenantAvailability",
    "TenantRead",
    "TenantService",
    "TenantSignup",
    "TenantsBase",
    "ensure_defaults",
    "ensure_tenants_database",
    "slugify",
    "tenants_database_url",
    "validate_slug",
]
