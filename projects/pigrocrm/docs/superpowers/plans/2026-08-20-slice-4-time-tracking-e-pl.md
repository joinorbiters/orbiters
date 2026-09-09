# PigroCRM Slice 4 — Time tracking, costi, P&L e preventivo vs consuntivo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record hours and costs against deals with the sale rate and internal cost frozen onto every row, lock reported periods against back-dated writes, ship a client-ready timesheet as PDF and XLSX, then — once slice 3 is in `main` — derive a per-deal and per-period profit and loss whose revenue *is* the invoice, a pro-rata estimate-versus-actual report, and an annual fiscal estimate.

**Architecture:** Two new domain packages in `packages/core` — `timetracking/` (hours, costs, cost categories, period locks, rates, the report) and `analytics/` (P&L, budget, the invoice bridge, the fiscal estimate) — plus one new shared module, `money.py`, that is the single authority on `Decimal` rounding. Neither package knows anything about HTTP or MCP: the FastAPI routers in `apps/api` and the MCP tools in `apps/mcp` import the same service classes in-process, and `packages/core/tests/test_architecture.py` keeps the dependency direction one-way and — new in this slice — keeps ten named methods off the MCP surface mechanically. Every economic total is computed in a service and returned already summed; the browser never adds money.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · psycopg 3 · PostgreSQL 17 · MCP SDK v2 · openpyxl · Pandoc 3.1.12.2 · Typst 0.11.0 · pytest + testcontainers · Vite · React 19 · TanStack Router/Query/Table · shadcn/ui · Tailwind v4 · Playwright

**Spec:** `docs/superpowers/specs/2026-08-20-slice-4-time-tracking-e-pl-design.md`

**Scope:** This is **one document holding two plans**, exactly as the spec's §16 requires. **Plan 4A** (Tasks 4A-1 … 4A-20) depends only on slices 1 and 2 and is shippable on its own. **Plan 4B** (Tasks 4B-1 … 4B-12) depends on 4A *and on slice 3 being merged into `main`* — see "Plan 4B — what must exist before it can start" for the plain statement of why. Do not begin 4B while `packages/core/src/pigrocrm/core/invoices/` does not exist.

---

## Global Constraints

These apply to **every** task in both plans. They are not repeated per task. Everything from `## Global Constraints` in the three earlier plans (`2026-08-06-slice-1a-backend.md`, `2026-08-06-slice-1b-frontend.md`, `2026-08-10-slice-2-documenti-e-template.md`) that still applies is carried here with its exact values; the last block is new to this slice.

### Carried from plan 1A (backend)

- **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Managed by **uv workspaces**. Do not use pip, poetry, or venv directly.
- **`packages/core` must never import from `apps.`** — enforced by `packages/core/tests/test_architecture.py`. That test is an *allowlist*: core may import the stdlib, the `pigrocrm` namespace, and only what `packages/core/pyproject.toml` declares under `[project].dependencies`. If a task seems to require anything else, either declare the dependency there or the design is wrong; stop and flag it.
- **Services receive and return Pydantic models only.** No `Request`, `Response`, `HTTPException`, or status codes inside `packages/core`.
- **Every service method that writes takes `actor: Actor`** as an explicit parameter. Never read the actor from global or contextual state.
- **One service method = one transaction.** The service commits; repositories never commit.
- **Money is `Numeric(12, 2)`; hours are `Numeric(8, 2)`.** Never `Float` for either. (This slice adds a third type — see "New to slice 4" below.)
- **All timestamps are `TIMESTAMP WITH TIME ZONE` in UTC.** Use `from datetime import UTC, datetime` → `datetime.now(UTC)`, matching `db/base.py`, never `datetime.utcnow()`.
- **All primary keys are UUIDv7** via the shared `pigrocrm.core.db.base.uuid7` wrapper, never `uuid_utils` directly in a model.
- **Soft delete**: entities carry `deleted_at`. Repository queries filter `deleted_at IS NULL` unless explicitly asked otherwise. No physical delete exists anywhere in this slice either.
- **Tests use real PostgreSQL via testcontainers.** Never SQLite — JSONB and GIN indexes do not exist there. Use the existing `db_engine`/`db_session` fixtures in `packages/core/tests/conftest.py`.
- **TDD is mandatory for `packages/core`.** Write the failing test, watch it fail, then implement.
- **Commit after every task**, using the message given in the task's final step.
- **UI language is Italian.** Field labels, buttons, and error messages shown to users are Italian. Code identifiers, table names, and column names are English except the Italian fiscal and domain terms already fixed in slices 1–2 (`partita_iva`, `codice_fiscale`, `codice_sdi`, `pec`, `ragione_sociale`, `indirizzo`, `cap`, `comune`, `provincia`, `nazione`, `tipo`, `titolo`, `stato`, `versione_corrente`, `numero`, `sorgente_markdown`, `variabili`, `variabili_dichiarate`, `corpo_markdown`, `attivo`, `creato_da`, `dimensione`) and the ones this slice's spec fixes (`ore`, `data`, `importo`, `descrizione`, `fatturabile`, `tariffa_applicata`, `costo_applicato`, `tariffa_origine`, `costo_origine`, `note_interne`, `tariffa_oraria`, `tariffa_oraria_default`, `costo_orario_default`, `fornitore`, `posizione`, `archiviata`, `anno`, `mese`, `chiuso_il`, `chiuso_da`, `ricavi`, `costi_diretti`, `costo_lavoro`, `margine_lordo`, `margine_percentuale`, `valore_maturato`, `avanzamento_ore`, `budget_pro_rata`, `scostamento_valore`, `coefficiente_redditivita`, `aliquota_imposta_sostitutiva`, `aliquota_inps`).
- **The `Expected: PASS (N passed)` counts are indicative, not contractual.** Parametrised tests expand to different totals than the number of test functions. What matters is that every test passes and none is skipped — a differing total is not a failure and must not be "fixed" by deleting or merging cases.
- **A uniqueness pre-check never replaces the database constraint.** Wherever a service does "SELECT to check, then INSERT", it must also catch `sqlalchemy.exc.IntegrityError` around the commit, `session.rollback()`, and re-raise the domain `Conflict`. Two concurrent requests both pass the SELECT; only the constraint stops the second, and without the rollback the caller's session is left poisoned (`PendingRollbackError` on its next statement).
- **Case-insensitive uniqueness needs a functional index, not a convention.** A plain `unique=True` on a text column is case-sensitive. Where identity is case-insensitive, declare `Index("uq_…", func.lower(col), unique=True)` in `__table_args__`.
- **A method named `list` must be the LAST method defined in its class.** `def list(...)` rebinds `list` in the *class* namespace, so any later method annotated `-> list[Something]` resolves it to that method and raises `TypeError: 'function' object is not subscriptable` at import time. Python 3.13 evaluates annotations eagerly, so this is a hard failure here; 3.14's PEP 649 would hide it. Calling `self.list()` from an earlier method is fine — that is a call-time attribute lookup, not an annotation. The rule is unconditional: do not reason about whether a later method *currently* returns a `list[...]`. `packages/core/tests/test_module_imports.py` is the real guard; keep it green.
- **Every `Numeric(p, s)` column needs a matching Pydantic `Field(max_digits=p, decimal_places=s)`** on both schemas. Without it, a value beyond the column's capacity reaches Postgres and raises `NumericValueOutOfRange` — an uncaught `DataError`, not an `IntegrityError`, so no handler catches it and the session is poisoned — and a sub-scale value like `Decimal("0.005")` is silently rounded by the database while `expire_on_commit=False` (`db/session.py`) leaves the object returned to the caller still reporting the original. **Reject rather than round.**
- **Every `String(n)` column needs a matching Pydantic `max_length=n`** on both the Create and the Update schema. Without it an over-long value reaches Postgres, raises `sqlalchemy.exc.DataError` — **not** a subclass of `IntegrityError` — and poisons the session. Where an exact-format check bounds the length, that check must use **`re.fullmatch`, never `re.match` with `$`**: Python's `$` matches before a trailing newline, so `^\d{11}$` accepts a 12-character string and the value still reaches the database. **This rule applies to every regex in this slice**, the `AAAA-MM` period key included, whether or not it is database-bound.
- **Every `Integer` column needs a bounded Pydantic field** (`Field(ge=…, le=…)`) on both schemas, picked to be defensible for that field's meaning. Without a bound, `2**40` reaches Postgres raw as `IntegerOutOfRange`. **Exception, not violation**: a field already fully bounded by an equivalent service-level range check does not also need a schema-level bound — adding one changes which exception type fires (`pydantic.ValidationError` instead of this project's own `ValidationFailed`) for a value the service already rejects correctly, which is a regression. Document any omission in a comment.
- **A NUL byte (`"\x00"`) in a native `String`/`Text` field is rejected, not stored.** Use the shared `pigrocrm.core.validation.SafeStr` annotated type on every user-supplied string field on every Create/Update schema, including inside `list[str]` fields. Reject, never strip. A field already passing through a transformation that structurally cannot leave a NUL byte behind does not need `SafeStr` layered on top — document why rather than adding a check that can be shown to never fire.
- **Every foreign key column is validated against the table it references, in both `create` and `update`**, including one that is optional (`nullable`) — a nullable FK is skipped only when the caller supplies nothing, never when the caller supplies a value. Without this, any syntactically valid UUID reaches `flush()`/`commit()` and comes back as a raw `ForeignKeyViolation` instead of this project's own `NotFound`.
- **Escape LIKE metacharacters in every search filter.** Use the shared `pigrocrm.core.db.escape_like` helper, escape `\`, `%` and `_` (backslash first), and pass `escape="\\"`.
- **Pagination `limit` must be bounded** — `Field(ge=1, le=200)` on the query schema, not only on the router.
- **On update, validate only the custom-field keys the caller supplies**, not the merge of stored and supplied. A supplied key with value `None` removes that entry — and must work even when its definition is archived, no longer exists, or is optional. It must **not** work when the key's current definition is active and `required=True`. Untouched stored keys pass through unchanged, archived ones included.

### Carried from plan 1B (frontend)

- **No `fetch` inside components.** Every request goes through the generated client wrapped in TanStack Query hooks.
- **The API client is generated, never handwritten.** `openapi-typescript` reads `openapi.json` from the running API (`pnpm generate:api`). A contract change must break `tsc`, not production.
- **No business logic in the frontend.** Validation messages come from the API's problem documents. Recomputing a rule client-side is how the three interfaces start disagreeing.
- **No component file over ~250 lines.** If a file approaches the limit, extract.
- **UI language is Italian.** Every visible label, button and message.
- **TypeScript strict mode**, no `any`, no `@ts-ignore`.
- **Commit after every task.**
- **Form state keeps `{native, custom}` as two namespaces, decided once at seed time and never re-derived at submit.** Provenance is structural. A native column clears on `""` and only on `""`; a custom field clears on `null` and only on `null`; an omitted key clears nothing. `0` and `false` are values, never blanks — mirror `is_blank` exactly. Never sum money as a JS float; format `Numeric` values as the strings the API sends.
- **`DynamicForm` takes a required, undefaulted `mode: 'create' | 'edit'` prop.** Every new call site answers the question explicitly.
- **A failed request must never look like an empty result.** A query in `isError` renders `QueryErrorBanner`, never an empty table or an empty list.
- **`DataTable` is TanStack Table v9.** `ColumnDef` takes `<TFeatures, TData, TValue>`; instantiate every column array as `ColumnDef<DataTableFeatures, Row>[]`. `useReactTable`/`getCoreRowModel` do not exist in 9.0.0, and `useLegacyTable` is `@deprecated` — do not reach for it.
- **`Intl.NumberFormat('it-IT')` always takes `useGrouping: 'always'`.** it-IT's default withholds the thousands separator until the integer part has five digits (`Intl.NumberFormat('it-IT').format(2500.5)` → `"2500,50"`), so a four-figure total silently loses its separator without it.
- **`new Date("YYYY-MM-DD")` parses as UTC midnight.** Formatting it with `Intl.DateTimeFormat` renders in the browser's zone, so anywhere behind UTC the date loses a day. Build the `Date` from its year/month/day parts in local time (`new Date(year, month - 1, day)`).

### Pinned versions

Backend (slice 1A, resolved and verified 2026-08-06 — unchanged): `fastapi 0.141.1` · `uvicorn 0.52.1` · `sqlalchemy 2.0.51` · `alembic 1.19.0` · `psycopg[binary] 3.3.4` · `pydantic 2.13.4` · `pydantic-settings 2.14.2` · `email-validator 2.3.0` · `argon2-cffi 25.1.0` · `pyjwt[crypto] 2.13.0` · `mcp 2.0.0` · `uuid-utils 0.17.0` · `pytest 9.1.1` · `pytest-cov 7.1.0` · `pytest-asyncio 1.4.0` · `testcontainers[postgres] 4.15.0` · `httpx 0.28.1` · `ruff 0.16.1` · `mypy 2.3.0`

Slice 2 toolchain (unchanged): `PANDOC_VERSION=3.1.12.2` · `TYPST_VERSION=0.11.0`, build args in `Dockerfile.api`.

Frontend (slice 1B — unchanged): `vite 8.2.0` · `react 19.2.8` · `react-dom 19.2.8` · `typescript 5.9` (**not** 7.x) · `@tanstack/react-router 1.170.20` · `@tanstack/router-plugin 1.168.25` · `@tanstack/react-query 5.101.4` · `@tanstack/react-table 9.0.0` · `tailwindcss 4.3.3` · `@tailwindcss/vite 4.3.3` · `shadcn 4.16.1` (CLI) · `@dnd-kit/core 6.3.1` · `@dnd-kit/sortable 10.0.0` · `openapi-typescript 7.13.0` · `openapi-fetch 0.17.0` · `@playwright/test 1.62.1` · `lucide-react` latest · `@tabler/icons-react` latest (**brand icons only**). Package manager: **pnpm 10**.

**New to this slice:** `openpyxl==3.1.5`, added to `packages/core/pyproject.toml` `[project].dependencies` (Task 4A-15). It goes on **core**, not on `apps/api`, because `packages/core/tests/test_architecture.py` derives its allowlist from core's own declared dependencies and the workbook builder is a domain function — the API image installs core's dependencies anyway, which is what the spec's "nell'immagine dell'API" means in practice. `3.1.5` is the pin verified at plan-writing time; if `uv lock` resolves a different version, update the pin in the same commit rather than leaving the two out of step. New AST-parsing test dependency: none — `ast` is stdlib, and the frontend guard (Task 4A-16) parses TypeScript with the `typescript` compiler package already in `apps/web`.

### Design tokens (exact values — do not improvise)

| Token | Hex | Role |
|---|---|---|
| Watermelon | `#ED254E` | primary action, destructive state |
| Royal Gold | `#F9DC5C` | warning, attention |
| Mint Cream | `#F4FFFD` | app background (light) |
| Prussian Blue | `#011936` | foreground text, dark surface |
| Charcoal Blue | `#465362` | muted / secondary text |

Font: **Outfit** only. `Reenie Beanie` belongs to the landing page in slice 5 — do **not** load it here. Contrast must reach **WCAG AA**; for body copy on light backgrounds use Prussian Blue.

### New to slice 4

- **Three numeric types, not two.** Money and every P&L row is `Numeric(12,2)`; hours are `Numeric(8,2)`; **factors — every hourly rate and internal cost — are `Numeric(12,6)`**. The third type is imposed by slice 3: `invoice_lines.prezzo_unitario` is `Numeric(12,6)`, and a rate at two decimals would change value the moment hours became an invoice line, breaking the reconciliation of 4B by a few cents for reasons nobody could reconstruct. A rate and a unit price are the same quantity seen from two tables, so they carry the same precision.
- **`ROUND_HALF_UP`, per row, then sum the already-rounded rows.** `valore_riga = ROUND(ore × tariffa_applicata, 2)`; an aggregate is `Σ valore_riga`, never `ROUND(Σ exact, 2)`. Half-up, not half-even: Italian fiscal practice, inherited from slice 3 §6.1. When the two disagree, the printed rows win — the row value is what the timesheet prints next to each entry.
- **No `float`, anywhere, in any language.** `Decimal` in the service, `Numeric` in Postgres, totals computed by the service and returned already summed. The **only** arithmetic permitted in the browser is adding the hours visible in one week, in integer hundredths, through `scaledFromDecimalString` (Task 4A-16). Task 4A-16 ships an AST test that fails the build if any module under `apps/web/src` applies `Number()`, `parseFloat` or `+` to an economic field coming from the API.
- **A rate is resolved once, at write time, and copied onto the row.** No report ever reads `deals.tariffa_oraria` or `users.tariffa_oraria_default`. `tariffa_applicata`/`costo_applicato` on the row are the only authority, and `tariffa_origine`/`costo_origine` record which level answered.
- **`time_entries.data` and `costs.data` are `Date`, never `timestamptz`.** They are calendar days, not instants; a `toISOString()` projection moves everything after 23:00 CET by a day and everything on the 31st by a month, straight into the wrong monthly report. Back-dating is allowed with **no year floor** (unlike slice 3's `data_emissione`); a **future** date is refused.
- **Nothing dated inside a closed period may be written.** Creating, moving, re-houring or deleting a `time_entry` or a `cost` whose `data` falls in a month present in `period_locks` raises `Conflict` naming the month and who closed it. On an update, **both** the old and the new date are checked — moving a row out of a closed month is still a write into it.
- **`period_locks` governs only this slice's two tables.** Invoices have their own immutability rules (slice 3 §4) and do not get a second one.
- **No user input ever reaches a command line** (carried from slice 2, unchanged): `subprocess.run` always with an argument *list*, never `shell=True`, always `timeout=RENDER_TIMEOUT_SECONDS` (`30`), always `check=False`. Every path in the argument list is generated by the service from `tempfile.mkdtemp()`.
- **Escaping is decided by context and applied exactly once, to the domain value.** Descriptions are stored raw, multi-line, unescaped; `escape_for` (slice 2) prepares them at render. The XLSX passes through no escaper at all — it writes values as cell values. No value ever traverses two escapers.
- **Every change to a rate column, a cost category or a fiscal parameter writes an activity.** R5 stays open in general; it closes here for the tables this slice touches, because the timeline is what reconstructs when a rate changed — and it is the reason §5 can afford not to historicise rates at all.

---

## Blocking prerequisites — three residuals that are tasks in this plan, not assumptions

`docs/superpowers/specs/2026-08-07-slice-1a-residui.md`, in its **2026-08-20 update**, promotes three residuals from "to be decided" to "blocking prerequisites, owner: slice 4". This plan does not assume any of them is fixed and does not fix any of them as a side effect: **each has its own named task**, and each task exists because the spec assigns the work here (§4.6, §9.2, §12). Nothing else in this plan may be started before the two 4A prerequisites are green.

| Residual | The measured evidence | Where it is fixed | What stays open |
|---|---|---|---|
| **R1** — `apps/mcp/src/pigrocrm_mcp/__main__.py` builds **one** SQLAlchemy `Session` and passes `lambda: session` to `build_server` for the whole process lifetime; the SDK dispatches sync calls concurrently. Reviewer's measurement on slice 1A: **10 concurrent `create_customer` → 0 successes and 0 rows**, with `Method 'rollback()' can't be called here` and `This session is provisioning a new connection; concurrent operations are not permitted`. `log_time` is a **write** tool and is the centre of this slice's agentic surface. | **Task 4A-1.** | Nothing about the API adapter changes; `deps.get_session` already hands each request its own session. R2 (the SDK validating some arguments before `_guard` runs) is untouched — every new strict scalar in Task 4A-13 uses the existing `WithJsonSchema` technique so no *new* raw pydantic dump is added, which is not the same as closing R2. |
| **A13** — `FieldDefinitionService.create` (`fields/service.py:41`) checks the slug against other *definitions* only, never against `native_fields()`. This slice's native columns are literally named `ore`, `data`, `importo`, `descrizione` — the first labels anybody would type defining a custom field on an hours entry. A field labelled «Ore» slugifies to `ore`, the API answers 201, and every later write lands in `custom_fields.ore` instead of the real column with nothing protesting. | **Task 4A-2.** | The guard covers `create` only. `FieldDefinitionUpdate` has no `key` field (the key is immutable), so there is no update path to guard — verified, and documented in the task rather than asserted. |
| **A14** — `Update` schemas are applied with `exclude_none=True`, so no spelling clears a numeric native column. `ore_preventivate` therefore has exactly two reachable states — `NULL` and `0.00` — which mean **opposite** things to the estimate-versus-actual report, and only `0.00` is writable: `""` gives 422, `null` is dropped by `exclude_none`, an omitted key does nothing. Slice 3 sidestepped A14 by replacing invoice lines wholesale; that exit does not exist here. | **Task 4B-1.** | The change is a contract change on every service's `update`. Task 4B-1 converts all of them and ships the parity tests; it does not add a general "clear any field" facility, and the secondary defence stays in place regardless — `ore_preventivate = 0` is treated as "not comparable", never as a denominator. |

Residuals this plan deliberately does **not** close, so nobody reads silence as a fix: **R5** (audit trail closes for rates, cost categories and fiscal parameters only), **R7** (the four new tables are born with the right partial indexes; the general gap remains), **R9** (`time_entries` and `costs` are born ordered by `data`; the general sorting gap remains), **R10** (PATs are still unscoped — which is precisely *why* §11's defence is structural), **R3** (answered concretely for `user_id`: `get_active` on write, plain `get` on read, so a deactivated user's hours stay in the P&L and in the PDF with their name; the same answer is *proposed* for `deals.owner_id` and not implemented), **B3** (the margins view is paginated with a mandatory period filter from the first commit; the Kanban's own unbounded load is untouched), **R12**, **R13** (restated in its correct form: the database is open, the type is extended in four places, no migration).

---

## Contradictions between the spec and the shipped code, and how they were resolved

Resolved in favour of the shipped code, as instructed. Each is implemented in the task named.

1. **`fiscal_profile` does not exist at all — slice 3 is not merged.** The spec's §4.5 says `fiscal_profile` "lacks the fiscal columns slice 1 promised" and proposes adding `coefficiente_redditivita`, `aliquota_imposta_sostitutiva` and `aliquota_inps` to slice 3's single row rather than creating a second profile. **Verified against the shipped code: the premise is stronger than the spec states.** `packages/core/src/pigrocrm/core/` contains `activities auth customers db deals documents emitter fields people pipeline render storage templates` and no `invoices/` or `fiscal/`; `grep -rn "fiscal_profile" packages apps` returns nothing; the migration chain stops at `0003_documents_templates_emitter.py`. There is no table to add columns to yet. **Resolution:** the spec's *decision* holds unchanged — one profile row, not a second — and the three columns are added by **Task 4B-2** as an `ALTER TABLE fiscal_profile` in migration `0005`, which is one more concrete reason 4B cannot start before slice 3 lands. Plan 4A must not create a `fiscal_profile` of its own; the fiscal report is 4B's, and 4A ships without it.
2. **`time_entries.invoice_line_id` cannot be a foreign key in 4A.** §4.1 declares it `UUID FK invoice_lines ON DELETE SET NULL`, and §16 puts `time_entries` in 4A, which by construction does not depend on slice 3 — but `invoice_lines` is a slice 3 table. **Resolution:** 4A creates the column as a plain nullable `UUID` with **no** FK constraint (Task 4A-5), together with the `CHECK (deleted_at IS NULL OR invoice_line_id IS NULL)` the spec asks for, which is a same-row condition and works with no other table present. **Task 4B-3** adds the real constraint (`ON DELETE SET NULL`) once `invoice_lines` exists. In 4A nothing writes the column — `bind_time_to_invoice` is 4B — so the state "linked" is unreachable, and 4A's immutability and `recalculate_rates` guards key on `invoice_line_id IS NOT NULL` (a deliberate superset of the real rule). Task 4B-3 narrows both to the spec's real rule, which is "linked to a line of an **issued** invoice", through the single shared helper `_billed_entry_ids` both are built around from the start.
3. **The architecture test has no MCP exclusion clause yet.** Slice 3's §11 grows `test_architecture.py` with it; slice 3 is not merged, so `packages/core/tests/test_architecture.py` today contains only the import-direction allowlist. **Resolution:** **Task 4A-13** introduces the clause itself, in the shape slice 4's §11 specifies, with the exclusion list declared as **exactly the ten names** the spec fixes — including `bind_time_to_invoice` and `get_fiscal_estimate`, which do not exist until 4B. The list is asserted to equal those ten names as a constant; the "no tool reaches them" half is trivially satisfied for the two that do not yet exist, and the "every other public method has a tool" half only ever inspects classes actually present in `AUDITED_SERVICES`. **Task 4B-9** therefore adds `AnalyticsService` to `AUDITED_SERVICES` and changes not one character of the list.
4. **`update_user_rates` and `update_deal_rate` are methods of `TimeEntryService`, not of a separate rate service.** §11 requires the audited surface to be the public methods of `TimeEntryService`, `CostService` and `AnalyticsService`, and requires the exclusion list to be exactly ten names two of which are these. A dedicated `RateService` would put two excluded names outside the audited set, which is exactly the "the ban degrades into an oversight" failure §11 exists to prevent. **Resolution (Task 4A-7):** both live on `TimeEntryService`, which is also the class that reads those columns and freezes them. `RateResolver` (`timetracking/rates.py`) stays a plain, session-taking helper class with no `actor`, so it is not a service and is not audited.
5. **`recalculate_rates` needs two read tools that §11's table does not enumerate.** §11 requires every non-excluded public method of the audited services to be reachable from a tool. `TimeEntryService.get`/`restore` and `CostService.get`/`restore` are not in §11's table but are ordinary reads and an ordinary reversal. **Resolution (Task 4A-13):** they get tools — `get_time_entry`, `restore_time_entry`, `get_cost`, `restore_cost`, `list_costs`. This is §11's reason 1 applied consistently (a reversible, attributed, single-row operation is exactly what an agent may do), not an extension of the agent's authority: none of them changes what an already-recorded number means.
6. **The timesheet PDF does not redraw the emitter identity block.** the previous system's `template-time-tracking.typ` sets `header: none` and draws logo-left / identity-right inline as its first `#grid`, because it had no shared page header. This product's Typst pipeline already renders `render/assets/header.typ.template` from `emitter_profile` via `--include-in-header` for **every** document, and it already carries logo-left / identity-right. **Resolution (Task 4A-14):** the carried-over knowledge — the identity block's *content and placement* — is honoured by the existing header, and the new template body carries the rest of the layout verbatim: the `Periodo / Data emissione` line, the Cliente + Offerta block, the three-column `DATA · ORE · DESCRIZIONE` table at `(0.18fr, 0.12fr, 0.7fr)`, the `0.6pt` divider, and the footer pairing total hours with the entry count. Duplicating the identity block would put it on the page twice.
7. **There is no template seeding mechanism to hang a `rapporto_ore` template on.** `packages/core/src/pigrocrm/core/render/assets/template-offer.md` exists but is referenced by nothing (`grep -rn "template-offer" packages apps` finds only a comment in `render/pdf.py`), and `TemplateService` has no `seed_defaults` — unlike `PipelineService.seed_defaults(actor)`. **Resolution (Task 4A-14):** add `TemplateService.seed_defaults(actor)` on the `PipelineService.seed_defaults` model, deduplicating on `lower(nome)` to match the existing `uq_templates_nome` functional index, plus a `pigrocrm seed-templates` CLI subcommand. It seeds exactly one template in this slice — `Rapporto ore`, `tipo="rapporto_ore"` — and leaves `template-offer.md` alone, because adopting it would change slice 2's shipped behaviour in a slice that is not about offers.
8. **The spec says "`enum`" nowhere, and neither does the codebase.** Every closed set in this schema is `String(n)` on the column plus a Pydantic `Literal` on the schema (`pipeline_stages.tipo` is `String(10)`, `documents.tipo` is `String(20)` with `DocumentTipo = Literal[...]`). **Resolution:** `time_entries.tariffa_origine`/`costo_origine` are `String(10)` + `Literal`, and `documents.tipo` gains the string `"rapporto_ore"` by appending to that `Literal` — a constant, not a migration. A Postgres `ENUM` would need an `ALTER TYPE` for every future value.

---

## File Structure

```
packages/core/
├── pyproject.toml                              # MODIFIED (4A-15): + openpyxl==3.1.5
└── src/pigrocrm/core/
    ├── money.py                                # NEW (4A-4): the only place rounding happens
    ├── fields/schemas.py                       # MODIFIED (4A-3): EntityType + time_entry, cost
    ├── fields/service.py                       # MODIFIED (4A-2): native-column collision guard
    ├── documents/schemas.py                    # MODIFIED (4A-3): DocumentTipo + rapporto_ore
    ├── schema_registry.py                      # MODIFIED (4A-3): ENTITY_TYPES + CREATE_MODELS
    ├── models_registry.py                      # MODIFIED (4A-5): imports the four new models
    ├── cli.py                                  # MODIFIED (4A-14): `pigrocrm seed-templates`
    ├── templates/service.py                    # MODIFIED (4A-14): seed_defaults
    ├── timetracking/
    │   ├── __init__.py
    │   ├── models.py         # TimeEntry · Cost · CostCategory · PeriodLock
    │   ├── schemas.py        # every Create/Update/Read/ListQuery/Page for the four
    │   ├── repository.py     # TimeEntryRepository · CostRepository
    │   ├── categories.py     # CostCategoryRepository + CostCategoryService
    │   ├── locks.py          # PeriodLockRepository + PeriodLockService
    │   ├── rates.py          # RateResolver + ResolvedRates
    │   ├── service.py        # TimeEntryService
    │   ├── costs.py          # CostService
    │   ├── xlsx.py           # build_time_report_xlsx() — pure, openpyxl only
    │   └── report.py         # TimeReportService (PDF via DocumentService, XLSX via xlsx.py)
    ├── analytics/                              # 4B only
    │   ├── __init__.py
    │   ├── schemas.py        # DealPnl · PeriodPnl · BudgetVsActualRow · FiscalEstimate
    │   ├── repository.py     # AnalyticsRepository — every aggregate query, one per row of §7.1
    │   ├── fiscal.py         # pure annual-estimate arithmetic, no session
    │   └── service.py        # AnalyticsService
    └── render/assets/
        └── template-time-report.md             # NEW (4A-14): the carried-over layout

packages/core/migrations/versions/
├── 0004_time_tracking.py                       # NEW (4A-5)
└── 0005_analytics.py                           # NEW (4B-2/4B-3)

apps/api/src/pigrocrm_api/routers/
├── time_entries.py · costs.py · cost_categories.py · period_locks.py   # NEW (4A-12)
└── analytics.py                                                        # NEW (4B-9)

apps/mcp/src/pigrocrm_mcp/
├── context.py · server.py · __main__.py        # MODIFIED (4A-1): session per call
└── tools/timetracking.py                       # NEW (4A-13); analytics tools added 4B-9
└── resources/entities.py                       # MODIFIED (4A-13): deal:// gains hours + stato

apps/web/src/
├── lib/decimal.ts                              # NEW (4A-16): scaledFromDecimalString
├── lib/query.ts · lib/schema.ts                # MODIFIED (4A-16/4A-3)
├── components/EntityDetailLayout.tsx           # MODIFIED (4A-17): `hours` + `economics` tabs
├── features/time/{queries.ts,TimeEntriesTab.tsx,TimeEntryForm.tsx,WeekGrid.tsx,
│                 WeekGridRow.tsx,TimeReportButtons.tsx,columns.tsx}
├── features/costs/{queries.ts,CostsPanel.tsx,CostForm.tsx,columns.tsx}
├── features/analytics/{queries.ts,EconomicsTab.tsx,MarginsTable.tsx,
│                      BudgetTable.tsx,FiscalPanel.tsx,columns.tsx}
├── features/settings/{CostCategoriesPanel.tsx,RatesPanel.tsx,PeriodsPanel.tsx}
└── routes/app/{ore.tsx,analisi.tsx,analisi/{margini,preventivo-consuntivo,fiscale}.tsx,
              impostazioni/{categorie-costo,tariffe,periodi}.tsx}
```

**Why these boundaries.** `timetracking/` is one package rather than four because hours, costs, categories and locks change together — a period lock exists only to protect the other three — but it is split into nine small files because each piece has to be provable alone: `money.py` with no session, `rates.py` with no report, `xlsx.py` with no database. `money.py` sits at the top level, not inside `timetracking/`, because `analytics/` needs the identical rounding and a second copy is how two totals start disagreeing. `analytics/repository.py` holds every aggregate query in one file so that "where does `ricavi` come from" has exactly one answer to read — the defect the previous system's three fallback buckets produced was a *dispersed* aggregation, and a single file is the structural answer to it.

---

# PLAN 4A — Ore, costi, tariffe, griglia settimanale, rapporto ore, superficie MCP

**Depends on:** slice 1 (`2026-08-06-slice-1a-backend.md`, `2026-08-06-slice-1b-frontend.md`) and slice 2 (`2026-08-10-slice-2-documenti-e-template.md`), both complete and in `main`. **Not** on slice 3.

**Shippable alone.** At the end of 4A a freelancer records hours from the app or by asking Claude, gives every hour a frozen rate, closes a month when they have reported it, and sends a client a professional timesheet as PDF or XLSX. The tab «Economia» does not exist yet, which a user understands — unlike a tab showing zeros.

**`period_locks` is in 4A and not in 4B on purpose**, even though it exists to protect 4B's reports: the constraint that has to exist is the one **on writes**, and it has to exist before there are months of hours written without it. Adding it later would mean deciding retroactively which periods were closed.

---

## Phase 4A-0 — The two blocking prerequisites

### Task 4A-1: One SQLAlchemy session per MCP call (residual R1)

**Files:**
- Modify: `apps/mcp/src/pigrocrm_mcp/context.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/server.py:78-90` (the `McpContext` construction and the `_guard` closure)
- Modify: `apps/mcp/src/pigrocrm_mcp/__main__.py:22-33`
- Test: `apps/mcp/tests/test_session_scope.py`

**Interfaces:**
- Consumes: `pigrocrm.core.db.session_factory(engine) -> sessionmaker[Session]`; `pigrocrm.core.db.create_engine_from_settings(settings) -> Engine`; the existing `McpContext(session_provider, actor_provider, storage)` frozen dataclass with its `session`/`actor` properties.
- Produces:
  - `pigrocrm_mcp.context.ScopedSessionProvider` — `ScopedSessionProvider(factory: sessionmaker[Session])`, callable as `() -> Session`, plus `def scope(self) -> AbstractContextManager[Session]` which opens exactly one session, binds it to a `contextvars.ContextVar`, and closes it on exit.
  - `McpContext.session` unchanged in signature (`-> Session`) — every read inside one logical call now resolves to the *same* session.
  - `pigrocrm_mcp.server.build_server(session_provider: SessionProvider, actor_provider: ActorProvider, storage: DocumentStorage | None = None) -> MCPServer` — signature unchanged; `_guard` now wraps every tool and resource in `session_provider.scope()` when the provider exposes one.

- [ ] **Step 1: Write the failing concurrency test**

```python
# apps/mcp/tests/test_session_scope.py
"""R1, reproduced and then closed.

The slice 1A reviewer measured 10 concurrent `create_customer` calls against one
shared Session as 0 successes and 0 rows. `log_time` (Task 4A-13) is a write tool
and the centre of this slice's agentic surface, so that measurement is the exact
behaviour this test refuses to ship.

Uses `Engine`-backed real sessions, not the `db_session` savepoint fixture: the
whole point is that each thread gets its own connection and its own transaction,
which a shared savepoint session cannot express.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import Engine, text

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.db import session_factory
from pigrocrm_mcp.context import McpContext, ScopedSessionProvider

CONCURRENCY = 20

# `mcp_engine` and `mcp_storage`, not core's `db_engine`: `apps/mcp/tests/conftest.py`
# already owns the engine fixture for this package (`mcp_engine`, `mcp_session`,
# `server`, `seeded_customer_id`, ...). `mcp_storage` is added by Step 6 below.


def test_twenty_concurrent_writes_all_succeed(mcp_engine: Engine, mcp_storage) -> None:
    provider = ScopedSessionProvider(session_factory(mcp_engine))
    actor = Actor(id=None, type="mcp", role="admin")
    context = McpContext(provider, lambda: actor, mcp_storage)
    barrier = threading.Barrier(CONCURRENCY)
    names = [f"Concorrente {uuid4()}" for _ in range(CONCURRENCY)]

    def write(nome: str) -> str:
        barrier.wait(timeout=30)
        with provider.scope():
            return str(
                CustomerService(context.session)
                .create(CustomerCreate(ragione_sociale=nome), context.actor)
                .id
            )

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        ids = list(pool.map(write, names))

    assert len(set(ids)) == CONCURRENCY
    with session_factory(mcp_engine)() as check:
        stored = check.execute(
            text("SELECT count(*) FROM customers WHERE ragione_sociale = ANY(:names)"),
            {"names": names},
        ).scalar_one()
    assert stored == CONCURRENCY


def test_every_read_of_session_inside_one_scope_is_the_same_session(
    mcp_engine: Engine, mcp_storage
) -> None:
    """`resources/entities.py` reads `context.session` up to four times while
    rendering one resource. A provider that opened a fresh session per read would
    leak that many un-closed sessions per call -- the concrete objection recorded
    in `server.py`'s own comment against a naive session-per-call design."""
    provider = ScopedSessionProvider(session_factory(mcp_engine))
    context = McpContext(provider, lambda: Actor.system(), mcp_storage)
    with provider.scope():
        assert context.session is context.session is provider()


def test_leaving_the_scope_closes_the_session(mcp_engine: Engine, mcp_storage) -> None:
    provider = ScopedSessionProvider(session_factory(mcp_engine))
    with provider.scope() as session:
        pass
    assert not session.is_active or session.get_transaction() is None
    # And a read outside any scope is a programming error, not a silent new session.
    try:
        provider()
    except RuntimeError as exc:
        assert "scope" in str(exc)
    else:
        raise AssertionError("expected RuntimeError outside a scope")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest apps/mcp/tests/test_session_scope.py -v`
Expected: FAIL with `ImportError: cannot import name 'ScopedSessionProvider' from 'pigrocrm_mcp.context'`.

- [ ] **Step 3: Implement the scoped provider**

```python
# apps/mcp/src/pigrocrm_mcp/context.py  (append; the existing McpContext is unchanged)
import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from pigrocrm.core.actor import Actor
from pigrocrm.core.storage import DocumentStorage

SessionProvider = Callable[[], Session]
ActorProvider = Callable[[], Actor]

_CURRENT_SESSION: contextvars.ContextVar[Session] = contextvars.ContextVar("mcp_session")


class ScopedSessionProvider:
    """One `Session` per logical MCP call, not one per process.

    `contextvars`, not `threading.local`: the SDK dispatches coroutine tools on an
    event loop as well as sync tools in a thread pool, and a `ContextVar` is the
    only primitive that is correct for both -- each task and each thread sees its
    own binding, and `Context.run` copying does not leak one call's session into
    another's.

    `__call__` refuses outside a scope instead of quietly opening a session. A
    session nobody closes is the failure this class exists to remove, and returning
    one from an unscoped read would reintroduce exactly the leak `server.py`'s own
    comment recorded as the objection to session-per-call.
    """

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def __call__(self) -> Session:
        try:
            return _CURRENT_SESSION.get()
        except LookupError as exc:
            raise RuntimeError(
                "no MCP session scope is active: every tool and resource must run "
                "inside ScopedSessionProvider.scope()"
            ) from exc

    @contextmanager
    def scope(self) -> Iterator[Session]:
        session = self._factory()
        token = _CURRENT_SESSION.set(session)
        try:
            yield session
        finally:
            _CURRENT_SESSION.reset(token)
            session.close()
```

- [ ] **Step 4: Make `_guard` open the scope, and drop the shared rollback**

```python
# apps/mcp/src/pigrocrm_mcp/server.py -- inside build_server, replacing the four
# `context.session.rollback()` call sites in both wrappers.
#
# The rollback existed because one Session lived for the whole process: an
# untranslated exception left its transaction failed and poisoned every later call
# forever. With a session per call that failure mode is gone -- the session is
# closed on the way out of the scope whatever happened -- so the guard goes back to
# translating errors and nothing else. `session_scope` is resolved once, here,
# rather than per call, so a plain callable provider (a test passing `lambda:
# session`) still works: it gets a null scope and the old behaviour.

from contextlib import nullcontext

_scope = getattr(session_provider, "scope", None)

def _session_scope() -> Any:
    return _scope() if _scope is not None else nullcontext()

def _guard[T: Callable[..., Any]](fn: T) -> T:
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with _session_scope():
                try:
                    return await fn(*args, **kwargs)
                except DomainError as exc:
                    raise _as_protocol_error(exc) from exc
                except ValueError as exc:
                    raise _as_protocol_error(to_domain_error(exc)) from exc

        return cast(T, async_wrapper)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _session_scope():
            try:
                return fn(*args, **kwargs)
            except DomainError as exc:
                raise _as_protocol_error(exc) from exc
            except ValueError as exc:
                raise _as_protocol_error(to_domain_error(exc)) from exc

    return cast(T, wrapper)
```

Replace the stale comment on the `McpContext(...)` construction (`server.py:56-70`) with:

```python
    # One session per logical call (Task 4A-1, residual R1). `_guard` opens the
    # scope; `McpContext.session` resolves to the one session bound to it, however
    # many times a tool or a resource render reads the property. The measurement
    # this replaces: 10 concurrent writes against one shared Session produced 0
    # successes and 0 rows.
```

- [ ] **Step 5: Give `__main__.py` the scoped provider**

```python
# apps/mcp/src/pigrocrm_mcp/__main__.py -- replacing the three lines that built one
# Session and passed `lambda: session`.
    engine = create_engine_from_settings(get_settings())
    provider = ScopedSessionProvider(session_factory(engine))

    # The PAT is resolved once, at start-up, in its own short-lived session: the
    # actor does not change for the life of the process, and resolving it inside a
    # per-call scope would hit the database on every tool call for an answer that
    # cannot have changed.
    with provider.scope() as bootstrap:
        try:
            actor = PatService(bootstrap).resolve(token)
        except DomainError as exc:
            print(f"Token non valido: {exc.message}", file=sys.stderr)
            return 1

    build_server(provider, lambda: actor).run("stdio")
    return 0
```

- [ ] **Step 6: Add the `mcp_storage` fixture if the MCP test package lacks one**

```python
# apps/mcp/tests/conftest.py (add if absent; a tmp-dir backend, never ./var/documents)
import pytest
from pigrocrm.core.storage.local import LocalFileStorage


@pytest.fixture
def mcp_storage(tmp_path) -> LocalFileStorage:
    return LocalFileStorage(str(tmp_path / "documents"))
```

- [ ] **Step 7: Run the whole MCP and core suites**

Run: `uv run pytest apps/mcp packages/core -q`
Expected: PASS, no skips. In particular the existing `_guard` tests that asserted a rollback on the shared session must now assert translation only — update their names and docstrings in this same commit rather than leaving a test that describes behaviour the code no longer has.

- [ ] **Step 8: Commit**

```bash
git add apps/mcp packages/core
git commit -m "fix(mcp): one SQLAlchemy session per call, closing residual R1"
```

---

### Task 4A-2: A custom-field key cannot collide with a native column (residual A13)

**Files:**
- Modify: `packages/core/src/pigrocrm/core/fields/service.py:41-72` (`FieldDefinitionService.create`)
- Test: `packages/core/tests/test_fields_native_collision.py`

**Interfaces:**
- Consumes: `pigrocrm.core.schema_registry.native_fields(entity_type: str) -> list[str]`; `pigrocrm.core.fields.schemas.slugify_key(raw: str) -> str`; `pigrocrm.core.errors.ValidationFailed(entity, field, reason, *, expected=None)`.
- Produces: no new public name. `FieldDefinitionService.create` now raises `ValidationFailed("field_definition", "key", "collide con una colonna nativa", expected=...)` before any database write when the slugified key matches a native field of that entity type.

**Import cycle note for the implementer:** `fields/service.py` must not import `schema_registry` at module scope. `schema_registry` imports `CustomerCreate`, `DealCreate`, `DocumentCreate`, `PersonCreate` *and* `FieldDefinitionService` itself (`schema_registry.py:19`), so a module-level import here is a genuine cycle. Import it inside the method body — the same call-time-resolution technique `server.py:build_server` already uses for `register_entity_tools`.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_fields_native_collision.py
"""A13. The residual document's 2026-08-20 update makes this blocking for slice 4
because this slice's native columns are named `ore`, `data`, `importo` and
`descrizione` -- the first labels anyone would type defining a custom field on an
hours entry. Before this guard, a field labelled "Ore" on `time_entry` slugified to
`ore`, the API answered 201, and every later write landed in `custom_fields.ore`
instead of the real column, silently.
"""

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService


@pytest.fixture
def admin() -> Actor:
    return Actor.system()


@pytest.mark.parametrize(
    ("entity_type", "label", "colliding_key"),
    [
        ("time_entry", "Ore", "ore"),
        ("time_entry", "Data", "data"),
        ("time_entry", "Descrizione", "descrizione"),
        ("cost", "Importo", "importo"),
        ("cost", "Data", "data"),
        ("deal", "Nome", "nome"),
        ("customer", "Ragione sociale", "ragione_sociale"),
        # Slugification is what makes this reachable by accident: nobody types
        # `ore_preventivate`, they type "Ore preventivate".
        ("deal", "Ore  preventivate", "ore_preventivate"),
        # Accent folding too -- slugify_key transliterates before stripping.
        ("deal", "Probabilità", "probabilita"),
    ],
)
def test_a_label_that_slugifies_onto_a_native_column_is_refused(
    db_session: Session, admin: Actor, entity_type: str, label: str, colliding_key: str
) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        FieldDefinitionService(db_session).create(
            FieldDefinitionCreate(entity_type=entity_type, label=label, field_type="text"),
            admin,
        )
    assert excinfo.value.details["field"] == "key"
    assert colliding_key in excinfo.value.details["expected"]


def test_a_non_colliding_label_is_still_accepted(db_session: Session, admin: Actor) -> None:
    field = FieldDefinitionService(db_session).create(
        FieldDefinitionCreate(entity_type="time_entry", label="Ore approvate", field_type="number"),
        admin,
    )
    assert field.key == "ore_approvate"


def test_nothing_is_written_when_the_guard_fires(db_session: Session, admin: Actor) -> None:
    """The guard must run before `repo.add`, or a refused definition still occupies
    the key: `get_by_key` does not filter on `archived`, so a half-written row would
    make even the corrected label unusable."""
    service = FieldDefinitionService(db_session)
    with pytest.raises(ValidationFailed):
        service.create(
            FieldDefinitionCreate(entity_type="cost", label="Importo", field_type="currency"),
            admin,
        )
    db_session.rollback()
    assert service.repo.get_by_key("cost", "importo") is None


def test_field_definition_update_has_no_key_to_collide(db_session: Session) -> None:
    """Documented rather than asserted in prose: there is no update path to guard,
    because the key is immutable by omission from the Update schema."""
    from pigrocrm.core.fields.schemas import FieldDefinitionUpdate

    assert "key" not in FieldDefinitionUpdate.model_fields
    assert "entity_type" not in FieldDefinitionUpdate.model_fields
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_fields_native_collision.py -v`
Expected: FAIL — the parametrised cases raise nothing and instead return a `FieldDefinitionRead`; the `time_entry`/`cost` cases additionally fail at `FieldDefinitionCreate` validation with `Input should be 'customer', 'person', 'deal' or 'document'` until Task 4A-3 widens `EntityType`. Run this task's test again at the end of Task 4A-3; the `deal`/`customer` rows must fail on the missing guard *now*, which is what proves the guard is the thing being added.

- [ ] **Step 3: Implement the guard**

```python
# packages/core/src/pigrocrm/core/fields/service.py -- inside create, immediately
# after `_check_options(data.field_type, data.options)` and before the
# `repo.get_by_key` pre-check.

        # A13. `native_fields()` is derived from the entity's own Create model
        # (schema_registry.py), never hand-listed, so it stays correct as models
        # change. Imported here rather than at module scope: `schema_registry`
        # imports this class (schema_registry.py:19), so a top-level import is a
        # real cycle -- the same call-time resolution `server.py` uses for
        # `register_entity_tools`.
        from pigrocrm.core.schema_registry import native_fields

        native = native_fields(data.entity_type)
        if data.key in native:
            raise ValidationFailed(
                "field_definition",
                "key",
                "collide con una colonna nativa dell'entità",
                expected=(
                    f"una chiave diversa da {data.key!r}: è già una colonna nativa di "
                    f"{data.entity_type}. Colonne native: {', '.join(sorted(native))}"
                ),
            )
```

- [ ] **Step 4: Run the test and the whole fields suite**

Run: `uv run pytest packages/core/tests/test_fields_native_collision.py packages/core/tests/test_fields.py -v`
Expected: PASS for every non-`time_entry`/`cost` case; the two new entity types stay red until Task 4A-3. Do not weaken the test to make them pass here.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/fields/service.py packages/core/tests/test_fields_native_collision.py
git commit -m "fix(fields): a custom key colliding with a native column is refused (A13)"
```

---

## Phase 4A-1 — Types, money and schema

### Task 4A-3: `entity_type` gains `time_entry` and `cost`; `documents.tipo` gains `rapporto_ore`

**Files:**
- Modify: `packages/core/src/pigrocrm/core/fields/schemas.py:17` (`EntityType`)
- Modify: `packages/core/src/pigrocrm/core/schema_registry.py:22-29` (`ENTITY_TYPES`, `CREATE_MODELS`)
- Modify: `packages/core/src/pigrocrm/core/documents/schemas.py:9` (`DocumentTipo`)
- Modify: `apps/web/src/lib/schema.ts:42` (`EntityType`)
- Test: `packages/core/tests/test_entity_types.py`

**Interfaces:**
- Consumes: `TimeEntryCreate` and `CostCreate` from `pigrocrm.core.timetracking.schemas` (defined in Task 4A-5). **Ordering note:** this task's `CREATE_MODELS` entries reference those two models, so run Step 3 of this task *after* Task 4A-5's schemas exist. Steps 1–2 and 4–5 (the literals and the frontend type) have no such dependency and are done here.
- Produces:
  - `EntityType = Literal["customer", "person", "deal", "document", "time_entry", "cost"]`
  - `ENTITY_TYPES: tuple[EntityType, ...] = ("customer", "person", "deal", "document", "time_entry", "cost")`
  - `CREATE_MODELS` gains `"time_entry": TimeEntryCreate` and `"cost": CostCreate`
  - `DocumentTipo = Literal["offerta", "contratto", "verbale", "documento", "rapporto_ore"]`
  - `apps/web/src/lib/schema.ts`: `export type EntityType = 'customer' | 'person' | 'deal' | 'document' | 'time_entry' | 'cost'`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_entity_types.py
"""R13, written in its correct form instead of the promise that has now been
disproved three times: **the database is open** (`field_definitions.entity_type` is
`String(30)` with no constraint), **the type is extended in four places** --
`fields/schemas.py:EntityType`, `schema_registry.py:ENTITY_TYPES` and
`CREATE_MODELS`, and `apps/web/src/lib/schema.ts:EntityType` -- **and no migration
is needed.** This test is the four places, asserted."""

import re
from pathlib import Path

from pigrocrm.core.documents.schemas import DocumentTipo
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.schema_registry import CREATE_MODELS, ENTITY_TYPES, native_fields

WEB_SCHEMA = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib" / "schema.ts"

EXPECTED = ("customer", "person", "deal", "document", "time_entry", "cost")


def test_entity_type_literal_covers_this_slice() -> None:
    assert set(EntityType.__args__) == set(EXPECTED)


def test_registry_agrees_with_the_literal() -> None:
    assert set(ENTITY_TYPES) == set(EXPECTED)
    assert set(CREATE_MODELS) == set(EXPECTED)


def test_native_fields_names_this_slice_columns() -> None:
    """The names A13 (Task 4A-2) has to defend. Asserted here so that renaming a
    column without revisiting the guard's own test still trips something."""
    assert {"ore", "data", "descrizione"} <= set(native_fields("time_entry"))
    assert {"importo", "data", "descrizione"} <= set(native_fields("cost"))


def test_document_tipo_gained_the_time_report() -> None:
    assert "rapporto_ore" in DocumentTipo.__args__


def test_the_frontend_literal_agrees() -> None:
    """`re.fullmatch`, not `re.match` with `$`, per the standing project rule -- and
    here it also matters: the union spans one line and a `$` would match before a
    trailing newline inside the file."""
    source = WEB_SCHEMA.read_text(encoding="utf-8")
    match = re.search(r"export type EntityType =([^\n]+)\n", source)
    assert match is not None, "EntityType not found in apps/web/src/lib/schema.ts"
    declared = {part.strip().strip("'") for part in match.group(1).split("|")}
    assert declared == set(EXPECTED)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_entity_types.py -v`
Expected: FAIL on all five — `EntityType.__args__` is `("customer", "person", "deal", "document")`, and `native_fields("time_entry")` raises `KeyError`.

- [ ] **Step 3: Widen the two literals and the registry**

```python
# packages/core/src/pigrocrm/core/fields/schemas.py -- replacing line 17 and its
# comment block above it.

# Closed by design: EntityType is a Literal, not an open set. The database column is
# `String(30)` with no constraint, so **the database** is open; the code is not.
# Adding an entity is an edit in exactly four places -- here, ENTITY_TYPES and
# CREATE_MODELS in schema_registry.py, and EntityType in apps/web/src/lib/schema.ts
# -- and no migration. That is R13 stated correctly; the earlier phrasing ("no
# changes required") has now been checked and disproved three times, once per slice.
EntityType = Literal["customer", "person", "deal", "document", "time_entry", "cost"]
```

```python
# packages/core/src/pigrocrm/core/documents/schemas.py -- replacing line 9.
# `rapporto_ore` is the timesheet PDF archived on the deal (slice 4 §10.2). A
# String(20) column plus a Literal, never a Postgres ENUM: a new value costs a
# constant, not an ALTER TYPE.
DocumentTipo = Literal["offerta", "contratto", "verbale", "documento", "rapporto_ore"]
```

```python
# packages/core/src/pigrocrm/core/schema_registry.py -- add the imports and widen
# both collections. Do this step after Task 4A-5, which defines the two models.
from pigrocrm.core.timetracking.schemas import CostCreate, TimeEntryCreate

ENTITY_TYPES: tuple[EntityType, ...] = (
    "customer",
    "person",
    "deal",
    "document",
    "time_entry",
    "cost",
)

CREATE_MODELS: dict[str, type[BaseModel]] = {
    "customer": CustomerCreate,
    "person": PersonCreate,
    "deal": DealCreate,
    "document": DocumentCreate,
    "time_entry": TimeEntryCreate,
    "cost": CostCreate,
}
```

- [ ] **Step 4: Widen the frontend literal**

```ts
// apps/web/src/lib/schema.ts -- replacing line 42.
export type EntityType = 'customer' | 'person' | 'deal' | 'document' | 'time_entry' | 'cost'
```

- [ ] **Step 5: Run everything that reads an entity type**

Run: `uv run pytest packages/core/tests/test_entity_types.py packages/core/tests/test_fields_native_collision.py apps/api/tests apps/mcp/tests -q`
Expected: PASS, including the `time_entry`/`cost` rows of Task 4A-2's parametrised test, which were red on purpose until now.

Run: `pnpm -C apps/web tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add packages/core apps/web/src/lib/schema.ts
git commit -m "feat(fields): entity types time_entry and cost, document type rapporto_ore"
```

---

### Task 4A-4: `money.py` — the one place rounding happens

**Files:**
- Create: `packages/core/src/pigrocrm/core/money.py`
- Test: `packages/core/tests/test_money.py`

**Interfaces:**
- Consumes: nothing beyond `decimal` from the stdlib. No session, no models — it is pure so it can be proven alone.
- Produces:
  ```python
  MONEY_SCALE: int = 2
  HOURS_SCALE: int = 2
  FACTOR_SCALE: int = 6
  MONEY_QUANT: Decimal      # Decimal("0.01")
  HOURS_QUANT: Decimal      # Decimal("0.01")
  FACTOR_QUANT: Decimal     # Decimal("0.000001")
  ZERO_MONEY: Decimal       # Decimal("0.00")
  ZERO_HOURS: Decimal       # Decimal("0.00")

  def round_money(value: Decimal) -> Decimal
  def round_hours(value: Decimal) -> Decimal
  def line_value(ore: Decimal, fattore: Decimal | None) -> Decimal | None
  def sum_money(values: Iterable[Decimal | None]) -> Decimal
  def sum_hours(values: Iterable[Decimal | None]) -> Decimal
  def percentage_of(part: Decimal, whole: Decimal) -> Decimal | None
  ```

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_money.py
"""The two rounding rules of §6.2, pinned. They disagree by cents, and the
disagreement is decided here rather than discovered in front of a client: the row
value is what the timesheet prints next to each entry, so an aggregate is the sum of
the printed rows, never the rounding of the exact sum."""

from decimal import Decimal

import pytest

from pigrocrm.core.money import (
    line_value,
    percentage_of,
    round_hours,
    round_money,
    sum_hours,
    sum_money,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.005", "0.01"),   # half-up, not half-even: banker's rounding gives 0.00
        ("0.015", "0.02"),   # half-even gives 0.02 here too -- kept for contrast
        ("0.025", "0.03"),   # half-even gives 0.02: this is the case that separates them
        ("-0.025", "-0.03"), # away from zero on the half, symmetrically
        ("2.344", "2.34"),
        ("2.345", "2.35"),
    ],
)
def test_round_money_is_half_up(raw: str, expected: str) -> None:
    assert round_money(Decimal(raw)) == Decimal(expected)


def test_line_value_is_a_rounded_product() -> None:
    assert line_value(Decimal("3.00"), Decimal("33.333333")) == Decimal("100.00")
    assert line_value(Decimal("0.10"), Decimal("33.333333")) == Decimal("3.33")


def test_line_value_without_a_factor_is_none_not_zero() -> None:
    """A silent fall back to 0.00 would say "this work was free", which is a lie that
    sums. `None` is excluded from the aggregate and counted separately as "ore senza
    tariffa" (§5.1)."""
    assert line_value(Decimal("8.00"), None) is None


def test_an_aggregate_is_the_sum_of_rounded_rows_and_diverges_from_the_exact_sum() -> None:
    """1000 rows of 0.10 h at 33.333333 EUR/h. `Σ ROUND(...)` is 3330.00;
    `ROUND(Σ exact)` is 3333.33. The rule is the first, and this test exhibits the
    difference rather than asserting the rule in prose (criterion 4)."""
    ore, tariffa = Decimal("0.10"), Decimal("33.333333")
    rows = [line_value(ore, tariffa) for _ in range(1000)]
    assert sum_money(rows) == Decimal("3330.00")
    assert round_money(ore * tariffa * 1000) == Decimal("3333.33")
    assert sum_money(rows) != round_money(ore * tariffa * 1000)


def test_the_same_thousand_rows_summed_as_floats_diverge_from_the_decimal_total() -> None:
    """The float control the spec's criterion 4 asks for by name: the test must
    compute the naive sum too, and show it differs."""
    naive = sum(0.10 * 33.333333 for _ in range(1000))
    assert Decimal(repr(round(naive, 2))) != sum_money(
        [line_value(Decimal("0.10"), Decimal("33.333333")) for _ in range(1000)]
    )


def test_sums_skip_none_and_return_a_typed_zero_when_empty() -> None:
    assert sum_money([]) == Decimal("0.00")
    assert sum_money([None, Decimal("1.00"), None]) == Decimal("1.00")
    assert sum_hours([Decimal("1.50"), Decimal("2.25")]) == Decimal("3.75")
    assert sum_hours([]) == Decimal("0.00")


def test_round_hours_keeps_two_places() -> None:
    assert round_hours(Decimal("1.005")) == Decimal("1.01")


def test_percentage_of_zero_is_none_not_zero() -> None:
    """`0.00` per cent means "everything I earned went out in costs"; here nothing has
    been earned at all. Two different facts, and the report does not flatten them
    (criterion 6)."""
    assert percentage_of(Decimal("-500.00"), Decimal("0.00")) is None
    assert percentage_of(Decimal("250.00"), Decimal("1000.00")) == Decimal("25.00")
    assert percentage_of(Decimal("1.00"), Decimal("3.00")) == Decimal("33.33")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_money.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.money'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/money.py
"""The single authority on rounding for this project.

Three scales, not two (slice 4 §6.1). Money and every P&L row are 2 places; hours
are 2 places; **rates and internal hourly costs are 6**, because slice 3 makes
`invoice_lines.prezzo_unitario` `Numeric(12,6)` and a rate at two places would
change value the moment hours became an invoice line -- the reconciliation of slice
4B would then fail by cents for a reason nobody could reconstruct.

`ROUND_HALF_UP`, never `ROUND_HALF_EVEN`. Italian fiscal practice, inherited from
slice 3 §6.1, and what the SdI's own arithmetic expects on the invoice line these
hours become. `Decimal.quantize` defaults to the context rounding, which is
`ROUND_HALF_EVEN`; every call here passes the mode explicitly rather than depending
on a context nobody sets.

Lives at the top level of `core`, not inside `timetracking/`, because `analytics/`
needs the identical arithmetic and a second copy is how two totals begin to
disagree.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

MONEY_SCALE = 2
HOURS_SCALE = 2
FACTOR_SCALE = 6

MONEY_QUANT = Decimal("0.01")
HOURS_QUANT = Decimal("0.01")
FACTOR_QUANT = Decimal("0.000001")

ZERO_MONEY = Decimal("0.00")
ZERO_HOURS = Decimal("0.00")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def round_hours(value: Decimal) -> Decimal:
    return value.quantize(HOURS_QUANT, rounding=ROUND_HALF_UP)


def line_value(ore: Decimal, fattore: Decimal | None) -> Decimal | None:
    """`ROUND(ore x fattore, 2)`, or `None` when there is no factor.

    `None`, never `0.00`: an hour with no rate is an hour nobody has priced, and a
    silent zero would say the work was free -- a lie that sums. The caller excludes
    `None` from money aggregates and counts those rows separately as "ore senza
    tariffa" (§5.1).
    """
    if fattore is None:
        return None
    return round_money(ore * fattore)


def sum_money(values: Iterable[Decimal | None]) -> Decimal:
    """The sum of already-rounded row values, never the rounding of an exact sum.

    The two differ by cents (see `test_money.py`), and this one wins for a reason
    specific to this slice: the row value is what the timesheet prints next to each
    entry, and a total that is not the sum of the visible column is the fastest way
    to lose a client's trust in a document you are sending them to get paid.
    """
    total = ZERO_MONEY
    for value in values:
        if value is not None:
            total += value
    return total


def sum_hours(values: Iterable[Decimal | None]) -> Decimal:
    total = ZERO_HOURS
    for value in values:
        if value is not None:
            total += value
    return total


def percentage_of(part: Decimal, whole: Decimal) -> Decimal | None:
    """`None` when `whole` is zero, never `0.00`.

    Zero per cent means "everything I earned went out in costs". A zero denominator
    means nothing has been earned yet. Two different facts; the report does not
    flatten them (§7.1, criterion 6). No division is ever executed on a zero
    denominator, so this is also the only place that question is asked.
    """
    if whole == 0:
        return None
    return round_money(part / whole * Decimal(100))
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_money.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/money.py packages/core/tests/test_money.py
git commit -m "feat(money): ROUND_HALF_UP per row, aggregates as sums of rounded rows"
```

---

## Phase 4A-2 — The four tables

### Task 4A-5: Models, schemas and migration `0004`

**Files:**
- Create: `packages/core/src/pigrocrm/core/timetracking/__init__.py`
- Create: `packages/core/src/pigrocrm/core/timetracking/models.py`
- Create: `packages/core/src/pigrocrm/core/timetracking/schemas.py`
- Create: `packages/core/migrations/versions/0004_time_tracking.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Modify: `packages/core/src/pigrocrm/core/deals/models.py` (add `tariffa_oraria`)
- Modify: `packages/core/src/pigrocrm/core/deals/schemas.py` (add `tariffa_oraria` to Create/Update/Read)
- Modify: `packages/core/src/pigrocrm/core/auth/models.py` (add the two default rate columns)
- Modify: `packages/core/src/pigrocrm/core/auth/schemas.py` (same on UserCreate/UserUpdate/UserRead)
- Test: `packages/core/tests/test_timetracking_models.py`
- Test: `packages/core/tests/test_migrations.py` (extend the existing parity assertions — do not create a second file)

**Interfaces:**
- Consumes: `pigrocrm.core.db.{Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin}`; `pigrocrm.core.validation.SafeStr`; `pigrocrm.core.money.{FACTOR_SCALE, HOURS_SCALE, MONEY_SCALE}`.
- Produces (models):
  - `TimeEntry` — `time_entries`: `deal_id` (FK `deals.id`, NOT NULL, indexed), `user_id` (FK `users.id`, NOT NULL), `data` `Date` NOT NULL, `ore` `Numeric(8,2)` NOT NULL, `descrizione` `Text` NOT NULL, `fatturabile` `Boolean` NOT NULL default `True`, `tariffa_applicata` `Numeric(12,6)` null, `costo_applicato` `Numeric(12,6)` null, `tariffa_origine` `String(10)` NOT NULL default `"assente"`, `costo_origine` `String(10)` NOT NULL default `"assente"`, `invoice_line_id` `Uuid` null (no FK until Task 4B-3), `note_interne` `Text` null, `custom_fields` `JSONB` NOT NULL default `dict`, plus `PrimaryKeyMixin`/`TimestampMixin`/`SoftDeleteMixin`.
  - `Cost` — `costs`: `deal_id` (FK `deals.id`, null, indexed), `category_id` (FK `cost_categories.id`, NOT NULL, indexed), `data` `Date` NOT NULL, `importo` `Numeric(12,2)` NOT NULL, `descrizione` `Text` NOT NULL, `fornitore` `String(200)` null, `document_id` (FK `documents.id`, null), `custom_fields` `JSONB`, plus the three mixins.
  - `CostCategory` — `cost_categories`: `nome` `String(60)` NOT NULL, `posizione` `Integer` NOT NULL default `0`, `code` `String(30)` null, `archiviata` `Boolean` NOT NULL default `False`, plus `PrimaryKeyMixin`/`TimestampMixin` (no soft delete — `archiviata` is the lifecycle flag, exactly as `templates.attivo` is).
  - `PeriodLock` — `period_locks`: composite primary key `(anno, mese)`, `chiuso_il` `timestamptz` NOT NULL, `chiuso_da` (FK `users.id`, null). No `PrimaryKeyMixin`, no `TimestampMixin`: the key *is* the identity and `chiuso_il` *is* the timestamp.
- Produces (schemas, all in `timetracking/schemas.py`): `RateOrigin`, `TimeEntryCreate`, `TimeEntryUpdate`, `TimeEntryRead`, `TimeEntryListQuery`, `TimeEntryPage`, `CostCreate`, `CostUpdate`, `CostRead`, `CostListQuery`, `CostPage`, `CostCategoryCreate`, `CostCategoryUpdate`, `CostCategoryRead`, `PeriodLockCreate`, `PeriodLockRead`, `RateDescription`, `DealTimeSummary`, `RecalculateRatesRequest`, `UserRatesUpdate`, `DealRateUpdate`, plus the constants below. Exact declarations are in Step 4.

- [ ] **Step 1: Write the failing model test**

```python
# packages/core/tests/test_timetracking_models.py
"""The four tables, their constraints and their indexes, asserted against real
Postgres. `Base.metadata.create_all` has already run in the `db_engine` fixture, so
every assertion here is about the schema that actually exists."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.db import Base
from pigrocrm.core.timetracking.models import Cost, CostCategory, PeriodLock, TimeEntry


def test_the_four_tables_exist_with_the_expected_columns(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    assert {"time_entries", "costs", "cost_categories", "period_locks"} <= set(
        inspector.get_table_names()
    )
    entry_columns = {c["name"] for c in inspector.get_columns("time_entries")}
    assert entry_columns == {
        "id", "created_at", "updated_at", "deleted_at",
        "deal_id", "user_id", "data", "ore", "descrizione", "fatturabile",
        "tariffa_applicata", "costo_applicato", "tariffa_origine", "costo_origine",
        "invoice_line_id", "note_interne", "custom_fields",
    }


def test_numeric_precision_is_the_three_scales_and_never_float(db_engine: Engine) -> None:
    """Numeric(8,2) hours, Numeric(12,2) money, Numeric(12,6) factors -- read off the
    live catalogue, not off the model, because the model is what is being checked."""
    with db_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT table_name || '.' || column_name, "
                    "       numeric_precision || ',' || numeric_scale "
                    "FROM information_schema.columns "
                    "WHERE table_name IN ('time_entries','costs','deals','users') "
                    "  AND data_type = 'numeric'"
                )
            ).all()
        )
    assert rows["time_entries.ore"] == "8,2"
    assert rows["time_entries.tariffa_applicata"] == "12,6"
    assert rows["time_entries.costo_applicato"] == "12,6"
    assert rows["costs.importo"] == "12,2"
    assert rows["deals.tariffa_oraria"] == "12,6"
    assert rows["users.tariffa_oraria_default"] == "12,6"
    assert rows["users.costo_orario_default"] == "12,6"
    # And nothing in these tables is a float.
    with db_engine.connect() as conn:
        floats = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name IN ('time_entries','costs','cost_categories') "
                "  AND data_type IN ('double precision','real')"
            )
        ).scalar_one()
    assert floats == 0


def test_the_partial_indexes_this_slice_queries_by_exist(db_engine: Engine) -> None:
    """(deal_id, data) and (user_id, data), both partial on `deleted_at IS NULL` --
    the shape every query in this slice has, and the cure residual R7 asks for in
    general. Asserted through `pg_indexes.indexdef` so a non-partial index of the
    same name still fails."""
    with db_engine.connect() as conn:
        definitions = {
            name: definition
            for name, definition in conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'time_entries'")
            ).all()
        }
    assert "deleted_at IS NULL" in definitions["ix_time_entries_deal_data"]
    assert "deleted_at IS NULL" in definitions["ix_time_entries_user_data"]
    with db_engine.connect() as conn:
        cost_definitions = {
            name: definition
            for name, definition in conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'costs'")
            ).all()
        }
    assert "deleted_at IS NULL" in cost_definitions["ix_costs_deal_data"]
    assert "deleted_at IS NULL" in cost_definitions["ix_costs_data"]


def test_a_billed_entry_cannot_be_soft_deleted_even_in_raw_sql(
    db_session: Session, seeded_entry_id
) -> None:
    """The CHECK, not the service. §4.3: the disappearance of an hour that belongs to
    a fiscal document is covered at the level no write path can go around. The
    constraint is deliberately WIDER than the service rule -- it forbids deleting any
    entry bound to a line, draft included -- because distinguishing invoice state
    would need to read another table, i.e. a trigger, and this project keeps that kind
    of invisible logic out of the database."""
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": uuid4(), "id": seeded_entry_id},
    )
    with pytest.raises(IntegrityError) as excinfo:
        db_session.execute(
            text("UPDATE time_entries SET deleted_at = now() WHERE id = :id"),
            {"id": seeded_entry_id},
        )
        db_session.flush()
    assert "ck_time_entries_billed_not_deleted" in str(excinfo.value)
    db_session.rollback()


def test_period_locks_primary_key_is_the_month(db_session: Session) -> None:
    db_session.add(PeriodLock(anno=2026, mese=3, chiuso_il=datetime.now(UTC), chiuso_da=None))
    db_session.flush()
    db_session.add(PeriodLock(anno=2026, mese=3, chiuso_il=datetime.now(UTC), chiuso_da=None))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_cost_category_code_is_unique_but_null_repeats(db_session: Session) -> None:
    """Copies `pipeline_stages.code` exactly (residual R11's fix): `code` is the stable
    identity of a seeded category, distinct from `nome`, which the user may rename.
    Postgres treats every NULL as distinct under a unique index, so any number of
    user-created code-less categories coexist."""
    db_session.add_all(
        [
            CostCategory(nome="Prima", code=None),
            CostCategory(nome="Seconda", code=None),
            CostCategory(nome="Terza", code="viaggi"),
        ]
    )
    db_session.flush()
    db_session.add(CostCategory(nome="Quarta", code="viaggi"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_cost_amount_may_be_negative_but_never_zero(db_session: Session, seeded_category_id,
                                                    seeded_deal_id) -> None:
    """§4.4: a negative amount is a refund or a credit note received -- the same choice
    slice 3 §6.1 rule 6 makes for a discount ("a discount is a line"), instead of a
    `tipo` column that multiplies the cases in every sum. Zero is refused, because it
    is neither a cost nor a correction."""
    db_session.add(
        Cost(
            deal_id=seeded_deal_id, category_id=seeded_category_id, data=date(2026, 3, 1),
            importo=Decimal("-120.00"), descrizione="Rimborso hotel",
        )
    )
    db_session.flush()
    db_session.add(
        Cost(
            deal_id=None, category_id=seeded_category_id, data=date(2026, 3, 1),
            importo=Decimal("0.00"), descrizione="Niente",
        )
    )
    with pytest.raises(IntegrityError) as excinfo:
        db_session.flush()
    assert "ck_costs_importo_non_zero" in str(excinfo.value)
    db_session.rollback()


def test_hours_are_bounded_by_the_database_too(db_session: Session, seeded_deal_id,
                                               seeded_user_id) -> None:
    """`ore > 0 AND ore <= 24` as a CHECK as well as a schema bound. 24 is not a
    productivity limit, it is a shape check: a value above it is almost always the
    comma slip that writes 80 for 8,0, which without the bound would enter the margin
    as ten thousand euros of work never done."""
    for bad in (Decimal("0.00"), Decimal("-1.00"), Decimal("24.01")):
        db_session.add(
            TimeEntry(
                deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 1),
                ore=bad, descrizione="x",
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
```

Add the shared fixtures to `packages/core/tests/conftest.py` — this slice's tests need a deal, a user and a category often enough that four files would otherwise each build their own:

```python
# packages/core/tests/conftest.py (append)
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.timetracking.models import CostCategory, TimeEntry


@pytest.fixture
def seeded_user_id(db_session: Session) -> UUID:
    user = User(
        email=f"tester-{uuid4()}@example.test",
        password_hash="x",
        nome="Tester",
        ruolo="collaboratore",
    )
    db_session.add(user)
    db_session.flush()
    return user.id


@pytest.fixture
def seeded_open_stage_id(db_session: Session) -> UUID:
    stage = PipelineStage(nome=f"Aperto {uuid4()}", posizione=0, probabilita_default=10, tipo="open")
    db_session.add(stage)
    db_session.flush()
    return stage.id


@pytest.fixture
def seeded_won_stage_id(db_session: Session) -> UUID:
    stage = PipelineStage(nome=f"Vinto {uuid4()}", posizione=9, probabilita_default=100, tipo="won")
    db_session.add(stage)
    db_session.flush()
    return stage.id


@pytest.fixture
def seeded_deal_id(db_session: Session, seeded_open_stage_id: UUID) -> UUID:
    customer = Customer(ragione_sociale=f"Cliente {uuid4()}")
    db_session.add(customer)
    db_session.flush()
    deal = Deal(
        nome="Progetto di prova",
        customer_id=customer.id,
        pipeline_stage_id=seeded_open_stage_id,
        probabilita=10,
    )
    db_session.add(deal)
    db_session.flush()
    return deal.id


@pytest.fixture
def seeded_category_id(db_session: Session) -> UUID:
    category = CostCategory(nome=f"Categoria {uuid4()}", posizione=0, code=None)
    db_session.add(category)
    db_session.flush()
    return category.id


@pytest.fixture
def seeded_entry_id(db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID) -> UUID:
    entry = TimeEntry(
        deal_id=seeded_deal_id,
        user_id=seeded_user_id,
        data=date(2026, 3, 10),
        ore=Decimal("8.00"),
        descrizione="Analisi",
        tariffa_applicata=Decimal("80.000000"),
        tariffa_origine="manuale",
    )
    db_session.add(entry)
    db_session.flush()
    return entry.id
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_timetracking_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.timetracking'`.

- [ ] **Step 3: Write the models**

```python
# packages/core/src/pigrocrm/core/timetracking/models.py
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin


class CostCategory(Base, PrimaryKeyMixin, TimestampMixin):
    """User-configurable, like pipeline stages and field definitions.

    `code` is the stable identity of a seeded category, distinct from `nome`, which
    the user is free to rename -- exactly why `pipeline_stages.code` was added during
    the slice 1 review (residual R11), after `seed_defaults` was found deduplicating
    on `nome`, the one field the user can change. Categories a user creates have no
    `code`; Postgres treats every NULL as distinct under a unique index, so any number
    of them coexist.

    `archiviata` rather than deletable, and no `deleted_at`: this is a taxonomy, not a
    record. A deleted category with costs still hanging off it produces orphan rows
    nobody can see (slice 1 §5.6, first of its three rules), and `templates.attivo` is
    the same shape for the same reason.
    """

    __tablename__ = "cost_categories"
    __table_args__ = (Index("uq_cost_categories_code", "code", unique=True),)

    nome: Mapped[str] = mapped_column(String(60), nullable=False)
    posizione: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    code: Mapped[str | None] = mapped_column(String(30), default=None)
    archiviata: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TimeEntry(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One hour-logging entry, carrying its own rate.

    `deal_id` is **required**. The budget lives on the deal (`ore_preventivate`,
    `valore_preventivato`), the revenue arrives from invoices that carry a `deal_id`,
    and the P&L is per deal. An hour attached only to a customer would have no
    estimate to compare against and would escape every line of this slice; an hour
    attached to nothing is the ghost row the previous system produces and no export shows
    (`filterTimeEntriesForExport` requires a match, while `timeTrackingSummaryRows`
    falls back to `entry.id` as a group key -- so those hours count on screen and
    appear in no document). Internal work not attributable to a client is out of
    scope: keeping it in would mean payroll.

    `user_id` is **required** too. Without it there is no labour cost and half the
    margin is undefined. Not nullable even for "logged through MCP": an `Actor` of
    type `mcp` carries the id of the PAT's owning user (slice 1 §9), so there is
    always a person to attribute it to.

    `data` is a `Date`, not a timestamp -- §6.3. It is the calendar day the work
    belongs to, and that day decides which month, which report and which period it
    lands in. The previous system's `formatIsoDate` used `toISOString()`, so an hour logged at 23:30
    CEST on 31 March was stored as 1 April and went into the wrong monthly export --
    the file attached to an invoice.

    `fatturabile` and `invoice_line_id` are two columns because they answer two
    questions. `fatturabile` is a property of the **work** (an internal alignment
    meeting is never billed, and that is decided when it is logged);
    `invoice_line_id` is a fact about a **document** (whether a line covering it
    exists). A billable, not-yet-billed hour is the normal state of everything done
    this month. Merging them would make the weekly question -- *how much do I have to
    invoice?* -- unanswerable, because "not yet" and "never" would be indistinguishable.

    `invoice_line_id` has **no foreign key** in slice 4A: `invoice_lines` is a slice 3
    table and 4A deliberately does not depend on slice 3. Task 4B-3 adds the real
    constraint with `ON DELETE SET NULL` once that table exists. Nothing in 4A writes
    this column -- `bind_time_to_invoice` is 4B -- so the "bound" state is unreachable
    until then.

    `tariffa_origine`/`costo_origine` are `String(10)` plus a Pydantic `Literal`, never
    a Postgres ENUM: every closed set in this schema is spelled that way
    (`pipeline_stages.tipo`, `documents.tipo`), and a new value then costs a constant
    instead of an `ALTER TYPE` migration. `costo_origine` never takes the value
    `deal`: an hour's cost is a property of who works it, not of the client they work
    it for (§5.1).
    """

    __tablename__ = "time_entries"
    __table_args__ = (
        # Not a productivity limit -- a shape check. A value above 24 is almost always
        # the comma slip that writes 80 for 8,0, which would enter the margin as ten
        # thousand euros of work never done. The *daily* total is deliberately
        # unbounded: two 14-hour entries on one day are a likely error but not an
        # impossible one, and refusing the second would refuse a correction in
        # progress.
        CheckConstraint("ore > 0 AND ore <= 24", name="ck_time_entries_ore_range"),
        # §4.3, and the one rule no write path can go around. Deliberately wider than
        # the service rule -- it forbids deleting any entry bound to a line, draft
        # included -- because a constraint that distinguished invoice state would have
        # to read another table, i.e. be a trigger, and this project keeps that kind
        # of invisible logic out of the database. Reaching it costs nothing: to delete
        # an entry still on a draft, take it off the draft first and
        # `invoice_line_id` returns to NULL.
        CheckConstraint(
            "deleted_at IS NULL OR invoice_line_id IS NULL",
            name="ck_time_entries_billed_not_deleted",
        ),
        CheckConstraint(
            "tariffa_origine IN ('manuale', 'deal', 'utente', 'assente')",
            name="ck_time_entries_tariffa_origine",
        ),
        CheckConstraint(
            "costo_origine IN ('manuale', 'utente', 'assente')",
            name="ck_time_entries_costo_origine",
        ),
        # The shape every query in this slice has, partial on the filter every one of
        # them applies. Residual R7 asks for exactly this in general; the two new
        # tables are simply born with it.
        Index(
            "ix_time_entries_deal_data",
            "deal_id",
            "data",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_time_entries_user_data",
            "user_id",
            "data",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_time_entries_custom_fields", "custom_fields", postgresql_using="gin"),
    )

    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False)
    ore: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    descrizione: Mapped[str] = mapped_column(Text, nullable=False)
    fatturabile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tariffa_applicata: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    costo_applicato: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    tariffa_origine: Mapped[str] = mapped_column(String(10), nullable=False, default="assente")
    costo_origine: Mapped[str] = mapped_column(String(10), nullable=False, default="assente")
    invoice_line_id: Mapped[UUID | None] = mapped_column(Uuid, default=None, index=True)
    note_interne: Mapped[str | None] = mapped_column(Text, default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Cost(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Money that actually left, towards somebody else, with a receipt to prove it.

    A cost is not a time entry even though both reduce the margin, and the three
    differences are the ones that matter (§4.2): a cost is real money out with a
    document behind it, while an hour's cost is an internal, notional figure derived
    from a rate you chose yourself; an hour is also *potential revenue* and a cost
    never is; and an hour has a quantity comparable with an estimate
    (`ore_preventivate`) while a cost has only money. Merging them would leave half
    the columns null on every row and turn "hours recorded" -- the central quantity of
    this slice -- into a filtered aggregate over a table where most rows are not hours.

    `deal_id IS NULL` means a general expense: it enters the period P&L in a row of
    its own and is **never apportioned** onto any deal (§7.4). Any apportionment key
    -- on revenue, on hours -- has one precise and unacceptable consequence: a deal's
    margin would move when a *different* deal was invoiced.

    `importo` is the **total paid**, VAT included. Under the flat-rate regime input VAT
    is not deductible, so it is cost in every sense and recording the net would
    understate the cost by 22%. Under an ordinary regime the right choice is the
    opposite one, and the extension path is a second `importo_iva` column read from
    `fiscal_profile.codice_regime` -- named here as a boundary, not designed (§13).

    `document_id` is the receipt, held in slice 2's document store with its pluggable
    storage, versioning and hash. The previous system kept the attachment as base64 inside the costs
    JSON (`parseBase64Payload`); the document store already exists and is not
    reinvented.
    """

    __tablename__ = "costs"
    __table_args__ = (
        # Zero is refused because it is neither a cost nor a correction; negative is
        # allowed because it is a refund or a credit note received (§4.4).
        CheckConstraint("importo <> 0", name="ck_costs_importo_non_zero"),
        Index(
            "ix_costs_deal_data", "deal_id", "data", postgresql_where=text("deleted_at IS NULL")
        ),
        # The period P&L reads costs by date across every deal *and* the general
        # expenses, where `deal_id` is NULL and the two-column index above cannot help.
        Index("ix_costs_data", "data", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_costs_custom_fields", "custom_fields", postgresql_using="gin"),
    )

    deal_id: Mapped[UUID | None] = mapped_column(ForeignKey("deals.id"), default=None, index=True)
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("cost_categories.id"), nullable=False, index=True
    )
    data: Mapped[date] = mapped_column(Date, nullable=False)
    importo: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    descrizione: Mapped[str] = mapped_column(Text, nullable=False)
    fornitore: Mapped[str | None] = mapped_column(String(200), default=None)
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PeriodLock(Base):
    """A reported month, closed against further writes.

    No `PrimaryKeyMixin` and no `TimestampMixin`: `(anno, mese)` *is* the identity --
    a month is closed or it is not, and a surrogate id would allow two rows saying so
    -- and `chiuso_il` *is* the timestamp. This is the only table in the schema without
    a UUID key, and it is because the natural key is total.

    Freezing rates (§5) stops a rate change from rewriting a margin somebody has
    already read. This stops the other way of moving the same number: logging today an
    hour dated last March. That is not an abuse, it is the back-dating §6.3 explicitly
    allows, and it is legitimate exactly as long as the period is open.

    Closing is not mandatory: somebody who closes nothing gets the previous behaviour,
    and no screen demands a ritual before it works. And closing does **not** freeze
    invoices, which already have their own rules (slice 3 §4) and do not want a second
    set: this table governs only `time_entries` and `costs`.
    """

    __tablename__ = "period_locks"

    anno: Mapped[int] = mapped_column(Integer, primary_key=True)
    mese: Mapped[int] = mapped_column(Integer, primary_key=True)
    chiuso_il: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chiuso_da: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)

    __table_args__ = (CheckConstraint("mese >= 1 AND mese <= 12", name="ck_period_locks_mese"),)
```

```python
# packages/core/src/pigrocrm/core/timetracking/__init__.py
from pigrocrm.core.timetracking.models import Cost, CostCategory, PeriodLock, TimeEntry

__all__ = ["Cost", "CostCategory", "PeriodLock", "TimeEntry"]
```

```python
# packages/core/src/pigrocrm/core/models_registry.py -- append, keeping alphabetical order
from pigrocrm.core.timetracking.models import (  # noqa: F401
    Cost,
    CostCategory,
    PeriodLock,
    TimeEntry,
)
```

- [ ] **Step 4: Write the schemas**

```python
# packages/core/src/pigrocrm/core/timetracking/schemas.py
"""Every Create/Update/Read/ListQuery/Page for the four tables of this slice.

`max_length` mirrors every `String(n)`; `max_digits`/`decimal_places` mirror every
`Numeric(p, s)`; `SafeStr` guards every user-supplied string. Without those an
over-long value, an over-capacity number or a NUL byte reaches `flush()` and comes
back as a raw `DataError` -- not an `IntegrityError`, so no handler catches it, and the
caller's session is poisoned. This project has closed that family of defects seven
times; it is not reopened on four new tables.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.money import FACTOR_SCALE, HOURS_SCALE, MONEY_SCALE
from pigrocrm.core.validation import SafeStr

# Mirror the columns in models.py.
DESCRIZIONE_MAX_LENGTH = 2000  # `Text`, so no column width to mirror; bounded anyway
FORNITORE_MAX_LENGTH = 200
CATEGORIA_NOME_MAX_LENGTH = 60
CATEGORIA_CODE_MAX_LENGTH = 30
HOURS_MAX_DIGITS = 8
MONEY_MAX_DIGITS = 12
FACTOR_MAX_DIGITS = 12

# `ore` is bounded here as well as by `ck_time_entries_ore_range`, not instead of it:
# the schema bound turns a 422 into a message naming the field before a statement is
# ever issued, and the CHECK covers every other write path including raw SQL. `gt=0`
# not `ge=0`: a zero-hour entry is not an entry, and the way to cancel a wrong one is
# a reversible soft delete (§2.2, last row), not a zero.
ORE_MIN = Decimal("0.01")
ORE_MAX = Decimal("24.00")

CATEGORIA_POSIZIONE_MIN = 0
CATEGORIA_POSIZIONE_MAX = 100_000
ANNO_MIN = 2000
ANNO_MAX = 2200

RateOrigin = Literal["manuale", "deal", "utente", "assente"]
# `costo_origine` never takes `deal`: an hour's cost is a property of who works it,
# not of the client they work it for (§5.1). Declared as its own narrower Literal
# rather than reusing RateOrigin, so the impossible value is unrepresentable instead
# of merely unwritten.
CostOrigin = Literal["manuale", "utente", "assente"]


class TimeEntryCreate(BaseModel):
    deal_id: UUID
    user_id: UUID
    data: date
    ore: Decimal = Field(
        max_digits=HOURS_MAX_DIGITS, decimal_places=HOURS_SCALE, ge=ORE_MIN, le=ORE_MAX
    )
    descrizione: SafeStr = Field(max_length=DESCRIZIONE_MAX_LENGTH)
    fatturabile: bool = True
    # Level 1 of §5.1's resolution: an explicit value in the request wins, and the
    # frozen column is written with it and `origine = "manuale"`. Named identically to
    # the columns on purpose -- `native_fields("time_entry")` is derived from this
    # model, so a differently-named input would leave `tariffa_applicata` outside the
    # A13 guard's reach and a custom field could still collide with it.
    tariffa_applicata: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_SCALE, ge=0
    )
    costo_applicato: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_SCALE, ge=0
    )
    note_interne: SafeStr | None = None
    custom_fields: dict[str, Any] = {}


class TimeEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `deal_id` and `user_id` are both here: §4.3 lists `deal_id` among the fields
    # frozen once billed, which means it is mutable while it is not, and criterion 8
    # requires reassigning an existing entry to a user to be attempted and refused
    # when that user is deactivated -- an operation that needs the field to exist.
    deal_id: UUID | None = None
    user_id: UUID | None = None
    data: date | None = None
    ore: Decimal | None = Field(
        default=None,
        max_digits=HOURS_MAX_DIGITS,
        decimal_places=HOURS_SCALE,
        ge=ORE_MIN,
        le=ORE_MAX,
    )
    descrizione: SafeStr | None = Field(default=None, max_length=DESCRIZIONE_MAX_LENGTH)
    fatturabile: bool | None = None
    tariffa_applicata: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_SCALE, ge=0
    )
    costo_applicato: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_SCALE, ge=0
    )
    note_interne: SafeStr | None = None
    custom_fields: dict[str, Any] | None = None


class TimeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    deal_id: UUID
    user_id: UUID
    data: date
    ore: Decimal
    descrizione: str
    fatturabile: bool
    tariffa_applicata: Decimal | None
    costo_applicato: Decimal | None
    tariffa_origine: RateOrigin
    costo_origine: CostOrigin
    # Derived and returned already computed, because §6 forbids the browser from doing
    # any economic arithmetic. `None` when the corresponding factor is `None` -- never
    # `0.00`, which would say the work was free.
    valore_riga: Decimal | None = None
    costo_riga: Decimal | None = None
    invoice_line_id: UUID | None
    note_interne: str | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class TimeEntryListQuery(BaseModel):
    deal_id: UUID | None = None
    user_id: UUID | None = None
    da: date | None = None
    a: date | None = None
    fatturabile: bool | None = None
    # Three states, not two: `True` = already on an invoice line, `False` = not yet,
    # `None` = do not filter. It is the "how much do I have to invoice?" query.
    fatturato: bool | None = None
    custom: dict[str, Any] | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class TimeEntryPage(BaseModel):
    items: list[TimeEntryRead]
    next_cursor: UUID | None


class CostCreate(BaseModel):
    deal_id: UUID | None = None
    category_id: UUID
    data: date
    importo: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_SCALE)
    descrizione: SafeStr = Field(max_length=DESCRIZIONE_MAX_LENGTH)
    fornitore: SafeStr | None = Field(default=None, max_length=FORNITORE_MAX_LENGTH)
    document_id: UUID | None = None
    custom_fields: dict[str, Any] = {}


class CostUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deal_id: UUID | None = None
    category_id: UUID | None = None
    data: date | None = None
    importo: Decimal | None = Field(
        default=None, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_SCALE
    )
    descrizione: SafeStr | None = Field(default=None, max_length=DESCRIZIONE_MAX_LENGTH)
    fornitore: SafeStr | None = Field(default=None, max_length=FORNITORE_MAX_LENGTH)
    document_id: UUID | None = None
    custom_fields: dict[str, Any] | None = None


class CostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    deal_id: UUID | None
    category_id: UUID
    data: date
    importo: Decimal
    descrizione: str
    fornitore: str | None
    document_id: UUID | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class CostListQuery(BaseModel):
    deal_id: UUID | None = None
    # `True` selects only general expenses (`deal_id IS NULL`). Needed because
    # `deal_id=None` already means "do not filter", and §7.4 gives general expenses a
    # row of their own that has to be selectable.
    solo_generali: bool = False
    category_id: UUID | None = None
    da: date | None = None
    a: date | None = None
    custom: dict[str, Any] | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class CostPage(BaseModel):
    items: list[CostRead]
    next_cursor: UUID | None


class CostCategoryCreate(BaseModel):
    nome: SafeStr = Field(max_length=CATEGORIA_NOME_MAX_LENGTH)
    posizione: int = Field(default=0, ge=CATEGORIA_POSIZIONE_MIN, le=CATEGORIA_POSIZIONE_MAX)
    # `code` is never caller-supplied: it is the stable identity of a *seeded*
    # category, and letting a user claim one would let them collide with a future seed.
    # Absent from this schema on purpose, exactly as `code` is absent from
    # `PipelineStageUpdate`.


class CostCategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: SafeStr | None = Field(default=None, max_length=CATEGORIA_NOME_MAX_LENGTH)
    posizione: int | None = Field(
        default=None, ge=CATEGORIA_POSIZIONE_MIN, le=CATEGORIA_POSIZIONE_MAX
    )


class CostCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    posizione: int
    code: str | None
    archiviata: bool
    created_at: datetime
    updated_at: datetime


class PeriodLockCreate(BaseModel):
    anno: int = Field(ge=ANNO_MIN, le=ANNO_MAX)
    mese: int = Field(ge=1, le=12)


class PeriodLockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    anno: int
    mese: int
    chiuso_il: datetime
    chiuso_da: UUID | None


class RateDescription(BaseModel):
    """What `log_time` *would* freeze onto a new entry right now.

    Exists so an agent can read before it writes (slice 1 §8.4) without having to
    guess which of the three levels answers -- and so the UI can show it next to the
    hours field instead of leaving the user to discover it after saving.
    """

    deal_id: UUID
    user_id: UUID
    tariffa: Decimal | None
    tariffa_origine: RateOrigin
    costo: Decimal | None
    costo_origine: CostOrigin


class DealTimeSummary(BaseModel):
    """The hours half of a deal's economics, computed in 4A and readable with no
    invoices in the database.

    Deliberately **not** carrying `ricavi` or `valore_maturato`: revenue is the invoice
    (§3, decision 2) and there is no second notion of it. 4B's `DealPnl` adds `ricavi`
    and defines `valore_maturato = ricavi + valore_ore_non_fatturate` on top of this,
    rather than 4A shipping a zero that would read as a real figure.
    """

    deal_id: UUID
    stato: Literal["in corso", "da fatturare", "chiuso"]
    ore_totali: Decimal
    ore_fatturabili_non_fatturate: Decimal
    valore_ore_non_fatturate: Decimal
    costo_lavoro: Decimal
    ore_senza_tariffa: int
    voci: int


class RecalculateRatesRequest(BaseModel):
    da: date
    a: date


class UserRatesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tariffa_oraria_default: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_SCALE, ge=0
    )
    costo_orario_default: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_SCALE, ge=0
    )


class DealRateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tariffa_oraria: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_SCALE, ge=0
    )
```

- [ ] **Step 5: Add the rate columns to `deals` and `users`**

```python
# packages/core/src/pigrocrm/core/deals/models.py -- append to Deal, after
# valore_preventivato.
    # Numeric(12,6), not (12,2): a rate is a factor, and slice 3 makes
    # `invoice_lines.prezzo_unitario` Numeric(12,6) for the same reason ("3 hours at
    # 33.3333 EUR/h is not expressible at two places"). A rate and a unit price are
    # the same quantity seen from two tables, so a rate at two places would change
    # value the moment these hours became an invoice line, and slice 4B's
    # reconciliation would fail by cents. Level 2 of the resolution order in slice 4
    # §5.1; no report ever reads it, because the resolved value is copied onto the row.
    tariffa_oraria: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
```

```python
# packages/core/src/pigrocrm/core/auth/models.py -- append to User.
    # Level 3 of slice 4 §5.1's resolution order, for both numbers. There is
    # deliberately no `costo_orario` on `deals`: an hour's cost is a property of who
    # works it, not of the client they work it for, and adding the level would let
    # somebody declare that the same person costs differently on two projects -- an
    # accounting entry, not CRM data. Both Numeric(12,6): they are factors, and slice
    # 3's `invoice_lines.prezzo_unitario` fixes that precision.
    tariffa_oraria_default: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    costo_orario_default: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
```

Add the matching schema fields. On `deals/schemas.py`, add to `DealCreate`, `DealUpdate` and `DealRead`; introduce `FACTOR_MAX_DIGITS = 12` and `FACTOR_DECIMAL_PLACES = 6` next to the existing constants:

```python
# packages/core/src/pigrocrm/core/deals/schemas.py -- new constants beside
# VALORE_MAX_DIGITS/ORE_MAX_DIGITS/DECIMAL_PLACES.
# `tariffa_oraria` is Numeric(12,6) -- a factor, not an amount. See the column's own
# comment in models.py for why slice 3 fixes the precision.
FACTOR_MAX_DIGITS = 12
FACTOR_DECIMAL_PLACES = 6

# ... and on DealCreate, DealUpdate and DealRead:
    tariffa_oraria: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_DECIMAL_PLACES, ge=0
    )
# On DealRead the annotation is the bare `tariffa_oraria: Decimal | None` -- a Read
# schema validates values the database produced, so a bound there would reject a row
# the column legitimately holds.
```

On `auth/schemas.py`, add the same two fields to `UserCreate`, `UserUpdate` and `UserRead`, with the same `FACTOR_MAX_DIGITS`/`FACTOR_DECIMAL_PLACES` constants declared locally (do not import them across domains — `deals` and `auth` do not depend on each other today and this is not the reason to start).

**`_check_numbers` must learn the new field.** `deals/service.py:35` iterates `("valore_previsto", "valore_preventivato", "ore_preventivate")` rejecting negatives. Add `"tariffa_oraria"` to that tuple, so a negative rate raises this project's `ValidationFailed` rather than pydantic's own error — and so the `ge=0` above is a second gate, not the only one.

- [ ] **Step 6: Write migration `0004`**

```python
# packages/core/migrations/versions/0004_time_tracking.py
"""time tracking: hours, costs, cost categories, period locks and the rate columns

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cost_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("nome", sa.String(length=60), nullable=False),
        sa.Column("posizione", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=True),
        sa.Column("archiviata", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_cost_categories_code", "cost_categories", ["code"], unique=True)

    op.create_table(
        "time_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("ore", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("descrizione", sa.Text(), nullable=False),
        sa.Column("fatturabile", sa.Boolean(), nullable=False),
        sa.Column("tariffa_applicata", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("costo_applicato", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("tariffa_origine", sa.String(length=10), nullable=False),
        sa.Column("costo_origine", sa.String(length=10), nullable=False),
        # No ForeignKeyConstraint: `invoice_lines` is a slice 3 table and 4A does not
        # depend on slice 3. Migration 0005 (Task 4B-3) adds the constraint with
        # ON DELETE SET NULL once that table exists.
        sa.Column("invoice_line_id", sa.Uuid(), nullable=True),
        sa.Column("note_interne", sa.Text(), nullable=True),
        sa.Column("custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("ore > 0 AND ore <= 24", name="ck_time_entries_ore_range"),
        sa.CheckConstraint(
            "deleted_at IS NULL OR invoice_line_id IS NULL",
            name="ck_time_entries_billed_not_deleted",
        ),
        sa.CheckConstraint(
            "tariffa_origine IN ('manuale', 'deal', 'utente', 'assente')",
            name="ck_time_entries_tariffa_origine",
        ),
        sa.CheckConstraint(
            "costo_origine IN ('manuale', 'utente', 'assente')",
            name="ck_time_entries_costo_origine",
        ),
    )
    op.create_index("ix_time_entries_deal_id", "time_entries", ["deal_id"])
    op.create_index("ix_time_entries_invoice_line_id", "time_entries", ["invoice_line_id"])
    op.create_index(
        "ix_time_entries_deal_data",
        "time_entries",
        ["deal_id", "data"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_time_entries_user_data",
        "time_entries",
        ["user_id", "data"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_time_entries_custom_fields", "time_entries", ["custom_fields"], postgresql_using="gin"
    )

    op.create_table(
        "costs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("importo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("descrizione", sa.Text(), nullable=False),
        sa.Column("fornitore", sa.String(length=200), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["cost_categories.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("importo <> 0", name="ck_costs_importo_non_zero"),
    )
    op.create_index("ix_costs_deal_id", "costs", ["deal_id"])
    op.create_index("ix_costs_category_id", "costs", ["category_id"])
    op.create_index(
        "ix_costs_deal_data", "costs", ["deal_id", "data"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_costs_data", "costs", ["data"], postgresql_where=sa.text("deleted_at IS NULL")
    )
    op.create_index("ix_costs_custom_fields", "costs", ["custom_fields"], postgresql_using="gin")

    op.create_table(
        "period_locks",
        sa.Column("anno", sa.Integer(), nullable=False),
        sa.Column("mese", sa.Integer(), nullable=False),
        sa.Column("chiuso_il", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chiuso_da", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["chiuso_da"], ["users.id"]),
        sa.PrimaryKeyConstraint("anno", "mese"),
        sa.CheckConstraint("mese >= 1 AND mese <= 12", name="ck_period_locks_mese"),
    )

    op.add_column("deals", sa.Column("tariffa_oraria", sa.Numeric(precision=12, scale=6), nullable=True))
    op.add_column(
        "users", sa.Column("tariffa_oraria_default", sa.Numeric(precision=12, scale=6), nullable=True)
    )
    op.add_column(
        "users", sa.Column("costo_orario_default", sa.Numeric(precision=12, scale=6), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "costo_orario_default")
    op.drop_column("users", "tariffa_oraria_default")
    op.drop_column("deals", "tariffa_oraria")
    op.drop_table("period_locks")
    op.drop_table("costs")
    op.drop_table("time_entries")
    op.drop_table("cost_categories")
```

- [ ] **Step 7: Extend the existing migration parity test**

Do not create a second migration test file. `packages/core/tests/test_migrations.py` already asserts the applied revision and metadata parity; change the expected head from `"0003"` to `"0004"` and let the existing parity assertion do the rest — it is what catches a column present in the model and absent from the migration.

- [ ] **Step 8: Run everything**

Run: `uv run pytest packages/core/tests/test_timetracking_models.py packages/core/tests/test_migrations.py packages/core/tests/test_deals.py packages/core/tests/test_auth_users.py packages/core/tests/test_entity_types.py packages/core/tests/test_module_imports.py -v`
Expected: PASS. Then `uv run mypy` and `uv run ruff check .` — both clean.

- [ ] **Step 9: Commit**

```bash
git add packages/core apps/web/src/lib/schema.ts
git commit -m "feat(timetracking): time_entries, costs, cost_categories, period_locks and the rate columns"
```

---

### Task 4A-6: `CostCategoryService` — configurable, archivable, audited

**Files:**
- Create: `packages/core/src/pigrocrm/core/timetracking/categories.py`
- Test: `packages/core/tests/test_cost_categories.py`

**Interfaces:**
- Consumes: `CostCategoryCreate`, `CostCategoryUpdate`, `CostCategoryRead` (Task 4A-5); `Actor.require_admin`; `ActivityService.record(entity_type, entity_id, kind, actor, payload=None) -> Activity`; `errors.{Conflict, NotFound, ValidationFailed}`.
- Produces:
  ```python
  ENTITY = "cost_category"
  SEED_CATEGORIES: tuple[tuple[str, str, int], ...]   # (code, nome, posizione)

  class CostCategoryRepository:
      def __init__(self, session: Session) -> None
      def get(self, category_id: UUID) -> CostCategory | None
      def get_by_code(self, code: str) -> CostCategory | None
      def get_by_nome(self, nome: str) -> CostCategory | None
      def add(self, category: CostCategory) -> CostCategory
      def count_costs(self, category_id: UUID) -> int
      def list(self, *, include_archived: bool = False) -> list[CostCategory]   # LAST

  class CostCategoryService:
      def __init__(self, session: Session) -> None
      def create_cost_category(self, data: CostCategoryCreate, actor: Actor) -> CostCategoryRead
      def update_cost_category(self, category_id: UUID, data: CostCategoryUpdate, actor: Actor) -> CostCategoryRead
      def archive_cost_category(self, category_id: UUID, actor: Actor) -> CostCategoryRead
      def unarchive_cost_category(self, category_id: UUID, actor: Actor) -> CostCategoryRead
      def seed_defaults(self, actor: Actor) -> list[CostCategoryRead]
      def require_active(self, category_id: UUID) -> CostCategory
      def list_cost_categories(self, *, include_archived: bool = False) -> list[CostCategoryRead]
  ```
  The three write methods are named `create_cost_category` / `update_cost_category` / `archive_cost_category` — **not** `create`/`update`/`archive` — because §11's MCP exclusion list is exactly ten literal names and three of them are these. The list method is `list_cost_categories`, so this class defines no method named `list` and the "must be last" rule does not arise; `list` on the *repository* does, and stays last there.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_cost_categories.py
"""A configurable taxonomy, on the pipeline-stage model: `code` is the stable identity
of a seed, `nome` is the label a user may rename, and `archiviata` replaces deletion."""

from decimal import Decimal
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.timetracking.categories import SEED_CATEGORIES, CostCategoryService
from pigrocrm.core.timetracking.models import Cost
from pigrocrm.core.timetracking.schemas import CostCategoryCreate, CostCategoryUpdate

ADMIN = Actor(id=None, type="system", role="admin")
COLLABORATOR = Actor(id=None, type="user", role="collaboratore")


def test_seed_creates_the_five_named_categories(db_session: Session) -> None:
    created = CostCategoryService(db_session).seed_defaults(ADMIN)
    assert [c.nome for c in created] == [
        "Consulenza esterna",
        "Software e licenze",
        "Viaggi e trasferte",
        "Materiali",
        "Altro",
    ]
    assert [c.code for c in created] == [code for code, _, _ in SEED_CATEGORIES]
    assert [c.posizione for c in created] == [0, 1, 2, 3, 4]


def test_seed_deduplicates_on_code_not_on_nome(db_session: Session) -> None:
    """The exact bug residual R11 records against `pipeline_stages`: `seed_defaults`
    deduplicated on `nome`, the one field the user is free to change, so renaming a
    seeded row made the next seed create a duplicate."""
    service = CostCategoryService(db_session)
    first = service.seed_defaults(ADMIN)
    renamed = first[0]
    service.update_cost_category(renamed.id, CostCategoryUpdate(nome="Fornitori terzi"), ADMIN)

    again = service.seed_defaults(ADMIN)
    assert again == []
    assert len(service.list_cost_categories(include_archived=True)) == len(SEED_CATEGORIES)


def test_a_duplicate_name_is_a_conflict_case_insensitively(db_session: Session) -> None:
    service = CostCategoryService(db_session)
    service.create_cost_category(CostCategoryCreate(nome="Trasferte"), ADMIN)
    with pytest.raises(Conflict):
        service.create_cost_category(CostCategoryCreate(nome="  trasferte "), ADMIN)


def test_archiving_keeps_existing_costs_readable(db_session: Session, seeded_deal_id: UUID) -> None:
    """§5.6's first rule, applied: a deleted category with costs still attached would
    produce orphan rows nobody can see. Archiving hides it from the picker and leaves
    the data readable."""
    service = CostCategoryService(db_session)
    category = service.create_cost_category(CostCategoryCreate(nome="Hosting"), ADMIN)
    db_session.add(
        Cost(
            deal_id=seeded_deal_id, category_id=category.id, data=date(2026, 3, 1),
            importo=Decimal("42.00"), descrizione="VPS",
        )
    )
    db_session.flush()

    archived = service.archive_cost_category(category.id, ADMIN)
    assert archived.archiviata is True
    assert category.id not in {c.id for c in service.list_cost_categories()}
    assert category.id in {c.id for c in service.list_cost_categories(include_archived=True)}
    with pytest.raises(ValidationFailed) as excinfo:
        service.require_active(category.id)
    assert excinfo.value.details["field"] == "category_id"


def test_unarchive_brings_it_back(db_session: Session) -> None:
    service = CostCategoryService(db_session)
    category = service.create_cost_category(CostCategoryCreate(nome="Hosting"), ADMIN)
    service.archive_cost_category(category.id, ADMIN)
    assert service.unarchive_cost_category(category.id, ADMIN).archiviata is False


def test_every_write_records_an_activity(db_session: Session) -> None:
    """R5 closes here for this table: the timeline is what reconstructs when the
    taxonomy changed, and that is not hygiene -- it is what lets §5 skip historicising
    anything."""
    service = CostCategoryService(db_session)
    category = service.create_cost_category(CostCategoryCreate(nome="Hosting"), ADMIN)
    service.update_cost_category(category.id, CostCategoryUpdate(nome="Cloud"), ADMIN)
    service.archive_cost_category(category.id, ADMIN)
    kinds = [
        entry.kind
        for entry in ActivityService(db_session).timeline("cost_category", category.id)
    ]
    assert kinds == ["archived", "updated", "created"]  # newest first


def test_every_write_is_admin_only(db_session: Session) -> None:
    service = CostCategoryService(db_session)
    for call in (
        lambda: service.create_cost_category(CostCategoryCreate(nome="X"), COLLABORATOR),
        lambda: service.archive_cost_category(uuid4(), COLLABORATOR),
        lambda: service.seed_defaults(COLLABORATOR),
    ):
        with pytest.raises(PermissionDenied):
            call()


def test_an_unknown_id_is_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        CostCategoryService(db_session).archive_cost_category(uuid4(), ADMIN)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_cost_categories.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.timetracking.categories'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/timetracking/categories.py
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.timetracking.models import Cost, CostCategory
from pigrocrm.core.timetracking.schemas import (
    CostCategoryCreate,
    CostCategoryRead,
    CostCategoryUpdate,
)

ENTITY = "cost_category"

# (code, nome, posizione). `code` is the stable identity a rename cannot touch; the
# five names come straight from spec §4.2.
SEED_CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("consulenza_esterna", "Consulenza esterna", 0),
    ("software_licenze", "Software e licenze", 1),
    ("viaggi_trasferte", "Viaggi e trasferte", 2),
    ("materiali", "Materiali", 3),
    ("altro", "Altro", 4),
)


def _conflicting_nome(nome: str) -> Conflict:
    return Conflict(ENTITY, "esiste già una categoria con questo nome", nome=nome)


class CostCategoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, category_id: UUID) -> CostCategory | None:
        return self.session.get(CostCategory, category_id)

    def get_by_code(self, code: str) -> CostCategory | None:
        return self.session.execute(
            select(CostCategory).where(CostCategory.code == code)
        ).scalar_one_or_none()

    def get_by_nome(self, nome: str) -> CostCategory | None:
        """Case-insensitive, matching `uq_cost_categories_nome`'s functional index.
        A pre-check on the raw column would pass for `"trasferte"` against a stored
        `"Trasferte"` and then be refused by the database with a raw
        `IntegrityError`."""
        return self.session.execute(
            select(CostCategory).where(func.lower(CostCategory.nome) == nome.strip().lower())
        ).scalar_one_or_none()

    def add(self, category: CostCategory) -> CostCategory:
        self.session.add(category)
        self.session.flush()
        return category

    def count_costs(self, category_id: UUID) -> int:
        return int(
            self.session.execute(
                select(func.count())
                .select_from(Cost)
                .where(Cost.category_id == category_id, Cost.deleted_at.is_(None))
            ).scalar_one()
        )

    # `list` stays the last method in this class -- the unconditional project rule.
    def list(self, *, include_archived: bool = False) -> list[CostCategory]:
        stmt = select(CostCategory)
        if not include_archived:
            stmt = stmt.where(CostCategory.archiviata.is_(False))
        return list(
            self.session.execute(stmt.order_by(CostCategory.posizione, CostCategory.nome)).scalars()
        )


class CostCategoryService:
    """Configuration, so every write is `admin` and every write records an activity.

    The three write methods are deliberately named `create_cost_category`,
    `update_cost_category` and `archive_cost_category` rather than the shorter
    `create`/`update`/`archive` used elsewhere: spec §11 fixes the MCP exclusion list
    to exactly ten literal method names, three of which are these, and the
    architecture test in Task 4A-13 matches on the name. A shorter name here would
    make the ban unenforceable by exactly the mechanism §11 exists to provide.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CostCategoryRepository(session)
        self.activities = ActivityService(session)

    def create_cost_category(self, data: CostCategoryCreate, actor: Actor) -> CostCategoryRead:
        actor.require_admin("create_cost_category")
        nome = data.nome.strip()
        if not nome:
            raise ValidationFailed(ENTITY, "nome", "nome vuoto", expected="un nome non vuoto")
        if self.repo.get_by_nome(nome):
            raise _conflicting_nome(nome)

        category = CostCategory(nome=nome, posizione=data.posizione, code=None, archiviata=False)
        try:
            self.repo.add(category)
            self.activities.record(ENTITY, category.id, "created", actor, {"nome": nome})
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a race between two concurrent requests:
            # there the functional unique index is the only authority. The rollback is
            # mandatory -- without it the caller's session is unusable.
            self.session.rollback()
            raise _conflicting_nome(nome) from exc
        return CostCategoryRead.model_validate(category)

    def update_cost_category(
        self, category_id: UUID, data: CostCategoryUpdate, actor: Actor
    ) -> CostCategoryRead:
        actor.require_admin("update_cost_category")
        category = self._require(category_id)
        changes = data.model_dump(exclude_none=True)
        if "nome" in changes:
            nome = changes["nome"].strip()
            if not nome:
                raise ValidationFailed(ENTITY, "nome", "nome vuoto", expected="un nome non vuoto")
            existing = self.repo.get_by_nome(nome)
            if existing is not None and existing.id != category.id:
                raise _conflicting_nome(nome)
            changes["nome"] = nome
        for key, value in changes.items():
            setattr(category, key, value)

        try:
            self.activities.record(
                ENTITY, category.id, "updated", actor, {"changed": sorted(changes)}
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise _conflicting_nome(str(changes.get("nome", category.nome))) from exc
        return CostCategoryRead.model_validate(category)

    def archive_cost_category(self, category_id: UUID, actor: Actor) -> CostCategoryRead:
        """Archive, never delete. A deleted category with costs still attached leaves
        orphan rows nobody can see -- the first of slice 1 §5.6's three rules. The
        stored `category_id` on every existing cost keeps resolving, so a report from
        last year still names its categories."""
        actor.require_admin("archive_cost_category")
        category = self._require(category_id)
        category.archiviata = True
        self.activities.record(
            ENTITY, category.id, "archived", actor, {"costi": self.repo.count_costs(category.id)}
        )
        self.session.commit()
        return CostCategoryRead.model_validate(category)

    def unarchive_cost_category(self, category_id: UUID, actor: Actor) -> CostCategoryRead:
        actor.require_admin("unarchive_cost_category")
        category = self._require(category_id)
        category.archiviata = False
        self.activities.record(ENTITY, category.id, "unarchived", actor)
        self.session.commit()
        return CostCategoryRead.model_validate(category)

    def seed_defaults(self, actor: Actor) -> list[CostCategoryRead]:
        """Idempotent, deduplicating on `code` and never on `nome`.

        Residual R11 records the bug this avoids: `PipelineService.seed_defaults`
        deduplicated on `nome`, the one field a user is free to change, so a renamed
        seed row produced a duplicate on the next seed. Returns only what it actually
        created, so a caller can tell "seeded" from "already there".
        """
        actor.require_admin("seed_cost_categories")
        created: list[CostCategoryRead] = []
        for code, nome, posizione in SEED_CATEGORIES:
            if self.repo.get_by_code(code) is not None:
                continue
            category = self.repo.add(
                CostCategory(nome=nome, posizione=posizione, code=code, archiviata=False)
            )
            self.activities.record(ENTITY, category.id, "created", actor, {"nome": nome, "code": code})
            created.append(CostCategoryRead.model_validate(category))
        self.session.commit()
        return created

    def require_active(self, category_id: UUID) -> CostCategory:
        """What `CostService` calls on create and update. `ValidationFailed`, not
        `NotFound`, for an archived category: the row exists and the caller can see it
        in the archived list -- what is wrong is choosing it for a new cost, which is a
        validation problem naming the field."""
        category = self.repo.get(category_id)
        if category is None:
            raise NotFound(ENTITY, category_id)
        if category.archiviata:
            raise ValidationFailed(
                ENTITY,
                "category_id",
                "la categoria è archiviata",
                expected="una categoria attiva",
            )
        return category

    def _require(self, category_id: UUID) -> CostCategory:
        category = self.repo.get(category_id)
        if category is None:
            raise NotFound(ENTITY, category_id)
        return category

    def list_cost_categories(self, *, include_archived: bool = False) -> list[CostCategoryRead]:
        return [
            CostCategoryRead.model_validate(c)
            for c in self.repo.list(include_archived=include_archived)
        ]
```

Add the functional unique index the repository's case-insensitive pre-check assumes. In `models.py`, `CostCategory.__table_args__` becomes:

```python
    __table_args__ = (
        Index("uq_cost_categories_code", "code", unique=True),
        # Case-insensitive identity needs a functional index, not a convention: a
        # plain unique=True on a text column is case-sensitive, and normalising in the
        # service protects only the paths that go through it.
        Index("uq_cost_categories_nome", func.lower(nome), unique=True),
    )
```

and migration `0004` gains, right after `uq_cost_categories_code`:

```python
    op.execute(
        "CREATE UNIQUE INDEX uq_cost_categories_nome ON cost_categories (lower(nome))"
    )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_cost_categories.py packages/core/tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(timetracking): configurable cost categories, archived not deleted, audited"
```

---

### Task 4A-7: Rates — resolved once, frozen onto the row (the slice's central guarantee)

**Files:**
- Create: `packages/core/src/pigrocrm/core/timetracking/rates.py`
- Test: `packages/core/tests/test_rates.py`

**Interfaces:**
- Consumes: `Deal` (`deals/models.py`, with the new `tariffa_oraria`); `User` (`auth/models.py`, with the two new defaults); `RateDescription`, `RateOrigin`, `CostOrigin` (Task 4A-5); `pigrocrm.core.money.FACTOR_QUANT`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class ResolvedRates:
      tariffa: Decimal | None
      tariffa_origine: RateOrigin   # "manuale" | "deal" | "utente" | "assente"
      costo: Decimal | None
      costo_origine: CostOrigin     # "manuale" | "utente" | "assente"

  class RateResolver:
      def __init__(self, session: Session) -> None
      def resolve(
          self,
          *,
          deal_id: UUID,
          user_id: UUID,
          tariffa_esplicita: Decimal | None = None,
          costo_esplicito: Decimal | None = None,
      ) -> ResolvedRates
      def describe(self, *, deal_id: UUID, user_id: UUID) -> RateDescription
  ```
  `RateResolver` is a plain helper, not a service: it takes no `Actor`, owns no transaction, and is therefore not part of the audited MCP surface. `TimeEntryService` (Task 4A-9) is the only caller that writes what it returns.
- The two rate-writing methods named in §11's exclusion list — `update_user_rates` and `update_deal_rate` — live on `TimeEntryService` and are implemented in Task 4A-9, not here, for the reason recorded in "Contradictions" item 4.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_rates.py
"""§5.1's resolution order and, more importantly, §5's guarantee: what happens to last
quarter's margin when you raise a rate today. The answer must be "nothing", and not
out of discipline -- by construction, because no report ever reads a rate column."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.timetracking.rates import RateResolver


def _set_deal_rate(db_session: Session, deal_id: UUID, value: Decimal | None) -> None:
    db_session.get(Deal, deal_id).tariffa_oraria = value
    db_session.flush()


def _set_user_rates(
    db_session: Session, user_id: UUID, tariffa: Decimal | None, costo: Decimal | None
) -> None:
    user = db_session.get(User, user_id)
    user.tariffa_oraria_default = tariffa
    user.costo_orario_default = costo
    db_session.flush()


def test_an_explicit_value_wins_and_is_marked_manuale(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, Decimal("120.000000"), Decimal("40.000000"))
    resolved = RateResolver(db_session).resolve(
        deal_id=seeded_deal_id,
        user_id=seeded_user_id,
        tariffa_esplicita=Decimal("99.500000"),
        costo_esplicito=Decimal("10.250000"),
    )
    assert resolved.tariffa == Decimal("99.500000")
    assert resolved.tariffa_origine == "manuale"
    assert resolved.costo == Decimal("10.250000")
    assert resolved.costo_origine == "manuale"


def test_the_deal_rate_is_level_two(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, Decimal("120.000000"), Decimal("40.000000"))
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert (resolved.tariffa, resolved.tariffa_origine) == (Decimal("150.000000"), "deal")
    # The internal cost has no deal level at all: it is a property of who works the
    # hour, not of the client they work it for. So it falls to the user level here.
    assert (resolved.costo, resolved.costo_origine) == (Decimal("40.000000"), "utente")


def test_the_user_default_is_level_three(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, None)
    _set_user_rates(db_session, seeded_user_id, Decimal("120.000000"), Decimal("40.000000"))
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert (resolved.tariffa, resolved.tariffa_origine) == (Decimal("120.000000"), "utente")


def test_nothing_resolves_to_none_never_to_zero(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """No global default and no silent fall back to zero. A `0.00` would say "this
    work was free", which is a lie that sums; a global default would be a number
    nobody chose quietly becoming everybody's rate."""
    _set_deal_rate(db_session, seeded_deal_id, None)
    _set_user_rates(db_session, seeded_user_id, None, None)
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert resolved.tariffa is None and resolved.tariffa_origine == "assente"
    assert resolved.costo is None and resolved.costo_origine == "assente"


def test_costo_origine_is_never_deal(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """A consequence to read off the table, not a coincidence: `costo_origine`'s
    possible values are `manuale`, `utente`, `assente` and nothing else."""
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, None, None)
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert resolved.costo_origine == "assente"


def test_an_explicit_zero_is_a_choice_and_survives(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """`0` is a value, never a blank -- the same rule the frontend's `isBlank` follows.
    Somebody writing 0.000000 is declaring free work on purpose, and the resolver must
    not fall through to a deal rate behind their back."""
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    resolved = RateResolver(db_session).resolve(
        deal_id=seeded_deal_id, user_id=seeded_user_id, tariffa_esplicita=Decimal("0.000000")
    )
    assert resolved.tariffa == Decimal("0.000000")
    assert resolved.tariffa_origine == "manuale"


def test_describe_answers_before_anything_is_written(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, None, Decimal("40.000000"))
    described = RateResolver(db_session).describe(
        deal_id=seeded_deal_id, user_id=seeded_user_id
    )
    assert described.tariffa == Decimal("150.000000")
    assert described.tariffa_origine == "deal"
    assert described.costo == Decimal("40.000000")
    assert described.costo_origine == "utente"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_rates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.timetracking.rates'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/timetracking/rates.py
"""Rate resolution -- the one place §5.1's order is expressed, and the only place it
is ever consulted.

The whole design turns on one question: what happens to last quarter's margin when
you raise a rate today? The answer is "nothing", and not out of discipline. A rate is
resolved exactly once, at write time, and copied onto the row; from then on no report
reads `deals.tariffa_oraria` or `users.tariffa_oraria_default` at all. The row is the
authority on itself, always and only -- the same shape as `invoices.snapshot` (slice 3
§8.3), applied to the smallest unit.

`rate_history(user_id, valido_da, valido_a, tariffa)` was considered and rejected for
three reasons, all verifiable. It does not remove the copy, it duplicates it: even
with a history, an entry *back-dated* today would read the rate of the period it names
and change a total somebody has already read, so the value would still have to be
frozen -- and then the history is a second place the same truth can diverge. It turns
every read into a temporal join whose validity intervals are editable, so correcting a
`valido_da` silently rewrites the margins of every period it covers. And the question
it would answer -- "when did Marco's rate change?" -- is already answered better by
the timeline (§4.5), which is also the only place that says *who* changed it. The same
reasoning slice 3 §7.1 used to refuse historicising `fiscal_profile`.

There is deliberately no "this person's rate on this deal" level. It is the fourth
level every system of this kind eventually grows, and it stays out because nobody
exercises it today: the audience is a freelancer or a two-person studio, where the
rate is set by the contract with the client (level `deal`) and the exception is
written on the single entry (level `manuale`). The extension path, if it is ever
needed, is a `deal_user_rates(deal_id, user_id, tariffa)` table inserted between
levels 1 and 2 -- no new column on any existing table, and the freezing above makes it
invisible to every row already written.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.errors import NotFound
from pigrocrm.core.timetracking.schemas import CostOrigin, RateDescription, RateOrigin


@dataclass(frozen=True)
class ResolvedRates:
    tariffa: Decimal | None
    tariffa_origine: RateOrigin
    costo: Decimal | None
    costo_origine: CostOrigin


class RateResolver:
    """A helper, not a service: no `Actor`, no transaction, no commit.

    That distinction is load-bearing beyond taste. The architecture test in Task
    4A-13 audits the public methods of the *services* in this slice and demands that
    each either has an MCP tool or appears in the ten-name exclusion list. A resolver
    that took an `Actor` would look like a service and force a spurious entry into
    one of those two lists.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def _deal(self, deal_id: UUID) -> Deal:
        deal = self.session.get(Deal, deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)
        return deal

    def _user(self, user_id: UUID) -> User:
        # Plain `get`, not `get_active`: reading the rate of a deactivated user is
        # correct -- their historical hours stay in the P&L with their name, because
        # the money really was spent (residual R3's answer). Refusing to *assign* new
        # hours to them is `TimeEntryService`'s job, through `get_active`, and belongs
        # there rather than here.
        user = self.session.get(User, user_id)
        if user is None:
            raise NotFound("user", user_id)
        return user

    def resolve(
        self,
        *,
        deal_id: UUID,
        user_id: UUID,
        tariffa_esplicita: Decimal | None = None,
        costo_esplicito: Decimal | None = None,
    ) -> ResolvedRates:
        """Stops at the first level that yields a value.

        `is not None`, never a truthiness test: an explicit `Decimal("0.000000")` is a
        choice -- somebody declaring free work on purpose -- and falling through it to
        a deal rate would overwrite a decision behind their back. `0` is a value,
        never a blank; the same rule `fields/validator.py:is_blank` already states and
        the frontend's `isBlank` mirrors.
        """
        deal = self._deal(deal_id)
        user = self._user(user_id)

        tariffa: Decimal | None
        tariffa_origine: RateOrigin
        if tariffa_esplicita is not None:
            tariffa, tariffa_origine = tariffa_esplicita, "manuale"
        elif deal.tariffa_oraria is not None:
            tariffa, tariffa_origine = deal.tariffa_oraria, "deal"
        elif user.tariffa_oraria_default is not None:
            tariffa, tariffa_origine = user.tariffa_oraria_default, "utente"
        else:
            # `None`, never `0.00`. A silent zero would say "this work was free",
            # which is a lie that sums; a global default would be a number nobody
            # chose quietly becoming everybody's rate. In the P&L these hours appear
            # in the hour count, are excluded from the accrued value and from the
            # margin, and are named on screen as "ore senza tariffa" with their count.
            tariffa, tariffa_origine = None, "assente"

        costo: Decimal | None
        costo_origine: CostOrigin
        if costo_esplicito is not None:
            costo, costo_origine = costo_esplicito, "manuale"
        elif user.costo_orario_default is not None:
            costo, costo_origine = user.costo_orario_default, "utente"
        else:
            costo, costo_origine = None, "assente"
        # No `deal` branch above, by design: `costo_origine` never takes that value,
        # which is why `CostOrigin` is a narrower Literal than `RateOrigin` rather
        # than the same one with a value nobody writes.

        return ResolvedRates(tariffa, tariffa_origine, costo, costo_origine)

    def describe(self, *, deal_id: UUID, user_id: UUID) -> RateDescription:
        """What a new entry would freeze right now, without writing one. Backs the
        `describe_rates` tool and endpoint: reading before acting (slice 1 §8.4)."""
        resolved = self.resolve(deal_id=deal_id, user_id=user_id)
        return RateDescription(
            deal_id=deal_id,
            user_id=user_id,
            tariffa=resolved.tariffa,
            tariffa_origine=resolved.tariffa_origine,
            costo=resolved.costo,
            costo_origine=resolved.costo_origine,
        )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_rates.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(timetracking): rate resolution, one level at a time, no global default"
```

---

### Task 4A-8: Period locks — the other half of the guarantee

**Files:**
- Create: `packages/core/src/pigrocrm/core/timetracking/locks.py`
- Test: `packages/core/tests/test_period_locks.py`

**Interfaces:**
- Consumes: `PeriodLock` (Task 4A-5); `PeriodLockCreate`, `PeriodLockRead`; `Actor.require_admin`; `ActivityService.record`; `errors.{Conflict, NotFound}`.
- Produces:
  ```python
  ENTITY = "period_lock"

  class PeriodLockRepository:
      def __init__(self, session: Session) -> None
      def get(self, anno: int, mese: int) -> PeriodLock | None
      def add(self, lock: PeriodLock) -> PeriodLock
      def delete(self, lock: PeriodLock) -> None
      def list(self, *, anno: int | None = None) -> list[PeriodLock]   # LAST

  class PeriodLockService:
      def __init__(self, session: Session) -> None
      def close_period(self, data: PeriodLockCreate, actor: Actor) -> PeriodLockRead
      def reopen_period(self, anno: int, mese: int, actor: Actor) -> None
      def is_closed(self, giorno: date) -> PeriodLockRead | None
      def assert_writable(self, entity: str, field: str, *giorni: date | None) -> None
      def list_locks(self, *, anno: int | None = None) -> list[PeriodLockRead]
  ```
  `close_period` and `reopen_period` are two of §11's ten excluded names, spelled exactly. `assert_writable` takes several days because an update has to check both the old and the new date — moving a row out of a closed month is still a write into it.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_period_locks.py
"""Freezing rates closes half of it. This is the other half: back-dating an entry into
a month somebody has already reported still moves that month's number. §6.4."""

from datetime import date
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.schemas import PeriodLockCreate

COLLABORATOR = Actor(id=None, type="user", role="collaboratore")


def test_closing_a_month_records_who_and_when(db_session: Session, seeded_user_id: UUID) -> None:
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    lock = PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    assert (lock.anno, lock.mese, lock.chiuso_da) == (2026, 3, seeded_user_id)
    assert lock.chiuso_il is not None


def test_a_write_dated_inside_a_closed_month_is_refused_and_names_it(
    db_session: Session, seeded_user_id: UUID
) -> None:
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = PeriodLockService(db_session)
    service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)

    with pytest.raises(Conflict) as excinfo:
        service.assert_writable("time_entry", "data", date(2026, 3, 31))
    details = excinfo.value.details
    assert details["anno"] == 2026 and details["mese"] == 3
    assert details["chiuso_da"] == str(seeded_user_id)
    assert "marzo 2026" in excinfo.value.message


@pytest.mark.parametrize(
    "giorno", [date(2026, 2, 28), date(2026, 4, 1)], ids=["month-before", "month-after"]
)
def test_the_neighbouring_months_stay_writable(
    db_session: Session, seeded_user_id: UUID, giorno: date
) -> None:
    """The boundary, explicitly: a lock on 2026-03 must not leak onto 28 February or
    1 April. A month is closed, not a range."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = PeriodLockService(db_session)
    service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    service.assert_writable("time_entry", "data", giorno)  # must not raise


def test_moving_a_row_out_of_a_closed_month_is_still_a_write_into_it(
    db_session: Session, seeded_user_id: UUID
) -> None:
    """The reason `assert_writable` is variadic: an update supplies both the stored
    date and the new one, and either falling inside a closed month refuses the
    write."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = PeriodLockService(db_session)
    service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    with pytest.raises(Conflict):
        service.assert_writable("time_entry", "data", date(2026, 3, 15), date(2026, 4, 15))
    with pytest.raises(Conflict):
        service.assert_writable("time_entry", "data", date(2026, 4, 15), date(2026, 3, 15))


def test_none_days_are_skipped(db_session: Session, seeded_user_id: UUID) -> None:
    """An update that does not touch `data` passes `None` for the new value; that is
    "unchanged", not "the epoch"."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = PeriodLockService(db_session)
    service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    service.assert_writable("time_entry", "data", None, date(2026, 4, 1))


def test_reopening_is_admin_and_leaves_a_trace(db_session: Session, seeded_user_id: UUID) -> None:
    """A period is not reopened by accident and is not reopened in silence."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = PeriodLockService(db_session)
    service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    service.reopen_period(2026, 3, admin)
    assert service.is_closed(date(2026, 3, 15)) is None
    service.assert_writable("time_entry", "data", date(2026, 3, 15))

    with pytest.raises(PermissionDenied):
        service.reopen_period(2026, 3, COLLABORATOR)


def test_closing_twice_is_a_conflict_and_reopening_an_open_month_is_not_found(
    db_session: Session, seeded_user_id: UUID
) -> None:
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = PeriodLockService(db_session)
    service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    with pytest.raises(Conflict):
        service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    with pytest.raises(NotFound):
        service.reopen_period(2026, 4, admin)


def test_closing_nothing_leaves_everything_writable(db_session: Session) -> None:
    """Closing is not mandatory: somebody who closes nothing gets the previous
    behaviour, and no screen demands a ritual before it works."""
    PeriodLockService(db_session).assert_writable("time_entry", "data", date(1999, 1, 1))


def test_the_timeline_carries_both_events(db_session: Session, seeded_user_id: UUID) -> None:
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = PeriodLockService(db_session)
    service.close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    service.reopen_period(2026, 3, admin)
    entries = ActivityService(db_session).timeline("period_lock", PERIOD_LOCK_TIMELINE_ID)
    assert [entry.kind for entry in entries] == ["reopened", "closed"]
    assert entries[0].payload == {"anno": 2026, "mese": 3}
```

`PERIOD_LOCK_TIMELINE_ID` is exported by the module — see the implementation's own comment for why a table without a UUID key needs one fixed id to hang its timeline on. Import it in the test:

```python
from pigrocrm.core.timetracking.locks import PERIOD_LOCK_TIMELINE_ID, PeriodLockService
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_period_locks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.timetracking.locks'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/timetracking/locks.py
"""Closed periods.

§5 stops a rate change from rewriting a margin somebody has already read. This stops
the other way of moving the same number: recording today an hour dated last March.
That is not an abuse -- it is the back-dating §6.3 explicitly allows, and it is
legitimate for exactly as long as the period is open.

Two deliberate properties. **Closing is not mandatory**: somebody who closes nothing
gets the previous behaviour, and no screen demands a ritual before it works. And
**closing does not freeze invoices**, which already have their own rules (slice 3 §4)
and do not want a second set: this table governs only `time_entries` and `costs`.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.timetracking.models import PeriodLock
from pigrocrm.core.timetracking.schemas import PeriodLockCreate, PeriodLockRead

ENTITY = "period_lock"

# `activities.entity_id` is a non-null UUID, and `period_locks` is the one table in
# this schema with no UUID key -- `(anno, mese)` is its whole identity (see the
# model's docstring). Every close and reopen therefore hangs off one fixed,
# well-known id, with the real month in the payload. The alternative -- deriving a
# UUID from the year and month -- would make the timeline of "the closures" impossible
# to read as one sequence, which is the only way anybody wants to read it.
PERIOD_LOCK_TIMELINE_ID = UUID("00000000-0000-0000-0000-0000706c6f63")

MESI_ITALIANI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def period_label(anno: int, mese: int) -> str:
    """`marzo 2026`. Long-form Italian, carried over from the previous system's own period label:
    the monthly cut is what a client expects next to an invoice, and it is what gets
    agreed on."""
    return f"{MESI_ITALIANI[mese - 1]} {anno}"


class PeriodLockRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, anno: int, mese: int) -> PeriodLock | None:
        return self.session.get(PeriodLock, (anno, mese))

    def add(self, lock: PeriodLock) -> PeriodLock:
        self.session.add(lock)
        self.session.flush()
        return lock

    def delete(self, lock: PeriodLock) -> None:
        """The one physical delete in this slice, and it is correct: a lock is not a
        record of anything, it is a switch. Its history lives in the timeline, which
        is why `reopen_period` writes one. Keeping a tombstone row would mean
        `is_closed` had to distinguish "closed" from "was closed", which is precisely
        the ambiguity the primary key exists to rule out."""
        self.session.delete(lock)
        self.session.flush()

    # `list` stays the last method in this class -- the unconditional project rule.
    def list(self, *, anno: int | None = None) -> list[PeriodLock]:
        stmt = select(PeriodLock)
        if anno is not None:
            stmt = stmt.where(PeriodLock.anno == anno)
        return list(
            self.session.execute(
                stmt.order_by(PeriodLock.anno.desc(), PeriodLock.mese.desc())
            ).scalars()
        )


class PeriodLockService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = PeriodLockRepository(session)
        self.activities = ActivityService(session)

    def close_period(self, data: PeriodLockCreate, actor: Actor) -> PeriodLockRead:
        actor.require_admin("close_period")
        if self.repo.get(data.anno, data.mese) is not None:
            raise Conflict(
                ENTITY,
                f"il periodo {period_label(data.anno, data.mese)} è già chiuso",
                anno=data.anno,
                mese=data.mese,
            )
        lock = PeriodLock(
            anno=data.anno, mese=data.mese, chiuso_il=datetime.now(UTC), chiuso_da=actor.id
        )
        try:
            self.repo.add(lock)
            self.activities.record(
                ENTITY,
                PERIOD_LOCK_TIMELINE_ID,
                "closed",
                actor,
                {"anno": data.anno, "mese": data.mese},
            )
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check cannot cover two concurrent closes of the same month:
            # there the composite primary key is the only authority.
            self.session.rollback()
            raise Conflict(
                ENTITY,
                f"il periodo {period_label(data.anno, data.mese)} è già chiuso",
                anno=data.anno,
                mese=data.mese,
            ) from exc
        return PeriodLockRead.model_validate(lock)

    def reopen_period(self, anno: int, mese: int, actor: Actor) -> None:
        actor.require_admin("reopen_period")
        lock = self.repo.get(anno, mese)
        if lock is None:
            raise NotFound(ENTITY, f"{anno}-{mese:02d}")
        self.repo.delete(lock)
        self.activities.record(
            ENTITY, PERIOD_LOCK_TIMELINE_ID, "reopened", actor, {"anno": anno, "mese": mese}
        )
        self.session.commit()

    def is_closed(self, giorno: date) -> PeriodLockRead | None:
        lock = self.repo.get(giorno.year, giorno.month)
        return PeriodLockRead.model_validate(lock) if lock is not None else None

    def assert_writable(self, entity: str, field: str, *giorni: date | None) -> None:
        """Refuses if **any** of the supplied days falls in a closed month.

        Variadic because an update has to pass both the stored date and the new one:
        moving a row *out* of a closed month is still a write into it, and checking
        only the destination would let somebody empty a reported month one row at a
        time. `None` days are skipped -- an update that does not touch `data` supplies
        `None`, meaning "unchanged", not "the epoch".

        Takes `entity` and `field` rather than hard-coding them so the `Conflict` names
        the caller's own table (`time_entry` or `cost`), which is what makes the
        problem document actionable on the right screen.
        """
        for giorno in giorni:
            if giorno is None:
                continue
            lock = self.repo.get(giorno.year, giorno.month)
            if lock is None:
                continue
            raise Conflict(
                entity,
                f"il periodo {period_label(lock.anno, lock.mese)} è chiuso: riaprilo per "
                "modificare voci datate in quel mese",
                field=field,
                anno=lock.anno,
                mese=lock.mese,
                chiuso_il=lock.chiuso_il.isoformat(),
                chiuso_da=str(lock.chiuso_da) if lock.chiuso_da else None,
            )

    def list_locks(self, *, anno: int | None = None) -> list[PeriodLockRead]:
        return [PeriodLockRead.model_validate(lock) for lock in self.repo.list(anno=anno)]
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_period_locks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(timetracking): period locks refuse writes dated inside a reported month"
```

---

## Phase 4A-3 — The two write services

### Task 4A-9: `TimeEntryService` — write, freeze, guard, summarise

**Files:**
- Create: `packages/core/src/pigrocrm/core/timetracking/repository.py`
- Create: `packages/core/src/pigrocrm/core/timetracking/service.py`
- Test: `packages/core/tests/test_time_entries.py`
- Test: `packages/core/tests/test_rate_freezing.py` (the slice's central guarantee — its own file so it can be pointed at)

**Interfaces:**
- Consumes: `RateResolver.resolve(...) -> ResolvedRates` and `.describe(...) -> RateDescription` (4A-7); `PeriodLockService.assert_writable(entity, field, *giorni)` (4A-8); `money.{line_value, sum_hours, sum_money}` (4A-4); `UserRepository.get_active(user_id) -> User` and `.get(user_id) -> User | None`; `DealRepository.get(deal_id)`; `PipelineService.get(stage_id) -> PipelineStageRead`; `FieldDefinitionService.specs_for(entity_type)`; `fields.validator.validate_custom_fields(entity, specs, values)`; `ActivityService.record`.
- Produces:
  ```python
  ENTITY = "time_entry"

  class TimeEntryRepository:
      def __init__(self, session: Session) -> None
      def get(self, entry_id: UUID, *, include_deleted: bool = False) -> TimeEntry | None
      def add(self, entry: TimeEntry) -> TimeEntry
      def for_deal(self, deal_id: UUID) -> list[TimeEntry]
      def in_range(self, deal_id: UUID, da: date, a: date) -> list[TimeEntry]
      def for_month(self, deal_id: UUID, anno: int, mese: int) -> list[TimeEntry]
      def list(self, query: TimeEntryListQuery) -> list[TimeEntry]      # LAST

  class TimeEntryService:
      def __init__(self, session: Session) -> None
      def create(self, data: TimeEntryCreate, actor: Actor) -> TimeEntryRead
      def update(self, entry_id: UUID, data: TimeEntryUpdate, actor: Actor) -> TimeEntryRead
      def soft_delete(self, entry_id: UUID, actor: Actor) -> None
      def restore(self, entry_id: UUID, actor: Actor) -> TimeEntryRead
      def get(self, entry_id: UUID, actor: Actor) -> TimeEntryRead
      def describe_rates(self, deal_id: UUID, user_id: UUID, actor: Actor) -> RateDescription
      def deal_summary(self, deal_id: UUID, actor: Actor) -> DealTimeSummary
      def recalculate_rates(self, deal_id: UUID, data: RecalculateRatesRequest, actor: Actor) -> int   # Task 4A-11
      def update_user_rates(self, user_id: UUID, data: UserRatesUpdate, actor: Actor) -> None
      def update_deal_rate(self, deal_id: UUID, data: DealRateUpdate, actor: Actor) -> None
      def list(self, query: TimeEntryListQuery, actor: Actor) -> TimeEntryPage                        # LAST
  ```
  Module-level helper other tasks import: `def to_read(entry: TimeEntry) -> TimeEntryRead` — builds a `TimeEntryRead` with `valore_riga`/`costo_riga` already computed. Task 4A-14 (the report) and Task 4B-4 (the P&L) both use it, and nothing else may recompute those two fields.
  Frozen-field helper 4B narrows: `def billed_entry_ids(session: Session, entries: Sequence[TimeEntry]) -> set[UUID]` — in 4A, every entry with `invoice_line_id IS NOT NULL`; **Task 4B-3 replaces the body** with "linked to a line of an *issued* invoice" and changes no call site.

- [ ] **Step 1: Write the failing behaviour test**

```python
# packages/core/tests/test_time_entries.py
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.auth.models import User
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.errors import (
    Conflict,
    ImmutableField,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.schemas import (
    PeriodLockCreate,
    TimeEntryCreate,
    TimeEntryListQuery,
    TimeEntryUpdate,
)
from pigrocrm.core.timetracking.service import TimeEntryService

WRITER = Actor(id=None, type="user", role="collaboratore")
READER = Actor(id=None, type="user", role="readonly")


def _create(service, deal_id, user_id, **overrides):
    payload = {
        "deal_id": deal_id,
        "user_id": user_id,
        "data": date(2026, 3, 10),
        "ore": Decimal("3.00"),
        "descrizione": "Sviluppo",
    }
    payload.update(overrides)
    return service.create(TimeEntryCreate(**payload), WRITER)


def test_a_created_entry_carries_its_frozen_rate_and_its_row_value(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    db_session.get(Deal, seeded_deal_id).tariffa_oraria = Decimal("80.000000")
    db_session.flush()
    entry = _create(TimeEntryService(db_session), seeded_deal_id, seeded_user_id)
    assert entry.tariffa_applicata == Decimal("80.000000")
    assert entry.tariffa_origine == "deal"
    # Returned already computed: the browser does no economic arithmetic (§6).
    assert entry.valore_riga == Decimal("240.00")
    assert entry.costo_riga is None
    assert entry.costo_origine == "assente"


def test_a_multi_line_description_keeps_its_newlines_unescaped(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """Two of the previous system's defects at once. `normalizeSingleLine` kept only the first line
    (`String(value).split(/\\r?\\n/)[0]`), silently dropping the rest; and it applied
    `escapeTypstText` at *write* time, so the stored value was already escaped for one
    target and reached the XLSX escaped and the PDF double-escaped. Here the value is
    stored raw and `escape_for` prepares it at render, once, for the context it lands
    in."""
    hostile = 'Call con @mario su [fase 1] & #2 — "urgente"\nseconda riga\\backslash'
    entry = _create(
        TimeEntryService(db_session), seeded_deal_id, seeded_user_id, descrizione=hostile
    )
    assert entry.descrizione == hostile
    stored = db_session.execute(
        text("SELECT descrizione FROM time_entries WHERE id = :id"), {"id": entry.id}
    ).scalar_one()
    assert stored == hostile


def test_a_future_date_is_refused_but_back_dating_is_not(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """§6.3. Back-dating with **no year floor**, unlike slice 3's `data_emissione`: here
    you declare when work was done, and a consultant logs Monday on Friday and closes
    December at the end of January. A future hour is not data, it is a forecast, and
    this slice makes no forecasts."""
    service = TimeEntryService(db_session)
    _create(service, seeded_deal_id, seeded_user_id, data=date(2019, 7, 1))
    with pytest.raises(ValidationFailed) as excinfo:
        _create(service, seeded_deal_id, seeded_user_id, data=date.today() + timedelta(days=1))
    assert excinfo.value.details["field"] == "data"


def test_a_write_into_a_closed_period_is_refused(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The lock, reached through the service rather than only through
    `assert_writable` -- criterion 2's second half."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    service = TimeEntryService(db_session)
    with pytest.raises(Conflict) as excinfo:
        _create(service, seeded_deal_id, seeded_user_id, data=date(2026, 3, 10))
    assert excinfo.value.details["mese"] == 3
    assert "marzo 2026" in excinfo.value.message

    # An entry already in an open month cannot be moved into the closed one, nor
    # deleted out of it.
    entry = _create(service, seeded_deal_id, seeded_user_id, data=date(2026, 4, 10))
    with pytest.raises(Conflict):
        service.update(entry.id, TimeEntryUpdate(data=date(2026, 3, 20)), WRITER)
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=4), admin)
    with pytest.raises(Conflict):
        service.soft_delete(entry.id, WRITER)


def test_a_deactivated_user_cannot_receive_new_hours_but_keeps_the_old_ones(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """Residual R3, answered concretely (criterion 8). `get_active` on write, plain
    `get` on read: the money really was spent, so the hours stay in the P&L, in the
    aggregates and in the PDF with their owner's name."""
    service = TimeEntryService(db_session)
    existing = _create(service, seeded_deal_id, seeded_user_id, ore=Decimal("12.00"))
    db_session.get(User, seeded_user_id).attivo = False
    db_session.flush()

    with pytest.raises(ValidationFailed) as excinfo:
        _create(service, seeded_deal_id, seeded_user_id)
    assert excinfo.value.details["field"] == "user_id"

    other = User(email=f"altro-{uuid4()}@example.test", password_hash="x", nome="Altro")
    db_session.add(other)
    db_session.flush()
    fresh = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=other.id, data=date(2026, 3, 11),
            ore=Decimal("1.00"), descrizione="x",
        ),
        WRITER,
    )
    with pytest.raises(ValidationFailed):
        service.update(fresh.id, TimeEntryUpdate(user_id=seeded_user_id), WRITER)

    # And the read path still resolves it.
    assert service.get(existing.id, READER).ore == Decimal("12.00")
    assert service.deal_summary(seeded_deal_id, READER).ore_totali == Decimal("13.00")


def test_logging_on_a_closed_deal_is_allowed_and_leaves_a_trace(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, seeded_won_stage_id: UUID
) -> None:
    """§4.3's last paragraph. On a won deal the work *begins* at that moment, and on a
    lost one the pre-sales hours are a real cost. Refusing would force reopening the
    deal to tell the truth -- corrupting the pipeline to save the actuals. The service
    warns and records; it does not refuse."""
    db_session.get(Deal, seeded_deal_id).pipeline_stage_id = seeded_won_stage_id
    db_session.flush()
    entry = _create(TimeEntryService(db_session), seeded_deal_id, seeded_user_id)
    kinds = [e.kind for e in ActivityService(db_session).timeline("time_entry", entry.id)]
    assert "time_logged_on_closed_deal" in kinds


def test_an_entry_bound_to_an_invoice_line_freezes_the_named_fields(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """§4.3's table. `note_interne` and `custom_fields` stay mutable because they appear
    on no artefact; `descrizione` is frozen and that is not obvious -- it is the column
    the client reads in the timesheet attached to the invoice, so changing it after
    issue would make the delivered document and the database say two different things."""
    service = TimeEntryService(db_session)
    entry = _create(service, seeded_deal_id, seeded_user_id)
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": uuid4(), "id": entry.id},
    )
    db_session.flush()

    for field, value in [
        ("ore", Decimal("4.00")),
        ("data", date(2026, 3, 12)),
        ("tariffa_applicata", Decimal("90.000000")),
        ("costo_applicato", Decimal("10.000000")),
        ("descrizione", "Altro"),
        ("deal_id", seeded_deal_id),
        ("fatturabile", False),
    ]:
        with pytest.raises(ImmutableField) as excinfo:
            service.update(entry.id, TimeEntryUpdate(**{field: value}), WRITER)
        assert excinfo.value.details["field"] == field

    updated = service.update(
        entry.id, TimeEntryUpdate(note_interne="da ricontrollare"), WRITER
    )
    assert updated.note_interne == "da ricontrollare"

    with pytest.raises(Conflict):
        service.soft_delete(entry.id, WRITER)


def test_the_summary_states_the_three_facts_a_report_needs(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    _create(service, seeded_deal_id, seeded_user_id, ore=Decimal("2.00"),
            tariffa_applicata=Decimal("100.000000"), costo_applicato=Decimal("30.000000"))
    _create(service, seeded_deal_id, seeded_user_id, ore=Decimal("1.50"))  # no rate at all
    _create(service, seeded_deal_id, seeded_user_id, ore=Decimal("1.00"), fatturabile=False,
            tariffa_applicata=Decimal("100.000000"), costo_applicato=Decimal("30.000000"))

    summary = service.deal_summary(seeded_deal_id, READER)
    assert summary.ore_totali == Decimal("4.50")
    assert summary.ore_fatturabili_non_fatturate == Decimal("3.50")
    # Only the priced, billable, unbilled hours contribute the accrued value; the
    # unpriced 1.50 h is counted separately and never valued at zero.
    assert summary.valore_ore_non_fatturate == Decimal("200.00")
    assert summary.ore_senza_tariffa == 1
    # Labour cost includes the NON-billable hour: an internal meeting costs exactly
    # what it would cost if it were billed, and excluding it would make the deal that
    # demanded more of them look more profitable (§7.1).
    assert summary.costo_lavoro == Decimal("90.00")
    assert summary.stato == "in corso"


def test_the_state_is_derived_never_stored(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, seeded_won_stage_id: UUID
) -> None:
    """§7.3's three states, and they come from the data -- a stage type plus whether
    billable unbilled hours exist -- never from a column."""
    service = TimeEntryService(db_session)
    _create(service, seeded_deal_id, seeded_user_id, tariffa_applicata=Decimal("100.000000"))
    assert service.deal_summary(seeded_deal_id, READER).stato == "in corso"

    db_session.get(Deal, seeded_deal_id).pipeline_stage_id = seeded_won_stage_id
    db_session.flush()
    assert service.deal_summary(seeded_deal_id, READER).stato == "da fatturare"

    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE deal_id = :deal"),
        {"line": uuid4(), "deal": seeded_deal_id},
    )
    db_session.flush()
    assert service.deal_summary(seeded_deal_id, READER).stato == "chiuso"


def test_soft_delete_is_reversible_and_a_reader_cannot_write(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    entry = _create(service, seeded_deal_id, seeded_user_id)
    service.soft_delete(entry.id, WRITER)
    assert service.list(TimeEntryListQuery(deal_id=seeded_deal_id), READER).items == []
    restored = service.restore(entry.id, WRITER)
    assert restored.deleted_at is None
    with pytest.raises(PermissionDenied):
        service.soft_delete(entry.id, READER)


def test_a_dangling_foreign_key_is_not_found_not_an_integrity_error(
    db_session: Session, seeded_user_id: UUID
) -> None:
    with pytest.raises(NotFound):
        TimeEntryService(db_session).create(
            TimeEntryCreate(
                deal_id=uuid4(), user_id=seeded_user_id, data=date(2026, 3, 1),
                ore=Decimal("1.00"), descrizione="x",
            ),
            WRITER,
        )


def test_the_list_is_ordered_by_date_descending(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """Residual R9 is open in general; a list of hours with no ordering is unusable, so
    these two tables are born ordered."""
    service = TimeEntryService(db_session)
    for day in (5, 20, 12):
        _create(service, seeded_deal_id, seeded_user_id, data=date(2026, 3, day))
    page = service.list(TimeEntryListQuery(deal_id=seeded_deal_id), READER)
    assert [e.data.day for e in page.items] == [20, 12, 5]


def test_the_fatturato_filter_answers_how_much_is_left_to_invoice(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    billed = _create(service, seeded_deal_id, seeded_user_id)
    _create(service, seeded_deal_id, seeded_user_id, data=date(2026, 3, 11))
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": uuid4(), "id": billed.id},
    )
    db_session.flush()
    unbilled = service.list(
        TimeEntryListQuery(deal_id=seeded_deal_id, fatturato=False), READER
    )
    assert [e.id for e in unbilled.items] == [
        e.id for e in unbilled.items if e.invoice_line_id is None
    ]
    assert len(unbilled.items) == 1
```

- [ ] **Step 2: Write the failing central-guarantee test**

```python
# packages/core/tests/test_rate_freezing.py
"""**The slice's central guarantee.** What happens to last quarter's margin when you
raise a rate today? Nothing -- and not out of discipline, by construction, because no
report reads a rate column.

Criterion 2's first half, at the service level. The API-level repeat, comparing whole
JSON responses before and after, is Task 4B-4's; this one proves the property where it
actually lives, so a failure here names the cause instead of a diff.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.money import sum_money
from pigrocrm.core.timetracking.schemas import TimeEntryCreate, TimeEntryListQuery
from pigrocrm.core.timetracking.service import TimeEntryService

WRITER = Actor(id=None, type="user", role="collaboratore")
READER = Actor(id=None, type="user", role="readonly")


def test_raising_a_rate_today_does_not_move_an_old_period(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    user = db_session.get(User, seeded_user_id)
    user.tariffa_oraria_default = Decimal("80.000000")
    db_session.flush()
    service = TimeEntryService(db_session)

    # 40 hours at 80.000000 EUR/h across March, exactly criterion 2's setup.
    for day in range(1, 6):
        service.create(
            TimeEntryCreate(
                deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, day),
                ore=Decimal("8.00"), descrizione=f"Giorno {day}",
            ),
            WRITER,
        )
    before = service.list(TimeEntryListQuery(deal_id=seeded_deal_id), READER)
    baseline_total = sum_money([e.valore_riga for e in before.items])
    assert baseline_total == Decimal("3200.00")
    baseline = [e.model_dump(mode="json") for e in before.items]

    # Now raise both levels, as high as criterion 2 asks.
    user.tariffa_oraria_default = Decimal("120.000000")
    db_session.get(Deal, seeded_deal_id).tariffa_oraria = Decimal("150.000000")
    db_session.flush()

    after = service.list(TimeEntryListQuery(deal_id=seeded_deal_id), READER)
    # Compared as structure, not by eye: every field of every row, including the
    # derived `valore_riga`, must be byte-identical.
    assert [e.model_dump(mode="json") for e in after.items] == baseline
    assert sum_money([e.valore_riga for e in after.items]) == baseline_total

    # And only a NEW hour picks up the new rate -- proving the old rows did not move
    # because nothing was read, not because nothing changed.
    fresh = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 4, 1),
            ore=Decimal("1.00"), descrizione="Aprile",
        ),
        WRITER,
    )
    assert fresh.tariffa_applicata == Decimal("150.000000")
    assert fresh.tariffa_origine == "deal"


def test_clearing_a_rate_column_altogether_leaves_written_rows_intact(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The harder direction: setting the source back to NULL. A report that re-read the
    column would turn a priced hour into an unpriced one."""
    db_session.get(Deal, seeded_deal_id).tariffa_oraria = Decimal("80.000000")
    db_session.flush()
    service = TimeEntryService(db_session)
    entry = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 1),
            ore=Decimal("2.00"), descrizione="x",
        ),
        WRITER,
    )
    db_session.get(Deal, seeded_deal_id).tariffa_oraria = None
    db_session.flush()

    reread = service.get(entry.id, READER)
    assert reread.tariffa_applicata == Decimal("80.000000")
    assert reread.valore_riga == Decimal("160.00")
    assert service.deal_summary(seeded_deal_id, READER).ore_senza_tariffa == 0
```

- [ ] **Step 3: Run both and watch them fail**

Run: `uv run pytest packages/core/tests/test_time_entries.py packages/core/tests/test_rate_freezing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.timetracking.service'`.

- [ ] **Step 4: Write the repository**

```python
# packages/core/src/pigrocrm/core/timetracking/repository.py
import calendar
from datetime import date
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from pigrocrm.core.timetracking.models import Cost, TimeEntry
from pigrocrm.core.timetracking.schemas import CostListQuery, TimeEntryListQuery


def month_bounds(anno: int, mese: int) -> tuple[date, date]:
    """First and last calendar day of a month, inclusive. Used by the report and by
    every monthly aggregate, so the boundary arithmetic exists once: `calendar.
    monthrange` rather than `date(anno, mese + 1, 1) - timedelta(days=1)`, which
    raises for December."""
    return date(anno, mese, 1), date(anno, mese, calendar.monthrange(anno, mese)[1])


class TimeEntryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entry_id: UUID, *, include_deleted: bool = False) -> TimeEntry | None:
        entry = self.session.get(TimeEntry, entry_id)
        if entry is None:
            return None
        if entry.deleted_at is not None and not include_deleted:
            return None
        return entry

    def add(self, entry: TimeEntry) -> TimeEntry:
        self.session.add(entry)
        self.session.flush()
        return entry

    def _live_for_deal(self, deal_id: UUID) -> Select[tuple[TimeEntry]]:
        return select(TimeEntry).where(
            TimeEntry.deal_id == deal_id, TimeEntry.deleted_at.is_(None)
        )

    def for_deal(self, deal_id: UUID) -> list[TimeEntry]:
        return list(self.session.execute(self._live_for_deal(deal_id)).scalars())

    def in_range(self, deal_id: UUID, da: date, a: date) -> list[TimeEntry]:
        return list(
            self.session.execute(
                self._live_for_deal(deal_id)
                .where(TimeEntry.data >= da, TimeEntry.data <= a)
                .order_by(TimeEntry.data, TimeEntry.created_at)
            ).scalars()
        )

    def for_month(self, deal_id: UUID, anno: int, mese: int) -> list[TimeEntry]:
        da, a = month_bounds(anno, mese)
        return self.in_range(deal_id, da, a)

    # `list` stays the last method in this class -- the unconditional project rule.
    def list(self, query: TimeEntryListQuery) -> list[TimeEntry]:
        """Keyset pagination on `(data DESC, id DESC)`.

        Ordered by date descending because a list of hours in insertion order is
        unusable (residual R9 names the general gap; these tables are simply born
        ordered). `id` breaks the tie deterministically -- UUIDv7 is time-ordered, so
        it is also chronological within a day. One row over `limit` is fetched so the
        service can tell "there is more" from "that was everything" without a second
        count query.
        """
        stmt = select(TimeEntry).where(TimeEntry.deleted_at.is_(None))
        if query.deal_id is not None:
            stmt = stmt.where(TimeEntry.deal_id == query.deal_id)
        if query.user_id is not None:
            stmt = stmt.where(TimeEntry.user_id == query.user_id)
        if query.da is not None:
            stmt = stmt.where(TimeEntry.data >= query.da)
        if query.a is not None:
            stmt = stmt.where(TimeEntry.data <= query.a)
        if query.fatturabile is not None:
            stmt = stmt.where(TimeEntry.fatturabile.is_(query.fatturabile))
        if query.fatturato is not None:
            stmt = stmt.where(
                TimeEntry.invoice_line_id.isnot(None)
                if query.fatturato
                else TimeEntry.invoice_line_id.is_(None)
            )
        if query.custom:
            # JSONB containment, served by ix_time_entries_custom_fields (GIN), so a
            # custom-field filter never degrades into a sequential scan.
            stmt = stmt.where(TimeEntry.custom_fields.contains(query.custom))
        if query.cursor is not None:
            anchor = self.session.get(TimeEntry, query.cursor)
            if anchor is not None:
                stmt = stmt.where(
                    (TimeEntry.data < anchor.data)
                    | ((TimeEntry.data == anchor.data) & (TimeEntry.id < anchor.id))
                )
        return list(
            self.session.execute(
                stmt.order_by(TimeEntry.data.desc(), TimeEntry.id.desc()).limit(query.limit + 1)
            ).scalars()
        )


class CostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, cost_id: UUID, *, include_deleted: bool = False) -> Cost | None:
        cost = self.session.get(Cost, cost_id)
        if cost is None:
            return None
        if cost.deleted_at is not None and not include_deleted:
            return None
        return cost

    def add(self, cost: Cost) -> Cost:
        self.session.add(cost)
        self.session.flush()
        return cost

    def for_deal(self, deal_id: UUID) -> list[Cost]:
        return list(
            self.session.execute(
                select(Cost).where(Cost.deal_id == deal_id, Cost.deleted_at.is_(None))
            ).scalars()
        )

    # `list` stays the last method in this class.
    def list(self, query: CostListQuery) -> list[Cost]:
        stmt = select(Cost).where(Cost.deleted_at.is_(None))
        if query.solo_generali:
            # `deal_id IS NULL` is a general expense (§7.4). A separate flag is needed
            # because `deal_id=None` on the query already means "do not filter".
            stmt = stmt.where(Cost.deal_id.is_(None))
        elif query.deal_id is not None:
            stmt = stmt.where(Cost.deal_id == query.deal_id)
        if query.category_id is not None:
            stmt = stmt.where(Cost.category_id == query.category_id)
        if query.da is not None:
            stmt = stmt.where(Cost.data >= query.da)
        if query.a is not None:
            stmt = stmt.where(Cost.data <= query.a)
        if query.custom:
            stmt = stmt.where(Cost.custom_fields.contains(query.custom))
        if query.cursor is not None:
            anchor = self.session.get(Cost, query.cursor)
            if anchor is not None:
                stmt = stmt.where(
                    (Cost.data < anchor.data)
                    | ((Cost.data == anchor.data) & (Cost.id < anchor.id))
                )
        return list(
            self.session.execute(
                stmt.order_by(Cost.data.desc(), Cost.id.desc()).limit(query.limit + 1)
            ).scalars()
        )
```

- [ ] **Step 5: Write the service**

```python
# packages/core/src/pigrocrm/core/timetracking/service.py
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.errors import (
    Conflict,
    ImmutableField,
    NotFound,
    ValidationFailed,
)
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.money import line_value, sum_hours, sum_money
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.models import TimeEntry
from pigrocrm.core.timetracking.rates import RateResolver
from pigrocrm.core.timetracking.repository import TimeEntryRepository
from pigrocrm.core.timetracking.schemas import (
    DealTimeSummary,
    DealRateUpdate,
    RateDescription,
    RecalculateRatesRequest,
    TimeEntryCreate,
    TimeEntryListQuery,
    TimeEntryPage,
    TimeEntryRead,
    TimeEntryUpdate,
    UserRatesUpdate,
)

ENTITY = "time_entry"

# §4.3's table, as data. Frozen once the entry belongs to a fiscal document;
# `note_interne` and `custom_fields` stay mutable because they appear on no artefact.
# `descrizione` is in this tuple and it is not obvious: it is the column the client
# reads in the timesheet attached to the invoice, so changing it after issue would
# make the delivered document and the database say two different things.
FROZEN_WHEN_BILLED: tuple[str, ...] = (
    "ore",
    "data",
    "tariffa_applicata",
    "costo_applicato",
    "descrizione",
    "deal_id",
    "fatturabile",
)


def to_read(entry: TimeEntry) -> TimeEntryRead:
    """The only place `valore_riga` and `costo_riga` are computed.

    Returned already summed because §6 forbids the browser from doing any economic
    arithmetic: every figure the UI shows arrives finished. Task 4A-14 (the report) and
    Task 4B-4 (the P&L) both call this rather than repeating the multiplication --
    The previous system's P&L recomputed its own totals in the browser and that is exactly how the
    printed column and the total came to disagree.
    """
    read = TimeEntryRead.model_validate(entry)
    read = read.model_copy(
        update={
            "valore_riga": line_value(entry.ore, entry.tariffa_applicata),
            "costo_riga": line_value(entry.ore, entry.costo_applicato),
        }
    )
    return read


def billed_entry_ids(session: Session, entries: Sequence[TimeEntry]) -> set[UUID]:
    """Which of `entries` belong to a fiscal document and are therefore frozen.

    **Slice 4A definition:** any entry with a non-null `invoice_line_id`. That is a
    deliberate *superset* of §4.3's real rule ("a line of an **issued** invoice"),
    and it is exactly right for 4A: `invoice_lines` does not exist yet, nothing in 4A
    writes the column, so the "bound" state is unreachable and the superset is
    unobservable.

    **Task 4B-3 replaces this body** with the real rule -- join `invoice_lines` to
    `invoices` and keep only `stato = 'emessa'` -- and changes not one call site. That
    is why this is one function and not an inline `is not None` in three places: the
    narrowing has to happen once.
    """
    return {entry.id for entry in entries if entry.invoice_line_id is not None}


class TimeEntryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = TimeEntryRepository(session)
        self.deals = DealRepository(session)
        self.users = UserRepository(session)
        self.pipeline = PipelineService(session)
        self.rates = RateResolver(session)
        self.locks = PeriodLockService(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    # ---- validation helpers ------------------------------------------------

    def _require_deal(self, deal_id: UUID):
        deal = self.deals.get(deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)
        return deal

    def _require_active_user(self, user_id: UUID) -> None:
        """`get_active`, which raises this project's own `DomainError` for a
        deactivated user, translated here into a `ValidationFailed` that names the
        field -- so the problem document highlights the user picker instead of reading
        as a generic 400. Residual R3's answer for this slice: an existing assignment
        survives, a new one is refused."""
        if self.users.get(user_id) is None:
            raise NotFound("user", user_id)
        try:
            self.users.get_active(user_id)
        except NotFound:
            raise
        except Exception as exc:  # UserRepository.get_active raises a DomainError
            raise ValidationFailed(
                ENTITY,
                "user_id",
                "l'utente non è attivo",
                expected="un utente attivo",
            ) from exc

    def _check_not_future(self, giorno: date) -> None:
        """A future hour is not data, it is a forecast, and this slice makes no
        forecasts (§13). Back-dating has no floor at all, unlike slice 3's
        `data_emissione`: there you write into a progressive fiscal register, where
        inserting into a closed year is wrong regardless; here you declare when work
        was done, and forbidding it would produce hours dated the day somebody
        remembered to write them -- an archive that lies about its only temporal
        field."""
        if giorno > date.today():
            raise ValidationFailed(
                ENTITY, "data", "data futura", expected="una data non successiva a oggi"
            )

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def _update_custom_fields(self, entry: TimeEntry, provided: dict[str, Any]) -> dict[str, Any]:
        """Copies `DealService._update_custom_fields`'s contract exactly -- see that
        method's docstring for the full reasoning. Validates only the keys the caller
        touches, against active definitions, never the union with what is stored; a
        supplied `None` removes the entry unless its definition is active and
        required."""
        active_by_key = {spec.key: spec for spec in self.fields.specs_for(ENTITY)}
        to_remove: set[str] = set()
        for key, value in provided.items():
            if value is not None:
                continue
            spec = active_by_key.get(key)
            if spec is not None and spec.required:
                raise ValidationFailed(
                    ENTITY, key, "campo obbligatorio", expected="un valore non vuoto"
                )
            to_remove.add(key)
        to_set = {k: v for k, v in provided.items() if v is not None}
        touched = [spec for spec in active_by_key.values() if spec.key in to_set]
        validated = validate_custom_fields(ENTITY, touched, to_set)
        merged = {k: v for k, v in entry.custom_fields.items() if k not in to_remove}
        merged.update(validated)
        return merged

    def _require(self, entry_id: UUID, *, include_deleted: bool = False) -> TimeEntry:
        entry = self.repo.get(entry_id, include_deleted=include_deleted)
        if entry is None:
            raise NotFound(ENTITY, entry_id)
        return entry

    # ---- writes -----------------------------------------------------------

    def create(self, data: TimeEntryCreate, actor: Actor) -> TimeEntryRead:
        actor.require_write("log_time")
        deal = self._require_deal(data.deal_id)
        self._require_active_user(data.user_id)
        self._check_not_future(data.data)
        self.locks.assert_writable(ENTITY, "data", data.data)

        resolved = self.rates.resolve(
            deal_id=data.deal_id,
            user_id=data.user_id,
            tariffa_esplicita=data.tariffa_applicata,
            costo_esplicito=data.costo_applicato,
        )
        entry = self.repo.add(
            TimeEntry(
                deal_id=data.deal_id,
                user_id=data.user_id,
                data=data.data,
                ore=data.ore,
                # Stored raw: multi-line, unescaped, exactly as typed. `escape_for`
                # prepares it at render, once, for the context it lands in. The previous system
                # escaped at write time and the value then reached the XLSX escaped and
                # the PDF double-escaped.
                descrizione=data.descrizione,
                fatturabile=data.fatturabile,
                tariffa_applicata=resolved.tariffa,
                costo_applicato=resolved.costo,
                tariffa_origine=resolved.tariffa_origine,
                costo_origine=resolved.costo_origine,
                note_interne=data.note_interne,
                custom_fields=self._validated_custom(data.custom_fields or {}),
            )
        )
        self.activities.record(
            ENTITY,
            entry.id,
            "created",
            actor,
            {
                "deal_id": str(entry.deal_id),
                "ore": str(entry.ore),
                "tariffa_applicata": str(entry.tariffa_applicata),
                "tariffa_origine": entry.tariffa_origine,
            },
        )
        stage = self.pipeline.get(deal.pipeline_stage_id)
        if stage.tipo != "open":
            # Closing a deal blocks nothing (§4.3). On a won deal the work *begins* at
            # that moment; on a lost one the pre-sales hours are a real cost. Refusing
            # would force reopening the deal to tell the truth -- corrupting the
            # pipeline to save the actuals. The UI warns, this records, neither refuses.
            self.activities.record(
                ENTITY, entry.id, "time_logged_on_closed_deal", actor, {"stage": stage.nome}
            )
        self.session.commit()
        return to_read(entry)

    def update(self, entry_id: UUID, data: TimeEntryUpdate, actor: Actor) -> TimeEntryRead:
        actor.require_write("update_time_entry")
        entry = self._require(entry_id)
        changes = data.model_dump(exclude_none=True, exclude={"custom_fields"})

        if billed_entry_ids(self.session, [entry]):
            for field in FROZEN_WHEN_BILLED:
                if field in changes:
                    raise ImmutableField(
                        ENTITY,
                        field,
                        "la voce appartiene a una fattura emessa e non è più un dato di CRM",
                    )

        if "deal_id" in changes:
            self._require_deal(changes["deal_id"])
        if "user_id" in changes:
            self._require_active_user(changes["user_id"])
        if "data" in changes:
            self._check_not_future(changes["data"])
        # Both the stored date and the new one: moving a row out of a closed month is
        # still a write into it, and checking only the destination would let somebody
        # empty a reported month one row at a time.
        self.locks.assert_writable(ENTITY, "data", entry.data, changes.get("data"))

        # A rate supplied on an update is an explicit override and is re-frozen with
        # `origine = "manuale"`; a rate NOT supplied is never re-resolved, because
        # re-resolving would be exactly the "a report re-reads a rate column" failure
        # §5 exists to prevent, wearing an update's clothes.
        if "tariffa_applicata" in changes:
            changes["tariffa_origine"] = "manuale"
        if "costo_applicato" in changes:
            changes["costo_origine"] = "manuale"

        if data.custom_fields is not None:
            changes["custom_fields"] = self._update_custom_fields(entry, data.custom_fields)
        for key, value in changes.items():
            setattr(entry, key, value)

        self.activities.record(ENTITY, entry.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return to_read(entry)

    def soft_delete(self, entry_id: UUID, actor: Actor) -> None:
        """Reversible, like everything else in this product. The previous system's only way to void a
        wrong entry was a physical `DELETE` that rewrote the whole archive file;
        `ore > 0` stays the rule and the correction has a path that is not destructive
        (§2.2, last row)."""
        actor.require_write("delete_time_entry")
        entry = self._require(entry_id)
        if billed_entry_ids(self.session, [entry]):
            raise Conflict(
                ENTITY,
                "la voce è legata a una riga di fattura: scollegala prima di cancellarla",
                invoice_line_id=str(entry.invoice_line_id),
            )
        self.locks.assert_writable(ENTITY, "data", entry.data)
        entry.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, entry.id, "deleted", actor)
        self.session.commit()

    def restore(self, entry_id: UUID, actor: Actor) -> TimeEntryRead:
        actor.require_write("restore_time_entry")
        entry = self._require(entry_id, include_deleted=True)
        self.locks.assert_writable(ENTITY, "data", entry.data)
        was_deleted = entry.deleted_at is not None
        entry.deleted_at = None
        if was_deleted:
            # Recorded only when it really was deleted: logging "restored" for an entry
            # that was never archived would claim a recovery that never happened --
            # the same guard `DealService.restore` already carries.
            self.activities.record(ENTITY, entry.id, "restored", actor)
        self.session.commit()
        return to_read(entry)

    def update_user_rates(self, user_id: UUID, data: UserRatesUpdate, actor: Actor) -> None:
        """On `TimeEntryService` and not on a service of its own, deliberately -- see
        "Contradictions" item 4: §11 fixes the audited surface to three classes and the
        exclusion list to ten literal names, two of which are this and
        `update_deal_rate`. A separate `RateService` would put two excluded names
        outside the audited set, which is the "the ban degrades into an oversight"
        failure §11 exists to prevent.

        `admin`, not `collaboratore`: changing what an hour is worth is closer to
        configuration than to writing an entity (slice 1 §6.3). Writes an activity,
        because the timeline is what reconstructs when a rate changed -- and is the
        reason §5 can afford not to historicise it (§4.5).

        `exclude_unset`, not `exclude_none`: clearing a rate back to `NULL` has to be
        expressible, and here it is not a convenience -- an unclearable rate is a
        number nobody chose staying in force forever. This method is written this way
        from the start; Task 4B-1 converts the rest of the codebase (residual A14).
        """
        actor.require_admin("update_user_rates")
        user = self.users.get(user_id)
        if user is None:
            raise NotFound("user", user_id)
        changes = data.model_dump(exclude_unset=True)
        previous = {key: str(getattr(user, key)) for key in changes}
        for key, value in changes.items():
            setattr(user, key, value)
        self.activities.record(
            "user", user_id, "rates_updated", actor,
            {"prima": previous, "dopo": {k: str(v) for k, v in changes.items()}},
        )
        self.session.commit()

    def update_deal_rate(self, deal_id: UUID, data: DealRateUpdate, actor: Actor) -> None:
        actor.require_admin("update_deal_rate")
        deal = self._require_deal(deal_id)
        changes = data.model_dump(exclude_unset=True)
        previous = {key: str(getattr(deal, key)) for key in changes}
        for key, value in changes.items():
            setattr(deal, key, value)
        self.activities.record(
            "deal", deal_id, "rate_updated", actor,
            {"prima": previous, "dopo": {k: str(v) for k, v in changes.items()}},
        )
        self.session.commit()

    def recalculate_rates(
        self, deal_id: UUID, data: RecalculateRatesRequest, actor: Actor
    ) -> int:
        """Implemented in Task 4A-11. Declared here so the class's public surface is
        complete for the architecture test in Task 4A-13."""
        raise NotImplementedError

    # ---- reads ------------------------------------------------------------

    def get(self, entry_id: UUID, actor: Actor) -> TimeEntryRead:
        return to_read(self._require(entry_id))

    def describe_rates(self, deal_id: UUID, user_id: UUID, actor: Actor) -> RateDescription:
        """What a new entry would freeze right now. Reading before acting (slice 1
        §8.4), and the reason an agent never has to guess which of the three levels
        answers."""
        self._require_deal(deal_id)
        if self.users.get(user_id) is None:
            raise NotFound("user", user_id)
        return self.rates.describe(deal_id=deal_id, user_id=user_id)

    def deal_summary(self, deal_id: UUID, actor: Actor) -> DealTimeSummary:
        """The hours half of a deal's economics, readable with no invoices present.

        Deliberately carries no `ricavi` and no `valore_maturato`: revenue is the
        invoice (§3, decision 2) and there is no second notion of it. 4B's `DealPnl`
        adds `ricavi` and defines `valore_maturato = ricavi +
        valore_ore_non_fatturate` on top of this, instead of 4A shipping a zero that
        would read as a real figure.
        """
        deal = self._require_deal(deal_id)
        entries = self.repo.for_deal(deal_id)
        billed = billed_entry_ids(self.session, entries)
        unbilled_billable = [
            e for e in entries if e.fatturabile and e.id not in billed
        ]
        stage = self.pipeline.get(deal.pipeline_stage_id)
        if stage.tipo == "open":
            stato = "in corso"
        elif unbilled_billable:
            stato = "da fatturare"
        else:
            stato = "chiuso"
        return DealTimeSummary(
            deal_id=deal_id,
            stato=stato,
            ore_totali=sum_hours([e.ore for e in entries]),
            ore_fatturabili_non_fatturate=sum_hours([e.ore for e in unbilled_billable]),
            # Only priced hours contribute; an unpriced one is counted separately and
            # never valued at zero, which would say the work was free.
            valore_ore_non_fatturate=sum_money(
                [line_value(e.ore, e.tariffa_applicata) for e in unbilled_billable]
            ),
            # Includes the NON-billable hours: an internal meeting costs exactly what
            # it would cost if it were billed, and excluding it would make the deal
            # that demanded more of them look more profitable (§7.1).
            costo_lavoro=sum_money([line_value(e.ore, e.costo_applicato) for e in entries]),
            ore_senza_tariffa=sum(1 for e in entries if e.tariffa_applicata is None),
            voci=len(entries),
        )

    # `list` stays the last method in this class -- the unconditional project rule.
    def list(self, query: TimeEntryListQuery, actor: Actor) -> TimeEntryPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return TimeEntryPage(
            items=[to_read(entry) for entry in items],
            next_cursor=items[-1].id if has_more and items else None,
        )
```

- [ ] **Step 6: Run both tests**

Run: `uv run pytest packages/core/tests/test_time_entries.py packages/core/tests/test_rate_freezing.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/core
git commit -m "feat(timetracking): TimeEntryService freezes the rate onto the row it writes"
```

---

### Task 4A-10: `CostService` — real money out, with its receipt

**Files:**
- Create: `packages/core/src/pigrocrm/core/timetracking/costs.py`
- Test: `packages/core/tests/test_costs.py`

**Interfaces:**
- Consumes: `CostRepository` (4A-9); `CostCategoryService.require_active(category_id) -> CostCategory` (4A-6); `PeriodLockService.assert_writable` (4A-8); `DocumentRepository.get(document_id)`; `DealRepository.get`; `validate_custom_fields`; `ActivityService.record`.
- Produces:
  ```python
  ENTITY = "cost"

  class CostService:
      def __init__(self, session: Session) -> None
      def create(self, data: CostCreate, actor: Actor) -> CostRead
      def update(self, cost_id: UUID, data: CostUpdate, actor: Actor) -> CostRead
      def soft_delete(self, cost_id: UUID, actor: Actor) -> None
      def restore(self, cost_id: UUID, actor: Actor) -> CostRead
      def get(self, cost_id: UUID, actor: Actor) -> CostRead
      def list(self, query: CostListQuery, actor: Actor) -> CostPage      # LAST
  ```
  No `describe_*` and no rate anything: a cost has money and no quantity, which is the third of §4.2's three differences and the reason these are two tables.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_costs.py
"""A cost is money that actually left, towards somebody else, with a receipt to prove
it -- as distinct from an hour's cost, which is an internal, notional figure derived
from a rate you chose yourself (§4.2)."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.timetracking.categories import CostCategoryService
from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.schemas import (
    CostCreate,
    CostListQuery,
    CostUpdate,
    PeriodLockCreate,
)

WRITER = Actor(id=None, type="user", role="collaboratore")
READER = Actor(id=None, type="user", role="readonly")


def _create(service, category_id, **overrides):
    payload = {
        "category_id": category_id,
        "data": date(2026, 3, 5),
        "importo": Decimal("120.00"),
        "descrizione": "Licenza annuale",
    }
    payload.update(overrides)
    return service.create(CostCreate(**payload), WRITER)


def test_a_cost_with_no_deal_is_a_general_expense(
    db_session: Session, seeded_category_id: UUID, seeded_deal_id: UUID
) -> None:
    """§7.4. It enters the period P&L in a row of its own and is never apportioned onto
    any deal: any apportionment key would make a deal's margin move when a *different*
    deal was invoiced."""
    service = CostService(db_session)
    general = _create(service, seeded_category_id, deal_id=None)
    attributed = _create(service, seeded_category_id, deal_id=seeded_deal_id)
    assert general.deal_id is None

    only_general = service.list(CostListQuery(solo_generali=True), READER)
    assert [c.id for c in only_general.items] == [general.id]
    per_deal = service.list(CostListQuery(deal_id=seeded_deal_id), READER)
    assert [c.id for c in per_deal.items] == [attributed.id]


def test_a_negative_amount_is_a_refund_and_zero_is_refused(
    db_session: Session, seeded_category_id: UUID
) -> None:
    """§4.4, the same choice slice 3 §6.1 rule 6 makes for a discount: represent the
    correction with the instrument that already exists, instead of a `tipo` column that
    multiplies the cases in every sum."""
    service = CostService(db_session)
    assert _create(service, seeded_category_id, importo=Decimal("-45.50")).importo == Decimal(
        "-45.50"
    )
    with pytest.raises(ValidationFailed) as excinfo:
        _create(service, seeded_category_id, importo=Decimal("0.00"))
    assert excinfo.value.details["field"] == "importo"


def test_an_archived_category_cannot_be_chosen_for_a_new_cost(
    db_session: Session, seeded_category_id: UUID
) -> None:
    admin = Actor(id=None, type="system", role="admin")
    CostCategoryService(db_session).archive_cost_category(seeded_category_id, admin)
    with pytest.raises(ValidationFailed) as excinfo:
        _create(CostService(db_session), seeded_category_id)
    assert excinfo.value.details["field"] == "category_id"


def test_a_write_into_a_closed_period_is_refused_both_ways(
    db_session: Session, seeded_category_id: UUID, seeded_user_id: UUID
) -> None:
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = CostService(db_session)
    cost = _create(service, seeded_category_id, data=date(2026, 4, 5))
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=3), admin)

    with pytest.raises(Conflict):
        _create(service, seeded_category_id, data=date(2026, 3, 5))
    with pytest.raises(Conflict):
        service.update(cost.id, CostUpdate(data=date(2026, 3, 5)), WRITER)

    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=4), admin)
    with pytest.raises(Conflict):
        service.soft_delete(cost.id, WRITER)


def test_the_receipt_is_a_document_reference_not_bytes(
    db_session: Session, seeded_category_id: UUID
) -> None:
    """The previous system kept the attachment as base64 inside the costs JSON
    (`parseBase64Payload`). The document store already exists, with pluggable storage,
    versioning and a hash, and is not reinvented (§10.3). An id that resolves to
    nothing is `NotFound`, not a raw `ForeignKeyViolation`."""
    with pytest.raises(NotFound):
        _create(CostService(db_session), seeded_category_id, document_id=uuid4())


def test_soft_delete_is_reversible_and_a_reader_cannot_write(
    db_session: Session, seeded_category_id: UUID
) -> None:
    service = CostService(db_session)
    cost = _create(service, seeded_category_id)
    service.soft_delete(cost.id, WRITER)
    assert service.list(CostListQuery(), READER).items == []
    assert service.restore(cost.id, WRITER).deleted_at is None
    with pytest.raises(PermissionDenied):
        service.soft_delete(cost.id, READER)


def test_the_list_is_ordered_by_date_descending(
    db_session: Session, seeded_category_id: UUID
) -> None:
    service = CostService(db_session)
    for day in (5, 20, 12):
        _create(service, seeded_category_id, data=date(2026, 3, day))
    assert [c.data.day for c in service.list(CostListQuery(), READER).items] == [20, 12, 5]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_costs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.timetracking.costs'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/timetracking/costs.py
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.timetracking.categories import CostCategoryService
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.models import Cost
from pigrocrm.core.timetracking.repository import CostRepository
from pigrocrm.core.timetracking.schemas import (
    CostCreate,
    CostListQuery,
    CostPage,
    CostRead,
    CostUpdate,
)

ENTITY = "cost"


class CostService:
    """Real money out, with a receipt.

    Not a variant of `TimeEntryService`, and the three differences are the ones that
    matter (§4.2): a cost is money that actually left towards somebody else and has a
    document proving it, while an hour's cost is an internal notional figure derived
    from a rate you chose; an hour is also *potential revenue* and a cost never is; and
    an hour has a quantity comparable with an estimate while a cost has only money.

    The labour cost never produces a row here and is never counted twice: an external
    consultant who invoices you their hours is a `cost` in category "Consulenza
    esterna", and their hours -- if you record them at all -- carry
    `costo_applicato = NULL`. The two sets are disjoint by construction, and Task
    4B-4's test proves no path lets the same expense in from both sides (§7.2).
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CostRepository(session)
        self.deals = DealRepository(session)
        self.documents = DocumentRepository(session)
        self.categories = CostCategoryService(session)
        self.locks = PeriodLockService(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    def _check_importo(self, importo: Decimal) -> None:
        """Zero is refused because it is neither a cost nor a correction. Checked here
        as well as by `ck_costs_importo_non_zero`, not instead of it: this raises the
        project's own `ValidationFailed` naming the field, the CHECK covers every other
        write path including raw SQL."""
        if importo == 0:
            raise ValidationFailed(
                ENTITY, "importo", "importo nullo", expected="un importo diverso da zero"
            )

    def _check_refs(self, deal_id: UUID | None, document_id: UUID | None) -> None:
        """Every foreign key validated in both create and update, optional ones
        included -- skipped only when the caller supplies nothing, never when they
        supply a value. Without this any syntactically valid UUID reaches `flush()` and
        comes back as a raw `ForeignKeyViolation`."""
        if deal_id is not None and self.deals.get(deal_id) is None:
            raise NotFound("deal", deal_id)
        if document_id is not None and self.documents.get(document_id) is None:
            raise NotFound("document", document_id)

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def _update_custom_fields(self, cost: Cost, provided: dict[str, Any]) -> dict[str, Any]:
        """Identical contract to `DealService._update_custom_fields` and
        `TimeEntryService._update_custom_fields`; see either for the full reasoning."""
        active_by_key = {spec.key: spec for spec in self.fields.specs_for(ENTITY)}
        to_remove: set[str] = set()
        for key, value in provided.items():
            if value is not None:
                continue
            spec = active_by_key.get(key)
            if spec is not None and spec.required:
                raise ValidationFailed(
                    ENTITY, key, "campo obbligatorio", expected="un valore non vuoto"
                )
            to_remove.add(key)
        to_set = {k: v for k, v in provided.items() if v is not None}
        touched = [spec for spec in active_by_key.values() if spec.key in to_set]
        validated = validate_custom_fields(ENTITY, touched, to_set)
        merged = {k: v for k, v in cost.custom_fields.items() if k not in to_remove}
        merged.update(validated)
        return merged

    def _require(self, cost_id: UUID, *, include_deleted: bool = False) -> Cost:
        cost = self.repo.get(cost_id, include_deleted=include_deleted)
        if cost is None:
            raise NotFound(ENTITY, cost_id)
        return cost

    def create(self, data: CostCreate, actor: Actor) -> CostRead:
        actor.require_write("create_cost")
        self._check_importo(data.importo)
        self._check_refs(data.deal_id, data.document_id)
        self.categories.require_active(data.category_id)
        self.locks.assert_writable(ENTITY, "data", data.data)

        cost = self.repo.add(
            Cost(
                deal_id=data.deal_id,
                category_id=data.category_id,
                data=data.data,
                # The **total paid**, VAT included: under the flat-rate regime input VAT
                # is not deductible, so it is cost in every sense and recording the net
                # would understate it by 22% (§4.4).
                importo=data.importo,
                descrizione=data.descrizione,
                fornitore=data.fornitore,
                document_id=data.document_id,
                custom_fields=self._validated_custom(data.custom_fields or {}),
            )
        )
        self.activities.record(
            ENTITY,
            cost.id,
            "created",
            actor,
            {"importo": str(cost.importo), "deal_id": str(cost.deal_id) if cost.deal_id else None},
        )
        self.session.commit()
        return CostRead.model_validate(cost)

    def update(self, cost_id: UUID, data: CostUpdate, actor: Actor) -> CostRead:
        actor.require_write("update_cost")
        cost = self._require(cost_id)
        changes = data.model_dump(exclude_none=True, exclude={"custom_fields"})
        if "importo" in changes:
            self._check_importo(changes["importo"])
        self._check_refs(changes.get("deal_id"), changes.get("document_id"))
        if "category_id" in changes:
            self.categories.require_active(changes["category_id"])
        self.locks.assert_writable(ENTITY, "data", cost.data, changes.get("data"))

        if data.custom_fields is not None:
            changes["custom_fields"] = self._update_custom_fields(cost, data.custom_fields)
        for key, value in changes.items():
            setattr(cost, key, value)
        self.activities.record(ENTITY, cost.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return CostRead.model_validate(cost)

    def soft_delete(self, cost_id: UUID, actor: Actor) -> None:
        actor.require_write("delete_cost")
        cost = self._require(cost_id)
        self.locks.assert_writable(ENTITY, "data", cost.data)
        cost.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, cost.id, "deleted", actor)
        self.session.commit()

    def restore(self, cost_id: UUID, actor: Actor) -> CostRead:
        actor.require_write("restore_cost")
        cost = self._require(cost_id, include_deleted=True)
        self.locks.assert_writable(ENTITY, "data", cost.data)
        was_deleted = cost.deleted_at is not None
        cost.deleted_at = None
        if was_deleted:
            self.activities.record(ENTITY, cost.id, "restored", actor)
        self.session.commit()
        return CostRead.model_validate(cost)

    def get(self, cost_id: UUID, actor: Actor) -> CostRead:
        return CostRead.model_validate(self._require(cost_id))

    # `list` stays the last method in this class -- the unconditional project rule.
    def list(self, query: CostListQuery, actor: Actor) -> CostPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return CostPage(
            items=[CostRead.model_validate(c) for c in items],
            next_cursor=items[-1].id if has_more and items else None,
        )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_costs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(timetracking): CostService with categories, receipts and period locks"
```

---

### Task 4A-11: `recalculate_rates` — the one visible way to touch the past

**Files:**
- Modify: `packages/core/src/pigrocrm/core/timetracking/service.py` (replace the `NotImplementedError` stub)
- Test: `packages/core/tests/test_recalculate_rates.py`

**Interfaces:**
- Consumes: `TimeEntryRepository.in_range(deal_id, da, a)`; `RateResolver.resolve`; `billed_entry_ids`; `PeriodLockService.assert_writable`; `Actor.require_admin`.
- Produces: `TimeEntryService.recalculate_rates(deal_id: UUID, data: RecalculateRatesRequest, actor: Actor) -> int` — returns how many entries were rewritten. Not an MCP tool (§11's exclusion list, first name).

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_recalculate_rates.py
"""A real error exists: somebody typed 80 instead of 180 and notices two weeks later.
Denying it would produce hand corrections row by row, which is worse. So there is one
way to touch the past -- and it is explicit, admin-only, audited per entry, absent from
MCP, and it never reaches an hour that has been invoiced. Criterion 3."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.errors import Conflict, PermissionDenied
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.schemas import (
    PeriodLockCreate,
    RecalculateRatesRequest,
    TimeEntryCreate,
    TimeEntryListQuery,
)
from pigrocrm.core.timetracking.service import TimeEntryService

WRITER = Actor(id=None, type="user", role="collaboratore")
READER = Actor(id=None, type="user", role="readonly")


def _log(service, deal_id, user_id, day, ore="8.00"):
    return service.create(
        TimeEntryCreate(
            deal_id=deal_id, user_id=user_id, data=date(2026, 3, day),
            ore=Decimal(ore), descrizione=f"Giorno {day}",
        ),
        WRITER,
    )


def test_it_rewrites_the_interval_and_records_one_activity_per_entry(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    deal = db_session.get(Deal, seeded_deal_id)
    deal.tariffa_oraria = Decimal("80.000000")
    db_session.flush()
    service = TimeEntryService(db_session)
    inside = [_log(service, seeded_deal_id, seeded_user_id, day) for day in (2, 3, 4)]
    outside = _log(service, seeded_deal_id, seeded_user_id, 25)

    deal.tariffa_oraria = Decimal("180.000000")
    db_session.flush()
    touched = service.recalculate_rates(
        seeded_deal_id, RecalculateRatesRequest(da=date(2026, 3, 1), a=date(2026, 3, 10)), admin
    )
    assert touched == 3

    for entry in inside:
        refreshed = service.get(entry.id, READER)
        assert refreshed.tariffa_applicata == Decimal("180.000000")
        assert refreshed.tariffa_origine == "deal"
        assert refreshed.valore_riga == Decimal("1440.00")
        kinds = [e.kind for e in ActivityService(db_session).timeline("time_entry", entry.id)]
        assert "rates_recalculated" in kinds
        payload = next(
            e.payload
            for e in ActivityService(db_session).timeline("time_entry", entry.id)
            if e.kind == "rates_recalculated"
        )
        assert payload["tariffa_prima"] == "80.000000"
        assert payload["tariffa_dopo"] == "180.000000"

    # Outside the interval, untouched.
    assert service.get(outside.id, READER).tariffa_applicata == Decimal("80.000000")


def test_a_billed_entry_in_the_interval_refuses_the_whole_call_and_changes_nothing(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """All-or-nothing, and verified by re-reading the others after the refusal -- a
    partial rewrite would leave the interval in a state nobody chose."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    deal = db_session.get(Deal, seeded_deal_id)
    deal.tariffa_oraria = Decimal("80.000000")
    db_session.flush()
    service = TimeEntryService(db_session)
    entries = [_log(service, seeded_deal_id, seeded_user_id, day) for day in (2, 3, 4)]
    line_id = uuid4()
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": line_id, "id": entries[1].id},
    )
    db_session.flush()

    deal.tariffa_oraria = Decimal("180.000000")
    db_session.flush()
    with pytest.raises(Conflict) as excinfo:
        service.recalculate_rates(
            seeded_deal_id,
            RecalculateRatesRequest(da=date(2026, 3, 1), a=date(2026, 3, 10)),
            admin,
        )
    assert excinfo.value.details["voci_fatturate"] == 1
    assert excinfo.value.details["prima_riga"] == str(line_id)

    db_session.rollback()
    for entry in entries:
        assert service.get(entry.id, READER).tariffa_applicata == Decimal("80.000000")


def test_a_collaborator_cannot_call_it(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """Rewriting what already-done work was worth is closer to configuration than to
    writing an entity -- slice 1 §6.3's reading, which slice 3 §11 applied to
    issuing."""
    with pytest.raises(PermissionDenied):
        TimeEntryService(db_session).recalculate_rates(
            seeded_deal_id,
            RecalculateRatesRequest(da=date(2026, 3, 1), a=date(2026, 3, 10)),
            WRITER,
        )


def test_it_will_not_rewrite_inside_a_closed_period(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The lock and the recalculation are the two ways the past can move, and they must
    not have a gap between them: a closed month is closed to this too."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    service = TimeEntryService(db_session)
    _log(service, seeded_deal_id, seeded_user_id, 2)
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    with pytest.raises(Conflict):
        service.recalculate_rates(
            seeded_deal_id,
            RecalculateRatesRequest(da=date(2026, 3, 1), a=date(2026, 3, 10)),
            admin,
        )


def test_an_inverted_interval_is_a_validation_failure(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    from pigrocrm.core.errors import ValidationFailed

    admin = Actor(id=seeded_user_id, type="user", role="admin")
    with pytest.raises(ValidationFailed) as excinfo:
        TimeEntryService(db_session).recalculate_rates(
            seeded_deal_id,
            RecalculateRatesRequest(da=date(2026, 3, 10), a=date(2026, 3, 1)),
            admin,
        )
    assert excinfo.value.details["field"] == "a"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_recalculate_rates.py -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/timetracking/service.py -- replacing the stub.
    def recalculate_rates(
        self, deal_id: UUID, data: RecalculateRatesRequest, actor: Actor
    ) -> int:
        """The only way to touch the past, and it is visible.

        `admin`, never `collaboratore`, and **not exposed over MCP** (§11's exclusion
        list, first name): rewriting what already-done work was worth is closer to
        configuration than to writing an entity -- slice 1 §6.3's reading, which slice
        3 §11 applied to issuing an invoice.

        All-or-nothing. If the interval contains even one entry belonging to an issued
        invoice the whole call refuses, naming how many and the first line involved,
        because that number has already been handed to a client. A partial rewrite
        would leave the interval in a state nobody chose, so the refusal happens before
        any assignment.

        Returns how many entries were rewritten, so a caller can say "12 voci
        aggiornate" instead of "done".
        """
        actor.require_admin("recalculate_rates")
        if data.a < data.da:
            raise ValidationFailed(
                ENTITY, "a", "intervallo invertito", expected="una data non anteriore a 'da'"
            )
        self._require_deal(deal_id)
        entries = self.repo.in_range(deal_id, data.da, data.a)

        billed = billed_entry_ids(self.session, entries)
        if billed:
            first = next(e for e in entries if e.id in billed)
            raise Conflict(
                ENTITY,
                "l'intervallo contiene voci già fatturate: quei valori sono stati "
                "consegnati a un cliente e non si riscrivono",
                voci_fatturate=len(billed),
                prima_riga=str(first.invoice_line_id),
                prima_voce=str(first.id),
            )

        # A closed month is closed to this too: the lock and the recalculation are the
        # two ways the past can move, and leaving a gap between them would make the
        # lock decorative.
        self.locks.assert_writable(ENTITY, "data", *[e.data for e in entries])

        touched = 0
        for entry in entries:
            resolved = self.rates.resolve(deal_id=entry.deal_id, user_id=entry.user_id)
            if (
                resolved.tariffa == entry.tariffa_applicata
                and resolved.costo == entry.costo_applicato
            ):
                # Nothing changed for this row: skip it rather than writing an activity
                # claiming a change that did not happen -- the same honesty guard
                # `restore` applies to its own "restored" entry.
                continue
            self.activities.record(
                ENTITY,
                entry.id,
                "rates_recalculated",
                actor,
                {
                    "tariffa_prima": str(entry.tariffa_applicata),
                    "tariffa_dopo": str(resolved.tariffa),
                    "costo_prima": str(entry.costo_applicato),
                    "costo_dopo": str(resolved.costo),
                },
            )
            entry.tariffa_applicata = resolved.tariffa
            entry.tariffa_origine = resolved.tariffa_origine
            entry.costo_applicato = resolved.costo
            entry.costo_origine = resolved.costo_origine
            touched += 1

        self.session.commit()
        return touched
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_recalculate_rates.py packages/core/tests/test_rate_freezing.py -v`
Expected: PASS. Both together, deliberately: `recalculate_rates` is the one sanctioned exception to the freezing guarantee, and the two tests have to stay green side by side or the exception has swallowed the rule.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(timetracking): recalculate_rates, admin-only, refusing invoiced hours"
```

---

## Phase 4A-4 — The two adapters

### Task 4A-12: REST routers for hours, costs, categories, locks and rates

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/time_entries.py`
- Create: `apps/api/src/pigrocrm_api/routers/costs.py`
- Create: `apps/api/src/pigrocrm_api/routers/cost_categories.py`
- Create: `apps/api/src/pigrocrm_api/routers/period_locks.py`
- Modify: `apps/api/src/pigrocrm_api/routers/deals.py` (the four deal-scoped routes)
- Modify: `apps/api/src/pigrocrm_api/routers/users.py` (`PUT /api/users/{id}/rates`)
- Modify: `apps/api/src/pigrocrm_api/main.py` (register the four new routers)
- Test: `apps/api/tests/test_time_entries_api.py`
- Test: `apps/api/tests/test_costs_api.py`

**Interfaces:**
- Consumes: `SessionDep`, `ActorDep` (`pigrocrm_api.deps`); `PROBLEM_RESPONSES` (`pigrocrm_api.errors`); `parse_custom_filter`, `CUSTOM_QUERY_DESCRIPTION` (`pigrocrm_api.query_params`); every service and schema from Tasks 4A-6 … 4A-11.
- Produces these endpoints, matching §11's table exactly:
  ```
  GET  POST      /api/time-entries
  GET PATCH DELETE /api/time-entries/{entry_id}
  POST          /api/time-entries/{entry_id}/restore
  GET           /api/deals/{deal_id}/time-entries
  GET           /api/deals/{deal_id}/time-summary
  GET           /api/deals/{deal_id}/rates            describe_rates
  PUT           /api/deals/{deal_id}/rate             (admin)
  POST          /api/deals/{deal_id}/rates/recalculate (admin)
  GET  POST     /api/costs      ; GET PATCH DELETE /api/costs/{cost_id} ; POST .../restore
  GET  POST     /api/cost-categories                  (POST admin)
  PATCH         /api/cost-categories/{category_id}    (admin)
  POST          /api/cost-categories/{category_id}/archive · /unarchive   (admin)
  POST          /api/cost-categories/seed              (admin)
  GET  POST     /api/period-locks ; DELETE /api/period-locks/{anno}/{mese}   (write admin)
  PUT           /api/users/{user_id}/rates             (admin)
  ```
  Every router is registered with `responses=PROBLEM_RESPONSES`. No router contains an `if` of business logic — a router that does is a bug (slice 1 §7). Role checks stay in the services, never in the routers.

- [ ] **Step 1: Write the failing API test**

```python
# apps/api/tests/test_time_entries_api.py
"""The HTTP surface, thin by design: validate the body, resolve the Actor, call the
service, serialise. Every assertion here is about the wire -- statuses, problem
documents, and Decimal-as-string -- never about business rules, which are proven in
packages/core."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient


def test_post_creates_and_returns_decimals_as_strings(
    api_client: TestClient, admin_cookies, seeded_deal_id, seeded_user_id
) -> None:
    """`Decimal` serialises to a JSON string, never a float -- which is exactly what
    lets the frontend read the digits instead of routing them through a binary float.
    Asserted on the raw text, because `response.json()` would already have parsed it."""
    response = api_client.post(
        "/api/time-entries",
        cookies=admin_cookies,
        json={
            "deal_id": str(seeded_deal_id),
            "user_id": str(seeded_user_id),
            "data": "2026-03-10",
            "ore": "3.50",
            "descrizione": "Sviluppo",
            "tariffa_applicata": "80.000000",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["ore"] == "3.50"
    assert body["tariffa_applicata"] == "80.000000"
    assert body["valore_riga"] == "280.00"
    assert '"ore":"3.50"' in response.text.replace(" ", "")


def test_a_closed_period_is_a_409_problem_document_naming_the_month(
    api_client: TestClient, admin_cookies, seeded_deal_id, seeded_user_id
) -> None:
    assert (
        api_client.post(
            "/api/period-locks", cookies=admin_cookies, json={"anno": 2026, "mese": 3}
        ).status_code
        == 201
    )
    response = api_client.post(
        "/api/time-entries",
        cookies=admin_cookies,
        json={
            "deal_id": str(seeded_deal_id),
            "user_id": str(seeded_user_id),
            "data": "2026-03-10",
            "ore": "1.00",
            "descrizione": "x",
        },
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "conflict"
    assert problem["mese"] == 3 and problem["anno"] == 2026
    assert "marzo 2026" in problem["detail"]


def test_a_future_date_is_a_422_naming_the_field(
    api_client: TestClient, admin_cookies, seeded_deal_id, seeded_user_id
) -> None:
    response = api_client.post(
        "/api/time-entries",
        cookies=admin_cookies,
        json={
            "deal_id": str(seeded_deal_id),
            "user_id": str(seeded_user_id),
            "data": "2099-01-01",
            "ore": "1.00",
            "descrizione": "x",
        },
    )
    assert response.status_code == 422
    assert response.json()["field"] == "data"


def test_over_range_hours_are_refused_before_the_database(
    api_client: TestClient, admin_cookies, seeded_deal_id, seeded_user_id
) -> None:
    """`ore = 80` is the comma slip that means 8,0. Bounded on the schema so it comes
    back as a clean 422 rather than reaching the CHECK as a raw IntegrityError."""
    response = api_client.post(
        "/api/time-entries",
        cookies=admin_cookies,
        json={
            "deal_id": str(seeded_deal_id),
            "user_id": str(seeded_user_id),
            "data": "2026-03-10",
            "ore": "80.00",
            "descrizione": "x",
        },
    )
    assert response.status_code == 422


def test_the_list_is_bounded_and_paginated(api_client: TestClient, admin_cookies) -> None:
    assert api_client.get(
        "/api/time-entries", cookies=admin_cookies, params={"limit": 500}
    ).status_code == 422
    ok = api_client.get("/api/time-entries", cookies=admin_cookies, params={"limit": 200})
    assert ok.status_code == 200
    assert set(ok.json()) == {"items", "next_cursor"}


def test_recalculate_requires_admin(
    api_client: TestClient, collaborator_cookies, seeded_deal_id
) -> None:
    response = api_client.post(
        f"/api/deals/{seeded_deal_id}/rates/recalculate",
        cookies=collaborator_cookies,
        json={"da": "2026-03-01", "a": "2026-03-31"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_the_openapi_document_describes_the_new_routes(api_client: TestClient) -> None:
    """The frontend client is generated from this document, so a route missing here is
    a route the UI cannot call with types."""
    paths = api_client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/time-entries",
        "/api/time-entries/{entry_id}",
        "/api/deals/{deal_id}/time-entries",
        "/api/deals/{deal_id}/time-summary",
        "/api/deals/{deal_id}/rates",
        "/api/costs",
        "/api/cost-categories",
        "/api/period-locks",
        "/api/users/{user_id}/rates",
    ):
        assert path in paths, path
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest apps/api/tests/test_time_entries_api.py -v`
Expected: FAIL with 404s on every new path.

- [ ] **Step 3: Write `time_entries.py`**

```python
# apps/api/src/pigrocrm_api/routers/time_entries.py
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.timetracking.schemas import (
    TimeEntryCreate,
    TimeEntryListQuery,
    TimeEntryPage,
    TimeEntryRead,
    TimeEntryUpdate,
)
from pigrocrm.core.timetracking.service import TimeEntryService
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES
from pigrocrm_api.query_params import CUSTOM_QUERY_DESCRIPTION, parse_custom_filter

router = APIRouter(prefix="/api/time-entries", tags=["time-entries"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=TimeEntryRead, status_code=status.HTTP_201_CREATED)
def create(data: TimeEntryCreate, session: SessionDep, actor: ActorDep) -> TimeEntryRead:
    return TimeEntryService(session).create(data, actor)


@router.get("", response_model=TimeEntryPage)
def list_time_entries(
    session: SessionDep,
    actor: ActorDep,
    deal_id: Annotated[UUID | None, Query()] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    da: Annotated[str | None, Query(description="Data minima, YYYY-MM-DD")] = None,
    a: Annotated[str | None, Query(description="Data massima, YYYY-MM-DD")] = None,
    fatturabile: Annotated[bool | None, Query()] = None,
    fatturato: Annotated[
        bool | None,
        Query(description="true = già su una riga di fattura; false = da fatturare"),
    ] = None,
    # SafeStr on the parameter itself, not only on a schema field: these are ordinary
    # query parameters, so the guard has to sit here for FastAPI's own validation to
    # reject a NUL byte as a 422 before TimeEntryListQuery is hand-built below --
    # identical to `list_deals` in routers/deals.py.
    custom: Annotated[list[SafeStr] | None, Query(description=CUSTOM_QUERY_DESCRIPTION)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> TimeEntryPage:
    query = TimeEntryListQuery(
        deal_id=deal_id,
        user_id=user_id,
        da=da,
        a=a,
        fatturabile=fatturabile,
        fatturato=fatturato,
        custom=parse_custom_filter(custom),
        limit=limit,
        cursor=cursor,
    )
    return TimeEntryService(session).list(query, actor)


@router.get("/{entry_id}", response_model=TimeEntryRead)
def get(entry_id: UUID, session: SessionDep, actor: ActorDep) -> TimeEntryRead:
    return TimeEntryService(session).get(entry_id, actor)


@router.patch("/{entry_id}", response_model=TimeEntryRead)
def update(
    entry_id: UUID, data: TimeEntryUpdate, session: SessionDep, actor: ActorDep
) -> TimeEntryRead:
    return TimeEntryService(session).update(entry_id, data, actor)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(entry_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    TimeEntryService(session).soft_delete(entry_id, actor)


@router.post("/{entry_id}/restore", response_model=TimeEntryRead)
def restore(entry_id: UUID, session: SessionDep, actor: ActorDep) -> TimeEntryRead:
    return TimeEntryService(session).restore(entry_id, actor)
```

- [ ] **Step 4: Write `costs.py`, `cost_categories.py` and `period_locks.py`**

```python
# apps/api/src/pigrocrm_api/routers/costs.py
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.schemas import (
    CostCreate,
    CostListQuery,
    CostPage,
    CostRead,
    CostUpdate,
)
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES
from pigrocrm_api.query_params import CUSTOM_QUERY_DESCRIPTION, parse_custom_filter

router = APIRouter(prefix="/api/costs", tags=["costs"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=CostRead, status_code=status.HTTP_201_CREATED)
def create(data: CostCreate, session: SessionDep, actor: ActorDep) -> CostRead:
    return CostService(session).create(data, actor)


@router.get("", response_model=CostPage)
def list_costs(
    session: SessionDep,
    actor: ActorDep,
    deal_id: Annotated[UUID | None, Query()] = None,
    solo_generali: Annotated[
        bool, Query(description="Solo spese generali, cioè senza deal (§7.4)")
    ] = False,
    category_id: Annotated[UUID | None, Query()] = None,
    da: Annotated[str | None, Query()] = None,
    a: Annotated[str | None, Query()] = None,
    custom: Annotated[list[SafeStr] | None, Query(description=CUSTOM_QUERY_DESCRIPTION)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> CostPage:
    query = CostListQuery(
        deal_id=deal_id,
        solo_generali=solo_generali,
        category_id=category_id,
        da=da,
        a=a,
        custom=parse_custom_filter(custom),
        limit=limit,
        cursor=cursor,
    )
    return CostService(session).list(query, actor)


@router.get("/{cost_id}", response_model=CostRead)
def get(cost_id: UUID, session: SessionDep, actor: ActorDep) -> CostRead:
    return CostService(session).get(cost_id, actor)


@router.patch("/{cost_id}", response_model=CostRead)
def update(cost_id: UUID, data: CostUpdate, session: SessionDep, actor: ActorDep) -> CostRead:
    return CostService(session).update(cost_id, data, actor)


@router.delete("/{cost_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(cost_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    CostService(session).soft_delete(cost_id, actor)


@router.post("/{cost_id}/restore", response_model=CostRead)
def restore(cost_id: UUID, session: SessionDep, actor: ActorDep) -> CostRead:
    return CostService(session).restore(cost_id, actor)
```

```python
# apps/api/src/pigrocrm_api/routers/cost_categories.py
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.timetracking.categories import CostCategoryService
from pigrocrm.core.timetracking.schemas import (
    CostCategoryCreate,
    CostCategoryRead,
    CostCategoryUpdate,
)
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(
    prefix="/api/cost-categories", tags=["cost-categories"], responses=PROBLEM_RESPONSES
)


@router.get("", response_model=list[CostCategoryRead])
def list_cost_categories(
    session: SessionDep,
    actor: ActorDep,
    include_archived: Annotated[bool, Query()] = False,
) -> list[CostCategoryRead]:
    return CostCategoryService(session).list_cost_categories(include_archived=include_archived)


@router.post("", response_model=CostCategoryRead, status_code=status.HTTP_201_CREATED)
def create(
    data: CostCategoryCreate, session: SessionDep, actor: ActorDep
) -> CostCategoryRead:
    return CostCategoryService(session).create_cost_category(data, actor)


@router.post("/seed", response_model=list[CostCategoryRead])
def seed(session: SessionDep, actor: ActorDep) -> list[CostCategoryRead]:
    """Idempotent: returns only what it actually created, so a second call answers
    `[]` rather than duplicating the taxonomy."""
    return CostCategoryService(session).seed_defaults(actor)


@router.patch("/{category_id}", response_model=CostCategoryRead)
def update(
    category_id: UUID, data: CostCategoryUpdate, session: SessionDep, actor: ActorDep
) -> CostCategoryRead:
    return CostCategoryService(session).update_cost_category(category_id, data, actor)


@router.post("/{category_id}/archive", response_model=CostCategoryRead)
def archive(category_id: UUID, session: SessionDep, actor: ActorDep) -> CostCategoryRead:
    """Archive, never delete: a deleted category with costs still attached leaves orphan
    rows nobody can see. There is deliberately no DELETE verb on this resource."""
    return CostCategoryService(session).archive_cost_category(category_id, actor)


@router.post("/{category_id}/unarchive", response_model=CostCategoryRead)
def unarchive(category_id: UUID, session: SessionDep, actor: ActorDep) -> CostCategoryRead:
    return CostCategoryService(session).unarchive_cost_category(category_id, actor)
```

```python
# apps/api/src/pigrocrm_api/routers/period_locks.py
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.schemas import PeriodLockCreate, PeriodLockRead
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/period-locks", tags=["period-locks"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=list[PeriodLockRead])
def list_locks(
    session: SessionDep, actor: ActorDep, anno: Annotated[int | None, Query()] = None
) -> list[PeriodLockRead]:
    return PeriodLockService(session).list_locks(anno=anno)


@router.post("", response_model=PeriodLockRead, status_code=status.HTTP_201_CREATED)
def close_period(data: PeriodLockCreate, session: SessionDep, actor: ActorDep) -> PeriodLockRead:
    return PeriodLockService(session).close_period(data, actor)


@router.delete("/{anno}/{mese}", status_code=status.HTTP_204_NO_CONTENT)
def reopen_period(
    session: SessionDep,
    actor: ActorDep,
    anno: Annotated[int, Path(ge=2000, le=2200)],
    mese: Annotated[int, Path(ge=1, le=12)],
) -> None:
    """A period is not reopened by accident: the service requires `admin` and writes an
    activity. The bounds here are the same ones `PeriodLockCreate` carries, so a
    nonsense path segment is a 422 before the service is reached."""
    PeriodLockService(session).reopen_period(anno, mese, actor)
```

- [ ] **Step 5: Add the deal-scoped and user-scoped routes**

```python
# apps/api/src/pigrocrm_api/routers/deals.py -- append, and add the imports
from pigrocrm.core.timetracking.schemas import (
    DealRateUpdate,
    DealTimeSummary,
    RateDescription,
    RecalculateRatesRequest,
    TimeEntryListQuery,
    TimeEntryPage,
)
from pigrocrm.core.timetracking.service import TimeEntryService


class RecalculateResponse(BaseModel):
    """`voci_aggiornate` rather than a bare integer: the UI says "12 voci aggiornate",
    and a naked number in a JSON body is a value nobody can label."""

    voci_aggiornate: int


@router.get("/{deal_id}/time-entries", response_model=TimeEntryPage)
def deal_time_entries(
    deal_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    da: Annotated[str | None, Query()] = None,
    a: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> TimeEntryPage:
    return TimeEntryService(session).list(
        TimeEntryListQuery(deal_id=deal_id, da=da, a=a, limit=limit, cursor=cursor), actor
    )


@router.get("/{deal_id}/time-summary", response_model=DealTimeSummary)
def deal_time_summary(deal_id: UUID, session: SessionDep, actor: ActorDep) -> DealTimeSummary:
    return TimeEntryService(session).deal_summary(deal_id, actor)


@router.get("/{deal_id}/rates", response_model=RateDescription)
def deal_rates(
    deal_id: UUID, user_id: Annotated[UUID, Query()], session: SessionDep, actor: ActorDep
) -> RateDescription:
    """What a new entry would freeze right now. Shown next to the hours field so the
    rate is visible before saving, not discovered after."""
    return TimeEntryService(session).describe_rates(deal_id, user_id, actor)


@router.put("/{deal_id}/rate", status_code=status.HTTP_204_NO_CONTENT)
def set_deal_rate(
    deal_id: UUID, data: DealRateUpdate, session: SessionDep, actor: ActorDep
) -> None:
    TimeEntryService(session).update_deal_rate(deal_id, data, actor)


@router.post("/{deal_id}/rates/recalculate", response_model=RecalculateResponse)
def recalculate_rates(
    deal_id: UUID, data: RecalculateRatesRequest, session: SessionDep, actor: ActorDep
) -> RecalculateResponse:
    return RecalculateResponse(
        voci_aggiornate=TimeEntryService(session).recalculate_rates(deal_id, data, actor)
    )
```

```python
# apps/api/src/pigrocrm_api/routers/users.py -- append, with the imports
from pigrocrm.core.timetracking.schemas import UserRatesUpdate
from pigrocrm.core.timetracking.service import TimeEntryService


@router.put("/{user_id}/rates", status_code=status.HTTP_204_NO_CONTENT)
def set_user_rates(
    user_id: UUID, data: UserRatesUpdate, session: SessionDep, actor: ActorDep
) -> None:
    """On `TimeEntryService`, not on `UserService`: see the method's own docstring and
    "Contradictions" item 4 -- §11 fixes the audited surface to three service classes
    and this is one of the ten names that must be excluded from MCP by name."""
    TimeEntryService(session).update_user_rates(user_id, data, actor)
```

- [ ] **Step 6: Register the four routers**

```python
# apps/api/src/pigrocrm_api/main.py -- add to the existing registration loop's list,
# in the same order the module currently uses.
from pigrocrm_api.routers import cost_categories, costs, period_locks, time_entries

# ... inside the loop's tuple of routers:
    time_entries.router,
    costs.router,
    cost_categories.router,
    period_locks.router,
```

- [ ] **Step 7: Run the API suite**

Run: `uv run pytest apps/api -q`
Expected: PASS. Then regenerate the frontend client so Task 4A-16 has types to build on:

Run: `pnpm -C apps/web generate:api`
Expected: `apps/web/src/lib/api-types.ts` gains `TimeEntryRead`, `CostRead`, `CostCategoryRead`, `PeriodLockRead`, `DealTimeSummary`, `RateDescription` and the new paths. Commit the regenerated file with this task — a generated file left behind is a `tsc` break in the next task.

- [ ] **Step 8: Commit**

```bash
git add apps/api apps/web/src/lib/api-types.ts
git commit -m "feat(api): REST surface for hours, costs, categories, period locks and rates"
```

---

### Task 4A-13: MCP tools, the `deal://` resource, and the ban made mechanical

**Files:**
- Create: `apps/mcp/src/pigrocrm_mcp/tools/timetracking.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py` (register the tools; add two `WithJsonSchema` aliases)
- Modify: `apps/mcp/src/pigrocrm_mcp/resources/entities.py` (`render_deal` gains the hours block)
- Modify: `packages/core/tests/test_architecture.py` (the exclusion clause)
- Test: `apps/mcp/tests/test_timetracking_tools.py`
- Test: `apps/mcp/tests/test_log_time_concurrency.py`

**Interfaces:**
- Consumes: `McpContext`, the `guard` closure passed into `register_entity_tools`, `BoundedLimit` and the `WithJsonSchema` technique already in `tools/__init__.py`; every service from Tasks 4A-6 … 4A-11.
- Produces (thin call-through functions, one per tool, in `tools/timetracking.py`):
  ```python
  def log_time(context, data: dict[str, Any]) -> dict[str, Any]
  def update_time_entry(context, entry_id: str, data: dict[str, Any]) -> dict[str, Any]
  def delete_time_entry(context, entry_id: str) -> dict[str, str]
  def restore_time_entry(context, entry_id: str) -> dict[str, Any]
  def get_time_entry(context, entry_id: str) -> dict[str, Any]
  def list_time_entries(context, query: TimeEntryListQuery) -> dict[str, Any]
  def get_deal_time_summary(context, deal_id: str) -> dict[str, Any]
  def describe_rates(context, deal_id: str, user_id: str) -> dict[str, Any]
  def create_cost(context, data: dict[str, Any]) -> dict[str, Any]
  def update_cost(context, cost_id: str, data: dict[str, Any]) -> dict[str, Any]
  def delete_cost(context, cost_id: str) -> dict[str, str]
  def restore_cost(context, cost_id: str) -> dict[str, Any]
  def get_cost(context, cost_id: str) -> dict[str, Any]
  def list_costs(context, query: CostListQuery) -> dict[str, Any]
  def list_cost_categories(context, include_archived: bool) -> dict[str, Any]
  ```
- Produces (architecture test): `AUDITED_SERVICES`, `MCP_EXCLUDED`, `test_the_mcp_exclusion_list_is_exactly_the_ten_declared_names`, `test_no_mcp_tool_reaches_an_excluded_method`, `test_every_other_public_method_has_a_tool`.
- **No tools** for the ten excluded names. §11's reasons, restated where the code lives: registering the tool is the only enforcement that holds while residual R10 is open, because a PAT has no scopes and inherits the owner's full role — an authorisation check would let an admin token straight through.

- [ ] **Step 1: Write the failing architecture test**

```python
# packages/core/tests/test_architecture.py -- append. The import-direction allowlist
# above is untouched.
"""The MCP ban, made mechanical.

Slice 4 §11 requires that for every public method of the audited services either an
MCP tool calls it, or the method appears in a declared exclusion list -- and that the
list is **exactly** ten names. Adding a tool for one of them breaks the build; removing
a name without adding a tool breaks it too. Somebody reading the list can then see that
the absence was a decision and not an oversight.

Two of the ten (`bind_time_to_invoice`, `get_fiscal_estimate`) belong to
`AnalyticsService`, which does not exist until plan 4B. The list is asserted as a
constant regardless -- it is the *declaration* §11 fixes -- while the coverage half only
inspects classes actually present in `AUDITED_SERVICES`. Task 4B-9 therefore adds
`AnalyticsService` to that tuple and changes not one character of the list.
"""

import importlib
import inspect

MCP_TOOLS_DIR = CORE_ROOT.parents[1] / "apps" / "mcp" / "src" / "pigrocrm_mcp"

# Exactly the ten names slice 4 §11 fixes, in the order the spec lists them.
MCP_EXCLUDED: tuple[str, ...] = (
    "recalculate_rates",
    "update_user_rates",
    "update_deal_rate",
    "create_cost_category",
    "update_cost_category",
    "archive_cost_category",
    "bind_time_to_invoice",
    "close_period",
    "reopen_period",
    "get_fiscal_estimate",
)


def _audited_services() -> list[type]:
    """`TimeEntryService`, `CostService` and -- from plan 4B -- `AnalyticsService`,
    exactly the three classes §11 names. Resolved by import rather than hard-coded
    objects so this file does not fail to collect before 4B exists."""
    found: list[type] = []
    for module_path, class_name in (
        ("pigrocrm.core.timetracking.service", "TimeEntryService"),
        ("pigrocrm.core.timetracking.costs", "CostService"),
        ("pigrocrm.core.analytics.service", "AnalyticsService"),
    ):
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            continue
        found.append(getattr(module, class_name))
    return found


def _public_methods(cls: type) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_") and member.__qualname__.startswith(cls.__name__ + ".")
    }


def _tool_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in (MCP_TOOLS_DIR / "tools").rglob("*.py")
    )


def test_the_mcp_exclusion_list_is_exactly_the_ten_declared_names() -> None:
    assert len(MCP_EXCLUDED) == 10
    assert len(set(MCP_EXCLUDED)) == 10
    assert set(MCP_EXCLUDED) == {
        "recalculate_rates",
        "update_user_rates",
        "update_deal_rate",
        "create_cost_category",
        "update_cost_category",
        "archive_cost_category",
        "bind_time_to_invoice",
        "close_period",
        "reopen_period",
        "get_fiscal_estimate",
    }


def test_no_mcp_tool_reaches_an_excluded_method() -> None:
    """Matched on the call site, not on the tool's own name: a tool called
    `tidy_up_rates` that happened to call `.recalculate_rates(` is exactly the way this
    ban would otherwise be lost."""
    source = _tool_source()
    offenders = [name for name in MCP_EXCLUDED if f".{name}(" in source]
    assert not offenders, (
        "these methods must not be reachable from any MCP tool (slice 4 §11): "
        f"{offenders}"
    )


def test_every_other_public_method_has_a_tool() -> None:
    source = _tool_source()
    audited = _audited_services()
    assert audited, "expected at least TimeEntryService and CostService to be importable"
    missing: list[str] = []
    for cls in audited:
        for name in sorted(_public_methods(cls)):
            if name in MCP_EXCLUDED:
                continue
            if f".{name}(" not in source:
                missing.append(f"{cls.__name__}.{name}")
    assert not missing, (
        "every public method of an audited service must either be reachable from an "
        f"MCP tool or be one of the ten declared exclusions: {missing}"
    )


def test_the_guard_catches_a_tool_added_for_an_excluded_method(tmp_path) -> None:
    """The guard proven to catch what it claims to, not merely written -- the same
    discipline the import-direction tests above follow."""
    sneaky = "TimeEntryService(context.session).recalculate_rates(deal_id, data, actor)"
    assert any(f".{name}(" in sneaky for name in MCP_EXCLUDED)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_architecture.py -v`
Expected: `test_every_other_public_method_has_a_tool` FAILS listing every `TimeEntryService`/`CostService` public method, because `apps/mcp/src/pigrocrm_mcp/tools/timetracking.py` does not exist yet. The other three pass — the list is already correct, which is the point.

- [ ] **Step 3: Write the tool call-throughs**

```python
# apps/mcp/src/pigrocrm_mcp/tools/timetracking.py
"""Thin calls into core services, like every other tool module.

A tool that contained business logic would be logic the web app cannot reach -- the
failure this architecture exists to prevent. Every function here builds a core schema
from caller-supplied data *inside* the guarded call, so a bad value becomes rendered
guidance instead of a raw pydantic dump (see `tools/__init__.py`'s own note on
`WithJsonSchema` and `_guard`).
"""

from typing import Any
from uuid import UUID

from pigrocrm.core.timetracking.categories import CostCategoryService
from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.schemas import (
    CostCreate,
    CostListQuery,
    CostUpdate,
    TimeEntryCreate,
    TimeEntryListQuery,
    TimeEntryUpdate,
)
from pigrocrm.core.timetracking.service import TimeEntryService
from pigrocrm_mcp.context import McpContext


def log_time(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    return (
        TimeEntryService(context.session)
        .create(TimeEntryCreate(**data), context.actor)
        .model_dump(mode="json")
    )


def update_time_entry(
    context: McpContext, entry_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    return (
        TimeEntryService(context.session)
        .update(UUID(entry_id), TimeEntryUpdate(**data), context.actor)
        .model_dump(mode="json")
    )


def delete_time_entry(context: McpContext, entry_id: str) -> dict[str, str]:
    TimeEntryService(context.session).soft_delete(UUID(entry_id), context.actor)
    return {"status": "archiviata", "entry_id": entry_id}


def restore_time_entry(context: McpContext, entry_id: str) -> dict[str, Any]:
    return (
        TimeEntryService(context.session)
        .restore(UUID(entry_id), context.actor)
        .model_dump(mode="json")
    )


def get_time_entry(context: McpContext, entry_id: str) -> dict[str, Any]:
    return (
        TimeEntryService(context.session)
        .get(UUID(entry_id), context.actor)
        .model_dump(mode="json")
    )


def list_time_entries(context: McpContext, query: TimeEntryListQuery) -> dict[str, Any]:
    page = TimeEntryService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def get_deal_time_summary(context: McpContext, deal_id: str) -> dict[str, Any]:
    return (
        TimeEntryService(context.session)
        .deal_summary(UUID(deal_id), context.actor)
        .model_dump(mode="json")
    )


def describe_rates(context: McpContext, deal_id: str, user_id: str) -> dict[str, Any]:
    return (
        TimeEntryService(context.session)
        .describe_rates(UUID(deal_id), UUID(user_id), context.actor)
        .model_dump(mode="json")
    )


def create_cost(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    return (
        CostService(context.session)
        .create(CostCreate(**data), context.actor)
        .model_dump(mode="json")
    )


def update_cost(context: McpContext, cost_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return (
        CostService(context.session)
        .update(UUID(cost_id), CostUpdate(**data), context.actor)
        .model_dump(mode="json")
    )


def delete_cost(context: McpContext, cost_id: str) -> dict[str, str]:
    CostService(context.session).soft_delete(UUID(cost_id), context.actor)
    return {"status": "archiviato", "cost_id": cost_id}


def restore_cost(context: McpContext, cost_id: str) -> dict[str, Any]:
    return (
        CostService(context.session)
        .restore(UUID(cost_id), context.actor)
        .model_dump(mode="json")
    )


def get_cost(context: McpContext, cost_id: str) -> dict[str, Any]:
    return (
        CostService(context.session).get(UUID(cost_id), context.actor).model_dump(mode="json")
    )


def list_costs(context: McpContext, query: CostListQuery) -> dict[str, Any]:
    page = CostService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def list_cost_categories(context: McpContext, include_archived: bool) -> dict[str, Any]:
    categories = CostCategoryService(context.session).list_cost_categories(
        include_archived=include_archived
    )
    return {"categories": [c.model_dump(mode="json") for c in categories]}
```

- [ ] **Step 4: Register the tools**

```python
# apps/mcp/src/pigrocrm_mcp/tools/__init__.py -- add the imports and two aliases, then
# the tool block at the end of register_entity_tools.
from pigrocrm.core.timetracking.schemas import (
    CostListQuery,
    CostUpdate,
    TimeEntryListQuery,
    TimeEntryUpdate,
)
from pigrocrm_mcp.tools import timetracking

# Same runtime-permissive / schema-only-strict split as the existing `*Changes`
# aliases: the parameter stays an unvalidated dict so a bad nested value is rejected by
# `TimeEntryUpdate(**data)` *inside* the guarded call and becomes rendered guidance,
# while `list_tools()` still advertises the real field names.
TimeEntryChanges = Annotated[dict[str, Any], WithJsonSchema(TimeEntryUpdate.model_json_schema())]
CostChanges = Annotated[dict[str, Any], WithJsonSchema(CostUpdate.model_json_schema())]

# `OptionalHours`/`OptionalFactor` mirror `OptionalMoney` exactly, for the same
# SDK-bypass reason: a bare `float` parameter lets a wrong-TYPE argument be rejected by
# the SDK's own pre-call coercion, before `_guard` runs, producing the raw English
# pydantic dump spec §8.2 forbids.
HoursArg = Annotated[float | str, WithJsonSchema({"type": "number", "exclusiveMinimum": 0, "maximum": 24})]
OptionalFactor = Annotated[
    float | str | None,
    WithJsonSchema({"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}], "default": None}),
]
```

```python
# ... and at the end of register_entity_tools:

    # ---- time tracking -----------------------------------------------------
    # An agent may record and read. It may not change what already-recorded numbers
    # mean. Ten methods are therefore deliberately absent from this module --
    # `recalculate_rates`, `update_user_rates`, `update_deal_rate`, the three
    # cost-category writes, `bind_time_to_invoice`, `close_period`, `reopen_period`,
    # `get_fiscal_estimate` -- and `packages/core/tests/test_architecture.py` fails the
    # build if a tool for any of them appears here or if that list changes. The defence
    # is structural rather than permission-based because residual R10 is open: a PAT
    # has no scopes and inherits its owner's full role, so an admin token would pass
    # any authorisation check. Not registering the tool is the only mechanism that
    # holds.

    @mcp.tool()
    @guard
    def log_time(
        deal_id: str,
        user_id: str,
        data: str,
        ore: HoursArg,
        descrizione: str,
        fatturabile: bool = True,
        tariffa_applicata: OptionalFactor = None,
        costo_applicato: OptionalFactor = None,
        note_interne: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra ore su un deal. `data` in formato YYYY-MM-DD, non futura.

        `deal_id` è obbligatorio e deve essere un id reale: usa prima `search_deals`
        per risolvere il nome del progetto. Questo strumento non crea nulla che non
        trovi -- attribuire ore fatturabili al cliente sbagliato è un errore che
        emerge solo su una fattura.

        La tariffa viene congelata sulla riga al momento della scrittura: chiama
        `describe_rates` per sapere quale si applicherebbe. Se non ne risulta nessuna
        la voce viene registrata comunque, senza tariffa, e comparirà fra le "ore
        senza tariffa".
        """
        return timetracking.log_time(
            context,
            {
                "deal_id": UUID(deal_id),
                "user_id": UUID(user_id),
                "data": data,
                "ore": ore,
                "descrizione": descrizione,
                "fatturabile": fatturabile,
                "tariffa_applicata": tariffa_applicata,
                "costo_applicato": costo_applicato,
                "note_interne": note_interne,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_time_entry(entry_id: str, changes: TimeEntryChanges) -> dict[str, Any]:
        """Aggiorna una voce di ore. Una voce già su una fattura emessa ha ore, data,
        tariffa e descrizione congelate: solo `note_interne` e i campi personalizzati
        restano modificabili."""
        return timetracking.update_time_entry(context, entry_id, changes)

    @mcp.tool()
    @guard
    def delete_time_entry(entry_id: str) -> dict[str, str]:
        """Archivia una voce di ore (reversibile con `restore_time_entry`). Fallisce se
        la voce è legata a una riga di fattura."""
        return timetracking.delete_time_entry(context, entry_id)

    @mcp.tool()
    @guard
    def restore_time_entry(entry_id: str) -> dict[str, Any]:
        """Ripristina una voce di ore archiviata."""
        return timetracking.restore_time_entry(context, entry_id)

    @mcp.tool()
    @guard
    def get_time_entry(entry_id: str) -> dict[str, Any]:
        """Legge una voce di ore, con il valore di riga già calcolato."""
        return timetracking.get_time_entry(context, entry_id)

    @mcp.tool()
    @guard
    def list_time_entries(
        deal_id: str | None = None,
        user_id: str | None = None,
        da: IsoDateStr = None,
        a: IsoDateStr = None,
        fatturabile: bool | None = None,
        fatturato: bool | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Elenca le voci di ore, dalla più recente. `fatturato = false` risponde alla
        domanda "quanto ho da fatturare"."""
        return timetracking.list_time_entries(
            context,
            TimeEntryListQuery(
                deal_id=UUID(deal_id) if deal_id else None,
                user_id=UUID(user_id) if user_id else None,
                da=da,
                a=a,
                fatturabile=fatturabile,
                fatturato=fatturato,
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def get_deal_time_summary(deal_id: str) -> dict[str, Any]:
        """Ore totali, ore da fatturare, valore delle ore non fatturate, costo del
        lavoro e stato del deal. Il ricavo non è qui: il ricavo è la fattura."""
        return timetracking.get_deal_time_summary(context, deal_id)

    @mcp.tool()
    @guard
    def describe_rates(deal_id: str, user_id: str) -> dict[str, Any]:
        """Quale tariffa e quale costo verrebbero congelati su una nuova voce, e da
        quale livello arrivano (`manuale`, `deal`, `utente`, `assente`). Chiamalo prima
        di `log_time`."""
        return timetracking.describe_rates(context, deal_id, user_id)

    @mcp.tool()
    @guard
    def create_cost(
        category_id: str,
        data: str,
        importo: OptionalMoney,
        descrizione: str,
        deal_id: str | None = None,
        fornitore: str | None = None,
        document_id: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra un costo. `deal_id` assente significa spesa generale, che entra nel
        conto economico di periodo e non viene ripartita su nessun deal. `importo` è il
        totale pagato, IVA inclusa; un valore negativo è un rimborso; zero è rifiutato.
        Chiama `list_cost_categories` per le categorie disponibili."""
        return timetracking.create_cost(
            context,
            {
                "category_id": UUID(category_id),
                "data": data,
                "importo": importo,
                "descrizione": descrizione,
                "deal_id": UUID(deal_id) if deal_id else None,
                "fornitore": fornitore,
                "document_id": UUID(document_id) if document_id else None,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_cost(cost_id: str, changes: CostChanges) -> dict[str, Any]:
        """Aggiorna un costo."""
        return timetracking.update_cost(context, cost_id, changes)

    @mcp.tool()
    @guard
    def delete_cost(cost_id: str) -> dict[str, str]:
        """Archivia un costo (reversibile)."""
        return timetracking.delete_cost(context, cost_id)

    @mcp.tool()
    @guard
    def restore_cost(cost_id: str) -> dict[str, Any]:
        """Ripristina un costo archiviato."""
        return timetracking.restore_cost(context, cost_id)

    @mcp.tool()
    @guard
    def get_cost(cost_id: str) -> dict[str, Any]:
        """Legge un costo."""
        return timetracking.get_cost(context, cost_id)

    @mcp.tool()
    @guard
    def list_costs(
        deal_id: str | None = None,
        solo_generali: bool = False,
        category_id: str | None = None,
        da: IsoDateStr = None,
        a: IsoDateStr = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Elenca i costi, dal più recente. `solo_generali = true` mostra solo le spese
        senza deal."""
        return timetracking.list_costs(
            context,
            CostListQuery(
                deal_id=UUID(deal_id) if deal_id else None,
                solo_generali=solo_generali,
                category_id=UUID(category_id) if category_id else None,
                da=da,
                a=a,
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def list_cost_categories(include_archived: bool = False) -> dict[str, Any]:
        """Elenca le categorie di costo configurate. Crearle e archiviarle è
        un'operazione di configurazione e si fa dall'app, non da qui."""
        return timetracking.list_cost_categories(context, include_archived)
```

- [ ] **Step 5: Give `deal://` the hours it needs**

```python
# apps/mcp/src/pigrocrm_mcp/resources/entities.py -- inside render_deal, appended to
# the Markdown it already builds, before the timeline section.
    # Reading before acting (slice 1 §8.4), applied to the one thing an agent wants to
    # know before logging an hour. No revenue figure here on purpose: revenue is the
    # invoice (§3, decision 2), and 4A has no invoices -- printing a zero would read as
    # a real number.
    summary = TimeEntryService(context.session).deal_summary(deal.id, context.actor)
    lines.append("")
    lines.append("## Ore")
    lines.append(f"- Stato: **{summary.stato}**")
    lines.append(f"- Ore consuntivate: {summary.ore_totali}")
    lines.append(f"- Ore fatturabili non ancora fatturate: {summary.ore_fatturabili_non_fatturate}")
    lines.append(f"- Valore delle ore non fatturate (stima): {summary.valore_ore_non_fatturate} EUR")
    if summary.ore_senza_tariffa:
        lines.append(
            f"- Voci senza tariffa: {summary.ore_senza_tariffa} "
            "(escluse dal valore maturato e dal margine)"
        )
    if deal.ore_preventivate is not None:
        lines.append(f"- Ore preventivate: {deal.ore_preventivate}")
```

- [ ] **Step 6: Write the MCP behaviour and concurrency tests**

```python
# apps/mcp/tests/test_timetracking_tools.py
"""`log_time` is the most valuable agentic operation in this product and the safest one:
"Claude, ho fatto tre ore ieri sul progetto Rossi" is the weekly time saving slice 1 §1
makes the criterion of existence for every feature. It is the opposite of
`issue_invoice`: reversible, attributed, and bounded to one deal and one day."""

import pytest

from mcp import Client


async def test_log_time_writes_and_is_attributable_to_the_agent(
    server, seeded_deal_id, seeded_user_id, mcp_session
) -> None:
    async with Client(server) as client:
        created = await client.call_tool(
            "log_time",
            {
                "deal_id": str(seeded_deal_id),
                "user_id": str(seeded_user_id),
                "data": "2026-03-10",
                "ore": 3,
                "descrizione": "Analisi requisiti",
            },
        )
        entry = created.structured_content
        assert entry["ore"] == "3.00"

        timeline = await client.call_tool(
            "get_timeline", {"entity_type": "time_entry", "entity_id": entry["id"]}
        )
        assert timeline.structured_content["entries"][0]["actor_type"] == "mcp"


async def test_the_ten_excluded_tools_do_not_exist(server) -> None:
    """Criterion 9's first half, from the client's own point of view: an agent trying to
    recalculate rates finds no tool to call."""
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    for forbidden in (
        "recalculate_rates",
        "update_user_rates",
        "update_deal_rate",
        "create_cost_category",
        "update_cost_category",
        "archive_cost_category",
        "bind_time_to_invoice",
        "close_period",
        "reopen_period",
        "get_fiscal_estimate",
    ):
        assert forbidden not in names
    assert {"log_time", "describe_rates", "list_cost_categories"} <= names


async def test_a_bad_argument_comes_back_as_guidance_not_a_pydantic_dump(
    server, seeded_deal_id, seeded_user_id
) -> None:
    """Spec §8.2: an LLM that receives a numeric code retries at random; one that
    receives a diagnosis stops or corrects. `HoursArg` keeps the SDK from rejecting the
    value ahead of `_guard`."""
    async with Client(server) as client:
        with pytest.raises(Exception) as excinfo:
            await client.call_tool(
                "log_time",
                {
                    "deal_id": str(seeded_deal_id),
                    "user_id": str(seeded_user_id),
                    "data": "2026-03-10",
                    "ore": "molte",
                    "descrizione": "x",
                },
            )
    assert "errors.pydantic.dev" not in str(excinfo.value)


async def test_the_deal_resource_carries_the_hours_block(
    server, seeded_deal_id, seeded_user_id
) -> None:
    async with Client(server) as client:
        await client.call_tool(
            "log_time",
            {
                "deal_id": str(seeded_deal_id),
                "user_id": str(seeded_user_id),
                "data": "2026-03-10",
                "ore": 8,
                "descrizione": "Sviluppo",
            },
        )
        rendered = (await client.read_resource(f"deal://{seeded_deal_id}")).contents[0].text
    assert "## Ore" in rendered
    assert "Ore consuntivate: 8.00" in rendered
    assert "Stato: **in corso**" in rendered
```

```python
# apps/mcp/tests/test_log_time_concurrency.py
"""Criterion 11. Twenty simultaneous `log_time` calls against real Postgres produce
twenty rows and twenty activities with no session error. It is residual R1 closed, and
it is the condition on which this tool exists at all -- Task 4A-1 is what makes it
pass, and this is the test that proves the fix reached the tool rather than only the
provider."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from sqlalchemy import Engine, text

from pigrocrm.core.actor import Actor
from pigrocrm.core.db import session_factory
from pigrocrm_mcp.context import McpContext, ScopedSessionProvider
from pigrocrm_mcp.tools import timetracking

CONCURRENCY = 20


def test_twenty_concurrent_log_time_calls_produce_twenty_rows(
    mcp_engine: Engine, mcp_storage, seeded_deal_id, seeded_user_id
) -> None:
    provider = ScopedSessionProvider(session_factory(mcp_engine))
    actor = Actor(id=seeded_user_id, type="mcp", role="collaboratore")
    context = McpContext(provider, lambda: actor, mcp_storage)
    barrier = threading.Barrier(CONCURRENCY)

    def write(index: int) -> str:
        barrier.wait(timeout=30)
        with provider.scope():
            return timetracking.log_time(
                context,
                {
                    "deal_id": seeded_deal_id,
                    "user_id": seeded_user_id,
                    "data": date(2026, 3, 10),
                    "ore": "1.00",
                    "descrizione": f"Voce {index}",
                },
            )["id"]

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        ids = list(pool.map(write, range(CONCURRENCY)))

    assert len(set(ids)) == CONCURRENCY
    with session_factory(mcp_engine)() as check:
        rows = check.execute(
            text("SELECT count(*) FROM time_entries WHERE deal_id = :deal"),
            {"deal": seeded_deal_id},
        ).scalar_one()
        activities = check.execute(
            text(
                "SELECT count(*) FROM activities "
                "WHERE entity_type = 'time_entry' AND kind = 'created' "
                "  AND actor_type = 'mcp'"
            )
        ).scalar_one()
    assert rows == CONCURRENCY
    assert activities == CONCURRENCY
```

- [ ] **Step 7: Run all three suites**

Run: `uv run pytest packages/core/tests/test_architecture.py apps/mcp -v`
Expected: PASS, including `test_every_other_public_method_has_a_tool`.

- [ ] **Step 8: Commit**

```bash
git add packages/core apps/mcp
git commit -m "feat(mcp): log_time and the time-tracking tools, with the ten-method ban in the build"
```

---

## Phase 4A-5 — The timesheet, in two formats

### Task 4A-14: The `rapporto_ore` template and its PDF

**Files:**
- Create: `packages/core/src/pigrocrm/core/render/assets/template-time-report.md`
- Create: `packages/core/src/pigrocrm/core/timetracking/report.py`
- Modify: `packages/core/src/pigrocrm/core/templates/service.py` (add `seed_defaults`, keeping `list` last)
- Modify: `packages/core/src/pigrocrm/core/cli.py` (add `seed-templates`)
- Test: `packages/core/tests/test_time_report_pdf.py`

**Interfaces:**
- Consumes (all shipped slice-2 code, read directly rather than from its spec): `DocumentService.create_from_template(data: DocumentFromTemplate, actor: Actor) -> DocumentRead`; `DocumentFromTemplate(template_id, titolo, customer_id, deal_id, variabili, custom_fields)`; `TemplateService.repo.get(template_id) -> Template | None`; `render_template(source, values, declared=()) -> str`; `escape_for(context, value)`; `build_header(profile) -> str`; `render_pdf(markdown, *, header_typst, settings) -> bytes`; `EmitterService.as_template_values(actor) -> dict[str, Any]`; `TimeEntryRepository.for_month(deal_id, anno, mese)`; `to_read(entry)` (4A-9); `month_bounds(anno, mese)` (4A-9); `period_label(anno, mese)` (4A-8).
- Produces:
  ```python
  PERIOD_KEY_RE: re.Pattern[str]     # fullmatch on r"(\d{4})-(0[1-9]|1[0-2])"
  TIME_REPORT_TEMPLATE_NOME = "Rapporto ore"

  def parse_period(mese: str) -> tuple[int, int]        # "2026-03" -> (2026, 3)
  def report_variables(entries, *, anno, mese, deal, customer) -> dict[str, Any]

  class TimeReportService:
      def __init__(self, session: Session, storage: DocumentStorage) -> None
      def render_pdf(self, deal_id: UUID, mese: str, actor: Actor) -> DocumentRead
      def build_xlsx(self, deal_id: UUID, mese: str, actor: Actor) -> tuple[str, bytes]   # Task 4A-15

  # TemplateService gains:
  def seed_defaults(self, actor: Actor) -> list[TemplateRead]
  ```

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_time_report_pdf.py
"""Criterion 10, PDF half. The report is a document produced by the slice 2 pipeline,
not a string built by concatenating Typst source in Python -- which is what the previous system did
(`[ENTRIES_PLACEHOLDER]` filled by string concatenation) and is why its descriptions
arrived at clients double-escaped."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.service import TemplateService
from pigrocrm.core.timetracking.report import (
    TIME_REPORT_TEMPLATE_NOME,
    TimeReportService,
    parse_period,
    report_variables,
)
from pigrocrm.core.timetracking.schemas import TimeEntryCreate
from pigrocrm.core.timetracking.service import TimeEntryService

ADMIN = Actor(id=None, type="system", role="admin")
WRITER = Actor(id=None, type="user", role="collaboratore")

HOSTILE = 'Call con @mario su [fase 1] & #2 — "urgente"\nseconda riga'

ASSETS = (
    Path(__file__).resolve().parents[1]
    / "src" / "pigrocrm" / "core" / "render" / "assets"
)


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "202603", "2026-3", "2026-03\n", ""])
def test_a_malformed_period_is_refused(bad: str) -> None:
    """`re.fullmatch`, never `re.match` with `$`: `$` matches before a trailing newline,
    so `"2026-03\\n"` would slip through a `$`-anchored pattern and reach the query as a
    value nobody validated. The standing project rule, on a pattern that touches no
    database column at all -- the habit is what protects the ones that do."""
    with pytest.raises(ValidationFailed):
        parse_period(bad)


def test_a_well_formed_period_parses() -> None:
    assert parse_period("2026-03") == (2026, 3)


def test_the_seeded_template_exists_and_names_no_freelancer(db_session: Session) -> None:
    """Criterion 10's last clause: a grep over the template sources finds no
    freelancer's name. Every identity value is `{{emittente.*}}`, read from
    `emitter_profile`."""
    created = TemplateService(db_session).seed_defaults(ADMIN)
    assert [t.nome for t in created] == [TIME_REPORT_TEMPLATE_NOME]
    assert created[0].tipo == "rapporto_ore"
    # Idempotent, deduplicating case-insensitively on `nome` to match uq_templates_nome.
    assert TemplateService(db_session).seed_defaults(ADMIN) == []

    body = (ASSETS / "template-time-report.md").read_text(encoding="utf-8")
    header = (ASSETS / "header.typ.template").read_text(encoding="utf-8")
    for source in (body, header):
        assert "humancraft" not in source.lower()
        assert "ivansala" not in source.lower()
        assert not re.search(r"P\.IVA\s+\d{11}", source)
    # The carried-over layout, asserted where it is expressible as text.
    assert "0.7fr" in body
    assert "DATA" in body and "ORE" in body and "DESCRIZIONE" in body
    assert "{{#each voci}}" in body
    assert "{{totale_ore}}" in body and "{{numero_voci}}" in body


def test_report_variables_carry_raw_values_and_a_finished_total(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The service hands the template finished figures and raw text: the total is
    already summed (§6 forbids arithmetic downstream) and the description is unescaped,
    because `escape_for` prepares it once, at render, for the context it lands in."""
    service = TimeEntryService(db_session)
    service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
            ore=Decimal("2.50"), descrizione=HOSTILE,
        ),
        WRITER,
    )
    service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 20),
            ore=Decimal("1.25"), descrizione="Revisione",
        ),
        WRITER,
    )
    # An entry in the next month must not appear.
    service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 4, 1),
            ore=Decimal("8.00"), descrizione="Aprile",
        ),
        WRITER,
    )

    report = TimeReportService(db_session, storage=None)
    variables = report.variables_for(seeded_deal_id, "2026-03", WRITER)
    assert variables["periodo"] == "marzo 2026"
    assert variables["totale_ore"] == "3.75"
    assert variables["numero_voci"] == "2"
    assert [v["data"] for v in variables["voci"]] == ["04/03/2026", "20/03/2026"]
    assert variables["voci"][0]["descrizione"] == HOSTILE
    assert variables["voci"][0]["ore"] == "2.50"


def test_the_pdf_renders_and_contains_the_hostile_description_verbatim(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, local_storage
) -> None:
    """Renders through Pandoc and Typst for real, then reads the text back out of the
    produced PDF. The assertion is on the round trip, because the whole point is that
    the value reaches the page as the literal text somebody typed."""
    TemplateService(db_session).seed_defaults(ADMIN)
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
            ore=Decimal("2.50"), descrizione=HOSTILE,
        ),
        WRITER,
    )
    document = TimeReportService(db_session, local_storage).render_pdf(
        seeded_deal_id, "2026-03", WRITER
    )
    assert document.tipo == "rapporto_ore"
    assert document.deal_id == seeded_deal_id
    assert document.versione_corrente == 1

    text = extract_pdf_text(local_storage, db_session, document.id)
    # Newlines and layout break lines unpredictably in a PDF, so each fragment is
    # asserted on its own -- the escaping bug this guards against corrupts characters,
    # not line breaks.
    for fragment in ("@mario", "[fase 1]", "#2", '"urgente"', "seconda riga"):
        assert fragment in text, fragment
    assert "\\@mario" not in text and "\\[fase 1\\]" not in text
    assert "Totale ore" in text and "3,75" not in text  # the PDF prints 2.50 for one entry
```

Add the two helpers the test uses to `packages/core/tests/conftest.py`:

```python
# packages/core/tests/conftest.py (append)
import subprocess
from uuid import UUID

import pytest

from pigrocrm.core.storage.local import LocalFileStorage


@pytest.fixture
def local_storage(tmp_path) -> LocalFileStorage:
    """A tmp-dir backend, never the default `./var/documents` root -- a test must not
    write real files into this repository's working tree."""
    return LocalFileStorage(str(tmp_path / "documents"))


def extract_pdf_text(storage, session, document_id: UUID) -> str:
    """Reads the stored PDF back and extracts its text with `pdftotext`, which ships in
    the same API image as Pandoc and Typst. Reading the produced artefact rather than
    the intermediate Markdown is the only assertion that proves what the client
    actually receives."""
    from pigrocrm.core.documents.repository import DocumentRepository

    version = DocumentRepository(session).version(document_id, 1)
    assert version is not None
    data = storage.get(version.storage_key)
    result = subprocess.run(
        ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
    )
    return result.stdout.decode("utf-8", errors="replace")
```

`pdftotext` comes from `poppler-utils`. Add it to `Dockerfile.api`'s existing `apt-get install` line in this task, next to the Pandoc and Typst installation — the test suite runs in that image in CI.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_time_report_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.timetracking.report'`.

- [ ] **Step 3: Write the template asset**

```markdown
<!-- packages/core/src/pigrocrm/core/render/assets/template-time-report.md

The layout carried over from `.reference-*/offer/template-time-tracking.typ`. What
is carried is the knowledge: the "Periodo / Data emissione" line, the Cliente + Offerta
block, a three-column DATA · ORE · DESCRIZIONE table with the description at 0.7fr
because it is the only column the client actually reads, the thin divider, and a footer
pairing the total hours with the **entry count** -- the detail that makes the document
verifiable at a glance.

What is deliberately NOT carried is the identity block the previous system drew inline as its first
`#grid` with `header: none`. This product renders `header.typ.template` from
`emitter_profile` through `--include-in-header` for every document, and that header
already places the logo left and the issuer's identity right. Redrawing it here would
put it on the page twice.

Also not carried: `[ENTRIES_PLACEHOLDER]`, which the previous system filled by concatenating Typst
source in JavaScript. It is `{{#each voci}}` here, so every value passes through
`escape_for` exactly once, in the context it lands in.
-->

```{=typst}
#v(0.4cm)
#text(size: 16pt, weight: "bold")[Rapporto ore]
#v(0.15cm)
#text(size: 9pt)[Periodo: {{periodo}} · Data emissione: {{oggi}}]
#v(0.35cm)
#line(length: 100%, stroke: 0.6pt + luma(180))
#v(0.35cm)
#grid(
  columns: (1fr, 1fr),
  column-gutter: 0.6cm,
  [
    #text(size: 8pt, fill: luma(110))[CLIENTE] \
    #text(size: 10pt, weight: "bold")[{{cliente.ragione_sociale}}] \
    #text(size: 9pt)[{{cliente.partita_iva}}]
  ],
  [
    #text(size: 8pt, fill: luma(110))[OFFERTA] \
    #text(size: 10pt, weight: "bold")[{{deal.nome}}]
  ],
)
#v(0.5cm)
#table(
  columns: (0.18fr, 0.12fr, 0.7fr),
  align: (left, right, left),
  stroke: none,
  table.header(
    [#text(size: 8pt, fill: luma(110))[DATA]],
    [#text(size: 8pt, fill: luma(110))[ORE]],
    [#text(size: 8pt, fill: luma(110))[DESCRIZIONE]],
  ),
  {{#each voci}}[{{data}}], [{{ore}}], [{{descrizione}}],{{/each}}
)
#v(0.35cm)
#line(length: 100%, stroke: 0.6pt + luma(180))
#v(0.25cm)
#grid(
  columns: (1fr, auto),
  [#text(size: 9pt, fill: luma(110))[{{numero_voci}} voci]],
  [#text(size: 11pt, weight: "bold")[Totale ore: {{totale_ore}}]],
)
```
```

- [ ] **Step 4: Add `TemplateService.seed_defaults`**

```python
# packages/core/src/pigrocrm/core/templates/service.py -- inserted BEFORE the existing
# `list` method, which must stay the last method in the class.

    def seed_defaults(self, actor: Actor) -> list[TemplateRead]:
        """Seeds the built-in templates that ship as assets, idempotently.

        On `PipelineService.seed_defaults`'s model, and deduplicating on `lower(nome)`
        to match `uq_templates_nome`'s own functional index -- a case-sensitive check
        would pass for "rapporto ore" against a stored "Rapporto ore" and then be
        refused by the database as a raw `IntegrityError`.

        Seeds exactly one template today: the timesheet. `render/assets/
        template-offer.md` is deliberately left alone -- adopting it would change slice
        2's shipped behaviour in a slice that is not about offers.

        Returns only what it actually created, so a caller can tell "seeded" from
        "already there".
        """
        from pigrocrm.core.timetracking.report import (  # local: avoids a package cycle
            TIME_REPORT_TEMPLATE_NOME,
            TIME_REPORT_TEMPLATE_VARIABLES,
        )

        seeds = (
            (
                TIME_REPORT_TEMPLATE_NOME,
                "rapporto_ore",
                (ASSETS_DIR / "template-time-report.md").read_text(encoding="utf-8"),
                TIME_REPORT_TEMPLATE_VARIABLES,
            ),
        )
        created: list[TemplateRead] = []
        for nome, tipo, corpo, variabili in seeds:
            if self.repo.get_by_nome(nome) is not None:
                continue
            template = self.repo.add(
                Template(
                    nome=nome,
                    tipo=tipo,
                    corpo_markdown=corpo,
                    variabili_dichiarate=list(variabili),
                    attivo=True,
                )
            )
            self.activities.record(
                "template", template.id, "created", actor, {"nome": nome, "seed": True}
            )
            created.append(TemplateRead.model_validate(template))
        self.session.commit()
        return created
```

`ASSETS_DIR` is already exported by `pigrocrm.core.render.pdf`; import it at the top of `templates/service.py` as `from pigrocrm.core.render.pdf import ASSETS_DIR`. If `TemplateRepository` has no `get_by_nome`, add it beside `get`, matching `CostCategoryRepository.get_by_nome`'s case-insensitive form exactly:

```python
# packages/core/src/pigrocrm/core/templates/repository.py -- add beside `get`.
    def get_by_nome(self, nome: str) -> Template | None:
        """Case-insensitive, matching `uq_templates_nome`'s functional index."""
        return self.session.execute(
            select(Template).where(func.lower(Template.nome) == nome.strip().lower())
        ).scalar_one_or_none()
```

- [ ] **Step 5: Write the report service**

```python
# packages/core/src/pigrocrm/core/timetracking/report.py
"""The timesheet: one set of figures, two formats.

Two formats for the same data is not redundancy -- they are two recipients with two
needs. The PDF is attached to the invoice; the XLSX gets filtered by whoever has to
check it (§2.1). Both read the same `variables_for`, so the two documents can never
disagree about a total.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.repository import CustomerRepository
from pigrocrm.core.customers.schemas import CustomerRead
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.schemas import DocumentFromTemplate, DocumentRead
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.money import sum_hours
from pigrocrm.core.storage import DocumentStorage
from pigrocrm.core.templates.service import TemplateService
from pigrocrm.core.timetracking.locks import period_label
from pigrocrm.core.timetracking.repository import TimeEntryRepository

ENTITY = "time_report"

TIME_REPORT_TEMPLATE_NOME = "Rapporto ore"

# Declared for the compilation form (slice 2 §4.3). `voci` is deliberately not
# declared: it is supplied by the service on every render, never typed by a human, and
# `render_template` accepts undeclared supplied keys -- `{{#each voci}}` resolves from
# `values`. Declaring it would put a list-typed variable on a form nobody fills in.
TIME_REPORT_TEMPLATE_VARIABLES: tuple[dict[str, Any], ...] = (
    {"nome": "periodo", "etichetta": "Periodo", "tipo": "text", "obbligatoria": True},
    {"nome": "totale_ore", "etichetta": "Totale ore", "tipo": "number", "obbligatoria": True},
    {"nome": "numero_voci", "etichetta": "Numero voci", "tipo": "number", "obbligatoria": True},
)

# `re.fullmatch` is what this is used with -- never `re.match` with `$`, because `$`
# matches before a trailing newline and `"2026-03\n"` would slip through. The month
# alternation, rather than `\d{2}`, is what makes `2026-13` and `2026-00` unrepresentable
# instead of merely rejected later by `date()`.
PERIOD_KEY_RE = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")


def parse_period(mese: str) -> tuple[int, int]:
    """`"2026-03"` -> `(2026, 3)`. The `AAAA-MM` key carried over from the previous system: the
    monthly cut is what a client expects next to an invoice, and it is what gets agreed
    on."""
    match = PERIOD_KEY_RE.fullmatch(mese)
    if match is None:
        raise ValidationFailed(
            ENTITY, "mese", "periodo non valido", expected="un periodo nella forma AAAA-MM"
        )
    return int(match.group(1)), int(match.group(2))


def _italian_date(giorno: date) -> str:
    """`dd/mm/yyyy`, formatted from the `Date`'s own parts.

    Never through an instant and never through `toISOString()`-shaped arithmetic:
    The previous system's `formatIsoDate` projected a timestamp to UTC, so an hour logged at 23:30
    CEST on 31 March was stored -- and printed -- as 1 April, landing in the wrong
    monthly export, which is the file attached to an invoice.
    """
    return f"{giorno.day:02d}/{giorno.month:02d}/{giorno.year}"


class TimeReportService:
    def __init__(self, session: Session, storage: DocumentStorage | None) -> None:
        self.session = session
        self.storage = storage
        self.entries = TimeEntryRepository(session)
        self.deals = DealRepository(session)
        self.customers = CustomerRepository(session)
        self.templates = TemplateService(session)

    def variables_for(self, deal_id: UUID, mese: str, actor: Actor) -> dict[str, Any]:
        """Everything both formats need, computed once.

        Every figure arrives finished: `totale_ore` is already summed with `sum_hours`,
        so neither the template nor the workbook adds anything. The previous system accumulated hours
        as binary floats (`sum + entry.hours`) and printed a total that was a binary sum
        rounded at the end.

        `descrizione` is handed over **raw** -- multi-line, unescaped. `escape_for`
        (slice 2) prepares it at render, once, for the context it lands in; the XLSX
        passes it through no escaper at all, because a cell value is not markup.
        """
        anno, numero_mese = parse_period(mese)
        deal = self.deals.get(deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)
        customer = self.customers.get(deal.customer_id)
        rows = self.entries.for_month(deal_id, anno, numero_mese)
        return {
            "periodo": period_label(anno, numero_mese),
            "oggi": _italian_date(date.today()),
            "deal": {"nome": deal.nome},
            "cliente": (
                CustomerRead.model_validate(customer).model_dump(mode="json") if customer else {}
            ),
            "voci": [
                {
                    "data": _italian_date(entry.data),
                    # `str(Decimal)` keeps the stored scale exactly ("2.50", not "2.5"):
                    # the column the client reads must show two places, and formatting
                    # a float here would be the drift `Numeric` exists to avoid.
                    "ore": str(entry.ore),
                    "descrizione": entry.descrizione,
                }
                for entry in rows
            ],
            "totale_ore": str(sum_hours([entry.ore for entry in rows])),
            "numero_voci": str(len(rows)),
            # Kept as native types for the workbook, which needs real dates and real
            # numbers rather than the display strings above (Task 4A-15).
            "_rows": [(entry.data, entry.ore, entry.descrizione) for entry in rows],
            "_anno": anno,
            "_mese": numero_mese,
        }

    def render_pdf(self, deal_id: UUID, mese: str, actor: Actor) -> DocumentRead:
        """Archived as a `document` of type `rapporto_ore` on the deal, through the
        slice 2 pipeline unchanged -- so it gets the versioning, the hash, the pluggable
        storage and the timeline that already work, and a regenerated report is a new
        version rather than a silent overwrite."""
        variables = self.variables_for(deal_id, mese, actor)
        template = self.templates.repo.get_by_nome(TIME_REPORT_TEMPLATE_NOME)
        if template is None:
            raise ValidationFailed(
                ENTITY,
                "template",
                f"il template «{TIME_REPORT_TEMPLATE_NOME}» non esiste",
                expected="esegui `pigrocrm seed-templates`",
            )
        if self.storage is None:
            raise ValidationFailed(
                ENTITY, "storage", "nessun backend di storage configurato", expected="uno storage"
            )
        public = {k: v for k, v in variables.items() if not k.startswith("_")}
        return DocumentService(self.session, self.storage).create_from_template(
            DocumentFromTemplate(
                template_id=template.id,
                titolo=f"Rapporto ore {variables['periodo']}",
                customer_id=None,
                deal_id=deal_id,
                variabili=public,
            ),
            actor,
        )

    def build_xlsx(self, deal_id: UUID, mese: str, actor: Actor) -> tuple[str, bytes]:
        """Implemented in Task 4A-15. Declared here so the class's surface is complete."""
        raise NotImplementedError
```

- [ ] **Step 6: Add the CLI subcommand**

```python
# packages/core/src/pigrocrm/core/cli.py -- add the subparser and the branch.
def seed_templates() -> int:
    """`pigrocrm seed-templates`. Idempotent, so it is safe on every deploy -- which is
    the point: the timesheet template has to exist before anyone presses Scarica, and
    requiring a manual step there is how a feature ships broken."""
    from pigrocrm.core.actor import Actor
    from pigrocrm.core.config import get_settings
    from pigrocrm.core.db import create_engine_from_settings, session_factory
    from pigrocrm.core.templates.service import TemplateService

    with session_factory(create_engine_from_settings(get_settings()))() as session:
        created = TemplateService(session).seed_defaults(Actor.system())
    for template in created:
        print(f"creato: {template.nome} ({template.tipo})")
    if not created:
        print("nessun template da creare: sono già presenti")
    return 0


# ... in main(), beside the existing `createadmin` subparser:
    sub.add_parser("seed-templates", help="Crea i template predefiniti, se mancano")

# ... and in the dispatch:
    if args.command == "seed-templates":
        return seed_templates()
```

- [ ] **Step 7: Run the test**

Run: `uv run pytest packages/core/tests/test_time_report_pdf.py -v`
Expected: PASS. Then `uv run pytest packages/core -q` to confirm `test_module_imports.py` still passes — `TemplateService.seed_defaults` was inserted before `list`, and putting it after would break the class at import.

- [ ] **Step 8: Commit**

```bash
git add packages/core Dockerfile.api
git commit -m "feat(timetracking): the rapporto ore PDF, through the slice 2 template pipeline"
```

---

### Task 4A-15: The XLSX export

**Files:**
- Create: `packages/core/src/pigrocrm/core/timetracking/xlsx.py`
- Modify: `packages/core/src/pigrocrm/core/timetracking/report.py` (implement `build_xlsx`)
- Modify: `packages/core/pyproject.toml` (`openpyxl==3.1.5`)
- Modify: `apps/api/src/pigrocrm_api/routers/deals.py` (`GET /api/deals/{deal_id}/time-report`)
- Test: `packages/core/tests/test_time_report_xlsx.py`

**Interfaces:**
- Consumes: `TimeReportService.variables_for(deal_id, mese, actor) -> dict[str, Any]` (its `_rows`, `_anno`, `_mese` keys carry native `date`/`Decimal` values); `openpyxl.Workbook`.
- Produces:
  ```python
  HEADER_FILL_ARGB = "FFD9D9D9"
  COLUMN_WIDTHS = (14, 10, 80)
  FREEZE_PANES = "A6"        # ySplit: 5

  def build_time_report_xlsx(
      *,
      cliente: str,
      offerta: str,
      periodo: str,
      rows: Sequence[tuple[date, Decimal, str]],
  ) -> bytes

  # TimeReportService gains the real body of:
  def build_xlsx(self, deal_id: UUID, mese: str, actor: Actor) -> tuple[str, bytes]
  ```
  `build_time_report_xlsx` is a pure function taking only primitives — no session, no ORM — so the sheet shape is provable on its own, which is exactly why it is a separate module from `report.py`.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_time_report_xlsx.py
"""Criterion 10, XLSX half. The **shape** of the sheet is carried over from the previous system's
`buildTimeTrackingXlsx`; the `exceljs` code that produced it is not, because it was a
JavaScript library inside a Node dev server this product no longer has.

Three things are rewritten rather than carried, and each is asserted below: hours and
amounts are written as **numbers** with a `number_format` instead of pre-formatted
strings; the date is written as a **date**; and the total is a `SUBTOTAL(109; ...)`
**formula**, not a constant -- whoever receives a timesheet filters it, and a constant
total after a filter contradicts the column above it, which is exactly §6.2's principle
applied to a spreadsheet.
"""

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from pigrocrm.core.timetracking.xlsx import build_time_report_xlsx

HOSTILE = 'Call con @mario su [fase 1] & #2 — "urgente"\nseconda riga'

ROWS = [
    (date(2026, 3, 4), Decimal("2.50"), HOSTILE),
    (date(2026, 3, 20), Decimal("1.25"), "Revisione"),
]


def _sheet(**overrides):
    payload = {
        "cliente": "Rossi & C. S.r.l.",
        "offerta": "Progetto Alfa",
        "periodo": "marzo 2026",
        "rows": ROWS,
    }
    payload.update(overrides)
    return load_workbook(BytesIO(build_time_report_xlsx(**payload))).active


def test_the_four_row_header_block_and_the_bold_grey_header_row() -> None:
    sheet = _sheet()
    assert sheet["A1"].value == "Rapporto ore"
    assert sheet["A2"].value == "Cliente" and sheet["B2"].value == "Rossi & C. S.r.l."
    assert sheet["A3"].value == "Offerta" and sheet["B3"].value == "Progetto Alfa"
    assert sheet["A4"].value == "Periodo" and sheet["B4"].value == "marzo 2026"
    assert {str(r) for r in sheet.merged_cells.ranges} >= {"A1:C1", "B2:C2", "B3:C3", "B4:C4"}

    for column, label in zip("ABC", ("DATA", "ORE", "DESCRIZIONE"), strict=True):
        cell = sheet[f"{column}5"]
        assert cell.value == label
        assert cell.font.bold is True
        assert cell.fill.fgColor.rgb == "FFD9D9D9"


def test_the_frozen_pane_and_the_carried_over_column_widths() -> None:
    """`ySplit: 5` and widths 14 / 10 / 80. Not deducible from any specification: they
    are what makes the file *usable* rather than merely correct, tuned by years of
    somebody scrolling and filtering it."""
    sheet = _sheet()
    assert sheet.freeze_panes == "A6"
    assert sheet.column_dimensions["A"].width == 14
    assert sheet.column_dimensions["B"].width == 10
    assert sheet.column_dimensions["C"].width == 80


def test_dates_are_dates_and_hours_are_numbers_with_their_format() -> None:
    sheet = _sheet()
    assert isinstance(sheet["A6"].value, (date, datetime))
    assert sheet["A6"].number_format == "dd/mm/yyyy"
    # A real number, not a string: a text cell cannot be summed, filtered numerically,
    # or charted, and that is what the previous system's pre-formatted strings cost.
    assert sheet["B6"].value == Decimal("2.50") or float(sheet["B6"].value) == 2.5
    assert not isinstance(sheet["B6"].value, str)
    assert sheet["B6"].number_format == "0.00"
    assert sheet["C6"].alignment.wrap_text is True


def test_the_description_arrives_verbatim_with_its_newline_and_no_escaping() -> None:
    """The previous system stored the description already escaped for Typst and wrote that same string
    into the cell (`vite.config.js:1245`), so a client opened the spreadsheet and read
    `Call con \\@mario su \\[fase 1\\]`. Nothing here escapes anything: a cell value is
    not markup."""
    sheet = _sheet()
    assert sheet["C6"].value == HOSTILE
    assert "\\@" not in sheet["C6"].value
    assert "\n" in sheet["C6"].value


def test_the_total_is_a_subtotal_formula_not_a_constant() -> None:
    sheet = _sheet()
    total_row = 5 + len(ROWS) + 1
    assert sheet[f"A{total_row}"].value == "Totale ore"
    assert sheet[f"A{total_row}"].font.bold is True
    assert sheet[f"B{total_row}"].value == f"=SUBTOTAL(109,B6:B{5 + len(ROWS)})"
    assert sheet[f"B{total_row}"].number_format == "0.00"
    assert sheet[f"B{total_row}"].font.bold is True


def test_an_empty_month_still_produces_a_valid_sheet() -> None:
    """A month with no hours is a real answer, not an error: the header block, the
    column headers and a zero-row total all have to survive an empty range."""
    sheet = _sheet(rows=[])
    assert sheet["A5"].value == "DATA"
    assert sheet["A6"].value == "Totale ore"
    assert sheet["B6"].value == "=SUBTOTAL(109,B6:B5)"


def test_the_autofilter_covers_the_data_rows_only() -> None:
    """The filter must not include the total row, or filtering hides the total it is
    supposed to update."""
    sheet = _sheet()
    assert sheet.auto_filter.ref == f"A5:C{5 + len(ROWS)}"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_time_report_xlsx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'openpyxl'`.

- [ ] **Step 3: Declare the dependency**

```toml
# packages/core/pyproject.toml -- append to [project].dependencies.
  # The XLSX writer. Declared on **core**, not on apps/api, because
  # packages/core/tests/test_architecture.py derives its import allowlist from this
  # list and the workbook builder is a domain function -- the API image installs
  # core's dependencies anyway, which is what the spec's "nell'immagine dell'API"
  # means in practice. The architecture test resolves this entry to the module root
  # `openpyxl` with no override needed.
  "openpyxl==3.1.5",
```

Run: `uv lock && uv sync`
If `uv` resolves a different version, update the pin in this same commit rather than leaving the two out of step.

- [ ] **Step 4: Write the workbook builder**

```python
# packages/core/src/pigrocrm/core/timetracking/xlsx.py
"""The timesheet as a spreadsheet.

The **shape** of this sheet is carried over from the previous system's `buildTimeTrackingXlsx`
(`.reference-*/website/vite.config.js`): a four-row header block with merged cells,
a bold header row on a grey fill, a frozen pane below it, and widths 14 / 10 / 80. None
of that is deducible from a specification -- it is what makes the file usable rather
than merely correct, tuned by years of somebody actually scrolling and filtering it.
The `exceljs` code that produced it is not carried: it was a JavaScript library inside a
Node dev server this product no longer has.

Three things are rewritten:
  * hours are **numbers** with a `number_format`, not pre-formatted strings -- a text
    cell cannot be summed, filtered numerically or charted;
  * the date is a **date**, not a string;
  * the total is a `SUBTOTAL(109, ...)` **formula**, not a constant. Whoever receives a
    timesheet filters it, and a constant total after a filter contradicts the column
    above it -- §6.2's principle ("the printed rows win") applied to a spreadsheet.

Nothing in this module escapes anything. A cell value is not markup, so the description
passes through no escaper at all -- which is the whole point: the previous system stored it already
escaped for Typst and wrote that same string into the cell, so clients read
`Call con \\@mario su \\[fase 1\\]` in their spreadsheet.

Pure: primitives in, bytes out, no session and no ORM, so the sheet shape is provable
on its own.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SHEET_TITLE = "Rapporto ore"
HEADER_FILL_ARGB = "FFD9D9D9"
COLUMN_WIDTHS = (14, 10, 80)
HEADER_ROW = 5
FIRST_DATA_ROW = HEADER_ROW + 1
# `ySplit: 5` in exceljs terms: everything above row 6 stays put while the entries
# scroll.
FREEZE_PANES = f"A{FIRST_DATA_ROW}"
DATE_FORMAT = "dd/mm/yyyy"
HOURS_FORMAT = "0.00"
COLUMN_HEADERS = ("DATA", "ORE", "DESCRIZIONE")


def build_time_report_xlsx(
    *,
    cliente: str,
    offerta: str,
    periodo: str,
    rows: Sequence[tuple[date, Decimal, str]],
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE

    bold = Font(bold=True)
    grey = PatternFill(start_color=HEADER_FILL_ARGB, end_color=HEADER_FILL_ARGB, fill_type="solid")

    sheet["A1"] = SHEET_TITLE
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.merge_cells("A1:C1")
    for row, (label, value) in enumerate(
        (("Cliente", cliente), ("Offerta", offerta), ("Periodo", periodo)), start=2
    ):
        sheet[f"A{row}"] = label
        sheet[f"A{row}"].font = bold
        sheet[f"B{row}"] = value
        sheet.merge_cells(f"B{row}:C{row}")

    for index, header in enumerate(COLUMN_HEADERS, start=1):
        cell = sheet.cell(row=HEADER_ROW, column=index, value=header)
        cell.font = bold
        cell.fill = grey

    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    for offset, (giorno, ore, descrizione) in enumerate(rows):
        row = FIRST_DATA_ROW + offset
        data_cell = sheet.cell(row=row, column=1, value=giorno)
        data_cell.number_format = DATE_FORMAT
        # `Decimal` handed to openpyxl unchanged: it writes it as a numeric cell, so no
        # float ever exists on this path. Converting to `float` here would reintroduce
        # exactly the drift `Numeric(8,2)` exists to avoid.
        ore_cell = sheet.cell(row=row, column=2, value=ore)
        ore_cell.number_format = HOURS_FORMAT
        # Raw, unescaped, newlines intact. `wrap_text` is what makes a multi-line
        # description readable in the 80-wide column instead of a single clipped line.
        descrizione_cell = sheet.cell(row=row, column=3, value=descrizione)
        descrizione_cell.alignment = Alignment(wrap_text=True, vertical="top")

    last_data_row = HEADER_ROW + len(rows)
    total_row = last_data_row + 1
    label_cell = sheet.cell(row=total_row, column=1, value="Totale ore")
    label_cell.font = bold
    # 109 is SUM-ignoring-hidden-rows: the total follows the filter, so it never
    # contradicts the visible column. A constant here is the spreadsheet form of the
    # defect §6.2 rules out.
    total_cell = sheet.cell(
        row=total_row,
        column=2,
        value=f"=SUBTOTAL(109,B{FIRST_DATA_ROW}:B{last_data_row})",
    )
    total_cell.font = bold
    total_cell.number_format = HOURS_FORMAT

    # The header row plus the data rows only -- never the total row, or filtering would
    # hide the very total it is supposed to update.
    sheet.auto_filter.ref = f"A{HEADER_ROW}:C{last_data_row}"
    sheet.freeze_panes = FREEZE_PANES

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 5: Implement `build_xlsx` and the download endpoint**

```python
# packages/core/src/pigrocrm/core/timetracking/report.py -- replacing the stub.
    def build_xlsx(self, deal_id: UUID, mese: str, actor: Actor) -> tuple[str, bytes]:
        """Returns `(filename, bytes)`.

        Not archived as a `document`, unlike the PDF, and that asymmetry is deliberate:
        the PDF is the artefact attached to an invoice and therefore has to be
        reproducible byte for byte a year later, which is what `document_versions` and
        its hash exist for. The XLSX is a working copy somebody filters -- it is
        regenerated from the same `variables_for` on every request, so it can never
        drift from the PDF, and storing versions of it would archive scratch paper.
        """
        variables = self.variables_for(deal_id, mese, actor)
        from pigrocrm.core.timetracking.xlsx import build_time_report_xlsx

        content = build_time_report_xlsx(
            cliente=str(variables["cliente"].get("ragione_sociale", "")),
            offerta=str(variables["deal"]["nome"]),
            periodo=str(variables["periodo"]),
            rows=variables["_rows"],
        )
        return f"rapporto-ore-{variables['_anno']}-{variables['_mese']:02d}.xlsx", content
```

```python
# apps/api/src/pigrocrm_api/routers/deals.py -- append, with the imports.
from typing import Literal

from fastapi import Response

from pigrocrm.core.timetracking.report import TimeReportService
from pigrocrm_api.deps import StorageDep

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/{deal_id}/time-report")
def time_report(
    deal_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    storage: StorageDep,
    mese: Annotated[str, Query(description="Periodo nella forma AAAA-MM")],
    formato: Annotated[Literal["pdf", "xlsx"], Query()] = "pdf",
) -> Response:
    """Two recipients, two needs (§2.1): the PDF gets attached to the invoice, the XLSX
    gets filtered by whoever checks it. `formato` is a `Literal`, so an unsupported
    value is a 422 rather than a branch nobody wrote.

    The PDF is archived as a `document` and this returns its id, matching the slice 2
    rule that the bytes are fetched from the document download endpoint; the XLSX is
    streamed, because it is a working copy and not an artefact.
    """
    service = TimeReportService(session, storage)
    if formato == "xlsx":
        filename, content = service.build_xlsx(deal_id, mese, actor)
        return Response(
            content=content,
            media_type=XLSX_CONTENT_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    document = service.render_pdf(deal_id, mese, actor)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content=jsonable_encoder(document)
    )
```

Add `from fastapi.encoders import jsonable_encoder` and `from fastapi.responses import JSONResponse` to that router's imports.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/core/tests/test_time_report_xlsx.py packages/core/tests/test_architecture.py apps/api -q`
Expected: PASS. `test_architecture.py` matters here specifically: `openpyxl` must now resolve through core's own declared dependencies rather than failing the allowlist.

- [ ] **Step 7: Commit**

```bash
git add packages/core apps/api uv.lock
git commit -m "feat(timetracking): XLSX timesheet with real dates, real numbers and a SUBTOTAL"
```

---

## Phase 4A-6 — The interface

### Task 4A-16: `lib/decimal.ts`, the query keys, and the guard that keeps money out of floats

**Files:**
- Create: `apps/web/src/lib/decimal.ts`
- Create: `apps/web/src/lib/decimal.test.ts`
- Create: `apps/web/src/features/time/queries.ts`
- Create: `apps/web/src/features/costs/queries.ts`
- Create: `apps/web/src/lib/no-float-money.test.ts` (the AST guard)
- Modify: `apps/web/src/lib/query.ts` (new query keys)
- Modify: `apps/web/src/features/deals/columns.tsx` (replace the private `centsFromDecimalString` with the shared helper)

**Interfaces:**
- Consumes: `api`, `unwrap`, `toProblem` (`@/lib/api`); `components['schemas'][...]` from the regenerated `api-types.ts` (Task 4A-12); `queryKeys` (`@/lib/query`).
- Produces:
  ```ts
  // lib/decimal.ts
  export function scaledFromDecimalString(value: string, scale: number): number
  export function decimalStringFromScaled(scaled: number, scale: number): string
  export function sumDecimalStrings(values: readonly (string | null)[], scale: number): string
  export const MONEY_SCALE = 2
  export const HOURS_SCALE = 2

  // lib/query.ts
  timeEntries: (params?: unknown) => readonly ['time-entries', unknown]
  timeEntry: (id: string) => readonly ['time-entry', string]
  dealTimeSummary: (dealId: string) => readonly ['deal-time-summary', string]
  dealRates: (dealId: string, userId: string) => readonly ['deal-rates', string, string]
  costs: (params?: unknown) => readonly ['costs', unknown]
  costCategories: (includeArchived: boolean) => readonly ['cost-categories', boolean]
  periodLocks: (anno?: number) => readonly ['period-locks', number | null]

  // features/time/queries.ts
  export type TimeEntry = components['schemas']['TimeEntryRead']
  export type DealTimeSummary = components['schemas']['DealTimeSummary']
  export type RateDescription = components['schemas']['RateDescription']
  export function useTimeEntries(params: TimeEntriesListParams): UseQueryResult<TimeEntriesResult>
  export function useDealTimeSummary(dealId: string): UseQueryResult<DealTimeSummary>
  export function useDealRates(dealId: string, userId: string | undefined): UseQueryResult<RateDescription>
  export function useLogTime(): UseMutationResult<TimeEntry, unknown, Record<string, unknown>>
  export function useUpdateTimeEntry(entryId: string): ...
  export function useDeleteTimeEntry(): ...
  export function timeReportUrl(dealId: string, mese: string, formato: 'pdf' | 'xlsx'): string

  // features/costs/queries.ts
  export type Cost = components['schemas']['CostRead']
  export type CostCategory = components['schemas']['CostCategoryRead']
  export function useCosts(params: CostsListParams): ...
  export function useCostCategories(includeArchived?: boolean): ...
  export function useCreateCost(): ... ; useUpdateCost(id) ; useDeleteCost()
  ```

- [ ] **Step 1: Write the failing decimal test**

```ts
// apps/web/src/lib/decimal.test.ts
import { describe, expect, it } from 'vitest'
import {
  decimalStringFromScaled,
  scaledFromDecimalString,
  sumDecimalStrings,
} from './decimal'

describe('scaledFromDecimalString', () => {
  it('never multiplies a fractional value', () => {
    // Checked directly in this project's own Node runtime: `Number("0.29") * 100`
    // equals 28.999999999999996, not 29. The fractional digits are read off the
    // string; only the already-integral whole part is multiplied.
    expect(scaledFromDecimalString('0.29', 2)).toBe(29)
    expect(scaledFromDecimalString('1234.56', 2)).toBe(123456)
    expect(scaledFromDecimalString('-45.50', 2)).toBe(-4550)
    expect(scaledFromDecimalString('8', 2)).toBe(800)
    expect(scaledFromDecimalString('0.5', 2)).toBe(50)
  })

  it('handles the six-place factor scale the API sends for rates', () => {
    expect(scaledFromDecimalString('33.333333', 6)).toBe(33333333)
    expect(scaledFromDecimalString('80.000000', 6)).toBe(80000000)
  })

  it('truncates beyond the requested scale rather than rounding', () => {
    // The API never sends more places than the column holds, so this is a defensive
    // shape rather than a rounding policy: rounding here would silently disagree with
    // the backend's ROUND_HALF_UP, and two rounding rules is worse than one truncation
    // that cannot fire.
    expect(scaledFromDecimalString('1.005', 2)).toBe(100)
  })
})

describe('sumDecimalStrings', () => {
  it('adds in integer units and formats once', () => {
    expect(sumDecimalStrings(['2.50', '1.25', '0.25'], 2)).toBe('4.00')
    expect(sumDecimalStrings([], 2)).toBe('0.00')
    expect(sumDecimalStrings([null, '3.00', null], 2)).toBe('3.00')
  })

  it('is exact where the naive float sum is not', () => {
    // 300 values near the top of Numeric(12,2)'s range: the integer sum is exact,
    // the float sum displays two cents high. The same demonstration
    // `features/deals/columns.test.ts` already carries for `sumValorePrevisto`.
    const values: string[] = []
    let cents = 999999999999
    for (let index = 0; index < 300; index += 1) {
      values.push(decimalStringFromScaled(cents, 2))
      cents -= 100000300
    }
    const exact = sumDecimalStrings(values, 2)
    const naive = values.reduce((sum, value) => sum + Number(value), 0)
    expect(exact).not.toBe(naive.toFixed(2))
  })
})

describe('decimalStringFromScaled', () => {
  it('round-trips', () => {
    for (const value of ['0.00', '0.07', '12.30', '-4.05', '999.99']) {
      expect(decimalStringFromScaled(scaledFromDecimalString(value, 2), 2)).toBe(value)
    }
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pnpm -C apps/web exec vitest run src/lib/decimal.test.ts`
Expected: FAIL — `Failed to resolve import "./decimal"`.

- [ ] **Step 3: Implement `lib/decimal.ts`**

```ts
// apps/web/src/lib/decimal.ts
/**
 * Exact arithmetic on the decimal strings the API sends.
 *
 * Every `Numeric` column serialises to a JSON **string**, never a number — which is
 * precisely what lets the browser read the digits instead of routing them through a
 * binary float. `Numeric(12,2)` exists on the backend so money is never a float
 * (`deals/models.py`: "a binary float cannot represent 1234.56 exactly, and that drift
 * is a bug the moment it reaches an invoice"), and summing those values as
 * `sum + Number(value)` in the browser throws that guarantee away.
 *
 * Generalised from `features/deals/columns.tsx`'s own private
 * `centsFromDecimalString`, which now imports from here: three features need it at
 * once (the week grid's row and column totals, the costs panel, the deals Kanban), and
 * a fourth copy is how they start disagreeing.
 *
 * **This is the only arithmetic permitted in the browser in this slice**, and only for
 * hours. Every economic figure — every P&L row, every margin, every accrued value —
 * arrives from the API already summed (§6), and `no-float-money.test.ts` fails the
 * build if any module adds one.
 *
 * Scale bounds: `Numeric(12,2)` holds at most 10 integer digits, so its hundredths
 * representation is at most 12 digits, far under `Number.MAX_SAFE_INTEGER`'s 16 even
 * summed across thousands of rows. `Numeric(12,6)` is the same 12 digits. Plain
 * `number` integer arithmetic is therefore exact here; nothing needs `BigInt`, only the
 * discipline of never multiplying or dividing a fractional value.
 */

export const MONEY_SCALE = 2
export const HOURS_SCALE = 2

/**
 * `"1234.56"` at scale 2 → `123456`.
 *
 * Splits the string into its integer and fractional halves as *strings*, parses each
 * separately, and combines with integer arithmetic. The fractional digits are never
 * multiplied — `Number("0.29") * 100` is `28.999999999999996` in this project's own
 * Node runtime — and only the whole-number part, already an integer, is scaled.
 */
export function scaledFromDecimalString(value: string, scale: number): number {
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [wholePart = '', fractionPart = ''] = unsigned.split('.')
  const padded = (fractionPart + '0'.repeat(scale)).slice(0, scale)
  const factor = 10 ** scale
  const scaled = Number(wholePart || '0') * factor + Number(padded || '0')
  return negative ? -scaled : scaled
}

/** `123456` at scale 2 → `"1234.56"`. The inverse, used once per displayed total. */
export function decimalStringFromScaled(scaled: number, scale: number): string {
  const negative = scaled < 0
  const digits = String(Math.abs(scaled)).padStart(scale + 1, '0')
  const whole = digits.slice(0, digits.length - scale)
  const fraction = digits.slice(digits.length - scale)
  return `${negative ? '-' : ''}${whole}${scale > 0 ? `.${fraction}` : ''}`
}

/**
 * Sums decimal strings exactly and formats the result once, at the end.
 *
 * `null` contributes nothing rather than zero — the same distinction `formatMoney`
 * draws when it renders a dash instead of `0,00 €` for an unpriced row.
 */
export function sumDecimalStrings(
  values: readonly (string | null)[],
  scale: number,
): string {
  let total = 0
  for (const value of values) {
    if (value !== null) total += scaledFromDecimalString(value, scale)
  }
  return decimalStringFromScaled(total, scale)
}
```

Then replace the private copy in `features/deals/columns.tsx`. Delete the local `centsFromDecimalString` function and its docblock, add `import { MONEY_SCALE, scaledFromDecimalString } from '@/lib/decimal'`, and change `sumValorePrevisto` to call `scaledFromDecimalString(deal.valore_previsto, MONEY_SCALE)`. Leave `columns.test.ts`'s 300-deal assertion exactly as it is — it must keep passing against the shared helper, which is what proves the extraction changed no behaviour.

- [ ] **Step 4: Write the AST guard**

```ts
// apps/web/src/lib/no-float-money.test.ts
/**
 * Criterion 4's second half: "no economic total is born in the browser".
 *
 * The previous system's whole P&L was computed in `App.jsx` — three fiscal constants, float hour
 * sums, and a margin that changed depending on which of three fallback buckets happened
 * to be non-empty. This slice moves that arithmetic into `packages/core` and this test
 * is what keeps it there. Parsed with the TypeScript compiler rather than grepped,
 * because `Number(` in a comment or in a string is not a defect and a regex cannot tell
 * the difference.
 */
import { readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { globSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const SRC = join(import.meta.dirname, '..')

/**
 * The API fields that are money, hours or rates. Every one of them arrives as a
 * decimal string and must reach the screen either as that string or through
 * `lib/decimal.ts` — never through `Number()`, `parseFloat`, or `+`.
 */
const ECONOMIC_FIELDS = new Set([
  'importo',
  'ore',
  'ore_totali',
  'ore_preventivate',
  'ore_fatturabili_non_fatturate',
  'valore_riga',
  'costo_riga',
  'valore_previsto',
  'valore_preventivato',
  'valore_ore_non_fatturate',
  'valore_maturato',
  'tariffa',
  'tariffa_applicata',
  'tariffa_oraria',
  'tariffa_oraria_default',
  'costo',
  'costo_applicato',
  'costo_orario_default',
  'costo_lavoro',
  'costi_diretti',
  'ricavi',
  'margine_lordo',
  'margine_percentuale',
  'budget_pro_rata',
  'scostamento_valore',
  'avanzamento_ore',
  'imponibile',
  'imposta_sostitutiva',
  'contributi',
  'reddito_netto_stimato',
])

/**
 * The one module allowed to touch these values numerically, and the one place the
 * exemption is written down. `lib/decimal.ts` is the exemption; its own test exercises
 * it. `features/deals/columns.tsx` is NOT exempt — it goes through the helper.
 */
const ALLOWED = new Set(['lib/decimal.ts', 'lib/decimal.test.ts', 'lib/no-float-money.test.ts'])

function economicFieldName(node: ts.Node): string | null {
  if (ts.isPropertyAccessExpression(node)) return node.name.text
  if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) {
    return node.argumentExpression.text
  }
  return null
}

function violationsIn(file: string): string[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, 'utf8'),
    ts.ScriptTarget.ESNext,
    true,
    ts.ScriptKind.TSX,
  )
  const found: string[] = []

  const isEconomic = (node: ts.Node): boolean => {
    const name = economicFieldName(node)
    return name !== null && ECONOMIC_FIELDS.has(name)
  }

  const report = (node: ts.Node, what: string) => {
    const { line } = source.getLineAndCharacterOfPosition(node.getStart(source))
    found.push(`${relative(SRC, file)}:${line + 1} ${what}`)
  }

  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
      const callee = node.expression.text
      if ((callee === 'Number' || callee === 'parseFloat' || callee === 'parseInt') &&
          node.arguments.some(isEconomic)) {
        report(node, `${callee}() applied to an economic field`)
      }
    }
    if (
      ts.isBinaryExpression(node) &&
      [
        ts.SyntaxKind.PlusToken,
        ts.SyntaxKind.MinusToken,
        ts.SyntaxKind.AsteriskToken,
        ts.SyntaxKind.SlashToken,
        ts.SyntaxKind.PlusEqualsToken,
      ].includes(node.operatorToken.kind) &&
      (isEconomic(node.left) || isEconomic(node.right))
    ) {
      report(node, 'arithmetic on an economic field')
    }
    if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.PlusToken &&
        isEconomic(node.operand)) {
      report(node, 'unary + on an economic field')
    }
    ts.forEachChild(node, visit)
  }

  ts.forEachChild(source, visit)
  return found
}

describe('no economic total is born in the browser', () => {
  it('finds no float arithmetic on an API money, hours or rate field', () => {
    const files = globSync('**/*.{ts,tsx}', { cwd: SRC })
      .filter((file) => !ALLOWED.has(file))
      .map((file) => join(SRC, file))
    const violations = files.flatMap(violationsIn)
    expect(violations).toEqual([])
  })

  it('actually catches a violation, rather than only claiming to', () => {
    // The guard proven to work, on a real construct, the same discipline
    // `test_architecture.py` follows for its own import checks.
    const fixture = join(import.meta.dirname, '__fixtures__', 'bad-money.ts')
    expect(violationsIn(fixture).length).toBeGreaterThan(0)
  })
})
```

```ts
// apps/web/src/lib/__fixtures__/bad-money.ts
// Not imported by anything: it exists so `no-float-money.test.ts` can prove its guard
// fires on a real construct instead of asserting so in prose. Excluded from the sweep
// by living under `__fixtures__`, which the glob's ALLOWED check does not need to know
// about because this file is passed to `violationsIn` directly.
export function wrong(rows: { importo: string }[]): number {
  return rows.reduce((sum, row) => sum + Number(row.importo), 0)
}
```

Add `__fixtures__` to the sweep's exclusion by filtering it in the glob: change the `.filter(...)` to `.filter((file) => !ALLOWED.has(file) && !file.includes('__fixtures__'))`.

- [ ] **Step 5: Add the query keys and the two query modules**

```ts
// apps/web/src/lib/query.ts -- append to queryKeys.
  timeEntries: (params?: unknown) => ['time-entries', params ?? {}] as const,
  timeEntry: (id: string) => ['time-entry', id] as const,
  dealTimeSummary: (dealId: string) => ['deal-time-summary', dealId] as const,
  // Keyed by both ids: the answer depends on the deal's rate *and* the user's default,
  // so a single-id key would serve one user's rate for another's.
  dealRates: (dealId: string, userId: string) => ['deal-rates', dealId, userId] as const,
  costs: (params?: unknown) => ['costs', params ?? {}] as const,
  costCategories: (includeArchived: boolean) => ['cost-categories', includeArchived] as const,
  periodLocks: (anno?: number) => ['period-locks', anno ?? null] as const,
```

```ts
// apps/web/src/features/time/queries.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

/**
 * Wire shapes taken from the generated OpenAPI schema, never hand-declared: the single
 * source of truth is `timetracking/schemas.py` and `pnpm generate:api` tracks it.
 *
 * Note that `ore`, `tariffa_applicata`, `valore_riga` and every other `Decimal` come
 * through as `string`, never `number` — which is what lets `lib/decimal.ts` read them
 * digit by digit instead of through a binary float.
 */
export type TimeEntry = components['schemas']['TimeEntryRead']
export type DealTimeSummary = components['schemas']['DealTimeSummary']
export type RateDescription = components['schemas']['RateDescription']

type TimeEntryCreateBody = components['schemas']['TimeEntryCreate']
type TimeEntryUpdateBody = components['schemas']['TimeEntryUpdate']

export interface TimeEntriesListParams {
  deal_id?: string
  user_id?: string
  da?: string
  a?: string
  fatturabile?: boolean
  fatturato?: boolean
}

export function useTimeEntries(params: TimeEntriesListParams = {}) {
  return useQuery({
    queryKey: queryKeys.timeEntries(params),
    queryFn: () =>
      unwrap(api.GET('/api/time-entries', { params: { query: { ...params, limit: 200 } } })),
  })
}

export function useDealTimeSummary(dealId: string) {
  return useQuery({
    queryKey: queryKeys.dealTimeSummary(dealId),
    queryFn: () =>
      unwrap(
        api.GET('/api/deals/{deal_id}/time-summary', {
          params: { path: { deal_id: dealId } },
        }),
      ),
  })
}

/**
 * `enabled` on a real `userId`, not a `?? ''` fallback: an empty path segment does not
 * match the route, Starlette's trailing-slash redirect lands the request on the *list*
 * endpoint with an absolute URL that escapes the Vite dev proxy, and it still resolves
 * 200 with nothing to show — the exact live defect `features/people/$personId.tsx`
 * found first.
 */
export function useDealRates(dealId: string, userId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.dealRates(dealId, userId ?? ''),
    enabled: Boolean(userId),
    queryFn: () =>
      unwrap(
        api.GET('/api/deals/{deal_id}/rates', {
          params: { path: { deal_id: dealId }, query: { user_id: userId as string } },
        }),
      ),
  })
}

/** Invalidates the summary and the deal's own timeline alongside the list: an hour
 *  changes all three, and a stale summary next to a fresh list is the shape of bug
 *  that makes people stop trusting the screen. */
function invalidateAfterWrite(queryClient: ReturnType<typeof useQueryClient>, dealId?: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.timeEntries() })
  if (dealId) {
    void queryClient.invalidateQueries({ queryKey: queryKeys.dealTimeSummary(dealId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('deal', dealId) })
  }
}

export function useLogTime() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/time-entries', { body: body as unknown as TimeEntryCreateBody })),
    onSuccess: (entry) => invalidateAfterWrite(queryClient, entry.deal_id),
  })
}

export function useUpdateTimeEntry(entryId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/api/time-entries/{entry_id}', {
          params: { path: { entry_id: entryId } },
          body: body as unknown as TimeEntryUpdateBody,
        }),
      ),
    onSuccess: (entry) => invalidateAfterWrite(queryClient, entry.deal_id),
  })
}

export function useDeleteTimeEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId }: { entryId: string; dealId?: string }) =>
      unwrap(
        api.DELETE('/api/time-entries/{entry_id}', { params: { path: { entry_id: entryId } } }),
      ),
    onSuccess: (_data, variables) => invalidateAfterWrite(queryClient, variables.dealId),
  })
}

/**
 * A plain URL, not a fetch: the browser downloads the file itself, so the bytes never
 * pass through JavaScript. Same-origin, so the session cookie travels with it and no
 * token has to be put in a query string.
 */
export function timeReportUrl(dealId: string, mese: string, formato: 'pdf' | 'xlsx'): string {
  const query = new URLSearchParams({ mese, formato })
  return `/api/deals/${dealId}/time-report?${query.toString()}`
}
```

```ts
// apps/web/src/features/costs/queries.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

export type Cost = components['schemas']['CostRead']
export type CostCategory = components['schemas']['CostCategoryRead']

type CostCreateBody = components['schemas']['CostCreate']
type CostUpdateBody = components['schemas']['CostUpdate']

export interface CostsListParams {
  deal_id?: string
  solo_generali?: boolean
  category_id?: string
  da?: string
  a?: string
}

export function useCosts(params: CostsListParams = {}) {
  return useQuery({
    queryKey: queryKeys.costs(params),
    queryFn: () => unwrap(api.GET('/api/costs', { params: { query: { ...params, limit: 200 } } })),
  })
}

export function useCostCategories(includeArchived = false) {
  return useQuery({
    queryKey: queryKeys.costCategories(includeArchived),
    queryFn: () =>
      unwrap(
        api.GET('/api/cost-categories', { params: { query: { include_archived: includeArchived } } }),
      ),
  })
}

function invalidateCosts(queryClient: ReturnType<typeof useQueryClient>, dealId?: string | null) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.costs() })
  if (dealId) {
    void queryClient.invalidateQueries({ queryKey: queryKeys.dealTimeSummary(dealId) })
  }
}

export function useCreateCost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/costs', { body: body as unknown as CostCreateBody })),
    onSuccess: (cost) => invalidateCosts(queryClient, cost.deal_id),
  })
}

export function useUpdateCost(costId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/api/costs/{cost_id}', {
          params: { path: { cost_id: costId } },
          body: body as unknown as CostUpdateBody,
        }),
      ),
    onSuccess: (cost) => invalidateCosts(queryClient, cost.deal_id),
  })
}

export function useDeleteCost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (costId: string) =>
      unwrap(api.DELETE('/api/costs/{cost_id}', { params: { path: { cost_id: costId } } })),
    onSuccess: () => invalidateCosts(queryClient),
  })
}
```

- [ ] **Step 6: Run the frontend suite**

Run: `pnpm -C apps/web exec vitest run src/lib src/features/deals` and `pnpm -C apps/web tsc --noEmit`
Expected: PASS, including the pre-existing `columns.test.ts` 300-deal assertion against the extracted helper.

- [ ] **Step 7: Commit**

```bash
git add apps/web
git commit -m "feat(web): exact decimal helpers, time and cost queries, and an AST guard against float money"
```

---

### Task 4A-17: The «Ore» tab on a deal

**Files:**
- Modify: `apps/web/src/components/EntityDetailLayout.tsx` (an optional `hours` tab)
- Create: `apps/web/src/features/time/TimeEntriesTab.tsx`
- Create: `apps/web/src/features/time/TimeEntryForm.tsx`
- Create: `apps/web/src/features/time/columns.tsx`
- Create: `apps/web/src/features/time/TimeReportButtons.tsx`
- Modify: `apps/web/src/routes/app/deal/$dealId.tsx` (pass `hours`; the «Preventivo» card loses its slice-4 placeholder note)
- Test: `apps/web/src/features/time/TimeEntriesTab.test.tsx`
- Test: `apps/web/src/features/time/columns.test.ts`

**Interfaces:**
- Consumes: `useTimeEntries`, `useDealTimeSummary`, `useDealRates`, `useLogTime`, `useUpdateTimeEntry`, `useDeleteTimeEntry`, `timeReportUrl` (4A-16); `useEntitySchema('time_entry')`; `DynamicForm` (required `mode`); `DataTable` with `DataTableFeatures`; `QueryErrorBanner`; `sumDecimalStrings`, `HOURS_SCALE`.
- Produces:
  ```tsx
  export function TimeEntriesTab({ dealId }: { dealId: string }): JSX.Element
  export function TimeEntryForm(props: TimeEntryFormProps): JSX.Element
  export interface TimeEntryFormValues { native: Record<string, unknown>; custom: Record<string, unknown> }
  export function timeEntryToFormValues(entry: TimeEntry): TimeEntryFormValues
  export function buildTimeEntryColumns(customFields: FieldDefinition[]): ColumnDef<DataTableFeatures, TimeEntry>[]
  export function formatHoursValue(value: string | null): string
  export function formatMoneyValue(value: string | null): string
  export function formatRateValue(value: string | null): string
  export function TimeReportButtons({ dealId }: { dealId: string }): JSX.Element
  ```
  `EntityDetailLayout` gains `hours?: ReactNode` and `economics?: ReactNode` (the latter is filled by Task 4B-10), both optional and both rendering no tab when absent — the same rule `documents` already follows, and for the same reason: an empty tab invites the user to look for something that does not exist for this entity.

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/features/time/TimeEntriesTab.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { TimeEntriesTab } from './TimeEntriesTab'

const DEAL = '11111111-1111-7111-8111-111111111111'

const entry = (overrides: Record<string, unknown> = {}) => ({
  id: '22222222-2222-7222-8222-222222222222',
  deal_id: DEAL,
  user_id: '33333333-3333-7333-8333-333333333333',
  data: '2026-03-10',
  ore: '2.50',
  descrizione: 'Analisi',
  fatturabile: true,
  tariffa_applicata: '80.000000',
  costo_applicato: null,
  tariffa_origine: 'deal',
  costo_origine: 'assente',
  valore_riga: '200.00',
  costo_riga: null,
  invoice_line_id: null,
  note_interne: null,
  custom_fields: {},
  created_at: '2026-03-10T09:00:00Z',
  updated_at: '2026-03-10T09:00:00Z',
  deleted_at: null,
  ...overrides,
})

const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TimeEntriesTab dealId={DEAL} />
    </QueryClientProvider>,
  )
}

describe('TimeEntriesTab', () => {
  it('shows the summary figures the API already summed, and never recomputes them', async () => {
    server.use(
      http.get('/api/time-entries', () =>
        HttpResponse.json({ items: [entry(), entry({ id: 'x', ore: '1.25' })], next_cursor: null }),
      ),
      http.get(`/api/deals/${DEAL}/time-summary`, () =>
        HttpResponse.json({
          deal_id: DEAL,
          stato: 'in corso',
          ore_totali: '3.75',
          ore_fatturabili_non_fatturate: '3.75',
          valore_ore_non_fatturate: '300.00',
          costo_lavoro: '0.00',
          ore_senza_tariffa: 1,
          voci: 2,
        }),
      ),
      http.get('/api/schema/time_entry', () =>
        HttpResponse.json({ entity_type: 'time_entry', native_fields: [], custom_fields: [] }),
      ),
    )
    renderTab()
    expect(await screen.findByText('3,75')).toBeInTheDocument()
    // Thousands separator forced on: it-IT's default withholds it below five digits.
    expect(await screen.findByText('300,00 €')).toBeInTheDocument()
    // Unpriced hours are named with their count, never valued at zero.
    expect(await screen.findByText(/1 voce senza tariffa/i)).toBeInTheDocument()
    expect(screen.getByText(/in corso/i)).toBeInTheDocument()
  })

  it('renders a banner, never an empty table, when the request fails', async () => {
    server.use(
      http.get('/api/time-entries', () => HttpResponse.json({ detail: 'Boom' }, { status: 500 })),
      http.get(`/api/deals/${DEAL}/time-summary`, () =>
        HttpResponse.json({ detail: 'Boom' }, { status: 500 }),
      ),
      http.get('/api/schema/time_entry', () =>
        HttpResponse.json({ entity_type: 'time_entry', native_fields: [], custom_fields: [] }),
      ),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/nessuna voce/i)).not.toBeInTheDocument()
  })

  it('surfaces a closed-period conflict as the server worded it', async () => {
    server.use(
      http.get('/api/time-entries', () => HttpResponse.json({ items: [], next_cursor: null })),
      http.get(`/api/deals/${DEAL}/time-summary`, () =>
        HttpResponse.json({
          deal_id: DEAL, stato: 'in corso', ore_totali: '0.00',
          ore_fatturabili_non_fatturate: '0.00', valore_ore_non_fatturate: '0.00',
          costo_lavoro: '0.00', ore_senza_tariffa: 0, voci: 0,
        }),
      ),
      http.get('/api/schema/time_entry', () =>
        HttpResponse.json({ entity_type: 'time_entry', native_fields: [], custom_fields: [] }),
      ),
      http.get(`/api/deals/${DEAL}/rates`, () =>
        HttpResponse.json({
          deal_id: DEAL, user_id: 'u', tariffa: '80.000000', tariffa_origine: 'deal',
          costo: null, costo_origine: 'assente',
        }),
      ),
      http.post('/api/time-entries', () =>
        HttpResponse.json(
          {
            type: 'https://pigrocrm.dev/errors/conflict',
            title: 'Conflitto con lo stato attuale',
            status: 409,
            detail: 'time_entry: il periodo marzo 2026 è chiuso: riaprilo per modificare voci datate in quel mese',
            code: 'conflict',
            instance: '/api/time-entries',
            anno: 2026,
            mese: 3,
          },
          { status: 409, headers: { 'content-type': 'application/problem+json' } },
        ),
      ),
    )
    renderTab()
    await userEvent.click(await screen.findByRole('button', { name: /registra ore/i }))
    await userEvent.click(await screen.findByRole('button', { name: /^salva$/i }))
    // The server's own sentence, never a client-side rewording.
    await waitFor(() =>
      expect(screen.getByText(/il periodo marzo 2026 è chiuso/i)).toBeInTheDocument(),
    )
  })

  it('marks a billed entry as not editable', async () => {
    server.use(
      http.get('/api/time-entries', () =>
        HttpResponse.json({ items: [entry({ invoice_line_id: 'line-1' })], next_cursor: null }),
      ),
      http.get(`/api/deals/${DEAL}/time-summary`, () =>
        HttpResponse.json({
          deal_id: DEAL, stato: 'chiuso', ore_totali: '2.50',
          ore_fatturabili_non_fatturate: '0.00', valore_ore_non_fatturate: '0.00',
          costo_lavoro: '0.00', ore_senza_tariffa: 0, voci: 1,
        }),
      ),
      http.get('/api/schema/time_entry', () =>
        HttpResponse.json({ entity_type: 'time_entry', native_fields: [], custom_fields: [] }),
      ),
    )
    renderTab()
    expect(await screen.findByText(/fatturata/i)).toBeInTheDocument()
  })
})
```

```ts
// apps/web/src/features/time/columns.test.ts
import { describe, expect, it } from 'vitest'
import { formatHoursValue, formatMoneyValue, formatRateValue } from './columns'

describe('the three formatters', () => {
  it('forces the thousands separator below five digits', () => {
    // it-IT's default grouping withholds the separator until the integer part has five
    // digits: `Intl.NumberFormat('it-IT').format(2500.5)` renders "2500,50". Every
    // currency surface in this product forces it on for that reason.
    expect(formatMoneyValue('2500.50')).toBe('2.500,50 €')
    expect(formatHoursValue('1234.50')).toBe('1.234,5')
  })

  it('renders an absent value as a dash, never as zero', () => {
    // `null` is a real, distinct state: an unpriced hour is not a free hour.
    expect(formatMoneyValue(null)).toBe('—')
    expect(formatRateValue(null)).toBe('—')
    expect(formatMoneyValue('0.00')).toBe('0,00 €')
  })

  it('shows a rate at the precision the column holds', () => {
    // Numeric(12,6): "33,333333 €/h" is not expressible at two places, which is the
    // whole reason the third scale exists.
    expect(formatRateValue('33.333333')).toBe('33,333333 €/h')
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pnpm -C apps/web exec vitest run src/features/time`
Expected: FAIL — `Failed to resolve import "./TimeEntriesTab"`.

- [ ] **Step 3: Add the two tab slots to `EntityDetailLayout`**

```tsx
// apps/web/src/components/EntityDetailLayout.tsx -- two new props on the interface,
// two new triggers, two new contents. The pattern `documents` already established.
  /**
   * The Ore tab's contents. Optional because only a Deal has hours: an hour is
   * attached to a deal, always and only (`time_entries.deal_id` is required), so
   * neither a Customer nor a Person can have this tab. Absent means the tab is not
   * rendered at all rather than rendered empty -- an empty tab invites the user to look
   * for something that does not exist for this entity.
   */
  hours?: ReactNode
  /**
   * The Economia tab's contents -- a Deal's own profit and loss, or a Customer's as the
   * sum of their deals. Filled by slice 4B; absent for the whole of 4A, which is why it
   * is optional rather than required. A tab showing zeros is worse than no tab: the
   * user understands "not yet", and cannot tell a real zero from a missing feature.
   */
  economics?: ReactNode

// ... in TabsList, between Documenti and Timeline:
          {hours && <TabsTrigger value="ore">Ore</TabsTrigger>}
          {economics && <TabsTrigger value="economia">Economia</TabsTrigger>}

// ... and the matching contents:
        {hours && (
          <TabsContent value="ore" className="mt-6">
            {hours}
          </TabsContent>
        )}
        {economics && (
          <TabsContent value="economia" className="mt-6">
            {economics}
          </TabsContent>
        )}
```

Add both to the destructured parameter list and update `EntityDetailLayout.test.tsx` with two cases asserting the tab is absent when the prop is absent and present when it is supplied — mirroring the existing `documents` cases exactly.

- [ ] **Step 4: Write the formatters and the columns**

```tsx
// apps/web/src/features/time/columns.tsx
import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { TimeEntry } from './queries'

const EMPTY = '—'

// `useGrouping: 'always'` on every formatter, never the ICU default: it-IT withholds
// the thousands separator until the integer part has five digits (checked directly on
// this stack's ICU: `Intl.NumberFormat('it-IT').format(2500.5)` renders "2500,50"). A
// four-figure total silently losing its separator on one screen is exactly the
// inconsistency this product forces grouping on to avoid.
const euro = new Intl.NumberFormat('it-IT', {
  style: 'currency',
  currency: 'EUR',
  useGrouping: 'always',
})
const hours = new Intl.NumberFormat('it-IT', { useGrouping: 'always' })
// Six places, because a rate is Numeric(12,6): "33,333333 €/h" is not expressible at
// two, which is the whole reason the third scale exists (§6.1).
const rate = new Intl.NumberFormat('it-IT', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
  useGrouping: 'always',
})

/** `null` is a real, distinct state -- an hour nobody has priced is not a free hour --
 *  so it renders as a dash and never as `0,00 €`. */
export function formatMoneyValue(value: string | null): string {
  return value === null ? EMPTY : euro.format(Number(value))
}

export function formatHoursValue(value: string | null): string {
  return value === null ? EMPTY : hours.format(Number(value))
}

export function formatRateValue(value: string | null): string {
  return value === null ? EMPTY : `${rate.format(Number(value))} €/h`
}

/**
 * `value` is the ISO `YYYY-MM-DD` string a `Date` column always stores.
 * `new Date("2026-03-10")` parses as UTC midnight, and formatting that with
 * `Intl.DateTimeFormat` renders in the browser's zone -- anywhere behind UTC that is
 * still the previous evening, so the date silently loses a day. Building the `Date`
 * from its parts in local time keeps construction and formatting in one zone. It is the
 * same trap the previous system fell into from the other direction, with `toISOString()` on write.
 */
export function formatIsoDate(value: string): string {
  const [year, month, day] = value.split('-').map(Number)
  if (year === undefined || month === undefined || day === undefined) return value
  return new Intl.DateTimeFormat('it-IT').format(new Date(year, month - 1, day))
}

const ORIGIN_LABELS: Record<string, string> = {
  manuale: 'manuale',
  deal: 'dal deal',
  utente: "dall'utente",
  assente: 'assente',
}

export function buildTimeEntryColumns(
  customFields: FieldDefinition[],
): ColumnDef<DataTableFeatures, TimeEntry>[] {
  const native: ColumnDef<DataTableFeatures, TimeEntry>[] = [
    { header: 'Data', id: 'data', accessorFn: (row) => formatIsoDate(row.data) },
    { header: 'Ore', id: 'ore', accessorFn: (row) => formatHoursValue(row.ore) },
    { header: 'Descrizione', accessorKey: 'descrizione' },
    {
      header: 'Tariffa',
      id: 'tariffa_applicata',
      // The origin next to the value, because "80 €/h" and "80 €/h, dal deal" answer
      // two different questions, and the second is the one somebody asks when the
      // number looks wrong.
      accessorFn: (row) =>
        row.tariffa_applicata === null
          ? '—'
          : `${formatRateValue(row.tariffa_applicata)} (${ORIGIN_LABELS[row.tariffa_origine]})`,
    },
    {
      header: 'Valore',
      id: 'valore_riga',
      // Straight from the API. This is the number the timesheet prints next to the
      // entry, so it must be the server's own figure and not a product computed here.
      accessorFn: (row) => formatMoneyValue(row.valore_riga),
    },
    {
      header: 'Stato',
      id: 'stato',
      accessorFn: (row) =>
        row.invoice_line_id !== null
          ? 'Fatturata'
          : row.fatturabile
            ? 'Da fatturare'
            : 'Non fatturabile',
    },
  ]

  // Prefixed `custom_` so a tenant-defined key can never collide with a native column's
  // id. The backend guard added in Task 4A-2 now refuses the collision at the source
  // too, but the prefix stays: it is what keeps the table correct for definitions
  // created before that guard existed.
  const custom: ColumnDef<DataTableFeatures, TimeEntry>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
```

- [ ] **Step 5: Write the tab, the form and the download buttons**

```tsx
// apps/web/src/features/time/TimeEntriesTab.tsx
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'
import { buildTimeEntryColumns, formatHoursValue, formatMoneyValue } from './columns'
import { TimeEntryForm, timeEntryToFormValues } from './TimeEntryForm'
import { TimeReportButtons } from './TimeReportButtons'
import { useDealTimeSummary, useLogTime, useTimeEntries, type TimeEntry } from './queries'

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function TimeEntriesTab({ dealId }: { dealId: string }) {
  const entries = useTimeEntries({ deal_id: dealId })
  const summary = useDealTimeSummary(dealId)
  const schema = useEntitySchema('time_entry')
  const canWrite = useCanWrite()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<TimeEntry | null>(null)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const log = useLogTime()

  // Three deliberately different shapes, never one table with different text in a cell:
  // a failed request is "we do not actually know", which is a different claim from
  // "there is nothing here" and not this component's to make on the caller's behalf.
  if (entries.isError || summary.isError) {
    return <QueryErrorBanner error={entries.error ?? summary.error} />
  }

  return (
    <div className="space-y-6">
      {summary.data && (
        <Card>
          <CardContent className="flex flex-wrap items-start justify-between gap-6 pt-6">
            <Figure label="Ore consuntivate" value={formatHoursValue(summary.data.ore_totali)} />
            <Figure
              label="Da fatturare"
              value={formatHoursValue(summary.data.ore_fatturabili_non_fatturate)}
            />
            <Figure
              label="Valore maturato (stima)"
              value={formatMoneyValue(summary.data.valore_ore_non_fatturate)}
              // Named as a stima and never as a margin: it is the estimate of §3
              // decision 2, and it stops being consulted the moment an invoice exists.
              hint="Non è un ricavo: il ricavo è la fattura"
            />
            <div className="flex flex-col items-start gap-2">
              <p className="text-sm text-muted-foreground">Stato</p>
              <Badge variant={summary.data.stato === 'chiuso' ? 'default' : 'secondary'}>
                {summary.data.stato}
              </Badge>
              {summary.data.ore_senza_tariffa > 0 && (
                <p className="text-xs text-muted-foreground">
                  {summary.data.ore_senza_tariffa}{' '}
                  {summary.data.ore_senza_tariffa === 1 ? 'voce' : 'voci'} senza tariffa,
                  esclusa dal valore maturato
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <TimeReportButtons dealId={dealId} />
        {canWrite && (
          <Button
            onClick={() => {
              setProblem(null)
              setCreating(true)
            }}
          >
            <Plus className="mr-2 size-4" />
            Registra ore
          </Button>
        )}
      </div>

      <DataTable
        columns={buildTimeEntryColumns(schema.data?.custom_fields ?? [])}
        data={entries.data?.items ?? []}
        isLoading={entries.isLoading}
        emptyMessage="Nessuna voce di ore su questo deal."
        onRowClick={
          canWrite
            ? (row) => {
                if (row.invoice_line_id !== null) {
                  toast.info(
                    'La voce è su una fattura: ore, data, tariffa e descrizione non sono più modificabili.',
                  )
                }
                setProblem(null)
                setEditing(row)
              }
            : undefined
        }
      />

      <TimeEntryForm
        open={creating}
        onOpenChange={setCreating}
        dealId={dealId}
        customFields={schema.data?.custom_fields ?? []}
        problem={problem}
        busy={log.isPending}
        title="Registra ore"
        onSubmit={(values) =>
          log.mutate(values, {
            onSuccess: () => {
              setCreating(false)
              toast.success('Ore registrate')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }
      />

      {editing && (
        <TimeEntryForm
          open
          onOpenChange={() => setEditing(null)}
          dealId={dealId}
          customFields={schema.data?.custom_fields ?? []}
          initial={timeEntryToFormValues(editing)}
          entryId={editing.id}
          locked={editing.invoice_line_id !== null}
          problem={problem}
          title="Modifica voce"
          onSubmit={() => undefined}
          onSaved={() => setEditing(null)}
        />
      )}
    </div>
  )
}
```

```tsx
// apps/web/src/features/time/TimeEntryForm.tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { DynamicForm } from '@/components/DynamicForm'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useSession } from '@/lib/auth'
import type { FieldDefinition } from '@/lib/schema'
import { formatRateValue } from './columns'
import { useDealRates, useLogTime, useUpdateTimeEntry, type TimeEntry } from './queries'

/**
 * The editable native columns, as `FieldDefinition`s so `DynamicFieldRenderer` draws
 * them -- the same idiom `DealForm`/`CustomerForm` use. `deal_id` is absent: it comes
 * from the route, and reassigning an hour to another deal is not something this screen
 * offers. `user_id` is absent too: it is the logged-in user on create, and reassigning
 * it is an admin operation with no picker control (`FieldType` has no user type).
 */
const NATIVE_FIELDS: FieldDefinition[] = [
  { key: 'data', label: 'Data', type: 'date', required: true, options: [] },
  { key: 'ore', label: 'Ore', type: 'number', required: true, options: [] },
  { key: 'descrizione', label: 'Descrizione', type: 'textarea', required: true, options: [] },
  { key: 'fatturabile', label: 'Fatturabile', type: 'checkbox', required: false, options: [] },
  {
    key: 'tariffa_applicata',
    label: 'Tariffa (€/h, lascia vuoto per usare quella predefinita)',
    type: 'number',
    required: false,
    options: [],
  },
  { key: 'note_interne', label: 'Note interne', type: 'textarea', required: false, options: [] },
]

const NATIVE_FIELD_KEYS = NATIVE_FIELDS.map((field) => field.key)

/** Fields the backend freezes once the entry is on an issued invoice (§4.3). The form
 *  hides them rather than letting the user type into a control whose value the server
 *  will refuse -- an `ImmutableField` after pressing Salva is a worse explanation than
 *  a field that is simply not there. */
const LOCKED_KEYS = new Set(['data', 'ore', 'descrizione', 'fatturabile', 'tariffa_applicata'])

/**
 * Two namespaces, decided once at seed time and never re-derived at submit -- copies
 * `DealFormValues` exactly, for the same reason: provenance is structural. A native
 * column clears on `""` and only on `""`; a custom field clears on `null` and only on
 * `null`; an omitted key clears nothing.
 */
export interface TimeEntryFormValues {
  native: Record<string, unknown>
  custom: Record<string, unknown>
}

const DEFAULT_VALUES: TimeEntryFormValues = {
  native: { fatturabile: true, data: new Date().toISOString().slice(0, 10) },
  custom: {},
}

export function timeEntryToFormValues(entry: TimeEntry): TimeEntryFormValues {
  const native: Record<string, unknown> = {}
  for (const key of NATIVE_FIELD_KEYS) {
    native[key] = (entry as unknown as Record<string, unknown>)[key]
  }
  return { native, custom: { ...entry.custom_fields } }
}

/** Mirrors `is_blank` in `fields/validator.py` and every other form's own helper:
 *  `null`/`undefined`, a whitespace-only string, or an empty array mean "no value";
 *  `false` and `0` are real values. */
function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

interface TimeEntryFormProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  dealId: string
  customFields: FieldDefinition[]
  initial?: TimeEntryFormValues
  entryId?: string
  locked?: boolean
  problem?: ProblemDetail | null
  busy?: boolean
  title: string
  onSubmit: (values: Record<string, unknown>) => void
  onSaved?: () => void
}

export function TimeEntryForm({
  open,
  onOpenChange,
  dealId,
  customFields,
  initial,
  entryId,
  locked = false,
  problem: externalProblem,
  busy,
  title,
  onSubmit,
  onSaved,
}: TimeEntryFormProps) {
  const session = useSession()
  const [values, setValues] = useState<TimeEntryFormValues>(initial ?? DEFAULT_VALUES)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const isCreate = initial === undefined
  const rates = useDealRates(dealId, session?.id)
  const log = useLogTime()
  const update = useUpdateTimeEntry(entryId ?? '')

  // Same "reset synchronously when `open` toggles" pattern as CustomerForm/DealForm:
  // this component stays mounted across dialog opens, so a plain useState initializer
  // would only ever run once.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setValues(initial ?? DEFAULT_VALUES)
      setProblem(null)
    }
  }

  const isRenderedCustomKey = (key: string) => customFields.some((field) => field.key === key)

  function change(key: string, value: unknown) {
    setValues((previous) =>
      isRenderedCustomKey(key) || key in previous.custom
        ? { ...previous, custom: { ...previous.custom, [key]: value } }
        : { ...previous, native: { ...previous.native, [key]: value } },
    )
  }

  function submit() {
    const native: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values.native)) {
      if (locked && LOCKED_KEYS.has(key)) continue
      if (!isBlank(value)) {
        native[key] = value
      } else if (!isBlank(initial?.native[key])) {
        // The user cleared a native column that held a value: say so explicitly with
        // `""`, or the old value survives untouched. `exclude_none=True` keeps an empty
        // string and drops an actual `None`, so `null` here would be silently ignored.
        native[key] = ''
      }
    }

    const custom: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values.custom)) {
      // A stored value whose definition is archived: omit the key and
      // `_update_custom_fields` carries it over untouched.
      if (!isRenderedCustomKey(key)) continue
      if (!isBlank(value)) {
        custom[key] = value
      } else if (!isBlank(initial?.custom[key])) {
        custom[key] = null
      }
    }

    const body = { ...native, custom_fields: custom }
    if (isCreate) {
      // `deal_id` and `user_id` come from the route and the session, never from a
      // control: an agent resolving the wrong deal attributes billable hours to the
      // wrong client, and a human picker here would be the same hazard with a mouse.
      log.mutate(
        { ...body, deal_id: dealId, user_id: session?.id },
        {
          onSuccess: () => {
            onOpenChange(false)
            toast.success('Ore registrate')
          },
          onError: (error) => setProblem(toProblem(error)),
        },
      )
      onSubmit(body)
      return
    }
    update.mutate(body, {
      onSuccess: () => {
        onSaved?.()
        toast.success('Voce aggiornata')
      },
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  const fields = [
    ...NATIVE_FIELDS.filter((field) => !(locked && LOCKED_KEYS.has(field.key))),
    ...customFields,
  ]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {locked && (
          <p className="rounded-lg border border-muted bg-muted/40 px-3 py-2 text-sm">
            La voce è su una fattura emessa: ore, data, tariffa e descrizione sono
            congelate. Restano modificabili le note interne e i campi personalizzati.
          </p>
        )}

        {isCreate && rates.data && (
          <p className="text-sm text-muted-foreground">
            Tariffa che verrà congelata su questa voce:{' '}
            <strong>{formatRateValue(rates.data.tariffa)}</strong>{' '}
            {rates.data.tariffa === null
              ? '— la voce sarà registrata senza tariffa'
              : `(${rates.data.tariffa_origine})`}
          </p>
        )}

        <DynamicForm
          fields={fields}
          values={{ ...values.native, ...values.custom }}
          onChange={change}
          problem={problem ?? externalProblem}
          mode={isCreate ? 'create' : 'edit'}
        />

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annulla
          </Button>
          <Button onClick={submit} disabled={busy || log.isPending || update.isPending}>
            {log.isPending || update.isPending ? 'Salvataggio…' : 'Salva'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

```tsx
// apps/web/src/features/time/TimeReportButtons.tsx
import { Download, FileSpreadsheet } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { timeReportUrl } from './queries'

/**
 * Two formats, two recipients (§2.1): the PDF is attached to the invoice, the XLSX gets
 * filtered by whoever has to check it. Plain anchors, not fetches: the browser
 * downloads the file itself, so the bytes never pass through JavaScript, and being
 * same-origin the session cookie travels with the request without a token in a query
 * string.
 */
export function TimeReportButtons({ dealId }: { dealId: string }) {
  const now = new Date()
  const [mese, setMese] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`,
  )

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-2">
        <Label htmlFor="time-report-mese">Rapporto ore del mese</Label>
        <Input
          id="time-report-mese"
          type="month"
          value={mese}
          onChange={(event) => setMese(event.target.value)}
          className="w-40"
        />
      </div>
      <Button asChild variant="outline">
        <a href={timeReportUrl(dealId, mese, 'pdf')}>
          <Download className="mr-2 size-4" />
          PDF
        </a>
      </Button>
      <Button asChild variant="outline">
        <a href={timeReportUrl(dealId, mese, 'xlsx')}>
          <FileSpreadsheet className="mr-2 size-4" />
          XLSX
        </a>
      </Button>
    </div>
  )
}
```

- [ ] **Step 6: Wire the tab into the deal route**

```tsx
// apps/web/src/routes/app/deal/$dealId.tsx
// Add the import:
import { TimeEntriesTab } from '@/features/time/TimeEntriesTab'

// Add the prop to EntityDetailLayout, next to `documents`:
        hours={<TimeEntriesTab dealId={dealId} />}

// And in the "Preventivo" card, replace the placeholder paragraph:
//   <p className="mt-3 text-xs text-muted-foreground">
//     Il confronto preventivo/consuntivo arriva nello slice 4, insieme al time tracking.
//   </p>
// with the honest 4A statement -- the actuals exist now, the comparison does not:
                <p className="mt-3 text-xs text-muted-foreground">
                  Le ore consuntivate sono nella tab «Ore». Il confronto
                  preventivo/consuntivo arriva con il conto economico.
                </p>
```

- [ ] **Step 7: Run the frontend suite**

Run: `pnpm -C apps/web exec vitest run src/features/time src/components/EntityDetailLayout.test.tsx` and `pnpm -C apps/web tsc --noEmit`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/web
git commit -m "feat(web): the Ore tab on a deal, with frozen-rate preview and timesheet downloads"
```

---

### Task 4A-18: `/ore` — the weekly grid

**Files:**
- Create: `apps/web/src/features/time/WeekGrid.tsx`
- Create: `apps/web/src/features/time/WeekGridRow.tsx`
- Create: `apps/web/src/features/time/week.ts` (pure date and total arithmetic)
- Create: `apps/web/src/routes/app/ore.tsx`
- Modify: `apps/web/src/components/AppShell.tsx` (the sidebar entry)
- Test: `apps/web/src/features/time/week.test.ts`
- Test: `apps/web/src/features/time/WeekGrid.test.tsx`

**Interfaces:**
- Consumes: `useTimeEntries`, `useLogTime`, `useUpdateTimeEntry`, `useDeleteTimeEntry` (4A-16); `useDeals` (`@/features/deals/queries`); `sumDecimalStrings`, `HOURS_SCALE` (4A-16); `useSession` (`@/lib/auth`); `QueryErrorBanner`.
- Produces:
  ```ts
  // week.ts
  export interface WeekDay { iso: string; label: string; short: string }
  export function weekDays(anchor: Date): WeekDay[]            // Monday-first, seven days
  export function shiftWeek(anchor: Date, weeks: number): Date
  export function isoDate(value: Date): string                 // local parts, never toISOString()
  export function parseIsoDate(value: string): Date             // local parts, never new Date(iso)
  export interface GridCell { entryId: string | null; ore: string | null }
  export function buildGrid(entries: TimeEntry[], days: WeekDay[]): Map<string, Map<string, GridCell>>
  export function rowTotal(row: Map<string, GridCell>): string
  export function columnTotal(grid: Map<string, Map<string, GridCell>>, iso: string): string
  export function gridTotal(grid: Map<string, Map<string, GridCell>>): string

  // components
  export function WeekGrid(): JSX.Element
  export function WeekGridRow(props: WeekGridRowProps): JSX.Element
  ```
  The route is `/app/ore`, registered file-based as `apps/web/src/routes/app/ore.tsx` exporting only `Route` — a route file exporting anything else opts that route out of the router plugin's automatic code-splitting, which `routeTree.gen.ts` warns about.

- [ ] **Step 1: Write the failing pure test**

```ts
// apps/web/src/features/time/week.test.ts
import { describe, expect, it } from 'vitest'
import {
  buildGrid,
  columnTotal,
  gridTotal,
  isoDate,
  parseIsoDate,
  rowTotal,
  shiftWeek,
  weekDays,
} from './week'

const DEAL_A = 'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa'
const DEAL_B = 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb'

const entry = (dealId: string, data: string, ore: string, id = `${dealId}-${data}`) =>
  ({ id, deal_id: dealId, data, ore }) as never

describe('weekDays', () => {
  it('is Monday-first and seven days long', () => {
    // Italian working weeks start on Monday; ICU's `it-IT` agrees, but the grid must
    // not depend on a locale lookup for its column order.
    const days = weekDays(new Date(2026, 2, 12)) // Thursday 12 March 2026
    expect(days).toHaveLength(7)
    expect(days[0]?.iso).toBe('2026-03-09')
    expect(days[6]?.iso).toBe('2026-03-15')
    expect(days[0]?.short).toBe('lun')
  })

  it('crosses a month and a year boundary without shifting a day', () => {
    // `new Date("2026-01-01")` is UTC midnight, which is 31 December in any zone behind
    // UTC. Everything here is built from local parts, so the boundary is stable.
    expect(weekDays(new Date(2026, 0, 1))[0]?.iso).toBe('2025-12-29')
    expect(weekDays(new Date(2026, 11, 31))[6]?.iso).toBe('2027-01-03')
  })
})

describe('isoDate and parseIsoDate', () => {
  it('round-trip through local parts, never through UTC', () => {
    // The trap in both directions: `toISOString()` on write moved the previous system's 31 March
    // 23:30 CEST entry into April, and `new Date("2026-03-10")` on read renders as
    // 9 March anywhere behind UTC.
    expect(isoDate(new Date(2026, 2, 31, 23, 30))).toBe('2026-03-31')
    const parsed = parseIsoDate('2026-03-10')
    expect([parsed.getFullYear(), parsed.getMonth(), parsed.getDate()]).toEqual([2026, 2, 10])
  })
})

describe('shiftWeek', () => {
  it('moves whole weeks in both directions', () => {
    expect(isoDate(shiftWeek(new Date(2026, 2, 12), -1))).toBe('2026-03-05')
    expect(isoDate(shiftWeek(new Date(2026, 2, 12), 1))).toBe('2026-03-19')
  })
})

describe('the grid and its totals', () => {
  const days = weekDays(new Date(2026, 2, 12))
  const grid = buildGrid(
    [
      entry(DEAL_A, '2026-03-09', '2.50'),
      entry(DEAL_A, '2026-03-11', '1.25'),
      entry(DEAL_B, '2026-03-09', '4.00'),
      entry(DEAL_A, '2026-03-30', '8.00'), // outside the week
    ],
    days,
  )

  it('places each entry in its deal row and its day column', () => {
    expect(grid.get(DEAL_A)?.get('2026-03-09')?.ore).toBe('2.50')
    expect(grid.get(DEAL_A)?.get('2026-03-10')?.ore).toBeNull()
    expect(grid.get(DEAL_A)?.get('2026-03-30')).toBeUndefined()
  })

  it('sums rows, columns and the whole grid in integer hundredths', () => {
    // The only arithmetic this slice permits in the browser, and only for hours (§6).
    expect(rowTotal(grid.get(DEAL_A)!)).toBe('3.75')
    expect(columnTotal(grid, '2026-03-09')).toBe('6.50')
    expect(gridTotal(grid)).toBe('7.75')
  })

  it('treats a day with no entry as contributing nothing, not zero hours logged', () => {
    expect(columnTotal(grid, '2026-03-15')).toBe('0.00')
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pnpm -C apps/web exec vitest run src/features/time/week.test.ts`
Expected: FAIL — `Failed to resolve import "./week"`.

- [ ] **Step 3: Implement `week.ts`**

```ts
// apps/web/src/features/time/week.ts
/**
 * The grid's arithmetic, kept pure so it can be proven with no React and no network.
 *
 * Every date here is built from and read as **local** year/month/day parts. Never
 * `toISOString()`, which is what moved the previous system's 31 March 23:30 CEST entry into April and
 * therefore into the wrong monthly export — the file attached to an invoice. And never
 * `new Date("2026-03-10")`, which parses as UTC midnight and renders as 9 March
 * anywhere behind UTC.
 *
 * Hour totals are summed in integer hundredths through `lib/decimal.ts`. This is the
 * only arithmetic the browser is allowed to do in this slice, and only for hours: every
 * economic figure arrives from the API already summed (§6).
 */
import { HOURS_SCALE, sumDecimalStrings } from '@/lib/decimal'
import type { TimeEntry } from './queries'

export interface WeekDay {
  /** `YYYY-MM-DD`, the exact shape `time_entries.data` stores and the API expects. */
  iso: string
  /** `lunedì 9 marzo` — the accessible label for the column header. */
  label: string
  /** `lun` — what actually fits in a column head. */
  short: string
}

export interface GridCell {
  entryId: string | null
  ore: string | null
}

const LONG = new Intl.DateTimeFormat('it-IT', { weekday: 'long', day: 'numeric', month: 'long' })
const SHORT = new Intl.DateTimeFormat('it-IT', { weekday: 'short' })

export function isoDate(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function parseIsoDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year ?? 1970, (month ?? 1) - 1, day ?? 1)
}

/** Monday-first. Not read from the locale: the column order of a working week is a
 *  product decision, and an ICU default that changed would silently reorder the grid. */
export function weekDays(anchor: Date): WeekDay[] {
  const monday = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
  // getDay(): 0 is Sunday, so Sunday must go back six days rather than none.
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7))
  return Array.from({ length: 7 }, (_, offset) => {
    const day = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + offset)
    return { iso: isoDate(day), label: LONG.format(day), short: SHORT.format(day) }
  })
}

export function shiftWeek(anchor: Date, weeks: number): Date {
  return new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + weeks * 7)
}

/**
 * One row per deal that has an entry this week, one cell per day.
 *
 * A cell holds at most one entry, and that is a deliberate limitation of this screen
 * rather than of the model: `time_entries` allows several entries on the same deal and
 * day (two 14-hour entries are a likely error but not an impossible one, §4.1), and the
 * deal's own Ore tab shows every one of them. The grid exists to attack the failure
 * §13 names — "I never entered Tuesday" — and a cell that tried to represent three
 * entries would be a worse control for that job. Where several exist, the grid shows
 * the first and the row links to the full list.
 */
export function buildGrid(
  entries: TimeEntry[],
  days: WeekDay[],
): Map<string, Map<string, GridCell>> {
  const wanted = new Set(days.map((day) => day.iso))
  const grid = new Map<string, Map<string, GridCell>>()
  for (const entry of entries) {
    if (!wanted.has(entry.data)) continue
    let row = grid.get(entry.deal_id)
    if (row === undefined) {
      row = new Map(days.map((day) => [day.iso, { entryId: null, ore: null }]))
      grid.set(entry.deal_id, row)
    }
    const cell = row.get(entry.data)
    if (cell === undefined || cell.entryId !== null) continue
    row.set(entry.data, { entryId: entry.id, ore: entry.ore })
  }
  return grid
}

export function rowTotal(row: Map<string, GridCell>): string {
  return sumDecimalStrings([...row.values()].map((cell) => cell.ore), HOURS_SCALE)
}

export function columnTotal(
  grid: Map<string, Map<string, GridCell>>,
  iso: string,
): string {
  return sumDecimalStrings(
    [...grid.values()].map((row) => row.get(iso)?.ore ?? null),
    HOURS_SCALE,
  )
}

export function gridTotal(grid: Map<string, Map<string, GridCell>>): string {
  return sumDecimalStrings(
    [...grid.values()].flatMap((row) => [...row.values()].map((cell) => cell.ore)),
    HOURS_SCALE,
  )
}
```

- [ ] **Step 4: Write the component test**

```tsx
// apps/web/src/features/time/WeekGrid.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { WeekGrid } from './WeekGrid'

const DEAL = 'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa'
const server = setupServer()
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  vi.setSystemTime(new Date(2026, 2, 12))
})
afterEach(() => server.resetHandlers())
afterAll(() => {
  server.close()
  vi.useRealTimers()
})

const deals = () =>
  http.get('/api/deals', () =>
    HttpResponse.json({
      items: [
        {
          id: DEAL, nome: 'Progetto Alfa', customer_id: 'c', pipeline_stage_id: 's',
          valore_previsto: null, probabilita: 10, data_chiusura_prevista: null,
          owner_id: null, note: null, ore_preventivate: null, valore_preventivato: null,
          tariffa_oraria: null, custom_fields: {},
          created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      next_cursor: null,
    }),
  )

function renderGrid() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <WeekGrid />
    </QueryClientProvider>,
  )
}

describe('WeekGrid', () => {
  it('shows a row total, a column total and a grand total summed in integer hundredths', async () => {
    server.use(
      deals(),
      http.get('/api/time-entries', () =>
        HttpResponse.json({
          items: [
            { id: 'e1', deal_id: DEAL, data: '2026-03-09', ore: '2.50' },
            { id: 'e2', deal_id: DEAL, data: '2026-03-11', ore: '1.25' },
          ],
          next_cursor: null,
        }),
      ),
    )
    renderGrid()
    expect(await screen.findByText('Progetto Alfa')).toBeInTheDocument()
    expect(await screen.findByTestId(`row-total-${DEAL}`)).toHaveTextContent('3,75')
    expect(await screen.findByTestId('column-total-2026-03-09')).toHaveTextContent('2,5')
    expect(await screen.findByTestId('grid-total')).toHaveTextContent('3,75')
  })

  it('typing in an empty cell logs an hour for that deal and that day', async () => {
    const posted: unknown[] = []
    server.use(
      deals(),
      http.get('/api/time-entries', () => HttpResponse.json({ items: [], next_cursor: null })),
      http.post('/api/time-entries', async ({ request }) => {
        const body = await request.json()
        posted.push(body)
        return HttpResponse.json({ ...(body as object), id: 'new' }, { status: 201 })
      }),
    )
    renderGrid()
    const cell = await screen.findByLabelText(/Progetto Alfa, lunedì 9 marzo/i)
    await userEvent.type(cell, '3,5')
    await userEvent.tab()
    await waitFor(() => expect(posted).toHaveLength(1))
    // The comma the Italian keyboard produces is normalised to the dot the API's
    // Decimal parser wants -- the one place in this product a locale-specific input
    // shape has to be translated, and it is done here rather than in the service.
    expect(posted[0]).toMatchObject({ deal_id: DEAL, data: '2026-03-09', ore: '3.5' })
  })

  it('renders a banner and no grid when the request fails', async () => {
    server.use(
      deals(),
      http.get('/api/time-entries', () => HttpResponse.json({ detail: 'Boom' }, { status: 500 })),
    )
    renderGrid()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByTestId('grid-total')).not.toBeInTheDocument()
  })

  it('moves a whole week at a time', async () => {
    server.use(
      deals(),
      http.get('/api/time-entries', () => HttpResponse.json({ items: [], next_cursor: null })),
    )
    renderGrid()
    expect(await screen.findByText(/9 marzo/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /settimana precedente/i }))
    expect(await screen.findByText(/2 marzo/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 5: Implement the grid**

```tsx
// apps/web/src/features/time/WeekGrid.tsx
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { useDeals } from '@/features/deals/queries'
import { useSession } from '@/lib/auth'
import { formatHoursValue } from './columns'
import { useTimeEntries } from './queries'
import { WeekGridRow } from './WeekGridRow'
import { buildGrid, columnTotal, gridTotal, isoDate, shiftWeek, weekDays } from './week'

/**
 * The screen that attacks the real failure mode. §13 argues it explicitly: the way a
 * freelancer's time tracking fails is not "I forgot to stop the timer", it is **"I never
 * entered Tuesday"**. A stopwatch needs a live-session entity, a recovery story for the
 * closed browser and another for the second device — three mechanisms — and does nothing
 * about Tuesday. A grid where a week is visibly incomplete does.
 */
export function WeekGrid() {
  const session = useSession()
  const [anchor, setAnchor] = useState(() => new Date())
  const days = useMemo(() => weekDays(anchor), [anchor])
  const entries = useTimeEntries({
    user_id: session?.id,
    da: days[0]?.iso,
    a: days[6]?.iso,
  })
  // Recently-worked deals, so the grid opens on the rows somebody actually needs rather
  // than on every deal ever created.
  const deals = useDeals()

  const grid = useMemo(
    () => buildGrid(entries.data?.items ?? [], days),
    [entries.data, days],
  )
  const dealNames = useMemo(
    () => new Map((deals.data?.items ?? []).map((deal) => [deal.id, deal.nome])),
    [deals.data],
  )
  // Rows: every deal with an entry this week, plus every open deal, so a week can be
  // started from nothing. Deduplicated by id, order stable by deal name.
  const rows = useMemo(() => {
    const ids = new Set<string>([...grid.keys()])
    for (const deal of deals.data?.items ?? []) ids.add(deal.id)
    return [...ids].sort((left, right) =>
      (dealNames.get(left) ?? '').localeCompare(dealNames.get(right) ?? '', 'it'),
    )
  }, [grid, deals.data, dealNames])

  if (entries.isError || deals.isError) {
    return <QueryErrorBanner error={entries.error ?? deals.error} />
  }

  return (
    <div className="space-y-4 p-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ore</h1>
          <p className="text-muted-foreground">
            {days[0]?.label} — {days[6]?.label}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            aria-label="Settimana precedente"
            onClick={() => setAnchor((current) => shiftWeek(current, -1))}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button variant="outline" onClick={() => setAnchor(new Date())}>
            Questa settimana
          </Button>
          <Button
            variant="outline"
            size="icon"
            aria-label="Settimana successiva"
            onClick={() => setAnchor((current) => shiftWeek(current, 1))}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </header>

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-muted/40">
              <th scope="col" className="p-2 text-left font-medium">
                Deal
              </th>
              {days.map((day) => (
                <th key={day.iso} scope="col" className="p-2 text-center font-medium">
                  <span className="block">{day.short}</span>
                  <span className="block text-xs text-muted-foreground">
                    {day.iso.slice(8)}
                  </span>
                </th>
              ))}
              <th scope="col" className="p-2 text-right font-medium">
                Totale
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((dealId) => (
              <WeekGridRow
                key={dealId}
                dealId={dealId}
                dealName={dealNames.get(dealId) ?? dealId}
                days={days}
                row={grid.get(dealId)}
              />
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t bg-muted/40 font-medium">
              <th scope="row" className="p-2 text-left">
                Totale
              </th>
              {days.map((day) => (
                <td
                  key={day.iso}
                  data-testid={`column-total-${day.iso}`}
                  className="p-2 text-center tabular-nums"
                >
                  {formatHoursValue(columnTotal(grid, day.iso))}
                </td>
              ))}
              <td data-testid="grid-total" className="p-2 text-right tabular-nums">
                {formatHoursValue(gridTotal(grid))}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        La tariffa viene congelata sulla voce quando la registri. Una cella con più voci
        nello stesso giorno mostra la prima: l&apos;elenco completo è nella tab «Ore» del
        deal.
      </p>
    </div>
  )
}
```

```tsx
// apps/web/src/features/time/WeekGridRow.tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/ui/input'
import { toProblem } from '@/lib/api'
import { formatHoursValue } from './columns'
import { useDeleteTimeEntry, useLogTime, useUpdateTimeEntry } from './queries'
import { rowTotal, type GridCell, type WeekDay } from './week'

const EMPTY_ROW = new Map<string, GridCell>()

interface WeekGridRowProps {
  dealId: string
  dealName: string
  days: WeekDay[]
  row: Map<string, GridCell> | undefined
}

/**
 * `"3,5"` -> `"3.5"`. The one place a locale-specific *input* shape is translated in
 * this product: an Italian keyboard produces a comma, and the API's `Decimal` parser
 * wants a dot. Done here rather than in the service, because the service must keep
 * accepting exactly one canonical form — a backend that guessed between `1,500` as
 * "one and a half" and "one thousand five hundred" would be the ambiguity this
 * translation exists to keep out of it.
 */
function normaliseHours(raw: string): string {
  return raw.trim().replace(',', '.')
}

export function WeekGridRow({ dealId, dealName, days, row }: WeekGridRowProps) {
  const cells = row ?? EMPTY_ROW
  const [draft, setDraft] = useState<Record<string, string>>({})
  const log = useLogTime()
  const remove = useDeleteTimeEntry()

  function commit(day: WeekDay, cell: GridCell | undefined) {
    const raw = draft[day.iso]
    if (raw === undefined) return
    setDraft((current) => {
      const next = { ...current }
      delete next[day.iso]
      return next
    })
    const value = normaliseHours(raw)
    const previous = cell?.ore ?? null
    if (value === (previous ?? '')) return

    if (value === '') {
      // Cleared: the honest action is a reversible soft delete, not an entry of zero
      // hours -- `ore > 0` is the rule, and a zero-hour row is not a row (§2.2).
      if (cell?.entryId) {
        remove.mutate(
          { entryId: cell.entryId, dealId },
          { onError: (error) => toast.error(toProblem(error).detail) },
        )
      }
      return
    }
    if (cell?.entryId) {
      // A hook per entry would break the rules of hooks inside a loop, so the mutation
      // is built here with the id it needs. `useUpdateTimeEntry` takes the id at
      // construction, which is why this branch cannot reuse a single shared instance.
      toast.promise(
        fetch(`/api/time-entries/${cell.entryId}`, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ ore: value }),
        }).then((response) => {
          if (!response.ok) throw new Error('patch failed')
        }),
        { loading: 'Salvataggio…', success: 'Ore aggiornate', error: 'Modifica non riuscita' },
      )
      return
    }
    log.mutate(
      {
        deal_id: dealId,
        data: day.iso,
        ore: value,
        // A grid cell has no description field: typing a number is the whole point of
        // the screen. The default is honest about where the entry came from and is
        // editable in the deal's Ore tab, where there is room for it.
        descrizione: `Attività del ${day.iso}`,
      },
      { onError: (error) => toast.error(toProblem(error).detail) },
    )
  }

  return (
    <tr className="border-b last:border-0">
      <th scope="row" className="p-2 text-left font-normal">
        {dealName}
      </th>
      {days.map((day) => {
        const cell = cells.get(day.iso)
        return (
          <td key={day.iso} className="p-1 text-center">
            <Input
              aria-label={`${dealName}, ${day.label}`}
              inputMode="decimal"
              className="h-9 w-16 text-center tabular-nums"
              value={draft[day.iso] ?? cell?.ore ?? ''}
              onChange={(event) =>
                setDraft((current) => ({ ...current, [day.iso]: event.target.value }))
              }
              onBlur={() => commit(day, cell)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') event.currentTarget.blur()
              }}
            />
          </td>
        )
      })}
      <td data-testid={`row-total-${dealId}`} className="p-2 text-right tabular-nums">
        {formatHoursValue(rowTotal(cells))}
      </td>
    </tr>
  )
}
```

**Replace the raw `fetch` before committing.** The `commit` branch above uses `fetch` as a placeholder shape only to show the request; the Global Constraints forbid `fetch` inside a component. Extract a `useUpdateHours()` mutation into `features/time/queries.ts` that takes `{entryId, ore, dealId}` as its variables rather than at construction, and call it here:

```ts
// apps/web/src/features/time/queries.ts -- append. Variables carry the id, so one
// mutation instance serves every cell in the grid; `useUpdateTimeEntry(id)` keeps its
// construction-time form for the single-entry form, where there is exactly one id.
export function useUpdateHours() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId, ore }: { entryId: string; ore: string; dealId?: string }) =>
      unwrap(
        api.PATCH('/api/time-entries/{entry_id}', {
          params: { path: { entry_id: entryId } },
          body: { ore } as unknown as TimeEntryUpdateBody,
        }),
      ),
    onSuccess: (_data, variables) => invalidateAfterWrite(queryClient, variables.dealId),
  })
}
```

and in `WeekGridRow`, replace the `toast.promise(fetch(...))` block with:

```tsx
      updateHours.mutate(
        { entryId: cell.entryId, ore: value, dealId },
        { onError: (error) => toast.error(toProblem(error).detail) },
      )
      return
```

declaring `const updateHours = useUpdateHours()` beside `const log = useLogTime()`.

- [ ] **Step 6: Add the route and the sidebar entry**

```tsx
// apps/web/src/routes/app/ore.tsx
import { createFileRoute } from '@tanstack/react-router'
import { WeekGrid } from '@/features/time/WeekGrid'

// Only `Route` is exported: a route file exporting anything else opts that route out of
// the router plugin's automatic code-splitting, which `routeTree.gen.ts` warns about --
// the same reason `SettingsLayout` lives in `features/settings/` rather than in its
// route file.
export const Route = createFileRoute('/app/ore')({ component: WeekGrid })
```

```tsx
// apps/web/src/components/AppShell.tsx -- add to the existing nav item list, after Deal.
  { to: '/app/ore', label: 'Ore', icon: Clock },
```

with `import { Clock } from 'lucide-react'` added to that file's icon imports.

- [ ] **Step 7: Run the frontend suite**

Run: `pnpm -C apps/web exec vitest run src/features/time` and `pnpm -C apps/web tsc --noEmit`
Expected: PASS. The AST guard from Task 4A-16 must stay green — `week.ts` sums hours only through `sumDecimalStrings`, and `WeekGridRow` never applies arithmetic to `cell.ore`.

- [ ] **Step 8: Commit**

```bash
git add apps/web
git commit -m "feat(web): the weekly hours grid at /ore, totals summed in integer hundredths"
```

---

### Task 4A-19: Settings — cost categories, rates, closed periods, and the costs panel

**Files:**
- Create: `apps/web/src/features/settings/CostCategoriesPanel.tsx`
- Create: `apps/web/src/features/settings/RatesPanel.tsx`
- Create: `apps/web/src/features/settings/PeriodsPanel.tsx`
- Create: `apps/web/src/features/settings/queries.timetracking.ts`
- Create: `apps/web/src/features/costs/CostsPanel.tsx`
- Create: `apps/web/src/features/costs/CostForm.tsx`
- Create: `apps/web/src/features/costs/columns.tsx`
- Create: `apps/web/src/routes/app/impostazioni/{categorie-costo,tariffe,periodi}.tsx`
- Modify: `apps/web/src/features/settings/SettingsLayout.tsx` (three new tabs)
- Modify: `apps/web/src/features/time/TimeEntriesTab.tsx` (mount `CostsPanel` below the hours table)
- Test: `apps/web/src/features/settings/PeriodsPanel.test.tsx`
- Test: `apps/web/src/features/costs/CostsPanel.test.tsx`

**Interfaces:**
- Consumes: `useCosts`, `useCostCategories`, `useCreateCost`, `useUpdateCost`, `useDeleteCost` (4A-16); `useUsers` (`@/features/settings/queries`); `useDeal` (`@/features/deals/queries`); `useIsAdmin`; `DataTable`; `QueryErrorBanner`; `DynamicForm`.
- Produces:
  ```tsx
  // features/settings/queries.timetracking.ts
  export function useCreateCostCategory(): ...
  export function useUpdateCostCategory(id: string): ...
  export function useArchiveCostCategory(): ...
  export function useUnarchiveCostCategory(): ...
  export function useSeedCostCategories(): ...
  export function usePeriodLocks(anno?: number): UseQueryResult<PeriodLock[]>
  export function useClosePeriod(): UseMutationResult<PeriodLock, unknown, { anno: number; mese: number }>
  export function useReopenPeriod(): UseMutationResult<void, unknown, { anno: number; mese: number }>
  export function useSetUserRates(userId: string): ...
  export function useSetDealRate(dealId: string): ...
  export type PeriodLock = components['schemas']['PeriodLockRead']

  // panels
  export function CostCategoriesPanel(): JSX.Element
  export function RatesPanel(): JSX.Element
  export function PeriodsPanel(): JSX.Element
  export function CostsPanel({ dealId }: { dealId?: string }): JSX.Element
  export function CostForm(props: CostFormProps): JSX.Element
  export function buildCostColumns(categories: CostCategory[], customFields: FieldDefinition[]): ColumnDef<DataTableFeatures, Cost>[]
  ```
  `SettingsLayout.TABS` gains `{ value: 'categorie-costo', label: 'Categorie costo' }`, `{ value: 'tariffe', label: 'Tariffe' }` and `{ value: 'periodi', label: 'Periodi' }`. All three are admin-only at the service layer, so they sit inside the existing `useIsAdmin` gate with no new gate of their own.

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/features/settings/PeriodsPanel.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { PeriodsPanel } from './PeriodsPanel'

const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <PeriodsPanel />
    </QueryClientProvider>,
  )
}

describe('PeriodsPanel', () => {
  it('lists the closed months with who closed them and when', async () => {
    server.use(
      http.get('/api/period-locks', () =>
        HttpResponse.json([
          { anno: 2026, mese: 3, chiuso_il: '2026-04-02T10:00:00Z', chiuso_da: 'u1' },
        ]),
      ),
      http.get('/api/users', () =>
        HttpResponse.json([{ id: 'u1', nome: 'Ivan', email: 'i@x.test', ruolo: 'admin', attivo: true }]),
      ),
    )
    renderPanel()
    expect(await screen.findByText(/marzo 2026/i)).toBeInTheDocument()
    expect(await screen.findByText(/Ivan/)).toBeInTheDocument()
  })

  it('says plainly that closing is optional', async () => {
    server.use(
      http.get('/api/period-locks', () => HttpResponse.json([])),
      http.get('/api/users', () => HttpResponse.json([])),
    )
    renderPanel()
    // §6.4's deliberate property: somebody who closes nothing gets the previous
    // behaviour, and no screen demands a ritual before it works.
    expect(await screen.findByText(/chiudere un periodo non è obbligatorio/i)).toBeInTheDocument()
  })

  it('asks for confirmation before reopening, and shows the server error if it fails', async () => {
    server.use(
      http.get('/api/period-locks', () =>
        HttpResponse.json([
          { anno: 2026, mese: 3, chiuso_il: '2026-04-02T10:00:00Z', chiuso_da: null },
        ]),
      ),
      http.get('/api/users', () => HttpResponse.json([])),
      http.delete('/api/period-locks/2026/3', () =>
        HttpResponse.json(
          {
            type: 'https://pigrocrm.dev/errors/permission_denied',
            title: 'Permesso negato', status: 403,
            detail: 'reopen_period requires one of [admin], actor has collaboratore',
            code: 'permission_denied', instance: '/api/period-locks/2026/3',
          },
          { status: 403, headers: { 'content-type': 'application/problem+json' } },
        ),
      ),
    )
    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: /riapri/i }))
    await userEvent.click(await screen.findByRole('button', { name: /conferma/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/requires one of/i))
  })

  it('renders a banner, never an empty list, when the request fails', async () => {
    server.use(
      http.get('/api/period-locks', () => HttpResponse.json({ detail: 'Boom' }, { status: 500 })),
      http.get('/api/users', () => HttpResponse.json([])),
    )
    renderPanel()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/nessun periodo chiuso/i)).not.toBeInTheDocument()
  })
})
```

```tsx
// apps/web/src/features/costs/CostsPanel.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { CostsPanel } from './CostsPanel'

const DEAL = 'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa'
const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const cost = (overrides = {}) => ({
  id: 'c1', deal_id: DEAL, category_id: 'cat1', data: '2026-03-05',
  importo: '2500.50', descrizione: 'Licenza', fornitore: 'ACME', document_id: null,
  custom_fields: {}, created_at: '2026-03-05T00:00:00Z', updated_at: '2026-03-05T00:00:00Z',
  deleted_at: null, ...overrides,
})

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CostsPanel dealId={DEAL} />
    </QueryClientProvider>,
  )
}

describe('CostsPanel', () => {
  it('formats amounts with a forced thousands separator and resolves the category name', async () => {
    server.use(
      http.get('/api/costs', () => HttpResponse.json({ items: [cost()], next_cursor: null })),
      http.get('/api/cost-categories', () =>
        HttpResponse.json([
          { id: 'cat1', nome: 'Software e licenze', posizione: 1, code: 'software_licenze', archiviata: false, created_at: 'x', updated_at: 'x' },
        ]),
      ),
      http.get('/api/schema/cost', () =>
        HttpResponse.json({ entity_type: 'cost', native_fields: [], custom_fields: [] }),
      ),
    )
    renderPanel()
    expect(await screen.findByText('2.500,50 €')).toBeInTheDocument()
    expect(await screen.findByText('Software e licenze')).toBeInTheDocument()
  })

  it('shows a negative amount as a refund rather than as an error', async () => {
    server.use(
      http.get('/api/costs', () =>
        HttpResponse.json({ items: [cost({ importo: '-45.50' })], next_cursor: null }),
      ),
      http.get('/api/cost-categories', () => HttpResponse.json([])),
      http.get('/api/schema/cost', () =>
        HttpResponse.json({ entity_type: 'cost', native_fields: [], custom_fields: [] }),
      ),
    )
    renderPanel()
    expect(await screen.findByText('-45,50 €')).toBeInTheDocument()
    expect(await screen.findByText(/rimborso/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pnpm -C apps/web exec vitest run src/features/settings/PeriodsPanel.test.tsx src/features/costs`
Expected: FAIL — both imports unresolved.

- [ ] **Step 3: Write the settings query module**

```ts
// apps/web/src/features/settings/queries.timetracking.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

export type PeriodLock = components['schemas']['PeriodLockRead']
type CostCategoryCreateBody = components['schemas']['CostCategoryCreate']
type CostCategoryUpdateBody = components['schemas']['CostCategoryUpdate']
type UserRatesBody = components['schemas']['UserRatesUpdate']
type DealRateBody = components['schemas']['DealRateUpdate']

/** Invalidates every list that shows a category, archived or not, because the panel
 *  toggles between the two views and a stale cache is what makes an archive look like
 *  it did nothing. */
function invalidateCategories(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ['cost-categories'] })
}

export function useCreateCostCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CostCategoryCreateBody) =>
      unwrap(api.POST('/api/cost-categories', { body })),
    onSuccess: () => invalidateCategories(queryClient),
  })
}

export function useUpdateCostCategory(categoryId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CostCategoryUpdateBody) =>
      unwrap(
        api.PATCH('/api/cost-categories/{category_id}', {
          params: { path: { category_id: categoryId } },
          body,
        }),
      ),
    onSuccess: () => invalidateCategories(queryClient),
  })
}

export function useArchiveCostCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (categoryId: string) =>
      unwrap(
        api.POST('/api/cost-categories/{category_id}/archive', {
          params: { path: { category_id: categoryId } },
        }),
      ),
    onSuccess: () => invalidateCategories(queryClient),
  })
}

export function useUnarchiveCostCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (categoryId: string) =>
      unwrap(
        api.POST('/api/cost-categories/{category_id}/unarchive', {
          params: { path: { category_id: categoryId } },
        }),
      ),
    onSuccess: () => invalidateCategories(queryClient),
  })
}

export function useSeedCostCategories() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/cost-categories/seed', {})),
    onSuccess: () => invalidateCategories(queryClient),
  })
}

export function usePeriodLocks(anno?: number) {
  return useQuery({
    queryKey: queryKeys.periodLocks(anno),
    queryFn: () =>
      unwrap(api.GET('/api/period-locks', { params: { query: anno ? { anno } : {} } })),
  })
}

export function useClosePeriod() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { anno: number; mese: number }) =>
      unwrap(api.POST('/api/period-locks', { body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['period-locks'] })
      // Closing a month changes what can still be written into the past, so every
      // hours and costs list is now answering a different question.
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeEntries() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.costs() })
    },
  })
}

export function useReopenPeriod() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ anno, mese }: { anno: number; mese: number }) =>
      unwrap(
        api.DELETE('/api/period-locks/{anno}/{mese}', { params: { path: { anno, mese } } }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['period-locks'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeEntries() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.costs() })
    },
  })
}

export function useSetUserRates(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UserRatesBody) =>
      unwrap(api.PUT('/api/users/{user_id}/rates', { params: { path: { user_id: userId } }, body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users })
      // Deliberately does NOT invalidate any time-entry cache: a rate change cannot
      // move an already-written row (§5), so refetching them would suggest it might.
      void queryClient.invalidateQueries({ queryKey: ['deal-rates'] })
    },
  })
}

export function useSetDealRate(dealId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: DealRateBody) =>
      unwrap(api.PUT('/api/deals/{deal_id}/rate', { params: { path: { deal_id: dealId } }, body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.deal(dealId) })
      void queryClient.invalidateQueries({ queryKey: ['deal-rates'] })
    },
  })
}
```

- [ ] **Step 4: Write `PeriodsPanel`**

```tsx
// apps/web/src/features/settings/PeriodsPanel.tsx
import { useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useUsers } from './queries'
import { useClosePeriod, usePeriodLocks, useReopenPeriod } from './queries.timetracking'

const MESI = [
  'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
  'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre',
]

/** `marzo 2026`. The same long-form Italian label `period_label` produces on the
 *  backend, so a `Conflict` naming a month and this list read identically. */
function label(anno: number, mese: number): string {
  return `${MESI[mese - 1]} ${anno}`
}

const stamp = new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' })

export function PeriodsPanel() {
  const locks = usePeriodLocks()
  const users = useUsers()
  const close = useClosePeriod()
  const reopen = useReopenPeriod()
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [pending, setPending] = useState<{ anno: number; mese: number } | null>(null)
  const now = new Date()
  const [mese, setMese] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`,
  )

  if (locks.isError) return <QueryErrorBanner error={locks.error} />

  const names = new Map((users.data ?? []).map((user) => [user.id, user.nome]))

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Periodi chiusi</h2>
        <p className="text-sm text-muted-foreground">
          Chiudere un periodo non è obbligatorio. Serve quando i numeri di un mese sono
          già stati riportati: da quel momento nessuna voce di ore e nessun costo datati
          in quel mese possono essere creati, modificati o cancellati. Le fatture hanno
          regole proprie e non vengono toccate.
        </p>
      </div>

      {problem && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {problem.detail}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="periodo-da-chiudere">Chiudi il mese</Label>
          <Input
            id="periodo-da-chiudere"
            type="month"
            value={mese}
            onChange={(event) => setMese(event.target.value)}
            className="w-40"
          />
        </div>
        <Button
          disabled={close.isPending}
          onClick={() => {
            const [anno, numero] = mese.split('-').map(Number)
            setProblem(null)
            close.mutate(
              { anno: anno ?? 0, mese: numero ?? 0 },
              { onError: (error) => setProblem(toProblem(error)) },
            )
          }}
        >
          Chiudi periodo
        </Button>
      </div>

      <ul className="divide-y rounded-lg border">
        {(locks.data ?? []).map((lock) => (
          <li key={`${lock.anno}-${lock.mese}`} className="flex items-center justify-between p-3">
            <div>
              <p className="font-medium">{label(lock.anno, lock.mese)}</p>
              <p className="text-xs text-muted-foreground">
                Chiuso il {stamp.format(new Date(lock.chiuso_il))}
                {lock.chiuso_da ? ` da ${names.get(lock.chiuso_da) ?? lock.chiuso_da}` : ''}
              </p>
            </div>
            {pending?.anno === lock.anno && pending?.mese === lock.mese ? (
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => setPending(null)}>
                  Annulla
                </Button>
                <Button
                  variant="destructive"
                  disabled={reopen.isPending}
                  onClick={() => {
                    setProblem(null)
                    reopen.mutate(
                      { anno: lock.anno, mese: lock.mese },
                      {
                        onSuccess: () => setPending(null),
                        onError: (error) => setProblem(toProblem(error)),
                      },
                    )
                  }}
                >
                  Conferma
                </Button>
              </div>
            ) : (
              // Confirmed, and it leaves a trace: a period is not reopened by accident
              // and is not reopened in silence -- the service writes an activity.
              <Button variant="outline" onClick={() => setPending({ anno: lock.anno, mese: lock.mese })}>
                Riapri
              </Button>
            )}
          </li>
        ))}
        {locks.data?.length === 0 && !locks.isLoading && (
          <li className="p-3 text-sm text-muted-foreground">Nessun periodo chiuso.</li>
        )}
      </ul>
    </div>
  )
}
```

- [ ] **Step 5: Write `CostCategoriesPanel`, `RatesPanel`, `CostsPanel`, `CostForm` and `columns.tsx`**

`CostCategoriesPanel` follows `PipelinePanel.tsx`'s shape exactly — a list ordered by `posizione`, an inline rename, a «Nuova categoria» dialog, an Archivia/Ripristina toggle, an «Includi archiviate» checkbox, and a «Crea le categorie predefinite» button calling `useSeedCostCategories` shown only when the list is empty. `code` is never editable and is rendered as muted text beside the name, with the note: *«identità stabile: il nome si può rinominare, il codice no»*.

`RatesPanel` is two tables. The first lists users with `tariffa_oraria_default` and `costo_orario_default` as inline number inputs saved through `useSetUserRates`; the second lists deals with a non-null `tariffa_oraria` plus a deal picker to add one, saved through `useSetDealRate`. Both carry the same standing note above them:

```tsx
      <p className="text-sm text-muted-foreground">
        Cambiare una tariffa non modifica nessuna voce di ore già registrata: la tariffa
        viene copiata sulla riga quando la voce è creata, e nessun report la rilegge. Per
        riscrivere le tariffe di voci già esistenti serve il ricalcolo, che è
        un&apos;operazione esplicita sul singolo deal e rifiuta le voci già fatturate.
      </p>
```

```tsx
// apps/web/src/features/costs/columns.tsx
import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import { formatIsoDate, formatMoneyValue } from '@/features/time/columns'
import type { Cost, CostCategory } from './queries'

export function buildCostColumns(
  categories: CostCategory[],
  customFields: FieldDefinition[],
): ColumnDef<DataTableFeatures, Cost>[] {
  const names = new Map(categories.map((category) => [category.id, category.nome]))
  const native: ColumnDef<DataTableFeatures, Cost>[] = [
    { header: 'Data', id: 'data', accessorFn: (row) => formatIsoDate(row.data) },
    {
      header: 'Categoria',
      id: 'category_id',
      // Resolved from the list rather than embedded in the row: a category can be
      // renamed, and an archived one still has to show its name here, which is exactly
      // why archiving replaces deletion.
      accessorFn: (row) => names.get(row.category_id) ?? '—',
    },
    { header: 'Descrizione', accessorKey: 'descrizione' },
    { header: 'Fornitore', id: 'fornitore', accessorFn: (row) => row.fornitore ?? '—' },
    {
      header: 'Importo',
      id: 'importo',
      // Straight from the API string. A negative amount is a refund or a credit note
      // received (§4.4), so it is labelled rather than treated as an error.
      accessorFn: (row) =>
        `${formatMoneyValue(row.importo)}${row.importo.startsWith('-') ? ' (rimborso)' : ''}`,
    },
    {
      header: 'Giustificativo',
      id: 'document_id',
      accessorFn: (row) => (row.document_id === null ? '—' : 'allegato'),
    },
  ]
  const custom: ColumnDef<DataTableFeatures, Cost>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))
  return [...native, ...custom]
}
```

`CostsPanel` mirrors `TimeEntriesTab`'s structure: `useCosts({deal_id})`, `useCostCategories()`, `useEntitySchema('cost')`, a `QueryErrorBanner` on `isError`, a `DataTable` with `buildCostColumns`, and a «Registra costo» button opening `CostForm`. `CostForm` copies `TimeEntryForm`'s two-namespace state verbatim with `NATIVE_FIELDS` of `data` (date), `importo` (currency), `descrizione` (textarea), `fornitore` (text) and a category `select` built from the active categories, plus the same `isBlank` helper and the same `""`-clears-native / `null`-clears-custom submit rules.

- [ ] **Step 6: Register the three settings routes and tabs**

```tsx
// apps/web/src/routes/app/impostazioni/categorie-costo.tsx
import { createFileRoute } from '@tanstack/react-router'
import { CostCategoriesPanel } from '@/features/settings/CostCategoriesPanel'

export const Route = createFileRoute('/app/impostazioni/categorie-costo')({
  component: CostCategoriesPanel,
})
```

```tsx
// apps/web/src/routes/app/impostazioni/tariffe.tsx
import { createFileRoute } from '@tanstack/react-router'
import { RatesPanel } from '@/features/settings/RatesPanel'

export const Route = createFileRoute('/app/impostazioni/tariffe')({ component: RatesPanel })
```

```tsx
// apps/web/src/routes/app/impostazioni/periodi.tsx
import { createFileRoute } from '@tanstack/react-router'
import { PeriodsPanel } from '@/features/settings/PeriodsPanel'

export const Route = createFileRoute('/app/impostazioni/periodi')({ component: PeriodsPanel })
```

```tsx
// apps/web/src/features/settings/SettingsLayout.tsx -- extend TABS. All three are
// admin-only at the service layer (CostCategoryService and PeriodLockService both call
// actor.require_admin on every write; so do update_user_rates and update_deal_rate), so
// they sit inside the existing useIsAdmin gate with no new gate of their own.
const TABS = [
  { value: 'campi', label: 'Campi' },
  { value: 'pipeline', label: 'Pipeline' },
  { value: 'utenti', label: 'Utenti' },
  { value: 'categorie-costo', label: 'Categorie costo' },
  { value: 'tariffe', label: 'Tariffe' },
  { value: 'periodi', label: 'Periodi' },
] as const
```

Mount `CostsPanel` in the deal's Ore tab, below the hours table:

```tsx
// apps/web/src/features/time/TimeEntriesTab.tsx -- after the DataTable, before the forms.
      <CostsPanel dealId={dealId} />
```

with `import { CostsPanel } from '@/features/costs/CostsPanel'`. Costs sit on the Ore tab in 4A rather than on an «Economia» tab because that tab does not exist until 4B, and a cost with nowhere to be entered is a cost nobody records.

- [ ] **Step 7: Run the frontend suite**

Run: `pnpm -C apps/web exec vitest run` and `pnpm -C apps/web tsc --noEmit`
Expected: PASS, `SettingsLayout.test.tsx` included — it asserts the tab list, so it needs its expectation extended in this same commit.

- [ ] **Step 8: Commit**

```bash
git add apps/web
git commit -m "feat(web): cost categories, rates and closed-period settings, plus the costs panel"
```

---

### Task 4A-20: End-to-end — a week of hours, a timesheet, a closed month

**Files:**
- Create: `apps/web/e2e/time-tracking.spec.ts`
- Modify: `apps/web/e2e/fixtures.ts` (a helper that seeds a deal and a rate through the API)

**Interfaces:**
- Consumes: the existing Playwright `test`/`expect` and the login fixture from `apps/web/e2e/fixtures.ts`; the API running against a real Postgres, as the existing E2E setup already arranges.
- Produces: `seedDealWithRate(request, {nome, tariffa}) -> Promise<{dealId: string, customerId: string}>` in `fixtures.ts`, reused by 4B's own spec (Task 4B-12).

- [ ] **Step 1: Write the failing spec**

```ts
// apps/web/e2e/time-tracking.spec.ts
import { expect, test } from './fixtures'

/**
 * Plan 4A's own definition of done, driven the way a user drives it. Deliberately not a
 * repeat of the unit tests: what is proven here is that the *screens* connect — the
 * grid writes an hour the deal tab then shows, the timesheet downloads as a real file,
 * and a closed month refuses a write with the server's own sentence on screen.
 */
test.describe('time tracking', () => {
  test('a week of hours, a timesheet and a closed month', async ({ page, request, login }) => {
    await login('admin')
    const { dealId } = await seedDealWithRate(request, {
      nome: 'Progetto E2E',
      tariffa: '80.000000',
    })

    // 1. The weekly grid writes an hour.
    await page.goto('/app/ore')
    const cell = page.getByLabel(/Progetto E2E, lun/i).first()
    await cell.fill('3,5')
    await cell.blur()
    await expect(page.getByTestId('grid-total')).toHaveText(/3,5/)

    // 2. The deal's Ore tab shows it, with the rate frozen from the deal.
    await page.goto(`/app/deal/${dealId}`)
    await page.getByRole('tab', { name: 'Ore' }).click()
    await expect(page.getByText('80,00 €/h (dal deal)')).toBeVisible()
    await expect(page.getByText('280,00 €')).toBeVisible()
    await expect(page.getByText(/Non è un ricavo: il ricavo è la fattura/)).toBeVisible()

    // 3. Raising the deal rate must not move the hour already written.
    await page.goto('/app/impostazioni/tariffe')
    await page.getByLabel(/Progetto E2E/).fill('150')
    await page.getByRole('button', { name: /salva tariffa/i }).click()
    await page.goto(`/app/deal/${dealId}`)
    await page.getByRole('tab', { name: 'Ore' }).click()
    await expect(page.getByText('80,00 €/h (dal deal)')).toBeVisible()
    await expect(page.getByText('280,00 €')).toBeVisible()

    // 4. The timesheet downloads, in both formats, as real files.
    const month = new Date().toISOString().slice(0, 7)
    await page.getByLabel(/rapporto ore del mese/i).fill(month)
    const xlsx = page.waitForEvent('download')
    await page.getByRole('link', { name: 'XLSX' }).click()
    const spreadsheet = await xlsx
    expect(await spreadsheet.suggestedFilename()).toMatch(/^rapporto-ore-\d{4}-\d{2}\.xlsx$/)

    // 5. A closed month refuses the next write, in the server's own words.
    const [anno, mese] = month.split('-')
    await page.goto('/app/impostazioni/periodi')
    await page.getByLabel(/chiudi il mese/i).fill(month)
    await page.getByRole('button', { name: /chiudi periodo/i }).click()
    await expect(page.getByText(new RegExp(`${anno}`))).toBeVisible()

    await page.goto('/app/ore')
    const blocked = page.getByLabel(/Progetto E2E, mar/i).first()
    await blocked.fill('2')
    await blocked.blur()
    await expect(page.getByText(/è chiuso/i)).toBeVisible()
  })

  test('a failed request never looks like an empty week', async ({ page, login }) => {
    await login('admin')
    await page.route('**/api/time-entries*', (route) => route.abort('failed'))
    await page.goto('/app/ore')
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByTestId('grid-total')).toHaveCount(0)
  })
})
```

```ts
// apps/web/e2e/fixtures.ts -- append. Seeds through the API rather than the UI: what
// this spec is testing is the hours screens, and driving five unrelated forms first
// would make a failure in any of them read as a time-tracking failure.
export async function seedDealWithRate(
  request: APIRequestContext,
  { nome, tariffa }: { nome: string; tariffa: string },
): Promise<{ dealId: string; customerId: string }> {
  const customer = await (
    await request.post('/api/customers', { data: { ragione_sociale: `${nome} SRL` } })
  ).json()
  const deal = await (
    await request.post('/api/deals', { data: { nome, customer_id: customer.id } })
  ).json()
  const rate = await request.put(`/api/deals/${deal.id}/rate`, {
    data: { tariffa_oraria: tariffa },
  })
  expect(rate.status()).toBe(204)
  return { dealId: deal.id, customerId: customer.id }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pnpm -C apps/web exec playwright test e2e/time-tracking.spec.ts`
Expected: FAIL — `seedDealWithRate` is not exported yet, and the grid's labels do not exist until Tasks 4A-18 and 4A-19 are merged. Run this task last in 4A.

- [ ] **Step 3: Seed the timesheet template in the E2E environment**

The PDF path needs the `Rapporto ore` template row. Add `pigrocrm seed-templates` and `POST /api/cost-categories/seed` to whatever the E2E harness already runs after migrations (the same place `pigrocrm createadmin` is invoked), so the environment is complete before the first spec runs. A missing template is a `ValidationFailed` naming the CLI command, which is the right failure but the wrong time to discover it.

- [ ] **Step 4: Run the whole E2E suite**

Run: `pnpm -C apps/web exec playwright test`
Expected: PASS, existing specs included.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "test(e2e): a week of hours, a downloaded timesheet and a refused write into a closed month"
```

---

## Definition of done for plan 4A

- `uv run pytest`, `uv run mypy` and `uv run ruff check .` all clean; `pnpm -C apps/web exec vitest run`, `pnpm -C apps/web tsc --noEmit` and `pnpm -C apps/web exec playwright test` all green.
- Spec criteria fully met by 4A: **2's first half** (a rate change does not move a written row — Task 4A-9), **2's second half** (a closed period refuses the write and an open one does not — Tasks 4A-8, 4A-9, 4A-12), **3** (`recalculate_rates` — Task 4A-11), **4's first and second parts** (Decimal sums with a float control, and no economic arithmetic in the browser — Tasks 4A-4, 4A-16), **8** (a deactivated user — Task 4A-9), **9** (the MCP ban in the build — Task 4A-13), **10** (the timesheet is a document, in both formats — Tasks 4A-14, 4A-15), **11** (twenty concurrent `log_time` — Tasks 4A-1, 4A-13).
- Criteria **1, 5, 6, 7, 12** and the third part of **4** are 4B's, and every one of them needs an invoice. They are not partially attempted here.

---

# PLAN 4B — Conto economico, preventivo vs consuntivo, ponte con le fatture, report fiscale

## Plan 4B — what must exist before it can start

**Read this before opening any task below.**

**4B cannot execute its central success criterion until slice 3 is merged into `main`.** Not "would be awkward without it" — cannot. Criterion 1 is *«a P&L revenue figure reconciles exactly with the invoices behind it»*, and it is asserted against a direct SQL query over `invoices`:

```sql
SELECT SUM(imponibile) FROM invoices
WHERE deal_id = :id AND tipo = 'fattura' AND stato = 'emessa' AND deleted_at IS NULL
```

There is no way to write that test, or the code it tests, without that table.

The reason is not a missing dependency that could be stubbed. It is the second of the three decisions the whole slice rests on: **revenue *is* the invoice.** There is no second notion of revenue in this design and none may be invented. The value derived from hours × rate is an **estimate** while no invoice exists, and from the moment one exists the revenue is that invoice's `imponibile` and the estimate stops being consulted at all (§3 decision 2, §7.1). A 4B that shipped against a stand-in — hours × rate as revenue, a `revenue` column, a hard-coded zero — would be shipping precisely the defect this slice exists to remove: the previous system's P&L used `offer.totalAmount`, the *offer's* amount, so a job invoiced for a third of its offer appeared at full revenue. Substituting anything for the invoice reintroduces that class of error under a new name.

**Concretely, the following must be true of `main` before Task 4B-1 begins:**

| Prerequisite | How to check | Which tasks die without it |
|---|---|---|
| `packages/core/src/pigrocrm/core/invoices/` exists, with `Invoice`, `InvoiceLine`, `InvoiceService` | `ls packages/core/src/pigrocrm/core/invoices/` | 4B-3, 4B-4, 4B-5, 4B-6, 4B-7, 4B-12 |
| `invoices` has `deal_id`, `tipo`, `stato`, `imponibile`, `totale`, `data_emissione`, `deleted_at`, and the `(tipo, stato)` `CHECK` | `\d invoices` | 4B-4, 4B-5, 4B-6 |
| `invoice_lines` exists with `quantita` `Numeric(12,6)` and `prezzo_unitario` `Numeric(12,6)` | `\d invoice_lines` | 4B-3, 4B-7 |
| `fiscal_profile` exists as a single row with `codice_regime` | `\d fiscal_profile` | 4B-2, 4B-8 |
| `InvoiceService.create(data: InvoiceCreate, actor) -> InvoiceRead` and `replace_lines(...)` exist, and `InvoiceCreate` accepts a `righe` list | read `invoices/schemas.py` | 4B-7 |
| The `RF01` synthetic fiscal profile fixture from slice 3 §14.8 exists in `packages/core/tests/` | `grep -rn "RF01" packages/core/tests/` | 4B-4 (the `imponibile` ≠ `totale` half of criterion 1) |
| Slice 3's architecture-test exclusion clause, if it landed, declares its own four names | read `packages/core/tests/test_architecture.py` | 4B-9 |

**If slice 3 slips, 4A ships anyway** and the «Economia» tab simply does not exist yet — which a user understands, unlike a tab showing zeros (§16). Nothing in 4A depends on anything in this section.

**One prerequisite of 4B is *not* about slice 3**, and it is the third blocking residual:

> **A14 — no spelling clears a numeric native column.** Every service applies its `Update` schema with `exclude_none=True`, so `ore_preventivate` has exactly two reachable states — `NULL` and `0.00` — which mean **opposite** things to the estimate-versus-actual report, and only `0.00` is writable: `""` gives 422, `null` is dropped by `exclude_none`, an omitted key does nothing. So the only reachable way to say "there is no estimate" after entering a wrong one is `0.00`, which this report would read as *"zero hours estimated, infinite overrun"*. Slice 3 sidestepped A14 by replacing invoice lines wholesale; that exit does not exist here. Task 4B-1 closes it, and it is a contract change on every service's `update` — which is exactly why the residual document says it deserved a task of its own and why doing it while it was merely an inconvenience would have been cheaper.

**Also carried in, and not fixed here:** **R1** and **A13** are closed by Tasks 4A-1 and 4A-2 and 4B assumes them done; **R5** closes for this slice's rate, category and fiscal columns only; **R10** stays open, which is why §11's MCP defence is structural; **B3** is answered for the margins view (mandatory period filter, paginated from the first commit) and stays open for the Kanban.

**One contradiction resolved against the spec, verified against the shipped code.** Spec §4.5 proposes adding `coefficiente_redditivita`, `aliquota_imposta_sostitutiva` and `aliquota_inps` to slice 3's existing `fiscal_profile` row rather than creating a second profile, on the grounds that the shipped table "contains the parameters FatturaPA needed and not the ones income calculation needs". Checked: **`fiscal_profile` does not exist at all** — `packages/core/src/pigrocrm/core/` has no `invoices/`, `grep -rn "fiscal_profile" packages apps` returns nothing, and the migration chain ends at `0003`. The spec's *decision* stands unchanged and is implemented in Task 4B-2 as an `ALTER TABLE`; its *premise* was understated, and that is one more reason 4B waits.

---

## Phase 4B-0 — The prerequisite and the two schema changes

### Task 4B-1: `exclude_unset` — a numeric column can be cleared (residual A14)

**Files:**
- Modify: `packages/core/src/pigrocrm/core/deals/service.py:195`
- Modify: `packages/core/src/pigrocrm/core/customers/service.py`, `people/service.py`, `pipeline/service.py`, `fields/service.py:82`, `documents/service.py:183`, `emitter/service.py`, `timetracking/service.py`, `timetracking/costs.py`, `timetracking/categories.py`, `invoices/service.py`
- Test: `packages/core/tests/test_update_semantics.py`

**Interfaces:**
- Consumes: nothing new. This is a contract change, applied identically everywhere.
- Produces: one shared helper, so the rule exists in one place rather than eleven:
  ```python
  # packages/core/src/pigrocrm/core/schemas.py  (new module)
  def supplied_changes(data: BaseModel, *, exclude: set[str] | None = None) -> dict[str, Any]
  ```
  Every `update` replaces `data.model_dump(exclude_none=True, exclude=...)` with `supplied_changes(data, exclude=...)`. **Contract after this task:** an omitted key changes nothing; a key supplied as `null` sets the column to `NULL`; a key supplied as `""` sets a text column to the empty string. Those are three distinct outcomes, and before this task the second was unreachable.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_update_semantics.py
"""A14, closed. Three spellings, three distinct outcomes, on every service.

Before this change `model_dump(exclude_none=True)` collapsed "supplied as null" into
"omitted", so no `Update` schema could clear a numeric or date column. On
`deals.ore_preventivate` that is not an inconvenience but a correctness defect: `NULL`
means "nobody estimated" and `0` means "estimated zero hours", the budget report treats
them as opposite, and only `0` was writable -- so a wrong estimate stayed stuck and read
as an infinite overrun.

The frontend contract is unchanged and stays as plan 1B fixed it: a native text column
clears on `""`, a custom field clears on `null`, an omitted key clears nothing. What
changes is that a native *numeric* or *date* column now clears on `null`, which nothing
could express before.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.deals.schemas import DealUpdate
from pigrocrm.core.deals.service import DealService

WRITER = Actor(id=None, type="user", role="collaboratore")


def test_an_omitted_key_changes_nothing(db_session: Session, seeded_deal_id: UUID) -> None:
    service = DealService(db_session)
    service.update(
        seeded_deal_id,
        DealUpdate(ore_preventivate=Decimal("100.00"), valore_preventivato=Decimal("10000.00")),
        WRITER,
    )
    after = service.update(seeded_deal_id, DealUpdate(nome="Rinominato"), WRITER)
    assert after.ore_preventivate == Decimal("100.00")
    assert after.valore_preventivato == Decimal("10000.00")


def test_a_key_supplied_as_null_clears_a_numeric_column(
    db_session: Session, seeded_deal_id: UUID
) -> None:
    """The state that was unreachable. `model_fields_set` is what distinguishes an
    explicit `null` from an absent key -- `exclude_none` cannot, because by the time it
    runs both are `None`."""
    service = DealService(db_session)
    service.update(seeded_deal_id, DealUpdate(ore_preventivate=Decimal("100.00")), WRITER)
    cleared = service.update(
        seeded_deal_id, DealUpdate.model_validate({"ore_preventivate": None}), WRITER
    )
    assert cleared.ore_preventivate is None


def test_a_key_supplied_as_null_clears_a_date_column(
    db_session: Session, seeded_deal_id: UUID
) -> None:
    service = DealService(db_session)
    service.update(
        seeded_deal_id, DealUpdate(data_chiusura_prevista=date(2026, 12, 31)), WRITER
    )
    cleared = service.update(
        seeded_deal_id, DealUpdate.model_validate({"data_chiusura_prevista": None}), WRITER
    )
    assert cleared.data_chiusura_prevista is None


def test_empty_string_still_clears_a_text_column(
    db_session: Session, seeded_deal_id: UUID
) -> None:
    """Unchanged, and it must stay unchanged: plan 1B's form contract is built on it and
    every existing form sends `""` for a cleared native text field."""
    service = DealService(db_session)
    service.update(seeded_deal_id, DealUpdate(note="qualcosa"), WRITER)
    assert service.update(seeded_deal_id, DealUpdate(note=""), WRITER).note == ""


def test_a_nullable_foreign_key_is_still_validated_when_supplied(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The trap this change opens if applied carelessly: with `exclude_none`, an
    explicit `owner_id: null` never reached `_check_owner`. Now it does, and it must be
    treated as "clear it" rather than sent to the repository as a lookup for `None` --
    which would raise `NotFound("user", None)`."""
    from uuid import uuid4

    import pytest

    from pigrocrm.core.errors import NotFound

    service = DealService(db_session)
    service.update(seeded_deal_id, DealUpdate(owner_id=seeded_user_id), WRITER)
    cleared = service.update(seeded_deal_id, DealUpdate.model_validate({"owner_id": None}), WRITER)
    assert cleared.owner_id is None
    with pytest.raises(NotFound):
        service.update(seeded_deal_id, DealUpdate(owner_id=uuid4()), WRITER)


def test_custom_fields_semantics_are_untouched(
    db_session: Session, seeded_deal_id: UUID
) -> None:
    """`custom_fields` is excluded from the dump in every service and handled
    separately, exactly as before: a `None` *inside* the dict removes that key, and that
    contract must not shift under this change."""
    service = DealService(db_session)
    assert service.update(
        seeded_deal_id, DealUpdate.model_validate({"custom_fields": None}), WRITER
    ).custom_fields == {}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_update_semantics.py -v`
Expected: the three `null`-clearing cases FAIL (the value survives untouched); the others pass.

- [ ] **Step 3: Add the shared helper**

```python
# packages/core/src/pigrocrm/core/schemas.py
"""The update contract, in one place.

Residual A14: every service used `data.model_dump(exclude_none=True)`, which collapses
"the caller supplied `null`" into "the caller omitted the key" -- so no `Update` schema
could clear a numeric or date column. On `deals.ore_preventivate` that is a correctness
defect and not a convenience: `NULL` means "nobody estimated" and `0` means "estimated
zero hours", the budget report of slice 4 §9.2 treats them as opposite, and only `0` was
writable.

`model_fields_set` is the distinction `exclude_none` cannot make: it records which keys
the caller actually provided, before defaults are filled in, so an explicit `null`
survives as a key present with value `None`.

Three outcomes, all now reachable:
  * key omitted   -> absent from the result -> the column is not touched;
  * key = `null`  -> present with `None`    -> the column is set to `NULL`;
  * key = `""`    -> present with `""`      -> a text column is set to the empty string.

The third is unchanged and must stay so: plan 1B's form contract is built on it, and
every shipped form sends `""` for a cleared native text field.
"""

from typing import Any

from pydantic import BaseModel


def supplied_changes(data: BaseModel, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """Only the fields the caller actually supplied, `None` included.

    `exclude` is for fields a service handles separately -- `custom_fields` in every
    domain, whose `None`-inside-the-dict semantics are different and must not be routed
    through here.
    """
    return data.model_dump(exclude_unset=True, exclude=exclude or set())
```

- [ ] **Step 4: Convert every service, and handle the nullable-FK consequence**

In each service's `update`, replace the dump and — wherever a nullable foreign key is validated — guard the lookup on the value rather than on the key's presence. `DealService.update` becomes:

```python
# packages/core/src/pigrocrm/core/deals/service.py -- inside update.
        changes = supplied_changes(data, exclude={"custom_fields"})
        _check_numbers(changes)
        # `is not None` on the value, not `in changes` on the key: with
        # `exclude_unset` an explicit `owner_id: null` now *reaches* this branch, and
        # sending `None` to the repository would raise `NotFound("user", None)` for
        # what is actually a valid instruction ("clear the owner"). `_check_owner`
        # already skips a `None`, so this is one guard, not two.
        if changes.get("owner_id") is not None:
            self._check_owner(changes["owner_id"])
```

`_check_numbers` must also tolerate `None` for every field it inspects — a cleared column has no sign to check. Add the guard at its top:

```python
# packages/core/src/pigrocrm/core/deals/service.py -- inside _check_numbers.
    for field in ("valore_previsto", "valore_preventivato", "ore_preventivate", "tariffa_oraria"):
        value = values.get(field)
        # `None` means "clear this column", which has no sign to validate. Before A14
        # was closed this branch was unreachable, because `exclude_none` had already
        # removed the key.
        if value is None:
            continue
        if value < 0:
            raise ValidationFailed("deal", field, "valore negativo", expected="un valore >= 0")
```

Apply the same two edits — `supplied_changes` plus `.get(fk) is not None` on every nullable FK — to `customers/service.py`, `people/service.py`, `pipeline/service.py`, `fields/service.py`, `documents/service.py`, `emitter/service.py`, `invoices/service.py`, and to `timetracking/service.py` and `timetracking/costs.py` from plan 4A. In `timetracking/costs.py` specifically, `_check_refs` already takes values rather than keys, so only the dump changes; and `_check_importo` gains the same `None` guard as `_check_numbers`, because `importo: null` now reaches it and a cleared amount is not a zero amount — for `costs.importo`, which is `NOT NULL`, an explicit `null` must be refused with `ValidationFailed("cost", "importo", "l'importo non può essere svuotato")` rather than allowed through to a database error.

`TimeEntryService.update` needs one further adjustment, because a rate is now clearable:

```python
# packages/core/src/pigrocrm/core/timetracking/service.py -- inside update, replacing
# the two `in changes` rate branches.
        # `in changes` on the key, not `is not None` on the value: clearing a rate is a
        # deliberate act ("this hour has no price"), and it is still `manuale` in origin
        # -- somebody chose it. A cleared rate must not silently re-resolve to the deal's,
        # which would be the "a report re-reads a rate column" failure §5 exists to
        # prevent, wearing an update's clothes.
        if "tariffa_applicata" in changes:
            changes["tariffa_origine"] = "manuale" if changes["tariffa_applicata"] is not None else "assente"
        if "costo_applicato" in changes:
            changes["costo_origine"] = "manuale" if changes["costo_applicato"] is not None else "assente"
```

- [ ] **Step 5: Run the entire backend suite**

Run: `uv run pytest -q`
Expected: PASS. This is the task with the widest blast radius in either plan — every `update` in the codebase changed contract. Any pre-existing test that relied on `null` being ignored is asserting the defect and its expectation must be corrected here, with a comment saying so, not worked around.

- [ ] **Step 6: Regenerate the client and check the frontend**

Run: `pnpm -C apps/web generate:api && pnpm -C apps/web tsc --noEmit && pnpm -C apps/web exec vitest run`
Expected: PASS. No form should need changing: every shipped form already sends `""` for a cleared native text field and omits untouched keys, and neither behaviour changes. If a form test fails it means that form was relying on `null` being ignored, which is now a real clear — fix the form, not the test.

- [ ] **Step 7: Commit**

```bash
git add packages/core apps/web/src/lib/api-types.ts
git commit -m "fix(core): exclude_unset so a null clears a native column, closing residual A14"
```

---

### Task 4B-2: `fiscal_profile` gains the three income-calculation columns

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/fiscal_models.py` (wherever slice 3 put `FiscalProfile`)
- Modify: the matching `FiscalProfileRead`/`FiscalProfileUpsert` schemas
- Create: `packages/core/migrations/versions/0005_analytics.py`
- Test: `packages/core/tests/test_fiscal_profile_income_columns.py`

**Interfaces:**
- Consumes: slice 3's `FiscalProfile` model and its service's existing activity-recording `upsert`.
- Produces three columns on the **existing single row**, all `Numeric(5,2)` nullable, with the defaults from the previous system's own profile:
  ```
  coefficiente_redditivita          Numeric(5,2) null   -- default 67.00
  aliquota_imposta_sostitutiva      Numeric(5,2) null   -- default  5.00
  aliquota_inps                     Numeric(5,2) null   -- default 26.07
  ```
  Plus the matching Pydantic `Field(max_digits=5, decimal_places=2, ge=0, le=100)` on both schemas.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_fiscal_profile_income_columns.py
"""§4.5. Three columns on the **existing** single row, not a second table.

Slice 1 §3 described a `FiscalProfile` holding "regime, ATECO coefficient, substitute
tax rate, INPS"; the table slice 3 delivered holds the parameters FatturaPA needed and
not the ones income calculation needs, which nobody used yet. They are the same concept,
so they go on the same single row: a second fiscal profile would create two answers to
"which regime am I in".

The three constants migrated out of the previous system's `App.jsx` -- `FORFETTARIO_PROFITABILITY_RATE
= 0.67`, `FORFETTARIO_SUBSTITUTE_TAX_RATE = 0.05`, `FORFETTARIO_INPS_RATE = 0.2607` --
become the defaults, as percentages. That migration is the final payment on the debt
slice 1 §2.2 cited as the empirical justification for this whole architecture.
"""

from decimal import Decimal

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.activities.service import ActivityService

ADMIN = Actor(id=None, type="system", role="admin")


def test_the_three_columns_exist_at_the_right_precision(db_engine: Engine) -> None:
    columns = {c["name"]: c for c in inspect(db_engine).get_columns("fiscal_profile")}
    for name in (
        "coefficiente_redditivita",
        "aliquota_imposta_sostitutiva",
        "aliquota_inps",
    ):
        assert name in columns, name
        assert columns[name]["nullable"] is True
    with db_engine.connect() as conn:
        precisions = dict(
            conn.execute(
                text(
                    "SELECT column_name, numeric_precision || ',' || numeric_scale "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'fiscal_profile' AND data_type = 'numeric'"
                )
            ).all()
        )
    assert precisions["coefficiente_redditivita"] == "5,2"
    assert precisions["aliquota_imposta_sostitutiva"] == "5,2"
    assert precisions["aliquota_inps"] == "5,2"


def test_there_is_exactly_one_fiscal_profile_table(db_engine: Engine) -> None:
    """Asserted so nobody later adds the second profile §4.5 rules out."""
    tables = set(inspect(db_engine).get_table_names())
    assert "fiscal_profile" in tables
    assert not {t for t in tables if t != "fiscal_profile" and "fiscal" in t}


def test_the_previous_systems_values_are_the_defaults(db_session: Session) -> None:
    from pigrocrm.core.invoices.fiscal_service import FiscalProfileService

    profile = FiscalProfileService(db_session).get(ADMIN)
    assert profile.coefficiente_redditivita == Decimal("67.00")
    assert profile.aliquota_imposta_sostitutiva == Decimal("5.00")
    assert profile.aliquota_inps == Decimal("26.07")


def test_changing_one_writes_an_activity(db_session: Session) -> None:
    """R5 closes for this table, and not for hygiene: the timeline is what reconstructs
    when a fiscal parameter changed, which is the same reason slice 3 §7.1 refused to
    historicise the profile at all."""
    from pigrocrm.core.invoices.fiscal_schemas import FiscalProfileUpsert
    from pigrocrm.core.invoices.fiscal_service import FiscalProfileService

    service = FiscalProfileService(db_session)
    before = service.get(ADMIN)
    service.upsert(
        FiscalProfileUpsert.model_validate({"aliquota_inps": Decimal("25.00")}), ADMIN
    )
    entries = ActivityService(db_session).timeline("fiscal_profile", before.id)
    assert entries[0].kind == "updated"
    assert "aliquota_inps" in str(entries[0].payload)


def test_an_out_of_range_rate_is_refused_before_the_database(db_session: Session) -> None:
    import pytest
    from pydantic import ValidationError

    from pigrocrm.core.invoices.fiscal_schemas import FiscalProfileUpsert

    for bad in (Decimal("-1.00"), Decimal("100.01"), Decimal("1.005")):
        with pytest.raises(ValidationError):
            FiscalProfileUpsert.model_validate({"aliquota_inps": bad})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_fiscal_profile_income_columns.py -v`
Expected: FAIL — the three columns are absent.

- [ ] **Step 3: Add the columns**

```python
# packages/core/src/pigrocrm/core/invoices/fiscal_models.py -- append to FiscalProfile.
    # §4.5. NOT a second table: slice 1 §3 described a FiscalProfile holding "regime,
    # ATECO coefficient, substitute tax rate, INPS", and the table slice 3 delivered
    # holds the FatturaPA parameters and not the income ones. Same concept, same single
    # row -- a second fiscal profile would create two answers to "which regime am I in".
    #
    # Percentages, so Numeric(5,2): `67.00`, not `0.67`. Stored the way a user reads and
    # types them, converted once in `analytics/fiscal.py`. Defaults are the previous system's own
    # profile -- the migration of FORFETTARIO_PROFITABILITY_RATE (0.67),
    # FORFETTARIO_SUBSTITUTE_TAX_RATE (0.05) and FORFETTARIO_INPS_RATE (0.2607) out of
    # App.jsx and into the service layer, which slice 1 §14 assigns to this slice.
    coefficiente_redditivita: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), default=Decimal("67.00")
    )
    aliquota_imposta_sostitutiva: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), default=Decimal("5.00")
    )
    aliquota_inps: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), default=Decimal("26.07")
    )
```

```python
# packages/core/src/pigrocrm/core/invoices/fiscal_schemas.py -- on both
# FiscalProfileUpsert and FiscalProfileRead. On Upsert:
RATE_MAX_DIGITS = 5
RATE_DECIMAL_PLACES = 2

    coefficiente_redditivita: Decimal | None = Field(
        default=None,
        max_digits=RATE_MAX_DIGITS,
        decimal_places=RATE_DECIMAL_PLACES,
        ge=0,
        le=100,
    )
    aliquota_imposta_sostitutiva: Decimal | None = Field(
        default=None, max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, ge=0, le=100
    )
    aliquota_inps: Decimal | None = Field(
        default=None, max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, ge=0, le=100
    )
# On Read the annotations are the bare `Decimal | None`: a Read schema validates values
# the database produced, so a bound there would reject a row the column legitimately
# holds.
```

- [ ] **Step 4: Write migration `0005`, part one**

```python
# packages/core/migrations/versions/0005_analytics.py
"""analytics: fiscal income columns, and the invoice_line foreign key on time_entries

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- the three income-calculation columns (Task 4B-2) ---------------------
    for column, default in (
        ("coefficiente_redditivita", "67.00"),
        ("aliquota_imposta_sostitutiva", "5.00"),
        ("aliquota_inps", "26.07"),
    ):
        op.add_column(
            "fiscal_profile", sa.Column(column, sa.Numeric(precision=5, scale=2), nullable=True)
        )
        # Backfilled on the existing row too, not only defaulted for new ones: there is
        # exactly one row and it already exists, so a NULL here would make the fiscal
        # report unavailable until somebody happened to open the settings screen.
        op.execute(
            sa.text(f"UPDATE fiscal_profile SET {column} = :value").bindparams(value=default)
        )

    # --- the real foreign key on time_entries (Task 4B-3) --------------------
    # Plan 4A created `invoice_line_id` as a bare Uuid because `invoice_lines` did not
    # exist then and 4A deliberately does not depend on slice 3. Now it does exist, so
    # the column becomes a real constraint. `ON DELETE SET NULL` is what lets slice 3's
    # wholesale line replacement (slice 3 §11) unbind and rebind hours without leaving
    # orphans, and without slice 4 having to touch the locked transaction of slice 3 §3.
    op.create_foreign_key(
        "fk_time_entries_invoice_line",
        "time_entries",
        "invoice_lines",
        ["invoice_line_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_time_entries_invoice_line", "time_entries", type_="foreignkey")
    op.drop_column("fiscal_profile", "aliquota_inps")
    op.drop_column("fiscal_profile", "aliquota_imposta_sostitutiva")
    op.drop_column("fiscal_profile", "coefficiente_redditivita")
```

Update `packages/core/tests/test_migrations.py`'s expected head from `"0004"` to `"0005"`.

- [ ] **Step 5: Run the test**

Run: `uv run pytest packages/core/tests/test_fiscal_profile_income_columns.py packages/core/tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/core
git commit -m "feat(fiscal): the three income-calculation columns on the single fiscal profile row"
```

---

### Task 4B-3: The `invoice_line_id` foreign key, and immutability narrowed to *issued*

**Files:**
- Modify: `packages/core/src/pigrocrm/core/timetracking/models.py` (`TimeEntry.invoice_line_id` gains the FK)
- Modify: `packages/core/src/pigrocrm/core/timetracking/service.py` (`billed_entry_ids` body only)
- Test: `packages/core/tests/test_billed_immutability.py`

**Interfaces:**
- Consumes: slice 3's `Invoice` and `InvoiceLine` models, and the `stato` values `bozza`/`emessa`/`annullata`.
- Produces: **no signature change anywhere.** `billed_entry_ids(session, entries) -> set[UUID]` keeps its name, parameters and return type; only its body changes, from "any non-null `invoice_line_id`" to §4.3's real rule. Every call site — `TimeEntryService.update`, `.soft_delete`, `.deal_summary`, `.recalculate_rates` — is untouched. That is the whole reason plan 4A routed all four through one function instead of writing `is not None` in four places.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_billed_immutability.py
"""§4.3, at full strength. The rule attaches to the **state of the invoice**, not to the
mere presence of the link, because a draft is still freely editable: while the invoice is
a draft the hours stay modifiable, and slice 3's wholesale line replacement unbinds and
rebinds them without orphans. The moment `issue()` commits, the bound hours are frozen --
without `issue()` having had to know they exist.

Part of criterion 5.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, ImmutableField
from pigrocrm.core.timetracking.schemas import TimeEntryCreate, TimeEntryUpdate
from pigrocrm.core.timetracking.service import TimeEntryService, billed_entry_ids

WRITER = Actor(id=None, type="user", role="collaboratore")


def test_an_hour_on_a_draft_invoice_is_still_editable(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, draft_invoice_line_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    entry = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
            ore=Decimal("2.00"), descrizione="x",
        ),
        WRITER,
    )
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": draft_invoice_line_id, "id": entry.id},
    )
    db_session.flush()

    assert billed_entry_ids(db_session, [db_session.get(type(entry), entry.id) or entry]) == set()
    updated = service.update(entry.id, TimeEntryUpdate(ore=Decimal("3.00")), WRITER)
    assert updated.ore == Decimal("3.00")


def test_issuing_the_invoice_freezes_the_bound_hour(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, issued_invoice_line_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    entry = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
            ore=Decimal("2.00"), descrizione="x",
        ),
        WRITER,
    )
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": issued_invoice_line_id, "id": entry.id},
    )
    db_session.flush()

    for field, value in [
        ("ore", Decimal("3.00")),
        ("data", date(2026, 3, 5)),
        ("tariffa_applicata", Decimal("99.000000")),
        ("descrizione", "Altro"),
    ]:
        with pytest.raises(ImmutableField) as excinfo:
            service.update(entry.id, TimeEntryUpdate(**{field: value}), WRITER)
        assert excinfo.value.details["field"] == field

    # `note_interne` stays mutable: it appears on no artefact.
    assert service.update(entry.id, TimeEntryUpdate(note_interne="ok"), WRITER).note_interne == "ok"

    with pytest.raises(Conflict):
        service.soft_delete(entry.id, WRITER)


def test_raw_sql_soft_delete_is_refused_by_the_check_even_for_a_draft(
    db_session: Session, seeded_entry_id: UUID, draft_invoice_line_id: UUID
) -> None:
    """The `CHECK` is deliberately wider than the service rule, and the difference has
    to be understood rather than smoothed over: it forbids deleting *any* entry bound to
    a line, a draft's included. A constraint that distinguished invoice state would have
    to read another table, i.e. be a trigger, and this project keeps that kind of
    invisible logic out of the database. Reaching it costs nothing -- take the entry off
    the draft first and `invoice_line_id` returns to NULL."""
    from sqlalchemy.exc import IntegrityError

    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": draft_invoice_line_id, "id": seeded_entry_id},
    )
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE time_entries SET deleted_at = now() WHERE id = :id"),
            {"id": seeded_entry_id},
        )
        db_session.flush()
    db_session.rollback()


def test_deleting_an_invoice_line_unbinds_rather_than_orphans(
    db_session: Session, seeded_entry_id: UUID, draft_invoice_line_id: UUID
) -> None:
    """`ON DELETE SET NULL`, which is what lets slice 3 replace a draft's lines wholesale
    without slice 4 participating in that transaction."""
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": draft_invoice_line_id, "id": seeded_entry_id},
    )
    db_session.flush()
    db_session.execute(
        text("DELETE FROM invoice_lines WHERE id = :line"), {"line": draft_invoice_line_id}
    )
    db_session.flush()
    remaining = db_session.execute(
        text("SELECT invoice_line_id FROM time_entries WHERE id = :id"), {"id": seeded_entry_id}
    ).scalar_one()
    assert remaining is None


def test_an_annulled_invoice_does_not_freeze_its_hours(
    db_session: Session, seeded_entry_id: UUID, annulled_invoice_line_id: UUID
) -> None:
    """Only `emessa` freezes. An annulled invoice keeps its number but not its revenue
    (§7.1) -- it is the struck-through page of a paper register -- so the hours behind it
    are CRM data again and can be re-invoiced."""
    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": annulled_invoice_line_id, "id": seeded_entry_id},
    )
    db_session.flush()
    entry = db_session.execute(
        text("SELECT id FROM time_entries WHERE id = :id"), {"id": seeded_entry_id}
    ).scalar_one()
    from pigrocrm.core.timetracking.models import TimeEntry

    assert billed_entry_ids(db_session, [db_session.get(TimeEntry, entry)]) == set()
```

Add three fixtures to `packages/core/tests/conftest.py`, each building a real invoice through slice 3's own service so the states are the ones that service produces rather than hand-written rows:

```python
# packages/core/tests/conftest.py (append)
@pytest.fixture
def draft_invoice_line_id(db_session: Session, seeded_deal_id: UUID) -> UUID:
    """A line on a `bozza`. Built through `InvoiceService` rather than inserted, so the
    `(tipo, stato)` CHECK and the line invariants are the real ones."""
    from pigrocrm.core.deals.models import Deal
    from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceLineCreate
    from pigrocrm.core.invoices.service import InvoiceService

    deal = db_session.get(Deal, seeded_deal_id)
    invoice = InvoiceService(db_session).create(
        InvoiceCreate(
            customer_id=deal.customer_id,
            deal_id=seeded_deal_id,
            tipo="fattura",
            righe=[
                InvoiceLineCreate(
                    descrizione="Attività",
                    quantita=Decimal("1.000000"),
                    prezzo_unitario=Decimal("100.000000"),
                    aliquota_iva=Decimal("0.00"),
                    natura="N2.2",
                )
            ],
        ),
        Actor.system(),
    )
    return db_session.execute(
        text("SELECT id FROM invoice_lines WHERE invoice_id = :inv ORDER BY numero_linea LIMIT 1"),
        {"inv": invoice.id},
    ).scalar_one()


@pytest.fixture
def issued_invoice_line_id(db_session: Session, draft_invoice_line_id: UUID) -> UUID:
    from pigrocrm.core.invoices.service import InvoiceService

    invoice_id = db_session.execute(
        text("SELECT invoice_id FROM invoice_lines WHERE id = :line"),
        {"line": draft_invoice_line_id},
    ).scalar_one()
    InvoiceService(db_session).issue_invoice(invoice_id, Actor.system())
    return draft_invoice_line_id


@pytest.fixture
def annulled_invoice_line_id(db_session: Session, issued_invoice_line_id: UUID) -> UUID:
    from pigrocrm.core.invoices.service import InvoiceService

    invoice_id = db_session.execute(
        text("SELECT invoice_id FROM invoice_lines WHERE id = :line"),
        {"line": issued_invoice_line_id},
    ).scalar_one()
    InvoiceService(db_session).annul_invoice(invoice_id, "errore di emissione", Actor.system())
    return issued_invoice_line_id
```

If slice 3's method names or signatures differ from these, adapt the fixtures to the shipped code — the shipped code governs — and record the difference in this task's commit message.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_billed_immutability.py -v`
Expected: `test_an_hour_on_a_draft_invoice_is_still_editable` and `test_an_annulled_invoice_does_not_freeze_its_hours` FAIL — 4A's superset freezes both. The others pass, which is the point: the narrowing must not loosen the issued case.

- [ ] **Step 3: Add the foreign key to the model and narrow the helper**

```python
# packages/core/src/pigrocrm/core/timetracking/models.py -- replacing the bare column.
    # Plan 4A created this as a bare `Uuid` because `invoice_lines` is a slice 3 table
    # and 4A deliberately does not depend on slice 3. Migration 0005 adds the real
    # constraint. `ON DELETE SET NULL` is what lets slice 3 replace a draft's lines
    # wholesale (slice 3 §11) without leaving orphans and without slice 4 having to join
    # the locked transaction of slice 3 §3 -- the part of the system that least wants new
    # participants.
    invoice_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("invoice_lines.id", ondelete="SET NULL"), default=None, index=True
    )
```

```python
# packages/core/src/pigrocrm/core/timetracking/service.py -- the body only. Signature,
# name and return type are unchanged, and no call site moves.
def billed_entry_ids(session: Session, entries: Sequence[TimeEntry]) -> set[UUID]:
    """Which of `entries` belong to a **line of an issued invoice** and are therefore
    frozen (§4.3).

    The rule attaches to the state of the invoice, not to the presence of the link,
    because a draft is still freely editable: while the invoice is a draft the hours stay
    modifiable and slice 3's wholesale line replacement unbinds and rebinds them without
    orphans; the moment `issue()` commits, the bound hours are frozen without `issue()`
    having had to know they exist.

    Only `emessa`. An **annulled** invoice keeps its number but not its revenue (§7.1) --
    the struck-through page of a paper register -- so its hours are CRM data again and can
    be re-invoiced. A **proforma** never freezes anything: it does not touch the register
    at all (slice 3 §5).

    One query, never one per entry: `deal_summary` calls this with every entry of a deal,
    and a per-row lookup would make the P&L quadratic in a deal's hours.
    """
    line_ids = {entry.invoice_line_id for entry in entries if entry.invoice_line_id is not None}
    if not line_ids:
        return set()
    issued = set(
        session.execute(
            select(InvoiceLine.id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                InvoiceLine.id.in_(line_ids),
                Invoice.tipo == "fattura",
                Invoice.stato == "emessa",
                Invoice.deleted_at.is_(None),
            )
        ).scalars()
    )
    return {entry.id for entry in entries if entry.invoice_line_id in issued}
```

with `from sqlalchemy import select` and `from pigrocrm.core.invoices.models import Invoice, InvoiceLine` added to that module's imports.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/core/tests/test_billed_immutability.py packages/core/tests/test_time_entries.py packages/core/tests/test_recalculate_rates.py -v`
Expected: PASS. Two of 4A's tests set `invoice_line_id` to a random UUID with raw SQL, which no longer resolves to an issued invoice — with the FK in place those inserts now fail outright. Convert both to the `issued_invoice_line_id` fixture in this same commit; they were asserting the right behaviour through a stand-in that has now been replaced by the real thing.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(timetracking): the real invoice_line FK, and freezing narrowed to issued invoices"
```

---

## Phase 4B-1 — The conto economico

### Task 4B-4: `deal_pnl` — and the figure that reconciles with its invoices exactly

**Files:**
- Create: `packages/core/src/pigrocrm/core/analytics/__init__.py`
- Create: `packages/core/src/pigrocrm/core/analytics/schemas.py`
- Create: `packages/core/src/pigrocrm/core/analytics/repository.py`
- Create: `packages/core/src/pigrocrm/core/analytics/service.py`
- Test: `packages/core/tests/test_deal_pnl.py`
- Test: `packages/core/tests/test_pnl_reconciliation.py` (criterion 1, in its own file so it can be pointed at)

**Interfaces:**
- Consumes: `Invoice`, `InvoiceLine` (slice 3); `TimeEntry`, `Cost` (4A-5); `money.{line_value, percentage_of, sum_hours, sum_money, ZERO_MONEY}`; `PipelineService.get`; `TimeEntryService.deal_summary` and `billed_entry_ids` (4A-9); `PeriodLockService.is_closed` (4A-8).
- Produces:
  ```python
  # analytics/schemas.py
  DealStato = Literal["in corso", "da fatturare", "chiuso"]

  class DealPnl(BaseModel):
      deal_id: UUID
      stato: DealStato
      ricavi: Decimal
      costi_diretti: Decimal
      costo_lavoro: Decimal
      margine_lordo: Decimal
      margine_percentuale: Decimal | None
      ore_totali: Decimal
      ore_fatturabili_non_fatturate: Decimal
      valore_maturato: Decimal
      ore_senza_tariffa: int
      fatture_emesse: int

  # analytics/repository.py
  class AnalyticsRepository:
      def __init__(self, session: Session) -> None
      def deal_revenue(self, deal_id: UUID) -> tuple[Decimal, int]
      def deal_direct_costs(self, deal_id: UUID) -> Decimal
      def revenue_in_range(self, da: date, a: date, customer_id: UUID | None) -> dict[UUID, Decimal]
      def costs_in_range(self, da: date, a: date, customer_id: UUID | None) -> tuple[dict[UUID, Decimal], Decimal]
      def labour_cost_in_range(self, da: date, a: date, customer_id: UUID | None) -> dict[UUID, Decimal]
      def hours_in_range(self, da: date, a: date, customer_id: UUID | None) -> dict[UUID, Decimal]
      def late_entry_count(self, da: date, a: date) -> int
      def annual_revenue(self, anno: int) -> Decimal
      def deals_in_range(self, da: date, a: date, customer_id: UUID | None) -> list[Deal]

  # analytics/service.py
  class AnalyticsService:
      def __init__(self, session: Session) -> None
      def deal_pnl(self, deal_id: UUID, actor: Actor) -> DealPnl
      def period_pnl(self, query: PeriodPnlQuery, actor: Actor) -> PeriodPnl              # Task 4B-5
      def budget_vs_actual(self, query: BudgetQuery, actor: Actor) -> BudgetPage          # Task 4B-6
      def bind_time_to_invoice(self, deal_id, data: BindTimeRequest, actor) -> InvoiceRead # Task 4B-7
      def get_fiscal_estimate(self, anno: int, actor: Actor) -> FiscalEstimate            # Task 4B-8
  ```
  Note `AnalyticsService` has **no** method named `list`, so the last-method rule does not arise for it; `AnalyticsRepository` has none either — every method returns a mapping or a scalar.

- [ ] **Step 1: Write the failing reconciliation test**

```python
# packages/core/tests/test_pnl_reconciliation.py
"""**Criterion 1.** A P&L revenue figure reconciles with the invoices behind it
**exactly, not approximately** — compared as `Decimal`, to the cent, against a direct
SQL query run on a path independent of the service.

This is the test that makes "revenue is the invoice" a property rather than a slogan.
The previous system's P&L used `offer.totalAmount` — the *offer's* amount — filtered to projects with
at least one non-draft invoice, so a job invoiced for a third of its offer appeared at
full revenue. There is no second notion of revenue here and none may be introduced.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.service import AnalyticsService

READER = Actor(id=None, type="user", role="readonly")


def test_revenue_equals_the_invoices_behind_it_to_the_cent(
    db_session: Session, deal_with_mixed_invoices
) -> None:
    """Three issued invoices, one annulled, one proforma. Only the three issued
    `fattura` rows count: a proforma is not revenue by definition (it never touches the
    register), and an annulled invoice keeps its number but not its revenue — the
    struck-through page of a paper register."""
    deal_id = deal_with_mixed_invoices
    pnl = AnalyticsService(db_session).deal_pnl(deal_id, READER)

    expected = db_session.execute(
        text(
            "SELECT COALESCE(SUM(imponibile), 0) FROM invoices "
            "WHERE deal_id = :id AND tipo = 'fattura' AND stato = 'emessa' "
            "  AND deleted_at IS NULL"
        ),
        {"id": deal_id},
    ).scalar_one()

    # Decimal, never float, and `==` rather than any tolerance: "exactly, not
    # approximately" is the criterion, and a `pytest.approx` here would pass for the
    # very drift this whole design exists to prevent.
    assert isinstance(pnl.ricavi, Decimal)
    assert pnl.ricavi == Decimal(expected)
    assert pnl.fatture_emesse == 3


def test_it_follows_imponibile_and_not_totale(
    db_session: Session, rf01_fiscal_profile, deal_with_vat_invoice
) -> None:
    """The `totale` includes VAT, which is not revenue: it is money collected on the
    State's behalf. Under the flat-rate regime the two coincide because the tax is zero,
    so the difference is not observable today — which is exactly why it is written and
    tested today, with the synthetic `RF01` profile slice 3 §14.8 introduces. The test
    fails if the P&L follows `totale`."""
    deal_id = deal_with_vat_invoice
    imponibile, totale = db_session.execute(
        text(
            "SELECT SUM(imponibile), SUM(totale) FROM invoices "
            "WHERE deal_id = :id AND tipo = 'fattura' AND stato = 'emessa' "
            "  AND deleted_at IS NULL"
        ),
        {"id": deal_id},
    ).one()
    assert imponibile != totale, "the fixture must produce a VAT-bearing invoice"

    pnl = AnalyticsService(db_session).deal_pnl(deal_id, READER)
    assert pnl.ricavi == Decimal(imponibile)
    assert pnl.ricavi != Decimal(totale)


def test_a_soft_deleted_invoice_leaves_the_figure(
    db_session: Session, deal_with_mixed_invoices
) -> None:
    """`deleted_at IS NULL` in the query, asserted rather than assumed: an invoice cannot
    normally be soft-deleted once issued (slice 3 §4's CHECK), so this is checked on a
    draft, which never contributed anyway — the point is that the filter is present."""
    deal_id = deal_with_mixed_invoices
    before = AnalyticsService(db_session).deal_pnl(deal_id, READER).ricavi
    db_session.execute(
        text(
            "UPDATE invoices SET deleted_at = now() "
            "WHERE deal_id = :id AND stato = 'bozza'"
        ),
        {"id": deal_id},
    )
    db_session.flush()
    assert AnalyticsService(db_session).deal_pnl(deal_id, READER).ricavi == before


def test_the_stated_figure_does_not_move_when_a_rate_moves(
    db_session: Session, deal_with_mixed_invoices, seeded_user_id: UUID
) -> None:
    """Criterion 2, at the P&L level rather than the entry level: the JSON is compared as
    a structure before and after both rate columns are raised."""
    from pigrocrm.core.auth.models import User
    from pigrocrm.core.deals.models import Deal

    deal_id = deal_with_mixed_invoices
    service = AnalyticsService(db_session)
    before = service.deal_pnl(deal_id, READER).model_dump(mode="json")

    db_session.get(Deal, deal_id).tariffa_oraria = Decimal("150.000000")
    db_session.get(User, seeded_user_id).tariffa_oraria_default = Decimal("120.000000")
    db_session.flush()

    assert service.deal_pnl(deal_id, READER).model_dump(mode="json") == before
```

- [ ] **Step 2: Write the failing behaviour test**

```python
# packages/core/tests/test_deal_pnl.py
"""§7.1's five decisions and §7.3's three states."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.schemas import CostCreate, TimeEntryCreate
from pigrocrm.core.timetracking.service import TimeEntryService

READER = Actor(id=None, type="user", role="readonly")
WRITER = Actor(id=None, type="user", role="collaboratore")


def test_an_incomplete_deal_does_not_lie(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """**Criterion 6.** An open deal with 20 hours and no invoice: revenue `0.00`, margin
    percentage `null` (not `"0.00"`), state "in corso", and the accrued value in a field
    whose name is not `ricavi`.

    Zero per cent means "everything I earned went out in costs"; here nothing has been
    earned. Two different facts, and the report does not flatten them."""
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
            ore=Decimal("20.00"), descrizione="Sviluppo",
            tariffa_applicata=Decimal("100.000000"), costo_applicato=Decimal("30.000000"),
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.ricavi == Decimal("0.00")
    assert pnl.margine_percentuale is None
    assert pnl.stato == "in corso"
    assert pnl.valore_maturato == Decimal("2000.00")
    assert pnl.costo_lavoro == Decimal("600.00")
    assert pnl.margine_lordo == Decimal("-600.00")
    # The accrued value is not revenue and lives under a different heading.
    assert "valore_maturato" in pnl.model_dump() and pnl.valore_maturato != pnl.ricavi


def test_costs_of_an_uninvoiced_deal_still_appear(
    db_session: Session, seeded_deal_id: UUID, seeded_category_id: UUID
) -> None:
    """The previous system's `projectCostRows` started from `offers.filter(offerKeysWithInvoices.has(...))`,
    so the expenses of a job in progress were invisible to every summary. Every deal has
    its own P&L here, invoiced or not, with the **state** beside it instead of the
    exclusion (§7.3)."""
    CostService(db_session).create(
        CostCreate(
            deal_id=seeded_deal_id, category_id=seeded_category_id, data=date(2026, 3, 1),
            importo=Decimal("500.00"), descrizione="Licenze",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.costi_diretti == Decimal("500.00")
    assert pnl.margine_lordo == Decimal("-500.00")


def test_labour_cost_includes_non_billable_hours(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """An internal meeting costs exactly what it would cost if it were billed, and
    excluding it would make the deal that demanded more of them look more profitable."""
    service = TimeEntryService(db_session)
    for fatturabile in (True, False):
        service.create(
            TimeEntryCreate(
                deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
                ore=Decimal("2.00"), descrizione="x", fatturabile=fatturabile,
                tariffa_applicata=Decimal("100.000000"), costo_applicato=Decimal("30.000000"),
            ),
            WRITER,
        )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.costo_lavoro == Decimal("120.00")
    # But only the billable hour contributes accrued value: a non-billable hour is never
    # potential revenue.
    assert pnl.valore_maturato == Decimal("200.00")


def test_unpriced_hours_are_counted_and_excluded_never_valued_at_zero(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
            ore=Decimal("5.00"), descrizione="senza tariffa",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.ore_totali == Decimal("5.00")
    assert pnl.ore_senza_tariffa == 1
    assert pnl.valore_maturato == Decimal("0.00")
    assert pnl.costo_lavoro == Decimal("0.00")


def test_the_three_states(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID,
    seeded_won_stage_id: UUID, issued_invoice_line_id: UUID,
) -> None:
    from sqlalchemy import text

    service = TimeEntryService(db_session)
    entry = service.create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 4),
            ore=Decimal("2.00"), descrizione="x", tariffa_applicata=Decimal("100.000000"),
        ),
        WRITER,
    )
    analytics = AnalyticsService(db_session)
    assert analytics.deal_pnl(seeded_deal_id, READER).stato == "in corso"

    db_session.get(Deal, seeded_deal_id).pipeline_stage_id = seeded_won_stage_id
    db_session.flush()
    assert analytics.deal_pnl(seeded_deal_id, READER).stato == "da fatturare"

    db_session.execute(
        text("UPDATE time_entries SET invoice_line_id = :line WHERE id = :id"),
        {"line": issued_invoice_line_id, "id": entry.id},
    )
    db_session.flush()
    assert analytics.deal_pnl(seeded_deal_id, READER).stato == "chiuso"


def test_the_stamp_duty_is_not_a_deal_cost(db_session: Session, deal_with_bollo_invoice) -> None:
    """Slice 3 §7.2 keeps the stamp duty out of the total and on the issuer. Making it a
    deal cost would require this slice to look inside an invoice's fiscal composition,
    which is slice 3's competence. If the user wants it in the margin they record it as
    an ordinary `cost`."""
    pnl = AnalyticsService(db_session).deal_pnl(deal_with_bollo_invoice, READER)
    assert pnl.costi_diretti == Decimal("0.00")


def test_no_path_lets_the_same_expense_in_twice(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, seeded_category_id: UUID
) -> None:
    """**Criterion 4's third part.** `costs` and the labour cost are disjoint by
    construction: `costs` is money out to third parties, labour cost derives from
    `time_entries`. An external consultant who invoices you their hours is a `cost` in
    "Consulenza esterna", and their hours — if you record them — carry
    `costo_applicato = NULL`."""
    CostService(db_session).create(
        CostCreate(
            deal_id=seeded_deal_id, category_id=seeded_category_id, data=date(2026, 3, 1),
            importo=Decimal("1000.00"), descrizione="Consulente esterno",
        ),
        WRITER,
    )
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 2),
            ore=Decimal("10.00"), descrizione="ore del consulente",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).deal_pnl(seeded_deal_id, READER)
    assert pnl.costi_diretti == Decimal("1000.00")
    assert pnl.costo_lavoro == Decimal("0.00")
    assert pnl.margine_lordo == Decimal("-1000.00")


def test_margin_percentage_when_there_is_revenue(
    db_session: Session, deal_with_mixed_invoices, seeded_user_id: UUID
) -> None:
    pnl = AnalyticsService(db_session).deal_pnl(deal_with_mixed_invoices, READER)
    if pnl.ricavi > 0:
        assert pnl.margine_percentuale is not None
        assert pnl.margine_percentuale == (
            pnl.margine_lordo / pnl.ricavi * Decimal(100)
        ).quantize(Decimal("0.01"))
```

The `deal_with_mixed_invoices`, `deal_with_vat_invoice`, `deal_with_bollo_invoice` and `rf01_fiscal_profile` fixtures go in `packages/core/tests/conftest.py`, each built through `InvoiceService` and `issue_invoice`/`annul_invoice` so the states are the ones that service actually produces. `rf01_fiscal_profile` reuses slice 3 §14.8's own synthetic profile fixture rather than declaring a second one — check `grep -rn "RF01" packages/core/tests/` and import it.

- [ ] **Step 3: Run both and watch them fail**

Run: `uv run pytest packages/core/tests/test_deal_pnl.py packages/core/tests/test_pnl_reconciliation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.analytics'`.

- [ ] **Step 4: Write the schemas**

```python
# packages/core/src/pigrocrm/core/analytics/schemas.py
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DealStato = Literal["in corso", "da fatturare", "chiuso"]


class DealPnl(BaseModel):
    """One deal's profit and loss, every figure computed by the service and returned
    already summed — the browser adds nothing (§6).

    `valore_maturato` is deliberately a separate field from `ricavi` and not a variant of
    it: it is the estimate of §3 decision 2, it is **not revenue**, it enters no P&L row,
    and it lives under a heading of its own. On an `in corso` deal it is the honest number
    to look at and the margin is provisional; the margin is only reportable in the
    `chiuso` state.
    """

    deal_id: UUID
    stato: DealStato
    ricavi: Decimal
    costi_diretti: Decimal
    costo_lavoro: Decimal
    margine_lordo: Decimal
    # `None`, never `0.00`, when revenue is zero: zero per cent means "everything I
    # earned went out in costs", a zero denominator means nothing has been earned. Two
    # different facts (§7.1, criterion 6).
    margine_percentuale: Decimal | None
    ore_totali: Decimal
    ore_fatturabili_non_fatturate: Decimal
    valore_maturato: Decimal
    ore_senza_tariffa: int
    fatture_emesse: int


class PeriodPnlQuery(BaseModel):
    da: date
    a: date
    customer_id: UUID | None = None


class PnlTotals(BaseModel):
    ricavi: Decimal
    costi_diretti: Decimal
    costo_lavoro: Decimal
    margine_lordo: Decimal
    margine_percentuale: Decimal | None
    deal: int


class PeriodPnl(BaseModel):
    """Two columns, never one total (§7.4).

    Adding a finished job's margin to a half-done one produces a figure that is neither,
    and that changes every week for reasons which are not business performance. The
    reportable number is `chiusi`.
    """

    da: date
    a: date
    customer_id: UUID | None
    chiusi: PnlTotals
    in_corso: PnlTotals
    # A cost with `deal_id IS NULL`: it enters the period P&L in a row of its own and is
    # **never apportioned** onto any deal. Every apportionment key has one precise and
    # unacceptable consequence — a deal's margin would move when a *different* deal was
    # invoiced.
    spese_generali: Decimal
    # Whether the number can still move, which is the thing a reader most needs to know
    # and costs a COUNT over two columns that already exist (§6.4).
    periodo_chiuso: bool
    voci_scritte_in_ritardo: int


class BudgetQuery(BaseModel):
    da: date
    a: date
    customer_id: UUID | None = None
    # Mandatory pagination from the first commit (residual B3): the margins view is by
    # its nature a list of *closed* deals, so unbounded growth stops being invisible here.
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class BudgetVsActualRow(BaseModel):
    deal_id: UUID
    nome: str
    ore_preventivate: Decimal | None
    ore_consuntivate: Decimal
    valore_preventivato: Decimal | None
    ricavi: Decimal
    # Per cent, two places: 40 hours of an estimated 100 is `"40.00"`.
    avanzamento_ore: Decimal | None
    budget_pro_rata: Decimal | None
    scostamento_valore: Decimal | None
    scostamento_ore: Decimal | None
    tariffa_media_preventivata: Decimal | None
    tariffa_media_consuntivata: Decimal | None
    # An absent estimate is not an estimate of zero: the row says so, is excluded from
    # the budget aggregates, and is never counted as a 100% overrun (§9.2).
    non_preventivato: bool
    # `valore_preventivato` set with `ore_preventivate` null: no progress figure exists
    # to derive a pro-rata from, so only the absolute comparison is shown rather than a
    # progress invented from the invoiced value — which would be circular, because the
    # invoiced value is the very quantity being judged.
    pro_rata_non_calcolabile: bool


class BudgetPage(BaseModel):
    items: list[BudgetVsActualRow]
    next_cursor: UUID | None
    # Only over rows with both estimate columns populated: including the unestimated ones
    # would make the aggregate depend on how many deals nobody estimated.
    totale_preventivato: Decimal
    totale_ricavi: Decimal
    deal_preventivati: int
    deal_non_preventivati: int


class FiscalEstimate(BaseModel):
    """§8. Declared an **estimate** in its own payload, not only in the UI copy: a
    labelled estimate is useful, an estimate presented as an actual is the original
    defect in a new form."""

    model_config = ConfigDict(frozen=True)

    anno: int
    stima: Literal[True] = True
    avvertenza: str
    ricavi: Decimal
    coefficiente_redditivita: Decimal | None
    imponibile: Decimal | None
    aliquota_imposta_sostitutiva: Decimal | None
    imposta_sostitutiva: Decimal | None
    aliquota_inps: Decimal | None
    contributi: Decimal | None
    reddito_netto_stimato: Decimal | None


class BindTimeRequest(BaseModel):
    """Which hours become invoice lines. `entry_ids` explicit rather than "everything
    billable": choosing *which* hours to invoice is a commercial decision, and a default
    of "all of them" is that decision made silently."""

    entry_ids: list[UUID] = Field(min_length=1)
    raggruppa_per_mese: bool = True
```

- [ ] **Step 5: Write the repository**

```python
# packages/core/src/pigrocrm/core/analytics/repository.py
"""Every aggregate query of this slice, in one file.

Deliberately one module rather than a query beside each caller: "where does `ricavi`
come from" must have exactly one answer to read. The previous system's defect was a *dispersed*
aggregation — `hoursByOfferKey.get(offer.id) || hoursByOfferKey.get(offer.fileName) ||
hoursByOfferKey.get(offer.offerName) || 0` took the **first non-empty bucket instead of
their sum**, so hours logged against an offer's name vanished if a single hour had been
logged against its id, and `linkedExpenseMap` lost costs the same way, silently. With one
required foreign key there are no buckets to merge and the sum is a `GROUP BY deal_id`;
this file is the structural counterpart of that.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from pigrocrm.core.deals.models import Deal
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.money import ZERO_MONEY, line_value, sum_hours, sum_money
from pigrocrm.core.timetracking.models import Cost, TimeEntry

# The one definition of "an invoice that is revenue" (§7.1). `imponibile`, never
# `totale`: the total includes VAT, which is not revenue but money collected on the
# State's behalf. `fattura`, never `proforma`: a proforma does not touch the register
# (slice 3 §5). `emessa`, never `annullata`: an annulled invoice keeps its number but not
# its revenue — the struck-through page of a paper register.
def _revenue_filter() -> tuple:
    return (
        Invoice.tipo == "fattura",
        Invoice.stato == "emessa",
        Invoice.deleted_at.is_(None),
    )


class AnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def deal_revenue(self, deal_id: UUID) -> tuple[Decimal, int]:
        """`(Σ imponibile, count)` for one deal. The count is returned alongside because
        a revenue of `0.00` with three invoices behind it and one with none are different
        situations, and the UI says which."""
        total, count = self.session.execute(
            select(func.coalesce(func.sum(Invoice.imponibile), 0), func.count())
            .where(Invoice.deal_id == deal_id, *_revenue_filter())
        ).one()
        return Decimal(total), int(count)

    def deal_direct_costs(self, deal_id: UUID) -> Decimal:
        return Decimal(
            self.session.execute(
                select(func.coalesce(func.sum(Cost.importo), 0)).where(
                    Cost.deal_id == deal_id, Cost.deleted_at.is_(None)
                )
            ).scalar_one()
        )

    def _customer_scope(self, stmt: Select, customer_id: UUID | None, column) -> Select:
        if customer_id is None:
            return stmt
        return stmt.where(
            column.in_(select(Deal.id).where(Deal.customer_id == customer_id))
        )

    def revenue_in_range(
        self, da: date, a: date, customer_id: UUID | None
    ) -> dict[UUID, Decimal]:
        """Revenue is attributed to the period by **its own** date — `data_emissione` —
        not by the deal's date, which does not exist, and not by one common date, which
        none of the three quantities has (§7.4)."""
        stmt = (
            select(Invoice.deal_id, func.coalesce(func.sum(Invoice.imponibile), 0))
            .where(
                Invoice.deal_id.isnot(None),
                Invoice.data_emissione >= da,
                Invoice.data_emissione <= a,
                *_revenue_filter(),
            )
            .group_by(Invoice.deal_id)
        )
        stmt = self._customer_scope(stmt, customer_id, Invoice.deal_id)
        return {row[0]: Decimal(row[1]) for row in self.session.execute(stmt).all()}

    def costs_in_range(
        self, da: date, a: date, customer_id: UUID | None
    ) -> tuple[dict[UUID, Decimal], Decimal]:
        """`({deal_id: total}, general_expenses)`. Costs are attributed by `costs.data`.

        General expenses — `deal_id IS NULL` — come back separately and are never
        distributed: any apportionment key would make a deal's margin move when a
        different deal was invoiced (§7.4). A customer filter excludes them entirely,
        because a general expense belongs to no customer by definition.
        """
        per_deal: dict[UUID, Decimal] = {}
        stmt = (
            select(Cost.deal_id, func.coalesce(func.sum(Cost.importo), 0))
            .where(Cost.deal_id.isnot(None), Cost.data >= da, Cost.data <= a,
                   Cost.deleted_at.is_(None))
            .group_by(Cost.deal_id)
        )
        stmt = self._customer_scope(stmt, customer_id, Cost.deal_id)
        for deal_id, total in self.session.execute(stmt).all():
            per_deal[deal_id] = Decimal(total)

        if customer_id is not None:
            return per_deal, ZERO_MONEY
        general = Decimal(
            self.session.execute(
                select(func.coalesce(func.sum(Cost.importo), 0)).where(
                    Cost.deal_id.is_(None), Cost.data >= da, Cost.data <= a,
                    Cost.deleted_at.is_(None),
                )
            ).scalar_one()
        )
        return per_deal, general

    def labour_cost_in_range(
        self, da: date, a: date, customer_id: UUID | None
    ) -> dict[UUID, Decimal]:
        """`Σ ROUND(ore × costo_applicato, 2)`, summed **per row** and then added — never
        `ROUND(Σ ore × costo, 2)`.

        Computed in Python rather than in SQL on purpose: Postgres would round the
        product with its own rule, and §6.2 fixes `ROUND_HALF_UP` per row in
        `money.py` as the single authority. Two rounding implementations is how the
        printed column and the total come to disagree.
        """
        stmt = select(TimeEntry.deal_id, TimeEntry.ore, TimeEntry.costo_applicato).where(
            TimeEntry.data >= da,
            TimeEntry.data <= a,
            TimeEntry.deleted_at.is_(None),
            TimeEntry.costo_applicato.isnot(None),
        )
        stmt = self._customer_scope(stmt, customer_id, TimeEntry.deal_id)
        grouped: dict[UUID, list[Decimal | None]] = defaultdict(list)
        for deal_id, ore, costo in self.session.execute(stmt).all():
            grouped[deal_id].append(line_value(ore, costo))
        return {deal_id: sum_money(values) for deal_id, values in grouped.items()}

    def hours_in_range(
        self, da: date, a: date, customer_id: UUID | None
    ) -> dict[UUID, Decimal]:
        stmt = (
            select(TimeEntry.deal_id, func.coalesce(func.sum(TimeEntry.ore), 0))
            .where(TimeEntry.data >= da, TimeEntry.data <= a, TimeEntry.deleted_at.is_(None))
            .group_by(TimeEntry.deal_id)
        )
        stmt = self._customer_scope(stmt, customer_id, TimeEntry.deal_id)
        return {row[0]: Decimal(row[1]) for row in self.session.execute(stmt).all()}

    def late_entry_count(self, da: date, a: date) -> int:
        """How many rows dated inside the period were written **after** it ended
        (`created_at > a`). It is what tells a reader whether the figure can still move,
        and it is free: a COUNT over two columns that already exist (§6.4)."""
        entries = self.session.execute(
            select(func.count())
            .select_from(TimeEntry)
            .where(
                TimeEntry.data >= da,
                TimeEntry.data <= a,
                TimeEntry.deleted_at.is_(None),
                func.date(TimeEntry.created_at) > a,
            )
        ).scalar_one()
        costs = self.session.execute(
            select(func.count())
            .select_from(Cost)
            .where(
                Cost.data >= da, Cost.data <= a, Cost.deleted_at.is_(None),
                func.date(Cost.created_at) > a,
            )
        ).scalar_one()
        return int(entries) + int(costs)

    def annual_revenue(self, anno: int) -> Decimal:
        """Every issued invoice of the year, deal or no deal: the fiscal estimate is
        about the person's income, so an invoice with no `deal_id` counts too."""
        return Decimal(
            self.session.execute(
                select(func.coalesce(func.sum(Invoice.imponibile), 0)).where(
                    Invoice.anno == anno, *_revenue_filter()
                )
            ).scalar_one()
        )

    def deals_in_range(self, da: date, a: date, customer_id: UUID | None) -> list[Deal]:
        """Every deal with any activity in the window — an issued invoice, a cost or an
        hour. Not "every deal": a period report listing deals with nothing in the period
        is the unbounded growth residual B3 describes, and the window is what bounds it.
        """
        active = (
            select(Invoice.deal_id.label("deal_id"))
            .where(Invoice.deal_id.isnot(None), Invoice.data_emissione >= da,
                   Invoice.data_emissione <= a, *_revenue_filter())
            .union(
                select(Cost.deal_id.label("deal_id")).where(
                    Cost.deal_id.isnot(None), Cost.data >= da, Cost.data <= a,
                    Cost.deleted_at.is_(None),
                ),
                select(TimeEntry.deal_id.label("deal_id")).where(
                    TimeEntry.data >= da, TimeEntry.data <= a, TimeEntry.deleted_at.is_(None)
                ),
            )
            .subquery()
        )
        stmt = select(Deal).where(Deal.id.in_(select(active.c.deal_id)), Deal.deleted_at.is_(None))
        if customer_id is not None:
            stmt = stmt.where(Deal.customer_id == customer_id)
        return list(self.session.execute(stmt.order_by(Deal.nome, Deal.id)).scalars())
```

- [ ] **Step 6: Write `deal_pnl`**

```python
# packages/core/src/pigrocrm/core/analytics/service.py
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.repository import AnalyticsRepository
from pigrocrm.core.analytics.schemas import DealPnl
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.errors import NotFound
from pigrocrm.core.money import percentage_of
from pigrocrm.core.timetracking.service import TimeEntryService

ENTITY = "analytics"


class AnalyticsService:
    """Reads only, except for `bind_time_to_invoice` (Task 4B-7).

    Every figure is computed here and returned already summed. §6 forbids the frontend of
    this slice from computing any economic total at all — the previous system's whole P&L lived in
    `App.jsx`, with three fiscal constants and float hour sums, and moving it here is the
    final payment on the debt slice 1 §2.2 cited as the empirical justification for this
    architecture.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = AnalyticsRepository(session)
        self.deals = DealRepository(session)
        self.entries = TimeEntryService(session)

    def deal_pnl(self, deal_id: UUID, actor: Actor) -> DealPnl:
        """The rows of §7.1, each from its one stated source.

        `valore_maturato = ricavi + valore delle ore fatturabili non fatturate`. It is
        **not** revenue, enters no P&L row, and is returned in a field of its own name
        (§7.3): on an `in corso` deal it is the honest figure and the margin is
        provisional; the margin is only reportable when the state is `chiuso`.
        """
        deal = self.deals.get(deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)

        ricavi, fatture = self.repo.deal_revenue(deal_id)
        costi_diretti = self.repo.deal_direct_costs(deal_id)
        # Reuses 4A's own summary rather than recomputing hours here: one definition of
        # "labour cost" and one of "state", so the Ore tab and the Economia tab can never
        # disagree about the same deal.
        summary = self.entries.deal_summary(deal_id, actor)
        margine = ricavi - costi_diretti - summary.costo_lavoro

        return DealPnl(
            deal_id=deal_id,
            stato=summary.stato,
            ricavi=ricavi,
            costi_diretti=costi_diretti,
            costo_lavoro=summary.costo_lavoro,
            margine_lordo=margine,
            # `percentage_of` returns `None` for a zero denominator and performs no
            # division at all in that case, so this is the only place the question is
            # asked and there is no second answer to keep aligned.
            margine_percentuale=percentage_of(margine, ricavi),
            ore_totali=summary.ore_totali,
            ore_fatturabili_non_fatturate=summary.ore_fatturabili_non_fatturate,
            valore_maturato=ricavi + summary.valore_ore_non_fatturate,
            ore_senza_tariffa=summary.ore_senza_tariffa,
            fatture_emesse=fatture,
        )
```

- [ ] **Step 7: Run both tests**

Run: `uv run pytest packages/core/tests/test_deal_pnl.py packages/core/tests/test_pnl_reconciliation.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/core
git commit -m "feat(analytics): deal P&L whose revenue reconciles with its invoices to the cent"
```

---

### Task 4B-5: `period_pnl` — two columns, general expenses, and whether the number can still move

**Files:**
- Modify: `packages/core/src/pigrocrm/core/analytics/service.py`
- Test: `packages/core/tests/test_period_pnl.py`

**Interfaces:**
- Consumes: `AnalyticsRepository.{revenue_in_range, costs_in_range, labour_cost_in_range, hours_in_range, late_entry_count, deals_in_range}` (4B-4); `PeriodLockService.is_closed` (4A-8); `PipelineService.get`; `TimeEntryService.deal_summary`.
- Produces: `AnalyticsService.period_pnl(query: PeriodPnlQuery, actor: Actor) -> PeriodPnl`, returning `PnlTotals` for `chiusi` and for `in_corso`, `spese_generali`, `periodo_chiuso` and `voci_scritte_in_ritardo` (schemas from 4B-4).

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_period_pnl.py
"""§7.4. Two columns, never one total; general expenses in a row of their own and
apportioned onto nobody; and the honesty flags that say whether the figure can still
move."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.schemas import PeriodPnlQuery
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.timetracking.costs import CostService
from pigrocrm.core.timetracking.locks import PeriodLockService
from pigrocrm.core.timetracking.schemas import (
    CostCreate,
    PeriodLockCreate,
    TimeEntryCreate,
)
from pigrocrm.core.timetracking.service import TimeEntryService

READER = Actor(id=None, type="user", role="readonly")
WRITER = Actor(id=None, type="user", role="collaboratore")
MARCH = PeriodPnlQuery(da=date(2026, 3, 1), a=date(2026, 3, 31))


def test_an_open_deal_and_a_closed_one_never_share_a_total(
    db_session: Session, open_deal_with_hours, closed_deal_with_invoice
) -> None:
    """Adding a finished job's margin to a half-done one produces a figure that is
    neither, and that changes every week for reasons which are not business performance.
    The reportable number is `chiusi`."""
    pnl = AnalyticsService(db_session).period_pnl(MARCH, READER)
    assert pnl.chiusi.deal == 1
    assert pnl.in_corso.deal == 1
    assert pnl.chiusi.ricavi > Decimal("0.00")
    assert pnl.in_corso.ricavi == Decimal("0.00")
    # And there is deliberately no combined field to read by mistake.
    assert not hasattr(pnl, "totale")


def test_a_general_expense_has_its_own_row_and_touches_no_deal(
    db_session: Session, seeded_category_id: UUID, open_deal_with_hours
) -> None:
    """Any apportionment key — on revenue, on hours — has one precise and unacceptable
    consequence: a deal's margin would move when a *different* deal was invoiced. That is
    exactly the property that makes a number unreportable, and it is the defect the previous system's
    P&L has for personal taxation."""
    service = AnalyticsService(db_session)
    before = service.period_pnl(MARCH, READER)
    CostService(db_session).create(
        CostCreate(
            deal_id=None, category_id=seeded_category_id, data=date(2026, 3, 15),
            importo=Decimal("300.00"), descrizione="Commercialista",
        ),
        WRITER,
    )
    after = service.period_pnl(MARCH, READER)
    assert after.spese_generali == Decimal("300.00")
    # Not one deal figure moved.
    assert after.chiusi.model_dump() == before.chiusi.model_dump()
    assert after.in_corso.costi_diretti == before.in_corso.costi_diretti


def test_a_customer_filter_excludes_general_expenses_entirely(
    db_session: Session, seeded_category_id: UUID, open_deal_with_hours
) -> None:
    """A general expense belongs to no customer by definition, so scoping to one must not
    show a share of it — which would be apportionment through the back door."""
    CostService(db_session).create(
        CostCreate(
            deal_id=None, category_id=seeded_category_id, data=date(2026, 3, 15),
            importo=Decimal("300.00"), descrizione="Commercialista",
        ),
        WRITER,
    )
    from pigrocrm.core.deals.models import Deal

    customer_id = db_session.get(Deal, open_deal_with_hours).customer_id
    scoped = AnalyticsService(db_session).period_pnl(
        PeriodPnlQuery(da=MARCH.da, a=MARCH.a, customer_id=customer_id), READER
    )
    assert scoped.spese_generali == Decimal("0.00")


def test_each_quantity_is_attributed_by_its_own_date(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, seeded_category_id: UUID
) -> None:
    """Revenue by `invoices.data_emissione`, costs by `costs.data`, labour cost by
    `time_entries.data`. Not by the deal's date, which does not exist, and not by one
    common date, which none of the three has."""
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 31),
            ore=Decimal("1.00"), descrizione="marzo", costo_applicato=Decimal("50.000000"),
        ),
        WRITER,
    )
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 4, 1),
            ore=Decimal("1.00"), descrizione="aprile", costo_applicato=Decimal("50.000000"),
        ),
        WRITER,
    )
    CostService(db_session).create(
        CostCreate(
            deal_id=seeded_deal_id, category_id=seeded_category_id, data=date(2026, 4, 1),
            importo=Decimal("10.00"), descrizione="aprile",
        ),
        WRITER,
    )
    pnl = AnalyticsService(db_session).period_pnl(MARCH, READER)
    assert pnl.in_corso.costo_lavoro == Decimal("50.00")
    assert pnl.in_corso.costi_diretti == Decimal("0.00")


def test_an_open_period_reports_the_late_entries_and_a_closed_one_says_so(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """**Criterion 2's second half.** With the period open, a back-dated write succeeds,
    the P&L changes, and the response declares `periodo_chiuso = false` and
    `voci_scritte_in_ritardo = 1`. It is the information that tells a reader whether the
    number can still move."""
    TimeEntryService(db_session).create(
        TimeEntryCreate(
            deal_id=seeded_deal_id, user_id=seeded_user_id, data=date(2026, 3, 10),
            ore=Decimal("2.00"), descrizione="retrodatata", costo_applicato=Decimal("50.000000"),
        ),
        WRITER,
    )
    service = AnalyticsService(db_session)
    open_period = service.period_pnl(MARCH, READER)
    assert open_period.periodo_chiuso is False
    # Written today, dated in March 2026: `created_at > a`.
    assert open_period.voci_scritte_in_ritardo == 1

    admin = Actor(id=seeded_user_id, type="user", role="admin")
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    closed = service.period_pnl(MARCH, READER)
    assert closed.periodo_chiuso is True
    assert closed.chiusi.model_dump() == open_period.chiusi.model_dump()


def test_a_multi_month_window_is_closed_only_when_every_month_is(
    db_session: Session, seeded_user_id: UUID
) -> None:
    """A window is only as closed as its least-closed month: reporting a quarter as
    closed because one of its months is would be the wrong reassurance in the one place
    it matters."""
    admin = Actor(id=seeded_user_id, type="user", role="admin")
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=1), admin)
    quarter = PeriodPnlQuery(da=date(2026, 1, 1), a=date(2026, 3, 31))
    assert AnalyticsService(db_session).period_pnl(quarter, READER).periodo_chiuso is False
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=2), admin)
    PeriodLockService(db_session).close_period(PeriodLockCreate(anno=2026, mese=3), admin)
    assert AnalyticsService(db_session).period_pnl(quarter, READER).periodo_chiuso is True


def test_an_inverted_window_is_refused(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        AnalyticsService(db_session).period_pnl(
            PeriodPnlQuery(da=date(2026, 3, 31), a=date(2026, 3, 1)), READER
        )
    assert excinfo.value.details["field"] == "a"


def test_an_empty_window_returns_typed_zeros_and_a_null_percentage(db_session: Session) -> None:
    pnl = AnalyticsService(db_session).period_pnl(
        PeriodPnlQuery(da=date(1999, 1, 1), a=date(1999, 1, 31)), READER
    )
    assert pnl.chiusi.ricavi == Decimal("0.00")
    assert pnl.chiusi.margine_percentuale is None
    assert pnl.spese_generali == Decimal("0.00")
    assert pnl.chiusi.deal == 0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_period_pnl.py -v`
Expected: FAIL with `AttributeError: 'AnalyticsService' object has no attribute 'period_pnl'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/analytics/service.py -- append to AnalyticsService,
# with the added imports.
from calendar import monthrange
from itertools import count

from pigrocrm.core.analytics.schemas import PeriodPnl, PeriodPnlQuery, PnlTotals
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.money import ZERO_MONEY, sum_money
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm.core.timetracking.locks import PeriodLockService


def _months_between(da: date, a: date) -> list[tuple[int, int]]:
    """Every (year, month) the window touches, inclusive. Iterated rather than computed
    with arithmetic on month numbers, which is where December off-by-ones live."""
    months: list[tuple[int, int]] = []
    year, month = da.year, da.month
    while (year, month) <= (a.year, a.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _totals(rows: list[tuple[Decimal, Decimal, Decimal]]) -> PnlTotals:
    ricavi = sum_money([row[0] for row in rows])
    costi = sum_money([row[1] for row in rows])
    lavoro = sum_money([row[2] for row in rows])
    margine = ricavi - costi - lavoro
    return PnlTotals(
        ricavi=ricavi,
        costi_diretti=costi,
        costo_lavoro=lavoro,
        margine_lordo=margine,
        margine_percentuale=percentage_of(margine, ricavi),
        deal=len(rows),
    )


    # ---- on AnalyticsService ------------------------------------------------

    def period_pnl(self, query: PeriodPnlQuery, actor: Actor) -> PeriodPnl:
        """Aggregated over a date window, optionally scoped to one customer.

        Each quantity is attributed to the period by **its own** date: revenue by
        `invoices.data_emissione`, costs by `costs.data`, labour cost by
        `time_entries.data`. Not by the deal's date, which does not exist, and not by one
        common date, which none of the three has.

        Presented in **two columns** — closed deals and deals in progress — because
        adding a finished job's margin to a half-done one produces a figure that is
        neither, and that changes every week for reasons which are not business
        performance. The reportable number is the first, and there is deliberately no
        combined field to read by mistake.
        """
        if query.a < query.da:
            raise ValidationFailed(
                ENTITY, "a", "intervallo invertito", expected="una data non anteriore a 'da'"
            )

        revenue = self.repo.revenue_in_range(query.da, query.a, query.customer_id)
        per_deal_costs, general = self.repo.costs_in_range(
            query.da, query.a, query.customer_id
        )
        labour = self.repo.labour_cost_in_range(query.da, query.a, query.customer_id)
        pipeline = PipelineService(self.session)

        chiusi: list[tuple[Decimal, Decimal, Decimal]] = []
        in_corso: list[tuple[Decimal, Decimal, Decimal]] = []
        for deal in self.repo.deals_in_range(query.da, query.a, query.customer_id):
            row = (
                revenue.get(deal.id, ZERO_MONEY),
                per_deal_costs.get(deal.id, ZERO_MONEY),
                labour.get(deal.id, ZERO_MONEY),
            )
            # The state comes from the same place the deal's own P&L gets it, so the two
            # screens can never disagree about which column a deal belongs in.
            stato = self.entries.deal_summary(deal.id, actor).stato
            (chiusi if stato == "chiuso" else in_corso).append(row)

        locks = PeriodLockService(self.session)
        # A window is only as closed as its least-closed month: reporting a quarter as
        # closed because one of its months is would be the wrong reassurance in the one
        # place it matters.
        periodo_chiuso = all(
            locks.is_closed(date(anno, mese, 1)) is not None
            for anno, mese in _months_between(query.da, query.a)
        )

        return PeriodPnl(
            da=query.da,
            a=query.a,
            customer_id=query.customer_id,
            chiusi=_totals(chiusi),
            in_corso=_totals(in_corso),
            # Never apportioned onto any deal (§7.4), and absent entirely under a
            # customer filter, because a general expense belongs to no customer.
            spese_generali=general,
            periodo_chiuso=periodo_chiuso,
            # Free: a COUNT over two columns that already exist, and the one thing a
            # reader most needs to know about an open period (§6.4).
            voci_scritte_in_ritardo=self.repo.late_entry_count(query.da, query.a),
        )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_period_pnl.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(analytics): period P&L in two columns, general expenses apportioned onto nobody"
```

---

### Task 4B-6: `budget_vs_actual` — pro-rata, and an absent estimate that is not zero

**Files:**
- Modify: `packages/core/src/pigrocrm/core/analytics/service.py`
- Test: `packages/core/tests/test_budget_vs_actual.py`

**Interfaces:**
- Consumes: `AnalyticsRepository.{revenue_in_range, hours_in_range, deals_in_range}`; `Deal.{ore_preventivate, valore_preventivato}`; `money.{percentage_of, round_money, sum_money, ZERO_MONEY}`.
- Produces: `AnalyticsService.budget_vs_actual(query: BudgetQuery, actor: Actor) -> BudgetPage` (schemas from 4B-4).

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_budget_vs_actual.py
"""**Criterion 7.** The comparison the decomposition names as this slice's title, and the
one that tells a consultant whether the work was worth the price.

The value comparison is against the **pro-rata** budget, not the full one: at 40% of the
hours, being at 40% of the estimated value is on track, while comparing with 100% would
mark every job in progress as underperforming — and a report that flags everything flags
nothing.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.schemas import BudgetQuery
from pigrocrm.core.analytics.service import AnalyticsService

READER = Actor(id=None, type="user", role="readonly")
MARCH = BudgetQuery(da=date(2026, 3, 1), a=date(2026, 3, 31))


def test_the_spec_worked_example(db_session: Session, budgeted_deal) -> None:
    """A deal of 100 hours and 10,000 EUR, 40 hours logged, 4,000 EUR invoiced:
    `avanzamento = "40.00"`, `budget_pro_rata = "4000.00"`, `scostamento_valore = "0.00"`.
    """
    deal_id = budgeted_deal(ore_preventivate="100.00", valore_preventivato="10000.00",
                            ore_registrate="40.00", ricavi="4000.00")
    row = next(
        r
        for r in AnalyticsService(db_session).budget_vs_actual(MARCH, READER).items
        if r.deal_id == deal_id
    )
    assert row.avanzamento_ore == Decimal("40.00")
    assert row.budget_pro_rata == Decimal("4000.00")
    assert row.scostamento_valore == Decimal("0.00")
    assert row.non_preventivato is False
    assert row.pro_rata_non_calcolabile is False


def test_over_delivery_is_measured_against_the_pro_rata_not_the_full_budget(
    db_session: Session, budgeted_deal
) -> None:
    """With 4,500 EUR invoiced the variance is `"500.00"`, **not** `"-5500.00"`. The second
    number is what comparing against the full budget produces, and it would mark a job
    that is ahead as 55% behind."""
    deal_id = budgeted_deal(ore_preventivate="100.00", valore_preventivato="10000.00",
                            ore_registrate="40.00", ricavi="4500.00")
    row = next(
        r
        for r in AnalyticsService(db_session).budget_vs_actual(MARCH, READER).items
        if r.deal_id == deal_id
    )
    assert row.scostamento_valore == Decimal("500.00")
    assert row.scostamento_valore != Decimal("-5500.00")


def test_an_absent_estimate_is_not_an_estimate_of_zero(
    db_session: Session, budgeted_deal
) -> None:
    """`ore_preventivate IS NULL` means nobody estimated. The row says «non preventivato»,
    is excluded from the budget aggregates, and is never counted as a 100% overrun. No
    division by a null or zero estimate is ever executed."""
    deal_id = budgeted_deal(ore_preventivate=None, valore_preventivato=None,
                            ore_registrate="40.00", ricavi="4000.00")
    page = AnalyticsService(db_session).budget_vs_actual(MARCH, READER)
    row = next(r for r in page.items if r.deal_id == deal_id)
    assert row.non_preventivato is True
    assert row.avanzamento_ore is None
    assert row.budget_pro_rata is None
    assert row.scostamento_valore is None
    assert row.scostamento_ore is None
    assert row.tariffa_media_preventivata is None
    # Excluded from the aggregates, and counted separately so the reader knows.
    assert page.deal_non_preventivati >= 1
    assert deal_id not in {r.deal_id for r in page.items if not r.non_preventivato}


def test_zero_estimated_hours_behave_identically_to_null(
    db_session: Session, budgeted_deal
) -> None:
    """The secondary defence residual A14 requires regardless of Task 4B-1: `0` is treated
    as "not comparable", never as a denominator. Without it, the only reachable way to say
    "no estimate" before A14 was closed — `0.00` — read as "zero hours estimated, infinite
    overrun"."""
    zero = budgeted_deal(ore_preventivate="0.00", valore_preventivato="10000.00",
                         ore_registrate="40.00", ricavi="4000.00")
    null = budgeted_deal(ore_preventivate=None, valore_preventivato="10000.00",
                         ore_registrate="40.00", ricavi="4000.00")
    items = {r.deal_id: r for r in AnalyticsService(db_session).budget_vs_actual(MARCH, READER).items}
    for field in ("avanzamento_ore", "budget_pro_rata", "scostamento_valore", "scostamento_ore"):
        assert getattr(items[zero], field) == getattr(items[null], field)
    assert items[zero].avanzamento_ore is None


def test_a_value_estimate_without_an_hours_estimate_shows_only_the_absolute_comparison(
    db_session: Session, budgeted_deal
) -> None:
    """The pro-rata needs **both** estimate columns. With `valore_preventivato` set and
    `ore_preventivate` null there is no progress figure to derive it from, so the row is
    marked `pro_rata_non_calcolabile` rather than inventing a progress from the invoiced
    value — which would be circular, because the invoiced value is the very quantity being
    judged."""
    deal_id = budgeted_deal(ore_preventivate=None, valore_preventivato="10000.00",
                            ore_registrate="40.00", ricavi="4000.00")
    row = next(
        r
        for r in AnalyticsService(db_session).budget_vs_actual(MARCH, READER).items
        if r.deal_id == deal_id
    )
    assert row.pro_rata_non_calcolabile is True
    assert row.non_preventivato is False
    assert row.budget_pro_rata is None
    # The absolute comparison is still there.
    assert row.valore_preventivato == Decimal("10000.00")
    assert row.ricavi == Decimal("4000.00")


def test_the_average_rate_is_the_row_that_matters_most(
    db_session: Session, budgeted_deal
) -> None:
    """Not in the decomposition, and the one that serves best: how much I realised per
    hour worked, against how much I expected to. Two figures comparable even between deals
    of different sizes, and the only form in which "is this client worth it?" has a
    numeric answer."""
    deal_id = budgeted_deal(ore_preventivate="100.00", valore_preventivato="10000.00",
                            ore_registrate="40.00", ricavi="4000.00")
    row = next(
        r
        for r in AnalyticsService(db_session).budget_vs_actual(MARCH, READER).items
        if r.deal_id == deal_id
    )
    assert row.tariffa_media_preventivata == Decimal("100.00")
    assert row.tariffa_media_consuntivata == Decimal("100.00")


def test_the_list_is_paginated_from_the_first_commit(db_session: Session, budgeted_deal) -> None:
    """Residual B3: the margins view is by its nature a list of *closed* deals, so
    unbounded growth stops being invisible here. Paginated with a mandatory period
    filter."""
    for index in range(5):
        budgeted_deal(ore_preventivate="10.00", valore_preventivato="1000.00",
                      ore_registrate="1.00", ricavi="100.00", nome=f"Deal {index}")
    page = AnalyticsService(db_session).budget_vs_actual(
        BudgetQuery(da=MARCH.da, a=MARCH.a, limit=2), READER
    )
    assert len(page.items) == 2
    assert page.next_cursor is not None
```

The `budgeted_deal` fixture is a factory in `packages/core/tests/conftest.py` returning a `deal_id`: it creates a customer and a deal with the given estimate columns, logs one time entry of `ore_registrate` dated 2026-03-10, and — when `ricavi` is not `None` — creates and issues an invoice for that `imponibile` dated 2026-03-15 through `InvoiceService`. Build the revenue through the real service, never by inserting a row: the whole point of criterion 1 is that the figure comes from an invoice that exists.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_budget_vs_actual.py -v`
Expected: FAIL with `AttributeError: 'AnalyticsService' object has no attribute 'budget_vs_actual'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/analytics/service.py -- append, with the imports.
from pigrocrm.core.analytics.schemas import BudgetPage, BudgetQuery, BudgetVsActualRow
from pigrocrm.core.money import round_money


def _comparable(estimate: Decimal | None) -> bool:
    """An estimate is comparable only when it is present **and** greater than zero.

    `None` means nobody estimated. `0` is the state residual A14 made the only reachable
    spelling of "no estimate" before Task 4B-1 closed it, and it reads as "zero hours
    estimated, infinite overrun" to any division. Both are refused as denominators here —
    the secondary defence §9.2 requires regardless of A14 — so no division by a null or
    zero estimate is ever executed anywhere in this file.
    """
    return estimate is not None and estimate > 0


    # ---- on AnalyticsService ------------------------------------------------

    def budget_vs_actual(self, query: BudgetQuery, actor: Actor) -> BudgetPage:
        """Estimate against actual, per deal, with the pro-rata comparison beside the
        full one rather than instead of it.

        This is the payment on an investment made in advance: `deals.ore_preventivate`
        and `deals.valore_preventivato` have existed since slice 1 — written with a
        comment saying so — and have never been read by anybody. The actuals are the one
        missing half.
        """
        if query.a < query.da:
            raise ValidationFailed(
                ENTITY, "a", "intervallo invertito", expected="una data non anteriore a 'da'"
            )

        revenue = self.repo.revenue_in_range(query.da, query.a, query.customer_id)
        hours = self.repo.hours_in_range(query.da, query.a, query.customer_id)
        deals = self.repo.deals_in_range(query.da, query.a, query.customer_id)

        # Keyset pagination over the already-ordered deal list rather than a second
        # database round trip: `deals_in_range` orders by `(nome, id)`, so the cursor is
        # the last id of the page.
        if query.cursor is not None:
            ids = [deal.id for deal in deals]
            if query.cursor in ids:
                deals = deals[ids.index(query.cursor) + 1 :]
        window = deals[: query.limit]
        next_cursor = window[-1].id if len(deals) > query.limit and window else None

        rows: list[BudgetVsActualRow] = []
        for deal in window:
            ore_consuntivate = hours.get(deal.id, Decimal("0.00"))
            ricavi = revenue.get(deal.id, ZERO_MONEY)
            ore_ok = _comparable(deal.ore_preventivate)
            valore_ok = _comparable(deal.valore_preventivato)

            avanzamento = (
                percentage_of(ore_consuntivate, deal.ore_preventivate) if ore_ok else None
            )
            # The pro-rata needs BOTH estimate columns. With a value estimate and no hours
            # estimate there is no progress to derive it from, and inventing one from the
            # invoiced value would be circular — the invoiced value is the quantity being
            # judged.
            pro_rata = (
                round_money(deal.valore_preventivato * avanzamento / Decimal(100))
                if (ore_ok and valore_ok and avanzamento is not None)
                else None
            )
            rows.append(
                BudgetVsActualRow(
                    deal_id=deal.id,
                    nome=deal.nome,
                    ore_preventivate=deal.ore_preventivate,
                    ore_consuntivate=ore_consuntivate,
                    valore_preventivato=deal.valore_preventivato,
                    ricavi=ricavi,
                    avanzamento_ore=avanzamento,
                    budget_pro_rata=pro_rata,
                    # Measured against the pro-rata, never the full budget: at 40% of the
                    # hours, being at 40% of the estimated value is on track, and
                    # comparing with 100% would mark every job in progress as
                    # underperforming.
                    scostamento_valore=(ricavi - pro_rata) if pro_rata is not None else None,
                    scostamento_ore=(
                        ore_consuntivate - deal.ore_preventivate if ore_ok else None
                    ),
                    tariffa_media_preventivata=(
                        round_money(deal.valore_preventivato / deal.ore_preventivate)
                        if (ore_ok and valore_ok)
                        else None
                    ),
                    # The row that serves best, and the only form in which "is this client
                    # worth it?" has a numeric answer: how much was realised per hour
                    # worked, comparable even between deals of very different sizes.
                    tariffa_media_consuntivata=(
                        round_money(ricavi / ore_consuntivate)
                        if ore_consuntivate > 0
                        else None
                    ),
                    non_preventivato=not ore_ok and not valore_ok,
                    pro_rata_non_calcolabile=valore_ok and not ore_ok,
                )
            )

        budgeted = [row for row in rows if not row.non_preventivato]
        return BudgetPage(
            items=rows,
            next_cursor=next_cursor,
            # Only over rows with an estimate: including the unestimated ones would make
            # the aggregate depend on how many deals nobody estimated.
            totale_preventivato=sum_money([row.valore_preventivato for row in budgeted]),
            totale_ricavi=sum_money([row.ricavi for row in budgeted]),
            deal_preventivati=len(budgeted),
            deal_non_preventivati=len(rows) - len(budgeted),
        )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_budget_vs_actual.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(analytics): estimate versus actual against the pro-rata budget"
```

---

### Task 4B-7: `bind_time_to_invoice` — the bridge, and the pin on the rounding disagreement

**Files:**
- Modify: `packages/core/src/pigrocrm/core/analytics/service.py`
- Test: `packages/core/tests/test_time_to_invoice.py`

**Interfaces:**
- Consumes: slice 3's `InvoiceService.create(data: InvoiceCreate, actor) -> InvoiceRead`, `InvoiceCreate`, `InvoiceLineCreate` and `issue_invoice`; `TimeEntryRepository`; `billed_entry_ids` (4B-3); `FiscalProfileService.get` (for `aliquota_iva_default`/`natura_default`); `locks.period_label` (4A-8); `money.sum_hours`.
- Produces: `AnalyticsService.bind_time_to_invoice(deal_id: UUID, data: BindTimeRequest, actor: Actor) -> InvoiceRead`. One of §11's ten excluded names — no MCP tool, `admin` only.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_time_to_invoice.py
"""**Criterion 5.** Hours become invoice lines, once; and the derived value stops
counting the moment the invoice exists.

The bridge owns no invoicing logic: it builds an `InvoiceCreate` and calls
`InvoiceService`, which stays the sole owner of numbering, fiscal validation, rounding
and freezing (slice 3 §3, §6, §9). This task adds no participant to slice 3's locked
transaction.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.schemas import BindTimeRequest
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.errors import Conflict, PermissionDenied, ValidationFailed
from pigrocrm.core.money import line_value, sum_hours, sum_money
from pigrocrm.core.timetracking.schemas import TimeEntryCreate, TimeEntryListQuery
from pigrocrm.core.timetracking.service import TimeEntryService

ADMIN = Actor(id=None, type="system", role="admin")
WRITER = Actor(id=None, type="user", role="collaboratore")
READER = Actor(id=None, type="user", role="readonly")


def _log(service, deal_id, user_id, *, day, ore, tariffa, fatturabile=True):
    return service.create(
        TimeEntryCreate(
            deal_id=deal_id, user_id=user_id, data=day, ore=Decimal(ore),
            descrizione=f"Attività {day.isoformat()}", fatturabile=fatturabile,
            tariffa_applicata=Decimal(tariffa) if tariffa else None,
        ),
        WRITER,
    )


def test_thirty_seven_entries_on_three_rates_and_two_months_become_six_lines(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """One line per `(tariffa_applicata, mese)`, with `quantita = Σ ore` and
    `prezzo_unitario = tariffa`. Not one line per entry: an invoice with forty lines is
    unreadable for the client, and the detail already has its place — the timesheet
    attached to it."""
    service = TimeEntryService(db_session)
    entries = []
    for month, day_base in ((3, 1), (4, 1)):
        for index, tariffa in enumerate(("80.000000", "100.000000", "120.000000")):
            for offset in range(6 if (month, index) != (4, 2) else 7):
                entries.append(
                    _log(
                        service, seeded_deal_id, seeded_user_id,
                        day=date(2026, month, day_base + offset), ore="1.50", tariffa=tariffa,
                    )
                )
    assert len(entries) == 37

    invoice = AnalyticsService(db_session).bind_time_to_invoice(
        seeded_deal_id, BindTimeRequest(entry_ids=[e.id for e in entries]), ADMIN
    )

    lines = db_session.execute(
        text(
            "SELECT id, quantita, prezzo_unitario, descrizione FROM invoice_lines "
            "WHERE invoice_id = :inv ORDER BY numero_linea"
        ),
        {"inv": invoice.id},
    ).all()
    assert len(lines) == 6
    # `Σ quantita` is **exactly** `Σ ore` of the bound entries.
    assert sum_hours([Decimal(row[1]) for row in lines]) == sum_hours(
        [e.ore for e in entries]
    )
    # Every entry is bound to exactly one line.
    bound = db_session.execute(
        text(
            "SELECT invoice_line_id, count(*) FROM time_entries "
            "WHERE deal_id = :deal GROUP BY invoice_line_id"
        ),
        {"deal": seeded_deal_id},
    ).all()
    assert all(row[0] is not None for row in bound)
    assert sum(row[1] for row in bound) == 37
    # The description names the month and the hours, which is what makes a six-line
    # invoice legible.
    assert any("marzo" in row[3] for row in lines)
    assert any("ore" in row[3] for row in lines)


def test_the_derived_value_stops_being_consulted_once_the_invoice_exists(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """**The rounding pin.** Per-entry and per-invoice-line rounding disagree by cents,
    and the spec dissolves the disagreement rather than reconciling it: hours × rate is an
    **estimate** that stops being consulted once an invoice exists (§3 decision 2, §6.2's
    exception, §7.1).

    Constructed so the two genuinely differ: 3 entries of 0.10 h at 33.333333 EUR/h.
    Per entry, `Σ ROUND(0.10 × 33.333333, 2)` = 3 × 3.33 = 9.99. As one grouped line,
    `ROUND(0.30 × 33.333333, 2)` = 10.00. One cent apart, and the P&L must report the
    invoice's figure, not the sum of the derived ones.
    """
    service = TimeEntryService(db_session)
    entries = [
        _log(service, seeded_deal_id, seeded_user_id, day=date(2026, 3, day),
             ore="0.10", tariffa="33.333333")
        for day in (1, 2, 3)
    ]
    derived = sum_money([line_value(e.ore, e.tariffa_applicata) for e in entries])
    assert derived == Decimal("9.99")

    analytics = AnalyticsService(db_session)
    invoice = analytics.bind_time_to_invoice(
        seeded_deal_id, BindTimeRequest(entry_ids=[e.id for e in entries]), ADMIN
    )
    from pigrocrm.core.invoices.service import InvoiceService

    InvoiceService(db_session).issue_invoice(invoice.id, ADMIN)

    issued_imponibile = db_session.execute(
        text("SELECT imponibile FROM invoices WHERE id = :id"), {"id": invoice.id}
    ).scalar_one()
    assert Decimal(issued_imponibile) == Decimal("10.00")
    assert Decimal(issued_imponibile) != derived

    pnl = analytics.deal_pnl(seeded_deal_id, READER)
    # The invoice's figure, not the sum of the derived ones. This is the assertion the
    # whole rounding question reduces to.
    assert pnl.ricavi == Decimal("10.00")
    assert pnl.ricavi != derived
    # And the accrued value no longer counts those hours at all: they are invoiced.
    assert pnl.valore_maturato == Decimal("10.00")


def test_unpriced_entries_are_refused_with_a_count_and_a_list(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """An invoice line with no unit price is not issuable, and inventing one here would
    decide on the user's behalf what their work is worth. The refusal counts them and
    lists them, so the response is an instruction — "give these six entries a rate" — and
    not an obstacle."""
    service = TimeEntryService(db_session)
    priced = _log(service, seeded_deal_id, seeded_user_id, day=date(2026, 3, 1),
                  ore="1.00", tariffa="80.000000")
    unpriced = [
        _log(service, seeded_deal_id, seeded_user_id, day=date(2026, 3, day),
             ore="1.00", tariffa=None)
        for day in (2, 3)
    ]
    with pytest.raises(ValidationFailed) as excinfo:
        AnalyticsService(db_session).bind_time_to_invoice(
            seeded_deal_id,
            BindTimeRequest(entry_ids=[priced.id, *[e.id for e in unpriced]]),
            ADMIN,
        )
    assert excinfo.value.details["voci_senza_tariffa"] == 2
    assert set(excinfo.value.details["voci"]) == {str(e.id) for e in unpriced}


def test_non_billable_entries_are_refused_by_definition(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    service = TimeEntryService(db_session)
    internal = _log(service, seeded_deal_id, seeded_user_id, day=date(2026, 3, 1),
                    ore="1.00", tariffa="80.000000", fatturabile=False)
    with pytest.raises(ValidationFailed) as excinfo:
        AnalyticsService(db_session).bind_time_to_invoice(
            seeded_deal_id, BindTimeRequest(entry_ids=[internal.id]), ADMIN
        )
    assert excinfo.value.details["field"] == "entry_ids"


def test_an_hour_already_on_an_issued_invoice_cannot_be_invoiced_twice(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The mechanism that stops the same work being billed twice, and it is at the service
    level because that is where the information is."""
    service = TimeEntryService(db_session)
    entry = _log(service, seeded_deal_id, seeded_user_id, day=date(2026, 3, 1),
                 ore="1.00", tariffa="80.000000")
    analytics = AnalyticsService(db_session)
    invoice = analytics.bind_time_to_invoice(
        seeded_deal_id, BindTimeRequest(entry_ids=[entry.id]), ADMIN
    )
    from pigrocrm.core.invoices.service import InvoiceService

    InvoiceService(db_session).issue_invoice(invoice.id, ADMIN)

    with pytest.raises(Conflict) as excinfo:
        analytics.bind_time_to_invoice(
            seeded_deal_id, BindTimeRequest(entry_ids=[entry.id]), ADMIN
        )
    assert "fattura" in excinfo.value.message
    assert excinfo.value.details["numero"] is not None


def test_an_hour_on_a_draft_can_be_rebound(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """Binding is written when the draft line is created, not at issue, so while the
    invoice is a draft the hours stay modifiable and re-selectable — which is what lets
    slice 3's wholesale line replacement work without slice 4 joining its transaction."""
    service = TimeEntryService(db_session)
    entry = _log(service, seeded_deal_id, seeded_user_id, day=date(2026, 3, 1),
                 ore="1.00", tariffa="80.000000")
    analytics = AnalyticsService(db_session)
    analytics.bind_time_to_invoice(seeded_deal_id, BindTimeRequest(entry_ids=[entry.id]), ADMIN)
    second = analytics.bind_time_to_invoice(
        seeded_deal_id, BindTimeRequest(entry_ids=[entry.id]), ADMIN
    )
    assert second.id is not None
    bound = service.get(entry.id, READER).invoice_line_id
    assert bound is not None


def test_a_collaborator_cannot_call_it(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """Choosing *which* hours to invoice is a commercial decision, and this is the step
    immediately before the irreversible one — slice 3 §11 withdrew `issue_invoice` from
    MCP with the same reasoning."""
    with pytest.raises(PermissionDenied):
        AnalyticsService(db_session).bind_time_to_invoice(
            seeded_deal_id, BindTimeRequest(entry_ids=[uuid4()]), WRITER
        )


def test_an_entry_from_another_deal_is_refused(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID, budgeted_deal
) -> None:
    other = budgeted_deal(ore_preventivate=None, valore_preventivato=None,
                          ore_registrate="1.00", ricavi=None)
    stray = db_session.execute(
        text("SELECT id FROM time_entries WHERE deal_id = :deal LIMIT 1"), {"deal": other}
    ).scalar_one()
    with pytest.raises(ValidationFailed):
        AnalyticsService(db_session).bind_time_to_invoice(
            seeded_deal_id, BindTimeRequest(entry_ids=[stray]), ADMIN
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_time_to_invoice.py -v`
Expected: FAIL with `AttributeError: 'AnalyticsService' object has no attribute 'bind_time_to_invoice'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/analytics/service.py -- append, with the imports.
from collections import defaultdict

from pigrocrm.core.analytics.schemas import BindTimeRequest
from pigrocrm.core.errors import Conflict
from pigrocrm.core.invoices.fiscal_service import FiscalProfileService
from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceLineCreate, InvoiceRead
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.money import sum_hours
from pigrocrm.core.timetracking.locks import period_label
from pigrocrm.core.timetracking.models import TimeEntry
from pigrocrm.core.timetracking.service import billed_entry_ids


    # ---- on AnalyticsService ------------------------------------------------

    def bind_time_to_invoice(
        self, deal_id: UUID, data: BindTimeRequest, actor: Actor
    ) -> InvoiceRead:
        """Turns selected hours into a draft invoice.

        **Issues nothing and computes no total.** It builds an `InvoiceCreate` with its
        lines and calls `InvoiceService`, which remains the sole owner of numbering,
        fiscal validation, rounding and freezing (slice 3 §3, §6, §9). Nothing here joins
        slice 3's locked transaction — the part of the system that least wants new
        participants.

        `admin`, and **no MCP tool** (§11's exclusion list). Binding hours to a draft is
        harmless while the draft is a draft, but it is the step that determines their
        freezing at issue, and choosing *which* hours to invoice is a commercial
        decision. Slice 3 §11 withdrew `issue_invoice` from MCP with the same reasoning;
        this is the rung immediately below it.

        The link is written **when the draft line is born**, not at issue: the FK is
        `ON DELETE SET NULL`, so while the invoice is a draft the hours stay modifiable
        and slice 3's wholesale line replacement unbinds and rebinds them without
        orphans; the moment `issue()` commits, the bound hours are frozen without
        `issue()` having had to know they exist.
        """
        actor.require_admin("bind_time_to_invoice")
        deal = self.deals.get(deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)

        entries = [self.session.get(TimeEntry, entry_id) for entry_id in data.entry_ids]
        missing = [str(i) for i, e in zip(data.entry_ids, entries, strict=True) if e is None]
        if missing:
            raise NotFound("time_entry", missing[0])
        rows: list[TimeEntry] = [e for e in entries if e is not None]

        stray = [str(e.id) for e in rows if e.deal_id != deal_id or e.deleted_at is not None]
        if stray:
            raise ValidationFailed(
                "time_entry",
                "entry_ids",
                "alcune voci non appartengono a questo deal o sono archiviate",
                expected=f"voci del deal {deal_id}: {', '.join(stray)}",
            )

        # Never in a draft, by definition.
        internal = [str(e.id) for e in rows if not e.fatturabile]
        if internal:
            raise ValidationFailed(
                "time_entry",
                "entry_ids",
                "alcune voci non sono fatturabili",
                expected=f"solo voci fatturabili: {', '.join(internal)}",
            )

        # Counted and listed, so the answer is an instruction and not an obstacle: an
        # invoice line with no unit price is not issuable, and inventing one here would
        # decide on the user's behalf what their work is worth.
        unpriced = [e for e in rows if e.tariffa_applicata is None]
        if unpriced:
            raise ValidationFailed(
                "time_entry",
                "entry_ids",
                f"{len(unpriced)} voci non hanno una tariffa: assegnane una prima di "
                "generare la bozza",
                expected="una tariffa su ogni voce selezionata",
            )

        already = billed_entry_ids(self.session, rows)
        if already:
            blocked = next(e for e in rows if e.id in already)
            numero, anno = self.session.execute(
                select(Invoice.numero, Invoice.anno)
                .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
                .where(InvoiceLine.id == blocked.invoice_line_id)
            ).one()
            raise Conflict(
                "time_entry",
                f"{len(already)} voci sono già su una fattura emessa: non si fattura due "
                "volte lo stesso lavoro",
                voci=len(already),
                numero=numero,
                anno=anno,
            )

        # One line per (tariffa_applicata, mese). Not one per entry: a forty-line invoice
        # is unreadable for the client and the detail already has its place, the timesheet
        # attached to it (§10.2). The grouping is adjustable in the dialog before the
        # draft is generated; `raggruppa_per_mese = False` collapses to one line per rate.
        groups: dict[tuple[Decimal, tuple[int, int] | None], list[TimeEntry]] = defaultdict(list)
        for entry in rows:
            key = (entry.data.year, entry.data.month) if data.raggruppa_per_mese else None
            groups[(entry.tariffa_applicata, key)] = groups[(entry.tariffa_applicata, key)]
            groups[(entry.tariffa_applicata, key)].append(entry)

        profile = FiscalProfileService(self.session).get(actor)
        lines: list[InvoiceLineCreate] = []
        ordered = sorted(groups.items(), key=lambda item: (item[0][1] or (0, 0), item[0][0]))
        for (tariffa, month_key), members in ordered:
            ore = sum_hours([m.ore for m in members])
            etichetta = period_label(*month_key) if month_key else "attività"
            lines.append(
                InvoiceLineCreate(
                    descrizione=f"Attività {etichetta} — {ore} ore",
                    # `quantita = Σ ore` and `prezzo_unitario = tariffa`, so
                    # `prezzo_totale` is `ROUND(Σ ore × tariffa, 2)` — which may differ by
                    # cents from `Σ ROUND(ore × tariffa, 2)`. **That is not a discrepancy
                    # to reconcile** (§6.2's stated exception): the derived value stops
                    # being consulted the moment the invoice exists, and the invoice's own
                    # figure is the revenue from then on.
                    quantita=ore,
                    prezzo_unitario=tariffa,
                    unita_misura="ore",
                    aliquota_iva=profile.aliquota_iva_default,
                    natura=profile.natura_default,
                    riferimento_normativo=profile.riferimento_normativo,
                )
            )

        invoice = InvoiceService(self.session).create(
            InvoiceCreate(
                customer_id=deal.customer_id,
                deal_id=deal_id,
                tipo="fattura",
                righe=lines,
            ),
            actor,
        )

        # Bind each entry to the line its group produced. The line ids are read back in
        # `numero_linea` order, which is the order `lines` was built in, so the mapping is
        # positional and deterministic rather than matched on a description string.
        line_ids = list(
            self.session.execute(
                select(InvoiceLine.id)
                .where(InvoiceLine.invoice_id == invoice.id)
                .order_by(InvoiceLine.numero_linea)
            ).scalars()
        )
        for line_id, (_, members) in zip(line_ids, ordered, strict=True):
            for entry in members:
                entry.invoice_line_id = line_id
        self.activities_for_binding(deal_id, invoice, rows, actor)
        self.session.commit()
        return invoice

    def activities_for_binding(self, deal_id, invoice, rows, actor) -> None:
        """One activity on the deal, not one per entry: binding is a single commercial act
        over a selection, unlike `recalculate_rates`, which changes each row's meaning
        individually and therefore records per row."""
        from pigrocrm.core.activities.service import ActivityService

        ActivityService(self.session).record(
            "deal",
            deal_id,
            "time_bound_to_invoice",
            actor,
            {"invoice_id": str(invoice.id), "voci": len(rows)},
        )
```

Add `from sqlalchemy import select` and `from pigrocrm.core.invoices.models import Invoice, InvoiceLine` to the module imports. `activities_for_binding` is a private helper in spirit but must be named with a leading underscore so the architecture test does not demand an MCP tool for it — rename it `_activities_for_binding` when implementing, and call it as such.

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_time_to_invoice.py packages/core/tests/test_pnl_reconciliation.py -v`
Expected: PASS, both together — the bridge must not disturb the reconciliation it feeds.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(analytics): hours to an invoice draft, grouped by rate and month"
```

---

### Task 4B-8: `get_fiscal_estimate` — the three constants, moved to where they belong

**Files:**
- Create: `packages/core/src/pigrocrm/core/analytics/fiscal.py`
- Modify: `packages/core/src/pigrocrm/core/analytics/service.py`
- Test: `packages/core/tests/test_fiscal_estimate.py`

**Interfaces:**
- Consumes: `FiscalProfileService.get(actor) -> FiscalProfileRead` (with the three columns from 4B-2); `AnalyticsRepository.annual_revenue(anno)`; `money.round_money`.
- Produces:
  ```python
  # analytics/fiscal.py — pure, no session
  AVVERTENZA: str
  def estimate_income(
      *, anno: int, ricavi: Decimal,
      coefficiente: Decimal | None,
      aliquota_sostitutiva: Decimal | None,
      aliquota_inps: Decimal | None,
  ) -> FiscalEstimate

  # analytics/service.py
  def get_fiscal_estimate(self, anno: int, actor: Actor) -> FiscalEstimate
  ```
  `admin` only, and one of §11's ten excluded names — the only read on that list, and for a different reason from the rest: taxable income, contributions and estimated net are the most sensitive data this product holds, and while residual R10 leaves a PAT indistinguishable from full account access, that figure does not enter a conversational context on the back of a generic question about deals.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_fiscal_estimate.py
"""§8. The previous system computed this **per offer**, inside `App.jsx`:

    const taxableBase   = gross * FORFETTARIO_PROFITABILITY_RATE       // 0.67
    const substituteTax = taxableBase * FORFETTARIO_SUBSTITUTE_TAX_RATE // 0.05
    const inps          = (taxableBase - substituteTax) * FORFETTARIO_INPS_RATE // 0.2607
    const net           = gross - substituteTax - inps

Wrong in three independent ways, and none of them is cured by correcting the formula.
INPS is not proportional to one project's revenue — it has a floor paid even at zero
income and a ceiling — so a pro-rata share attributes to a job an amount that does not
depend on it. The profitability coefficient applies to the whole year, not to a slice, so
applying it to slices and adding them gives a different number. And the result changes
retroactively: a March project's "profit" depends on what is invoiced in November,
because both feed the same base — the very property §7.4 refuses for general expenses,
here applied to the entire tax computation.

So the cure is not a corrected formula per deal. It is the same computation moved to the
level where it is meaningful: **a period report, never per deal**, in `packages/core`.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.analytics.fiscal import estimate_income
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.errors import PermissionDenied

ADMIN = Actor(id=None, type="system", role="admin")
WRITER = Actor(id=None, type="user", role="collaboratore")


def test_the_arithmetic_matches_the_previous_systems_at_the_annual_level() -> None:
    """The formula is carried over unchanged — it was never the defect. Only the level is
    different, and the constants now live in a table."""
    estimate = estimate_income(
        anno=2026,
        ricavi=Decimal("100000.00"),
        coefficiente=Decimal("67.00"),
        aliquota_sostitutiva=Decimal("5.00"),
        aliquota_inps=Decimal("26.07"),
    )
    assert estimate.imponibile == Decimal("67000.00")
    assert estimate.imposta_sostitutiva == Decimal("3350.00")
    # (67000 - 3350) * 0.2607
    assert estimate.contributi == Decimal("16593.56")
    # ricavi - sostitutiva - contributi
    assert estimate.reddito_netto_stimato == Decimal("80056.44")


def test_it_says_it_is_an_estimate_in_its_own_payload() -> None:
    """A labelled estimate is useful; an estimate presented as an actual is the original
    defect in a new form. So the label is in the data, not only in the page copy."""
    estimate = estimate_income(
        anno=2026, ricavi=Decimal("1000.00"), coefficiente=Decimal("67.00"),
        aliquota_sostitutiva=Decimal("5.00"), aliquota_inps=Decimal("26.07"),
    )
    assert estimate.stima is True
    assert "minimale" in estimate.avvertenza
    assert "massimale" in estimate.avvertenza
    assert "acconti" in estimate.avvertenza


def test_a_missing_parameter_yields_null_not_a_guess() -> None:
    """A parameter nobody configured is not a parameter of zero: the report says it cannot
    compute that line rather than reporting a number derived from an assumption."""
    estimate = estimate_income(
        anno=2026, ricavi=Decimal("1000.00"), coefficiente=None,
        aliquota_sostitutiva=Decimal("5.00"), aliquota_inps=Decimal("26.07"),
    )
    assert estimate.imponibile is None
    assert estimate.imposta_sostitutiva is None
    assert estimate.contributi is None
    assert estimate.reddito_netto_stimato is None
    assert estimate.ricavi == Decimal("1000.00")


def test_rounding_is_the_projects_own_half_up_at_every_step() -> None:
    estimate = estimate_income(
        anno=2026, ricavi=Decimal("1.05"), coefficiente=Decimal("67.00"),
        aliquota_sostitutiva=Decimal("5.00"), aliquota_inps=Decimal("26.07"),
    )
    # 1.05 * 0.67 = 0.7035 -> 0.70 half-up
    assert estimate.imponibile == Decimal("0.70")


def test_the_service_reads_the_year_from_issued_invoices_only(
    db_session: Session, deal_with_mixed_invoices
) -> None:
    from sqlalchemy import text

    expected = db_session.execute(
        text(
            "SELECT COALESCE(SUM(imponibile), 0) FROM invoices "
            "WHERE anno = 2026 AND tipo = 'fattura' AND stato = 'emessa' "
            "  AND deleted_at IS NULL"
        )
    ).scalar_one()
    estimate = AnalyticsService(db_session).get_fiscal_estimate(2026, ADMIN)
    assert estimate.ricavi == Decimal(expected)


def test_it_is_admin_only(db_session: Session) -> None:
    """The only read on §11's exclusion list, and for a reason different from the rest: it
    is the most sensitive figure this product holds, and residual R10 leaves a PAT
    indistinguishable from full account access."""
    with pytest.raises(PermissionDenied):
        AnalyticsService(db_session).get_fiscal_estimate(2026, WRITER)


def test_there_is_no_per_deal_variant_anywhere(db_session: Session) -> None:
    """Asserted so nobody helpfully adds one: the whole point of §8 is that this
    computation has no meaning per project."""
    surface = dir(AnalyticsService)
    assert not [name for name in surface if "fiscal" in name and "deal" in name]
    from pigrocrm.core.analytics.schemas import DealPnl

    assert not [f for f in DealPnl.model_fields if "imposta" in f or "inps" in f or "netto" in f]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/core/tests/test_fiscal_estimate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.analytics.fiscal'`.

- [ ] **Step 3: Implement it**

```python
# packages/core/src/pigrocrm/core/analytics/fiscal.py
"""The annual income estimate — the last piece of the previous system's logic to leave the browser.

Slice 1 §2.2 cited three constants inside `App.jsx` — `FORFETTARIO_INPS_RATE = 0.2607`,
a 67% coefficient and a 5% substitute tax — as the empirical justification for this whole
architecture. They were there to compute a margin. Bringing them into `packages/core` is
the final payment on that debt, and slice 1 §14 assigns it to this slice.

The **formula** is carried over unchanged; it was never the defect. The **level** is
different, and that is the whole correction: the previous system computed this per offer, which is
wrong in three independent ways (see `test_fiscal_estimate.py`'s own docstring for all
three). Here it is annual, never per deal, and there is deliberately no per-deal variant
anywhere in this package.

Pure: no session, no ORM, so the arithmetic is provable on its own and the same numbers
can be checked against a spreadsheet.
"""

from decimal import Decimal

from pigrocrm.core.analytics.schemas import FiscalEstimate
from pigrocrm.core.money import round_money

AVVERTENZA = (
    "Stima indicativa. Non tiene conto del minimale e del massimale contributivo, "
    "di altri redditi, degli acconti già versati né di deduzioni e detrazioni. "
    "Per la dichiarazione fai riferimento al tuo commercialista."
)

_HUNDRED = Decimal(100)


def estimate_income(
    *,
    anno: int,
    ricavi: Decimal,
    coefficiente: Decimal | None,
    aliquota_sostitutiva: Decimal | None,
    aliquota_inps: Decimal | None,
) -> FiscalEstimate:
    """Taxable base, substitute tax, contributions and estimated net for one year.

    Percentages in, so `67.00` rather than `0.67`: the columns store what a user reads and
    types, and the single division by 100 happens here.

    A missing parameter yields `None` for every line that depends on it, never a guess: a
    parameter nobody configured is not a parameter of zero, and a report that filled it in
    would be presenting an assumption as a figure. `round_money` at every step, so the
    printed lines add up to the printed total — §6.2's rule, applied to a report instead
    of an invoice.
    """
    imponibile = (
        round_money(ricavi * coefficiente / _HUNDRED) if coefficiente is not None else None
    )
    sostitutiva = (
        round_money(imponibile * aliquota_sostitutiva / _HUNDRED)
        if (imponibile is not None and aliquota_sostitutiva is not None)
        else None
    )
    contributi = (
        round_money((imponibile - sostitutiva) * aliquota_inps / _HUNDRED)
        if (imponibile is not None and sostitutiva is not None and aliquota_inps is not None)
        else None
    )
    netto = (
        round_money(ricavi - sostitutiva - contributi)
        if (sostitutiva is not None and contributi is not None)
        else None
    )
    return FiscalEstimate(
        anno=anno,
        avvertenza=AVVERTENZA,
        ricavi=ricavi,
        coefficiente_redditivita=coefficiente,
        imponibile=imponibile,
        aliquota_imposta_sostitutiva=aliquota_sostitutiva,
        imposta_sostitutiva=sostitutiva,
        aliquota_inps=aliquota_inps,
        contributi=contributi,
        reddito_netto_stimato=netto,
    )
```

```python
# packages/core/src/pigrocrm/core/analytics/service.py -- append.
    def get_fiscal_estimate(self, anno: int, actor: Actor) -> FiscalEstimate:
        """A **period** report, never per deal (§8).

        `admin`, and **no MCP tool** — the only read on §11's exclusion list, and for a
        reason unlike the other nine. It is not about reversibility: taxable income,
        contributions and estimated net for a real person are the most sensitive data
        this product holds, and while residual R10 leaves a PAT without scopes and
        inheriting its owner's full role — while "give Claude a token" still means "give
        it your account" — that figure does not enter a conversational context on the
        back of a generic question about deals.
        """
        actor.require_admin("get_fiscal_estimate")
        profile = FiscalProfileService(self.session).get(actor)
        return estimate_income(
            anno=anno,
            ricavi=self.repo.annual_revenue(anno),
            coefficiente=profile.coefficiente_redditivita,
            aliquota_sostitutiva=profile.aliquota_imposta_sostitutiva,
            aliquota_inps=profile.aliquota_inps,
        )
```

with `from pigrocrm.core.analytics.fiscal import estimate_income` and `from pigrocrm.core.analytics.schemas import FiscalEstimate` added.

- [ ] **Step 4: Run the test**

Run: `uv run pytest packages/core/tests/test_fiscal_estimate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core
git commit -m "feat(analytics): the annual fiscal estimate, labelled a stima, never per deal"
```

---

## Phase 4B-2 — Adapters and interface

### Task 4B-9: The analytics REST surface, three MCP tools, and the ban still mechanical

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/analytics.py`
- Modify: `apps/api/src/pigrocrm_api/routers/deals.py` (`/pnl` and `/budget`)
- Modify: `apps/api/src/pigrocrm_api/main.py` (register the router)
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/timetracking.py` (three read call-throughs)
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py` (register the three tools)
- Modify: `apps/mcp/src/pigrocrm_mcp/resources/entities.py` (`deal://` gains revenue and margin)
- Modify: `packages/core/tests/test_architecture.py` (**one line**: add `AnalyticsService` to the audited tuple)
- Test: `apps/api/tests/test_analytics_api.py`
- Test: `apps/mcp/tests/test_analytics_tools.py`

**Interfaces:**
- Consumes: `AnalyticsService` and every schema from Tasks 4B-4 … 4B-8; `SessionDep`, `ActorDep`, `PROBLEM_RESPONSES`.
- Produces:
  ```
  GET  /api/deals/{deal_id}/pnl                        -> DealPnl
  GET  /api/deals/{deal_id}/budget                     -> BudgetVsActualRow
  POST /api/deals/{deal_id}/time-entries/to-invoice-draft  (admin) -> InvoiceRead
  GET  /api/analytics/pnl?from=&to=&customer_id=        -> PeriodPnl
  GET  /api/analytics/budget?from=&to=                 -> BudgetPage
  GET  /api/analytics/fiscale?anno=            (admin)  -> FiscalEstimate
  ```
  MCP tools added: `get_deal_pnl`, `get_period_pnl`, `get_budget_vs_actual` — and **nothing else**. `bind_time_to_invoice` and `get_fiscal_estimate` get no tool, which is what the architecture test now enforces for them as well as for the eight it already covered.
- **The exclusion list does not change.** Task 4A-13 declared it as exactly the ten names the spec fixes, including these two, precisely so that this task is a one-line change to `AUDITED_SERVICES` and nothing else.

Note the endpoint spellings: the spec's §11 writes `?from=&to=`, and `from` is a Python keyword. The router therefore declares `da`/`a` as the *parameter names* with `alias="from"`/`alias="to"` so the wire matches the spec while the code stays valid — recorded here rather than silently diverging.

- [ ] **Step 1: Write the failing architecture and API tests**

```python
# packages/core/tests/test_architecture.py -- the ONLY change: AnalyticsService joins the
# audited tuple. The ten-name list is untouched, which is the payoff of declaring it in
# full in Task 4A-13.
        ("pigrocrm.core.analytics.service", "AnalyticsService"),
```

```python
# apps/api/tests/test_analytics_api.py
from decimal import Decimal

from fastapi.testclient import TestClient


def test_deal_pnl_serialises_decimals_as_strings_and_null_percentage(
    api_client: TestClient, admin_cookies, deal_with_hours_no_invoice
) -> None:
    response = api_client.get(
        f"/api/deals/{deal_with_hours_no_invoice}/pnl", cookies=admin_cookies
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ricavi"] == "0.00"
    # `null`, never `"0.00"`: two different facts, and the wire keeps them apart.
    assert body["margine_percentuale"] is None
    assert body["stato"] == "in corso"
    assert body["valore_maturato"] != body["ricavi"]


def test_the_period_report_uses_the_spec_query_names(
    api_client: TestClient, admin_cookies
) -> None:
    """`from` and `to` on the wire, as §11 writes them; `da`/`a` in the code, because
    `from` is a Python keyword. The alias is what keeps both true."""
    response = api_client.get(
        "/api/analytics/pnl",
        cookies=admin_cookies,
        params={"from": "2026-03-01", "to": "2026-03-31"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"chiusi", "in_corso", "spese_generali", "periodo_chiuso",
                         "voci_scritte_in_ritardo"}
    assert "totale" not in body


def test_the_period_filter_is_mandatory(api_client: TestClient, admin_cookies) -> None:
    """Residual B3: paginated with a mandatory period filter from the first commit, because
    a margins view is by nature a list of closed deals and unbounded growth stops being
    invisible here."""
    assert api_client.get("/api/analytics/pnl", cookies=admin_cookies).status_code == 422
    assert api_client.get("/api/analytics/budget", cookies=admin_cookies).status_code == 422


def test_the_budget_list_is_bounded(api_client: TestClient, admin_cookies) -> None:
    over = api_client.get(
        "/api/analytics/budget",
        cookies=admin_cookies,
        params={"from": "2026-01-01", "to": "2026-12-31", "limit": 500},
    )
    assert over.status_code == 422


def test_the_fiscal_report_is_admin_only(api_client: TestClient, collaborator_cookies) -> None:
    response = api_client.get(
        "/api/analytics/fiscale", cookies=collaborator_cookies, params={"anno": 2026}
    )
    assert response.status_code == 403


def test_to_invoice_draft_is_admin_only(
    api_client: TestClient, collaborator_cookies, deal_with_hours_no_invoice
) -> None:
    response = api_client.post(
        f"/api/deals/{deal_with_hours_no_invoice}/time-entries/to-invoice-draft",
        cookies=collaborator_cookies,
        json={"entry_ids": ["11111111-1111-7111-8111-111111111111"]},
    )
    assert response.status_code == 403


def test_the_openapi_document_describes_every_analytics_route(api_client: TestClient) -> None:
    paths = api_client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/deals/{deal_id}/pnl",
        "/api/deals/{deal_id}/budget",
        "/api/deals/{deal_id}/time-entries/to-invoice-draft",
        "/api/analytics/pnl",
        "/api/analytics/budget",
        "/api/analytics/fiscale",
    ):
        assert path in paths, path
```

```python
# apps/mcp/tests/test_analytics_tools.py
"""**Criterion 9**, completed: an agent can read the economics and cannot change what
already-recorded numbers mean, and the two most sensitive operations have no tool at
all."""

from mcp import Client


async def test_the_three_read_tools_exist_and_the_two_excluded_do_not(server) -> None:
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert {"get_deal_pnl", "get_period_pnl", "get_budget_vs_actual"} <= names
    assert "bind_time_to_invoice" not in names
    assert "get_fiscal_estimate" not in names


async def test_get_deal_pnl_returns_the_service_figures_verbatim(
    server, deal_with_hours_no_invoice
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "get_deal_pnl", {"deal_id": str(deal_with_hours_no_invoice)}
        )
    pnl = result.structured_content
    assert pnl["ricavi"] == "0.00"
    assert pnl["margine_percentuale"] is None


async def test_the_deal_resource_now_carries_revenue_and_margin(
    server, deal_with_hours_no_invoice
) -> None:
    async with Client(server) as client:
        rendered = (
            await client.read_resource(f"deal://{deal_with_hours_no_invoice}")
        ).contents[0].text
    assert "## Economia" in rendered
    assert "Ricavi fatturati: 0,00" in rendered or "Ricavi fatturati: 0.00" in rendered
    # An open deal's margin is provisional and the resource says so, rather than handing
    # an agent a figure it will quote as final.
    assert "provvisorio" in rendered
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/core/tests/test_architecture.py apps/api/tests/test_analytics_api.py apps/mcp/tests/test_analytics_tools.py -v`
Expected: FAIL — `test_every_other_public_method_has_a_tool` now lists `AnalyticsService.deal_pnl`, `.period_pnl` and `.budget_vs_actual`; the API paths 404; the tools do not exist.

- [ ] **Step 3: Write the analytics router**

```python
# apps/api/src/pigrocrm_api/routers/analytics.py
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from pigrocrm.core.analytics.schemas import (
    BudgetPage,
    BudgetQuery,
    FiscalEstimate,
    PeriodPnl,
    PeriodPnlQuery,
)
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/analytics", tags=["analytics"], responses=PROBLEM_RESPONSES)

# `from` and `to` on the wire, as spec §11 writes them; `da`/`a` as the parameter names,
# because `from` is a Python keyword. The alias is what keeps both true, and it is
# recorded rather than silently diverging from the spec.
FromDate = Annotated[date, Query(alias="from", description="Inizio del periodo, YYYY-MM-DD")]
ToDate = Annotated[date, Query(alias="to", description="Fine del periodo, YYYY-MM-DD")]


@router.get("/pnl", response_model=PeriodPnl)
def period_pnl(
    session: SessionDep,
    actor: ActorDep,
    da: FromDate,
    a: ToDate,
    customer_id: Annotated[UUID | None, Query()] = None,
) -> PeriodPnl:
    """Two columns, closed deals and deals in progress. There is deliberately no combined
    total: adding a finished job's margin to a half-done one produces a figure that is
    neither."""
    return AnalyticsService(session).period_pnl(
        PeriodPnlQuery(da=da, a=a, customer_id=customer_id), actor
    )


@router.get("/budget", response_model=BudgetPage)
def budget_vs_actual(
    session: SessionDep,
    actor: ActorDep,
    da: FromDate,
    a: ToDate,
    customer_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> BudgetPage:
    """The period filter is mandatory and the list is paginated from the first commit
    (residual B3): a margins view is by its nature a list of closed deals, so unbounded
    growth stops being invisible here."""
    return AnalyticsService(session).budget_vs_actual(
        BudgetQuery(da=da, a=a, customer_id=customer_id, limit=limit, cursor=cursor), actor
    )


@router.get("/fiscale", response_model=FiscalEstimate)
def fiscal_estimate(
    session: SessionDep, actor: ActorDep, anno: Annotated[int, Query(ge=2000, le=2200)]
) -> FiscalEstimate:
    """`admin` — enforced by the service, not here. A router containing an authorisation
    `if` is a router the MCP adapter cannot reuse."""
    return AnalyticsService(session).get_fiscal_estimate(anno, actor)
```

```python
# apps/api/src/pigrocrm_api/routers/deals.py -- append, with the imports.
from pigrocrm.core.analytics.schemas import BindTimeRequest, BudgetQuery, BudgetVsActualRow, DealPnl
from pigrocrm.core.analytics.service import AnalyticsService
from pigrocrm.core.invoices.schemas import InvoiceRead


@router.get("/{deal_id}/pnl", response_model=DealPnl)
def deal_pnl(deal_id: UUID, session: SessionDep, actor: ActorDep) -> DealPnl:
    return AnalyticsService(session).deal_pnl(deal_id, actor)


@router.get("/{deal_id}/budget", response_model=BudgetVsActualRow)
def deal_budget(
    deal_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    da: Annotated[date, Query(alias="from")],
    a: Annotated[date, Query(alias="to")],
) -> BudgetVsActualRow:
    """One deal's row of the estimate-versus-actual report. Served from the same method as
    the list so the two can never disagree: a per-deal reimplementation is how the detail
    page and the report start showing different variances."""
    page = AnalyticsService(session).budget_vs_actual(
        BudgetQuery(da=da, a=a, limit=200), actor
    )
    for row in page.items:
        if row.deal_id == deal_id:
            return row
    raise NotFound("deal_budget", deal_id)


@router.post("/{deal_id}/time-entries/to-invoice-draft", response_model=InvoiceRead)
def to_invoice_draft(
    deal_id: UUID, data: BindTimeRequest, session: SessionDep, actor: ActorDep
) -> InvoiceRead:
    """Builds a draft; issues nothing. `InvoiceService` stays the sole owner of numbering,
    fiscal validation, rounding and freezing."""
    return AnalyticsService(session).bind_time_to_invoice(deal_id, data, actor)
```

Add `from pigrocrm.core.errors import NotFound` to that router's imports, and register `analytics.router` in `main.py`'s router tuple.

- [ ] **Step 4: Add the three MCP tools and the resource block**

```python
# apps/mcp/src/pigrocrm_mcp/tools/timetracking.py -- append.
# Three reads, and only three. `bind_time_to_invoice` and `get_fiscal_estimate` are
# absent by decision, not by omission -- see tools/__init__.py's block comment and
# packages/core/tests/test_architecture.py, which fails the build if either appears here.
from pigrocrm.core.analytics.schemas import BudgetQuery, PeriodPnlQuery
from pigrocrm.core.analytics.service import AnalyticsService


def get_deal_pnl(context: McpContext, deal_id: str) -> dict[str, Any]:
    return (
        AnalyticsService(context.session)
        .deal_pnl(UUID(deal_id), context.actor)
        .model_dump(mode="json")
    )


def get_period_pnl(context: McpContext, query: PeriodPnlQuery) -> dict[str, Any]:
    return (
        AnalyticsService(context.session).period_pnl(query, context.actor).model_dump(mode="json")
    )


def get_budget_vs_actual(context: McpContext, query: BudgetQuery) -> dict[str, Any]:
    return (
        AnalyticsService(context.session)
        .budget_vs_actual(query, context.actor)
        .model_dump(mode="json")
    )
```

```python
# apps/mcp/src/pigrocrm_mcp/tools/__init__.py -- append to register_entity_tools.

    # ---- analytics ---------------------------------------------------------
    # Reads only. `bind_time_to_invoice` has no tool because binding hours to a draft is
    # the step that determines their freezing at issue, and choosing *which* hours to
    # invoice is a commercial decision -- slice 3 §11 withdrew `issue_invoice` with the
    # same reasoning and this is the rung below it. `get_fiscal_estimate` has no tool for
    # a different reason: taxable income, contributions and estimated net for a real
    # person are the most sensitive data this product holds, and residual R10 leaves a PAT
    # indistinguishable from full account access.

    @mcp.tool()
    @guard
    def get_deal_pnl(deal_id: str) -> dict[str, Any]:
        """Conto economico di un deal: ricavi fatturati, costi diretti, costo del lavoro,
        margine e stato. `margine_percentuale` è `null` quando i ricavi sono zero — non
        zero per cento: significa che non è ancora stato incassato niente, non che tutto
        se n'è andato in costi. `valore_maturato` non è un ricavo: è una stima."""
        return timetracking.get_deal_pnl(context, deal_id)

    @mcp.tool()
    @guard
    def get_period_pnl(
        da: str, a: str, customer_id: str | None = None
    ) -> dict[str, Any]:
        """Conto economico di periodo, in due colonne: deal chiusi e deal in corso. Il
        numero riportabile è il primo. `periodo_chiuso` e `voci_scritte_in_ritardo` dicono
        se la cifra può ancora muoversi. Le spese generali stanno in una riga a parte e non
        vengono ripartite su nessun deal."""
        return timetracking.get_period_pnl(
            context,
            PeriodPnlQuery(da=da, a=a, customer_id=UUID(customer_id) if customer_id else None),
        )

    @mcp.tool()
    @guard
    def get_budget_vs_actual(
        da: str, a: str, customer_id: str | None = None, limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Preventivo contro consuntivo per deal. Lo scostamento di valore è calcolato
        contro il preventivo **pro-rata** (preventivo × avanzamento ore), non contro quello
        pieno. Una riga con `non_preventivato = true` non ha alcun preventivo: non è un
        preventivo di zero, ed è esclusa dagli aggregati."""
        return timetracking.get_budget_vs_actual(
            context,
            BudgetQuery(
                da=da, a=a,
                customer_id=UUID(customer_id) if customer_id else None,
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )
```

```python
# apps/mcp/src/pigrocrm_mcp/resources/entities.py -- inside render_deal, after the
# "## Ore" block Task 4A-13 added.
    pnl = AnalyticsService(context.session).deal_pnl(deal.id, context.actor)
    lines.append("")
    lines.append("## Economia")
    lines.append(f"- Ricavi fatturati: {pnl.ricavi} EUR ({pnl.fatture_emesse} fatture emesse)")
    lines.append(f"- Costi diretti: {pnl.costi_diretti} EUR")
    lines.append(f"- Costo del lavoro: {pnl.costo_lavoro} EUR")
    if pnl.stato == "chiuso":
        lines.append(f"- Margine lordo: {pnl.margine_lordo} EUR (definitivo)")
    else:
        # Never called a margin without the qualifier on an unfinished deal: the figure is
        # provisional, and an agent handed a bare number will quote it as final.
        lines.append(f"- Margine lordo: {pnl.margine_lordo} EUR — **provvisorio**")
        lines.append(f"- Valore maturato (stima, non un ricavo): {pnl.valore_maturato} EUR")
    if pnl.margine_percentuale is None:
        lines.append("- Margine %: non calcolabile, nessun ricavo fatturato")
    else:
        lines.append(f"- Margine %: {pnl.margine_percentuale}")
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q`
Expected: PASS, `test_every_other_public_method_has_a_tool` included.

Run: `pnpm -C apps/web generate:api`
Expected: `api-types.ts` gains `DealPnl`, `PeriodPnl`, `BudgetPage`, `BudgetVsActualRow`, `FiscalEstimate` and the six paths. Commit it with this task.

- [ ] **Step 6: Commit**

```bash
git add packages/core apps/api apps/mcp apps/web/src/lib/api-types.ts
git commit -m "feat(analytics): REST and MCP surface, with bind_time_to_invoice and the fiscal estimate off MCP"
```

---

### Task 4B-10: The «Economia» tab, on a deal and on a customer

**Files:**
- Create: `apps/web/src/features/analytics/queries.ts`
- Create: `apps/web/src/features/analytics/EconomicsTab.tsx`
- Create: `apps/web/src/features/analytics/PnlRows.tsx`
- Create: `apps/web/src/features/analytics/ToInvoiceDialog.tsx`
- Modify: `apps/web/src/routes/app/deal/$dealId.tsx` (`economics=`)
- Modify: `apps/web/src/routes/app/clienti/$customerId.tsx` (`economics=`)
- Modify: `apps/web/src/lib/query.ts` (analytics keys)
- Test: `apps/web/src/features/analytics/EconomicsTab.test.tsx`

**Interfaces:**
- Consumes: the regenerated `components['schemas'][…]` types (4B-9); `EntityDetailLayout`'s `economics?: ReactNode` prop added in Task 4A-17; `formatMoneyValue`, `formatHoursValue` (4A-17); `QueryErrorBanner`; `useTimeEntries` (4A-16).
- Produces:
  ```ts
  // features/analytics/queries.ts
  export type DealPnl = components['schemas']['DealPnl']
  export type PeriodPnl = components['schemas']['PeriodPnl']
  export type BudgetVsActualRow = components['schemas']['BudgetVsActualRow']
  export type BudgetPage = components['schemas']['BudgetPage']
  export type FiscalEstimate = components['schemas']['FiscalEstimate']
  export function useDealPnl(dealId: string): UseQueryResult<DealPnl>
  export function useDealBudget(dealId: string, da: string, a: string): UseQueryResult<BudgetVsActualRow>
  export function usePeriodPnl(params: { from: string; to: string; customer_id?: string }): UseQueryResult<PeriodPnl>
  export function useBudget(params: { from: string; to: string; customer_id?: string; limit?: number; cursor?: string }): UseQueryResult<BudgetPage>
  export function useFiscalEstimate(anno: number): UseQueryResult<FiscalEstimate>
  export function useToInvoiceDraft(dealId: string): UseMutationResult<unknown, unknown, { entry_ids: string[]; raggruppa_per_mese: boolean }>

  // components
  export function EconomicsTab(props: { dealId: string } | { customerId: string }): JSX.Element
  export function PnlRows({ pnl }: { pnl: DealPnl }): JSX.Element
  export function ToInvoiceDialog(props: ToInvoiceDialogProps): JSX.Element
  export function formatPercent(value: string | null): string
  ```
  `EconomicsTab` takes a **discriminated** argument — `{dealId: string} | {customerId: string}` — never two optional props, for the reason `useDocuments` already establishes: there is then no "empty string" spelling to get wrong, which is the defect residual B1 names.

- [ ] **Step 1: Write the failing test**

```tsx
// apps/web/src/features/analytics/EconomicsTab.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { EconomicsTab } from './EconomicsTab'

const DEAL = 'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa'
const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const pnl = (overrides = {}) => ({
  deal_id: DEAL, stato: 'in corso', ricavi: '0.00', costi_diretti: '500.00',
  costo_lavoro: '600.00', margine_lordo: '-1100.00', margine_percentuale: null,
  ore_totali: '20.00', ore_fatturabili_non_fatturate: '20.00',
  valore_maturato: '2000.00', ore_senza_tariffa: 0, fatture_emesse: 0, ...overrides,
})

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <EconomicsTab dealId={DEAL} />
    </QueryClientProvider>,
  )
}

describe('EconomicsTab', () => {
  it('never prints a bare margin for a deal in progress', async () => {
    server.use(http.get(`/api/deals/${DEAL}/pnl`, () => HttpResponse.json(pnl())))
    renderTab()
    // §7.3: on an `in corso` deal the margin is provisional and the accrued value sits
    // beside it under a different heading. The word "margine" must never appear alone.
    expect(await screen.findByText(/provvisorio/i)).toBeInTheDocument()
    expect(await screen.findByText(/valore maturato/i)).toBeInTheDocument()
    expect(await screen.findByText(/non è un ricavo/i)).toBeInTheDocument()
    expect(await screen.findByText('2.000,00 €')).toBeInTheDocument()
  })

  it('shows a null margin percentage as "non calcolabile", not as zero per cent', async () => {
    server.use(http.get(`/api/deals/${DEAL}/pnl`, () => HttpResponse.json(pnl())))
    renderTab()
    expect(await screen.findByText(/non calcolabile/i)).toBeInTheDocument()
    expect(screen.queryByText('0,00 %')).not.toBeInTheDocument()
  })

  it('calls a closed deal figure definitive', async () => {
    server.use(
      http.get(`/api/deals/${DEAL}/pnl`, () =>
        HttpResponse.json(
          pnl({
            stato: 'chiuso', ricavi: '10000.00', margine_lordo: '8900.00',
            margine_percentuale: '89.00', ore_fatturabili_non_fatturate: '0.00',
            valore_maturato: '10000.00', fatture_emesse: 2,
          }),
        ),
      ),
    )
    renderTab()
    expect(await screen.findByText(/definitivo/i)).toBeInTheDocument()
    expect(await screen.findByText('89,00 %')).toBeInTheDocument()
    expect(await screen.findByText('8.900,00 €')).toBeInTheDocument()
  })

  it('names the unpriced hours with their count', async () => {
    server.use(
      http.get(`/api/deals/${DEAL}/pnl`, () => HttpResponse.json(pnl({ ore_senza_tariffa: 6 }))),
    )
    renderTab()
    expect(await screen.findByText(/6 voci senza tariffa/i)).toBeInTheDocument()
  })

  it('renders a banner and no figures when the request fails', async () => {
    server.use(
      http.get(`/api/deals/${DEAL}/pnl`, () =>
        HttpResponse.json({ detail: 'Boom' }, { status: 500 }),
      ),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/margine/i)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pnpm -C apps/web exec vitest run src/features/analytics`
Expected: FAIL — `Failed to resolve import "./EconomicsTab"`.

- [ ] **Step 3: Write the queries and the tab**

```ts
// apps/web/src/features/analytics/queries.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

export type DealPnl = components['schemas']['DealPnl']
export type PeriodPnl = components['schemas']['PeriodPnl']
export type BudgetVsActualRow = components['schemas']['BudgetVsActualRow']
export type BudgetPage = components['schemas']['BudgetPage']
export type FiscalEstimate = components['schemas']['FiscalEstimate']

export function useDealPnl(dealId: string) {
  return useQuery({
    queryKey: queryKeys.dealPnl(dealId),
    queryFn: () =>
      unwrap(api.GET('/api/deals/{deal_id}/pnl', { params: { path: { deal_id: dealId } } })),
  })
}

export function useDealBudget(dealId: string, da: string, a: string) {
  return useQuery({
    queryKey: queryKeys.dealBudget(dealId, da, a),
    queryFn: () =>
      unwrap(
        api.GET('/api/deals/{deal_id}/budget', {
          params: { path: { deal_id: dealId }, query: { from: da, to: a } },
        }),
      ),
  })
}

export function usePeriodPnl(params: { from: string; to: string; customer_id?: string }) {
  return useQuery({
    queryKey: queryKeys.periodPnl(params),
    queryFn: () => unwrap(api.GET('/api/analytics/pnl', { params: { query: params } })),
  })
}

export function useBudget(params: {
  from: string
  to: string
  customer_id?: string
  limit?: number
  cursor?: string
}) {
  return useQuery({
    queryKey: queryKeys.budget(params),
    queryFn: () => unwrap(api.GET('/api/analytics/budget', { params: { query: params } })),
  })
}

export function useFiscalEstimate(anno: number) {
  return useQuery({
    queryKey: queryKeys.fiscalEstimate(anno),
    queryFn: () => unwrap(api.GET('/api/analytics/fiscale', { params: { query: { anno } } })),
  })
}

/** Invalidates the P&L, the hours and the deal's timeline: binding hours to a draft
 *  changes what is left to invoice, which all three screens report. */
export function useToInvoiceDraft(dealId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { entry_ids: string[]; raggruppa_per_mese: boolean }) =>
      unwrap(
        api.POST('/api/deals/{deal_id}/time-entries/to-invoice-draft', {
          params: { path: { deal_id: dealId } },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dealPnl(dealId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.dealTimeSummary(dealId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeEntries() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('deal', dealId) })
    },
  })
}
```

```ts
// apps/web/src/lib/query.ts -- append.
  dealPnl: (dealId: string) => ['deal-pnl', dealId] as const,
  dealBudget: (dealId: string, da: string, a: string) =>
    ['deal-budget', dealId, da, a] as const,
  periodPnl: (params: unknown) => ['period-pnl', params ?? {}] as const,
  budget: (params: unknown) => ['budget', params ?? {}] as const,
  fiscalEstimate: (anno: number) => ['fiscal-estimate', anno] as const,
```

```tsx
// apps/web/src/features/analytics/PnlRows.tsx
import { formatHoursValue, formatMoneyValue } from '@/features/time/columns'
import type { DealPnl } from './queries'

const percent = new Intl.NumberFormat('it-IT', {
  style: 'percent',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  useGrouping: 'always',
})

/**
 * `null` renders as «non calcolabile», never as `0,00 %`.
 *
 * Zero per cent means "everything I earned went out in costs"; a null denominator means
 * nothing has been earned yet. Two different facts, and this is the last place they could
 * be flattened after the backend took care to keep them apart (§7.1, criterion 6).
 */
export function formatPercent(value: string | null): string {
  return value === null ? 'non calcolabile' : percent.format(Number(value) / 100)
}

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b py-2 last:border-0">
      <span className="text-muted-foreground">
        {label}
        {hint && <span className="ml-2 text-xs">{hint}</span>}
      </span>
      <span className="text-right font-medium tabular-nums">{value}</span>
    </div>
  )
}

export function PnlRows({ pnl }: { pnl: DealPnl }) {
  const definitive = pnl.stato === 'chiuso'
  return (
    <div>
      <Row
        label="Ricavi fatturati"
        value={formatMoneyValue(pnl.ricavi)}
        hint={`${pnl.fatture_emesse} fatture emesse`}
      />
      <Row label="Costi diretti" value={formatMoneyValue(pnl.costi_diretti)} />
      <Row label="Costo del lavoro" value={formatMoneyValue(pnl.costo_lavoro)} />
      <Row
        label="Margine lordo"
        value={formatMoneyValue(pnl.margine_lordo)}
        // The qualifier is never optional on an unfinished deal: a deal with 20 hours and
        // no invoice has a negative margin, and that is not a loss -- it is unfinished
        // work. The report shows a *state* rather than the bare number (§7.3).
        hint={definitive ? '(definitivo)' : '(provvisorio)'}
      />
      <Row label="Margine %" value={formatPercent(pnl.margine_percentuale)} />
      {!definitive && (
        <Row
          label="Valore maturato"
          value={formatMoneyValue(pnl.valore_maturato)}
          hint="stima — non è un ricavo"
        />
      )}
      <Row label="Ore consuntivate" value={formatHoursValue(pnl.ore_totali)} />
      <Row
        label="Ore da fatturare"
        value={formatHoursValue(pnl.ore_fatturabili_non_fatturate)}
      />
      {pnl.ore_senza_tariffa > 0 && (
        <Row
          label="Voci senza tariffa"
          value={String(pnl.ore_senza_tariffa)}
          hint="escluse dal valore maturato e dal margine"
        />
      )}
    </div>
  )
}
```

```tsx
// apps/web/src/features/analytics/EconomicsTab.tsx
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCanWrite, useIsAdmin } from '@/lib/auth'
import { useState } from 'react'
import { PnlRows } from './PnlRows'
import { ToInvoiceDialog } from './ToInvoiceDialog'
import { useDealPnl, usePeriodPnl } from './queries'

/**
 * A discriminated argument, never two optional props: there is then no "empty string"
 * spelling to get wrong, which is the defect residual B1 names and the same shape
 * `useDocuments` already uses for `{customerId} | {dealId}`.
 */
type EconomicsTabProps = { dealId: string } | { customerId: string }

function DealEconomics({ dealId }: { dealId: string }) {
  const pnl = useDealPnl(dealId)
  const isAdmin = useIsAdmin()
  const [invoicing, setInvoicing] = useState(false)

  if (pnl.isError) return <QueryErrorBanner error={pnl.error} />
  if (pnl.isLoading || !pnl.data) return <Skeleton className="h-64 w-full" />

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="pt-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Conto economico</h2>
            <Badge variant={pnl.data.stato === 'chiuso' ? 'default' : 'secondary'}>
              {pnl.data.stato}
            </Badge>
          </div>
          <PnlRows pnl={pnl.data} />
        </CardContent>
      </Card>

      {isAdmin && Number(pnl.data.ore_fatturabili_non_fatturate) > 0 && (
        <div>
          <Button onClick={() => setInvoicing(true)}>Genera bozza di fattura</Button>
          <p className="mt-2 text-xs text-muted-foreground">
            Crea una bozza raggruppando le ore per tariffa e mese. Non emette niente:
            l&apos;emissione resta un passaggio a parte.
          </p>
        </div>
      )}

      {invoicing && (
        <ToInvoiceDialog dealId={dealId} open onOpenChange={() => setInvoicing(false)} />
      )}
    </div>
  )
}

function CustomerEconomics({ customerId }: { customerId: string }) {
  // A customer's economics is the sum of their deals (§7.4), served by the same period
  // endpoint with a `customer_id` filter -- never a second aggregation written here,
  // which is how two totals begin to disagree. The window defaults to the current year
  // because the endpoint requires one.
  const year = new Date().getFullYear()
  const pnl = usePeriodPnl({
    from: `${year}-01-01`,
    to: `${year}-12-31`,
    customer_id: customerId,
  })

  if (pnl.isError) return <QueryErrorBanner error={pnl.error} />
  if (pnl.isLoading || !pnl.data) return <Skeleton className="h-48 w-full" />

  return (
    <Card>
      <CardContent className="pt-6">
        <h2 className="mb-1 font-semibold">Conto economico {year}</h2>
        <p className="mb-3 text-xs text-muted-foreground">
          Somma dei deal di questo cliente. Le spese generali non sono ripartite su
          nessun cliente e non compaiono qui.
        </p>
        <PeriodTotals pnl={pnl.data} />
      </CardContent>
    </Card>
  )
}

export function EconomicsTab(props: EconomicsTabProps) {
  return 'dealId' in props ? (
    <DealEconomics dealId={props.dealId} />
  ) : (
    <CustomerEconomics customerId={props.customerId} />
  )
}
```

`PeriodTotals` is a small shared component rendering the `chiusi` / `in_corso` pair as two columns with the reportable one marked; it lives in `PnlRows.tsx` beside `PnlRows` and is exported from there. `ToInvoiceDialog` lists the deal's billable unbilled entries from `useTimeEntries({deal_id, fatturabile: true, fatturato: false})` with a checkbox each (all pre-selected), a «Raggruppa per mese» toggle, and a Genera button calling `useToInvoiceDraft`; when the mutation fails with a `ValidationFailed` naming unpriced entries it renders the server's own sentence — the response is an instruction, so it is shown as one.

- [ ] **Step 4: Wire both tabs**

```tsx
// apps/web/src/routes/app/deal/$dealId.tsx -- add the prop.
        economics={<EconomicsTab dealId={dealId} />}

// apps/web/src/routes/app/clienti/$customerId.tsx -- add the prop.
        economics={<EconomicsTab customerId={customerId} />}
```

with `import { EconomicsTab } from '@/features/analytics/EconomicsTab'` in both. In the deal route, the «Preventivo» card's note becomes a link to the new report rather than a promise:

```tsx
                <p className="mt-3 text-xs text-muted-foreground">
                  Il confronto con il consuntivo è nella tab «Economia» e in{' '}
                  <Link to="/app/analisi/preventivo-consuntivo" className="underline">
                    Analisi › Preventivo/consuntivo
                  </Link>
                  .
                </p>
```

- [ ] **Step 5: Run the frontend suite**

Run: `pnpm -C apps/web exec vitest run` and `pnpm -C apps/web tsc --noEmit`
Expected: PASS. The AST guard from Task 4A-16 must stay green: `EconomicsTab` applies `Number()` to `ore_fatturabili_non_fatturate` in the `> 0` test, which the guard forbids — replace that check with `pnl.data.ore_fatturabili_non_fatturate !== '0.00'`, comparing the string the API sent, and note in the guard's `ECONOMIC_FIELDS` docstring that this is exactly the kind of accidental arithmetic it exists to catch.

- [ ] **Step 6: Commit**

```bash
git add apps/web
git commit -m "feat(web): the Economia tab on deals and customers, with a provisional margin named as such"
```

---

### Task 4B-11: `/analisi` — margins, estimate-versus-actual, fiscal

**Files:**
- Create: `apps/web/src/features/analytics/MarginsTable.tsx`
- Create: `apps/web/src/features/analytics/BudgetTable.tsx`
- Create: `apps/web/src/features/analytics/FiscalPanel.tsx`
- Create: `apps/web/src/features/analytics/PeriodPicker.tsx`
- Create: `apps/web/src/features/analytics/columns.tsx`
- Create: `apps/web/src/routes/app/analisi.tsx` (layout with three tabs)
- Create: `apps/web/src/routes/app/analisi/{margini,preventivo-consuntivo,fiscale}.tsx`
- Modify: `apps/web/src/components/AppShell.tsx` (sidebar entry)
- Test: `apps/web/src/features/analytics/BudgetTable.test.tsx`
- Test: `apps/web/src/features/analytics/FiscalPanel.test.tsx`

**Interfaces:**
- Consumes: `usePeriodPnl`, `useBudget`, `useFiscalEstimate` (4B-10); `DataTable` with `DataTableFeatures`; `formatMoneyValue`, `formatHoursValue` (4A-17); `formatPercent` (4B-10); `useIsAdmin`; `QueryErrorBanner`.
- Produces:
  ```tsx
  export function MarginsTable(): JSX.Element
  export function BudgetTable(): JSX.Element
  export function FiscalPanel(): JSX.Element
  export function PeriodPicker(props: { value: { from: string; to: string }; onChange: (value: { from: string; to: string }) => void }): JSX.Element
  export function buildBudgetColumns(): ColumnDef<DataTableFeatures, BudgetVsActualRow>[]
  export function AnalyticsLayout(): JSX.Element   // in features/analytics/, not the route file
  ```
  `AnalyticsLayout` lives in `features/analytics/` and not in `routes/app/analisi.tsx`, so it can be imported by a plain component test — a route file exporting anything beyond `Route` opts that route out of the router plugin's code-splitting, the same reason `SettingsLayout` sits where it does.

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/features/analytics/BudgetTable.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { BudgetTable } from './BudgetTable'

const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const row = (overrides = {}) => ({
  deal_id: 'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa', nome: 'Progetto Alfa',
  ore_preventivate: '100.00', ore_consuntivate: '40.00',
  valore_preventivato: '10000.00', ricavi: '4000.00',
  avanzamento_ore: '40.00', budget_pro_rata: '4000.00',
  scostamento_valore: '0.00', scostamento_ore: '-60.00',
  tariffa_media_preventivata: '100.00', tariffa_media_consuntivata: '100.00',
  non_preventivato: false, pro_rata_non_calcolabile: false, ...overrides,
})

function renderTable() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <BudgetTable />
    </QueryClientProvider>,
  )
}

describe('BudgetTable', () => {
  it('shows the full budget and the pro-rata side by side', async () => {
    server.use(
      http.get('/api/analytics/budget', () =>
        HttpResponse.json({
          items: [row()], next_cursor: null, totale_preventivato: '10000.00',
          totale_ricavi: '4000.00', deal_preventivati: 1, deal_non_preventivati: 0,
        }),
      ),
    )
    renderTable()
    // The full budget is shown *beside* the pro-rata, never instead of it (§9.2).
    expect(await screen.findByText('10.000,00 €')).toBeInTheDocument()
    expect(await screen.findByText('4.000,00 €')).toBeInTheDocument()
    expect(await screen.findByText('40,00 %')).toBeInTheDocument()
  })

  it('says "non preventivato" instead of showing a 100% overrun', async () => {
    server.use(
      http.get('/api/analytics/budget', () =>
        HttpResponse.json({
          items: [
            row({
              ore_preventivate: null, valore_preventivato: null, avanzamento_ore: null,
              budget_pro_rata: null, scostamento_valore: null, scostamento_ore: null,
              tariffa_media_preventivata: null, non_preventivato: true,
            }),
          ],
          next_cursor: null, totale_preventivato: '0.00', totale_ricavi: '0.00',
          deal_preventivati: 0, deal_non_preventivati: 1,
        }),
      ),
    )
    renderTable()
    expect(await screen.findByText(/non preventivato/i)).toBeInTheDocument()
    expect(screen.queryByText('100,00 %')).not.toBeInTheDocument()
    expect(await screen.findByText(/1 deal senza preventivo/i)).toBeInTheDocument()
  })

  it('marks a row whose pro-rata cannot be computed', async () => {
    server.use(
      http.get('/api/analytics/budget', () =>
        HttpResponse.json({
          items: [
            row({
              ore_preventivate: null, avanzamento_ore: null, budget_pro_rata: null,
              scostamento_valore: null, pro_rata_non_calcolabile: true,
            }),
          ],
          next_cursor: null, totale_preventivato: '10000.00', totale_ricavi: '4000.00',
          deal_preventivati: 1, deal_non_preventivati: 0,
        }),
      ),
    )
    renderTable()
    expect(await screen.findByText(/pro-rata non calcolabile/i)).toBeInTheDocument()
  })

  it('renders a banner, never an empty table, when the request fails', async () => {
    server.use(
      http.get('/api/analytics/budget', () =>
        HttpResponse.json({ detail: 'Boom' }, { status: 500 }),
      ),
    )
    renderTable()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/nessun deal/i)).not.toBeInTheDocument()
  })
})
```

```tsx
// apps/web/src/features/analytics/FiscalPanel.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { FiscalPanel } from './FiscalPanel'

const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <FiscalPanel />
    </QueryClientProvider>,
  )
}

describe('FiscalPanel', () => {
  it('puts the word "stima" at the top of the page, not at the bottom', async () => {
    server.use(
      http.get('/api/analytics/fiscale', () =>
        HttpResponse.json({
          anno: 2026, stima: true,
          avvertenza: 'Stima indicativa. Non tiene conto del minimale e del massimale contributivo, di altri redditi, degli acconti già versati né di deduzioni e detrazioni. Per la dichiarazione fai riferimento al tuo commercialista.',
          ricavi: '100000.00', coefficiente_redditivita: '67.00', imponibile: '67000.00',
          aliquota_imposta_sostitutiva: '5.00', imposta_sostitutiva: '3350.00',
          aliquota_inps: '26.07', contributi: '16593.56',
          reddito_netto_stimato: '80056.44',
        }),
      ),
    )
    const { container } = renderPanel()
    const warning = await screen.findByRole('note')
    const figures = await screen.findByText('80.056,44 €')
    // §8: the label goes at the head of the page. Asserted by document order, because
    // "at the top" is the requirement and a footnote satisfies the word and not the point.
    expect(
      warning.compareDocumentPosition(figures) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(warning).toHaveTextContent(/stima/i)
    expect(container.textContent).toMatch(/minimale/)
  })

  it('shows a line as not computable when its parameter is missing', async () => {
    server.use(
      http.get('/api/analytics/fiscale', () =>
        HttpResponse.json({
          anno: 2026, stima: true, avvertenza: 'Stima indicativa.',
          ricavi: '1000.00', coefficiente_redditivita: null, imponibile: null,
          aliquota_imposta_sostitutiva: null, imposta_sostitutiva: null,
          aliquota_inps: null, contributi: null, reddito_netto_stimato: null,
        }),
      ),
    )
    renderPanel()
    expect(await screen.findAllByText(/non calcolabile/i)).not.toHaveLength(0)
    expect(await screen.findByText(/imposta i parametri fiscali/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pnpm -C apps/web exec vitest run src/features/analytics`
Expected: FAIL — both imports unresolved.

- [ ] **Step 3: Write the columns and the three panels**

```tsx
// apps/web/src/features/analytics/columns.tsx
import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { formatHoursValue, formatMoneyValue } from '@/features/time/columns'
import { formatPercent } from './PnlRows'
import type { BudgetVsActualRow } from './queries'

const NOT_BUDGETED = 'non preventivato'
const NO_PRO_RATA = 'pro-rata non calcolabile'

export function buildBudgetColumns(): ColumnDef<DataTableFeatures, BudgetVsActualRow>[] {
  return [
    { header: 'Deal', accessorKey: 'nome' },
    {
      header: 'Ore prev. / cons.',
      id: 'ore',
      accessorFn: (row) =>
        row.non_preventivato
          ? `— / ${formatHoursValue(row.ore_consuntivate)}`
          : `${formatHoursValue(row.ore_preventivate)} / ${formatHoursValue(row.ore_consuntivate)}`,
    },
    {
      header: 'Avanzamento',
      id: 'avanzamento_ore',
      // `null` is "not comparable", never "0%" -- an absent estimate is not an estimate
      // of zero, and a row marked 0% would read as a deal that has done nothing.
      accessorFn: (row) =>
        row.non_preventivato ? NOT_BUDGETED : formatPercent(row.avanzamento_ore),
    },
    {
      header: 'Preventivo pieno',
      id: 'valore_preventivato',
      // Shown BESIDE the pro-rata, never instead of it (§9.2).
      accessorFn: (row) => formatMoneyValue(row.valore_preventivato),
    },
    {
      header: 'Preventivo pro-rata',
      id: 'budget_pro_rata',
      accessorFn: (row) =>
        row.pro_rata_non_calcolabile ? NO_PRO_RATA : formatMoneyValue(row.budget_pro_rata),
    },
    { header: 'Fatturato', id: 'ricavi', accessorFn: (row) => formatMoneyValue(row.ricavi) },
    {
      header: 'Scostamento',
      id: 'scostamento_valore',
      accessorFn: (row) =>
        row.scostamento_valore === null ? '—' : formatMoneyValue(row.scostamento_valore),
    },
    {
      header: 'Tariffa media prev. / cons.',
      id: 'tariffa_media',
      // The row that serves most: how much was realised per hour worked against how much
      // was expected. Comparable even between deals of very different sizes, and the only
      // form in which "is this client worth it?" has a numeric answer.
      accessorFn: (row) =>
        `${formatMoneyValue(row.tariffa_media_preventivata)} / ${formatMoneyValue(
          row.tariffa_media_consuntivata,
        )}`,
    },
  ]
}
```

`PeriodPicker` is two `<input type="month">`-backed date fields defaulting to the current month, emitting `{from, to}` as `YYYY-MM-DD` built from local parts — never `toISOString()`. `MarginsTable` calls `usePeriodPnl` with that window, renders the `chiusi` / `in_corso` pair with the reportable column marked and the general-expenses row beneath, shows `periodo_chiuso` as a badge and `voci_scritte_in_ritardo` as a note («N voci scritte dopo la fine del periodo: questo numero può ancora muoversi»), and lists the deals through `DataTable`. `BudgetTable` calls `useBudget` with the same window, renders `buildBudgetColumns()`, and shows `deal_non_preventivati` as a footnote. `FiscalPanel` renders the `avvertenza` in a `role="note"` block **first**, then the figures, with every `null` line as «non calcolabile» plus a link to `/app/impostazioni/tariffe` reading «imposta i parametri fiscali».

- [ ] **Step 4: Add the layout, the routes and the sidebar entry**

```tsx
// apps/web/src/features/analytics/AnalyticsLayout.tsx
import { Link, Outlet, useRouterState } from '@tanstack/react-router'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const TABS = [
  { value: 'margini', label: 'Margini' },
  { value: 'preventivo-consuntivo', label: 'Preventivo/consuntivo' },
  { value: 'fiscale', label: 'Fiscale' },
] as const

/**
 * Lives here rather than in `routes/app/analisi.tsx` so it can be imported by a plain
 * component test -- a route file exporting anything beyond `Route` opts that route out of
 * the router plugin's automatic code-splitting, which `routeTree.gen.ts` warns about. The
 * same reason `SettingsLayout` sits in `features/settings/`.
 *
 * No `useIsAdmin` gate on the layout: Margini and Preventivo/consuntivo are ordinary
 * reads available to any authenticated actor, and only Fiscale is admin-only -- enforced
 * by the service, surfaced by that panel as a 403 problem document rather than by hiding
 * the tab, so a non-admin gets an explanation instead of a missing feature.
 */
export function AnalyticsLayout() {
  const { location } = useRouterState()
  const active =
    TABS.find((tab) => location.pathname.endsWith(tab.value))?.value ?? 'margini'
  return (
    <div className="p-8">
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">Analisi</h1>
      <Tabs value={active}>
        <TabsList>
          {TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value} asChild>
              <Link to={`/app/analisi/${tab.value}`}>{tab.label}</Link>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="mt-6">
        <Outlet />
      </div>
    </div>
  )
}
```

```tsx
// apps/web/src/routes/app/analisi.tsx
import { createFileRoute } from '@tanstack/react-router'
import { AnalyticsLayout } from '@/features/analytics/AnalyticsLayout'

export const Route = createFileRoute('/app/analisi')({ component: AnalyticsLayout })
```

```tsx
// apps/web/src/routes/app/analisi/margini.tsx
import { createFileRoute } from '@tanstack/react-router'
import { MarginsTable } from '@/features/analytics/MarginsTable'

export const Route = createFileRoute('/app/analisi/margini')({ component: MarginsTable })
```

```tsx
// apps/web/src/routes/app/analisi/preventivo-consuntivo.tsx
import { createFileRoute } from '@tanstack/react-router'
import { BudgetTable } from '@/features/analytics/BudgetTable'

export const Route = createFileRoute('/app/analisi/preventivo-consuntivo')({
  component: BudgetTable,
})
```

```tsx
// apps/web/src/routes/app/analisi/fiscale.tsx
import { createFileRoute } from '@tanstack/react-router'
import { FiscalPanel } from '@/features/analytics/FiscalPanel'

export const Route = createFileRoute('/app/analisi/fiscale')({ component: FiscalPanel })
```

```tsx
// apps/web/src/components/AppShell.tsx -- add after the Ore entry.
  { to: '/app/analisi/margini', label: 'Analisi', icon: TrendingUp },
```

with `TrendingUp` added to the icon imports.

- [ ] **Step 5: Run the frontend suite**

Run: `pnpm -C apps/web exec vitest run` and `pnpm -C apps/web tsc --noEmit`
Expected: PASS, and the AST guard green — every figure on these three screens is rendered from the API's own string.

- [ ] **Step 6: Commit**

```bash
git add apps/web
git commit -m "feat(web): the /analisi reports for margins, budget versus actual and the fiscal estimate"
```

---

### Task 4B-12: End-to-end — the full cycle, from both adapters

**Files:**
- Create: `apps/web/e2e/economics.spec.ts`
- Modify: `apps/web/e2e/fixtures.ts` (reuse `seedDealWithRate` from Task 4A-20)
- Create: `apps/mcp/tests/test_full_cycle.py`

**Interfaces:**
- Consumes: `seedDealWithRate` (4A-20); the Playwright `login` fixture; the in-process MCP `server` fixture and the `Client` used by 4A-13's tool tests.
- Produces: no new exported name — this is the last gate, and **criterion 12** in full.

- [ ] **Step 1: Write the failing MCP-side test**

```python
# apps/mcp/tests/test_full_cycle.py
"""**Criterion 12.** The whole cycle, driven from both adapters, ending on the one thing
an agent must not be able to do.

Claude logs 8 hours through MCP and reads `deal://{id}`; the human generates the invoice
draft and issues it through the API; the deal's P&L then satisfies criterion 1; the
timeline distinguishes `mcp` from `user`; and Claude's attempt to recalculate the rates
finds no tool to call.
"""

from decimal import Decimal

from mcp import Client
from sqlalchemy import text


async def test_the_full_cycle_from_both_adapters(
    server, mcp_session, api_client, admin_cookies, seeded_deal_id, seeded_user_id
) -> None:
    # 1. Claude records the hours and reads the deal back.
    async with Client(server) as client:
        logged = await client.call_tool(
            "log_time",
            {
                "deal_id": str(seeded_deal_id),
                "user_id": str(seeded_user_id),
                "data": "2026-03-10",
                "ore": 8,
                "descrizione": "Analisi e sviluppo",
            },
        )
        entry_id = logged.structured_content["id"]
        rendered = (await client.read_resource(f"deal://{seeded_deal_id}")).contents[0].text
        assert "Ore consuntivate: 8.00" in rendered
        assert "## Economia" in rendered
        assert "provvisorio" in rendered

        # 2. And the tool it must not find, is not there.
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert "recalculate_rates" not in names
        assert "bind_time_to_invoice" not in names
        assert "get_fiscal_estimate" not in names

    # 3. The human turns those hours into a draft and issues it.
    draft = api_client.post(
        f"/api/deals/{seeded_deal_id}/time-entries/to-invoice-draft",
        cookies=admin_cookies,
        json={"entry_ids": [entry_id], "raggruppa_per_mese": True},
    )
    assert draft.status_code == 200
    invoice_id = draft.json()["id"]
    issued = api_client.post(f"/api/invoices/{invoice_id}/issue", cookies=admin_cookies)
    assert issued.status_code == 200
    assert issued.json()["numero"] is not None

    # 4. The P&L now satisfies criterion 1, against direct SQL.
    pnl = api_client.get(f"/api/deals/{seeded_deal_id}/pnl", cookies=admin_cookies).json()
    expected = mcp_session.execute(
        text(
            "SELECT COALESCE(SUM(imponibile), 0) FROM invoices "
            "WHERE deal_id = :id AND tipo = 'fattura' AND stato = 'emessa' "
            "  AND deleted_at IS NULL"
        ),
        {"id": seeded_deal_id},
    ).scalar_one()
    assert Decimal(pnl["ricavi"]) == Decimal(expected)
    assert pnl["stato"] == "chiuso"
    # The hours are invoiced, so the accrued value no longer carries them separately.
    assert Decimal(pnl["valore_maturato"]) == Decimal(pnl["ricavi"])

    # 5. The hour is frozen, and the timeline tells the two actors apart.
    frozen = api_client.patch(
        f"/api/time-entries/{entry_id}", cookies=admin_cookies, json={"ore": "9.00"}
    )
    assert frozen.status_code == 409
    assert frozen.json()["code"] == "immutable_field"

    timeline = api_client.get(
        f"/api/deals/{seeded_deal_id}/timeline", cookies=admin_cookies
    ).json()
    actor_types = {entry["actor_type"] for entry in timeline}
    assert {"mcp", "user"} <= actor_types
```

- [ ] **Step 2: Write the failing browser-side spec**

```ts
// apps/web/e2e/economics.spec.ts
import { expect, test } from './fixtures'
import { seedDealWithRate } from './fixtures'

test.describe('economics', () => {
  test('hours become an invoice, and the margin becomes reportable', async ({
    page,
    request,
    login,
  }) => {
    await login('admin')
    const { dealId } = await seedDealWithRate(request, {
      nome: 'Progetto Economia',
      tariffa: '100.000000',
    })
    await request.patch(`/api/deals/${dealId}`, {
      data: { ore_preventivate: '100.00', valore_preventivato: '10000.00' },
    })
    await request.post('/api/time-entries', {
      data: {
        deal_id: dealId,
        user_id: (await (await request.get('/api/auth/me')).json()).id,
        data: '2026-03-10',
        ore: '40.00',
        descrizione: 'Sviluppo',
      },
    })

    // 1. Before invoicing: provisional, and the accrued value is not called revenue.
    await page.goto(`/app/deal/${dealId}`)
    await page.getByRole('tab', { name: 'Economia' }).click()
    await expect(page.getByText(/provvisorio/i)).toBeVisible()
    await expect(page.getByText(/non calcolabile/i)).toBeVisible()
    await expect(page.getByText(/valore maturato/i)).toBeVisible()
    await expect(page.getByText(/non è un ricavo/i)).toBeVisible()

    // 2. Generate the draft from those hours.
    await page.getByRole('button', { name: /genera bozza di fattura/i }).click()
    await page.getByRole('button', { name: /^genera$/i }).click()
    await expect(page.getByText(/bozza creata/i)).toBeVisible()

    // 3. Issue it, then read the margin back as definitive.
    const invoiceId = new URL(page.url()).searchParams.get('invoice') ?? ''
    if (invoiceId) {
      await request.post(`/api/invoices/${invoiceId}/issue`)
    } else {
      const invoices = await (await request.get(`/api/invoices?deal_id=${dealId}`)).json()
      await request.post(`/api/invoices/${invoices.items[0].id}/issue`)
    }
    await page.reload()
    await page.getByRole('tab', { name: 'Economia' }).click()
    await expect(page.getByText(/definitivo/i)).toBeVisible()
    await expect(page.getByText('4.000,00 €')).toBeVisible()

    // 4. The estimate-versus-actual report shows the pro-rata comparison.
    await page.goto('/app/analisi/preventivo-consuntivo')
    await page.getByLabel(/dal/i).fill('2026-03-01')
    await page.getByLabel(/al/i).fill('2026-03-31')
    await expect(page.getByText('40,00 %')).toBeVisible()
    // Against the pro-rata, so the variance is zero rather than -6.000,00 €.
    await expect(page.getByText('0,00 €')).toBeVisible()
    await expect(page.getByText('10.000,00 €')).toBeVisible()

    // 5. The margins report puts it in the reportable column.
    await page.goto('/app/analisi/margini')
    await page.getByLabel(/dal/i).fill('2026-03-01')
    await page.getByLabel(/al/i).fill('2026-03-31')
    await expect(page.getByTestId('totale-chiusi')).toContainText('4.000,00 €')
    await expect(page.getByTestId('totale-in-corso')).toContainText('0,00 €')

    // 6. The fiscal page leads with the word "stima".
    await page.goto('/app/analisi/fiscale')
    await expect(page.getByRole('note')).toContainText(/stima/i)
  })

  test('a failed request never looks like a zero margin', async ({ page, login, request }) => {
    await login('admin')
    const { dealId } = await seedDealWithRate(request, {
      nome: 'Progetto Errore',
      tariffa: '100.000000',
    })
    await page.route('**/api/deals/*/pnl', (route) => route.abort('failed'))
    await page.goto(`/app/deal/${dealId}`)
    await page.getByRole('tab', { name: 'Economia' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText(/margine/i)).toHaveCount(0)
  })
})
```

- [ ] **Step 3: Run both and watch them fail**

Run: `uv run pytest apps/mcp/tests/test_full_cycle.py -v` and `pnpm -C apps/web exec playwright test e2e/economics.spec.ts`
Expected: FAIL until every earlier 4B task is merged. This task is last and adds no production code of its own — anything it exposes is a defect in one of Tasks 4B-1 … 4B-11 and is fixed there, in that task's own file, not patched here.

- [ ] **Step 4: Run every suite, both plans**

Run: `uv run pytest -q && uv run mypy && uv run ruff check .`
Run: `pnpm -C apps/web exec vitest run && pnpm -C apps/web tsc --noEmit && pnpm -C apps/web exec playwright test`
Expected: all green, no skips.

- [ ] **Step 5: Commit**

```bash
git add apps/web apps/mcp
git commit -m "test(e2e): the full cycle from both adapters, ending on the tool an agent cannot find"
```

---

## Definition of done for plan 4B

- Every suite green, both plans: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `pnpm -C apps/web exec vitest run`, `pnpm -C apps/web tsc --noEmit`, `pnpm -C apps/web exec playwright test`.
- Spec criteria met by 4B: **1** (exact reconciliation, and `imponibile` over `totale` under a synthetic `RF01` — Task 4B-4), **4's third part** (no path lets the same expense in twice — Task 4B-4), **5** (grouped lines, `Σ quantita` = `Σ ore`, freezing at issue, and the derived value ceasing to count — Tasks 4B-3, 4B-7), **6** (an incomplete deal does not lie — Tasks 4B-4, 4B-10), **7** (the pro-rata budget, and `NULL` behaving like `0` — Task 4B-6), **12** (the full cycle — Task 4B-12). Criterion **2's second half** is completed here by `periodo_chiuso` / `voci_scritte_in_ritardo` (Task 4B-5).
- Residual **A14** closed (Task 4B-1). **R5** closed for the fiscal columns (Task 4B-2). **B3** answered for the margins and budget views (Tasks 4B-6, 4B-9).
- The MCP exclusion list is still exactly the ten declared names, and `AnalyticsService` is now audited against it (Task 4B-9).

---

## Self-review

Run against the spec with fresh eyes, section by section.

**1. Spec coverage.** Every section maps to at least one task: §1–§3 (the three decisions) → 4A-7, 4A-8, 4B-4, 4B-7; §2.1 carried knowledge → 4A-14, 4A-15; §2.2's thirteen rewritten defects → 4A-5 (FK, Postgres row-per-entry, UUIDv7, soft delete, `ore > 0`), 4A-9 (raw multi-line description, `Date` not UTC instant, required `user_id`), 4A-4 (Decimal not float), 4A-7 (rates exist at all), 4B-4 (revenue from invoices not offers; uninvoiced deals visible; no dispersed buckets), 4B-8 (personal taxation out of the deal margin), 4B-1 (`PUT` that cannot clear); §4.1–§4.6 → 4A-2, 4A-3, 4A-5, 4A-6, 4B-3; §5 → 4A-7, 4A-9, 4A-11; §6 → 4A-4, 4A-5, 4A-16; §6.3 → 4A-9; §6.4 → 4A-8, 4B-5; §7 → 4B-4, 4B-5; §8 → 4B-2, 4B-8; §9 → 4B-1, 4B-6; §10.1 → 4B-7; §10.2 → 4A-14, 4A-15; §10.3 → 4A-10; §11 → 4A-12, 4A-13, 4B-9; §12's residual table → the Blocking-prerequisites table plus 4A-1, 4A-2, 4B-1; §13's exclusions are honoured by omission and each is named in the task that would otherwise have drifted into it; §14's twelve criteria → mapped explicitly in the two Definition-of-done sections; §15 → 4A-17, 4A-18, 4A-19, 4B-10, 4B-11; §16 → the 4A/4B split itself.

**Two things I could not turn into a concrete task, and both are deliberate.** §11's `deal://{id}` acquiring "ore consuntivate, valore maturato e stato" is split across 4A-13 and 4B-9 because `valore maturato` in §7.3's full sense needs invoices — 4A's resource block carries hours, state and the unbilled estimate, 4B's adds revenue and margin. And §10.1's "il raggruppamento è modificabile nel dialogo prima di generare la bozza" is implemented as a single `raggruppa_per_mese` toggle rather than a free-form line editor: a full editor is slice 3's `replace_lines` surface, already shipped there, and duplicating it here would create a second place invoice lines are composed.

**2. Placeholder scan.** One real placeholder found and fixed inline: Task 4A-18's `WeekGridRow` first drafted the cell-update branch as a raw `fetch`, which the Global Constraints forbid — the task now carries the `useUpdateHours()` mutation and an explicit instruction to replace the `fetch` before committing. Task 4B-7's `activities_for_binding` was named without a leading underscore, which would have made the architecture test demand an MCP tool for it; the task now says to name it `_activities_for_binding`. Task 4B-10 noted that `Number(pnl.data.ore_fatturabili_non_fatturate)` trips 4A-16's own AST guard and gives the string comparison to use instead. Prose descriptions stand in for full component bodies in three places — `CostCategoriesPanel`/`RatesPanel` (4A-19), `PeriodTotals`/`ToInvoiceDialog` (4B-10), `PeriodPicker`/`MarginsTable`/`FiscalPanel` (4B-11) — but each names the exact hook, prop types, formatter and copy to use and points at the shipped file it mirrors, so no decision is left to the implementer.

**3. Type consistency.** Checked across tasks: `billed_entry_ids(session, entries) -> set[UUID]` keeps its signature between 4A-9 and 4B-3 (only the body changes, which is why all four call sites route through it); `to_read(entry) -> TimeEntryRead` is the single producer of `valore_riga`/`costo_riga` and is used by 4A-9, 4A-12 and 4A-14; `DealTimeSummary` (4A-5) deliberately omits `ricavi`/`valore_maturato` and `DealPnl` (4B-4) adds them, so no field means two things; `period_label(anno, mese)` is defined once in 4A-8 and reused by 4A-14 and 4B-7; `month_bounds` lives in 4A-9's repository and is used by 4A-14; `formatMoneyValue`/`formatHoursValue`/`formatRateValue`/`formatIsoDate` are defined once in 4A-17 and imported by 4A-19, 4B-10 and 4B-11; `formatPercent` is defined once in 4B-10; `scaledFromDecimalString`/`sumDecimalStrings` are defined once in 4A-16 and the private `centsFromDecimalString` in `features/deals/columns.tsx` is deleted in that same task rather than left as a second copy. The ten excluded MCP names are spelled identically in 4A-13's `MCP_EXCLUDED`, in `CostCategoryService`'s method names (4A-6), in `PeriodLockService`'s (4A-8), in `TimeEntryService`'s (4A-9, 4A-11) and in `AnalyticsService`'s (4B-7, 4B-8) — which is exactly what makes the architecture test's name matching work.


