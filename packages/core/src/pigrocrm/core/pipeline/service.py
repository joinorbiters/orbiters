from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.repository import PipelineRepository
from pigrocrm.core.pipeline.schemas import (
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
)

DEFAULT_STAGES: list[tuple[str, int, int, str]] = [
    ("Lead", 0, 10, "open"),
    ("Contattato", 1, 25, "open"),
    ("Offerta", 2, 50, "open"),
    ("Negoziazione", 3, 75, "open"),
    ("Vinto", 4, 100, "won"),
    ("Perso", 5, 0, "lost"),
]


def _check_probability(value: int | None) -> None:
    if value is not None and not 0 <= value <= 100:
        raise ValidationFailed(
            "pipeline_stage", "probabilita_default", "fuori intervallo", expected="0-100"
        )


class PipelineService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = PipelineRepository(session)

    def create(self, data: PipelineStageCreate, actor: Actor) -> PipelineStageRead:
        actor.require_admin("create_pipeline_stage")
        _check_probability(data.probabilita_default)
        stage = self.repo.add(PipelineStage(**data.model_dump()))
        self.session.commit()
        return PipelineStageRead.model_validate(stage)

    def update(self, stage_id: UUID, data: PipelineStageUpdate, actor: Actor) -> PipelineStageRead:
        actor.require_admin("update_pipeline_stage")
        stage = self.repo.get(stage_id)
        if stage is None:
            raise NotFound("pipeline_stage", stage_id)
        changes = data.model_dump(exclude_none=True)
        _check_probability(changes.get("probabilita_default"))
        for key, value in changes.items():
            setattr(stage, key, value)
        self.session.commit()
        return PipelineStageRead.model_validate(stage)

    def get(self, stage_id: UUID) -> PipelineStageRead:
        stage = self.repo.get(stage_id)
        if stage is None:
            raise NotFound("pipeline_stage", stage_id)
        return PipelineStageRead.model_validate(stage)

    # `list` is defined LAST in this class on purpose — see the note below the code.
    def seed_defaults(self) -> list[PipelineStageRead]:
        existing = {s.nome for s in self.repo.list()}
        for nome, posizione, probabilita, tipo in DEFAULT_STAGES:
            if nome not in existing:
                self.repo.add(
                    PipelineStage(
                        nome=nome,
                        posizione=posizione,
                        probabilita_default=probabilita,
                        tipo=tipo,
                    )
                )
        self.session.commit()
        return self.list()

    def default_stage(self) -> PipelineStageRead:
        stages = self.list()
        if not stages:
            raise NotFound("pipeline_stage", "default")
        return stages[0]

    def list(self) -> list[PipelineStageRead]:
        return [PipelineStageRead.model_validate(s) for s in self.repo.list()]
