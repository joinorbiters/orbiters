# Slice 9B — Credenziale Google Drive e durata dell'autenticazione: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un secondo consenso OAuth Google, separato da quello Gmail, con soli scope Drive (`drive.readonly` + `drive.file`), registrato in una riga propria con le cartelle radice scelte dal titolare; un trasporto Drive che accetta sia il service account di oggi sia un token utente; la sessione dell'app che dura sei mesi con rinnovo a ogni uso.

**Architecture:** `GoogleDriveAccount` è una tabella gemella di `google_accounts` con la stessa cifratura del refresh token; `GoogleDriveOAuthService` replica il flusso PKCE di `GmailOAuthService` con scope e callback propri e rifiuta un `sub` diverso dalla casella Gmail collegata. `gdrive.py` viene scomposto in `DriveTransport` (HTTP, retry, errori, URL) e un `TokenProvider` con due implementazioni: service account (codice esistente) e utente (`GoogleTokenClient.access_token` sul refresh token della riga Drive). `refresh_token_days` passa a 180: la rotazione a ogni `/api/auth/refresh` è già sliding.

**Tech Stack:** Python 3.13, SQLAlchemy 2 + Alembic, Pydantic 2, FastAPI, `mcp` 2.0, pytest + testcontainers, `fakes/fake_drive.py` e `fakes/fake_gmail.py` come trasporti finti, React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-04-slice-9-import-storico-e-google-drive-design.md` §4.1 (radici), §5 (credenziale), §5.6 (sei mesi).

## Global Constraints

- Test DB-backed: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest ...` dalla radice del worktree.
- Nessun `google-api-python-client`: solo `urllib.request` + `json`, come `gdrive.py` e `gmail/transport.py` (test di architettura del pacchetto core).
- **Nessuna scadenza imposta dal CRM a una credenziale Google** (§5.6): `consent_expires_at` si valorizza solo se `settings.google_app_unverified` è vero, esattamente come oggi per Gmail.
- Scope Drive richiesti, verbatim: `openid`, `email`, `https://www.googleapis.com/auth/drive.readonly`, `https://www.googleapis.com/auth/drive.file`. Nessun altro.
- Il refresh token Drive è sigillato con `seal(..., decode_google_token_key(settings))` e mai esposto da nessuno schema di lettura (`repr=False` dove serve, come `GoogleAccountRead`).
- Il grant Drive con `google_sub` diverso da quello di `google_accounts` dello stesso utente è un `Conflict` (§5.2). Se non esiste ancora un account Gmail, il controllo si applica quando quello arriva (modifica simmetrica in `GmailOAuthService.complete`).
- `refresh_token_days` default `180`, `access_token_minutes` resta `15`.
- Formattazione e lint prima di ogni commit; messaggi `feat(drive): ...`, `feat(auth): ...` con la riga `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Ruling (R10 non chiuso):** i PAT non hanno scope (il minimo di slice 5 §8.4 non è in albero). Finché non lo sono, le funzionalità Drive lato agente si gateano con `mcp_full_access` esattamente come `discover_gmail_correspondents`; il piano 9C lo applica. Qui non c'è nulla da gateare.

---

## File Structure

| File | Responsabilità |
|---|---|
| `packages/core/src/pigrocrm/core/config.py` | `refresh_token_days = 180` |
| `packages/core/migrations/versions/0026_google_drive_accounts.py` | Tabella `google_drive_accounts`; colonna `google_oauth_states.purpose` |
| `packages/core/src/pigrocrm/core/drive/__init__.py` | Nuovo pacchetto: il Drive non è Gmail e non va in `gmail/` |
| `packages/core/src/pigrocrm/core/drive/models.py` | `GoogleDriveAccount` |
| `packages/core/src/pigrocrm/core/drive/schemas.py` | Scope, `GoogleDriveAccountRead`, `DriveHealth`, `DriveRootsUpdate`, `DriveBannerReason` |
| `packages/core/src/pigrocrm/core/drive/repository.py` | `DriveRepository`: `account_for_user`, `add`, stati OAuth con `purpose="drive"` |
| `packages/core/src/pigrocrm/core/drive/oauth.py` | `GoogleDriveOAuthService.start/complete/disconnect` |
| `packages/core/src/pigrocrm/core/drive/account.py` | `GoogleDriveAccountService.health/usable/mark_revoked/set_roots` |
| `packages/core/src/pigrocrm/core/drive/transport.py` | `DriveTransport` (estratto da `storage/gdrive.py`) + `TokenProvider` protocol, `ServiceAccountTokens`, `UserTokens` |
| `packages/core/src/pigrocrm/core/storage/gdrive.py` | `GDriveStorage(transport: DriveTransport, root_folder_id)`; il costruttore attuale resta come classmethod `from_service_account(...)` |
| `packages/core/src/pigrocrm/core/gmail/oauth.py` | Controllo simmetrico del `sub` contro l'account Drive |
| `apps/api/src/pigrocrm_api/routers/drive.py` | `/api/drive/account`, `/oauth/start`, `/oauth/callback`, `DELETE /account`, `PATCH /account/roots` |
| `apps/mcp/src/pigrocrm_mcp/tools/drive.py` | `describe_drive_account` (sempre registrato quando Google è configurato) |
| `apps/web/src/features/drive/DrivePanel.tsx`, `apps/web/src/routes/app/impostazioni/drive.tsx` | Collega/Scollega Drive, radici, banner |
| `docs/superpowers/notes/2026-09-04-google-oauth-publish-runbook.md` | Pubblicazione del progetto OAuth (Internal) e `PIGROCRM_GOOGLE_APP_UNVERIFIED=false` |
| Test | `packages/core/tests/test_auth_session_ttl.py`, `packages/core/tests/test_drive_oauth.py`, `packages/core/tests/test_drive_transport.py`, `apps/api/tests/test_drive_api.py`, `apps/mcp/tests/test_drive_tools.py`, `apps/web/src/features/drive/DrivePanel.test.tsx` |

---

### Task 1: Sessione a sei mesi

**Files:**
- Modify: `packages/core/src/pigrocrm/core/config.py:27`
- Test: `packages/core/tests/test_auth_session_ttl.py` (nuovo)
- Modify: `.env.example` (riga `PIGROCRM_REFRESH_TOKEN_DAYS=180` con commento)

**Interfaces:** nessuna nuova; `RefreshTokenService.issue` legge `settings.refresh_token_days`.

- [ ] **Step 1: Test che fallisce**

```python
"""Spec 9 §5.6: the session lasts six months and every refresh renews it."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.auth.refresh_models import RefreshToken
from pigrocrm.core.auth.refresh_service import RefreshTokenService
from pigrocrm.core.auth.tokens import decode_token
from pigrocrm.core.config import Settings


def _settings() -> Settings:
    return Settings(_env_file=None, jwt_secret="x" * 32)  # type: ignore[call-arg]


def test_the_default_refresh_lifetime_is_one_hundred_and_eighty_days() -> None:
    assert _settings().refresh_token_days == 180
    assert _settings().access_token_minutes == 15


def test_a_refresh_issued_today_expires_in_six_months(db_session: Session, admin_user) -> None:  # noqa: ANN001
    settings = _settings()
    token = RefreshTokenService(db_session).issue(admin_user.id, settings)
    payload = decode_token(token, settings, expected_type="refresh")
    row = db_session.execute(select(RefreshToken).where(RefreshToken.jti == payload.jti)).scalar_one()
    assert timedelta(days=179, hours=23) < row.expires_at - datetime.now(UTC) <= timedelta(days=180)


def test_rotation_renews_the_window(db_session: Session, admin_user) -> None:  # noqa: ANN001
    """Consuming the old jti and issuing a new one is what `/api/auth/refresh` does:
    the new row's expiry is measured from now, so a user who refreshes on day 179
    gets another 180 days. Sliding, not fixed."""
    settings = _settings()
    service = RefreshTokenService(db_session)
    first = decode_token(service.issue(admin_user.id, settings), settings, expected_type="refresh")
    service.consume(first.jti, admin_user.id)
    second = decode_token(service.issue(admin_user.id, settings), settings, expected_type="refresh")
    rows = {r.jti: r for r in db_session.execute(select(RefreshToken).where(RefreshToken.user_id == admin_user.id)).scalars()}
    assert rows[first.jti].consumed_at is not None
    assert rows[second.jti].expires_at >= rows[first.jti].expires_at
```

Il fixture di un utente (`admin_user` o simile) va letto da `packages/core/tests/conftest.py`; se manca, creare un `User(email=..., password_hash="x", nome="Owner", ruolo="admin", attivo=True)` inline come fa `fakes/gmail_fixtures.py:connected_account`.

- [ ] **Step 2: Vederlo fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_auth_session_ttl.py -q`
Expected: FAIL — `assert 30 == 180`.

- [ ] **Step 3: Implementare**

`config.py:27` → `refresh_token_days: int = 180` con il commento:

```python
    # Six months, sliding: `/api/auth/refresh` consumes the old jti and issues a new row
    # whose expiry is measured from now, so anyone who uses the CRM never sees the login
    # again and anyone who leaves it for six months does (spec 9 §5.6). The access token
    # stays at fifteen minutes: that is the revocation window, not the session length.
```

`.env.example`: aggiungere `PIGROCRM_REFRESH_TOKEN_DAYS=180` con una riga di commento. Aggiornare `docs/superpowers/specs/2026-08-06-pigrocrm-core-crm-mcp-design.md` **solo** se cita esplicitamente «30 giorni» per il refresh (grep); in quel caso una riga «portato a 180 dallo slice 9 §5.6».

- [ ] **Step 4: Verde**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_auth_session_ttl.py packages/core/tests/test_auth*.py apps/api/tests/test_auth_api.py -q`
Expected: PASS. Se un test esistente asserisce `30`, aggiornarlo a `180` citando §5.6.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/config.py packages/core/tests/test_auth_session_ttl.py .env.example
git commit -m "feat(auth): the session lasts six months, renewed on every refresh (slice 9 §5.6)"
```

---

### Task 2: Modello, migrazione e schemi dell'account Drive

**Files:**
- Create: `packages/core/src/pigrocrm/core/drive/__init__.py`, `drive/models.py`, `drive/schemas.py`
- Create: `packages/core/migrations/versions/0026_google_drive_accounts.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/models.py` (`GoogleOAuthState.purpose`), `packages/core/src/pigrocrm/core/models_registry.py`
- Test: `packages/core/tests/test_drive_oauth.py` (nuovo, prima parte)

**Interfaces:**
- Produces:
  - `GoogleDriveAccount` (`__tablename__ = "google_drive_accounts"`): `user_id: UUID` (FK users, unique), `google_sub: str(255)`, `email_address: str(320)`, `refresh_token_ciphertext: bytes`, `refresh_token_nonce: bytes`, `scopes_granted: list[str]` (JSONB), `status: str(16)` in {`active`, `revoked`, `expired`, `disconnected`}, `consent_expires_at: datetime | None`, `root_folder_ids: list[str]` (JSONB, default `[]`), `storage_folder_id: str | None`, `last_error: str | None`, `last_error_at: datetime | None`, `connected_at: datetime`, `disconnected_at: datetime | None`. Mixin `PrimaryKeyMixin` + `TimestampMixin` come `GoogleAccount`.
  - `GoogleOAuthState.purpose: str(10)` default `"gmail"`, valori `gmail` | `drive`.
  - `drive/schemas.py`: `DRIVE_SCOPE_READONLY`, `DRIVE_SCOPE_FILE`, `DRIVE_REQUESTED_SCOPES = ("openid", "email", DRIVE_SCOPE_READONLY, DRIVE_SCOPE_FILE)`; `DriveStatus = Literal["active","revoked","expired","disconnected"]`; `GoogleDriveAccountRead` (stessi campi di `GoogleAccountRead` meno quelli Gmail, più `root_folder_ids`, `storage_folder_id`); `DriveBannerReason = Literal["revoked","expiring","expired","scope_missing"] | None`; `DriveHealth(account: GoogleDriveAccountRead | None, banner, banner_text, missing_scopes: list[str], configured: bool)`; `DriveRootsUpdate(root_folder_ids: list[SafeStr] (1..20, ciascuno `^[A-Za-z0-9_-]{10,128}$`), storage_folder_id: SafeStr | None (stessa regex))`.

- [ ] **Step 1: Test che fallisce**

```python
"""The Drive credential: a second grant, a second row, the same key (spec 9 §5)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.schemas import DRIVE_REQUESTED_SCOPES, DriveRootsUpdate, GoogleDriveAccountRead
from pigrocrm.core.gmail.models import GoogleOAuthState


