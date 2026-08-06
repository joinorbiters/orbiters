from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, Integer, Table
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.db import Base
from pigrocrm.core.errors import Conflict, PermissionDenied, ValidationFailed
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


# --- Fix round 1 ------------------------------------------------------------------


def test_seed_is_idempotent_across_a_rename(db_session: Session) -> None:
    """`nome` is a label the user is free to rename -- exactly why `tipo` exists, and
    exactly why `seed_defaults` must not use `nome` as the seeded stages' identity
    either. Renaming "Vinto" and reseeding must not recreate a stage called "Vinto"."""
    service = PipelineService(db_session)
    stages = service.seed_defaults()
    vinto = next(s for s in stages if s.nome == "Vinto")
    service.update(vinto.id, PipelineStageUpdate(nome="Chiuso vinto"), ADMIN)

    reseeded = service.seed_defaults()

    assert len(reseeded) == 6
    assert {s.nome for s in reseeded} == {
        "Lead",
        "Contattato",
        "Offerta",
        "Negoziazione",
        "Chiuso vinto",
        "Perso",
    }


def test_update_cannot_change_code(db_session: Session) -> None:
    """`code` is identity, like `field_type` for custom fields: it must not be a
    settable field on the update schema at all, not merely rejected by convention."""
    assert "code" not in PipelineStageUpdate.model_fields
    with pytest.raises(ValidationError):
        PipelineStageUpdate.model_validate({"code": "qualcosa"})


def test_default_stage_returns_the_lowest_position_open_stage(db_session: Session) -> None:
    """A deal created without an explicit stage must start somewhere still in
    progress. A terminal stage at a lower position must not win just because it
    sorts first."""
    service = PipelineService(db_session)
    service.create(PipelineStageCreate(nome="Chiuso perso", posizione=-1, tipo="lost"), ADMIN)
    service.create(PipelineStageCreate(nome="Nuovo", posizione=0, tipo="open"), ADMIN)

    assert service.default_stage().nome == "Nuovo"


def test_default_stage_raises_when_no_open_stage_exists(db_session: Session) -> None:
    service = PipelineService(db_session)
    service.create(PipelineStageCreate(nome="Vinto", posizione=0, tipo="won"), ADMIN)

    with pytest.raises(ValidationFailed):
        service.default_stage()


def test_delete_removes_a_stage(db_session: Session) -> None:
    service = PipelineService(db_session)
    stage = service.create(PipelineStageCreate(nome="Temporaneo", posizione=0), ADMIN)

    service.delete(stage.id, ADMIN)

    assert stage.id not in {s.id for s in service.list()}


def test_delete_requires_admin(db_session: Session) -> None:
    service = PipelineService(db_session)
    stage = service.create(PipelineStageCreate(nome="Temporaneo", posizione=0), ADMIN)

    with pytest.raises(PermissionDenied):
        service.delete(stage.id, COLLAB)


def test_create_rejects_a_duplicate_code(db_session: Session) -> None:
    service = PipelineService(db_session)
    service.create(PipelineStageCreate(nome="Uno", posizione=0, code="dup"), ADMIN)

    with pytest.raises(Conflict):
        service.create(PipelineStageCreate(nome="Due", posizione=1, code="dup"), ADMIN)


def test_create_allows_several_stages_with_no_code(db_session: Session) -> None:
    """`code=None` is the normal case for a user-created stage. Postgres allows any
    number of `NULL`s under a unique index, so these must not collide with each other."""
    service = PipelineService(db_session)
    service.create(PipelineStageCreate(nome="Uno", posizione=0), ADMIN)
    service.create(PipelineStageCreate(nome="Due", posizione=1), ADMIN)

    assert {s.nome for s in service.list()} == {"Uno", "Due"}


# --- Fix round 2 ------------------------------------------------------------------


def test_create_rejects_a_duplicate_code_race_past_the_precheck(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`test_create_rejects_a_duplicate_code` above only exercises the precheck
    branch -- the second call's own `get_by_code` correctly finds the first row, so
    the `except IntegrityError` branch never runs. This mirrors
    `test_duplicate_key_race_past_the_precheck_still_becomes_a_domain_conflict` in
    fields (force the precheck to report "not found" while a real duplicate already
    exists, so the INSERT hits the database's own unique index) and is the test that
    was actually missing, not the one already there."""
    service = PipelineService(db_session)
    service.create(PipelineStageCreate(nome="Uno", posizione=0, code="dup"), ADMIN)

    monkeypatch.setattr(service.repo, "get_by_code", lambda code: None)

    with pytest.raises(Conflict) as exc:
        service.create(PipelineStageCreate(nome="Due", posizione=1, code="dup"), ADMIN)
    assert exc.value.details["code"] == "dup"

    # The session must still be usable right after -- a leftover PendingRollbackError
    # would blow up on the very next statement issued on it.
    assert len(service.list()) == 1


def test_seed_defaults_race_past_the_precheck_converges_silently(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same shape as the create()-race tests (force the precheck to lie so the INSERT
    hits the real unique constraint), but seed_defaults's contract is the opposite of
    create()'s: the caller only wanted the defaults to exist, not to create *this
    specific* row, so losing the race must converge silently instead of raising
    Conflict. Lies only on the first `repo.list()` call (the precheck that computes
    `existing_codes`) -- `seed_defaults`'s own trailing `return self.list()` also calls
    `repo.list()`, and that call must see the real rows."""
    service = PipelineService(db_session)
    service.seed_defaults()

    real_list = service.repo.list
    calls = {"n": 0}

    def _lie_on_first_call() -> list[Any]:
        calls["n"] += 1
        return [] if calls["n"] == 1 else real_list()

    monkeypatch.setattr(service.repo, "list", _lie_on_first_call)

    result = service.seed_defaults()

    assert len(result) == 6


def test_delete_fails_loudly_if_the_deals_table_lacks_the_expected_column(
    db_session: Session,
) -> None:
    """Returning 0 from `count_deals_in_stage` is only correct when `deals` does not
    exist yet. If it exists but without the expected column, that is a bug in this
    code, not "no deals" -- silently returning 0 would let `delete()` remove a stage
    that might still be full of deals. Registers a bare `deals` table directly in
    `Base.metadata` (no `pipeline_stage_id`) rather than waiting for the real table to
    exist; this only exercises the Python-side column lookup, never issues SQL against
    it, so no real DDL is needed."""
    fake_deals = Table("deals", Base.metadata, Column("id", Integer, primary_key=True))
    try:
        service = PipelineService(db_session)
        stage = service.create(PipelineStageCreate(nome="Occupato", posizione=0), ADMIN)

        with pytest.raises(RuntimeError):
            service.delete(stage.id, ADMIN)
    finally:
        Base.metadata.remove(fake_deals)


def test_nome_over_the_column_width_is_rejected_on_create_and_update() -> None:
    """Same class of gap `code`'s `CODE_MAX_LENGTH` closed in fix round 1, but on
    `nome` -- present since the original Task 9 brief, unbounded until now. The
    fourth time this project has hit an unbounded string column that can reach
    `flush()` and come back as a raw, session-poisoning `DataError`."""
    with pytest.raises(ValidationError):
        PipelineStageCreate(nome="x" * 61, posizione=0)
    with pytest.raises(ValidationError):
        PipelineStageUpdate(nome="x" * 61)
