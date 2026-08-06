from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.db import Base
from pigrocrm.core.pipeline.models import PipelineStage


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, stage_id: UUID) -> PipelineStage | None:
        return self.session.get(PipelineStage, stage_id)

    def get_by_code(self, code: str) -> PipelineStage | None:
        stmt = select(PipelineStage).where(PipelineStage.code == code)
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self) -> list[PipelineStage]:
        stmt = select(PipelineStage).order_by(PipelineStage.posizione, PipelineStage.nome)
        return list(self.session.execute(stmt).scalars())

    def add(self, stage: PipelineStage) -> PipelineStage:
        self.session.add(stage)
        self.session.flush()
        return stage

    def delete(self, stage: PipelineStage) -> None:
        self.session.delete(stage)
        self.session.flush()

    def count_deals_in_stage(self, stage_id: UUID) -> int:
        """Deals arrive in a later slice. Until then, `deals` is simply absent from
        `Base.metadata.tables`, and this returns 0 rather than querying a table that
        does not exist yet -- the same defensive lookup `CustomerRepository` uses for
        `count_active_deals`.

        The referencing column is assumed to be named `stage_id`, following this
        codebase's `_id`-suffix convention for foreign keys (`Activity.entity_id`,
        `Activity.actor_id`). If the task that introduces `deals` names it differently,
        this is the one line that needs to change.
        """
        deals_table = Base.metadata.tables.get("deals")
        if deals_table is None:
            return 0
        stmt = (
            select(func.count()).select_from(deals_table).where(deals_table.c.stage_id == stage_id)
        )
        return self.session.execute(stmt).scalar_one()
