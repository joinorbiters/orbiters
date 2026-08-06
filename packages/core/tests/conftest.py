from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.config import Settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory


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
