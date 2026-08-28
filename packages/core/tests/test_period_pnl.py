"""§7.4. Two columns, never one total; general expenses in a row of their own and
apportioned onto nobody; and the honesty flags that say whether the figure can still
move."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from periodo_fiscale import GIORNO_PRIMA, OGGI, PRIMO_DEL_MESE
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.schemas import PeriodPnlQuery
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.schemas import (
    CostCreate,
    PeriodLockCreate,
    TimeEntryCreate,
)
from pigrocrm.core.timetracking.service import TimeEntryService

READER = Actor(id=None, type="user", role="readonly")
WRITER = Actor(id=None, type="user", role="collaboratore")
# The window the P&L fixtures are dated into, derived and never a literal month: the
# closed deal carries an *issued* invoice, and `issue()` refuses a `data_emissione`
# outside the current fiscal year -- so a literal `2026-03` here was a date on which this
# whole file would begin failing. `periodo_fiscale.py` explains why "this year, March"
# would not have been a fix either.
PERIODO = PeriodPnlQuery(da=PRIMO_DEL_MESE, a=OGGI)
# A second window, for the one test that needs the period to be *over*:
# `voci_scritte_in_ritardo` counts rows whose `created_at` is later than `a`, so a window
# ending today can never contain a late row -- a row written now is written on the last
# day of the period, not after it. The previous calendar month is the nearest window that
# has certainly ended, and it is available on every run day including 1 January. It may
# fall in the previous fiscal year, which is why no test that issues an invoice may use
# it -- and none does: nothing here needs a `data_emissione`.
MESE_CHIUSO = PeriodPnlQuery(da=GIORNO_PRIMA.replace(day=1), a=GIORNO_PRIMA)


def test_an_open_deal_and_a_closed_one_never_share_a_total(
    db_session: Session, open_deal_with_hours: UUID, closed_deal_with_invoice: UUID
) -> None:
    """Adding a finished job's margin to a half-done one produces a figure that is
    neither, and that changes every week for reasons which are not business performance.
    The reportable number is `chiusi`."""
    pnl = AnalyticsService(db_session).period_pnl(PERIODO, READER)
    assert pnl.chiusi.deal == 1
    assert pnl.in_corso.deal == 1
    # The closed column, in full: 2000.00 invoiced, 200.00 of costs, no hours.
    assert pnl.chiusi.ricavi == Decimal("2000.00")
    assert pnl.chiusi.costi_diretti == Decimal("200.00")
    assert pnl.chiusi.costo_lavoro == Decimal("0.00")
    assert pnl.chiusi.margine_lordo == Decimal("1800.00")
    assert pnl.chiusi.margine_percentuale == Decimal("90.00")
    # The open one, in full: nothing invoiced, 150.00 of costs, 10h at 40.00 internal.
    assert pnl.in_corso.ricavi == Decimal("0.00")
    assert pnl.in_corso.costi_diretti == Decimal("150.00")
    assert pnl.in_corso.costo_lavoro == Decimal("400.00")
    assert pnl.in_corso.margine_lordo == Decimal("-550.00")
    assert pnl.in_corso.margine_percentuale is None
    # And there is deliberately no combined field to read by mistake.
    assert not hasattr(pnl, "totale")


def test_a_general_expense_has_its_own_row_and_touches_no_deal(
    db_session: Session,
    seeded_category_id: UUID,
    open_deal_with_hours: UUID,
    closed_deal_with_invoice: UUID,
) -> None:
    """Any apportionment key -- on revenue, on hours -- has one precise and unacceptable
    consequence: a deal's margin would move when a *different* deal was invoiced. That is
    exactly the property that makes a number unreportable, and it is the defect Acme's
    P&L has for personal taxation.

    Both columns are non-zero before the expense lands, so "nothing moved" is a statement
    about real figures and not about two pairs of zeros.
    """
    service = AnalyticsService(db_session)
    before = service.period_pnl(PERIODO, READER)
    assert before.spese_generali == Decimal("0.00")
    assert before.chiusi.margine_lordo == Decimal("1800.00")
    assert before.in_corso.margine_lordo == Decimal("-550.00")

    CostService(db_session).create(
        CostCreate(
            deal_id=None,
            category_id=seeded_category_id,
            data=OGGI,
            importo=Decimal("300.00"),
            descrizione="Commercialista",
        ),
        WRITER,
    )
    after = service.period_pnl(PERIODO, READER)
    assert after.spese_generali == Decimal("300.00")
    # Not one deal figure moved -- in either column, and including the percentages, which
    # is where a share of 300.00 would show up even if the absolute rows were rounded
    # back to where they started.
    assert after.chiusi == before.chiusi
    assert after.in_corso == before.in_corso


def test_a_customer_filter_excludes_general_expenses_entirely(
    db_session: Session, seeded_category_id: UUID, open_deal_with_hours: UUID
) -> None:
    """A general expense belongs to no customer by definition, so scoping to one must not
    show a share of it -- which would be apportionment through the back door."""
    CostService(db_session).create(
        CostCreate(
            deal_id=None,
            category_id=seeded_category_id,
            data=OGGI,
            importo=Decimal("300.00"),
            descrizione="Commercialista",
        ),
        WRITER,
    )
    unscoped = AnalyticsService(db_session).period_pnl(PERIODO, READER)
    assert unscoped.spese_generali == Decimal("300.00")

    customer_id = db_session.get(Deal, open_deal_with_hours).customer_id  # type: ignore[union-attr]
    scoped = AnalyticsService(db_session).period_pnl(
        PeriodPnlQuery(da=PERIODO.da, a=PERIODO.a, customer_id=customer_id), READER
    )
    assert scoped.spese_generali == Decimal("0.00")
    # And the customer's own deal is still there in full: a scope that returned nothing
    # at all would satisfy the assertion above while answering a different question.
    assert scoped.in_corso.deal == 1
    assert scoped.in_corso.costi_diretti == Decimal("150.00")
    assert scoped.in_corso.costo_lavoro == Decimal("400.00")


def test_each_quantity_is_attributed_by_its_own_date(
    db_session: Session,
    seeded_deal_id: UUID,
    seeded_user_id: UUID,
    seeded_category_id: UUID,
) -> None:
    """Revenue by `invoices.data_emissione`, costs by `costs.data`, labour cost by
    `time_entries.data`. Not by the deal's date, which does not exist, and not by one
    common date, which none of the three has.

    The boundary is tested on the day *before* the window opens rather than the day after
    it closes. The window ends today, and a `time_entry` dated after today is refused
    outright by `TimeEntryService` -- so "one day past the end" is a row that cannot be
    written at all, and an assertion that it is excluded would be an assertion about
    nothing. `GIORNO_PRIMA` is the same off-by-one on the other edge, and it is a day that
    always exists.
    """
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=PRIMO_DEL_MESE,
            ore=Decimal("1.00"),
            descrizione="nel periodo",
            costo_applicato=Decimal("50.000000"),
        ),
        WRITER,
    )
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=GIORNO_PRIMA,
            ore=Decimal("1.00"),
            descrizione="fuori periodo",
            costo_applicato=Decimal("50.000000"),
        ),
        WRITER,
    )
    CostService(db_session).create(
        CostCreate(
            deal_id=seeded_deal_id,
            category_id=seeded_category_id,
            data=GIORNO_PRIMA,
            importo=Decimal("10.00"),
            descrizione="fuori periodo",
        ),
        WRITER,
    )
    # A general expense one day before the window, so `spese_generali` is subject to the
    # same boundary as every other row rather than to the whole table.
    CostService(db_session).create(
        CostCreate(
            deal_id=None,
            category_id=seeded_category_id,
            data=GIORNO_PRIMA,
            importo=Decimal("77.00"),
            descrizione="fuori periodo generale",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).period_pnl(PERIODO, READER)
    assert pnl.in_corso.costo_lavoro == Decimal("50.00")
    assert pnl.in_corso.costi_diretti == Decimal("0.00")
    assert pnl.spese_generali == Decimal("0.00")


def test_an_open_period_reports_the_late_entries_and_a_closed_one_says_so(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """**Criterion 2's second half.** With the period open, a back-dated write succeeds,
    the P&L changes, and the response declares `periodo_chiuso = false` and
    `voci_scritte_in_ritardo = 1`. It is the information that tells a reader whether the
    number can still move.

    `MESE_CHIUSO` and not `PERIODO`: "written late" is only a statement a window that has
    ended can make about itself.
    """
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id,
            user_id=seeded_user_id,
            data=MESE_CHIUSO.a,
            ore=Decimal("2.00"),
            descrizione="retrodatata",
            costo_applicato=Decimal("50.000000"),
        ),
        WRITER,
    )
    service = AnalyticsService(db_session)
    open_period = service.period_pnl(MESE_CHIUSO, READER)
    assert open_period.periodo_chiuso is False
    # Written today, dated inside a month that ended before today: `created_at > a`.
    assert open_period.voci_scritte_in_ritardo == 1
    assert open_period.in_corso.costo_lavoro == Decimal("100.00")

    admin = Actor(id=seeded_user_id, type="user", role="admin")
    PeriodLockService(db_session).close_period(
        PeriodLockCreate(anno=MESE_CHIUSO.a.year, mese=MESE_CHIUSO.a.month), admin
    )
    closed = service.period_pnl(MESE_CHIUSO, READER)
    assert closed.periodo_chiuso is True
    # Closing changes what can still be written, never what was already read: the figures
    # are the same ones, and the late count does not reset on the way through.
    assert closed.in_corso == open_period.in_corso
    assert closed.chiusi == open_period.chiusi
    assert closed.voci_scritte_in_ritardo == 1


def test_a_multi_month_window_is_closed_only_when_every_month_is(
    db_session: Session, seeded_user_id: UUID
) -> None:
    """A window is only as closed as its least-closed month: reporting a quarter as
    closed because one of its months is would be the wrong reassurance in the one place
    it matters."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=1), admin)
    quarter = PeriodPnlQuery(da=date(2026, 1, 1), a=date(2026, 3, 31))
    assert AnalyticsService(db_session).period_pnl(quarter, READER).periodo_chiuso is False
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=2), admin)
    assert AnalyticsService(db_session).period_pnl(quarter, READER).periodo_chiuso is False
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    assert AnalyticsService(db_session).period_pnl(quarter, READER).periodo_chiuso is True


