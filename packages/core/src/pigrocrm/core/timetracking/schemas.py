"""Minimal stand-ins for Task 4A-3 (`EntityType` gains `time_entry` and `cost`).

`schema_registry.CREATE_MODELS` needs a real Pydantic class per entity type --
`native_fields(entity_type)` derives its answer from `model_fields`, so without a
class here it raises `KeyError` for these two new types instead of the empty-list-
minus-guard answer A13's guard (`fields/service.py`) needs.

Task 4A-5 owns the authoritative version of this module: the ORM models
(`TimeEntry`, `Cost`, `CostCategory`, `PeriodLock`), the migration, and the full
schema set (`TimeEntryUpdate`, `TimeEntryRead`, `TimeEntryListQuery`, `TimeEntryPage`,
the `Cost*` equivalents, `RateOrigin`, and friends) bound to the real `Numeric(p, s)`
column widths (`money.py`, also 4A-5's). Field names here already match the columns
4A-5's plan commits to; only the exact numeric bounds are deferred to it. Replace,
don't merely extend, these two classes when that task lands.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from pigrocrm.core.validation import SafeStr

# `descrizione` is `Text` in the future model (no column width to mirror), but an
# unbounded string still sails past Pydantic straight to the database -- bounding it
# here is the same standing defence every other Create schema in this package
# applies to its own free-text fields.
DESCRIZIONE_MAX_LENGTH = 2000
FORNITORE_MAX_LENGTH = 200


class TimeEntryCreate(BaseModel):
    deal_id: UUID
    user_id: UUID
    data: date
    ore: Decimal
    descrizione: SafeStr = Field(max_length=DESCRIZIONE_MAX_LENGTH)
    fatturabile: bool = True
    note_interne: SafeStr | None = Field(default=None, max_length=DESCRIZIONE_MAX_LENGTH)


class CostCreate(BaseModel):
    deal_id: UUID | None = None
    category_id: UUID
    data: date
    importo: Decimal
    descrizione: SafeStr = Field(max_length=DESCRIZIONE_MAX_LENGTH)
    fornitore: SafeStr | None = Field(default=None, max_length=FORNITORE_MAX_LENGTH)
