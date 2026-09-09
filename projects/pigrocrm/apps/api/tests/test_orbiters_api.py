"""`POST /api/orbiters/signups`: public, on its own database, idempotent, and mute.

The `orbiters` database is created inside the same Postgres container `api_engine`
starts, through the real `ensure_orbiters_database` path, and the CRM session the
other tests use is never touched by it.

Mute is the security property these tests are here to keep: the one unauthenticated
write in the API answers the same thing to everybody, so posting somebody else's
address tells you nothing about them -- not their name, not their profile, not even
whether they are on the list. Whatever a test wants to know about a row, it reads from
the database directly.
"""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.orbiters import ensure_orbiters_database
from pigrocrm.core.orbiters.conversions import hashed_email
from pigrocrm_api.deps import get_orbiters_session
from pigrocrm_api.routers import orbiters as orbiters_router
from pigrocrm_api.routers.orbiters import SIGNUPS_PER_MINUTE, reset_signup_rate_limit


@pytest.fixture(scope="module")
def orbiters_engine(api_engine: Engine) -> Iterator[Engine]:
    settings = Settings(
        database_url=api_engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = ensure_orbiters_database(settings)
    yield engine
    engine.dispose()


@pytest.fixture
def orbiters_session(orbiters_engine: Engine) -> Iterator[Session]:
    session = session_factory(orbiters_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("DELETE FROM signups"))
        session.commit()
        session.close()


@pytest.fixture
def orbiters_client(client: TestClient, orbiters_session: Session) -> Iterator[TestClient]:
    client.app.dependency_overrides[get_orbiters_session] = lambda: orbiters_session  # type: ignore[attr-defined]
    # The limiter counts requests per process, so one test's posts would otherwise be
    # spent out of the next test's budget.
    reset_signup_rate_limit()
    yield client


def _row(session: Session, email: str) -> tuple[str | None, str | None, str | None]:
    return tuple(  # type: ignore[return-value]
        session.execute(
            text("SELECT nome, cognome, linkedin_url FROM signups WHERE email = :email"),
            {"email": email},
        ).one()
    )


def _body(email: str, **extra: object) -> dict[str, object]:
    """What the landing posts: the three required answers, plus whatever the test adds."""
    return {"email": email, "nome": "Ada", "cognome": "Lovelace", **extra}


def test_a_visitor_with_no_account_can_sign_up(
    orbiters_client: TestClient, orbiters_session: Session
) -> None:
    response = orbiters_client.post("/api/orbiters/signups", json=_body("Ada@Studio.it"))
    assert response.status_code == 201, response.text
    # All of it: the answer says the request was accepted and nothing else.
    assert response.json() == {"ok": True}
    assert _row(orbiters_session, "ada@studio.it") == ("Ada", "Lovelace", None)


def test_the_profile_travels_with_the_name(
    orbiters_client: TestClient, orbiters_session: Session
) -> None:
    response = orbiters_client.post(
        "/api/orbiters/signups",
        json=_body("ada@studio.it", linkedin_url="https://www.linkedin.com/in/ada"),
    )
    assert response.status_code == 201, response.text
    assert _row(orbiters_session, "ada@studio.it") == (
        "Ada",
        "Lovelace",
        "https://www.linkedin.com/in/ada",
    )


def test_posting_someone_elses_address_discloses_nothing_about_them(
    orbiters_client: TestClient, orbiters_session: Session
) -> None:
    """The whole point of `SignupAck`. A stranger who guesses an address gets the same
    201 and the same body as the person who signed up, learns neither the stored name
    nor the profile, and cannot even tell that the address was already there."""
    first = orbiters_client.post(
        "/api/orbiters/signups",
        json=_body("ada@studio.it", linkedin_url="https://www.linkedin.com/in/ada"),
    )
    probe = orbiters_client.post(
        "/api/orbiters/signups", json={"email": "ada@studio.it", "nome": "x", "cognome": "y"}
    )
    assert (probe.status_code, probe.json()) == (first.status_code, first.json())
    assert "Lovelace" not in probe.text and "linkedin" not in probe.text
    # And the probe changed nothing: what was there stays there.
    assert _row(orbiters_session, "ada@studio.it") == (
        "Ada",
        "Lovelace",
        "https://www.linkedin.com/in/ada",
    )


def test_a_profile_with_a_newline_in_it_is_a_422_not_a_stored_line_break(
    orbiters_client: TestClient,
) -> None:
    response = orbiters_client.post(
        "/api/orbiters/signups",
        json=_body(
            "ada@studio.it",
            linkedin_url="https://www.linkedin.com/in/ada\nBcc: qualcuno@altrove.it",
        ),
    )
    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} == {"linkedin_url"}


