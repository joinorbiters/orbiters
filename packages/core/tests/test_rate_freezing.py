"""**The slice's central guarantee.** What happens to last quarter's margin when you
raise a rate today? Nothing -- and not out of discipline, by construction, because no
report reads a rate column.

Criterion 2's first half, at the service level. The API-level repeat, comparing whole
JSON responses before and after, is Task 4B-4's; this one proves the property where it
actually lives, so a failure here names the cause instead of a diff.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.money import sum_money
from pigrocrm.core.timetracking.schemas import TimeEntryCreate, TimeEntryListQuery
from pigrocrm.core.timetracking.service import TimeEntryService

WRITER = Actor(id=None, type="user", role="collaboratore")
READER = Actor(id=None, type="user", role="readonly")


def test_raising_a_rate_today_does_not_move_an_old_period(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    user = db_session.get(User, seeded_user_id)
    user.tariffa_oraria_default = Decimal("80.000000")
    db_session.flush()
    service = TimeEntryService(db_session)

    # 40 hours at 80.000000 EUR/h across March, exactly criterion 2's setup.
    for day in range(1, 6):
        service.create(
            TimeEntryCreate(
                deal_id=seeded_deal_id,
                user_id=seeded_user_id,
                data=date(2026, 3, day),
                ore=Decimal("8.00"),
                descrizione=f"Giorno {day}",
            ),
            WRITER,
        )
    before = service.list(TimeEntryListQuery(deal_id=seeded_deal_id), READER)
    baseline_total = sum_money([e.valore_riga for e in before.items])
    assert baseline_total == Decimal("3200.00")
    baseline = [e.model_dump(mode="json") for e in before.items]

    # Now raise both levels, as high as criterion 2 asks.
    user.tariffa_oraria_default = Decimal("120.000000")
    db_session.get(Deal, seeded_deal_id).tariffa_oraria = Decimal("150.000000")
    db_session.flush()

    after = service.list(TimeEntryListQuery(deal_id=seeded_deal_id), READER)
    # Compared as structure, not by eye: every field of every row, including the
    # derived `valore_riga`, must be byte-identical.
    assert [e.model_dump(mode="json") for e in after.items] == baseline
    assert sum_money([e.valore_riga for e in after.items]) == baseline_total

    # And only a NEW hour picks up the new rate -- proving the old rows did not move
    # because nothing was read, not because nothing changed.
    fresh = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=date(2026, 4, 1),
            ore=Decimal("1.00"),
            descrizione="Aprile",
        ),
        WRITER,
    )
    assert fresh.tariffa_applicata == Decimal("150.000000")
    assert fresh.tariffa_origine == "deal"


def test_clearing_a_rate_column_altogether_leaves_written_rows_intact(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The harder direction: setting the source back to NULL. A report that re-read the
    column would turn a priced hour into an unpriced one."""
    db_session.get(Deal, seeded_deal_id).tariffa_oraria = Decimal("80.000000")
    db_session.flush()
    service = TimeEntryService(db_session)
    entry = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=date(2026, 3, 1),
            ore=Decimal("2.00"),
            descrizione="x",
        ),
        WRITER,
    )
    db_session.get(Deal, seeded_deal_id).tariffa_oraria = None
    db_session.flush()

    reread = service.get(entry.id, READER)
    assert reread.tariffa_applicata == Decimal("80.000000")
    assert reread.valore_riga == Decimal("160.00")
    assert service.deal_summary(seeded_deal_id, READER).ore_senza_tariffa == 0
