"""`discover_gmail_correspondents`: an opt-in tool, and the first that is about Gmail.

Everything `tools/gmail.py` grants reads the stored mirror; everything it refuses spends
the owner's Gmail quota under the owner's consent. Discovery is on the refused side of
that line by nature -- it asks Google a question -- and on the granted side by decision:
the installation that opened `mcp_full_access` has said its agent may spend what its
owner spends. So it lives in `tools/privileged.py`, appears only behind *both* switches
(full access, and a configured Gmail), and stores nothing: the roster of spec 4.2 widens
when a person adds an address, never because a tool found one.
"""

import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

# The in-memory Gmail lives with the core tests, which are a separate pytest root with
# no package of their own. Reached by path rather than duplicated: a second fake would be
# a second place for the two to disagree about what Gmail does.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "core" / "tests"))
from fakes.fake_gmail import FakeGmail, FakeMessage  # noqa: E402
from mcp import Client
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.gmail.crypto import seal
from pigrocrm.core.gmail.models import GmailMessage, GoogleAccount
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES
from pigrocrm.core.gmail.transport import GmailTransport
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_mcp.server import build_server
from pigrocrm_mcp.tools import privileged

TOOL = "discover_gmail_correspondents"
TOKEN_KEY_B64 = "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s="
MAILBOX = "io@example.it"
GOOGLE = {
    "google_client_id": "cid.apps.googleusercontent.com",
    "google_client_secret": "the-secret",
    "google_token_key": TOKEN_KEY_B64,
    "public_url": "https://crm.example.it",
}


def _settings(*, full_access: bool, gmail: bool) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        mcp_full_access=full_access,
        **(GOOGLE if gmail else {}),
    )


def _payload(result: Any) -> Any:
    return result.structured_content or json.loads(result.content[0].text)


def _mail(index: int, *, frm: str, to: str, thread: str) -> FakeMessage:
    return FakeMessage(
        id=f"m{index}",
        thread_id=thread,
        headers={
            "From": frm,
            "To": to,
            "Subject": f"Oggetto {index}",
            "Message-ID": f"<msg{index}@example.it>",
        },
        body_text="riservato",
        internal_date_ms=int((datetime.now(UTC) - timedelta(days=index)).timestamp() * 1000),
    )


@pytest.fixture
def owner(mcp_session: Session) -> Actor:
    """An `mcp` actor whose installation opened the switch, with a real `users.id`: the
    sync service resolves the mailbox through `account_for_user(actor.id)`."""
    user = User(
        email="agent-owner@example.test",
        password_hash="x",
        nome="Owner",
        ruolo="admin",
        attivo=True,
    )
    mcp_session.add(user)
    mcp_session.flush()
    return Actor(id=user.id, type="mcp", role="admin", full_access=True)


@pytest.fixture
def connected_account(mcp_session: Session, owner: Actor) -> GoogleAccount:
    ciphertext, nonce = seal("1//0gFixtureRefreshToken", base64.b64decode(TOKEN_KEY_B64))
    account = GoogleAccount(
        user_id=owner.id,
        google_sub="sub-123",
        email_address=MAILBOX,
        refresh_token_ciphertext=ciphertext,
        refresh_token_nonce=nonce,
        scopes_granted=list(REQUESTED_SCOPES),
        status="active",
    )
    mcp_session.add(account)
    mcp_session.flush()
    return account


@pytest.fixture
def fake_gmail(monkeypatch: pytest.MonkeyPatch) -> FakeGmail:
    """The transport seam, pointed at an in-memory Gmail. `GmailTransport(http=...)` is
    the production class with its network replaced, which is the seam every core test
    uses; here it is reached through the module that constructs it."""
    fake = FakeGmail()
    monkeypatch.setattr(
        privileged, "GmailTransport", lambda: GmailTransport(http=fake, sleep=lambda _: None)
    )
    return fake


@pytest.fixture
def open_server(mcp_session: Session, owner: Actor, tmp_path: Path) -> Any:
    return build_server(
        lambda: mcp_session,
        lambda: owner,
        LocalFileStorage(tmp_path),
        settings=_settings(full_access=True, gmail=True),
    )


