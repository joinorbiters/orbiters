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

# 5B-1 — OAuth and synchronisation

**What must exist before 5B-1 can start.** All four, and the first two are not negotiable:

1. **5A deployed**, with `/`, `/privacy` and `/termini` publicly reachable on the verified domain, and the OAuth client **submitted for verification**. Without it the client stays in Testing and a consumer refresh token expires every 7 days — Google's own behaviour, not something this plan can code around.
2. **The R10 + R5 minimum cut, closed.** PAT scopes with `gmail:*` off by default; a mandatory `expires_at` on any token carrying a `gmail:*` scope; an `activities` row on token create and on token revoke. See *The blocking prerequisite outside this slice* above. **This plan consumes that work in Task B1-14 and does not implement it.** If `gmail:read` does not exist as a PAT scope when B1-14 is reached, stop and close the prerequisite — do not invent a local substitute.
3. Slice 1 in `main` (it is) and slice 2 complete (it is: `documents/`, `templates/`, `render/`, `storage/`, `emitter/` are all in the tree with their tests green).
4. A Google Cloud project with an OAuth client of type *Web application*, its single authorised redirect URI set to `{PIGROCRM_PUBLIC_URL}/api/gmail/oauth/callback`. Google compares that string exactly.

**What 5B-1 does not need:** slice 3. Nothing in 5B-1 touches an invoice.

**Tasks:** 17. Migrations land at revisions `0004` (B1-1), `0005` (B1-3) and `0006` (B1-8).

---

### Task B1-1: The address roster, and the index the relevance query needs

Relevance is decided by the data. That makes the roster query the hottest query in the slice, and it currently sequential-scans half of what it reads.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/customers/models.py:36`
- Create: `packages/core/src/pigrocrm/core/gmail/__init__.py`
- Create: `packages/core/src/pigrocrm/core/gmail/roster.py`
- Create: `packages/core/migrations/versions/0004_customers_email_index.py`
- Modify: `packages/core/tests/test_migrations.py:139,161` (`"0003"` → `"0004"`)
- Create: `packages/core/tests/test_gmail_roster.py`

**Interfaces:**
- Consumes: `Customer` (`customers/models.py`), `Person` (`people/models.py`), `Deal` (`deals/models.py`), the `db_session` fixture from `packages/core/tests/conftest.py`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class EntityRef:
      entity_type: str   # "customer" | "person" | "deal"
      entity_id: UUID

  class AddressRoster:
      def __init__(self, session: Session) -> None: ...
      def known_addresses(self) -> tuple[str, ...]: ...
      def resolve(self, address: str) -> tuple[EntityRef, ...]: ...
  ```
  Consumed by B1-7 (`known_addresses`), B1-9 (`resolve`), B1-11 (both).

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_roster.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.gmail.roster import AddressRoster, EntityRef
from pigrocrm.core.people.models import Person


def _customer(session: Session, *, ragione_sociale: str, email: str | None) -> Customer:
    customer = Customer(ragione_sociale=ragione_sociale, email=email)
    session.add(customer)
    session.flush()
    return customer


def test_roster_collects_both_tables_lowercased_and_deduplicated(db_session: Session) -> None:
    customer = _customer(db_session, ragione_sociale="Acme", email="Info@Acme.IT")
    db_session.add(Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id))
    # The same address on a person and on a customer is one address, not two: a `q`
    # that repeats a clause wastes the length budget the 20-address batch depends on.
    db_session.add(Person(nome="Bob", cognome="Rossi", email="info@acme.it", customer_id=customer.id))
    db_session.flush()

    assert AddressRoster(db_session).known_addresses() == ("ada@acme.it", "info@acme.it")


def test_roster_ignores_soft_deleted_and_null_addresses(db_session: Session) -> None:
    kept = _customer(db_session, ragione_sociale="Kept", email="kept@example.it")
    gone = _customer(db_session, ragione_sociale="Gone", email="gone@example.it")
    gone.deleted_at = datetime.now(UTC)
    _customer(db_session, ragione_sociale="Blank", email=None)
    db_session.add(
        Person(nome="Via", cognome="Via", email="via@example.it", customer_id=kept.id, deleted_at=datetime.now(UTC))
    )
    db_session.flush()

    assert AddressRoster(db_session).known_addresses() == ("kept@example.it",)


def test_resolve_returns_every_entity_the_address_touches(db_session: Session) -> None:
    customer = _customer(db_session, ragione_sociale="Acme", email="info@acme.it")
    person = Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id)
    db_session.add(person)
    db_session.flush()
    deal = Deal(titolo="Rinnovo", customer_id=customer.id)
    db_session.add(deal)
    db_session.flush()

    # One email concerns the person, her customer, and that customer's open deals at
    # once. This is why gmail_message_links is many-to-many and not three nullable
    # foreign keys: a single FK would force a choice the data does not support.
    assert set(AddressRoster(db_session).resolve("Ada@Acme.it")) == {
        EntityRef("person", person.id),
        EntityRef("customer", customer.id),
        EntityRef("deal", deal.id),
    }


def test_resolve_is_empty_for_an_address_nobody_owns(db_session: Session) -> None:
    assert AddressRoster(db_session).resolve("stranger@example.com") == ()


def test_customers_email_is_indexed_like_people_email(db_session: Session) -> None:
    """people.email has had an index since slice 1; customers.email has not, and the
    relevance resolution queries both on every message. Same query shape, same cost,
    so the same index."""
    columns = {
        tuple(index["column_names"])
        for index in inspect(db_session.get_bind()).get_indexes("customers")
    }
    assert ("email",) in columns
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_roster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pigrocrm.core.gmail'`.

- [ ] **Step 3: Index the column and write the roster**

`packages/core/src/pigrocrm/core/customers/models.py:36` — add `index=True`, matching `people/models.py:36` exactly:

```python
    # Indexed for the same reason people.email is: Gmail relevance resolution
    # (gmail/roster.py) looks an address up in both tables on every message it
    # considers, and an unindexed lookup there is a sequential scan per message.
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
```

`packages/core/src/pigrocrm/core/gmail/__init__.py`: empty file.

`packages/core/src/pigrocrm/core/gmail/roster.py`:

```python
"""Who the CRM already knows, by email address.

This module *is* the relevance rule of spec 4.2. There are no rules to configure, no
filters to maintain and no domain lists to curate: the set of relevant addresses is
the address book, and keeping it current is work the user was doing anyway. The good
consequence is that making a conversation appear means adding the person to the CRM,
which is the action they wanted to take regardless.

The rule this module must never break: an address discovered *inside* a thread does
not enter the roster (spec 4.3). If it did, relevance would widen by itself on every
cycle, which is exactly the failure mode spec 4 exists to prevent.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.people.models import Person


@dataclass(frozen=True)
class EntityRef:
    """A CRM entity an email concerns. `entity_type` is a plain `str` and not
    `fields.EntityType`: that literal is the *custom-field* entity type and Gmail adds
    no custom fields to anything. Widening it here would offer administrators custom
    fields on a credential row."""

    entity_type: str
    entity_id: UUID


class AddressRoster:
    def __init__(self, session: Session) -> None:
        self.session = session

    def known_addresses(self) -> tuple[str, ...]:
        """Every non-null email on a live Person or Customer, lowercased, deduplicated
        and sorted. Sorted because the batching in `gmail/query.py` must be stable: an
        unstable order means two consecutive syncs issue different `q` strings for the
        same data, and the request-inspecting test in B1-7 could then pass by luck."""
        people = select(func.lower(Person.email)).where(
            Person.email.is_not(None), Person.deleted_at.is_(None)
        )
        customers = select(func.lower(Customer.email)).where(
            Customer.email.is_not(None), Customer.deleted_at.is_(None)
        )
        rows = self.session.execute(people.union(customers)).scalars().all()
        return tuple(sorted(address for address in rows if address))

    def resolve(self, address: str) -> tuple[EntityRef, ...]:
        """Every entity one address touches: the person, that person's customer, the
        customer itself, and that customer's live deals."""
        needle = address.strip().lower()
        if not needle:
            return ()

        refs: list[EntityRef] = []
        customer_ids: set[UUID] = set()

        person_rows = self.session.execute(
            select(Person.id, Person.customer_id).where(
                func.lower(Person.email) == needle, Person.deleted_at.is_(None)
            )
        ).all()
        for person_id, customer_id in person_rows:
            refs.append(EntityRef("person", person_id))
            if customer_id is not None:
                customer_ids.add(customer_id)

        direct = self.session.execute(
            select(Customer.id).where(
                func.lower(Customer.email) == needle, Customer.deleted_at.is_(None)
            )
        ).scalars().all()
        customer_ids.update(direct)

        for customer_id in customer_ids:
            refs.append(EntityRef("customer", customer_id))

        if customer_ids:
            deal_ids = self.session.execute(
                select(Deal.id).where(
                    Deal.customer_id.in_(customer_ids), Deal.deleted_at.is_(None)
                )
            ).scalars().all()
            refs.extend(EntityRef("deal", deal_id) for deal_id in deal_ids)

        # Deduplicated because a customer reached through two of its own people is one
        # customer. Order is not part of the contract; the test compares as a set.
        return tuple(dict.fromkeys(refs))
```

- [ ] **Step 4: Write the migration**

`packages/core/migrations/versions/0004_customers_email_index.py`:

```python
"""customers.email index for Gmail relevance resolution

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_customers_email", "customers", ["email"])


def downgrade() -> None:
    op.drop_index("ix_customers_email", table_name="customers")
```

The index name is `ix_customers_email` because that is what SQLAlchemy's default naming convention produces for `index=True` on that column — `test_migrations_produce_exactly_the_models_schema` compares migrations against models and will reject any other name.

- [ ] **Step 5: Bump the applied-revision assertions**

`packages/core/tests/test_migrations.py:139` and `:161` — `assert revision == "0003"` becomes `assert revision == "0004"` in both places. Leave `HAND_MAINTAINED_INDEXES` alone: `ix_customers_email` comes from the model's `index=True`, so the model-versus-migration comparison already covers it, and adding a declarative index to a set documented as holding the *hand-maintained* ones would make that set mean two things.

- [ ] **Step 6: Register the module and run**

`packages/core/src/pigrocrm/core/models_registry.py` — nothing to add yet (this task adds no model). Then:

Run: `uv run pytest packages/core/tests/test_gmail_roster.py packages/core/tests/test_migrations.py -v`
Expected: PASS.

Run: `uv run mypy && uv run ruff check .`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/src/pigrocrm/core/customers/models.py \
        packages/core/migrations/versions/0004_customers_email_index.py \
        packages/core/tests/test_gmail_roster.py packages/core/tests/test_migrations.py
git commit -m "feat(gmail): the address roster, and the index its lookups needed"
```

---

### Task B1-2: Configuration, and Gmail being absent rather than broken

**Files:**
- Modify: `packages/core/src/pigrocrm/core/config.py`
- Create: `packages/core/tests/test_gmail_config.py`

**Interfaces:**
- Consumes: `Settings` and `get_settings()` from `config.py`, and the `_jwt_secret_must_be_long_enough` validator as the precedent for failing at startup.
- Produces, on `Settings`:
  ```python
  google_client_id: str = ""
  google_client_secret: str = ""
  google_token_key: str = ""            # 32 raw bytes, base64-encoded
  public_url: str = ""                  # PIGROCRM_PUBLIC_URL
  google_app_unverified: bool = False
  gmail_sync_address_batch_size: int = 20
  gmail_backfill_days: int = 90
  gmail_watermark_overlap_hours: int = 24
  gmail_body_max_bytes: int = 262_144
  gmail_attachment_max_bytes: int = 20_971_520
  gmail_send_grace_minutes: int = 15
  ```
  and, module level:
  ```python
  GOOGLE_TOKEN_KEY_BYTES = 32
  def gmail_configured(settings: Settings) -> bool: ...
  def require_gmail_configured(settings: Settings) -> None: ...   # raises Conflict
  def decode_google_token_key(settings: Settings) -> bytes: ...   # raises ValueError
  ```
  Consumed by B1-3 (`decode_google_token_key`), B1-6, B1-7, B1-13 (`require_gmail_configured`), B1-14 (`gmail_configured`).

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_config.py`:

```python
import base64

import pytest

from pigrocrm.core.config import (
    GOOGLE_TOKEN_KEY_BYTES,
    Settings,
    decode_google_token_key,
    gmail_configured,
    require_gmail_configured,
)
from pigrocrm.core.errors import Conflict

VALID_KEY = base64.b64encode(b"k" * GOOGLE_TOKEN_KEY_BYTES).decode()


def _settings(**overrides: object) -> Settings:
    # _env_file=None so a developer's own .env cannot make this suite pass or fail.
    base: dict[str, object] = {"jwt_secret": "x" * 32, "_env_file": None}
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_gmail_is_absent_when_no_client_id_is_set() -> None:
    assert gmail_configured(_settings()) is False


def test_gmail_needs_all_four_values_not_just_the_client_id() -> None:
    partial = _settings(google_client_id="cid", google_client_secret="secret")
    assert gmail_configured(partial) is False
    whole = _settings(
        google_client_id="cid",
        google_client_secret="secret",
        google_token_key=VALID_KEY,
        public_url="https://crm.example.it",
    )
    assert gmail_configured(whole) is True


def test_an_unconfigured_install_gets_a_sentence_not_a_stack_trace() -> None:
    with pytest.raises(Conflict) as caught:
        require_gmail_configured(_settings())
    assert "Gmail non è configurato su questa installazione" in caught.value.message
    assert caught.value.code == "conflict"


def test_the_token_key_must_be_thirty_two_bytes_of_base64() -> None:
    for bad, why in [
        ("", "missing"),
        ("not-base64!!", "not base64"),
        (base64.b64encode(b"short").decode(), "wrong length"),
    ]:
        with pytest.raises(ValueError, match="PIGROCRM_GOOGLE_TOKEN_KEY") as caught:
            decode_google_token_key(_settings(google_token_key=bad))
        # The message names the variable and the requirement, and never the value:
        # a key that reached a log or an exception message is a leaked key.
        assert bad not in str(caught.value), why


def test_a_valid_token_key_decodes_to_exactly_thirty_two_bytes() -> None:
    assert len(decode_google_token_key(_settings(google_token_key=VALID_KEY))) == 32


def test_the_batch_size_is_configurable_without_touching_code() -> None:
    # Spec 4.1: twenty addresses with two clauses each fit Gmail's practical `q`
    # length with margin, but the number has to be correctable from the environment.
    assert _settings().gmail_sync_address_batch_size == 20
    assert _settings(gmail_sync_address_batch_size=8).gmail_sync_address_batch_size == 8


def test_the_documented_defaults_are_the_documented_values() -> None:
    settings = _settings()
    assert settings.gmail_backfill_days == 90
    assert settings.gmail_watermark_overlap_hours == 24
    assert settings.gmail_body_max_bytes == 262_144
    assert settings.gmail_attachment_max_bytes == 20 * 1024 * 1024
    assert settings.gmail_send_grace_minutes == 15
    assert settings.google_app_unverified is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'GOOGLE_TOKEN_KEY_BYTES'`.

- [ ] **Step 3: Extend `config.py`**

Add to `Settings`, after the render settings:

```python
    # --- Gmail (slice 5). Absent, not broken: if `google_client_id` is unset, Gmail
    # does not exist on this installation. The UI hides the section, the endpoints
    # answer Conflict, and the MCP tools are never registered. That is what lets
    # someone who self-hosts precisely in order not to have Google not have Google.
    google_client_id: str = ""
    google_client_secret: str = ""
    # 32 raw bytes, base64-encoded. Encrypts `google_accounts.refresh_token_ciphertext`
    # at rest. The key lives outside the database on purpose: a dump, a backup or a
    # pg_dump attached to a bug report are different exposure surfaces from the running
    # system, and this credential opens a *third-party* account, not just this app.
    google_token_key: str = ""
    # The public origin, used to build the one redirect_uri Google compares exactly:
    # {public_url}/api/gmail/oauth/callback.
    public_url: str = ""
    # Google exposes no API for "is my OAuth client verified", so the operator states
    # it. True means Testing, which means a consumer refresh token expires 7 days after
    # consent -- so `consent_expires_at` gets set and the UI warns 48 hours ahead.
    google_app_unverified: bool = False

    gmail_sync_address_batch_size: int = 20
    gmail_backfill_days: int = 90
    gmail_watermark_overlap_hours: int = 24
    gmail_body_max_bytes: int = 262_144
    gmail_attachment_max_bytes: int = 20_971_520
    gmail_send_grace_minutes: int = 15
```

And at module level, below `MIN_JWT_SECRET_LENGTH`:

```python
GOOGLE_TOKEN_KEY_BYTES = 32
```

Below `get_settings()`:

```python
def gmail_configured(settings: Settings) -> bool:
    """All four or none. A client id with no token key would connect an account and
    then be unable to store its refresh token, which is a worse failure than not
    offering the feature."""
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_token_key
        and settings.public_url
    )


def require_gmail_configured(settings: Settings) -> None:
    if not gmail_configured(settings):
        raise Conflict("gmail", "Gmail non è configurato su questa installazione")


def decode_google_token_key(settings: Settings) -> bytes:
    """Raises `ValueError` naming the variable, never quoting the value.

    Called at startup when `google_accounts` has at least one row (apps/api deps),
    so a missing or malformed key fails the boot rather than the first sync -- the
    same discipline as `_jwt_secret_must_be_long_enough`. Not a pydantic validator,
    because the empty default has to stay legal for every install that has no Gmail.
    """
    if not settings.google_token_key:
        raise ValueError(
            "PIGROCRM_GOOGLE_TOKEN_KEY is not set, but google_accounts holds at least "
            "one stored refresh token. Without the key those rows cannot be decrypted."
        )
    try:
        key = base64.b64decode(settings.google_token_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "PIGROCRM_GOOGLE_TOKEN_KEY is not valid base64"
        ) from exc
    if len(key) != GOOGLE_TOKEN_KEY_BYTES:
        raise ValueError(
            f"PIGROCRM_GOOGLE_TOKEN_KEY must decode to exactly {GOOGLE_TOKEN_KEY_BYTES} "
            f"bytes for AES-256-GCM, got {len(key)}"
        )
    return key
```

Add `import base64`, `import binascii` and `from pigrocrm.core.errors import Conflict` to the imports.

Note the `raise ValueError(...) from exc` — `binascii.Error` carries the offending input in some Python builds, so the chained cause must never be formatted into a user-facing message. The API's error handler renders `DomainError` only; a `ValueError` at startup goes to the process log, which is the one place this belongs.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_config.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Document the variables**

Append to `.env.example` (create the block; keep every value empty so a checkout is an install without Gmail):

```
# --- Gmail (slice 5). Leave PIGROCRM_GOOGLE_CLIENT_ID empty to run without Gmail.
PIGROCRM_GOOGLE_CLIENT_ID=
PIGROCRM_GOOGLE_CLIENT_SECRET=
# openssl rand -base64 32
PIGROCRM_GOOGLE_TOKEN_KEY=
# The public origin. Google compares {PIGROCRM_PUBLIC_URL}/api/gmail/oauth/callback
# against the authorised redirect URI character for character.
PIGROCRM_PUBLIC_URL=
# true while the OAuth client is unverified (Testing): consumer refresh tokens then
# expire 7 days after consent, and the UI warns 48 hours before that.
PIGROCRM_GOOGLE_APP_UNVERIFIED=false
```

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/config.py packages/core/tests/test_gmail_config.py .env.example
git commit -m "feat(gmail): configuration, with Gmail absent rather than broken when unset"
```

---

### Task B1-3: `google_accounts`, `google_oauth_states`, and the refresh token encrypted at rest

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/crypto.py`
- Create: `packages/core/src/pigrocrm/core/gmail/models.py`
- Create: `packages/core/src/pigrocrm/core/gmail/schemas.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Modify: `packages/core/pyproject.toml` (declare `cryptography`)
- Create: `packages/core/migrations/versions/0005_google_accounts.py`
- Modify: `packages/core/tests/test_migrations.py:139,161` (`"0004"` → `"0005"`)
- Create: `packages/core/tests/test_gmail_crypto.py`
- Create: `packages/core/tests/test_gmail_models.py`

**Interfaces:**
- Consumes: `decode_google_token_key` from B1-2; `Base`, `PrimaryKeyMixin`, `TimestampMixin` from `pigrocrm.core.db`.
- Produces:
  ```python
  # crypto.py
  def seal(plaintext: str, key: bytes) -> tuple[bytes, bytes]:    # (ciphertext, nonce)
  def unseal(ciphertext: bytes, nonce: bytes, key: bytes) -> str  # raises Conflict

  # models.py
  class GoogleAccount(Base, PrimaryKeyMixin, TimestampMixin)
  class GoogleOAuthState(Base, PrimaryKeyMixin, TimestampMixin)

  # schemas.py
  GmailStatus = Literal["active", "expired", "revoked"]
  SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
  SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
  REQUESTED_SCOPES: tuple[str, ...] = ("openid", "email", SCOPE_READONLY, SCOPE_SEND)
  class GoogleAccountRead(BaseModel)
  ```
  Consumed by B1-5, B1-6, B1-12, B1-13, and by 5B-2's send gate.

- [ ] **Step 1: Write the failing crypto test**

`packages/core/tests/test_gmail_crypto.py`:

```python
import pytest

from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import seal, unseal

KEY = b"k" * 32
OTHER_KEY = b"j" * 32
TOKEN = "1//0gSecretRefreshTokenValue-XYZ"


def test_a_sealed_token_comes_back_identical() -> None:
    ciphertext, nonce = seal(TOKEN, KEY)
    assert unseal(ciphertext, nonce, KEY) == TOKEN


def test_the_ciphertext_never_contains_the_plaintext() -> None:
    ciphertext, _ = seal(TOKEN, KEY)
    assert TOKEN.encode() not in ciphertext


def test_two_seals_of_the_same_token_differ() -> None:
    """A fresh nonce per seal. Reusing a nonce with AES-GCM is a catastrophic
    failure, not a weakness: two messages under one nonce leak their XOR and forge
    the authenticator."""
    first, first_nonce = seal(TOKEN, KEY)
    second, second_nonce = seal(TOKEN, KEY)
    assert first_nonce != second_nonce
    assert first != second


def test_the_wrong_key_is_refused_not_garbled() -> None:
    ciphertext, nonce = seal(TOKEN, KEY)
    with pytest.raises(Conflict) as caught:
        unseal(ciphertext, nonce, OTHER_KEY)
    assert "PIGROCRM_GOOGLE_TOKEN_KEY" in caught.value.message


def test_a_tampered_ciphertext_is_refused() -> None:
    ciphertext, nonce = seal(TOKEN, KEY)
    tampered = bytes([ciphertext[0] ^ 0x01]) + ciphertext[1:]
    with pytest.raises(Conflict):
        unseal(tampered, nonce, KEY)


def test_no_failure_path_puts_the_token_or_the_key_in_the_message() -> None:
    ciphertext, nonce = seal(TOKEN, KEY)
    for args in [(ciphertext, nonce, OTHER_KEY), (b"\x00" * len(ciphertext), nonce, KEY)]:
        with pytest.raises(Conflict) as caught:
            unseal(*args)
        rendered = f"{caught.value.message} {caught.value.details}"
        assert TOKEN not in rendered
        assert KEY.hex() not in rendered
        assert ciphertext.hex() not in rendered
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_crypto.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.crypto'`.

- [ ] **Step 3: Declare the dependency, then write the module**

`packages/core/pyproject.toml`, under `[project].dependencies`, add `"cryptography"` pinned to the version `uv.lock` already resolves for `pyjwt[crypto]`. Read it, do not guess:

```bash
uv run python -c "import cryptography; print(cryptography.__version__)"
```

The architecture test (`packages/core/tests/test_architecture.py`) is an allowlist built from that `dependencies` list, so an undeclared import fails it — which is the point: `cryptography` arrives here as a transitive edge of `pyjwt[crypto]` today, and a transitive edge is not a contract.

`packages/core/src/pigrocrm/core/gmail/crypto.py`:

```python
"""AES-256-GCM for the one secret this slice stores at rest.

Why encrypt at all, when the database belongs to the user: not to protect them from
themselves, but because a dump, a backup, or a `pg_dump` attached to a bug report are
different exposure surfaces from the running system -- and this credential grants
access to a *third-party* account, not merely to this application. The key lives
outside the database. That is the entire point.

Access tokens are never stored, here or anywhere: they live in memory for the duration
of one sync or one send. An access token is valid for an hour; persisting it would add
a second secret to protect for no gain. `storage/gdrive.py` already made that call.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pigrocrm.core.errors import Conflict

# 96 bits, the size AES-GCM is specified for. A longer nonce is hashed down and a
# shorter one narrows the space needlessly.
NONCE_BYTES = 12


def seal(plaintext: str, key: bytes) -> tuple[bytes, bytes]:
    """Returns `(ciphertext, nonce)`. A fresh nonce per call, from `os.urandom`."""
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def unseal(ciphertext: bytes, nonce: bytes, key: bytes) -> str:
    """Raises `Conflict` naming the environment variable and nothing else.

    Never the ciphertext, never the key, never a partial decryption: an authentication
    failure means either the key is wrong or the row was altered, and both are the
    same instruction to the operator. Distinguishing them in the message would leak
    which one, and an oracle on 'is this the right key' is the one thing GCM's
    authenticator exists to withhold.
    """
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise Conflict(
            "google_account",
            "il refresh token memorizzato non è decifrabile: verifica "
            "PIGROCRM_GOOGLE_TOKEN_KEY, oppure ricollega la casella",
        ) from exc
```

- [ ] **Step 4: Run the crypto test and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_crypto.py packages/core/tests/test_architecture.py -v`
Expected: PASS (6 crypto tests, architecture green).

- [ ] **Step 5: Write the failing model test**

`packages/core/tests/test_gmail_models.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User
from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES, SCOPE_READONLY, SCOPE_SEND


def _user(session: Session, email: str) -> User:
    user = User(email=email, nome="Tester", password_hash="x", role="admin", attivo=True)
    session.add(user)
    session.flush()
    return user


def _account(session: Session, user: User, **overrides: object) -> GoogleAccount:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "google_sub": f"sub-{user.email}",
        "email_address": user.email,
        "refresh_token_ciphertext": b"\x01\x02",
        "refresh_token_nonce": b"\x03" * 12,
        "scopes_granted": list(REQUESTED_SCOPES),
        "status": "active",
    }
    account = GoogleAccount(**{**defaults, **overrides})  # type: ignore[arg-type]
    session.add(account)
    session.flush()
    return account


def test_one_mailbox_per_user_is_enforced_by_the_database(db_session: Session) -> None:
    """Two mailboxes double the relevance question without anyone having asked it."""
    user = _user(db_session, "one@example.it")
    _account(db_session, user)
    with pytest.raises(IntegrityError):
        _account(db_session, user, google_sub="sub-other", email_address="other@example.it")
    db_session.rollback()


def test_status_and_granted_scopes_are_two_separate_facts(db_session: Session) -> None:
    """Spec 5.1: a valid credential missing a scope is healthy; it is the *feature*
    that is unavailable. Conflating them is the contradiction every other OAuth
    integration falls into."""
    user = _user(db_session, "partial@example.it")
    account = _account(db_session, user, scopes_granted=["openid", "email", SCOPE_SEND])
    assert account.status == "active"
    assert SCOPE_READONLY not in account.scopes_granted
    assert SCOPE_SEND in account.scopes_granted


def test_bodies_are_stored_by_default_and_the_switch_is_per_account(db_session: Session) -> None:
    user = _user(db_session, "bodies@example.it")
    account = _account(db_session, user)
    assert account.gmail_store_bodies is True


def test_a_state_jti_can_only_exist_once(db_session: Session) -> None:
    """The registry that makes the JWT's `jti` single-use for real rather than in
    principle. It also holds the PKCE code_verifier, which must stay server-side: put
    it in the signed state and the browser can read it, which cancels PKCE."""
    user = _user(db_session, "state@example.it")
    expires = datetime.now(UTC) + timedelta(minutes=5)
    db_session.add(
        GoogleOAuthState(jti="j1", code_verifier="v" * 43, user_id=user.id, expires_at=expires)
    )
    db_session.flush()
    db_session.add(
        GoogleOAuthState(jti="j1", code_verifier="w" * 43, user_id=user.id, expires_at=expires)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_fresh_state_row_has_not_been_consumed(db_session: Session) -> None:
    user = _user(db_session, "fresh@example.it")
    state = GoogleOAuthState(
        jti=str(uuid4()),
        code_verifier="v" * 43,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    db_session.add(state)
    db_session.flush()
    assert state.consumed_at is None
```

- [ ] **Step 6: Write the models and the schemas**

`packages/core/src/pigrocrm/core/gmail/schemas.py`:

```python
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Mirror the column widths in gmail/models.py exactly.
GOOGLE_SUB_MAX_LENGTH = 255
EMAIL_ADDRESS_MAX_LENGTH = 320
STATUS_MAX_LENGTH = 10
LAST_ERROR_MAX_LENGTH = 500
JTI_MAX_LENGTH = 64
CODE_VERIFIER_MAX_LENGTH = 128

GmailStatus = Literal["active", "expired", "revoked"]

SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
# `openid` + `email` identify *which* mailbox was connected: without the stable `sub`
# there is no way to refuse a reconnection that points at a different mailbox by
# mistake and silently relabels the entire history.
REQUESTED_SCOPES: tuple[str, ...] = ("openid", "email", SCOPE_READONLY, SCOPE_SEND)


class GoogleAccountRead(BaseModel):
    """What the settings page and `describe_gmail_account` show. No token, in either
    form: not the plaintext, not the ciphertext, not the nonce."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email_address: str
    scopes_granted: list[str]
    status: GmailStatus
    consent_expires_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    last_sync_at: datetime | None
    sync_watermark: datetime | None
    gmail_store_bodies: bool
    connected_at: datetime
    disconnected_at: datetime | None
```

`packages/core/src/pigrocrm/core/gmail/models.py`:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class GoogleAccount(Base, PrimaryKeyMixin, TimestampMixin):
    """One connected mailbox, per CRM user.

    `status` has three values and not four, and the distinction is load-bearing:
    `expired` is what we *predicted* (the consent window has passed with no successful
    refresh since), `revoked` is what Google *told us* (`invalid_grant`). They call for
    different reactions -- the first is a warning to show early, the second a fact to
    record -- so they are two states.

    `scopes_granted` deliberately does not feed `status`. Capability is derived from it
    at the point of use; the health of the credential is `status`. Google may grant a
    subset, and an account with `gmail.send` but not `gmail.readonly` is a healthy
    credential on which sync is unavailable.
    """

    __tablename__ = "google_accounts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    google_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    # AES-256-GCM, key from PIGROCRM_GOOGLE_TOKEN_KEY. Never logged, never returned by
    # any schema, never in an exception message.
    refresh_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes_granted: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    # When the *consent* must be renewed, not when an access token expires. Set to
    # connected_at + 7 days while PIGROCRM_GOOGLE_APP_UNVERIFIED is true, because that
    # is Google's Testing-mode behaviour and Google exposes no API to detect it.
    consent_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # The sentence the user reads, in Italian. Never a stack trace, never an upstream
    # body, never a token.
    last_error: Mapped[str | None] = mapped_column(String(500), default=None)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sync_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Off means headers and Gmail's snippet only, with the read-through degradation of
    # spec 5.4 point 2 as a declared consequence rather than a hidden one.
    gmail_store_bodies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class GoogleOAuthState(Base, PrimaryKeyMixin, TimestampMixin):
    """One in-flight authorisation.

    It exists because **PKCE's `code_verifier` has to stay server-side** between
    `/start` and `/callback`: putting it inside the signed `state` would make it
    readable by the browser and cancel PKCE entirely. It is also the registry that
    makes the JWT's `jti` single-use in fact rather than in principle.

    Expired rows are pruned on each sync cycle -- unlike `refresh_tokens`, which
    residuo R8 records as never pruned at all.
    """

    __tablename__ = "google_oauth_states"

    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

`packages/core/src/pigrocrm/core/models_registry.py` — add:

```python
from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState  # noqa: F401
```

Follow whatever pattern that file already uses for the slice-2 models; the point is that Alembic's autogenerate and `test_migrations` both see the metadata.

- [ ] **Step 7: Write the migration and bump the revision assertions**

`packages/core/migrations/versions/0005_google_accounts.py` — generate it, then read it:

```bash
uv run alembic -c packages/core/alembic.ini revision --autogenerate -m "google accounts and oauth states"
```

Rename the file to `0005_google_accounts.py`, set `revision = "0005"` and `down_revision = "0004"`, and check that it created `google_accounts` with the unique constraint on `user_id` and `google_oauth_states` with the unique constraint on `jti`. Autogenerate does not always emit `LargeBinary` as `sa.LargeBinary()`; if it emitted `sa.BLOB()`, fix it by hand — Postgres needs `BYTEA`.

`packages/core/tests/test_migrations.py:139,161` — `"0004"` → `"0005"`.

- [ ] **Step 8: Run everything and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_models.py packages/core/tests/test_gmail_crypto.py packages/core/tests/test_migrations.py packages/core/tests/test_module_imports.py -v`
Expected: PASS.

Run: `uv run mypy && uv run ruff check .`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/src/pigrocrm/core/models_registry.py \
        packages/core/pyproject.toml uv.lock packages/core/migrations/versions/0005_google_accounts.py \
        packages/core/tests/test_gmail_crypto.py packages/core/tests/test_gmail_models.py \
        packages/core/tests/test_migrations.py
git commit -m "feat(gmail): google_accounts, PKCE state, and the refresh token sealed at rest"
```

---

### Task B1-4: The HTTP seam, `FakeGmail`, and the rule that no test opens a socket

This is the task the other Gmail tasks are testable *because of*. Acme's two live production defects are both in code no test ever executed, and both are in exactly this layer.

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/errors.py`
- Create: `packages/core/src/pigrocrm/core/gmail/transport.py`
- Create: `packages/core/tests/fakes/fake_gmail.py`
- Create: `packages/core/tests/test_gmail_transport.py`
- Create: `packages/core/tests/test_no_network.py`

**Interfaces:**
- Consumes: the shape of `storage/gdrive.py`'s seam (`HttpCall`, `NETWORK_ERROR_STATUS = 599`, `_RETRYABLE_STATUSES`, `_MAX_HTTP_ATTEMPTS = 4`, `_RETRY_BASE_DELAY_SECONDS = 0.5`) as the precedent to follow — and to widen, deliberately.
- Produces:
  ```python
  # gmail/transport.py
  NETWORK_ERROR_STATUS = 599
  HTTP_TIMEOUT_SECONDS = 30
  MAX_HTTP_ATTEMPTS = 4
  GmailCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes, dict[str, str]]]
  SleepFn = Callable[[float], None]

  class GmailTransport:
      def __init__(self, *, http: GmailCall | None = None, sleep: SleepFn | None = None) -> None: ...
      def json(self, method: str, url: str, *, token: str, body: dict[str, Any] | None = None,
               what: str) -> dict[str, Any]: ...
      def form(self, url: str, fields: dict[str, str], *, what: str) -> dict[str, Any]: ...

  # gmail/errors.py
  @dataclass(frozen=True)
  class UpstreamFailure:
      status: int
      error_code: str
      retry_after: float | None

  class GoogleCallFailed(Exception):
      failure: UpstreamFailure
      what: str

  class CredentialRevoked(Conflict): ...
  class ScopeMissing(Conflict): ...
  class GmailUnavailable(Conflict): ...
  ```
- Produces, for tests: `FakeGmail`, whose `.requests: list[RecordedRequest]` is what B1-7's adversarial test asserts against.

- [ ] **Step 1: Write the failing transport test**

`packages/core/tests/test_gmail_transport.py`:

```python
import json

import pytest

from pigrocrm.core.gmail.errors import GoogleCallFailed
from pigrocrm.core.gmail.transport import NETWORK_ERROR_STATUS, GmailTransport

TOKEN = "ya29.a0-ACCESS-TOKEN-VALUE"
URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


def _responder(*responses: tuple[int, bytes, dict[str, str]]):
    queue = list(responses)
    calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def http(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes, dict[str, str]]:
        calls.append((method, url, headers, body))
        return queue.pop(0) if queue else (200, b"{}", {})

    return http, calls


def test_a_successful_call_returns_parsed_json_and_carries_the_bearer() -> None:
    http, calls = _responder((200, json.dumps({"messages": []}).encode(), {}))
    result = GmailTransport(http=http).json("GET", URL, token=TOKEN, what="elenco messaggi")
    assert result == {"messages": []}
    assert calls[0][2]["Authorization"] == f"Bearer {TOKEN}"


def test_a_429_is_retried_and_honours_the_servers_own_retry_after() -> None:
    """gdrive.py's seam cannot read response headers, so its backoff is a fixed
    exponential schedule and it says so in a comment. This seam is widened to carry
    them, because a 429 from Gmail names the delay and guessing is worse."""
    slept: list[float] = []
    http, calls = _responder(
        (429, json.dumps({"error": {"status": "RESOURCE_EXHAUSTED"}}).encode(), {"Retry-After": "3"}),
        (200, b"{}", {}),
    )
    GmailTransport(http=http, sleep=slept.append).json("GET", URL, token=TOKEN, what="elenco")
    assert slept == [3.0]
    assert len(calls) == 2


def test_a_401_is_not_retried_because_it_will_not_heal() -> None:
    body = json.dumps(
        {"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "Invalid Credentials"}}
    ).encode()
    http, calls = _responder((401, body, {}))
    with pytest.raises(GoogleCallFailed) as caught:
        GmailTransport(http=http, sleep=lambda _: None).json("GET", URL, token=TOKEN, what="elenco")
    assert len(calls) == 1
    assert caught.value.failure.status == 401
    assert caught.value.failure.error_code == "UNAUTHENTICATED"


def test_a_network_failure_becomes_a_synthetic_status_and_is_retried() -> None:
    slept: list[float] = []
    http, calls = _responder(
        (NETWORK_ERROR_STATUS, b'{"error":{"message":"timed out"}}', {}),
        (200, b"{}", {}),
    )
    GmailTransport(http=http, sleep=slept.append).json("GET", URL, token=TOKEN, what="elenco")
    assert len(calls) == 2
    assert slept == [0.5]


def test_it_gives_up_after_four_attempts_rather_than_forever() -> None:
    slept: list[float] = []
    http, calls = _responder(*[(503, b"{}", {})] * 6)
    with pytest.raises(GoogleCallFailed):
        GmailTransport(http=http, sleep=slept.append).json("GET", URL, token=TOKEN, what="elenco")
    assert len(calls) == 4
    assert slept == [0.5, 1.0, 2.0]


def test_the_token_endpoint_surfaces_invalid_grant_as_a_machine_readable_code() -> None:
    """Acme's parseGoogleError truncated the message to 400 characters and returned
    500, so a revoked token and a flaky network produced the same screen and therefore
    the same wrong reaction: retry. The code is what makes them distinguishable."""
    body = json.dumps({"error": "invalid_grant", "error_description": "Token has been expired or revoked."}).encode()
    http, calls = _responder((400, body, {}))
    with pytest.raises(GoogleCallFailed) as caught:
        GmailTransport(http=http, sleep=lambda _: None).form(
            "https://oauth2.googleapis.com/token", {"grant_type": "refresh_token"}, what="refresh"
        )
    assert caught.value.failure.error_code == "invalid_grant"
    assert len(calls) == 1, "invalid_grant is terminal: retrying it is a bug"


def test_no_failure_path_puts_the_token_in_the_exception() -> None:
    http, _ = _responder((403, b'{"error":{"status":"PERMISSION_DENIED"}}', {}))
    with pytest.raises(GoogleCallFailed) as caught:
        GmailTransport(http=http, sleep=lambda _: None).json("GET", URL, token=TOKEN, what="elenco")
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value.failure)


def test_a_malformed_retry_after_does_not_crash_the_backoff() -> None:
    slept: list[float] = []
    http, _ = _responder((429, b"{}", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), (200, b"{}", {}))
    GmailTransport(http=http, sleep=slept.append).json("GET", URL, token=TOKEN, what="elenco")
    # An HTTP-date Retry-After is legal and Gmail does not send it, but a parser that
    # crashes on a legal header is a parser that turns a retry into an outage.
    assert slept == [0.5]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_transport.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.errors'`.

- [ ] **Step 3: Write the error taxonomy**

`packages/core/src/pigrocrm/core/gmail/errors.py`:

```python
"""The distinction Acme did not make.

`parseGoogleError` + `truncateMessage(400)` -> 500 gave a revoked token and a flaky
network the same screen, so they got the same wrong reaction: retry. Retrying an
`invalid_grant` is a bug -- it will never succeed. These types exist so that the
difference survives the trip from the socket to the user.
"""

from dataclasses import dataclass
from uuid import UUID

from pigrocrm.core.errors import Conflict


@dataclass(frozen=True)
class UpstreamFailure:
    """What Google actually said. `error_code` is the machine-readable one --
    `invalid_grant`, `UNAUTHENTICATED`, `RESOURCE_EXHAUSTED` -- and never the prose,
    because the prose is what got truncated and thrown away last time. Empty string
    when the body carried none.

    Nothing here can hold a secret: the status is an integer, the code comes from a
    fixed vocabulary Google publishes, and `retry_after` is a number.
    """

    status: int
    error_code: str
    retry_after: float | None


class GoogleCallFailed(Exception):
    """Internal to `pigrocrm.core.gmail`. Never crosses the package boundary: every
    public method converts it into a `DomainError` first, because a caller outside
    this package cannot be expected to know what an `UpstreamFailure` is."""

    def __init__(self, failure: UpstreamFailure, what: str) -> None:
        super().__init__(f"{what} fallita ({failure.status}/{failure.error_code or 'n/d'})")
        self.failure = failure
        self.what = what


class CredentialRevoked(Conflict):
    """`invalid_grant`. Terminal. Do not retry, and do not skip silently."""

    def __init__(self, account_id: UUID, email_address: str) -> None:
        super().__init__(
            "google_account",
            f"il consenso Google per {email_address} è stato revocato: "
            "ricollega la casella da Impostazioni → Gmail",
            account_id=str(account_id),
            email_address=email_address,
        )


class ScopeMissing(Conflict):
    """A healthy credential that was granted less than was asked for. `status` stays
    `active` -- it is the feature that is unavailable, not the credential."""

    def __init__(self, scope: str, feature: str) -> None:
        super().__init__(
            "google_account",
            f"{feature} non è disponibile: manca l'autorizzazione {scope}. "
            "Usa «ri-autorizza» da Impostazioni → Gmail",
            scope=scope,
            feature=feature,
        )


class GmailUnavailable(Conflict):
    """Transient, after every retry was spent. Distinct from `CredentialRevoked`
    precisely because the reaction differs: wait and try again, versus re-consent."""

    def __init__(self, what: str, status: int) -> None:
        super().__init__(
            "gmail",
            f"{what}: Gmail non ha risposto correttamente (codice {status}). Riprova più tardi",
            status=status,
        )
```

- [ ] **Step 4: Write the transport**

`packages/core/src/pigrocrm/core/gmail/transport.py`:

```python
"""The only module in this slice that knows a socket exists.

Shaped after `storage/gdrive.py`: `urllib.request`, no Google client library, and an
injectable seam that the fake transport replaces. What is faked is the *network*, so
URL construction, `q` construction, RFC822 assembly and error classification all run
for real in the tests -- which matters because those are precisely the parts Acme got
wrong, in code no test ever executed.

One deliberate widening over `gdrive.py`'s `HttpCall`: this seam carries **response
headers**. `gdrive.py` says in its own comment that not carrying them means Google's
`Retry-After` on a 429 is unreadable and its backoff is therefore a fixed schedule,
and that widening the type "would fix that properly" but was out of scope there. Here
it is in scope, and this is a new type rather than a change to that one, so nothing
`gdrive.py` was reviewed against moves.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from pigrocrm.core.gmail.errors import GoogleCallFailed, UpstreamFailure

HTTP_TIMEOUT_SECONDS = 30
# Same synthetic status and the same reasoning as gdrive.py: "no HTTP response was
# ever received" needs to travel through the one channel every other status uses,
# rather than a second failure path only the urllib adapter knows about.
NETWORK_ERROR_STATUS = 599
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, NETWORK_ERROR_STATUS})
# First attempt plus up to three retries: 0.5s, 1s, 2s.
MAX_HTTP_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 0.5
# A server-supplied Retry-After is honoured, but not unboundedly: a synchronous sync
# holding a request open for an hour because a header said so is an outage with extra
# steps.
_MAX_HONOURED_RETRY_AFTER_SECONDS = 30.0

# (method, url, headers, body) -> (status, body, response headers).
GmailCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes, dict[str, str]]]
SleepFn = Callable[[float], None]


def _retry_delay_seconds(attempt: int) -> float:
    # `1 << attempt`, not `2 ** attempt`: typeshed types `int.__pow__` as returning
    # `Any`, which would make this function's return type `Any` under mypy strict.
    return _RETRY_BASE_DELAY_SECONDS * (1 << attempt)


def _urllib_call(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(), dict(exc.headers.items()) if exc.headers else {}
    except (urllib.error.URLError, OSError) as exc:
        # `str(exc)` names the failure reason and possibly the target host -- always a
        # googleapis.com address, never sensitive -- but never the request's headers or
        # body, so no bearer token can reach it.
        return (
            NETWORK_ERROR_STATUS,
            json.dumps({"error": {"message": str(exc)}}).encode(),
            {},
        )


def _parse_retry_after(headers: dict[str, str]) -> float | None:
    """Seconds only. An HTTP-date is legal and Gmail does not send one, but a parser
    that raises on a legal header turns a retry into an outage."""
    for name, value in headers.items():
        if name.lower() != "retry-after":
            continue
        try:
            seconds = float(value.strip())
        except ValueError:
            return None
        if seconds <= 0:
            return None
        return min(seconds, _MAX_HONOURED_RETRY_AFTER_SECONDS)
    return None


def _error_code(payload: bytes) -> str:
    """Google speaks two dialects and this slice touches both. The OAuth token
    endpoint answers `{"error": "invalid_grant"}` -- a bare string. The Gmail API
    answers `{"error": {"status": "UNAUTHENTICATED", ...}}` -- an object. Reading only
    one of them is how `invalid_grant` gets lost, which is the Acme defect."""
    try:
        parsed = json.loads(payload.decode())
    except (ValueError, UnicodeDecodeError):
        return ""
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        status = error.get("status")
        if isinstance(status, str):
            return status
        errors = error.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            reason = errors[0].get("reason")
            if isinstance(reason, str):
                return reason
    return ""


class GmailTransport:
    def __init__(self, *, http: GmailCall | None = None, sleep: SleepFn | None = None) -> None:
        self._http: GmailCall = http or _urllib_call
        # Injectable so the retry tests do not actually block for seconds.
        self._sleep: SleepFn = sleep or __import__("time").sleep

    def _call(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, what: str
    ) -> dict[str, Any]:
        for attempt in range(MAX_HTTP_ATTEMPTS):
            status, payload, response_headers = self._http(method, url, headers, body)
            if status < 400:
                return json.loads(payload.decode()) if payload else {}

            failure = UpstreamFailure(
                status=status,
                error_code=_error_code(payload),
                retry_after=_parse_retry_after(response_headers),
            )
            last = attempt == MAX_HTTP_ATTEMPTS - 1
            if status not in _RETRYABLE_STATUSES or last:
                raise GoogleCallFailed(failure, what)
            # The server's own hint wins over our guess when it gave one.
            self._sleep(
                failure.retry_after
                if failure.retry_after is not None
                else _retry_delay_seconds(attempt)
            )
        raise AssertionError("unreachable: the loop either returns or raises")

    def json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
        what: str,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        encoded: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(body).encode()
        return self._call(method, url, headers, encoded, what)

    def form(self, url: str, fields: dict[str, str], *, what: str) -> dict[str, Any]:
        """POST `application/x-www-form-urlencoded`, for the OAuth token endpoint and
        nothing else. No `Authorization` header: the credentials are in the body, and
        this is the one call that carries the client secret. Nothing here logs."""
        return self._call(
            "POST",
            url,
            {"Content-Type": "application/x-www-form-urlencoded"},
            urlencode(fields).encode(),
            what,
        )
```

Replace `__import__("time").sleep` with a module-level `import time` and `time.sleep` — the inline import is written above only to keep the snippet self-contained; use the normal import.

- [ ] **Step 5: Write `FakeGmail`**

`packages/core/tests/fakes/fake_gmail.py`:

```python
"""An in-memory Gmail that speaks the same HTTP surface `GmailTransport` uses.

A fake of the *transport*, on the model of `fakes/fake_drive.py`, and for the same
reason: URL building, the `q` string, the RFC822 body and the error handling are the
parts most likely to be wrong, so they must run for real. What is replaced is the
network, nothing above it.

`requests` is the point of this class. Every request is recorded with its parsed query
string, so a test can assert on **what was asked of Google** and not merely on what
ended up in the database. Spec 4.1 requires exactly that: "a `list` without a `q` is a
bug, and it is verified by a test that inspects the requests received by the fake
transport -- not by a convention written in a comment."
"""

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

TOKEN_HOST = "oauth2.googleapis.com"
API_HOST = "gmail.googleapis.com"


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    host: str
    path: str
    query: dict[str, list[str]]
    body: bytes | None

    @property
    def q(self) -> str | None:
        """The Gmail search expression, if this was a listing."""
        values = self.query.get("q")
        return values[0] if values else None

    @property
    def is_messages_list(self) -> bool:
        return self.method == "GET" and self.path.endswith("/messages")

    @property
    def is_messages_send(self) -> bool:
        return self.method == "POST" and self.path.endswith("/messages/send")


@dataclass
class FakeMessage:
    id: str
    thread_id: str
    headers: dict[str, str]
    body_text: str = ""
    body_html: str = ""
    internal_date_ms: int = 0
    label_ids: list[str] = field(default_factory=lambda: ["INBOX"])
    attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeGmail:
    """Configure the mailbox, then hand `self` to `GmailTransport(http=fake)`."""

    messages: dict[str, FakeMessage] = field(default_factory=dict)
    requests: list[RecordedRequest] = field(default_factory=list)
    token_requests: int = 0
    # A refresh token that Google has revoked. When set, the token endpoint answers
    # the real 400 body, once per call, forever -- because that is what a revoked
    # grant does. It never heals.
    revoked: bool = False
    access_token: str = "ya29.fake-access-token"
    expires_in: int = 3599
    granted_scopes: tuple[str, ...] = ()
    # A queue of (status, body, headers) consumed FIFO before normal handling. One
    # transient failure is `fail_with=[(503, b"{}", {})]`; a rate limit that names its
    # delay is `[(429, b"{}", {"Retry-After": "2"})]`.
    fail_with: list[tuple[int, bytes, dict[str, str]]] = field(default_factory=list)
    # Set to raise a socket-level failure instead of answering, for the "unknown
    # outcome" path of spec 6.3(b).
    timeout_on_send: bool = False

    # ---- the seam ---------------------------------------------------------------

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes, dict[str, str]]:
        parsed = urlparse(url)
        recorded = RecordedRequest(
            method=method,
            host=parsed.netloc,
            path=parsed.path,
            query=parse_qs(parsed.query),
            body=body,
        )
        self.requests.append(recorded)

        if self.fail_with:
            return self.fail_with.pop(0)

        if parsed.netloc == TOKEN_HOST:
            return self._token()
        if recorded.is_messages_send:
            return self._send()
        if recorded.is_messages_list:
            return self._list(recorded)
        if "/threads/" in parsed.path:
            return self._thread(parsed.path.rsplit("/", 1)[-1])
        if "/messages/" in parsed.path:
            return self._message(parsed.path.rsplit("/", 1)[-1])
        return 404, json.dumps({"error": {"status": "NOT_FOUND"}}).encode(), {}

    # ---- endpoints --------------------------------------------------------------

    def _token(self) -> tuple[int, bytes, dict[str, str]]:
        self.token_requests += 1
        if self.revoked:
            # The exact shape Google returns for a revoked or expired grant. A bare
            # string under "error", not an object -- the dialect that gets lost when a
            # parser only reads the API's shape.
            return (
                400,
                json.dumps(
                    {
                        "error": "invalid_grant",
                        "error_description": "Token has been expired or revoked.",
                    }
                ).encode(),
                {},
            )
        payload: dict[str, Any] = {
            "access_token": self.access_token,
            "expires_in": self.expires_in,
            "token_type": "Bearer",
        }
        if self.granted_scopes:
            payload["scope"] = " ".join(self.granted_scopes)
        return 200, json.dumps(payload).encode(), {}

    def _send(self) -> tuple[int, bytes, dict[str, str]]:
        if self.timeout_on_send:
            # The synthetic status `_urllib_call` produces when no HTTP response was
            # ever received. This is the "we do not know" case of spec 6.3(b).
            return 599, json.dumps({"error": {"message": "timed out"}}).encode(), {}
        message_id = f"sent-{len([r for r in self.requests if r.is_messages_send])}"
        return (
            200,
            json.dumps({"id": message_id, "threadId": f"thread-{message_id}"}).encode(),
            {},
        )

    def _list(self, recorded: RecordedRequest) -> tuple[int, bytes, dict[str, str]]:
        """Matches on the `q` the way Gmail does for the operators this slice uses:
        `from:`, `to:`, `after:` and `rfc822msgid:`. Deliberately not a full Gmail
        query engine -- but deliberately *not* a stub that ignores `q` either, because
        a fake that returns everything regardless would make the relevance test
        vacuous."""
        from tests.fakes.gmail_query import matches  # local import: test-only helper

        query = recorded.q or ""
        hits = [message for message in self.messages.values() if matches(message, query)]
        hits.sort(key=lambda message: message.internal_date_ms)
        return (
            200,
            json.dumps(
                {
                    "messages": [{"id": m.id, "threadId": m.thread_id} for m in hits],
                    "resultSizeEstimate": len(hits),
                }
            ).encode(),
            {},
        )

    def _thread(self, thread_id: str) -> tuple[int, bytes, dict[str, str]]:
        members = [m for m in self.messages.values() if m.thread_id == thread_id]
        if not members:
            return 404, json.dumps({"error": {"status": "NOT_FOUND"}}).encode(), {}
        members.sort(key=lambda message: message.internal_date_ms)
        return (
            200,
            json.dumps(
                {"id": thread_id, "messages": [self._as_api(m) for m in members]}
            ).encode(),
            {},
        )

    def _message(self, message_id: str) -> tuple[int, bytes, dict[str, str]]:
        message = self.messages.get(message_id)
        if message is None:
            return 404, json.dumps({"error": {"status": "NOT_FOUND"}}).encode(), {}
        return 200, json.dumps(self._as_api(message)).encode(), {}

    # ---- shaping ----------------------------------------------------------------

    def _as_api(self, message: FakeMessage) -> dict[str, Any]:
        """Gmail's own `format=full` shape: base64url parts, headers as a list of
        name/value pairs, `multipart/alternative` when both a text and an HTML part
        exist. The parser under test has to cope with the real shape."""
        import base64

        def b64(text: str) -> str:
            return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

        parts: list[dict[str, Any]] = []
        if message.body_text:
            parts.append(
                {
                    "mimeType": "text/plain",
                    "body": {"data": b64(message.body_text), "size": len(message.body_text)},
                }
            )
        if message.body_html:
            parts.append(
                {
                    "mimeType": "text/html",
                    "body": {"data": b64(message.body_html), "size": len(message.body_html)},
                }
            )
        for attachment in message.attachments:
            parts.append(
                {
                    "mimeType": attachment["mime"],
                    "filename": attachment["filename"],
                    "body": {"attachmentId": "att-1", "size": attachment["size"]},
                }
            )
        return {
            "id": message.id,
            "threadId": message.thread_id,
            "labelIds": message.label_ids,
            "snippet": (message.body_text or message.body_html)[:120],
            "internalDate": str(message.internal_date_ms),
            "payload": {
                "mimeType": "multipart/mixed" if len(parts) > 1 else "text/plain",
                "headers": [{"name": k, "value": v} for k, v in message.headers.items()],
                "parts": parts if len(parts) > 1 else [],
                "body": parts[0]["body"] if len(parts) == 1 else {"size": 0},
            },
        }
```

And the query matcher it imports, `packages/core/tests/fakes/gmail_query.py`:

```python
"""Just enough of Gmail's `q` to make the relevance test meaningful.

Supports `from:`, `to:`, `after:`, `rfc822msgid:`, parenthesised groups and `OR`.
Everything else raises, on purpose: a fake that silently ignores an operator the
production code relies on turns a passing test into a false statement.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.fakes.fake_gmail import FakeMessage

_TERM = re.compile(r"(from|to|after|rfc822msgid):(\S+)")


def matches(message: "FakeMessage", query: str) -> bool:
    if not query.strip():
        raise AssertionError(
            "FakeGmail received a messages.list with an empty q. Spec 4.1: a listing "
            "without an address filter is a bug, not a broad search."
        )

    groups = re.findall(r"\(([^)]*)\)", query)
    outside = re.sub(r"\([^)]*\)", " ", query)

    unknown = [
        token
        for token in outside.split()
        if ":" in token and not _TERM.fullmatch(token)
    ]
    if unknown:
        raise AssertionError(f"FakeGmail does not implement the Gmail operator(s) {unknown}")

    # Terms outside any group are ANDed; a parenthesised group is ORed internally.
    for group in groups:
        if not any(_term_matches(message, term) for term in _TERM.findall(group)):
            return False
    for term in _TERM.findall(outside):
        if not _term_matches(message, term):
            return False
    return True


def _term_matches(message: "FakeMessage", term: tuple[str, str]) -> bool:
    operator, value = term
    if operator == "from":
        return value.lower() in message.headers.get("From", "").lower()
    if operator == "to":
        haystack = " ".join(
            message.headers.get(name, "") for name in ("To", "Cc", "Bcc")
        ).lower()
        return value.lower() in haystack
    if operator == "after":
        return message.internal_date_ms >= int(value) * 1000
    if operator == "rfc822msgid":
        return message.headers.get("Message-ID", "").strip("<>") == value.strip("<>")
    raise AssertionError(f"unreachable operator {operator}")
```

- [ ] **Step 6: Write the no-network guard**

`packages/core/tests/test_no_network.py`:

```python
"""No test in this slice may open a socket.

A suite that skips when credentials are absent proves nothing: it is green on a
developer's laptop, green in CI, and has never executed the code it claims to cover.
The seam is at the HTTP boundary precisely so that everything above it can be
exercised for real without a network -- so a socket opening during the suite means
something bypassed the seam, which is the one thing that must not happen quietly.
"""

import socket

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_sockets() -> None:
    original = socket.socket.connect

    def refuse(self: socket.socket, address: object) -> None:
        # testcontainers and psycopg legitimately connect to the Postgres container on
        # localhost. Anything else is a test reaching the internet.
        host = address[0] if isinstance(address, tuple) else ""
        if host in {"127.0.0.1", "::1", "localhost"}:
            original(self, address)  # type: ignore[arg-type]
            return
        raise AssertionError(
            f"a test tried to open a socket to {address!r}. Slice 5 tests drive "
            "FakeGmail through the GmailTransport seam; they never touch the network."
        )

    socket.socket.connect = refuse  # type: ignore[method-assign]


def test_the_guard_is_installed_and_actually_refuses() -> None:
    with pytest.raises(AssertionError, match="never touch the network"):
        socket.create_connection(("gmail.googleapis.com", 443), timeout=0.1)


def test_no_slice_five_test_is_skipped_on_a_missing_credential() -> None:
    """`skipif` on an environment variable is how a Gmail suite comes to prove
    nothing. Checked as text, over the slice's own test files."""
    from pathlib import Path

    tests = Path(__file__).parent
    offenders = [
        path.name
        for path in tests.glob("test_gmail*.py")
        if "PIGROCRM_GOOGLE_CLIENT_ID" in path.read_text() and "skipif" in path.read_text()
    ]
    assert offenders == []
```

Move the `_no_sockets` fixture into `packages/core/tests/conftest.py` if the session-scoped autouse fixture does not apply across files from here — a fixture defined in a test module only applies to that module. The guard belongs in `conftest.py`; `test_no_network.py` keeps only the two tests that prove the guard is live.

- [ ] **Step 7: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_transport.py packages/core/tests/test_no_network.py -v`
Expected: PASS (8 transport tests + 2 guard tests).

Run: `uv run pytest packages/core/tests -q`
Expected: the whole existing suite still green. If the socket guard breaks testcontainers, widen the localhost allowlist to include the container's mapped address — never to include a public host.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail/errors.py packages/core/src/pigrocrm/core/gmail/transport.py \
        packages/core/tests/fakes/fake_gmail.py packages/core/tests/fakes/gmail_query.py \
        packages/core/tests/test_gmail_transport.py packages/core/tests/test_no_network.py \
        packages/core/tests/conftest.py
git commit -m "feat(gmail): the HTTP seam, a recording fake, and no socket in the suite"
```

---
### Task B1-5: Token exchange, refresh, and the cache Acme did not have

Acme discarded `expires_in`, had six call sites, and performed **two OAuth exchanges to send one invoice email**. That is not a missed optimisation: it is why a transient network error showed up twice per send.

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/tokens.py`
- Create: `packages/core/tests/test_gmail_tokens.py`

**Interfaces:**
- Consumes: `GmailTransport` and `GoogleCallFailed` from B1-4; `CredentialRevoked` from B1-4; `seal`/`unseal` from B1-3; `Settings` from B1-2.
- Produces:
  ```python
  GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
  GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
  GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

  @dataclass(frozen=True)
  class TokenGrant:
      access_token: str
      refresh_token: str
      scopes: tuple[str, ...]
      subject: str
      email_address: str
      expires_in: int

  class GoogleTokenClient:
      def __init__(self, *, client_id: str, client_secret: str, transport: GmailTransport,
                   clock: Callable[[], float] = time.monotonic) -> None: ...
      def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> TokenGrant: ...
      def access_token(self, *, account_id: UUID, email_address: str, refresh_token: str) -> str: ...
  ```
  Consumed by B1-6 (`exchange_code`), B1-7/B1-8/B1-11 and 5B-2's send path (`access_token`).

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_tokens.py`:

```python
import base64
import json
from uuid import uuid4

import pytest

from pigrocrm.core.gmail.errors import CredentialRevoked
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport
from tests.fakes.fake_gmail import FakeGmail

ACCOUNT = uuid4()
REFRESH = "1//0gRefreshTokenValue"


def _client(fake: FakeGmail, clock: object | None = None) -> GoogleTokenClient:
    return GoogleTokenClient(
        client_id="cid.apps.googleusercontent.com",
        client_secret="the-client-secret",
        transport=GmailTransport(http=fake, sleep=lambda _: None),
        clock=clock or (lambda: 1000.0),  # type: ignore[arg-type]
    )


def test_one_exchange_serves_every_call_within_the_token_lifetime() -> None:
    """Acme performed two OAuth exchanges to send a single invoice email, because it
    threw `expires_in` away. The cache is not an optimisation: it is why a flaky
    network stops presenting itself twice per operation."""
    fake = FakeGmail(expires_in=3599)
    client = _client(fake)
    tokens = {
        client.access_token(account_id=ACCOUNT, email_address="a@b.it", refresh_token=REFRESH)
        for _ in range(5)
    }
    assert tokens == {fake.access_token}
    assert fake.token_requests == 1


def test_the_cache_expires_on_the_servers_own_expires_in() -> None:
    now = [1000.0]
    fake = FakeGmail(expires_in=3599)
    client = _client(fake, clock=lambda: now[0])
    client.access_token(account_id=ACCOUNT, email_address="a@b.it", refresh_token=REFRESH)
    now[0] += 3000  # still inside the window, minus the safety margin
    client.access_token(account_id=ACCOUNT, email_address="a@b.it", refresh_token=REFRESH)
    assert fake.token_requests == 1
    now[0] += 1000  # past it
    client.access_token(account_id=ACCOUNT, email_address="a@b.it", refresh_token=REFRESH)
    assert fake.token_requests == 2


def test_two_accounts_do_not_share_a_cache_entry() -> None:
    fake = FakeGmail()
    client = _client(fake)
    client.access_token(account_id=ACCOUNT, email_address="a@b.it", refresh_token=REFRESH)
    client.access_token(account_id=uuid4(), email_address="c@d.it", refresh_token="1//other")
    assert fake.token_requests == 2


def test_invalid_grant_is_terminal_and_is_never_retried() -> None:
    fake = FakeGmail(revoked=True)
    client = _client(fake)
    with pytest.raises(CredentialRevoked) as caught:
        client.access_token(account_id=ACCOUNT, email_address="ada@acme.it", refresh_token=REFRESH)
    assert "ada@acme.it" in caught.value.message
    assert "revocato" in caught.value.message
    # Exactly one attempt. Retrying an invalid_grant is a bug: it will never succeed,
    # and retrying only delays telling the user something they must act on.
    assert fake.token_requests == 1


def test_a_revoked_grant_is_not_cached_as_a_failure_either() -> None:
    """A second call must ask again rather than replay a cached exception: the user may
    have re-consented between the two."""
    fake = FakeGmail(revoked=True)
    client = _client(fake)
    for _ in range(2):
        with pytest.raises(CredentialRevoked):
            client.access_token(account_id=ACCOUNT, email_address="a@b.it", refresh_token=REFRESH)
    assert fake.token_requests == 2


def test_no_error_path_leaks_the_refresh_token_or_the_client_secret() -> None:
    fake = FakeGmail(revoked=True)
    client = _client(fake)
    with pytest.raises(CredentialRevoked) as caught:
        client.access_token(account_id=ACCOUNT, email_address="a@b.it", refresh_token=REFRESH)
    rendered = f"{caught.value.message} {caught.value.details}"
    assert REFRESH not in rendered
    assert "the-client-secret" not in rendered


def test_exchange_code_reads_the_granted_scopes_and_the_subject() -> None:
    """Google may grant a subset of what was asked. What was *granted* is what gets
    recorded, because every feature checks the granted set, never the requested one."""
    claims = base64.urlsafe_b64encode(
        json.dumps({"sub": "104729", "email": "ada@acme.it"}).encode()
    ).decode().rstrip("=")
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.id_token = f"header.{claims}.signature"
    grant = _client(fake).exchange_code(
        code="4/0A-code", code_verifier="v" * 43, redirect_uri="https://crm.example.it/api/gmail/oauth/callback"
    )
    assert grant.subject == "104729"
    assert grant.email_address == "ada@acme.it"
    assert grant.scopes == REQUESTED_SCOPES
    assert grant.refresh_token


def test_a_grant_without_a_refresh_token_is_rejected_loudly() -> None:
    """Google omits the refresh token when `prompt=consent` was not sent and the user
    had already consented. Storing the row anyway would produce an account that can
    never refresh, failing only on the second day."""
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.omit_refresh_token = True
    with pytest.raises(CredentialRevoked):
        _client(fake).exchange_code(
            code="4/0A-code", code_verifier="v" * 43, redirect_uri="https://crm.example.it/x"
        )
```

`FakeGmail` needs three more fields for this task: `id_token: str = ""`, `omit_refresh_token: bool = False`, and `refresh_token: str = "1//0gFakeRefresh"`. Add them, and make `_token()` include `"refresh_token"` (unless `omit_refresh_token`) and `"id_token"` (when set) in the 200 body.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_tokens.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.tokens'`.

- [ ] **Step 3: Write the module**

`packages/core/src/pigrocrm/core/gmail/tokens.py`:

```python
"""Access tokens: obtained, cached in memory, never stored.

Three things Acme got wrong and this module exists to get right:

1. It discarded `expires_in` and re-exchanged on every call site -- two OAuth
   round-trips to send one invoice email.
2. Its Gmail refresh token fell back to the Drive one (`effectiveGmailRefresh`),
   putting two different capabilities on one credential.
3. It could not tell `invalid_grant` from a transient failure, so a revoked token and
   a flaky network produced the same screen and the same wrong reaction.

Only the refresh token is persisted, and only encrypted (`gmail/crypto.py`). An access
token is valid for an hour; persisting it would add a second secret to protect for no
gain.
"""

import base64
import binascii
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pigrocrm.core.gmail.errors import CredentialRevoked, GmailUnavailable, GoogleCallFailed
from pigrocrm.core.gmail.transport import GmailTransport

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Google's `invalid_grant` covers revoked, expired and never-issued grants alike. All
# three are terminal for us, and all three mean the same thing to the user: re-consent.
_INVALID_GRANT = "invalid_grant"
# Refresh a minute early rather than discovering expiry mid-sync.
_EXPIRY_MARGIN_SECONDS = 60


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    refresh_token: str
    scopes: tuple[str, ...]
    subject: str
    email_address: str
    expires_in: int


@dataclass(frozen=True)
class _CachedToken:
    value: str
    expires_at: float


def _decode_id_token_claims(id_token: str) -> dict[str, str]:
    """Reads the payload of the ID token *without* verifying its signature, and that
    is correct here: the token arrived over TLS directly from Google's token endpoint
    in response to a request carrying our client secret, which is precisely the case
    OpenID Connect exempts from signature verification. It is never accepted from a
    browser, a redirect, or any other party."""
    parts = id_token.split(".")
    if len(parts) != 3:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(claims, dict):
        return {}
    return {k: str(v) for k, v in claims.items() if isinstance(k, str)}


class GoogleTokenClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        transport: GmailTransport,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        # Monotonic, not wall clock: an NTP step backwards must not extend a token's
        # apparent life.
        self._clock = clock
        self._cache: dict[UUID, _CachedToken] = {}

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> TokenGrant:
        payload = self._post(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            what="scambio del codice di autorizzazione",
            account_id=None,
            email_address="",
        )
        refresh_token = str(payload.get("refresh_token") or "")
        claims = _decode_id_token_claims(str(payload.get("id_token") or ""))
        email_address = claims.get("email", "")
        if not refresh_token:
            # Without `prompt=consent`, Google omits the refresh token when the user has
            # already consented once. Storing the row anyway builds an account that can
            # never refresh and fails on day two instead of now.
            raise CredentialRevoked(
                UUID(int=0),
                email_address or "la casella selezionata",
            )
        granted = str(payload.get("scope") or "").split()
        return TokenGrant(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=refresh_token,
            scopes=tuple(granted),
            subject=claims.get("sub", ""),
            email_address=email_address,
            expires_in=int(payload.get("expires_in") or 0),
        )

    def access_token(self, *, account_id: UUID, email_address: str, refresh_token: str) -> str:
        cached = self._cache.get(account_id)
        now = self._clock()
        if cached is not None and cached.expires_at > now:
            return cached.value

        payload = self._post(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            what="rinnovo del token di accesso",
            account_id=account_id,
            email_address=email_address,
        )
        token = str(payload.get("access_token") or "")
        expires_in = int(payload.get("expires_in") or 0)
        self._cache[account_id] = _CachedToken(
            value=token,
            expires_at=now + max(0, expires_in - _EXPIRY_MARGIN_SECONDS),
        )
        return token

    def forget(self, account_id: UUID) -> None:
        """Drop a cached token, on disconnect or on re-authorisation."""
        self._cache.pop(account_id, None)

    def _post(
        self,
        fields: dict[str, str],
        *,
        what: str,
        account_id: UUID | None,
        email_address: str,
    ) -> dict[str, object]:
        try:
            return self._transport.form(GOOGLE_TOKEN_URL, fields, what=what)
        except GoogleCallFailed as failed:
            if failed.failure.error_code == _INVALID_GRANT:
                # Terminal. Not cached as a failure either: the user may re-consent
                # between two calls, and a cached refusal would hide that.
                raise CredentialRevoked(
                    account_id or UUID(int=0), email_address or "la casella collegata"
                ) from failed
            raise GmailUnavailable(what, failed.failure.status) from failed
```

Note `UUID(int=0)` in the two paths where no account row exists yet: `CredentialRevoked` carries an id for the problem document, and the all-zero UUID is the honest value for "there is no row" — better than inventing one or making the parameter optional and letting every consumer branch on `None`.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_tokens.py -v`
Expected: PASS (8 tests). `fake.token_requests == 1` in the first test is the assertion that matters most; if it is 5, the cache key is wrong.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail/tokens.py packages/core/tests/fakes/fake_gmail.py \
        packages/core/tests/test_gmail_tokens.py
git commit -m "feat(gmail): token refresh with an in-process cache, and invalid_grant as terminal"
```

---

### Task B1-6: The OAuth flow — PKCE, a single-use state, and refusing the wrong mailbox

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/oauth.py`
- Create: `packages/core/src/pigrocrm/core/gmail/repository.py`
- Create: `packages/core/tests/test_gmail_oauth.py`

**Interfaces:**
- Consumes: `GoogleTokenClient.exchange_code` and `GOOGLE_AUTH_URL` from B1-5; `GoogleAccount`/`GoogleOAuthState` from B1-3; `seal` from B1-3; `decode_google_token_key`/`require_gmail_configured` from B1-2; `ActivityService.record` (`activities/service.py`); `Actor`.
- Produces:
  ```python
  class GmailRepository:
      def __init__(self, session: Session) -> None: ...
      def account_for_user(self, user_id: UUID) -> GoogleAccount | None: ...
      def account(self, account_id: UUID) -> GoogleAccount | None: ...
      def add_state(self, state: GoogleOAuthState) -> GoogleOAuthState: ...
      def consume_state(self, jti: str, now: datetime) -> GoogleOAuthState | None: ...
      def prune_states(self, now: datetime) -> int: ...
      # `list`-named methods, if any are added later, go LAST in this class.

  class GmailOAuthService:
      def __init__(self, session: Session, *, settings: Settings, tokens: GoogleTokenClient) -> None: ...
      def start(self, actor: Actor) -> str: ...
      def complete(self, *, code: str, state: str, actor: Actor) -> GoogleAccountRead: ...
      def disconnect(self, *, delete_messages: bool, actor: Actor) -> None: ...
  ```
  Consumed by B1-13 (the router) and B1-15 (the settings panel).

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_oauth.py`:

```python
import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import unseal
from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState
from pigrocrm.core.gmail.oauth import GmailOAuthService
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES, SCOPE_SEND
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport
from tests.fakes.fake_gmail import FakeGmail

KEY_B64 = base64.b64encode(b"k" * 32).decode()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret": "x" * 32,
        "google_client_id": "cid.apps.googleusercontent.com",
        "google_client_secret": "the-secret",
        "google_token_key": KEY_B64,
        "public_url": "https://crm.example.it",
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def _id_token(sub: str, email: str) -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"sub": sub, "email": email}).encode())
    return f"h.{claims.decode().rstrip('=')}.s"


def _service(session: Session, fake: FakeGmail, settings: Settings | None = None) -> GmailOAuthService:
    resolved = settings or _settings()
    return GmailOAuthService(
        session,
        settings=resolved,
        tokens=GoogleTokenClient(
            client_id=resolved.google_client_id,
            client_secret=resolved.google_client_secret,
            transport=GmailTransport(http=fake, sleep=lambda _: None),
        ),
    )


def _user(session: Session, email: str = "owner@example.it") -> User:
    user = User(email=email, nome="Owner", password_hash="x", role="admin", attivo=True)
    session.add(user)
    session.flush()
    return user


def _actor(user: User) -> Actor:
    return Actor(id=user.id, type="user", role="admin")


def test_start_asks_for_offline_access_and_forces_the_consent_screen(db_session: Session) -> None:
    user = _user(db_session)
    url = _service(db_session, FakeGmail()).start(_actor(user))
    query = parse_qs(urlparse(url).query)
    assert query["access_type"] == ["offline"]
    # Without prompt=consent a repeat authorisation returns no refresh token at all.
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    assert set(query["scope"][0].split()) == set(REQUESTED_SCOPES)
    assert query["redirect_uri"] == ["https://crm.example.it/api/gmail/oauth/callback"]


def test_start_keeps_the_code_verifier_server_side(db_session: Session) -> None:
    """PKCE is worth nothing if the verifier travels through the browser. It lives in
    google_oauth_states; the signed `state` carries only a jti."""
    user = _user(db_session)
    url = _service(db_session, FakeGmail()).start(_actor(user))
    query = parse_qs(urlparse(url).query)
    row = db_session.execute(select(GoogleOAuthState)).scalars().one()
    assert row.code_verifier not in url
    assert row.code_verifier != query["code_challenge"][0]
    assert len(row.code_verifier) >= 43


def test_complete_stores_the_refresh_token_encrypted_and_records_the_connection(
    db_session: Session,
) -> None:
    user = _user(db_session)
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.id_token = _id_token("104729", "ada@acme.it")
    fake.refresh_token = "1//0gTheRealRefresh"
    service = _service(db_session, fake)
    url = service.start(_actor(user))
    state = parse_qs(urlparse(url).query)["state"][0]

    read = service.complete(code="4/0A-code", state=state, actor=_actor(user))
    db_session.commit()

    assert read.email_address == "ada@acme.it"
    assert read.status == "active"
    account = db_session.execute(select(GoogleAccount)).scalars().one()
    assert b"1//0gTheRealRefresh" not in account.refresh_token_ciphertext
    assert unseal(account.refresh_token_ciphertext, account.refresh_token_nonce, b"k" * 32) == (
        "1//0gTheRealRefresh"
    )
    kinds = db_session.execute(select(Activity.kind)).scalars().all()
    assert "gmail.account_collegato" in kinds


def test_a_state_can_only_be_used_once(db_session: Session) -> None:
    user = _user(db_session)
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.id_token = _id_token("104729", "ada@acme.it")
    service = _service(db_session, fake)
    state = parse_qs(urlparse(service.start(_actor(user))).query)["state"][0]
    service.complete(code="4/0A-code", state=state, actor=_actor(user))
    db_session.commit()

    with pytest.raises(Conflict) as caught:
        service.complete(code="4/0A-code", state=state, actor=_actor(user))
    # Deliberately does not say which check failed: signature, expiry, replay and
    # user mismatch all answer the same way.
    assert caught.value.message.count("autorizzazione") >= 1


def test_a_state_belonging_to_another_user_is_refused(db_session: Session) -> None:
    owner = _user(db_session, "owner@example.it")
    other = _user(db_session, "other@example.it")
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.id_token = _id_token("104729", "ada@acme.it")
    service = _service(db_session, fake)
    state = parse_qs(urlparse(service.start(_actor(owner))).query)["state"][0]
    with pytest.raises(Conflict):
        service.complete(code="4/0A-code", state=state, actor=_actor(other))


def test_an_expired_state_is_refused(db_session: Session) -> None:
    user = _user(db_session)
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.id_token = _id_token("104729", "ada@acme.it")
    service = _service(db_session, fake)
    state = parse_qs(urlparse(service.start(_actor(user))).query)["state"][0]
    row = db_session.execute(select(GoogleOAuthState)).scalars().one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    with pytest.raises(Conflict):
        service.complete(code="4/0A-code", state=state, actor=_actor(user))


def test_reconnecting_a_different_mailbox_is_refused_and_names_both(db_session: Session) -> None:
    """Silently relabelling the whole stored history because someone picked the wrong
    Google account in the chooser is the failure this refusal exists to prevent."""
    user = _user(db_session)
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.id_token = _id_token("104729", "ada@acme.it")
    service = _service(db_session, fake)
    service.complete(
        code="c1", state=parse_qs(urlparse(service.start(_actor(user))).query)["state"][0], actor=_actor(user)
    )
    db_session.commit()

    fake.id_token = _id_token("999999", "someone.else@gmail.com")
    with pytest.raises(Conflict) as caught:
        service.complete(
            code="c2",
            state=parse_qs(urlparse(service.start(_actor(user))).query)["state"][0],
            actor=_actor(user),
        )
    assert "ada@acme.it" in caught.value.message
    assert "someone.else@gmail.com" in caught.value.message


def test_a_partial_grant_is_stored_as_granted_and_stays_active(db_session: Session) -> None:
    """Spec 5.1: status describes the credential, capability is derived from the
    granted scopes at the point of use. Only gmail.send was granted here, so the
    account is healthy and it is *sync* that will refuse."""
    user = _user(db_session)
    fake = FakeGmail(granted_scopes=("openid", "email", SCOPE_SEND))
    fake.id_token = _id_token("104729", "ada@acme.it")
    service = _service(db_session, fake)
    read = service.complete(
        code="c", state=parse_qs(urlparse(service.start(_actor(user))).query)["state"][0], actor=_actor(user)
    )
    assert read.status == "active"
    assert SCOPE_SEND in read.scopes_granted
    assert "https://www.googleapis.com/auth/gmail.readonly" not in read.scopes_granted


def test_consent_expiry_is_set_only_while_the_client_is_unverified(db_session: Session) -> None:
    user = _user(db_session)
    fake = FakeGmail(granted_scopes=REQUESTED_SCOPES)
    fake.id_token = _id_token("104729", "ada@acme.it")
    service = _service(db_session, fake, _settings(google_app_unverified=True))
    read = service.complete(
        code="c", state=parse_qs(urlparse(service.start(_actor(user))).query)["state"][0], actor=_actor(user)
    )
    assert read.consent_expires_at is not None
    # Testing mode: Google expires a consumer refresh token seven days after consent.
    assert 6 < (read.consent_expires_at - datetime.now(UTC)).days <= 7


def test_an_unconfigured_installation_refuses_to_start(db_session: Session) -> None:
    user = _user(db_session)
    bare = _settings(google_client_id="")
    with pytest.raises(Conflict, match="non è configurato"):
        _service(db_session, FakeGmail(), bare).start(_actor(user))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_oauth.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.oauth'`.

- [ ] **Step 3: Write the repository**

`packages/core/src/pigrocrm/core/gmail/repository.py`:

```python
"""Queries only. Never commits -- the service owns the transaction."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState


class GmailRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def account_for_user(self, user_id: UUID) -> GoogleAccount | None:
        return self.session.execute(
            select(GoogleAccount).where(GoogleAccount.user_id == user_id)
        ).scalar_one_or_none()

    def account(self, account_id: UUID) -> GoogleAccount | None:
        return self.session.get(GoogleAccount, account_id)

    def add_state(self, state: GoogleOAuthState) -> GoogleOAuthState:
        self.session.add(state)
        self.session.flush()
        return state

    def consume_state(self, jti: str, now: datetime) -> GoogleOAuthState | None:
        """Marks the row consumed and returns it, or returns `None` if it does not
        exist, has expired, or was already consumed. One statement, so two concurrent
        callbacks carrying the same jti cannot both win: the second updates zero rows.
        """
        row = self.session.execute(
            select(GoogleOAuthState)
            .where(
                GoogleOAuthState.jti == jti,
                GoogleOAuthState.consumed_at.is_(None),
                GoogleOAuthState.expires_at > now,
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if row is None:
            return None
        row.consumed_at = now
        self.session.flush()
        return row

    def prune_states(self, now: datetime) -> int:
        """Called at the start of every sync. `refresh_tokens` has this same problem
        and, per residuo R8, no pruning at all -- this table does not repeat it."""
        result = self.session.execute(
            delete(GoogleOAuthState).where(GoogleOAuthState.expires_at < now)
        )
        return int(result.rowcount or 0)
```

- [ ] **Step 4: Write the service**

`packages/core/src/pigrocrm/core/gmail/oauth.py`:

```python
"""Authorization-code flow with PKCE, server-side.

The `code_verifier` lives in `google_oauth_states`, not in the signed state: putting it
in the state would make it readable by the browser and cancel PKCE. The state itself is
a five-minute JWT carrying a single-use `jti` and the CRM user's id, minted with the
machinery already in `auth/tokens.py` -- no new cryptography.
"""

import base64
import hashlib
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, decode_google_token_key, require_gmail_configured
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import seal
from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES, GoogleAccountRead
from pigrocrm.core.gmail.tokens import GOOGLE_AUTH_URL, GoogleTokenClient

STATE_TTL_MINUTES = 5
# Testing-mode consumer refresh tokens expire seven days after consent. Google exposes
# no API to detect verification status, so the operator declares it.
UNVERIFIED_CONSENT_DAYS = 7
_VERIFIER_BYTES = 48  # 64 base64url characters, inside PKCE's 43-128 range


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class GmailOAuthService:
    def __init__(
        self, session: Session, *, settings: Settings, tokens: GoogleTokenClient
    ) -> None:
        self.session = session
        self.settings = settings
        self.tokens = tokens
        self.repo = GmailRepository(session)
        self.activities = ActivityService(session)

    @property
    def redirect_uri(self) -> str:
        # One fixed, configured string. Google compares it character for character.
        return f"{self.settings.public_url.rstrip('/')}/api/gmail/oauth/callback"

    def start(self, actor: Actor) -> str:
        require_gmail_configured(self.settings)
        actor.require_write("collegare un account Google")
        if actor.id is None:
            raise Conflict("google_account", "solo un utente può collegare una casella Google")

        verifier = _b64url(os.urandom(_VERIFIER_BYTES))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        jti = _b64url(os.urandom(24))
        now = datetime.now(UTC)
        self.repo.add_state(
            GoogleOAuthState(
                jti=jti,
                code_verifier=verifier,
                user_id=actor.id,
                expires_at=now + timedelta(minutes=STATE_TTL_MINUTES),
            )
        )
        self.session.commit()

        return f"{GOOGLE_AUTH_URL}?" + urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(REQUESTED_SCOPES),
                "access_type": "offline",
                # Without this, a repeat authorisation returns no refresh token.
                "prompt": "consent",
                "include_granted_scopes": "false",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": jti,
            }
        )

    def complete(self, *, code: str, state: str, actor: Actor) -> GoogleAccountRead:
        require_gmail_configured(self.settings)
        actor.require_write("collegare un account Google")
        now = datetime.now(UTC)

        row = self.repo.consume_state(state, now)
        # One message for every failure -- unknown jti, expired, replayed, or belonging
        # to another session. Saying which one leaked would tell an attacker which half
        # of the attack worked.
        if row is None or row.user_id != actor.id:
            self.session.rollback()
            raise Conflict(
                "google_account",
                "questa autorizzazione non è più valida: ricomincia da "
                "Impostazioni → Gmail",
            )

        grant = self.tokens.exchange_code(
            code=code, code_verifier=row.code_verifier, redirect_uri=self.redirect_uri
        )

        existing = self.repo.account_for_user(actor.id) if actor.id else None
        if existing is not None and existing.google_sub != grant.subject:
            self.session.rollback()
            raise Conflict(
                "google_account",
                f"questa installazione è collegata a {existing.email_address}, non a "
                f"{grant.email_address}: scollega prima l'account attuale",
                connected=existing.email_address,
                offered=grant.email_address,
            )

        ciphertext, nonce = seal(grant.refresh_token, decode_google_token_key(self.settings))
        consent_expires_at = (
            now + timedelta(days=UNVERIFIED_CONSENT_DAYS)
            if self.settings.google_app_unverified
            else None
        )

        if existing is None:
            account = GoogleAccount(
                user_id=actor.id,
                google_sub=grant.subject,
                email_address=grant.email_address,
                refresh_token_ciphertext=ciphertext,
                refresh_token_nonce=nonce,
                scopes_granted=list(grant.scopes),
                status="active",
                consent_expires_at=consent_expires_at,
            )
            self.session.add(account)
            self.session.flush()
        else:
            account = existing
            account.refresh_token_ciphertext = ciphertext
            account.refresh_token_nonce = nonce
            account.scopes_granted = list(grant.scopes)
            account.status = "active"
            account.consent_expires_at = consent_expires_at
            account.last_error = None
            account.last_error_at = None
            account.disconnected_at = None
            self.session.flush()

        self.tokens.forget(account.id)
        # Last thing before the commit: ActivityService.record flushes and joins this
        # transaction, so nothing may commit after it on this session.
        self.activities.record(
            "google_account",
            account.id,
            "gmail.account_collegato",
            actor,
            {"email_address": account.email_address, "scopes_granted": list(grant.scopes)},
        )
        self.session.commit()
        return GoogleAccountRead.model_validate(account)

    def disconnect(self, *, delete_messages: bool, actor: Actor) -> None:
        """Offers to delete the stored messages; never does it on its own. Deleting a
        customer's correspondence because a token expired would be a disaster, so the
        choice is recorded in the timeline."""
        actor.require_write("scollegare un account Google")
        if actor.id is None:
            raise Conflict("google_account", "solo un utente può scollegare una casella Google")
        account = self.repo.account_for_user(actor.id)
        if account is None:
            raise Conflict("google_account", "nessuna casella Google collegata")

        if delete_messages:
            self.repo.delete_messages_for(account.id)  # added in Task B1-8

        account.status = "revoked"
        account.disconnected_at = datetime.now(UTC)
        # Overwritten, not merely dereferenced: leaving the ciphertext behind means the
        # credential is still in every backup taken after the disconnect.
        account.refresh_token_ciphertext = b""
        account.refresh_token_nonce = b""
        self.tokens.forget(account.id)
        self.activities.record(
            "google_account",
            account.id,
            "gmail.account_scollegato",
            actor,
            {"email_address": account.email_address, "messaggi_cancellati": delete_messages},
        )
        self.session.commit()
```

`disconnect` calls `self.repo.delete_messages_for`, which Task B1-8 adds along with the `gmail_messages` table. Until B1-8 lands, `disconnect` is exercised only with `delete_messages=False`; B1-8's step 6 adds the method and the test for `True`.

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_oauth.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail/oauth.py packages/core/src/pigrocrm/core/gmail/repository.py \
        packages/core/tests/test_gmail_oauth.py
git commit -m "feat(gmail): PKCE OAuth with a single-use state and a mailbox-identity check"
```

---

### Task B1-7: Relevance as a mechanism — every listing carries an address filter

**The first hard part.** Spec §4.1 is not a policy, it is a constraint that must be impossible to violate: *"Every call to `users.messages.list` carries a `q` containing at least one email address known to the CRM. A `list` without a `q` is a bug"* — proven by inspecting the fake transport's recorded requests, not by a comment.

Two independent guards, because either alone can be defeated by a future edit:
1. The only function that can build a `messages.list` URL **refuses** to build one whose `q` has no address clause.
2. A test reads `FakeGmail.requests` after a full sync and asserts the property over every recorded request.

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/query.py`
- Create: `packages/core/tests/test_gmail_query.py`

**Interfaces:**
- Consumes: `AddressRoster.known_addresses()` from B1-1; `Settings.gmail_sync_address_batch_size` from B1-2.
- Produces:
  ```python
  GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
  ADDRESS_BATCH_DEFAULT = 20
  MAX_RESULTS_PER_PAGE = 100

  def build_address_clause(addresses: Sequence[str]) -> str: ...
  def build_list_queries(addresses: Sequence[str], *, after_epoch: int,
                         batch_size: int = ADDRESS_BATCH_DEFAULT) -> tuple[str, ...]: ...
  def messages_list_url(query: str, *, page_token: str | None = None,
                        max_results: int = MAX_RESULTS_PER_PAGE) -> str: ...
  def thread_get_url(thread_id: str) -> str: ...
  def message_get_url(message_id: str) -> str: ...
  def rfc822msgid_query(message_id_header: str) -> str: ...
  ```
  Consumed by B1-8, B1-11 and 5B-2's reconciliation.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_query.py`:

```python
from urllib.parse import parse_qs, urlparse

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.gmail.query import (
    ADDRESS_BATCH_DEFAULT,
    build_address_clause,
    build_list_queries,
    messages_list_url,
    rfc822msgid_query,
    thread_get_url,
)


def test_the_default_batch_is_twenty_addresses() -> None:
    # Twenty, because Gmail's `q` has a practical length limit and twenty addresses
    # with two clauses each fit inside it with margin.
    assert ADDRESS_BATCH_DEFAULT == 20


def test_each_address_contributes_both_directions() -> None:
    clause = build_address_clause(["ada@acme.it", "bob@acme.it"])
    assert clause == "(from:ada@acme.it OR to:ada@acme.it OR from:bob@acme.it OR to:bob@acme.it)"


def test_an_empty_roster_produces_no_query_at_all() -> None:
    """Not an empty query -- no query. A sync with nothing to look for must issue zero
    requests, never one unfiltered request."""
    assert build_list_queries([], after_epoch=1_700_000_000) == ()


def test_addresses_are_batched_and_every_batch_keeps_the_filter() -> None:
    addresses = [f"user{n}@acme.it" for n in range(45)]
    queries = build_list_queries(addresses, after_epoch=1_700_000_000, batch_size=20)
    assert len(queries) == 3
    for query in queries:
        assert query.startswith("(from:")
        assert " after:1700000000" in query
        assert query.count("from:") == query.count("to:")
    # Every address appears exactly once across the batches: a dropped address is a
    # silently missing conversation.
    for address in addresses:
        assert sum(query.count(f"from:{address} ") + query.count(f"from:{address})") for query in queries) == 1


def test_after_is_epoch_seconds_and_never_a_date() -> None:
    """A date loses the hours and forces re-reading a whole day every cycle."""
    query = build_list_queries(["ada@acme.it"], after_epoch=1_723_766_400)
    assert "after:1723766400" in query[0]
    assert "after:2024/" not in query[0]


def test_an_address_that_could_break_out_of_the_query_is_refused() -> None:
    for hostile in ["ada@acme.it OR from:ceo@rival.com", "ada@acme.it)", 'ada"@acme.it', "ada acme@it"]:
        with pytest.raises(ValidationFailed) as caught:
            build_address_clause([hostile])
        assert caught.value.details["field"] == "address"


def test_the_list_url_refuses_a_query_without_an_address_clause() -> None:
    """Guard one of two. The only function that can build a messages.list URL will not
    build one that does not filter by a known address -- so the bug spec 4.1 names is
    not merely discouraged, it is unconstructible."""
    for bad in ["", "   ", "after:1700000000", "is:unread", "subject:fattura"]:
        with pytest.raises(ValidationFailed, match="senza un filtro"):
            messages_list_url(bad)


def test_the_list_url_accepts_a_query_that_does_filter() -> None:
    url = messages_list_url("(from:ada@acme.it OR to:ada@acme.it) after:1700000000", page_token="tok")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "gmail.googleapis.com"
    assert parsed.path == "/gmail/v1/users/me/messages"
    assert query["q"] == ["(from:ada@acme.it OR to:ada@acme.it) after:1700000000"]
    assert query["pageToken"] == ["tok"]
    assert query["maxResults"] == ["100"]


def test_the_reconciliation_query_is_the_one_exception_and_is_still_specific() -> None:
    """rfc822msgid: names one exact message we ourselves generated. It is not a search
    of the mailbox, which is why it is allowed past the address-filter guard."""
    query = rfc822msgid_query("<abc.123@crm.example.it>")
    assert query == "rfc822msgid:abc.123@crm.example.it"
    assert messages_list_url(query)


def test_no_helper_can_build_a_url_that_takes_a_caller_supplied_search_string() -> None:
    """Spec 8.2 and 12: no surface in this slice accepts a Gmail search string. The
    module exposes exactly these builders, and none of them takes free text."""
    import inspect

    from pigrocrm.core.gmail import query as module

    exported = [
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and inspect.isfunction(value)
    ]
    assert sorted(exported) == [
        "build_address_clause",
        "build_list_queries",
        "message_get_url",
        "messages_list_url",
        "rfc822msgid_query",
        "thread_get_url",
    ]


def test_thread_get_asks_for_the_full_format() -> None:
    url = thread_get_url("thread-1")
    assert url.endswith("/threads/thread-1?format=full")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_query.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.query'`.

- [ ] **Step 3: Write the module**

`packages/core/src/pigrocrm/core/gmail/query.py`:

```python
"""The relevance mechanism, as pure functions.

Spec 4 names the failure mode to avoid: synchronising a mailbox. A mailbox holds the
newsletters, the Amazon receipts, the messages from the children's school, and the
conversations with clients. Ingesting all of it and filtering afterwards means all of
it went through the process -- a broken promise even if 98% is then discarded.

So the filter is applied *server-side*, inside the `q`, and this module is the only
place a `messages.list` URL can be built. `messages_list_url` refuses a query with no
address clause, which makes the bug spec 4.1 names unconstructible rather than merely
forbidden. `tests/test_gmail_sync.py` then asserts the same property over the requests
the fake transport actually received, because one guard in the code is one edit away
from being removed.
"""

import re
from collections.abc import Sequence
from urllib.parse import urlencode

from pigrocrm.core.errors import ValidationFailed

GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
# Twenty: Gmail's `q` has a practical length limit, and twenty addresses at two clauses
# each fit with margin. Configurable via PIGROCRM_GMAIL_SYNC_ADDRESS_BATCH_SIZE so the
# number can be corrected without touching code.
ADDRESS_BATCH_DEFAULT = 20
MAX_RESULTS_PER_PAGE = 100

# Deliberately stricter than RFC 5322: this string is interpolated into a Gmail query
# expression, so anything that could terminate a clause or introduce an operator has to
# be impossible, not merely unusual. re.fullmatch, never re.match with `$`.
_SAFE_ADDRESS = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,63}")
# What makes a query legitimate: at least one address-bearing clause.
_HAS_ADDRESS_CLAUSE = re.compile(r"\b(?:from|to|cc|bcc|rfc822msgid):\S")


def _checked(address: str) -> str:
    normalised = address.strip().lower()
    if not _SAFE_ADDRESS.fullmatch(normalised):
        raise ValidationFailed(
            "gmail_query",
            "address",
            "non è un indirizzo email interpolabile in una query Gmail",
            expected="local@dominio.tld, senza spazi, parentesi o virgolette",
        )
    return normalised


def build_address_clause(addresses: Sequence[str]) -> str:
    """`(from:a OR to:a OR from:b OR to:b …)` -- both directions per address, because a
    conversation is relevant whoever started it."""
    if not addresses:
        raise ValidationFailed(
            "gmail_query", "addresses", "una clausola di indirizzi non può essere vuota"
        )
    terms: list[str] = []
    for address in addresses:
        safe = _checked(address)
        terms.append(f"from:{safe}")
        terms.append(f"to:{safe}")
    return "(" + " OR ".join(terms) + ")"


def build_list_queries(
    addresses: Sequence[str], *, after_epoch: int, batch_size: int = ADDRESS_BATCH_DEFAULT
) -> tuple[str, ...]:
    """One query per batch of addresses. An empty roster yields **no** queries -- not
    one unfiltered query, which is the whole point.

    `after:` takes epoch seconds, not a date: a date loses the hours and forces
    re-reading an entire day on every cycle.
    """
    if batch_size < 1:
        raise ValidationFailed(
            "gmail_query", "batch_size", "deve essere almeno 1", expected=">= 1"
        )
    if after_epoch < 0:
        raise ValidationFailed("gmail_query", "after_epoch", "non può essere negativo")
    unique = list(dict.fromkeys(_checked(address) for address in addresses))
    return tuple(
        f"{build_address_clause(unique[start:start + batch_size])} after:{after_epoch}"
        for start in range(0, len(unique), batch_size)
    )


def messages_list_url(
    query: str, *, page_token: str | None = None, max_results: int = MAX_RESULTS_PER_PAGE
) -> str:
    """The only way to build a `users.messages.list` URL in this codebase.

    It refuses a `q` with no address-bearing clause. That refusal is the mechanism of
    spec 4.1: a listing without an address filter cannot be constructed, so it cannot
    be shipped by accident.
    """
    if not _HAS_ADDRESS_CLAUSE.search(query):
        raise ValidationFailed(
            "gmail_query",
            "q",
            "un elenco di messaggi senza un filtro su un indirizzo noto è un bug, "
            "non una ricerca ampia",
            expected="una clausola from:, to: o rfc822msgid:",
        )
    params: dict[str, str] = {"q": query, "maxResults": str(max_results)}
    if page_token:
        params["pageToken"] = page_token
    return f"{GMAIL_API_ROOT}/messages?{urlencode(params)}"


def thread_get_url(thread_id: str) -> str:
    return f"{GMAIL_API_ROOT}/threads/{_checked_id(thread_id)}?format=full"


def message_get_url(message_id: str) -> str:
    return f"{GMAIL_API_ROOT}/messages/{_checked_id(message_id)}?format=full"


def rfc822msgid_query(message_id_header: str) -> str:
    """Finds one exact message by the `Message-ID` we generated ourselves. This is the
    one query in the slice that is not built from the address roster, and it is allowed
    because it is *more* specific, not less: it names a single message, and one we
    created. Used only by the send reconciliation of spec 6.3."""
    stripped = message_id_header.strip().strip("<>")
    if not _SAFE_ADDRESS.fullmatch(stripped):
        raise ValidationFailed(
            "gmail_query", "message_id_header", "non è un Message-ID interpolabile"
        )
    return f"rfc822msgid:{stripped}"


_SAFE_ID = re.compile(r"[A-Za-z0-9_\-]{1,128}")


def _checked_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValidationFailed(
            "gmail_query", "id", "un id Gmail contiene solo lettere, cifre, - e _"
        )
    return value
```

`_checked_id` and `_checked` are private, so they do not appear in the exported-functions test. Keep them private: that test is what stops a future free-text search helper from being added quietly.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_query.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail/query.py packages/core/tests/test_gmail_query.py
git commit -m "feat(gmail): a listing without an address filter is unconstructible"
```

---
### Task B1-8: `gmail_messages`, thread ascent, idempotency — and the request-inspection test

The second guard of spec §4.1 lands here: after a real sync against a mailbox of 1,000 irrelevant messages, **every request the fake transport recorded** is inspected.

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/parse.py`
- Create: `packages/core/src/pigrocrm/core/gmail/sync.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/models.py` (append `GmailMessage`, `GmailMessageLink`)
- Modify: `packages/core/src/pigrocrm/core/gmail/repository.py` (append message methods)
- Modify: `packages/core/src/pigrocrm/core/gmail/schemas.py` (append `SyncReport`, `GmailMessageRead`)
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Create: `packages/core/migrations/versions/0006_gmail_messages.py`
- Modify: `packages/core/tests/test_migrations.py:139,161` (`"0005"` → `"0006"`)
- Create: `packages/core/tests/test_gmail_parse.py`
- Create: `packages/core/tests/test_gmail_sync.py`

**Interfaces:**
- Consumes: `build_list_queries`, `messages_list_url`, `thread_get_url` from B1-7; `AddressRoster.known_addresses` from B1-1; `GoogleTokenClient.access_token` from B1-5; `GmailTransport.json` from B1-4; `Settings.gmail_body_max_bytes`, `gmail_watermark_overlap_hours`, `gmail_sync_address_batch_size` from B1-2.
- Produces:
  ```python
  # gmail/parse.py
  @dataclass(frozen=True)
  class ParsedAttachment:
      filename: str
      mime: str
      size: int

  @dataclass(frozen=True)
  class ParsedMessage:
      gmail_message_id: str
      gmail_thread_id: str
      message_id_header: str
      in_reply_to: str
      references: str
      from_address: str
      to_addresses: list[str]
      cc_addresses: list[str]
      subject: str
      snippet: str
      internal_date: datetime
      body_text: str
      body_truncated: bool
      body_html_scartato: bool
      attachments: list[ParsedAttachment]

  BODY_TRUNCATION_MARKER = "\n\n[…] messaggio troncato da PigroCRM"
  def parse_message(payload: dict[str, Any], *, body_max_bytes: int, store_bodies: bool) -> ParsedMessage: ...
  def header_addresses(raw: str) -> list[str]: ...

  # gmail/sync.py
  class GmailSyncService:
      def __init__(self, session: Session, *, settings: Settings, transport: GmailTransport,
                   tokens: GoogleTokenClient) -> None: ...
      def sync(self, actor: Actor) -> SyncReport: ...

  # gmail/schemas.py
  class SyncReport(BaseModel):
      started_at: datetime
      already_running: bool
      running_since: datetime | None
      queries_issued: int
      threads_fetched: int
      messages_stored: int
      messages_skipped: int
      links_created: int
      states_pruned: int
  ```
  Consumed by B1-9 (links), B1-10 (the lock), B1-11 (backfill), B1-13, B1-14, and 5B-2's reconciliation.

- [ ] **Step 1: Write the failing parse test**

`packages/core/tests/test_gmail_parse.py`:

```python
import base64
from datetime import UTC, datetime

from pigrocrm.core.gmail.parse import BODY_TRUNCATION_MARKER, header_addresses, parse_message


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX"],
        "snippet": "Ciao",
        "internalDate": "1723766400000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Ada Byron <ada@acme.it>"},
                {"name": "To", "value": "io@example.it"},
                {"name": "Subject", "value": "Offerta"},
                {"name": "Message-ID", "value": "<abc@acme.it>"},
            ],
            "parts": [],
            "body": {"data": _b64("Ciao, però è già così."), "size": 24},
        },
    }
    return {**base, **overrides}


def test_it_reads_the_headers_the_slice_actually_uses() -> None:
    parsed = parse_message(_payload(), body_max_bytes=262_144, store_bodies=True)
    assert parsed.gmail_message_id == "m1"
    assert parsed.gmail_thread_id == "t1"
    assert parsed.from_address == "ada@acme.it"
    assert parsed.to_addresses == ["io@example.it"]
    assert parsed.subject == "Offerta"
    assert parsed.message_id_header == "<abc@acme.it>"
    assert parsed.internal_date == datetime(2024, 8, 16, 0, 0, tzinfo=UTC)


def test_accented_and_typographic_text_survives_base64url_decoding() -> None:
    parsed = parse_message(_payload(), body_max_bytes=262_144, store_bodies=True)
    assert parsed.body_text == "Ciao, però è già così."


def test_base64url_without_padding_still_decodes() -> None:
    """Gmail strips the `=` padding. A decoder that requires it fails on roughly two
    messages in three."""
    unpadded = _b64("x" * 10)
    assert not unpadded.endswith("=")
    payload = _payload()
    payload["payload"]["body"] = {"data": unpadded, "size": 10}  # type: ignore[index]
    assert parse_message(payload, body_max_bytes=262_144, store_bodies=True).body_text == "x" * 10


def test_an_html_only_message_stores_the_text_conversion_and_flags_it() -> None:
    """Email HTML carries tracking pixels, remote CSS and script. Rendering it would
    make the CRM a beacon and an XSS surface. For the original there is 'open in
    Gmail'."""
    payload = _payload()
    payload["payload"] = {
        "mimeType": "text/html",
        "headers": [{"name": "From", "value": "ada@acme.it"}, {"name": "Subject", "value": "X"}],
        "parts": [],
        "body": {"data": _b64("<p>Ciao <b>Ada</b></p><script>evil()</script>"), "size": 44},
    }
    parsed = parse_message(payload, body_max_bytes=262_144, store_bodies=True)
    assert parsed.body_html_scartato is True
    assert "<script>" not in parsed.body_text
    assert "evil()" not in parsed.body_text
    assert "Ciao Ada" in parsed.body_text


def test_a_multipart_alternative_prefers_the_plain_part_and_flags_nothing() -> None:
    payload = _payload()
    payload["payload"] = {
        "mimeType": "multipart/alternative",
        "headers": [{"name": "From", "value": "ada@acme.it"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("testo semplice"), "size": 14}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>testo</p>"), "size": 12}},
        ],
        "body": {"size": 0},
    }
    parsed = parse_message(payload, body_max_bytes=262_144, store_bodies=True)
    assert parsed.body_text == "testo semplice"
    assert parsed.body_html_scartato is False


def test_a_long_body_is_truncated_with_a_marker_not_silently_cut() -> None:
    payload = _payload()
    payload["payload"]["body"] = {"data": _b64("a" * 5_000), "size": 5_000}  # type: ignore[index]
    parsed = parse_message(payload, body_max_bytes=1_000, store_bodies=True)
    assert parsed.body_truncated is True
    assert parsed.body_text.endswith(BODY_TRUNCATION_MARKER)
    assert len(parsed.body_text.encode()) <= 1_000 + len(BODY_TRUNCATION_MARKER.encode())


def test_truncation_never_splits_a_multibyte_character() -> None:
    payload = _payload()
    payload["payload"]["body"] = {"data": _b64("è" * 2_000), "size": 4_000}  # type: ignore[index]
    parsed = parse_message(payload, body_max_bytes=1_001, store_bodies=True)
    # A byte-slice at an odd offset inside a two-byte character would raise on decode,
    # or worse, store a replacement character. Neither is acceptable in stored mail.
    assert "�" not in parsed.body_text


def test_with_bodies_off_only_the_snippet_survives() -> None:
    parsed = parse_message(_payload(), body_max_bytes=262_144, store_bodies=False)
    assert parsed.body_text == ""
    assert parsed.snippet == "Ciao"


def test_attachments_keep_their_metadata_and_none_of_their_bytes() -> None:
    payload = _payload()
    payload["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "From", "value": "ada@acme.it"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("vedi allegato"), "size": 13}},
            {
                "mimeType": "application/pdf",
                "filename": "offerta.pdf",
                "body": {"attachmentId": "att-1", "size": 91_234},
            },
        ],
        "body": {"size": 0},
    }
    parsed = parse_message(payload, body_max_bytes=262_144, store_bodies=True)
    assert [(a.filename, a.mime, a.size) for a in parsed.attachments] == [
        ("offerta.pdf", "application/pdf", 91_234)
    ]
    # Not one byte: those would be gigabytes in slice 2's storage. The attachment that
    # matters is saved by an explicit action, through DocumentStorage.
    assert "attachmentId" not in str(parsed.attachments)


def test_header_addresses_splits_display_names_and_lowercases() -> None:
    assert header_addresses('Ada Byron <Ada@Acme.IT>, "Rossi, Bob" <bob@acme.it>') == [
        "ada@acme.it",
        "bob@acme.it",
    ]


def test_a_message_with_no_headers_at_all_parses_rather_than_raising() -> None:
    """Gmail returns thin payloads for drafts and for some system messages. A parser
    that raises here stops the whole sync on one odd row."""
    parsed = parse_message(
        {"id": "m9", "threadId": "t9", "internalDate": "0", "payload": {"headers": []}},
        body_max_bytes=262_144,
        store_bodies=True,
    )
    assert parsed.from_address == ""
    assert parsed.subject == ""
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_parse.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.parse'`.

- [ ] **Step 3: Write the parser**

`packages/core/src/pigrocrm/core/gmail/parse.py`:

```python
"""Gmail's `format=full` JSON, turned into the shapes this slice stores.

Positions taken, all from spec 5.4:

* **Only `text/plain`.** If a message is HTML-only, the text conversion is stored and
  `body_html_scartato` is set. Email HTML carries tracking pixels, remote CSS and
  script; rendering it would make the CRM a beacon and an XSS surface. For the original
  there is "open in Gmail".
* **Bodies are truncated with a marker**, at `gmail_body_max_bytes` (256 KB), the same
  discipline as `activities/sanitize.py`: a generous limit that only bites on the
  anomalous.
* **No attachment bytes**, ever. Name, MIME type and size only.
* Nothing here raises on an odd message. A parser that throws stops an entire sync on
  one strange row, and mailboxes are full of strange rows.
"""

import base64
import binascii
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

BODY_TRUNCATION_MARKER = "\n\n[…] messaggio troncato da PigroCRM"

_ADDRESS_IN_HEADER = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}")
_TAG = re.compile(r"<[^>]+>")
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WHITESPACE = re.compile(r"[ \t]*\n[ \t]*")


@dataclass(frozen=True)
class ParsedAttachment:
    filename: str
    mime: str
    size: int


@dataclass(frozen=True)
class ParsedMessage:
    gmail_message_id: str
    gmail_thread_id: str
    message_id_header: str
    in_reply_to: str
    references: str
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: str
    snippet: str
    internal_date: datetime
    body_text: str
    body_truncated: bool
    body_html_scartato: bool
    attachments: list[ParsedAttachment] = field(default_factory=list)


def header_addresses(raw: str) -> list[str]:
    """Every address in a `To`/`Cc` header, lowercased and deduplicated. A regex rather
    than `email.utils.getaddresses` because a display name containing a comma --
    `"Rossi, Bob" <bob@acme.it>` -- is exactly where naive splitting invents a
    recipient, and because only the addresses are stored."""
    return list(dict.fromkeys(match.group(0).lower() for match in _ADDRESS_IN_HEADER.finditer(raw)))


def _decode_b64url(data: str) -> str:
    """Gmail strips the `=` padding; a decoder that requires it fails on most
    messages. `errors="replace"` is deliberately *not* used -- a body that will not
    decode is stored empty rather than sprinkled with replacement characters."""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return ""


def _html_to_text(html: str) -> str:
    without_code = _SCRIPT_OR_STYLE.sub(" ", html)
    text = _TAG.sub("", without_code)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return _WHITESPACE.sub("\n", text).strip()


def _truncate(text: str, body_max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= body_max_bytes:
        return text, False
    # Decode with errors="ignore" so a cut landing inside a multi-byte character drops
    # that character rather than storing U+FFFD. Stored mail with replacement
    # characters in it is mail nobody trusts.
    return encoded[:body_max_bytes].decode("utf-8", errors="ignore") + BODY_TRUNCATION_MARKER, True


def _walk(part: dict[str, Any]) -> list[dict[str, Any]]:
    found = [part]
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            found.extend(_walk(child))
    return found


def parse_message(
    payload: dict[str, Any], *, body_max_bytes: int, store_bodies: bool
) -> ParsedMessage:
    root = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    headers = {
        str(entry.get("name", "")).lower(): str(entry.get("value", ""))
        for entry in (root.get("headers") or [])
        if isinstance(entry, dict)
    }

    parts = _walk(root)
    plain = next(
        (p for p in parts if p.get("mimeType") == "text/plain" and (p.get("body") or {}).get("data")),
        None,
    )
    html = next(
        (p for p in parts if p.get("mimeType") == "text/html" and (p.get("body") or {}).get("data")),
        None,
    )

    body_text = ""
    body_truncated = False
    html_discarded = False
    if store_bodies:
        if plain is not None:
            body_text = _decode_b64url(str((plain.get("body") or {}).get("data") or ""))
        elif html is not None:
            body_text = _html_to_text(_decode_b64url(str((html.get("body") or {}).get("data") or "")))
            html_discarded = True
        body_text, body_truncated = _truncate(body_text, body_max_bytes)

    attachments = [
        ParsedAttachment(
            filename=str(part.get("filename") or ""),
            mime=str(part.get("mimeType") or "application/octet-stream"),
            size=int((part.get("body") or {}).get("size") or 0),
        )
        for part in parts
        if part.get("filename")
    ]

    try:
        internal_ms = int(payload.get("internalDate") or 0)
    except (TypeError, ValueError):
        internal_ms = 0

    from_addresses = header_addresses(headers.get("from", ""))
    return ParsedMessage(
        gmail_message_id=str(payload.get("id") or ""),
        gmail_thread_id=str(payload.get("threadId") or ""),
        message_id_header=headers.get("message-id", ""),
        in_reply_to=headers.get("in-reply-to", ""),
        references=headers.get("references", ""),
        from_address=from_addresses[0] if from_addresses else "",
        to_addresses=header_addresses(headers.get("to", "")),
        cc_addresses=header_addresses(headers.get("cc", "")),
        subject=headers.get("subject", ""),
        snippet=str(payload.get("snippet") or ""),
        internal_date=datetime.fromtimestamp(internal_ms / 1000, tz=UTC),
        body_text=body_text,
        body_truncated=body_truncated,
        body_html_scartato=html_discarded,
        attachments=attachments,
    )
```

`body_html_scartato` keeps the spec's Italian spelling because the spec names the column, and a column called one thing in the design and another in the schema is how a review question becomes an investigation. It is added to the Italian-terms list in the Global Constraints.

- [ ] **Step 4: Run the parse test**

Run: `uv run pytest packages/core/tests/test_gmail_parse.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Write the failing sync test — including the request inspection**

`packages/core/tests/test_gmail_sync.py`:

```python
import base64
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.gmail.models import GmailMessage
from pigrocrm.core.gmail.query import ADDRESS_BATCH_DEFAULT
from pigrocrm.core.gmail.sync import GmailSyncService
from pigrocrm.core.people.models import Person
from tests.fakes.fake_gmail import FakeGmail, FakeMessage

# Test helpers `connected_account`, `sync_service` and `_actor` live in
# packages/core/tests/fakes/gmail_fixtures.py, added by this step: they build a User,
# a GoogleAccount with a sealed refresh token, and a GmailSyncService wired to a
# FakeGmail. Every 5B test uses them, so they are written once.
from tests.fakes.gmail_fixtures import connected_account, sync_service


def _message(index: int, *, frm: str, to: str, thread: str, when_ms: int) -> FakeMessage:
    return FakeMessage(
        id=f"m{index}",
        thread_id=thread,
        headers={
            "From": frm,
            "To": to,
            "Subject": f"Oggetto {index}",
            "Message-ID": f"<msg{index}@example.it>",
        },
        body_text=f"corpo {index}",
        internal_date_ms=when_ms,
    )


def _noise(fake: FakeGmail, count: int) -> None:
    """A realistic mailbox: newsletters, receipts, the children's school."""
    base = 1_700_000_000_000
    for index in range(count):
        fake.messages[f"n{index}"] = FakeMessage(
            id=f"n{index}",
            thread_id=f"nt{index}",
            headers={
                "From": f"newsletter{index}@spam.example",
                "To": "io@example.it",
                "Subject": "Offerta imperdibile",
                "Message-ID": f"<n{index}@spam.example>",
            },
            body_text="compra",
            internal_date_ms=base + index,
        )


def test_a_thousand_irrelevant_messages_and_two_known_addresses(db_session: Session) -> None:
    """Spec 13, criterion 1."""
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email="info@acme.it")
    db_session.add(customer)
    db_session.flush()
    db_session.add(Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id))
    db_session.flush()

    fake = FakeGmail()
    _noise(fake, 1_000)
    fake.messages["m1"] = _message(1, frm="ada@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_500_000)
    fake.messages["m2"] = _message(2, frm="io@example.it", to="info@acme.it", thread="t2", when_ms=1_700_000_600_000)

    report = sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    db_session.commit()

    stored = db_session.execute(select(GmailMessage.gmail_message_id)).scalars().all()
    assert sorted(stored) == ["m1", "m2"]
    assert report.messages_stored == 2


def test_no_messages_list_is_ever_issued_without_an_address_filter(db_session: Session) -> None:
    """The adversarial test spec 4.1 asks for by name: it inspects the requests the
    fake transport *received*, rather than trusting a rule written in a comment. Guard
    one lives in `messages_list_url`; this is guard two, and both are needed, because a
    single guard is one edit away from being removed."""
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email="info@acme.it")
    db_session.add(customer)
    db_session.flush()
    db_session.add(Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id))
    db_session.flush()
    known = {"info@acme.it", "ada@acme.it"}

    fake = FakeGmail()
    _noise(fake, 50)
    fake.messages["m1"] = _message(1, frm="ada@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_500_000)
    sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))

    listings = [request for request in fake.requests if request.is_messages_list]
    assert listings, "the sync issued no listing at all, so this test proves nothing"
    for request in listings:
        assert request.q, f"a messages.list with no q: {request.path}?{request.query}"
        assert any(f"from:{address}" in request.q for address in known), (
            f"a q with no known address in it: {request.q}"
        )
    # And nothing in the whole sync asked Gmail to send anything (spec 13, criterion 15).
    assert [request for request in fake.requests if request.is_messages_send] == []


def test_an_empty_roster_issues_no_request_at_all(db_session: Session) -> None:
    """Not one unfiltered listing: none. This is the shape of the failure spec 4 exists
    to prevent, so it gets its own test."""
    account = connected_account(db_session)
    fake = FakeGmail()
    _noise(fake, 10)
    report = sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    assert [request for request in fake.requests if request.is_messages_list] == []
    assert report.queries_issued == 0
    assert report.messages_stored == 0


def test_addresses_are_asked_in_batches_of_twenty(db_session: Session) -> None:
    account = connected_account(db_session)
    for index in range(45):
        db_session.add(Customer(ragione_sociale=f"C{index}", email=f"c{index}@acme.it"))
    db_session.flush()

    fake = FakeGmail()
    sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    listings = [request for request in fake.requests if request.is_messages_list]
    assert len(listings) == 3
    for request in listings:
        assert (request.q or "").count("from:") <= ADDRESS_BATCH_DEFAULT


def test_running_the_sync_twice_produces_the_same_rows(db_session: Session) -> None:
    """Spec 13, criterion 2. The `(google_account_id, gmail_message_id)` unique
    constraint is what makes the watermark's deliberate 24-hour overlap free."""
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.flush()

    fake = FakeGmail()
    fake.messages["m1"] = _message(1, frm="info@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_500_000)
    actor = Actor(id=account.user_id, type="user", role="admin")
    service = sync_service(db_session, fake)
    service.sync(actor)
    db_session.commit()
    first = db_session.execute(select(func.count()).select_from(GmailMessage)).scalar_one()
    second_report = service.sync(actor)
    db_session.commit()
    assert db_session.execute(select(func.count()).select_from(GmailMessage)).scalar_one() == first
    assert second_report.messages_skipped >= 1


def test_the_watermark_moves_forward_but_overlaps_by_a_day(db_session: Session) -> None:
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.flush()
    fake = FakeGmail()
    before = datetime.now(UTC)
    sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    db_session.commit()
    db_session.refresh(account)
    assert account.last_sync_at is not None
    assert account.sync_watermark is not None
    # Deliberate overlap: it costs almost nothing and it absorbs a message that arrived
    # across the boundary of two runs.
    assert account.sync_watermark <= before - timedelta(hours=23)


def test_a_whole_thread_is_stored_including_participants_we_do_not_know(
    db_session: Session,
) -> None:
    """Spec 4.3. A conversation read halfway is worse than one not read: if the client
    writes, a colleague replies in copy and the client confirms, keeping only the first
    and third produces a thread that lies."""
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.flush()

    fake = FakeGmail()
    fake.messages["m1"] = _message(1, frm="info@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_500_000)
    fake.messages["m2"] = _message(2, frm="collega@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_600_000)
    fake.messages["m3"] = _message(3, frm="io@example.it", to="info@acme.it", thread="t1", when_ms=1_700_000_700_000)
    sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    db_session.commit()

    assert sorted(db_session.execute(select(GmailMessage.gmail_message_id)).scalars().all()) == ["m1", "m2", "m3"]


def test_an_unknown_sender_met_inside_a_thread_does_not_join_the_roster(
    db_session: Session,
) -> None:
    """Spec 4.3, the cost stated plainly. If those addresses entered the roster,
    relevance would widen by itself on every cycle -- exactly the failure mode of spec
    4."""
    from pigrocrm.core.gmail.roster import AddressRoster

    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.flush()
    fake = FakeGmail()
    fake.messages["m1"] = _message(1, frm="info@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_500_000)
    fake.messages["m2"] = _message(2, frm="stranger@elsewhere.com", to="io@example.it", thread="t1", when_ms=1_700_000_600_000)
    sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    db_session.commit()

    assert "stranger@elsewhere.com" not in AddressRoster(db_session).known_addresses()


def test_direction_is_recorded_from_the_connected_mailbox(db_session: Session) -> None:
    account = connected_account(db_session, email_address="io@example.it")
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.flush()
    fake = FakeGmail()
    fake.messages["m1"] = _message(1, frm="info@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_500_000)
    fake.messages["m2"] = _message(2, frm="io@example.it", to="info@acme.it", thread="t1", when_ms=1_700_000_600_000)
    sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    db_session.commit()

    rows = {
        row.gmail_message_id: row.direction
        for row in db_session.execute(select(GmailMessage)).scalars().all()
    }
    assert rows == {"m1": "inbound", "m2": "outbound"}


def test_with_store_bodies_off_only_the_snippet_is_kept(db_session: Session) -> None:
    account = connected_account(db_session)
    account.gmail_store_bodies = False
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.flush()
    fake = FakeGmail()
    fake.messages["m1"] = _message(1, frm="info@acme.it", to="io@example.it", thread="t1", when_ms=1_700_000_500_000)
    sync_service(db_session, fake).sync(Actor(id=account.user_id, type="user", role="admin"))
    db_session.commit()
    row = db_session.execute(select(GmailMessage)).scalars().one()
    assert row.body_text == ""
    assert row.snippet != ""
```

And the shared fixture module, `packages/core/tests/fakes/gmail_fixtures.py`:

```python
"""Builders every 5B test needs: a user, a connected account with a sealed refresh
token, and a service wired to a FakeGmail through the transport seam."""

import base64
from uuid import uuid4

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.gmail.crypto import seal
from pigrocrm.core.gmail.models import GoogleAccount
from pigrocrm.core.gmail.schemas import REQUESTED_SCOPES
from pigrocrm.core.gmail.sync import GmailSyncService
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport
from tests.fakes.fake_gmail import FakeGmail

TOKEN_KEY = b"k" * 32
REFRESH_TOKEN = "1//0gFixtureRefreshToken"


def gmail_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret": "x" * 32,
        "google_client_id": "cid.apps.googleusercontent.com",
        "google_client_secret": "the-secret",
        "google_token_key": base64.b64encode(TOKEN_KEY).decode(),
        "public_url": "https://crm.example.it",
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def connected_account(
    session: Session,
    *,
    email_address: str = "io@example.it",
    scopes: tuple[str, ...] = REQUESTED_SCOPES,
    status: str = "active",
) -> GoogleAccount:
    user = User(
        email=f"user-{uuid4().hex[:8]}@example.it",
        nome="Owner",
        password_hash="x",
        role="admin",
        attivo=True,
    )
    session.add(user)
    session.flush()
    ciphertext, nonce = seal(REFRESH_TOKEN, TOKEN_KEY)
    account = GoogleAccount(
        user_id=user.id,
        google_sub=f"sub-{user.id}",
        email_address=email_address,
        refresh_token_ciphertext=ciphertext,
        refresh_token_nonce=nonce,
        scopes_granted=list(scopes),
        status=status,
    )
    session.add(account)
    session.flush()
    return account


def actor_for(account: GoogleAccount) -> Actor:
    return Actor(id=account.user_id, type="user", role="admin")


def sync_service(
    session: Session, fake: FakeGmail, *, settings: Settings | None = None
) -> GmailSyncService:
    resolved = settings or gmail_settings()
    transport = GmailTransport(http=fake, sleep=lambda _: None)
    return GmailSyncService(
        session,
        settings=resolved,
        transport=transport,
        tokens=GoogleTokenClient(
            client_id=resolved.google_client_id,
            client_secret=resolved.google_client_secret,
            transport=transport,
        ),
    )
```

- [ ] **Step 6: Write the models, the repository methods and the sync service**

Append to `packages/core/src/pigrocrm/core/gmail/models.py`:

```python
class GmailMessage(Base, PrimaryKeyMixin, TimestampMixin):
    """One synchronised message.

    The unique constraint on `(google_account_id, gmail_message_id)` is what makes the
    watermark's deliberate 24-hour overlap free and every re-run idempotent. Acme kept
    its send record in a JSON file on disk with a non-atomic read-modify-write, so two
    concurrent sends lost the count; a unique constraint cannot lose anything.
    """

    __tablename__ = "gmail_messages"
    __table_args__ = (
        UniqueConstraint("google_account_id", "gmail_message_id", name="uq_gmail_messages_account_message"),
        Index("ix_gmail_messages_thread_date", "gmail_thread_id", "internal_date"),
    )

    google_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("google_accounts.id", ondelete="CASCADE"), nullable=False
    )
    gmail_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id_header: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    in_reply_to: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    references: Mapped[str] = mapped_column(Text, nullable=False, default="")
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cc_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    snippet: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    internal_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    body_html_scartato: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # name, mime, size. No bytes, ever (spec 5.4).
    attachments: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)


class GmailMessageLink(Base, PrimaryKeyMixin, TimestampMixin):
    """Many-to-many, and not three nullable foreign keys: one email concerns the
    person, that person's customer and a deal all at once, and a single FK would force
    a choice the data does not support."""

    __tablename__ = "gmail_message_links"
    __table_args__ = (
        UniqueConstraint(
            "gmail_message_id", "entity_type", "entity_id", name="uq_gmail_message_links_triple"
        ),
        Index("ix_gmail_message_links_entity", "entity_type", "entity_id"),
    )

    gmail_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("gmail_messages.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
```

Add `Index`, `Text`, `UniqueConstraint` and `datetime` to that module's imports.

`String(998)` on the header columns is RFC 5322's maximum line length minus the field name — the real bound, not a guessed one. Each needs a matching Pydantic `max_length=998` wherever it appears on a Create/Update schema; `GmailMessageRead` is read-only and takes none.

Append to `packages/core/src/pigrocrm/core/gmail/repository.py`:

```python
    def message_ids_present(self, account_id: UUID, gmail_ids: Sequence[str]) -> set[str]:
        if not gmail_ids:
            return set()
        rows = self.session.execute(
            select(GmailMessage.gmail_message_id).where(
                GmailMessage.google_account_id == account_id,
                GmailMessage.gmail_message_id.in_(list(gmail_ids)),
            )
        ).scalars().all()
        return set(rows)

    def add_message(self, message: GmailMessage) -> GmailMessage:
        self.session.add(message)
        self.session.flush()
        return message

    def message_by_gmail_id(self, account_id: UUID, gmail_id: str) -> GmailMessage | None:
        return self.session.execute(
            select(GmailMessage).where(
                GmailMessage.google_account_id == account_id,
                GmailMessage.gmail_message_id == gmail_id,
            )
        ).scalar_one_or_none()

    def delete_messages_for(self, account_id: UUID) -> int:
        """Called only when the user explicitly chose to on disconnect. The
        gmail_message_links rows go with them by ON DELETE CASCADE."""
        result = self.session.execute(
            delete(GmailMessage).where(GmailMessage.google_account_id == account_id)
        )
        return int(result.rowcount or 0)
```

`packages/core/src/pigrocrm/core/gmail/sync.py`:

```python
"""The incremental cycle.

No daemon: the sync runs on request -- a button, `POST /api/gmail/sync`, an MCP tool,
or a `docker compose run` from cron installed by the operator, the same scheme already
documented for the MCP server. This project has no worker process, and adding a queue
for one job is complexity that does not pay for itself today -- the same reasoning that
made slice 2's PDF render synchronous.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, decode_google_token_key, require_gmail_configured
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import unseal
from pigrocrm.core.gmail.models import GmailMessage, GoogleAccount
from pigrocrm.core.gmail.parse import ParsedMessage, parse_message
from pigrocrm.core.gmail.query import build_list_queries, messages_list_url, thread_get_url
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.roster import AddressRoster
from pigrocrm.core.gmail.schemas import SyncReport
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport

# How far back the first cycle looks when there is no watermark yet.
_FIRST_CYCLE_DAYS = 30


class GmailSyncService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        transport: GmailTransport,
        tokens: GoogleTokenClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.transport = transport
        self.tokens = tokens
        self.repo = GmailRepository(session)
        self.roster = AddressRoster(session)

    def sync(self, actor: Actor) -> SyncReport:
        require_gmail_configured(self.settings)
        actor.require_write("sincronizzare Gmail")
        account = self._account(actor)
        started_at = datetime.now(UTC)
        report = SyncReport(started_at=started_at)

        report.states_pruned = self.repo.prune_states(started_at)

        addresses = self.roster.known_addresses()
        after_epoch = int(self._window_start(account).timestamp())
        queries = build_list_queries(
            addresses,
            after_epoch=after_epoch,
            batch_size=self.settings.gmail_sync_address_batch_size,
        )
        report.queries_issued = len(queries)

        token = self._access_token(account)
        thread_ids: list[str] = []
        for query in queries:
            for entry in self._list_all(query, token):
                thread_id = str(entry.get("threadId") or "")
                if thread_id and thread_id not in thread_ids:
                    thread_ids.append(thread_id)

        for thread_id in thread_ids:
            report.threads_fetched += 1
            payload = self.transport.json(
                "GET", thread_get_url(thread_id), token=token, what="lettura di una conversazione"
            )
            for raw in payload.get("messages") or []:
                if not isinstance(raw, dict):
                    continue
                parsed = parse_message(
                    raw,
                    body_max_bytes=self.settings.gmail_body_max_bytes,
                    store_bodies=account.gmail_store_bodies,
                )
                if self._store(account, parsed):
                    report.messages_stored += 1
                else:
                    report.messages_skipped += 1

        account.last_sync_at = started_at
        # The watermark is rolled back by the configured overlap on every cycle. It is
        # free because the unique constraint makes re-insertion idempotent, and it is
        # what absorbs a message that arrived across the boundary of two runs.
        account.sync_watermark = started_at - timedelta(
            hours=self.settings.gmail_watermark_overlap_hours
        )
        self.session.commit()
        return report

    # ---- internals ---------------------------------------------------------------

    def _account(self, actor: Actor) -> GoogleAccount:
        if actor.id is None:
            raise Conflict("google_account", "solo un utente può sincronizzare una casella")
        account = self.repo.account_for_user(actor.id)
        if account is None:
            raise Conflict("google_account", "nessuna casella Google collegata")
        return account

    def _access_token(self, account: GoogleAccount) -> str:
        refresh_token = unseal(
            account.refresh_token_ciphertext,
            account.refresh_token_nonce,
            decode_google_token_key(self.settings),
        )
        return self.tokens.access_token(
            account_id=account.id,
            email_address=account.email_address,
            refresh_token=refresh_token,
        )

    def _window_start(self, account: GoogleAccount) -> datetime:
        if account.sync_watermark is not None:
            return account.sync_watermark
        return datetime.now(UTC) - timedelta(days=_FIRST_CYCLE_DAYS)

    def _list_all(self, query: str, token: str) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        page_token: str | None = None
        while True:
            payload = self.transport.json(
                "GET",
                messages_list_url(query, page_token=page_token),
                token=token,
                what="elenco dei messaggi",
            )
            entries.extend(
                entry for entry in (payload.get("messages") or []) if isinstance(entry, dict)
            )
            next_token = payload.get("nextPageToken")
            page_token = str(next_token) if next_token else None
            if page_token is None:
                return entries

    def _store(self, account: GoogleAccount, parsed: ParsedMessage) -> bool:
        """Returns True when a new row was written. A duplicate is not an error: it is
        the overlap doing its job."""
        if not parsed.gmail_message_id:
            return False
        if self.repo.message_by_gmail_id(account.id, parsed.gmail_message_id) is not None:
            return False
        row = GmailMessage(
            google_account_id=account.id,
            gmail_message_id=parsed.gmail_message_id,
            gmail_thread_id=parsed.gmail_thread_id,
            message_id_header=parsed.message_id_header[:998],
            in_reply_to=parsed.in_reply_to[:998],
            references=parsed.references,
            direction=(
                "outbound"
                if parsed.from_address == account.email_address.lower()
                else "inbound"
            ),
            from_address=parsed.from_address,
            to_addresses=list(parsed.to_addresses),
            cc_addresses=list(parsed.cc_addresses),
            subject=parsed.subject[:998],
            snippet=parsed.snippet[:500],
            internal_date=parsed.internal_date,
            body_text=parsed.body_text,
            body_truncated=parsed.body_truncated,
            body_html_scartato=parsed.body_html_scartato,
            attachments=[
                {"filename": a.filename, "mime": a.mime, "size": a.size} for a in parsed.attachments
            ],
        )
        try:
            self.repo.add_message(row)
        except IntegrityError:
            # A pre-check never replaces the constraint: two overlapping cycles both
            # pass the SELECT, and only the constraint stops the second. Without the
            # rollback the caller's session is poisoned for its next statement.
            self.session.rollback()
            return False
        return True
```

Append `SyncReport` and `GmailMessageRead` to `gmail/schemas.py`:

```python
class SyncReport(BaseModel):
    """What one cycle did. Returned by the REST endpoint and by the MCP tool, so an
    agent can diagnose instead of retrying."""

    started_at: datetime
    already_running: bool = False
    running_since: datetime | None = None
    queries_issued: int = 0
    threads_fetched: int = 0
    messages_stored: int = 0
    messages_skipped: int = 0
    links_created: int = 0
    states_pruned: int = 0


class GmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gmail_message_id: str
    gmail_thread_id: str
    direction: Literal["inbound", "outbound"]
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: str
    snippet: str
    internal_date: datetime
    body_text: str
    body_truncated: bool
    body_html_scartato: bool
    attachments: list[dict[str, object]]
```

`SyncReport` is mutated in place by `sync()`, so it must not be `frozen`. It is a response model, never an input, so it needs no `SafeStr` and no `max_length`.

- [ ] **Step 7: Migration, registry, and the revision bump**

Register both models in `models_registry.py`. Generate the migration, rename it to `0006_gmail_messages.py`, set `revision = "0006"` / `down_revision = "0005"`, and check the two unique constraints and the two indexes are present by the names given in `__table_args__`. Bump `test_migrations.py:139,161` to `"0006"`.

- [ ] **Step 8: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_sync.py packages/core/tests/test_gmail_parse.py packages/core/tests/test_migrations.py -v`
Expected: PASS. The two tests to read the output of carefully are `test_no_messages_list_is_ever_issued_without_an_address_filter` and `test_an_empty_roster_issues_no_request_at_all`: they are the mechanism, not a nicety.

- [ ] **Step 9: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/src/pigrocrm/core/models_registry.py \
        packages/core/migrations/versions/0006_gmail_messages.py packages/core/tests/fakes/gmail_fixtures.py \
        packages/core/tests/test_gmail_parse.py packages/core/tests/test_gmail_sync.py \
        packages/core/tests/test_migrations.py
git commit -m "feat(gmail): store only relevant threads, whole, idempotently"
```

---

### Task B1-9: Linking messages to entities, and the timeline entries

**Files:**
- Modify: `packages/core/src/pigrocrm/core/gmail/sync.py` (link after store)
- Modify: `packages/core/src/pigrocrm/core/gmail/repository.py` (link + query methods)
- Create: `packages/core/tests/test_gmail_links.py`

**Interfaces:**
- Consumes: `AddressRoster.resolve` and `EntityRef` from B1-1; `GmailMessageLink` from B1-8; `ActivityService.record`.
- Produces:
  ```python
  # repository.py
  def add_link(self, message_id: UUID, ref: EntityRef) -> bool: ...   # False if it already existed
  def messages_for_entity(self, entity_type: str, entity_id: UUID, *, limit: int) -> list[GmailMessage]: ...
  def last_inbound_from(self, account_id: UUID, addresses: Sequence[str], since: datetime) -> GmailMessage | None: ...
  ```
  `last_inbound_from` is consumed by 5B-2's reminder candidate list. `messages_for_entity` by B1-13 and B1-17.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_links.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.gmail.models import GmailMessage, GmailMessageLink
from pigrocrm.core.people.models import Person
from tests.fakes.fake_gmail import FakeGmail, FakeMessage
from tests.fakes.gmail_fixtures import actor_for, connected_account, sync_service


def _thread(fake: FakeGmail) -> None:
    fake.messages["m1"] = FakeMessage(
        id="m1",
        thread_id="t1",
        headers={
            "From": "ada@acme.it",
            "To": "io@example.it",
            "Subject": "Rinnovo",
            "Message-ID": "<m1@acme.it>",
        },
        body_text="Ciao",
        internal_date_ms=1_700_000_500_000,
    )
    fake.messages["m2"] = FakeMessage(
        id="m2",
        thread_id="t1",
        headers={
            "From": "stranger@elsewhere.com",
            "To": "io@example.it",
            "Subject": "Re: Rinnovo",
            "Message-ID": "<m2@elsewhere.com>",
        },
        body_text="Aggiungo",
        internal_date_ms=1_700_000_600_000,
    )


def test_an_email_appears_on_the_person_and_on_her_customer(db_session: Session) -> None:
    """Spec 13, criterion 3."""
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email=None)
    db_session.add(customer)
    db_session.flush()
    person = Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id)
    db_session.add(person)
    db_session.flush()
    deal = Deal(titolo="Rinnovo", customer_id=customer.id)
    db_session.add(deal)
    db_session.flush()

    fake = FakeGmail()
    _thread(fake)
    report = sync_service(db_session, fake).sync(actor_for(account))
    db_session.commit()

    first = db_session.execute(
        select(GmailMessage).where(GmailMessage.gmail_message_id == "m1")
    ).scalars().one()
    links = {
        (row.entity_type, row.entity_id)
        for row in db_session.execute(
            select(GmailMessageLink).where(GmailMessageLink.gmail_message_id == first.id)
        ).scalars().all()
    }
    assert links == {("person", person.id), ("customer", customer.id), ("deal", deal.id)}
    assert report.links_created >= 3


def test_a_sibling_message_from_a_stranger_is_stored_but_linked_through_the_thread(
    db_session: Session,
) -> None:
    """The stranger's own address resolves to nothing, so the link comes from the
    thread: the message belongs to the same conversation, and a conversation shown
    half-populated is the defect spec 4.3 exists to avoid."""
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email=None)
    db_session.add(customer)
    db_session.flush()
    db_session.add(Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id))
    db_session.flush()

    fake = FakeGmail()
    _thread(fake)
    sync_service(db_session, fake).sync(actor_for(account))
    db_session.commit()

    sibling = db_session.execute(
        select(GmailMessage).where(GmailMessage.gmail_message_id == "m2")
    ).scalars().one()
    entity_types = db_session.execute(
        select(GmailMessageLink.entity_type).where(GmailMessageLink.gmail_message_id == sibling.id)
    ).scalars().all()
    assert "customer" in entity_types


def test_syncing_twice_does_not_duplicate_a_link(db_session: Session) -> None:
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email=None)
    db_session.add(customer)
    db_session.flush()
    db_session.add(Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id))
    db_session.flush()
    fake = FakeGmail()
    _thread(fake)
    service = sync_service(db_session, fake)
    service.sync(actor_for(account))
    db_session.commit()
    before = len(db_session.execute(select(GmailMessageLink)).scalars().all())
    service.sync(actor_for(account))
    db_session.commit()
    assert len(db_session.execute(select(GmailMessageLink)).scalars().all()) == before


def test_a_received_message_writes_a_timeline_entry_on_the_linked_entity(
    db_session: Session,
) -> None:
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email=None)
    db_session.add(customer)
    db_session.flush()
    db_session.add(Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id))
    db_session.flush()
    fake = FakeGmail()
    _thread(fake)
    sync_service(db_session, fake).sync(actor_for(account))
    db_session.commit()

    rows = db_session.execute(
        select(Activity).where(Activity.kind == "gmail.messaggio_ricevuto")
    ).scalars().all()
    assert rows, "an inbound message must be visible on the timeline it belongs to"
    assert {row.entity_type for row in rows} <= {"customer", "person", "deal"}
    # activities/sanitize.py's own docstring cites "recording, say, an inbound email's
    # subject line" as the reason a payload is sanitised rather than validated. The
    # extension point was written with this in mind.
    assert any("Rinnovo" in str(row.payload.get("subject", "")) for row in rows)


def test_the_sync_itself_is_recorded_once_per_cycle(db_session: Session) -> None:
    account = connected_account(db_session)
    sync_service(db_session, FakeGmail()).sync(actor_for(account))
    db_session.commit()
    rows = db_session.execute(
        select(Activity).where(Activity.kind == "gmail.sync_eseguito")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].entity_type == "google_account"
    assert rows[0].entity_id == account.id


def test_an_mcp_actor_is_recorded_as_mcp(db_session: Session) -> None:
    from pigrocrm.core.actor import Actor

    account = connected_account(db_session)
    sync_service(db_session, FakeGmail()).sync(
        Actor(id=account.user_id, type="mcp", role="admin")
    )
    db_session.commit()
    row = db_session.execute(
        select(Activity).where(Activity.kind == "gmail.sync_eseguito")
    ).scalars().one()
    assert row.actor_type == "mcp"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_links.py -v`
Expected: FAIL — no `gmail_message_links` rows are written and no activity is recorded.

- [ ] **Step 3: Add the repository methods**

Append to `gmail/repository.py`:

```python
    def add_link(self, message_id: UUID, ref: EntityRef) -> bool:
        """False when the triple already existed. Concurrency-safe by constraint, not
        by pre-check: two overlapping cycles both pass a SELECT."""
        link = GmailMessageLink(
            gmail_message_id=message_id, entity_type=ref.entity_type, entity_id=ref.entity_id
        )
        self.session.add(link)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            return False
        return True

    def messages_for_entity(
        self, entity_type: str, entity_id: UUID, *, limit: int
    ) -> list[GmailMessage]:
        return list(
            self.session.execute(
                select(GmailMessage)
                .join(GmailMessageLink, GmailMessageLink.gmail_message_id == GmailMessage.id)
                .where(
                    GmailMessageLink.entity_type == entity_type,
                    GmailMessageLink.entity_id == entity_id,
                )
                .order_by(GmailMessage.gmail_thread_id, GmailMessage.internal_date)
                .limit(limit)
            ).scalars().all()
        )

    def last_inbound_from(
        self, account_id: UUID, addresses: Sequence[str], since: datetime
    ) -> GmailMessage | None:
        """The most recent inbound message from any of `addresses` after `since`.

        This is the signal Acme could not have had: from the moment the CRM reads the
        mail, the reminder candidate list can say "the client replied on 12 August".
        Chasing someone who has already replied is the mistake a CRM that does not read
        email cannot even notice it is making.
        """
        if not addresses:
            return None
        return self.session.execute(
            select(GmailMessage)
            .where(
                GmailMessage.google_account_id == account_id,
                GmailMessage.direction == "inbound",
                GmailMessage.from_address.in_([address.lower() for address in addresses]),
                GmailMessage.internal_date > since,
            )
            .order_by(GmailMessage.internal_date.desc())
            .limit(1)
        ).scalar_one_or_none()
```

Add `IntegrityError`, `EntityRef`, `GmailMessageLink`, `Sequence` and `datetime` to that module's imports.

- [ ] **Step 4: Link and record inside the sync**

In `gmail/sync.py`, add `from pigrocrm.core.activities.service import ActivityService` and `self.activities = ActivityService(session)` to `__init__`. Replace the thread loop's body so that a stored message is linked, and record the cycle before the commit:

```python
        for thread_id in thread_ids:
            report.threads_fetched += 1
            payload = self.transport.json(
                "GET", thread_get_url(thread_id), token=token, what="lettura di una conversazione"
            )
            raw_messages = [m for m in (payload.get("messages") or []) if isinstance(m, dict)]
            parsed_thread = [
                parse_message(
                    raw,
                    body_max_bytes=self.settings.gmail_body_max_bytes,
                    store_bodies=account.gmail_store_bodies,
                )
                for raw in raw_messages
            ]
            # The refs for the *thread*, gathered from every address in it that the CRM
            # already knows. A sibling message from an address nobody registered is
            # still linked through the thread -- and its address still does not join
            # the roster, which is what stops relevance from widening by itself.
            thread_refs: list[EntityRef] = []
            for parsed in parsed_thread:
                for address in [parsed.from_address, *parsed.to_addresses, *parsed.cc_addresses]:
                    for ref in self.roster.resolve(address):
                        if ref not in thread_refs:
                            thread_refs.append(ref)

            for parsed in parsed_thread:
                row = self._store(account, parsed)
                if row is None:
                    report.messages_skipped += 1
                    continue
                report.messages_stored += 1
                for ref in thread_refs:
                    if self.repo.add_link(row.id, ref):
                        report.links_created += 1
                if parsed.direction_is_inbound(account.email_address):
                    for ref in thread_refs:
                        self.activities.record(
                            ref.entity_type,
                            ref.entity_id,
                            "gmail.messaggio_ricevuto",
                            actor,
                            {
                                "subject": parsed.subject,
                                "from_address": parsed.from_address,
                                "gmail_message_id": parsed.gmail_message_id,
                                "gmail_thread_id": parsed.gmail_thread_id,
                            },
                        )
```

`_store` now returns `GmailMessage | None` instead of `bool` — change its signature and its two `return False` branches to `return None`, and its success branch to `return row`. Update B1-8's `_store` docstring accordingly.

Add to `ParsedMessage` in `parse.py`:

```python
    def direction_is_inbound(self, mailbox_address: str) -> bool:
        return self.from_address != mailbox_address.strip().lower()
```

and use it in `_store` for the `direction` column, so the rule lives in one place.

Before the `self.session.commit()` at the end of `sync`:

```python
        self.activities.record(
            "google_account",
            account.id,
            "gmail.sync_eseguito",
            actor,
            {
                "queries_issued": report.queries_issued,
                "threads_fetched": report.threads_fetched,
                "messages_stored": report.messages_stored,
                "messages_skipped": report.messages_skipped,
            },
        )
```

`ActivityService.record` flushes and joins the caller's transaction, and its docstring requires it to be the last thing touching the session before the commit. Nothing may call another committing service after it.

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_links.py packages/core/tests/test_gmail_sync.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/tests/test_gmail_links.py
git commit -m "feat(gmail): an email lands on the person, the customer and the deal"
```

---
### Task B1-10: Two overlapping syncs answer, rather than fail

A cron every 15 minutes and a human pressing the button is not a hypothetical.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/gmail/sync.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/repository.py`
- Create: `packages/core/tests/test_gmail_lock.py`

**Interfaces:**
- Consumes: `SyncReport.already_running` / `.running_since` from B1-8.
- Produces:
  ```python
  # repository.py
  SYNC_LOCK_NAMESPACE = 0x7091  # arbitrary, stable, and this project's alone
  def try_sync_lock(self, account_id: UUID) -> bool: ...
  def release_sync_lock(self, account_id: UUID) -> None: ...
  def sync_started_at(self, account_id: UUID) -> datetime | None: ...
  ```

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_lock.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.gmail.repository import GmailRepository
from tests.fakes.fake_gmail import FakeGmail
from tests.fakes.gmail_fixtures import actor_for, connected_account, sync_service


def test_a_second_overlapping_sync_answers_instead_of_failing(
    db_session: Session, db_engine: Engine
) -> None:
    """Spec 13, criterion 4. A user who presses the button twice must see a response,
    not an error -- and the second press must not double the requests."""
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.commit()

    # A second connection holds the advisory lock, exactly as a concurrent cron run
    # would. Advisory locks are per-session in Postgres, so a second SQLAlchemy Session
    # on its own connection is a faithful reproduction, not an approximation.
    with Session(db_engine) as holder:
        assert GmailRepository(holder).try_sync_lock(account.id) is True
        fake = FakeGmail()
        report = sync_service(db_session, fake).sync(actor_for(account))

        assert report.already_running is True
        assert report.running_since is not None
        assert report.messages_stored == 0
        # Not one request: the point of the lock is that the work is not done twice.
        assert fake.requests == []
        GmailRepository(holder).release_sync_lock(account.id)


def test_the_lock_is_released_even_when_the_cycle_raises(
    db_session: Session, db_engine: Engine
) -> None:
    """A lock leaked by an exception makes every later sync answer 'already running'
    forever, which looks exactly like a hung job and is impossible to diagnose."""
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.commit()

    fake = FakeGmail(revoked=True)  # the refresh fails, so the cycle raises
    try:
        sync_service(db_session, fake).sync(actor_for(account))
    except Exception:  # noqa: BLE001 -- the failure is the point; the lock is the test
        pass
    db_session.rollback()

    with Session(db_engine) as other:
        assert GmailRepository(other).try_sync_lock(account.id) is True
        GmailRepository(other).release_sync_lock(account.id)


def test_two_different_accounts_do_not_block_each_other(
    db_session: Session, db_engine: Engine
) -> None:
    first = connected_account(db_session)
    second = connected_account(db_session, email_address="due@example.it")
    db_session.commit()
    with Session(db_engine) as holder:
        assert GmailRepository(holder).try_sync_lock(first.id) is True
        with Session(db_engine) as other:
            assert GmailRepository(other).try_sync_lock(second.id) is True
            GmailRepository(other).release_sync_lock(second.id)
        GmailRepository(holder).release_sync_lock(first.id)


def test_the_reported_start_time_is_the_last_sync_that_actually_ran(
    db_session: Session, db_engine: Engine
) -> None:
    account = connected_account(db_session)
    account.last_sync_at = datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
    db_session.commit()
    with Session(db_engine) as holder:
        GmailRepository(holder).try_sync_lock(account.id)
        report = sync_service(db_session, FakeGmail()).sync(actor_for(account))
        assert report.running_since == datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
        GmailRepository(holder).release_sync_lock(account.id)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_lock.py -v`
Expected: FAIL — `GmailRepository has no attribute 'try_sync_lock'`.

- [ ] **Step 3: Add the lock methods**

Append to `gmail/repository.py`:

```python
# An arbitrary but stable first key for `pg_try_advisory_lock(int, int)`, so this
# project's locks cannot collide with another application sharing the database. The
# two-integer form is used rather than the single bigint one precisely because it
# namespaces: hashing a UUID into 64 bits alone risks colliding with anything else that
# also hashes something into 64 bits.
SYNC_LOCK_NAMESPACE = 0x7091


def _lock_key(account_id: UUID) -> int:
    """A signed 32-bit integer derived from the account id. `int.from_bytes` with
    `signed=True` over the first four bytes of the UUID: Postgres advisory-lock keys are
    `int4`, and passing an out-of-range value is an error, not a truncation."""
    return int.from_bytes(account_id.bytes[:4], "big", signed=True)
```

and inside the class:

```python
    def try_sync_lock(self, account_id: UUID) -> bool:
        """Non-blocking. A caller that does not get the lock must answer 'already in
        progress' -- it must not wait, and it must not fail."""
        return bool(
            self.session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :key)"),
                {"ns": SYNC_LOCK_NAMESPACE, "key": _lock_key(account_id)},
            ).scalar_one()
        )

    def release_sync_lock(self, account_id: UUID) -> None:
        self.session.execute(
            text("SELECT pg_advisory_unlock(:ns, :key)"),
            {"ns": SYNC_LOCK_NAMESPACE, "key": _lock_key(account_id)},
        )
```

Add `from sqlalchemy import text` to the imports.

- [ ] **Step 4: Wrap the cycle**

In `gmail/sync.py`, restructure `sync` so the whole body after `_account` sits inside the lock:

```python
    def sync(self, actor: Actor) -> SyncReport:
        require_gmail_configured(self.settings)
        actor.require_write("sincronizzare Gmail")
        account = self._account(actor)
        started_at = datetime.now(UTC)

        if not self.repo.try_sync_lock(account.id):
            # Not an error and not a wait: a user who pressed twice gets an answer that
            # says what is happening and when it started.
            return SyncReport(
                started_at=started_at,
                already_running=True,
                running_since=account.last_sync_at,
            )
        try:
            return self._run_cycle(account, actor, started_at)
        finally:
            # `finally`, so a raised cycle does not leak the lock. A leaked advisory
            # lock makes every later sync answer "already running" for the life of the
            # connection, which is indistinguishable from a hung job.
            self.repo.release_sync_lock(account.id)
```

Move the existing body of `sync` into `_run_cycle(self, account: GoogleAccount, actor: Actor, started_at: datetime) -> SyncReport`.

Note: the lock is held on `self.session`'s connection. `pg_advisory_unlock` must run on that same connection, which is why the release goes through `self.repo` and not a fresh session — and why `_run_cycle`'s `self.session.commit()` is safe: a commit does not release a session-scoped advisory lock.

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_lock.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/tests/test_gmail_lock.py
git commit -m "feat(gmail): overlapping syncs answer 'already running' instead of failing"
```

---

### Task B1-11: Backfill for a newly known address, and the full-history action

**Files:**
- Modify: `packages/core/src/pigrocrm/core/gmail/sync.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/models.py` (append `GmailKnownAddress`)
- Modify: `packages/core/src/pigrocrm/core/gmail/repository.py`
- Modify: `packages/core/migrations/versions/0006_gmail_messages.py` (same revision — B1-8 and B1-11 land together in `0006` if B1-11 is done before `0006` is applied anywhere; otherwise add `0007_gmail_known_addresses.py` and bump the revision assertions to `"0007"`)
- Create: `packages/core/tests/test_gmail_backfill.py`

**Interfaces:**
- Produces:
  ```python
  class GmailKnownAddress(Base, PrimaryKeyMixin, TimestampMixin):
      google_account_id: Mapped[UUID]
      address: Mapped[str]           # unique together with google_account_id
      first_seen_at: Mapped[datetime]

  # sync.py
  def backfill(self, entity_type: str, entity_id: UUID, *, full: bool, actor: Actor) -> SyncReport: ...
  ```
  `backfill` is consumed by B1-13 (`POST /api/gmail/backfill`) and B1-14 (`backfill_gmail`).

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_backfill.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.gmail.models import GmailMessage
from pigrocrm.core.people.models import Person
from tests.fakes.fake_gmail import FakeGmail, FakeMessage
from tests.fakes.gmail_fixtures import actor_for, connected_account, sync_service

OLD_MS = 1_500_000_000_000  # 2017, far outside any 90-day horizon
RECENT_MS = 1_723_000_000_000


def _message(mid: str, *, frm: str, when_ms: int) -> FakeMessage:
    return FakeMessage(
        id=mid,
        thread_id=f"t-{mid}",
        headers={"From": frm, "To": "io@example.it", "Subject": "S", "Message-ID": f"<{mid}@x.it>"},
        body_text="c",
        internal_date_ms=when_ms,
    )


def test_a_newly_added_address_is_backfilled_over_ninety_days(db_session: Session) -> None:
    """Spec 4.4: an address added to the CRM is treated as a backfill on the *next*
    cycle. PersonService is not made to learn what Gmail is -- packages/core services
    do not call each other for network side effects."""
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email=None)
    db_session.add(customer)
    db_session.flush()
    db_session.add(Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id))
    db_session.commit()

    fake = FakeGmail()
    fake.messages["recent"] = _message("recent", frm="ada@acme.it", when_ms=RECENT_MS)
    fake.messages["ancient"] = _message("ancient", frm="ada@acme.it", when_ms=OLD_MS)
    report = sync_service(db_session, fake).sync(actor_for(account))
    db_session.commit()

    # The first cycle sees ada@acme.it as new, so it looks back gmail_backfill_days
    # rather than only to the watermark -- but not to the beginning of time.
    assert report.messages_stored >= 1
    stored = set(db_session.execute(select(GmailMessage.gmail_message_id)).scalars().all())
    assert "recent" in stored
    assert "ancient" not in stored
    rows = db_session.execute(
        select(Activity).where(Activity.kind == "gmail.backfill_eseguito")
    ).scalars().all()
    assert rows, "a backfill has to be visible, not silent"


def test_the_second_cycle_does_not_backfill_the_same_address_again(db_session: Session) -> None:
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.commit()
    fake = FakeGmail()
    service = sync_service(db_session, fake)
    service.sync(actor_for(account))
    db_session.commit()
    first_queries = len([r for r in fake.requests if r.is_messages_list])
    fake.requests.clear()
    service.sync(actor_for(account))
    db_session.commit()
    # The second cycle uses the watermark only, so it issues no wider query than the
    # first did.
    assert len([r for r in fake.requests if r.is_messages_list]) <= first_queries


def test_full_history_takes_one_address_and_has_no_horizon(db_session: Session) -> None:
    """Spec 4.4 row 3: explicit, human-initiated, one address at a time. Not a default,
    because on a ten-year mailbox it is slow and nobody wants it by accident."""
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email=None)
    db_session.add(customer)
    db_session.flush()
    person = Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id)
    db_session.add(person)
    db_session.commit()

    fake = FakeGmail()
    fake.messages["ancient"] = _message("ancient", frm="ada@acme.it", when_ms=OLD_MS)
    report = sync_service(db_session, fake).backfill(
        "person", person.id, full=True, actor=actor_for(account)
    )
    db_session.commit()

    assert report.messages_stored == 1
    listings = [r for r in fake.requests if r.is_messages_list]
    assert len(listings) == 1
    assert "after:0" in (listings[0].q or "")
    # Still filtered by address. "No horizon" is about time, never about relevance.
    assert "from:ada@acme.it" in (listings[0].q or "")


def test_backfill_on_an_entity_with_no_address_refuses_clearly(db_session: Session) -> None:
    account = connected_account(db_session)
    customer = Customer(ragione_sociale="Acme", email=None)
    db_session.add(customer)
    db_session.commit()
    with pytest.raises(Conflict, match="nessun indirizzo"):
        sync_service(db_session, FakeGmail()).backfill(
            "customer", customer.id, full=False, actor=actor_for(account)
        )


def test_backfill_on_an_unknown_entity_is_a_not_found(db_session: Session) -> None:
    from uuid import uuid4

    account = connected_account(db_session)
    db_session.commit()
    with pytest.raises(NotFound):
        sync_service(db_session, FakeGmail()).backfill(
            "customer", uuid4(), full=False, actor=actor_for(account)
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_backfill.py -v`
Expected: FAIL — `GmailSyncService has no attribute 'backfill'`.

- [ ] **Step 3: Add the seen-address register**

Append to `gmail/models.py`:

```python
class GmailKnownAddress(Base, PrimaryKeyMixin, TimestampMixin):
    """Which roster addresses this account has already looked for.

    This is how "an address added to the CRM gets backfilled" happens *without*
    `PersonService` learning what Gmail is. The Gmail service compares the roster
    against this table at the start of each cycle and treats the difference as a
    backfill -- so a new address is synchronised on the next cycle, not in the instant
    it was saved, and the interface says so (spec 4.4) instead of leaving the user to
    discover it.
    """

    __tablename__ = "gmail_known_addresses"
    __table_args__ = (
        UniqueConstraint("google_account_id", "address", name="uq_gmail_known_addresses"),
    )

    google_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("google_accounts.id", ondelete="CASCADE"), nullable=False
    )
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Repository methods:

```python
    def seen_addresses(self, account_id: UUID) -> set[str]:
        return set(
            self.session.execute(
                select(GmailKnownAddress.address).where(
                    GmailKnownAddress.google_account_id == account_id
                )
            ).scalars().all()
        )

    def remember_addresses(self, account_id: UUID, addresses: Sequence[str]) -> int:
        added = 0
        for address in addresses:
            self.session.add(
                GmailKnownAddress(google_account_id=account_id, address=address)
            )
            try:
                self.session.flush()
                added += 1
            except IntegrityError:
                self.session.rollback()
        return added
```

- [ ] **Step 4: Split the cycle into two windows and add `backfill`**

In `_run_cycle`, replace the single `build_list_queries` call with two:

```python
        addresses = self.roster.known_addresses()
        seen = self.repo.seen_addresses(account.id)
        fresh = [address for address in addresses if address not in seen]
        established = [address for address in addresses if address in seen]

        queries: list[str] = []
        # Established addresses: only since the watermark.
        if established:
            queries.extend(
                build_list_queries(
                    established,
                    after_epoch=int(self._window_start(account).timestamp()),
                    batch_size=self.settings.gmail_sync_address_batch_size,
                )
            )
        # New addresses: the backfill horizon, once.
        if fresh:
            horizon = datetime.now(UTC) - timedelta(days=self.settings.gmail_backfill_days)
            queries.extend(
                build_list_queries(
                    fresh,
                    after_epoch=int(horizon.timestamp()),
                    batch_size=self.settings.gmail_sync_address_batch_size,
                )
            )
        report.queries_issued = len(queries)
```

After the thread loop, before the sync activity:

```python
        if fresh:
            self.repo.remember_addresses(account.id, fresh)
            self.activities.record(
                "google_account",
                account.id,
                "gmail.backfill_eseguito",
                actor,
                {"addresses": len(fresh), "days": self.settings.gmail_backfill_days},
            )
```

And the explicit action:

```python
    def backfill(
        self, entity_type: str, entity_id: UUID, *, full: bool, actor: Actor
    ) -> SyncReport:
        """One entity, one address at a time. `full=True` drops the time horizon and
        keeps the address filter: "no horizon" is about time, never about relevance."""
        require_gmail_configured(self.settings)
        actor.require_write("sincronizzare lo storico Gmail")
        account = self._account(actor)
        addresses = self._addresses_of(entity_type, entity_id)
        if not addresses:
            raise Conflict(
                "gmail_backfill",
                f"{entity_type} {entity_id} non ha nessun indirizzo email da sincronizzare",
            )

        started_at = datetime.now(UTC)
        if not self.repo.try_sync_lock(account.id):
            return SyncReport(
                started_at=started_at, already_running=True, running_since=account.last_sync_at
            )
        try:
            after_epoch = (
                0
                if full
                else int(
                    (
                        datetime.now(UTC) - timedelta(days=self.settings.gmail_backfill_days)
                    ).timestamp()
                )
            )
            report = SyncReport(started_at=started_at)
            token = self._access_token(account)
            queries = build_list_queries(
                addresses, after_epoch=after_epoch, batch_size=len(addresses)
            )
            report.queries_issued = len(queries)
            self._ingest(account, actor, queries, token, report)
            self.repo.remember_addresses(account.id, addresses)
            self.activities.record(
                "google_account",
                account.id,
                "gmail.backfill_eseguito",
                actor,
                {
                    "entity_type": entity_type,
                    "entity_id": str(entity_id),
                    "full": full,
                    "messages_stored": report.messages_stored,
                },
            )
            self.session.commit()
            return report
        finally:
            self.repo.release_sync_lock(account.id)

    def _addresses_of(self, entity_type: str, entity_id: UUID) -> list[str]:
        """Raises `NotFound` for an entity that does not exist, so a typo in an id is a
        404 and not a silent empty backfill."""
        if entity_type == "person":
            person = self.session.get(Person, entity_id)
            if person is None or person.deleted_at is not None:
                raise NotFound("person", entity_id)
            return [person.email.lower()] if person.email else []
        if entity_type == "customer":
            customer = self.session.get(Customer, entity_id)
            if customer is None or customer.deleted_at is not None:
                raise NotFound("customer", entity_id)
            addresses = [customer.email.lower()] if customer.email else []
            addresses.extend(
                email.lower()
                for email in self.session.execute(
                    select(Person.email).where(
                        Person.customer_id == entity_id,
                        Person.email.is_not(None),
                        Person.deleted_at.is_(None),
                    )
                ).scalars().all()
                if email
            )
            return list(dict.fromkeys(addresses))
        raise ValidationFailed(
            "gmail_backfill",
            "entity_type",
            "il backfill si esegue su una persona o su un cliente",
            expected="person | customer",
        )
```

Extract the thread-fetching and storing block of `_run_cycle` into `_ingest(self, account, actor, queries, token, report) -> None` so both `_run_cycle` and `backfill` use one code path — that is what keeps the "every listing carries an address filter" guarantee single-sourced.

- [ ] **Step 5: Migration and revision bump**

If `0006` has not been applied anywhere yet, add `gmail_known_addresses` to it. Otherwise create `0007_gmail_known_addresses.py` with `down_revision = "0006"` and bump `test_migrations.py:139,161` to `"0007"`. Register the model in `models_registry.py`.

- [ ] **Step 6: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_backfill.py packages/core/tests/test_gmail_sync.py packages/core/tests/test_gmail_links.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/migrations/versions \
        packages/core/src/pigrocrm/core/models_registry.py packages/core/tests/test_gmail_backfill.py \
        packages/core/tests/test_migrations.py
git commit -m "feat(gmail): a new address is backfilled on the next cycle, visibly"
```

---

### Task B1-12: A revoked or expired credential degrades visibly

**The second hard part.** This is the point where an OAuth integration usually lies. Spec §5.5 and success criteria 5–8.

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/account.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/sync.py` (catch `CredentialRevoked`, mark and record)
- Modify: `packages/core/src/pigrocrm/core/gmail/schemas.py` (append `GmailBannerReason`, `GmailHealth`)
- Create: `packages/core/tests/test_gmail_degradation.py`

**Interfaces:**
- Consumes: `CredentialRevoked`, `ScopeMissing` from B1-4; `SCOPE_READONLY`, `SCOPE_SEND` from B1-3.
- Produces:
  ```python
  CONSENT_WARNING_HOURS = 48

  GmailBannerReason = Literal["revoked", "expiring", "expired", "scope_missing"] | None

  class GmailHealth(BaseModel):
      account: GoogleAccountRead | None
      banner: GmailBannerReason
      banner_text: str | None
      missing_scopes: list[str]

  class GoogleAccountService:
      def __init__(self, session: Session, *, settings: Settings) -> None: ...
      def health(self, actor: Actor) -> GmailHealth: ...
      def usable(self, actor: Actor, *, scope: str, feature: str) -> GoogleAccount: ...
      def mark_revoked(self, account: GoogleAccount, actor: Actor, reason: str) -> None: ...
      def set_store_bodies(self, *, enabled: bool, actor: Actor) -> GoogleAccountRead: ...
  ```
  `usable` is the gate 5B-2's send path calls **before composing anything** — that is the whole reason it exists here rather than in `send.py`.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_degradation.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.gmail.account import CONSENT_WARNING_HOURS, GoogleAccountService
from pigrocrm.core.gmail.errors import CredentialRevoked, ScopeMissing
from pigrocrm.core.gmail.schemas import SCOPE_READONLY, SCOPE_SEND
from tests.fakes.fake_gmail import FakeGmail
from tests.fakes.gmail_fixtures import actor_for, connected_account, gmail_settings, sync_service


def _service(session: Session) -> GoogleAccountService:
    return GoogleAccountService(session, settings=gmail_settings())


def test_invalid_grant_marks_the_account_revoked_and_records_it(db_session: Session) -> None:
    """Spec 13, criterion 5 (a) and (b)."""
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.commit()

    fake = FakeGmail(revoked=True)
    with pytest.raises(CredentialRevoked):
        sync_service(db_session, fake).sync(actor_for(account))
    db_session.expire_all()

    db_session.refresh(account)
    assert account.status == "revoked"
    assert account.last_error is not None
    assert account.last_error_at is not None
    rows = db_session.execute(
        select(Activity).where(Activity.kind == "gmail.credenziale_revocata")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_type == "system"
    assert rows[0].entity_type == "google_account"


def test_the_refresh_is_never_retried_on_invalid_grant(db_session: Session) -> None:
    """Spec 13, criterion 5 (f). Retrying an invalid_grant is a bug: it cannot succeed,
    and retrying only delays telling the user the one thing they must act on."""
    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.commit()
    fake = FakeGmail(revoked=True)
    with pytest.raises(CredentialRevoked):
        sync_service(db_session, fake).sync(actor_for(account))
    assert fake.token_requests == 1


def test_the_stored_error_is_a_sentence_and_never_a_token_or_a_stack(
    db_session: Session,
) -> None:
    from tests.fakes.gmail_fixtures import REFRESH_TOKEN

    account = connected_account(db_session)
    db_session.add(Customer(ragione_sociale="Acme", email="info@acme.it"))
    db_session.commit()
    with pytest.raises(CredentialRevoked):
        sync_service(db_session, FakeGmail(revoked=True)).sync(actor_for(account))
    db_session.refresh(account)
    assert REFRESH_TOKEN not in (account.last_error or "")
    assert "Traceback" not in (account.last_error or "")
    assert "invalid_grant" not in (account.last_error or "")
    assert "ricollega" in (account.last_error or "").lower()


def test_a_send_gate_refuses_before_any_http_call_is_made(db_session: Session) -> None:
    """Spec 13, criterion 5 (d): a send against a non-active account answers Conflict
    **without making any HTTP call at all**. That is why this gate lives in
    GoogleAccountService and is called before the message is composed -- not inside the
    send path after the RFC822 has been built."""
    account = connected_account(db_session, status="revoked")
    db_session.commit()
    fake = FakeGmail()
    with pytest.raises(CredentialRevoked):
        _service(db_session).usable(actor_for(account), scope=SCOPE_SEND, feature="l'invio")
    assert fake.requests == []


def test_a_partial_grant_leaves_the_account_active_and_refuses_only_the_sync(
    db_session: Session,
) -> None:
    """Spec 13, criterion 7. status describes the credential; capability is derived
    from the granted scopes at the point of use. The two must not be conflated."""
    account = connected_account(db_session, scopes=("openid", "email", SCOPE_SEND))
    db_session.commit()
    service = _service(db_session)

    # Sending works.
    assert service.usable(actor_for(account), scope=SCOPE_SEND, feature="l'invio").id == account.id
    # Sync refuses, and names the missing scope.
    with pytest.raises(ScopeMissing) as caught:
        service.usable(actor_for(account), scope=SCOPE_READONLY, feature="la sincronizzazione")
    assert SCOPE_READONLY in caught.value.message
    db_session.refresh(account)
    assert account.status == "active"


def test_the_health_banner_has_three_causes_and_three_texts(db_session: Session) -> None:
    """Spec 11: a single banner saying "problem with Gmail" helps nobody."""
    account = connected_account(db_session)
    db_session.commit()
    service = _service(db_session)
    actor = actor_for(account)

    assert service.health(actor).banner is None

    account.status = "revoked"
    db_session.flush()
    revoked = service.health(actor)
    assert revoked.banner == "revoked"
    assert "revocato" in (revoked.banner_text or "")

    account.status = "active"
    account.consent_expires_at = datetime.now(UTC) + timedelta(hours=36)
    db_session.flush()
    expiring = service.health(actor)
    assert expiring.banner == "expiring"
    assert "rinnovato" in (expiring.banner_text or "")

    account.consent_expires_at = None
    account.scopes_granted = ["openid", "email", SCOPE_SEND]
    db_session.flush()
    partial = service.health(actor)
    assert partial.banner == "scope_missing"
    assert SCOPE_READONLY in (partial.banner_text or "")
    assert partial.missing_scopes == [SCOPE_READONLY]

    # Three distinct texts, not one text with three causes behind it.
    assert len({revoked.banner_text, expiring.banner_text, partial.banner_text}) == 3


def test_the_warning_arrives_before_anything_has_failed(db_session: Session) -> None:
    """Spec 13, criterion 6. A warning after the first error is not a warning: the
    error was the warning."""
    account = connected_account(db_session)
    account.consent_expires_at = datetime.now(UTC) + timedelta(hours=36)
    db_session.commit()
    health = _service(db_session).health(actor_for(account))
    assert health.banner == "expiring"
    assert account.status == "active"
    assert account.last_error is None
    assert CONSENT_WARNING_HOURS == 48


def test_an_expiry_further_out_than_the_warning_window_says_nothing_yet(
    db_session: Session,
) -> None:
    account = connected_account(db_session)
    account.consent_expires_at = datetime.now(UTC) + timedelta(days=6)
    db_session.commit()
    assert _service(db_session).health(actor_for(account)).banner is None


def test_health_on_an_installation_with_no_account_is_empty_not_an_error(
    db_session: Session,
) -> None:
    from pigrocrm.core.actor import Actor
    from pigrocrm.core.auth.models import User

    user = User(email="solo@example.it", nome="Solo", password_hash="x", role="admin", attivo=True)
    db_session.add(user)
    db_session.commit()
    health = _service(db_session).health(Actor(id=user.id, type="user", role="admin"))
    assert health.account is None
    assert health.banner is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_degradation.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.account'`.

- [ ] **Step 3: Write the account service**

`packages/core/src/pigrocrm/core/gmail/account.py`:

```python
"""The credential's state, and the two questions that must never be confused.

*Is the credential healthy?* is `status`. *Is this feature available?* is derived from
`scopes_granted` at the point of use. A valid credential that was granted less than was
asked for is healthy; it is the feature that is unavailable. Conflating them is the
contradiction the rest of the OAuth-integration world falls into, and it produces a
"reconnect your account" prompt for a problem reconnecting does not fix.

`/health` deliberately does **not** change when any of this goes wrong. A broken Gmail
credential is not a broken deploy, and teaching the operator that the probe goes red for
things they cannot fix teaches them to ignore the probe.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.errors import CredentialRevoked, ScopeMissing
from pigrocrm.core.gmail.models import GoogleAccount
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.schemas import (
    SCOPE_READONLY,
    SCOPE_SEND,
    GmailHealth,
    GoogleAccountRead,
)

# Warn two days out -- before anything fails. A warning issued after the first error is
# not a warning, because the error already was one.
CONSENT_WARNING_HOURS = 48

_REVOKED_TEXT = (
    "Il consenso Google per {email} è stato revocato: la sincronizzazione e l'invio "
    "sono sospesi finché non ricolleghi la casella."
)
_EXPIRING_TEXT = (
    "Il consenso Google per {email} va rinnovato entro il {when}. "
    "Dopo quella data la sincronizzazione si interrompe."
)
_EXPIRED_TEXT = (
    "Il consenso Google per {email} è scaduto e va rinnovato: la sincronizzazione è ferma."
)
_SCOPE_TEXT = (
    "Il sync è spento: manca l'autorizzazione {scopes}. Usa «ri-autorizza» per concederla."
)


class GoogleAccountService:
    def __init__(self, session: Session, *, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = GmailRepository(session)
        self.activities = ActivityService(session)

    def health(self, actor: Actor) -> GmailHealth:
        """One call answers the whole shell banner. No account at all is not a problem
        to report: an installation without Gmail has nothing to say about it."""
        account = self.repo.account_for_user(actor.id) if actor.id else None
        if account is None:
            return GmailHealth(account=None, banner=None, banner_text=None, missing_scopes=[])

        read = GoogleAccountRead.model_validate(account)
        now = datetime.now(UTC)

        # Order matters: revoked is the most actionable and the most final, so it wins.
        if account.status == "revoked":
            return GmailHealth(
                account=read,
                banner="revoked",
                banner_text=_REVOKED_TEXT.format(email=account.email_address),
                missing_scopes=[],
            )
        if account.status == "expired":
            return GmailHealth(
                account=read,
                banner="expired",
                banner_text=_EXPIRED_TEXT.format(email=account.email_address),
                missing_scopes=[],
            )
        if (
            account.consent_expires_at is not None
            and account.consent_expires_at - now <= timedelta(hours=CONSENT_WARNING_HOURS)
        ):
            return GmailHealth(
                account=read,
                banner="expiring",
                banner_text=_EXPIRING_TEXT.format(
                    email=account.email_address,
                    when=account.consent_expires_at.strftime("%d/%m/%Y alle %H:%M"),
                ),
                missing_scopes=[],
            )

        missing = [
            scope
            for scope in (SCOPE_READONLY, SCOPE_SEND)
            if scope not in account.scopes_granted
        ]
        if SCOPE_READONLY in missing:
            return GmailHealth(
                account=read,
                banner="scope_missing",
                banner_text=_SCOPE_TEXT.format(scopes=SCOPE_READONLY),
                missing_scopes=missing,
            )
        return GmailHealth(account=read, banner=None, banner_text=None, missing_scopes=missing)

    def usable(self, actor: Actor, *, scope: str, feature: str) -> GoogleAccount:
        """The gate. Called **before** anything is composed or any HTTP call is made, so
        that an operator who presses Send on a revoked account learns it at the press
        and not afterwards -- and so that nothing is half-done in between."""
        if actor.id is None:
            raise Conflict("google_account", "solo un utente può usare una casella Google")
        account = self.repo.account_for_user(actor.id)
        if account is None:
            raise Conflict("google_account", "nessuna casella Google collegata")
        if account.status != "active":
            raise CredentialRevoked(account.id, account.email_address)
        if scope not in account.scopes_granted:
            raise ScopeMissing(scope, feature)
        return account

    def mark_revoked(self, account: GoogleAccount, actor: Actor, reason: str) -> None:
        """Terminal. Called from the one place that can learn it -- a refresh answering
        `invalid_grant`. Committed on its own so the fact survives the failure of
        whatever operation discovered it."""
        account.status = "revoked"
        account.last_error = reason
        account.last_error_at = datetime.now(UTC)
        self.activities.record(
            "google_account",
            account.id,
            "gmail.credenziale_revocata",
            # `system`, not the caller: Google revoked this, nobody here did.
            Actor.system(),
            {"email_address": account.email_address},
        )
        self.session.commit()

    def set_store_bodies(self, *, enabled: bool, actor: Actor) -> GoogleAccountRead:
        actor.require_write("modificare le impostazioni Gmail")
        account = self.usable_or_present(actor)
        account.gmail_store_bodies = enabled
        self.activities.record(
            "google_account",
            account.id,
            "gmail.impostazioni_modificate",
            actor,
            {"gmail_store_bodies": enabled},
        )
        self.session.commit()
        return GoogleAccountRead.model_validate(account)

    def usable_or_present(self, actor: Actor) -> GoogleAccount:
        """The account regardless of status -- for settings changes, which must remain
        possible precisely when something is wrong."""
        if actor.id is None:
            raise Conflict("google_account", "solo un utente può usare una casella Google")
        account = self.repo.account_for_user(actor.id)
        if account is None:
            raise Conflict("google_account", "nessuna casella Google collegata")
        return account
```

`"gmail.impostazioni_modificate"` is one kind beyond the nine the spec's §5.6 lists. It is added because turning the body store off is a decision worth a trace — it changes what the CRM will remember — and because `activities.kind` is a `String(30)` truncated by `ActivityService.record`, so a new kind needs no migration and no schema change. Record it in the kind list in `schemas.py`'s module comment alongside the other ten.

Append to `gmail/schemas.py`:

```python
GmailBannerReason = Literal["revoked", "expiring", "expired", "scope_missing"] | None


class GmailHealth(BaseModel):
    """Everything the shell banner needs, in one response. Three distinct causes with
    three distinct texts: a single banner reading "problem with Gmail" helps nobody."""

    account: GoogleAccountRead | None
    banner: GmailBannerReason
    banner_text: str | None
    missing_scopes: list[str]
```

- [ ] **Step 4: Wire the revocation into the sync**

In `gmail/sync.py`, wrap `_access_token`'s call so the fact is recorded where it is learned:

```python
    def _access_token(self, account: GoogleAccount) -> str:
        refresh_token = unseal(
            account.refresh_token_ciphertext,
            account.refresh_token_nonce,
            decode_google_token_key(self.settings),
        )
        try:
            return self.tokens.access_token(
                account_id=account.id,
                email_address=account.email_address,
                refresh_token=refresh_token,
            )
        except CredentialRevoked as revoked:
            # Terminal, and it must not be swallowed: `mark_revoked` commits the state
            # and the timeline entry, then the exception continues so the caller stops
            # rather than proceeding against a dead credential.
            GoogleAccountService(self.session, settings=self.settings).mark_revoked(
                account,
                Actor.system(),
                f"Il consenso Google per {account.email_address} è stato revocato: "
                "ricollega la casella da Impostazioni → Gmail.",
            )
            raise revoked
```

The message stored in `last_error` is the sentence the user reads. It must not contain `invalid_grant`, the token, or a traceback — the test asserts all three.

Also add a `sync` guard so a partial grant refuses with the scope named rather than failing at the first listing:

```python
        GoogleAccountService(self.session, settings=self.settings).usable(
            actor, scope=SCOPE_READONLY, feature="la sincronizzazione"
        )
```

placed immediately after `_account(actor)` and before the lock is taken — refusing before taking a lock is what stops a refused call from making the next one answer "already running".

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_degradation.py -v`
Expected: PASS (9 tests).

- [ ] **Step 6: Assert `/health` did not change**

Add to `apps/api/tests/test_health.py` (or create it):

```python
def test_health_is_unchanged_by_a_broken_gmail_credential(client: TestClient) -> None:
    """Spec 13, criterion 5 (g). A broken third-party credential is not a broken
    deploy. Making the probe red for something the operator cannot fix from the deploy
    layer teaches them to ignore the probe."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "gmail" not in response.text.lower()
```

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/tests/test_gmail_degradation.py \
        apps/api/tests/test_health.py
git commit -m "feat(gmail): a revoked credential is recorded, surfaced, and never retried"
```

---
### Task B1-13: The REST surface

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/gmail.py`
- Modify: `apps/api/src/pigrocrm_api/main.py` (register the router)
- Create: `apps/api/tests/test_gmail_router.py`

**Interfaces:**
- Consumes: `GmailOAuthService`, `GmailSyncService`, `GoogleAccountService`, `GmailRepository.messages_for_entity`, `gmail_configured`; the existing `deps.py` providers for the session and the current actor.
- Produces:
  ```
  GET    /api/gmail/account          -> GmailHealth
  GET    /api/gmail/oauth/start      -> 307 to Google
  GET    /api/gmail/oauth/callback   -> 307 to /app/impostazioni/gmail?esito=…
  DELETE /api/gmail/account          -> 204   ?elimina_messaggi=bool
  POST   /api/gmail/sync             -> SyncReport
  POST   /api/gmail/backfill         -> SyncReport   body: GmailBackfillRequest
  GET    /api/gmail/messages         -> list[GmailMessageRead]   ?entity_type&entity_id&limit
  PATCH  /api/gmail/account          -> GoogleAccountRead        body: GmailSettingsUpdate
  ```
  plus, in `gmail/schemas.py`:
  ```python
  class GmailBackfillRequest(BaseModel):
      entity_type: Literal["person", "customer"]
      entity_id: UUID
      full: bool = False

  class GmailSettingsUpdate(BaseModel):
      gmail_store_bodies: bool
  ```
  Consumed by B1-15, B1-16, B1-17.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_gmail_router.py`:

```python
from fastapi.testclient import TestClient


def test_an_unconfigured_installation_answers_conflict_not_five_hundred(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """Absent, not broken. Every endpoint says the same sentence, and none of them
    raises."""
    for method, path in [
        ("GET", "/api/gmail/oauth/start"),
        ("POST", "/api/gmail/sync"),
    ]:
        response = client.request(method, path, headers=admin_headers)
        assert response.status_code == 409, path
        assert "non è configurato" in response.json()["detail"]


def test_the_account_endpoint_is_readable_even_with_gmail_off(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """The settings page has to be able to render "not configured" without a 409 in the
    console: a query in isError renders QueryErrorBanner, and this is not an error."""
    response = client.get("/api/gmail/account", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {
        "account": None,
        "banner": None,
        "banner_text": None,
        "missing_scopes": [],
    }


def test_every_gmail_endpoint_requires_authentication(client: TestClient) -> None:
    for method, path in [
        ("GET", "/api/gmail/account"),
        ("POST", "/api/gmail/sync"),
        ("POST", "/api/gmail/backfill"),
        ("GET", "/api/gmail/messages"),
        ("DELETE", "/api/gmail/account"),
    ]:
        assert client.request(method, path).status_code == 401, path


def test_a_readonly_actor_cannot_sync(
    client: TestClient, readonly_headers: dict[str, str]
) -> None:
    assert client.post("/api/gmail/sync", headers=readonly_headers).status_code == 403


def test_the_callback_never_renders_the_upstream_error_to_the_browser(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """Google appends ?error=access_denied when the user declines. The redirect carries
    a code the SPA turns into Italian; it does not echo Google's text, which is English
    and occasionally contains the client id."""
    response = client.get(
        "/api/gmail/oauth/callback?error=access_denied",
        headers=admin_headers,
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("/app/impostazioni/gmail?esito=")
    assert "access_denied" not in location


def test_the_messages_endpoint_bounds_its_limit(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get(
        "/api/gmail/messages",
        params={"entity_type": "customer", "entity_id": "00000000-0000-7000-8000-000000000000", "limit": 5_000},
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_no_endpoint_accepts_a_gmail_search_string(client: TestClient) -> None:
    """Spec 12: no surface in this slice accepts a Gmail search expression. Checked
    against the generated OpenAPI document, so a future parameter cannot slip in."""
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/gmail"):
            continue
        for operation in operations.values():
            names = {p["name"] for p in operation.get("parameters", [])}
            assert "q" not in names, f"{path} exposes a Gmail query parameter"
            assert "query" not in names, f"{path} exposes a Gmail query parameter"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest apps/api/tests/test_gmail_router.py -v`
Expected: FAIL — 404 on every path.

- [ ] **Step 3: Write the router**

`apps/api/src/pigrocrm_api/routers/gmail.py`:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, gmail_configured
from pigrocrm.core.gmail.account import GoogleAccountService
from pigrocrm.core.gmail.oauth import GmailOAuthService
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.schemas import (
    GmailBackfillRequest,
    GmailHealth,
    GmailMessageRead,
    GmailSettingsUpdate,
    GoogleAccountRead,
    SyncReport,
)
from pigrocrm.core.gmail.sync import GmailSyncService
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport
from pigrocrm_api.deps import current_actor, get_session, get_settings_dep

router = APIRouter(prefix="/api/gmail", tags=["gmail"])

# Where the SPA now lives (slice 5A moved it under /app/). The callback redirects here
# with an outcome code the UI renders in Italian, rather than echoing Google's own
# English text -- which is occasionally the client id in a sentence.
_SETTINGS_PAGE = "/app/impostazioni/gmail"


def _oauth(session: Session, settings: Settings) -> GmailOAuthService:
    transport = GmailTransport()
    return GmailOAuthService(
        session,
        settings=settings,
        tokens=GoogleTokenClient(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            transport=transport,
        ),
    )


def _sync(session: Session, settings: Settings) -> GmailSyncService:
    transport = GmailTransport()
    return GmailSyncService(
        session,
        settings=settings,
        transport=transport,
        tokens=GoogleTokenClient(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            transport=transport,
        ),
    )


@router.get("/account", response_model=GmailHealth)
def read_account(
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> GmailHealth:
    """Answers 200 even when Gmail is not configured. The settings page must be able to
    render "not available on this installation" without the SPA treating it as a failed
    request -- a failed request renders QueryErrorBanner, and this is not a failure."""
    if not gmail_configured(settings):
        return GmailHealth(account=None, banner=None, banner_text=None, missing_scopes=[])
    return GoogleAccountService(session, settings=settings).health(actor)


@router.get("/oauth/start")
def start_oauth(
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> RedirectResponse:
    return RedirectResponse(_oauth(session, settings).start(actor), status_code=307)


@router.get("/oauth/callback")
def finish_oauth(
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error is not None or code is None or state is None:
        # One outcome code for every refusal. Google's own `error` is not forwarded:
        # it is English, and it sometimes embeds the client id.
        return RedirectResponse(f"{_SETTINGS_PAGE}?esito=negato", status_code=307)
    _oauth(session, settings).complete(code=code, state=state, actor=actor)
    return RedirectResponse(f"{_SETTINGS_PAGE}?esito=collegato", status_code=307)


@router.delete("/account", status_code=204)
def disconnect(
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    elimina_messaggi: Annotated[bool, Query()] = False,
) -> None:
    _oauth(session, settings).disconnect(delete_messages=elimina_messaggi, actor=actor)


@router.patch("/account", response_model=GoogleAccountRead)
def update_settings(
    payload: GmailSettingsUpdate,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> GoogleAccountRead:
    return GoogleAccountService(session, settings=settings).set_store_bodies(
        enabled=payload.gmail_store_bodies, actor=actor
    )


@router.post("/sync", response_model=SyncReport)
def run_sync(
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SyncReport:
    return _sync(session, settings).sync(actor)


@router.post("/backfill", response_model=SyncReport)
def run_backfill(
    payload: GmailBackfillRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SyncReport:
    return _sync(session, settings).backfill(
        payload.entity_type, payload.entity_id, full=payload.full, actor=actor
    )


@router.get("/messages", response_model=list[GmailMessageRead])
def read_messages(
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    entity_type: Annotated[str, Query(pattern="^(customer|person|deal)$")],
    entity_id: Annotated[UUID, Query()],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[GmailMessageRead]:
    """Reads only what is already in the CRM. There is no parameter here that reaches
    Gmail, by design (spec 8.2)."""
    del actor  # authorisation is the dependency's job; reading is not role-gated
    rows = GmailRepository(session).messages_for_entity(entity_type, entity_id, limit=limit)
    return [GmailMessageRead.model_validate(row) for row in rows]
```

Register it in `main.py` beside the other routers. Match whatever helper `deps.py` exposes for `Settings` — if it has none, add `get_settings_dep` there returning `get_settings()`, and use that one name everywhere in this slice.

Append the two request schemas to `gmail/schemas.py`:

```python
class GmailBackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: Literal["person", "customer"]
    entity_id: UUID
    full: bool = False


class GmailSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gmail_store_bodies: bool
```

Neither carries a free-text field, so neither needs `SafeStr` — and that absence is the point: nothing a caller can type reaches Gmail.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest apps/api/tests/test_gmail_router.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Regenerate the frontend client**

```bash
uv run uvicorn pigrocrm_api.main:app --port 8000 &
cd apps/web && pnpm generate:api && pnpm tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/pigrocrm_api apps/api/tests/test_gmail_router.py \
        packages/core/src/pigrocrm/core/gmail/schemas.py apps/web/src/lib/api-types.ts
git commit -m "feat(gmail): the REST surface, with no endpoint that takes a search string"
```

---

### Task B1-14: The MCP surface — deliberately asymmetric

An agent that reads a mailbox and sends mail as you is a different proposition from one that creates a customer. The asymmetry is the design, not an omission.

**Files:**
- Create: `apps/mcp/src/pigrocrm_mcp/tools/gmail.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/server.py` (register conditionally)
- Create: `apps/mcp/tests/test_gmail_tools.py`

**Interfaces:**
- Consumes: `gmail_configured`; the same four services as B1-13; the PAT `gmail:read` scope from **the R10/R5 prerequisite**.
- Produces the tools `list_gmail_messages`, `get_gmail_message`, `sync_gmail`, `backfill_gmail`, `describe_gmail_account` — and no others.

- [ ] **Step 1: Write the failing test**

`apps/mcp/tests/test_gmail_tools.py`:

```python
import json

import pytest


async def test_the_five_read_and_sync_tools_are_registered(mcp_server) -> None:
    names = {tool.name for tool in await mcp_server.list_tools()}
    assert {
        "list_gmail_messages",
        "get_gmail_message",
        "sync_gmail",
        "backfill_gmail",
        "describe_gmail_account",
    } <= names


async def test_no_tool_can_send_anything(mcp_server) -> None:
    """Spec 8.2 and 13, criterion 16. An email sent from your mailbox cannot be
    recalled, the client reads it as your words, and an agent holding *read* of the mail
    and *send* in the same belt has the injection source and the exfiltration channel in
    one channel. The human presses Send; the agent writes the draft."""
    names = {tool.name for tool in await mcp_server.list_tools()}
    for forbidden in [
        "send_email",
        "send_payment_reminder",
        "connect_google_account",
        "disconnect_google_account",
    ]:
        assert forbidden not in names
    assert not any("send" in name for name in names)


async def test_no_tool_schema_accepts_a_gmail_search_string(mcp_server) -> None:
    """Verified by schema and not only by name: a parameter called `filtro` that takes
    a Gmail expression would be the same hole with better manners. Every string
    parameter on a Gmail tool is checked against an allowlist of what it may be."""
    allowed_strings = {"entity_type", "message_id"}
    for tool in await mcp_server.list_tools():
        if "gmail" not in tool.name:
            continue
        properties = (tool.inputSchema or {}).get("properties", {})
        for name, schema in properties.items():
            if schema.get("type") == "string" and "format" not in schema:
                assert name in allowed_strings, f"{tool.name}.{name} takes free text"


async def test_the_tools_are_absent_when_gmail_is_not_configured(mcp_server_without_gmail) -> None:
    """Absent, not broken (spec 5.3). And the whole suite passes in that
    configuration -- spec 13, criterion 8."""
    names = {tool.name for tool in await mcp_server_without_gmail.list_tools()}
    assert not any("gmail" in name for name in names)


async def test_a_sync_through_mcp_is_recorded_as_mcp(mcp_server, db_session) -> None:
    from sqlalchemy import select

    from pigrocrm.core.activities.models import Activity

    await mcp_server.call_tool("sync_gmail", {})
    rows = db_session.execute(
        select(Activity).where(Activity.kind == "gmail.sync_eseguito")
    ).scalars().all()
    assert rows and rows[-1].actor_type == "mcp"


async def test_a_token_without_the_gmail_read_scope_cannot_call_the_read_tools(
    mcp_server_scoped_without_gmail_read,
) -> None:
    """Spec 13, criterion 17. This consumes the R10 minimum cut; it does not implement
    it. If `gmail:read` does not exist as a PAT scope, stop and close that prerequisite
    first -- do not weaken this test."""
    result = await mcp_server_scoped_without_gmail_read.call_tool(
        "list_gmail_messages", {"entity_type": "customer", "entity_id": str(__import__("uuid").uuid4())}
    )
    assert "gmail:read" in json.dumps(result)


async def test_the_whole_gmail_suite_makes_no_send_call(mcp_server, fake_gmail) -> None:
    """Spec 13, criterion 15, from the MCP side."""
    await mcp_server.call_tool("sync_gmail", {})
    assert [request for request in fake_gmail.requests if request.is_messages_send] == []
```

The four fixtures — `mcp_server`, `mcp_server_without_gmail`, `mcp_server_scoped_without_gmail_read`, `fake_gmail` — go in `apps/mcp/tests/conftest.py`, built with the same `connected_account` / `gmail_settings` helpers from `packages/core/tests/fakes/gmail_fixtures.py` and the existing `build_server(session_provider=…)` entry point. Each one differs from `mcp_server` by exactly one thing: no Gmail settings, a PAT scope set without `gmail:read`, and the shared `FakeGmail` instance respectively.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest apps/mcp/tests/test_gmail_tools.py -v`
Expected: FAIL — the five tool names are absent.

- [ ] **Step 3: Write the tools**

`apps/mcp/src/pigrocrm_mcp/tools/gmail.py`:

```python
"""What an agent may do with the mail, and what it may not.

Granted: reading what is **already** in the CRM (an agent can read the timeline with
`get_timeline` already, so this is not a new surface); running the sync and the
backfill, because both operate only under the relevance rule of spec 4 and both land in
the CRM where the result is inspectable; and writing a **local draft**, which is where
an agent is worth the most -- "prepare the covering email for the offer".

Not granted, and not an oversight: **sending**. `POST /api/email-drafts/{id}/send`
exists as a REST endpoint and deliberately not as a tool. That gap is the design.

Also not granted: any tool taking a Gmail search string. Without that rule every
guarantee in spec 4 is one prompt away from being nothing.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, WithJsonSchema

from pigrocrm.core.gmail.account import GoogleAccountService
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.sync import GmailSyncService

# R2: the MCP SDK validates some arguments before `_guard` runs, so a strict scalar has
# to carry its own JSON schema or a wrong value produces a raw pydantic dump with a link
# to errors.pydantic.dev. Same technique as tools/__init__.py already uses.
GmailEntityType = Annotated[
    Literal["customer", "person", "deal"],
    WithJsonSchema({"type": "string", "enum": ["customer", "person", "deal"]}),
]
BackfillEntityType = Annotated[
    Literal["person", "customer"],
    WithJsonSchema({"type": "string", "enum": ["person", "customer"]}),
]
BoundedLimit = Annotated[int, Field(ge=1, le=200)]


def register(server, context) -> None:  # signature per apps/mcp/src/pigrocrm_mcp/server.py
    @server.tool()
    def list_gmail_messages(
        entity_type: GmailEntityType, entity_id: UUID, limit: BoundedLimit = 50
    ) -> list[dict[str, object]]:
        """Le email già sincronizzate per un cliente, una persona o un deal."""
        context.require_scope("gmail:read")
        rows = GmailRepository(context.session).messages_for_entity(
            entity_type, entity_id, limit=limit
        )
        return [
            {
                "id": str(row.id),
                "thread": row.gmail_thread_id,
                "direzione": row.direction,
                "da": row.from_address,
                "a": row.to_addresses,
                "oggetto": row.subject,
                "data": row.internal_date.isoformat(),
                "estratto": row.snippet,
            }
            for row in rows
        ]

    @server.tool()
    def get_gmail_message(message_id: UUID) -> dict[str, object]:
        """Il testo completo di un'email già sincronizzata."""
        context.require_scope("gmail:read")
        row = GmailRepository(context.session).message(message_id)
        return {
            "oggetto": row.subject,
            "da": row.from_address,
            "a": row.to_addresses,
            "cc": row.cc_addresses,
            "data": row.internal_date.isoformat(),
            "corpo": row.body_text,
            "troncato": row.body_truncated,
            "html_scartato": row.body_html_scartato,
            "allegati": row.attachments,
        }

    @server.tool()
    def sync_gmail() -> dict[str, object]:
        """Sincronizza le conversazioni con gli indirizzi già presenti nel CRM."""
        context.require_scope("gmail:read")
        report = context.gmail_sync().sync(context.actor)
        return report.model_dump(mode="json")

    @server.tool()
    def backfill_gmail(
        entity_type: BackfillEntityType, entity_id: UUID, full: bool = False
    ) -> dict[str, object]:
        """Recupera lo storico per gli indirizzi di una persona o di un cliente."""
        context.require_scope("gmail:read")
        report = context.gmail_sync().backfill(
            entity_type, entity_id, full=full, actor=context.actor
        )
        return report.model_dump(mode="json")

    @server.tool()
    def describe_gmail_account() -> dict[str, object]:
        """Stato della connessione Gmail, così l'agente diagnostica invece di ritentare."""
        context.require_scope("gmail:read")
        health = GoogleAccountService(
            context.session, settings=context.settings
        ).health(context.actor)
        return health.model_dump(mode="json")
```

`GmailSyncService` is constructed by `context.gmail_sync()` rather than inline, so the MCP adapter builds it exactly once and the tests can inject `FakeGmail` at that seam. Add that factory to `apps/mcp/src/pigrocrm_mcp/context.py`, and add `require_scope(name: str) -> None` there too — it reads the PAT's scope set from the authenticated principal and raises the project's `PermissionDenied` naming the missing scope.

`GmailRepository.message(message_id: UUID) -> GmailMessage` raising `NotFound` is one more repository method to add in this task.

In `server.py`, register conditionally:

```python
    if gmail_configured(settings):
        from pigrocrm_mcp.tools import gmail as gmail_tools

        gmail_tools.register(server, context)
```

Not registered means not listed and not callable — absent, not broken.

**Note on residuo R1:** the MCP server still shares one SQLAlchemy `Session` across concurrent calls. `sync_gmail` is a long call that holds it far longer than any slice-1 tool did, which *widens* the window R1 describes. This task adds no session handling of its own and changes nothing about `context.session`; it must not be read as having fixed R1, and this plan does not claim to.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest apps/mcp/tests/test_gmail_tools.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the whole suite with Gmail unconfigured**

```bash
env -u PIGROCRM_GOOGLE_CLIENT_ID -u PIGROCRM_GOOGLE_TOKEN_KEY uv run pytest -q
```

Expected: PASS. Spec 13, criterion 8: with no client id the entire suite passes and no Gmail surface exists.

- [ ] **Step 6: Commit**

```bash
git add apps/mcp/src/pigrocrm_mcp apps/mcp/tests
git commit -m "feat(gmail): five MCP tools, none of which can send or search"
```

---

### Task B1-15: Impostazioni → Gmail

**Files:**
- Create: `apps/web/src/features/gmail/queries.ts`
- Create: `apps/web/src/features/gmail/GmailPanel.tsx`
- Create: `apps/web/src/routes/app/impostazioni/gmail.tsx`
- Create: `apps/web/src/features/gmail/GmailPanel.test.tsx`

**Interfaces:**
- Consumes: the generated `api-types.ts` from B1-13; `QueryErrorBanner`, `Button`, `Switch`, `Badge` from `components/`.
- Produces:
  ```ts
  export const gmailKeys = { health: ['gmail', 'health'] as const,
                             messages: (t: string, id: string) => ['gmail', 'messages', t, id] as const }
  export function useGmailHealth(): UseQueryResult<GmailHealth>
  export function useSyncGmail(): UseMutationResult<SyncReport, ApiError, void>
  export function useDisconnectGmail(): UseMutationResult<void, ApiError, { eliminaMessaggi: boolean }>
  export function useSetStoreBodies(): UseMutationResult<GoogleAccountRead, ApiError, boolean>
  export function useGmailMessages(args: { entityType: 'customer' | 'person' | 'deal'; entityId: string }):
      UseQueryResult<GmailMessageRead[]>
  ```
  Consumed by B1-16 (`useGmailHealth`) and B1-17 (`useGmailMessages`).

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/gmail/GmailPanel.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GmailPanel } from './GmailPanel'
import type { GmailHealth } from './queries'

function renderWith(health: GmailHealth | undefined, state: 'ok' | 'error' | 'loading') {
  vi.doMock('./queries', () => ({
    useGmailHealth: () => ({
      data: health,
      isError: state === 'error',
      isLoading: state === 'loading',
    }),
    useSyncGmail: () => ({ mutate: vi.fn(), isPending: false }),
    useDisconnectGmail: () => ({ mutate: vi.fn(), isPending: false }),
    useSetStoreBodies: () => ({ mutate: vi.fn(), isPending: false }),
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <GmailPanel />
    </QueryClientProvider>,
  )
}

const connected: GmailHealth = {
  account: {
    id: '00000000-0000-7000-8000-000000000001',
    email_address: 'ada@acme.it',
    scopes_granted: [
      'openid',
      'email',
      'https://www.googleapis.com/auth/gmail.readonly',
      'https://www.googleapis.com/auth/gmail.send',
    ],
    status: 'active',
    consent_expires_at: null,
    last_error: null,
    last_error_at: null,
    last_sync_at: '2026-08-20T09:30:00Z',
    sync_watermark: '2026-08-19T09:30:00Z',
    gmail_store_bodies: true,
    connected_at: '2026-08-01T09:00:00Z',
    disconnected_at: null,
  },
  banner: null,
  banner_text: null,
  missing_scopes: [],
}

describe('GmailPanel', () => {
  it('shows the connected mailbox, the granted scopes and the last sync', () => {
    renderWith(connected, 'ok')
    expect(screen.getByText('ada@acme.it')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sincronizza adesso' })).toBeEnabled()
    expect(screen.getByText(/gmail\.readonly/)).toBeInTheDocument()
  })

  it('says Gmail is not available rather than showing a broken panel', () => {
    // Absent, not broken. `account: null` with no banner is the not-configured shape.
    renderWith({ account: null, banner: null, banner_text: null, missing_scopes: [] }, 'ok')
    expect(screen.getByText(/non è configurato su questa installazione/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sincronizza adesso' })).not.toBeInTheDocument()
  })

  it('renders the error banner instead of an empty panel when the request failed', () => {
    // A failed request must never look like an empty result.
    renderWith(undefined, 'error')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/non è configurato/)).not.toBeInTheDocument()
  })

  it('disables the sync button and explains why when readonly was not granted', () => {
    renderWith(
      {
        ...connected,
        account: { ...connected.account!, scopes_granted: ['openid', 'email', 'https://www.googleapis.com/auth/gmail.send'] },
        banner: 'scope_missing',
        banner_text: 'Il sync è spento: manca l’autorizzazione https://www.googleapis.com/auth/gmail.readonly.',
        missing_scopes: ['https://www.googleapis.com/auth/gmail.readonly'],
      },
      'ok',
    )
    expect(screen.getByRole('button', { name: 'Sincronizza adesso' })).toBeDisabled()
    expect(screen.getByText(/manca l/)).toBeInTheDocument()
  })

  it('makes the disconnect dialog ask about the stored messages, defaulting to keeping them', () => {
    renderWith(connected, 'ok')
    const checkbox = screen.getByRole('checkbox', { name: /elimina anche le email/i })
    // Never the default: deleting a customer's correspondence because a token expired
    // would be a disaster.
    expect(checkbox).not.toBeChecked()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run src/features/gmail`
Expected: FAIL — `Failed to resolve import './GmailPanel'`.

- [ ] **Step 3: Write the queries**

`apps/web/src/features/gmail/queries.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { components } from '@/lib/api-types'

export type GmailHealth = components['schemas']['GmailHealth']
export type GoogleAccountRead = components['schemas']['GoogleAccountRead']
export type GmailMessageRead = components['schemas']['GmailMessageRead']
export type SyncReport = components['schemas']['SyncReport']

export const gmailKeys = {
  health: ['gmail', 'health'] as const,
  messages: (entityType: string, entityId: string) =>
    ['gmail', 'messages', entityType, entityId] as const,
}

export function useGmailHealth() {
  return useQuery({
    queryKey: gmailKeys.health,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/gmail/account')
      if (error) throw error
      return data
    },
  })
}

export function useSyncGmail() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/gmail/sync')
      if (error) throw error
      return data
    },
    onSuccess: () => {
      // The health row carries last_sync_at, and any entity's Email tab may have
      // gained messages.
      void client.invalidateQueries({ queryKey: gmailKeys.health })
      void client.invalidateQueries({ queryKey: ['gmail', 'messages'] })
    },
  })
}

export function useDisconnectGmail() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ eliminaMessaggi }: { eliminaMessaggi: boolean }) => {
      const { error } = await api.DELETE('/api/gmail/account', {
        params: { query: { elimina_messaggi: eliminaMessaggi } },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: gmailKeys.health })
      void client.invalidateQueries({ queryKey: ['gmail', 'messages'] })
    },
  })
}

export function useSetStoreBodies() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (enabled: boolean) => {
      const { data, error } = await api.PATCH('/api/gmail/account', {
        body: { gmail_store_bodies: enabled },
      })
      if (error) throw error
      return data
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: gmailKeys.health }),
  })
}

export function useGmailMessages(args: {
  entityType: 'customer' | 'person' | 'deal'
  entityId: string
}) {
  // No `enabled: !!id` escape hatch: the argument is a required route param at every
  // call site, and there is no empty-string spelling to get wrong (residuo B1).
  return useQuery({
    queryKey: gmailKeys.messages(args.entityType, args.entityId),
    queryFn: async () => {
      const { data, error } = await api.GET('/api/gmail/messages', {
        params: { query: { entity_type: args.entityType, entity_id: args.entityId } },
      })
      if (error) throw error
      return data
    },
  })
}
```

- [ ] **Step 4: Write the panel and the route**

`apps/web/src/features/gmail/GmailPanel.tsx` — under 250 lines; it renders four regions and delegates the rest:

```tsx
import { useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  useDisconnectGmail,
  useGmailHealth,
  useSetStoreBodies,
  useSyncGmail,
} from './queries'

const READONLY_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'

function formatDate(value: string | null): string {
  if (!value) return 'mai'
  return new Date(value).toLocaleString('it-IT', { dateStyle: 'medium', timeStyle: 'short' })
}

export function GmailPanel() {
  const health = useGmailHealth()
  const sync = useSyncGmail()
  const disconnect = useDisconnectGmail()
  const storeBodies = useSetStoreBodies()
  const [eliminaMessaggi, setEliminaMessaggi] = useState(false)

  // Order matters: a failed request must never look like an empty result, so isError
  // is answered before any "nothing here" rendering.
  if (health.isError) return <QueryErrorBanner onRetry={() => void health.refetch()} />
  if (health.isLoading || !health.data) return <p>Caricamento…</p>

  const { account, banner_text, missing_scopes } = health.data
  if (!account) {
    return (
      <section>
        <h2 className="text-lg font-medium">Gmail</h2>
        <p className="text-muted-foreground">
          Gmail non è configurato su questa installazione. Per attivarlo servono un client
          OAuth di Google e le variabili <code>PIGROCRM_GOOGLE_CLIENT_ID</code>,
          <code>PIGROCRM_GOOGLE_CLIENT_SECRET</code>, <code>PIGROCRM_GOOGLE_TOKEN_KEY</code> e
          <code>PIGROCRM_PUBLIC_URL</code>.
        </p>
      </section>
    )
  }

  const canSync = account.status === 'active' && !missing_scopes.includes(READONLY_SCOPE)

  return (
    <section className="space-y-6">
      <header>
        <h2 className="text-lg font-medium">Gmail</h2>
        <p className="font-medium">{account.email_address}</p>
        <p className="text-sm text-muted-foreground">
          Stato: {account.status} · Ultimo sync: {formatDate(account.last_sync_at)}
          {account.consent_expires_at
            ? ` · Consenso da rinnovare entro il ${formatDate(account.consent_expires_at)}`
            : ''}
        </p>
      </header>

      {banner_text ? <p role="status">{banner_text}</p> : null}
      {account.last_error ? <p role="status">{account.last_error}</p> : null}

      <div>
        <h3 className="text-sm font-medium">Autorizzazioni concesse</h3>
        <ul className="text-sm text-muted-foreground">
          {account.scopes_granted.map((scope) => (
            <li key={scope}>{scope}</li>
          ))}
        </ul>
      </div>

      <div className="flex items-center gap-3">
        <Switch
          id="gmail-store-bodies"
          checked={account.gmail_store_bodies}
          disabled={storeBodies.isPending}
          onCheckedChange={(checked) => storeBodies.mutate(checked)}
        />
        <label htmlFor="gmail-store-bodies" className="text-sm">
          Salva il testo delle email nel database. Spegnendolo restano solo intestazioni e
          anteprima, e la corrispondenza già archiviata non si arricchisce più.
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => sync.mutate()} disabled={!canSync || sync.isPending}>
          Sincronizza adesso
        </Button>
        <a href="/api/gmail/oauth/start">
          <Button variant="outline">Ri-autorizza</Button>
        </a>
      </div>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={eliminaMessaggi}
            onChange={(event) => setEliminaMessaggi(event.target.checked)}
          />
          Elimina anche le email già archiviate
        </label>
        <Button
          variant="destructive"
          disabled={disconnect.isPending}
          onClick={() => disconnect.mutate({ eliminaMessaggi })}
        >
          Scollega la casella
        </Button>
      </div>
    </section>
  )
}
```

`apps/web/src/routes/app/impostazioni/gmail.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { GmailPanel } from '@/features/gmail/GmailPanel'

/** The two outcome codes B1-13's callback redirects with, rendered in Italian here
 *  rather than echoed from Google -- whose own `error` is English and occasionally
 *  embeds the client id. */
const ESITO: Record<string, string> = {
  collegato: 'Casella collegata.',
  negato: "Autorizzazione negata: la casella non è stata collegata.",
}

function GmailSettingsRoute() {
  const { esito } = Route.useSearch()
  return (
    <div className="space-y-4">
      {esito && ESITO[esito] ? <p role="status">{ESITO[esito]}</p> : null}
      <GmailPanel />
    </div>
  )
}

export const Route = createFileRoute('/app/impostazioni/gmail')({
  validateSearch: (search: Record<string, unknown>): { esito?: string } => ({
    esito: typeof search.esito === 'string' ? search.esito : undefined,
  }),
  component: GmailSettingsRoute,
})
```

`validateSearch` narrows the param rather than rendering it: `ESITO[esito]` looks the code up in a fixed table, so an attacker-supplied `?esito=` cannot put text of their choosing on the page.

- [ ] **Step 5: Run it and watch it pass**

Run: `cd apps/web && pnpm vitest run src/features/gmail && pnpm tsc --noEmit`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/gmail apps/web/src/routes/app/impostazioni/gmail.tsx
git commit -m "feat(web): Impostazioni → Gmail, absent rather than broken when unconfigured"
```

---

### Task B1-16: The persistent shell banner — three causes, three texts

A toast that scrolls away is a silent failure with extra steps.

**Files:**
- Create: `apps/web/src/components/GmailBanner.tsx`
- Modify: `apps/web/src/routes/app.tsx` (mount it in the authenticated shell)
- Create: `apps/web/src/components/GmailBanner.test.tsx`
- Create: `apps/web/e2e/gmail.spec.ts`

**Interfaces:**
- Consumes: `useGmailHealth` from B1-15.
- Produces: `export function GmailBanner(): JSX.Element | null`.

- [ ] **Step 1: Write the failing unit test**

`apps/web/src/components/GmailBanner.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GmailBanner } from './GmailBanner'

function withHealth(banner: string | null, text: string | null) {
  vi.doMock('@/features/gmail/queries', () => ({
    useGmailHealth: () => ({
      data: { account: null, banner, banner_text: text, missing_scopes: [] },
      isError: false,
      isLoading: false,
    }),
  }))
}

describe('GmailBanner', () => {
  it('renders nothing when there is nothing wrong', () => {
    withHealth(null, null)
    const { container } = render(<GmailBanner />)
    expect(container).toBeEmptyDOMElement()
  })

  it('is a persistent region, not a toast', () => {
    // A toast that scrolls away is a silent failure with extra steps.
    withHealth('revoked', 'Il consenso Google per ada@acme.it è stato revocato.')
    render(<GmailBanner />)
    const banner = screen.getByRole('alert')
    expect(banner).toBeInTheDocument()
    expect(banner.querySelector('button[aria-label="Chiudi"]')).toBeNull()
  })

  it('carries the backend text verbatim and links to the settings page', () => {
    // The text comes from the API. Recomputing it here is how the three interfaces
    // start disagreeing.
    withHealth('expiring', 'Il consenso Google va rinnovato entro il 22/08/2026 alle 10:00.')
    render(<GmailBanner />)
    expect(screen.getByRole('alert')).toHaveTextContent('entro il 22/08/2026 alle 10:00')
    expect(screen.getByRole('link', { name: /Impostazioni/ })).toHaveAttribute(
      'href',
      '/app/impostazioni/gmail',
    )
  })

  it('never renders an error of its own when the health request fails', () => {
    // The shell banner is not the place to report that the shell banner could not
    // load: it would appear on every page of a working app during a blip.
    vi.doMock('@/features/gmail/queries', () => ({
      useGmailHealth: () => ({ data: undefined, isError: true, isLoading: false }),
    }))
    const { container } = render(<GmailBanner />)
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 2: Write the failing E2E spec**

`apps/web/e2e/gmail.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { login } from './helpers'

test('a revoked credential shows a persistent banner in the app shell', async ({ page }) => {
  // Spec 13, criterion 5 (e). The API is driven into the revoked state through its own
  // surface, so this exercises the same path a real revocation takes.
  await login(page)
  await page.route('**/api/gmail/account', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        account: null,
        banner: 'revoked',
        banner_text: 'Il consenso Google per ada@acme.it è stato revocato: ricollega la casella.',
        missing_scopes: [],
      }),
    })
  })

  await page.goto('/app/clienti')
  const banner = page.getByRole('alert')
  await expect(banner).toContainText('è stato revocato')

  // Persistent: still there after navigating to a different page of the shell.
  await page.goto('/app/deal')
  await expect(page.getByRole('alert')).toContainText('è stato revocato')
})

test('the banner does not appear on the login screen', async ({ page }) => {
  // An unauthenticated visitor has no google_accounts row to have an opinion about,
  // and the health query would 401 on every page load.
  await page.goto('/app/login')
  await expect(page.getByRole('alert')).toHaveCount(0)
})
```

- [ ] **Step 3: Run both and watch them fail**

Run: `cd apps/web && pnpm vitest run src/components/GmailBanner.test.tsx`
Expected: FAIL — `Failed to resolve import './GmailBanner'`.

- [ ] **Step 4: Write the component and mount it**

`apps/web/src/components/GmailBanner.tsx`:

```tsx
import { Link } from '@tanstack/react-router'
import { useGmailHealth } from '@/features/gmail/queries'

/**
 * Persistent, in the authenticated shell. Three distinct causes get three distinct
 * texts, and the texts come from the API: a single banner reading "problem with Gmail"
 * helps nobody, and recomputing the wording here is how the three interfaces start
 * disagreeing.
 *
 * Mounted in routes/app.tsx and not __root.tsx: an unauthenticated visitor has no
 * google_accounts row to have an opinion about, and the health query would 401 on every
 * page load of the login screen.
 */
export function GmailBanner() {
  const health = useGmailHealth()
  // Deliberately silent on isError: a blip in this one query must not put an error on
  // every page of an otherwise working application. The settings panel is where a
  // failure to read the Gmail state is reported.
  if (health.isError || health.isLoading || !health.data?.banner_text) return null

  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 border-b bg-accent px-4 py-2 text-sm text-accent-foreground"
    >
      <span>{health.data.banner_text}</span>
      <Link to="/app/impostazioni/gmail" className="underline">
        Vai a Impostazioni → Gmail
      </Link>
    </div>
  )
}
```

In `apps/web/src/routes/app.tsx`, render `<GmailBanner />` immediately inside the authenticated shell, above the header, so it is present on every page under `/app/` and on none outside it.

- [ ] **Step 5: Run both and watch them pass**

Run: `cd apps/web && pnpm vitest run src/components/GmailBanner.test.tsx && pnpm test:e2e -- gmail.spec.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/GmailBanner.tsx apps/web/src/components/GmailBanner.test.tsx \
        apps/web/src/routes/app.tsx apps/web/e2e/gmail.spec.ts
git commit -m "feat(web): a persistent Gmail banner with three causes and three texts"
```

---

### Task B1-17: The Email tab, and telling the user when a new address will appear

**Files:**
- Create: `apps/web/src/features/gmail/EmailTab.tsx`
- Create: `apps/web/src/features/gmail/EmailThread.tsx`
- Modify: `apps/web/src/components/EntityDetailLayout.tsx` (an `emails?: ReactNode` slot)
- Modify: `apps/web/src/routes/app/clienti/$customerId.tsx`, `.../persone/$personId.tsx`, `.../deal/$dealId.tsx`
- Modify: `apps/web/src/features/people/PersonForm.tsx` (the notice)
- Create: `apps/web/src/features/gmail/EmailTab.test.tsx`

**Interfaces:**
- Consumes: `useGmailMessages` from B1-15; `EntityDetailLayout`'s existing tab mechanism, which already takes a `documents?: ReactNode` slot from slice 2 — this adds `emails?: ReactNode` the same way.
- Produces: `export function EmailTab(props: { entityType: 'customer' | 'person' | 'deal'; entityId: string }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/gmail/EmailTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { EmailTab } from './EmailTab'
import type { GmailMessageRead } from './queries'

function message(overrides: Partial<GmailMessageRead>): GmailMessageRead {
  return {
    id: 'a',
    gmail_message_id: 'm1',
    gmail_thread_id: 't1',
    direction: 'inbound',
    from_address: 'ada@acme.it',
    to_addresses: ['io@example.it'],
    cc_addresses: [],
    subject: 'Rinnovo',
    snippet: 'Ciao',
    internal_date: '2026-08-18T10:00:00Z',
    body_text: 'Ciao, confermo.',
    body_truncated: false,
    body_html_scartato: false,
    attachments: [],
    ...overrides,
  }
}

function withMessages(data: GmailMessageRead[] | undefined, state: 'ok' | 'error') {
  vi.doMock('./queries', () => ({
    useGmailMessages: () => ({ data, isError: state === 'error', isLoading: false }),
  }))
}

describe('EmailTab', () => {
  it('groups messages by thread and shows the direction', () => {
    withMessages(
      [
        message({ id: 'a', gmail_message_id: 'm1' }),
        message({ id: 'b', gmail_message_id: 'm2', direction: 'outbound', from_address: 'io@example.it' }),
        message({ id: 'c', gmail_message_id: 'm3', gmail_thread_id: 't2', subject: 'Altro' }),
      ],
      'ok',
    )
    render(<EmailTab entityType="customer" entityId="00000000-0000-7000-8000-000000000001" />)
    expect(screen.getAllByRole('group')).toHaveLength(2)
    expect(screen.getByText('Ricevuta')).toBeInTheDocument()
    expect(screen.getByText('Inviata')).toBeInTheDocument()
  })

  it('offers open in Gmail on every message', () => {
    withMessages([message({})], 'ok')
    render(<EmailTab entityType="customer" entityId="00000000-0000-7000-8000-000000000001" />)
    expect(screen.getByRole('link', { name: 'Apri in Gmail' })).toHaveAttribute(
      'href',
      'https://mail.google.com/mail/u/0/#all/m1',
    )
  })

  it('never renders an empty list for a failed request', () => {
    withMessages(undefined, 'error')
    render(<EmailTab entityType="customer" entityId="00000000-0000-7000-8000-000000000001" />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/Nessuna email/)).not.toBeInTheDocument()
  })

  it('says plainly that there is nothing yet, when there genuinely is not', () => {
    withMessages([], 'ok')
    render(<EmailTab entityType="customer" entityId="00000000-0000-7000-8000-000000000001" />)
    expect(screen.getByText(/Nessuna email/)).toBeInTheDocument()
  })

  it('marks a message whose body was dropped or truncated, rather than showing a lie', () => {
    withMessages([message({ body_truncated: true, body_html_scartato: true })], 'ok')
    render(<EmailTab entityType="customer" entityId="00000000-0000-7000-8000-000000000001" />)
    expect(screen.getByText(/troncato/)).toBeInTheDocument()
    expect(screen.getByText(/solo HTML/)).toBeInTheDocument()
  })
})
```

Plus one test in `apps/web/src/features/people/PersonForm.test.tsx`:

```tsx
it('tells the user when a newly added address will start showing conversations', async () => {
  // Spec 4.4 and 11: the address is synchronised on the next cycle, not in the instant
  // it is saved. Saying so beats letting the user discover it.
  render(<PersonForm mode="create" />)
  await userEvent.type(screen.getByLabelText('Email'), 'ada@acme.it')
  expect(
    screen.getByText(/le conversazioni con questo indirizzo compariranno al prossimo sync/i),
  ).toBeInTheDocument()
})
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd apps/web && pnpm vitest run src/features/gmail/EmailTab.test.tsx`
Expected: FAIL — `Failed to resolve import './EmailTab'`.

- [ ] **Step 3: Write the components**

`apps/web/src/features/gmail/EmailTab.tsx`:

```tsx
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { EmailThread } from './EmailThread'
import { useGmailMessages, type GmailMessageRead } from './queries'

function byThread(messages: GmailMessageRead[]): [string, GmailMessageRead[]][] {
  const grouped = new Map<string, GmailMessageRead[]>()
  for (const message of messages) {
    const bucket = grouped.get(message.gmail_thread_id) ?? []
    bucket.push(message)
    grouped.set(message.gmail_thread_id, bucket)
  }
  // Most recently active conversation first: that is the one being worked on.
  return [...grouped.entries()].sort(
    (a, b) =>
      new Date(b[1][b[1].length - 1]!.internal_date).getTime() -
      new Date(a[1][a[1].length - 1]!.internal_date).getTime(),
  )
}

export function EmailTab(props: {
  entityType: 'customer' | 'person' | 'deal'
  entityId: string
}) {
  const messages = useGmailMessages({ entityType: props.entityType, entityId: props.entityId })

  // isError before anything else: an empty tab and a failed request must never look
  // the same.
  if (messages.isError) return <QueryErrorBanner onRetry={() => void messages.refetch()} />
  if (messages.isLoading || !messages.data) return <p>Caricamento…</p>
  if (messages.data.length === 0) {
    return (
      <p className="text-muted-foreground">
        Nessuna email sincronizzata per questa scheda. Le conversazioni compaiono quando un
        indirizzo di questa scheda è presente nell'anagrafica e il sync è stato eseguito.
      </p>
    )
  }

  return (
    <div className="space-y-6">
      {byThread(messages.data).map(([threadId, thread]) => (
        <EmailThread key={threadId} messages={thread} />
      ))}
    </div>
  )
}
```

`apps/web/src/features/gmail/EmailThread.tsx`:

```tsx
import { Badge } from '@/components/ui/badge'
import type { GmailMessageRead } from './queries'

function formatWhen(value: string): string {
  return new Date(value).toLocaleString('it-IT', { dateStyle: 'medium', timeStyle: 'short' })
}

export function EmailThread(props: { messages: GmailMessageRead[] }) {
  const first = props.messages[0]
  if (!first) return null

  return (
    <section role="group" aria-label={first.subject} className="space-y-3">
      <h3 className="text-base font-medium">{first.subject || '(senza oggetto)'}</h3>
      {props.messages.map((message) => (
        <article key={message.id} className="space-y-1 rounded-lg bg-card p-3">
          <header className="flex flex-wrap items-baseline gap-2 text-sm">
            <Badge variant={message.direction === 'inbound' ? 'secondary' : 'outline'}>
              {message.direction === 'inbound' ? 'Ricevuta' : 'Inviata'}
            </Badge>
            <span className="font-medium">{message.from_address}</span>
            <span className="text-muted-foreground">{formatWhen(message.internal_date)}</span>
            {/* Deep-linked by Gmail's own message id: for the original -- HTML, images,
                full headers -- there is Gmail, and that is deliberate. */}
            <a
              className="ml-auto underline"
              href={`https://mail.google.com/mail/u/0/#all/${message.gmail_message_id}`}
              target="_blank"
              rel="noreferrer"
            >
              Apri in Gmail
            </a>
          </header>

          <p className="whitespace-pre-wrap text-sm">{message.body_text}</p>

          {/* The two honesty markers. A stored body that is not the whole story has to
              say so: showing a silently shortened or silently converted message as if it
              were the original is the CRM believing something other than what happened. */}
          {message.body_truncated ? (
            <p className="text-xs text-muted-foreground">
              Corpo troncato: il messaggio superava il limite di 256 KB. L'originale è in Gmail.
            </p>
          ) : null}
          {message.body_html_scartato ? (
            <p className="text-xs text-muted-foreground">
              Il messaggio era solo HTML: qui è conservata la conversione in testo. L'HTML non
              viene mostrato perché porta con sé pixel di tracciamento e CSS remoto.
            </p>
          ) : null}

          {message.attachments.length > 0 ? (
            <ul className="text-sm">
              {message.attachments.map((attachment) => (
                <li key={String(attachment.filename)} className="flex items-center gap-2">
                  <span>
                    {String(attachment.filename)} · {String(attachment.mime)} ·{' '}
                    {Math.round(Number(attachment.size) / 1024)} KB
                  </span>
                  {/* No bytes were stored (spec 5.4), so this action fetches from Gmail
                      and writes through DocumentStorage -- the layer that already has the
                      authorisation, the hash and the versioning. */}
                  <button type="button" className="underline">
                    Salva come documento
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </article>
      ))}
    </section>
  )
}
```

The «Salva come documento» button's handler is the one piece of this component that needs a backend endpoint of its own (`POST /api/gmail/messages/{id}/attachments/{index}/save`, which fetches the attachment by `attachmentId` and writes it through `DocumentService`). It is **not** in this slice's REST surface (spec §8.3 does not list it), so wire the button to a disabled state with `title="In arrivo"` and open it as a follow-up — do not invent the endpoint here. Recorded in the self-review below as the one spec sentence that did not become a task.

`EntityDetailLayout` gains `emails?: ReactNode` beside the existing `documents?: ReactNode`, and a tab labelled `Email` rendered when it is provided — the same shape slice 2 used, so the component still has one page structure rather than three that resemble each other.

In `PersonForm.tsx`, render the notice under the Email field whenever the field is non-empty and the form's `mode` is `'create'` or the value changed in `'edit'`:

```tsx
{form.native.email ? (
  <p className="text-sm text-muted-foreground">
    Le conversazioni con questo indirizzo compariranno al prossimo sync di Gmail, non
    immediatamente.
  </p>
) : null}
```

`form.native.email` reads the native namespace: the email is a native column, so it clears on `""` and only on `""`.

- [ ] **Step 4: Run it and watch it pass**

Run: `cd apps/web && pnpm vitest run && pnpm tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src apps/web/e2e
git commit -m "feat(web): an Email tab on customer, person and deal"
```

---

**5B-1 is done here.** At this point the CRM reads only the conversations it can justify reading, records what it did, and says so out loud when it cannot. 5B-2 adds the only path that sends anything.

---
# 5B-2 — Send and payment reminders

**What must exist before 5B-2 can start:**

1. **5B-1 merged.** 5B-2 uses its `google_accounts` row, its transport seam, its `FakeGmail`, its `GoogleAccountService.usable` gate and its `rfc822msgid_query`.
2. Slice 2 — **already in the tree**: `documents/`, `document_versions.storage_key`, `DocumentStorage.get`, the `{{}}`/`#if` template engine, and `emitter_profile`. Attachments and the reminder text both depend on it.
3. **For the reminder half only: slice 3 (invoices), which is in progress but not yet usable.** As of this writing `packages/core/src/pigrocrm/core/invoices/` contains `schemas.py` and `totals.py` but **no `models.py`** — so there is no `invoices` table, no `Invoice` ORM class and nothing for `payment_reminders.invoice_id` to reference. Tasks **B2-8, B2-9 and B2-12** are therefore marked **BLOCKED ON SLICE 3** and name the exact invoice fields they consume. The unblocking condition is precise: `Invoice` importable from `pigrocrm.core.invoices.models`, with an `invoices` table in a migration, carrying a due date and a payment state. Do not start them by inventing an invoice model — an invented `data_scadenza` is worse than a missing feature, because the reminder logic would be tested against a shape slice 3 then contradicts. Check `invoices/schemas.py` for the real field names before writing B2-8: they may already be settled there even though the model is not.
4. The Gmail client must hold `gmail.send` among its granted scopes. If only `gmail.readonly` was granted, sending refuses by naming the scope (B1-12's gate), which is correct behaviour and not a blocker for building.

**Tasks:** 12 — nine executable as soon as 5B-1 lands, three blocked on slice 3. Migrations land at `0008` (B2-3), `0009` (B2-7) and `0010` (B2-8).

---

### Task B2-1: Verify that Gmail preserves a client-supplied `Message-ID`

Spec §6.3 is explicit: *"To verify in the first task of the send, not to assume."* The whole exact-reconciliation design rests on it, and the fallback is materially worse, so this is settled before anything is built on top.

**Files:**
- Create: `docs/superpowers/notes/2026-08-20-gmail-message-id-verification.md`
- Create: `packages/core/tests/test_gmail_message_id_contract.py`
- Modify: `packages/core/src/pigrocrm/core/config.py` (one setting)

**Interfaces:**
- Produces:
  ```python
  # config.py
  gmail_reconcile_by_message_id: bool = True
  ```
  and a recorded verification result. Consumed by B2-6, which branches on that setting exactly once.

- [ ] **Step 1: Run the verification by hand, against real Gmail, once**

This is the one manual step in the whole plan, and it is manual because it is a question about Google's behaviour that no fake can answer. Use a throwaway Google account and the OAuth client from 5B-1.

```bash
# 1. Obtain an access token with gmail.send + gmail.readonly (use the app's own
#    /api/gmail/oauth/start against a dev instance, then read the token from the
#    in-process cache via a one-off `uv run python -c` against GoogleTokenClient).
# 2. Send a message carrying a Message-ID we chose.
MSGID="pigrocrm-verify-$(date +%s)@example.invalid"
RAW=$(printf 'From: me@example.it\r\nTo: me@example.it\r\nSubject: verifica Message-ID\r\nMessage-ID: <%s>\r\nContent-Type: text/plain; charset="UTF-8"\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\nverifica\r\n' "$MSGID" \
  | base64 | tr '+/' '-_' | tr -d '=\n')
curl -sS -X POST "https://gmail.googleapis.com/gmail/v1/users/me/messages/send" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"raw\":\"$RAW\"}"

# 3. Ask for it back by the Message-ID we supplied.
curl -sS -G "https://gmail.googleapis.com/gmail/v1/users/me/messages" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "q=rfc822msgid:$MSGID"
```

If step 3 returns exactly one message, the `Message-ID` is preserved and the exact path holds.

- [ ] **Step 2: Record the result, whichever it is**

`docs/superpowers/notes/2026-08-20-gmail-message-id-verification.md`:

```markdown
# Does Gmail preserve a client-supplied Message-ID on messages.send?

**Verified:** <date>  ·  **By:** <name>  ·  **Account type:** <consumer | Workspace>

## Method
Sent an RFC822 message with `Message-ID: <pigrocrm-verify-…@example.invalid>` through
`POST /gmail/v1/users/me/messages/send`, then queried
`users.messages.list?q=rfc822msgid:<the same id>`.

## Result
- Message-ID preserved: **YES / NO**
- Messages returned by the rfc822msgid query: **<n>**
- The id Gmail assigned: `<gmail message id>`

## Consequence
- **YES** → `PIGROCRM_GMAIL_RECONCILE_BY_MESSAGE_ID` stays `true`. Reconciliation is
  exact: one lookup, one answer, no guessing. This is the path spec 6.3 wants.
- **NO** → set it to `false`. Reconciliation falls back to matching on recipient +
  subject + `internalDate` inside the grace window, within the per-address sweep the
  sync already performs. This is **declaredly inferior** — it is an approximate match,
  and two identical messages minutes apart are indistinguishable under it — which is
  exactly why the Message-ID path is the one to use if it holds.

## Re-verify when
Google changes the Gmail API's documented behaviour, or a Workspace tenant with a
transport rule that rewrites headers is onboarded. This is a statement about a third
party, so it has a shelf life.
```

- [ ] **Step 3: Add the setting**

In `Settings`, beside the other Gmail settings:

```python
    # Whether reconciliation may rely on Gmail preserving the Message-ID we supply.
    # Verified once, by hand, and recorded in
    # docs/superpowers/notes/2026-08-20-gmail-message-id-verification.md -- spec 6.3
    # requires this to be verified rather than assumed, because the fallback (matching
    # on recipient + subject + internalDate) is an approximate comparison and cannot
    # tell two near-identical sends apart.
    gmail_reconcile_by_message_id: bool = True
```

- [ ] **Step 4: Write the contract test both ways**

`packages/core/tests/test_gmail_message_id_contract.py`:

```python
"""The fake's send/lookup behaviour must match whatever the note recorded.

This does not verify Gmail -- no test in this slice touches the network. It verifies
that `FakeGmail` models the *verified* behaviour, so every test built on it is testing
the real contract rather than a convenient one.
"""

from pathlib import Path

from pigrocrm.core.gmail.query import rfc822msgid_query
from tests.fakes.fake_gmail import FakeGmail, FakeMessage

NOTE = (
    Path(__file__).parents[3]
    / "docs/superpowers/notes/2026-08-20-gmail-message-id-verification.md"
)


def test_the_verification_was_actually_performed_and_recorded() -> None:
    """A design that rests on a third party's behaviour needs the check written down,
    with a date and a result. An unrecorded verification is an assumption."""
    text = NOTE.read_text(encoding="utf-8")
    assert "Message-ID preserved: **YES**" in text or "Message-ID preserved: **NO**" in text, (
        "fill in the verification note before building on its result"
    )
    assert "<date>" not in text, "the note still has its placeholders"


def test_the_fake_returns_a_sent_message_by_the_message_id_we_supplied() -> None:
    fake = FakeGmail()
    fake.messages["sent-1"] = FakeMessage(
        id="sent-1",
        thread_id="t-sent-1",
        headers={
            "From": "io@example.it",
            "To": "ada@acme.it",
            "Subject": "Offerta",
            "Message-ID": "<ours.1@crm.example.it>",
        },
        internal_date_ms=1_723_000_000_000,
    )
    status, body, _ = fake(
        "GET",
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?q="
        + rfc822msgid_query("<ours.1@crm.example.it>"),
        {},
        None,
    )
    assert status == 200
    assert b"sent-1" in body


def test_the_fake_finds_nothing_for_a_message_id_that_was_never_delivered() -> None:
    fake = FakeGmail()
    status, body, _ = fake(
        "GET",
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?q="
        + rfc822msgid_query("<never.sent@crm.example.it>"),
        {},
        None,
    )
    assert status == 200
    assert b'"messages": []' in body.replace(b" ", b" ")
```

`FakeGmail._send` must additionally register the sent message in `self.messages` under its returned id, with the `Message-ID` taken from the RFC822 it received — otherwise the reconciliation tests in B2-6 would pass against a fake that cannot lose a message, which is the one thing they are about. Add that in this task:

```python
    def _send(self) -> tuple[int, bytes, dict[str, str]]:
        request = self.requests[-1]
        raw = self._decode_raw(request.body)
        if self.timeout_on_send:
            # Two flavours, and the difference is the whole of spec 6.3: with
            # `deliver_on_timeout` the message really did arrive and only the answer was
            # lost -- which is the case Acme gets wrong in production.
            if self.deliver_on_timeout:
                self._register_sent(raw)
            return 599, json.dumps({"error": {"message": "timed out"}}).encode(), {}
        message = self._register_sent(raw)
        return 200, json.dumps({"id": message.id, "threadId": message.thread_id}).encode(), {}
```

with `deliver_on_timeout: bool = False`, a `_decode_raw` that base64url-decodes `{"raw": …}`, and a `_register_sent` that parses the `Message-ID`, `To` and `Subject` headers out of it and stores a `FakeMessage`.

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_message_id_contract.py -v`
Expected: PASS once the note is filled in. Until then the first test fails, and that failure is the point: nothing downstream should be built on an unverified assumption.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/notes/2026-08-20-gmail-message-id-verification.md \
        packages/core/src/pigrocrm/core/config.py packages/core/tests/fakes/fake_gmail.py \
        packages/core/tests/test_gmail_message_id_contract.py
git commit -m "test(gmail): verify Gmail keeps our Message-ID, and record the result"
```

---

### Task B2-2: The RFC822 builder — three defects of Acme's, none repeated

`buildRawEmailMessage` (`.reference-acme/website/vite.config.js:2480-2525`) hand-rolls `multipart/mixed` and gets three things wrong: no `Message-ID`, no `In-Reply-To`/`References`, and `Content-Transfer-Encoding: 7bit` declared over Italian text containing `à` and `’` — **a live defect in production**.

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/rfc822.py`
- Create: `packages/core/tests/test_gmail_rfc822.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class OutgoingAttachment:
      filename: str
      mime: str
      content: bytes

  def new_message_id(domain: str) -> str          # "<uuid7hex.epoch@domain>"
  def build_rfc822(*, from_address: str, from_name: str, to: Sequence[str],
                   cc: Sequence[str], subject: str, body_text: str, message_id: str,
                   in_reply_to: str = "", references: str = "",
                   attachments: Sequence[OutgoingAttachment] = ()) -> bytes
  def to_base64url(raw: bytes) -> str
  ```
  Consumed by B2-5 and B2-9.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_rfc822.py`:

```python
import base64
import re
from email import message_from_bytes
from email.policy import default as default_policy

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.gmail.rfc822 import (
    OutgoingAttachment,
    build_rfc822,
    new_message_id,
    to_base64url,
)

# Accents, typographic quotes, an em dash and an emoji. Acme declares 7bit over text
# like this; it works by accident until the first mail client that takes the
# declaration literally.
TRICKY = "Però è già così — l’offerta “definitiva” costa 1.200 € 🎉"


def _parsed(raw: bytes):
    return message_from_bytes(raw, policy=default_policy)


def test_the_body_round_trips_character_for_character() -> None:
    """Spec 13, criterion 12."""
    raw = build_rfc822(
        from_address="io@example.it",
        from_name="Io",
        to=["ada@acme.it"],
        cc=[],
        subject=TRICKY,
        body_text=TRICKY,
        message_id="<a.1@crm.example.it>",
    )
    message = _parsed(raw)
    assert message.get_content().rstrip("\n") == TRICKY
    assert message["Subject"] == TRICKY


def test_no_branch_declares_seven_bit_over_non_ascii() -> None:
    """The live Acme defect, banned by name. Checked over every branch: plain, with a
    cc, and with an attachment."""
    for attachments in ((), (OutgoingAttachment("offerta.pdf", "application/pdf", b"%PDF-1.7\n"),)):
        raw = build_rfc822(
            from_address="io@example.it",
            from_name="Io",
            to=["ada@acme.it"],
            cc=["bob@acme.it"],
            subject=TRICKY,
            body_text=TRICKY,
            message_id="<a.2@crm.example.it>",
            attachments=attachments,
        )
        text_parts = [
            part
            for part in _parsed(raw).walk()
            if part.get_content_maintype() == "text"
        ]
        assert text_parts
        for part in text_parts:
            assert part["Content-Transfer-Encoding"] in {"quoted-printable", "base64"}
            assert part.get_content_charset() == "utf-8"
        assert b"7bit" not in raw


def test_a_message_id_is_always_present_and_is_the_one_we_chose() -> None:
    raw = build_rfc822(
        from_address="io@example.it",
        from_name="Io",
        to=["ada@acme.it"],
        cc=[],
        subject="x",
        body_text="y",
        message_id="<chosen.1@crm.example.it>",
    )
    assert _parsed(raw)["Message-ID"] == "<chosen.1@crm.example.it>"


def test_a_generated_message_id_is_unique_and_uses_the_configured_domain() -> None:
    ids = {new_message_id("crm.example.it") for _ in range(100)}
    assert len(ids) == 100
    for value in ids:
        assert re.fullmatch(r"<[0-9a-f]+\.\d+@crm\.example\.it>", value), value


def test_a_reply_carries_in_reply_to_and_references() -> None:
    """Spec 6.2 rule 2 and criterion 13. Without these, a reminder arrives detached:
    whoever receives it cannot see the invoice above it, and the first thing they do is
    ask for it to be resent."""
    raw = build_rfc822(
        from_address="io@example.it",
        from_name="Io",
        to=["ada@acme.it"],
        cc=[],
        subject="Re: Fattura 2026/14",
        body_text="Sollecito",
        message_id="<reminder.1@crm.example.it>",
        in_reply_to="<original.1@crm.example.it>",
        references="<thread.root@acme.it> <original.1@crm.example.it>",
    )
    message = _parsed(raw)
    assert message["In-Reply-To"] == "<original.1@crm.example.it>"
    assert message["References"] == "<thread.root@acme.it> <original.1@crm.example.it>"


def test_an_attachment_keeps_its_name_its_type_and_its_bytes() -> None:
    pdf = b"%PDF-1.7\n%\xc3\xa8\xc3\xa9 binary\n"
    raw = build_rfc822(
        from_address="io@example.it",
        from_name="Io",
        to=["ada@acme.it"],
        cc=[],
        subject="Offerta",
        body_text="In allegato.",
        message_id="<a.3@crm.example.it>",
        attachments=[OutgoingAttachment("Offerta — così.pdf", "application/pdf", pdf)],
    )
    message = _parsed(raw)
    assert message.get_content_maintype() == "multipart"
    parts = [p for p in message.walk() if p.get_filename()]
    assert len(parts) == 1
    # A non-ASCII filename has to survive too: Italian document titles have accents.
    assert parts[0].get_filename() == "Offerta — così.pdf"
    assert parts[0].get_payload(decode=True) == pdf


def test_a_newline_in_a_header_is_refused_rather_than_injected() -> None:
    """A subject carrying CRLF would let a caller append arbitrary headers -- a Bcc, for
    instance. Escaping is decided by context, and the context here is an RFC822 header."""
    for hostile in ["Offerta\r\nBcc: chiunque@altrove.it", "Offerta\nX-Header: x", "a\rb"]:
        with pytest.raises(ValidationFailed) as caught:
            build_rfc822(
                from_address="io@example.it",
                from_name="Io",
                to=["ada@acme.it"],
                cc=[],
                subject=hostile,
                body_text="x",
                message_id="<a.4@crm.example.it>",
            )
        assert caught.value.details["field"] == "subject"


def test_a_recipient_that_is_not_an_address_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        build_rfc822(
            from_address="io@example.it",
            from_name="Io",
            to=["ada@acme.it, bcc@altrove.it"],
            cc=[],
            subject="x",
            body_text="y",
            message_id="<a.5@crm.example.it>",
        )


def test_at_least_one_recipient_is_required() -> None:
    with pytest.raises(ValidationFailed):
        build_rfc822(
            from_address="io@example.it",
            from_name="Io",
            to=[],
            cc=[],
            subject="x",
            body_text="y",
            message_id="<a.6@crm.example.it>",
        )


def test_base64url_output_is_what_the_send_endpoint_expects() -> None:
    encoded = to_base64url(b"ciao \xc3\xa8")
    assert "+" not in encoded and "/" not in encoded and "=" not in encoded
    assert base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)) == b"ciao \xc3\xa8"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_rfc822.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.rfc822'`.

- [ ] **Step 3: Write the builder**

`packages/core/src/pigrocrm/core/gmail/rfc822.py`:

```python
"""Building the message Gmail will send.

Same structure as Acme's `buildRawEmailMessage` -- `multipart/mixed`, base64url for the
`raw` field -- and none of its three defects:

1. **`Message-ID` is always present**, generated here, with the right-hand side derived
   from the configured domain. It is what makes the thread correct when the client
   replies, and what makes the reconciliation of spec 6.3 exact rather than heuristic.
2. **`In-Reply-To` and `References` are set** when replying or chasing inside an
   existing thread. Without them the reminder arrives detached, and the first thing the
   recipient does is ask for the invoice again.
3. **The body declares `quoted-printable` or `base64`, with `charset="UTF-8"`. Never
   `7bit`.** Acme declares `7bit` over text containing `à` and `’`; it works by accident
   until the first client that takes the declaration literally.

Built on `email.message.EmailMessage` from the standard library rather than by string
concatenation. That is the point of the third defect: the encoding rules are subtle,
they are already implemented correctly, and hand-rolling them is what produced the bug.
"""

import base64
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP

from pigrocrm.core.db import uuid7
from pigrocrm.core.errors import ValidationFailed

# Deliberately strict: these strings become RFC822 headers.
_ADDRESS = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}")
_MESSAGE_ID = re.compile(r"<[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}>")
_CONTROL = re.compile(r"[\r\n\x00]")


@dataclass(frozen=True)
class OutgoingAttachment:
    filename: str
    mime: str
    content: bytes


def new_message_id(domain: str) -> str:
    """`<uuid7hex.epoch@domain>`. UUIDv7 for the left half so two ids minted in the same
    second still differ, and the epoch so a human reading a header can date it."""
    if not _ADDRESS.fullmatch(f"x@{domain}"):
        raise ValidationFailed(
            "email_draft", "message_id_domain", "non è un dominio valido", expected="esempio.it"
        )
    return f"<{uuid7().hex}.{int(time.time())}@{domain}>"


def _header(value: str, field: str) -> str:
    """No CR, LF or NUL in a header value. A subject carrying CRLF would let a caller
    append arbitrary headers -- a `Bcc`, for instance -- which is header injection, the
    same class of defect as SQL injection and with the same non-fix (hoping nobody
    tries)."""
    if _CONTROL.search(value):
        raise ValidationFailed(
            "email_draft",
            field,
            "non può contenere ritorni a capo o byte NUL",
            expected="una sola riga di testo",
        )
    return value


def _addresses(values: Sequence[str], field: str) -> list[str]:
    checked: list[str] = []
    for value in values:
        candidate = value.strip()
        if not _ADDRESS.fullmatch(candidate):
            raise ValidationFailed(
                "email_draft", field, f"{candidate!r} non è un indirizzo email valido"
            )
        checked.append(candidate)
    return checked


def build_rfc822(
    *,
    from_address: str,
    from_name: str,
    to: Sequence[str],
    cc: Sequence[str],
    subject: str,
    body_text: str,
    message_id: str,
    in_reply_to: str = "",
    references: str = "",
    attachments: Sequence[OutgoingAttachment] = (),
) -> bytes:
    recipients = _addresses(to, "to")
    if not recipients:
        raise ValidationFailed("email_draft", "to", "serve almeno un destinatario")
    copies = _addresses(cc, "cc")
    sender = _addresses([from_address], "from_address")[0]
    if not _MESSAGE_ID.fullmatch(message_id):
        raise ValidationFailed(
            "email_draft", "message_id", "deve avere la forma <local@dominio.tld>"
        )

    message = EmailMessage(policy=SMTP)
    # `EmailMessage` applies RFC 2047 encoded-words to a header containing non-ASCII by
    # itself, which is the other half of what Acme got wrong -- its subjects were raw
    # UTF-8 in a header field.
    message["From"] = f"{_header(from_name, 'from_name')} <{sender}>" if from_name else sender
    message["To"] = ", ".join(recipients)
    if copies:
        message["Cc"] = ", ".join(copies)
    message["Subject"] = _header(subject, "subject")
    message["Message-ID"] = message_id
    if in_reply_to:
        message["In-Reply-To"] = _header(in_reply_to, "in_reply_to")
    if references:
        message["References"] = _header(references, "references")

    # `cte="quoted-printable"` explicitly, never the default: the default picks 7bit for
    # a body that happens to be ASCII today, and an Italian body one edit later is not.
    # Choosing it unconditionally means there is no branch in which 7bit can appear.
    message.set_content(body_text, subtype="plain", charset="utf-8", cte="quoted-printable")

    for attachment in attachments:
        maintype, _, subtype = attachment.mime.partition("/")
        message.add_attachment(
            attachment.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=_header(attachment.filename, "attachment_filename"),
        )

    return message.as_bytes()


def to_base64url(raw: bytes) -> str:
    """What `users.messages.send` wants in its `raw` field: base64url, unpadded."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_rfc822.py -v`
Expected: PASS (10 tests). If `test_no_branch_declares_seven_bit_over_non_ascii` fails, do not relax it — it is the reproduction of a defect currently live in production.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail/rfc822.py packages/core/tests/test_gmail_rfc822.py
git commit -m "feat(gmail): RFC822 with a Message-ID, a thread and never 7bit"
```

---

### Task B2-3: `email_drafts` — the draft is durable, and it comes first

**Files:**
- Modify: `packages/core/src/pigrocrm/core/gmail/models.py` (append `EmailDraft`)
- Create: `packages/core/src/pigrocrm/core/gmail/drafts.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/schemas.py`
- Create: `packages/core/migrations/versions/0008_email_drafts.py`
- Modify: `packages/core/tests/test_migrations.py:139,161`
- Create: `packages/core/tests/test_email_drafts.py`

**Interfaces:**
- Produces:
  ```python
  SendState = Literal["bozza", "in_invio", "inviato", "incerto", "fallito"]

  class EmailDraftCreate(BaseModel):
      entity_type: Literal["customer", "person", "deal"]
      entity_id: UUID
      to_addresses: list[SafeStr]          # each max_length=320
      cc_addresses: list[SafeStr] = []
      subject: SafeStr                     # max_length=998
      body_markdown: SafeStr               # max_length=100_000
      attachment_version_ids: list[UUID] = []
      in_reply_to_message_id: UUID | None = None

  class EmailDraftUpdate(BaseModel):
      to_addresses: list[SafeStr] | None = None
      cc_addresses: list[SafeStr] | None = None
      subject: SafeStr | None = None            # max_length=998
      body_markdown: SafeStr | None = None      # max_length=100_000
      attachment_version_ids: list[UUID] | None = None

  class EmailDraftRead(BaseModel):
      # Every column of EmailDraft, from_attributes=True. Full field list in Step 4.
      id: UUID
      send_state: SendState
      message_id_header: str

  class EmailDraftService:
      def __init__(self, session: Session, *, settings: Settings) -> None: ...
      def create(self, data: EmailDraftCreate, actor: Actor) -> EmailDraftRead: ...
      def update(self, draft_id: UUID, data: EmailDraftUpdate, actor: Actor) -> EmailDraftRead: ...
      def get(self, draft_id: UUID, actor: Actor) -> EmailDraftRead: ...
      def delete(self, draft_id: UUID, actor: Actor) -> None: ...
      def repo_draft(self, draft_id: UUID) -> EmailDraft: ...   # the ORM row, for tests
      def list(self, query: EmailDraftListQuery, actor: Actor) -> EmailDraftPage: ...  # LAST
  ```
  Consumed by B2-4, B2-5, B2-9, B2-10, B2-11.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_email_drafts.py`:

```python
import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.gmail.drafts import EmailDraftService
from pigrocrm.core.gmail.schemas import EmailDraftCreate, EmailDraftUpdate
from tests.fakes.gmail_fixtures import actor_for, connected_account, gmail_settings


def _customer(session: Session) -> Customer:
    customer = Customer(ragione_sociale="Acme", email="info@acme.it")
    session.add(customer)
    session.flush()
    return customer


def _payload(customer: Customer, **overrides: object) -> EmailDraftCreate:
    base: dict[str, object] = {
        "entity_type": "customer",
        "entity_id": customer.id,
        "to_addresses": ["ada@acme.it"],
        "subject": "Offerta",
        "body_markdown": "Gentile Ada,\n\nin allegato l'offerta.",
    }
    return EmailDraftCreate(**{**base, **overrides})  # type: ignore[arg-type]


def _service(session: Session) -> EmailDraftService:
    return EmailDraftService(session, settings=gmail_settings())


def test_a_draft_is_written_to_the_database_before_anything_else(db_session: Session) -> None:
    """Losing a hand-written email to an HTTP error is unforgivable, and a composer that
    keeps the text only in React state loses it on the first refresh."""
    account = connected_account(db_session)
    customer = _customer(db_session)
    read = _service(db_session).create(_payload(customer), actor_for(account))
    db_session.commit()
    assert read.send_state == "bozza"
    assert read.body_markdown.startswith("Gentile Ada")


def test_a_message_id_is_minted_at_creation_not_at_send(db_session: Session) -> None:
    """Spec 6.2: the Message-ID exists *before* Gmail is called. That is what makes an
    unknown outcome resolvable by lookup instead of by guessing."""
    account = connected_account(db_session)
    customer = _customer(db_session)
    read = _service(db_session).create(_payload(customer), actor_for(account))
    assert read.message_id_header.startswith("<")
    assert read.message_id_header.endswith(">")


def test_two_drafts_never_share_a_message_id(db_session: Session) -> None:
    account = connected_account(db_session)
    customer = _customer(db_session)
    service = _service(db_session)
    ids = {service.create(_payload(customer), actor_for(account)).message_id_header for _ in range(10)}
    assert len(ids) == 10


def test_editing_a_draft_keeps_its_message_id(db_session: Session) -> None:
    """Changing the id on every keystroke would make the reconciliation look for a
    message that was never sent under that name."""
    account = connected_account(db_session)
    customer = _customer(db_session)
    service = _service(db_session)
    created = service.create(_payload(customer), actor_for(account))
    db_session.commit()
    updated = service.update(
        created.id, EmailDraftUpdate(body_markdown="Testo nuovo"), actor_for(account)
    )
    assert updated.message_id_header == created.message_id_header
    assert updated.body_markdown == "Testo nuovo"


def test_a_sent_draft_can_no_longer_be_edited(db_session: Session) -> None:
    account = connected_account(db_session)
    customer = _customer(db_session)
    service = _service(db_session)
    created = service.create(_payload(customer), actor_for(account))
    draft = service.repo_draft(created.id)
    draft.send_state = "inviato"
    db_session.commit()
    with pytest.raises(Conflict, match="già inviata"):
        service.update(created.id, EmailDraftUpdate(subject="Altro"), actor_for(account))


def test_an_unknown_entity_is_a_not_found_not_a_foreign_key_error(db_session: Session) -> None:
    from uuid import uuid4

    account = connected_account(db_session)
    customer = _customer(db_session)
    with pytest.raises(NotFound):
        _service(db_session).create(
            _payload(customer, entity_id=uuid4()), actor_for(account)
        )


def test_an_over_long_subject_is_rejected_by_the_schema_not_by_postgres(
    db_session: Session,
) -> None:
    with pytest.raises(Exception) as caught:
        EmailDraftCreate(
            entity_type="customer",
            entity_id=__import__("uuid").uuid4(),
            to_addresses=["a@b.it"],
            subject="x" * 999,
            body_markdown="y",
        )
    assert "998" in str(caught.value) or "at most" in str(caught.value)


def test_a_nul_byte_in_the_body_is_rejected_and_not_stripped(db_session: Session) -> None:
    with pytest.raises(Exception):
        EmailDraftCreate(
            entity_type="customer",
            entity_id=__import__("uuid").uuid4(),
            to_addresses=["a@b.it"],
            subject="x",
            body_markdown="prima\x00dopo",
        )


def test_a_draft_with_no_recipients_is_refused_at_creation(db_session: Session) -> None:
    account = connected_account(db_session)
    customer = _customer(db_session)
    with pytest.raises(ValidationFailed):
        _service(db_session).create(_payload(customer, to_addresses=[]), actor_for(account))


def test_list_is_the_last_method_defined_on_the_service() -> None:
    """A method named `list` rebinds the builtin in the class namespace, so a later
    method annotated `-> list[...]` fails at import on Python 3.13. The rule is
    unconditional, so it is asserted rather than remembered."""
    import inspect

    source = inspect.getsource(EmailDraftService)
    names = [
        match.group(1)
        for match in __import__("re").finditer(r"\n    def ([a-zA-Z_]\w*)\(", source)
    ]
    assert names[-1] == "list", names
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_email_drafts.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.drafts'`.

- [ ] **Step 3: Write the model**

Append to `gmail/models.py`:

```python
class EmailDraft(Base, PrimaryKeyMixin, TimestampMixin):
    """A message being written, and the record of what happened to it.

    Written to the database **before** Gmail is called. Two reasons, and the second is
    the load-bearing one: losing hand-written text to an HTTP error is unforgivable, and
    the `message_id_header` minted here is what makes an unknown send outcome resolvable
    by an exact lookup instead of a guess (spec 6.3).

    Acme kept this in a JSON file with a non-atomic read-modify-write, so two
    concurrent sends lost the count. The columns are the same ones -- they were the right
    columns -- on a support that cannot lose a write.
    """

    __tablename__ = "email_drafts"
    __table_args__ = (
        UniqueConstraint("message_id_header", name="uq_email_drafts_message_id"),
        Index("ix_email_drafts_entity", "entity_type", "entity_id"),
        Index("ix_email_drafts_send_state", "send_state"),
    )

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cc_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attachment_version_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Ours, minted at creation. Unique, because the reconciliation looks a draft up by
    # it: two drafts sharing one id would make that lookup ambiguous exactly when it
    # matters most.
    message_id_header: Mapped[str] = mapped_column(String(998), nullable=False)
    # The thread this reply or reminder belongs to, so In-Reply-To/References can be set.
    in_reply_to_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("gmail_messages.id", ondelete="SET NULL"), default=None
    )
    send_state: Mapped[str] = mapped_column(String(10), nullable=False, default="bozza")
    send_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_error: Mapped[str | None] = mapped_column(String(500), default=None)
    # The sent message, once Gmail has answered. Never before.
    sent_gmail_message_id: Mapped[str | None] = mapped_column(String(128), default=None)
    payment_reminder_id: Mapped[UUID | None] = mapped_column(default=None)
```

`payment_reminder_id` is a plain nullable `UUID` with **no** foreign key, because `payment_reminders` does not exist until B2-8 and slice 3. B2-8 adds the constraint in its own migration. Recorded here so the absence is a decision rather than an oversight.

- [ ] **Step 4: Write the schemas and the service**

Append to `gmail/schemas.py`:

```python
SUBJECT_MAX_LENGTH = 998
BODY_MAX_LENGTH = 100_000
SendState = Literal["bozza", "in_invio", "inviato", "incerto", "fallito"]


class EmailDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: Literal["customer", "person", "deal"]
    entity_id: UUID
    to_addresses: list[Annotated[SafeStr, Field(max_length=EMAIL_ADDRESS_MAX_LENGTH)]]
    cc_addresses: list[Annotated[SafeStr, Field(max_length=EMAIL_ADDRESS_MAX_LENGTH)]] = []
    subject: SafeStr = Field(max_length=SUBJECT_MAX_LENGTH)
    # 100 000 characters is generous for an email and bites only on the anomalous, the
    # same discipline as the 256 KB inbound body limit.
    body_markdown: SafeStr = Field(max_length=BODY_MAX_LENGTH)
    attachment_version_ids: list[UUID] = []
    in_reply_to_message_id: UUID | None = None


class EmailDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_addresses: list[Annotated[SafeStr, Field(max_length=EMAIL_ADDRESS_MAX_LENGTH)]] | None = None
    cc_addresses: list[Annotated[SafeStr, Field(max_length=EMAIL_ADDRESS_MAX_LENGTH)]] | None = None
    subject: SafeStr | None = Field(default=None, max_length=SUBJECT_MAX_LENGTH)
    body_markdown: SafeStr | None = Field(default=None, max_length=BODY_MAX_LENGTH)
    attachment_version_ids: list[UUID] | None = None


class EmailDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: str
    body_markdown: str
    attachment_version_ids: list[UUID]
    message_id_header: str
    in_reply_to_message_id: UUID | None
    send_state: SendState
    send_attempted_at: datetime | None
    last_error: str | None
    sent_gmail_message_id: str | None
    payment_reminder_id: UUID | None
    created_at: datetime
    updated_at: datetime


class EmailDraftListQuery(BaseModel):
    entity_type: Literal["customer", "person", "deal"] | None = None
    entity_id: UUID | None = None
    send_state: SendState | None = None
    limit: int = Field(default=50, ge=1, le=200)


class EmailDraftPage(BaseModel):
    items: list[EmailDraftRead]
    total: int
```

`packages/core/src/pigrocrm/core/gmail/drafts.py` holds `EmailDraftService` with `create`, `update`, `get`, `delete`, `repo_draft` and — **last** — `list`. `create` mints the `Message-ID` with `new_message_id(self._domain())`, where `_domain` takes the host of `Settings.public_url` (falling back to `emitter_profile.sito_web`'s host, then to `localhost.invalid`, which is the honest value for an install with neither). `update` refuses any draft whose `send_state` is not `bozza` with `Conflict("email_draft", "questa email è già inviata o in invio: duplicala per modificarla")`. Every FK-shaped value — `entity_id` against its table, each `attachment_version_ids` entry against `document_versions` — is validated in both `create` and `update`, so a syntactically valid UUID becomes `NotFound` rather than a raw `IntegrityError`.

- [ ] **Step 5: Migration, registry, revision bump**

Register `EmailDraft`, generate `0008_email_drafts.py`, set `revision = "0008"` / `down_revision = "0007"`, bump `test_migrations.py:139,161` to `"0008"`.

- [ ] **Step 6: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_email_drafts.py packages/core/tests/test_migrations.py packages/core/tests/test_module_imports.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/migrations/versions/0008_email_drafts.py \
        packages/core/src/pigrocrm/core/models_registry.py packages/core/tests/test_email_drafts.py \
        packages/core/tests/test_migrations.py
git commit -m "feat(gmail): a durable draft, with our Message-ID minted before any send"
```

---

### Task B2-4: Attachments from documents only, and the 20 MB cap checked before composing

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/attach.py`
- Create: `packages/core/tests/test_gmail_attachments.py`

**Interfaces:**
- Consumes: `DocumentVersion` and `DocumentStorage.get` from slice 2; `OutgoingAttachment` from B2-2; `Settings.gmail_attachment_max_bytes` from B1-2.
- Produces:
  ```python
  def resolve_attachments(session: Session, storage: DocumentStorage,
                          version_ids: Sequence[UUID], *, max_bytes: int
                          ) -> tuple[OutgoingAttachment, ...]: ...
  ```
  Consumed by B2-5 and B2-9.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_attachments.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.gmail.attach import resolve_attachments
from tests.fakes.fake_storage import FakeStorage  # the slice-2 in-memory DocumentStorage

MB = 1024 * 1024


def test_it_resolves_a_document_version_into_bytes_a_name_and_a_type(
    db_session: Session, offerta_version
) -> None:
    storage = FakeStorage({offerta_version.storage_key: b"%PDF-1.7\n"})
    attachments = resolve_attachments(
        db_session, storage, [offerta_version.id], max_bytes=20 * MB
    )
    assert len(attachments) == 1
    assert attachments[0].content == b"%PDF-1.7\n"
    assert attachments[0].filename.endswith(".pdf")
    assert attachments[0].mime == "application/pdf"


def test_the_mime_type_comes_from_the_allowlist_never_from_a_caller(
    db_session: Session, offerta_version
) -> None:
    """ALLOWED_CONTENT_TYPES in documents/schemas.py is the authority. Echoing a
    caller-supplied type is how a script gets mailed as a PDF."""
    from pigrocrm.core.documents.schemas import ALLOWED_CONTENT_TYPES

    storage = FakeStorage({offerta_version.storage_key: b"%PDF"})
    attachments = resolve_attachments(db_session, storage, [offerta_version.id], max_bytes=20 * MB)
    assert attachments[0].mime in ALLOWED_CONTENT_TYPES


def test_twenty_one_megabytes_are_refused_before_anything_is_composed(
    db_session: Session, offerta_version
) -> None:
    """Spec 13, criterion 11. Gmail refuses above 25 MB and its refusal mid-upload is an
    incomprehensible message, so the limit is ours and the check is early."""
    storage = FakeStorage({offerta_version.storage_key: b"x" * (21 * MB)})
    with pytest.raises(ValidationFailed) as caught:
        resolve_attachments(db_session, storage, [offerta_version.id], max_bytes=20 * MB)
    message = str(caught.value)
    # The error says how much it weighs and what the limit is. "Too big" is not an
    # actionable message.
    assert "21" in message and "20" in message
    assert caught.value.details["field"] == "attachment_version_ids"


def test_the_cap_is_on_the_total_not_on_each_file(db_session: Session, two_versions) -> None:
    first, second = two_versions
    storage = FakeStorage(
        {first.storage_key: b"a" * (12 * MB), second.storage_key: b"b" * (12 * MB)}
    )
    with pytest.raises(ValidationFailed):
        resolve_attachments(db_session, storage, [first.id, second.id], max_bytes=20 * MB)


def test_an_unknown_version_id_is_a_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        resolve_attachments(db_session, FakeStorage({}), [uuid4()], max_bytes=20 * MB)


def test_a_version_whose_bytes_are_missing_from_storage_is_a_not_found(
    db_session: Session, offerta_version
) -> None:
    """A dangling storage key must not become an email with an empty attachment: the
    recipient would receive a 0-byte PDF and nobody would know why."""
    with pytest.raises(NotFound):
        resolve_attachments(db_session, FakeStorage({}), [offerta_version.id], max_bytes=20 * MB)


def test_no_arbitrary_upload_path_exists(db_session: Session) -> None:
    """Spec 6.4: attachments come only from document_version_id. A free upload in the
    composer would be a second route for bytes to enter the system, with a second
    authorisation to write."""
    import inspect

    from pigrocrm.core.gmail import attach

    signature = inspect.signature(attach.resolve_attachments)
    assert "version_ids" in signature.parameters
    assert not any(
        name in signature.parameters for name in ("content", "raw", "upload", "file", "bytes")
    )
```

The three fixtures `offerta_version`, `two_versions` and `FakeStorage` come from slice 2's own test suite — reuse them rather than building new ones; `packages/core/tests/test_documents_service.py` shows how a `DocumentVersion` with a `storage_key` is created.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_attachments.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.attach'`.

- [ ] **Step 3: Write the resolver**

`packages/core/src/pigrocrm/core/gmail/attach.py`:

```python
"""Attachments come from `document_version_id` and from nowhere else.

The thing anyone actually wants to attach is the offer's PDF -- slice 2 explicitly
deferred sending the offer to this slice -- and going through the document means going
through the layer that already has the authorisation, the hash and the versioning. A
free-form upload in the composer would be a second route for bytes to enter the system,
with a second authorisation to write and a second place for it to be wrong.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.gmail.rfc822 import OutgoingAttachment
from pigrocrm.core.storage import DocumentStorage

_MB = 1024 * 1024


def resolve_attachments(
    session: Session,
    storage: DocumentStorage,
    version_ids: Sequence[UUID],
    *,
    max_bytes: int,
) -> tuple[OutgoingAttachment, ...]:
    """Reads the bytes, names the files, and refuses an oversized total **before**
    anything is composed.

    Gmail refuses above 25 MB, and its refusal arrives mid-upload as a message nobody
    can act on. So the limit is ours, it is lower, and the error says how much the
    attachments weigh and what the limit is -- "too big" is not actionable.
    """
    resolved: list[OutgoingAttachment] = []
    total = 0
    for version_id in version_ids:
        row = session.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id == version_id)
        ).one_or_none()
        if row is None:
            raise NotFound("document_version", version_id)
        version, document = row

        content = storage.get(version.storage_key)
        if content is None:
            # A dangling storage key must not become an email carrying a 0-byte PDF: the
            # recipient gets a broken file and nobody learns why.
            raise NotFound("document_blob", version.storage_key)

        total += len(content)
        resolved.append(
            OutgoingAttachment(
                filename=f"{document.titolo}-v{version.numero}.pdf",
                # From the document's own recorded type, which came from
                # ALLOWED_CONTENT_TYPES -- never echoed from a request.
                mime=version.content_type,
                content=content,
            )
        )

    if total > max_bytes:
        raise ValidationFailed(
            "email_draft",
            "attachment_version_ids",
            f"gli allegati pesano {total / _MB:.1f} MB, il limite è "
            f"{max_bytes / _MB:.0f} MB",
            expected=f"totale <= {max_bytes / _MB:.0f} MB",
        )
    return tuple(resolved)
```

If slice 2's `DocumentStorage.get` raises `NotFound` itself rather than returning `None`, drop the `is None` branch and let it propagate — check the shipped `storage/__init__.py` Protocol before writing this, and match it exactly.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_attachments.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail/attach.py packages/core/tests/test_gmail_attachments.py
git commit -m "feat(gmail): attachments from documents only, capped before composing"
```

---
### Task B2-5: The one send path, and it is idempotent

**Files:**
- Create: `packages/core/src/pigrocrm/core/gmail/send.py`
- Modify: `packages/core/src/pigrocrm/core/gmail/repository.py` (the claim statement)
- Create: `packages/core/tests/test_gmail_send.py`

**Interfaces:**
- Consumes: `GoogleAccountService.usable` from B1-12; `build_rfc822`/`to_base64url`/`OutgoingAttachment` from B2-2; `EmailDraftService` from B2-3; `resolve_attachments` from B2-4; `GmailTransport.json`; `SCOPE_SEND`.
- Produces:
  ```python
  GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

  # repository.py
  def claim_draft_for_send(self, draft_id: UUID, now: datetime) -> bool: ...

  class EmailSendService:
      def __init__(self, session: Session, *, settings: Settings, transport: GmailTransport,
                   tokens: GoogleTokenClient, storage: DocumentStorage) -> None: ...
      def send(self, draft_id: UUID, actor: Actor) -> EmailDraftRead: ...
      # reconcile / reconcile_all are added by B2-6 on this same class.
  ```
  Consumed by B2-6, B2-9, B2-10, B2-11.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_send.py`:

```python
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.errors import CredentialRevoked, ScopeMissing
from pigrocrm.core.gmail.models import EmailDraft, GmailMessage
from pigrocrm.core.gmail.schemas import SCOPE_READONLY, EmailDraftCreate
from tests.fakes.fake_gmail import FakeGmail
from tests.fakes.gmail_fixtures import (
    actor_for,
    connected_account,
    draft_service,
    send_service,
)


def _draft(session: Session, account, **overrides: object):
    customer = Customer(ragione_sociale="Acme", email="info@acme.it")
    session.add(customer)
    session.flush()
    payload = EmailDraftCreate(
        entity_type="customer",
        entity_id=customer.id,
        to_addresses=["ada@acme.it"],
        subject="Offerta — così",
        body_markdown="Gentile Ada,\n\nè già pronta l’offerta.",
        **overrides,  # type: ignore[arg-type]
    )
    return draft_service(session).create(payload, actor_for(account))


def test_a_successful_send_records_the_message_and_the_timeline_entry(
    db_session: Session,
) -> None:
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail()

    read = send_service(db_session, fake).send(draft.id, actor_for(account))
    db_session.commit()

    assert read.send_state == "inviato"
    assert read.sent_gmail_message_id
    # The outbound row is written *after* Gmail answered, never before.
    outbound = db_session.execute(
        select(GmailMessage).where(GmailMessage.direction == "outbound")
    ).scalars().one()
    assert outbound.gmail_message_id == read.sent_gmail_message_id
    assert outbound.message_id_header == draft.message_id_header
    kinds = db_session.execute(select(Activity.kind)).scalars().all()
    assert "gmail.messaggio_inviato" in kinds


def test_the_message_that_left_carries_our_own_message_id(db_session: Session) -> None:
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail()
    send_service(db_session, fake).send(draft.id, actor_for(account))

    sends = [request for request in fake.requests if request.is_messages_send]
    assert len(sends) == 1
    import base64
    import json

    raw = json.loads(sends[0].body or b"{}")["raw"]
    decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
    assert draft.message_id_header in decoded
    # And no 7bit anywhere in what actually went out.
    assert "7bit" not in decoded


def test_sending_the_same_draft_twice_is_refused(db_session: Session) -> None:
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail()
    service = send_service(db_session, fake)
    service.send(draft.id, actor_for(account))
    db_session.commit()

    with pytest.raises(Conflict) as caught:
        service.send(draft.id, actor_for(account))
    assert "inviato" in caught.value.message
    # One email, one send call. A double click or a proxy retry cannot spend twice.
    assert len([r for r in fake.requests if r.is_messages_send]) == 1


def test_two_concurrent_sends_produce_one_email_one_row_and_one_conflict(
    db_session: Session, db_engine: Engine
) -> None:
    """Spec 13, criterion 10. Real threads on real connections: the claim is a
    conditional UPDATE, and only the database can arbitrate it."""
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail()

    def attempt() -> str:
        with Session(db_engine) as session:
            try:
                send_service(session, fake).send(draft.id, actor_for(account))
                return "sent"
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _: attempt(), range(2)))

    assert outcomes == ["conflict", "sent"]
    assert len([r for r in fake.requests if r.is_messages_send]) == 1
    with Session(db_engine) as check:
        assert check.execute(
            select(func.count()).select_from(GmailMessage).where(GmailMessage.direction == "outbound")
        ).scalar_one() == 1


def test_gmail_refusing_leaves_the_draft_intact_and_editable(db_session: Session) -> None:
    """Spec 6.3 (a), the clean case: nothing left, so the composer reopens with the text
    inside and the error beside it."""
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail(fail_with=[(400, b'{"error":{"status":"INVALID_ARGUMENT"}}', {})])

    with pytest.raises(Conflict):
        send_service(db_session, fake).send(draft.id, actor_for(account))
    db_session.rollback()

    row = db_session.get(EmailDraft, draft.id)
    assert row is not None
    assert row.send_state == "fallito"
    assert row.last_error
    assert row.body_markdown == "Gentile Ada,\n\nè già pronta l’offerta."
    assert db_session.execute(select(func.count()).select_from(GmailMessage)).scalar_one() == 0


def test_a_failed_draft_can_be_retried(db_session: Session) -> None:
    """`fallito` is not terminal: nothing left, so trying again is correct. Only
    `inviato`, `in_invio` and `incerto` are refused."""
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    failing = FakeGmail(fail_with=[(400, b"{}", {})])
    with pytest.raises(Conflict):
        send_service(db_session, failing).send(draft.id, actor_for(account))
    db_session.rollback()

    working = FakeGmail()
    read = send_service(db_session, working).send(draft.id, actor_for(account))
    assert read.send_state == "inviato"


def test_a_revoked_credential_fails_before_composing_and_makes_no_http_call(
    db_session: Session,
) -> None:
    """Spec 13, criterion 5 (d). The gate is called before the attachments are read and
    before the RFC822 is built, so nothing is half-done and nothing is spent."""
    account = connected_account(db_session, status="revoked")
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail()

    with pytest.raises(CredentialRevoked):
        send_service(db_session, fake).send(draft.id, actor_for(account))
    assert fake.requests == []
    db_session.rollback()
    row = db_session.get(EmailDraft, draft.id)
    assert row is not None
    # Not even claimed: a refusal before the gate must not consume the draft.
    assert row.send_state == "bozza"


def test_a_grant_without_gmail_send_refuses_by_naming_the_scope(db_session: Session) -> None:
    account = connected_account(db_session, scopes=("openid", "email", SCOPE_READONLY))
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail()
    with pytest.raises(ScopeMissing) as caught:
        send_service(db_session, fake).send(draft.id, actor_for(account))
    assert "gmail.send" in caught.value.message
    assert fake.requests == []


def test_a_reminder_inside_a_thread_carries_in_reply_to_and_references(
    db_session: Session,
) -> None:
    """Spec 13, criterion 13."""
    import base64
    import json
    from datetime import UTC, datetime

    account = connected_account(db_session)
    original = GmailMessage(
        google_account_id=account.id,
        gmail_message_id="m-original",
        gmail_thread_id="t-1",
        message_id_header="<original.1@crm.example.it>",
        references="<root@acme.it>",
        direction="outbound",
        from_address="io@example.it",
        to_addresses=["ada@acme.it"],
        subject="Fattura 2026/14",
        internal_date=datetime(2026, 8, 1, tzinfo=UTC),
    )
    db_session.add(original)
    db_session.flush()
    draft = _draft(db_session, account, in_reply_to_message_id=original.id)
    db_session.commit()

    fake = FakeGmail()
    send_service(db_session, fake).send(draft.id, actor_for(account))
    raw = json.loads(
        [r for r in fake.requests if r.is_messages_send][0].body or b"{}"
    )["raw"]
    decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
    assert "In-Reply-To: <original.1@crm.example.it>" in decoded
    assert "<root@acme.it>" in decoded
    assert "<original.1@crm.example.it>" in decoded.split("References:")[1]
```

Add `draft_service` and `send_service` to `packages/core/tests/fakes/gmail_fixtures.py`, built exactly like `sync_service` and passing `FakeStorage({})` for the document storage.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_send.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.send'`.

- [ ] **Step 3: Add the claim statement**

Append to `gmail/repository.py`:

```python
    def claim_draft_for_send(self, draft_id: UUID, now: datetime) -> bool:
        """Moves a draft from `bozza` to `in_invio` in one statement, returning whether
        this caller is the one that moved it.

        A conditional UPDATE and not a SELECT-then-set: two concurrent requests both
        pass a read, and only the database can arbitrate which of them owns the send.
        `send_state` is the guard in the WHERE clause, so the second caller updates zero
        rows and learns it lost.
        """
        result = self.session.execute(
            update(EmailDraft)
            .where(EmailDraft.id == draft_id, EmailDraft.send_state == "bozza")
            .values(send_state="in_invio", send_attempted_at=now, last_error=None)
        )
        return bool(result.rowcount)
```

Add `update` to the SQLAlchemy imports.

- [ ] **Step 4: Write the send service**

`packages/core/src/pigrocrm/core/gmail/send.py`:

```python
"""The only place in this slice that can call `users.messages.send`.

One send path, in the whole slice. Payment reminders do not get their own -- spec 8.3 is
explicit that `POST /api/payment-reminders` creates a row and a draft and does not send,
so that the reminder logic can rely on this idempotence rather than reimplementing it.

**On transaction boundaries.** Every other service method in this codebase is one
transaction. This one is deliberately three, and the reason is the design rather than an
oversight: there is a non-transactional side effect -- an email leaving the building --
in the middle.

1. The claim (`bozza` -> `in_invio`) is committed **before** the HTTP call, because a
   concurrent request has to be able to see it. An uncommitted claim is invisible, and
   two requests would both send.
2. The HTTP call happens outside any transaction, holding no locks. A synchronous send
   holding a row lock for the length of a network round trip is how a database gets
   wedged by a slow third party.
3. The outcome is committed after.

The cost is that the process can die between 2 and 3. That is precisely the `incerto`
state, and B2-6 is how it gets resolved -- by asking Gmail, not by guessing. Acme had
the same window and no name for it, which is why it answers
`404 'Fattura non trovata per registrare l'invio'` while the email is already delivered,
and why the operator then presses the button again.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, decode_google_token_key, require_gmail_configured
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.gmail.account import GoogleAccountService
from pigrocrm.core.gmail.attach import resolve_attachments
from pigrocrm.core.gmail.crypto import unseal
from pigrocrm.core.gmail.errors import GoogleCallFailed
from pigrocrm.core.gmail.models import EmailDraft, GmailMessage, GoogleAccount
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.rfc822 import build_rfc822, to_base64url
from pigrocrm.core.gmail.schemas import SCOPE_SEND, EmailDraftRead
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import NETWORK_ERROR_STATUS, GmailTransport
from pigrocrm.core.storage import DocumentStorage

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

# A definite refusal: Gmail looked at the message and said no, so nothing left and the
# draft is safe to retry. Anything else -- a timeout, a lost connection, a 5xx after
# every retry -- is "we do not know", and guessing either way is what produces a double
# send or a lost email.
_DEFINITE_REFUSAL = frozenset({400, 403, 404, 413, 422})


class EmailSendService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        transport: GmailTransport,
        tokens: GoogleTokenClient,
        storage: DocumentStorage,
    ) -> None:
        self.session = session
        self.settings = settings
        self.transport = transport
        self.tokens = tokens
        self.storage = storage
        self.repo = GmailRepository(session)
        self.activities = ActivityService(session)
        self.accounts = GoogleAccountService(session, settings=settings)

    def send(self, draft_id: UUID, actor: Actor) -> EmailDraftRead:
        require_gmail_configured(self.settings)
        actor.require_write("inviare un'email")

        # (1) The gate, first. Before the attachments are read, before the RFC822 is
        # built, before the draft is claimed: an operator pressing Send on a revoked
        # account learns it at the press, and nothing is half-done in between.
        account = self.accounts.usable(actor, scope=SCOPE_SEND, feature="l'invio")

        draft = self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise NotFound("email_draft", draft_id)
        if draft.send_state != "bozza":
            raise Conflict(
                "email_draft",
                self._already(draft.send_state),
                send_state=draft.send_state,
            )

        # (2) Claim it, and commit the claim so a concurrent request can see it.
        now = datetime.now(UTC)
        if not self.repo.claim_draft_for_send(draft_id, now):
            self.session.rollback()
            current = self.session.get(EmailDraft, draft_id)
            state = current.send_state if current else "sconosciuto"
            raise Conflict("email_draft", self._already(state), send_state=state)
        self.session.commit()

        try:
            raw = self._compose(account, draft)
        except Exception:
            # Composition failed -- an oversized attachment, a missing blob, a hostile
            # header. Nothing left, so the draft goes back to being editable rather than
            # being stranded in `in_invio` forever.
            self._finish(draft_id, "fallito", error="Impossibile comporre il messaggio.")
            raise

        try:
            answer = self.transport.json(
                "POST", GMAIL_SEND_URL, token=self._token(account), body={"raw": raw},
                what="invio del messaggio",
            )
        except GoogleCallFailed as failed:
            if failed.failure.status in _DEFINITE_REFUSAL:
                # (3a) Gmail refused. Clean: nothing left.
                self._finish(
                    draft_id,
                    "fallito",
                    error=f"Gmail ha rifiutato il messaggio (codice {failed.failure.status}).",
                )
                raise Conflict(
                    "email_draft",
                    f"Gmail ha rifiutato il messaggio (codice {failed.failure.status}): "
                    "il testo è rimasto nella bozza",
                    status=failed.failure.status,
                ) from failed
            # (3b) We do not know. The message MAY be in the user's Sent folder.
            # Neither assumption is made -- see B2-6.
            self._finish(
                draft_id,
                "incerto",
                error=(
                    "Non sappiamo se il messaggio sia partito: Gmail non ha risposto. "
                    "Usa «verifica» per accertarlo."
                ),
            )
            raise Conflict(
                "email_draft",
                "esito dell'invio da verificare: Gmail non ha risposto",
                send_state="incerto",
            ) from failed

        return self._record_sent(account, draft_id, answer, actor)

    # ---- internals ---------------------------------------------------------------

    @staticmethod
    def _already(state: str) -> str:
        return {
            "inviato": "questa email è già stata inviata",
            "in_invio": "questa email è già in invio",
            "incerto": "l'esito di questa email è da verificare: usa «verifica» prima di rinviare",
        }.get(state, f"questa email non è inviabile nello stato {state}")

    def _token(self, account: GoogleAccount) -> str:
        return self.tokens.access_token(
            account_id=account.id,
            email_address=account.email_address,
            refresh_token=unseal(
                account.refresh_token_ciphertext,
                account.refresh_token_nonce,
                decode_google_token_key(self.settings),
            ),
        )

    def _compose(self, account: GoogleAccount, draft: EmailDraft) -> str:
        attachments = resolve_attachments(
            self.session,
            self.storage,
            [UUID(str(value)) for value in draft.attachment_version_ids],
            max_bytes=self.settings.gmail_attachment_max_bytes,
        )
        in_reply_to = ""
        references = ""
        if draft.in_reply_to_message_id is not None:
            parent = self.session.get(GmailMessage, draft.in_reply_to_message_id)
            if parent is not None:
                in_reply_to = parent.message_id_header
                # Append, never replace: References is the whole chain, and a reminder
                # that drops it arrives detached from the invoice it is about.
                references = " ".join(
                    part for part in (parent.references, parent.message_id_header) if part
                )
        return to_base64url(
            build_rfc822(
                from_address=account.email_address,
                from_name=self._signature_name(),
                to=list(draft.to_addresses),
                cc=list(draft.cc_addresses),
                subject=draft.subject,
                body_text=draft.body_markdown,
                message_id=draft.message_id_header,
                in_reply_to=in_reply_to,
                references=references,
                attachments=attachments,
            )
        )

    def _signature_name(self) -> str:
        """The display name on the From header, from `emitter_profile.ragione_sociale`.
        Never hardcoded: slice 2's whole point about `header.typ` was that a CRM for
        Italian freelancers cannot carry one freelancer's name in its source."""
        profile = self.repo.emitter_profile()
        return profile.ragione_sociale if profile else ""

    def _finish(self, draft_id: UUID, state: str, *, error: str | None) -> None:
        """Its own transaction, so the outcome survives the exception that follows."""
        self.session.rollback()
        row = self.session.get(EmailDraft, draft_id)
        if row is None:
            return
        row.send_state = state
        row.last_error = error
        self.session.commit()

    def _record_sent(
        self, account: GoogleAccount, draft_id: UUID, answer: dict[str, object], actor: Actor
    ) -> EmailDraftRead:
        gmail_id = str(answer.get("id") or "")
        thread_id = str(answer.get("threadId") or "")
        row = self.session.get(EmailDraft, draft_id)
        if row is None:
            raise NotFound("email_draft", draft_id)
        row.send_state = "inviato"
        row.sent_gmail_message_id = gmail_id
        row.last_error = None

        # The outbound row is written only now, after Gmail answered. Never before.
        message = GmailMessage(
            google_account_id=account.id,
            gmail_message_id=gmail_id,
            gmail_thread_id=thread_id,
            message_id_header=row.message_id_header,
            direction="outbound",
            from_address=account.email_address,
            to_addresses=list(row.to_addresses),
            cc_addresses=list(row.cc_addresses),
            subject=row.subject,
            snippet=row.body_markdown[:500],
            internal_date=datetime.now(UTC),
            body_text=row.body_markdown if account.gmail_store_bodies else "",
        )
        self.repo.add_message(message)
        for ref in [(row.entity_type, row.entity_id)]:
            self.repo.add_link(message.id, EntityRef(ref[0], ref[1]))
        # Same transaction as the row above, per spec 6.2.
        self.activities.record(
            row.entity_type,
            row.entity_id,
            "gmail.messaggio_inviato",
            actor,
            {
                "subject": row.subject,
                "to_addresses": list(row.to_addresses),
                "gmail_message_id": gmail_id,
            },
        )
        self.session.commit()
        return EmailDraftRead.model_validate(row)
```

Add `from uuid import UUID` and `from pigrocrm.core.gmail.roster import EntityRef`. Add `GmailRepository.emitter_profile() -> EmitterProfile | None` returning the single row.

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_send.py -v`
Expected: PASS (9 tests). The one to read carefully is `test_two_concurrent_sends_produce_one_email_one_row_and_one_conflict`: if it reports `["sent", "sent"]`, the claim is not a conditional UPDATE, or it is not committed before the HTTP call.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/tests/test_gmail_send.py \
        packages/core/tests/fakes/gmail_fixtures.py
git commit -m "feat(gmail): one send path, claimed by the database so it cannot run twice"
```

---

### Task B2-6: An unknown outcome reconciles exactly, so a double send cannot happen

**The third hard part.** Acme sends at `vite.config.js:5334`, then looks the invoice up on disk and answers `404 'Fattura non trovata per registrare l'invio.'` **while the email is already delivered**. The operator reads an error and presses the button again: two emails. This task is the answer, and the test is the proof.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/gmail/send.py` (append `reconcile`, `reconcile_all`)
- Modify: `packages/core/src/pigrocrm/core/gmail/sync.py` (reconcile at the start of every cycle)
- Create: `packages/core/tests/test_gmail_reconcile.py`

**Interfaces:**
- Consumes: `rfc822msgid_query`/`messages_list_url` from B1-7; `Settings.gmail_send_grace_minutes` and `gmail_reconcile_by_message_id` from B1-2/B2-1.
- Produces:
  ```python
  def reconcile(self, draft_id: UUID, actor: Actor) -> EmailDraftRead: ...
  def reconcile_all(self, actor: Actor) -> int: ...   # how many drafts it resolved
  ```
  `reconcile_all` is consumed by `GmailSyncService._run_cycle`; `reconcile` by B2-10's `/reconcile` endpoint and B2-11's «verifica» button.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_gmail_reconcile.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.models import EmailDraft, GmailMessage
from pigrocrm.core.gmail.schemas import EmailDraftCreate
from tests.fakes.fake_gmail import FakeGmail
from tests.fakes.gmail_fixtures import (
    actor_for,
    connected_account,
    draft_service,
    send_service,
    sync_service,
)


def _draft(session: Session, account):
    customer = Customer(ragione_sociale="Acme", email="info@acme.it")
    session.add(customer)
    session.flush()
    return draft_service(session).create(
        EmailDraftCreate(
            entity_type="customer",
            entity_id=customer.id,
            to_addresses=["ada@acme.it"],
            subject="Fattura 2026/14",
            body_markdown="Gentile Ada, in allegato la fattura.",
        ),
        actor_for(account),
    )


def _lost_answer(deliver: bool) -> FakeGmail:
    """Gmail's answer never arrives. `deliver=True` is the case that matters: the
    message really did leave, and only the response was lost. That is Acme's live
    defect, and it is the case a guess gets wrong."""
    return FakeGmail(timeout_on_send=True, deliver_on_timeout=deliver)


def test_a_lost_answer_leaves_the_draft_uncertain_and_never_says_sent(
    db_session: Session,
) -> None:
    """Spec 13, criterion 9, first half. The interface must not write "sent"."""
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()

    with pytest.raises(Conflict, match="da verificare"):
        send_service(db_session, _lost_answer(True)).send(draft.id, actor_for(account))
    db_session.rollback()

    row = db_session.get(EmailDraft, draft.id)
    assert row is not None
    assert row.send_state == "incerto"
    assert "sappiamo" in (row.last_error or "")
    # And no outbound row was invented: we do not know that it arrived.
    assert db_session.execute(select(func.count()).select_from(GmailMessage)).scalar_one() == 0


def test_reconciliation_finds_it_by_our_own_message_id_and_adopts_gmails(
    db_session: Session,
) -> None:
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = _lost_answer(True)
    service = send_service(db_session, fake)
    with pytest.raises(Conflict):
        service.send(draft.id, actor_for(account))
    db_session.rollback()

    read = service.reconcile(draft.id, actor_for(account))
    db_session.commit()

    assert read.send_state == "inviato"
    assert read.sent_gmail_message_id
    outbound = db_session.execute(
        select(GmailMessage).where(GmailMessage.direction == "outbound")
    ).scalars().one()
    assert outbound.message_id_header == draft.message_id_header
    # The lookup was by rfc822msgid, i.e. exact -- not a comparison of subject and time.
    lookups = [r for r in fake.requests if r.is_messages_list and "rfc822msgid" in (r.q or "")]
    assert len(lookups) == 1
    assert draft.message_id_header.strip("<>") in (lookups[0].q or "")


def test_a_double_send_cannot_happen(db_session: Session) -> None:
    """The whole point, in one test.

    The sequence is the one that produces two emails in Acme: the send's outcome is
    unknown, the operator retries, and nothing stops them. Here the retry is refused,
    the reconciliation resolves the truth by asking Gmail, and exactly one message was
    ever sent.
    """
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = _lost_answer(True)
    service = send_service(db_session, fake)

    with pytest.raises(Conflict):
        service.send(draft.id, actor_for(account))
    db_session.rollback()

    # The operator presses Send again, exactly as they would after reading an error.
    with pytest.raises(Conflict) as caught:
        service.send(draft.id, actor_for(account))
    assert "verifica" in caught.value.message
    db_session.rollback()

    service.reconcile(draft.id, actor_for(account))
    db_session.commit()

    # One send call over the whole scenario. Not two, and not zero.
    assert len([r for r in fake.requests if r.is_messages_send]) == 1
    assert db_session.execute(
        select(func.count()).select_from(GmailMessage).where(GmailMessage.direction == "outbound")
    ).scalar_one() == 1
    row = db_session.get(EmailDraft, draft.id)
    assert row is not None and row.send_state == "inviato"


def test_a_message_genuinely_absent_after_the_grace_window_becomes_failed(
    db_session: Session,
) -> None:
    """Spec 13, criterion 9, second half: the draft stays intact."""
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = _lost_answer(False)  # it really did not leave
    service = send_service(db_session, fake)
    with pytest.raises(Conflict):
        service.send(draft.id, actor_for(account))
    db_session.rollback()

    row = db_session.get(EmailDraft, draft.id)
    assert row is not None
    row.send_attempted_at = datetime.now(UTC) - timedelta(minutes=16)
    db_session.commit()

    read = service.reconcile(draft.id, actor_for(account))
    db_session.commit()
    assert read.send_state == "fallito"
    assert read.body_markdown == "Gentile Ada, in allegato la fattura."
    assert db_session.execute(select(func.count()).select_from(GmailMessage)).scalar_one() == 0


def test_inside_the_grace_window_it_stays_uncertain_rather_than_guessing(
    db_session: Session,
) -> None:
    """Gmail's index is not instantaneous. Declaring failure at second zero would turn
    a slow index into a resend -- which is the very outcome this design exists to
    prevent."""
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = _lost_answer(False)
    service = send_service(db_session, fake)
    with pytest.raises(Conflict):
        service.send(draft.id, actor_for(account))
    db_session.rollback()

    read = service.reconcile(draft.id, actor_for(account))
    assert read.send_state == "incerto"


def test_reconciliation_is_idempotent(db_session: Session) -> None:
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = _lost_answer(True)
    service = send_service(db_session, fake)
    with pytest.raises(Conflict):
        service.send(draft.id, actor_for(account))
    db_session.rollback()
    service.reconcile(draft.id, actor_for(account))
    db_session.commit()
    service.reconcile(draft.id, actor_for(account))
    db_session.commit()
    assert db_session.execute(
        select(func.count()).select_from(GmailMessage).where(GmailMessage.direction == "outbound")
    ).scalar_one() == 1


def test_reconciling_a_draft_that_was_never_sent_does_nothing(db_session: Session) -> None:
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = FakeGmail()
    read = send_service(db_session, fake).reconcile(draft.id, actor_for(account))
    assert read.send_state == "bozza"
    assert fake.requests == []


def test_every_sync_reconciles_first(db_session: Session) -> None:
    """Spec 6.3 point 3: reconciliation runs at the start of every sync and on request.
    A state that only resolves when a human remembers to press a button is a state that
    stays wrong."""
    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    fake = _lost_answer(True)
    with pytest.raises(Conflict):
        send_service(db_session, fake).send(draft.id, actor_for(account))
    db_session.rollback()

    sync_service(db_session, fake).sync(actor_for(account))
    db_session.commit()

    row = db_session.get(EmailDraft, draft.id)
    assert row is not None
    assert row.send_state == "inviato"


def test_an_uncertain_send_writes_its_own_timeline_entry(db_session: Session) -> None:
    from pigrocrm.core.activities.models import Activity

    account = connected_account(db_session)
    draft = _draft(db_session, account)
    db_session.commit()
    with pytest.raises(Conflict):
        send_service(db_session, _lost_answer(True)).send(draft.id, actor_for(account))
    db_session.rollback()
    kinds = db_session.execute(select(Activity.kind)).scalars().all()
    assert "gmail.invio_incerto" in kinds
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_gmail_reconcile.py -v`
Expected: FAIL — `EmailSendService has no attribute 'reconcile'`.

- [ ] **Step 3: Append the reconciliation**

In `gmail/send.py`, record the uncertain state in the timeline as well (add to the `incerto` branch of `send`, right after `_finish`):

```python
            self.activities.record(
                draft.entity_type,
                draft.entity_id,
                "gmail.invio_incerto",
                actor,
                {"subject": draft.subject, "message_id_header": draft.message_id_header},
            )
            self.session.commit()
```

and append:

```python
    def reconcile(self, draft_id: UUID, actor: Actor) -> EmailDraftRead:
        """Resolves an `incerto` draft by asking Gmail, not by guessing.

        The lookup is `q=rfc822msgid:<our own Message-ID>` -- exact, because we chose
        that id before calling send (spec 6.2). Found means it left: adopt Gmail's id and
        mark it sent. Not found, after a grace window, means it did not: mark it failed
        with the draft intact.

        Why a grace window at all: Gmail's search index is not instantaneous. Declaring
        failure at second zero would turn a slow index into a resend, which is the
        outcome this whole design exists to prevent.
        """
        draft = self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise NotFound("email_draft", draft_id)
        if draft.send_state != "incerto":
            # Nothing to resolve, and no request made: a draft that was never sent has
            # no outcome to look up.
            return EmailDraftRead.model_validate(draft)

        account = self.accounts.usable(actor, scope=SCOPE_SEND, feature="la verifica dell'invio")
        if not self.settings.gmail_reconcile_by_message_id:
            # The recorded fallback of spec 6.3, used only if the B2-1 verification came
            # back NO. Declaredly inferior: it is an approximate match and cannot tell
            # two near-identical sends apart.
            found = self._find_by_approximation(account, draft)
        else:
            payload = self.transport.json(
                "GET",
                messages_list_url(rfc822msgid_query(draft.message_id_header)),
                token=self._token(account),
                what="verifica dell'invio",
            )
            entries = [e for e in (payload.get("messages") or []) if isinstance(e, dict)]
            found = entries[0] if entries else None

        if found is not None:
            return self._record_sent(
                account,
                draft_id,
                {"id": found.get("id"), "threadId": found.get("threadId")},
                actor,
            )

        attempted = draft.send_attempted_at or datetime.now(UTC)
        grace = timedelta(minutes=self.settings.gmail_send_grace_minutes)
        if datetime.now(UTC) - attempted < grace:
            # Still inside the window: stay uncertain. "We do not know yet" is a true
            # answer and a resend is not.
            return EmailDraftRead.model_validate(draft)

        draft.send_state = "fallito"
        draft.last_error = (
            "Il messaggio non risulta inviato: la bozza è intatta e puoi riprovare."
        )
        self.session.commit()
        return EmailDraftRead.model_validate(draft)

    def reconcile_all(self, actor: Actor) -> int:
        """Every `incerto` draft. Runs at the start of each sync, so an unresolved
        outcome does not wait for someone to remember it."""
        resolved = 0
        for draft_id in self.repo.uncertain_draft_ids():
            before = self.session.get(EmailDraft, draft_id)
            state_before = before.send_state if before else ""
            self.reconcile(draft_id, actor)
            after = self.session.get(EmailDraft, draft_id)
            if after is not None and after.send_state != state_before:
                resolved += 1
        return resolved
```

Add `timedelta` to the datetime import, and `messages_list_url`/`rfc822msgid_query` to the query import. Add to the repository:

```python
    def uncertain_draft_ids(self) -> list[UUID]:
        return list(
            self.session.execute(
                select(EmailDraft.id)
                .where(EmailDraft.send_state == "incerto")
                .order_by(EmailDraft.send_attempted_at)
            ).scalars().all()
        )
```

`_find_by_approximation(self, account, draft) -> dict[str, object] | None` searches the already-synchronised `gmail_messages` for an outbound row to the same recipient with the same subject inside the grace window. It reads the CRM, not Gmail, because the per-address sweep the sync already performs is what puts the message there — that is what spec §6.3 means by "inside the sweep by address that §4 already does".

- [ ] **Step 4: Reconcile at the start of every sync**

In `gmail/sync.py`'s `_run_cycle`, immediately after the states are pruned:

```python
        # Before anything else: resolve any send whose outcome we do not know. Doing it
        # first means the outbound rows exist before this cycle's own listing might
        # otherwise re-discover the same message and store it twice.
        report.reconciled = self._send_service().reconcile_all(actor)
```

`_send_service()` builds an `EmailSendService` on the same session, transport and tokens. `SyncReport` gains `reconciled: int = 0`.

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_gmail_reconcile.py packages/core/tests/test_gmail_send.py -v`
Expected: PASS (9 + 9 tests). `test_a_double_send_cannot_happen` is the one this task exists for; if the send count is 2, the retry was not refused.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/gmail packages/core/tests/test_gmail_reconcile.py
git commit -m "feat(gmail): an unknown outcome is resolved by lookup, never by guessing"
```

---
### Task B2-7: The signature as data, and Acme's reminder copy as a template

Acme's reminder text is the one thing here worth carrying intact: it went to real clients for years, and it has the right running order — invoice number, date, due date, amount, IBAN. The signature is the opposite: `Ivan Sala / CTO / mobile / web`, duplicated **verbatim** in both builders.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/emitter/models.py` (append `firma_email`)
- Modify: `packages/core/src/pigrocrm/core/emitter/schemas.py`
- Modify: `packages/core/src/pigrocrm/core/templates/schemas.py` (`TemplateTipo`)
- Create: `packages/core/migrations/versions/0009_emitter_firma_email.py`
- Modify: `packages/core/tests/test_migrations.py:139,161`
- Create: `packages/core/tests/test_sollecito_template.py`
- Modify: `packages/core/tests/test_emitter.py`

**Interfaces:**
- Consumes: `render_template(source, values, declared)` from `templates/renderer.py`.
- Produces:
  ```python
  # emitter: a nullable Text column
  firma_email: Mapped[str | None]
  FIRMA_EMAIL_MAX_LENGTH = 2_000

  # templates/schemas.py
  TemplateTipo = Literal["offerta", "contratto", "verbale", "documento", "email", "sollecito"]

  # a seeded template
  SOLLECITO_TEMPLATE_NOME = "Sollecito di pagamento"
  SOLLECITO_TEMPLATE_SOURCE: str
  SOLLECITO_DECLARED_VARIABLES: tuple[DeclaredVariable, ...]
  ```
  Consumed by B2-9 and B2-12.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_sollecito_template.py`:

```python
import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.gmail.solleciti_template import (
    SOLLECITO_DECLARED_VARIABLES,
    SOLLECITO_TEMPLATE_SOURCE,
)
from pigrocrm.core.templates.renderer import render_template

VALUES = {
    "cliente": "Acme S.r.l.",
    "numero_fattura": "2026/14",
    "data_fattura": "01/07/2026",
    "scadenza": "31/07/2026",
    "importo": "1.200,00 €",
    "iban": "IT60X0542811101000000123456",
    "livello": 1,
    "emittente": {
        "ragione_sociale": "Studio Rossi",
        "telefono": "+39 333 1234567",
        "sito_web": "https://studiorossi.it",
    },
    "firma_email": "Mario Rossi\nConsulente",
}


def test_the_carried_copy_keeps_Mitra_running_order() -> None:
    """Portato: this text went to real clients for years, and its order is the useful
    part -- invoice number, date, due date, amount, IBAN."""
    rendered = render_template(SOLLECITO_TEMPLATE_SOURCE, VALUES, SOLLECITO_DECLARED_VARIABLES)
    assert "Gentile Acme S.r.l." in rendered
    for line in [
        "Fattura: 2026/14",
        "Data fattura: 01/07/2026",
        "Scadenza: 31/07/2026",
        "Importo: 1.200,00 €",
        "IBAN: IT60X0542811101000000123456",
    ]:
        assert line in rendered
    assert rendered.index("Fattura: ") < rendered.index("Data fattura: ")
    assert rendered.index("Scadenza: ") < rendered.index("Importo: ")
    assert rendered.index("Importo: ") < rendered.index("IBAN: ")


def test_the_courtesy_clauses_that_earned_their_place_are_still_there() -> None:
    rendered = render_template(SOLLECITO_TEMPLATE_SOURCE, VALUES, SOLLECITO_DECLARED_VARIABLES)
    assert "Qualora avesse già provveduto al pagamento, La preghiamo di ignorare questo messaggio." in rendered
    assert "Sistema di Interscambio (SdI)" in rendered


def test_no_freelancers_name_appears_in_the_source() -> None:
    """Rifatta la sostanza: a CRM for Italian freelancers cannot carry one freelancer's
    name in its source -- and Acme carried it twice, verbatim, in two builders."""
    for forbidden in ["Ivan Sala", "CTO", "+39 333 1234567", "humancraft"]:
        assert forbidden.lower() not in SOLLECITO_TEMPLATE_SOURCE.lower()


def test_the_signature_comes_from_the_emitter_profile() -> None:
    rendered = render_template(SOLLECITO_TEMPLATE_SOURCE, VALUES, SOLLECITO_DECLARED_VARIABLES)
    assert "Mario Rossi" in rendered
    assert "Studio Rossi" in rendered
    # The phone and the website are read from emitter_profile rather than retyped into
    # firma_email, so the number cannot diverge between two places.
    assert "+39 333 1234567" in rendered
    assert "https://studiorossi.it" in rendered


def test_the_reminder_level_is_a_variable_and_not_three_templates() -> None:
    """Spec 7.3: the tone of the sequence is a template variable. Three templates that
    resemble each other diverge -- the same decision slice 2 made about the offer."""
    first = render_template(SOLLECITO_TEMPLATE_SOURCE, VALUES, SOLLECITO_DECLARED_VARIABLES)
    third = render_template(
        SOLLECITO_TEMPLATE_SOURCE, {**VALUES, "livello": 3}, SOLLECITO_DECLARED_VARIABLES
    )
    assert first != third
    assert "sollecito" in first.lower()
    # By the third, the tone is firmer and says so, without inventing a legal threat.
    assert "terzo" in third.lower() or "ulteriore" in third.lower()


def test_a_missing_required_variable_names_the_template_line() -> None:
    with pytest.raises(ValidationFailed):
        render_template(
            SOLLECITO_TEMPLATE_SOURCE,
            {key: value for key, value in VALUES.items() if key != "iban"},
            SOLLECITO_DECLARED_VARIABLES,
        )
```

Plus, appended to `packages/core/tests/test_emitter.py`:

```python
def test_firma_email_holds_a_text_block_and_firma_key_still_holds_an_image(
    db_session: Session,
) -> None:
    """Spec 10: the shipped `firma_key` is the storage key of a signature *image*, and
    an email does not attach one -- it wants a text block. The two coexist; neither is
    overloaded."""
    service = EmitterService(db_session)
    read = service.upsert(
        EmitterProfileUpsert(
            ragione_sociale="Studio Rossi",
            telefono="+39 333 1234567",
            sito_web="https://studiorossi.it",
            firma_key="firme/rossi.png",
            firma_email="Mario Rossi\nConsulente",
        ),
        Actor.system(),
    )
    assert read.firma_email == "Mario Rossi\nConsulente"
    assert read.firma_key == "firme/rossi.png"


def test_firma_email_is_bounded_and_rejects_a_nul_byte() -> None:
    with pytest.raises(Exception):
        EmitterProfileUpsert(ragione_sociale="X", firma_email="a" * 2_001)
    with pytest.raises(Exception):
        EmitterProfileUpsert(ragione_sociale="X", firma_email="Mario\x00Rossi")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_sollecito_template.py -v`
Expected: FAIL — `No module named 'pigrocrm.core.gmail.solleciti_template'`.

- [ ] **Step 3: Add `firma_email`**

`emitter/models.py`, after `firma_key`:

```python
    # A text block -- name and role of the person signing. NOT the same thing as
    # `firma_key`, which is the storage key of a signature *image* used on the PDF: an
    # email does not attach an image of a signature, it wants text. The phone number,
    # the website and the company name are deliberately NOT repeated here; a template
    # reads them from their own columns, so the number cannot diverge between two
    # places. Acme hardcoded all of it, twice, verbatim, in two builders.
    firma_email: Mapped[str | None] = mapped_column(Text, default=None)
```

Add `Text` to that module's imports. In `emitter/schemas.py`, add `FIRMA_EMAIL_MAX_LENGTH = 2_000`, `firma_email: SafeStr | None = Field(default=None, max_length=FIRMA_EMAIL_MAX_LENGTH)` to `EmitterProfileUpsert`, and `firma_email: str | None` to `EmitterProfileRead`.

`Text` has no column width, so strictly no `max_length` is required by the `String(n)` rule — it is bounded anyway, at 2,000, because an unbounded text field on a signature block is an unbounded text field, and a signature has no more use for 100,000 characters than a template variable name does.

- [ ] **Step 4: Widen `TemplateTipo`**

In `templates/schemas.py`, replace the `DocumentTipo` import and its use on `TemplateCreate`/`TemplateUpdate`/`TemplateRead` with:

```python
# Templates cover more than documents: this slice adds an `email` body and a
# `sollecito`. `DocumentTipo` is left alone because no `documents` row is ever an
# email, and appending these there would make them legal document types. The column is
# already String(20) with no constraint, so there is no migration.
TemplateTipo = Literal["offerta", "contratto", "verbale", "documento", "email", "sollecito"]
```

Anywhere a template's `tipo` is compared against a document's, convert explicitly rather than relying on the two literals having overlapped.

- [ ] **Step 5: Write the template**

`packages/core/src/pigrocrm/core/gmail/solleciti_template.py`:

```python
"""The reminder text, carried from Acme and de-personalised.

`buildReminderInvoiceEmailBody` (`.reference-acme/website/src/App.jsx:2329-2372`) is
text that went to real clients for years, with the right running order: invoice number,
date, due date, amount, IBAN. That is carried. What is not carried is the signature --
`Ivan Sala / CTO / mobile +39 333 1234567 / web https://www.humancraft.tech`,
duplicated verbatim in both builders -- nor the `NOME_CLIENTE` placeholder syntax, which
slice 2 already replaced with `{{}}` for the offer.

The reminder level is a **variable**, not three templates. Three templates that resemble
each other diverge; this is the same decision slice 2 made when it refused to duplicate
the offer template.
"""

from pigrocrm.core.templates.renderer import DeclaredVariable

SOLLECITO_TEMPLATE_NOME = "Sollecito di pagamento"

SOLLECITO_TEMPLATE_SOURCE = """Gentile {{cliente}},

{{#if primo}}con la presente Le notifichiamo un sollecito di pagamento relativo alla fattura indicata di seguito.{{/if}}{{#if secondo}}torniamo a scriverLe in merito alla fattura indicata di seguito, che risulta ancora non saldata.{{/if}}{{#if terzo}}con questo terzo e ulteriore sollecito Le segnaliamo che la fattura indicata di seguito risulta ancora non saldata, nonostante i precedenti solleciti.{{/if}}

Fattura: {{numero_fattura}}
Data fattura: {{data_fattura}}
Scadenza: {{scadenza}}
Importo: {{importo}}
IBAN: {{iban}}

Qualora avesse già provveduto al pagamento, La preghiamo di ignorare questo messaggio.

In allegato trova copia di cortesia della fattura. L'originale è stato trasmesso digitalmente tramite il Sistema di Interscambio (SdI) secondo le modalità previste.

Restiamo a disposizione per qualsiasi chiarimento e cogliamo l'occasione per porgere cordiali saluti.

--
{{firma_email}}
{{emittente.ragione_sociale}}
{{#if emittente.telefono}}tel. {{emittente.telefono}}{{/if}}
{{#if emittente.sito_web}}{{emittente.sito_web}}{{/if}}
"""

SOLLECITO_DECLARED_VARIABLES: tuple[DeclaredVariable, ...] = (
    DeclaredVariable(nome="cliente", etichetta="Cliente", tipo="text", obbligatoria=True),
    DeclaredVariable(nome="numero_fattura", etichetta="Numero fattura", tipo="text", obbligatoria=True),
    DeclaredVariable(nome="data_fattura", etichetta="Data fattura", tipo="text", obbligatoria=True),
    DeclaredVariable(nome="scadenza", etichetta="Scadenza", tipo="text", obbligatoria=True),
    DeclaredVariable(nome="importo", etichetta="Importo", tipo="text", obbligatoria=True),
    DeclaredVariable(nome="iban", etichetta="IBAN", tipo="text", obbligatoria=True),
    # The three `#if` flags are derived from `livello` by the caller, because the
    # template engine has no comparison operator -- and giving it one for this is a
    # feature nobody asked for.
    DeclaredVariable(nome="primo", etichetta="Primo sollecito", tipo="checkbox", obbligatoria=False),
    DeclaredVariable(nome="secondo", etichetta="Secondo sollecito", tipo="checkbox", obbligatoria=False),
    DeclaredVariable(nome="terzo", etichetta="Terzo sollecito", tipo="checkbox", obbligatoria=False),
    DeclaredVariable(nome="firma_email", etichetta="Firma", tipo="text", obbligatoria=False),
)


def level_flags(livello: int) -> dict[str, bool]:
    """`livello` -> the three flags the template branches on. Levels above three reuse
    the third wording rather than escalating further: `max_reminders` defaults to 3, and
    inventing a fourth register would be inventing a legal threat."""
    return {
        "primo": livello <= 1,
        "secondo": livello == 2,
        "terzo": livello >= 3,
    }
```

Match `DeclaredVariable`'s actual field names and `tipo` vocabulary to `templates/renderer.py` and `fields/types.py` before writing this — read them; the names above follow slice 2's Italian convention (`nome`, `etichetta`, `tipo`, `obbligatoria`) but the `tipo` values must come from `FieldType`.

The renderer treats an undeclared-optional variable as `None`, and `None` is falsy, so `{{#if secondo}}` renders nothing when `level_flags` says `False`. That is why the flags can be plain booleans with no per-type table.

- [ ] **Step 6: Migration and revision bump**

`0009_emitter_firma_email.py`, `down_revision = "0008"`, one `op.add_column("emitter_profile", sa.Column("firma_email", sa.Text(), nullable=True))`. Bump `test_migrations.py:139,161` to `"0009"`.

- [ ] **Step 7: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_sollecito_template.py packages/core/tests/test_emitter.py packages/core/tests/test_migrations.py packages/core/tests/test_templates_service.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core packages/core/migrations/versions/0009_emitter_firma_email.py \
        packages/core/tests
git commit -m "feat(gmail): carry Acme's reminder text, leave its author's name behind"
```

---

### Task B2-8: `payment_reminders` and `candidates()` — **BLOCKED ON SLICE 3**

**Do not start this task until slice 3 (invoices) is in `main`.** There is no `invoices` package in the tree. The four conditions below each read an invoice column, and implementing them against an invented model would produce logic tested against a shape slice 3 then contradicts.

**Exactly what this task needs from slice 3**, and nothing more:

| Needed | Used for |
|---|---|
| An invoice entity with `id`, `numero`, `data` | Identity and the template's `numero_fattura` / `data_fattura` |
| `data_scadenza` (a date) | Condition 2 — the only thing that makes a reminder legitimate |
| A payment state with an unambiguous "unpaid" value | Condition 1 |
| `importo` (`Numeric(12, 2)`) | The template's `importo` |
| `customer_id` | Resolving the recipient and the reply signal |
| The issuer's IBAN, on `emitter_profile` or on the invoice | The template's `iban` |

If slice 3 names these differently, adapt the code below and record the mapping in this task rather than renaming slice 3's columns.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/gmail/models.py` (append `PaymentReminder`)
- Create: `packages/core/src/pigrocrm/core/gmail/solleciti.py`
- Create: `packages/core/migrations/versions/0010_payment_reminders.py`
- Modify: `packages/core/tests/test_migrations.py:139,161`
- Create: `packages/core/tests/test_solleciti_candidates.py`

**Interfaces:**
- Consumes: slice 3's invoice model; `GmailRepository.last_inbound_from` from B1-9; `Settings.solleciti_*` (added in this task: `solleciti_grace_days: int = 7`, `solleciti_min_interval_days: int = 14`, `solleciti_max_reminders: int = 3`).
- Produces:
  ```python
  class PaymentReminder(Base, PrimaryKeyMixin, TimestampMixin):
      invoice_id: Mapped[UUID]
      sequence: Mapped[int]          # unique together with invoice_id
      sent_at: Mapped[datetime | None]
      email_draft_id: Mapped[UUID | None]

  class SollecitoCandidate(BaseModel):
      invoice_id: UUID
      numero: str
      data_scadenza: date
      giorni_di_ritardo: int
      importo: Decimal
      cliente: str
      customer_id: UUID
      solleciti_inviati: int
      ultimo_sollecito_il: date | None
      prossimo_livello: int
      ultima_risposta_il: date | None      # the signal Acme could not have

  class SollecitiService:
      def __init__(self, session: Session, *, settings: Settings) -> None: ...
      def candidates(self, actor: Actor) -> list[SollecitoCandidate]: ...
  ```

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_solleciti_candidates.py` — the four conditions, one test each, plus the reply signal:

```python
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.gmail.models import GmailMessage, PaymentReminder
from pigrocrm.core.gmail.solleciti import SollecitiService
from tests.fakes.gmail_fixtures import actor_for, connected_account, gmail_settings
# Slice 3's own helper. If it does not exist under this name, use whatever
# packages/core/tests/test_invoices*.py provides -- do not build a second one.
from tests.fakes.invoice_fixtures import unpaid_invoice


def _service(session: Session) -> SollecitiService:
    return SollecitiService(session, settings=gmail_settings())


def test_a_paid_invoice_is_never_a_candidate(db_session: Session) -> None:
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    invoice.stato_pagamento = "pagata"
    db_session.commit()
    assert _service(db_session).candidates(actor_for(account)) == []


def test_an_invoice_inside_the_grace_period_is_not_yet_a_candidate(
    db_session: Session,
) -> None:
    """Default 7 days. Chasing the day after the due date is aggressive and often wrong:
    the transfer has already left."""
    account = connected_account(db_session)
    unpaid_invoice(db_session, due=date.today() - timedelta(days=3))
    db_session.commit()
    assert _service(db_session).candidates(actor_for(account)) == []


def test_an_invoice_past_the_grace_period_is_a_candidate(db_session: Session) -> None:
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=10))
    db_session.commit()
    candidates = _service(db_session).candidates(actor_for(account))
    assert [c.invoice_id for c in candidates] == [invoice.id]
    assert candidates[0].giorni_di_ritardo == 10
    assert candidates[0].prossimo_livello == 1


def test_a_recent_reminder_takes_it_off_the_list_for_the_minimum_interval(
    db_session: Session,
) -> None:
    """Default 14 days. This is the layer that stops the double send hours apart, after
    the first one has been forgotten."""
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    db_session.add(
        PaymentReminder(
            invoice_id=invoice.id, sequence=1, sent_at=datetime.now(UTC) - timedelta(days=3)
        )
    )
    db_session.commit()
    assert _service(db_session).candidates(actor_for(account)) == []


def test_after_the_minimum_interval_it_returns_at_the_next_level(db_session: Session) -> None:
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=40))
    db_session.add(
        PaymentReminder(
            invoice_id=invoice.id, sequence=1, sent_at=datetime.now(UTC) - timedelta(days=20)
        )
    )
    db_session.commit()
    candidate = _service(db_session).candidates(actor_for(account))[0]
    assert candidate.solleciti_inviati == 1
    assert candidate.prossimo_livello == 2


def test_the_cap_stops_it_becoming_automated_harassment(db_session: Session) -> None:
    """Default 3. What stops a disputed invoice from turning into a persecution."""
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=200))
    for sequence in (1, 2, 3):
        db_session.add(
            PaymentReminder(
                invoice_id=invoice.id,
                sequence=sequence,
                sent_at=datetime.now(UTC) - timedelta(days=60 - sequence * 15),
            )
        )
    db_session.commit()
    assert _service(db_session).candidates(actor_for(account)) == []


def test_a_client_who_replied_is_flagged_and_sorted_last_but_not_removed(
    db_session: Session,
) -> None:
    """The signal Acme could not have had. A reply is not a payment, and sometimes the
    reply is exactly what needs chasing -- so it does not suppress the candidate. It goes
    to the bottom of the list and says why. Chasing someone who has already replied is
    the mistake a CRM that does not read email cannot even notice it is making."""
    account = connected_account(db_session)
    quiet = unpaid_invoice(db_session, due=date.today() - timedelta(days=20), numero="2026/01")
    replied = unpaid_invoice(db_session, due=date.today() - timedelta(days=40), numero="2026/02")
    customer = db_session.get(Customer, replied.customer_id)
    assert customer is not None
    customer.email = "info@acme.it"
    db_session.add(
        GmailMessage(
            google_account_id=account.id,
            gmail_message_id="m-reply",
            gmail_thread_id="t-1",
            direction="inbound",
            from_address="info@acme.it",
            to_addresses=["io@example.it"],
            subject="Re: Fattura 2026/02",
            internal_date=datetime.now(UTC) - timedelta(days=5),
        )
    )
    db_session.commit()

    candidates = _service(db_session).candidates(actor_for(account))
    assert [c.numero for c in candidates] == ["2026/01", "2026/02"]
    assert candidates[1].ultima_risposta_il is not None
    assert candidates[0].ultima_risposta_il is None


def test_candidates_sends_absolutely_nothing(db_session: Session) -> None:
    """Spec 7.1: "this call sends nothing. It prepares the list." Asserted rather than
    trusted, because the whole product argument -- the boring part is *building the
    list* -- rests on it."""
    from tests.fakes.fake_gmail import FakeGmail

    account = connected_account(db_session)
    unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    db_session.commit()
    fake = FakeGmail()
    _service(db_session).candidates(actor_for(account))
    assert fake.requests == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_solleciti_candidates.py -v`
Expected: FAIL — `No module named 'tests.fakes.invoice_fixtures'`, which is the correct failure while slice 3 is absent. **Stop here if that is the failure.**

- [ ] **Step 3: Write the model, the settings and the service**

Append to `gmail/models.py`:

```python
class PaymentReminder(Base, PrimaryKeyMixin, TimestampMixin):
    """One reminder for one invoice, at one position in the sequence.

    The unique constraint on `(invoice_id, sequence)` is the first of the three layers
    of spec 7.3, and it is the database that guarantees it rather than application code:
    two concurrent writes mean the second takes an IntegrityError and becomes a Conflict.

    Acme had none of this. `wasSent = emailSentCount > 0` chose between a courtesy copy
    and a reminder, and nothing anywhere checked a due date, an interval, or a ceiling.
    Pressing the button ten times sent ten emails -- and the choice was wrong even when
    it worked: a courtesy copy resent because the first bounced became, on the second
    send, a letter of demand.
    """

    __tablename__ = "payment_reminders"
    __table_args__ = (
        UniqueConstraint("invoice_id", "sequence", name="uq_payment_reminders_invoice_sequence"),
    )

    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    email_draft_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="SET NULL"), default=None
    )
```

`ForeignKey("invoices.id")` uses slice 3's actual table name — check it and adjust. `0010_payment_reminders.py` also adds the deferred FK from `email_drafts.payment_reminder_id` to this table, which B2-3 deliberately left off.

Settings, with `Field(ge=…, le=…)` on each because they are `Integer`-shaped and reach no service-level range check:

```python
    solleciti_grace_days: int = 7
    solleciti_min_interval_days: int = 14
    solleciti_max_reminders: int = 3
```

`packages/core/src/pigrocrm/core/gmail/solleciti.py`:

```python
"""Which invoices are worth chasing.

A query, not an event. And **this call sends nothing** -- it prepares the list, which is
the part that was actually laborious: crossing due dates against payments. Pressing a
button was never the work.

The comparison with Acme justifies each of the four conditions. There, the reminder was
chosen by `emailSentCount > 0` -- "is this the second email" -- with no due date, no
interval and no ceiling anywhere. Here the due date is the only thing that makes a
reminder legitimate, the interval is the only thing that makes it bearable, and the
ceiling is what stops a disputed invoice becoming an automated persecution.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.gmail.models import PaymentReminder
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.schemas import SollecitoCandidate
from pigrocrm.core.invoices.models import Invoice  # slice 3


class SollecitiService:
    def __init__(self, session: Session, *, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = GmailRepository(session)

    def candidates(self, actor: Actor) -> list[SollecitoCandidate]:
        del actor  # reading the list is not role-gated; sending is
        today = date.today()
        grace_cutoff = today - timedelta(days=self.settings.solleciti_grace_days)
        interval_cutoff = datetime.now(UTC) - timedelta(
            days=self.settings.solleciti_min_interval_days
        )

        # One aggregate over payment_reminders, so conditions 3 and 4 are a HAVING rather
        # than N follow-up queries.
        reminders = (
            select(
                PaymentReminder.invoice_id.label("invoice_id"),
                func.count().label("inviati"),
                func.max(PaymentReminder.sent_at).label("ultimo"),
            )
            .group_by(PaymentReminder.invoice_id)
            .subquery()
        )

        rows = self.session.execute(
            select(
                Invoice,
                Customer,
                func.coalesce(reminders.c.inviati, 0).label("inviati"),
                reminders.c.ultimo,
            )
            .join(Customer, Customer.id == Invoice.customer_id)
            .outerjoin(reminders, reminders.c.invoice_id == Invoice.id)
            .where(
                # 1. not paid
                Invoice.stato_pagamento != "pagata",
                # 2. overdue by more than the grace period -- chasing the day after the
                #    due date is aggressive and often wrong: the transfer has left
                Invoice.data_scadenza < grace_cutoff,
                Customer.deleted_at.is_(None),
            )
            .having(
                # 3. no reminder inside the minimum interval
                func.coalesce(func.max(reminders.c.ultimo), datetime(1970, 1, 1, tzinfo=UTC))
                < interval_cutoff,
            )
            .group_by(Invoice.id, Customer.id, reminders.c.inviati, reminders.c.ultimo)
            .order_by(Invoice.data_scadenza)
        ).all()

        candidates: list[SollecitoCandidate] = []
        account = self.repo.any_account()
        for invoice, customer, inviati, ultimo in rows:
            # 4. below the ceiling
            if inviati >= self.settings.solleciti_max_reminders:
                continue

            # The signal Acme could not have had: from the moment the CRM reads the
            # mail, the list can say "the client replied on 12 August". It does not
            # suppress the candidate -- a reply is not a payment, and sometimes the reply
            # is exactly what needs chasing -- but it goes last and it says so.
            reply = (
                self.repo.last_inbound_from(
                    account.id,
                    self._addresses_of(customer),
                    datetime.combine(invoice.data, datetime.min.time(), tzinfo=UTC),
                )
                if account is not None
                else None
            )

            candidates.append(
                SollecitoCandidate(
                    invoice_id=invoice.id,
                    numero=invoice.numero,
                    data_scadenza=invoice.data_scadenza,
                    giorni_di_ritardo=(today - invoice.data_scadenza).days,
                    importo=invoice.importo,
                    cliente=customer.ragione_sociale,
                    customer_id=customer.id,
                    solleciti_inviati=int(inviati),
                    ultimo_sollecito_il=ultimo.date() if ultimo else None,
                    prossimo_livello=int(inviati) + 1,
                    ultima_risposta_il=reply.internal_date.date() if reply else None,
                )
            )

        # Repliers last, then most overdue first. Ordered here rather than in SQL because
        # the reply signal is not a column: it is the result of the per-customer lookup
        # above, and pushing it into the query would mean a join on gmail_messages that
        # says nothing clearer.
        candidates.sort(
            key=lambda candidate: (
                candidate.ultima_risposta_il is not None,
                -candidate.giorni_di_ritardo,
            )
        )
        return candidates

    @staticmethod
    def _addresses_of(customer: Customer) -> list[str]:
        addresses = [customer.email.lower()] if customer.email else []
        addresses.extend(
            person.email.lower()
            for person in customer.people
            if person.email and person.deleted_at is None
        )
        return list(dict.fromkeys(addresses))
```

`GmailRepository.any_account()` returns the single `google_accounts` row (there is at most one per user, and reminders are read per installation) or `None`, so the list still works on an installation with no Gmail connected — it simply carries no reply signal, which is the honest degradation.

`SollecitoCandidate` goes in `gmail/schemas.py` with the field types given in the Interfaces block above. `importo` is `Decimal` with `Field(max_digits=12, decimal_places=2)`, matching slice 3's `Numeric(12, 2)`.

The `.having()` clause above reads `func.max(reminders.c.ultimo)`, which is a max over an already-aggregated column. If slice 3's schema makes that awkward, move condition 3 into the Python loop beside condition 4 — the correctness is what matters, and the test for it (`test_a_recent_reminder_takes_it_off_the_list_for_the_minimum_interval`) does not care which layer enforces it.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/core/tests/test_solleciti_candidates.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core packages/core/migrations/versions/0010_payment_reminders.py \
        packages/core/tests/test_solleciti_candidates.py packages/core/tests/test_migrations.py
git commit -m "feat(solleciti): a candidate list with a due date, an interval and a ceiling"
```

---

### Task B2-9: Creating a reminder creates a draft, and sends nothing — **BLOCKED ON SLICE 3**

**Files:**
- Modify: `packages/core/src/pigrocrm/core/gmail/solleciti.py`
- Create: `packages/core/tests/test_solleciti_create.py`

**Interfaces:**
- Consumes: `SollecitoCandidate` from B2-8; `EmailDraftService.create` from B2-3; `SOLLECITO_TEMPLATE_SOURCE`/`level_flags` from B2-7; `GmailRepository` for the thread lookup.
- Produces:
  ```python
  def create_reminder(self, invoice_id: UUID, actor: Actor) -> PaymentReminderRead: ...
  # PaymentReminderRead carries `email_draft_id`, so the caller sends through the one
  # send path and nowhere else.
  ```

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_solleciti_create.py`:

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.models import EmailDraft, GmailMessage, PaymentReminder
from pigrocrm.core.gmail.solleciti import SollecitiService
from tests.fakes.fake_gmail import FakeGmail
from tests.fakes.gmail_fixtures import actor_for, connected_account, gmail_settings, send_service
from tests.fakes.invoice_fixtures import unpaid_invoice


def _service(session: Session) -> SollecitiService:
    return SollecitiService(session, settings=gmail_settings())


def test_creating_a_reminder_creates_a_draft_and_sends_nothing(db_session: Session) -> None:
    """Spec 8.3: POST /api/payment-reminders does not send. That is what lets 7.3 rely
    on 6.1's idempotence instead of rewriting it -- one send path in the whole slice."""
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    db_session.commit()
    fake = FakeGmail()

    read = _service(db_session).create_reminder(invoice.id, actor_for(account))
    db_session.commit()

    assert read.sequence == 1
    assert read.email_draft_id is not None
    assert read.sent_at is None
    draft = db_session.get(EmailDraft, read.email_draft_id)
    assert draft is not None and draft.send_state == "bozza"
    assert "Sollecito" in draft.subject
    assert invoice.numero in draft.body_markdown
    # Not one HTTP call. Nothing was sent, by anyone, anywhere.
    assert fake.requests == []


def test_the_draft_body_is_the_template_and_not_a_string_in_the_source(
    db_session: Session,
) -> None:
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    db_session.commit()
    read = _service(db_session).create_reminder(invoice.id, actor_for(account))
    draft = db_session.get(EmailDraft, read.email_draft_id)
    assert draft is not None
    assert "Fattura:" in draft.body_markdown
    assert "IBAN:" in draft.body_markdown
    assert "Ivan Sala" not in draft.body_markdown


def test_two_concurrent_creations_produce_one_row_and_one_conflict(
    db_session: Session, db_engine: Engine
) -> None:
    """Spec 13, criterion 14. The database arbitrates, via (invoice_id, sequence)."""
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    db_session.commit()

    def attempt() -> str:
        with Session(db_engine) as session:
            try:
                SollecitiService(session, settings=gmail_settings()).create_reminder(
                    invoice.id, actor_for(account)
                )
                return "created"
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _: attempt(), range(2)))

    assert outcomes == ["conflict", "created"]
    with Session(db_engine) as check:
        assert check.execute(
            select(func.count()).select_from(PaymentReminder)
        ).scalar_one() == 1


def test_a_reminder_inside_an_existing_thread_replies_to_the_original_send(
    db_session: Session,
) -> None:
    """Spec 13, criterion 13, end to end: the reminder threads onto the invoice's own
    covering email, so the recipient can see the invoice above it."""
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    original = GmailMessage(
        google_account_id=account.id,
        gmail_message_id="m-orig",
        gmail_thread_id="t-invoice",
        message_id_header="<invio.originale@crm.example.it>",
        direction="outbound",
        from_address="io@example.it",
        to_addresses=["info@acme.it"],
        subject=f"Fattura {invoice.numero}",
        internal_date=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    db_session.add(original)
    db_session.commit()

    read = _service(db_session).create_reminder(invoice.id, actor_for(account))
    draft = db_session.get(EmailDraft, read.email_draft_id)
    assert draft is not None
    assert draft.in_reply_to_message_id == original.id


def test_the_candidate_leaves_the_list_once_the_reminder_has_been_sent(
    db_session: Session,
) -> None:
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=30))
    db_session.commit()
    service = _service(db_session)
    read = service.create_reminder(invoice.id, actor_for(account))
    db_session.commit()

    fake = FakeGmail()
    send_service(db_session, fake).send(read.email_draft_id, actor_for(account))
    db_session.commit()

    assert service.candidates(actor_for(account)) == []
    row = db_session.get(PaymentReminder, read.id)
    assert row is not None and row.sent_at is not None


def test_creating_a_reminder_beyond_the_cap_is_refused(db_session: Session) -> None:
    account = connected_account(db_session)
    invoice = unpaid_invoice(db_session, due=date.today() - timedelta(days=200))
    for sequence in (1, 2, 3):
        db_session.add(PaymentReminder(invoice_id=invoice.id, sequence=sequence))
    db_session.commit()
    with pytest.raises(Conflict, match="massimo"):
        _service(db_session).create_reminder(invoice.id, actor_for(account))
```

- [ ] **Step 2: Run it and watch it fail**

Expected: FAIL — `SollecitiService has no attribute 'create_reminder'`.

- [ ] **Step 3: Implement `create_reminder`**

Append to `packages/core/src/pigrocrm/core/gmail/solleciti.py`:

```python
    def create_reminder(self, invoice_id: UUID, actor: Actor) -> PaymentReminderRead:
        """Creates the `payment_reminders` row **and** its draft. Sends nothing.

        Spec 8.3 is explicit that this endpoint does not send: the draft goes out through
        `/api/email-drafts/{id}/send` like any other email. That is what lets spec 7.3
        rely on 6.1's idempotence instead of reimplementing it -- **one send path in the
        whole slice** -- and it is why `sent_at` is filled by
        `EmailSendService._record_sent` rather than here.
        """
        actor.require_write("preparare un sollecito")
        invoice = self.session.get(Invoice, invoice_id)
        if invoice is None:
            raise NotFound("invoice", invoice_id)

        already = self.repo.reminder_count(invoice_id)
        if already >= self.settings.solleciti_max_reminders:
            raise Conflict(
                "payment_reminder",
                f"questa fattura ha già il numero massimo di solleciti "
                f"({self.settings.solleciti_max_reminders})",
                invoice_id=str(invoice_id),
                solleciti_inviati=already,
            )
        sequence = already + 1

        customer = self.session.get(Customer, invoice.customer_id)
        if customer is None:
            raise NotFound("customer", invoice.customer_id)
        recipients = self._recipients(customer)
        if not recipients:
            raise Conflict(
                "payment_reminder",
                f"{customer.ragione_sociale} non ha un indirizzo email a cui scrivere",
            )

        profile = self.repo.emitter_profile()
        body = render_template(
            SOLLECITO_TEMPLATE_SOURCE,
            {
                "cliente": customer.ragione_sociale,
                "numero_fattura": invoice.numero,
                "data_fattura": format_italian_date(invoice.data),
                "scadenza": format_italian_date(invoice.data_scadenza),
                "importo": format_euro(invoice.importo),
                "iban": self._iban(invoice, profile),
                "firma_email": (profile.firma_email if profile else "") or "",
                "emittente": {
                    "ragione_sociale": (profile.ragione_sociale if profile else "") or "",
                    "telefono": (profile.telefono if profile else "") or "",
                    "sito_web": (profile.sito_web if profile else "") or "",
                },
                **level_flags(sequence),
            },
            SOLLECITO_DECLARED_VARIABLES,
        )

        draft = EmailDraftService(self.session, settings=self.settings).create(
            EmailDraftCreate(
                entity_type="customer",
                entity_id=customer.id,
                to_addresses=recipients,
                subject=f"Sollecito pagamento – {invoice.numero}",
                body_markdown=body,
                # The invoice's own PDF, through slice 2's document layer -- never an
                # arbitrary upload (spec 6.4).
                attachment_version_ids=self.repo.invoice_pdf_version_ids(invoice_id),
                # Threads the reminder onto the original covering email, so the recipient
                # sees the invoice above it. Without this the reminder arrives detached
                # and the first thing they do is ask for the invoice again.
                in_reply_to_message_id=self.repo.last_outbound_about(invoice.numero),
            ),
            actor,
        )

        reminder = PaymentReminder(
            invoice_id=invoice_id, sequence=sequence, email_draft_id=draft.id
        )
        self.session.add(reminder)
        try:
            self.session.flush()
        except IntegrityError as clash:
            # The unique constraint on (invoice_id, sequence) is the first of the three
            # layers of spec 7.3, and the database is what guarantees it: two concurrent
            # callers both pass the count above, and only the constraint stops the
            # second. Without the rollback the caller's session is poisoned.
            self.session.rollback()
            raise Conflict(
                "payment_reminder",
                f"un sollecito numero {sequence} per questa fattura esiste già",
                invoice_id=str(invoice_id),
                sequence=sequence,
            ) from clash

        self.activities.record(
            "customer",
            customer.id,
            "gmail.sollecito_inviato",
            actor,
            {
                "invoice_id": str(invoice_id),
                "numero": invoice.numero,
                "sequence": sequence,
                "email_draft_id": str(draft.id),
                # Deliberately not "sent": this records that a reminder was *prepared*.
                "inviato": False,
            },
        )
        self.session.commit()
        return PaymentReminderRead.model_validate(reminder)

    @staticmethod
    def _recipients(customer: Customer) -> list[str]:
        """The customer's own address if it has one; otherwise every live person on it.
        An invoice reminder goes to whoever pays, and on a small company that is often a
        named person rather than a generic mailbox."""
        if customer.email:
            return [customer.email.lower()]
        return [
            person.email.lower()
            for person in customer.people
            if person.email and person.deleted_at is None
        ]

    @staticmethod
    def _iban(invoice: Invoice, profile: EmitterProfile | None) -> str:
        """The invoice's own IBAN if slice 3 records one per invoice, else the emitter's.
        Never a literal: Acme's `normalizeIban(iban) || 'IBAN_PAGAMENTO'` shipped the
        placeholder to the client whenever the value was missing, which is worse than
        refusing."""
        iban = getattr(invoice, "iban", None) or (profile.iban if profile else None)
        if not iban:
            raise Conflict(
                "payment_reminder",
                "manca l'IBAN: compilalo nel profilo dell'emittente prima di sollecitare",
            )
        return str(iban)
```

Three repository methods to add alongside: `reminder_count(invoice_id) -> int`, `invoice_pdf_version_ids(invoice_id) -> list[UUID]` (the current version of the invoice's own document), and `last_outbound_about(numero) -> UUID | None` (the newest outbound `gmail_messages` row whose `subject` contains the invoice number, `escape_like`-escaped). `PaymentReminderRead` mirrors the model with `from_attributes=True`. `format_italian_date` and `format_euro` come from wherever slice 2/3 already put them — reuse, do not add a second pair.

`EmitterProfile.iban` may not exist: slice 2 shipped no IBAN column. If it does not, add it in this task the same way B2-7 added `firma_email` (nullable `String(34)`, the IBAN maximum, with a matching `max_length`), and record it here — a reminder with no IBAN is a reminder nobody can act on.

- [ ] **Step 4: Run it, watch it pass, commit**

```bash
uv run pytest packages/core/tests/test_solleciti_create.py -v
git add packages/core/src/pigrocrm/core/gmail packages/core/tests/test_solleciti_create.py
git commit -m "feat(solleciti): creating a reminder writes a draft and sends nothing"
```

---

### Task B2-10: The send REST surface, and the MCP surface that cannot send

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/email_drafts.py`
- Create: `apps/api/src/pigrocrm_api/routers/payment_reminders.py` (**routes registered only when slice 3 is present**)
- Modify: `apps/api/src/pigrocrm_api/main.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/gmail.py` (add `draft_email`, and `list_payment_reminder_candidates` when slice 3 is present)
- Create: `apps/api/tests/test_email_drafts_router.py`
- Modify: `apps/mcp/tests/test_gmail_tools.py`

**Interfaces:**
- Produces:
  ```
  GET    /api/email-drafts            POST /api/email-drafts
  GET    /api/email-drafts/{id}       PATCH /api/email-drafts/{id}   DELETE /api/email-drafts/{id}
  POST   /api/email-drafts/{id}/send
  POST   /api/email-drafts/{id}/reconcile
  GET    /api/payment-reminders/candidates      # slice 3
  POST   /api/payment-reminders                 # slice 3 — creates, never sends
  ```
  and the MCP tool `draft_email(entity_type, entity_id, to_addresses, subject, body_markdown) -> dict`.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_email_drafts_router.py`:

```python
def test_send_exists_as_an_endpoint(client, admin_headers, draft_id) -> None:
    """And deliberately not as an MCP tool. That gap between the two surfaces is the
    design, not an omission to fill in later."""
    response = client.post(f"/api/email-drafts/{draft_id}/send", headers=admin_headers)
    assert response.status_code in {200, 409}


def test_a_readonly_actor_cannot_send(client, readonly_headers, draft_id) -> None:
    assert client.post(f"/api/email-drafts/{draft_id}/send", headers=readonly_headers).status_code == 403


def test_an_uncertain_draft_answers_409_and_the_body_says_verify_not_sent(
    client, admin_headers, uncertain_draft_id
) -> None:
    response = client.post(f"/api/email-drafts/{uncertain_draft_id}/send", headers=admin_headers)
    assert response.status_code == 409
    assert "verifica" in response.json()["detail"]
    assert "inviata" not in response.json()["detail"].lower()


def test_reconcile_is_reachable_on_its_own(client, admin_headers, uncertain_draft_id) -> None:
    assert client.post(
        f"/api/email-drafts/{uncertain_draft_id}/reconcile", headers=admin_headers
    ).status_code == 200


def test_no_draft_endpoint_accepts_an_arbitrary_attachment_upload(client) -> None:
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/email-drafts"):
            continue
        for operation in operations.values():
            body = operation.get("requestBody", {}).get("content", {})
            assert "multipart/form-data" not in body, path
```

and appended to `apps/mcp/tests/test_gmail_tools.py`:

```python
async def test_draft_email_is_the_one_writing_tool_an_agent_gets(mcp_server) -> None:
    """Spec 8.1: this is where an agent is worth the most -- "prepare the covering email
    for the offer" -- and it writes a local draft, nothing more."""
    names = {tool.name for tool in await mcp_server.list_tools()}
    assert "draft_email" in names
    assert "send_email" not in names


async def test_draft_email_leaves_the_draft_unsent_and_makes_no_http_call(
    mcp_server, db_session, fake_gmail, customer_id
) -> None:
    from sqlalchemy import select

    from pigrocrm.core.gmail.models import EmailDraft

    await mcp_server.call_tool(
        "draft_email",
        {
            "entity_type": "customer",
            "entity_id": str(customer_id),
            "to_addresses": ["ada@acme.it"],
            "subject": "Accompagnamento offerta",
            "body_markdown": "Gentile Ada,\n\nin allegato l'offerta.",
        },
    )
    draft = db_session.execute(select(EmailDraft)).scalars().one()
    assert draft.send_state == "bozza"
    assert fake_gmail.requests == []


async def test_the_entire_mcp_suite_never_calls_messages_send(mcp_server, fake_gmail) -> None:
    """Spec 13, criterion 15, as a whole-suite property. Run last, after every other
    test in this module has executed against the shared fake."""
    assert [request for request in fake_gmail.requests if request.is_messages_send] == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest apps/api/tests/test_email_drafts_router.py apps/mcp/tests/test_gmail_tools.py -v`
Expected: FAIL — 404 on the draft paths, `draft_email` absent.

- [ ] **Step 3: Write the routers and the tool**

`apps/api/src/pigrocrm_api/routers/email_drafts.py` — the two action endpoints are the whole point of the file:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.gmail.drafts import EmailDraftService
from pigrocrm.core.gmail.schemas import (
    EmailDraftCreate,
    EmailDraftListQuery,
    EmailDraftPage,
    EmailDraftRead,
    EmailDraftUpdate,
)
from pigrocrm.core.gmail.send import EmailSendService
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport
from pigrocrm.core.storage import storage_from_settings
from pigrocrm_api.deps import current_actor, get_session, get_settings_dep

router = APIRouter(prefix="/api/email-drafts", tags=["email-drafts"])


def _sender(session: Session, settings: Settings) -> EmailSendService:
    transport = GmailTransport()
    return EmailSendService(
        session,
        settings=settings,
        transport=transport,
        tokens=GoogleTokenClient(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            transport=transport,
        ),
        storage=storage_from_settings(settings),
    )


@router.post("", response_model=EmailDraftRead, status_code=201)
def create_draft(
    payload: EmailDraftCreate,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> EmailDraftRead:
    return EmailDraftService(session, settings=settings).create(payload, actor)


@router.get("/{draft_id}", response_model=EmailDraftRead)
def read_draft(
    draft_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> EmailDraftRead:
    return EmailDraftService(session, settings=settings).get(draft_id, actor)


@router.patch("/{draft_id}", response_model=EmailDraftRead)
def update_draft(
    draft_id: UUID,
    payload: EmailDraftUpdate,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> EmailDraftRead:
    return EmailDraftService(session, settings=settings).update(draft_id, payload, actor)


@router.delete("/{draft_id}", status_code=204)
def delete_draft(
    draft_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> None:
    EmailDraftService(session, settings=settings).delete(draft_id, actor)


@router.get("", response_model=EmailDraftPage)
def list_drafts(
    query: Annotated[EmailDraftListQuery, Depends()],
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> EmailDraftPage:
    return EmailDraftService(session, settings=settings).list(query, actor)


@router.post("/{draft_id}/send", response_model=EmailDraftRead)
def send_draft(
    draft_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> EmailDraftRead:
    """The only endpoint in the product that sends an email, and deliberately **not** an
    MCP tool. That gap between the two surfaces is the design: an email sent from your
    mailbox cannot be recalled, the client reads it as your words, and an agent holding
    read-of-the-mail and send in the same belt has the injection source and the
    exfiltration channel in one channel."""
    return _sender(session, settings).send(draft_id, actor)


@router.post("/{draft_id}/reconcile", response_model=EmailDraftRead)
def reconcile_draft(
    draft_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[Actor, Depends(current_actor)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> EmailDraftRead:
    """Resolves an `incerto` draft by asking Gmail. Also runs at the start of every sync,
    so an unresolved outcome does not wait for someone to remember it."""
    return _sender(session, settings).reconcile(draft_id, actor)
```

`apps/api/src/pigrocrm_api/routers/payment_reminders.py` is the same shape over `SollecitiService`, with `GET /candidates` and a `POST ""` that returns `PaymentReminderRead` and **sends nothing**. In `main.py`:

```python
# Registered only when slice 3 is in the tree. `payment_reminders.py` imports
# pigrocrm.core.invoices, which does not exist yet, and a router that cannot import is
# an API that will not boot. Delete this guard -- and the try/except -- the day slice 3
# lands; leaving it in place would hide a genuine import error later.
try:
    from pigrocrm_api.routers import payment_reminders

    app.include_router(payment_reminders.router)
except ImportError:  # pragma: no cover - exercised only before slice 3 exists
    pass
```

The MCP tool, appended to `apps/mcp/src/pigrocrm_mcp/tools/gmail.py`'s `register`:

```python
    @server.tool()
    def draft_email(
        entity_type: GmailEntityType,
        entity_id: UUID,
        to_addresses: list[str],
        subject: str,
        body_markdown: str,
    ) -> dict[str, object]:
        """Prepara una bozza locale. **Non invia**: l'invio lo fa una persona."""
        context.require_scope("gmail:draft")
        draft = EmailDraftService(context.session, settings=context.settings).create(
            EmailDraftCreate(
                entity_type=entity_type,
                entity_id=entity_id,
                to_addresses=to_addresses,
                subject=subject,
                body_markdown=body_markdown,
                # No attachment_version_ids: which document to attach is a separate
                # decision and this task does not open it. A human adds it in the
                # composer, where they can see what they are attaching.
            ),
            context.actor,
        )
        return {
            "id": str(draft.id),
            "oggetto": draft.subject,
            "stato": draft.send_state,
            "nota": "La bozza è pronta. L'invio va fatto da una persona, dall'interfaccia.",
        }
```

`to_addresses`, `subject` and `body_markdown` are free-text `str` parameters — the first ones in the slice. They are safe under the "no Gmail search string" rule for a mechanical reason, not a judgement: they are validated by `EmailDraftCreate` (`SafeStr`, `max_length`) and they never reach a Gmail query. Add all three to B1-14's `allowed_strings` allowlist in the same commit, with that reason in the comment, so the schema test keeps its teeth instead of being widened silently.

`gmail:draft` is a second PAT scope beyond `gmail:read`, and it comes from the same R10 prerequisite. Writing a local draft is a lesser capability than reading the mailbox, so it gets its own scope rather than riding on `gmail:read`.

- [ ] **Step 4: Run, regenerate the client, commit**

```bash
uv run pytest apps/api/tests apps/mcp/tests -q
cd apps/web && pnpm generate:api && pnpm tsc --noEmit
git add apps/api apps/mcp apps/web/src/lib/api-types.ts
git commit -m "feat(gmail): send over REST only, draft_email over MCP"
```

---

### Task B2-11: The composer

**Files:**
- Create: `apps/web/src/features/gmail/EmailComposer.tsx`
- Create: `apps/web/src/features/gmail/draftQueries.ts`
- Modify: `apps/web/src/features/gmail/EmailTab.tsx` (a «Scrivi» button)
- Create: `apps/web/src/features/gmail/EmailComposer.test.tsx`

**Interfaces:**
- Consumes: the generated client for `/api/email-drafts*`; `DocumentPicker` from slice 2's documents feature, for choosing attachments.
- Produces:
  ```ts
  export function useCreateDraft(): UseMutationResult<EmailDraftRead, ApiError, EmailDraftCreate>
  export function useUpdateDraft(): UseMutationResult<EmailDraftRead, ApiError, {id: string; patch: EmailDraftUpdate}>
  export function useSendDraft(): UseMutationResult<EmailDraftRead, ApiError, string>
  export function useReconcileDraft(): UseMutationResult<EmailDraftRead, ApiError, string>
  export function EmailComposer(props: {
    entityType: 'customer' | 'person' | 'deal'
    entityId: string
    draftId?: string
    onClose: () => void
  }): JSX.Element
  ```

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/gmail/EmailComposer.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { EmailComposer } from './EmailComposer'

const base = {
  id: 'd1',
  entity_type: 'customer',
  entity_id: 'c1',
  to_addresses: ['ada@acme.it'],
  cc_addresses: [],
  subject: 'Offerta',
  body_markdown: 'Gentile Ada,',
  attachment_version_ids: [],
  message_id_header: '<a.1@crm.example.it>',
  in_reply_to_message_id: null,
  send_state: 'bozza' as const,
  send_attempted_at: null,
  last_error: null,
  sent_gmail_message_id: null,
  payment_reminder_id: null,
  created_at: '2026-08-20T09:00:00Z',
  updated_at: '2026-08-20T09:00:00Z',
}

function mockDraft(overrides: Partial<typeof base>) {
  const update = vi.fn()
  const send = vi.fn()
  vi.doMock('./draftQueries', () => ({
    useDraft: () => ({ data: { ...base, ...overrides }, isError: false, isLoading: false }),
    useCreateDraft: () => ({ mutate: vi.fn(), isPending: false }),
    useUpdateDraft: () => ({ mutate: update, isPending: false }),
    useSendDraft: () => ({ mutate: send, isPending: false }),
    useReconcileDraft: () => ({ mutate: vi.fn(), isPending: false }),
  }))
  return { update, send }
}

describe('EmailComposer', () => {
  it('prefills the recipients from the entity', () => {
    mockDraft({})
    render(<EmailComposer entityType="customer" entityId="c1" draftId="d1" onClose={vi.fn()} />)
    expect(screen.getByLabelText('A')).toHaveValue('ada@acme.it')
  })

  it('saves while you type, so a refresh does not lose the text', async () => {
    // Spec 6.1. A composer that keeps the text only in React state loses it on the
    // first refresh, and losing a hand-written email is unforgivable.
    const { update } = mockDraft({})
    render(<EmailComposer entityType="customer" entityId="c1" draftId="d1" onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Testo'), ' buongiorno')
    await vi.waitFor(() => expect(update).toHaveBeenCalled())
  })

  it('shows an uncertain outcome as "esito da verificare" and never as "inviata"', () => {
    // Spec 6.3 point 1, and criterion 9. This is the exact lie the design exists to
    // prevent.
    mockDraft({ send_state: 'incerto', last_error: 'Non sappiamo se il messaggio sia partito.' })
    render(<EmailComposer entityType="customer" entityId="c1" draftId="d1" onClose={vi.fn()} />)
    expect(screen.getByText('Esito da verificare')).toBeInTheDocument()
    expect(screen.queryByText(/inviata/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Verifica' })).toBeInTheDocument()
  })

  it('does not offer Send for a draft whose outcome is unknown', () => {
    const { send } = mockDraft({ send_state: 'incerto' })
    render(<EmailComposer entityType="customer" entityId="c1" draftId="d1" onClose={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Invia' })).not.toBeInTheDocument()
    expect(send).not.toHaveBeenCalled()
  })

  it('reopens a failed draft with the text intact and the error beside it', () => {
    mockDraft({ send_state: 'fallito', last_error: 'Gmail ha rifiutato il messaggio (codice 400).' })
    render(<EmailComposer entityType="customer" entityId="c1" draftId="d1" onClose={vi.fn()} />)
    expect(screen.getByLabelText('Testo')).toHaveValue('Gentile Ada,')
    expect(screen.getByRole('status')).toHaveTextContent('codice 400')
    expect(screen.getByRole('button', { name: 'Invia' })).toBeEnabled()
  })

  it('disables Send once and only once, so a double click cannot spend twice', async () => {
    const { send } = mockDraft({})
    render(<EmailComposer entityType="customer" entityId="c1" draftId="d1" onClose={vi.fn()} />)
    const button = screen.getByRole('button', { name: 'Invia' })
    await userEvent.dblClick(button)
    expect(send).toHaveBeenCalledTimes(1)
  })

  it('offers no free-form file upload', () => {
    // Spec 6.4: attachments come from documents only. A file input here would be a
    // second route for bytes into the system.
    mockDraft({})
    const { container } = render(
      <EmailComposer entityType="customer" entityId="c1" draftId="d1" onClose={vi.fn()} />,
    )
    expect(container.querySelector('input[type="file"]')).toBeNull()
    expect(screen.getByRole('button', { name: /Allega un documento/ })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm vitest run src/features/gmail/EmailComposer.test.tsx`
Expected: FAIL — `Failed to resolve import './EmailComposer'`.

- [ ] **Step 3: Write it**

`draftQueries.ts` mirrors `features/gmail/queries.ts` exactly in shape: types re-exported from `components['schemas']`, a `draftKeys` map, and one hook per endpoint with `if (error) throw error` and `invalidateQueries` on success. `useSendDraft` and `useReconcileDraft` both invalidate `draftKeys.one(id)` **and** `gmailKeys.messages(...)`, because a successful send writes an outbound `gmail_messages` row that the Email tab shows.

`apps/web/src/features/gmail/EmailComposer.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { DocumentPicker } from '@/features/documents/DocumentPicker'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import {
  useDraft,
  useReconcileDraft,
  useSendDraft,
  useUpdateDraft,
} from './draftQueries'

const AUTOSAVE_MS = 600

/** What the user is told, per state. `incerto` says "esito da verificare" and never
 *  "inviata": writing "sent" for a state that means "we do not know" is exactly the lie
 *  this whole design exists to prevent (spec 6.3). */
const STATE_HEADING: Record<string, string> = {
  bozza: 'Bozza',
  in_invio: 'Invio in corso',
  inviato: 'Inviata',
  incerto: 'Esito da verificare',
  fallito: 'Invio non riuscito',
}

export function EmailComposer(props: {
  entityType: 'customer' | 'person' | 'deal'
  entityId: string
  draftId?: string
  onClose: () => void
}) {
  const draft = useDraft(props.draftId)
  const update = useUpdateDraft()
  const send = useSendDraft()
  const reconcile = useReconcileDraft()

  // Two namespaces even though a draft has no custom fields today: provenance is
  // structural, decided once at seed time, so a custom field later has a place to go
  // rather than being merged in at submit.
  const [form, setForm] = useState({
    native: { to: '', cc: '', subject: '', body: '' },
    custom: {} as Record<string, unknown>,
  })
  const seeded = useRef(false)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    if (seeded.current || !draft.data) return
    seeded.current = true
    setForm({
      native: {
        to: draft.data.to_addresses.join(', '),
        cc: draft.data.cc_addresses.join(', '),
        subject: draft.data.subject,
        body: draft.data.body_markdown,
      },
      custom: {},
    })
  }, [draft.data])

  const editable = draft.data?.send_state === 'bozza' || draft.data?.send_state === 'fallito'

  // Saves while you type. Spec 6.1: losing hand-written text to an HTTP error is
  // unforgivable, and a composer that keeps it only in React state loses it on the first
  // refresh. Skipped entirely once the draft is no longer a draft -- the API would
  // refuse, and a request per keystroke against a refusal is only noise.
  useEffect(() => {
    if (!props.draftId || !seeded.current || draft.data?.send_state !== 'bozza') return
    const timer = setTimeout(() => {
      update.mutate({
        id: props.draftId!,
        patch: {
          to_addresses: form.native.to.split(',').map((value) => value.trim()).filter(Boolean),
          cc_addresses: form.native.cc.split(',').map((value) => value.trim()).filter(Boolean),
          subject: form.native.subject,
          body_markdown: form.native.body,
        },
      })
    }, AUTOSAVE_MS)
    return () => clearTimeout(timer)
  }, [form, props.draftId, draft.data?.send_state, update])

  if (draft.isError) return <QueryErrorBanner onRetry={() => void draft.refetch()} />
  if (draft.isLoading || !draft.data) return <p>Caricamento…</p>

  const state = draft.data.send_state

  return (
    <div role="dialog" aria-label="Scrivi un'email" className="space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-medium">{STATE_HEADING[state] ?? state}</h2>
        <Button variant="ghost" onClick={props.onClose}>
          Chiudi
        </Button>
      </header>

      {draft.data.last_error ? <p role="status">{draft.data.last_error}</p> : null}

      <label className="block">
        A
        <input
          aria-label="A"
          value={form.native.to}
          disabled={!editable}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              native: { ...current.native, to: event.target.value },
            }))
          }
        />
      </label>

      <label className="block">
        Oggetto
        <input
          aria-label="Oggetto"
          value={form.native.subject}
          disabled={!editable}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              native: { ...current.native, subject: event.target.value },
            }))
          }
        />
      </label>

      <label className="block">
        Testo
        <textarea
          aria-label="Testo"
          rows={14}
          value={form.native.body}
          disabled={!editable}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              native: { ...current.native, body: event.target.value },
            }))
          }
        />
      </label>

      {/* Documents only, never a file input: spec 6.4. A free upload would be a second
          route for bytes into the system, with a second authorisation to write. */}
      <DocumentPicker
        entityType={props.entityType}
        entityId={props.entityId}
        selected={draft.data.attachment_version_ids}
        disabled={!editable}
        label="Allega un documento"
        onChange={(versionIds) =>
          props.draftId
            ? update.mutate({ id: props.draftId, patch: { attachment_version_ids: versionIds } })
            : undefined
        }
      />

      <footer className="flex gap-2">
        {state === 'incerto' ? (
          <Button
            onClick={() => props.draftId && reconcile.mutate(props.draftId)}
            disabled={reconcile.isPending}
          >
            Verifica
          </Button>
        ) : null}
        {editable ? (
          <Button
            // Guarded by local state as well as isPending: a double click resolves
            // before React has re-rendered with isPending, and the server would answer
            // 409 -- correct, but the user should not be shown a conflict they caused
            // by clicking twice.
            disabled={sending || send.isPending}
            onClick={() => {
              if (sending || !props.draftId) return
              setSending(true)
              send.mutate(props.draftId, { onSettled: () => setSending(false) })
            }}
          >
            Invia
          </Button>
        ) : null}
      </footer>
    </div>
  )
}
```

The labels above are unstyled for brevity; wrap the inputs in the project's existing `Field`/`Input` primitives from `components/ui/` so the composer matches every other form. Keep `aria-label` on each control regardless — the tests select by it, and so do screen readers.

- [ ] **Step 4: Run, type-check, commit**

```bash
cd apps/web && pnpm vitest run && pnpm tsc --noEmit
git add apps/web/src/features/gmail
git commit -m "feat(web): a composer that saves as you type and never claims 'sent'"
```

---

### Task B2-12: The solleciti page — **BLOCKED ON SLICE 3**

**Files:**
- Create: `apps/web/src/features/solleciti/{queries.ts,SollecitiPage.tsx,columns.tsx}`
- Create: `apps/web/src/routes/app/solleciti.tsx`
- Create: `apps/web/src/features/solleciti/SollecitiPage.test.tsx`
- Create: `apps/web/e2e/solleciti.spec.ts`

**Interfaces:**
- Consumes: `GET /api/payment-reminders/candidates`, `POST /api/payment-reminders`, `POST /api/email-drafts/{id}/send` from B2-10; `DataTable` (**TanStack Table v9**); `QueryErrorBanner`.
- Produces: the route `/app/solleciti`, linked from `AppShell`'s navigation.

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/solleciti/SollecitiPage.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SollecitiPage } from './SollecitiPage'
import type { SollecitoCandidate } from './queries'

const quiet: SollecitoCandidate = {
  invoice_id: 'i1',
  numero: '2026/01',
  data_scadenza: '2026-07-31',
  giorni_di_ritardo: 20,
  importo: '1200.00',
  cliente: 'Acme S.r.l.',
  customer_id: 'c1',
  solleciti_inviati: 0,
  ultimo_sollecito_il: null,
  prossimo_livello: 1,
  ultima_risposta_il: null,
}

const replied: SollecitoCandidate = {
  ...quiet,
  invoice_id: 'i2',
  numero: '2026/02',
  giorni_di_ritardo: 40,
  solleciti_inviati: 1,
  ultimo_sollecito_il: '2026-08-01',
  prossimo_livello: 2,
  ultima_risposta_il: '2026-08-12',
}

function mount(
  candidates: SollecitoCandidate[] | undefined,
  state: 'ok' | 'error' = 'ok',
) {
  const create = vi.fn()
  vi.doMock('./queries', () => ({
    useCandidates: () => ({
      data: candidates,
      isError: state === 'error',
      isLoading: false,
      refetch: vi.fn(),
    }),
    useCreateReminder: () => ({ mutate: create, isPending: false }),
  }))
  render(<SollecitiPage />)
  return { create }
}

describe('SollecitiPage', () => {
  it('shows the days overdue, the amount and the date of the last reminder', () => {
    // The boring part is *building this list* by crossing due dates against payments.
    // Pressing the button was never the work, which is why the columns are the work.
    mount([replied])
    expect(screen.getByText('2026/02')).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
    expect(screen.getByText('1.200,00 €')).toBeInTheDocument()
    expect(screen.getByText('01/08/2026')).toBeInTheDocument()
    expect(screen.getByText('2° sollecito')).toBeInTheDocument()
  })

  it('flags a client who has replied, and shows them last', () => {
    // A reply is not a payment, and sometimes the reply is exactly what needs chasing.
    // So the candidate stays; it says so and it sinks.
    mount([replied, quiet])
    const rows = screen.getAllByRole('row').slice(1) // drop the header row
    expect(rows[0]).toHaveTextContent('2026/01')
    expect(rows[1]).toHaveTextContent('2026/02')
    expect(rows[1]).toHaveTextContent('ha risposto il 12/08/2026')
    expect(rows[0]).not.toHaveTextContent('ha risposto')
  })

  it('renders QueryErrorBanner rather than an empty table when the request failed', () => {
    mount(undefined, 'error')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/Nessuna fattura da sollecitare/)).not.toBeInTheDocument()
  })

  it('says the list is empty because nothing is due, not because something broke', () => {
    mount([])
    expect(screen.getByText(/Nessuna fattura da sollecitare/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('creates the reminder without sending it, and says so', () => {
    // One press, one email -- and the press that creates is not the press that sends.
    // POST /api/payment-reminders creates the row and the draft; the draft goes through
    // the same single send path as any other email.
    const { create } = mount([quiet])
    void userEvent.click(screen.getByRole('button', { name: 'Prepara sollecito' }))
    return vi.waitFor(() => {
      expect(create).toHaveBeenCalledWith('i1')
      expect(screen.queryByRole('button', { name: 'Invia' })).not.toBeInTheDocument()
    })
  })

  it('offers no bulk action, because a reminder is a commercial act', () => {
    // Spec 7.2: a human every time, in this slice. What would have to exist for this to
    // become automatic -- a per-customer opt-in, a log of empty runs, an instant kill
    // switch -- does not exist, so it is not automatic, and there is no "send all".
    mount([quiet, replied])
    expect(screen.queryByRole('button', { name: /Invia tutti|Seleziona tutt/ })).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })
})
```

`apps/web/e2e/solleciti.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { login } from './helpers'

test('a candidate becomes a reviewed draft and then exactly one email', async ({ page }) => {
  await login(page)
  await page.goto('/app/solleciti')

  const row = page.getByRole('row').filter({ hasText: '2026/' }).first()
  await expect(row).toBeVisible()
  const numero = (await row.textContent()) ?? ''

  await row.getByRole('button', { name: 'Prepara sollecito' }).click()

  // The draft opens for review. Nothing has been sent yet: the reminder text is a
  // template, so the words are the operator's own, and they get to read them.
  const composer = page.getByRole('dialog')
  await expect(composer.getByLabelText('Testo')).toContainText('Fattura:')
  await expect(composer.getByLabelText('Testo')).toContainText('IBAN:')

  await composer.getByRole('button', { name: 'Invia' }).click()
  await expect(composer).toBeHidden()

  // Gone from the list, for min_interval_days.
  await expect(page.getByRole('row').filter({ hasText: numero.slice(0, 7) })).toHaveCount(0)
})
```

- [ ] **Step 2: Run both and watch them fail**

Run: `cd apps/web && pnpm vitest run src/features/solleciti`
Expected: FAIL — `Failed to resolve import './SollecitiPage'`.

- [ ] **Step 3: Write the queries, the columns and the page**

`apps/web/src/features/solleciti/queries.ts` mirrors `features/gmail/queries.ts` exactly: `SollecitoCandidate` and `PaymentReminderRead` re-exported from `components['schemas']`, a `sollecitiKeys` map, `useCandidates()` over `GET /api/payment-reminders/candidates`, and `useCreateReminder()` over `POST /api/payment-reminders` invalidating `sollecitiKeys.candidates` and the draft list on success.

`columns.tsx` declares the `DataTable` columns — **TanStack Table v9**, so `ColumnDef<DataTableFeatures, SollecitoCandidate>` with the `tableFeatures({})` object the other feature folders already build, not v8's bare `ColumnDef<T>`:

```tsx
import type { ColumnDef } from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { formatEuro, formatItalianDate } from '@/lib/format'
import type { DataTableFeatures } from '@/components/DataTable'
import type { SollecitoCandidate } from './queries'

export function sollecitiColumns(
  onPrepare: (invoiceId: string) => void,
  pendingId: string | null,
): ColumnDef<DataTableFeatures, SollecitoCandidate>[] {
  return [
    { accessorKey: 'numero', header: 'Fattura' },
    { accessorKey: 'cliente', header: 'Cliente' },
    {
      accessorKey: 'giorni_di_ritardo',
      header: 'Giorni di ritardo',
      cell: ({ row }) => row.original.giorni_di_ritardo,
    },
    {
      accessorKey: 'importo',
      header: 'Importo',
      // Formatted from the string the API sent. Never parsed into a JS float: money is
      // Numeric(12, 2) on the server and a float here would round it silently.
      cell: ({ row }) => formatEuro(row.original.importo),
    },
    {
      accessorKey: 'ultimo_sollecito_il',
      header: 'Ultimo sollecito',
      cell: ({ row }) =>
        row.original.ultimo_sollecito_il
          ? formatItalianDate(row.original.ultimo_sollecito_il)
          : '—',
    },
    {
      id: 'prossimo_livello',
      header: 'Prossimo',
      cell: ({ row }) => `${row.original.prossimo_livello}° sollecito`,
    },
    {
      id: 'risposta',
      header: '',
      cell: ({ row }) =>
        row.original.ultima_risposta_il ? (
          <span className="text-sm text-muted-foreground">
            ha risposto il {formatItalianDate(row.original.ultima_risposta_il)}
          </span>
        ) : null,
    },
    {
      id: 'azione',
      header: '',
      cell: ({ row }) => (
        <Button
          size="sm"
          disabled={pendingId === row.original.invoice_id}
          onClick={() => onPrepare(row.original.invoice_id)}
        >
          Prepara sollecito
        </Button>
      ),
    },
  ]
}
```

`SollecitiPage.tsx`:

```tsx
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { EmailComposer } from '@/features/gmail/EmailComposer'
import { sollecitiColumns } from './columns'
import { useCandidates, useCreateReminder } from './queries'

export function SollecitiPage() {
  const candidates = useCandidates()
  const createReminder = useCreateReminder()
  const [openDraftId, setOpenDraftId] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)

  // isError first, always: an empty table and a failed request must never look the same.
  if (candidates.isError) return <QueryErrorBanner onRetry={() => void candidates.refetch()} />
  if (candidates.isLoading || !candidates.data) return <p>Caricamento…</p>

  // Already ordered by the server: a candidate whose client has replied goes last.
  // Re-sorting here would be business logic in the frontend and the two would drift.
  const rows = candidates.data

  return (
    <section className="space-y-4">
      <header>
        <h1 className="text-xl font-medium">Solleciti</h1>
        <p className="text-sm text-muted-foreground">
          Fatture scadute da più di una settimana, non ancora saldate, senza un sollecito
          recente e sotto il tetto dei tre. Preparare il sollecito non lo invia: la bozza si
          apre per la revisione.
        </p>
      </header>

      {rows.length === 0 ? (
        <p className="text-muted-foreground">
          Nessuna fattura da sollecitare. È la lista che costa fatica a costruire, non il
          pulsante da premere.
        </p>
      ) : (
        <DataTable
          columns={sollecitiColumns((invoiceId) => {
            setPendingId(invoiceId)
            createReminder.mutate(invoiceId, {
              onSuccess: (reminder) => {
                setPendingId(null)
                setOpenDraftId(reminder.email_draft_id)
              },
              onError: () => setPendingId(null),
            })
          }, pendingId)}
          data={rows}
        />
      )}

      {openDraftId ? (
        <EmailComposer
          entityType="customer"
          entityId={rows.find((row) => row.invoice_id === pendingId)?.customer_id ?? ''}
          draftId={openDraftId}
          onClose={() => setOpenDraftId(null)}
        />
      ) : null}
    </section>
  )
}
```

`apps/web/src/routes/app/solleciti.tsx` is the four-line file-based route rendering `<SollecitiPage />`, and `AppShell`'s navigation gains one entry pointing at it.

- [ ] **Step 4: Run both and watch them pass**

Run: `cd apps/web && pnpm vitest run src/features/solleciti && pnpm tsc --noEmit && pnpm test:e2e -- solleciti.spec.ts`
Expected: PASS (6 unit tests, 1 E2E).

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/solleciti apps/web/src/routes/app/solleciti.tsx \
        apps/web/src/components/AppShell.tsx apps/web/e2e/solleciti.spec.ts
git commit -m "feat(web): the solleciti list, where the work is the list and not the button"
```

---
# Self-review

Run against the spec with fresh eyes after the plan was written, as `superpowers:writing-plans` requires. Findings were fixed inline; what remains open is listed rather than hidden.

## 1. Spec coverage

| Spec | Where it lands |
|---|---|
| §1 order: landing before Gmail | *Sub-plan order* above; 5A's exit criteria; 5B-1's precondition 1 |
| §2 carried from Acme: reminder copy | B2-7 |
| §2 carried: send as the user, from their mailbox | B2-5 (`from_address` is the connected mailbox) |
| §2 redone: `getGoogleAccessToken`, no state | B1-3, B1-5 |
| §2 redone: no token cache, two exchanges per email | B1-5 |
| §2 redone: `parseGoogleError` cannot see `invalid_grant` | B1-4, B1-5 |
| §2 redone: `buildRawEmailMessage`'s three defects | B2-2 |
| §2 carried-as-columns: `emailSentAt`/`emailSentCount`/… | B2-3, B2-5 |
| §2 the two production defects | B2-5 (send before persist), B2-6 (reconciliation), B2-8 (`emailSentCount` as the only check) |
| §2 the technical precedent is `gdrive.py`, not Acme | B1-4 |
| §3 prerequisites verified, not assumed | 5B-1 and 5B-2 precondition blocks |
| §3 `customers.email` unindexed | B1-1 |
| §3 PAT scopes/expiry/audit | *The blocking prerequisite outside this slice* — stated, not planned |
| §4.1 every `list` carries a known address | **B1-7** (unconstructible) + **B1-8** (request inspection) |
| §4.1 batches of 20, `after:` in epoch seconds, 24 h overlap | B1-7, B1-8 |
| §4.2 the data decides relevance | B1-1 |
| §4.3 thread ascent; unknown senders excluded from the roster | B1-8, B1-9 |
| §4.4 three cases: new message, new address, full history | B1-8, B1-11, B1-11 |
| §4.4 the backfill queues rather than hooking `PersonService` | B1-11 (`GmailKnownAddress`) |
| §4.5 no daemon; advisory lock per account | B1-10, B1-13, B1-14 |
| §4.6 not History, not push | A rejected alternative — recorded in `sync.py`'s docstring (B1-8), no task |
| §5.1 the three scopes, and the ones not asked for | B1-3, B1-12, A4 (the policy names them) |
| §5.1 status ≠ scope sufficiency | **B1-12** |
| §5.2 refresh token encrypted at rest, key outside the DB | B1-3, B1-2 |
| §5.2 access tokens never stored | B1-5 |
| §5.3 PKCE, signed single-use state, `prompt=consent`, sub check | B1-6 |
| §5.3 no client id ⇒ Gmail does not exist here | B1-2, B1-13, B1-14, B1-15 |
| §5.4 text/plain only, 256 KB, no attachment bytes, per-account switch | B1-8, B1-15 |
| §5.4 disconnect *offers* to delete | B1-6, B1-15 |
| §5.5 `invalid_grant` terminal, no retry, activity row, banner, send blocked | **B1-12**, B1-16, B2-5 |
| §5.5 `consent_expires_at`, warning at 48 h | B1-6, B1-12 |
| §5.5 `/health` unchanged | B1-12 step 6 |
| §5.6 the six tables + the new activity kinds | B1-3, B1-8, B2-3, B2-8 |
| §6.1 durable draft, refuses non-`bozza` | B2-3, B2-5 |
| §6.2 what is recorded, and when | B2-5 |
| §6.2 the three RFC822 rules | B2-2 |
| §6.3 (a) refused vs (b) unknown | B2-5 |
| §6.3 reconciliation by `rfc822msgid`, 15-minute grace | **B2-6** |
| §6.3 verify the `Message-ID` assumption first | **B2-1** |
| §6.4 documents only, 20 MB before composing | B2-4 |
| §7.1 four conditions + the reply signal | B2-8 |
| §7.2 a human every time | B2-9, B2-12 |
| §7.3 three layers; level as a variable | B2-8, B2-9, B2-5, B2-7 |
| §8.1 what an agent may do | B1-14, B2-10 |
| §8.2 what it may not, by name and by schema | B1-14 |
| §8.3 the REST surface | B1-13, B2-10 |
| §8.4 the PAT prerequisite | Stated as blocking; consumed by B1-14 and B2-10 |
| §9.1 the four purposes of the landing | A3, A4 |
| §9.2 carry the technique, not the content; the wrong-copy trap | A1, A2, A3 |
| §9.3 no new tint, derived tokens, ΔE, grain, motion | A1, A2 |
| §9.4 separate build, same origin, 40 KB, nginx, `base: '/app/'` | A6, A7 |
| §10 the seven contradictions | *Contradictions* section; A7, A1, B1-1, B2-7 |
| §11 settings, banner, Email tab, composer, solleciti, the notice | B1-15, B1-16, B1-17, B2-11, B2-12, B1-17 |
| §12 what the slice does not do | B1-7, B1-13, B1-14, A3, A6 (each asserted, not promised) |
| §13 criteria 1–26 | See the table below |
| §14 two plans and a half | The three-part structure of this document |

**Success criteria, one by one.** 1 → B1-8 · 2 → B1-8 · 3 → B1-9 · 4 → B1-10 · 5 (a–d, f) → B1-12, (e) → B1-16, (g) → B1-12 step 6 · 6 → B1-12 · 7 → B1-12 · 8 → B1-2 and B1-14 step 5 · 9 → B2-6 · 10 → B2-5 · 11 → B2-4 · 12 → B2-2 · 13 → B2-2 and B2-9 · 14 → B2-9 · 15 → B1-8, B1-14, B2-9 · 16 → B1-14 · 17 → B1-14 (consumes the prerequisite) · 18 → A1 · 19 → A1 · 20 → A8 · 21 → A1 · 22 → A6 · 23 → A6 · 24 → A7 · 25 → A3 and A4 · 26 → A4.

**Gaps — spec text that did not become a concrete task, and why:**

1. **«Salva allegato come documento»** (§11). §8.3 lists no endpoint for it, and no attachment bytes are stored (§5.4), so it needs a new `POST /api/gmail/messages/{id}/attachments/{index}/save` that fetches from Gmail and writes through `DocumentService`. Inventing an endpoint the spec's own surface list omits would be adding scope. B1-17 renders the button disabled with `title="In arrivo"`; the endpoint is a follow-up.
2. **§4.6's rejected alternatives** (History API, `users.watch` + Pub/Sub). Correctly nothing to build; the reasoning is recorded in `sync.py`'s module docstring so the choice is not re-litigated by someone reading only the code.
3. **§8.4 / R10 + R5.** A stated blocking prerequisite, deliberately not planned here per instruction. B1-14 and B2-10 consume `gmail:read` and `gmail:draft` and will fail loudly if they do not exist.
4. **Slice 3.** B2-8, B2-9 and B2-12 are marked blocked and name the six invoice fields they need. Not plannable further without slice 3's actual column names.
5. **`emitter_profile.iban`.** Slice 2 shipped no IBAN column and the reminder template needs one. B2-9 adds it if it is still absent, following B2-7's pattern. Conditional because slice 3 may add it first.
6. **Residuo R1** (the MCP server's shared `Session`) is *widened* by `sync_gmail`, which holds that session far longer than any slice-1 tool. B1-14 says so explicitly and does not claim to fix it.

## 2. Placeholder scan

Scanned for every pattern the skill names. `TBD`/`TODO`/`FIXME`: none. "implement later" / "fill in details": none. "add appropriate error handling" / "add validation" / "handle edge cases": none. "Similar to Task N": none — repeated code is repeated in full. "Write tests for the above" without test code: none. `etc.` / "and so on": none.

Five steps were prose-only descriptions of code when first drafted and were rewritten with real code during this review: **B2-12**'s six test bodies (they were empty `{}`), **B2-12**'s page and columns, **B2-9**'s `create_reminder`, **B2-8**'s `candidates()`, **B2-11**'s `EmailComposer`, **B2-10**'s routers and `draft_email`, **B1-17**'s `EmailThread`, and **B1-15**'s route file. One self-flagged placeholder shape in **B1-12** (a ternary choosing between two identical activity kinds) was replaced with the real kind, `gmail.impostazioni_modificate`.

The remaining `...` tokens in the document are all Python stub ellipses inside **Interfaces** blocks — the signature-declaration form the skill's own task template uses. They are not omitted implementations; every one of them has a full implementation in that task's own steps.

## 3. Type consistency

Checked across tasks, since each implementer sees only their own task:

- `SyncReport` is created in B1-8 and gains exactly one field later, `reconciled`, in B2-6. Both places say so.
- `EntityRef(entity_type: str, entity_id: UUID)` is defined once (B1-1) and imported by B1-9 and B2-5. It is a plain `str`, **not** `fields.EntityType` — Contradiction 3 explains why.
- `GmailBannerReason` was written two ways (`Literal[…, None]` in an Interfaces block, `Literal[…] | None` in the code). Fixed to `Literal[…] | None` in both.
- `EmailDraftService`'s constructor and `repo_draft` were used in B2-3's tests but missing from its Interfaces block. Added.
- `_store` changes return type from `bool` to `GmailMessage | None` between B1-8 and B1-9. B1-9 states the change and the two `return False` branches it affects.
- `GmailRepository` grows across seven tasks (B1-6, B1-8, B1-9, B1-10, B1-11, B1-14, B2-5, B2-6, B2-9). Each task lists the methods it adds. If a `list`-named method is ever added to it, it goes **last** — the rule is asserted for `EmailDraftService` in B2-3 and applies to every class here.
- `GmailCall` (B1-4) is a **new** type carrying response headers, not a change to `gdrive.py`'s `HttpCall`. Nothing slice 2 was reviewed against moves.
- Scope constants live in one place, `gmail/schemas.py` (B1-3), and are imported by B1-6, B1-12, B2-5. No task restates the URLs.
- `body_html_scartato` keeps the spec's Italian spelling in the dataclass, the column, the read schema and the UI, so no rename layer exists.
- The Playwright `landing` project (A6) and the compose config (A7) select disjoint spec files, so no spec runs under two baseURLs.

## 4. Further contradictions found while writing, resolved here

Beyond the nine in the *Contradictions* section above, writing the tasks surfaced six more. All resolved in favour of the shipped code or of internal consistency, and recorded so no reviewer has to rediscover them:

1. **The spec's §9.3 breaks its own rule.** It specifies the grain hatching as `rgba(1, 25, 54, .04)` — Prussian Blue as a literal — three lines after requiring that no `--landing-*` value contain a raw hexadecimal. Resolved in A1: `color-mix(in oklab, var(--color-prussian-blue) 4%, transparent)`, identical result, one source of colour.
2. **The spec's §9.3 asks `landing.css` to "import the same `@theme` as `tokens.css`", which CSS cannot do.** Resolved in A1 by build-time extraction (Contradiction 5 above). Recorded again here because it is the one place the spec asks for something mechanically impossible rather than merely different from the code.
3. **Seven tables, not six.** §5.6 lists six; B1-11 adds a seventh, `gmail_known_addresses`. It is what makes §4.4's "the Gmail service compares the roster with the addresses already seen" true without `PersonService` learning what Gmail is. Without it that sentence has no implementation.
4. **Ten activity kinds, not nine.** §5.6 lists nine; B1-12 adds `gmail.impostazioni_modificate`, because turning the body store off changes what the CRM will remember and is worth a trace. No migration: `activities.kind` is a truncated `String(30)`.
5. **A second PAT scope.** §8.4 says `gmail:*` off by default. This plan consumes two specific ones: `gmail:read` (B1-14) and `gmail:draft` (B2-10). Writing a local draft is a lesser capability than reading a mailbox, so it does not ride on the read scope.
6. **The spec misattributes Acme's post-delivery 404.** §2 and §6.3 quote it as `404 'Offerta non trovata per registrare l'invio email.'`. Verified in the reference: `messages/send` is called at `vite.config.js:5334`, and the 404 that fires **after** it is at `:5368` — `` `Fattura non trovata per registrare l'invio. drive=${driveFileId}` ``. The offer-not-found strings at `:5114` and `:5300` both precede the send and are harmless. The spec's *argument* is exactly right and the defect is real; only the quoted string belongs to the invoice path. B2-5's and B2-6's docstrings quote the correct one.

---

## Execution handoff

Plan complete. Two execution options:

1. **Subagent-driven (recommended)** — a fresh subagent per task, with review between tasks. Use `superpowers:subagent-driven-development`. Given 37 tasks across three sub-plans with hard ordering, this is the fit.
2. **Inline execution** — batch execution with checkpoints, using `superpowers:executing-plans`.

**Execute in the order 5A → (PAT prerequisite, outside this plan) → 5B-1 → 5B-2**, and submit the Google verification the day 5A is deployed. The verification is calendar time, not work time; 5B-1 is what you build while it runs.




