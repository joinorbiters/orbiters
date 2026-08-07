from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from pigrocrm.core.auth.pat_service import PatRead, PatService
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/tokens", tags=["tokens"], responses=PROBLEM_RESPONSES)

# Mirrors PersonalAccessToken.nome's column width (auth/pat_models.py: String(120)).
# Without this, an over-length value sails past Pydantic, reaches flush(), and comes
# back as a raw sqlalchemy.exc.DataError (StringDataRightTruncation) -- not a subclass
# of IntegrityError, so no handler catches it, and it poisons the session. Same class
# of gap every other Create schema in this codebase already closes (see e.g.
# CustomerCreate.RAGIONE_SOCIALE_MAX_LENGTH). `PatService.create` takes a bare `nome:
# str`, not a packages/core schema of its own (see pat_service.py), so this router's
# own request model is the only Pydantic layer standing between a caller and
# `personal_access_tokens.nome` -- both the length bound and the SafeStr NUL guard
# have to live here, not in packages/core.
NOME_MAX_LENGTH = 120


class CreateTokenRequest(BaseModel):
    nome: SafeStr = Field(max_length=NOME_MAX_LENGTH)


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
