import subprocess
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.storage.local import LocalFileStorage
from pigrocrm.core.timetracking.models import CostCategory, TimeEntry


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
    session = session_factory(db_engine)(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded_user_id(db_session: Session) -> UUID:
    user = User(
        email=f"tester-{uuid4()}@example.test",
        password_hash="x",
        nome="Tester",
        ruolo="collaboratore",
    )
    db_session.add(user)
    db_session.flush()
    return user.id


@pytest.fixture
def seeded_open_stage_id(db_session: Session) -> UUID:
    stage = PipelineStage(
        nome=f"Aperto {uuid4()}", posizione=0, probabilita_default=10, tipo="open"
    )
    db_session.add(stage)
    db_session.flush()
    return stage.id


@pytest.fixture
def seeded_won_stage_id(db_session: Session) -> UUID:
    stage = PipelineStage(nome=f"Vinto {uuid4()}", posizione=9, probabilita_default=100, tipo="won")
    db_session.add(stage)
    db_session.flush()
    return stage.id


@pytest.fixture
def seeded_deal_id(db_session: Session, seeded_open_stage_id: UUID) -> UUID:
    customer = Customer(ragione_sociale=f"Cliente {uuid4()}")
    db_session.add(customer)
    db_session.flush()
    deal = Deal(
        nome="Progetto di prova",
        customer_id=customer.id,
        pipeline_stage_id=seeded_open_stage_id,
        probabilita=10,
    )
    db_session.add(deal)
    db_session.flush()
    return deal.id


@pytest.fixture
def seeded_category_id(db_session: Session) -> UUID:
    category = CostCategory(nome=f"Categoria {uuid4()}", posizione=0, code=None)
    db_session.add(category)
    db_session.flush()
    return category.id


@pytest.fixture
def seeded_entry_id(db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID) -> UUID:
    entry = TimeEntry(
        deal_id=seeded_deal_id,
        user_id=seeded_user_id,
        data=date(2026, 3, 10),
        ore=Decimal("8.00"),
        descrizione="Analisi",
        tariffa_applicata=Decimal("80.000000"),
        tariffa_origine="manuale",
    )
    db_session.add(entry)
    db_session.flush()
    return entry.id


@pytest.fixture
def local_storage(tmp_path) -> LocalFileStorage:
    """A tmp-dir backend, never the default `./var/documents` root -- a test must not
    write real files into this repository's working tree."""
    return LocalFileStorage(str(tmp_path / "documents"))


def extract_pdf_text(storage, session, document_id: UUID) -> str:
    """Reads the stored PDF back and extracts its text with `pdftotext`, which ships in
    the same API image as Pandoc and Typst. Reading the produced artefact rather than
    the intermediate Markdown is the only assertion that proves what the client
    actually receives."""
    from pigrocrm.core.documents.repository import DocumentRepository

    version = DocumentRepository(session).version(document_id, 1)
    assert version is not None
    data = storage.get(version.storage_key)
    result = subprocess.run(
        ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
    )
    return result.stdout.decode("utf-8", errors="replace")
