"""Companies: a project that needs people, and what an admin does with the request."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbiters_core.comments import CommentService
from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.models import COMPANY_STATES, Company
from orbiters_core.schemas import CompanyCreate, CompanyList, CompanyRead, StatusChange

ENTITY = "company"
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 500


class CompanyService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def request(self, data: CompanyCreate) -> CompanyRead:
        """Every request is a row: a company has several projects, and two requests a
        week apart are two things to answer, not one to merge."""
        utm = data.utm.model_dump() if data.utm is not None and not data.utm.is_empty() else {}
        row = Company(
            nome_azienda=data.nome_azienda,
            referente=data.referente,
            email=data.email.strip().lower(),
            progetto=data.progetto,
            periodo_da=data.periodo_da,
            durata=data.durata,
            budget_giornaliero=data.budget_giornaliero,
            **utm,
        )
        self.session.add(row)
        self.session.commit()
        return CompanyRead.model_validate(row)

    def list_recent(self, limit: int = LIST_LIMIT_DEFAULT, stato: str | None = None) -> CompanyList:
        limit = max(1, min(limit, LIST_LIMIT_MAX))
        stmt = select(Company)
        count = select(func.count()).select_from(Company)
        if stato is not None:
            stmt = stmt.where(Company.stato == stato)
            count = count.where(Company.stato == stato)
        rows = self.session.scalars(
            stmt.order_by(Company.created_at.desc(), Company.id.desc()).limit(limit)
        ).all()
        totale = self.session.scalar(count) or 0
        return CompanyList(totale=totale, items=[CompanyRead.model_validate(r) for r in rows])

    def get(self, company_id: UUID) -> CompanyRead:
        """The row with its thread of comments, newest first. Only here: the list
        leaves `commenti` empty."""
        read = CompanyRead.model_validate(self._require(company_id))
        read.commenti = CommentService(self.session).list(ENTITY, company_id)
        return read

    def set_status(self, company_id: UUID, change: StatusChange) -> CompanyRead:
        if change.stato not in COMPANY_STATES:
            raise ValidationFailed(ENTITY, "stato", f"uno fra {', '.join(COMPANY_STATES)}")
        row = self._require(company_id)
        row.stato = change.stato
        if change.note is not None:
            row.note = change.note.strip() or None
        self.session.commit()
        return CompanyRead.model_validate(row)

    def _require(self, company_id: UUID) -> Company:
        row = self.session.get(Company, company_id)
        if row is None:
            raise NotFound(ENTITY, company_id)
        return row
