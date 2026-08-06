from datetime import UTC, datetime
from uuid import UUID

from pigrocrm.core.db import uuid7
from sqlalchemy import text
from sqlalchemy.orm import Session


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
