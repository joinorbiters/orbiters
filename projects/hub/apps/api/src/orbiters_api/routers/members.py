"""The member area's API: a link in, a cookie out, one row behind it.

`POST /auth/link` answers 202 whether the address applied or not, and the mail goes out
in a background task after the response, so neither the status nor the timing nor a
provider failure says whether an address is known. `POST /auth/enter` spends the token
and sets `orbiters_user`. Everything under `/me` reads the row from the session and
never from the URL: there is no `/me/{id}`.

`POST /auth/link`, `POST /auth/enter` and `PUT /me/cv` all spend from the public rate
limit: the first two because they are unauthenticated by design, `PUT /me/cv` because
FastAPI reads its multipart body while resolving parameters, before `MemberDep` gets a
chance to reject an anonymous caller with a 401.
"""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from orbiters_api.deps import MEMBER_COOKIE, MemberDep, SenderDep, SessionDep, SettingsDep
from orbiters_api.downloads import cv_response
from orbiters_api.ratelimit import spend_one
from orbiters_core.mail import EmailSender, Mail
from orbiters_core.members import MemberService
from orbiters_core.models import CV_MAX_BYTES
from orbiters_core.schemas import Ack, EnterRequest, LinkRequest, MemberProfile, MemberUpdate

router = APIRouter(prefix="/api/hub", tags=["hub-member"])

_log = logging.getLogger(__name__)


def _send(sender: EmailSender, mail: Mail) -> None:
    """Runs after the response. A refusal is logged without the address or the key: the
    operator needs to know the provider said no, not to whom."""
    if not sender.send(mail):
        _log.warning("the magic link mail was refused by the provider")


@router.post("/auth/link", response_model=Ack, status_code=status.HTTP_202_ACCEPTED)
def request_link(
    payload: LinkRequest,
    request: Request,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    sender: SenderDep,
) -> Ack:
    spend_one(request)
    if sender is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "L'accesso via email non è ancora attivo. Riprova più avanti.",
        )
    mail = MemberService(session, settings).request_link(payload.email)
    if mail is not None:
        background.add_task(_send, sender, mail)
    return Ack()


@router.post("/auth/enter", response_model=MemberProfile)
def enter(
    payload: EnterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> MemberProfile:
    spend_one(request)
    outcome = MemberService(session, settings).enter(payload.token)
    if outcome is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Link non valido o scaduto. Chiedine un altro."
        )
    profile, raw = outcome
    response.set_cookie(
        MEMBER_COOKIE,
        raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.member_session_days * 86400,
        path="/",
    )
    return profile


@router.get("/me", response_model=MemberProfile)
def me(member: MemberDep) -> MemberProfile:
    return member


@router.patch("/me", response_model=MemberProfile)
def update_me(
    member: MemberDep, session: SessionDep, settings: SettingsDep, payload: MemberUpdate
) -> MemberProfile:
    return MemberService(session, settings).update(member.id, payload)


@router.put("/me/cv", response_model=MemberProfile)
def replace_my_cv(
    member: MemberDep,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    cv: Annotated[UploadFile, File()],
) -> MemberProfile:
    # The multipart body is already parsed by the time any dependency runs, so an
    # anonymous caller has made the server read it regardless of the 401 that follows;
    # charge it to the public bucket and never materialise more than the limit `check_cv`
    # enforces anyway.
    spend_one(request)
    content = cv.file.read(CV_MAX_BYTES + 1)
    return MemberService(session, settings).replace_cv(
        member.id, content, cv.filename or "", cv.content_type or ""
    )


@router.get("/me/cv")
def my_cv(member: MemberDep, session: SessionDep, settings: SettingsDep) -> Response:
    cv = MemberService(session, settings).cv(member.id)
    return cv_response(cv)


@router.post("/me/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    MemberService(session, settings).close_session(request.cookies.get(MEMBER_COOKIE))
    response.delete_cookie(MEMBER_COOKIE, path="/")
