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
6. **The timesheet PDF does not redraw the emitter identity block.** Acme's `template-time-tracking.typ` sets `header: none` and draws logo-left / identity-right inline as its first `#grid`, because it had no shared page header. This product's Typst pipeline already renders `render/assets/header.typ.template` from `emitter_profile` via `--include-in-header` for **every** document, and it already carries logo-left / identity-right. **Resolution (Task 4A-14):** the carried-over knowledge — the identity block's *content and placement* — is honoured by the existing header, and the new template body carries the rest of the layout verbatim: the `Periodo / Data emissione` line, the Cliente + Offerta block, the three-column `DATA · ORE · DESCRIZIONE` table at `(0.18fr, 0.12fr, 0.7fr)`, the `0.6pt` divider, and the footer pairing total hours with the entry count. Duplicating the identity block would put it on the page twice.
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

**Why these boundaries.** `timetracking/` is one package rather than four because hours, costs, categories and locks change together — a period lock exists only to protect the other three — but it is split into nine small files because each piece has to be provable alone: `money.py` with no session, `rates.py` with no report, `xlsx.py` with no database. `money.py` sits at the top level, not inside `timetracking/`, because `analytics/` needs the identical rounding and a second copy is how two totals start disagreeing. `analytics/repository.py` holds every aggregate query in one file so that "where does `ricavi` come from" has exactly one answer to read — the defect Acme's three fallback buckets produced was a *dispersed* aggregation, and a single file is the structural answer to it.

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
    attached to nothing is the ghost row Acme produces and no export shows
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
    lands in. Acme's `formatIsoDate` used `toISOString()`, so an hour logged at 23:30
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
    storage, versioning and hash. Acme kept the attachment as base64 inside the costs
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
    """`marzo 2026`. Long-form Italian, carried over from Acme's own period label:
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

<!--PLAN-CONTINUES-->
