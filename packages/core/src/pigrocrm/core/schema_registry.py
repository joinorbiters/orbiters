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
from pigrocrm.core.invoices.schemas import InvoiceCreate
from pigrocrm.core.people.schemas import PersonCreate

ENTITY_TYPES: tuple[EntityType, ...] = ("customer", "person", "deal", "document", "invoice")

CREATE_MODELS: dict[str, type[BaseModel]] = {
    "customer": CustomerCreate,
    "person": PersonCreate,
    "deal": DealCreate,
    "document": DocumentCreate,
    "invoice": InvoiceCreate,
}

# Native columns an entity has that its Create schema does *not* declare, because they
# are derived or set only by a dedicated method. Empty for the four entities whose
# writable surface is their whole surface; non-empty for `invoice`, whose fiscal
# columns are computed at emission and are exactly the names an administrator would
# slugify into by accident ("Totale" -> `totale`).
#
# A13 remains open: `FieldDefinitionService.create` still compares a slugified label
# only against other definitions and never calls this function at all. Making the list
# complete does not close that hole -- it makes the data the fix will read correct, so
# that closing it in slice 1A protects the fiscal columns too rather than only the six
# names `InvoiceCreate` happens to declare.
EXTRA_NATIVE_FIELDS: dict[str, tuple[str, ...]] = {
    "customer": (),
    "person": (),
    "deal": (),
    "document": (),
    "invoice": (
        "anno",
        "numero",
        "riferimento",
        "stato",
        "data_emissione",
        "data_scadenza",
        "tipo_documento",
        "divisa",
        "imponibile",
        "imposta",
        "bollo",
        "totale",
        "stato_pagamento",
        "data_incasso",
        "trasmessa_esternamente_il",
        "annullata_il",
        "motivo_annullamento",
        "origine_proforma_id",
    ),
}


def native_fields(entity_type: str) -> list[str]:
    """Derived from the Pydantic model, never hand-listed -- plus the columns that
    model cannot declare (see EXTRA_NATIVE_FIELDS). Order is stable: derived first, in
    field-definition order, then the extras in declaration order, so a caller can
    diff two runs."""
    derived = [name for name in CREATE_MODELS[entity_type].model_fields if name != "custom_fields"]
    extra = [name for name in EXTRA_NATIVE_FIELDS.get(entity_type, ()) if name not in derived]
    return derived + extra


def describe_entity(session: Session, entity_type: EntityType) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "native_fields": native_fields(entity_type),
        "custom_fields": describe_specs(FieldDefinitionService(session).specs_for(entity_type)),
    }
