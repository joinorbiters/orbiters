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

`POST /members/lookup` is the one route here for another product rather than for a
person: PigroCRM's signup asks whether an address belongs to a member (ORB-173), under
the token the two hosts already share for the registry of spaces (ORB-142). A POST with
the address in the body, so no access log on either host writes it.
"""

import logging
import secrets
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from orbiters_api.deps import MEMBER_COOKIE, MemberDep, SenderDep, SessionDep, SettingsDep
from orbiters_api.downloads import cv_response, perk_response
from orbiters_api.ratelimit import spend_one
from orbiters_core.mail import EmailSender, Mail
from orbiters_core.members import MemberService
from orbiters_core.models import CV_MAX_BYTES
from orbiters_core.perks import GUIDE_FILENAME, PerkService, guide_bytes
from orbiters_core.schemas import (
    Ack,
    EnterRequest,
    LinkRequest,
    MemberLookup,
    MemberLookupRequest,
    MemberProfile,
    MemberUpdate,
)

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


@router.get("/me/guida")
def my_guide(member: MemberDep, session: SessionDep) -> Response:
    """The guide, to a member and to nobody else.

    `MemberDep` is the whole access rule: the perk of being in the community is that
    this answers at all, so an anonymous caller gets the same 401 as `/me` rather than
    a redirect or a teaser. The file is `orbiters_core`'s own package data, and the
    member row is not read for anything beyond having resolved. Since ORB-156 the
    download is written down first, who and when, for the admin area's counter.
    """
    PerkService(session).record_guide_download(member.id)
    return perk_response(guide_bytes(), GUIDE_FILENAME)


@router.post("/members/lookup", response_model=MemberLookup)
def lookup_member(
    payload: MemberLookupRequest,
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> MemberLookup:
    """Whether an address belongs to a freelancer in the community, and their names, for
    the one caller that holds `ORBITERS_PIGRO_REGISTRY_TOKEN`: PigroCRM's signup, which
    greets a member by name instead of asking for it (ORB-173). The same shape as the
    CRM's `GET /api/tenants/` in the other direction (ORB-142): without the token
    configured the route does not exist (404), so nothing says there is a door; with it,
    a missing or wrong bearer is a 401. An unknown address is `membro: false`, never an
    error: the hub says who is a member, not who is at the keyboard. A POST so the address
    travels in the body and not in a URL the access log would keep."""
    if not settings.pigro_registry_token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    presented = authorization.removeprefix("Bearer ").strip() if authorization else ""
    # Bytes, not str: Starlette decodes headers as latin-1 and `compare_digest` refuses a
    # `str` with a non-ASCII character, which would turn a stray byte into a 500.
    if not presented or not secrets.compare_digest(
        presented.encode("utf-8"), settings.pigro_registry_token.encode("utf-8")
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token non valido")
    return MemberService(session, settings).lookup(payload.email)


@router.post("/me/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    MemberService(session, settings).close_session(request.cookies.get(MEMBER_COOKIE))
    response.delete_cookie(MEMBER_COOKIE, path="/")
