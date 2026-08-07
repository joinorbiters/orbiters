from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from pigrocrm.core.auth.refresh_service import RefreshTokenService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserRead
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.auth.tokens import decode_token, issue_access_token
from pigrocrm.core.errors import DomainError
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE, ActorDep, SessionDep, SettingsDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/auth", tags=["auth"], responses=PROBLEM_RESPONSES)


class LoginRequest(BaseModel):
    # SafeStr, not EmailStr: UserRepository.get_by_email binds `email` straight
    # into a SELECT ... WHERE email = :email, and psycopg refuses to adapt any
    # string parameter containing a NUL byte, insert or not -- the same defect
    # class as the list routers' search/stato/custom, but reachable with zero
    # credentials, since login is the one endpoint anyone can call. This is a
    # request-body field (like every Create schema's own fields), so FastAPI's
    # normal request-body validation already turns a rejection here into a clean
    # 422 with no further change needed -- unlike the query-parameter case, where
    # the parameter itself has to carry the annotation (see routers/customers.py).
    email: SafeStr
    password: str


def _set_cookie(response: Response, name: str, value: str, max_age: int, *, secure: bool) -> None:
    response.set_cookie(
        name, value, httponly=True, secure=secure, samesite="lax", max_age=max_age, path="/"
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
        secure=settings.cookie_secure,
    )
    _set_cookie(
        response,
        REFRESH_COOKIE,
        RefreshTokenService(session).issue(user.id, settings),
        settings.refresh_token_days * 86400,
        secure=settings.cookie_secure,
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    # Logging out must kill the session server-side, not just empty the browser's
    # cookie jar -- otherwise a copy of the refresh token taken before logout stays
    # valid for the rest of its 30-day life. An already-invalid or already-expired
    # token has nothing left to invalidate, so that case is not an error here: the
    # goal state ("no usable session") is already true.
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            payload = decode_token(token, settings, expected_type="refresh")
            if payload.jti is not None:
                RefreshTokenService(session).consume(payload.jti, payload.sub)
        except DomainError:
            pass
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
    if payload.jti is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token non valido")

    refresh_tokens = RefreshTokenService(session)
    # Consumed before anything else: this is what makes rotation real. Once this call
    # returns, the token just presented can never be used again -- if it had already
    # been consumed by an earlier request, this raises and, as a side effect, revokes
    # every other still-valid refresh token this user holds (see consume()'s
    # docstring): that earlier request was the legitimate rotation, so this one
    # presenting the same token again is a replay.
    try:
        refresh_tokens.consume(payload.jti, payload.sub)
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token non valido") from exc

    try:
        user = UserRepository(session).get_active(payload.sub)
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo") from exc

    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings),
        settings.access_token_minutes * 60,
        secure=settings.cookie_secure,
    )
    # A fresh token with its own row -- not a re-signing of the same claims -- because
    # the one just consumed above can never be honoured again.
    _set_cookie(
        response,
        REFRESH_COOKIE,
        refresh_tokens.issue(user.id, settings),
        settings.refresh_token_days * 86400,
        secure=settings.cookie_secure,
    )
    return UserRead.model_validate(user)


@router.get("/me", response_model=UserRead)
def me(actor: ActorDep, session: SessionDep) -> UserRead:
    user = UserRepository(session).get(actor.id) if actor.id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non trovato")
    return UserRead.model_validate(user)
