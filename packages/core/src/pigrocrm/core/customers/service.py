import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.customers.repository import CustomerRepository
from pigrocrm.core.customers.schemas import (
    CustomerCreate,
    CustomerListQuery,
    CustomerPage,
    CustomerRead,
    CustomerUpdate,
)
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields

# Typed as the fields module's own EntityType (not a bare `str`) so that passing it
# straight into `specs_for` type-checks under mypy strict -- a plain `ENTITY = "customer"`
# widens to `str` at the module level, which `specs_for(entity_type: EntityType)` then
# rejects. Every other call site here (NotFound, ValidationFailed, Conflict,
# ActivityService.record, validate_custom_fields) only asks for `str`, so the narrower
# type costs nothing there.
ENTITY: EntityType = "customer"
PARTITA_IVA_RE = re.compile(r"^\d{11}$")
CODICE_SDI_LENGTH = 7


def _check_fiscal(data: dict[str, Any]) -> None:
    piva = data.get("partita_iva")
    if piva and not PARTITA_IVA_RE.match(piva):
        raise ValidationFailed(
            ENTITY, "partita_iva", "deve essere di 11 cifre", expected="11 cifre numeriche"
        )
    sdi = data.get("codice_sdi")
    if sdi and len(sdi) != CODICE_SDI_LENGTH:
        raise ValidationFailed(
            ENTITY, "codice_sdi", "deve essere di 7 caratteri", expected="7 caratteri"
        )


class CustomerService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CustomerRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def create(self, data: CustomerCreate, actor: Actor) -> CustomerRead:
        actor.require_write("create_customer")
        payload = data.model_dump()
        _check_fiscal(payload)
        payload["custom_fields"] = self._validated_custom(payload.get("custom_fields") or {})

        customer = self.repo.add(Customer(**payload))
        self.activities.record(
            ENTITY, customer.id, "created", actor, {"ragione_sociale": customer.ragione_sociale}
        )
        self.session.commit()
        return CustomerRead.model_validate(customer)

    def update(self, customer_id: UUID, data: CustomerUpdate, actor: Actor) -> CustomerRead:
        actor.require_write("update_customer")
        customer = self.repo.get(customer_id)
        if customer is None:
            raise NotFound(ENTITY, customer_id)

        changes = data.model_dump(exclude_none=True)
        _check_fiscal(changes)
        if "custom_fields" in changes:
            merged = {**customer.custom_fields, **changes["custom_fields"]}
            changes["custom_fields"] = self._validated_custom(merged)
        for key, value in changes.items():
            setattr(customer, key, value)

        self.activities.record(ENTITY, customer.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return CustomerRead.model_validate(customer)

    def get(self, customer_id: UUID, actor: Actor) -> CustomerRead:
        customer = self.repo.get(customer_id)
        if customer is None:
            raise NotFound(ENTITY, customer_id)
        return CustomerRead.model_validate(customer)

    def list(self, query: CustomerListQuery, actor: Actor) -> CustomerPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return CustomerPage(
            items=[CustomerRead.model_validate(c) for c in items],
            next_cursor=items[-1].id if has_more and items else None,
        )

    def soft_delete(self, customer_id: UUID, actor: Actor) -> None:
        """Sets deleted_at. No physical delete exists in this slice: a misread
        instruction from an agent must be reversible."""
        actor.require_write("delete_customer")
        customer = self.repo.get(customer_id)
        if customer is None:
            raise NotFound(ENTITY, customer_id)

        active_deals = self.repo.count_active_deals(customer_id)
        if active_deals:
            raise Conflict(
                ENTITY,
                "il cliente ha deal attivi: archivia prima i deal",
                active_deals=active_deals,
            )

        customer.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, customer.id, "deleted", actor)
        self.session.commit()

    def restore(self, customer_id: UUID, actor: Actor) -> CustomerRead:
        actor.require_write("restore_customer")
        customer = self.repo.get(customer_id, include_deleted=True)
        if customer is None:
            raise NotFound(ENTITY, customer_id)
        customer.deleted_at = None
        self.activities.record(ENTITY, customer.id, "restored", actor)
        self.session.commit()
        return CustomerRead.model_validate(customer)
