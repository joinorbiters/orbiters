from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.timetracking.categories import CostCategoryService
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.models import Cost
from pigrocrm.core.timetracking.repository import CostRepository
from pigrocrm.core.timetracking.schemas import (
    CostCreate,
    CostListQuery,
    CostPage,
    CostRead,
    CostUpdate,
)

# Typed as the fields module's own EntityType (not a bare `str`), matching
# TimeEntryService.ENTITY/DealService.ENTITY exactly: passing a plain `str` into
# `specs_for` fails mypy strict, which requires the narrower Literal type.
ENTITY: EntityType = "cost"


class CostService:
    """Real money out, with a receipt.

    Not a variant of `TimeEntryService`, and the three differences are the ones that
    matter (§4.2): a cost is money that actually left towards somebody else and has a
    document proving it, while an hour's cost is an internal notional figure derived
    from a rate you chose; an hour is also *potential revenue* and a cost never is; and
    an hour has a quantity comparable with an estimate while a cost has only money.

    The labour cost never produces a row here and is never counted twice: an external
    consultant who invoices you their hours is a `cost` in category "Consulenza
    esterna", and their hours -- if you record them at all -- carry
    `costo_applicato = NULL`. The two sets are disjoint by construction, and Task
    4B-4's test proves no path lets the same expense in from both sides (§7.2).
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CostRepository(session)
        self.deals = DealRepository(session)
        self.documents = DocumentRepository(session)
        self.categories = CostCategoryService(session)
        self.locks = PeriodLockService(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    def _check_importo(self, importo: Decimal) -> None:
        """Zero is refused because it is neither a cost nor a correction. Checked here
        as well as by `ck_costs_importo_non_zero`, not instead of it: this raises the
        project's own `ValidationFailed` naming the field, the CHECK covers every other
        write path including raw SQL."""
        if importo == 0:
            raise ValidationFailed(
                ENTITY, "importo", "importo nullo", expected="un importo diverso da zero"
            )

    def _check_refs(self, deal_id: UUID | None, document_id: UUID | None) -> None:
        """Every foreign key validated in both create and update, optional ones
        included -- skipped only when the caller supplies nothing, never when they
        supply a value. Without this any syntactically valid UUID reaches `flush()` and
        comes back as a raw `ForeignKeyViolation`."""
        if deal_id is not None and self.deals.get(deal_id) is None:
            raise NotFound("deal", deal_id)
        if document_id is not None and self.documents.get(document_id) is None:
            raise NotFound("document", document_id)

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def _update_custom_fields(self, cost: Cost, provided: dict[str, Any]) -> dict[str, Any]:
        """Identical contract to `DealService._update_custom_fields` and
        `TimeEntryService._update_custom_fields`; see either for the full reasoning."""
        active_by_key = {spec.key: spec for spec in self.fields.specs_for(ENTITY)}
        to_remove: set[str] = set()
        for key, value in provided.items():
            if value is not None:
                continue
            spec = active_by_key.get(key)
            if spec is not None and spec.required:
                raise ValidationFailed(
                    ENTITY, key, "campo obbligatorio", expected="un valore non vuoto"
                )
            to_remove.add(key)
        to_set = {k: v for k, v in provided.items() if v is not None}
        touched = [spec for spec in active_by_key.values() if spec.key in to_set]
        validated = validate_custom_fields(ENTITY, touched, to_set)
        merged = {k: v for k, v in cost.custom_fields.items() if k not in to_remove}
        merged.update(validated)
        return merged

    def _require(self, cost_id: UUID, *, include_deleted: bool = False) -> Cost:
        cost = self.repo.get(cost_id, include_deleted=include_deleted)
        if cost is None:
            raise NotFound(ENTITY, cost_id)
        return cost

    def create(self, data: CostCreate, actor: Actor) -> CostRead:
        actor.require_write("create_cost")
        self._check_importo(data.importo)
        self._check_refs(data.deal_id, data.document_id)
        self.categories.require_active(data.category_id)
        self.locks.assert_writable(ENTITY, "data", data.data)

        cost = self.repo.add(
            Cost(
                deal_id=data.deal_id,
                category_id=data.category_id,
                data=data.data,
                # The **total paid**, VAT included: under the flat-rate regime input VAT
                # is not deductible, so it is cost in every sense and recording the net
                # would understate it by 22% (§4.4).
                importo=data.importo,
                descrizione=data.descrizione,
                fornitore=data.fornitore,
                document_id=data.document_id,
                custom_fields=self._validated_custom(data.custom_fields or {}),
            )
        )
        self.activities.record(
            ENTITY,
            cost.id,
            "created",
            actor,
            {
                "importo": str(cost.importo),
                "deal_id": str(cost.deal_id) if cost.deal_id else None,
            },
        )
        self.session.commit()
        return CostRead.model_validate(cost)

    def update(self, cost_id: UUID, data: CostUpdate, actor: Actor) -> CostRead:
        actor.require_write("update_cost")
        cost = self._require(cost_id)
        changes = data.model_dump(exclude_none=True, exclude={"custom_fields"})
        if "importo" in changes:
            self._check_importo(changes["importo"])
        self._check_refs(changes.get("deal_id"), changes.get("document_id"))
        if "category_id" in changes:
            self.categories.require_active(changes["category_id"])
        self.locks.assert_writable(ENTITY, "data", cost.data, changes.get("data"))

        if data.custom_fields is not None:
            changes["custom_fields"] = self._update_custom_fields(cost, data.custom_fields)
        for key, value in changes.items():
            setattr(cost, key, value)
        self.activities.record(ENTITY, cost.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return CostRead.model_validate(cost)

    def soft_delete(self, cost_id: UUID, actor: Actor) -> None:
        actor.require_write("delete_cost")
        cost = self._require(cost_id)
        self.locks.assert_writable(ENTITY, "data", cost.data)
        cost.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, cost.id, "deleted", actor)
        self.session.commit()

    def restore(self, cost_id: UUID, actor: Actor) -> CostRead:
        actor.require_write("restore_cost")
        cost = self._require(cost_id, include_deleted=True)
        self.locks.assert_writable(ENTITY, "data", cost.data)
        was_deleted = cost.deleted_at is not None
        cost.deleted_at = None
        if was_deleted:
            self.activities.record(ENTITY, cost.id, "restored", actor)
        self.session.commit()
        return CostRead.model_validate(cost)

    def get(self, cost_id: UUID, actor: Actor) -> CostRead:
        return CostRead.model_validate(self._require(cost_id))

    # `list` stays the last method in this class -- the unconditional project rule.
    def list(self, query: CostListQuery, actor: Actor) -> CostPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return CostPage(
            items=[CostRead.model_validate(c) for c in items],
            next_cursor=items[-1].id if has_more and items else None,
        )
