# PigroCRM Slice 1A — Backend (Core + API + MCP) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Core CRM (Customer, Person, Deal) with user-definable custom fields, exposed simultaneously through a REST API and an MCP server, on a shared service layer that neither adapter can bypass.

**Architecture:** A Python package `pigrocrm.core` holds all domain services. It receives and returns Pydantic models, owns its transactions, takes an explicit `Actor`, and never imports from `apps/`. Two thin adapters sit on top — FastAPI routers and MCP tools — both importing the same services in-process. A machine-enforced test guarantees the dependency direction.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · psycopg 3 · PostgreSQL 17 · MCP SDK v2 · pytest + testcontainers

**Spec:** `docs/superpowers/specs/2026-08-06-pigrocrm-core-crm-mcp-design.md`

**Scope:** Slice 1 is split into two plans because a single document at this granularity would be unmanageable for the engineer executing it. **This is plan 1A.** The web UI, E2E tests and deployment are in `2026-08-06-slice-1b-frontend.md`.

Plan 1A is complete and shippable on its own: at the end of it, Claude can run the whole CRM through MCP, and spec success criteria 1–4 are met (criterion 1 via the API rather than the UI). Plan 1B adds the human interface and criterion 5.

---

## Global Constraints

These apply to **every** task. They are not repeated per task.

- **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Managed by **uv workspaces**. Do not use pip, poetry, or venv directly.
- **`packages/core` must never import from `apps.`** — enforced by the test in Task 1. If a task seems to require it, the design is wrong; stop and flag it.
- **Services receive and return Pydantic models only.** No `Request`, `Response`, `HTTPException`, or status codes inside `packages/core`.
- **Every service method that writes takes `actor: Actor`** as an explicit parameter. Never read the actor from global or contextual state.
- **One service method = one transaction.** The service commits; repositories never commit.
- **Money is `Numeric(12, 2)`; hours are `Numeric(8, 2)`.** Never `Float` for either.
- **All timestamps are `TIMESTAMP WITH TIME ZONE` in UTC.** Use `datetime.now(timezone.utc)`, never `datetime.utcnow()`.
- **All primary keys are UUIDv7** via `uuid_utils.uuid7()`, stored as native `UUID`.
- **Soft delete**: `customers`, `people`, `deals` have `deleted_at`. Repository queries filter `deleted_at IS NULL` unless explicitly asked otherwise. No physical delete exists anywhere in this slice.
- **Tests use real PostgreSQL via testcontainers.** Never SQLite — JSONB and GIN indexes do not exist there.
- **TDD is mandatory for `packages/core`.** Write the failing test, watch it fail, then implement.
- **Commit after every task**, using the message given in the task's final step.
- **UI language is Italian.** Field labels, buttons, and error messages shown to users are Italian. Code identifiers, table names, and column names are English except the Italian fiscal terms already fixed in the spec (`partita_iva`, `codice_fiscale`, `codice_sdi`, `pec`, `ragione_sociale`, and the address parts `indirizzo`, `cap`, `comune`, `provincia`, `nazione`).
- **The `Expected: PASS (N passed)` counts are indicative, not contractual.** Parametrised tests expand to different totals than the number of test functions. What matters is that every test passes and none is skipped — a differing total is not a failure and must not be "fixed" by deleting or merging cases.
- **A uniqueness pre-check never replaces the database constraint.** Wherever a service does "SELECT to check, then INSERT", it must also catch `sqlalchemy.exc.IntegrityError` around the commit, `session.rollback()`, and re-raise the domain `Conflict`. Two concurrent requests both pass the SELECT; only the constraint stops the second, and without the rollback the caller's session is left poisoned (`PendingRollbackError` on its next statement). Established in Task 4 and applied identically in Task 7.
- **Case-insensitive uniqueness needs a functional index, not a convention.** A plain `unique=True` on a text column is case-sensitive: lowercasing in a Pydantic validator protects only the paths that go through it. Where identity is case-insensitive (emails, slugs), declare `Index("uq_…", func.lower(col), unique=True)` in `__table_args__`.

### Pinned versions

Backend (resolved and verified 2026-08-06): `fastapi 0.141.1` · `uvicorn 0.52.1` · `sqlalchemy 2.0.51` · `alembic 1.19.0` · `psycopg[binary] 3.3.4` · `pydantic 2.13.4` · `pydantic-settings 2.14.2` · `argon2-cffi 25.1.0` · `pyjwt 2.13.0` · `mcp 2.0.0` · `uuid-utils 0.17.0` · `pytest 9.1.1` · `testcontainers[postgres] 4.15.0` · `ruff 0.16.1` · `mypy 2.3.0`

Frontend versions and design tokens live in plan 1B. Do not install Node dependencies in this plan.

---

## File Structure

```
pigrocrm/
├── pyproject.toml                      # uv workspace root
├── packages/core/
│   ├── pyproject.toml
│   └── src/pigrocrm/core/
│       ├── errors.py                   # domain exceptions (structured, no strings)
│       ├── actor.py                    # Actor model
│       ├── config.py                   # pydantic-settings
│       ├── cli.py                      # `pigrocrm createadmin`
│       ├── db/{base,session,types}.py  # DeclarativeBase, engine, TimestampMixin
│       ├── auth/{models,schemas,repository,service,passwords,tokens}.py
│       ├── fields/{models,schemas,repository,service,validator,dynamic.py}
│       ├── activities/{models,schemas,repository,service}.py
│       ├── pipeline/{models,schemas,repository,service}.py
│       ├── customers/{models,schemas,repository,service}.py
│       ├── people/{models,schemas,repository,service}.py
│       └── deals/{models,schemas,repository,service}.py
│   ├── migrations/                     # Alembic
│   └── tests/
├── apps/api/
│   ├── pyproject.toml
│   └── src/pigrocrm_api/
│       ├── main.py · deps.py · errors.py
│       └── routers/{auth,customers,people,deals,fields,pipeline,users,tokens,schema}.py
│   └── tests/
├── apps/mcp/
│   ├── pyproject.toml
│   └── src/pigrocrm_mcp/
│       ├── server.py · context.py · errors.py
│       ├── tools/{schema,customers,people,deals,pipeline,timeline}.py
│       └── resources/entities.py
│   └── tests/
├── apps/web/
│   └── src/
│       ├── styles/tokens.css
│       ├── lib/{api.ts,query.ts,auth.tsx}
│       ├── components/ui/              # shadcn-generated
│       ├── components/{EntityDetailLayout,DynamicFieldRenderer,DataTable}.tsx
│       ├── features/{customers,people,deals,settings}/
│       └── routes/                     # TanStack Router file-based
├── docker-compose.yml · Dockerfile.api · Dockerfile.web
└── .github/workflows/ci-deploy.yml
```

**Why these boundaries:** each domain folder is four small files (`models` SQLAlchemy, `schemas` Pydantic, `repository` queries, `service` business rules). If a `service.py` exceeds ~300 lines, split the domain. `fields/` holds the two highest-leverage modules in the codebase: `validator.py` (single validation authority) and `dynamic.py` (runtime model factory feeding both adapters).

---

# Phase 1 — Foundations

### Task 1: Monorepo scaffolding and the architecture guard

**Files:**
- Create: `pyproject.toml`, `packages/core/pyproject.toml`, `packages/core/src/pigrocrm/core/__init__.py`
- Create: `apps/api/pyproject.toml`, `apps/api/src/pigrocrm_api/__init__.py`
- Create: `apps/mcp/pyproject.toml`, `apps/mcp/src/pigrocrm_mcp/__init__.py`
- Create: `ruff.toml`, `.python-version`
- Test: `packages/core/tests/test_architecture.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: uv workspace with three members; `pigrocrm.core`, `pigrocrm_api`, `pigrocrm_mcp` importable; `pytest` and `ruff` runnable from the repo root

- [ ] **Step 1: Create the workspace root**

`pyproject.toml`:

```toml
[project]
name = "pigrocrm"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = ["pigrocrm-core", "pigrocrm-api", "pigrocrm-mcp"]

[tool.uv.workspace]
members = ["packages/*", "apps/api", "apps/mcp"]

[tool.uv.sources]
pigrocrm-core = { workspace = true }
pigrocrm-api = { workspace = true }
pigrocrm-mcp = { workspace = true }

[dependency-groups]
dev = [
  "pytest==9.1.1", "pytest-cov==7.1.0", "pytest-asyncio==1.4.0",
  "testcontainers[postgres]==4.15.0", "httpx==0.28.1",
  "ruff==0.16.1", "mypy==2.3.0",
]

[tool.pytest.ini_options]
testpaths = ["packages/core/tests", "apps/api/tests", "apps/mcp/tests"]
asyncio_mode = "auto"

[tool.mypy]
python_version = "3.13"
strict = true
```

`.python-version`:

```
3.13
```

`ruff.toml`:

```toml
line-length = 100
target-version = "py313"

[lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TID"]

[lint.flake8-tidy-imports.banned-api]
"apps".msg = "packages/core must not import from apps/"
```

- [ ] **Step 2: Create the three member packages**

`packages/core/pyproject.toml`:

```toml
[project]
name = "pigrocrm-core"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
  "sqlalchemy==2.0.51", "alembic==1.19.0", "psycopg[binary]==3.3.4",
  "pydantic==2.13.4", "pydantic-settings==2.14.2",
  "argon2-cffi==25.1.0", "pyjwt==2.13.0", "uuid-utils==0.17.0",
]

[project.scripts]
pigrocrm = "pigrocrm.core.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pigrocrm"]
```

`apps/api/pyproject.toml`:

```toml
[project]
name = "pigrocrm-api"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
  "pigrocrm-core", "fastapi==0.141.1", "uvicorn[standard]==0.52.1",
  "python-multipart==0.0.20",
]

[tool.uv.sources]
pigrocrm-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pigrocrm_api"]
```

`apps/mcp/pyproject.toml`:

```toml
[project]
name = "pigrocrm-mcp"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = ["pigrocrm-core", "mcp==2.0.0"]

[tool.uv.sources]
pigrocrm-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pigrocrm_mcp"]
```

Create empty `__init__.py` in `packages/core/src/pigrocrm/core/`, `apps/api/src/pigrocrm_api/`, `apps/mcp/src/pigrocrm_mcp/`.

Note: `packages/core/src/pigrocrm/` gets **no** `__init__.py` — it is a namespace package. Only `pigrocrm/core/` gets one.

- [ ] **Step 3: Write the failing architecture test**

`packages/core/tests/test_architecture.py`:

```python
"""The one rule that cannot be recovered later: core must not depend on adapters."""

import ast
from pathlib import Path

CORE_SRC = Path(__file__).resolve().parents[1] / "src" / "pigrocrm" / "core"
FORBIDDEN_ROOTS = {"pigrocrm_api", "pigrocrm_mcp", "fastapi", "mcp", "starlette"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_never_imports_from_adapters() -> None:
    offenders: list[str] = []
    for path in CORE_SRC.rglob("*.py"):
        bad = _imported_roots(path) & FORBIDDEN_ROOTS
        if bad:
            offenders.append(f"{path.relative_to(CORE_SRC)} imports {sorted(bad)}")
    assert not offenders, (
        "packages/core must not import adapters or web frameworks:\n  "
        + "\n  ".join(offenders)
    )


def test_core_source_directory_exists() -> None:
    assert CORE_SRC.is_dir(), f"expected core sources at {CORE_SRC}"
```

- [ ] **Step 4: Install and run the test**

Run: `uv sync && uv run pytest packages/core/tests/test_architecture.py -v`
Expected: **PASS** (2 passed). The guard is green from the start — its job is to fail later, if someone breaks the rule.

To confirm the guard actually works, temporarily add `import fastapi` to `packages/core/src/pigrocrm/core/__init__.py`, re-run, and verify it **FAILS** with the offender listed. Then remove that line and re-run to confirm PASS.

- [ ] **Step 5: Verify lint and types run clean**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: uv workspace scaffolding with the core/adapters architecture guard"
```

---

### Task 2: Database foundation and the test container fixture

**Files:**
- Create: `packages/core/src/pigrocrm/core/config.py`
- Create: `packages/core/src/pigrocrm/core/db/__init__.py`, `db/base.py`, `db/session.py`
- Create: `packages/core/tests/conftest.py`
- Test: `packages/core/tests/test_db.py`

**Interfaces:**
- Consumes: Task 1 workspace
- Produces:
  - `Settings` (pydantic-settings) with `database_url: str`, `jwt_secret: str`, `access_token_minutes: int = 15`, `refresh_token_days: int = 30`; `get_settings() -> Settings` (cached)
  - `Base` — `DeclarativeBase` subclass
  - `PrimaryKeyMixin` — `id: Mapped[UUID]` default `uuid7()`
  - `TimestampMixin` — `created_at`/`updated_at: Mapped[datetime]`, timezone-aware
  - `SoftDeleteMixin` — `deleted_at: Mapped[datetime | None]`
  - `create_engine_from_settings(settings) -> Engine`, `session_factory(engine) -> sessionmaker[Session]`
  - pytest fixtures `db_engine` (session-scoped container) and `db_session` (function-scoped, rolled back)

- [ ] **Step 1: Write `config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIGROCRM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pigrocrm:pigrocrm@localhost:5432/pigrocrm"
    jwt_secret: str = "change-me-in-production"
    access_token_minutes: int = 15
    refresh_token_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Write `db/base.py`**

```python
from datetime import UTC, datetime
from uuid import UUID

import uuid_utils
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid7() -> UUID:
    """UUIDv7: random enough to be unguessable, ordered enough to index well."""
    return UUID(str(uuid_utils.uuid7()))


class Base(DeclarativeBase):
    pass


class PrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

- [ ] **Step 3: Write `db/session.py`**

```python
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from pigrocrm.core.config import Settings


def create_engine_from_settings(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

`db/__init__.py`:

```python
from pigrocrm.core.db.base import (
    Base,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid7,
)
from pigrocrm.core.db.session import create_engine_from_settings, session_factory, session_scope

__all__ = [
    "Base",
    "PrimaryKeyMixin",
    "SoftDeleteMixin",
    "TimestampMixin",
    "create_engine_from_settings",
    "session_factory",
    "session_scope",
    "uuid7",
]
```

- [ ] **Step 4: Write `conftest.py` with the real-Postgres fixture**

```python
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm.core.config import Settings


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Real PostgreSQL. JSONB and GIN do not exist in SQLite, so there is no shortcut."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        settings = Settings(database_url=container.get_connection_url())
        engine = create_engine_from_settings(settings)
        import pigrocrm.core.models_registry  # noqa: F401  (imports every model)

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Each test runs in a transaction that is rolled back, so tests never see each other."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = session_factory(db_engine)(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
```

Create `packages/core/src/pigrocrm/core/models_registry.py` with only a docstring for now:

```python
"""Imports every SQLAlchemy model so that `Base.metadata` is complete.

Each task that adds a model appends its import here.
"""
```

- [ ] **Step 5: Write the failing test**

`packages/core/tests/test_db.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.db import uuid7


def test_uuid7_is_a_uuid_and_is_time_ordered() -> None:
    first, second = uuid7(), uuid7()
    assert isinstance(first, UUID)
    assert first != second
    assert first.hex < second.hex, "UUIDv7 must be monotonically ordered"


def test_database_is_postgres_and_supports_jsonb(db_session: Session) -> None:
    version = db_session.execute(text("SELECT version()")).scalar_one()
    assert "PostgreSQL" in version

    result = db_session.execute(
        text("""SELECT '{"a": 1}'::jsonb @> '{"a": 1}'::jsonb""")
    ).scalar_one()
    assert result is True


def test_timestamps_are_timezone_aware(db_session: Session) -> None:
    now = db_session.execute(text("SELECT now()")).scalar_one()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.astimezone(UTC).tzinfo is UTC
```

- [ ] **Step 6: Run the test**

Run: `uv run pytest packages/core/tests/test_db.py -v`
Expected: PASS (3 passed). First run pulls `postgres:17-alpine` and takes ~30s; later runs reuse the session-scoped container.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: database foundation with UUIDv7, tz-aware timestamps and a real-Postgres test fixture"
```

---

### Task 3: Domain errors and the Actor

**Files:**
- Create: `packages/core/src/pigrocrm/core/errors.py`
- Create: `packages/core/src/pigrocrm/core/actor.py`
- Test: `packages/core/tests/test_errors.py`

**Interfaces:**
- Consumes: Task 1
- Produces:
  - `DomainError(Exception)` with `.code: str` and `.details: dict[str, Any]`
  - `NotFound(entity: str, identifier: str | UUID)`
  - `ValidationFailed(entity: str, field: str, reason: str, *, expected: str | None = None)`
  - `Conflict(entity: str, reason: str, **details: Any)`
  - `PermissionDenied(action: str, required_roles: list[str], actual_role: str)`
  - `ImmutableField(entity: str, field: str, reason: str)`
  - `Actor(BaseModel)` with `id: UUID | None`, `type: ActorType`, `role: Role`; `ActorType = Literal["user", "mcp", "system"]`; `Role = Literal["admin", "collaboratore", "readonly"]`
  - `Actor.system()` classmethod, `Actor.can_write` / `Actor.can_administer` properties

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_errors.py`:

```python
import pytest

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import (
    Conflict,
    DomainError,
    ImmutableField,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)


def test_errors_carry_structured_details_not_formatted_strings() -> None:
    """The same exception becomes an HTTP problem detail AND an LLM-readable message.
    That is only possible if the data stays structured."""
    err = ValidationFailed("customer", "partita_iva", "must be 11 digits", expected="11 digits")

    assert isinstance(err, DomainError)
    assert err.code == "validation_failed"
    assert err.details == {
        "entity": "customer",
        "field": "partita_iva",
        "reason": "must be 11 digits",
        "expected": "11 digits",
    }


def test_not_found_records_which_entity_and_which_id() -> None:
    err = NotFound("deal", "0199-abc")
    assert err.code == "not_found"
    assert err.details["entity"] == "deal"
    assert err.details["identifier"] == "0199-abc"


def test_conflict_accepts_arbitrary_context() -> None:
    err = Conflict("customer", "has active deals", active_deals=3)
    assert err.code == "conflict"
    assert err.details["active_deals"] == 3


def test_permission_denied_states_what_role_would_be_enough() -> None:
    err = PermissionDenied("update_deal", ["admin", "collaboratore"], "readonly")
    assert err.details["required_roles"] == ["admin", "collaboratore"]
    assert err.details["actual_role"] == "readonly"


def test_immutable_field_is_its_own_error() -> None:
    err = ImmutableField("field_definition", "field_type", "would orphan existing values")
    assert err.code == "immutable_field"


@pytest.mark.parametrize(
    ("role", "can_write", "can_administer"),
    [("admin", True, True), ("collaboratore", True, False), ("readonly", False, False)],
)
def test_actor_permissions_by_role(role: str, can_write: bool, can_administer: bool) -> None:
    actor = Actor(id=None, type="user", role=role)  # type: ignore[arg-type]
    assert actor.can_write is can_write
    assert actor.can_administer is can_administer


def test_system_actor_is_an_admin_with_no_user_id() -> None:
    actor = Actor.system()
    assert actor.type == "system"
    assert actor.id is None
    assert actor.can_administer is True
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.errors'`

- [ ] **Step 3: Write `errors.py`**

```python
from typing import Any
from uuid import UUID


class DomainError(Exception):
    """Base for every business-rule failure.

    Carries structured `details`, never a pre-formatted sentence: the API renders
    them as RFC 9457 problem details, the MCP adapter renders them as guidance an
    LLM can act on. Those are two different renderings of the same fact.
    """

    code: str = "domain_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details


class NotFound(DomainError):
    code = "not_found"

    def __init__(self, entity: str, identifier: str | UUID) -> None:
        super().__init__(
            f"{entity} {identifier} not found", entity=entity, identifier=str(identifier)
        )


class ValidationFailed(DomainError):
    code = "validation_failed"

    def __init__(
        self, entity: str, field: str, reason: str, *, expected: str | None = None
    ) -> None:
        super().__init__(
            f"{entity}.{field}: {reason}",
            entity=entity,
            field=field,
            reason=reason,
            expected=expected,
        )


class Conflict(DomainError):
    code = "conflict"

    def __init__(self, entity: str, reason: str, **details: Any) -> None:
        super().__init__(f"{entity}: {reason}", entity=entity, reason=reason, **details)


class PermissionDenied(DomainError):
    code = "permission_denied"

    def __init__(self, action: str, required_roles: list[str], actual_role: str) -> None:
        super().__init__(
            f"{action} requires one of {required_roles}, actor has {actual_role}",
            action=action,
            required_roles=required_roles,
            actual_role=actual_role,
        )


class ImmutableField(DomainError):
    code = "immutable_field"

    def __init__(self, entity: str, field: str, reason: str) -> None:
        super().__init__(
            f"{entity}.{field} cannot be changed: {reason}",
            entity=entity,
            field=field,
            reason=reason,
        )
```

- [ ] **Step 4: Write `actor.py`**

```python
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel

from pigrocrm.core.errors import PermissionDenied

ActorType = Literal["user", "mcp", "system"]
Role = Literal["admin", "collaboratore", "readonly"]

WRITE_ROLES: list[str] = ["admin", "collaboratore"]
ADMIN_ROLES: list[str] = ["admin"]


class Actor(BaseModel):
    """Who is performing an operation. Always passed explicitly — never inferred
    from global state — so that authorization is testable and the timeline is honest
    about whether a human or an agent made the change."""

    id: UUID | None
    type: ActorType
    role: Role

    @classmethod
    def system(cls) -> Self:
        return cls(id=None, type="system", role="admin")

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    @property
    def can_administer(self) -> bool:
        return self.role in ADMIN_ROLES

    def require_write(self, action: str) -> None:
        if not self.can_write:
            raise PermissionDenied(action, WRITE_ROLES, self.role)

    def require_admin(self, action: str) -> None:
        if not self.can_administer:
            raise PermissionDenied(action, ADMIN_ROLES, self.role)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/core/tests/test_errors.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: structured domain errors and explicit Actor with role checks"
```

---

# Phase 2 — Identity

### Task 4: Users, password hashing and the `createadmin` CLI

**Files:**
- Create: `packages/core/src/pigrocrm/core/auth/__init__.py`, `auth/models.py`, `auth/schemas.py`, `auth/passwords.py`, `auth/repository.py`, `auth/service.py`
- Create: `packages/core/src/pigrocrm/core/cli.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Test: `packages/core/tests/test_auth_users.py`

**Interfaces:**
- Consumes: `Base`, `PrimaryKeyMixin`, `TimestampMixin` (Task 2); `Actor`, `NotFound`, `Conflict`, `ValidationFailed`, `PermissionDenied` (Task 3)
- Produces:
  - `User` model — table `users`, columns `email` (unique, citext-lowered), `password_hash`, `nome`, `ruolo`, `attivo`
  - `hash_password(plain: str) -> str`, `verify_password(plain: str, hashed: str) -> bool`
  - `UserCreate(email, password, nome, ruolo)`, `UserUpdate(nome=None, ruolo=None, attivo=None)`, `UserRead(id, email, nome, ruolo, attivo, created_at)`
  - `UserRepository(session)` with `get(id)`, `get_by_email(email)`, `list_all()`, `add(user)`
  - `UserService(session)` with `create(data, actor) -> UserRead`, `update(id, data, actor) -> UserRead`, `list(actor) -> list[UserRead]`, `authenticate(email, password) -> UserRead`, `count() -> int`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_auth_users.py`:

```python
import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.passwords import hash_password, verify_password
from pigrocrm.core.auth.schemas import UserCreate, UserUpdate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.errors import Conflict, PermissionDenied, ValidationFailed

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")


def test_password_hash_is_argon2_and_never_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2")
    assert "correct horse" not in hashed
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_the_same_password_hashes_differently_each_time() -> None:
    assert hash_password("same") != hash_password("same"), "argon2 must salt per hash"


def test_create_user_stores_a_hash_and_normalises_the_email(db_session: Session) -> None:
    service = UserService(db_session)
    user = service.create(
        UserCreate(email="  Mario@Example.IT ", password="supersegreta1", nome="Ivan", ruolo="admin"),
        ADMIN,
    )
    assert user.email == "mario@example.it"
    assert user.ruolo == "admin"
    assert user.attivo is True
    assert not hasattr(user, "password_hash"), "UserRead must never expose the hash"


def test_duplicate_email_is_a_conflict(db_session: Session) -> None:
    service = UserService(db_session)
    service.create(UserCreate(email="a@b.it", password="supersegreta1", nome="A", ruolo="admin"), ADMIN)
    with pytest.raises(Conflict) as exc:
        service.create(
            UserCreate(email="A@B.it", password="supersegreta1", nome="A2", ruolo="admin"), ADMIN
        )
    assert exc.value.details["entity"] == "user"


def test_short_password_is_rejected(db_session: Session) -> None:
    service = UserService(db_session)
    with pytest.raises(ValidationFailed) as exc:
        service.create(UserCreate(email="c@d.it", password="corta", nome="C", ruolo="admin"), ADMIN)
    assert exc.value.details["field"] == "password"


def test_only_admins_manage_users(db_session: Session) -> None:
    service = UserService(db_session)
    with pytest.raises(PermissionDenied) as exc:
        service.create(UserCreate(email="e@f.it", password="supersegreta1", nome="E", ruolo="readonly"), COLLAB)
    assert exc.value.details["required_roles"] == ["admin"]


def test_authenticate_accepts_correct_credentials(db_session: Session) -> None:
    service = UserService(db_session)
    service.create(UserCreate(email="g@h.it", password="supersegreta1", nome="G", ruolo="admin"), ADMIN)
    assert service.authenticate("G@H.it", "supersegreta1").email == "g@h.it"


@pytest.mark.parametrize("email,password", [("g@h.it", "sbagliata"), ("nope@h.it", "supersegreta1")])
def test_authenticate_rejects_bad_credentials_without_saying_which(
    db_session: Session, email: str, password: str
) -> None:
    """Distinguishing 'unknown user' from 'wrong password' leaks which emails exist."""
    service = UserService(db_session)
    service.create(UserCreate(email="g@h.it", password="supersegreta1", nome="G", ruolo="admin"), ADMIN)
    with pytest.raises(ValidationFailed) as exc:
        service.authenticate(email, password)
    assert exc.value.details["reason"] == "credenziali non valide"


def test_deactivated_user_cannot_authenticate(db_session: Session) -> None:
    service = UserService(db_session)
    user = service.create(
        UserCreate(email="i@j.it", password="supersegreta1", nome="I", ruolo="admin"), ADMIN
    )
    service.update(user.id, UserUpdate(attivo=False), ADMIN)
    with pytest.raises(ValidationFailed):
        service.authenticate("i@j.it", "supersegreta1")
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_auth_users.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.auth'`

- [ ] **Step 3: Write `auth/passwords.py`**

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError):
        return False
