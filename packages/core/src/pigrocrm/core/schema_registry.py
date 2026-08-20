"""One description of an entity's shape, for every adapter.

Lives in core rather than in an adapter because both the REST API and the MCP
server must answer "what fields does a customer have?" with the same answer.
Nothing in core imports this module, so pulling in the entity schemas here
creates no cycle.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from pigrocrm.core.customers.schemas import CustomerCreate
from pigrocrm.core.deals.schemas import DealCreate
from pigrocrm.core.documents.schemas import DocumentCreate
from pigrocrm.core.fields.dynamic import describe_specs
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.people.schemas import PersonCreate

ENTITY_TYPES: tuple[EntityType, ...] = ("customer", "person", "deal", "document")

CREATE_MODELS: dict[str, type[BaseModel]] = {
    "customer": CustomerCreate,
    "person": PersonCreate,
    "deal": DealCreate,
    "document": DocumentCreate,
}


def native_fields(entity_type: str) -> list[str]:
    """Derived from the Pydantic model, never hand-listed."""
    return [name for name in CREATE_MODELS[entity_type].model_fields if name != "custom_fields"]


def describe_entity(session: Session, entity_type: EntityType) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "native_fields": native_fields(entity_type),
        "custom_fields": describe_specs(FieldDefinitionService(session).specs_for(entity_type)),
    }
