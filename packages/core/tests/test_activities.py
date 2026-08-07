from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import ValidationFailed

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


# --- Fix round 1 ------------------------------------------------------------------


def test_record_sanitizes_non_finite_floats(db_session: Session) -> None:
    """Postgres JSONB rejects NaN/Infinity outright; a naive audit write must not be
    able to take the operation it is recording down with it."""
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record(
        "customer",
        entity_id,
        "created",
        USER,
        {"a": float("nan"), "b": float("inf"), "c": float("-inf")},
    )
    db_session.commit()

    entry = service.timeline("customer", entity_id)[0]
    assert entry.payload == {"a": "NaN", "b": "Infinity", "c": "-Infinity"}


def test_record_strips_null_bytes_from_strings(db_session: Session) -> None:
    """Postgres text storage cannot hold a NUL byte at all."""
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("customer", entity_id, "created", USER, {"note": "abc\x00def"})
    db_session.commit()

    entry = service.timeline("customer", entity_id)[0]
    assert entry.payload == {"note": "abcdef"}


def test_record_truncates_long_strings(db_session: Session) -> None:
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("customer", entity_id, "created", USER, {"note": "x" * 3000})
    db_session.commit()

    saved = service.timeline("customer", entity_id)[0].payload["note"]
    assert len(saved) == 2001
    assert saved.endswith("…")


def test_record_caps_nesting_depth(db_session: Session) -> None:
    """Must not raise on pathological input and must not preserve unbounded nesting.
    The exact placeholder text is an implementation detail; only that recursion stops
    at a bounded depth is the contract."""
    nested: dict[str, Any] = {"leaf": "bottom"}
    for _ in range(20):
        nested = {"next": nested}

    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("customer", entity_id, "created", USER, nested)
    db_session.commit()

    cursor: Any = service.timeline("customer", entity_id)[0].payload
    for _ in range(10):
        assert isinstance(cursor, dict)
        cursor = cursor["next"]
    # ten "next" unwraps land on the placeholder: recursion stopped, not a dict.
    assert isinstance(cursor, str)


def test_record_truncates_kind_and_entity_type_to_column_widths(db_session: Session) -> None:
    """`entity_type`/`kind` are developer-controlled literals, not user input -- plain
    truncation is enough, unlike the richer sanitization the payload needs."""
    long_entity_type = "y" * 50
    long_kind = "x" * 100
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record(long_entity_type, entity_id, long_kind, USER)
    db_session.commit()

    entry = service.timeline(long_entity_type[:30], entity_id)[0]
    assert entry.entity_type == long_entity_type[:30]
    assert entry.kind == long_kind[:50]


def test_session_remains_usable_after_a_hostile_payload(db_session: Session) -> None:
    """Before sanitization, recording a NaN reached `flush()` raw and Postgres
    rejected it with a `DataError`, leaving the session in `PendingRollbackError` --
    poisoning every later operation in the same transaction, including the unrelated
    change the activity was supposed to be auditing."""
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("customer", entity_id, "created", USER, {"x": float("nan")})

    # The session must still accept further writes in the same transaction.
    service.record("customer", entity_id, "updated", USER, {"y": 1})
    db_session.commit()

    assert len(service.timeline("customer", entity_id)) == 2


# --- Final review item 5 (CRITICAL): timeline's limit was unbounded, unlike REST --
#
# All three REST timeline routes declare `Query(ge=1, le=200)`; the shared service
# behind both adapters -- and therefore the MCP `get_timeline` tool, which called
# straight into it with a bare `int` parameter -- enforced no bound at all. `-1`
# reaches Postgres as `InvalidRowCountInLimitClause`; `10**9` succeeds where REST
# would refuse the same value outright. Bounding it here, at the one place both
# adapters share, is what makes the MCP tool match REST without the tool itself
# needing its own copy of the rule -- the same pattern `_check_numbers` already
# uses for `probabilita` on `create_deal`'s tool parameter.


def test_timeline_rejects_a_limit_below_one(db_session: Session) -> None:
    service = ActivityService(db_session)
    with pytest.raises(ValidationFailed) as exc:
        service.timeline("customer", uuid4(), limit=0)
    assert exc.value.details["field"] == "limit"


def test_timeline_rejects_a_negative_limit(db_session: Session) -> None:
    """Before the bound existed, this reached Postgres raw as
    `psycopg.errors.InvalidRowCountInLimitClause` ('LIMIT must not be negative')."""
    service = ActivityService(db_session)
    with pytest.raises(ValidationFailed):
        service.timeline("customer", uuid4(), limit=-1)


def test_timeline_rejects_a_limit_above_two_hundred(db_session: Session) -> None:
    """Matches every REST timeline route's own `Query(ge=1, le=200)` exactly."""
    service = ActivityService(db_session)
    with pytest.raises(ValidationFailed) as exc:
        service.timeline("customer", uuid4(), limit=201)
    assert exc.value.details["expected"] == "1-200"


def test_timeline_accepts_the_boundary_values(db_session: Session) -> None:
    service = ActivityService(db_session)
    entity_id = uuid4()
    service.record("customer", entity_id, "created", USER)
    db_session.commit()

    assert service.timeline("customer", entity_id, limit=1) == service.timeline(
        "customer", entity_id, limit=200
    )
