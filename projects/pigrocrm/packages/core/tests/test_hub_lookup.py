"""The hub client never raises and never reaches a hub in a test (ORB-173).

Every path ends in a `MemberLookup`: the member, the non-member, a refused token, a
hub that is down, a body that is not the shape, and an installation with no token at
all. The HTTP seam is a fake that records the one request that would have left."""

import json

from pigrocrm.core.config import Settings
from pigrocrm.core.tenants.hub import LOOKUP_PATH, MemberLookup, lookup_member

TOKEN = "un-token-lungo-condiviso-con-l-hub"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "jwt_secret": "test-secret-for-the-core-test-suite-only",
        "registry_token": TOKEN,
        "hub_url": "https://joinorbiters.com/",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class FakeHub:
    """Answers what the test says and keeps the request it received."""

    def __init__(self, status: int = 200, body: object = None) -> None:
        self.status = status
        self.body = json.dumps(body).encode() if body is not None else b""
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.raises: Exception | None = None

    def __call__(self, method: str, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.calls.append((method, url, headers))
        if self.raises is not None:
            raise self.raises
        return self.status, self.body


def test_a_member_comes_back_with_the_two_names_and_one_get_left_with_the_bearer() -> None:
    hub = FakeHub(body={"membro": True, "nome": "Ada", "cognome": "Lovelace"})
    found = lookup_member(_settings(), "  Ada@Studio.it ", http=hub)
    assert found == MemberLookup(membro=True, nome="Ada", cognome="Lovelace")
    assert [(m, u) for m, u, _ in hub.calls] == [
        ("GET", f"https://joinorbiters.com{LOOKUP_PATH}?email=ada%40studio.it")
    ]
    assert hub.calls[0][2]["Authorization"] == f"Bearer {TOKEN}"


def test_a_non_member_is_a_plain_false() -> None:
    hub = FakeHub(body={"membro": False, "nome": None, "cognome": None})
    assert lookup_member(_settings(), "nessuno@example.org", http=hub) == MemberLookup(membro=False)


def test_a_refused_token_is_not_a_member_and_not_an_error() -> None:
    hub = FakeHub(status=401, body={"detail": "token non valido"})
    assert lookup_member(_settings(), "ada@studio.it", http=hub) == MemberLookup(membro=False)


def test_a_hub_that_is_down_is_not_a_member_and_not_an_error() -> None:
    hub = FakeHub()
    hub.raises = OSError("connection refused")
    assert lookup_member(_settings(), "ada@studio.it", http=hub) == MemberLookup(membro=False)


def test_a_body_that_is_not_the_shape_is_not_a_member() -> None:
    garbled = FakeHub()
    garbled.body = b"<html>not json</html>"
    assert lookup_member(_settings(), "ada@studio.it", http=garbled) == MemberLookup(membro=False)
    wrong_shape = FakeHub(body={"membro": "forse"})
    assert lookup_member(_settings(), "ada@studio.it", http=wrong_shape) == MemberLookup(
        membro=False
    )


def test_without_a_token_or_a_url_or_an_address_the_hub_is_never_asked() -> None:
    hub = FakeHub(body={"membro": True, "nome": "Ada", "cognome": "Lovelace"})
    assert lookup_member(_settings(registry_token=""), "ada@studio.it", http=hub) == MemberLookup(
        membro=False
    )
    assert lookup_member(_settings(hub_url=""), "ada@studio.it", http=hub) == MemberLookup(
        membro=False
    )
    assert lookup_member(_settings(), "   ", http=hub) == MemberLookup(membro=False)
    assert hub.calls == []


def test_the_real_transport_treats_a_closed_port_as_not_a_member() -> None:
    """No fake: the default `urllib` call against a loopback port nobody listens on.
    Refused at once, and the answer is the same `false` every other failure gives."""
    assert lookup_member(_settings(hub_url="http://127.0.0.1:9"), "ada@studio.it") == (
        MemberLookup(membro=False)
    )
