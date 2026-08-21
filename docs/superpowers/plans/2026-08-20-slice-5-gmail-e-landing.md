# PigroCRM Slice 5 — Gmail e landing page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the public landing page that Google's restricted-scope verification requires, then the Gmail integration it unblocks — OAuth with an encrypted refresh token, a sync that only ever asks Gmail about addresses the CRM already knows, and a send path whose unknown outcomes are reconciled by lookup instead of guessed at.

**Architecture:** Three sub-plans in one document, in dependency order. **5A** is a framework-free static site (`apps/web/landing/`) built by its own Vite config, sharing exactly one source of colour and one woff2 with the app; it moves the SPA under `/app/` so `/` can belong to the landing. **5B-1** adds `packages/core/src/pigrocrm/core/gmail/` — an injectable HTTP seam shaped exactly like slice 2's `gdrive.py`, a `google_accounts` row per user with the refresh token encrypted at rest, and a sync whose every `users.messages.list` carries a `q` built from the CRM's own address roster. **5B-2** adds a durable `email_drafts` row that carries our own `Message-ID` before Gmail is ever called, so a send with an unknown outcome is resolved by `rfc822msgid:` lookup rather than by retrying. FastAPI routers and MCP tools call the same services in-process, and the send path is deliberately absent from the MCP surface.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · psycopg 3 · PostgreSQL 17 · MCP SDK v2 · pytest + testcontainers · `urllib.request` (no Google client library) · `cryptography` (AES-GCM, already present via `pyjwt[crypto]`) · Vite · React 19 · TanStack Router/Query/Table · Tailwind v4 · Playwright · axe-core · nginx

**Spec:** `docs/superpowers/specs/2026-08-20-slice-5-gmail-e-landing-design.md` — it governs. Supporting: `docs/superpowers/specs/2026-08-06-pigrocrm-core-crm-mcp-design.md` §10.3 (design system), `docs/superpowers/specs/2026-08-07-slice-1a-residui.md` (the blocking PAT prerequisite), `docs/superpowers/specs/2026-08-06-slice-1b-residui.md`.

---

## Sub-plan order, and why it is not the intuitive one

| Sub-plan | Content | Tasks | Cannot start until |
|---|---|---|---|
| **5A — Landing** | Spec §9, and the first three rows of §10 | 8 | **Nothing.** Unblocked today |
| **5B-1 — OAuth and sync** | Spec §4, §5, §8.1, §8.3 (read half), the Email tab, the `customers.email` index | 17 | 5A **deployed and publicly reachable**, Google verification submitted, **and** the PAT prerequisite below |
| **5B-2 — Send and reminders** | Spec §6, §7, the composer, the solleciti page | 12 | 5B-1 merged. The §7 half additionally needs slice 3 (invoices), which is **not in the tree** |

**5A ships first, and it is not a matter of taste.** Google does not grant the restricted Gmail scopes — `gmail.readonly` and `gmail.send` are both restricted — to an OAuth client that has no public homepage and no public privacy policy. The consent screen displays both URLs, and the verification review checks that they exist, sit on a verified domain, and describe what the application does with the data. Until those pages are live, the client stays in **Testing**, and in Testing **a consumer Google account's refresh token expires every 7 days**. So the landing is not Gmail's shop window; it is Gmail's technical precondition, and building Gmail first would mean building something that breaks every Wednesday by construction.

The dependency runs one way only. The landing needs nothing from Gmail: not a table, not a service, not a line of code.

Verification is calendar time, not work time. Submit it the day 5A is deployed, and build 5B-1 while it runs.

---

## The blocking prerequisite outside this slice

**5B-1 must not start until the minimum cut of residui 1A **R10** and **R5** is closed.** This plan does not contain that fix and must not be read as containing it.

Today (`docs/superpowers/specs/2026-08-07-slice-1a-residui.md`, R10 and R5, and its update of 2026-08-20): a personal access token has **no scopes**, **inherits the full role of its owner**, **never expires**, and **leaves no audit trail** on creation or revocation. "Give Claude a token" currently means "give Claude your account, forever, untraceably".

Gmail makes that materially worse, because it adds a **third-party** credential on a real person's mailbox. A token minted so an agent could read deals would, unchanged, read the correspondence — and nothing anywhere would record that it had.

The minimum cut, exactly as the residui update states it:

1. PATs carry a set of **scopes**, and the `gmail:*` scopes are **off by default** — they must be selected explicitly at creation.
2. PATs carry an `expires_at`, **mandatory** for any token carrying a `gmail:*` scope (default 90 days). The asymmetry is the point: the credential that opens the mailbox is the one for which an expiry is worth the friction.
3. Creating and revoking a PAT each write an `activities` row. This closes R5 for the token family, which is the family it was reported for.

That is not the full solution to R10 — scopes and expiry for *every* token remain open — and this plan does not plan it. Task B1-14 **consumes** the resulting `gmail:read` scope check; if that scope does not exist when B1-14 is reached, stop and close the prerequisite first rather than inventing a local substitute.

---

## Global Constraints

These apply to **every** task in all three sub-plans. They are not repeated per task. Everything from `## Global Constraints` in `2026-08-06-slice-1a-backend.md`, `2026-08-06-slice-1b-frontend.md` and `2026-08-10-slice-2-documenti-e-template.md` that still applies is carried here with its exact values.

### Carried from plan 1A (backend)

- **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Managed by **uv workspaces**. Do not use pip, poetry, or venv directly.
- **`packages/core` must never import from `apps.`** — enforced by `packages/core/tests/test_architecture.py`. That test is an *allowlist*: core may import the stdlib, the `pigrocrm` namespace, and only what `packages/core/pyproject.toml` declares under `[project].dependencies`. If a task seems to require anything else, either declare the dependency there or the design is wrong; stop and flag it.
- **Services receive and return Pydantic models only.** No `Request`, `Response`, `HTTPException`, or status codes inside `packages/core`.
- **Every service method that writes takes `actor: Actor`** as an explicit parameter. Never read the actor from global or contextual state.
- **One service method = one transaction. The service commits; repositories never commit.**
- **Money is `Numeric(12, 2)`; hours are `Numeric(8, 2)`.** Never `Float` for either.
- **All timestamps are `TIMESTAMP WITH TIME ZONE` in UTC.** Use `from datetime import UTC, datetime` → `datetime.now(UTC)`, matching `db/base.py`. Never `datetime.utcnow()`.
- **All primary keys are UUIDv7** via the shared `pigrocrm.core.db.base.uuid7` wrapper, stored as native `UUID`. Never `uuid_utils` directly in a model.
- **Soft delete**: entities carry `deleted_at`. Repository queries filter `deleted_at IS NULL` unless explicitly asked otherwise. No physical delete exists anywhere in this slice either.
- **Tests use real PostgreSQL via testcontainers. Never SQLite** — JSONB and GIN indexes do not exist there. Use the existing `db_engine`/`db_session` fixtures in `packages/core/tests/conftest.py`.
- **TDD is mandatory for `packages/core`.** Write the failing test, watch it fail, then implement.
- **Commit after every task**, using the message given in the task's final step.
- **UI language is Italian.** Field labels, buttons, and error messages shown to users are Italian. Code identifiers, table names and column names are English except the Italian fiscal and domain terms already fixed in slices 1 and 2 (`partita_iva`, `codice_fiscale`, `codice_sdi`, `pec`, `ragione_sociale`, `indirizzo`, `cap`, `comune`, `provincia`, `nazione`, `tipo`, `titolo`, `stato`, `versione_corrente`, `numero`, `sorgente_markdown`, `variabili`, `variabili_dichiarate`, `corpo_markdown`, `attivo`, `creato_da`, `dimensione`) and the ones this slice fixes (`sollecito`, `firma_email`, `send_state` values `bozza`/`in_invio`/`inviato`/`incerto`/`fallito`).
- **The `Expected: PASS (N passed)` counts are indicative, not contractual.** Parametrised tests expand to different totals than the number of test functions. What matters is that every test passes and none is skipped — a differing total is not a failure and must not be "fixed" by deleting or merging cases.
- **A uniqueness pre-check never replaces the database constraint.** Wherever a service does "SELECT to check, then INSERT", it must also catch `sqlalchemy.exc.IntegrityError` around the commit, `session.rollback()`, and re-raise the domain `Conflict`. Two concurrent requests both pass the SELECT; only the constraint stops the second, and without the rollback the caller's session is left poisoned (`PendingRollbackError` on its next statement).
- **Case-insensitive uniqueness needs a functional index, not a convention.** Where identity is case-insensitive (email addresses in this slice), declare `Index("uq_…", func.lower(col), unique=True)` in `__table_args__`.
- **A method named `list` must be the LAST method in its class.** `def list(...)` rebinds `list` in the class namespace, so any later method annotated `-> list[Something]` resolves it to that method and raises `TypeError: 'function' object is not subscriptable` **at import time**. Python 3.13 evaluates annotations eagerly, so this is a hard failure here; 3.14's PEP 649 would hide it. Calling `self.list()` from an earlier method is fine — that is a call-time attribute lookup, not an annotation. The rule is unconditional: do not reason about whether a later method *currently* returns a `list[...]`. `packages/core/tests/test_module_imports.py` is the real guard; keep it green.
- **Every `Numeric(p, s)` column needs a matching Pydantic `Field(max_digits=p, decimal_places=s)`** on both schemas. Without it a value beyond the column's capacity reaches Postgres as `NumericValueOutOfRange` — an uncaught `DataError`, poisoned session — and a sub-scale value like `Decimal("0.005")` is silently rounded by the database while the returned object still shows the original. Reject rather than round.
- **Every `String(n)` column needs a matching Pydantic `max_length=n`** on both the Create and the Update schema. Without it an over-long value reaches Postgres, raises `sqlalchemy.exc.DataError` — **not** an `IntegrityError` subclass, so no existing handler catches it — and poisons the caller's session.
- **`re.fullmatch`, never `re.match` with `$`.** Python's `$` matches before a trailing newline, so `^\d{11}$` accepts a 12-character string and the value still reaches the database. **This applies to every regex in this slice, database-bound or not** — the RFC822 header patterns, the `Message-ID` pattern, the storage-key patterns, the landing's CSS-parsing tests. The habit is what protects the ones that are.
- **Every `Integer` column needs a bounded Pydantic field** (`Field(ge=..., le=...)`) on both schemas, picked to be defensible for that field's meaning. Without a bound a value like `2**40` reaches Postgres raw as `IntegerOutOfRange`. **Exception, not violation**: a field already fully bounded by an equivalent service-level range check does not also need a schema-level bound — adding one changes which exception type fires (`pydantic.ValidationError` instead of this project's own `ValidationFailed`) for a same-shaped value the service already rejects correctly. Document any omission in a comment.
- **A NUL byte (`"\x00"`) in a native `String`/`Text` field is rejected, not stored.** Use `pigrocrm.core.validation.SafeStr` on every user-supplied string field on every Create/Update schema, including inside `list[str]` fields. Reject, never strip. A field that structurally cannot carry a NUL byte through (one slugified through a regex first) does not need `SafeStr` layered on top — document why rather than adding a check that can be shown never to fire.
- **Every foreign key column is validated against the table it references, in both `create` and `update`**, including an optional (nullable) one — a nullable FK is skipped only when the caller supplies nothing, never when the caller supplies a value. Without this any syntactically valid UUID reaches `flush()`/`commit()` and comes back as a raw `IntegrityError` (`ForeignKeyViolation`) instead of this project's own `NotFound`.
- **Escape LIKE metacharacters in every search filter.** Use the shared `pigrocrm.core.db.escape_like` helper, escape `\`, `%` and `_` (backslash first), and pass `escape="\\"`.
- **Pagination `limit` must be bounded** — `Field(ge=1, le=200)` on the query schema, not only on the router.

### Carried from plan 1B (frontend)

- **No `fetch` inside components.** Every request goes through the generated client wrapped in TanStack Query hooks. *(5A is exempt: it is not a React application and makes no requests at all — see the 5A-specific constraints.)*
- **The API client is generated, never handwritten.** `openapi-typescript` reads `openapi.json` from the running API (`pnpm generate:api`). A contract change must break `tsc`, not production.
- **No business logic in the frontend. Validation lives in the backend.** Validation messages come from the API's problem documents. Recomputing a rule client-side is how the three interfaces start disagreeing — the exact defect inherited from Acme, where the fiscal maths lived in `App.jsx`.
- **No component file over ~250 lines.** If a file approaches the limit, extract.
- **UI language is Italian.** Every visible label, button and message.
- **TypeScript strict mode**, no `any`, no `@ts-ignore`.
- **Form state keeps `{native, custom}` as two namespaces, decided once at seed time and never re-derived at submit.** Provenance is structural. A native column clears on `""` and only on `""`; a custom field clears on `null` and only on `null`; an omitted key clears nothing. **`0` and `false` are values, never blanks** — mirror `is_blank` exactly. Never sum money as a JS float; format `Numeric` values as the strings the API sends.
- **`DynamicForm` takes a required, undefaulted `mode: 'create' | 'edit'` prop.** Every new call site answers the question explicitly.
- **A failed request must never look like an empty result.** A query in `isError` renders `QueryErrorBanner`, never an empty table or an empty list.
- **`DataTable` is TanStack Table v9** (`@tanstack/react-table 9.0.0`). Do not import v8 APIs.
- **A hook must never be called with an empty id.** Make the row conditional, or give the hook a discriminated argument with no "empty string" spelling to get wrong, and ship a test for it (residuo B1).
- **Commit after every task.**

### Carried from plan 2

- **No user input ever reaches a command line.** `subprocess.run` is always called with an argument *list*, never a string, never `shell=True`. This slice adds no new subprocess call; the constraint stands so that no task introduces one.
- **Escaping is decided by context, never by a single pass.** No function may escape a value without being told which context it is escaping for. In this slice the contexts are `"markdown"`, `"typst"`, `"url"` (existing, `templates/escaping.py`) plus the two this slice adds, `"rfc822-header"` and `"quoted-printable"` (Task B2-2). A `str.replace` over a whole rendered document is the defect slice 2 exists to prevent, and an unescaped newline injected into an RFC822 header is the same defect with a worse blast radius.
- **`content_type` is chosen from a fixed allowlist, never echoed from the request.** `ALLOWED_CONTENT_TYPES` in `documents/schemas.py` is the authority. An attachment's MIME type in this slice comes from there, never from Gmail and never from a caller.
- **No new Python dependency is added to `packages/core`.** The Gmail client is `urllib.request` + `json` from the stdlib, exactly as `storage/gdrive.py` is. AES-GCM comes from `cryptography`, already in the tree via `pyjwt[crypto]` — declare it explicitly in `packages/core/pyproject.toml` rather than relying on a transitive edge (Task B1-3).

### New to slice 5 — secrets

- **No secret, token or key may be logged, or appear in an exception message, a problem document, an `activities` payload, or a `__repr__`.** That covers the Google client secret, the refresh token in either form (ciphertext included), every access token, `PIGROCRM_GOOGLE_TOKEN_KEY`, and the PKCE `code_verifier`. `google_accounts.last_error` holds the sentence the *user* reads, never the upstream body. Task B1-4 ships the test that greps the raised exception's `str()` for the fixture token value.
- **An access token is never persisted.** It lives in an in-process cache bounded by the `expires_in` Google returned, and dies with the process. Persisting it would add a second secret to protect for no gain — the same decision `gdrive.py` already made.

### New to slice 5 — no test may touch the network

- **No test in this slice may perform a network call.** The seam is at the **HTTP boundary**, not at the service boundary: `GmailTransport` is the injected callable, and `FakeGmail` replaces the *transport*, so URL construction, `q` construction, RFC822 assembly and error classification all really run in the tests. That is the whole point — those are precisely the parts Acme got wrong, in code no test ever executed.
- **The fake returns the real API's error shapes**, not invented ones. It must be able to produce, at minimum: a `401` with Google's `{"error": {"code": 401, "status": "UNAUTHENTICATED", ...}}` body; a `429` with a `Retry-After` header; a token-endpoint `400` with `{"error": "invalid_grant", ...}`; a `403` `rateLimitExceeded`; a socket timeout; and a `200` with a truncated body.
- **A suite that skips when credentials are absent proves nothing.** No test may be decorated with `skipif` on the presence of `PIGROCRM_GOOGLE_CLIENT_ID`, a network check, or a fixture file of real tokens. `packages/core/tests/test_no_network.py` (Task B1-4) fails the suite if any test in the slice opens a socket.

### New to slice 5 — the landing (5A only)

- **The landing carries no framework.** No React, no TanStack Router, no TanStack Query, no Radix, no dnd-kit. Three HTML files, one CSS file, one script of roughly a kilobyte.
- **`apps/web/src/styles/tokens.css` stays the single source of colour. The landing extends it and must not fork it.** No `--landing-*` value may contain a raw hexadecimal: every one is a `var(--color-…)` or a `color-mix()` of one, and the build injects the palette out of `tokens.css` itself rather than restating it. Enforced mechanically in Task A1, not by convention.
- **The contrast problem solved in the app must stay solved.** `#ed254e` / `--color-watermelon` may never be a solid fill under white text; solid fills carrying white text use `--color-watermelon-strong` (`#e5133e`, 4.673:1 against white). Every landing text/background pair reaches **4.5:1**; every large-text or component pair reaches **3:1**.
- **Watermelon appears only on the call-to-action and the focus ring** (core design §10.3). Everything else is the desaturated expression of the same five colours.
- **`Outfit` and nothing else**, from the *same* `apps/web/src/assets/fonts/outfit-variable-latin.woff2` (32,292 bytes) the app already serves from its own origin. One font file in the repository, two builds referencing it. **Never from a CDN.** `Reenie Beanie` is not loaded by either stylesheet.
- **Under 40 KB transferred cold**, excluding the shared woff2, and **zero requests to any host other than the page's own origin**. Both are Playwright assertions on `page.on('request')`, not aspirations.
- **The initial state is visible.** The reveal script applies the hidden state and then removes it; CSS never hides content that JavaScript must reveal. With JavaScript off, every word is readable and every link works.

