from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.pipeline.models import PipelineStage


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, stage_id: UUID) -> PipelineStage | None:
        return self.session.get(PipelineStage, stage_id)

    def list(self) -> list[PipelineStage]:
        stmt = select(PipelineStage).order_by(PipelineStage.posizione, PipelineStage.nome)
        return list(self.session.execute(stmt).scalars())

    def add(self, stage: PipelineStage) -> PipelineStage:
        self.session.add(stage)
        self.session.flush()
        return stage
