"""The MCP surface of slice 5B, and the shape of its asymmetry.

An agent that reads a mailbox is a different proposition from one that creates a
customer, and an agent that *fetches* from a mailbox is a different proposition again.
This file asserts where the line was drawn:

**Granted.** Reading what is already in the CRM -- the stored mirror in `gmail_messages`
-- and reading the state of the credential. Neither makes a Google call, neither spends
anybody's Gmail quota, and neither exercises anybody's consent.

**Refused, structurally.** Fetching (`sync`, `backfill`), connecting, disconnecting,
changing what the CRM keeps, and sending. None of them is a permission check inside a
registered tool, because a PAT inherits its owner's full role and never expires
(residuo R10): the only mechanism that holds is that the tool does not exist. The
durable list lives in `test_mcp_invoice_ban.py`, which owns the structural bans; what is
asserted here is the positive half -- exactly three Gmail tools, and no fourth.

The proof that the read tools never reach Google is the repository-root socket guard:
it fails any test that opens one, so a read tool that grew a fetch would fail this file
rather than pass it quietly.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.gmail.models import GmailMessage, GmailMessageLink, GoogleAccount
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_mcp.server import build_server

# 32 bytes of "k", base64. Written out rather than imported from
# `fakes.gmail_fixtures`: that package lives under `packages/core/tests`, which is only
# on `sys.path` once a test from that root has been collected, so importing it here
# would make this file pass in a full run and fail when run on its own.
TOKEN_KEY_B64 = "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s="

MAILBOX = "io@example.it"
CLIENT = "ada@acme.it"


def _payload(result: Any) -> Any:
    return result.structured_content or json.loads(result.content[0].text)


def gmail_settings() -> Settings:
    return Settings(
        google_client_id="cid.apps.googleusercontent.com",
        google_client_secret="the-secret",
        google_token_key=TOKEN_KEY_B64,
        public_url="https://crm.example.it",
        # `_env_file=None` so a developer's own .env cannot change what is asserted.
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def gmail_actor(mcp_session: Session) -> Actor:
    """An `mcp` actor with a real `users.id`.

    The conftest's `ADMIN` has `id=None`, and every Gmail service resolves the account
    through `repo.account_for_user(actor.id)` -- one mailbox per user -- so an actor
    without an id has no mailbox by construction.
    """
    user = User(
        email="agent-owner@example.test",
        password_hash="x",
        nome="Owner",
        ruolo="admin",
        attivo=True,
    )
    mcp_session.add(user)
    mcp_session.flush()
    return Actor(id=user.id, type="mcp", role="admin")


@pytest.fixture
def gmail_server(mcp_session: Session, gmail_actor: Actor, tmp_path: Path) -> Any:
    return build_server(
        lambda: mcp_session,
        lambda: gmail_actor,
        LocalFileStorage(tmp_path),
        settings=gmail_settings(),
    )


@pytest.fixture
def connected_account(mcp_session: Session, gmail_actor: Actor) -> GoogleAccount:
    account = GoogleAccount(
        user_id=gmail_actor.id,
        google_sub="sub-123",
        email_address=MAILBOX,
        # Opaque on purpose: nothing in this file decrypts them, and no tool may show
        # them.
        refresh_token_ciphertext=b"\x01\x02ciphertext",
        refresh_token_nonce=b"\x03\x04nonce",
        scopes_granted=list(REQUESTED_SCOPES),
        status="active",
    )
    mcp_session.add(account)
    mcp_session.flush()
    return account


@pytest.fixture
def filed_message(
    mcp_session: Session, connected_account: GoogleAccount
) -> Iterator[tuple[UUID, UUID]]:
    """One inbound message filed against one customer. Returns (customer id, message
    id) -- the two identifiers an agent would hold."""
    customer_id = uuid4()
    message = GmailMessage(
        google_account_id=connected_account.id,
        gmail_message_id="m-1",
        gmail_thread_id="t-1",
        direction="inbound",
        from_address=CLIENT,
        to_addresses=[MAILBOX],
        cc_addresses=[],
        subject="Preventivo per il rifacimento del sito",
        snippet="Ciao, ci mandi un preventivo",
        internal_date=datetime.now(UTC) - timedelta(days=2),
        body_text="Ciao, ci mandi un preventivo per il rifacimento del sito?",
        attachments=[{"name": "brief.pdf", "mime": "application/pdf", "size": 1024}],
    )
    mcp_session.add(message)
    mcp_session.flush()
    mcp_session.add(
        GmailMessageLink(gmail_message_id=message.id, entity_type="customer", entity_id=customer_id)
    )
    mcp_session.flush()
    yield customer_id, message.id


# --- what exists, and what does not ---------------------------------------------------


async def test_exactly_three_gmail_tools_exist_and_none_of_them_fetches(gmail_server: Any) -> None:
    """The positive half of the asymmetry, asserted as an equality rather than a subset:
    "and no others" is the claim, and a subset assertion would pass with a
    `sync_gmail` sitting next to them."""
    async with Client(gmail_server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert {name for name in names if "gmail" in name or "google" in name} == {
        "list_gmail_messages",
        "get_gmail_message",
        "describe_gmail_account",
    }


async def test_no_tool_can_send_anything(gmail_server: Any) -> None:
    """Spec 8.2 and 13, criterion 16. An email sent from your mailbox cannot be
    recalled and the client reads it as your words; an agent holding *read* of the mail
    and *send* in the same belt has the injection source and the exfiltration channel on
    one channel. The human presses Invia.

    Asserted on the substring and not only on a list of names: the point is that no tool
    sends, not that four particular spellings are absent."""
    async with Client(gmail_server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert not [name for name in names if "send" in name or "invia" in name]


async def test_no_tool_schema_accepts_a_gmail_search_string(gmail_server: Any) -> None:
    """Verified by schema and not only by name: a parameter called `filtro` that took a
    Gmail expression would be the same hole with better manners. Every guarantee in spec
    4 -- the address filter, the roster, "an empty roster issues no request" -- is one
    free-text parameter away from being nothing.

    `entity_type` is the only free-form string allowed, and it is a closed enum. Every
    identifier is a UUID, which carries `format` in its schema and is checked here for
    exactly that."""
    allowed_strings = {"entity_type"}
    async with Client(gmail_server) as client:
        tools = (await client.list_tools()).tools

    checked = 0
    for tool in tools:
        if "gmail" not in tool.name:
            continue
        for name, schema in (tool.input_schema or {}).get("properties", {}).items():
            checked += 1
            if schema.get("type") == "string" and "format" not in schema:
                assert name in allowed_strings, f"{tool.name}.{name} accetta testo libero"
    # A sweep over zero properties is a sweep that cannot fail.
    assert checked >= 4, checked


async def test_the_gmail_tools_are_absent_when_gmail_is_not_configured(server: Any) -> None:
    """Absent, not broken (spec 5.3). The `server` fixture builds with the process's own
    settings, and this repository has no `.env`, so this is the unconfigured
    installation -- the same one the whole suite runs under (spec 13, criterion 8)."""
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert not [name for name in names if "gmail" in name]
    # And the rest of the surface is untouched: "absent" must mean the Gmail tools, not
    # a server that failed to build.
    assert "create_customer" in names


# --- what the three tools actually answer ----------------------------------------------


async def test_list_gmail_messages_reads_the_stored_mirror(
    gmail_server: Any, filed_message: tuple[UUID, UUID]
) -> None:
    """The whole reason this tool may exist while `sync_gmail` may not: it reads rows
    this CRM already holds. No Google call, no quota, no consent exercised -- and the
    repository-root socket guard is what turns that from a claim into a test, because it
    fails any test that opens a socket."""
    customer_id, message_id = filed_message
    async with Client(gmail_server) as client:
        result = await client.call_tool(
            "list_gmail_messages",
            {"entity_type": "customer", "entity_id": str(customer_id)},
        )

    rows = _payload(result)
    rows = rows["result"] if isinstance(rows, dict) and "result" in rows else rows
    assert [row["id"] for row in rows] == [str(message_id)]
    assert rows[0]["da"] == CLIENT
    assert rows[0]["oggetto"] == "Preventivo per il rifacimento del sito"
    # The listing is a listing: the body belongs to `get_gmail_message`, so an agent
    # that only needs to know a conversation exists does not pull a customer's whole
    # correspondence into its context to find out.
    assert "corpo" not in rows[0]


async def test_get_gmail_message_returns_the_body_marked_as_untrusted(
    gmail_server: Any, filed_message: tuple[UUID, UUID]
) -> None:
    """The body is what makes this tool worth having -- an agent cannot answer "what did
    the client actually ask for" from a snippet -- and it is also the one place text
    written by somebody outside this CRM enters an agent's context. It is returned with
    a provenance marker for that reason, and the surface holds no send tool, so the
    injection source has no exfiltration channel next to it."""
    _customer_id, message_id = filed_message
    async with Client(gmail_server) as client:
        result = await client.call_tool("get_gmail_message", {"message_id": str(message_id)})

    body = _payload(result)
    assert body["corpo"] == "Ciao, ci mandi un preventivo per il rifacimento del sito?"
    assert body["allegati"][0]["name"] == "brief.pdf"
    assert "non attendibile" in body["provenienza"]


async def test_get_gmail_message_marks_our_own_mail_as_ours(
    gmail_server: Any, mcp_session: Session, connected_account: GoogleAccount
) -> None:
    """The other side of the marker, and the reason it is a field rather than a constant
    banner: text the owner of this CRM wrote is not somebody else's instruction, and
    labelling it as untrusted would train an agent to discount the one half of a thread
    it can rely on."""
    message = GmailMessage(
        google_account_id=connected_account.id,
        gmail_message_id="m-2",
        gmail_thread_id="t-1",
        direction="outbound",
        from_address=MAILBOX,
        to_addresses=[CLIENT],
        cc_addresses=[],
        subject="Re: Preventivo",
        snippet="Eccolo",
        internal_date=datetime.now(UTC),
        body_text="Eccolo, in allegato.",
        attachments=[],
    )
    mcp_session.add(message)
    mcp_session.flush()

    async with Client(gmail_server) as client:
        result = await client.call_tool("get_gmail_message", {"message_id": str(message.id)})

    assert "non attendibile" not in _payload(result)["provenienza"]


async def test_a_message_id_nobody_stored_is_guidance_not_a_stack_trace(
    gmail_server: Any,
) -> None:
    async with Client(gmail_server) as client:
        result = await client.call_tool("get_gmail_message", {"message_id": str(uuid4())})

    assert result.is_error
    rendered = result.content[0].text
    # `_guard` turns the `NotFound` into `to_agent_message`'s rendered guidance. What
    # must never appear is the raw pydantic/SDK shape with its English footer.
    assert "errors.pydantic.dev" not in rendered
    assert "gmail_message" in rendered


async def test_describe_gmail_account_tells_an_agent_to_stop_retrying(
    gmail_server: Any, mcp_session: Session, connected_account: GoogleAccount
) -> None:
    """The reason this tool is granted while `sync_gmail` is not. An agent that cannot
    see the credential's state answers a stale mirror as if it were current, or retries
    a fetch that will never succeed. This is the diagnosis; pressing Sincronizza is the
    person's half."""
    connected_account.status = "revoked"
    connected_account.last_error = "revocato da Google"
    mcp_session.flush()

    async with Client(gmail_server) as client:
        result = await client.call_tool("describe_gmail_account", {})

    health = _payload(result)
    assert health["banner"] == "revoked"
    assert health["account"]["email_address"] == MAILBOX
    assert "ricollegh" in health["banner_text"]


async def test_no_gmail_tool_answer_carries_a_credential(
    gmail_server: Any, filed_message: tuple[UUID, UUID]
) -> None:
    """The refresh token is a credential to a *third-party* account. It may not reach a
    tool result any more than it may reach a log line -- and a tool result is the one
    channel that ends up verbatim in a model's context and, from there, wherever that
    context is stored."""
    customer_id, message_id = filed_message
    async with Client(gmail_server) as client:
        answers = [
            await client.call_tool(
                "list_gmail_messages",
                {"entity_type": "customer", "entity_id": str(customer_id)},
            ),
            await client.call_tool("get_gmail_message", {"message_id": str(message_id)}),
            await client.call_tool("describe_gmail_account", {}),
        ]

    rendered = json.dumps([_payload(answer) for answer in answers], default=str)
    for forbidden in ("ciphertext", "nonce", "refresh_token", "the-secret", TOKEN_KEY_B64):
        assert forbidden not in rendered, forbidden
