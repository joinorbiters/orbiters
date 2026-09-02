"""One endpoint per dashboard. Sub-plan 6C adds two more to this file.

Each one is a single request served by a single read-only `REPEATABLE READ` transaction,
so that every figure on the page was true at one instant (§7.1). That property lives on
the *session*: Postgres refuses to change the isolation level once a transaction has
begun, and `DashboardService._open_snapshot` raises rather than degrading silently to
`READ COMMITTED`, where a card and its own drill-through can disagree.

Which is why this router takes `SnapshotSessionDep` and not the ordinary `SessionDep`.
`ActorDep` authenticates by reading `users`, and that read autobegins a transaction on
whatever session it was given -- so a dashboard sharing it would raise on every request.
The MCP adapter solves the same problem the same way and has since Task 4A-1:
`__main__.py` resolves the PAT in its own short-lived session, leaving the tool's session
untouched. See `deps.get_snapshot_session`.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from pigrocrm.core.dashboard.schemas import CommercialDashboard, PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm_api.deps import ActorDep, SnapshotSessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], responses=PROBLEM_RESPONSES)


@router.get("/commerciale", response_model=CommercialDashboard)
def commerciale(
    session: SnapshotSessionDep,
    actor: ActorDep,
    # Both or neither: `PeriodoQuery.resolve` refuses one alone rather than guessing the
    # other, because guessing would silently answer a different question. The default is
    # the current month, and the response always echoes the period back -- a screenshot of
    # a dashboard with no explicit period is a number with no unit (§4).
    da: Annotated[date | None, Query()] = None,
    a: Annotated[date | None, Query()] = None,
) -> CommercialDashboard:
    return DashboardService(session).get_commercial_dashboard(PeriodoQuery(da=da, a=a), actor)
