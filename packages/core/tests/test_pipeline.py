import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
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