```

- [ ] **Step 4: Write `auth/models.py`**

```python
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class User(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    ruolo: Mapped[str] = mapped_column(String(20), nullable=False, default="collaboratore")
    attivo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

- [ ] **Step 5: Write `auth/schemas.py`**

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from pigrocrm.core.actor import Role

MIN_PASSWORD_LENGTH = 10


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    nome: str
    ruolo: Role = "collaboratore"

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    nome: str | None = None
    ruolo: Role | None = None
    attivo: bool | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    nome: str
    ruolo: Role
    attivo: bool
    created_at: datetime
```

- [ ] **Step 6: Write `auth/repository.py`**

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> list[User]:
        return list(self.session.execute(select(User).order_by(User.nome)).scalars())

    def count(self) -> int:
        return len(self.list_all())

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user
```

- [ ] **Step 7: Write `auth/service.py`**

```python
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.passwords import hash_password, verify_password
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import MIN_PASSWORD_LENGTH, UserCreate, UserRead, UserUpdate
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed

INVALID_CREDENTIALS = "credenziali non valide"


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = UserRepository(session)

    def create(self, data: UserCreate, actor: Actor) -> UserRead:
        actor.require_admin("create_user")
        if len(data.password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(
                "user",
                "password",
                f"deve avere almeno {MIN_PASSWORD_LENGTH} caratteri",
                expected=f">= {MIN_PASSWORD_LENGTH} caratteri",
            )
        if self.repo.get_by_email(data.email):
            raise Conflict("user", "esiste già un utente con questa email", email=data.email)

        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            nome=data.nome,
            ruolo=data.ruolo,
            attivo=True,
        )
        self.repo.add(user)
        self.session.commit()
        return UserRead.model_validate(user)

    def update(self, user_id: UUID, data: UserUpdate, actor: Actor) -> UserRead:
        actor.require_admin("update_user")
        user = self.repo.get(user_id)
        if user is None:
            raise NotFound("user", user_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(user, field, value)
        self.session.commit()
        return UserRead.model_validate(user)

    def list(self, actor: Actor) -> list[UserRead]:
        actor.require_admin("list_users")
        return [UserRead.model_validate(u) for u in self.repo.list_all()]

    def count(self) -> int:
        return self.repo.count()

    def authenticate(self, email: str, password: str) -> UserRead:
        user = self.repo.get_by_email(email)
        # Hash even when the user is missing, so timing does not reveal which emails exist.
        reference = user.password_hash if user else hash_password("dummy-for-constant-time")
        ok = verify_password(password, reference)
        if user is None or not ok or not user.attivo:
            raise ValidationFailed("user", "credentials", INVALID_CREDENTIALS)
        return UserRead.model_validate(user)
```

`auth/__init__.py`:

```python
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.schemas import UserCreate, UserRead, UserUpdate
from pigrocrm.core.auth.service import UserService

__all__ = ["User", "UserCreate", "UserRead", "UserService", "UserUpdate"]
```

- [ ] **Step 8: Register the model**

Append to `packages/core/src/pigrocrm/core/models_registry.py`:

```python
from pigrocrm.core.auth.models import User  # noqa: F401
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest packages/core/tests/test_auth_users.py -v`
Expected: PASS (10 passed)

- [ ] **Step 10: Write the `createadmin` CLI**

`packages/core/src/pigrocrm/core/cli.py`:

```python
import argparse
import getpass
import sys

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory


def createadmin(email: str | None, nome: str | None) -> int:
    """Bootstrap the first administrator. There is no default account and no known
    default password — the direct lesson from the previous system's hardcoded credentials."""
    email = email or input("Email: ").strip()
    nome = nome or input("Nome: ").strip()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Conferma password: "):
        print("Le password non coincidono.", file=sys.stderr)
        return 1

    engine = create_engine_from_settings(get_settings())
    with session_factory(engine)() as session:
        service = UserService(session)
        user = service.create(
            UserCreate(email=email, password=password, nome=nome, ruolo="admin"),
            Actor.system(),
        )
    print(f"Creato amministratore {user.email}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="pigrocrm")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("createadmin", help="Crea il primo utente amministratore")
    admin.add_argument("--email")
    admin.add_argument("--nome")

    args = parser.parse_args()
    if args.command == "createadmin":
        return createadmin(args.email, args.nome)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 11: Verify the CLI is registered**

Run: `uv run pigrocrm --help`
Expected: usage text listing the `createadmin` subcommand.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "feat: users with argon2 hashing, admin-only management and createadmin CLI"
```

---

### Task 5: JWT sessions and personal access tokens

**Files:**
- Create: `packages/core/src/pigrocrm/core/auth/tokens.py`, `auth/pat_models.py`, `auth/pat_service.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`, `auth/__init__.py`
- Test: `packages/core/tests/test_auth_tokens.py`

**Interfaces:**
- Consumes: `User`, `UserService` (Task 4); `Settings` (Task 2); errors and `Actor` (Task 3)
- Produces:
  - `issue_access_token(user_id, role, settings) -> str`, `issue_refresh_token(user_id, settings) -> str`
  - `decode_token(token, settings, *, expected_type) -> TokenPayload`; `TokenPayload(sub: UUID, role: str | None, type: str, exp: datetime)`
  - `PersonalAccessToken` model — table `personal_access_tokens`, columns `user_id`, `nome`, `token_hash`, `prefix`, `last_used_at`, `revoked_at`
  - `PatService(session)` with `create(nome, actor) -> tuple[PatRead, str]`, `list(actor) -> list[PatRead]`, `revoke(pat_id, actor) -> None`, `resolve(raw_token) -> Actor`
  - `PatRead(id, nome, prefix, last_used_at, revoked_at, created_at)`
  - Constant `PAT_PREFIX = "pgc_"`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_auth_tokens.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.pat_service import PAT_PREFIX, PatService
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.auth.tokens import decode_token, issue_access_token, issue_refresh_token
from pigrocrm.core.config import Settings
from pigrocrm.core.errors import NotFound, PermissionDenied, ValidationFailed

SETTINGS = Settings(jwt_secret="test-secret-not-for-production")
ADMIN = Actor(id=None, type="system", role="admin")


def _make_user(db_session: Session, email: str = "tok@test.it"):
    return UserService(db_session).create(
        UserCreate(email=email, password="supersegreta1", nome="Tok", ruolo="admin"), ADMIN
    )


def test_access_token_round_trips_user_and_role(db_session: Session) -> None:
    user = _make_user(db_session)
    payload = decode_token(
        issue_access_token(user.id, "admin", SETTINGS), SETTINGS, expected_type="access"
    )
    assert payload.sub == user.id
    assert payload.role == "admin"
    assert payload.type == "access"


def test_refresh_token_cannot_be_used_as_an_access_token(db_session: Session) -> None:
    user = _make_user(db_session)
    refresh = issue_refresh_token(user.id, SETTINGS)
    with pytest.raises(ValidationFailed) as exc:
        decode_token(refresh, SETTINGS, expected_type="access")
    assert exc.value.details["field"] == "token"


def test_expired_token_is_rejected(db_session: Session) -> None:
    user = _make_user(db_session)
    expired = Settings(jwt_secret=SETTINGS.jwt_secret, access_token_minutes=-1)
    token = issue_access_token(user.id, "admin", expired)
    with pytest.raises(ValidationFailed):
        decode_token(token, SETTINGS, expected_type="access")


def test_token_signed_with_another_secret_is_rejected(db_session: Session) -> None:
    user = _make_user(db_session)
    token = issue_access_token(user.id, "admin", Settings(jwt_secret="a-different-secret"))
    with pytest.raises(ValidationFailed):
        decode_token(token, SETTINGS, expected_type="access")


def test_access_token_expiry_matches_settings(db_session: Session) -> None:
    user = _make_user(db_session)
    payload = decode_token(
        issue_access_token(user.id, "admin", SETTINGS), SETTINGS, expected_type="access"
    )
    expected = datetime.now(UTC) + timedelta(minutes=SETTINGS.access_token_minutes)
    assert abs((payload.exp - expected).total_seconds()) < 5


def test_pat_is_returned_once_and_stored_only_as_a_hash(db_session: Session) -> None:
    user = _make_user(db_session, "pat@test.it")
    actor = Actor(id=user.id, type="user", role="admin")
    service = PatService(db_session)

    record, raw = service.create("Claude locale", actor)

    assert raw.startswith(PAT_PREFIX)
    assert len(raw) > 40
    assert record.prefix == raw[: len(PAT_PREFIX) + 8]
    assert not hasattr(record, "token_hash"), "PatRead must never expose the hash"

    stored = service.list(actor)[0]
    assert stored.prefix == record.prefix
    assert raw not in str(stored.model_dump())


def test_pat_resolves_to_an_actor_and_records_last_use(db_session: Session) -> None:
    user = _make_user(db_session, "pat2@test.it")
    actor = Actor(id=user.id, type="user", role="admin")
    service = PatService(db_session)
    _, raw = service.create("Claude locale", actor)

    resolved = service.resolve(raw)
    assert resolved.id == user.id
    assert resolved.type == "mcp", "a PAT identifies an agent, not a browser session"
    assert resolved.role == "admin"
    assert service.list(actor)[0].last_used_at is not None


def test_revoked_pat_stops_working(db_session: Session) -> None:
    user = _make_user(db_session, "pat3@test.it")
    actor = Actor(id=user.id, type="user", role="admin")
    service = PatService(db_session)
    record, raw = service.create("Da revocare", actor)

    service.revoke(record.id, actor)

    with pytest.raises(ValidationFailed):
        service.resolve(raw)


def test_unknown_pat_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValidationFailed):
        PatService(db_session).resolve("pgc_totally-made-up-token-value-here")


def test_a_user_cannot_revoke_another_users_pat(db_session: Session) -> None:
    owner = _make_user(db_session, "owner@test.it")
    other = _make_user(db_session, "other@test.it")
    service = PatService(db_session)
    record, _ = service.create("Mio", Actor(id=owner.id, type="user", role="admin"))

    with pytest.raises(NotFound):
        service.revoke(record.id, Actor(id=other.id, type="user", role="admin"))


def test_pat_for_deactivated_user_stops_working(db_session: Session) -> None:
    from pigrocrm.core.auth.schemas import UserUpdate

    user = _make_user(db_session, "pat4@test.it")
    actor = Actor(id=user.id, type="user", role="admin")
    _, raw = PatService(db_session).create("Token", actor)
    UserService(db_session).update(user.id, UserUpdate(attivo=False), ADMIN)

    with pytest.raises(ValidationFailed):
        PatService(db_session).resolve(raw)
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_auth_tokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.auth.tokens'`

- [ ] **Step 3: Write `auth/tokens.py`**

```python
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from pydantic import BaseModel

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]


class TokenPayload(BaseModel):
    sub: UUID
    role: str | None
    type: TokenType
    exp: datetime


def _issue(
    user_id: UUID, role: str | None, token_type: TokenType, delta: timedelta, settings: Settings
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def issue_access_token(user_id: UUID, role: str, settings: Settings) -> str:
    return _issue(user_id, role, "access", timedelta(minutes=settings.access_token_minutes), settings)


def issue_refresh_token(user_id: UUID, settings: Settings) -> str:
    return _issue(user_id, None, "refresh", timedelta(days=settings.refresh_token_days), settings)


def decode_token(token: str, settings: Settings, *, expected_type: TokenType) -> TokenPayload:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise ValidationFailed("session", "token", "token non valido o scaduto") from exc

    if claims.get("type") != expected_type:
        raise ValidationFailed(
            "session", "token", "tipo di token errato", expected=expected_type
        )
    return TokenPayload(
        sub=UUID(claims["sub"]),
        role=claims.get("role"),
        type=claims["type"],
        exp=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )
```

- [ ] **Step 4: Write `auth/pat_models.py`**

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class PersonalAccessToken(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "personal_access_tokens"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

- [ ] **Step 5: Write `auth/pat_service.py`**

```python
import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor, Role
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.pat_models import PersonalAccessToken
from pigrocrm.core.errors import NotFound, ValidationFailed

PAT_PREFIX = "pgc_"
PREFIX_VISIBLE_CHARS = 8


class PatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


def _digest(raw: str) -> str:
    """SHA-256, not argon2: lookup is by hash, so it must be deterministic. Safe here
    because the token is 32 random bytes, not a human-chosen password."""
    return hashlib.sha256(raw.encode()).hexdigest()


class PatService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, nome: str, actor: Actor) -> tuple[PatRead, str]:
        if actor.id is None:
            raise ValidationFailed("token", "actor", "serve un utente autenticato")

        raw = PAT_PREFIX + secrets.token_urlsafe(32)
        record = PersonalAccessToken(
            user_id=actor.id,
            nome=nome,
            token_hash=_digest(raw),
            prefix=raw[: len(PAT_PREFIX) + PREFIX_VISIBLE_CHARS],
        )
        self.session.add(record)
        self.session.commit()
        # The raw value is returned exactly once and never stored.
        return PatRead.model_validate(record), raw

    def list(self, actor: Actor) -> list[PatRead]:
        stmt = (
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == actor.id)
            .order_by(PersonalAccessToken.created_at.desc())
        )
        return [PatRead.model_validate(r) for r in self.session.execute(stmt).scalars()]

    def revoke(self, pat_id: UUID, actor: Actor) -> None:
        stmt = select(PersonalAccessToken).where(
            PersonalAccessToken.id == pat_id, PersonalAccessToken.user_id == actor.id
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            raise NotFound("personal_access_token", pat_id)
        record.revoked_at = datetime.now(UTC)
        self.session.commit()

    def resolve(self, raw_token: str) -> Actor:
        stmt = select(PersonalAccessToken).where(
            PersonalAccessToken.token_hash == _digest(raw_token)
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            raise ValidationFailed("token", "token", "token non valido o revocato")

        user = self.session.get(User, record.user_id)
        if user is None or not user.attivo:
            raise ValidationFailed("token", "token", "utente non attivo")

        record.last_used_at = datetime.now(UTC)
        self.session.commit()
        role: Role = user.ruolo  # type: ignore[assignment]
        # type="mcp": a PAT identifies an agent, which is what makes the timeline honest.
        return Actor(id=user.id, type="mcp", role=role)
```

- [ ] **Step 6: Register the model and re-export**

Append to `models_registry.py`:

```python
from pigrocrm.core.auth.pat_models import PersonalAccessToken  # noqa: F401
```

Append to `auth/__init__.py`:

```python
from pigrocrm.core.auth.pat_models import PersonalAccessToken
from pigrocrm.core.auth.pat_service import PAT_PREFIX, PatRead, PatService
from pigrocrm.core.auth.tokens import (
    TokenPayload,
    decode_token,
    issue_access_token,
    issue_refresh_token,
)
```

and extend `__all__` with `"PAT_PREFIX"`, `"PatRead"`, `"PatService"`, `"PersonalAccessToken"`, `"TokenPayload"`, `"decode_token"`, `"issue_access_token"`, `"issue_refresh_token"`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest packages/core/tests/test_auth_tokens.py -v`
Expected: PASS (11 passed)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: JWT access/refresh tokens and hashed personal access tokens"
```

---

# Phase 3 — Dynamic fields

This phase contains the two highest-leverage modules in the codebase. `validator.py` is the single
authority on whether a custom value is acceptable — routers, MCP tools and the frontend all defer to
it. `dynamic.py` turns field definitions into Pydantic models at runtime, which is what makes custom
fields visible to both OpenAPI and MCP from one source.

### Task 6: The custom-field validator

**Files:**
- Create: `packages/core/src/pigrocrm/core/fields/__init__.py`, `fields/types.py`, `fields/validator.py`
- Test: `packages/core/tests/test_fields_validator.py`

**Interfaces:**
- Consumes: `ValidationFailed` (Task 3)
- Produces:
  - `FieldType = Literal["text","textarea","number","currency","date","select","multiselect","checkbox","url"]`
  - `FieldSpec(BaseModel)` — `key: str`, `label: str`, `field_type: FieldType`, `options: list[str] = []`, `required: bool = False`
  - `validate_custom_fields(entity: str, specs: list[FieldSpec], values: dict[str, Any]) -> dict[str, Any]` — returns coerced values, raises `ValidationFailed`
  - `coerce_value(entity: str, spec: FieldSpec, value: Any) -> Any`

No database access here — the validator is pure, which is why it can be tested exhaustively and fast.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_fields_validator.py`:

```python
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fields.types import FieldSpec
from pigrocrm.core.fields.validator import validate_custom_fields


def spec(key: str, field_type: str, **kw: Any) -> FieldSpec:
    return FieldSpec(key=key, label=key.title(), field_type=field_type, **kw)  # type: ignore[arg-type]


def test_empty_specs_and_empty_values_produce_empty_result() -> None:
    assert validate_custom_fields("customer", [], {}) == {}


def test_unknown_key_is_rejected_rather_than_silently_stored() -> None:
    """Silently accepting unknown keys turns JSONB into a junk drawer and hides typos
    from agents that guessed a field name."""
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("customer", [spec("settore", "text")], {"setore": "IT"})
    assert exc.value.details["field"] == "setore"
    assert "settore" in exc.value.details["reason"]


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("customer", [spec("settore", "text", required=True)], {})
    assert exc.value.details["field"] == "settore"


def test_required_field_rejects_empty_string() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields("customer", [spec("settore", "text", required=True)], {"settore": "   "})


def test_optional_field_accepts_none_and_is_dropped() -> None:
    assert validate_custom_fields("customer", [spec("settore", "text")], {"settore": None}) == {}


def test_text_is_trimmed() -> None:
    result = validate_custom_fields("customer", [spec("settore", "text")], {"settore": "  IT  "})
    assert result == {"settore": "IT"}


def test_number_accepts_int_float_and_numeric_string() -> None:
    specs = [spec("n", "number")]
    assert validate_custom_fields("c", specs, {"n": 5})["n"] == 5.0
    assert validate_custom_fields("c", specs, {"n": 5.5})["n"] == 5.5
    assert validate_custom_fields("c", specs, {"n": "5.5"})["n"] == 5.5


def test_number_rejects_non_numeric() -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [spec("n", "number")], {"n": "molto"})
    assert exc.value.details["expected"] == "un numero"


def test_currency_is_stored_as_a_two_decimal_string_not_a_float() -> None:
    """JSON has no decimal type. Storing money as float rounds wrong on invoices,
    so currency is serialised as a fixed-scale string."""
    result = validate_custom_fields("c", [spec("budget", "currency")], {"budget": "1234.567"})
    assert result == {"budget": "1234.57"}
    assert Decimal(result["budget"]) == Decimal("1234.57")


def test_currency_rejects_non_numeric() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [spec("budget", "currency")], {"budget": "gratis"})


def test_date_accepts_iso_string_and_date_and_normalises_to_iso() -> None:
    specs = [spec("scadenza", "date")]
    assert validate_custom_fields("c", specs, {"scadenza": "2026-08-06"})["scadenza"] == "2026-08-06"
    assert validate_custom_fields("c", specs, {"scadenza": date(2026, 8, 6)})["scadenza"] == "2026-08-06"


@pytest.mark.parametrize("bad", ["06/08/2026", "2026-13-01", "domani"])
def test_date_rejects_non_iso(bad: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [spec("scadenza", "date")], {"scadenza": bad})
    assert exc.value.details["expected"] == "una data ISO (YYYY-MM-DD)"


def test_select_accepts_a_declared_option() -> None:
    s = spec("stato", "select", options=["attivo", "sospeso"])
    assert validate_custom_fields("c", [s], {"stato": "attivo"})["stato"] == "attivo"


def test_select_rejects_an_undeclared_option_and_lists_the_valid_ones() -> None:
    """The error must name the allowed values: an agent that gets 'invalid' retries
    at random, one that gets the list corrects itself."""
    s = spec("stato", "select", options=["attivo", "sospeso"])
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [s], {"stato": "chiuso"})
    assert "attivo" in exc.value.details["expected"]
    assert "sospeso" in exc.value.details["expected"]


def test_multiselect_accepts_a_list_and_deduplicates_preserving_order() -> None:
    s = spec("tag", "multiselect", options=["a", "b", "c"])
    assert validate_custom_fields("c", [s], {"tag": ["b", "a", "b"]})["tag"] == ["b", "a"]


def test_multiselect_rejects_a_bare_string() -> None:
    s = spec("tag", "multiselect", options=["a"])
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [s], {"tag": "a"})
    assert exc.value.details["expected"] == "una lista di valori"


def test_multiselect_rejects_an_undeclared_member() -> None:
    s = spec("tag", "multiselect", options=["a", "b"])
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [s], {"tag": ["a", "z"]})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(True, True), (False, False), ("true", True), ("false", False), (1, True), (0, False)],
)
def test_checkbox_coerces_common_truthy_representations(raw: Any, expected: bool) -> None:
    assert validate_custom_fields("c", [spec("ok", "checkbox")], {"ok": raw})["ok"] is expected


def test_checkbox_rejects_ambiguous_values() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [spec("ok", "checkbox")], {"ok": "forse"})


@pytest.mark.parametrize("url", ["https://example.com", "http://localhost:5173/x?y=1"])
def test_url_accepts_http_and_https(url: str) -> None:
    assert validate_custom_fields("c", [spec("sito", "url")], {"sito": url})["sito"] == url


@pytest.mark.parametrize("bad", ["example.com", "javascript:alert(1)", "ftp://x.it"])
def test_url_rejects_anything_that_is_not_http_or_https(bad: str) -> None:
    """javascript: in particular would become a stored-XSS vector the moment the UI
    renders a custom field as a link."""
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [spec("sito", "url")], {"sito": bad})
    assert exc.value.details["expected"] == "un URL http:// o https://"


def test_archived_specs_are_simply_not_passed_in_so_their_values_are_rejected() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [], {"vecchio": "valore"})


def test_all_errors_name_the_entity() -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("deal", [spec("n", "number")], {"n": "x"})
    assert exc.value.details["entity"] == "deal"
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_fields_validator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.fields'`

- [ ] **Step 3: Write `fields/types.py`**