def test_the_requested_scopes_are_exactly_the_four_of_the_spec() -> None:
    assert DRIVE_REQUESTED_SCOPES == (
        "openid",
        "email",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
    )


def test_a_drive_account_row_round_trips_and_hides_its_token(db_session: Session, admin_user) -> None:  # noqa: ANN001
    row = GoogleDriveAccount(
        user_id=admin_user.id, google_sub="sub-1", email_address="io@example.it",
        refresh_token_ciphertext=b"\x01", refresh_token_nonce=b"\x02",
        scopes_granted=list(DRIVE_REQUESTED_SCOPES), status="active",
        root_folder_ids=["1AbCdEfGhIjKlMnOpQ"], storage_folder_id=None,
    )
    db_session.add(row)
    db_session.flush()
    read = GoogleDriveAccountRead.model_validate(row)
    assert read.root_folder_ids == ["1AbCdEfGhIjKlMnOpQ"]
    assert "refresh_token" not in read.model_dump_json()


def test_an_oauth_state_knows_its_purpose(db_session: Session, admin_user) -> None:  # noqa: ANN001
    state = GoogleOAuthState(jti="j1", code_verifier="v" * 43, user_id=admin_user.id, expires_at=datetime.now(UTC))
    db_session.add(state)
    db_session.flush()
    assert state.purpose == "gmail"


