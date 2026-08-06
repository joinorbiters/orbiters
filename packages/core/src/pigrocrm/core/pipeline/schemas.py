from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StageKind = Literal["open", "won", "lost"]

# Mirrors PipelineStage.code's column width (models.py). Without this, an over-length
# code sails past Pydantic, reaches flush(), and comes back as a raw
# sqlalchemy.exc.DataError (StringDataRightTruncation) instead of an ordinary
# ValidationError -- the same class of gap fields/schemas.py's KEY_MAX_LENGTH closes.
CODE_MAX_LENGTH = 30


class PipelineStageCreate(BaseModel):
    nome: str
    posizione: int
    probabilita_default: int = 0
    tipo: StageKind = "open"
    code: str | None = Field(default=None, max_length=CODE_MAX_LENGTH)


class PipelineStageUpdate(BaseModel):
    """`code` is deliberately absent, the same way `field_type` is absent from
    `FieldDefinitionUpdate`: it is identity, not a label, and changing it after
    creation has no correct meaning. `seed_defaults`'s idempotency across a rename
    depends on `code` never moving once set."""

    model_config = ConfigDict(extra="forbid")

    nome: str | None = None
    posizione: int | None = None
    probabilita_default: int | None = None
    tipo: StageKind | None = None


class PipelineStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    posizione: int
    probabilita_default: int
    tipo: StageKind
    code: str | None