```python
from typing import Literal

from pydantic import BaseModel

FieldType = Literal[
    "text",
    "textarea",
    "number",
    "currency",
    "date",
    "select",
    "multiselect",
    "checkbox",
    "url",
]

FIELD_TYPES: tuple[FieldType, ...] = (
    "text",
    "textarea",
    "number",
    "currency",
    "date",
    "select",
    "multiselect",
    "checkbox",
    "url",
)

OPTION_TYPES: frozenset[str] = frozenset({"select", "multiselect"})


class FieldSpec(BaseModel):
    """A field definition, detached from the database row, so the validator stays pure."""

    key: str
    label: str
    field_type: FieldType
    options: list[str] = []
    required: bool = False
```

- [ ] **Step 4: Write `fields/validator.py`**

```python
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn
from urllib.parse import urlparse

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fields.types import FieldSpec

TRUE_VALUES = {True, 1, "1", "true", "True", "si", "sì", "yes"}
FALSE_VALUES = {False, 0, "0", "false", "False", "no"}
ALLOWED_URL_SCHEMES = {"http", "https"}


def _fail(entity: str, key: str, reason: str, expected: str | None = None) -> NoReturn:
    """`NoReturn` is load-bearing: it tells mypy every call ends the function, so no
    caller needs an unreachable `raise` after it just to satisfy the return type."""
    raise ValidationFailed(entity, key, reason, expected=expected)


def _coerce_number(entity: str, spec: FieldSpec, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        _fail(entity, spec.key, f"'{value}' non è un numero", "un numero")


def _coerce_currency(entity: str, spec: FieldSpec, value: Any) -> str:
    """Money is stored as a fixed-scale string: JSON has no decimal type, and float
    rounding on money is a bug that only shows up on an invoice."""
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError, ValueError):
        _fail(entity, spec.key, f"'{value}' non è un importo", "un importo numerico")


def _coerce_date(entity: str, spec: FieldSpec, value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        _fail(entity, spec.key, f"'{value}' non è una data valida", "una data ISO (YYYY-MM-DD)")


def _coerce_select(entity: str, spec: FieldSpec, value: Any) -> str:
    text = str(value).strip()
    if text not in spec.options:
        _fail(
            entity,
            spec.key,
            f"'{text}' non è tra le opzioni ammesse",
            f"uno tra: {', '.join(spec.options)}",
        )
    return text


def _coerce_multiselect(entity: str, spec: FieldSpec, value: Any) -> list[str]:
    if not isinstance(value, list):
        _fail(entity, spec.key, "il valore deve essere una lista", "una lista di valori")
    seen: list[str] = []
    for item in value:
        text = str(item).strip()
        if text not in spec.options:
            _fail(
                entity,
                spec.key,
                f"'{text}' non è tra le opzioni ammesse",
                f"valori tra: {', '.join(spec.options)}",
            )
        if text not in seen:
            seen.append(text)
    return seen


def _coerce_checkbox(entity: str, spec: FieldSpec, value: Any) -> bool:
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    _fail(entity, spec.key, f"'{value}' non è un booleano", "true oppure false")


def _coerce_url(entity: str, spec: FieldSpec, value: Any) -> str:
    text = str(value).strip()
    parsed = urlparse(text)
    # Rejecting javascript: here is what stops a stored-XSS the moment the UI
    # renders a custom field as a link.
    if parsed.scheme not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        _fail(entity, spec.key, f"'{text}' non è un URL valido", "un URL http:// o https://")
    return text


def coerce_value(entity: str, spec: FieldSpec, value: Any) -> Any:
    match spec.field_type:
        case "text" | "textarea":
            return str(value).strip()
        case "number":
            return _coerce_number(entity, spec, value)
        case "currency":
            return _coerce_currency(entity, spec, value)
        case "date":
            return _coerce_date(entity, spec, value)
        case "select":
            return _coerce_select(entity, spec, value)
        case "multiselect":
            return _coerce_multiselect(entity, spec, value)
        case "checkbox":
            return _coerce_checkbox(entity, spec, value)
        case "url":
            return _coerce_url(entity, spec, value)
    _fail(entity, spec.key, f"tipo di campo sconosciuto: {spec.field_type}")


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_custom_fields(
    entity: str, specs: list[FieldSpec], values: dict[str, Any]
) -> dict[str, Any]:
    """The single authority on custom-field validity.

    Routers, MCP tools and the UI all defer to this. Duplicating any part of it
    elsewhere is how the three interfaces start disagreeing about what is valid.
    """
    by_key = {spec.key: spec for spec in specs}

    for key in values:
        if key not in by_key:
            known = ", ".join(sorted(by_key)) or "nessuno"
            _fail(entity, key, f"campo non definito (campi disponibili: {known})")

    result: dict[str, Any] = {}
    for spec in specs:
        raw = values.get(spec.key)
        if _is_blank(raw):
            if spec.required:
                _fail(entity, spec.key, "campo obbligatorio", "un valore non vuoto")
            continue
        result[spec.key] = coerce_value(entity, spec, raw)
    return result
```

`fields/__init__.py`:

```python
from pigrocrm.core.fields.types import FIELD_TYPES, FieldSpec, FieldType
from pigrocrm.core.fields.validator import coerce_value, validate_custom_fields

__all__ = [
    "FIELD_TYPES",
    "FieldSpec",
    "FieldType",
    "coerce_value",
    "validate_custom_fields",
]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/core/tests/test_fields_validator.py -v`
Expected: PASS (34 passed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: pure custom-field validator with per-type coercion and actionable errors"
```

---

### Task 7: Field definitions — model, service and immutability rules

**Files:**
- Create: `packages/core/src/pigrocrm/core/fields/models.py`, `fields/schemas.py`, `fields/repository.py`, `fields/service.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`, `fields/__init__.py`
- Test: `packages/core/tests/test_fields_service.py`

**Interfaces:**
- Consumes: `FieldSpec`, `FieldType` (Task 6); `Actor`, errors (Task 3)
- Produces:
  - `FieldDefinition` model — table `field_definitions`, columns `entity_type`, `key`, `label`, `field_type`, `options` (JSONB), `required`, `position`, `archived`; unique constraint on `(entity_type, key)`
  - `EntityType = Literal["customer","person","deal"]` (open by design — later slices add `document`, `invoice`)
  - `FieldDefinitionCreate(entity_type, key, label, field_type, options=[], required=False, position=0)`
  - `FieldDefinitionUpdate(label=None, options=None, required=None, position=None)` — **no `field_type`**
  - `FieldDefinitionRead(id, entity_type, key, label, field_type, options, required, position, archived)`
  - `FieldDefinitionService(session)` with `create(data, actor)`, `update(id, data, actor)`, `archive(id, actor)`, `list(entity_type, *, include_archived=False)`, `specs_for(entity_type) -> list[FieldSpec]`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_fields_service.py`:

```python
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, PermissionDenied, ValidationFailed
from pigrocrm.core.fields.schemas import FieldDefinitionCreate, FieldDefinitionUpdate
from pigrocrm.core.fields.service import FieldDefinitionService

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")


def _create(service: FieldDefinitionService, key: str = "settore", **kw):
    payload = {"entity_type": "customer", "key": key, "label": key.title(), "field_type": "text"}
    payload.update(kw)
    return service.create(FieldDefinitionCreate(**payload), ADMIN)


def test_create_returns_the_definition(db_session: Session) -> None:
    field = _create(FieldDefinitionService(db_session))
    assert field.key == "settore"
    assert field.archived is False


def test_key_is_slugified(db_session: Session) -> None:
    field = _create(FieldDefinitionService(db_session), key="  Settore Merceologico  ")
    assert field.key == "settore_merceologico"


def test_duplicate_key_on_the_same_entity_is_a_conflict(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    _create(service)
    with pytest.raises(Conflict):
        _create(service)


def test_the_same_key_on_a_different_entity_is_allowed(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    _create(service)
    other = service.create(
        FieldDefinitionCreate(entity_type="deal", key="settore", label="Settore", field_type="text"),
        ADMIN,
    )
    assert other.entity_type == "deal"


def test_select_without_options_is_rejected(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    with pytest.raises(ValidationFailed) as exc:
        _create(service, key="stato", field_type="select", options=[])
    assert exc.value.details["field"] == "options"


def test_non_select_with_options_is_rejected(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    with pytest.raises(ValidationFailed):
        _create(service, key="nome", field_type="text", options=["a"])


def test_field_type_cannot_be_changed(db_session: Session) -> None:
    """There is no correct answer for text -> number with existing values, so the
    operation does not exist. Archive the old field and create a new one."""
    service = FieldDefinitionService(db_session)
    field = _create(service)

    assert "field_type" not in FieldDefinitionUpdate.model_fields
    # extra="forbid" turns the attempt into a pydantic ValidationError, so the
    # request never reaches the service at all.
    with pytest.raises(ValidationError):
        FieldDefinitionUpdate(field_type="number")  # type: ignore[call-arg]

    updated = service.update(field.id, FieldDefinitionUpdate(label="Nuovo"), ADMIN)
    assert updated.field_type == "text"


def test_archive_hides_the_field_but_keeps_it_readable(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    field = _create(service)
    service.archive(field.id, ADMIN)

    assert service.list("customer") == []
    archived = service.list("customer", include_archived=True)
    assert len(archived) == 1
    assert archived[0].archived is True


def test_archived_fields_are_excluded_from_specs(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    keep = _create(service, key="tenuto")
    drop = _create(service, key="archiviato")
    service.archive(drop.id, ADMIN)

    keys = [spec.key for spec in service.specs_for("customer")]
    assert keys == [keep.key]


def test_list_is_ordered_by_position_then_label(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    _create(service, key="terzo", position=2)
    _create(service, key="primo", position=0)
    _create(service, key="secondo", position=1)
    assert [f.key for f in service.list("customer")] == ["primo", "secondo", "terzo"]


def test_only_admins_change_the_schema(db_session: Session) -> None:
    service = FieldDefinitionService(db_session)
    with pytest.raises(PermissionDenied) as exc:
        service.create(
            FieldDefinitionCreate(
                entity_type="customer", key="x", label="X", field_type="text"
            ),
            COLLAB,
        )
    assert exc.value.details["required_roles"] == ["admin"]


def test_specs_for_returns_field_specs_usable_by_the_validator(db_session: Session) -> None:
    from pigrocrm.core.fields.validator import validate_custom_fields

    service = FieldDefinitionService(db_session)
    _create(service, key="stato", field_type="select", options=["attivo", "sospeso"])

    specs = service.specs_for("customer")
    assert validate_custom_fields("customer", specs, {"stato": "attivo"}) == {"stato": "attivo"}
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_fields_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.fields.schemas'`

- [ ] **Step 3: Write `fields/models.py`**

```python
from typing import Any

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class FieldDefinition(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "field_definitions"
    __table_args__ = (UniqueConstraint("entity_type", "key", name="uq_field_entity_key"),)

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)
    options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
```

- [ ] **Step 4: Write `fields/schemas.py`**

```python
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from pigrocrm.core.fields.types import FieldType

# Open by design: later slices append "document" and "invoice" with no schema change.
EntityType = Literal["customer", "person", "deal"]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify_key(raw: str) -> str:
    return _SLUG_STRIP.sub("_", raw.strip().lower()).strip("_")


class FieldDefinitionCreate(BaseModel):
    entity_type: EntityType
    key: str
    label: str
    field_type: FieldType
    options: list[str] = []
    required: bool = False
    position: int = 0

    @field_validator("key", mode="before")
    @classmethod
    def _slugify(cls, value: str) -> str:
        return slugify_key(value)


class FieldDefinitionUpdate(BaseModel):
    """`field_type` is deliberately absent. Changing it with existing values has no
    correct answer, so the operation does not exist at any layer."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    options: list[str] | None = None
    required: bool | None = None
    position: int | None = None


class FieldDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: EntityType
    key: str
    label: str
    field_type: FieldType
    options: list[str]
    required: bool
    position: int
    archived: bool
```

Note: `extra="forbid"` is what turns `FieldDefinitionUpdate(field_type="number")` into the `TypeError`
the test expects, rather than a silently ignored argument.

- [ ] **Step 5: Write `fields/repository.py`**

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.fields.models import FieldDefinition


class FieldDefinitionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, field_id: UUID) -> FieldDefinition | None:
        return self.session.get(FieldDefinition, field_id)

    def get_by_key(self, entity_type: str, key: str) -> FieldDefinition | None:
        stmt = select(FieldDefinition).where(
            FieldDefinition.entity_type == entity_type, FieldDefinition.key == key
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, entity_type: str, *, include_archived: bool = False) -> list[FieldDefinition]:
        stmt = select(FieldDefinition).where(FieldDefinition.entity_type == entity_type)
        if not include_archived:
            stmt = stmt.where(FieldDefinition.archived.is_(False))
        stmt = stmt.order_by(FieldDefinition.position, FieldDefinition.label)
        return list(self.session.execute(stmt).scalars())

    def add(self, field: FieldDefinition) -> FieldDefinition:
        self.session.add(field)
        self.session.flush()
        return field
```

- [ ] **Step 6: Write `fields/service.py`**

```python
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.fields.models import FieldDefinition
from pigrocrm.core.fields.repository import FieldDefinitionRepository
from pigrocrm.core.fields.schemas import (
    EntityType,
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
)
from pigrocrm.core.fields.types import OPTION_TYPES, FieldSpec


def _check_options(field_type: str, options: list[str]) -> None:
    if field_type in OPTION_TYPES and not options:
        raise ValidationFailed(
            "field_definition",
            "options",
            f"un campo di tipo {field_type} richiede almeno un'opzione",
            expected="una lista non vuota",
        )
    if field_type not in OPTION_TYPES and options:
        raise ValidationFailed(
            "field_definition",
            "options",
            f"un campo di tipo {field_type} non ammette opzioni",
            expected="una lista vuota",
        )


class FieldDefinitionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = FieldDefinitionRepository(session)

    def create(self, data: FieldDefinitionCreate, actor: Actor) -> FieldDefinitionRead:
        actor.require_admin("create_field_definition")
        if not data.key:
            raise ValidationFailed("field_definition", "key", "chiave vuota dopo la normalizzazione")
        _check_options(data.field_type, data.options)

        if self.repo.get_by_key(data.entity_type, data.key):
            raise Conflict(
                "field_definition",
                "esiste già un campo con questa chiave",
                entity_type=data.entity_type,
                key=data.key,
            )

        field = FieldDefinition(**data.model_dump())
        try:
            self.repo.add(field)
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a race between two concurrent requests:
            # there the database constraint is the only authority. The rollback is
            # mandatory — without it the session is unusable for the caller.
            self.session.rollback()
            raise Conflict(
                "field_definition",
                "esiste già un campo con questa chiave",
                entity_type=data.entity_type,
                key=data.key,
            ) from exc
        return FieldDefinitionRead.model_validate(field)

    def update(
        self, field_id: UUID, data: FieldDefinitionUpdate, actor: Actor
    ) -> FieldDefinitionRead:
        actor.require_admin("update_field_definition")
        field = self.repo.get(field_id)
        if field is None:
            raise NotFound("field_definition", field_id)

        changes = data.model_dump(exclude_none=True)
        if "options" in changes:
            _check_options(field.field_type, changes["options"])
        for key, value in changes.items():
            setattr(field, key, value)
        self.session.commit()
        return FieldDefinitionRead.model_validate(field)

    def archive(self, field_id: UUID, actor: Actor) -> FieldDefinitionRead:
        """Archive rather than delete: deleting a definition while rows still hold the
        value in JSONB produces orphan data nobody can see."""
        actor.require_admin("archive_field_definition")
        field = self.repo.get(field_id)
        if field is None:
            raise NotFound("field_definition", field_id)
        field.archived = True
        self.session.commit()
        return FieldDefinitionRead.model_validate(field)

    def list(
        self, entity_type: EntityType, *, include_archived: bool = False
    ) -> list[FieldDefinitionRead]:
        return [
            FieldDefinitionRead.model_validate(f)
            for f in self.repo.list(entity_type, include_archived=include_archived)
        ]

    def specs_for(self, entity_type: EntityType) -> list[FieldSpec]:
        """The bridge to the validator and to the runtime model factory."""
        return [
            FieldSpec(
                key=f.key,
                label=f.label,
                field_type=f.field_type,  # type: ignore[arg-type]
                options=list(f.options),
                required=f.required,
            )
            for f in self.repo.list(entity_type)
        ]
```

- [ ] **Step 7: Register the model and re-export**

Append to `models_registry.py`:

```python
from pigrocrm.core.fields.models import FieldDefinition  # noqa: F401
```

Append to `fields/__init__.py`:

```python
from pigrocrm.core.fields.models import FieldDefinition
from pigrocrm.core.fields.schemas import (
    EntityType,
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
)
from pigrocrm.core.fields.service import FieldDefinitionService
```

and extend `__all__` accordingly.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest packages/core/tests/test_fields_service.py -v`
Expected: PASS (12 passed)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: field definitions with slugified keys, archiving and immutable field_type"
```

---

### Task 8: The runtime model factory

This is the module that makes custom fields visible to OpenAPI and to MCP from a single source.
The MCP SDK infers a tool's JSON Schema from its function signature — `add_tool()` takes no explicit
schema — so the bridge is `pydantic.create_model()`.

**Files:**
- Create: `packages/core/src/pigrocrm/core/fields/dynamic.py`
- Modify: `packages/core/src/pigrocrm/core/fields/__init__.py`
- Test: `packages/core/tests/test_fields_dynamic.py`

**Interfaces:**
- Consumes: `FieldSpec`, `FieldType` (Task 6)
- Produces:
  - `python_type_for(spec: FieldSpec) -> Any` — the annotation for one field
  - `build_custom_fields_model(entity: str, specs: list[FieldSpec]) -> type[BaseModel]`
  - `describe_specs(specs: list[FieldSpec]) -> list[dict[str, Any]]` — plain data for `describe_schema`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_fields_dynamic.py`:

```python
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from pigrocrm.core.fields.dynamic import build_custom_fields_model, describe_specs
from pigrocrm.core.fields.types import FieldSpec


def spec(key: str, field_type: str, **kw: Any) -> FieldSpec:
    return FieldSpec(key=key, label=key.title(), field_type=field_type, **kw)  # type: ignore[arg-type]


def test_no_specs_produces_an_empty_but_valid_model() -> None:
    model = build_custom_fields_model("customer", [])
    assert issubclass(model, BaseModel)
    assert model().model_dump() == {}


def test_the_model_name_mentions_the_entity() -> None:
    model = build_custom_fields_model("customer", [spec("settore", "text")])
    assert "Customer" in model.__name__


def test_optional_fields_default_to_none() -> None:
    model = build_custom_fields_model("customer", [spec("settore", "text")])
    assert model().settore is None  # type: ignore[attr-defined]


def test_required_fields_are_required() -> None:
    model = build_custom_fields_model("customer", [spec("settore", "text", required=True)])
    with pytest.raises(ValidationError):
        model()


def test_json_schema_exposes_every_key_with_its_label_as_description() -> None:
    """This is what an agent reads to discover a field nobody hardcoded."""
    specs = [spec("settore", "text"), spec("budget", "currency")]
    schema = build_custom_fields_model("customer", specs).model_json_schema()

    assert set(schema["properties"]) == {"settore", "budget"}
    assert schema["properties"]["settore"]["description"] == "Settore"


def test_select_becomes_an_enum_in_the_json_schema() -> None:
    """An enum is what lets the model pick a valid option instead of guessing."""
    s = spec("stato", "select", options=["attivo", "sospeso"])
    schema = build_custom_fields_model("customer", [s]).model_json_schema()
    rendered = str(schema)
    assert "attivo" in rendered and "sospeso" in rendered


def test_multiselect_becomes_an_array() -> None:
    s = spec("tag", "multiselect", options=["a", "b"])
    schema = build_custom_fields_model("customer", [s]).model_json_schema()
    prop = schema["properties"]["tag"]
    assert "array" in str(prop)


@pytest.mark.parametrize(
    ("field_type", "value"),
    [
        ("text", "IT"),
        ("textarea", "riga\nriga"),
        ("number", 5.5),
        ("currency", "1234.56"),
        ("date", "2026-08-06"),
        ("checkbox", True),
        ("url", "https://example.com"),
    ],
)
def test_each_type_round_trips_a_valid_value(field_type: str, value: Any) -> None:
    model = build_custom_fields_model("customer", [spec("campo", field_type)])
    assert model(campo=value).model_dump()["campo"] == value


def test_checkbox_rejects_a_non_boolean() -> None:
    model = build_custom_fields_model("customer", [spec("ok", "checkbox")])
    with pytest.raises(ValidationError):
        model(ok="forse")


def test_describe_specs_returns_plain_serialisable_data() -> None:
    import json

    specs = [spec("stato", "select", options=["attivo"], required=True)]
    described = describe_specs(specs)

    assert described == [
        {
            "key": "stato",
            "label": "Stato",
            "type": "select",
            "required": True,
            "options": ["attivo"],
        }
    ]
    json.dumps(described)  # must not raise


def test_two_entities_produce_independent_models() -> None:
    a = build_custom_fields_model("customer", [spec("uno", "text")])
    b = build_custom_fields_model("deal", [spec("due", "text")])
    assert set(a.model_fields) == {"uno"}
    assert set(b.model_fields) == {"due"}
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_fields_dynamic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.fields.dynamic'`

- [ ] **Step 3: Write `fields/dynamic.py`**

```python
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, create_model

from pigrocrm.core.fields.types import FieldSpec

# currency and date stay strings on the wire: JSON has no decimal and no date type,
# and the validator has already normalised them to a canonical string form.
_SIMPLE_TYPES: dict[str, Any] = {
    "text": str,
    "textarea": str,
    "number": float,
    "currency": str,
    "date": str,
    "checkbox": bool,
    "url": str,
}


def python_type_for(spec: FieldSpec) -> Any:
    if spec.field_type == "select":
        return Literal[tuple(spec.options)] if spec.options else str
    if spec.field_type == "multiselect":
        inner = Literal[tuple(spec.options)] if spec.options else str
        return list[inner]  # type: ignore[valid-type]
    return _SIMPLE_TYPES[spec.field_type]


def build_custom_fields_model(entity: str, specs: list[FieldSpec]) -> type[BaseModel]:
    """Turn field definitions into a real Pydantic model at runtime.

    This is the bridge that makes user-defined fields visible to both adapters:
    FastAPI derives OpenAPI from it, and the MCP SDK derives a tool's JSON Schema
    from the function signature it annotates. One source, two descriptions.
    """
    definitions: dict[str, Any] = {}
    for spec in specs:
        annotation = python_type_for(spec)
        if spec.required:
            definitions[spec.key] = (
                Annotated[annotation, Field(description=spec.label)],
                ...,
            )
        else:
            definitions[spec.key] = (
                Annotated[annotation | None, Field(description=spec.label)],
                None,
            )

    model_name = f"{entity.capitalize()}CustomFields"
    return create_model(model_name, **definitions)  # type: ignore[call-overload, no-any-return]


def describe_specs(specs: list[FieldSpec]) -> list[dict[str, Any]]:
    """Plain JSON-serialisable description, for the `describe_schema` MCP tool and
    for the frontend's dynamic renderer."""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "type": spec.field_type,
            "required": spec.required,
            "options": list(spec.options),
        }
        for spec in specs
    ]
```

- [ ] **Step 4: Re-export**

Append to `fields/__init__.py`:

```python
from pigrocrm.core.fields.dynamic import build_custom_fields_model, describe_specs, python_type_for
```

