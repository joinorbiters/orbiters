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
<!-- PLAN-CURSOR: 5B-1 continues at B1-8 -->


