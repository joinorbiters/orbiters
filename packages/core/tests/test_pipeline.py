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