def test_root_ids_are_drive_ids_not_free_text() -> None:
    DriveRootsUpdate(root_folder_ids=["1AbCdEfGhIjKlMnOpQ"])
    with pytest.raises(ValidationError):
        DriveRootsUpdate(root_folder_ids=["'x' in parents or name contains 'a'"])
    with pytest.raises(ValidationError):
        DriveRootsUpdate(root_folder_ids=[])
```

- [ ] **Step 2: Vederlo fallire** — `ModuleNotFoundError: pigrocrm.core.drive`.

- [ ] **Step 3: Implementare** modello (copiando la forma di `GoogleAccount`, cifratura e commenti sul perché di ogni colonna), schemi, colonna `purpose` su `GoogleOAuthState`, migrazione 0026 (`create_table google_drive_accounts` con unique su `user_id`, check su `status`; `add_column google_oauth_states.purpose String(10) NOT NULL server_default 'gmail'`), registrazione in `models_registry.py`.

- [ ] **Step 4: Verde** — `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_drive_oauth.py packages/core/tests/test_gmail_oauth*.py -q`.

- [ ] **Step 5: Commit** — `feat(drive): google_drive_accounts model, schemas and the oauth state purpose`.

---

### Task 3: `GoogleDriveOAuthService`

**Files:**
- Create: `packages/core/src/pigrocrm/core/drive/repository.py`, `drive/oauth.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/oauth.py` (`complete`: controllo `sub` contro l'account Drive), `packages/core/src/pigrocrm/core/gmail/repository.py` (`add_state` accetta `purpose`, `consume_state(jti, now, purpose)`)
- Test: `packages/core/tests/test_drive_oauth.py` (append)

**Interfaces:**
- Consumes: `GoogleTokenClient.exchange_code(code, code_verifier, redirect_uri) -> TokenGrant(subject, email_address, refresh_token, scopes)`, `seal`, `decode_google_token_key`, `GoogleOAuthState`, `ActivityService.record`.
- Produces: `GoogleDriveOAuthService(session, *, settings, tokens)` con `redirect_uri -> f"{settings.public_url}/api/drive/oauth/callback"`, `start(actor) -> str` (URL con `scope=" ".join(DRIVE_REQUESTED_SCOPES)`, `access_type=offline`, `prompt=consent`, PKCE S256, stato con `purpose="drive"`), `complete(*, code, state, actor) -> GoogleDriveAccountRead`, `disconnect(actor) -> None` (status `disconnected`, `disconnected_at`, refresh token sostituito da byte vuoti come fa Gmail se lo fa; altrimenti lasciato sigillato — seguire `GmailOAuthService.disconnect`). `DriveRepository(session)`: `account_for_user(user_id) -> GoogleDriveAccount | None`, `add(account)`.
- Regole: `complete` rifiuta uno stato con `purpose != "drive"`; rifiuta un grant senza `subject`/`email`; rifiuta (`Conflict`) un `subject` diverso da `google_accounts.google_sub` dello stesso utente quando quell'account esiste ed è collegato; simmetricamente `GmailOAuthService.complete` rifiuta un `subject` diverso da un account Drive collegato. `consent_expires_at` come Gmail (solo se `google_app_unverified`). Attività `drive.account_collegato` / `drive.account_scollegato` su entity `google_drive_account`.

- [ ] **Step 1: Test che fallisce** — usando `FakeGmail` (il suo endpoint token serve anche a Drive: `exchange_code` e `access_token` sono gli stessi URL) e `gmail_settings()` di `fakes/gmail_fixtures.py`:

```python
def test_start_asks_google_for_drive_scopes_only_with_pkce(db_session: Session, admin_user) -> None:  # noqa: ANN001
    from urllib.parse import parse_qs, urlparse

    from fakes.gmail_fixtures import gmail_settings
    from pigrocrm.core.actor import Actor
    from pigrocrm.core.drive.oauth import GoogleDriveOAuthService
    from pigrocrm.core.gmail.tokens import GoogleTokenClient
    from pigrocrm.core.gmail.transport import GmailTransport

    settings = gmail_settings()
    transport = GmailTransport(http=FakeGmail(), sleep=lambda _: None)
    service = GoogleDriveOAuthService(db_session, settings=settings, tokens=GoogleTokenClient(client_id=settings.google_client_id, client_secret=settings.google_client_secret, transport=transport))
    url = service.start(Actor(id=admin_user.id, type="user", role="admin"))
    q = parse_qs(urlparse(url).query)
    assert q["scope"] == [" ".join(DRIVE_REQUESTED_SCOPES)]
    assert q["redirect_uri"][0].endswith("/api/drive/oauth/callback")
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    state = db_session.execute(select(GoogleOAuthState).where(GoogleOAuthState.jti == q["state"][0])).scalar_one()
    assert state.purpose == "drive"


