from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from pigrocrm.core.auth.refresh_service import RefreshTokenService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserRead
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.auth.tokens import decode_token, issue_access_token
from pigrocrm.core.errors import DomainError, ValidationFailed
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE, ActorDep, SessionDep, SettingsDep
from pigrocrm_api.errors import PROBLEM_RESPONSES
from pigrocrm_api.tenancy import cookie_path

router = APIRouter(prefix="/api/auth", tags=["auth"], responses=PROBLEM_RESPONSES)

# STATUS_BY_CODE (pigrocrm_api/errors.py) maps ValidationFailed to 422 for every other
# endpoint, correctly -- there it means "the body was well-formed but violated a
# domain rule." Here it would mean something else entirely: UserService.authenticate
# raises this same exception class for wrong credentials, which is "not authenticated,"
# the same category refresh (below) and deps.get_actor already answer with 401 for an
# invalid refresh/access token. Router-level, not a STATUS_BY_CODE change, because this
# is specific to what ValidationFailed means at this one call site, not a
# reclassification of the error code everywhere else it is raised.
#
# PROBLEM_RESPONSES (attached to the whole router above) has no 401 entry, so
# without a route-level addition login's OpenAPI documentation would stay silent
# about a status code it can now actually return, and slice 1B's generated
# TypeScript client would type this response as `unknown` -- exactly the kind of
# silent client-generation gap _domain_and_request_validation_response above already
# had to fix once for 422. FastAPI merges a route's own `responses=` with the
# router's (see APIRouter.post/_combined_responses in fastapi/routing.py), so this
# only adds 401 here without touching the shared dict every other route relies on.
# (`me` and `refresh` need the same treatment, for a different, more load-bearing
# reason -- see `_UNAUTHENTICATED_RESPONSE` just below.)
_LOGIN_UNAUTHORIZED_RESPONSE: dict[str, Any] = {
    "description": (
        "Email o password non corrette, oppure l'utente è disattivato -- lo stesso "
        "messaggio identico in tutti e tre i casi, così la risposta stessa non "
        "rivela quale sia la causa reale."
    ),
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
                "required": ["detail"],
            }
        }
    },
}

# `me` and `refresh` both reach 401 the same way login does above -- deps.get_actor or
# this router's own token checks raising a plain HTTPException, never a DomainError --
# so PROBLEM_RESPONSES (application/problem+json) would misdocument this exactly as
# _LOGIN_UNAUTHORIZED_RESPONSE above had to fix once already. One shared entry, not one
# per route: unlike login's single fixed message, these two cover several distinct
# causes each (get_actor: no cookie at all, an expired/invalid access token, a user
# deactivated after the token was issued, an unrecognised bearer PAT; refresh: no
# refresh cookie, an invalid/expired refresh token, a replayed/already-consumed token,
# a now-inactive user) -- but every one of them means the same thing to a caller: the
# session is gone, not "you sent something malformed." That is *more* load-bearing for
# a generated client than login's own 401: this is the routine "session expired" signal
# a frontend auth layer branches on programmatically (try /refresh once, then redirect
# to /login), where login's error is hand-written UX regardless of how precisely it is
# typed. `logout` deliberately has no entry here -- it has no actor dependency and is
# idempotent by design (see its own docstring), so it cannot structurally produce a 401
# the way these two can; documenting one anyway would claim a response this route can
# never send.
_UNAUTHENTICATED_RESPONSE: dict[str, Any] = {
    "description": (
        "Non autenticato: il cookie di sessione è assente, scaduto o non valido, "
        "oppure l'utente non è più attivo. Il client deve trattarlo come sessione "
        "terminata (ritentare /api/auth/refresh e poi reindirizzare al login), non "
        "come un errore da ripetere."
    ),
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
                "required": ["detail"],
            }
        }
    },
}


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


def _set_cookie(
    response: Response, name: str, value: str, max_age: int, *, secure: bool, path: str = "/"
) -> None:
    response.set_cookie(
        name, value, httponly=True, secure=secure, samesite="lax", max_age=max_age, path=path
    )


@router.post("/login", response_model=UserRead, responses={401: _LOGIN_UNAUTHORIZED_RESPONSE})
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> UserRead:
    # Same message regardless of which of the three the domain layer detected (unknown
    # email, wrong password, deactivated user) -- UserService.authenticate already
    # raises one identical ValidationFailed for all three, on purpose, so there is
    # nothing here that could distinguish them even if this wanted to.
    try:
        user = UserService(session).authenticate(payload.email, payload.password)
    except ValidationFailed as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenziali non valide") from exc
    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings),
        settings.access_token_minutes * 60,
        secure=settings.cookie_secure,
        path=cookie_path(request),
    )
    _set_cookie(
        response,
        REFRESH_COOKIE,
        RefreshTokenService(session).issue(user.id, settings),
        settings.refresh_token_days * 86400,
        secure=settings.cookie_secure,
        path=cookie_path(request),
    )
    return user


