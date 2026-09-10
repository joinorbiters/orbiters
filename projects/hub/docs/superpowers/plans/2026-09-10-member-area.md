# Member Area Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A freelancer who filled in the hub's wizard can get back in with a magic link by email, read what they sent, change it, replace their CV, and find the perks.

**Architecture:** Two new tables (`magic_link_tokens`, `member_sessions`) beside the admin's, a `MemberService` in `orbiters_core` that reuses the wizard's validation and the ORB-59 comment thread, a `mail.py` seam with a Resend sender over `urllib`, a `members` router under `/api/hub` with its own cookie `orbiters_user`, and four screens in the hub SPA's public shell that reuse the wizard's field components.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, FastAPI, pydantic 2, pytest + testcontainers; React 19, TanStack Router and Query, Tailwind 4, vitest + Testing Library.

**Spec:** `projects/hub/docs/superpowers/specs/2026-09-10-member-area-design.md`

## Global Constraints

- Everything runs from the repository root (`uv run ...`, `pnpm --filter hub ...`).
- Code, comments, tests, commits in English, first person, Conventional Commits, no AI trailer, no em dashes. Product strings (what a person reads: UI copy, API error sentences, the mail) in Italian, in the voice of `docs/design/positioning.md`: short, «noi» and «tu», no hype words, no exclamation marks.
- `orbiters_core` imports neither adapter; `orbiters_api` never imports `orbiters_mcp`; nothing imports `pigrocrm*` (ruff enforces it).
- Tests never open a socket to anything but the loopback (`projects/hub/conftest.py` enforces it): HTTP goes through the `HttpCall` seam with a fake.
- Commit with a pathspec (`git add <files>`), never `-A`. The last line of every commit body is `ORB-62.`
- Migration and models in their own commit. No `create_all` anywhere: the tests run the migrations.
- The member never sees `stato`, `note`, the UTM columns or another person's row.
- Cookie flags for the member session are the admin's: httpOnly, `secure=settings.cookie_secure`, `SameSite=Lax`, `Path=/`.
- Lint and types before every commit: `uv run ruff check projects/hub && uv run ruff format --check projects/hub && uv run mypy` for Python, `pnpm --filter hub lint` for the web.

---

## File structure

| File | Responsibility |
|---|---|
| `projects/hub/packages/core/src/orbiters_core/models.py` | add `MagicLinkToken`, `MemberSession` |
| `projects/hub/packages/core/migrations/versions/0005_member_area.py` | the two tables |
| `projects/hub/packages/core/src/orbiters_core/config.py` | five member-area settings |
| `projects/hub/packages/core/src/orbiters_core/http.py` | the `HttpCall` seam and `urllib_call`, moved out of `conversions.py` so two modules share one |
| `projects/hub/packages/core/src/orbiters_core/conversions.py` | imports the seam from `http.py`; behaviour unchanged |
| `projects/hub/packages/core/src/orbiters_core/mail.py` | `Mail`, `EmailSender`, `ResendSender`, `RecordingSender`, `sender_from_settings`, `magic_link_mail` |
| `projects/hub/packages/core/src/orbiters_core/schemas.py` | `FreelancerFields` extracted from `FreelancerCreate`; `MemberUpdate`, `MemberProfile`, `LinkRequest`, `EnterRequest` |
| `projects/hub/packages/core/src/orbiters_core/members.py` | `MemberService` |
| `projects/hub/packages/core/tests/test_mail.py`, `test_members.py` | core tests |
| `projects/hub/apps/api/src/orbiters_api/deps.py` | `MEMBER_COOKIE`, `get_member`, `MemberDep`, `get_sender`, `SenderDep` |
| `projects/hub/apps/api/src/orbiters_api/routers/members.py` | the seven routes |
| `projects/hub/apps/api/src/orbiters_api/main.py` | include the router |
| `projects/hub/apps/api/tests/test_member_api.py` | API tests |
| `projects/hub/apps/web/src/lib/api.ts` | `member` namespace, `MemberProfile`, `MemberUpdate` |
| `projects/hub/apps/web/src/lib/member.tsx` | hooks and the two converters |
| `projects/hub/apps/web/src/pages/member/Accedi.tsx`, `Entra.tsx`, `Guard.tsx`, `Area.tsx`, `Modifica.tsx` | the screens |
| `projects/hub/apps/web/src/router.tsx` | the routes |
| `projects/hub/apps/web/src/components/Shell.tsx`, `pages/Thanks.tsx` | «La tua area», the thank-you sentence |
| `projects/hub/.env.example`, `docker-compose.yml`, `AGENTS.md`, `docs/design/DECISIONS.md` | configuration and records |

---

### Task 1: The two tables

**Files:**
- Modify: `projects/hub/packages/core/src/orbiters_core/models.py` (append after `AdminSession`)
- Create: `projects/hub/packages/core/migrations/versions/0005_member_area.py`
- Test: `projects/hub/packages/core/tests/test_migrations.py` (existing, no change)

**Interfaces:**
- Produces: `orbiters_core.models.MagicLinkToken(freelancer_id: UUID, token_hash: str, expires_at: datetime, used_at: datetime | None)`, `orbiters_core.models.MemberSession(freelancer_id: UUID, token_hash: str, expires_at: datetime)`, both with `id` and `created_at` from the mixins.

- [ ] **Step 1: Run the migration test to see it green before the change**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_migrations.py`
Expected: 2 passed.

- [ ] **Step 2: Add the models**

Append to `models.py`, after `AdminSession`:

```python
# ---- the member area: how a freelancer gets back in ------------------------------------

TOKEN_HASH_LENGTH = 64  # sha256, hex


