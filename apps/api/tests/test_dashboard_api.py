"""The HTTP surface of §4, plus the configuration endpoints of §9.6.

**Why this file builds its own sessions.** A dashboard is one transaction in
`REPEATABLE READ`, and Postgres refuses to change the isolation level once a transaction
has begun -- so `DashboardService` needs a session nothing has touched. The suite's
`api_session` is the opposite of that: it is bound to a connection inside an outer
transaction that is rolled back at teardown, and `ActorDep` has already read `users` on
it by the time any route body runs. The route therefore takes `SnapshotSessionDep`, a
second session resolved per request, and this file overrides that dependency with real
sessions on `api_engine` and commits the corpus they can see. The rows are removed in the
teardown, `pipeline_stages` included: `api_engine` is session-scoped, and six stages left
behind would be six stages every other API test did not create.

`test_authentication_does_not_poison_the_snapshot` is the one that pins the reason. Point
the route at the ordinary `SessionDep` and it is the test that fails, with the service's
own `RuntimeError` rather than a wrong number -- which is the whole design of
`_open_snapshot`.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import session_factory, today_local
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm_api.deps import get_snapshot_session

SEED = Actor(id=None, type="system", role="admin")
_PREFIX = "APIDASH"

EXPECTED_KEYS = {
    "periodo",
    "calcolato_alle",
    "pipeline",
    "chiusure",
    "offerte_in_attesa",
    "offerte_in_attesa_totale",
    "chiusure_previste_30_giorni",
    "chiusure_non_attribuibili",
    "offerte_accettate_deal_non_vinto",
}


@pytest.fixture
def dashboard_corpus(client: TestClient, api_engine: Engine) -> Iterator[Engine]:
    """Committed rows plus the per-request snapshot session that can see them.

    Committed, not flushed: the dashboard runs in its own transaction on its own
    connection, so uncommitted fixture data is invisible to it by construction. That is
    the property, not a limitation -- a dashboard that could read another transaction's
    uncommitted rows would not be one instant.
    """
    factory = session_factory(api_engine)
    with factory() as session:
        stages = {s.code: s for s in PipelineService(session).seed_defaults(SEED) if s.code}
        customer = Customer(ragione_sociale=f"{_PREFIX} Cliente", nazione="IT", custom_fields={})
        session.add(customer)
        session.flush()
        session.add(
            Deal(
                nome=f"{_PREFIX} aperto",
                customer_id=customer.id,
                pipeline_stage_id=stages["lead"].id,
                valore_previsto=Decimal("1000.00"),
                probabilita=50,
                custom_fields={},
            )
        )
        session.add(
            Deal(
                nome=f"{_PREFIX} vinto",
                customer_id=customer.id,
                pipeline_stage_id=stages["vinto"].id,
                valore_previsto=Decimal("5000.00"),
                probabilita=100,
                chiuso_il=today_local(),
                custom_fields={},
            )
        )
        session.add(
            Document(
                customer_id=customer.id,
                tipo="offerta",
                titolo=f"{_PREFIX} offerta",
                stato="inviata",
                stato_dal=today_local(),
                versione_corrente=1,
                custom_fields={},
            )
        )
        session.commit()

    def provide() -> Iterator[object]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    client.app.dependency_overrides[get_snapshot_session] = provide
    try:
        yield api_engine
    finally:
        client.app.dependency_overrides.pop(get_snapshot_session, None)
        with factory() as session:
            session.execute(delete(Document).where(Document.titolo.like(f"{_PREFIX} %")))
            session.execute(delete(Deal).where(Deal.nome.like(f"{_PREFIX} %")))
            session.execute(delete(Customer).where(Customer.ragione_sociale.like(f"{_PREFIX} %")))
            session.execute(delete(PipelineStage))
            session.commit()


# -- the commercial dashboard ----------------------------------------------------


def test_the_commercial_dashboard_is_one_request(
    logged_in: TestClient, dashboard_corpus: Engine
) -> None:
    """One endpoint, not one per card (§7.1). The key set is asserted whole: a card added
    to the schema without a place on the page, or one quietly dropped, both fail here."""
    response = logged_in.get("/api/dashboard/commerciale")
    assert response.status_code == 200, response.text
    assert set(response.json()) == EXPECTED_KEYS


def test_authentication_does_not_poison_the_snapshot(
    logged_in: TestClient, dashboard_corpus: Engine
) -> None:
    """The reason this route does not take `SessionDep`.

    `ActorDep` reads `users` to resolve the cookie, which autobegins a transaction on the
    session it was handed -- and `DashboardService._open_snapshot` refuses a session that
    is already in one, loudly, rather than running in `READ COMMITTED` and returning a
    total that was true at no instant. Sharing one session between the two would make
    every dashboard request a 500. So there are two sessions, and this is the test that
    says so: it fails the moment the route stops asking for its own.
    """
    response = logged_in.get("/api/dashboard/commerciale")
    assert response.status_code == 200, response.text
    assert response.json()["calcolato_alle"]


def test_the_endpoint_returns_what_the_service_returns(
    logged_in: TestClient, dashboard_corpus: Engine
) -> None:
    """The adapter is thin: no figure is computed, reshaped or renamed on the way out.

    Compared against the service reached directly on its own fresh session, over the same
    committed corpus -- not against numbers recomputed here, which would make this file a
    second source of truth for figures §3 says only one place may produce.
    """
    body = logged_in.get("/api/dashboard/commerciale").json()
    with session_factory(dashboard_corpus)() as session:
        direct = DashboardService(session).get_commercial_dashboard(PeriodoQuery(), SEED)
    expected = direct.model_dump(mode="json")
    assert body["pipeline"] == expected["pipeline"]
    assert body["chiusure"] == expected["chiusure"]
    assert body["offerte_in_attesa_totale"] == expected["offerte_in_attesa_totale"]
    assert next(row for row in body["pipeline"] if row["stage_code"] == "lead")["numero"] == 1


def test_the_period_round_trips_through_the_query_string(
    logged_in: TestClient, dashboard_corpus: Engine
) -> None:
    response = logged_in.get(
        "/api/dashboard/commerciale", params={"da": "2026-03-01", "a": "2026-03-31"}
    )
    assert response.json()["periodo"] == {"da": "2026-03-01", "a": "2026-03-31"}


def test_an_inverted_period_is_a_422_naming_the_field(
    logged_in: TestClient, dashboard_corpus: Engine
) -> None:
    response = logged_in.get(
        "/api/dashboard/commerciale", params={"da": "2026-03-31", "a": "2026-03-01"}
    )
    assert response.status_code == 422
    assert response.json()["field"] == "da"


@pytest.mark.parametrize(("da", "a"), [("2026-03-01", None), (None, "2026-03-31")])
def test_half_a_period_is_a_422_naming_the_missing_bound(
    logged_in: TestClient, dashboard_corpus: Engine, da: str | None, a: str | None
) -> None:
    """Both spellings, because a rule written as `if da is None` alone accepts the other
    one -- and `field` is what `fieldErrorFrom` in the web client reads."""
    params = {key: value for key, value in (("da", da), ("a", a)) if value is not None}
    response = logged_in.get("/api/dashboard/commerciale", params=params)
    assert response.status_code == 422
    assert response.json()["field"] == ("da" if da is None else "a")


def test_money_is_serialised_as_a_string(logged_in: TestClient, dashboard_corpus: Engine) -> None:
    """A JSON number is a float in every client that parses it, and a float total is the
    defect this whole slice is built to avoid.

    Asserted over a corpus with a real value in it, so the loop cannot pass by iterating
    over nothing -- and on the closure figures too, which are a different schema.
    """
    body = logged_in.get("/api/dashboard/commerciale").json()
    assert body["pipeline"], "the corpus produced no stage rows, so this test proved nothing"
    for row in body["pipeline"]:
        assert isinstance(row["valore_totale"], str), row
        assert isinstance(row["valore_ponderato"], str), row
    assert isinstance(body["chiusure"]["valore_vinto"], str)
    assert isinstance(body["chiusure"]["tasso_conversione"], str)


def test_a_readonly_actor_sees_the_dashboard(
    readonly_client: TestClient, dashboard_corpus: Engine
) -> None:
    """§13: this slice adds no role and no authorisation rule. Every figure here comes
    from a read every role already has."""
    assert readonly_client.get("/api/dashboard/commerciale").status_code == 200


def test_an_unauthenticated_request_is_a_401(client: TestClient, dashboard_corpus: Engine) -> None:
    assert client.get("/api/dashboard/commerciale").status_code == 401


# -- the automation configuration ------------------------------------------------


def test_the_automation_config_is_readable_by_a_readonly_actor(
    readonly_client: TestClient,
) -> None:
    response = readonly_client.get("/api/automation-config")
    assert response.status_code == 200
    assert set(response.json()) == {
        "a1_offerta_accettata_vince_deal",
        "a2_offerta_inviata_avanza_deal",
    }


def test_only_an_admin_may_change_the_automation_config(
    readonly_client: TestClient,
) -> None:
    """403 and not 401: the caller is authenticated and simply may not do this. The check
    lives in the service, so it holds for every caller of it and not only for this route.

    Read back afterwards, because a refusal that had already written the row would answer
    403 and pass on the status code alone -- `require_admin` runs before anything is
    touched, and this is what says so.
    """
    forbidden = readonly_client.put(
        "/api/automation-config", json={"a1_offerta_accettata_vince_deal": False}
    )
    assert forbidden.status_code == 403
    assert (
        readonly_client.get("/api/automation-config").json()["a1_offerta_accettata_vince_deal"]
        is True
    )


def test_an_admin_switches_a_rule_off_and_it_stays_off(logged_in: TestClient) -> None:
    allowed = logged_in.put(
        "/api/automation-config", json={"a1_offerta_accettata_vince_deal": False}
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["a1_offerta_accettata_vince_deal"] is False
    # Read back through the other endpoint: a `PUT` that answered correctly without
    # persisting would pass on its own response alone.
    assert logged_in.get("/api/automation-config").json() == {
        "a1_offerta_accettata_vince_deal": False,
        "a2_offerta_inviata_avanza_deal": True,
    }


def test_an_unknown_field_on_the_config_is_refused(logged_in: TestClient) -> None:
    """`extra="forbid"`: a typo in a field name must not silently do nothing. The only
    thing a misspelled key can do on a settings form is report success for a change that
    was not made."""
    response = logged_in.put("/api/automation-config", json={"a3_qualcosa": True})
    assert response.status_code == 422


def test_the_description_names_both_rules_with_their_state(logged_in: TestClient) -> None:
    body = logged_in.get("/api/automations").json()
    assert [rule["codice"] for rule in body["regole"]] == ["A1", "A2"]
    assert all(rule["descrizione"] for rule in body["regole"])
    assert body["configurazione"]["a1_offerta_accettata_vince_deal"] is True


def test_the_runs_endpoint_returns_the_recent_activities(logged_in: TestClient) -> None:
    """§9.4: the run log is a read of `activities` by `kind`, never a new table. Changing
    the configuration is itself one of the three kinds, so it is the cheapest way to prove
    the endpoint reads the real timeline rather than an empty list."""
    logged_in.put("/api/automation-config", json={"a2_offerta_inviata_avanza_deal": False})
    response = logged_in.get("/api/automation-runs", params={"limit": 5})
    assert response.status_code == 200
    runs = response.json()
    assert "automazione.configurazione_modificata" in [run["kind"] for run in runs]
    # A configuration change is not about a deal, and a bare `entity_id` here would render
    # as a link to a deal that does not exist.
    assert all(run["deal_id"] is None for run in runs)


def test_the_runs_limit_is_bounded(logged_in: TestClient) -> None:
    """Bounded on the route, like every other list in the project: an unbounded `limit` is
    a full table scan requested from a query string."""
    assert logged_in.get("/api/automation-runs", params={"limit": 500}).status_code == 422
    assert logged_in.get("/api/automation-runs", params={"limit": 0}).status_code == 422
