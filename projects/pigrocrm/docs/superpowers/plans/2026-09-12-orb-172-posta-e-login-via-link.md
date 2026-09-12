# ORB-172, la posta del CRM e il login via link: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In PigroCRM si entra come nella community: si scrive l'email e arriva un link via mail (Resend) che vale 15 minuti; la password resta come seconda via per chi la ha già e non viene più chiesta a nessuno.

**Architecture:** Monorepo Orbiters, progetto `projects/pigrocrm/` (percorsi relativi a quella cartella; comandi dalla radice del repository, nel worktree `../pigrocrm-orb172`). In `packages/core`: un modulo `mail.py` con la stessa forma di `orbiters_core/mail.py` (un `Protocol`, `ResendSender`, `RecordingSender`), una migrazione (`password_hash` nullable, `email_verificata_il`, tabella `magic_link_tokens`), un `MagicLinkService`. In `apps/api/routers/auth.py`: `POST /api/auth/link` e `POST /api/auth/entra`, con il mittente come dipendenza FastAPI dichiarata nel router stesso (non in `deps.py`, che ORB-170 sta cambiando). In `apps/web`: il login diventa email-first con la password come seconda via, una route `/app/entra`, e l'helper e2e clicca un bottone in più. Nessun import fra hub e CRM.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, FastAPI, Pydantic 2, argon2, `urllib` (stdlib) per Resend; React 19, TanStack Router/Query, vitest, Playwright.

**Spec:** `projects/pigrocrm/docs/superpowers/specs/2026-09-12-onboarding-product-led-design.md` §6.1 e §6.2 (sul branch di ORB-171 finché non è su `main`; in questo worktree leggerla da `../pigrocrm-orb171/...`).

## Global Constraints

- Commit in inglese, Conventional Commits, prima persona, **nessun trailer AI**; ultima riga `ORB-172.`; `git add` con pathspec.
- `packages/core` non aggiunge dipendenze: Resend si chiama con `urllib.request` (`test_architecture.py` legge `[project].dependencies`).
- Nessun indirizzo email, token o chiave nei log, nelle eccezioni rilanciate o nella timeline.
- Il login con password resta e continua a rispondere «Credenziali non valide» in modo byte-identico per email sconosciuta, password sbagliata, utente senza password, utente disattivato (`test_login_failures_are_byte_identical_regardless_of_cause`).
- `POST /api/auth/link` risponde 202 anche per un'email sconosciuta; la mail parte in `BackgroundTasks` dopo la risposta, come nell'hub.
- Non toccare `apps/api/src/pigrocrm_api/deps.py` né `tenancy.py` (ORB-170). Aprire le sessioni degli altri spazi con `create_engine` locale.
- La migrazione è `0034`; prima di aprire la PR ricontrollare `origin/main` (`ls packages/core/migrations/versions | tail -1`) e rinumerare se un'altra PR ha preso il numero.
- `pnpm --filter web generate:api` richiede l'API viva su `:8000`; in alternativa aggiornare `apps/web/src/lib/api-types.ts` a mano con le stesse forme che il generatore produrrebbe (guardare come è tipizzato `/api/auth/login`).

---

### Task 1: le impostazioni e il modulo `pigrocrm.core.mail`

**Files:**
- Modify: `packages/core/src/pigrocrm/core/config.py` (tre campi)
- Create: `packages/core/src/pigrocrm/core/mail.py`
- Modify: `.env.example`
- Test: `packages/core/tests/test_mail.py` (nuovo)

**Interfaces:**
- Produces: `Settings.resend_api_key: str` (`PIGROCRM_RESEND_API_KEY`, `repr=False`), `Settings.mail_from: str = "PigroCRM <ciao@joinorbiters.com>"`, `Settings.magic_link_minutes: int = 15`; in `mail.py`: `Mail(to, subject, text, html=None)`, `EmailSender` (Protocol, `send(mail) -> bool`), `RecordingSender` (`.sent: list[Mail]`), `ResendSender(api_key, sender, http=None)`, `sender_from_settings(settings) -> EmailSender | None`, `HttpCall = Callable[[str, str, dict[str, str], bytes], tuple[int, bytes]]`, `urllib_call`, e `magic_link_mail(to: str, links: Sequence[tuple[str, str]], minutes: int) -> Mail` dove ogni link è `(etichetta, url)`.

- [ ] **Step 1: Il test**

`packages/core/tests/test_mail.py`:

```python
"""The CRM's outbound mail: a seam, Resend behind it, and the one mail this slice sends."""

from pigrocrm.core.config import Settings
from pigrocrm.core.mail import (
    RESEND_URL,
    Mail,
    RecordingSender,
    ResendSender,
    magic_link_mail,
    sender_from_settings,
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_without_a_key_there_is_no_sender() -> None:
    assert sender_from_settings(_settings()) is None


def test_with_a_key_the_sender_is_resend_with_the_configured_from() -> None:
    sender = sender_from_settings(_settings(resend_api_key="re_x", mail_from="PigroCRM <ciao@x.it>"))
    assert isinstance(sender, ResendSender)
    assert sender.sender == "PigroCRM <ciao@x.it>"


def test_resend_posts_one_json_object_with_the_key_as_bearer() -> None:
    calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def http(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        calls.append((method, url, headers, body))
        return 200, b"{}"

    sender = ResendSender("re_x", "PigroCRM <ciao@x.it>", http=http)
    assert sender.send(Mail(to="ada@x.it", subject="s", text="t", html="<p>t</p>")) is True
    (method, url, headers, body) = calls[0]
    assert (method, url) == ("POST", RESEND_URL)
    assert headers["Authorization"] == "Bearer re_x"
    assert b'"to": ["ada@x.it"]' in body and b'"html": "<p>t</p>"' in body


def test_resend_never_raises_and_answers_false_on_a_failure() -> None:
    def boom(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        raise OSError("down")

    assert ResendSender("re_x", "x", http=boom).send(Mail(to="a@x.it", subject="s", text="t")) is False
    assert ResendSender("re_x", "x", http=lambda *a: (500, b"")).send(
        Mail(to="a@x.it", subject="s", text="t")
    ) is False


def test_the_magic_link_mail_carries_every_link_and_the_minutes() -> None:
    mail = magic_link_mail(
        "ada@x.it",
        [("studio-ada", "https://pigro.test/studio-ada/app/entra?t=abc"), ("secondo", "https://pigro.test/secondo/app/entra?t=def")],
        15,
    )
    assert mail.to == "ada@x.it"
    assert "15 minuti" in mail.text
    assert "https://pigro.test/studio-ada/app/entra?t=abc" in mail.text
    assert "https://pigro.test/secondo/app/entra?t=def" in mail.text
    assert mail.html is not None and "studio-ada" in mail.html and "&lt;" not in mail.text
    # A token that tried to close the tag is escaped in the HTML.
    hostile = magic_link_mail("a@x.it", [("x", 'https://pigro.test/x/app/entra?t="><script>')], 15)
    assert hostile.html is not None and "<script>" not in hostile.html


def test_the_recording_sender_keeps_what_it_was_given() -> None:
    recording = RecordingSender()
    mail = Mail(to="a@x.it", subject="s", text="t")
    assert recording.send(mail) is True
    assert recording.sent == [mail]
```