def test_a_window_across_a_year_end_enumerates_every_month_it_touches(
    db_session: Session, seeded_user_id: UUID
) -> None:
    """December to January is where month arithmetic goes wrong, and the wrong answer
    here is `periodo_chiuso = true` on a window nobody has closed."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    across = PeriodPnlQuery(da=date(2025, 12, 1), a=date(2026, 1, 31))
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2025, mese=12), admin)
    assert AnalyticsService(db_session).period_pnl(across, READER).periodo_chiuso is False
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=1), admin)
    assert AnalyticsService(db_session).period_pnl(across, READER).periodo_chiuso is True


def test_an_inverted_window_is_refused(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        AnalyticsService(db_session).period_pnl(
            PeriodPnlQuery(da=date(2026, 3, 31), a=date(2026, 3, 1)), READER
        )
    assert excinfo.value.details["field"] == "a"


def test_an_empty_window_returns_typed_zeros_and_a_null_percentage(db_session: Session) -> None:
    pnl = AnalyticsService(db_session).period_pnl(
        PeriodPnlQuery(da=date(1999, 1, 1), a=date(1999, 1, 31)), READER
    )
    assert pnl.chiusi.ricavi == Decimal("0.00")
    assert pnl.chiusi.margine_percentuale is None
    assert pnl.spese_generali == Decimal("0.00")
    assert pnl.chiusi.deal == 0
    assert pnl.in_corso.deal == 0
    assert pnl.periodo_chiuso is False
    assert pnl.voci_scritte_in_ritardo == 0
