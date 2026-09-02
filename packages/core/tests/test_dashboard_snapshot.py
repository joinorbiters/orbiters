"""**Criterion 6.** A dashboard is one instant, and this is what proves it.

`test_dashboard_commercial.py` already shows a commit landing between two of the
dashboard's *aggregates* and staying invisible. This file goes at the same property from
the other side, and adds the three things that file cannot say:

  (a) the constant `SNAPSHOT_ISOLATION` is the level the connection actually gets --
      asserted for both values, so the lever the inversion below pulls is proven to be
      connected to something before it is used as evidence;
  (b) a genuinely parallel connection COMMITs *between* `_open_snapshot()` and the very
      first aggregate, synchronised with two events rather than by calling the writer
      inline -- so what is asserted is that the snapshot is fixed by the
      `transaction_timestamp()` statement itself, not merely by whichever query ran first;
  (c) `calcolato_alle` precedes that commit, bracketed by the database's own clock.

And then the inversion, which is what makes (a) mean something instead of decorating the
file: repeated with the isolation level forced to `read committed`, (b) **fails** -- the
intruder shows up in two independent figures. `transaction_timestamp()` is constant for a
whole transaction even in `READ COMMITTED`, so a test that stopped at (c) would pass on a
dashboard that read seven different states. A control test then re-reads the dashboard
afterwards and requires the intruder to be visible, so that (b) cannot pass because the
writer quietly failed and the row never existed at all.

This file deliberately does not use the `db_session` fixture: it holds an outer transaction
open, and Postgres refuses to change the isolation level once a transaction has begun.
`test_dashboard_commercial.py` is the other dashboard file that builds its own sessions,
and for the same reason. Like that file, the teardown empties `pipeline_stages` wholesale --
`db_engine` is session-scoped, and six stages left behind would be six stages every other
test in the suite did not create.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete, text

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.dashboard import service as dashboard_service
from pigrocrm.core.dashboard.schemas import (
    CommercialDashboard,
    PeriodoQuery,
    PipelineStageSummary,
)
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import month_bounds, session_factory, today_local, window_from
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.schemas import PipelineStageRead
from pigrocrm.core.pipeline.service import PipelineService

READONLY = Actor(id=uuid7(), type="user", role="readonly")
SEED = Actor(id=None, type="system", role="admin")
_PREFIX = "SNAP"
# Generous on purpose: this bounds a deadlock, not a query. A barrier that times out
# reports "the writer never committed" rather than hanging the suite.
_BARRIER_TIMEOUT = 30.0


class Seeded(NamedTuple):
    engine: Engine
    customer_id: UUID
    stages: dict[str, PipelineStageRead]


@pytest.fixture
def seeded(db_engine: Engine) -> Iterator[Seeded]:
    factory = session_factory(db_engine)
    with factory() as session:
        stages = {s.code: s for s in PipelineService(session).seed_defaults(SEED) if s.code}
        customer = Customer(ragione_sociale=f"{_PREFIX} Cliente", nazione="IT", custom_fields={})
        session.add(customer)
        session.flush()
        customer_id = customer.id
        # No `data_chiusura_prevista`: the baseline for "prossime chiusure" has to be zero
        # so that the intruder below is the only thing that could ever move it.
        session.add(
            Deal(
                nome=f"{_PREFIX} base",
                customer_id=customer_id,
                pipeline_stage_id=stages["lead"].id,
                valore_previsto=Decimal("1000.00"),
                probabilita=50,
                custom_fields={},
            )
        )
        session.commit()
    try:
        yield Seeded(db_engine, customer_id, stages)
    finally:
        with factory() as session:
            session.execute(delete(Deal).where(Deal.nome.like(f"{_PREFIX} %")))
            session.execute(delete(Customer).where(Customer.ragione_sociale.like(f"{_PREFIX} %")))
            session.execute(delete(PipelineStage))
            session.commit()


def _dashboard(engine: Engine) -> CommercialDashboard:
    with session_factory(engine)() as session:
        return DashboardService(session).get_commercial_dashboard(PeriodoQuery(), READONLY)


def _imminent_date() -> date:
    """A day inside the "prossime chiusure" window of the default (current month) period.

    The window runs from the period's last day for thirty days, so ten days past the end of
    the month is inside it and outside the period itself.
    """
    today = today_local()
    _, fine_periodo = month_bounds(today.year, today.month)
    _, imminente = window_from(fine_periodo, 10)
    return imminente


def _run_with_a_commit_in_the_middle(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> tuple[CommercialDashboard, datetime]:
    """Run the dashboard while another connection commits a new open deal between
    `_open_snapshot()` and the first aggregate.

    The barrier hangs off `pipeline_summary`, which is the first aggregate the service
    calls. Signalling from inside it and *waiting* for the writer means the commit lands
    after the snapshot was taken -- `SELECT transaction_timestamp()` is the transaction's
    first statement and is what acquires it -- and before every remaining query, which is
    exactly the window `READ COMMITTED` leaks through.

    The intruder is shaped so that two independent queries would each report it: it sits in
    an open stage (`pipeline_summary`) and expects to close inside the imminent window
    (`expected_closures`). One figure moving would be a coincidence; the pair is the
    property.

    Returns the response and an instant that provably precedes the parallel COMMIT, taken
    from the database's clock rather than the host's.
    """
    reader_reached_first_query = threading.Event()
    writer_committed = threading.Event()
    instant_before_commit: list[datetime] = []

    def writer() -> None:
        try:
            reader_reached_first_query.wait(_BARRIER_TIMEOUT)
            with session_factory(seeded.engine)() as session:
                session.add(
                    Deal(
                        nome=f"{_PREFIX} intruso",
                        customer_id=seeded.customer_id,
                        pipeline_stage_id=seeded.stages["lead"].id,
                        valore_previsto=Decimal("9999.00"),
                        probabilita=50,
                        data_chiusura_prevista=_imminent_date(),
                        custom_fields={},
                    )
                )
                session.flush()
                instant_before_commit.append(
                    session.execute(text("SELECT clock_timestamp()")).scalar_one()
                )
                session.commit()
        finally:
            # In a `finally` so a writer that raises releases the reader immediately and
            # the assertion below reports the real failure, instead of the suite paying
            # `_BARRIER_TIMEOUT` seconds to reach the same conclusion.
            writer_committed.set()

    original = DealRepository.pipeline_summary
    tripped = threading.Event()

    def barrier(self: DealRepository) -> list[PipelineStageSummary]:
        if not tripped.is_set():
            tripped.set()
            reader_reached_first_query.set()
            writer_committed.wait(_BARRIER_TIMEOUT)
        return original(self)

    monkeypatch.setattr(DealRepository, "pipeline_summary", barrier)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        result = _dashboard(seeded.engine)
    finally:
        thread.join(timeout=_BARRIER_TIMEOUT)
    assert tripped.is_set(), (
        "pipeline_summary was never called, so nothing was synchronised; check that it is "
        "still the first aggregate get_commercial_dashboard invokes"
    )
    assert instant_before_commit, "the parallel writer never committed"
    return result, instant_before_commit[0]


def _lead(result: CommercialDashboard) -> PipelineStageSummary:
    return next(row for row in result.pipeline if row.stage_code == "lead")


# -- clause (a): the constant is the level, and the lever works -------------------


@pytest.mark.parametrize(
    ("constant", "shown"),
    [("REPEATABLE READ", "repeatable read"), ("READ COMMITTED", "read committed")],
)
def test_the_constant_is_the_level_the_connection_actually_gets(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch, constant: str, shown: str
) -> None:
    """Both values, not just the shipped one.

    The shipped case is the criterion. The other case is what licenses the inversion test
    below to be read as evidence: if patching `SNAPSHOT_ISOLATION` did not actually reach
    the connection -- because the service had started reading a setting, or caching the
    execution option -- the inversion would fail for a reason that has nothing to do with
    the snapshot, and somebody would "fix" it by weakening clause (b).
    """
    assert dashboard_service.SNAPSHOT_ISOLATION == "REPEATABLE READ"
    monkeypatch.setattr(dashboard_service, "SNAPSHOT_ISOLATION", constant)
    with session_factory(seeded.engine)() as session:
        DashboardService(session).get_commercial_dashboard(PeriodoQuery(), READONLY)
        level = session.execute(text("SHOW transaction_isolation")).scalar_one()
    assert level == shown


# -- clause (b): a commit in the middle reaches no figure ------------------------


def test_clause_b_a_commit_before_the_first_aggregate_appears_in_no_figure(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The intruder commits before the *first* aggregate runs, and is still invisible.

    That is the sharper half of the claim: not "a later query agrees with an earlier one",
    but "the snapshot was already fixed by the time any aggregate ran". Two unrelated
    figures are checked, because a single one could be right for its own reasons.
    """
    result, _instant = _run_with_a_commit_in_the_middle(seeded, monkeypatch)

    lead = _lead(result)
    assert lead.numero == 1
    assert lead.valore_totale == Decimal("1000.00")
    assert lead.valore_ponderato == Decimal("500.00")
    assert result.chiusure_previste_30_giorni == 0