def test_the_422_names_the_field_it_refused_so_the_form_can_point_at_it(
    orbiters_client: TestClient,
) -> None:
    """The landing reads `detail[].loc` to decide which field to mark and focus; without
    this contract it can only blame the address, which is a dead end for the visitor."""
    response = orbiters_client.post(
        "/api/orbiters/signups", json=_body("ada@studio.it", linkedin_url="https://example.com/ada")
    )
    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} == {"linkedin_url"}


def test_too_many_signups_from_one_client_are_refused_in_italian(
    orbiters_client: TestClient,
) -> None:
    for index in range(SIGNUPS_PER_MINUTE):
        accepted = orbiters_client.post(
            "/api/orbiters/signups", json=_body(f"ada{index}@studio.it")
        )
        assert accepted.status_code == 201, accepted.text
    refused = orbiters_client.post("/api/orbiters/signups", json=_body("ancora@studio.it"))
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "60"
    assert "Troppe richieste" in refused.json()["detail"]


def test_a_signup_without_a_name_is_a_422(orbiters_client: TestClient) -> None:
    response = orbiters_client.post("/api/orbiters/signups", json={"email": "ada@studio.it"})
    assert response.status_code == 422
    # FastAPI's own request-validation shape, the one the form's field highlighting
    # reads (see `errors.py`, `_domain_and_request_validation_response`).
    missing = {error["loc"][-1] for error in response.json()["detail"]}
    assert {"nome", "cognome"} <= missing


def test_a_profile_that_is_not_on_linkedin_is_a_422_not_a_row(
    orbiters_client: TestClient,
) -> None:
    response = orbiters_client.post(
        "/api/orbiters/signups", json=_body("ada@studio.it", linkedin_url="https://example.com/ada")
    )
    assert response.status_code == 422


def test_the_same_address_again_answers_exactly_the_same_thing(
    orbiters_client: TestClient, orbiters_session: Session
) -> None:
    """One row, two identical successes. It used to be 201 then 200 with `nuova`, which
    told any caller whether an address was already on the list."""
    first = orbiters_client.post("/api/orbiters/signups", json=_body("ada@studio.it"))
    second = orbiters_client.post("/api/orbiters/signups", json=_body("ADA@studio.it"))
    assert (first.status_code, first.json()) == (201, {"ok": True})
    assert (second.status_code, second.json()) == (201, {"ok": True})
    assert orbiters_session.execute(text("SELECT count(*) FROM signups")).scalar() == 1


def test_an_address_that_is_not_one_is_a_422(orbiters_client: TestClient) -> None:
    response = orbiters_client.post("/api/orbiters/signups", json=_body("ciao"))
    assert response.status_code == 422


def test_the_list_never_lands_in_the_crm_database(
    orbiters_client: TestClient, api_session: Session
) -> None:
    orbiters_client.post("/api/orbiters/signups", json=_body("ada@studio.it"))
    assert api_session.execute(text("SELECT to_regclass('signups')")).scalar() is None


def test_the_attribution_travels_with_the_email_and_is_stored(
    orbiters_client: TestClient, orbiters_session: Session
) -> None:
    response = orbiters_client.post(
        "/api/orbiters/signups",
        json=_body(
            "ada@studio.it",
            utm={
                "utm_source": "linkedin",
                "utm_medium": "paid-social",
                "utm_id": "{{AD_SET_ID}}",
            },
        ),
    )
    assert response.status_code == 201, response.text
    stored = orbiters_session.execute(
        text("SELECT utm_source, utm_medium, utm_id, utm_campaign FROM signups")
    ).one()
    assert tuple(stored) == ("linkedin", "paid-social", "{{AD_SET_ID}}", None)


def test_an_attribution_longer_than_the_column_is_a_422_not_a_500(
    orbiters_client: TestClient,
) -> None:
    response = orbiters_client.post(
        "/api/orbiters/signups", json=_body("ada@studio.it", utm={"utm_source": "x" * 201})
    )
    assert response.status_code == 422