### Pinned versions

Backend (slices 1A/2, unchanged): `fastapi 0.141.1` · `uvicorn 0.52.1` · `sqlalchemy 2.0.51` · `alembic 1.19.0` · `psycopg[binary] 3.3.4` · `pydantic 2.13.4` · `pydantic-settings 2.14.2` · `argon2-cffi 25.1.0` · `pyjwt 2.13.0` · `mcp 2.0.0` · `uuid-utils 0.17.0` · `pytest 9.1.1` · `pytest-cov 7.1.0` · `pytest-asyncio 1.4.0` · `testcontainers[postgres] 4.15.0` · `httpx 0.28.1` · `ruff 0.16.1` · `mypy 2.3.0`

Frontend (slice 1B, unchanged): `vite 8.2.0` · `react 19.2.8` · `react-dom 19.2.8` · `typescript 5.9` (**not** 7.x) · `@tanstack/react-router 1.170.20` · `@tanstack/router-plugin 1.168.25` · `@tanstack/react-query 5.101.4` · `@tanstack/react-table 9.0.0` · `tailwindcss 4.3.3` · `@tailwindcss/vite 4.3.3` · `@dnd-kit/core 6.3.1` · `openapi-typescript 7.13.0` · `openapi-fetch 0.17.0` · `@playwright/test 1.62.1` · `vitest 4.1.10`. Package manager **pnpm 10.12.4** (the version `Dockerfile.web` activates).

**New to this slice:** `cryptography` — declared explicitly in `packages/core/pyproject.toml` at the version `uv.lock` already resolves for `pyjwt[crypto]`; read it out of the lockfile in Task B1-3 rather than guessing. `@axe-core/playwright` — added with `pnpm add -D @axe-core/playwright`, and whatever version that resolves is pinned into `apps/web/package.json` in the same commit, the convention this repo already uses for `lucide-react`.

### Design tokens (exact values — do not improvise)

| Token | Hex | Role |
|---|---|---|
| Watermelon | `#ed254e` | brand accent, borders, icons, focus ring. **Never a solid fill under white text** |
| Watermelon strong | `#e5133e` | every solid fill that carries white text (4.673:1) |
| Royal Gold | `#f9dc5c` | warning, attention |
| Mint Cream | `#f4fffd` | app background (light) |
| Prussian Blue | `#011936` | foreground text, dark surface |
| Charcoal Blue | `#465362` | muted / secondary text |

The landing's own tokens, all derived, none new (spec §9.3):

| Token | Expression | Computed sRGB |
|---|---|---|
| `--landing-surface` | `color-mix(in oklab, var(--color-mint-cream) 92%, #ffffff)` | `#f5fffd` |
| `--landing-veil-warm` | `color-mix(in oklab, var(--color-watermelon) 32%, #ffffff)` | `#ffc3c4` |
| `--landing-veil-gold` | `color-mix(in oklab, var(--color-royal-gold) 28%, #ffffff)` | `#fdf6d7` |
| `--landing-ink` | `var(--color-prussian-blue)` | `#011936` |
| `--landing-ink-quiet` | `var(--color-charcoal-blue)` | `#465362` |

`#ffffff` is the one literal permitted inside a `color-mix()` — it is the neutral being mixed toward, not a sixth tint, and Task A1's no-raw-hex test allows exactly that token and no other.

---

## Contradictions between the spec and the shipped code, and how they were resolved

Resolved **in favour of the shipped code**, as instructed. Each is implemented in the task named.

1. **The spec says `templates.tipo` gains a `sollecito` type; the shipped column is typed by `DocumentTipo`.** `packages/core/src/pigrocrm/core/templates/schemas.py:17` imports `DocumentTipo` from `documents/schemas.py`, where it is `Literal["offerta", "contratto", "verbale", "documento"]` — a *document* type, reused for templates. Appending `sollecito` and `email` there would make them legal document types too, which they are not: no `documents` row is ever an email. **Resolution (Task B2-7):** introduce `TemplateTipo = Literal["offerta", "contratto", "verbale", "documento", "email", "sollecito"]` in `templates/schemas.py` and use it there instead of `DocumentTipo`; `DocumentTipo` is left untouched for `documents`. The DB column is already `String(20)` with no constraint, so there is no migration. The spec's substantive claim — "a `sollecito` template of slice 2's engine" — holds exactly; its implied claim that the type set is shared does not.

2. **The spec leaves the email signature "to be decided"; the shipped `emitter_profile` settles half of it.** `emitter/models.py` ships `firma_key String(255)` documented as "Storage keys, not filesystem paths" — the key of a signature *image*. It also already ships `telefono`, `sito_web`, `ragione_sociale`, `email`. The spec's §10 offers two routes and calls the second simpler. **Resolution (Task B2-7):** add a nullable `firma_email Text` column for the two things genuinely absent — the signing person's name and role — and reference the rest from the template as `{{emittente.telefono}}` / `{{emittente.sito_web}}`. That takes the simpler route without creating the second place a phone number can diverge, which was the objection to it. `firma_key` is not touched, not overloaded, and not deprecated.

3. **The spec says `activities.entity_type` is "an open value by project"; `fields/schemas.py` says the opposite about its own `EntityType`.** Residuo **R13** records that this promise had been checked and disproved three times, and slice 2 closed the argument in the source: `fields/schemas.py:11-18` now reads `EntityType = Literal["customer", "person", "deal", "document"]` under a comment that states the cost precisely — "Closed by design … widening it to add a new entity is an edit in exactly three places — here, `ENTITY_TYPES`/`CREATE_MODELS` in `schema_registry.py`, and `EntityType` in `apps/web/src/lib/schema.ts` — rather than a schema or migration change." **The two are about different columns.** `ActivityService.record` takes `entity_type: str` and truncates it to the column width (`activities/service.py:60-62`) without consulting any `Literal`, so `entity_type='google_account'` genuinely needs no migration and no schema change. `fields.EntityType` is the *custom-field* entity type, and Gmail adds no custom fields to anything. **Resolution:** the spec is right about `activities`, and `fields/schemas.py`, `schema_registry.py` and `apps/web/src/lib/schema.ts` are **not touched anywhere in this slice**. Recorded here so nobody spends a fourth investigation on it, and so nobody "helpfully" appends `google_account` to the custom-field literal — that would offer administrators custom fields on a credential row, which is not a thing.

4. **The spec's §5.6 says "six new tables"; it lists six but `google_accounts` needs a seventh column set the spec puts elsewhere.** No conflict of substance — recorded only because the count is quoted in the spec and Tasks B1-3, B1-8, B1-9, B2-3 and B2-8 create exactly `google_accounts`, `google_oauth_states`, `gmail_messages`, `gmail_message_links`, `email_drafts`, `payment_reminders`. Six.

5. **The spec's §9.3 shows `landing.css` "importing the same `@theme` as `tokens.css`". CSS cannot do that, and Tailwind's `@theme` cannot be consumed by a non-Tailwind stylesheet.** `tokens.css:47-65` declares the palette inside a Tailwind v4 `@theme` block, whose literal hex values are what let the app generate `bg-watermelon/50`-style utilities; pointing `@theme` at `var()` indirections to make them shareable would break that. **Resolution (Task A1):** the landing build *extracts* the palette from `tokens.css` at build time and injects it as a plain `:root { … }` block. There is still exactly one source of colour, drift is impossible rather than discouraged, and the app's `@theme` is not disturbed. The spec's requirement ("the landing extends it, does not fork it") is met more strictly than an `@import` would have met it.

6. **The spec says the E2E specs must be updated to the new paths; most of them already use them.** `apps/web/e2e/*.spec.ts` already navigate to `/app/clienti`, `/app/persone`, `/app/deal`, `/app/impostazioni/…`. Only three call sites use a path that moves: `e2e/helpers.ts:16` and `e2e/auth.spec.ts:15,25`, all `page.goto('/login')`. **Resolution (Task A7):** change those three, and nothing else. The spec's warning was sound but its scope was wider than the code's.

7. **The spec's §11 puts the shell banner "in the app shell"; the shipped router has both `__root.tsx` and `app.tsx`.** The banner must not appear on the login screen, and `/login` moves under `/app` in Task A7. **Resolution (Task B1-16):** the banner mounts in `routes/app.tsx` (the authenticated shell), not `__root.tsx`, because an unauthenticated visitor has no `google_accounts` row to have an opinion about and the query would 401 on every page load.

8. **The spec's §7 depends on invoices; there is no invoices module in the tree.** `packages/core/src/pigrocrm/core/` has no `invoices`/`fatture` package, so slice 3 is not shipped. **Resolution:** 5B-2 is split internally. Tasks B2-1 … B2-7 and B2-10 … B2-11 (send, drafts, RFC822, composer) depend on nothing from slice 3 and can be executed as soon as 5B-1 is merged. Tasks **B2-8, B2-9 and B2-12** (candidates, reminder creation, the solleciti page) are marked **BLOCKED ON SLICE 3** and name the exact invoice fields they consume; do not start them by inventing an invoice model.

9. **`--sidebar-primary` still carries the 4.22:1 shortfall, in both themes** (`tokens.css:97` and `:130`, each with a comment saying to repoint it when something uses it). The landing does not use the sidebar and this slice does not touch it. Recorded so it is not rediscovered cold — and Task A1's regression test is written so that it would catch the same mistake if the landing ever reached for `--color-watermelon` as a fill.

---

## File Structure

