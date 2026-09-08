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

    def get_by_tipo(self, tipo: str) -> list[PipelineStage]:
        """Every stage of a kind, ordered by `posizione`.

        Returns a **list** and not an `Optional`, deliberately: residuo **R14** records
        that nothing forbids two `tipo='won'` stages, and "there are two" is an answer the
        automation runner has to be able to see so it can decline instead of picking one.
        An `Optional` signature would force this method to choose, which is exactly the
        decision it must not make.

        Defined above `list` because its return annotation is a bare `list[...]`: after
        `def list` rebinds that name in the class namespace, evaluating this annotation
        would resolve `list` to the method and raise `TypeError` at import time on 3.13.
        """
        return list(
            self.session.execute(
                select(PipelineStage)
                .where(PipelineStage.tipo == tipo)
                .order_by(PipelineStage.posizione, PipelineStage.id)
            ).scalars()
        )

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
        `count_active_deals`. The referencing column is `pipeline_stage_id` (per the
        plan's Task 12).

        Returning 0 is only correct for the "table does not exist yet" case above. If
        `deals` exists but does not expose `pipeline_stage_id`, that is a bug in this
        code, not "no deals in this stage" -- returning 0 there would let `delete()`
        remove a stage that might still be full of deals, so this raises instead of
        guessing.
        """
        deals_table = Base.metadata.tables.get("deals")
        if deals_table is None:
            return 0  # i deal arrivano in un task successivo
        column = deals_table.c.get("pipeline_stage_id")
        if column is None:
            # La tabella esiste ma non ha la colonna attesa: e' un errore di codice,
            # non l'assenza di deal. Restituire 0 qui permetterebbe di cancellare uno
            # stato ancora referenziato.
            raise RuntimeError(
                "la tabella deals non espone pipeline_stage_id: aggiornare count_deals_in_stage"
            )
        stmt = select(func.count()).select_from(deals_table).where(column == stage_id)
        return self.session.execute(stmt).scalar_one()