def test_the_intruder_really_was_committed_and_the_dashboard_can_see_it(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above, and the reason it is not vacuous.

    A writer that silently did nothing would satisfy every assertion of clause (b). So the
    same row is read back by a *fresh* dashboard, with the same predicates, and both
    figures must move. Clause (b) then means "invisible to that snapshot", not "absent".
    """
    _run_with_a_commit_in_the_middle(seeded, monkeypatch)

    later = _dashboard(seeded.engine)
    assert _lead(later).numero == 2
    assert _lead(later).valore_totale == Decimal("10999.00")
    assert later.chiusure_previste_30_giorni == 1


# -- clause (c): the instant is the snapshot's, not the response's ---------------


def test_clause_c_calcolato_alle_precedes_the_parallel_commit(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`calcolato_alle` is when the reading happened, not when the answering finished.

    The bound is taken with `clock_timestamp()` on the writer's connection immediately
    before its COMMIT, so it is a real lower bound on that commit rather than a reading
    taken after it. A `calcolato_alle` filled in at the end of the request -- with
    `clock_timestamp()`, or in Python -- lands after this instant and fails here, while
    still passing a bracket taken around the whole call.
    """
    result, instant_before_commit = _run_with_a_commit_in_the_middle(seeded, monkeypatch)
    assert result.calcolato_alle < instant_before_commit, (
        f"calcolato_alle {result.calcolato_alle} is not before the parallel commit at "
        f"{instant_before_commit}; it is not the snapshot's instant"
    )


# -- the inversion ---------------------------------------------------------------


def test_the_inversion_read_committed_leaks_the_parallel_commit(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test that makes clause (a) mean something.

    Forced to `READ COMMITTED` -- Postgres's default, and therefore what this dashboard
    would silently get if nobody had said otherwise -- each statement takes its own
    snapshot, so every query after the barrier sees the intruder. If this test ever starts
    passing with clause (b)'s numbers, the isolation level has stopped doing anything and
    clauses (a) to (c) are decorative.
    """
    monkeypatch.setattr(dashboard_service, "SNAPSHOT_ISOLATION", "READ COMMITTED")

    result, _instant = _run_with_a_commit_in_the_middle(seeded, monkeypatch)

    lead = _lead(result)
    assert lead.numero == 2, (
        "in READ COMMITTED the post-barrier queries should have seen the parallel commit. "
        "They did not, which means the barrier is not actually landing between two "
        "statements -- fix the barrier before trusting clause (b)."
    )
    assert lead.valore_totale == Decimal("10999.00")
    assert result.chiusure_previste_30_giorni == 1