```
apps/web/                                      # 5A
├── landing/
│   ├── index.html                             # A3 — the home page Google's consent screen links to
│   ├── privacy.html                           # A4 — names gmail.readonly and gmail.send
│   ├── termini.html                           # A4
│   ├── landing.css                            # A1 tokens + A2 the soft layer
│   ├── reveal.js                              # A5 — ~1 KB, IntersectionObserver only
│   ├── palette-plugin.ts                      # A1 — injects tokens.css's palette; the anti-fork device
│   └── palette-plugin.test.ts                 # A1
├── vite.landing.config.ts                     # A6 — three HTML inputs, outDir dist-landing
├── vite.config.ts                             # A7 MODIFIED: base: '/app/'
├── playwright.config.ts                       # A6 MODIFIED: a second `landing` project
├── package.json                               # A6 MODIFIED: build:landing, @axe-core/playwright
├── src/routes/index.tsx                       # A7 DELETED — that path belongs to the landing
├── src/routes/login.tsx                       # A7 MOVED -> src/routes/app/login.tsx
├── src/styles/tokens.test.ts                  # A1 MODIFIED: the Reenie Beanie test's name
├── src/styles/landing-tokens.test.ts          # A1 — contrast + no-raw-hex + ΔE
├── e2e/helpers.ts, e2e/auth.spec.ts           # A7 MODIFIED: three `/login` call sites
├── e2e/landing.spec.ts                        # A5/A6/A8 — no-JS, budget, axe, meta
└── e2e/landing-served.spec.ts                 # A7 — routing against the real compose stack
deploy/nginx/spa.conf                          # A7 MODIFIED: landing at /, SPA under /app/
Dockerfile.web                                 # A7 MODIFIED: two builds, two copy targets
apps/web/scripts/e2e-compose.sh                # A7 — runs landing-served.spec.ts against compose

packages/core/src/pigrocrm/core/               # 5B-1 and 5B-2
├── config.py                                  # B1-2 MODIFIED: the PIGROCRM_GOOGLE_* settings
├── customers/models.py                        # B1-1 MODIFIED: an index on email
├── emitter/{models,schemas}.py                # B2-7 MODIFIED: firma_email
├── templates/schemas.py                       # B2-7 MODIFIED: TemplateTipo
├── gmail/
│   ├── transport.py                           # B1-4 — the HTTP seam and its error taxonomy
│   ├── crypto.py                              # B1-3 — AES-GCM for the refresh token
│   ├── models.py                              # B1-3, B1-8, B1-9, B2-3, B2-8
│   ├── schemas.py                             # every Pydantic shape in the slice
│   ├── repository.py                           # queries; commits nothing
│   ├── tokens.py                               # B1-5 — exchange, refresh, in-process cache
│   ├── oauth.py                                # B1-6 — PKCE start/complete
│   ├── query.py                                # B1-7 — the relevance mechanism, pure
│   ├── roster.py                               # B1-1 — the CRM's known-address roster
│   ├── parse.py                                # B1-8 — Gmail JSON -> our shapes
│   ├── sync.py                                # B1-7, B1-8, B1-10, B1-11
│   ├── account.py                              # B1-12 — status, scopes, the usability gate
│   ├── rfc822.py                               # B2-2 — message construction
│   ├── send.py                                 # B2-5, B2-6 — the single send path
│   └── solleciti.py                            # B2-8, B2-9 — BLOCKED ON SLICE 3
├── migrations/versions/…                       # one migration per model task
apps/api/src/pigrocrm_api/routers/
├── gmail.py                                    # B1-13
├── email_drafts.py                             # B2-10
└── payment_reminders.py                        # B2-10 — BLOCKED ON SLICE 3
apps/mcp/src/pigrocrm_mcp/tools/gmail.py        # B1-14, B2-10
packages/core/tests/
├── fakes/fake_gmail.py                         # B1-4 — records every request it receives
├── test_no_network.py                          # B1-4 — the suite fails if a socket opens
└── test_gmail_*.py                             # one file per task
apps/web/src/features/gmail/                    # B1-15..17, B2-11..12
```

**Why these boundaries:** `gmail/` is one domain folder but a large one, so it is split by *what fails* rather than by layer. `query.py`, `rfc822.py` and `parse.py` are pure functions with no session and no I/O — they are the three places Acme was wrong, so they are the three places that must be unit-testable without a database. `transport.py` is the only module that knows `urllib` exists. `send.py` is the only module that can call `messages.send`, which is what makes "one send path in the whole slice" checkable by grep.

---

# 5A — The landing page

**What must exist before 5A can start:** nothing beyond `main` as it stands. No backend, no migration, no service, no Google account, no credential. 5A shares not one line of code with 5B.

**What 5A must produce before 5B-1 can start:** `/`, `/privacy` and `/termini` **deployed and publicly reachable on the verified domain**, with `/privacy` naming `gmail.readonly` and `gmail.send` explicitly and stating what the product does with the data it reads. Then submit the OAuth client for verification. Until that clears, the client is in Testing and a consumer refresh token dies every 7 days.

**Tasks:** 8.

---

### Task A1: The shared palette, the landing tokens, and the contrast floor

The anti-fork device comes first, because every later task depends on being unable to invent a colour.

**Files:**
- Create: `apps/web/landing/palette-plugin.ts`
- Create: `apps/web/landing/palette-plugin.test.ts`
- Create: `apps/web/landing/landing.css`
- Create: `apps/web/landing/landing-tokens.test.ts`
- Modify: `apps/web/tsconfig.json` — `"include": ["src", "e2e"]` becomes `["src", "e2e", "landing"]`
- Modify: `apps/web/src/styles/tokens.test.ts:67-69` — the test's name, not its assertion

**Interfaces:**
- Consumes: `apps/web/src/styles/tokens.css` as read-only text — the `@theme` block at lines 47–65 and `@theme inline` at 154–188.
- Produces:
  - `export function extractSharedTokens(css: string): Record<string, string>` — the 15 custom properties both stylesheets share, keyed by full property name including the leading `--`. Throws if the count is not 15.
  - `export function palettePlugin(): Plugin` — a Vite plugin prepending those 15 as a `:root { … }` block to `landing/landing.css`. Consumed by Task A6.
  - `apps/web/landing/landing.css` declaring `--landing-surface`, `--landing-veil-warm`, `--landing-veil-gold`, `--landing-ink`, `--landing-ink-quiet`, `--landing-cta`, `--landing-cta-ink`, `--landing-focus`, `--landing-hairline`, `--landing-grain-line`, `--landing-shadow`, `--landing-lightline`, `--landing-radius-pill`. Consumed by A2, A3, A4.

- [ ] **Step 1: Write the failing test for the extractor**

`apps/web/landing/palette-plugin.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { extractSharedTokens } from './palette-plugin'

const tokensCss = readFileSync(join(__dirname, '../src/styles/tokens.css'), 'utf-8')

describe('extractSharedTokens', () => {
  it('extracts exactly the fifteen tokens the two stylesheets share', () => {
    expect(Object.keys(extractSharedTokens(tokensCss)).sort()).toEqual([
      '--color-charcoal-blue',
      '--color-mint-cream',
      '--color-prussian-blue',
      '--color-royal-gold',
      '--color-watermelon',
      '--color-watermelon-strong',
      '--font-sans',
      '--radius',
      '--radius-2xl',
      '--radius-3xl',
      '--radius-4xl',
      '--radius-lg',
      '--radius-md',
      '--radius-sm',
      '--radius-xl',
    ])
  })

  it('carries the live hex, so an edit to tokens.css travels with it', () => {
    expect(extractSharedTokens(tokensCss)['--color-watermelon-strong']).toBe('#e5133e')
  })

  it('drops the app-only indirections rather than emitting dangling var() references', () => {
    // `@theme inline` re-exports --color-primary: var(--primary) and 25 siblings.
    // --primary is declared in tokens.css's `:root`, which the landing does not
    // import, so injecting them would produce colours resolving to nothing.
    const extracted = extractSharedTokens(tokensCss)
    expect(extracted['--color-primary']).toBeUndefined()
    expect(extracted['--color-background']).toBeUndefined()
    // --radius-2xl also uses var(), but only of a token that IS extracted.
    expect(extracted['--radius-2xl']).toBe('calc(var(--radius) * 1.8)')
  })

  it('refuses a stylesheet that has lost the palette, instead of emitting nothing', () => {
    expect(() => extractSharedTokens('@theme { --color-watermelon: #ed254e; }')).toThrow(
      /extracted only 1 shared token/,
    )
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run landing/palette-plugin.test.ts`
Expected: FAIL — `Failed to resolve import "./palette-plugin"`.

- [ ] **Step 3: Write the extractor and the plugin**

`apps/web/landing/palette-plugin.ts`:

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'

const TOKENS_CSS = resolve(__dirname, '../src/styles/tokens.css')

/** The palette, the font stack and the radius scale, and nothing else. Fifteen
 *  today; the count is asserted so that a token added to or removed from
 *  tokens.css is a failing test rather than a silently thinner landing. */
const EXPECTED_TOKEN_COUNT = 15

/**
 * Reads the custom properties `tokens.css` declares inside a `@theme` block and
 * that the landing can meaningfully use on its own.
 *
 * Why extraction and not an `@import`: the palette lives inside Tailwind v4's
 * `@theme` at-rule, whose literal hex values are what let the app generate
 * `bg-watermelon/50`-style utilities. Pointing `@theme` at `var()` indirections to
 * make the block shareable would break that. The landing has no Tailwind at all, so
 * it cannot consume `@theme` either way. Copying the six hexes into `landing.css`
 * is the obvious alternative and is exactly the fork this function exists to make
 * impossible: there is one source of colour, and a landing built from a stale copy
 * of it cannot happen because no copy exists.
 *
 * The `var()` filter is what keeps `@theme inline`'s 26 semantic re-exports out.
 * They point at `--primary`, `--background` and friends, which live in
 * `tokens.css`'s `:root` and are the *app's* theme, not the shared system.
 */
export function extractSharedTokens(css: string): Record<string, string> {
  const collected: Record<string, string> = {}
  // tokens.css's two `@theme` blocks contain no nested braces, so a non-greedy
  // match up to the first `}` is exact here.
  for (const block of css.matchAll(/@theme[^{]*\{([^}]*)\}/g)) {
    for (const decl of (block[1] ?? '').matchAll(
      /(--(?:color|radius|font)[\w-]*)\s*:\s*([^;]+);/g,
    )) {
      const name = decl[1]
      const value = decl[2]
      if (name && value) collected[name] = value.trim()
    }
  }

  const names = new Set(Object.keys(collected))
  const shared: Record<string, string> = {}
  for (const [name, value] of Object.entries(collected)) {
    const references = [...value.matchAll(/var\((--[\w-]+)\)/g)].map((match) => match[1])
    if (references.every((reference) => reference !== undefined && names.has(reference))) {
      shared[name] = value
    }
  }

  const count = Object.keys(shared).length
  if (count !== EXPECTED_TOKEN_COUNT) {
    throw new Error(
      `extractSharedTokens extracted only ${count} shared token${count === 1 ? '' : 's'} ` +
        `from tokens.css (expected ${EXPECTED_TOKEN_COUNT}). The landing must not restate ` +
        'the palette: fix the extraction, do not paste values into landing.css.',
    )
  }
  return shared
}

/** Prepends the shared tokens to `landing/landing.css`, at build and at dev time. */
export function palettePlugin(): Plugin {
  return {
    name: 'pigrocrm-landing-palette',
    enforce: 'pre',
    transform(code, id) {
      if (!id.split('?')[0]?.endsWith('landing/landing.css')) return null
      const tokens = extractSharedTokens(readFileSync(TOKENS_CSS, 'utf-8'))
      const block = Object.entries(tokens)
        .map(([name, value]) => `  ${name}: ${value};`)
        .join('\n')
      return `/* injected from src/styles/tokens.css by palette-plugin.ts */\n:root {\n${block}\n}\n\n${code}`
    },
  }
}
```

- [ ] **Step 4: Add `landing` to the TypeScript project, then run the test**

`apps/web/tsconfig.json`: change `"include": ["src", "e2e"]` to `"include": ["src", "e2e", "landing"]`. Without it `pnpm tsc --noEmit` type-checks neither new file.

Run: `cd apps/web && pnpm vitest run landing/palette-plugin.test.ts`
Expected: PASS (4 tests). If the count assertion fails at 15, read what changed in `tokens.css` and update the list in the test — do not loosen the guard.

- [ ] **Step 5: Write the failing test for the landing tokens**

`apps/web/landing/landing-tokens.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { extractSharedTokens } from './palette-plugin'

const shared = extractSharedTokens(readFileSync(join(__dirname, '../src/styles/tokens.css'), 'utf-8'))
const landingCss = readFileSync(join(__dirname, 'landing.css'), 'utf-8')

type Triple = [number, number, number]

function toLinear(channel: number): number {
  const c = channel / 255
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function toChannel(linear: number): number {
  const v = linear <= 0.0031308 ? linear * 12.92 : 1.055 * Math.pow(linear, 1 / 2.4) - 0.055
  return Math.min(255, Math.max(0, Math.round(v * 255)))
}

function hexToRgb(hex: string): Triple {
  const v = hex.replace('#', '')
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)]
}

function rgbToHex([r, g, b]: Triple): string {
  return `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`
}

/** The CSS Color 4 matrices. `color-mix(in oklab, …)` interpolates in exactly this
 *  space, so resolving a token here yields the sRGB a browser would paint. */
