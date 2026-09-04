"""The REST surface of slice 9B's Drive credential -- the Drive twin of `routers/gmail.py`.

Everything that module's docstring says about the settings page applies here
unchanged, for the same reasons: `GET /account` answers 200 even when Google is not
configured, because "this installation has no Google" and "you have not connected
Drive yet" are both states with no account and no error to report, and the settings
page has to render the first without the SPA treating the response as a failed query.
The OAuth callback is a browser navigation and always ends on the settings page with
one of three outcome codes, never with Google's own `error` (English, and occasionally
the client id) and never with a `Conflict`'s problem document (which would strand the
user outside the SPA at the end of a consent flow).

One thing here is *not* a mirror of Gmail: there is no `/sync`, `/backfill` or
`/messages`. Slice 9B is only the credential and its two configuration fields
(`root_folder_ids`, `storage_folder_id`); reading and writing files through it is 9C/9D's
surface, built on the `usable()` gate `drive/account.py` already exposes.
"""

import threading

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings, gmail_configured
from pigrocrm.core.drive.account import GoogleDriveAccountService
from pigrocrm.core.drive.oauth import GoogleDriveOAuthService
from pigrocrm.core.drive.schemas import DriveHealth, DriveRootsUpdate, GoogleDriveAccountRead
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport
from pigrocrm_api.deps import ActorDep, SessionDep, SettingsDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/drive", tags=["drive"], responses=PROBLEM_RESPONSES)

# Where the SPA renders the outcome of a consent flow -- the same fixed table of three
# codes as `routers/gmail.py`'s own constants, on Drive's own settings tab so that
# nothing an attacker appends to this URL can put words of their own on the screen.
_SETTINGS_PAGE = "/app/impostazioni/drive"
_ESITO_COLLEGATO = "collegato"
_ESITO_NEGATO = "negato"
_ESITO_ERRORE = "errore"

# One `GoogleTokenClient` per process, keyed by the OAuth client it authenticates as --
# shared with `routers/gmail.py` for the identical reason its own module docstring
# gives: one Google OAuth client authenticates both credentials, so the access-token
# cache the client keeps is the same cache either flow should be reading from. A second,
# Drive-only dict here would just be a second cache that a Gmail sync had already warmed
# and a Drive one would cold-start against for no reason.
_token_clients: dict[str, GoogleTokenClient] = {}
_token_clients_lock = threading.Lock()

_ACCOUNT_PATH = "/account"


def token_client(settings: Settings) -> GoogleTokenClient:
    client = _token_clients.get(settings.google_client_id)
    if client is None:
        with _token_clients_lock:
            client = _token_clients.get(settings.google_client_id)
            if client is None:
                client = GoogleTokenClient(
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    transport=GmailTransport(),
                )
                _token_clients[settings.google_client_id] = client
    return client


def _oauth(session: Session, settings: Settings) -> GoogleDriveOAuthService:
    return GoogleDriveOAuthService(session, settings=settings, tokens=token_client(settings))


@router.get(_ACCOUNT_PATH, response_model=DriveHealth)
def read_account(session: SessionDep, actor: ActorDep, settings: SettingsDep) -> DriveHealth:
    """200 even when Drive is not configured -- see the module docstring."""
    if not gmail_configured(settings):
        return DriveHealth(
            account=None, banner=None, banner_text=None, missing_scopes=[], configured=False
        )
    return GoogleDriveAccountService(session, settings=settings).health(actor)


@router.get("/oauth/start")
def start_oauth(session: SessionDep, actor: ActorDep, settings: SettingsDep) -> RedirectResponse:
    return RedirectResponse(_oauth(session, settings).start(actor), status_code=307)


@router.get("/oauth/callback")
def finish_oauth(
    session: SessionDep,
    actor: ActorDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error is not None or code is None or state is None:
        return _back_to_settings(_ESITO_NEGATO)
    try:
        _oauth(session, settings).complete(code=code, state=state, actor=actor)
    except Conflict:
        # Every refusal `complete` can produce is a `Conflict` -- a replayed or expired
        # state, a Drive that points at a different Google identity than the connected
        # mailbox, an account already connected to someone else, a grant Google answered
        # with no identity. All of them arrive here through a browser redirect, so all
        # of them end on the settings page, which re-reads `GET /account` and shows the
        # true state.
        return _back_to_settings(_ESITO_ERRORE)
    return _back_to_settings(_ESITO_COLLEGATO)


def _back_to_settings(esito: str) -> RedirectResponse:
    return RedirectResponse(f"{_SETTINGS_PAGE}?esito={esito}", status_code=307)


@router.delete(_ACCOUNT_PATH, status_code=204)
def disconnect(session: SessionDep, actor: ActorDep, settings: SettingsDep) -> None:
    """No `elimina_messaggi` flag: Drive stores no correspondence of its own, so there is
    nothing here for one to name -- see `GoogleDriveOAuthService.disconnect`."""
    _oauth(session, settings).disconnect(actor)


@router.patch("/account/roots", response_model=GoogleDriveAccountRead)
def update_roots(
    payload: DriveRootsUpdate, session: SessionDep, actor: ActorDep, settings: SettingsDep
) -> GoogleDriveAccountRead:
    """No `gmail_configured` gate, on purpose: `set_roots` reaches the row through
    `_present`, which lets a revoked or expired credential still be reconfigured -- the
    person most likely to be on this screen is the one trying to recover from exactly
    that state, and the route must not add a gate the service deliberately omits."""
    return GoogleDriveAccountService(session, settings=settings).set_roots(payload, actor)