def _every_cookie_value(request: Request, name: str) -> list[str]:
    """Every value the browser sent under `name`, not only the one `request.cookies`
    keeps.

    A browser holds one cookie per (name, domain, path), and it sends all of them that
    match: a session opened at `/` before the root got its own name, and the one opened
    at `/humancraft/` after, arrive as two `refresh_token=` pairs in one header. The
    `SimpleCookie` parser behind `request.cookies` keeps the last of them, so a logout
    that read only that one left the other alive. Parsed by hand because the values are
    JWTs -- no `;`, no `=` beyond the first, nothing to quote."""
    header = request.headers.get("cookie", "")
    values: list[str] = []
    for pair in header.split(";"):
        key, sep, value = pair.strip().partition("=")
        if sep and key.strip() == name and value:
            values.append(value.strip())
    return values


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    # Logging out must kill the session server-side, not just empty the browser's
    # cookie jar -- otherwise a copy of the refresh token taken before logout stays
    # valid for the rest of its life, which `refresh_token_days` puts at six months by
    # default (T1 raised it from thirty days). An already-invalid or already-expired
    # token has nothing left to invalidate, so that case is not an error here: the
    # goal state ("no usable session") is already true.
    #
    # Every refresh token the browser presented, not the first: see
    # `_every_cookie_value`. Consuming one that was already consumed revokes the rest
    # of this user's tokens as a replay (`RefreshTokenService.consume`), which on a
    # logout is the right outcome too -- the person asked for no usable session.
    refresh_tokens = RefreshTokenService(session)
    for token in _every_cookie_value(request, REFRESH_COOKIE):
        try:
            payload = decode_token(token, settings, expected_type="refresh")
            if payload.jti is not None:
                refresh_tokens.consume(payload.jti, payload.sub)
        except DomainError:
            pass
    # Deleted at the path the request wore and, when that is a space's or the root's
    # own name, at `/` as well: a cookie is only ever removed by a Set-Cookie with the
    # same path, and a browser that still holds the pair a plain `/app/login` set
    # before the prefix existed would otherwise keep sending it -- which is a session
    # the person just said they do not want.
    paths = {cookie_path(request), "/"}
    for path in sorted(paths, key=len, reverse=True):
        response.delete_cookie(ACCESS_COOKIE, path=path)
        response.delete_cookie(REFRESH_COOKIE, path=path)


@router.post("/refresh", response_model=UserRead, responses={401: _UNAUTHENTICATED_RESPONSE})
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
    # Rotated before anything else: this is what makes rotation real. Once this call
    # returns, the token just presented can never be used again -- if it had already
    # been consumed by an earlier request, this either hands back that request's own
    # successor (the two-tabs case, inside refresh_service.REFRESH_GRACE_SECONDS)
    # or raises and, as a side effect, revokes every other still-valid refresh token
    # this user holds: that earlier request was the legitimate rotation, so this one
    # presenting the same token again long afterwards is a replay. See
    # `RefreshTokenService.rotate` for where that line is drawn -- this router does
    # not know, and must not know, which of the two branches answered it.
    try:
        rotation = refresh_tokens.rotate(payload.jti, payload.sub, settings)
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token non valido") from exc

    try:
        user = UserRepository(session).get_active(payload.sub)
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo") from exc

    # One cookie-setting path for both branches, deliberately: a grace-window answer
    # that differed from an ordinary rotation in any observable way -- a header, a
    # max-age, an order -- would tell a caller how long ago some other tab refreshed,
    # and would be a second code path on the endpoint that must never fail.
    #
    # `issued_at` is the rotation's own instant, not "now": signing the access token
    # from it is what makes the second tab's pair identical to the first's rather than
    # merely equivalent (see `issue_access_token`). For an ordinary rotation the two
    # are the same instant anyway, microseconds apart at worst.
    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings, issued_at=rotation.issued_at),
        settings.access_token_minutes * 60,
        secure=settings.cookie_secure,
        path=cookie_path(request),
    )
    # A fresh token with its own row -- not a re-signing of the same claims -- because
    # the one just rotated above can never be honoured again.
    _set_cookie(
        response,
        REFRESH_COOKIE,
        rotation.refresh_token,
        settings.refresh_token_days * 86400,
        secure=settings.cookie_secure,
        path=cookie_path(request),
    )
    return UserRead.model_validate(user)


@router.get("/me", response_model=UserRead, responses={401: _UNAUTHENTICATED_RESPONSE})
def me(actor: ActorDep, session: SessionDep) -> UserRead:
    user = UserRepository(session).get(actor.id) if actor.id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non trovato")
    return UserRead.model_validate(user)