- [ ] **Step 2: Vederlo fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_mail.py`
Expected: FAIL, `ModuleNotFoundError: pigrocrm.core.mail`.

- [ ] **Step 3: Le impostazioni**

In `config.py`, dopo il blocco Gmail (dopo `google_app_unverified`), aggiungere:

```python
    # --- Outbound mail (spec 2026-09-12 §6.1). Resend sends the login link and the
    # welcome mail. Empty key: no sender, and the endpoints that would mail answer 503
    # with a sentence rather than pretend. `repr=False` for the same reason as the Google
    # secret above: a Settings object reaches logs and tracebacks.
    resend_api_key: str = Field(default="", repr=False)
    # joinorbiters.com already carries SPF and DKIM for Resend (the hub sends from it).
    mail_from: str = "PigroCRM <ciao@joinorbiters.com>"
    # How long a link by mail is good for. Fifteen, like the hub's.
    magic_link_minutes: int = Field(default=15, ge=1, le=120)
```

In `.env.example`, dopo il blocco `PIGROCRM_REGISTRY_TOKEN`:

```
# --- Outbound mail (spec 2026-09-12 §6.1). Resend sends the login link («Mandami il
# link») and the welcome mail of a new space. Leave the key empty and the CRM sends
# nothing: those endpoints answer 503 with a sentence, the password login still works.
# The sender must be on a domain Resend verified; joinorbiters.com already is.
PIGROCRM_RESEND_API_KEY=
PIGROCRM_MAIL_FROM=PigroCRM <ciao@joinorbiters.com>
```

- [ ] **Step 4: `mail.py`**

`packages/core/src/pigrocrm/core/mail.py`. Stessa architettura di `projects/hub/packages/core/src/orbiters_core/mail.py` (leggerlo prima), riscritta qui perché il CRM non può importare dall'hub:

```python
"""Outbound mail: a seam, one provider, and the mails PigroCRM sends (spec 2026-09-12 §6.1).

The seam exists so tests never send and production never guesses: `sender_from_settings`
answers `None` without a key, and the API turns that into a 503 sentence rather than a
mail that does not arrive. Nothing here raises past `send`, and nothing logs an address
or the key. The HTML is the same box the hub's mails use (tables, inline styles, the
brand values written out), with PigroCRM's name and the site's legal pages.

Same shape as `orbiters_core/mail.py` on purpose, and not an import of it: the two
products do not import each other (root `AGENTS.md`), and eighty lines are cheaper than
a dependency between two release trains.
"""

import html as html_escape
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pigrocrm.core.config import Settings

RESEND_URL = "https://api.resend.com/emails"

HttpCall = Callable[[str, str, dict[str, str], bytes], tuple[int, bytes]]


