import calendar
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from pigrocrm.core.dashboard.schemas import DayHours, WeekHours
from pigrocrm.core.money import ZERO_HOURS, round_hours, sum_hours
from pigrocrm.core.timetracking.models import Cost, TimeEntry
from pigrocrm.core.timetracking.schemas import CostListQuery, TimeEntryListQuery


def month_bounds(anno: int, mese: int) -> tuple[date, date]:
    """First and last calendar day of a month, inclusive. Used by the report and by
    every monthly aggregate, so the boundary arithmetic exists once: `calendar.
    monthrange` rather than `date(anno, mese + 1, 1) - timedelta(days=1)`, which
    raises for December."""
    return date(anno, mese, 1), date(anno, mese, calendar.monthrange(anno, mese)[1])


class TimeEntryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entry_id: UUID, *, include_deleted: bool = False) -> TimeEntry | None:
        entry = self.session.get(TimeEntry, entry_id)
        if entry is None:
            return None
        if entry.deleted_at is not None and not include_deleted:
            return None
        return entry

    def add(self, entry: TimeEntry) -> TimeEntry:
        self.session.add(entry)
        self.session.flush()
        return entry

    def _live_for_deal(self, deal_id: UUID) -> Select[tuple[TimeEntry]]:
        return select(TimeEntry).where(TimeEntry.deal_id == deal_id, TimeEntry.deleted_at.is_(None))

    def for_deal(self, deal_id: UUID) -> list[TimeEntry]:
        return list(self.session.execute(self._live_for_deal(deal_id)).scalars())

    def in_range(self, deal_id: UUID, da: date, a: date) -> list[TimeEntry]:
        return list(
            self.session.execute(
                self._live_for_deal(deal_id)
                .where(TimeEntry.data >= da, TimeEntry.data <= a)
                .order_by(TimeEntry.data, TimeEntry.created_at)
            ).scalars()
        )

    def for_month(self, deal_id: UUID, anno: int, mese: int) -> list[TimeEntry]:
        da, a = month_bounds(anno, mese)
        return self.in_range(deal_id, da, a)

    def week_hours(self, da: date, a: date) -> WeekHours:
        """`SUM(ore) GROUP BY data` over the window, filled out to **every** day in it.

        Assembled here rather than in the dashboard for two reasons that agree: it is a
        single-table `SUM`, which §3 puts in this table's repository, and "the days with no
        hours" is a set difference -- which `DashboardService` is forbidden from containing
        (§3, and `test_dashboard_no_arithmetic.py`). Assembling it whole is also what keeps
        the two lists from being able to disagree: they are built from the same window and
        the same grouped result, in one place.

        The fill is the point. A `GROUP BY` returns only the days that have rows, so a week
        with three worked days comes back as three points and any chart drawn from it shows
        three consecutive bars -- a shape the week never had. `giorni` therefore carries one
        entry per day of the window, in calendar order, zeros included, and an empty week
        is seven zeros rather than nothing at all.

        A day *present* in the grouped result counts as **logged** whatever it sums to, so
        membership of `giorni_senza_ore` is decided by the presence of a row and never by
        the total being zero. Under `ck_time_entries_ore_range` (`ore > 0 AND ore <= 24`)
        the two readings are today indistinguishable -- a day with rows cannot sum to zero,
        and no test can separate them, which is why this is written down rather than
        asserted. Presence is nonetheless the right one: it is the reading that says "nobody
        wrote anything for this day", which is the question §6 asks, and it stays correct if
        that constraint is ever loosened. `0` is a value, never a blank, is the same rule
        the frontend's `isBlank` applies from the other side.

        `sum_hours` and `round_hours` from `core/money.py` rather than a local `quantize`:
        that module is the project's single authority on rounding, it rounds `ROUND_HALF_UP`
        where `Decimal.quantize` would default to half-even, and a second copy here is how
        two totals of the same hours begin to disagree.
        """
        rows = self.session.execute(
            select(TimeEntry.data, func.sum(TimeEntry.ore))
            .where(
                TimeEntry.deleted_at.is_(None),
                TimeEntry.data >= da,
                TimeEntry.data <= a,
            )
            .group_by(TimeEntry.data)
        ).all()
        # `func.sum` over a group is never null -- a group exists because it has at least
        # one row -- so there is no `coalesce` here. The `or ZERO_HOURS` that would look
        # prudent would instead hide a column becoming nullable.
        logged: dict[date, Decimal] = {row[0]: round_hours(Decimal(row[1])) for row in rows}

        span = (a - da).days + 1
        giorni_finestra = [da + timedelta(days=offset) for offset in range(span)]
        giorni = [
            DayHours(giorno=giorno, ore=logged.get(giorno, ZERO_HOURS))
            for giorno in giorni_finestra
        ]
        return WeekHours(
            da=da,
            a=a,
            giorni=giorni,
            # Membership by presence in `logged`, not by `ore == 0`: the zero-hour day is
            # exactly the case the two readings disagree on, and this is the one that is
            # right.
            giorni_senza_ore=[giorno for giorno in giorni_finestra if giorno not in logged],
            ore_totali=sum_hours([row.ore for row in giorni]),
        )

    # `list` stays the last method in this class -- the unconditional project rule.
    def list(self, query: TimeEntryListQuery) -> list[TimeEntry]:
        """Keyset pagination on `(data DESC, id DESC)`.

        Ordered by date descending because a list of hours in insertion order is
        unusable (residual R9 names the general gap; these tables are simply born
        ordered). `id` breaks the tie deterministically -- UUIDv7 is time-ordered, so
        it is also chronological within a day. One row over `limit` is fetched so the
        service can tell "there is more" from "that was everything" without a second
        count query.
        """
        stmt = select(TimeEntry).where(TimeEntry.deleted_at.is_(None))
        if query.deal_id is not None:
            stmt = stmt.where(TimeEntry.deal_id == query.deal_id)
        if query.user_id is not None:
            stmt = stmt.where(TimeEntry.user_id == query.user_id)
        if query.da is not None:
            stmt = stmt.where(TimeEntry.data >= query.da)
        if query.a is not None:
            stmt = stmt.where(TimeEntry.data <= query.a)
        if query.fatturabile is not None:
            stmt = stmt.where(TimeEntry.fatturabile.is_(query.fatturabile))
        if query.fatturato is not None:
            stmt = stmt.where(
                TimeEntry.invoice_line_id.isnot(None)
                if query.fatturato
                else TimeEntry.invoice_line_id.is_(None)
            )
        if query.custom:
            # JSONB containment, served by ix_time_entries_custom_fields (GIN), so a
            # custom-field filter never degrades into a sequential scan.
            stmt = stmt.where(TimeEntry.custom_fields.contains(query.custom))
        if query.cursor is not None:
            anchor = self.session.get(TimeEntry, query.cursor)
            if anchor is not None:
                stmt = stmt.where(
                    (TimeEntry.data < anchor.data)
                    | ((TimeEntry.data == anchor.data) & (TimeEntry.id < anchor.id))
                )
        return list(
            self.session.execute(
                stmt.order_by(TimeEntry.data.desc(), TimeEntry.id.desc()).limit(query.limit + 1)
            ).scalars()
        )


class CostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, cost_id: UUID, *, include_deleted: bool = False) -> Cost | None:
        cost = self.session.get(Cost, cost_id)
        if cost is None:
            return None
        if cost.deleted_at is not None and not include_deleted:
            return None
        return cost

    def add(self, cost: Cost) -> Cost:
        self.session.add(cost)
        self.session.flush()
        return cost

    def for_deal(self, deal_id: UUID) -> list[Cost]:
        return list(
            self.session.execute(
                select(Cost).where(Cost.deal_id == deal_id, Cost.deleted_at.is_(None))
            ).scalars()
        )

    # `list` stays the last method in this class.
    def list(self, query: CostListQuery) -> list[Cost]:
        stmt = select(Cost).where(Cost.deleted_at.is_(None))
        if query.solo_generali:
            # `deal_id IS NULL` is a general expense (§7.4). A separate flag is needed
            # because `deal_id=None` on the query already means "do not filter".
            stmt = stmt.where(Cost.deal_id.is_(None))
        elif query.deal_id is not None:
            stmt = stmt.where(Cost.deal_id == query.deal_id)
        if query.category_id is not None:
            stmt = stmt.where(Cost.category_id == query.category_id)
        if query.da is not None:
            stmt = stmt.where(Cost.data >= query.da)
        if query.a is not None:
            stmt = stmt.where(Cost.data <= query.a)
        if query.custom:
            stmt = stmt.where(Cost.custom_fields.contains(query.custom))
        if query.cursor is not None:
            anchor = self.session.get(Cost, query.cursor)
            if anchor is not None:
                stmt = stmt.where(
                    (Cost.data < anchor.data) | ((Cost.data == anchor.data) & (Cost.id < anchor.id))
                )
        return list(
            self.session.execute(
                stmt.order_by(Cost.data.desc(), Cost.id.desc()).limit(query.limit + 1)
            ).scalars()
        )
