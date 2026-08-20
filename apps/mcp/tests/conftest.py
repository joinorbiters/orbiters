from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_mcp.server import build_server

ADMIN = Actor(id=None, type="mcp", role="admin")


@pytest.fixture(scope="session")
def mcp_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        engine = create_engine_from_settings(Settings(database_url=container.get_connection_url()))
        import pigrocrm.core.models_registry  # noqa: F401

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def mcp_session(mcp_engine: Engine) -> Iterator[Session]:
    connection = mcp_engine.connect()
    transaction = connection.begin()
    # join_transaction_mode="create_savepoint" is load-bearing, not optional -- see
    # packages/core/tests/conftest.py's identical `db_session` fixture, established
    # in Task 2 specifically because its absence lets `session.rollback()` propagate
    # to the real, externally-managed transaction instead of nesting inside it. This
    # was dormant here because no MCP-side code ever called `session.rollback()`
    # across more than one tool call sharing this session -- until the final review's
    # item 6 fix made `_guard` roll back on every exception, which surfaced it
    # immediately: a blocked `archive_customer` call's `Conflict` rolling back with
    # this parameter absent silently discarded the customer and deal an earlier,
    # already-committed tool call in the *same test* had created. Confirmed directly
    # by reproducing it with this parameter removed and watching two already-
    # committed rows disappear after an unrelated later rollback.
    session = session_factory(mcp_engine)(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def server(mcp_session: Session, tmp_path: Path):
    # `create_document_from_template` (task 13) actually writes bytes through
    # `context.storage`. Without this override, `build_server`'s own default --
    # `storage_from_settings(get_settings())` -- falls back to a `LocalFileStorage`
    # rooted at the repository's own `./var/documents`, exactly the same real-files-
    # left-in-the-working-tree problem the API's `client` fixture was fixed for in
    # task 12. A fresh `tmp_path` per test keeps storage exactly as isolated as the
    # database already is (`mcp_session`'s own rolled-back transaction).
    return build_server(lambda: mcp_session, lambda: ADMIN, LocalFileStorage(tmp_path))


@pytest.fixture
def seeded_customer_id(mcp_session: Session) -> str:
    from pigrocrm.core.customers.models import Customer

    customer = Customer(ragione_sociale="ACME S.r.l.")
    mcp_session.add(customer)
    mcp_session.flush()
    return str(customer.id)


@pytest.fixture
def seeded_template_id(mcp_session: Session) -> str:
    """Built with the same in-process services `server` itself calls -- an
    emitter profile (`create_document_from_template` renders through it) and one
    template with a single declared variable, `oggetto`, so
    `test_describe_template_reports_the_variables_before_anyone_is_asked` has
    exactly one name to check for."""
    from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
    from pigrocrm.core.emitter.service import EmitterProfileService
    from pigrocrm.core.templates.schemas import TemplateCreate, TemplateVariable
    from pigrocrm.core.templates.service import TemplateService

    EmitterProfileService(mcp_session).upsert(
        EmitterProfileUpsert(ragione_sociale="Humancraft di Ivan Sala", partita_iva="14518240966"),
        ADMIN,
    )
    template = TemplateService(mcp_session).create(
        TemplateCreate(
            nome="Consulenza CTO",
            tipo="offerta",
            corpo_markdown="Spett.le {{cliente.ragione_sociale}} — {{oggetto}}",
            variabili_dichiarate=[
                TemplateVariable(
                    nome="oggetto", etichetta="Oggetto", tipo="text", obbligatoria=True
                )
            ],
        ),
        ADMIN,
    )
    return str(template.id)


@pytest.fixture
def seeded_offer_id(mcp_session: Session, seeded_customer_id: str, tmp_path: Path) -> str:
    """A plain (not template-generated) offer in its initial `bozza` state -- enough
    to exercise `set_offer_state`'s guard and `get_document_versions` on a document
    with zero versions, without needing Pandoc/Typst installed."""
    from uuid import UUID

    from pigrocrm.core.documents.schemas import DocumentCreate
    from pigrocrm.core.documents.service import DocumentService

    document = DocumentService(mcp_session, LocalFileStorage(tmp_path)).create(
        DocumentCreate(customer_id=UUID(seeded_customer_id), tipo="offerta", titolo="Offerta test"),
        ADMIN,
    )
    return str(document.id)
