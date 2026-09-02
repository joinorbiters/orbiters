"""Composition, and deliberately nothing else.

**This module contains no arithmetic, and `packages/core/tests/test_dashboard_no_arithmetic.py`
makes that a fact of the build rather than an intention of this docstring.** It may not
import `Decimal`, and it may not contain a `BinOp` node with `*`, `/` or `-`. A composition
service that cannot subtract cannot invent a margin.

Spec §3: every figure on a dashboard is either returned verbatim by the service that owns
the data, or a single `COUNT`/`SUM` written in the repository of the table it counts. So
this file calls **services** for figures somebody else already owns and **repositories**
for the aggregates it defines -- and never a third thing.

Why repositories rather than services for those aggregates: a service exists to own
authorisation, a transaction and business rules, and these aggregates have none beyond
`deleted_at IS NULL`. Putting `pipeline_summary` on `DealService` would create two paths an
agent could reach the same number by -- the deal domain tool and the dashboard tool -- which
is the duplication this slice exists not to introduce.

**One endpoint, one transaction, one instant, in `REPEATABLE READ`.** Not one endpoint per
card. In `READ COMMITTED` -- Postgres's default, and so what you get by saying nothing --
each statement takes its own snapshot, and seven queries in one transaction can see seven
states exactly as seven transactions can: a user who adds two cards by hand and does not
get the third stops trusting all three, and is right to. The transaction is read-only, so
the usual price of the higher level is not paid -- a serialisation failure can only strike a
writer, and nothing here writes.

The accepted cost, stated because it is real: no partial rendering. One slow figure slows
the whole page. It is bearable because the queries are few and the period is always bounded,
and it is the price of the property this page exists for.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.dashboard.schemas import CommercialDashboard, PeriodoQuery
from pigrocrm.core.db import window_from
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.repository import DocumentRepository

# The property §7.1 requires, named so the tests can assert on the same constant the code
# uses rather than on a duplicated string literal.
SNAPSHOT_ISOLATION = "REPEATABLE READ"

_PENDING_OFFERS_SHOWN = 20
_EXPECTED_CLOSURE_WINDOW_DAYS = 30


class DashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.deals = DealRepository(session)
        self.documents = DocumentRepository(session)

    def _open_snapshot(self) -> datetime:
        """Begin the one read-only `REPEATABLE READ` transaction, and return its instant.

        Must be the first thing that touches the session: Postgres refuses to change the
        isolation level once a transaction has begun. That is not automatic in either
        adapter, and both pay for it explicitly: the API's dashboard routes take
        `SnapshotSessionDep`, a *second* session per request, because `ActorDep` resolves
        the cookie by reading `users` on the ordinary one; the MCP server resolves its PAT
        in a short-lived session of its own before any tool body runs.

        It raises rather than continuing when it cannot. Silent degradation here produces a
        total that was true at no single instant, and nothing about re-reading this file
        would reveal it -- which makes a loud failure strictly better than a plausible
        number. SQLAlchemy accepts the execution option on a session that is already in a
        transaction and quietly applies it to the *next* one, so the check is explicit
        rather than a `try`/`except` around the call: the failure this guards against is
        precisely the one that raises nothing.

        `transaction_timestamp()` is constant for the whole transaction, so it is the
        instant the whole response describes, and this `SELECT` is also what fixes the
        snapshot: in `REPEATABLE READ` Postgres takes it at the transaction's first
        statement, so every figure below is read as of this line. On its own the timestamp
        would prove nothing -- it is constant in `READ COMMITTED` too, which is precisely
        why criterion 6 asserts the isolation level as well.
        """
        if self.session.in_transaction():
            raise RuntimeError(
                "a dashboard needs a session with no transaction in progress so it can "
                f"run in {SNAPSHOT_ISOLATION}; this session already had one. Pass a fresh "
                "session (the API's SnapshotSessionDep, not SessionDep, which the actor "
                "lookup has already read on)."
            )
        self.session.connection(execution_options={"isolation_level": SNAPSHOT_ISOLATION})
        # Annotated rather than returned directly: `scalar_one()` is typed `Any`, and an
        # `Any` flowing out of a function declared to return `datetime` is what `mypy`'s
        # `no-any-return` is for.
        istante: datetime = self.session.execute(
            text("SELECT transaction_timestamp()")
        ).scalar_one()
        return istante

    def get_commercial_dashboard(self, query: PeriodoQuery, actor: Actor) -> CommercialDashboard:
        """Pipeline snapshot plus two period measures. Touches no invoice and no hour --
        it reads `deals`, `pipeline_stages` and `documents`, which is what lets it ship
        before the economic dashboard (§4, §17).

        The period is resolved **before** the snapshot is opened: a malformed period is the
        caller's mistake, and answering it with a `ValidationFailed` should not cost a
        transaction.

        No authorisation check: §13 states this slice adds no role and no authorisation
        rule, every figure here comes from a read every role already has, and the one
        admin-only figure of that area -- the fiscal estimate -- is on no dashboard (§5.3).
        Inventing a fourth visibility level on a read-only screen would put a security rule
        where nobody looks for one. `actor` is taken because every service method here does.
        """
        periodo = query.resolve()
        calcolato_alle = self._open_snapshot()
        # The window the "prossime chiusure" card means starts where the period ends, not
        # where it begins: on a January dashboard the imminent closures are February's, not
        # January's own. `window_from` lives in `db/clock.py` because a date offset is still
        # a `BinOp` and this package may not contain one -- see the module docstring.
        _, finestra_a = window_from(periodo.a, _EXPECTED_CLOSURE_WINDOW_DAYS)
        return CommercialDashboard(
            periodo=periodo,
            calcolato_alle=calcolato_alle,
            pipeline=self.deals.pipeline_summary(),
            chiusure=self.deals.closed_in_period(periodo.da, periodo.a),
            offerte_in_attesa=self.documents.pending_offers(_PENDING_OFFERS_SHOWN),
            offerte_in_attesa_totale=self.documents.count_pending_offers(),
            chiusure_previste_30_giorni=self.deals.expected_closures(periodo.a, finestra_a),
            chiusure_non_attribuibili=self.deals.unattributable_closures(),
            offerte_accettate_deal_non_vinto=(self.documents.count_accepted_with_unwon_deal()),
        )