and extend `__all__` with `"build_custom_fields_model"`, `"describe_specs"`, `"python_type_for"`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/core/tests/test_fields_dynamic.py -v`
Expected: PASS (20 passed)

- [ ] **Step 6: Run the whole suite and the guard**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy packages/core/src`
Expected: all green, including `test_core_never_imports_from_adapters`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: runtime Pydantic model factory so custom fields reach OpenAPI and MCP alike"
```

---

# Phase 4 — Domain entities

### Task 9: Activities (the unified timeline) and pipeline stages

Two small domains in one task: they are both pure infrastructure for the entities that follow, and
neither is independently reviewable in a useful way.

**Files:**
- Create: `packages/core/src/pigrocrm/core/activities/{__init__,models,schemas,repository,service}.py`
- Create: `packages/core/src/pigrocrm/core/pipeline/{__init__,models,schemas,repository,service}.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Test: `packages/core/tests/test_activities.py`, `packages/core/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Actor` (Task 3), db mixins (Task 2)
- Produces:
  - `Activity` model — table `activities`, columns `entity_type`, `entity_id`, `kind`, `actor_id`, `actor_type`, `payload` (JSONB), `occurred_at`
  - `ActivityRead(id, entity_type, entity_id, kind, actor_id, actor_type, payload, occurred_at)`
  - `ActivityService(session)` with `record(entity_type, entity_id, kind, actor, payload=None) -> Activity` (**flushes, never commits** — it joins the caller's transaction) and `timeline(entity_type, entity_id, limit=50) -> list[ActivityRead]`
  - `PipelineStage` model — table `pipeline_stages`, columns `nome`, `posizione`, `probabilita_default`, `tipo`
  - `StageKind = Literal["open","won","lost"]`
  - `PipelineStageCreate(nome, posizione, probabilita_default=0, tipo="open")`, `PipelineStageUpdate(nome=None, posizione=None, probabilita_default=None, tipo=None)`, `PipelineStageRead(id, nome, posizione, probabilita_default, tipo)`
  - `PipelineService(session)` with `create/update/list/get/delete` and `seed_defaults() -> list[PipelineStageRead]`
  - `DEFAULT_STAGES` — the seed data

- [ ] **Step 1: Write the failing tests**

`packages/core/tests/test_activities.py`:

```python
from uuid import uuid4

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.activities.service import ActivityService

USER = Actor(id=uuid4(), type="user", role="admin")
AGENT = Actor(id=uuid4(), type="mcp", role="admin")


def test_record_stores_who_did_what(db_session: Session) -> None:
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("customer", entity_id, "created", USER, {"ragione_sociale": "ACME"})
    db_session.commit()

    entries = service.timeline("customer", entity_id)
    assert len(entries) == 1
    assert entries[0].kind == "created"
    assert entries[0].payload == {"ragione_sociale": "ACME"}
    assert entries[0].actor_id == USER.id


def test_actor_type_distinguishes_a_human_from_an_agent(db_session: Session) -> None:
    """In an AI-first CRM this is the first thing you want to know when something
    looks wrong: did I do that, or did Claude?"""
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("deal", entity_id, "created", USER)
    service.record("deal", entity_id, "stage_changed", AGENT)
    db_session.commit()

    assert {e.actor_type for e in service.timeline("deal", entity_id)} == {"user", "mcp"}


def test_timeline_is_newest_first_and_limited(db_session: Session) -> None:
    service = ActivityService(db_session)
    entity_id = uuid4()
    for index in range(5):
        service.record("customer", entity_id, f"kind_{index}", USER)
    db_session.commit()

    entries = service.timeline("customer", entity_id, limit=3)
    assert len(entries) == 3
    assert entries[0].kind == "kind_4"


def test_timeline_is_scoped_to_one_entity(db_session: Session) -> None:
    service = ActivityService(db_session)
    mine, theirs = uuid4(), uuid4()
    service.record("customer", mine, "created", USER)
    service.record("customer", theirs, "created", USER)
    db_session.commit()

    assert len(service.timeline("customer", mine)) == 1


def test_record_does_not_commit_so_it_joins_the_callers_transaction(db_session: Session) -> None:
    """If recording committed on its own, a service that later fails would leave a
    timeline entry for a change that never happened."""
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("customer", entity_id, "created", USER)
    db_session.rollback()

    assert service.timeline("customer", entity_id) == []
```

`packages/core/tests/test_pipeline.py`:

```python
import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import PermissionDenied, ValidationFailed
from pigrocrm.core.pipeline.schemas import PipelineStageCreate, PipelineStageUpdate
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")


def test_seed_creates_the_default_italian_sales_process(db_session: Session) -> None:
    stages = PipelineService(db_session).seed_defaults()
    assert [s.nome for s in stages] == [
        "Lead",
        "Contattato",
        "Offerta",
        "Negoziazione",
        "Vinto",
        "Perso",
    ]


def test_seed_marks_the_terminal_stages_so_dashboards_need_no_name_matching(
    db_session: Session,
) -> None:
    """Dashboards must know what 'won' means without string-matching a label the
    user is free to rename."""
    by_name = {s.nome: s for s in PipelineService(db_session).seed_defaults()}
    assert by_name["Vinto"].tipo == "won"
    assert by_name["Perso"].tipo == "lost"
    assert by_name["Lead"].tipo == "open"


def test_seed_is_idempotent(db_session: Session) -> None:
    service = PipelineService(db_session)
    service.seed_defaults()
    service.seed_defaults()
    assert len(service.list()) == 6


def test_list_is_ordered_by_position(db_session: Session) -> None:
    service = PipelineService(db_session)
    service.create(PipelineStageCreate(nome="Secondo", posizione=1), ADMIN)
    service.create(PipelineStageCreate(nome="Primo", posizione=0), ADMIN)
    assert [s.nome for s in service.list()] == ["Primo", "Secondo"]


def test_probability_outside_zero_to_hundred_is_rejected(db_session: Session) -> None:
    service = PipelineService(db_session)
    with pytest.raises(ValidationFailed):
        service.create(PipelineStageCreate(nome="X", posizione=0, probabilita_default=101), ADMIN)


def test_only_admins_configure_the_pipeline(db_session: Session) -> None:
    with pytest.raises(PermissionDenied):
        PipelineService(db_session).create(PipelineStageCreate(nome="X", posizione=0), COLLAB)


def test_update_changes_a_stage(db_session: Session) -> None:
    service = PipelineService(db_session)
    stage = service.create(PipelineStageCreate(nome="Vecchio", posizione=0), ADMIN)
    assert service.update(stage.id, PipelineStageUpdate(nome="Nuovo"), ADMIN).nome == "Nuovo"
```

- [ ] **Step 2: Run them to watch them fail**

Run: `uv run pytest packages/core/tests/test_activities.py packages/core/tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError` for both new packages.

- [ ] **Step 3: Write the activities domain**

`activities/models.py`:

```python
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin


class Activity(Base, PrimaryKeyMixin):
    """One table for the whole timeline.

    Later slices append emails, documents, invoices and time entries by writing new
    `kind` values — no migration. That is what makes the unified timeline free.
    """

    __tablename__ = "activities"
    __table_args__ = (Index("ix_activities_entity", "entity_type", "entity_id", "occurred_at"),)

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(default=None)
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
```

`activities/schemas.py`:

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    kind: str
    actor_id: UUID | None
    actor_type: str
    payload: dict[str, Any]
    occurred_at: datetime
```

`activities/repository.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, activity: Activity) -> Activity:
        self.session.add(activity)
        self.session.flush()
        return activity

    def timeline(self, entity_type: str, entity_id: UUID, limit: int) -> list[Activity]:
        stmt = (
            select(Activity)
            .where(Activity.entity_type == entity_type, Activity.entity_id == entity_id)
            .order_by(Activity.occurred_at.desc(), Activity.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())
```

`activities/service.py`:

```python
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.actor import Actor


class ActivityService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ActivityRepository(session)

    def record(
        self,
        entity_type: str,
        entity_id: UUID,
        kind: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
    ) -> Activity:
        """Flushes but never commits: it joins the caller's transaction so a timeline
        entry can never survive a change that was rolled back."""
        return self.repo.add(
            Activity(
                entity_type=entity_type,
                entity_id=entity_id,
                kind=kind,
                actor_id=actor.id,
                actor_type=actor.type,
                payload=payload or {},
            )
        )

    def timeline(self, entity_type: str, entity_id: UUID, limit: int = 50) -> list[ActivityRead]:
        return [
            ActivityRead.model_validate(a) for a in self.repo.timeline(entity_type, entity_id, limit)
        ]
```

`activities/__init__.py`:

```python
from pigrocrm.core.activities.models import Activity
from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService

__all__ = ["Activity", "ActivityRead", "ActivityService"]
```

- [ ] **Step 4: Write the pipeline domain**

`pipeline/models.py`:

```python
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class PipelineStage(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "pipeline_stages"

    nome: Mapped[str] = mapped_column(String(60), nullable=False)
    posizione: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probabilita_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
```

`pipeline/schemas.py`:

```python
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

StageKind = Literal["open", "won", "lost"]


class PipelineStageCreate(BaseModel):
    nome: str
    posizione: int
    probabilita_default: int = 0
    tipo: StageKind = "open"


class PipelineStageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = None
    posizione: int | None = None
    probabilita_default: int | None = None
    tipo: StageKind | None = None


class PipelineStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    posizione: int
    probabilita_default: int
    tipo: StageKind
```

`pipeline/repository.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.pipeline.models import PipelineStage


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, stage_id: UUID) -> PipelineStage | None:
        return self.session.get(PipelineStage, stage_id)

    def list(self) -> list[PipelineStage]:
        stmt = select(PipelineStage).order_by(PipelineStage.posizione, PipelineStage.nome)
        return list(self.session.execute(stmt).scalars())

    def add(self, stage: PipelineStage) -> PipelineStage:
        self.session.add(stage)
        self.session.flush()
        return stage
```

`pipeline/service.py`:

```python
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.repository import PipelineRepository
from pigrocrm.core.pipeline.schemas import (
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
)

DEFAULT_STAGES: list[tuple[str, int, int, str]] = [
    ("Lead", 0, 10, "open"),
    ("Contattato", 1, 25, "open"),
    ("Offerta", 2, 50, "open"),
    ("Negoziazione", 3, 75, "open"),
    ("Vinto", 4, 100, "won"),
    ("Perso", 5, 0, "lost"),
]


def _check_probability(value: int | None) -> None:
    if value is not None and not 0 <= value <= 100:
        raise ValidationFailed(
            "pipeline_stage", "probabilita_default", "fuori intervallo", expected="0-100"
        )


class PipelineService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = PipelineRepository(session)

    def create(self, data: PipelineStageCreate, actor: Actor) -> PipelineStageRead:
        actor.require_admin("create_pipeline_stage")
        _check_probability(data.probabilita_default)
        stage = self.repo.add(PipelineStage(**data.model_dump()))
        self.session.commit()
        return PipelineStageRead.model_validate(stage)

    def update(
        self, stage_id: UUID, data: PipelineStageUpdate, actor: Actor
    ) -> PipelineStageRead:
        actor.require_admin("update_pipeline_stage")
        stage = self.repo.get(stage_id)
        if stage is None:
            raise NotFound("pipeline_stage", stage_id)
        changes = data.model_dump(exclude_none=True)
        _check_probability(changes.get("probabilita_default"))
        for key, value in changes.items():
            setattr(stage, key, value)
        self.session.commit()
        return PipelineStageRead.model_validate(stage)

    def get(self, stage_id: UUID) -> PipelineStageRead:
        stage = self.repo.get(stage_id)
        if stage is None:
            raise NotFound("pipeline_stage", stage_id)
        return PipelineStageRead.model_validate(stage)

    def list(self) -> list[PipelineStageRead]:
        return [PipelineStageRead.model_validate(s) for s in self.repo.list()]

    def seed_defaults(self) -> list[PipelineStageRead]:
        existing = {s.nome for s in self.repo.list()}
        for nome, posizione, probabilita, tipo in DEFAULT_STAGES:
            if nome not in existing:
                self.repo.add(
                    PipelineStage(
                        nome=nome,
                        posizione=posizione,
                        probabilita_default=probabilita,
                        tipo=tipo,
                    )
                )
        self.session.commit()
        return self.list()

    def default_stage(self) -> PipelineStageRead:
        stages = self.list()
        if not stages:
            raise NotFound("pipeline_stage", "default")
        return stages[0]
```

`pipeline/__init__.py`:

```python
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.schemas import (
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
    StageKind,
)
from pigrocrm.core.pipeline.service import DEFAULT_STAGES, PipelineService

__all__ = [
    "DEFAULT_STAGES",
    "PipelineService",
    "PipelineStage",
    "PipelineStageCreate",
    "PipelineStageRead",
    "PipelineStageUpdate",
    "StageKind",
]
```

- [ ] **Step 5: Register both models**

Append to `models_registry.py`:

```python
from pigrocrm.core.activities.models import Activity  # noqa: F401
from pigrocrm.core.pipeline.models import PipelineStage  # noqa: F401
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/core/tests/test_activities.py packages/core/tests/test_pipeline.py -v`
Expected: PASS (12 passed)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: unified activity timeline and configurable pipeline stages with typed terminals"
```

---

### Task 10: Customers

The first full entity. People and Deals follow the same four-file shape, so get this one right.

**Files:**
- Create: `packages/core/src/pigrocrm/core/customers/{__init__,models,schemas,repository,service}.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Test: `packages/core/tests/test_customers.py`

**Interfaces:**
- Consumes: `FieldDefinitionService.specs_for` (Task 7), `validate_custom_fields` (Task 6), `ActivityService.record` (Task 9), `Actor` and errors (Task 3)
- Produces:
  - `Customer` model — table `customers`, all fiscal columns from spec §5.1, plus `custom_fields` JSONB with a GIN index and `deleted_at`
  - `CustomerCreate`, `CustomerUpdate`, `CustomerRead`, `CustomerListQuery(search=None, stato=None, custom=None, limit=50, cursor=None)`, `CustomerPage(items, next_cursor)`
  - `CustomerService(session)` with `create`, `update`, `get`, `list`, `soft_delete`, `restore`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_customers.py`:

```python
import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate, CustomerListQuery, CustomerUpdate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.errors import NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")
READONLY = Actor(id=None, type="user", role="readonly")


def test_create_requires_only_the_company_name(db_session: Session) -> None:
    customer = CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME Srl"), ADMIN)
    assert customer.ragione_sociale == "ACME Srl"
    assert customer.nazione == "IT", "Italian default, because that is the target market"
    assert customer.custom_fields == {}


def test_fiscal_fields_are_first_class_columns(db_session: Session) -> None:
    """the previous system guessed among vat_number / vat / piva because these were external
    attributes. Here they are columns, so slice 3 can build FatturaPA on them."""
    customer = CustomerService(db_session).create(
        CustomerCreate(
            ragione_sociale="ACME Srl",
            partita_iva="12345678901",
            codice_fiscale="RSSMRA80A01H501U",
            codice_sdi="ABCDEFG",
            pec="acme@pec.it",
        ),
        ADMIN,
    )
    assert customer.partita_iva == "12345678901"
    assert customer.codice_sdi == "ABCDEFG"


@pytest.mark.parametrize("bad", ["1234567890", "123456789012", "1234567890A"])
def test_partita_iva_must_be_eleven_digits(db_session: Session, bad: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        CustomerService(db_session).create(
            CustomerCreate(ragione_sociale="X", partita_iva=bad), ADMIN
        )
    assert exc.value.details["field"] == "partita_iva"


def test_codice_sdi_must_be_seven_characters(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as exc:
        CustomerService(db_session).create(
            CustomerCreate(ragione_sociale="X", codice_sdi="ABC"), ADMIN
        )
    assert exc.value.details["field"] == "codice_sdi"


def test_custom_fields_are_validated_against_the_definitions(db_session: Session) -> None:
    FieldDefinitionService(db_session).create(
        FieldDefinitionCreate(
            entity_type="customer",
            key="stato_cliente",
            label="Stato",
            field_type="select",
            options=["attivo", "sospeso"],
        ),
        ADMIN,
    )
    service = CustomerService(db_session)

    ok = service.create(
        CustomerCreate(ragione_sociale="ACME", custom_fields={"stato_cliente": "attivo"}), ADMIN
    )
    assert ok.custom_fields == {"stato_cliente": "attivo"}

    with pytest.raises(ValidationFailed):
        service.create(
            CustomerCreate(ragione_sociale="B", custom_fields={"stato_cliente": "chiuso"}), ADMIN
        )


def test_undefined_custom_field_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValidationFailed):
        CustomerService(db_session).create(
            CustomerCreate(ragione_sociale="X", custom_fields={"inventato": "v"}), ADMIN
        )


def test_create_records_a_timeline_entry_naming_the_actor(db_session: Session) -> None:
    from pigrocrm.core.activities.service import ActivityService

    customer = CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    entries = ActivityService(db_session).timeline("customer", customer.id)
    assert [e.kind for e in entries] == ["created"]
    assert entries[0].actor_type == "system"


def test_update_records_only_the_changed_fields(db_session: Session) -> None:
    from pigrocrm.core.activities.service import ActivityService

    service = CustomerService(db_session)
    customer = service.create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    service.update(customer.id, CustomerUpdate(telefono="0212345"), ADMIN)

    updates = [e for e in ActivityService(db_session).timeline("customer", customer.id)
               if e.kind == "updated"]
    assert updates[0].payload["changed"] == ["telefono"]


def test_readonly_cannot_write_but_can_read(db_session: Session) -> None:
    service = CustomerService(db_session)
    customer = service.create(CustomerCreate(ragione_sociale="ACME"), ADMIN)

    assert service.get(customer.id, READONLY).id == customer.id
    with pytest.raises(PermissionDenied):
        service.create(CustomerCreate(ragione_sociale="B"), READONLY)


def test_collaborator_can_write(db_session: Session) -> None:
    assert CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), COLLAB)


def test_soft_delete_hides_the_row_without_removing_it(db_session: Session) -> None:
    service = CustomerService(db_session)
    customer = service.create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    service.soft_delete(customer.id, ADMIN)

    with pytest.raises(NotFound):
        service.get(customer.id, ADMIN)
    assert service.list(CustomerListQuery(), ADMIN).items == []
    assert service.restore(customer.id, ADMIN).ragione_sociale == "ACME"


def test_search_matches_name_vat_and_email(db_session: Session) -> None:
    service = CustomerService(db_session)
    service.create(
        CustomerCreate(ragione_sociale="ACME Srl", partita_iva="12345678901", email="a@acme.it"),
        ADMIN,
    )
    service.create(CustomerCreate(ragione_sociale="Beta Spa"), ADMIN)

    assert len(service.list(CustomerListQuery(search="acme"), ADMIN).items) == 1
    assert len(service.list(CustomerListQuery(search="12345678901"), ADMIN).items) == 1
    assert len(service.list(CustomerListQuery(search="a@acme.it"), ADMIN).items) == 1
    assert len(service.list(CustomerListQuery(search="zzz"), ADMIN).items) == 0


def test_filter_by_custom_field_uses_jsonb_containment(db_session: Session) -> None:
    FieldDefinitionService(db_session).create(
        FieldDefinitionCreate(
            entity_type="customer", key="settore", label="Settore", field_type="text"
        ),
        ADMIN,
    )
    service = CustomerService(db_session)
    service.create(CustomerCreate(ragione_sociale="A", custom_fields={"settore": "IT"}), ADMIN)
    service.create(CustomerCreate(ragione_sociale="B", custom_fields={"settore": "Retail"}), ADMIN)

    page = service.list(CustomerListQuery(custom={"settore": "IT"}), ADMIN)
    assert [c.ragione_sociale for c in page.items] == ["A"]


def test_pagination_returns_a_cursor_and_does_not_repeat_rows(db_session: Session) -> None:
    service = CustomerService(db_session)
    for index in range(5):
        service.create(CustomerCreate(ragione_sociale=f"Cliente {index:02d}"), ADMIN)

    first = service.list(CustomerListQuery(limit=2), ADMIN)
    assert len(first.items) == 2
    assert first.next_cursor is not None

    second = service.list(CustomerListQuery(limit=2, cursor=first.next_cursor), ADMIN)
    assert {c.id for c in first.items}.isdisjoint({c.id for c in second.items})


def test_last_page_has_no_cursor(db_session: Session) -> None:
    service = CustomerService(db_session)
    service.create(CustomerCreate(ragione_sociale="Solo"), ADMIN)
    assert service.list(CustomerListQuery(limit=10), ADMIN).next_cursor is None


def test_get_missing_customer_raises_not_found(db_session: Session) -> None:
    from uuid import uuid4

    with pytest.raises(NotFound):
        CustomerService(db_session).get(uuid4(), ADMIN)
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_customers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.customers'`

- [ ] **Step 3: Write `customers/models.py`**

```python
from typing import Any

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin


class Customer(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_custom_fields", "custom_fields", postgresql_using="gin"),
        Index("ix_customers_ragione_sociale", "ragione_sociale"),
    )

    ragione_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    partita_iva: Mapped[str | None] = mapped_column(String(11), default=None, index=True)
    codice_fiscale: Mapped[str | None] = mapped_column(String(16), default=None)
    codice_sdi: Mapped[str | None] = mapped_column(String(7), default=None)
    pec: Mapped[str | None] = mapped_column(String(320), default=None)
    indirizzo: Mapped[str | None] = mapped_column(String(255), default=None)
    cap: Mapped[str | None] = mapped_column(String(10), default=None)
    comune: Mapped[str | None] = mapped_column(String(120), default=None)
    provincia: Mapped[str | None] = mapped_column(String(2), default=None)
    nazione: Mapped[str] = mapped_column(String(2), nullable=False, default="IT")
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    telefono: Mapped[str | None] = mapped_column(String(40), default=None)
    sito_web: Mapped[str | None] = mapped_column(String(255), default=None)
    stato: Mapped[str | None] = mapped_column(String(40), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
```

- [ ] **Step 4: Write `customers/schemas.py`**

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    ragione_sociale: str
    partita_iva: str | None = None
    codice_fiscale: str | None = None
    codice_sdi: str | None = None
    pec: str | None = None
    indirizzo: str | None = None
    cap: str | None = None
    comune: str | None = None
    provincia: str | None = None
    nazione: str = "IT"
    email: str | None = None
    telefono: str | None = None
    sito_web: str | None = None
    stato: str | None = None
    note: str | None = None
    custom_fields: dict[str, Any] = {}


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ragione_sociale: str | None = None
    partita_iva: str | None = None
    codice_fiscale: str | None = None
    codice_sdi: str | None = None
    pec: str | None = None
    indirizzo: str | None = None
    cap: str | None = None
    comune: str | None = None
    provincia: str | None = None
    nazione: str | None = None
    email: str | None = None
    telefono: str | None = None
    sito_web: str | None = None
    stato: str | None = None
    note: str | None = None
    custom_fields: dict[str, Any] | None = None


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ragione_sociale: str
    partita_iva: str | None
    codice_fiscale: str | None
    codice_sdi: str | None
    pec: str | None
    indirizzo: str | None
    cap: str | None
    comune: str | None
    provincia: str | None
    nazione: str
    email: str | None
    telefono: str | None
    sito_web: str | None
    stato: str | None
    note: str | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CustomerListQuery(BaseModel):
    search: str | None = None
    stato: str | None = None
    custom: dict[str, Any] | None = None
    limit: int = 50
    cursor: UUID | None = None


class CustomerPage(BaseModel):
    items: list[CustomerRead]
    next_cursor: UUID | None
```

- [ ] **Step 5: Write `customers/repository.py`**

```python
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.customers.schemas import CustomerListQuery


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, customer_id: UUID, *, include_deleted: bool = False) -> Customer | None:
        customer = self.session.get(Customer, customer_id)
        if customer is None:
            return None
        if customer.deleted_at is not None and not include_deleted:
            return None
        return customer

    def add(self, customer: Customer) -> Customer:
        self.session.add(customer)
        self.session.flush()
        return customer

    def list(self, query: CustomerListQuery) -> list[Customer]:
        stmt = select(Customer).where(Customer.deleted_at.is_(None))

        if query.search:
            like = f"%{query.search.lower()}%"
            stmt = stmt.where(
                or_(
                    Customer.ragione_sociale.ilike(like),
                    Customer.partita_iva.ilike(like),
                    Customer.email.ilike(like),
                    Customer.codice_fiscale.ilike(like),
                )
            )
        if query.stato:
            stmt = stmt.where(Customer.stato == query.stato)
        if query.custom:
            # JSONB containment, served by the GIN index.
            stmt = stmt.where(Customer.custom_fields.contains(query.custom))
        if query.cursor:
            stmt = stmt.where(Customer.id > query.cursor)

        # Keyset pagination on a UUIDv7 id: ordered by creation, stable under inserts.
        return list(
            self.session.execute(stmt.order_by(Customer.id).limit(query.limit + 1)).scalars()
        )

    def count_active_deals(self, customer_id: UUID) -> int:
        """Queries the deals table through the metadata rather than importing the model.

        Deals are written in Task 12. Importing `pigrocrm.core.deals.models` here —
        at module level or inside the function — would raise ModuleNotFoundError in
        this task's own tests. Going through `Base.metadata` keeps the dependency
        one-directional and lets this method start returning real counts the moment
        the deals model is registered, with no edit here.
        """
        deals = Base.metadata.tables.get("deals")
        if deals is None:
            return 0
        stmt = (
            select(func.count())
            .select_from(deals)
            .where(deals.c.customer_id == customer_id, deals.c.deleted_at.is_(None))
        )
        return int(self.session.execute(stmt).scalar_one())
```

The imports at the top of this file must therefore be:

```python
from sqlalchemy import func, or_, select

from pigrocrm.core.db import Base
```

- [ ] **Step 6: Write `customers/service.py`**

```python
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.customers.repository import CustomerRepository
from pigrocrm.core.customers.schemas import (
    CustomerCreate,
    CustomerListQuery,
    CustomerPage,
    CustomerRead,
    CustomerUpdate,
)
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields

ENTITY = "customer"
PARTITA_IVA_RE = re.compile(r"^\d{11}$")
CODICE_SDI_LENGTH = 7


def _check_fiscal(data: dict[str, Any]) -> None:
    piva = data.get("partita_iva")
    if piva and not PARTITA_IVA_RE.match(piva):
        raise ValidationFailed(
            ENTITY, "partita_iva", "deve essere di 11 cifre", expected="11 cifre numeriche"
        )
    sdi = data.get("codice_sdi")
    if sdi and len(sdi) != CODICE_SDI_LENGTH:
        raise ValidationFailed(
            ENTITY, "codice_sdi", "deve essere di 7 caratteri", expected="7 caratteri"
        )


class CustomerService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CustomerRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def create(self, data: CustomerCreate, actor: Actor) -> CustomerRead:
        actor.require_write("create_customer")
        payload = data.model_dump()
        _check_fiscal(payload)
        payload["custom_fields"] = self._validated_custom(payload.get("custom_fields") or {})

        customer = self.repo.add(Customer(**payload))
        self.activities.record(
            ENTITY, customer.id, "created", actor, {"ragione_sociale": customer.ragione_sociale}
        )
        self.session.commit()
        return CustomerRead.model_validate(customer)

    def update(self, customer_id: UUID, data: CustomerUpdate, actor: Actor) -> CustomerRead:
        actor.require_write("update_customer")
        customer = self.repo.get(customer_id)
        if customer is None:
            raise NotFound(ENTITY, customer_id)

        changes = data.model_dump(exclude_none=True)
        _check_fiscal(changes)
        if "custom_fields" in changes:
            merged = {**customer.custom_fields, **changes["custom_fields"]}
            changes["custom_fields"] = self._validated_custom(merged)
        for key, value in changes.items():
            setattr(customer, key, value)

        self.activities.record(
            ENTITY, customer.id, "updated", actor, {"changed": sorted(changes)}
        )
        self.session.commit()
        return CustomerRead.model_validate(customer)

    def get(self, customer_id: UUID, actor: Actor) -> CustomerRead:
        customer = self.repo.get(customer_id)
        if customer is None:
            raise NotFound(ENTITY, customer_id)
        return CustomerRead.model_validate(customer)

    def list(self, query: CustomerListQuery, actor: Actor) -> CustomerPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return CustomerPage(
            items=[CustomerRead.model_validate(c) for c in items],
            next_cursor=items[-1].id if has_more and items else None,
        )

    def soft_delete(self, customer_id: UUID, actor: Actor) -> None:
        """Sets deleted_at. No physical delete exists in this slice: a misread
        instruction from an agent must be reversible."""
        actor.require_write("delete_customer")
        customer = self.repo.get(customer_id)
        if customer is None:
            raise NotFound(ENTITY, customer_id)

        active_deals = self.repo.count_active_deals(customer_id)
        if active_deals:
            raise Conflict(
                ENTITY,
                "il cliente ha deal attivi: archivia prima i deal",
                active_deals=active_deals,
            )

        customer.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, customer.id, "deleted", actor)
        self.session.commit()

    def restore(self, customer_id: UUID, actor: Actor) -> CustomerRead:
        actor.require_write("restore_customer")
        customer = self.repo.get(customer_id, include_deleted=True)
        if customer is None:
            raise NotFound(ENTITY, customer_id)
        customer.deleted_at = None
        self.activities.record(ENTITY, customer.id, "restored", actor)
        self.session.commit()
        return CustomerRead.model_validate(customer)
```

`customers/__init__.py`:

```python
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.customers.schemas import (
    CustomerCreate,
    CustomerListQuery,
    CustomerPage,
    CustomerRead,
    CustomerUpdate,
)
from pigrocrm.core.customers.service import CustomerService

__all__ = [
    "Customer",
    "CustomerCreate",
    "CustomerListQuery",
    "CustomerPage",
    "CustomerRead",
    "CustomerService",
    "CustomerUpdate",
]
```

- [ ] **Step 7: Register the model**

Append to `models_registry.py`:

```python
from pigrocrm.core.customers.models import Customer  # noqa: F401
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest packages/core/tests/test_customers.py -v`
Expected: PASS (18 passed)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: customers with first-class fiscal columns, JSONB custom fields and soft delete"
```

---

### Task 11: People

**Files:**
- Create: `packages/core/src/pigrocrm/core/people/{__init__,models,schemas,repository,service}.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Test: `packages/core/tests/test_people.py`

**Interfaces:**
- Consumes: `Customer` (Task 10), fields, activities, `Actor`
- Produces:
  - `Person` model — table `people`, `customer_id` **nullable** FK, `nome`, `cognome`, `email`, `telefono`, `ruolo`, `linkedin`, `note`, `custom_fields`, `deleted_at`
  - `PersonCreate`, `PersonUpdate`, `PersonRead`, `PersonListQuery(search=None, customer_id=None, custom=None, limit=50, cursor=None)`, `PersonPage(items, next_cursor)`
  - `PersonService(session)` with `create`, `update`, `get`, `list`, `soft_delete`, `restore`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_people.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.errors import NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.people.schemas import PersonCreate, PersonListQuery, PersonUpdate
from pigrocrm.core.people.service import PersonService

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")


def test_a_person_can_exist_without_a_customer(db_session: Session) -> None:
    """Forcing the association produces phantom customers called 'Freelance vari'."""
    person = PersonService(db_session).create(PersonCreate(nome="Mario"), ADMIN)
    assert person.customer_id is None


def test_a_person_can_be_attached_to_a_customer(db_session: Session) -> None:
    customer = CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    person = PersonService(db_session).create(
        PersonCreate(nome="Mario", cognome="Rossi", customer_id=customer.id), ADMIN
    )
    assert person.customer_id == customer.id


def test_attaching_to_a_missing_customer_is_rejected(db_session: Session) -> None:
    with pytest.raises(NotFound) as exc:
        PersonService(db_session).create(PersonCreate(nome="Mario", customer_id=uuid4()), ADMIN)
    assert exc.value.details["entity"] == "customer"


def test_invalid_email_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as exc:
        PersonService(db_session).create(PersonCreate(nome="Mario", email="non-una-email"), ADMIN)
    assert exc.value.details["field"] == "email"


def test_email_is_normalised_to_lowercase(db_session: Session) -> None:
    person = PersonService(db_session).create(
        PersonCreate(nome="Mario", email="  Mario@ACME.IT "), ADMIN
    )
    assert person.email == "mario@acme.it"


def test_create_records_a_timeline_entry(db_session: Session) -> None:
    from pigrocrm.core.activities.service import ActivityService

    person = PersonService(db_session).create(PersonCreate(nome="Mario"), ADMIN)
    assert [e.kind for e in ActivityService(db_session).timeline("person", person.id)] == ["created"]


def test_list_can_be_filtered_by_customer(db_session: Session) -> None:
    customer = CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    service = PersonService(db_session)
    service.create(PersonCreate(nome="Dentro", customer_id=customer.id), ADMIN)
    service.create(PersonCreate(nome="Fuori"), ADMIN)

    page = service.list(PersonListQuery(customer_id=customer.id), ADMIN)
    assert [p.nome for p in page.items] == ["Dentro"]


def test_search_matches_name_surname_and_email(db_session: Session) -> None:
    service = PersonService(db_session)
    service.create(PersonCreate(nome="Mario", cognome="Rossi", email="mr@acme.it"), ADMIN)
    service.create(PersonCreate(nome="Luigi", cognome="Verdi"), ADMIN)

    assert len(service.list(PersonListQuery(search="rossi"), ADMIN).items) == 1
    assert len(service.list(PersonListQuery(search="mr@acme.it"), ADMIN).items) == 1
    assert len(service.list(PersonListQuery(search="mario"), ADMIN).items) == 1


def test_update_can_detach_a_person_from_a_customer(db_session: Session) -> None:
    customer = CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    service = PersonService(db_session)
    person = service.create(PersonCreate(nome="Mario", customer_id=customer.id), ADMIN)

    detached = service.update(person.id, PersonUpdate(customer_id=None, detach=True), ADMIN)
    assert detached.customer_id is None


def test_soft_delete_then_restore(db_session: Session) -> None:
    service = PersonService(db_session)
    person = service.create(PersonCreate(nome="Mario"), ADMIN)
    service.soft_delete(person.id, ADMIN)

    with pytest.raises(NotFound):
        service.get(person.id, ADMIN)
    assert service.restore(person.id, ADMIN).nome == "Mario"


def test_readonly_cannot_create(db_session: Session) -> None:
    with pytest.raises(PermissionDenied):
        PersonService(db_session).create(PersonCreate(nome="Mario"), READONLY)


def test_custom_fields_are_validated(db_session: Session) -> None:
    from pigrocrm.core.fields.schemas import FieldDefinitionCreate
    from pigrocrm.core.fields.service import FieldDefinitionService

    FieldDefinitionService(db_session).create(
        FieldDefinitionCreate(
            entity_type="person", key="seniority", label="Seniority", field_type="text"
        ),
        ADMIN,
    )
    person = PersonService(db_session).create(
        PersonCreate(nome="Mario", custom_fields={"seniority": "Senior"}), ADMIN
    )
    assert person.custom_fields == {"seniority": "Senior"}

    with pytest.raises(ValidationFailed):
        PersonService(db_session).create(
            PersonCreate(nome="Luigi", custom_fields={"inventato": "x"}), ADMIN
        )
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_people.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.people'`

- [ ] **Step 3: Write `people/models.py`**

```python
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin


class Person(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "people"
    __table_args__ = (
        Index("ix_people_custom_fields", "custom_fields", postgresql_using="gin"),
    )

    # Nullable on purpose: a contact may exist before you know who they work for.
    customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id"), default=None, index=True
    )
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    cognome: Mapped[str | None] = mapped_column(String(120), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
    telefono: Mapped[str | None] = mapped_column(String(40), default=None)
    ruolo: Mapped[str | None] = mapped_column(String(120), default=None)
    linkedin: Mapped[str | None] = mapped_column(String(255), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
```

- [ ] **Step 4: Write `people/schemas.py`**

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


def _normalise_email(value: str | None) -> str | None:
    return value.strip().lower() if isinstance(value, str) else value


class PersonCreate(BaseModel):
    nome: str
    cognome: str | None = None
    email: str | None = None
    telefono: str | None = None
    ruolo: str | None = None
    linkedin: str | None = None
    note: str | None = None
    customer_id: UUID | None = None
    custom_fields: dict[str, Any] = {}

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return _normalise_email(value)


class PersonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = None
    cognome: str | None = None
    email: str | None = None
    telefono: str | None = None
    ruolo: str | None = None
    linkedin: str | None = None
    note: str | None = None
    customer_id: UUID | None = None
    custom_fields: dict[str, Any] | None = None
    # `exclude_none` cannot express "set customer_id back to null", so detaching is explicit.
    detach: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return _normalise_email(value)


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    cognome: str | None
    email: str | None
    telefono: str | None
    ruolo: str | None
    linkedin: str | None
    note: str | None
    customer_id: UUID | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PersonListQuery(BaseModel):
    search: str | None = None
    customer_id: UUID | None = None
    custom: dict[str, Any] | None = None
    limit: int = 50
    cursor: UUID | None = None


class PersonPage(BaseModel):
    items: list[PersonRead]
    next_cursor: UUID | None
```

- [ ] **Step 5: Write `people/repository.py`**

```python
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pigrocrm.core.people.models import Person
from pigrocrm.core.people.schemas import PersonListQuery


class PersonRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, person_id: UUID, *, include_deleted: bool = False) -> Person | None:
        person = self.session.get(Person, person_id)
        if person is None:
            return None
        if person.deleted_at is not None and not include_deleted:
            return None
        return person

    def add(self, person: Person) -> Person:
        self.session.add(person)
        self.session.flush()
        return person

    def list(self, query: PersonListQuery) -> list[Person]:
        stmt = select(Person).where(Person.deleted_at.is_(None))

        if query.search:
            like = f"%{query.search.lower()}%"
            stmt = stmt.where(
                or_(Person.nome.ilike(like), Person.cognome.ilike(like), Person.email.ilike(like))
            )
        if query.customer_id:
            stmt = stmt.where(Person.customer_id == query.customer_id)
        if query.custom:
            stmt = stmt.where(Person.custom_fields.contains(query.custom))
        if query.cursor:
            stmt = stmt.where(Person.id > query.cursor)

        return list(self.session.execute(stmt.order_by(Person.id).limit(query.limit + 1)).scalars())
```

- [ ] **Step 6: Write `people/service.py`**

```python
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.repository import CustomerRepository
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.people.models import Person
from pigrocrm.core.people.repository import PersonRepository
from pigrocrm.core.people.schemas import (
    PersonCreate,
    PersonListQuery,
    PersonPage,
    PersonRead,
    PersonUpdate,
)

ENTITY = "person"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_email(email: str | None) -> None:
    if email and not EMAIL_RE.match(email):
        raise ValidationFailed(ENTITY, "email", "indirizzo non valido", expected="nome@dominio.it")


class PersonService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = PersonRepository(session)
        self.customers = CustomerRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    def _check_customer(self, customer_id: UUID | None) -> None:
        if customer_id is not None and self.customers.get(customer_id) is None:
            raise NotFound("customer", customer_id)

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def create(self, data: PersonCreate, actor: Actor) -> PersonRead:
        actor.require_write("create_person")
        payload = data.model_dump()
        _check_email(payload.get("email"))
        self._check_customer(payload.get("customer_id"))
        payload["custom_fields"] = self._validated_custom(payload.get("custom_fields") or {})

        person = self.repo.add(Person(**payload))
        self.activities.record(ENTITY, person.id, "created", actor, {"nome": person.nome})
        self.session.commit()
        return PersonRead.model_validate(person)

    def update(self, person_id: UUID, data: PersonUpdate, actor: Actor) -> PersonRead:
        actor.require_write("update_person")
        person = self.repo.get(person_id)
        if person is None:
            raise NotFound(ENTITY, person_id)

        changes = data.model_dump(exclude_none=True, exclude={"detach"})
        _check_email(changes.get("email"))
        if "customer_id" in changes:
            self._check_customer(changes["customer_id"])
        if "custom_fields" in changes:
            merged = {**person.custom_fields, **changes["custom_fields"]}
            changes["custom_fields"] = self._validated_custom(merged)
        for key, value in changes.items():
            setattr(person, key, value)
        if data.detach:
            person.customer_id = None
            changes["customer_id"] = None

        self.activities.record(ENTITY, person.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return PersonRead.model_validate(person)

    def get(self, person_id: UUID, actor: Actor) -> PersonRead:
        person = self.repo.get(person_id)
        if person is None:
            raise NotFound(ENTITY, person_id)
        return PersonRead.model_validate(person)

    def list(self, query: PersonListQuery, actor: Actor) -> PersonPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return PersonPage(
            items=[PersonRead.model_validate(p) for p in items],
            next_cursor=items[-1].id if has_more and items else None,
        )

    def soft_delete(self, person_id: UUID, actor: Actor) -> None:
        actor.require_write("delete_person")
        person = self.repo.get(person_id)
        if person is None:
            raise NotFound(ENTITY, person_id)
        person.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, person.id, "deleted", actor)
        self.session.commit()

    def restore(self, person_id: UUID, actor: Actor) -> PersonRead:
        actor.require_write("restore_person")
        person = self.repo.get(person_id, include_deleted=True)
        if person is None:
            raise NotFound(ENTITY, person_id)
        person.deleted_at = None
        self.activities.record(ENTITY, person.id, "restored", actor)
        self.session.commit()
        return PersonRead.model_validate(person)
```

`people/__init__.py`:

```python
from pigrocrm.core.people.models import Person
from pigrocrm.core.people.schemas import (
    PersonCreate,
    PersonListQuery,
    PersonPage,
    PersonRead,
    PersonUpdate,
)
from pigrocrm.core.people.service import PersonService

__all__ = [
    "Person",
    "PersonCreate",
    "PersonListQuery",
    "PersonPage",
    "PersonRead",
    "PersonService",
    "PersonUpdate",
]
```

- [ ] **Step 7: Register the model**

Append to `models_registry.py`:

```python
from pigrocrm.core.people.models import Person  # noqa: F401
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest packages/core/tests/test_people.py -v`
Expected: PASS (13 passed)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: people with optional customer association and explicit detach"
```

---

### Task 12: Deals

**Files:**
- Create: `packages/core/src/pigrocrm/core/deals/{__init__,models,schemas,repository,service}.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Test: `packages/core/tests/test_deals.py`

**Interfaces:**
- Consumes: `Customer` (Task 10), `PipelineService` (Task 9), fields, activities
- Produces:
  - `Deal` model — table `deals`, `customer_id` **required** FK, `pipeline_stage_id` FK, `nome`, `valore_previsto`, `probabilita`, `data_chiusura_prevista`, `owner_id`, `note`, `ore_preventivate`, `valore_preventivato`, `custom_fields`, `deleted_at`
  - `DealCreate`, `DealUpdate`, `DealRead`, `DealListQuery(search=None, customer_id=None, stage_id=None, custom=None, limit=50, cursor=None)`, `DealPage(items, next_cursor)`
  - `DealService(session)` with `create`, `update`, `get`, `list`, `move_stage(deal_id, stage_id, actor)`, `soft_delete`, `restore`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_deals.py`:

```python
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.deals.schemas import DealCreate, DealListQuery, DealUpdate
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")


@pytest.fixture
def customer_id(db_session: Session):
    return CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), ADMIN).id


@pytest.fixture
def stages(db_session: Session):
    return {s.nome: s for s in PipelineService(db_session).seed_defaults()}


def test_a_deal_requires_a_customer(db_session: Session, customer_id, stages) -> None:
    deal = DealService(db_session).create(
        DealCreate(nome="Progetto X", customer_id=customer_id), ADMIN
    )
    assert deal.customer_id == customer_id


def test_a_deal_for_a_missing_customer_is_rejected(db_session: Session, stages) -> None:
    with pytest.raises(NotFound) as exc:
        DealService(db_session).create(DealCreate(nome="X", customer_id=uuid4()), ADMIN)
    assert exc.value.details["entity"] == "customer"


def test_a_new_deal_lands_in_the_first_stage_by_default(
    db_session: Session, customer_id, stages
) -> None:
    deal = DealService(db_session).create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    assert deal.pipeline_stage_id == stages["Lead"].id


def test_a_new_deal_inherits_the_stage_default_probability(
    db_session: Session, customer_id, stages
) -> None:
    deal = DealService(db_session).create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    assert deal.probabilita == stages["Lead"].probabilita_default


def test_an_explicit_probability_wins_over_the_stage_default(
    db_session: Session, customer_id, stages
) -> None:
    deal = DealService(db_session).create(
        DealCreate(nome="X", customer_id=customer_id, probabilita=42), ADMIN
    )
    assert deal.probabilita == 42


def test_money_keeps_two_decimals_and_does_not_drift(
    db_session: Session, customer_id, stages
) -> None:
    """Float would turn 1234.56 into 1234.5599999. On an invoice that is a bug."""
    deal = DealService(db_session).create(
        DealCreate(nome="X", customer_id=customer_id, valore_previsto=Decimal("1234.56")), ADMIN
    )
    assert deal.valore_previsto == Decimal("1234.56")


def test_probability_outside_range_is_rejected(db_session: Session, customer_id, stages) -> None:
    with pytest.raises(ValidationFailed) as exc:
        DealService(db_session).create(
            DealCreate(nome="X", customer_id=customer_id, probabilita=150), ADMIN
        )
    assert exc.value.details["field"] == "probabilita"


def test_negative_value_is_rejected(db_session: Session, customer_id, stages) -> None:
    with pytest.raises(ValidationFailed):
        DealService(db_session).create(
            DealCreate(nome="X", customer_id=customer_id, valore_previsto=Decimal("-1")), ADMIN
        )


def test_move_stage_updates_the_deal_and_the_timeline(
    db_session: Session, customer_id, stages
) -> None:
    from pigrocrm.core.activities.service import ActivityService

    service = DealService(db_session)
    deal = service.create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    moved = service.move_stage(deal.id, stages["Offerta"].id, ADMIN)

    assert moved.pipeline_stage_id == stages["Offerta"].id
    entry = next(
        e for e in ActivityService(db_session).timeline("deal", deal.id) if e.kind == "stage_changed"
    )
    assert entry.payload["to"] == "Offerta"
    assert entry.payload["from"] == "Lead"


def test_move_to_a_missing_stage_is_rejected(db_session: Session, customer_id, stages) -> None:
    service = DealService(db_session)
    deal = service.create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    with pytest.raises(NotFound):
        service.move_stage(deal.id, uuid4(), ADMIN)


def test_moving_to_a_won_stage_sets_probability_to_one_hundred(
    db_session: Session, customer_id, stages
) -> None:
    service = DealService(db_session)
    deal = service.create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    assert service.move_stage(deal.id, stages["Vinto"].id, ADMIN).probabilita == 100


def test_moving_to_a_lost_stage_sets_probability_to_zero(
    db_session: Session, customer_id, stages
) -> None:
    service = DealService(db_session)
    deal = service.create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    assert service.move_stage(deal.id, stages["Perso"].id, ADMIN).probabilita == 0


def test_list_can_be_filtered_by_customer_and_by_stage(
    db_session: Session, customer_id, stages
) -> None:
    other = CustomerService(db_session).create(CustomerCreate(ragione_sociale="Beta"), ADMIN).id
    service = DealService(db_session)
    service.create(DealCreate(nome="Mio", customer_id=customer_id), ADMIN)
    service.create(DealCreate(nome="Altro", customer_id=other), ADMIN)

    assert [d.nome for d in service.list(DealListQuery(customer_id=customer_id), ADMIN).items] == [
        "Mio"
    ]
    assert len(service.list(DealListQuery(stage_id=stages["Lead"].id), ADMIN).items) == 2


def test_estimate_fields_exist_for_the_later_pnl_slice(
    db_session: Session, customer_id, stages
) -> None:
    deal = DealService(db_session).create(
        DealCreate(
            nome="X",
            customer_id=customer_id,
            ore_preventivate=Decimal("120.50"),
            valore_preventivato=Decimal("15000.00"),
        ),
        ADMIN,
    )
    assert deal.ore_preventivate == Decimal("120.50")
    assert deal.valore_preventivato == Decimal("15000.00")


def test_a_customer_with_active_deals_cannot_be_deleted(
    db_session: Session, customer_id, stages
) -> None:
    """Deleting must not cascade silently; the error says how many deals are in the way."""
    DealService(db_session).create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    with pytest.raises(Conflict) as exc:
        CustomerService(db_session).soft_delete(customer_id, ADMIN)
    assert exc.value.details["active_deals"] == 1


def test_deleting_the_deal_first_then_the_customer_works(
    db_session: Session, customer_id, stages
) -> None:
    service = DealService(db_session)
    deal = service.create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    service.soft_delete(deal.id, ADMIN)
    CustomerService(db_session).soft_delete(customer_id, ADMIN)

    with pytest.raises(NotFound):
        CustomerService(db_session).get(customer_id, ADMIN)


def test_readonly_cannot_move_a_deal(db_session: Session, customer_id, stages) -> None:
    service = DealService(db_session)
    deal = service.create(DealCreate(nome="X", customer_id=customer_id), ADMIN)
    with pytest.raises(PermissionDenied) as exc:
        service.move_stage(deal.id, stages["Offerta"].id, READONLY)
    assert exc.value.details["actual_role"] == "readonly"


def test_update_changes_name_and_records_it(db_session: Session, customer_id, stages) -> None:
    service = DealService(db_session)
    deal = service.create(DealCreate(nome="Vecchio", customer_id=customer_id), ADMIN)
    assert service.update(deal.id, DealUpdate(nome="Nuovo"), ADMIN).nome == "Nuovo"
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_deals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.deals'`

- [ ] **Step 3: Write `deals/models.py`**

```python
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin


class Deal(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "deals"
    __table_args__ = (Index("ix_deals_custom_fields", "custom_fields", postgresql_using="gin"),)

    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    # Required: a deal without a customer has no economic meaning.
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    pipeline_stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_stages.id"), nullable=False, index=True
    )
    valore_previsto: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    probabilita: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_chiusura_prevista: Mapped[date | None] = mapped_column(Date, default=None)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    # Written now, consumed by the slice 4 estimate-vs-actual report. Costs nothing today.
    ore_preventivate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), default=None)
    valore_preventivato: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
```

- [ ] **Step 4: Write `deals/schemas.py`**

