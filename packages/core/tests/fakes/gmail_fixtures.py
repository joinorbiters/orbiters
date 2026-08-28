"""Builders every 5B test needs: a user, a connected account with a sealed refresh
token, and a service wired to a `FakeGmail` through the transport seam.

A module under `fakes/` rather than a `conftest.py` helper, for the reason the
`extract_pdf_text` fixture states at length: this repository has three test roots, none
with an `__init__.py`, so `conftest` is an ambiguous top-level module name and
`from conftest import ...` binds to whichever root pytest imported first. `fakes` is a
real package and `fakes.gmail_fixtures` is unambiguous however the roots are combined.
"""

import base64
from uuid import uuid4

from sqlalchemy.orm import Session

from fakes.fake_gmail import FakeGmail
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.gmail.crypto import seal
from pigrocrm.core.gmail.models import GoogleAccount
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES
from pigrocrm.core.gmail.sync import GmailSyncService
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport

TOKEN_KEY = b"k" * 32
REFRESH_TOKEN = "1//0gFixtureRefreshToken"
MAILBOX = "io@example.it"


def gmail_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret": "x" * 32,
        "google_client_id": "cid.apps.googleusercontent.com",
        "google_client_secret": "the-secret",
        "google_token_key": base64.b64encode(TOKEN_KEY).decode(),
        "public_url": "https://crm.example.it",
        # `_env_file: None` so a developer's own .env cannot change what these tests
        # assert -- the settings under test are exactly the ones written here.
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def connected_account(
    session: Session,
    *,
    email_address: str = MAILBOX,
    scopes: tuple[str, ...] = REQUESTED_SCOPES,
    status: str = "active",
) -> GoogleAccount:
    """A user with a mailbox already connected: the state every sync test starts from.

    The refresh token is really sealed, with the same key `gmail_settings` publishes, so
    the token refresh under test runs its real `unseal` rather than reading a plaintext
    column that production never has.
    """
    user = User(
        email=f"user-{uuid4().hex[:8]}@example.it",
        nome="Owner",
        password_hash="x",
        ruolo="admin",
        attivo=True,
    )
    session.add(user)
    session.flush()
    ciphertext, nonce = seal(REFRESH_TOKEN, TOKEN_KEY)
    account = GoogleAccount(
        user_id=user.id,
        google_sub=f"sub-{user.id}",
        email_address=email_address,
        refresh_token_ciphertext=ciphertext,
        refresh_token_nonce=nonce,
        scopes_granted=list(scopes),
        status=status,
    )
    session.add(account)
    session.flush()
    return account


def actor_for(account: GoogleAccount) -> Actor:
    return Actor(id=account.user_id, type="user", role="admin")


def sync_service(
    session: Session, fake: FakeGmail, *, settings: Settings | None = None
) -> GmailSyncService:
    resolved = settings or gmail_settings()
    transport = GmailTransport(http=fake, sleep=lambda _: None)
    return GmailSyncService(
        session,
        settings=resolved,
        transport=transport,
        tokens=GoogleTokenClient(
            client_id=resolved.google_client_id,
            client_secret=resolved.google_client_secret,
            transport=transport,
        ),
    )
