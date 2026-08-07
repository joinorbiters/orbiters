from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.repository import PipelineRepository
from pigrocrm.core.pipeline.schemas import (
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
)

# (code, nome, posizione, probabilita_default, tipo). `seed_defaults` deduplicates on
# `code`, never on `nome` -- see `PipelineStage`'s docstring for why.
DEFAULT_STAGES: list[tuple[str, str, int, int, str]] = [
    ("lead", "Lead", 0, 10, "open"),
    ("contattato", "Contattato", 1, 25, "open"),
    ("offerta", "Offerta", 2, 50, "open"),
    ("negoziazione", "Negoziazione", 3, 75, "open"),
    ("vinto", "Vinto", 4, 100, "won"),
    ("perso", "Perso", 5, 0, "lost"),
]


def _check_probability(value: int | None) -> None:
    if value is not None and not 0 <= value <= 100:
        raise ValidationFailed(
            "pipeline_stage", "probabilita_default", "fuori intervallo", expected="0-100"
        )


def _conflicting_code(code: str | None) -> Conflict:
    return Conflict("pipeline_stage", "esiste già uno stato con questo code", code=code)


class PipelineService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = PipelineRepository(session)

    def create(self, data: PipelineStageCreate, actor: Actor) -> PipelineStageRead:
        actor.require_admin("create_pipeline_stage")
        _check_probability(data.probabilita_default)
        if data.code is not None and self.repo.get_by_code(data.code) is not None:
            raise _conflicting_code(data.code)
        stage = PipelineStage(**data.model_dump())
        try:
            self.repo.add(stage)
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a race between two concurrent requests
            # that both pass it before either commits -- the unique index on `code` is
            # the real authority. The rollback is mandatory: without it the session is
            # unusable for the caller.
            self.session.rollback()
            raise _conflicting_code(data.code) from exc
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

    def delete(self, stage_id: UUID, actor: Actor) -> None:
        """Admin-only, and refuses if any deal is currently in this stage -- deleting
        it out from under them would leave those deals pointing at nothing.

        `count_deals_in_stage` counts every deal in the stage, soft-deleted or not
        (see that method's own docstring): `pipeline_stage_id` is `NOT NULL` with no
        `ON DELETE` rule, so an archived deal's row still references this stage just
        as much as an active one's, and a hard `DELETE` here would hit that foreign
        key regardless of `deleted_at`. Freeing a stage that only has archived deals
        in it means *moving* them to a different stage, not soft-deleting them again
        -- and since a soft-deleted deal is not found by `move_stage` either, the
        full sequence is restore, then move, then soft-delete again. The message
        below says so explicitly, rather than leaving an administrator to work out
        both of those facts from a bare count.
        """
        actor.require_admin("delete_pipeline_stage")
        stage = self.repo.get(stage_id)
        if stage is None:
            raise NotFound("pipeline_stage", stage_id)
        deal_count = self.repo.count_deals_in_stage(stage_id)
        if deal_count > 0:
            raise Conflict(
                "pipeline_stage",
                "ci sono deal in questo stato (inclusi quelli archiviati): "
                "spostali in un altro stato prima di eliminarlo",
                deals=deal_count,
            )
        self.repo.delete(stage)
        self.session.commit()

    def get(self, stage_id: UUID) -> PipelineStageRead:
        stage = self.repo.get(stage_id)
        if stage is None:
            raise NotFound("pipeline_stage", stage_id)
        return PipelineStageRead.model_validate(stage)

    # `list` is defined LAST in this class on purpose — see the note below the code.
    def seed_defaults(self, actor: Actor) -> list[PipelineStageRead]:
        """Admin-only, like every other write method on this class. Reviewed into
        existence for Task 15: this method used to take no `actor` at all, which left
        the admin check living solely in the REST router (`routers/pipeline.py`'s
        `seed()` used to call `actor.require_admin` itself) -- correct for that one
        adapter, but silently absent the moment anything else calls `seed_defaults()`
        directly, which is the entire point of putting it on a shared service. See
        `test_seed_defaults_requires_admin`.
        """
        actor.require_admin("seed_pipeline")
        existing_codes = {s.code for s in self.repo.list() if s.code is not None}
        try:
            for code, nome, posizione, probabilita, tipo in DEFAULT_STAGES:
                if code not in existing_codes:
                    self.repo.add(
                        PipelineStage(
                            code=code,
                            nome=nome,
                            posizione=posizione,
                            probabilita_default=probabilita,
                            tipo=tipo,
                        )
                    )
            self.session.commit()
        except IntegrityError:
            # Different recovery than create()'s on purpose. There, the caller wants
            # *that specific* stage created and a conflict is information they need.
            # Here, the caller only wants the defaults to exist -- if a concurrent
            # seed_defaults() call won the race on `code`'s unique index first, the
            # desired end state (these stages exist) is already reached, so this
            # converges silently instead of raising. The rollback is still mandatory:
            # without it the session is unusable for whatever runs next. Wraps the
            # whole loop, not just the commit -- each `repo.add()` flushes immediately,
            # so the conflict can surface there rather than at the trailing commit.
            self.session.rollback()
        return self.list()

    def default_stage(self) -> PipelineStageRead:
        """The lowest-position stage of type `open` -- never a terminal one. A deal
        created without an explicit stage must start somewhere still in progress;
        handing it a `won`/`lost` stage would fabricate an outcome nobody decided."""
        open_stages = [s for s in self.list() if s.tipo == "open"]
        if not open_stages:
            raise ValidationFailed(
                "pipeline_stage",
                "tipo",
                "nessuno stato aperto configurato",
                expected="almeno uno stato di tipo open",
            )
        return min(open_stages, key=lambda s: s.posizione)

    def list(self) -> list[PipelineStageRead]:
        return [PipelineStageRead.model_validate(s) for s in self.repo.list()]
