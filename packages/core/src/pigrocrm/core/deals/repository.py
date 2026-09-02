from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.db import decode_cursor, escape_like, keyset_predicate, order_by
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.schemas import DEAL_SORTS, DealListQuery


class DealRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, deal_id: UUID, *, include_deleted: bool = False) -> Deal | None:
        deal = self.session.get(Deal, deal_id)
        if deal is None:
            return None
        if deal.deleted_at is not None and not include_deleted:
            return None
        return deal

    def add(self, deal: Deal) -> Deal:
        self.session.add(deal)
        self.session.flush()
        return deal

    def list(self, query: DealListQuery) -> list[Deal]:
        stmt = select(Deal).where(Deal.deleted_at.is_(None))

        if query.search:
            # escape_like neutralizes "%"/"_"/"\" in the *user's* term before it is
            # wrapped in the wildcard "%...%" this method builds -- otherwise a
            # literal "_" in the search box matches "any one character" and a
            # trailing "\" combines with the wildcard just after it into an
            # accidental escape sequence that swallows the match entirely. escape="\\"
            # states explicitly which character escape_like used, rather than relying
            # on ILIKE's default. Mirrors CustomerRepository.list/PersonRepository.list
            # exactly.
            like = f"%{escape_like(query.search.lower())}%"
            stmt = stmt.where(Deal.nome.ilike(like, escape="\\"))
        if query.customer_id:
            stmt = stmt.where(Deal.customer_id == query.customer_id)
        if query.stage_id:
            stmt = stmt.where(Deal.pipeline_stage_id == query.stage_id)
        if query.custom:
            # JSONB containment, served by the GIN index.
            stmt = stmt.where(Deal.custom_fields.contains(query.custom))

        # Residuo R9 -- see `CustomerRepository.list` for the reasoning.
        spec = DEAL_SORTS.resolve(query.sort)
        if query.cursor:
            value, row_id = decode_cursor(spec, query.cursor)
            stmt = stmt.where(keyset_predicate(spec, query.dir, value, row_id))

        return list(
            self.session.execute(
                stmt.order_by(*order_by(spec, query.dir)).limit(query.limit + 1)
            ).scalars()
        )
