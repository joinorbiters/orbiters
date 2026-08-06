from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
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


@pytest.fixture(scope="module")
def rollback_regression_table(db_engine: Engine) -> Iterator[str]:
    """A real table, created and dropped on its own already-committed connection.

    Its lifecycle must not depend on what any single test's `db_session` does with commit or
    rollback - that independence is what lets the two tests below prove isolation survives a
    mid-test `.rollback()`, not just a plain `.commit()`. Module-scoped so both tests share
    the same table: the second test must see what the first one did (or, if the fixture is
    doing its job, did not do).
    """
    table = "_regression_rollback_isolation"
    with db_engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE IF NOT EXISTS {table} (n INTEGER NOT NULL)"))
    yield table
    with db_engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


def test_mid_test_rollback_does_not_escape_the_savepoint(
    db_session: Session, rollback_regression_table: str
) -> None:
    """The hard case for `db_session` isolation: a `.rollback()`, not just a `.commit()`.

    SQLAlchemy's default `join_transaction_mode` ("conditional_savepoint") degrades to
    "rollback_only" once a session is bound to a connection already in a transaction - which
    is exactly how `db_session` binds it. In "rollback_only" mode, `.commit()` is safely
    contained (it cannot reach the real transaction), but `.rollback()` ends the real outer
    transaction for real. A write issued after that point, followed by `.commit()`, then
    lands in the database for good, because there is no longer an outer transaction left for
    the fixture to roll back - its teardown only warns
    ("transaction already deassociated from connection") instead of undoing anything.
    `db_session` must pass `join_transaction_mode="create_savepoint"` so that even this
    `.rollback()` only unwinds to a SAVEPOINT, leaving the fixture's own outer transaction
    intact. The next test is the other half of the proof: it fails if that argument is
    removed from conftest.py.
    """
    db_session.execute(text(f"INSERT INTO {rollback_regression_table} (n) VALUES (1)"))
    db_session.rollback()
    db_session.execute(text(f"INSERT INTO {rollback_regression_table} (n) VALUES (2)"))
    db_session.commit()


def test_previous_tests_post_rollback_commit_did_not_leak(
    db_session: Session, rollback_regression_table: str
) -> None:
    """Proves the previous test's post-rollback commit did not survive into this test.

    A fresh `db_session` (fresh connection, fresh transaction) must see an empty table. If it
    does not, row `n=2` from the previous test escaped the fixture's teardown rollback and was
    committed for real - the exact contamination this fixture exists to prevent.
    """
    count = db_session.execute(
        text(f"SELECT count(*) FROM {rollback_regression_table}")
    ).scalar_one()
    assert count == 0, "a row committed after a mid-test rollback leaked into another test"
