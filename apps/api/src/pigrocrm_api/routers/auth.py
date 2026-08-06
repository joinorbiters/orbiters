from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserRead
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.auth.tokens import decode_token, issue_access_token, issue_refresh_token
from pigrocrm.core.errors import DomainError
from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE, ActorDep, SessionDep, SettingsDep

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name, value, httponly=True, secure=True, samesite="lax", max_age=max_age, path="/"
    )


@router.post("/login", response_model=UserRead)
def login(
    payload: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> UserRead:
    user = UserService(session).authenticate(payload.email, payload.password)
    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings),
        settings.access_token_minutes * 60,
    )
    _set_cookie(
        response,
        REFRESH_COOKIE,
        issue_refresh_token(user.id, settings),
        settings.refresh_token_days * 86400,
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


@router.post("/refresh", response_model=UserRead)
def refresh(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> UserRead:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token assente")

    # A refresh token is a credential, like the access token get_actor checks -- not
    # user-submitted form data -- so an invalid or expired one reads as 401, the same
    # way get_actor treats a bad access token, not as a generic 422 validation failure.
    try:
        payload = decode_token(token, settings, expected_type="refresh")
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token non valido") from exc
    user = UserRepository(session).get(payload.sub)
    if user is None or not user.attivo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo")

    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings),
        settings.access_token_minutes * 60,
    )
    # Rotate the refresh token on every use, so a stolen one has a short life.
    _set_cookie(
        response,
        REFRESH_COOKIE,
        issue_refresh_token(user.id, settings),
        settings.refresh_token_days * 86400,
    )
    return UserRead.model_validate(user)


@router.get("/me", response_model=UserRead)
def me(actor: ActorDep, session: SessionDep) -> UserRead:
    user = UserRepository(session).get(actor.id) if actor.id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non trovato")
    return UserRead.model_validate(user)