def test_complete_stores_a_sealed_token_and_refuses_a_foreign_sub(db_session: Session, admin_user) -> None:  # noqa: ANN001
    """The Gmail account of this user is `sub-gmail`; a Drive grant for another Google
    identity is refused, a grant for the same identity is stored, sealed, with no
    CRM-imposed expiry."""
    ...  # build the Gmail account with fakes.gmail_fixtures.connected_account (google_sub="sub-gmail"),
         # configure FakeGmail(id_token=<JWT-like payload with sub/email>, granted_scopes=DRIVE_REQUESTED_SCOPES),
         # call start(), read the state jti, call complete(code="c", state=jti) and assert:
         # - Conflict when the fake's id_token carries sub="sub-other"
         # - success when sub="sub-gmail": row.status == "active", row.consent_expires_at is None,
         #   unseal(row.refresh_token_ciphertext, row.refresh_token_nonce, key) == fake.refresh_token,
         #   activity "drive.account_collegato" written
```

Leggere in `packages/core/tests/test_gmail_oauth.py` come viene costruito l'`id_token` finto e come si legge il `jti` dallo `state`, e replicarlo letteralmente: quel test è il modello di questo. Aggiungere il test simmetrico: con un account Drive `sub-drive` collegato, `GmailOAuthService.complete` con `sub-other` è `Conflict`.

- [ ] **Step 2: Vederlo fallire** — `ModuleNotFoundError: pigrocrm.core.drive.oauth`.

- [ ] **Step 3: Implementare** copiando la struttura di `GmailOAuthService` (start/complete/_store/_invalid_authorisation) con i nomi Drive; `consume_state` prende `purpose` e restituisce `None` se non coincide; il controllo incrociato del `sub` in entrambi i servizi legge l'altra tabella via repository. Messaggi in italiano: «questo Drive appartiene a un account Google diverso dalla casella collegata ({email}): usa lo stesso account».

- [ ] **Step 4: Verde** — `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_drive_oauth.py packages/core/tests/test_gmail_oauth*.py -q`.

- [ ] **Step 5: Commit** — `feat(drive): a separate OAuth grant for Drive, same Google identity as the mailbox (slice 9 §5.1-5.2)`.

---

### Task 4: `GoogleDriveAccountService` — health, usable, radici

**Files:**
- Create: `packages/core/src/pigrocrm/core/drive/account.py`
- Test: `packages/core/tests/test_drive_oauth.py` (append)

**Interfaces:**
- Produces: `GoogleDriveAccountService(session, *, settings)`: `health(actor) -> DriveHealth` (stessa scala di attuabilità di `GoogleAccountService.health`: revoked > disconnected > expired > expiring (48h) > scope_missing su `drive.readonly`); `usable(actor, *, scope, feature) -> GoogleDriveAccount` (solleva `CredentialRevoked`/`ConsentExpired` di `gmail/errors.py` riusati, o `Conflict` «Drive non collegato»); `mark_revoked(account, actor, reason)`; `set_roots(data: DriveRootsUpdate, actor) -> GoogleDriveAccountRead` (`require_write("impostare le cartelle Drive")`, attività `drive.radici_impostate`).
- Testi banner in italiano, modellati su `_REVOKED_TEXT`/`_EXPIRED_TEXT` di `gmail/account.py` con «Impostazioni → Drive».

- [ ] **Step 1: Test che fallisce** — health senza account → `account None, banner None, configured True`; account `revoked` → banner `revoked`; `consent_expires_at` fra 24h → `expiring`; scope mancante `drive.readonly` → `scope_missing`; `set_roots` persiste e scrive l'attività; `usable(scope=DRIVE_SCOPE_READONLY)` su account senza quello scope → errore che nomina lo scope.

- [ ] **Step 2–4:** fallisce per import mancante; implementare; verde.

- [ ] **Step 5: Commit** — `feat(drive): account health, the usable gate and the configured roots (slice 9 §4.1, §5.5)`.

---

### Task 5: `DriveTransport` e i fornitori di token

**Files:**
- Create: `packages/core/src/pigrocrm/core/drive/transport.py`
- Modify: `packages/core/src/pigrocrm/core/storage/gdrive.py`, `packages/core/src/pigrocrm/core/storage/factory.py`
- Test: `packages/core/tests/test_drive_transport.py` (nuovo); i test esistenti di `gdrive` (`packages/core/tests/test_gdrive*.py`) devono restare verdi **senza modifiche** salvo il costruttore.

**Interfaces:**
- Produces:
  - `class TokenProvider(Protocol): def access_token(self) -> str: ...; def forget(self) -> None: ...`
  - `ServiceAccountTokens(service_account_json: str, *, http, sign_assertion, sleep)` — il codice di `_access_token`/`_sign_with_private_key` di oggi, spostato.
  - `UserTokens(account_id: UUID, email_address: str, refresh_token: str, tokens: GoogleTokenClient)` — `access_token()` delega a `GoogleTokenClient.access_token(account_id=..., email_address=..., refresh_token=...)`.
  - `DriveTransport(*, tokens: TokenProvider, http: HttpCall | None = None, sleep: SleepFn | None = None)` con `json(method, url, *, body: bytes | None = None, content_type: str | None = None, what: str) -> dict[str, Any]` e `bytes(method, url, *, what) -> bytes`: `_call` con retry, `Authorization: Bearer`, `_decode` degli errori — tutto il codice HTTP di `gdrive.py`, senza la logica di cartelle/chiavi.
  - `GDriveStorage(*, transport: DriveTransport, root_folder_id: str)` e `GDriveStorage.from_service_account(*, service_account_json, root_folder_id, http=None, sign_assertion=None, sleep=None)` che costruisce `ServiceAccountTokens` + `DriveTransport` (usato da `factory.py`, invariato per chi ha il service account).
  - `factory.storage_from_settings(settings, session=None)`: se `storage_backend == "gdrive"` e **non** c'è `gdrive_service_account_json`, costruisce `UserTokens` dall'account Drive del titolare (`DriveRepository(session).account_for_user(...)` dell'unico admin con account collegato) con `storage_folder_id` come root; se nessuno dei due è configurato, errore di configurazione con il testo attuale esteso («…oppure collega Drive da Impostazioni e scegli la cartella di scrittura»).

- [ ] **Step 1: Test che fallisce** — con `fakes/fake_drive.py`: `DriveTransport(tokens=<stub che restituisce "tok">)` mette `Bearer tok` su ogni chiamata registrata dal fake; un `429` poi `200` viene ritentato una volta; `UserTokens` chiama `GoogleTokenClient.access_token` (con `FakeGmail` come token endpoint) e mette in cache; `GDriveStorage.from_service_account(...)` supera gli stessi `put/get/delete` dei test esistenti.

- [ ] **Step 2–4:** fallisce per import; refactor **senza cambiare comportamento** (spostare, non riscrivere: i docstring di `gdrive.py` viaggiano con il codice); verde su `test_drive_transport.py` + `test_gdrive*.py` + `test_storage*.py`.

- [ ] **Step 5: Commit** — `refactor(drive): DriveTransport with pluggable token providers; GDriveStorage keeps its service-account path`.

---

### Task 6: REST `/api/drive`

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/drive.py`
- Test: `apps/api/tests/test_drive_api.py`

