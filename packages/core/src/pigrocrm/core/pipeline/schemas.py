from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

StageKind = Literal["open", "won", "lost"]


class PipelineStageCreate(BaseModel):
    nome: str
    posizione: int
    probabilita_default: int = 0
    tipo: StageKind = "open"


class PipelineStageUpdate(BaseModel):
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
