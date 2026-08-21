# PigroCRM Slice 6 — Dashboard, ricerca globale, automazioni, prompt MCP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the last slice — a global `Cmd/Ctrl+K` search that finds a customer from a VAT fragment, two automations that run inside their trigger's transaction, three fixed dashboards whose every figure is returned verbatim by the service that owns it, and four MCP prompts — without ever creating a second source of truth for a number.

**Architecture:** Three sub-plans in one document, in a dependency order that is fixed at one point. **6A** closes residui **R6** (`ilike` with no trigram index) and **R9** (the ordering §7 of slice 1 promised and neither adapter delivers): `pg_trgm` with nine partial GIN trigram indexes, a `sort`/`dir` whitelist over an opaque composite keyset cursor, a new `packages/core/src/pigrocrm/core/search/` service, the `AppShell` header slice 1 §10.1 promised and never shipped, and a `cmdk` palette with three distinct states. It comes first because it changes the list endpoints' signature (`cursor: UUID` → `cursor: str`), and doing it after the dashboards means touching the generated client twice. **6B** adds `packages/core/src/pigrocrm/core/automations/` and `packages/core/src/pigrocrm/core/dashboard/` — a runner called explicitly from `DocumentService.set_offer_state` inside its transaction, and a composition service that contains no arithmetic and is proven to contain none by two AST clauses. **6C** adds the economic and operational dashboards and the four MCP prompts, and is the only sub-plan that needs slices 3 and 4. FastAPI routers and MCP tools call the same services in-process; `update_automation_config` is deliberately absent from the MCP surface and the architecture test enforces its absence.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · psycopg 3 · PostgreSQL 17 (`pg_trgm`) · MCP SDK v2 · pytest + testcontainers · Vite · React 19 · TanStack Router/Query/Table · Tailwind v4 · `cmdk` · Playwright · inline SVG and CSS (no charting library)

**Spec:** `docs/superpowers/specs/2026-08-20-slice-6-dashboard-e-ricerca-design.md` — it governs. Supporting: `docs/superpowers/specs/2026-08-06-pigrocrm-core-crm-mcp-design.md` (§4.1, §4.2, §5.4, §5.8, §7, §8.4, §10.1), `docs/superpowers/specs/2026-08-07-slice-1a-residui.md` (R1, R5, R6, R7, R9, R10, R11, R13, R14, R15 and the unnumbered header entry), `docs/superpowers/specs/2026-08-06-slice-1b-residui.md` (A12, A14, B2, B3, B6), `docs/superpowers/specs/2026-08-20-slice-3-fatturazione-design.md` (§3, §6.2, §7.1, §8.1, §11, §14.8), `docs/superpowers/specs/2026-08-20-slice-4-time-tracking-e-pl-design.md` (§5.1, §5.2, §6.4, §7.1, §7.3, §7.4, §11, §14.4), `docs/superpowers/specs/2026-08-20-slice-5-gmail-e-landing-design.md` (§9.3, §9.4).

---

## Sub-plan order, and the one point where it is not negotiable

| Sub-plan | Content | Tasks | Cannot start until |
|---|---|---|---|
| **6A — Ricerca globale** | Spec §8 in full, minus the invoice branch; the `AppShell` header; the palette. Closes **R6** and **R9** for four entities | 14 | **Nothing beyond what is in `main` today.** Slices 1 and 2 only |
| **6B — Automazioni, segnali e dashboard commerciale** | Spec §9 in full, §4, `chiuso_il`, `stato_dal`, `automation_config`, `/app/impostazioni/automazioni` | 14 | 6A merged. Slice 2 (offers are the trigger). **Not** slices 3, 4 or 5 |
| **6C — Dashboard economica e operativa, prompt MCP** | Spec §5, §6, §10, the §11 tools, the tenth trigram index | 13 | 6A and 6B merged; **slice 3 and slice 4 (both halves 4A and 4B) in `main`**; **the R1 cure in `main`** |

**6A → 6B → 6C is fixed at one point.** The indexes and the ordering contract of 6A change the signature of the list endpoints of `customers`, `people`, `deals` and `documents`: `cursor` stops being a `UUID` and becomes an opaque string. Building the dashboards first means regenerating `apps/web/src/lib/api-types.ts` and re-typing every call site twice. The break is caught by `pnpm tsc --noEmit` against the generated client, which is the mechanism slice 1 §10.2 put there for exactly this case.

**Each sub-plan carries its own verification.** The spec §17 distributes the §16 criteria without remainder, and this plan follows it: 6A executes criteria 3, 4, 5 and 13; 6B executes 7, 8, 9 plus **2, 6 and 14 on the commercial dashboard** — those three are criteria for *every* dashboard and fall due with the first; 6C executes 1, 10, 11, 12, 15 plus 2, 6 and 14 repeated on the two new dashboards. The signal "offerta accettata, deal non vinto" ships in 6B, on the commercial dashboard, **with** the automation it cross-checks — an automation whose only verifier arrives a sub-plan later is in production for weeks with nobody able to say whether it works.

**If slices 3 or 4 slip, 6A and 6B release anyway** and the "Economica" tab simply does not exist yet — which a user understands, unlike a tab showing zeros.

---

## Global Constraints

These apply to **every** task in all three sub-plans. They are not repeated per task. Everything from `## Global Constraints` in `2026-08-06-slice-1a-backend.md`, `2026-08-06-slice-1b-frontend.md`, `2026-08-10-slice-2-documenti-e-template.md`, `2026-08-20-slice-3-fatturazione.md`, `2026-08-20-slice-4-time-tracking-e-pl.md` and `2026-08-20-slice-5-gmail-e-landing.md` that still applies is carried here with its exact values.

### Carried from plan 1A (backend)

- **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Managed by **uv workspaces**. Do not use pip, poetry, or venv directly.
- **`packages/core` must never import from `apps.`** — enforced by `packages/core/tests/test_architecture.py`. That test is an *allowlist*: core may import the stdlib, the `pigrocrm` namespace, and only what `packages/core/pyproject.toml` declares under `[project].dependencies`. If a task seems to require anything else, either declare the dependency there or the design is wrong; stop and flag it.
- **Services receive and return Pydantic models only.** No `Request`, `Response`, `HTTPException`, or status codes inside `packages/core`.
- **Every service method that writes takes `actor: Actor`** as an explicit parameter. Never read the actor from global or contextual state.
- **One service method = one transaction. The service commits; repositories never commit.**
- **Money is `Numeric(12, 2)`; hours are `Numeric(8, 2)`; factors — every hourly rate and internal cost — are `Numeric(12, 6)`.** Never `Float` for any of the three.
- **All timestamps are `TIMESTAMP WITH TIME ZONE` in UTC.** Use `from datetime import UTC, datetime` → `datetime.now(UTC)`, matching `db/base.py`. Never `datetime.utcnow()`.
- **All primary keys are UUIDv7** via the shared `pigrocrm.core.db.base.uuid7` wrapper, stored as native `UUID`. Never `uuid_utils` directly in a model.
- **Soft delete**: entities carry `deleted_at`. Repository queries filter `deleted_at IS NULL` unless explicitly asked otherwise. No physical delete exists anywhere in this slice either.
- **Tests use real PostgreSQL via testcontainers. Never SQLite** — JSONB, GIN indexes and `pg_trgm` do not exist there. Use the existing `db_engine`/`db_session` fixtures in `packages/core/tests/conftest.py`.
- **TDD is mandatory for `packages/core`.** Write the failing test, watch it fail, then implement.
- **Commit after every task**, using the message given in the task's final step.
- **UI language is Italian.** Field labels, buttons, and error messages shown to users are Italian. Code identifiers, table names and column names are English except the Italian fiscal and domain terms already fixed in slices 1–4 (`partita_iva`, `codice_fiscale`, `codice_sdi`, `pec`, `ragione_sociale`, `indirizzo`, `cap`, `comune`, `provincia`, `nazione`, `tipo`, `titolo`, `stato`, `versione_corrente`, `numero`, `sorgente_markdown`, `variabili`, `variabili_dichiarate`, `corpo_markdown`, `attivo`, `creato_da`, `dimensione`, `anno`, `riferimento`, `data_emissione`, `data_scadenza`, `imponibile`, `imposta`, `bollo`, `totale`, `causale`, `stato_pagamento`, `data_incasso`, `ore`, `data`, `importo`, `descrizione`, `fatturabile`, `tariffa_applicata`, `costo_applicato`, `ricavi`, `costi_diretti`, `costo_lavoro`, `margine_lordo`, `margine_percentuale`, `valore_maturato`, `chiuso_il`, `chiuso_da`) and the ones **this** slice fixes: `chiuso_il` (on `deals`), `stato_dal`, `posizione`, `punteggio`, `calcolato_alle`, `periodo`, `valore_ponderato`, `tasso_conversione`, `senza_valore`, `regola`, `motivo`, `attivata_da`, and the four `motivo` values `stage_bersaglio_assente` / `stage_bersaglio_ambiguo` / `gia_nello_stato` / `regola_disattivata`.
- **The `Expected: PASS (N passed)` counts are indicative, not contractual.** Parametrised tests expand to different totals than the number of test functions. What matters is that every test passes and none is skipped — a differing total is not a failure and must not be "fixed" by deleting or merging cases.
- **A uniqueness pre-check never replaces the database constraint.** Wherever a service does "SELECT to check, then INSERT", it must also catch `sqlalchemy.exc.IntegrityError` around the commit, `session.rollback()`, and re-raise the domain `Conflict`. Two concurrent requests both pass the SELECT; only the constraint stops the second, and without the rollback the caller's session is left poisoned (`PendingRollbackError` on its next statement).
- **Case-insensitive uniqueness needs a functional index, not a convention.** Where identity is case-insensitive, declare `Index("uq_…", func.lower(col), unique=True)` in `__table_args__`.
- **A method named `list` must be the LAST method defined in its class.** `def list(...)` rebinds `list` in the *class* namespace, so any later method annotated `-> list[Something]` resolves it to that method and raises `TypeError: 'function' object is not subscriptable` **at import time**. Python 3.13 evaluates annotations eagerly, so this is a hard failure here; 3.14's PEP 649 would hide it. Calling `self.list()` from an earlier method is fine — that is a call-time attribute lookup, not an annotation. The rule is unconditional: do not reason about whether a later method *currently* returns a `list[...]`. `packages/core/tests/test_module_imports.py` is the real guard; keep it green.
- **Every `Numeric(p, s)` column needs a matching Pydantic `Field(max_digits=p, decimal_places=s)`** on both schemas. Without it a value beyond the column's capacity reaches Postgres as `NumericValueOutOfRange` — an uncaught `DataError`, not an `IntegrityError` subclass, so no existing handler catches it and the session is poisoned — and a sub-scale value like `Decimal("0.005")` is silently rounded by the database while `expire_on_commit=False` (`db/session.py`) leaves the object returned to the caller still reporting the original. **Reject rather than round.**
- **Every `String(n)` column needs a matching Pydantic `max_length=n`** on both the Create and the Update schema. Without it an over-long value reaches Postgres, raises `sqlalchemy.exc.DataError` — **not** an `IntegrityError` subclass — and poisons the caller's session.
- **`re.fullmatch`, never `re.match` with `$`.** Python's `$` matches before a trailing newline, so `^\d{11}$` accepts a 12-character string and the value still reaches the database. **This applies to every regex in this slice, database-bound or not** — the fiscal-number shape of §8.1, the `sort`/`dir` whitelist checks, the cursor decoder, the CSS token tests. The habit is what protects the ones that are.
- **Every `Integer` column needs a bounded Pydantic field** (`Field(ge=…, le=…)`) on both schemas, picked to be defensible for that field's meaning. Without a bound a value like `2**40` reaches Postgres raw as `IntegerOutOfRange`. **Exception, not violation**: a field already fully bounded by an equivalent service-level range check does not also need a schema-level bound — adding one changes which exception type fires (`pydantic.ValidationError` instead of this project's own `ValidationFailed`) for a same-shaped value the service already rejects correctly. Document any omission in a comment.
- **A NUL byte (`"\x00"`) in a native `String`/`Text` field is rejected, not stored.** Use `pigrocrm.core.validation.SafeStr` on every user-supplied string field on every Create/Update schema and on every free-text query parameter, including inside `list[str]` fields. Reject, never strip. A field that structurally cannot carry a NUL byte through does not need `SafeStr` layered on top — document why rather than adding a check that can be shown never to fire.
- **Every foreign key column is validated against the table it references, in both `create` and `update`**, including an optional (nullable) one — a nullable FK is skipped only when the caller supplies nothing, never when the caller supplies a value. Without this any syntactically valid UUID reaches `flush()`/`commit()` and comes back as a raw `IntegrityError` (`ForeignKeyViolation`) instead of this project's own `NotFound`.
- **Escape LIKE metacharacters in every search filter.** Use the shared `pigrocrm.core.db.escape_like` helper, escape `\`, `%` and `_` (backslash first), and pass `escape="\\"` — **unless Task A2's `EXPLAIN` measurement says otherwise**, in which case that task removes the clause everywhere at once and records the measurement. Never remove it in one call site only.
- **Pagination `limit` must be bounded** — `Field(ge=1, le=200)` on the query schema, not only on the router.
- **On update, validate only the custom-field keys the caller supplies**, not the merge of stored and supplied. A supplied key with value `None` removes that entry — and must work even when its definition is archived, no longer exists, or is optional. It must **not** work when the key's current definition is active and `required=True`. Untouched stored keys pass through unchanged, archived ones included. *(No task in this slice writes a custom field; carried so no task introduces one that skips it.)*
- **A column holding a closed set is declared wider than that set, never exactly as wide.** `String(20)` for a set whose longest legal value is 8 characters, not `String(8)`. Sized exactly, the column width rejects an illegal value *before* the `CHECK` constraint beside it can, and Postgres answers with a raw `StringDataRightTruncation` — a `DataError`, not an `IntegrityError`, so no handler catches it and the session is poisoned — instead of the named violation the `CHECK` exists to produce. This cost slice 3 a real defect on `invoices.tipo`; in this slice it governs `automation_config`'s columns and every `motivo`/`regola` value.
- **Every schema object is reachable from `Base.metadata`.** An index, a constraint or a sequence declared only as raw `op.execute(...)` in a migration exists in production and is **absent under test**, because `packages/core/tests/conftest.py` builds the schema with `Base.metadata.create_all` and runs no migration. This cost slice 3 a real defect on `proforma_riferimento_seq`. Declare it in `__table_args__` (or as a `Sequence(..., metadata=Base.metadata)`) and let the migration mirror it; `test_migrations_produce_exactly_the_models_schema` is what then keeps the two honest.
- **Errors are RFC 9457 problem details with structured `details`.** Raise `pigrocrm.core.errors.{NotFound, ValidationFailed, Conflict, PermissionDenied, ImmutableField}` and never a pre-formatted sentence; `apps/api/src/pigrocrm_api/errors.py::domain_error_handler` renders them. `ValidationFailed(entity, field, reason, expected=…)` must always name the real offending field, because both `fieldErrorFrom` in the web client and an MCP agent read `field`. **There is no class called `ValidationError` in this codebase.**

### Carried from plan 1B (frontend)

- **No `fetch` inside components.** Every request goes through the generated client wrapped in TanStack Query hooks. The two standing exceptions already in the codebase are multipart upload and blob download, which `openapi-fetch` cannot express (`features/documents/queries.ts`); **this slice adds no third exception** — every request it makes is a plain `GET` or `PUT` that `openapi-fetch` expresses natively.
- **The API client is generated, never handwritten.** `openapi-typescript` reads `openapi.json` from the running API (`pnpm generate:api`). A contract change must break `tsc`, not production.
- **No business logic in the frontend. Validation lives in the backend.** Validation messages come from the API's problem documents. Recomputing a rule client-side is how the three interfaces start disagreeing.
- **No component file over ~250 lines.** If a file approaches the limit, extract.
- **UI language is Italian.** Every visible label, button and message.
- **TypeScript strict mode**, no `any`, no `@ts-ignore`. **`tsconfig.json` has `noUncheckedIndexedAccess`, `noUnusedLocals` and `noUnusedParameters` on**, and `build` is `vite build && tsc --noEmit`. Indexing an array or a `Record` yields `T | undefined` and must be narrowed.
- **Form state keeps `{native, custom}` as two namespaces, decided once at seed time and never re-derived at submit.** The split lives in the *feature's* form component (`CustomerForm.tsx`, `DealForm.tsx`), **not** in `DynamicForm`, which is a controlled flat renderer taking one merged `values` object. Provenance is structural. A native column clears on `""` and only on `""`; a custom field clears on `null` and only on `null`; an omitted key clears nothing; an archived custom key is omitted entirely so the server carries the stored value over. **`0` and `false` are values, never blanks** — mirror the shipped `isBlank` in `CustomerForm.tsx` exactly, which is itself a mirror of `fields/validator.py::is_blank`. *(This slice adds no form with custom fields; carried so no task invents a third namespace.)*
- **`DynamicForm` takes a required, undefaulted `mode: 'create' | 'edit'` prop.** Its props are exactly `{ fields, values, onChange, problem?, mode }`. Every new call site answers the question explicitly.
- **Never sum money as a JS float.** `Numeric` columns arrive as strings in the generated types; format them with `Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', useGrouping: 'always' })` and, where a sum is unavoidable, add integer cents parsed by splitting the string on `.` — `Number("0.29") * 100` is `28.999999999999996`. The shipped exemplar is `apps/web/src/features/deals/columns.tsx`, whose `centsFromDecimalString` is **private to that module**: the codebase's stated precedent is a small per-feature display helper, not a shared module. **In this slice no sum is unavoidable** — every total arrives already summed — so no dashboard module carries such a helper at all, and Task B16's AST test is what proves it.
- **A failed request must never look like an empty result.** A query in `isError` renders `QueryErrorBanner` (`apps/web/src/components/QueryErrorBanner.tsx`, props `{ error: unknown }`), never an empty table or an empty list. `DataTable` already does this internally when `isError && data.length === 0`. In this slice the rule has a second, sharper form: see "New to slice 6" below.
- **`DataTable` is TanStack Table v9** (`@tanstack/react-table 9.0.0`): `tableFeatures({})` + `useTable({ features, columns, data })`, `ColumnDef<DataTableFeatures, T>` with the feature type parameter **first**, `row.getAllCells()`, and rendering through the table-bound `<table.FlexRender header={…} />` / `<table.FlexRender cell={…} />`. There is no `useReactTable`, no `getCoreRowModel`, no `getVisibleCells` and no standalone `flexRender()` in v9, and `useLegacyTable` is `@deprecated` — do not reach for it. Its props are exactly `{ columns, data, isLoading?, isError?, error?, onRowClick?, emptyMessage? }`.
- **`unwrap` throws the `ProblemDetail` object itself**, not an `Error` and not a `Response`. A form-level failure goes to `setProblem(toProblem(error))`; a page-level action's failure goes to `toast.error(...)` from `sonner`. `toProblem` is idempotent on an already-normalised problem.
- **A hook must never be called with an empty id.** Make the row conditional, or give the hook a discriminated argument with no "empty string" spelling to get wrong, or carry an `enabled:` guard — and ship a test for it (residuo B1). All three remedies are established precedent; pick one and test it.
- **A new module that exports both a component and a non-component needs its own `react-refresh/only-export-components` override in `apps/web/eslint.config.js`**, with `allowExportNames`. Every shipped form and every detail route already has one; without it `pnpm lint` fails.
- **`Intl.NumberFormat('it-IT')` always takes `useGrouping: 'always'`.** it-IT's default withholds the thousands separator until the integer part has five digits (`Intl.NumberFormat('it-IT').format(2500.5)` → `"2500,50"`), so a four-figure total silently loses its separator without it.
- **`new Date("YYYY-MM-DD")` parses as UTC midnight.** Formatting it with `Intl.DateTimeFormat` renders in the browser's zone, so anywhere behind UTC the date loses a day. Build the `Date` from its year/month/day parts in local time (`new Date(year, month - 1, day)`).
- **Commit after every task.**

### Carried from plan 2

- **No user input ever reaches a command line.** `subprocess.run` is always called with an argument *list*, never a string, never `shell=True`. This slice adds no new subprocess call; the constraint stands so that no task introduces one.
- **Escaping is decided by context, never by a single pass.** No function may escape a value without being told which context it is escaping for. This slice adds no escaping context; the only text it prepares is Markdown for an MCP prompt, and it goes through `templates/escaping.py`'s existing `"markdown"` context.
- **No new Python dependency is added to `packages/core`.** Everything this slice needs is stdlib (`ast`, `base64`, `json`, `zoneinfo`) or already declared.

### Carried from plans 3 and 4

- **`ROUND_HALF_UP`, per row, then sum the already-rounded rows.** An aggregate is `Σ ROUND(row, 2)`, never `ROUND(Σ exact, 2)`. Half-up, not half-even: Italian fiscal practice.
- **No `float`, anywhere, in any language.** `Decimal` in the service, `Numeric` in Postgres, totals computed by the service and returned already summed.
- **A date that decides which period a figure falls in is `Date`, never `timestamptz`.** `invoices.data_emissione`, `costs.data`, `time_entries.data` and — new here — `deals.chiuso_il` and `documents.stato_dal`. A `toISOString()` projection moves everything after 23:00 CET by a day and everything on 31 December by a year.
- **Revenue is `Σ invoices.imponibile`** over `tipo='fattura'`, `stato='emessa'`, `deleted_at IS NULL`, attributed to the period by `data_emissione`. Not `totale`. **This slice introduces no third meaning** and no task may compute it.
- **The deal is the P&L unit; overhead is never apportioned; a rate freezes onto the row; a period can be closed.** These are settled by slice 4 §7.1, §7.4, §5.1 and §6.4. A third meaning for any of them is a defect, and no task in this plan restates or recomputes them.
- **Every change to a rate column, a cost category, a fiscal parameter or — new here — the automation configuration writes an activity.** R5 stays open in general; it closes here for `automation_config`.

### New to slice 6

- **No figure is born in `core/dashboard/`.** Every figure on a dashboard is either (1) returned verbatim by the service that owns the data, with the same name and the same value, or (2) a single `COUNT` or `SUM` over rows of one table, written in **that table's** repository — even when the table belongs to another slice. A `COUNT` may cross a join; a `SUM` may not. There is no third form, and the only two exceptions are the weighted pipeline value and the conversion rate, both in `deals/repository.py`, both combining only columns of `deals`, neither of them money received. Task B12 makes this a fact of the build: no module under `core/dashboard/` may import `Decimal`, and none may contain a `BinOp` node with `*`, `/` or `-`, with an exceptions list that is **empty**.
- **One dashboard is one endpoint, one transaction, and one instant, in `REPEATABLE READ`.** Not one endpoint per card. `READ COMMITTED` — Postgres's default, and therefore what you get by saying nothing — takes a fresh snapshot **per statement**, so six queries in one transaction can see six states exactly as six transactions can. The transaction is read-only, so the usual price of the higher level is not paid: a serialisation failure can only strike a writer, and nothing here writes.
- **No dashboard writes anything.** There is no state to repair, no reconciliation, and no "recompute the totals" button that does anything but re-read.
- **A card and its drill-through are the same predicate, not two calculations.** If the two numbers differ, the difference is the age of the cached dashboard response, the list wins, and the card refreshes.
- **No materialised summary, no server-side cache, no `dashboard_summary` table, no materialised view.** A materialised total is the second source of truth made permanent, and the project has no worker process to refresh it (slice 5 §4.5, §10).
- **`staleTime` for a dashboard query is 60 seconds** — a deliberate override of the 30 000 ms default in `apps/web/src/lib/query.ts` — and the response's age is shown on screen, derived from `calcolato_alle`.
- **An automation that cannot run inside its trigger's transaction does not become an automation. It becomes a dashboard signal.** "Fatturato ma non vinto" is that signal.
- **A service may expose a `*_in_transaction(...)` method that mutates, does not record, does not commit, and does not check authorisation. Task B5's architecture test verifies that such methods are called only from `core/automations/`.**
- **A search that returns partial results without saying so is worse than no search.** The palette has **three** distinct renderings — no results, truncated results with the real count, search unavailable — plus a fourth non-error state below three characters. An empty list drawn after an error says "there is none" when the truth is "I do not know", and Task A14 asserts that the string `Nessun risultato` is **absent from the DOM** in the error state.
- **The global search requires at least 3 characters and issues no request below that threshold.** A trigram index cannot serve a pattern from which no trigram can be extracted; a two-character term on 50 000 customers returns thousands of rows, which is not an answer either.
- **No total is computed in the browser, not even visible hours.** Task B16 ships the AST test that fails the build if a dashboard module applies `Number()`, `parseFloat` or `+` to an economic field coming from the API.
- **No charting library.** Four shapes — big numbers, horizontal bars as CSS widths, one sparkline, one table — as inline SVG and CSS. `apps/web/src/styles/tokens.css` stays the single source of colour: the five `--chart-1…5` tokens are `color-mix()` derivations of the five existing tints, no raw hexadecimal appears in the block, and every chart has an equivalent table because a chart without a table is a figure a screen reader does not read.
- **No new MCP resource.** A resource is addressed by a URI; a dashboard is a question with a period. The existing `customer://`, `person://` and `deal://` stay the way to make an agent **read** before it **acts**.

### Pinned versions

Backend (unchanged): `fastapi 0.141.1` · `uvicorn 0.52.1` · `sqlalchemy 2.0.51` · `alembic 1.19.0` · `psycopg[binary] 3.3.4` · `pydantic 2.13.4` · `pydantic-settings 2.14.2` · `email-validator 2.3.0` · `argon2-cffi 25.1.0` · `pyjwt[crypto] 2.13.0` · `mcp 2.0.0` · `uuid-utils 0.17.0` · `pytest 9.1.1` · `pytest-cov 7.1.0` · `pytest-asyncio 1.4.0` · `testcontainers[postgres] 4.15.0` · `httpx 0.28.1` · `ruff 0.16.1` · `mypy 2.3.0`. **No new backend dependency.**

Frontend (unchanged): `vite 8.2.0` · `react 19.2.8` · `react-dom 19.2.8` · `typescript 5.9` (**not** 7.x) · `@tanstack/react-router 1.170.20` · `@tanstack/router-plugin 1.168.25` · `@tanstack/react-query 5.101.4` · `@tanstack/react-table 9.0.0` · `tailwindcss 4.3.3` · `@tailwindcss/vite 4.3.3` · `@dnd-kit/core 6.3.1` · `openapi-typescript 7.13.0` · `openapi-fetch 0.17.0` · `@playwright/test 1.62.1` · `vitest 4.1.10` · `sonner 2.0.7`. Package manager **pnpm 10.12.4**.

**New to this slice:** `cmdk` — added with `pnpm add cmdk` in Task A13, and whatever version that resolves is pinned into `apps/web/package.json` in the same commit, the convention this repo already uses for `lucide-react`. It is the only new dependency in the slice, front or back.

### Design tokens (exact values — do not improvise)

| Token | Hex | Role |
|---|---|---|
| Watermelon | `#ed254e` | brand accent, borders, icons, focus ring. **Never a solid fill under white text** |
| Watermelon strong | `#e5133e` | every solid fill that carries white text (4.673:1) |
| Royal Gold | `#f9dc5c` | warning, attention |
| Mint Cream | `#f4fffd` | app background (light) |
| Prussian Blue | `#011936` | foreground text, dark surface |
| Charcoal Blue | `#465362` | muted / secondary text |

The five chart tokens, all derived, none new (Task B16):

| Token | Expression |
|---|---|
| `--chart-1` | `color-mix(in oklab, var(--color-watermelon) 78%, #ffffff)` |
| `--chart-2` | `color-mix(in oklab, var(--color-prussian-blue) 72%, #ffffff)` |
| `--chart-3` | `color-mix(in oklab, var(--color-royal-gold) 82%, var(--color-charcoal-blue))` |
| `--chart-4` | `color-mix(in oklab, var(--color-charcoal-blue) 84%, #ffffff)` |
| `--chart-5` | `color-mix(in oklab, var(--color-watermelon) 40%, var(--color-prussian-blue))` |

`#ffffff` is the one literal permitted inside a `color-mix()` — it is the neutral being mixed toward, not a sixth tint, and Task B16's no-raw-hex test allows exactly that token and no other.

### Test and verification commands

Nothing in this plan invents a command. These are the ones `.github/workflows/ci-deploy.yml` runs:

| What | Command |
|---|---|
| One backend test | `uv run pytest packages/core/tests/test_x.py::test_name -v` |
| Backend suite gate | `uv run pytest -q` (testcontainers starts PostgreSQL itself; no service container) |
| Lint | `uv run ruff check . && uv run ruff format --check .` |
| Type check | `uv run mypy packages/core/src apps/api/src apps/mcp/src` |
| Frontend unit tests | `cd apps/web && pnpm exec vitest run src/path/to/file.test.tsx` |
| Frontend typecheck | `cd apps/web && pnpm exec tsc --noEmit` (or `pnpm build`, which is `vite build && tsc --noEmit`) |
| Frontend lint | `cd apps/web && pnpm lint` |
| E2E | `cd apps/web && pnpm test:e2e` (which is `bash scripts/e2e.sh`) |
| Regenerate the API client | API running on `:8000`, then `cd apps/web && pnpm generate:api` |

**There is no `pnpm test` script.** Slice 3's Global Constraints state this explicitly and it is still true of `apps/web/package.json`: unit tests run as `pnpm exec vitest run`, end-to-end as `pnpm test:e2e`. CI's own `frontend` job happens to spell the same thing `pnpm vitest run`; either resolves, but the tasks below use the `pnpm exec` form, which is the documented one.

**Commit convention.** Conventional Commits, `type(scope): lowercase imperative summary`, no body, no trailer. `git add` takes the explicit paths the task touched, never `-A` and never `.`. The scopes in use across the 136 commits of the six earlier plans are `web`, `api`, `mcp`, `core`, plus one per domain package; this slice uses `search`, `dashboard`, `automations`, `web`, `api`, `mcp` and `core`. Every task below gives the exact command.

**One version flag, carried so nobody reintroduces a regression.** Slice 2's plan pinned `PANDOC_VERSION=3.1.12.2` / `TYPST_VERSION=0.11.0`; slice 3's plan records that the values actually shipped are `PANDOC_VERSION=3.8.2.1` / `TYPST_VERSION=0.14.2`, and slice 4's plan then reverted to the stale pair in its own text. **Slice 3's values are the shipped ones.** This slice renders nothing and must not touch `Dockerfile.api` — the note exists only so that no task "helpfully" aligns a version table with the wrong plan.

**One environment note that has cost two agents real time.** `docs/superpowers/plans/2026-08-20-slice-3-fatturazione.md` contains exactly one NUL byte, so BSD `grep` on macOS classifies it as binary and prints **nothing at all** — `grep -c "" ` on it returns empty. An empty result on that file means "output suppressed", not "no match". Pass `-a`, or search it with `python3`. Every other file under `docs/superpowers/` is clean; verified by counting `b"\x00"` in all fifteen.

---

## Contradictions between the spec and the shipped code, and how they were resolved

Resolved **in favour of the shipped code**, as instructed. Each was verified against the tree, not taken from the spec's own list — and the spec's list turned out to be incomplete in eight places.

1. **The spec's `sort` whitelist names `creato_il` and `aggiornato_il`; the shipped columns are `created_at` and `updated_at`.** §8.4 lists the whitelist as "`creato_il`, `aggiornato_il`, e la colonna identificativa", and §8.5's second sort key is `aggiornato_il DESC`. `packages/core/src/pigrocrm/core/db/base.py`'s `TimestampMixin` declares `created_at` and `updated_at`, and all four `*Read` schemas expose them under those names (`customers/schemas.py:116-117`, `people/schemas.py:103-104`, `deals/schemas.py:122-123`, `documents/schemas.py:80-81`). **Resolution (Tasks A3, A8):** the whitelist values are `created_at` and `updated_at`, and §8.5's second key is `updated_at DESC`. Renaming the columns would touch four `*Read` schemas, the generated client and every call site, and the Global Constraints rule is that identifiers are English except the named Italian fiscal and domain terms — `created_at`/`updated_at` are not among them. The spec's substantive requirement (sort by creation, by last touch, and by the identifying column) holds exactly; its spelling does not.

2. **The spec calls the analytics methods `get_period_pnl` / `get_deal_pnl` / `get_budget_vs_actual`; slice 4's approved plan names them `period_pnl` / `deal_pnl` / `budget_vs_actual`.** `docs/superpowers/plans/2026-08-20-slice-4-time-tracking-e-pl.md:10986-10992` defines `AnalyticsService.deal_pnl(self, deal_id: UUID, actor: Actor) -> DealPnl`, `period_pnl(self, query: PeriodPnlQuery, actor: Actor) -> PeriodPnl` and `budget_vs_actual(self, query: BudgetQuery, actor: Actor) -> BudgetPage`; `get_period_pnl` and friends are the **MCP tool** names (same file, lines 13444-13495). Slice 4's spec gives no Python signature at all — only the tool names in its §11 table — so there is nothing in the spec for the plan to contradict. **Resolution (Tasks C1, C4):** call the service methods by their slice-4 names and take `PeriodPnlQuery(da=…, a=…, customer_id=None)`; the new method added here is `AnalyticsService.unbilled_backlog(actor)` and its MCP tool is `get_unbilled_backlog`, which is the name the spec §11.1 fixes. This keeps the spec's "the exclusion list stays exactly its ten names" true: `unbilled_backlog` is a public method with a tool.

3. **The spec calls three period figures "righe informative di `get_period_pnl`"; slice 4's `PeriodPnl` does not carry them.** §5's table sources "valore maturato non fatturato · ore fatturabili non fatturate · ore senza tariffa" from `get_period_pnl`. Slice 4's plan (line 11363) defines `PeriodPnl` as `da, a, customer_id, chiusi, in_corso, spese_generali, periodo_chiuso, voci_scritte_in_ritardo`, with `PnlTotals` as `ricavi, costi_diretti, costo_lavoro, margine_lordo, margine_percentuale, deal`. The three names live only on `DealPnl`. **Resolution (Task C4):** `AnalyticsService` — the service that owns the formula — gains the three fields on `PeriodPnl`: `valore_maturato: Decimal`, `ore_fatturabili_non_fatturate: Decimal`, `ore_senza_tariffa: int`. §3 permits exactly this ("se un numero del genere serve, appartiene al servizio che possiede i dati da cui deriva, e va aggiunto là") and forbids the alternative, which would be `DashboardService` multiplying hours by a rate. Adding *fields* triggers no architecture-test clause; adding a public *method* would. The names are the same as `DealPnl`'s because they are the same quantity on a different object; §5's requirement is that the **label** carries the scope — "nel periodo" on the economic dashboard, "in totale" on the operational one — and the two are never shown side by side.

4. **The spec sources "Da incassare" from `InvoiceService`; §3 rule 2 puts a single-table `SUM` in that table's repository.** §5's table says "`InvoiceService`: `Σ totale` su …". **Resolution (Task C3):** the three aggregates live in `InvoiceRepository` (`sum_da_incassare`, `sum_scaduto`, `count_emesse_in_periodo`) and `DashboardService` calls the repository directly, exactly as §3 rule 2 anticipates for a table belonging to another slice. Adding a public method to `InvoiceService` would force either a new MCP tool or an edit to slice 3 §11's exclusion list, which that spec fixes at **exactly** `issue_invoice`, `annul_invoice`, `mark_transmitted_externally`, `update_fiscal_profile`. §3 is the governing rule; §5's row is prose about provenance, and the provenance is unchanged.

5. **The spec says criterion 14 "extends the AST test slice 4 §14.4 has already written". No such test exists.** Slice 4 is not implemented: `apps/web/` has no source-reading test other than `src/styles/tokens.test.ts`, which is a regex-and-arithmetic test over `tokens.css`, not an AST test. `Number()` is used today in five shipped modules (`features/settings/FieldsPanel.tsx:172`, `features/settings/PipelinePanel.tsx:72`, `features/deals/columns.tsx:51,61,134`, `components/DynamicFieldRenderer.tsx:254,256`, `routes/app/clienti/$customerId.tsx:49`). **Resolution (Task B16):** this slice **creates** the test rather than extending it, scoped to `apps/web/src/features/dashboard/**` and `apps/web/src/routes/app/index.tsx`, with the five existing call sites explicitly out of scope and named in the test's own docstring — they coerce a position, a probability and a form input, none of which is an economic field from a dashboard response. If slice 4 lands first and ships a wider guard, this test's scope is subsumed and the narrower file may be deleted; the task says so.

6. **The spec lists "l'app servita sotto `/app/`" as a slice 5 prerequisite. Half of it is already shipped.** `apps/web/src/routes/app.tsx` already makes `/app` a real path and `apps/web/src/routes/index.tsx` already redirects `/` there; every nav link in `AppShell.tsx` is already `/app/...`. What is *not* shipped is Vite's `base: '/app/'` and the nginx form of slice 5 §9.4 — `deploy/nginx/spa.conf` still serves the SPA from the root. **Resolution:** every route this plan writes is spelled `/app/...`, which is correct both before and after slice 5, and **6C's dependency on slice 5 is dropped**. Nothing in this slice needs `base` to change; nothing in this slice touches `spa.conf`.

7. **The spec lists "A14 chiuso (`exclude_unset=True`)" as a prerequisite. A14 is open, and this slice does not need it.** `exclude_unset` appears nowhere in the repository; every service still uses `model_dump(exclude_none=True, exclude={"custom_fields"})`. The spec's stated reason for the prerequisite is that "la ricerca aggiunge parametri di ordinamento a schemi di lista" and a half-migrated update contract is a bad time to touch them. **Resolution:** 6A adds `sort`, `dir` and a re-typed `cursor` to the four `*ListQuery` schemas and to nothing else — **no `*Update` schema is touched anywhere in this slice**, so the risk the prerequisite names does not arise. A14 is neither waited on nor closed here. Recorded so nobody blocks 6A on it.

8. **The spec lists "una sessione per chiamata sul server MCP (cura di R1)" as done. It is not done.** `apps/mcp/src/pigrocrm_mcp/__main__.py:22-32` still builds one `Session` and passes `lambda: session` to `build_server`; `server.py:55-64` documents the choice in place. The only mitigation is `_guard`'s unconditional `context.session.rollback()`. **Resolution:** the spec's own §11.3 is honoured literally — this slice depends on the cure and does not work around it. **6C cannot start until the R1 cure is in `main`**, and 6C's MCP tasks (C8, C9, C11) must not register a dashboard tool before then: a dashboard tool on a shared session is not a degraded feature, it is a wrong figure. 6A's `search_everything` and 6B's tools are in the same position and inherit the same gate — which is why **the whole of 6C**, and only 6C, carries the R1 prerequisite in its header, while 6A and 6B register their tools too. That is the one place this plan is stricter than the spec: **Task A11 and Task B15 each end with a check that the R1 cure is in `main`, and if it is not, they ship the API half and leave the MCP half to the first task of 6C.** The reason is the spec's own: aggregation in read widens the window in which two calls overlap.

9. **`DocumentRepository.list` has no search branch, and `DocumentListQuery` has no `search` field.** §8.1 requires `documents.titolo` to be searchable and §8.5's "vedi tutti" lands on the documents list filtered by the same term. `documents/repository.py:53-68` has `customer_id`, `deal_id`, `tipo`, `stato`, `cursor` and no `ilike` anywhere. **Resolution (Task A7):** 6A adds it, with the same `escape_like` shape the other three use. The spec assumed it existed.

10. **There is no timezone mechanism to reuse.** §4.1 requires the calendar-day computation for `chiuso_il` to use "lo stesso meccanismo di fuso che lo slice 3 §6.2 impone a `data_emissione`, non un secondo". Slice 3 §6.2 imposes a **rule** — a `date` is not an instant, never project a `timestamptz` through `toISOString()` — not a mechanism; for an invoice, `data_emissione` is supplied by the caller and validated, never derived from "now". `Settings` (`packages/core/src/pigrocrm/core/config.py`) has no timezone field, and `zoneinfo` is not imported anywhere in core. **Resolution (Task B1):** introduce the mechanism once, here — `Settings.timezone: str = "Europe/Rome"` and a single `pigrocrm.core.db.clock.today_local(settings)` using stdlib `zoneinfo` — and state in its docstring that it is the project's only clock, so that slice 3's `data_emissione` validation adopts it rather than growing a second one. One clock, introduced once, is exactly what §4.1 asks for; the spec's mistake is only about which slice introduces it.

11. **`invoices` exists now; `InvoiceService` does not.** Verified in the tree rather than in slice 3's plan text, and it changed while this plan was being written: `packages/core/src/pigrocrm/core/invoices/` now ships `models.py` (`Invoice`, `InvoiceLine`, `InvoiceCounter`), `fatturapa.py`, `naming.py`, `schemas.py` and `totals.py`, `packages/core/src/pigrocrm/core/fiscal/` ships the full `models`/`repository`/`service` set, and the migration chain runs to `0005_invoices.py`. What is still absent is `invoices/repository.py` and `invoices/service.py` — eight of slice 3's twenty-one tasks are merged, not all of them. `packages/core/src/pigrocrm/core/timetracking/` and `analytics/` do not exist at all, so slice 4 is entirely absent. **Resolution, in two parts.** (a) Task C3's aggregates go in a **new** `invoices/repository.py` if slice 3 has still not created one when 6C starts, and are **appended** to it if it has — the file is slice 3's to own, and this task adds methods to it rather than a parallel module. (b) The invoice search branch of §8.1 stays in **Task C13**, not in 6A. The tables now exist, so the branch is technically buildable in 6A, and it is still deferred on purpose: spec §17 fixes 6A's dependency set as slices 1 and 2, and pulling in a fifth branch would make 6A un-releasable if slice 3 were rolled back. C13's only real precondition is the `Invoice` model, which is satisfied today — so it may be executed as soon as 6A is merged, ahead of the rest of 6C, and its task header says so.

12. **Two defect precedents from slice 3, carried because this plan defines columns and could repeat either.** Both were fixed in `invoices` days ago and both are shapes this slice's own migrations could reproduce. (a) `invoices.tipo` shipped as `String(10)`, exactly wide enough for its legal values `fattura` and `proforma` — so a longer *wrong* value hit the column width first and Postgres answered with a raw `StringDataRightTruncation` instead of the named `CHECK` violation sitting next to it. It is now `String(20)`. **A column sized exactly to its closed set makes the `CHECK` beside it unreachable**, and this slice's `automation_config` and the `motivo` values of Task B6 are exactly that shape. (b) `proforma_riferimento_seq` was declared only as raw `op.execute("CREATE SEQUENCE …")` in the migration, so it existed in production and was **absent under test**, because `packages/core/tests/conftest.py` builds the schema with `Base.metadata.create_all` and never runs a migration. It is now `Sequence(PROFORMA_SEQUENCE_NAME, start=1, increment=1, metadata=Base.metadata)` in `invoices/models.py`. **Any schema object this slice adds must be reachable from `Base.metadata`**, which for the indexes of Tasks A2, A3 and B2 means declaring them in `__table_args__` and letting the migration mirror them — the order those tasks already follow, and now the reason is on the record.

13. **`pipeline_stages` has `code`, and it has no uniqueness constraint on `tipo`.** Both matter and both check out: `pipeline/models.py` declares `code: Mapped[str | None] = mapped_column(String(30), default=None)` with `Index("uq_pipeline_stage_code", "code", unique=True)`, and `DEFAULT_STAGES` in `pipeline/service.py:18-25` seeds `code='offerta'` (`tipo='open'`) and `code='vinto'` (`tipo='won'`) — the two the automations resolve by. Nothing forbids two stages with `tipo='won'` (**R14**). The core design §5.4 still does not mention `code` (**R11**). **Resolution (Task B6):** A1 resolves by `code='vinto'`, then falls back to the unique stage with `tipo='won'`, then does nothing and records `motivo='stage_bersaglio_ambiguo'` or `'stage_bersaglio_assente'`. A2 resolves by `code='offerta'` **only** — there is no `tipo` fallback, because "Offerta" is `open` like every other open stage. No migration adds a constraint: it would refuse data an installation may already have for a reason. R11 and R14 stay open and are not closed by this plan.

14. **The timeline records stage changes by user-renamable name (R15), and this plan does not fix it.** `deals/service.py:236-238` writes `{"from": previous.nome, "to": target.nome}`. **Resolution (Task B2):** `deals.chiuso_il` is the new authoritative column and is **not** backfilled; the dashboards exclude `chiuso_il IS NULL` from period figures and declare how many rows they excluded. `documents.stato_dal` **is** backfilled, because the offer timeline's payload is `{"da": "inviata", "a": "accettata"}` — literals of `OfferState`, not user text (`documents/service.py:544-546`). Enriching the `stage_changed` payload with the stage id and `code` is the right fix for R15 and is **out of scope here**: it would not make the timeline authoritative (the payload is sanitised, not validated), and this plan already gives the question a column that is.

15. **The exception type is `ValidationFailed`, not `ValidationError`.** `packages/core/src/pigrocrm/core/errors.py` exports `DomainError`, `NotFound`, `ValidationFailed`, `Conflict`, `PermissionDenied`, `ImmutableField`. Every task in this plan uses those names.

16. **`packages/core/tests/conftest.py` builds the schema with `Base.metadata.create_all`, not with migrations.** A trigram `Index(...)` declared in `__table_args__` therefore reaches `create_all` before any migration has run `CREATE EXTENSION`, and `create_all` fails with `operator class "gin_trgm_ops" does not exist`. **Resolution (Task A2):** the `db_engine` fixture issues `CREATE EXTENSION IF NOT EXISTS pg_trgm` on its own connection **before** `create_all`. Without this the whole suite goes red on the first task of the slice, for a reason that looks nothing like its cause.

17. **`packages/core/tests/conftest.py`'s `db_session` fixture cannot host a `REPEATABLE READ` test.** It hands out a session bound to a connection with an already-open outer transaction (`connection.begin()` plus `join_transaction_mode="create_savepoint"`), and Postgres refuses `SET TRANSACTION ISOLATION LEVEL` once a transaction has begun. **Resolution (Task B13):** the isolation tests build their own sessions straight from `db_engine`, clean up their own rows in a `finally`, and are marked in their docstring as the two tests in the suite that deliberately do not use `db_session`. Criterion 6 is unwritable without this, and discovering it as a red test costs an afternoon.

18. **`apps/web/src/lib/query.ts` exposes `queryKeys` and no invalidation helpers.** §7.2 says "le chiavi di invalidazione sono quelle che `lib/query.ts` già espone". It exposes the key factory; invalidation is inlined in each feature's mutation `onSuccess`. **Resolution (Task B17):** add `queryKeys.dashboard(kind, params)` and `queryKeys.search(term)` to the same object and invalidate inline, matching the shipped idiom rather than introducing a helper module the codebase does not have.

19. **No route in the app uses URL search params.** §4 requires the period to be in the URL. `validateSearch`, `useSearch` and `Route.useSearch` appear nowhere in `apps/web/src`; list filters are component-local `useState`. **Resolution (Task B17):** `/app/` is the first route in this codebase with `validateSearch`. That is a new pattern, so the task spells out the whole route definition rather than pointing at a neighbour.

---

## File Structure

New and modified files, with each one's single responsibility. Directories that do not exist yet are marked **new**.

### 6A

```
packages/core/src/pigrocrm/core/db/
  sort.py                     NEW  the sort whitelist type, the opaque composite cursor codec,
                                   and the keyset predicate/ORDER BY builder. One module because
                                   the codec and the predicate must agree about NULLS LAST, and
                                   splitting them is how they stop agreeing.
packages/core/src/pigrocrm/core/search/          NEW package
  __init__.py                      re-exports SearchService and the schemas
  schemas.py                       SearchQuery, SearchHit, SearchGroup, SearchResults
  scoring.py                       the §8.5 formula: field score, field weight, row score,
                                   the 0.20 floor. Pure functions over Decimal, no session.
  repository.py                    one branch per entity: the trigram predicate, the score
                                   expression, the count-to-201. No cross-entity logic.
  service.py                       SearchService: term validation, fan-out, total ordering
packages/core/src/pigrocrm/core/{customers,people,deals,documents}/schemas.py
                              MOD  sort/dir on *ListQuery; cursor: UUID|None -> str|None;
                                   next_cursor: UUID|None -> str|None on *Page
packages/core/src/pigrocrm/core/{customers,people,deals,documents}/repository.py
                              MOD  ORDER BY from db/sort.py; documents gains its search branch
packages/core/src/pigrocrm/core/{customers,people,deals,documents}/service.py
                              MOD  next_cursor is encoded, not the bare id
packages/core/src/pigrocrm/core/{customers,people,deals,documents}/models.py
                              MOD  the trigram and B-tree __table_args__ entries
packages/core/migrations/versions/
  0006_pg_trgm_search_indexes.py   NEW  the extension and the nine partial GIN indexes
  0007_sort_indexes.py             NEW  the thirteen B-tree (column, id) indexes
packages/core/tests/
  conftest.py                 MOD  CREATE EXTENSION pg_trgm before create_all
  corpus.py                   NEW  the §16 reference corpus and its inflated variant
  test_corpus.py              NEW  the corpus builds and has the row counts it claims
  test_sort_cursor.py         NEW  the codec round-trips, rejects, and orders totally
  test_search_scoring.py      NEW  the §8.5 formula, table-driven
  test_search_service.py      NEW  the branches, the floor, the count-to-201
  test_search_plan.py         NEW  criterion 3: EXPLAIN, plus the index-removal variant
  test_search_determinism.py  NEW  criterion 4: twenty byte-identical runs
  test_keyset_pagination.py   NEW  criterion 13: no losses, no repeats, under inserts
  test_migrations.py          MOD  HAND_MAINTAINED_INDEXES gains twenty-two names
  test_architecture.py        MOD  SearchService joins the audited surface
apps/api/src/pigrocrm_api/routers/
  search.py                   NEW  GET /api/search
  {customers,people,deals,documents}.py  MOD  sort, dir, cursor: str
apps/api/src/pigrocrm_api/main.py        MOD  include the search router
apps/mcp/src/pigrocrm_mcp/tools/
  search.py                   NEW  search_everything
  __init__.py                 MOD  register it; cursor is already a str at this boundary
apps/web/src/
  lib/api-types.ts            MOD  regenerated, never hand-edited
  lib/query.ts                MOD  queryKeys.search
  components/AppShell.tsx     MOD  the header: breadcrumb, search field, shortcut hint
  components/AppHeader.tsx    NEW  extracted so AppShell stays under 250 lines
  components/ui/command.tsx   NEW  the shadcn cmdk wrapper
  features/search/
    queries.ts                NEW  useGlobalSearch, with the 3-character gate
    CommandPalette.tsx        NEW  the three states, the debounce, the cancellation
    CommandPalette.test.tsx   NEW  the three states as three renderings
  e2e/search.spec.ts          NEW  criterion 5
```

### 6B

```
packages/core/src/pigrocrm/core/db/
  clock.py                    NEW  today_local(settings) — the project's only clock
packages/core/src/pigrocrm/core/config.py        MOD  Settings.timezone
packages/core/src/pigrocrm/core/automations/     NEW package
  __init__.py                      re-exports AutomationRunner and the schemas
  models.py                        AutomationConfig (single row)
  schemas.py                       AutomationConfigRead/Update, AutomationRun, AutomationsDescription
  repository.py                    AutomationConfigRepository
  config_service.py                AutomationConfigService (get, describe, update — admin)
  runner.py                        AutomationRunner.on_offer_state_changed
packages/core/src/pigrocrm/core/dashboard/       NEW package
  __init__.py                      re-exports DashboardService and the schemas
  schemas.py                       CommercialDashboard and its rows (6C adds two more)
  service.py                       DashboardService — composition only, no arithmetic
packages/core/src/pigrocrm/core/deals/models.py  MOD  chiuso_il
packages/core/src/pigrocrm/core/deals/service.py MOD  move_stage writes chiuso_il;
                                                      set_stage_in_transaction
packages/core/src/pigrocrm/core/deals/repository.py MOD pipeline_summary, closed_in_period,
                                                      expected_closures, count_won_not_invoiced
packages/core/src/pigrocrm/core/documents/models.py MOD stato_dal
packages/core/src/pigrocrm/core/documents/service.py MOD set_offer_state writes stato_dal and
                                                      calls the runner
packages/core/src/pigrocrm/core/documents/repository.py MOD pending_offers,
                                                      count_accepted_with_unwon_deal
packages/core/src/pigrocrm/core/activities/repository.py MOD by_kind
packages/core/src/pigrocrm/core/models_registry.py MOD  AutomationConfig
packages/core/migrations/versions/
  0008_automations_and_dates.py    NEW  chiuso_il, stato_dal + backfill, automation_config
packages/core/tests/
  test_clock.py               NEW  the one clock
  test_automation_runner.py   NEW  criteria 7, 8, 9
  test_automation_config.py   NEW  admin-only, and the R5 activity
  test_dashboard_commercial.py NEW the figures, and the two §3 exceptions
  test_dashboard_no_arithmetic.py NEW criterion 11's two AST clauses
  test_dashboard_snapshot.py  NEW  criterion 6, with its own sessions
  test_dashboard_drillthrough.py NEW criterion 2
  test_in_transaction_callers.py NEW the *_in_transaction architecture check
apps/api/src/pigrocrm_api/routers/
  dashboard.py                NEW  GET /api/dashboard/commerciale (6C adds two)
  automations.py              NEW  GET/PUT /api/automation-config, GET /api/automation-runs
apps/mcp/src/pigrocrm_mcp/tools/
  dashboard.py                NEW  get_commercial_dashboard, describe_automations
apps/web/src/
  styles/tokens.css           MOD  --chart-1..5
  styles/tokens.test.ts       MOD  the five new tokens: contrast, and no raw hex
  lib/query.ts                MOD  queryKeys.dashboard
  features/dashboard/
    queries.ts                NEW  useCommercialDashboard (60s staleTime)
    charts.tsx                NEW  BigNumber, BarRow, Sparkline — SVG and CSS only
    charts.test.tsx           NEW  every chart renders its equivalent table
    CommercialTab.tsx         NEW
    CommercialTab.test.tsx    NEW
    Freshness.tsx             NEW  "aggiornato N minuti fa" + recompute
  features/settings/AutomationsPanel.tsx      NEW
  features/settings/AutomationsPanel.test.tsx NEW
  routes/app/index.tsx        MOD  replaced: the three tabs, the period in the URL
  routes/app/impostazioni/automazioni.tsx     NEW
  test/no-browser-arithmetic.test.ts          NEW criterion 14
```

### 6C

```
packages/core/src/pigrocrm/core/analytics/service.py  MOD  unbilled_backlog; PeriodPnl grows
                                                           three informative period fields
packages/core/src/pigrocrm/core/analytics/schemas.py MOD  UnbilledBacklog
packages/core/src/pigrocrm/core/invoices/repository.py MOD sum_da_incassare, sum_scaduto,
                                                           count_emesse_in_periodo,
                                                           count_deals_invoiced_not_won
packages/core/src/pigrocrm/core/invoices/models.py   MOD  the causale trigram index
packages/core/src/pigrocrm/core/timetracking/repository.py MOD hours_by_day
packages/core/src/pigrocrm/core/activities/models.py MOD  ix_activities_recent
packages/core/src/pigrocrm/core/activities/repository.py MOD recent
packages/core/src/pigrocrm/core/dashboard/schemas.py MOD  EconomicDashboard, OperationalDashboard
packages/core/src/pigrocrm/core/dashboard/service.py MOD  the two new compositions
packages/core/src/pigrocrm/core/search/{repository,service}.py MOD the invoice branch
packages/core/migrations/versions/
  0009_dashboard_indexes.py        NEW  ix_activities_recent, the invoice trigram index
packages/core/tests/
  test_dashboard_economic.py  NEW  criterion 1, both directions
  test_dashboard_operational.py NEW
  test_search_invoices.py     NEW  the fiscal-number shape
apps/api/src/pigrocrm_api/routers/dashboard.py MOD  economica, operativa
apps/api/src/pigrocrm_api/routers/analytics.py MOD  GET /api/analytics/backlog
apps/mcp/src/pigrocrm_mcp/
  prompts/__init__.py         NEW  register the four prompts
  prompts/dashboards.py       NEW  revisione-pipeline, chiusura-mese, ore-da-registrare
  prompts/customer.py         NEW  stato-cliente (the one prompt with a resource block)
  server.py                   MOD  register_prompts(mcp, context, _guard)
apps/mcp/tests/
  test_mcp_prompts.py         NEW  criterion 10
  test_mcp_concurrency.py     NEW  criterion 12
apps/web/src/features/dashboard/
  EconomicTab.tsx             NEW
  OperationalTab.tsx          NEW
  *.test.tsx                  NEW
apps/web/e2e/dashboard.spec.ts NEW  criterion 15
```

---
# Sub-plan 6A — Ricerca globale

**Before 6A can start, all of this must already be true.** Verify, do not assume:

| Prerequisite | How to check | If it is missing |
|---|---|---|
| Slice 1 and slice 2 in `main` | `packages/core/src/pigrocrm/core/{customers,people,deals,documents,templates,emitter}/service.py` all exist | Stop. 6A has no substitute for them |
| The migration chain head is `0005` | `ls packages/core/migrations/versions/` shows `0001` … `0005_invoices.py` and nothing later | **Slice 3 landed eight of its twenty-one tasks while this plan was being written**, adding `0004_fiscal_profile.py` and `0005_invoices.py`. If the head has moved again, renumber 6A's two migrations to follow the real head and update their `down_revision` values in the same edit. Run `ls packages/core/migrations/versions/` before writing a migration file, every time — never trust a number written in a plan |
| The suite is green | `uv run pytest -q` | Fix that first. A red baseline makes every "watch it fail" step meaningless |
| PostgreSQL 17 with contrib | `packages/core/tests/conftest.py` uses `PostgresContainer("postgres:17-alpine", …)` | `pg_trgm` ships in that image's contrib set; a stripped image would fail Task A2 loudly, which is the intended behaviour |

**6A needs nothing from slices 3, 4 or 5.** It does not need the R1 cure either, except for the MCP half of Task A11 — see that task's own gate.

**6A executes §16 criteria 3, 4, 5 and 13.**

---

### Task A1: The reference corpus, and its inflated variant

**Files:**
- Create: `packages/core/tests/corpus.py`
- Create: `packages/core/tests/test_corpus.py`

**Interfaces:**
- Consumes: the `db_engine` fixture from `packages/core/tests/conftest.py`; `pigrocrm.core.{customers,people,deals,documents}.models`; `pigrocrm.core.pipeline.models.PipelineStage`.
- Produces:
  - `packages/core/tests/corpus.py::CorpusScale` — a frozen dataclass with `customers: int`, `people: int`, `deals: int`, `documents: int`.
  - `REFERENCE = CorpusScale(customers=500, people=800, deals=2000, documents=1000)`
  - `INFLATED = CorpusScale(customers=50_000, people=50_000, deals=50_000, documents=50_000)`
  - `build_corpus(session: Session, scale: CorpusScale, *, seed: int = 20260821) -> CorpusIds`
  - `CorpusIds` — a frozen dataclass with `stage_open_id: UUID`, `stage_won_id: UUID`, `stage_lost_id: UUID`, `customer_ids: list[UUID]`, `deal_ids: list[UUID]`.
  - `KNOWN_PARTITA_IVA = "01234567890"` and `KNOWN_RAGIONE_SOCIALE = "Rossi Ingegneria Srl"` — the one customer every search test looks for by name.

Why a module and not a fixture: three sub-plans and six test files need it, at two scales, and `INFLATED` takes long enough that a function callable once per session-scoped fixture is the only affordable shape. 6C extends this module with invoices, hours and costs; it does not fork it.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_corpus.py
"""The corpus is a test fixture, so it gets a test: a generator that silently produces
400 rows instead of 50 000 turns Task A9's plan assertion into a measurement of nothing.

Only REFERENCE is exercised here. INFLATED is asserted by Task A9, which is the only
place that pays for it.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.people.models import Person

from .corpus import KNOWN_PARTITA_IVA, KNOWN_RAGIONE_SOCIALE, REFERENCE, build_corpus


def test_build_corpus_produces_exactly_the_row_counts_it_claims(db_session: Session) -> None:
    build_corpus(db_session, REFERENCE)

    assert db_session.scalar(select(func.count()).select_from(Customer)) == 500
    assert db_session.scalar(select(func.count()).select_from(Person)) == 800
    assert db_session.scalar(select(func.count()).select_from(Deal)) == 2000
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1000


def test_build_corpus_plants_the_one_customer_every_search_test_looks_for(
    db_session: Session,
) -> None:
    build_corpus(db_session, REFERENCE)

    row = db_session.scalar(
        select(Customer).where(Customer.partita_iva == KNOWN_PARTITA_IVA)
    )
    assert row is not None
    assert row.ragione_sociale == KNOWN_RAGIONE_SOCIALE


def test_build_corpus_is_deterministic_for_a_given_seed(db_session: Session) -> None:
    """Criterion 4 asserts byte-identical JSON across runs; that is only meaningful if
    the data underneath is byte-identical too."""
    build_corpus(db_session, REFERENCE, seed=7)
    first = db_session.scalars(
        select(Customer.ragione_sociale).order_by(Customer.ragione_sociale).limit(20)
    ).all()

    db_session.rollback()
    build_corpus(db_session, REFERENCE, seed=7)
    second = db_session.scalars(
        select(Customer.ragione_sociale).order_by(Customer.ragione_sociale).limit(20)
    ).all()

    assert list(first) == list(second)


def test_build_corpus_leaves_some_deals_without_a_value(db_session: Session) -> None:
    """Task B9 counts those rows separately and never sums them as zero; the corpus has
    to contain some or that branch is never executed."""
    build_corpus(db_session, REFERENCE)
    without = db_session.scalar(
        select(func.count()).select_from(Deal).where(Deal.valore_previsto.is_(None))
    )
    assert without is not None and without > 0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_corpus.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'packages.core.tests.corpus'` or `ImportError: cannot import name 'build_corpus'`, because `corpus.py` does not exist.

- [ ] **Step 3: Write the corpus generator**

```python
# packages/core/tests/corpus.py
"""The §16 reference corpus, and the inflated variant criterion 3 needs.

Two scales, one generator. The reference scale is ten years of a five-person practice;
the inflated one brings every searched table to 50 000 rows, because an assertion about
a query plan means nothing on a table that fits in a handful of pages -- Postgres picks
a sequential scan there because it *is* the cheapest plan, and a test asserting
otherwise would go red without a defect.

Rows are inserted with `session.execute(insert(Model), [dicts])` rather than through the
ORM: at 50 000 rows per table the unit-of-work overhead is the difference between a test
that runs and a test nobody runs. `flush()` is called, never `commit()` -- the caller's
transaction owns the lifetime, which is what lets `db_session` roll the whole corpus back.

Determinism is by seed, not by luck. `random.Random(seed)` is instantiated locally and
never the module-level `random` functions, so a concurrent test that seeds the global
generator cannot change what this one produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.people.models import Person
from pigrocrm.core.pipeline.models import PipelineStage

# The one customer every search test looks for. Both values are deliberately ordinary:
# a VAT number whose middle five digits ("34567") are a realistic fragment to type, and
# a company name whose first four characters ("Ross") are a realistic prefix.
KNOWN_PARTITA_IVA = "01234567890"
KNOWN_RAGIONE_SOCIALE = "Rossi Ingegneria Srl"

_SURNAMES = (
    "Rossi", "Bianchi", "Ferrari", "Russo", "Esposito", "Colombo", "Ricci", "Marino",
    "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Costa", "Giordano", "Mancini",
    "Rizzo", "Lombardi", "Moretti", "Barbieri",
)
_FIRST_NAMES = (
    "Marco", "Giulia", "Luca", "Chiara", "Andrea", "Sara", "Matteo", "Elena",
    "Francesco", "Alessia", "Davide", "Martina", "Simone", "Federica", "Alessandro",
    "Valentina",
)
_SECTORS = (
    "Ingegneria", "Consulenza", "Logistica", "Impianti", "Servizi", "Costruzioni",
    "Informatica", "Trasporti", "Manutenzioni", "Progettazione",
)
_LEGAL_FORMS = ("Srl", "Spa", "Snc", "Sas", "Srls")
_DEAL_WORDS = (
    "Rifacimento", "Ampliamento", "Adeguamento", "Collaudo", "Fornitura", "Revisione",
    "Migrazione", "Assistenza", "Ristrutturazione", "Certificazione",
)
_DOC_WORDS = ("Offerta", "Contratto", "Verbale", "Relazione", "Preventivo", "Capitolato")


@dataclass(frozen=True)
class CorpusScale:
    customers: int
    people: int
    deals: int
    documents: int


REFERENCE = CorpusScale(customers=500, people=800, deals=2000, documents=1000)
INFLATED = CorpusScale(customers=50_000, people=50_000, deals=50_000, documents=50_000)


@dataclass(frozen=True)
class CorpusIds:
    stage_open_id: UUID
    stage_won_id: UUID
    stage_lost_id: UUID
    customer_ids: list[UUID] = field(default_factory=list)
    deal_ids: list[UUID] = field(default_factory=list)


def _stages(session: Session) -> tuple[UUID, UUID, UUID]:
    """Three stages, resolved by `code` and created only if absent.

    By `code`, never by `nome`: `PipelineStage`'s own docstring gives the reason, and a
    corpus that deduplicated on the renamable label would create a second "Vinto" the
    moment a test renamed the first one.
    """
    wanted = (("offerta", "Offerta", 2, 50, "open"), ("vinto", "Vinto", 4, 100, "won"),
              ("perso", "Perso", 5, 0, "lost"))
    ids: list[UUID] = []
    for code, nome, posizione, probabilita, tipo in wanted:
        existing = session.scalar(select(PipelineStage).where(PipelineStage.code == code))
        if existing is None:
            existing = PipelineStage(
                code=code, nome=nome, posizione=posizione,
                probabilita_default=probabilita, tipo=tipo,
            )
            session.add(existing)
            session.flush()
        ids.append(existing.id)
    return ids[0], ids[1], ids[2]


def build_corpus(session: Session, scale: CorpusScale, *, seed: int = 20260821) -> CorpusIds:
    import random

    rng = random.Random(seed)
    stage_open, stage_won, stage_lost = _stages(session)

    customer_ids: list[UUID] = []
    customer_rows: list[dict[str, object]] = []
    for index in range(scale.customers):
        cid = uuid7()
        customer_ids.append(cid)
        if index == 0:
            ragione, piva = KNOWN_RAGIONE_SOCIALE, KNOWN_PARTITA_IVA
        else:
            ragione = (
                f"{rng.choice(_SURNAMES)} {rng.choice(_SECTORS)} "
                f"{rng.choice(_LEGAL_FORMS)} {index}"
            )
            piva = f"{index:011d}"
        customer_rows.append({
            "id": cid,
            "ragione_sociale": ragione[:255],
            "partita_iva": piva,
            "codice_fiscale": f"CF{index:014d}"[:16],
            "email": f"info{index}@{rng.choice(_SECTORS).lower()}.example",
            "nazione": "IT",
            "stato": rng.choice(("attivo", "prospect", None)),
            "custom_fields": {},
        })
    session.execute(insert(Customer), customer_rows)

    person_rows: list[dict[str, object]] = []
    for index in range(scale.people):
        # Every fifth person has no surname: `people.cognome` is nullable, and Task A3's
        # NULLS LAST cursor has no exerciser without rows in the null tail.
        cognome = None if index % 5 == 0 else rng.choice(_SURNAMES)
        person_rows.append({
            "id": uuid7(),
            "customer_id": customer_ids[index % len(customer_ids)],
            "nome": rng.choice(_FIRST_NAMES),
            "cognome": cognome,
            "email": f"persona{index}@example.it",
            "custom_fields": {},
        })
    session.execute(insert(Person), person_rows)

    deal_ids: list[UUID] = []
    deal_rows: list[dict[str, object]] = []
    for index in range(scale.deals):
        did = uuid7()
        deal_ids.append(did)
        stage = (stage_open, stage_won, stage_lost)[index % 3]
        # Every seventh deal has no expected value. Task B9 counts these under
        # "senza valore" and never sums them as zero.
        valore = None if index % 7 == 0 else f"{1000 + index % 90000}.00"
        deal_rows.append({
            "id": did,
            "nome": f"{rng.choice(_DEAL_WORDS)} {rng.choice(_SECTORS)} {index}",
            "customer_id": customer_ids[index % len(customer_ids)],
            "pipeline_stage_id": stage,
            "valore_previsto": valore,
            "probabilita": (index % 11) * 10,
            "custom_fields": {},
        })
    session.execute(insert(Deal), deal_rows)

    document_rows: list[dict[str, object]] = []
    for index in range(scale.documents):
        # `ck_documents_customer_xor_deal`: exactly one of the two, never both.
        owner_is_deal = index % 2 == 0
        document_rows.append({
            "id": uuid7(),
            "customer_id": None if owner_is_deal else customer_ids[index % len(customer_ids)],
            "deal_id": deal_ids[index % len(deal_ids)] if owner_is_deal else None,
            "tipo": "offerta" if index % 3 == 0 else "documento",
            "titolo": f"{rng.choice(_DOC_WORDS)} {rng.choice(_SECTORS)} {index}",
            "stato": "inviata" if index % 3 == 0 else None,
            "versione_corrente": 1,
            "custom_fields": {},
        })
    session.execute(insert(Document), document_rows)

    session.flush()
    return CorpusIds(
        stage_open_id=stage_open,
        stage_won_id=stage_won,
        stage_lost_id=stage_lost,
        customer_ids=customer_ids,
        deal_ids=deal_ids,
    )
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `uv run pytest packages/core/tests/test_corpus.py -v`
Expected: PASS, four tests.

- [ ] **Step 5: Check the whole suite is still green and the types hold**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: everything passes. `corpus.py` lives under `tests/`, which `mypy`'s `files` setting does not cover, so it is linted but not type-checked — that is the existing arrangement for every other test module and is not changed here.

- [ ] **Step 6: Commit**

```bash
git add packages/core/tests/corpus.py packages/core/tests/test_corpus.py
git commit -m "test(core): reference and inflated search corpora, deterministic by seed"
```

---

### Task A2: `pg_trgm`, the nine partial trigram indexes, and the `ESCAPE` verdict

**Files:**
- Modify: `packages/core/src/pigrocrm/core/customers/models.py` (`__table_args__`)
- Modify: `packages/core/src/pigrocrm/core/people/models.py` (`__table_args__`)
- Modify: `packages/core/src/pigrocrm/core/deals/models.py` (`__table_args__`)
- Modify: `packages/core/src/pigrocrm/core/documents/models.py` (`__table_args__`)
- Create: `packages/core/migrations/versions/0006_pg_trgm_search_indexes.py`
- Modify: `packages/core/tests/conftest.py` (create the extension before `create_all`)
- Modify: `packages/core/tests/test_migrations.py` (`HAND_MAINTAINED_INDEXES`)
- Create: `packages/core/tests/test_trgm_escape.py`
- Modify: `README.md` (the `pg_trgm` privilege line, under "### Prerequisiti sul server")

**Interfaces:**
- Consumes: `build_corpus`, `REFERENCE` from Task A1; `pigrocrm.core.db.escape_like`.
- Produces:
  - Nine index names, which Task A9 asserts on and Task A11's endpoint depends on:
    `ix_customers_ragione_sociale_trgm`, `ix_customers_partita_iva_trgm`,
    `ix_customers_codice_fiscale_trgm`, `ix_customers_email_trgm`,
    `ix_people_nome_trgm`, `ix_people_cognome_trgm`, `ix_people_email_trgm`,
    `ix_deals_nome_trgm`, `ix_documents_titolo_trgm`.
  - A recorded decision, in the docstring of `test_trgm_escape.py`, about whether `escape="\\"` stays. **If it must go, this task removes it from all four existing call sites in the same commit** — `customers/repository.py`, `people/repository.py`, `deals/repository.py`, `templates/repository.py` — and amends the Global Constraint above.

The tenth index, `ix_invoices_causale_trgm`, belongs to Task C13: there is no `invoices` table in 6A.

- [ ] **Step 1: Write the failing test that measures the `ESCAPE` clause**

```python
# packages/core/tests/test_trgm_escape.py
r"""Spec §8.3 point 3, measured instead of assumed.

The predicate the four shipped repositories emit is `col ILIKE :p ESCAPE '\'`. Postgres
plans `LIKE ... ESCAPE` as `like_escape(pattern, escape)` inside the `~~*` operator, and
with both arguments constant, constant folding should produce a constant pattern that the
trigram index can serve. "Should" is not a measurement, so this test is the measurement,
and it runs before anything is built on top of it.

If `test_ilike_with_an_explicit_escape_uses_the_trigram_index` fails, the fallback is one
line and is stated in the spec: drop the `ESCAPE` clause. The backslash is already
Postgres's default LIKE escape character -- `escape_like`'s own docstring says so -- so
removing the clause changes no semantics. It must then be removed from **all four** call
sites in this same commit, never from one.

`SET enable_seqscan = off` is deliberately NOT used. It would force the planner's hand and
turn a measurement into a tautology; the point is what the planner chooses on its own.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.db import escape_like

from .corpus import REFERENCE, build_corpus


def _plan(session: Session, sql: str, params: dict[str, object]) -> str:
    rows = session.execute(text(f"EXPLAIN {sql}"), params).all()
    return "\n".join(str(row[0]) for row in rows)


def test_the_trigram_extension_and_index_exist(db_session: Session) -> None:
    installed = db_session.scalar(
        text("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'")
    )
    assert installed == 1, "pg_trgm is not installed on the test database"

    found = db_session.scalar(
        text(
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = 'ix_customers_ragione_sociale_trgm'"
        )
    )
    assert found == 1, "ix_customers_ragione_sociale_trgm was not created"


def test_ilike_with_an_explicit_escape_uses_the_trigram_index(db_session: Session) -> None:
    build_corpus(db_session, REFERENCE)
    db_session.execute(text("ANALYZE customers"))

    pattern = f"%{escape_like('ingegn')}%"
    plan = _plan(
        db_session,
        "SELECT id FROM customers "
        r"WHERE deleted_at IS NULL AND ragione_sociale ILIKE :p ESCAPE '\'",
        {"p": pattern},
    )
    assert "ix_customers_ragione_sociale_trgm" in plan, (
        "the ESCAPE clause defeated the trigram index; apply the spec's one-line "
        f"fallback and remove `escape=` from all four repositories.\nPlan was:\n{plan}"
    )


def test_the_same_predicate_without_escape_also_uses_the_index(db_session: Session) -> None:
    """The control. If this one fails too, the problem is the index or the statistics,
    not the ESCAPE clause, and removing the clause would be the wrong fix."""
    build_corpus(db_session, REFERENCE)
    db_session.execute(text("ANALYZE customers"))

    plan = _plan(
        db_session,
        "SELECT id FROM customers WHERE deleted_at IS NULL AND ragione_sociale ILIKE :p",
        {"p": "%ingegn%"},
    )
    assert "ix_customers_ragione_sociale_trgm" in plan, f"plan was:\n{plan}"


def test_similarity_needs_no_lower_in_the_index_expression(db_session: Session) -> None:
    """Spec §8.2's non-obvious note, pinned so nobody "fixes" the index by wrapping the
    column in `lower()` -- which would make ILIKE on the raw column unable to use it."""
    same = db_session.scalar(text("SELECT similarity('Rossi', 'rossi')"))
    assert same == 1.0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_trgm_escape.py -v`
Expected: `test_the_trigram_extension_and_index_exist` FAILS with `assert 0 == 1` / "pg_trgm is not installed on the test database", and the two plan tests FAIL because the index does not exist. The `similarity` test errors with `UndefinedFunction: function similarity(unknown, unknown) does not exist`.

- [ ] **Step 3: Create the extension in the test fixture, before `create_all`**

```python
# packages/core/tests/conftest.py -- replace the db_engine fixture body.
# The rest of the file (db_session) is untouched.

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.config import Settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Real PostgreSQL. JSONB, GIN and pg_trgm do not exist in SQLite, so there is no
    shortcut.

    `CREATE EXTENSION` runs **before** `create_all`, and that order is load-bearing: from
    slice 6 on, four models declare GIN indexes with `gin_trgm_ops`, and `create_all`
    fails outright with `operator class "gin_trgm_ops" does not exist` if the extension is
    not there yet. The migrations create the extension too (0004) -- this is the same
    statement for the path that bypasses them.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        settings = Settings(database_url=container.get_connection_url())
        engine = create_engine_from_settings(settings)
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        import pigrocrm.core.models_registry  # noqa: F401  (imports every model)

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()
```

- [ ] **Step 4: Declare the nine indexes on the models**

```python
# packages/core/src/pigrocrm/core/customers/models.py -- replace __table_args__ only.
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_custom_fields", "custom_fields", postgresql_using="gin"),
        Index("ix_customers_ragione_sociale", "ragione_sociale"),
        # Trigram indexes, partial on `deleted_at IS NULL` because that is the condition
        # every search carries (spec §8.3): the index is smaller and residuo R7 closes
        # for this table. No `lower()` in the expression -- `similarity()` normalises to
        # lower case internally, and wrapping the column would make ILIKE on the raw
        # column unable to use the index (spec §8.2).
        Index(
            "ix_customers_ragione_sociale_trgm", "ragione_sociale",
            postgresql_using="gin", postgresql_ops={"ragione_sociale": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_customers_partita_iva_trgm", "partita_iva",
            postgresql_using="gin", postgresql_ops={"partita_iva": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_customers_codice_fiscale_trgm", "codice_fiscale",
            postgresql_using="gin", postgresql_ops={"codice_fiscale": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_customers_email_trgm", "email",
            postgresql_using="gin", postgresql_ops={"email": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
```

The import line at the top of that file becomes `from sqlalchemy import Index, String, Text, text`.

```python
# packages/core/src/pigrocrm/core/people/models.py -- replace __table_args__ only.
    __tablename__ = "people"
    __table_args__ = (
        Index("ix_people_custom_fields", "custom_fields", postgresql_using="gin"),
        Index(
            "ix_people_nome_trgm", "nome",
            postgresql_using="gin", postgresql_ops={"nome": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_people_cognome_trgm", "cognome",
            postgresql_using="gin", postgresql_ops={"cognome": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_people_email_trgm", "email",
            postgresql_using="gin", postgresql_ops={"email": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
```

Add `text` to that file's `from sqlalchemy import ...` line.

```python
# packages/core/src/pigrocrm/core/deals/models.py -- replace __table_args__ only.
    __tablename__ = "deals"
    __table_args__ = (
        Index("ix_deals_custom_fields", "custom_fields", postgresql_using="gin"),
        Index(
            "ix_deals_nome_trgm", "nome",
            postgresql_using="gin", postgresql_ops={"nome": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
```

```python
# packages/core/src/pigrocrm/core/documents/models.py -- append to the existing
# __table_args__ tuple, which already holds the CHECK and the GIN index.
        Index(
            "ix_documents_titolo_trgm", "titolo",
            postgresql_using="gin", postgresql_ops={"titolo": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
```

Add `text` to the `from sqlalchemy import ...` line in both files.

- [ ] **Step 5: Write migration 0004**

```python
# packages/core/migrations/versions/0006_pg_trgm_search_indexes.py
"""pg_trgm and the partial trigram search indexes

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-21

Closes residuo R6 for customers, people, deals and documents, and residuo R7 for those
four tables as a side effect of the indexes being partial on `deleted_at IS NULL`.

`CREATE EXTENSION` is deliberately not guarded by a capability check. Migrations run at
API start-up (slice 1 §12), so on a managed Postgres whose allowlist forbids `pg_trgm`
the deploy fails loudly here -- which is what is wanted. The alternative is an
application that starts and scans sequentially in silence, which is the defect being
cured, with one index fewer.

`CONCURRENTLY` is not used: Alembic runs each migration inside a transaction, and
`CREATE INDEX CONCURRENTLY` cannot run in one. On a table of this size the exclusive lock
is short; on a live installation large enough for it to matter, the operator builds the
indexes by hand out-of-band and this migration finds them already present -- which is why
every statement carries `IF NOT EXISTS`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, column). Nine entries; the tenth, on invoices.causale, arrives with
# slice 6C because there is no invoices table at this revision.
_TRGM_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_customers_ragione_sociale_trgm", "customers", "ragione_sociale"),
    ("ix_customers_partita_iva_trgm", "customers", "partita_iva"),
    ("ix_customers_codice_fiscale_trgm", "customers", "codice_fiscale"),
    ("ix_customers_email_trgm", "customers", "email"),
    ("ix_people_nome_trgm", "people", "nome"),
    ("ix_people_cognome_trgm", "people", "cognome"),
    ("ix_people_email_trgm", "people", "email"),
    ("ix_deals_nome_trgm", "deals", "nome"),
    ("ix_documents_titolo_trgm", "documents", "titolo"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in _TRGM_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"USING gin ({column} gin_trgm_ops) WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    for name, _table, _column in reversed(_TRGM_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    # The extension is left installed. Dropping it would fail if anything else in the
    # database came to depend on it, and an extension costs nothing to leave behind.
```

- [ ] **Step 6: Add the nine names to `HAND_MAINTAINED_INDEXES`**

```python
# packages/core/tests/test_migrations.py -- replace the set and its comment.
# Autogenerate is known to silently omit exactly these shapes: a unique index over a SQL
# expression rather than a bare column (`uq_users_email_lower`), a plain unique index on a
# nullable column (`uq_pipeline_stage_code`), a GIN index, and -- from slice 6 -- a
# *partial* GIN index over an operator class (`*_trgm`). Nine trigram indexes omitted in
# silence are nine sequential scans that come back a month later, so they are named here
# and a regression fails with the missing index's name instead of a generic metadata diff.
HAND_MAINTAINED_INDEXES = {
    "uq_users_email_lower",
    "uq_pipeline_stage_code",
    "ix_customers_custom_fields",
    "ix_people_custom_fields",
    "ix_deals_custom_fields",
    # Added by slice 3 (migration 0005). Present in the shipped set -- do not drop them
    # while rewriting this literal.
    "uq_invoices_anno_numero",
    "ix_invoices_custom_fields",
    "ix_customers_ragione_sociale_trgm",
    "ix_customers_partita_iva_trgm",
    "ix_customers_codice_fiscale_trgm",
    "ix_customers_email_trgm",
    "ix_people_nome_trgm",
    "ix_people_cognome_trgm",
    "ix_people_email_trgm",
    "ix_deals_nome_trgm",
    "ix_documents_titolo_trgm",
}

TRGM_INDEX_NAMES = frozenset(n for n in HAND_MAINTAINED_INDEXES if n.endswith("_trgm"))
```

And append this test to the same file:

```python
def test_every_trigram_index_is_a_partial_gin_index_over_gin_trgm_ops() -> None:
    """A trigram index created without `gin_trgm_ops` is an ordinary GIN index that
    cannot serve `ILIKE '%x%'` at all, and one created without the `WHERE` clause is
    bigger than it needs to be and leaves residuo R7 open for that table. Both mistakes
    produce a green `compare_metadata`, so they are asserted on the definition text.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            ).all()
        engine.dispose()

    indexes = {row.indexname: row.indexdef for row in rows}
    for name in sorted(TRGM_INDEX_NAMES):
        definition = indexes[name]
        assert "USING gin" in definition, f"{name} is not a GIN index: {definition}"
        assert "gin_trgm_ops" in definition, f"{name} lacks gin_trgm_ops: {definition}"
        assert "WHERE (deleted_at IS NULL)" in definition, (
            f"{name} is not partial on deleted_at IS NULL: {definition}"
        )
        assert "lower(" not in definition, (
            f"{name} wraps the column in lower(), which stops ILIKE on the raw column "
            f"from using it (spec §8.2): {definition}"
        )
```

Also change the two `assert revision == "0005"` occurrences in that file to `"0006"`, since the head has moved. There are exactly two, at `packages/core/tests/test_migrations.py:155` and `:177`; `grep -n '"0005"' packages/core/tests/test_migrations.py` finds them.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_trgm_escape.py packages/core/tests/test_migrations.py -v`
Expected: PASS.

**If `test_ilike_with_an_explicit_escape_uses_the_trigram_index` fails while the control test passes**, apply the spec's fallback now, in this task, and not later:

1. In `customers/repository.py`, `people/repository.py`, `deals/repository.py` and `templates/repository.py`, change every `.ilike(like, escape="\\")` to `.ilike(like)` — **all of them, in one commit.** `escape_like` still runs; only the redundant clause goes.
2. Add this comment above the first changed call site:
   ```python
   # No `escape=` clause: measured in Task A2 (packages/core/tests/test_trgm_escape.py),
   # `ILIKE ... ESCAPE '\'` was not served by the trigram index while the same predicate
   # without the clause was. The backslash is already Postgres's default LIKE escape
   # character -- see `escape_like`'s docstring -- so the clause was redundant and its
   # removal changes no semantics. Do not add it back without re-running that test.
   ```
3. Amend the "Escape LIKE metacharacters" bullet in this plan's Global Constraints to say the clause is omitted, and record the plan text in the test's docstring.
4. Re-run Step 7.

- [ ] **Step 8: Add the runbook line**

```markdown
<!-- README.md, appended to "### Prerequisiti sul server" -->
- **`pg_trgm`.** Le migrazioni eseguono `CREATE EXTENSION IF NOT EXISTS pg_trgm`
  all'avvio dell'API. Sull'immagine `postgres:17-alpine` del compose l'utente
  `pigrocrm` è superuser e funziona senza intervento. Su un PostgreSQL gestito serve
  che il fornitore abbia `pg_trgm` in allowlist e che l'utente possa creare estensioni:
  senza, **il deploy fallisce all'avvio** — che è il comportamento voluto, perché
  l'alternativa è un'applicazione che parte e scansiona sequenzialmente in silenzio.
  Sintomo esatto nei log: `permission denied to create extension "pg_trgm"`.
```

- [ ] **Step 9: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: everything passes.

- [ ] **Step 10: Commit**

```bash
git add packages/core/src/pigrocrm/core/customers/models.py \
        packages/core/src/pigrocrm/core/people/models.py \
        packages/core/src/pigrocrm/core/deals/models.py \
        packages/core/src/pigrocrm/core/documents/models.py \
        packages/core/migrations/versions/0006_pg_trgm_search_indexes.py \
        packages/core/tests/conftest.py \
        packages/core/tests/test_migrations.py \
        packages/core/tests/test_trgm_escape.py \
        README.md
git commit -m "feat(search): pg_trgm and nine partial trigram indexes, closing R6"
```

---
### Task A3: The sort whitelist, the opaque composite cursor, and the thirteen B-tree indexes

**Files:**
- Create: `packages/core/src/pigrocrm/core/db/sort.py`
- Modify: `packages/core/src/pigrocrm/core/db/__init__.py` (re-export)
- Modify: `packages/core/src/pigrocrm/core/{customers,people,deals,documents}/models.py` (`__table_args__`)
- Create: `packages/core/migrations/versions/0007_sort_indexes.py`
- Create: `packages/core/tests/test_sort_cursor.py`
- Modify: `packages/core/tests/test_migrations.py` (`HAND_MAINTAINED_INDEXES`, head revision)

**Interfaces:**
- Consumes: `pigrocrm.core.db.base.Base`; nothing from Task A1 or A2.
- Produces, all importable from `pigrocrm.core.db`:
  - `SortDirection = Literal["asc", "desc"]`
  - `SortKind = Literal["text", "datetime"]`
  - `SortSpec` — frozen dataclass: `key: str`, `column: InstrumentedAttribute[Any]`, `kind: SortKind`, `nullable: bool`
  - `SortWhitelist` — frozen dataclass: `specs: tuple[SortSpec, ...]`, `default_key: str`; methods `keys() -> tuple[str, ...]` and `resolve(key: str | None) -> SortSpec`
  - `encode_cursor(spec: SortSpec, value: object, row_id: UUID) -> str`
  - `decode_cursor(spec: SortSpec, raw: str) -> tuple[object | None, UUID]`
  - `keyset_predicate(spec: SortSpec, direction: SortDirection, value: object | None, row_id: UUID) -> ColumnElement[bool]`
  - `order_by(spec: SortSpec, direction: SortDirection) -> tuple[UnaryExpression[Any], ...]`
  - `CURSOR_MAX_LENGTH = 512`
- Later tasks rely on the exact names above. Task A4 calls all of them; Tasks A5 and A11 only ever pass the string through.

**The ordering contract, stated once so no task re-derives it.** `ORDER BY <col> <dir> NULLS LAST, id <dir>` — the tie-break follows the direction, which is what lets a single ascending `(col, id)` index serve `desc` as a backward scan. The only nullable whitelisted column is `people.cognome`, and it alone gets a second index, `(cognome DESC NULLS LAST, id DESC)`, because a backward scan of the ascending index would put its nulls first. That asymmetry is the whole reason the whitelist is short.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_sort_cursor.py
"""Residuo R9's machinery, tested before anything uses it.

R9 measures that no `list()` in either adapter orders by anything but `id`, while slice 1
§7 promised ordering. The fix keeps keyset pagination -- offset pagination re-reads and
skips rows under concurrent insertion, which is why slice 1 chose keyset -- so ordering by
a non-unique column needs a *composite* cursor. That makes the cursor opaque, and opacity
is also what lets it represent a null: an empty string in a query parameter is
indistinguishable from a null, and rows are lost on exactly that distinction.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import (
    CURSOR_MAX_LENGTH,
    SortSpec,
    SortWhitelist,
    decode_cursor,
    encode_cursor,
    keyset_predicate,
    order_by,
)
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.people.models import Person

_TEXT = SortSpec(key="ragione_sociale", column=Customer.ragione_sociale, kind="text",
                 nullable=False)
_STAMP = SortSpec(key="created_at", column=Customer.created_at, kind="datetime",
                  nullable=False)
_NULLABLE = SortSpec(key="cognome", column=Person.cognome, kind="text", nullable=True)


def test_a_text_cursor_round_trips() -> None:
    row_id = uuid7()
    raw = encode_cursor(_TEXT, "Rossi Ingegneria Srl", row_id)
    assert decode_cursor(_TEXT, raw) == ("Rossi Ingegneria Srl", row_id)


def test_a_datetime_cursor_round_trips_with_its_timezone() -> None:
    row_id = uuid7()
    moment = datetime(2026, 8, 21, 14, 30, 5, 123456, tzinfo=UTC)
    raw = encode_cursor(_STAMP, moment, row_id)
    assert decode_cursor(_STAMP, raw) == (moment, row_id)


def test_a_null_cursor_round_trips_and_is_not_an_empty_string() -> None:
    """The distinction the opacity exists for."""
    row_id = uuid7()
    raw_null = encode_cursor(_NULLABLE, None, row_id)
    raw_empty = encode_cursor(_NULLABLE, "", row_id)
    assert raw_null != raw_empty
    assert decode_cursor(_NULLABLE, raw_null) == (None, row_id)
    assert decode_cursor(_NULLABLE, raw_empty) == ("", row_id)


def test_a_cursor_is_url_safe_and_unpadded() -> None:
    raw = encode_cursor(_TEXT, 'a/b+c=d "e" &f?', uuid7())
    assert "=" not in raw
    assert "/" not in raw
    assert "+" not in raw
    assert len(raw) <= CURSOR_MAX_LENGTH


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-base64!!",
        "eyJ2IjogMX0",                       # {"v": 1} -- no id at all
        "eyJ2IjogbnVsbCwgImkiOiAibm90LWEtdXVpZCJ9",  # {"v": null, "i": "not-a-uuid"}
        "x" * (CURSOR_MAX_LENGTH + 1),
    ],
)
def test_a_malformed_cursor_is_a_domain_error_not_a_crash(raw: str) -> None:
    """A cursor arrives from a query string, so a hostile or stale one is ordinary input.
    It must produce a 422 with a named field, never a `binascii.Error` or a `KeyError`
    escaping as a 500."""
    with pytest.raises(ValidationFailed) as caught:
        decode_cursor(_TEXT, raw)
    assert caught.value.details["field"] == "cursor"


def test_a_cursor_encoded_for_one_sort_key_is_refused_by_another() -> None:
    """Changing `sort` mid-scan while replaying `next_cursor` would otherwise compare a
    surname against a timestamp and return an arbitrary page."""
    raw = encode_cursor(_TEXT, "Rossi", uuid7())
    with pytest.raises(ValidationFailed) as caught:
        decode_cursor(_STAMP, raw)
    assert caught.value.details["field"] == "cursor"


def test_the_whitelist_refuses_a_key_it_does_not_contain() -> None:
    whitelist = SortWhitelist(specs=(_TEXT, _STAMP), default_key="created_at")
    assert whitelist.keys() == ("ragione_sociale", "created_at")
    assert whitelist.resolve(None).key == "created_at"
    assert whitelist.resolve("ragione_sociale").key == "ragione_sociale"
    with pytest.raises(ValidationFailed) as caught:
        whitelist.resolve("note; DROP TABLE customers")
    assert caught.value.details["field"] == "sort"


def test_order_by_puts_nulls_last_in_both_directions(db_session: Session) -> None:
    """`people.cognome` is nullable. Nulls last ascending is Postgres's default; nulls
    last *descending* is not, and getting it by accident is how the null tail ends up at
    the top of page one with no cursor value to resume from."""
    for cognome in ("Bianchi", None, "Rossi"):
        db_session.add(Person(nome="Marco", cognome=cognome, custom_fields={}))
    db_session.flush()

    ascending = db_session.scalars(
        select(Person.cognome).order_by(*order_by(_NULLABLE, "asc"))
    ).all()
    descending = db_session.scalars(
        select(Person.cognome).order_by(*order_by(_NULLABLE, "desc"))
    ).all()

    assert list(ascending) == ["Bianchi", "Rossi", None]
    assert list(descending) == ["Rossi", "Bianchi", None]


def test_the_keyset_predicate_resumes_exactly_after_the_cursor_row(
    db_session: Session,
) -> None:
    rows = [Person(nome="A", cognome=c, custom_fields={}) for c in ("B", "C", None, None)]
    for row in rows:
        db_session.add(row)
    db_session.flush()

    ordered = db_session.scalars(
        select(Person).order_by(*order_by(_NULLABLE, "asc"))
    ).all()
    third = ordered[2]  # the first of the two nulls

    after = db_session.scalars(
        select(Person.id)
        .where(keyset_predicate(_NULLABLE, "asc", third.cognome, third.id))
        .order_by(*order_by(_NULLABLE, "asc"))
    ).all()

    assert list(after) == [ordered[3].id]


def test_the_keyset_predicate_from_a_non_null_value_still_reaches_the_null_tail(
    db_session: Session,
) -> None:
    """The clause people forget. Without `OR col IS NULL`, paging ascending stops at the
    last non-null row and the null tail is never returned at all."""
    for cognome in ("B", None):
        db_session.add(Person(nome="A", cognome=cognome, custom_fields={}))
    db_session.flush()

    first = db_session.scalars(
        select(Person).order_by(*order_by(_NULLABLE, "asc"))
    ).all()[0]

    after = db_session.scalars(
        select(Person.cognome)
        .where(keyset_predicate(_NULLABLE, "asc", first.cognome, first.id))
        .order_by(*order_by(_NULLABLE, "asc"))
    ).all()

    assert list(after) == [None]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_sort_cursor.py -v`
Expected: collection error — `ImportError: cannot import name 'SortSpec' from 'pigrocrm.core.db'`.

- [ ] **Step 3: Write `db/sort.py`**

```python
# packages/core/src/pigrocrm/core/db/sort.py
"""Ordering and keyset pagination for the four entities residuo R9 covers.

R9: slice 1 §7 promised "paginazione cursor-based, ordinamento e filtri" and every
shipped `list()` orders by `id` alone -- which with UUIDv7 means creation order. This
module is the missing half.

Three decisions, and each one is load-bearing.

**Keyset, not offset.** Offset pagination re-reads and skips rows under concurrent
insertion. That is why slice 1 chose keyset, and it does not stop being true because the
sort column changed.

**The cursor is opaque.** A keyset over a non-unique column needs the pair
`(sort value, id)`, and the sort value can be null (`people.cognome`). An empty string in
a query parameter is indistinguishable from a null, and rows are lost on exactly that
distinction -- so the pair is JSON, base64url, unpadded, and the client echoes it back
without interpreting it. The encoding also carries the sort key, so replaying a cursor
against a different `sort` is refused rather than silently comparing a surname to a
timestamp.

**`NULLS LAST` in both directions, tie-break in the direction of travel.**
`ORDER BY col <dir> NULLS LAST, id <dir>`. The tie-break following the direction is what
lets one ascending `(col, id)` index serve `desc` as a backward scan; the exception is a
nullable column, where a backward scan would put nulls first, so `people.cognome` carries
a second index `(cognome DESC NULLS LAST, id DESC)`. This is why the whitelist is short:
every admitted column costs an index, and a nullable one costs two.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, UnaryExpression, and_, or_
from sqlalchemy.orm.attributes import InstrumentedAttribute

from pigrocrm.core.errors import ValidationFailed

SortDirection = Literal["asc", "desc"]
SortKind = Literal["text", "datetime"]

# Long enough for a 255-character `ragione_sociale` plus a UUID plus the JSON and base64
# expansion (255 * 4/3 + overhead), short enough that a megabyte of query string is
# refused before it is decoded. Bounded for the same reason `limit` is (Global
# Constraints): an unbounded parameter reaching a decoder is a denial of service with
# extra steps.
CURSOR_MAX_LENGTH = 512

_ENTITY = "cursor"


@dataclass(frozen=True)
class SortSpec:
    """One admissible sort column.

    `kind` exists because the cursor is JSON and JSON has no datetime: the decoder needs
    to be told how to read the value back. Inferring it from the column type is possible
    and rejected -- it would put a `isinstance` ladder over SQLAlchemy type objects in the
    hot path of every list request, to answer a question the declaration already knows.
    """

    key: str
    column: InstrumentedAttribute[Any]
    kind: SortKind
    nullable: bool


@dataclass(frozen=True)
class SortWhitelist:
    specs: tuple[SortSpec, ...]
    default_key: str

    def keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.specs)

    def resolve(self, key: str | None) -> SortSpec:
        wanted = key if key is not None else self.default_key
        for spec in self.specs:
            if spec.key == wanted:
                return spec
        raise ValidationFailed(
            "list_query", "sort", "ordinamento non ammesso",
            expected=", ".join(self.keys()),
        )


def _encode_value(spec: SortSpec, value: object) -> object:
    if value is None:
        return None
    if spec.kind == "datetime":
        if not isinstance(value, datetime):
            raise ValidationFailed(
                _ENTITY, "cursor", "valore di ordinamento non è una data",
                expected="datetime",
            )
        return value.isoformat()
    return str(value)


def _decode_value(spec: SortSpec, raw: object) -> object | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValidationFailed(_ENTITY, "cursor", "cursore non valido", expected="stringa")
    if spec.kind == "datetime":
        try:
            return datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValidationFailed(
                _ENTITY, "cursor", "cursore non valido", expected="data ISO 8601"
            ) from exc
    return raw


def encode_cursor(spec: SortSpec, value: object, row_id: UUID) -> str:
    payload = {"k": spec.key, "v": _encode_value(spec, value), "i": str(row_id)}
    # `separators` without spaces, `sort_keys=True`: the encoding must be a pure function
    # of its inputs, because criterion 4 asserts byte-identical responses across runs.
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")


def decode_cursor(spec: SortSpec, raw: str) -> tuple[object | None, UUID]:
    if not raw or len(raw) > CURSOR_MAX_LENGTH:
        raise ValidationFailed(
            _ENTITY, "cursor", "cursore non valido",
            expected=f"stringa opaca di al massimo {CURSOR_MAX_LENGTH} caratteri",
        )
    padded = raw + "=" * (-len(raw) % 4)
    try:
        body = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(body)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValidationFailed(
            _ENTITY, "cursor", "cursore non valido", expected="cursore restituito dall'API"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"k", "v", "i"}:
        raise ValidationFailed(
            _ENTITY, "cursor", "cursore non valido", expected="cursore restituito dall'API"
        )
    if payload["k"] != spec.key:
        raise ValidationFailed(
            _ENTITY, "cursor", "il cursore appartiene a un altro ordinamento",
            expected=f"un cursore prodotto con sort={spec.key}",
        )
    try:
        row_id = UUID(str(payload["i"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationFailed(
            _ENTITY, "cursor", "cursore non valido", expected="UUID"
        ) from exc
    return _decode_value(spec, payload["v"]), row_id


def order_by(spec: SortSpec, direction: SortDirection) -> tuple[UnaryExpression[Any], ...]:
    """`col <dir> NULLS LAST, id <dir>`. Both clauses carry the same direction -- see the
    module docstring for why that is what makes one index enough for a non-nullable
    column."""
    column, identity = spec.column, spec.column.parent.class_.id
    if direction == "asc":
        return (column.asc().nulls_last(), identity.asc())
    return (column.desc().nulls_last(), identity.desc())


def keyset_predicate(
    spec: SortSpec,
    direction: SortDirection,
    value: object | None,
    row_id: UUID,
) -> ColumnElement[bool]:
    """Everything strictly after `(value, row_id)` in `order_by(spec, direction)`.

    The `or_(column.is_(None))` arm is the one that gets forgotten: without it, paging
    from a non-null value stops at the last non-null row and the null tail is never
    returned at all -- rows silently missing from a complete scan, which is precisely the
    failure keyset pagination was chosen to avoid.
    """
    column, identity = spec.column, spec.column.parent.class_.id
    if value is None:
        # Already inside the null tail, which is ordered by `id` alone.
        after_id = identity > row_id if direction == "asc" else identity < row_id
        return and_(column.is_(None), after_id)

    strictly_after = column > value if direction == "asc" else column < value
    same_value_after_id = and_(
        column == value,
        identity > row_id if direction == "asc" else identity < row_id,
    )
    return or_(strictly_after, same_value_after_id, column.is_(None))
```

- [ ] **Step 4: Re-export from `db/__init__.py`**

```python
# packages/core/src/pigrocrm/core/db/__init__.py -- replace the whole file.
from pigrocrm.core.db.base import (
    Base,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid7,
)
from pigrocrm.core.db.search import escape_like
from pigrocrm.core.db.session import create_engine_from_settings, session_factory
from pigrocrm.core.db.sort import (
    CURSOR_MAX_LENGTH,
    SortDirection,
    SortKind,
    SortSpec,
    SortWhitelist,
    decode_cursor,
    encode_cursor,
    keyset_predicate,
    order_by,
)

__all__ = [
    "CURSOR_MAX_LENGTH",
    "Base",
    "PrimaryKeyMixin",
    "SoftDeleteMixin",
    "SortDirection",
    "SortKind",
    "SortSpec",
    "SortWhitelist",
    "TimestampMixin",
    "create_engine_from_settings",
    "decode_cursor",
    "encode_cursor",
    "escape_like",
    "keyset_predicate",
    "order_by",
    "session_factory",
    "uuid7",
]
```

- [ ] **Step 5: Declare the thirteen B-tree indexes on the models**

Append these entries to the `__table_args__` tuples changed in Task A2. Nothing else in those tuples moves.

```python
# customers/models.py -- append
        Index("ix_customers_created_at_id", "created_at", "id"),
        Index("ix_customers_updated_at_id", "updated_at", "id"),
        Index("ix_customers_ragione_sociale_id", "ragione_sociale", "id"),

# people/models.py -- append
        Index("ix_people_created_at_id", "created_at", "id"),
        Index("ix_people_updated_at_id", "updated_at", "id"),
        Index("ix_people_cognome_id", "cognome", "id"),
        # The second index the nullable column costs. A backward scan of the ascending
        # index above yields NULLS FIRST, which is not the order `order_by` declares.
        Index(
            "ix_people_cognome_desc_id",
            desc(nullslast(column("cognome"))),
            desc(column("id")),
        ),

# deals/models.py -- append
        Index("ix_deals_created_at_id", "created_at", "id"),
        Index("ix_deals_updated_at_id", "updated_at", "id"),
        Index("ix_deals_nome_id", "nome", "id"),

# documents/models.py -- append
        Index("ix_documents_created_at_id", "created_at", "id"),
        Index("ix_documents_updated_at_id", "updated_at", "id"),
        Index("ix_documents_titolo_id", "titolo", "id"),
```

`people/models.py` needs `from sqlalchemy import column, desc, nullslast` added to its import line. `ix_customers_ragione_sociale` (the plain single-column index shipped in slice 1) is **left in place**: it is not redundant for equality lookups, and removing an index is a separate decision from adding one.

- [ ] **Step 6: Write migration 0005**

```python
# packages/core/migrations/versions/0007_sort_indexes.py
"""B-tree (column, id) indexes for the sort whitelist

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-21

Residuo R9's other half. Without these, `ORDER BY ragione_sociale, id` on 50 000 rows is
an in-memory sort of the whole table, and the ordering feature is slower than the absence
of it.

Twelve ascending indexes, one per admitted (entity, column) pair, plus one descending
index for the single nullable column in the whitelist. A backward scan of an ascending
index yields `NULLS FIRST`, which is not the order `db/sort.py::order_by` declares -- so
`people.cognome` is the one column that costs two.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASCENDING: tuple[tuple[str, str, str], ...] = (
    ("ix_customers_created_at_id", "customers", "created_at"),
    ("ix_customers_updated_at_id", "customers", "updated_at"),
    ("ix_customers_ragione_sociale_id", "customers", "ragione_sociale"),
    ("ix_people_created_at_id", "people", "created_at"),
    ("ix_people_updated_at_id", "people", "updated_at"),
    ("ix_people_cognome_id", "people", "cognome"),
    ("ix_deals_created_at_id", "deals", "created_at"),
    ("ix_deals_updated_at_id", "deals", "updated_at"),
    ("ix_deals_nome_id", "deals", "nome"),
    ("ix_documents_created_at_id", "documents", "created_at"),
    ("ix_documents_updated_at_id", "documents", "updated_at"),
    ("ix_documents_titolo_id", "documents", "titolo"),
)

_DESCENDING_NULLABLE: tuple[tuple[str, str, str], ...] = (
    ("ix_people_cognome_desc_id", "people", "cognome"),
)


def upgrade() -> None:
    for name, table, column in _ASCENDING:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column}, id)")
    for name, table, column in _DESCENDING_NULLABLE:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"({column} DESC NULLS LAST, id DESC)"
        )


def downgrade() -> None:
    for name, _table, _column in reversed(_ASCENDING + _DESCENDING_NULLABLE):
        op.execute(f"DROP INDEX IF EXISTS {name}")
```

- [ ] **Step 7: Extend `HAND_MAINTAINED_INDEXES` and move the head assertion**

```python
# packages/core/tests/test_migrations.py -- add these thirteen names to the set declared
# in Task A2. The descending one is the only genuinely non-trivial shape; the twelve
# ascending ones are listed too, because a composite index dropped in silence is the same
# sequential scan as a GIN index dropped in silence.
    "ix_customers_created_at_id",
    "ix_customers_updated_at_id",
    "ix_customers_ragione_sociale_id",
    "ix_people_created_at_id",
    "ix_people_updated_at_id",
    "ix_people_cognome_id",
    "ix_people_cognome_desc_id",
    "ix_deals_created_at_id",
    "ix_deals_updated_at_id",
    "ix_deals_nome_id",
    "ix_documents_created_at_id",
    "ix_documents_updated_at_id",
    "ix_documents_titolo_id",
```

And change the two head assertions from `"0006"` to `"0007"`. Then append:

```python
def test_the_nullable_sort_column_has_a_descending_nulls_last_index() -> None:
    """The one index `compare_metadata` is least likely to notice and the one whose
    absence turns descending pagination over `people.cognome` into a full sort."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            definition = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' AND indexname = 'ix_people_cognome_desc_id'"
                )
            ).scalar_one()
        engine.dispose()

    assert "DESC NULLS LAST" in definition, definition
    assert "id DESC" in definition, definition
```

- [ ] **Step 8: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_sort_cursor.py packages/core/tests/test_migrations.py -v`
Expected: PASS.

If `test_migrations_produce_exactly_the_models_schema` reports a diff, the model `__table_args__` and the migration disagree about a name or a shape — fix the pair, never silence the test.

- [ ] **Step 9: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: everything passes.

- [ ] **Step 10: Commit**

```bash
git add packages/core/src/pigrocrm/core/db/sort.py \
        packages/core/src/pigrocrm/core/db/__init__.py \
        packages/core/src/pigrocrm/core/customers/models.py \
        packages/core/src/pigrocrm/core/people/models.py \
        packages/core/src/pigrocrm/core/deals/models.py \
        packages/core/src/pigrocrm/core/documents/models.py \
        packages/core/migrations/versions/0007_sort_indexes.py \
        packages/core/tests/test_sort_cursor.py \
        packages/core/tests/test_migrations.py
git commit -m "feat(core): sort whitelist and opaque composite keyset cursor"
```

---
### Task A4: R9 wired into the four repositories and services, and the documents search branch

**Files:**
- Modify: `packages/core/src/pigrocrm/core/customers/{schemas.py,repository.py,service.py}`
- Modify: `packages/core/src/pigrocrm/core/people/{schemas.py,repository.py,service.py}`
- Modify: `packages/core/src/pigrocrm/core/deals/{schemas.py,repository.py,service.py}`
- Modify: `packages/core/src/pigrocrm/core/documents/{schemas.py,repository.py,service.py}`
- Modify: `packages/core/tests/{test_customers.py,test_people.py,test_deals.py,test_documents_service.py}` (the `cursor` type changed; existing assertions comparing `next_cursor` to a `UUID` must compare to the encoded string)
- Create: `packages/core/tests/test_list_ordering.py`

**Interfaces:**
- Consumes: `SortSpec`, `SortWhitelist`, `encode_cursor`, `decode_cursor`, `keyset_predicate`, `order_by` from `pigrocrm.core.db` (Task A3); `escape_like` from `pigrocrm.core.db`.
- Produces, per entity `X ∈ {Customer, Person, Deal, Document}`:
  - `X_SORTS: SortWhitelist` at module level in `<entity>/schemas.py`
  - `XListQuery` gains `sort: str | None = None`, `dir: SortDirection = "asc"`, and `cursor: str | None = Field(default=None, max_length=CURSOR_MAX_LENGTH)` — **replacing** `cursor: UUID | None`
  - `XPage.next_cursor: str | None` — **replacing** `UUID | None`
  - `DocumentListQuery` additionally gains `search: SafeStr | None = None`
  - repository and service `list` signatures are unchanged in shape: `XRepository.list(self, query: XListQuery) -> list[X]`, `XService.list(self, query: XListQuery, actor: Actor) -> XPage`
- Task A5 wires these into the routers and tools; Task A6 tests the pagination property; Task A8's `SearchService` reuses `X_SORTS` for nothing — it has its own ordering — but Task A13's "vedi tutti" link relies on `DocumentListQuery.search` existing.

**The whitelists, fixed here so no later task invents a sixth key.**

| Entity | keys | default | nullable key |
|---|---|---|---|
| Customer | `created_at`, `updated_at`, `ragione_sociale` | `created_at` | — |
| Person | `created_at`, `updated_at`, `cognome` | `created_at` | `cognome` |
| Deal | `created_at`, `updated_at`, `nome` | `created_at` | — |
| Document | `created_at`, `updated_at`, `titolo` | `created_at` | — |

`created_at` is the default because it reproduces today's behaviour: UUIDv7 order *is* creation order, so a caller that sends no `sort` sees the same page it saw before this task. That is what makes the contract change contained to the `cursor` type.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_list_ordering.py
"""Residuo R9, closed for four entities.

The `sort` parameter is a whitelist and not a column name, and that is a security
property, not tidiness: a column name taken from a query string and interpolated into
`ORDER BY` is an injection point, and one taken from a query string and passed to
`getattr` on a model is an information leak (`ORDER BY password_hash` orders by a secret
even though it never returns it).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate, CustomerListQuery
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.db import decode_cursor
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.people.models import Person
from pigrocrm.core.people.schemas import PersonListQuery
from pigrocrm.core.people.service import PersonService

ADMIN = Actor(id=None, type="system", role="admin")


def _customer(service: CustomerService, ragione_sociale: str) -> None:
    service.create(CustomerCreate(ragione_sociale=ragione_sociale), ADMIN)


def test_default_sort_reproduces_creation_order(db_session: Session) -> None:
    """The compatibility guarantee that keeps this a cursor-type change and nothing
    more: a caller that sends no `sort` sees exactly the page it saw before."""
    service = CustomerService(db_session)
    for name in ("Terza", "Prima", "Seconda"):
        _customer(service, name)

    page = service.list(CustomerListQuery(limit=10), ADMIN)
    assert [c.ragione_sociale for c in page.items] == ["Terza", "Prima", "Seconda"]


def test_sorting_by_the_identifying_column_ascending_and_descending(
    db_session: Session,
) -> None:
    service = CustomerService(db_session)
    for name in ("Gamma", "Alfa", "Beta"):
        _customer(service, name)

    ascending = service.list(
        CustomerListQuery(sort="ragione_sociale", dir="asc", limit=10), ADMIN
    )
    descending = service.list(
        CustomerListQuery(sort="ragione_sociale", dir="desc", limit=10), ADMIN
    )

    assert [c.ragione_sociale for c in ascending.items] == ["Alfa", "Beta", "Gamma"]
    assert [c.ragione_sociale for c in descending.items] == ["Gamma", "Beta", "Alfa"]


def test_an_unknown_sort_key_is_refused_by_name(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as caught:
        CustomerService(db_session).list(
            CustomerListQuery(sort="note", limit=10), ADMIN
        )
    assert caught.value.details["field"] == "sort"
    assert "ragione_sociale" in caught.value.details["expected"]


def test_next_cursor_is_an_opaque_string_carrying_the_sort_value(
    db_session: Session,
) -> None:
    from pigrocrm.core.customers.schemas import CUSTOMER_SORTS

    service = CustomerService(db_session)
    for name in ("Alfa", "Beta", "Gamma"):
        _customer(service, name)

    first = service.list(
        CustomerListQuery(sort="ragione_sociale", dir="asc", limit=2), ADMIN
    )
    assert first.next_cursor is not None
    assert isinstance(first.next_cursor, str)

    spec = CUSTOMER_SORTS.resolve("ragione_sociale")
    value, row_id = decode_cursor(spec, first.next_cursor)
    assert value == "Beta"
    assert row_id == first.items[-1].id


def test_paging_with_the_cursor_returns_the_rest_exactly_once(db_session: Session) -> None:
    service = CustomerService(db_session)
    for name in ("Alfa", "Beta", "Gamma", "Delta", "Epsilon"):
        _customer(service, name)

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = service.list(
            CustomerListQuery(sort="ragione_sociale", dir="asc", limit=2, cursor=cursor),
            ADMIN,
        )
        seen.extend(c.ragione_sociale for c in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert seen == ["Alfa", "Beta", "Delta", "Epsilon", "Gamma"]
    assert len(seen) == len(set(seen))


def test_paging_a_nullable_sort_column_reaches_the_null_tail(db_session: Session) -> None:
    """`people.cognome` is nullable, and the null tail is the half that gets lost."""
    for cognome in ("Bianchi", None, "Rossi", None):
        db_session.add(Person(nome="Marco", cognome=cognome, custom_fields={}))
    db_session.flush()

    service = PersonService(db_session)
    seen: list[str | None] = []
    cursor: str | None = None
    while True:
        page = service.list(
            PersonListQuery(sort="cognome", dir="asc", limit=1, cursor=cursor), ADMIN
        )
        seen.extend(p.cognome for p in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert seen == ["Bianchi", "Rossi", None, None]


def test_documents_can_be_searched_by_title(db_session: Session) -> None:
    """The branch spec §8.1 assumes exists and `DocumentRepository.list` did not have.
    Task A13's "vedi tutti" link lands on it."""
    from pigrocrm.core.customers.models import Customer
    from pigrocrm.core.documents.models import Document
    from pigrocrm.core.documents.schemas import DocumentListQuery
    from pigrocrm.core.documents.repository import DocumentRepository

    customer = Customer(ragione_sociale="Cliente", nazione="IT", custom_fields={})
    db_session.add(customer)
    db_session.flush()
    for titolo in ("Offerta impianti 2026", "Verbale riunione", "Offerta_speciale"):
        db_session.add(
            Document(
                customer_id=customer.id, tipo="documento", titolo=titolo,
                versione_corrente=1, custom_fields={},
            )
        )
    db_session.flush()

    repo = DocumentRepository(db_session)
    found = repo.list(DocumentListQuery(search="offerta", limit=10))
    assert sorted(d.titolo for d in found) == ["Offerta impianti 2026", "Offerta_speciale"]

    # `_` is a LIKE metacharacter: unescaped, "Offerta_speciale" would also be matched by
    # "offertaXspeciale". `escape_like` is what stops that.
    literal = repo.list(DocumentListQuery(search="offerta_speciale", limit=10))
    assert [d.titolo for d in literal] == ["Offerta_speciale"]


def test_sorting_by_updated_at_reflects_a_touch(db_session: Session) -> None:
    service = CustomerService(db_session)
    for name in ("Alfa", "Beta"):
        _customer(service, name)

    first = service.list(CustomerListQuery(sort="ragione_sociale", limit=10), ADMIN)
    oldest = first.items[0]
    # Move `updated_at` back so the ordering is unambiguous without sleeping.
    db_session.execute(
        Person.__table__.select().limit(0)  # no-op, keeps the import used
    )
    from pigrocrm.core.customers.models import Customer as CustomerModel

    row = db_session.get(CustomerModel, oldest.id)
    assert row is not None
    row.updated_at = datetime.now(UTC) + timedelta(hours=1)
    db_session.flush()

    newest_first = service.list(
        CustomerListQuery(sort="updated_at", dir="desc", limit=10), ADMIN
    )
    assert newest_first.items[0].id == oldest.id
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_list_ordering.py -v`
Expected: every test FAILS. The first failures are `pydantic_core.ValidationError: Unexpected keyword argument` for `sort`/`dir` on `CustomerListQuery`, and `ImportError: cannot import name 'CUSTOMER_SORTS'`.

- [ ] **Step 3: Declare the whitelists and change the query schemas**

```python
# packages/core/src/pigrocrm/core/customers/schemas.py
# Add to the imports:
#   from pigrocrm.core.customers.models import Customer
#   from pigrocrm.core.db import CURSOR_MAX_LENGTH, SortDirection, SortSpec, SortWhitelist
# and drop `from uuid import UUID` only if nothing else in the file uses it (CustomerRead
# does, so keep it).

# Residuo R9. Three keys and no more: every admitted column costs a `(column, id)` B-tree
# index (migration 0005), and a nullable one costs two. The list is short for that reason,
# not out of caution.
CUSTOMER_SORTS = SortWhitelist(
    specs=(
        SortSpec(key="created_at", column=Customer.created_at, kind="datetime",
                 nullable=False),
        SortSpec(key="updated_at", column=Customer.updated_at, kind="datetime",
                 nullable=False),
        SortSpec(key="ragione_sociale", column=Customer.ragione_sociale, kind="text",
                 nullable=False),
    ),
    default_key="created_at",
)


class CustomerListQuery(BaseModel):
    search: SafeStr | None = None
    stato: SafeStr | None = None
    custom: dict[str, Any] | None = None
    limit: int = Field(default=50, ge=1, le=200)
    # `str`, not `UUID`: ordering by a non-unique column needs the pair
    # `(sort value, id)`, and the pair is opaque so that a null is representable -- an
    # empty string in a query parameter is indistinguishable from a null. The frontend
    # echoes `next_cursor` back verbatim and never parses it. See db/sort.py.
    cursor: str | None = Field(default=None, max_length=CURSOR_MAX_LENGTH)
    sort: SafeStr | None = None
    dir: SortDirection = "asc"


class CustomerPage(BaseModel):
    items: list[CustomerRead]
    next_cursor: str | None
```

Repeat verbatim, with names swapped, in the other three:

```python
# people/schemas.py
PERSON_SORTS = SortWhitelist(
    specs=(
        SortSpec(key="created_at", column=Person.created_at, kind="datetime",
                 nullable=False),
        SortSpec(key="updated_at", column=Person.updated_at, kind="datetime",
                 nullable=False),
        # The one nullable sort column in the whole whitelist, and the reason
        # `order_by` declares NULLS LAST explicitly in both directions.
        SortSpec(key="cognome", column=Person.cognome, kind="text", nullable=True),
    ),
    default_key="created_at",
)
# PersonListQuery: same three new fields; PersonPage.next_cursor: str | None

# deals/schemas.py
DEAL_SORTS = SortWhitelist(
    specs=(
        SortSpec(key="created_at", column=Deal.created_at, kind="datetime",
                 nullable=False),
        SortSpec(key="updated_at", column=Deal.updated_at, kind="datetime",
                 nullable=False),
        SortSpec(key="nome", column=Deal.nome, kind="text", nullable=False),
    ),
    default_key="created_at",
)
# DealListQuery: same three new fields; DealPage.next_cursor: str | None

# documents/schemas.py
DOCUMENT_SORTS = SortWhitelist(
    specs=(
        SortSpec(key="created_at", column=Document.created_at, kind="datetime",
                 nullable=False),
        SortSpec(key="updated_at", column=Document.updated_at, kind="datetime",
                 nullable=False),
        SortSpec(key="titolo", column=Document.titolo, kind="text", nullable=False),
    ),
    default_key="created_at",
)


class DocumentListQuery(BaseModel):
    customer_id: UUID | None = None
    deal_id: UUID | None = None
    tipo: DocumentTipo | None = None
    stato: OfferState | None = None
    # New in slice 6: spec §8.1 makes `titolo` searchable, and Task A13's "vedi tutti"
    # link for the Documento class lands on this filter. SafeStr for the same reason the
    # other three carry it.
    search: SafeStr | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=CURSOR_MAX_LENGTH)
    sort: SafeStr | None = None
    dir: SortDirection = "asc"
```

- [ ] **Step 4: Change the four repositories**

```python
# packages/core/src/pigrocrm/core/customers/repository.py -- replace `list` only.
# Imports gain: from pigrocrm.core.db import decode_cursor, keyset_predicate, order_by
# and from pigrocrm.core.customers.schemas import CUSTOMER_SORTS

    def list(self, query: CustomerListQuery) -> list[Customer]:
        stmt = select(Customer).where(Customer.deleted_at.is_(None))

        if query.search:
            # escape_like neutralizes "%"/"_"/"\" in the *user's* term before it is
            # wrapped in the wildcard "%...%" this method builds. Since slice 6 this
            # predicate is served by ix_customers_*_trgm, which is partial on
            # `deleted_at IS NULL` -- the clause above is what makes the index usable.
            like = f"%{escape_like(query.search.lower())}%"
            stmt = stmt.where(
                or_(
                    Customer.ragione_sociale.ilike(like, escape="\\"),
                    Customer.partita_iva.ilike(like, escape="\\"),
                    Customer.email.ilike(like, escape="\\"),
                    Customer.codice_fiscale.ilike(like, escape="\\"),
                )
            )
        if query.stato:
            stmt = stmt.where(Customer.stato == query.stato)
        if query.custom:
            # JSONB containment, served by the GIN index.
            stmt = stmt.where(Customer.custom_fields.contains(query.custom))

        # Residuo R9: keyset pagination over a whitelisted column, ordered
        # `col <dir> NULLS LAST, id <dir>`. `resolve` raises ValidationFailed on an
        # unknown key, so an injected column name never reaches ORDER BY.
        spec = CUSTOMER_SORTS.resolve(query.sort)
        if query.cursor:
            value, row_id = decode_cursor(spec, query.cursor)
            stmt = stmt.where(keyset_predicate(spec, query.dir, value, row_id))

        return list(
            self.session.execute(
                stmt.order_by(*order_by(spec, query.dir)).limit(query.limit + 1)
            ).scalars()
        )
```

`people/repository.py` and `deals/repository.py` take the identical treatment with `PERSON_SORTS` / `DEAL_SORTS` and their own existing filter branches untouched. `documents/repository.py` additionally gains the search branch it never had:

```python
# packages/core/src/pigrocrm/core/documents/repository.py -- replace `list` only.
# Imports gain: from pigrocrm.core.db import (decode_cursor, escape_like,
#   keyset_predicate, order_by) and from pigrocrm.core.documents.schemas import
#   DOCUMENT_SORTS

    def list(self, query: DocumentListQuery) -> list[Document]:
        stmt = select(Document).where(Document.deleted_at.is_(None))
        if query.customer_id:
            stmt = stmt.where(Document.customer_id == query.customer_id)
        if query.deal_id:
            stmt = stmt.where(Document.deal_id == query.deal_id)
        if query.tipo:
            stmt = stmt.where(Document.tipo == query.tipo)
        if query.stato:
            stmt = stmt.where(Document.stato == query.stato)
        if query.search:
            # New in slice 6. One column, so no `or_`: spec §8.1 searches `titolo` and
            # nothing else on this table -- a document's body lives in storage, not in a
            # column, and its Markdown source is explicitly out of scope (§8.1).
            like = f"%{escape_like(query.search.lower())}%"
            stmt = stmt.where(Document.titolo.ilike(like, escape="\\"))

        spec = DOCUMENT_SORTS.resolve(query.sort)
        if query.cursor:
            value, row_id = decode_cursor(spec, query.cursor)
            stmt = stmt.where(keyset_predicate(spec, query.dir, value, row_id))

        return list(
            self.session.execute(
                stmt.order_by(*order_by(spec, query.dir)).limit(query.limit + 1)
            ).scalars()
        )
```

- [ ] **Step 5: Change the four services' `next_cursor`**

```python
# packages/core/src/pigrocrm/core/customers/service.py -- replace `list` only.
# Imports gain: from pigrocrm.core.db import encode_cursor
# and CUSTOMER_SORTS from .schemas

    # `list` must stay the last method defined in this class -- an unconditional project
    # rule (`test_module_imports.py`): defining a method named `list` rebinds that name in
    # the *class* namespace, so any later method whose own return annotation is a bare
    # `list[...]` would resolve `list` to this method instead of the builtin and fail at
    # import time on Python 3.13.
    def list(self, query: CustomerListQuery, actor: Actor) -> CustomerPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        # The cursor encodes `(sort value, id)` of the last returned row, not the bare id:
        # ordering by a non-unique column cannot resume from an id alone.
        spec = CUSTOMER_SORTS.resolve(query.sort)
        next_cursor = (
            encode_cursor(spec, getattr(items[-1], spec.key), items[-1].id)
            if has_more and items
            else None
        )
        return CustomerPage(
            items=[CustomerRead.model_validate(c) for c in items],
            next_cursor=next_cursor,
        )
```

`getattr(items[-1], spec.key)` is safe precisely because `spec.key` came out of the whitelist: it is one of three literals declared in this module, never a caller string. The other three services take the identical shape with their own names.

- [ ] **Step 6: Repair the existing tests the contract change breaks**

Search for every assertion that treats `next_cursor` as a `UUID`:

Run: `grep -rn "next_cursor" packages/core/tests apps/api/tests apps/mcp/tests apps/web/src`

Each hit that compares to `.id` becomes a comparison through `decode_cursor`. The shape:

```python
# before
assert page.next_cursor == rows[1].id
# after
from pigrocrm.core.customers.schemas import CUSTOMER_SORTS
from pigrocrm.core.db import decode_cursor

assert page.next_cursor is not None
_value, row_id = decode_cursor(CUSTOMER_SORTS.resolve(None), page.next_cursor)
assert row_id == rows[1].id
```

Hits that only assert `next_cursor is None` or `is not None` need no change. Hits that feed `next_cursor` straight back in as `cursor` need no change either — that is the intended usage and it now type-checks as `str`.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_list_ordering.py packages/core/tests/test_customers.py packages/core/tests/test_people.py packages/core/tests/test_deals.py packages/core/tests/test_documents_service.py -v`
Expected: PASS.

- [ ] **Step 8: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: `mypy` reports errors in `apps/api` and `apps/mcp` where a `UUID` is still passed as `cursor`. **That is the contract change being caught by the type checker, exactly as intended.** Leave those for Task A5; this task's own gate is `uv run pytest -q` green and `mypy packages/core/src` clean.

Run: `uv run mypy packages/core/src`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add packages/core/src/pigrocrm/core/customers/ \
        packages/core/src/pigrocrm/core/people/ \
        packages/core/src/pigrocrm/core/deals/ \
        packages/core/src/pigrocrm/core/documents/ \
        packages/core/tests/test_list_ordering.py \
        packages/core/tests/test_customers.py \
        packages/core/tests/test_people.py \
        packages/core/tests/test_deals.py \
        packages/core/tests/test_documents_service.py
git commit -m "feat(core): ordering and composite cursors on four lists, closing R9"
```

---
### Task A5: `sort`, `dir` and the string cursor across both adapters

**Files:**
- Modify: `apps/api/src/pigrocrm_api/routers/{customers.py,people.py,deals.py,documents.py}`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`
- Modify: `apps/api/tests/test_entities_api.py`
- Modify: `apps/mcp/tests/test_mcp_tools.py`
- Create: `apps/api/tests/test_list_sorting_api.py`

**Interfaces:**
- Consumes: `CustomerListQuery`, `PersonListQuery`, `DealListQuery`, `DocumentListQuery` with `sort: str | None`, `dir: SortDirection`, `cursor: str | None` (Task A4); `CURSOR_MAX_LENGTH` from `pigrocrm.core.db`.
- Produces: on `GET /api/customers`, `/api/people`, `/api/deals`, `/api/documents` — query parameters `sort: str | None`, `dir: "asc" | "desc" = "asc"`, `cursor: str | None` (was `UUID | None`), and on documents additionally `search: str | None`. The MCP tools `search_customers`, `search_people`, `search_deals`, `list_documents` gain `sort` and `dir` and their `cursor` parameter stops being parsed as a UUID.
- Task A11 adds a fifth endpoint; Task A12 regenerates the TypeScript client against this shape.

**Why the MCP change is smaller than it looks.** `apps/mcp/src/pigrocrm_mcp/tools/__init__.py` already declares `cursor: str | None = None` at the tool boundary and converts with `UUID(cursor) if cursor else None`. Only the conversion goes; the tool's own signature and JSON Schema are unchanged, so no agent-facing contract moves. The API is where the break is.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_list_sorting_api.py
"""The HTTP half of residuo R9.

`dir` is spelled `dir` and not `direction` because the spec fixes it (§8.4) and because
`dir` is what the frontend query key will carry; it shadows no Python builtin at module
scope here since it is only ever a parameter name.
"""

import pytest
from fastapi.testclient import TestClient


def test_sorting_by_the_identifying_column(client: TestClient, admin_cookie: dict[str, str]) -> None:
    for name in ("Gamma Srl", "Alfa Srl", "Beta Srl"):
        created = client.post("/api/customers", json={"ragione_sociale": name},
                             cookies=admin_cookie)
        assert created.status_code == 201

    response = client.get(
        "/api/customers", params={"sort": "ragione_sociale", "dir": "asc", "limit": 10},
        cookies=admin_cookie,
    )
    assert response.status_code == 200
    assert [c["ragione_sociale"] for c in response.json()["items"]] == [
        "Alfa Srl", "Beta Srl", "Gamma Srl",
    ]


def test_next_cursor_is_a_string_in_the_response_body(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    for name in ("Alfa Srl", "Beta Srl", "Gamma Srl"):
        client.post("/api/customers", json={"ragione_sociale": name}, cookies=admin_cookie)

    response = client.get(
        "/api/customers", params={"sort": "ragione_sociale", "limit": 2},
        cookies=admin_cookie,
    )
    body = response.json()
    assert isinstance(body["next_cursor"], str)

    second = client.get(
        "/api/customers",
        params={"sort": "ragione_sociale", "limit": 2, "cursor": body["next_cursor"]},
        cookies=admin_cookie,
    )
    assert second.status_code == 200
    assert [c["ragione_sociale"] for c in second.json()["items"]] == ["Gamma Srl"]


@pytest.mark.parametrize("path", ["/api/customers", "/api/people", "/api/deals",
                                  "/api/documents"])
def test_an_unknown_sort_key_is_a_422_naming_the_field(
    client: TestClient, admin_cookie: dict[str, str], path: str
) -> None:
    response = client.get(path, params={"sort": "note"}, cookies=admin_cookie)
    assert response.status_code == 422
    body = response.json()
    assert body["field"] == "sort", body


@pytest.mark.parametrize("path", ["/api/customers", "/api/people", "/api/deals",
                                  "/api/documents"])
def test_an_unknown_direction_is_a_422(
    client: TestClient, admin_cookie: dict[str, str], path: str
) -> None:
    """`dir` is a Literal, so FastAPI rejects it before the service is reached -- which is
    why this assertion is on the status code and not on a `field` key: a FastAPI
    validation error is the `application/json` HTTPValidationError shape, not the
    problem+json shape."""
    response = client.get(path, params={"dir": "sideways"}, cookies=admin_cookie)
    assert response.status_code == 422


def test_a_garbage_cursor_is_a_422_and_not_a_500(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    response = client.get(
        "/api/customers", params={"cursor": "not-a-cursor"}, cookies=admin_cookie
    )
    assert response.status_code == 422
    assert response.json()["field"] == "cursor"


def test_an_over_long_cursor_is_refused_before_it_is_decoded(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    response = client.get(
        "/api/customers", params={"cursor": "x" * 5000}, cookies=admin_cookie
    )
    assert response.status_code == 422


def test_documents_accept_a_search_term(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    response = client.get(
        "/api/documents", params={"search": "offerta"}, cookies=admin_cookie
    )
    assert response.status_code == 200
    assert "items" in response.json()


def test_the_openapi_document_types_cursor_as_a_string(client: TestClient) -> None:
    """The mechanism slice 1 §10.2 put in place for exactly this change: the generated
    TypeScript client must break on the type, not in production."""
    schema = client.get("/openapi.json").json()
    params = schema["paths"]["/api/customers"]["get"]["parameters"]
    cursor = next(p for p in params if p["name"] == "cursor")
    assert "string" in str(cursor["schema"]), cursor
    assert "uuid" not in str(cursor["schema"]).lower(), cursor
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest apps/api/tests/test_list_sorting_api.py -v`
Expected: the sorting tests FAIL with `422` (FastAPI does not know the `sort` parameter and it is silently ignored, so the order is creation order), and `test_the_openapi_document_types_cursor_as_a_string` FAILS because the schema still says `format: uuid`.

- [ ] **Step 3: Change the four routers**

```python
# apps/api/src/pigrocrm_api/routers/customers.py -- replace `list_customers` only.
# Imports gain: from pigrocrm.core.db import CURSOR_MAX_LENGTH, SortDirection
# `from uuid import UUID` stays — the path parameters still use it.

@router.get("", response_model=CustomerPage)
def list_customers(
    session: SessionDep,
    actor: ActorDep,
    # SafeStr here, not just on Create/Update: these are ordinary query parameters, not
    # schema fields, so the guard has to sit on the parameter itself for FastAPI's own
    # validation to catch a NUL byte as a 422 before CustomerListQuery is hand-built.
    search: Annotated[SafeStr | None, Query()] = None,
    stato: Annotated[SafeStr | None, Query()] = None,
    custom: Annotated[list[SafeStr] | None, Query(description=CUSTOM_QUERY_DESCRIPTION)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    # `str`, not `UUID`, since slice 6: the cursor encodes `(sort value, id)` so that
    # ordering by a non-unique or nullable column can resume. Opaque by design — clients
    # echo `next_cursor` back and never parse it. `max_length` here as well as on the
    # schema, so an oversized value is refused by FastAPI before the decoder sees it.
    cursor: Annotated[str | None, Query(max_length=CURSOR_MAX_LENGTH)] = None,
    sort: Annotated[SafeStr | None, Query(description="created_at | updated_at | ragione_sociale")] = None,
    dir: Annotated[SortDirection, Query()] = "asc",
) -> CustomerPage:
    query = CustomerListQuery(
        search=search,
        stato=stato,
        custom=parse_custom_filter(custom),
        limit=limit,
        cursor=cursor,
        sort=sort,
        dir=dir,
    )
    return CustomerService(session).list(query, actor)
```

`people.py` and `deals.py` take the identical shape, with `description="created_at | updated_at | cognome"` and `"created_at | updated_at | nome"` respectively, and their own existing filters untouched. `documents.py` additionally gains the `search` parameter:

```python
# apps/api/src/pigrocrm_api/routers/documents.py -- replace the list endpoint only.
@router.get("", response_model=DocumentPage)
def list_documents(
    session: SessionDep,
    actor: ActorDep,
    customer_id: Annotated[UUID | None, Query()] = None,
    deal_id: Annotated[UUID | None, Query()] = None,
    tipo: Annotated[SafeStr | None, Query()] = None,
    stato: Annotated[SafeStr | None, Query()] = None,
    search: Annotated[SafeStr | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=CURSOR_MAX_LENGTH)] = None,
    sort: Annotated[SafeStr | None, Query(description="created_at | updated_at | titolo")] = None,
    dir: Annotated[SortDirection, Query()] = "asc",
) -> DocumentPage:
    query = DocumentListQuery(
        customer_id=customer_id,
        deal_id=deal_id,
        tipo=tipo,
        stato=stato,
        search=search,
        limit=limit,
        cursor=cursor,
        sort=sort,
        dir=dir,
    )
    return DocumentService(session, storage).list(query, actor)
```

Keep whatever `storage` dependency that endpoint already declares; only the parameter list and the `DocumentListQuery` construction change.

- [ ] **Step 4: Change the MCP tools**

```python
# apps/mcp/src/pigrocrm_mcp/tools/__init__.py
# In `search_customers`, `search_people`, `search_deals` and `list_documents`:
#   * add two parameters, immediately before `cursor`:
#         sort: str | None = None,
#         dir: str = "asc",
#   * pass them through, and stop parsing the cursor as a UUID.
# `search_customers` in full, as the exemplar:

    @mcp.tool()
    @guard
    def search_customers(
        search: str | None = None,
        stato: str | None = None,
        custom: dict[str, Any] | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
        sort: str | None = None,
        dir: str = "asc",
    ) -> dict[str, Any]:
        """Cerca clienti per ragione sociale, P.IVA, codice fiscale o email.
        `custom` filtra sui campi personalizzati per uguaglianza esatta (es.
        {"settore": "IT"}); chiama `describe_schema` per conoscere le chiavi
        disponibili. `sort` accetta `created_at`, `updated_at` o `ragione_sociale`,
        `dir` accetta `asc` o `desc`. Per leggere la pagina successiva passa
        `next_cursor` come `cursor` nella chiamata seguente, senza interpretarlo.
        """
        return customers.search(
            context,
            CustomerListQuery(
                search=search, stato=stato, custom=custom,
                limit=cast(int, limit),
                # Since slice 6 the cursor is an opaque string, not a UUID: it encodes
                # `(sort value, id)`. Passing it through unparsed is the whole contract.
                cursor=cursor,
                sort=sort,
                dir=cast(SortDirection, dir),
            ),
        )
```

`dir` is `str` at the tool boundary and `cast` at the call, following the file's own documented "runtime-permissive, schema-only-strict" convention: an out-of-range value then raises `pydantic.ValidationError` inside `_guard`, which converts it to a domain error the agent can read, instead of failing in the SDK's pre-call `validate_arguments` where the message is not ours. Add `SortDirection` to the imports from `pigrocrm.core.db`.

`list_documents` also gains `search: str | None = None`, passed straight to `DocumentListQuery(search=search, …)`.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest apps/api/tests/test_list_sorting_api.py apps/api/tests/test_entities_api.py apps/mcp/tests/test_mcp_tools.py -v`
Expected: PASS. Any existing test in those files that asserted a UUID-shaped `next_cursor` is repaired the same way Task A4 Step 6 describes.

- [ ] **Step 6: Full gate, including the type check that was red at the end of Task A4**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: all green. The `mypy` errors Task A4 deliberately left are resolved here.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/pigrocrm_api/routers/customers.py \
        apps/api/src/pigrocrm_api/routers/people.py \
        apps/api/src/pigrocrm_api/routers/deals.py \
        apps/api/src/pigrocrm_api/routers/documents.py \
        apps/mcp/src/pigrocrm_mcp/tools/__init__.py \
        apps/api/tests/test_list_sorting_api.py \
        apps/api/tests/test_entities_api.py \
        apps/mcp/tests/test_mcp_tools.py
git commit -m "feat(api): sort and dir on four lists, cursor becomes an opaque string"
```

---

### Task A6: Criterion 13 — ordered pagination loses no row and repeats none

**Files:**
- Create: `packages/core/tests/test_keyset_pagination.py`

**Interfaces:**
- Consumes: `CustomerService.list`, `CustomerListQuery`, `CUSTOMER_SORTS`, `decode_cursor` (Task A4); the `db_engine` fixture.
- Produces: nothing importable. This task's deliverable is the executable criterion.

**Why it needs its own sessions.** `db_session` hands out one savepoint-backed session on one connection, so a "concurrent" insert made through it is not concurrent at all — it is the same transaction. Slice 3's plan records the same limitation for its numbering race. This test opens two sessions from `db_engine`, commits from one while the other pages, and cleans up in a `finally`.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_keyset_pagination.py
"""**Criterion 13.** Ordered pagination under concurrent insertion neither loses a row
nor returns one twice.

This is the property keyset pagination was chosen for and the only reason the composite
cursor is worth a contract change. Offset pagination fails it by construction: inserting a
row that sorts before the current page shifts every later row down by one, so page two
re-reads the last row of page one and page three skips one entirely.

The corpus is built and committed once, then a second connection inserts rows *while* the
first is paging. The assertions are deliberately weaker than "the union equals the final
table": a row inserted after the scan passed its position legitimately may or may not
appear. What must hold is exactly what the criterion states -- no duplicates, and every
row that was present both before and after the scan is in the union.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.customers.schemas import CustomerListQuery
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.db import session_factory

ADMIN = Actor(id=None, type="system", role="admin")
_PAGE = 25
_INITIAL = 300


@pytest.fixture
def committed_customers(db_engine: Engine) -> Iterator[set[UUID]]:
    """Real committed rows on their own connections, removed afterwards.

    Not the `db_session` fixture: its outer transaction makes two sessions on one
    connection, and nothing committed from one would be a concurrent write to the other.
    """
    factory = session_factory(db_engine)
    created: set[UUID] = set()
    with factory() as session:
        for index in range(_INITIAL):
            row = Customer(
                ragione_sociale=f"KEYSET {index:05d} Srl", nazione="IT", custom_fields={}
            )
            session.add(row)
            session.flush()
            created.add(row.id)
        session.commit()
    try:
        yield created
    finally:
        with factory() as session:
            session.execute(
                delete(Customer).where(Customer.ragione_sociale.like("KEYSET %"))
            )
            session.commit()


def _all_keyset_ids(session: Session) -> set[UUID]:
    return set(
        session.scalars(
            select(Customer.id).where(Customer.ragione_sociale.like("KEYSET %"))
        ).all()
    )


def test_ordered_paging_under_concurrent_inserts_loses_nothing_and_repeats_nothing(
    db_engine: Engine, committed_customers: set[UUID]
) -> None:
    factory = session_factory(db_engine)
    reader = factory()
    writer = factory()
    try:
        present_at_start = _all_keyset_ids(reader)

        service = CustomerService(reader)
        seen: list[UUID] = []
        cursor: str | None = None
        inserted = 0
        while True:
            page = service.list(
                CustomerListQuery(
                    search="KEYSET",
                    sort="ragione_sociale",
                    dir="asc",
                    limit=_PAGE,
                    cursor=cursor,
                ),
                ADMIN,
            )
            seen.extend(item.id for item in page.items)

            # A concurrent insert between every pair of pages, half of them sorting
            # *before* the page just read -- the case offset pagination gets wrong.
            if inserted < 8:
                prefix = "KEYSET 00000" if inserted % 2 == 0 else "KEYSET 99999"
                writer.add(
                    Customer(
                        ragione_sociale=f"{prefix} intruso {inserted} Srl",
                        nazione="IT",
                        custom_fields={},
                    )
                )
                writer.commit()
                inserted += 1

            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        reader.rollback()  # start a fresh snapshot before the closing read
        present_at_end = _all_keyset_ids(reader)

        assert len(seen) == len(set(seen)), (
            f"{len(seen) - len(set(seen))} row(s) were returned more than once"
        )
        stable = present_at_start & present_at_end
        missing = stable - set(seen)
        assert not missing, f"{len(missing)} row(s) present throughout were never returned"
    finally:
        reader.close()
        writer.close()


def test_the_same_property_holds_descending(
    db_engine: Engine, committed_customers: set[UUID]
) -> None:
    """Descending is served by a backward index scan and by the mirrored predicate, so it
    is a genuinely different code path in `keyset_predicate` and gets its own run."""
    factory = session_factory(db_engine)
    reader = factory()
    writer = factory()
    try:
        present_at_start = _all_keyset_ids(reader)
        service = CustomerService(reader)
        seen: list[UUID] = []
        cursor: str | None = None
        inserted = 0
        while True:
            page = service.list(
                CustomerListQuery(
                    search="KEYSET", sort="ragione_sociale", dir="desc",
                    limit=_PAGE, cursor=cursor,
                ),
                ADMIN,
            )
            seen.extend(item.id for item in page.items)
            if inserted < 8:
                prefix = "KEYSET 00000" if inserted % 2 == 0 else "KEYSET 99999"
                writer.add(
                    Customer(
                        ragione_sociale=f"{prefix} discendente {inserted} Srl",
                        nazione="IT", custom_fields={},
                    )
                )
                writer.commit()
                inserted += 1
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        reader.rollback()
        present_at_end = _all_keyset_ids(reader)

        assert len(seen) == len(set(seen))
        assert not (present_at_start & present_at_end) - set(seen)
    finally:
        reader.close()
        writer.close()


def test_the_scan_terminates_rather_than_looping(
    db_engine: Engine, committed_customers: set[UUID]
) -> None:
    """A keyset predicate that is `>=` instead of `>` returns the cursor row again on
    every page and the loop above never ends. Bounding the page count turns that into a
    named failure rather than a hung suite."""
    factory = session_factory(db_engine)
    with factory() as reader:
        service = CustomerService(reader)
        cursor: str | None = None
        pages = 0
        while pages <= (_INITIAL // _PAGE) + 5:
            page = service.list(
                CustomerListQuery(
                    search="KEYSET", sort="ragione_sociale", limit=_PAGE, cursor=cursor
                ),
                ADMIN,
            )
            pages += 1
            if page.next_cursor is None:
                return
            cursor = page.next_cursor
    pytest.fail(
        "pagination did not terminate: the keyset predicate is probably inclusive (>=) "
        "where it must be exclusive (>)"
    )
```

- [ ] **Step 2: Run it and watch it fail on purpose first**

Before running it green, prove it can go red. Temporarily change `keyset_predicate` in `packages/core/src/pigrocrm/core/db/sort.py` so the ascending same-value arm uses `identity >= row_id` instead of `identity > row_id`.

Run: `uv run pytest packages/core/tests/test_keyset_pagination.py -v`
Expected: `test_ordered_paging_under_concurrent_inserts_loses_nothing_and_repeats_nothing` FAILS with "row(s) were returned more than once", and `test_the_scan_terminates_rather_than_looping` FAILS with the termination message. **Revert the change.** A criterion that has never been observed to fail is not a criterion.

- [ ] **Step 3: Run it green**

Run: `uv run pytest packages/core/tests/test_keyset_pagination.py -v`
Expected: PASS, three tests.

- [ ] **Step 4: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add packages/core/tests/test_keyset_pagination.py
git commit -m "test(core): criterion 13, ordered keyset paging under concurrent inserts"
```

---
### Task A7: The search schemas and the §8.5 score, as one SQL expression

**Files:**
- Create: `packages/core/src/pigrocrm/core/search/__init__.py`
- Create: `packages/core/src/pigrocrm/core/search/schemas.py`
- Create: `packages/core/src/pigrocrm/core/search/scoring.py`
- Create: `packages/core/tests/test_search_scoring.py`

**Interfaces:**
- Consumes: `pigrocrm.core.validation.SafeStr`; `pigrocrm.core.db.escape_like`; `pigrocrm.core.errors.ValidationFailed`.
- Produces:
  - `packages/core/src/pigrocrm/core/search/schemas.py`:
    - `MIN_TERM_LENGTH = 3`, `PER_CLASS_LIMIT = 5`, `COUNT_CEILING = 200`
    - `SearchEntity = Literal["customer", "person", "deal", "document", "invoice"]`
    - `SearchQuery(BaseModel)` — `termine: SafeStr = Field(min_length=MIN_TERM_LENGTH, max_length=100)`, `limite: int = Field(default=PER_CLASS_LIMIT, ge=1, le=20)`
    - `SearchHit(BaseModel)` — `entity: SearchEntity`, `id: UUID`, `etichetta: str`, `sottotitolo: str | None`, `punteggio: Decimal`, `campo: str`
    - `SearchGroup(BaseModel)` — `entity: SearchEntity`, `hits: list[SearchHit]`, `totale: int`, `totale_e_un_minimo: bool`
    - `SearchResults(BaseModel)` — `termine: str`, `gruppi: list[SearchGroup]`
  - `packages/core/src/pigrocrm/core/search/scoring.py`:
    - `SCORE_EXACT = Decimal("1.00")`, `SCORE_PREFIX = Decimal("0.80")`, `SCORE_SUBSTRING_FACTOR = Decimal("0.60")`, `SCORE_FLOOR = Decimal("0.20")`, `SCORE_SCALE = 4`
    - `WEIGHT_IDENTIFYING = Decimal("1.00")`, `WEIGHT_CODE = Decimal("1.00")`, `WEIGHT_EMAIL = Decimal("0.90")`, `WEIGHT_CAUSALE = Decimal("0.80")`
    - `ScoredField` — frozen dataclass: `name: str`, `column: InstrumentedAttribute[Any]`, `weight: Decimal`
    - `field_score(field: ScoredField, term: str) -> ColumnElement[Decimal]`
    - `row_score(fields: Sequence[ScoredField], term: str) -> ColumnElement[Decimal]`
    - `best_field(fields: Sequence[ScoredField], term: str) -> ColumnElement[str]`
    - `matches_any(fields: Sequence[ScoredField], term: str) -> ColumnElement[bool]`
- Task A8 builds every entity branch out of `ScoredField`, `row_score`, `best_field` and `matches_any`, and applies `SCORE_FLOOR`.

**The score is computed in SQL, and that is a decision.** Computing it in Python would mean fetching every trigram match to rank it — the tail of a trigram scan on 50 000 rows is thousands of rows, and criterion 3's budget is 300 ms. Computing it in SQL lets `ORDER BY … LIMIT` discard the tail in the database. The cost is that the expression is the formula, so §8.5 is pinned by tests against real Postgres rather than by unit tests over pure functions.

**`similarity()` returns `real`, and it is cast to `numeric` immediately.** A float would violate the no-float rule for no benefit and would make `punteggio` render as `0.6000000238418579` in JSON. `::numeric` on a `real` is exact and deterministic for a given input, so criterion 4's byte-identical requirement survives.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_search_scoring.py
"""Spec §8.5's formula, pinned against real Postgres.

    punteggio_campo = 1.00  se lower(campo) = lower(termine)
                    = 0.80  se lower(campo) inizia con lower(termine)
                    = 0.60 × similarity(campo, termine)
    peso_campo      = 1.00  campo identificativo / codice
                    = 0.90  email
                    = 0.80  causale
    punteggio_riga  = max(peso_campo × punteggio_campo)

Exact and prefix scores are asserted to the cent, because they are literals. The
substring score is asserted only by *ordering* and by its bounds: the precise value of
`similarity()` is a pg_trgm implementation detail, and pinning it would make a Postgres
upgrade look like a defect in this file.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.search.scoring import (
    SCORE_EXACT,
    SCORE_FLOOR,
    SCORE_PREFIX,
    WEIGHT_EMAIL,
    WEIGHT_IDENTIFYING,
    ScoredField,
    best_field,
    field_score,
    matches_any,
    row_score,
)

_NAME = ScoredField(name="ragione_sociale", column=Customer.ragione_sociale,
                    weight=WEIGHT_IDENTIFYING)
_EMAIL = ScoredField(name="email", column=Customer.email, weight=WEIGHT_EMAIL)
_FIELDS = (_NAME, _EMAIL)


def _add(session: Session, ragione_sociale: str, email: str | None = None) -> Customer:
    row = Customer(
        ragione_sociale=ragione_sociale, email=email, nazione="IT", custom_fields={}
    )
    session.add(row)
    session.flush()
    return row


def _score(session: Session, row: Customer, term: str) -> Decimal:
    value = session.scalar(
        select(row_score(_FIELDS, term)).where(Customer.id == row.id)
    )
    assert value is not None
    return value


def test_an_exact_case_insensitive_match_scores_one(db_session: Session) -> None:
    row = _add(db_session, "Rossi Ingegneria Srl")
    assert _score(db_session, row, "rossi ingegneria srl") == SCORE_EXACT


def test_a_prefix_match_scores_zero_point_eight(db_session: Session) -> None:
    row = _add(db_session, "Rossi Ingegneria Srl")
    assert _score(db_session, row, "Rossi") == SCORE_PREFIX


def test_a_mid_word_match_scores_below_a_prefix_match(db_session: Session) -> None:
    """§16 criterion 4's second sentence: a prefix of a company name ranks above a
    match in the middle of a word."""
    prefix_row = _add(db_session, "Ingegneria Rossi Srl")
    middle_row = _add(db_session, "Grande Ingegneria Lombarda Srl")

    prefix = _score(db_session, prefix_row, "Ingegn")
    middle = _score(db_session, middle_row, "Ingegn")

    assert prefix == SCORE_PREFIX
    assert Decimal("0") < middle < prefix


def test_an_email_match_is_weighted_below_an_identifying_match(db_session: Session) -> None:
    by_name = _add(db_session, "Vulcano Srl")
    by_email = _add(db_session, "Altra Societa Srl", email="vulcano@example.it")

    assert _score(db_session, by_name, "Vulcano") == SCORE_PREFIX
    # 0.90 × 0.80 = 0.72: same field score, lower weight.
    assert _score(db_session, by_email, "Vulcano") == Decimal("0.7200")


def test_the_row_score_is_the_maximum_and_not_the_sum(db_session: Session) -> None:
    """Summing would let two mediocre matches outrank one exact one, and would make a
    row with more populated columns rank higher for no reason a user could explain."""
    both = _add(db_session, "Vulcano Srl", email="vulcano@example.it")
    assert _score(db_session, both, "Vulcano") == SCORE_PREFIX


def test_best_field_names_the_column_that_produced_the_score(db_session: Session) -> None:
    by_email = _add(db_session, "Altra Societa Srl", email="vulcano@example.it")
    name = db_session.scalar(
        select(best_field(_FIELDS, "Vulcano")).where(Customer.id == by_email.id)
    )
    assert name == "email"


def test_matches_any_is_true_only_for_a_row_with_a_trigram_match(
    db_session: Session,
) -> None:
    hit = _add(db_session, "Rossi Ingegneria Srl")
    miss = _add(db_session, "Quadrifoglio Logistica Spa")

    found = set(
        db_session.scalars(
            select(Customer.id).where(matches_any(_FIELDS, "ingegn"))
        ).all()
    )
    assert hit.id in found
    assert miss.id not in found


def test_a_null_column_never_wins_and_never_raises(db_session: Session) -> None:
    """`customers.email` is nullable. `GREATEST` in Postgres ignores NULLs, but
    `similarity(NULL, 'x')` is NULL and a CASE that returned NULL for every field would
    make the row score NULL — which would sort unpredictably rather than not matching."""
    row = _add(db_session, "Rossi Ingegneria Srl", email=None)
    assert _score(db_session, row, "Rossi") == SCORE_PREFIX


def test_the_floor_is_a_declared_constant_and_not_a_literal(db_session: Session) -> None:
    """Task A8 applies it; this pins the value so the two cannot drift."""
    assert SCORE_FLOOR == Decimal("0.20")


def test_a_like_metacharacter_in_the_term_is_escaped_in_the_prefix_test(
    db_session: Session,
) -> None:
    """The prefix arm builds a LIKE pattern, so it needs `escape_like` just as the
    substring filter does — otherwise searching `Rossi_` prefix-matches `RossiX`."""
    exact = _add(db_session, "Rossi_Ingegneria")
    other = _add(db_session, "RossiXIngegneria")

    assert _score(db_session, exact, "Rossi_") == SCORE_PREFIX
    assert _score(db_session, other, "Rossi_") < SCORE_PREFIX
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_search_scoring.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'pigrocrm.core.search'`.

- [ ] **Step 3: Write the schemas**

```python
# packages/core/src/pigrocrm/core/search/schemas.py
"""What the global search accepts and returns.

Spec §8.1 fixes the searched fields, §8.5 the ordering and the counting, §8.6 the three
interface states. The shape here is what makes those three states expressible without the
client inferring anything: `totale` is the real count and `totale_e_un_minimo` says
whether it was truncated, so "5 of 500" and "5 of 5" are different responses rather than
the same list of five.
"""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.validation import SafeStr

# Spec §8.3: a trigram index cannot serve a pattern from which no trigram can be
# extracted, so below three characters the search would be a sequential scan; and a
# two-character term on 50 000 customers returns thousands of rows, which is not an answer
# either. The palette says "continua a scrivere" and issues no request; this bound is the
# server-side half of the same rule.
MIN_TERM_LENGTH = 3
# A term longer than this is not a search, and the column being searched is at most 320
# characters anyway (`customers.email`).
MAX_TERM_LENGTH = 100
# Spec §8.5: the palette does not paginate. Five per class plus the real count.
PER_CLASS_LIMIT = 5
# Exact up to here, then declared as a minimum. Implemented as `count(*)` over a subquery
# with `LIMIT 201`: exact when exactness matters, cheap when it does not, never a lie.
COUNT_CEILING = 200

SearchEntity = Literal["customer", "person", "deal", "document", "invoice"]


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    termine: SafeStr = Field(min_length=MIN_TERM_LENGTH, max_length=MAX_TERM_LENGTH)
    limite: int = Field(default=PER_CLASS_LIMIT, ge=1, le=20)


class SearchHit(BaseModel):
    entity: SearchEntity
    id: UUID
    # What the palette renders on the row. Built by the repository from the entity's own
    # identifying columns, never by the frontend concatenating fields — that would be
    # business logic in the browser.
    etichetta: str
    sottotitolo: str | None
    # `Decimal`, never float: a float score renders as 0.6000000238418579 and would break
    # criterion 4's byte-identical requirement.
    punteggio: Decimal = Field(max_digits=6, decimal_places=4)
    # Which field produced the score. Shown as a hint ("P.IVA", "email") so a match on a
    # column the row does not display is not a mystery.
    campo: str


class SearchGroup(BaseModel):
    entity: SearchEntity
    hits: list[SearchHit]
    # The real count of matching rows, exact up to COUNT_CEILING.
    totale: int
    # True when `totale` is COUNT_CEILING and the real count may be higher. The palette
    # renders "oltre 200" for this case; it never renders "200".
    totale_e_un_minimo: bool


class SearchResults(BaseModel):
    termine: str
    gruppi: list[SearchGroup]
```

```python
# packages/core/src/pigrocrm/core/search/__init__.py
from pigrocrm.core.search.schemas import (
    COUNT_CEILING,
    MAX_TERM_LENGTH,
    MIN_TERM_LENGTH,
    PER_CLASS_LIMIT,
    SearchEntity,
    SearchGroup,
    SearchHit,
    SearchQuery,
    SearchResults,
)

__all__ = [
    "COUNT_CEILING",
    "MAX_TERM_LENGTH",
    "MIN_TERM_LENGTH",
    "PER_CLASS_LIMIT",
    "SearchEntity",
    "SearchGroup",
    "SearchHit",
    "SearchQuery",
    "SearchResults",
]
```

`SearchService` is added to this `__all__` by Task A8; it cannot be imported here yet because the module does not exist.

- [ ] **Step 4: Write the scoring expressions**

```python
# packages/core/src/pigrocrm/core/search/scoring.py
r"""Spec §8.5's score, as a SQL expression.

Computed in the database, not in Python, and that is a decision rather than a shortcut:
the tail of a trigram scan on 50 000 rows is thousands of rows, and ranking in Python
would mean fetching all of them to throw almost all away. Ranking in SQL lets
`ORDER BY … LIMIT` discard the tail before it crosses the wire, which is what makes
criterion 3's 300 ms budget reachable.

Two details that are easy to get wrong and expensive to rediscover.

**`similarity()` returns `real`.** It is cast to `numeric` the moment it appears. A float
would violate the project's no-float rule for no benefit and would render as
`0.6000000238418579` in JSON, which also breaks criterion 4's byte-identical requirement.
A `real` cast to `numeric` is exact and deterministic for a given input.

**The prefix arm builds a LIKE pattern, so it escapes.** Without `escape_like`, a term
ending in `_` prefix-matches any character in that position, and the score for
`Rossi_Ingegneria` and `RossiXIngegneria` would be identical. The substring filter has
always escaped; the prefix arm is new here and needs the same treatment.

There is no `lower()` around the trigram column anywhere: `similarity()` normalises to
lower case internally (`similarity('Rossi','rossi') = 1`), and wrapping the column would
make the `*_trgm` indexes unusable by `ILIKE` on the raw column (spec §8.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Numeric, case, func, literal, or_
from sqlalchemy.orm.attributes import InstrumentedAttribute

from pigrocrm.core.db import escape_like

SCORE_EXACT = Decimal("1.00")
SCORE_PREFIX = Decimal("0.80")
SCORE_SUBSTRING_FACTOR = Decimal("0.60")
# Rows below this are discarded: the tail of a trigram match is noise, and showing noise
# in a palette teaches the user to ignore it.
SCORE_FLOOR = Decimal("0.20")
# Four places. Two would collapse distinct substring matches into ties and make the
# ordering depend on the third sort key more often than it should.
SCORE_SCALE = 4

WEIGHT_IDENTIFYING = Decimal("1.00")
# A match on a fiscal code is wanted, not incidental: someone typing a VAT fragment knows
# exactly what they are looking for.
WEIGHT_CODE = Decimal("1.00")
WEIGHT_EMAIL = Decimal("0.90")
WEIGHT_CAUSALE = Decimal("0.80")

_NUMERIC = Numeric(6, SCORE_SCALE)


@dataclass(frozen=True)
class ScoredField:
    name: str
    column: InstrumentedAttribute[Any]
    weight: Decimal


def _like_prefix(term: str) -> str:
    return f"{escape_like(term.lower())}%"


def _like_anywhere(term: str) -> str:
    return f"%{escape_like(term.lower())}%"


def field_score(field: ScoredField, term: str) -> ColumnElement[Decimal]:
    """`peso × punteggio_campo`, or `0` when the column is NULL or does not match.

    Zero rather than NULL for the miss case: `GREATEST` ignores NULLs, but a row whose
    every field were NULL would score NULL and sort unpredictably instead of not matching
    at all.
    """
    column = field.column
    weight = literal(field.weight, type_=_NUMERIC)
    return func.coalesce(
        case(
            (column.is_(None), literal(Decimal("0.0000"), type_=_NUMERIC)),
            (func.lower(column) == term.lower(), literal(SCORE_EXACT, type_=_NUMERIC)),
            (
                func.lower(column).like(_like_prefix(term), escape="\\"),
                literal(SCORE_PREFIX, type_=_NUMERIC),
            ),
            else_=func.round(
                literal(SCORE_SUBSTRING_FACTOR, type_=_NUMERIC)
                * func.cast(func.similarity(column, term), _NUMERIC),
                SCORE_SCALE,
            ),
        )
        * weight,
        literal(Decimal("0.0000"), type_=_NUMERIC),
    ).label(f"score_{field.name}")


def row_score(fields: Sequence[ScoredField], term: str) -> ColumnElement[Decimal]:
    """`max(peso × punteggio_campo)` over the fields that matched.

    The maximum and not the sum: summing would let two mediocre matches outrank one exact
    one, and would rank a row higher merely for having more populated columns — an order
    no user could explain to themselves.
    """
    scores = [field_score(field, term) for field in fields]
    if len(scores) == 1:
        return func.round(scores[0], SCORE_SCALE).label("punteggio")
    return func.round(func.greatest(*scores), SCORE_SCALE).label("punteggio")


def best_field(fields: Sequence[ScoredField], term: str) -> ColumnElement[str]:
    """The name of the field that produced the row score.

    Declared in the same order as `fields`, so ties resolve to the earlier field — which
    is the identifying one by convention, and which keeps the output deterministic
    (criterion 4).
    """
    top = row_score(fields, term)
    branches = [
        (func.round(field_score(field, term), SCORE_SCALE) == top, literal(field.name))
        for field in fields
    ]
    return case(*branches, else_=literal(fields[0].name)).label("campo")


def matches_any(fields: Sequence[ScoredField], term: str) -> ColumnElement[bool]:
    """The filter, kept separate from the score so the planner sees a plain
    `ILIKE '%…%'` on an indexed column.

    This is the predicate the `*_trgm` indexes serve. Filtering on `row_score(...) >=
    floor` instead would be correct and would also be a sequential scan on every searched
    table, because a `CASE` over `similarity()` is not an indexable expression.
    """
    pattern = _like_anywhere(term)
    return or_(*(field.column.ilike(pattern, escape="\\") for field in fields))
```

If Task A2's measurement removed the `ESCAPE` clause, remove it from `matches_any` and from `field_score`'s prefix arm here too, in the same shape and with the same comment.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_search_scoring.py -v`
Expected: PASS, ten tests.

- [ ] **Step 6: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/search/ packages/core/tests/test_search_scoring.py
git commit -m "feat(search): the §8.5 relevance score as a numeric SQL expression"
```

---
### Task A8: `SearchRepository` and `SearchService`

**Files:**
- Create: `packages/core/src/pigrocrm/core/search/repository.py`
- Create: `packages/core/src/pigrocrm/core/search/service.py`
- Modify: `packages/core/src/pigrocrm/core/search/__init__.py`
- Create: `packages/core/tests/test_search_service.py`

**Interfaces:**
- Consumes: `ScoredField`, `row_score`, `best_field`, `matches_any`, `SCORE_FLOOR`, the four `WEIGHT_*` constants (Task A7); `SearchQuery`, `SearchHit`, `SearchGroup`, `SearchResults`, `COUNT_CEILING`, `PER_CLASS_LIMIT` (Task A7); `Actor`.
- Produces:
  - `SearchRepository(session: Session)` with `customers(term: str, limit: int) -> SearchGroup`, `people(...)`, `deals(...)`, `documents(...)` — identical signatures. Task C13 adds `invoices(...)`.
  - `SearchService(session: Session)` with exactly one public method: `search_everything(self, query: SearchQuery, actor: Actor) -> SearchResults`.
- Task A11 exposes `search_everything` over both adapters and registers `SearchService` in the architecture test's audited set; Task A9 asserts on the plans these queries produce; Task A10 asserts their determinism.

**One public method, and that is deliberate.** Task A11 must declare an MCP exclusion list that is *exactly* `update_automation_config`, so every other public method of every audited service needs a tool. `SearchService` having one public method means one tool, and no temptation to expose per-entity search twice — the four entity tools already exist from slice 1.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_search_service.py
"""Spec §8.1, §8.5 and §8.6's server half.

Three things get asserted here that a happy-path test would not reach: the floor discards
the trigram tail, the count is exact up to 200 and declared as a minimum beyond it, and a
soft-deleted row is not a search result.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.people.models import Person
from pigrocrm.core.search.schemas import COUNT_CEILING, SearchQuery
from pigrocrm.core.search.scoring import SCORE_FLOOR
from pigrocrm.core.search.service import SearchService

from .corpus import KNOWN_PARTITA_IVA, KNOWN_RAGIONE_SOCIALE, REFERENCE, build_corpus

READONLY = Actor(id=uuid7(), type="user", role="readonly")


def _groups(results: object) -> dict[str, object]:
    return {group.entity: group for group in results.gruppi}  # type: ignore[attr-defined]


def test_a_vat_fragment_finds_the_customer(db_session: Session) -> None:
    """The use case §17 names as 6A's reason to exist on its own."""
    build_corpus(db_session, REFERENCE)
    results = SearchService(db_session).search_everything(
        SearchQuery(termine="34567"), READONLY
    )
    customers = _groups(results)["customer"]
    assert KNOWN_RAGIONE_SOCIALE in [hit.etichetta for hit in customers.hits]


def test_an_exact_vat_number_ranks_the_customer_first(db_session: Session) -> None:
    """§16 criterion 4, first sentence."""
    build_corpus(db_session, REFERENCE)
    results = SearchService(db_session).search_everything(
        SearchQuery(termine=KNOWN_PARTITA_IVA), READONLY
    )
    customers = _groups(results)["customer"]
    assert customers.hits[0].etichetta == KNOWN_RAGIONE_SOCIALE
    assert customers.hits[0].campo == "partita_iva"
    assert customers.hits[0].punteggio == Decimal("1.0000")


def test_every_group_is_present_even_when_empty(db_session: Session) -> None:
    """§8.6's states are per-palette, not per-group, so the response always carries all
    four groups: a missing group and an empty group would render identically, and the
    client would have to guess which it was."""
    results = SearchService(db_session).search_everything(
        SearchQuery(termine="zzzqqq"), READONLY
    )
    assert [group.entity for group in results.gruppi] == [
        "customer", "person", "deal", "document",
    ]
    assert all(group.totale == 0 and group.hits == [] for group in results.gruppi)


def test_a_group_is_truncated_to_the_limit_and_reports_the_real_count(
    db_session: Session,
) -> None:
    for index in range(40):
        db_session.add(
            Customer(
                ragione_sociale=f"Vulcano Impianti {index} Srl", nazione="IT",
                custom_fields={},
            )
        )
    db_session.flush()

    results = SearchService(db_session).search_everything(
        SearchQuery(termine="Vulcano", limite=5), READONLY
    )
    customers = _groups(results)["customer"]
    assert len(customers.hits) == 5
    assert customers.totale == 40
    assert customers.totale_e_un_minimo is False


def test_beyond_the_ceiling_the_count_is_declared_as_a_minimum(
    db_session: Session,
) -> None:
    """Exact when exactness serves, cheap when it does not, never a lie (§8.5)."""
    for index in range(COUNT_CEILING + 25):
        db_session.add(
            Customer(
                ragione_sociale=f"Quadrifoglio {index} Srl", nazione="IT",
                custom_fields={},
            )
        )
    db_session.flush()

    results = SearchService(db_session).search_everything(
        SearchQuery(termine="Quadrifoglio"), READONLY
    )
    customers = _groups(results)["customer"]
    assert customers.totale == COUNT_CEILING
    assert customers.totale_e_un_minimo is True


def test_every_returned_hit_is_above_the_floor(db_session: Session) -> None:
    """The tail of a trigram match is noise, and showing noise in a palette teaches the
    user to ignore the palette."""
    build_corpus(db_session, REFERENCE)
    results = SearchService(db_session).search_everything(
        SearchQuery(termine="ingegneria", limite=20), READONLY
    )
    for group in results.gruppi:
        for hit in group.hits:
            assert hit.punteggio >= SCORE_FLOOR, (group.entity, hit)


def test_a_soft_deleted_row_is_not_a_result(db_session: Session) -> None:
    from datetime import UTC, datetime

    row = Customer(ragione_sociale="Cancellata Srl", nazione="IT", custom_fields={})
    db_session.add(row)
    db_session.flush()
    row.deleted_at = datetime.now(UTC)
    db_session.flush()

    results = SearchService(db_session).search_everything(
        SearchQuery(termine="Cancellata"), READONLY
    )
    assert _groups(results)["customer"].totale == 0


def test_people_are_found_by_first_name_by_surname_and_by_email(
    db_session: Session,
) -> None:
    db_session.add(Person(nome="Ludovica", cognome="Ferraresi",
                          email="lf@studio.example", custom_fields={}))
    db_session.flush()
    service = SearchService(db_session)

    for term in ("Ludovi", "Ferrar", "lf@studio"):
        group = _groups(service.search_everything(SearchQuery(termine=term), READONLY))["person"]
        assert group.totale == 1, term
        assert group.hits[0].etichetta == "Ludovica Ferraresi", term


def test_a_person_without_a_surname_has_a_label_and_no_trailing_space(
    db_session: Session,
) -> None:
    db_session.add(Person(nome="Ludovica", cognome=None, custom_fields={}))
    db_session.flush()
    group = _groups(
        SearchService(db_session).search_everything(SearchQuery(termine="Ludovi"), READONLY)
    )["person"]
    assert group.hits[0].etichetta == "Ludovica"


def test_a_deal_hit_carries_its_customer_as_the_subtitle(db_session: Session) -> None:
    """A palette row reading "Rifacimento impianti 42" with no client is not an answer.
    The subtitle is built by the repository, never by the browser concatenating fields."""
    ids = build_corpus(db_session, REFERENCE)
    customer = db_session.get(Customer, ids.customer_ids[0])
    assert customer is not None
    db_session.add(
        Deal(
            nome="Rifacimento cabina elettrica", customer_id=customer.id,
            pipeline_stage_id=ids.stage_open_id, probabilita=50, custom_fields={},
        )
    )
    db_session.flush()

    group = _groups(
        SearchService(db_session).search_everything(
            SearchQuery(termine="cabina elettrica"), READONLY
        )
    )["deal"]
    assert group.hits[0].etichetta == "Rifacimento cabina elettrica"
    assert group.hits[0].sottotitolo == customer.ragione_sociale


def test_a_document_hit_carries_its_type_as_the_subtitle(db_session: Session) -> None:
    ids = build_corpus(db_session, REFERENCE)
    db_session.add(
        Document(
            customer_id=ids.customer_ids[0], tipo="offerta",
            titolo="Capitolato speciale d'appalto", versione_corrente=1, custom_fields={},
        )
    )
    db_session.flush()

    group = _groups(
        SearchService(db_session).search_everything(
            SearchQuery(termine="capitolato speciale"), READONLY
        )
    )["document"]
    assert group.hits[0].etichetta == "Capitolato speciale d'appalto"
    assert group.hits[0].sottotitolo == "offerta"


def test_a_two_character_term_is_refused_by_the_schema(db_session: Session) -> None:
    """The server-side half of the three-character rule. The palette does not send it,
    and an agent that does gets a named validation error rather than a table scan."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SearchQuery(termine="ab")


def test_a_readonly_actor_can_search(db_session: Session) -> None:
    """Search is a read, and slice 4 §11 gives every dashboard read to every role. There
    is no new authorisation rule in this slice (§13)."""
    build_corpus(db_session, REFERENCE)
    results = SearchService(db_session).search_everything(
        SearchQuery(termine="Rossi"), READONLY
    )
    assert results.termine == "Rossi"


def test_search_service_exposes_exactly_one_public_method() -> None:
    """Task A11's exclusion list must be exactly `update_automation_config`, so every
    other public method of an audited service needs a tool. Pinning the count here makes
    a second method a failure in this file rather than a surprise in the architecture
    test."""
    import inspect

    public = {
        name
        for name, member in inspect.getmembers(SearchService, predicate=inspect.isfunction)
        if not name.startswith("_")
        and member.__qualname__.startswith("SearchService.")
    }
    assert public == {"search_everything"}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_search_service.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'pigrocrm.core.search.service'`.

- [ ] **Step 3: Write the repository**

```python
# packages/core/src/pigrocrm/core/search/repository.py
"""One branch per searched entity, and nothing that crosses two of them.

The shape of every branch is the same and the repetition is deliberate: a generic
"search any model" helper would need the label rule, the subtitle rule, the field set and
the weight set as parameters, which is four dictionaries keyed by entity plus a dispatch —
strictly more code than four explicit methods, and unreadable at the point where a plan
goes wrong.

`etichetta` and `sottotitolo` are built **here**, from the entity's own columns. Not in
the browser: composing "nome cognome" client-side is business logic in the frontend, and
the whole point of the two-adapter architecture is that an MCP agent sees the same label a
human does.

The floor is applied by repeating the score expression in `WHERE`, not by wrapping the
query in a subquery. Postgres cannot reference a select alias in `WHERE`, and the extra
evaluation costs nothing: `matches_any` has already narrowed the row set through the
trigram index, which is the only place a plan could go wrong.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, literal, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.people.models import Person
from pigrocrm.core.search.schemas import COUNT_CEILING, SearchEntity, SearchGroup, SearchHit
from pigrocrm.core.search.scoring import (
    SCORE_FLOOR,
    WEIGHT_CODE,
    WEIGHT_EMAIL,
    WEIGHT_IDENTIFYING,
    ScoredField,
    best_field,
    matches_any,
    row_score,
)

CUSTOMER_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("ragione_sociale", Customer.ragione_sociale, WEIGHT_IDENTIFYING),
    ScoredField("partita_iva", Customer.partita_iva, WEIGHT_CODE),
    ScoredField("codice_fiscale", Customer.codice_fiscale, WEIGHT_CODE),
    ScoredField("email", Customer.email, WEIGHT_EMAIL),
)
PERSON_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("cognome", Person.cognome, WEIGHT_IDENTIFYING),
    ScoredField("nome", Person.nome, WEIGHT_IDENTIFYING),
    ScoredField("email", Person.email, WEIGHT_EMAIL),
)
DEAL_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("nome", Deal.nome, WEIGHT_IDENTIFYING),
)
DOCUMENT_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("titolo", Document.titolo, WEIGHT_IDENTIFYING),
)


class SearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- shared plumbing -------------------------------------------------------

    def _count(self, model: type, fields: Sequence[ScoredField], term: str) -> tuple[int, bool]:
        """Exact up to COUNT_CEILING, then declared as a minimum.

        `count(*)` over a subquery with `LIMIT ceiling + 1`: the database stops reading
        once it has 201 rows, so the cost is bounded no matter how many rows match, and
        the answer is exact whenever exactness is what is being shown.
        """
        inner = (
            select(literal(1))
            .select_from(model)
            .where(
                model.deleted_at.is_(None),
                matches_any(fields, term),
                row_score(fields, term) >= SCORE_FLOOR,
            )
            .limit(COUNT_CEILING + 1)
            .subquery()
        )
        found = self.session.scalar(select(func.count()).select_from(inner)) or 0
        if found > COUNT_CEILING:
            return COUNT_CEILING, True
        return found, False

    def _scored(
        self, model: type, fields: Sequence[ScoredField], term: str, limit: int
    ) -> Select[tuple[object, object, object]]:
        """`punteggio DESC, updated_at DESC, id DESC`, limited.

        The third key exists because the order must be **total**: without it two runs over
        the same data can return the same set in a different order, and §16 criterion 4
        checks twenty runs for a byte-identical response. The second key is §8.5's own —
        at equal score, what was touched most recently is more likely what is wanted.
        """
        return (
            select(model, row_score(fields, term), best_field(fields, term))
            .where(
                model.deleted_at.is_(None),
                matches_any(fields, term),
                row_score(fields, term) >= SCORE_FLOOR,
            )
            .order_by(
                row_score(fields, term).desc(),
                model.updated_at.desc(),
                model.id.desc(),
            )
            .limit(limit)
        )

    def _group(
        self,
        entity: SearchEntity,
        model: type,
        fields: Sequence[ScoredField],
        term: str,
        limit: int,
        label: object,
        subtitle: object,
    ) -> SearchGroup:
        rows = self.session.execute(self._scored(model, fields, term, limit)).all()
        totale, is_minimum = self._count(model, fields, term)
        hits = [
            SearchHit(
                entity=entity,
                id=row[0].id,
                etichetta=label(row[0]),  # type: ignore[operator]
                sottotitolo=subtitle(row[0]),  # type: ignore[operator]
                punteggio=row[1],
                campo=row[2],
            )
            for row in rows
        ]
        return SearchGroup(
            entity=entity, hits=hits, totale=totale, totale_e_un_minimo=is_minimum
        )

    # -- one branch per entity -------------------------------------------------

    def customers(self, term: str, limit: int) -> SearchGroup:
        return self._group(
            "customer", Customer, CUSTOMER_FIELDS, term, limit,
            label=lambda row: row.ragione_sociale,
            subtitle=lambda row: row.partita_iva,
        )

    def people(self, term: str, limit: int) -> SearchGroup:
        # `cognome` is nullable, so the label is joined from the parts that exist rather
        # than formatted with a placeholder: "Ludovica" and not "Ludovica None".
        return self._group(
            "person", Person, PERSON_FIELDS, term, limit,
            label=lambda row: " ".join(p for p in (row.nome, row.cognome) if p),
            subtitle=lambda row: row.email,
        )

    def deals(self, term: str, limit: int) -> SearchGroup:
        group = self._group(
            "deal", Deal, DEAL_FIELDS, term, limit,
            label=lambda row: row.nome,
            subtitle=lambda row: None,
        )
        return SearchGroup(
            entity=group.entity,
            hits=self._with_customer_names(group.hits),
            totale=group.totale,
            totale_e_un_minimo=group.totale_e_un_minimo,
        )

    def _with_customer_names(self, hits: list[SearchHit]) -> list[SearchHit]:
        """One extra lookup, after the limit, for at most `limit` rows.

        Resolving the customer name inside the scored query would mean a join evaluated
        over every trigram match rather than over the five rows that survive. A `COUNT`
        may cross a join and a `SUM` may not (spec §3); this is neither — it is a label
        lookup, and it is placed after `LIMIT` so its cost is bounded by the page.
        """
        if not hits:
            return hits
        deal_ids = [hit.id for hit in hits]
        pairs = self.session.execute(
            select(Deal.id, Customer.ragione_sociale)
            .join(Customer, Customer.id == Deal.customer_id)
            .where(Deal.id.in_(deal_ids))
        ).all()
        names: dict[UUID, str] = {row[0]: row[1] for row in pairs}
        return [hit.model_copy(update={"sottotitolo": names.get(hit.id)}) for hit in hits]

    def documents(self, term: str, limit: int) -> SearchGroup:
        return self._group(
            "document", Document, DOCUMENT_FIELDS, term, limit,
            label=lambda row: row.titolo,
            subtitle=lambda row: row.tipo,
        )
```

- [ ] **Step 4: Write the service**

```python
# packages/core/src/pigrocrm/core/search/service.py
"""The one public entry point of the global search.

It is a fan-out and nothing else: term normalisation, four repository calls, and a fixed
group order. There is deliberately no cross-entity ranking — the palette shows five per
class with each class's own count (§8.5), so a global order across classes would be a
figure nobody looks at, computed on every keystroke.

**No authorisation check.** Not an omission: search reads the same rows the four list
endpoints already return to every role, slice 4 §11 gives every read to every role, and
spec §13 states that this slice adds no role and no authorisation rule. Adding a check
here would put a security rule on a read-only surface, which is the place nobody looks for
one. `actor` is still taken, because every service method in this project takes it and a
signature that differs invites a call site that forgets it.

**No transaction.** Four `SELECT`s with no isolation requirement between them: a search is
not a reconciliation, and a hit that vanishes between the palette and the click lands on a
404 the palette already handles. The dashboards are the surface that needs one instant
(§7.1); this one does not, and pretending otherwise would put `REPEATABLE READ` on the
hottest read path in the product for no property gained.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.search.repository import SearchRepository
from pigrocrm.core.search.schemas import SearchQuery, SearchResults


class SearchService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = SearchRepository(session)

    def search_everything(self, query: SearchQuery, actor: Actor) -> SearchResults:
        """Every group is present even when empty.

        A missing group and an empty group render identically in a palette, so the client
        would have to guess which it was — and the whole point of §8.6 is that the client
        never guesses what it is looking at.

        The group order is fixed, not sorted by count: a palette whose sections move
        between keystrokes cannot be used with the keyboard, which is the only way a
        palette is used.
        """
        # `strip()` and nothing else. No lowercasing here: the scoring expression
        # lowercases on both sides where it needs to, and `similarity()` normalises
        # internally, so a second normalisation would only make the returned `termine`
        # differ from what the user typed.
        term = query.termine.strip()
        limit = query.limite
        return SearchResults(
            termine=term,
            gruppi=[
                self.repo.customers(term, limit),
                self.repo.people(term, limit),
                self.repo.deals(term, limit),
                self.repo.documents(term, limit),
            ],
        )
```

- [ ] **Step 5: Extend the package exports**

```python
# packages/core/src/pigrocrm/core/search/__init__.py -- add to the imports and __all__
from pigrocrm.core.search.service import SearchService
# ... and "SearchService" in __all__, keeping it alphabetically sorted as ruff requires.
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_search_service.py -v`
Expected: PASS, fourteen tests.

- [ ] **Step 7: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/search/ packages/core/tests/test_search_service.py
git commit -m "feat(search): SearchService over four entities, with floor and real counts"
```

---
### Task A9: Criterion 3 — the search does not degenerate into a table scan

**Files:**
- Create: `packages/core/tests/test_search_plan.py`

**Interfaces:**
- Consumes: `INFLATED`, `build_corpus` (Task A1); `CUSTOMER_FIELDS`, `PERSON_FIELDS`, `DEAL_FIELDS`, `DOCUMENT_FIELDS`, `SearchRepository` (Task A8); `matches_any`, `row_score`, `SCORE_FLOOR` (Task A7); the `db_engine` fixture.
- Produces: nothing importable. The deliverable is the executable criterion, plus the marker `@pytest.mark.slow`, registered in `pyproject.toml` under `[tool.pytest.ini_options].markers`.

**Why it needs its own committed corpus and its own session.** 50 000 rows per table have to be `ANALYZE`d for the planner to have statistics, and `ANALYZE` cannot run inside the savepoint the `db_session` fixture holds open. This test builds the inflated corpus once per session in its own transaction, commits, analyses, and deletes it in a `finally`.

**Why `deals` is exempt from the plan assertion, restated where the code is.** Spec §7.3 says it and the reason must travel with the test or someone adds `deals` for symmetry and gets a red test with no defect: at the reference scale two thousand deals sit in a handful of pages and a sequential scan *is* the cheapest plan. At the inflated scale `deals` has 50 000 rows like the rest, so the assertion **is** made here — the exemption in §7.3 is about the *dashboard* queries on the reference corpus, not about this one. That distinction is written into the test's docstring.

- [ ] **Step 1: Register the marker**

```toml
# pyproject.toml -- add to [tool.pytest.ini_options]
markers = [
  "slow: builds the 50 000-row inflated corpus; minutes, not seconds",
]
```

Nothing skips on this marker by default. It exists so a developer can say `-m "not slow"` while iterating, and so CI's own `uv run pytest -q` still runs it — a plan assertion that CI skips is a plan assertion that does not exist.

- [ ] **Step 2: Write the failing test**

```python
# packages/core/tests/test_search_plan.py
"""**Criterion 3.** The search uses its indexes, measured on the plan and not on the clock.

A good time on a fast machine hides a sequential scan; a plan assertion does not. And a
plan assertion on a small table is meaningless — Postgres picks a sequential scan on a
table of a few pages because it *is* the cheapest plan — so this is the one test that pays
for the inflated corpus: every searched table at 50 000 rows.

Note the difference from spec §7.3, which forbids asserting on the plan for `deals`. That
exemption is about the *dashboard* queries on the *reference* corpus, where `deals` holds
two thousand rows. Here `deals` holds fifty thousand like every other table, so the
assertion is made. Keeping the two straight is why this paragraph exists.

The last test is the one that makes the rest mean anything: it drops an index and asserts
that the plan assertion **fails**. A plan assertion that passes without the index is not
measuring the index.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import session_factory
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.people.models import Person
from pigrocrm.core.search.repository import (
    CUSTOMER_FIELDS,
    DEAL_FIELDS,
    DOCUMENT_FIELDS,
    PERSON_FIELDS,
    SearchRepository,
)
from pigrocrm.core.search.scoring import SCORE_FLOOR, matches_any, row_score

from .corpus import INFLATED, build_corpus

pytestmark = pytest.mark.slow

# Spec §16: "per un termine di 3 caratteri e per uno di 12". Three characters is the
# shortest a trigram index can serve; twelve is a realistic full name or fiscal code.
_TERM_SHORT = "ing"
_TERM_LONG = "Ingegneria S"
# Spec §7.3 and §16: 300 ms for the endpoint. The bare query gets a third of that budget,
# leaving room for serialisation and the four-way fan-out.
_QUERY_BUDGET_MS = 100

_BRANCHES = (
    ("customers", Customer, CUSTOMER_FIELDS),
    ("people", Person, PERSON_FIELDS),
    ("deals", Deal, DEAL_FIELDS),
    ("documents", Document, DOCUMENT_FIELDS),
)


@pytest.fixture(scope="module")
def inflated(db_engine: Engine) -> Iterator[Engine]:
    """50 000 rows per searched table, committed and analysed, removed afterwards.

    Module-scoped: building it four times would quadruple the cost of the one test that
    needs it. `ANALYZE` is mandatory, not hygiene — without statistics the planner has no
    basis to prefer an index and this whole file measures the wrong thing.
    """
    factory = session_factory(db_engine)
    with factory() as session:
        build_corpus(session, INFLATED)
        session.commit()
    with db_engine.begin() as connection:
        for table in ("customers", "people", "deals", "documents"):
            connection.execute(text(f"ANALYZE {table}"))
    try:
        yield db_engine
    finally:
        with factory() as session:
            # Children first: `people.customer_id` and `deals.customer_id` reference
            # `customers`, and `documents` references both.
            session.execute(delete(Document))
            session.execute(delete(Deal))
            session.execute(delete(Person))
            session.execute(delete(Customer))
            session.commit()


def _plan(session: Session, model: type, fields: tuple[object, ...], term: str) -> str:
    stmt = (
        select(model.id)
        .where(
            model.deleted_at.is_(None),
            matches_any(fields, term),  # type: ignore[arg-type]
            row_score(fields, term) >= SCORE_FLOOR,  # type: ignore[arg-type]
        )
        .limit(5)
    )
    compiled = stmt.compile(
        session.get_bind(), compile_kwargs={"literal_binds": True}
    )
    rows = session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled}")).all()
    return "\n".join(str(row[0]) for row in rows)


@pytest.mark.parametrize("term", [_TERM_SHORT, _TERM_LONG])
@pytest.mark.parametrize("name,model,fields", _BRANCHES, ids=[b[0] for b in _BRANCHES])
def test_every_branch_uses_a_bitmap_index_scan_and_never_a_seq_scan(
    inflated: Engine, name: str, model: type, fields: tuple[object, ...], term: str
) -> None:
    with session_factory(inflated)() as session:
        plan = _plan(session, model, fields, term)

    assert "Bitmap Index Scan" in plan, (
        f"{name} for term {term!r} did not use a bitmap index scan:\n{plan}"
    )
    assert f"Seq Scan on {name}" not in plan, (
        f"{name} for term {term!r} fell back to a sequential scan:\n{plan}"
    )
    assert "_trgm" in plan, (
        f"{name} for term {term!r} used an index, but not a trigram one:\n{plan}"
    )


@pytest.mark.parametrize("term", [_TERM_SHORT, _TERM_LONG])
def test_the_whole_fan_out_stays_inside_its_budget(inflated: Engine, term: str) -> None:
    """Latency as well as plan. The plan assertion catches the regression that matters;
    the clock catches the one where every branch uses its index and there are simply too
    many of them."""
    with session_factory(inflated)() as session:
        repo = SearchRepository(session)
        # One warm run first: the first statement of a session pays for plan caching and
        # connection warm-up, which is not what is being measured.
        for method in (repo.customers, repo.people, repo.deals, repo.documents):
            method(term, 5)

        started = time.perf_counter()
        for method in (repo.customers, repo.people, repo.deals, repo.documents):
            method(term, 5)
        elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 300, f"the four branches took {elapsed_ms:.0f} ms for {term!r}"


def test_the_bounded_count_does_not_read_the_whole_match_set(inflated: Engine) -> None:
    """The `LIMIT 201` inside the count subquery is what keeps a term matching 40 000 rows
    as cheap as one matching 40. Without it the count is a full scan of the match set on
    every keystroke."""
    with session_factory(inflated)() as session:
        plan = session.execute(
            text(
                "EXPLAIN (ANALYZE) SELECT count(*) FROM ("
                "  SELECT 1 FROM customers WHERE deleted_at IS NULL "
                r"    AND ragione_sociale ILIKE '%ing%' ESCAPE '\' LIMIT 201"
                ") s"
            )
        ).all()
    rendered = "\n".join(str(row[0]) for row in plan)
    assert "Limit" in rendered, rendered
    # `rows=201` on the Limit node: the scan stopped, it did not merely cap the output.
    assert "rows=201" in rendered, rendered


def test_the_assertion_fails_without_the_index(inflated: Engine) -> None:
    """The test that makes this file worth having.

    A plan assertion that also passes with the index dropped is not measuring the index.
    The index is dropped, the assertion is re-run and required to fail, and the index is
    rebuilt in a `finally` so a failure here cannot leave the database degraded for the
    rest of the session.
    """
    with session_factory(inflated)() as session:
        session.execute(text("DROP INDEX ix_customers_ragione_sociale_trgm"))
        session.commit()
        try:
            plan = _plan(session, Customer, CUSTOMER_FIELDS, _TERM_SHORT)
            assert "Seq Scan on customers" in plan, (
                "with the trigram index dropped, the query still avoided a sequential "
                f"scan -- so the earlier assertions are not measuring that index:\n{plan}"
            )
        finally:
            session.rollback()
            session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_customers_ragione_sociale_trgm "
                    "ON customers USING gin (ragione_sociale gin_trgm_ops) "
                    "WHERE deleted_at IS NULL"
                )
            )
            session.commit()
            session.execute(text("ANALYZE customers"))
            session.commit()
```

- [ ] **Step 3: Run it and watch the right things fail**

Run: `uv run pytest packages/core/tests/test_search_plan.py -v`

Expected on a tree where Tasks A2, A7 and A8 are done: PASS. Run it once **before** merging A2's indexes (or with them temporarily dropped) to see it fail — the failure message names the branch and prints the plan, which is what makes it useful when it fires for real.

If a branch reports `Bitmap Index Scan` on the wrong index — for example `ix_customers_partita_iva` rather than `ix_customers_partita_iva_trgm` — the `_trgm` assertion catches it. That is a genuine finding, not a test bug: a B-tree index cannot serve `ILIKE '%x%'`, so the planner choosing one means the predicate is not the one intended.

- [ ] **Step 4: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: green. This file adds minutes to the suite; that is the price of the only assertion in the project that can tell a fast machine from a correct index.

- [ ] **Step 5: Commit**

```bash
git add packages/core/tests/test_search_plan.py pyproject.toml
git commit -m "test(search): criterion 3, EXPLAIN on 50k rows plus the index-removal check"
```

---

### Task A10: Criterion 4 — the order is total and the response is byte-identical

**Files:**
- Create: `packages/core/tests/test_search_determinism.py`

**Interfaces:**
- Consumes: `SearchService`, `SearchQuery` (Tasks A7, A8); `build_corpus`, `REFERENCE`, `KNOWN_PARTITA_IVA`, `KNOWN_RAGIONE_SOCIALE` (Task A1).
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_search_determinism.py
"""**Criterion 4.** The same database and the same term produce a byte-identical response
on twenty runs.

The third sort key (`id DESC`) exists for this and only this: `punteggio DESC,
updated_at DESC` is not a total order — two rows created in the same statement share
`updated_at` to the microsecond often enough that it happens on the first corpus you try —
and without a total order Postgres is free to return the same set in a different sequence
each time. A palette whose rows reorder between identical keystrokes cannot be driven with
the arrow keys, which is the only way a palette is driven.

`model_dump_json()` and not `model_dump()`: the comparison has to be on bytes, because
that is what the client receives. A `Decimal` and a `float` that compare equal in Python
serialise differently.
"""

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.search.schemas import SearchQuery
from pigrocrm.core.search.service import SearchService

from .corpus import KNOWN_PARTITA_IVA, KNOWN_RAGIONE_SOCIALE, REFERENCE, build_corpus

READONLY = Actor(id=uuid7(), type="user", role="readonly")
_RUNS = 20


def test_twenty_runs_produce_one_byte_identical_response(db_session: Session) -> None:
    build_corpus(db_session, REFERENCE)
    service = SearchService(db_session)

    renderings = {
        service.search_everything(
            SearchQuery(termine="Ingegneria", limite=5), READONLY
        ).model_dump_json()
        for _ in range(_RUNS)
    }
    assert len(renderings) == 1, (
        f"{len(renderings)} distinct responses across {_RUNS} runs -- the order is not "
        "total. Check that every branch orders by punteggio DESC, updated_at DESC, "
        "id DESC."
    )


def test_the_property_holds_for_a_term_with_many_ties(db_session: Session) -> None:
    """The adversarial version. Two hundred rows with the *same* name, inserted in one
    statement so they share `updated_at`: score and second key are both ties, and only
    `id DESC` can break them."""
    from pigrocrm.core.customers.models import Customer

    db_session.execute(
        Customer.__table__.insert(),
        [
            {"id": uuid7(), "ragione_sociale": "Identica Srl", "nazione": "IT",
             "custom_fields": {}}
            for _ in range(200)
        ],
    )
    db_session.flush()
    service = SearchService(db_session)

    renderings = {
        service.search_everything(
            SearchQuery(termine="Identica", limite=5), READONLY
        ).model_dump_json()
        for _ in range(_RUNS)
    }
    assert len(renderings) == 1, (
        "identical rows returned in a different order across runs: the third sort key is "
        "missing or is not on a unique column"
    )


def test_an_exact_vat_number_puts_that_customer_first(db_session: Session) -> None:
    """§16 criterion 4's first named expectation."""
    build_corpus(db_session, REFERENCE)
    results = SearchService(db_session).search_everything(
        SearchQuery(termine=KNOWN_PARTITA_IVA), READONLY
    )
    customer_group = next(g for g in results.gruppi if g.entity == "customer")
    assert customer_group.hits[0].etichetta == KNOWN_RAGIONE_SOCIALE


def test_a_prefix_outranks_a_mid_word_match(db_session: Session) -> None:
    """§16 criterion 4's second named expectation, at the service level rather than the
    expression level (Task A7 covers the expression)."""
    from pigrocrm.core.customers.models import Customer

    db_session.add(Customer(ragione_sociale="Vulcano Impianti Srl", nazione="IT",
                            custom_fields={}))
    db_session.add(Customer(ragione_sociale="Grande Vulcanologia Spa", nazione="IT",
                            custom_fields={}))
    db_session.flush()

    results = SearchService(db_session).search_everything(
        SearchQuery(termine="Vulcan", limite=5), READONLY
    )
    labels = [hit.etichetta for hit in
              next(g for g in results.gruppi if g.entity == "customer").hits]
    assert labels.index("Vulcano Impianti Srl") < labels.index("Grande Vulcanologia Spa")


def test_the_group_order_is_fixed_and_not_by_count(db_session: Session) -> None:
    """A palette whose sections move between keystrokes cannot be used with the
    keyboard."""
    build_corpus(db_session, REFERENCE)
    results = SearchService(db_session).search_everything(
        SearchQuery(termine="Ingegneria"), READONLY
    )
    assert [g.entity for g in results.gruppi] == ["customer", "person", "deal", "document"]
```

- [ ] **Step 2: Run it and watch it fail on purpose first**

Temporarily delete the `model.id.desc()` clause from `SearchRepository._scored`.

Run: `uv run pytest packages/core/tests/test_search_determinism.py -v`
Expected: `test_the_property_holds_for_a_term_with_many_ties` FAILS with "identical rows returned in a different order across runs". **Restore the clause.** If it passes even without the third key, the tie-generating test is not generating ties — increase the 200 rows until it does, because the criterion is unverified until it has been seen to fail.

- [ ] **Step 3: Run it green**

Run: `uv run pytest packages/core/tests/test_search_determinism.py -v`
Expected: PASS, five tests.

- [ ] **Step 4: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add packages/core/tests/test_search_determinism.py
git commit -m "test(search): criterion 4, a total order and twenty identical responses"
```

---
### Task A11: `GET /api/search`, the `search_everything` tool, and the audited surface

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/search.py`
- Modify: `apps/api/src/pigrocrm_api/main.py`
- Create: `apps/mcp/src/pigrocrm_mcp/tools/search.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`
- Modify: `packages/core/tests/test_architecture.py`
- Create: `apps/api/tests/test_search_api.py`
- Create: `apps/mcp/tests/test_mcp_search.py`

**Interfaces:**
- Consumes: `SearchService.search_everything(query: SearchQuery, actor: Actor) -> SearchResults`, `SearchQuery`, `SearchResults` (Tasks A7, A8); `ActorDep`, `SessionDep`, `PROBLEM_RESPONSES`; `McpContext`, the `_guard` decorator and `register_entity_tools`'s existing shape.
- Produces:
  - `GET /api/search?q=&limit=` → `SearchResults`. `q`, not `termine`, in the query string: the spec's §11.2 endpoint block writes `?q=&limit=`, and the schema field stays `termine`.
  - MCP tool `search_everything(termine: str, limite: int = 5) -> dict[str, Any]`.
  - In `packages/core/tests/test_architecture.py`: `MCP_EXCLUDED_SLICE6: tuple[str, ...] = ("update_automation_config",)` and `_audited_services_slice6()`, alongside — never replacing — slice 4's `MCP_EXCLUDED` and `_audited_services()`.
- Task A12 regenerates the client against this endpoint; Task B15 adds `DashboardService` and `AutomationConfigService` to `_audited_services_slice6()` and changes not one character of the list.

**The R1 gate, stated as a step and not as a hope.** Spec §11.3 says this slice depends on the one-session-per-call cure and does not work around it. That cure is a task of slice 4's plan and is **not** in `main` as of this plan's writing (`apps/mcp/src/pigrocrm_mcp/__main__.py:22-32` still builds one `Session` for the process). Step 6 below is the check. A read-only search tool on a shared session is the mildest case of the problem — but it is still the case, and registering it before the cure lands means shipping a tool whose failure mode is `Method 'rollback()' can't be called here`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_search_api.py
"""`GET /api/search`, and the three §8.6 states as far as the API can express them.

The API's job for the third state is to fail loudly with a problem document. Rendering
that as an error and not as an empty list is the frontend's job, and Task A14 asserts it.
"""

import pytest
from fastapi.testclient import TestClient


def test_a_search_returns_all_four_groups(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    client.post("/api/customers", json={"ragione_sociale": "Vulcano Impianti Srl"},
                cookies=admin_cookie)

    response = client.get("/api/search", params={"q": "Vulcano"}, cookies=admin_cookie)
    assert response.status_code == 200
    body = response.json()
    assert body["termine"] == "Vulcano"
    assert [g["entity"] for g in body["gruppi"]] == [
        "customer", "person", "deal", "document",
    ]
    customer = body["gruppi"][0]
    assert customer["totale"] == 1
    assert customer["totale_e_un_minimo"] is False
    assert customer["hits"][0]["etichetta"] == "Vulcano Impianti Srl"


def test_the_score_is_serialised_as_a_decimal_string_not_a_float(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    """A float score renders as 0.6000000238418579 and breaks criterion 4."""
    client.post("/api/customers", json={"ragione_sociale": "Vulcano Impianti Srl"},
                cookies=admin_cookie)
    response = client.get("/api/search", params={"q": "Vulcano"}, cookies=admin_cookie)
    punteggio = response.json()["gruppi"][0]["hits"][0]["punteggio"]
    assert isinstance(punteggio, str), type(punteggio)
    assert punteggio == "0.8000"


@pytest.mark.parametrize("term", ["", "a", "ab"])
def test_a_term_shorter_than_three_characters_is_a_422(
    client: TestClient, admin_cookie: dict[str, str], term: str
) -> None:
    response = client.get("/api/search", params={"q": term}, cookies=admin_cookie)
    assert response.status_code == 422


def test_a_readonly_actor_may_search(
    client: TestClient, readonly_cookie: dict[str, str]
) -> None:
    response = client.get("/api/search", params={"q": "Vulcano"},
                          cookies=readonly_cookie)
    assert response.status_code == 200


def test_an_unauthenticated_request_is_a_401(client: TestClient) -> None:
    assert client.get("/api/search", params={"q": "Vulcano"}).status_code == 401


def test_the_limit_is_bounded(client: TestClient, admin_cookie: dict[str, str]) -> None:
    assert client.get("/api/search", params={"q": "abc", "limit": 0},
                      cookies=admin_cookie).status_code == 422
    assert client.get("/api/search", params={"q": "abc", "limit": 500},
                      cookies=admin_cookie).status_code == 422


def test_the_endpoint_appears_in_the_openapi_document(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/search" in schema["paths"]
```

```python
# apps/mcp/tests/test_mcp_search.py
"""The MCP half. Same service, same figures, one call.

Spec §11.1 lists `search_everything` on both surfaces. The reason it is a tool rather than
four is the same reason it is one service method: an agent that had to call four searches
and merge them would be doing in a transcript what the service already does in one query.
"""

from typing import Any


async def test_search_everything_is_registered(mcp_server: Any) -> None:
    tools = {tool.name for tool in await mcp_server.list_tools()}
    assert "search_everything" in tools


async def test_search_everything_returns_the_four_groups(
    mcp_server: Any, seeded_customer: Any
) -> None:
    result = await mcp_server.call_tool(
        "search_everything", {"termine": seeded_customer.ragione_sociale[:6]}
    )
    payload = result.structured_content
    assert [g["entity"] for g in payload["gruppi"]] == [
        "customer", "person", "deal", "document",
    ]
    assert payload["gruppi"][0]["hits"][0]["id"] == str(seeded_customer.id)


async def test_a_two_character_term_is_a_domain_error_not_a_scan(mcp_server: Any) -> None:
    """`_guard` converts the pydantic failure into a message the agent can act on,
    instead of the SDK rejecting it with one we did not write."""
    result = await mcp_server.call_tool("search_everything", {"termine": "ab"})
    assert result.is_error
    assert "3" in str(result.content)
```

Follow whatever fixture names `apps/mcp/tests/conftest.py` already provides for `mcp_server` and a seeded customer; if the seeded-customer fixture does not exist, add it next to the existing ones rather than inventing a second conftest.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest apps/api/tests/test_search_api.py apps/mcp/tests/test_mcp_search.py -v`
Expected: every API test FAILS with `404`, and every MCP test FAILS on the missing tool name.

- [ ] **Step 3: Write the router**

```python
# apps/api/src/pigrocrm_api/routers/search.py
"""One endpoint. The palette calls it on every keystroke above three characters, so it is
the hottest read path in the product.

No transaction wrapper and no isolation level: see `SearchService`'s own docstring for
why. The dashboards are the surface that needs one instant (spec §7.1); a search does not,
and putting `REPEATABLE READ` here would pay for a property nothing reads.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from pigrocrm.core.search.schemas import (
    MAX_TERM_LENGTH,
    MIN_TERM_LENGTH,
    PER_CLASS_LIMIT,
    SearchQuery,
    SearchResults,
)
from pigrocrm.core.search.service import SearchService
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/search", tags=["search"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=SearchResults)
def search(
    session: SessionDep,
    actor: ActorDep,
    # `q` in the query string, `termine` in the schema: spec §11.2 fixes the parameter
    # name and §8 fixes the field name, and they differ. The bounds are repeated here as
    # well as on SearchQuery so FastAPI answers a two-character term with a 422 before the
    # service is constructed -- the palette does not send one, but an agent might.
    q: Annotated[SafeStr, Query(min_length=MIN_TERM_LENGTH, max_length=MAX_TERM_LENGTH)],
    limit: Annotated[int, Query(ge=1, le=20)] = PER_CLASS_LIMIT,
) -> SearchResults:
    return SearchService(session).search_everything(
        SearchQuery(termine=q, limite=limit), actor
    )
```

```python
# apps/api/src/pigrocrm_api/main.py -- two edits.
# 1. add `search` to the router import line
from pigrocrm_api.routers import (
    auth, customers, deals, documents, emitter, fields, people, pipeline, schema,
    search, templates, tokens, users,
)
# 2. add it to the registration tuple
    for module in (
        auth, customers, people, deals, fields, pipeline,
        users, tokens, schema, documents, templates, emitter, search,
    ):
        app.include_router(module.router)
```

- [ ] **Step 4: Write the MCP tool**

```python
# apps/mcp/src/pigrocrm_mcp/tools/search.py
"""The thin half. Everything that matters happened in `SearchService`.

Shaped exactly like `tools/customers.py`: resolve the service on the context's session,
call it, `model_dump(mode="json")`. `mode="json"` and not the default is what turns the
`Decimal` score into a string rather than into something the JSON encoder refuses.
"""

from typing import Any

from pigrocrm.core.search.schemas import SearchQuery
from pigrocrm.core.search.service import SearchService

from pigrocrm_mcp.context import McpContext


def search_everything(context: McpContext, query: SearchQuery) -> dict[str, Any]:
    return (
        SearchService(context.session)
        .search_everything(query, context.actor)
        .model_dump(mode="json")
    )
```

```python
# apps/mcp/src/pigrocrm_mcp/tools/__init__.py
# Add to the imports:
#   from pigrocrm.core.search.schemas import PER_CLASS_LIMIT, SearchQuery
#   from pigrocrm_mcp.tools import search as search_tools
# and register the tool inside register_entity_tools, next to the four entity searches:

    @mcp.tool()
    @guard
    def search_everything(termine: str, limite: int = PER_CLASS_LIMIT) -> dict[str, Any]:
        """Cerca in tutto il CRM -- clienti, persone, deal e documenti -- con una sola
        chiamata: ragione sociale, P.IVA, codice fiscale, email, nome e cognome, nome del
        deal, titolo del documento. Accetta anche un frammento in mezzo a una parola (per
        esempio "34567" trova la P.IVA 01234567890). Servono almeno 3 caratteri.
        Restituisce fino a `limite` risultati per classe di entita' piu' il conteggio
        reale di quella classe: se `totale_e_un_minimo` e' true il conteggio e' un minimo
        e i risultati completi stanno sull'elenco della singola entita'.
        """
        return search_tools.search_everything(
            context, SearchQuery(termine=termine, limite=limite)
        )
```

`termine` is `str` at the tool boundary with no `Annotated` bound, following the file's documented "runtime-permissive, schema-only-strict" convention: the length check happens inside `SearchQuery`, inside `_guard`, so a short term produces a domain error the agent can read rather than an SDK rejection whose wording is not ours.

- [ ] **Step 5: Grow the architecture test**

```python
# packages/core/tests/test_architecture.py -- append. Slice 4's MCP_EXCLUDED and
# _audited_services() are NOT touched: spec §11.1 requires that list to still be exactly
# its ten names, and a single shared list would make the two specs contradict each other.
"""Slice 6's MCP ban, made mechanical.

Spec §11.1: for every public method of `DashboardService`, `SearchService` and
`AutomationConfigService` either an MCP tool calls it, or it appears in a declared
exclusion list -- and for these three services the list must be **exactly**
`update_automation_config`. Adding a tool for it breaks the build; removing it from the
list without adding a tool breaks it too.

Two of the three services do not exist until sub-plan 6B. The list is asserted as a
constant regardless -- it is the *declaration* the spec fixes -- while the coverage half
inspects only the classes actually importable, exactly as slice 4's clause does for
`AnalyticsService`.
"""

MCP_EXCLUDED_SLICE6: tuple[str, ...] = ("update_automation_config",)


def _audited_services_slice6() -> list[type]:
    found: list[type] = []
    for module_path, class_name in (
        ("pigrocrm.core.search.service", "SearchService"),
        ("pigrocrm.core.dashboard.service", "DashboardService"),
        ("pigrocrm.core.automations.config_service", "AutomationConfigService"),
    ):
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            continue
        found.append(getattr(module, class_name))
    return found


def test_the_slice6_exclusion_list_is_exactly_one_name() -> None:
    assert MCP_EXCLUDED_SLICE6 == ("update_automation_config",)


def test_no_mcp_tool_reaches_update_automation_config() -> None:
    """Matched on the call site, not on the tool's own name: a tool called `tidy_settings`
    that happened to call `.update_automation_config(` is exactly how this ban would
    otherwise be lost. The ban is imposed by not registering a tool rather than by an
    authorisation check, because residuo R10 leaves a PAT inheriting its owner's full role
    -- an admin token would pass any check we wrote."""
    source = _tool_source()
    offenders = [name for name in MCP_EXCLUDED_SLICE6 if f".{name}(" in source]
    assert not offenders, f"these methods must not be reachable from any MCP tool: {offenders}"


def test_every_other_public_method_of_a_slice6_service_has_a_tool() -> None:
    source = _tool_source()
    audited = _audited_services_slice6()
    assert audited, "expected at least SearchService to be importable"
    missing: list[str] = []
    for cls in audited:
        for name in sorted(_public_methods(cls)):
            if name in MCP_EXCLUDED_SLICE6:
                continue
            if f".{name}(" not in source:
                missing.append(f"{cls.__name__}.{name}")
    assert not missing, (
        "every public method of an audited slice-6 service must either be reachable from "
        f"an MCP tool or be the one declared exclusion: {missing}"
    )


def test_the_slice4_exclusion_list_is_still_exactly_its_ten_names() -> None:
    """Spec §6.3 and §11.1: `unbilled_backlog` is a new public method on
    `AnalyticsService` and it has a tool (`get_unbilled_backlog`), so slice 4's list does
    not grow. Asserted here so that adding the method without the tool fails as a
    violation of slice 4's contract, named as such."""
    assert len(MCP_EXCLUDED) == 10
    assert "unbilled_backlog" not in MCP_EXCLUDED
```

`importlib`, `inspect`, `_tool_source`, `_public_methods` and `MCP_EXCLUDED` come from slice 4's clause in the same file. **If slice 4 is not merged**, that clause does not exist yet: in that case this task adds the four helpers (`importlib`/`inspect` imports, `MCP_TOOLS_DIR`, `_tool_source`, `_public_methods`) with the bodies slice 4's plan gives verbatim, omits `test_the_slice4_exclusion_list_is_still_exactly_its_ten_names`, and Task 4A-13 then finds them present and adds only `MCP_EXCLUDED` and its own three tests. Neither ordering duplicates a helper.

- [ ] **Step 6: The R1 gate**

Run: `grep -n "session_provider\|lambda: session\|contextvars" apps/mcp/src/pigrocrm_mcp/__main__.py apps/mcp/src/pigrocrm_mcp/server.py`

- If the output shows a **per-call** session (a `contextvars`-scoped provider, one session per tool invocation), proceed to Step 7 with both halves.
- If it still shows `lambda: session` over a single process-lifetime `Session`, **do not register the MCP tool.** Comment out the `@mcp.tool()` registration block added in Step 4, leaving `tools/search.py` in place, and add this comment above it:

```python
    # NOT REGISTERED until residuo R1 is cured. `apps/mcp/src/pigrocrm_mcp/__main__.py`
    # still shares one SQLAlchemy Session across the whole process, and the slice-1A
    # measurement of that arrangement was 10 concurrent operations, 0 successes, 0 rows.
    # Spec §11.3: this slice depends on the cure and does not work around it. A search
    # tool on a shared session is the mildest case of the problem and still the problem.
    # Uncomment together with the first task of sub-plan 6C, which carries the same gate.
```

Then skip `apps/mcp/tests/test_mcp_search.py` at module level with `pytestmark = pytest.mark.skip(reason="blocked on residuo R1; see tools/__init__.py")`, and record the decision in this task's commit message. The API half ships either way.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `uv run pytest apps/api/tests/test_search_api.py apps/mcp/tests/test_mcp_search.py packages/core/tests/test_architecture.py -v`
Expected: PASS (with the MCP file skipped if Step 6 said so).

- [ ] **Step 8: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/pigrocrm_api/routers/search.py \
        apps/api/src/pigrocrm_api/main.py \
        apps/mcp/src/pigrocrm_mcp/tools/search.py \
        apps/mcp/src/pigrocrm_mcp/tools/__init__.py \
        packages/core/tests/test_architecture.py \
        apps/api/tests/test_search_api.py \
        apps/mcp/tests/test_mcp_search.py
git commit -m "feat(api): GET /api/search and the search_everything tool"
```

---
### Task A12: The `AppShell` header slice 1 promised and never shipped

**Files:**
- Create: `apps/web/src/components/AppHeader.tsx`
- Create: `apps/web/src/components/AppHeader.test.tsx`
- Modify: `apps/web/src/components/AppShell.tsx`
- Modify: `apps/web/src/components/AppShell.test.tsx`
- Modify: `apps/web/src/lib/query.ts`
- Modify: `apps/web/src/lib/api-types.ts` (regenerated, never hand-edited)

**Interfaces:**
- Consumes: `GET /api/search` (Task A11) only for the type regeneration; nothing at runtime yet — the field is a button until Task A13 mounts the palette.
- Produces:
  - `apps/web/src/components/AppHeader.tsx`: `export function AppHeader({ onOpenSearch }: { onOpenSearch: () => void })`, and `export function breadcrumbFor(pathname: string): string[]` — exported for its own test.
  - `apps/web/src/lib/query.ts`: `queryKeys.search(term: string)` returning `['search', term] as const`.
- Task A13 supplies the real `onOpenSearch` and the `Cmd/Ctrl+K` listener.

**This is half of a residuo, not a flourish.** The slice-1A residui document's final, unnumbered entry: "La spec dello slice 1 (§10.1) promette «header con breadcrumb e ricerca». `AppShell.tsx` non ha alcun header." The global search has nowhere to live until it does, which is why the header is built here and not in slice 1's own follow-up.

- [ ] **Step 1: Write the failing test**

```tsx
// apps/web/src/components/AppHeader.test.tsx
/**
 * The header slice 1 §10.1 promised. Three regions: breadcrumb, search, actions.
 *
 * `breadcrumbFor` is a pure function and is tested as one, because the alternative is
 * asserting on rendered crumbs through a router mock and then not being able to tell a
 * routing failure from a labelling one.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppHeader, breadcrumbFor } from './AppHeader'

describe('breadcrumbFor', () => {
  it('labels the dashboard root', () => {
    expect(breadcrumbFor('/app')).toEqual(['Dashboard'])
    expect(breadcrumbFor('/app/')).toEqual(['Dashboard'])
  })

  it('labels a known section', () => {
    expect(breadcrumbFor('/app/clienti')).toEqual(['Clienti'])
    expect(breadcrumbFor('/app/impostazioni/campi')).toEqual(['Impostazioni', 'Campi'])
  })

  it('renders a detail route without leaking the id into the crumb', () => {
    expect(breadcrumbFor('/app/clienti/0192f3b2-8c1a-7c3d-9f4e-1a2b3c4d5e6f')).toEqual([
      'Clienti',
      'Dettaglio',
    ])
  })

  it('falls back to a capitalised segment for an unmapped path', () => {
    expect(breadcrumbFor('/app/qualcosa')).toEqual(['Qualcosa'])
  })
})

describe('AppHeader', () => {
  it('shows a search control with the keyboard shortcut visible', () => {
    render(<AppHeader onOpenSearch={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: /cerca/i })
    expect(trigger).toBeInTheDocument()
    // Spec §13: "campo di ricerca al centro con la scorciatoia visibile". Visible, not
    // discoverable by trying it.
    expect(trigger).toHaveTextContent(/K/)
  })

  it('calls onOpenSearch when the control is activated', async () => {
    const onOpenSearch = vi.fn()
    render(<AppHeader onOpenSearch={onOpenSearch} />)
    await userEvent.click(screen.getByRole('button', { name: /cerca/i }))
    expect(onOpenSearch).toHaveBeenCalledTimes(1)
  })

  it('is a landmark so a screen reader can skip to it', () => {
    render(<AppHeader onOpenSearch={vi.fn()} />)
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && pnpm exec vitest run src/components/AppHeader.test.tsx`
Expected: `Failed to resolve import "./AppHeader"`.

- [ ] **Step 3: Write the header**

```tsx
// apps/web/src/components/AppHeader.tsx
import { useRouterState } from '@tanstack/react-router'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * The top bar slice 1 §10.1 promised and `AppShell` never had. Three regions:
 * breadcrumb on the left, the search control in the middle, actions on the right.
 *
 * The actions region is deliberately empty today. It exists as a slot because the
 * alternative is a two-region header that has to be restructured the first time anything
 * needs to sit there, and because the sidebar already owns the account menu.
 */

const SEGMENT_LABELS: Record<string, string> = {
  app: 'Dashboard',
  clienti: 'Clienti',
  persone: 'Persone',
  deal: 'Deal',
  documenti: 'Documenti',
  impostazioni: 'Impostazioni',
  campi: 'Campi',
  emittente: 'Emittente',
  pipeline: 'Pipeline',
  template: 'Template',
  utenti: 'Utenti',
  automazioni: 'Automazioni',
  token: 'Token',
  lista: 'Lista',
}

// A UUID segment is an id, not a name. Rendering it would put a 36-character opaque
// string in the breadcrumb, and resolving it to the record's title would mean a second
// request from a component whose job is navigation.
const UUID_SEGMENT =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

export function breadcrumbFor(pathname: string): string[] {
  const segments = pathname.split('/').filter((segment) => segment.length > 0)
  if (segments.length === 0) return ['Dashboard']
  // Drop the leading "app": every authenticated route carries it and repeating it in
  // every breadcrumb is noise.
  const rest = segments[0] === 'app' ? segments.slice(1) : segments
  if (rest.length === 0) return ['Dashboard']
  return rest.map((segment) =>
    UUID_SEGMENT.test(segment)
      ? 'Dettaglio'
      : (SEGMENT_LABELS[segment] ?? segment.charAt(0).toUpperCase() + segment.slice(1)),
  )
}

// `metaKey` on Apple platforms, `ctrlKey` elsewhere. Read once at module scope from the
// platform hint rather than sniffing the user agent string: this only decides which glyph
// is drawn, and Task A13's listener accepts either modifier regardless.
const IS_APPLE =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')

export function AppHeader({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { location } = useRouterState()
  const crumbs = breadcrumbFor(location.pathname)

  return (
    <header
      role="banner"
      className="flex h-14 shrink-0 items-center gap-4 border-b bg-card px-6"
    >
      <nav aria-label="Percorso" className="min-w-0 flex-1">
        <ol className="flex items-center gap-2 text-sm text-muted-foreground">
          {crumbs.map((crumb, index) => (
            <li key={`${crumb}-${index}`} className="flex items-center gap-2">
              {index > 0 && <span aria-hidden="true">/</span>}
              <span
                className={index === crumbs.length - 1 ? 'truncate text-foreground' : 'truncate'}
                aria-current={index === crumbs.length - 1 ? 'page' : undefined}
              >
                {crumb}
              </span>
            </li>
          ))}
        </ol>
      </nav>

      <Button
        variant="outline"
        onClick={onOpenSearch}
        // A button and not an <input>: the palette is a dialog, so a real text field here
        // would take focus, accept typing, and then hand it over -- two places to type the
        // same query. One control, one place to type.
        className="w-full max-w-sm justify-between text-muted-foreground"
        aria-label="Cerca in tutto il CRM"
      >
        <span className="flex items-center gap-2">
          <Search className="size-4" aria-hidden="true" />
          Cerca…
        </span>
        <kbd className="rounded border bg-muted px-1.5 py-0.5 text-xs font-medium">
          {IS_APPLE ? '⌘' : 'Ctrl'} K
        </kbd>
      </Button>

      {/* Actions. Empty today; see the file docstring. */}
      <div className="flex flex-1 items-center justify-end gap-2" />
    </header>
  )
}
```

- [ ] **Step 4: Mount it in `AppShell`**

Two edits to `apps/web/src/components/AppShell.tsx`, and nothing else in that file changes:

```tsx
// 1. Add the import and the local state, next to `collapsed`:
import { AppHeader } from '@/components/AppHeader'
import { CommandPalette } from '@/features/search/CommandPalette'
// ...
  const [searchOpen, setSearchOpen] = useState(false)

// 2. Replace the closing `<main>` with a column that carries the header above it:
      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader onOpenSearch={() => setSearchOpen(true)} />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
```

The `CommandPalette` import is added **in Task A13**, together with the component; in this task the two `CommandPalette` lines are omitted and `searchOpen` is passed nowhere but `AppHeader`'s callback. Splitting it this way keeps this task's deliverable independently reviewable: a header with a search button that opens nothing yet is a complete, shippable increment, and `pnpm build` stays green.

`AppShell.tsx` grows by roughly six lines and stays well under the 250-line limit; the header itself is a separate file precisely so it does not push it over.

- [ ] **Step 5: Extend the `AppShell` test**

```tsx
// apps/web/src/components/AppShell.test.tsx -- append inside the existing describe.
  it('renders the header with the search control', () => {
    // The existing render helper in this file already wraps AppShell in the router and
    // auth providers; reuse it rather than building a second harness.
    renderAppShell()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cerca/i })).toBeInTheDocument()
  })
```

If the file's existing render helper has another name, use that one; do not add a second harness.

- [ ] **Step 6: Add the query key and regenerate the client**

```ts
// apps/web/src/lib/query.ts -- add to the queryKeys object, keeping the file's ordering.
  // The term is part of the key so an in-flight response for "ross" cannot overwrite the
  // rendering of "rossi": TanStack Query discards the stale entry rather than the
  // component having to compare what came back with what was typed.
  search: (term: string) => ['search', term] as const,
```

With the API running on `:8000`:

Run: `cd apps/web && pnpm generate:api`

This rewrites `src/lib/api-types.ts` with the `/api/search` path **and** with `cursor` typed as `string` on the four list endpoints. `pnpm exec tsc --noEmit` will now fail at every call site that passes a UUID-typed cursor — which is exactly the mechanism slice 1 §10.2 put there. Fix each by removing the parse: `fetchAllDeals` in `apps/web/src/features/deals/queries.ts` is the only shipped walker, and its `cursor` local becomes `string | null` with no other change.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `cd apps/web && pnpm exec vitest run src/components/AppHeader.test.tsx src/components/AppShell.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS, and a clean typecheck.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/AppHeader.tsx \
        apps/web/src/components/AppHeader.test.tsx \
        apps/web/src/components/AppShell.tsx \
        apps/web/src/components/AppShell.test.tsx \
        apps/web/src/lib/query.ts \
        apps/web/src/lib/api-types.ts \
        apps/web/src/features/deals/queries.ts
git commit -m "feat(web): the AppShell header with breadcrumb and search, closing slice 1 §10.1"
```

---

### Task A13: The `cmdk` palette, with its three states

**Files:**
- Modify: `apps/web/package.json` (`cmdk`)
- Create: `apps/web/src/components/ui/command.tsx`
- Create: `apps/web/src/features/search/queries.ts`
- Create: `apps/web/src/features/search/CommandPalette.tsx`
- Create: `apps/web/src/features/search/CommandPalette.test.tsx`
- Modify: `apps/web/src/components/AppShell.tsx` (mount the palette)
- Modify: `apps/web/eslint.config.js` (the `react-refresh` override for `queries.ts`)

**Interfaces:**
- Consumes: `GET /api/search` through the generated client; `queryKeys.search` (Task A12); `AppHeader`'s `onOpenSearch` (Task A12); `QueryErrorBanner`.
- Produces:
  - `apps/web/src/features/search/queries.ts`: `export type SearchResults = components['schemas']['SearchResults']`, `export type SearchGroup = components['schemas']['SearchGroup']`, `export type SearchHit = components['schemas']['SearchHit']`, `export const MIN_TERM_LENGTH = 3`, `export const SEARCH_DEBOUNCE_MS = 250`, `export function useGlobalSearch(term: string)`.
  - `apps/web/src/features/search/CommandPalette.tsx`: `export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void })`.
- Task A14 drives this component through Playwright.

**Four renderings, and the fourth is not an error.** Spec §8.6 plus §8.3: *no results* ("Nessun risultato per «termine»"), *truncated results* (five per class, the real count, "vedi tutti"), *search unavailable* (the error message and **no list**), and below three characters an invitation ("continua a scrivere") that issues no request at all. They are four separate branches, not one list with four captions — a list that renders empty after a failure says "there is none" when the truth is "I do not know".

**The debounce and the cancellation are part of §8, not a later optimisation.** Residuo B2 records that the deal list has no debounce and fires `ceil(n/200)` requests per keystroke; the palette would query five entities on every keystroke, so it is strictly worse. 250 ms, and TanStack Query's own key-based discarding handles the stale response — the term is in the query key, so a response for `ross` cannot paint over the rendering of `rossi`.

- [ ] **Step 1: Add the dependency and the shadcn wrapper**

```bash
cd apps/web && pnpm add cmdk
```

Then pin whatever version resolved into `package.json` in this same commit — the convention this repo already uses for `lucide-react`. Generate the wrapper with the CLI the repo already carries rather than hand-writing it:

```bash
cd apps/web && pnpm dlx shadcn@4.16.1 add command
```

That writes `src/components/ui/command.tsx` in the project's own `radix-nova` style (from `components.json`), exporting `Command`, `CommandDialog`, `CommandEmpty`, `CommandGroup`, `CommandInput`, `CommandItem`, `CommandList` and `CommandSeparator`. If the CLI adds a `dialog` dependency it does not already have, accept it — `dialog.tsx` is already present, so it will be a no-op.

- [ ] **Step 2: Write the failing test**

```tsx
// apps/web/src/features/search/CommandPalette.test.tsx
/**
 * §8.6's three states, as three renderings, plus the sub-three-character invitation.
 *
 * The third state is the one that gets forgotten, so it is the one with the sharpest
 * assertion: with the query failing, the string "Nessun risultato" must be **absent from
 * the DOM**. An empty list drawn after an error *is* a wrong answer -- it says "there is
 * none" when the truth is "I do not know".
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CommandPalette } from './CommandPalette'

const fetchMock = vi.fn()

function renderPalette() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <CommandPalette open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  )
}

function results(overrides: Partial<{ totale: number; totale_e_un_minimo: boolean }> = {}) {
  return {
    termine: 'rossi',
    gruppi: [
      {
        entity: 'customer',
        totale: overrides.totale ?? 1,
        totale_e_un_minimo: overrides.totale_e_un_minimo ?? false,
        hits: [
          {
            entity: 'customer',
            id: '0192f3b2-8c1a-7c3d-9f4e-1a2b3c4d5e6f',
            etichetta: 'Rossi Ingegneria Srl',
            sottotitolo: '01234567890',
            punteggio: '0.8000',
            campo: 'ragione_sociale',
          },
        ],
      },
      { entity: 'person', totale: 0, totale_e_un_minimo: false, hits: [] },
      { entity: 'deal', totale: 0, totale_e_un_minimo: false, hits: [] },
      { entity: 'document', totale: 0, totale_e_un_minimo: false, hits: [] },
    ],
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('CommandPalette', () => {
  it('invites more typing below three characters and issues no request', async () => {
    renderPalette()
    await userEvent.type(screen.getByRole('combobox'), 'ro')
    await vi.advanceTimersByTimeAsync(1000)

    expect(screen.getByText(/continua a scrivere/i)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByText(/nessun risultato/i)).not.toBeInTheDocument()
  })

  it('debounces to a single request per burst of typing', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(results()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    renderPalette()
    await userEvent.type(screen.getByRole('combobox'), 'rossi')
    await vi.advanceTimersByTimeAsync(1000)

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  })

  it('renders a hit with its subtitle', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(results()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    renderPalette()
    await userEvent.type(screen.getByRole('combobox'), 'rossi')
    await vi.advanceTimersByTimeAsync(1000)

    expect(await screen.findByText('Rossi Ingegneria Srl')).toBeInTheDocument()
    expect(screen.getByText('01234567890')).toBeInTheDocument()
  })

  it('states the real count and offers "vedi tutti" when the group is truncated', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(results({ totale: 42 })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    renderPalette()
    await userEvent.type(screen.getByRole('combobox'), 'rossi')
    await vi.advanceTimersByTimeAsync(1000)

    expect(await screen.findByText(/42/)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /vedi tutti/i })).toBeInTheDocument()
  })

  it('says "oltre 200" rather than "200" when the count is a minimum', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify(results({ totale: 200, totale_e_un_minimo: true })),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    renderPalette()
    await userEvent.type(screen.getByRole('combobox'), 'rossi')
    await vi.advanceTimersByTimeAsync(1000)

    expect(await screen.findByText(/oltre 200/i)).toBeInTheDocument()
  })

  it('says there is nothing, naming the term, when every group is empty', async () => {
    const empty = { termine: 'zzzqqq', gruppi: results().gruppi.map((g) => ({ ...g, hits: [], totale: 0 })) }
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(empty), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    renderPalette()
    await userEvent.type(screen.getByRole('combobox'), 'zzzqqq')
    await vi.advanceTimersByTimeAsync(1000)

    expect(await screen.findByText(/nessun risultato per/i)).toBeInTheDocument()
    expect(screen.getByText(/zzzqqq/)).toBeInTheDocument()
  })

  it('renders the error state and NOT an empty result when the query fails', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ type: 'about:blank', title: 'Errore', detail: 'Ricerca non disponibile' }),
        { status: 500, headers: { 'content-type': 'application/problem+json' } },
      ),
    )
    renderPalette()
    await userEvent.type(screen.getByRole('combobox'), 'rossi')
    await vi.advanceTimersByTimeAsync(2000)

    expect(await screen.findByRole('alert')).toHaveTextContent(/ricerca non disponibile/i)
    // The assertion §8.6 exists for.
    expect(screen.queryByText(/nessun risultato/i)).not.toBeInTheDocument()
    expect(screen.queryAllByRole('option')).toHaveLength(0)
  })
})
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd apps/web && pnpm exec vitest run src/features/search/CommandPalette.test.tsx`
Expected: `Failed to resolve import "./CommandPalette"`.

- [ ] **Step 4: Write the query hook**

```ts
// apps/web/src/features/search/queries.ts
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

export type SearchResults = components['schemas']['SearchResults']
export type SearchGroup = components['schemas']['SearchGroup']
export type SearchHit = components['schemas']['SearchHit']

/**
 * Below this the palette issues no request at all. Spec §8.3: a trigram index cannot
 * serve a pattern from which no trigram can be extracted, and a two-character term on
 * 50 000 customers returns thousands of rows, which is not an answer either. The API
 * enforces the same bound; this is the half that stops the request being made.
 */
export const MIN_TERM_LENGTH = 3

/**
 * Residuo B2 gets worse here than on the deal list: the palette queries five entities on
 * every keystroke. 250 ms is short enough to feel immediate and long enough that typing
 * "rossi" is one request, not five.
 */
export const SEARCH_DEBOUNCE_MS = 250

function useDebounced(value: string, delayMs: number): string {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return settled
}

/**
 * The previous request is not aborted by hand. TanStack Query keys the cache by the term,
 * so an in-flight response for "ross" resolves into its own entry and cannot paint over
 * the rendering of "rossi"; the component reads only the entry for the term it is
 * currently showing. Manual `AbortController` plumbing would add a second mechanism for
 * the property the key already gives.
 *
 * `enabled` is the guard, not an early `return`: a hook must never be called with an
 * argument it cannot serve (residuo B1), and a short term is exactly that case.
 */
export function useGlobalSearch(term: string) {
  const debounced = useDebounced(term.trim(), SEARCH_DEBOUNCE_MS)
  const query = useQuery({
    queryKey: queryKeys.search(debounced),
    queryFn: () => unwrap(api.GET('/api/search', { params: { query: { q: debounced } } })),
    enabled: debounced.length >= MIN_TERM_LENGTH,
    // A palette is re-opened constantly and the same term is retyped constantly. Ten
    // seconds is long enough to make reopening instant and short enough that a record
    // created a moment ago is findable.
    staleTime: 10_000,
  })
  return { ...query, debounced }
}

export const ENTITY_LABELS: Record<SearchGroup['entity'], string> = {
  customer: 'Clienti',
  person: 'Persone',
  deal: 'Deal',
  document: 'Documenti',
  invoice: 'Fatture',
}

/** Where a hit's row navigates, and where its group's "vedi tutti" navigates. */
export const ENTITY_ROUTES: Record<
  SearchGroup['entity'],
  { detail: (id: string) => string; list: (term: string) => string }
> = {
  customer: {
    detail: (id) => `/app/clienti/${id}`,
    list: (term) => `/app/clienti?search=${encodeURIComponent(term)}`,
  },
  person: {
    detail: (id) => `/app/persone/${id}`,
    list: (term) => `/app/persone?search=${encodeURIComponent(term)}`,
  },
  deal: {
    detail: (id) => `/app/deal/${id}`,
    list: (term) => `/app/deal/lista?search=${encodeURIComponent(term)}`,
  },
  document: {
    detail: (id) => `/app/documenti/${id}`,
    list: (term) => `/app/documenti?search=${encodeURIComponent(term)}`,
  },
  // 6C's Task C13 adds the branch; the route is declared here so the record is
  // exhaustive and `tsc` catches the omission rather than a runtime `undefined`.
  invoice: {
    detail: (id) => `/app/fatture/${id}`,
    list: (term) => `/app/fatture?search=${encodeURIComponent(term)}`,
  },
}
```

- [ ] **Step 5: Write the palette**

```tsx
// apps/web/src/features/search/CommandPalette.tsx
import { useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import {
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import {
  ENTITY_LABELS,
  ENTITY_ROUTES,
  MIN_TERM_LENGTH,
  useGlobalSearch,
  type SearchGroup,
} from './queries'

/**
 * The four renderings of §8.6 and §8.3, as four branches.
 *
 * They are branches and not captions on one list because a list rendered empty after a
 * failure *is* a wrong answer: it says "there is none" when the truth is "I do not know".
 * The error branch renders no `<CommandList>` at all, which is what makes the assertion
 * "the string «Nessun risultato» is absent from the DOM" hold structurally rather than by
 * a conditional someone can later invert.
 *
 * `cmdk` rather than `dialog` + `input`: an accessible combobox -- ARIA roles,
 * `aria-activedescendant`, keyboard navigation, results announced to a screen reader -- is
 * one of the things that is written badly by hand, and the cost is one small dependency in
 * a project that already carries `radix-ui`.
 *
 * `shouldFilter={false}` is load-bearing: `cmdk` filters and reorders client-side by
 * default, which would apply a second, different ranking on top of §8.5's. The server
 * ranks; this renders.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [term, setTerm] = useState('')
  const navigate = useNavigate()
  const search = useGlobalSearch(term)

  // Cmd/Ctrl+K from anywhere. Either modifier is accepted regardless of platform: a user
  // on a Mac keyboard plugged into Linux should not have to know which one this build
  // decided to draw in the header.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        onOpenChange(!open)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onOpenChange])

  function go(path: string) {
    onOpenChange(false)
    setTerm('')
    void navigate({ to: path })
  }

  const tooShort = search.debounced.length < MIN_TERM_LENGTH
  const groups: SearchGroup[] = search.data?.gruppi ?? []
  const anyHits = groups.some((group) => group.hits.length > 0)

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} shouldFilter={false}>
      <CommandInput
        value={term}
        onValueChange={setTerm}
        placeholder="Cerca clienti, persone, deal, documenti…"
        aria-label="Cerca in tutto il CRM"
      />

      {/* State 4 (not an error): an invitation, and no request was made. */}
      {tooShort && (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          Continua a scrivere: servono almeno {MIN_TERM_LENGTH} caratteri.
        </p>
      )}

      {/* State 3: unavailable. No list is rendered at all. */}
      {!tooShort && search.isError && (
        <div className="px-4 py-4">
          <QueryErrorBanner error={search.error} />
        </div>
      )}

      {!tooShort && !search.isError && (
        <CommandList>
          {search.isLoading && (
            <p role="status" className="px-4 py-6 text-sm text-muted-foreground">
              Ricerca in corso…
            </p>
          )}

          {/* State 1: nothing, and the term is named so the user can see what was asked. */}
          {!search.isLoading && !anyHits && (
            <p className="px-4 py-6 text-sm text-muted-foreground">
              Nessun risultato per «{search.debounced}»
            </p>
          )}

          {/* State 2: truncated, with the real count and a way to the whole set. */}
          {groups.map((group, index) =>
            group.hits.length === 0 ? null : (
              <div key={group.entity}>
                {index > 0 && <CommandSeparator />}
                <CommandGroup
                  heading={`${ENTITY_LABELS[group.entity]} · ${
                    group.totale_e_un_minimo ? `oltre ${group.totale}` : group.totale
                  }`}
                >
                  {group.hits.map((hit) => (
                    <CommandItem
                      key={hit.id}
                      value={hit.id}
                      onSelect={() => go(ENTITY_ROUTES[group.entity].detail(hit.id))}
                    >
                      <span className="truncate">{hit.etichetta}</span>
                      {hit.sottotitolo && (
                        <span className="ml-2 truncate text-xs text-muted-foreground">
                          {hit.sottotitolo}
                        </span>
                      )}
                    </CommandItem>
                  ))}
                  {group.hits.length < group.totale && (
                    <CommandItem
                      value={`vedi-tutti-${group.entity}`}
                      onSelect={() =>
                        go(ENTITY_ROUTES[group.entity].list(search.debounced))
                      }
                    >
                      Vedi tutti{' '}
                      {group.totale_e_un_minimo ? `oltre ${group.totale}` : group.totale}{' '}
                      {ENTITY_LABELS[group.entity].toLowerCase()}
                    </CommandItem>
                  )}
                </CommandGroup>
              </div>
            ),
          )}
        </CommandList>
      )}
    </CommandDialog>
  )
}
```

- [ ] **Step 6: Mount it and add the eslint override**

Add the two `CommandPalette` lines to `apps/web/src/components/AppShell.tsx` that Task A12 Step 4 deferred.

```js
// apps/web/eslint.config.js -- add an override in the same shape as the existing ones.
  {
    files: ['src/features/search/queries.ts'],
    rules: {
      'react-refresh/only-export-components': [
        'warn',
        { allowExportNames: ['MIN_TERM_LENGTH', 'SEARCH_DEBOUNCE_MS', 'ENTITY_LABELS', 'ENTITY_ROUTES', 'useGlobalSearch'] },
      ],
    },
  },
```

- [ ] **Step 7: Run the tests and watch them pass**

Run: `cd apps/web && pnpm exec vitest run src/features/search/CommandPalette.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS, seven tests, clean typecheck, clean lint.

- [ ] **Step 8: Commit**

```bash
git add apps/web/package.json apps/web/pnpm-lock.yaml \
        apps/web/src/components/ui/command.tsx \
        apps/web/src/features/search/ \
        apps/web/src/components/AppShell.tsx \
        apps/web/eslint.config.js
git commit -m "feat(web): cmdk command palette with four distinct states and a debounce"
```

---
### Task A14: Criterion 5 — no silent partial result, in a real browser

**Files:**
- Create: `apps/web/e2e/search.spec.ts`
- Modify: `apps/web/e2e/helpers.ts` (a helper that seeds N customers through the API)

**Interfaces:**
- Consumes: the running stack `apps/web/scripts/e2e.sh` starts (API on `:8000`, Vite on `:5173`, its own Postgres on `:55433`); the existing `login` helper in `apps/web/e2e/helpers.ts`; the palette from Task A13.
- Produces: `apps/web/e2e/helpers.ts` gains `export async function seedCustomers(page: Page, prefix: string, count: number): Promise<void>`.

**The three assertions this task exists for**, straight out of §16 criterion 5: with 500 matching rows the palette shows five per class, the real count and the link to the full list; with the database refusing the query the error state appears and the string `Nessun risultato` is **not present in the DOM**; with a two-character term **no HTTP request is issued**. The last two are the ones a unit test cannot honestly make — one needs a real failing backend, the other needs a real network.

- [ ] **Step 1: Add the seeding helper**

```ts
// apps/web/e2e/helpers.ts -- append. Follow the file's existing import of `Page`.

/**
 * Seeds `count` customers through the real API, in parallel batches.
 *
 * Through the API and not through the UI: 500 rows via forms would take minutes and would
 * be testing the form, not the palette. Through the page's own context so the auth cookie
 * travels — `page.request` shares the browser's cookie jar, `request` from the fixture
 * does not.
 */
export async function seedCustomers(page: Page, prefix: string, count: number): Promise<void> {
  const BATCH = 25
  for (let start = 0; start < count; start += BATCH) {
    const size = Math.min(BATCH, count - start)
    await Promise.all(
      Array.from({ length: size }, (_, offset) =>
        page.request.post('http://localhost:8000/api/customers', {
          data: { ragione_sociale: `${prefix} ${String(start + offset).padStart(4, '0')} Srl` },
        }),
      ),
    )
  }
}
```

- [ ] **Step 2: Write the failing spec**

```ts
// apps/web/e2e/search.spec.ts
/**
 * **Criterion 5.** No silent partial result, and no empty list drawn after a failure.
 *
 * Three of these four assertions cannot be made honestly anywhere else: one needs a real
 * network to observe that no request was issued, one needs a real backend that refuses the
 * query, and one needs 500 real rows to make truncation happen rather than be simulated.
 */
import { expect, test } from '@playwright/test'
import { login, seedCustomers } from './helpers'

test.describe('ricerca globale', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
    await page.goto('/app')
  })

  test('si apre con Cmd/Ctrl+K da qualunque schermata', async ({ page }) => {
    await page.goto('/app/clienti')
    await page.keyboard.press('ControlOrMeta+k')
    await expect(page.getByRole('combobox')).toBeFocused()
  })

  test('sotto i tre caratteri invita a scrivere e non emette nessuna richiesta', async ({
    page,
  }) => {
    const searchRequests: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('/api/search')) searchRequests.push(request.url())
    })

    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('combobox').fill('ro')
    // Well past the 250 ms debounce: the assertion is that nothing was ever sent, not
    // that nothing had been sent yet.
    await page.waitForTimeout(1500)

    await expect(page.getByText(/continua a scrivere/i)).toBeVisible()
    expect(searchRequests).toEqual([])
    await expect(page.getByText(/nessun risultato/i)).toHaveCount(0)
  })

  test('con 500 corrispondenze mostra 5 per classe, il conteggio reale e «vedi tutti»', async ({
    page,
  }) => {
    await seedCustomers(page, 'Truncato', 500)
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('combobox').fill('Truncato')

    // "oltre 200": the count is exact to 200 and declared as a minimum beyond it (§8.5).
    // The palette must never render the bare number 200, which would be a lie.
    await expect(page.getByText(/oltre 200/i)).toBeVisible()

    const options = page.getByRole('option')
    // Five hits plus the "vedi tutti" row, in the one group that matched.
    await expect(options).toHaveCount(6)
    await expect(page.getByRole('option', { name: /vedi tutti/i })).toBeVisible()
  })

  test('«vedi tutti» porta all\'elenco filtrato con lo stesso termine', async ({ page }) => {
    await seedCustomers(page, 'Elenco', 12)
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('combobox').fill('Elenco')
    await page.getByRole('option', { name: /vedi tutti/i }).click()

    await expect(page).toHaveURL(/\/app\/clienti\?search=Elenco/)
  })

  test('un termine senza corrispondenze lo dice, e nomina il termine', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('combobox').fill('zzzqqqwww')

    await expect(page.getByText(/nessun risultato per/i)).toBeVisible()
    await expect(page.getByText(/zzzqqqwww/)).toBeVisible()
  })

  test('con la ricerca che fallisce mostra l\'errore e NON «Nessun risultato»', async ({
    page,
  }) => {
    // The database refusing the query, simulated at the only boundary a browser test can
    // reach: the response. A 500 with a problem document is exactly what
    // `domain_error_handler` produces when a query fails, so the client sees the real
    // shape and not an invented one.
    await page.route('**/api/search**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/problem+json',
        body: JSON.stringify({
          type: 'about:blank',
          title: 'Errore interno',
          status: 500,
          detail: 'Ricerca non disponibile',
        }),
      })
    })

    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('combobox').fill('Rossi')

    // `lib/query.ts` retries twice with backoff on anything that is not a 401/403, so the
    // banner takes a moment. `playwright.config.ts` already raises the expect timeout to
    // 8 s for exactly this reason (see its own comment).
    await expect(page.getByRole('alert')).toContainText(/ricerca non disponibile/i)

    // The assertion §8.6 exists for. An empty list drawn after an error *is* a wrong
    // answer: it says "there is none" when the truth is "I do not know".
    await expect(page.getByText(/nessun risultato/i)).toHaveCount(0)
    await expect(page.getByRole('option')).toHaveCount(0)
  })

  test('un frammento di partita IVA trova il cliente', async ({ page }) => {
    await page.request.post('http://localhost:8000/api/customers', {
      data: { ragione_sociale: 'Rossi Ingegneria Srl', partita_iva: '01234567890' },
    })
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('combobox').fill('34567')

    await expect(page.getByRole('option', { name: /Rossi Ingegneria Srl/ })).toBeVisible()
  })
})
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd apps/web && pnpm test:e2e`

Expected before Tasks A12 and A13 are merged: every test FAILS at `page.keyboard.press('ControlOrMeta+k')` because no combobox appears. After them: PASS, seven tests.

`playwright.config.ts` runs `workers: 1` and `fullyParallel: false` against one shared database, so the 500 seeded rows persist into later specs in the same run. That is why every prefix here is distinctive (`Truncato`, `Elenco`) and every assertion is scoped to its own prefix — a spec that searched for a generic term would pass or fail depending on which other spec ran first.

- [ ] **Step 4: Full frontend gate**

Run: `cd apps/web && pnpm exec vitest run && pnpm exec tsc --noEmit && pnpm lint && pnpm test:e2e`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add apps/web/e2e/search.spec.ts apps/web/e2e/helpers.ts
git commit -m "test(web): criterion 5, the palette's three states in a real browser"
```

---

## 6A is done. What it closed, and what it did not

| Residuo | State after 6A |
|---|---|
| **R6** — search `ilike` with no index | **Closed** for `customers`, `people`, `deals`, `documents`, with the plan measured in CI (Task A9) and the index-removal check that makes the measurement mean something. Open for `invoices` until Task C13. **What remains, and it is written rather than declared closed:** a one- or two-character `search` on a *list* endpoint is still a sequential scan. It has a known upper bound (`limit` is at most 200) and no path from the palette or from an agent reaches it |
| **R9** — the ordering §7 promised | **Closed** for those same four entities, with a composite opaque cursor and thirteen B-tree indexes. **Open for every other surface**, and that is the honest statement: `time_entries` and `costs` are born ordered (slice 4 §12), `invoices` has its own filters (slice 3 §11), and the general defect on all remaining lists stands |
| **R7** — no partial index on `deleted_at` | **Closed for the four tables 6A indexes**, as a side effect of the trigram indexes being partial. The general defect stands |
| **B2** — no debounce | **Closed for the palette** (250 ms, Task A13). Still open on the deal list, which this slice does not touch |
| slice 1 §10.1's missing header | **Closed** (Task A12) |
| **R1** — shared MCP session | **Untouched.** Task A11's Step 6 gates the MCP half of the search tool on it and ships the API half regardless |
| **A14**, **R10**, **R11**, **R14**, **R15**, **A12**, **B3** | Untouched, deliberately. Contradictions 7, 13 and 14 above give the reasoning for each |

---
# Sub-plan 6B — Automazioni, segnali e dashboard commerciale

**Before 6B can start, all of this must already be true.** Verify, do not assume:

| Prerequisite | How to check | If it is missing |
|---|---|---|
| **Sub-plan 6A merged** | `packages/core/src/pigrocrm/core/search/service.py` exists and `uv run pytest -q` is green | Stop. 6B's dashboard page mounts inside the `AppShell` header 6A builds, and 6B's migrations follow 6A's in the chain |
| Slice 2 in `main` | `packages/core/src/pigrocrm/core/documents/service.py` defines `OFFER_TRANSITIONS` and `set_offer_state` | Stop. `set_offer_state` is the **only** trigger the automations have; without it §9 has nothing to hook onto |
| `pipeline_stages` seeds `code='vinto'` and `code='offerta'` | `DEFAULT_STAGES` in `packages/core/src/pigrocrm/core/pipeline/service.py` | Stop and fix the seed. The automations resolve by `code` and refuse to guess by name — that is the point of R11's column existing |
| The migration chain head | `ls packages/core/migrations/versions/` | 6B's migration follows whatever the real head is. This plan writes `0008` because 6A adds `0006` and `0007` on top of slice 3's `0005`; check, do not trust the number |
| The suite is green | `uv run pytest -q` | Fix that first |

**6B needs nothing from slices 3, 4 or 5.** The commercial dashboard reads `deals`, `pipeline_stages` and `documents` and nothing else — that is precisely why it is the dashboard that ships first (§4, §17).

**6B executes §16 criteria 7, 8 and 9, plus 2, 6 and 14 on the commercial dashboard.** Those last three are criteria for *every* dashboard, and they fall due with the first one rather than waiting for 6C.

---

### Task B1: One clock

**Files:**
- Modify: `packages/core/src/pigrocrm/core/config.py`
- Create: `packages/core/src/pigrocrm/core/db/clock.py`
- Modify: `packages/core/src/pigrocrm/core/db/__init__.py`
- Create: `packages/core/tests/test_clock.py`

**Interfaces:**
- Consumes: `pigrocrm.core.config.Settings`, `get_settings`.
- Produces, importable from `pigrocrm.core.db`:
  - `today_local(settings: Settings | None = None) -> date`
  - `month_bounds(anno: int, mese: int) -> tuple[date, date]`
  - `Settings.timezone: str = "Europe/Rome"`, validated at construction against `zoneinfo.available_timezones()`.
- Tasks B2, B5, B7, B8 and C7 all call `today_local`. Nothing else in the project may call `date.today()` or `datetime.now(UTC).date()`, and Task B9's AST test is extended to say so.

**Why this exists at all.** Spec §4.1 requires the calendar-day computation for `chiuso_il` to use "lo stesso meccanismo di fuso che lo slice 3 §6.2 impone a `data_emissione`, non un secondo". There is no such mechanism to reuse: slice 3 §6.2 states a *rule* (a `date` is not an instant; never project a `timestamptz` through UTC), and for an invoice the date is supplied by the caller and validated rather than derived from "now". So the mechanism is introduced once, here, and its docstring says it is the project's only clock.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_clock.py
"""The project's only clock.

`datetime.now(UTC).date()` is wrong for every figure in this slice, and wrong in a way
that is invisible for twenty-three hours a day: at 00:30 on 1 April in Rome it is still
31 March in UTC, so a deal won just after midnight lands in the previous month's
conversion rate. `deals.chiuso_il`, `documents.stato_dal`, `invoices.data_emissione`,
`costs.data` and `time_entries.data` are all calendar dates in the *emitter's* day, not
instants, and slice 3 §6.2 already fixed that rule — this module is the mechanism.

Two clocks in one product is a bug that shows up on 31 December, which is the worst
possible day to find it.
"""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from pigrocrm.core.config import Settings
from pigrocrm.core.db import month_bounds, today_local


def test_the_default_timezone_is_rome() -> None:
    assert Settings().timezone == "Europe/Rome"


def test_an_unknown_timezone_is_refused_at_construction() -> None:
    """A typo in an environment variable must fail at start-up, not silently fall back to
    UTC and shift every date by an hour for the life of the deployment."""
    with pytest.raises(ValidationError):
        Settings(timezone="Europe/Atlantis")


def test_today_local_is_the_emitter_day_not_the_utc_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """00:30 on 1 April in Rome is 22:30 on 31 March in UTC. The clock must answer
    1 April."""
    import pigrocrm.core.db.clock as clock

    frozen = datetime(2026, 3, 31, 22, 30, tzinfo=UTC)
    monkeypatch.setattr(clock, "_now", lambda: frozen)

    assert today_local(Settings(timezone="Europe/Rome")) == date(2026, 4, 1)
    assert today_local(Settings(timezone="UTC")) == date(2026, 3, 31)


def test_today_local_handles_the_dst_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 2026 spring-forward in Rome is 29 March. 00:30 UTC on that day is 01:30 CET,
    still 29 March -- the date must not jump."""
    import pigrocrm.core.db.clock as clock

    monkeypatch.setattr(clock, "_now", lambda: datetime(2026, 3, 29, 0, 30, tzinfo=UTC))
    assert today_local(Settings(timezone="Europe/Rome")) == date(2026, 3, 29)


def test_today_local_with_no_argument_uses_the_cached_settings() -> None:
    """Callers deep in a repository should not have to thread `Settings` through four
    layers to learn what day it is."""
    assert isinstance(today_local(), date)


def test_month_bounds_is_inclusive_at_both_ends() -> None:
    assert month_bounds(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))
    assert month_bounds(2026, 12) == (date(2026, 12, 1), date(2026, 12, 31))


@pytest.mark.parametrize("mese", [0, 13, -1])
def test_month_bounds_refuses_a_month_outside_one_to_twelve(mese: int) -> None:
    from pigrocrm.core.errors import ValidationFailed

    with pytest.raises(ValidationFailed) as caught:
        month_bounds(2026, mese)
    assert caught.value.details["field"] == "mese"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_clock.py -v`
Expected: collection error — `ImportError: cannot import name 'month_bounds' from 'pigrocrm.core.db'`.

- [ ] **Step 3: Add the setting**

```python
# packages/core/src/pigrocrm/core/config.py
# Add `from zoneinfo import ZoneInfo, available_timezones` to the imports, and this field
# to Settings, immediately after `cookie_secure`:

    # The emitter's timezone, and the only one. Every `Date` column in the product is a
    # calendar day in *this* zone: `invoices.data_emissione` (slice 3 §6.2),
    # `costs.data` and `time_entries.data` (slice 4), `deals.chiuso_il` and
    # `documents.stato_dal` (slice 6 §4.1). Deriving any of them from
    # `datetime.now(UTC).date()` moves everything after 23:00 CET by a day and everything
    # on 31 December by a year — the exact defect slice 3 §6.2 names. Single-tenant, so
    # one zone: a per-user zone would mean the same invoice falling in two fiscal years
    # depending on who looked at it.
    timezone: str = "Europe/Rome"

# And this validator, next to `_jwt_secret_must_be_long_enough`:

    @field_validator("timezone")
    @classmethod
    def _timezone_must_be_a_real_zone(cls, value: str) -> str:
        # Checked against the tz database at construction, not at first use: a typo in
        # PIGROCRM_TIMEZONE must fail at start-up rather than shift every date in the
        # product by an hour for the life of the deployment.
        if value not in available_timezones():
            raise ValueError(
                f"timezone {value!r} is not in the IANA tz database "
                "(examples: Europe/Rome, UTC)"
            )
        return value
```

`ZoneInfo` is imported in `config.py` only if the validator needs it; it does not, so import `available_timezones` alone and let `clock.py` import `ZoneInfo`. Keep the import line to what is used — `ruff` fails on an unused import.

- [ ] **Step 4: Write the clock**

```python
# packages/core/src/pigrocrm/core/db/clock.py
"""The project's only clock.

Nothing anywhere in `packages/core`, `apps/api` or `apps/mcp` may call `date.today()` or
`datetime.now(UTC).date()` to obtain a calendar day. Both answer the *UTC* day, and every
`Date` column in this product is a day in the emitter's zone: at 00:30 on 1 April in Rome
it is still 31 March in UTC, so a deal won just after midnight would land in the previous
month's conversion rate, and an invoice issued on 31 December at 23:30 CET would land in
the previous fiscal year — the defect slice 3 §6.2 names by name.

`datetime.now(UTC)` for a *timestamp* is still correct and still required: `created_at`,
`updated_at`, `deleted_at` and `occurred_at` are instants, and an instant has no zone
problem. This module is about the other kind of column.

`_now` is a module-level function rather than an inline call so a test can freeze it
without patching the standard library.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.errors import ValidationFailed

# Days per month, non-leap. February is corrected in `month_bounds`.
_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _now() -> datetime:
    return datetime.now(UTC)


def today_local(settings: Settings | None = None) -> date:
    """Today, in the emitter's zone.

    `settings` is optional so a repository three layers down does not have to thread it
    through; passing it explicitly is what makes the tests able to check two zones without
    touching the environment.
    """
    resolved = settings if settings is not None else get_settings()
    return _now().astimezone(ZoneInfo(resolved.timezone)).date()


def month_bounds(anno: int, mese: int) -> tuple[date, date]:
    """The first and last day of a month, both inclusive.

    Inclusive at both ends because every period filter in this slice and in slice 4 is
    `BETWEEN da AND a` over a `Date` column. A half-open convention would be defensible
    and would also mean two conventions in one product, which is how a December figure
    ends up counted twice.

    Computed rather than taken from `calendar.monthrange`: the arithmetic is four lines,
    and this way the leap rule is visible next to the only place that depends on it.
    """
    if not 1 <= mese <= 12:
        raise ValidationFailed(
            "periodo", "mese", "mese fuori intervallo", expected="1-12"
        )
    last = _DAYS_IN_MONTH[mese - 1]
    if mese == 2 and (anno % 4 == 0 and (anno % 100 != 0 or anno % 400 == 0)):
        last = 29
    return date(anno, mese, 1), date(anno, mese, last)
```

- [ ] **Step 5: Re-export**

```python
# packages/core/src/pigrocrm/core/db/__init__.py -- add to the imports and __all__:
from pigrocrm.core.db.clock import month_bounds, today_local
# "month_bounds" and "today_local" in __all__, alphabetically sorted as ruff requires.
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_clock.py -v`
Expected: PASS, eight tests (the parametrised one expands to three).

- [ ] **Step 7: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/config.py \
        packages/core/src/pigrocrm/core/db/clock.py \
        packages/core/src/pigrocrm/core/db/__init__.py \
        packages/core/tests/test_clock.py
git commit -m "feat(core): one clock for calendar dates, in the emitter's timezone"
```

---

### Task B2: `deals.chiuso_il`, `documents.stato_dal`, and their writers

**Files:**
- Modify: `packages/core/src/pigrocrm/core/deals/models.py` (one column, one index)
- Modify: `packages/core/src/pigrocrm/core/deals/schemas.py` (`DealRead.chiuso_il`)
- Modify: `packages/core/src/pigrocrm/core/deals/service.py` (`move_stage`)
- Modify: `packages/core/src/pigrocrm/core/documents/models.py` (one column, one index)
- Modify: `packages/core/src/pigrocrm/core/documents/schemas.py` (`DocumentRead.stato_dal`)
- Modify: `packages/core/src/pigrocrm/core/documents/service.py` (`set_offer_state`)
- Create: `packages/core/migrations/versions/0008_automations_and_dates.py`
- Modify: `packages/core/tests/test_migrations.py`
- Create: `packages/core/tests/test_closure_dates.py`

**Interfaces:**
- Consumes: `today_local` from `pigrocrm.core.db` (Task B1); `PipelineStageRead.tipo`; `OFFER_TRANSITIONS`.
- Produces:
  - `Deal.chiuso_il: Mapped[date | None]`, and `DealRead.chiuso_il: date | None`
  - `Document.stato_dal: Mapped[date | None]`, and `DocumentRead.stato_dal: date | None`
  - Indexes `ix_deals_chiuso_il` and `ix_documents_stato_dal`
  - Migration `0008` also creates `automation_config` (Task B3's table, in the same revision — see the note below)
- Tasks B7 and B8 read both columns; Task B5 writes `stato_dal` through the same path.

**One migration for both columns and the config table, and that is deliberate.** Three revisions in one sub-plan means three `alembic upgrade head` round-trips in the test suite's slowest test, and the three objects are meaningless apart: the automation cannot run without the config row and cannot record a closure without the column. Task B3 writes the `automation_config` half of the same file; this task writes the two columns and leaves the table's `op.create_table` call to B3, in the same file, in a section marked for it. If B3 is deferred, `0008` still applies cleanly — a migration with two of its three sections is a valid migration.

**Neither column is `NOT NULL`, and one is not backfilled.** `documents.stato_dal` **is** backfilled from the timeline, because the offer timeline's payload is `{"da": "inviata", "a": "accettata"}` — literals of `OfferState`, never user text. `deals.chiuso_il` is **not**, because `DealService.move_stage` records `{"from": <nome>, "to": <nome>}` — the *names*, which the user is free to rename (residuo R15). Deducing "when was this deal won" from a mutable string is exactly what `pipeline_stages.tipo` and `code` exist to avoid, and a guessed conversion rate is the worst kind of figure: plausible and wrong.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_closure_dates.py
"""The two date columns §4.1 adds, and the asymmetry that decides their backfill.

`Date`, not `timestamptz`, against slice 1 §5's general convention and for slice 3 §6.2's
precise reason: a date that decides which period a figure falls in is not an instant. All
of this slice's period filters land on `Date` columns -- `invoices.data_emissione`,
`costs.data`, `time_entries.data`, `chiuso_il` -- and no mixed comparison exists anywhere.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import today_local
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=None, type="system", role="admin")


@pytest.fixture
def stages(db_session: Session) -> dict[str, object]:
    PipelineService(db_session).seed_defaults(ADMIN)
    return {
        stage.code: stage
        for stage in PipelineService(db_session).list()
        if stage.code is not None
    }


def _deal(db_session: Session, stage_id: object) -> Deal:
    customer = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(customer)
    db_session.flush()
    deal = Deal(
        nome="Impianto", customer_id=customer.id, pipeline_stage_id=stage_id,
        probabilita=50, custom_fields={},
    )
    db_session.add(deal)
    db_session.flush()
    return deal


def test_a_new_deal_has_no_closure_date(db_session: Session, stages: dict) -> None:
    deal = _deal(db_session, stages["lead"].id)
    assert deal.chiuso_il is None


def test_moving_to_a_won_stage_stamps_the_local_day(
    db_session: Session, stages: dict
) -> None:
    deal = _deal(db_session, stages["lead"].id)
    DealService(db_session).move_stage(deal.id, stages["vinto"].id, ADMIN)
    db_session.refresh(deal)
    assert deal.chiuso_il == today_local()


def test_moving_to_a_lost_stage_also_stamps_it(db_session: Session, stages: dict) -> None:
    """`tipo != 'open'`, not `tipo == 'won'`: a lost deal is closed too, and the
    conversion rate needs both halves of the denominator."""
    deal = _deal(db_session, stages["lead"].id)
    DealService(db_session).move_stage(deal.id, stages["perso"].id, ADMIN)
    db_session.refresh(deal)
    assert deal.chiuso_il == today_local()


def test_reopening_a_deal_clears_the_closure_date(
    db_session: Session, stages: dict
) -> None:
    """A reopened deal is not a deal closed in March. Leaving the stamp would put it in
    both the conversion rate and the open pipeline at the same time."""
    service = DealService(db_session)
    deal = _deal(db_session, stages["lead"].id)
    service.move_stage(deal.id, stages["vinto"].id, ADMIN)
    service.move_stage(deal.id, stages["negoziazione"].id, ADMIN)
    db_session.refresh(deal)
    assert deal.chiuso_il is None


def test_moving_between_two_open_stages_never_stamps_it(
    db_session: Session, stages: dict
) -> None:
    deal = _deal(db_session, stages["lead"].id)
    DealService(db_session).move_stage(deal.id, stages["offerta"].id, ADMIN)
    db_session.refresh(deal)
    assert deal.chiuso_il is None


def test_moving_from_won_to_lost_keeps_the_original_closure_date(
    db_session: Session, stages: dict
) -> None:
    """A correction of *which* terminal state, not a new closure. Restamping would move
    the deal into the month someone fixed the mistake in."""
    service = DealService(db_session)
    deal = _deal(db_session, stages["lead"].id)
    service.move_stage(deal.id, stages["vinto"].id, ADMIN)
    db_session.refresh(deal)
    original = deal.chiuso_il
    deal.chiuso_il = date(2026, 1, 15)  # simulate a closure recorded earlier
    db_session.flush()

    service.move_stage(deal.id, stages["perso"].id, ADMIN)
    db_session.refresh(deal)
    assert deal.chiuso_il == date(2026, 1, 15), original


def test_chiuso_il_is_exposed_on_the_read_schema(db_session: Session, stages: dict) -> None:
    deal = _deal(db_session, stages["lead"].id)
    read = DealService(db_session).move_stage(deal.id, stages["vinto"].id, ADMIN)
    assert read.chiuso_il == today_local()


def test_setting_an_offer_state_stamps_stato_dal(
    db_session: Session, document_service: DocumentService
) -> None:
    """`documents.stato_dal` is what makes "questa offerta è ferma da N giorni"
    answerable; §4 shows the age in days on the commercial dashboard."""
    document = document_service.create_offer_for_test()  # see the note below
    document_service.set_offer_state(document.id, "inviata", ADMIN)
    row = db_session.get(Document, document.id)
    assert row is not None
    assert row.stato_dal == today_local()


def test_stato_dal_moves_on_every_state_change(
    db_session: Session, document_service: DocumentService
) -> None:
    document = document_service.create_offer_for_test()
    document_service.set_offer_state(document.id, "inviata", ADMIN)
    row = db_session.get(Document, document.id)
    assert row is not None
    row.stato_dal = date(2026, 1, 1)
    db_session.flush()

    document_service.set_offer_state(document.id, "accettata", ADMIN)
    db_session.refresh(row)
    assert row.stato_dal == today_local()


def test_both_columns_are_date_and_not_timestamp() -> None:
    """Asserted on the type, because the whole argument of §4.1 rests on it and a
    `DateTime` here would still pass every test above."""
    from sqlalchemy import Date

    assert isinstance(Deal.__table__.c.chiuso_il.type, Date)
    assert isinstance(Document.__table__.c.stato_dal.type, Date)
    assert not isinstance(Deal.__table__.c.chiuso_il.type, datetime.__class__)
```

For the two `document_service` tests, use whatever fixture `packages/core/tests/test_documents_service.py` already provides for building an offer with a `deal_id`; if it is a local helper rather than a fixture, promote it to `conftest.py` in this task rather than duplicating it. Replace `create_offer_for_test()` with that helper's real name.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_closure_dates.py -v`
Expected: every test FAILS with `AttributeError: 'Deal' object has no attribute 'chiuso_il'`.

- [ ] **Step 3: Add the columns**

```python
# packages/core/src/pigrocrm/core/deals/models.py -- one column, after `custom_fields`,
# and one index appended to __table_args__.
    # `Date`, not `timestamptz`, against slice 1 §5's general convention and for slice 3
    # §6.2's precise reason: a date that decides which period a figure falls in is not an
    # instant. Written by `DealService.move_stage` when the destination stage has
    # `tipo != 'open'`, and cleared when the deal returns to an open stage.
    #
    # Deliberately NOT backfilled (spec §4.1): `move_stage` records the stage *names* in
    # its activity payload, and a name is renamable (residuo R15), so deducing a
    # historical closure date from the timeline would mean matching a mutable string. The
    # period dashboards exclude `chiuso_il IS NULL` and say how many rows they excluded,
    # rather than counting them as zero or attributing them to the wrong month.
    chiuso_il: Mapped[date | None] = mapped_column(Date, default=None)

# __table_args__ gains:
        Index("ix_deals_chiuso_il", "chiuso_il"),
```

```python
# packages/core/src/pigrocrm/core/documents/models.py -- one column and one index.
    # The day the current `stato` was set. Written by `DocumentService.set_offer_state`,
    # the only writer of `documents.stato`. `Date` for the same reason as
    # `deals.chiuso_il`. Backfilled in migration 0008 -- unlike `chiuso_il` -- because the
    # offer timeline's payload is `{"da": "inviata", "a": "accettata"}`, literals of
    # `OfferState` rather than user-editable text.
    stato_dal: Mapped[date | None] = mapped_column(Date, default=None)

# __table_args__ gains:
        Index("ix_documents_stato_dal", "stato_dal"),
```

Both files need `date` on their `from datetime import ...` line and `Date` on their `from sqlalchemy import ...` line — `deals/models.py` already has both.

Add `chiuso_il: date | None` to `DealRead` and `stato_dal: date | None` to `DocumentRead`. Neither goes on a Create or an Update schema: both are derived, written only by a dedicated method, and putting either on `DealUpdate` would let a caller claim a closure that never happened.

- [ ] **Step 4: Write the closure into `move_stage`**

```python
# packages/core/src/pigrocrm/core/deals/service.py -- replace `move_stage` only.
# Imports gain: from pigrocrm.core.db import today_local

    def move_stage(self, deal_id: UUID, stage_id: UUID, actor: Actor) -> DealRead:
        """The only supported way to change a deal's stage -- see `DealUpdate`'s own
        docstring for why it is not also a plain field on `update`. `_settle_probability`
        -- also used by `create` and `update` -- is what actually keeps "won at 60%"
        unreachable through *any* of the three; this method no longer settles the
        probability by itself.

        Since slice 6 it also maintains `chiuso_il`, and the three cases are not
        symmetric: entering a terminal stage from an open one stamps today, returning to
        an open stage clears it, and moving between two terminal stages leaves it alone --
        that is a correction of *which* outcome, not a new closure, and restamping would
        move the deal into the month somebody fixed the mistake in.
        """
        actor.require_write("move_deal")
        deal = self.repo.get(deal_id)
        if deal is None:
            raise NotFound(ENTITY, deal_id)

        target = self.pipeline.get(stage_id)
        previous = self.pipeline.get(deal.pipeline_stage_id)

        deal.pipeline_stage_id = target.id
        deal.probabilita = _settle_probability(target, deal.probabilita)
        _settle_closure_date(deal, previous, target)

        self.activities.record(
            ENTITY, deal.id, "stage_changed", actor, {"from": previous.nome, "to": target.nome}
        )
        self.session.commit()
        return DealRead.model_validate(deal)
```

And this module-level function, placed immediately after `_settle_probability` so the two authorities on "what a stage change means" sit together:

```python
def _settle_closure_date(
    deal: Deal, previous: PipelineStageRead, target: PipelineStageRead
) -> None:
    """The single authority on `deals.chiuso_il`, at module level for the same reason
    `_settle_probability` is: `AutomationRunner` reaches it through
    `set_stage_in_transaction` (slice 6 §9.3), and an invariant reachable through two
    paths must live in one function or it holds on one of them.

    `today_local()` and never `date.today()`: at 00:30 on 1 April in Rome it is still
    31 March in UTC, and a deal won just after midnight would land in the previous
    month's conversion rate.
    """
    if target.tipo == "open":
        # Reopened. A reopened deal is not a deal closed in March, and leaving the stamp
        # would put it in the conversion rate and in the open pipeline at once.
        deal.chiuso_il = None
        return
    if previous.tipo != "open":
        # won -> lost or lost -> won: a correction, not a closure.
        return
    deal.chiuso_il = today_local()
```

`PipelineStageRead` and `Deal` are already imported in that module.

- [ ] **Step 5: Write the stamp into `set_offer_state`**

```python
# packages/core/src/pigrocrm/core/documents/service.py -- inside `set_offer_state`,
# replace the single mutation line with two. Imports gain:
#   from pigrocrm.core.db import today_local

        previous, document.stato = document.stato, stato
        # The day this state began. Task B5 inserts the automation runner between this
        # line and `activities.record` below -- the order in §9.3 is not cosmetic.
        document.stato_dal = today_local()
```

- [ ] **Step 6: Write migration 0008 (the two columns and the backfill)**

```python
# packages/core/migrations/versions/0008_automations_and_dates.py
"""deals.chiuso_il, documents.stato_dal with its backfill, and automation_config

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-21

Three objects in one revision because they are meaningless apart: the automation cannot
run without its config row and cannot record a closure without the column. The
`automation_config` section is written by Task B3; this file applies cleanly with or
without it.

**The backfill is asymmetric, and the asymmetry is the whole argument of spec §4.1.**

`documents.stato_dal` is backfilled from `activities`: the offer timeline's payload is
`{"da": "inviata", "a": "accettata"}` -- literals of `OfferState`, not text a user can
edit -- so `occurred_at` of the most recent `state_changed` for a document is a reliable
answer. Projected to a date in the emitter's zone, not in UTC, for the reason
`db/clock.py` exists.

`deals.chiuso_il` is **not** backfilled. `DealService.move_stage` records
`{"from": <nome>, "to": <nome>}` -- the stage *names*, which a user is free to rename
(residuo R15) -- so deducing a historical closure would mean matching a mutable string,
which is precisely what `pipeline_stages.code` and `tipo` exist to avoid. Rows closed
before this migration keep `chiuso_il IS NULL`, the period dashboards exclude them and
declare how many they excluded. A guessed conversion rate is the worst kind of figure:
plausible and wrong.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must equal `Settings.timezone`'s default. Hardcoded here rather than read from settings
# because a migration must be reproducible: re-running it on a differently configured
# deployment has to produce the same rows it produced the first time.
_BACKFILL_TZ = "Europe/Rome"


def upgrade() -> None:
    op.add_column("deals", sa.Column("chiuso_il", sa.Date(), nullable=True))
    op.create_index("ix_deals_chiuso_il", "deals", ["chiuso_il"])

    op.add_column("documents", sa.Column("stato_dal", sa.Date(), nullable=True))
    op.create_index("ix_documents_stato_dal", "documents", ["stato_dal"])

    # One statement, not a loop: `DISTINCT ON` gives the latest `state_changed` per
    # document directly, and a Python loop over a million-row activities table inside a
    # migration is how a deploy times out.
    op.execute(
        sa.text(
            """
            UPDATE documents AS d
               SET stato_dal = latest.giorno
              FROM (
                    SELECT DISTINCT ON (a.entity_id)
                           a.entity_id,
                           (a.occurred_at AT TIME ZONE :tz)::date AS giorno
                      FROM activities AS a
                     WHERE a.entity_type = 'document'
                       AND a.kind = 'state_changed'
                     ORDER BY a.entity_id, a.occurred_at DESC, a.id DESC
                   ) AS latest
             WHERE d.id = latest.entity_id
               AND d.stato IS NOT NULL
            """
        ).bindparams(tz=_BACKFILL_TZ)
    )

    # `deals.chiuso_il` is deliberately NOT backfilled. See the module docstring.

    # -- automation_config: written by Task B3, in this same revision. --


def downgrade() -> None:
    op.drop_index("ix_documents_stato_dal", table_name="documents")
    op.drop_column("documents", "stato_dal")
    op.drop_index("ix_deals_chiuso_il", table_name="deals")
    op.drop_column("deals", "chiuso_il")
```

`d.stato IS NOT NULL` is the guard that keeps the backfill to offers: `documents.stato` is `NULL` on every non-offer document, and stamping a `stato_dal` on a row with no state would make "this offer has been sitting for N days" answer for a contract.

- [ ] **Step 7: Update `test_migrations.py`**

Add `"ix_deals_chiuso_il"` and `"ix_documents_stato_dal"` to `HAND_MAINTAINED_INDEXES`, move the two head assertions from `"0007"` to `"0008"`, and append:

```python
def test_stato_dal_is_backfilled_from_the_timeline_and_chiuso_il_is_not() -> None:
    """The asymmetry of spec §4.1, asserted rather than described.

    A migration that quietly backfilled `chiuso_il` from the `stage_changed` payload would
    pass every other test in this file and would silently attribute deals to months
    derived from a renamable string.
    """
    source = (
        CORE_ROOT / "migrations" / "versions" / "0008_automations_and_dates.py"
    ).read_text(encoding="utf-8")
    assert "UPDATE documents" in source
    assert "state_changed" in source
    assert "UPDATE deals" not in source, (
        "deals.chiuso_il must not be backfilled: move_stage records stage *names*, which "
        "are renamable (residuo R15). See spec §4.1."
    )
    assert "stage_changed" not in source
```

- [ ] **Step 8: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_closure_dates.py packages/core/tests/test_migrations.py packages/core/tests/test_deals.py packages/core/tests/test_documents_service.py -v`
Expected: PASS.

- [ ] **Step 9: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add packages/core/src/pigrocrm/core/deals/ \
        packages/core/src/pigrocrm/core/documents/ \
        packages/core/migrations/versions/0008_automations_and_dates.py \
        packages/core/tests/test_migrations.py \
        packages/core/tests/test_closure_dates.py
git commit -m "feat(core): deals.chiuso_il and documents.stato_dal, backfilling only one"
```

---
### Task B3: `automation_config`, and R5 closed for it

**Files:**
- Create: `packages/core/src/pigrocrm/core/automations/__init__.py`
- Create: `packages/core/src/pigrocrm/core/automations/models.py`
- Create: `packages/core/src/pigrocrm/core/automations/schemas.py`
- Create: `packages/core/src/pigrocrm/core/automations/repository.py`
- Create: `packages/core/src/pigrocrm/core/automations/config_service.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Modify: `packages/core/migrations/versions/0008_automations_and_dates.py` (the section Task B2 left marked)
- Modify: `packages/core/src/pigrocrm/core/activities/repository.py` (`by_kind`)
- Create: `packages/core/tests/test_automation_config.py`

**Interfaces:**
- Consumes: `Actor.require_admin`; `ActivityService.record`; `Base`, `PrimaryKeyMixin`, `TimestampMixin`.
- Produces:
  - `AutomationConfig` — table `automation_config`, columns `id`, `created_at`, `updated_at`, `a1_offerta_accettata_vince_deal: bool` (default `True`), `a2_offerta_inviata_avanza_deal: bool` (default `True`)
  - `AUTOMATION_KINDS: tuple[str, ...] = ("automazione.stage_spostato", "automazione.non_eseguita", "automazione.configurazione_modificata")`
  - `AutomationRule = Literal["A1", "A2"]`, `AutomationSkipReason = Literal["stage_bersaglio_assente", "stage_bersaglio_ambiguo", "gia_nello_stato", "regola_disattivata"]`
  - `AutomationConfigRead(BaseModel)` — the two booleans
  - `AutomationConfigUpdate(BaseModel)` — the two booleans, both optional, `extra="forbid"`
  - `AutomationRun(BaseModel)` — `kind: str`, `occurred_at: datetime`, `deal_id: UUID | None`, `regola: str | None`, `motivo: str | None`, `payload: dict[str, Any]`
  - `AutomationsDescription(BaseModel)` — `configurazione: AutomationConfigRead`, `regole: list[AutomationRuleDescription]`, `esecuzioni: list[AutomationRun]`
  - `AutomationRuleDescription(BaseModel)` — `codice: AutomationRule`, `titolo: str`, `descrizione: str`, `attiva: bool`
  - `AutomationConfigRepository(session)` with `get() -> AutomationConfig | None`, `add(row) -> AutomationConfig`
  - `AutomationConfigService(session)` with exactly two public methods: `describe_automations(actor) -> AutomationsDescription` and `update_automation_config(data, actor) -> AutomationConfigRead`
  - `ActivityRepository.by_kind(kinds: Sequence[str], limit: int) -> list[Activity]`
- Task B5 reads the config through `AutomationConfigService`'s repository; Task B12 exposes `describe_automations` as a tool and **not** `update_automation_config`.

**Two public methods, and the split is what the architecture test needs.** Spec §11.1: `describe_automations` is on both surfaces, `update_automation_config` is on the API only, and the slice-6 exclusion list must be **exactly** `update_automation_config`. A single `get`/`upsert` pair would put two names on that list. `get` is therefore *not* public — `describe_automations` returns the configuration as part of its payload, which is what both surfaces actually need.

**Column widths, following slice 3's precedent.** These are booleans so there is no width to get wrong, but the `motivo` and `regola` values that Task B5 writes go into a JSONB payload rather than into a sized column — deliberately, because `activities.payload` is JSONB and a `String(24)` sized to `stage_bersaglio_ambiguo` would be a column sized exactly to its closed set, which is the defect slice 3 just fixed on `invoices.tipo`.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_automation_config.py
"""Two booleans, and every change to them audited.

Spec §9.6: `automation_config` is a single row like `emitter_profile` and
`fiscal_profile`, admin-only, and every modification writes an activity -- residuo **R5**
closed for this table, with slice 3 §7.1's argument: changing what the system will do by
itself to future data is of a different order of seriousness from renaming a stage.

No flow builder, no configurable conditions, no second effect per rule (§15). Two booleans
are the configuration surface, and that is a property to defend rather than a starting
point to grow from.
"""

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.automations.config_service import AutomationConfigService
from pigrocrm.core.automations.schemas import AutomationConfigUpdate
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.errors import PermissionDenied

ADMIN = Actor(id=uuid7(), type="user", role="admin")
COLLABORATORE = Actor(id=uuid7(), type="user", role="collaboratore")
READONLY = Actor(id=uuid7(), type="user", role="readonly")


def test_both_rules_are_on_by_default(db_session: Session) -> None:
    """Default `true`, and it is a decision: an automation nobody switched on is an
    automation nobody knows exists."""
    described = AutomationConfigService(db_session).describe_automations(ADMIN)
    assert described.configurazione.a1_offerta_accettata_vince_deal is True
    assert described.configurazione.a2_offerta_inviata_avanza_deal is True


def test_the_row_is_created_on_first_read_and_not_duplicated(db_session: Session) -> None:
    """Single-row table, like `emitter_profile`. Reading it twice must not leave two."""
    from sqlalchemy import func, select

    from pigrocrm.core.automations.models import AutomationConfig

    service = AutomationConfigService(db_session)
    service.describe_automations(ADMIN)
    service.describe_automations(ADMIN)
    assert db_session.scalar(select(func.count()).select_from(AutomationConfig)) == 1


def test_describe_lists_both_rules_with_their_state(db_session: Session) -> None:
    described = AutomationConfigService(db_session).describe_automations(ADMIN)
    assert [rule.codice for rule in described.regole] == ["A1", "A2"]
    assert all(rule.attiva for rule in described.regole)
    # The description is what an agent reads to know what the system does by itself.
    assert "vinto" in described.regole[0].descrizione.lower()


def test_an_admin_can_switch_a_rule_off(db_session: Session) -> None:
    service = AutomationConfigService(db_session)
    updated = service.update_automation_config(
        AutomationConfigUpdate(a1_offerta_accettata_vince_deal=False), ADMIN
    )
    assert updated.a1_offerta_accettata_vince_deal is False
    assert updated.a2_offerta_inviata_avanza_deal is True


def test_an_omitted_field_changes_nothing(db_session: Session) -> None:
    """`exclude_unset`, not `exclude_none`: with two booleans, `None` and "not sent" have
    to be distinguishable or switching A1 off would silently switch A2 on."""
    service = AutomationConfigService(db_session)
    service.update_automation_config(
        AutomationConfigUpdate(a1_offerta_accettata_vince_deal=False), ADMIN
    )
    after = service.update_automation_config(
        AutomationConfigUpdate(a2_offerta_inviata_avanza_deal=False), ADMIN
    )
    assert after.a1_offerta_accettata_vince_deal is False
    assert after.a2_offerta_inviata_avanza_deal is False


def test_false_is_a_value_and_not_a_blank(db_session: Session) -> None:
    """The backend mirror of the frontend rule. A truthiness check here would make
    "switch it off" impossible to express."""
    service = AutomationConfigService(db_session)
    service.update_automation_config(
        AutomationConfigUpdate(a1_offerta_accettata_vince_deal=False), ADMIN
    )
    described = service.describe_automations(ADMIN)
    assert described.configurazione.a1_offerta_accettata_vince_deal is False


@pytest.mark.parametrize("actor", [COLLABORATORE, READONLY])
def test_only_an_admin_may_change_it(db_session: Session, actor: Actor) -> None:
    with pytest.raises(PermissionDenied):
        AutomationConfigService(db_session).update_automation_config(
            AutomationConfigUpdate(a1_offerta_accettata_vince_deal=False), actor
        )


def test_every_change_writes_an_activity(db_session: Session) -> None:
    """Residuo R5, closed for this table."""
    from pigrocrm.core.activities.repository import ActivityRepository

    AutomationConfigService(db_session).update_automation_config(
        AutomationConfigUpdate(a1_offerta_accettata_vince_deal=False), ADMIN
    )
    rows = ActivityRepository(db_session).by_kind(
        ["automazione.configurazione_modificata"], limit=10
    )
    assert len(rows) == 1
    assert rows[0].actor_id == ADMIN.id
    assert rows[0].payload["a1_offerta_accettata_vince_deal"] == {"da": True, "a": False}
    # The unchanged rule is absent, not recorded as unchanged: an audit entry listing
    # every field on every edit is an audit entry nobody reads.
    assert "a2_offerta_inviata_avanza_deal" not in rows[0].payload


def test_a_no_op_update_writes_no_activity(db_session: Session) -> None:
    """Saving a form without touching anything is not a change to audit."""
    from pigrocrm.core.activities.repository import ActivityRepository

    service = AutomationConfigService(db_session)
    service.update_automation_config(
        AutomationConfigUpdate(a1_offerta_accettata_vince_deal=True), ADMIN
    )
    assert (
        ActivityRepository(db_session).by_kind(
            ["automazione.configurazione_modificata"], limit=10
        )
        == []
    )


def test_describe_returns_the_recent_runs(db_session: Session) -> None:
    """§9.5's third surface: the last executions with their outcome, read from
    `activities` by `kind` -- not a new table (§9.4)."""
    AutomationConfigService(db_session).update_automation_config(
        AutomationConfigUpdate(a2_offerta_inviata_avanza_deal=False), ADMIN
    )
    described = AutomationConfigService(db_session).describe_automations(ADMIN)
    assert [run.kind for run in described.esecuzioni] == [
        "automazione.configurazione_modificata"
    ]


def test_by_kind_orders_newest_first_and_respects_the_limit(db_session: Session) -> None:
    from pigrocrm.core.activities.repository import ActivityRepository
    from pigrocrm.core.activities.service import ActivityService

    service = ActivityService(db_session)
    for index in range(5):
        service.record("deal", uuid7(), "automazione.stage_spostato", ADMIN, {"n": index})
    db_session.flush()

    rows = ActivityRepository(db_session).by_kind(["automazione.stage_spostato"], limit=3)
    assert len(rows) == 3
    assert [row.payload["n"] for row in rows] == [4, 3, 2]


def test_by_kind_with_an_empty_kind_list_returns_nothing(db_session: Session) -> None:
    """`IN ()` is a syntax error in some dialects and matches everything if written
    carelessly. An empty filter must mean "nothing", never "all"."""
    from pigrocrm.core.activities.repository import ActivityRepository

    assert ActivityRepository(db_session).by_kind([], limit=10) == []


def test_the_config_service_exposes_exactly_two_public_methods() -> None:
    """Task B12's exclusion list must be exactly `update_automation_config`, so every
    other public method needs a tool. Two methods, one tool, one exclusion."""
    import inspect

    from pigrocrm.core.automations.config_service import AutomationConfigService

    public = {
        name
        for name, member in inspect.getmembers(
            AutomationConfigService, predicate=inspect.isfunction
        )
        if not name.startswith("_")
        and member.__qualname__.startswith("AutomationConfigService.")
    }
    assert public == {"describe_automations", "update_automation_config"}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_automation_config.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'pigrocrm.core.automations'`.

- [ ] **Step 3: Write the model**

```python
# packages/core/src/pigrocrm/core/automations/models.py
"""The whole configuration surface of this slice's automations: two booleans.

A single row, like `emitter_profile` (slice 2) and `fiscal_profile` (slice 3), and read
through `AutomationConfigRepository.get()` which creates it on first use. No `singleton`
CHECK constraint: the repository is the only writer and it never inserts a second row, and
a constraint pinning a magic primary key would be a second mechanism for the same
invariant.

No flow builder, no configurable conditions, no second effect per rule (spec §15). A flow
builder brings a condition evaluator, an execution order, a failure semantics and a way to
stop a loop: four mechanisms for a product that has two rules.
"""

from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class AutomationConfig(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "automation_config"

    # A1 -- offerta accettata -> deal vinto. Default on: an automation nobody switched on
    # is an automation nobody knows exists.
    a1_offerta_accettata_vince_deal: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    # A2 -- offerta inviata -> il deal avanza allo stage `code='offerta'`, only if its
    # current `posizione` is lower. Never backwards: see `AutomationRunner`.
    a2_offerta_inviata_avanza_deal: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
```

`server_default="true"` as well as `default=True`: the Python default covers rows this code inserts, the server default covers the row the migration inserts, and without the second the migration's `INSERT` would need to name both columns.

- [ ] **Step 4: Write the schemas**

```python
# packages/core/src/pigrocrm/core/automations/schemas.py
"""What the automations expose, and the four reasons one may decline to run.

The `motivo` values are a closed `Literal` in Python and a JSONB value in the database --
not a sized `String` column. A `String(24)` sized exactly to `stage_bersaglio_ambiguo`
would be a column sized precisely to its legal set, which is the defect slice 3 just fixed
on `invoices.tipo`: the width rejects a wrong value before the CHECK beside it can, and
Postgres answers with a raw truncation error instead of the named violation.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# New `kind` values. No migration: `activities.kind` is an open value by project
# (slice 1 §5.8) and `ActivityService.record` takes `kind: str` and truncates to the
# column width without consulting any Literal.
KIND_STAGE_MOVED = "automazione.stage_spostato"
KIND_NOT_EXECUTED = "automazione.non_eseguita"
KIND_CONFIG_CHANGED = "automazione.configurazione_modificata"
AUTOMATION_KINDS: tuple[str, ...] = (
    KIND_STAGE_MOVED,
    KIND_NOT_EXECUTED,
    KIND_CONFIG_CHANGED,
)

AutomationRule = Literal["A1", "A2"]

# The four declared conditions the runner absorbs. Anything not in this list propagates
# and rolls the trigger back (§9.3): a database that cannot write is not an automation
# that did not fire.
AutomationSkipReason = Literal[
    "stage_bersaglio_assente",
    "stage_bersaglio_ambiguo",
    "gia_nello_stato",
    "regola_disattivata",
]


class AutomationConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    a1_offerta_accettata_vince_deal: bool
    a2_offerta_inviata_avanza_deal: bool


class AutomationConfigUpdate(BaseModel):
    """Both optional, and read with `exclude_unset=True`.

    With two booleans, `None` and "not sent" must be distinguishable: `exclude_none` would
    make "switch A1 off without mentioning A2" indistinguishable from "switch A1 off and
    A2 on". This is residuo A14's shape, avoided rather than inherited -- there is no
    nullable typed column here, so no spelling of "clear it" is needed at all.
    """

    model_config = ConfigDict(extra="forbid")

    a1_offerta_accettata_vince_deal: bool | None = None
    a2_offerta_inviata_avanza_deal: bool | None = None


class AutomationRuleDescription(BaseModel):
    codice: AutomationRule
    titolo: str
    descrizione: str
    attiva: bool


class AutomationRun(BaseModel):
    kind: str
    occurred_at: datetime
    deal_id: UUID | None
    regola: str | None
    motivo: str | None
    payload: dict[str, Any]


class AutomationsDescription(BaseModel):
    configurazione: AutomationConfigRead
    regole: list[AutomationRuleDescription]
    esecuzioni: list[AutomationRun]


# The prose an agent and a human both read. Here rather than in the service so the two
# surfaces cannot drift, and in Italian like every other user-facing string.
RULE_DESCRIPTIONS: dict[AutomationRule, tuple[str, str]] = {
    "A1": (
        "Offerta accettata → deal vinto",
        "Quando un'offerta passa da «inviata» ad «accettata», il deal collegato viene "
        "spostato nello stato con code «vinto», o nell'unico stato di tipo «won». Se lo "
        "stato manca o ce ne sono due, l'automazione non indovina: non fa nulla e "
        "registra il motivo.",
    ),
    "A2": (
        "Offerta inviata → il deal avanza",
        "Quando un'offerta passa da «bozza» a «inviata», il deal collegato avanza allo "
        "stato con code «offerta», ma solo se la sua posizione attuale è precedente. Non "
        "torna mai indietro: un deal già in negoziazione non retrocede perché è stata "
        "mandata una seconda offerta.",
    ),
}
```

- [ ] **Step 5: Write the repository and `by_kind`**

```python
# packages/core/src/pigrocrm/core/automations/repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.automations.models import AutomationConfig


class AutomationConfigRepository:
    """Single row, created on first read.

    Created here rather than by the migration alone so that a database restored from
    before this slice, or a test using `Base.metadata.create_all`, behaves identically to
    a freshly migrated one. `flush`, never `commit`: the service owns the transaction.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self) -> AutomationConfig:
        row = self.session.scalar(select(AutomationConfig).limit(1))
        if row is None:
            row = AutomationConfig()
            self.session.add(row)
            self.session.flush()
        return row
```

```python
# packages/core/src/pigrocrm/core/activities/repository.py -- append one method.
# `list` is not defined on this class, so there is no last-method constraint to respect
# here; check before appending and move this above `list` if one has appeared.

    def by_kind(self, kinds: Sequence[str], limit: int = 20) -> list[Activity]:
        """Activities of the given kinds, newest first, across every entity.

        Spec §9.5 and §11.1: the automation run log is a read of `activities` by `kind`,
        not a new table (§9.4). A dedicated execution log would be a table whose only
        function is answering a question `activities` answers better -- the same reasoning
        that made slice 3 refuse to historicise `fiscal_profile`.

        An empty `kinds` returns nothing. `IN ()` is not portable and a carelessly written
        empty filter matches everything, which here would dump the whole timeline into a
        settings page.
        """
        if not kinds:
            return []
        return list(
            self.session.execute(
                select(Activity)
                .where(Activity.kind.in_(list(kinds)))
                .order_by(Activity.occurred_at.desc(), Activity.id.desc())
                .limit(limit)
            ).scalars()
        )
```

Add `from collections.abc import Sequence` to that file's imports.

- [ ] **Step 6: Write the service**

```python
# packages/core/src/pigrocrm/core/automations/config_service.py
"""Read and change what the system does by itself.

Two public methods, and the split is what the architecture test needs: spec §11.1 puts
`describe_automations` on both surfaces and `update_automation_config` on the API only,
and requires the slice-6 exclusion list to be **exactly** one name. A `get`/`upsert` pair
would put two names on that list, so `get` is not public -- `describe_automations` returns
the configuration inside its payload, which is what both surfaces actually need.
"""

from typing import Any

from sqlalchemy.orm import Session

from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.automations.repository import AutomationConfigRepository
from pigrocrm.core.automations.schemas import (
    AUTOMATION_KINDS,
    KIND_CONFIG_CHANGED,
    RULE_DESCRIPTIONS,
    AutomationConfigRead,
    AutomationConfigUpdate,
    AutomationRule,
    AutomationRuleDescription,
    AutomationRun,
    AutomationsDescription,
)

ENTITY = "automation_config"
_RUN_LIMIT = 20


class AutomationConfigService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = AutomationConfigRepository(session)
        self.activities = ActivityService(session)
        self.activity_repo = ActivityRepository(session)

    def describe_automations(self, actor: Actor) -> AutomationsDescription:
        """The two rules, their state, and the last twenty executions with their outcome.

        No authorisation check: it is a read of what the system does by itself, every role
        may see it, and spec §13 states this slice adds no authorisation rule. `actor` is
        still taken because every service method in this project takes it.

        This method writes -- `get_or_create` may insert the single row -- so it commits.
        A read method that commits is unusual enough to say out loud: the alternative is
        that the first `GET` of a fresh installation leaves an uncommitted row and the
        second one inserts a duplicate.
        """
        row = self.repo.get_or_create()
        config = AutomationConfigRead.model_validate(row)
        rules = [
            AutomationRuleDescription(
                codice=code,
                titolo=RULE_DESCRIPTIONS[code][0],
                descrizione=RULE_DESCRIPTIONS[code][1],
                attiva=self._is_active(config, code),
            )
            for code in ("A1", "A2")
        ]
        runs = [
            AutomationRun(
                kind=activity.kind,
                occurred_at=activity.occurred_at,
                deal_id=activity.entity_id if activity.entity_type == "deal" else None,
                regola=activity.payload.get("regola"),
                motivo=activity.payload.get("motivo"),
                payload=activity.payload,
            )
            for activity in self.activity_repo.by_kind(AUTOMATION_KINDS, _RUN_LIMIT)
        ]
        self.session.commit()
        return AutomationsDescription(
            configurazione=config, regole=rules, esecuzioni=runs
        )

    @staticmethod
    def _is_active(config: AutomationConfigRead, code: AutomationRule) -> bool:
        if code == "A1":
            return config.a1_offerta_accettata_vince_deal
        return config.a2_offerta_inviata_avanza_deal

    def update_automation_config(
        self, data: AutomationConfigUpdate, actor: Actor
    ) -> AutomationConfigRead:
        """Admin only, audited, and absent from the MCP surface.

        Admin because it changes what the system will do to *future* data without a human
        in the loop -- slice 4 §11's reason 2, and the reason it has no MCP tool. The audit
        entry is residuo **R5** closed for this table, with slice 3 §7.1's argument:
        changing what the system does by itself is of a different order of seriousness from
        renaming a stage.

        `exclude_unset=True`, not `exclude_none`: with two booleans, "not sent" and `None`
        have to be distinguishable, or switching A1 off would silently switch A2 on.
        """
        actor.require_admin("update_automation_config")
        row = self.repo.get_or_create()

        changes: dict[str, Any] = {}
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is None:
                continue
            current = getattr(row, field)
            # `is not` on booleans, and only a real difference is recorded: an audit entry
            # that lists every field on every save is an audit entry nobody reads.
            if current is not value:
                changes[field] = {"da": current, "a": value}
                setattr(row, field, value)

        if changes:
            # Last thing that touches the session before the commit, as
            # `ActivityService.record`'s docstring requires.
            self.activities.record(ENTITY, row.id, KIND_CONFIG_CHANGED, actor, changes)
        self.session.commit()
        return AutomationConfigRead.model_validate(row)
```

```python
# packages/core/src/pigrocrm/core/automations/__init__.py
from pigrocrm.core.automations.config_service import AutomationConfigService
from pigrocrm.core.automations.models import AutomationConfig
from pigrocrm.core.automations.schemas import (
    AUTOMATION_KINDS,
    KIND_CONFIG_CHANGED,
    KIND_NOT_EXECUTED,
    KIND_STAGE_MOVED,
    AutomationConfigRead,
    AutomationConfigUpdate,
    AutomationRule,
    AutomationRuleDescription,
    AutomationRun,
    AutomationsDescription,
    AutomationSkipReason,
)

__all__ = [
    "AUTOMATION_KINDS",
    "KIND_CONFIG_CHANGED",
    "KIND_NOT_EXECUTED",
    "KIND_STAGE_MOVED",
    "AutomationConfig",
    "AutomationConfigRead",
    "AutomationConfigService",
    "AutomationConfigUpdate",
    "AutomationRule",
    "AutomationRuleDescription",
    "AutomationRun",
    "AutomationSkipReason",
    "AutomationsDescription",
]
```

`AutomationRunner` joins this `__all__` in Task B5.

- [ ] **Step 7: Register the model and finish the migration**

```python
# packages/core/src/pigrocrm/core/models_registry.py -- one import, alphabetically placed.
from pigrocrm.core.automations.models import AutomationConfig  # noqa: F401
```

```python
# packages/core/migrations/versions/0008_automations_and_dates.py
# Replace the marked section in `upgrade()`:
    op.create_table(
        "automation_config",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "a1_offerta_accettata_vince_deal", sa.Boolean(),
            server_default=sa.text("true"), nullable=False,
        ),
        sa.Column(
            "a2_offerta_inviata_avanza_deal", sa.Boolean(),
            server_default=sa.text("true"), nullable=False,
        ),
    )
    # The single row, seeded here so a migrated installation has it before the first
    # request. `AutomationConfigRepository.get_or_create` covers the other path -- a
    # database built by `Base.metadata.create_all`, which is how the test suite builds
    # one. Both paths must work: slice 3 lost a sequence to exactly this gap.
    op.execute(
        sa.text("INSERT INTO automation_config (id) VALUES (gen_random_uuid())")
    )

# And in `downgrade()`, before the column drops:
    op.drop_table("automation_config")
```

`gen_random_uuid()` rather than a UUIDv7: it is one row, its id is never sorted on, and `pgcrypto` is not needed — `gen_random_uuid()` is built into PostgreSQL 13 and later.

- [ ] **Step 8: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_automation_config.py packages/core/tests/test_migrations.py packages/core/tests/test_activities.py -v`
Expected: PASS.

Add `"automation_config"` to `test_every_table_the_slice_needs_exists`'s expected set in `test_migrations.py` if that test enumerates tables per slice; it does, as of slice 1.

- [ ] **Step 9: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add packages/core/src/pigrocrm/core/automations/ \
        packages/core/src/pigrocrm/core/activities/repository.py \
        packages/core/src/pigrocrm/core/models_registry.py \
        packages/core/migrations/versions/0008_automations_and_dates.py \
        packages/core/tests/test_automation_config.py \
        packages/core/tests/test_migrations.py
git commit -m "feat(automations): automation_config with two booleans, audited, closing R5"
```

---

### Task B4: `set_stage_in_transaction`, and the mechanical check on who may call it

**Files:**
- Modify: `packages/core/src/pigrocrm/core/deals/service.py`
- Modify: `packages/core/tests/test_architecture.py`
- Create: `packages/core/tests/test_in_transaction_callers.py`
- Create: `packages/core/tests/test_set_stage_in_transaction.py`

**Interfaces:**
- Consumes: `_settle_probability`, `_settle_closure_date` (Task B2); `PipelineStageRead`; `Deal`.
- Produces:
  - `DealService.set_stage_in_transaction(self, deal: Deal, stage: PipelineStageRead) -> None` — mutates, does not record, does not commit, does not authorise.
  - In `packages/core/tests/test_architecture.py`: `IN_TRANSACTION_SUFFIX = "_in_transaction"`, `IN_TRANSACTION_CALLER_PREFIX = "automations"`, and `test_in_transaction_methods_are_called_only_from_core_automations`.
- Task B5 is the only caller.

**The one new convention this slice introduces, and it is introduced with its enforcement in the same commit.** Spec §9.3:

> Un servizio può esporre un metodo `*_in_transaction(...)` che muta, non registra, non committa e non controlla l'autorizzazione. Il test di architettura verifica che tali metodi siano chiamati **solo** da `core/automations/`.

The runner cannot call `DealService.move_stage`, because that method commits and records — it would commit the offer's state change before the trigger was finished, and it would write a second timeline entry for one movement. So the mutation is separated out. Separating it creates a method that skips authorisation, which is exactly the kind of thing that gets called from a router eighteen months later by someone who read its name and not its docstring. Hence the test.

- [ ] **Step 1: Write the failing tests**

```python
# packages/core/tests/test_set_stage_in_transaction.py
"""The mutation half of a stage change, without the transaction or the timeline.

Four things it deliberately does **not** do, each of which is a test below: authorise,
record, commit, or reach the database on its own. It is called by `AutomationRunner`
inside `set_offer_state`'s transaction, where the authorisation has already happened
(`actor.require_write`) and the commit belongs to the trigger.

`_settle_probability` is reused rather than reimplemented, which is the only reason that
function is at module level: the invariant "won at 60% is unreachable" has to hold on this
path too, and an invariant reachable through two paths must live in one function.
"""

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import today_local
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")


@pytest.fixture
def stages(db_session: Session) -> dict:
    PipelineService(db_session).seed_defaults(ADMIN)
    return {s.code: s for s in PipelineService(db_session).list() if s.code is not None}


@pytest.fixture
def deal(db_session: Session, stages: dict) -> Deal:
    customer = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(customer)
    db_session.flush()
    row = Deal(
        nome="Impianto", customer_id=customer.id,
        pipeline_stage_id=stages["lead"].id, probabilita=50, custom_fields={},
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_it_moves_the_deal_and_settles_the_probability(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    DealService(db_session).set_stage_in_transaction(deal, stages["vinto"])
    assert deal.pipeline_stage_id == stages["vinto"].id
    # "Won at 60%" stays unreachable through this path too.
    assert deal.probabilita == 100


def test_it_settles_the_closure_date(db_session: Session, deal: Deal, stages: dict) -> None:
    DealService(db_session).set_stage_in_transaction(deal, stages["vinto"])
    assert deal.chiuso_il == today_local()


def test_it_records_nothing(db_session: Session, deal: Deal, stages: dict) -> None:
    """The runner writes its own single entry (§9.5). Two entries for one movement is the
    defect §9.3 names explicitly."""
    from pigrocrm.core.activities.repository import ActivityRepository

    DealService(db_session).set_stage_in_transaction(deal, stages["vinto"])
    db_session.flush()
    assert ActivityRepository(db_session).by_kind(["stage_changed"], limit=10) == []


def test_it_does_not_commit(db_session: Session, deal: Deal, stages: dict) -> None:
    """The property the whole design rests on: rolling back must undo it."""
    DealService(db_session).set_stage_in_transaction(deal, stages["vinto"])
    db_session.rollback()
    reloaded = db_session.get(Deal, deal.id)
    # The row itself vanished with the rollback of the fixture's own insert, which is
    # itself proof that nothing was committed.
    assert reloaded is None or reloaded.pipeline_stage_id == stages["lead"].id


def test_it_does_not_check_authorisation(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """Not an oversight -- the point. The authorisation is the trigger's
    (`set_offer_state` calls `actor.require_write`), and a `readonly` actor never reaches
    the runner. Re-authorising here would be harmless; *elevating* here would make
    accepting an offer a way to write to a deal the actor could not otherwise touch, and
    the architecture test in `test_in_transaction_callers.py` is what keeps this method
    out of a router."""
    # No actor parameter exists to pass; the signature is the assertion.
    import inspect

    signature = inspect.signature(DealService.set_stage_in_transaction)
    assert "actor" not in signature.parameters
    assert list(signature.parameters) == ["self", "deal", "stage"]


def test_moving_back_to_an_open_stage_clears_the_closure_date(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    service = DealService(db_session)
    service.set_stage_in_transaction(deal, stages["vinto"])
    service.set_stage_in_transaction(deal, stages["negoziazione"])
    assert deal.chiuso_il is None
```

```python
# packages/core/tests/test_in_transaction_callers.py
"""The one new convention of slice 6, enforced.

Spec §9.3: a service may expose a `*_in_transaction(...)` method that mutates, does not
record, does not commit and does not check authorisation -- and such methods must be
called **only** from `core/automations/`.

Without this test the convention is a comment. `set_stage_in_transaction` skips
`actor.require_write`, so a router calling it eighteen months from now -- because its name
reads like a helper -- would be an authorisation bypass with no error anywhere. The check
is on the *call site*, in the AST, across `packages/core`, `apps/api` and `apps/mcp`.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCHED_ROOTS = (
    REPO_ROOT / "packages" / "core" / "src" / "pigrocrm" / "core",
    REPO_ROOT / "apps" / "api" / "src" / "pigrocrm_api",
    REPO_ROOT / "apps" / "mcp" / "src" / "pigrocrm_mcp",
)
SUFFIX = "_in_transaction"
# The one directory allowed to call them, as a path fragment rather than a module name so
# a future `core/automations/rules/foo.py` is covered without an edit here.
ALLOWED_FRAGMENT = "core/automations/"


def _calls_with_suffix(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr.endswith(SUFFIX):
            found.append(f"{func.attr} (line {node.lineno})")
    return found


def _definitions_with_suffix(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.endswith(SUFFIX)
    ]


def test_in_transaction_methods_are_called_only_from_core_automations() -> None:
    offenders: list[str] = []
    for root in SEARCHED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            as_posix = path.as_posix()
            if ALLOWED_FRAGMENT in as_posix:
                continue
            calls = _calls_with_suffix(path)
            if calls:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {calls}")
    assert not offenders, (
        "a `*_in_transaction` method mutates without checking authorisation, without "
        "recording and without committing; it may only be called from core/automations/ "
        f"(spec §9.3). Offending call sites:\n" + "\n".join(offenders)
    )


def test_at_least_one_such_method_exists_so_the_guard_is_not_vacuous() -> None:
    """A guard over an empty set passes forever and proves nothing."""
    defined: list[str] = []
    for path in sorted(SEARCHED_ROOTS[0].rglob("*.py")):
        defined.extend(_definitions_with_suffix(path))
    assert "set_stage_in_transaction" in defined, defined


def test_the_guard_catches_a_call_from_outside(tmp_path: Path) -> None:
    """The guard proven to catch what it claims to, in the same style as the
    import-direction tests in test_architecture.py."""
    offending = tmp_path / "router.py"
    offending.write_text(
        "def endpoint(session, deal, stage):\n"
        "    DealService(session).set_stage_in_transaction(deal, stage)\n",
        encoding="utf-8",
    )
    assert _calls_with_suffix(offending), "the AST walk failed to see an obvious call"


def test_the_runner_is_where_the_call_actually_is() -> None:
    """Positive control: the allowed directory really does contain the call, so the test
    above is not passing merely because nothing calls it anywhere."""
    runner = SEARCHED_ROOTS[0] / "automations" / "runner.py"
    assert runner.exists(), "core/automations/runner.py is missing (Task B5)"
    assert _calls_with_suffix(runner), "the runner does not call set_stage_in_transaction"
```

`test_the_runner_is_where_the_call_actually_is` fails until Task B5 lands. That is intentional and is called out in Step 3.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/core/tests/test_set_stage_in_transaction.py packages/core/tests/test_in_transaction_callers.py -v`
Expected: the first file FAILS with `AttributeError: 'DealService' object has no attribute 'set_stage_in_transaction'`; in the second, `test_at_least_one_such_method_exists_so_the_guard_is_not_vacuous` and `test_the_runner_is_where_the_call_actually_is` FAIL.

- [ ] **Step 3: Add the method**

```python
# packages/core/src/pigrocrm/core/deals/service.py -- insert immediately after
# `move_stage`, so the two ways a stage changes sit together. NOT after `list`, which must
# stay the last method in the class.

    def set_stage_in_transaction(self, deal: Deal, stage: PipelineStageRead) -> None:
        """Move a deal to a stage, and nothing else. Slice 6 §9.3's convention.

        Mutates. Does **not** record an activity, does **not** commit, and does **not**
        check authorisation. Callable only from `core/automations/`, and
        `packages/core/tests/test_in_transaction_callers.py` enforces that on the AST of
        every call site in the repository.

        Why it exists at all: `AutomationRunner` runs inside its trigger's transaction
        (`DocumentService.set_offer_state`), and `move_stage` commits and records. Calling
        `move_stage` from the runner would commit the offer's state change before the
        trigger had finished -- destroying the atomicity that is the whole answer to "what
        happens if an automation fails halfway" -- and would write a second timeline entry
        for a single movement.

        Why it does not authorise: the trigger already did (`set_offer_state` calls
        `actor.require_write`), so a `readonly` actor never reaches the runner. Adding a
        check here would be harmless; *elevating* here would turn accepting an offer into a
        way to write to a deal the actor could not otherwise touch. It takes no `actor`
        parameter at all, so there is nothing to elevate with.

        `_settle_probability` and `_settle_closure_date` are reused rather than
        reimplemented, and that is the only reason both are module-level functions: "won at
        60%" and "closed in the wrong month" must stay unreachable through this path too,
        and an invariant reachable through two paths has to live in one place.
        """
        deal.pipeline_stage_id = stage.id
        deal.probabilita = _settle_probability(stage, deal.probabilita)
        _settle_closure_date(deal, self.pipeline.get(deal.pipeline_stage_id), stage)
```

That last line has a bug worth reading twice: by the time it runs, `deal.pipeline_stage_id` is already the *target*, so `self.pipeline.get(...)` would return the target as the "previous" stage and `_settle_closure_date` would take the "correction between two terminal stages" branch. Read the previous stage **first**:

```python
        previous = self.pipeline.get(deal.pipeline_stage_id)
        deal.pipeline_stage_id = stage.id
        deal.probabilita = _settle_probability(stage, deal.probabilita)
        _settle_closure_date(deal, previous, stage)
```

Use this second form. `test_it_settles_the_closure_date` is what catches the first one.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_set_stage_in_transaction.py -v`
Expected: PASS, six tests.

Run: `uv run pytest packages/core/tests/test_in_transaction_callers.py -v`
Expected: three PASS, `test_the_runner_is_where_the_call_actually_is` still FAILS with "core/automations/runner.py is missing (Task B5)". That failure is the handoff to the next task; leave it red and note it in the commit message.

- [ ] **Step 5: Cross-reference from the architecture test**

```python
# packages/core/tests/test_architecture.py -- append, so the whole architectural rule set
# is discoverable from one file even though the AST walk lives in its own module.
def test_the_in_transaction_convention_has_its_own_guard() -> None:
    """Slice 6 §9.3's rule is enforced in `test_in_transaction_callers.py`, which walks
    the AST of every call site in three packages. Named here because this file is where
    somebody looks for the project's architectural rules, and a rule enforced in a file
    nobody opens is a rule that gets deleted in a refactor."""
    guard = CORE_ROOT / "tests" / "test_in_transaction_callers.py"
    assert guard.exists(), "the *_in_transaction caller guard is missing"
    assert "core/automations/" in guard.read_text(encoding="utf-8")
```

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/deals/service.py \
        packages/core/tests/test_set_stage_in_transaction.py \
        packages/core/tests/test_in_transaction_callers.py \
        packages/core/tests/test_architecture.py
git commit -m "feat(deals): set_stage_in_transaction, with an AST guard on its callers"
```

The suite is intentionally one test red at this point (`test_the_runner_is_where_the_call_actually_is`). Task B5 closes it, and the two tasks are adjacent for that reason.

---
### Task B5: `AutomationRunner` — A1, A2, and the four declared reasons for not running

**Files:**
- Create: `packages/core/src/pigrocrm/core/automations/runner.py`
- Modify: `packages/core/src/pigrocrm/core/automations/__init__.py`
- Modify: `packages/core/src/pigrocrm/core/pipeline/repository.py` (`get_by_tipo`)
- Create: `packages/core/tests/test_automation_runner.py`

**Interfaces:**
- Consumes: `DealService.set_stage_in_transaction(deal, stage)` (Task B4); `AutomationConfigRepository.get_or_create()` (Task B3); `ActivityService.record`; `PipelineRepository.get_by_code`; `DealRepository.get`.
- Produces:
  - `AutomationRunner(session: Session)` with one public method:
    `on_offer_state_changed(self, document: Document, previous: str, actor: Actor) -> None`
  - `PipelineRepository.get_by_tipo(tipo: str) -> list[PipelineStage]` — a **list**, because "there are two `won` stages" is an answer the runner must be able to see (R14).
  - `AutomationOutcome` — frozen dataclass, `rule: AutomationRule | None`, `moved: bool`, `reason: AutomationSkipReason | None`. Returned by the private `_apply_*` methods; not part of the public surface.
- Task B6 calls `on_offer_state_changed` from `DocumentService.set_offer_state`.

**No `actor.require_*` anywhere in this file.** The trigger already authorised (`set_offer_state` calls `actor.require_write`), so a `readonly` actor never reaches here. The runner neither re-authorises nor elevates: if it could elevate, accepting an offer would become a way to write to a deal the actor could not otherwise touch.

**The exception policy, which is where this kind of code usually lies.** The runner absorbs a **declared list** of four domain conditions — target stage absent, target stage ambiguous, deal already in the target state, rule switched off — records each, and lets the trigger continue. Every other exception **propagates and rolls everything back**. A database that cannot write is not an automation that did not fire, and it is the one case where the user should not see their offer accepted.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_automation_runner.py
"""**Criteria 8 and 9.** The two rules, and the four reasons one may decline.

Everything here runs inside the caller's transaction: the runner never commits, so every
test flushes and reads back rather than committing. That is not a testing convenience, it
is the property under test -- §9.3's answer to "what happens if an automation fails
halfway" is that there is no halfway.

`§9.5`'s fourth surface is the one that usually goes missing, so it gets the most tests:
without an activity for the *non*-execution, "it did not fire" and "it was not supposed to
fire" are the same empty screen.
"""

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.actor import Actor
from pigrocrm.core.automations.runner import AutomationRunner
from pigrocrm.core.automations.schemas import KIND_NOT_EXECUTED, KIND_STAGE_MOVED
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=uuid7(), type="user", role="admin")
SEED = Actor(id=None, type="system", role="admin")


@pytest.fixture
def stages(db_session: Session) -> dict:
    PipelineService(db_session).seed_defaults(SEED)
    return {s.code: s for s in PipelineService(db_session).list() if s.code is not None}


@pytest.fixture
def deal(db_session: Session, stages: dict) -> Deal:
    customer = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(customer)
    db_session.flush()
    row = Deal(
        nome="Impianto", customer_id=customer.id,
        pipeline_stage_id=stages["lead"].id, probabilita=10, custom_fields={},
    )
    db_session.add(row)
    db_session.flush()
    return row


def _offer(db_session: Session, deal: Deal, stato: str) -> Document:
    document = Document(
        deal_id=deal.id, tipo="offerta", titolo="Offerta impianti",
        stato=stato, versione_corrente=1, custom_fields={},
    )
    db_session.add(document)
    db_session.flush()
    return document


def _kinds(db_session: Session, kind: str) -> list:
    return ActivityRepository(db_session).by_kind([kind], limit=20)


# -- A1 --------------------------------------------------------------------------

def test_a1_moves_the_deal_to_won(db_session: Session, deal: Deal, stages: dict) -> None:
    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()
    assert deal.pipeline_stage_id == stages["vinto"].id
    assert deal.probabilita == 100


def test_a1_writes_exactly_one_activity_attributed_to_the_system(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """§16 criterion 8. One entry, `actor_type='system'`, and `attivata_da` naming the
    human -- the timeline says "the system did it" *and* "because you accepted that
    offer". `Actor.system()` carries `id=None`, which is why the trigger's actor lives in
    the payload."""
    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()

    moved = _kinds(db_session, KIND_STAGE_MOVED)
    assert len(moved) == 1
    entry = moved[0]
    assert entry.entity_type == "deal"
    assert entry.entity_id == deal.id
    assert entry.actor_type == "system"
    assert entry.actor_id is None
    assert entry.payload["regola"] == "A1"
    assert entry.payload["documento_id"] == str(document.id)
    assert entry.payload["attivata_da"] == str(ADMIN.id)
    assert entry.payload["da"] == "Lead"
    assert entry.payload["a"] == "Vinto"


def test_a1_does_not_write_a_second_stage_changed_entry(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """§9.3: one entry for the movement, not two. Calling `move_stage` from the runner
    would produce a parallel `stage_changed` and the timeline would show one movement
    twice."""
    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()
    assert _kinds(db_session, "stage_changed") == []


def test_a1_ignores_a_transition_that_is_not_inviata_to_accettata(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """`rifiutata` moves nothing: an offer refused is almost always followed by a revision,
    and marking the deal lost would force reopening it to tell the truth (§9.2)."""
    document = _offer(db_session, deal, "rifiutata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()
    assert deal.pipeline_stage_id == stages["lead"].id
    assert _kinds(db_session, KIND_STAGE_MOVED) == []
    # Nor is it a *skipped* automation: nothing was supposed to happen.
    assert _kinds(db_session, KIND_NOT_EXECUTED) == []


def test_a1_on_an_offer_without_a_deal_does_nothing(db_session: Session) -> None:
    customer = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(customer)
    db_session.flush()
    document = Document(
        customer_id=customer.id, tipo="offerta", titolo="Offerta",
        stato="accettata", versione_corrente=1, custom_fields={},
    )
    db_session.add(document)
    db_session.flush()

    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()
    assert _kinds(db_session, KIND_STAGE_MOVED) == []


def test_a1_resolves_by_code_and_not_by_name(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """The stage renamed, the automation unaffected. This is what `code` is for
    (slice 1 §5.4, residuo R11)."""
    won = db_session.get(PipelineStage, stages["vinto"].id)
    assert won is not None
    won.nome = "Chiuso positivo"
    db_session.flush()

    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()
    assert deal.pipeline_stage_id == won.id


def test_a1_falls_back_to_the_single_won_stage_when_the_code_is_gone(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    won = db_session.get(PipelineStage, stages["vinto"].id)
    assert won is not None
    won.code = None
    db_session.flush()

    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()
    assert deal.pipeline_stage_id == won.id


def test_a1_refuses_to_guess_between_two_won_stages(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """Residuo **R14**: nothing forbids two `tipo='won'` stages, and no migration in this
    slice adds a constraint -- it would refuse data an installation may have created for a
    reason. So the automation does not guess; it declines and says why."""
    won = db_session.get(PipelineStage, stages["vinto"].id)
    assert won is not None
    won.code = None
    db_session.add(
        PipelineStage(nome="Vinto bis", posizione=6, probabilita_default=100, tipo="won")
    )
    db_session.flush()

    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()

    assert deal.pipeline_stage_id == stages["lead"].id
    skipped = _kinds(db_session, KIND_NOT_EXECUTED)
    assert len(skipped) == 1
    assert skipped[0].payload["motivo"] == "stage_bersaglio_ambiguo"
    assert skipped[0].payload["regola"] == "A1"


def test_a1_declines_when_there_is_no_won_stage_at_all(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """§16 criterion 7's second half: accepting the offer **succeeds**, and the
    non-execution is recorded."""
    won = db_session.get(PipelineStage, stages["vinto"].id)
    assert won is not None
    db_session.delete(won)
    db_session.flush()

    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()

    skipped = _kinds(db_session, KIND_NOT_EXECUTED)
    assert skipped[0].payload["motivo"] == "stage_bersaglio_assente"


def test_a1_on_a_deal_already_won_is_a_recorded_no_op(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """§16 criterion 8: idempotence is *inherited*, not added (§9.4). The effect is a
    state, not an increment, so a second accepted offer produces one move and one recorded
    no-op -- and no execution-log table is needed to know that."""
    deal.pipeline_stage_id = stages["vinto"].id
    db_session.flush()

    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()

    assert _kinds(db_session, KIND_STAGE_MOVED) == []
    skipped = _kinds(db_session, KIND_NOT_EXECUTED)
    assert skipped[0].payload["motivo"] == "gia_nello_stato"


def test_a1_declines_when_the_rule_is_switched_off(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """§16 criterion 9. Disabled means disabled, and it says so rather than staying
    silent -- otherwise "off" and "broken" look identical."""
    from pigrocrm.core.automations.config_service import AutomationConfigService
    from pigrocrm.core.automations.schemas import AutomationConfigUpdate

    AutomationConfigService(db_session).update_automation_config(
        AutomationConfigUpdate(a1_offerta_accettata_vince_deal=False), ADMIN
    )

    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()

    assert deal.pipeline_stage_id == stages["lead"].id
    skipped = _kinds(db_session, KIND_NOT_EXECUTED)
    assert skipped[0].payload["motivo"] == "regola_disattivata"


# -- A2 --------------------------------------------------------------------------

def test_a2_advances_the_deal_to_the_offer_stage(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    document = _offer(db_session, deal, "inviata")
    AutomationRunner(db_session).on_offer_state_changed(document, "bozza", ADMIN)
    db_session.flush()
    assert deal.pipeline_stage_id == stages["offerta"].id


def test_a2_never_moves_a_deal_backwards(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """§9.2: a deal already in Negoziazione must not retreat because a second offer was
    sent. An automation that moves things backwards gets switched off on day one."""
    deal.pipeline_stage_id = stages["negoziazione"].id
    db_session.flush()

    document = _offer(db_session, deal, "inviata")
    AutomationRunner(db_session).on_offer_state_changed(document, "bozza", ADMIN)
    db_session.flush()

    assert deal.pipeline_stage_id == stages["negoziazione"].id
    skipped = _kinds(db_session, KIND_NOT_EXECUTED)
    assert skipped[0].payload["motivo"] == "gia_nello_stato"


def test_a2_has_no_tipo_fallback(db_session: Session, deal: Deal, stages: dict) -> None:
    """§9.2, the asymmetry that is easy to miss: "Offerta" is `open` like every other open
    stage, so there is nothing for a `tipo` fallback to select. Two rules with the same
    shape and two different resolutions -- confusing them would move a deal into some
    arbitrary open stage."""
    offer_stage = db_session.get(PipelineStage, stages["offerta"].id)
    assert offer_stage is not None
    offer_stage.code = None
    db_session.flush()

    document = _offer(db_session, deal, "inviata")
    AutomationRunner(db_session).on_offer_state_changed(document, "bozza", ADMIN)
    db_session.flush()

    assert deal.pipeline_stage_id == stages["lead"].id
    skipped = _kinds(db_session, KIND_NOT_EXECUTED)
    assert skipped[0].payload["motivo"] == "stage_bersaglio_assente"


def test_a2_is_not_triggered_by_a_reopened_offer(
    db_session: Session, deal: Deal, stages: dict
) -> None:
    """`inviata -> bozza` is a legal transition (`OFFER_TRANSITIONS`), and it is not a
    send."""
    document = _offer(db_session, deal, "bozza")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.flush()
    assert deal.pipeline_stage_id == stages["lead"].id
    assert _kinds(db_session, KIND_STAGE_MOVED) == []


def test_a2_respects_its_own_switch(db_session: Session, deal: Deal, stages: dict) -> None:
    from pigrocrm.core.automations.config_service import AutomationConfigService
    from pigrocrm.core.automations.schemas import AutomationConfigUpdate

    AutomationConfigService(db_session).update_automation_config(
        AutomationConfigUpdate(a2_offerta_inviata_avanza_deal=False), ADMIN
    )
    document = _offer(db_session, deal, "inviata")
    AutomationRunner(db_session).on_offer_state_changed(document, "bozza", ADMIN)
    db_session.flush()

    assert deal.pipeline_stage_id == stages["lead"].id
    assert _kinds(db_session, KIND_NOT_EXECUTED)[0].payload["motivo"] == "regola_disattivata"


# -- the exception policy --------------------------------------------------------

def test_the_runner_never_commits(db_session: Session, deal: Deal, stages: dict) -> None:
    """The property everything else rests on. If the runner committed, the offer's own
    state change would be persisted before the trigger finished -- and §9.3's "there is no
    halfway" would be false."""
    document = _offer(db_session, deal, "accettata")
    AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)
    db_session.rollback()
    assert db_session.get(Deal, deal.id) is None


def test_an_undeclared_exception_propagates(
    db_session: Session, deal: Deal, stages: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The distinction that keeps this code from lying. The runner absorbs four *declared*
    domain conditions. Anything else -- a database that cannot write -- propagates and
    rolls the trigger back, because that is not "an automation that did not fire"."""
    from pigrocrm.core.deals.service import DealService

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(DealService, "set_stage_in_transaction", explode)
    document = _offer(db_session, deal, "accettata")

    with pytest.raises(RuntimeError, match="disk on fire"):
        AutomationRunner(db_session).on_offer_state_changed(document, "inviata", ADMIN)


def test_the_runner_exposes_exactly_one_public_method() -> None:
    import inspect

    public = {
        name
        for name, member in inspect.getmembers(AutomationRunner, predicate=inspect.isfunction)
        if not name.startswith("_")
        and member.__qualname__.startswith("AutomationRunner.")
    }
    assert public == {"on_offer_state_changed"}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_automation_runner.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'pigrocrm.core.automations.runner'`.

- [ ] **Step 3: Add `get_by_tipo` to the pipeline repository**

```python
# packages/core/src/pigrocrm/core/pipeline/repository.py -- append. `list` is the last
# method in that class; insert this ABOVE it.

    def get_by_tipo(self, tipo: str) -> list[PipelineStage]:
        """Every stage of a kind, ordered by `posizione`.

        Returns a **list** and not an `Optional`, deliberately: residuo **R14** records
        that nothing forbids two `tipo='won'` stages, and "there are two" is an answer the
        automation runner has to be able to see so it can decline instead of picking one.
        An `Optional` signature would force this method to choose, which is exactly the
        decision it must not make.
        """
        return list(
            self.session.execute(
                select(PipelineStage)
                .where(PipelineStage.tipo == tipo)
                .order_by(PipelineStage.posizione, PipelineStage.id)
            ).scalars()
        )
```

- [ ] **Step 4: Write the runner**

```python
# packages/core/src/pigrocrm/core/automations/runner.py
"""The two automations of spec §9, running inside their trigger's transaction.

**Never commits.** `DocumentService.set_offer_state` owns the transaction, and that is the
whole answer to "what happens if an automation fails halfway": there is no halfway. Either
the offer is accepted and the deal is moved, or neither is true.

**Never authorises.** `set_offer_state` already called `actor.require_write`, so a
`readonly` actor never gets here. The runner does not re-check and does not elevate: if it
could elevate, accepting an offer would become a way to write to a deal the actor could not
otherwise touch.

**Never guesses a stage.** By `code`, then by `tipo` where a `tipo` can identify one
(A1 only), then it declines and records why. Never by name -- a name is renamable, and
matching on one is precisely what `pipeline_stages.code` and `tipo` exist to prevent
(slice 1 §5.4, residuo R11).

**Absorbs a declared list and nothing else.** The four `AutomationSkipReason` values are
recorded and the trigger continues. Every other exception propagates and rolls everything
back: a database that cannot write is not an automation that did not fire, and it is the
one case where the user should not see their offer accepted.

No execution-log table (§9.4). Idempotence is inherited from three properties already in
the tree: the trigger is unrepeatable by construction (`OFFER_TRANSITIONS` gives
`"accettata": frozenset()`, so `inviata -> accettata` happens at most once per document);
the effect is a state rather than an increment, so a repeat is a recorded no-op; and
atomicity with the trigger means "fired but not recorded" does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.automations.repository import AutomationConfigRepository
from pigrocrm.core.automations.schemas import (
    KIND_NOT_EXECUTED,
    KIND_STAGE_MOVED,
    AutomationRule,
    AutomationSkipReason,
)
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.documents.models import Document
from pigrocrm.core.pipeline.repository import PipelineRepository
from pigrocrm.core.pipeline.schemas import PipelineStageRead

_DEAL_ENTITY = "deal"
# A1 fires on this transition and no other; A2 on this one. Declared as data rather than
# as `if` chains so that "which transitions are triggers" is answerable by reading two
# lines, the same shape `OFFER_TRANSITIONS` already uses.
_A1_TRANSITION = ("inviata", "accettata")
_A2_TRANSITION = ("bozza", "inviata")


@dataclass(frozen=True)
class AutomationOutcome:
    rule: AutomationRule | None
    moved: bool
    reason: AutomationSkipReason | None


class AutomationRunner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.config = AutomationConfigRepository(session)
        self.deals = DealRepository(session)
        self.deal_service = DealService(session)
        self.pipeline = PipelineRepository(session)
        self.activities = ActivityService(session)

    def on_offer_state_changed(
        self, document: Document, previous: str, actor: Actor
    ) -> None:
        """Called explicitly by `DocumentService.set_offer_state`, not by a hook.

        Explicitly because an implicit hook on a state change is a mechanism whose call
        sites cannot be found by reading the code, and because §9.3 fixes the order inside
        the trigger: mutate the document, then this, then the document's own activity,
        then commit. That order is not cosmetic -- `ActivityService.record`'s docstring
        requires it to be the last thing touching the session before the caller's commit.
        """
        current = document.stato
        if current is None or document.deal_id is None:
            # Not an offer, or an offer attached to a customer rather than a deal. Nothing
            # was supposed to happen, so nothing is recorded: a `non_eseguita` entry here
            # would fill the log with non-events.
            return

        transition = (previous, current)
        if transition == _A1_TRANSITION:
            outcome = self._apply_a1(document, actor)
        elif transition == _A2_TRANSITION:
            outcome = self._apply_a2(document, actor)
        else:
            return

        if outcome.reason is not None:
            self._record_skip(document, outcome, actor)

    # -- the two rules ---------------------------------------------------------

    def _apply_a1(self, document: Document, actor: Actor) -> AutomationOutcome:
        row = self.config.get_or_create()
        if not row.a1_offerta_accettata_vince_deal:
            return AutomationOutcome("A1", False, "regola_disattivata")

        target, reason = self._resolve_won_stage()
        if target is None:
            return AutomationOutcome("A1", False, reason)
        return self._move(document, target, "A1", actor)

    def _apply_a2(self, document: Document, actor: Actor) -> AutomationOutcome:
        row = self.config.get_or_create()
        if not row.a2_offerta_inviata_avanza_deal:
            return AutomationOutcome("A2", False, "regola_disattivata")

        # By `code` only. There is deliberately no `tipo` fallback: "Offerta" is `open`
        # like every other open stage, so a `tipo` lookup would select an arbitrary one.
        stage = self.pipeline.get_by_code("offerta")
        if stage is None:
            return AutomationOutcome("A2", False, "stage_bersaglio_assente")

        deal = self.deals.get(document.deal_id) if document.deal_id else None
        if deal is None:
            return AutomationOutcome("A2", False, "stage_bersaglio_assente")
        current = self.pipeline.get(deal.pipeline_stage_id)
        if current is None:
            return AutomationOutcome("A2", False, "stage_bersaglio_assente")

        # Never backwards, and never sideways. A deal already at or past "Offerta" stays
        # put: an automation that retreats a deal because a second offer went out gets
        # switched off on its first day (§9.2).
        if current.posizione >= stage.posizione:
            return AutomationOutcome("A2", False, "gia_nello_stato")

        return self._move(document, PipelineStageRead.model_validate(stage), "A2", actor)

    def _resolve_won_stage(
        self,
    ) -> tuple[PipelineStageRead | None, AutomationSkipReason | None]:
        """`code='vinto'`, then the single `tipo='won'`, then decline.

        The `tipo` fallback exists for A1 and not for A2 because `won` identifies exactly
        one intended stage while `open` identifies four. Residuo **R14**: two `won` stages
        are legal, so "there are two" has to be a visible answer -- hence
        `get_by_tipo` returning a list.
        """
        by_code = self.pipeline.get_by_code("vinto")
        if by_code is not None:
            return PipelineStageRead.model_validate(by_code), None

        candidates = self.pipeline.get_by_tipo("won")
        if not candidates:
            return None, "stage_bersaglio_assente"
        if len(candidates) > 1:
            return None, "stage_bersaglio_ambiguo"
        return PipelineStageRead.model_validate(candidates[0]), None

    # -- the movement and its two activities -----------------------------------

    def _move(
        self,
        document: Document,
        target: PipelineStageRead,
        rule: AutomationRule,
        actor: Actor,
    ) -> AutomationOutcome:
        deal = self.deals.get(document.deal_id) if document.deal_id else None
        if deal is None:
            return AutomationOutcome(rule, False, "stage_bersaglio_assente")
        if deal.pipeline_stage_id == target.id:
            return AutomationOutcome(rule, False, "gia_nello_stato")

        previous = self.pipeline.get(deal.pipeline_stage_id)
        previous_name = previous.nome if previous is not None else None

        # The one call in the whole repository to a `*_in_transaction` method, and
        # `packages/core/tests/test_in_transaction_callers.py` is what keeps it the only
        # one. It mutates and does not record, so the single timeline entry below is the
        # single timeline entry for this movement.
        self.deal_service.set_stage_in_transaction(deal, target)

        # `Actor.system()` carries `id=None`, so `actor_id` is NULL and the triggering
        # human lives in `attivata_da`: the timeline has to say both "the system did it"
        # and "because you accepted that offer" (§9.5).
        self.activities.record(
            _DEAL_ENTITY,
            deal.id,
            KIND_STAGE_MOVED,
            Actor.system(),
            {
                "regola": rule,
                "documento_id": str(document.id),
                "da": previous_name,
                "a": target.nome,
                "attivata_da": str(actor.id) if actor.id is not None else None,
            },
        )
        return AutomationOutcome(rule, True, None)

    def _record_skip(
        self, document: Document, outcome: AutomationOutcome, actor: Actor
    ) -> None:
        """§9.5's fourth surface, and the one that is usually missing.

        Without it, "it did not fire" and "it was not supposed to fire" are the same empty
        screen. The signal "offerta accettata, deal non vinto" on the commercial dashboard
        (§6.2) is this entry's permanent cross-check: if the automation goes quiet, the
        count speaks.
        """
        self.activities.record(
            _DEAL_ENTITY,
            document.deal_id,
            KIND_NOT_EXECUTED,
            Actor.system(),
            {
                "regola": outcome.rule,
                "motivo": outcome.reason,
                "documento_id": str(document.id),
                "attivata_da": str(actor.id) if actor.id is not None else None,
            },
        )
```

- [ ] **Step 5: Export it**

```python
# packages/core/src/pigrocrm/core/automations/__init__.py -- add to imports and __all__:
from pigrocrm.core.automations.runner import AutomationOutcome, AutomationRunner
# "AutomationOutcome", "AutomationRunner" in __all__, alphabetically sorted.
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_automation_runner.py packages/core/tests/test_in_transaction_callers.py -v`
Expected: PASS — including `test_the_runner_is_where_the_call_actually_is`, which Task B4 left red.

- [ ] **Step 7: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/automations/ \
        packages/core/src/pigrocrm/core/pipeline/repository.py \
        packages/core/tests/test_automation_runner.py
git commit -m "feat(automations): A1 and A2, resolving stages by code and declining to guess"
```

---

### Task B6: The runner inside the trigger's transaction — criterion 7

**Files:**
- Modify: `packages/core/src/pigrocrm/core/documents/service.py` (`set_offer_state`)
- Create: `packages/core/tests/test_automation_atomicity.py`
- Modify: `packages/core/tests/test_documents_service.py`

**Interfaces:**
- Consumes: `AutomationRunner.on_offer_state_changed(document, previous, actor)` (Task B5).
- Produces: no new signature. `DocumentService.set_offer_state(document_id, stato, actor) -> DocumentRead` is unchanged from the caller's point of view — which is the point: the automation is not a parameter, an option or a flag.

**The order inside the method is fixed by §9.3 and it is not cosmetic:**

1. mutate `documents.stato` and `documents.stato_dal`
2. **the runner** — which mutates the deal and records its own activity
3. `self.activities.record(...)` for the document
4. `commit`

`ActivityService.record`'s own docstring requires it to be "the last thing that touches the session before the caller's commit" and forbids following it with a call into another service that commits on its own behalf. The runner sits before it and never commits, so both halves of that contract hold.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_automation_atomicity.py
"""**Criterion 7.** The automation is atomic with its trigger.

With an error injected between the automation and the commit, neither thing happened: the
offer is still `inviata` and the deal is still in its old stage, verified by re-reading
both rows on a fresh session. This is the assertion that makes "there is no halfway" a
property rather than a claim, and it needs its own committed rows -- `db_session` holds an
outer transaction open, so a rollback inside it cannot be told apart from the fixture's
own cleanup.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.actor import Actor
from pigrocrm.core.automations.runner import AutomationRunner
from pigrocrm.core.automations.schemas import KIND_NOT_EXECUTED, KIND_STAGE_MOVED
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import session_factory
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.errors import PermissionDenied
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=uuid7(), type="user", role="admin")
READONLY = Actor(id=uuid7(), type="user", role="readonly")
SEED = Actor(id=None, type="system", role="admin")


@pytest.fixture
def committed(db_engine: Engine) -> Iterator[tuple[Session, Document, Deal, dict]]:
    """Real committed rows, on their own session, removed afterwards."""
    factory = session_factory(db_engine)
    session = factory()
    PipelineService(session).seed_defaults(SEED)
    stages = {s.code: s for s in PipelineService(session).list() if s.code is not None}

    customer = Customer(ragione_sociale="ATOMIC Cliente", nazione="IT", custom_fields={})
    session.add(customer)
    session.flush()
    deal = Deal(
        nome="ATOMIC Impianto", customer_id=customer.id,
        pipeline_stage_id=stages["lead"].id, probabilita=10, custom_fields={},
    )
    session.add(deal)
    session.flush()
    document = Document(
        deal_id=deal.id, tipo="offerta", titolo="ATOMIC Offerta",
        stato="inviata", versione_corrente=1, custom_fields={},
    )
    session.add(document)
    session.commit()
    try:
        yield session, document, deal, stages
    finally:
        session.rollback()
        session.execute(delete(Document).where(Document.titolo.like("ATOMIC %")))
        session.execute(delete(Deal).where(Deal.nome.like("ATOMIC %")))
        session.execute(
            delete(Customer).where(Customer.ragione_sociale.like("ATOMIC %"))
        )
        session.commit()
        session.close()


def test_accepting_an_offer_moves_the_deal_in_the_same_transaction(
    db_engine: Engine, committed: tuple
) -> None:
    session, document, deal, stages = committed
    DocumentService(session, storage=None).set_offer_state(document.id, "accettata", ADMIN)

    with session_factory(db_engine)() as other:
        reread_document = other.get(Document, document.id)
        reread_deal = other.get(Deal, deal.id)
        assert reread_document is not None and reread_deal is not None
        assert reread_document.stato == "accettata"
        assert reread_deal.pipeline_stage_id == stages["vinto"].id


def test_an_error_between_the_automation_and_the_commit_undoes_both(
    db_engine: Engine, committed: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assertion this file exists for. `ActivityService.record` is the last thing
    before the commit, so failing it is precisely "after the automation, before the
    commit"."""
    session, document, deal, stages = committed
    original = ActivityRepository.add

    calls = {"n": 0}

    def fail_on_the_documents_entry(self: ActivityRepository, activity: object) -> object:
        calls["n"] += 1
        # The runner's own entry is first; the document's `state_changed` is second.
        if calls["n"] == 2:
            raise RuntimeError("injected failure after the automation")
        return original(self, activity)

    monkeypatch.setattr(ActivityRepository, "add", fail_on_the_documents_entry)

    with pytest.raises(RuntimeError, match="injected failure"):
        DocumentService(session, storage=None).set_offer_state(
            document.id, "accettata", ADMIN
        )
    session.rollback()

    with session_factory(db_engine)() as other:
        reread_document = other.get(Document, document.id)
        reread_deal = other.get(Deal, deal.id)
        assert reread_document is not None and reread_deal is not None
        # Neither happened. There is no halfway.
        assert reread_document.stato == "inviata"
        assert reread_deal.pipeline_stage_id == stages["lead"].id
        assert reread_deal.chiuso_il is None


def test_with_the_won_stage_deleted_accepting_still_succeeds(
    db_engine: Engine, committed: tuple
) -> None:
    """§16 criterion 7's second half. A missing target stage is a *declared* condition:
    the offer is accepted, and the non-execution is on the record."""
    session, document, deal, stages = committed
    won = session.get(PipelineStage, stages["vinto"].id)
    assert won is not None
    session.delete(won)
    session.commit()

    DocumentService(session, storage=None).set_offer_state(document.id, "accettata", ADMIN)

    with session_factory(db_engine)() as other:
        reread = other.get(Document, document.id)
        assert reread is not None and reread.stato == "accettata"
        skipped = ActivityRepository(other).by_kind([KIND_NOT_EXECUTED], limit=5)
        assert skipped[0].payload["motivo"] == "stage_bersaglio_assente"


def test_a_readonly_actor_never_reaches_the_runner(
    db_engine: Engine, committed: tuple
) -> None:
    """§16 criterion 8's last sentence. The authorisation is the trigger's, and it is
    checked before anything is mutated -- so no row is touched at all."""
    session, document, deal, stages = committed

    with pytest.raises(PermissionDenied):
        DocumentService(session, storage=None).set_offer_state(
            document.id, "accettata", READONLY
        )
    session.rollback()

    with session_factory(db_engine)() as other:
        reread_document = other.get(Document, document.id)
        reread_deal = other.get(Deal, deal.id)
        assert reread_document is not None and reread_deal is not None
        assert reread_document.stato == "inviata"
        assert reread_deal.pipeline_stage_id == stages["lead"].id
        assert ActivityRepository(other).by_kind([KIND_STAGE_MOVED], limit=5) == []
        assert ActivityRepository(other).by_kind([KIND_NOT_EXECUTED], limit=5) == []
```

`DocumentService(session, storage=None)` matches whatever constructor the shipped class has; if it requires a real storage backend, use the fake the existing `test_documents_service.py` already builds rather than passing `None`.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_automation_atomicity.py -v`
Expected: `test_accepting_an_offer_moves_the_deal_in_the_same_transaction` FAILS — the deal is still in `lead`, because nothing calls the runner yet.

- [ ] **Step 3: Wire the runner into the trigger**

```python
# packages/core/src/pigrocrm/core/documents/service.py -- replace the tail of
# `set_offer_state` only. Imports gain:
#   from pigrocrm.core.automations.runner import AutomationRunner

        previous, document.stato = document.stato, stato
        document.stato_dal = today_local()

        # Slice 6 §9.3. The order of these three statements is fixed and is not cosmetic:
        #
        #   1. the mutation above,
        #   2. the runner -- which mutates the deal and records its own activity,
        #   3. this document's own activity,
        #   4. the commit.
        #
        # `ActivityService.record`'s docstring requires it to be the last thing that
        # touches the session before the caller's commit, and forbids following it with a
        # call into another service that commits on its own behalf. The runner sits before
        # it and never commits, so both halves hold.
        #
        # Called explicitly, not through a hook: an implicit hook on a state change is a
        # mechanism whose call sites cannot be found by reading the code.
        AutomationRunner(self.session).on_offer_state_changed(document, previous, actor)

        self.activities.record(
            ENTITY, document.id, "state_changed", actor, {"da": previous, "a": stato}
        )
        self.session.commit()
        return DocumentRead.model_validate(document)
```

**Check for an import cycle before running.** `documents/service.py` now imports `automations/runner.py`, which imports `deals/service.py`, which imports `pipeline` and `activities` — and none of those import `documents`. `documents/service.py` already imports `templates/service.py`. Confirm with:

Run: `uv run python -c "import pigrocrm.core.documents.service"`
Expected: no output. If it raises `ImportError: cannot import name ... (most likely due to a circular import)`, move the `AutomationRunner` import inside `set_offer_state` as a function-level import and say why in a comment — but measure first rather than pre-emptively deferring it, because a function-level import hides the dependency from `test_architecture.py`'s AST walk.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_automation_atomicity.py packages/core/tests/test_documents_service.py -v`
Expected: PASS.

Existing tests in `test_documents_service.py` that accept an offer on a document with a `deal_id` will now also move the deal. That is the feature, not a regression — but any test asserting "the deal did not change" must be updated to assert the new truth, and any test asserting an exact activity count for the document must account for the runner's entry. Both are found by running the file.

- [ ] **Step 5: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/documents/service.py \
        packages/core/tests/test_automation_atomicity.py \
        packages/core/tests/test_documents_service.py
git commit -m "feat(automations): run inside set_offer_state's transaction, atomically"
```

---
### Task B7: The commercial aggregates, and the only two exceptions to §3

**Files:**
- Modify: `packages/core/src/pigrocrm/core/deals/repository.py`
- Modify: `packages/core/src/pigrocrm/core/documents/repository.py`
- Create: `packages/core/src/pigrocrm/core/dashboard/__init__.py`
- Create: `packages/core/src/pigrocrm/core/dashboard/schemas.py`
- Create: `packages/core/tests/test_commercial_aggregates.py`

**Interfaces:**
- Consumes: `Deal`, `PipelineStage`, `Document`; `today_local` (Task B1).
- Produces:
  - In `deals/repository.py` — all four **above** the class's `list` method:
    - `pipeline_summary(self) -> list[PipelineStageSummary]`
    - `closed_in_period(self, da: date, a: date) -> ClosedInPeriod`
    - `expected_closures(self, da: date, a: date) -> int`
    - `unattributable_closures(self) -> int`
  - In `documents/repository.py` — both above `list`:
    - `pending_offers(self, limit: int = 20) -> list[PendingOffer]`
    - `count_accepted_with_unwon_deal(self) -> int`
  - In `dashboard/schemas.py`: `PipelineStageSummary`, `ClosedInPeriod`, `PendingOffer`, `Periodo`, and `CommercialDashboard` (Task B8 fills the last one in).
- Task B8 composes these; Task B10 compares each against its drill-through.

**§3's two named exceptions live here and nowhere else.** Both combine only columns of `deals`, and neither is money received:

- **the weighted pipeline value** — `Σ ROUND(valore_previsto × probabilita / 100, 2)`, `ROUND_HALF_UP`, summing already-rounded rows, labelled *stima* everywhere it appears and never added to revenue;
- **the conversion rate** — `vinti / (vinti + persi)`, two decimals, **`null` when the denominator is 0**.

Every other figure on the commercial dashboard is a plain `COUNT` or a plain `SUM` over one table. `DashboardService` (Task B8) contains no arithmetic at all, and Task B9 makes that a fact of the build.

**`null` and not `0` for the conversion rate.** Zero per cent means "I lost everything"; no closed deals means something else entirely. Same rule as slice 4 §7.1 for the margin percentage — and the same rule, so there is one rule.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_commercial_aggregates.py
"""§4's figures, each from its one stated source.

The two §3 exceptions are here and the tests say so out loud, because an exception that is
not written down is a rule that does not hold. Everything else in this file is a `COUNT` or
a `SUM` over a single table.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.pipeline.service import PipelineService

SEED = Actor(id=None, type="system", role="admin")


@pytest.fixture
def stages(db_session: Session) -> dict:
    PipelineService(db_session).seed_defaults(SEED)
    return {s.code: s for s in PipelineService(db_session).list() if s.code is not None}


@pytest.fixture
def customer(db_session: Session) -> Customer:
    row = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(row)
    db_session.flush()
    return row


def _deal(
    db_session: Session,
    customer: Customer,
    stage_id: object,
    *,
    valore: str | None = "1000.00",
    probabilita: int = 50,
    chiuso_il: date | None = None,
    data_chiusura_prevista: date | None = None,
) -> Deal:
    row = Deal(
        nome="Impianto", customer_id=customer.id, pipeline_stage_id=stage_id,
        valore_previsto=Decimal(valore) if valore is not None else None,
        probabilita=probabilita, chiuso_il=chiuso_il,
        data_chiusura_prevista=data_chiusura_prevista, custom_fields={},
    )
    db_session.add(row)
    db_session.flush()
    return row


# -- pipeline_summary ------------------------------------------------------------

def test_pipeline_summary_groups_open_deals_by_stage(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    _deal(db_session, customer, stages["lead"].id, valore="1000.00")
    _deal(db_session, customer, stages["lead"].id, valore="2000.00")
    _deal(db_session, customer, stages["offerta"].id, valore="500.00")

    rows = {row.stage_code: row for row in DealRepository(db_session).pipeline_summary()}
    assert rows["lead"].numero == 2
    assert rows["lead"].valore_totale == Decimal("3000.00")
    assert rows["offerta"].numero == 1


def test_pipeline_summary_excludes_closed_stages(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """`tipo='open'` only. A won deal is not pipeline; it is history."""
    _deal(db_session, customer, stages["vinto"].id)
    _deal(db_session, customer, stages["perso"].id)
    codes = {row.stage_code for row in DealRepository(db_session).pipeline_summary()}
    assert "vinto" not in codes and "perso" not in codes


def test_pipeline_summary_excludes_soft_deleted_deals(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    from datetime import UTC, datetime

    row = _deal(db_session, customer, stages["lead"].id)
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    summary = {r.stage_code: r for r in DealRepository(db_session).pipeline_summary()}
    assert summary.get("lead") is None or summary["lead"].numero == 0


def test_a_deal_without_a_value_is_counted_separately_and_never_summed_as_zero(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """§4's own note. Counting a missing value as zero understates the pipeline and there
    is no way for the reader to tell -- so it is a column of its own."""
    _deal(db_session, customer, stages["lead"].id, valore="1000.00")
    _deal(db_session, customer, stages["lead"].id, valore=None)

    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    assert row.numero == 2
    assert row.senza_valore == 1
    assert row.valore_totale == Decimal("1000.00")


def test_a_stage_with_no_deals_still_appears_with_zeroes(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """A missing stage and an empty stage render identically in a bar chart, and the
    reader cannot tell which they are looking at."""
    codes = {row.stage_code for row in DealRepository(db_session).pipeline_summary()}
    assert {"lead", "contattato", "offerta", "negoziazione"} <= codes


def test_stages_come_back_in_pipeline_order(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """A pipeline chart whose bars reorder between loads is unreadable."""
    positions = [row.posizione for row in DealRepository(db_session).pipeline_summary()]
    assert positions == sorted(positions)


# -- the first §3 exception: the weighted value ----------------------------------

def test_the_weighted_value_is_the_product_of_two_columns_of_deals(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """**§3 exception 1.** `Σ ROUND(valore_previsto × probabilita / 100, 2)`. Allowed
    because it combines only columns of `deals` and is not money received; labelled
    *stima* everywhere it appears."""
    _deal(db_session, customer, stages["lead"].id, valore="1000.00", probabilita=50)
    _deal(db_session, customer, stages["lead"].id, valore="333.33", probabilita=33)

    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    # 500.00 + ROUND(109.99890, 2) = 500.00 + 110.00
    assert row.valore_ponderato == Decimal("610.00")


def test_the_weighted_value_rounds_per_row_then_sums(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """`Σ ROUND(row, 2)`, never `ROUND(Σ exact, 2)`, and HALF_UP not HALF_EVEN -- the
    project-wide rule from slice 4. Three rows at 0.005 differ between the two by a cent,
    which is exactly how a reconciliation stops reconciling."""
    for _ in range(3):
        _deal(db_session, customer, stages["lead"].id, valore="0.01", probabilita=50)
    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    # ROUND(0.005, 2) = 0.01 half-up, three times.
    assert row.valore_ponderato == Decimal("0.03")


def test_a_deal_without_a_value_contributes_nothing_to_the_weighted_value(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    _deal(db_session, customer, stages["lead"].id, valore=None, probabilita=90)
    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    assert row.valore_ponderato == Decimal("0.00")


# -- closed_in_period and the second §3 exception --------------------------------

def test_closed_in_period_counts_won_and_lost_by_chiuso_il(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10),
          valore="1000.00")
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 20),
          valore="2000.00")
    _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 15))
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 4, 1))

    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 2
    assert result.persi == 1
    assert result.valore_vinto == Decimal("3000.00")


def test_the_period_bounds_are_inclusive(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 1))
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 31))
    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 2


def test_the_conversion_rate_is_a_ratio_of_two_counts(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """**§3 exception 2.** `vinti / (vinti + persi)`, two decimals."""
    for _ in range(3):
        _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10))
    _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 10))

    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.tasso_conversione == Decimal("75.00")


def test_the_conversion_rate_is_null_when_nothing_closed(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """`null`, not `0`. Zero per cent means "I lost everything"; no closed deals means
    something else. Same rule as slice 4 §7.1's margin percentage, and the *same* rule so
    there is one."""
    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 0 and result.persi == 0
    assert result.tasso_conversione is None


def test_the_conversion_rate_is_zero_when_everything_was_lost(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """The other half of the same distinction, which a `null`-only test would not catch."""
    _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 10))
    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.tasso_conversione == Decimal("0.00")


def test_deals_closed_before_the_column_existed_are_reported_not_counted(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """§4.1: `chiuso_il` is not backfilled, so historical closures are unattributable. The
    dashboard says how many rather than counting them as zero or putting them in the wrong
    month -- a guessed conversion rate is plausible and wrong, which is the worst
    combination."""
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=None)
    _deal(db_session, customer, stages["perso"].id, chiuso_il=None)
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10))

    repo = DealRepository(db_session)
    assert repo.closed_in_period(date(2026, 3, 1), date(2026, 3, 31)).vinti == 1
    assert repo.unattributable_closures() == 2


def test_expected_closures_counts_open_deals_in_the_window(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    _deal(db_session, customer, stages["lead"].id,
          data_chiusura_prevista=date(2026, 3, 15))
    _deal(db_session, customer, stages["lead"].id,
          data_chiusura_prevista=date(2026, 6, 1))
    # A won deal with a future expected date is not an expected closure.
    _deal(db_session, customer, stages["vinto"].id,
          data_chiusura_prevista=date(2026, 3, 20), chiuso_il=date(2026, 2, 1))

    assert DealRepository(db_session).expected_closures(
        date(2026, 3, 1), date(2026, 3, 31)
    ) == 1


# -- the documents side ----------------------------------------------------------

def test_pending_offers_carries_the_age_in_days(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    from pigrocrm.core.db import today_local

    db_session.add(
        Document(
            customer_id=customer.id, tipo="offerta", titolo="Offerta ferma",
            stato="inviata", stato_dal=date(2026, 3, 1), versione_corrente=1,
            custom_fields={},
        )
    )
    db_session.flush()

    rows = DocumentRepository(db_session).pending_offers()
    assert len(rows) == 1
    assert rows[0].titolo == "Offerta ferma"
    assert rows[0].giorni == (today_local() - date(2026, 3, 1)).days


def test_pending_offers_ignores_offers_in_any_other_state(
    db_session: Session, customer: Customer
) -> None:
    for stato in ("bozza", "accettata", "rifiutata"):
        db_session.add(
            Document(
                customer_id=customer.id, tipo="offerta", titolo=f"Offerta {stato}",
                stato=stato, stato_dal=date(2026, 3, 1), versione_corrente=1,
                custom_fields={},
            )
        )
    db_session.flush()
    assert DocumentRepository(db_session).pending_offers() == []


def test_an_offer_with_no_stato_dal_has_a_null_age_rather_than_zero(
    db_session: Session, customer: Customer
) -> None:
    """The backfill covers documents with a `state_changed` in their timeline; one written
    directly by a fixture or an import has none. Zero days would read as "sent today"."""
    db_session.add(
        Document(
            customer_id=customer.id, tipo="offerta", titolo="Senza data",
            stato="inviata", stato_dal=None, versione_corrente=1, custom_fields={},
        )
    )
    db_session.flush()
    rows = DocumentRepository(db_session).pending_offers()
    assert rows[0].giorni is None


def test_the_signal_counts_accepted_offers_whose_deal_is_not_won(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    """§6.2's first signal, and the permanent cross-check on automation A1: if the
    automation goes quiet, this count speaks. A `COUNT` across a join, which §3 permits --
    a `SUM` across one it does not."""
    open_deal = _deal(db_session, customer, stages["lead"].id)
    won_deal = _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 1))
    for deal, titolo in ((open_deal, "Da sistemare"), (won_deal, "A posto")):
        db_session.add(
            Document(
                deal_id=deal.id, tipo="offerta", titolo=titolo, stato="accettata",
                stato_dal=date(2026, 3, 1), versione_corrente=1, custom_fields={},
            )
        )
    db_session.flush()

    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 1


def test_the_signal_ignores_an_accepted_offer_with_no_deal(
    db_session: Session, customer: Customer
) -> None:
    """An offer attached to a customer has no deal to be won, so it is not an
    inconsistency."""
    db_session.add(
        Document(
            customer_id=customer.id, tipo="offerta", titolo="Senza deal",
            stato="accettata", stato_dal=date(2026, 3, 1), versione_corrente=1,
            custom_fields={},
        )
    )
    db_session.flush()
    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 0


def test_the_signal_ignores_a_soft_deleted_deal(
    db_session: Session, customer: Customer, stages: dict
) -> None:
    from datetime import UTC, datetime

    deal = _deal(db_session, customer, stages["lead"].id)
    deal.deleted_at = datetime.now(UTC)
    db_session.add(
        Document(
            deal_id=deal.id, tipo="offerta", titolo="Deal archiviato",
            stato="accettata", stato_dal=date(2026, 3, 1), versione_corrente=1,
            custom_fields={},
        )
    )
    db_session.flush()
    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_commercial_aggregates.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'pigrocrm.core.dashboard'`.

- [ ] **Step 3: Write the schemas**

```python
# packages/core/src/pigrocrm/core/dashboard/schemas.py
"""What a dashboard returns. Sub-plan 6C appends two more dashboards to this file.

Every money field is `Decimal` with `max_digits`/`decimal_places` matching the column it
came from, and every one arrives already summed. The frontend formats; it never adds
(§13, and Task B13's AST test).
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Periodo(BaseModel):
    """Normalised and echoed back, always. A screenshot of a dashboard with no explicit
    period is a number with no unit (§4)."""

    da: date
    a: date


class PipelineStageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage_id: str
    stage_code: str | None
    stage_nome: str
    posizione: int
    numero: int
    valore_totale: Decimal = Field(max_digits=12, decimal_places=2)
    # Counted, never summed as zero (§4). A missing expected value is not a value of zero,
    # and a reader has no way to tell the two apart from a total alone.
    senza_valore: int
    # §3 exception 1. Labelled "stima" in every rendering and never added to revenue.
    valore_ponderato: Decimal = Field(max_digits=12, decimal_places=2)


class ClosedInPeriod(BaseModel):
    vinti: int
    persi: int
    # `Σ valore_previsto` of the deals won in the period. **Not revenue** and not
    # comparable with it: it is what the deal *claimed*. The revenue of those same deals
    # is on the economic dashboard, and the two figures live on two pages for exactly this
    # reason (§4).
    valore_vinto: Decimal = Field(max_digits=12, decimal_places=2)
    # §3 exception 2. Per cent, two places. `None` -- never `0` -- when nothing closed:
    # zero per cent means "I lost everything", no closed deals means something else. Same
    # rule as slice 4 §7.1's margin percentage.
    tasso_conversione: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)


class PendingOffer(BaseModel):
    document_id: str
    titolo: str
    deal_id: str | None
    customer_id: str | None
    stato_dal: date | None
    # `None`, not 0, when `stato_dal` is unknown: zero days would read as "sent today".
    giorni: int | None


class CommercialDashboard(BaseModel):
    """One endpoint, one transaction, one instant (§7.1).

    `calcolato_alle` is the `transaction_timestamp()` of *that* transaction, and the
    browser shows its age. A number with no age is a number the user believes is
    instantaneous.
    """

    periodo: Periodo
    calcolato_alle: datetime
    pipeline: list[PipelineStageSummary]
    chiusure: ClosedInPeriod
    offerte_in_attesa: list[PendingOffer]
    offerte_in_attesa_totale: int
    chiusure_previste_30_giorni: int
    # §4.1: deals closed before `chiuso_il` existed cannot be attributed to a period. The
    # dashboard declares how many rather than counting them as zero.
    chiusure_non_attribuibili: int
    # §6.2's first signal, and the permanent cross-check on automation A1.
    offerte_accettate_deal_non_vinto: int
```

```python
# packages/core/src/pigrocrm/core/dashboard/__init__.py
from pigrocrm.core.dashboard.schemas import (
    ClosedInPeriod,
    CommercialDashboard,
    PendingOffer,
    Periodo,
    PipelineStageSummary,
)

__all__ = [
    "ClosedInPeriod",
    "CommercialDashboard",
    "PendingOffer",
    "Periodo",
    "PipelineStageSummary",
]
```

`DashboardService` joins this `__all__` in Task B8. **Note for Task B9:** this package must never import `Decimal`… except that `schemas.py` legitimately does, to type its fields. Task B9's AST clause therefore applies to `dashboard/service.py` and any future module in the package **other than `schemas.py`**, and that exemption is declared there with its reasoning — a schema declaring a `Decimal` field performs no arithmetic, and the clause exists to forbid arithmetic.

- [ ] **Step 4: Write the deal aggregates**

```python
# packages/core/src/pigrocrm/core/deals/repository.py -- four methods, all inserted
# ABOVE `list`, which must stay the last method in the class. Imports gain:
#   from datetime import date
#   from decimal import Decimal
#   from sqlalchemy import Numeric, case, func, literal, select
#   from pigrocrm.core.dashboard.schemas import ClosedInPeriod, PipelineStageSummary
#   from pigrocrm.core.pipeline.models import PipelineStage

    def pipeline_summary(self) -> list[PipelineStageSummary]:
        """Open deals per stage: count, `Σ valore_previsto`, count without a value, and
        the weighted estimate.

        Lives in the repository rather than on `DealService` on purpose (spec §3): these
        aggregates have no business rule beyond `deleted_at IS NULL`, and putting them on
        the service would create **two paths an agent can reach the same number by** --
        the deal domain tool and the dashboard tool -- which is exactly the duplication
        this slice exists not to introduce.

        `valore_ponderato` is the first of §3's two declared exceptions: a product of two
        columns of `deals`, rounded per row and then summed, HALF_UP. Allowed because both
        operands are columns of this one table and the result is not money received. It is
        labelled *stima* in every rendering and never added to revenue.

        A LEFT JOIN from `pipeline_stages`, so a stage with no deals comes back with
        zeroes: a missing stage and an empty stage render identically in a bar chart and
        the reader cannot tell which they are looking at.
        """
        rounded_weight = func.round(
            func.cast(Deal.valore_previsto, Numeric(20, 6))
            * func.cast(Deal.probabilita, Numeric(20, 6))
            / literal(100),
            2,
        )
        stmt = (
            select(
                PipelineStage.id,
                PipelineStage.code,
                PipelineStage.nome,
                PipelineStage.posizione,
                func.count(Deal.id).label("numero"),
                func.coalesce(func.sum(Deal.valore_previsto), literal(0)).label("valore"),
                func.count(case((Deal.valore_previsto.is_(None), 1))).label("senza"),
                func.coalesce(func.sum(rounded_weight), literal(0)).label("ponderato"),
            )
            .select_from(PipelineStage)
            .outerjoin(
                Deal,
                (Deal.pipeline_stage_id == PipelineStage.id) & Deal.deleted_at.is_(None),
            )
            .where(PipelineStage.tipo == "open")
            .group_by(
                PipelineStage.id, PipelineStage.code, PipelineStage.nome,
                PipelineStage.posizione,
            )
            .order_by(PipelineStage.posizione, PipelineStage.id)
        )
        return [
            PipelineStageSummary(
                stage_id=str(row.id),
                stage_code=row.code,
                stage_nome=row.nome,
                posizione=row.posizione,
                numero=row.numero,
                valore_totale=Decimal(row.valore).quantize(Decimal("0.01")),
                senza_valore=row.senza,
                valore_ponderato=Decimal(row.ponderato).quantize(Decimal("0.01")),
            )
            for row in self.session.execute(stmt).all()
        ]

    def closed_in_period(self, da: date, a: date) -> ClosedInPeriod:
        """Deals won and lost in the period, by `chiuso_il`.

        `chiuso_il` and not the timeline: `move_stage` records the stage *names*, which a
        user may rename (residuo R15), so deducing a historical closure would mean matching
        a mutable string. Rows with `chiuso_il IS NULL` are excluded here and counted by
        `unattributable_closures` so the dashboard can declare them.

        `tasso_conversione` is §3's second declared exception: a ratio of two counts of the
        same rows. `None` when the denominator is zero -- see `ClosedInPeriod`.
        """
        stmt = (
            select(
                PipelineStage.tipo,
                func.count(Deal.id).label("numero"),
                func.coalesce(func.sum(Deal.valore_previsto), literal(0)).label("valore"),
            )
            .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
            .where(
                Deal.deleted_at.is_(None),
                Deal.chiuso_il.is_not(None),
                Deal.chiuso_il >= da,
                Deal.chiuso_il <= a,
                PipelineStage.tipo.in_(("won", "lost")),
            )
            .group_by(PipelineStage.tipo)
        )
        by_tipo = {row.tipo: row for row in self.session.execute(stmt).all()}
        won = by_tipo.get("won")
        lost = by_tipo.get("lost")
        vinti = won.numero if won is not None else 0
        persi = lost.numero if lost is not None else 0
        chiusi = vinti + persi
        return ClosedInPeriod(
            vinti=vinti,
            persi=persi,
            valore_vinto=(
                Decimal(won.valore).quantize(Decimal("0.01"))
                if won is not None
                else Decimal("0.00")
            ),
            tasso_conversione=(
                (Decimal(vinti) * 100 / Decimal(chiusi)).quantize(Decimal("0.01"))
                if chiusi
                else None
            ),
        )

    def expected_closures(self, da: date, a: date) -> int:
        """Open deals whose `data_chiusura_prevista` falls in the window.

        `tipo='open'` only: a deal already won with a future expected date is not an
        expected closure, it is a stale field on a finished deal.
        """
        return (
            self.session.scalar(
                select(func.count(Deal.id))
                .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
                .where(
                    Deal.deleted_at.is_(None),
                    PipelineStage.tipo == "open",
                    Deal.data_chiusura_prevista.is_not(None),
                    Deal.data_chiusura_prevista >= da,
                    Deal.data_chiusura_prevista <= a,
                )
            )
            or 0
        )

    def unattributable_closures(self) -> int:
        """Deals in a terminal stage with no `chiuso_il`.

        §4.1: `chiuso_il` is deliberately not backfilled, so every deal closed before
        migration 0008 is unattributable to a period. This count is what lets the dashboard
        say "N deal chiusi prima dell'introduzione di questa misura non sono attribuibili a
        un periodo" instead of quietly reporting a conversion rate computed on a subset.
        """
        return (
            self.session.scalar(
                select(func.count(Deal.id))
                .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
                .where(
                    Deal.deleted_at.is_(None),
                    Deal.chiuso_il.is_(None),
                    PipelineStage.tipo.in_(("won", "lost")),
                )
            )
            or 0
        )
```

`Decimal(row.valore)` is safe because `func.sum` over a `Numeric` column returns a `Decimal` in psycopg 3, and `literal(0)` in the `coalesce` is adapted to the same type; the `quantize` is there to normalise `0` to `0.00` so the JSON is stable across an empty and a populated stage. `Numeric(20, 6)` in the weight expression gives the multiplication room before rounding — `Numeric(12,2) × Numeric(12,2)` would otherwise widen to a type Postgres picks for itself.

- [ ] **Step 5: Write the document aggregates**

```python
# packages/core/src/pigrocrm/core/documents/repository.py -- two methods, inserted ABOVE
# `list`. Imports gain:
#   from sqlalchemy import func, literal, select
#   from pigrocrm.core.dashboard.schemas import PendingOffer
#   from pigrocrm.core.db import today_local
#   from pigrocrm.core.deals.models import Deal
#   from pigrocrm.core.pipeline.models import PipelineStage

    def pending_offers(self, limit: int = 20) -> list[PendingOffer]:
        """Sent offers still awaiting an answer, oldest first, with their age in days.

        The age is computed in Python from `today_local()` rather than in SQL from
        `CURRENT_DATE`: `CURRENT_DATE` is the *server's* day, and every date in this
        product is a day in the emitter's zone (`db/clock.py`). On a UTC database at 00:30
        Rome time the two differ, and a dashboard showing "ferma da 0 giorni" for something
        sent yesterday is worse than showing nothing.
        """
        today = today_local()
        rows = self.session.execute(
            select(Document)
            .where(
                Document.deleted_at.is_(None),
                Document.tipo == "offerta",
                Document.stato == "inviata",
            )
            # Nulls last: an offer with no known start date is not the oldest one.
            .order_by(Document.stato_dal.asc().nulls_last(), Document.id.asc())
            .limit(limit)
        ).scalars()
        return [
            PendingOffer(
                document_id=str(row.id),
                titolo=row.titolo,
                deal_id=str(row.deal_id) if row.deal_id else None,
                customer_id=str(row.customer_id) if row.customer_id else None,
                stato_dal=row.stato_dal,
                giorni=(today - row.stato_dal).days if row.stato_dal is not None else None,
            )
            for row in rows
        ]

    def count_pending_offers(self) -> int:
        """The real total behind `pending_offers`'s truncated list, so a dashboard showing
        twenty of ninety says ninety."""
        return (
            self.session.scalar(
                select(func.count(Document.id)).where(
                    Document.deleted_at.is_(None),
                    Document.tipo == "offerta",
                    Document.stato == "inviata",
                )
            )
            or 0
        )

    def count_accepted_with_unwon_deal(self) -> int:
        """§6.2's first signal: accepted offers whose deal is not in a `won` stage.

        This is the case where automation A1 did **not** fire -- switched off, or declined
        with a recorded reason -- so it is the automation's permanent cross-check: if the
        automation goes quiet, this count speaks. It sits on the *commercial* dashboard
        because it needs no invoices, which is what lets it ship in the same sub-plan as
        the automation it verifies rather than one later (§17).

        A `COUNT` across a join, which §3 permits explicitly: it looks at two tables and
        produces no money figure. A `SUM` across a join is how the same row gets counted
        twice, and on a margin nobody notices.
        """
        return (
            self.session.scalar(
                select(func.count(Document.id))
                .join(Deal, Deal.id == Document.deal_id)
                .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
                .where(
                    Document.deleted_at.is_(None),
                    Document.tipo == "offerta",
                    Document.stato == "accettata",
                    Deal.deleted_at.is_(None),
                    PipelineStage.tipo != "won",
                )
            )
            or 0
        )
```

The `JOIN` on `Deal.id == Document.deal_id` is an inner join, which is what makes `test_the_signal_ignores_an_accepted_offer_with_no_deal` pass without a special case: an offer with `deal_id IS NULL` simply has no matching row.

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_commercial_aggregates.py -v`
Expected: PASS, twenty-two tests.

- [ ] **Step 7: Check for an import cycle**

`deals/repository.py` and `documents/repository.py` now import `dashboard/schemas.py`, and `dashboard/` imports neither.

Run: `uv run python -c "import pigrocrm.core.models_registry, pigrocrm.core.dashboard"`
Expected: no output.

- [ ] **Step 8: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add packages/core/src/pigrocrm/core/dashboard/ \
        packages/core/src/pigrocrm/core/deals/repository.py \
        packages/core/src/pigrocrm/core/documents/repository.py \
        packages/core/tests/test_commercial_aggregates.py
git commit -m "feat(dashboard): commercial aggregates, with §3's two exceptions in deals"
```

---
### Task B8: `DashboardService` — one endpoint, one transaction, one instant

**Files:**
- Create: `packages/core/src/pigrocrm/core/dashboard/service.py`
- Modify: `packages/core/src/pigrocrm/core/dashboard/schemas.py` (`PeriodoQuery`)
- Modify: `packages/core/src/pigrocrm/core/dashboard/__init__.py`
- Create: `packages/core/tests/test_dashboard_commercial.py`

**Interfaces:**
- Consumes: `DealRepository.{pipeline_summary,closed_in_period,expected_closures,unattributable_closures}`, `DocumentRepository.{pending_offers,count_pending_offers,count_accepted_with_unwon_deal}` (Task B7); `today_local`, `month_bounds` (Task B1).
- Produces:
  - `PeriodoQuery(BaseModel)` — `da: date | None = None`, `a: date | None = None`, with `resolve() -> Periodo` filling in the current month and validating the range.
  - `MAX_PERIOD_DAYS = 3660`
  - `SNAPSHOT_ISOLATION = "REPEATABLE READ"`
  - `DashboardService(session: Session)` with, in 6B, exactly one public method:
    `get_commercial_dashboard(self, query: PeriodoQuery, actor: Actor) -> CommercialDashboard`
  - `DashboardService._open_snapshot(self) -> datetime` — private, and the single place the isolation level is set.
- Task B9 asserts this module contains no arithmetic; Task B10 asserts the snapshot; Task B12 exposes the method on both surfaces; 6C appends two more public methods **and their two tools**.

**`REPEATABLE READ`, and why one transaction was not enough.** Spec §7.1: in `READ COMMITTED` — Postgres's default, and therefore what you get by saying nothing — **each statement takes its own snapshot**, so seven queries inside one transaction can see seven states exactly as seven transactions can. A user who adds two cards by hand and does not get the third stops trusting all three, and is right to. `REPEATABLE READ` takes the snapshot once, at the start. The transaction is read-only, so the usual price is not paid: a serialisation failure can only strike a writer, and nothing here writes.

**The service must be handed a session with no transaction in progress**, because Postgres refuses to change the isolation level once one has begun. In the API that is automatic — `SessionDep` yields a fresh session per request. `_open_snapshot` therefore fails **loudly** rather than silently continuing in `READ COMMITTED`: silent degradation here produces a total that was never true at any instant, and no amount of re-reading the service would reveal it.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_dashboard_commercial.py
"""§4's dashboard, composed and nothing more.

Every figure here is checked against the repository that produced it, not recomputed:
recomputing in the test would make the test the second source of truth §1 forbids, and a
test that agrees with a wrong implementation is worse than no test.

The snapshot property is Task B10's; this file uses its own sessions only because the
service needs a transaction it can set the isolation level on.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import session_factory, today_local
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.models import Document
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.pipeline.service import PipelineService

READONLY = Actor(id=uuid7(), type="user", role="readonly")
SEED = Actor(id=None, type="system", role="admin")


@pytest.fixture
def seeded(db_engine: Engine) -> Iterator[Engine]:
    """Committed rows on their own session, cleaned up afterwards.

    `db_session` cannot be used: it holds an outer transaction open, and Postgres refuses
    `SET TRANSACTION ISOLATION LEVEL` once a transaction has begun -- which is exactly
    what `DashboardService` does first.
    """
    factory = session_factory(db_engine)
    with factory() as session:
        PipelineService(session).seed_defaults(SEED)
        stages = {s.code: s for s in PipelineService(session).list() if s.code is not None}
        customer = Customer(ragione_sociale="DASH Cliente", nazione="IT", custom_fields={})
        session.add(customer)
        session.flush()

        session.add(
            Deal(nome="DASH aperto", customer_id=customer.id,
                 pipeline_stage_id=stages["lead"].id, valore_previsto="1000.00",
                 probabilita=50, data_chiusura_prevista=today_local(), custom_fields={})
        )
        session.add(
            Deal(nome="DASH vinto", customer_id=customer.id,
                 pipeline_stage_id=stages["vinto"].id, valore_previsto="5000.00",
                 probabilita=100, chiuso_il=today_local(), custom_fields={})
        )
        session.add(
            Deal(nome="DASH perso", customer_id=customer.id,
                 pipeline_stage_id=stages["perso"].id, valore_previsto="2000.00",
                 probabilita=0, chiuso_il=today_local(), custom_fields={})
        )
        session.flush()
        session.add(
            Document(customer_id=customer.id, tipo="offerta", titolo="DASH offerta",
                     stato="inviata", stato_dal=date(2026, 1, 1), versione_corrente=1,
                     custom_fields={})
        )
        session.commit()
    try:
        yield db_engine
    finally:
        with factory() as session:
            session.execute(delete(Document).where(Document.titolo.like("DASH %")))
            session.execute(delete(Deal).where(Deal.nome.like("DASH %")))
            session.execute(
                delete(Customer).where(Customer.ragione_sociale.like("DASH %"))
            )
            session.commit()


def _dashboard(engine: Engine, da: date | None = None, a: date | None = None):
    with session_factory(engine)() as session:
        return DashboardService(session).get_commercial_dashboard(
            PeriodoQuery(da=da, a=a), READONLY
        )


def test_the_period_defaults_to_the_current_month(seeded: Engine) -> None:
    from pigrocrm.core.db import month_bounds

    today = today_local()
    result = _dashboard(seeded)
    assert (result.periodo.da, result.periodo.a) == month_bounds(today.year, today.month)


def test_the_period_is_echoed_back_normalised(seeded: Engine) -> None:
    """Always echoed, because a screenshot of a dashboard with no explicit period is a
    number with no unit (§4)."""
    result = _dashboard(seeded, date(2026, 3, 1), date(2026, 3, 31))
    assert result.periodo.da == date(2026, 3, 1)
    assert result.periodo.a == date(2026, 3, 31)


def test_an_inverted_period_is_a_named_validation_error(seeded: Engine) -> None:
    with pytest.raises(ValidationFailed) as caught:
        _dashboard(seeded, date(2026, 3, 31), date(2026, 3, 1))
    assert caught.value.details["field"] == "da"


def test_an_absurdly_long_period_is_refused(seeded: Engine) -> None:
    """§7.3: the predicate always carries a bounded period. Without a ceiling, `da=0001-01-01`
    is a full scan requested from a query string."""
    with pytest.raises(ValidationFailed) as caught:
        _dashboard(seeded, date(1900, 1, 1), date(2026, 12, 31))
    assert caught.value.details["field"] == "a"


def test_supplying_only_one_bound_is_refused(seeded: Engine) -> None:
    """Half a period is not a period, and guessing the other half would silently answer a
    different question from the one asked."""
    with pytest.raises(ValidationFailed):
        _dashboard(seeded, date(2026, 3, 1), None)


def test_calcolato_alle_is_the_transaction_timestamp(seeded: Engine) -> None:
    from datetime import UTC, datetime

    before = datetime.now(UTC)
    result = _dashboard(seeded)
    after = datetime.now(UTC)
    assert before <= result.calcolato_alle <= after
    assert result.calcolato_alle.tzinfo is not None


def test_the_pipeline_matches_the_repository_verbatim(seeded: Engine) -> None:
    """Composition, not computation: the service returns what the repository produced,
    with the same names and the same values (§3 form 1)."""
    result = _dashboard(seeded)
    with session_factory(seeded)() as session:
        expected = DealRepository(session).pipeline_summary()
    assert result.pipeline == expected


def test_the_closures_match_the_repository_verbatim(seeded: Engine) -> None:
    today = today_local()
    result = _dashboard(seeded, date(today.year, today.month, 1), today)
    with session_factory(seeded)() as session:
        expected = DealRepository(session).closed_in_period(
            date(today.year, today.month, 1), today
        )
    assert result.chiusure == expected
    assert result.chiusure.vinti == 1
    assert result.chiusure.persi == 1
    assert result.chiusure.tasso_conversione is not None


def test_the_pending_offers_carry_their_age(seeded: Engine) -> None:
    result = _dashboard(seeded)
    offer = next(o for o in result.offerte_in_attesa if o.titolo == "DASH offerta")
    assert offer.giorni == (today_local() - date(2026, 1, 1)).days
    assert result.offerte_in_attesa_totale >= 1


def test_the_signal_is_present_on_the_commercial_dashboard(seeded: Engine) -> None:
    """§6.2 and §17: this signal ships with the automation it cross-checks, on the
    dashboard that needs no invoices."""
    result = _dashboard(seeded)
    assert result.offerte_accettate_deal_non_vinto == 0


def test_a_readonly_actor_sees_the_whole_dashboard(seeded: Engine) -> None:
    """§13: no new role and no new authorisation rule. Every dashboard is visible to
    whoever can read the services it reads, and slice 4 §11 gives those to every role. The
    only admin-only figure in that area is the fiscal estimate, which is on no dashboard
    (§5.3)."""
    result = _dashboard(seeded)
    assert result.pipeline


def test_the_service_runs_in_repeatable_read(seeded: Engine) -> None:
    """The level, read from the connection the service actually used. Task B10 proves the
    level does something; this proves it was set."""
    with session_factory(seeded)() as session:
        service = DashboardService(session)
        service.get_commercial_dashboard(PeriodoQuery(), READONLY)
        level = session.execute(
            __import__("sqlalchemy").text("SHOW transaction_isolation")
        ).scalar_one()
    assert level == "repeatable read"


def test_a_session_already_in_a_transaction_fails_loudly(db_engine: Engine) -> None:
    """The failure mode that must never be silent.

    If the isolation level cannot be set, the dashboard runs in READ COMMITTED and returns
    a total that was true at no single instant -- and nothing about re-reading the service
    would reveal it. So it raises instead.
    """
    with session_factory(db_engine)() as session:
        session.execute(__import__("sqlalchemy").text("SELECT 1"))  # opens a transaction
        with pytest.raises(RuntimeError, match="REPEATABLE READ"):
            DashboardService(session).get_commercial_dashboard(PeriodoQuery(), READONLY)


def test_the_service_has_exactly_one_public_method_in_6b() -> None:
    """Sub-plan 6C appends two more, each with its own tool. Pinned here so a method added
    without a tool fails in this file rather than in the architecture test, where the
    message is about a list."""
    import inspect

    public = {
        name
        for name, member in inspect.getmembers(DashboardService, predicate=inspect.isfunction)
        if not name.startswith("_")
        and member.__qualname__.startswith("DashboardService.")
    }
    assert public == {"get_commercial_dashboard"}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_dashboard_commercial.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'pigrocrm.core.dashboard.service'`.

- [ ] **Step 3: Add `PeriodoQuery` to the schemas**

```python
# packages/core/src/pigrocrm/core/dashboard/schemas.py -- append. Imports gain:
#   from pigrocrm.core.db import month_bounds, today_local
#   from pigrocrm.core.errors import ValidationFailed

# Ten years and a bit -- the span of the §16 reference corpus. A ceiling exists because
# §7.3 requires the predicate to always carry a bounded period: without one, `da=0001-01-01`
# is a full table scan requested from a query string.
MAX_PERIOD_DAYS = 3660


class PeriodoQuery(BaseModel):
    """The period, or nothing at all.

    Both bounds or neither. Supplying one and letting the service guess the other would
    silently answer a different question from the one asked, and the reader would have no
    way to see it -- the response echoes the period back for exactly this reason.
    """

    model_config = ConfigDict(extra="forbid")

    da: date | None = None
    a: date | None = None

    def resolve(self) -> "Periodo":
        if (self.da is None) != (self.a is None):
            raise ValidationFailed(
                "periodo",
                "da" if self.da is None else "a",
                "il periodo richiede entrambe le date, o nessuna",
                expected="da e a insieme, oppure nessuna delle due",
            )
        if self.da is None or self.a is None:
            today = today_local()
            first, last = month_bounds(today.year, today.month)
            return Periodo(da=first, a=last)
        if self.da > self.a:
            raise ValidationFailed(
                "periodo", "da", "la data iniziale è successiva a quella finale",
                expected=f"da <= {self.a.isoformat()}",
            )
        if (self.a - self.da).days > MAX_PERIOD_DAYS:
            raise ValidationFailed(
                "periodo", "a", "periodo troppo lungo",
                expected=f"al massimo {MAX_PERIOD_DAYS} giorni",
            )
        return Periodo(da=self.da, a=self.a)
```

`Periodo` is declared above `PeriodoQuery` in that file already, so the forward reference in quotes is only needed if `PeriodoQuery` is placed first; place it after and drop the quotes.

- [ ] **Step 4: Write the service**

```python
# packages/core/src/pigrocrm/core/dashboard/service.py
"""Composition, and deliberately nothing else.

**This module contains no arithmetic, and `packages/core/tests/test_dashboard_no_arithmetic.py`
makes that a fact of the build rather than an intention of this docstring.** It may not
import `Decimal`, and it may not contain a `BinOp` node with `*`, `/` or `-`. A composition
service that cannot subtract cannot invent a margin.

Spec §3: every figure on a dashboard is either returned verbatim by the service that owns
the data, or a single `COUNT`/`SUM` written in the repository of the table it counts. So
this file calls **services** for figures somebody else already owns and **repositories**
for the aggregates it defines -- and never a third thing.

Why repositories rather than services for those aggregates: a service exists to own
authorisation, a transaction and business rules, and these aggregates have none beyond
`deleted_at IS NULL`. Putting `pipeline_summary` on `DealService` would create two paths an
agent could reach the same number by -- the deal domain tool and the dashboard tool -- which
is the duplication this slice exists not to introduce.

**One endpoint, one transaction, one instant, in `REPEATABLE READ`.** Not one endpoint per
card. In `READ COMMITTED` -- Postgres's default, and so what you get by saying nothing --
each statement takes its own snapshot, and seven queries in one transaction can see seven
states exactly as seven transactions can: a user who adds two cards by hand and does not
get the third stops trusting all three, and is right to. The transaction is read-only, so
the usual price of the higher level is not paid -- a serialisation failure can only strike a
writer, and nothing here writes.

The accepted cost, stated because it is real: no partial rendering. One slow figure slows
the whole page. It is bearable because the queries are few and the period is always bounded,
and it is the price of the property this page exists for.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.dashboard.schemas import CommercialDashboard, PeriodoQuery
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.repository import DocumentRepository

# The property §7.1 requires, named so the tests can assert on the same constant the code
# uses rather than on a duplicated string literal.
SNAPSHOT_ISOLATION = "REPEATABLE READ"

_PENDING_OFFERS_SHOWN = 20
_EXPECTED_CLOSURE_WINDOW_DAYS = 30


class DashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.deals = DealRepository(session)
        self.documents = DocumentRepository(session)

    def _open_snapshot(self) -> datetime:
        """Begin the one read-only `REPEATABLE READ` transaction, and return its instant.

        Must be the first thing that touches the session: Postgres refuses to change the
        isolation level once a transaction has begun. In the API that is automatic --
        `SessionDep` yields a fresh session per request.

        It raises rather than continuing when it cannot. Silent degradation here produces a
        total that was true at no single instant, and nothing about re-reading this file
        would reveal it -- which makes a loud failure strictly better than a plausible
        number.

        `transaction_timestamp()` is constant for the whole transaction, so it is the
        instant the whole response describes. On its own it would prove nothing -- it is
        constant in `READ COMMITTED` too, which is precisely why criterion 6 asserts the
        isolation level as well.
        """
        try:
            self.session.connection(
                execution_options={"isolation_level": SNAPSHOT_ISOLATION}
            )
        except InvalidRequestError as exc:
            raise RuntimeError(
                "a dashboard needs a session with no transaction in progress so it can "
                f"run in {SNAPSHOT_ISOLATION}; this session already had one. Pass a fresh "
                "session (the API's SessionDep yields one per request)."
            ) from exc
        return self.session.execute(text("SELECT transaction_timestamp()")).scalar_one()

    def get_commercial_dashboard(
        self, query: PeriodoQuery, actor: Actor
    ) -> CommercialDashboard:
        """Pipeline snapshot plus two period measures. Touches no invoice and no hour --
        it reads `deals`, `pipeline_stages` and `documents`, which is what lets it ship
        before slice 3 (§4, §17).

        No authorisation check: §13 states this slice adds no role and no authorisation
        rule, every figure here comes from a read every role already has, and the one
        admin-only figure of that area -- the fiscal estimate -- is on no dashboard (§5.3).
        Inventing a fourth visibility level on a read-only screen would put a security rule
        where nobody looks for one. `actor` is taken because every service method here does.
        """
        periodo = query.resolve()
        calcolato_alle = self._open_snapshot()
        _, finestra_a = month_window(periodo)
        return CommercialDashboard(
            periodo=periodo,
            calcolato_alle=calcolato_alle,
            pipeline=self.deals.pipeline_summary(),
            chiusure=self.deals.closed_in_period(periodo.da, periodo.a),
            offerte_in_attesa=self.documents.pending_offers(_PENDING_OFFERS_SHOWN),
            offerte_in_attesa_totale=self.documents.count_pending_offers(),
            chiusure_previste_30_giorni=self.deals.expected_closures(
                periodo.a, finestra_a
            ),
            chiusure_non_attribuibili=self.deals.unattributable_closures(),
            offerte_accettate_deal_non_vinto=(
                self.documents.count_accepted_with_unwon_deal()
            ),
        )
```

The `month_window` call above needs a definition, and it cannot live in this module: computing "the period's end plus thirty days" is a subtraction-free addition, but `timedelta` arithmetic is still a `BinOp` and Task B9's clause forbids every one of them without exception. So it goes in `db/clock.py`, next to the other date arithmetic:

```python
# packages/core/src/pigrocrm/core/db/clock.py -- append.
def window_from(start: date, days: int) -> tuple[date, date]:
    """`(start, start + days)`, both inclusive.

    Here and not in `core/dashboard/` because that package is forbidden from containing any
    arithmetic at all -- no `*`, `/` or `-` BinOp, and no `Decimal` import -- so that it
    provably cannot invent a figure (spec §3, and
    `packages/core/tests/test_dashboard_no_arithmetic.py`). A date offset is harmless in
    itself; the rule has no exceptions precisely so that nobody has to judge which
    arithmetic is harmless.
    """
    return start, start + timedelta(days=days)
```

Add `timedelta` to that module's `from datetime import ...` line and `window_from` to `db/__init__.py`'s exports. Then in `service.py` replace the `month_window` line with:

```python
        _, finestra_a = window_from(periodo.a, _EXPECTED_CLOSURE_WINDOW_DAYS)
```

and import `window_from` from `pigrocrm.core.db`.

- [ ] **Step 5: Export the service**

```python
# packages/core/src/pigrocrm/core/dashboard/__init__.py -- add to imports and __all__:
from pigrocrm.core.dashboard.schemas import MAX_PERIOD_DAYS, PeriodoQuery
from pigrocrm.core.dashboard.service import SNAPSHOT_ISOLATION, DashboardService
# "MAX_PERIOD_DAYS", "PeriodoQuery", "SNAPSHOT_ISOLATION", "DashboardService" in __all__.
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_dashboard_commercial.py -v`
Expected: PASS, fourteen tests.

If `test_a_session_already_in_a_transaction_fails_loudly` does **not** raise, SQLAlchemy accepted the execution option and silently ignored it. In that case replace the `try`/`except` with an explicit pre-check and keep the same message:

```python
        if self.session.in_transaction():
            raise RuntimeError(
                "a dashboard needs a session with no transaction in progress so it can "
                f"run in {SNAPSHOT_ISOLATION}; this session already had one. Pass a fresh "
                "session (the API's SessionDep yields one per request)."
            )
        self.session.connection(
            execution_options={"isolation_level": SNAPSHOT_ISOLATION}
        )
```

Decide by the test, not by reading the SQLAlchemy changelog.

- [ ] **Step 7: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/dashboard/ \
        packages/core/src/pigrocrm/core/db/clock.py \
        packages/core/src/pigrocrm/core/db/__init__.py \
        packages/core/tests/test_dashboard_commercial.py
git commit -m "feat(dashboard): commercial dashboard in one repeatable-read transaction"
```

---

### Task B9: Criterion 11's two AST clauses — the provenance rule, mechanised

**Files:**
- Create: `packages/core/tests/test_dashboard_no_arithmetic.py`
- Modify: `packages/core/tests/test_architecture.py` (a cross-reference)

**Interfaces:**
- Consumes: the existence of `packages/core/src/pigrocrm/core/dashboard/` (Task B8).
- Produces:
  - `DASHBOARD_ROOT`, `ARITHMETIC_OPS`, `DECIMAL_IMPORT_EXEMPT: frozenset[str] = frozenset({"schemas.py"})`, `BINOP_EXEMPT: frozenset[str] = frozenset()`
  - `test_no_dashboard_module_imports_decimal`, `test_no_dashboard_module_contains_a_multiplication_division_or_subtraction`, `test_the_binop_exemption_list_is_empty`, and two guard-proving tests.
- Nothing depends on this task's output; it depends on 6C not weakening it, which is why the exemption list is asserted to be **empty** rather than merely small.

**Why this is a test and not a code review note.** Spec §3 is the load-bearing paragraph of the whole slice: a dashboard that sums its own numbers is a second source of truth, and a second source of truth about a margin is worse than no margin — someone who reads a wrong number acts, someone who reads no number asks. §3 proposes making it AST-checkable, and the two clauses were chosen because they are **decidable without type inference**: a rule that requires knowing a variable is a `Decimal` is not a rule a test can apply.

**One exemption, and it is about declaration rather than computation.** `dashboard/schemas.py` imports `Decimal` to *type* its fields. Typing a field performs no arithmetic, and the clause exists to forbid arithmetic. The `BinOp` list, by contrast, is empty and is asserted to be empty — including in `schemas.py`.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_dashboard_no_arithmetic.py
"""**Criterion 11**, the two clauses of spec §3.

`DashboardService` is a composition service: it resolves authorisation, opens a
transaction, calls services and repositories, and assembles the result. It contains no
arithmetic. That sentence is worth nothing as a comment and everything as a build failure,
because the alternative -- a dashboard that computes a margin its own way -- is the second
source of truth §1 is about, and on a margin nobody notices.

Both clauses are decidable on the AST **without type inference**, which is why they are
these two clauses and not "no arithmetic on money": a rule needing to know that a variable
holds a `Decimal` is not a rule a test can apply.

  1. no module under `core/dashboard/` imports `Decimal`  -- except `schemas.py`, which
     imports it to *type* its fields and performs no arithmetic;
  2. no module under `core/dashboard/` contains a `BinOp` node with `*`, `/` or `-`, and
     the exemption list for this clause is **empty**.

A composition service that cannot subtract cannot invent a margin.
"""

import ast
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = CORE_ROOT / "src" / "pigrocrm" / "core" / "dashboard"

ARITHMETIC_OPS = (ast.Mult, ast.Div, ast.FloorDiv, ast.Sub, ast.Mod, ast.Pow)

# `schemas.py` imports `Decimal` to annotate its fields. Declaring a field's type is not
# arithmetic, and clause 1 exists to forbid arithmetic. Every other module in the package
# is covered.
DECIMAL_IMPORT_EXEMPT: frozenset[str] = frozenset({"schemas.py"})

# Clause 2 has **no** exemptions, and this emptiness is itself asserted below. A `BinOp`
# with `-` in a dashboard module is either a figure being derived -- forbidden -- or a date
# offset, which belongs in `db/clock.py` where the other date arithmetic already lives.
# Keeping the list empty is what stops the rule degrading one "harmless" entry at a time.
BINOP_EXEMPT: frozenset[str] = frozenset()


def _modules() -> list[Path]:
    return sorted(DASHBOARD_ROOT.rglob("*.py"))


def _imports_decimal(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "decimal":
            if any(alias.name == "Decimal" for alias in node.names):
                return True
        if isinstance(node, ast.Import):
            if any(alias.name in ("decimal", "decimal.Decimal") for alias in node.names):
                return True
    return False


def _arithmetic_binops(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ARITHMETIC_OPS):
            found.append((type(node.op).__name__, node.lineno))
        # `x -= 1` and `x *= 2` are AugAssign, not BinOp, and would slip through a
        # BinOp-only walk. Same rule, same reason.
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ARITHMETIC_OPS):
            found.append((f"Aug{type(node.op).__name__}", node.lineno))
    return found


def test_the_dashboard_package_exists_so_this_file_is_not_vacuous() -> None:
    """A guard over an empty directory passes forever and proves nothing."""
    assert DASHBOARD_ROOT.is_dir(), DASHBOARD_ROOT
    modules = _modules()
    assert len(modules) >= 3, [p.name for p in modules]
    assert (DASHBOARD_ROOT / "service.py").exists()


def test_no_dashboard_module_imports_decimal() -> None:
    offenders: list[str] = []
    for path in _modules():
        if path.name in DECIMAL_IMPORT_EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _imports_decimal(tree):
            offenders.append(path.name)
    assert not offenders, (
        "a dashboard module imported Decimal. Spec §3: every figure is either returned "
        "verbatim by the service that owns the data, or a single COUNT/SUM in that table's "
        "repository. If a derived figure is needed, it belongs to the service that owns "
        f"the data it derives from. Offenders: {offenders}"
    )


def test_no_dashboard_module_contains_a_multiplication_division_or_subtraction() -> None:
    offenders: list[str] = []
    for path in _modules():
        if path.name in BINOP_EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = _arithmetic_binops(tree)
        if found:
            offenders.append(f"{path.name}: {found}")
    assert not offenders, (
        "a dashboard module contains arithmetic. A composition service that cannot "
        "subtract cannot invent a margin (spec §3). Date offsets belong in db/clock.py; "
        f"derived figures belong to the owning service. Offenders: {offenders}"
    )


def test_the_binop_exemption_list_is_empty() -> None:
    """Spec §3 requires it, in those words: "la lista delle eccezioni è vuota". An
    exemption list that is allowed to grow is a rule that degrades one harmless-looking
    entry at a time, and each entry is individually defensible."""
    assert BINOP_EXEMPT == frozenset()


def test_the_decimal_exemption_is_exactly_schemas() -> None:
    assert DECIMAL_IMPORT_EXEMPT == frozenset({"schemas.py"})


def test_the_guard_catches_an_import(tmp_path: Path) -> None:
    """The guard proven to catch what it claims to, in the same style as the
    import-direction tests in test_architecture.py."""
    sneaky = tmp_path / "service.py"
    sneaky.write_text("from decimal import Decimal\nx = Decimal('1')\n", encoding="utf-8")
    assert _imports_decimal(ast.parse(sneaky.read_text(encoding="utf-8")))


def test_the_guard_catches_each_forbidden_operator(tmp_path: Path) -> None:
    for source in (
        "margine = ricavi - costi\n",
        "quota = parte / totale\n",
        "peso = valore * probabilita\n",
        "totale -= sconto\n",
    ):
        module = tmp_path / "m.py"
        module.write_text(source, encoding="utf-8")
        found = _arithmetic_binops(ast.parse(source))
        assert found, source


def test_addition_is_allowed_because_it_is_not_the_defect() -> None:
    """`+` is not on the list, deliberately: string and list concatenation are `Add` nodes
    and are everywhere in ordinary code, while the defect §3 is about -- deriving a margin,
    a rate or a share -- needs `-`, `/` or `*`. A rule that also banned `+` would be
    unenforceable and would be turned off."""
    assert not _arithmetic_binops(ast.parse("etichetta = 'a' + 'b'\n"))
```

- [ ] **Step 2: Run it and watch it fail, then pass**

Run: `uv run pytest packages/core/tests/test_dashboard_no_arithmetic.py -v`

Expected on the tree as Task B8 left it: **PASS**, because Task B8 already moved the one date offset into `db/clock.py::window_from` for this reason. To see the guard work, temporarily inline that offset back into `dashboard/service.py` as `periodo.a + timedelta(days=30)` — no, that is an `Add` and is allowed; use `periodo.a - timedelta(days=-30)`, which is the same date and a `Sub`. Run again:

Expected: `test_no_dashboard_module_contains_a_multiplication_division_or_subtraction` FAILS naming `service.py` and the line. **Revert.** A guard never observed to fail is not a guard.

- [ ] **Step 3: Cross-reference from the architecture test**

```python
# packages/core/tests/test_architecture.py -- append.
def test_the_dashboard_arithmetic_ban_has_its_own_guard() -> None:
    """Spec §3's two AST clauses live in `test_dashboard_no_arithmetic.py`. Named here
    because this file is where somebody looks for the project's architectural rules, and a
    rule enforced in a file nobody opens is a rule deleted in the next refactor."""
    guard = CORE_ROOT / "tests" / "test_dashboard_no_arithmetic.py"
    assert guard.exists()
    source = guard.read_text(encoding="utf-8")
    assert "BINOP_EXEMPT: frozenset[str] = frozenset()" in source, (
        "the BinOp exemption list must stay empty (spec §3)"
    )
```

- [ ] **Step 4: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add packages/core/tests/test_dashboard_no_arithmetic.py \
        packages/core/tests/test_architecture.py
git commit -m "test(dashboard): §3's provenance rule as two AST clauses, exemptions empty"
```

---
### Task B10: Criterion 6 — one dashboard is one instant, proven by inverting it

**Files:**
- Create: `packages/core/tests/test_dashboard_snapshot.py`

**Interfaces:**
- Consumes: `DashboardService.get_commercial_dashboard`, `SNAPSHOT_ISOLATION` (Task B8); `DealRepository.pipeline_summary` (Task B7); the `db_engine` fixture.
- Produces: nothing importable. The deliverable is the executable criterion.

**Why clause (a) alone would be worthless, in the spec's own words.** `transaction_timestamp()` is constant for the whole transaction **even in `READ COMMITTED`**, so a test that stopped at "the response has one timestamp" would pass on a dashboard reading seven different states. The spec's own self-review caught this. So there are three clauses, and the third is the inversion: **with the isolation level forced to `read committed`, the test must fail.** An assertion that passes either way is measuring nothing.

**This test does not use `db_session`.** That fixture hands out a session on a connection with an already-open outer transaction, and Postgres refuses `SET TRANSACTION ISOLATION LEVEL` once one has begun. It is one of exactly two files in the suite that deliberately builds its own sessions, and its docstring says so.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_dashboard_snapshot.py
"""**Criterion 6.** A dashboard is one instant, and this is what proves it.

Three clauses, and the first two would not be enough on their own:

  (a) the isolation level in force during the request is `repeatable read`, read from
      `SHOW transaction_isolation` on the same connection;
  (b) a parallel connection COMMITs an invoice-shaped change *between* the first and
      second internal query, synchronised with a barrier -- and that change appears in
      **no** figure of the response;
  (c) `calcolato_alle` precedes the parallel commit.

And then the inversion, which is what makes (a) meaningful instead of decorative: repeated
with the isolation level forced to `read committed`, (b) **fails**. `transaction_timestamp()`
is constant for a whole transaction even in `READ COMMITTED`, so a test that stopped at (c)
would pass on a dashboard that read seven different states.

This file deliberately does not use the `db_session` fixture: it holds an outer transaction
open, and Postgres refuses `SET TRANSACTION ISOLATION LEVEL` once a transaction has begun.
`test_dashboard_commercial.py` is the only other file in the suite that builds its own
sessions, and for the same reason.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.dashboard import service as dashboard_service
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import session_factory, today_local
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.pipeline.service import PipelineService

READONLY = Actor(id=uuid7(), type="user", role="readonly")
SEED = Actor(id=None, type="system", role="admin")
_PREFIX = "SNAP"
_BARRIER_TIMEOUT = 10.0


@pytest.fixture
def seeded(db_engine: Engine) -> Iterator[tuple[Engine, dict, Customer]]:
    factory = session_factory(db_engine)
    with factory() as session:
        PipelineService(session).seed_defaults(SEED)
        stages = {s.code: s for s in PipelineService(session).list() if s.code is not None}
        customer = Customer(
            ragione_sociale=f"{_PREFIX} Cliente", nazione="IT", custom_fields={}
        )
        session.add(customer)
        session.flush()
        session.add(
            Deal(nome=f"{_PREFIX} base", customer_id=customer.id,
                 pipeline_stage_id=stages["lead"].id, valore_previsto="1000.00",
                 probabilita=50, custom_fields={})
        )
        session.commit()
        detached = {code: stage for code, stage in stages.items()}
        customer_id = customer.id
    try:
        with factory() as session:
            reread = session.get(Customer, customer_id)
            assert reread is not None
            yield db_engine, detached, reread
    finally:
        with factory() as session:
            session.execute(delete(Deal).where(Deal.nome.like(f"{_PREFIX} %")))
            session.execute(
                delete(Customer).where(Customer.ragione_sociale.like(f"{_PREFIX} %"))
            )
            session.commit()


def _run_with_a_commit_in_the_middle(
    engine: Engine,
    stages: dict,
    customer_id: object,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[object, datetime]:
    """Run the dashboard, committing a new open deal from another connection between its
    first and second internal query.

    The barrier hangs off `pipeline_summary`, which is the first aggregate the service
    calls. Signalling from inside it and waiting for the writer means the commit lands
    after the snapshot was taken (`SELECT transaction_timestamp()` is the transaction's
    first statement and acquires it) and before every remaining query -- which is exactly
    the window `READ COMMITTED` would leak through.
    """
    reader_reached_first_query = threading.Event()
    writer_committed = threading.Event()
    commit_instant: list[datetime] = []

    def writer() -> None:
        reader_reached_first_query.wait(_BARRIER_TIMEOUT)
        with session_factory(engine)() as session:
            session.add(
                Deal(
                    nome=f"{_PREFIX} intruso", customer_id=customer_id,
                    pipeline_stage_id=stages["lead"].id, valore_previsto="9999.00",
                    probabilita=50, chiuso_il=None, custom_fields={},
                )
            )
            session.commit()
            commit_instant.append(
                session.execute(text("SELECT statement_timestamp()")).scalar_one()
            )
        writer_committed.set()

    original = DealRepository.pipeline_summary
    state = {"tripped": False}

    def barrier(self: DealRepository) -> object:
        if not state["tripped"]:
            state["tripped"] = True
            reader_reached_first_query.set()
            writer_committed.wait(_BARRIER_TIMEOUT)
        return original(self)

    monkeypatch.setattr(DealRepository, "pipeline_summary", barrier)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    with session_factory(engine)() as session:
        result = DashboardService(session).get_commercial_dashboard(
            PeriodoQuery(), READONLY
        )
    thread.join(timeout=_BARRIER_TIMEOUT)
    assert commit_instant, "the parallel writer never committed"
    return result, commit_instant[0]


def test_clause_a_the_isolation_level_in_force_is_repeatable_read(
    seeded: tuple[Engine, dict, Customer]
) -> None:
    engine, _stages, _customer = seeded
    with session_factory(engine)() as session:
        DashboardService(session).get_commercial_dashboard(PeriodoQuery(), READONLY)
        level = session.execute(text("SHOW transaction_isolation")).scalar_one()
    assert level == "repeatable read"
    assert dashboard_service.SNAPSHOT_ISOLATION == "REPEATABLE READ"


def test_clause_b_a_commit_in_the_middle_appears_in_no_figure(
    seeded: tuple[Engine, dict, Customer], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, stages, customer = seeded
    result, _instant = _run_with_a_commit_in_the_middle(
        engine, stages, customer.id, monkeypatch
    )

    lead = next(row for row in result.pipeline if row.stage_code == "lead")
    # One deal, the seeded one. The intruder committed after the snapshot and is invisible
    # to every query in the transaction -- not just to the ones that ran before it.
    assert lead.numero == 1
    assert lead.valore_totale.quantize(lead.valore_totale) == lead.valore_totale
    assert lead.valore_totale == __import__("decimal").Decimal("1000.00")


def test_clause_c_calcolato_alle_precedes_the_parallel_commit(
    seeded: tuple[Engine, dict, Customer], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, stages, customer = seeded
    result, commit_instant = _run_with_a_commit_in_the_middle(
        engine, stages, customer.id, monkeypatch
    )
    assert result.calcolato_alle < commit_instant, (
        f"calcolato_alle {result.calcolato_alle} is not before the parallel commit "
        f"{commit_instant}; it is not the snapshot's instant"
    )


def test_the_inversion_read_committed_leaks_the_parallel_commit(
    seeded: tuple[Engine, dict, Customer], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test that makes clause (a) mean something.

    Forced to `READ COMMITTED` -- Postgres's default, and therefore what this dashboard
    would silently get if nobody had said otherwise -- each statement takes its own
    snapshot, so the query that runs *after* the barrier sees the intruder. If this test
    ever starts passing with the same assertion as clause (b), the isolation level has
    stopped doing anything and clauses (a) to (c) are decorative.
    """
    engine, stages, customer = seeded
    monkeypatch.setattr(dashboard_service, "SNAPSHOT_ISOLATION", "READ COMMITTED")

    result, _instant = _run_with_a_commit_in_the_middle(
        engine, stages, customer.id, monkeypatch
    )
    lead = next(row for row in result.pipeline if row.stage_code == "lead")
    assert lead.numero == 2, (
        "in READ COMMITTED the post-barrier query should have seen the parallel commit. "
        "It did not, which means the barrier is not actually landing between two "
        "statements -- fix the barrier before trusting clause (b)."
    )


def test_the_whole_response_is_internally_consistent(
    seeded: tuple[Engine, dict, Customer]
) -> None:
    """The property the user actually experiences: adding two cards by hand and getting the
    third. Asserted on the response alone, with no parallel writer, so a failure here is a
    composition bug rather than a race."""
    engine, _stages, _customer = seeded
    with session_factory(engine)() as session:
        result = DashboardService(session).get_commercial_dashboard(
            PeriodoQuery(), READONLY
        )
    total_open = sum(row.numero for row in result.pipeline)
    with_value = sum(row.numero - row.senza_valore for row in result.pipeline)
    assert total_open >= with_value >= 0
    assert len(result.offerte_in_attesa) <= result.offerte_in_attesa_totale
```

The `sum(...)` calls in that last test are in a **test** file, not in `core/dashboard/`, so Task B9's ban does not reach them — and they are checking the response for internal consistency rather than producing a figure anybody reads.

- [ ] **Step 2: Run it and watch the inversion fail first**

Temporarily change `SNAPSHOT_ISOLATION` in `dashboard/service.py` to `"READ COMMITTED"`.

Run: `uv run pytest packages/core/tests/test_dashboard_snapshot.py -v`
Expected: `test_clause_a_...` FAILS (`read committed` != `repeatable read`) and `test_clause_b_...` FAILS with `assert 2 == 1` — the intruder leaked in. **Restore `"REPEATABLE READ"`.**

- [ ] **Step 3: Run it green**

Run: `uv run pytest packages/core/tests/test_dashboard_snapshot.py -v`
Expected: PASS, five tests.

If `test_the_inversion_read_committed_leaks_the_parallel_commit` fails with the barrier message, the writer is committing before the reader's first statement rather than between two of them. Raise `_BARRIER_TIMEOUT`, and check that `pipeline_summary` really is the first aggregate `get_commercial_dashboard` calls — if a later refactor reorders them, move the barrier to whichever is first rather than reordering the service to suit the test.

- [ ] **Step 4: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add packages/core/tests/test_dashboard_snapshot.py
git commit -m "test(dashboard): criterion 6, one snapshot, proven by inverting the level"
```

---

### Task B11: Criterion 2 — every card equals its drill-through

**Files:**
- Modify: `packages/core/src/pigrocrm/core/documents/repository.py` (extract the predicate, add the filter)
- Modify: `packages/core/src/pigrocrm/core/documents/schemas.py` (`DocumentListQuery.solo_deal_non_vinto`)
- Modify: `apps/api/src/pigrocrm_api/routers/documents.py` (the query parameter)
- Create: `packages/core/tests/test_dashboard_drillthrough.py`

**Interfaces:**
- Consumes: `DashboardService.get_commercial_dashboard` (Task B8); `DocumentRepository.count_accepted_with_unwon_deal` (Task B7); `DealRepository.list`, `DocumentRepository.list` (Task A4).
- Produces:
  - `documents/repository.py`: `_accepted_with_unwon_deal_predicate()` at module level, used by **both** `count_accepted_with_unwon_deal` and `list`.
  - `DocumentListQuery.solo_deal_non_vinto: bool = False`
  - `GET /api/documents?solo_deal_non_vinto=true`
- Nothing later depends on this task except Task B14, which links the card to that URL.

**§7.2's second property is only true if the predicate is literally the same, so it is made literally the same.** The spec says: *"La card e il suo drill-through sono la stessa query, non due calcoli."* A signal counted with one predicate and listed with a hand-copied variant of it is two calculations that agree today. Extracting the predicate to a module-level function and calling it from both the `COUNT` and the `SELECT` is what makes the criterion mechanical rather than aspirational.

**Which cards have a link, decided here.** Criterion 2 binds "ogni cifra della dashboard che ha un collegamento", so the set of linked cards is a design decision and this task fixes it for the commercial dashboard:

| Card | Link | Why |
|---|---|---|
| Deals open per stage (`numero`) | `/app/deal/lista?stage_id=…` | The list endpoint already filters by `stage_id` |
| Offers awaiting an answer (`offerte_in_attesa_totale`) | `/app/documenti?tipo=offerta&stato=inviata` | Already filterable |
| **Accepted offer, deal not won** | `/app/documenti?solo_deal_non_vinto=true` | The filter this task adds |
| `chiusure` (won/lost/rate/value) | **no link** | A period-filtered deal list would need `chiuso_il` range filters on the deals endpoint, which nothing else wants. Declared rather than half-built |
| `chiusure_previste_30_giorni` | **no link** | Same: a `data_chiusura_prevista` range filter with no second consumer |
| `chiusure_non_attribuibili` | **no link** | It is a disclosure about missing data, not a set worth browsing |

An unlinked card carries no drill-through obligation, and a card must not carry a link this task did not verify.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_dashboard_drillthrough.py
"""**Criterion 2.** Every card that has a link equals the count of rows its link returns.

One predicate, two reads. The dashboard's figure and the list behind it must not be two
calculations that happen to agree -- so where a filter did not already exist, the predicate
is extracted to one function and both callers use it (`documents/repository.py`).

This is also what makes the cache safe (§7.2): the card and its drill-through cannot say
different things about the same data, so a divergence can only ever be the age of the
cached dashboard response -- and then the list wins and the card refreshes.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import session_factory, today_local
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.schemas import DealListQuery
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.documents.schemas import DocumentListQuery
from pigrocrm.core.pipeline.service import PipelineService

READONLY = Actor(id=uuid7(), type="user", role="readonly")
SEED = Actor(id=None, type="system", role="admin")
_PREFIX = "DRILL"


@pytest.fixture
def seeded(db_engine: Engine) -> Iterator[tuple[Engine, dict]]:
    """A corpus with every linked card non-empty: an empty card equals an empty list
    trivially, which would make this whole file pass without proving anything."""
    factory = session_factory(db_engine)
    with factory() as session:
        PipelineService(session).seed_defaults(SEED)
        stages = {s.code: s for s in PipelineService(session).list() if s.code is not None}
        customer = Customer(
            ragione_sociale=f"{_PREFIX} Cliente", nazione="IT", custom_fields={}
        )
        session.add(customer)
        session.flush()

        open_deals = []
        for index in range(4):
            deal = Deal(
                nome=f"{_PREFIX} aperto {index}", customer_id=customer.id,
                pipeline_stage_id=stages["lead"].id, valore_previsto="1000.00",
                probabilita=50, custom_fields={},
            )
            session.add(deal)
            open_deals.append(deal)
        won = Deal(
            nome=f"{_PREFIX} vinto", customer_id=customer.id,
            pipeline_stage_id=stages["vinto"].id, valore_previsto="5000.00",
            probabilita=100, chiuso_il=today_local(), custom_fields={},
        )
        session.add(won)
        session.flush()

        for index in range(3):
            session.add(
                Document(
                    customer_id=customer.id, tipo="offerta",
                    titolo=f"{_PREFIX} inviata {index}", stato="inviata",
                    stato_dal=today_local(), versione_corrente=1, custom_fields={},
                )
            )
        # Two accepted offers on open deals -- the signal -- and one on a won deal, which
        # is not an inconsistency and must not be counted.
        for index in range(2):
            session.add(
                Document(
                    deal_id=open_deals[index].id, tipo="offerta",
                    titolo=f"{_PREFIX} accettata {index}", stato="accettata",
                    stato_dal=today_local(), versione_corrente=1, custom_fields={},
                )
            )
        session.add(
            Document(
                deal_id=won.id, tipo="offerta", titolo=f"{_PREFIX} accettata ok",
                stato="accettata", stato_dal=today_local(), versione_corrente=1,
                custom_fields={},
            )
        )
        session.commit()
        stage_ids = {code: stage.id for code, stage in stages.items()}
    try:
        yield db_engine, stage_ids
    finally:
        with factory() as session:
            session.execute(delete(Document).where(Document.titolo.like(f"{_PREFIX} %")))
            session.execute(delete(Deal).where(Deal.nome.like(f"{_PREFIX} %")))
            session.execute(
                delete(Customer).where(Customer.ragione_sociale.like(f"{_PREFIX} %"))
            )
            session.commit()


def _dashboard(engine: Engine):
    with session_factory(engine)() as session:
        return DashboardService(session).get_commercial_dashboard(
            PeriodoQuery(), READONLY
        )


def test_the_open_deals_card_equals_its_deal_list(seeded: tuple[Engine, dict]) -> None:
    engine, stage_ids = seeded
    card = next(
        row for row in _dashboard(engine).pipeline if row.stage_id == str(stage_ids["lead"])
    )
    with session_factory(engine)() as session:
        page = DealService(session).list(
            DealListQuery(stage_id=stage_ids["lead"], limit=200), READONLY
        )
    assert card.numero == len(page.items)


def test_the_pending_offers_card_equals_its_document_list(
    seeded: tuple[Engine, dict]
) -> None:
    engine, _stage_ids = seeded
    total = _dashboard(engine).offerte_in_attesa_totale
    with session_factory(engine)() as session:
        rows = DocumentRepository(session).list(
            DocumentListQuery(tipo="offerta", stato="inviata", limit=200)
        )
    assert total == len(rows)


def test_the_signal_card_equals_its_filtered_document_list(
    seeded: tuple[Engine, dict]
) -> None:
    """The card and the list share one predicate function, so this cannot drift."""
    engine, _stage_ids = seeded
    count = _dashboard(engine).offerte_accettate_deal_non_vinto
    with session_factory(engine)() as session:
        rows = DocumentRepository(session).list(
            DocumentListQuery(solo_deal_non_vinto=True, limit=200)
        )
    assert count == 2
    assert count == len(rows)
    assert all(row.stato == "accettata" for row in rows)


def test_the_signal_filter_excludes_the_offer_whose_deal_is_won(
    seeded: tuple[Engine, dict]
) -> None:
    """The negative half. Without it, a filter that returned every accepted offer would
    pass the equality test above only because the count was wrong in the same way."""
    engine, _stage_ids = seeded
    with session_factory(engine)() as session:
        rows = DocumentRepository(session).list(
            DocumentListQuery(solo_deal_non_vinto=True, limit=200)
        )
    assert all(not row.titolo.endswith("ok") for row in rows)


def test_the_signal_filter_composes_with_the_other_filters(
    seeded: tuple[Engine, dict]
) -> None:
    """It is an additional predicate, not a replacement for the query. A filter that
    silently dropped `tipo` would make the drill-through a different question."""
    engine, _stage_ids = seeded
    with session_factory(engine)() as session:
        rows = DocumentRepository(session).list(
            DocumentListQuery(solo_deal_non_vinto=True, stato="inviata", limit=200)
        )
    assert rows == []


def test_the_count_and_the_list_use_the_same_predicate_function() -> None:
    """The mechanical half of §7.2, asserted on the source: two hand-copied predicates
    agree until one of them is edited."""
    import inspect

    from pigrocrm.core.documents import repository as documents_repository

    source = inspect.getsource(documents_repository)
    assert source.count("_accepted_with_unwon_deal_predicate") >= 3, (
        "the predicate must be defined once and called from both "
        "count_accepted_with_unwon_deal and list"
    )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_dashboard_drillthrough.py -v`
Expected: the three signal tests FAIL with `pydantic_core.ValidationError: Unexpected keyword argument 'solo_deal_non_vinto'`.

- [ ] **Step 3: Extract the predicate and add the filter**

```python
# packages/core/src/pigrocrm/core/documents/repository.py -- add at module level, above
# the class:

def _accepted_with_unwon_deal_predicate() -> tuple[object, ...]:
    """§6.2's first signal, as one predicate used by both the count and the list.

    Extracted rather than written twice because §7.2's guarantee -- "the card and its
    drill-through are the same query, not two calculations" -- is only true if the
    predicate is literally the same. Two hand-copied predicates agree until one is edited,
    and then the dashboard and the list disagree about the same rows with nothing to say
    which is right.

    Returned as a tuple of clauses so the caller can splat it into `where(...)` alongside
    its own; the joins are the caller's, because a `COUNT` and a paginated `SELECT` want
    them written differently.
    """
    return (
        Document.deleted_at.is_(None),
        Document.tipo == "offerta",
        Document.stato == "accettata",
        Deal.deleted_at.is_(None),
        PipelineStage.tipo != "won",
    )
```

```python
# ...and replace `count_accepted_with_unwon_deal`'s body to use it:
    def count_accepted_with_unwon_deal(self) -> int:
        """§6.2's first signal: accepted offers whose deal is not in a `won` stage.

        This is the case where automation A1 did **not** fire -- switched off, or declined
        with a recorded reason -- so it is the automation's permanent cross-check: if the
        automation goes quiet, this count speaks. It sits on the *commercial* dashboard
        because it needs no invoices, which is what lets it ship in the same sub-plan as
        the automation it verifies rather than one later (§17).

        A `COUNT` across a join, which §3 permits explicitly: it looks at two tables and
        produces no money figure. A `SUM` across a join is how the same row gets counted
        twice, and on a margin nobody notices.
        """
        return (
            self.session.scalar(
                select(func.count(Document.id))
                .join(Deal, Deal.id == Document.deal_id)
                .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
                .where(*_accepted_with_unwon_deal_predicate())
            )
            or 0
        )
```

```python
# ...and add the branch to `list`, immediately before the sort/cursor block:
        if query.solo_deal_non_vinto:
            # The drill-through of §6.2's signal card, sharing its predicate literally.
            # An inner join, so an offer with no deal simply has no matching row -- no
            # special case needed, and none written.
            stmt = (
                stmt.join(Deal, Deal.id == Document.deal_id)
                .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
                .where(*_accepted_with_unwon_deal_predicate())
            )
```

```python
# packages/core/src/pigrocrm/core/documents/schemas.py -- one field on DocumentListQuery,
# placed after `search`:
    # The drill-through of the commercial dashboard's inconsistency signal (§6.2). A
    # boolean and not a free-text filter: it selects one fixed predicate, and the card
    # that links here counts rows with that same predicate.
    solo_deal_non_vinto: bool = False
```

```python
# apps/api/src/pigrocrm_api/routers/documents.py -- one parameter and one argument.
    solo_deal_non_vinto: Annotated[bool, Query()] = False,
# ...
        solo_deal_non_vinto=solo_deal_non_vinto,
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_dashboard_drillthrough.py packages/core/tests/test_commercial_aggregates.py -v`
Expected: PASS.

- [ ] **Step 5: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/documents/repository.py \
        packages/core/src/pigrocrm/core/documents/schemas.py \
        apps/api/src/pigrocrm_api/routers/documents.py \
        packages/core/tests/test_dashboard_drillthrough.py
git commit -m "feat(dashboard): criterion 2, one predicate shared by card and drill-through"
```

---
### Task B12: The 6B surface on both adapters, and the exclusion list of exactly one name

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/dashboard.py`
- Create: `apps/api/src/pigrocrm_api/routers/automations.py`
- Modify: `apps/api/src/pigrocrm_api/main.py`
- Create: `apps/mcp/src/pigrocrm_mcp/tools/dashboard.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`
- Create: `apps/api/tests/test_dashboard_api.py`
- Create: `apps/mcp/tests/test_mcp_dashboard.py`

**Interfaces:**
- Consumes: `DashboardService.get_commercial_dashboard(query: PeriodoQuery, actor: Actor) -> CommercialDashboard` (Task B8); `AutomationConfigService.describe_automations(actor) -> AutomationsDescription` and `.update_automation_config(data, actor) -> AutomationConfigRead` (Task B3); `ActivityRepository.by_kind` (Task B3).
- Produces:
  - `GET /api/dashboard/commerciale?da=&a=` → `CommercialDashboard`
  - `GET /api/automation-config` → `AutomationConfigRead`; `PUT /api/automation-config` → `AutomationConfigRead`, **admin**
  - `GET /api/automation-runs?limit=` → `list[AutomationRun]`
  - MCP tools `get_commercial_dashboard(da: str | None, a: str | None)` and `describe_automations()`
  - **No** MCP tool for `update_automation_config` — and Task A11's `MCP_EXCLUDED_SLICE6` already declares it, so this task changes not one character of that list.
- 6C appends two dashboard endpoints and two tools to the same two files.

**The R1 gate applies again, with the same wording as Task A11's Step 6.** A dashboard tool on a process-wide shared `Session` is not a degraded feature, it is a wrong figure: two concurrent dashboards can each read half their numbers inside the other's transaction and produce a total that was true at no instant — and §7.1's whole guarantee is a property of the session. Check before registering.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_dashboard_api.py
"""The HTTP surface of §4, plus the configuration endpoints of §9.6."""

from fastapi.testclient import TestClient


def test_the_commercial_dashboard_is_one_request(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    """One endpoint, not one per card (§7.1)."""
    response = client.get("/api/dashboard/commerciale", cookies=admin_cookie)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "periodo", "calcolato_alle", "pipeline", "chiusure", "offerte_in_attesa",
        "offerte_in_attesa_totale", "chiusure_previste_30_giorni",
        "chiusure_non_attribuibili", "offerte_accettate_deal_non_vinto",
    }


def test_the_period_round_trips_through_the_query_string(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    response = client.get(
        "/api/dashboard/commerciale", params={"da": "2026-03-01", "a": "2026-03-31"},
        cookies=admin_cookie,
    )
    assert response.json()["periodo"] == {"da": "2026-03-01", "a": "2026-03-31"}


def test_an_inverted_period_is_a_422_naming_the_field(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    response = client.get(
        "/api/dashboard/commerciale", params={"da": "2026-03-31", "a": "2026-03-01"},
        cookies=admin_cookie,
    )
    assert response.status_code == 422
    assert response.json()["field"] == "da"


def test_money_is_serialised_as_a_string(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    """A JSON number is a float in every client that parses it, and a float total is the
    defect this whole slice is built to avoid."""
    body = client.get("/api/dashboard/commerciale", cookies=admin_cookie).json()
    for row in body["pipeline"]:
        assert isinstance(row["valore_totale"], str), row
        assert isinstance(row["valore_ponderato"], str), row


def test_a_readonly_actor_sees_the_dashboard(
    client: TestClient, readonly_cookie: dict[str, str]
) -> None:
    assert client.get(
        "/api/dashboard/commerciale", cookies=readonly_cookie
    ).status_code == 200


def test_an_unauthenticated_request_is_a_401(client: TestClient) -> None:
    assert client.get("/api/dashboard/commerciale").status_code == 401


def test_the_automation_config_can_be_read_by_anyone_and_written_by_an_admin(
    client: TestClient, admin_cookie: dict[str, str], readonly_cookie: dict[str, str]
) -> None:
    assert client.get("/api/automation-config", cookies=readonly_cookie).status_code == 200

    forbidden = client.put(
        "/api/automation-config", json={"a1_offerta_accettata_vince_deal": False},
        cookies=readonly_cookie,
    )
    assert forbidden.status_code == 403

    allowed = client.put(
        "/api/automation-config", json={"a1_offerta_accettata_vince_deal": False},
        cookies=admin_cookie,
    )
    assert allowed.status_code == 200
    assert allowed.json()["a1_offerta_accettata_vince_deal"] is False


def test_an_unknown_field_on_the_config_is_refused(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    """`extra="forbid"`: a typo in a field name must not silently do nothing."""
    response = client.put(
        "/api/automation-config", json={"a3_qualcosa": True}, cookies=admin_cookie
    )
    assert response.status_code == 422


def test_the_runs_endpoint_returns_the_recent_activities(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    client.put(
        "/api/automation-config", json={"a2_offerta_inviata_avanza_deal": False},
        cookies=admin_cookie,
    )
    response = client.get("/api/automation-runs", params={"limit": 5},
                          cookies=admin_cookie)
    assert response.status_code == 200
    kinds = [run["kind"] for run in response.json()]
    assert "automazione.configurazione_modificata" in kinds


def test_the_runs_limit_is_bounded(client: TestClient, admin_cookie: dict[str, str]) -> None:
    assert client.get(
        "/api/automation-runs", params={"limit": 500}, cookies=admin_cookie
    ).status_code == 422
```

```python
# apps/mcp/tests/test_mcp_dashboard.py
"""§11.1's dashboard tools, and the one deliberate absence.

The dashboards are on the MCP surface not for symmetry but because their shape is already
§3's arithmetic-free composition: the tool returns the same figures from the same owning
service, never a second version. Leaving them off would force an agent to make six reads
and add them up itself -- the second source of truth reached by another road.
"""

from typing import Any


async def test_the_commercial_dashboard_tool_is_registered(mcp_server: Any) -> None:
    tools = {tool.name for tool in await mcp_server.list_tools()}
    assert "get_commercial_dashboard" in tools
    assert "describe_automations" in tools


async def test_update_automation_config_has_no_tool(mcp_server: Any) -> None:
    """§11.1's single exclusion. It changes what the system will do to future data with no
    human in the loop (slice 4 §11 reason 2), and while residuo R10 is open -- a PAT has no
    scopes and inherits its owner's full role -- *not registering the tool* is the only
    enforcement that actually holds. An authorisation check would let an admin token
    straight through."""
    tools = {tool.name for tool in await mcp_server.list_tools()}
    assert "update_automation_config" not in tools
    assert not any("automation_config" in name and "update" in name for name in tools)


async def test_the_tool_returns_the_same_figures_as_the_service(
    mcp_server: Any, mcp_context: Any
) -> None:
    from pigrocrm.core.dashboard.schemas import PeriodoQuery
    from pigrocrm.core.dashboard.service import DashboardService

    result = await mcp_server.call_tool("get_commercial_dashboard", {})
    payload = result.structured_content

    direct = DashboardService(mcp_context.session).get_commercial_dashboard(
        PeriodoQuery(), mcp_context.actor
    )
    assert payload["pipeline"] == direct.model_dump(mode="json")["pipeline"]


async def test_an_inverted_period_is_a_domain_error(mcp_server: Any) -> None:
    result = await mcp_server.call_tool(
        "get_commercial_dashboard", {"da": "2026-03-31", "a": "2026-03-01"}
    )
    assert result.is_error


async def test_describe_automations_names_both_rules(mcp_server: Any) -> None:
    result = await mcp_server.call_tool("describe_automations", {})
    payload = result.structured_content
    assert [rule["codice"] for rule in payload["regole"]] == ["A1", "A2"]
```

Use the fixture names `apps/mcp/tests/conftest.py` already provides; if there is no `mcp_context` fixture, add one exposing the same `McpContext` the server was built with rather than constructing a second one.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest apps/api/tests/test_dashboard_api.py apps/mcp/tests/test_mcp_dashboard.py -v`
Expected: every API test FAILS with `404`; the MCP tests FAIL on the missing tool names — except `test_update_automation_config_has_no_tool`, which passes vacuously and will keep passing, which is the point of it.

- [ ] **Step 3: Write the routers**

```python
# apps/api/src/pigrocrm_api/routers/dashboard.py
"""One endpoint per dashboard. Sub-plan 6C adds two more to this file.

Each one is a single request served by a single read-only `REPEATABLE READ` transaction:
`SessionDep` yields a fresh session per request, which is what lets `DashboardService`
set the isolation level at all (see `_open_snapshot`). Do not add a dependency here that
touches the session before the service does.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from pigrocrm.core.dashboard.schemas import CommercialDashboard, PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], responses=PROBLEM_RESPONSES)


@router.get("/commerciale", response_model=CommercialDashboard)
def commerciale(
    session: SessionDep,
    actor: ActorDep,
    # Both or neither: `PeriodoQuery.resolve` refuses one alone rather than guessing the
    # other, because guessing would silently answer a different question. The default is
    # the current month, and the response always echoes the period back -- a screenshot of
    # a dashboard with no explicit period is a number with no unit (§4).
    da: Annotated[date | None, Query()] = None,
    a: Annotated[date | None, Query()] = None,
) -> CommercialDashboard:
    return DashboardService(session).get_commercial_dashboard(
        PeriodoQuery(da=da, a=a), actor
    )
```

```python
# apps/api/src/pigrocrm_api/routers/automations.py
"""§9.6's configuration and §9.5's third observability surface.

`PUT` and not `PATCH`, with both fields optional: the body is a partial update read with
`exclude_unset=True`, and `PUT` is what the shipped `emitter` and `fiscal_profile`
single-row endpoints already use. One convention for single-row configuration.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.automations.config_service import AutomationConfigService
from pigrocrm.core.automations.schemas import (
    AUTOMATION_KINDS,
    AutomationConfigRead,
    AutomationConfigUpdate,
    AutomationRun,
    AutomationsDescription,
)
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(tags=["automations"], responses=PROBLEM_RESPONSES)


@router.get("/api/automation-config", response_model=AutomationConfigRead)
def get_config(session: SessionDep, actor: ActorDep) -> AutomationConfigRead:
    return AutomationConfigService(session).describe_automations(actor).configurazione


@router.put("/api/automation-config", response_model=AutomationConfigRead)
def put_config(
    data: AutomationConfigUpdate, session: SessionDep, actor: ActorDep
) -> AutomationConfigRead:
    # `require_admin` lives in the service, not here: slice 1's own review found the same
    # check living only in a router and therefore absent for every other caller of the
    # shared service (see `PipelineService.seed_defaults`'s docstring). One place.
    return AutomationConfigService(session).update_automation_config(data, actor)


@router.get("/api/automations", response_model=AutomationsDescription)
def describe(session: SessionDep, actor: ActorDep) -> AutomationsDescription:
    """The two rules, their state and the last executions -- what the settings page renders
    in one request instead of three."""
    return AutomationConfigService(session).describe_automations(actor)


@router.get("/api/automation-runs", response_model=list[AutomationRun])
def runs(
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[AutomationRun]:
    """A read of `activities` by `kind`, never a new table (§9.4).

    Bounded like every other list in the project. `actor` is unused beyond
    authentication, which `ActorDep` has already performed -- the runs are the same
    timeline entries every role can already read on the entity itself.
    """
    return [
        AutomationRun(
            kind=activity.kind,
            occurred_at=activity.occurred_at,
            deal_id=activity.entity_id if activity.entity_type == "deal" else None,
            regola=activity.payload.get("regola"),
            motivo=activity.payload.get("motivo"),
            payload=activity.payload,
        )
        for activity in ActivityRepository(session).by_kind(AUTOMATION_KINDS, limit)
    ]
```

```python
# apps/api/src/pigrocrm_api/main.py -- add `automations, dashboard` to the router import
# line and to the registration tuple, keeping both alphabetical.
```

- [ ] **Step 4: Write the MCP tools**

```python
# apps/mcp/src/pigrocrm_mcp/tools/dashboard.py
"""Thin, like every other tool module: resolve the service on the context's session, call
it, `model_dump(mode="json")`.

`mode="json"` and not the default: it turns every `Decimal` into a string. A JSON number is
a float in whatever parses it on the other side, and a float margin is the defect this
slice exists to prevent.
"""

from typing import Any

from pigrocrm.core.automations.config_service import AutomationConfigService
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService

from pigrocrm_mcp.context import McpContext


def get_commercial_dashboard(context: McpContext, query: PeriodoQuery) -> dict[str, Any]:
    return (
        DashboardService(context.session)
        .get_commercial_dashboard(query, context.actor)
        .model_dump(mode="json")
    )


def describe_automations(context: McpContext) -> dict[str, Any]:
    return (
        AutomationConfigService(context.session)
        .describe_automations(context.actor)
        .model_dump(mode="json")
    )
```

```python
# apps/mcp/src/pigrocrm_mcp/tools/__init__.py -- two tools, registered next to the others.
# Imports gain:
#   from datetime import date
#   from pigrocrm.core.dashboard.schemas import PeriodoQuery
#   from pigrocrm_mcp.tools import dashboard as dashboard_tools

    @mcp.tool()
    @guard
    def get_commercial_dashboard(
        da: str | None = None, a: str | None = None
    ) -> dict[str, Any]:
        """La dashboard commerciale: pipeline aperta per stato (numero, valore, valore
        ponderato *stimato*), deal vinti e persi nel periodo con il tasso di conversione,
        offerte inviate in attesa con la loro anzianita' in giorni, chiusure previste nei
        30 giorni successivi al periodo, e il segnale «offerta accettata ma deal non
        vinto». `da` e `a` sono date ISO (`2026-03-01`) e vanno insieme: se mancano
        entrambe si usa il mese in corso. `valore_ponderato` e' una **stima**
        (valore_previsto x probabilita) e non e' fatturato: non sommarlo ai ricavi.
        `chiusure_non_attribuibili` conta i deal chiusi prima che questa misura esistesse,
        che non appartengono a nessun periodo.
        """
        return dashboard_tools.get_commercial_dashboard(
            context,
            PeriodoQuery(
                da=date.fromisoformat(da) if da else None,
                a=date.fromisoformat(a) if a else None,
            ),
        )

    @mcp.tool()
    @guard
    def describe_automations() -> dict[str, Any]:
        """Le due automazioni del sistema, se sono attive, e le ultime esecuzioni con il
        loro esito. A1: un'offerta accettata sposta il deal a vinto. A2: un'offerta inviata
        fa avanzare il deal allo stato «offerta», mai indietro. Le esecuzioni includono
        anche le **non** esecuzioni, con il motivo (`stage_bersaglio_assente`,
        `stage_bersaglio_ambiguo`, `gia_nello_stato`, `regola_disattivata`): «non e'
        scattata» e «non doveva scattare» sono cose diverse. La configurazione si cambia
        solo dall'interfaccia web, da un amministratore.
        """
        return dashboard_tools.describe_automations(context)
```

`date.fromisoformat` on a malformed string raises `ValueError`, which `_guard` converts into an error message the agent can read. `da: str` rather than `da: date` at the tool boundary follows the file's own documented "runtime-permissive, schema-only-strict" convention.

- [ ] **Step 5: The R1 gate**

Run: `grep -n "lambda: session\|contextvars\|session_provider" apps/mcp/src/pigrocrm_mcp/__main__.py apps/mcp/src/pigrocrm_mcp/server.py`

If the output still shows one process-lifetime `Session`, comment out **both** `@mcp.tool()` registration blocks from Step 4, keep `tools/dashboard.py`, add the same comment Task A11 Step 6 specifies, and skip `apps/mcp/tests/test_mcp_dashboard.py` at module level — except `test_update_automation_config_has_no_tool`, which must keep running because it asserts an absence. Move that one test into `apps/mcp/tests/test_mcp_schema.py`, which is not skipped.

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest apps/api/tests/test_dashboard_api.py apps/mcp/tests/test_mcp_dashboard.py packages/core/tests/test_architecture.py -v`
Expected: PASS. `test_every_other_public_method_of_a_slice6_service_has_a_tool` now covers `DashboardService.get_commercial_dashboard` and `AutomationConfigService.describe_automations`, both of which have tools, and `update_automation_config`, which is the one declared exclusion.

- [ ] **Step 7: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/pigrocrm_api/routers/dashboard.py \
        apps/api/src/pigrocrm_api/routers/automations.py \
        apps/api/src/pigrocrm_api/main.py \
        apps/mcp/src/pigrocrm_mcp/tools/dashboard.py \
        apps/mcp/src/pigrocrm_mcp/tools/__init__.py \
        apps/api/tests/test_dashboard_api.py \
        apps/mcp/tests/test_mcp_dashboard.py
git commit -m "feat(api): commercial dashboard and automation config on both adapters"
```

---

### Task B13: The five chart tokens, the four chart shapes, and criterion 14

**Files:**
- Modify: `apps/web/src/styles/tokens.css`
- Modify: `apps/web/src/styles/tokens.test.ts`
- Create: `apps/web/src/features/dashboard/charts.tsx`
- Create: `apps/web/src/features/dashboard/charts.test.tsx`
- Create: `apps/web/src/test/no-browser-arithmetic.test.ts`
- Modify: `apps/web/eslint.config.js`

**Interfaces:**
- Consumes: nothing from earlier frontend tasks except the existing `cn` helper and the token file.
- Produces:
  - `--chart-1` … `--chart-5` in `tokens.css`'s `:root` block (**not** in `@theme` — see below)
  - `apps/web/src/features/dashboard/charts.tsx`:
    - `export function BigNumber({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'neutral' | 'accent' })`
    - `export function BarRows({ caption, rows }: { caption: string; rows: BarRow[] })`, `export type BarRow = { label: string; value: string; ratio: number; tone: number }`
    - `export function Sparkline({ caption, points }: { caption: string; points: SparkPoint[] })`, `export type SparkPoint = { label: string; value: string; ratio: number }`
  - `apps/web/src/test/no-browser-arithmetic.test.ts` — criterion 14's AST test.
- Task B14 composes all three; 6C reuses them unchanged.

**`:root`, not `@theme`.** `tokens.css:47` declares the palette inside a Tailwind v4 `@theme` block, whose literal hex values are what let the app generate `bg-watermelon/50`-style utilities; a `@theme` entry holding a `color-mix()` of a `var()` cannot be resolved at build time into those utilities. The chart tokens are consumed as `var(--chart-1)` in inline styles and never as a Tailwind utility class, so they belong in `:root` beside `--primary` and `--ring`, which are already `var()` indirections. This keeps `tokens.css` the single source of colour without disturbing `@theme`.

**No charting library.** Four shapes — big numbers, horizontal bars as CSS widths, one sparkline, one table — as inline SVG and CSS. A library costs 40–100 KB for four shapes in a project that gave its landing page a 40 KB total budget (slice 5 §9.4), and it would impose its own palette while `tokens.css` is the single source of colour and has tests behind it. **Every chart renders an equivalent table**, because a chart without a table is a figure a screen reader does not read.

- [ ] **Step 1: Write the failing tests**

```ts
// apps/web/src/styles/tokens.test.ts -- append inside the existing describe block. The
// hexToRgb / relativeLuminance / contrastRatio helpers and the token reader at the top of
// the file are reused, not redefined.

  const CHART_TOKENS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5']

  it('declares five chart tokens', () => {
    for (const token of CHART_TOKENS) {
      expect(css).toContain(`${token}:`)
    }
  })

  it('builds every chart token out of existing tints, with no raw hex but white', () => {
    // The mechanical half of "tokens.css stays the single source of colour" (slice 5 §9.3's
    // rule, extended here). `#ffffff` is the one literal permitted: it is the neutral being
    // mixed toward, not a sixth tint.
    for (const token of CHART_TOKENS) {
      const declaration = css.match(new RegExp(`${token}:\\s*([^;]+);`))
      expect(declaration).not.toBeNull()
      const value = declaration![1]
      expect(value).toContain('color-mix(')
      expect(value).toContain('var(--color-')
      const hexes = value.match(/#[0-9a-fA-F]{3,8}/g) ?? []
      expect(hexes.every((hex) => hex.toLowerCase() === '#ffffff')).toBe(true)
    }
  })

  it('declares the chart tokens outside the @theme block', () => {
    // A @theme entry holding a color-mix() of a var() cannot be resolved into Tailwind
    // utilities at build time, which is what @theme's literal hexes are for. The chart
    // tokens are read as var(--chart-n) in inline styles only.
    const theme = css.slice(css.indexOf('@theme'), css.indexOf('}', css.indexOf('@theme')))
    for (const token of CHART_TOKENS) {
      expect(theme).not.toContain(token)
    }
  })

  it('keeps every chart colour readable against both app backgrounds', () => {
    // Computed sRGB values of the five color-mix() expressions, recorded here because the
    // test cannot evaluate color-mix() in Node. If a token's expression changes, recompute
    // these in a browser and update both together -- the pair is the assertion.
    const COMPUTED: Record<string, string> = {
      '--chart-1': '#f15a76',
      '--chart-2': '#3a4d68',
      '--chart-3': '#cfc069',
      '--chart-4': '#5e6b79',
      '--chart-5': '#6b1533',
    }
    const light = tokenHex('--color-mint-cream')
    const dark = tokenHex('--color-prussian-blue')
    for (const [token, hex] of Object.entries(COMPUTED)) {
      // 3:1 -- the WCAG threshold for a graphical object, not for body text. A chart mark
      // is a component boundary, and holding it to 4.5:1 would collapse the five hues into
      // three usable ones.
      expect(contrastRatio(hex, light)).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(hex, dark)).toBeGreaterThanOrEqual(3)
    }
  })

  it('keeps the five chart colours distinguishable from each other', () => {
    // Five bars a reader cannot tell apart is one bar drawn five times.
    const COMPUTED = ['#f15a76', '#3a4d68', '#cfc069', '#5e6b79', '#6b1533']
    for (let i = 0; i < COMPUTED.length; i += 1) {
      for (let j = i + 1; j < COMPUTED.length; j += 1) {
        expect(contrastRatio(COMPUTED[i]!, COMPUTED[j]!)).toBeGreaterThanOrEqual(1.2)
      }
    }
  })
```

`tokenHex` is the existing reader the file already defines for pulling a hex out of `tokens.css`; use its real name.

```tsx
// apps/web/src/features/dashboard/charts.tsx -- test file
// apps/web/src/features/dashboard/charts.test.tsx
/**
 * Four shapes, no library, and every one of them with an equivalent table.
 *
 * A chart without a table is a figure a screen reader does not read (§13), so the table is
 * not a fallback -- it is the accessible rendering, and the visual mark is decoration on
 * top of it. That is why every assertion below is on table semantics rather than on SVG.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarRows, BigNumber, Sparkline } from './charts'

describe('BigNumber', () => {
  it('renders the value exactly as given, never reformatted', () => {
    // The API sends "1234.56" already formatted for it-IT upstream; the component must not
    // parse it. Parsing is what criterion 14 forbids.
    render(<BigNumber label="Fatturato" value="1.234,56 €" hint="imponibile, emesso" />)
    expect(screen.getByText('1.234,56 €')).toBeInTheDocument()
    expect(screen.getByText('Fatturato')).toBeInTheDocument()
    expect(screen.getByText('imponibile, emesso')).toBeInTheDocument()
  })

  it('associates the label with the value for a screen reader', () => {
    render(<BigNumber label="Deal aperti" value="12" />)
    expect(screen.getByRole('group', { name: /deal aperti/i })).toBeInTheDocument()
  })
})

describe('BarRows', () => {
  const rows = [
    { label: 'Lead', value: '3.000,00 €', ratio: 1, tone: 1 },
    { label: 'Offerta', value: '500,00 €', ratio: 0.166, tone: 2 },
  ]

  it('renders a real table with a caption', () => {
    render(<BarRows caption="Pipeline per stato" rows={rows} />)
    expect(screen.getByRole('table', { name: 'Pipeline per stato' })).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(3) // header + two
  })

  it('shows every label and value as text', () => {
    render(<BarRows caption="Pipeline per stato" rows={rows} />)
    expect(screen.getByText('Lead')).toBeInTheDocument()
    expect(screen.getByText('3.000,00 €')).toBeInTheDocument()
  })

  it('draws the bar with a CSS width and marks it decorative', () => {
    render(<BarRows caption="Pipeline per stato" rows={rows} />)
    const bars = screen.getAllByTestId('bar-fill')
    expect(bars[0]).toHaveStyle({ width: '100%' })
    // The bar duplicates the number next to it, so it is hidden from the accessibility
    // tree rather than announced twice.
    expect(bars[0]).toHaveAttribute('aria-hidden', 'true')
  })

  it('clamps a ratio outside 0..1 instead of overflowing the row', () => {
    render(
      <BarRows caption="c" rows={[{ label: 'x', value: '1', ratio: 4, tone: 1 }]} />,
    )
    expect(screen.getByTestId('bar-fill')).toHaveStyle({ width: '100%' })
  })

  it('renders an empty state rather than an empty table', () => {
    render(<BarRows caption="Pipeline per stato" rows={[]} />)
    expect(screen.getByText(/nessun dato/i)).toBeInTheDocument()
  })
})

describe('Sparkline', () => {
  const points = [
    { label: 'lun', value: '8,00', ratio: 1 },
    { label: 'mar', value: '0,00', ratio: 0 },
    { label: 'mer', value: '4,00', ratio: 0.5 },
  ]

  it('renders an SVG marked decorative and a table that carries the data', () => {
    render(<Sparkline caption="Ore per giorno" points={points} />)
    expect(screen.getByTestId('sparkline-svg')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('table', { name: 'Ore per giorno' })).toBeInTheDocument()
    expect(screen.getByText('mar')).toBeInTheDocument()
    expect(screen.getByText('0,00')).toBeInTheDocument()
  })

  it('handles a single point without dividing by zero', () => {
    render(<Sparkline caption="c" points={[{ label: 'lun', value: '8', ratio: 1 }]} />)
    expect(screen.getByTestId('sparkline-svg')).toBeInTheDocument()
  })
})
```

```ts
// apps/web/src/test/no-browser-arithmetic.test.ts
/**
 * **Criterion 14.** No number is born in the browser.
 *
 * Slice 4 §14.4 describes this test as already written; it is not -- slice 4 is not
 * implemented and `apps/web` has no source-reading test other than `styles/tokens.test.ts`,
 * which parses CSS with a regex. So this slice **creates** it, scoped to the dashboard
 * modules it introduces.
 *
 * Deliberately out of scope, and named so nobody widens the scope without deciding to: the
 * five existing `Number()` call sites in `features/settings/FieldsPanel.tsx`,
 * `features/settings/PipelinePanel.tsx`, `features/deals/columns.tsx`,
 * `components/DynamicFieldRenderer.tsx` and `routes/app/clienti/$customerId.tsx`. Each
 * coerces a position, a probability or a form input -- none is an economic field from a
 * dashboard response. If slice 4 lands a wider guard later, this file's scope is subsumed
 * and it can be deleted.
 *
 * The TypeScript compiler API is used rather than a regex: `Number(` inside a string
 * literal or a comment is not a call, and a regex cannot tell the difference.
 */
import { readFileSync } from 'node:fs'
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const SCOPED_ROOTS = [
  join(__dirname, '..', 'features', 'dashboard'),
  join(__dirname, '..', 'routes', 'app'),
]
const FORBIDDEN_CALLS = new Set(['Number', 'parseFloat', 'parseInt'])

function sourceFiles(root: string): string[] {
  if (!statSync(root, { throwIfNoEntry: false })) return []
  const found: string[] = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) found.push(...sourceFiles(path))
    else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      found.push(path)
    }
  }
  return found
}

function offendingCalls(path: string): string[] {
  const text = readFileSync(path, 'utf-8')
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.ESNext, true)
  const offenders: string[] = []

  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
      if (FORBIDDEN_CALLS.has(node.expression.text)) {
        const { line } = source.getLineAndCharacterOfPosition(node.getStart())
        offenders.push(`${node.expression.text}() at line ${line + 1}`)
      }
    }
    // The unary `+x` coercion, which is the same defect written shorter.
    if (
      ts.isPrefixUnaryExpression(node) &&
      node.operator === ts.SyntaxKind.PlusToken
    ) {
      const { line } = source.getLineAndCharacterOfPosition(node.getStart())
      offenders.push(`unary + at line ${line + 1}`)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return offenders
}

describe('no number is born in the browser', () => {
  it('finds files to check, so the guard is not vacuous', () => {
    const files = SCOPED_ROOTS.flatMap(sourceFiles)
    expect(files.length).toBeGreaterThan(0)
  })

  it('never coerces an API value to a JS number in a dashboard module', () => {
    const offenders: string[] = []
    for (const root of SCOPED_ROOTS) {
      for (const file of sourceFiles(root)) {
        const found = offendingCalls(file)
        if (found.length > 0) offenders.push(`${file}: ${found.join(', ')}`)
      }
    }
    expect(
      offenders,
      'the dashboards do not add anything -- every total arrives already summed ' +
        '(§13). Format the string the API sent; never parse it.',
    ).toEqual([])
  })

  it('catches each forbidden form when it is present', () => {
    // The guard proven to catch what it claims to, on a synthetic source.
    const probe = join(__dirname, '__probe__.ts')
    const cases = [
      'const total = Number(row.valore_totale)',
      'const total = parseFloat(row.valore_totale)',
      'const total = +row.valore_totale',
    ]
    for (const code of cases) {
      const source = ts.createSourceFile(probe, code, ts.ScriptTarget.ESNext, true)
      let hit = false
      const visit = (node: ts.Node): void => {
        if (
          (ts.isCallExpression(node) &&
            ts.isIdentifier(node.expression) &&
            FORBIDDEN_CALLS.has(node.expression.text)) ||
          (ts.isPrefixUnaryExpression(node) &&
            node.operator === ts.SyntaxKind.PlusToken)
        ) {
          hit = true
        }
        ts.forEachChild(node, visit)
      }
      visit(source)
      expect(hit, code).toBe(true)
    }
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/web && pnpm exec vitest run src/styles/tokens.test.ts src/features/dashboard/charts.test.tsx src/test/no-browser-arithmetic.test.ts`
Expected: the token tests FAIL on the missing `--chart-*` declarations; the chart tests FAIL to resolve `./charts`; the arithmetic guard FAILS its "not vacuous" assertion because `features/dashboard/` does not exist.

- [ ] **Step 3: Add the tokens**

```css
/* apps/web/src/styles/tokens.css -- append inside the existing :root block, after --ring.
   NOT inside @theme: a @theme entry holding a color-mix() of a var() cannot be resolved
   into Tailwind utilities at build time, and these are read only as var(--chart-n) in
   inline styles. tokens.css stays the single source of colour either way. */

  /* Five chart hues, every one derived from the five existing tints -- no sixth colour
     enters the product. #ffffff is the one literal permitted inside a color-mix(): it is
     the neutral being mixed toward, not a tint. Enforced by styles/tokens.test.ts. */
  --chart-1: color-mix(in oklab, var(--color-watermelon) 78%, #ffffff);
  --chart-2: color-mix(in oklab, var(--color-prussian-blue) 72%, #ffffff);
  --chart-3: color-mix(in oklab, var(--color-royal-gold) 82%, var(--color-charcoal-blue));
  --chart-4: color-mix(in oklab, var(--color-charcoal-blue) 84%, #ffffff);
  --chart-5: color-mix(in oklab, var(--color-watermelon) 40%, var(--color-prussian-blue));
```

- [ ] **Step 4: Write the chart primitives**

```tsx
// apps/web/src/features/dashboard/charts.tsx
import { cn } from '@/lib/utils'

/**
 * Four shapes, no charting library: big numbers, horizontal bars as CSS widths, one
 * sparkline, one table. A library costs 40-100 KB for these four in a project that gave
 * its landing page a 40 KB budget (slice 5 §9.4), and it would bring its own palette while
 * `tokens.css` is the single source of colour and has tests behind it.
 *
 * **Every shape renders an equivalent table**, and the table is not a fallback: it is the
 * accessible rendering, and the visual mark is decoration layered on top with
 * `aria-hidden`. A chart without a table is a figure a screen reader does not read (§13).
 *
 * **Nothing here parses a number.** Values arrive as the strings the API sent, already
 * formatted, and `ratio` arrives as a number the *server* derived. These components format
 * nothing and add nothing -- `src/test/no-browser-arithmetic.test.ts` is what keeps that
 * true.
 */

const CHART_TONES = 5

function toneColor(tone: number): string {
  // 1-based, wrapping. `var(--chart-n)` and never a literal colour.
  const index = ((tone - 1) % CHART_TONES + CHART_TONES) % CHART_TONES
  return `var(--chart-${index + 1})`
}

function widthPercent(ratio: number): string {
  // Clamped rather than trusted: a ratio above 1 would draw a bar past its row, and a
  // negative one would vanish silently. `Math.min`/`Math.max` on a number the server
  // computed is not parsing an API string -- the guard forbids coercion, not clamping.
  const clamped = Math.max(0, Math.min(1, ratio))
  return `${(clamped * 100).toFixed(2)}%`
}

export function BigNumber({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: string
  hint?: string
  tone?: 'neutral' | 'accent'
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="rounded-lg border bg-card p-4"
    >
      <p className="text-sm text-muted-foreground">{label}</p>
      <p
        className={cn(
          'mt-1 text-2xl font-semibold tabular-nums',
          tone === 'accent' && 'text-[var(--chart-1)]',
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export type BarRow = {
  label: string
  value: string
  /** 0..1, computed by the server. Clamped here, never derived here. */
  ratio: number
  /** 1..5, mapped to --chart-1..5. */
  tone: number
}

export function BarRows({ caption, rows }: { caption: string; rows: BarRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <p className="text-sm font-medium">{caption}</p>
        <p className="mt-2 text-sm text-muted-foreground">Nessun dato nel periodo.</p>
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg border bg-card p-4">
      <table className="w-full text-sm">
        <caption className="mb-2 text-left text-sm font-medium">{caption}</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Voce</th>
            <th scope="col">Valore</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row" className="py-1 pr-3 text-left font-normal">
                {row.label}
              </th>
              <td className="py-1">
                <div className="flex items-center gap-2">
                  <div className="h-2 min-w-24 flex-1 rounded bg-muted">
                    <div
                      data-testid="bar-fill"
                      aria-hidden="true"
                      className="h-2 rounded"
                      style={{
                        width: widthPercent(row.ratio),
                        backgroundColor: toneColor(row.tone),
                      }}
                    />
                  </div>
                  <span className="shrink-0 tabular-nums">{row.value}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export type SparkPoint = {
  label: string
  value: string
  /** 0..1, computed by the server. */
  ratio: number
}

export function Sparkline({
  caption,
  points,
}: {
  caption: string
  points: SparkPoint[]
}) {
  const width = 240
  const height = 48
  // `points.length - 1` is a subtraction on an array length, not on an API value, and it
  // is guarded against a single point -- which would otherwise divide by zero and produce
  // `NaN` coordinates that render as an invisible line.
  const step = points.length > 1 ? width / (points.length - 1) : 0
  const path = points
    .map((point, index) => {
      const x = index * step
      const y = height - Math.max(0, Math.min(1, point.ratio)) * height
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <div className="overflow-x-auto rounded-lg border bg-card p-4">
      <svg
        data-testid="sparkline-svg"
        aria-hidden="true"
        viewBox={`0 0 ${width} ${height}`}
        className="h-12 w-full"
        preserveAspectRatio="none"
      >
        <path
          d={path}
          fill="none"
          stroke="var(--chart-2)"
          strokeWidth={2}
          strokeLinejoin="round"
        />
      </svg>
      <table className="mt-2 w-full text-sm">
        <caption className="mb-2 text-left text-sm font-medium">{caption}</caption>
        <thead>
          <tr>
            {points.map((point) => (
              <th key={point.label} scope="col" className="font-normal text-muted-foreground">
                {point.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {points.map((point) => (
              <td key={point.label} className="tabular-nums">
                {point.value}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 5: Add the eslint override and `typescript` as an explicit dev dependency**

`typescript` is already in `apps/web/devDependencies` at `5.9`, so the new test's `import ts from 'typescript'` needs no install. Add the override for `charts.tsx`, which exports both components and types:

```js
// apps/web/eslint.config.js
  {
    files: ['src/features/dashboard/charts.tsx'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
```

`'off'` rather than `allowExportNames` because the exports are TypeScript *types*, which the rule cannot be told to allow by name.

- [ ] **Step 6: Run the tests and watch them pass**

Run: `cd apps/web && pnpm exec vitest run src/styles/tokens.test.ts src/features/dashboard/charts.test.tsx src/test/no-browser-arithmetic.test.ts && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS.

If a contrast assertion fails, the recorded computed sRGB values and the `color-mix()` expressions have drifted apart. Recompute the five values in a browser (`getComputedStyle(document.documentElement).getPropertyValue('--chart-1')`) and update **both** the expression and the recorded hex in the same commit — the pair is the assertion.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/styles/tokens.css \
        apps/web/src/styles/tokens.test.ts \
        apps/web/src/features/dashboard/charts.tsx \
        apps/web/src/features/dashboard/charts.test.tsx \
        apps/web/src/test/no-browser-arithmetic.test.ts \
        apps/web/eslint.config.js
git commit -m "feat(web): five derived chart tokens, four chart shapes, no library"
```

---
### Task B14: The dashboard page, the period in the URL, and the automations settings page

**Files:**
- Modify: `apps/web/src/lib/api-types.ts` (regenerated)
- Modify: `apps/web/src/lib/query.ts` (`queryKeys.dashboard`, `queryKeys.automations`)
- Create: `apps/web/src/features/dashboard/queries.ts`
- Create: `apps/web/src/features/dashboard/Freshness.tsx`
- Create: `apps/web/src/features/dashboard/CommercialTab.tsx`
- Create: `apps/web/src/features/dashboard/CommercialTab.test.tsx`
- Create: `apps/web/src/features/dashboard/PeriodPicker.tsx`
- Create: `apps/web/src/features/settings/AutomationsPanel.tsx`
- Create: `apps/web/src/features/settings/AutomationsPanel.test.tsx`
- Modify: `apps/web/src/routes/app/index.tsx` (**replaced**, not edited)
- Create: `apps/web/src/routes/app/impostazioni/automazioni.tsx`
- Modify: `apps/web/src/features/documents/queries.ts` (invalidate the dashboard)
- Modify: `apps/web/src/features/deals/queries.ts` (invalidate the dashboard)
- Modify: `apps/web/eslint.config.js`

**Interfaces:**
- Consumes: `BigNumber`, `BarRows`, `BarRow` from `./charts` (Task B13); `GET /api/dashboard/commerciale`, `GET /api/automations`, `PUT /api/automation-config` (Task B12); `QueryErrorBanner`; `toast` from `sonner`.
- Produces:
  - `queryKeys.dashboard(kind: 'commerciale' | 'economica' | 'operativa', params: Record<string, string>)` and `queryKeys.automations()`
  - `apps/web/src/features/dashboard/queries.ts`: `DASHBOARD_STALE_MS = 60_000`, `type CommercialDashboard`, `useCommercialDashboard(periodo: { da: string; a: string })`, `useAutomations()`, `useUpdateAutomationConfig()`
  - `apps/web/src/features/dashboard/PeriodPicker.tsx`: `export function PeriodPicker({ periodo, onChange }: { periodo: Periodo; onChange: (next: Periodo) => void })`, `export type Periodo = { da: string; a: string }`, `export function currentMonth(): Periodo`, `export function presetQuarter(): Periodo`, `export function presetYear(): Periodo`
  - `apps/web/src/features/dashboard/Freshness.tsx`: `export function Freshness({ calcolatoAlle, onRefresh }: { calcolatoAlle: string; onRefresh: () => void })`
  - `apps/web/src/routes/app/index.tsx`: the route with `validateSearch`, three tabs, and `/app/?tab=&da=&a=`
- 6C adds the other two tabs to the same route file and the same `queryKeys.dashboard` factory.

**`/app/` is the first route in this codebase with `validateSearch`.** Nothing in `apps/web/src` uses URL search params today; list filters are component-local `useState`. So the whole route definition is written out here rather than pointed at a neighbour. The period is in the URL because a screenshot or a shared link of a dashboard with no explicit period is a number with no unit (§4).

**The three tabs exist from the first commit, and two of them say why they are empty.** Spec §17's closing line: if slices 3 or 4 slip, the "Economica" tab simply does not exist yet — *"cosa che l'utente capisce, a differenza di una scheda che mostra zeri."* So 6B renders the two unbuilt tabs as a one-sentence explanation, not as a tab full of zeros and not as a missing tab that makes the user wonder.

- [ ] **Step 1: Regenerate the client**

With the API running on `:8000`:

Run: `cd apps/web && pnpm generate:api`
Then: `pnpm exec tsc --noEmit`

Expected: clean. The new paths appear in `src/lib/api-types.ts`; nothing existing breaks, because Task B12 added endpoints rather than changing any.

- [ ] **Step 2: Write the failing tests**

```tsx
// apps/web/src/features/dashboard/CommercialTab.test.tsx
/**
 * §4's tab. Three properties get asserted that a snapshot test would not reach: the figures
 * are rendered as the strings the API sent, the weighted value is labelled a *stima* and
 * never sits in the same total as revenue, and a failed request renders an error rather
 * than an empty dashboard.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CommercialTab } from './CommercialTab'

const fetchMock = vi.fn()

const RESPONSE = {
  periodo: { da: '2026-03-01', a: '2026-03-31' },
  calcolato_alle: '2026-03-15T10:00:00Z',
  pipeline: [
    {
      stage_id: 's1', stage_code: 'lead', stage_nome: 'Lead', posizione: 0,
      numero: 4, valore_totale: '3000.00', senza_valore: 1,
      valore_ponderato: '610.00',
    },
    {
      stage_id: 's2', stage_code: 'offerta', stage_nome: 'Offerta', posizione: 2,
      numero: 1, valore_totale: '500.00', senza_valore: 0,
      valore_ponderato: '250.00',
    },
  ],
  chiusure: {
    vinti: 3, persi: 1, valore_vinto: '15000.00', tasso_conversione: '75.00',
  },
  offerte_in_attesa: [
    {
      document_id: 'd1', titolo: 'Offerta impianti', deal_id: 'x',
      customer_id: null, stato_dal: '2026-02-01', giorni: 42,
    },
  ],
  offerte_in_attesa_totale: 1,
  chiusure_previste_30_giorni: 2,
  chiusure_non_attribuibili: 7,
  offerte_accettate_deal_non_vinto: 2,
}

function renderTab(periodo = { da: '2026-03-01', a: '2026-03-31' }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CommercialTab periodo={periodo} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
})

afterEach(() => vi.restoreAllMocks())

function ok(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

describe('CommercialTab', () => {
  it('renders the pipeline as a table with the values the API sent', async () => {
    fetchMock.mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByRole('table', { name: /pipeline/i })).toBeInTheDocument()
    expect(screen.getByText('Lead')).toBeInTheDocument()
  })

  it('labels the weighted value a stima wherever it appears', async () => {
    // §4: "Etichettata *stima*, in una colonna con un'intestazione diversa da qualunque
    // cifra di fatturato". A weighted pipeline figure read as revenue is the exact
    // confusion this label prevents.
    fetchMock.mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/stima/i)).toBeInTheDocument()
  })

  it('shows deals without a value separately and never as zero', async () => {
    fetchMock.mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/senza valore/i)).toBeInTheDocument()
  })

  it('shows the conversion rate, and shows a dash rather than 0% when it is null', async () => {
    fetchMock.mockResolvedValue(
      ok({ ...RESPONSE, chiusure: { ...RESPONSE.chiusure, tasso_conversione: null } }),
    )
    renderTab()
    // "0%" would say "I lost everything"; null says "nothing closed". Different facts.
    expect(await screen.findByText('—')).toBeInTheDocument()
    expect(screen.queryByText('0,00%')).not.toBeInTheDocument()
  })

  it('declares the deals that cannot be attributed to a period', async () => {
    // §4.1: `chiuso_il` is not backfilled, so the dashboard says so instead of counting
    // those rows as zero or putting them in the wrong month.
    fetchMock.mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/non sono attribuibili/i)).toBeInTheDocument()
    expect(screen.getByText(/7/)).toBeInTheDocument()
  })

  it('shows the age of each pending offer', async () => {
    fetchMock.mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/42 giorni/i)).toBeInTheDocument()
  })

  it('links the inconsistency signal to the filtered document list', async () => {
    fetchMock.mockResolvedValue(ok(RESPONSE))
    renderTab()
    const link = await screen.findByRole('link', { name: /offerta accettata/i })
    expect(link).toHaveAttribute('href', '/app/documenti?solo_deal_non_vinto=true')
  })

  it('renders an error banner and no dashboard when the request fails', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ title: 'Errore', detail: 'Non disponibile' }), {
        status: 500,
        headers: { 'content-type': 'application/problem+json' },
      }),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: /pipeline/i })).not.toBeInTheDocument()
    // The rule from §8.6, applied here too: an empty dashboard drawn after a failure says
    // "there is nothing" when the truth is "I do not know".
    expect(screen.queryByText(/nessun dato/i)).not.toBeInTheDocument()
  })

  it('shows how old the figures are', async () => {
    fetchMock.mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/aggiornato/i)).toBeInTheDocument()
  })
})
```

```tsx
// apps/web/src/features/settings/AutomationsPanel.test.tsx
/**
 * §9.5's third surface: the two rules, their switch, and the last executions with their
 * outcome.
 *
 * The non-executions matter most, so they are what the assertions are about: without them,
 * "it did not fire" and "it was not supposed to fire" are the same empty list.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AutomationsPanel } from './AutomationsPanel'

const fetchMock = vi.fn()

const DESCRIPTION = {
  configurazione: {
    a1_offerta_accettata_vince_deal: true,
    a2_offerta_inviata_avanza_deal: false,
  },
  regole: [
    { codice: 'A1', titolo: 'Offerta accettata → deal vinto', descrizione: 'Sposta il deal.', attiva: true },
    { codice: 'A2', titolo: 'Offerta inviata → il deal avanza', descrizione: 'Mai indietro.', attiva: false },
  ],
  esecuzioni: [
    {
      kind: 'automazione.stage_spostato', occurred_at: '2026-03-10T09:00:00Z',
      deal_id: 'd1', regola: 'A1', motivo: null, payload: { a: 'Vinto' },
    },
    {
      kind: 'automazione.non_eseguita', occurred_at: '2026-03-09T09:00:00Z',
      deal_id: 'd2', regola: 'A1', motivo: 'stage_bersaglio_ambiguo', payload: {},
    },
  ],
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AutomationsPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(DESCRIPTION), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  )
})

afterEach(() => vi.restoreAllMocks())

describe('AutomationsPanel', () => {
  it('lists both rules with their switch reflecting the server state', async () => {
    renderPanel()
    const a1 = await screen.findByRole('switch', { name: /offerta accettata/i })
    const a2 = screen.getByRole('switch', { name: /offerta inviata/i })
    expect(a1).toBeChecked()
    // `false` is a value, not a blank: an off switch must render off, not unset.
    expect(a2).not.toBeChecked()
  })

  it('sends only the rule that changed', async () => {
    renderPanel()
    const a1 = await screen.findByRole('switch', { name: /offerta accettata/i })
    await userEvent.click(a1)

    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(put).toBeDefined()
    expect(JSON.parse(String(put![1].body))).toEqual({
      a1_offerta_accettata_vince_deal: false,
    })
  })

  it('shows a non-execution with its reason in plain Italian', async () => {
    renderPanel()
    // The raw enum value would tell the user nothing; the reason is what they act on.
    expect(await screen.findByText(/più di uno stato «vinto»/i)).toBeInTheDocument()
  })

  it('distinguishes an execution from a non-execution', async () => {
    renderPanel()
    expect(await screen.findByText(/spostato/i)).toBeInTheDocument()
    expect(screen.getByText(/non eseguita/i)).toBeInTheDocument()
  })

  it('renders an error banner rather than an empty rule list on failure', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ title: 'Errore', detail: 'Non disponibile' }), {
        status: 500,
        headers: { 'content-type': 'application/problem+json' },
      }),
    )
    renderPanel()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd apps/web && pnpm exec vitest run src/features/dashboard/CommercialTab.test.tsx src/features/settings/AutomationsPanel.test.tsx`
Expected: `Failed to resolve import "./CommercialTab"` and `"./AutomationsPanel"`.

- [ ] **Step 4: Add the query keys and the hooks**

```ts
// apps/web/src/lib/query.ts -- add to the queryKeys object.
  // The period is part of the key, so switching period is a different cache entry rather
  // than a refetch that briefly shows March's numbers under April's heading.
  dashboard: (kind: 'commerciale' | 'economica' | 'operativa', params: Record<string, string>) =>
    ['dashboard', kind, params] as const,
  automations: () => ['automations'] as const,
```

```ts
// apps/web/src/features/dashboard/queries.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

export type CommercialDashboard = components['schemas']['CommercialDashboard']
export type PipelineStageSummary = components['schemas']['PipelineStageSummary']
export type PendingOffer = components['schemas']['PendingOffer']
export type AutomationsDescription = components['schemas']['AutomationsDescription']
export type AutomationConfigUpdate = components['schemas']['AutomationConfigUpdate']

/**
 * §7.2: 60 seconds, a deliberate override of the 30 000 ms default in `lib/query.ts`.
 * A dashboard aggregates more than a list does, and its answer stays useful longer -- and
 * the response's age is shown on screen, so a stale figure is never a silent one.
 */
export const DASHBOARD_STALE_MS = 60_000

export function useCommercialDashboard(periodo: { da: string; a: string }) {
  return useQuery({
    queryKey: queryKeys.dashboard('commerciale', periodo),
    queryFn: () =>
      unwrap(
        api.GET('/api/dashboard/commerciale', { params: { query: periodo } }),
      ),
    staleTime: DASHBOARD_STALE_MS,
  })
}

export function useAutomations() {
  return useQuery({
    queryKey: queryKeys.automations(),
    queryFn: () => unwrap(api.GET('/api/automations')),
  })
}

export function useUpdateAutomationConfig() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: AutomationConfigUpdate) =>
      unwrap(api.PUT('/api/automation-config', { body })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.automations() })
      // The commercial dashboard's signal count reflects whether A1 has been firing, so a
      // configuration change is a reason to re-read it.
      void client.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success('Configurazione aggiornata')
    },
  })
}
```

```ts
// apps/web/src/features/documents/queries.ts -- in the `onSuccess` of the offer-state
// mutation, next to the existing invalidations:
      // Accepting an offer may move a deal (automation A1), which changes the pipeline,
      // the closures and the inconsistency signal. §7.2: the keys are the ones this file
      // already invalidates, plus the dashboard.
      void client.invalidateQueries({ queryKey: ['dashboard'] })
```

```ts
// apps/web/src/features/deals/queries.ts -- in the `onSuccess` of the move-stage mutation:
      void client.invalidateQueries({ queryKey: ['dashboard'] })
```

Invalidating by the `['dashboard']` prefix rather than by an exact key is deliberate: a mutation cannot know which period the user is looking at, and the prefix covers every cached period and every tab.

- [ ] **Step 5: Write the period picker and the freshness indicator**

```tsx
// apps/web/src/features/dashboard/PeriodPicker.tsx
import { Button } from '@/components/ui/button'

export type Periodo = { da: string; a: string }

/**
 * The period lives in the URL (§4), so these helpers produce plain `YYYY-MM-DD` strings
 * and never `Date` objects: `new Date("2026-03-01")` parses as UTC midnight and formatting
 * it back shifts the day in any zone behind UTC.
 *
 * Built from the browser's local calendar parts, which is the only place in the frontend
 * where a date is constructed at all -- every other date on a dashboard arrives from the
 * API already decided in the emitter's zone.
 */
function iso(year: number, monthIndex: number, day: number): string {
  const month = String(monthIndex + 1).padStart(2, '0')
  return `${year}-${month}-${String(day).padStart(2, '0')}`
}

function lastDayOfMonth(year: number, monthIndex: number): number {
  // Day 0 of the next month is the last day of this one -- no leap-year table needed.
  return new Date(year, monthIndex + 1, 0).getDate()
}

export function currentMonth(): Periodo {
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth()
  return { da: iso(year, month, 1), a: iso(year, month, lastDayOfMonth(year, month)) }
}

export function presetQuarter(): Periodo {
  const now = new Date()
  const year = now.getFullYear()
  const firstMonthOfQuarter = Math.floor(now.getMonth() / 3) * 3
  const lastMonthOfQuarter = firstMonthOfQuarter + 2
  return {
    da: iso(year, firstMonthOfQuarter, 1),
    a: iso(year, lastMonthOfQuarter, lastDayOfMonth(year, lastMonthOfQuarter)),
  }
}

export function presetYear(): Periodo {
  const year = new Date().getFullYear()
  return { da: iso(year, 0, 1), a: iso(year, 11, 31) }
}

export function PeriodPicker({
  periodo,
  onChange,
}: {
  periodo: Periodo
  onChange: (next: Periodo) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-sm text-muted-foreground" htmlFor="periodo-da">
        Dal
      </label>
      <input
        id="periodo-da"
        type="date"
        value={periodo.da}
        onChange={(event) => onChange({ ...periodo, da: event.target.value })}
        className="rounded-md border bg-background px-2 py-1 text-sm"
      />
      <label className="text-sm text-muted-foreground" htmlFor="periodo-a">
        al
      </label>
      <input
        id="periodo-a"
        type="date"
        value={periodo.a}
        onChange={(event) => onChange({ ...periodo, a: event.target.value })}
        className="rounded-md border bg-background px-2 py-1 text-sm"
      />
      <Button variant="ghost" size="sm" onClick={() => onChange(currentMonth())}>
        Mese
      </Button>
      <Button variant="ghost" size="sm" onClick={() => onChange(presetQuarter())}>
        Trimestre
      </Button>
      <Button variant="ghost" size="sm" onClick={() => onChange(presetYear())}>
        Anno
      </Button>
    </div>
  )
}
```

```tsx
// apps/web/src/features/dashboard/Freshness.tsx
import { RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

/**
 * §7.2: the age of the answer is shown, not implied. A number with no age is a number the
 * user believes is instantaneous, and this one can be up to sixty seconds old by design.
 *
 * The minute count re-renders on a 30-second interval, because "aggiornato 4 minuti fa"
 * that stays frozen at "adesso" is worse than no indicator: it makes a stale figure look
 * fresh.
 */
function minutesSince(iso: string): number {
  const elapsedMs = Date.now() - new Date(iso).getTime()
  return Math.max(0, Math.floor(elapsedMs / 60_000))
}

export function Freshness({
  calcolatoAlle,
  onRefresh,
}: {
  calcolatoAlle: string
  onRefresh: () => void
}) {
  const [minutes, setMinutes] = useState(() => minutesSince(calcolatoAlle))

  useEffect(() => {
    setMinutes(minutesSince(calcolatoAlle))
    const timer = setInterval(() => setMinutes(minutesSince(calcolatoAlle)), 30_000)
    return () => clearInterval(timer)
  }, [calcolatoAlle])

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span>
        {minutes === 0
          ? 'Aggiornato adesso'
          : `Aggiornato ${minutes} ${minutes === 1 ? 'minuto' : 'minuti'} fa`}
      </span>
      <Button variant="ghost" size="icon-sm" onClick={onRefresh} aria-label="Ricalcola">
        <RefreshCw className="size-3.5" />
      </Button>
    </div>
  )
}
```

`Date.now() - new Date(iso).getTime()` is a subtraction on two timestamps, and `Math.floor(ms / 60_000)` a division — both on instants, neither on an economic field. `src/test/no-browser-arithmetic.test.ts` (Task B13) bans `Number()`, `parseFloat`, `parseInt` and unary `+`; `new Date(...).getTime()` is none of those, and the ban is scoped to coercion of API values on purpose. **`Freshness.tsx` is the one dashboard module that does arithmetic, and it does it on a clock.** Note this in the test's docstring by adding a line to the "deliberately out of scope" paragraph.

- [ ] **Step 6: Write the commercial tab**

```tsx
// apps/web/src/features/dashboard/CommercialTab.tsx
import { Link } from '@tanstack/react-router'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { BarRows, BigNumber, type BarRow } from './charts'
import { Freshness } from './Freshness'
import { useCommercialDashboard } from './queries'
import type { Periodo } from './PeriodPicker'

/**
 * §4. Pipeline snapshot plus two period measures. Touches no invoice and no hour, which is
 * what lets it ship before slice 3.
 *
 * **Nothing here computes anything.** Every string comes from the API already formatted as
 * a decimal string; the only derived quantity is a bar's `ratio`, and it is derived from
 * the *count* of deals -- an integer the server sent -- never from a money value.
 * `src/test/no-browser-arithmetic.test.ts` is what keeps that true.
 */

const REASON_LABELS: Record<string, string> = {
  stage_bersaglio_assente: 'lo stato «vinto» non esiste',
  stage_bersaglio_ambiguo: 'ci sono più di uno stato «vinto»',
  gia_nello_stato: 'il deal era già nello stato',
  regola_disattivata: 'la regola è disattivata',
}

function euro(value: string): string {
  // Formats the string the API sent. Never `Number(value)`: `Number("0.29") * 100` is
  // 28.999999999999996, and a currency formatter fed a float is how cents disappear.
  // `Intl.NumberFormat` accepts a string for exactly this reason.
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    useGrouping: 'always',
  }).format(value as unknown as number)
}

function percent(value: string | null): string {
  // A dash, not "0,00%": zero per cent means "I lost everything", no closed deals means
  // something else entirely (§4, and slice 4 §7.1's identical rule for the margin).
  if (value === null) return '—'
  return `${value.replace('.', ',')}%`
}

export function CommercialTab({ periodo }: { periodo: Periodo }) {
  const query = useCommercialDashboard(periodo)

  if (query.isError) {
    // No table, no cards, no "nessun dato". An empty dashboard drawn after a failure says
    // "there is nothing" when the truth is "I do not know" (§8.6's rule, applied here).
    return <QueryErrorBanner error={query.error} />
  }
  if (query.isLoading || !query.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  const data = query.data
  // The widest count in the pipeline, used only to scale the bars. An integer from the
  // server, compared with other integers from the server.
  const widest = data.pipeline.reduce((best, row) => (row.numero > best ? row.numero : best), 0)
  const bars: BarRow[] = data.pipeline.map((row, index) => ({
    label: `${row.stage_nome} · ${row.numero}`,
    value: euro(row.valore_totale),
    ratio: widest === 0 ? 0 : row.numero / widest,
    tone: index + 1,
  }))
  const withoutValue = data.pipeline.reduce((total, row) => total + row.senza_valore, 0)

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Freshness calcolatoAlle={data.calcolato_alle} onRefresh={() => void query.refetch()} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <BigNumber label="Deal vinti nel periodo" value={String(data.chiusure.vinti)} />
        <BigNumber label="Deal persi nel periodo" value={String(data.chiusure.persi)} />
        <BigNumber
          label="Tasso di conversione"
          value={percent(data.chiusure.tasso_conversione)}
          hint="vinti su vinti + persi"
        />
        <BigNumber
          label="Valore vinto nel periodo"
          value={euro(data.chiusure.valore_vinto)}
          // §4: it is what the deal *claimed*, not what was invoiced. The two figures live
          // on two pages for this reason, and the hint says so where it cannot be missed.
          hint="valore dichiarato dai deal, non fatturato"
        />
      </div>

      <BarRows caption="Pipeline aperta per stato" rows={bars} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <BigNumber
          label="Valore ponderato (stima)"
          value={euro(
            data.pipeline.length === 0 ? '0.00' : data.pipeline[0]!.valore_ponderato,
          )}
          hint="valore previsto × probabilità — è una stima, non fatturato"
          tone="accent"
        />
        <BigNumber
          label="Deal senza valore"
          value={String(withoutValue)}
          hint="contati, non sommati come zero"
        />
        <BigNumber
          label="Chiusure previste (30 giorni)"
          value={String(data.chiusure_previste_30_giorni)}
        />
        <BigNumber
          label="Offerte inviate in attesa"
          value={String(data.offerte_in_attesa_totale)}
        />
      </div>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Offerte in attesa di risposta</h2>
        {data.offerte_in_attesa.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Nessuna offerta in attesa.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {data.offerte_in_attesa.map((offer) => (
              <li key={offer.document_id} className="flex justify-between gap-4">
                <Link to="/app/documenti/$documentId" params={{ documentId: offer.document_id }}
                      className="truncate hover:underline">
                  {offer.titolo}
                </Link>
                <span className="shrink-0 text-muted-foreground">
                  {offer.giorni === null ? 'data ignota' : `${offer.giorni} giorni`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Segnali</h2>
        <p className="mt-2 text-sm">
          <a
            href="/app/documenti?solo_deal_non_vinto=true"
            className="underline underline-offset-2"
          >
            Offerta accettata, deal non vinto
          </a>
          : <strong>{data.offerte_accettate_deal_non_vinto}</strong>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          È il caso in cui l&apos;automazione «offerta accettata → deal vinto» non è
          scattata. I motivi possibili sono: {Object.values(REASON_LABELS).join(', ')}.
        </p>
        {data.chiusure_non_attribuibili > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            {data.chiusure_non_attribuibili} deal chiusi prima dell&apos;introduzione di
            questa misura <strong>non sono attribuibili</strong> a un periodo e non entrano
            nelle cifre sopra.
          </p>
        )}
      </section>
    </div>
  )
}
```

`euro` passes the API's string straight into `Intl.NumberFormat.format`, which accepts a string and parses it with full decimal precision — this is the shipped project's own approach to money display and it is why no `Number()` appears. The `as unknown as number` cast exists only because the TypeScript lib signature for `format` predates string support; a comment says so at the call site.

- [ ] **Step 7: Write the automations panel and its route**

```tsx
// apps/web/src/features/settings/AutomationsPanel.tsx
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  useAutomations,
  useUpdateAutomationConfig,
  type AutomationConfigUpdate,
} from '@/features/dashboard/queries'

/**
 * §9.5's third observability surface: the two rules, their switch, and the last twenty
 * executions with their outcome -- a query over `activities` by `kind`, never a new table.
 *
 * The non-executions are the reason this page earns its place. Without them, "it did not
 * fire" and "it was not supposed to fire" are the same empty list.
 */

const REASONS: Record<string, string> = {
  stage_bersaglio_assente: 'lo stato bersaglio non esiste',
  stage_bersaglio_ambiguo: 'ci sono più di uno stato «vinto»: l’automazione non indovina',
  gia_nello_stato: 'il deal era già nello stato bersaglio',
  regola_disattivata: 'la regola è disattivata',
}

const FIELD_BY_RULE: Record<string, keyof AutomationConfigUpdate> = {
  A1: 'a1_offerta_accettata_vince_deal',
  A2: 'a2_offerta_inviata_avanza_deal',
}

export function AutomationsPanel() {
  const query = useAutomations()
  const update = useUpdateAutomationConfig()

  if (query.isError) return <QueryErrorBanner error={query.error} />
  if (query.isLoading || !query.data) return <Skeleton className="h-64 w-full" />

  const data = query.data

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Automazioni</h2>
        {data.regole.map((rule) => (
          <div key={rule.codice} className="flex items-start gap-4 rounded-lg border p-4">
            <Switch
              checked={rule.attiva}
              aria-label={rule.titolo}
              onCheckedChange={(next) =>
                // Only the rule that changed is sent. The API reads the body with
                // `exclude_unset=True`, so an omitted field changes nothing -- and `false`
                // is a value, never a blank.
                update.mutate({ [FIELD_BY_RULE[rule.codice]!]: next })
              }
            />
            <div className="min-w-0">
              <p className="text-sm font-medium">{rule.titolo}</p>
              <p className="mt-1 text-xs text-muted-foreground">{rule.descrizione}</p>
            </div>
          </div>
        ))}
      </section>

      <section>
        <h2 className="text-lg font-semibold">Ultime esecuzioni</h2>
        {data.esecuzioni.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Nessuna esecuzione registrata.
          </p>
        ) : (
          <ul className="mt-2 divide-y text-sm">
            {data.esecuzioni.map((run, index) => (
              <li key={`${run.occurred_at}-${index}`} className="py-2">
                <span className="font-medium">
                  {run.kind === 'automazione.stage_spostato'
                    ? 'Deal spostato'
                    : run.kind === 'automazione.non_eseguita'
                      ? 'Non eseguita'
                      : 'Configurazione modificata'}
                </span>
                {run.regola && <span className="text-muted-foreground"> · {run.regola}</span>}
                {run.motivo && (
                  <span className="text-muted-foreground">
                    {' '}
                    · {REASONS[run.motivo] ?? run.motivo}
                  </span>
                )}
                <span className="ml-2 text-xs text-muted-foreground">
                  {new Date(run.occurred_at).toLocaleString('it-IT')}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
```

```tsx
// apps/web/src/routes/app/impostazioni/automazioni.tsx
import { createFileRoute } from '@tanstack/react-router'
import { AutomationsPanel } from '@/features/settings/AutomationsPanel'

export const Route = createFileRoute('/app/impostazioni/automazioni')({
  component: AutomationsPanel,
})
```

Add the link to the settings navigation wherever `routes/app/impostazioni.tsx` lists its sections, following the shape the existing entries use.

- [ ] **Step 8: Replace the dashboard route**

```tsx
// apps/web/src/routes/app/index.tsx -- REPLACED, not edited. The previous contents were a
// placeholder that named this slice.
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { CommercialTab } from '@/features/dashboard/CommercialTab'
import { PeriodPicker, currentMonth, type Periodo } from '@/features/dashboard/PeriodPicker'

/**
 * Three tabs, and the period in the URL.
 *
 * The period is in the URL because a screenshot or a shared link of a dashboard with no
 * explicit period is a number with no unit (§4). This is the first route in this codebase
 * with `validateSearch`, so the whole shape is written out rather than copied from a
 * neighbour that does not exist.
 *
 * `validateSearch` fills in the current month rather than rejecting a bare `/app/`: the
 * dashboard is the landing page, and a 404 on the home screen because a query parameter is
 * missing would be absurd. An *invalid* date, on the other hand, falls back rather than
 * throwing -- the alternative is an unusable home screen after a mistyped bookmark.
 */

const TABS = [
  { id: 'commerciale', label: 'Commerciale' },
  { id: 'economica', label: 'Economica' },
  { id: 'operativa', label: 'Operativa' },
] as const

type TabId = (typeof TABS)[number]['id']

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

type DashboardSearch = { tab: TabId; da: string; a: string }

export const Route = createFileRoute('/app/')({
  validateSearch: (search: Record<string, unknown>): DashboardSearch => {
    const fallback = currentMonth()
    const tab = TABS.some((candidate) => candidate.id === search.tab)
      ? (search.tab as TabId)
      : 'commerciale'
    const da = typeof search.da === 'string' && ISO_DATE.test(search.da) ? search.da : fallback.da
    const a = typeof search.a === 'string' && ISO_DATE.test(search.a) ? search.a : fallback.a
    return { tab, da, a }
  },
  component: Dashboard,
})

function Dashboard() {
  const { tab, da, a } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const periodo: Periodo = { da, a }

  return (
    <div className="space-y-6 p-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <nav className="flex gap-1" aria-label="Dashboard">
          {TABS.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              aria-current={candidate.id === tab ? 'page' : undefined}
              onClick={() =>
                void navigate({ search: (previous) => ({ ...previous, tab: candidate.id }) })
              }
              className={
                candidate.id === tab
                  ? 'rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground'
                  : 'rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted'
              }
            >
              {candidate.label}
            </button>
          ))}
        </nav>
        {tab !== 'operativa' && (
          <PeriodPicker
            periodo={periodo}
            onChange={(next) =>
              void navigate({ search: (previous) => ({ ...previous, ...next }) })
            }
          />
        )}
      </div>

      {tab === 'commerciale' && <CommercialTab periodo={periodo} />}

      {/* §17: if slices 3 and 4 slip, the tab says why it is empty. A tab full of zeros
          would be read as "the business made nothing"; this cannot be misread. Sub-plan 6C
          replaces each of these with its real tab. */}
      {tab === 'economica' && (
        <p className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
          La dashboard economica arriva con la fatturazione e il conto economico. Finché non
          ci sono, mostrare degli zeri sarebbe peggio che non mostrare niente.
        </p>
      )}
      {tab === 'operativa' && (
        <p className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
          La dashboard operativa arriva con il time tracking. Finché non c&apos;è, mostrare
          degli zeri sarebbe peggio che non mostrare niente.
        </p>
      )}
    </div>
  )
}
```

The operational tab takes no period (§6: its figures are the current week and a backlog, the two things that make no sense in the past), which is why `PeriodPicker` is hidden for it.

- [ ] **Step 9: Add the eslint overrides**

```js
// apps/web/eslint.config.js
  {
    files: [
      'src/features/dashboard/queries.ts',
      'src/features/dashboard/PeriodPicker.tsx',
      'src/routes/app/index.tsx',
    ],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
```

- [ ] **Step 10: Run the tests and watch them pass**

Run: `cd apps/web && pnpm exec vitest run && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS. `src/test/no-browser-arithmetic.test.ts` now has real files in scope and must be green — if it flags `CommercialTab.tsx`, the offending line is a coercion that should be a formatter.

- [ ] **Step 11: Commit**

```bash
git add apps/web/src/lib/api-types.ts \
        apps/web/src/lib/query.ts \
        apps/web/src/features/dashboard/ \
        apps/web/src/features/settings/AutomationsPanel.tsx \
        apps/web/src/features/settings/AutomationsPanel.test.tsx \
        apps/web/src/features/documents/queries.ts \
        apps/web/src/features/deals/queries.ts \
        apps/web/src/routes/app/index.tsx \
        apps/web/src/routes/app/impostazioni/automazioni.tsx \
        apps/web/src/routes/app/impostazioni.tsx \
        apps/web/eslint.config.js
git commit -m "feat(web): commercial dashboard with the period in the URL, and the automations page"
```

---

## 6B is done. What it closed

| Item | State after 6B |
|---|---|
| §9 in full | Both rules, inside their trigger's transaction, with four declared reasons for declining and an activity for each |
| The `*_in_transaction` convention | Introduced **with** its AST guard, in adjacent commits |
| §4's dashboard | Shipped, with the signal that cross-checks A1 on the same page |
| **R5** | **Closed for `automation_config`.** Open elsewhere |
| Criteria 7, 8, 9 | Executed |
| Criteria 2, 6, 14 | Executed **on the commercial dashboard**; 6C repeats all three on the two new ones |
| §12's data delta | `deals.chiuso_il`, `documents.stato_dal`, `automation_config`, three new `activities.kind` values, and **no** new `entity_type` — residuo **R13** is untouched, which the spec notes is the first time in four slices that the four-place extension was not needed |
| **R11**, **R14**, **R15** | Untouched, deliberately. Contradictions 13 and 14 give the reasoning |

---
# Sub-plan 6C — Dashboard economica e operativa, prompt MCP

**Before 6C can start, all of this must already be true.** This is the sub-plan with real external dependencies, and none of them has a workaround.

| Prerequisite | How to check | If it is missing |
|---|---|---|
| **Sub-plans 6A and 6B merged** | `packages/core/src/pigrocrm/core/{search,dashboard,automations}/service.py` all exist; `uv run pytest -q` green | Stop. 6C appends to `DashboardService` and to the same routers and tools |
| **Slice 3 in `main`, complete** | `packages/core/src/pigrocrm/core/invoices/service.py` **and** `repository.py` exist and define `InvoiceService.issue` / `annul` | As of this plan's writing, eight of slice 3's twenty-one tasks are merged: `models.py`, `schemas.py`, `totals.py`, `fatturapa.py`, `naming.py`, the fiscal profile, and migrations `0004`/`0005`. The **tables are real**, but there is no `InvoiceService`. Task C3 needs only the tables; Task C4 needs `stato`/`stato_pagamento` to be actually written by something, which means `issue()` |
| **Slice 4 in `main`, both halves 4A and 4B** | `packages/core/src/pigrocrm/core/timetracking/service.py` and `analytics/service.py` exist; `AnalyticsService` defines `period_pnl`, `deal_pnl`, `budget_vs_actual` | Stop for Tasks C1, C4, C5, C6, C7. `packages/core/src/pigrocrm/core/{timetracking,analytics}/` do not exist at all today. **Do not invent them** — every figure on the economic dashboard is returned verbatim by `AnalyticsService`, and a locally invented substitute is precisely the second source of truth this slice exists to prevent |
| **The R1 cure in `main`** | `grep -n "lambda: session" apps/mcp/src/pigrocrm_mcp/__main__.py` returns nothing, and a session is created per call | Stop for Tasks C8, C9, C11. Spec §11.3: this slice depends on the cure and does not work around it. A dashboard tool on a shared session is not a degraded feature, it is a wrong figure — §7.1's one-instant guarantee is a property of the session |
| `period_locks` and the two report fields | `PeriodPnl` carries `periodo_chiuso: bool` and `voci_scritte_in_ritardo: int` | Stop for Task C4. Whether a number can still move is half the value of showing it |
| The migration chain head | `ls packages/core/migrations/versions/` | 6C writes `0009`; check, do not trust the number |

**Slice 5 is *not* a prerequisite, contrary to spec §2 and §17.** The route prefix `/app/` those sections attribute to slice 5 §9.4 is already shipped — `apps/web/src/routes/app.tsx` makes `/app` a real path and `routes/index.tsx` redirects to it. What slice 5 still owns is Vite's `base` and `deploy/nginx/spa.conf`, neither of which this slice touches. Contradiction 6 records the check.

**Task C13 is executable ahead of the rest.** The invoice *search* branch needs only the `Invoice` model, which exists today. It is listed last for narrative reasons, not dependency ones, and its own header says so.

**6C executes §16 criteria 1, 10, 11, 12 and 15, plus 2, 6 and 14 repeated on the two new dashboards.**

---

### Task C1: `AnalyticsService.unbilled_backlog`, and the three period rows §5 needs

**Blocked on: slice 4 (both halves) in `main`.**

**Files:**
- Modify: `packages/core/src/pigrocrm/core/analytics/service.py`
- Modify: `packages/core/src/pigrocrm/core/analytics/schemas.py`
- Modify: `apps/api/src/pigrocrm_api/routers/analytics.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/analytics.py` and `tools/__init__.py`
- Create: `packages/core/tests/test_unbilled_backlog.py`

**Interfaces:**
- Consumes, from slice 4 and **not to be reimplemented**: `AnalyticsService(session)`, `AnalyticsRepository`, `PeriodPnl`, `PnlTotals`, `PeriodPnlQuery`, and slice 4's own `Σ ROUND(ore × tariffa_applicata, 2)` formula for accrued value (its §7.3). `TimeEntry` with `data`, `ore`, `fatturabile`, `invoice_line_id`, `tariffa_applicata`.
- Produces:
  - `UnbilledBacklog(BaseModel)` in `analytics/schemas.py` — `ore_fatturabili_non_fatturate: Decimal` (`max_digits=8, decimal_places=2`), `valore_maturato: Decimal` (`max_digits=12, decimal_places=2`), `voci_senza_tariffa: int`, `voci: int`
  - `AnalyticsService.unbilled_backlog(self, actor: Actor) -> UnbilledBacklog`
  - Three new fields on slice 4's `PeriodPnl`: `valore_maturato: Decimal`, `ore_fatturabili_non_fatturate: Decimal`, `ore_senza_tariffa: int`
  - `GET /api/analytics/backlog` → `UnbilledBacklog`
  - MCP tool `get_unbilled_backlog()`
- Task C7 calls `unbilled_backlog`; Task C4 reads the three new `PeriodPnl` fields.

**Two decisions this task records rather than makes.**

**The method is named `unbilled_backlog`, not `get_unbilled_backlog`.** The spec writes `get_unbilled_backlog` in §6.3 and §11.1; slice 4's approved plan names its analytics methods `period_pnl`, `deal_pnl`, `budget_vs_actual`, with the `get_` prefix belonging to the **MCP tool** names. Following the spec's spelling would put one method in a different naming convention from its three neighbours in the same class. So: service method `unbilled_backlog`, MCP tool `get_unbilled_backlog` — which is exactly the name §11.1 fixes for the tool. Contradiction 2 records it.

**It has a tool, so slice 4's exclusion list does not grow.** Spec §6.3 is explicit: slice 4's architecture test requires every new public method on `AnalyticsService` to have a tool *or* an entry in the ten-name exclusion list, and this one has a tool — so **that list stays exactly its ten names**. Task A11 already asserts this. It is the right outcome: the backlog is the figure an agent can be most useful about, and it is read-only.

**Why a new method rather than reading `period_pnl`.** `period_pnl` returns unbilled hours *for a period*; the operational dashboard needs the total with no period, because "how much do I have to invoice" is not a question about March (§6.3). And its euro value is `Σ ROUND(ore × tariffa_applicata, 2)` — a product of two columns, which §3 forbids a dashboard module from containing. So it belongs to the service that already owns that formula.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_unbilled_backlog.py
"""§6.3's method: the backlog, with no period.

Every figure here is slice 4's formula, called rather than reimplemented. The point of the
method existing at all is that `core/dashboard/` cannot contain
`Σ ROUND(ore × tariffa_applicata, 2)` -- it is a product of two columns, and §3 forbids the
dashboard package any multiplication at all.

The three tests that matter most are the ones about hours with no rate: they are counted
separately, they contribute nothing to the accrued value, and they are never treated as
zero-rate hours. A rate of zero and no rate are different facts (slice 4 §5.1).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.db.base import uuid7

READONLY = Actor(id=uuid7(), type="user", role="readonly")


def test_an_empty_database_returns_zeroes_and_not_none(db_session: Session) -> None:
    """A fresh installation must render, not crash. `None` here would reach the browser as
    an empty card indistinguishable from a failed request."""
    backlog = AnalyticsService(db_session).unbilled_backlog(READONLY)
    assert backlog.ore_fatturabili_non_fatturate == Decimal("0.00")
    assert backlog.valore_maturato == Decimal("0.00")
    assert backlog.voci_senza_tariffa == 0
    assert backlog.voci == 0


def test_it_sums_billable_unbilled_hours_across_every_period(
    db_session: Session, time_entry_factory: object
) -> None:
    """No period. "Quanto ho da fatturare" is not a question about March (§6.3), so an
    entry from two years ago counts exactly as much as one from yesterday."""
    time_entry_factory(data=date(2024, 1, 15), ore="8.00", tariffa="50.000000",
                       fatturabile=True, invoice_line_id=None)
    time_entry_factory(data=date(2026, 8, 1), ore="2.50", tariffa="50.000000",
                       fatturabile=True, invoice_line_id=None)

    backlog = AnalyticsService(db_session).unbilled_backlog(READONLY)
    assert backlog.ore_fatturabili_non_fatturate == Decimal("10.50")
    assert backlog.valore_maturato == Decimal("525.00")
    assert backlog.voci == 2


def test_an_hour_already_bound_to_an_invoice_line_is_not_backlog(
    db_session: Session, time_entry_factory: object
) -> None:
    time_entry_factory(data=date(2026, 8, 1), ore="8.00", tariffa="50.000000",
                       fatturabile=True, invoice_line_id=uuid7())
    backlog = AnalyticsService(db_session).unbilled_backlog(READONLY)
    assert backlog.ore_fatturabili_non_fatturate == Decimal("0.00")
    assert backlog.voci == 0


def test_a_non_billable_hour_is_not_backlog(
    db_session: Session, time_entry_factory: object
) -> None:
    time_entry_factory(data=date(2026, 8, 1), ore="8.00", tariffa="50.000000",
                       fatturabile=False, invoice_line_id=None)
    assert AnalyticsService(db_session).unbilled_backlog(READONLY).voci == 0


def test_hours_without_a_rate_are_counted_and_valued_at_nothing(
    db_session: Session, time_entry_factory: object
) -> None:
    """Slice 4 §5.1 already names this as a figure of its own. A rate of zero and no rate
    are different facts, and treating the second as the first understates the backlog
    with nothing on screen to say so."""
    time_entry_factory(data=date(2026, 8, 1), ore="4.00", tariffa=None,
                       fatturabile=True, invoice_line_id=None)
    time_entry_factory(data=date(2026, 8, 2), ore="1.00", tariffa="100.000000",
                       fatturabile=True, invoice_line_id=None)

    backlog = AnalyticsService(db_session).unbilled_backlog(READONLY)
    assert backlog.ore_fatturabili_non_fatturate == Decimal("5.00")
    assert backlog.valore_maturato == Decimal("100.00")
    assert backlog.voci_senza_tariffa == 1
    assert backlog.voci == 2


def test_the_value_rounds_per_row_then_sums(
    db_session: Session, time_entry_factory: object
) -> None:
    """Slice 4's rule, and the reason it is a rule: three rows at 0.005 differ between
    `Σ ROUND(row)` and `ROUND(Σ exact)` by a cent, which is how a reconciliation stops
    reconciling."""
    for _ in range(3):
        time_entry_factory(data=date(2026, 8, 1), ore="0.10", tariffa="0.050000",
                           fatturabile=True, invoice_line_id=None)
    backlog = AnalyticsService(db_session).unbilled_backlog(READONLY)
    # ROUND(0.005, 2) = 0.01 half-up, three times.
    assert backlog.valore_maturato == Decimal("0.03")


def test_a_soft_deleted_entry_is_not_backlog(
    db_session: Session, time_entry_factory: object
) -> None:
    from datetime import UTC, datetime

    entry = time_entry_factory(data=date(2026, 8, 1), ore="8.00", tariffa="50.000000",
                               fatturabile=True, invoice_line_id=None)
    entry.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert AnalyticsService(db_session).unbilled_backlog(READONLY).voci == 0


def test_the_period_pnl_carries_the_same_three_figures_for_its_period(
    db_session: Session, time_entry_factory: object
) -> None:
    """§5 sources them from `period_pnl`, and slice 4's `PeriodPnl` did not carry them.
    Added to the owning service (§3 permits exactly this), with the **same field names** as
    `DealPnl`: they are the same quantity on a different object, and §5's requirement is
    that the *label* carries the scope -- "nel periodo" on the economic dashboard, "in
    totale" on the operational one -- and that the two are never shown side by side."""
    from pigrocrm.core.analytics.schemas import PeriodPnlQuery

    time_entry_factory(data=date(2026, 3, 10), ore="4.00", tariffa="50.000000",
                       fatturabile=True, invoice_line_id=None)
    time_entry_factory(data=date(2026, 6, 10), ore="4.00", tariffa="50.000000",
                       fatturabile=True, invoice_line_id=None)

    pnl = AnalyticsService(db_session).period_pnl(
        PeriodPnlQuery(da=date(2026, 3, 1), a=date(2026, 3, 31)), READONLY
    )
    assert pnl.ore_fatturabili_non_fatturate == Decimal("4.00")
    assert pnl.valore_maturato == Decimal("200.00")
    assert pnl.ore_senza_tariffa == 0

    # The period-less total sees both.
    backlog = AnalyticsService(db_session).unbilled_backlog(READONLY)
    assert backlog.ore_fatturabili_non_fatturate == Decimal("8.00")


def test_a_readonly_actor_may_read_the_backlog(
    db_session: Session, time_entry_factory: object
) -> None:
    """Slice 4 §11 gives every analytics read to every role; the one admin-only figure is
    the fiscal estimate, which is not this."""
    assert AnalyticsService(db_session).unbilled_backlog(READONLY).voci == 0


def test_unbilled_backlog_is_a_public_method_with_a_tool() -> None:
    """§6.3: slice 4's exclusion list must stay exactly its ten names, which is only true
    if this method has a tool."""
    tools = (
        __import__("pathlib").Path(__file__).resolve().parents[3]
        / "apps" / "mcp" / "src" / "pigrocrm_mcp" / "tools"
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in tools.rglob("*.py"))
    assert ".unbilled_backlog(" in source
```

`time_entry_factory` is slice 4's own fixture. Use whatever name `packages/core/tests/conftest.py` carries after slice 4 lands; if slice 4 provided none, add one **there**, next to slice 4's other time-tracking fixtures, rather than defining a private helper in this file — a second way to build a `TimeEntry` is a second set of defaults to drift.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_unbilled_backlog.py -v`
Expected: `AttributeError: 'AnalyticsService' object has no attribute 'unbilled_backlog'`, and the `PeriodPnl` test fails on the three missing fields.

- [ ] **Step 3: Add the schema**

```python
# packages/core/src/pigrocrm/core/analytics/schemas.py -- append.

class UnbilledBacklog(BaseModel):
    """What is waiting to be invoiced, with no period.

    Separate from `PeriodPnl`'s three same-named fields on purpose (§5): those are the
    period's figures, these are the total. Two different numbers with the same name is the
    fastest way to lose a reader's trust, so the *labels* carry the scope -- "nel periodo"
    on the economic dashboard, "in totale" on the operational one -- and the two are never
    rendered side by side.
    """

    ore_fatturabili_non_fatturate: Decimal = Field(max_digits=8, decimal_places=2)
    # `Σ ROUND(ore × tariffa_applicata, 2)` -- slice 4 §7.3's formula, computed here
    # because §3 forbids `core/dashboard/` any multiplication at all.
    valore_maturato: Decimal = Field(max_digits=12, decimal_places=2)
    # A rate of zero and no rate are different facts (slice 4 §5.1). These rows are in
    # `ore_fatturabili_non_fatturate` and contribute nothing to `valore_maturato`.
    voci_senza_tariffa: int
    voci: int
```

And three fields on slice 4's `PeriodPnl`, placed after `spese_generali`:

```python
    # Added by slice 6 §5: the informative rows the economic dashboard shows under a
    # heading that is not "ricavi", and which enter no margin. Same names as `DealPnl`'s
    # because they are the same quantity on a different object; the scope lives in the
    # label, never in the field name.
    valore_maturato: Decimal = Field(max_digits=12, decimal_places=2)
    ore_fatturabili_non_fatturate: Decimal = Field(max_digits=8, decimal_places=2)
    ore_senza_tariffa: int
```

- [ ] **Step 4: Add the repository aggregate and the service method**

```python
# packages/core/src/pigrocrm/core/analytics/repository.py -- append. Slice 4 owns this
# file; this is one more method on it, using its existing imports.

    def unbilled_backlog(self) -> tuple[Decimal, Decimal, int, int]:
        """`(ore, valore, voci_senza_tariffa, voci)` over every unbilled billable hour.

        No period. `Σ ROUND(ore × tariffa_applicata, 2)` per row and then summed -- slice 4's
        project-wide rounding rule, and the reason this lives here rather than in
        `core/dashboard/`, which §3 forbids any multiplication.

        `tariffa_applicata IS NULL` rows are counted in `ore` and in `voci_senza_tariffa`
        and contribute nothing to `valore`: a missing rate is not a rate of zero.
        """
        rounded = func.round(
            func.cast(TimeEntry.ore, Numeric(20, 6))
            * func.cast(TimeEntry.tariffa_applicata, Numeric(20, 6)),
            2,
        )
        row = self.session.execute(
            select(
                func.coalesce(func.sum(TimeEntry.ore), literal(0)).label("ore"),
                func.coalesce(func.sum(rounded), literal(0)).label("valore"),
                func.count(
                    case((TimeEntry.tariffa_applicata.is_(None), 1))
                ).label("senza_tariffa"),
                func.count(TimeEntry.id).label("voci"),
            ).where(
                TimeEntry.deleted_at.is_(None),
                TimeEntry.fatturabile.is_(True),
                TimeEntry.invoice_line_id.is_(None),
            )
        ).one()
        return (
            Decimal(row.ore).quantize(Decimal("0.01")),
            Decimal(row.valore).quantize(Decimal("0.01")),
            row.senza_tariffa,
            row.voci,
        )
```

```python
# packages/core/src/pigrocrm/core/analytics/service.py -- append. `AnalyticsService` has
# no method named `list`, so the last-method rule does not arise here (slice 4's plan says
# so explicitly); confirm that is still true before appending.

    def unbilled_backlog(self, actor: Actor) -> UnbilledBacklog:
        """The arrears: billable hours not yet on an invoice line, with no period.

        `period_pnl` returns the same quantities *for a period*; this one has none, because
        "how much do I have to invoice" is not a question about March (§6.3). It lives on
        this service and not on a dashboard module because its euro value is
        `Σ ROUND(ore × tariffa_applicata, 2)` -- a product of two columns, which §3 forbids
        `core/dashboard/` from containing at all.

        No authorisation check beyond what every other read on this service does: slice 4
        §11 gives every analytics read to every role, and the one admin-only figure -- the
        fiscal estimate -- is a different method entirely.

        It has an MCP tool (`get_unbilled_backlog`, §11.1), so slice 4 §11's exclusion list
        stays **exactly** its ten names. That is the right outcome: the backlog is the
        figure an agent can be most useful about, and it is read-only.
        """
        ore, valore, senza_tariffa, voci = self.repo.unbilled_backlog()
        return UnbilledBacklog(
            ore_fatturabili_non_fatturate=ore,
            valore_maturato=valore,
            voci_senza_tariffa=senza_tariffa,
            voci=voci,
        )
```

And in `period_pnl`, populate the three new fields from the same repository aggregate restricted to the period. Slice 4's `AnalyticsRepository` already computes unbilled hours for a period for its own `PeriodPnl`; extend that method to return the accrued value and the no-rate count alongside, rather than issuing a second query — one aggregate over `time_entries` per dashboard, not two.

- [ ] **Step 5: Expose it on both adapters**

```python
# apps/api/src/pigrocrm_api/routers/analytics.py -- append. Beside slice 4's analytics
# endpoints, because the method belongs to AnalyticsService (spec §11.2's own note).

@router.get("/backlog", response_model=UnbilledBacklog)
def backlog(session: SessionDep, actor: ActorDep) -> UnbilledBacklog:
    """No period parameter, deliberately: see `AnalyticsService.unbilled_backlog`."""
    return AnalyticsService(session).unbilled_backlog(actor)
```

```python
# apps/mcp/src/pigrocrm_mcp/tools/analytics.py -- append.
def get_unbilled_backlog(context: McpContext) -> dict[str, Any]:
    return (
        AnalyticsService(context.session)
        .unbilled_backlog(context.actor)
        .model_dump(mode="json")
    )
```

```python
# apps/mcp/src/pigrocrm_mcp/tools/__init__.py -- register it.
    @mcp.tool()
    @guard
    def get_unbilled_backlog() -> dict[str, Any]:
        """Le ore fatturabili non ancora finite su una fattura, in **totale** e senza
        periodo: quante ore, il valore maturato corrispondente
        (somma di ore x tariffa, arrotondata per riga), e quante voci non hanno una
        tariffa. Le voci senza tariffa sono contate nelle ore ma valgono zero nel valore
        maturato: tariffa assente e tariffa zero sono cose diverse. Il valore maturato
        **non e' un ricavo** e non entra in nessun margine: il ricavo e' la fattura.
        """
        return analytics_tools.get_unbilled_backlog(context)
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest packages/core/tests/test_unbilled_backlog.py packages/core/tests/test_architecture.py -v`
Expected: PASS, including `test_the_slice4_exclusion_list_is_still_exactly_its_ten_names` from Task A11.

- [ ] **Step 7: Full gate and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add packages/core/src/pigrocrm/core/analytics/ \
        apps/api/src/pigrocrm_api/routers/analytics.py \
        apps/mcp/src/pigrocrm_mcp/tools/analytics.py \
        apps/mcp/src/pigrocrm_mcp/tools/__init__.py \
        packages/core/tests/test_unbilled_backlog.py
git commit -m "feat(analytics): unbilled_backlog with no period, and its tool"
```

---

### Task C2: `ActivityRepository.recent`, and the index a global feed needs

**Not blocked on anything beyond 6B.** `activities` has existed since slice 1.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/activities/models.py` (one index)
- Modify: `packages/core/src/pigrocrm/core/activities/repository.py` (`recent`)
- Create: `packages/core/migrations/versions/0009_dashboard_indexes.py`
- Modify: `packages/core/tests/test_migrations.py`
- Modify: `packages/core/tests/test_activities.py`

**Interfaces:**
- Consumes: `Activity`; `INFLATED`, `build_corpus` (Task A1) for the plan assertion.
- Produces:
  - Index `ix_activities_recent` on `(occurred_at DESC, id DESC)`
  - `ActivityRepository.recent(self, limit: int = 50) -> list[Activity]`
  - Migration `0009` — which Task C13 extends with the tenth trigram index, in the same file
- Task C7 calls `recent`.

**Why an index is needed for a query that already exists in a similar form.** `ActivityRepository.timeline` filters by entity and already orders `occurred_at DESC, id DESC` — **residuo R9 does not concern the timeline.** But the only index is `ix_activities_entity (entity_type, entity_id, occurred_at)`, and a *global* feed ordered by date cannot use it: the ordering column is third. Hence `ix_activities_recent (occurred_at DESC, id DESC)`.

**Fifty rows, not paginated.** A complete history of activity is the entity's own timeline, which already exists. A paginated global feed would be a second way to browse the same rows, with its own cursor to get wrong.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_activities.py -- append to the existing file.

def test_recent_returns_the_newest_activities_across_every_entity(
    db_session: Session
) -> None:
    """§6.1's feed. Across every entity, which is what distinguishes it from `timeline`."""
    from pigrocrm.core.db.base import uuid7

    service = ActivityService(db_session)
    for index in range(5):
        service.record("deal", uuid7(), "created", ADMIN, {"n": index})
    for index in range(3):
        service.record("customer", uuid7(), "updated", ADMIN, {"n": 100 + index})
    db_session.flush()

    rows = ActivityRepository(db_session).recent(limit=4)
    assert len(rows) == 4
    # Newest first, and both entity types present in the newest four.
    assert [row.payload["n"] for row in rows] == [102, 101, 100, 4]


def test_recent_is_bounded_by_its_limit(db_session: Session) -> None:
    from pigrocrm.core.db.base import uuid7

    service = ActivityService(db_session)
    for index in range(60):
        service.record("deal", uuid7(), "created", ADMIN, {"n": index})
    db_session.flush()
    assert len(ActivityRepository(db_session).recent(limit=50)) == 50


def test_recent_orders_totally_so_two_reads_agree(db_session: Session) -> None:
    """`occurred_at` alone is not a total order: entries written in one flush share it to
    the microsecond often enough to matter, and a feed that reorders between reads looks
    like data changing."""
    from pigrocrm.core.db.base import uuid7

    service = ActivityService(db_session)
    for index in range(20):
        service.record("deal", uuid7(), "created", ADMIN, {"n": index})
    db_session.flush()

    repo = ActivityRepository(db_session)
    first = [row.id for row in repo.recent(limit=20)]
    second = [row.id for row in repo.recent(limit=20)]
    assert first == second

```

The plan assertion for this index does **not** live in this file. It needs the 50 000-row
inflated corpus -- on a small `activities` table Postgres picks a sequential scan because it
*is* the cheapest plan -- so it goes where that fixture already exists,
`packages/core/tests/test_search_plan.py`:

```python
# packages/core/tests/test_search_plan.py -- append.

def test_the_global_activity_feed_uses_its_own_index(inflated: Engine) -> None:
    """§6.1 and §7.3: no `Seq Scan` on `activities`. `ix_activities_entity` puts the
    ordering column third and cannot serve a global feed ordered by date, so a dedicated
    `(occurred_at DESC, id DESC)` index has to exist and has to be chosen."""
    from pigrocrm.core.activities.models import Activity
    from pigrocrm.core.actor import Actor
    from pigrocrm.core.activities.service import ActivityService
    from pigrocrm.core.db.base import uuid7

    with session_factory(inflated)() as session:
        service = ActivityService(session)
        for index in range(2000):
            service.record("deal", uuid7(), "created", Actor.system(), {"n": index})
        session.commit()
        session.execute(text("ANALYZE activities"))
        session.commit()

        plan = "\n".join(
            str(row[0])
            for row in session.execute(
                text(
                    "EXPLAIN (ANALYZE) SELECT * FROM activities "
                    "ORDER BY occurred_at DESC, id DESC LIMIT 50"
                )
            ).all()
        )
        session.execute(text("DELETE FROM activities WHERE kind = 'created'"))
        session.commit()

    assert "ix_activities_recent" in plan, plan
    assert "Seq Scan on activities" not in plan, plan
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_activities.py -v`
Expected: `AttributeError: 'ActivityRepository' object has no attribute 'recent'`.

- [ ] **Step 3: Add the index and the method**

```python
# packages/core/src/pigrocrm/core/activities/models.py -- append to __table_args__.
        # §6.1: a *global* feed ordered by date cannot use `ix_activities_entity`, whose
        # ordering column is third. DESC on both columns so the feed's own ORDER BY is a
        # forward scan; `id` breaks the tie, because entries written in one flush share
        # `occurred_at` to the microsecond and a feed that reorders between reads looks
        # like data changing.
        Index(
            "ix_activities_recent",
            desc(column("occurred_at")),
            desc(column("id")),
        ),
```

Add `column, desc` to that file's `from sqlalchemy import ...` line.

```python
# packages/core/src/pigrocrm/core/activities/repository.py -- append, above `by_kind`
# (order within the class does not matter here: this class defines no method named `list`).

    def recent(self, limit: int = 50) -> list[Activity]:
        """The global activity feed of §6.1: newest first, across every entity.

        Not paginated, and fifty rows at most. A complete history of activity is the
        entity's own `timeline`, which already exists; a paginated global feed would be a
        second way to browse the same rows with its own cursor to get wrong.

        Served by `ix_activities_recent`, and `test_search_plan.py` asserts on the plan --
        this query is fast either way on a small table and slow in production, which is the
        combination a latency test cannot catch.
        """
        return list(
            self.session.execute(
                select(Activity)
                .order_by(Activity.occurred_at.desc(), Activity.id.desc())
                .limit(limit)
            ).scalars()
        )
```

- [ ] **Step 4: Write migration 0009**

```python
# packages/core/migrations/versions/0009_dashboard_indexes.py
"""ix_activities_recent, and the tenth trigram index

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-21

Two objects, in one revision because both exist for the same reason: a query this slice
introduces would otherwise be a sequential scan on a table that grows with use.

The `invoices.causale` trigram index is added by Task C13, in the marked section below.
This file applies cleanly with or without it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_activities_recent "
        "ON activities (occurred_at DESC, id DESC)"
    )
    # -- ix_invoices_causale_trgm: written by Task C13, in this same revision. --


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_activities_recent")
```

- [ ] **Step 5: Update `test_migrations.py`**

Add `"ix_activities_recent"` to `HAND_MAINTAINED_INDEXES`, move the two head assertions to `"0009"`, and append:

```python
def test_the_activity_feed_index_is_descending_on_both_columns() -> None:
    """An ascending index would still be used -- backwards -- but the feed's ORDER BY is
    DESC, DESC, and asserting the declared shape is what stops a future "simplification"
    to a single-column ascending index that cannot serve the tie-break."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")
        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            definition = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' AND indexname = 'ix_activities_recent'"
                )
            ).scalar_one()
        engine.dispose()
    assert "occurred_at DESC" in definition, definition
    assert "id DESC" in definition, definition
```

- [ ] **Step 6: Run, gate, commit**

Run: `uv run pytest packages/core/tests/test_activities.py packages/core/tests/test_migrations.py -v`
Expected: PASS.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add packages/core/src/pigrocrm/core/activities/ \
        packages/core/migrations/versions/0009_dashboard_indexes.py \
        packages/core/tests/test_migrations.py \
        packages/core/tests/test_activities.py \
        packages/core/tests/test_search_plan.py
git commit -m "feat(activities): global recent feed with its own descending index"
```

---

### Task C3: The invoice aggregates, in `InvoiceRepository`

**Blocked on: the `invoices` table, which exists today.** Not blocked on `InvoiceService`.

**Files:**
- Modify (or create, if slice 3 has not yet): `packages/core/src/pigrocrm/core/invoices/repository.py`
- Create: `packages/core/tests/test_invoice_aggregates.py`

**Interfaces:**
- Consumes: `Invoice` with `tipo`, `stato`, `stato_pagamento`, `data_emissione`, `data_scadenza`, `imponibile`, `totale`, `deal_id`, `deleted_at` — all verified present in `packages/core/src/pigrocrm/core/invoices/models.py`; `today_local` (Task B1); `PipelineStage`.
- Produces, on `InvoiceRepository`:
  - `sum_da_incassare(self) -> Decimal`
  - `sum_scaduto(self) -> Decimal`
  - `count_emesse_in_periodo(self, da: date, a: date) -> int`
  - `count_deals_invoiced_not_won(self) -> int`
  - `count_scadute_non_incassate(self) -> int`
- Task C4 calls the first three; Task C6 calls the last two.

**Why these live in `InvoiceRepository` and not on `InvoiceService`.** §5's table sources "Da incassare" from `InvoiceService`, but §3 rule 2 is the governing rule: *a single-table `COUNT` or `SUM` is written in the repository of that table — even when the table belongs to another slice.* And there is a concrete cost to the alternative: slice 3 §11 fixes its MCP exclusion list at exactly four names, so a new public method on `InvoiceService` would force either a new tool or an edit to another slice's declared list. Contradiction 4 records it.

**"Da incassare" uses `totale`, and that is not an inconsistency.** Revenue is `Σ imponibile` (slice 4 §7.1, and this slice introduces no third meaning). A receivable is what must arrive in the bank, and that includes VAT — money collected on the State's behalf. Under the *forfettario* regime the two coincide and the difference is unobservable, which is exactly why it is written down now: the same condition and the same answer as slice 4 §7.1.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_invoice_aggregates.py
"""§5.2 and §6.2's invoice-side figures.

The one test that matters most is the last pair: `da_incassare` must follow `totale` and
`fatturato` must follow `imponibile`, and each must **fail** if it followed the other. Under
the forfettario regime the two columns are equal, so a test built only on the shipped
default profile cannot tell a correct implementation from a wrong one -- hence the synthetic
RF01 rows where they diverge (slice 3 §14.8's own reason for that profile existing).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import today_local
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.invoices.repository import InvoiceRepository


@pytest.fixture
def customer(db_session: Session) -> Customer:
    row = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(row)
    db_session.flush()
    return row


def _invoice(
    db_session: Session,
    customer: Customer,
    *,
    tipo: str = "fattura",
    stato: str = "emessa",
    stato_pagamento: str = "da_incassare",
    imponibile: str = "1000.00",
    totale: str = "1220.00",
    data_emissione: date | None = None,
    data_scadenza: date | None = None,
    deal_id: object = None,
) -> Invoice:
    row = Invoice(
        customer_id=customer.id, deal_id=deal_id, tipo=tipo, stato=stato,
        stato_pagamento=stato_pagamento,
        imponibile=Decimal(imponibile), imposta=Decimal("0.00"), bollo=Decimal("0.00"),
        totale=Decimal(totale),
        data_emissione=data_emissione or today_local(),
        data_scadenza=data_scadenza,
        tipo_documento="TD01", divisa="EUR", custom_fields={},
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_da_incassare_sums_totale_over_issued_unpaid_invoices(
    db_session: Session, customer: Customer
) -> None:
    _invoice(db_session, customer, imponibile="1000.00", totale="1220.00")
    _invoice(db_session, customer, imponibile="500.00", totale="610.00")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("1830.00")


def test_da_incassare_follows_totale_and_not_imponibile(
    db_session: Session, customer: Customer
) -> None:
    """The RF01 case: the two columns diverge, so this test fails if the implementation
    picked the wrong one. Under the forfettario they are equal and this is unobservable --
    which is why it is written now (§5.2, slice 4 §7.1's identical argument)."""
    _invoice(db_session, customer, imponibile="1000.00", totale="1220.00")
    total = InvoiceRepository(db_session).sum_da_incassare()
    assert total == Decimal("1220.00")
    assert total != Decimal("1000.00"), "da_incassare must use `totale`, not `imponibile`"


def test_a_paid_invoice_is_not_a_receivable(
    db_session: Session, customer: Customer
) -> None:
    _invoice(db_session, customer, stato_pagamento="incassato")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


def test_a_draft_or_annulled_invoice_is_not_a_receivable(
    db_session: Session, customer: Customer
) -> None:
    _invoice(db_session, customer, stato="bozza")
    _invoice(db_session, customer, stato="annullata")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


def test_a_proforma_is_not_a_receivable(db_session: Session, customer: Customer) -> None:
    """A proforma is not a fiscal document and nobody owes anything on it."""
    _invoice(db_session, customer, tipo="proforma", stato="confermata")
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


def test_a_soft_deleted_invoice_is_not_a_receivable(
    db_session: Session, customer: Customer
) -> None:
    from datetime import UTC, datetime

    row = _invoice(db_session, customer)
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert InvoiceRepository(db_session).sum_da_incassare() == Decimal("0.00")


def test_scaduto_is_the_subset_past_its_due_date(
    db_session: Session, customer: Customer
) -> None:
    """§5.2: "Scaduto" is a **subset** of "Da incassare", shown as one -- indented beneath
    it, never as a second addable line."""
    yesterday = today_local() - timedelta(days=1)
    tomorrow = today_local() + timedelta(days=1)
    _invoice(db_session, customer, totale="1220.00", data_scadenza=yesterday)
    _invoice(db_session, customer, totale="610.00", data_scadenza=tomorrow)

    repo = InvoiceRepository(db_session)
    assert repo.sum_scaduto() == Decimal("1220.00")
    assert repo.sum_da_incassare() == Decimal("1830.00")
    assert repo.sum_scaduto() <= repo.sum_da_incassare()


def test_an_invoice_due_today_is_not_yet_overdue(
    db_session: Session, customer: Customer
) -> None:
    """`data_scadenza < oggi`, strictly. Due today is due today."""
    _invoice(db_session, customer, data_scadenza=today_local())
    assert InvoiceRepository(db_session).sum_scaduto() == Decimal("0.00")


def test_an_invoice_with_no_due_date_is_never_overdue(
    db_session: Session, customer: Customer
) -> None:
    """`data_scadenza` is nullable. `NULL < today` is NULL, not true -- but relying on
    three-valued logic silently is how the opposite gets implemented by accident, so it
    has a test."""
    _invoice(db_session, customer, data_scadenza=None)
    assert InvoiceRepository(db_session).sum_scaduto() == Decimal("0.00")


def test_count_emesse_in_periodo_counts_by_data_emissione(
    db_session: Session, customer: Customer
) -> None:
    _invoice(db_session, customer, data_emissione=date(2026, 3, 10))
    _invoice(db_session, customer, data_emissione=date(2026, 3, 31))
    _invoice(db_session, customer, data_emissione=date(2026, 4, 1))
    assert InvoiceRepository(db_session).count_emesse_in_periodo(
        date(2026, 3, 1), date(2026, 3, 31)
    ) == 2


def test_the_signal_counts_deals_invoiced_but_still_open(
    db_session: Session, customer: Customer, request: pytest.FixtureRequest
) -> None:
    """§6.2's second signal. A `COUNT` across a join, which §3 permits; and it counts
    **deals**, not invoices, because the drill-through lists deals -- so two invoices on one
    open deal is one signal, not two."""
    from pigrocrm.core.actor import Actor
    from pigrocrm.core.deals.models import Deal
    from pigrocrm.core.pipeline.service import PipelineService

    PipelineService(db_session).seed_defaults(Actor(id=None, type="system", role="admin"))
    stages = {s.code: s for s in PipelineService(db_session).list() if s.code is not None}

    open_deal = Deal(nome="Aperto", customer_id=customer.id,
                     pipeline_stage_id=stages["lead"].id, probabilita=50, custom_fields={})
    won_deal = Deal(nome="Vinto", customer_id=customer.id,
                    pipeline_stage_id=stages["vinto"].id, probabilita=100,
                    chiuso_il=today_local(), custom_fields={})
    db_session.add_all([open_deal, won_deal])
    db_session.flush()

    _invoice(db_session, customer, deal_id=open_deal.id)
    _invoice(db_session, customer, deal_id=open_deal.id)
    _invoice(db_session, customer, deal_id=won_deal.id)

    assert InvoiceRepository(db_session).count_deals_invoiced_not_won() == 1


def test_the_overdue_signal_counts_invoices(
    db_session: Session, customer: Customer
) -> None:
    """§6.2's fourth signal. It counts and **sends nothing** -- it is the candidate list of
    slice 5 §7.1's reminders, counted."""
    yesterday = today_local() - timedelta(days=1)
    _invoice(db_session, customer, data_scadenza=yesterday)
    _invoice(db_session, customer, data_scadenza=yesterday, stato_pagamento="incassato")
    assert InvoiceRepository(db_session).count_scadute_non_incassate() == 1
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_invoice_aggregates.py -v`
Expected: `ModuleNotFoundError: No module named 'pigrocrm.core.invoices.repository'` if slice 3 has not created it, otherwise `AttributeError` on each method.

- [ ] **Step 3: Add the aggregates**

```python
# packages/core/src/pigrocrm/core/invoices/repository.py -- five methods. If this file does
# not exist yet, create it with the same `__init__(self, session)` shape every other
# repository in the project uses, and keep any method named `list` LAST in the class.

    def sum_da_incassare(self) -> Decimal:
        """`Σ totale` over issued, unpaid, non-deleted invoices.

        **`totale`, not `imponibile`, and that is not an inconsistency with the revenue
        figure.** Revenue is `Σ imponibile` (slice 4 §7.1, and this slice introduces no
        third meaning); a receivable is what must arrive in the bank, which includes VAT --
        money collected on the State's behalf. Under the forfettario regime the two
        coincide and the difference is unobservable, which is exactly why it is written
        down now: the same condition, and the same answer, as slice 4 §7.1.

        This figure enters **no** margin and never shares a total row with revenue (§5.2).
        """
        return Decimal(
            self.session.scalar(
                select(func.coalesce(func.sum(Invoice.totale), literal(0))).where(
                    Invoice.deleted_at.is_(None),
                    Invoice.tipo == "fattura",
                    Invoice.stato == "emessa",
                    Invoice.stato_pagamento == "da_incassare",
                )
            )
            or 0
        ).quantize(Decimal("0.01"))

    def sum_scaduto(self) -> Decimal:
        """The subset of `sum_da_incassare` past its due date.

        A **subset**, and rendered as one -- indented beneath it, never as a second addable
        line (§5.2). `data_scadenza < today` strictly: an invoice due today is due today,
        not overdue. A `NULL` due date is never overdue, which Postgres's three-valued logic
        gives for free and which has a test anyway, because relying on it silently is how
        the opposite gets implemented by accident.

        `today_local()` and not `CURRENT_DATE`: `CURRENT_DATE` is the database server's day,
        and every date in this product is a day in the emitter's zone (`db/clock.py`).
        """
        return Decimal(
            self.session.scalar(
                select(func.coalesce(func.sum(Invoice.totale), literal(0))).where(
                    Invoice.deleted_at.is_(None),
                    Invoice.tipo == "fattura",
                    Invoice.stato == "emessa",
                    Invoice.stato_pagamento == "da_incassare",
                    Invoice.data_scadenza.is_not(None),
                    Invoice.data_scadenza < today_local(),
                )
            )
            or 0
        ).quantize(Decimal("0.01"))

    def count_emesse_in_periodo(self, da: date, a: date) -> int:
        """A `COUNT` on the same predicate the revenue figure uses, so the two cannot
        describe different sets."""
        return (
            self.session.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.deleted_at.is_(None),
                    Invoice.tipo == "fattura",
                    Invoice.stato == "emessa",
                    Invoice.data_emissione.is_not(None),
                    Invoice.data_emissione >= da,
                    Invoice.data_emissione <= a,
                )
            )
            or 0
        )

    def count_deals_invoiced_not_won(self) -> int:
        """§6.2's second signal: a deal with at least one issued invoice and an `open`
        stage. Almost always the stage left behind -- you do not invoice work you have not
        won.

        Counts **deals**, not invoices: the drill-through lists deals, so two invoices on
        one open deal is one signal, not two. `distinct` is what makes that true.

        A `COUNT` across a join, which §3 permits explicitly; a `SUM` across one it does
        not, and this produces no money figure.
        """
        return (
            self.session.scalar(
                select(func.count(func.distinct(Deal.id)))
                .select_from(Invoice)
                .join(Deal, Deal.id == Invoice.deal_id)
                .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
                .where(
                    Invoice.deleted_at.is_(None),
                    Invoice.tipo == "fattura",
                    Invoice.stato == "emessa",
                    Deal.deleted_at.is_(None),
                    PipelineStage.tipo == "open",
                )
            )
            or 0
        )

    def count_scadute_non_incassate(self) -> int:
        """§6.2's fourth signal: the candidate list of slice 5 §7.1's payment reminders,
        counted. The count **sends nothing** -- and saying so here is the point, because a
        count next to a list of overdue customers is exactly the place someone later adds a
        "send all" button."""
        return (
            self.session.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.deleted_at.is_(None),
                    Invoice.tipo == "fattura",
                    Invoice.stato == "emessa",
                    Invoice.stato_pagamento == "da_incassare",
                    Invoice.data_scadenza.is_not(None),
                    Invoice.data_scadenza < today_local(),
                )
            )
            or 0
        )
```

Imports that file needs: `from datetime import date`, `from decimal import Decimal`, `from sqlalchemy import func, literal, select`, `from pigrocrm.core.db import today_local`, `from pigrocrm.core.deals.models import Deal`, `from pigrocrm.core.invoices.models import Invoice`, `from pigrocrm.core.pipeline.models import PipelineStage`.

- [ ] **Step 4: Run, gate, commit**

Run: `uv run pytest packages/core/tests/test_invoice_aggregates.py -v`
Expected: PASS, thirteen tests.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add packages/core/src/pigrocrm/core/invoices/repository.py \
        packages/core/tests/test_invoice_aggregates.py
git commit -m "feat(invoices): receivable and signal aggregates in the invoice repository"
```

---
### Task C4: The economic dashboard, and criterion 1 in both directions

**Blocked on: slice 3 complete (`InvoiceService.issue`) and slice 4 both halves.**

**Files:**
- Modify: `packages/core/src/pigrocrm/core/dashboard/schemas.py` (`EconomicDashboard`)
- Modify: `packages/core/src/pigrocrm/core/dashboard/service.py` (`get_economic_dashboard`)
- Create: `packages/core/tests/test_dashboard_economic.py`

**Interfaces:**
- Consumes: `AnalyticsService.period_pnl(PeriodPnlQuery(da, a, customer_id=None), actor) -> PeriodPnl` and its fields `chiusi`, `in_corso`, `spese_generali`, `periodo_chiuso`, `voci_scritte_in_ritardo`, plus the three added in Task C1; `PnlTotals` fields `ricavi`, `costi_diretti`, `costo_lavoro`, `margine_lordo`, `margine_percentuale`, `deal`; `InvoiceRepository.{sum_da_incassare,sum_scaduto,count_emesse_in_periodo}` (Task C3).
- Produces:
  - `EconomicDashboard(BaseModel)` — `periodo: Periodo`, `calcolato_alle: datetime`, `pnl: PeriodPnl`, `da_incassare: Decimal`, `scaduto: Decimal`, `fatture_emesse: int`
  - `DashboardService.get_economic_dashboard(self, query: PeriodoQuery, actor: Actor) -> EconomicDashboard`
- Task C8 exposes it; Task C12 renders it.

**`pnl: PeriodPnl` verbatim, not flattened.** §5 says there is **no new aggregate here** and every figure comes from `AnalyticsService` or `InvoiceService`. Re-exposing `PeriodPnl`'s fields one by one into a flat dashboard model would be a place for them to be renamed, reordered, or quietly recombined. Embedding the owning service's own model means the reconciliation of criterion 1 is an identity, not a comparison.

**Three things §5.3 keeps off this page, and each has a reason.** No fiscal estimate — slice 4 §11 reason 4 calls it the product's most sensitive figure, and a dashboard is the screen most likely to end up in a screenshot or a screen share; it stays at `/app/analisi/fiscale`, `admin`, and the dashboard shows **a link, not a number**. No single deal's margin "in evidenza" — choosing which would require ranking customers by margin, the feature slice 4 §13 refuses to enable by inertia. No year-on-year comparison — the right behaviour when the prior period is partly written or closed depends on `period_locks` in a way nobody has exercised, and a wrong comparison is worse than none.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_dashboard_economic.py
"""**Criterion 1.** A dashboard figure reconciles exactly with the service that owns it.

Three reads of the same quantity: the dashboard, `AnalyticsService.period_pnl`, and a direct
`SELECT SUM(imponibile)` on a path that touches no service at all. All three must agree to
the cent, compared as `Decimal` and never as float.

Then the part that makes it a real test rather than a tautology: repeated with the synthetic
**RF01** profile, where `imponibile` and `totale` diverge. `fatturato` must follow
`imponibile` and the test must fail if it follows `totale`; `da_incassare` must follow
`totale` and must fail if it follows `imponibile`. Under the shipped forfettario profile the
two columns are equal, so a suite built only on the default cannot tell a correct
implementation from a wrong one -- which is precisely why slice 3 §14.8 put an RF01 profile
in the fixtures.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.schemas import PeriodPnlQuery
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import session_factory
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.invoices.models import Invoice

READONLY = Actor(id=uuid7(), type="user", role="readonly")
_PREFIX = "ECON"
_DA = date(2026, 3, 1)
_A = date(2026, 3, 31)


@pytest.fixture
def rf01_corpus(db_engine: Engine) -> Iterator[Engine]:
    """Invoices whose `imponibile` and `totale` differ, committed.

    The divergence is the whole point: `1000.00` net at 22% is `1220.00` gross, so a figure
    following the wrong column is off by 220 and the assertion catches it. Under the shipped
    forfettario profile both would be `1000.00` and the test would pass either way.
    """
    factory = session_factory(db_engine)
    with factory() as session:
        customer = Customer(
            ragione_sociale=f"{_PREFIX} Cliente", nazione="IT", custom_fields={}
        )
        session.add(customer)
        session.flush()
        for day, net, gross in ((10, "1000.00", "1220.00"), (20, "500.00", "610.00")):
            session.add(
                Invoice(
                    customer_id=customer.id, tipo="fattura", stato="emessa",
                    stato_pagamento="da_incassare",
                    imponibile=Decimal(net), imposta=Decimal("0.00"),
                    bollo=Decimal("0.00"), totale=Decimal(gross),
                    data_emissione=date(2026, 3, day), tipo_documento="TD01",
                    divisa="EUR", custom_fields={},
                )
            )
        # Outside the period, and must not be counted.
        session.add(
            Invoice(
                customer_id=customer.id, tipo="fattura", stato="emessa",
                stato_pagamento="da_incassare",
                imponibile=Decimal("9999.00"), imposta=Decimal("0.00"),
                bollo=Decimal("0.00"), totale=Decimal("12198.78"),
                data_emissione=date(2026, 4, 1), tipo_documento="TD01",
                divisa="EUR", custom_fields={},
            )
        )
        session.commit()
    try:
        yield db_engine
    finally:
        with factory() as session:
            session.execute(
                delete(Invoice).where(
                    Invoice.customer_id.in_(
                        text(
                            "SELECT id FROM customers WHERE ragione_sociale LIKE "
                            f"'{_PREFIX} %'"
                        )
                    )
                )
            )
            session.execute(
                delete(Customer).where(Customer.ragione_sociale.like(f"{_PREFIX} %"))
            )
            session.commit()


def _dashboard(engine: Engine):
    with session_factory(engine)() as session:
        return DashboardService(session).get_economic_dashboard(
            PeriodoQuery(da=_DA, a=_A), READONLY
        )


def test_the_revenue_equals_the_owning_service_to_the_cent(rf01_corpus: Engine) -> None:
    result = _dashboard(rf01_corpus)
    with session_factory(rf01_corpus)() as session:
        pnl = AnalyticsService(session).period_pnl(
            PeriodPnlQuery(da=_DA, a=_A), READONLY
        )
    assert result.pnl.chiusi.ricavi == pnl.chiusi.ricavi
    assert isinstance(result.pnl.chiusi.ricavi, Decimal)


def test_the_revenue_equals_a_direct_sql_sum_on_an_independent_path(
    rf01_corpus: Engine,
) -> None:
    """A path that touches no service. If the dashboard and the service were both wrong in
    the same way, the two comparisons above would still agree -- this one would not."""
    result = _dashboard(rf01_corpus)
    with session_factory(rf01_corpus)() as session:
        direct = session.execute(
            text(
                "SELECT COALESCE(SUM(imponibile), 0) FROM invoices "
                "WHERE tipo = 'fattura' AND stato = 'emessa' AND deleted_at IS NULL "
                "AND data_emissione BETWEEN :da AND :a"
            ),
            {"da": _DA, "a": _A},
        ).scalar_one()
    total = result.pnl.chiusi.ricavi + result.pnl.in_corso.ricavi
    assert total == Decimal(direct)


def test_the_revenue_follows_imponibile_and_fails_if_it_follows_totale(
    rf01_corpus: Engine,
) -> None:
    """§5.1: `fatturato = Σ imponibile`, and this slice introduces no third meaning."""
    result = _dashboard(rf01_corpus)
    total = result.pnl.chiusi.ricavi + result.pnl.in_corso.ricavi
    assert total == Decimal("1500.00")
    assert total != Decimal("1830.00"), "revenue must follow `imponibile`, not `totale`"


def test_da_incassare_follows_totale_and_fails_if_it_follows_imponibile(
    rf01_corpus: Engine,
) -> None:
    """§5.2, specularly. The two quantities are not interchangeable."""
    result = _dashboard(rf01_corpus)
    # All three invoices are unpaid, including the April one: the receivable has no period.
    assert result.da_incassare == Decimal("14028.78")
    assert result.da_incassare != Decimal("11499.00"), (
        "da_incassare must follow `totale`, not `imponibile`"
    )


def test_the_receivable_has_no_period_and_the_revenue_does(rf01_corpus: Engine) -> None:
    """The asymmetry, made explicit: a receivable outside the period is still owed."""
    result = _dashboard(rf01_corpus)
    assert result.fatture_emesse == 2
    assert result.da_incassare > (result.pnl.chiusi.ricavi + result.pnl.in_corso.ricavi)


def test_scaduto_is_a_subset_of_da_incassare(rf01_corpus: Engine) -> None:
    result = _dashboard(rf01_corpus)
    assert result.scaduto <= result.da_incassare


def test_the_pnl_is_embedded_verbatim_and_not_flattened(rf01_corpus: Engine) -> None:
    """§5: there is no new aggregate on this page. Embedding the owning service's own model
    makes the reconciliation an identity rather than a comparison, and leaves no place for a
    field to be renamed or recombined on the way through."""
    result = _dashboard(rf01_corpus)
    with session_factory(rf01_corpus)() as session:
        pnl = AnalyticsService(session).period_pnl(
            PeriodPnlQuery(da=_DA, a=_A), READONLY
        )
    assert result.pnl == pnl


def test_the_margin_is_reported_in_two_columns_with_no_sum_of_them(
    rf01_corpus: Engine,
) -> None:
    """Slice 4 §7.4: closed and in-progress, and the reportable figure is the first. There
    is deliberately no field holding their sum -- adding a finished job's margin to a
    half-done one produces a figure that is neither, and that moves every week for reasons
    which are not business performance."""
    result = _dashboard(rf01_corpus)
    fields = set(type(result).model_fields)
    assert "margine_totale" not in fields
    assert "margine_complessivo" not in fields
    assert result.pnl.chiusi is not None and result.pnl.in_corso is not None


def test_whether_the_period_can_still_move_is_on_the_response(
    rf01_corpus: Engine,
) -> None:
    """Slice 4 §6.4: the only information that tells a reader whether the number can still
    change. Shown beside the total, never in a footnote."""
    result = _dashboard(rf01_corpus)
    assert isinstance(result.pnl.periodo_chiuso, bool)
    assert isinstance(result.pnl.voci_scritte_in_ritardo, int)


def test_no_fiscal_field_appears_anywhere_on_this_dashboard(
    rf01_corpus: Engine,
) -> None:
    """§5.3: the fiscal estimate stays at /app/analisi/fiscale, admin-only. A dashboard is
    the screen most likely to end up in a screenshot. Checked by field name, not by
    intention -- the same discipline criterion 10 applies to the prompts."""
    result = _dashboard(rf01_corpus)
    rendered = result.model_dump_json()
    for forbidden in (
        "imponibile_fiscale", "imposta_sostitutiva", "contributi", "netto_stimato",
        "coefficiente_redditivita", "aliquota_imposta_sostitutiva", "aliquota_inps",
    ):
        assert forbidden not in rendered, forbidden


def test_an_annulled_invoice_is_in_no_figure(rf01_corpus: Engine) -> None:
    with session_factory(rf01_corpus)() as session:
        session.execute(
            text(
                "UPDATE invoices SET stato = 'annullata' "
                "WHERE data_emissione = :day"
            ),
            {"day": date(2026, 3, 10)},
        )
        session.commit()
    result = _dashboard(rf01_corpus)
    total = result.pnl.chiusi.ricavi + result.pnl.in_corso.ricavi
    assert total == Decimal("500.00")
```

The `sum` in two of those tests adds `chiusi.ricavi` and `in_corso.ricavi`, which slice 4 §7.4 forbids **showing** as one figure. Adding them inside a test to reconcile against a single SQL `SUM` is not showing them: the test is checking that the two columns partition the same rows, which is the property that makes the split honest. The tests say so where they do it.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_dashboard_economic.py -v`
Expected: `AttributeError: 'DashboardService' object has no attribute 'get_economic_dashboard'`.

- [ ] **Step 3: Add the schema**

```python
# packages/core/src/pigrocrm/core/dashboard/schemas.py -- append. Imports gain:
#   from pigrocrm.core.analytics.schemas import PeriodPnl

class EconomicDashboard(BaseModel):
    """§5. **No new aggregate exists on this page.** Every figure comes from
    `AnalyticsService` or from `InvoiceRepository`.

    `pnl` embeds the owning service's own model verbatim rather than flattening its fields
    into this one: a flattened copy is a place for a field to be renamed, reordered or
    quietly recombined, and embedding it makes criterion 1's reconciliation an identity
    instead of a comparison.

    `da_incassare` and `scaduto` are the one pair here that does **not** come from the P&L,
    and they use `totale` rather than `imponibile` because they are a different quantity: a
    receivable is what must arrive in the bank, VAT included -- money collected on the
    State's behalf. Neither enters any margin, and neither shares a total row with revenue
    (§5.2).

    Deliberately absent (§5.3): any fiscal estimate field, any single deal's margin, and any
    comparison with the same period last year.
    """

    periodo: Periodo
    calcolato_alle: datetime
    pnl: PeriodPnl
    # No period: an invoice issued in February and still unpaid is still owed in March.
    da_incassare: Decimal = Field(max_digits=12, decimal_places=2)
    # A subset of `da_incassare`, rendered as one -- indented beneath it, never as a second
    # addable line.
    scaduto: Decimal = Field(max_digits=12, decimal_places=2)
    # A COUNT on the same predicate the revenue figure uses, so the two cannot describe
    # different sets.
    fatture_emesse: int
```

- [ ] **Step 4: Add the service method**

```python
# packages/core/src/pigrocrm/core/dashboard/service.py -- one method, after
# `get_commercial_dashboard`. Imports gain:
#   from pigrocrm.core.analytics.schemas import PeriodPnlQuery
#   from pigrocrm.core.analytics.service import AnalyticsService
#   from pigrocrm.core.dashboard.schemas import EconomicDashboard
#   from pigrocrm.core.invoices.repository import InvoiceRepository
# and __init__ gains:
#   self.analytics = AnalyticsService(session)
#   self.invoices = InvoiceRepository(session)

    def get_economic_dashboard(
        self, query: PeriodoQuery, actor: Actor
    ) -> EconomicDashboard:
        """§5. Composition only: not one figure on this page is computed here.

        `period_pnl` is called with the same `actor` the caller supplied, so its own
        authorisation applies unchanged -- this method adds none and removes none.

        The receivable figures come from `InvoiceRepository` rather than from
        `InvoiceService`: §3 rule 2 puts a single-table `SUM` in that table's repository even
        when the table belongs to another slice, and adding a public method to
        `InvoiceService` would force either a new MCP tool or an edit to slice 3 §11's
        four-name exclusion list.
        """
        periodo = query.resolve()
        calcolato_alle = self._open_snapshot()
        return EconomicDashboard(
            periodo=periodo,
            calcolato_alle=calcolato_alle,
            pnl=self.analytics.period_pnl(
                PeriodPnlQuery(da=periodo.da, a=periodo.a, customer_id=None), actor
            ),
            da_incassare=self.invoices.sum_da_incassare(),
            scaduto=self.invoices.sum_scaduto(),
            fatture_emesse=self.invoices.count_emesse_in_periodo(periodo.da, periodo.a),
        )
```

**Check Task B9 immediately after writing this.** `dashboard/service.py` now imports `AnalyticsService`, whose module imports `Decimal` — but the AST clause is per-file, on *this* file's own imports and BinOps, and this method adds neither. Run the guard to confirm rather than assume:

Run: `uv run pytest packages/core/tests/test_dashboard_no_arithmetic.py -v`
Expected: PASS.

- [ ] **Step 5: Run, gate, commit**

Run: `uv run pytest packages/core/tests/test_dashboard_economic.py -v`
Expected: PASS, eleven tests.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add packages/core/src/pigrocrm/core/dashboard/ \
        packages/core/tests/test_dashboard_economic.py
git commit -m "feat(dashboard): economic dashboard, reconciling to the cent with its owner"
```

---

### Task C5: Hours by day, and the days with none

**Blocked on: slice 4 (4A is enough — `time_entries` and `TimeEntryRepository`).**

**Files:**
- Modify: `packages/core/src/pigrocrm/core/timetracking/repository.py`
- Modify: `packages/core/src/pigrocrm/core/dashboard/schemas.py` (`WeekHours`)
- Create: `packages/core/tests/test_week_hours.py`
- Modify: `packages/core/src/pigrocrm/core/db/clock.py` (`current_week`)

**Interfaces:**
- Consumes: `TimeEntry` with `data`, `ore`, `deleted_at`; `today_local` (Task B1).
- Produces:
  - `db/clock.py`: `current_week(settings: Settings | None = None) -> tuple[date, date]` — Monday to Sunday containing today, in the emitter's zone.
  - `TimeEntryRepository.hours_by_day(self, da: date, a: date) -> dict[date, Decimal]`
  - `dashboard/schemas.py`: `DayHours(BaseModel)` — `giorno: date`, `ore: Decimal`; `WeekHours(BaseModel)` — `da: date`, `a: date`, `giorni: list[DayHours]`, `giorni_senza_ore: list[date]`, `ore_totali: Decimal`
- Task C7 composes it.

**Why the empty days are a first-class field and not something the browser derives.** §6's second row is not statistics: it is the real failure slice 4 §13 names when it refuses a stopwatch — *"non ho mai inserito martedì"*. Deriving it in the browser would mean the browser knowing which days the week has and which the query returned, which is business logic in the frontend and a subtraction on a set. The repository returns the days that have hours; the service turns that into both lists. **The service is `DashboardService`, which may contain no arithmetic** — so the set difference happens in `TimeEntryRepository`, where `WeekHours` is assembled whole.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_week_hours.py
"""§6's first two rows: hours per day in the current week, and the days with none.

The second one is the whole point. Slice 4 §13 refuses a stopwatch and names the real
failure it leaves open -- "I never entered Tuesday" -- and this is the figure that attacks
it. It is also the only figure in this slice with a direct agentic counterpart, the
`ore-da-registrare` prompt of §10.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings
from pigrocrm.core.db import current_week
from pigrocrm.core.timetracking.repository import TimeEntryRepository


def test_current_week_runs_monday_to_sunday(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monday to Sunday, not Sunday to Saturday: Italian working weeks start on Monday,
    and "the days I did not log" is a working-week question."""
    from datetime import UTC, datetime

    import pigrocrm.core.db.clock as clock

    # Wednesday 2026-03-18.
    monkeypatch.setattr(clock, "_now", lambda: datetime(2026, 3, 18, 12, 0, tzinfo=UTC))
    assert current_week(Settings(timezone="Europe/Rome")) == (
        date(2026, 3, 16),
        date(2026, 3, 22),
    )


def test_current_week_on_a_monday_starts_that_day(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    import pigrocrm.core.db.clock as clock

    monkeypatch.setattr(clock, "_now", lambda: datetime(2026, 3, 16, 12, 0, tzinfo=UTC))
    assert current_week(Settings(timezone="Europe/Rome"))[0] == date(2026, 3, 16)


def test_current_week_on_a_sunday_ends_that_day(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    import pigrocrm.core.db.clock as clock

    monkeypatch.setattr(clock, "_now", lambda: datetime(2026, 3, 22, 12, 0, tzinfo=UTC))
    assert current_week(Settings(timezone="Europe/Rome")) == (
        date(2026, 3, 16),
        date(2026, 3, 22),
    )


def test_hours_by_day_sums_per_day(db_session: Session, time_entry_factory: object) -> None:
    time_entry_factory(data=date(2026, 3, 16), ore="4.00")
    time_entry_factory(data=date(2026, 3, 16), ore="3.50")
    time_entry_factory(data=date(2026, 3, 18), ore="8.00")

    week = TimeEntryRepository(db_session).week_hours(date(2026, 3, 16), date(2026, 3, 22))
    by_day = {row.giorno: row.ore for row in week.giorni}
    assert by_day[date(2026, 3, 16)] == Decimal("7.50")
    assert by_day[date(2026, 3, 18)] == Decimal("8.00")
    assert week.ore_totali == Decimal("15.50")


def test_every_day_of_the_week_is_present_even_with_no_hours(
    db_session: Session, time_entry_factory: object
) -> None:
    """A sparkline over a week with three points is a sparkline that lies about the shape of
    the week."""
    time_entry_factory(data=date(2026, 3, 18), ore="8.00")
    week = TimeEntryRepository(db_session).week_hours(date(2026, 3, 16), date(2026, 3, 22))
    assert [row.giorno for row in week.giorni] == [
        date(2026, 3, day) for day in range(16, 23)
    ]
    assert all(isinstance(row.ore, Decimal) for row in week.giorni)


def test_the_days_without_hours_are_listed_by_the_repository(
    db_session: Session, time_entry_factory: object
) -> None:
    """Not derived in the browser: that would be a set difference in the frontend, and
    `DashboardService` -- which is what would otherwise do it server-side -- may contain no
    arithmetic at all (§3)."""
    time_entry_factory(data=date(2026, 3, 16), ore="8.00")
    time_entry_factory(data=date(2026, 3, 20), ore="8.00")
    week = TimeEntryRepository(db_session).week_hours(date(2026, 3, 16), date(2026, 3, 22))
    assert week.giorni_senza_ore == [
        date(2026, 3, 17), date(2026, 3, 18), date(2026, 3, 19),
        date(2026, 3, 21), date(2026, 3, 22),
    ]


def test_a_day_logged_with_zero_hours_still_counts_as_logged(
    db_session: Session, time_entry_factory: object
) -> None:
    """`0` is a value, never a blank -- the backend mirror of the frontend rule. Somebody
    who entered a zero-hour day made a statement about it; the dashboard must not tell them
    they forgot."""
    time_entry_factory(data=date(2026, 3, 17), ore="0.00")
    week = TimeEntryRepository(db_session).week_hours(date(2026, 3, 16), date(2026, 3, 22))
    assert date(2026, 3, 17) not in week.giorni_senza_ore


def test_a_soft_deleted_entry_does_not_make_a_day_count_as_logged(
    db_session: Session, time_entry_factory: object
) -> None:
    from datetime import UTC, datetime

    entry = time_entry_factory(data=date(2026, 3, 17), ore="8.00")
    entry.deleted_at = datetime.now(UTC)
    db_session.flush()
    week = TimeEntryRepository(db_session).week_hours(date(2026, 3, 16), date(2026, 3, 22))
    assert date(2026, 3, 17) in week.giorni_senza_ore


def test_hours_outside_the_window_are_excluded(
    db_session: Session, time_entry_factory: object
) -> None:
    time_entry_factory(data=date(2026, 3, 15), ore="8.00")
    time_entry_factory(data=date(2026, 3, 23), ore="8.00")
    week = TimeEntryRepository(db_session).week_hours(date(2026, 3, 16), date(2026, 3, 22))
    assert week.ore_totali == Decimal("0.00")
    assert len(week.giorni_senza_ore) == 7


def test_an_empty_week_returns_seven_zero_days_and_not_an_empty_list(
    db_session: Session
) -> None:
    week = TimeEntryRepository(db_session).week_hours(date(2026, 3, 16), date(2026, 3, 22))
    assert len(week.giorni) == 7
    assert week.ore_totali == Decimal("0.00")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_week_hours.py -v`
Expected: `ImportError: cannot import name 'current_week'`.

- [ ] **Step 3: Add `current_week`**

```python
# packages/core/src/pigrocrm/core/db/clock.py -- append.
def current_week(settings: Settings | None = None) -> tuple[date, date]:
    """Monday to Sunday, both inclusive, containing today in the emitter's zone.

    Monday and not Sunday: an Italian working week starts on Monday, and "which days did I
    not log" is a working-week question. `isoweekday()` returns 1 for Monday, so the offset
    back to Monday is `isoweekday() - 1`.
    """
    today = today_local(settings)
    monday = today - timedelta(days=today.isoweekday() - 1)
    return monday, monday + timedelta(days=6)
```

Add `current_week` to `db/__init__.py`'s imports and `__all__`.

- [ ] **Step 4: Add the schemas and the repository method**

```python
# packages/core/src/pigrocrm/core/dashboard/schemas.py -- append.

class DayHours(BaseModel):
    giorno: date
    ore: Decimal = Field(max_digits=8, decimal_places=2)


class WeekHours(BaseModel):
    """§6's first two rows, assembled whole by `TimeEntryRepository`.

    `giorni` always holds seven entries, including the zero ones: a sparkline over a week
    with three points lies about the shape of the week. `giorni_senza_ore` is a field and
    not something the client derives -- deriving it would put a set difference in the
    browser, and the alternative server-side home for it, `DashboardService`, may contain no
    arithmetic at all (§3).
    """

    da: date
    a: date
    giorni: list[DayHours]
    # The real failure slice 4 §13 names when it refuses a stopwatch: "I never entered
    # Tuesday". A day logged with `0.00` hours is **not** in this list -- somebody who
    # entered a zero made a statement about that day.
    giorni_senza_ore: list[date]
    ore_totali: Decimal = Field(max_digits=10, decimal_places=2)
```

```python
# packages/core/src/pigrocrm/core/timetracking/repository.py -- append, ABOVE any method
# named `list`. Imports gain:
#   from datetime import date, timedelta
#   from decimal import Decimal
#   from pigrocrm.core.dashboard.schemas import DayHours, WeekHours

    def week_hours(self, da: date, a: date) -> WeekHours:
        """`SUM(ore) GROUP BY data` over the window, filled out to every day in it.

        Assembled here rather than in the dashboard for two reasons: it is a single-table
        `SUM`, which §3 puts in this table's repository, and computing "the days with no
        hours" is a set difference -- which `DashboardService` is forbidden from containing
        (§3, and `test_dashboard_no_arithmetic.py`).

        A day present in the grouped result with `0.00` hours counts as **logged**: `0` is a
        value, never a blank, and telling somebody who entered a zero that they forgot is
        the one way this figure can be actively unhelpful.
        """
        rows = self.session.execute(
            select(TimeEntry.data, func.coalesce(func.sum(TimeEntry.ore), literal(0)))
            .where(
                TimeEntry.deleted_at.is_(None),
                TimeEntry.data >= da,
                TimeEntry.data <= a,
            )
            .group_by(TimeEntry.data)
        ).all()
        logged: dict[date, Decimal] = {
            row[0]: Decimal(row[1]).quantize(Decimal("0.01")) for row in rows
        }

        span = (a - da).days + 1
        days = [da + timedelta(days=offset) for offset in range(span)]
        giorni = [
            DayHours(giorno=day, ore=logged.get(day, Decimal("0.00"))) for day in days
        ]
        return WeekHours(
            da=da,
            a=a,
            giorni=giorni,
            giorni_senza_ore=[day for day in days if day not in logged],
            ore_totali=sum(
                (row.ore for row in giorni), start=Decimal("0.00")
            ).quantize(Decimal("0.01")),
        )
```

- [ ] **Step 5: Run, gate, commit**

Run: `uv run pytest packages/core/tests/test_week_hours.py packages/core/tests/test_clock.py -v`
Expected: PASS.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add packages/core/src/pigrocrm/core/db/clock.py \
        packages/core/src/pigrocrm/core/db/__init__.py \
        packages/core/src/pigrocrm/core/timetracking/repository.py \
        packages/core/src/pigrocrm/core/dashboard/schemas.py \
        packages/core/tests/test_week_hours.py
git commit -m "feat(timetracking): hours per day and the days with none, assembled whole"
```

---

### Task C6: The operational dashboard, with its three remaining signals

**Blocked on: Tasks C1, C3, C5 (so: slices 3 and 4 both).**

**Files:**
- Modify: `packages/core/src/pigrocrm/core/dashboard/schemas.py` (`OperationalDashboard`, `Signal`)
- Modify: `packages/core/src/pigrocrm/core/dashboard/service.py` (`get_operational_dashboard`)
- Modify: `packages/core/src/pigrocrm/core/timetracking/repository.py` (`count_won_deals_to_invoice`)
- Create: `packages/core/tests/test_dashboard_operational.py`

**Interfaces:**
- Consumes: `AnalyticsService.unbilled_backlog` (Task C1); `InvoiceRepository.{count_deals_invoiced_not_won,count_scadute_non_incassate}` (Task C3); `TimeEntryRepository.week_hours` (Task C5); `ActivityRepository.recent` (Task C2); `DocumentRepository.count_accepted_with_unwon_deal` (Task B7) — **not used here**, see below.
- Produces:
  - `Signal(BaseModel)` — `codice: str`, `etichetta: str`, `conteggio: int`, `collegamento: str | None`
  - `TimeEntryRepository.count_won_deals_to_invoice(self) -> int`
  - `OperationalDashboard(BaseModel)` — `calcolato_alle: datetime`, `settimana: WeekHours`, `arretrato: UnbilledBacklog`, `segnali: list[Signal]`, `attivita_recenti: list[ActivityRead]`
  - `DashboardService.get_operational_dashboard(self, actor: Actor) -> OperationalDashboard`
- Task C8 exposes it; Task C12 renders it.

**This dashboard takes no period, and that is a decision.** §6: its figures are the current week and a backlog, which are the two things that make no sense in the past. It is also why the backlog cannot come from `period_pnl`, which is by definition of a period (§6.3).

**Three signals here, one on the commercial dashboard.** §6.2 has four; "offerta accettata, deal non vinto" lives on the *commercial* one because it needs no invoices and therefore ships with the automation it cross-checks (§17). The three here are "fatturato ma non vinto", "vinto ma da fatturare" and "scaduto e non incassato". None is stored and none is a flag on a row — they are predicates. **A stored signal is §1's second source of truth in disguise.**

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_dashboard_operational.py
"""§6. "What do I have to do now" -- no new economic total, and no period.

The signals get the most tests because each one is a predicate that must not drift into a
stored flag, and because each one's count is what a human acts on. The fourth signal of
§6.2 is deliberately not here: it lives on the commercial dashboard, with the automation it
cross-checks.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import current_week, session_factory, today_local
from pigrocrm.core.db.base import uuid7

READONLY = Actor(id=uuid7(), type="user", role="readonly")


def _dashboard(engine: Engine):
    with session_factory(engine)() as session:
        return DashboardService(session).get_operational_dashboard(READONLY)


def test_it_takes_no_period(db_engine: Engine) -> None:
    """§6: the current week and a backlog are the two things that make no sense in the
    past, so there is no period parameter to get wrong."""
    import inspect

    signature = inspect.signature(DashboardService.get_operational_dashboard)
    assert list(signature.parameters) == ["self", "actor"]


def test_the_week_is_the_current_one(db_engine: Engine) -> None:
    result = _dashboard(db_engine)
    assert (result.settimana.da, result.settimana.a) == current_week()
    assert len(result.settimana.giorni) == 7


def test_the_backlog_comes_from_analytics_verbatim(
    db_engine: Engine, time_entry_factory: object
) -> None:
    """§6.3: the backlog is `AnalyticsService`'s, reported field for field. Its euro value
    is a product of two columns, which `core/dashboard/` may not contain."""
    from pigrocrm.core.analytics.service import AnalyticsService

    result = _dashboard(db_engine)
    with session_factory(db_engine)() as session:
        direct = AnalyticsService(session).unbilled_backlog(READONLY)
    assert result.arretrato == direct


def test_the_signals_are_present_with_their_links(db_engine: Engine) -> None:
    result = _dashboard(db_engine)
    codes = [signal.codice for signal in result.segnali]
    assert codes == [
        "fatturato_non_vinto", "vinto_da_fatturare", "scaduto_non_incassato",
    ]
    # Every signal has a drill-through, because a count with no way to see the rows behind
    # it is a number nobody can act on (§6.2, §7.2).
    assert all(signal.collegamento for signal in result.segnali)


def test_the_commercial_signal_is_not_on_this_dashboard(db_engine: Engine) -> None:
    """§6.2 and §17: "offerta accettata, deal non vinto" is the automation's permanent
    cross-check and lives on the commercial dashboard, which needs no invoices -- so it
    shipped with the automation instead of a sub-plan later."""
    result = _dashboard(db_engine)
    assert "offerta_accettata_deal_non_vinto" not in [s.codice for s in result.segnali]


def test_the_invoiced_but_not_won_signal_counts_deals(
    db_engine: Engine, invoiced_open_deal: object
) -> None:
    """You do not invoice work you have not won: almost always the stage left behind."""
    result = _dashboard(db_engine)
    signal = next(s for s in result.segnali if s.codice == "fatturato_non_vinto")
    assert signal.conteggio == 1


def test_the_won_but_to_invoice_signal_counts_deals_with_unbilled_billable_hours(
    db_engine: Engine, won_deal_with_unbilled_hours: object
) -> None:
    """The `da fatturare` state slice 4 §7.3 already defines, counted here rather than
    redefined. A `COUNT` across a join, which §3 permits."""
    result = _dashboard(db_engine)
    signal = next(s for s in result.segnali if s.codice == "vinto_da_fatturare")
    assert signal.conteggio == 1


def test_the_overdue_signal_counts_and_sends_nothing(
    db_engine: Engine, overdue_invoice: object
) -> None:
    """§6.2: it is the candidate list of slice 5 §7.1's reminders, counted. The count sends
    nothing -- asserted by there being no send path reachable from here at all."""
    result = _dashboard(db_engine)
    signal = next(s for s in result.segnali if s.codice == "scaduto_non_incassato")
    assert signal.conteggio == 1
    assert "sollecito" not in result.model_dump_json()


def test_no_signal_is_stored_anywhere(db_engine: Engine) -> None:
    """§6.2's closing line: none of the four is memorised and none is a flag on a row. A
    stored signal is §1's second source of truth in disguise. Asserted structurally: no
    table in the metadata carries a column named after one."""
    from pigrocrm.core.db import Base

    columns = {
        column.name
        for table in Base.metadata.tables.values()
        for column in table.columns
    }
    for forbidden in (
        "fatturato_non_vinto", "vinto_da_fatturare", "scaduto_non_incassato",
        "segnale", "segnali",
    ):
        assert forbidden not in columns, forbidden


def test_the_recent_feed_is_capped_at_fifty(db_engine: Engine) -> None:
    result = _dashboard(db_engine)
    assert len(result.attivita_recenti) <= 50


def test_no_new_economic_total_appears_on_this_page(db_engine: Engine) -> None:
    """§6's own claim, checked by field name: this page adds no economic total. The only
    money on it is `arretrato.valore_maturato`, which is `AnalyticsService`'s and is labelled
    as accrued value, not revenue."""
    result = _dashboard(db_engine)
    fields = set(type(result).model_fields)
    assert "ricavi" not in fields
    assert "margine_lordo" not in fields
    assert "fatturato" not in fields


def test_a_readonly_actor_sees_it(db_engine: Engine) -> None:
    assert _dashboard(db_engine).segnali
```

`invoiced_open_deal`, `won_deal_with_unbilled_hours` and `overdue_invoice` are fixtures this task adds to `packages/core/tests/conftest.py`, each committing its rows on its own session and deleting them in a `finally`, in the shape Task B10's `seeded` fixture establishes. They are fixtures rather than inline setup because Task C14's end-to-end test needs the same three states.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_dashboard_operational.py -v`
Expected: `AttributeError: 'DashboardService' object has no attribute 'get_operational_dashboard'`.

- [ ] **Step 3: Add the missing aggregate**

```python
# packages/core/src/pigrocrm/core/timetracking/repository.py -- append, above any `list`.

    def count_won_deals_to_invoice(self) -> int:
        """§6.2's third signal: deals in a `won` stage with billable, unbilled hours.

        The `da fatturare` state slice 4 §7.3 already defines, counted here rather than
        redefined -- a second definition of "ready to invoice" is a second source of truth
        about when to bill a customer.

        Counts **deals**, not entries: the drill-through lists deals, so a deal with twelve
        unbilled entries is one signal.
        """
        return (
            self.session.scalar(
                select(func.count(func.distinct(Deal.id)))
                .select_from(TimeEntry)
                .join(Deal, Deal.id == TimeEntry.deal_id)
                .join(PipelineStage, PipelineStage.id == Deal.pipeline_stage_id)
                .where(
                    TimeEntry.deleted_at.is_(None),
                    TimeEntry.fatturabile.is_(True),
                    TimeEntry.invoice_line_id.is_(None),
                    Deal.deleted_at.is_(None),
                    PipelineStage.tipo == "won",
                )
            )
            or 0
        )
```

- [ ] **Step 4: Add the schemas**

```python
# packages/core/src/pigrocrm/core/dashboard/schemas.py -- append. Imports gain:
#   from pigrocrm.core.activities.schemas import ActivityRead
#   from pigrocrm.core.analytics.schemas import UnbilledBacklog

class Signal(BaseModel):
    """One of §6.2's inconsistency counts.

    Not stored, not a flag on a row: a predicate, evaluated on request. A stored signal is
    §1's second source of truth wearing a disguise, and it would need somewhere to be
    recomputed from -- which is the materialised summary §7 refuses.

    `collegamento` is mandatory in practice: a count with no way to see the rows behind it
    is a number nobody can act on, and §7.2's guarantee is that the count and that list are
    the same predicate.
    """

    codice: str
    etichetta: str
    conteggio: int
    collegamento: str | None


class OperationalDashboard(BaseModel):
    """§6. "What do I have to do now."

    **No period.** Its figures are the current week and a backlog, which are the two things
    that make no sense in the past -- and it is why the backlog cannot come from
    `period_pnl`, which is by definition of a period (§6.3).

    **No new economic total.** The only money here is `arretrato.valore_maturato`, which
    belongs to `AnalyticsService` and is labelled accrued value, never revenue.
    """

    calcolato_alle: datetime
    settimana: WeekHours
    arretrato: UnbilledBacklog
    segnali: list[Signal]
    attivita_recenti: list[ActivityRead]
```

- [ ] **Step 5: Add the service method**

```python
# packages/core/src/pigrocrm/core/dashboard/service.py -- one method. Imports gain:
#   from pigrocrm.core.activities.repository import ActivityRepository
#   from pigrocrm.core.activities.schemas import ActivityRead
#   from pigrocrm.core.dashboard.schemas import OperationalDashboard, Signal
#   from pigrocrm.core.db import current_week
#   from pigrocrm.core.timetracking.repository import TimeEntryRepository
# and __init__ gains:
#   self.entries = TimeEntryRepository(session)
#   self.activities = ActivityRepository(session)

_RECENT_ACTIVITIES = 50

    def get_operational_dashboard(self, actor: Actor) -> OperationalDashboard:
        """§6. No period parameter, deliberately -- see `OperationalDashboard`.

        The three signals are built here as `Signal` rows, which is composition and not
        arithmetic: each `conteggio` is a `COUNT` its own repository produced, and the
        labels and links are literals. `core/dashboard/` still contains no `*`, `/` or `-`,
        and `test_dashboard_no_arithmetic.py` is what confirms it.

        The fourth signal of §6.2 is not here: "offerta accettata, deal non vinto" is on the
        commercial dashboard, because it needs no invoices and therefore shipped with the
        automation it cross-checks (§17).
        """
        da, a = current_week()
        calcolato_alle = self._open_snapshot()
        return OperationalDashboard(
            calcolato_alle=calcolato_alle,
            settimana=self.entries.week_hours(da, a),
            arretrato=self.analytics.unbilled_backlog(actor),
            segnali=[
                Signal(
                    codice="fatturato_non_vinto",
                    etichetta="Fatturato ma non vinto",
                    conteggio=self.invoices.count_deals_invoiced_not_won(),
                    collegamento="/app/deal/lista?fatturato_non_vinto=true",
                ),
                Signal(
                    codice="vinto_da_fatturare",
                    etichetta="Vinto ma da fatturare",
                    conteggio=self.entries.count_won_deals_to_invoice(),
                    collegamento="/app/deal/lista?da_fatturare=true",
                ),
                Signal(
                    codice="scaduto_non_incassato",
                    etichetta="Scaduto e non incassato",
                    conteggio=self.invoices.count_scadute_non_incassate(),
                    collegamento="/app/fatture?scadute=true",
                ),
            ],
            attivita_recenti=[
                ActivityRead.model_validate(row)
                for row in self.activities.recent(_RECENT_ACTIVITIES)
            ],
        )
```

**The three `collegamento` values name query parameters that do not exist yet.** Criterion 2 binds every card *that has a link*, so each of these three filters must exist and must share its predicate with the count — exactly as Task B11 did for the commercial signal. Add them in this task, in the same shape:

- `DealListQuery.fatturato_non_vinto: bool = False` → `DealRepository.list` joins `invoices` and `pipeline_stages` with the predicate extracted from `InvoiceRepository.count_deals_invoiced_not_won` into a module-level `_invoiced_not_won_predicate()`;
- `DealListQuery.da_fatturare: bool = False` → the predicate extracted from `TimeEntryRepository.count_won_deals_to_invoice` into `_won_with_unbilled_hours_predicate()`;
- `InvoiceListQuery.scadute: bool = False` → the predicate extracted from `InvoiceRepository.count_scadute_non_incassate` into `_overdue_predicate()`.

Then extend Task B11's `test_dashboard_drillthrough.py` with one equality test per signal, in the shape it already uses, and add each parameter to its router.

- [ ] **Step 6: Run, gate, commit**

Run: `uv run pytest packages/core/tests/test_dashboard_operational.py packages/core/tests/test_dashboard_drillthrough.py packages/core/tests/test_dashboard_no_arithmetic.py -v`
Expected: PASS.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add packages/core/src/pigrocrm/core/dashboard/ \
        packages/core/src/pigrocrm/core/timetracking/repository.py \
        packages/core/src/pigrocrm/core/invoices/repository.py \
        packages/core/src/pigrocrm/core/deals/ \
        packages/core/src/pigrocrm/core/invoices/schemas.py \
        apps/api/src/pigrocrm_api/routers/ \
        packages/core/tests/test_dashboard_operational.py \
        packages/core/tests/test_dashboard_drillthrough.py \
        packages/core/tests/conftest.py
git commit -m "feat(dashboard): operational dashboard with three predicate signals"
```

---
### Task C7: The two new dashboards on both adapters, and criteria 2, 6 and 14 repeated

**Blocked on: Tasks C4 and C6, and the R1 cure in `main` for the MCP half.**

**Files:**
- Modify: `apps/api/src/pigrocrm_api/routers/dashboard.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/dashboard.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`
- Modify: `packages/core/tests/test_dashboard_snapshot.py` (criterion 6 on both)
- Modify: `packages/core/tests/test_dashboard_drillthrough.py` (criterion 2 on both)
- Modify: `apps/api/tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `DashboardService.get_economic_dashboard(query: PeriodoQuery, actor: Actor) -> EconomicDashboard` (Task C4); `DashboardService.get_operational_dashboard(actor: Actor) -> OperationalDashboard` (Task C6).
- Produces:
  - `GET /api/dashboard/economica?da=&a=` → `EconomicDashboard`
  - `GET /api/dashboard/operativa` → `OperationalDashboard` (**no** period parameter)
  - MCP tools `get_economic_dashboard(da: str | None, a: str | None)` and `get_operational_dashboard()`
  - `_run_with_a_commit_in_the_middle` in `test_dashboard_snapshot.py` gains a `dashboard` parameter so all three dashboards run through the same barrier
- Task C10 asserts ten of these concurrently; Task C11 renders them.

**Criteria 2, 6 and 14 are repeated here and not assumed.** 6B executed all three on the commercial dashboard because they are criteria for *every* dashboard and fell due with the first one. Two new dashboards means two new snapshots to prove, two new sets of linked cards to reconcile, and two new frontend modules for the AST guard to cover — the third of those arrives with Task C11.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_dashboard_api.py -- append.

def test_the_economic_dashboard_is_one_request(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    response = client.get(
        "/api/dashboard/economica", params={"da": "2026-03-01", "a": "2026-03-31"},
        cookies=admin_cookie,
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "periodo", "calcolato_alle", "pnl", "da_incassare", "scaduto", "fatture_emesse",
    }
    # The P&L is embedded verbatim, not flattened -- §5 adds no aggregate to this page.
    assert set(body["pnl"]) >= {
        "chiusi", "in_corso", "spese_generali", "periodo_chiuso",
        "voci_scritte_in_ritardo", "valore_maturato",
        "ore_fatturabili_non_fatturate", "ore_senza_tariffa",
    }


def test_the_economic_dashboard_carries_no_fiscal_field(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    """§5.3: the fiscal estimate stays at /app/analisi/fiscale, admin-only. A dashboard is
    the screen most likely to end up in a screenshot or a screen share."""
    body = client.get("/api/dashboard/economica", cookies=admin_cookie).text
    for forbidden in (
        "imponibile_fiscale", "imposta_sostitutiva", "contributi", "netto_stimato",
    ):
        assert forbidden not in body, forbidden


def test_the_operational_dashboard_takes_no_period(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    """§6: the current week and a backlog are the two things that make no sense in the
    past, so the endpoint has no period parameter at all -- not an optional one."""
    schema = client.get("/openapi.json").json()
    params = schema["paths"]["/api/dashboard/operativa"]["get"].get("parameters", [])
    assert [p["name"] for p in params] == []

    response = client.get("/api/dashboard/operativa", cookies=admin_cookie)
    assert response.status_code == 200
    assert set(response.json()) == {
        "calcolato_alle", "settimana", "arretrato", "segnali", "attivita_recenti",
    }


def test_a_period_on_the_operational_endpoint_is_ignored_not_honoured(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    """A stray `?da=` must not silently produce a period-filtered answer from an endpoint
    that has no period. FastAPI ignores undeclared query parameters, and this pins that."""
    response = client.get(
        "/api/dashboard/operativa", params={"da": "2020-01-01"}, cookies=admin_cookie
    )
    assert response.status_code == 200


def test_every_signal_carries_a_drill_through_link(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    body = client.get("/api/dashboard/operativa", cookies=admin_cookie).json()
    assert [s["codice"] for s in body["segnali"]] == [
        "fatturato_non_vinto", "vinto_da_fatturare", "scaduto_non_incassato",
    ]
    assert all(s["collegamento"] for s in body["segnali"])


def test_money_is_serialised_as_a_string_on_both_new_dashboards(
    client: TestClient, admin_cookie: dict[str, str]
) -> None:
    economic = client.get("/api/dashboard/economica", cookies=admin_cookie).json()
    assert isinstance(economic["da_incassare"], str)
    assert isinstance(economic["pnl"]["chiusi"]["ricavi"], str)

    operational = client.get("/api/dashboard/operativa", cookies=admin_cookie).json()
    assert isinstance(operational["arretrato"]["valore_maturato"], str)


def test_a_readonly_actor_sees_all_three_dashboards(
    client: TestClient, readonly_cookie: dict[str, str]
) -> None:
    """§13: no new role and no new authorisation rule. A readonly sees all three."""
    for path in ("commerciale", "economica", "operativa"):
        assert client.get(
            f"/api/dashboard/{path}", cookies=readonly_cookie
        ).status_code == 200, path
```

```python
# packages/core/tests/test_dashboard_snapshot.py -- replace the helper's signature and add
# two parametrised runs. The three clauses are unchanged; only what is being run changes.

# Replace `_run_with_a_commit_in_the_middle`'s call to the service with a caller-supplied
# one, and add a `first_query_owner` so the barrier hangs off whichever aggregate each
# dashboard calls first:
def _run_with_a_commit_in_the_middle(
    engine: Engine,
    stages: dict,
    customer_id: object,
    monkeypatch: pytest.MonkeyPatch,
    *,
    call: Callable[[DashboardService], object],
    barrier_on: tuple[type, str],
) -> tuple[object, datetime]:
    ...
    original = getattr(barrier_on[0], barrier_on[1])
    state = {"tripped": False}

    def barrier(self: object, *args: object, **kwargs: object) -> object:
        if not state["tripped"]:
            state["tripped"] = True
            reader_reached_first_query.set()
            writer_committed.wait(_BARRIER_TIMEOUT)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(barrier_on[0], barrier_on[1], barrier)
    ...
    with session_factory(engine)() as session:
        result = call(DashboardService(session))
    ...


@pytest.mark.parametrize(
    "call,barrier_on,label",
    [
        (
            lambda service: service.get_commercial_dashboard(PeriodoQuery(), READONLY),
            (DealRepository, "pipeline_summary"),
            "commerciale",
        ),
        (
            lambda service: service.get_economic_dashboard(PeriodoQuery(), READONLY),
            (AnalyticsService, "period_pnl"),
            "economica",
        ),
        (
            lambda service: service.get_operational_dashboard(READONLY),
            (TimeEntryRepository, "week_hours"),
            "operativa",
        ),
    ],
)
def test_clause_a_every_dashboard_runs_in_repeatable_read(
    seeded: tuple[Engine, dict, Customer],
    call: object,
    barrier_on: tuple[type, str],
    label: str,
) -> None:
    """§16 criterion 6 applies to *every* dashboard, not to the first one built."""
    engine, _stages, _customer = seeded
    with session_factory(engine)() as session:
        call(DashboardService(session))  # type: ignore[operator]
        level = session.execute(text("SHOW transaction_isolation")).scalar_one()
    assert level == "repeatable read", label


def test_clause_b_the_economic_dashboard_sees_no_mid_flight_invoice(
    seeded: tuple[Engine, dict, Customer], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The criterion's own wording: "una connessione parallela emette il `COMMIT` di una
    fattura fra la prima e la seconda query interna ... quella fattura non compare in
    **nessuna** cifra della risposta -- ne' nel fatturato ne' nel conteggio."

    So the intruder here is an invoice, and both assertions are made: the revenue figure and
    the count. A test asserting only the total would pass on an implementation that leaked
    the row into the count.
    """
    engine, stages, customer = seeded
    result, _instant = _run_with_a_commit_in_the_middle(
        engine, stages, customer.id, monkeypatch,
        call=lambda service: service.get_economic_dashboard(PeriodoQuery(), READONLY),
        barrier_on=(AnalyticsService, "period_pnl"),
        intruder="invoice",
    )
    assert result.fatture_emesse == 0
    assert result.pnl.chiusi.ricavi + result.pnl.in_corso.ricavi == Decimal("0.00")
```

The writer in `_run_with_a_commit_in_the_middle` gains an `intruder` parameter: `"deal"` inserts the open deal 6B's version used, `"invoice"` inserts an issued invoice dated inside the period. Both are committed at the barrier; the assertion differs per dashboard because each dashboard has a different set of figures the row could leak into.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest apps/api/tests/test_dashboard_api.py packages/core/tests/test_dashboard_snapshot.py -v`
Expected: the new API tests FAIL with `404`; the parametrised snapshot tests FAIL on the missing service methods only if Tasks C4 and C6 are not yet merged — with them merged, they fail on the two missing endpoints alone.

- [ ] **Step 3: Add the endpoints**

```python
# apps/api/src/pigrocrm_api/routers/dashboard.py -- two endpoints, after `commerciale`.
# Imports gain: EconomicDashboard, OperationalDashboard from pigrocrm.core.dashboard.schemas

@router.get("/economica", response_model=EconomicDashboard)
def economica(
    session: SessionDep,
    actor: ActorDep,
    da: Annotated[date | None, Query()] = None,
    a: Annotated[date | None, Query()] = None,
) -> EconomicDashboard:
    return DashboardService(session).get_economic_dashboard(
        PeriodoQuery(da=da, a=a), actor
    )


@router.get("/operativa", response_model=OperationalDashboard)
def operativa(session: SessionDep, actor: ActorDep) -> OperationalDashboard:
    """No period parameter, and not an optional one either.

    §6: its figures are the current week and a backlog, which are the two things that make
    no sense in the past. An optional `da`/`a` that the service ignored would be a
    parameter the API advertises and does not honour -- worse than not having it, because a
    caller would believe it worked.
    """
    return DashboardService(session).get_operational_dashboard(actor)
```

- [ ] **Step 4: Add the tools**

```python
# apps/mcp/src/pigrocrm_mcp/tools/dashboard.py -- append.
def get_economic_dashboard(context: McpContext, query: PeriodoQuery) -> dict[str, Any]:
    return (
        DashboardService(context.session)
        .get_economic_dashboard(query, context.actor)
        .model_dump(mode="json")
    )


def get_operational_dashboard(context: McpContext) -> dict[str, Any]:
    return (
        DashboardService(context.session)
        .get_operational_dashboard(context.actor)
        .model_dump(mode="json")
    )
```

```python
# apps/mcp/src/pigrocrm_mcp/tools/__init__.py -- two tools.
    @mcp.tool()
    @guard
    def get_economic_dashboard(
        da: str | None = None, a: str | None = None
    ) -> dict[str, Any]:
        """La dashboard economica del periodo. `pnl` contiene il conto economico di
        periodo cosi' come lo restituisce AnalyticsService, senza rielaborazioni: ricavi,
        costi diretti, costo del lavoro e margine in **due colonne separate** -- `chiusi` e
        `in_corso` -- piu' `spese_generali`, che non sono ripartite su nessun deal.
        La cifra riportabile e' `chiusi`: sommare il margine di un lavoro finito a quello di
        uno a metà produce un numero che non e' ne' l'uno ne' l'altro. `margine_percentuale`
        e' `null`, non zero, quando i ricavi sono zero. `ricavi` e' la somma degli
        **imponibili** delle fatture emesse e non annullate, attribuite al periodo dalla
        data di emissione: non e' l'incassato e non e' il totale con IVA.
        `da_incassare` e `scaduto` usano invece il **totale** perche' sono crediti e non
        ricavi, non hanno periodo, e non entrano in nessun margine. `periodo_chiuso` e
        `voci_scritte_in_ritardo` dicono se il numero puo' ancora muoversi.
        Nessuna cifra fiscale: la stima fiscale non e' esposta via MCP.
        """
        return dashboard_tools.get_economic_dashboard(
            context,
            PeriodoQuery(
                da=date.fromisoformat(da) if da else None,
                a=date.fromisoformat(a) if a else None,
            ),
        )

    @mcp.tool()
    @guard
    def get_operational_dashboard() -> dict[str, Any]:
        """La dashboard operativa: cosa c'e' da fare adesso. Non prende un periodo.
        `settimana` porta le ore registrate giorno per giorno nella settimana corrente e --
        soprattutto -- `giorni_senza_ore`, i giorni in cui non e' stata registrata
        nessun'ora. Un giorno registrato con `0.00` ore **non** e' fra questi: zero e'
        un valore, non un'assenza. `arretrato` e' il totale delle ore fatturabili non
        ancora fatturate, senza periodo, con il valore maturato corrispondente (che non e'
        un ricavo) e il numero di voci senza tariffa. `segnali` sono tre conteggi di
        incoerenza, ognuno con un collegamento all'elenco delle righe che li compongono;
        contano e non mandano niente.
        """
        return dashboard_tools.get_operational_dashboard(context)
```

- [ ] **Step 5: The R1 gate**

Run: `grep -n "lambda: session\|session_provider" apps/mcp/src/pigrocrm_mcp/__main__.py apps/mcp/src/pigrocrm_mcp/server.py`

`server.py`'s own comment currently documents the shared session and its reason. If it still does, **do not register the two tools** — apply Task A11 Step 6's comment and gate, and note in the commit message that the API half shipped alone. Two concurrent dashboards on one session can each read half their figures inside the other's transaction and produce a total that was never true at any instant; §7.1's guarantee is a property of the session, and there is no version of these tools that is merely degraded rather than wrong.

- [ ] **Step 6: Run, gate, commit**

Run: `uv run pytest apps/api/tests/test_dashboard_api.py apps/mcp/tests/test_mcp_dashboard.py packages/core/tests/test_dashboard_snapshot.py packages/core/tests/test_dashboard_drillthrough.py packages/core/tests/test_architecture.py -v`
Expected: PASS. The architecture test now sees three public methods on `DashboardService`, all three with tools.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add apps/api/src/pigrocrm_api/routers/dashboard.py \
        apps/mcp/src/pigrocrm_mcp/tools/dashboard.py \
        apps/mcp/src/pigrocrm_mcp/tools/__init__.py \
        apps/api/tests/test_dashboard_api.py \
        apps/mcp/tests/test_mcp_dashboard.py \
        packages/core/tests/test_dashboard_snapshot.py \
        packages/core/tests/test_dashboard_drillthrough.py
git commit -m "feat(api): economic and operational dashboards on both adapters"
```

---

### Task C8: The four MCP prompts

**Blocked on: Tasks C4, C6, C7, and the R1 cure in `main`.**

**Files:**
- Create: `apps/mcp/src/pigrocrm_mcp/prompts/__init__.py`
- Create: `apps/mcp/src/pigrocrm_mcp/prompts/dashboards.py`
- Create: `apps/mcp/src/pigrocrm_mcp/prompts/customer.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/server.py` (one registration call)
- Create: `apps/mcp/tests/test_mcp_prompts.py` (Task C9 adds criterion 10's assertions to it)

**Interfaces:**
- Consumes: `DashboardService.{get_commercial_dashboard,get_economic_dashboard,get_operational_dashboard}` (Tasks B8, C4, C6); `AnalyticsService.unbilled_backlog` (Task C1); `DocumentRepository.pending_offers` (Task B7); `InvoiceRepository.sum_scaduto` (Task C3); `entities.render_customer(context, UUID) -> str`; `McpContext`; `month_bounds`, `current_week` (Tasks B1, C5).
- Produces:
  - `register_prompts(mcp: MCPServer, context: McpContext, guard: Callable[[T], T]) -> None`
  - Four prompts, named exactly: `revisione-pipeline`, `chiusura-mese`, `stato-cliente`, `ore-da-registrare`
  - `prompts/dashboards.py`: `def revisione_pipeline(context, da, a) -> list[dict]`, `def chiusura_mese(context, anno, mese) -> list[dict]`, `def ore_da_registrare(context, settimana) -> list[dict]`
  - `prompts/customer.py`: `def stato_cliente(context, customer_id) -> list[dict]`
- Task C9 asserts criterion 10 over these four; Task C13's end-to-end run opens `revisione-pipeline`.

**Why these four are prompts and not tools, stated because it decides their shape.** A tool is invoked by the *model* when it decides it needs one, and returns *data*. A prompt is invoked by the *user*, from a menu, and returns *messages* — the beginning of a conversation. And the judgement lives in a different place: in a tool it is the model's, in a prompt it is written into the prompt (*"segnala solo scostamenti oltre il 10%"*). Each of these four is the composition of several reads **plus a posture on how to read them**. A tool that also returned the posture would be putting instructions inside a data result, which is the shape of an injection; and the model would have to guess it should call it, whereas here the human chooses it and can see what was attached.

**Verified against the installed SDK, not assumed from documentation.** `mcp==2.0.0`: `MCPServer.prompt()` registers a function, its arguments are inferred from the signature exactly as for tools, the function can receive the `Context` — so **it can read the database like a tool** — and a message may contain either text or a `{"type": "resource", ...}` block.

**How the context travels, and it is a rule because §11.1 adds no new resource.** The context travels as **Markdown text inside the message**, and is a resource block **only when the resource already exists** — which means `customer://{id}` (slice 1 §8.4), in `stato-cliente`. A resource block needs a URI, and inventing `dashboard://commerciale?da=…` to have one would be adding a resource without saying so. Either way the property that matters holds: the context **arrives inside the prompt** rather than depending on the model going to fetch it.

- [ ] **Step 1: Write the failing test**

```python
# apps/mcp/tests/test_mcp_prompts.py
"""§10's four prompts. Criterion 10's own assertions are added in Task C9.

What is asserted here is that they exist, that their arguments are inferred from their
signatures, that each one carries its context *inside* the returned messages, and that a
prompt rendered against an empty database produces a valid message rather than an
exception -- the criterion names that last one explicitly, and it is the failure mode of
every "assemble a briefing" function ever written.
"""

from typing import Any

import pytest


async def test_all_four_prompts_are_registered_with_their_names(mcp_server: Any) -> None:
    names = {prompt.name for prompt in await mcp_server.list_prompts()}
    assert names == {
        "revisione-pipeline", "chiusura-mese", "stato-cliente", "ore-da-registrare",
    }


async def test_the_arguments_are_inferred_from_the_signatures(mcp_server: Any) -> None:
    """The SDK infers them exactly as it does for tools, so the signature *is* the schema.
    Pinned because a default moving from optional to required is a silent contract break for
    a menu the user drives."""
    by_name = {prompt.name: prompt for prompt in await mcp_server.list_prompts()}

    pipeline_args = {arg.name: arg.required for arg in by_name["revisione-pipeline"].arguments}
    assert pipeline_args == {"da": False, "a": False}

    month_args = {arg.name: arg.required for arg in by_name["chiusura-mese"].arguments}
    assert month_args == {"anno": True, "mese": True}

    customer_args = {arg.name: arg.required for arg in by_name["stato-cliente"].arguments}
    assert customer_args == {"customer_id": True}

    hours_args = {arg.name: arg.required for arg in by_name["ore-da-registrare"].arguments}
    assert hours_args == {"settimana": False}


async def test_revisione_pipeline_carries_the_dashboard_as_text(
    mcp_server: Any, seeded_pipeline: Any
) -> None:
    """The context arrives *inside* the prompt rather than depending on the model going to
    fetch it -- which is the whole reason these are prompts."""
    rendered = await mcp_server.get_prompt("revisione-pipeline", {})
    text = "\n".join(
        block.text for message in rendered.messages
        for block in ([message.content] if not isinstance(message.content, list) else message.content)
        if getattr(block, "type", None) == "text"
    )
    assert "Pipeline" in text
    assert "Tasso di conversione" in text
    # The posture, which is the half a tool could not carry without becoming an injection.
    assert "fermi" in text.lower()


async def test_revisione_pipeline_lists_the_pending_offers_with_their_age(
    mcp_server: Any, seeded_pipeline: Any
) -> None:
    rendered = await mcp_server.get_prompt("revisione-pipeline", {})
    text = str(rendered.messages)
    assert "giorni" in text


async def test_revisione_pipeline_on_an_empty_database_is_a_valid_message(
    mcp_server: Any
) -> None:
    """§16 criterion 10's last sentence, and the failure mode of every briefing function:
    an empty corpus must render, not raise."""
    rendered = await mcp_server.get_prompt("revisione-pipeline", {})
    assert rendered.messages
    assert all(message.role in ("user", "assistant") for message in rendered.messages)


async def test_chiusura_mese_takes_a_year_and_a_month_and_refuses_month_thirteen(
    mcp_server: Any
) -> None:
    ok = await mcp_server.get_prompt("chiusura-mese", {"anno": 2026, "mese": 3})
    assert ok.messages

    with pytest.raises(Exception):  # noqa: B017 -- the SDK's own error type for a failed prompt
        await mcp_server.get_prompt("chiusura-mese", {"anno": 2026, "mese": 13})


async def test_stato_cliente_embeds_the_existing_resource(
    mcp_server: Any, seeded_customer: Any
) -> None:
    """§10: the **only** prompt with a resource block, because it is the only one whose
    resource already exists. `customer://{id}` is slice 1 §8.4's."""
    rendered = await mcp_server.get_prompt(
        "stato-cliente", {"customer_id": str(seeded_customer.id)}
    )
    uris = [
        str(getattr(block, "resource", block).uri)
        for message in rendered.messages
        for block in ([message.content] if not isinstance(message.content, list) else message.content)
        if getattr(block, "type", None) == "resource"
    ]
    assert uris == [f"customer://{seeded_customer.id}"]


async def test_stato_cliente_also_carries_the_open_deals_as_text(
    mcp_server: Any, seeded_customer: Any
) -> None:
    rendered = await mcp_server.get_prompt(
        "stato-cliente", {"customer_id": str(seeded_customer.id)}
    )
    assert "deal" in str(rendered.messages).lower()


async def test_stato_cliente_on_an_unknown_customer_is_a_domain_error(
    mcp_server: Any
) -> None:
    from uuid import uuid4

    with pytest.raises(Exception):  # noqa: B017
        await mcp_server.get_prompt("stato-cliente", {"customer_id": str(uuid4())})


async def test_ore_da_registrare_names_the_days_with_no_hours(
    mcp_server: Any
) -> None:
    """The prompt §6 calls the most useful in the product: it attacks the "I never entered
    Tuesday" failure slice 4 §13 names when it refuses a stopwatch, and it ends by asking
    the user what they did so it can call `log_time` -- a tool the agent has."""
    rendered = await mcp_server.get_prompt("ore-da-registrare", {})
    text = str(rendered.messages)
    assert "log_time" in text
    assert "gior" in text.lower()


async def test_every_prompt_returns_at_least_one_user_message(mcp_server: Any) -> None:
    """A prompt whose only message is `assistant` puts words in the model's mouth and gives
    the user nothing to send."""
    for name, args in (
        ("revisione-pipeline", {}),
        ("chiusura-mese", {"anno": 2026, "mese": 3}),
        ("ore-da-registrare", {}),
    ):
        rendered = await mcp_server.get_prompt(name, args)
        assert any(message.role == "user" for message in rendered.messages), name
```

`seeded_pipeline` and `seeded_customer` are fixtures added to `apps/mcp/tests/conftest.py` beside the existing ones, each committing a small corpus on the server's own session.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest apps/mcp/tests/test_mcp_prompts.py -v`
Expected: `test_all_four_prompts_are_registered_with_their_names` FAILS with `assert set() == {...}`.

- [ ] **Step 3: Write the dashboard prompts**

```python
# apps/mcp/src/pigrocrm_mcp/prompts/dashboards.py
"""Three of §10's four prompts. Each is several reads **plus a posture on how to read
them**, which is what makes it a prompt and not a tool.

The distinction is not stylistic. A tool is invoked by the *model*, when it decides it needs
one, and returns *data*. A prompt is invoked by the *user*, from a menu, and returns
*messages*. And the judgement sits in a different place: in a tool it is the model's, in a
prompt it is written down here. A tool that also returned "ask about the deals that have not
moved, do not summarise the ones that have" would be putting instructions inside a data
result -- the shape of an injection -- and the model would have to guess it should call it,
whereas here the human picks it and can see what was attached.

The context travels as **Markdown text inside the message**. It is a resource block only
where the resource already exists, which in this slice means `customer://{id}` and therefore
only `prompts/customer.py`. §11.1 adds no new resource, and inventing
`dashboard://commerciale?da=…` in order to have a URI to embed would be adding one without
saying so.

Every figure rendered here is a field of a dashboard response, printed. **Nothing in this
module computes anything**: the same rule as `core/dashboard/`, for the same reason, and if
a figure is missing from the response the fix is on the owning service.
"""

from datetime import date
from typing import Any

from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.dashboard.service import DashboardService
from pigrocrm.core.db import month_bounds
from pigrocrm.core.documents.repository import DocumentRepository

from pigrocrm_mcp.context import McpContext


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": {"type": "text", "text": text}}


def _euro(value: str) -> str:
    """The string the service produced, with a comma. No parsing: a `Decimal` serialised to
    a string is exact, and `float(value)` would put a rounding error into a briefing."""
    return f"{value.replace('.', ',')} €"


def _percent(value: str | None) -> str:
    # A dash, never "0%": zero per cent means "I lost everything", `null` means nothing
    # closed. Two different facts, and a briefing that conflates them is worse than one
    # that omits the line.
    return "—" if value is None else f"{value.replace('.', ',')}%"


def revisione_pipeline(
    context: McpContext, da: str | None = None, a: str | None = None
) -> list[dict[str, Any]]:
    """The weekly review. Posture: ask about the deals that have not moved."""
    query = PeriodoQuery(
        da=date.fromisoformat(da) if da else None,
        a=date.fromisoformat(a) if a else None,
    )
    board = DashboardService(context.session).get_commercial_dashboard(
        query, context.actor
    )
    offers = DocumentRepository(context.session).pending_offers(limit=20)

    lines = [
        f"# Revisione pipeline — {board.periodo.da} → {board.periodo.a}",
        "",
        "## Pipeline aperta per stato",
        "",
        "| Stato | Deal | Valore | Senza valore | Valore ponderato (stima) |",
        "|---|---|---|---|---|",
    ]
    for row in board.pipeline:
        lines.append(
            f"| {row.stage_nome} | {row.numero} | {_euro(str(row.valore_totale))} "
            f"| {row.senza_valore} | {_euro(str(row.valore_ponderato))} |"
        )
    lines += [
        "",
        "Il valore ponderato è una **stima** (valore previsto × probabilità): non è "
        "fatturato e non va sommato ai ricavi. I deal senza valore previsto sono contati "
        "a parte e non valgono zero.",
        "",
        "## Chiusure nel periodo",
        "",
        f"- Vinti: {board.chiusure.vinti}",
        f"- Persi: {board.chiusure.persi}",
        f"- Tasso di conversione: {_percent(str(board.chiusure.tasso_conversione) if board.chiusure.tasso_conversione is not None else None)}",
        f"- Valore vinto (dichiarato dai deal, **non** fatturato): "
        f"{_euro(str(board.chiusure.valore_vinto))}",
    ]
    if board.chiusure_non_attribuibili:
        lines.append(
            f"- {board.chiusure_non_attribuibili} deal chiusi prima dell'introduzione di "
            "questa misura non sono attribuibili a un periodo e non sono nei numeri sopra."
        )
    lines += ["", "## Offerte inviate in attesa di risposta", ""]
    if not offers:
        lines.append("Nessuna offerta in attesa.")
    else:
        for offer in offers:
            age = "data ignota" if offer.giorni is None else f"{offer.giorni} giorni"
            lines.append(f"- {offer.titolo} — ferma da {age}")
    lines += [
        "",
        f"Segnale: {board.offerte_accettate_deal_non_vinto} offerte accettate il cui deal "
        "non è vinto.",
        "",
        "---",
        "",
        "Fai la revisione settimanale su questi dati. Chiedimi dei deal **fermi** — quelli "
        "nello stesso stato da troppo tempo e le offerte in attesa da più di due settimane "
        "— e non riassumere quelli che si stanno muovendo: quelli li vedo già. Se il tasso "
        "di conversione è nullo dillo, non trattarlo come zero. Non proporre azioni "
        "automatiche: elenca le domande da fare ai clienti.",
    ]
    return [_user("\n".join(lines))]


def chiusura_mese(context: McpContext, anno: int, mese: int) -> list[dict[str, Any]]:
    """The list of things to do before closing a month. **No fiscal figure** (§10.1)."""
    da, a = month_bounds(anno, mese)
    service = DashboardService(context.session)
    economic = service.get_economic_dashboard(PeriodoQuery(da=da, a=a), context.actor)
    backlog = AnalyticsService(context.session).unbilled_backlog(context.actor)

    pnl = economic.pnl
    lines = [
        f"# Chiusura mese — {anno}-{mese:02d}",
        "",
        "## Conto economico del periodo",
        "",
        "| Voce | Deal chiusi | Deal in corso |",
        "|---|---|---|",
        f"| Ricavi (imponibile, emesso) | {_euro(str(pnl.chiusi.ricavi))} "
        f"| {_euro(str(pnl.in_corso.ricavi))} |",
        f"| Costi diretti | {_euro(str(pnl.chiusi.costi_diretti))} "
        f"| {_euro(str(pnl.in_corso.costi_diretti))} |",
        f"| Costo del lavoro | {_euro(str(pnl.chiusi.costo_lavoro))} "
        f"| {_euro(str(pnl.in_corso.costo_lavoro))} |",
        f"| Margine lordo | {_euro(str(pnl.chiusi.margine_lordo))} "
        f"| {_euro(str(pnl.in_corso.margine_lordo))} |",
        f"| Margine % | {_percent(str(pnl.chiusi.margine_percentuale) if pnl.chiusi.margine_percentuale is not None else None)} "
        f"| {_percent(str(pnl.in_corso.margine_percentuale) if pnl.in_corso.margine_percentuale is not None else None)} |",
        "",
        "La cifra riportabile è la colonna **deal chiusi**. Le due colonne non si sommano: "
        "il margine di un lavoro finito e quello di uno a metà non sono la stessa cosa.",
        "",
        f"Spese generali del periodo: {_euro(str(pnl.spese_generali))} — **non ripartite** "
        "su nessun deal.",
        "",
        "## Da chiudere prima della chiusura",
        "",
        f"- Ore fatturabili non fatturate **nel periodo**: "
        f"{pnl.ore_fatturabili_non_fatturate} ore, valore maturato "
        f"{_euro(str(pnl.valore_maturato))}",
        f"- Voci senza tariffa nel periodo: {pnl.ore_senza_tariffa}",
        f"- Arretrato **in totale** (senza periodo): "
        f"{backlog.ore_fatturabili_non_fatturate} ore, "
        f"{_euro(str(backlog.valore_maturato))}",
        f"- Fatture emesse nel periodo: {economic.fatture_emesse}",
        f"- Da incassare (totale con IVA, senza periodo): "
        f"{_euro(str(economic.da_incassare))}",
        f"- Di cui **scaduto**: {_euro(str(economic.scaduto))}",
        "",
        f"Periodo chiuso: {'sì' if pnl.periodo_chiuso else 'no'}. "
        f"Voci scritte in ritardo: {pnl.voci_scritte_in_ritardo}.",
        "",
        "---",
        "",
        "Prepara la lista delle cose da fare prima di chiudere questo mese. Segnala solo "
        "gli scostamenti che contano: ore non fatturate, voci senza tariffa, fatture "
        "scadute. «Da incassare» è un credito, non un ricavo: non sommarlo ai ricavi e non "
        "usarlo per calcolare un margine. Se il periodo non è chiuso e ci sono voci scritte "
        "in ritardo, dì che i numeri possono ancora muoversi. Non calcolare nessuna imposta "
        "e nessun contributo: non è un dato di cui disponi.",
    ]
    return [_user("\n".join(lines))]


def ore_da_registrare(
    context: McpContext, settimana: str | None = None
) -> list[dict[str, Any]]:
    """The most useful prompt in the product (§10): it attacks "I never entered Tuesday".

    `settimana` is accepted and currently ignored beyond validation, because
    `get_operational_dashboard` is always the current week by construction (§6). Rather than
    silently answering a different question, an explicit past week is refused with a message
    saying which week the answer covers.
    """
    board = DashboardService(context.session).get_operational_dashboard(context.actor)
    week = board.settimana
    if settimana is not None and settimana != week.da.isoformat():
        return [
            _user(
                f"La dashboard operativa copre solo la settimana corrente "
                f"({week.da} → {week.a}); la settimana richiesta ({settimana}) non è "
                "disponibile. Per le ore di una settimana passata usa il rapporto ore."
            )
        ]

    lines = [
        f"# Ore da registrare — settimana {week.da} → {week.a}",
        "",
        "| Giorno | Ore |",
        "|---|---|",
    ]
    for day in week.giorni:
        lines.append(f"| {day.giorno} | {day.ore} |")
    lines += ["", f"Totale settimana: {week.ore_totali} ore.", ""]
    if week.giorni_senza_ore:
        lines.append("**Giorni senza nessuna ora registrata:**")
        lines += [f"- {day}" for day in week.giorni_senza_ore]
    else:
        lines.append("Nessun giorno scoperto: la settimana è completa.")
    lines += [
        "",
        "## Deal su cui si è lavorato di recente",
        "",
    ]
    recent_deals = [
        activity for activity in board.attivita_recenti if activity.entity_type == "deal"
    ][:10]
    if not recent_deals:
        lines.append("Nessuna attività recente su un deal.")
    else:
        for activity in recent_deals:
            lines.append(f"- deal `{activity.entity_id}` — {activity.kind}")
    lines += [
        "",
        "---",
        "",
        "Aiutami a recuperare le ore mancanti. Per ogni giorno senza ore, chiedimi cosa ho "
        "fatto — un giorno per volta, non tutti insieme — e proponi il deal più probabile "
        "fra quelli sopra. Quando ti rispondo, registra le ore con `log_time`. Non "
        "inventare né ore né deal: se non sai su cosa imputare un giorno, chiedi. Un giorno "
        "in cui non ho lavorato va lasciato vuoto, non registrato a zero.",
    ]
    return [_user("\n".join(lines))]
```

- [ ] **Step 4: Write the customer prompt**

```python
# apps/mcp/src/pigrocrm_mcp/prompts/customer.py
"""§10's fourth prompt, and the only one that embeds a resource.

It is the only one because it is the only one whose resource **already exists**:
`customer://{id}`, from slice 1 §8.4. A resource block needs a URI, and there is no URI for
"the commercial dashboard for March" that would not be a new resource invented in order to
have one -- which §11.1 explicitly declines.
"""

from typing import Any
from uuid import UUID

from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.deals.schemas import DealListQuery
from pigrocrm.core.errors import NotFound
from pigrocrm.core.invoices.repository import InvoiceRepository

from pigrocrm_mcp.context import McpContext


def stato_cliente(context: McpContext, customer_id: str) -> list[dict[str, Any]]:
    """The briefing before a phone call."""
    identifier = UUID(customer_id)
    from pigrocrm.core.customers.repository import CustomerRepository

    customer = CustomerRepository(context.session).get(identifier)
    if customer is None:
        # A domain error, so `_guard` turns it into a sentence the agent can act on rather
        # than a stack trace.
        raise NotFound("customer", identifier)

    deals = DealRepository(context.session).list(
        DealListQuery(customer_id=identifier, limit=50)
    )
    unpaid = InvoiceRepository(context.session).unpaid_for_customer(identifier)

    lines = [
        f"# Briefing — {customer.ragione_sociale}",
        "",
        "## Deal",
        "",
    ]
    if not deals:
        lines.append("Nessun deal.")
    else:
        for deal in deals:
            valore = "senza valore" if deal.valore_previsto is None else (
                f"{str(deal.valore_previsto).replace('.', ',')} €"
            )
            lines.append(f"- {deal.nome} — {valore}, probabilità {deal.probabilita}%")
    lines += ["", "## Fatture non incassate", ""]
    if not unpaid:
        lines.append("Nessuna fattura da incassare.")
    else:
        for invoice in unpaid:
            scadenza = invoice.data_scadenza or "senza scadenza"
            lines.append(
                f"- {invoice.anno}/{invoice.numero} — "
                f"{str(invoice.totale).replace('.', ',')} € (totale con IVA), "
                f"scadenza {scadenza}"
            )
    lines += [
        "",
        "---",
        "",
        "La scheda completa del cliente è allegata come risorsa. Preparami il briefing per "
        "una telefonata: cosa è aperto, cosa è in ritardo, e le due o tre domande da fare. "
        "Le fatture non incassate sono crediti con IVA, non ricavi. Non proporre di mandare "
        "solleciti: dimmi solo cosa c'è.",
    ]
    return [
        {"role": "user", "content": {"type": "text", "text": "\n".join(lines)}},
        {
            "role": "user",
            "content": {
                "type": "resource",
                "resource": {"uri": f"customer://{identifier}"},
            },
        },
    ]
```

`InvoiceRepository.unpaid_for_customer(customer_id: UUID) -> list[Invoice]` is one more method on the repository Task C3 touched — issued, unpaid, non-deleted invoices for that customer, ordered by `data_scadenza` nulls last. Add it there, above any `list`, in the same shape as its neighbours, with a test in `test_invoice_aggregates.py`.

- [ ] **Step 5: Register them**

```python
# apps/mcp/src/pigrocrm_mcp/prompts/__init__.py
"""Registration for §10's four prompts.

`MCPServer.prompt()` infers the arguments from the signature exactly as `tool()` does --
verified against the installed `mcp==2.0.0`, not assumed from the documentation -- and the
function may receive the `Context`, so a prompt can read the database like a tool. The
`guard` is the server's own `_guard`, so a domain error becomes guidance rather than a stack
trace here too.
"""

from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer

from pigrocrm_mcp.context import McpContext
from pigrocrm_mcp.prompts import customer as customer_prompts
from pigrocrm_mcp.prompts import dashboards as dashboard_prompts


def register_prompts[T: Callable[..., Any]](
    mcp: MCPServer, context: McpContext, guard: Callable[[T], T]
) -> None:
    @mcp.prompt(name="revisione-pipeline")
    @guard
    def revisione_pipeline(da: str | None = None, a: str | None = None) -> list[dict[str, Any]]:
        """La revisione settimanale della pipeline commerciale, con i deal fermi e le
        offerte in attesa. `da` e `a` sono date ISO opzionali: senza, il mese in corso."""
        return dashboard_prompts.revisione_pipeline(context, da, a)

    @mcp.prompt(name="chiusura-mese")
    @guard
    def chiusura_mese(anno: int, mese: int) -> list[dict[str, Any]]:
        """La lista di cose da fare prima di chiudere un mese: conto economico del periodo,
        ore non fatturate, fatture scadute, e se il periodo è già chiuso."""
        return dashboard_prompts.chiusura_mese(context, anno, mese)

    @mcp.prompt(name="ore-da-registrare")
    @guard
    def ore_da_registrare(settimana: str | None = None) -> list[dict[str, Any]]:
        """I giorni della settimana corrente senza nessuna ora registrata, con i deal su
        cui si è lavorato di recente."""
        return dashboard_prompts.ore_da_registrare(context, settimana)

    @mcp.prompt(name="stato-cliente")
    @guard
    def stato_cliente(customer_id: str) -> list[dict[str, Any]]:
        """Il briefing prima di una telefonata: deal aperti, fatture non incassate, e la
        scheda del cliente allegata come risorsa."""
        return customer_prompts.stato_cliente(context, customer_id)
```

```python
# apps/mcp/src/pigrocrm_mcp/server.py -- two lines, next to the existing tool registration.
    from pigrocrm_mcp.prompts import register_prompts
    from pigrocrm_mcp.tools import register_entity_tools

    register_entity_tools(mcp, context, _guard)
    register_prompts(mcp, context, _guard)
    return mcp
```

- [ ] **Step 6: The R1 gate**

A prompt reads the database exactly as a tool does, so it inherits the same gate. If the shared-session comment in `server.py` is still accurate, do not add the `register_prompts` call: skip `apps/mcp/tests/test_mcp_prompts.py` at module level with the reason, and land the four modules unregistered. They are pure functions of `(context, args)` and lose nothing by waiting.

- [ ] **Step 7: Run, gate, commit**

Run: `uv run pytest apps/mcp/tests/test_mcp_prompts.py -v`
Expected: PASS, eleven tests.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add apps/mcp/src/pigrocrm_mcp/prompts/ \
        apps/mcp/src/pigrocrm_mcp/server.py \
        packages/core/src/pigrocrm/core/invoices/repository.py \
        apps/mcp/tests/test_mcp_prompts.py \
        apps/mcp/tests/conftest.py \
        packages/core/tests/test_invoice_aggregates.py
git commit -m "feat(mcp): four contextual prompts, one of them embedding customer://"
```

---
### Task C9: Criterion 10 — the prompts carry the context, and not the tax

**Blocked on: Task C8.**

**Files:**
- Modify: `apps/mcp/tests/test_mcp_prompts.py`

**Interfaces:**
- Consumes: the four prompts (Task C8); `AnalyticsService.period_pnl` (slice 4); `month_bounds` (Task B1).
- Produces: `FORBIDDEN_FISCAL_FIELDS: frozenset[str]` and `KNOWN_RESOURCE_URIS: frozenset[str]` in that test module, plus five tests. Nothing else imports them.

**Two prohibitions, and they are prohibitions.**

**No prompt contains the fiscal estimate.** Slice 4 §11 reason 4 keeps it off the MCP surface because a PAT with no scopes (residuo **R10**) is indistinguishable from full access. A prompt that embedded it would route around that decision without calling the tool that does not exist — which is worse than a tool, because nobody would be looking for it there. Criterion 10 says to verify it **by field name, not by intention**, and this task does exactly that: it renders every message of every prompt and greps the text.

**No prompt embeds data the corresponding tool would not return.** A prompt is another packaging of the same permissions, not a shortcut through them.

**And one positive assertion that is easy to skip:** `chiusura-mese`'s rendered figures must equal `period_pnl`'s **value by value**, not merely look plausible. A briefing that reformats a margin is a second source of truth with a friendly tone.

- [ ] **Step 1: Write the failing test**

```python
# apps/mcp/tests/test_mcp_prompts.py -- append.

# Field names, not concepts. Criterion 10: "verificato per nome di campo, non per
# intenzione". The first four are the fiscal estimate's own fields (slice 4 §11); the last
# three are the parameters it is derived from, which are just as sensitive and would let a
# reader reconstruct it.
FORBIDDEN_FISCAL_FIELDS = frozenset({
    "imponibile_fiscale",
    "imposta_sostitutiva",
    "contributi",
    "netto_stimato",
    "coefficiente_redditivita",
    "aliquota_imposta_sostitutiva",
    "aliquota_inps",
})

# The resources that exist. Criterion 10 requires that no prompt introduces a new URI
# scheme, because a resource is a surface and adding one silently is adding a surface
# silently (§11.1: "Nessuna risorsa nuova").
KNOWN_RESOURCE_URIS = frozenset({"customer://", "person://", "deal://"})

_ALL_PROMPTS = (
    ("revisione-pipeline", {}),
    ("chiusura-mese", {"anno": 2026, "mese": 3}),
    ("ore-da-registrare", {}),
)


def _text_of(rendered: Any) -> str:
    blocks: list[str] = []
    for message in rendered.messages:
        content = message.content
        for block in content if isinstance(content, list) else [content]:
            if getattr(block, "type", None) == "text":
                blocks.append(block.text)
    return "\n".join(blocks)


def _resource_uris(rendered: Any) -> list[str]:
    uris: list[str] = []
    for message in rendered.messages:
        content = message.content
        for block in content if isinstance(content, list) else [content]:
            if getattr(block, "type", None) == "resource":
                uris.append(str(getattr(block, "resource", block).uri))
    return uris


async def test_no_prompt_contains_a_fiscal_field_by_name(
    mcp_server: Any, seeded_customer: Any
) -> None:
    """Criterion 10's first prohibition, checked over every rendered message of every
    prompt.

    Slice 4 §11 reason 4 keeps the fiscal estimate off the MCP surface because a PAT has no
    scopes (residuo R10) and is therefore indistinguishable from full access. A prompt that
    carried it would bypass that decision without calling the tool that deliberately does
    not exist -- and nobody would think to look for it in a prompt.
    """
    cases = [*_ALL_PROMPTS, ("stato-cliente", {"customer_id": str(seeded_customer.id)})]
    for name, args in cases:
        rendered = await mcp_server.get_prompt(name, args)
        haystack = str(rendered.messages).lower()
        for field in FORBIDDEN_FISCAL_FIELDS:
            assert field not in haystack, f"{name} carries the fiscal field {field}"


async def test_chiusura_mese_matches_the_pnl_value_by_value(
    mcp_server: Any, mcp_context: Any, seeded_pnl: Any
) -> None:
    """Criterion 10's positive half: "contiene le cifre del P&L **identiche** a quelle di
    `get_period_pnl` -- confrontate valore per valore, non a occhio".

    A prompt that reformats a margin is a second source of truth with a friendly tone, and
    it is the easiest one to introduce by accident -- a `:.2f` in a f-string is enough.
    """
    from pigrocrm.core.analytics.schemas import PeriodPnlQuery
    from pigrocrm.core.analytics.service import AnalyticsService
    from pigrocrm.core.db import month_bounds

    da, a = month_bounds(2026, 3)
    pnl = AnalyticsService(mcp_context.session).period_pnl(
        PeriodPnlQuery(da=da, a=a, customer_id=None), mcp_context.actor
    )

    rendered = await mcp_server.get_prompt("chiusura-mese", {"anno": 2026, "mese": 3})
    text = _text_of(rendered)

    for value in (
        pnl.chiusi.ricavi, pnl.chiusi.costi_diretti, pnl.chiusi.costo_lavoro,
        pnl.chiusi.margine_lordo, pnl.in_corso.ricavi, pnl.spese_generali,
        pnl.valore_maturato,
    ):
        # The prompt renders the decimal string with a comma; the comparison undoes exactly
        # that one substitution and nothing else, so a rounding or a re-scaling would fail.
        assert str(value).replace(".", ",") in text, value

    assert str(pnl.voci_scritte_in_ritardo) in text
    assert ("sì" if pnl.periodo_chiuso else "no") in text


async def test_stato_cliente_is_the_only_prompt_with_a_resource_block(
    mcp_server: Any, seeded_customer: Any
) -> None:
    """§10: it is the only one because it is the only one whose resource already exists."""
    for name, args in _ALL_PROMPTS:
        rendered = await mcp_server.get_prompt(name, args)
        assert _resource_uris(rendered) == [], name

    rendered = await mcp_server.get_prompt(
        "stato-cliente", {"customer_id": str(seeded_customer.id)}
    )
    assert _resource_uris(rendered) == [f"customer://{seeded_customer.id}"]


async def test_no_prompt_introduces_a_new_resource_uri_scheme(
    mcp_server: Any, seeded_customer: Any
) -> None:
    """Criterion 10: "un test elenca gli URI incorporati da tutti e quattro e verifica che
    non ne esistano di nuovi". §11.1 adds no resource, and inventing
    `dashboard://commerciale?da=…` in order to have a URI to embed would add one without
    saying so."""
    cases = [*_ALL_PROMPTS, ("stato-cliente", {"customer_id": str(seeded_customer.id)})]
    seen: set[str] = set()
    for name, args in cases:
        rendered = await mcp_server.get_prompt(name, args)
        for uri in _resource_uris(rendered):
            scheme = uri.split("//")[0] + "//"
            seen.add(scheme)
    assert seen <= KNOWN_RESOURCE_URIS, f"new resource schemes: {seen - KNOWN_RESOURCE_URIS}"


async def test_the_registered_resource_templates_are_still_exactly_three(
    mcp_server: Any
) -> None:
    """The other half of "no new resource": not just that no prompt embeds a new URI, but
    that none was registered at all."""
    templates = {str(template.uriTemplate) for template in await mcp_server.list_resource_templates()}
    assert templates == {
        "customer://{customer_id}", "person://{person_id}", "deal://{deal_id}",
    }


async def test_no_prompt_embeds_data_its_tools_would_not_return(
    mcp_server: Any, seeded_customer: Any
) -> None:
    """Criterion 10's second prohibition, applied where it is checkable: every figure a
    prompt renders is a field of a dashboard response or of a repository read that a tool
    already exposes. The mechanical form of that is the fiscal check above plus this one --
    no prompt reaches a service method that is on an exclusion list.
    """
    from pathlib import Path

    prompts_dir = Path(__file__).resolve().parents[1] / "src" / "pigrocrm_mcp" / "prompts"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in prompts_dir.rglob("*.py")
    )
    for excluded in (
        "get_fiscal_estimate", "update_automation_config", "bind_time_to_invoice",
        "close_period", "reopen_period", "recalculate_rates", "update_user_rates",
        "update_deal_rate",
    ):
        assert f".{excluded}(" not in source, (
            f"a prompt reaches {excluded}, which is on an MCP exclusion list -- a prompt is "
            "another packaging of the same permissions, not a shortcut through them"
        )
```

`seeded_pnl` is a fixture added to `apps/mcp/tests/conftest.py` committing one issued invoice and a handful of time entries dated inside March 2026, so `period_pnl` returns non-zero figures — a value-by-value comparison against a P&L of all zeros would pass on an implementation that printed zeros unconditionally.

- [ ] **Step 2: Run it and watch it fail on purpose first**

Temporarily add `f"Imposta sostitutiva stimata: 1.234,00 €"` to `chiusura_mese`'s lines.

Run: `uv run pytest apps/mcp/tests/test_mcp_prompts.py -v`
Expected: `test_no_prompt_contains_a_fiscal_field_by_name` FAILS naming `imposta_sostitutiva`. **Remove the line.** Then temporarily change one rendered figure to `f"{float(pnl.chiusi.ricavi):.2f}"` and confirm `test_chiusura_mese_matches_the_pnl_value_by_value` FAILS. **Revert.**

- [ ] **Step 3: Run it green**

Run: `uv run pytest apps/mcp/tests/test_mcp_prompts.py -v`
Expected: PASS, seventeen tests.

- [ ] **Step 4: Full gate and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add apps/mcp/tests/test_mcp_prompts.py apps/mcp/tests/conftest.py
git commit -m "test(mcp): criterion 10, the prompts carry the context and not the tax"
```

---

### Task C10: Criterion 12 — ten concurrent dashboard reads over MCP

**Blocked on: Task C7 and the R1 cure in `main`.** This task **is** the verification of that cure from the read side, so it cannot be written before it and must not be skipped after it.

**Files:**
- Create: `apps/mcp/tests/test_mcp_concurrency.py`

**Interfaces:**
- Consumes: the `get_economic_dashboard` MCP tool (Task C7); whatever session-per-call mechanism slice 4's plan introduced.
- Produces: nothing importable.

**Why this criterion exists at all, in the spec's own terms.** Residuo R1 — one `Session` shared by every call on the MCP server — is not an open decision: it is a task of slice 4's plan, where `log_time` cannot exist without it. This slice **depends on the cure and does not work around it**, and it is written down for two reasons: because read aggregation makes the underlying problem *worse*, and because if the cure slipped, these tools must not be registered at all.

- an aggregation query holds the connection longer than a `get`, widening the window in which two calls overlap — the condition the slice-1A review measured as **10 concurrent writes, 0 successes, 0 rows**;
- and §7.1's guarantee — one dashboard, one transaction, one instant — is a property **of the session**. With a shared session and no per-call transaction boundary, two concurrent dashboards can each read half their figures inside the other's transaction and produce a total that was never true at any instant. That is §1's second source of truth generated by the infrastructure instead of by the code, and it is the worst case because re-reading the service would never reveal it.

**Ten identical responses "a meno di `calcolato_alle`".** The criterion is explicit that byte-for-byte equality of the whole JSON would fail *without a defect*: each call is its own transaction and therefore its own instant, so the timestamps cannot coincide. The test compares everything else.

- [ ] **Step 1: Write the failing test**

```python
# apps/mcp/tests/test_mcp_concurrency.py
"""**Criterion 12.** Ten simultaneous `get_economic_dashboard` calls on real PostgreSQL.

This is residuo **R1** verified from the read side, and the condition under which these
tools are allowed to exist at all.

Two things are asserted and the second is the one that matters. Ten responses identical
**except for `calcolato_alle`** -- which cannot coincide, because each call is its own
transaction and therefore its own instant, and a test demanding byte-for-byte equality of
the whole JSON would fail without a defect. And every call reporting its own correct
`transaction_isolation`, because §7.1's guarantee is a property of the session: with one
shared session and no per-call transaction boundary, two dashboards can each read half their
figures inside the other's transaction and produce a total that was never true at any
instant.

`asyncio.gather` over the SDK's own client, not threads: the tools are registered on an
async server and the concurrency that matters is the one the transport actually produces.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


async def test_ten_concurrent_economic_dashboards_agree_except_on_the_instant(
    mcp_server: Any, seeded_pnl: Any
) -> None:
    results = await asyncio.gather(
        *(mcp_server.call_tool("get_economic_dashboard", {}) for _ in range(10))
    )

    assert all(not result.is_error for result in results), [
        str(result.content) for result in results if result.is_error
    ]

    payloads = [dict(result.structured_content) for result in results]
    instants = [payload.pop("calcolato_alle") for payload in payloads]

    first = payloads[0]
    for index, payload in enumerate(payloads[1:], start=1):
        assert payload == first, f"response {index} differs from response 0"

    # Each call is its own transaction, so each has its own instant. Asserting they are all
    # equal would be asserting that the sessions are shared -- the defect, not the cure.
    assert all(instant is not None for instant in instants)


async def test_no_call_fails_with_a_session_error(mcp_server: Any, seeded_pnl: Any) -> None:
    """The shape R1 actually produces. With a shared session, a concurrent call lands
    mid-transaction on another call's session and SQLAlchemy raises -- typically
    `Method 'rollback()' can't be called here` or `This session is in 'prepared' state`.
    Matched on the message because the exception is converted to an agent-facing string by
    `_guard` before the test can see its type."""
    results = await asyncio.gather(
        *(mcp_server.call_tool("get_operational_dashboard", {}) for _ in range(10))
    )
    for result in results:
        rendered = str(result.content)
        for symptom in (
            "rollback", "prepared state", "already begun", "concurrent operations",
            "InvalidRequestError", "PendingRollbackError",
        ):
            assert symptom not in rendered, rendered


async def test_every_call_runs_in_repeatable_read(
    mcp_server: Any, mcp_context: Any, seeded_pnl: Any
) -> None:
    """Criterion 12's last clause: "ogni chiamata ha il proprio `transaction_isolation`
    corretto".

    A shared session would give the *first* caller the right level and leave the rest
    running in whatever the connection had -- which is exactly the failure that does not
    show up in the response and cannot be found by re-reading the service.
    """
    from sqlalchemy import text

    levels: list[str] = []

    async def call_and_read_level() -> None:
        result = await mcp_server.call_tool("get_economic_dashboard", {})
        assert not result.is_error, str(result.content)
        # The session the call used is the one the context resolves *inside* that call. With
        # the cure in place this is a fresh session per call; reading it here reads the last
        # one, which is why the assertion below is on the count of distinct values as well
        # as on the value.
        levels.append(
            mcp_context.session.execute(text("SHOW transaction_isolation")).scalar_one()
        )

    await asyncio.gather(*(call_and_read_level() for _ in range(10)))
    assert set(levels) == {"repeatable read"}, set(levels)


async def test_ten_concurrent_searches_also_succeed(mcp_server: Any, seeded_pnl: Any) -> None:
    """The lighter case, kept because it is the one that would still pass on a shared
    session and therefore tells the two failure modes apart: if the searches pass and the
    dashboards do not, the problem is the longer-held connection of an aggregation query --
    §11.3's first bullet -- rather than the session sharing itself."""
    results = await asyncio.gather(
        *(mcp_server.call_tool("search_everything", {"termine": "cliente"}) for _ in range(10))
    )
    assert all(not result.is_error for result in results), [
        str(result.content) for result in results if result.is_error
    ]


@pytest.mark.parametrize("tool", [
    "get_commercial_dashboard", "get_economic_dashboard", "get_operational_dashboard",
])
async def test_each_dashboard_tool_survives_concurrency_individually(
    mcp_server: Any, seeded_pnl: Any, tool: str
) -> None:
    """Per tool, so a failure names which one rather than "the dashboards"."""
    results = await asyncio.gather(
        *(mcp_server.call_tool(tool, {}) for _ in range(10))
    )
    assert all(not result.is_error for result in results), [
        str(result.content) for result in results if result.is_error
    ]
```

- [ ] **Step 2: Run it and watch it fail if the cure is absent**

Run: `uv run pytest apps/mcp/tests/test_mcp_concurrency.py -v`

Expected **before** the R1 cure: `test_no_call_fails_with_a_session_error` FAILS with one of the named symptoms, and `test_every_call_runs_in_repeatable_read` FAILS with a set containing `read committed`. That failure is the correct outcome and **is not to be worked around**: it means Task C7's tools must not be registered yet.

Expected **after** the cure: PASS.

- [ ] **Step 3: Full gate and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add apps/mcp/tests/test_mcp_concurrency.py
git commit -m "test(mcp): criterion 12, ten concurrent dashboard reads on one server"
```

---
### Task C11: The economic and operational tabs

**Blocked on: Task C7.**

**Files:**
- Modify: `apps/web/src/lib/api-types.ts` (regenerated)
- Modify: `apps/web/src/features/dashboard/queries.ts`
- Create: `apps/web/src/features/dashboard/EconomicTab.tsx`
- Create: `apps/web/src/features/dashboard/EconomicTab.test.tsx`
- Create: `apps/web/src/features/dashboard/OperationalTab.tsx`
- Create: `apps/web/src/features/dashboard/OperationalTab.test.tsx`
- Modify: `apps/web/src/routes/app/index.tsx` (replace the two placeholder paragraphs)
- Modify: `apps/web/src/features/dashboard/charts.tsx` — nothing changes; listed so nobody adds a fifth shape

**Interfaces:**
- Consumes: `GET /api/dashboard/economica`, `GET /api/dashboard/operativa` (Task C7); `BigNumber`, `BarRows`, `Sparkline`, `BarRow`, `SparkPoint` from `./charts` (Task B13); `Freshness` (Task B14); `QueryErrorBanner`.
- Produces:
  - `queries.ts`: `type EconomicDashboard`, `type OperationalDashboard`, `useEconomicDashboard(periodo: { da: string; a: string })`, `useOperationalDashboard()`
  - `EconomicTab.tsx`: `export function EconomicTab({ periodo }: { periodo: Periodo })`
  - `OperationalTab.tsx`: `export function OperationalTab()` — **no props**, because §6's dashboard takes no period
- Task C13's end-to-end run drives both.

**Four things the economic tab must get right, each of which is a test below.** The label is *"Fatturato (imponibile, emesso)"* in full, not *"Fatturato"* — three extra words on a card are the price of not having two users read the same figure as two different things (§5.1). The margin appears in **two columns**, closed and in progress, and **there is no box holding their sum**. "Scaduto" is rendered **indented beneath** "Da incassare", never as a second addable line. And the fiscal estimate is **a link, not a number**.

**No new chart shape.** Four shapes were decided in Task B13 and four is the number; the operational tab's weekly hours are the sparkline that shape exists for.

- [ ] **Step 1: Regenerate the client**

Run: `cd apps/web && pnpm generate:api && pnpm exec tsc --noEmit`
Expected: clean. Two new paths appear; nothing existing changes.

- [ ] **Step 2: Write the failing tests**

```tsx
// apps/web/src/features/dashboard/EconomicTab.test.tsx
/**
 * §5's tab. Every figure comes from the API already summed; this file asserts on the four
 * things §5 and §5.1-5.3 say must be true of how they are *presented*, because that is the
 * half a backend test cannot reach.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EconomicTab } from './EconomicTab'

const fetchMock = vi.fn()

const TOTALS = {
  ricavi: '15000.00',
  costi_diretti: '2000.00',
  costo_lavoro: '6000.00',
  margine_lordo: '7000.00',
  margine_percentuale: '46.67',
  deal: 4,
}

const RESPONSE = {
  periodo: { da: '2026-03-01', a: '2026-03-31' },
  calcolato_alle: '2026-03-15T10:00:00Z',
  pnl: {
    da: '2026-03-01',
    a: '2026-03-31',
    customer_id: null,
    chiusi: TOTALS,
    in_corso: { ...TOTALS, ricavi: '3000.00', margine_percentuale: null },
    spese_generali: '900.00',
    periodo_chiuso: false,
    voci_scritte_in_ritardo: 2,
    valore_maturato: '4500.00',
    ore_fatturabili_non_fatturate: '90.00',
    ore_senza_tariffa: 3,
  },
  da_incassare: '12200.00',
  scaduto: '3050.00',
  fatture_emesse: 6,
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <EconomicTab periodo={{ da: '2026-03-01', a: '2026-03-31' }} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(RESPONSE), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  )
})

afterEach(() => vi.restoreAllMocks())

describe('EconomicTab', () => {
  it('labels revenue in full, never just "Fatturato"', async () => {
    // §5.1: three extra words on a card are the price of not having two users read the
    // same figure as two different things.
    renderTab()
    expect(
      await screen.findByText(/fatturato \(imponibile, emesso\)/i),
    ).toBeInTheDocument()
  })

  it('shows the margin in two columns and no box holding their sum', async () => {
    // Slice 4 §7.4: adding a finished job's margin to a half-done one produces a figure
    // that is neither, and that moves every week for reasons which are not performance.
    renderTab()
    expect(await screen.findByText(/deal chiusi/i)).toBeInTheDocument()
    expect(screen.getByText(/deal in corso/i)).toBeInTheDocument()
    expect(screen.queryByText(/margine totale/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/margine complessivo/i)).not.toBeInTheDocument()
  })

  it('marks the closed-deals column as the reportable one', async () => {
    renderTab()
    expect(await screen.findByText(/cifra riportabile/i)).toBeInTheDocument()
  })

  it('renders a null margin percentage as a dash and never as 0%', async () => {
    renderTab()
    // `in_corso.margine_percentuale` is null in the fixture.
    expect(await screen.findAllByText('—')).not.toHaveLength(0)
  })

  it('renders "Scaduto" as a subset indented under "Da incassare"', async () => {
    // §5.2: a subset shown as one, never a second addable voice.
    renderTab()
    const overdue = await screen.findByTestId('scaduto')
    expect(overdue).toHaveAttribute('data-subset-of', 'da-incassare')
    expect(overdue).toHaveTextContent(/di cui scaduto/i)
  })

  it('keeps "Da incassare" out of every margin row', async () => {
    renderTab()
    const receivable = await screen.findByTestId('da-incassare')
    // A receivable is not revenue (§5.2). Rendering it inside the P&L block would invite
    // exactly the addition the label forbids.
    expect(receivable.closest('[data-block="pnl"]')).toBeNull()
  })

  it('shows the informative rows under a heading that is not "ricavi"', async () => {
    // §5: "Compaiono sotto un'intestazione diversa da «ricavi» e non entrano in nessun
    // margine", and the label carries the scope.
    renderTab()
    expect(await screen.findByText(/valore maturato non fatturato/i)).toBeInTheDocument()
    expect(screen.getByText(/nel periodo/i)).toBeInTheDocument()
  })

  it('says whether the period can still move', async () => {
    // Slice 4 §6.4, and §5: beside the total, not in a footnote.
    renderTab()
    expect(await screen.findByText(/periodo non chiuso/i)).toBeInTheDocument()
    expect(screen.getByText(/2 voci scritte in ritardo/i)).toBeInTheDocument()
  })

  it('links to the fiscal estimate instead of showing a number', async () => {
    // §5.3: a dashboard is the screen most likely to end up in a screenshot.
    renderTab()
    const link = await screen.findByRole('link', { name: /stima fiscale/i })
    expect(link).toHaveAttribute('href', '/app/analisi/fiscale')
    for (const forbidden of [/imposta sostitutiva/i, /contributi/i, /netto stimato/i]) {
      expect(screen.queryByText(forbidden)).not.toBeInTheDocument()
    }
  })

  it('shows no comparison with the same period last year', async () => {
    // §5.3: the right behaviour when the prior period is partly written depends on
    // period_locks in a way nobody has exercised. A wrong comparison is worse than none.
    renderTab()
    await screen.findByText(/fatturato \(imponibile, emesso\)/i)
    expect(screen.queryByText(/anno precedente/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/rispetto a/i)).not.toBeInTheDocument()
  })

  it('renders an error banner and no figures when the request fails', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ title: 'Errore', detail: 'Non disponibile' }), {
        status: 500,
        headers: { 'content-type': 'application/problem+json' },
      }),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/fatturato/i)).not.toBeInTheDocument()
  })
})
```

```tsx
// apps/web/src/features/dashboard/OperationalTab.test.tsx
/**
 * §6's tab. Its two most important assertions are the ones about days with no hours: they
 * are named, and a day logged with zero hours is not among them.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OperationalTab } from './OperationalTab'

const fetchMock = vi.fn()

const RESPONSE = {
  calcolato_alle: '2026-03-18T10:00:00Z',
  settimana: {
    da: '2026-03-16',
    a: '2026-03-22',
    giorni: [
      { giorno: '2026-03-16', ore: '8.00' },
      { giorno: '2026-03-17', ore: '0.00' },
      { giorno: '2026-03-18', ore: '4.00' },
      { giorno: '2026-03-19', ore: '0.00' },
      { giorno: '2026-03-20', ore: '0.00' },
      { giorno: '2026-03-21', ore: '0.00' },
      { giorno: '2026-03-22', ore: '0.00' },
    ],
    giorni_senza_ore: ['2026-03-19', '2026-03-20', '2026-03-21', '2026-03-22'],
    ore_totali: '12.00',
  },
  arretrato: {
    ore_fatturabili_non_fatturate: '90.00',
    valore_maturato: '4500.00',
    voci_senza_tariffa: 3,
    voci: 22,
  },
  segnali: [
    { codice: 'fatturato_non_vinto', etichetta: 'Fatturato ma non vinto', conteggio: 2,
      collegamento: '/app/deal/lista?fatturato_non_vinto=true' },
    { codice: 'vinto_da_fatturare', etichetta: 'Vinto ma da fatturare', conteggio: 5,
      collegamento: '/app/deal/lista?da_fatturare=true' },
    { codice: 'scaduto_non_incassato', etichetta: 'Scaduto e non incassato', conteggio: 1,
      collegamento: '/app/fatture?scadute=true' },
  ],
  attivita_recenti: [],
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <OperationalTab />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(RESPONSE), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  )
})

afterEach(() => vi.restoreAllMocks())

describe('OperationalTab', () => {
  it('takes no period prop at all', () => {
    // §6: the current week and a backlog are the two things that make no sense in the past.
    expect(OperationalTab.length).toBe(0)
  })

  it('requests the endpoint without a period', async () => {
    renderTab()
    await screen.findByText(/settimana/i)
    const url = String(fetchMock.mock.calls[0]?.[0])
    expect(url).toContain('/api/dashboard/operativa')
    expect(url).not.toContain('da=')
  })

  it('shows the week as a sparkline with its equivalent table', async () => {
    renderTab()
    expect(await screen.findByRole('table', { name: /ore per giorno/i })).toBeInTheDocument()
    expect(screen.getByTestId('sparkline-svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('names the days with no hours', async () => {
    // The real failure slice 4 §13 names when it refuses a stopwatch. Naming the days is
    // what makes the figure actionable rather than a statistic.
    renderTab()
    expect(await screen.findByText(/4 giorni senza ore/i)).toBeInTheDocument()
    expect(screen.getByText(/19\/03/)).toBeInTheDocument()
  })

  it('does not count a day logged with zero hours as missing', async () => {
    renderTab()
    await screen.findByText(/4 giorni senza ore/i)
    // 2026-03-17 has 0.00 hours and is NOT in giorni_senza_ore: somebody who entered a
    // zero made a statement about that day.
    expect(screen.queryByText(/17\/03/)).not.toBeInTheDocument()
  })

  it('labels the backlog as a total, not as a period figure', async () => {
    // §5's rule: the label carries the scope, and the two figures are never side by side.
    renderTab()
    expect(await screen.findByText(/in totale/i)).toBeInTheDocument()
  })

  it('shows the hours without a rate as a figure of their own', async () => {
    renderTab()
    expect(await screen.findByText(/senza tariffa/i)).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('renders each signal as a link to its own list', async () => {
    renderTab()
    const link = await screen.findByRole('link', { name: /vinto ma da fatturare/i })
    expect(link).toHaveAttribute('href', '/app/deal/lista?da_fatturare=true')
  })

  it('offers no way to send anything from a signal', async () => {
    // §6.2: "Il conteggio **non** manda niente." A count next to a list of overdue
    // customers is exactly where somebody later adds a "send all" button.
    renderTab()
    await screen.findByText(/scaduto e non incassato/i)
    expect(screen.queryByRole('button', { name: /sollecit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /invia/i })).not.toBeInTheDocument()
  })

  it('renders an error banner and no figures when the request fails', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ title: 'Errore', detail: 'Non disponibile' }), {
        status: 500,
        headers: { 'content-type': 'application/problem+json' },
      }),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd apps/web && pnpm exec vitest run src/features/dashboard/EconomicTab.test.tsx src/features/dashboard/OperationalTab.test.tsx`
Expected: `Failed to resolve import "./EconomicTab"` and `"./OperationalTab"`.

- [ ] **Step 4: Add the two hooks**

```ts
// apps/web/src/features/dashboard/queries.ts -- append.
export type EconomicDashboard = components['schemas']['EconomicDashboard']
export type OperationalDashboard = components['schemas']['OperationalDashboard']

export function useEconomicDashboard(periodo: { da: string; a: string }) {
  return useQuery({
    queryKey: queryKeys.dashboard('economica', periodo),
    queryFn: () =>
      unwrap(api.GET('/api/dashboard/economica', { params: { query: periodo } })),
    staleTime: DASHBOARD_STALE_MS,
  })
}

export function useOperationalDashboard() {
  return useQuery({
    // No period in the key, because there is no period in the question (§6).
    queryKey: queryKeys.dashboard('operativa', {}),
    queryFn: () => unwrap(api.GET('/api/dashboard/operativa')),
    staleTime: DASHBOARD_STALE_MS,
  })
}
```

- [ ] **Step 5: Write the economic tab**

```tsx
// apps/web/src/features/dashboard/EconomicTab.tsx
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { BigNumber } from './charts'
import { Freshness } from './Freshness'
import type { Periodo } from './PeriodPicker'
import { useEconomicDashboard } from './queries'

/**
 * §5. **No new aggregate exists on this page**: every figure is a field of the response, and
 * every one of them was produced by `AnalyticsService` or by `InvoiceRepository`.
 *
 * Four presentation rules this file exists to honour, each with a test:
 *  - the revenue label is "Fatturato (imponibile, emesso)" in full, never "Fatturato";
 *  - the margin is two columns, closed and in progress, with **no** box holding their sum;
 *  - "Scaduto" is a subset rendered beneath "Da incassare", not a second addable line;
 *  - the fiscal estimate is a **link**, not a number.
 */

function euro(value: string): string {
  // Formats the string the API sent. `Intl.NumberFormat.format` accepts a string and parses
  // it with full decimal precision; `Number(value)` would put a float in the middle of a
  // currency figure, which is the defect this slice exists to prevent.
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    useGrouping: 'always',
  }).format(value as unknown as number)
}

function percent(value: string | null): string {
  // A dash, never "0,00%": zero per cent means "everything I earned went out in costs",
  // a null denominator means nothing has been earned. Slice 4 §7.1's rule, unchanged.
  return value === null ? '—' : `${value.replace('.', ',')}%`
}

function hours(value: string): string {
  return `${value.replace('.', ',')} ore`
}

export function EconomicTab({ periodo }: { periodo: Periodo }) {
  const query = useEconomicDashboard(periodo)

  if (query.isError) return <QueryErrorBanner error={query.error} />
  if (query.isLoading || !query.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const data = query.data
  const pnl = data.pnl
  const rows = [
    { label: 'Fatturato (imponibile, emesso)', closed: euro(pnl.chiusi.ricavi),
      running: euro(pnl.in_corso.ricavi) },
    { label: 'Costi diretti', closed: euro(pnl.chiusi.costi_diretti),
      running: euro(pnl.in_corso.costi_diretti) },
    { label: 'Costo del lavoro', closed: euro(pnl.chiusi.costo_lavoro),
      running: euro(pnl.in_corso.costo_lavoro) },
    { label: 'Margine lordo', closed: euro(pnl.chiusi.margine_lordo),
      running: euro(pnl.in_corso.margine_lordo) },
    { label: 'Margine %', closed: percent(pnl.chiusi.margine_percentuale),
      running: percent(pnl.in_corso.margine_percentuale) },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {pnl.periodo_chiuso ? 'Periodo chiuso' : 'Periodo non chiuso'}
          {pnl.voci_scritte_in_ritardo > 0 &&
            ` · ${pnl.voci_scritte_in_ritardo} voci scritte in ritardo`}
          {!pnl.periodo_chiuso && ' — questi numeri possono ancora muoversi.'}
        </p>
        <Freshness calcolatoAlle={data.calcolato_alle} onRefresh={() => void query.refetch()} />
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card p-4" data-block="pnl">
        <table className="w-full text-sm">
          <caption className="mb-2 text-left text-sm font-medium">
            Conto economico del periodo — la <strong>cifra riportabile</strong> è la colonna
            «Deal chiusi». Le due colonne non si sommano.
          </caption>
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col" className="font-normal">Voce</th>
              <th scope="col" className="font-normal">Deal chiusi</th>
              <th scope="col" className="font-normal">Deal in corso</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <th scope="row" className="py-1 pr-3 text-left font-normal">{row.label}</th>
                <td className="py-1 tabular-nums">{row.closed}</td>
                <td className="py-1 tabular-nums text-muted-foreground">{row.running}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-muted-foreground">
          Spese generali del periodo: <strong>{euro(pnl.spese_generali)}</strong> — non
          ripartite su nessun deal.
        </p>
      </div>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Maturato e non fatturato — nel periodo</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Non sono ricavi e non entrano in nessun margine.
        </p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3 text-sm">
          <div>
            <dt className="text-muted-foreground">Valore maturato non fatturato</dt>
            <dd className="tabular-nums">{euro(pnl.valore_maturato)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Ore fatturabili non fatturate</dt>
            <dd className="tabular-nums">{hours(pnl.ore_fatturabili_non_fatturate)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Ore senza tariffa</dt>
            <dd className="tabular-nums">{pnl.ore_senza_tariffa}</dd>
          </div>
        </dl>
      </section>

      <div className="grid gap-4 sm:grid-cols-3">
        <div data-testid="da-incassare" className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">Da incassare</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {euro(data.da_incassare)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Totale con IVA. È un credito, non un ricavo: non entra in nessun margine.
          </p>
          {/* A subset, indented beneath its parent -- never a second addable line (§5.2). */}
          <p
            data-testid="scaduto"
            data-subset-of="da-incassare"
            className="mt-2 border-l-2 pl-3 text-sm text-muted-foreground"
          >
            di cui scaduto: <strong className="tabular-nums">{euro(data.scaduto)}</strong>
          </p>
        </div>
        <BigNumber label="Fatture emesse nel periodo" value={String(data.fatture_emesse)} />
        <div className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">Stima fiscale</p>
          <p className="mt-1 text-sm">
            <a href="/app/analisi/fiscale" className="underline underline-offset-2">
              Apri la stima fiscale
            </a>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Non è mostrata qui: una dashboard è la schermata che più facilmente finisce in
            uno screenshot.
          </p>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Write the operational tab**

```tsx
// apps/web/src/features/dashboard/OperationalTab.tsx
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { BigNumber, Sparkline, type SparkPoint } from './charts'
import { Freshness } from './Freshness'
import { useOperationalDashboard } from './queries'

/**
 * §6. One question: what do I have to do now. **No period, and no props** -- the current
 * week and a backlog are the two things that make no sense in the past.
 *
 * The second row is not a statistic: it is the real failure slice 4 §13 names when it
 * refuses a stopwatch -- "I never entered Tuesday". So the days are **named**, not counted,
 * and a day logged with `0.00` hours is not among them: somebody who entered a zero made a
 * statement about that day.
 */

function euro(value: string): string {
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    useGrouping: 'always',
  }).format(value as unknown as number)
}

function dayLabel(iso: string): string {
  // Built from the parts, in local time: `new Date("2026-03-19")` parses as UTC midnight
  // and formatting it back loses a day anywhere behind UTC.
  const [year, month, day] = iso.split('-').map((part) => Number.parseInt(part, 10))
  const local = new Date(year!, month! - 1, day!)
  return new Intl.DateTimeFormat('it-IT', { day: '2-digit', month: '2-digit' }).format(local)
}

export function OperationalTab() {
  const query = useOperationalDashboard()

  if (query.isError) return <QueryErrorBanner error={query.error} />
  if (query.isLoading || !query.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  const data = query.data
  const week = data.settimana
  // The tallest day, used only to scale the sparkline. Comparing two strings the server
  // sent, by length then lexically, avoids a numeric parse entirely: the values are
  // fixed-scale decimals, so a longer string is a larger number and equal lengths compare
  // correctly character by character.
  const tallest = week.giorni.reduce(
    (best, day) =>
      day.ore.length > best.length || (day.ore.length === best.length && day.ore > best)
        ? day.ore
        : best,
    '0.00',
  )
  const points: SparkPoint[] = week.giorni.map((day) => ({
    label: dayLabel(day.giorno),
    value: day.ore.replace('.', ','),
    // The one ratio on this page, and it is derived from a comparison of two server-sent
    // strings rather than from a parse. `0` when the week is empty.
    ratio: tallest === '0.00' ? 0 : day.ore.length / tallest.length === 1 ? 1 : 0.5,
  }))

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Freshness calcolatoAlle={data.calcolato_alle} onRefresh={() => void query.refetch()} />
      </div>

      <Sparkline caption="Ore per giorno — settimana corrente" points={points} />

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">
          {week.giorni_senza_ore.length === 0
            ? 'Settimana completa: nessun giorno scoperto'
            : `${week.giorni_senza_ore.length} giorni senza ore`}
        </h2>
        {week.giorni_senza_ore.length > 0 && (
          <>
            <ul className="mt-2 flex flex-wrap gap-2 text-sm">
              {week.giorni_senza_ore.map((day) => (
                <li key={day} className="rounded border px-2 py-0.5 tabular-nums">
                  {dayLabel(day)}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              Un giorno registrato con zero ore non è fra questi: zero è un valore, non
              un&apos;assenza.
            </p>
          </>
        )}
      </section>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Arretrato da fatturare — in totale</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Senza periodo: «quanto ho da fatturare» non è una domanda su un mese.
        </p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3 text-sm">
          <div>
            <dt className="text-muted-foreground">Ore fatturabili non fatturate</dt>
            <dd className="tabular-nums">
              {data.arretrato.ore_fatturabili_non_fatturate.replace('.', ',')} ore
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Valore maturato</dt>
            <dd className="tabular-nums">{euro(data.arretrato.valore_maturato)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Voci senza tariffa</dt>
            <dd className="tabular-nums">{data.arretrato.voci_senza_tariffa}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Segnali di incoerenza</h2>
        <ul className="mt-2 space-y-1 text-sm">
          {data.segnali.map((signal) => (
            <li key={signal.codice}>
              {signal.collegamento ? (
                <a href={signal.collegamento} className="underline underline-offset-2">
                  {signal.etichetta}
                </a>
              ) : (
                signal.etichetta
              )}
              : <strong className="tabular-nums">{signal.conteggio}</strong>
            </li>
          ))}
        </ul>
        {/* §6.2: the count sends nothing. There is deliberately no action here. */}
      </section>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Attività recenti</h2>
        {data.attivita_recenti.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Nessuna attività recente.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {data.attivita_recenti.slice(0, 20).map((activity) => (
              <li key={activity.id} className="text-muted-foreground">
                {activity.kind} · {activity.entity_type}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
```

The `ratio` expression above is deliberately crude, and the crudeness is the point: a faithful proportion would require dividing two decimal strings, which means parsing them. **A sparkline is a shape, not a measurement** — the table beneath it carries the values, and it is the accessible rendering. If a more faithful shape is ever wanted, the ratio belongs on the server as a field of `DayHours`, computed in `Decimal`; do not add a parse here.

- [ ] **Step 7: Wire the tabs into the route**

```tsx
// apps/web/src/routes/app/index.tsx -- replace the two placeholder paragraphs with the
// real tabs, and add the two imports.
import { EconomicTab } from '@/features/dashboard/EconomicTab'
import { OperationalTab } from '@/features/dashboard/OperationalTab'
// ...
      {tab === 'economica' && <EconomicTab periodo={periodo} />}
      {tab === 'operativa' && <OperationalTab />}
```

- [ ] **Step 8: Run the tests and watch them pass**

Run: `cd apps/web && pnpm exec vitest run && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS. `src/test/no-browser-arithmetic.test.ts` must stay green — if it flags either new tab, the offending line is a coercion that must become a formatter or a server-side field.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/lib/api-types.ts \
        apps/web/src/features/dashboard/queries.ts \
        apps/web/src/features/dashboard/EconomicTab.tsx \
        apps/web/src/features/dashboard/EconomicTab.test.tsx \
        apps/web/src/features/dashboard/OperationalTab.tsx \
        apps/web/src/features/dashboard/OperationalTab.test.tsx \
        apps/web/src/routes/app/index.tsx
git commit -m "feat(web): economic and operational dashboard tabs"
```

---

### Task C12: The fifth search branch — invoices, and the tenth trigram index

**Blocked on: the `invoices` table only, which exists today.** This task may be executed as soon as 6A is merged, ahead of the rest of 6C.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/models.py` (one index)
- Modify: `packages/core/src/pigrocrm/core/search/schemas.py` (`FISCAL_NUMBER_PATTERNS`)
- Modify: `packages/core/src/pigrocrm/core/search/repository.py` (`invoices`)
- Modify: `packages/core/src/pigrocrm/core/search/service.py` (one more group)
- Modify: `packages/core/migrations/versions/0009_dashboard_indexes.py` (the marked section)
- Modify: `packages/core/tests/test_migrations.py`
- Create: `packages/core/tests/test_search_invoices.py`
- Modify: `packages/core/tests/test_search_plan.py`, `packages/core/tests/corpus.py`
- Modify: `apps/web/src/features/search/queries.ts` — nothing changes; the `invoice` routes were declared exhaustively in Task A13

**Interfaces:**
- Consumes: `Invoice` with `causale String(200)`, `anno Integer | None`, `numero Integer | None`, `tipo`, `stato`, `deleted_at` — verified in the shipped model; `ScoredField`, `row_score`, `best_field`, `matches_any`, `WEIGHT_IDENTIFYING`, `WEIGHT_CAUSALE` (Task A7); `SearchGroup`, `SearchHit` (Task A7).
- Produces:
  - Index `ix_invoices_causale_trgm` — the tenth
  - `search/schemas.py`: `FISCAL_NUMBER_PATTERNS: tuple[re.Pattern[str], ...]` and `parse_fiscal_number(term: str) -> tuple[int | None, int] | None`
  - `SearchRepository.invoices(self, term: str, limit: int) -> SearchGroup`
  - `SearchResults.gruppi` gains a fifth group, always last
- Nothing later depends on this task.

**Why it was deferred out of 6A, and why it is safe to pull forward.** Spec §17 fixes 6A's dependency set as slices 1 and 2, so a fifth branch reading `invoices` would have made 6A un-releasable if slice 3 were rolled back. That reason is about release coupling, not about code: the only thing this branch needs is the `Invoice` model, which shipped with migration `0005`. Contradiction 11 records both halves.

**Two match paths, and the second is not a trigram search.** `causale` is free text and goes through the trigram index like every other field. But `(anno, numero)` is a *fiscal number*, and when the term looks like one — `2026/7`, `7/2026`, `7` — it is matched by equality, served by `uq_invoices_anno_numero`, the unique index slice 3 §3 already creates. Searching `7` as a trigram over `causale` would return every invoice mentioning a seven; matching it as a number returns invoice 7.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_search_invoices.py
"""§8.1's fifth branch: `causale` by trigram, and `(anno, numero)` by equality when the
term has the shape of a fiscal number.

The shape cases are the interesting half. `2026/7` and `7/2026` are both how people write
the same number, and `7` on its own means "invoice seven, this year" -- while `7` searched
as a trigram over `causale` means "every invoice whose description contains a seven", which
is not an answer.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import today_local
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.search.schemas import SearchQuery, parse_fiscal_number
from pigrocrm.core.search.service import SearchService

READONLY = Actor(id=uuid7(), type="user", role="readonly")


@pytest.mark.parametrize(
    "term,expected",
    [
        ("2026/7", (2026, 7)),
        ("7/2026", (2026, 7)),
        ("2026-7", (2026, 7)),
        ("7", (None, 7)),
        ("0007", (None, 7)),
        ("2026/007", (2026, 7)),
        # Not fiscal numbers.
        ("abc", None),
        ("2026/", None),
        ("/7", None),
        ("2026/7/3", None),
        ("999999999", None),  # beyond any plausible invoice number
        ("2026/0", None),     # invoice numbering starts at 1
    ],
)
def test_parse_fiscal_number(term: str, expected: tuple[int | None, int] | None) -> None:
    assert parse_fiscal_number(term) == expected


@pytest.fixture
def invoices(db_session: Session) -> Customer:
    customer = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(customer)
    db_session.flush()
    for anno, numero, causale in (
        (2026, 7, "Progettazione impianti elettrici"),
        (2026, 8, "Collaudo cabina di trasformazione"),
        (2025, 7, "Manutenzione annuale"),
    ):
        db_session.add(
            Invoice(
                customer_id=customer.id, tipo="fattura", stato="emessa",
                stato_pagamento="da_incassare", anno=anno, numero=numero,
                causale=causale,
                imponibile=Decimal("1000.00"), imposta=Decimal("0.00"),
                bollo=Decimal("0.00"), totale=Decimal("1000.00"),
                data_emissione=date(anno, 3, 1), tipo_documento="TD01",
                divisa="EUR", custom_fields={},
            )
        )
    db_session.flush()
    return customer


def _group(db_session: Session, term: str):
    results = SearchService(db_session).search_everything(
        SearchQuery(termine=term), READONLY
    )
    return next(group for group in results.gruppi if group.entity == "invoice")


def test_the_invoice_group_is_always_present_and_last(
    db_session: Session, invoices: Customer
) -> None:
    results = SearchService(db_session).search_everything(
        SearchQuery(termine="zzzqqq"), READONLY
    )
    assert [group.entity for group in results.gruppi] == [
        "customer", "person", "deal", "document", "invoice",
    ]


def test_the_causale_is_searchable_by_a_fragment(
    db_session: Session, invoices: Customer
) -> None:
    group = _group(db_session, "impianti")
    assert group.totale == 1
    assert "Progettazione" in group.hits[0].etichetta
    assert group.hits[0].campo == "causale"


def test_a_full_fiscal_number_finds_exactly_that_invoice(
    db_session: Session, invoices: Customer
) -> None:
    group = _group(db_session, "2026/7")
    assert group.totale == 1
    assert group.hits[0].etichetta.startswith("2026/7")
    # An exact fiscal-number match is a code match: weight 1.00, score 1.00.
    assert group.hits[0].punteggio == Decimal("1.0000")
    assert group.hits[0].campo == "numero"


def test_the_reversed_form_finds_the_same_invoice(
    db_session: Session, invoices: Customer
) -> None:
    assert _group(db_session, "7/2026").hits[0].etichetta.startswith("2026/7")


def test_a_bare_number_finds_that_number_in_every_year(
    db_session: Session, invoices: Customer
) -> None:
    """`7` alone has no year, so it matches invoice 7 of every year. Guessing the current
    year would hide last year's invoice 7 with nothing on screen to say so."""
    group = _group(db_session, "7")
    assert group.totale == 2
    assert {hit.etichetta.split(" ")[0] for hit in group.hits} == {"2026/7", "2025/7"}


def test_a_fiscal_number_term_does_not_also_trigram_the_causale(
    db_session: Session, invoices: Customer
) -> None:
    """`7` as a trigram over `causale` would match nothing here, but on a real corpus it
    matches every description containing a seven -- which is why the two paths are
    exclusive rather than combined."""
    group = _group(db_session, "2026/8")
    assert group.totale == 1
    assert group.hits[0].campo == "numero"


def test_a_draft_invoice_has_no_number_and_is_not_found_by_one(
    db_session: Session, invoices: Customer
) -> None:
    """`anno`/`numero` are NULL until emission -- that is what makes "a failed creation
    cannot burn a number" true by construction (slice 3). A draft is still findable by its
    causale."""
    db_session.add(
        Invoice(
            customer_id=invoices.id, tipo="fattura", stato="bozza",
            stato_pagamento="da_incassare", anno=None, numero=None,
            causale="Bozza da rivedere",
            imponibile=Decimal("0.00"), imposta=Decimal("0.00"),
            bollo=Decimal("0.00"), totale=Decimal("0.00"),
            tipo_documento="TD01", divisa="EUR", custom_fields={},
        )
    )
    db_session.flush()

    by_causale = _group(db_session, "rivedere")
    assert by_causale.totale == 1
    assert by_causale.hits[0].etichetta.startswith("bozza")


def test_a_soft_deleted_invoice_is_not_a_result(
    db_session: Session, invoices: Customer
) -> None:
    from datetime import UTC, datetime

    row = db_session.query(Invoice).filter(Invoice.numero == 8).one()
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert _group(db_session, "collaudo").totale == 0


def test_the_hit_carries_the_customer_as_its_subtitle(
    db_session: Session, invoices: Customer
) -> None:
    group = _group(db_session, "impianti")
    assert group.hits[0].sottotitolo == "Cliente Srl"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_search_invoices.py -v`
Expected: `ImportError: cannot import name 'parse_fiscal_number'`.

- [ ] **Step 3: Add the fiscal-number parser**

```python
# packages/core/src/pigrocrm/core/search/schemas.py -- append. Imports gain `import re`.

# The three shapes people actually write a fiscal number in. `re.fullmatch` throughout, so
# a trailing newline cannot smuggle a partial match through -- the project-wide rule, and it
# matters here because the term arrives from a query string.
_YEAR_FIRST = re.compile(r"(\d{4})[/\-](\d{1,6})")
_NUMBER_FIRST = re.compile(r"(\d{1,6})[/\-](\d{4})")
_BARE_NUMBER = re.compile(r"(\d{1,6})")

# An invoice number is at least 1 (slice 3's counter starts there) and no installation
# issues a million invoices a year. A bound exists so that a long digit string is treated as
# free text rather than as a number nobody has.
_MIN_INVOICE_NUMBER = 1
_MAX_INVOICE_NUMBER = 999_999
_MIN_YEAR = 2000
_MAX_YEAR = 2999


def parse_fiscal_number(term: str) -> tuple[int | None, int] | None:
    """`(anno, numero)` when the term has the shape of a fiscal number, else `None`.

    `2026/7`, `7/2026` and `2026-7` are all how the same number gets written. A bare `7`
    returns `(None, 7)` and matches invoice 7 in **every** year: guessing the current year
    would hide last year's invoice 7 with nothing on screen to say so.

    When this returns a value, the invoice branch matches by equality on `(anno, numero)` and
    does **not** also trigram the `causale`. The two paths are exclusive because `7` searched
    as a trigram means "every description containing a seven", which is not an answer to
    "show me invoice seven".
    """
    candidate = term.strip()

    match = _YEAR_FIRST.fullmatch(candidate)
    if match:
        anno, numero = int(match.group(1)), int(match.group(2))
        if _MIN_YEAR <= anno <= _MAX_YEAR and _MIN_INVOICE_NUMBER <= numero <= _MAX_INVOICE_NUMBER:
            return anno, numero
        return None

    match = _NUMBER_FIRST.fullmatch(candidate)
    if match:
        numero, anno = int(match.group(1)), int(match.group(2))
        if _MIN_YEAR <= anno <= _MAX_YEAR and _MIN_INVOICE_NUMBER <= numero <= _MAX_INVOICE_NUMBER:
            return anno, numero
        return None

    match = _BARE_NUMBER.fullmatch(candidate)
    if match:
        numero = int(match.group(1))
        if _MIN_INVOICE_NUMBER <= numero <= _MAX_INVOICE_NUMBER:
            return None, numero
    return None
```

`2026/7` matches `_YEAR_FIRST` before `_NUMBER_FIRST` can see it, and `7/2026` fails `_YEAR_FIRST` (the first group needs four digits) and then matches `_NUMBER_FIRST`. The order of the three attempts is therefore load-bearing and a comment says so above the constants.

- [ ] **Step 4: Add the branch**

```python
# packages/core/src/pigrocrm/core/search/repository.py -- append. Imports gain:
#   from pigrocrm.core.invoices.models import Invoice
#   from pigrocrm.core.search.schemas import parse_fiscal_number
#   from pigrocrm.core.search.scoring import SCORE_EXACT, WEIGHT_CAUSALE

INVOICE_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("causale", Invoice.causale, WEIGHT_CAUSALE),
)

    def invoices(self, term: str, limit: int) -> SearchGroup:
        """§8.1's fifth branch: `causale` by trigram, `(anno, numero)` by equality.

        The two paths are **exclusive**. When the term parses as a fiscal number, the
        equality path runs alone -- served by `uq_invoices_anno_numero`, the unique index
        slice 3 §3 already creates, so no new index is needed for it. Trigramming `7` over
        `causale` would return every invoice whose description contains a seven, which is not
        an answer to "show me invoice seven".
        """
        fiscal = parse_fiscal_number(term)
        if fiscal is not None:
            return self._invoices_by_number(*fiscal, limit=limit)
        group = self._group(
            "invoice", Invoice, INVOICE_FIELDS, term, limit,
            label=self._invoice_label,
            subtitle=lambda row: None,
        )
        return SearchGroup(
            entity=group.entity,
            hits=self._with_customer_names_for_invoices(group.hits),
            totale=group.totale,
            totale_e_un_minimo=group.totale_e_un_minimo,
        )

    @staticmethod
    def _invoice_label(row: Invoice) -> str:
        """`2026/7 — causale` when numbered, `bozza — causale` when not.

        `anno`/`numero` are NULL until emission, which is what makes "a failed creation
        cannot burn a number" true by construction (slice 3). A draft still has to be
        findable and readable, so the state stands in for the number rather than the label
        rendering "None/None".
        """
        prefix = (
            f"{row.anno}/{row.numero}"
            if row.anno is not None and row.numero is not None
            else row.stato
        )
        return f"{prefix} — {row.causale}" if row.causale else prefix

    def _invoices_by_number(
        self, anno: int | None, numero: int, *, limit: int
    ) -> SearchGroup:
        stmt = select(Invoice).where(
            Invoice.deleted_at.is_(None),
            Invoice.numero == numero,
        )
        if anno is not None:
            stmt = stmt.where(Invoice.anno == anno)
        rows = self.session.execute(
            stmt.order_by(Invoice.anno.desc(), Invoice.numero.desc()).limit(limit)
        ).scalars().all()
        total = self.session.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.deleted_at.is_(None),
                Invoice.numero == numero,
                *(() if anno is None else (Invoice.anno == anno,)),
            )
        ) or 0
        hits = [
            SearchHit(
                entity="invoice",
                id=row.id,
                etichetta=self._invoice_label(row),
                sottotitolo=None,
                # An exact fiscal-number match is a code match: weight 1.00 (§8.5's own
                # "un match su un codice è voluto"), score 1.00.
                punteggio=SCORE_EXACT.quantize(Decimal("0.0001")),
                campo="numero",
            )
            for row in rows
        ]
        return SearchGroup(
            entity="invoice", hits=self._with_customer_names_for_invoices(hits),
            totale=min(total, COUNT_CEILING),
            totale_e_un_minimo=total > COUNT_CEILING,
        )
```

`_with_customer_names_for_invoices` mirrors `_with_customer_names` from Task A8 exactly, joining `Customer` on `Invoice.customer_id` for at most `limit` rows after the limit — a label lookup, not an aggregate.

```python
# packages/core/src/pigrocrm/core/search/service.py -- one more line in `gruppi`, last:
                self.repo.invoices(term, limit),
```

Fifth and last, because the group order is fixed and a palette whose sections move between keystrokes cannot be driven with the keyboard.

- [ ] **Step 5: Add the tenth index**

```python
# packages/core/src/pigrocrm/core/invoices/models.py -- append to Invoice's __table_args__.
        # The tenth trigram index (spec §8.3). Partial on `deleted_at IS NULL` like the
        # other nine: it is the condition every search carries, so the index is smaller and
        # residuo R7 closes for this table too.
        Index(
            "ix_invoices_causale_trgm", "causale",
            postgresql_using="gin", postgresql_ops={"causale": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
```

```python
# packages/core/migrations/versions/0009_dashboard_indexes.py -- replace the marked line.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_invoices_causale_trgm ON invoices "
        "USING gin (causale gin_trgm_ops) WHERE deleted_at IS NULL"
    )
```

...and in `downgrade()`, before the activities index: `op.execute("DROP INDEX IF EXISTS ix_invoices_causale_trgm")`.

Add `"ix_invoices_causale_trgm"` to `HAND_MAINTAINED_INDEXES`; `test_every_trigram_index_is_a_partial_gin_index_over_gin_trgm_ops` picks it up automatically, because it iterates `TRGM_INDEX_NAMES`, which is derived from the set.

- [ ] **Step 6: Extend the corpus and the plan assertion**

```python
# packages/core/tests/corpus.py -- add `invoices: int` to CorpusScale (REFERENCE 5_000,
# INFLATED 50_000) and a fifth insert block after documents, guarded so the module still
# imports before slice 3's table exists:

    # Invoices, if the table is in the metadata. Guarded rather than assumed: this module is
    # imported by 6A's tests, which run on a tree where slice 3 may not be merged.
    if "invoices" in Base.metadata.tables and scale.invoices:
        invoice_rows: list[dict[str, object]] = []
        for index in range(scale.invoices):
            anno = 2017 + index % 10
            invoice_rows.append({
                "id": uuid7(),
                "customer_id": customer_ids[index % len(customer_ids)],
                "deal_id": deal_ids[index % len(deal_ids)] if index % 2 == 0 else None,
                "tipo": "fattura",
                "stato": "emessa",
                "stato_pagamento": "da_incassare" if index % 3 else "incassato",
                "anno": anno,
                "numero": index % 500 + 1,
                "causale": f"{rng.choice(_DEAL_WORDS)} {rng.choice(_SECTORS)} {index}",
                "imponibile": "1000.00",
                "imposta": "0.00",
                "bollo": "0.00",
                "totale": "1000.00",
                "data_emissione": f"{anno}-{index % 12 + 1:02d}-15",
                "tipo_documento": "TD01",
                "divisa": "EUR",
                "custom_fields": {},
            })
        session.execute(insert(Base.metadata.tables["invoices"]), invoice_rows)
```

Add `("invoices", Invoice, INVOICE_FIELDS)` to `_BRANCHES` in `test_search_plan.py`, importing `Invoice` and `INVOICE_FIELDS`, and add `"invoices"` to the `ANALYZE` loop and to the deletion order in the fixture's `finally` (before `deals`, since `invoices.deal_id` references it).

- [ ] **Step 7: Run, gate, commit**

Run: `uv run pytest packages/core/tests/test_search_invoices.py packages/core/tests/test_search_service.py packages/core/tests/test_migrations.py -v`
Expected: PASS. `test_every_group_is_present_even_when_empty` in `test_search_service.py` now expects five groups — update its literal in this task.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages/core/src apps/api/src apps/mcp/src`

```bash
git add packages/core/src/pigrocrm/core/invoices/models.py \
        packages/core/src/pigrocrm/core/search/ \
        packages/core/migrations/versions/0009_dashboard_indexes.py \
        packages/core/tests/test_migrations.py \
        packages/core/tests/test_search_invoices.py \
        packages/core/tests/test_search_service.py \
        packages/core/tests/test_search_plan.py \
        packages/core/tests/corpus.py
git commit -m "feat(search): invoices by causale and by fiscal number, closing R6"
```

---
### Task C13: Criterion 15 — the full cycle, from both adapters

**Blocked on: every other task of 6C.** This is the last task of the slice.

**Files:**
- Create: `apps/web/e2e/dashboard.spec.ts`
- Create: `apps/mcp/tests/test_full_cycle.py`
- Modify: `apps/web/e2e/helpers.ts` (one seeding helper)

**Interfaces:**
- Consumes: everything. The four MCP prompts (Task C8), `search_everything` (Task A11), `get_commercial_dashboard` (Task B12), the three dashboard tabs (Tasks B14, C11), `set_offer_state` through the UI (Task B6), the `sonner` toast (Task B14).
- Produces:
  - `apps/web/e2e/helpers.ts`: `export async function seedCycleFixture(page: Page): Promise<{ customerId: string; dealId: string; documentId: string; partitaIva: string }>`
  - Nothing importable from the Python side.

**Criterion 15 in full, as the six things it asks for.** Claude opens `revisione-pipeline`, reads the commercial dashboard, finds the stalled deal, and resolves the customer from a VAT fragment with `search_everything`; the human in the app accepts that deal's offer, sees the movement toast, sees the `system` entry in the timeline, and watches the "offerta accettata, deal non vinto" signal go **down by one**; the month's economic dashboard passes criterion 1; and Claude's attempt to change the automation configuration finds **no tool to call**.

It is split across two files because it is genuinely two surfaces: the agent half is a Python test against the in-process MCP server, the human half is Playwright against the real browser. Splitting it is not a weakening — the criterion's own structure is "Claude does this, the human does that", and a single harness driving both would have to fake one of them.

- [ ] **Step 1: Add the seeding helper**

```ts
// apps/web/e2e/helpers.ts -- append.

/**
 * One customer with a recognisable VAT number, one deal in an open stage, one offer on that
 * deal in state `inviata`, and a second offer already `accettata` on a *different* open deal
 * so the inconsistency signal starts at one and can be watched going to zero.
 *
 * Seeded through the API for the same reason `seedCustomers` is: doing it through the UI
 * would be testing the forms, and this spec is about the cycle.
 */
export async function seedCycleFixture(page: Page): Promise<{
  customerId: string
  dealId: string
  documentId: string
  partitaIva: string
}> {
  const partitaIva = '09876543210'
  const customer = await page.request.post('http://localhost:8000/api/customers', {
    data: { ragione_sociale: 'Ciclo Ingegneria Srl', partita_iva: partitaIva },
  })
  const customerId = (await customer.json()).id as string

  const stages = await page.request.get('http://localhost:8000/api/pipeline')
  const openStage = (await stages.json()).find(
    (stage: { tipo: string; code: string | null }) => stage.code === 'lead',
  )

  const deal = await page.request.post('http://localhost:8000/api/deals', {
    data: {
      nome: 'Ciclo — rifacimento impianti',
      customer_id: customerId,
      pipeline_stage_id: openStage.id,
      valore_previsto: '18000.00',
      probabilita: 60,
    },
  })
  const dealId = (await deal.json()).id as string

  const document = await page.request.post('http://localhost:8000/api/documents', {
    data: { deal_id: dealId, tipo: 'offerta', titolo: 'Ciclo — offerta impianti' },
  })
  const documentId = (await document.json()).id as string
  await page.request.post(
    `http://localhost:8000/api/documents/${documentId}/stato`,
    { data: { stato: 'inviata' } },
  )

  // A second, already-accepted offer on another open deal, so the signal starts above zero.
  const other = await page.request.post('http://localhost:8000/api/deals', {
    data: {
      nome: 'Ciclo — segnale preesistente',
      customer_id: customerId,
      pipeline_stage_id: openStage.id,
      probabilita: 50,
    },
  })
  const otherDealId = (await other.json()).id as string
  const otherDocument = await page.request.post('http://localhost:8000/api/documents', {
    data: { deal_id: otherDealId, tipo: 'offerta', titolo: 'Ciclo — offerta accettata' },
  })
  const otherDocumentId = (await otherDocument.json()).id as string
  await page.request.post(
    `http://localhost:8000/api/documents/${otherDocumentId}/stato`,
    { data: { stato: 'inviata' } },
  )
  // Accepting this one fires A1 and moves its deal to `vinto`, so it does *not* contribute
  // to the signal. Switch A1 off first, accept, then switch it back on: that leaves exactly
  // the state the signal exists to detect — an accepted offer whose deal was never moved.
  await page.request.put('http://localhost:8000/api/automation-config', {
    data: { a1_offerta_accettata_vince_deal: false },
  })
  await page.request.post(
    `http://localhost:8000/api/documents/${otherDocumentId}/stato`,
    { data: { stato: 'accettata' } },
  )
  await page.request.put('http://localhost:8000/api/automation-config', {
    data: { a1_offerta_accettata_vince_deal: true },
  })

  return { customerId, dealId, documentId, partitaIva }
}
```

Adjust the offer-state path and body to whatever `apps/api/src/pigrocrm_api/routers/documents.py` actually exposes for `set_offer_state`; the shipped router is the authority, not this snippet.

- [ ] **Step 2: Write the human half**

```ts
// apps/web/e2e/dashboard.spec.ts
/**
 * **Criterion 15**, the human half. The agent half is
 * `apps/mcp/tests/test_full_cycle.py`.
 *
 * Split across two files because it is two surfaces: the criterion's own shape is "Claude
 * does this, the human does that", and one harness driving both would have to fake one of
 * them.
 */
import { expect, test } from '@playwright/test'
import { login, seedCycleFixture } from './helpers'

test.describe('il ciclo completo — metà umana', () => {
  test('accettare un\'offerta muove il deal, si vede nel toast, nella timeline e nel segnale', async ({
    page,
  }) => {
    await login(page)
    const { dealId, documentId } = await seedCycleFixture(page)

    // 1. The signal, before.
    await page.goto('/app?tab=commerciale')
    const signalBefore = await page
      .getByRole('link', { name: /offerta accettata/i })
      .locator('xpath=../strong')
      .textContent()
    const before = Number.parseInt(signalBefore ?? '0', 10)
    expect(before).toBeGreaterThanOrEqual(1)

    // 2. Accept the offer, in the app, as a human would.
    await page.goto(`/app/documenti/${documentId}`)
    await page.getByRole('button', { name: /accett/i }).click()

    // 3. The immediate feedback §9.5 requires: the dialog says what *else* happened.
    await expect(page.getByText(/il deal è stato spostato in vinto/i)).toBeVisible()

    // 4. The timeline entry, attributed to the system and naming who triggered it.
    await page.goto(`/app/deal/${dealId}`)
    const entry = page.getByTestId('timeline').getByText(/automazione/i).first()
    await expect(entry).toBeVisible()
    await expect(page.getByTestId('timeline')).toContainText(/sistema/i)

    // 5. The signal, after: down by one. The card and its drill-through are the same
    //    predicate, so this is also criterion 2 observed live.
    await page.goto('/app?tab=commerciale')
    await page.getByRole('button', { name: /ricalcola/i }).click()
    await expect(
      page.getByRole('link', { name: /offerta accettata/i }).locator('xpath=../strong'),
    ).toHaveText(String(before - 1))
  })

  test('la card del segnale e il suo elenco dicono lo stesso numero', async ({ page }) => {
    await login(page)
    await seedCycleFixture(page)
    await page.goto('/app?tab=commerciale')

    const card = await page
      .getByRole('link', { name: /offerta accettata/i })
      .locator('xpath=../strong')
      .textContent()

    await page.getByRole('link', { name: /offerta accettata/i }).click()
    await expect(page).toHaveURL(/solo_deal_non_vinto=true/)
    // The drill-through re-runs live, so its row count is the authority when the two differ.
    await expect(page.getByRole('row')).toHaveCount(Number.parseInt(card ?? '0', 10) + 1)
  })

  test('le tre schede sono raggiungibili e il periodo è nell\'URL', async ({ page }) => {
    await login(page)
    await page.goto('/app?tab=economica&da=2026-03-01&a=2026-03-31')
    await expect(page.getByText(/fatturato \(imponibile, emesso\)/i)).toBeVisible()
    // The period survives a reload, which is the point of it being in the URL (§4).
    await page.reload()
    await expect(page.getByText(/fatturato \(imponibile, emesso\)/i)).toBeVisible()

    await page.goto('/app?tab=operativa')
    await expect(page.getByRole('table', { name: /ore per giorno/i })).toBeVisible()
    // The operational tab has no period picker (§6).
    await expect(page.getByLabel('Dal')).toHaveCount(0)
  })

  test('la stima fiscale è un link e non un numero', async ({ page }) => {
    await login(page)
    await page.goto('/app?tab=economica')
    await expect(page.getByRole('link', { name: /stima fiscale/i })).toBeVisible()
    for (const forbidden of [/imposta sostitutiva/i, /contributi/i, /netto stimato/i]) {
      await expect(page.getByText(forbidden)).toHaveCount(0)
    }
  })

  test('la ricerca globale trova il cliente da un frammento di partita IVA', async ({
    page,
  }) => {
    await login(page)
    const { partitaIva } = await seedCycleFixture(page)
    await page.goto('/app')
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('combobox').fill(partitaIva.slice(3, 8))
    await expect(
      page.getByRole('option', { name: /Ciclo Ingegneria Srl/ }),
    ).toBeVisible()
  })
})
```

- [ ] **Step 3: Write the agent half**

```python
# apps/mcp/tests/test_full_cycle.py
"""**Criterion 15**, the agent half. The human half is `apps/web/e2e/dashboard.spec.ts`.

Four things, in the order the criterion states them: open the prompt, read the dashboard,
find the stalled deal, resolve the customer from a VAT fragment. Plus the negative one that
is easiest to forget -- the attempt to change the automation configuration must find **no
tool to call**, and the assertion is on the absence of a tool rather than on a refusal,
because while residuo R10 is open (a PAT has no scopes and inherits its owner's full role) a
refusal is exactly what an admin token would not get.
"""

from typing import Any


async def test_the_agent_can_run_the_weekly_review_end_to_end(
    mcp_server: Any, cycle_fixture: Any
) -> None:
    # 1. Open the prompt. The context arrives inside it.
    rendered = await mcp_server.get_prompt("revisione-pipeline", {})
    briefing = str(rendered.messages)
    assert "Pipeline aperta per stato" in briefing
    assert "Offerte inviate in attesa" in briefing
    assert cycle_fixture.deal_name in briefing

    # 2. Read the dashboard as data, which is what a tool is for.
    board = await mcp_server.call_tool("get_commercial_dashboard", {})
    assert not board.is_error, str(board.content)
    payload = board.structured_content
    assert payload["offerte_in_attesa_totale"] >= 1

    # 3. The stalled deal is identifiable: the offer carries its age.
    stalled = [
        offer for offer in payload["offerte_in_attesa"] if offer["giorni"] is not None
    ]
    assert stalled, payload["offerte_in_attesa"]

    # 4. Resolve the customer from a fragment of its VAT number -- the use case §17 names as
    #    6A's reason to exist on its own.
    found = await mcp_server.call_tool(
        "search_everything", {"termine": cycle_fixture.partita_iva[3:8]}
    )
    assert not found.is_error, str(found.content)
    customers = next(
        group for group in found.structured_content["gruppi"]
        if group["entity"] == "customer"
    )
    assert cycle_fixture.customer_name in [hit["etichetta"] for hit in customers["hits"]]


async def test_the_agent_finds_no_tool_to_change_the_automation_configuration(
    mcp_server: Any
) -> None:
    """§11.1's single exclusion, observed from the agent's side.

    Asserted as an **absence of a tool**, not as a refusal: while residuo R10 is open a PAT
    carries no scopes and inherits its owner's full role, so an authorisation check would let
    an admin token straight through. Not registering the tool is the only enforcement that
    holds.
    """
    names = {tool.name for tool in await mcp_server.list_tools()}
    assert "update_automation_config" not in names
    assert not [name for name in names if "automation" in name and "update" in name]

    # And it is not reachable by another name either: `describe_automations` is read-only.
    described = await mcp_server.call_tool("describe_automations", {})
    assert not described.is_error
    assert set(described.structured_content) == {"configurazione", "regole", "esecuzioni"}


async def test_the_economic_dashboard_the_agent_reads_passes_criterion_one(
    mcp_server: Any, mcp_context: Any, cycle_fixture: Any
) -> None:
    """Criterion 1 through the MCP surface, not only through the API: §11.1's claim is that
    the tool returns *the same figures from the same owning service*, never a second
    version. This is that claim, checked."""
    from pigrocrm.core.analytics.schemas import PeriodPnlQuery
    from pigrocrm.core.analytics.service import AnalyticsService
    from pigrocrm.core.db import month_bounds, today_local

    today = today_local()
    da, a = month_bounds(today.year, today.month)

    result = await mcp_server.call_tool(
        "get_economic_dashboard", {"da": da.isoformat(), "a": a.isoformat()}
    )
    assert not result.is_error, str(result.content)

    direct = AnalyticsService(mcp_context.session).period_pnl(
        PeriodPnlQuery(da=da, a=a, customer_id=None), mcp_context.actor
    )
    assert result.structured_content["pnl"] == direct.model_dump(mode="json")


async def test_the_agent_sees_the_signal_and_the_automation_that_explains_it(
    mcp_server: Any, cycle_fixture: Any
) -> None:
    """The pair that makes the automation observable: the signal counts what did not happen,
    and `describe_automations` says why. Without both, "it did not fire" and "it was not
    supposed to fire" are the same empty screen (§9.5)."""
    board = await mcp_server.call_tool("get_commercial_dashboard", {})
    assert board.structured_content["offerte_accettate_deal_non_vinto"] >= 1

    described = await mcp_server.call_tool("describe_automations", {})
    reasons = {
        run.get("motivo") for run in described.structured_content["esecuzioni"]
    }
    assert reasons & {"regola_disattivata", "stage_bersaglio_assente", None}
```

`cycle_fixture` is a fixture added to `apps/mcp/tests/conftest.py` producing the same state `seedCycleFixture` produces, on the server's own session, and exposing `customer_name`, `deal_name` and `partita_iva`. It is a second implementation of the same setup, in the other language, and that is unavoidable: the two halves run in two processes with two harnesses.

- [ ] **Step 4: Run both halves**

Run: `uv run pytest apps/mcp/tests/test_full_cycle.py -v`
Expected: PASS, four tests.

Run: `cd apps/web && pnpm test:e2e`
Expected: PASS. `playwright.config.ts` runs `workers: 1, fullyParallel: false` against one database, so every fixture here uses the `Ciclo` prefix and every assertion is scoped to it.

- [ ] **Step 5: The whole slice, green**

Run from the repository root:

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/core/src apps/api/src apps/mcp/src
cd apps/web && pnpm exec vitest run && pnpm exec tsc --noEmit && pnpm lint && pnpm test:e2e
```

Expected: all green. This is the command sequence `.github/workflows/ci-deploy.yml` runs, in the same order.

- [ ] **Step 6: Commit**

```bash
git add apps/web/e2e/dashboard.spec.ts \
        apps/web/e2e/helpers.ts \
        apps/mcp/tests/test_full_cycle.py \
        apps/mcp/tests/conftest.py
git commit -m "test: criterion 15, the full cycle from both adapters"
```

---

## 6C is done. What the slice closed, and what it left open

| Item | State at the end of slice 6 |
|---|---|
| **R6** — search `ilike` with no index | **Closed** for all five searched entities, with the plan measured in CI and the index-removal check behind it. The declared remainder: a one- or two-character `search` on a *list* endpoint is still a scan, bounded by `limit ≤ 200`, reachable from no palette and no agent path |
| **R9** — the ordering §7 promised | **Closed** for `customers`, `people`, `deals`, `documents`, with a composite opaque cursor. **Open for every other surface**, and written as open: `time_entries` and `costs` are born ordered, `invoices` has its own filters, and the general defect on all remaining lists stands |
| **R7** — no partial index on `deleted_at` | **Closed for the five tables this slice indexes.** The general defect stands |
| **R5** — no audit for configuration | **Closed for `automation_config`.** Open for the rest |
| **R1** — shared MCP session | **Not closed here, and depended upon.** It is a task of slice 4's plan; 6C's MCP tasks are gated on it, Task C10 is its read-side verification, and no task works around it |
| **R10** — PAT without scopes | Untouched. It is the reason the fiscal estimate is in no prompt (§10.1) and the reason `update_automation_config` is enforced by *not registering a tool* rather than by a check |
| **R11**, **R14**, **R15** | Untouched, deliberately. The automations resolve by `code`, fall back to a unique `tipo` where one identifies a stage, and otherwise decline and record why; `deals.chiuso_il` gives the "when was this won" question a column instead of a mutable string |
| **R13** — `entity_type` in four places | **Untouched, and worth noting**: this is the first slice in four where the four-place extension was not needed, because the automations write on entities that already exist |
| **B2** — no debounce | Closed for the palette (250 ms). Open on the deal list |
| **B3** — the Kanban loads closed deals | Untouched. The dashboards are period-bounded from the first commit, so nothing here makes it worse |
| **A12**, **A14** | Untouched. Contradiction 7 records why A14 does not block this slice |
| slice 1 §10.1's missing header | **Closed** |
| `pipeline_stages` without a uniqueness constraint on `tipo` | **Newly surfaced by this slice and left open by decision**: a migration adding the constraint would refuse data an installation may have created for a reason. The automations decline instead of guessing |

---

## Self-review

Run against the spec with fresh eyes after the plan was complete. Findings were fixed inline; this section records what was checked and what changed.

### 1. Spec coverage

Every numbered section of `2026-08-20-slice-6-dashboard-e-ricerca-design.md`, mapped to the task that implements it.

| Spec | Task(s) |
|---|---|
| §2 prerequisites | The three sub-plan header tables, each verified against the tree; Contradictions 6, 7, 8, 11 |
| §3 provenance rule | B7 (the two exceptions), B8 (composition only), **B9** (the two AST clauses), C3, C4, C5, C6 |
| §4 commercial dashboard | B7, B8, B14 |
| §4.1 `chiuso_il` / `stato_dal` and the backfill asymmetry | B1 (the clock), B2 |
| §5 economic dashboard | C1 (the three period rows), C3, C4, C11 |
| §5.1 what "fatturato" means | C4, C11 |
| §5.2 "da incassare" uses `totale` | C3, C4, C11 |
| §5.3 what is deliberately absent | C4, C11 (link not number; no year-on-year; no featured deal margin) |
| §6 operational dashboard | C2, C5, C6, C11 |
| §6.1 the global feed and its index | C2 |
| §6.2 the four signals | B7 + B11 (the commercial one), C3 + C6 (the other three) |
| §6.3 the backlog belongs to `AnalyticsService` | C1 |
| §7 freshness and cost | B8, B14 (60 s + visible age), and the "no materialised summary" Global Constraint |
| §7.1 one endpoint, one transaction, one instant | B8, **B10**, C7 |
| §7.2 browser cache, card = drill-through | B11, B14, C6, C13 |
| §7.3 the measured budget | A9, C2 |
| §8.1–8.3 what is searched, trigrams, the indexes, the `ESCAPE` verdict | A2, A4, A7, A8, C12 |
| §8.4 R9, sort, the composite cursor | A3, A4, A5, A6 |
| §8.5 the score, the order, the count | A7, A8, A10, C12 |
| §8.6 the three interface states | A13, A14 |
| §9.1 two of the three are already derivations | Recorded in B5's docstring and in the `AutomationRunner` module docstring; no task implements them, which is the point |
| §9.2 A1 and A2, resolved by `code` | B5 |
| §9.3 inside the trigger's transaction, `*_in_transaction` | B4, B6 |
| §9.4 inherited idempotence | B5 |
| §9.5 four observability surfaces | B5 (timeline + non-execution), B14 (toast + settings page) |
| §9.6 configuration, R5 | B3 |
| §10 the four prompts | C8 |
| §10.1 the two prohibitions | C9 |
| §11.1 tools and the exclusion list | A11, B12, C1, C7 |
| §11.2 the endpoints | A11, B12, C1, C7 |
| §11.3 R1 | A11 Step 6, B12 Step 5, C7 Step 5, **C10** |
| §12 the data delta | A2, A3, B2, B3, C2, C12 |
| §13 the interface | A12, A13, B13, B14, C11 |
| §14 residui | The closing table of each sub-plan |
| §15 out of scope | Nothing implements it; the Global Constraints and the schema docstrings state each exclusion where it would otherwise be added |
| §16 criteria 1–15 | 1: C4 · 2: B11, C6 · 3: A9 · 4: A10 · 5: A14 · 6: B10, C7 · 7: B6 · 8: B5 · 9: B5 · 10: C9 · 11: A11, B9 · 12: C10 · 13: A6 · 14: B13 · 15: C13 |
| §17 three plans, in order | The document's structure, and the sub-plan order table |

**One gap found and closed during this review.** §5's row "Fatture emesse nel periodo (numero)" was sourced from "the same predicate as the revenue figure" but no task asserted that the two predicates actually match. Task C3's `count_emesse_in_periodo` docstring now states it and `test_count_emesse_in_periodo_counts_by_data_emissione` is the check; a stronger form — asserting the two SQL predicates are literally identical, as Task B11 does for the signal — was considered and rejected, because revenue is `AnalyticsService`'s and reaching into it to compare predicates would couple this slice to another's internals.

**Two things in the spec that did not become tasks, and why.**

- **§8.1's extension routes** (a `tsvector` column on `gmail_messages.body_text`, per-key indexes for custom-field values, `tsvector` for notes) are named in the spec as *boundaries*, not requirements — §15 lists all three as out of scope. They are recorded in `search/schemas.py`'s docstring so the next person finds the reasoning, and no task implements them.
- **§7's rejected alternatives** (a `dashboard_summary` table, a materialised view, a server-side cache) are decisions *against* building something. They are carried as a Global Constraint rather than as a task, because there is no test that can prove a table was not created — the closest thing is `test_migrations.py`'s `test_every_table_the_slice_needs_exists`, and adding "and no others" to it would fail on every future slice.

### 2. Placeholder scan

Searched the document for the failure patterns: `TBD`, `TODO`, `implement later`, `fill in`, `appropriate error handling`, `add validation`, `handle edge cases`, `write tests for the above`, `similar to Task`, `as above`, `etc.` in a code step.

Three findings, all fixed:

1. Task C12's `SearchRepository.invoices` carried an `if True else` expression from an earlier draft, followed by a paragraph correcting it. The method body is now written once, correctly, and the correcting paragraph is gone.
2. Task B6's `git add` block had a mistyped path (`packages ing/...`) and a note about the typo. The path is correct and the note is gone.
3. Task C2 carried a `test_recent_uses_its_own_index_and_not_the_entity_one` that was a docstring and an `importorskip` with no assertion in it — a placeholder wearing a test's name. **Found still present when this scan was run against the file rather than against memory**, and removed: the real plan assertion lives in `test_search_plan.py`, where the inflated corpus fixture exists, and C2 now points at it in prose instead of shipping an empty test.

Every code step in the document contains the code it asks for. Where a task consumes something another slice owns — slice 4's `AnalyticsRepository`, slice 3's `InvoiceService` — the Interfaces block names the exact signature and the step says *call it, do not reimplement it*, which is a constraint rather than a placeholder.

### 3. Type and signature consistency

Checked every name that crosses a task boundary.

| Name | Defined | Consumed | Consistent |
|---|---|---|---|
| `SortSpec`, `SortWhitelist`, `encode_cursor`, `decode_cursor`, `keyset_predicate`, `order_by`, `CURSOR_MAX_LENGTH` | A3 | A4, A5 | yes |
| `X_SORTS` (`CUSTOMER_SORTS`, `PERSON_SORTS`, `DEAL_SORTS`, `DOCUMENT_SORTS`) | A4 | A4, A5 | yes |
| `SearchQuery.termine` / `.limite`; `q` / `limit` at HTTP | A7 | A8, A11, A13, C12 | yes — the query-string names differ from the field names by design (§11.2 fixes `q`), and Task A11 says so |
| `SearchGroup.totale` / `.totale_e_un_minimo` | A7 | A8, A13, C12 | yes |
| `ScoredField(name, column, weight)` positional | A7 | A8, C12 | yes |
| `today_local`, `month_bounds`, `window_from`, `current_week` | B1, B8, C5 | B2, B5, B7, B8, C3, C5, C6, C8 | yes — all four live in `db/clock.py` and are re-exported from `pigrocrm.core.db` |
| `AutomationSkipReason` values | B3 | B5, B14 | yes — `gia_nello_stato` without the accent in all four places, matching the Global Constraints' identifier list |
| `set_stage_in_transaction(deal, stage)` | B4 | B5 | yes — no `actor` parameter, asserted in B4 |
| `AutomationRunner.on_offer_state_changed(document, previous, actor)` | B5 | B6 | yes |
| `PipelineStageSummary`, `ClosedInPeriod`, `PendingOffer`, `Periodo`, `PeriodoQuery` | B7, B8 | B8, B12, B14, C4 | yes |
| `DashboardService._open_snapshot`, `SNAPSHOT_ISOLATION` | B8 | B10, C4, C6, C7 | yes |
| `AnalyticsService.period_pnl(query, actor)` / `unbilled_backlog(actor)` | slice 4 / C1 | C4, C6, C8 | yes — the spec's own `get_*` spelling appears nowhere as a *service* call; it survives only where it is correct (the MCP tool names) and where the Contradictions section quotes the spec. Contradiction 2 records the resolution |
| `PnlTotals.costo_lavoro` | slice 4 | C4, C8, C11 | yes — not `costo_del_lavoro`, which is the prose label; the field is `costo_lavoro` |
| `InvoiceRepository.{sum_da_incassare,sum_scaduto,count_emesse_in_periodo,count_deals_invoiced_not_won,count_scadute_non_incassate,unpaid_for_customer}` | C3, C8 | C4, C6, C8 | yes |
| `WeekHours`, `DayHours` | C5 | C6, C11 | yes |
| `UnbilledBacklog` | C1 | C6, C8, C11 | yes |
| `Signal.{codice,etichetta,conteggio,collegamento}` | C6 | C7, C11 | yes |
| `queryKeys.dashboard(kind, params)` / `.search(term)` / `.automations()` | A12, B14 | B14, C11 | yes |
| `BigNumber`, `BarRows`, `BarRow`, `Sparkline`, `SparkPoint` | B13 | B14, C11 | yes |
| `Periodo` (TS) / `currentMonth` / `presetQuarter` / `presetYear` | B14 | B14, C11 | yes |
| `MCP_EXCLUDED_SLICE6`, `_audited_services_slice6` | A11 | B12, C1, C7 | yes — and slice 4's `MCP_EXCLUDED` is untouched, asserted in A11 |
| `parse_fiscal_number` | C12 | C12 | yes |

One further correction made during this pass: Task C6's `OperationalDashboard.attivita_recenti` was typed `list[ActivityRead]`, while Task C2 produces `list[Activity]` (ORM rows) from `ActivityRepository.recent`. The service now converts with `ActivityRead.model_validate`, which is stated in C6's service snippet — a repository returning ORM rows and a schema field expecting Pydantic models is exactly the mismatch that surfaces as a `ValidationError` on the first request.

---

## Execution handoff

Plan complete. **Execute the sub-plans in order — 6A, then 6B, then 6C — and do not interleave them:** 6A changes the list endpoints' signature, and building the dashboards first means regenerating the TypeScript client and re-typing every call site twice.

Before starting each sub-plan, work through its prerequisite table against the tree. Three of those checks have already changed once while this plan was being written — slice 3 landed two migrations and eight tasks — so the numbers in this document are a starting point for verification, not a substitute for it. In particular: **run `ls packages/core/migrations/versions/` before writing any migration file**, and re-run the R1 grep before registering any MCP tool.

