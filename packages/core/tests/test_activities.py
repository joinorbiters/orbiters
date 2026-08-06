from uuid import uuid4

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor

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
