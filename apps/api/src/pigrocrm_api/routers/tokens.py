from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from pigrocrm.core.auth.pat_service import PatRead, PatService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

# Mirrors PersonalAccessToken.nome's column width (auth/pat_models.py: String(120)).
# Without this, an over-length value sails past Pydantic, reaches flush(), and comes
# back as a raw sqlalchemy.exc.DataError (StringDataRightTruncation) -- not a subclass
# of IntegrityError, so no handler catches it, and it poisons the session. Same class
# of gap every other Create schema in this codebase already closes (see e.g.
# CustomerCreate.RAGIONE_SOCIALE_MAX_LENGTH).
NOME_MAX_LENGTH = 120


class CreateTokenRequest(BaseModel):
    nome: str = Field(max_length=NOME_MAX_LENGTH)


class CreatedToken(PatRead):
    """The only response in the whole API that carries the raw token. It is shown
    once, at creation, and never again."""

    token: str


@router.post("", response_model=CreatedToken, status_code=status.HTTP_201_CREATED)
def create(data: CreateTokenRequest, session: SessionDep, actor: ActorDep) -> CreatedToken:
    record, raw = PatService(session).create(data.nome, actor)
    return CreatedToken(**record.model_dump(), token=raw)


@router.get("", response_model=list[PatRead])
def list_tokens(session: SessionDep, actor: ActorDep) -> list[PatRead]:
    return PatService(session).list(actor)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(token_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    PatService(session).revoke(token_id, actor)