def urllib_call(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    """The one HTTP call this module makes, as a function so a test can replace it."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed https URL
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str | None = None


class EmailSender(Protocol):
    def send(self, mail: Mail) -> bool:
        """`True` when the provider accepted it. Never raises."""
        ...


class RecordingSender:
    """Keeps every mail in a list. For tests, and for reading a link in development."""

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
        body: dict[str, object] = {
            "from": self.sender,
            "to": [mail.to],
            "subject": mail.subject,
            "text": mail.text,
        }
        if mail.html is not None:
            body["html"] = mail.html
        payload = json.dumps(body).encode()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            status, _ = self.http("POST", RESEND_URL, headers, payload)
        except Exception:  # noqa: BLE001 - the seam's contract is "never raises"
            return False
        return 200 <= status < 300


def sender_from_settings(settings: Settings) -> EmailSender | None:
    if not settings.resend_api_key:
        return None
    return ResendSender(settings.resend_api_key, settings.mail_from)


# ---- the box, as a mail ------------------------------------------------------------
# `shared/brand/palette.css` is the source of these values; a mail cannot read a
# stylesheet, so they are written out here.
PAPER = "#f1f2f3"
INK = "#011936"
INK_QUIET = "#465362"
ROYAL_GOLD = "#f9dc5c"
WATERMELON = "#ed254e"
CTA = "#e5133e"
FONT = "Outfit, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Arial, sans-serif"
STEP = 8
TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'
SITE = "https://joinorbiters.com"


def _quiet_link(href: str, label: str) -> str:
    return f'<a href="{href}" style="color:{INK_QUIET};text-decoration:underline;">{label}</a>'


def _tile(colour: str) -> str:
    size = "width:10px;height:10px;line-height:0;font-size:0;"
    return f'<td width="10" height="10" bgcolor="{colour}" style="{size}">&nbsp;</td>'


def _mark() -> str:
    return (
        f'<table {TABLE} style="border-collapse:collapse;">'
        f"<tr>{_tile(INK)}{_tile(ROYAL_GOLD)}</tr>"
        f"<tr>{_tile(WATERMELON)}{_tile(INK)}</tr>"
        "</table>"
    )


def _button(href: str, label: str) -> str:
    text = f"font-family:{FONT};font-size:17px;font-weight:500;color:#ffffff;"
    cell = f'bgcolor="{CTA}" style="background-color:{CTA};border:2px solid {CTA};padding:14px 24px;"'
    return (
        f'<table {TABLE} style="border-collapse:collapse;"><tr><td {cell}>'
        f'<a href="{href}" style="display:inline-block;{text}text-decoration:none;">{label}</a>'
        "</td></tr></table>"
    )


def _frame(title: str, body: str) -> str:
    ground = f'bgcolor="{PAPER}" style="background-color:{PAPER};"'
    name = f"font-family:{FONT};font-size:18px;font-weight:500;color:{INK};"
    step = f'bgcolor="{INK}" style="background-color:{INK};padding:0 {STEP}px {STEP}px 0;"'
    card = f'bgcolor="#ffffff" style="background-color:#ffffff;border:2px solid {INK};"'
    copy = f"font-family:{FONT};font-size:17px;font-weight:400;line-height:1.6;color:{INK};"
    fine = f"font-family:{FONT};font-size:13px;line-height:1.6;color:{INK_QUIET};"
    gap = "&nbsp;&nbsp;&nbsp;"
    footer = gap.join(
        (
            _quiet_link(f"{SITE}/pigrocrm", "PigroCRM"),
            _quiet_link(f"{SITE}/privacy", "Privacy"),
            _quiet_link(f"{SITE}/termini", "Termini"),
        )
    )
    return "\n".join(
        (
            "<!DOCTYPE html>",
            '<html lang="it">',
            '<head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<meta name="color-scheme" content="light">',
            '<meta name="supported-color-schemes" content="light">',
            f"<title>{html_escape.escape(title)}</title></head>",
            f'<body style="margin:0;padding:0;background-color:{PAPER};">',
            f'<table {TABLE} width="100%" {ground}>',
            '<tr><td align="center" style="padding:32px 16px 40px 16px;">',
            f'<table {TABLE} width="560" style="width:560px;max-width:100%;">',
            '<tr><td style="padding:0 0 20px 0;">',
            f"<table {TABLE}><tr>",
            f'<td valign="middle" style="padding-right:10px;">{_mark()}</td>',
            f'<td valign="middle" style="{name}">PigroCRM</td>',
            "</tr></table>",
            "</td></tr>",
            f"<tr><td {step}>",
            f'<table {TABLE} width="100%" {card}>',
            f'<tr><td style="padding:36px 36px 32px 36px;{copy}">',
            body,
            "</td></tr></table>",
            "</td></tr>",
            f'<tr><td style="padding:24px 0 0 0;{fine}">{footer}</td></tr>',
            "</table>",
            "</td></tr></table>",
            "</body></html>",
        )
    )


def magic_link_mail(to: str, links: Sequence[tuple[str, str]], minutes: int) -> Mail:
    """The way in: one link per space the address owns (usually one), how long they last,
    and that ignoring the mail is fine. `links` are `(label, url)`; the label is the
    space's name, shown when there is more than one."""
    several = len(links) > 1
    paragraph = 'style="margin:24px 0 0 0;"'
    small = f'style="margin:24px 0 0 0;font-size:13px;line-height:1.5;color:{INK_QUIET};'
    intro = (
        "questi sono i link per entrare nei tuoi spazi PigroCRM:"
        if several
        else "questo è il link per entrare nel tuo spazio PigroCRM:"
    )
    text_links = "\n".join(
        (f"{label}: {url}" if several else url) for label, url in links
    )
    text = (
        "Ciao,\n\n"
        f"{intro}\n\n{text_links}\n\n"
        f"Vale {minutes} minuti e funziona una volta sola. Se non l'hai chiesto tu, ignora "
        "questa mail: non succede niente.\n\n"
        "PigroCRM\n"
    )
    buttons = "\n".join(
        (
            f'<p {paragraph}><strong>{html_escape.escape(label)}</strong></p>' if several else ""
        )
        + _button(html_escape.escape(url, quote=True), "Entra nel tuo spazio")
        + f'<p {small}word-break:break-all;">Se il bottone non si apre, copia questo indirizzo '
        f"nel browser:<br>{_quiet_link(html_escape.escape(url, quote=True), html_escape.escape(url))}</p>"
        for label, url in links
    )
    body = "\n".join(
        (
            '<p style="margin:0 0 20px 0;">Ciao,</p>',
            f'<p style="margin:0 0 24px 0;">{intro}</p>',
            buttons,
            f"<p {paragraph}>Vale {minutes} minuti e funziona una volta sola. "
            "Se non l'hai chiesto tu, ignora questa mail: non succede niente.</p>",
            f"<p {paragraph}>PigroCRM</p>",
        )
    )
    subject = "Il tuo accesso a PigroCRM"
    return Mail(to=to, subject=subject, text=text, html=_frame(subject, body))
```

- [ ] **Step 5: Test, lint, tipi**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_mail.py projects/pigrocrm/packages/core/tests/test_architecture.py && uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: verde e pulito. Se ruff segnala `S310` con un altro codice o non lo segnala, adeguare il `noqa`.

- [ ] **Step 6: Commit**

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/config.py projects/pigrocrm/packages/core/src/pigrocrm/core/mail.py projects/pigrocrm/.env.example projects/pigrocrm/packages/core/tests/test_mail.py
git commit -m "feat(core): the CRM can send mail through Resend, behind a seam that never raises" -m "Same shape as the hub's mail.py and not an import of it: the two products do not import each other. Without a key there is no sender, and the callers answer 503 with a sentence.

ORB-172."
```

---

### Task 2: la migrazione e i modelli

**Files:**
- Create: `packages/core/migrations/versions/0034_magic_links.py`
- Modify: `packages/core/src/pigrocrm/core/auth/models.py` (due colonne)
- Create: `packages/core/src/pigrocrm/core/auth/magic_models.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Modify: `packages/core/src/pigrocrm/core/auth/service.py` (`authenticate`)
- Test: `packages/core/tests/test_auth_service.py` o il file dove vive oggi `authenticate` (trovarlo con `grep -rn "def test_.*authenticate" packages/core/tests`)

**Interfaces:**
- Produces: `User.password_hash: Mapped[str | None]`, `User.email_verificata_il: Mapped[datetime | None]`; `MagicLinkToken(id, user_id, token_hash, expires_at, used_at, created_at)` con `__tablename__ = "magic_link_tokens"`.

- [ ] **Step 1: Il test su `authenticate`**

Nel file dei test del servizio utenti, aggiungere:

```python
def test_a_user_without_a_password_cannot_log_in_with_one(db_session: Session) -> None:
    service = UserService(db_session)
    created = service.create(
        UserCreate(email="link@x.it", password="lunghissima1", nome="Link", ruolo="admin"),
        Actor.system(),
    )
    row = UserRepository(db_session).get(created.id)
    assert row is not None
    row.password_hash = None
    db_session.flush()
    with pytest.raises(ValidationFailed) as excinfo:
        service.authenticate("link@x.it", "lunghissima1")
    assert INVALID_CREDENTIALS in str(excinfo.value)
```

(`INVALID_CREDENTIALS` è la costante che `authenticate` già usa; importarla da `pigrocrm.core.auth.service`.)

- [ ] **Step 2: Vederlo fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests -k without_a_password`
Expected: FAIL con `IntegrityError` (la colonna è ancora NOT NULL) o `TypeError` in `verify_password`.

- [ ] **Step 3: I modelli**

`auth/models.py`: `password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)` con il commento «`None` for a user who has only ever entered with a link by mail (spec 2026-09-12 §6.2); `authenticate` refuses them like a wrong password.»; e dopo `attivo`:

```python
    # When a link by mail was first used by this user: the moment the address stopped
    # being a claim. Written once by `MagicLinkService.enter`, which also revokes every
    # session issued before it. `None` for the accounts that only ever used a password.
    email_verificata_il: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
```

Aggiungere `from datetime import datetime` e `DateTime` agli import di sqlalchemy.

`auth/magic_models.py`:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class MagicLinkToken(Base, PrimaryKeyMixin, TimestampMixin):
    """One row per link sent (spec 2026-09-12 §6.2). Only the SHA-256 of the raw token
    is stored, so a dump of this table opens nothing. Spent rows keep `used_at`, so a
    second click can be told from a link that never existed; `MagicLinkService.request`
    sweeps a user's spent and expired rows before writing a new one."""

    __tablename__ = "magic_link_tokens"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

`models_registry.py`: `from pigrocrm.core.auth.magic_models import MagicLinkToken  # noqa: F401` dopo la riga di `PersonalAccessToken`.

- [ ] **Step 4: La migrazione**

`packages/core/migrations/versions/0034_magic_links.py`:

```python
"""a link by mail is a way in: nullable password, verified-at, magic_link_tokens

Revision ID: 0034
Revises: 0033

Spec 2026-09-12 §6.2. In PigroCRM one enters as in the community, with a link by mail;
the password stays as a second way for whoever has one and is never asked again.

`users.password_hash` becomes nullable: a person who created their space through the
wizard has no password at all, and `UserService.authenticate` refuses such a user with
the same sentence and cost as a wrong password. `users.email_verificata_il` records the
first time a link by mail was used; that entry also revokes every refresh token issued
before it, which is what makes the session opened at signup safe.

`magic_link_tokens` holds the SHA-256 of each link sent, its expiry and when it was
spent. No downgrade of the nullability if a row has `NULL`: the downgrade would have to
invent a password, and it does not.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)
    op.add_column(
        "users", sa.Column("email_verificata_il", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_magic_link_tokens_user_id", "magic_link_tokens", ["user_id"])
    op.create_index(
        "uq_magic_link_tokens_token_hash", "magic_link_tokens", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_magic_link_tokens_token_hash", table_name="magic_link_tokens")
    op.drop_index("ix_magic_link_tokens_user_id", table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")
    op.drop_column("users", "email_verificata_il")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
```

Controllare in `db/base.py` come `TimestampMixin.updated_at` è dichiarato (`onupdate`?) e allineare la colonna. Poi verificare che la migrazione e i modelli coincidano: c'è un test che confronta `Base.metadata` con `alembic upgrade head` (cercare `grep -rln "compare_metadata\|alembic" packages/core/tests`); eseguirlo.

- [ ] **Step 5: `authenticate`**

In `auth/service.py`:

```python
    def authenticate(self, email: str, password: str) -> UserRead:
        user = self.repo.get_by_email(email)
        # Compare against a precomputed constant hash when the user is missing or has
        # never had a password (a link-by-mail account, spec 2026-09-12 §6.2), so every
        # path costs exactly one verify and timing does not reveal which case it was.
        has_password = user is not None and user.password_hash is not None
        reference = user.password_hash if has_password and user else dummy_hash()
        ok = verify_password(password, reference)
        if user is None or not has_password or not ok or not user.attivo:
            raise ValidationFailed("user", "credentials", INVALID_CREDENTIALS)
        return UserRead.model_validate(user)
```

(mypy: `reference` deve essere `str`; se si lamenta, scrivere `reference = user.password_hash if user is not None and user.password_hash is not None else dummy_hash()`.)

- [ ] **Step 6: Test, lint, tipi**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests -k "authenticate or without_a_password or metadata or migration" && uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_tenants.py -k provisioning_creates` (il provisioning esegue `alembic upgrade head` vero: se la migrazione non gira, si vede qui) `&& uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: verde e pulito.

- [ ] **Step 7: Commit (migrazione da sola, come vuole la skill `pr-creation`)**

```bash
git add projects/pigrocrm/packages/core/migrations/versions/0034_magic_links.py
git commit -m "feat(core): migration 0034, a nullable password, a verified-at and the magic_link_tokens table" -m "ORB-172."
git add projects/pigrocrm/packages/core/src/pigrocrm/core/auth/models.py projects/pigrocrm/packages/core/src/pigrocrm/core/auth/magic_models.py projects/pigrocrm/packages/core/src/pigrocrm/core/models_registry.py projects/pigrocrm/packages/core/src/pigrocrm/core/auth/service.py projects/pigrocrm/packages/core/tests/<il file dei test>
git commit -m "feat(core): a user may have no password, and the password login refuses them like a wrong one" -m "Same sentence, same cost: a link-by-mail account is not distinguishable from an unknown address through the password form.

ORB-172."
```

---

### Task 3: `MagicLinkService`

**Files:**
- Create: `packages/core/src/pigrocrm/core/auth/magic_link.py`
- Modify: `packages/core/src/pigrocrm/core/auth/refresh_service.py` (un metodo pubblico)
- Test: `packages/core/tests/test_magic_link.py` (nuovo)

**Interfaces:**
- Consumes: `UserRepository.get_by_email`, `RefreshTokenService`, `Settings.magic_link_minutes`.
- Produces: `MagicLinkService(session, settings)` con `request(email: str) -> str | None` (il token grezzo, o `None` se nessun utente attivo ha quell'email) e `enter(raw: str) -> UserRead | None`; `RefreshTokenService.revoke_all(user_id, now)` (pubblico, chiama `_revoke_all_valid`).

- [ ] **Step 1: Il test**

`packages/core/tests/test_magic_link.py`:

```python
"""A link by mail as a way in (spec 2026-09-12 §6.2)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.magic_link import MagicLinkService, _hash
from pigrocrm.core.auth.magic_models import MagicLinkToken
from pigrocrm.core.auth.refresh_models import RefreshToken
from pigrocrm.core.auth.refresh_service import RefreshTokenService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings

SETTINGS = Settings(_env_file=None)  # type: ignore[call-arg]


def _user(session: Session, email: str = "ada@x.it") -> UserService:
    service = UserService(session)
    service.create(
        UserCreate(email=email, password="lunghissima1", nome="Ada", ruolo="admin"), Actor.system()
    )
    return service


def test_request_answers_a_token_for_a_known_address_and_none_otherwise(db_session: Session) -> None:
    _user(db_session)
    links = MagicLinkService(db_session, SETTINGS)
    raw = links.request("Ada@X.it")
    assert raw is not None and len(raw) >= 32
    assert links.request("nessuno@x.it") is None
    row = db_session.scalar(select(MagicLinkToken))
    assert row is not None and row.token_hash == _hash(raw) and row.used_at is None
    assert row.expires_at > datetime.now(UTC) + timedelta(minutes=14)


def test_enter_spends_the_token_once_and_verifies_the_address(db_session: Session) -> None:
    _user(db_session)
    links = MagicLinkService(db_session, SETTINGS)
    raw = links.request("ada@x.it")
    assert raw is not None
    user = links.enter(raw)
    assert user is not None and user.email == "ada@x.it"
    assert links.enter(raw) is None  # spent
    row = UserRepository(db_session).get_by_email("ada@x.it")
    assert row is not None and row.email_verificata_il is not None


def test_the_first_entry_revokes_the_sessions_issued_before_it(db_session: Session) -> None:
    _user(db_session)
    user = UserRepository(db_session).get_by_email("ada@x.it")
    assert user is not None
    RefreshTokenService(db_session).issue(user.id, SETTINGS)  # the session opened at signup
    links = MagicLinkService(db_session, SETTINGS)
    raw = links.request("ada@x.it")
    assert raw is not None and links.enter(raw) is not None
    alive = db_session.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.consumed_at.is_(None))
    ).all()
    assert alive == []
    # A later entry is an ordinary login: it revokes nothing.
    RefreshTokenService(db_session).issue(user.id, SETTINGS)
    raw2 = links.request("ada@x.it")
    assert raw2 is not None and links.enter(raw2) is not None
    assert (
        len(
            db_session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user.id, RefreshToken.consumed_at.is_(None)
                )
            ).all()
        )
        == 1
    )


def test_an_expired_or_unknown_or_inactive_link_answers_none(db_session: Session) -> None:
    service = _user(db_session)
    links = MagicLinkService(db_session, SETTINGS)
    assert links.enter("") is None
    assert links.enter("non-esiste") is None
    raw = links.request("ada@x.it")
    assert raw is not None
    row = db_session.scalar(select(MagicLinkToken))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert links.enter(raw) is None
    raw2 = links.request("ada@x.it")
    assert raw2 is not None
    user = UserRepository(db_session).get_by_email("ada@x.it")
    assert user is not None
    service.deactivate(user.id, Actor.system())  # check the real method name in UserService
    assert links.enter(raw2) is None


def test_request_sweeps_the_spent_and_expired_rows_of_that_user(db_session: Session) -> None:
    _user(db_session)
    links = MagicLinkService(db_session, SETTINGS)
    first = links.request("ada@x.it")
    assert first is not None and links.enter(first) is not None
    links.request("ada@x.it")
    rows = db_session.scalars(select(MagicLinkToken)).all()
    assert len(rows) == 1 and rows[0].used_at is None
```

(Se `UserService` chiama la disattivazione in un altro modo, usare quello: `grep -n "def " packages/core/src/pigrocrm/core/auth/service.py`.)

- [ ] **Step 2: Vederlo fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_magic_link.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Il metodo pubblico su `RefreshTokenService`**

In `refresh_service.py`, dopo `consume`:

```python
    def revoke_all(self, user_id: UUID, now: datetime | None = None) -> None:
        """Every still-valid refresh token of `user_id` is consumed. Public for the one
        caller outside this class that has a reason: `MagicLinkService.enter`, on the
        first link entry of a user, when whoever opened a session before the address was
        proven must lose it (spec 2026-09-12 §6.2)."""
        self._revoke_all_valid(user_id, now or datetime.now(UTC))
```

- [ ] **Step 4: Il servizio**

`auth/magic_link.py`:

```python
"""A link by mail as the way in (spec 2026-09-12 §6.2), the hub's shape in the CRM.

`request` answers the raw token or `None`; the caller builds the URL and the mail,
because only the router knows which prefix and which public origin the link must wear.
`enter` spends the token with a conditional UPDATE gated on it still being unused, so of
two requests racing on the same raw token (a mail scanner's prefetch against the
person's own click) only one opens a session.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from pigrocrm.core.auth.magic_models import MagicLinkToken
from pigrocrm.core.auth.refresh_service import RefreshTokenService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserRead
from pigrocrm.core.config import Settings


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class MagicLinkService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)

    def request(self, email: str) -> str | None:
        """The raw token for an active user with this address, or `None`. Sweeps the
        person's spent and expired tokens first: nothing needs a cron."""
        user = self.users.get_by_email(email.strip().lower())
        if user is None or not user.attivo:
            return None
        now = datetime.now(UTC)
        self.session.execute(
            delete(MagicLinkToken).where(
                MagicLinkToken.user_id == user.id,
                or_(MagicLinkToken.used_at.is_not(None), MagicLinkToken.expires_at <= now),
            )
        )
        raw = secrets.token_urlsafe(32)
        self.session.add(
            MagicLinkToken(
                user_id=user.id,
                token_hash=_hash(raw),
                expires_at=now + timedelta(minutes=self.settings.magic_link_minutes),
            )
        )
        self.session.commit()
        return raw

    def enter(self, raw: str) -> UserRead | None:
        """The user, or `None` for a wrong, spent or expired link, or an inactive user.
        The first entry of a user writes `email_verificata_il` and revokes every refresh
        token issued before it: the address was a claim until this click."""
        if not raw:
            return None
        now = datetime.now(UTC)
        token = self.session.scalar(
            select(MagicLinkToken).where(MagicLinkToken.token_hash == _hash(raw))
        )
        if token is None or token.used_at is not None or token.expires_at <= now:
            return None
        user = self.users.get(token.user_id)
        if user is None or not user.attivo:
            return None
        spent = self.session.execute(
            update(MagicLinkToken)
            .where(MagicLinkToken.id == token.id, MagicLinkToken.used_at.is_(None))
            .values(used_at=now)
            .returning(MagicLinkToken.id)
        )
        if len(spent.scalars().all()) != 1:
            self.session.rollback()
            return None
        if user.email_verificata_il is None:
            user.email_verificata_il = now
            self.session.flush()
            # Commits, and takes the flush above with it.
            RefreshTokenService(self.session).revoke_all(user.id, now)
        else:
            self.session.commit()
        return UserRead.model_validate(user)
```

- [ ] **Step 5: Test, lint, tipi**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_magic_link.py projects/pigrocrm/packages/core/tests/test_refresh*.py && uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: verde e pulito.

- [ ] **Step 6: Commit**

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/auth/magic_link.py projects/pigrocrm/packages/core/src/pigrocrm/core/auth/refresh_service.py projects/pigrocrm/packages/core/tests/test_magic_link.py
git commit -m "feat(core): MagicLinkService issues a link token and spends it once, revoking earlier sessions on the first entry" -m "The hub's shape: a hashed token, a conditional UPDATE so a prefetch cannot consume the click. The first entry is where the address stops being a claim, so the sessions opened before it (the one a signup opens) die there.

ORB-172."
```

---

### Task 4: `POST /api/auth/link` e `POST /api/auth/entra`

**Files:**
- Modify: `apps/api/src/pigrocrm_api/routers/auth.py`
- Test: `apps/api/tests/test_auth_api.py` (in coda) e `apps/api/tests/test_tenants_api.py` (un test per la radice con spazi)

**Interfaces:**
- Consumes: `MagicLinkService`, `magic_link_mail`, `sender_from_settings`, `TenantService.list()`, `tenant_database_url`, `tenant_database_name`, `tenant_slug(request)`, `cookie_path`, `_set_cookie`, `_clear_other_jars`, `issue_access_token`, `RefreshTokenService.issue`.
- Produces: `get_sender(settings) -> EmailSender | None` (dipendenza da sovrascrivere nei test), `POST /api/auth/link {email}` → 202 `{"ok": true}` / 503; `POST /api/auth/entra {t}` → 200 `UserRead` + cookie / 401 «link non valido o scaduto».

- [ ] **Step 1: I test**

In coda a `apps/api/tests/test_auth_api.py`:

```python
# --- a link by mail (spec 2026-09-12 §6.2) --------------------------------------------

from pigrocrm.core.mail import RecordingSender
from pigrocrm_api.routers.auth import get_sender


@pytest.fixture
def sender(client: TestClient) -> RecordingSender:
    recording = RecordingSender()
    client.app.dependency_overrides[get_sender] = lambda: recording  # type: ignore[attr-defined]
    return recording


def _token_from(mail_text: str) -> str:
    return mail_text.split("?t=", 1)[1].split()[0]


def test_link_answers_202_and_mails_a_known_address(client: TestClient, admin_user, sender: RecordingSender) -> None:
    response = client.post("/api/auth/link", json={"email": ADMIN_EMAIL.upper()})
    assert response.status_code == 202
    assert len(sender.sent) == 1
    mail = sender.sent[0]
    assert mail.to == ADMIN_EMAIL and "/app/entra?t=" in mail.text and "15 minuti" in mail.text


def test_link_answers_202_and_mails_nothing_for_an_unknown_address(client: TestClient, sender: RecordingSender) -> None:
    response = client.post("/api/auth/link", json={"email": "nessuno@pigro.it"})
    assert response.status_code == 202
    assert sender.sent == []


def test_link_is_503_without_a_sender(client: TestClient, admin_user) -> None:
    response = client.post("/api/auth/link", json={"email": ADMIN_EMAIL})
    assert response.status_code == 503
    assert "non è" in response.json()["detail"]


def test_entra_sets_the_cookies_and_me_answers(client: TestClient, admin_user, sender: RecordingSender) -> None:
    client.post("/api/auth/link", json={"email": ADMIN_EMAIL})
    token = _token_from(sender.sent[0].text)
    response = client.post("/api/auth/entra", json={"t": token})
    assert response.status_code == 200, response.text
    assert response.json()["email"] == ADMIN_EMAIL
    set_cookie = response.headers.get_list("set-cookie")
    assert any("pigrocrm_access=" in c and "Path=/" in c for c in set_cookie)
    assert client.get("/api/auth/me").status_code == 200
    # Spent: the same link a second time is a 401 with the sentence the page shows.
    again = client.post("/api/auth/entra", json={"t": token})
    assert again.status_code == 401 and "link" in again.json()["detail"]


def test_entra_with_garbage_is_401(client: TestClient) -> None:
    assert client.post("/api/auth/entra", json={"t": "x"}).status_code == 401
```

In `apps/api/tests/test_tenants_api.py`, dopo aver letto come `spaces_client` provisiona uno spazio (fixture e helper già presenti in quel file), un test:

```python
def test_a_link_asked_at_the_root_reaches_the_space_that_address_owns(spaces_client: TestClient) -> None:
    from pigrocrm.core.mail import RecordingSender
    from pigrocrm_api.routers.auth import get_sender

    recording = RecordingSender()
    spaces_client.app.dependency_overrides[get_sender] = lambda: recording  # type: ignore[attr-defined]
    created = spaces_client.post(
        "/api/tenants/", json={"slug": "linkato", "nome": "Ada", "email": "ada@linkato.it", "password": "lunghissima1"}
    )
    assert created.status_code == 201, created.text
    response = spaces_client.post("/api/auth/link", json={"email": "ada@linkato.it"})
    assert response.status_code == 202
    assert len(recording.sent) == 1 and "/linkato/app/entra?t=" in recording.sent[0].text
    token = recording.sent[0].text.split("?t=", 1)[1].split()[0]
    entered = spaces_client.post("/linkato/api/auth/entra", json={"t": token})
    assert entered.status_code == 200, entered.text
    assert any("Path=/linkato/" in c for c in entered.headers.get_list("set-cookie"))
    assert spaces_client.get("/linkato/api/auth/me").status_code == 200
```

(Adattare la pulizia dello spazio a come il file già la fa per gli altri test: cercare `_drop` o una fixture `clean`.)

- [ ] **Step 2: Vederli fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/apps/api/tests/test_auth_api.py -k "link or entra"`
Expected: FAIL, `ImportError: get_sender`.

- [ ] **Step 3: Il router**

In `routers/auth.py`, import aggiuntivi:

```python
from collections.abc import Callable
from typing import Annotated

from fastapi import BackgroundTasks, Depends
from sqlalchemy import create_engine

from pigrocrm.core.auth.magic_link import MagicLinkService
from pigrocrm.core.db.session import session_factory
from pigrocrm.core.mail import EmailSender, Mail, magic_link_mail, sender_from_settings
from pigrocrm.core.tenants import TenantService
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url
from pigrocrm_api.deps import TenantsRegistryDep
from pigrocrm_api.tenancy import tenant_slug
```

La dipendenza del mittente, dichiarata qui e non in `deps.py` (ORB-170 lo sta cambiando):

```python
def get_sender(settings: SettingsDep) -> EmailSender | None:
    """The mail sender, or `None` without a key: the endpoints that mail answer 503."""
    return sender_from_settings(settings)


SenderDep = Annotated[EmailSender | None, Depends(get_sender)]

NO_SENDER = "L'accesso via email non è ancora attivo su questa installazione. Entra con la password."
INVALID_LINK = "Questo link non è valido o è scaduto. Chiedine un altro."


class LinkRequest(BaseModel):
    email: SafeStr


class LinkToken(BaseModel):
    t: SafeStr


class Ack(BaseModel):
    ok: bool = True


def _send(sender: EmailSender, mail: Mail) -> None:
    sender.send(mail)


def _origin(request: Request, settings: Settings) -> str:
    """Where the link points: the configured public origin, else the request's own."""
    return settings.public_url.rstrip("/") or str(request.base_url).rstrip("/")


def _entra_url(origin: str, prefix: str, raw: str) -> str:
    return f"{origin}{prefix}/app/entra?t={raw}"
```

L'endpoint del link:

```python
@router.post("/link", response_model=Ack, status_code=status.HTTP_202_ACCEPTED)
def request_link(
    payload: LinkRequest,
    request: Request,
    background: BackgroundTasks,
    session: SessionDep,
    registry: TenantsRegistryDep,
    settings: SettingsDep,
    sender: SenderDep,
) -> Ack:
    """A link by mail (spec 2026-09-12 §6.2). Under a space's prefix, the space's own
    user. At the root, every space the registry says this address owns gets a link in
    one mail, and the root itself is tried when none does. 202 whether the address is
    known or not, and the mail leaves after the response, so neither the status nor the
    timing says which; 503 while no sender is configured."""
    if sender is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_SENDER)
    email = payload.email.strip().lower()
    origin = _origin(request, settings)
    links: list[tuple[str, str]] = []
    slug = tenant_slug(request)
    if slug is not None:
        raw = MagicLinkService(session, settings).request(email)
        if raw:
            links.append((slug, _entra_url(origin, f"/{slug}", raw)))
    else:
        owned = [t.slug for t in TenantService(registry, settings).list() if t.owner_email == email]
        for owned_slug in owned:
            engine = create_engine(
                tenant_database_url(settings, tenant_database_name(owned_slug)), future=True
            )
            try:
                with session_factory(engine)() as space:
                    raw = MagicLinkService(space, settings).request(email)
            finally:
                engine.dispose()
            if raw:
                links.append((owned_slug, _entra_url(origin, f"/{owned_slug}", raw)))
        if not links:
            raw = MagicLinkService(session, settings).request(email)
            if raw:
                # The root logs in on the bare page (decision 2026-09-09); its cookies
                # live at `/`, so the entry page is the bare one too.
                links.append((settings.root_slug or "PigroCRM", _entra_url(origin, "", raw)))
    if links:
        background.add_task(_send, sender, magic_link_mail(email, links, settings.magic_link_minutes))
    return Ack()
```

L'ingresso:

```python
@router.post("/entra", response_model=UserRead, responses={401: _UNAUTHENTICATED_RESPONSE})
def enter_with_link(
    payload: LinkToken,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> UserRead:
    """Spends the link and opens the session, with the cookies `login` sets."""
    user = MagicLinkService(session, settings).enter(payload.t)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LINK)
    _clear_other_jars(response, request, settings)
    _set_cookie(
        response,
        ACCESS_COOKIE,
        issue_access_token(user.id, user.ruolo, settings),
        settings.access_token_minutes * 60,
        secure=settings.cookie_secure,
        path=cookie_path(request),
    )
    _set_cookie(
        response,
        REFRESH_COOKIE,
        RefreshTokenService(session).issue(user.id, settings),
        settings.refresh_token_days * 86400,
        secure=settings.cookie_secure,
        path=cookie_path(request),
    )
    return user
```

Controllare che `TenantsRegistryDep` sia importabile senza ciclo (`deps.py` non importa i router) e che `spaces_client` nei test dei tenant usi un override di `get_settings` che punta al server dei test: `TenantService.list()` legge il registro di quel server.

- [ ] **Step 4: Test, lint, tipi**

Run: `uv run pytest -q -n 0 projects/pigrocrm/apps/api/tests/test_auth_api.py projects/pigrocrm/apps/api/tests/test_tenants_api.py projects/pigrocrm/apps/api/tests/test_error_rendering.py && uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: verde e pulito. `test_error_rendering.py` o un test sull'OpenAPI potrebbe chiedere che ogni 401 sia documentato: `enter_with_link` lo dichiara già.

- [ ] **Step 5: Commit**

```bash
git add projects/pigrocrm/apps/api/src/pigrocrm_api/routers/auth.py projects/pigrocrm/apps/api/tests/test_auth_api.py projects/pigrocrm/apps/api/tests/test_tenants_api.py
git commit -m "feat(api): POST /api/auth/link mails a way in, POST /api/auth/entra opens the session" -m "Under a prefix the space's own user; at the root every space the address owns, one mail, one link each. 202 either way and the mail leaves after the response, so nothing says whether the address is known. 503 while no sender is configured.

ORB-172."
```

---

### Task 5: il login email-first, la route `/app/entra`, i tipi dell'API

**Files:**
- Modify: `apps/web/src/lib/api-types.ts` (i due endpoint)
- Modify: `apps/web/src/lib/auth.tsx` (`enterWithLink`)
- Modify: `apps/web/src/routes/app/login.tsx`
- Create: `apps/web/src/routes/app/entra.tsx`
- Modify: `apps/web/src/routes/app.tsx` (`PUBLIC_ROUTES`)
- Test: `apps/web/src/routes/app/login.test.tsx` (nuovo), `apps/web/src/routes/app/entra.test.tsx` (nuovo)

**Interfaces:**
- Consumes: `POST /api/auth/link {email}` → 202 `{ok}`; `POST /api/auth/entra {t}` → `SessionUser`.
- Produces: `useAuth().enterWithLink(t: string): Promise<void>`; il login con `data-testid` stabili: `login-email`, `login-send-link`, `login-use-password`, `login-password`, `login-submit`.

- [ ] **Step 1: I tipi dell'API**

Con l'API viva (`uv run uvicorn pigrocrm_api.main:app --port 8000` da `projects/pigrocrm` con un `.env` locale) eseguire `pnpm --filter web generate:api`; altrimenti aggiungere a mano in `api-types.ts` le voci `"/api/auth/link"` e `"/api/auth/entra"` copiando la forma di `"/api/auth/login"` (request body `LinkRequest {email: string}` / `LinkToken {t: string}`, response 202 `Ack {ok: boolean}` / 200 `UserRead`, più il 401/422/503 come gli altri). Poi `pnpm --filter web build` deve compilare (`tsc --noEmit` è nel build).

- [ ] **Step 2: I test del login**

`apps/web/src/routes/app/login.test.tsx`, con lo stesso impianto di `registrati.test.tsx` (mock del router e di `@/lib/api`, più `@/lib/auth`):

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useNavigate: () => navigate, createFileRoute: () => (options: unknown) => options }
})
const login = vi.fn()
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: null, login }) }))
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } }
})

import { api } from '@/lib/api'
import { LoginPage } from './login'

const GET = api.GET as unknown as ReturnType<typeof vi.fn>
const POST = api.POST as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  GET.mockReset()
  POST.mockReset()
  login.mockReset()
  GET.mockResolvedValue({ data: { slug: null } })
})

describe('the login page', () => {
  it('asks only for the email and sends the link', async () => {
    POST.mockResolvedValue({ data: { ok: true }, response: { status: 202 } })
    render(<LoginPage />)
    expect(screen.queryByLabelText('Password')).toBeNull()
    await userEvent.type(screen.getByLabelText('Email'), 'ada@studio.it')
    await userEvent.click(screen.getByRole('button', { name: 'Mandami il link' }))
    await waitFor(() => expect(POST).toHaveBeenCalledWith('/api/auth/link', { body: { email: 'ada@studio.it' } }))
    expect(await screen.findByText(/Controlla la posta/)).toBeInTheDocument()
  })

  it('says when the installation cannot mail', async () => {
    POST.mockResolvedValue({ error: { detail: "L'accesso via email non è ancora attivo su questa installazione. Entra con la password." }, response: { status: 503 } })
    render(<LoginPage />)
    await userEvent.type(screen.getByLabelText('Email'), 'ada@studio.it')
    await userEvent.click(screen.getByRole('button', { name: 'Mandami il link' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/non è ancora attivo/)
  })

  it('still lets whoever has a password use it', async () => {
    render(<LoginPage />)
    await userEvent.click(screen.getByRole('button', { name: /Accedi con la password/ }))
    await userEvent.type(screen.getByLabelText('Email'), 'ada@studio.it')
    await userEvent.type(screen.getByLabelText('Password'), 'lunghissima1')
    await userEvent.click(screen.getByRole('button', { name: 'Accedi' }))
    await waitFor(() => expect(login).toHaveBeenCalledWith('ada@studio.it', 'lunghissima1'))
  })
})
```

Nota: `LoginPage` va esportata da `login.tsx` (oggi è una funzione locale). Il modo esatto in cui `unwrap` segnala un errore 503 va letto in `apps/web/src/lib/api.ts` e il secondo test adattato a quella forma (probabilmente `POST` che risolve con `{ error, response }` e `unwrap` che lancia; `toProblem(error).detail` è il testo).

- [ ] **Step 3: Il test di `/app/entra`**

`apps/web/src/routes/app/entra.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, createFileRoute: () => (options: unknown) => options }
})
const enterWithLink = vi.fn()
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: null, enterWithLink }) }))
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn().mockResolvedValue({ data: { slug: null } }), POST: vi.fn() } }
})

import { EnterPage } from './entra'

beforeEach(() => enterWithLink.mockReset())

describe('the entry page', () => {
  it('spends the token and goes to the home', async () => {
    enterWithLink.mockResolvedValue(undefined)
    const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {})
    render(<EnterPage token="abc" />)
    await waitFor(() => expect(enterWithLink).toHaveBeenCalledWith('abc'))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('/app/'))
  })

  it('shows the sentence and the way to ask another link when the token is dead', async () => {
    enterWithLink.mockRejectedValue({ detail: 'Questo link non è valido o è scaduto. Chiedine un altro.' })
    render(<EnterPage token="abc" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/non è valido/)
    expect(screen.getByRole('link', { name: /Torna al login/ })).toBeInTheDocument()
  })
})
```

(`window.location.assign` in jsdom può non essere spiabile: in quel caso `EnterPage` accetta una prop `go?: (url: string) => void` con default `window.location.assign`, e il test la passa. La stessa tecnica per il test 1 della pagina di login se serve.)

- [ ] **Step 4: Vederli fallire**

Run: `pnpm --filter web test -- login.test.tsx entra.test.tsx`
Expected: FAIL (export mancanti).

- [ ] **Step 5: `auth.tsx`**

Aggiungere a `AuthValue` `enterWithLink: (t: string) => Promise<void>` e in `AuthProvider`:

```tsx
  const enterMutation = useMutation({
    mutationFn: (body: { t: string }) => unwrap(api.POST('/api/auth/entra', { body })),
    onSuccess: (user) => queryClient.setQueryData(queryKeys.me, user),
  })
  // ...in value:
    enterWithLink: async (t) => {
      await enterMutation.mutateAsync({ t })
    },
```

- [ ] **Step 6: `login.tsx`**

Esportare `LoginPage`. Lo stato: `const [mode, setMode] = useState<'link' | 'password'>('link')`, `const [sent, setSent] = useState(false)`, `const [linkError, setLinkError] = useState<string | null>(null)`. Il form:

- Titolo e descrizione come oggi.
- Campo Email sempre presente (`id="email"`, `autoComplete="username"`).
- In `mode === 'link'`: bottone principale «Mandami il link» (`disabled={busy || email === ''}`); `onSubmit` chiama `unwrap(api.POST('/api/auth/link', { body: { email } }))`, su successo `setSent(true)`, su errore `setLinkError(toProblem(error).detail)`. Quando `sent`: al posto del form una riga `role="status"`: «Controlla la posta: il link vale 15 minuti. Se non arriva, guarda nello spam.» e un bottone ghost «Usa un'altra email» che rimette `sent` a `false`. L'errore in un `<p role="alert" className="text-destructive text-sm">`.
- Sotto, un bottone `variant="link"` «Hai una password? Accedi con la password» → `setMode('password')`.
- In `mode === 'password'`: il form di oggi (Email, Password, «Accedi») e sotto «Torna al link via email» → `setMode('link')`.
- Il bottone «Crea il tuo spazio» resta com'è, sotto entrambi i modi, solo sulla radice.
- L'effect di redirect su `user` resta identico.

- [ ] **Step 7: `entra.tsx`**

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { BrandMark } from '@/components/BrandMark'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { api, toProblem } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { tenantPrefix } from '@/lib/tenant'

/** Where a fresh session goes: the space's home, or the root's under its own name
 *  (the same rule as `login.tsx`). Asks `/api/tenants/root` only on the bare page. */
async function homeAfterEntry(): Promise<string> {
  if (tenantPrefix !== '') return `${tenantPrefix}/app/`
  const { data } = await api.GET('/api/tenants/root')
  return data?.slug ? `/${data.slug}/app/` : '/app/'
}

export function EnterPage({ token, go = (url) => window.location.assign(url) }: { token: string; go?: (url: string) => void }) {
  const { enterWithLink } = useAuth()
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        await enterWithLink(token)
        const target = await homeAfterEntry()
        if (!cancelled) go(target)
      } catch (caught) {
        if (!cancelled) setError(toProblem(caught).detail)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, enterWithLink, go])

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="inline-flex items-center text-2xl">
            <BrandMark className="mr-2.5 size-3.5" />
            {error ? 'Il link non funziona' : 'Un momento…'}
          </CardTitle>
          <CardDescription>{error ? null : 'Stiamo aprendo il tuo spazio.'}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <>
              <p className="text-destructive text-sm" role="alert">{error}</p>
              <Button asChild variant="outline" className="w-full">
                <a href={`${tenantPrefix}/app/login`}>Torna al login e chiedi un altro link</a>
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function EnterRoute() {
  const { t } = Route.useSearch()
  return <EnterPage token={t} />
}

export const Route = createFileRoute('/app/entra')({
  validateSearch: (search: Record<string, unknown>): { t: string } => ({
    t: typeof search.t === 'string' ? search.t : '',
  }),
  component: EnterRoute,
})
```

Il nome accessibile del link nel test è «Torna al login e chiedi un altro link»: il regex `/Torna al login/` lo copre. In `routes/app.tsx`: `const PUBLIC_ROUTES = new Set(['/app/login', '/app/registrati', '/app/entra'])`, e aggiornare il commento sopra (tre pagine senza sessione, non due). Il route tree si rigenera al `pnpm --filter web build`/`dev` (plugin TanStack); se `routeTree.gen.ts` è versionato, committarlo.

- [ ] **Step 8: Test, lint, build**

Run: `pnpm --filter web test && pnpm --filter web lint && pnpm --filter web build`
Expected: verde. Qualche test esistente che rende `LoginPage` o che cerca «Accedi» sulla pagina di login potrebbe dover cliccare prima «Accedi con la password»: cercare `getByRole('button', { name: 'Accedi' })` in `apps/web/src` e adeguare.

- [ ] **Step 9: Commit**

```bash
git add projects/pigrocrm/apps/web/src/lib/api-types.ts projects/pigrocrm/apps/web/src/lib/auth.tsx projects/pigrocrm/apps/web/src/routes/app/login.tsx projects/pigrocrm/apps/web/src/routes/app/login.test.tsx projects/pigrocrm/apps/web/src/routes/app/entra.tsx projects/pigrocrm/apps/web/src/routes/app/entra.test.tsx projects/pigrocrm/apps/web/src/routes/app.tsx
git commit -m "feat(web): the login asks for the email and mails a link; the password stays as a second way" -m "As in the community. /app/entra spends the link and lands on the home; a dead link says so and offers the login again. Nobody is asked for a password any more, and whoever has one still gets in with it.

ORB-172."
```

---

### Task 6: l'e2e clicca un bottone in più

**Files:**
- Modify: `apps/web/e2e/helpers.ts` (`login`)
- Modify: `apps/web/e2e/auth.spec.ts` (i due test che compilano la password)

- [ ] **Step 1: `helpers.ts`**

In `login(page, email, password)`, dopo `await page.goto('/app/login')`:

```ts
  // Since ORB-172 the login is email-first: the password form is the second way and
  // opens on this button. The e2e admin has a password, so this is its door.
  await page.getByRole('button', { name: /Accedi con la password/ }).click()
```

- [ ] **Step 2: `auth.spec.ts`**

La stessa riga nei due test che fanno `getByLabel('Password')` prima di compilare. Il primo test («an unauthenticated visitor is sent to the login page») non cambia.

- [ ] **Step 3: Eseguire l'e2e, se la porta 8000 è libera**

`lsof -i :8000` prima. Se libera: `pnpm --filter web test:e2e -- auth.spec.ts` (avvia Postgres su 55433, l'API su 8000, Vite su 5173; uccide chi tiene :8000 e :5173, quindi controllare prima). Se occupata da un'altra sessione, dirlo nella PR e lasciare l'e2e al `push` su `main`, che lo esegue.

- [ ] **Step 4: Commit**

```bash
git add projects/pigrocrm/apps/web/e2e/helpers.ts projects/pigrocrm/apps/web/e2e/auth.spec.ts
git commit -m "test(web): the e2e login opens the password form before filling it" -m "ORB-172."
```

---

### Task 7: decisione, piano, verifica completa, PR

- [ ] **Step 1: `docs/design/DECISIONS.md`**, una riga in coda (dopo quelle di `origin/main`, ORB-171 compresa se già dentro):

```markdown
| 2026-09-12 | The community enters with a link by mail; PigroCRM asked for a password of its own, had no mail sender and no way to recover a lost password. How does one enter PigroCRM? | With the email: `POST /api/auth/link` mails a link that lasts fifteen minutes and `POST /api/auth/entra` opens the session; Resend sends it, behind `pigrocrm.core.mail`, a copy of the hub's seam and not an import of it. The password form stays as a second way for the accounts that have one and is never asked of anybody again. The first link entry of a user revokes every refresh token issued before it (ORB-172, spec `projects/pigrocrm/docs/superpowers/specs/2026-09-12-onboarding-product-led-design.md` §6.2). | One identity per person, the email, on both products. An address is a claim until a link sent to it is used, and whatever was opened before that click dies with it. No password reset: the link is the recovery. |
```

- [ ] **Step 2: Il piano** è già in `docs/superpowers/plans/2026-09-12-orb-172-posta-e-login-via-link.md`; committare i due file:

```bash
git add docs/design/DECISIONS.md projects/pigrocrm/docs/superpowers/plans/2026-09-12-orb-172-posta-e-login-via-link.md
git commit -m "docs(pigrocrm): the decision on entering with the email, and the ORB-172 plan" -m "ORB-172."
```

- [ ] **Step 3: Verifica completa**, in serie: `uv run pytest -q -n 0 -m "not slow and not planner" projects/pigrocrm/packages/core/tests projects/pigrocrm/apps/api/tests projects/pigrocrm/apps/mcp/tests` (in background, 4-5 minuti), poi `uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy && pnpm --filter web lint && pnpm --filter web test && pnpm --filter web build`.

- [ ] **Step 4: Rebase, numero della migrazione, push, PR**

`git fetch origin && git rebase origin/main`; se `origin/main` ha una `0034`, rinumerare la propria in `0035` (nome del file, `revision`, `down_revision`) e ricontrollare `test_tenants.py -k provisioning`. Push del branch `ivansala/orb-172-pigrocrm-asks-for-a-password-the-community-never-gave-sends`. PR con titolo `feat(api): one enters PigroCRM with a link by mail, and the password stays as a second way`, corpo nelle quattro sezioni del template; in «Anything a reviewer should look at twice»: la revoca alla prima entrata, la scelta del 503 senza mittente, l'`_origin` che preferisce `PIGROCRM_PUBLIC_URL`; Screenshots: coppia prima/dopo della pagina di login (ricetta in `docs/pr-screenshots/README.md` e nella memoria: stack proprio su porte non 8000). Su Linear: `In Review` + commento con l'URL. Poi la revisione, il merge con merge commit, `Done` con l'evidenza, e la nota a Ivan che in produzione servono `PIGROCRM_RESEND_API_KEY` e, se non c'è, `PIGROCRM_PUBLIC_URL=https://pigro.joinorbiters.com` in `/opt/pigrocrm/.env`.