def test_the_rate_limit_key_is_the_address_nginx_saw_not_the_one_the_client_wrote() -> None:
    """`X-Forwarded-For` is `client-supplied, proxy-appended`: the FIRST hop is whatever the
    visitor typed, the LAST is what nginx observed. Keying on the first let a script mint
    a fresh bucket per request by changing the header; `X-Real-IP` (set by nginx too) is
    the same observed address and wins when present."""
    from starlette.requests import Request

    from pigrocrm_api.routers.orbiters import _client_key

    def req(headers: dict[str, str], client: tuple[str, int] | None = ("127.0.0.1", 1)) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request(
            {"type": "http", "headers": raw, "client": client, "method": "POST", "path": "/"}
        )

    assert (
        _client_key(req({"X-Real-IP": "203.0.113.9", "X-Forwarded-For": "1.1.1.1, 203.0.113.9"}))
        == "203.0.113.9"
    )
    assert _client_key(req({"X-Forwarded-For": "1.1.1.1, 203.0.113.9"})) == "203.0.113.9"
    assert _client_key(req({"X-Forwarded-For": "forged-value, 203.0.113.9"})) == "203.0.113.9"
    assert _client_key(req({})) == "127.0.0.1"
    assert _client_key(req({}, client=None)) == "sconosciuto"


# --- the ad conversion ------------------------------------------------------------------
#
# The row is what matters and the event is not allowed to touch it. So every test here
# asserts two things at once: what reached OpenAI, and that the signup answered 201 and
# was written whatever OpenAI did. `TestClient` runs background tasks before returning
# from `post`, which is why the recorded calls can be read straight after it.

PIXEL_ID = "9r6qrnPxBV8WDVGtpuaqxh"
EVENT_ID = "8f14e45f-ceea-467a-9f36-dcd8b0eba0b1"


class RecordingHttp:
    """The seam `ConversionsPixel` posts through, remembered per call."""

    def __init__(self, status: int = 200, raises: bool = False) -> None:
        self.status = status
        self.raises = raises
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, headers, body))
        if self.raises:
            raise OSError("la rete non c'e'")
        return self.status, b'{"ok":true}'

    def event(self) -> dict[str, object]:
        return dict(json.loads(self.calls[-1][3])["events"][0])


@pytest.fixture
def pixel(orbiters_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingHttp]:
    """A configured conversion source whose network is a recorder.

    The settings are declared here rather than inherited: the client fixture's own
    `Settings(_env_file=None)` has no pixel at all, which is the state
    `test_an_installation_without_a_pixel_sends_nothing` relies on.
    """
    http = RecordingHttp()
    orbiters_client.app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[attr-defined]
        openai_pixel_id=PIXEL_ID,
        openai_conversions_api_key="sk-non-una-chiave-vera",
        orbiters_signup_url="https://joinorbiters.com/orbiters",
        _env_file=None,  # type: ignore[call-arg]
    )
    real = orbiters_router.pixel_from_settings

    def with_recorder(settings: Settings):  # type: ignore[no-untyped-def]
        built = real(settings)
        if built is not None:
            built.http = http
        return built

    monkeypatch.setattr(orbiters_router, "pixel_from_settings", with_recorder)
    yield http
    orbiters_client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]


def test_a_signup_measures_one_conversion_with_the_id_the_browser_used(
    orbiters_client: TestClient, orbiters_session: Session, pixel: RecordingHttp
) -> None:
    response = orbiters_client.post(
        "/api/orbiters/signups", json=_body("ada@studio.it", pixel_event_id=EVENT_ID)
    )

    assert response.status_code == 201, response.text
    assert len(pixel.calls) == 1
    event = pixel.event()
    # The same id the pixel used in the browser: OpenAI deduplicates on it, so the two
    # halves of this conversion are one conversion.
    assert event["id"] == EVENT_ID
    assert event["type"] == "registration_completed"
    assert event["source_url"] == "https://joinorbiters.com/orbiters"
    assert _row(orbiters_session, "ada@studio.it") == ("Ada", "Lovelace", None)


def test_the_click_identifier_and_the_browser_cookie_reach_the_event(
    orbiters_client: TestClient, pixel: RecordingHttp
) -> None:
    """`oppref` comes from the landing URL through the body; `__obref` is the SDK's own
    first-party cookie, which the browser sends to this endpoint too. Without them the
    server event is a conversion the platform cannot attribute to a click."""
    response = orbiters_client.post(
        "/api/orbiters/signups",
        json=_body("ada@studio.it", pixel_event_id=EVENT_ID, oppref="clic-123"),
        headers={
            # Sent as a header rather than through the client's cookie jar: the jar
            # applies its own domain and Secure policy, and what is under test is the
            # route reading the cookie, not httpx storing one.
            "Cookie": "__obref=ob-abc",
            "X-Real-IP": "203.0.113.7",
            "User-Agent": "Mozilla/5.0",
        },
    )

    assert response.status_code == 201, response.text
    event = pixel.event()
    assert event["oppref"] == "clic-123"
    assert event["user"] == {
        "obref": "ob-abc",
        "ip_address": "203.0.113.7",
        "user_agent": "Mozilla/5.0",
    }