```python
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DealCreate(BaseModel):
    nome: str
    customer_id: UUID
    pipeline_stage_id: UUID | None = None
    valore_previsto: Decimal | None = None
    probabilita: int | None = None
    data_chiusura_prevista: date | None = None
    owner_id: UUID | None = None
    note: str | None = None
    ore_preventivate: Decimal | None = None
    valore_preventivato: Decimal | None = None
    custom_fields: dict[str, Any] = {}


class DealUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = None
    valore_previsto: Decimal | None = None
    probabilita: int | None = None
    data_chiusura_prevista: date | None = None
    owner_id: UUID | None = None
    note: str | None = None
    ore_preventivate: Decimal | None = None
    valore_preventivato: Decimal | None = None
    custom_fields: dict[str, Any] | None = None


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    customer_id: UUID
    pipeline_stage_id: UUID
    valore_previsto: Decimal | None
    probabilita: int
    data_chiusura_prevista: date | None
    owner_id: UUID | None
    note: str | None
    ore_preventivate: Decimal | None
    valore_preventivato: Decimal | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DealListQuery(BaseModel):
    search: str | None = None
    customer_id: UUID | None = None
    stage_id: UUID | None = None
    custom: dict[str, Any] | None = None
    limit: int = 50
    cursor: UUID | None = None


class DealPage(BaseModel):
    items: list[DealRead]
    next_cursor: UUID | None
```

- [ ] **Step 5: Write `deals/repository.py`**

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.schemas import DealListQuery


class DealRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, deal_id: UUID, *, include_deleted: bool = False) -> Deal | None:
        deal = self.session.get(Deal, deal_id)
        if deal is None:
            return None
        if deal.deleted_at is not None and not include_deleted:
            return None
        return deal

    def add(self, deal: Deal) -> Deal:
        self.session.add(deal)
        self.session.flush()
        return deal

    def list(self, query: DealListQuery) -> list[Deal]:
        stmt = select(Deal).where(Deal.deleted_at.is_(None))

        if query.search:
            stmt = stmt.where(Deal.nome.ilike(f"%{query.search.lower()}%"))
        if query.customer_id:
            stmt = stmt.where(Deal.customer_id == query.customer_id)
        if query.stage_id:
            stmt = stmt.where(Deal.pipeline_stage_id == query.stage_id)
        if query.custom:
            stmt = stmt.where(Deal.custom_fields.contains(query.custom))
        if query.cursor:
            stmt = stmt.where(Deal.id > query.cursor)

        return list(self.session.execute(stmt.order_by(Deal.id).limit(query.limit + 1)).scalars())
```

- [ ] **Step 6: Write `deals/service.py`**

```python
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.repository import CustomerRepository
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.deals.schemas import (
    DealCreate,
    DealListQuery,
    DealPage,
    DealRead,
    DealUpdate,
)
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.pipeline.service import PipelineService

ENTITY = "deal"


def _check_numbers(values: dict[str, Any]) -> None:
    probabilita = values.get("probabilita")
    if probabilita is not None and not 0 <= probabilita <= 100:
        raise ValidationFailed(ENTITY, "probabilita", "fuori intervallo", expected="0-100")
    for field in ("valore_previsto", "valore_preventivato", "ore_preventivate"):
        value = values.get(field)
        if value is not None and Decimal(value) < 0:
            raise ValidationFailed(ENTITY, field, "non può essere negativo", expected=">= 0")