function rgbToOklab([r, g, b]: Triple): Triple {
  const lr = toLinear(r)
  const lg = toLinear(g)
  const lb = toLinear(b)
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb)
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb)
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function oklabToRgb([L, a, b]: Triple): Triple {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    toChannel(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    toChannel(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    toChannel(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]
}

function relativeLuminance([r, g, b]: Triple): number {
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
}

/** WCAG 2.x contrast ratio, order-independent. Same formula as tokens.test.ts. */
function contrastRatio(hexA: string, hexB: string): number {
  const a = relativeLuminance(hexToRgb(hexA))
  const b = relativeLuminance(hexToRgb(hexB))
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/** Euclidean distance in OKLab. Perceptually uniform by construction, which is what
 *  makes a single threshold defensible across hues. */
function deltaEOk(hexA: string, hexB: string): number {
  const a = rgbToOklab(hexToRgb(hexA))
  const b = rgbToOklab(hexToRgb(hexB))
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
}

const LANDING_DECLARATION = /--landing-[\w-]+\s*:\s*[^;]+;/g
const MIX = /^color-mix\(in oklab,\s*var\((--color-[\w-]+)\)\s*(\d+)%,\s*#ffffff\)$/
const VAR = /^var\((--color-[\w-]+)\)$/

function declaredValue(token: string): string {
  const match = landingCss.match(new RegExp(`${token}\\s*:\\s*([^;]+);`))
  const value = match?.[1]
  if (!value) throw new Error(`${token} is not declared in landing.css`)
  return value.trim()
}

/** Resolves a --landing-* colour token to the sRGB hex a browser would compute. */
function resolveLandingColour(token: string): string {
  const value = declaredValue(token)
  const direct = VAR.exec(value)
  if (direct) {
    const hex = shared[direct[1] ?? '']
    if (!hex) throw new Error(`${token} points at ${direct[1]}, which tokens.css does not define`)
    return hex
  }
  const mixed = MIX.exec(value)
  if (mixed) {
    const hex = shared[mixed[1] ?? '']
    if (!hex) throw new Error(`${token} mixes ${mixed[1]}, which tokens.css does not define`)
    const share = Number(mixed[2]) / 100
    const from = rgbToOklab(hexToRgb(hex))
    const to = rgbToOklab([255, 255, 255])
    return rgbToHex(
      oklabToRgb([
        from[0] * share + to[0] * (1 - share),
        from[1] * share + to[1] * (1 - share),
        from[2] * share + to[2] * (1 - share),
      ]),
    )
  }
  throw new Error(`${token} is neither var(--color-…) nor a color-mix of one: ${value}`)
}

describe('landing tokens', () => {
  it('resolves every --landing-* colour out of the shared palette', () => {
    expect(resolveLandingColour('--landing-surface')).toBe('#f5fffd')
    expect(resolveLandingColour('--landing-veil-warm')).toBe('#ffc3c4')
    expect(resolveLandingColour('--landing-veil-gold')).toBe('#fdf6d7')
    expect(resolveLandingColour('--landing-ink')).toBe('#011936')
    expect(resolveLandingColour('--landing-ink-quiet')).toBe('#465362')
    expect(resolveLandingColour('--landing-cta')).toBe('#e5133e')
    expect(resolveLandingColour('--landing-focus')).toBe('#ed254e')
  })

  it('contains no raw hexadecimal in the --landing-* block, other than white', () => {
    // White is the neutral a tint is mixed toward, not a sixth colour. Everything
    // else must be a var(--color-…) or a color-mix() of one, which is what makes
    // forking the palette mechanically impossible rather than discouraged.
    for (const declaration of landingCss.match(LANDING_DECLARATION) ?? []) {
      for (const hex of declaration.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []) {
        expect(hex.toLowerCase(), `raw hex in ${declaration}`).toBe('#ffffff')
      }
    }
  })

  it('reaches 4.5:1 on every text pair', () => {
    const surface = resolveLandingColour('--landing-surface')
    const warm = resolveLandingColour('--landing-veil-warm')
    const gold = resolveLandingColour('--landing-veil-gold')
    const ink = resolveLandingColour('--landing-ink')
    const quiet = resolveLandingColour('--landing-ink-quiet')
    for (const [text, background] of [
      [ink, surface],
      [quiet, surface],
      [ink, warm],
      [quiet, warm],
      [ink, gold],
      [quiet, gold],
      ['#ffffff', resolveLandingColour('--landing-cta')],
    ] as const) {
      expect(contrastRatio(text, background), `${text} on ${background}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('reaches 3:1 on the focus ring, which is a component and not text', () => {
    const ratio = contrastRatio(
      resolveLandingColour('--landing-focus'),
      resolveLandingColour('--landing-surface'),
    )
    expect(ratio).toBeGreaterThanOrEqual(3)
  })

  it('never uses raw Watermelon as a solid fill', () => {
    // The regression banned by name. In the app this is solved: --primary and
    // --destructive both point at --color-watermelon-strong, because white on raw
    // Watermelon is 4.221:1 and misses the 4.5:1 body-text floor. The landing must
    // not re-introduce it on the one element that IS a solid fill under white
    // text: the call to action.
    for (const [, property, value] of landingCss.matchAll(
      /(?:^|[;{])\s*(background|background-color|fill)\s*:\s*([^;}]+)/g,
    )) {
      expect(value, `${property} fills with raw Watermelon`).not.toMatch(
        /--color-watermelon(?!-strong)/,
      )
      expect(value, `${property} fills with #ed254e`).not.toMatch(/#ed254e/i)
    }
  })

  it('lands --landing-veil-warm within the declared ΔE of Coral #FFB7B2', () => {
    // Spec 9.3 makes Coral a target to hit, not a sixth token to add. 32% measures
    // 0.0313 in OKLab; the declared tolerance is 0.05. 39% would be the exact
    // centre (0.0093), but the spec fixes 32% and 32% is inside tolerance, so the
    // declared recipe stands and this test says what "in the neighbourhood" means
    // as a number.
    expect(deltaEOk(resolveLandingColour('--landing-veil-warm'), '#ffb7b2')).toBeLessThanOrEqual(0.05)
  })

  it('loads no webfont other than Outfit, and none from a CDN', () => {
    expect(landingCss).not.toMatch(/Reenie/i)
    expect(landingCss).not.toMatch(/fonts\.googleapis\.com|fonts\.gstatic\.com/)
    const families = [...landingCss.matchAll(/@font-face\s*\{[^}]*font-family:\s*'([^']+)'/g)].map(
      (m) => m[1],
    )
    expect(families).toEqual(['Outfit'])
  })
})
```

- [ ] **Step 6: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run landing/landing-tokens.test.ts`
Expected: FAIL — `ENOENT … landing/landing.css`.

- [ ] **Step 7: Write the token block**

`apps/web/landing/landing.css` — the whole file for now; Task A2 appends to it.

```css
/* The landing page's own stylesheet. It has no Tailwind, no framework and no
   palette of its own: palette-plugin.ts prepends the fifteen shared tokens out of
   src/styles/tokens.css at build time, so the five colours, the font stack and the
   radius scale are literally the same values the app renders.

   Every token below is a var() or a color-mix() of one of those. #ffffff is the
   only literal, and only ever as the neutral a tint is mixed toward. */
:root {
  /* Surfaces */
  --landing-surface: color-mix(in oklab, var(--color-mint-cream) 92%, #ffffff);
  --landing-veil-warm: color-mix(in oklab, var(--color-watermelon) 32%, #ffffff);
  --landing-veil-gold: color-mix(in oklab, var(--color-royal-gold) 28%, #ffffff);

  /* Text. 17.263:1 and 7.705:1 on --landing-surface respectively. */
  --landing-ink: var(--color-prussian-blue);
  --landing-ink-quiet: var(--color-charcoal-blue);

  /* The one saturated thing on the page, and precisely what
     --color-watermelon-strong exists for: white on it is 4.673:1, white on raw
     Watermelon is 4.221:1 and fails the body-text floor. */
  --landing-cta: var(--color-watermelon-strong);
  --landing-cta-ink: #ffffff;
  /* Raw Watermelon is correct here: a focus ring is a component (3:1), not text,
     and it measures 4.141:1 against --landing-surface. */
  --landing-focus: var(--color-watermelon);

  /* Separation comes from surface tint and from space. Where a line is
     unavoidable it is a hairline in transparent Prussian Blue, never --border. */
  --landing-hairline: color-mix(in oklab, var(--color-prussian-blue) 8%, transparent);
  /* Spec 9.3 writes this as rgba(1, 25, 54, .04). That is Prussian Blue spelled as
     a literal, which the no-raw-hex rule in the same section forbids -- so it is
     spelled as the mix instead. Identical result, one source of colour. */
  --landing-grain-line: color-mix(in oklab, var(--color-prussian-blue) 4%, transparent);

  /* Relief without borders: large, soft, low opacity, plus a light edge on top.
     Carried from Acme's .invoice-chart / .offer-group recipe (App.css:537-542,
     824-830), re-tinted from its greens to Prussian Blue. */
  --landing-shadow: 0 24px 60px -24px color-mix(in oklab, var(--color-prussian-blue) 22%, transparent);
  --landing-lightline: inset 0 1px 0 rgba(255, 255, 255, 0.8);

  --landing-radius-pill: 999px;
}

/* Same woff2 as the app, same origin, one file in the repository. Never a CDN: a
   product sold on the promise of self-hosting cannot hand every visitor's IP to
   Google, and an @import in CSS blocks rendering on top of that. */
@font-face {
  font-family: 'Outfit';
  font-style: normal;
  font-weight: 300 700;
  font-display: swap;
  src: url('../src/assets/fonts/outfit-variable-latin.woff2') format('woff2');
}
```

- [ ] **Step 8: Run it and watch it pass**

Run: `cd apps/web && pnpm vitest run landing/`
Expected: PASS (11 tests across the two files).

- [ ] **Step 9: Correct the false claim in the app's own token test**

The assertion at `apps/web/src/styles/tokens.test.ts:67-69` is still right; its *name* now asserts something this slice has decided is false — that `Reenie Beanie` belongs to the landing. Replace those three lines with:

```ts
  it('loads no webfont other than Outfit', () => {
    // `Reenie Beanie` was reserved for the landing page in slice 1B. Slice 5
    // decided it belongs to neither stylesheet: a second webfont is another
    // request and another licence check, it is illegible at small sizes, and a
    // handwritten accent on a page Google reads during OAuth verification looks
    // unserious. landing/landing-tokens.test.ts asserts the same for the other
    // stylesheet, so neither can regain it quietly.
    expect(css).not.toMatch(/Reenie/i)
    const families = [...css.matchAll(/@font-face\s*\{[^}]*font-family:\s*'([^']+)'/g)].map((m) => m[1])
    expect(families).toEqual(['Outfit'])
  })
```

- [ ] **Step 10: Run the whole unit suite and the type check**

Run: `cd apps/web && pnpm vitest run && pnpm tsc --noEmit`
Expected: PASS, with `tokens.test.ts` still green.

- [ ] **Step 11: Commit**

```bash
git add apps/web/landing apps/web/tsconfig.json apps/web/src/styles/tokens.test.ts
git commit -m "feat(landing): the palette is extracted from tokens.css, never restated"
```

---

### Task A2: The soft layer — grain, relief, radii, rhythm, motion

**Files:**
- Modify: `apps/web/landing/landing.css` (append)
- Create: `apps/web/landing/landing-style.test.ts`

**Interfaces:**
- Consumes: every `--landing-*` token from Task A1.
- Produces: the class names A3 and A4 build markup from — `.grain`, `.wrap`, `.section`, `.measure`, `.overline`, `.lead`, `.card`, `.hairline`, `.cta`, `.quiet-link`, `.rise` — plus `.rise[data-hidden]`, the hidden state Task A5's script adds and removes, and the custom property `--rise-index` it sets per element.

- [ ] **Step 1: Write the failing test**

`apps/web/landing/landing-style.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'landing.css'), 'utf-8')

/** The declarations of one rule, by exact selector. */
function rule(selector: string): string {
  const escaped = selector.replace(/[.[\]*+?^${}()|\\]/g, '\\$&')
  const body = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))?.[1]
  if (!body) throw new Error(`rule "${selector}" not found in landing.css`)
  return body
}

describe('the landing soft layer', () => {
  it('defaults every border away, the way the app does not', () => {
    // The app separates with --border everywhere. The landing separates with the
    // tint of the surface and with space; any visible line is a hairline.
    expect(rule('*')).toMatch(/border-width:\s*0/)
    expect(css).not.toMatch(/var\(--border\)/)
  })

  it('never uses backdrop-filter', () => {
    // Acme puts blur(12px) on .panel (App.css:166-172). It costs GPU on a phone,
    // and on a static page there is nothing behind the surface worth blurring.
    expect(css).not.toMatch(/backdrop-filter/)
  })

  it('lays the grain under the content, in two stacked pseudo-elements', () => {
    expect(rule('.grain::before').match(/radial-gradient/g)).toHaveLength(3)
    expect(rule('.grain::after')).toMatch(/repeating-linear-gradient\(\s*120deg/)
    expect(rule('.grain::after')).toMatch(/opacity:\s*0\.12/)
    expect(rule('.grain::after')).toMatch(/pointer-events:\s*none/)
    for (const selector of ['.grain::before', '.grain::after']) {
      expect(rule(selector)).toMatch(/z-index:\s*-\d/)
    }
  })

  it('turns the grain off when the reader asked for more contrast', () => {
    // The hatching sits above the background and below the text, so under
    // prefers-contrast: more it is contrast taken away.
    const block = css.match(/@media \(prefers-contrast: more\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(block).toMatch(/\.grain::before/)
    expect(block).toMatch(/\.grain::after/)
    expect(block).toMatch(/display:\s*none/)
  })

  it('uses only the shipped radius scale, plus the pill for the CTA', () => {
    for (const [, value] of css.matchAll(/border-radius:\s*([^;]+);/g)) {
      expect(value.trim()).toMatch(
        /^var\(--radius-(?:2xl|3xl|4xl|md|lg)\)$|^var\(--landing-radius-pill\)$/,
      )
    }
    expect(rule('.cta')).toMatch(/border-radius:\s*var\(--landing-radius-pill\)/)
  })

  it('gives sections a wider rhythm than the app and a 62ch measure', () => {
    expect(rule('.section')).toMatch(/padding-block:\s*clamp\(4rem,\s*10vw,\s*9rem\)/)
    expect(rule('.measure')).toMatch(/max-width:\s*62ch/)
  })

  it('carries Acme overlines verbatim', () => {
    // App.css:88-94. A small detail that does much of the work of that system's
    // character.
    expect(rule('.overline')).toMatch(/text-transform:\s*uppercase/)
    expect(rule('.overline')).toMatch(/letter-spacing:\s*0\.24em/)
    expect(rule('.overline')).toMatch(/font-size:\s*0\.75rem/)
  })

  it('shortens Acme rise from 0.6s to 320ms and stages it 60ms apart', () => {
    expect(rule('.rise')).toMatch(/320ms/)
    expect(rule('.rise')).toMatch(/cubic-bezier\(0\.2,\s*0\.7,\s*0\.2,\s*1\)/)
    expect(css).toMatch(/--rise-stagger:\s*60ms/)
  })

  it('hides only under an attribute a script has to add', () => {
    // The rule that matters: the initial state is visible. CSS that hides and JS
    // that reveals gives a blank page whenever the script does not run.
    expect(rule('.rise[data-hidden]')).toMatch(/opacity:\s*0/)
    expect(rule('.rise[data-hidden]')).toMatch(/translateY\(12px\)/)
    expect(rule('.rise')).not.toMatch(/opacity:\s*0\b/)
  })

  it('cancels the motion entirely when the reader asked for less of it', () => {
    const block = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(block).toMatch(/\.rise/)
    expect(block).toMatch(/transition:\s*none/)
    expect(block).toMatch(/transform:\s*none/)
    expect(block).toMatch(/opacity:\s*1/)
  })

  it('has no scroll-linked transform anywhere', () => {
    // No parallax: it fights the reader and it costs on a phone.
    expect(css).not.toMatch(/animation-timeline|scroll\(\)|view\(\)/)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run landing/landing-style.test.ts`
Expected: FAIL — `rule "*" not found in landing.css`.

- [ ] **Step 3: Append the soft layer**

Append to `apps/web/landing/landing.css`:

```css
* {
  box-sizing: border-box;
  /* The app draws --border on everything (tokens.css @layer base). The landing
     draws nothing: relief comes from --landing-shadow plus --landing-lightline,
     separation from surface tint and from space. */
  border-width: 0;
  border-style: solid;
  margin: 0;
}

html {
  -webkit-text-size-adjust: 100%;
}

body {
  --rise-stagger: 60ms;
  background-color: var(--landing-surface);
  color: var(--landing-ink);
  font-family: var(--font-sans);
  font-weight: 300;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

/* --- Grain: two stacked layers, zero bytes, zero requests, no binary asset. That
   is why this beats an feTurbulence in a data: URI. Carried from Acme
   (App.css:52-77), re-tinted: the blooms take the landing veils instead of its
   burnt orange and sage, and the hatching is Prussian Blue rather than black. */
.grain {
  position: relative;
  isolation: isolate;
  overflow-x: clip;
}

.grain::before {
  content: '';
  position: absolute;
  inset: -20% 0 0;
  background:
    radial-gradient(circle at 8% 4%, var(--landing-veil-warm), transparent 55%),
    radial-gradient(circle at 82% 18%, var(--landing-veil-gold), transparent 55%),
    radial-gradient(circle at 24% 72%, var(--landing-surface), transparent 55%);
  pointer-events: none;
  z-index: -2;
}

.grain::after {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    120deg,
    var(--landing-grain-line) 0,
    var(--landing-grain-line) 1px,
    transparent 1px,
    transparent 10px
  );
  opacity: 0.12;
  pointer-events: none;
  z-index: -1;
}

/* The hatching lies above the background and below the text. A reader who asked
   for more contrast is asking for less of exactly this. */
@media (prefers-contrast: more) {
  .grain::before,
  .grain::after {
    display: none;
  }
}

/* --- Rhythm, wider than the app's: the calm comes from the space, and space is
   the cheapest thing on the page to get right. */
.wrap {
  max-width: 72rem;
  margin-inline: auto;
}

.section {
  padding-block: clamp(4rem, 10vw, 9rem);
  padding-inline: clamp(1.25rem, 5vw, 3rem);
}

.measure {
  max-width: 62ch;
}

/* --- Type: fluid, one family. */
h1 {
  font-size: clamp(2.4rem, 3vw + 1.6rem, 4rem);
  font-weight: 300;
  line-height: 1.1;
  letter-spacing: -0.02em;
}

h2 {
  font-size: clamp(1.6rem, 1.5vw + 1.1rem, 2.4rem);
  font-weight: 400;
  line-height: 1.2;
}

p,
li {
  font-size: clamp(1rem, 0.3vw + 0.95rem, 1.125rem);
  color: var(--landing-ink-quiet);
}

.lead {
  font-size: clamp(1.15rem, 0.6vw + 1rem, 1.4rem);
  color: var(--landing-ink);
}

.overline {
  text-transform: uppercase;
  letter-spacing: 0.24em;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--landing-ink-quiet);
  margin-bottom: 0.6rem;
}

/* --- Surfaces: translucent white, relief from shadow plus a light edge, no blur. */
.card {
  background-color: rgba(255, 255, 255, 0.85);
  border-radius: var(--radius-4xl);
  box-shadow: var(--landing-shadow), var(--landing-lightline);
  padding: clamp(1.5rem, 3vw, 2.5rem);
}

.hairline {
  border-top-width: 1px;
  border-top-color: var(--landing-hairline);
}

/* --- The one saturated element on the page. */
.cta {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background-color: var(--landing-cta);
  color: var(--landing-cta-ink);
  font-size: 1.0625rem;
  font-weight: 500;
  text-decoration: none;
  padding: 0.9rem 1.75rem;
  border-radius: var(--landing-radius-pill);
  box-shadow: var(--landing-shadow);
}

.quiet-link {
  color: var(--landing-ink-quiet);
  text-decoration: none;
  border-radius: var(--radius-md);
  padding: 0.4rem 0.75rem;
}

.quiet-link:hover,
.cta:hover {
  text-decoration: underline;
}

:where(a, button):focus-visible {
  outline: 3px solid var(--landing-focus);
  outline-offset: 3px;
}

/* --- Motion: Acme's rise (App.css:1233-1242), shortened from 0.6s -- on a page
   that scrolls, 0.6s per element accumulates. No parallax and nothing tied to
   scroll position.

   The initial state is VISIBLE. reveal.js adds [data-hidden] and then removes it;
   CSS that hides and JS that reveals is a blank page whenever the script fails. */
.rise {
  transition:
    opacity 320ms cubic-bezier(0.2, 0.7, 0.2, 1),
    transform 320ms cubic-bezier(0.2, 0.7, 0.2, 1);
  transition-delay: calc(var(--rise-index, 0) * var(--rise-stagger));
}

.rise[data-hidden] {
  opacity: 0;
  transform: translateY(12px);
}

/* Acme's guard covered only .panel and .button (App.css:1289-1297). This one
   covers everything that moves, because everything that moves is .rise. */
@media (prefers-reduced-motion: reduce) {
  .rise,
  .rise[data-hidden] {
    transition: none;
    transform: none;
    opacity: 1;
  }
}
```

- [ ] **Step 4: Run it and watch it pass**

Run: `cd apps/web && pnpm vitest run landing/`
Expected: PASS. `landing-tokens.test.ts`'s no-raw-hex test still passes: the only new literals are `rgba(255, 255, 255, 0.85)` on `.card` and `rgba(255, 255, 255, 0.8)` inside `--landing-lightline`, both white, and `.card`'s is not inside a `--landing-*` declaration at all.

- [ ] **Step 5: Commit**

```bash
git add apps/web/landing
git commit -m "feat(landing): grain, relief and rhythm, borrowed from Acme and re-tinted"
```

---

### Task A3: `/` — the home page

**Files:**
- Create: `apps/web/landing/index.html`
- Create: `apps/web/landing/landing-pages.test.ts`

**Interfaces:**
- Consumes: the class names from Task A2.
- Produces: `apps/web/landing/index.html`, one of the three `rollupOptions.input` entries Task A6 declares. Also `landing-pages.test.ts`'s `describe.each(PAGES)` block, which Task A4 appends to.

- [ ] **Step 1: Write the failing test**

`apps/web/landing/landing-pages.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const PAGES = ['index.html', 'privacy.html', 'termini.html'] as const
const html = Object.fromEntries(
  PAGES.map((name) => [name, readFileSync(join(__dirname, name), 'utf-8')]),
) as Record<(typeof PAGES)[number], string>

function meta(page: string, name: string): string | undefined {
  return page.match(new RegExp(`<meta\\s+(?:name|property)="${name}"\\s+content="([^"]*)"`))?.[1]
}

describe.each(PAGES)('%s', (name) => {
  const page = html[name]

  it('is in Italian and says so', () => {
    expect(page).toMatch(/<html lang="it">/)
  })

  it('carries its own title, description and Open Graph', () => {
    const title = page.match(/<title>([^<]+)<\/title>/)?.[1] ?? ''
    expect(title).toContain('PigroCRM')
    const description = meta(page, 'description') ?? ''
    expect(description.length).toBeGreaterThan(40)
    // The trap named in spec 9.2: Acme's index.html still carries "Humancraft is
    // the AI optimization platform for human and AI agents" from the scaffold it
    // was generated out of (.reference-acme/website/index.html:7-10), describing
    // a product that exists nowhere in that codebase. It is the easiest mistake
    // to repeat, and it is text Google reads during verification.
    expect(description).not.toMatch(/AI optimization platform/i)
    expect(meta(page, 'og:title')).toBeTruthy()
    expect(meta(page, 'og:description')).toBeTruthy()
    expect(meta(page, 'og:type')).toBe('website')
  })

  it('requests nothing from another origin', () => {
    for (const [, url] of page.matchAll(/(?:href|src)="(https?:\/\/[^"]+)"/g)) {
      // An href to a repository the reader clicks is fine; a subresource is not.
      expect(url, 'external subresource').toMatch(/^https:\/\/github\.com\//)
    }
    expect(page).not.toMatch(/fonts\.googleapis\.com|fonts\.gstatic\.com/)
    expect(page).not.toMatch(/<link[^>]+href="https?:/)
    expect(page).not.toMatch(/<script[^>]+src="https?:/)
  })

  it('offers a way into an existing installation', () => {
    // Spec 9.1 purpose 4: whoever opens the root of their own instance must not
    // be stranded on advertising copy.
    expect(page).toMatch(/href="\/app\/"/)
    expect(page).toContain('Accedi')
  })

  it('lays the grain under the content', () => {
    expect(page).toMatch(/<body class="grain">/)
  })
})

describe('index.html', () => {
  const page = html['index.html']

  it('sends the visitor to the only action that exists', () => {
    // There is no public signup and the product stays single-tenant self-hosted.
    // A CTA promising a registration that does not exist is worse than no CTA.
    expect(page).toContain('Installala sul tuo server')
    expect(page).not.toMatch(/Prova gratis|Registrati|Iscriviti/i)
  })

  it('says who it is for, in the words that qualify a reader in fifteen seconds', () => {
    for (const word of ['freelance', 'forfettario', 'self-hosted']) {
      expect(page.toLowerCase()).toContain(word)
    }
  })

  it('links the two pages Google reads during verification', () => {
    expect(page).toMatch(/href="\/privacy"/)
    expect(page).toMatch(/href="\/termini"/)
  })

  it('collects nothing and measures nothing', () => {
    expect(page).not.toMatch(/<form/i)
    expect(page).not.toMatch(/<input/i)
    expect(page).not.toMatch(/gtag|googletagmanager|analytics|plausible|fathom|hotjar|pixel/i)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run landing/landing-pages.test.ts`
Expected: FAIL — `ENOENT … landing/index.html`.

- [ ] **Step 3: Write the page**

`apps/web/landing/index.html`:

```html
<!doctype html>
<html lang="it">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PigroCRM — il CRM che lavora al posto tuo</title>
    <meta
      name="description"
      content="Un CRM self-hosted per freelance e piccole società di consulenza in Italia: clienti, persone, deal, offerte in PDF e fatture, con un server MCP perché a usarlo sia anche il tuo assistente AI."
    />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="PigroCRM — il CRM che lavora al posto tuo" />
    <meta
      property="og:description"
      content="Clienti, deal, offerte e fatture su un server che è tuo. Pensato per il regime forfettario, e progettato perché un assistente AI possa usarlo quanto te."
    />
    <meta property="og:locale" content="it_IT" />
    <link rel="stylesheet" href="./landing.css" />
  </head>
  <body class="grain">
    <header class="wrap section" style="padding-block: 1.5rem">
      <nav style="display: flex; align-items: center; justify-content: space-between">
        <span style="font-size: 1.25rem; font-weight: 500">PigroCRM</span>
        <a class="quiet-link" href="/app/">Accedi</a>
      </nav>
    </header>

    <main>
      <section class="wrap section">
        <p class="overline rise">CRM self-hosted · AI-first</p>
        <h1 class="measure rise">Il CRM che lavora al posto tuo.</h1>
        <p class="lead measure rise" style="margin-top: 1.5rem">
          Clienti, persone, deal, offerte in PDF e fatture — su un server che è tuo, con i tuoi dati
          nel tuo database. E un server MCP, perché il lavoro noioso lo faccia il tuo assistente AI
          invece di te.
        </p>
        <p class="rise" style="margin-top: 2.5rem">
          <a class="cta" href="https://github.com/pigrocrm/pigrocrm#installazione"
            >Installala sul tuo server</a
          >
        </p>
        <p class="measure rise" style="margin-top: 1rem; font-size: 0.9375rem">
          Non c'è una registrazione: non è un servizio, è un programma che installi. Docker Compose,
          un dominio, dieci minuti.
        </p>
      </section>

      <section class="wrap section">
        <p class="overline">Per chi è</p>
        <div
          style="display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr))"
        >
          <article class="card rise">
            <h2>Freelance e piccole società di consulenza</h2>
            <p>
              In Italia, spesso in regime forfettario. Pochi clienti, pochi deal, molte offerte da
              scrivere e fatture da farsi pagare.
            </p>
          </article>
          <article class="card rise">
            <h2>Chi vuole i suoi dati sul suo server</h2>
            <p>
              Self-hosted per davvero: nessun account da creare presso di noi, nessun piano da
              scegliere, nessun dato che esce dalla tua macchina se non lo mandi tu.
            </p>
          </article>
          <article class="card rise">
            <h2>Chi lavora già con un assistente AI</h2>
            <p>
              Ogni cosa che fa l'interfaccia la fa anche il server MCP, sugli stessi servizi. Non è
              un'integrazione aggiunta dopo: è metà del progetto.
            </p>
          </article>
        </div>
      </section>

      <section class="wrap section">
        <p class="overline">Cosa fa</p>
        <ul class="measure" style="display: grid; gap: 0.75rem; list-style: none; padding: 0">
          <li class="rise">Clienti, persone e deal, con i campi che decidi tu a runtime.</li>
          <li class="rise">Offerte e contratti da template Markdown, in PDF, con i tuoi dati fiscali.</li>
          <li class="rise">Fatture e solleciti, con la lista di chi va sollecitato già pronta.</li>
          <li class="rise">Gmail: le conversazioni con i tuoi contatti, sulla scheda del cliente.</li>
          <li class="rise">Un server MCP su tutto quanto sopra.</li>
        </ul>
      </section>

      <footer class="wrap section hairline" style="padding-block: 2.5rem">
        <p style="font-size: 0.9375rem">
          <a class="quiet-link" href="/privacy" style="padding-left: 0">Privacy</a>
          <a class="quiet-link" href="/termini">Termini</a>
        </p>
      </footer>
    </main>

    <script src="./reveal.js" defer></script>
  </body>
</html>
```

- [ ] **Step 4: Run the page test**

Run: `cd apps/web && pnpm vitest run landing/landing-pages.test.ts`
Expected: FAIL, but **only** on `privacy.html` and `termini.html` (`ENOENT`) — Task A4 writes them. The `describe('index.html')` block's four tests pass. Confirm that before moving on.

- [ ] **Step 5: Commit**

```bash
git add apps/web/landing
git commit -m "feat(landing): the home page, with the only call to action that exists"
```

---

### Task A4: `/privacy` and `/termini` — the pages Google reads

This is what 5B-1 is actually blocked on. `/privacy` must name both restricted scopes and state what the product does with the data, or verification does not clear and the OAuth client stays in Testing.

**Files:**
- Create: `apps/web/landing/privacy.html`
- Create: `apps/web/landing/termini.html`
- Modify: `apps/web/landing/landing-pages.test.ts` (append two `describe` blocks)

**Interfaces:**
- Consumes: `landing.css` from A2, and A3's shared `describe.each(PAGES)` block, which already covers `lang`, title, description, Open Graph, no external subresource, the `Accedi` link and the grain for all three pages.
- Produces: the remaining two `rollupOptions.input` entries.

- [ ] **Step 1: Write the failing test**

Append to `apps/web/landing/landing-pages.test.ts`:

```ts
describe('privacy.html', () => {
  const page = html['privacy.html']

  it('names both restricted Gmail scopes, in full', () => {
    // Spec 13, criterion 26. Not pedantry: Google's review of a restricted scope
    // checks that the privacy policy states what the application does with the
    // data. Without this text 5B-1 stays in Testing, where a consumer refresh
    // token expires every seven days.
    expect(page).toContain('https://www.googleapis.com/auth/gmail.readonly')
    expect(page).toContain('https://www.googleapis.com/auth/gmail.send')
  })

  it('says what is read, what is stored, and what is never touched', () => {
    for (const claim of [
      'indirizzi email già presenti',
      'non leggiamo',
      'non trasferiamo',
      'sul tuo server',
      'revocare',
    ]) {
      expect(page.toLowerCase()).toContain(claim.toLowerCase())
    }
  })

  it('names the scopes it deliberately does not ask for', () => {
    // The consent screen shows what is requested; the policy is where "and not
    // these" belongs. gmail.modify would let the product touch the mailbox, and
    // it never does: the state lives in the CRM.
    expect(page).toContain('gmail.modify')
    expect(page).toContain('https://mail.google.com/')
  })

  it('gives a date, so a reviewer can tell when it was last true', () => {
    expect(page).toMatch(/<time datetime="\d{4}-\d{2}-\d{2}">/)
  })
})

describe('termini.html', () => {
  const page = html['termini.html']

  it('is honest that there is no service being provided', () => {
    for (const claim of ['nessuna garanzia', 'software', 'licenza']) {
      expect(page.toLowerCase()).toContain(claim)
    }
    expect(page).not.toMatch(/abbonamento|canone|SLA/i)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run landing/landing-pages.test.ts`
Expected: FAIL — `ENOENT … landing/privacy.html`.

- [ ] **Step 3: Write `apps/web/landing/privacy.html`**

```html
<!doctype html>
<html lang="it">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PigroCRM — Informativa sulla privacy</title>
    <meta
      name="description"
      content="Che dati tratta PigroCRM, dove restano, e cosa fa esattamente con l'accesso a Gmail: gli scope richiesti, quelli non richiesti, e come revocarli."
    />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="PigroCRM — Informativa sulla privacy" />
    <meta
      property="og:description"
      content="I dati restano sul tuo server. Questa pagina dice cosa PigroCRM legge da Gmail, perché, e cosa non tocca mai."
    />
    <meta property="og:locale" content="it_IT" />
    <link rel="stylesheet" href="./landing.css" />
  </head>
  <body class="grain">
    <header class="wrap section" style="padding-block: 1.5rem">
      <nav style="display: flex; align-items: center; justify-content: space-between">
        <a class="quiet-link" href="/" style="padding-left: 0">PigroCRM</a>
        <a class="quiet-link" href="/app/">Accedi</a>
      </nav>
    </header>

    <main class="wrap section">
      <p class="overline">Ultimo aggiornamento <time datetime="2026-08-20">20 agosto 2026</time></p>
      <h1 class="measure">Informativa sulla privacy</h1>

      <div class="measure" style="display: grid; gap: 1.25rem; margin-top: 2rem">
        <h2>Dove stanno i dati</h2>
        <p>
          PigroCRM è un programma che installi tu, sul tuo server. Non esiste un servizio gestito,
          non esiste un nostro database, non esiste un account da creare presso di noi. I dati dei
          tuoi clienti stanno nel tuo PostgreSQL, sul tuo server, e <strong>non trasferiamo</strong>
          nulla a noi né a terzi. Chi tratta quei dati, e con quale base giuridica, sei tu.
        </p>

        <h2>L'accesso a Gmail</h2>
        <p>
          Se scegli di collegare una casella Gmail, PigroCRM chiede a Google due autorizzazioni
          <em>restricted</em>, e chiede esattamente queste:
        </p>
        <ul style="display: grid; gap: 0.75rem">
          <li>
            <code>https://www.googleapis.com/auth/gmail.readonly</code> — per trovare e leggere
            <strong>soltanto</strong> le conversazioni che riguardano gli
            <strong>indirizzi email già presenti</strong> nella tua anagrafica di clienti e persone.
            La selezione avviene lato Google, dentro la query: PigroCRM non elenca la tua casella e
            non la scarica. Di conseguenza <strong>non leggiamo</strong> le newsletter, le ricevute,
            i messaggi personali, né alcun messaggio che non appartenga a una di quelle
            conversazioni. L'unica eccezione, dichiarata: quando un messaggio rilevante appartiene a
            una conversazione, la conversazione viene salvata intera, compresi eventuali
            partecipanti che non conosciamo — perché una conversazione letta a metà è peggio che non
            letta. Quegli indirizzi non entrano nell'anagrafica e non allargano le ricerche
            successive.
          </li>
          <li>
            <code>https://www.googleapis.com/auth/gmail.send</code> — per inviare, dalla tua casella,
            le email che <strong>tu</strong> scrivi e mandi da dentro PigroCRM: l'offerta con il PDF
            allegato, un sollecito di pagamento. Nessuna email parte da sola, mai, e nessun
            assistente AI può inviarne una: il server MCP non espone alcuno strumento di invio.
          </li>
        </ul>
        <p>
          Di ogni messaggio salviamo intestazioni, oggetto e il corpo in <em>testo semplice</em>;
          degli allegati solo nome, tipo e dimensione, <strong>mai</strong> i byte. L'HTML delle
          email non viene conservato né mostrato, perché porta con sé pixel di tracciamento e CSS
          remoto. Puoi disattivare del tutto il salvataggio dei corpi. Tutto resta
          <strong>sul tuo server</strong>: i dati di Gmail non passano da noi, non vengono usati per
          addestrare alcun modello, non vengono venduti e non vengono condivisi.
        </p>

        <h2>Cosa non chiediamo</h2>
        <p>
          Non chiediamo <code>gmail.modify</code>: PigroCRM non etichetta, non archivia e non sposta
          nulla nella tua casella. Non chiediamo <code>gmail.compose</code>: le bozze vivono nel CRM,
          non in Gmail. Non chiediamo <code>https://mail.google.com/</code>, che darebbe accesso a
          tutto, cancellazione compresa. Non chiediamo Calendar né Contacts.
        </p>

        <h2>Come si toglie</h2>
        <p>
          Puoi <strong>revocare</strong> l'accesso in qualsiasi momento, in due modi indipendenti: da
          Impostazioni → Gmail dentro PigroCRM, oppure dalla pagina delle autorizzazioni del tuo
          account Google. Alla disconnessione PigroCRM ti chiede se cancellare anche i messaggi già
          salvati, e non lo fa da solo: cancellare la corrispondenza di un cliente perché è scaduto
          un token sarebbe un danno, non un'attenzione.
        </p>

        <h2>Contatti</h2>
        <p>
          Per qualunque domanda su questa informativa:
          <a class="quiet-link" href="mailto:privacy@pigrocrm.it" style="padding-left: 0"
            >privacy@pigrocrm.it</a
          >.
        </p>
      </div>

      <footer class="hairline" style="margin-top: 3rem; padding-top: 2rem; font-size: 0.9375rem">
        <a class="quiet-link" href="/" style="padding-left: 0">Home</a>
        <a class="quiet-link" href="/termini">Termini</a>
      </footer>
    </main>

    <script src="./reveal.js" defer></script>
  </body>
</html>
```

**Before deploying, replace `privacy@pigrocrm.it` and the GitHub URL in `index.html` with the real address and repository.** Google's verification checks that the contact route works; an unreachable mailbox fails the review. These two strings are the only values in 5A that must come from outside this plan — everything else is decided here.

- [ ] **Step 4: Write `apps/web/landing/termini.html`**

```html
<!doctype html>
<html lang="it">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PigroCRM — Termini di utilizzo</title>
    <meta
      name="description"
      content="PigroCRM è software che installi tu: la licenza, l'assenza di garanzie, e chi risponde di cosa quando il server è il tuo."
    />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="PigroCRM — Termini di utilizzo" />
    <meta
      property="og:description"
      content="Non è un abbonamento: è un programma. Cosa concede la licenza e cosa non garantisce nessuno."
    />
    <meta property="og:locale" content="it_IT" />
    <link rel="stylesheet" href="./landing.css" />
  </head>
  <body class="grain">
    <header class="wrap section" style="padding-block: 1.5rem">
      <nav style="display: flex; align-items: center; justify-content: space-between">
        <a class="quiet-link" href="/" style="padding-left: 0">PigroCRM</a>
        <a class="quiet-link" href="/app/">Accedi</a>
      </nav>
    </header>

    <main class="wrap section">
      <p class="overline">Ultimo aggiornamento <time datetime="2026-08-20">20 agosto 2026</time></p>
      <h1 class="measure">Termini di utilizzo</h1>

      <div class="measure" style="display: grid; gap: 1.25rem; margin-top: 2rem">
        <h2>Cos'è che stai usando</h2>
        <p>
          PigroCRM è <strong>software</strong> che scarichi e installi sul tuo server. Non è un
          servizio: non c'è un abbonamento, non c'è un canone, non c'è un livello di servizio da
          rispettare, e non c'è nessuno che possa spegnerlo al posto tuo.
        </p>

        <h2>Licenza</h2>
        <p>
          Il codice è distribuito sotto la <strong>licenza</strong> indicata nel file
          <code>LICENSE</code> del repository, che è l'unico testo che fa fede. Puoi eseguirlo,
          modificarlo e ridistribuirlo nei termini che quella licenza concede.
        </p>

        <h2>Garanzie</h2>
        <p>
          <strong>Nessuna garanzia.</strong> Il software è fornito «così com'è», senza garanzia
          esplicita o implicita di funzionamento, idoneità a uno scopo particolare o assenza di
          difetti. In particolare: i calcoli fiscali, i documenti generati e le fatture prodotte
          restano una tua responsabilità e vanno verificati. Nessun autore risponde di perdite di
          dati, mancati incassi o danni derivanti dall'uso.
        </p>

        <h2>I tuoi dati, la tua responsabilità</h2>
        <p>
          Backup, aggiornamenti, TLS, credenziali e conservazione dei dati stanno sul tuo server e
          sono a tuo carico. Vale lo stesso per gli obblighi che ti riguardano come titolare del
          trattamento dei dati dei tuoi clienti. Cosa PigroCRM tratta, e come, è descritto
          nell'<a class="quiet-link" href="/privacy" style="padding-left: 0"
            >informativa sulla privacy</a
          >.
        </p>

        <h2>Integrazioni di terze parti</h2>
        <p>
          Se colleghi Gmail o Google Drive valgono anche i termini di Google, e le autorizzazioni che
          concedi puoi revocarle quando vuoi. PigroCRM non è affiliata a Google.
        </p>
      </div>

      <footer class="hairline" style="margin-top: 3rem; padding-top: 2rem; font-size: 0.9375rem">
        <a class="quiet-link" href="/" style="padding-left: 0">Home</a>
        <a class="quiet-link" href="/privacy">Privacy</a>
      </footer>
    </main>

    <script src="./reveal.js" defer></script>
  </body>
</html>
```

- [ ] **Step 5: Run the whole page suite and watch it pass**

Run: `cd apps/web && pnpm vitest run landing/`
Expected: PASS. The shared block now runs five assertions against each of three pages, plus the index, privacy and termini blocks.

- [ ] **Step 6: Commit**

```bash
git add apps/web/landing
git commit -m "feat(landing): the privacy policy Google's verification actually reads"
```

---

### Task A5: `reveal.js` — the motion, and the page that works without it

**Files:**
- Create: `apps/web/landing/reveal.js`
- Create: `apps/web/landing/reveal.test.ts`

**Interfaces:**
- Consumes: `.rise` and `.rise[data-hidden]` from Task A2; the three pages from A3 and A4, each of which already ends with `<script src="./reveal.js" defer></script>`.
- Produces: `apps/web/landing/reveal.js`, and the exported-for-test entry point `window.__pigroReveal` — a function taking the document so the unit test can drive it against jsdom without a bundler.

- [ ] **Step 1: Write the failing test**

`apps/web/landing/reveal.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const source = readFileSync(join(__dirname, 'reveal.js'), 'utf-8')

interface RevealWindow {
  __pigroReveal?: (doc: Document) => void
}

/** Evaluates reveal.js the way the browser does: as a classic script that assigns
 *  onto `window`. No bundler and no import, because the shipped file has none. */
function load(): (doc: Document) => void {
  new Function('window', 'document', 'IntersectionObserver', source)(
    window,
    document,
    window.IntersectionObserver,
  )
  const entry = (window as unknown as RevealWindow).__pigroReveal
  if (!entry) throw new Error('reveal.js did not expose window.__pigroReveal')
  return entry
}

describe('reveal.js', () => {
  beforeEach(() => {
    document.body.innerHTML = '<p class="rise">uno</p><p class="rise">due</p><p>tre</p>'
    delete (window as unknown as RevealWindow).__pigroReveal
  })

  it('is small enough to be worth having', () => {
    // "roughly a kilobyte" from spec 9.4, made checkable. The whole page budget is
    // 40 KB; a reveal script that grew past 2 KB stopped being this script.
    expect(Buffer.byteLength(source, 'utf-8')).toBeLessThan(2048)
  })

  it('makes no request and touches no global other than window and document', () => {
    expect(source).not.toMatch(/fetch\(|XMLHttpRequest|import\s|require\(/)
    expect(source).not.toMatch(/localStorage|sessionStorage|document\.cookie|navigator\.sendBeacon/)
  })

  it('hides the elements it is about to reveal, and only those', () => {
    load()(document)
    const risen = [...document.querySelectorAll('.rise')]
    expect(risen.every((element) => element.hasAttribute('data-hidden'))).toBe(true)
    expect(document.querySelector('p:not(.rise)')?.hasAttribute('data-hidden')).toBe(false)
  })

  it('numbers them so the CSS can stagger them', () => {
    load()(document)
    const risen = [...document.querySelectorAll<HTMLElement>('.rise')]
    expect(risen[0]?.style.getPropertyValue('--rise-index')).toBe('0')
    expect(risen[1]?.style.getPropertyValue('--rise-index')).toBe('1')
  })

  it('reveals an element when the observer reports it visible, and stops watching it', () => {
    const unobserve = vi.fn()
    let notify: ((entries: { target: Element; isIntersecting: boolean }[]) => void) | undefined
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(callback: (entries: { target: Element; isIntersecting: boolean }[]) => void) {
          notify = callback
        }
        observe = vi.fn()
        unobserve = unobserve
        disconnect = vi.fn()
      },
    )

    load()(document)
    const first = document.querySelector('.rise')!
    notify?.([{ target: first, isIntersecting: true }])

    expect(first.hasAttribute('data-hidden')).toBe(false)
    expect(unobserve).toHaveBeenCalledWith(first)
    vi.unstubAllGlobals()
  })

  it('leaves everything visible when IntersectionObserver does not exist', () => {
    // The rule that matters, restated as a test: no browser, and no failure mode,
    // may produce a blank page. If the mechanism is missing, so is the animation --
    // never the content.
    vi.stubGlobal('IntersectionObserver', undefined)
    load()(document)
    expect([...document.querySelectorAll('.rise')].some((e) => e.hasAttribute('data-hidden'))).toBe(
      false,
    )
    vi.unstubAllGlobals()
  })

  it('does not hide anything when the reader asked for reduced motion', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
    load()(document)
    expect([...document.querySelectorAll('.rise')].some((e) => e.hasAttribute('data-hidden'))).toBe(
      false,
    )
    vi.unstubAllGlobals()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run landing/reveal.test.ts`
Expected: FAIL — `ENOENT … landing/reveal.js`.

- [ ] **Step 3: Write the script**

`apps/web/landing/reveal.js`:

```js
/* The whole of the landing page's JavaScript.
 *
 * The rule it exists to obey: the initial state is VISIBLE. This script adds
 * [data-hidden] and then takes it away again. The opposite arrangement -- CSS that
 * hides, JavaScript that reveals -- gives a blank page every time the script does
 * not run: an old browser, a blocked file, a syntax error, a CSP. Here, if anything
 * at all goes wrong, the reader loses an animation and keeps the page.
 *
 * Everything else follows from that: reduced motion means "do not hide", no
 * IntersectionObserver means "do not hide", nothing observed means "do not hide".
 */
;(function () {
  function reveal(doc) {
    var reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || typeof IntersectionObserver !== 'function') return

    var targets = doc.querySelectorAll('.rise')
    if (targets.length === 0) return

    var observer = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i += 1) {
          if (!entries[i].isIntersecting) continue
          entries[i].target.removeAttribute('data-hidden')
          // Once shown, stop watching: the animation runs once, and an observer
          // left attached keeps firing on every scroll for the life of the page.
          observer.unobserve(entries[i].target)
        }
      },
      { rootMargin: '0px 0px -10% 0px', threshold: 0.01 },
    )

    for (var index = 0; index < targets.length; index += 1) {
      // The stagger lives in CSS (transition-delay reads --rise-index); the script
      // only supplies the ordinal. Keeping the timing in the stylesheet is what
      // lets prefers-reduced-motion cancel it without the script knowing.
      targets[index].style.setProperty('--rise-index', String(index % 6))
      targets[index].setAttribute('data-hidden', '')
      observer.observe(targets[index])
    }
  }

  window.__pigroReveal = reveal
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      reveal(document)
    })
  } else {
    reveal(document)
  }
})()
```

Note on `--rise-index` and `index % 6`: the stagger must reset, or the thirtieth element on the page waits 1.8 seconds after entering the viewport. Six is the largest group that appears together in any one section of `index.html`.

- [ ] **Step 4: Run it and watch it pass**

Run: `cd apps/web && pnpm vitest run landing/reveal.test.ts`
Expected: PASS (7 tests).

**Note on the test's assertion about `--rise-index`:** it checks `'0'` and `'1'` for the first two `.rise` elements, which the `% 6` leaves unchanged. Do not "simplify" the test by dropping the modulo from the implementation.

- [ ] **Step 5: Commit**

```bash
git add apps/web/landing
git commit -m "feat(landing): reveal on scroll, arranged so a failed script costs nothing"
```

---

### Task A6: The landing build, and the transfer budget as a test

**Files:**
- Create: `apps/web/vite.landing.config.ts`
- Modify: `apps/web/package.json` — a `build:landing` script, and `@axe-core/playwright` as a dev dependency
- Modify: `apps/web/playwright.config.ts` — a second project and a second `webServer`
- Modify: `apps/web/.gitignore` — `dist-landing`
- Modify: `.dockerignore` — `apps/web/dist-landing/`
- Create: `apps/web/e2e/landing.spec.ts`

**Interfaces:**
- Consumes: `palettePlugin()` from Task A1; the three HTML files from A3 and A4; `reveal.js` from A5.
- Produces:
  - `apps/web/dist-landing/` containing `index.html`, `privacy.html`, `termini.html`, one hashed CSS, one hashed JS and one hashed woff2.
  - `pnpm build:landing`.
  - A Playwright project named `landing` on `http://localhost:4173`, so `e2e/landing.spec.ts` runs against a real static server while the existing `chromium` project keeps running against `pnpm dev`.

- [ ] **Step 1: Write the failing E2E spec**

`apps/web/e2e/landing.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

const PAGES = ['/', '/privacy', '/termini'] as const
const BUDGET_BYTES = 40 * 1024

test.describe('the landing page', () => {
  for (const path of PAGES) {
    test(`${path} asks nothing of any other host`, async ({ page }) => {
      const foreign: string[] = []
      page.on('request', (request) => {
        const host = new URL(request.url()).host
        if (host !== new URL(page.url() || 'http://localhost:4173').host) foreign.push(request.url())
      })
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      // This is what makes "no analytics, no third-party script" a verification
      // rather than a promise.
      expect(foreign).toEqual([])
    })
  }

  test('loads cold under 40 KB, excluding the shared woff2', async ({ page }) => {
    let bytes = 0
    page.on('requestfinished', async (request) => {
      if (request.url().endsWith('.woff2')) return
      const sizes = await request.sizes()
      bytes += sizes.responseBodySize + sizes.responseHeadersSize
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    expect(bytes, `${bytes} bytes transferred`).toBeLessThan(BUDGET_BYTES)
  })

  test('shares exactly one font file with the app, from its own origin', async ({ page }) => {
    const fonts: string[] = []
    page.on('request', (request) => {
      if (request.url().endsWith('.woff2')) fonts.push(request.url())
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    expect(fonts).toHaveLength(1)
    expect(fonts[0]).toContain('outfit-variable-latin')
  })

  test.describe('with JavaScript disabled', () => {
    test.use({ javaScriptEnabled: false })

    for (const path of PAGES) {
      test(`${path} shows all of its content and all of its links work`, async ({ page }) => {
        await page.goto(path)
        // Every .rise element must be visible: the hidden state only ever exists
        // because a script put it there.
        const risen = page.locator('.rise')
        const count = await risen.count()
        for (let index = 0; index < count; index += 1) {
          await expect(risen.nth(index)).toBeVisible()
        }
        await expect(page.locator('h1')).toBeVisible()
        for (const link of await page.locator('a[href^="/"]').all()) {
          const href = await link.getAttribute('href')
          expect(href).toBeTruthy()
          const response = await page.request.get(href!)
          expect(response.status(), `${href} from ${path}`).toBeLessThan(400)
        }
      })
    }
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm exec playwright test --project=landing`
Expected: FAIL — `Project(s) "landing" not found`.

- [ ] **Step 3: Write the landing build config**

`apps/web/vite.landing.config.ts`:

```ts
import type { IncomingMessage, ServerResponse } from 'node:http'
import path from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import { palettePlugin } from './landing/palette-plugin'

/**
 * nginx maps `/privacy` to `/privacy.html` in production (deploy/nginx/spa.conf).
 * Vite's dev and preview servers do not, so an extensionless link that works in
 * production 404s locally -- and the E2E suite would then have to navigate to paths
 * no visitor ever uses, which is a suite that tests something else. This makes all
 * three agree.
 */
function extensionlessHtml(): Plugin {
  function rewrite(req: IncomingMessage, _res: ServerResponse, next: () => void): void {
    const [pathname = '/', query] = (req.url ?? '/').split('?')
    if (pathname !== '/' && !pathname.includes('.')) {
      req.url = `${pathname}.html${query ? `?${query}` : ''}`
    }
    next()
  }
  return {
    name: 'pigrocrm-landing-extensionless-html',
    configureServer(server) {
      server.middlewares.use(rewrite)
    },
    configurePreviewServer(server) {
      server.middlewares.use(rewrite)
    },
  }
}

export default defineConfig({
  root: path.resolve(__dirname, 'landing'),
  // Absolute, not './': nginx serves these three files from the document root, and
  // /privacy is one path segment deep only by URL, not by directory. A relative
  // base would still work here, but it would break the moment a page moved.
  base: '/',
  // No React, no Tailwind, no TanStack router plugin. That absence is the
  // requirement, not an omission: spec 9.4 exists so the landing does not drag the
  // application's bundle behind it.
  plugins: [palettePlugin(), extensionlessHtml()],
  build: {
    outDir: path.resolve(__dirname, 'dist-landing'),
    emptyOutDir: true,
    // The pages have no shared JS chunk to speak of, and inlining the ~1 KB of
    // reveal.js would put it inside three HTML files instead of one cacheable one.
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, 'landing/index.html'),
        privacy: path.resolve(__dirname, 'landing/privacy.html'),
        termini: path.resolve(__dirname, 'landing/termini.html'),
      },
    },
  },
  preview: { port: 4173, strictPort: true },
})
```

- [ ] **Step 4: Wire the scripts and the ignore files**

`apps/web/package.json`, in `"scripts"`:

```json
    "build:landing": "vite build --config vite.landing.config.ts",
    "preview:landing": "vite preview --config vite.landing.config.ts",
```

Then:

```bash
cd apps/web && pnpm add -D @axe-core/playwright
```

Pin whatever that resolves into `apps/web/package.json` in this same commit, the convention this repo already uses for `lucide-react`.

`apps/web/.gitignore` gains one line: `dist-landing`.

`/.dockerignore` gains one line, beside the existing `apps/web/dist/`: `apps/web/dist-landing/`. Same reason the comment at the top of that file gives for `dist/` — the image builds its own, and copying the host's would shadow it.

- [ ] **Step 5: Add the Playwright project**

`apps/web/playwright.config.ts` — replace the single `use`/`projects`/`webServer` triple with:

```ts
  use: { trace: 'on-first-retry' },
  expect: { timeout: 8_000 },
  projects: [
    {
      name: 'chromium',
      testIgnore: /landing.*\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:5173' },
    },
    {
      // The landing is a separate build served by a static server, so it needs its
      // own origin. Splitting by project rather than by baseURL override keeps the
      // app suite pointed at `pnpm dev` -- which now serves under /app/ -- without
      // either suite knowing about the other.
      name: 'landing',
      testMatch: /landing\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:4173' },
    },
  ],
  webServer: [
    {
      command: 'pnpm dev',
      url: 'http://localhost:5173/app/',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // `preview` serves dist-landing, so the build has to have happened. Chaining
      // it here means the E2E command stays the one documented command.
      command: 'pnpm build:landing && pnpm preview:landing',
      url: 'http://localhost:4173/',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
```

`e2e/landing-served.spec.ts` (Task A7) is matched by neither project's pattern on purpose — it runs only against the compose stack, through its own config in A7.

- [ ] **Step 6: Build once by hand and read the output**

Run: `cd apps/web && pnpm build:landing && ls -la dist-landing dist-landing/assets`
Expected: three `.html` files, one hashed `.css`, one hashed `.js`, one hashed `.woff2`. Check the injected palette actually landed:

Run: `grep -c -- '--color-watermelon-strong' apps/web/dist-landing/assets/*.css`
Expected: `1`. If it is `0`, `palettePlugin`'s `id` check did not match — log `id` in the `transform` hook and fix the suffix test rather than hardcoding the palette.

- [ ] **Step 7: Run the E2E spec and watch it pass**

Run: `cd apps/web && pnpm exec playwright test --project=landing`
Expected: PASS (9 tests: three no-foreign-host, budget, font, three no-JS). If the budget test fails, the number it prints is the real one — reduce the page, do not raise `BUDGET_BYTES`.

- [ ] **Step 8: Commit**

```bash
git add apps/web/vite.landing.config.ts apps/web/package.json apps/web/pnpm-lock.yaml \
        apps/web/playwright.config.ts apps/web/.gitignore apps/web/e2e/landing.spec.ts .dockerignore
git commit -m "feat(landing): a separate build, with the 40 KB budget as a test"
```

---

### Task A7: Move the app under `/app/` and give `/` to the landing

The three shipped contradictions from spec §10, resolved together, because resolving them separately leaves the tree in a state where `/` 404s.

**Files:**
- Delete: `apps/web/src/routes/index.tsx`
- Move: `apps/web/src/routes/login.tsx` → `apps/web/src/routes/app/login.tsx`
- Modify: `apps/web/vite.config.ts` (add `base: '/app/'`)
- Modify: `apps/web/src/routes/app.tsx:12` (`navigate({ to: '/login' })` → `'/app/login'`)
- Modify: `apps/web/e2e/helpers.ts:16`, `apps/web/e2e/auth.spec.ts:15`, `apps/web/e2e/auth.spec.ts:25` (`page.goto('/login')` → `'/app/login'`)
- Modify: `apps/web/e2e/auth.spec.ts:11,21,34` and `apps/web/e2e/roles.spec.ts:35` (tighten the `/\/login/` assertions)
- Modify: `deploy/nginx/spa.conf`
- Modify: `Dockerfile.web`
- Create: `apps/web/e2e/landing-served.spec.ts`
- Create: `apps/web/playwright.compose.config.ts`
- Create: `apps/web/scripts/e2e-compose.sh`

**Interfaces:**
- Consumes: `dist-landing` from Task A6.
- Produces: `/` → the landing, `/privacy` and `/termini` → 200, `/app/…` → the SPA with deep-link refresh intact, `/login` → 302 to `/app/login`. The route path `'/app/login'` replaces `'/login'` in TanStack Router's generated `FileRoutesByTo` union, so every `to=`/`goto` referring to the old path is a type error rather than a runtime 404.

- [ ] **Step 1: Write the failing served-stack spec**

`apps/web/e2e/landing-served.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

/**
 * Runs against the real compose stack (nginx + api + db), never against the Vite
 * dev server. Spec 13, criterion 24: the routing this task changes lives in
 * deploy/nginx/spa.conf, which the dev server does not use at all -- so a suite
 * that only ever hits :5173 would pass while production 404s. Driven by
 * apps/web/scripts/e2e-compose.sh through playwright.compose.config.ts.
 */
test.describe('the served stack', () => {
  test('/ serves the landing, not the application', async ({ page }) => {
    const response = await page.goto('/')
    expect(response?.status()).toBe(200)
    await expect(page.locator('h1')).toHaveText('Il CRM che lavora al posto tuo.')
    await expect(page.locator('#root')).toHaveCount(0)
  })

  test.each(['/privacy', '/termini'])('%s answers 200', async (path) => {
    const response = await page.goto(path)
    expect(response?.status()).toBe(200)
  })

  test('/app/ serves the SPA', async ({ page }) => {
    await page.goto('/app/')
    await expect(page.locator('#root')).toHaveCount(1)
  })

  test('/app redirects to /app/, so the prefix location matches', async ({ page }) => {
    // Without `location = /app { return 302 /app/; }` the bare path does not enter
    // `location ^~ /app/` at all and falls through to the landing's `try_files`.
    await page.goto('/app')
    expect(new URL(page.url()).pathname).toBe('/app/')
  })

  test('a refresh on a deep link still serves the SPA shell', async ({ page }) => {
    const response = await page.goto('/app/clienti/00000000-0000-7000-8000-000000000000')
    expect(response?.status()).toBe(200)
    await expect(page.locator('#root')).toHaveCount(1)
  })

  test('the old /login link does not die', async ({ page }) => {
    await page.goto('/login')
    expect(new URL(page.url()).pathname).toBe('/app/login')
  })

  test('/health still reaches the API, unchanged by any of this', async ({ page }) => {
    const response = await page.request.get('/health')
    expect(response.status()).toBe(200)
    expect(await response.json()).toEqual({ status: 'ok' })
  })
})
```

Note: `test.each` inside `test.describe` needs the fixture, so write that one as a plain loop if the Playwright version in use does not accept it:

```ts
  for (const path of ['/privacy', '/termini']) {
    test(`${path} answers 200`, async ({ page }) => {
      expect((await page.goto(path))?.status()).toBe(200)
    })
  }
```

Use the loop form. It is what the rest of this repo's specs already do.

- [ ] **Step 2: Write the compose harness**

`apps/web/playwright.compose.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: /landing-served\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  // The compose file publishes web on 127.0.0.1:8080 (docker-compose.yml).
  use: {
    baseURL: process.env.PIGROCRM_COMPOSE_URL ?? 'http://127.0.0.1:8080',
    trace: 'on-first-retry',
    ...devices['Desktop Chrome'],
  },
  expect: { timeout: 8_000 },
  // No webServer: this config deliberately does not own the stack. e2e-compose.sh
  // brings it up and tears it down, so a half-built image fails the script rather
  // than timing out inside Playwright with no logs.
})
```

`apps/web/scripts/e2e-compose.sh`:

```bash
#!/usr/bin/env bash
# Verifies the routing this slice changes against the real nginx, not the Vite dev
# server. deploy/nginx/spa.conf is not exercised by `pnpm dev` at all, so `/`,
# `/privacy`, `/termini`, `/app` and the `/login` redirect can only be proven here.
#
#   apps/web/scripts/e2e-compose.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

cleanup() {
  docker compose down -v
}
trap cleanup EXIT

# A pre-existing volume keeps its original POSTGRES_PASSWORD (residuo B6), so a
# clean start has to be an explicitly clean one.
docker compose down -v
docker compose up -d --build

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:8080/health >/dev/null

cd "$REPO_ROOT/apps/web"
pnpm exec playwright test --config playwright.compose.config.ts
```

Then `chmod +x apps/web/scripts/e2e-compose.sh` and add `"test:e2e:compose": "bash scripts/e2e-compose.sh"` to `apps/web/package.json`.

- [ ] **Step 3: Run it and watch it fail**

Run: `apps/web/scripts/e2e-compose.sh`
Expected: FAIL — `/` still serves the SPA (`#root` present, `h1` absent), `/privacy` 404s, `/login` does not redirect.

- [ ] **Step 4: Change nginx**

In `deploy/nginx/spa.conf`, replace the `location / { try_files $uri $uri/ /index.html; }` block — and its comment, which is now about a fallback that no longer exists — with:

```nginx
    # The landing page owns the document root; the SPA lives under /app/. Ordering
    # note: these are exact-match and prefix locations, so nginx's own precedence
    # rules apply and the block order in this file does not matter -- but the
    # `= /app` redirect does, because without it the bare path never enters the
    # `^~ /app/` prefix block and falls through to the landing's try_files below.
    location = /            { try_files /index.html =404; }
    location = /privacy     { try_files /privacy.html =404; }
    location = /termini     { try_files /termini.html =404; }
    location = /app         { return 302 /app/; }
    location = /login       { return 302 /app/login; }   # old links do not die

    # Client-side routing, now scoped: an unknown path under /app/ is a route, not a
    # missing file, so a refresh on a deep link like /app/clienti/<uuid> re-serves
    # the SPA shell. Scoping it to `^~ /app/` is what stops that fallback from also
    # swallowing `/`, which is the whole reason this block changed.
    location ^~ /app/       { try_files $uri /app/index.html; }

    # Everything else the landing build emitted (hashed CSS, JS and the woff2 under
    # /assets/), and nothing invented: a bare 404 rather than an SPA fallback.
    location / {
        try_files $uri =404;
    }
```

The `resolver`, `/api/` and `= /health` blocks are unchanged. `/health` **must** stay exactly as it is — a broken Gmail credential is not a broken deploy, and confusing the two trains the operator to ignore the probe.

- [ ] **Step 5: Change the image build**

`Dockerfile.web` — replace the single build and single copy with:

```dockerfile
COPY apps/web ./
RUN pnpm build && pnpm build:landing

FROM nginx:1.27-alpine
# The landing at the document root, the SPA one directory down. Two builds, one
# origin: one TLS certificate, one nginx, one deploy, and an "Accedi" link that
# needs no cross-origin thought.
COPY --from=build /app/dist-landing /usr/share/nginx/html
COPY --from=build /app/dist /usr/share/nginx/html/app
COPY deploy/nginx/spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

Order matters: `dist-landing` first, `dist` into `app/` second. Reversed, the second copy would land beside the first instead of under it.

- [ ] **Step 6: Change the app's base and its routes**

`apps/web/vite.config.ts` — add to the `defineConfig` object, above `plugins`:

```ts
  // The SPA is served from /usr/share/nginx/html/app (Dockerfile.web) and matched by
  // `location ^~ /app/` (deploy/nginx/spa.conf). Without this, every emitted asset
  // URL is /assets/... and 404s under the new prefix. The API client is unaffected:
  // lib/api.ts uses `baseUrl: ''` with full `/api/...` keys, so its requests are
  // absolute-from-root and do not inherit this base.
  base: '/app/',
```

Then:

```bash
git rm apps/web/src/routes/index.tsx
git mv apps/web/src/routes/login.tsx apps/web/src/routes/app/login.tsx
```

In the moved file, change the last line from `createFileRoute('/login')` to `createFileRoute('/app/login')`.

`apps/web/src/routes/app.tsx:12` — `if (!isLoading && !user) void navigate({ to: '/login' })` becomes `{ to: '/app/login' }`.

`apps/web/src/routes/app/login.tsx` keeps `await navigate({ to: '/app' })` on success: `/app` is still a real route (`routes/app.tsx`), and it is what `AppShell`'s Dashboard link already points at.

Deleting `routes/index.tsx` removes `'/'` from the generated union, so any remaining `to: '/'` is a type error. There are none today — verified: the only reference to that route was its own redirect.

- [ ] **Step 7: Update the E2E paths, and tighten the assertions that would pass by accident**

Three navigations move:

- `apps/web/e2e/helpers.ts:16` — `await page.goto('/login')` → `await page.goto('/app/login')`
- `apps/web/e2e/auth.spec.ts:15` and `:25` — the same change

Four assertions are `/\/login/`, which still matches `/app/login` and would therefore pass without proving anything. Make them exact:

- `apps/web/e2e/auth.spec.ts:11`, `:21`, `:34` — `await expect(page).toHaveURL(/\/login/)` → `await expect(page).toHaveURL(/\/app\/login$/)`
- `apps/web/e2e/roles.spec.ts:35` — the same change
- `apps/web/e2e/helpers.ts:20` and `apps/web/e2e/auth.spec.ts:30` — `toHaveURL(/\/app/)` → `toHaveURL(/\/app(\/|$)/)`, so it cannot be satisfied by `/app/login` when the test means "logged in"

Every other `page.goto` in `e2e/` already uses an `/app/…` path and needs no change — 24 of the 27 navigations. `custom-fields.spec.ts:112`'s `new URL(page.url()).pathname.split('/').pop()` still yields the UUID, because the id is still the last segment.

- [ ] **Step 8: Run all three suites**

```bash
cd apps/web && pnpm vitest run && pnpm build && pnpm build:landing && pnpm tsc --noEmit
cd apps/web && pnpm test:e2e
apps/web/scripts/e2e-compose.sh
```

Expected: PASS throughout. The `landing-served` suite is the one that was failing in Step 3; it is now the proof that `/` and `/app/…` coexist.

- [ ] **Step 9: Commit**

```bash
git add -A apps/web deploy/nginx/spa.conf Dockerfile.web
git commit -m "feat(landing): / belongs to the landing, the app moves under /app/"
```

---

### Task A8: Accessibility, verified with the grain switched on

**Files:**
- Modify: `apps/web/e2e/landing.spec.ts` (append)

**Interfaces:**
- Consumes: `@axe-core/playwright` from Task A6; the built `dist-landing` served by the `landing` Playwright project.
- Produces: nothing other pages consume. This is the gate.

- [ ] **Step 1: Write the failing test**

Append to `apps/web/e2e/landing.spec.ts`:

```ts
import AxeBuilder from '@axe-core/playwright'

test.describe('accessibility', () => {
  for (const path of PAGES) {
    test(`${path} has zero axe violations, with the grain layer active`, async ({ page }) => {
      await page.goto(path, { waitUntil: 'networkidle' })
      // With the grain active, deliberately. The hatching is painted between the
      // background and the text, so a run with it disabled would measure a page
      // nobody sees. Spec 13, criterion 20.
      await expect(page.locator('body.grain')).toBeVisible()
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()
      expect(
        results.violations.map((violation) => `${violation.id}: ${violation.help}`),
      ).toEqual([])
    })
  }

  test('the call to action is the accessible Watermelon, never the raw one', async ({ page }) => {
    await page.goto('/')
    // Computed, not asserted against the stylesheet: landing-tokens.test.ts already
    // checks the source. This checks what the browser actually resolved the
    // color-mix and the var() chain to, which is the only thing a reader sees.
    const background = await page
      .locator('.cta')
      .first()
      .evaluate((element) => getComputedStyle(element).backgroundColor)
    expect(background).toBe('rgb(229, 19, 62)') // #e5133e, 4.673:1 under white
    const colour = await page
      .locator('.cta')
      .first()
      .evaluate((element) => getComputedStyle(element).color)
    expect(colour).toBe('rgb(255, 255, 255)')
  })

  test('the grain disappears when the reader asks for more contrast', async ({ browser }) => {
    const context = await browser.newContext({ contrast: 'more' })
    const page = await context.newPage()
    await page.goto('/')
    const shown = await page.evaluate(
      () => getComputedStyle(document.body, '::after').display,
    )
    expect(shown).toBe('none')
    await context.close()
  })

  test('every page declares Italian, so a screen reader reads it as Italian', async ({ page }) => {
    for (const path of PAGES) {
      await page.goto(path)
      await expect(page.locator('html')).toHaveAttribute('lang', 'it')
    }
  })
})
```

If the installed `@playwright/test` does not support the `contrast` context option, replace that one test with `page.emulateMedia({ contrast: 'more' })` before the `goto`; if neither exists in the pinned version, drop the runtime check and rely on `landing-style.test.ts`'s source assertion, and say so in a comment rather than deleting the requirement silently.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm exec playwright test --project=landing -g accessibility`
Expected: FAIL — `Cannot find module '@axe-core/playwright'` if Task A6's install was skipped; otherwise it runs and reports whatever real violations exist.

- [ ] **Step 3: Fix what axe reports, in the markup and the stylesheet**

Do not add ARIA to silence a rule. The likely findings and their real fixes:

- `landmark-one-main` / `region` — every block of content must sit inside `<main>`, `<header>`, `<footer>` or `<nav>`. `index.html` already does; check `privacy.html` and `termini.html` for a stray sibling of `<main>`.
- `heading-order` — the `<h2>`s in the card grid follow the page `<h1>` directly, which is correct; a section that introduces an `<h3>` without an `<h2>` above it is not.
- `color-contrast` — should not fire; the pairs are computed in `landing-tokens.test.ts`. If it does, axe is measuring a pair that test does not cover, which means the stylesheet grew a colour combination outside the token set. Add the pair to `landing-tokens.test.ts` and fix the colour, not the axe run.
- `link-name` — `.quiet-link` elements must carry text, never only an icon.

- [ ] **Step 4: Run it and watch it pass**

Run: `cd apps/web && pnpm exec playwright test --project=landing`
Expected: PASS, all of `landing.spec.ts`.

- [ ] **Step 5: Add both landing suites to CI**

`.github/workflows/ci-deploy.yml`, `frontend` job, after `pnpm build`: add `pnpm build:landing`. In the `e2e` job, after `apps/web/scripts/e2e.sh`, add `apps/web/scripts/e2e-compose.sh`. The compose run needs Docker, which the GitHub-hosted Ubuntu runner has.

- [ ] **Step 6: Commit**

```bash
git add apps/web/e2e/landing.spec.ts .github/workflows/ci-deploy.yml
git commit -m "test(landing): axe on all three pages, with the grain switched on"
```

---

**5A is done here. Before starting 5B-1:** deploy, confirm `https://<domain>/`, `/privacy` and `/termini` are publicly reachable, put the real contact address in `privacy.html`, then create the Google Cloud OAuth client, set its homepage and privacy-policy URLs to those pages, and **submit it for verification**. Verification is calendar time. Build 5B-1 while it runs, and expect the 7-day refresh-token expiry until it clears — Task B1-12 makes that expiry visible rather than mysterious.

---