def _example(session: Session, **overrides: object) -> Customer:
    fields: dict[str, object] = {
        "ragione_sociale": "Example Ltd",
        "sito_web": "https://www.example.com/",
    }
    fields.update(overrides)
    customer = Customer(**fields)
    session.add(customer)
    session.flush()
    return customer


# --- where it exists ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("full_access", "gmail", "present"),
    [(False, False, False), (True, False, False), (False, True, False), (True, True, True)],
)
async def test_the_tool_exists_only_behind_both_switches(
    mcp_session: Session, tmp_path: Path, full_access: bool, gmail: bool, present: bool
) -> None:
    """Two conditions, one tool. Without the switch it is a forbidden operation like the
    others; without Google there is no mailbox to ask, and a tool that answered
    409 on every call would be the "registered but broken" state both guards exist to
    prevent."""
    server = build_server(
        lambda: mcp_session,
        lambda: Actor(id=None, type="mcp", role="admin", full_access=full_access),
        LocalFileStorage(tmp_path),
        settings=_settings(full_access=full_access, gmail=gmail),
    )
    names = {tool.name for tool in await server.list_tools()}
    assert (TOOL in names) is present


async def test_the_tool_takes_a_customer_id_and_no_free_text(open_server: Any) -> None:
    """The domain comes from the customer record. A `dominio` or `query` parameter would
    be the free-text search spec 8.2 and 12 exclude, with a UUID standing next to it."""
    async with Client(open_server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    properties = (tools[TOOL].input_schema or {}).get("properties", {})
    assert set(properties) == {"customer_id"}
    assert properties["customer_id"].get("format") == "uuid"


# --- what it answers --------------------------------------------------------------------


async def test_discovery_answers_the_addresses_at_the_customer_domain(
    open_server: Any, mcp_session: Session, connected_account: GoogleAccount, fake_gmail: FakeGmail
) -> None:
    customer = _example(mcp_session)
    fake_gmail.messages["m1"] = _mail(
        1, frm="Marco Bianchi <marco@example.com>", to=MAILBOX, thread="t1"
    )
    fake_gmail.messages["m2"] = _mail(
        2, frm=MAILBOX, to="sarah@example.com, marco@example.com", thread="t1"
    )
    fake_gmail.messages["m3"] = _mail(3, frm="estraneo@altrove.com", to=MAILBOX, thread="t9")

    async with Client(open_server) as client:
        result = await client.call_tool(TOOL, {"customer_id": str(customer.id)})

    report = _payload(result)
    assert report["dominio"] == "example.com"
    rows = {row["indirizzo"]: row for row in report["corrispondenti"]}
    assert set(rows) == {"marco@example.com", "sarah@example.com"}
    assert rows["marco@example.com"]["nome"] == "Marco Bianchi"
    assert rows["marco@example.com"]["messaggi"] == 2
    assert rows["marco@example.com"]["gia_in_anagrafica"] is False
    # And every listing Gmail received was the domain clause: nothing an agent passed.
    listings = [request for request in fake_gmail.requests if request.is_messages_list]
    assert listings
    assert all(request.q == "(from:@example.com OR to:@example.com)" for request in listings)


async def test_discovery_stores_nothing(
    open_server: Any, mcp_session: Session, connected_account: GoogleAccount, fake_gmail: FakeGmail
) -> None:
    """Spec 4.2, unchanged: the mirror widens when a person puts an address on a Person,
    not because a tool found one."""
    customer = _example(mcp_session)
    fake_gmail.messages["m1"] = _mail(1, frm="marco@example.com", to=MAILBOX, thread="t1")

    async with Client(open_server) as client:
        await client.call_tool(TOOL, {"customer_id": str(customer.id)})

    assert mcp_session.execute(select(func.count()).select_from(GmailMessage)).scalar_one() == 0


async def test_a_customer_without_a_domain_gets_guidance_not_a_stack_trace(
    open_server: Any, mcp_session: Session, connected_account: GoogleAccount, fake_gmail: FakeGmail
) -> None:
    customer = _example(mcp_session, sito_web=None, email="ceo@gmail.com")

    async with Client(open_server) as client:
        result = await client.call_tool(TOOL, {"customer_id": str(customer.id)})

    assert result.is_error
    text = result.content[0].text
    assert "dominio" in text and "sito web" in text
    assert "Traceback" not in text
    # Refused before Google was asked anything.
    assert fake_gmail.requests == []