def test_an_address_the_proxy_could_not_name_is_left_out_rather_than_invented(
    orbiters_client: TestClient, pixel: RecordingHttp
) -> None:
    """`_client_key` answers `"sconosciuto"` when there is no address to be had, which
    is fine for a rate-limit bucket and is not an IP. Forwarding it would put a word
    where a third party expects an address."""
    response = orbiters_client.post(
        "/api/orbiters/signups",
        json=_body("ada@studio.it", pixel_event_id=EVENT_ID),
        headers={"X-Real-IP": "non-un-indirizzo"},
    )

    assert response.status_code == 201, response.text
    assert "ip_address" not in (pixel.event().get("user") or {})


def test_the_subscribers_address_does_not_travel(
    orbiters_client: TestClient, pixel: RecordingHttp
) -> None:
    """Not raw, not hashed. The installation has not asked for it -- and pasting a pixel
    id must not be what starts sending an ad platform the mailing list."""
    orbiters_client.post(
        "/api/orbiters/signups", json=_body("ada@studio.it", pixel_event_id=EVENT_ID)
    )

    body = pixel.calls[-1][3].decode()
    assert "ada@studio.it" not in body
    assert hashed_email("ada@studio.it") not in body
    assert "Lovelace" not in body


def test_an_installation_without_a_pixel_sends_nothing(
    orbiters_client: TestClient, orbiters_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default state of the product. Not an error, and not a request to nowhere: no
    call is made at all."""
    calls: list[object] = []
    monkeypatch.setattr(
        orbiters_router,
        "pixel_from_settings",
        lambda settings: calls.append(settings) or None,  # type: ignore[func-returns-value]
    )
    response = orbiters_client.post("/api/orbiters/signups", json=_body("ada@studio.it"))

    assert response.status_code == 201, response.text
    assert _row(orbiters_session, "ada@studio.it") == ("Ada", "Lovelace", None)


def test_a_signup_without_a_pixel_event_id_still_converts(
    orbiters_client: TestClient, pixel: RecordingHttp
) -> None:
    """A client that posted without the pixel -- JavaScript off, a script, a curl. The
    event gets an id of its own, which makes it unpairable, and that is right: there is
    no browser event to pair it with."""
    response = orbiters_client.post("/api/orbiters/signups", json=_body("ada@studio.it"))

    assert response.status_code == 201, response.text
    assert pixel.event()["id"]


@pytest.mark.parametrize("failure", [{"status": 500}, {"raises": True}])
def test_a_failed_conversion_never_becomes_a_failed_signup(
    orbiters_client: TestClient,
    orbiters_session: Session,
    pixel: RecordingHttp,
    failure: dict[str, object],
) -> None:
    """OpenAI down, or refusing, or unreachable. The row is committed before the event
    is even built and the event runs after the response has been sent: the person who
    signed up is on the list and is told so."""
    pixel.status = int(failure.get("status", 200))  # type: ignore[arg-type]
    pixel.raises = bool(failure.get("raises", False))

    response = orbiters_client.post(
        "/api/orbiters/signups", json=_body("ada@studio.it", pixel_event_id=EVENT_ID)
    )

    assert response.status_code == 201, response.text
    assert response.json() == {"ok": True}
    assert _row(orbiters_session, "ada@studio.it") == ("Ada", "Lovelace", None)


def test_a_malformed_event_id_is_refused_before_anything_is_written(
    orbiters_client: TestClient, orbiters_session: Session, pixel: RecordingHttp
) -> None:
    """It is interpolated into a JSON body sent to a third party, so it is checked like
    every other field of this public body -- and a 422 means no row and no event."""
    response = orbiters_client.post(
        "/api/orbiters/signups",
        json=_body("ada@studio.it", pixel_event_id="../../etc/passwd"),
    )

    assert response.status_code == 422
    assert pixel.calls == []
    assert (
        orbiters_session.execute(
            text("SELECT count(*) FROM signups WHERE email = :email"),
            {"email": "ada@studio.it"},
        ).scalar()
        == 0
    )
