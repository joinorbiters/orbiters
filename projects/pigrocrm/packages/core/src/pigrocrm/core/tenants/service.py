"""Provisioning a space: a registry row, a database, its schema, its first admin, its
defaults.

Everything a space needs is what a fresh installation needs, done in-process: the same
Alembic migrations production runs at boot, the same `UserService.create` that
`createadmin` calls. The one thing that is new is the order, and what happens when a
step fails after the registry row exists -- the database is dropped and the row taken
back, so a name is never held by a space that does not work.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import pigrocrm.core
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings
from pigrocrm.core.db.session import session_factory
from pigrocrm.core.db.sidecar import create_database_if_missing, drop_database
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url
from pigrocrm.core.tenants.defaults import ensure_defaults
from pigrocrm.core.tenants.models import Tenant
from pigrocrm.core.tenants.schemas import (
    TenantAvailability,
    TenantRead,
    TenantSignup,
    validate_slug,
)


def default_alembic_ini() -> Path:
    """packages/core/alembic.ini, found from this package: `pigrocrm/core/__init__.py`
    sits four levels below it in the checkout and in the API image alike."""
    return Path(pigrocrm.core.__file__).resolve().parents[3] / "alembic.ini"


def migrate_to_head(settings: Settings, url: str) -> None:
    """`alembic upgrade head` against `url`, with the repository's own env.py. The
    configured URL wins over `get_settings()` there -- that is exactly the hook env.py
    documents for callers like this one."""
    ini = (
        Path(settings.tenants_alembic_ini)
        if settings.tenants_alembic_ini
        else default_alembic_ini()
    )
    if not ini.is_file():
        raise RuntimeError(f"alembic.ini not found at {ini}; set PIGROCRM_TENANTS_ALEMBIC_INI")
    config = Config(str(ini))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


class TenantService:
    """On a session of the registry database, never of a space."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def count_for_owner(self, email: str) -> int:
        """How many spaces that address has already opened: what only the registry knows,
        and what the signup uses to tell a returning person there is something to get
        back into, so a second space is opened on purpose and not by mistake (ORB-173).
        A count and not the slugs: the caller has not proven the address yet, and which
        spaces are whose is the mail's to tell. `owner_email` is stored lowercased by
        `provision`, so the match is on the lowercased input."""
        return (
            self.session.scalar(
                select(func.count())
                .select_from(Tenant)
                .where(Tenant.owner_email == email.strip().lower())
            )
            or 0
        )

    def list(self) -> list[TenantRead]:
        """Every space, newest first: what the registry knows, which is who opened it and
        when, never what is inside it (ORB-142)."""
        rows = self.session.scalars(
            select(Tenant).order_by(Tenant.created_at.desc(), Tenant.id.desc())
        ).all()
        return [TenantRead.model_validate(row) for row in rows]

    def get(self, slug: str) -> Tenant:
        tenant = self.session.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            raise NotFound("tenant", slug)
        return tenant

    def _reason(self, slug: str) -> str | None:
        """`validate_slug`, plus the one name only this installation knows is taken: the
        root's own (`PIGROCRM_ROOT_SLUG`)."""
        reason = validate_slug(slug)
        if reason is None and self.settings.root_slug and slug == self.settings.root_slug:
            return "questo nome è riservato"
        return reason

    def availability(self, slug: str) -> TenantAvailability:
        reason = self._reason(slug)
        if reason is not None:
            return TenantAvailability(slug=slug, disponibile=False, motivo=reason)
        taken = self.session.scalar(select(Tenant.id).where(Tenant.slug == slug)) is not None
        if taken:
            return TenantAvailability(
                slug=slug, disponibile=False, motivo="questo nome è già in uso"
            )
        return TenantAvailability(slug=slug, disponibile=True)

    def provision(self, data: TenantSignup) -> TenantRead:
        """The registry row first, so the unique index decides who gets the name; then
        the database, its schema, its admin. Any failure after the row undoes the row."""
        reason = self._reason(data.slug)
        if reason is not None:
            raise ValidationFailed("tenant", "slug", reason)
        db_name = tenant_database_name(data.slug)
        tenant = Tenant(slug=data.slug, db_name=db_name, owner_email=data.email.lower())
        self.session.add(tenant)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise Conflict("tenant", "questo nome è già in uso", slug=data.slug) from exc

        url = tenant_database_url(self.settings, db_name)
        try:
            create_database_if_missing(self.settings, url)
            migrate_to_head(self.settings, url.render_as_string(hide_password=False))
            engine = create_engine(url, future=True)
            try:
                with session_factory(engine)() as space:
                    UserService(space).create(
                        # No password: the admin enters with a link by mail, and the first
                        # link proves the address (spec 2026-09-12 §6.4).
                        UserCreate(email=data.email, password=None, nome=data.nome, ruolo="admin"),
                        Actor.system(),
                    )
                    # Born ready (spec 2026-09-12 §6.5): stages, templates and
                    # categories, then an emitter that carries the name and nothing
                    # fiscal. Inside the same try: a space that fails here is undone
                    # like one whose migration failed.
                    ensure_defaults(space)
                    # `nome` is capped at 200 by `TenantSignup`, under the emitter's 255;
                    # a name that is only spaces would make an empty header, so the
                    # address stands in for it.
                    EmitterProfileService(space).upsert(
                        EmitterProfileUpsert(ragione_sociale=data.nome.strip() or data.slug),
                        Actor.system(),
                    )
            finally:
                engine.dispose()
        except ValidationFailed:
            # A domain rule refused something about the admin: nothing about the space
            # is wrong, only the input, and the person will retry. Leave nothing behind.
            self._undo(tenant, url)
            raise
        except Exception:
            self._undo(tenant, url)
            raise
        return TenantRead.model_validate(tenant)

    def _undo(self, tenant: Tenant, url: URL) -> None:
        try:
            drop_database(self.settings, url)
        finally:
            self.session.delete(tenant)
            self.session.commit()
