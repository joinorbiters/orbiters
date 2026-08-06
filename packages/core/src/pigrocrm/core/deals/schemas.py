from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Mirrors Deal's column width (models.py). Without this, an over-length value sails
# past Pydantic, reaches flush(), and comes back as a raw sqlalchemy.exc.DataError
# (StringDataRightTruncation) -- not a subclass of IntegrityError, so no handler
# catches it, and it poisons the session. The same gap CustomerCreate's own
# *_MAX_LENGTH constants (customers/schemas.py) and PersonCreate's own (people/
# schemas.py) close -- this project has hit the class of bug often enough that it is
# now a standing global constraint, not a one-off fix.
#
# `note` is deliberately absent: it is `Text` in models.py, which has no column
# width to mirror.
NOME_MAX_LENGTH = 255


class DealCreate(BaseModel):
    nome: str = Field(max_length=NOME_MAX_LENGTH)
    customer_id: UUID
    pipeline_stage_id: UUID | None = None
    valore_previsto: Decimal | None = None
    probabilita: int | None = None
    data_chiusura_prevista: date | None = None
    owner_id: UUID | None = None
    note: str | None = None
    ore_preventivate: Decimal | None = None
    valore_preventivato: Decimal | None = None
    custom_fields: dict[str, Any] = {}


class DealUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `customer_id` and `pipeline_stage_id` are deliberately absent here, the same
    # way `code` is absent from `PipelineStageUpdate`: reassigning either through a
    # generic update would bypass the validation and probability-settling logic that
    # `create`/`move_stage` exist to enforce. `move_stage` is the only supported way
    # to change a deal's stage.
    nome: str | None = Field(default=None, max_length=NOME_MAX_LENGTH)
    valore_previsto: Decimal | None = None
    probabilita: int | None = None
    data_chiusura_prevista: date | None = None
    owner_id: UUID | None = None
    note: str | None = None
    ore_preventivate: Decimal | None = None
    valore_preventivato: Decimal | None = None
    custom_fields: dict[str, Any] | None = None


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    customer_id: UUID
    pipeline_stage_id: UUID
    valore_previsto: Decimal | None
    probabilita: int
    data_chiusura_prevista: date | None
    owner_id: UUID | None
    note: str | None
    ore_preventivate: Decimal | None
    valore_preventivato: Decimal | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DealListQuery(BaseModel):
    search: str | None = None
    customer_id: UUID | None = None
    stage_id: UUID | None = None
    custom: dict[str, Any] | None = None
    # Upper-bounded so a caller (an MCP agent especially) cannot request an
    # unbounded page; matches CustomerListQuery.limit/PersonListQuery.limit exactly.
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class DealPage(BaseModel):
    items: list[DealRead]
    next_cursor: UUID | None
