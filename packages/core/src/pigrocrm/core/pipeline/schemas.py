from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StageKind = Literal["open", "won", "lost"]

# Both mirror PipelineStage's column widths (models.py). Without these, an over-length
# value sails past Pydantic, reaches flush(), and comes back as a raw
# sqlalchemy.exc.DataError (StringDataRightTruncation) instead of an ordinary
# ValidationError -- the same class of gap fields/schemas.py's KEY_MAX_LENGTH closes.
# `nome` is the fourth time this project has hit an unbounded string column that can
# poison the session this way; `code` was closed in fix round 1, `nome` predates that
# round and is closed here.
NOME_MAX_LENGTH = 60
CODE_MAX_LENGTH = 30


class PipelineStageCreate(BaseModel):
    nome: str = Field(max_length=NOME_MAX_LENGTH)
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

    nome: str | None = Field(default=None, max_length=NOME_MAX_LENGTH)
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