**Interfaces:**
- `GET /api/drive/account -> DriveHealth` (200 anche senza Google configurato, `configured=False`, come `/api/gmail/account`); `GET /api/drive/oauth/start -> 307` verso Google; `GET /api/drive/oauth/callback -> 307` verso `/app/impostazioni/drive?esito=collegato|negato|errore`; `DELETE /api/drive/account -> 204`; `PATCH /api/drive/account/roots` (body `DriveRootsUpdate`) `-> GoogleDriveAccountRead`.
- Il router viene incluso da `main.py` automaticamente se quel file itera i moduli di `routers/` (verificare `main.py:89`); altrimenti aggiungerlo esplicitamente.

- [ ] **Step 1: Test che fallisce** — `GET /api/drive/account` con settings senza Google → `configured False`; `oauth/start` con Google configurato → 307 e `Location` contiene `drive.readonly`; `PATCH roots` senza account → 409; `PATCH roots` con account (inserito via `api_session`) → 200 e `root_folder_ids` aggiornati; collaboratore su `PATCH roots` → 403.

- [ ] **Step 2–4:** 404 → implementare copiando `routers/gmail.py` (`_oauth`, `_back_to_settings`, `_SETTINGS_PAGE = "/app/impostazioni/drive"`) → verde.

- [ ] **Step 5: Commit** — `feat(api): /api/drive — account health, OAuth start/callback, roots`.

