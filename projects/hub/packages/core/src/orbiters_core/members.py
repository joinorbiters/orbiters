"""The member area: how a freelancer gets back in, and what they may change once in.

The way in is a magic link (member area spec, 2026-09-10): the person types the address
they gave the wizard, a one-time token goes out by mail, the link opens a session. No
password anywhere. Sessions are the admin's shape in a table of their own. Every change
the person makes is a comment in the row's thread (ORB-59), so the admin sees what moved
without an audit table. The service never sends a mail: it returns the one to send, and
the adapter answers the same status and body whether the address exists or not and
sends in the background; the rate limit on that route is what bounds how many timing
samples an address can collect.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from orbiters_core.comments import CommentService
from orbiters_core.config import Settings
from orbiters_core.errors import NotFound
from orbiters_core.freelancers import check_cv, cv_of
from orbiters_core.mail import Mail, magic_link_mail
from orbiters_core.models import (
    AUTORE_MAX_LENGTH,
    Freelancer,
    MagicLinkToken,
    MemberLogin,
    MemberSession,
)
from orbiters_core.schemas import CvFile, MemberProfile, MemberUpdate

ENTITY = "freelancer"
# What the comment calls each field, in the admin's language, in the wizard's order.
FIELD_LABELS: dict[str, str] = {
    "nome": "nome",
    "cognome": "cognome",
    "linkedin_url": "profilo LinkedIn",
    "tariffa_giornaliera": "tariffa giornaliera",
    "posizione": "posizione",
    "remoto": "modalità di lavoro",
    "links": "link",
}


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class MemberService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # ---- the way in ----------------------------------------------------------------

    def request_link(self, email: str) -> Mail | None:
        """The mail to send, or `None` when nobody with that address applied. Sweeps the
        person's spent and expired tokens first: nothing needs a cron."""
        row = self._by_email(email.strip().lower())
        if row is None:
            return None
        now = datetime.now(UTC)
        self.session.execute(
            delete(MagicLinkToken).where(
                MagicLinkToken.freelancer_id == row.id,
                or_(MagicLinkToken.used_at.is_not(None), MagicLinkToken.expires_at <= now),
            )
        )
        raw = secrets.token_urlsafe(32)
        self.session.add(
            MagicLinkToken(
                freelancer_id=row.id,
                token_hash=_hash(raw),
                expires_at=now + timedelta(minutes=self.settings.magic_link_minutes),
            )
        )
        self.session.commit()
        link = f"{self.settings.hub_url.rstrip('/')}/entra?t={raw}"
        return magic_link_mail(row.email, link, self.settings.magic_link_minutes)

    def enter(self, raw_token: str) -> tuple[MemberProfile, str] | None:
        """The profile and the raw session token for the cookie, or `None` for a wrong,
        spent or expired link. The token is spent by a conditional update gated on it
        still being unused, so of two requests racing on the same raw token (a mail
        scanner's prefetch against the person's own click) only one sees its row come
        back from `RETURNING` and opens a session; the other finds the token already
        spent and gets `None`. `RETURNING` rather than `rowcount`: the DBAPI's row
        count is typed on `CursorResult` only, not on the `Result` a generic `execute`
        returns."""
        if not raw_token:
            return None
        now = datetime.now(UTC)
        token = self.session.scalar(
            select(MagicLinkToken).where(MagicLinkToken.token_hash == _hash(raw_token))
        )
        if token is None or token.used_at is not None or token.expires_at <= now:
            return None
        row = self.session.get(Freelancer, token.freelancer_id)
        if row is None:
            return None
        spent = self.session.execute(
            update(MagicLinkToken)
            .where(MagicLinkToken.id == token.id, MagicLinkToken.used_at.is_(None))
            .values(used_at=now)
            .returning(MagicLinkToken.id)
        )
        if len(spent.scalars().all()) != 1:
            self.session.rollback()
            return None
        raw_session = secrets.token_urlsafe(32)
        self.session.add(
            MemberSession(
                freelancer_id=row.id, token_hash=_hash(raw_session), expires_at=self._deadline(now)
            )
        )
        # The login itself, kept after the session is gone (ORB-158): same commit, so a
        # session never exists without its login and a login never without its session.
        self.session.add(MemberLogin(freelancer_id=row.id, logged_at=now))
        self.session.commit()
        return MemberProfile.model_validate(row), raw_session

    def resolve(self, raw: str | None) -> MemberProfile | None:
        """The member behind a cookie, or `None`. Slides the expiry on every hit and
        forgets a session past its deadline the moment it is presented."""
        if not raw:
            return None
        session_row = self.session.scalar(
            select(MemberSession).where(MemberSession.token_hash == _hash(raw))
        )
        if session_row is None:
            return None
        now = datetime.now(UTC)
        if session_row.expires_at <= now:
            self.session.delete(session_row)
            self.session.commit()
            return None
        row = self.session.get(Freelancer, session_row.freelancer_id)
        if row is None:
            return None
        session_row.expires_at = self._deadline(now)
        self.session.commit()
        return MemberProfile.model_validate(row)

    def close_session(self, raw: str | None) -> None:
        if not raw:
            return
        session_row = self.session.scalar(
            select(MemberSession).where(MemberSession.token_hash == _hash(raw))
        )
        if session_row is not None:
            self.session.delete(session_row)
            self.session.commit()

    # ---- what they see and change -----------------------------------------------------

    def profile(self, freelancer_id: UUID) -> MemberProfile:
        return MemberProfile.model_validate(self._require(freelancer_id))

    def update(self, freelancer_id: UUID, data: MemberUpdate) -> MemberProfile:
        """Applies the seven answers and leaves one comment naming the ones that moved,
        signed with the person's name after the change. Nothing moved, no comment --
        unless the card was an admin's draft from a signup (ORB-155): saving it, even
        unchanged, makes it the person's (`compilata_da = "persona"`), and the thread
        says so. `stato`, `note` and the attribution are never touched here."""
        row = self._require(freelancer_id)
        changed: list[str] = []
        for field, label in FIELD_LABELS.items():
            value = getattr(data, field)
            if field == "links":
                value = list(value)
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed.append(label)
        taken_over = row.compilata_da != "persona"
        if not changed and not taken_over:
            return MemberProfile.model_validate(row)
        row.compilata_da = "persona"
        self.session.commit()
        if changed:
            self._comment(row, f"Profilo aggiornato dalla persona: {', '.join(changed)}")
        else:
            self._comment(row, "Scheda confermata dalla persona")
        return MemberProfile.model_validate(row)

    def replace_cv(
        self, freelancer_id: UUID, content: bytes, filename: str, mime: str
    ) -> MemberProfile:
        """The same check as the wizard's (`check_cv`), then the bytes replace the old
        ones and the thread says so."""
        filename, mime = check_cv(content, filename, mime)
        row = self._require(freelancer_id)
        first = row.cv_bytes is None
        row.cv_bytes, row.cv_filename, row.cv_mime, row.cv_size = (
            content,
            filename,
            mime,
            len(content),
        )
        row.compilata_da = "persona"
        self.session.commit()
        self._comment(row, "CV caricato dalla persona" if first else "CV aggiornato dalla persona")
        return MemberProfile.model_validate(row)

    def cv(self, freelancer_id: UUID) -> CvFile:
        return cv_of(self._require(freelancer_id))

    # ---- helpers ---------------------------------------------------------------------

    def _comment(self, row: Freelancer, text: str) -> None:
        author = f"{row.nome} {row.cognome}"[:AUTORE_MAX_LENGTH]
        CommentService(self.session).add(ENTITY, row.id, text, author)

    def _deadline(self, now: datetime | None = None) -> datetime:
        return (now or datetime.now(UTC)) + timedelta(days=self.settings.member_session_days)

    def _require(self, freelancer_id: UUID) -> Freelancer:
        row = self.session.get(Freelancer, freelancer_id)
        if row is None:
            raise NotFound(ENTITY, freelancer_id)
        return row

    def _by_email(self, email: str) -> Freelancer | None:
        return self.session.scalar(select(Freelancer).where(func.lower(Freelancer.email) == email))
