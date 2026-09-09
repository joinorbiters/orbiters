"""Freelancers: the wizard's applications, and what an admin does with them."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.models import CV_MAX_BYTES, FREELANCER_STATES, Freelancer
from orbiters_core.schemas import (
    CvFile,
    FreelancerCreate,
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


class FreelancerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def apply(
        self, data: FreelancerCreate, cv: bytes, cv_filename: str, cv_mime: str
    ) -> FreelancerRead:
        """One row per address. A second application from the same address is the same
        person correcting or refreshing theirs, so it overwrites what the wizard asked
        and leaves what the admin wrote (`stato`, `note`) alone. The first attribution
        stays, as it does for signups."""
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
        try:
            self.session.commit()
        except IntegrityError:
            # Two first applications racing on one address: the index decides, and the
            # loser applies again on top of the winner's row.
            self.session.rollback()
            return self.apply(data, cv, cv_filename, cv_mime)
        return FreelancerRead.model_validate(row)

    def list_recent(
        self, limit: int = LIST_LIMIT_DEFAULT, stato: str | None = None
    ) -> FreelancerList:
        limit = max(1, min(limit, LIST_LIMIT_MAX))
        stmt = select(Freelancer)
        count = select(func.count()).select_from(Freelancer)
        if stato is not None:
            stmt = stmt.where(Freelancer.stato == stato)
            count = count.where(Freelancer.stato == stato)
        rows = self.session.scalars(
            stmt.order_by(Freelancer.created_at.desc(), Freelancer.id.desc()).limit(limit)
        ).all()
        totale = self.session.scalar(count) or 0
        return FreelancerList(totale=totale, items=[FreelancerRead.model_validate(r) for r in rows])

    def get(self, freelancer_id: UUID) -> FreelancerRead:
        return FreelancerRead.model_validate(self._require(freelancer_id))

    def cv(self, freelancer_id: UUID) -> CvFile:
        row = self._require(freelancer_id)
        return CvFile(filename=row.cv_filename, mime=row.cv_mime, content=row.cv_bytes)

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