---

### Task 7: `describe_drive_account` su MCP

**Files:**
- Create: `apps/mcp/src/pigrocrm_mcp/tools/drive.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/server.py` (registrazione dentro `if gmail_configured(resolved_settings):`, subito dopo `gmail_tools.register`)
- Modify: `apps/mcp/tests/test_gmail_tools.py` (`SLICE_5B_TOOLS` → l'insieme dei tool Google diventa sei: aggiungere `describe_drive_account` con un commento che rimanda allo slice 9), `apps/mcp/tests/test_mcp_surface_coverage.py` (esclusioni per `GoogleDriveOAuthService.start/complete/disconnect`, `GoogleDriveAccountService.usable/mark_revoked/set_roots` con le stesse ragioni delle omologhe Gmail)
- Test: `apps/mcp/tests/test_drive_tools.py`

**Interfaces:**
- `describe_drive_account() -> dict` = `DriveHealth.model_dump(mode="json")`. Nessun parametro. Sempre registrato quando Google è configurato (diagnosi, non spesa di quota).

- [ ] **Step 1: Test che fallisce** — presente con `gmail_settings()`, assente senza Google; risposta con `banner` e `configured`; nessuna richiesta HTTP verso Google (il socket guard del repo lo garantisce).

- [ ] **Step 2–4:** implementare; verde su `test_drive_tools.py`, `test_gmail_tools.py`, `test_mcp_surface_coverage.py`, `test_mcp_invoice_ban.py`.

- [ ] **Step 5: Commit** — `feat(mcp): describe_drive_account`.

---

### Task 8: Pannello Impostazioni → Drive

**Files:**
- Create: `apps/web/src/features/drive/DrivePanel.tsx`, `apps/web/src/features/drive/queries.ts`, `apps/web/src/routes/app/impostazioni/drive.tsx`
- Modify: `apps/web/src/lib/api-types.ts` (rigenerato), il menu di Impostazioni dove è linkato `impostazioni/gmail`
- Test: `apps/web/src/features/drive/DrivePanel.test.tsx`

**Interfaces:** consuma `GET/DELETE /api/drive/account`, `PATCH /api/drive/account/roots`, link `/api/drive/oauth/start`.

- [ ] **Step 1: Test che fallisce** — modellato su `GmailPanel.test.tsx`: senza account mostra «Collega Google Drive» come link a `/api/drive/oauth/start`; con account mostra email, stato, elenco radici editabile (id cartella + nome libero solo come etichetta locale), pulsante «Scollega Drive»; con `banner_text` mostra il banner e non il form.

- [ ] **Step 2–4:** implementare seguendo `GmailPanel.tsx` (stessi componenti UI); `npm run generate:api` con API in esecuzione; `npx vitest run src/features/drive && npm run lint && npx tsc --noEmit`.

- [ ] **Step 5: Commit** — `feat(web): Impostazioni → Drive panel`.

---

### Task 9: Runbook di pubblicazione OAuth

**Files:**
- Create: `docs/superpowers/notes/2026-09-04-google-oauth-publish-runbook.md`

Contenuto: passi nella Google Cloud Console per il progetto OAuth esistente — tipo utente **Internal** (Workspace humancraft.tech), stato **In produzione**, scope dichiarati (i quattro Gmail + i due Drive), redirect URI `…/api/gmail/oauth/callback` e `…/api/drive/oauth/callback`; poi `PIGROCRM_GOOGLE_APP_UNVERIFIED=false` e `PIGROCRM_REFRESH_TOKEN_DAYS=180` in `.env`, restart dell'API, riconnessione della casella una volta (il vecchio consenso in Testing scade comunque). Verifica: `describe_gmail_account` con `consent_expires_at: null` e nessun banner. Nessun codice.

- [ ] **Step 1: Scrivere e committare** — `docs: runbook to publish the Google OAuth project (Internal) so consents stop expiring`.

---

## Self-review

- §5.1 scope e consenso separato → T2, T3. §5.2 modello dati e controllo `sub` → T2, T3. §5.4 trasporto e fornitori di token → T5. §5.5 diagnosi → T4, T7. §5.6 sei mesi → T1, T9. §4.1 radici → T2 (`DriveRootsUpdate`), T4 (`set_roots`), T6, T8. §5.3 scope PAT → **ruling** nei Global Constraints (R10 non in albero: gating con `mcp_full_access` in 9C).
- Nomi coerenti fra i task: `GoogleDriveAccount`, `GoogleDriveAccountRead`, `DriveHealth`, `DriveRootsUpdate`, `DRIVE_REQUESTED_SCOPES`, `DRIVE_SCOPE_READONLY`, `DRIVE_SCOPE_FILE`, `GoogleDriveOAuthService`, `GoogleDriveAccountService`, `DriveRepository`, `DriveTransport`, `TokenProvider`, `ServiceAccountTokens`, `UserTokens`, `GDriveStorage.from_service_account`.
- Da verificare sul codice nei task (esplicitato): forma dell'`id_token` finto in `test_gmail_oauth.py`, presenza di `admin_user` in conftest core, iterazione dei router in `main.py`, cosa fa `disconnect` di Gmail con il token sigillato.