class DealService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = DealRepository(session)
        self.customers = CustomerRepository(session)
        self.pipeline = PipelineService(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def create(self, data: DealCreate, actor: Actor) -> DealRead:
        actor.require_write("create_deal")
        payload = data.model_dump()
        _check_numbers(payload)

        if self.customers.get(payload["customer_id"]) is None:
            raise NotFound("customer", payload["customer_id"])

        stage = (
            self.pipeline.get(payload["pipeline_stage_id"])
            if payload.get("pipeline_stage_id")
            else self.pipeline.default_stage()
        )
        payload["pipeline_stage_id"] = stage.id
        if payload.get("probabilita") is None:
            payload["probabilita"] = stage.probabilita_default
        payload["custom_fields"] = self._validated_custom(payload.get("custom_fields") or {})

        deal = self.repo.add(Deal(**payload))
        self.activities.record(
            ENTITY, deal.id, "created", actor, {"nome": deal.nome, "stage": stage.nome}
        )
        self.session.commit()
        return DealRead.model_validate(deal)

    def update(self, deal_id: UUID, data: DealUpdate, actor: Actor) -> DealRead:
        actor.require_write("update_deal")
        deal = self.repo.get(deal_id)
        if deal is None:
            raise NotFound(ENTITY, deal_id)

        changes = data.model_dump(exclude_none=True)
        _check_numbers(changes)
        if "custom_fields" in changes:
            merged = {**deal.custom_fields, **changes["custom_fields"]}
            changes["custom_fields"] = self._validated_custom(merged)
        for key, value in changes.items():
            setattr(deal, key, value)

        self.activities.record(ENTITY, deal.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return DealRead.model_validate(deal)

    def move_stage(self, deal_id: UUID, stage_id: UUID, actor: Actor) -> DealRead:
        actor.require_write("move_deal")
        deal = self.repo.get(deal_id)
        if deal is None:
            raise NotFound(ENTITY, deal_id)

        target = self.pipeline.get(stage_id)
        previous = self.pipeline.get(deal.pipeline_stage_id)

        deal.pipeline_stage_id = target.id
        # A terminal stage settles the probability: 'won at 60%' is not a state.
        if target.tipo == "won":
            deal.probabilita = 100
        elif target.tipo == "lost":
            deal.probabilita = 0

        self.activities.record(
            ENTITY, deal.id, "stage_changed", actor, {"from": previous.nome, "to": target.nome}
        )
        self.session.commit()
        return DealRead.model_validate(deal)

    def get(self, deal_id: UUID, actor: Actor) -> DealRead:
        deal = self.repo.get(deal_id)
        if deal is None:
            raise NotFound(ENTITY, deal_id)
        return DealRead.model_validate(deal)

    def list(self, query: DealListQuery, actor: Actor) -> DealPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return DealPage(
            items=[DealRead.model_validate(d) for d in items],
            next_cursor=items[-1].id if has_more and items else None,
        )

    def soft_delete(self, deal_id: UUID, actor: Actor) -> None:
        actor.require_write("delete_deal")
        deal = self.repo.get(deal_id)
        if deal is None:
            raise NotFound(ENTITY, deal_id)
        deal.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, deal.id, "deleted", actor)
        self.session.commit()

    def restore(self, deal_id: UUID, actor: Actor) -> DealRead:
        actor.require_write("restore_deal")
        deal = self.repo.get(deal_id, include_deleted=True)
        if deal is None:
            raise NotFound(ENTITY, deal_id)
        deal.deleted_at = None
        self.activities.record(ENTITY, deal.id, "restored", actor)
        self.session.commit()
        return DealRead.model_validate(deal)
```

`deals/__init__.py`:

```python
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.schemas import (
    DealCreate,
    DealListQuery,
    DealPage,
    DealRead,
    DealUpdate,
)
from pigrocrm.core.deals.service import DealService

__all__ = [
    "Deal",
    "DealCreate",
    "DealListQuery",
    "DealPage",
    "DealRead",
    "DealService",
    "DealUpdate",
]
```

- [ ] **Step 7: Register the model**

Append to `models_registry.py`:

```python
from pigrocrm.core.deals.models import Deal  # noqa: F401
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest packages/core/tests/test_deals.py -v`
Expected: PASS (18 passed)

- [ ] **Step 9: Run the whole core suite**

Run: `uv run pytest packages/core -v && uv run ruff check . && uv run mypy packages/core/src`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: deals with pipeline stages, terminal-stage probability and estimate fields"
```

---

### Task 13: Alembic migrations

Until now the schema existed only through `Base.metadata.create_all` in tests. Production needs
versioned migrations.

**Files:**
- Create: `packages/core/alembic.ini`, `packages/core/migrations/env.py`, `packages/core/migrations/script.py.mako`
- Create: `packages/core/migrations/versions/0001_initial_schema.py` (generated)
- Test: `packages/core/tests/test_migrations.py`

**Interfaces:**
- Consumes: every model registered in `models_registry.py` (Tasks 4, 5, 7, 9, 10, 11, 12)
- Produces: `alembic upgrade head` builds the full schema; a test proving migrations and models agree

- [ ] **Step 1: Initialise Alembic**

Run: `cd packages/core && uv run alembic init migrations && cd ../..`

- [ ] **Step 2: Point Alembic at the models**

Replace the body of `packages/core/migrations/env.py` with:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from pigrocrm.core.config import get_settings
from pigrocrm.core.db import Base
import pigrocrm.core.models_registry  # noqa: F401  (populates Base.metadata)

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Write the failing test**

`packages/core/tests/test_migrations.py`:

```python
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.command import upgrade
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine
from testcontainers.postgres import PostgresContainer

from pigrocrm.core.db import Base
import pigrocrm.core.models_registry  # noqa: F401

CORE_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(url: str) -> Config:
    config = Config(str(CORE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(CORE_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migrations_produce_exactly_the_models_schema() -> None:
    """A drift between migrations and models is invisible until deploy day, when the
    application meets a table the code does not expect."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, Base.metadata)
        engine.dispose()

    assert diff == [], f"migrations and models disagree: {diff}"


def test_every_table_the_slice_needs_exists() -> None:
    expected = {
        "users",
        "personal_access_tokens",
        "field_definitions",
        "pipeline_stages",
        "activities",
        "customers",
        "people",
        "deals",
    }
    assert expected <= set(Base.metadata.tables)
```

- [ ] **Step 4: Run it to watch it fail**

Run: `uv run pytest packages/core/tests/test_migrations.py -v`
Expected: FAIL — no revision files exist yet, so `compare_metadata` reports every table as missing.

- [ ] **Step 5: Generate the initial migration**

Start a throwaway database, generate against it, then stop it:

```bash
docker run --rm -d --name pigrocrm-migrate -e POSTGRES_PASSWORD=pigrocrm \
  -e POSTGRES_USER=pigrocrm -e POSTGRES_DB=pigrocrm -p 55432:5432 postgres:17-alpine
sleep 3
cd packages/core
PIGROCRM_DATABASE_URL="postgresql+psycopg://pigrocrm:pigrocrm@localhost:55432/pigrocrm" \
  uv run alembic revision --autogenerate -m "initial schema"
cd ../..
docker stop pigrocrm-migrate
```

- [ ] **Step 6: Rename the revision and verify the GIN indexes survived**

Rename the generated file in `packages/core/migrations/versions/` to `0001_initial_schema.py`, and
set `revision = "0001"`, `down_revision = None` inside it.

Open the file and confirm it contains three GIN index creations:

```python
op.create_index(
    "ix_customers_custom_fields", "customers", ["custom_fields"], postgresql_using="gin"
)
```

and the equivalents for `people` and `deals`. If autogenerate omitted them, add them by hand — losing
them makes every custom-field filter a sequential scan.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest packages/core/tests/test_migrations.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: Alembic migrations with a drift test between migrations and models"
```

---

# Phase 5 — HTTP adapter

### Task 14: FastAPI application, dependencies and RFC 9457 errors

**Files:**
- Create: `apps/api/src/pigrocrm_api/{main,deps,errors}.py`, `apps/api/src/pigrocrm_api/routers/{__init__,auth}.py`
- Create: `apps/api/tests/conftest.py`, `apps/api/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `UserService`, `PatService`, token helpers (Tasks 4-5); `DomainError` hierarchy (Task 3)
- Produces:
  - `create_app() -> FastAPI` and module-level `app`
  - `get_session()` — request-scoped SQLAlchemy session
  - `get_actor(request, session)` — resolves the JWT cookie, else the `Authorization: Bearer pgc_…` header; raises 401 when neither is present
  - `require_actor` alias for router use
  - `domain_error_handler` mapping `DomainError` → `application/problem+json`
  - `STATUS_BY_CODE: dict[str, int]` — `not_found`→404, `validation_failed`→422, `conflict`→409, `permission_denied`→403, `immutable_field`→409
  - Cookie names `ACCESS_COOKIE = "pigrocrm_access"`, `REFRESH_COOKIE = "pigrocrm_refresh"`
  - Endpoints `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/refresh`, `GET /api/auth/me`

- [ ] **Step 1: Write the failing test**

`apps/api/tests/conftest.py`:

```python
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm_api.deps import get_session
from pigrocrm_api.main import create_app

ADMIN_EMAIL = "admin@pigro.it"
ADMIN_PASSWORD = "supersegreta1"


@pytest.fixture(scope="session")
def api_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        settings = Settings(
            database_url=container.get_connection_url(), jwt_secret="test-secret"
        )
        get_settings.cache_clear()
        engine = create_engine_from_settings(settings)
        import pigrocrm.core.models_registry  # noqa: F401

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def api_session(api_engine: Engine) -> Iterator[Session]:
    connection = api_engine.connect()
    transaction = connection.begin()
    session = session_factory(api_engine)(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(api_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: api_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_user(api_session: Session):
    return UserService(api_session).create(
        UserCreate(email=ADMIN_EMAIL, password=ADMIN_PASSWORD, nome="Admin", ruolo="admin"),
        Actor.system(),
    )


@pytest.fixture
def logged_in(client: TestClient, admin_user) -> TestClient:
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client
```

`apps/api/tests/test_auth_api.py`:

```python
from fastapi.testclient import TestClient

from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE

CREDENTIALS = {"email": "admin@pigro.it", "password": "supersegreta1"}


def test_login_sets_httponly_cookies(client: TestClient, admin_user) -> None:
    response = client.post("/api/auth/login", json=CREDENTIALS)
    assert response.status_code == 200
    assert ACCESS_COOKIE in response.cookies
    assert REFRESH_COOKIE in response.cookies
    # The token must never be readable by JavaScript.
    assert "httponly" in response.headers["set-cookie"].lower()


def test_login_does_not_return_the_token_in_the_body(client: TestClient, admin_user) -> None:
    body = client.post("/api/auth/login", json=CREDENTIALS).json()
    assert "access_token" not in body
    assert body["email"] == "admin@pigro.it"


def test_login_with_wrong_password_is_422_with_a_problem_document(
    client: TestClient, admin_user
) -> None:
    response = client.post("/api/auth/login", json={**CREDENTIALS, "password": "sbagliata"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "validation_failed"
    assert "title" in problem and "detail" in problem


def test_me_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_current_user(logged_in: TestClient) -> None:
    body = logged_in.get("/api/auth/me").json()
    assert body["email"] == "admin@pigro.it"
    assert body["ruolo"] == "admin"


def test_logout_clears_the_cookies(logged_in: TestClient) -> None:
    assert logged_in.post("/api/auth/logout").status_code == 204
    assert logged_in.get("/api/auth/me").status_code == 401


def test_refresh_issues_a_new_access_cookie(logged_in: TestClient) -> None:
    response = logged_in.post("/api/auth/refresh")
    assert response.status_code == 200
    assert ACCESS_COOKIE in response.cookies


def test_a_personal_access_token_authenticates_too(logged_in: TestClient) -> None:
    """The same API serves the browser and the agent; only the credential differs."""
    raw = logged_in.post("/api/tokens", json={"nome": "Claude"}).json()["token"]

    bare = TestClient(logged_in.app)
    response = bare.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 200
    assert response.json()["email"] == "admin@pigro.it"


def test_an_invalid_bearer_token_is_401(client: TestClient) -> None:
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer pgc_inventato"})
    assert response.status_code == 401


def test_openapi_document_is_served(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "PigroCRM API"
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest apps/api/tests/test_auth_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm_api.main'`

- [ ] **Step 3: Write `errors.py`**

```python
from fastapi import Request
from fastapi.responses import JSONResponse

from pigrocrm.core.errors import DomainError

STATUS_BY_CODE: dict[str, int] = {
    "not_found": 404,
    "validation_failed": 422,
    "conflict": 409,
    "permission_denied": 403,
    "immutable_field": 409,
    "domain_error": 400,
}

TITLE_BY_CODE: dict[str, str] = {
    "not_found": "Risorsa non trovata",
    "validation_failed": "Dati non validi",
    "conflict": "Conflitto con lo stato attuale",
    "permission_denied": "Permesso negato",
    "immutable_field": "Campo non modificabile",
    "domain_error": "Errore di dominio",
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """RFC 9457 problem details. The structured `details` survive to the client, which
    is what lets the UI highlight the offending field instead of showing a toast."""
    assert isinstance(exc, DomainError)
    status = STATUS_BY_CODE.get(exc.code, 400)
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://pigrocrm.dev/errors/{exc.code}",
            "title": TITLE_BY_CODE.get(exc.code, "Errore"),
            "status": status,
            "detail": exc.message,
            "code": exc.code,
            "instance": str(request.url.path),
            **exc.details,
        },
    )
```

- [ ] **Step 4: Write `deps.py`**

```python
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor, Role
from pigrocrm.core.auth.pat_service import PAT_PREFIX, PatService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.tokens import decode_token
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.errors import DomainError

ACCESS_COOKIE = "pigrocrm_access"
REFRESH_COOKIE = "pigrocrm_refresh"

_engine = None
_factory = None


def get_session() -> Iterator[Session]:
    global _engine, _factory
    if _factory is None:
        _engine = create_engine_from_settings(get_settings())
        _factory = session_factory(_engine)
    session = _factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_actor(request: Request, session: SessionDep, settings: SettingsDep) -> Actor:
    """Two credentials, one actor: the browser presents a JWT cookie, an agent presents
    a PAT. Everything downstream is identical."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer ") and header[7:].startswith(PAT_PREFIX):
        try:
            return PatService(session).resolve(header[7:])
        except DomainError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token non valido") from exc

    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticazione richiesta")
    try:
        payload = decode_token(token, settings, expected_type="access")
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione scaduta") from exc

    user = UserRepository(session).get(payload.sub)
    if user is None or not user.attivo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo")

    role: Role = user.ruolo  # type: ignore[assignment]
    return Actor(id=user.id, type="user", role=role)


ActorDep = Annotated[Actor, Depends(get_actor)]
```

- [ ] **Step 5: Write `routers/auth.py`**

```python
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserRead
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.auth.tokens import decode_token, issue_access_token, issue_refresh_token
from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE, ActorDep, SessionDep, SettingsDep

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name, value, httponly=True, secure=True, samesite="lax", max_age=max_age, path="/"
    )


@router.post("/login", response_model=UserRead)
def login(
    payload: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> UserRead:
    user = UserService(session).authenticate(payload.email, payload.password)
    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings),
        settings.access_token_minutes * 60,
    )
    _set_cookie(
        response,
        REFRESH_COOKIE,
        issue_refresh_token(user.id, settings),
        settings.refresh_token_days * 86400,
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


@router.post("/refresh", response_model=UserRead)
def refresh(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> UserRead:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token assente")

    payload = decode_token(token, settings, expected_type="refresh")
    user = UserRepository(session).get(payload.sub)
    if user is None or not user.attivo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo")

    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings),
        settings.access_token_minutes * 60,
    )
    # Rotate the refresh token on every use, so a stolen one has a short life.
    _set_cookie(
        response,
        REFRESH_COOKIE,
        issue_refresh_token(user.id, settings),
        settings.refresh_token_days * 86400,
    )
    return UserRead.model_validate(user)


@router.get("/me", response_model=UserRead)
def me(actor: ActorDep, session: SessionDep) -> UserRead:
    user = UserRepository(session).get(actor.id) if actor.id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non trovato")
    return UserRead.model_validate(user)
```

- [ ] **Step 6: Write `main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pigrocrm.core.errors import DomainError
from pigrocrm_api.errors import domain_error_handler
from pigrocrm_api.routers import auth


def create_app() -> FastAPI:
    app = FastAPI(
        title="PigroCRM API",
        version="0.1.0",
        description="API pubblica di PigroCRM. La UI e il server MCP usano esclusivamente questi servizi.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(DomainError, domain_error_handler)
    app.include_router(auth.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

`routers/__init__.py` stays empty for now.

- [ ] **Step 7: Run the tests except the PAT one**

Run: `uv run pytest apps/api/tests/test_auth_api.py -v -k "not personal_access_token"`
Expected: PASS (9 passed) — the PAT test needs the tokens router from Task 15.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: FastAPI app with cookie auth, PAT bearer auth and RFC 9457 problem details"
```

---

### Task 15: Entity routers and the schema endpoint

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/{customers,people,deals,fields,pipeline,users,tokens,schema}.py`
- Create: `packages/core/src/pigrocrm/core/schema_registry.py`
- Modify: `apps/api/src/pigrocrm_api/main.py`
- Test: `apps/api/tests/test_entities_api.py`, `packages/core/tests/test_schema_registry.py`

**Interfaces:**
- Consumes: every service from Phase 4; `ActorDep`, `SessionDep` (Task 14)
- Produces:
  - the endpoint surface from spec §7, plus `POST /api/tokens` returning `{"token": "<raw>"}` exactly once
  - `pigrocrm.core.schema_registry` with `ENTITY_TYPES`, `CREATE_MODELS`, `native_fields(entity_type) -> list[str]`, `describe_entity(session, entity_type) -> dict` — **consumed by both adapters**, so `GET /api/schema/{entity}` and the MCP `describe_schema` tool return identical data by construction

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_entities_api.py`:

```python
from fastapi.testclient import TestClient


def _seed_pipeline(logged_in: TestClient) -> None:
    assert logged_in.post("/api/pipeline-stages/seed").status_code == 200


def test_full_customer_lifecycle_over_http(logged_in: TestClient) -> None:
    created = logged_in.post("/api/customers", json={"ragione_sociale": "ACME Srl"})
    assert created.status_code == 201
    customer_id = created.json()["id"]

    assert logged_in.get(f"/api/customers/{customer_id}").json()["ragione_sociale"] == "ACME Srl"

    updated = logged_in.patch(f"/api/customers/{customer_id}", json={"telefono": "0212345"})
    assert updated.json()["telefono"] == "0212345"

    assert logged_in.delete(f"/api/customers/{customer_id}").status_code == 204
    assert logged_in.get(f"/api/customers/{customer_id}").status_code == 404


def test_missing_customer_returns_a_problem_document(logged_in: TestClient) -> None:
    from uuid import uuid4

    response = logged_in.get(f"/api/customers/{uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"


def test_a_custom_field_defined_over_http_is_immediately_usable(logged_in: TestClient) -> None:
    """This is the whole point of dynamic fields: define it, then use it, with no deploy."""
    definition = logged_in.post(
        "/api/field-definitions",
        json={
            "entity_type": "customer",
            "key": "settore",
            "label": "Settore",
            "field_type": "select",
            "options": ["IT", "Retail"],
        },
    )
    assert definition.status_code == 201

    ok = logged_in.post(
        "/api/customers", json={"ragione_sociale": "Beta", "custom_fields": {"settore": "IT"}}
    )
    assert ok.status_code == 201
    assert ok.json()["custom_fields"] == {"settore": "IT"}

    bad = logged_in.post(
        "/api/customers", json={"ragione_sociale": "Gamma", "custom_fields": {"settore": "Altro"}}
    )
    assert bad.status_code == 422
    assert "IT" in bad.json()["expected"]


def test_schema_endpoint_describes_the_current_shape(logged_in: TestClient) -> None:
    logged_in.post(
        "/api/field-definitions",
        json={
            "entity_type": "customer",
            "key": "settore",
            "label": "Settore",
            "field_type": "text",
        },
    )
    body = logged_in.get("/api/schema/customer").json()

    assert body["entity_type"] == "customer"
    assert any(f["key"] == "settore" for f in body["custom_fields"])
    assert "ragione_sociale" in body["native_fields"]


def test_deal_lifecycle_including_the_kanban_move(logged_in: TestClient) -> None:
    _seed_pipeline(logged_in)
    stages = logged_in.get("/api/pipeline-stages").json()
    offerta = next(s for s in stages if s["nome"] == "Offerta")

    customer_id = logged_in.post("/api/customers", json={"ragione_sociale": "ACME"}).json()["id"]
    deal = logged_in.post(
        "/api/deals", json={"nome": "Progetto X", "customer_id": customer_id}
    ).json()

    moved = logged_in.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": offerta["id"]})
    assert moved.status_code == 200
    assert moved.json()["pipeline_stage_id"] == offerta["id"]


def test_timeline_endpoint_reports_what_happened(logged_in: TestClient) -> None:
    customer_id = logged_in.post("/api/customers", json={"ragione_sociale": "ACME"}).json()["id"]
    logged_in.patch(f"/api/customers/{customer_id}", json={"telefono": "02"})

    timeline = logged_in.get(f"/api/customers/{customer_id}/timeline").json()
    assert {entry["kind"] for entry in timeline} == {"created", "updated"}
    assert all(entry["actor_type"] == "user" for entry in timeline)


def test_deleting_a_customer_with_deals_is_409_and_says_how_many(logged_in: TestClient) -> None:
    _seed_pipeline(logged_in)
    customer_id = logged_in.post("/api/customers", json={"ragione_sociale": "ACME"}).json()["id"]
    logged_in.post("/api/deals", json={"nome": "X", "customer_id": customer_id})

    response = logged_in.delete(f"/api/customers/{customer_id}")
    assert response.status_code == 409
    assert response.json()["active_deals"] == 1


def test_list_supports_search_and_pagination(logged_in: TestClient) -> None:
    for index in range(3):
        logged_in.post("/api/customers", json={"ragione_sociale": f"Cliente {index}"})

    page = logged_in.get("/api/customers", params={"limit": 2}).json()
    assert len(page["items"]) == 2
    assert page["next_cursor"] is not None

    found = logged_in.get("/api/customers", params={"search": "Cliente 1"}).json()
    assert len(found["items"]) == 1


def test_a_pat_is_shown_once_and_then_only_by_prefix(logged_in: TestClient) -> None:
    created = logged_in.post("/api/tokens", json={"nome": "Claude"}).json()
    assert created["token"].startswith("pgc_")

    listed = logged_in.get("/api/tokens").json()
    assert listed[0]["prefix"] == created["token"][:12]
    assert all("token" not in entry for entry in listed)


def test_a_person_can_be_created_without_a_customer(logged_in: TestClient) -> None:
    response = logged_in.post("/api/people", json={"nome": "Mario"})
    assert response.status_code == 201
    assert response.json()["customer_id"] is None
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest apps/api/tests/test_entities_api.py -v`
Expected: FAIL — 404 on every endpoint, since no routers are registered.

- [ ] **Step 3: Write `routers/customers.py`**

```python
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.customers.schemas import (
    CustomerCreate,
    CustomerListQuery,
    CustomerPage,
    CustomerRead,
    CustomerUpdate,
)
from pigrocrm.core.customers.service import CustomerService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create(data: CustomerCreate, session: SessionDep, actor: ActorDep) -> CustomerRead:
    return CustomerService(session).create(data, actor)


@router.get("", response_model=CustomerPage)
def list_customers(
    session: SessionDep,
    actor: ActorDep,
    search: Annotated[str | None, Query()] = None,
    stato: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> CustomerPage:
    query = CustomerListQuery(search=search, stato=stato, limit=limit, cursor=cursor)
    return CustomerService(session).list(query, actor)


@router.get("/{customer_id}", response_model=CustomerRead)
def get(customer_id: UUID, session: SessionDep, actor: ActorDep) -> CustomerRead:
    return CustomerService(session).get(customer_id, actor)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update(
    customer_id: UUID, data: CustomerUpdate, session: SessionDep, actor: ActorDep
) -> CustomerRead:
    return CustomerService(session).update(customer_id, data, actor)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(customer_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    """Sets deleted_at. Nothing in this slice removes a row."""
    CustomerService(session).soft_delete(customer_id, actor)


@router.post("/{customer_id}/restore", response_model=CustomerRead)
def restore(customer_id: UUID, session: SessionDep, actor: ActorDep) -> CustomerRead:
    return CustomerService(session).restore(customer_id, actor)


@router.get("/{customer_id}/timeline", response_model=list[ActivityRead])
def timeline(customer_id: UUID, session: SessionDep, actor: ActorDep) -> list[ActivityRead]:
    return ActivityService(session).timeline("customer", customer_id)
```

- [ ] **Step 4: Write `routers/people.py`**

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.people.schemas import (
    PersonCreate,
    PersonListQuery,
    PersonPage,
    PersonRead,
    PersonUpdate,
)
from pigrocrm.core.people.service import PersonService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/people", tags=["people"])


@router.post("", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
def create(data: PersonCreate, session: SessionDep, actor: ActorDep) -> PersonRead:
    return PersonService(session).create(data, actor)


@router.get("", response_model=PersonPage)
def list_people(
    session: SessionDep,
    actor: ActorDep,
    search: Annotated[str | None, Query()] = None,
    customer_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> PersonPage:
    query = PersonListQuery(search=search, customer_id=customer_id, limit=limit, cursor=cursor)
    return PersonService(session).list(query, actor)


@router.get("/{person_id}", response_model=PersonRead)
def get(person_id: UUID, session: SessionDep, actor: ActorDep) -> PersonRead:
    return PersonService(session).get(person_id, actor)


@router.patch("/{person_id}", response_model=PersonRead)
def update(
    person_id: UUID, data: PersonUpdate, session: SessionDep, actor: ActorDep
) -> PersonRead:
    return PersonService(session).update(person_id, data, actor)


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(person_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    PersonService(session).soft_delete(person_id, actor)


@router.post("/{person_id}/restore", response_model=PersonRead)
def restore(person_id: UUID, session: SessionDep, actor: ActorDep) -> PersonRead:
    return PersonService(session).restore(person_id, actor)


@router.get("/{person_id}/timeline", response_model=list[ActivityRead])
def timeline(person_id: UUID, session: SessionDep, actor: ActorDep) -> list[ActivityRead]:
    return ActivityService(session).timeline("person", person_id)
```

- [ ] **Step 5: Write `routers/deals.py`**

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.deals.schemas import (
    DealCreate,
    DealListQuery,
    DealPage,
    DealRead,
    DealUpdate,
)
from pigrocrm.core.deals.service import DealService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/deals", tags=["deals"])


class MoveStageRequest(BaseModel):
    stage_id: UUID


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
def create(data: DealCreate, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).create(data, actor)


@router.get("", response_model=DealPage)
def list_deals(
    session: SessionDep,
    actor: ActorDep,
    search: Annotated[str | None, Query()] = None,
    customer_id: Annotated[UUID | None, Query()] = None,
    stage_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> DealPage:
    query = DealListQuery(
        search=search, customer_id=customer_id, stage_id=stage_id, limit=limit, cursor=cursor
    )
    return DealService(session).list(query, actor)


@router.get("/{deal_id}", response_model=DealRead)
def get(deal_id: UUID, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).get(deal_id, actor)


@router.patch("/{deal_id}", response_model=DealRead)
def update(deal_id: UUID, data: DealUpdate, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).update(deal_id, data, actor)


@router.patch("/{deal_id}/stage", response_model=DealRead)
def move_stage(
    deal_id: UUID, data: MoveStageRequest, session: SessionDep, actor: ActorDep
) -> DealRead:
    """Backs the Kanban drag. Optimistic on the client, authoritative here."""
    return DealService(session).move_stage(deal_id, data.stage_id, actor)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(deal_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    DealService(session).soft_delete(deal_id, actor)


@router.post("/{deal_id}/restore", response_model=DealRead)
def restore(deal_id: UUID, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).restore(deal_id, actor)


@router.get("/{deal_id}/timeline", response_model=list[ActivityRead])
def timeline(deal_id: UUID, session: SessionDep, actor: ActorDep) -> list[ActivityRead]:
    return ActivityService(session).timeline("deal", deal_id)
```

- [ ] **Step 6: Write `routers/fields.py`, `routers/pipeline.py`, `routers/users.py`, `routers/tokens.py`**

`routers/fields.py`:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.fields.schemas import (
    EntityType,
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
)
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/field-definitions", tags=["fields"])


@router.post("", response_model=FieldDefinitionRead, status_code=status.HTTP_201_CREATED)
def create(
    data: FieldDefinitionCreate, session: SessionDep, actor: ActorDep
) -> FieldDefinitionRead:
    return FieldDefinitionService(session).create(data, actor)


@router.get("", response_model=list[FieldDefinitionRead])
def list_fields(
    session: SessionDep,
    actor: ActorDep,
    entity_type: Annotated[EntityType, Query()],
    include_archived: Annotated[bool, Query()] = False,
) -> list[FieldDefinitionRead]:
    return FieldDefinitionService(session).list(entity_type, include_archived=include_archived)


@router.patch("/{field_id}", response_model=FieldDefinitionRead)
def update(
    field_id: UUID, data: FieldDefinitionUpdate, session: SessionDep, actor: ActorDep
) -> FieldDefinitionRead:
    return FieldDefinitionService(session).update(field_id, data, actor)


@router.post("/{field_id}/archive", response_model=FieldDefinitionRead)
def archive(field_id: UUID, session: SessionDep, actor: ActorDep) -> FieldDefinitionRead:
    """Archive, never delete: rows still hold the value in JSONB."""
    return FieldDefinitionService(session).archive(field_id, actor)
```

`routers/pipeline.py`:

```python
from uuid import UUID

from fastapi import APIRouter, status

from pigrocrm.core.pipeline.schemas import (
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
)
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/pipeline-stages", tags=["pipeline"])


@router.post("", response_model=PipelineStageRead, status_code=status.HTTP_201_CREATED)
def create(data: PipelineStageCreate, session: SessionDep, actor: ActorDep) -> PipelineStageRead:
    return PipelineService(session).create(data, actor)


@router.get("", response_model=list[PipelineStageRead])
def list_stages(session: SessionDep, actor: ActorDep) -> list[PipelineStageRead]:
    return PipelineService(session).list()


@router.patch("/{stage_id}", response_model=PipelineStageRead)
def update(
    stage_id: UUID, data: PipelineStageUpdate, session: SessionDep, actor: ActorDep
) -> PipelineStageRead:
    return PipelineService(session).update(stage_id, data, actor)


@router.post("/seed", response_model=list[PipelineStageRead])
def seed(session: SessionDep, actor: ActorDep) -> list[PipelineStageRead]:
    actor.require_admin("seed_pipeline")
    return PipelineService(session).seed_defaults()
```

`routers/users.py`:

```python
from uuid import UUID

from fastapi import APIRouter, status

from pigrocrm.core.auth.schemas import UserCreate, UserRead, UserUpdate
from pigrocrm.core.auth.service import UserService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create(data: UserCreate, session: SessionDep, actor: ActorDep) -> UserRead:
    return UserService(session).create(data, actor)


@router.get("", response_model=list[UserRead])
def list_users(session: SessionDep, actor: ActorDep) -> list[UserRead]:
    return UserService(session).list(actor)


@router.patch("/{user_id}", response_model=UserRead)
def update(user_id: UUID, data: UserUpdate, session: SessionDep, actor: ActorDep) -> UserRead:
    return UserService(session).update(user_id, data, actor)
```

`routers/tokens.py`:

```python
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel

from pigrocrm.core.auth.pat_service import PatRead, PatService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


class CreateTokenRequest(BaseModel):
    nome: str


class CreatedToken(PatRead):
    """The only response in the whole API that carries the raw token. It is shown
    once, at creation, and never again."""

    token: str


@router.post("", response_model=CreatedToken, status_code=status.HTTP_201_CREATED)
def create(data: CreateTokenRequest, session: SessionDep, actor: ActorDep) -> CreatedToken:
    record, raw = PatService(session).create(data.nome, actor)
    return CreatedToken(**record.model_dump(), token=raw)


@router.get("", response_model=list[PatRead])
def list_tokens(session: SessionDep, actor: ActorDep) -> list[PatRead]:
    return PatService(session).list(actor)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(token_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    PatService(session).revoke(token_id, actor)
```

- [ ] **Step 7: Write the shared schema description in core**

Both adapters must describe an entity identically — that is the whole point of
`describe_schema`. So the description is computed once, in core, and imported by both.
A hand-maintained field list in either adapter would be a second source of truth that
drifts silently the first time a column is added.

`packages/core/src/pigrocrm/core/schema_registry.py`:

```python
"""One description of an entity's shape, for every adapter.

Lives in core rather than in an adapter because both the REST API and the MCP
server must answer "what fields does a customer have?" with the same answer.
Nothing in core imports this module, so pulling in the entity schemas here
creates no cycle.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from pigrocrm.core.customers.schemas import CustomerCreate
from pigrocrm.core.deals.schemas import DealCreate
from pigrocrm.core.fields.dynamic import describe_specs
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.people.schemas import PersonCreate

ENTITY_TYPES: tuple[EntityType, ...] = ("customer", "person", "deal")

CREATE_MODELS: dict[str, type[BaseModel]] = {
    "customer": CustomerCreate,
    "person": PersonCreate,
    "deal": DealCreate,
}


def native_fields(entity_type: str) -> list[str]:
    """Derived from the Pydantic model, never hand-listed."""
    return [name for name in CREATE_MODELS[entity_type].model_fields if name != "custom_fields"]


def describe_entity(session: Session, entity_type: EntityType) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "native_fields": native_fields(entity_type),
        "custom_fields": describe_specs(FieldDefinitionService(session).specs_for(entity_type)),
    }
```

Add a test at `packages/core/tests/test_schema_registry.py`:

```python
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.schema_registry import ENTITY_TYPES, describe_entity, native_fields

ADMIN = Actor(id=None, type="system", role="admin")


def test_native_fields_come_from_the_model_not_a_hand_written_list() -> None:
    fields = native_fields("customer")
    assert "ragione_sociale" in fields
    assert "partita_iva" in fields
    assert "custom_fields" not in fields, "custom fields are described separately"


def test_every_entity_type_can_be_described(db_session: Session) -> None:
    for entity_type in ENTITY_TYPES:
        described = describe_entity(db_session, entity_type)
        assert described["entity_type"] == entity_type
        assert described["native_fields"]


def test_a_new_custom_field_shows_up_immediately(db_session: Session) -> None:
    FieldDefinitionService(db_session).create(
        FieldDefinitionCreate(
            entity_type="deal", key="rischio", label="Rischio", field_type="text"
        ),
        ADMIN,
    )
    described = describe_entity(db_session, "deal")
    assert [field["key"] for field in described["custom_fields"]] == ["rischio"]
```

Run: `uv run pytest packages/core/tests/test_schema_registry.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Write `routers/schema.py`**

```python
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.schema_registry import describe_entity
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/schema", tags=["schema"])


class EntitySchema(BaseModel):
    entity_type: str
    native_fields: list[str]
    custom_fields: list[dict[str, Any]]


@router.get("/{entity_type}", response_model=EntitySchema)
def describe(entity_type: EntityType, session: SessionDep, actor: ActorDep) -> EntitySchema:
    """The same information the MCP `describe_schema` tool returns — literally the same
    function — so the UI and an agent can never disagree about what fields exist."""
    return EntitySchema(**describe_entity(session, entity_type))
```

- [ ] **Step 9: Register every router in `main.py`**

Replace the import and the `include_router` call in `create_app()`:

```python
from pigrocrm_api.routers import (
    auth,
    customers,
    deals,
    fields,
    people,
    pipeline,
    schema,
    tokens,
    users,
)

...

    for module in (auth, customers, people, deals, fields, pipeline, users, tokens, schema):
        app.include_router(module.router)
```

- [ ] **Step 10: Run the full API suite and the core suite**

Run: `uv run pytest apps/api packages/core/tests/test_schema_registry.py -v`
Expected: PASS — the 10 auth tests including the PAT one, 11 entity tests, 3 schema-registry tests.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: REST routers plus the shared entity-schema description in core"
```

---

# Phase 6 — MCP adapter

### Task 16: MCP server, dynamic schema and resources

**Files:**
- Create: `apps/mcp/src/pigrocrm_mcp/{server,context,errors}.py`, `apps/mcp/src/pigrocrm_mcp/tools/{__init__,schema}.py`, `apps/mcp/src/pigrocrm_mcp/resources/entities.py`
- Create: `apps/mcp/tests/conftest.py`, `apps/mcp/tests/test_mcp_schema.py`

**Interfaces:**
- Consumes: `FieldDefinitionService`, `describe_specs`, `build_custom_fields_model` (Tasks 7-8); `PatService` (Task 5); services from Phase 4
- Produces:
  - `build_server(session_provider, actor_provider) -> MCPServer` — injectable, so tests need no subprocess
  - `to_agent_message(exc: DomainError) -> str` — LLM-actionable rendering
  - `describe_schema(entity_type)` tool
  - `refresh_schema()` tool re-registering dynamic tools and emitting `send_tool_list_changed()`
  - resources `customer://{id}`, `person://{id}`, `deal://{id}` returning Markdown

- [ ] **Step 1: Write the failing test**

`apps/mcp/tests/conftest.py`:

```python
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm_mcp.server import build_server

ADMIN = Actor(id=None, type="mcp", role="admin")


@pytest.fixture(scope="session")
def mcp_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        engine = create_engine_from_settings(
            Settings(database_url=container.get_connection_url())
        )
        import pigrocrm.core.models_registry  # noqa: F401

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def mcp_session(mcp_engine: Engine) -> Iterator[Session]:
    connection = mcp_engine.connect()
    transaction = connection.begin()
    session = session_factory(mcp_engine)(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def server(mcp_session: Session):
    return build_server(lambda: mcp_session, lambda: ADMIN)
```

`apps/mcp/tests/test_mcp_schema.py`:

```python
import json

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService

ADMIN = Actor(id=None, type="mcp", role="admin")


def _payload(result) -> dict:
    return result.structured_content or json.loads(result.content[0].text)


async def test_describe_schema_lists_native_and_custom_fields(server, mcp_session: Session) -> None:
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer", key="settore", label="Settore", field_type="text"
        ),
        ADMIN,
    )
    async with Client(server) as client:
        result = await client.call_tool("describe_schema", {"entity_type": "customer"})

    body = _payload(result)
    assert "ragione_sociale" in body["native_fields"]
    assert any(field["key"] == "settore" for field in body["custom_fields"])


async def test_describe_schema_reads_live_so_a_new_field_appears_at_once(
    server, mcp_session: Session
) -> None:
    """Tool schemas are fixed at registration, so describe_schema must not be. This is
    how an agent notices a field added from the web app while the server was running."""
    async with Client(server) as client:
        before = _payload(await client.call_tool("describe_schema", {"entity_type": "deal"}))
        assert before["custom_fields"] == []

        FieldDefinitionService(mcp_session).create(
            FieldDefinitionCreate(
                entity_type="deal", key="rischio", label="Rischio", field_type="text"
            ),
            ADMIN,
        )
        after = _payload(await client.call_tool("describe_schema", {"entity_type": "deal"}))

    assert [f["key"] for f in after["custom_fields"]] == ["rischio"]


async def test_the_tool_list_is_advertised(server) -> None:
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert {"describe_schema", "refresh_schema"} <= names


async def test_refresh_schema_reports_what_it_rebuilt(server, mcp_session: Session) -> None:
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer", key="settore", label="Settore", field_type="text"
        ),
        ADMIN,
    )
    async with Client(server) as client:
        body = _payload(await client.call_tool("refresh_schema", {}))
    assert body["customer"] == 1


async def test_customer_resource_returns_readable_markdown(server, mcp_session: Session) -> None:
    """Resources exist so an agent can read before it acts."""
    from pigrocrm.core.customers.schemas import CustomerCreate
    from pigrocrm.core.customers.service import CustomerService

    customer = CustomerService(mcp_session).create(
        CustomerCreate(ragione_sociale="ACME Srl", partita_iva="12345678901"), ADMIN
    )
    async with Client(server) as client:
        result = await client.read_resource(f"customer://{customer.id}")

    text = result.contents[0].text
    assert "ACME Srl" in text
    assert "12345678901" in text
    assert "## Timeline" in text


async def test_an_unknown_resource_id_explains_itself(server) -> None:
    from uuid import uuid4

    async with Client(server) as client:
        with pytest.raises(Exception) as exc:
            await client.read_resource(f"customer://{uuid4()}")
    assert "non trovato" in str(exc.value).lower() or "not found" in str(exc.value).lower()
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest apps/mcp -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm_mcp.server'`

- [ ] **Step 3: Write `errors.py`**

```python
from pigrocrm.core.errors import DomainError

HINT_BY_CODE: dict[str, str] = {
    "not_found": "Verifica l'identificativo, oppure cerca l'entità con lo strumento di ricerca.",
    "validation_failed": "Correggi il valore indicato e riprova.",
    "conflict": "Lo stato attuale impedisce l'operazione: risolvi il conflitto descritto e riprova.",
    "permission_denied": "Servono permessi diversi: chiedi all'utente di procedere manualmente.",
    "immutable_field": "Questo campo non è modificabile: archivia e ricrea invece di aggiornare.",
}


def to_agent_message(exc: DomainError) -> str:
    """A numeric status makes a model retry at random; a diagnosis makes it stop or fix.

    So the MCP rendering states what failed, what was expected, and what to do next —
    the same structured details the API renders as a problem document.
    """
    lines = [exc.message]

    expected = exc.details.get("expected")
    if expected:
        lines.append(f"Valore atteso: {expected}.")

    if exc.code == "permission_denied":
        required = ", ".join(exc.details.get("required_roles", []))
        actual = exc.details.get("actual_role", "sconosciuto")
        lines.append(f"Ruolo attuale: {actual}. Ruoli sufficienti: {required}.")

    extras = {
        key: value
        for key, value in exc.details.items()
        if key not in {"expected", "required_roles", "actual_role", "entity", "field", "reason"}
    }
    if extras:
        lines.append("Contesto: " + ", ".join(f"{k}={v}" for k, v in sorted(extras.items())))

    lines.append(HINT_BY_CODE.get(exc.code, "Rivedi i parametri e riprova."))
    return " ".join(lines)
```

- [ ] **Step 4: Write `context.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor

SessionProvider = Callable[[], Session]
ActorProvider = Callable[[], Actor]


@dataclass(frozen=True)
class McpContext:
    """Injected rather than imported, so tests drive the server in-process with a
    rolled-back transaction instead of spawning a subprocess."""

    session_provider: SessionProvider
    actor_provider: ActorProvider

    @property
    def session(self) -> Session:
        return self.session_provider()

    @property
    def actor(self) -> Actor:
        return self.actor_provider()
```

- [ ] **Step 5: Write `resources/entities.py`**

```python
from uuid import UUID

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.people.schemas import PersonListQuery
from pigrocrm.core.people.service import PersonService
from pigrocrm_mcp.context import McpContext


def _timeline_lines(context: McpContext, entity: str, entity_id: UUID) -> list[str]:
    entries = ActivityService(context.session).timeline(entity, entity_id, limit=10)
    if not entries:
        return ["_Nessuna attività registrata._"]
    return [
        f"- {e.occurred_at:%Y-%m-%d %H:%M} · **{e.kind}** · da {e.actor_type}" for e in entries
    ]


def _custom_lines(custom_fields: dict[str, object]) -> list[str]:
    if not custom_fields:
        return []
    return ["", "## Campi personalizzati", ""] + [
        f"- **{key}**: {value}" for key, value in sorted(custom_fields.items())
    ]


def render_customer(context: McpContext, customer_id: UUID) -> str:
    customer = CustomerService(context.session).get(customer_id, context.actor)
    people = PersonService(context.session).list(
        PersonListQuery(customer_id=customer_id, limit=50), context.actor
    )
    from pigrocrm.core.deals.schemas import DealListQuery

    deals = DealService(context.session).list(
        DealListQuery(customer_id=customer_id, limit=50), context.actor
    )

    lines = [
        f"# {customer.ragione_sociale}",
        "",
        "## Dati fiscali",
        "",
        f"- P.IVA: {customer.partita_iva or '—'}",
        f"- Codice fiscale: {customer.codice_fiscale or '—'}",
        f"- Codice SDI: {customer.codice_sdi or '—'}",
        f"- PEC: {customer.pec or '—'}",
        f"- Indirizzo: {customer.indirizzo or '—'}, {customer.cap or ''} "
        f"{customer.comune or ''} ({customer.provincia or ''}) {customer.nazione}",
        "",
        "## Contatti",
        "",
    ]
    lines += [f"- {p.nome} {p.cognome or ''} — {p.ruolo or 'ruolo non indicato'} — {p.email or '—'}"
              for p in people.items] or ["_Nessun contatto._"]
    lines += ["", "## Deal", ""]
    lines += [f"- {d.nome} — valore previsto {d.valore_previsto or '—'} — probabilità {d.probabilita}%"
              for d in deals.items] or ["_Nessun deal._"]
    lines += _custom_lines(customer.custom_fields)
    lines += ["", "## Timeline", ""] + _timeline_lines(context, "customer", customer_id)
    if customer.note:
        lines += ["", "## Note", "", customer.note]
    return "\n".join(lines)


def render_person(context: McpContext, person_id: UUID) -> str:
    person = PersonService(context.session).get(person_id, context.actor)
    lines = [
        f"# {person.nome} {person.cognome or ''}".strip(),
        "",
        f"- Ruolo: {person.ruolo or '—'}",
        f"- Email: {person.email or '—'}",
        f"- Telefono: {person.telefono or '—'}",
        f"- LinkedIn: {person.linkedin or '—'}",
    ]
    if person.customer_id:
        customer = CustomerService(context.session).get(person.customer_id, context.actor)
        lines.append(f"- Cliente: {customer.ragione_sociale} (`customer://{customer.id}`)")
    else:
        lines.append("- Cliente: non associato")
    lines += _custom_lines(person.custom_fields)
    lines += ["", "## Timeline", ""] + _timeline_lines(context, "person", person_id)
    if person.note:
        lines += ["", "## Note", "", person.note]
    return "\n".join(lines)


def render_deal(context: McpContext, deal_id: UUID) -> str:
    deal = DealService(context.session).get(deal_id, context.actor)
    customer = CustomerService(context.session).get(deal.customer_id, context.actor)

    from pigrocrm.core.pipeline.service import PipelineService

    stage = PipelineService(context.session).get(deal.pipeline_stage_id)

    lines = [
        f"# {deal.nome}",
        "",
        f"- Cliente: {customer.ragione_sociale} (`customer://{customer.id}`)",
        f"- Stato: {stage.nome} ({stage.tipo})",
        f"- Valore previsto: {deal.valore_previsto or '—'}",
        f"- Probabilità: {deal.probabilita}%",
        f"- Chiusura prevista: {deal.data_chiusura_prevista or '—'}",
        f"- Ore preventivate: {deal.ore_preventivate or '—'}",
        f"- Valore preventivato: {deal.valore_preventivato or '—'}",
    ]
    lines += _custom_lines(deal.custom_fields)
    lines += ["", "## Timeline", ""] + _timeline_lines(context, "deal", deal_id)
    if deal.note:
        lines += ["", "## Note", "", deal.note]
    return "\n".join(lines)
```

- [ ] **Step 6: Write `tools/schema.py`**

Thin by design: the description itself lives in `pigrocrm.core.schema_registry` (Task 15),
so this adapter and the REST router return literally the same data.

```python
from typing import Any

from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.schema_registry import ENTITY_TYPES, describe_entity
from pigrocrm_mcp.context import McpContext

__all__ = ["ENTITY_TYPES", "entity_schema"]


def entity_schema(context: McpContext, entity_type: EntityType) -> dict[str, Any]:
    return describe_entity(context.session, entity_type)
```

- [ ] **Step 7: Write `server.py`**

```python
from typing import Any, Literal
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from pigrocrm.core.errors import DomainError
from pigrocrm_mcp.context import ActorProvider, McpContext, SessionProvider
from pigrocrm_mcp.errors import to_agent_message
from pigrocrm_mcp.resources import entities
from pigrocrm_mcp.tools.schema import ENTITY_TYPES, entity_schema

EntityType = Literal["customer", "person", "deal"]

INSTRUCTIONS = """PigroCRM — CRM per freelancer e piccole startup italiane.

Prima di creare o aggiornare un'entità, chiama `describe_schema` per conoscere i campi
personalizzati definiti dall'utente: non sono codificati negli strumenti e cambiano nel tempo.
Per leggere il contesto completo usa le risorse `customer://`, `person://` e `deal://`.
Nulla viene cancellato fisicamente: le operazioni di archiviazione sono reversibili.
"""


def _guard(fn):
    """Every tool renders domain errors as guidance instead of leaking a stack trace."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DomainError as exc:
            raise ValueError(to_agent_message(exc)) from exc

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def build_server(
    session_provider: SessionProvider, actor_provider: ActorProvider
) -> MCPServer:
    context = McpContext(session_provider, actor_provider)
    mcp = MCPServer("PigroCRM", instructions=INSTRUCTIONS)

    @mcp.tool()
    @_guard
    def describe_schema(entity_type: EntityType) -> dict[str, Any]:
        """Campi nativi e personalizzati attualmente definiti per un'entità.

        Legge dal database a ogni chiamata: usalo prima di creare o aggiornare.
        """
        return entity_schema(context, entity_type)

    @mcp.tool()
    async def refresh_schema(ctx: Context) -> dict[str, int]:
        """Ricarica i campi personalizzati e aggiorna la lista degli strumenti.

        Serve quando un campo è stato aggiunto dalla web app mentre questo server
        era già avviato: gli schemi degli strumenti sono fissati alla registrazione.
        """
        counts = {
            entity: len(entity_schema(context, entity)["custom_fields"])
            for entity in ENTITY_TYPES
        }
        await ctx.session.send_tool_list_changed()
        return counts

    @mcp.resource("customer://{customer_id}")
    @_guard
    def customer_resource(customer_id: str) -> str:
        """Scheda completa di un cliente: dati fiscali, contatti, deal e timeline."""
        return entities.render_customer(context, UUID(customer_id))

    @mcp.resource("person://{person_id}")
    @_guard
    def person_resource(person_id: str) -> str:
        """Scheda completa di una persona."""
        return entities.render_person(context, UUID(person_id))

    @mcp.resource("deal://{deal_id}")
    @_guard
    def deal_resource(deal_id: str) -> str:
        """Scheda completa di un deal, incluso stato di pipeline e timeline."""
        return entities.render_deal(context, UUID(deal_id))

    from pigrocrm_mcp.tools import register_entity_tools

    register_entity_tools(mcp, context, _guard)
    return mcp
```

- [ ] **Step 8: Write a temporary `tools/__init__.py`**

Task 17 fills this in. For now it must exist so `server.py` imports cleanly:

```python
from typing import Any, Callable

from mcp.server import MCPServer

from pigrocrm_mcp.context import McpContext


def register_entity_tools(
    mcp: MCPServer, context: McpContext, guard: Callable[..., Any]
) -> None:
    """Filled in by Task 17."""
    return None
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest apps/mcp -v`
Expected: PASS (6 passed)

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: MCP server with live schema discovery, Markdown resources and agent-readable errors"
```

---

### Task 17: MCP entity tools and the end-to-end proof

**Files:**
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`
- Create: `apps/mcp/src/pigrocrm_mcp/tools/{customers,people,deals}.py`, `apps/mcp/src/pigrocrm_mcp/__main__.py`
- Test: `apps/mcp/tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: everything from Task 16 and Phase 4
- Produces: the tool surface of spec §8.3, and a stdio entry point `python -m pigrocrm_mcp`

- [ ] **Step 1: Write the failing test**

`apps/mcp/tests/test_mcp_tools.py`:

```python
import json

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=None, type="mcp", role="admin")


def _payload(result) -> dict:
    return result.structured_content or json.loads(result.content[0].text)


async def test_every_tool_from_the_spec_is_exposed(server) -> None:
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert {
        "describe_schema", "refresh_schema",
        "create_customer", "update_customer", "get_customer", "search_customers",
        "archive_customer",
        "create_person", "update_person", "get_person", "search_people", "archive_person",
        "create_deal", "update_deal", "get_deal", "search_deals", "move_deal", "archive_deal",
        "list_pipeline_stages", "get_timeline",
    } <= names


async def test_no_destructive_delete_tool_exists(server) -> None:
    """An agent misreading 'elimina i deal chiusi' must not be able to destroy rows."""
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert not [name for name in names if name.startswith("delete_")]


async def test_the_full_journey_an_agent_would_take(server, mcp_session: Session) -> None:
    """Spec success criterion 2: Claude does the whole job through MCP, discovering a
    custom field nobody hardcoded."""
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer",
            key="settore",
            label="Settore",
            field_type="select",
            options=["IT", "Retail"],
        ),
        ADMIN,
    )
    PipelineService(mcp_session).seed_defaults()

    async with Client(server) as client:
        schema = _payload(await client.call_tool("describe_schema", {"entity_type": "customer"}))
        assert [f["key"] for f in schema["custom_fields"]] == ["settore"]

        customer = _payload(
            await client.call_tool(
                "create_customer",
                {
                    "ragione_sociale": "ACME Srl",
                    "partita_iva": "12345678901",
                    "custom_fields": {"settore": "IT"},
                },
            )
        )
        assert customer["custom_fields"] == {"settore": "IT"}

        person = _payload(
            await client.call_tool(
                "create_person",
                {"nome": "Mario", "cognome": "Rossi", "customer_id": customer["id"]},
            )
        )
        assert person["customer_id"] == customer["id"]

        deal = _payload(
            await client.call_tool(
                "create_deal", {"nome": "Progetto X", "customer_id": customer["id"]}
            )
        )

        stages = _payload(await client.call_tool("list_pipeline_stages", {}))["stages"]
        offerta = next(s for s in stages if s["nome"] == "Offerta")
        moved = _payload(
            await client.call_tool(
                "move_deal", {"deal_id": deal["id"], "stage_id": offerta["id"]}
            )
        )
        assert moved["pipeline_stage_id"] == offerta["id"]

        timeline = _payload(
            await client.call_tool(
                "get_timeline", {"entity_type": "deal", "entity_id": deal["id"]}
            )
        )["entries"]

    # Criterion 3: the timeline distinguishes the agent from a human.
    assert {entry["actor_type"] for entry in timeline} == {"mcp"}
    assert "stage_changed" in {entry["kind"] for entry in timeline}


async def test_an_invalid_custom_value_returns_guidance_naming_the_options(
    server, mcp_session: Session
) -> None:
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer",
            key="settore",
            label="Settore",
            field_type="select",
            options=["IT", "Retail"],
        ),
        ADMIN,
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "create_customer",
            {"ragione_sociale": "Beta", "custom_fields": {"settore": "Altro"}},
        )

    assert result.is_error
    message = result.content[0].text
    assert "IT" in message and "Retail" in message
    assert "Valore atteso" in message


async def test_a_permission_error_tells_the_agent_to_ask_the_user(mcp_session: Session) -> None:
    from pigrocrm_mcp.server import build_server

    readonly = Actor(id=None, type="mcp", role="readonly")
    server = build_server(lambda: mcp_session, lambda: readonly)

    async with Client(server) as client:
        result = await client.call_tool("create_customer", {"ragione_sociale": "ACME"})

    assert result.is_error
    message = result.content[0].text
    assert "readonly" in message
    assert "manualmente" in message


async def test_search_customers_finds_by_free_text(server, mcp_session: Session) -> None:
    async with Client(server) as client:
        await client.call_tool("create_customer", {"ragione_sociale": "ACME Srl"})
        await client.call_tool("create_customer", {"ragione_sociale": "Beta Spa"})
        found = _payload(await client.call_tool("search_customers", {"search": "acme"}))

    assert [c["ragione_sociale"] for c in found["items"]] == ["ACME Srl"]


async def test_archive_customer_is_reversible_and_blocks_on_active_deals(
    server, mcp_session: Session
) -> None:
    PipelineService(mcp_session).seed_defaults()
    async with Client(server) as client:
        customer = _payload(await client.call_tool("create_customer", {"ragione_sociale": "ACME"}))
        deal = _payload(
            await client.call_tool(
                "create_deal", {"nome": "X", "customer_id": customer["id"]}
            )
        )

        blocked = await client.call_tool("archive_customer", {"customer_id": customer["id"]})
        assert blocked.is_error
        assert "deal attivi" in blocked.content[0].text

        await client.call_tool("archive_deal", {"deal_id": deal["id"]})
        ok = await client.call_tool("archive_customer", {"customer_id": customer["id"]})

    assert not ok.is_error
```

- [ ] **Step 2: Run it to watch it fail**

Run: `uv run pytest apps/mcp/tests/test_mcp_tools.py -v`
Expected: FAIL — the entity tools are not registered, so `list_tools` is missing them.

- [ ] **Step 3: Write `tools/customers.py`**

```python
from typing import Any
from uuid import UUID

from pigrocrm.core.customers.schemas import CustomerCreate, CustomerListQuery, CustomerUpdate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm_mcp.context import McpContext


def create(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    service = CustomerService(context.session)
    return service.create(CustomerCreate(**data), context.actor).model_dump(mode="json")


def update(context: McpContext, customer_id: str, data: dict[str, Any]) -> dict[str, Any]:
    service = CustomerService(context.session)
    result = service.update(UUID(customer_id), CustomerUpdate(**data), context.actor)
    return result.model_dump(mode="json")


def get(context: McpContext, customer_id: str) -> dict[str, Any]:
    return (
        CustomerService(context.session)
        .get(UUID(customer_id), context.actor)
        .model_dump(mode="json")
    )


def search(context: McpContext, query: CustomerListQuery) -> dict[str, Any]:
    page = CustomerService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def archive(context: McpContext, customer_id: str) -> dict[str, str]:
    CustomerService(context.session).soft_delete(UUID(customer_id), context.actor)
    return {"status": "archiviato", "customer_id": customer_id}
```

- [ ] **Step 4: Write `tools/people.py`**

```python
from typing import Any
from uuid import UUID

from pigrocrm.core.people.schemas import PersonCreate, PersonListQuery, PersonUpdate
from pigrocrm.core.people.service import PersonService
from pigrocrm_mcp.context import McpContext


def create(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    return (
        PersonService(context.session)
        .create(PersonCreate(**data), context.actor)
        .model_dump(mode="json")
    )


def update(context: McpContext, person_id: str, data: dict[str, Any]) -> dict[str, Any]:
    result = PersonService(context.session).update(
        UUID(person_id), PersonUpdate(**data), context.actor
    )
    return result.model_dump(mode="json")


def get(context: McpContext, person_id: str) -> dict[str, Any]:
    return (
        PersonService(context.session).get(UUID(person_id), context.actor).model_dump(mode="json")
    )


def search(context: McpContext, query: PersonListQuery) -> dict[str, Any]:
    page = PersonService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def archive(context: McpContext, person_id: str) -> dict[str, str]:
    PersonService(context.session).soft_delete(UUID(person_id), context.actor)
    return {"status": "archiviato", "person_id": person_id}
```

- [ ] **Step 5: Write `tools/deals.py`**

```python
from typing import Any
from uuid import UUID

from pigrocrm.core.deals.schemas import DealCreate, DealListQuery, DealUpdate
from pigrocrm.core.deals.service import DealService
from pigrocrm_mcp.context import McpContext


def create(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    return (
        DealService(context.session).create(DealCreate(**data), context.actor).model_dump(mode="json")
    )


def update(context: McpContext, deal_id: str, data: dict[str, Any]) -> dict[str, Any]:
    result = DealService(context.session).update(UUID(deal_id), DealUpdate(**data), context.actor)
    return result.model_dump(mode="json")


def get(context: McpContext, deal_id: str) -> dict[str, Any]:
    return DealService(context.session).get(UUID(deal_id), context.actor).model_dump(mode="json")


def search(context: McpContext, query: DealListQuery) -> dict[str, Any]:
    page = DealService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def move(context: McpContext, deal_id: str, stage_id: str) -> dict[str, Any]:
    result = DealService(context.session).move_stage(UUID(deal_id), UUID(stage_id), context.actor)
    return result.model_dump(mode="json")


def archive(context: McpContext, deal_id: str) -> dict[str, str]:
    DealService(context.session).soft_delete(UUID(deal_id), context.actor)
    return {"status": "archiviato", "deal_id": deal_id}
```

- [ ] **Step 6: Replace `tools/__init__.py` with the real registration**

```python
from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from mcp.server import MCPServer

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.customers.schemas import CustomerListQuery
from pigrocrm.core.deals.schemas import DealListQuery
from pigrocrm.core.people.schemas import PersonListQuery
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm_mcp.context import McpContext
from pigrocrm_mcp.tools import customers, deals, people

EntityType = Literal["customer", "person", "deal"]


def register_entity_tools(
    mcp: MCPServer, context: McpContext, guard: Callable[..., Any]
) -> None:
    """Every tool is a thin call into a core service.

    A tool that contained business logic would be logic the web app cannot reach —
    exactly the failure this architecture exists to prevent. Custom fields travel as
    a plain dict validated by the core validator; call `describe_schema` to learn
    which keys are legal right now.
    """

    # ---- customers -------------------------------------------------------

    @mcp.tool()
    @guard
    def create_customer(
        ragione_sociale: str,
        partita_iva: str | None = None,
        codice_fiscale: str | None = None,
        codice_sdi: str | None = None,
        pec: str | None = None,
        indirizzo: str | None = None,
        cap: str | None = None,
        comune: str | None = None,
        provincia: str | None = None,
        email: str | None = None,
        telefono: str | None = None,
        note: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea un cliente. Chiama prima `describe_schema` per i campi personalizzati."""
        return customers.create(
            context,
            {
                "ragione_sociale": ragione_sociale,
                "partita_iva": partita_iva,
                "codice_fiscale": codice_fiscale,
                "codice_sdi": codice_sdi,
                "pec": pec,
                "indirizzo": indirizzo,
                "cap": cap,
                "comune": comune,
                "provincia": provincia,
                "email": email,
                "telefono": telefono,
                "note": note,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_customer(customer_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Aggiorna un cliente. `changes` contiene solo i campi da modificare."""
        return customers.update(context, customer_id, changes)

    @mcp.tool()
    @guard
    def get_customer(customer_id: str) -> dict[str, Any]:
        """Legge un cliente. Per il contesto completo usa la risorsa `customer://<id>`."""
        return customers.get(context, customer_id)

    @mcp.tool()
    @guard
    def search_customers(
        search: str | None = None, stato: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Cerca clienti per ragione sociale, P.IVA, codice fiscale o email."""
        return customers.search(
            context, CustomerListQuery(search=search, stato=stato, limit=limit)
        )

    @mcp.tool()
    @guard
    def archive_customer(customer_id: str) -> dict[str, str]:
        """Archivia un cliente (reversibile). Fallisce se ha deal attivi."""
        return customers.archive(context, customer_id)

    # ---- people ----------------------------------------------------------

    @mcp.tool()
    @guard
    def create_person(
        nome: str,
        cognome: str | None = None,
        email: str | None = None,
        telefono: str | None = None,
        ruolo: str | None = None,
        linkedin: str | None = None,
        note: str | None = None,
        customer_id: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea una persona. `customer_id` è facoltativo: un contatto può non avere ancora un cliente."""
        return people.create(
            context,
            {
                "nome": nome,
                "cognome": cognome,
                "email": email,
                "telefono": telefono,
                "ruolo": ruolo,
                "linkedin": linkedin,
                "note": note,
                "customer_id": UUID(customer_id) if customer_id else None,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_person(person_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Aggiorna una persona. Per staccarla dal cliente passa `{"detach": true}`."""
        return people.update(context, person_id, changes)

    @mcp.tool()
    @guard
    def get_person(person_id: str) -> dict[str, Any]:
        """Legge una persona."""
        return people.get(context, person_id)

    @mcp.tool()
    @guard
    def search_people(
        search: str | None = None, customer_id: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Cerca persone per nome, cognome o email, opzionalmente entro un cliente."""
        return people.search(
            context,
            PersonListQuery(
                search=search,
                customer_id=UUID(customer_id) if customer_id else None,
                limit=limit,
            ),
        )

    @mcp.tool()
    @guard
    def archive_person(person_id: str) -> dict[str, str]:
        """Archivia una persona (reversibile)."""
        return people.archive(context, person_id)

    # ---- deals -----------------------------------------------------------

    @mcp.tool()
    @guard
    def create_deal(
        nome: str,
        customer_id: str,
        valore_previsto: float | None = None,
        probabilita: int | None = None,
        data_chiusura_prevista: str | None = None,
        note: str | None = None,
        ore_preventivate: float | None = None,
        valore_preventivato: float | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea un deal. Il cliente è obbligatorio; lo stato iniziale è il primo della pipeline."""
        return deals.create(
            context,
            {
                "nome": nome,
                "customer_id": UUID(customer_id),
                "valore_previsto": valore_previsto,
                "probabilita": probabilita,
                "data_chiusura_prevista": data_chiusura_prevista,
                "note": note,
                "ore_preventivate": ore_preventivate,
                "valore_preventivato": valore_preventivato,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_deal(deal_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Aggiorna un deal. Per cambiare stato usa `move_deal`."""
        return deals.update(context, deal_id, changes)

    @mcp.tool()
    @guard
    def get_deal(deal_id: str) -> dict[str, Any]:
        """Legge un deal."""
        return deals.get(context, deal_id)

    @mcp.tool()
    @guard
    def search_deals(
        search: str | None = None,
        customer_id: str | None = None,
        stage_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Cerca deal per nome, cliente o stato di pipeline."""
        return deals.search(
            context,
            DealListQuery(
                search=search,
                customer_id=UUID(customer_id) if customer_id else None,
                stage_id=UUID(stage_id) if stage_id else None,
                limit=limit,
            ),
        )

    @mcp.tool()
    @guard
    def move_deal(deal_id: str, stage_id: str) -> dict[str, Any]:
        """Sposta un deal in un altro stato. Uno stato vinto/perso fissa la probabilità a 100/0."""
        return deals.move(context, deal_id, stage_id)

    @mcp.tool()
    @guard
    def archive_deal(deal_id: str) -> dict[str, str]:
        """Archivia un deal (reversibile)."""
        return deals.archive(context, deal_id)

    # ---- shared ----------------------------------------------------------

    @mcp.tool()
    @guard
    def list_pipeline_stages() -> dict[str, Any]:
        """Elenca gli stati della pipeline, con il tipo (open/won/lost) di ciascuno."""
        stages = PipelineService(context.session).list()
        return {"stages": [stage.model_dump(mode="json") for stage in stages]}

    @mcp.tool()
    @guard
    def get_timeline(entity_type: EntityType, entity_id: str, limit: int = 50) -> dict[str, Any]:
        """Cronologia di un'entità. `actor_type` distingue le azioni umane da quelle di un agente."""
        entries = ActivityService(context.session).timeline(
            entity_type, UUID(entity_id), limit=limit
        )
        return {"entries": [entry.model_dump(mode="json") for entry in entries]}
```

- [ ] **Step 7: Write the stdio entry point**

`apps/mcp/src/pigrocrm_mcp/__main__.py`:

```python
import os
import sys

from pigrocrm.core.auth.pat_service import PatService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.errors import DomainError
from pigrocrm_mcp.server import build_server

PAT_ENV_VAR = "PIGROCRM_TOKEN"


def main() -> int:
    token = os.environ.get(PAT_ENV_VAR)
    if not token:
        print(
            f"{PAT_ENV_VAR} non impostato. Genera un token dalla UI in Impostazioni → Token.",
            file=sys.stderr,
        )
        return 1

    engine = create_engine_from_settings(get_settings())
    factory = session_factory(engine)
    session = factory()

    try:
        actor = PatService(session).resolve(token)
    except DomainError as exc:
        print(f"Token non valido: {exc.message}", file=sys.stderr)
        return 1

    build_server(lambda: session, lambda: actor).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Run the MCP suite**

Run: `uv run pytest apps/mcp -v`
Expected: PASS (13 passed)

- [ ] **Step 9: Run everything**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: all green, including `test_core_never_imports_from_adapters`.

- [ ] **Step 10: Verify the server starts over stdio**

```bash
docker run --rm -d --name pigrocrm-smoke -e POSTGRES_PASSWORD=pigrocrm \
  -e POSTGRES_USER=pigrocrm -e POSTGRES_DB=pigrocrm -p 55432:5432 postgres:17-alpine
sleep 3
export PIGROCRM_DATABASE_URL="postgresql+psycopg://pigrocrm:pigrocrm@localhost:55432/pigrocrm"
(cd packages/core && uv run alembic upgrade head)
uv run pigrocrm createadmin --email admin@pigro.it --nome Admin   # password at the prompt
uv run python -m pigrocrm_mcp   # expect the missing-token message, then exit 1
docker stop pigrocrm-smoke
```

Expected: `alembic upgrade head` succeeds, `createadmin` prints `Creato amministratore admin@pigro.it`,
and `python -m pigrocrm_mcp` exits 1 with the message about `PIGROCRM_TOKEN`. That last one is the
success case for this smoke test: it proves the entry point loads the whole dependency graph.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: MCP entity tools, archive-only mutations and stdio entry point"
```

---

## Definition of done for plan 1A

- [ ] `uv run pytest` is green across `packages/core`, `apps/api` and `apps/mcp`
- [ ] `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy` are clean
- [ ] `test_core_never_imports_from_adapters` passes — the dependency direction holds
- [ ] `test_migrations_produce_exactly_the_models_schema` passes — no schema drift
- [ ] `test_the_full_journey_an_agent_would_take` passes — spec criterion 2 is met
- [ ] The timeline distinguishes `user` from `mcp` — spec criterion 3 is met

Then continue with `2026-08-06-slice-1b-frontend.md`.
