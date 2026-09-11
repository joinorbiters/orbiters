"""Freelancers: the wizard's applications, what an admin does with them, and since
ORB-155 the card an admin writes from a signup for the person to complete."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Subquery, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbiters_core.comments import CommentService
from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.models import (
    CV_MAX_BYTES,
    FREELANCER_STATES,
    UTM_COLUMNS,
    Freelancer,
    MemberLogin,
    Signup,
)
from orbiters_core.schemas import (
    CvFile,
    FreelancerCreate,
    FreelancerDraft,
    FreelancerList,
    FreelancerRead,
    StatusChange,
)

ENTITY = "freelancer"
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 500
PDF_MAGIC = b"%PDF-"


def check_cv(content: bytes, filename: str, mime: str) -> tuple[str, str]:
    """A PDF, at most `CV_MAX_BYTES`, or a refusal naming the field.

    Decided on the bytes, never on the declared type alone: a browser says whatever the
    extension suggests, and the five bytes every PDF starts with are what the file is.
    Returns the filename and mime as they will be stored -- the mime normalised to the
    one type the bytes proved.
    """
    if not content:
        raise ValidationFailed(ENTITY, "cv", "serve il CV, in PDF")
    if len(content) > CV_MAX_BYTES:
        raise ValidationFailed(ENTITY, "cv", "il CV può pesare al massimo 5 MB")
    if not content.startswith(PDF_MAGIC):
        raise ValidationFailed(ENTITY, "cv", "il CV deve essere un PDF")
    name = (filename or "cv.pdf").strip().replace("\\", "/").rsplit("/", 1)[-1][:255] or "cv.pdf"
    return name, "application/pdf" if mime in (
        "",
        "application/pdf",
        "application/octet-stream",
    ) else "application/pdf"


def cv_of(row: Freelancer) -> CvFile:
    """The stored CV as a download, or `NotFound("cv", ...)` on a card born from a
    signup that the person has not completed yet (ORB-155). Shared with the member
    area, so the two downloads answer the same thing to the same row."""
    if row.cv_bytes is None or row.cv_filename is None or row.cv_mime is None:
        raise NotFound("cv", row.id)
    return CvFile(filename=row.cv_filename, mime=row.cv_mime, content=row.cv_bytes)


def _logins_per_card() -> Subquery:
    """How many times each card's owner entered and when last (ORB-158), as one grouped
    subquery the list joins once: two hundred people are not two hundred counts."""
    return (
        select(
            MemberLogin.freelancer_id,
            func.count().label("accessi"),
            func.max(MemberLogin.logged_at).label("ultimo_accesso"),
        )
        .group_by(MemberLogin.freelancer_id)
        .subquery()
    )


def _read_with_logins(
    row: Freelancer, accessi: int | None, ultimo: datetime | None
) -> FreelancerRead:
    read = FreelancerRead.model_validate(row)
    read.accessi = accessi or 0
    read.ultimo_accesso = ultimo
    return read


class FreelancerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def apply(
        self, data: FreelancerCreate, cv: bytes, cv_filename: str, cv_mime: str
    ) -> FreelancerRead:
        """One row per address. A second application from the same address is the same
        person correcting or refreshing theirs, so it overwrites what the wizard asked
        and leaves what the admin wrote (`stato`, `note`) alone. The first attribution
        stays, as it does for signups. A card an admin drafted from a signup (ORB-155)
        is taken over the same way: the person's answers replace the research and the
        card becomes theirs (`compilata_da = "persona"`)."""
        filename, mime = check_cv(cv, cv_filename, cv_mime)
        email = data.email.strip().lower()
        row = self._find(email)
        if row is None:
            utm = data.utm.model_dump() if data.utm is not None and not data.utm.is_empty() else {}
            row = Freelancer(
                email=email, cv_bytes=cv, cv_filename=filename, cv_mime=mime, cv_size=len(cv), **utm
            )
            self.session.add(row)
        else:
            row.cv_bytes, row.cv_filename, row.cv_mime, row.cv_size = cv, filename, mime, len(cv)
        row.nome = data.nome
        row.cognome = data.cognome
        row.linkedin_url = data.linkedin_url
        row.tariffa_giornaliera = data.tariffa_giornaliera
        row.posizione = data.posizione
        row.remoto = data.remoto
        row.links = list(data.links)
        row.compilata_da = "persona"
        try:
            self.session.commit()
        except IntegrityError:
            # Two first applications racing on one address: the index decides, and the
            # loser applies again on top of the winner's row.
            self.session.rollback()
            return self.apply(data, cv, cv_filename, cv_mime)
        return FreelancerRead.model_validate(row)

    def draft_from_signup(
        self, signup_id: UUID, data: FreelancerDraft, autore: str
    ) -> FreelancerRead:
        """A card written by an admin from what the public web says about a signup
        (ORB-155): the address and the attribution come from the signup, the answers
        from the research, the CV from nobody -- the person adds it from the member
        area. One row per address still: a second research on a card the admin wrote
        replaces the researched fields and leaves `stato`, `note` and the CV alone; a
        research on a card the person filled (`compilata_da == "persona"`) is refused,
        because their own words win. One comment in the thread names the sources, so
        whoever reads the card can check where it came from."""
        signup = self.session.get(Signup, signup_id)
        if signup is None:
            raise NotFound("signup", signup_id)
        email = signup.email.strip().lower()
        row = self._find(email)
        if row is not None and row.compilata_da == "persona":
            raise ValidationFailed(ENTITY, "email", "la persona ha già compilato la sua scheda")
        created = row is None
        if row is None:
            utm = {column: getattr(signup, column) for column in UTM_COLUMNS}
            row = Freelancer(email=email, **utm)
            self.session.add(row)
        row.nome = data.nome
        row.cognome = data.cognome
        row.linkedin_url = data.linkedin_url
        row.posizione = data.posizione
        row.tariffa_giornaliera = data.tariffa_giornaliera
        row.remoto = data.remoto
        row.links = list(data.links)
        row.compilata_da = "admin"
        try:
            self.session.commit()
        except IntegrityError:
            # Two first drafts racing on one address: the index decides, and the loser
            # drafts again on top of the winner's row.
            self.session.rollback()
            return self.draft_from_signup(signup_id, data, autore)
        sources = ", ".join(data.fonti)
        text = (
            f"Scheda creata dall'iscrizione del {signup.created_at:%d/%m/%Y}. Fonti: {sources}"
            if created
            else f"Scheda aggiornata dalla ricerca. Fonti: {sources}"
        )
        CommentService(self.session).add(ENTITY, row.id, text, autore)
        return self.get(row.id)

    def list_recent(
        self, limit: int = LIST_LIMIT_DEFAULT, stato: str | None = None
    ) -> FreelancerList:
        limit = max(1, min(limit, LIST_LIMIT_MAX))
        logins = _logins_per_card()
        stmt = select(Freelancer, logins.c.accessi, logins.c.ultimo_accesso).outerjoin(
            logins, logins.c.freelancer_id == Freelancer.id
        )
        count = select(func.count()).select_from(Freelancer)
        if stato is not None:
            stmt = stmt.where(Freelancer.stato == stato)
            count = count.where(Freelancer.stato == stato)
        rows = self.session.execute(
            stmt.order_by(Freelancer.created_at.desc(), Freelancer.id.desc()).limit(limit)
        ).all()
        totale = self.session.scalar(count) or 0
        return FreelancerList(
            totale=totale,
            items=[_read_with_logins(row, accessi, ultimo) for row, accessi, ultimo in rows],
        )

    def get(self, freelancer_id: UUID) -> FreelancerRead:
        """The row with its thread of comments, newest first. Only here: the list
        leaves `commenti` empty."""
        row = self._require(freelancer_id)
        logins = _logins_per_card()
        counted = self.session.execute(
            select(logins.c.accessi, logins.c.ultimo_accesso).where(
                logins.c.freelancer_id == row.id
            )
        ).first()
        read = _read_with_logins(row, *(counted or (None, None)))
        read.commenti = CommentService(self.session).list(ENTITY, freelancer_id)
        return read

    def cv(self, freelancer_id: UUID) -> CvFile:
        return cv_of(self._require(freelancer_id))

    def set_status(self, freelancer_id: UUID, change: StatusChange) -> FreelancerRead:
        if change.stato not in FREELANCER_STATES:
            raise ValidationFailed(ENTITY, "stato", f"uno fra {', '.join(FREELANCER_STATES)}")
        row = self._require(freelancer_id)
        row.stato = change.stato
        if change.note is not None:
            row.note = change.note.strip() or None
        self.session.commit()
        return FreelancerRead.model_validate(row)

    def _require(self, freelancer_id: UUID) -> Freelancer:
        row = self.session.get(Freelancer, freelancer_id)
        if row is None:
            raise NotFound(ENTITY, freelancer_id)
        return row

    def _find(self, email: str) -> Freelancer | None:
        return self.session.scalar(select(Freelancer).where(func.lower(Freelancer.email) == email))
