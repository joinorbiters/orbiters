"""Every aggregate query of this slice, in one file.

Deliberately one module rather than a query beside each caller: "where does `ricavi`
come from" must have exactly one answer to read. the previous system's defect was a *dispersed*
aggregation -- `hoursByOfferKey.get(offer.id) || hoursByOfferKey.get(offer.fileName) ||
hoursByOfferKey.get(offer.offerName) || 0` took the **first non-empty bucket instead of
their sum**, so hours logged against an offer's name vanished if a single hour had been
logged against its id, and `linkedExpenseMap` lost costs the same way, silently. With one
required foreign key there are no buckets to merge and the sum is a `GROUP BY deal_id`;
this file is the structural counterpart of that.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from pigrocrm.core.deals.models import Deal
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.money import ZERO_MONEY, line_value, sum_money
from pigrocrm.core.timetracking.models import Cost, TimeEntry

# `Self`-preserving, so a scoped statement keeps the row type its `select()` gave it and
# the caller's `session.execute(...)` stays typed. A bare `Select[Any]` would work at
# runtime and quietly turn every scoped query's rows into `Any`.
_S = TypeVar("_S", bound=Select[Any])


def _revenue_filter() -> tuple[ColumnElement[bool], ...]:
    """The one definition of "an invoice that is revenue" (§7.1).

    `fattura`, never `proforma`: a proforma does not touch the register (slice 3 §5).
    `emessa`, never `annullata`: an annulled invoice keeps its number but not its revenue
    -- the struck-through page of a paper register. And `deleted_at IS NULL`, which on an
    issued invoice is guaranteed by `ck_invoices_no_delete_once_consumed` anyway: the
    filter is here so that the query and the constraint cannot drift apart.

    A function rather than a module-level tuple only because a shared expression object
    reused across statements is a subtlety nobody should have to think about at the call
    site; the three comparisons cost nothing to rebuild.
    """
    return (
        Invoice.tipo == "fattura",
        Invoice.stato == "emessa",
        Invoice.deleted_at.is_(None),
    )


class AnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def deal_revenue(self, deal_id: UUID) -> tuple[Decimal, int]:
        """`(Σ imponibile, count)` for one deal.

        `imponibile`, never `totale`: the total includes VAT, which is not revenue but
        money collected on the State's behalf. Under the forfettario the two coincide,
        which is exactly why the choice is made here and tested against a synthetic
        `RF01` profile rather than left to be noticed.

        The count is returned alongside because a revenue of `0.00` with three invoices
        behind it and one with none are different situations, and the UI says which.
        """
        total, count = self.session.execute(
            select(func.coalesce(func.sum(Invoice.imponibile), 0), func.count()).where(
                Invoice.deal_id == deal_id, *_revenue_filter()
            )
        ).one()
        return Decimal(total), int(count)

    def deal_direct_costs(self, deal_id: UUID) -> Decimal:
        return Decimal(
            self.session.execute(
                select(func.coalesce(func.sum(Cost.importo), 0)).where(
                    Cost.deal_id == deal_id, Cost.deleted_at.is_(None)
                )
            ).scalar_one()
        )

    def _customer_scope(
        self, stmt: _S, customer_id: UUID | None, column: InstrumentedAttribute[Any]
    ) -> _S:
        if customer_id is None:
            return stmt
        scoped: _S = stmt.where(column.in_(select(Deal.id).where(Deal.customer_id == customer_id)))
        return scoped

    def revenue_in_range(self, da: date, a: date, customer_id: UUID | None) -> dict[UUID, Decimal]:
        """Revenue is attributed to the period by **its own** date -- `data_emissione` --
        not by the deal's date, which does not exist, and not by one common date, which
        none of the three quantities has (§7.4)."""
        stmt = (
            select(Invoice.deal_id, func.coalesce(func.sum(Invoice.imponibile), 0))
            .where(
                Invoice.deal_id.isnot(None),
                Invoice.data_emissione >= da,
                Invoice.data_emissione <= a,
                *_revenue_filter(),
            )
            .group_by(Invoice.deal_id)
        )
        stmt = self._customer_scope(stmt, customer_id, Invoice.deal_id)
        return {row[0]: Decimal(row[1]) for row in self.session.execute(stmt).all()}

    def costs_in_range(
        self, da: date, a: date, customer_id: UUID | None
    ) -> tuple[dict[UUID, Decimal], Decimal]:
        """`({deal_id: total}, general_expenses)`. Costs are attributed by `costs.data`.

        General expenses -- `deal_id IS NULL` -- come back separately and are never
        distributed: any apportionment key would make a deal's margin move when a
        different deal was invoiced (§7.4). A customer filter excludes them entirely,
        because a general expense belongs to no customer by definition.
        """
        per_deal: dict[UUID, Decimal] = {}
        stmt = (
            select(Cost.deal_id, func.coalesce(func.sum(Cost.importo), 0))
            .where(
                Cost.deal_id.isnot(None),
                Cost.data >= da,
                Cost.data <= a,
                Cost.deleted_at.is_(None),
            )
            .group_by(Cost.deal_id)
        )
        stmt = self._customer_scope(stmt, customer_id, Cost.deal_id)
        for deal_id, total in self.session.execute(stmt).all():
            per_deal[deal_id] = Decimal(total)

        if customer_id is not None:
            return per_deal, ZERO_MONEY
        general = Decimal(
            self.session.execute(
                select(func.coalesce(func.sum(Cost.importo), 0)).where(
                    Cost.deal_id.is_(None),
                    Cost.data >= da,
                    Cost.data <= a,
                    Cost.deleted_at.is_(None),
                )
            ).scalar_one()
        )
        return per_deal, general

    def labour_cost_in_range(
        self, da: date, a: date, customer_id: UUID | None
    ) -> dict[UUID, Decimal]:
        """`Σ ROUND(ore × costo_applicato, 2)`, summed **per row** and then added -- never
        `ROUND(Σ ore × costo, 2)`.

        Computed in Python rather than in SQL on purpose: Postgres would round the
        product with its own rule, and §6.2 fixes `ROUND_HALF_UP` per row in
        `money.py` as the single authority. Two rounding implementations is how the
        printed column and the total come to disagree.
        """
        stmt = select(TimeEntry.deal_id, TimeEntry.ore, TimeEntry.costo_applicato).where(
            TimeEntry.data >= da,
            TimeEntry.data <= a,
            TimeEntry.deleted_at.is_(None),
            TimeEntry.costo_applicato.isnot(None),
        )
        stmt = self._customer_scope(stmt, customer_id, TimeEntry.deal_id)
        grouped: dict[UUID, list[Decimal | None]] = defaultdict(list)
        for deal_id, ore, costo in self.session.execute(stmt).all():
            grouped[deal_id].append(line_value(ore, costo))
        return {deal_id: sum_money(values) for deal_id, values in grouped.items()}

    def hours_in_range(self, da: date, a: date, customer_id: UUID | None) -> dict[UUID, Decimal]:
        stmt = (
            select(TimeEntry.deal_id, func.coalesce(func.sum(TimeEntry.ore), 0))
            .where(TimeEntry.data >= da, TimeEntry.data <= a, TimeEntry.deleted_at.is_(None))
            .group_by(TimeEntry.deal_id)
        )
        stmt = self._customer_scope(stmt, customer_id, TimeEntry.deal_id)
        return {row[0]: Decimal(row[1]) for row in self.session.execute(stmt).all()}

    def late_entry_count(self, da: date, a: date) -> int:
        """How many rows dated inside the period were written **after** it ended
        (`created_at > a`). It is what tells a reader whether the figure can still move,
        and it is free: a COUNT over two columns that already exist (§6.4)."""
        entries = self.session.execute(
            select(func.count())
            .select_from(TimeEntry)
            .where(
                TimeEntry.data >= da,
                TimeEntry.data <= a,
                TimeEntry.deleted_at.is_(None),
                func.date(TimeEntry.created_at) > a,
            )
        ).scalar_one()
        costs = self.session.execute(
            select(func.count())
            .select_from(Cost)
            .where(
                Cost.data >= da,
                Cost.data <= a,
                Cost.deleted_at.is_(None),
                func.date(Cost.created_at) > a,
            )
        ).scalar_one()
        return int(entries) + int(costs)

    def annual_revenue(self, anno: int) -> Decimal:
        """Every issued invoice of the year, deal or no deal: the fiscal estimate is
        about the person's income, so an invoice with no `deal_id` counts too."""
        return Decimal(
            self.session.execute(
                select(func.coalesce(func.sum(Invoice.imponibile), 0)).where(
                    Invoice.anno == anno, *_revenue_filter()
                )
            ).scalar_one()
        )

    def deals_in_range(self, da: date, a: date, customer_id: UUID | None) -> list[Deal]:
        """Every deal with any activity in the window -- an issued invoice, a cost or an
        hour. Not "every deal": a period report listing deals with nothing in the period
        is the unbounded growth residual B3 describes, and the window is what bounds it.
        """
        active = (
            select(Invoice.deal_id.label("deal_id"))
            .where(
                Invoice.deal_id.isnot(None),
                Invoice.data_emissione >= da,
                Invoice.data_emissione <= a,
                *_revenue_filter(),
            )
            .union(
                select(Cost.deal_id.label("deal_id")).where(
                    Cost.deal_id.isnot(None),
                    Cost.data >= da,
                    Cost.data <= a,
                    Cost.deleted_at.is_(None),
                ),
                select(TimeEntry.deal_id.label("deal_id")).where(
                    TimeEntry.data >= da, TimeEntry.data <= a, TimeEntry.deleted_at.is_(None)
                ),
            )
            .subquery()
        )
        stmt = select(Deal).where(Deal.id.in_(select(active.c.deal_id)), Deal.deleted_at.is_(None))
        if customer_id is not None:
            stmt = stmt.where(Deal.customer_id == customer_id)
        return list(self.session.execute(stmt.order_by(Deal.nome, Deal.id)).scalars())


__all__ = ["AnalyticsRepository"]