class MagicLinkToken(Base, PrimaryKeyMixin):
    """One link, one entry. The raw value travels in the mail and nowhere else; the row
    holds its sha256, a deadline (`magic_link_minutes`) and the moment it was spent, so a
    link forwarded or fetched twice opens nothing the second time. Hangs on the
    freelancer with `ON DELETE CASCADE`: deleting a person deletes their way in."""

    __tablename__ = "magic_link_tokens"

    freelancer_id: Mapped[UUID] = mapped_column(
        ForeignKey("freelancers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class MemberSession(Base, PrimaryKeyMixin):
    """The admin session's shape, for a freelancer: opaque cookie, hashed at rest, sliding
    expiry, revoked by deleting the row. A second table and a second cookie rather than
    a role column on `admin_sessions`, so a member token can never resolve to an admin."""

    __tablename__ = "member_sessions"

    freelancer_id: Mapped[UUID] = mapped_column(
        ForeignKey("freelancers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 3: Run the migration test to see it fail**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_migrations.py`
Expected: FAIL, `compare_metadata` reports two `add_table` entries.

- [ ] **Step 4: Write the migration**

`0005_member_area.py`:

```python
"""magic_link_tokens and member_sessions: a freelancer's way back into the hub

Revision ID: 0005
Revises: 0004

Two new tables, nothing conditional. Both hang on `freelancers.id` with ON DELETE
CASCADE: a deleted person takes their tokens and sessions with them. The shape is the
admin session's (0003) plus `used_at` on the token, which is what makes a link single
use (member area spec, 2026-09-10).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "freelancer_id",
            sa.Uuid(),
            sa.ForeignKey("freelancers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_magic_link_tokens_token_hash"),
    )
    op.create_index("ix_magic_link_tokens_freelancer_id", "magic_link_tokens", ["freelancer_id"])

    op.create_table(
        "member_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "freelancer_id",
            sa.Uuid(),
            sa.ForeignKey("freelancers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_member_sessions_token_hash"),
    )
    op.create_index("ix_member_sessions_freelancer_id", "member_sessions", ["freelancer_id"])


def downgrade() -> None:
    op.drop_index("ix_member_sessions_freelancer_id", table_name="member_sessions")
    op.drop_table("member_sessions")
    op.drop_index("ix_magic_link_tokens_freelancer_id", table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")
```

- [ ] **Step 5: Run the migration test to see it pass**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_migrations.py`
Expected: 2 passed. If `compare_metadata` still lists a difference (an index name, a constraint), align the model with the migration; the migration names above are the ones SQLAlchemy would generate.

- [ ] **Step 6: Lint, types, commit**

```bash
uv run ruff check projects/hub && uv run ruff format --check projects/hub && uv run mypy
git add projects/hub/packages/core/src/orbiters_core/models.py projects/hub/packages/core/migrations/versions/0005_member_area.py
git commit -m "feat(hub): magic_link_tokens and member_sessions, a freelancer's way back in

Two tables beside the admin's, both hanging on freelancers.id with ON DELETE
CASCADE. The token row carries used_at, which is what makes a link single use;
the session row is the admin session's shape in a table of its own, so a member
cookie can never resolve to an admin.

ORB-62."
```

---

### Task 2: Settings, the HTTP seam and the Resend sender

**Files:**
- Modify: `projects/hub/packages/core/src/orbiters_core/config.py`
- Create: `projects/hub/packages/core/src/orbiters_core/http.py`
- Modify: `projects/hub/packages/core/src/orbiters_core/conversions.py` (import the seam from `http.py`)
- Create: `projects/hub/packages/core/src/orbiters_core/mail.py`
- Test: `projects/hub/packages/core/tests/test_mail.py`

**Interfaces:**
- Produces: `Settings.resend_api_key: str`, `Settings.mail_from: str`, `Settings.hub_url: str`, `Settings.magic_link_minutes: int`, `Settings.member_session_days: int`; `orbiters_core.http.HttpCall`, `orbiters_core.http.urllib_call`, `orbiters_core.http.NETWORK_ERROR_STATUS`, `orbiters_core.http.HTTP_TIMEOUT_SECONDS`; `orbiters_core.mail.Mail(to, subject, text)`, `EmailSender.send(mail) -> bool`, `ResendSender(api_key, sender, http=None)`, `RecordingSender().sent: list[Mail]`, `sender_from_settings(settings) -> EmailSender | None`, `magic_link_mail(to, link, minutes) -> Mail`.

- [ ] **Step 1: Write the failing tests**

`test_mail.py`:

```python
"""What leaves the process when a member asks for a link, and what a test sees instead.

The network is the only thing faked, as in `test_conversions.py`: the URL, the header,
the JSON and the failure classification run for real.
"""

import json

from orbiters_core.config import Settings
from orbiters_core.mail import (
    RESEND_URL,
    Mail,
    RecordingSender,
    ResendSender,
    magic_link_mail,
    sender_from_settings,
)

KEY = "re_non_una_chiave_vera"
FROM = "Orbiters <ciao@joinorbiters.com>"


class FakeHttp:
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
        return self.status, b'{"id":"x"}'


def test_resend_posts_one_json_object_with_the_bearer_key() -> None:
    http = FakeHttp()
    sender = ResendSender(KEY, FROM, http=http)
    mail = Mail(to="ada@studio.it", subject="Il tuo accesso a Orbiters", text="ciao")
    assert sender.send(mail) is True
    method, url, headers, body = http.calls[0]
    assert (method, url) == ("POST", RESEND_URL)
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {
        "from": FROM,
        "to": ["ada@studio.it"],
        "subject": "Il tuo accesso a Orbiters",
        "text": "ciao",
    }


def test_resend_answers_false_and_never_raises_on_any_failure() -> None:
    mail = Mail(to="ada@studio.it", subject="x", text="y")
    assert ResendSender(KEY, FROM, http=FakeHttp(status=422)).send(mail) is False
    assert ResendSender(KEY, FROM, http=FakeHttp(status=500)).send(mail) is False
    assert ResendSender(KEY, FROM, http=FakeHttp(raises=True)).send(mail) is False


def test_the_recording_sender_keeps_what_was_sent() -> None:
    sender = RecordingSender()
    mail = Mail(to="ada@studio.it", subject="x", text="y")
    assert sender.send(mail) is True
    assert sender.sent == [mail]


def test_no_key_means_no_sender() -> None:
    assert sender_from_settings(Settings(_env_file=None)) is None  # type: ignore[call-arg]
    configured = sender_from_settings(
        Settings(resend_api_key=KEY, _env_file=None)  # type: ignore[call-arg]
    )
    assert isinstance(configured, ResendSender)


def test_the_magic_link_mail_carries_the_link_and_how_long_it_lasts() -> None:
    mail = magic_link_mail("ada@studio.it", "https://joinorbiters.com/hub/entra?t=abc", 15)
    assert mail.to == "ada@studio.it"
    assert mail.subject == "Il tuo accesso a Orbiters"
    assert "https://joinorbiters.com/hub/entra?t=abc" in mail.text
    assert "15 minuti" in mail.text
    assert "una volta sola" in mail.text
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_mail.py`
Expected: FAIL, `ModuleNotFoundError: orbiters_core.mail`.

- [ ] **Step 3: Add the settings**

In `config.py`, after `admin_session_days`:

```python
    # --- the member area -------------------------------------------------------------
    # Resend sends the magic link. An empty key means no sender, and the API answers the
    # link request with a 503 sentence rather than pretending a mail went out: the key
    # lives in the server's `.env` only (`.env.example`).
    resend_api_key: str = ""
    mail_from: str = "Orbiters <ciao@joinorbiters.com>"
    # Where the SPA answers, for the link in the mail: `{hub_url}/entra?t=...`. Local
    # development points it at the Vite dev server.
    hub_url: str = "https://joinorbiters.com/hub"
    magic_link_minutes: int = 15
    # Sliding, as the admin's.
    member_session_days: int = 30
```

- [ ] **Step 4: Move the HTTP seam into `http.py`**

Create `http.py` with the seam that `conversions.py` defines today, moved verbatim: the `HttpCall` type alias, `HTTP_TIMEOUT_SECONDS`, `NETWORK_ERROR_STATUS` with their comments, and the function currently named `_urllib_call` renamed `urllib_call`. Then in `conversions.py` delete those definitions and import them:

```python
from orbiters_core.http import HTTP_TIMEOUT_SECONDS, NETWORK_ERROR_STATUS, HttpCall, urllib_call
```

Replace every `_urllib_call` in `conversions.py` with `urllib_call`. Keep `NETWORK_ERROR_STATUS` importable from `orbiters_core.conversions` (the re-export above does it: `test_conversions.py` imports it from there). Remove the now unused `urllib.error`, `urllib.request` imports from `conversions.py` if nothing else uses them; `ruff` will say. Module docstring for `http.py`:

```python
"""One HTTP seam for everything the hub sends out: the conversions pixel and the mail.

`HttpCall` is `(method, url, headers, body) -> (status, body)`. Production hands
`urllib_call`; a test hands a fake and reads what would have left. No dependency, no
retry, and a network error travels as `NETWORK_ERROR_STATUS` rather than as a second
failure path, the convention PigroCRM's transports set.
"""
```

Run: `uv run pytest -q projects/hub/packages/core/tests/test_conversions.py`
Expected: all passed, unchanged count.

- [ ] **Step 5: Write `mail.py`**

```python
"""Outbound mail: a seam, one provider, and the one text the hub sends today.

The seam exists so tests never send and production never guesses: `sender_from_settings`
answers `None` without a key, and the API turns that into a 503 sentence rather than a
mail that does not arrive. Like `conversions.py`, nothing here raises past `send` and
nothing logs an address or the key.
"""

import json
from dataclasses import dataclass
from typing import Protocol

from orbiters_core.config import Settings
from orbiters_core.http import HttpCall, urllib_call

RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class Mail:
    """Plain text only: a login link needs no HTML, and plain text is what arrives."""

    to: str
    subject: str
    text: str


class EmailSender(Protocol):
    def send(self, mail: Mail) -> bool:
        """`True` when the provider accepted it. Never raises."""
        ...


class RecordingSender:
    """Keeps every mail in a list. For tests, and for reading the link in development."""

    def __init__(self) -> None:
        self.sent: list[Mail] = []

    def send(self, mail: Mail) -> bool:
        self.sent.append(mail)
        return True


class ResendSender:
    """Resend's `POST /emails`: one JSON object, the key as a bearer token."""

    def __init__(self, api_key: str, sender: str, http: HttpCall | None = None) -> None:
        self.api_key = api_key
        self.sender = sender
        self.http = http or urllib_call

    def send(self, mail: Mail) -> bool:
        payload = json.dumps(
            {"from": self.sender, "to": [mail.to], "subject": mail.subject, "text": mail.text}
        ).encode()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            status, _ = self.http("POST", RESEND_URL, headers, payload)
        except Exception:  # noqa: BLE001 - the seam's contract is "never raises"
            return False
        return 200 <= status < 300


def sender_from_settings(settings: Settings) -> EmailSender | None:
    if not settings.resend_api_key:
        return None
    return ResendSender(settings.resend_api_key, settings.mail_from)


def magic_link_mail(to: str, link: str, minutes: int) -> Mail:
    """The one mail the hub sends: the link, how long it lasts, and that ignoring it is
    fine. In the voice of `docs/design/positioning.md`."""
    text = (
        "Ciao,\n"
        "\n"
        "questo è il link per entrare nella tua area su Orbiters:\n"
        "\n"
        f"{link}\n"
        "\n"
        f"Vale {minutes} minuti e funziona una volta sola. Se non l'hai chiesto tu, ignora "
        "questa mail: non succede niente.\n"
        "\n"
        "Noi di Orbiters\n"
    )
    return Mail(to=to, subject="Il tuo accesso a Orbiters", text=text)
```

If ruff refuses the bare `except Exception`, use the same exception set `urllib_call` catches plus `OSError`, and say so in the comment.

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_mail.py projects/hub/packages/core/tests/test_conversions.py`
Expected: all passed.

- [ ] **Step 7: Lint, types, commit**

```bash
uv run ruff check projects/hub && uv run ruff format --check projects/hub && uv run mypy
git add projects/hub/packages/core/src/orbiters_core/config.py projects/hub/packages/core/src/orbiters_core/http.py projects/hub/packages/core/src/orbiters_core/conversions.py projects/hub/packages/core/src/orbiters_core/mail.py projects/hub/packages/core/tests/test_mail.py
git commit -m "feat(hub): the hub can send a mail through Resend, behind a seam tests never cross

Mail, EmailSender, ResendSender over urllib and a RecordingSender for tests.
Without a key there is no sender, and the caller decides what that means.
The HTTP seam the conversions pixel used moves to http.py so both share it;
the pixel's behaviour and its tests are unchanged.

ORB-62."
```

---

### Task 3: The schemas the member reads and writes

**Files:**
- Modify: `projects/hub/packages/core/src/orbiters_core/schemas.py`
- Test: `projects/hub/packages/core/tests/test_members.py` (created here, extended in Task 4)

**Interfaces:**
- Produces: `FreelancerFields` (base with `nome`, `cognome`, `linkedin_url`, `tariffa_giornaliera`, `posizione`, `remoto`, `links` and their validators), `FreelancerCreate(FreelancerFields)` unchanged in behaviour, `MemberUpdate(FreelancerFields)`, `MemberProfile`, `LinkRequest(email: EmailStr)`, `EnterRequest(token: str)`.

- [ ] **Step 1: Write the failing tests**

`test_members.py`:

```python
"""The member area: a freelancer's way back in, and what they may change once in."""

import pytest
from pydantic import ValidationError

from orbiters_core.schemas import FreelancerCreate, MemberProfile, MemberUpdate

GOOD = {
    "nome": "Ada",
    "cognome": "Lovelace",
    "linkedin_url": "https://www.linkedin.com/in/ada",
    "tariffa_giornaliera": "450",
    "posizione": "Backend developer",
    "remoto": "remoto",
    "links": ["https://github.com/ada", " "],
}


def test_member_update_applies_the_wizards_rules_and_nothing_else() -> None:
    update = MemberUpdate(**GOOD)
    assert update.links == ["https://github.com/ada"]
    for bad in (
        {**GOOD, "linkedin_url": "http://www.linkedin.com/in/ada"},
        {**GOOD, "tariffa_giornaliera": "0"},
        {**GOOD, "posizione": "   "},
        {**GOOD, "remoto": "da casa"},
        {**GOOD, "links": ["ftp://x.it"]},
        {**GOOD, "email": "ada@studio.it"},
        {**GOOD, "stato": "attivo"},
    ):
        with pytest.raises(ValidationError):
            MemberUpdate(**bad)
    # The wizard still accepts what it accepted: the base class changed, the rules did not.
    assert FreelancerCreate(**GOOD, email="ada@studio.it").links == ["https://github.com/ada"]


def test_member_profile_carries_no_admin_field() -> None:
    fields = set(MemberProfile.model_fields)
    assert {"nome", "cognome", "email", "cv_filename", "cv_size", "links"} <= fields
    assert not fields & {"stato", "note", "utm_source", "utm_campaign", "cv_bytes"}
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_members.py`
Expected: FAIL, `ImportError: MemberProfile`.

- [ ] **Step 3: Extract `FreelancerFields` and add the new schemas**

In `schemas.py`, replace the `FreelancerCreate` class with:

```python
class FreelancerFields(BaseModel):
    """The seven answers the wizard asks for and the person may later change. One set of
    rules for the wizard (`FreelancerCreate`) and the member area (`MemberUpdate`), so
    the two can never accept different things."""

    model_config = ConfigDict(extra="forbid")

    nome: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    cognome: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    linkedin_url: SafeStr | None = Field(default=None, max_length=LINKEDIN_URL_MAX_LENGTH)
    tariffa_giornaliera: Decimal = Field(
        max_digits=7, decimal_places=2, ge=TARIFFA_MIN, le=TARIFFA_MAX
    )
    posizione: SafeStr = Field(min_length=1, max_length=POSIZIONE_MAX_LENGTH)
    remoto: Remoto
    links: list[SafeStr] = Field(default_factory=list, max_length=LINKS_MAX)

    @field_validator("nome", "cognome", "posizione", mode="after")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        return _clean_text(value, what="un valore")

    @field_validator("linkedin_url", mode="after")
    @classmethod
    def _linkedin(cls, value: str | None) -> str | None:
        return SignupCreate._linkedin(value)

    @field_validator("links", mode="after")
    @classmethod
    def _links(cls, value: list[str]) -> list[str]:
        cleaned = [_https_url(link) for link in value if link.strip()]
        if any(len(link) > LINK_MAX_LENGTH for link in cleaned):
            raise ValueError(f"un link può avere al massimo {LINK_MAX_LENGTH} caratteri")
        return cleaned


class FreelancerCreate(FreelancerFields):
    """What the wizard collects. The CV travels beside this body, not inside it: the API
    takes it as a multipart file and hands the bytes to the service with this schema."""

    email: EmailStr
    utm: SignupUtm | None = None


class MemberUpdate(FreelancerFields):
    """What a member changes about themselves: the wizard's answers, never the email
    (it is the identity the link proved) and never the admin's fields."""
```

Then, after `CommentCreate`, add:

```python
class MemberProfile(BaseModel):
    """The row as its owner reads it: what they gave, and nothing the admin wrote.
    No `stato`, no `note`, no attribution, and never the CV bytes."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    cognome: str
    email: str
    linkedin_url: str | None
    cv_filename: str
    cv_size: int
    tariffa_giornaliera: Decimal
    posizione: str
    remoto: str
    links: list[str]
    created_at: datetime
    updated_at: datetime


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class EnterRequest(BaseModel):
    """The raw token from the link. `token_urlsafe(32)` is 43 characters; the bounds
    leave room without accepting a paragraph."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
```

- [ ] **Step 4: Run the core suite to see everything pass**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_members.py projects/hub/packages/core/tests/test_freelancers_companies.py`
Expected: all passed (the wizard's tests prove the extraction changed nothing).

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check projects/hub && uv run ruff format --check projects/hub && uv run mypy
git add projects/hub/packages/core/src/orbiters_core/schemas.py projects/hub/packages/core/tests/test_members.py
git commit -m "refactor(hub): the wizard's seven answers are one schema the member area shares

FreelancerFields holds the fields and validators FreelancerCreate had;
FreelancerCreate adds the email and the attribution, MemberUpdate adds nothing.
MemberProfile is the row as its owner reads it, with no admin field on it.

ORB-62."
```

---

### Task 4: `MemberService`

**Files:**
- Create: `projects/hub/packages/core/src/orbiters_core/members.py`
- Test: `projects/hub/packages/core/tests/test_members.py` (extend)

**Interfaces:**
- Consumes: `MagicLinkToken`, `MemberSession` (Task 1); `Settings.hub_url`, `magic_link_minutes`, `member_session_days`, `magic_link_mail` (Task 2); `MemberProfile`, `MemberUpdate` (Task 3); `CommentService.add(entity_type, entity_id, testo, autore)`; `check_cv(content, filename, mime) -> (filename, mime)` from `freelancers.py`.
- Produces: `MemberService(session, settings)` with `request_link(email) -> Mail | None`, `enter(raw_token) -> tuple[MemberProfile, str] | None`, `resolve(raw) -> MemberProfile | None`, `close_session(raw) -> None`, `profile(freelancer_id) -> MemberProfile`, `update(freelancer_id, data: MemberUpdate) -> MemberProfile`, `replace_cv(freelancer_id, content, filename, mime) -> MemberProfile`, `cv(freelancer_id) -> CvFile`.

- [ ] **Step 1: Extend the tests**

Append to `test_members.py`:

```python
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from orbiters_core.comments import CommentService
from orbiters_core.config import Settings
from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.freelancers import FreelancerService
from orbiters_core.members import MemberService
from orbiters_core.models import MagicLinkToken, MemberSession

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"


@pytest.fixture
def members(hub_engine: Engine, hub_session: Session) -> MemberService:
    settings = Settings(
        database_url=hub_engine.url.render_as_string(hide_password=False),
        hub_url="http://localhost:5180/hub",
        _env_file=None,  # type: ignore[call-arg]
    )
    yield MemberService(hub_session, settings)  # type: ignore[misc]
    hub_session.rollback()
    for table in ("member_sessions", "magic_link_tokens", "comments", "freelancers"):
        hub_session.execute(text(f"DELETE FROM {table}"))
    hub_session.commit()


def _apply(session: Session, email: str = "ada@studio.it") -> UUID:
    return FreelancerService(session).apply(
        FreelancerCreate(**GOOD, email=email), PDF, "Ada CV.pdf", "application/pdf"
    ).id


def _token_from(mail_text: str) -> str:
    match = re.search(r"/entra\?t=([A-Za-z0-9_-]+)", mail_text)
    assert match, mail_text
    return match.group(1)


def test_a_link_is_written_only_for_an_address_that_applied(
    members: MemberService, hub_session: Session
) -> None:
    assert members.request_link("nessuno@studio.it") is None
    assert hub_session.scalar(select(MagicLinkToken)) is None

    _apply(hub_session)
    mail = members.request_link("  ADA@studio.it ")
    assert mail is not None and mail.to == "ada@studio.it"
    assert "http://localhost:5180/hub/entra?t=" in mail.text
    row = hub_session.scalar(select(MagicLinkToken))
    assert row is not None and row.used_at is None
    assert row.token_hash != _token_from(mail.text) and len(row.token_hash) == 64


def test_a_link_opens_a_session_once_and_never_twice(
    members: MemberService, hub_session: Session
) -> None:
    _apply(hub_session)
    mail = members.request_link("ada@studio.it")
    assert mail is not None
    raw = _token_from(mail.text)

    outcome = members.enter(raw)
    assert outcome is not None
    profile, session_token = outcome
    assert profile.email == "ada@studio.it"
    assert members.resolve(session_token) is not None
    assert members.enter(raw) is None, "a spent link opens nothing"
    assert members.enter("non-un-token-vero-ma-lungo-abbastanza") is None
    assert members.enter("") is None


def test_an_expired_link_opens_nothing_and_is_swept_by_the_next_request(
    members: MemberService, hub_session: Session
) -> None:
    _apply(hub_session)
    mail = members.request_link("ada@studio.it")
    assert mail is not None
    row = hub_session.scalar(select(MagicLinkToken))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    hub_session.commit()
    assert members.enter(_token_from(mail.text)) is None

    members.request_link("ada@studio.it")
    tokens = hub_session.scalars(select(MagicLinkToken)).all()
    assert len(tokens) == 1 and tokens[0].id != row.id


def test_a_member_session_is_hashed_sliding_and_closable(
    members: MemberService, hub_session: Session
) -> None:
    _apply(hub_session)
    mail = members.request_link("ada@studio.it")
    assert mail is not None
    outcome = members.enter(_token_from(mail.text))
    assert outcome is not None
    _, raw = outcome
    row = hub_session.scalar(select(MemberSession))
    assert row is not None and row.token_hash != raw and len(row.token_hash) == 64
    row.expires_at = row.expires_at - timedelta(days=1)
    hub_session.commit()
    before = row.expires_at
    assert members.resolve(raw) is not None
    hub_session.refresh(row)
    assert row.expires_at > before

    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    hub_session.commit()
    assert members.resolve(raw) is None
    assert hub_session.scalar(select(MemberSession)) is None

    outcome = members.enter(_token_from(members.request_link("ada@studio.it").text))  # type: ignore[union-attr]
    assert outcome is not None
    members.close_session(outcome[1])
    assert members.resolve(outcome[1]) is None
    assert members.resolve(None) is None


def test_an_update_changes_the_row_and_leaves_one_comment_naming_what_moved(
    members: MemberService, hub_session: Session
) -> None:
    freelancer_id = _apply(hub_session)
    FreelancerService(hub_session).set_status(
        freelancer_id, StatusChange(stato="contattato", note="da sentire")
    )

    unchanged = members.update(freelancer_id, MemberUpdate(**GOOD))
    assert unchanged.tariffa_giornaliera == Decimal("450")
    assert CommentService(hub_session).list("freelancer", freelancer_id) == []

    changed = members.update(
        freelancer_id,
        MemberUpdate(**{**GOOD, "tariffa_giornaliera": "500", "links": []}),
    )
    assert changed.tariffa_giornaliera == Decimal("500") and changed.links == []
    thread = CommentService(hub_session).list("freelancer", freelancer_id)
    assert len(thread) == 1
    assert thread[0].testo == "Profilo aggiornato dalla persona: tariffa giornaliera, link"
    assert thread[0].autore == "Ada Lovelace"

    admin_view = FreelancerService(hub_session).get(freelancer_id)
    assert (admin_view.stato, admin_view.note) == ("contattato", "da sentire")


def test_a_new_cv_is_checked_like_the_wizards_and_leaves_its_comment(
    members: MemberService, hub_session: Session
) -> None:
    freelancer_id = _apply(hub_session)
    with pytest.raises(ValidationFailed) as refused:
        members.replace_cv(freelancer_id, b"non un pdf", "cv.pdf", "application/pdf")
    assert refused.value.details["field"] == "cv"

    new_pdf = PDF + b"\n% versione 2\n"
    profile = members.replace_cv(freelancer_id, new_pdf, "Ada 2026.pdf", "application/pdf")
    assert (profile.cv_filename, profile.cv_size) == ("Ada 2026.pdf", len(new_pdf))
    assert members.cv(freelancer_id).content == new_pdf
    thread = CommentService(hub_session).list("freelancer", freelancer_id)
    assert [comment.testo for comment in thread] == ["CV aggiornato dalla persona"]


def test_a_row_that_is_not_there_is_not_found(members: MemberService) -> None:
    missing = UUID("00000000-0000-7000-8000-000000000000")
    with pytest.raises(NotFound):
        members.profile(missing)
    with pytest.raises(NotFound):
        members.update(missing, MemberUpdate(**GOOD))
```

Add `StatusChange` to the `orbiters_core.schemas` import at the top of the file.

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_members.py`
Expected: FAIL, `ModuleNotFoundError: orbiters_core.members`.

- [ ] **Step 3: Write `members.py`**

```python
"""The member area: how a freelancer gets back in, and what they may change once in.

The way in is a magic link (member area spec, 2026-09-10): the person types the address
they gave the wizard, a one-time token goes out by mail, the link opens a session. No
password anywhere. Sessions are the admin's shape in a table of their own. Every change
the person makes is a comment in the row's thread (ORB-59), so the admin sees what moved
without an audit table. The service never sends a mail: it returns the one to send, and
the adapter decides how, so the same code path answers whether the address exists or not.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from orbiters_core.comments import CommentService
from orbiters_core.config import Settings
from orbiters_core.errors import NotFound
from orbiters_core.freelancers import check_cv
from orbiters_core.mail import Mail, magic_link_mail
from orbiters_core.models import AUTORE_MAX_LENGTH, Freelancer, MagicLinkToken, MemberSession
from orbiters_core.schemas import CvFile, MemberProfile, MemberUpdate

ENTITY = "freelancer"
# What the comment calls each field, in the admin's language, in the wizard's order.
FIELD_LABELS: dict[str, str] = {
    "nome": "nome",
    "cognome": "cognome",
    "linkedin_url": "profilo LinkedIn",
    "tariffa_giornaliera": "tariffa giornaliera",
    "posizione": "posizione",
    "remoto": "modalità di lavoro",
    "links": "link",
}


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class MemberService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # ---- the way in ----------------------------------------------------------------

    def request_link(self, email: str) -> Mail | None:
        """The mail to send, or `None` when nobody with that address applied. Sweeps the
        person's spent and expired tokens first: nothing needs a cron."""
        row = self._by_email(email.strip().lower())
        if row is None:
            return None
        now = datetime.now(UTC)
        self.session.execute(
            delete(MagicLinkToken).where(
                MagicLinkToken.freelancer_id == row.id,
                or_(MagicLinkToken.used_at.is_not(None), MagicLinkToken.expires_at <= now),
            )
        )
        raw = secrets.token_urlsafe(32)
        self.session.add(
            MagicLinkToken(
                freelancer_id=row.id,
                token_hash=_hash(raw),
                expires_at=now + timedelta(minutes=self.settings.magic_link_minutes),
            )
        )
        self.session.commit()
        link = f"{self.settings.hub_url.rstrip('/')}/entra?t={raw}"
        return magic_link_mail(row.email, link, self.settings.magic_link_minutes)

    def enter(self, raw_token: str) -> tuple[MemberProfile, str] | None:
        """The profile and the raw session token for the cookie, or `None` for a wrong,
        spent or expired link. The token is marked used in the same commit that opens
        the session, so a link fetched twice opens one session."""
        if not raw_token:
            return None
        now = datetime.now(UTC)
        token = self.session.scalar(
            select(MagicLinkToken).where(MagicLinkToken.token_hash == _hash(raw_token))
        )
        if token is None or token.used_at is not None or token.expires_at <= now:
            return None
        row = self.session.get(Freelancer, token.freelancer_id)
        if row is None:
            return None
        token.used_at = now
        raw_session = secrets.token_urlsafe(32)
        self.session.add(
            MemberSession(
                freelancer_id=row.id, token_hash=_hash(raw_session), expires_at=self._deadline(now)
            )
        )
        self.session.commit()
        return MemberProfile.model_validate(row), raw_session

    def resolve(self, raw: str | None) -> MemberProfile | None:
        """The member behind a cookie, or `None`. Slides the expiry on every hit and
        forgets a session past its deadline the moment it is presented."""
        if not raw:
            return None
        session_row = self.session.scalar(
            select(MemberSession).where(MemberSession.token_hash == _hash(raw))
        )
        if session_row is None:
            return None
        now = datetime.now(UTC)
        if session_row.expires_at <= now:
            self.session.delete(session_row)
            self.session.commit()
            return None
        row = self.session.get(Freelancer, session_row.freelancer_id)
        if row is None:
            return None
        session_row.expires_at = self._deadline(now)
        self.session.commit()
        return MemberProfile.model_validate(row)

    def close_session(self, raw: str | None) -> None:
        if not raw:
            return
        session_row = self.session.scalar(
            select(MemberSession).where(MemberSession.token_hash == _hash(raw))
        )
        if session_row is not None:
            self.session.delete(session_row)
            self.session.commit()

    # ---- what they see and change -----------------------------------------------------

    def profile(self, freelancer_id: UUID) -> MemberProfile:
        return MemberProfile.model_validate(self._require(freelancer_id))

    def update(self, freelancer_id: UUID, data: MemberUpdate) -> MemberProfile:
        """Applies the seven answers and leaves one comment naming the ones that moved,
        signed with the person's name after the change. Nothing moved, no comment.
        `stato`, `note` and the attribution are never touched here."""
        row = self._require(freelancer_id)
        changed: list[str] = []
        for field, label in FIELD_LABELS.items():
            value = getattr(data, field)
            if field == "links":
                value = list(value)
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed.append(label)
        if not changed:
            return MemberProfile.model_validate(row)
        self.session.commit()
        self._comment(row, f"Profilo aggiornato dalla persona: {', '.join(changed)}")
        return MemberProfile.model_validate(row)

    def replace_cv(
        self, freelancer_id: UUID, content: bytes, filename: str, mime: str
    ) -> MemberProfile:
        """The same check as the wizard's (`check_cv`), then the bytes replace the old
        ones and the thread says so."""
        filename, mime = check_cv(content, filename, mime)
        row = self._require(freelancer_id)
        row.cv_bytes, row.cv_filename, row.cv_mime, row.cv_size = (
            content,
            filename,
            mime,
            len(content),
        )
        self.session.commit()
        self._comment(row, "CV aggiornato dalla persona")
        return MemberProfile.model_validate(row)

    def cv(self, freelancer_id: UUID) -> CvFile:
        row = self._require(freelancer_id)
        return CvFile(filename=row.cv_filename, mime=row.cv_mime, content=row.cv_bytes)

    # ---- helpers ---------------------------------------------------------------------

    def _comment(self, row: Freelancer, text: str) -> None:
        author = f"{row.nome} {row.cognome}"[:AUTORE_MAX_LENGTH]
        CommentService(self.session).add(ENTITY, row.id, text, author)

    def _deadline(self, now: datetime | None = None) -> datetime:
        return (now or datetime.now(UTC)) + timedelta(days=self.settings.member_session_days)

    def _require(self, freelancer_id: UUID) -> Freelancer:
        row = self.session.get(Freelancer, freelancer_id)
        if row is None:
            raise NotFound(ENTITY, freelancer_id)
        return row

    def _by_email(self, email: str) -> Freelancer | None:
        return self.session.scalar(select(Freelancer).where(func.lower(Freelancer.email) == email))
```

- [ ] **Step 4: Run to see them pass**

Run: `uv run pytest -q projects/hub/packages/core/tests/test_members.py`
Expected: all passed. If the `Decimal` comparison in `update` reports a change on equal values (`Decimal("450.00") != Decimal("450")` is `False`, so it should not), compare with `==` on `Decimal` and leave strings as they are.

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check projects/hub && uv run ruff format --check projects/hub && uv run mypy
git add projects/hub/packages/core/src/orbiters_core/members.py projects/hub/packages/core/tests/test_members.py
git commit -m "feat(hub): a freelancer can ask for a link, enter with it once, and change their answers

MemberService writes a hashed one-time token and returns the mail to send,
opens a sliding session when the link comes back, and applies the wizard's
seven answers with one comment in the row's thread naming what moved. The
CV goes through the wizard's own check. stato and note are never touched.

ORB-62."
```

---

### Task 5: The API

**Files:**
- Modify: `projects/hub/apps/api/src/orbiters_api/deps.py`
- Create: `projects/hub/apps/api/src/orbiters_api/routers/members.py`
- Modify: `projects/hub/apps/api/src/orbiters_api/main.py`
- Test: `projects/hub/apps/api/tests/test_member_api.py`

**Interfaces:**
- Consumes: `MemberService` (Task 4), `sender_from_settings`, `EmailSender`, `RecordingSender` (Task 2), `LinkRequest`, `EnterRequest`, `MemberProfile`, `MemberUpdate`, `Ack` (Task 3), `spend_one`.
- Produces: `deps.MEMBER_COOKIE = "orbiters_user"`, `deps.get_member`, `deps.MemberDep`, `deps.get_sender`, `deps.SenderDep`; routes `POST /api/hub/auth/link`, `POST /api/hub/auth/enter`, `GET /api/hub/me`, `PATCH /api/hub/me`, `PUT /api/hub/me/cv`, `GET /api/hub/me/cv`, `POST /api/hub/me/logout`.

- [ ] **Step 1: Write the failing tests**

`test_member_api.py`:

```python
"""The member area over HTTP: a link in, a cookie out, and only your own row behind it."""

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from orbiters_api.deps import get_sender
from orbiters_core.admin import AdminService
from orbiters_core.config import Settings
from orbiters_core.mail import RecordingSender

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"
ADMIN = {"email": "ivan@orbiters.it", "password": "una-password-lunga"}


@pytest.fixture
def sender(client: TestClient) -> Iterator[RecordingSender]:
    recording = RecordingSender()
    client.app.dependency_overrides[get_sender] = lambda: recording  # type: ignore[attr-defined]
    yield recording


@pytest.fixture
def clean(api_session: Session) -> Iterator[None]:
    yield
    api_session.rollback()
    for table in (
        "member_sessions",
        "magic_link_tokens",
        "comments",
        "admin_sessions",
        "admin_users",
        "freelancers",
    ):
        api_session.execute(text(f"DELETE FROM {table}"))
    api_session.commit()


def _apply(client: TestClient, email: str, nome: str = "Ada") -> None:
    response = client.post(
        "/api/hub/freelancers",
        data={
            "nome": nome,
            "cognome": "Lovelace",
            "email": email,
            "tariffa_giornaliera": "450",
            "posizione": "Backend developer",
            "remoto": "remoto",
        },
        files={"cv": ("Ada CV.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text


def _enter(client: TestClient, sender: RecordingSender, email: str) -> dict[str, object]:
    assert client.post("/api/hub/auth/link", json={"email": email}).status_code == 202
    match = re.search(r"/entra\?t=([A-Za-z0-9_-]+)", sender.sent[-1].text)
    assert match
    entered = client.post("/api/hub/auth/enter", json={"token": match.group(1)})
    assert entered.status_code == 200, entered.text
    return entered.json()  # type: ignore[no-any-return]


def test_without_a_sender_the_link_request_is_a_503_sentence(client: TestClient, clean: None) -> None:
    client.app.dependency_overrides[get_sender] = lambda: None  # type: ignore[attr-defined]
    response = client.post("/api/hub/auth/link", json={"email": "ada@studio.it"})
    assert response.status_code == 503
    assert "non è ancora attivo" in response.json()["detail"]


def test_the_link_request_answers_the_same_whether_the_address_applied_or_not(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    _apply(client, "ada@studio.it")
    known = client.post("/api/hub/auth/link", json={"email": "Ada@studio.it"})
    unknown = client.post("/api/hub/auth/link", json={"email": "nessuno@studio.it"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"ok": True}
    assert [mail.to for mail in sender.sent] == ["ada@studio.it"]
    assert "/entra?t=" in sender.sent[0].text


def test_the_link_enters_once_sets_the_member_cookie_and_opens_only_the_members_routes(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    _apply(client, "ada@studio.it")
    for path in ("/api/hub/me", "/api/hub/me/cv"):
        assert client.get(path).status_code == 401, path

    profile = _enter(client, sender, "ada@studio.it")
    assert profile["email"] == "ada@studio.it"
    assert "stato" not in profile and "note" not in profile and "utm_source" not in profile
    cookie = client.cookies.get("orbiters_user")
    assert cookie
    assert client.get("/api/hub/me").json()["nome"] == "Ada"

    # The same link a second time opens nothing.
    match = re.search(r"/entra\?t=([A-Za-z0-9_-]+)", sender.sent[-1].text)
    assert match
    again = client.post("/api/hub/auth/enter", json={"token": match.group(1)})
    assert again.status_code == 401
    assert again.json()["detail"].startswith("Link non valido o scaduto")

    # A member cookie is not an admin cookie.
    assert client.get("/api/hub/freelancers").status_code == 401
    assert client.get("/api/hub/auth/me").status_code == 401

    cv = client.get("/api/hub/me/cv")
    assert cv.status_code == 200 and cv.content == PDF
    assert 'filename="Ada CV.pdf"' in cv.headers["content-disposition"]

    assert client.post("/api/hub/me/logout").status_code == 204
    assert client.get("/api/hub/me").status_code == 401


def test_a_wrong_token_is_a_401_and_a_malformed_one_a_422(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    assert (
        client.post("/api/hub/auth/enter", json={"token": "a" * 43}).status_code == 401
    )
    assert client.post("/api/hub/auth/enter", json={"token": "corto"}).status_code == 422


def test_a_member_changes_their_answers_and_the_admin_sees_the_comment(
    client: TestClient, sender: RecordingSender, api_session: Session, clean: None
) -> None:
    _apply(client, "ada@studio.it")
    _enter(client, sender, "ada@studio.it")

    refused = client.patch(
        "/api/hub/me",
        json={
            "nome": "Ada",
            "cognome": "Lovelace",
            "linkedin_url": "http://linkedin.com/in/ada",
            "tariffa_giornaliera": "500",
            "posizione": "Backend developer",
            "remoto": "remoto",
            "links": [],
        },
    )
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"][-1] == "linkedin_url"

    changed = client.patch(
        "/api/hub/me",
        json={
            "nome": "Ada",
            "cognome": "Lovelace",
            "linkedin_url": None,
            "tariffa_giornaliera": "500",
            "posizione": "Staff engineer",
            "remoto": "ibrido",
            "links": ["https://github.com/ada"],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["posizione"] == "Staff engineer"

    new_pdf = PDF + b"\n% v2\n"
    replaced = client.put(
        "/api/hub/me/cv", files={"cv": ("Ada 2026.pdf", new_pdf, "application/pdf")}
    )
    assert replaced.status_code == 200 and replaced.json()["cv_filename"] == "Ada 2026.pdf"
    not_a_pdf = client.put("/api/hub/me/cv", files={"cv": ("x.pdf", b"ciao", "application/pdf")})
    assert not_a_pdf.status_code == 422 and not_a_pdf.json()["detail"][0]["loc"][-1] == "cv"

    # The admin reads the thread the member wrote into.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    AdminService(api_session, settings).create(ADMIN["email"], "Ivan", ADMIN["password"])
    assert client.post("/api/hub/auth/login", json=ADMIN).status_code == 200
    listed = client.get("/api/hub/freelancers").json()["items"]
    assert len(listed) == 1 and listed[0]["posizione"] == "Staff engineer"
    thread = client.get(f"/api/hub/freelancers/{listed[0]['id']}/comments").json()
    assert [comment["testo"] for comment in thread] == [
        "CV aggiornato dalla persona",
        "Profilo aggiornato dalla persona: tariffa giornaliera, posizione, modalità di lavoro, link",
    ]
    assert thread[0]["autore"] == "Ada Lovelace"


def test_a_member_never_sees_another_members_row(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    _apply(client, "ada@studio.it", nome="Ada")
    _apply(client, "grace@studio.it", nome="Grace")
    assert _enter(client, sender, "grace@studio.it")["nome"] == "Grace"
    assert client.get("/api/hub/me").json()["email"] == "grace@studio.it"
    # There is no route that takes an id: the only row reachable is the session's.
    assert client.get("/api/hub/me/00000000-0000-7000-8000-000000000000").status_code == 404
```

The comment order in the thread test is newest first (`CommentService.list`), which is why the CV comment comes first.

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q projects/hub/apps/api/tests/test_member_api.py`
Expected: FAIL, `ImportError: get_sender`.

- [ ] **Step 3: Extend `deps.py`**

Add the imports and, after `AdminDep`:

```python
from orbiters_core.mail import EmailSender, sender_from_settings
from orbiters_core.members import MemberService
from orbiters_core.schemas import MemberProfile

MEMBER_COOKIE = "orbiters_user"


def get_member(request: Request, session: SessionDep, settings: SettingsDep) -> MemberProfile:
    """The freelancer behind the member cookie, or 401. Never the admin cookie: the two
    tables and the two cookies are separate on purpose (member area spec)."""
    member = MemberService(session, settings).resolve(request.cookies.get(MEMBER_COOKIE))
    if member is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticazione richiesta")
    return member


MemberDep = Annotated[MemberProfile, Depends(get_member)]


def get_sender(settings: SettingsDep) -> EmailSender | None:
    """`None` without a key: the route answers 503 and nothing pretends to send."""
    return sender_from_settings(settings)


SenderDep = Annotated[EmailSender | None, Depends(get_sender)]
```

(Put the imports at the top with the others; ruff sorts them.)

- [ ] **Step 4: Write `routers/members.py`**

```python
"""The member area's API: a link in, a cookie out, one row behind it.

`POST /auth/link` answers 202 whether the address applied or not, and the mail goes out
in a background task after the response, so neither the status nor the timing nor a
provider failure says whether an address is known. `POST /auth/enter` spends the token
and sets `orbiters_user`. Everything under `/me` reads the row from the session and
never from the URL: there is no `/me/{id}`.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, Response, UploadFile, status

from orbiters_api.deps import MEMBER_COOKIE, MemberDep, SenderDep, SessionDep, SettingsDep
from orbiters_api.ratelimit import spend_one
from orbiters_core.members import MemberService
from orbiters_core.schemas import Ack, EnterRequest, LinkRequest, MemberProfile, MemberUpdate

router = APIRouter(prefix="/api/hub", tags=["hub-member"])


@router.post("/auth/link", response_model=Ack, status_code=status.HTTP_202_ACCEPTED)
def request_link(
    payload: LinkRequest,
    request: Request,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    sender: SenderDep,
) -> Ack:
    spend_one(request)
    if sender is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "L'accesso via email non è ancora attivo. Riprova più avanti.",
        )
    mail = MemberService(session, settings).request_link(payload.email)
    if mail is not None:
        background.add_task(sender.send, mail)
    return Ack()


@router.post("/auth/enter", response_model=MemberProfile)
def enter(
    payload: EnterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> MemberProfile:
    spend_one(request)
    outcome = MemberService(session, settings).enter(payload.token)
    if outcome is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Link non valido o scaduto. Chiedine un altro."
        )
    profile, raw = outcome
    response.set_cookie(
        MEMBER_COOKIE,
        raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.member_session_days * 86400,
        path="/",
    )
    return profile


@router.get("/me", response_model=MemberProfile)
def me(member: MemberDep) -> MemberProfile:
    return member


@router.patch("/me", response_model=MemberProfile)
def update_me(
    member: MemberDep, session: SessionDep, settings: SettingsDep, payload: MemberUpdate
) -> MemberProfile:
    return MemberService(session, settings).update(member.id, payload)


@router.put("/me/cv", response_model=MemberProfile)
def replace_my_cv(
    member: MemberDep,
    session: SessionDep,
    settings: SettingsDep,
    cv: Annotated[UploadFile, File()],
) -> MemberProfile:
    return MemberService(session, settings).replace_cv(
        member.id, cv.file.read(), cv.filename or "", cv.content_type or ""
    )


@router.get("/me/cv")
def my_cv(member: MemberDep, session: SessionDep, settings: SettingsDep) -> Response:
    cv = MemberService(session, settings).cv(member.id)
    safe = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in cv.filename) or "cv.pdf"
    return Response(
        content=cv.content,
        media_type=cv.mime,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.post("/me/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    MemberService(session, settings).close_session(request.cookies.get(MEMBER_COOKIE))
    response.delete_cookie(MEMBER_COOKIE, path="/")
```

In `main.py`, import `members` beside the other routers and `app.include_router(members.router)` after `admin.router`.

- [ ] **Step 5: Run the API suite**

Run: `uv run pytest -q projects/hub/apps/api/tests`
Expected: all passed, the new file included. If `client.cookies.get("orbiters_user")` is `None` because `TestClient` refuses a `Secure` cookie, the fixture already uses `base_url="https://testserver"`; check the header instead: `"orbiters_user=" in entered.headers["set-cookie"].lower()`.

- [ ] **Step 6: Lint, types, commit**

```bash
uv run ruff check projects/hub && uv run ruff format --check projects/hub && uv run mypy
git add projects/hub/apps/api/src/orbiters_api/deps.py projects/hub/apps/api/src/orbiters_api/routers/members.py projects/hub/apps/api/src/orbiters_api/main.py projects/hub/apps/api/tests/test_member_api.py
git commit -m "feat(hub): the API takes a link request, opens a member session and serves one row

POST /api/hub/auth/link answers 202 for any address and sends in the
background, or 503 with a sentence when no provider is configured.
POST /api/hub/auth/enter spends the token and sets orbiters_user. GET, PATCH,
PUT /cv, GET /cv and POST /logout under /api/hub/me read the row from the
session and never from the URL.

ORB-62."
```

---

### Task 6: The web client, the hooks, `/accedi` and `/entra`

**Files:**
- Modify: `projects/hub/apps/web/src/lib/api.ts`
- Create: `projects/hub/apps/web/src/lib/member.tsx`
- Create: `projects/hub/apps/web/src/pages/member/Accedi.tsx`, `Entra.tsx`
- Modify: `projects/hub/apps/web/src/router.tsx`
- Test: `projects/hub/apps/web/src/pages/member/Accedi.test.tsx`, `Entra.test.tsx`

**Interfaces:**
- Consumes: the seven routes of Task 5.
- Produces: `api.ts`: `MemberProfile`, `MemberUpdate`, `member.requestLink(email)`, `member.enter(token)`, `member.me()`, `member.update(data)`, `member.replaceCv(file)`, `member.cvUrl`, `member.logout()`; `member.tsx`: `MEMBER_KEY`, `useMember()`, `useRequestLink()`, `useEnter()`, `useUpdateProfile()`, `useReplaceCv()`, `useMemberLogout()`, `toApplication(profile): FreelancerApplication`, `toUpdate(value: FreelancerApplication): MemberUpdate`; routes `/accedi`, `/entra`.

- [ ] **Step 1: Write the failing tests**

`Accedi.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Accedi } from './Accedi'

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mount() {
  const root = createRootRoute({ component: () => <Outlet /> })
  const accedi = createRoute({ getParentRoute: () => root, path: '/accedi', component: Accedi })
  const freelance = createRoute({ getParentRoute: () => root, path: '/freelance', component: () => <h1>Wizard</h1> })
  const router = createRouter({
    routeTree: root.addChildren([accedi, freelance]),
    history: createMemoryHistory({ initialEntries: ['/accedi'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('/accedi', () => {
  it('says the same thing for any address', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(202, { ok: true }))
    mount()
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email'), 'ada@studio.it')
    await user.click(screen.getByRole('button', { name: 'Mandami il link' }))
    const sentence = await screen.findByText(/Se sei dentro, ti abbiamo scritto/)
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/hub/auth/link',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ email: 'ada@studio.it' }) }),
    )

    await user.click(screen.getByRole('button', { name: /chiedine un altro/ }))
    await user.clear(await screen.findByLabelText('Email'))
    await user.type(screen.getByLabelText('Email'), 'nessuno@studio.it')
    await user.click(screen.getByRole('button', { name: 'Mandami il link' }))
    expect((await screen.findByText(/Se sei dentro, ti abbiamo scritto/)).textContent).toBe(
      sentence.textContent,
    )
  })

  it('shows the API sentence when the mail is not active yet', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      answer(503, { detail: "L'accesso via email non è ancora attivo. Riprova più avanti." }),
    )
    mount()
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email'), 'ada@studio.it')
    await user.click(screen.getByRole('button', { name: 'Mandami il link' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('non è ancora attivo'),
    )
  })
})
```

`Entra.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Entra } from './Entra'

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const PROFILE = {
  id: 'f1',
  nome: 'Ada',
  cognome: 'Lovelace',
  email: 'ada@studio.it',
  linkedin_url: null,
  cv_filename: 'cv.pdf',
  cv_size: 1024,
  tariffa_giornaliera: '450.00',
  posizione: 'Backend developer',
  remoto: 'remoto',
  links: [],
  created_at: '2026-09-10T10:00:00Z',
  updated_at: '2026-09-10T10:00:00Z',
}

function mount(path: string) {
  const root = createRootRoute({ component: () => <Outlet /> })
  const entra = createRoute({
    getParentRoute: () => root,
    path: '/entra',
    validateSearch: (search: Record<string, unknown>): { t: string } => ({ t: String(search.t ?? '') }),
    component: Entra,
  })
  const io = createRoute({ getParentRoute: () => root, path: '/io', component: () => <h1>La tua area</h1> })
  const accedi = createRoute({ getParentRoute: () => root, path: '/accedi', component: () => <h1>Accedi</h1> })
  const router = createRouter({
    routeTree: root.addChildren([entra, io, accedi]),
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('/entra', () => {
  it('posts the token from the URL once and goes to the area', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, PROFILE))
    mount('/entra?t=abc-123_XYZ')
    await screen.findByRole('heading', { name: 'La tua area' })
    const enterCalls = fetchSpy.mock.calls.filter(([url]) => url === '/api/hub/auth/enter')
    expect(enterCalls).toHaveLength(1)
    expect(enterCalls[0][1]).toMatchObject({ method: 'POST', body: JSON.stringify({ token: 'abc-123_XYZ' }) })
  })

  it('says the link is no longer valid and offers another', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      answer(401, { detail: 'Link non valido o scaduto. Chiedine un altro.' }),
    )
    mount('/entra?t=abc-123_XYZ')
    expect(await screen.findByRole('alert')).toHaveTextContent('non è più valido')
    expect(screen.getByRole('link', { name: /Chiedine un altro/ })).toHaveAttribute('href', '/accedi')
  })
})
```

- [ ] **Step 2: Run to see them fail**

Run: `pnpm --filter hub test -- src/pages/member`
Expected: FAIL, cannot resolve `./Accedi`, `./Entra`. (If `--` is swallowed, run `pnpm --filter hub exec vitest run src/pages/member`.)

- [ ] **Step 3: Extend `api.ts`**

After the admin section, add:

```ts
// ---- the member area ------------------------------------------------------------------

/** The row as its owner reads it: what they gave, never the admin's fields. */
export interface MemberProfile {
  id: string
  nome: string
  cognome: string
  email: string
  linkedin_url: string | null
  cv_filename: string
  cv_size: number
  tariffa_giornaliera: string
  posizione: string
  remoto: Remoto
  links: string[]
  created_at: string
  updated_at: string
}

/** The seven answers a member may change. The email is not among them. */
export interface MemberUpdate {
  nome: string
  cognome: string
  linkedin_url: string | null
  tariffa_giornaliera: string
  posizione: string
  remoto: Remoto
  links: string[]
}

export const member = {
  /** 202 whether the address is known or not; the page says one thing in both cases. */
  requestLink: (email: string) => request<{ ok: true }>('/api/hub/auth/link', json({ email })),
  enter: (token: string) => request<MemberProfile>('/api/hub/auth/enter', json({ token })),
  me: () => request<MemberProfile>('/api/hub/me'),
  update: (data: MemberUpdate) =>
    request<MemberProfile>('/api/hub/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  replaceCv: (file: File) => {
    const form = new FormData()
    form.set('cv', file, file.name)
    return request<MemberProfile>('/api/hub/me/cv', { method: 'PUT', body: form })
  },
  cvUrl: '/api/hub/me/cv',
  logout: () => request<void>('/api/hub/me/logout', { method: 'POST' }),
}
```

Update the file's header comment: the API is no longer "six routes and two shapes"; say "a handful of routes and three shapes".

- [ ] **Step 4: Write `lib/member.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  member,
  type FreelancerApplication,
  type MemberProfile,
  type MemberUpdate,
} from './api'

export const MEMBER_KEY = ['member', 'me'] as const

/** The freelancer behind the member cookie, or `null`. A 401 is "not logged in". */
export function useMember() {
  return useQuery({
    queryKey: MEMBER_KEY,
    queryFn: async (): Promise<MemberProfile | null> => {
      try {
        return await member.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
    staleTime: 60_000,
  })
}

export function useRequestLink() {
  return useMutation({ mutationFn: (email: string) => member.requestLink(email) })
}

export function useEnter() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => member.enter(token),
    onSuccess: (me) => client.setQueryData(MEMBER_KEY, me),
  })
}

export function useUpdateProfile() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (data: MemberUpdate) => member.update(data),
    onSuccess: (me) => client.setQueryData(MEMBER_KEY, me),
  })
}

export function useReplaceCv() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => member.replaceCv(file),
    onSuccess: (me) => client.setQueryData(MEMBER_KEY, me),
  })
}

export function useMemberLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => member.logout(),
    onSettled: () => {
      client.clear()
      window.location.assign('/hub/accedi')
    },
  })
}

/** The profile in the wizard's own shape, so its steps can render and validate it.
 *  `cv` is `null`: the file we hold is not a `File` in the browser. */
export function toApplication(profile: MemberProfile): FreelancerApplication {
  return {
    nome: profile.nome,
    cognome: profile.cognome,
    email: profile.email,
    linkedin_url: profile.linkedin_url ?? '',
    tariffa_giornaliera: profile.tariffa_giornaliera,
    posizione: profile.posizione,
    remoto: profile.remoto,
    links: profile.links,
    cv: null,
  }
}

/** What `PATCH /me` takes, trimmed the way the wizard trims before posting. */
export function toUpdate(value: FreelancerApplication): MemberUpdate {
  return {
    nome: value.nome.trim(),
    cognome: value.cognome.trim(),
    linkedin_url: value.linkedin_url.trim() || null,
    tariffa_giornaliera: value.tariffa_giornaliera.replace(',', '.').trim(),
    posizione: value.posizione.trim(),
    remoto: value.remoto as MemberUpdate['remoto'],
    links: value.links.map((link) => link.trim()).filter(Boolean),
  }
}
```

- [ ] **Step 5: Write `pages/member/Accedi.tsx`**

```tsx
import { Link } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'
import { useRequestLink } from '@/lib/member'

/** The way in: an address, a link by mail, no password. The page says the same thing
 *  whether the address is known or not, as the API does. */
export function Accedi() {
  const requestLink = useRequestLink()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    requestLink.mutate(email.trim(), {
      onSuccess: () => setSent(true),
      onError: (failure) =>
        setError(
          failure instanceof ApiError
            ? failure.message
            : 'Non siamo riusciti a mandarti il link. Riprova.',
        ),
    })
  }

  if (sent) {
    return (
      <div className="mx-auto max-w-xl space-y-4 text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Controlla la posta</h1>
        <p className="text-muted-foreground">
          Se sei dentro, ti abbiamo scritto: apri la mail e segui il link. Vale quindici minuti.
        </p>
        <p className="text-sm text-muted-foreground">
          Non arriva? Guarda nello spam, oppure{' '}
          <button
            type="button"
            className="underline underline-offset-2"
            onClick={() => setSent(false)}
          >
            chiedine un altro
          </button>
          .
        </p>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-md space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Entra nella tua area</h1>
        <p className="mt-2 text-muted-foreground">
          L’indirizzo che ci hai dato: ti mandiamo un link, senza password.
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          required
          autoComplete="email"
          autoFocus
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" className="w-full" disabled={requestLink.isPending}>
        {requestLink.isPending ? 'Un attimo…' : 'Mandami il link'}
      </Button>
      <p className="text-sm text-muted-foreground">
        Non sei ancora dentro?{' '}
        <Link to="/freelance" className="underline underline-offset-2">
          Raccontaci chi sei
        </Link>
        .
      </p>
    </form>
  )
}
```

- [ ] **Step 6: Write `pages/member/Entra.tsx`**

```tsx
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import { useEnter } from '@/lib/member'

/** Where the mail's link lands. The token is posted from here, once, and never fetched
 *  by the link itself: a scanner that opens every link in a message does not run this
 *  page, so it cannot spend the token. */
export function Entra() {
  const { t } = useSearch({ strict: false }) as { t?: string }
  const navigate = useNavigate()
  const enter = useEnter()
  const started = useRef(false)

  useEffect(() => {
    if (started.current || !t) return
    started.current = true
    enter.mutate(t, { onSuccess: () => void navigate({ to: '/io', replace: true }) })
  }, [t, enter, navigate])

  if (!t || enter.isError) {
    return (
      <div className="mx-auto max-w-xl space-y-4 text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Questo link non funziona</h1>
        <p role="alert" className="text-muted-foreground">
          Il link non è più valido: vale quindici minuti e una volta sola.
        </p>
        <Link to="/accedi" className="text-sm underline underline-offset-2">
          Chiedine un altro
        </Link>
      </div>
    )
  }
  return <p className="text-center text-sm text-muted-foreground">Un attimo, ti facciamo entrare…</p>
}
```

- [ ] **Step 7: Add the two routes to `router.tsx`**

After `grazie`:

```tsx
const accedi = createRoute({ getParentRoute: () => publicLayout, path: '/accedi', component: Accedi })
const entra = createRoute({
  getParentRoute: () => publicLayout,
  path: '/entra',
  validateSearch: (search: Record<string, unknown>): { t: string } => ({
    t: typeof search.t === 'string' ? search.t : '',
  }),
  component: Entra,
})
```

Add both to `publicLayout.addChildren([...])` and the imports. Update the tree comment: the count of screens is no longer nine.

- [ ] **Step 8: Run the tests, lint and types**

Run: `pnpm --filter hub test && pnpm --filter hub lint && pnpm --filter hub exec tsc --noEmit`
Expected: all passed, no lint or type error.

- [ ] **Step 9: Commit**

```bash
git add projects/hub/apps/web/src/lib/api.ts projects/hub/apps/web/src/lib/member.tsx projects/hub/apps/web/src/pages/member/Accedi.tsx projects/hub/apps/web/src/pages/member/Accedi.test.tsx projects/hub/apps/web/src/pages/member/Entra.tsx projects/hub/apps/web/src/pages/member/Entra.test.tsx projects/hub/apps/web/src/router.tsx
git commit -m "feat(hub): /hub/accedi asks for the address and /hub/entra spends the link

The client and the hooks for the member routes, the shape of the admin's. The
page after the form says the same sentence for any address. The mail's link
lands on the SPA, which posts the token once, so a scanner cannot spend it.

ORB-62."
```

---

### Task 7: `/io`, the area itself

**Files:**
- Create: `projects/hub/apps/web/src/pages/member/Guard.tsx`, `Area.tsx`
- Modify: `projects/hub/apps/web/src/router.tsx`
- Test: `projects/hub/apps/web/src/pages/member/Area.test.tsx`

**Interfaces:**
- Consumes: `useMember`, `useMemberLogout`, `toApplication` (Task 6), `FREELANCER_STEPS` (`pages/FreelancerWizard.tsx`), `member.cvUrl`, `formatBytes` (`lib/format.ts`).
- Produces: `MemberGuard` layout, `Area` page; routes `/io` (layout) and `/io/` (index).

- [ ] **Step 1: Write the failing test**

`Area.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Area } from './Area'
import { MemberGuard } from './Guard'

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const PROFILE = {
  id: 'f1',
  nome: 'Ada',
  cognome: 'Lovelace',
  email: 'ada@studio.it',
  linkedin_url: 'https://www.linkedin.com/in/ada',
  cv_filename: 'Ada CV.pdf',
  cv_size: 2048,
  tariffa_giornaliera: '450.00',
  posizione: 'Backend developer',
  remoto: 'ibrido',
  links: ['https://github.com/ada'],
  created_at: '2026-09-10T10:00:00Z',
  updated_at: '2026-09-10T10:00:00Z',
}

function mount() {
  const root = createRootRoute({ component: () => <Outlet /> })
  const io = createRoute({ getParentRoute: () => root, path: '/io', component: MemberGuard })
  const index = createRoute({ getParentRoute: () => io, path: '/', component: Area })
  const accedi = createRoute({ getParentRoute: () => root, path: '/accedi', component: () => <h1>Accedi</h1> })
  const router = createRouter({
    routeTree: root.addChildren([io.addChildren([index]), accedi]),
    history: createMemoryHistory({ initialEntries: ['/io'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('/io', () => {
  it('shows the answers under the wizard’s questions, the CV and the two perks', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, PROFILE))
    mount()
    // The name is both the heading and the answer to the first question.
    expect(await screen.findAllByText('Ada Lovelace')).not.toHaveLength(0)
    expect(screen.getByText('Come ti chiami?')).toBeInTheDocument()
    expect(screen.getByText('450.00 € / giorno')).toBeInTheDocument()
    expect(screen.getByText('Ibrido')).toBeInTheDocument()
    expect(screen.getByText('ada@studio.it')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Ada CV\.pdf/ })).toHaveAttribute('href', '/api/hub/me/cv')
    expect(screen.getByRole('link', { name: /Apri PigroCRM/ })).toHaveAttribute(
      'href',
      'https://pigro.joinorbiters.com/app/registrati',
    )
    expect(screen.getByText('Altro in arrivo')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Modifica' })).toHaveAttribute('href', '/io/modifica')
  })

  it('sends a visitor without a session to /accedi', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(401, { detail: 'Autenticazione richiesta' }))
    mount()
    expect(await screen.findByRole('heading', { name: 'Accedi' })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to see it fail**

Run: `pnpm --filter hub exec vitest run src/pages/member/Area.test.tsx`
Expected: FAIL, cannot resolve `./Area`, `./Guard`.

- [ ] **Step 3: Write `Guard.tsx`**

```tsx
import { Outlet, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { useMember } from '@/lib/member'

/** Nothing under /io renders until the session is known; without one the visitor goes
 *  to /accedi. The shape of `AdminLayout`'s guard, without the frame. */
export function MemberGuard() {
  const me = useMember()
  const navigate = useNavigate()

  useEffect(() => {
    if (!me.isPending && me.data === null) void navigate({ to: '/accedi', replace: true })
  }, [me.isPending, me.data, navigate])

  if (me.isPending) return <p className="text-sm text-muted-foreground">Caricamento…</p>
  if (!me.data) return null
  return <Outlet />
}
```

- [ ] **Step 4: Write `Area.tsx`**

```tsx
import { Link } from '@tanstack/react-router'
import { ArrowUpRight, Download, LogOut, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { member } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import { toApplication, useMember, useMemberLogout } from '@/lib/member'
import { FREELANCER_STEPS } from '@/pages/FreelancerWizard'

const PIGROCRM_URL = 'https://pigro.joinorbiters.com/app/registrati'

/** What the person sent, under the wizard's own questions, and the perks. The email is
 *  shown and not editable: it is the address the link proved. */
export function Area() {
  const me = useMember()
  const logout = useMemberLogout()
  if (!me.data) return null
  const profile = me.data
  const value = toApplication(profile)
  const steps = FREELANCER_STEPS.filter((step) => step.id !== 'email' && step.id !== 'cv')

  return (
    <div className="mx-auto max-w-2xl space-y-10">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">La tua area</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            {profile.nome} {profile.cognome}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Ti scriviamo a <span className="font-medium text-foreground">{profile.email}</span>.
            Per cambiare indirizzo, rifai la candidatura con quello nuovo.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/io/modifica">
              <Pencil className="mr-2 size-4" />
              Modifica
            </Link>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
            <LogOut className="mr-2 size-4" />
            Esci
          </Button>
        </div>
      </header>

      <section aria-label="Quello che ci hai mandato">
        <dl className="divide-y rounded-2xl border bg-card">
          {steps.map((step) => (
            <div key={step.id} className="flex items-start gap-4 px-4 py-3 text-sm">
              <dt className="w-40 shrink-0 text-muted-foreground">{step.title}</dt>
              <dd className="min-w-0 flex-1 break-words font-medium">{step.summary(value) || '—'}</dd>
            </div>
          ))}
          <div className="flex items-start gap-4 px-4 py-3 text-sm">
            <dt className="w-40 shrink-0 text-muted-foreground">Il tuo CV</dt>
            <dd className="min-w-0 flex-1">
              <a href={member.cvUrl} className="inline-flex items-center gap-1.5 font-medium underline-offset-2 hover:underline">
                <Download className="size-4" aria-hidden="true" />
                {profile.cv_filename}
                <span className="font-normal text-muted-foreground">({formatBytes(profile.cv_size)})</span>
              </a>
            </dd>
          </div>
        </dl>
      </section>

      <section aria-label="I tuoi vantaggi" className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-3 rounded-2xl border-2 border-foreground bg-card p-6">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Per chi è dentro</p>
          <h2 className="text-lg font-semibold">PigroCRM è tuo, gratis</h2>
          <p className="text-sm text-muted-foreground">
            Preventivo, contratto, fattura, ore: fatturare e farti pagare, con i dati fiscali già giusti.
          </p>
          <Button asChild className="mt-auto self-start">
            <a href={PIGROCRM_URL}>
              Apri PigroCRM
              <ArrowUpRight className="ml-2 size-4" />
            </a>
          </Button>
        </div>
        <div className="flex flex-col gap-3 rounded-2xl border border-dashed bg-muted/40 p-6 text-muted-foreground">
          <p className="text-xs font-medium tracking-wide uppercase">Prossimamente</p>
          <h2 className="text-lg font-semibold">Altro in arrivo</h2>
          <p className="text-sm">Stiamo mettendo insieme altre cose per chi è dentro. Ti scriviamo noi.</p>
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 5: Add the routes**

In `router.tsx`:

```tsx
const io = createRoute({ getParentRoute: () => publicLayout, path: '/io', component: MemberGuard })
const ioIndex = createRoute({ getParentRoute: () => io, path: '/', component: Area })
```

and in the tree: `publicLayout.addChildren([chooser, freelance, aziende, grazie, accedi, entra, io.addChildren([ioIndex])])`. Import `MemberGuard` and `Area`.

- [ ] **Step 6: Run tests, lint and types**

Run: `pnpm --filter hub test && pnpm --filter hub lint && pnpm --filter hub exec tsc --noEmit`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add projects/hub/apps/web/src/pages/member/Guard.tsx projects/hub/apps/web/src/pages/member/Area.tsx projects/hub/apps/web/src/pages/member/Area.test.tsx projects/hub/apps/web/src/router.tsx
git commit -m "feat(hub): /hub/io shows a freelancer what they sent, their CV and the perks

The answers sit under the wizard's own questions, the CV is a download of the
member's own file, PigroCRM is the perk in evidence and a second box says more
is coming. Without a session the page goes to /hub/accedi.

ORB-62."
```

---

### Task 8: `/io/modifica`, the form

**Files:**
- Create: `projects/hub/apps/web/src/pages/member/Modifica.tsx`
- Modify: `projects/hub/apps/web/src/router.tsx`
- Test: `projects/hub/apps/web/src/pages/member/Modifica.test.tsx`

**Interfaces:**
- Consumes: `FREELANCER_STEPS`, `Step<T>` (`wizard/Wizard.tsx`), `FreelancerApplication`, `ApiError`, `toApplication`, `toUpdate`, `useMember`, `useUpdateProfile`, `useReplaceCv`.
- Produces: `EDIT_STEPS: Step<FreelancerApplication>[]`, `Modifica` page; route `/io/modifica`.

- [ ] **Step 1: Write the failing tests**

`Modifica.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EDIT_STEPS, Modifica } from './Modifica'

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const PROFILE = {
  id: 'f1',
  nome: 'Ada',
  cognome: 'Lovelace',
  email: 'ada@studio.it',
  linkedin_url: null,
  cv_filename: 'Ada CV.pdf',
  cv_size: 2048,
  tariffa_giornaliera: '450.00',
  posizione: 'Backend developer',
  remoto: 'remoto',
  links: [],
  created_at: '2026-09-10T10:00:00Z',
  updated_at: '2026-09-10T10:00:00Z',
}

function mount() {
  const root = createRootRoute({ component: () => <Outlet /> })
  const modifica = createRoute({ getParentRoute: () => root, path: '/io/modifica', component: Modifica })
  const io = createRoute({ getParentRoute: () => root, path: '/io', component: () => <h1>La tua area</h1> })
  const router = createRouter({
    routeTree: root.addChildren([modifica, io]),
    history: createMemoryHistory({ initialEntries: ['/io/modifica'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('the edit steps', () => {
  const base = { ...PROFILE, linkedin_url: '', cv: null }

  it('leave the email out and make the CV optional', () => {
    expect(EDIT_STEPS.map((step) => step.id)).not.toContain('email')
    const cv = EDIT_STEPS.find((step) => step.id === 'cv')!
    expect(cv.validate(base as never)).toBeNull()
    const png = new File(['x'], 'cv.png', { type: 'image/png' })
    expect(cv.validate({ ...base, cv: png } as never)).not.toBeNull()
  })

  it('keep the wizard’s rules for everything else', () => {
    const linkedin = EDIT_STEPS.find((step) => step.id === 'linkedin_url')!
    expect(linkedin.validate({ ...base, linkedin_url: 'https://twitter.com/ada' } as never)).not.toBeNull()
  })
})

describe('/io/modifica', () => {
  it('starts from the current answers and saves them with PATCH', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (url, init) =>
        init?.method === 'PATCH'
          ? answer(200, { ...PROFILE, posizione: 'Staff engineer' })
          : answer(200, PROFILE),
      )
    mount()
    const user = userEvent.setup()
    const posizione = await screen.findByLabelText('Posizione')
    expect(posizione).toHaveValue('Backend developer')
    await user.clear(posizione)
    await user.type(posizione, 'Staff engineer')
    await user.click(screen.getByRole('button', { name: 'Salva' }))
    await screen.findByRole('heading', { name: 'La tua area' })
    const patch = fetchSpy.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(patch[0]).toBe('/api/hub/me')
    expect(JSON.parse(patch[1]!.body as string)).toEqual({
      nome: 'Ada',
      cognome: 'Lovelace',
      linkedin_url: null,
      tariffa_giornaliera: '450.00',
      posizione: 'Staff engineer',
      remoto: 'remoto',
      links: [],
    })
    expect(fetchSpy.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
  })

  it('shows a server refusal under the field it names', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) =>
      init?.method === 'PATCH'
        ? answer(422, {
            detail: [{ loc: ['body', 'tariffa_giornaliera'], msg: 'serve una cifra più bassa' }],
          })
        : answer(200, PROFILE),
    )
    mount()
    const user = userEvent.setup()
    await screen.findByLabelText('Posizione')
    await user.click(screen.getByRole('button', { name: 'Salva' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('serve una cifra più bassa'),
    )
  })
})
```

- [ ] **Step 2: Run to see them fail**

Run: `pnpm --filter hub exec vitest run src/pages/member/Modifica.test.tsx`
Expected: FAIL, cannot resolve `./Modifica`.

- [ ] **Step 3: Write `Modifica.tsx`**

```tsx
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError, type FreelancerApplication } from '@/lib/api'
import { toApplication, toUpdate, useMember, useReplaceCv, useUpdateProfile } from '@/lib/member'
import { FREELANCER_STEPS } from '@/pages/FreelancerWizard'
import type { Step } from '@/wizard/Wizard'

/**
 * The wizard's steps, as a form: every question at once, because the person is
 * correcting and not answering for the first time. The email is not among them (it is
 * the identity the link proved) and the CV is optional here: `null` keeps the one we
 * hold. Everything else, control and rule alike, is the wizard's own.
 */
export const EDIT_STEPS: Step<FreelancerApplication>[] = FREELANCER_STEPS.filter(
  (step) => step.id !== 'email',
).map((step) =>
  step.id === 'cv'
    ? {
        ...step,
        optional: true,
        hint: 'Solo se vuoi sostituirlo: un PDF, al massimo 5 MB. Altrimenti teniamo quello che abbiamo.',
        validate: (value) => (value.cv ? step.validate(value) : null),
      }
    : step,
)

export function Modifica() {
  const me = useMember()
  const navigate = useNavigate()
  const update = useUpdateProfile()
  const replaceCv = useReplaceCv()
  const [draft, setDraft] = useState<FreelancerApplication | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState<string | null>(null)

  // State that follows a prop, adjusted during render: the draft starts from the
  // profile the first time it is known, and never again while the person is typing.
  if (draft === null && me.data) setDraft(toApplication(me.data))
  if (!me.data || draft === null) {
    return <p className="text-sm text-muted-foreground">Caricamento…</p>
  }
  const value = draft
  const set = (patch: Partial<FreelancerApplication>) =>
    setDraft((current) => (current ? { ...current, ...patch } : current))
  const saving = update.isPending || replaceCv.isPending

  async function save() {
    setFailure(null)
    const problems: Record<string, string> = {}
    for (const step of EDIT_STEPS) {
      const problem = step.validate(value)
      if (problem) problems[step.id] = problem
    }
    setErrors(problems)
    if (Object.keys(problems).length) return
    try {
      await update.mutateAsync(toUpdate(value))
      if (value.cv) await replaceCv.mutateAsync(value.cv)
      void navigate({ to: '/io' })
    } catch (error) {
      const refusal = error instanceof ApiError ? error : null
      if (refusal?.fields.length) {
        setErrors(Object.fromEntries(refusal.fields.map((field) => [field, refusal.message])))
      } else {
        setFailure(refusal?.message ?? 'Non siamo riusciti a salvare. Riprova.')
      }
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">La tua area</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Correggi quello che ci hai mandato</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Ti scriviamo a <span className="font-medium text-foreground">{me.data.email}</span>: per
          cambiare indirizzo, rifai la candidatura con quello nuovo.
        </p>
      </div>

      {EDIT_STEPS.map((step) => (
        <section key={step.id} className="space-y-3" aria-labelledby={`edit-${step.id}`}>
          <div>
            <h2 id={`edit-${step.id}`} className="text-lg font-semibold tracking-tight">
              {step.title}
              {step.optional && (
                <span className="ml-2 text-sm font-normal text-muted-foreground">(facoltativo)</span>
              )}
            </h2>
            {step.hint && <p className="mt-1 text-sm text-muted-foreground">{step.hint}</p>}
          </div>
          {step.render({
            value,
            set,
            next: () => void save(),
            error: errors[step.id] ?? null,
            autoFocus: false,
          })}
          {errors[step.id] && (
            <p role="alert" className="text-sm text-destructive">
              {errors[step.id]}
            </p>
          )}
        </section>
      ))}

      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {failure}
        </p>
      )}
      <div className="flex items-center justify-between">
        <Button asChild variant="ghost">
          <Link to="/io">Annulla</Link>
        </Button>
        <Button type="button" onClick={() => void save()} disabled={saving}>
          {saving ? 'Salvo…' : 'Salva'}
        </Button>
      </div>
    </div>
  )
}
```

If ESLint's `react-hooks` rule refuses `setDraft` during render, move the initialisation into a `useEffect` keyed on `me.data` that runs only while `draft === null`.

- [ ] **Step 4: Add the route**

In `router.tsx`:

```tsx
const ioModifica = createRoute({ getParentRoute: () => io, path: '/modifica', component: Modifica })
```

and `io.addChildren([ioIndex, ioModifica])`. Import `Modifica`.

- [ ] **Step 5: Run tests, lint and types**

Run: `pnpm --filter hub test && pnpm --filter hub lint && pnpm --filter hub exec tsc --noEmit`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add projects/hub/apps/web/src/pages/member/Modifica.tsx projects/hub/apps/web/src/pages/member/Modifica.test.tsx projects/hub/apps/web/src/router.tsx
git commit -m "feat(hub): /hub/io/modifica lets a freelancer correct their answers and replace the CV

The wizard's steps as one form, with its controls and its rules; the email is
not among them and the CV only when a new file is chosen. A server refusal
lands under the field it names.

ORB-62."
```

---

### Task 9: The door, the thank-you sentence, configuration and records

**Files:**
- Modify: `projects/hub/apps/web/src/components/Shell.tsx`
- Modify: `projects/hub/apps/web/src/pages/Thanks.tsx`
- Modify: `projects/hub/.env.example`, `projects/hub/docker-compose.yml`, `projects/hub/AGENTS.md`
- Modify: `docs/design/DECISIONS.md`
- Test: `projects/hub/apps/web/src/pages/Thanks.test.tsx` (create)

**Interfaces:**
- Consumes: routes `/accedi`, `/io` (Tasks 6, 7); settings names (Task 2).

- [ ] **Step 1: Write the failing test**

`Thanks.test.tsx`:

```tsx
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Thanks } from './Thanks'

function mount(chi: string) {
  const root = createRootRoute({ component: () => <Outlet /> })
  const grazie = createRoute({
    getParentRoute: () => root,
    id: 'public',
    path: '/grazie',
    validateSearch: (search: Record<string, unknown>): { chi: 'freelance' | 'azienda' } => ({
      chi: search.chi === 'azienda' ? 'azienda' : 'freelance',
    }),
    component: Thanks,
  })
  const router = createRouter({
    routeTree: root.addChildren([grazie]),
    history: createMemoryHistory({ initialEntries: [`/grazie?chi=${chi}`] }),
  })
  render(<RouterProvider router={router} />)
}

describe('the thank-you page', () => {
  it('tells a freelancer the area exists', async () => {
    mount('freelance')
    expect(await screen.findByRole('link', { name: /Entra nella tua area/ })).toHaveAttribute(
      'href',
      '/accedi',
    )
  })

  it('does not tell a company', async () => {
    mount('azienda')
    await screen.findByRole('heading', { name: 'Grazie, ci siamo.' })
    expect(screen.queryByRole('link', { name: /Entra nella tua area/ })).toBeNull()
  })
})
```

`Thanks` reads `useSearch({ from: '/public/grazie' })`; if the test router cannot satisfy that id, change `Thanks` to `useSearch({ strict: false })` with the same typed destructuring, which is what the page needs anyway.

- [ ] **Step 2: Run to see it fail**

Run: `pnpm --filter hub exec vitest run src/pages/Thanks.test.tsx`
Expected: FAIL, no link «Entra nella tua area».

- [ ] **Step 3: The thank-you sentence and the header link**

In `Thanks.tsx`, after the PigroCRM paragraph and before «Torna all’inizio», add for the freelancer only:

```tsx
      {!azienda && (
        <p className="text-sm text-muted-foreground">
          Vuoi rileggere o cambiare quello che ci hai mandato?{' '}
          <Link to="/accedi" className="underline underline-offset-2">
            Entra nella tua area
          </Link>
          .
        </p>
      )}
```

In `Shell.tsx`, wrap the right side of the header so it holds two links:

```tsx
        <nav className="flex items-center gap-4 text-sm">
          <Link to="/io" className="text-muted-foreground underline-offset-2 hover:underline">
            La tua area
          </Link>
          <a
            className="text-muted-foreground underline-offset-2 hover:underline"
            href="https://joinorbiters.com/"
          >
            joinorbiters.com
          </a>
        </nav>
```

- [ ] **Step 4: Configuration**

`projects/hub/.env.example`, after the ChatGPT Ads block:

```
# --- the member area: the magic link by mail ------------------------------------------
# Resend sends the login link. Empty key: the link request answers 503 with a sentence
# and nothing pretends to send. The key is a secret and lives in this file on the
# server only; the SPF and DKIM records for joinorbiters.com are set in Resend's panel.
ORBITERS_RESEND_API_KEY=
ORBITERS_MAIL_FROM=Orbiters <ciao@joinorbiters.com>
# Where the SPA answers, for the link in the mail. Local development: the Vite server.
ORBITERS_HUB_URL=https://joinorbiters.com/hub
```

`projects/hub/docker-compose.yml`, in the `api` service's `environment`, after the conversions lines:

```yaml
      # The member area's mail. Empty key is a hub with the area's door still closed.
      ORBITERS_RESEND_API_KEY: ${ORBITERS_RESEND_API_KEY:-}
      ORBITERS_MAIL_FROM: ${ORBITERS_MAIL_FROM:-Orbiters <ciao@joinorbiters.com>}
      ORBITERS_HUB_URL: ${ORBITERS_HUB_URL:-https://joinorbiters.com/hub}
```

`projects/hub/AGENTS.md`: in the layout block change the `apps/web/` line to `pnpm package \`hub\`: the SPA at joinorbiters.com/hub/ (wizards, the member area, admin)`; in «What it is» add one sentence: «Since 2026-09-10 a freelancer can get back in with a magic link by mail (`/hub/accedi`, `/hub/io`): spec `docs/superpowers/specs/2026-09-10-member-area-design.md`.»; in «Deploying» add: «The member area's mail needs `ORBITERS_RESEND_API_KEY` and `ORBITERS_MAIL_FROM` in the host `.env`; without the key `/hub/accedi` answers 503 with a sentence.»

`docs/design/DECISIONS.md`, one row at the end:

```
| 2026-09-10 | How does a freelancer prove they own the address they gave the hub? | A magic link by email: a hashed one-time token, fifteen minutes, single use, opening a sliding session in its own cookie (`orbiters_user`). No password anywhere. The provider is Resend, the key on the host only. | The hub has no password to store or reset. A member session is never the admin's table or cookie. A link lands on the SPA, which posts the token, never on the API. Spec: `projects/hub/docs/superpowers/specs/2026-09-10-member-area-design.md`. |
```

- [ ] **Step 5: Run everything**

```bash
pnpm --filter hub test && pnpm --filter hub lint && pnpm --filter hub build
uv run ruff check projects/hub && uv run ruff format --check projects/hub && uv run mypy
uv run pytest -q projects/hub
```

Expected: every command green; note the Python test count and the vitest count for the PR body.

- [ ] **Step 6: Commit**

```bash
git add projects/hub/apps/web/src/components/Shell.tsx projects/hub/apps/web/src/pages/Thanks.tsx projects/hub/apps/web/src/pages/Thanks.test.tsx projects/hub/.env.example projects/hub/docker-compose.yml projects/hub/AGENTS.md docs/design/DECISIONS.md
git commit -m "feat(hub): the thank-you page and the header say the area exists, and the host knows how to mail

«Entra nella tua area» after the freelancer wizard, «La tua area» in the hub
header, the three mail settings in .env.example and compose, the decision
recorded in DECISIONS.md and the project's AGENTS.md.

ORB-62."
```

---

## After the tasks (the driver's own steps, not a subagent's)

1. Run the hub API and web locally with a `RecordingSender` stand-in (`ORBITERS_RESEND_API_KEY` empty shows the 503; to walk the flow, set a fake key and read the link from a debug print, or call `MemberService.request_link` from `uv run python` against the local database) and take the four screens at 1440×900 for the PR, plus the thank-you page and the header pair, per `docs/pr-screenshots/README.md`.
2. `gh pr create` per the `pr-creation` skill: title `feat(hub): a freelancer gets back in with a link and changes what they sent`, body with «Migrations» (0005), «API changes» (the seven routes, `api.ts`), «Screenshots».
3. Move ORB-62 to `In Review` with the PR URL; dispatch the independent reviewer; apply findings in a second commit; `gh pr checks --watch`; merge with a merge commit; close on Linear with the evidence; file the follow-up card for the website's community page.
