# PigroCRM Slice 3 — Fatturazione — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the declared cycle *Contatto → Cliente → Deal → Offerta → Lavoro → Fattura* by giving PigroCRM multi-line invoices with gap-free per-year numbering, a fiscal profile, a FatturaPA FPR12 XML export, proforma invoices, and immutability enforced by the database rather than by convention.

**Architecture:** Everything new lives in `packages/core` as domain services that know nothing about HTTP or MCP, exactly as slices 1 and 2. Two new packages: `fiscal/` (the single-row `fiscal_profile` plus a pure `RegimeStrategy`) and `invoices/` (models, schemas, repository, a pure `totals.py`, a pure `fatturapa.py` exporter built on an `lxml` element tree, a pure `naming.py`, and one `InvoiceService`). The number is assigned by a row-locked per-year counter inside the emission transaction — never a Postgres `SEQUENCE`, whose `nextval()` is non-transactional and would leave a gap on every rollback. The PDF and the XML are produced *after* that transaction commits, from the frozen `snapshot`, so a Typst subprocess never holds a row lock. The two thin adapters import the same services in-process, `packages/core/tests/test_architecture.py` keeps the dependency direction one-way, and a new test in `apps/mcp/tests/` keeps the four irreversible operations off the MCP surface mechanically.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · psycopg 3 · PostgreSQL 17 · MCP SDK v2 · lxml · pytest + testcontainers · Pandoc 3.8.2.1 · Typst 0.14.2 · Vite · React 19 · TanStack Router/Query/Table v9 · shadcn/ui · Tailwind v4 · Playwright

**Spec:** `docs/superpowers/specs/2026-08-20-slice-3-fatturazione-design.md`

**Prerequisite:** slice 1 (`2026-08-06-slice-1a-backend.md`, `2026-08-06-slice-1b-frontend.md`) and slice 2 (`2026-08-10-slice-2-documenti-e-template.md`) complete and in `main`.

---

## Global Constraints

These apply to **every** task. They are not repeated per task. Everything from `## Global Constraints` in the three earlier plans that still applies is carried here with its exact values; the last block is new to this slice.

### Carried from plan 1A (backend)

- **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Managed by **uv workspaces**. Do not use pip, poetry, or venv directly.
- **`packages/core` must never import from `apps.`** — enforced by `packages/core/tests/test_architecture.py`. That test is an *allowlist*: core may import the stdlib, the `pigrocrm` namespace, and only what `packages/core/pyproject.toml` declares under `[project].dependencies`. If a task seems to require anything else, either declare the dependency there or the design is wrong; stop and flag it. **This slice declares exactly one new dependency, `lxml==6.1.2`** (Task 4), and needs no change to `test_architecture.py` because `lxml` imports as itself.
- **Services receive and return Pydantic models only.** No `Request`, `Response`, `HTTPException`, or status codes inside `packages/core`.
- **Every service method that writes takes `actor: Actor`** as an explicit parameter. Never read the actor from global or contextual state.
- **One service method = one transaction.** The service commits; repositories never commit. **One documented exception in this slice**, mandated by spec §3: `InvoiceService.issue` commits the fiscal facts and *then* produces the PDF and XML in a second transaction, because holding the counter's row lock for the duration of a Typst subprocess would serialise every emission on PDF compile time. That exception exists in exactly one method and is spelled out in Task 10.
- **Money is `Numeric(12, 2)`; hours are `Numeric(8, 2)`.** Never `Float` for either. **Extended deliberately in this slice** (spec §6): `quantita` and `prezzo_unitario` are `Numeric(12, 6)` because they are factors, not amounts — at two decimals, 3 hours at 33,3333 €/h is not expressible — and `aliquota_iva` is `Numeric(5, 2)`.
- **All timestamps are `TIMESTAMP WITH TIME ZONE` in UTC.** Use `from datetime import UTC, datetime` → `datetime.now(UTC)`, matching `db/base.py`, never `datetime.utcnow()`. **`data_emissione`, `data_scadenza`, `data_incasso`, `trasmessa_esternamente_il` and `annullata_il` are `Date`, not timestamps** (spec §6.2): they are the dates printed on a document and the ones that decide a fiscal year, not instants. Never derive one by projecting an instant through UTC.
- **All primary keys are UUIDv7** via the shared `pigrocrm.core.db.base.uuid7` wrapper, never `uuid_utils` directly in a model. **One exception:** `invoice_counters` is keyed by `anno INTEGER PRIMARY KEY` (spec §3) — the year *is* the identity, and a surrogate key would need its own uniqueness constraint on `anno` anyway.
- **Soft delete**: entities carry `deleted_at`. Repository queries filter `deleted_at IS NULL` unless explicitly asked otherwise. No physical delete exists anywhere in this slice either. **On `invoices` the soft delete itself is constrained by a `CHECK`** (spec §4) so a numbered row cannot be soft-deleted even by direct SQL.
- **Tests use real PostgreSQL via testcontainers.** Never SQLite — JSONB and GIN indexes do not exist there. Use the existing `db_engine`/`db_session` fixtures in `packages/core/tests/conftest.py`. **`db_session` is savepoint-backed on a single connection and therefore cannot produce real concurrency**: the numbering race test in Task 10 opens its own sessions from `db_engine` and cleans up after itself.
- **TDD is mandatory for `packages/core`.** Write the failing test, watch it fail, then implement.
- **Commit after every task**, using the message given in the task's final step.
- **UI language is Italian.** Field labels, buttons, and error messages shown to users are Italian. Code identifiers, table names, and column names are English except the Italian fiscal and domain terms already fixed in slices 1 and 2 (`partita_iva`, `codice_fiscale`, `codice_sdi`, `pec`, `ragione_sociale`, `indirizzo`, `cap`, `comune`, `provincia`, `nazione`, `tipo`, `titolo`, `stato`, `versione_corrente`, `numero`, `sorgente_markdown`, `variabili`, `variabili_dichiarate`, `corpo_markdown`, `attivo`, `creato_da`, `dimensione`) and the ones this slice's spec fixes (`anno`, `riferimento`, `data_emissione`, `data_scadenza`, `tipo_documento`, `divisa`, `imponibile`, `imposta`, `bollo`, `totale`, `causale`, `righe`, `numero_linea`, `descrizione`, `quantita`, `unita_misura`, `prezzo_unitario`, `sconto_percentuale`, `sconto_importo`, `prezzo_totale`, `aliquota_iva`, `natura`, `riferimento_normativo`, `stato_pagamento`, `data_incasso`, `note_interne`, `annullata_il`, `motivo_annullamento`, `codice_regime`, `applica_bollo`, `soglia_bollo`, `importo_bollo`, `condizioni_pagamento`, `modalita_pagamento`, `giorni_scadenza`, `iban`, `ultimo_numero`, `origine_proforma_id`, `trasmessa_esternamente_il`).
- **The `Expected: PASS (N passed)` counts are indicative, not contractual.** Parametrised tests expand to different totals than the number of test functions. What matters is that every test passes and none is skipped — a differing total is not a failure and must not be "fixed" by deleting or merging cases.
- **A uniqueness pre-check never replaces the database constraint.** Wherever a service does "SELECT to check, then INSERT", it must also catch `sqlalchemy.exc.IntegrityError` around the commit, `session.rollback()`, and re-raise the domain `Conflict`. Two concurrent requests both pass the SELECT; only the constraint stops the second, and without the rollback the caller's session is left poisoned (`PendingRollbackError` on its next statement).
- **Case-insensitive uniqueness needs a functional index, not a convention.** A plain `unique=True` on a text column is case-sensitive. Where identity is case-insensitive, declare `Index("uq_…", func.lower(col), unique=True)` in `__table_args__`. Nothing in this slice has a case-insensitive text identity — `(anno, numero)` are integers — so no functional index is added here.
- **A method named `list` must be the last method in its class.** `def list(...)` rebinds `list` in the class namespace, so any later method annotated `-> list[Something]` resolves it to that method and raises `TypeError: 'function' object is not subscriptable` at import time. Python 3.13 evaluates annotations eagerly, so this is a hard failure here; 3.14's PEP 649 would hide it. Calling `self.list()` from an earlier method is fine — that is a call-time attribute lookup, not an annotation. The rule is unconditional: do not reason about whether a later method *currently* returns a `list[...]`. `packages/core/tests/test_module_imports.py` is the real guard; keep it green. **In this slice it binds `InvoiceService.list` and `InvoiceRepository.list`, both of which must be the last method in their class, and `InvoiceService.lines` — which returns `list[InvoiceLineRead]` — must therefore be defined *above* `list`.**
- **Every `Numeric(p, s)` column needs a matching Pydantic `Field(max_digits=p, decimal_places=s)`** on both schemas. Without it, a value beyond the column's capacity reaches Postgres and raises `NumericValueOutOfRange` — the same uncaught-`DataError`, poisoned-session failure as the string case — and a sub-scale value like `Decimal("0.005")` is silently rounded by the database while the object returned to the caller still shows the original. Reject rather than round.
- **Every `String(n)` column needs a matching Pydantic `max_length=n`** on both the Create and the Update schema. Without it an over-long value reaches Postgres, raises `sqlalchemy.exc.DataError` — **not** a subclass of `IntegrityError`, so no existing handler catches it — and leaves the caller's session poisoned. Where an exact-format check already bounds the length, that check must use **`re.fullmatch`, never `re.match` with `$`**: Python's `$` matches before a trailing newline, so `^\d{11}$` accepts a 12-character string and the value still reaches the database. **This rule applies to every regex in this slice, including `naming.py`'s file-name patterns and `regime.py`'s `RF\d\d` check, which are not database-bound at all** — the habit is what protects the ones that are.
- **Every `Integer` column needs a bounded Pydantic field** (`Field(ge=…, le=…)`) on both schemas, picked to be defensible for that field's meaning. Without a bound, a value like `2**40` reaches Postgres raw as `IntegerOutOfRange`, the same uncaught-`DataError`, poisoned-session failure. **Exception, not violation**: a field already fully bounded by an equivalent service-level range check does not also need a schema-level bound — adding one changes which exception type fires (`pydantic.ValidationError` instead of this project's own `ValidationFailed`) for a same-shaped value the service already rejects correctly, which is a regression. Document any omission in a comment.
- **A NUL byte (`"\x00"`) in a native `String`/`Text` field is rejected, not stored.** Use the shared `pigrocrm.core.validation.SafeStr` annotated type on every user-supplied string field on every Create/Update schema, including inside list fields. Reject, never strip.
- **Every foreign key column is validated against the table it references, in both `create` and `update`**, including one that is optional (`nullable`) — a nullable FK is skipped only when the caller supplies nothing, never when the caller supplies a value. Without this, any syntactically valid UUID reaches `flush()`/`commit()` and comes back as a raw `sqlalchemy.exc.IntegrityError` (`ForeignKeyViolation`) instead of this project's own `NotFound`.
- **Escape LIKE metacharacters in every search filter.** Use the shared `pigrocrm.core.db.escape_like` helper, escape `\`, `%` and `_` (backslash first), and pass `escape="\\"`.
- **Pagination `limit` must be bounded** — `Field(ge=1, le=200)` on the query schema, not only on the router.
- **On update, validate only the custom-field keys the caller supplies**, not the merge of stored and supplied. A supplied key with value `None` removes that entry — and must work even when its definition is archived, no longer exists, or is optional. It must **not** work when the key's current definition is active and `required=True`. Untouched stored keys pass through unchanged, archived ones included.
- **Errors are RFC 9457 problem details with structured `details`.** Raise `pigrocrm.core.errors.{NotFound, ValidationFailed, Conflict, PermissionDenied, ImmutableField}` and never a pre-formatted sentence; `apps/api/src/pigrocrm_api/errors.py::domain_error_handler` renders them. `ValidationFailed(entity, field, reason, expected=…)` must always name the real offending field, because both `fieldErrorFrom` in the web client and an MCP agent read `field`.

### Carried from plan 1B (frontend)

- **No `fetch` inside components.** Every request goes through the generated client wrapped in TanStack Query hooks. The two documented exceptions already in the codebase are multipart upload and blob download, which `openapi-fetch` cannot express (`features/documents/queries.ts`); this slice reuses that same raw-`fetch` shape for the PDF/XML download and adds no third exception.
- **The API client is generated, never handwritten.** `openapi-typescript` reads `openapi.json` from the running API (`pnpm generate:api`). A contract change must break `tsc`, not production.
- **No business logic in the frontend.** Validation messages come from the API's problem documents. Recomputing a rule client-side is how the three interfaces start disagreeing — and on an invoice it is the exact Acme defect this slice exists to remove.
- **No component file over ~250 lines.** If a file approaches the limit, extract.
- **UI language is Italian.** Every visible label, button and message.
- **TypeScript strict mode**, no `any`, no `@ts-ignore`. `tsconfig.json` has `noUncheckedIndexedAccess` on.
- **Commit after every task.**
- **Form state keeps `{native, custom}` as two namespaces, decided once at seed time and never re-derived at submit.** The split lives in the *feature's* form component (`CustomerForm.tsx`, `DealForm.tsx`), not in `DynamicForm`, which is a controlled flat renderer taking one merged `values` object. Provenance is structural: a native column clears on `""` and only on `""` (`model_dump(exclude_none=True)` keeps an empty string and drops a `None`); a custom field clears on `null` and only on `null`; an omitted key clears nothing; an archived custom key is omitted entirely so the server carries the stored value over. `0` and `false` are values, never blanks — mirror the shipped `isBlank` in `CustomerForm.tsx` exactly, which is itself a mirror of `fields/validator.py::is_blank`.
- **Never sum money as a JS float.** `Numeric` columns arrive as strings in the generated types; format them with `Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', useGrouping: 'always' })` and, where a sum is unavoidable, add integer cents parsed by splitting the string on `.` — `Number("0.29") * 100` is `28.999999999999996`. `useGrouping: 'always'` is not optional: the default withholds the thousands separator below five integer digits. The shipped exemplar is `apps/web/src/features/deals/columns.tsx`, whose `centsFromDecimalString` is **private to that module** — the codebase's stated precedent is a small per-feature display helper rather than a shared module, so the invoice feature carries its own copy rather than widening that file's public surface and its `columns.test.ts`.
- **`DynamicForm` takes a required, undefaulted `mode: 'create' | 'edit'` prop.** Every new call site answers the question explicitly. Its props are exactly `{ fields, values, onChange, problem?, mode }`.
- **A failed request must never look like an empty result.** A query in `isError` renders `QueryErrorBanner` (`apps/web/src/components/QueryErrorBanner.tsx`, props `{ error: unknown }`), never an empty table or an empty list. `DataTable` already does this internally when `isError && data.length === 0`.
- **`DataTable` is TanStack Table v9** (`@tanstack/react-table 9.0.0`): `tableFeatures({})` + `useTable({ features, columns, data })`, `ColumnDef<DataTableFeatures, T>` with the feature type parameter **first**, `row.getAllCells()`, and rendering through the table-bound `<table.FlexRender header={…} />` / `<table.FlexRender cell={…} />`. There is no `useReactTable`, no `getCoreRowModel`, no `getVisibleCells` and no standalone `flexRender()` in v9. Its props are exactly `{ columns, data, isLoading?, isError?, error?, onRowClick?, emptyMessage? }`.
- **`unwrap` throws the `ProblemDetail` object itself**, not an `Error` and not a `Response`. A form-level failure goes to `setProblem(toProblem(error))`; a page-level action's failure goes to `toast.error(...)` from `sonner`. `toProblem` is idempotent on an already-normalised problem.
- **`tsconfig.json` has `noUncheckedIndexedAccess`, `noUnusedLocals` and `noUnusedParameters` on**, and `build` is `vite build && tsc --noEmit`. Indexing an array or a `Record` yields `T | undefined` and must be narrowed.
- **A new module that exports both a component and a non-component needs its own `react-refresh/only-export-components` override in `apps/web/eslint.config.js`**, with `allowExportNames`. Every shipped form and every detail route already has one; without it `pnpm lint` fails. There is no `pnpm test` script: unit tests run as `pnpm exec vitest run`, end-to-end as `pnpm test:e2e` (which is `bash scripts/e2e.sh`).

### Pinned versions

Backend (slice 1A, resolved and verified 2026-08-06 — unchanged): `fastapi 0.141.1` · `uvicorn 0.52.1` · `sqlalchemy 2.0.51` · `alembic 1.19.0` · `psycopg[binary] 3.3.4` · `pydantic 2.13.4` · `pydantic-settings 2.14.2` · `email-validator 2.3.0` · `argon2-cffi 25.1.0` · `pyjwt[crypto] 2.13.0` · `mcp 2.0.0` · `uuid-utils 0.17.0` · `pytest 9.1.1` · `pytest-cov 7.1.0` · `pytest-asyncio 1.4.0` · `testcontainers[postgres] 4.15.0` · `httpx 0.28.1` · `ruff 0.16.1` · `mypy 2.3.0`

Frontend (slice 1B — unchanged): `vite 8.2.0` · `react 19.2.8` · `react-dom 19.2.8` · `typescript 5.9` (**not** 7.x) · `@tanstack/react-router 1.170.20` · `@tanstack/router-plugin 1.168.25` · `@tanstack/react-query 5.101.4` · `@tanstack/react-table 9.0.0` · `tailwindcss 4.3.3` · `@tailwindcss/vite 4.3.3` · `shadcn 4.16.1` · `@dnd-kit/core 6.3.1` · `@dnd-kit/sortable 10.0.0` · `openapi-typescript 7.13.0` · `openapi-fetch 0.17.0` · `@playwright/test 1.62.1` · `vitest 4.1.10` · `sonner 2.0.7` · `radix-ui 1.6.7` · `lucide-react` latest · `@tabler/icons-react` latest (**brand icons only**). Package manager: **pnpm 10**.

Render toolchain (slice 2 — **the values actually shipped**, which are not the ones slice 2's plan text pinned): `TYPST_VERSION=0.14.2` and `PANDOC_VERSION=3.8.2.1`, as build args in `Dockerfile.api`. See contradiction 5 below.

**New to this slice:** `lxml==6.1.2` in `packages/core/pyproject.toml` `[project].dependencies`. FPR12 schema, vendored under `packages/core/tests/fpr12/`: `Schema_VFPR12_v1.2.3.xsd` (from `https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.4/Schema_VFPR12_v1.2.3.xsd`) and `xmldsig-core-schema.xsd` (from `https://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd`).

### Design tokens (exact values — do not improvise)

| Token | Hex | Role |
|---|---|---|
| Watermelon | `#ED254E` | primary action, destructive state |
| Royal Gold | `#F9DC5C` | warning, attention |
| Mint Cream | `#F4FFFD` | app background (light) |
| Prussian Blue | `#011936` | foreground text, dark surface |
| Charcoal Blue | `#465362` | muted / secondary text |

Font: **Outfit** only. `Reenie Beanie` belongs to the landing page in slice 5 — do **not** load it here. Contrast must reach **WCAG AA**; for body copy on light backgrounds use Prussian Blue.

### New to slice 3

- **XML is built as an element tree and serialised once, never concatenated.** No function anywhere in `invoices/fatturapa.py` may produce a fragment of XML as a string. Markup injection then becomes impossible *by structure*, not by remembering to call an escaper — which is precisely how Acme's generator stayed correct only as long as every interpolation site remembered `escapeXml`.
- **One escaper per value, applied to the domain value.** A value that reached the XML has never been through `escape_typst`, `escape_markdown` or `escape_url`. The `xml` context added to `RenderContext` in Task 1 is a *refusal*, not a substitution: it rejects code points XML 1.0 cannot represent and returns the value byte-for-byte otherwise, because the tree serialiser is the one and only escaping pass. Acme's literal backslash inside an Agenzia delle Entrate record came from stacking two escapers; there is no code path here that can stack them.
- **`lxml`, not `xml.etree.ElementTree`.** `lxml` accepts an explicit `nsmap` on the root element, so the `ds:` and `xsi:` declarations that a prologue already accepted by the SdI carries survive even though this file references neither. ElementTree prunes unreferenced prefixes.
- **No fiscal decision is an `if` inside the generator.** Default VAT rate, `Natura`, `RiferimentoNormativo` and the stamp-duty threshold come from `fiscal_profile` through a `RegimeStrategy`. A second regime is a second strategy object, with no new column and no migration.
- **`ROUND_HALF_UP`, never the `Decimal` default `ROUND_HALF_EVEN`.** Italian fiscal practice and the SdI's own arithmetic round a half up. Every `quantize` in this slice passes `rounding=ROUND_HALF_UP` explicitly.
- **A group's `ImponibileImporto` is the sum of already-rounded `PrezzoTotale` values, and its `Imposta` is computed from the group, not summed from the lines.** The SdI checks both, and the two rules disagree by cents; spec §6.1 fixes which one wins where. The forfettario ships with every tax at zero, so a synthetic `RF01` strategy exists in test fixtures for the sole purpose of making these rules observable.
- **An issued invoice is fiscal, so the database enforces what it can.** The `(tipo, stato)` pairs, the `(aliquota_iva = 0) = (natura IS NOT NULL)` agreement, the contiguity of `numero_linea`, and the impossibility of soft-deleting a numbered row are all table constraints. Defending an invariant only in the service leaves it reachable from any other write path.
- **The MCP surface cannot emit.** `issue_invoice`, `annul_invoice`, `mark_transmitted_externally` and `update_fiscal_profile` have no MCP tool, and the ban is imposed by *not registering the tool* rather than by an authorisation check, because R10 (a PAT has no scope and inherits the owner's full role) means an authorisation check would be passed by an administrative token. A test asserts the exclusion list is exactly those four names.

---

## Known open defects this slice must not walk into

From `docs/superpowers/specs/2026-08-07-slice-1a-residui.md` and `2026-08-06-slice-1b-residui.md`. Each entry either constrains a task here or is explicitly out of scope.

- **R1 — the MCP server shares one SQLAlchemy `Session` across concurrent calls.** Still open. The row lock in Task 10 is correct only if every call has its own session and its own transaction; the MCP process shares one. This slice **does not depend on that being fixed**, because the MCP surface never emits (Task 15) and therefore never takes that lock. It is written down here because the obvious "completion" of the MCP surface — adding `issue_invoice` — would reintroduce a numbering race with nothing in the code to say why it was left out. Task 15's ban test is what makes that impossible to do by accident.
- **R2 — the MCP SDK validates some arguments before `_guard` runs.** Task 15 reuses the existing `WithJsonSchema` technique from `apps/mcp/src/pigrocrm_mcp/tools/__init__.py` (`BoundedLimit` verbatim, plus a new `InvoiceStatoArg`) for every strict scalar it introduces, so no new raw pydantic dump is added.
- **R5 — no audit trail for configuration.** Closed **for `fiscal_profile` only** (Task 6): every upsert writes an activity, because changing fiscal regime without a trace is a different order of severity from renaming a pipeline stage, and the timeline is also what reconstructs the history of regimes without a `valido_da`/`valido_a` column. Open for everything else; this slice does not claim otherwise.
- **R9 — sorting does not exist in either adapter.** Not fixed. `InvoiceRepository.list` orders server-side by `id` (UUIDv7, i.e. creation order) with no caller-supplied sort, matching every other list in the codebase, so no half-feature is added.
- **R10 — PATs have no scope, inherit the full role and never expire.** This is the *reason* the MCP ban in Task 15 is structural rather than a permission check: an administrative PAT would pass `actor.require_admin`. Not fixed here.
- **R12 — a foreign VAT number cannot even be stored** (`customers.partita_iva` is `\d{11}`). This slice works around it by declaring foreign customers out of scope and refusing emission when `nazione != 'IT'`, with a `ValidationFailed` that names the field (Task 9). That is honest, not a fix, and the residuo stays open.
- **R13 — `entity_type` is not "open"; it is a closed `Literal` extended in four places.** Task 8 does exactly that, for the fourth time, and stops repeating the claim.
- **A13 — a custom-field key can collide with a native column.** `FieldDefinitionService.create` still compares a slugified label only against other definitions, never against `native_fields()`. Task 8 makes `native_fields("invoice")` **complete** — including the derived fiscal columns `totale`, `imponibile`, `imposta`, `numero`, `anno`, which are not on `InvoiceCreate` and so would otherwise be absent from the derived list — so that when slice 1A's guard lands it protects the fiscal columns too. **Today the collision remains reachable**, because nothing consults `native_fields` during field creation. The plan does not pretend to close A13; it makes the data the fix will need correct.
- **A14 — `exclude_none=True` means a typed native column cannot be cleared.** Sidestepped structurally, not papered over: invoice lines are **replaced in bulk** (`PUT /api/invoices/{id}/lines`), so `sconto_importo` and `unita_misura` never need a "clear it" spelling; `InvoiceUpdate` exposes only `note_interne` (`Text`, clearable with `""`) and `custom_fields`; `stato`, `stato_pagamento` and `data_incasso` are changed only through dedicated methods taking required non-nullable values. That removes the A14 shape from this slice's surface.
- **B1 — no automatic test on a hook called with an empty id.** Task 16's `useInvoice(invoiceId)` carries the same `enabled: invoiceId !== ''` guard as `useDocument`, and Task 16 ships a test for it.

---

## Contradictions between the spec and the shipped code, and how they were resolved

Resolved in favour of the shipped code, as instructed. Each was verified by reading the file named, not by trusting the spec's own list.

1. **`EntityType` already contains `"document"`.** Spec §8.5 says `fields/schemas.py:12` is `EntityType = Literal["customer", "person", "deal"]`. **Verified false:** `packages/core/src/pigrocrm/core/fields/schemas.py:17` is `EntityType = Literal["customer", "person", "deal", "document"]` — slice 2 already appended one. The spec's *substance* holds (the type is closed and must be widened); its citation is one slice stale. **Resolution (Task 8):** append `"invoice"` to that `Literal`, to `ENTITY_TYPES` and `CREATE_MODELS` in `schema_registry.py`, and to `EntityType` in `apps/web/src/lib/schema.ts`. Four places, no migration.
2. **`native_fields()` is derived, not hand-listed.** Spec §8.5 says the cost is "una riga nel `Literal` più una voce in `native_fields("invoice")`". **Verified:** `schema_registry.py:32-34` derives the list from `CREATE_MODELS[entity_type].model_fields`, so registering `InvoiceCreate` produces a list automatically — and that list is *wrong for this entity*, because an invoice's most collision-prone names (`totale`, `imponibile`, `imposta`, `numero`, `anno`, `stato`) are derived columns absent from the Create schema. **Resolution (Task 8):** add an `EXTRA_NATIVE_FIELDS` mapping to `schema_registry.py`, empty for the three existing entity types and populated for `invoice`, and have `native_fields` union it in. The derivation stays the default; the one entity whose native surface is bigger than its Create schema declares the difference explicitly.
3. **`emitter_profile` already has a `regime_fiscale` column.** Spec §7.1 introduces `fiscal_profile.codice_regime` as if nothing described the regime yet. **Verified:** `emitter/models.py:42` is `regime_fiscale: Mapped[str | None] = mapped_column(String(200), default=None)` — free text, 200 characters, used today only as a line of prose in the offer header. **Resolution (Task 6):** `fiscal_profile.codice_regime` is `String(4)` with a `RF\d\d` check and is the **only** input to the XML's `RegimeFiscale`; `emitter_profile.regime_fiscale` keeps its current meaning — a human-readable sentence for the PDF header — and is left untouched, because renaming or dropping a shipped column that slice 2's `header.typ.template` already reads is a migration this slice has no reason to pay for. The two are not duplicates: one is a code the SdI validates, the other is a caption.
4. **The success criterion names FPR12 v1.2.1; the schema in force is v1.2.3.** Spec §14.1 says "XSD FPR12 v1.2.1". **Verified against `fatturapa.gov.it`:** the current *fattura ordinaria* schema is `Schema_VFPR12_v1.2.3.xsd`, in force since 2025-04-01, and v1.2.1 is no longer published on that page. The `versione="FPR12"` attribute is unchanged across 1.2.x, so nothing about the generator changes. **Resolution (Task 4):** vendor and validate against **1.2.3**. Validating against a superseded schema would prove the file valid for a rule set the SdI no longer applies.
5. **`xmllint --schema` is replaced by `lxml.etree.XMLSchema`, and the `ds:` import is resolved locally.** Spec §14.1 names `xmllint`. Two facts force a change: nothing in the repo installs `libxml2-utils` (`Dockerfile.api` installs only Pandoc, Typst and `libpq5`), and the official XSD's single `xs:import` points at a **remote** `http://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd`, which a CI run with no network cannot fetch. **Resolution (Task 4):** validate with `lxml.etree.XMLSchema` — the same libxml2 engine `xmllint` is a CLI over, already a dependency because the generator needs it, so no new binary in the image — and resolve that one import through an `lxml.etree.Resolver` mapping the exact remote URL to the vendored sibling file. The official XSD is committed **byte-for-byte unmodified**: hand-editing a `schemaLocation` inside a fiscal schema to make a test pass is exactly the kind of edit nobody reviews twice.
6. **The shipped render toolchain is Pandoc 3.8.2.1 / Typst 0.14.2, not slice 2's plan text.** Slice 2's Global Constraints pin `PANDOC_VERSION=3.1.12.2` and `TYPST_VERSION=0.11.0` "as `.reference-acme/Dockerfile` pins them". **Verified:** the shipped `Dockerfile.api` pins `ARG TYPST_VERSION=0.14.2` and `ARG PANDOC_VERSION=3.8.2.1`, with a comment recording that `render/diagnostics.py`'s `_LOCATION_RE` and `render/pdf.py`'s `_defeat_typst_autotypography` were confirmed against 0.14.2 specifically. **Resolution:** this plan's pinned versions are the shipped pair. Task 13's templates are written for Typst 0.14.2.
7. **The SdI file-name convention cannot be a storage key.** Spec §8.4 asks for `IT{cf_o_piva}_{progressivo}.xml`. **Verified:** `storage/base.py:40`'s `_KEY_RE` is `[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*` — lowercase only, deliberately, because two keys differing only in case name the same file on APFS and NTFS. `IT…` uppercase is refused. **Resolution (Tasks 5, 12):** the SdI name is the **download** file name, in `Content-Disposition` on `GET /api/invoices/{id}/xml`, which is where it matters — the file goes to an intermediary that often validates the name before the content. The storage key stays lowercase and structural: `fatture/{anno}/{numero}/v{n}.xml`, `proforma/{invoice_id}/v{n}.pdf`.
8. **`issue_invoice` takes the source row's id in the path, and `origine_proforma_id` is set by the method rather than passed to it.** Spec §11 says `issue_invoice` "accetta un `origine_proforma_id` facoltativo" while pinning the endpoint to `POST /api/invoices/{id}/issue`; spec §5 says the conversion **creates a new row** pointing at the proforma. Passing both an `{id}` and an `origine_proforma_id` makes two ways to say the same thing, and the second would need a "duplicate this proforma as a draft" endpoint nobody asked for. **Resolution (Task 10):** one method, `InvoiceService.issue(invoice_id, data, actor)`, where `invoice_id` names either a `bozza` **fattura** (issued in place) or a `confermata` **proforma** (a new `emessa` row is created, its lines copied, `origine_proforma_id` set to the proforma, and the proforma marked `consumata`). One endpoint, one lock, one set of validations, one freezing step — which is the property §11 asked for.
9. **The MCP ban test needs two declared lists, not one.** Spec §11 says the architecture test grows a clause: "for every public method of `InvoiceService`, either an MCP tool calls it, or the method is in a declared exclusion list — and the list must be **exactly** `issue_invoice`, `annul_invoice`, `mark_transmitted_externally`, `update_fiscal_profile`." Taken literally that is unsatisfiable: `update`, `soft_delete`, `export_xml`, `produce_artifacts`, `download` and `lines` have no MCP tool either, and none of them is one of the four. **Resolution (Task 15):** two declared sets, `MCP_FORBIDDEN_OPERATIONS` — asserted to be exactly those four names — and `MCP_UNEXPOSED_OPERATIONS`, each entry carrying its one-line reason. The test asserts every public method falls in exactly one of three buckets (reached by a tool, forbidden, or declared-unexposed), so adding a method without deciding which it is breaks the build. The spec's substantive requirement is met exactly; conflating "must never be exposed" with "happens not to be exposed" would have made the four-name assertion meaningless within a slice.

10. **The proforma reference comes from one sequence, not a sequence per year.** Spec §5 says the proforma's `riferimento` comes from "una `SEQUENCE` Postgres per anno". A sequence per year means either creating a sequence with runtime DDL inside a request, or pre-creating a hundred of them in a migration. **Resolution (Task 8):** one `proforma_riferimento_seq`, never reset, with the label `PROV-{anno}-{nextval:04d}`. The spec's *reason* for choosing a sequence here is honoured exactly — `nextval()` does not roll back, gaps on a proforma mean nothing, and in exchange the counter serialises nobody — and "per year" was only ever cosmetic, since the number carries no fiscal meaning and the year is already in the label.

11. **The invoice and proforma layouts are repo assets, not rows in the `templates` table.** Spec §10 says "due template nuovi, `fattura` e `proforma`" without saying where they live. **Verified:** `templates` rows are user-editable with no per-row version history, and `render/assets/template-offer.md` shows the shipped precedent for a layout that lives in the package. A fiscal document whose layout can be silently edited between issue and re-render cannot satisfy §14.6's byte-for-byte re-render. **Resolution (Task 13):** `render/assets/template-invoice.md` and `render/assets/template-proforma.md`, read from disk, filled from the frozen `snapshot`. `"fattura"`/`"proforma"` are still added to `DocumentTipo` because `documents.tipo` needs them (§8.4); that they become legal `templates.tipo` values too is harmless.

---

## File Structure

```
packages/core/pyproject.toml                  # MODIFIED: + lxml==6.1.2
packages/core/src/pigrocrm/core/
├── templates/escaping.py                     # MODIFIED: RenderContext + "xml", escape_xml
├── fields/schemas.py                          # MODIFIED: EntityType gains "invoice"
├── schema_registry.py                         # MODIFIED: ENTITY_TYPES, CREATE_MODELS, EXTRA_NATIVE_FIELDS
├── models_registry.py                         # MODIFIED: imports the four new models
├── documents/schemas.py                       # MODIFIED: DocumentTipo + ALLOWED_CONTENT_TYPES gain xml
├── documents/service.py                       # MODIFIED: storage_key_for/add_version take a prefix
├── fiscal/
│   ├── models.py                              # FiscalProfile — one row
│   ├── schemas.py                             # FiscalProfileUpsert / FiscalProfileRead / FiscalSnapshot
│   ├── repository.py                          # FiscalProfileRepository
│   ├── service.py                             # FiscalProfileService (+ activity on every upsert)
│   └── regime.py                              # RegimeStrategy: RF19 forfettario, RF01 ordinario
└── invoices/
    ├── models.py                              # Invoice · InvoiceLine · InvoiceCounter
    ├── schemas.py                              # every Pydantic shape, incl. InvoiceSnapshot
    ├── repository.py                           # queries + the FOR UPDATE counter read
    ├── totals.py                               # pure money maths: line_total, build_riepilogo, sum_totals
    ├── naming.py                               # progressivo_invio, sdi_filename, storage prefixes
    ├── fatturapa.py                            # FatturaPAExporter — lxml tree, no DB
    ├── pdf.py                                  # snapshot -> template scope -> PDF bytes
    └── service.py                              # InvoiceService — the only writer
packages/core/migrations/versions/
└── 0004_invoices_fiscal_profile.py
packages/core/src/pigrocrm/core/render/assets/
├── template-invoice.md                         # carried from .reference-acme/offer/template-invoice.md
└── template-proforma.md
packages/core/tests/fpr12/
├── __init__.py                                 # fpr12_schema() -> etree.XMLSchema, local ds: resolver
├── Schema_VFPR12_v1.2.3.xsd                    # official, unmodified
└── xmldsig-core-schema.xsd                     # official, unmodified

apps/api/src/pigrocrm_api/
├── main.py                                     # MODIFIED: register the two new routers
└── routers/{invoices,fiscal_profile}.py

apps/mcp/src/pigrocrm_mcp/tools/
├── __init__.py                                 # MODIFIED: register the read/proforma tools
└── invoices.py                                 # thin calls + MCP_FORBIDDEN_OPERATIONS

apps/web/src/
├── lib/schema.ts                               # MODIFIED: EntityType gains 'invoice'
├── lib/query.ts                                # MODIFIED: invoice + fiscal-profile query keys
├── components/EntityDetailLayout.tsx           # MODIFIED: optional `invoices` tab
├── components/AppShell.tsx                     # MODIFIED: NAV gains Fatture
├── features/invoices/
│   ├── queries.ts                              # types, hooks, labels, transitions
│   ├── format.ts                               # exact-cents money, dates, number label
│   ├── columns.tsx                             # DataTable columns
│   ├── InvoiceStateBadge.tsx                   # state + collection badges
│   ├── InvoiceLinesEditor.tsx                  # the multi-line editor
│   ├── InvoiceForm.tsx                         # create draft / proforma
│   ├── InvoiceActions.tsx                      # issue · annul · transmitted · payment
│   └── InvoicesTab.tsx                         # the customer/deal detail tab
├── features/settings/FiscalProfilePanel.tsx    # beside the shipped EmitterPanel
├── routes/app/fatture/{index.tsx,$invoiceId.tsx}
└── routes/app/impostazioni/fiscale.tsx
apps/web/e2e/fatture.spec.ts
apps/web/eslint.config.js                       # MODIFIED: four only-export-components overrides
```

**Why these boundaries:** `totals.py`, `naming.py`, `regime.py` and `fatturapa.py` are pure and have no database, no I/O and no session — which is what lets the arithmetic rules of §6.1 and the hostile-input cases of §14.2 be proven without a container, and what keeps `service.py` a sequence of decisions rather than a place where maths and XML hide. `invoices/pdf.py` is separate from `render/pdf.py` because the latter is the generic Pandoc/Typst runner and must stay ignorant of invoices. `fiscal/` is its own package rather than a file inside `invoices/` because the profile is configuration read by both the invoice service and, later, anything else that needs the regime.

---
# Phase 1 — The fiscal kernel

Six tasks, no database, no I/O, no session. This phase is first because it holds every rule that is expensive to get wrong and cheap to prove: the escaping contract, the rounding rules, the regime, and the XML itself.

### Task 1: The `xml` render context

**Files:**
- Modify: `packages/core/src/pigrocrm/core/templates/escaping.py`
- Test: `packages/core/tests/test_template_escaping.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RenderContext = Literal["markdown", "typst", "typst_string", "url", "verbatim", "xml"]`
  - `escape_xml(value: str) -> str` — returns `value` unchanged, raising `ValueError` when it contains a code point XML 1.0 cannot represent
  - `escape_for("xml", value)` dispatches to it

- [ ] **Step 1: Write the failing test**

Append to `packages/core/tests/test_template_escaping.py`:

```python
# --- the xml context (slice 3) ---------------------------------------------


def test_xml_context_returns_the_domain_value_untouched() -> None:
    """The tree serialiser is the one and only escaping pass. Acme put a literal
    backslash into an Agenzia delle Entrate record by running a value through
    escapeTypstText and then escapeXml; there is no code path here that can stack
    two escapers, because this one substitutes nothing."""
    hostile = 'Rossi & C. <IdCodice>999</IdCodice> "#$@\\ ]]>'
    assert escape_xml(hostile) == hostile
    assert escape_for("xml", hostile) == hostile


@pytest.mark.parametrize(
    "forbidden",
    [
        "\x00",  # NUL, also refused by SafeStr upstream
        "\x01",
        "\x08",
        "\x0b",  # vertical tab
        "\x0c",  # form feed
        "\x1f",
        "￾",
        "￿",
        "\ud800",  # a lone surrogate, reachable in a Python str
    ],
)
def test_xml_context_refuses_a_code_point_xml_cannot_represent(forbidden: str) -> None:
    with pytest.raises(ValueError, match="non rappresentabile in XML"):
        escape_xml(f"Rossi{forbidden}C.")


@pytest.mark.parametrize("allowed", ["\t", "\n", "\r", "à", "€", "𝄞"])
def test_xml_context_allows_every_code_point_xml_1_0_permits(allowed: str) -> None:
    assert escape_xml(f"a{allowed}b") == f"a{allowed}b"


def test_xml_is_a_declared_render_context() -> None:
    assert "xml" in get_args(RenderContext)
```

and extend that file's existing import block so it reads:

```python
from typing import get_args

from pigrocrm.core.templates.escaping import (
    RenderContext,
    escape_for,
    escape_markdown,
    escape_typst,
    escape_typst_string,
    escape_url,
    escape_xml,
)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_template_escaping.py -k xml -v`
Expected: FAIL with `ImportError: cannot import name 'escape_xml'`

- [ ] **Step 3: Implement**

In `packages/core/src/pigrocrm/core/templates/escaping.py`, change the `RenderContext` alias:

```python
RenderContext = Literal["markdown", "typst", "typst_string", "url", "verbatim", "xml"]
```

Add, immediately after `escape_url`:

```python
# XML 1.0 Char production (§2.2): #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
# | [#x10000-#x10FFFF]. Everything else -- the C0 controls other than tab/LF/CR, the
# surrogate range (reachable in a Python str, e.g. from a lone "\ud800"), and the two
# non-characters #xFFFE/#xFFFF -- has no representation at all: not as a literal byte,
# and not as a numeric character reference either, so no escaper could rescue it. A
# serialiser that emits one produces a file no conformant parser will open, which on a
# fiscal document means an outright rejection with no diagnostic worth reading.
_INVALID_XML_CHARS = re.compile(
    "[^\t\n\r -퟿-�\U00010000-\U0010ffff]"
)


def escape_xml(value: str) -> str:
    """For a value that lands as the text of an XML element.

    Returns `value` **unchanged**. That is the whole rule, and it is deliberate: this
    slice builds the FatturaPA document as an `lxml` element tree and serialises it
    once, so the serialiser is the single escaping pass and anything this function
    substituted would be escaped a second time on the way out -- `&` would reach the
    Agenzia delle Entrate as `&amp;amp;`. Acme's own literal-backslash defect
    (`normalizeSingleLine` ran `escapeTypstText` and then `escapeXml` over the same
    string) is that mistake in its other direction. The `xml` context therefore exists
    to say, explicitly and in the same module as the other four contexts, that the
    correct number of escaping passes for an XML target is one and it does not happen
    here.

    What it does do is refuse what no escaper can fix: a code point outside XML 1.0's
    `Char` production. `SafeStr` already stops a NUL byte at the schema boundary; this
    closes the rest of the class rather than that one case.
    """
    invalid = _INVALID_XML_CHARS.search(value)
    if invalid is not None:
        raise ValueError(
            "il testo contiene un carattere non rappresentabile in XML 1.0: "
            f"U+{ord(invalid.group(0)):04X}"
        )
    return value
```

and add the branch to `escape_for`, immediately before `case "verbatim":`:

```python
        case "xml":
            return escape_xml(value)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_template_escaping.py -v`
Expected: PASS, every existing case still green — the alias widened and no existing branch changed.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/templates/escaping.py packages/core/tests/test_template_escaping.py
git commit -m "feat(templates): an xml render context that refuses what no escaper can fix"
```

---

### Task 2: Money and rounding

**Files:**
- Create: `packages/core/src/pigrocrm/core/invoices/__init__.py` (empty)
- Create: `packages/core/src/pigrocrm/core/invoices/totals.py`
- Test: `packages/core/tests/test_invoice_totals.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MONEY_EXPONENT: Decimal` (`Decimal("0.01")`)
  - `round_money(value: Decimal) -> Decimal`
  - `format_amount_2(value: Decimal) -> str`, `format_amount_8(value: Decimal) -> str`, `format_rate(value: Decimal) -> str`
  - `@dataclass(frozen=True) ComputedLine` with fields `numero_linea: int`, `descrizione: str`, `quantita: Decimal`, `unita_misura: str | None`, `prezzo_unitario: Decimal`, `sconto_percentuale: Decimal | None`, `sconto_importo: Decimal | None`, `prezzo_totale: Decimal`, `aliquota_iva: Decimal`, `natura: str | None`, `riferimento_normativo: str | None`
  - `@dataclass(frozen=True) RiepilogoGroup` with `aliquota_iva: Decimal`, `natura: str | None`, `riferimento_normativo: str | None`, `imponibile: Decimal`, `imposta: Decimal`
  - `line_total(*, quantita: Decimal, prezzo_unitario: Decimal, sconto_percentuale: Decimal | None, sconto_importo: Decimal | None) -> Decimal`
  - `build_riepilogo(righe: Sequence[ComputedLine]) -> tuple[RiepilogoGroup, ...]`
  - `sum_totals(riepilogo: Sequence[RiepilogoGroup]) -> tuple[Decimal, Decimal, Decimal]` returning `(imponibile, imposta, totale)`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_invoice_totals.py`:

```python
"""The arithmetic of spec 6.1, proven where it is observable.

Under the forfettario every tax is zero, so rules 2 and 3 -- "a group's taxable base
is the sum of the already-rounded line totals" and "a group's tax is computed from
the group, not summed from the lines" -- cannot be distinguished from real data. They
are exactly the rules the SdI checks and rejects a file over, so they are pinned here
with rates the shipped product never uses.
"""

from decimal import Decimal

import pytest

from pigrocrm.core.invoices.totals import (
    ComputedLine,
    build_riepilogo,
    format_amount_2,
    format_amount_8,
    format_rate,
    line_total,
    round_money,
    sum_totals,
)


def _line(
    numero: int,
    prezzo_totale: str,
    aliquota: str,
    natura: str | None = None,
    riferimento: str | None = None,
) -> ComputedLine:
    return ComputedLine(
        numero_linea=numero,
        descrizione=f"riga {numero}",
        quantita=Decimal("1.000000"),
        unita_misura=None,
        prezzo_unitario=Decimal(prezzo_totale),
        sconto_percentuale=None,
        sconto_importo=None,
        prezzo_totale=Decimal(prezzo_totale),
        aliquota_iva=Decimal(aliquota),
        natura=natura,
        riferimento_normativo=riferimento,
    )


def test_a_half_cent_rounds_up_not_to_even() -> None:
    """ROUND_HALF_UP, not Decimal's ROUND_HALF_EVEN default: Italian fiscal practice
    and the SdI's own arithmetic round a half up. Banker's rounding would send
    0.125 to 0.12 and 0.135 to 0.14, i.e. disagree with the SdI on alternate cents."""
    assert round_money(Decimal("0.125")) == Decimal("0.13")
    assert round_money(Decimal("0.135")) == Decimal("0.14")
    assert round_money(Decimal("-0.125")) == Decimal("-0.13")


def test_line_total_is_quantity_times_price_rounded_to_the_cent() -> None:
    assert line_total(
        quantita=Decimal("3.000000"),
        prezzo_unitario=Decimal("33.333333"),
        sconto_percentuale=None,
        sconto_importo=None,
    ) == Decimal("100.00")


def test_line_total_applies_a_percentage_discount_then_a_fixed_one() -> None:
    assert line_total(
        quantita=Decimal("2.000000"),
        prezzo_unitario=Decimal("100.000000"),
        sconto_percentuale=Decimal("10.00"),
        sconto_importo=Decimal("5.00"),
    ) == Decimal("175.00")


def test_a_negative_line_is_allowed_because_a_discount_is_a_line() -> None:
    assert line_total(
        quantita=Decimal("1.000000"),
        prezzo_unitario=Decimal("-50.000000"),
        sconto_percentuale=None,
        sconto_importo=None,
    ) == Decimal("-50.00")


def test_a_group_base_is_the_sum_of_already_rounded_line_totals() -> None:
    """Spec 6.1 rule 2. Three lines of 0.005 each: the exact sum is 0.015, whose
    rounding is 0.02, but each printed line reads 0.01, so the SdI's own check
    (ImponibileImporto == sum of the group's PrezzoTotale) wants 0.03. Rounding the
    exact sum instead is a discarded file."""
    righe = [_line(1, "0.01", "22.00"), _line(2, "0.01", "22.00"), _line(3, "0.01", "22.00")]
    (group,) = build_riepilogo(righe)
    assert group.imponibile == Decimal("0.03")


def test_group_tax_is_computed_from_the_group_not_summed_from_the_lines() -> None:
    """Spec 6.1 rule 3, and the point where rules 2 and 3 genuinely disagree.
    Three lines of 3.33 at 22%: per line the tax rounds to 0.73 each, summing to
    2.19, while the group's 9.99 x 22% is 2.1978 -> 2.20. The SdI checks the group
    product, so 2.20 is the only acceptable answer."""
    righe = [_line(1, "3.33", "22.00"), _line(2, "3.33", "22.00"), _line(3, "3.33", "22.00")]
    (group,) = build_riepilogo(righe)
    assert group.imponibile == Decimal("9.99")
    assert group.imposta == Decimal("2.20")
    assert sum(round_money(Decimal("3.33") * Decimal("22") / 100) for _ in range(3)) == Decimal(
        "2.19"
    )


def test_two_rates_on_one_invoice_produce_one_group_each() -> None:
    """Spec 14.8, the synthetic RF01 case: 22% and 10% on the same invoice."""
    righe = [
        _line(1, "100.00", "22.00"),
        _line(2, "50.00", "10.00"),
        _line(3, "25.00", "22.00"),
    ]
    groups = build_riepilogo(righe)
    assert [(g.aliquota_iva, g.imponibile, g.imposta) for g in groups] == [
        (Decimal("10.00"), Decimal("50.00"), Decimal("5.00")),
        (Decimal("22.00"), Decimal("125.00"), Decimal("27.50")),
    ]
    imponibile, imposta, totale = sum_totals(groups)
    assert (imponibile, imposta, totale) == (
        Decimal("175.00"),
        Decimal("32.50"),
        Decimal("207.50"),
    )


def test_same_rate_different_natura_are_distinct_groups() -> None:
    """Spec 6.1 rule 5: the group key is (aliquota, natura), because the two carry
    different RiferimentoNormativo values and the SdI reads them per group."""
    righe = [
        _line(1, "100.00", "0.00", natura="N2.2", riferimento="art. 1 L. 190/2014"),
        _line(2, "40.00", "0.00", natura="N1", riferimento="art. 15 DPR 633/72"),
    ]
    groups = build_riepilogo(righe)
    assert [(g.natura, g.imponibile) for g in groups] == [
        ("N1", Decimal("40.00")),
        ("N2.2", Decimal("100.00")),
    ]


def test_the_forfettario_shape_is_all_zeroes_and_still_sums() -> None:
    righe = [_line(1, "1500.00", "0.00", natura="N2.2"), _line(2, "-100.00", "0.00", natura="N2.2")]
    groups = build_riepilogo(righe)
    imponibile, imposta, totale = sum_totals(groups)
    assert (imponibile, imposta, totale) == (
        Decimal("1400.00"),
        Decimal("0.00"),
        Decimal("1400.00"),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0", "0.00"), ("1400", "1400.00"), ("1400.5", "1400.50"), ("-100.005", "-100.01")],
)
def test_amount_2_always_carries_exactly_two_decimals(value: str, expected: str) -> None:
    """FPR12's Amount2DecimalType is `[\\-]?[0-9]{1,11}\\.[0-9]{2}`: a bare "1400" is
    schema-invalid, so formatting is not cosmetic here."""
    assert format_amount_2(Decimal(value)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", "3.000000"), ("33.333333", "33.333333"), ("-1.5", "-1.500000")],
)
def test_amount_8_carries_six_decimals_inside_the_schema_range(
    value: str, expected: str
) -> None:
    """Amount8DecimalType allows 2 to 8 decimals; the columns are Numeric(12, 6), so
    six is both exact for the stored value and inside the schema's range."""
    assert format_amount_8(Decimal(value)) == expected


@pytest.mark.parametrize(("value", "expected"), [("0", "0.00"), ("22", "22.00"), ("4.5", "4.50")])
def test_rate_always_carries_exactly_two_decimals(value: str, expected: str) -> None:
    assert format_rate(Decimal(value)) == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_totals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.invoices'`

- [ ] **Step 3: Implement**

Create `packages/core/src/pigrocrm/core/invoices/__init__.py` empty, and `packages/core/src/pigrocrm/core/invoices/totals.py`:

```python
"""The money arithmetic of spec 6.1, as pure functions over `Decimal`.

No `float` reaches this module and none leaves it. Acme applied a percentage to a
total it had re-read out of a formatted string (`parseAmount(values.TOTALE)`); here an
amount is only ever a `Decimal` computed from other `Decimal`s, and text is produced
at the very end by `format_amount_*` for the XML and the PDF, never parsed back.

Kept free of the database, the regime and the exporter on purpose: rules 2 and 3 below
disagree by cents, the disagreement is invisible under the forfettario the product
ships with, and the only way to pin them is a test with rates nobody uses -- which
needs no session, no container and no XML.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONEY_EXPONENT = Decimal("0.01")
FACTOR_EXPONENT = Decimal("0.000001")
RATE_EXPONENT = Decimal("0.01")
_HUNDRED = Decimal("100")


def round_money(value: Decimal) -> Decimal:
    """Two decimals, `ROUND_HALF_UP`.

    Not `Decimal`'s own `ROUND_HALF_EVEN` default: Italian fiscal practice, and the
    arithmetic the SdI's own checks perform, round a half away from zero. Banker's
    rounding disagrees on alternate cents, which is enough for a file to be discarded.
    """
    return value.quantize(MONEY_EXPONENT, rounding=ROUND_HALF_UP)


def format_amount_2(value: Decimal) -> str:
    """FPR12 `Amount2DecimalType`: `[\\-]?[0-9]{1,11}\\.[0-9]{2}` -- exactly two
    decimals, so a bare "1400" is schema-invalid and `str(Decimal("1400"))` cannot be
    used directly."""
    return f"{round_money(value):.2f}"


def format_amount_8(value: Decimal) -> str:
    """FPR12 `Amount8DecimalType`: two to eight decimals. Six, matching the
    `Numeric(12, 6)` columns exactly, so the printed value is the stored value."""
    return f"{value.quantize(FACTOR_EXPONENT, rounding=ROUND_HALF_UP):.6f}"


def format_rate(value: Decimal) -> str:
    """FPR12 `RateType`: `[0-9]{1,3}\\.[0-9]{2}`."""
    return f"{value.quantize(RATE_EXPONENT, rounding=ROUND_HALF_UP):.2f}"


@dataclass(frozen=True)
class ComputedLine:
    """One `DettaglioLinee`, with every derived value already decided.

    Built by `InvoiceService` from the caller's input plus the `RegimeStrategy`'s
    answer; this module never decides `aliquota_iva`, `natura` or
    `riferimento_normativo`, it only groups by them.
    """

    numero_linea: int
    descrizione: str
    quantita: Decimal
    unita_misura: str | None
    prezzo_unitario: Decimal
    sconto_percentuale: Decimal | None
    sconto_importo: Decimal | None
    prezzo_totale: Decimal
    aliquota_iva: Decimal
    natura: str | None
    riferimento_normativo: str | None


@dataclass(frozen=True)
class RiepilogoGroup:
    """One `DatiRiepilogo`. The key is `(aliquota_iva, natura)` -- spec 6.1 rule 5."""

    aliquota_iva: Decimal
    natura: str | None
    riferimento_normativo: str | None
    imponibile: Decimal
    imposta: Decimal


def line_total(
    *,
    quantita: Decimal,
    prezzo_unitario: Decimal,
    sconto_percentuale: Decimal | None,
    sconto_importo: Decimal | None,
) -> Decimal:
    """Spec 6.1 rule 1: `ROUND(quantita x prezzo_unitario - sconto, 2)`.

    The percentage is applied to the exact product and the fixed amount is subtracted
    after it, so the two discounts compose in a defined order instead of depending on
    which one the caller happened to fill in. Rounding happens once, at the end: a
    line's own intermediate product is never rounded, because rounding twice is how a
    total stops matching the sum of what is printed.

    A negative result is returned as-is. A discount is a line (spec 6.1 rule 6), so
    refusing one here would make the ordinary case unrepresentable; the check that a
    whole *invoice* must total more than zero belongs to emission, not to a line.
    """
    gross = quantita * prezzo_unitario
    if sconto_percentuale is not None:
        gross -= gross * sconto_percentuale / _HUNDRED
    if sconto_importo is not None:
        gross -= sconto_importo
    return round_money(gross)


def build_riepilogo(righe: Sequence[ComputedLine]) -> tuple[RiepilogoGroup, ...]:
    """One group per `(aliquota_iva, natura)`, ordered by that key so the output is
    deterministic and a re-export is byte-identical.

    Two rules that disagree, both from spec 6.1:

    * rule 2 -- `imponibile` is the sum of the group's **already-rounded**
      `prezzo_totale` values, not the rounding of the exact sum. The SdI checks
      `ImponibileImporto` against the sum of the group's printed `PrezzoTotale`, and
      rounding the exact sum can differ from that by a cent;
    * rule 3 -- `imposta` is `ROUND(imponibile x aliquota / 100, 2)` computed **from
      the group**, not the sum of per-line taxes. The SdI checks `Imposta` against
      that product, and the sum of rounded per-line taxes can differ from it by
      several cents.

    Both rules are unobservable under a regime where every rate is zero, which is why
    they are stated here rather than discovered on the first rejected file.
    """
    grouped: dict[tuple[Decimal, str | None], list[ComputedLine]] = {}
    for riga in righe:
        grouped.setdefault((riga.aliquota_iva, riga.natura), []).append(riga)

    groups: list[RiepilogoGroup] = []
    for (aliquota, natura), members in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        imponibile = sum((m.prezzo_totale for m in members), start=Decimal("0.00"))
        groups.append(
            RiepilogoGroup(
                aliquota_iva=aliquota,
                natura=natura,
                # Every member of a group shares a natura, and the regime derives the
                # normative reference from the natura, so the first member's value is
                # the group's value by construction.
                riferimento_normativo=members[0].riferimento_normativo,
                imponibile=round_money(imponibile),
                imposta=round_money(imponibile * aliquota / _HUNDRED),
            )
        )
    return tuple(groups)


def sum_totals(riepilogo: Sequence[RiepilogoGroup]) -> tuple[Decimal, Decimal, Decimal]:
    """`(imponibile, imposta, totale)`, where `totale = imponibile + imposta`.

    The stamp duty is **not** part of the total (spec 6.1 rule 4 and 7.2):
    `DatiBollo/BolloVirtuale` declares that the issuer has settled it virtually, and
    charging it back to the customer would need a line with `Natura N1` -- a feature
    with its own semantics, explicitly out of scope.
    """
    imponibile = round_money(sum((g.imponibile for g in riepilogo), start=Decimal("0.00")))
    imposta = round_money(sum((g.imposta for g in riepilogo), start=Decimal("0.00")))
    return imponibile, imposta, round_money(imponibile + imposta)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_totals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/ packages/core/tests/test_invoice_totals.py
git commit -m "feat(invoices): the rounding rules of spec 6.1 as pure Decimal maths"
```

---

### Task 3: The fiscal regime as a strategy

**Files:**
- Create: `packages/core/src/pigrocrm/core/fiscal/__init__.py` (empty)
- Create: `packages/core/src/pigrocrm/core/fiscal/schemas.py`
- Create: `packages/core/src/pigrocrm/core/fiscal/regime.py`
- Test: `packages/core/tests/test_fiscal_regime.py`

**Interfaces:**
- Consumes: `pigrocrm.core.errors.ValidationFailed`; `pigrocrm.core.validation.SafeStr`.
- Produces:
  - `fiscal/schemas.py`: `CODICE_REGIME_RE: re.Pattern[str]`, `DEFAULT_RIFERIMENTO_NORMATIVO: str`, `class FiscalSnapshot(BaseModel)` with `codice_regime: str`, `aliquota_iva_default: Decimal`, `natura_default: str | None`, `riferimento_normativo: str | None`, `applica_bollo: bool`, `soglia_bollo: Decimal`, `importo_bollo: Decimal`, `condizioni_pagamento: str`, `modalita_pagamento: str`, `giorni_scadenza: int`, `iban: str | None`
  - `fiscal/regime.py`: `class RegimeStrategy(Protocol)` with `codice: str`, `resolve_line_vat(self, requested: Decimal | None, profile: FiscalSnapshot) -> tuple[Decimal, str | None, str | None]`, `bollo(self, riepilogo: Sequence[RiepilogoGroup], profile: FiscalSnapshot) -> Decimal`; `FORFETTARIO: RegimeStrategy`; `ORDINARIO: RegimeStrategy`; `resolve_regime(codice_regime: str) -> RegimeStrategy`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_fiscal_regime.py`:

```python
"""A regime decides three things and nothing else (spec 7.2): the default rate on a
line, the Natura/RiferimentoNormativo pair, and whether the stamp duty applies.

`ORDINARIO` (RF01) ships with the product but is exercised only by tests and by
whoever changes regime: it exists so the rounding rules of spec 6.1 -- which the
forfettario reduces to zero -- are verifiable behaviour rather than documentation.
"""

from decimal import Decimal

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fiscal.regime import FORFETTARIO, ORDINARIO, resolve_regime
from pigrocrm.core.fiscal.schemas import DEFAULT_RIFERIMENTO_NORMATIVO, FiscalSnapshot
from pigrocrm.core.invoices.totals import RiepilogoGroup


def _profile(**overrides: object) -> FiscalSnapshot:
    base: dict[str, object] = {
        "codice_regime": "RF19",
        "aliquota_iva_default": Decimal("0.00"),
        "natura_default": "N2.2",
        "riferimento_normativo": DEFAULT_RIFERIMENTO_NORMATIVO,
        "applica_bollo": True,
        "soglia_bollo": Decimal("77.47"),
        "importo_bollo": Decimal("2.00"),
        "condizioni_pagamento": "TP02",
        "modalita_pagamento": "MP05",
        "giorni_scadenza": 30,
        "iban": "IT60X0542811101000000123456",
    }
    base.update(overrides)
    return FiscalSnapshot(**base)  # type: ignore[arg-type]


def _group(aliquota: str, imponibile: str, natura: str | None) -> RiepilogoGroup:
    return RiepilogoGroup(
        aliquota_iva=Decimal(aliquota),
        natura=natura,
        riferimento_normativo=None,
        imponibile=Decimal(imponibile),
        imposta=Decimal("0.00"),
    )


def test_resolve_regime_picks_the_strategy_from_the_code() -> None:
    assert resolve_regime("RF19") is FORFETTARIO
    assert resolve_regime("RF01") is ORDINARIO


def test_an_unknown_regime_code_names_the_field() -> None:
    with pytest.raises(ValidationFailed) as caught:
        resolve_regime("RF07")
    assert caught.value.details["entity"] == "fiscal_profile"
    assert caught.value.details["field"] == "codice_regime"


def test_a_code_that_is_not_a_regime_at_all_is_refused_by_fullmatch() -> None:
    """`.fullmatch`, never `.match` with `$`: "RF19\\n" is 5 characters and would
    reach a String(4) column as a raw DataError."""
    with pytest.raises(ValidationFailed):
        resolve_regime("RF19\n")


def test_forfettario_forces_zero_rate_with_the_natura_and_the_reference() -> None:
    aliquota, natura, riferimento = FORFETTARIO.resolve_line_vat(None, _profile())
    assert aliquota == Decimal("0.00")
    assert natura == "N2.2"
    assert riferimento == DEFAULT_RIFERIMENTO_NORMATIVO


def test_forfettario_accepts_an_explicit_zero_and_refuses_anything_else() -> None:
    """Two SdI checks applied as a pair: a zero rate without a Natura is rejected,
    and a Natura with a non-zero rate is rejected. Whoever does not know that
    discovers the second only after fixing the first."""
    assert FORFETTARIO.resolve_line_vat(Decimal("0.00"), _profile())[0] == Decimal("0.00")
    with pytest.raises(ValidationFailed) as caught:
        FORFETTARIO.resolve_line_vat(Decimal("22.00"), _profile())
    assert caught.value.details["field"] == "aliquota_iva"


def test_forfettario_applies_the_stamp_duty_only_above_the_threshold() -> None:
    """Spec 14.1's two boundary cases: 77.47 is not above the threshold, 77.48 is."""
    profile = _profile()
    assert FORFETTARIO.bollo([_group("0.00", "77.47", "N2.2")], profile) == Decimal("0.00")
    assert FORFETTARIO.bollo([_group("0.00", "77.48", "N2.2")], profile) == Decimal("2.00")


def test_forfettario_honours_applica_bollo_false() -> None:
    profile = _profile(applica_bollo=False)
    assert FORFETTARIO.bollo([_group("0.00", "5000.00", "N2.2")], profile) == Decimal("0.00")


def test_the_stamp_duty_looks_only_at_the_untaxed_base() -> None:
    """`DatiBollo` is due on the amount not subject to VAT. A taxed group must not
    push a mostly-taxed invoice over the threshold."""
    profile = _profile()
    groups = [_group("22.00", "5000.00", None), _group("0.00", "10.00", "N2.2")]
    assert FORFETTARIO.bollo(groups, profile) == Decimal("0.00")


def test_ordinario_uses_the_requested_rate_with_no_natura() -> None:
    profile = _profile(codice_regime="RF01", aliquota_iva_default=Decimal("22.00"), natura_default=None, riferimento_normativo=None)
    assert ORDINARIO.resolve_line_vat(Decimal("10.00"), profile) == (
        Decimal("10.00"),
        None,
        None,
    )
    assert ORDINARIO.resolve_line_vat(None, profile) == (Decimal("22.00"), None, None)


def test_ordinario_refuses_a_zero_rate_because_it_has_no_natura_to_pair_with_it() -> None:
    profile = _profile(codice_regime="RF01", aliquota_iva_default=Decimal("22.00"), natura_default=None, riferimento_normativo=None)
    with pytest.raises(ValidationFailed) as caught:
        ORDINARIO.resolve_line_vat(Decimal("0.00"), profile)
    assert caught.value.details["field"] == "aliquota_iva"


def test_ordinario_never_charges_the_stamp_duty() -> None:
    profile = _profile(codice_regime="RF01", natura_default=None)
    assert ORDINARIO.bollo([_group("22.00", "9999.00", None)], profile) == Decimal("0.00")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_fiscal_regime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.fiscal'`

- [ ] **Step 3: Implement the snapshot shape**

Create `packages/core/src/pigrocrm/core/fiscal/__init__.py` empty, and `packages/core/src/pigrocrm/core/fiscal/schemas.py`:

```python
"""The fiscal parameters, as a value object and as the API's Create/Read pair.

`FiscalSnapshot` is what gets frozen onto an issued invoice and what the exporter and
the PDF read. It is a plain Pydantic model with no `id` and no timestamps precisely so
that it can be serialised into `invoices.snapshot` and read back three years later
without the row it came from still existing in its original shape.
"""

import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.validation import SafeStr

# `RF01`..`RF19`, the codes FPR12's own `RegimeFiscaleType` enumerates. `.fullmatch`
# is what the callers use, never `.match` with `$`: "RF19\n" is five characters and
# would reach the String(4) column as a raw, session-poisoning DataError.
CODICE_REGIME_RE = re.compile(r"RF(0[1-9]|1[0-9])")

CODICE_REGIME_MAX_LENGTH = 4
NATURA_MAX_LENGTH = 4
CONDIZIONI_PAGAMENTO_MAX_LENGTH = 4
MODALITA_PAGAMENTO_MAX_LENGTH = 4
IBAN_MAX_LENGTH = 34
MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
RATE_MAX_DIGITS = 5
RATE_DECIMAL_PLACES = 2
GIORNI_SCADENZA_MIN = 0
GIORNI_SCADENZA_MAX = 365

# Acme shipped `RiferimentoNormativo` as "N2.2 (non soggette - altri casi)", which is
# the *description of the code*, not a normative reference. This is the real one for
# the forfettario, and it is a default rather than a constant because the article
# numbers have changed before.
DEFAULT_RIFERIMENTO_NORMATIVO = (
    "Operazione non soggetta a IVA ai sensi dell'art. 1, commi 54-89, "
    "L. 190/2014 - regime forfettario"
)

# Values of law, not preferences: 77.47 EUR is the threshold above which the stamp
# duty is due and 2.00 EUR is its amount. Configurable because the law has already
# changed them once.
DEFAULT_SOGLIA_BOLLO = Decimal("77.47")
DEFAULT_IMPORTO_BOLLO = Decimal("2.00")


class FiscalSnapshot(BaseModel):
    """The parameters as they were when an invoice was issued.

    Frozen, so nothing downstream of `InvoiceService.issue` can mutate a value the
    document was built from; `extra="forbid"` so a stored snapshot written by a later
    version of this model is a loud failure rather than a silently ignored field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    codice_regime: str = Field(max_length=CODICE_REGIME_MAX_LENGTH)
    aliquota_iva_default: Decimal = Field(
        max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES
    )
    natura_default: str | None = Field(default=None, max_length=NATURA_MAX_LENGTH)
    riferimento_normativo: str | None = None
    applica_bollo: bool
    soglia_bollo: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    importo_bollo: Decimal = Field(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    condizioni_pagamento: str = Field(max_length=CONDIZIONI_PAGAMENTO_MAX_LENGTH)
    modalita_pagamento: str = Field(max_length=MODALITA_PAGAMENTO_MAX_LENGTH)
    giorni_scadenza: int = Field(ge=GIORNI_SCADENZA_MIN, le=GIORNI_SCADENZA_MAX)
    iban: str | None = Field(default=None, max_length=IBAN_MAX_LENGTH)


__all__ = [
    "CODICE_REGIME_RE",
    "DEFAULT_IMPORTO_BOLLO",
    "DEFAULT_RIFERIMENTO_NORMATIVO",
    "DEFAULT_SOGLIA_BOLLO",
    "FiscalSnapshot",
    "SafeStr",
]
```

Delete the `SafeStr` re-export from `__all__` and its import if `ruff` flags it as unused at this point — it is used by `FiscalProfileUpsert`, which Task 7 adds to this same file. Keep the import and the `__all__` entry so Task 7 does not have to re-add them.

- [ ] **Step 4: Implement the strategies**

`packages/core/src/pigrocrm/core/fiscal/regime.py`:

```python
"""A regime decides three things and nothing else: the rate a line defaults to, the
`Natura`/`RiferimentoNormativo` pair, and whether the stamp duty applies (spec 7.2).

Acme hardcoded all three in the generator, which is why "what regime was this
invoice in" had no answer other than reading the source at the time. Here they come
from `fiscal_profile` through one of these objects, so a different regime is a second
object -- no new column, no migration -- and the rounding rules of `totals.py`, already
written, simply start producing non-zero values.

Deliberately out of scope and named rather than half-designed: withholding tax,
social-security fund, split payment, reverse charge, deferred or cash-basis VAT
liability. Each is a distinct XML block the forfettario never exercises.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fiscal.schemas import (
    CODICE_REGIME_RE,
    DEFAULT_RIFERIMENTO_NORMATIVO,
    FiscalSnapshot,
)
from pigrocrm.core.invoices.totals import RiepilogoGroup, round_money

ENTITY = "fiscal_profile"
ZERO = Decimal("0.00")


@runtime_checkable
class RegimeStrategy(Protocol):
    codice: str

    def resolve_line_vat(
        self, requested: Decimal | None, profile: FiscalSnapshot
    ) -> tuple[Decimal, str | None, str | None]:
        """`(aliquota_iva, natura, riferimento_normativo)` for one line.

        The three are returned together because the SdI validates them together: a
        zero rate without a `Natura` is rejected, and a `Natura` alongside a non-zero
        rate is rejected too. Returning them separately would let a caller pair them
        wrongly, and the table constraint `(aliquota_iva = 0) = (natura IS NOT NULL)`
        would then be the first thing to notice.
        """
        ...

    def bollo(self, riepilogo: Sequence[RiepilogoGroup], profile: FiscalSnapshot) -> Decimal:
        """The virtual stamp duty for the whole invoice, or `0.00`.

        Reads the summary groups rather than a single total because the duty is owed on
        the portion **not subject to VAT**: a large taxed amount must not push a
        mostly-taxed invoice over the threshold.
        """
        ...


class _Forfettario:
    """`RF19`. No VAT, `Natura N2.2`, and the normative declaration on every line and
    every summary group."""

    codice = "RF19"

    def resolve_line_vat(
        self, requested: Decimal | None, profile: FiscalSnapshot
    ) -> tuple[Decimal, str | None, str | None]:
        if requested is not None and requested != ZERO:
            raise ValidationFailed(
                "invoice_line",
                "aliquota_iva",
                f"il regime {self.codice} non applica IVA, quindi l'aliquota deve essere zero",
                expected="0.00",
            )
        natura = profile.natura_default or "N2.2"
        riferimento = profile.riferimento_normativo or DEFAULT_RIFERIMENTO_NORMATIVO
        return ZERO, natura, riferimento

    def bollo(self, riepilogo: Sequence[RiepilogoGroup], profile: FiscalSnapshot) -> Decimal:
        if not profile.applica_bollo:
            return ZERO
        untaxed = sum(
            (group.imponibile for group in riepilogo if group.aliquota_iva == ZERO),
            start=ZERO,
        )
        if round_money(untaxed) > profile.soglia_bollo:
            return round_money(profile.importo_bollo)
        return ZERO


class _Ordinario:
    """`RF01`. Present so the arithmetic of spec 6.1 is observable.

    The product ships the forfettario; this strategy is what a `test` fixture selects
    to put a 22% and a 10% group on the same invoice and watch `build_riepilogo` and
    `sum_totals` produce values that are not all zero. It is a real strategy, not a
    mock: switching `fiscal_profile.codice_regime` to `RF01` selects it in production
    too, and everything it needs already exists.
    """

    codice = "RF01"

    def resolve_line_vat(
        self, requested: Decimal | None, profile: FiscalSnapshot
    ) -> tuple[Decimal, str | None, str | None]:
        aliquota = requested if requested is not None else profile.aliquota_iva_default
        if aliquota == ZERO:
            # The table constraint requires a `natura` whenever the rate is zero, and
            # an ordinary regime has none to offer: refusing here names the field,
            # instead of letting the insert fail on a CHECK whose message names a
            # constraint.
            raise ValidationFailed(
                "invoice_line",
                "aliquota_iva",
                f"il regime {self.codice} non ha una natura da abbinare a un'aliquota zero",
                expected="un'aliquota maggiore di zero",
            )
        return aliquota, None, None

    def bollo(self, riepilogo: Sequence[RiepilogoGroup], profile: FiscalSnapshot) -> Decimal:
        # An ordinary regime taxes its operations, so there is no untaxed base for the
        # duty to be owed on. Returning zero unconditionally is the honest answer, not
        # a placeholder: an `RF01` invoice with an exempt line would need that line's
        # own `Natura`, which this strategy refuses to invent (see resolve_line_vat).
        return ZERO


FORFETTARIO: RegimeStrategy = _Forfettario()
ORDINARIO: RegimeStrategy = _Ordinario()

_BY_CODE: dict[str, RegimeStrategy] = {
    FORFETTARIO.codice: FORFETTARIO,
    ORDINARIO.codice: ORDINARIO,
}


def resolve_regime(codice_regime: str) -> RegimeStrategy:
    """The strategy for a stored `codice_regime`, or `ValidationFailed` naming it.

    Two checks, not one: the value must be a syntactically valid `RF01`-`RF19` code
    (`.fullmatch`, so a trailing newline is refused rather than accepted and passed
    on), and a strategy must exist for it. A code such as `RF07` is real FPR12 and
    still has no implementation here, and saying so is more useful than resolving it
    to the forfettario and silently issuing an invoice under the wrong regime.
    """
    if not CODICE_REGIME_RE.fullmatch(codice_regime):
        raise ValidationFailed(
            ENTITY,
            "codice_regime",
            f"codice regime non valido: {codice_regime!r}",
            expected="un codice da RF01 a RF19",
        )
    strategy = _BY_CODE.get(codice_regime)
    if strategy is None:
        raise ValidationFailed(
            ENTITY,
            "codice_regime",
            f"il regime {codice_regime} non e' implementato in questa versione",
            expected=f"uno tra: {', '.join(sorted(_BY_CODE))}",
        )
    return strategy


__all__ = ["FORFETTARIO", "ORDINARIO", "RegimeStrategy", "resolve_regime"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_fiscal_regime.py packages/core/tests/test_module_imports.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/fiscal/ packages/core/tests/test_fiscal_regime.py
git commit -m "feat(fiscal): RegimeStrategy decides rate, natura and stamp duty from data"
```

---

### Task 4: Invoice schemas, the snapshot, and `entity_type = "invoice"`

**Files:**
- Create: `packages/core/src/pigrocrm/core/invoices/schemas.py`
- Modify: `packages/core/src/pigrocrm/core/fields/schemas.py:17`
- Modify: `packages/core/src/pigrocrm/core/schema_registry.py`
- Modify: `packages/core/src/pigrocrm/core/documents/schemas.py`
- Modify: `apps/web/src/lib/schema.ts`
- Test: `packages/core/tests/test_invoice_schemas.py`, `packages/core/tests/test_schema_registry.py` (append)

**Interfaces:**
- Consumes: `pigrocrm.core.fiscal.schemas.FiscalSnapshot`; `pigrocrm.core.validation.SafeStr`.
- Produces, from `invoices/schemas.py`:
  - `InvoiceTipo = Literal["fattura", "proforma"]`
  - `InvoiceStato = Literal["bozza", "emessa", "annullata", "confermata", "consumata"]`
  - `StatoPagamento = Literal["da_incassare", "incassato"]`
  - `ArtifactKind = Literal["pdf", "xml"]`
  - `ALLOWED_STATI: dict[str, frozenset[str]]` keyed by `tipo`, and `STATO_TRANSITIONS: dict[str, frozenset[str]]`
  - `SNAPSHOT_VERSIONE: int` (`1`), `MAX_LINES: int` (`200`), `TIPO_DOCUMENTO: str` (`"TD01"`), `DIVISA: str` (`"EUR"`)
  - `class PartySnapshot(BaseModel)`, `class InvoiceSnapshot(BaseModel)`
  - `class InvoiceLineIn(BaseModel)`, `class InvoiceLineRead(BaseModel)`
  - `class InvoiceCreate(BaseModel)`, `class InvoiceUpdate(BaseModel)`, `class InvoiceRead(BaseModel)`
  - `class InvoiceIssue(BaseModel)`, `class InvoiceAnnul(BaseModel)`, `class InvoiceTransmitted(BaseModel)`, `class PaymentState(BaseModel)`
  - `class InvoiceListQuery(BaseModel)`, `class InvoicePage(BaseModel)`, `class InvoiceArtifact(BaseModel)`, `class InvoiceForExport(BaseModel)`
- Also produces: `EntityType` includes `"invoice"`; `ENTITY_TYPES` and `CREATE_MODELS` include it; `native_fields("invoice")` returns the derived Create fields **plus** `EXTRA_NATIVE_FIELDS["invoice"]`; `DocumentTipo` includes `"fattura"`, `"fattura_xml"`, `"proforma"`; `ALLOWED_CONTENT_TYPES` includes `"application/xml": ".xml"`.

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_invoice_schemas.py`:

```python
"""Shapes only -- no session, no service. What is pinned here is the set of things
that reach Postgres if a schema forgets them: a width, a scale, a NUL byte, a bound.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pigrocrm.core.documents.schemas import ALLOWED_CONTENT_TYPES, DocumentTipo
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.invoices.schemas import (
    ALLOWED_STATI,
    DESCRIZIONE_MAX_LENGTH,
    MAX_LINES,
    SNAPSHOT_VERSIONE,
    InvoiceCreate,
    InvoiceLineIn,
    InvoiceListQuery,
    InvoiceSnapshot,
    InvoiceUpdate,
    PartySnapshot,
)
from pigrocrm.core.schema_registry import CREATE_MODELS, ENTITY_TYPES, native_fields
from typing import get_args


def test_invoice_is_a_declared_entity_type_in_all_three_python_places() -> None:
    assert "invoice" in get_args(EntityType)
    assert "invoice" in ENTITY_TYPES
    assert CREATE_MODELS["invoice"] is InvoiceCreate


def test_native_fields_for_an_invoice_covers_the_derived_fiscal_columns() -> None:
    """`native_fields` derives from the Create schema, and an invoice's most
    collision-prone names -- `totale`, `imponibile`, `numero` -- are derived columns
    that no Create schema declares. A custom field labelled "Totale" slugifies to
    `totale`; A13 is still open, so nothing consults this list yet, but the list it
    will consult has to be right."""
    names = native_fields("invoice")
    assert {"customer_id", "tipo", "causale", "righe"} <= set(names)
    assert {"anno", "numero", "imponibile", "imposta", "bollo", "totale", "stato"} <= set(names)
    assert "custom_fields" not in names


def test_native_fields_for_the_older_entities_is_unchanged() -> None:
    """EXTRA_NATIVE_FIELDS is empty for them, so the derivation is still the whole
    answer and no existing behaviour moved."""
    assert native_fields("customer") == [
        name for name in CREATE_MODELS["customer"].model_fields if name != "custom_fields"
    ]


def test_documents_learns_the_three_invoice_artefact_types() -> None:
    assert {"fattura", "fattura_xml", "proforma"} <= set(get_args(DocumentTipo))
    assert ALLOWED_CONTENT_TYPES["application/xml"] == ".xml"


def test_the_state_machines_are_declared_per_tipo() -> None:
    """Two state machines in one column would be ambiguous, so the legal pairs are
    data here and a table constraint in the database."""
    assert ALLOWED_STATI == {
        "fattura": frozenset({"bozza", "emessa", "annullata"}),
        "proforma": frozenset({"bozza", "confermata", "consumata"}),
    }


def test_a_line_rejects_a_nul_byte_in_its_description() -> None:
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="Consulenza\x00", prezzo_unitario=Decimal("100.00"))


def test_a_line_description_is_bounded_to_the_column_width() -> None:
    with pytest.raises(ValidationError):
        InvoiceLineIn(
            descrizione="x" * (DESCRIZIONE_MAX_LENGTH + 1), prezzo_unitario=Decimal("100.00")
        )


def test_a_unit_price_keeps_six_decimals_and_refuses_a_seventh() -> None:
    """Numeric(12, 6): six decimals is what makes 33,3333 EUR/h expressible, and a
    seventh would be silently rounded by Postgres while the response still reported
    the original."""
    assert InvoiceLineIn(
        descrizione="Consulenza", prezzo_unitario=Decimal("33.333333")
    ).prezzo_unitario == Decimal("33.333333")
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("33.3333331"))


def test_a_unit_price_beyond_twelve_digits_is_refused_before_postgres_sees_it() -> None:
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("1234567.000000"))


def test_a_line_never_carries_its_own_natura() -> None:
    """`natura` and `riferimento_normativo` are the regime's answer, not the caller's:
    accepting them would make the table constraint
    `(aliquota_iva = 0) = (natura IS NOT NULL)` reachable from a request body."""
    assert "natura" not in InvoiceLineIn.model_fields
    assert "riferimento_normativo" not in InvoiceLineIn.model_fields
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="x", prezzo_unitario=Decimal("1.00"), natura="N2.2")


def test_an_invoice_cannot_be_created_with_more_lines_than_the_bound() -> None:
    line = {"descrizione": "x", "prezzo_unitario": "1.00"}
    with pytest.raises(ValidationError):
        InvoiceCreate(customer_id=uuid4(), righe=[line] * (MAX_LINES + 1))


def test_update_exposes_only_text_columns_and_custom_fields() -> None:
    """A14 is sidestepped rather than reproduced: every native column on this schema
    is text-shaped, so `""` is a real "clear it" spelling. No typed column -- numeric,
    date or literal -- appears here, which is what removes the A14 shape from this
    surface instead of hitting it again. `causale` is editable but only while the
    invoice is a draft, which the service enforces with `ImmutableField`."""
    assert set(InvoiceUpdate.model_fields) == {"causale", "note_interne", "custom_fields"}


def test_the_list_query_limit_is_bounded_in_the_schema_not_only_the_router() -> None:
    assert InvoiceListQuery().limit == 50
    with pytest.raises(ValidationError):
        InvoiceListQuery(limit=201)


def test_a_snapshot_round_trips_through_json_with_its_version() -> None:
    party = PartySnapshot(
        ragione_sociale="Rossi & C.",
        partita_iva="12345678901",
        codice_fiscale=None,
        codice_sdi="ABCDEFG",
        pec=None,
        indirizzo="Via Roma 1",
        cap="20100",
        comune="Milano",
        provincia="MI",
        nazione="IT",
        email=None,
        telefono=None,
        sito_web=None,
    )
    snapshot = InvoiceSnapshot(
        versione=SNAPSHOT_VERSIONE,
        emittente=party,
        cliente=party,
        fiscale={
            "codice_regime": "RF19",
            "aliquota_iva_default": Decimal("0.00"),
            "natura_default": "N2.2",
            "riferimento_normativo": "art. 1",
            "applica_bollo": True,
            "soglia_bollo": Decimal("77.47"),
            "importo_bollo": Decimal("2.00"),
            "condizioni_pagamento": "TP02",
            "modalita_pagamento": "MP05",
            "giorni_scadenza": 30,
            "iban": None,
        },
    )
    payload = snapshot.model_dump(mode="json")
    assert payload["versione"] == 1
    restored = InvoiceSnapshot.model_validate(payload)
    assert restored == snapshot


def test_an_unversioned_snapshot_payload_is_refused() -> None:
    """A JSON blob written today is read by code three years from now; a payload with
    no version is interpreted by guessing. That is what the column costs and what it
    buys."""
    with pytest.raises(ValidationError):
        InvoiceSnapshot.model_validate({"emittente": {}, "cliente": {}, "fiscale": {}})


def test_an_issue_request_may_carry_a_date_and_nothing_else() -> None:
    from pigrocrm.core.invoices.schemas import InvoiceIssue

    assert set(InvoiceIssue.model_fields) == {"data_emissione"}
    assert InvoiceIssue(data_emissione=date(2026, 8, 20)).data_emissione == date(2026, 8, 20)
    assert InvoiceIssue().data_emissione is None
```

Append to `packages/core/tests/test_schema_registry.py`:

```python
def test_describing_an_invoice_is_a_supported_entity_type() -> None:
    from pigrocrm.core.schema_registry import ENTITY_TYPES

    assert "invoice" in ENTITY_TYPES
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.invoices.schemas'`

- [ ] **Step 3: Implement the invoice schemas**

`packages/core/src/pigrocrm/core/invoices/schemas.py`:

```python
"""Every Pydantic shape the invoice domain exposes.

Widths and scales mirror `invoices/models.py` exactly. That is not defensive
duplication: without it an over-long string reaches Postgres as `DataError` and a
value beyond a `Numeric`'s capacity as `NumericValueOutOfRange`, neither of which is
an `IntegrityError`, so no handler catches either and the caller's session is left
poisoned. This project has paid for that class of defect seven times.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.fiscal.schemas import FiscalSnapshot
from pigrocrm.core.validation import SafeStr

InvoiceTipo = Literal["fattura", "proforma"]
InvoiceStato = Literal["bozza", "emessa", "annullata", "confermata", "consumata"]
StatoPagamento = Literal["da_incassare", "incassato"]
ArtifactKind = Literal["pdf", "xml"]

# Two state machines share one column, so the legal pairs are declared once here and
# enforced as a table `CHECK` in the migration. A convention in the service would
# leave `stato = 'consumata'` reachable on a `fattura` from any other write path.
ALLOWED_STATI: dict[str, frozenset[str]] = {
    "fattura": frozenset({"bozza", "emessa", "annullata"}),
    "proforma": frozenset({"bozza", "confermata", "consumata"}),
}

# Transitions, as a table rather than a chain of `if`s -- the same shape
# `documents/service.py::OFFER_TRANSITIONS` already uses, and read by the UI to decide
# which buttons exist. `emessa`, `annullata` and `consumata` are terminal.
STATO_TRANSITIONS: dict[str, frozenset[str]] = {
    "bozza": frozenset({"emessa", "confermata"}),
    "confermata": frozenset({"consumata", "bozza"}),
    "emessa": frozenset({"annullata"}),
    "annullata": frozenset(),
    "consumata": frozenset(),
}

SNAPSHOT_VERSIONE = 1
TIPO_DOCUMENTO = "TD01"
DIVISA = "EUR"

# FPR12 widths, which the columns mirror: Descrizione is String1000Type, Causale is
# String200Type, UnitaMisura is String10Type, Natura is 2-4 characters.
DESCRIZIONE_MAX_LENGTH = 1000
CAUSALE_MAX_LENGTH = 200
UNITA_MISURA_MAX_LENGTH = 10
NATURA_MAX_LENGTH = 4
RIFERIMENTO_MAX_LENGTH = 30
MOTIVO_ANNULLAMENTO_MAX_LENGTH = 500
TIPO_DOCUMENTO_MAX_LENGTH = 4
DIVISA_MAX_LENGTH = 3
HASH_LENGTH = 64

MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
FACTOR_MAX_DIGITS = 12
FACTOR_DECIMAL_PLACES = 6
RATE_MAX_DIGITS = 5
RATE_DECIMAL_PLACES = 2

# A `numero_linea` is contiguous from 1, so this doubles as the ceiling on both the
# line count and the line number. 200 lines is far more document than anyone posts,
# and the bound is what stops an unbounded list from becoming an unbounded number of
# INSERTs in one transaction.
MAX_LINES = 200
# Spec 8.4: the SdI file name embeds `anno * 10000 + numero`, so a five-digit numero
# would collide with the next year's. Emission is refused past this rather than a name
# quietly becoming ambiguous.
MAX_NUMERO = 9999
ANNO_MIN = 2000
ANNO_MAX = 2999


class PartySnapshot(BaseModel):
    """One party's identity and address as it was at emission.

    Frozen, and `extra="forbid"`: a stored snapshot that carries a field this model
    does not know about must fail loudly rather than be read with that field silently
    dropped, because the thing being reconstructed is a fiscal document.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ragione_sociale: str
    partita_iva: str | None
    codice_fiscale: str | None
    codice_sdi: str | None
    pec: str | None
    indirizzo: str
    cap: str
    comune: str
    provincia: str
    nazione: str
    email: str | None
    telefono: str | None
    sito_web: str | None


class InvoiceSnapshot(BaseModel):
    """What makes a re-render faithful: a customer who moves does not rewrite an
    invoice from two years ago (spec 8.3).

    `versione` is required and has no default on purpose. A default would let a
    payload with no version validate as version 1, which is exactly the guess the
    column exists to prevent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    versione: int
    emittente: PartySnapshot
    cliente: PartySnapshot
    fiscale: FiscalSnapshot


class InvoiceLineIn(BaseModel):
    """One line as a caller supplies it.

    `natura` and `riferimento_normativo` are deliberately absent: they are the
    `RegimeStrategy`'s answer, and accepting them here would put the table constraint
    `(aliquota_iva = 0) = (natura IS NOT NULL)` within reach of a request body.
    `aliquota_iva` is optional and means "use the regime's default"; under the
    forfettario the regime refuses anything but zero anyway.
    """

    model_config = ConfigDict(extra="forbid")

    descrizione: SafeStr = Field(max_length=DESCRIZIONE_MAX_LENGTH)
    quantita: Decimal = Field(
        default=Decimal("1.000000"),
        max_digits=FACTOR_MAX_DIGITS,
        decimal_places=FACTOR_DECIMAL_PLACES,
    )
    unita_misura: SafeStr | None = Field(default=None, max_length=UNITA_MISURA_MAX_LENGTH)
    prezzo_unitario: Decimal = Field(
        max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_DECIMAL_PLACES
    )
    sconto_percentuale: Decimal | None = Field(
        default=None, max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES
    )
    sconto_importo: Decimal | None = Field(
        default=None, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    aliquota_iva: Decimal | None = Field(
        default=None, max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES
    )


class InvoiceLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    numero_linea: int
    descrizione: str
    quantita: Decimal
    unita_misura: str | None
    prezzo_unitario: Decimal
    sconto_percentuale: Decimal | None
    sconto_importo: Decimal | None
    prezzo_totale: Decimal
    aliquota_iva: Decimal
    natura: str | None
    riferimento_normativo: str | None


class InvoiceCreate(BaseModel):
    """A draft invoice or a proforma. Neither has a number: a number is assigned only
    at emission, which is why "a failed creation burns a number" is impossible by
    construction rather than by care."""

    customer_id: UUID
    deal_id: UUID | None = None
    tipo: InvoiceTipo = "fattura"
    causale: SafeStr | None = Field(default=None, max_length=CAUSALE_MAX_LENGTH)
    note_interne: SafeStr | None = None
    righe: list[InvoiceLineIn] = Field(default_factory=list, max_length=MAX_LINES)
    custom_fields: dict[str, Any] = {}


class InvoiceUpdate(BaseModel):
    """Only what stays mutable after emission (spec 4).

    Everything typed and clearable is absent, which removes the A14 shape from this
    surface instead of reproducing it: lines are replaced in bulk, `stato_pagamento`
    and `data_incasso` go through `set_payment_state`, and `stato` goes through
    `issue`/`annul`. Both native fields here are text-shaped, so `""` is a real
    "clear it" spelling for each.

    `causale` is on this schema because a draft has to be correctable before it is
    issued, and it is frozen afterwards by `InvoiceService.update`, which raises
    `ImmutableField` -- not by leaving it off the schema, which would have made a
    draft's own subject line unfixable.
    """

    model_config = ConfigDict(extra="forbid")

    causale: SafeStr | None = Field(default=None, max_length=CAUSALE_MAX_LENGTH)
    note_interne: SafeStr | None = None
    custom_fields: dict[str, Any] | None = None


class InvoiceIssue(BaseModel):
    """`data_emissione` may be back-dated within the current year (spec 6.2); omitted
    means today in the issuer's own calendar, never a UTC projection of an instant."""

    model_config = ConfigDict(extra="forbid")

    data_emissione: date | None = None


class InvoiceAnnul(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: SafeStr = Field(min_length=1, max_length=MOTIVO_ANNULLAMENTO_MAX_LENGTH)


class InvoiceTransmitted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: date


class PaymentState(BaseModel):
    """`stato_pagamento` and `data_incasso` move together: "collected with no date" and
    "a date but not collected" are both nonsense, and a single method taking both
    required values has no spelling for either."""

    model_config = ConfigDict(extra="forbid")

    stato_pagamento: StatoPagamento
    data_incasso: date | None = None


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    deal_id: UUID | None
    tipo: str
    stato: str
    anno: int | None
    numero: int | None
    riferimento: str | None
    data_emissione: date | None
    data_scadenza: date | None
    tipo_documento: str
    divisa: str
    imponibile: Decimal
    imposta: Decimal
    bollo: Decimal
    totale: Decimal
    causale: str | None
    stato_pagamento: str
    data_incasso: date | None
    trasmessa_esternamente_il: date | None
    xml_hash_sha256: str | None
    pdf_document_id: UUID | None
    xml_document_id: UUID | None
    origine_proforma_id: UUID | None
    annullata_il: date | None
    motivo_annullamento: str | None
    note_interne: str | None
    snapshot_versione: int | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class InvoiceListQuery(BaseModel):
    customer_id: UUID | None = None
    deal_id: UUID | None = None
    tipo: InvoiceTipo | None = None
    stato: InvoiceStato | None = None
    anno: int | None = Field(default=None, ge=ANNO_MIN, le=ANNO_MAX)
    stato_pagamento: StatoPagamento | None = None
    # Bounded here, not only on the router: an MCP tool builds this object directly,
    # with no `Query(...)` bound sitting between it and this schema.
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class InvoicePage(BaseModel):
    items: list[InvoiceRead]
    next_cursor: UUID | None


class InvoiceArtifact(BaseModel):
    """What `export_xml`/`render_pdf` report. Never the bytes: an MCP tool returns an
    identifier and the bytes are fetched over REST (slice 2 §7)."""

    kind: ArtifactKind
    document_id: UUID
    version_numero: int
    filename: str
    content_type: str
    hash_sha256: str = Field(min_length=HASH_LENGTH, max_length=HASH_LENGTH)


class InvoiceForExport(BaseModel):
    """Everything `FatturaPAExporter` reads, and nothing else.

    A distinct type rather than `InvoiceRead` plus its lines, because the exporter must
    be provably unable to read `emitter_profile`, `customers` or `fiscal_profile`: what
    it can see is what was frozen. That is what makes a re-export reproducible and
    what lets the whole generator be tested with no database at all.
    """

    model_config = ConfigDict(frozen=True)

    anno: int = Field(ge=ANNO_MIN, le=ANNO_MAX)
    numero: int = Field(ge=1, le=MAX_NUMERO)
    data_emissione: date
    data_scadenza: date | None
    tipo_documento: str = Field(max_length=TIPO_DOCUMENTO_MAX_LENGTH)
    divisa: str = Field(max_length=DIVISA_MAX_LENGTH)
    imponibile: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    imposta: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    bollo: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    totale: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    causale: str | None = Field(default=None, max_length=CAUSALE_MAX_LENGTH)
    snapshot: InvoiceSnapshot
    righe: tuple[InvoiceLineRead, ...]
```

- [ ] **Step 4: Widen `EntityType` and the registry**

In `packages/core/src/pigrocrm/core/fields/schemas.py`, replace line 17:

```python
EntityType = Literal["customer", "person", "deal", "document", "invoice"]
```

In `packages/core/src/pigrocrm/core/schema_registry.py`, add the import, widen the two constants, and add the extra-natives mapping:

```python
from pigrocrm.core.invoices.schemas import InvoiceCreate

ENTITY_TYPES: tuple[EntityType, ...] = ("customer", "person", "deal", "document", "invoice")

CREATE_MODELS: dict[str, type[BaseModel]] = {
    "customer": CustomerCreate,
    "person": PersonCreate,
    "deal": DealCreate,
    "document": DocumentCreate,
    "invoice": InvoiceCreate,
}

# Native columns an entity has that its Create schema does *not* declare, because they
# are derived or set only by a dedicated method. Empty for the four entities whose
# writable surface is their whole surface; non-empty for `invoice`, whose fiscal
# columns are computed at emission and are exactly the names an administrator would
# slugify into by accident ("Totale" -> `totale`).
#
# A13 remains open: `FieldDefinitionService.create` still compares a slugified label
# only against other definitions and never calls this function at all. Making the list
# complete does not close that hole -- it makes the data the fix will read correct, so
# that closing it in slice 1A protects the fiscal columns too rather than only the six
# names `InvoiceCreate` happens to declare.
EXTRA_NATIVE_FIELDS: dict[str, tuple[str, ...]] = {
    "customer": (),
    "person": (),
    "deal": (),
    "document": (),
    "invoice": (
        "anno",
        "numero",
        "riferimento",
        "stato",
        "data_emissione",
        "data_scadenza",
        "tipo_documento",
        "divisa",
        "imponibile",
        "imposta",
        "bollo",
        "totale",
        "stato_pagamento",
        "data_incasso",
        "trasmessa_esternamente_il",
        "annullata_il",
        "motivo_annullamento",
        "origine_proforma_id",
    ),
}


def native_fields(entity_type: str) -> list[str]:
    """Derived from the Pydantic model, never hand-listed -- plus the columns that
    model cannot declare (see EXTRA_NATIVE_FIELDS). Order is stable: derived first, in
    field-definition order, then the extras in declaration order, so a caller can
    diff two runs."""
    derived = [
        name for name in CREATE_MODELS[entity_type].model_fields if name != "custom_fields"
    ]
    extra = [name for name in EXTRA_NATIVE_FIELDS.get(entity_type, ()) if name not in derived]
    return derived + extra
```

- [ ] **Step 5: Teach `documents` the three artefact types**

In `packages/core/src/pigrocrm/core/documents/schemas.py`, replace the `DocumentTipo` alias and add the XML content type:

```python
# `fattura` is the PDF of an issued invoice, `fattura_xml` its FatturaPA file, and
# `proforma` the PDF of a provisional one (which has no XML). Two `documents` rows per
# issued invoice, not one: a `document_versions` chain is a linear history of one
# logical file with one `hash_sha256` used for deduplication and integrity, so putting
# two formats in it would make "version 3" ambiguous and the two hashes incomparable.
DocumentTipo = Literal[
    "offerta", "contratto", "verbale", "documento", "fattura", "fattura_xml", "proforma"
]
```

and inside `ALLOWED_CONTENT_TYPES`, after the `"application/pdf"` entry:

```python
    "application/xml": ".xml",
```

- [ ] **Step 6: Widen the frontend union**

In `apps/web/src/lib/schema.ts`:

```ts
export type EntityType = 'customer' | 'person' | 'deal' | 'document' | 'invoice'
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_schemas.py packages/core/tests/test_schema_registry.py packages/core/tests/test_module_imports.py packages/core/tests/test_fields_service.py -v`
Expected: PASS

Run: `uv run mypy` and `uv run ruff check .`
Expected: clean.

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/schemas.py packages/core/src/pigrocrm/core/fields/schemas.py packages/core/src/pigrocrm/core/schema_registry.py packages/core/src/pigrocrm/core/documents/schemas.py apps/web/src/lib/schema.ts packages/core/tests/test_invoice_schemas.py packages/core/tests/test_schema_registry.py
git commit -m "feat(invoices): schemas, the frozen snapshot, and invoice as an entity type"
```

---

### Task 5: The SdI file name and `ProgressivoInvio`

**Files:**
- Create: `packages/core/src/pigrocrm/core/invoices/naming.py`
- Test: `packages/core/tests/test_invoice_naming.py`

**Interfaces:**
- Consumes: `pigrocrm.core.invoices.schemas.MAX_NUMERO`; `pigrocrm.core.errors.ValidationFailed`.
- Produces:
  - `progressivo_invio(anno: int, numero: int) -> str` — base-36, five uppercase characters
  - `sdi_filename(id_fiscale: str, anno: int, numero: int) -> str`
  - `invoice_storage_prefix(anno: int, numero: int) -> str`
  - `proforma_storage_prefix(invoice_id: UUID) -> str`
  - `numero_completo(anno: int, numero: int) -> str`
  - `FISCAL_ID_RE: re.Pattern[str]`, `NUMERO_COMPLETO_RE: re.Pattern[str]`, `RIFERIMENTO_PROFORMA_RE: re.Pattern[str]`
  - `proforma_riferimento(anno: int, sequenza: int) -> str`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_invoice_naming.py`:

```python
"""Names that leave the system.

The XML file goes to an intermediary that often validates its name before its
content, and the proforma's reference goes on a document somebody might try to pay.
Both are therefore deterministic functions of stored data, never derived from a
user-visible label -- Acme recovered the fiscal progressive with
`/Fattura\\s+(\\d+)/i` against a title.
"""

from uuid import UUID

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.invoices.naming import (
    NUMERO_COMPLETO_RE,
    RIFERIMENTO_PROFORMA_RE,
    invoice_storage_prefix,
    numero_completo,
    proforma_riferimento,
    proforma_storage_prefix,
    progressivo_invio,
    sdi_filename,
)


def test_the_progressive_is_five_base36_characters_of_year_times_ten_thousand() -> None:
    """`anno * 10000 + numero` in base 36, padded to five characters: deterministic,
    so re-exporting produces the same name, and collision-free while numero stays
    under 10 000."""
    assert progressivo_invio(2026, 1) == "C28PT"
    assert progressivo_invio(2026, 2) == "C28PU"
    assert progressivo_invio(2027, 1) == "C2GFL"


def test_the_progressive_is_injective_across_a_year_boundary() -> None:
    seen = {progressivo_invio(anno, numero) for anno in (2026, 2027) for numero in (1, 9999)}
    assert len(seen) == 4


def test_a_five_digit_numero_is_refused_rather_than_producing_an_ambiguous_name() -> None:
    with pytest.raises(ValidationFailed) as caught:
        progressivo_invio(2026, 10_000)
    assert caught.value.details["field"] == "numero"


def test_the_sdi_file_name_follows_the_convention() -> None:
    assert sdi_filename("12345678901", 2026, 7) == "IT12345678901_C28PZ.xml"


def test_the_sdi_file_name_refuses_an_identifier_that_is_not_a_piva_or_a_cf() -> None:
    """A malformed IdCodice is an outright rejection; a malformed *file name* is one
    too, and cheaper to catch here."""
    for bad in ("1234567890", "IT12345678901", "12345678901\n", "abc"):
        with pytest.raises(ValidationFailed):
            sdi_filename(bad, 2026, 7)


def test_a_sixteen_character_fiscal_code_is_accepted() -> None:
    assert sdi_filename("RSSMRA80A01H501U", 2026, 1) == "ITRSSMRA80A01H501U_C28PT.xml"


def test_storage_prefixes_are_lowercase_and_disjoint() -> None:
    """`storage/base.py`'s key pattern is lowercase-only on purpose -- two keys
    differing only in case name the same file on APFS and NTFS -- so the SdI's
    uppercase name cannot be a storage key. It is the download name instead."""
    assert invoice_storage_prefix(2026, 7) == "fatture/2026/7"
    assert (
        proforma_storage_prefix(UUID("0192f0aa-0000-7000-8000-000000000001"))
        == "proforma/0192f0aa-0000-7000-8000-000000000001"
    )
    assert invoice_storage_prefix(2026, 7).islower()


def test_the_full_number_is_year_slash_number() -> None:
    assert numero_completo(2026, 7) == "2026/7"
    assert NUMERO_COMPLETO_RE.fullmatch("2026/7")


def test_a_proforma_reference_can_never_match_the_fiscal_number_pattern() -> None:
    """Mechanism 1 of the four that keep a proforma from being mistaken for an
    invoice: a non-numeric prefix that no fiscal-number regex accepts."""
    riferimento = proforma_riferimento(2026, 7)
    assert riferimento == "PROV-2026-0007"
    assert RIFERIMENTO_PROFORMA_RE.fullmatch(riferimento)
    assert NUMERO_COMPLETO_RE.fullmatch(riferimento) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_naming.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.invoices.naming'`

- [ ] **Step 3: Implement**

`packages/core/src/pigrocrm/core/invoices/naming.py`:

```python
"""Deterministic names for things that leave the system.

Every function here is a pure function of stored integers. None reads a label, a
title, or any other user-visible string: Acme recovered the fiscal progressive from
a display title with `/Fattura\\s+(\\d+)/i`, which made the number on a legal document
a derivative of a caption someone could rename.
"""

import re
from uuid import UUID

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.invoices.schemas import MAX_NUMERO

ENTITY = "invoice"

_BASE36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PROGRESSIVO_WIDTH = 5
_YEAR_STRIDE = 10_000

# An `IdCodice` is either an 11-digit VAT number or a 16-character fiscal code -- the
# two forms Acme's own normalisation accepted, which is the highest-value line in
# that file. `.fullmatch` everywhere, never `.match` with `$`: `$` matches before a
# trailing newline, and a name with a newline in it reaches a filesystem and a
# `Content-Disposition` header as something neither agreed to.
FISCAL_ID_RE = re.compile(r"\d{11}|[A-Z0-9]{16}")
NUMERO_COMPLETO_RE = re.compile(r"\d{4}/\d{1,4}")
RIFERIMENTO_PROFORMA_RE = re.compile(r"PROV-\d{4}-\d{4,6}")


def _to_base36(value: int, width: int) -> str:
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        digits.append(_BASE36_DIGITS[remainder])
    return "".join(reversed(digits)).rjust(width, "0")


def progressivo_invio(anno: int, numero: int) -> str:
    """`ProgressivoInvio`, and the same token the file name carries.

    It identifies the *file*, not the invoice, which is why Acme deriving it from the
    invoice progressive was wrong in principle -- but it must also be **deterministic**,
    because spec 14.6 requires a re-export to be byte-identical to the original. A
    fresh random or clock-derived value would satisfy the first property and break the
    second. `anno * 10000 + numero` in base 36 satisfies both: it is a function of the
    invoice's own identity, unique across years, and stable forever.

    Five characters is enough while `numero <= 9999` (36**5 = 60 466 176, comfortably
    above 2999 * 10000 + 9999). Past that the mapping stops being injective across
    years, so emission refuses rather than producing a name that could collide.
    """
    if not 1 <= numero <= MAX_NUMERO:
        raise ValidationFailed(
            ENTITY,
            "numero",
            f"un progressivo oltre {MAX_NUMERO} renderebbe ambiguo il nome del file XML",
            expected=f"un numero fra 1 e {MAX_NUMERO}",
        )
    return _to_base36(anno * _YEAR_STRIDE + numero, _PROGRESSIVO_WIDTH)


def sdi_filename(id_fiscale: str, anno: int, numero: int) -> str:
    """`IT{cf_o_piva}_{progressivo}.xml`, the SdI's own convention.

    This is the **download** name, set in `Content-Disposition`, not a storage key:
    `storage/base.py`'s key pattern is lowercase-only by deliberate decision (two keys
    differing only in case name the same file on APFS and NTFS), so an uppercase `IT`
    prefix could never be one. The name matters because the file goes to an
    intermediary, which often validates the name before the content.
    """
    if not FISCAL_ID_RE.fullmatch(id_fiscale):
        raise ValidationFailed(
            "emitter_profile",
            "partita_iva",
            "il nome del file XML richiede una partita IVA di 11 cifre o un codice "
            "fiscale di 16 caratteri",
            expected="11 cifre oppure 16 caratteri alfanumerici maiuscoli",
        )
    return f"IT{id_fiscale}_{progressivo_invio(anno, numero)}.xml"


def invoice_storage_prefix(anno: int, numero: int) -> str:
    """`fatture/{anno}/{numero}` -- so a file pulled out of context is still
    identifiable, which is mechanism 4 of the four that keep a proforma from being
    mistaken for an invoice."""
    return f"fatture/{anno}/{numero}"


def proforma_storage_prefix(invoice_id: UUID) -> str:
    """`proforma/{id}` -- a different prefix, deliberately, from
    `invoice_storage_prefix`. A proforma has no number, so its id is its only stable
    handle."""
    return f"proforma/{invoice_id}"


def numero_completo(anno: int, numero: int) -> str:
    """The `Numero` printed on the document and sent in the XML.

    `{anno}/{numero}`, not Acme's `"{n}/00"`: that form carried no year at all, on a
    progressive that was global and never reset, so two invoices from different years
    were indistinguishable by number.
    """
    return f"{anno}/{numero}"


def proforma_riferimento(anno: int, sequenza: int) -> str:
    """`PROV-{anno}-{sequenza:04d}`.

    The non-numeric prefix is load-bearing: no fiscal-number pattern can accept it, so
    a proforma cannot be read as an invoice by any regex, in this codebase or in a
    spreadsheet somebody builds later.
    """
    return f"PROV-{anno}-{sequenza:04d}"


__all__ = [
    "FISCAL_ID_RE",
    "NUMERO_COMPLETO_RE",
    "RIFERIMENTO_PROFORMA_RE",
    "invoice_storage_prefix",
    "numero_completo",
    "proforma_riferimento",
    "proforma_storage_prefix",
    "progressivo_invio",
    "sdi_filename",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_naming.py -v`
Expected: PASS. If `test_the_progressive_is_five_base36_characters...` fails, do **not** edit the assertion — compute `_to_base36(2026 * 10000 + 1, 5)` in a REPL and fix the implementation; the expected values in the test were derived from the definition, and a mismatch means the base-36 conversion is wrong.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/naming.py packages/core/tests/test_invoice_naming.py
git commit -m "feat(invoices): deterministic SdI file name and ProgressivoInvio"
```

---
### Task 6: `FatturaPAExporter` — the XML, validated against the official schema

**Files:**
- Modify: `packages/core/pyproject.toml` (add `lxml==6.1.2`)
- Create: `packages/core/src/pigrocrm/core/invoices/fatturapa.py`
- Create: `packages/core/tests/fpr12/__init__.py`
- Create: `packages/core/tests/fpr12/Schema_VFPR12_v1.2.3.xsd` (downloaded, unmodified)
- Create: `packages/core/tests/fpr12/xmldsig-core-schema.xsd` (downloaded, unmodified)
- Test: `packages/core/tests/test_invoice_fatturapa.py`

**Interfaces:**
- Consumes: `pigrocrm.core.invoices.schemas.{InvoiceForExport, InvoiceLineRead, InvoiceSnapshot, PartySnapshot}`; `pigrocrm.core.invoices.totals.{RiepilogoGroup, build_riepilogo, format_amount_2, format_amount_8, format_rate}`; `pigrocrm.core.invoices.naming.{FISCAL_ID_RE, numero_completo, progressivo_invio}`; `pigrocrm.core.templates.escaping.escape_xml`; `pigrocrm.core.errors.ValidationFailed`.
- Produces:
  - `FPR12_NAMESPACE: str`, `FORMATO_TRASMISSIONE: str`, `NSMAP: dict[str | None, str]`
  - `class FatturaPAExporter` with `to_bytes(self, invoice: InvoiceForExport) -> bytes`
  - `normalise_fiscal_id(value: str | None) -> str | None`
  - `check_party_exportable(party: PartySnapshot, entity: str) -> None` and `check_recipient_routing(party: PartySnapshot) -> None` — module-level, because `InvoiceService.issue` calls them too
  - test helper `packages/core/tests/fpr12/__init__.py::fpr12_schema() -> lxml.etree.XMLSchema`

- [ ] **Step 1: Declare the dependency and vendor the schema**

```bash
uv add --package pigrocrm-core "lxml==6.1.2"
mkdir -p packages/core/tests/fpr12
curl -fL -o packages/core/tests/fpr12/Schema_VFPR12_v1.2.3.xsd \
  https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.4/Schema_VFPR12_v1.2.3.xsd
curl -fL -o packages/core/tests/fpr12/xmldsig-core-schema.xsd \
  https://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd
```

Confirm `packages/core/pyproject.toml`'s `[project].dependencies` now contains `"lxml==6.1.2"`. If `uv add` reports that version does not exist, take the newest `6.x` it resolves, write that exact pin into `packages/core/pyproject.toml`, and update the "Pinned versions" line at the top of this plan to match — the pin must be exact, not a range.

Both `.xsd` files are committed **byte-for-byte as downloaded**. Do not reformat them and do not edit the `schemaLocation` inside the FPR12 schema to point at the local sibling: hand-editing a fiscal schema so a test passes is an edit nobody reviews twice, and Step 2's resolver does the same job without touching the file.

- [ ] **Step 2: Write the schema-loading helper**

`packages/core/tests/fpr12/__init__.py`:

```python
"""The official FPR12 schema, loaded with its one remote import resolved locally.

`Schema_VFPR12_v1.2.3.xsd` carries exactly one `xs:import`, pointing at
`http://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd`. A CI
run has no network, so the import is redirected to the vendored sibling by an lxml
resolver rather than by editing the schema.

Validation goes through `lxml.etree.XMLSchema` rather than the `xmllint --schema` the
spec's success criterion names. Two reasons, both practical: nothing in this repo
installs `libxml2-utils` (`Dockerfile.api` installs Pandoc, Typst and `libpq5`), and
`lxml` is already a dependency because the generator needs it -- so this is the same
libxml2 engine `xmllint` is a thin CLI over, with no new binary in the image.

Version 1.2.3, not the 1.2.1 the spec names: 1.2.3 is the *fattura ordinaria* schema
in force since 2025-04-01 and 1.2.1 is no longer published. The `versione="FPR12"`
attribute is unchanged across 1.2.x, so nothing about the generator differs; proving a
file valid against a superseded rule set would simply prove the wrong thing.
"""

from functools import lru_cache
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
FPR12_XSD = HERE / "Schema_VFPR12_v1.2.3.xsd"
XMLDSIG_XSD = HERE / "xmldsig-core-schema.xsd"
XMLDSIG_URL = "http://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd"


class _LocalXmldsigResolver(etree.Resolver):
    def resolve(self, system_url: str, public_id: str | None, context: object):  # type: ignore[no-untyped-def]
        if system_url == XMLDSIG_URL:
            return self.resolve_filename(str(XMLDSIG_XSD), context)
        return None


@lru_cache(maxsize=1)
def fpr12_schema() -> etree.XMLSchema:
    """The compiled schema. Cached because compiling it takes noticeable time and
    every validating test wants the same object."""
    parser = etree.XMLParser(no_network=True, load_dtd=False, resolve_entities=True)
    parser.resolvers.add(_LocalXmldsigResolver())
    return etree.XMLSchema(etree.parse(str(FPR12_XSD), parser))


def assert_valid(xml_bytes: bytes) -> None:
    """Validate, and on failure raise with libxml2's own message.

    A bare `assert schema.validate(doc)` reports "False", which says nothing about
    which element in a 200-line sequence is out of order -- and element order is the
    single hardest thing about FPR12.
    """
    schema = fpr12_schema()
    document = etree.fromstring(xml_bytes)
    if not schema.validate(document):
        raise AssertionError(
            "l'XML non valida contro lo schema FPR12 v1.2.3:\n"
            + "\n".join(str(error) for error in schema.error_log)
        )
```

- [ ] **Step 3: Write the failing test**

`packages/core/tests/test_invoice_fatturapa.py`:

```python
"""The generator, proven against the official schema and against a hostile value.

No database, no session, no container: the exporter reads an `InvoiceForExport` and
returns bytes, which is exactly what makes these cases cheap enough to be exhaustive.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fpr12 import assert_valid
from lxml import etree

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.invoices.fatturapa import (
    FPR12_NAMESPACE,
    FatturaPAExporter,
    normalise_fiscal_id,
)
from pigrocrm.core.invoices.schemas import (
    SNAPSHOT_VERSIONE,
    InvoiceForExport,
    InvoiceLineRead,
    InvoiceSnapshot,
    PartySnapshot,
)
from pigrocrm.core.invoices.totals import build_riepilogo, sum_totals

Q = f"{{{FPR12_NAMESPACE}}}"

EMITTENTE = PartySnapshot(
    ragione_sociale="Humancraft di Ivan Sala",
    partita_iva="14518240966",
    codice_fiscale="HMCRFT00A01H501K",
    codice_sdi=None,
    pec="someone@example.com",
    indirizzo="Via Vittorio Veneto 12",
    cap="20124",
    comune="Milano",
    provincia="MI",
    nazione="IT",
    email="someone@example.com",
    telefono="+39 02 1234567",
    sito_web="https://humancraft.tech",
)

FISCALE = {
    "codice_regime": "RF19",
    "aliquota_iva_default": Decimal("0.00"),
    "natura_default": "N2.2",
    "riferimento_normativo": (
        "Operazione non soggetta a IVA ai sensi dell'art. 1, commi 54-89, "
        "L. 190/2014 - regime forfettario"
    ),
    "applica_bollo": True,
    "soglia_bollo": Decimal("77.47"),
    "importo_bollo": Decimal("2.00"),
    "condizioni_pagamento": "TP02",
    "modalita_pagamento": "MP05",
    "giorni_scadenza": 30,
    "iban": "IT60X0542811101000000123456",
}


def _cliente(**overrides: object) -> PartySnapshot:
    base: dict[str, object] = {
        "ragione_sociale": "Acme S.r.l.",
        "partita_iva": "12345678901",
        "codice_fiscale": None,
        "codice_sdi": "ABCDEFG",
        "pec": None,
        "indirizzo": "Corso Italia 5",
        "cap": "00100",
        "comune": "Roma",
        "provincia": "RM",
        "nazione": "IT",
        "email": None,
        "telefono": None,
        "sito_web": None,
    }
    base.update(overrides)
    return PartySnapshot(**base)  # type: ignore[arg-type]


def _line(
    numero: int,
    descrizione: str,
    quantita: str,
    prezzo: str,
    prezzo_totale: str,
    aliquota: str = "0.00",
    natura: str | None = "N2.2",
    unita: str | None = None,
) -> InvoiceLineRead:
    return InvoiceLineRead(
        id=uuid4(),
        invoice_id=uuid4(),
        numero_linea=numero,
        descrizione=descrizione,
        quantita=Decimal(quantita),
        unita_misura=unita,
        prezzo_unitario=Decimal(prezzo),
        sconto_percentuale=None,
        sconto_importo=None,
        prezzo_totale=Decimal(prezzo_totale),
        aliquota_iva=Decimal(aliquota),
        natura=natura,
        riferimento_normativo=FISCALE["riferimento_normativo"] if natura else None,
    )


def _invoice(
    righe: list[InvoiceLineRead],
    *,
    cliente: PartySnapshot | None = None,
    bollo: str = "0.00",
    causale: str | None = "Consulenza tecnica",
    numero: int = 7,
) -> InvoiceForExport:
    imponibile, imposta, totale = sum_totals(build_riepilogo_from(righe))
    return InvoiceForExport(
        anno=2026,
        numero=numero,
        data_emissione=date(2026, 8, 20),
        data_scadenza=date(2026, 9, 19),
        tipo_documento="TD01",
        divisa="EUR",
        imponibile=imponibile,
        imposta=imposta,
        bollo=Decimal(bollo),
        totale=totale,
        causale=causale,
        snapshot=InvoiceSnapshot(
            versione=SNAPSHOT_VERSIONE,
            emittente=EMITTENTE,
            cliente=cliente or _cliente(),
            fiscale=FISCALE,  # type: ignore[arg-type]
        ),
        righe=tuple(righe),
    )


def build_riepilogo_from(righe: list[InvoiceLineRead]):
    from pigrocrm.core.invoices.totals import ComputedLine

    return build_riepilogo(
        [
            ComputedLine(
                numero_linea=r.numero_linea,
                descrizione=r.descrizione,
                quantita=r.quantita,
                unita_misura=r.unita_misura,
                prezzo_unitario=r.prezzo_unitario,
                sconto_percentuale=r.sconto_percentuale,
                sconto_importo=r.sconto_importo,
                prezzo_totale=r.prezzo_totale,
                aliquota_iva=r.aliquota_iva,
                natura=r.natura,
                riferimento_normativo=r.riferimento_normativo,
            )
            for r in righe
        ]
    )


# --- criterion 1: the official schema validates -----------------------------------


def test_a_single_line_invoice_validates() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza tecnica", "1.000000", "1500.000000", "1500.00")])
    )
    assert_valid(xml)


def test_a_five_line_invoice_validates() -> None:
    righe = [
        _line(n, f"Attivita {n}", "2.000000", "150.000000", "300.00", unita="ore")
        for n in range(1, 6)
    ]
    assert_valid(FatturaPAExporter().to_bytes(_invoice(righe)))


def test_an_invoice_with_a_negative_discount_line_validates() -> None:
    righe = [
        _line(1, "Consulenza", "1.000000", "1000.000000", "1000.00"),
        _line(2, "Sconto commerciale", "1.000000", "-100.000000", "-100.00"),
    ]
    xml = FatturaPAExporter().to_bytes(_invoice(righe))
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(f".//{Q}ImportoTotaleDocumento") == "900.00"


def test_exactly_at_the_stamp_duty_threshold_there_is_no_dati_bollo() -> None:
    """Spec 14.1: 77.47 is not *above* the threshold."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "77.470000", "77.47")], bollo="0.00")
    )
    assert_valid(xml)
    assert etree.fromstring(xml).find(f".//{Q}DatiBollo") is None


def test_one_cent_above_the_threshold_the_stamp_duty_is_declared() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "77.480000", "77.48")], bollo="2.00")
    )
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(f".//{Q}BolloVirtuale") == "SI"
    assert root.findtext(f".//{Q}ImportoBollo") == "2.00"
    # The duty is settled by the issuer, not charged to the customer (spec 7.2).
    assert root.findtext(f".//{Q}ImportoTotaleDocumento") == "77.48"


# --- criterion 2: a hostile name cannot corrupt the file ---------------------------

HOSTILE = 'Rossi & C. <IdCodice>999</IdCodice> "#$@\\ ]]>'


def test_a_hostile_name_still_produces_a_schema_valid_file() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(ragione_sociale=HOSTILE),
        )
    )
    assert_valid(xml)


def test_a_hostile_name_round_trips_byte_for_byte() -> None:
    """The tree serialiser is the one escaping pass, so re-parsing must give back the
    domain value exactly. Acme ran a value through escapeTypstText and then
    escapeXml, which put a literal backslash into an Agenzia delle Entrate record --
    that is what this asserts cannot happen."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(ragione_sociale=HOSTILE),
        )
    )
    root = etree.fromstring(xml)
    denominazioni = [element.text for element in root.iter(f"{Q}Denominazione")]
    assert HOSTILE in denominazioni


def test_a_hostile_name_creates_no_element_the_exporter_did_not_create() -> None:
    """Verified by walking the tree, not by comparing strings: `<IdCodice>999` inside
    a name must be text, so the document must contain exactly the three `IdCodice`
    elements the exporter emits (transmitter, cedente, cessionario) and no fourth."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(ragione_sociale=HOSTILE),
        )
    )
    root = etree.fromstring(xml)
    assert len(list(root.iter(f"{Q}IdCodice"))) == 3
    assert not [element.text for element in root.iter(f"{Q}IdCodice") if element.text == "999"]


def test_a_hostile_description_and_causale_are_equally_inert() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, HOSTILE, "1.000000", "100.000000", "100.00")], causale=HOSTILE)
    )
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(f".//{Q}Descrizione") == HOSTILE
    assert root.findtext(f".//{Q}Causale") == HOSTILE


def test_a_code_point_xml_cannot_represent_is_refused_not_emitted() -> None:
    with pytest.raises(ValueError, match="non rappresentabile in XML"):
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza\x0b", "1.000000", "100.000000", "100.00")],
            )
        )


# --- the prologue and the element order carried over from Acme --------------------


def test_the_prologue_keeps_the_three_declarations_and_the_version_attribute() -> None:
    """`lxml`, not ElementTree, precisely for this: ElementTree prunes a prefix the
    document does not reference, and `ds:`/`xsi:` are unreferenced here. Removing a
    declaration from a prologue the SdI and every intermediary's validator have
    already accepted buys nothing."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    head = xml.decode("utf-8").split(">", 2)[1]
    assert xml.startswith(b'<?xml version=\'1.0\' encoding=\'UTF-8\'?>')
    assert 'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"' in head
    assert 'xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"' in head
    assert 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' in head
    assert 'versione="FPR12"' in head
    assert head.lstrip("<").startswith("p:FatturaElettronica")


def test_formato_trasmissione_is_repeated_inside_dati_trasmissione() -> None:
    """Not redundant with the root attribute: the SdI reads it from here."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    assert etree.fromstring(xml).findtext(f".//{Q}FormatoTrasmissione") == "FPR12"


def test_the_number_carries_the_year(  ) -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")], numero=7)
    )
    root = etree.fromstring(xml)
    assert root.findtext(f".//{Q}Numero") == "2026/7"
    assert root.findtext(f".//{Q}ProgressivoInvio") == "C28PZ"
    assert root.findtext(f".//{Q}Data") == "2026-08-20"


def test_the_transmitter_id_may_be_the_fiscal_code() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    trasmittente = etree.fromstring(xml).find(f".//{Q}IdTrasmittente")
    assert trasmittente.findtext(f"{Q}IdCodice") == "HMCRFT00A01H501K"


def test_the_vat_quartet_agrees_on_every_summary_group() -> None:
    """Two SdI checks applied as a pair: a zero rate with no Natura is rejected, and
    a Natura with a non-zero rate is rejected. All four must agree."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    riepilogo = etree.fromstring(xml).find(f".//{Q}DatiRiepilogo")
    assert riepilogo.findtext(f"{Q}AliquotaIVA") == "0.00"
    assert riepilogo.findtext(f"{Q}Natura") == "N2.2"
    assert riepilogo.findtext(f"{Q}Imposta") == "0.00"
    assert riepilogo.findtext(f"{Q}EsigibilitaIVA") == "I"
    assert riepilogo.findtext(f"{Q}RiferimentoNormativo") == FISCALE["riferimento_normativo"]


def test_the_payment_block_carries_the_profile_values() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    root = etree.fromstring(xml)
    assert root.findtext(f".//{Q}CondizioniPagamento") == "TP02"
    assert root.findtext(f".//{Q}ModalitaPagamento") == "MP05"
    assert root.findtext(f".//{Q}DataScadenzaPagamento") == "2026-09-19"
    assert root.findtext(f".//{Q}ImportoPagamento") == "100.00"
    assert root.findtext(f".//{Q}IBAN") == "IT60X0542811101000000123456"


def test_quantity_and_unit_price_keep_six_decimals() -> None:
    """Amount8DecimalType allows 2 to 8 decimals; three hours at 33,333333 EUR/h is
    the case `Numeric(12, 6)` exists for."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "3.000000", "33.333333", "100.00")])
    )
    root = etree.fromstring(xml)
    assert root.findtext(f".//{Q}Quantita") == "3.000000"
    assert root.findtext(f".//{Q}PrezzoUnitario") == "33.333333"
    assert root.findtext(f".//{Q}PrezzoTotale") == "100.00"


# --- the recipient-code fallback, and the refusals --------------------------------


def test_a_customer_with_a_pec_but_no_sdi_gets_the_seven_zeroes_and_the_pec() -> None:
    """The correct fallback is not deducible from the schema, where the field is
    simply mandatory."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(codice_sdi=None, pec="acme@pec.it"),
        )
    )
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(f".//{Q}CodiceDestinatario") == "0000000"
    assert root.findtext(f".//{Q}PECDestinatario") == "acme@pec.it"


def test_a_customer_with_neither_sdi_nor_pec_is_refused_by_field_name() -> None:
    """Acme produced an empty `CodiceDestinatario` here: an invalid file, generated
    without an error."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(codice_sdi=None, pec=None),
            )
        )
    assert caught.value.details["entity"] == "customer"
    assert caught.value.details["field"] == "codice_sdi"


@pytest.mark.parametrize("field", ["indirizzo", "cap", "comune", "provincia"])
def test_a_missing_address_part_is_refused_by_field_name(field: str) -> None:
    """These are four real columns on `customers`. Acme guessed them out of one
    free-text address with a regex over Italian street prefixes."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(**{field: ""}),
            )
        )
    assert caught.value.details["field"] == field


def test_a_cap_that_is_not_five_digits_is_refused() -> None:
    """FPR12's CAP is exactly `[0-9]{5}`, while `customers.cap` is String(10)."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(cap="2012"),
            )
        )
    assert caught.value.details["field"] == "cap"


def test_a_denomination_longer_than_the_schema_allows_is_refused_not_truncated() -> None:
    """`Denominazione` is String80LatinType; `customers.ragione_sociale` is
    String(255). Truncating a legal name on a fiscal document is worse than refusing
    to issue it."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(ragione_sociale="A" * 81),
            )
        )
    assert caught.value.details["field"] == "ragione_sociale"


def test_a_denomination_outside_latin_1_is_refused_by_field_name() -> None:
    """The schema's own pattern admits Basic Latin and Latin-1 Supplement only. An
    SdI rejection over a code point is worse than a message naming the field."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(ragione_sociale="Акме ООО"),
            )
        )
    assert caught.value.details["field"] == "ragione_sociale"


def test_a_foreign_customer_is_refused_because_the_slice_does_not_do_them() -> None:
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(nazione="DE"),
            )
        )
    assert caught.value.details["field"] == "nazione"


def test_an_invoice_with_no_lines_is_refused() -> None:
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(_invoice([]))
    assert caught.value.details["field"] == "righe"


# --- fiscal-id normalisation, the highest-value line carried from Acme ------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("IT12345678901", "12345678901"),
        ("12.345.678.901", "12345678901"),
        (" 12345678901 ", "12345678901"),
        ("rssmra80a01h501u", "RSSMRA80A01H501U"),
        ("1234567890", None),
        ("12345678901234567", None),
        ("", None),
        (None, None),
    ],
)
def test_a_fiscal_id_that_does_not_match_is_omitted_rather_than_malformed(
    raw: str | None, expected: str | None
) -> None:
    """The highest-value line in Acme's generator: a malformed `IdCodice` is an
    outright rejection, while an absent element often passes."""
    assert normalise_fiscal_id(raw) == expected


def test_a_customer_with_an_unusable_vat_number_omits_the_element_entirely() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(partita_iva=None, codice_fiscale="RSSMRA80A01H501U"),
        )
    )
    assert_valid(xml)
    cessionario = etree.fromstring(xml).find(f".//{Q}CessionarioCommittente")
    assert cessionario.find(f".//{Q}IdFiscaleIVA") is None
    assert cessionario.findtext(f".//{Q}CodiceFiscale") == "RSSMRA80A01H501U"


# --- criterion 8: the synthetic RF01 case, end to end through the XML -------------


def test_two_rates_produce_one_summary_group_each_with_group_computed_tax() -> None:
    righe = [
        _line(1, "Consulenza", "1.000000", "100.000000", "100.00", aliquota="22.00", natura=None),
        _line(2, "Formazione", "1.000000", "50.000000", "50.00", aliquota="10.00", natura=None),
        _line(3, "Assistenza", "1.000000", "25.000000", "25.00", aliquota="22.00", natura=None),
    ]
    invoice = _invoice(righe, causale=None)
    xml = FatturaPAExporter().to_bytes(invoice)
    assert_valid(xml)
    root = etree.fromstring(xml)
    groups = [
        (
            g.findtext(f"{Q}AliquotaIVA"),
            g.findtext(f"{Q}ImponibileImporto"),
            g.findtext(f"{Q}Imposta"),
        )
        for g in root.iter(f"{Q}DatiRiepilogo")
    ]
    assert groups == [("10.00", "50.00", "5.00"), ("22.00", "125.00", "27.50")]
    assert root.findtext(f".//{Q}ImportoTotaleDocumento") == "207.50"
    assert root.find(f".//{Q}Natura") is None


# --- determinism, which criterion 6 depends on ------------------------------------


def test_two_exports_of_the_same_invoice_are_byte_identical() -> None:
    invoice = _invoice([_line(1, "Consulenza", "1.000000", "1500.000000", "1500.00")])
    exporter = FatturaPAExporter()
    assert exporter.to_bytes(invoice) == exporter.to_bytes(invoice)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_fatturapa.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.invoices.fatturapa'`

- [ ] **Step 5: Implement**

`packages/core/src/pigrocrm/core/invoices/fatturapa.py`:

```python
"""The FatturaPA FPR12 generator.

Built as an `lxml` element tree and serialised exactly once. There is no point in this
module where a fragment of XML exists as a string, which is what makes markup
injection impossible *by structure* rather than by every interpolation site
remembering to call an escaper -- the property Acme's string-concatenated generator
could only ever approximate.

Three consequences, spelled out because each replaces a specific defect:

1. A value enters as the `.text` of a node, in its domain form, and the serialiser
   escapes it once. `escape_xml` is applied first and substitutes nothing; it only
   refuses code points XML 1.0 cannot represent. No value in this module has been
   through another escaper -- Acme's `normalizeSingleLine` ran `escapeTypstText`
   before `escapeXml`, so "Rossi & C. #1" reached the Agenzia delle Entrate as
   "Rossi &amp; C. \\#1", with a literal backslash inside a fiscal record.
2. `lxml`, not `xml.etree.ElementTree`: an explicit `nsmap` on the root keeps the
   `ds:` and `xsi:` declarations this document does not reference. ElementTree prunes
   them. The prologue is reproduced identically because it is one the SdI and the
   intermediaries' own validators have already accepted, and there is no upside to
   changing it.
3. Nothing here reads the database. The input is an `InvoiceForExport`, whose
   `snapshot` was frozen at emission, so a re-export is reproducible and the whole
   generator is testable with no session at all.

Order is not negotiable: every FPR12 complex type is an `xs:sequence`, so an element
in the wrong position is an invalid document even when every value is right.
Reconstructing that order from the schema is the bulk of the work, and it is carried
over from a generator whose output the Sistema di Interscambio accepted.
"""

import re
from datetime import date
from decimal import Decimal

from lxml import etree

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.invoices.naming import FISCAL_ID_RE, numero_completo, progressivo_invio
from pigrocrm.core.invoices.schemas import InvoiceForExport, PartySnapshot
from pigrocrm.core.invoices.totals import (
    ComputedLine,
    build_riepilogo,
    format_amount_2,
    format_amount_8,
    format_rate,
)
from pigrocrm.core.templates.escaping import escape_xml

FPR12_NAMESPACE = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
DS_NAMESPACE = "http://www.w3.org/2000/09/xmldsig#"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
FORMATO_TRASMISSIONE = "FPR12"

# All three prefixes are declared on the root, `ds:` and `xsi:` included even though
# nothing in this file uses either. `ds:` becomes load-bearing only with the digital
# signature, which is out of scope; keeping both is how the prologue stays identical
# to one already accepted downstream. This is the reason for lxml -- see the module
# docstring.
NSMAP: dict[str | None, str] = {"p": FPR12_NAMESPACE, "ds": DS_NAMESPACE, "xsi": XSI_NAMESPACE}

# `CodiceDestinatario` for a private recipient with no SDI code, paired with
# `PECDestinatario`. Not deducible from the schema, where the field is simply
# mandatory.
CODICE_DESTINATARIO_FALLBACK = "0000000"
# Immediate VAT liability. The deferred and cash-basis variants are out of scope.
ESIGIBILITA_IVA = "I"
BOLLO_VIRTUALE = "SI"

# FPR12 widths. Every one is narrower than the Postgres column it comes from, so each
# is a real check and not a restatement of the schema's own bound.
_DENOMINAZIONE_MAX = 80
_INDIRIZZO_MAX = 60
_COMUNE_MAX = 60
_DESCRIZIONE_MAX = 1000
_CAUSALE_MAX = 200
_RIFERIMENTO_NORMATIVO_MAX = 100
_EMAIL_MAX = 256
_TELEFONO_MAX = 12

# `xs:pattern` restrictions the schema applies. `.fullmatch` at every call site, never
# `.match` with `$`.
_CAP_RE = re.compile(r"\d{5}")
_PROVINCIA_RE = re.compile(r"[A-Z]{2}")
_NAZIONE_RE = re.compile(r"[A-Z]{2}")
_IBAN_RE = re.compile(r"[A-Z]{2}\d{2}[A-Za-z0-9]{11,30}")
_CODICE_DESTINATARIO_RE = re.compile(r"[A-Z0-9]{7}")
_TIPO_PAGAMENTO_RE = re.compile(r"(TP|MP)\d{2}")
# The schema's `String*LatinType` family admits Basic Latin and Latin-1 Supplement
# only. A code point outside that is an SdI rejection, so it is refused here with the
# field named instead.
_LATIN_RE = re.compile(r"[\x00-\xff]*")
# Punctuation and the "IT" prefix are stripped before a fiscal identifier is matched,
# exactly as Acme's own normalisation did.
_FISCAL_ID_NOISE = re.compile(r"[^0-9A-Za-z]")


def normalise_fiscal_id(value: str | None) -> str | None:
    """An 11-digit VAT number or a 16-character fiscal code, or `None`.

    Strips the `IT` prefix and any punctuation, upper-cases, and then accepts only the
    two shapes FPR12 recognises. **Anything else returns `None` so the caller omits
    the element** rather than emitting it malformed -- the highest-value line carried
    over from Acme's generator, because a malformed `IdCodice` is an outright
    rejection while an absent element usually passes.
    """
    if not value:
        return None
    cleaned = _FISCAL_ID_NOISE.sub("", value).upper()
    if cleaned.startswith("IT") and len(cleaned) == 13:
        cleaned = cleaned[2:]
    return cleaned if FISCAL_ID_RE.fullmatch(cleaned) else None


def check_party_exportable(party: PartySnapshot, entity: str) -> None:
    """Refuse, naming the field on the record the user can go and fix (spec 14.9).

    A module-level function rather than a method, because it has **two** callers and
    they must not drift: this exporter, and `InvoiceService.issue`, which runs it
    *before* consuming a number. Checking only here would be too late -- the export
    happens after the emission transaction has committed (spec 3), so a customer
    missing a CAP would already own a register number that can never produce a valid
    file, and the only remaining remedy would be an annulment.

    Acme guessed `indirizzo`, `cap`, `comune` and `provincia` out of one free-text
    field with a regex over Italian street prefixes. They are four real columns on
    `customers`; nothing is guessed, and a missing one refuses.
    """
    if party.nazione != "IT":
        raise ValidationFailed(
            entity,
            "nazione",
            "questo slice non emette fatture verso l'estero: richiedono un IdPaese "
            "diverso e CodiceDestinatario XXXXXXX",
            expected="IT",
        )
    for field in ("indirizzo", "cap", "comune", "provincia"):
        if not (getattr(party, field) or "").strip():
            raise ValidationFailed(
                entity,
                field,
                "campo obbligatorio per la fattura elettronica",
                expected="un valore non vuoto",
            )
    if not party.ragione_sociale.strip():
        raise ValidationFailed(
            entity, "ragione_sociale", "campo obbligatorio", expected="un valore non vuoto"
        )


def check_recipient_routing(party: PartySnapshot) -> None:
    """A customer must have an SDI code or a PEC, or there is no `CodiceDestinatario`.

    Split from `check_party_exportable` because it applies only to the *recipient*,
    and shared with `InvoiceService.issue` for the same reason: Acme emitted an empty
    `CodiceDestinatario` here, producing an invalid file with no error at all.
    """
    if not (party.codice_sdi or "").strip() and not (party.pec or "").strip():
        raise ValidationFailed(
            "customer",
            "codice_sdi",
            "serve un codice destinatario (SDI) oppure una PEC per emettere la fattura",
            expected="codice_sdi di 7 caratteri oppure pec",
        )


class FatturaPAExporter:
    """`InvoiceForExport` in, `bytes` out. No database, no profile lookup, no clock."""

    def to_bytes(self, invoice: InvoiceForExport) -> bytes:
        if not invoice.righe:
            raise ValidationFailed(
                "invoice", "righe", "una fattura senza righe non e' esportabile",
                expected="almeno una riga",
            )
        emittente = invoice.snapshot.emittente
        cliente = invoice.snapshot.cliente
        check_party_exportable(emittente, "emitter_profile")
        check_party_exportable(cliente, "customer")

        root = etree.Element(f"{{{FPR12_NAMESPACE}}}FatturaElettronica", nsmap=NSMAP)
        root.set("versione", FORMATO_TRASMISSIONE)

        header = etree.SubElement(root, "FatturaElettronicaHeader")
        self._dati_trasmissione(header, invoice)
        self._cedente(header, invoice)
        self._cessionario(header, cliente)

        body = etree.SubElement(root, "FatturaElettronicaBody")
        self._dati_generali(body, invoice)
        self._dati_beni_servizi(body, invoice)
        self._dati_pagamento(body, invoice)

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    # ---- value writers ---------------------------------------------------------

    def _text(
        self,
        parent: etree._Element,
        tag: str,
        value: str,
        *,
        entity: str,
        field: str,
        max_length: int | None = None,
        pattern: re.Pattern[str] | None = None,
        latin_only: bool = True,
    ) -> etree._Element:
        """Append `<tag>value</tag>`, with `value` as the node's text and nothing else.

        `escape_xml` runs first and substitutes nothing (see its docstring): it refuses
        a code point XML 1.0 cannot represent. The serialiser is the single escaping
        pass, which is why no second escaper is applied here and why one applied
        earlier would be a defect rather than extra safety.
        """
        value = escape_xml(value)
        if max_length is not None and len(value) > max_length:
            raise ValidationFailed(
                entity,
                field,
                f"il valore supera i {max_length} caratteri ammessi da FPR12 per {tag}",
                expected=f"al massimo {max_length} caratteri",
            )
        if latin_only and not _LATIN_RE.fullmatch(value):
            raise ValidationFailed(
                entity,
                field,
                f"FPR12 ammette in {tag} solo caratteri latini di base o Latin-1",
                expected="solo caratteri latini",
            )
        if pattern is not None and not pattern.fullmatch(value):
            raise ValidationFailed(
                entity,
                field,
                f"il valore non ha la forma richiesta da FPR12 per {tag}: {value!r}",
                expected=pattern.pattern,
            )
        element = etree.SubElement(parent, tag)
        element.text = value
        return element

    def _anagrafica(self, parent: etree._Element, party: PartySnapshot, entity: str) -> None:
        """`Anagrafica/Denominazione`, even for a natural person with only a fiscal
        code: FPR12 allows `Nome`/`Cognome` instead, but `customers` has a single
        `ragione_sociale`, so there is no choice to make."""
        anagrafica = etree.SubElement(parent, "Anagrafica")
        self._text(
            anagrafica,
            "Denominazione",
            party.ragione_sociale,
            entity=entity,
            field="ragione_sociale",
            max_length=_DENOMINAZIONE_MAX,
        )

    def _sede(self, parent: etree._Element, party: PartySnapshot, entity: str) -> None:
        sede = etree.SubElement(parent, "Sede")
        self._text(
            sede, "Indirizzo", party.indirizzo, entity=entity, field="indirizzo",
            max_length=_INDIRIZZO_MAX,
        )
        self._text(sede, "CAP", party.cap.strip(), entity=entity, field="cap", pattern=_CAP_RE)
        self._text(
            sede, "Comune", party.comune, entity=entity, field="comune", max_length=_COMUNE_MAX
        )
        self._text(
            sede,
            "Provincia",
            party.provincia.strip().upper(),
            entity=entity,
            field="provincia",
            pattern=_PROVINCIA_RE,
        )
        self._text(
            sede, "Nazione", party.nazione.strip().upper(), entity=entity, field="nazione",
            pattern=_NAZIONE_RE,
        )

    def _id_fiscale(
        self, parent: etree._Element, tag: str, id_codice: str, entity: str, field: str
    ) -> None:
        block = etree.SubElement(parent, tag)
        paese = etree.SubElement(block, "IdPaese")
        paese.text = "IT"
        self._text(block, "IdCodice", id_codice, entity=entity, field=field)

    # ---- header ----------------------------------------------------------------

    def _dati_trasmissione(self, header: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: IdTrasmittente, ProgressivoInvio, FormatoTrasmissione,
        CodiceDestinatario, ContattiTrasmittente?, PECDestinatario?."""
        emittente = invoice.snapshot.emittente
        cliente = invoice.snapshot.cliente
        block = etree.SubElement(header, "DatiTrasmissione")

        # `IdTrasmittente/IdCodice` may be the issuer's *fiscal code* rather than the
        # VAT number, which is not obvious from the schema. Fiscal code first because
        # that is what the working generator sent.
        trasmittente = normalise_fiscal_id(emittente.codice_fiscale) or normalise_fiscal_id(
            emittente.partita_iva
        )
        if trasmittente is None:
            raise ValidationFailed(
                "emitter_profile",
                "codice_fiscale",
                "serve un codice fiscale o una partita IVA dell'emittente per il "
                "blocco IdTrasmittente",
                expected="11 cifre oppure 16 caratteri",
            )
        self._id_fiscale(
            block, "IdTrasmittente", trasmittente, "emitter_profile", "codice_fiscale"
        )

        progressivo = etree.SubElement(block, "ProgressivoInvio")
        progressivo.text = progressivo_invio(invoice.anno, invoice.numero)

        formato = etree.SubElement(block, "FormatoTrasmissione")
        # Not redundant with the root's own `versione` attribute: the SdI reads it here.
        formato.text = FORMATO_TRASMISSIONE

        codice_sdi = (cliente.codice_sdi or "").strip().upper()
        if codice_sdi:
            self._text(
                block,
                "CodiceDestinatario",
                codice_sdi,
                entity="customer",
                field="codice_sdi",
                pattern=_CODICE_DESTINATARIO_RE,
            )
        elif (cliente.pec or "").strip():
            destinatario = etree.SubElement(block, "CodiceDestinatario")
            destinatario.text = CODICE_DESTINATARIO_FALLBACK
        else:
            # Acme emitted an empty element here: an invalid file, produced with no
            # error at all.
            raise ValidationFailed(
                "customer",
                "codice_sdi",
                "serve un codice destinatario (SDI) oppure una PEC per emettere la fattura",
                expected="codice_sdi di 7 caratteri oppure pec",
            )

        if (emittente.email or "").strip():
            contatti = etree.SubElement(block, "ContattiTrasmittente")
            self._text(
                contatti, "Email", emittente.email or "", entity="emitter_profile",
                field="email", max_length=_EMAIL_MAX,
            )
        if not codice_sdi and (cliente.pec or "").strip():
            self._text(
                block, "PECDestinatario", cliente.pec or "", entity="customer", field="pec",
                max_length=_EMAIL_MAX,
            )

    def _cedente(self, header: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: DatiAnagrafici(IdFiscaleIVA?, CodiceFiscale?, Anagrafica,
        ..., RegimeFiscale), Sede, ..., Contatti?."""
        emittente = invoice.snapshot.emittente
        cedente = etree.SubElement(header, "CedentePrestatore")
        anagrafici = etree.SubElement(cedente, "DatiAnagrafici")

        piva = normalise_fiscal_id(emittente.partita_iva)
        if piva is not None:
            self._id_fiscale(
                anagrafici, "IdFiscaleIVA", piva, "emitter_profile", "partita_iva"
            )
        codice_fiscale = normalise_fiscal_id(emittente.codice_fiscale)
        if codice_fiscale is not None:
            self._text(
                anagrafici, "CodiceFiscale", codice_fiscale, entity="emitter_profile",
                field="codice_fiscale",
            )
        if piva is None and codice_fiscale is None:
            raise ValidationFailed(
                "emitter_profile",
                "partita_iva",
                "l'emittente deve avere una partita IVA o un codice fiscale valido",
                expected="11 cifre oppure 16 caratteri",
            )
        self._anagrafica(anagrafici, emittente, "emitter_profile")
        regime = etree.SubElement(anagrafici, "RegimeFiscale")
        # From `fiscal_profile.codice_regime`, never a constant in the source: the
        # whole point of the profile.
        regime.text = invoice.snapshot.fiscale.codice_regime

        self._sede(cedente, emittente, "emitter_profile")

        telefono = (emittente.telefono or "").strip()
        email = (emittente.email or "").strip()
        if telefono or email:
            contatti = etree.SubElement(cedente, "Contatti")
            if telefono:
                # FPR12's Telefono is 5-12 characters with no spaces or plus sign
                # allowed by the pattern; strip the presentation characters a user
                # typed rather than refusing a perfectly good number.
                digits = re.sub(r"[^0-9]", "", telefono)[:_TELEFONO_MAX]
                if len(digits) >= 5:
                    node = etree.SubElement(contatti, "Telefono")
                    node.text = digits
            if email:
                self._text(
                    contatti, "Email", email, entity="emitter_profile", field="email",
                    max_length=_EMAIL_MAX,
                )

    def _cessionario(self, header: etree._Element, cliente: PartySnapshot) -> None:
        cessionario = etree.SubElement(header, "CessionarioCommittente")
        anagrafici = etree.SubElement(cessionario, "DatiAnagrafici")
        piva = normalise_fiscal_id(cliente.partita_iva)
        if piva is not None:
            self._id_fiscale(anagrafici, "IdFiscaleIVA", piva, "customer", "partita_iva")
        codice_fiscale = normalise_fiscal_id(cliente.codice_fiscale)
        if codice_fiscale is not None:
            self._text(
                anagrafici, "CodiceFiscale", codice_fiscale, entity="customer",
                field="codice_fiscale",
            )
        self._anagrafica(anagrafici, cliente, "customer")
        self._sede(cessionario, cliente, "customer")

    # ---- body ------------------------------------------------------------------

    def _dati_generali(self, body: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: TipoDocumento, Divisa, Data, Numero, DatiRitenuta*, DatiBollo?,
        DatiCassaPrevidenziale*, ScontoMaggiorazione*, ImportoTotaleDocumento?,
        Arrotondamento?, Causale*, Art73?."""
        generali = etree.SubElement(body, "DatiGenerali")
        documento = etree.SubElement(generali, "DatiGeneraliDocumento")

        tipo = etree.SubElement(documento, "TipoDocumento")
        tipo.text = invoice.tipo_documento
        divisa = etree.SubElement(documento, "Divisa")
        divisa.text = invoice.divisa
        data = etree.SubElement(documento, "Data")
        # A `date`, formatted with `isoformat()`. Never `toISOString()` on an instant:
        # that is what put an invoice issued on 31 December at 23:30 CET into the next
        # fiscal year.
        data.text = self._iso(invoice.data_emissione)
        numero = etree.SubElement(documento, "Numero")
        numero.text = numero_completo(invoice.anno, invoice.numero)

        if invoice.bollo > Decimal("0.00"):
            bollo = etree.SubElement(documento, "DatiBollo")
            virtuale = etree.SubElement(bollo, "BolloVirtuale")
            virtuale.text = BOLLO_VIRTUALE
            importo = etree.SubElement(bollo, "ImportoBollo")
            importo.text = format_amount_2(invoice.bollo)

        totale = etree.SubElement(documento, "ImportoTotaleDocumento")
        # The stamp duty is not part of the total: `DatiBollo` declares that the
        # issuer settled it virtually, and charging it back would need a line with
        # `Natura N1` -- explicitly out of scope.
        totale.text = format_amount_2(invoice.totale)

        if (invoice.causale or "").strip():
            self._text(
                documento, "Causale", invoice.causale or "", entity="invoice",
                field="causale", max_length=_CAUSALE_MAX,
            )

    def _dati_beni_servizi(self, body: etree._Element, invoice: InvoiceForExport) -> None:
        beni = etree.SubElement(body, "DatiBeniServizi")
        for riga in invoice.righe:
            self._dettaglio_linea(beni, riga)
        for group in build_riepilogo(
            [
                ComputedLine(
                    numero_linea=r.numero_linea,
                    descrizione=r.descrizione,
                    quantita=r.quantita,
                    unita_misura=r.unita_misura,
                    prezzo_unitario=r.prezzo_unitario,
                    sconto_percentuale=r.sconto_percentuale,
                    sconto_importo=r.sconto_importo,
                    prezzo_totale=r.prezzo_totale,
                    aliquota_iva=r.aliquota_iva,
                    natura=r.natura,
                    riferimento_normativo=r.riferimento_normativo,
                )
                for r in invoice.righe
            ]
        ):
            self._dati_riepilogo(beni, group)

    def _dettaglio_linea(self, parent: etree._Element, riga) -> None:  # type: ignore[no-untyped-def]
        """Sequence: NumeroLinea, TipoCessionePrestazione?, CodiceArticolo*,
        Descrizione, Quantita?, UnitaMisura?, DataInizioPeriodo?, DataFinePeriodo?,
        PrezzoUnitario, ScontoMaggiorazione*, PrezzoTotale, AliquotaIVA, Ritenuta?,
        Natura?, RiferimentoAmministrazione?, AltriDatiGestionali*.

        `UnitaMisura` comes *after* `Quantita` and *before* `PrezzoUnitario`: getting
        that wrong is a schema-invalid file with every value correct.
        """
        linea = etree.SubElement(parent, "DettaglioLinee")
        numero = etree.SubElement(linea, "NumeroLinea")
        # A real line number per real line. Acme hardcoded 1, quantity 1 and the
        # whole total as the unit price, so the detail of the work never reached the
        # customer.
        numero.text = str(riga.numero_linea)
        self._text(
            linea, "Descrizione", riga.descrizione, entity="invoice_line",
            field="descrizione", max_length=_DESCRIZIONE_MAX,
        )
        quantita = etree.SubElement(linea, "Quantita")
        quantita.text = format_amount_8(riga.quantita)
        if (riga.unita_misura or "").strip():
            self._text(
                linea, "UnitaMisura", riga.unita_misura or "", entity="invoice_line",
                field="unita_misura",
            )
        prezzo = etree.SubElement(linea, "PrezzoUnitario")
        prezzo.text = format_amount_8(riga.prezzo_unitario)
        # `ScontoMaggiorazione` is deliberately not emitted: the discount is already
        # inside `prezzo_totale` (totals.py::line_total), and declaring it twice would
        # make the SdI's own check on PrezzoTotale fail.
        totale = etree.SubElement(linea, "PrezzoTotale")
        totale.text = format_amount_2(riga.prezzo_totale)
        aliquota = etree.SubElement(linea, "AliquotaIVA")
        aliquota.text = format_rate(riga.aliquota_iva)
        if riga.natura:
            natura = etree.SubElement(linea, "Natura")
            natura.text = riga.natura

    def _dati_riepilogo(self, parent: etree._Element, group) -> None:  # type: ignore[no-untyped-def]
        """Sequence: AliquotaIVA, Natura?, SpeseAccessorie?, Arrotondamento?,
        ImponibileImporto, Imposta, EsigibilitaIVA?, RiferimentoNormativo?."""
        riepilogo = etree.SubElement(parent, "DatiRiepilogo")
        aliquota = etree.SubElement(riepilogo, "AliquotaIVA")
        aliquota.text = format_rate(group.aliquota_iva)
        if group.natura:
            natura = etree.SubElement(riepilogo, "Natura")
            natura.text = group.natura
        imponibile = etree.SubElement(riepilogo, "ImponibileImporto")
        imponibile.text = format_amount_2(group.imponibile)
        imposta = etree.SubElement(riepilogo, "Imposta")
        imposta.text = format_amount_2(group.imposta)
        esigibilita = etree.SubElement(riepilogo, "EsigibilitaIVA")
        esigibilita.text = ESIGIBILITA_IVA
        if group.natura and group.riferimento_normativo:
            # A real normative reference, from the profile. Acme sent the *description
            # of the code* ("N2.2 (non soggette - altri casi)") in this field.
            self._text(
                riepilogo,
                "RiferimentoNormativo",
                group.riferimento_normativo,
                entity="fiscal_profile",
                field="riferimento_normativo",
                max_length=_RIFERIMENTO_NORMATIVO_MAX,
            )

    def _dati_pagamento(self, body: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: CondizioniPagamento, DettaglioPagamento+; and inside it
        Beneficiario?, ModalitaPagamento, DataRiferimentoTerminiPagamento?,
        GiorniTerminiPagamento?, DataScadenzaPagamento?, ImportoPagamento, ..., IBAN?."""
        fiscale = invoice.snapshot.fiscale
        pagamento = etree.SubElement(body, "DatiPagamento")
        self._text(
            pagamento,
            "CondizioniPagamento",
            fiscale.condizioni_pagamento,
            entity="fiscal_profile",
            field="condizioni_pagamento",
            pattern=_TIPO_PAGAMENTO_RE,
        )
        dettaglio = etree.SubElement(pagamento, "DettaglioPagamento")
        self._text(
            dettaglio,
            "ModalitaPagamento",
            fiscale.modalita_pagamento,
            entity="fiscal_profile",
            field="modalita_pagamento",
            pattern=_TIPO_PAGAMENTO_RE,
        )
        if invoice.data_scadenza is not None:
            scadenza = etree.SubElement(dettaglio, "DataScadenzaPagamento")
            scadenza.text = self._iso(invoice.data_scadenza)
        importo = etree.SubElement(dettaglio, "ImportoPagamento")
        importo.text = format_amount_2(invoice.totale)
        if (fiscale.iban or "").strip():
            self._text(
                dettaglio,
                "IBAN",
                (fiscale.iban or "").strip().replace(" ", ""),
                entity="fiscal_profile",
                field="iban",
                pattern=_IBAN_RE,
            )

    @staticmethod
    def _iso(value: date) -> str:
        """A `date`'s own ISO form.

        Deliberately not a timestamp conversion. Acme's `formatIsoDate` called
        `toISOString()`, i.e. projected an instant through UTC: an invoice created on
        31 December at 23:30 CET came out dated 1 January, so its fiscal year was
        wrong on an immutable document. There is no instant here to get wrong.
        """
        return value.isoformat()


__all__ = [
    "FPR12_NAMESPACE",
    "FORMATO_TRASMISSIONE",
    "NSMAP",
    "FatturaPAExporter",
    "check_party_exportable",
    "check_recipient_routing",
    "normalise_fiscal_id",
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_fatturapa.py -v`
Expected: PASS. If a case fails with a libxml2 sequence error, read the message — `assert_valid` prints libxml2's own error log naming the element and the expected successor, which is the whole reason it exists. Fix the element order in the implementation, never the assertion.

Run: `uv run pytest packages/core/tests/test_architecture.py -v`
Expected: PASS — `lxml` is now declared in `packages/core/pyproject.toml`, so the allowlist admits it with no edit to the test.

- [ ] **Step 7: Commit**

```bash
git add packages/core/pyproject.toml uv.lock packages/core/src/pigrocrm/core/invoices/fatturapa.py packages/core/tests/fpr12/ packages/core/tests/test_invoice_fatturapa.py
git commit -m "feat(invoices): FatturaPA FPR12 exporter, validated against the official schema"
```

---

# Phase 2 — Database and services

### Task 7: `fiscal_profile`

**Files:**
- Create: `packages/core/src/pigrocrm/core/fiscal/models.py`
- Modify: `packages/core/src/pigrocrm/core/fiscal/schemas.py` (add `FiscalProfileUpsert`, `FiscalProfileRead`)
- Create: `packages/core/src/pigrocrm/core/fiscal/repository.py`
- Create: `packages/core/src/pigrocrm/core/fiscal/service.py`
- Create: `packages/core/migrations/versions/0004_fiscal_profile.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Modify: `packages/core/tests/test_migrations.py` (two `revision == "0003"` assertions, the table set)
- Test: `packages/core/tests/test_fiscal_profile.py`

**Interfaces:**
- Consumes: `pigrocrm.core.fiscal.schemas.{FiscalSnapshot, CODICE_REGIME_RE, DEFAULT_*}`; `pigrocrm.core.activities.service.ActivityService`; `pigrocrm.core.actor.Actor`.
- Produces:
  - `FiscalProfile` ORM model, table `fiscal_profile`
  - `class FiscalProfileUpsert(BaseModel)`, `class FiscalProfileRead(BaseModel)`
  - `class FiscalProfileRepository` with `get(self) -> FiscalProfile | None`, `add(self, profile: FiscalProfile) -> FiscalProfile`
  - `class FiscalProfileService` with `get(self, actor: Actor) -> FiscalProfileRead`, `upsert(self, data: FiscalProfileUpsert, actor: Actor) -> FiscalProfileRead`, `snapshot(self) -> FiscalSnapshot`, `describe(self, actor: Actor) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_fiscal_profile.py`:

```python
"""One row, an admin-only writer, and an activity on every change.

R5 (no audit trail for configuration) stays open in general and is closed here:
changing fiscal regime without a trace is a different order of severity from renaming
a pipeline stage, and the timeline is also what reconstructs the history of regimes
without a `valido_da`/`valido_a` column -- which spec 7.1 considered and rejected
because spec 6.2 forbids back-dating past the current year, so no emission ever needs
a previous period's parameters.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.fiscal.models import FiscalProfile
from pigrocrm.core.fiscal.repository import FiscalProfileRepository
from pigrocrm.core.fiscal.schemas import (
    DEFAULT_IMPORTO_BOLLO,
    DEFAULT_RIFERIMENTO_NORMATIVO,
    DEFAULT_SOGLIA_BOLLO,
    FiscalProfileUpsert,
)
from pigrocrm.core.fiscal.service import FiscalProfileService

ADMIN = Actor(id=None, type="system", role="admin")
COLLABORATORE = Actor(id=None, type="user", role="collaboratore")


def _payload(**overrides: object) -> FiscalProfileUpsert:
    base: dict[str, object] = {
        "codice_regime": "RF19",
        "aliquota_iva_default": Decimal("0.00"),
        "natura_default": "N2.2",
        "riferimento_normativo": DEFAULT_RIFERIMENTO_NORMATIVO,
        "applica_bollo": True,
        "soglia_bollo": DEFAULT_SOGLIA_BOLLO,
        "importo_bollo": DEFAULT_IMPORTO_BOLLO,
        "condizioni_pagamento": "TP02",
        "modalita_pagamento": "MP05",
        "giorni_scadenza": 30,
        "iban": "IT60X0542811101000000123456",
    }
    base.update(overrides)
    return FiscalProfileUpsert(**base)  # type: ignore[arg-type]


def test_reading_a_profile_that_does_not_exist_is_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        FiscalProfileService(db_session).get(ADMIN)


def test_the_defaults_are_the_values_of_law(db_session: Session) -> None:
    profile = FiscalProfileService(db_session).upsert(
        FiscalProfileUpsert(codice_regime="RF19"), ADMIN
    )
    assert profile.soglia_bollo == Decimal("77.47")
    assert profile.importo_bollo == Decimal("2.00")
    assert profile.applica_bollo is True
    assert profile.condizioni_pagamento == "TP02"
    assert profile.modalita_pagamento == "MP05"
    assert profile.aliquota_iva_default == Decimal("0.00")


def test_a_second_upsert_updates_the_same_row(db_session: Session) -> None:
    service = FiscalProfileService(db_session)
    first = service.upsert(_payload(), ADMIN)
    second = service.upsert(_payload(giorni_scadenza=60), ADMIN)
    assert first.id == second.id
    assert second.giorni_scadenza == 60


def test_only_an_admin_may_write(db_session: Session) -> None:
    with pytest.raises(PermissionDenied):
        FiscalProfileService(db_session).upsert(_payload(), COLLABORATORE)


def test_every_upsert_records_an_activity(db_session: Session) -> None:
    service = FiscalProfileService(db_session)
    profile = service.upsert(_payload(), ADMIN)
    service.upsert(_payload(codice_regime="RF01", natura_default=None, aliquota_iva_default=Decimal("22.00"), riferimento_normativo=None), ADMIN)
    entries = ActivityService(db_session).timeline("fiscal_profile", profile.id)
    assert [entry.kind for entry in entries] == ["updated", "updated"]
    assert "codice_regime" in entries[0].payload["changed"]


def test_an_unimplemented_regime_is_refused_at_the_service_boundary(
    db_session: Session,
) -> None:
    with pytest.raises(ValidationFailed) as caught:
        FiscalProfileService(db_session).upsert(_payload(codice_regime="RF07"), ADMIN)
    assert caught.value.details["field"] == "codice_regime"


def test_a_regime_code_with_a_trailing_newline_never_reaches_the_column(
    db_session: Session,
) -> None:
    """String(4) plus `.fullmatch`: `re.match` with `$` would accept "RF19\\n" and
    hand five characters to a four-character column as a raw DataError."""
    with pytest.raises(ValidationFailed):
        FiscalProfileService(db_session).upsert(_payload(codice_regime="RF19\n"), ADMIN)


def test_an_iban_longer_than_the_column_is_refused_by_pydantic(db_session: Session) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _payload(iban="IT" + "0" * 40)


def test_a_forfettario_profile_must_declare_a_natura(db_session: Session) -> None:
    """Under a zero-rate regime the summary group needs a Natura, and a profile with
    neither a natura nor a non-zero default rate can only produce invoices the SdI
    rejects. Caught at configuration time, not at emission time."""
    with pytest.raises(ValidationFailed) as caught:
        FiscalProfileService(db_session).upsert(
            _payload(natura_default=None), ADMIN
        )
    assert caught.value.details["field"] == "natura_default"


def test_the_snapshot_is_the_profile_without_its_identity(db_session: Session) -> None:
    service = FiscalProfileService(db_session)
    service.upsert(_payload(), ADMIN)
    snapshot = service.snapshot()
    assert snapshot.codice_regime == "RF19"
    assert snapshot.giorni_scadenza == 30
    assert not hasattr(snapshot, "id")


def test_upsert_turns_a_true_insert_race_into_a_clean_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `repo.get()` pre-check cannot cover two concurrent first-time saves: both
    see no row, both insert, and only the `singleton` unique constraint stops the
    second. Forced deterministically -- a savepoint-backed test session cannot produce
    real thread concurrency -- the same technique `test_emitter.py` already uses."""
    service = FiscalProfileService(db_session)
    service.upsert(_payload(), ADMIN)
    monkeypatch.setattr(FiscalProfileRepository, "get", lambda self: None)
    with pytest.raises(Conflict):
        service.upsert(_payload(), ADMIN)


def test_the_singleton_column_is_the_database_guarantee(db_session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    db_session.add(FiscalProfile(codice_regime="RF19"))
    db_session.flush()
    db_session.add(FiscalProfile(codice_regime="RF01"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_fiscal_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.fiscal.models'`

- [ ] **Step 3: Implement the model**

`packages/core/src/pigrocrm/core/fiscal/models.py`:

```python
from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class FiscalProfile(Base, PrimaryKeyMixin, TimestampMixin):
    """The fiscal parameters of the one issuer. One row, ever.

    `emitter_profile` (slice 2) holds the issuer's *identity*; this holds the numbers
    and codes the SdI validates. They are not duplicates, and
    `emitter_profile.regime_fiscale` -- a `String(200)` of free text, already shipped
    and already read by `render/assets/header.typ.template` -- keeps its own meaning as
    a human-readable caption on the PDF. `codice_regime` here is the machine value,
    `String(4)`, and the only input to the XML's `RegimeFiscale`.

    Not historicised, and the alternative was considered rather than overlooked: a
    regime changes on 1 January, but spec 6.2 forbids back-dating an invoice past the
    start of the current year, so no emission ever needs a previous period's
    parameters. A `valido_da`/`valido_a` pair would only answer a question the
    per-invoice `snapshot` already answers, and answers better.

    Single-row is enforced by the database, exactly as `EmitterProfile` does it:
    `singleton` is `unique=True` and always `True`, so a second insert fails on the
    constraint. A "select then insert" pre-check alone would let two concurrent
    first-time saves both pass.
    """

    __tablename__ = "fiscal_profile"

    singleton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, unique=True)
    # RF01..RF19, as FPR12's RegimeFiscaleType enumerates them.
    codice_regime: Mapped[str] = mapped_column(String(4), nullable=False)
    aliquota_iva_default: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00")
    )
    natura_default: Mapped[str | None] = mapped_column(String(4), default=None)
    riferimento_normativo: Mapped[str | None] = mapped_column(Text, default=None)
    # Values of law, not preferences: configurable because the law has changed them.
    applica_bollo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    soglia_bollo: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("77.47")
    )
    importo_bollo: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("2.00")
    )
    condizioni_pagamento: Mapped[str] = mapped_column(String(4), nullable=False, default="TP02")
    modalita_pagamento: Mapped[str] = mapped_column(String(4), nullable=False, default="MP05")
    giorni_scadenza: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    iban: Mapped[str | None] = mapped_column(String(34), default=None)
```

- [ ] **Step 4: Add the API shapes**

Append to `packages/core/src/pigrocrm/core/fiscal/schemas.py`:

```python
class FiscalProfileUpsert(BaseModel):
    """One shape for create and update: there is only ever one row, so "create" and
    "update" are the same operation with the same required fields -- the same decision
    `EmitterProfileUpsert` already made.

    `codice_regime` carries `max_length` because the column is `String(4)` and the
    service's own `.fullmatch` check is *not* a length check on its own for a value
    that fails the pattern for another reason. Every `Numeric` carries
    `max_digits`/`decimal_places` mirroring its column, and `giorni_scadenza` carries
    a bound, because none of the three has a service-level range check that would make
    a schema bound redundant.
    """

    model_config = ConfigDict(extra="forbid")

    codice_regime: SafeStr = Field(max_length=CODICE_REGIME_MAX_LENGTH)
    aliquota_iva_default: Decimal = Field(
        default=Decimal("0.00"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES
    )
    natura_default: SafeStr | None = Field(default="N2.2", max_length=NATURA_MAX_LENGTH)
    riferimento_normativo: SafeStr | None = DEFAULT_RIFERIMENTO_NORMATIVO
    applica_bollo: bool = True
    soglia_bollo: Decimal = Field(
        default=DEFAULT_SOGLIA_BOLLO,
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
    )
    importo_bollo: Decimal = Field(
        default=DEFAULT_IMPORTO_BOLLO,
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
    )
    condizioni_pagamento: SafeStr = Field(
        default="TP02", max_length=CONDIZIONI_PAGAMENTO_MAX_LENGTH
    )
    modalita_pagamento: SafeStr = Field(default="MP05", max_length=MODALITA_PAGAMENTO_MAX_LENGTH)
    giorni_scadenza: int = Field(default=30, ge=GIORNI_SCADENZA_MIN, le=GIORNI_SCADENZA_MAX)
    iban: SafeStr | None = Field(default=None, max_length=IBAN_MAX_LENGTH)


class FiscalProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    codice_regime: str
    aliquota_iva_default: Decimal
    natura_default: str | None
    riferimento_normativo: str | None
    applica_bollo: bool
    soglia_bollo: Decimal
    importo_bollo: Decimal
    condizioni_pagamento: str
    modalita_pagamento: str
    giorni_scadenza: int
    iban: str | None
    created_at: datetime
    updated_at: datetime
```

and extend that file's imports and `__all__`:

```python
from datetime import datetime
from uuid import UUID
```

```python
__all__ = [
    "CODICE_REGIME_RE",
    "DEFAULT_IMPORTO_BOLLO",
    "DEFAULT_RIFERIMENTO_NORMATIVO",
    "DEFAULT_SOGLIA_BOLLO",
    "FiscalProfileRead",
    "FiscalProfileUpsert",
    "FiscalSnapshot",
]
```

- [ ] **Step 5: Implement the repository and the service**

`packages/core/src/pigrocrm/core/fiscal/repository.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.fiscal.models import FiscalProfile


class FiscalProfileRepository:
    """A repository never commits (project rule): every method here reads or flushes,
    and the surrounding service method is the one transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> FiscalProfile | None:
        return self.session.execute(select(FiscalProfile)).scalars().first()

    def add(self, profile: FiscalProfile) -> FiscalProfile:
        self.session.add(profile)
        self.session.flush()
        return profile
```

`packages/core/src/pigrocrm/core/fiscal/service.py`:

```python
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.fiscal.models import FiscalProfile
from pigrocrm.core.fiscal.regime import resolve_regime
from pigrocrm.core.fiscal.repository import FiscalProfileRepository
from pigrocrm.core.fiscal.schemas import (
    FiscalProfileRead,
    FiscalProfileUpsert,
    FiscalSnapshot,
)

ENTITY = "fiscal_profile"
ZERO = Decimal("0.00")


class FiscalProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = FiscalProfileRepository(session)
        self.activities = ActivityService(session)

    def get(self, actor: Actor) -> FiscalProfileRead:
        return FiscalProfileRead.model_validate(self._require())

    def snapshot(self) -> FiscalSnapshot:
        """The parameters as a frozen value object, ready to be written into
        `invoices.snapshot`. No `actor`: it takes no decision and returns no identity,
        it is the read `InvoiceService.issue` performs on the caller's behalf."""
        profile = self._require()
        return FiscalSnapshot(
            codice_regime=profile.codice_regime,
            aliquota_iva_default=profile.aliquota_iva_default,
            natura_default=profile.natura_default,
            riferimento_normativo=profile.riferimento_normativo,
            applica_bollo=profile.applica_bollo,
            soglia_bollo=profile.soglia_bollo,
            importo_bollo=profile.importo_bollo,
            condizioni_pagamento=profile.condizioni_pagamento,
            modalita_pagamento=profile.modalita_pagamento,
            giorni_scadenza=profile.giorni_scadenza,
            iban=profile.iban,
        )

    def describe(self, actor: Actor) -> dict[str, Any]:
        """What `describe_fiscal_profile` returns over MCP: the parameters an agent
        needs to compose a proforma the human will actually be able to issue, with no
        identity or timestamps in it."""
        profile = self.get(actor)
        return profile.model_dump(mode="json", exclude={"id", "created_at", "updated_at"})

    def upsert(self, data: FiscalProfileUpsert, actor: Actor) -> FiscalProfileRead:
        """Create-or-update the one row, admin only.

        `repo.add` sits **inside** the `try`, not before it: it is the only statement
        that can violate the `singleton` constraint, and leaving it outside would let
        two concurrent first-time saves poison the session with a raw `IntegrityError`
        instead of surfacing a clean `Conflict`. Same shape, same reason, as
        `EmitterProfileService.upsert`.
        """
        actor.require_admin("update_fiscal_profile")
        payload = data.model_dump()
        self._check(payload)

        profile = self.repo.get()
        try:
            if profile is None:
                profile = self.repo.add(FiscalProfile(**payload))
            else:
                for key, value in payload.items():
                    setattr(profile, key, value)
            # R5 is closed for this table: changing regime without a trace is a
            # different order of severity from renaming a pipeline stage, and the
            # timeline is also what reconstructs the history of regimes without a
            # validity column. Recorded last, so it can never survive a rollback.
            self.activities.record(
                ENTITY, profile.id, "updated", actor, {"changed": sorted(payload)}
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise Conflict(ENTITY, "il profilo fiscale esiste gia'") from exc
        return FiscalProfileRead.model_validate(profile)

    @staticmethod
    def _check(payload: dict[str, Any]) -> None:
        # `resolve_regime` does both checks: the `RF01`-`RF19` shape, with
        # `.fullmatch` so "RF19\n" cannot reach the String(4) column, and whether a
        # strategy exists. Raising here means an unimplemented regime is refused at
        # configuration time rather than at the first emission.
        resolve_regime(payload["codice_regime"])
        if payload["aliquota_iva_default"] == ZERO and not payload.get("natura_default"):
            raise ValidationFailed(
                ENTITY,
                "natura_default",
                "un'aliquota di default a zero richiede una natura, altrimenti ogni "
                "riepilogo prodotto verrebbe scartato dallo SdI",
                expected="una natura, per esempio N2.2",
            )
        if payload["aliquota_iva_default"] != ZERO and payload.get("natura_default"):
            raise ValidationFailed(
                ENTITY,
                "natura_default",
                "una natura con un'aliquota di default diversa da zero viene scartata "
                "dallo SdI",
                expected="nessuna natura",
            )
        if payload["applica_bollo"] and payload["importo_bollo"] <= ZERO:
            raise ValidationFailed(
                ENTITY,
                "importo_bollo",
                "il bollo e' attivo ma il suo importo non e' positivo",
                expected="un importo maggiore di zero",
            )

    def _require(self) -> FiscalProfile:
        profile = self.repo.get()
        if profile is None:
            raise NotFound(ENTITY, "singleton")
        return profile
```

- [ ] **Step 6: Write the migration**

`packages/core/migrations/versions/0004_fiscal_profile.py`:

```python
"""fiscal profile

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fiscal_profile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("singleton", sa.Boolean(), nullable=False),
        sa.Column("codice_regime", sa.String(length=4), nullable=False),
        sa.Column("aliquota_iva_default", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("natura_default", sa.String(length=4), nullable=True),
        sa.Column("riferimento_normativo", sa.Text(), nullable=True),
        sa.Column("applica_bollo", sa.Boolean(), nullable=False),
        sa.Column("soglia_bollo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("importo_bollo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("condizioni_pagamento", sa.String(length=4), nullable=False),
        sa.Column("modalita_pagamento", sa.String(length=4), nullable=False),
        sa.Column("giorni_scadenza", sa.Integer(), nullable=False),
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("singleton", name="uq_fiscal_profile_singleton"),
    )


def downgrade() -> None:
    op.drop_table("fiscal_profile")
```

- [ ] **Step 7: Register the model and update the migration test**

In `packages/core/src/pigrocrm/core/models_registry.py`, add in alphabetical position:

```python
from pigrocrm.core.fiscal.models import FiscalProfile  # noqa: F401
```

In `packages/core/tests/test_migrations.py`, add `"fiscal_profile"` to the `expected` set in `test_every_table_the_slice_needs_exists`, and change **both** occurrences of `assert revision == "0003"` to `assert revision == "0004"`.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_fiscal_profile.py packages/core/tests/test_migrations.py packages/core/tests/test_module_imports.py -v`
Expected: PASS, including `test_migrations_produce_exactly_the_models_schema` — a `compare_metadata` diff here means the migration and the model disagree on a width or a nullability, and the message names the column.

- [ ] **Step 9: Commit**

```bash
git add packages/core/src/pigrocrm/core/fiscal/ packages/core/src/pigrocrm/core/models_registry.py packages/core/migrations/versions/0004_fiscal_profile.py packages/core/tests/test_fiscal_profile.py packages/core/tests/test_migrations.py
git commit -m "feat(fiscal): a single-row fiscal profile with an audited upsert"
```

---
### Task 8: `invoices`, `invoice_lines`, `invoice_counters` — and the constraints that do the work

**Files:**
- Create: `packages/core/src/pigrocrm/core/invoices/models.py`
- Create: `packages/core/migrations/versions/0005_invoices.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Modify: `packages/core/tests/test_migrations.py`
- Test: `packages/core/tests/test_invoice_models.py`

**Interfaces:**
- Consumes: `pigrocrm.core.db.{Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin}`; `pigrocrm.core.invoices.schemas.ALLOWED_STATI` (for the doc comment only — the SQL is written out).
- Produces:
  - `Invoice` (table `invoices`), `InvoiceLine` (table `invoice_lines`), `InvoiceCounter` (table `invoice_counters`)
  - `PROFORMA_SEQUENCE_NAME: str` (`"proforma_riferimento_seq"`)
  - Constraint names, referenced by later tasks: `ck_invoices_tipo_stato`, `ck_invoices_anno_numero_together`, `ck_invoices_numero_requires_issued_fattura`, `ck_invoices_numero_positive`, `ck_invoices_riferimento_only_on_proforma`, `ck_invoices_snapshot_together`, `ck_invoices_annullamento_complete`, `ck_invoices_incasso_requires_state`, `ck_invoices_no_delete_once_consumed`, `uq_invoices_anno_numero`, `ix_invoices_custom_fields`, `uq_invoice_lines_invoice_numero`, `ck_invoice_lines_natura_agrees_with_rate`, `ck_invoice_lines_numero_positive`, `ck_invoice_counters_non_negative`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_invoice_models.py`:

```python
"""The constraints, exercised with raw SQL rather than through the service.

Spec 14.4 is explicit that immutability must be imposed by the database and not by
the service, so every check here bypasses `InvoiceService` entirely: an invariant that
only the service defends is an invariant any other write path -- an importer, a fix-up
script, a psql session -- can walk straight past.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.invoices.models import Invoice, InvoiceCounter, InvoiceLine


@pytest.fixture
def customer_id(db_session: Session) -> UUID:
    customer = Customer(ragione_sociale="Acme S.r.l.", nazione="IT")
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _draft(customer_id: UUID, **overrides: object) -> Invoice:
    payload: dict[str, object] = {
        "customer_id": customer_id,
        "tipo": "fattura",
        "stato": "bozza",
        "tipo_documento": "TD01",
        "divisa": "EUR",
        "imponibile": Decimal("0.00"),
        "imposta": Decimal("0.00"),
        "bollo": Decimal("0.00"),
        "totale": Decimal("0.00"),
        "stato_pagamento": "da_incassare",
        "custom_fields": {},
    }
    payload.update(overrides)
    return Invoice(**payload)


def _add(db_session: Session, invoice: Invoice) -> None:
    db_session.add(invoice)
    db_session.flush()


def _refuses(db_session: Session, invoice: Invoice, constraint: str) -> None:
    db_session.add(invoice)
    with pytest.raises(IntegrityError) as caught:
        db_session.flush()
    assert constraint in str(caught.value)
    db_session.rollback()


# --- (tipo, stato): two state machines in one column -------------------------------


@pytest.mark.parametrize("stato", ["bozza", "emessa", "annullata"])
def test_a_fattura_may_hold_its_own_three_states(
    db_session: Session, customer_id: UUID, stato: str
) -> None:
    extra: dict[str, object] = {}
    if stato != "bozza":
        extra = {"anno": 2026, "numero": 1, "data_emissione": date(2026, 1, 5)}
    if stato == "annullata":
        extra |= {"annullata_il": date(2026, 2, 1), "motivo_annullamento": "importo errato"}
    _add(db_session, _draft(customer_id, stato=stato, **extra))


@pytest.mark.parametrize("stato", ["confermata", "consumata"])
def test_a_fattura_may_not_hold_a_proforma_state(
    db_session: Session, customer_id: UUID, stato: str
) -> None:
    _refuses(db_session, _draft(customer_id, stato=stato), "ck_invoices_tipo_stato")


def test_a_proforma_may_not_hold_the_emessa_state(
    db_session: Session, customer_id: UUID
) -> None:
    _refuses(
        db_session,
        _draft(customer_id, tipo="proforma", stato="emessa"),
        "ck_invoices_tipo_stato",
    )


def test_an_unknown_tipo_is_refused(db_session: Session, customer_id: UUID) -> None:
    _refuses(db_session, _draft(customer_id, tipo="nota_credito"), "ck_invoices_tipo_stato")


# --- the number ---------------------------------------------------------------------


def test_a_number_without_a_year_is_refused(db_session: Session, customer_id: UUID) -> None:
    _refuses(
        db_session,
        _draft(customer_id, stato="emessa", numero=1, data_emissione=date(2026, 1, 5)),
        "ck_invoices_anno_numero_together",
    )


def test_a_draft_may_not_carry_a_number(db_session: Session, customer_id: UUID) -> None:
    """A draft has no number, so "a failed creation burned a number" is impossible by
    construction rather than by care."""
    _refuses(
        db_session,
        _draft(customer_id, anno=2026, numero=1),
        "ck_invoices_numero_requires_issued_fattura",
    )


def test_a_proforma_may_not_carry_a_number(db_session: Session, customer_id: UUID) -> None:
    _refuses(
        db_session,
        _draft(customer_id, tipo="proforma", stato="confermata", anno=2026, numero=1),
        "ck_invoices_numero_requires_issued_fattura",
    )


def test_a_number_must_be_positive(db_session: Session, customer_id: UUID) -> None:
    _refuses(
        db_session,
        _draft(customer_id, stato="emessa", anno=2026, numero=0, data_emissione=date(2026, 1, 5)),
        "ck_invoices_numero_positive",
    )


def test_the_same_year_and_number_cannot_exist_twice(
    db_session: Session, customer_id: UUID
) -> None:
    """The partial unique index is a net, not the mechanism: the row lock in
    `InvoiceService.issue` is the primary defence, and this is what makes a failure of
    that defence observable rather than a silent duplicate."""
    _add(
        db_session,
        _draft(customer_id, stato="emessa", anno=2026, numero=1, data_emissione=date(2026, 1, 5)),
    )
    _refuses(
        db_session,
        _draft(customer_id, stato="emessa", anno=2026, numero=1, data_emissione=date(2026, 1, 6)),
        "uq_invoices_anno_numero",
    )


def test_two_drafts_do_not_collide_on_a_null_number(
    db_session: Session, customer_id: UUID
) -> None:
    """`WHERE numero IS NOT NULL`: without the partial predicate every draft would be
    a duplicate of every other."""
    _add(db_session, _draft(customer_id))
    _add(db_session, _draft(customer_id))


def test_the_same_number_may_exist_in_two_different_years(
    db_session: Session, customer_id: UUID
) -> None:
    _add(
        db_session,
        _draft(customer_id, stato="emessa", anno=2026, numero=1, data_emissione=date(2026, 1, 5)),
    )
    _add(
        db_session,
        _draft(customer_id, stato="emessa", anno=2027, numero=1, data_emissione=date(2027, 1, 5)),
    )


def test_a_fiscal_reference_belongs_only_to_a_proforma(
    db_session: Session, customer_id: UUID
) -> None:
    _refuses(
        db_session,
        _draft(customer_id, riferimento="PROV-2026-0001"),
        "ck_invoices_riferimento_only_on_proforma",
    )


# --- immutability: spec 14.4 -------------------------------------------------------


def test_soft_deleting_an_issued_invoice_fails_even_in_raw_sql(
    db_session: Session, customer_id: UUID
) -> None:
    """The point of the check: `UPDATE invoices SET deleted_at = now()` is refused by
    Postgres, not by Python. A numbered row is a page in a register."""
    invoice = _draft(
        customer_id, stato="emessa", anno=2026, numero=1, data_emissione=date(2026, 1, 5)
    )
    _add(db_session, invoice)
    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text("UPDATE invoices SET deleted_at = now() WHERE id = :id"), {"id": invoice.id}
        )
    assert "ck_invoices_no_delete_once_consumed" in str(caught.value)
    db_session.rollback()


def test_soft_deleting_a_consumed_proforma_also_fails(
    db_session: Session, customer_id: UUID
) -> None:
    """A consumed proforma is the antecedent of an immutable document, so it is not
    deletable either -- even though it never held a number."""
    proforma = _draft(customer_id, tipo="proforma", stato="consumata")
    _add(db_session, proforma)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE invoices SET deleted_at = now() WHERE id = :id"), {"id": proforma.id}
        )
    db_session.rollback()


def test_soft_deleting_a_draft_is_allowed(db_session: Session, customer_id: UUID) -> None:
    draft = _draft(customer_id)
    _add(db_session, draft)
    db_session.execute(
        text("UPDATE invoices SET deleted_at = now() WHERE id = :id"), {"id": draft.id}
    )
    db_session.flush()


def test_an_annulment_needs_both_a_date_and_a_reason(
    db_session: Session, customer_id: UUID
) -> None:
    _refuses(
        db_session,
        _draft(
            customer_id,
            stato="annullata",
            anno=2026,
            numero=1,
            data_emissione=date(2026, 1, 5),
            annullata_il=date(2026, 2, 1),
        ),
        "ck_invoices_annullamento_complete",
    )


def test_an_annulment_date_on_a_live_invoice_is_refused(
    db_session: Session, customer_id: UUID
) -> None:
    _refuses(
        db_session,
        _draft(
            customer_id,
            stato="emessa",
            anno=2026,
            numero=1,
            data_emissione=date(2026, 1, 5),
            annullata_il=date(2026, 2, 1),
            motivo_annullamento="ripensamento",
        ),
        "ck_invoices_annullamento_complete",
    )


def test_a_collection_date_requires_the_collected_state(
    db_session: Session, customer_id: UUID
) -> None:
    _refuses(
        db_session,
        _draft(customer_id, data_incasso=date(2026, 3, 1)),
        "ck_invoices_incasso_requires_state",
    )


def test_a_snapshot_and_its_version_travel_together(
    db_session: Session, customer_id: UUID
) -> None:
    _refuses(
        db_session,
        _draft(customer_id, snapshot={"versione": 1}),
        "ck_invoices_snapshot_together",
    )


# --- lines --------------------------------------------------------------------------


def _line(invoice_id: UUID, **overrides: object) -> InvoiceLine:
    payload: dict[str, object] = {
        "invoice_id": invoice_id,
        "numero_linea": 1,
        "descrizione": "Consulenza",
        "quantita": Decimal("1.000000"),
        "prezzo_unitario": Decimal("100.000000"),
        "prezzo_totale": Decimal("100.00"),
        "aliquota_iva": Decimal("0.00"),
        "natura": "N2.2",
    }
    payload.update(overrides)
    return InvoiceLine(**payload)


def test_a_zero_rate_line_must_carry_a_natura(db_session: Session, customer_id: UUID) -> None:
    """The two SdI checks the spec names as a pair, as one table constraint: the
    invalid combination is not storable, therefore not exportable. Defending the
    invariant in the generator would leave it reachable from every other write path."""
    invoice = _draft(customer_id)
    _add(db_session, invoice)
    _refuses(
        db_session,
        _line(invoice.id, natura=None),
        "ck_invoice_lines_natura_agrees_with_rate",
    )


def test_a_non_zero_rate_line_must_not_carry_a_natura(
    db_session: Session, customer_id: UUID
) -> None:
    invoice = _draft(customer_id)
    _add(db_session, invoice)
    _refuses(
        db_session,
        _line(invoice.id, aliquota_iva=Decimal("22.00"), natura="N2.2"),
        "ck_invoice_lines_natura_agrees_with_rate",
    )


def test_a_non_zero_rate_line_with_no_natura_is_accepted(
    db_session: Session, customer_id: UUID
) -> None:
    invoice = _draft(customer_id)
    _add(db_session, invoice)
    _add(db_session, _line(invoice.id, aliquota_iva=Decimal("22.00"), natura=None))


def test_two_lines_cannot_share_a_number_on_one_invoice(
    db_session: Session, customer_id: UUID
) -> None:
    invoice = _draft(customer_id)
    _add(db_session, invoice)
    _add(db_session, _line(invoice.id))
    _refuses(db_session, _line(invoice.id), "uq_invoice_lines_invoice_numero")


def test_a_line_number_starts_at_one(db_session: Session, customer_id: UUID) -> None:
    invoice = _draft(customer_id)
    _add(db_session, invoice)
    _refuses(db_session, _line(invoice.id, numero_linea=0), "ck_invoice_lines_numero_positive")


def test_a_unit_price_keeps_six_decimals_in_the_column(
    db_session: Session, customer_id: UUID
) -> None:
    """`Numeric(12, 6)` is the deliberate extension of the money convention: three
    hours at 33,333333 EUR/h is not expressible at two decimals, and the user would
    otherwise be forced to write a total that is not the product of what they
    declared."""
    invoice = _draft(customer_id)
    _add(db_session, invoice)
    line = _line(invoice.id, prezzo_unitario=Decimal("33.333333"))
    _add(db_session, line)
    db_session.expire(line)
    assert line.prezzo_unitario == Decimal("33.333333")


# --- the counter --------------------------------------------------------------------


def test_the_counter_is_keyed_by_year(db_session: Session) -> None:
    db_session.add(InvoiceCounter(anno=2026, ultimo_numero=0))
    db_session.flush()
    db_session.add(InvoiceCounter(anno=2026, ultimo_numero=5))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_the_counter_cannot_go_negative(db_session: Session) -> None:
    db_session.add(InvoiceCounter(anno=2026, ultimo_numero=-1))
    with pytest.raises(IntegrityError) as caught:
        db_session.flush()
    assert "ck_invoice_counters_non_negative" in str(caught.value)
    db_session.rollback()


def test_the_proforma_sequence_exists_and_never_repeats(db_session: Session) -> None:
    """A `SEQUENCE` is the right tool *here* and the wrong one for the fiscal number,
    for the same property: `nextval()` does not roll back. On a proforma a gap means
    nothing, and in exchange the counter serialises nobody."""
    first = db_session.execute(text("SELECT nextval('proforma_riferimento_seq')")).scalar_one()
    second = db_session.execute(text("SELECT nextval('proforma_riferimento_seq')")).scalar_one()
    assert second == first + 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.invoices.models'`

- [ ] **Step 3: Implement the models**

`packages/core/src/pigrocrm/core/invoices/models.py`:

```python
"""The three tables, and the constraints that carry the invariants.

Spec 14.4 asks for immutability "imposed by the database, not by the service", and
that is the organising idea of this file: the legal `(tipo, stato)` pairs, the
agreement between a zero rate and a `Natura`, the impossibility of a numbered row
carrying a `deleted_at`, and the uniqueness of `(anno, numero)` are all table
constraints. An invariant only the service defends is an invariant an importer, a
fix-up script or a psql session walks straight past -- and on a fiscal register that is
not a hypothetical.

`String(n)` + a Pydantic `Literal`, never a Postgres `ENUM`: that is how every closed
set in this schema is already spelled (`pipeline_stages.tipo` is `String(10)`,
`documents.tipo` is `String(20)`), and it means a future value costs a schema constant
rather than an `ALTER TYPE` migration. The closed sets that must also hold across write
paths get a `CHECK` on top, which an `ENUM` would not have made unnecessary anyway --
an `ENUM` cannot express that `stato` depends on `tipo`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin

PROFORMA_SEQUENCE_NAME = "proforma_riferimento_seq"


class Invoice(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A fiscal invoice or a proforma. One table, because lists, timeline and search
    stay one query and `tipo` already carries the difference."""

    __tablename__ = "invoices"

    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    deal_id: Mapped[UUID | None] = mapped_column(ForeignKey("deals.id"), default=None, index=True)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    stato: Mapped[str] = mapped_column(String(12), nullable=False)
    # `NULL` until emission. That is what makes "a failed creation cannot burn a
    # number" true by construction rather than by care.
    anno: Mapped[int | None] = mapped_column(Integer, default=None)
    numero: Mapped[int | None] = mapped_column(Integer, default=None)
    riferimento: Mapped[str | None] = mapped_column(String(30), default=None)
    # `Date`, never a timestamp: this is the date printed on the document and the one
    # that decides the fiscal year, not an instant. Acme's `toISOString()` moved an
    # invoice issued on 31 December at 23:30 CET into the next year.
    data_emissione: Mapped[date | None] = mapped_column(Date, default=None)
    data_scadenza: Mapped[date | None] = mapped_column(Date, default=None)
    tipo_documento: Mapped[str] = mapped_column(String(4), nullable=False, default="TD01")
    divisa: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Derived by the service and stored. Never recomputed by a client: a total computed
    # in the browser is the structural defect this slice exists to remove.
    imponibile: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    imposta: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    bollo: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    totale: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    causale: Mapped[str | None] = mapped_column(String(200), default=None)
    # Both parties' identity and the fiscal parameters as they were at emission.
    # `NULL` on a draft and on a proforma.
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    # An integer because a snapshot written today is read by code from three years
    # hence, and an unversioned JSON payload is interpreted by guessing.
    snapshot_versione: Mapped[int | None] = mapped_column(Integer, default=None)
    stato_pagamento: Mapped[str] = mapped_column(
        String(14), nullable=False, default="da_incassare"
    )
    data_incasso: Mapped[date | None] = mapped_column(Date, default=None)
    # Why this column exists even though the slice performs no transmission: the XML
    # is a deliverable the user hands to their own intermediary. Without it the system
    # could not tell an invoice that never left -- annullable -- from one already
    # deposited with the Agenzia delle Entrate, and would treat both the same.
    trasmessa_esternamente_il: Mapped[date | None] = mapped_column(Date, default=None)
    xml_hash_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    pdf_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id"), default=None
    )
    xml_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id"), default=None
    )
    # A conversion is a new row pointing at the proforma, not a state change in place:
    # otherwise "immutable after emission" would be a property of something that *was*
    # mutable, verifiable only by reconstructing the history.
    origine_proforma_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("invoices.id"), default=None
    )
    annullata_il: Mapped[date | None] = mapped_column(Date, default=None)
    motivo_annullamento: Mapped[str | None] = mapped_column(String(500), default=None)
    note_interne: Mapped[str | None] = mapped_column(Text, default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        # Two state machines share one column, so the legal pairs are a table
        # constraint and not a convention of the service: `stato = 'consumata'` on a
        # `fattura` is not storable at all.
        CheckConstraint(
            "(tipo = 'fattura' AND stato IN ('bozza', 'emessa', 'annullata')) "
            "OR (tipo = 'proforma' AND stato IN ('bozza', 'confermata', 'consumata'))",
            name="ck_invoices_tipo_stato",
        ),
        CheckConstraint(
            "(anno IS NULL) = (numero IS NULL)", name="ck_invoices_anno_numero_together"
        ),
        CheckConstraint(
            "numero IS NULL OR (tipo = 'fattura' AND stato <> 'bozza')",
            name="ck_invoices_numero_requires_issued_fattura",
        ),
        CheckConstraint("numero IS NULL OR numero > 0", name="ck_invoices_numero_positive"),
        CheckConstraint(
            "riferimento IS NULL OR tipo = 'proforma'",
            name="ck_invoices_riferimento_only_on_proforma",
        ),
        CheckConstraint(
            "(snapshot IS NULL) = (snapshot_versione IS NULL)",
            name="ck_invoices_snapshot_together",
        ),
        CheckConstraint(
            "(annullata_il IS NULL AND motivo_annullamento IS NULL) "
            "OR (stato = 'annullata' AND annullata_il IS NOT NULL "
            "AND motivo_annullamento IS NOT NULL)",
            name="ck_invoices_annullamento_complete",
        ),
        CheckConstraint(
            "data_incasso IS NULL OR stato_pagamento = 'incassato'",
            name="ck_invoices_incasso_requires_state",
        ),
        # Spec 4: what never consumed a number is deletable; what consumed one is not,
        # not even by direct SQL -- and neither is a `consumata` proforma, which is the
        # antecedent of an immutable document.
        CheckConstraint(
            "deleted_at IS NULL OR (numero IS NULL AND stato <> 'consumata')",
            name="ck_invoices_no_delete_once_consumed",
        ),
        # The net under the row lock, not the mechanism (spec 3): it turns any future
        # path that bypasses the lock -- a direct INSERT, an importer, a second service
        # -- into an error instead of a duplicate. Partial, because every unnumbered
        # draft would otherwise be a duplicate of every other.
        Index(
            "uq_invoices_anno_numero",
            "anno",
            "numero",
            unique=True,
            postgresql_where=text("numero IS NOT NULL"),
        ),
        Index("ix_invoices_custom_fields", "custom_fields", postgresql_using="gin"),
    )


class InvoiceLine(Base, PrimaryKeyMixin, TimestampMixin):
    """One `DettaglioLinee`.

    Acme sent one line per invoice -- `NumeroLinea` hardcoded to 1, quantity 1, the
    whole total as the unit price -- so the detail of the work never reached the
    customer.

    `numero_linea` is unique per invoice, starts at 1, and is contiguous. The first two
    are database constraints; **contiguity is a service invariant**, maintained by
    `InvoiceService.replace_lines` renumbering the whole list from 1, because no
    single-row `CHECK` can see the other rows. Saying so plainly is better than
    implying the database guarantees more than it does.
    """

    __tablename__ = "invoice_lines"

    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoices.id"), nullable=False, index=True
    )
    numero_linea: Mapped[int] = mapped_column(Integer, nullable=False)
    # String(1000), mirroring FPR12's own `String1000LatinType`, with the matching
    # Pydantic `max_length` in schemas.py. Not `Text`: a width the schema already
    # imposes is a width worth having on the column, so an over-long value is refused
    # before it reaches an SdI validator.
    descrizione: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Numeric(12, 6): a factor, not an amount. See the class docstring on Invoice.
    quantita: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    unita_misura: Mapped[str | None] = mapped_column(String(10), default=None)
    prezzo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    sconto_percentuale: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    sconto_importo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    prezzo_totale: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    aliquota_iva: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    natura: Mapped[str | None] = mapped_column(String(4), default=None)
    riferimento_normativo: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (
        UniqueConstraint("invoice_id", "numero_linea", name="uq_invoice_lines_invoice_numero"),
        # The two checks the SdI applies as a pair, as one table constraint: a zero
        # rate without a Natura is rejected, and a Natura with a non-zero rate is
        # rejected. The invalid combination is therefore not storable, so it is not
        # exportable either.
        CheckConstraint(
            "(aliquota_iva = 0) = (natura IS NOT NULL)",
            name="ck_invoice_lines_natura_agrees_with_rate",
        ),
        CheckConstraint("numero_linea >= 1", name="ck_invoice_lines_numero_positive"),
    )


class InvoiceCounter(Base):
    """One row per year, locked with `SELECT ... FOR UPDATE` inside the emission
    transaction (spec 3).

    **Not a `SEQUENCE`**, and the reason is the property a sequence proudly does not
    have: `nextval()` in Postgres is deliberately non-transactional and does not roll
    back, so every aborted transaction would leave a permanent gap -- which is exactly
    what "progressive numbering with no gaps" forbids. A sequence guarantees uniqueness
    and prohibits the one property that is actually required here.

    Keyed by `anno` rather than by a UUID: the year *is* the identity, and a surrogate
    key would need a uniqueness constraint on `anno` anyway. No `TimestampMixin`
    either -- this row is a lock target, not a record of anything.
    """

    __tablename__ = "invoice_counters"

    anno: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ultimo_numero: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("ultimo_numero >= 0", name="ck_invoice_counters_non_negative"),
    )
```

Add `from sqlalchemy import text` to that file's imports (it is used by the partial index's `postgresql_where`).

- [ ] **Step 4: Write the migration**

`packages/core/migrations/versions/0005_invoices.py`:

```python
"""invoices, invoice lines and the per-year counter

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMPS = (
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
)


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("tipo", sa.String(length=10), nullable=False),
        sa.Column("stato", sa.String(length=12), nullable=False),
        sa.Column("anno", sa.Integer(), nullable=True),
        sa.Column("numero", sa.Integer(), nullable=True),
        sa.Column("riferimento", sa.String(length=30), nullable=True),
        sa.Column("data_emissione", sa.Date(), nullable=True),
        sa.Column("data_scadenza", sa.Date(), nullable=True),
        sa.Column("tipo_documento", sa.String(length=4), nullable=False),
        sa.Column("divisa", sa.String(length=3), nullable=False),
        sa.Column("imponibile", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("imposta", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("bollo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("totale", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("causale", sa.String(length=200), nullable=True),
        sa.Column("snapshot", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot_versione", sa.Integer(), nullable=True),
        sa.Column("stato_pagamento", sa.String(length=14), nullable=False),
        sa.Column("data_incasso", sa.Date(), nullable=True),
        sa.Column("trasmessa_esternamente_il", sa.Date(), nullable=True),
        sa.Column("xml_hash_sha256", sa.String(length=64), nullable=True),
        sa.Column("pdf_document_id", sa.Uuid(), nullable=True),
        sa.Column("xml_document_id", sa.Uuid(), nullable=True),
        sa.Column("origine_proforma_id", sa.Uuid(), nullable=True),
        sa.Column("annullata_il", sa.Date(), nullable=True),
        sa.Column("motivo_annullamento", sa.String(length=500), nullable=True),
        sa.Column("note_interne", sa.Text(), nullable=True),
        sa.Column("custom_fields", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_TIMESTAMPS,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["pdf_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["xml_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["origine_proforma_id"], ["invoices.id"]),
        sa.CheckConstraint(
            "(tipo = 'fattura' AND stato IN ('bozza', 'emessa', 'annullata')) "
            "OR (tipo = 'proforma' AND stato IN ('bozza', 'confermata', 'consumata'))",
            name="ck_invoices_tipo_stato",
        ),
        sa.CheckConstraint(
            "(anno IS NULL) = (numero IS NULL)", name="ck_invoices_anno_numero_together"
        ),
        sa.CheckConstraint(
            "numero IS NULL OR (tipo = 'fattura' AND stato <> 'bozza')",
            name="ck_invoices_numero_requires_issued_fattura",
        ),
        sa.CheckConstraint("numero IS NULL OR numero > 0", name="ck_invoices_numero_positive"),
        sa.CheckConstraint(
            "riferimento IS NULL OR tipo = 'proforma'",
            name="ck_invoices_riferimento_only_on_proforma",
        ),
        sa.CheckConstraint(
            "(snapshot IS NULL) = (snapshot_versione IS NULL)",
            name="ck_invoices_snapshot_together",
        ),
        sa.CheckConstraint(
            "(annullata_il IS NULL AND motivo_annullamento IS NULL) "
            "OR (stato = 'annullata' AND annullata_il IS NOT NULL "
            "AND motivo_annullamento IS NOT NULL)",
            name="ck_invoices_annullamento_complete",
        ),
        sa.CheckConstraint(
            "data_incasso IS NULL OR stato_pagamento = 'incassato'",
            name="ck_invoices_incasso_requires_state",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (numero IS NULL AND stato <> 'consumata')",
            name="ck_invoices_no_delete_once_consumed",
        ),
    )
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])
    op.create_index("ix_invoices_deal_id", "invoices", ["deal_id"])
    # Autogenerate is known to drop both of these shapes -- a partial unique index and
    # a GIN index -- so they are written by hand and named in
    # test_migrations.HAND_MAINTAINED_INDEXES.
    op.create_index(
        "uq_invoices_anno_numero",
        "invoices",
        ["anno", "numero"],
        unique=True,
        postgresql_where=sa.text("numero IS NOT NULL"),
    )
    op.create_index(
        "ix_invoices_custom_fields", "invoices", ["custom_fields"], postgresql_using="gin"
    )

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("numero_linea", sa.Integer(), nullable=False),
        sa.Column("descrizione", sa.String(length=1000), nullable=False),
        sa.Column("quantita", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("unita_misura", sa.String(length=10), nullable=True),
        sa.Column("prezzo_unitario", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("sconto_percentuale", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("sconto_importo", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("prezzo_totale", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("aliquota_iva", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("natura", sa.String(length=4), nullable=True),
        sa.Column("riferimento_normativo", sa.Text(), nullable=True),
        *_TIMESTAMPS,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.UniqueConstraint("invoice_id", "numero_linea", name="uq_invoice_lines_invoice_numero"),
        sa.CheckConstraint(
            "(aliquota_iva = 0) = (natura IS NOT NULL)",
            name="ck_invoice_lines_natura_agrees_with_rate",
        ),
        sa.CheckConstraint("numero_linea >= 1", name="ck_invoice_lines_numero_positive"),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])

    op.create_table(
        "invoice_counters",
        sa.Column("anno", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ultimo_numero", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("anno"),
        sa.CheckConstraint("ultimo_numero >= 0", name="ck_invoice_counters_non_negative"),
    )

    # The right tool *here* and the wrong one for the fiscal number, for the same
    # property: `nextval()` does not roll back. A gap in a proforma reference means
    # nothing, and in exchange the counter serialises nobody.
    op.execute("CREATE SEQUENCE proforma_riferimento_seq AS bigint START WITH 1 INCREMENT BY 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE proforma_riferimento_seq")
    op.drop_table("invoice_counters")
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_custom_fields", table_name="invoices")
    op.drop_index("uq_invoices_anno_numero", table_name="invoices")
    op.drop_index("ix_invoices_deal_id", table_name="invoices")
    op.drop_index("ix_invoices_customer_id", table_name="invoices")
    op.drop_table("invoices")
```

- [ ] **Step 5: Register the models and update the migration test**

In `packages/core/src/pigrocrm/core/models_registry.py`:

```python
from pigrocrm.core.invoices.models import Invoice, InvoiceCounter, InvoiceLine  # noqa: F401
```

In `packages/core/tests/test_migrations.py`:
- add `"invoices"`, `"invoice_lines"`, `"invoice_counters"` to the `expected` set;
- add `"uq_invoices_anno_numero"` and `"ix_invoices_custom_fields"` to `HAND_MAINTAINED_INDEXES`;
- change both `assert revision == "0004"` to `assert revision == "0005"`;
- extend `test_hand_maintained_indexes_survive_the_migration` with the two new assertions:

```python
    assert "USING gin" in indexes["ix_invoices_custom_fields"], (
        "ix_invoices_custom_fields was not created as a GIN index"
    )
    anno_numero_def = indexes["uq_invoices_anno_numero"]
    assert "UNIQUE" in anno_numero_def, "uq_invoices_anno_numero must be a unique index"
    assert "WHERE" in anno_numero_def and "numero IS NOT NULL" in anno_numero_def, (
        "uq_invoices_anno_numero lost its partial predicate, so every unnumbered draft "
        f"is now a duplicate of every other: {anno_numero_def}"
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_models.py packages/core/tests/test_migrations.py -v`
Expected: PASS. If `test_migrations_produce_exactly_the_models_schema` reports a diff, the migration and the model disagree on a width, a nullability or the partial predicate — read the diff, fix the migration, and do not silence the test.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/models.py packages/core/migrations/versions/0005_invoices.py packages/core/src/pigrocrm/core/models_registry.py packages/core/tests/test_invoice_models.py packages/core/tests/test_migrations.py
git commit -m "feat(invoices): tables whose constraints carry the fiscal invariants"
```

---
### Task 9: `InvoiceService` — drafts, proformas and the line editor

**Files:**
- Create: `packages/core/src/pigrocrm/core/invoices/repository.py`
- Create: `packages/core/src/pigrocrm/core/invoices/service.py`
- Test: `packages/core/tests/test_invoice_service.py`

**Interfaces:**
- Consumes: `Invoice`, `InvoiceLine`, `InvoiceCounter`, `PROFORMA_SEQUENCE_NAME` (Task 8); every schema from Task 4; `line_total`, `build_riepilogo`, `sum_totals`, `ComputedLine` (Task 2); `resolve_regime` (Task 3); `FiscalProfileService` (Task 7); `proforma_riferimento` (Task 5); `ActivityService`, `FieldDefinitionService`, `validate_custom_fields`, `DocumentStorage`, `Settings`.
- Produces:
  - `class InvoiceRepository` with, in this order: `get(self, invoice_id: UUID, *, include_deleted: bool = False) -> Invoice | None`, `add(self, invoice: Invoice) -> Invoice`, `lines(self, invoice_id: UUID) -> list[InvoiceLine]`, `clear_lines(self, invoice_id: UUID) -> None`, `add_line(self, line: InvoiceLine) -> InvoiceLine`, `next_proforma_sequence(self) -> int`, `list(self, query: InvoiceListQuery) -> list[Invoice]` — **`list` last**
  - `class InvoiceService` with, in this order: `create`, `update`, `replace_lines`, `confirm_proforma`, `get`, `lines`, `soft_delete`, `set_payment_state`, `list` — **`list` last**, and `lines` (which returns `list[InvoiceLineRead]`) therefore defined above it
  - `ENTITY: EntityType = "invoice"`
  - `InvoiceService.__init__(self, session: Session, storage: DocumentStorage, settings: Settings | None = None) -> None`
  - `create(self, data: InvoiceCreate, actor: Actor) -> InvoiceRead`
  - `update(self, invoice_id: UUID, data: InvoiceUpdate, actor: Actor) -> InvoiceRead`
  - `replace_lines(self, invoice_id: UUID, righe: list[InvoiceLineIn], actor: Actor) -> InvoiceRead`
  - `confirm_proforma(self, invoice_id: UUID, actor: Actor) -> InvoiceRead`
  - `get(self, invoice_id: UUID, actor: Actor) -> InvoiceRead`
  - `lines(self, invoice_id: UUID, actor: Actor) -> list[InvoiceLineRead]`
  - `soft_delete(self, invoice_id: UUID, actor: Actor) -> None`
  - `set_payment_state(self, invoice_id: UUID, data: PaymentState, actor: Actor) -> InvoiceRead`
  - `list(self, query: InvoiceListQuery, actor: Actor) -> InvoicePage`
  - internal, relied on by Tasks 10–13: `_require(self, invoice_id: UUID) -> Invoice`, `_computed_lines(self, righe: Sequence[InvoiceLineIn], profile: FiscalSnapshot) -> tuple[ComputedLine, ...]`, `_apply_totals(self, invoice: Invoice, computed: Sequence[ComputedLine], profile: FiscalSnapshot) -> None`, `_persist_lines(self, invoice: Invoice, computed: Sequence[ComputedLine]) -> None`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_invoice_service.py`:

```python
"""Drafts and proformas: everything that happens before a number exists.

A draft has no number at all, which is why "a failed creation burned a number" is not
a scenario in this file -- it is impossible by construction. The number appears only in
`issue`, which the next task covers.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.errors import (
    Conflict,
    ImmutableField,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.invoices.naming import RIFERIMENTO_PROFORMA_RE
from pigrocrm.core.invoices.schemas import (
    InvoiceCreate,
    InvoiceLineIn,
    InvoiceListQuery,
    InvoiceUpdate,
    PaymentState,
)
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")
COLLABORATORE = Actor(id=None, type="user", role="collaboratore")
READONLY = Actor(id=None, type="user", role="readonly")


@pytest.fixture
def storage(tmp_path) -> LocalFileStorage:  # type: ignore[no-untyped-def]
    return LocalFileStorage(tmp_path / "documents")


@pytest.fixture
def service(db_session: Session, storage: LocalFileStorage) -> InvoiceService:
    FiscalProfileService(db_session).upsert(FiscalProfileUpsert(codice_regime="RF19"), ADMIN)
    return InvoiceService(db_session, storage)


@pytest.fixture
def customer_id(db_session: Session) -> UUID:
    customer = Customer(
        ragione_sociale="Acme S.r.l.",
        partita_iva="12345678901",
        codice_sdi="ABCDEFG",
        indirizzo="Corso Italia 5",
        cap="00100",
        comune="Roma",
        provincia="RM",
        nazione="IT",
    )
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _line(descrizione: str = "Consulenza", prezzo: str = "1000.00", **kw: object) -> InvoiceLineIn:
    payload: dict[str, object] = {
        "descrizione": descrizione,
        "prezzo_unitario": Decimal(prezzo),
    }
    payload.update(kw)
    return InvoiceLineIn(**payload)  # type: ignore[arg-type]


# --- creation -----------------------------------------------------------------------


def test_a_new_invoice_is_a_draft_with_no_number(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    assert invoice.tipo == "fattura"
    assert invoice.stato == "bozza"
    assert invoice.anno is None
    assert invoice.numero is None
    assert invoice.riferimento is None
    assert invoice.tipo_documento == "TD01"
    assert invoice.divisa == "EUR"
    assert invoice.totale == Decimal("0.00")
    assert invoice.stato_pagamento == "da_incassare"


def test_a_new_proforma_gets_a_reference_no_fiscal_regex_can_accept(
    service: InvoiceService, customer_id: UUID
) -> None:
    proforma = service.create(
        InvoiceCreate(customer_id=customer_id, tipo="proforma", righe=[_line()]), ADMIN
    )
    assert proforma.stato == "bozza"
    assert proforma.numero is None
    assert RIFERIMENTO_PROFORMA_RE.fullmatch(proforma.riferimento or "")


def test_two_proformas_get_different_references(
    service: InvoiceService, customer_id: UUID
) -> None:
    first = service.create(InvoiceCreate(customer_id=customer_id, tipo="proforma"), ADMIN)
    second = service.create(InvoiceCreate(customer_id=customer_id, tipo="proforma"), ADMIN)
    assert first.riferimento != second.riferimento


def test_creation_computes_and_stores_the_totals(
    service: InvoiceService, customer_id: UUID
) -> None:
    """Totals are computed by the service and stored, never recomputed by a client:
    a total computed in the browser is the structural defect this slice removes."""
    invoice = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            righe=[
                _line("Consulenza", "33.333333", quantita=Decimal("3.000000")),
                _line("Sconto", "-10.00"),
            ],
        ),
        ADMIN,
    )
    assert invoice.imponibile == Decimal("90.00")
    assert invoice.imposta == Decimal("0.00")
    assert invoice.totale == Decimal("90.00")
    assert invoice.bollo == Decimal("2.00")


def test_the_stamp_duty_is_stored_but_stays_out_of_the_total(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice = service.create(
        InvoiceCreate(customer_id=customer_id, righe=[_line("Consulenza", "1000.00")]), ADMIN
    )
    assert invoice.bollo == Decimal("2.00")
    assert invoice.totale == Decimal("1000.00")


def test_the_regime_decides_the_line_natura(service: InvoiceService, customer_id: UUID) -> None:
    invoice = service.create(
        InvoiceCreate(customer_id=customer_id, righe=[_line()]), ADMIN
    )
    (riga,) = service.lines(invoice.id, ADMIN)
    assert riga.numero_linea == 1
    assert riga.aliquota_iva == Decimal("0.00")
    assert riga.natura == "N2.2"
    assert riga.riferimento_normativo is not None


def test_a_non_zero_rate_under_the_forfettario_is_refused_by_field_name(
    service: InvoiceService, customer_id: UUID
) -> None:
    with pytest.raises(ValidationFailed) as caught:
        service.create(
            InvoiceCreate(
                customer_id=customer_id,
                righe=[_line(aliquota_iva=Decimal("22.00"))],
            ),
            ADMIN,
        )
    assert caught.value.details["field"] == "aliquota_iva"


def test_an_unknown_customer_is_not_found_rather_than_a_foreign_key_violation(
    service: InvoiceService,
) -> None:
    with pytest.raises(NotFound):
        service.create(InvoiceCreate(customer_id=uuid4()), ADMIN)


def test_an_unknown_deal_is_not_found_even_though_the_column_is_nullable(
    service: InvoiceService, customer_id: UUID
) -> None:
    """A nullable FK is skipped only when the caller supplies nothing, never when the
    caller supplies a value -- the defect `deals.owner_id` shipped with."""
    with pytest.raises(NotFound):
        service.create(InvoiceCreate(customer_id=customer_id, deal_id=uuid4()), ADMIN)


def test_a_deal_belonging_to_another_customer_is_refused(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    other = Customer(ragione_sociale="Altro", nazione="IT")
    db_session.add(other)
    db_session.flush()
    deal = Deal(nome="Progetto", customer_id=other.id)
    db_session.add(deal)
    db_session.flush()
    with pytest.raises(ValidationFailed) as caught:
        service.create(InvoiceCreate(customer_id=customer_id, deal_id=deal.id), ADMIN)
    assert caught.value.details["field"] == "deal_id"


def test_creation_without_a_fiscal_profile_says_which_configuration_is_missing(
    db_session: Session, storage: LocalFileStorage, customer_id: UUID
) -> None:
    with pytest.raises(NotFound) as caught:
        InvoiceService(db_session, storage).create(
            InvoiceCreate(customer_id=customer_id), ADMIN
        )
    assert caught.value.details["entity"] == "fiscal_profile"


def test_a_readonly_actor_cannot_create(service: InvoiceService, customer_id: UUID) -> None:
    with pytest.raises(PermissionDenied):
        service.create(InvoiceCreate(customer_id=customer_id), READONLY)


def test_a_collaboratore_may_create_a_draft(service: InvoiceService, customer_id: UUID) -> None:
    """Drafting is ordinary entity writing; only consuming a register number is not
    (spec 11)."""
    assert service.create(InvoiceCreate(customer_id=customer_id), COLLABORATORE).stato == "bozza"


def test_creation_records_an_activity(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    entries = ActivityService(db_session).timeline("invoice", invoice.id)
    assert [entry.kind for entry in entries] == ["created"]


# --- the line editor ----------------------------------------------------------------


def test_replacing_the_lines_renumbers_them_from_one_contiguously(
    service: InvoiceService, customer_id: UUID
) -> None:
    """Contiguity is a service invariant -- no single-row CHECK can see the other rows
    -- and this is where it is maintained: the whole list is renumbered from 1."""
    invoice = service.create(
        InvoiceCreate(customer_id=customer_id, righe=[_line("A"), _line("B"), _line("C")]), ADMIN
    )
    service.replace_lines(invoice.id, [_line("Solo questa", "50.00")], ADMIN)
    righe = service.lines(invoice.id, ADMIN)
    assert [r.numero_linea for r in righe] == [1]
    assert righe[0].descrizione == "Solo questa"


def test_replacing_the_lines_recomputes_the_totals(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice = service.create(
        InvoiceCreate(customer_id=customer_id, righe=[_line("A", "1000.00")]), ADMIN
    )
    updated = service.replace_lines(invoice.id, [_line("A", "10.00")], ADMIN)
    assert updated.totale == Decimal("10.00")
    # Below the threshold now, so the duty disappears with the amount.
    assert updated.bollo == Decimal("0.00")


def test_replacing_the_lines_with_an_empty_list_is_allowed_on_a_draft(
    service: InvoiceService, customer_id: UUID
) -> None:
    """A draft with no lines is a legitimate intermediate state; only *emission*
    requires at least one line."""
    invoice = service.create(
        InvoiceCreate(customer_id=customer_id, righe=[_line()]), ADMIN
    )
    assert service.replace_lines(invoice.id, [], ADMIN).totale == Decimal("0.00")
    assert service.lines(invoice.id, ADMIN) == []


def test_bulk_replacement_is_how_an_optional_numeric_field_gets_cleared(
    service: InvoiceService, customer_id: UUID
) -> None:
    """A14 avoided rather than papered over: with `exclude_none=True` there is no
    spelling that clears `sconto_importo`, so the list is replaced instead of patched."""
    invoice = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            righe=[_line("A", "100.00", sconto_importo=Decimal("10.00"), unita_misura="ore")],
        ),
        ADMIN,
    )
    service.replace_lines(invoice.id, [_line("A", "100.00")], ADMIN)
    (riga,) = service.lines(invoice.id, ADMIN)
    assert riga.sconto_importo is None
    assert riga.unita_misura is None
    assert riga.prezzo_totale == Decimal("100.00")


def test_a_percentage_and_a_fixed_discount_compose_in_a_defined_order(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            righe=[
                _line(
                    "A",
                    "100.00",
                    quantita=Decimal("2.000000"),
                    sconto_percentuale=Decimal("10.00"),
                    sconto_importo=Decimal("5.00"),
                )
            ],
        ),
        ADMIN,
    )
    assert invoice.totale == Decimal("175.00")


def test_more_lines_than_the_bound_are_refused_by_the_schema(
    service: InvoiceService, customer_id: UUID
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InvoiceCreate(customer_id=customer_id, righe=[_line()] * 201)


def test_replacing_lines_records_an_activity(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    service.replace_lines(invoice.id, [_line(), _line("B")], ADMIN)
    kinds = [e.kind for e in ActivityService(db_session).timeline("invoice", invoice.id)]
    assert "lines_replaced" in kinds


# --- editing what may be edited -----------------------------------------------------


def test_the_causale_and_the_notes_are_editable_on_a_draft(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice = service.create(InvoiceCreate(customer_id=customer_id, causale="Bozza"), ADMIN)
    updated = service.update(
        invoice.id, InvoiceUpdate(causale="Consulenza agosto", note_interne="da rileggere"), ADMIN
    )
    assert updated.causale == "Consulenza agosto"
    assert updated.note_interne == "da rileggere"


def test_an_empty_string_clears_a_text_column(
    service: InvoiceService, customer_id: UUID
) -> None:
    """The only clear-it spelling that exists, and it works because both editable
    native columns are text-shaped."""
    invoice = service.create(InvoiceCreate(customer_id=customer_id, causale="Bozza"), ADMIN)
    assert service.update(invoice.id, InvoiceUpdate(causale=""), ADMIN).causale == ""


def test_an_omitted_key_clears_nothing(service: InvoiceService, customer_id: UUID) -> None:
    invoice = service.create(
        InvoiceCreate(customer_id=customer_id, causale="Bozza", note_interne="nota"), ADMIN
    )
    assert service.update(invoice.id, InvoiceUpdate(causale="Altro"), ADMIN).note_interne == "nota"


# --- proforma confirmation ----------------------------------------------------------


def test_confirming_a_proforma_moves_it_out_of_draft(
    service: InvoiceService, customer_id: UUID
) -> None:
    proforma = service.create(
        InvoiceCreate(customer_id=customer_id, tipo="proforma", righe=[_line()]), ADMIN
    )
    assert service.confirm_proforma(proforma.id, ADMIN).stato == "confermata"


def test_confirming_a_proforma_with_no_lines_is_refused(
    service: InvoiceService, customer_id: UUID
) -> None:
    proforma = service.create(InvoiceCreate(customer_id=customer_id, tipo="proforma"), ADMIN)
    with pytest.raises(ValidationFailed) as caught:
        service.confirm_proforma(proforma.id, ADMIN)
    assert caught.value.details["field"] == "righe"


def test_a_fattura_cannot_be_confirmed(service: InvoiceService, customer_id: UUID) -> None:
    invoice = service.create(InvoiceCreate(customer_id=customer_id, righe=[_line()]), ADMIN)
    with pytest.raises(Conflict):
        service.confirm_proforma(invoice.id, ADMIN)


def test_a_confirmed_proforma_can_still_be_edited(
    service: InvoiceService, customer_id: UUID
) -> None:
    """A proforma is entirely mutable until it is consumed -- that is what it is for
    (spec 5): agree the amount before consuming a number."""
    proforma = service.create(
        InvoiceCreate(customer_id=customer_id, tipo="proforma", righe=[_line()]), ADMIN
    )
    service.confirm_proforma(proforma.id, ADMIN)
    assert service.replace_lines(proforma.id, [_line("B", "20.00")], ADMIN).totale == Decimal(
        "20.00"
    )


# --- deletion -----------------------------------------------------------------------


def test_a_draft_can_be_soft_deleted_and_disappears_from_the_list(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    service.soft_delete(invoice.id, ADMIN)
    assert invoice.id not in [item.id for item in service.list(InvoiceListQuery(), ADMIN).items]
    with pytest.raises(NotFound):
        service.get(invoice.id, ADMIN)


def test_soft_deleting_a_draft_also_removes_its_lines_from_the_reader(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice = service.create(InvoiceCreate(customer_id=customer_id, righe=[_line()]), ADMIN)
    service.soft_delete(invoice.id, ADMIN)
    with pytest.raises(NotFound):
        service.lines(invoice.id, ADMIN)


# --- payment ------------------------------------------------------------------------


def test_the_payment_state_cannot_be_set_on_a_draft(
    service: InvoiceService, customer_id: UUID
) -> None:
    """There is nothing to collect on a document that was never issued."""
    invoice = service.create(InvoiceCreate(customer_id=customer_id, righe=[_line()]), ADMIN)
    with pytest.raises(Conflict):
        service.set_payment_state(
            invoice.id, PaymentState(stato_pagamento="incassato", data_incasso=date(2026, 9, 1)),
            ADMIN,
        )


def test_marking_collected_without_a_date_is_refused(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    """"Collected with no date" and "a date but not collected" are both nonsense, so
    a single method takes both and checks their agreement."""
    invoice = _issued_row(db_session, customer_id)
    with pytest.raises(ValidationFailed) as caught:
        service.set_payment_state(invoice.id, PaymentState(stato_pagamento="incassato"), ADMIN)
    assert caught.value.details["field"] == "data_incasso"


def test_going_back_to_uncollected_clears_the_date(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice = _issued_row(db_session, customer_id)
    service.set_payment_state(
        invoice.id, PaymentState(stato_pagamento="incassato", data_incasso=date(2026, 9, 1)), ADMIN
    )
    back = service.set_payment_state(
        invoice.id, PaymentState(stato_pagamento="da_incassare"), ADMIN
    )
    assert back.stato_pagamento == "da_incassare"
    assert back.data_incasso is None


def test_a_collaboratore_may_record_a_payment(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    """Spec 11: `set_payment_state` is the one invoice write a collaborator -- and an
    agent -- may perform, because collecting is a subsequent fact, not part of the
    document."""
    invoice = _issued_row(db_session, customer_id)
    assert (
        service.set_payment_state(
            invoice.id,
            PaymentState(stato_pagamento="incassato", data_incasso=date(2026, 9, 1)),
            COLLABORATORE,
        ).stato_pagamento
        == "incassato"
    )


def _issued_row(db_session: Session, customer_id: UUID) -> Invoice:
    """An already-issued row inserted directly, so this file's payment tests do not
    depend on `issue` (next task) being written yet."""
    invoice = Invoice(
        customer_id=customer_id,
        tipo="fattura",
        stato="emessa",
        anno=2026,
        numero=1,
        data_emissione=date(2026, 8, 20),
        tipo_documento="TD01",
        divisa="EUR",
        imponibile=Decimal("100.00"),
        imposta=Decimal("0.00"),
        bollo=Decimal("2.00"),
        totale=Decimal("100.00"),
        stato_pagamento="da_incassare",
        snapshot={"versione": 1},
        snapshot_versione=1,
        custom_fields={},
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


# --- editing what may not be edited -------------------------------------------------


def test_the_lines_of_an_issued_invoice_cannot_be_replaced(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice = _issued_row(db_session, customer_id)
    with pytest.raises(ImmutableField) as caught:
        service.replace_lines(invoice.id, [_line()], ADMIN)
    assert caught.value.details["field"] == "righe"


def test_the_causale_of_an_issued_invoice_cannot_be_changed(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice = _issued_row(db_session, customer_id)
    with pytest.raises(ImmutableField) as caught:
        service.update(invoice.id, InvoiceUpdate(causale="ripensamento"), ADMIN)
    assert caught.value.details["field"] == "causale"


def test_the_internal_notes_of_an_issued_invoice_can_still_be_changed(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    """They appear on no artefact, so they are not part of the document (spec 4)."""
    invoice = _issued_row(db_session, customer_id)
    assert (
        service.update(invoice.id, InvoiceUpdate(note_interne="sollecitato"), ADMIN).note_interne
        == "sollecitato"
    )


def test_an_issued_invoice_cannot_be_soft_deleted(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice = _issued_row(db_session, customer_id)
    with pytest.raises(Conflict):
        service.soft_delete(invoice.id, ADMIN)


# --- listing ------------------------------------------------------------------------


def test_the_list_filters_by_tipo_stato_year_and_payment(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    draft = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    proforma = service.create(InvoiceCreate(customer_id=customer_id, tipo="proforma"), ADMIN)
    issued = _issued_row(db_session, customer_id)

    assert {i.id for i in service.list(InvoiceListQuery(tipo="proforma"), ADMIN).items} == {
        proforma.id
    }
    assert {i.id for i in service.list(InvoiceListQuery(stato="bozza"), ADMIN).items} == {
        draft.id,
        proforma.id,
    }
    assert {i.id for i in service.list(InvoiceListQuery(anno=2026), ADMIN).items} == {issued.id}
    assert {
        i.id for i in service.list(InvoiceListQuery(stato_pagamento="incassato"), ADMIN).items
    } == set()


def test_the_list_paginates_on_the_uuid_v7_cursor(
    service: InvoiceService, customer_id: UUID
) -> None:
    for _ in range(3):
        service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    first = service.list(InvoiceListQuery(limit=2), ADMIN)
    assert len(first.items) == 2
    assert first.next_cursor is not None
    second = service.list(InvoiceListQuery(limit=2, cursor=first.next_cursor), ADMIN)
    assert len(second.items) == 1
    assert second.next_cursor is None


def test_list_is_the_last_method_of_the_service_class() -> None:
    """`def list` rebinds `list` in the class namespace, so a later method annotated
    `-> list[...]` fails at import on Python 3.13. `lines` returns
    `list[InvoiceLineRead]`, so it has to sit above `list`, and this pins the order
    rather than trusting a comment."""
    names = [
        name
        for name, value in vars(InvoiceService).items()
        if callable(value) and not name.startswith("__")
    ]
    assert names[-1] == "list"
    assert names.index("lines") < names.index("list")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.invoices.repository'`

- [ ] **Step 3: Implement the repository**

`packages/core/src/pigrocrm/core/invoices/repository.py`:

```python
"""Queries only. A repository never commits (project rule): every method reads or
flushes, and the surrounding `InvoiceService` method is the one transaction."""

from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from pigrocrm.core.invoices.models import PROFORMA_SEQUENCE_NAME, Invoice, InvoiceLine
from pigrocrm.core.invoices.schemas import InvoiceListQuery


class InvoiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, invoice_id: UUID, *, include_deleted: bool = False) -> Invoice | None:
        invoice = self.session.get(Invoice, invoice_id)
        if invoice is None:
            return None
        if invoice.deleted_at is not None and not include_deleted:
            return None
        return invoice

    def add(self, invoice: Invoice) -> Invoice:
        self.session.add(invoice)
        self.session.flush()
        return invoice

    def lines(self, invoice_id: UUID) -> list[InvoiceLine]:
        stmt = (
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice_id)
            .order_by(InvoiceLine.numero_linea)
        )
        return list(self.session.execute(stmt).scalars())

    def clear_lines(self, invoice_id: UUID) -> None:
        """A real `DELETE`, then a fresh insert of the whole list.

        Bulk replacement rather than a per-line diff, for the reason spec 11 gives: it
        is the natural shape of a line editor, and it is what makes clearing an
        optional numeric column possible at all (A14 -- with `exclude_none=True` there
        is no spelling that means "set `sconto_importo` back to nothing").
        """
        self.session.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id))
        self.session.flush()

    def add_line(self, line: InvoiceLine) -> InvoiceLine:
        self.session.add(line)
        self.session.flush()
        return line

    def next_proforma_sequence(self) -> int:
        """`nextval` on the one proforma sequence.

        A `SEQUENCE` is the right tool here and the wrong one for the fiscal number,
        for the same property: it does not roll back. A gap in a proforma reference
        means nothing -- a proforma is not a register -- and in exchange this counter
        serialises nobody, which is exactly what the fiscal counter cannot afford to
        do and must do anyway.
        """
        return int(
            self.session.execute(
                text(f"SELECT nextval('{PROFORMA_SEQUENCE_NAME}')")
            ).scalar_one()
        )

    # `list` must stay the last method defined in this class -- an unconditional
    # project rule (`test_module_imports.py`). Defining a method named `list` rebinds
    # that name in the *class* namespace, so any later method whose own return
    # annotation is a bare `list[...]` would resolve `list` to this method instead of
    # the builtin and fail at import time on Python 3.13.
    def list(self, query: InvoiceListQuery) -> list[Invoice]:
        stmt = select(Invoice).where(Invoice.deleted_at.is_(None))
        if query.customer_id:
            stmt = stmt.where(Invoice.customer_id == query.customer_id)
        if query.deal_id:
            stmt = stmt.where(Invoice.deal_id == query.deal_id)
        if query.tipo:
            stmt = stmt.where(Invoice.tipo == query.tipo)
        if query.stato:
            stmt = stmt.where(Invoice.stato == query.stato)
        if query.anno:
            stmt = stmt.where(Invoice.anno == query.anno)
        if query.stato_pagamento:
            stmt = stmt.where(Invoice.stato_pagamento == query.stato_pagamento)
        if query.cursor:
            stmt = stmt.where(Invoice.id > query.cursor)
        # Keyset pagination on a UUIDv7 id: ordered by creation, stable under inserts.
        # No caller-supplied sort -- R9 is open and this adds no half-feature.
        return list(
            self.session.execute(stmt.order_by(Invoice.id).limit(query.limit + 1)).scalars()
        )
```

- [ ] **Step 4: Implement the service**

`packages/core/src/pigrocrm/core/invoices/service.py`:

```python
"""The only writer of `invoices` and `invoice_lines`.

This task covers everything that happens before a number exists. A draft and a
proforma are ordinary mutable rows; the number, the freezing and the artefacts belong
to `issue`, `annul` and the artefact methods added by the following tasks.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.errors import Conflict, ImmutableField, NotFound, ValidationFailed
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.fiscal.regime import RegimeStrategy, resolve_regime
from pigrocrm.core.fiscal.schemas import FiscalSnapshot
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.models import Invoice, InvoiceLine
from pigrocrm.core.invoices.naming import proforma_riferimento
from pigrocrm.core.invoices.repository import InvoiceRepository
from pigrocrm.core.invoices.schemas import (
    DIVISA,
    TIPO_DOCUMENTO,
    InvoiceCreate,
    InvoiceLineIn,
    InvoiceLineRead,
    InvoiceListQuery,
    InvoicePage,
    InvoiceRead,
    InvoiceUpdate,
    PaymentState,
)
from pigrocrm.core.invoices.totals import ComputedLine, build_riepilogo, line_total, sum_totals
from pigrocrm.core.storage.base import DocumentStorage

ENTITY: EntityType = "invoice"
ZERO = Decimal("0.00")

# What stays writable once a `fattura` has left the `bozza` state (spec 4). Everything
# else on the row is frozen, and an attempt raises `ImmutableField` naming the field.
# `stato_pagamento`/`data_incasso` are absent because they have their own method, which
# is what makes their agreement checkable; `stato` is absent for the same reason.
MUTABLE_AFTER_ISSUE: frozenset[str] = frozenset({"note_interne", "custom_fields"})


class InvoiceService:
    def __init__(
        self, session: Session, storage: DocumentStorage, settings: Settings | None = None
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings or get_settings()
        self.repo = InvoiceRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)
        self.fiscal = FiscalProfileService(session)

    # ---- shared helpers -------------------------------------------------------

    def _check_owner(self, customer_id: UUID, deal_id: UUID | None) -> None:
        """A syntactically valid but unknown UUID becomes this project's own
        `NotFound` instead of a raw `ForeignKeyViolation` reaching the caller from
        `flush()`. The nullable `deal_id` is checked too whenever a value is supplied
        -- skipping a nullable FK is the defect `deals.owner_id` shipped with."""
        if self.session.get(Customer, customer_id) is None:
            raise NotFound("customer", customer_id)
        if deal_id is None:
            return
        deal = self.session.get(Deal, deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)
        if deal.customer_id != customer_id:
            raise ValidationFailed(
                ENTITY,
                "deal_id",
                "il deal appartiene a un altro cliente",
                expected=f"un deal del cliente {customer_id}",
            )

    def _regime(self) -> tuple[RegimeStrategy, FiscalSnapshot]:
        """The strategy and the parameters, read together so a caller cannot pair a
        profile with the wrong strategy. Raises `NotFound("fiscal_profile", ...)` when
        nothing is configured, which tells the user which screen to go to."""
        profile = self.fiscal.snapshot()
        return resolve_regime(profile.codice_regime), profile

    def _computed_lines(
        self, righe: Sequence[InvoiceLineIn], profile: FiscalSnapshot
    ) -> tuple[ComputedLine, ...]:
        """Caller input plus the regime's answer, renumbered from 1.

        Renumbering here is what maintains contiguity: the unique constraint on
        `(invoice_id, numero_linea)` and the `>= 1` check are the database's half, and
        no single-row `CHECK` can see the other rows.
        """
        strategy = resolve_regime(profile.codice_regime)
        computed: list[ComputedLine] = []
        for index, riga in enumerate(righe, start=1):
            aliquota, natura, riferimento = strategy.resolve_line_vat(riga.aliquota_iva, profile)
            computed.append(
                ComputedLine(
                    numero_linea=index,
                    descrizione=riga.descrizione,
                    quantita=riga.quantita,
                    unita_misura=riga.unita_misura,
                    prezzo_unitario=riga.prezzo_unitario,
                    sconto_percentuale=riga.sconto_percentuale,
                    sconto_importo=riga.sconto_importo,
                    prezzo_totale=line_total(
                        quantita=riga.quantita,
                        prezzo_unitario=riga.prezzo_unitario,
                        sconto_percentuale=riga.sconto_percentuale,
                        sconto_importo=riga.sconto_importo,
                    ),
                    aliquota_iva=aliquota,
                    natura=natura,
                    riferimento_normativo=riferimento,
                )
            )
        return tuple(computed)

    def _apply_totals(
        self, invoice: Invoice, computed: Sequence[ComputedLine], profile: FiscalSnapshot
    ) -> None:
        """Compute and **store**. Never recomputed by a client: a total computed in
        the browser is the structural defect inherited from Acme, and on an invoice it
        costs more."""
        strategy = resolve_regime(profile.codice_regime)
        riepilogo = build_riepilogo(computed)
        imponibile, imposta, totale = sum_totals(riepilogo)
        invoice.imponibile = imponibile
        invoice.imposta = imposta
        invoice.totale = totale
        # The stamp duty is stored but does not enter the total: `DatiBollo` declares
        # that the issuer settled it virtually (spec 7.2).
        invoice.bollo = strategy.bollo(riepilogo, profile)

    def _persist_lines(self, invoice: Invoice, computed: Sequence[ComputedLine]) -> None:
        self.repo.clear_lines(invoice.id)
        for riga in computed:
            self.repo.add_line(
                InvoiceLine(
                    invoice_id=invoice.id,
                    numero_linea=riga.numero_linea,
                    descrizione=riga.descrizione,
                    quantita=riga.quantita,
                    unita_misura=riga.unita_misura,
                    prezzo_unitario=riga.prezzo_unitario,
                    sconto_percentuale=riga.sconto_percentuale,
                    sconto_importo=riga.sconto_importo,
                    prezzo_totale=riga.prezzo_totale,
                    aliquota_iva=riga.aliquota_iva,
                    natura=riga.natura,
                    riferimento_normativo=riga.riferimento_normativo,
                )
            )

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def _update_custom_fields(self, invoice: Invoice, provided: dict[str, Any]) -> dict[str, Any]:
        """Validates only the keys the caller is touching, never the merge with what is
        stored -- identical in shape to `CustomerService._update_custom_fields`, and for
        the same reason: re-validating the merge would let archiving a field block every
        future custom-field update on rows that still hold it."""
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
        to_set = {key: value for key, value in provided.items() if value is not None}
        touched = [spec for spec in active_by_key.values() if spec.key in to_set]
        merged = {k: v for k, v in invoice.custom_fields.items() if k not in to_remove}
        merged.update(validate_custom_fields(ENTITY, touched, to_set))
        return merged

    def _is_editable(self, invoice: Invoice) -> bool:
        """A `fattura` is editable only as a `bozza`; a `proforma` is editable until it
        is `consumata`. That asymmetry is the point of a proforma (spec 5): agree the
        amount, correct it as many times as needed, without touching the register."""
        if invoice.tipo == "proforma":
            return invoice.stato in ("bozza", "confermata")
        return invoice.stato == "bozza"

    def _require_editable(self, invoice: Invoice, field: str) -> None:
        if not self._is_editable(invoice):
            raise ImmutableField(
                ENTITY,
                field,
                f"una fattura in stato '{invoice.stato}' e' un documento fiscale: "
                "si corregge con un annullamento e una nuova emissione, non con una modifica",
            )

    # ---- writes ---------------------------------------------------------------

    def create(self, data: InvoiceCreate, actor: Actor) -> InvoiceRead:
        """A draft or a proforma. Neither has a number, which is why a failed creation
        cannot burn one -- not as a matter of care, but because there is nothing to
        burn until `issue` runs."""
        actor.require_write("create_invoice")
        self._check_owner(data.customer_id, data.deal_id)
        _, profile = self._regime()

        invoice = Invoice(
            customer_id=data.customer_id,
            deal_id=data.deal_id,
            tipo=data.tipo,
            stato="bozza",
            tipo_documento=TIPO_DOCUMENTO,
            divisa=DIVISA,
            causale=data.causale,
            note_interne=data.note_interne,
            imponibile=ZERO,
            imposta=ZERO,
            bollo=ZERO,
            totale=ZERO,
            stato_pagamento="da_incassare",
            custom_fields=self._validated_custom(data.custom_fields or {}),
        )
        if data.tipo == "proforma":
            invoice.riferimento = proforma_riferimento(
                date.today().year, self.repo.next_proforma_sequence()
            )
        computed = self._computed_lines(data.righe, profile)
        self._apply_totals(invoice, computed, profile)
        self.repo.add(invoice)
        self._persist_lines(invoice, computed)
        self.activities.record(
            ENTITY,
            invoice.id,
            "created",
            actor,
            {"tipo": invoice.tipo, "righe": len(computed), "totale": str(invoice.totale)},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def update(self, invoice_id: UUID, data: InvoiceUpdate, actor: Actor) -> InvoiceRead:
        actor.require_write("update_invoice")
        invoice = self._require(invoice_id)
        changes = data.model_dump(exclude_none=True, exclude={"custom_fields"})
        frozen = [key for key in changes if key not in MUTABLE_AFTER_ISSUE]
        if frozen and not self._is_editable(invoice):
            raise ImmutableField(
                ENTITY,
                sorted(frozen)[0],
                f"campo congelato su un documento in stato '{invoice.stato}'",
            )
        if data.custom_fields is not None:
            changes["custom_fields"] = self._update_custom_fields(invoice, data.custom_fields)
        for key, value in changes.items():
            setattr(invoice, key, value)
        self.activities.record(ENTITY, invoice.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def replace_lines(
        self, invoice_id: UUID, righe: list[InvoiceLineIn], actor: Actor
    ) -> InvoiceRead:
        """The whole list, never a partial patch.

        Two reasons, both from spec 11: it is the natural shape of a line editor, and
        it is the only way an optional numeric or date column can be cleared at all
        while `exclude_none=True` is the update contract (A14). Replacing the list
        sidesteps that defect instead of pretending it is closed.
        """
        actor.require_write("replace_invoice_lines")
        invoice = self._require(invoice_id)
        self._require_editable(invoice, "righe")
        _, profile = self._regime()
        computed = self._computed_lines(righe, profile)
        self._apply_totals(invoice, computed, profile)
        self._persist_lines(invoice, computed)
        self.activities.record(
            ENTITY,
            invoice.id,
            "lines_replaced",
            actor,
            {"righe": len(computed), "totale": str(invoice.totale)},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def confirm_proforma(self, invoice_id: UUID, actor: Actor) -> InvoiceRead:
        """`bozza` -> `confermata` on a proforma: the amount is agreed and the document
        is ready to be sent, still without touching the register."""
        actor.require_write("confirm_proforma")
        invoice = self._require(invoice_id)
        if invoice.tipo != "proforma":
            raise Conflict(
                ENTITY, "solo una proforma si conferma", tipo=invoice.tipo, stato=invoice.stato
            )
        if invoice.stato != "bozza":
            raise Conflict(
                ENTITY,
                f"da '{invoice.stato}' non si puo' passare a 'confermata'",
                stato_attuale=invoice.stato,
            )
        if not self.repo.lines(invoice.id):
            raise ValidationFailed(
                ENTITY, "righe", "una proforma senza righe non si conferma",
                expected="almeno una riga",
            )
        invoice.stato = "confermata"
        self.activities.record(ENTITY, invoice.id, "confirmed", actor)
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def soft_delete(self, invoice_id: UUID, actor: Actor) -> None:
        """Only what never consumed a number, and never a `consumata` proforma.

        Checked here **and** by `ck_invoices_no_delete_once_consumed`, which is what
        makes the rule true for a psql session too. Without the gap-free register the
        numbering guarantee of spec 3 would be worth nothing: a number that can be
        deleted is a gap with extra steps.
        """
        actor.require_write("delete_invoice")
        invoice = self._require(invoice_id)
        if invoice.numero is not None or invoice.stato == "consumata":
            raise Conflict(
                ENTITY,
                "un documento che ha consumato un numero non si elimina: "
                "si annulla, conservando il numero",
                stato=invoice.stato,
                numero=invoice.numero,
            )
        invoice.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, invoice.id, "deleted", actor)
        try:
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a row that was issued concurrently: the
            # CHECK is the real authority, and the rollback is mandatory or the
            # caller's session is unusable on its next statement.
            self.session.rollback()
            raise Conflict(
                ENTITY, "il documento e' stato emesso nel frattempo e non si elimina piu'"
            ) from exc

    def set_payment_state(
        self, invoice_id: UUID, data: PaymentState, actor: Actor
    ) -> InvoiceRead:
        """Collection is a subsequent fact, not part of the document (spec 4), so this
        is the one invoice write a collaborator -- and an agent -- may perform."""
        actor.require_write("set_payment_state")
        invoice = self._require(invoice_id)
        if invoice.stato != "emessa":
            raise Conflict(
                ENTITY,
                "solo una fattura emessa ha un incasso da registrare",
                stato=invoice.stato,
            )
        if data.stato_pagamento == "incassato" and data.data_incasso is None:
            raise ValidationFailed(
                ENTITY,
                "data_incasso",
                "un incasso senza data non e' un incasso",
                expected="la data in cui il pagamento e' arrivato",
            )
        invoice.stato_pagamento = data.stato_pagamento
        # Cleared rather than left dangling: the table's own
        # `ck_invoices_incasso_requires_state` would refuse the inconsistent pair
        # anyway, and a stale date on an uncollected invoice is a lie either way.
        invoice.data_incasso = (
            data.data_incasso if data.stato_pagamento == "incassato" else None
        )
        self.activities.record(
            ENTITY,
            invoice.id,
            "payment_state_changed",
            actor,
            {"stato_pagamento": invoice.stato_pagamento},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    # ---- reads ---------------------------------------------------------------

    def get(self, invoice_id: UUID, actor: Actor) -> InvoiceRead:
        return InvoiceRead.model_validate(self._require(invoice_id))

    def lines(self, invoice_id: UUID, actor: Actor) -> list[InvoiceLineRead]:
        self._require(invoice_id)
        return [InvoiceLineRead.model_validate(r) for r in self.repo.lines(invoice_id)]

    def _require(self, invoice_id: UUID) -> Invoice:
        invoice = self.repo.get(invoice_id)
        if invoice is None:
            raise NotFound(ENTITY, invoice_id)
        return invoice

    # `list` must stay the last method defined in this class -- an unconditional
    # project rule (`test_module_imports.py`). `lines` above returns
    # `list[InvoiceLineRead]`, so it must be defined before this point or its
    # annotation resolves `list` to this method and fails at import on Python 3.13.
    def list(self, query: InvoiceListQuery, actor: Actor) -> InvoicePage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return InvoicePage(
            items=[InvoiceRead.model_validate(i) for i in items],
            next_cursor=items[-1].id if has_more and items else None,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_service.py packages/core/tests/test_module_imports.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/repository.py packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_service.py
git commit -m "feat(invoices): drafts, proformas and a bulk line editor"
```

---
### Task 10: Emission — gap-free numbering under real concurrency

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/repository.py` (two methods, inserted **above** `list`)
- Modify: `packages/core/src/pigrocrm/core/invoices/service.py` (add `issue` and its helpers)
- Test: `packages/core/tests/test_invoice_issue.py`
- Test: `packages/core/tests/test_invoice_numbering_concurrency.py`

**Interfaces:**
- Consumes: everything Task 9 produced; `EmitterProfileService.get` (slice 2); `check_party_exportable`, `check_recipient_routing` (Task 6); `InvoiceSnapshot`, `PartySnapshot`, `InvoiceIssue`, `SNAPSHOT_VERSIONE` (Task 4).
- Produces:
  - `InvoiceRepository.lock_counter(self, anno: int) -> InvoiceCounter`
  - `InvoiceRepository.last_issued_date(self, anno: int) -> date | None`
  - `InvoiceService.issue(self, invoice_id: UUID, data: InvoiceIssue, actor: Actor) -> InvoiceRead`
  - `InvoiceService._build_snapshot(self, invoice: Invoice, profile: FiscalSnapshot, actor: Actor) -> InvoiceSnapshot`
  - `InvoiceService._check_issue_date(self, data_emissione: date, anno_corrente: int) -> None`
  - `InvoiceService._party_from_customer(self, customer: Customer) -> PartySnapshot`
  - `InvoiceService._party_from_emitter(self, actor: Actor) -> PartySnapshot`

- [ ] **Step 1: Write the failing test for the single-threaded rules**

`packages/core/tests/test_invoice_issue.py`:

```python
"""Emission: the one irreversible creation in the product.

Everything here runs on the shared savepoint-backed `db_session`, which is fine for
the rules. The *race* is a separate file, because a single connection with a savepoint
cannot produce concurrency and a test that pretends otherwise proves nothing.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import (
    SNAPSHOT_VERSIONE,
    InvoiceCreate,
    InvoiceIssue,
    InvoiceLineIn,
)
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")
COLLABORATORE = Actor(id=None, type="user", role="collaboratore")
TODAY = date.today()


@pytest.fixture
def service(db_session: Session, tmp_path) -> InvoiceService:  # type: ignore[no-untyped-def]
    FiscalProfileService(db_session).upsert(FiscalProfileUpsert(codice_regime="RF19"), ADMIN)
    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Humancraft di Ivan Sala",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Vittorio Veneto 12",
            cap="20124",
            comune="Milano",
            provincia="MI",
            nazione="IT",
            email="someone@example.com",
        ),
        ADMIN,
    )
    return InvoiceService(db_session, LocalFileStorage(tmp_path / "documents"))


def _customer(db_session: Session, **overrides: object) -> UUID:
    payload: dict[str, object] = {
        "ragione_sociale": "Acme S.r.l.",
        "partita_iva": "12345678901",
        "codice_sdi": "ABCDEFG",
        "indirizzo": "Corso Italia 5",
        "cap": "00100",
        "comune": "Roma",
        "provincia": "RM",
        "nazione": "IT",
    }
    payload.update(overrides)
    customer = Customer(**payload)  # type: ignore[arg-type]
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _draft(service: InvoiceService, customer_id: UUID, prezzo: str = "1000.00") -> UUID:
    return service.create(
        InvoiceCreate(
            customer_id=customer_id,
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal(prezzo))],
        ),
        ADMIN,
    ).id


# --- the number ---------------------------------------------------------------------


def test_the_first_invoice_of_the_year_is_number_one(
    service: InvoiceService, db_session: Session
) -> None:
    invoice = service.issue(_draft(service, _customer(db_session)), InvoiceIssue(), ADMIN)
    assert invoice.stato == "emessa"
    assert invoice.anno == TODAY.year
    assert invoice.numero == 1
    assert invoice.data_emissione == TODAY


def test_numbers_are_consecutive(service: InvoiceService, db_session: Session) -> None:
    customer_id = _customer(db_session)
    numbers = [
        service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN).numero
        for _ in range(3)
    ]
    assert numbers == [1, 2, 3]


def test_the_counter_row_is_created_on_first_use_and_then_incremented(
    service: InvoiceService, db_session: Session
) -> None:
    customer_id = _customer(db_session)
    service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN)
    service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN)
    stored = db_session.execute(
        text("SELECT ultimo_numero FROM invoice_counters WHERE anno = :anno"),
        {"anno": TODAY.year},
    ).scalar_one()
    assert stored == 2


def test_a_failed_emission_consumes_no_number(
    service: InvoiceService, db_session: Session
) -> None:
    """The property a `SEQUENCE` cannot give: `nextval()` is non-transactional and
    does not roll back, so every aborted transaction would leave a permanent gap."""
    customer_id = _customer(db_session)
    service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN)

    broken = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)  # no lines
    with pytest.raises(ValidationFailed):
        service.issue(broken.id, InvoiceIssue(), ADMIN)

    assert service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN).numero == 2


def test_a_draft_that_failed_to_issue_is_still_a_draft(
    service: InvoiceService, db_session: Session
) -> None:
    customer_id = _customer(db_session)
    broken = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    with pytest.raises(ValidationFailed):
        service.issue(broken.id, InvoiceIssue(), ADMIN)
    again = service.get(broken.id, ADMIN)
    assert again.stato == "bozza"
    assert again.numero is None


# --- the date -----------------------------------------------------------------------


def test_the_issue_date_is_a_date_in_the_issuer_s_own_calendar(
    service: InvoiceService, db_session: Session
) -> None:
    """Never a UTC projection of an instant: `toISOString()` on 31 December at
    23:30 CET yields 1 January, i.e. the wrong fiscal year on an immutable
    document. `date.today()` is the local civil date, and `anno` is derived from it,
    so the year in the number and the year on the document cannot disagree."""
    invoice = service.issue(_draft(service, _customer(db_session)), InvoiceIssue(), ADMIN)
    assert invoice.data_emissione == TODAY
    assert invoice.anno == invoice.data_emissione.year


def test_back_dating_inside_the_current_year_is_allowed(
    service: InvoiceService, db_session: Session
) -> None:
    earlier = date(TODAY.year, 1, 2)
    invoice = service.issue(
        _draft(service, _customer(db_session)), InvoiceIssue(data_emissione=earlier), ADMIN
    )
    assert invoice.data_emissione == earlier
    assert invoice.anno == TODAY.year


def test_a_future_date_is_refused(service: InvoiceService, db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as caught:
        service.issue(
            _draft(service, _customer(db_session)),
            InvoiceIssue(data_emissione=TODAY + timedelta(days=1)),
            ADMIN,
        )
    assert caught.value.details["field"] == "data_emissione"


def test_a_date_before_the_first_of_january_is_refused(
    service: InvoiceService, db_session: Session
) -> None:
    """A closed year is closed. It is also the reason the fiscal profile is not
    historicised: no emission ever needs a previous period's parameters."""
    with pytest.raises(ValidationFailed) as caught:
        service.issue(
            _draft(service, _customer(db_session)),
            InvoiceIssue(data_emissione=date(TODAY.year - 1, 12, 31)),
            ADMIN,
        )
    assert caught.value.details["field"] == "data_emissione"


def test_the_register_must_stay_chronologically_monotonic(
    service: InvoiceService, db_session: Session
) -> None:
    """Read inside the locked transaction, where "the date of the previous number" is
    a safe thing to read."""
    customer_id = _customer(db_session)
    service.issue(
        _draft(service, customer_id), InvoiceIssue(data_emissione=date(TODAY.year, 6, 1)), ADMIN
    )
    with pytest.raises(ValidationFailed) as caught:
        service.issue(
            _draft(service, customer_id),
            InvoiceIssue(data_emissione=date(TODAY.year, 5, 31)),
            ADMIN,
        )
    assert caught.value.details["field"] == "data_emissione"


def test_the_same_date_as_the_previous_invoice_is_allowed(
    service: InvoiceService, db_session: Session
) -> None:
    customer_id = _customer(db_session)
    same = date(TODAY.year, 6, 1)
    service.issue(_draft(service, customer_id), InvoiceIssue(data_emissione=same), ADMIN)
    assert (
        service.issue(
            _draft(service, customer_id), InvoiceIssue(data_emissione=same), ADMIN
        ).numero
        == 2
    )


def test_the_due_date_comes_from_the_profile(
    service: InvoiceService, db_session: Session
) -> None:
    invoice = service.issue(_draft(service, _customer(db_session)), InvoiceIssue(), ADMIN)
    assert invoice.data_scadenza == invoice.data_emissione + timedelta(days=30)


# --- the refusals, each naming the field (criterion 9) ------------------------------


def test_an_invoice_with_no_lines_is_refused(
    service: InvoiceService, db_session: Session
) -> None:
    empty = service.create(InvoiceCreate(customer_id=_customer(db_session)), ADMIN)
    with pytest.raises(ValidationFailed) as caught:
        service.issue(empty.id, InvoiceIssue(), ADMIN)
    assert caught.value.details["field"] == "righe"


def test_a_total_of_zero_is_refused(service: InvoiceService, db_session: Session) -> None:
    """A TD01 at zero or below is not an invoice."""
    with pytest.raises(ValidationFailed) as caught:
        service.issue(_draft(service, _customer(db_session), prezzo="0.00"), InvoiceIssue(), ADMIN)
    assert caught.value.details["field"] == "totale"


def test_a_negative_total_is_refused(service: InvoiceService, db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as caught:
        service.issue(
            _draft(service, _customer(db_session), prezzo="-10.00"), InvoiceIssue(), ADMIN
        )
    assert caught.value.details["field"] == "totale"


def test_a_customer_with_neither_sdi_nor_pec_is_refused_before_the_number_is_taken(
    service: InvoiceService, db_session: Session
) -> None:
    customer_id = _customer(db_session, codice_sdi=None, pec=None)
    with pytest.raises(ValidationFailed) as caught:
        service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN)
    assert caught.value.details["entity"] == "customer"
    assert caught.value.details["field"] == "codice_sdi"
    # And nothing was consumed: the counter row does not even exist yet.
    assert (
        db_session.execute(
            text("SELECT count(*) FROM invoice_counters WHERE anno = :anno"),
            {"anno": TODAY.year},
        ).scalar_one()
        == 1
    )
    assert (
        db_session.execute(
            text("SELECT ultimo_numero FROM invoice_counters WHERE anno = :anno"),
            {"anno": TODAY.year},
        ).scalar_one()
        == 0
    )


@pytest.mark.parametrize("field", ["cap", "comune", "indirizzo", "provincia"])
def test_a_missing_address_part_is_refused_by_name(
    service: InvoiceService, db_session: Session, field: str
) -> None:
    customer_id = _customer(db_session, **{field: None})
    with pytest.raises(ValidationFailed) as caught:
        service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN)
    assert caught.value.details["field"] == field


def test_a_foreign_customer_is_refused_by_name(
    service: InvoiceService, db_session: Session
) -> None:
    """R12: `customers.partita_iva` accepts only 11 digits, so a foreign VAT number
    cannot even be stored. The slice declares foreign customers out of scope and says
    so, rather than issuing something the SdI will reject."""
    customer_id = _customer(db_session, nazione="DE")
    with pytest.raises(ValidationFailed) as caught:
        service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN)
    assert caught.value.details["field"] == "nazione"


def test_issuing_requires_admin_not_merely_write(
    service: InvoiceService, db_session: Session
) -> None:
    """Spec 11: `collaboratore` is "writing entities, excluding configuration", and
    consuming a number of the fiscal register sits closer to configuration."""
    with pytest.raises(PermissionDenied) as caught:
        service.issue(_draft(service, _customer(db_session)), InvoiceIssue(), COLLABORATORE)
    assert caught.value.details["required_roles"] == ["admin"]


# --- the freeze ---------------------------------------------------------------------


def test_the_snapshot_freezes_both_parties_and_the_fiscal_parameters(
    service: InvoiceService, db_session: Session
) -> None:
    invoice_id = _draft(service, _customer(db_session))
    issued = service.issue(invoice_id, InvoiceIssue(), ADMIN)
    assert issued.snapshot_versione == SNAPSHOT_VERSIONE
    stored = db_session.execute(
        text("SELECT snapshot FROM invoices WHERE id = :id"), {"id": invoice_id}
    ).scalar_one()
    assert stored["versione"] == SNAPSHOT_VERSIONE
    assert stored["cliente"]["ragione_sociale"] == "Acme S.r.l."
    assert stored["emittente"]["ragione_sociale"] == "Humancraft di Ivan Sala"
    assert stored["fiscale"]["codice_regime"] == "RF19"


def test_a_customer_who_moves_does_not_rewrite_an_issued_invoice(
    service: InvoiceService, db_session: Session
) -> None:
    """Spec 8.3, the whole point of the snapshot."""
    customer_id = _customer(db_session)
    invoice_id = _draft(service, customer_id)
    service.issue(invoice_id, InvoiceIssue(), ADMIN)
    db_session.execute(
        text("UPDATE customers SET comune = 'Torino' WHERE id = :id"), {"id": customer_id}
    )
    stored = db_session.execute(
        text("SELECT snapshot FROM invoices WHERE id = :id"), {"id": invoice_id}
    ).scalar_one()
    assert stored["cliente"]["comune"] == "Roma"


def test_issuing_records_an_activity_naming_the_number(
    service: InvoiceService, db_session: Session
) -> None:
    invoice = service.issue(_draft(service, _customer(db_session)), InvoiceIssue(), ADMIN)
    entries = ActivityService(db_session).timeline("invoice", invoice.id)
    issued = [entry for entry in entries if entry.kind == "issued"]
    assert issued and issued[0].payload["numero"] == 1


# --- issuing from a proforma --------------------------------------------------------


def test_issuing_a_confirmed_proforma_creates_a_new_row_and_consumes_the_proforma(
    service: InvoiceService, db_session: Session
) -> None:
    """Spec 5: not a state change in place. Two rows -- one always mutable, one always
    frozen -- so "immutable after emission" is a property of something that was never
    mutable, rather than one verifiable only by reconstructing the history."""
    customer_id = _customer(db_session)
    proforma = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            tipo="proforma",
            causale="Consulenza agosto",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    service.confirm_proforma(proforma.id, ADMIN)

    issued = service.issue(proforma.id, InvoiceIssue(), ADMIN)
    assert issued.id != proforma.id
    assert issued.tipo == "fattura"
    assert issued.stato == "emessa"
    assert issued.numero == 1
    assert issued.origine_proforma_id == proforma.id
    assert issued.causale == "Consulenza agosto"
    assert [r.descrizione for r in service.lines(issued.id, ADMIN)] == ["Consulenza"]
    assert issued.totale == Decimal("500.00")

    consumed = service.get(proforma.id, ADMIN)
    assert consumed.stato == "consumata"
    assert consumed.numero is None
    assert [r.descrizione for r in service.lines(proforma.id, ADMIN)] == ["Consulenza"]


def test_an_unconfirmed_proforma_cannot_be_issued(
    service: InvoiceService, db_session: Session
) -> None:
    proforma = service.create(
        InvoiceCreate(
            customer_id=_customer(db_session),
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    with pytest.raises(Conflict):
        service.issue(proforma.id, InvoiceIssue(), ADMIN)


def test_a_consumed_proforma_cannot_be_issued_twice(
    service: InvoiceService, db_session: Session
) -> None:
    customer_id = _customer(db_session)
    proforma = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    service.confirm_proforma(proforma.id, ADMIN)
    service.issue(proforma.id, InvoiceIssue(), ADMIN)
    with pytest.raises(Conflict):
        service.issue(proforma.id, InvoiceIssue(), ADMIN)


def test_an_already_issued_invoice_cannot_be_issued_again(
    service: InvoiceService, db_session: Session
) -> None:
    invoice_id = _draft(service, _customer(db_session))
    service.issue(invoice_id, InvoiceIssue(), ADMIN)
    with pytest.raises(Conflict):
        service.issue(invoice_id, InvoiceIssue(), ADMIN)


def test_a_missing_invoice_is_not_found(service: InvoiceService) -> None:
    from uuid import uuid4

    with pytest.raises(NotFound):
        service.issue(uuid4(), InvoiceIssue(), ADMIN)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_issue.py -v`
Expected: FAIL with `AttributeError: 'InvoiceService' object has no attribute 'issue'`

- [ ] **Step 3: Add the two repository methods, above `list`**

In `packages/core/src/pigrocrm/core/invoices/repository.py`, insert these **before** `def list` (the `list`-last rule is unconditional, and `lines` above already returns a `list[...]`):

```python
    def lock_counter(self, anno: int) -> InvoiceCounter:
        """The year's counter row, locked for the rest of this transaction.

        Two statements, in this order and for these reasons:

        1. `INSERT ... ON CONFLICT (anno) DO NOTHING` -- two concurrent
           first-invoices-of-the-year: one inserts, the other does nothing, both carry
           on. Without `ON CONFLICT` the loser would take a `UniqueViolation` and have
           to be retried by the caller.
        2. `SELECT ... FOR UPDATE` -- from here on every other emission for the same
           year waits. This is deliberately **the first row lock the emission
           transaction takes**, and no later statement in that transaction takes a lock
           a concurrent emission could already hold, so two emissions cannot deadlock
           against each other.

        Not a `SEQUENCE`, and that is the whole design: `nextval()` is
        non-transactional by design and does not roll back, so a sequence guarantees
        uniqueness while prohibiting exactly the property required here -- the absence
        of gaps. Every aborted transaction would leave a permanent hole in the
        register.

        The `SELECT` is `.one()`, not `.first()`: after step 1 the row must exist, and
        a `None` here would mean the insert silently did nothing for a reason worth
        crashing over rather than working around.
        """
        self.session.execute(
            text(
                "INSERT INTO invoice_counters (anno, ultimo_numero) "
                "VALUES (:anno, 0) ON CONFLICT (anno) DO NOTHING"
            ),
            {"anno": anno},
        )
        stmt = select(InvoiceCounter).where(InvoiceCounter.anno == anno).with_for_update()
        return self.session.execute(stmt).scalars().one()

    def last_issued_date(self, anno: int) -> date | None:
        """The `data_emissione` of the highest-numbered invoice of `anno`.

        Safe to read only *after* `lock_counter` has run, which is the one place it is
        called from: without the lock, a concurrent emission could commit a later
        number between this read and the write that depends on it. Includes
        `annullata` rows on purpose -- an annulled invoice keeps its number and its
        place in the chronological order, which is what makes the register monotonic
        rather than merely gap-free.
        """
        stmt = (
            select(Invoice.data_emissione)
            .where(Invoice.anno == anno, Invoice.numero.is_not(None))
            .order_by(Invoice.numero.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()
```

and extend that module's imports:

```python
from datetime import date

from pigrocrm.core.invoices.models import (
    PROFORMA_SEQUENCE_NAME,
    Invoice,
    InvoiceCounter,
    InvoiceLine,
)
```

- [ ] **Step 4: Implement `issue`**

In `packages/core/src/pigrocrm/core/invoices/service.py`, add these imports:

```python
from datetime import timedelta

from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.invoices.fatturapa import check_party_exportable, check_recipient_routing
from pigrocrm.core.invoices.schemas import (
    SNAPSHOT_VERSIONE,
    InvoiceIssue,
    InvoiceSnapshot,
    PartySnapshot,
)
```

add to `__init__`:

```python
        self.emitter = EmitterProfileService(session)
```

and add the following methods **above** `get` (so `lines` and `list` keep their required positions):

```python
    def _party_from_customer(self, customer: Customer) -> PartySnapshot:
        return PartySnapshot(
            ragione_sociale=customer.ragione_sociale,
            partita_iva=customer.partita_iva,
            codice_fiscale=customer.codice_fiscale,
            codice_sdi=customer.codice_sdi,
            pec=customer.pec,
            indirizzo=customer.indirizzo or "",
            cap=customer.cap or "",
            comune=customer.comune or "",
            provincia=customer.provincia or "",
            nazione=customer.nazione,
            email=customer.email,
            telefono=customer.telefono,
            sito_web=customer.sito_web,
        )

    def _party_from_emitter(self, actor: Actor) -> PartySnapshot:
        """The issuer's identity from `emitter_profile` (slice 2).

        `emitter_profile.regime_fiscale` is deliberately not read here: it is a
        human-readable caption for the PDF header, `String(200)` of free text, and the
        machine value the SdI validates is `fiscal_profile.codice_regime`. Two columns,
        two jobs; conflating them is how a caption ends up inside `RegimeFiscale`.
        """
        profile = self.emitter.get(actor)
        return PartySnapshot(
            ragione_sociale=profile.ragione_sociale,
            partita_iva=profile.partita_iva,
            codice_fiscale=profile.codice_fiscale,
            codice_sdi=profile.codice_sdi,
            pec=profile.pec,
            indirizzo=profile.indirizzo or "",
            cap=profile.cap or "",
            comune=profile.comune or "",
            provincia=profile.provincia or "",
            nazione=profile.nazione,
            email=profile.email,
            telefono=profile.telefono,
            sito_web=profile.sito_web,
        )

    def _build_snapshot(self, invoice: Invoice, profile: FiscalSnapshot, actor: Actor) -> InvoiceSnapshot:
        customer = self.session.get(Customer, invoice.customer_id)
        if customer is None:  # pragma: no cover - the FK makes this unreachable
            raise NotFound("customer", invoice.customer_id)
        return InvoiceSnapshot(
            versione=SNAPSHOT_VERSIONE,
            emittente=self._party_from_emitter(actor),
            cliente=self._party_from_customer(customer),
            fiscale=profile,
        )

    def _check_issue_date(self, data_emissione: date, anno_corrente: int) -> None:
        """Two limits, both from spec 6.2.

        `data_emissione` is a `date` in the issuer's own calendar, never the UTC
        projection of an instant: `toISOString()` on 31 December at 23:30 CET yields
        1 January, which puts an immutable document in the wrong fiscal year. That is
        the defect this whole method exists around, and `date.today()` is the fix --
        there is no instant here to mis-project.
        """
        if data_emissione > date.today():
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "una fattura non si emette con data futura",
                expected=f"una data non successiva a {date.today().isoformat()}",
            )
        if data_emissione < date(anno_corrente, 1, 1):
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "un anno chiuso e' chiuso: non si inserisce nel registro di un anno "
                "precedente dopo che ne e' iniziato uno nuovo",
                expected=f"una data dal {anno_corrente}-01-01 in poi",
            )

    def issue(self, invoice_id: UUID, data: InvoiceIssue, actor: Actor) -> InvoiceRead:
        """Consume a register number. **One transaction, in this exact order.**

        `invoice_id` names either a `bozza` **fattura**, issued in place, or a
        `confermata` **proforma**, in which case a *new* `emessa` row is created with
        the proforma's lines copied and `origine_proforma_id` pointing back at it, and
        the proforma is marked `consumata` (spec 5). One method, because emitting from
        scratch and from a proforma share the lock, the validations, the freezing and
        the numbering, and splitting them would mean two paths to keep aligned on
        exactly the part that must not diverge.

        Ordering, and why each step is where it is:

        1. resolve the source row and the issue date, and check the date against
           "not in the future, not before 1 January of the current year". No lock yet:
           these are pure checks on the caller's own input;
        2. `lock_counter(anno)` -- the **first** row lock this transaction takes;
        3. every fiscal validation, the totals, and the chronological-monotonicity
           check. All of it after the lock, so "the date of the previous number" is a
           safe thing to read, and all of it *before* the counter is touched, so a
           refusal never even reaches the increment;
        4. increment the counter, write the row with `(anno, numero)`, write the
           frozen `snapshot`, write the activity;
        5. `COMMIT`.

        **The number does not exist before the commit.** If any step fails, the
        rollback returns `ultimo_numero` to its previous value and nothing was
        consumed -- the property a `SEQUENCE` does not have.

        The PDF and the XML are produced **after** this commit, in a second
        transaction, from the snapshot. Holding a row lock for the duration of a Typst
        subprocess would serialise every emission on PDF compile time, and an invoice
        is a legal fact independent of its printout: if the render fails, the invoice
        exists with its number and its artefacts regenerate deterministically. That is
        the one documented exception to "one service method = one transaction", and
        spec 3 mandates it.
        """
        actor.require_admin("issue_invoice")
        source = self._require(invoice_id)
        data_emissione = data.data_emissione or date.today()
        anno = data_emissione.year
        self._check_issue_date(data_emissione, date.today().year)

        from_proforma = source.tipo == "proforma"
        if from_proforma:
            if source.stato != "confermata":
                raise Conflict(
                    ENTITY,
                    "solo una proforma confermata si converte in fattura",
                    stato_attuale=source.stato,
                    stato_richiesto="confermata",
                )
        elif source.stato != "bozza":
            raise Conflict(
                ENTITY,
                f"una fattura in stato '{source.stato}' e' gia' stata emessa: "
                "una correzione e' un annullamento e una nuova fattura",
                stato_attuale=source.stato,
            )

        # Step 2. From here on, every other emission for this year waits.
        counter = self.repo.lock_counter(anno)

        # Step 3. Validations and totals, after the lock and before the increment.
        _, profile = self._regime()
        snapshot = self._build_snapshot(source, profile, actor)
        check_party_exportable(snapshot.emittente, "emitter_profile")
        check_party_exportable(snapshot.cliente, "customer")
        check_recipient_routing(snapshot.cliente)

        righe = self.repo.lines(source.id)
        if not righe:
            raise ValidationFailed(
                ENTITY, "righe", "una fattura senza righe non si emette",
                expected="almeno una riga",
            )
        computed = tuple(
            ComputedLine(
                numero_linea=r.numero_linea,
                descrizione=r.descrizione,
                quantita=r.quantita,
                unita_misura=r.unita_misura,
                prezzo_unitario=r.prezzo_unitario,
                sconto_percentuale=r.sconto_percentuale,
                sconto_importo=r.sconto_importo,
                prezzo_totale=r.prezzo_totale,
                aliquota_iva=r.aliquota_iva,
                natura=r.natura,
                riferimento_normativo=r.riferimento_normativo,
            )
            for r in righe
        )
        riepilogo = build_riepilogo(computed)
        imponibile, imposta, totale = sum_totals(riepilogo)
        if totale <= ZERO:
            raise ValidationFailed(
                ENTITY,
                "totale",
                "una TD01 a zero o negativa non e' una fattura",
                expected="un totale maggiore di zero",
            )

        previous = self.repo.last_issued_date(anno)
        if previous is not None and data_emissione < previous:
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "il registro deve restare cronologicamente monotono rispetto al numero: "
                f"l'ultima fattura del {anno} porta la data {previous.isoformat()}",
                expected=f"una data dal {previous.isoformat()} in poi",
            )

        # Step 4. Increment, write, freeze.
        counter.ultimo_numero += 1
        numero = counter.ultimo_numero

        target = source
        if from_proforma:
            target = self.repo.add(
                Invoice(
                    customer_id=source.customer_id,
                    deal_id=source.deal_id,
                    tipo="fattura",
                    stato="bozza",
                    tipo_documento=TIPO_DOCUMENTO,
                    divisa=DIVISA,
                    causale=source.causale,
                    note_interne=source.note_interne,
                    imponibile=ZERO,
                    imposta=ZERO,
                    bollo=ZERO,
                    totale=ZERO,
                    stato_pagamento="da_incassare",
                    origine_proforma_id=source.id,
                    custom_fields=dict(source.custom_fields),
                )
            )
            self._persist_lines(target, computed)
            source.stato = "consumata"

        strategy = resolve_regime(profile.codice_regime)
        target.stato = "emessa"
        target.anno = anno
        target.numero = numero
        target.data_emissione = data_emissione
        target.data_scadenza = data_emissione + timedelta(days=profile.giorni_scadenza)
        target.imponibile = imponibile
        target.imposta = imposta
        target.totale = totale
        target.bollo = strategy.bollo(riepilogo, profile)
        target.snapshot = snapshot.model_dump(mode="json")
        target.snapshot_versione = SNAPSHOT_VERSIONE

        self.activities.record(
            ENTITY,
            target.id,
            "issued",
            actor,
            {
                "anno": anno,
                "numero": numero,
                "totale": str(target.totale),
                "origine_proforma_id": str(source.id) if from_proforma else None,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as exc:
            # The partial unique index `uq_invoices_anno_numero` is the net under the
            # row lock, not the mechanism (spec 3). Reaching it means something wrote
            # a number without taking the lock -- an importer, a direct INSERT, a
            # second service -- and this is what makes that failure observable instead
            # of a silent duplicate. The rollback is mandatory or the caller's session
            # is unusable on its next statement.
            self.session.rollback()
            raise Conflict(
                ENTITY,
                "un altro processo ha scritto lo stesso numero senza passare dal "
                "contatore: riprova e verifica il registro",
                anno=anno,
                numero=numero,
            ) from exc
        return InvoiceRead.model_validate(target)
```

- [ ] **Step 5: Run the single-threaded tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_issue.py packages/core/tests/test_module_imports.py -v`
Expected: PASS

- [ ] **Step 6: Write the concurrency test**

`packages/core/tests/test_invoice_numbering_concurrency.py`:

```python
"""Spec 14.3, run for real.

The shared `db_session` fixture binds one connection and wraps every test in a
savepoint that is rolled back, which is exactly right for the other suites and
useless here: a single connection cannot contend with itself, so a "concurrency" test
written on it would pass no matter what the code did. Every session below is opened
from `db_engine` and commits for real, and the fixture cleans up after itself.
"""

import threading
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import session_factory
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceIssue, InvoiceLineIn
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")
EMISSIONS = 20
FAILURES = 10
ANNO = date.today().year


@pytest.fixture
def world(db_engine: Engine, tmp_path):  # type: ignore[no-untyped-def]
    """A committed customer, emitter profile and fiscal profile, plus a teardown that
    physically removes everything this test wrote.

    Physical `DELETE`s, not a soft delete: `ck_invoices_no_delete_once_consumed`
    refuses `deleted_at` on a numbered row, which is the point of the constraint, and
    a test must not be the reason it gets weakened.
    """
    factory = session_factory(db_engine)
    with factory() as setup:
        customer = Customer(
            ragione_sociale="Acme S.r.l.",
            partita_iva="12345678901",
            codice_sdi="ABCDEFG",
            indirizzo="Corso Italia 5",
            cap="00100",
            comune="Roma",
            provincia="RM",
            nazione="IT",
        )
        setup.add(customer)
        setup.flush()
        customer_id = customer.id
        FiscalProfileService(setup).upsert(FiscalProfileUpsert(codice_regime="RF19"), ADMIN)
        EmitterProfileService(setup).upsert(
            EmitterProfileUpsert(
                ragione_sociale="Humancraft di Ivan Sala",
                partita_iva="14518240966",
                codice_fiscale="HMCRFT00A01H501K",
                indirizzo="Via Vittorio Veneto 12",
                cap="20124",
                comune="Milano",
                provincia="MI",
                nazione="IT",
                email="someone@example.com",
            ),
            ADMIN,
        )
        setup.commit()
    try:
        yield factory, customer_id, tmp_path
    finally:
        with factory() as cleanup:
            cleanup.execute(text("DELETE FROM invoice_lines"))
            cleanup.execute(text("DELETE FROM activities WHERE entity_type = 'invoice'"))
            cleanup.execute(text("UPDATE invoices SET origine_proforma_id = NULL"))
            cleanup.execute(text("DELETE FROM invoices"))
            cleanup.execute(text("DELETE FROM invoice_counters"))
            cleanup.execute(text("DELETE FROM fiscal_profile"))
            cleanup.execute(text("DELETE FROM emitter_profile"))
            cleanup.execute(
                text("DELETE FROM customers WHERE id = :id"), {"id": customer_id}
            )
            cleanup.commit()


def _make_draft(factory, storage_root, customer_id: UUID) -> UUID:  # type: ignore[no-untyped-def]
    with factory() as session:
        return (
            InvoiceService(session, LocalFileStorage(storage_root))
            .create(
                InvoiceCreate(
                    customer_id=customer_id,
                    righe=[
                        InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("100.00"))
                    ],
                ),
                ADMIN,
            )
            .id
        )


def test_twenty_concurrent_emissions_produce_one_to_twenty_with_no_gap(world) -> None:  # type: ignore[no-untyped-def]
    """Spec 14.3, first half. Twenty threads, each on its own session and its own
    transaction, all issuing at once: twenty invoices, numbers 1 to 20, no duplicate
    and no gap, verified with a `SELECT` against the database rather than against what
    the service returned."""
    factory, customer_id, tmp_path = world
    drafts = [_make_draft(factory, tmp_path / "documents", customer_id) for _ in range(EMISSIONS)]
    start = threading.Barrier(EMISSIONS)
    results: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def emit(draft_id: UUID) -> None:
        try:
            start.wait(timeout=30)
            with factory() as session:
                issued = InvoiceService(session, LocalFileStorage(tmp_path / "documents")).issue(
                    draft_id, InvoiceIssue(), ADMIN
                )
            with lock:
                results.append(issued.numero or 0)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=emit, args=(d,)) for d in drafts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == [], f"emissioni fallite: {errors}"
    assert sorted(results) == list(range(1, EMISSIONS + 1))

    with factory() as check:
        rows = check.execute(
            text("SELECT numero FROM invoices WHERE anno = :anno ORDER BY numero"),
            {"anno": ANNO},
        ).scalars().all()
        counter = check.execute(
            text("SELECT ultimo_numero FROM invoice_counters WHERE anno = :anno"),
            {"anno": ANNO},
        ).scalar_one()
    assert list(rows) == list(range(1, EMISSIONS + 1))
    assert counter == EMISSIONS


def test_a_failure_between_the_counter_update_and_the_commit_consumes_nothing(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Spec 14.3, second half -- the property a `SEQUENCE` cannot provide.

    The error is injected **after** the counter has been incremented in the
    transaction and **before** the commit, which is the only window where a
    sequence-based design would already have burnt the number. `ActivityService.record`
    is the last statement `issue` runs before committing, so patching it puts the
    failure exactly there without inventing a seam in production code for a test to
    pull.
    """
    factory, customer_id, tmp_path = world
    storage_root = tmp_path / "documents"

    # Phase 1: twenty successful emissions, so there is a real register to protect.
    for _ in range(EMISSIONS):
        with factory() as session:
            InvoiceService(session, LocalFileStorage(storage_root)).issue(
                _make_draft(factory, storage_root, customer_id), InvoiceIssue(), ADMIN
            )

    # Phase 2: ten emissions that die between the UPDATE and the COMMIT.
    original = ActivityService.record

    def explode(self, entity_type, entity_id, kind, actor, payload=None):  # type: ignore[no-untyped-def]
        if kind == "issued":
            raise RuntimeError("iniezione fra l'UPDATE del contatore e il COMMIT")
        return original(self, entity_type, entity_id, kind, actor, payload)

    monkeypatch.setattr(ActivityService, "record", explode)
    for _ in range(FAILURES):
        draft_id = _make_draft(factory, storage_root, customer_id)
        with factory() as session:
            with pytest.raises(RuntimeError):
                InvoiceService(session, LocalFileStorage(storage_root)).issue(
                    draft_id, InvoiceIssue(), ADMIN
                )
    monkeypatch.undo()

    with factory() as check:
        counter = check.execute(
            text("SELECT ultimo_numero FROM invoice_counters WHERE anno = :anno"),
            {"anno": ANNO},
        ).scalar_one()
        rows = check.execute(
            text("SELECT numero FROM invoices WHERE anno = :anno ORDER BY numero"),
            {"anno": ANNO},
        ).scalars().all()
    assert counter == EMISSIONS, "un'emissione fallita ha bruciato un numero"
    assert list(rows) == list(range(1, EMISSIONS + 1))

    # Phase 3: the next successful emission takes 21, not 31.
    with factory() as session:
        issued = InvoiceService(session, LocalFileStorage(storage_root)).issue(
            _make_draft(factory, storage_root, customer_id), InvoiceIssue(), ADMIN
        )
    assert issued.numero == EMISSIONS + 1


def test_two_first_invoices_of_a_year_do_not_collide_on_the_counter_insert(
    world,
) -> None:  # type: ignore[no-untyped-def]
    """`INSERT ... ON CONFLICT (anno) DO NOTHING` before the `SELECT ... FOR UPDATE`:
    two concurrent first-invoices-of-the-year both proceed, one having inserted the
    row and the other having done nothing. Without `ON CONFLICT` the loser would take
    a `UniqueViolation` the caller would have to retry."""
    factory, customer_id, tmp_path = world
    drafts = [_make_draft(factory, tmp_path / "documents", customer_id) for _ in range(2)]
    start = threading.Barrier(2)
    numbers: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def emit(draft_id: UUID) -> None:
        try:
            start.wait(timeout=30)
            with factory() as session:
                issued = InvoiceService(session, LocalFileStorage(tmp_path / "documents")).issue(
                    draft_id, InvoiceIssue(), ADMIN
                )
            with lock:
                numbers.append(issued.numero or 0)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=emit, args=(d,)) for d in drafts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert sorted(numbers) == [1, 2]
```

- [ ] **Step 7: Run the concurrency test to verify it fails, then passes**

Run: `uv run pytest packages/core/tests/test_invoice_numbering_concurrency.py -v`
Expected: PASS once `lock_counter` is in place. To prove the test has teeth before trusting it, temporarily replace `lock_counter`'s body with a plain `SELECT` (no `.with_for_update()`), re-run, and watch `test_twenty_concurrent_emissions_produce_one_to_twenty_with_no_gap` fail with duplicate numbers or an `IntegrityError` on `uq_invoices_anno_numero`. Restore the `FOR UPDATE` before committing. A concurrency test that has never been seen to fail is a concurrency test nobody has verified.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/repository.py packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_issue.py packages/core/tests/test_invoice_numbering_concurrency.py
git commit -m "feat(invoices): gap-free per-year numbering under a row lock"
```

---

### Task 11: Immutability, annulment and external transmission

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/service.py` (add `annul` and `mark_transmitted_externally`)
- Test: `packages/core/tests/test_invoice_immutability.py`

**Interfaces:**
- Consumes: Task 10's `issue`; `InvoiceAnnul`, `InvoiceTransmitted` (Task 4).
- Produces:
  - `InvoiceService.annul(self, invoice_id: UUID, data: InvoiceAnnul, actor: Actor) -> InvoiceRead`
  - `InvoiceService.mark_transmitted_externally(self, invoice_id: UUID, data: InvoiceTransmitted, actor: Actor) -> InvoiceRead`

- [ ] **Step 1: Write the failing test**

`packages/core/tests/test_invoice_immutability.py`:

```python
"""Spec 4: an issued invoice is a fiscal document, not a CRM row with an extra state.

A correction is a new document, and which route is available is not the user's choice
-- it depends on a verifiable fact: whether the file has left for the intermediary.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, ImmutableField, PermissionDenied, ValidationFailed
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import (
    InvoiceAnnul,
    InvoiceCreate,
    InvoiceIssue,
    InvoiceLineIn,
    InvoiceTransmitted,
    InvoiceUpdate,
    PaymentState,
)
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")
COLLABORATORE = Actor(id=None, type="user", role="collaboratore")
TODAY = date.today()


@pytest.fixture
def service(db_session: Session, tmp_path) -> InvoiceService:  # type: ignore[no-untyped-def]
    FiscalProfileService(db_session).upsert(FiscalProfileUpsert(codice_regime="RF19"), ADMIN)
    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Humancraft di Ivan Sala",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Vittorio Veneto 12",
            cap="20124",
            comune="Milano",
            provincia="MI",
            nazione="IT",
            email="someone@example.com",
        ),
        ADMIN,
    )
    return InvoiceService(db_session, LocalFileStorage(tmp_path / "documents"))


@pytest.fixture
def customer_id(db_session: Session) -> UUID:
    customer = Customer(
        ragione_sociale="Acme S.r.l.",
        partita_iva="12345678901",
        codice_sdi="ABCDEFG",
        indirizzo="Corso Italia 5",
        cap="00100",
        comune="Roma",
        provincia="RM",
        nazione="IT",
    )
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _issue(service: InvoiceService, customer_id: UUID) -> UUID:
    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            causale="Consulenza",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("1000.00"))],
        ),
        ADMIN,
    )
    return service.issue(draft.id, InvoiceIssue(), ADMIN).id


# --- annulment: the correction route for an invoice that never left ------------------


def test_annulling_keeps_the_number_and_the_row_readable(
    service: InvoiceService, customer_id: UUID
) -> None:
    """The equivalent of a struck-through page in a paper register, and what preserves
    the gap-free property of spec 3: without it, "no gaps" would be worth nothing."""
    invoice_id = _issue(service, customer_id)
    annulled = service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), ADMIN)
    assert annulled.stato == "annullata"
    assert annulled.numero == 1
    assert annulled.annullata_il == TODAY
    assert annulled.motivo_annullamento == "importo errato"
    assert annulled.totale == Decimal("1000.00")
    assert len(service.lines(invoice_id, ADMIN)) == 1


def test_a_corrected_invoice_takes_the_next_number_not_the_annulled_one(
    service: InvoiceService, customer_id: UUID
) -> None:
    first = _issue(service, customer_id)
    service.annul(first, InvoiceAnnul(motivo="importo errato"), ADMIN)
    assert service.get(_issue(service, customer_id), ADMIN).numero == 2


def test_an_annulment_needs_a_reason(service: InvoiceService, customer_id: UUID) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InvoiceAnnul(motivo="")


def test_a_draft_cannot_be_annulled(service: InvoiceService, customer_id: UUID) -> None:
    """It has no number to preserve, so it is deleted, not struck through."""
    draft = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    with pytest.raises(Conflict):
        service.annul(draft.id, InvoiceAnnul(motivo="ripensamento"), ADMIN)


def test_annulling_twice_is_refused(service: InvoiceService, customer_id: UUID) -> None:
    invoice_id = _issue(service, customer_id)
    service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), ADMIN)
    with pytest.raises(Conflict):
        service.annul(invoice_id, InvoiceAnnul(motivo="ancora"), ADMIN)


def test_annulling_requires_admin(service: InvoiceService, customer_id: UUID) -> None:
    invoice_id = _issue(service, customer_id)
    with pytest.raises(PermissionDenied):
        service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), COLLABORATORE)


def test_annulling_records_an_activity_with_the_reason(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), ADMIN)
    entries = ActivityService(db_session).timeline("invoice", invoice_id)
    annulled = [entry for entry in entries if entry.kind == "annulled"]
    assert annulled and annulled[0].payload["motivo"] == "importo errato"


# --- transmission: the fact that decides which correction route exists --------------


def test_marking_transmitted_is_a_one_way_door(
    service: InvoiceService, customer_id: UUID
) -> None:
    """Spec 4: settable once, then frozen. This column is the reason annulment is safe
    rather than optimistic -- without it the system could not tell an invoice that
    never left from one already deposited with the Agenzia delle Entrate."""
    invoice_id = _issue(service, customer_id)
    marked = service.mark_transmitted_externally(
        invoice_id, InvoiceTransmitted(data=TODAY), ADMIN
    )
    assert marked.trasmessa_esternamente_il == TODAY
    with pytest.raises(ImmutableField) as caught:
        service.mark_transmitted_externally(
            invoice_id, InvoiceTransmitted(data=TODAY), ADMIN
        )
    assert caught.value.details["field"] == "trasmessa_esternamente_il"


def test_a_transmitted_invoice_cannot_be_annulled(
    service: InvoiceService, customer_id: UUID
) -> None:
    """From here the correction needs a credit note, which this slice does not produce
    -- so it happens outside PigroCRM and the application says so, instead of offering
    a button that pretends to solve it."""
    invoice_id = _issue(service, customer_id)
    service.mark_transmitted_externally(invoice_id, InvoiceTransmitted(data=TODAY), ADMIN)
    with pytest.raises(Conflict) as caught:
        service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), ADMIN)
    assert "nota di credito" in caught.value.message


def test_a_future_transmission_date_is_refused(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    with pytest.raises(ValidationFailed) as caught:
        service.mark_transmitted_externally(
            invoice_id, InvoiceTransmitted(data=TODAY + timedelta(days=1)), ADMIN
        )
    assert caught.value.details["field"] == "trasmessa_esternamente_il"


def test_a_transmission_date_before_the_issue_date_is_refused(
    service: InvoiceService, customer_id: UUID
) -> None:
    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("100.00"))],
        ),
        ADMIN,
    )
    issued = service.issue(draft.id, InvoiceIssue(data_emissione=TODAY), ADMIN)
    with pytest.raises(ValidationFailed):
        service.mark_transmitted_externally(
            issued.id, InvoiceTransmitted(data=TODAY - timedelta(days=1)), ADMIN
        )


def test_a_draft_cannot_be_marked_transmitted(
    service: InvoiceService, customer_id: UUID
) -> None:
    draft = service.create(InvoiceCreate(customer_id=customer_id), ADMIN)
    with pytest.raises(Conflict):
        service.mark_transmitted_externally(draft.id, InvoiceTransmitted(data=TODAY), ADMIN)


def test_marking_transmitted_requires_admin(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    with pytest.raises(PermissionDenied):
        service.mark_transmitted_externally(
            invoice_id, InvoiceTransmitted(data=TODAY), COLLABORATORE
        )


# --- what stays mutable, and what the database refuses ------------------------------


def test_collection_stays_mutable_on_an_annulled_invoice_is_refused_but_on_an_issued_one_is_not(
    service: InvoiceService, customer_id: UUID
) -> None:
    """Collection is a subsequent fact on a live invoice; on a struck-through one
    there is nothing to collect."""
    live = _issue(service, customer_id)
    assert (
        service.set_payment_state(
            live, PaymentState(stato_pagamento="incassato", data_incasso=TODAY), ADMIN
        ).stato_pagamento
        == "incassato"
    )
    annulled = _issue(service, customer_id)
    service.annul(annulled, InvoiceAnnul(motivo="importo errato"), ADMIN)
    with pytest.raises(Conflict):
        service.set_payment_state(
            annulled, PaymentState(stato_pagamento="incassato", data_incasso=TODAY), ADMIN
        )


def test_the_internal_notes_and_custom_fields_stay_mutable_forever(
    service: InvoiceService, customer_id: UUID
) -> None:
    """They appear on no artefact, so they are not part of the document."""
    invoice_id = _issue(service, customer_id)
    service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), ADMIN)
    assert (
        service.update(invoice_id, InvoiceUpdate(note_interne="sostituita da 2/2026"), ADMIN)
        .note_interne
        == "sostituita da 2/2026"
    )


def test_the_soft_delete_of_an_issued_invoice_fails_in_raw_sql_too(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    """Spec 14.4 is explicit that the database must enforce this, not the service:
    an invariant only the service defends is one a psql session walks past."""
    invoice_id = _issue(service, customer_id)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE invoices SET deleted_at = now() WHERE id = :id"), {"id": invoice_id}
        )
    db_session.rollback()


def test_an_annulled_invoice_still_cannot_be_soft_deleted(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), ADMIN)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE invoices SET deleted_at = now() WHERE id = :id"), {"id": invoice_id}
        )
    db_session.rollback()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_immutability.py -v`
Expected: FAIL with `AttributeError: 'InvoiceService' object has no attribute 'annul'`

- [ ] **Step 3: Implement**

In `packages/core/src/pigrocrm/core/invoices/service.py`, add these two methods immediately after `issue` (still above `get`):

```python
    def annul(self, invoice_id: UUID, data: InvoiceAnnul, actor: Actor) -> InvoiceRead:
        """Strike the page through; keep the number.

        The number **stays consumed** and the row stays readable: that is what
        preserves the gap-free property of spec 3, which would otherwise be worth
        nothing -- a number that can disappear is a gap with extra steps.

        Refused once the file has been handed to the intermediary. From that point the
        correction requires a credit note (`TD04`), which this slice does not produce
        for a structural reason rather than as a deferral: a credit note corrects an
        invoice **already accepted by the SdI**, and nothing here is transmitted. So
        the application says where the correction has to happen, instead of offering a
        button that pretends to solve it.
        """
        actor.require_admin("annul_invoice")
        invoice = self._require(invoice_id)
        if invoice.stato != "emessa":
            raise Conflict(
                ENTITY,
                "si annulla solo una fattura emessa: una bozza si elimina, "
                "una fattura gia' annullata non si annulla due volte",
                stato_attuale=invoice.stato,
            )
        if invoice.trasmessa_esternamente_il is not None:
            raise Conflict(
                ENTITY,
                "la fattura e' stata consegnata all'intermediario il "
                f"{invoice.trasmessa_esternamente_il.isoformat()}: da questo punto la "
                "correzione richiede una nota di credito, che PigroCRM non emette. "
                "Va fatta dal tuo intermediario o dal portale dell'Agenzia delle Entrate.",
                trasmessa_esternamente_il=invoice.trasmessa_esternamente_il.isoformat(),
            )
        invoice.stato = "annullata"
        invoice.annullata_il = date.today()
        invoice.motivo_annullamento = data.motivo
        self.activities.record(
            ENTITY,
            invoice.id,
            "annulled",
            actor,
            {"numero": invoice.numero, "anno": invoice.anno, "motivo": data.motivo},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def mark_transmitted_externally(
        self, invoice_id: UUID, data: InvoiceTransmitted, actor: Actor
    ) -> InvoiceRead:
        """Record that the XML has been handed to the intermediary. Settable **once**.

        This is the column that makes annulment safe rather than optimistic: without
        it the system could not distinguish an invoice that never left -- annullable --
        from one already deposited with the Agenzia delle Entrate, and would treat the
        two the same. Freezing it after the first write is what stops that distinction
        from being editable away.
        """
        actor.require_admin("mark_transmitted_externally")
        invoice = self._require(invoice_id)
        if invoice.stato != "emessa":
            raise Conflict(
                ENTITY,
                "solo una fattura emessa si consegna a un intermediario",
                stato_attuale=invoice.stato,
            )
        if invoice.trasmessa_esternamente_il is not None:
            raise ImmutableField(
                ENTITY,
                "trasmessa_esternamente_il",
                "la consegna si registra una volta sola: e' il fatto su cui si decide "
                "se un annullamento e' ancora possibile",
            )
        if data.data > date.today():
            raise ValidationFailed(
                ENTITY,
                "trasmessa_esternamente_il",
                "una consegna non si registra con data futura",
                expected=f"una data non successiva a {date.today().isoformat()}",
            )
        if invoice.data_emissione is not None and data.data < invoice.data_emissione:
            raise ValidationFailed(
                ENTITY,
                "trasmessa_esternamente_il",
                "la consegna non puo' precedere l'emissione "
                f"({invoice.data_emissione.isoformat()})",
                expected=f"una data dal {invoice.data_emissione.isoformat()} in poi",
            )
        invoice.trasmessa_esternamente_il = data.data
        self.activities.record(
            ENTITY, invoice.id, "transmitted_externally", actor, {"data": data.data.isoformat()}
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)
```

and extend the schema import in that module:

```python
from pigrocrm.core.invoices.schemas import (
    DIVISA,
    SNAPSHOT_VERSIONE,
    TIPO_DOCUMENTO,
    InvoiceAnnul,
    InvoiceCreate,
    InvoiceIssue,
    InvoiceLineIn,
    InvoiceLineRead,
    InvoiceListQuery,
    InvoicePage,
    InvoiceRead,
    InvoiceSnapshot,
    InvoiceTransmitted,
    InvoiceUpdate,
    PartySnapshot,
    PaymentState,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_immutability.py packages/core/tests/test_invoice_issue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_immutability.py
git commit -m "feat(invoices): annul-then-reissue, and transmission as a one-way door"
```

---
### Task 12: The XML artefact — one document stream, one hash, byte-identical forever

**Files:**
- Modify: `packages/core/src/pigrocrm/core/documents/service.py` (`storage_key_for` and `add_version` take a prefix)
- Modify: `packages/core/src/pigrocrm/core/invoices/service.py` (add the artefact methods)
- Test: `packages/core/tests/test_invoice_artifacts_xml.py`
- Test: `packages/core/tests/test_documents_service.py` (append two cases for the prefix)

**Interfaces:**
- Consumes: `DocumentService` (slice 2); `FatturaPAExporter`, `normalise_fiscal_id` (Task 6); `sdi_filename`, `invoice_storage_prefix`, `proforma_storage_prefix`, `numero_completo` (Task 5); `InvoiceForExport`, `InvoiceArtifact`, `ArtifactKind` (Task 4).
- Produces:
  - `DocumentService.storage_key_for(self, document: Document, numero: int, content_type: str, *, prefix: str | None = None) -> str`
  - `DocumentService.add_version(..., storage_prefix: str | None = None) -> DocumentVersionRead` (new keyword-only parameter, appended; every existing call site keeps working)
  - `InvoiceService.export_xml(self, invoice_id: UUID, actor: Actor) -> InvoiceArtifact`
  - `InvoiceService.download(self, invoice_id: UUID, kind: ArtifactKind, actor: Actor) -> tuple[bytes, str, str]`
  - `InvoiceService._for_export(self, invoice: Invoice) -> InvoiceForExport`
  - `InvoiceService._artifact_document(self, invoice: Invoice, tipo: str, titolo: str, actor: Actor) -> Document`

- [ ] **Step 1: Write the failing test for the storage prefix**

Append to `packages/core/tests/test_documents_service.py`:

```python
def test_a_storage_prefix_overrides_the_customer_folder(
    db_session: Session, tmp_path: Path
) -> None:
    """Slice 3 needs `fatture/{anno}/{numero}/v1.xml`, not the customer-slug folder:
    a file pulled out of context has to stay identifiable as a fiscal artefact, which
    is one of the four independent mechanisms keeping a proforma from being mistaken
    for an invoice. The default path is untouched -- the parameter is keyword-only and
    defaults to None, so every existing caller behaves exactly as before."""
    service = _service(db_session, tmp_path)
    customer = _customer(db_session)
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="fattura", titolo="Fattura 2026/1"), ADMIN
    )
    version = service.add_version(
        document.id,
        b"<?xml version='1.0'?><a/>",
        "application/xml",
        ADMIN,
        storage_prefix="fatture/2026/1",
    )
    assert version.storage_key == "fatture/2026/1/v1.xml"


def test_without_a_prefix_the_customer_folder_is_still_used(
    db_session: Session, tmp_path: Path
) -> None:
    service = _service(db_session, tmp_path)
    customer = _customer(db_session)
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="Nota"), ADMIN
    )
    version = service.add_version(document.id, b"ciao", "text/plain", ADMIN)
    assert version.storage_key.endswith(f"/{document.id}/v1.txt")
```

Reuse whatever `_service` / `_customer` / `ADMIN` helpers that file already defines; if their names differ, use the ones actually there rather than adding duplicates.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/core/tests/test_documents_service.py -k storage_prefix -v`
Expected: FAIL with `TypeError: add_version() got an unexpected keyword argument 'storage_prefix'`

- [ ] **Step 3: Add the prefix to `DocumentService`**

In `packages/core/src/pigrocrm/core/documents/service.py`, replace `storage_key_for`'s signature and add the early return, keeping the existing docstring and appending the new paragraph:

```python
    def storage_key_for(
        self, document: Document, numero: int, content_type: str, *, prefix: str | None = None
    ) -> str:
        """`{cliente-slug}-{id[:8]}/{document_id}/v{numero}{ext}`, or
        `{prefix}/v{numero}{ext}` when a caller supplies its own prefix.

        [existing docstring paragraphs unchanged]

        The `prefix` override exists for the fiscal artefacts of slice 3, which need
        `fatture/{anno}/{numero}/` and `proforma/{id}/` rather than a customer folder:
        the bytes live under a prefix that keeps a file identifiable when it is pulled
        out of its context, which is one of the four independent mechanisms that stop a
        proforma from being read as an invoice. Keyword-only and defaulting to `None`,
        so every existing caller is unaffected; the value still passes through
        `storage.put`'s own `validate_storage_key` gate, which is what actually refuses
        an unsafe key -- this method's job is to produce a sensible one.
        """
        if prefix is not None:
            return f"{prefix}/v{numero}{ALLOWED_CONTENT_TYPES[content_type]}"
        customer = self._customer_of(document)
        folder = (
            f"{slugify_folder(customer.ragione_sociale)}-{str(customer.id)[:_CUSTOMER_ID_FRAGMENT]}"
            if customer
            else "senza-cliente"
        )
        return f"{folder}/{document.id}/v{numero}{ALLOWED_CONTENT_TYPES[content_type]}"
```

In `add_version`, add the keyword-only parameter after `variabili`:

```python
        variabili: dict[str, Any] | None = None,
        storage_prefix: str | None = None,
```

and change the `storage_key=` argument of the `DocumentVersion(...)` construction to:

```python
            storage_key=self.storage_key_for(document, numero, content_type, prefix=storage_prefix),
```

- [ ] **Step 4: Write the failing test for the XML artefact**

`packages/core/tests/test_invoice_artifacts_xml.py`:

```python
"""The XML as a stored artefact: one `documents` row, one hash, byte-identical forever.

Two `documents` rows per issued invoice, not one (spec 8.4): a `document_versions`
chain is a linear history of one logical file with one `hash_sha256` used for
deduplication and integrity, so putting the PDF and the XML in the same chain would
make "version 3" ambiguous and the two hashes incomparable.
"""

import hashlib
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from lxml import etree
from fpr12 import assert_valid
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceIssue, InvoiceLineIn
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")


@pytest.fixture
def storage(tmp_path) -> LocalFileStorage:  # type: ignore[no-untyped-def]
    return LocalFileStorage(tmp_path / "documents")


@pytest.fixture
def service(db_session: Session, storage: LocalFileStorage) -> InvoiceService:
    FiscalProfileService(db_session).upsert(FiscalProfileUpsert(codice_regime="RF19"), ADMIN)
    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Humancraft di Ivan Sala",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Vittorio Veneto 12",
            cap="20124",
            comune="Milano",
            provincia="MI",
            nazione="IT",
            email="someone@example.com",
        ),
        ADMIN,
    )
    return InvoiceService(db_session, storage)


@pytest.fixture
def customer_id(db_session: Session) -> UUID:
    customer = Customer(
        ragione_sociale="Acme S.r.l.",
        partita_iva="12345678901",
        codice_sdi="ABCDEFG",
        indirizzo="Corso Italia 5",
        cap="00100",
        comune="Roma",
        provincia="RM",
        nazione="IT",
    )
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _issue(service: InvoiceService, customer_id: UUID) -> UUID:
    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            causale="Consulenza",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("1000.00"))],
        ),
        ADMIN,
    )
    return service.issue(draft.id, InvoiceIssue(), ADMIN).id


def test_the_first_export_writes_a_document_a_version_and_the_hash(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    artifact = service.export_xml(invoice_id, ADMIN)
    invoice = service.get(invoice_id, ADMIN)

    assert artifact.kind == "xml"
    assert artifact.version_numero == 1
    assert artifact.content_type == "application/xml"
    assert invoice.xml_document_id == artifact.document_id
    assert invoice.xml_hash_sha256 == artifact.hash_sha256


def test_the_stored_bytes_validate_against_the_official_schema(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    service.export_xml(invoice_id, ADMIN)
    data, content_type, filename = service.download(invoice_id, "xml", ADMIN)
    assert_valid(data)
    assert content_type == "application/xml"
    assert filename.startswith("IT")
    assert filename.endswith(".xml")


def test_the_download_name_follows_the_sdi_convention_using_the_frozen_emitter_id(
    service: InvoiceService, customer_id: UUID
) -> None:
    """The name comes from the snapshot, not from the live profile: the file goes to an
    intermediary that often validates the name before the content, and it must not
    change because the issuer edited their profile afterwards."""
    invoice_id = _issue(service, customer_id)
    service.export_xml(invoice_id, ADMIN)
    _, _, before = service.download(invoice_id, "xml", ADMIN)
    EmitterProfileService(service.session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Altro Nome",
            partita_iva="14518240966",
            codice_fiscale="RSSMRA80A01H501U",
            indirizzo="Via Nuova 1",
            cap="20125",
            comune="Milano",
            provincia="MI",
            nazione="IT",
        ),
        ADMIN,
    )
    _, _, after = service.download(invoice_id, "xml", ADMIN)
    assert before == after
    assert before.startswith("ITHMCRFT00A01H501K_")


def test_the_bytes_live_under_the_fiscal_prefix(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    artifact = service.export_xml(invoice_id, ADMIN)
    key = db_session.execute(
        text(
            "SELECT storage_key FROM document_versions "
            "WHERE document_id = :id AND numero = :numero"
        ),
        {"id": artifact.document_id, "numero": artifact.version_numero},
    ).scalar_one()
    invoice = service.get(invoice_id, ADMIN)
    assert key == f"fatture/{invoice.anno}/{invoice.numero}/v1.xml"


def test_the_xml_gets_its_own_documents_row_typed_fattura_xml(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    artifact = service.export_xml(invoice_id, ADMIN)
    tipo, stato = db_session.execute(
        text("SELECT tipo, stato FROM documents WHERE id = :id"), {"id": artifact.document_id}
    ).one()
    assert tipo == "fattura_xml"
    # `documents.stato` stays NULL for all three invoice artefact types: the
    # authoritative state is the invoice's. Duplicating a state machine in two tables
    # produces two truths.
    assert stato is None


def test_re_exporting_returns_the_same_artifact_without_writing_a_second_version(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    first = service.export_xml(invoice_id, ADMIN)
    second = service.export_xml(invoice_id, ADMIN)
    assert second == first
    versions = db_session.execute(
        text("SELECT count(*) FROM document_versions WHERE document_id = :id"),
        {"id": first.document_id},
    ).scalar_one()
    assert versions == 1


def test_a_regenerated_export_is_byte_identical_to_the_original(
    service: InvoiceService, customer_id: UUID
) -> None:
    """Criterion 6 for the XML half: with the emitter and fiscal profiles changed in
    the meantime, the bytes still match, because the exporter reads the snapshot and
    nothing else."""
    invoice_id = _issue(service, customer_id)
    service.export_xml(invoice_id, ADMIN)
    original, _, _ = service.download(invoice_id, "xml", ADMIN)

    FiscalProfileService(service.session).upsert(
        FiscalProfileUpsert(
            codice_regime="RF01",
            aliquota_iva_default=Decimal("22.00"),
            natura_default=None,
            riferimento_normativo=None,
            giorni_scadenza=60,
        ),
        ADMIN,
    )
    EmitterProfileService(service.session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Altro Nome",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Nuova 1",
            cap="20125",
            comune="Torino",
            provincia="TO",
            nazione="IT",
        ),
        ADMIN,
    )

    service.export_xml(invoice_id, ADMIN)
    again, _, _ = service.download(invoice_id, "xml", ADMIN)
    assert again == original
    assert hashlib.sha256(again).hexdigest() == service.get(invoice_id, ADMIN).xml_hash_sha256


def test_a_lost_file_is_repaired_as_a_new_identical_version(
    service: InvoiceService, storage: LocalFileStorage, db_session: Session, customer_id: UUID
) -> None:
    """Spec 4: a new version whose content is byte-for-byte the previous one is a
    repair, not a modification. The stored bytes are deleted behind the service's back
    and the export puts them back."""
    invoice_id = _issue(service, customer_id)
    artifact = service.export_xml(invoice_id, ADMIN)
    key = db_session.execute(
        text("SELECT storage_key FROM document_versions WHERE document_id = :id"),
        {"id": artifact.document_id},
    ).scalar_one()
    storage.delete(key)

    repaired = service.export_xml(invoice_id, ADMIN)
    assert repaired.version_numero == 2
    assert repaired.hash_sha256 == artifact.hash_sha256
    data, _, _ = service.download(invoice_id, "xml", ADMIN)
    assert hashlib.sha256(data).hexdigest() == artifact.hash_sha256


def test_a_divergent_export_is_an_error_to_report_not_a_version_to_save(
    service: InvoiceService, db_session: Session, customer_id: UUID
) -> None:
    """Spec 4, said exactly: "a divergence is an error to report, not a version to
    save". The snapshot is tampered with directly, which is the only way to make the
    generator produce different bytes for the same invoice -- and precisely the kind of
    out-of-band edit this check exists to catch."""
    invoice_id = _issue(service, customer_id)
    service.export_xml(invoice_id, ADMIN)
    db_session.execute(
        text(
            "UPDATE invoices SET snapshot = jsonb_set(snapshot, "
            "'{cliente,ragione_sociale}', '\"Altro Cliente\"') WHERE id = :id"
        ),
        {"id": invoice_id},
    )
    db_session.expire_all()
    with pytest.raises(Conflict) as caught:
        service.export_xml(invoice_id, ADMIN)
    assert "xml_hash_sha256" in str(caught.value.details)


def test_a_proforma_produces_no_xml(service: InvoiceService, customer_id: UUID) -> None:
    """Mechanism 2 of the four: the exporter refuses on the basis of the row's own
    **state**, never on a flag passed by the caller."""
    proforma = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("100.00"))],
        ),
        ADMIN,
    )
    with pytest.raises(Conflict) as caught:
        service.export_xml(proforma.id, ADMIN)
    assert caught.value.details["entity"] == "invoice"


def test_a_draft_produces_no_xml(service: InvoiceService, customer_id: UUID) -> None:
    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("100.00"))],
        ),
        ADMIN,
    )
    with pytest.raises(Conflict):
        service.export_xml(draft.id, ADMIN)


def test_an_annulled_invoice_still_exports_its_xml(
    service: InvoiceService, customer_id: UUID
) -> None:
    """An annulled invoice consumed a number and remains a document of record; being
    unable to produce its file would make the register unauditable."""
    from pigrocrm.core.invoices.schemas import InvoiceAnnul

    invoice_id = _issue(service, customer_id)
    service.export_xml(invoice_id, ADMIN)
    service.annul(invoice_id, InvoiceAnnul(motivo="importo errato"), ADMIN)
    assert service.export_xml(invoice_id, ADMIN).kind == "xml"


def test_downloading_an_xml_that_was_never_exported_is_not_found(
    service: InvoiceService, customer_id: UUID
) -> None:
    invoice_id = _issue(service, customer_id)
    with pytest.raises(NotFound):
        service.download(invoice_id, "xml", ADMIN)


def test_the_hostile_customer_name_survives_the_whole_round_trip(
    service: InvoiceService, db_session: Session
) -> None:
    """Criterion 2, end to end through storage rather than in memory."""
    hostile = 'Rossi & C. <IdCodice>999</IdCodice> "#$@\\ ]]>'
    customer = Customer(
        ragione_sociale=hostile,
        partita_iva="12345678901",
        codice_sdi="ABCDEFG",
        indirizzo="Corso Italia 5",
        cap="00100",
        comune="Roma",
        provincia="RM",
        nazione="IT",
    )
    db_session.add(customer)
    db_session.flush()
    invoice_id = _issue(service, customer.id)
    service.export_xml(invoice_id, ADMIN)
    data, _, _ = service.download(invoice_id, "xml", ADMIN)
    assert_valid(data)
    root = etree.fromstring(data)
    ns = "{http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2}"
    assert hostile in [element.text for element in root.iter(f"{ns}Denominazione")]
    assert len(list(root.iter(f"{ns}IdCodice"))) == 3
```

- [ ] **Step 5: Run it to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_artifacts_xml.py -v`
Expected: FAIL with `AttributeError: 'InvoiceService' object has no attribute 'export_xml'`

- [ ] **Step 6: Implement the artefact methods**

In `packages/core/src/pigrocrm/core/invoices/service.py`, add these imports:

```python
import hashlib

from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.schemas import DocumentCreate
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.invoices.fatturapa import (
    FatturaPAExporter,
    check_party_exportable,
    check_recipient_routing,
    normalise_fiscal_id,
)
from pigrocrm.core.invoices.naming import (
    invoice_storage_prefix,
    numero_completo,
    proforma_riferimento,
    proforma_storage_prefix,
    sdi_filename,
)
from pigrocrm.core.invoices.schemas import ArtifactKind, InvoiceArtifact, InvoiceForExport
```

add to `__init__`:

```python
        self.documents = DocumentService(session, storage, self.settings)
```

and add these methods immediately after `mark_transmitted_externally` (still above `get`):

```python
    def _for_export(self, invoice: Invoice) -> InvoiceForExport:
        """The frozen view the exporter and the PDF read. Never the live profiles.

        `InvoiceSnapshot.model_validate` on the stored JSONB is deliberate: the model
        is `extra="forbid"` and `versione` has no default, so a payload written by a
        different version of this code is a loud failure rather than one silently read
        with a field dropped. This is a fiscal document; guessing is the failure mode
        the version column exists to prevent.
        """
        if invoice.snapshot is None or invoice.anno is None or invoice.numero is None:
            raise Conflict(
                ENTITY,
                "un documento senza numero e senza congelamento non si esporta",
                stato=invoice.stato,
            )
        if invoice.data_emissione is None:  # pragma: no cover - the CHECKs make this unreachable
            raise Conflict(ENTITY, "manca la data di emissione", stato=invoice.stato)
        return InvoiceForExport(
            anno=invoice.anno,
            numero=invoice.numero,
            data_emissione=invoice.data_emissione,
            data_scadenza=invoice.data_scadenza,
            tipo_documento=invoice.tipo_documento,
            divisa=invoice.divisa,
            imponibile=invoice.imponibile,
            imposta=invoice.imposta,
            bollo=invoice.bollo,
            totale=invoice.totale,
            causale=invoice.causale,
            snapshot=InvoiceSnapshot.model_validate(invoice.snapshot),
            righe=tuple(
                InvoiceLineRead.model_validate(r) for r in self.repo.lines(invoice.id)
            ),
        )

    def _artifact_document(
        self, invoice: Invoice, tipo: str, titolo: str, actor: Actor
    ) -> Document:
        """The `documents` row for one artefact stream, created on first use.

        Two rows per issued invoice, not one (spec 8.4): a `document_versions` chain is
        a linear history of *one* logical file with one `hash_sha256` used for
        deduplication and integrity, so mixing the PDF and the XML would make
        "version 3" ambiguous and the two hashes incomparable. Two streams, two hashes,
        two integrity checks -- and re-rendering the PDF never touches the XML.

        `documents.stato` is left `NULL` for all three invoice artefact types: the
        authoritative state is `invoices.stato`, and duplicating a state machine across
        two tables produces two truths.
        """
        existing_id = (
            invoice.xml_document_id if tipo == "fattura_xml" else invoice.pdf_document_id
        )
        if existing_id is not None:
            document = self.documents.repo.get(existing_id)
            if document is not None:
                return document
        created = self.documents.create(
            DocumentCreate(customer_id=invoice.customer_id, tipo=tipo, titolo=titolo),  # type: ignore[arg-type]
            actor,
        )
        document = self.documents.repo.get(created.id)
        if document is None:  # pragma: no cover - just created in this transaction
            raise NotFound("document", created.id)
        if tipo == "fattura_xml":
            invoice.xml_document_id = document.id
        else:
            invoice.pdf_document_id = document.id
        return document

    def _artifact_prefix(self, invoice: Invoice) -> str:
        if invoice.tipo == "proforma":
            return proforma_storage_prefix(invoice.id)
        if invoice.anno is None or invoice.numero is None:  # pragma: no cover
            raise Conflict(ENTITY, "un documento senza numero non ha un prefisso fiscale")
        return invoice_storage_prefix(invoice.anno, invoice.numero)

    def _xml_filename(self, export: InvoiceForExport) -> str:
        """`IT{cf_o_piva}_{progressivo}.xml`, from the **frozen** emitter identity.

        Fiscal code first, then VAT number: the same order `IdTrasmittente` uses, and
        for the same reason -- the SdI accepts either, and this is what the working
        generator sent. Reading the snapshot rather than the live profile is what keeps
        the name stable after the issuer edits their own data.
        """
        emittente = export.snapshot.emittente
        id_fiscale = normalise_fiscal_id(emittente.codice_fiscale) or normalise_fiscal_id(
            emittente.partita_iva
        )
        if id_fiscale is None:
            raise ValidationFailed(
                "emitter_profile",
                "codice_fiscale",
                "il nome del file XML richiede un codice fiscale o una partita IVA "
                "validi dell'emittente",
                expected="11 cifre oppure 16 caratteri",
            )
        return sdi_filename(id_fiscale, export.anno, export.numero)

    def _store_artifact(
        self,
        invoice: Invoice,
        *,
        kind: ArtifactKind,
        tipo: str,
        titolo: str,
        content_type: str,
        filename: str,
        data: bytes,
        expected_hash: str | None,
        actor: Actor,
    ) -> InvoiceArtifact:
        """Write the bytes, or prove the bytes already there are the same bytes.

        Three outcomes, and they are spec 4's three:

        * no previous hash -- the first successful production, the only moment with
          nothing to compare against. Write version 1 and record the hash;
        * the hash matches and the stored bytes still hash to it -- nothing to do.
          Return the existing version rather than writing an identical one, so a
          download does not grow the history;
        * the hash matches but the bytes are gone or corrupt -- a **repair**: write a
          new version with identical content. Spec 4 allows exactly this and calls it a
          repair, not a modification;
        * the hash differs -- an error to report, never a version to save.
        """
        digest = hashlib.sha256(data).hexdigest()
        if expected_hash is not None and digest != expected_hash:
            raise Conflict(
                ENTITY,
                f"il {kind} rigenerato non coincide con quello originale: e' una "
                "divergenza da segnalare, non una nuova versione da salvare",
                atteso=expected_hash,
                ottenuto=digest,
                campo="xml_hash_sha256" if kind == "xml" else "hash_sha256",
            )

        document = self._artifact_document(invoice, tipo, titolo, actor)
        current = (
            self.documents.repo.version(document.id, document.versione_corrente)
            if document.versione_corrente
            else None
        )
        if current is not None and current.hash_sha256 == digest:
            try:
                stored_ok = hashlib.sha256(self.storage.get(current.storage_key)).hexdigest() == digest
            except Exception:
                stored_ok = False
            if stored_ok:
                return InvoiceArtifact(
                    kind=kind,
                    document_id=document.id,
                    version_numero=current.numero,
                    filename=filename,
                    content_type=content_type,
                    hash_sha256=digest,
                )

        version = self.documents.add_version(
            document.id,
            data,
            content_type,
            actor,
            storage_prefix=self._artifact_prefix(invoice),
        )
        return InvoiceArtifact(
            kind=kind,
            document_id=document.id,
            version_numero=version.numero,
            filename=filename,
            content_type=content_type,
            hash_sha256=digest,
        )

    def export_xml(self, invoice_id: UUID, actor: Actor) -> InvoiceArtifact:
        """Produce -- or verify -- the FatturaPA file.

        Refuses a proforma and a draft on the basis of the row's own **state**, never a
        flag the caller passed: that is the second of the four independent mechanisms
        that stop a proforma from being mistaken for an invoice, and the only one that
        cannot be bypassed by a caller who believes otherwise.

        `xml_hash_sha256` is written by the **first** successful export -- the one
        moment with no previous value to compare against -- and from then on every
        export compares and does not rewrite. Until then the column is `NULL` and the
        export is freely repeatable, which is exactly what makes the out-of-transaction
        render of spec 3 harmless.
        """
        actor.require_write("export_invoice_xml")
        invoice = self._require(invoice_id)
        if invoice.tipo != "fattura":
            raise Conflict(
                ENTITY,
                "una proforma non produce un file FatturaPA: non e' un documento fiscale",
                tipo=invoice.tipo,
                stato=invoice.stato,
            )
        if invoice.stato == "bozza":
            raise Conflict(
                ENTITY,
                "una bozza non ha ancora un numero e non produce un file FatturaPA",
                stato=invoice.stato,
            )

        export = self._for_export(invoice)
        # Re-checked here even though `issue` already checked: the snapshot could have
        # been edited out of band, and the two callers of these functions are the whole
        # reason they are module-level rather than methods.
        check_party_exportable(export.snapshot.emittente, "emitter_profile")
        check_party_exportable(export.snapshot.cliente, "customer")
        check_recipient_routing(export.snapshot.cliente)

        data = FatturaPAExporter().to_bytes(export)
        artifact = self._store_artifact(
            invoice,
            kind="xml",
            tipo="fattura_xml",
            titolo=f"Fattura {numero_completo(export.anno, export.numero)} (XML)",
            content_type="application/xml",
            filename=self._xml_filename(export),
            data=data,
            expected_hash=invoice.xml_hash_sha256,
            actor=actor,
        )
        if invoice.xml_hash_sha256 is None:
            invoice.xml_hash_sha256 = artifact.hash_sha256
        self.session.commit()
        return artifact

    def download(
        self, invoice_id: UUID, kind: ArtifactKind, actor: Actor
    ) -> tuple[bytes, str, str]:
        """`(bytes, content_type, filename)`.

        The download always goes through the API, which is the only place authorisation
        exists on either storage backend (slice 2 §5). The XML's name is the SdI
        convention; the PDF's is a plain, slug-safe name, because nothing downstream
        validates it.
        """
        invoice = self._require(invoice_id)
        document_id = invoice.xml_document_id if kind == "xml" else invoice.pdf_document_id
        if document_id is None:
            raise NotFound("invoice_artifact", f"{invoice_id}#{kind}")
        document = self.documents.repo.get(document_id)
        if document is None or not document.versione_corrente:
            raise NotFound("invoice_artifact", f"{invoice_id}#{kind}")
        version = self.documents.repo.version(document.id, document.versione_corrente)
        if version is None:  # pragma: no cover - versione_corrente points at a real row
            raise NotFound("invoice_artifact", f"{invoice_id}#{kind}")
        if kind == "xml":
            filename = self._xml_filename(self._for_export(invoice))
        elif invoice.tipo == "proforma":
            filename = f"proforma-{(invoice.riferimento or str(invoice.id)).lower()}.pdf"
        else:
            filename = f"fattura-{invoice.anno}-{invoice.numero}.pdf"
        return self.storage.get(version.storage_key), version.content_type, filename
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_artifacts_xml.py packages/core/tests/test_documents_service.py packages/core/tests/test_documents_from_template.py -v`
Expected: PASS — the two `documents` tests are in the run because `storage_key_for` and `add_version` changed, and nothing about their existing behaviour may move.

- [ ] **Step 8: Commit**

```bash
git add packages/core/src/pigrocrm/core/documents/service.py packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_artifacts_xml.py packages/core/tests/test_documents_service.py
git commit -m "feat(invoices): the FatturaPA file as a versioned, hash-verified artefact"
```

---
### Task 13: The PDF — two templates, and artefacts produced after the commit

**Files:**
- Create: `packages/core/src/pigrocrm/core/render/assets/template-invoice.md`
- Create: `packages/core/src/pigrocrm/core/render/assets/template-proforma.md`
- Create: `packages/core/src/pigrocrm/core/invoices/pdf.py`
- Modify: `packages/core/src/pigrocrm/core/invoices/service.py` (add `render_pdf`, `produce_artifacts`, and the post-commit call in `issue`)
- Test: `packages/core/tests/test_invoice_pdf.py`

**Interfaces:**
- Consumes: `render_pdf`, `build_header` from `pigrocrm.core.render.pdf` (slice 2); `render_template` from `pigrocrm.core.templates.renderer`; `InvoiceForExport`, `InvoiceArtifact` (Task 4); `build_riepilogo`, `format_amount_2`, `format_amount_8`, `format_rate` (Task 2); `numero_completo`, `proforma_riferimento` (Task 5).
- Produces:
  - `pigrocrm.core.invoices.pdf.INVOICE_TEMPLATE: Path`, `PROFORMA_TEMPLATE: Path`, `PROFORMA_DECLARATION: str`
  - `pigrocrm.core.invoices.pdf.build_scope(export: InvoiceForExport, *, riferimento: str | None) -> dict[str, Any]`
  - `pigrocrm.core.invoices.pdf.render_invoice_pdf(export: InvoiceForExport, *, riferimento: str | None, settings: Settings) -> tuple[str, bytes]`
  - `InvoiceService.render_pdf(self, invoice_id: UUID, actor: Actor) -> InvoiceArtifact`
  - `InvoiceService.produce_artifacts(self, invoice_id: UUID, actor: Actor) -> list[InvoiceArtifact]`

- [ ] **Step 1: Write the two templates**

`packages/core/src/pigrocrm/core/render/assets/template-invoice.md`:

```markdown
```{=typst}
#let muted = rgb("#465362")
#let divider = rgb("#E2E2E2")

#text(size: 9pt, fill: muted)[{{fattura.etichetta}}] | #text(size: 9pt, fill: muted)[Numero: {{fattura.numero}}] | #text(size: 9pt, fill: muted)[Data: {{fattura.data}}]

#v(10pt)

#text(size: 9pt, weight: "bold", fill: muted)[Committente]
#stack(
  spacing: 2pt,
  [#text(size: 9pt)[{{cliente.ragione_sociale}}]],
  [#text(size: 9pt)[P.IVA: {{cliente.partita_iva}} | CF: {{cliente.codice_fiscale}}]],
  [#text(size: 9pt)[{{cliente.indirizzo}}, {{cliente.cap}} {{cliente.comune}} ({{cliente.provincia}}) {{cliente.nazione}}]],
  [#text(size: 9pt)[PEC: {{cliente.pec}} | Codice destinatario: {{cliente.codice_destinatario}}]],
)

#v(14pt)
#text(size: 9pt, weight: "bold", fill: muted)[Dettaglio]
#table(
  columns: (0.46fr, 0.1fr, 0.14fr, 0.1fr, 0.2fr),
  align: (left, right, right, center, right),
  inset: (x: 4pt, y: 6pt),
  stroke: none,
  table.header(
    [#text(size: 8pt, weight: "bold", fill: muted)[DESCRIZIONE]],
    [#text(size: 8pt, weight: "bold", fill: muted)[QTA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[PREZZO]],
    [#text(size: 8pt, weight: "bold", fill: muted)[%IVA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[TOTALE]],
  ),
  {{#each righe}}[#text(size: 9pt)[{{descrizione}}]], [#text(size: 9pt)[{{quantita}}]], [#text(size: 9pt)[{{prezzo_unitario}}]], [#text(size: 9pt)[{{aliquota_iva}}]], [#text(size: 9pt)[{{prezzo_totale}}]],{{/each}}
)

#v(10pt)
#align(right)[
  #table(
    columns: (auto, auto),
    align: (left, right),
    inset: (x: 4pt, y: 4pt),
    stroke: none,
    [#text(size: 9pt, fill: muted)[Imponibile]], [#text(size: 9pt)[{{fattura.imponibile}}]],
    [#text(size: 9pt, fill: muted)[Imposta]], [#text(size: 9pt)[{{fattura.imposta}}]],
    [#text(size: 10pt, weight: "bold")[Totale documento]], [#text(size: 10pt, weight: "bold")[{{fattura.totale}}]],
  )
]

#v(14pt)
#text(size: 9pt, weight: "bold", fill: muted)[Modalita pagamento]
#table(
  columns: (0.2fr, 0.44fr, 0.16fr, 0.2fr),
  align: (left, left, center, right),
  inset: (x: 4pt, y: 6pt),
  stroke: none,
  table.header(
    [#text(size: 8pt, weight: "bold", fill: muted)[MODALITA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[IBAN]],
    [#text(size: 8pt, weight: "bold", fill: muted)[SCADENZA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[IMPORTO]],
  ),
  [#text(size: 9pt)[{{fiscale.modalita_pagamento}}]],
  [#text(size: 9pt)[{{fiscale.iban}}]],
  [#text(size: 9pt)[{{fattura.data_scadenza}}]],
  [#text(size: 9pt)[{{fattura.totale}}]],
)

#v(14pt)
#line(length: 100%, stroke: 0.6pt + divider)
#v(10pt)

#text(size: 8pt, fill: muted)[{{fiscale.riferimento_normativo}}]

#text(size: 8pt, fill: muted)[{{fattura.dichiarazione_bollo}}]
```
```

`packages/core/src/pigrocrm/core/render/assets/template-proforma.md`: identical to the file above, with one block inserted immediately after the `#let divider` line:

```markdown
#align(center)[
  #block(
    fill: rgb("#F9DC5C"),
    inset: 8pt,
    radius: 4pt,
    width: 100%,
  )[
    #align(center)[#text(size: 11pt, weight: "bold")[FATTURA PROFORMA - NON COSTITUISCE FATTURA]]
  ]
]

#v(12pt)
```

The declaration goes **in the body**, not as a watermark: a watermark is a thing a print can lose, and this is the third of the four independent mechanisms that stop a proforma from being paid as an invoice. Everything else in the proforma template is byte-identical to the invoice one, including `{{fattura.numero}}`, which for a proforma is filled with its `riferimento` (`PROV-2026-0007`) — a string no fiscal-number pattern accepts.

- [ ] **Step 2: Write the failing test**

`packages/core/tests/test_invoice_pdf.py`:

```python
"""The PDF, through the real Pandoc/Typst pipeline of slice 2.

These are real compiles reading real bytes back, not string assertions: the escaping
lesson of slice 2 was learned against the actual Typst compiler, and this slice has
two compilers to satisfy rather than one.
"""

import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import get_settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.pdf import PROFORMA_DECLARATION
from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceIssue, InvoiceLineIn
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")
HOSTILE = 'Rossi & C. <IdCodice>999</IdCodice> "#$@\\ ]]>'


def _pdf_text(data: bytes, tmp_path: Path) -> str:
    """The PDF's own extracted text, the way `test_render_pdf.py` already does it: an
    assertion on a string this module produced would prove nothing about what a reader
    sees."""
    target = tmp_path / "out.pdf"
    target.write_bytes(data)
    result = subprocess.run(
        ["pdftotext", "-layout", str(target), "-"],
        capture_output=True,
        check=False,
        timeout=30,
    )
    return result.stdout.decode("utf-8", errors="replace")


@pytest.fixture
def storage(tmp_path) -> LocalFileStorage:  # type: ignore[no-untyped-def]
    return LocalFileStorage(tmp_path / "documents")


@pytest.fixture
def service(db_session: Session, storage: LocalFileStorage) -> InvoiceService:
    FiscalProfileService(db_session).upsert(
        FiscalProfileUpsert(codice_regime="RF19", iban="IT60X0542811101000000123456"), ADMIN
    )
    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Humancraft di Ivan Sala",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Vittorio Veneto 12",
            cap="20124",
            comune="Milano",
            provincia="MI",
            nazione="IT",
            email="someone@example.com",
            regime_fiscale="Regime forfettario ex L. 190/2014",
        ),
        ADMIN,
    )
    return InvoiceService(db_session, storage, get_settings())


def _customer(db_session: Session, **overrides: object) -> UUID:
    payload: dict[str, object] = {
        "ragione_sociale": "Acme S.r.l.",
        "partita_iva": "12345678901",
        "codice_sdi": "ABCDEFG",
        "indirizzo": "Corso Italia 5",
        "cap": "00100",
        "comune": "Roma",
        "provincia": "RM",
        "nazione": "IT",
    }
    payload.update(overrides)
    customer = Customer(**payload)  # type: ignore[arg-type]
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _issue(service: InvoiceService, customer_id: UUID) -> UUID:
    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            causale="Consulenza",
            righe=[
                InvoiceLineIn(
                    descrizione="Consulenza tecnica",
                    quantita=Decimal("3.000000"),
                    unita_misura="ore",
                    prezzo_unitario=Decimal("500.000000"),
                )
            ],
        ),
        ADMIN,
    )
    return service.issue(draft.id, InvoiceIssue(), ADMIN).id


def test_issuing_produces_both_artefacts(service: InvoiceService, db_session: Session) -> None:
    """The render happens after the commit, in a second transaction, from the
    snapshot -- but by the time the call returns, both artefacts exist."""
    invoice_id = _issue(service, _customer(db_session))
    invoice = service.get(invoice_id, ADMIN)
    assert invoice.pdf_document_id is not None
    assert invoice.xml_document_id is not None
    assert invoice.xml_hash_sha256 is not None


def test_the_pdf_shows_the_number_the_customer_and_the_lines(
    service: InvoiceService, db_session: Session, tmp_path: Path
) -> None:
    invoice_id = _issue(service, _customer(db_session))
    data, content_type, filename = service.download(invoice_id, "pdf", ADMIN)
    assert content_type == "application/pdf"
    assert filename.endswith(".pdf")
    body = _pdf_text(data, tmp_path)
    invoice = service.get(invoice_id, ADMIN)
    assert f"{invoice.anno}/{invoice.numero}" in body
    assert "Acme S.r.l." in body
    assert "Consulenza tecnica" in body
    assert "1.500,00" in body or "1500.00" in body


def test_the_pdf_carries_the_regime_declaration_from_the_profile(
    service: InvoiceService, db_session: Session, tmp_path: Path
) -> None:
    """In Acme this was a fixed string in the source of a public repository."""
    invoice_id = _issue(service, _customer(db_session))
    data, _, _ = service.download(invoice_id, "pdf", ADMIN)
    assert "forfettario" in _pdf_text(data, tmp_path)


def test_a_hostile_customer_name_appears_in_the_pdf_as_text(
    service: InvoiceService, db_session: Session, tmp_path: Path
) -> None:
    """Criterion 2's second half: the same hostile value that must not corrupt the XML
    must also compile, and read back, as text. Two compilers, one assertion each."""
    invoice_id = _issue(service, _customer(db_session, ragione_sociale=HOSTILE))
    data, _, _ = service.download(invoice_id, "pdf", ADMIN)
    body = _pdf_text(data, tmp_path)
    assert "Rossi & C." in body
    assert "IdCodice" in body


def test_a_proforma_pdf_declares_itself_in_the_body(
    service: InvoiceService, db_session: Session, tmp_path: Path
) -> None:
    """Mechanism 3 of the four: the declaration is in the document body, not a
    watermark a print can lose."""
    proforma = service.create(
        InvoiceCreate(
            customer_id=_customer(db_session),
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    service.render_pdf(proforma.id, ADMIN)
    data, _, filename = service.download(proforma.id, "pdf", ADMIN)
    assert PROFORMA_DECLARATION in _pdf_text(data, tmp_path)
    assert filename.startswith("proforma-")


def test_a_proforma_pdf_shows_its_reference_where_a_number_would_be(
    service: InvoiceService, db_session: Session, tmp_path: Path
) -> None:
    proforma = service.create(
        InvoiceCreate(
            customer_id=_customer(db_session),
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    service.render_pdf(proforma.id, ADMIN)
    data, _, _ = service.download(proforma.id, "pdf", ADMIN)
    body = _pdf_text(data, tmp_path)
    reference = service.get(proforma.id, ADMIN).riferimento or ""
    assert reference in body


def test_a_proforma_pdf_lives_under_its_own_storage_prefix(
    service: InvoiceService, db_session: Session
) -> None:
    """Mechanism 4: the bytes live under a different prefix, so a file pulled out of
    context stays identifiable."""
    proforma = service.create(
        InvoiceCreate(
            customer_id=_customer(db_session),
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    artifact = service.render_pdf(proforma.id, ADMIN)
    key = db_session.execute(
        text("SELECT storage_key FROM document_versions WHERE document_id = :id"),
        {"id": artifact.document_id},
    ).scalar_one()
    assert key == f"proforma/{proforma.id}/v1.pdf"


def test_a_proforma_gets_a_proforma_typed_documents_row(
    service: InvoiceService, db_session: Session
) -> None:
    proforma = service.create(
        InvoiceCreate(
            customer_id=_customer(db_session),
            tipo="proforma",
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("500.00"))],
        ),
        ADMIN,
    )
    artifact = service.render_pdf(proforma.id, ADMIN)
    tipo = db_session.execute(
        text("SELECT tipo FROM documents WHERE id = :id"), {"id": artifact.document_id}
    ).scalar_one()
    assert tipo == "proforma"


def test_re_rendering_is_byte_identical_and_writes_no_second_version(
    service: InvoiceService, db_session: Session
) -> None:
    """Criterion 6 for the PDF half. `PDF_CREATION_TIMESTAMP` is already pinned in
    `render/pdf.py`, which is what makes byte-for-byte reproduction possible at all --
    Typst otherwise stamps the compile's wall-clock time into the container."""
    invoice_id = _issue(service, _customer(db_session))
    first = service.render_pdf(invoice_id, ADMIN)
    original, _, _ = service.download(invoice_id, "pdf", ADMIN)

    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Altro Nome",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Nuova 1",
            cap="20125",
            comune="Torino",
            provincia="TO",
            nazione="IT",
        ),
        ADMIN,
    )
    FiscalProfileService(db_session).upsert(
        FiscalProfileUpsert(
            codice_regime="RF01",
            aliquota_iva_default=Decimal("22.00"),
            natura_default=None,
            riferimento_normativo=None,
        ),
        ADMIN,
    )

    second = service.render_pdf(invoice_id, ADMIN)
    again, _, _ = service.download(invoice_id, "pdf", ADMIN)
    assert again == original
    assert second == first
    versions = db_session.execute(
        text("SELECT count(*) FROM document_versions WHERE document_id = :id"),
        {"id": first.document_id},
    ).scalar_one()
    assert versions == 1


def test_a_render_failure_leaves_the_invoice_with_its_number(
    service: InvoiceService, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 3: an invoice is a legal fact independent of its printout. If the render
    fails, the invoice exists with its number and the artefacts regenerate later."""
    import pigrocrm.core.invoices.pdf as invoice_pdf

    monkeypatch.setattr(
        invoice_pdf, "render_pdf", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("typst giu'"))
    )
    invoice_id = _issue(service, _customer(db_session))
    invoice = service.get(invoice_id, ADMIN)
    assert invoice.numero == 1
    assert invoice.stato == "emessa"
    assert invoice.pdf_document_id is None
    entries = db_session.execute(
        text("SELECT kind FROM activities WHERE entity_id = :id"), {"id": invoice_id}
    ).scalars().all()
    assert "artifacts_failed" in entries


def test_the_artefacts_regenerate_after_a_failed_render(
    service: InvoiceService, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pigrocrm.core.invoices.pdf as invoice_pdf

    monkeypatch.setattr(
        invoice_pdf, "render_pdf", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("typst giu'"))
    )
    invoice_id = _issue(service, _customer(db_session))
    monkeypatch.undo()
    artefacts = service.produce_artifacts(invoice_id, ADMIN)
    assert {a.kind for a in artefacts} == {"pdf", "xml"}


def test_a_draft_has_no_pdf(service: InvoiceService, db_session: Session) -> None:
    draft = service.create(
        InvoiceCreate(
            customer_id=_customer(db_session),
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("100.00"))],
        ),
        ADMIN,
    )
    with pytest.raises(Conflict):
        service.render_pdf(draft.id, ADMIN)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest packages/core/tests/test_invoice_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.invoices.pdf'`

- [ ] **Step 4: Implement the scope builder and the renderer**

`packages/core/src/pigrocrm/core/invoices/pdf.py`:

```python
"""From a frozen `InvoiceForExport` to PDF bytes, through slice 2's pipeline unchanged.

Separate from `render/pdf.py` on purpose: that module is the generic Pandoc/Typst
runner and the only place in the codebase that spawns a process, and it must stay
ignorant of invoices. This module knows about invoices and nothing about subprocesses.

Every value in the scope is a **string already formatted for display**, produced by
`totals.py`'s formatters. Amounts are never handed to the template as `Decimal` for the
template to format, and never re-parsed from text: Acme applied a percentage to a
total it had read back out of a formatted string, and that is the class of defect this
separation removes.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

from pigrocrm.core.config import Settings
from pigrocrm.core.invoices.naming import numero_completo
from pigrocrm.core.invoices.schemas import InvoiceForExport
from pigrocrm.core.invoices.totals import format_amount_2, format_amount_8, format_rate
from pigrocrm.core.render.pdf import ASSETS_DIR, build_header, render_pdf
from pigrocrm.core.templates.renderer import render_template

INVOICE_TEMPLATE = ASSETS_DIR / "template-invoice.md"
PROFORMA_TEMPLATE = ASSETS_DIR / "template-proforma.md"

# In the body of the document, not a watermark: a watermark is a thing a print can
# lose, and this is one of four independent mechanisms keeping a proforma from being
# paid as an invoice. Asserted verbatim by the tests, so it is a constant rather than
# a string typed twice.
PROFORMA_DECLARATION = "FATTURA PROFORMA - NON COSTITUISCE FATTURA"

CODICE_DESTINATARIO_FALLBACK = "0000000"
_EMPTY = ""


def build_scope(export: InvoiceForExport, *, riferimento: str | None) -> dict[str, Any]:
    """What the template can read.

    Built entirely from the snapshot and the stored totals. The live `emitter_profile`
    and `fiscal_profile` are not consulted, which is what makes a re-render a year
    later produce the same bytes (criterion 6) rather than a document that quietly
    reflects whatever the configuration says today.
    """
    snapshot = export.snapshot
    cliente = snapshot.cliente
    fiscale = snapshot.fiscale
    codice_destinatario = (cliente.codice_sdi or "").strip() or (
        CODICE_DESTINATARIO_FALLBACK if (cliente.pec or "").strip() else _EMPTY
    )
    bollo = (
        f"Imposta di bollo di {format_amount_2(export.bollo)} EUR assolta in modo "
        "virtuale a carico dell'emittente."
        if export.bollo > Decimal("0.00")
        else _EMPTY
    )
    return {
        "emittente": snapshot.emittente.model_dump(mode="json"),
        "cliente": {
            **cliente.model_dump(mode="json"),
            "codice_destinatario": codice_destinatario,
        },
        "fiscale": fiscale.model_dump(mode="json"),
        "fattura": {
            "etichetta": "Fattura" if riferimento is None else "Fattura proforma",
            "numero": riferimento
            if riferimento is not None
            else numero_completo(export.anno, export.numero),
            "data": export.data_emissione.isoformat(),
            "data_scadenza": (
                export.data_scadenza.isoformat() if export.data_scadenza else _EMPTY
            ),
            "causale": export.causale or _EMPTY,
            "imponibile": format_amount_2(export.imponibile),
            "imposta": format_amount_2(export.imposta),
            "bollo": format_amount_2(export.bollo),
            "totale": format_amount_2(export.totale),
            "dichiarazione_bollo": bollo,
        },
        "righe": [
            {
                "numero_linea": str(riga.numero_linea),
                "descrizione": riga.descrizione,
                "quantita": format_amount_8(riga.quantita),
                "unita_misura": riga.unita_misura or _EMPTY,
                "prezzo_unitario": format_amount_2(riga.prezzo_unitario),
                "aliquota_iva": format_rate(riga.aliquota_iva),
                "prezzo_totale": format_amount_2(riga.prezzo_totale),
            }
            for riga in export.righe
        ],
    }


def render_invoice_pdf(
    export: InvoiceForExport, *, riferimento: str | None, settings: Settings
) -> tuple[str, bytes]:
    """`(compiled_markdown, pdf_bytes)`.

    `riferimento is None` picks the fiscal template; a reference string picks the
    proforma one, which carries `PROFORMA_DECLARATION` in its body. The choice is made
    from the row's own data, never from a caller's flag.

    The page header and footer come from `build_header`, exactly as slice 2's offer
    render does, so the issuer's identity, logo and contacts are laid out once and in
    one place rather than repeated in every body template.
    """
    template = INVOICE_TEMPLATE if riferimento is None else PROFORMA_TEMPLATE
    scope = build_scope(export, riferimento=riferimento)
    markdown = render_template(template.read_text(encoding="utf-8"), scope)
    header = build_header(scope["emittente"])
    return markdown, render_pdf(markdown, header_typst=header, settings=settings)
```

- [ ] **Step 5: Add the service methods and hook them to `issue`**

In `packages/core/src/pigrocrm/core/invoices/service.py`, add:

```python
from pigrocrm.core.invoices import pdf as invoice_pdf
```

then add these two methods immediately after `export_xml` (still above `get`):

```python
    def render_pdf(self, invoice_id: UUID, actor: Actor) -> InvoiceArtifact:
        """Produce -- or verify -- the PDF.

        The same three-way outcome as `export_xml`, compared against the previous
        `document_versions.hash_sha256` of the PDF stream rather than against
        `invoices.xml_hash_sha256`: two streams, two hashes, two independent integrity
        checks, and re-rendering the PDF never touches the XML.
        """
        actor.require_write("render_invoice_pdf")
        invoice = self._require(invoice_id)
        if invoice.stato == "bozza":
            raise Conflict(
                ENTITY,
                "una bozza non ha un PDF: confermala (proforma) o emettila (fattura)",
                stato=invoice.stato,
            )
        if invoice.tipo == "proforma":
            export = self._proforma_for_export(invoice)
            riferimento = invoice.riferimento
            titolo = f"Proforma {invoice.riferimento}"
            tipo = "proforma"
        else:
            export = self._for_export(invoice)
            riferimento = None
            titolo = f"Fattura {numero_completo(export.anno, export.numero)}"
            tipo = "fattura"

        _, data = invoice_pdf.render_invoice_pdf(
            export, riferimento=riferimento, settings=self.settings
        )
        document_id = invoice.pdf_document_id
        previous = None
        if document_id is not None:
            document = self.documents.repo.get(document_id)
            if document is not None and document.versione_corrente:
                version = self.documents.repo.version(document.id, document.versione_corrente)
                previous = version.hash_sha256 if version is not None else None

        artifact = self._store_artifact(
            invoice,
            kind="pdf",
            tipo=tipo,
            titolo=titolo,
            content_type="application/pdf",
            filename=(
                f"proforma-{(invoice.riferimento or str(invoice.id)).lower()}.pdf"
                if invoice.tipo == "proforma"
                else f"fattura-{invoice.anno}-{invoice.numero}.pdf"
            ),
            data=data,
            expected_hash=previous,
            actor=actor,
        )
        self.session.commit()
        return artifact

    def produce_artifacts(self, invoice_id: UUID, actor: Actor) -> list[InvoiceArtifact]:
        """Both artefacts of an issued invoice, or just the PDF of a proforma.

        Idempotent by construction: each producer either writes the first version,
        returns the existing one when the bytes still match, repairs a lost file with
        an identical version, or reports a divergence. Calling it again after a
        successful run therefore changes nothing.
        """
        invoice = self._require(invoice_id)
        artefacts = [self.render_pdf(invoice_id, actor)]
        if invoice.tipo == "fattura" and invoice.stato != "bozza":
            artefacts.append(self.export_xml(invoice_id, actor))
        return artefacts

    def _proforma_for_export(self, invoice: Invoice) -> InvoiceForExport:
        """A proforma has no number, no issue date and no snapshot, so it cannot use
        `_for_export`; it is rendered from the live rows instead.

        That asymmetry is correct rather than convenient: a proforma is *meant* to be
        re-rendered differently after an edit, because editing it is what it is for.
        Byte-for-byte reproducibility is a promise about fiscal documents, and this is
        deliberately not one -- which is also why the `anno`/`numero` pair here is a
        placeholder the schema will accept (`InvoiceForExport` requires both): neither
        value reaches the proforma template, whose number field is filled from
        `riferimento`, and neither is ever written to a row.
        """
        _, profile = self._regime()
        snapshot = self._build_snapshot(invoice, profile, Actor.system())
        return InvoiceForExport(
            anno=date.today().year,
            numero=1,
            data_emissione=date.today(),
            data_scadenza=date.today() + timedelta(days=profile.giorni_scadenza),
            tipo_documento=invoice.tipo_documento,
            divisa=invoice.divisa,
            imponibile=invoice.imponibile,
            imposta=invoice.imposta,
            bollo=invoice.bollo,
            totale=invoice.totale,
            causale=invoice.causale,
            snapshot=snapshot,
            righe=tuple(InvoiceLineRead.model_validate(r) for r in self.repo.lines(invoice.id)),
        )
```

Finally, in `issue`, replace the closing `return InvoiceRead.model_validate(target)` with:

```python
        # Spec 3: the render happens **after** the commit, in a second transaction,
        # reading the snapshot. Holding the counter's row lock for the duration of a
        # Typst subprocess would serialise every emission on PDF compile time, and an
        # invoice is a legal fact independent of its printout. This is the one
        # documented exception to "one service method = one transaction".
        #
        # A failure here is recorded and swallowed rather than propagated: the invoice
        # exists with its number, and `produce_artifacts` regenerates deterministically
        # from the snapshot whenever it is called again. Re-raising would tell the
        # caller the emission failed when it did not, which is the more dangerous lie.
        try:
            self.produce_artifacts(target.id, actor)
        except Exception as exc:  # noqa: BLE001 - recorded, never hidden
            self.session.rollback()
            self.activities.record(
                ENTITY,
                target.id,
                "artifacts_failed",
                actor,
                {"errore": type(exc).__name__, "messaggio": str(exc)[:200]},
            )
            self.session.commit()
        return InvoiceRead.model_validate(self._require(target.id))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/core/tests/test_invoice_pdf.py -v`
Expected: PASS. These tests need Pandoc, Typst and `pdftotext` on the PATH — the same prerequisites `packages/core/tests/test_render_pdf.py` already has, so if that file passes locally these will too.

Run: `uv run pytest packages/core/tests -v`
Expected: PASS across the whole core suite.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/render/assets/template-invoice.md packages/core/src/pigrocrm/core/render/assets/template-proforma.md packages/core/src/pigrocrm/core/invoices/pdf.py packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_pdf.py
git commit -m "feat(invoices): fiscal and proforma PDFs, rendered after the commit"
```

---

# Phase 3 — The two adapters

### Task 14: The REST surface

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/invoices.py`
- Create: `apps/api/src/pigrocrm_api/routers/fiscal_profile.py`
- Modify: `apps/api/src/pigrocrm_api/main.py`
- Test: `apps/api/tests/test_invoices_api.py`

**Interfaces:**
- Consumes: `InvoiceService`, `FiscalProfileService`, every invoice schema; `ActorDep`, `SessionDep`, `SettingsDep`, `StorageDep`, `PROBLEM_RESPONSES`.
- Produces these endpoints:
  - `GET /api/invoices` → `InvoicePage`
  - `POST /api/invoices` → `InvoiceRead`, 201
  - `GET /api/invoices/{invoice_id}` → `InvoiceRead`
  - `PATCH /api/invoices/{invoice_id}` → `InvoiceRead`
  - `DELETE /api/invoices/{invoice_id}` → 204
  - `GET /api/invoices/{invoice_id}/lines` → `list[InvoiceLineRead]`
  - `PUT /api/invoices/{invoice_id}/lines` → `InvoiceRead`
  - `POST /api/invoices/{invoice_id}/confirm` → `InvoiceRead`
  - `POST /api/invoices/{invoice_id}/issue` → `InvoiceRead`
  - `POST /api/invoices/{invoice_id}/annul` → `InvoiceRead`
  - `POST /api/invoices/{invoice_id}/transmitted` → `InvoiceRead`
  - `PATCH /api/invoices/{invoice_id}/payment` → `InvoiceRead`
  - `POST /api/invoices/{invoice_id}/artifacts` → `list[InvoiceArtifact]`
  - `GET /api/invoices/{invoice_id}/pdf` and `/xml` → `Response` (bytes)
  - `GET /api/invoices/{invoice_id}/timeline` → `list[ActivityRead]`
  - `GET /api/fiscal-profile` → `FiscalProfileRead`; `PUT /api/fiscal-profile` → `FiscalProfileRead`
  - `class InvoiceLinesBody(BaseModel)` with `righe: list[InvoiceLineIn] = Field(default_factory=list, max_length=MAX_LINES)`

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_invoices_api.py`:

```python
"""The HTTP surface. Role enforcement lives in the services (`actor.require_admin`),
so these tests assert the status codes and the problem documents that come out of it,
not a router-level dependency that does not exist in this codebase.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

TODAY = date.today().isoformat()


@pytest.fixture
def fiscal_profile(admin_client: TestClient) -> dict[str, Any]:
    response = admin_client.put("/api/fiscal-profile", json={"codice_regime": "RF19"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def emitter(admin_client: TestClient) -> dict[str, Any]:
    response = admin_client.put(
        "/api/emitter",
        json={
            "ragione_sociale": "Humancraft di Ivan Sala",
            "partita_iva": "14518240966",
            "codice_fiscale": "HMCRFT00A01H501K",
            "indirizzo": "Via Vittorio Veneto 12",
            "cap": "20124",
            "comune": "Milano",
            "provincia": "MI",
            "nazione": "IT",
            "email": "someone@example.com",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def customer(admin_client: TestClient) -> dict[str, Any]:
    response = admin_client.post(
        "/api/customers",
        json={
            "ragione_sociale": "Acme S.r.l.",
            "partita_iva": "12345678901",
            "codice_sdi": "ABCDEFG",
            "indirizzo": "Corso Italia 5",
            "cap": "00100",
            "comune": "Roma",
            "provincia": "RM",
            "nazione": "IT",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _draft(client: TestClient, customer_id: str, prezzo: str = "1000.00") -> dict[str, Any]:
    response = client.post(
        "/api/invoices",
        json={
            "customer_id": customer_id,
            "causale": "Consulenza",
            "righe": [{"descrizione": "Consulenza", "prezzo_unitario": prezzo}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_fiscal_profile_round_trips(
    admin_client: TestClient, fiscal_profile: dict[str, Any]
) -> None:
    assert fiscal_profile["codice_regime"] == "RF19"
    assert fiscal_profile["soglia_bollo"] == "77.47"
    assert admin_client.get("/api/fiscal-profile").json()["codice_regime"] == "RF19"


def test_reading_a_missing_fiscal_profile_is_a_problem_document(
    admin_client: TestClient,
) -> None:
    response = admin_client.get("/api/fiscal-profile")
    if response.status_code == 404:
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "not_found"


def test_only_an_admin_may_write_the_fiscal_profile(collaboratore_client: TestClient) -> None:
    response = collaboratore_client.put("/api/fiscal-profile", json={"codice_regime": "RF19"})
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_creating_a_draft_returns_201_with_no_number(
    admin_client: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any]
) -> None:
    draft = _draft(admin_client, customer["id"])
    assert draft["stato"] == "bozza"
    assert draft["numero"] is None
    assert draft["totale"] == "1000.00"


def test_replacing_the_lines_recomputes_the_total(
    admin_client: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any]
) -> None:
    draft = _draft(admin_client, customer["id"])
    response = admin_client.put(
        f"/api/invoices/{draft['id']}/lines",
        json={"righe": [{"descrizione": "Altro", "prezzo_unitario": "250.00"}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["totale"] == "250.00"
    lines = admin_client.get(f"/api/invoices/{draft['id']}/lines").json()
    assert [line["numero_linea"] for line in lines] == [1]


def test_issuing_assigns_a_number_and_produces_both_artefacts(
    admin_client: TestClient,
    customer: dict[str, Any],
    fiscal_profile: dict[str, Any],
    emitter: dict[str, Any],
) -> None:
    draft = _draft(admin_client, customer["id"])
    response = admin_client.post(f"/api/invoices/{draft['id']}/issue", json={})
    assert response.status_code == 200, response.text
    issued = response.json()
    assert issued["stato"] == "emessa"
    assert issued["numero"] == 1
    assert issued["anno"] == date.today().year

    pdf = admin_client.get(f"/api/invoices/{issued['id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment; filename*=UTF-8''" in pdf.headers["content-disposition"]
    assert pdf.headers["x-content-type-options"] == "nosniff"

    xml = admin_client.get(f"/api/invoices/{issued['id']}/xml")
    assert xml.status_code == 200
    assert xml.headers["content-type"] == "application/xml"
    assert b"FatturaElettronica" in xml.content
    assert "IT" in xml.headers["content-disposition"]


def test_a_collaboratore_cannot_issue(
    collaboratore_client: TestClient,
    admin_client: TestClient,
    customer: dict[str, Any],
    fiscal_profile: dict[str, Any],
    emitter: dict[str, Any],
) -> None:
    draft = _draft(admin_client, customer["id"])
    response = collaboratore_client.post(f"/api/invoices/{draft['id']}/issue", json={})
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_a_collaboratore_may_record_a_payment(
    collaboratore_client: TestClient,
    admin_client: TestClient,
    customer: dict[str, Any],
    fiscal_profile: dict[str, Any],
    emitter: dict[str, Any],
) -> None:
    draft = _draft(admin_client, customer["id"])
    issued = admin_client.post(f"/api/invoices/{draft['id']}/issue", json={}).json()
    response = collaboratore_client.patch(
        f"/api/invoices/{issued['id']}/payment",
        json={"stato_pagamento": "incassato", "data_incasso": TODAY},
    )
    assert response.status_code == 200, response.text
    assert response.json()["stato_pagamento"] == "incassato"


def test_deleting_an_issued_invoice_is_a_409(
    admin_client: TestClient,
    customer: dict[str, Any],
    fiscal_profile: dict[str, Any],
    emitter: dict[str, Any],
) -> None:
    """Criterion 4: `DELETE` is refused by the API."""
    draft = _draft(admin_client, customer["id"])
    issued = admin_client.post(f"/api/invoices/{draft['id']}/issue", json={}).json()
    response = admin_client.delete(f"/api/invoices/{issued['id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_deleting_a_draft_is_204(
    admin_client: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any]
) -> None:
    draft = _draft(admin_client, customer["id"])
    assert admin_client.delete(f"/api/invoices/{draft['id']}").status_code == 204


def test_annul_then_reissue_is_the_correction_route(
    admin_client: TestClient,
    customer: dict[str, Any],
    fiscal_profile: dict[str, Any],
    emitter: dict[str, Any],
) -> None:
    first = admin_client.post(
        f"/api/invoices/{_draft(admin_client, customer['id'])['id']}/issue", json={}
    ).json()
    annulled = admin_client.post(
        f"/api/invoices/{first['id']}/annul", json={"motivo": "importo errato"}
    )
    assert annulled.status_code == 200, annulled.text
    assert annulled.json()["stato"] == "annullata"
    assert annulled.json()["numero"] == 1

    second = admin_client.post(
        f"/api/invoices/{_draft(admin_client, customer['id'])['id']}/issue", json={}
    ).json()
    assert second["numero"] == 2


def test_a_transmitted_invoice_refuses_annulment_and_says_where_to_go(
    admin_client: TestClient,
    customer: dict[str, Any],
    fiscal_profile: dict[str, Any],
    emitter: dict[str, Any],
) -> None:
    issued = admin_client.post(
        f"/api/invoices/{_draft(admin_client, customer['id'])['id']}/issue", json={}
    ).json()
    assert (
        admin_client.post(
            f"/api/invoices/{issued['id']}/transmitted", json={"data": TODAY}
        ).status_code
        == 200
    )
    response = admin_client.post(
        f"/api/invoices/{issued['id']}/annul", json={"motivo": "importo errato"}
    )
    assert response.status_code == 409
    assert "nota di credito" in response.json()["detail"]


def test_a_proforma_refuses_to_produce_xml(
    admin_client: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any], emitter: dict[str, Any]
) -> None:
    proforma = admin_client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "tipo": "proforma",
            "righe": [{"descrizione": "Consulenza", "prezzo_unitario": "500.00"}],
        },
    ).json()
    admin_client.post(f"/api/invoices/{proforma['id']}/confirm", json={})
    admin_client.post(f"/api/invoices/{proforma['id']}/artifacts", json={})
    response = admin_client.get(f"/api/invoices/{proforma['id']}/xml")
    assert response.status_code in (404, 409)
    assert response.json()["code"] in ("not_found", "conflict")


def test_converting_a_confirmed_proforma_creates_a_new_numbered_row(
    admin_client: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any], emitter: dict[str, Any]
) -> None:
    proforma = admin_client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "tipo": "proforma",
            "righe": [{"descrizione": "Consulenza", "prezzo_unitario": "500.00"}],
        },
    ).json()
    admin_client.post(f"/api/invoices/{proforma['id']}/confirm", json={})
    issued = admin_client.post(f"/api/invoices/{proforma['id']}/issue", json={}).json()
    assert issued["id"] != proforma["id"]
    assert issued["origine_proforma_id"] == proforma["id"]
    assert admin_client.get(f"/api/invoices/{proforma['id']}").json()["stato"] == "consumata"


def test_a_refusal_names_the_field_in_the_problem_document(
    admin_client: TestClient, fiscal_profile: dict[str, Any], emitter: dict[str, Any]
) -> None:
    """Criterion 9: an RFC 9457 problem document with `entity` and `field` populated,
    which is what `fieldErrorFrom` in the web client reads."""
    customer = admin_client.post(
        "/api/customers",
        json={"ragione_sociale": "Senza recapito", "nazione": "IT", "cap": "00100", "comune": "Roma", "provincia": "RM", "indirizzo": "Via Roma 1"},
    ).json()
    draft = _draft(admin_client, customer["id"])
    response = admin_client.post(f"/api/invoices/{draft['id']}/issue", json={})
    assert response.status_code == 422
    body = response.json()
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["entity"] == "customer"
    assert body["field"] == "codice_sdi"
    assert body["expected"]


def test_the_list_filters_and_paginates(
    admin_client: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any]
) -> None:
    for _ in range(3):
        _draft(admin_client, customer["id"])
    page = admin_client.get("/api/invoices", params={"limit": 2}).json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    filtered = admin_client.get("/api/invoices", params={"tipo": "proforma"}).json()
    assert filtered["items"] == []


def test_the_list_limit_is_bounded_at_the_http_layer(admin_client: TestClient) -> None:
    assert admin_client.get("/api/invoices", params={"limit": 201}).status_code == 422


def test_the_timeline_of_an_invoice_is_readable(
    admin_client: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any], emitter: dict[str, Any]
) -> None:
    issued = admin_client.post(
        f"/api/invoices/{_draft(admin_client, customer['id'])['id']}/issue", json={}
    ).json()
    entries = admin_client.get(f"/api/invoices/{issued['id']}/timeline").json()
    assert {entry["kind"] for entry in entries} >= {"created", "issued"}
    assert {entry["actor_type"] for entry in entries} == {"user"}


def test_the_openapi_document_declares_invoice_as_an_entity_type(
    admin_client: TestClient,
) -> None:
    """The generated TypeScript client reads this; a contract change must break `tsc`."""
    schema = admin_client.get("/openapi.json").json()
    assert "/api/invoices" in schema["paths"]
    assert "InvoiceRead" in schema["components"]["schemas"]
    assert "FiscalProfileRead" in schema["components"]["schemas"]
```

Use whatever `admin_client` / `collaboratore_client` fixtures `apps/api/tests/conftest.py` already provides; if the collaborator fixture has a different name there, use the real one rather than adding a second.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest apps/api/tests/test_invoices_api.py -v`
Expected: FAIL — every request 404s, because neither router is registered yet.

- [ ] **Step 3: Implement the fiscal-profile router**

`apps/api/src/pigrocrm_api/routers/fiscal_profile.py`:

```python
from fastapi import APIRouter

from pigrocrm.core.fiscal.schemas import FiscalProfileRead, FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/fiscal-profile", tags=["fiscal-profile"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=FiscalProfileRead)
def get(session: SessionDep, actor: ActorDep) -> FiscalProfileRead:
    return FiscalProfileService(session).get(actor)


@router.put("", response_model=FiscalProfileRead)
def upsert(
    data: FiscalProfileUpsert, session: SessionDep, actor: ActorDep
) -> FiscalProfileRead:
    """Admin only, enforced by the service (`actor.require_admin`), not by a router
    dependency: there is no role dependency in this codebase, and adding one here would
    put the same rule in two places."""
    return FiscalProfileService(session).upsert(data, actor)
```

- [ ] **Step 4: Implement the invoices router**

`apps/api/src/pigrocrm_api/routers/invoices.py`:

```python
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.invoices.schemas import (
    MAX_LINES,
    ArtifactKind,
    InvoiceAnnul,
    InvoiceArtifact,
    InvoiceCreate,
    InvoiceIssue,
    InvoiceLineIn,
    InvoiceLineRead,
    InvoiceListQuery,
    InvoicePage,
    InvoiceRead,
    InvoiceStato,
    InvoiceTipo,
    InvoiceTransmitted,
    InvoiceUpdate,
    PaymentState,
    StatoPagamento,
)
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm_api.deps import ActorDep, SessionDep, SettingsDep, StorageDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/invoices", tags=["invoices"], responses=PROBLEM_RESPONSES)

ANNO_MIN = 2000
ANNO_MAX = 2999


class InvoiceLinesBody(BaseModel):
    """The whole list, never a partial patch.

    A body object rather than a bare array so the endpoint can grow a sibling field
    later without becoming a different shape, and so the `max_length` bound lives in
    one place the OpenAPI document also shows.
    """

    righe: list[InvoiceLineIn] = Field(default_factory=list, max_length=MAX_LINES)


def _service(session: SessionDep, storage: StorageDep, settings: SettingsDep) -> InvoiceService:
    return InvoiceService(session, storage, settings)


@router.get("", response_model=InvoicePage)
def list_invoices(
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
    customer_id: Annotated[UUID | None, Query()] = None,
    deal_id: Annotated[UUID | None, Query()] = None,
    tipo: Annotated[InvoiceTipo | None, Query()] = None,
    stato: Annotated[InvoiceStato | None, Query()] = None,
    anno: Annotated[int | None, Query(ge=ANNO_MIN, le=ANNO_MAX)] = None,
    stato_pagamento: Annotated[StatoPagamento | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> InvoicePage:
    query = InvoiceListQuery(
        customer_id=customer_id,
        deal_id=deal_id,
        tipo=tipo,
        stato=stato,
        anno=anno,
        stato_pagamento=stato_pagamento,
        limit=limit,
        cursor=cursor,
    )
    return _service(session, storage, settings).list(query, actor)


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create(
    data: InvoiceCreate,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    return _service(session, storage, settings).create(data, actor)


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get(
    invoice_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    return _service(session, storage, settings).get(invoice_id, actor)


@router.patch("/{invoice_id}", response_model=InvoiceRead)
def update(
    invoice_id: UUID,
    data: InvoiceUpdate,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    return _service(session, storage, settings).update(invoice_id, data, actor)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(
    invoice_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> None:
    """Refused with 409 once a number has been consumed. There is no physical delete
    anywhere, and the `CHECK` on the table refuses the soft one for a numbered row even
    in raw SQL."""
    _service(session, storage, settings).soft_delete(invoice_id, actor)


@router.get("/{invoice_id}/lines", response_model=list[InvoiceLineRead])
def lines(
    invoice_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> list[InvoiceLineRead]:
    return _service(session, storage, settings).lines(invoice_id, actor)


@router.put("/{invoice_id}/lines", response_model=InvoiceRead)
def replace_lines(
    invoice_id: UUID,
    body: InvoiceLinesBody,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    """`PUT`, not `PATCH`: the whole list is replaced. It is the natural shape of a line
    editor, and it is what makes clearing an optional numeric column possible at all
    (A14)."""
    return _service(session, storage, settings).replace_lines(invoice_id, body.righe, actor)


@router.post("/{invoice_id}/confirm", response_model=InvoiceRead)
def confirm(
    invoice_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    return _service(session, storage, settings).confirm_proforma(invoice_id, actor)


@router.post("/{invoice_id}/issue", response_model=InvoiceRead)
def issue(
    invoice_id: UUID,
    data: InvoiceIssue,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    """Admin only, enforced by the service. `{invoice_id}` is the *source* row: a
    `bozza` fattura is issued in place, and a `confermata` proforma produces a new
    numbered row linked back to it."""
    return _service(session, storage, settings).issue(invoice_id, data, actor)


@router.post("/{invoice_id}/annul", response_model=InvoiceRead)
def annul(
    invoice_id: UUID,
    data: InvoiceAnnul,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    return _service(session, storage, settings).annul(invoice_id, data, actor)


@router.post("/{invoice_id}/transmitted", response_model=InvoiceRead)
def transmitted(
    invoice_id: UUID,
    data: InvoiceTransmitted,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    return _service(session, storage, settings).mark_transmitted_externally(
        invoice_id, data, actor
    )


@router.patch("/{invoice_id}/payment", response_model=InvoiceRead)
def payment(
    invoice_id: UUID,
    data: PaymentState,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> InvoiceRead:
    return _service(session, storage, settings).set_payment_state(invoice_id, data, actor)


@router.post("/{invoice_id}/artifacts", response_model=list[InvoiceArtifact])
def artifacts(
    invoice_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> list[InvoiceArtifact]:
    """Regenerate -- or verify -- the PDF and the XML. Idempotent: an unchanged
    artefact is returned rather than rewritten, a lost file is repaired with an
    identical version, and a divergence is a 409."""
    return _service(session, storage, settings).produce_artifacts(invoice_id, actor)


def _download(
    service: InvoiceService, invoice_id: UUID, kind: ArtifactKind, actor: ActorDep
) -> Response:
    data, content_type, filename = service.download(invoice_id, kind, actor)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            # RFC 5987, percent-encoded rather than interpolated: the XML name is built
            # from a fiscal identifier and the PDF name from integers, so nothing
            # dangerous should reach here -- encoding it anyway means a future change
            # cannot turn a name into a response header.
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{invoice_id}/pdf")
def download_pdf(
    invoice_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> Response:
    return _download(_service(session, storage, settings), invoice_id, "pdf", actor)


@router.get("/{invoice_id}/xml")
def download_xml(
    invoice_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> Response:
    """The download always goes through the API: it is the only place authorisation
    exists, on both storage backends."""
    return _download(_service(session, storage, settings), invoice_id, "xml", actor)


@router.get("/{invoice_id}/timeline", response_model=list[ActivityRead])
def timeline(
    invoice_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    return ActivityService(session).timeline("invoice", invoice_id, limit)
```

- [ ] **Step 5: Register both routers**

In `apps/api/src/pigrocrm_api/main.py`, add the two imports alongside the existing router imports and append them to the same registration loop the other routers already go through — the loop is what attaches `PROBLEM_RESPONSES` and the exception handler, so a router registered outside it would document its errors wrongly:

```python
from pigrocrm_api.routers import (
    auth,
    customers,
    deals,
    documents,
    emitter,
    fields,
    fiscal_profile,
    invoices,
    people,
    pipeline,
    schema,
    templates,
    tokens,
    users,
)
```

and add `invoices.router` and `fiscal_profile.router` to the sequence that file iterates over.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest apps/api/tests -v`
Expected: PASS, including `test_input_bounds_sweep.py` — it walks every route in the OpenAPI document, so two new routers put every new bound under it automatically.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/pigrocrm_api/routers/invoices.py apps/api/src/pigrocrm_api/routers/fiscal_profile.py apps/api/src/pigrocrm_api/main.py apps/api/tests/test_invoices_api.py
git commit -m "feat(api): invoice and fiscal-profile endpoints"
```

---
### Task 15: The MCP surface — an agent may prepare, never emit

**Files:**
- Create: `apps/mcp/src/pigrocrm_mcp/tools/invoices.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`
- Test: `apps/mcp/tests/test_mcp_invoices.py`
- Test: `apps/mcp/tests/test_mcp_invoice_ban.py`

**Interfaces:**
- Consumes: `InvoiceService`, `FiscalProfileService`, `InvoiceCreate`, `InvoiceLineIn`, `InvoiceListQuery`, `PaymentState`; `McpContext`; `BoundedLimit` from `tools/__init__.py`.
- Produces, from `tools/invoices.py`:
  - `MCP_FORBIDDEN_OPERATIONS: frozenset[str]` — exactly `{"issue_invoice", "annul_invoice", "mark_transmitted_externally", "update_fiscal_profile"}`
  - `MCP_UNEXPOSED_OPERATIONS: dict[str, str]` — method name to the reason it has no tool
  - `SERVICE_METHOD_TO_OPERATION: dict[str, str]`
  - `search(context, query) -> dict[str, Any]`, `get(context, invoice_id) -> dict[str, Any]`, `create_proforma(context, data) -> dict[str, Any]`, `replace_proforma_lines(context, invoice_id, righe) -> dict[str, Any]`, `render_proforma_pdf(context, invoice_id) -> dict[str, Any]`, `xml_url(context, invoice_id) -> dict[str, Any]`, `set_payment_state(context, invoice_id, stato_pagamento, data_incasso) -> dict[str, Any]`, `describe_fiscal_profile(context) -> dict[str, Any]`
- Also produces, from `tools/__init__.py`: the registered tools `list_invoices`, `get_invoice`, `create_proforma`, `replace_proforma_lines`, `render_proforma_pdf`, `get_invoice_xml_url`, `set_invoice_payment_state`, `describe_fiscal_profile`, plus `InvoiceTipoArg`, `StatoPagamentoArg`, `InvoiceLinesArg` annotated aliases.

- [ ] **Step 1: Write the failing ban test**

`apps/mcp/tests/test_mcp_invoice_ban.py`:

```python
"""Spec 14.7: the ban is in the build, not in a code review.

Three reasons the four operations below have no tool, none of them generic distrust of
agents:

1. emission is the only irreversible creation in the product. Every other mistake
   reachable through MCP undoes: a soft delete restores, a state goes back, a field is
   rewritten. Consuming a register number does not undo -- at best it is documented;
2. the guarantee has to be structural, because permissions are not enough. R10 is open
   -- a PAT has no scope and inherits the owner's full role -- so "MCP does not emit"
   is not enforceable with an authorisation check, since an administrative token would
   pass it. Not registering the tool is the only mechanism that holds while R10 is
   open;
3. it costs one click. The agent does all the work: reads the deal, composes the
   lines, produces a readable proforma. A human presses a button.
"""

import ast
import inspect
from pathlib import Path

from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm_mcp.tools.invoices import (
    MCP_FORBIDDEN_OPERATIONS,
    MCP_UNEXPOSED_OPERATIONS,
    SERVICE_METHOD_TO_OPERATION,
)

MCP_SRC = Path(inspect.getfile(FiscalProfileService)).parents[4] / "apps" / "mcp" / "src"

FORBIDDEN_SERVICE_METHODS = {
    "InvoiceService.issue",
    "InvoiceService.annul",
    "InvoiceService.mark_transmitted_externally",
    "FiscalProfileService.upsert",
}


def _public_methods(cls: type) -> set[str]:
    return {
        name
        for name, value in vars(cls).items()
        if callable(value) and not name.startswith("_")
    }


def test_the_exclusion_list_is_exactly_those_four_names() -> None:
    """Adding a tool for one of the four breaks the build; removing a name from the
    list without adding the tool breaks it too. Whoever reads the list learns that the
    absence was a decision and not an oversight."""
    assert MCP_FORBIDDEN_OPERATIONS == frozenset(
        {
            "issue_invoice",
            "annul_invoice",
            "mark_transmitted_externally",
            "update_fiscal_profile",
        }
    )


def test_every_public_service_method_is_classified_exactly_once() -> None:
    """Three buckets: reached by a tool, forbidden, or declared-unexposed with a
    reason. A new method that nobody classified fails here rather than quietly
    joining whichever bucket happens to be the default."""
    methods = _public_methods(InvoiceService) | _public_methods(FiscalProfileService)
    unclassified = methods - set(SERVICE_METHOD_TO_OPERATION) - set(MCP_UNEXPOSED_OPERATIONS)
    assert unclassified == set(), (
        "questi metodi pubblici non sono classificati: aggiungili a "
        f"SERVICE_METHOD_TO_OPERATION o a MCP_UNEXPOSED_OPERATIONS con la ragione: {unclassified}"
    )
    both = set(SERVICE_METHOD_TO_OPERATION) & set(MCP_UNEXPOSED_OPERATIONS)
    assert both == set(), f"classificati due volte: {both}"


def test_every_unexposed_method_carries_a_reason() -> None:
    assert all(reason.strip() for reason in MCP_UNEXPOSED_OPERATIONS.values())


def test_no_mcp_source_file_calls_a_forbidden_service_method() -> None:
    """Walked as an AST over every file under `apps/mcp/src`, not grepped: a rename
    that reintroduces the call under a different local alias still shows up as an
    attribute access with the forbidden name."""
    offenders: list[str] = []
    for path in MCP_SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            for qualified in FORBIDDEN_SERVICE_METHODS:
                if func.attr == qualified.split(".", 1)[1]:
                    offenders.append(f"{path.name}:{node.lineno} chiama {func.attr}")
    assert offenders == [], (
        "l'MCP non emette e non annulla: la difesa e' strutturale perche' R10 e' "
        f"aperto e un PAT amministrativo passerebbe un controllo di permessi. {offenders}"
    )


def test_no_registered_tool_is_named_after_a_forbidden_operation() -> None:
    from mcp.server import MCPServer

    from pigrocrm_mcp.server import build_server

    server: MCPServer = build_server(session_provider=lambda: None)  # type: ignore[arg-type]
    names = {tool.name for tool in server.list_tools_sync()}
    assert names & MCP_FORBIDDEN_OPERATIONS == set()


def test_the_tools_an_agent_does_get_are_the_declared_ones() -> None:
    from mcp.server import MCPServer

    from pigrocrm_mcp.server import build_server

    server: MCPServer = build_server(session_provider=lambda: None)  # type: ignore[arg-type]
    names = {tool.name for tool in server.list_tools_sync()}
    assert {
        "list_invoices",
        "get_invoice",
        "create_proforma",
        "replace_proforma_lines",
        "render_proforma_pdf",
        "get_invoice_xml_url",
        "set_invoice_payment_state",
        "describe_fiscal_profile",
    } <= names
```

`build_server` and the way `apps/mcp/tests/test_mcp_tools.py` already enumerates registered tools are the authority for the last two cases: use that file's existing helper rather than the `build_server(...)`/`list_tools_sync()` shape sketched here if it differs, and keep the assertions identical.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest apps/mcp/tests/test_mcp_invoice_ban.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm_mcp.tools.invoices'`

- [ ] **Step 3: Write the thin call module**

`apps/mcp/src/pigrocrm_mcp/tools/invoices.py`:

```python
"""Thin calls into `InvoiceService`, plus the declaration of what MCP deliberately
cannot reach.

An agent may **prepare**. It may not emit. See `apps/mcp/tests/test_mcp_invoice_ban.py`
for the three reasons, and note that the mechanism is the absence of a tool rather than
an authorisation check: R10 is open, so a PAT inherits the owner's full role and an
administrative token would pass any check written here.
"""

from datetime import date
from typing import Any
from uuid import UUID

from pigrocrm.core.errors import Conflict
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import (
    InvoiceCreate,
    InvoiceLineIn,
    InvoiceListQuery,
    PaymentState,
)
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm_mcp.context import McpContext

# Operations that must **never** be reachable from MCP. Asserted to be exactly these
# four names by the ban test: adding a tool for one of them breaks the build, and
# removing a name without adding the tool breaks it too.
MCP_FORBIDDEN_OPERATIONS: frozenset[str] = frozenset(
    {
        "issue_invoice",
        "annul_invoice",
        "mark_transmitted_externally",
        "update_fiscal_profile",
    }
)

# Public service methods with no tool that are **not** forbidden -- they simply have no
# audience on the agentic surface. Each carries its reason, so the distinction between
# "must never be exposed" and "happens not to be exposed" stays visible.
MCP_UNEXPOSED_OPERATIONS: dict[str, str] = {
    "update": "note interne e campi custom: nessun agente ha motivo di scriverli, e "
    "la causale e' congelata dopo l'emissione",
    "soft_delete": "la spec dello slice 1 ha gia' deciso che l'MCP non espone delete "
    "distruttivi",
    "confirm_proforma": "e' la conferma umana che precede l'emissione: l'agente "
    "prepara, la persona conferma",
    "export_xml": "l'XML esiste solo per una fattura emessa, e l'MCP non emette; "
    "get_invoice_xml_url restituisce l'URL di uno gia' prodotto",
    "produce_artifacts": "rigenerazione di artefatti fiscali: appartiene alla persona "
    "che ha emesso",
    "download": "l'MCP non restituisce mai byte, solo identificativi e URL "
    "(spec slice 2 §7)",
    "lines": "get_invoice restituisce gia' la fattura; le righe si leggono dall'API",
    "render_pdf": "esposto come render_proforma_pdf, che rifiuta una fattura",
    "snapshot": "lettura interna del profilo fiscale, senza actor e senza audience",
    "get": "esposto come get_invoice / describe_fiscal_profile",
}

# Which operation name each public service method belongs to, for the operations that
# *are* exposed or forbidden. `get` appears in MCP_UNEXPOSED_OPERATIONS because both
# services define one and the tools call the domain-specific wrappers below.
SERVICE_METHOD_TO_OPERATION: dict[str, str] = {
    "list": "list_invoices",
    "create": "create_proforma",
    "replace_lines": "replace_proforma_lines",
    "set_payment_state": "set_invoice_payment_state",
    "describe": "describe_fiscal_profile",
    "issue": "issue_invoice",
    "annul": "annul_invoice",
    "mark_transmitted_externally": "mark_transmitted_externally",
    "upsert": "update_fiscal_profile",
}


def _invoices(context: McpContext) -> InvoiceService:
    return InvoiceService(context.session, context.storage)


def search(context: McpContext, query: InvoiceListQuery) -> dict[str, Any]:
    page = _invoices(context).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def get(context: McpContext, invoice_id: str) -> dict[str, Any]:
    service = _invoices(context)
    invoice = service.get(UUID(invoice_id), context.actor)
    return {
        **invoice.model_dump(mode="json"),
        "righe": [
            line.model_dump(mode="json")
            for line in service.lines(UUID(invoice_id), context.actor)
        ],
    }


def create_proforma(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    """`tipo` is forced to `proforma` here rather than taken from the caller: this is
    the only creation an agent performs, and letting it choose would put a draft
    invoice -- one button away from a consumed number -- on the agentic surface."""
    payload = {**data, "tipo": "proforma"}
    return _invoices(context).create(InvoiceCreate(**payload), context.actor).model_dump(
        mode="json"
    )


def _require_proforma(service: InvoiceService, invoice_id: UUID, context: McpContext) -> None:
    invoice = service.get(invoice_id, context.actor)
    if invoice.tipo != "proforma":
        raise Conflict(
            "invoice",
            "da MCP si modificano solo le proforma: una fattura la prepara e la emette "
            "una persona",
            tipo=invoice.tipo,
            stato=invoice.stato,
        )


def replace_proforma_lines(
    context: McpContext, invoice_id: str, righe: list[dict[str, Any]]
) -> dict[str, Any]:
    service = _invoices(context)
    identifier = UUID(invoice_id)
    _require_proforma(service, identifier, context)
    return service.replace_lines(
        identifier, [InvoiceLineIn(**riga) for riga in righe], context.actor
    ).model_dump(mode="json")


def render_proforma_pdf(context: McpContext, invoice_id: str) -> dict[str, Any]:
    service = _invoices(context)
    identifier = UUID(invoice_id)
    _require_proforma(service, identifier, context)
    artifact = service.render_pdf(identifier, context.actor)
    return {
        **artifact.model_dump(mode="json"),
        # An identifier and a URL, never the bytes: a base64 PDF inside a model's own
        # context is waste and risk (slice 2 §7).
        "download_url": f"/api/invoices/{invoice_id}/pdf",
    }


def xml_url(context: McpContext, invoice_id: str) -> dict[str, Any]:
    """The URL of an already-produced XML. Never the bytes, and never a production:
    producing one requires an issued invoice, and MCP does not issue."""
    invoice = _invoices(context).get(UUID(invoice_id), context.actor)
    if invoice.xml_document_id is None:
        raise Conflict(
            "invoice",
            "questa fattura non ha ancora un file XML: va prodotto dall'applicazione",
            stato=invoice.stato,
        )
    return {
        "invoice_id": invoice_id,
        "numero": f"{invoice.anno}/{invoice.numero}",
        "download_url": f"/api/invoices/{invoice_id}/xml",
        "hash_sha256": invoice.xml_hash_sha256,
    }


def set_payment_state(
    context: McpContext, invoice_id: str, stato_pagamento: str, data_incasso: str | None
) -> dict[str, Any]:
    return (
        _invoices(context)
        .set_payment_state(
            UUID(invoice_id),
            PaymentState(
                stato_pagamento=stato_pagamento,  # type: ignore[arg-type]
                data_incasso=date.fromisoformat(data_incasso) if data_incasso else None,
            ),
            context.actor,
        )
        .model_dump(mode="json")
    )


def describe_fiscal_profile(context: McpContext) -> dict[str, Any]:
    return FiscalProfileService(context.session).describe(context.actor)
```

- [ ] **Step 4: Register the tools**

In `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`, add `invoices` to the module import, add the three annotated aliases next to the existing ones, and register the eight tools at the end of `register_entity_tools`:

```python
from pigrocrm_mcp.tools import customers, deals, documents, invoices, people
```

```python
# Same runtime-permissive / schema-only-strict split as `OfferStateArg`: the parameter
# stays a plain `str` so a wrong value is rejected by the schema's own `Literal` inside
# the guarded call and rendered as guidance, while `list_tools()` shows the real
# choices. R2 is open, and this is the technique that keeps a raw pydantic dump out of
# an agent's context.
InvoiceTipoArg = Annotated[
    str | None,
    WithJsonSchema(
        {"anyOf": [{"type": "string", "enum": ["fattura", "proforma"]}, {"type": "null"}], "default": None}
    ),
]
InvoiceStatoArg = Annotated[
    str | None,
    WithJsonSchema(
        {
            "anyOf": [
                {
                    "type": "string",
                    "enum": ["bozza", "emessa", "annullata", "confermata", "consumata"],
                },
                {"type": "null"},
            ],
            "default": None,
        }
    ),
]
StatoPagamentoArg = Annotated[
    str,
    WithJsonSchema({"type": "string", "enum": ["da_incassare", "incassato"]}),
]
InvoiceLinesArg = Annotated[
    list[dict[str, Any]],
    WithJsonSchema(
        {
            "type": "array",
            "maxItems": 200,
            "items": InvoiceLineIn.model_json_schema(),
        }
    ),
]
```

with `from pigrocrm.core.invoices.schemas import InvoiceLineIn, InvoiceListQuery` added to that module's imports, and then:

```python
    # ---- invoices ----------------------------------------------------------
    # An agent may prepare. It may not emit. `issue_invoice`, `annul_invoice`,
    # `mark_transmitted_externally` and `update_fiscal_profile` are deliberately
    # absent, and `apps/mcp/tests/test_mcp_invoice_ban.py` is what keeps them absent:
    # the guarantee is structural because R10 (a PAT has no scope and inherits the
    # owner's full role) means an authorisation check would be passed by an
    # administrative token.

    @mcp.tool()
    @guard
    def list_invoices(
        customer_id: str | None = None,
        deal_id: str | None = None,
        tipo: InvoiceTipoArg = None,
        stato: InvoiceStatoArg = None,
        anno: int | str | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Elenca fatture e proforma. Passa `next_cursor` come `cursor` per la pagina
        successiva. Per scaricare i byte usa l'API REST: MCP restituisce
        identificativi."""
        return invoices.search(
            context,
            InvoiceListQuery(
                customer_id=UUID(customer_id) if customer_id else None,
                deal_id=UUID(deal_id) if deal_id else None,
                tipo=tipo,  # type: ignore[arg-type]
                stato=stato,  # type: ignore[arg-type]
                anno=cast(int, anno) if anno is not None else None,
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def get_invoice(invoice_id: str) -> dict[str, Any]:
        """Legge una fattura o una proforma con le sue righe, i totali e lo stato."""
        return invoices.get(context, invoice_id)

    @mcp.tool()
    @guard
    def describe_fiscal_profile() -> dict[str, Any]:
        """I parametri fiscali in vigore: regime, aliquota di default, natura, bollo,
        condizioni di pagamento e giorni di scadenza. Chiamalo **prima** di comporre
        una proforma, per sapere che aliquota le righe possono portare."""
        return invoices.describe_fiscal_profile(context)

    @mcp.tool()
    @guard
    def create_proforma(
        customer_id: str,
        righe: InvoiceLinesArg,
        deal_id: str | None = None,
        causale: str | None = None,
    ) -> dict[str, Any]:
        """Crea una proforma: ha la forma di una fattura, si manda al cliente e non
        tocca il registro fiscale. Non consuma un numero. L'emissione la fa una
        persona dall'applicazione: non esiste un tool per emettere."""
        return invoices.create_proforma(
            context,
            {
                "customer_id": UUID(customer_id),
                "deal_id": UUID(deal_id) if deal_id else None,
                "causale": causale,
                "righe": righe,
            },
        )

    @mcp.tool()
    @guard
    def replace_proforma_lines(invoice_id: str, righe: InvoiceLinesArg) -> dict[str, Any]:
        """Sostituisce **tutte** le righe di una proforma e ricalcola i totali. Non e'
        una modifica parziale: l'elenco che passi diventa l'elenco completo."""
        return invoices.replace_proforma_lines(context, invoice_id, righe)

    @mcp.tool()
    @guard
    def render_proforma_pdf(invoice_id: str) -> dict[str, Any]:
        """Genera il PDF di una proforma e restituisce l'URL da cui scaricarlo. Il PDF
        porta nel corpo la dichiarazione FATTURA PROFORMA - NON COSTITUISCE FATTURA."""
        return invoices.render_proforma_pdf(context, invoice_id)

    @mcp.tool()
    @guard
    def get_invoice_xml_url(invoice_id: str) -> dict[str, Any]:
        """L'URL del file FatturaPA di una fattura gia' emessa. Restituisce un URL, mai
        i byte."""
        return invoices.xml_url(context, invoice_id)

    @mcp.tool()
    @guard
    def set_invoice_payment_state(
        invoice_id: str, stato_pagamento: StatoPagamentoArg, data_incasso: IsoDateStr = None
    ) -> dict[str, Any]:
        """Registra l'incasso di una fattura emessa. `data_incasso` in formato
        YYYY-MM-DD ed e' obbligatoria quando lo stato e' `incassato`."""
        return invoices.set_payment_state(context, invoice_id, stato_pagamento, data_incasso)
```

- [ ] **Step 5: Write the behavioural MCP test**

`apps/mcp/tests/test_mcp_invoices.py`:

```python
"""What an agent can actually do: read, prepare a proforma, render it, record a
payment -- and find no tool at all when it tries to issue.
"""

from decimal import Decimal
from typing import Any

import pytest

from pigrocrm.core.errors import Conflict
from pigrocrm.core.invoices.schemas import InvoiceListQuery
from pigrocrm_mcp.tools import invoices


def test_an_agent_can_prepare_a_proforma_with_three_lines(mcp_context) -> None:  # type: ignore[no-untyped-def]
    customer_id = _customer(mcp_context)
    created = invoices.create_proforma(
        mcp_context,
        {
            "customer_id": customer_id,
            "causale": "Consulenza agosto",
            "righe": [
                {"descrizione": "Analisi", "prezzo_unitario": "500.00"},
                {"descrizione": "Sviluppo", "prezzo_unitario": "1500.00"},
                {"descrizione": "Sconto", "prezzo_unitario": "-200.00"},
            ],
        },
    )
    assert created["tipo"] == "proforma"
    assert created["numero"] is None
    assert created["riferimento"].startswith("PROV-")
    assert created["totale"] == "1800.00"


def test_an_agent_cannot_create_a_fattura_even_by_asking(mcp_context) -> None:  # type: ignore[no-untyped-def]
    """`tipo` is forced, not taken from the caller: a draft invoice is one button away
    from a consumed number, so it is not on the agentic surface."""
    created = invoices.create_proforma(
        mcp_context,
        {"customer_id": _customer(mcp_context), "tipo": "fattura", "righe": []},
    )
    assert created["tipo"] == "proforma"


def test_an_agent_cannot_edit_the_lines_of_a_fattura(mcp_context) -> None:  # type: ignore[no-untyped-def]
    invoice_id = _draft_invoice(mcp_context)
    with pytest.raises(Conflict):
        invoices.replace_proforma_lines(
            mcp_context, invoice_id, [{"descrizione": "X", "prezzo_unitario": "1.00"}]
        )


def test_rendering_a_proforma_returns_a_url_and_never_bytes(mcp_context) -> None:  # type: ignore[no-untyped-def]
    created = invoices.create_proforma(
        mcp_context,
        {
            "customer_id": _customer(mcp_context),
            "righe": [{"descrizione": "Analisi", "prezzo_unitario": "500.00"}],
        },
    )
    result = invoices.render_proforma_pdf(mcp_context, created["id"])
    assert result["download_url"] == f"/api/invoices/{created['id']}/pdf"
    assert not any(isinstance(value, bytes) for value in result.values())


def test_the_xml_url_of_an_unissued_invoice_is_a_conflict_not_a_produced_file(
    mcp_context,
) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Conflict):
        invoices.xml_url(mcp_context, _draft_invoice(mcp_context))


def test_describe_fiscal_profile_tells_an_agent_what_rate_a_line_may_carry(
    mcp_context,
) -> None:  # type: ignore[no-untyped-def]
    described = invoices.describe_fiscal_profile(mcp_context)
    assert described["codice_regime"] == "RF19"
    assert described["aliquota_iva_default"] == "0.00"
    assert "id" not in described


def test_listing_returns_identifiers_and_a_cursor(mcp_context) -> None:  # type: ignore[no-untyped-def]
    _draft_invoice(mcp_context)
    page = invoices.search(mcp_context, InvoiceListQuery(limit=1))
    assert len(page["items"]) == 1
    assert "next_cursor" in page
```

Build `_customer`, `_draft_invoice` and the `mcp_context` fixture on top of whatever `apps/mcp/tests/conftest.py` already provides — `test_mcp_documents.py` is the closest precedent and already sets up a context with a session, a storage backend and an actor; reuse its fixture rather than adding a parallel one, and seed the fiscal and emitter profiles the same way `test_mcp_documents.py` seeds the emitter profile.

- [ ] **Step 6: Run everything**

Run: `uv run pytest apps/mcp/tests -v`
Expected: PASS

Run: `uv run pytest packages/core/tests/test_architecture.py apps/mcp/tests/test_mcp_invoice_ban.py -v`
Expected: PASS

To prove the ban test has teeth, temporarily add a `@mcp.tool()` named `issue_invoice` that calls `invoices` and re-run: `test_the_exclusion_list_is_exactly_those_four_names` still passes but `test_no_registered_tool_is_named_after_a_forbidden_operation` and `test_no_mcp_source_file_calls_a_forbidden_service_method` both fail. Remove it before committing.

- [ ] **Step 7: Commit**

```bash
git add apps/mcp/src/pigrocrm_mcp/tools/invoices.py apps/mcp/src/pigrocrm_mcp/tools/__init__.py apps/mcp/tests/test_mcp_invoices.py apps/mcp/tests/test_mcp_invoice_ban.py
git commit -m "feat(mcp): an agent may prepare a proforma, and cannot emit at all"
```

---

# Phase 4 — The web app

### Task 16: The invoice data layer

**Files:**
- Modify: `apps/web/src/lib/query.ts`
- Create: `apps/web/src/features/invoices/queries.ts`
- Create: `apps/web/src/features/invoices/format.ts`
- Test: `apps/web/src/features/invoices/queries.test.tsx`
- Test: `apps/web/src/features/invoices/format.test.ts`

**Interfaces:**
- Consumes: `api`, `unwrap`, `toProblem` from `@/lib/api`; `queryKeys` from `@/lib/query`; the regenerated `components['schemas']` types.
- Produces, from `queries.ts`:
  - types `Invoice`, `InvoiceLine`, `InvoicePage`, `InvoiceArtifact`, `FiscalProfile`, `InvoiceOwner`
  - `INVOICE_STATE_LABELS: Record<InvoiceStato, string>`, `PAYMENT_STATE_LABELS: Record<StatoPagamento, string>`, `INVOICE_TYPE_LABELS: Record<InvoiceTipo, string>`
  - `useInvoices(params)`, `useInvoice(invoiceId)`, `useInvoiceLines(invoiceId)`, `useInvoiceTimeline(invoiceId)`, `useFiscalProfile()`
  - `useCreateInvoice()`, `useReplaceLines(invoiceId)`, `useConfirmProforma(invoiceId)`, `useIssueInvoice(invoiceId)`, `useAnnulInvoice(invoiceId)`, `useMarkTransmitted(invoiceId)`, `useSetPaymentState(invoiceId)`, `useProduceArtifacts(invoiceId)`, `useUpdateInvoice(invoiceId)`, `useDeleteInvoice()`, `useSaveFiscalProfile()`
  - `downloadInvoiceArtifact(invoiceId: string, kind: 'pdf' | 'xml'): Promise<void>`
- Produces, from `format.ts`: `formatMoney(value: string | null): string`, `formatQuantity(value: string | null): string`, `formatRate(value: string | null): string`, `formatDate(value: string | null): string`, `formatInvoiceNumber(invoice: Pick<Invoice, 'anno' | 'numero' | 'riferimento'>): string`, `sumLineTotals(lines: Pick<InvoiceLine, 'prezzo_totale'>[]): string`

- [ ] **Step 1: Regenerate the API types**

```bash
uv run uvicorn pigrocrm_api.main:app --port 8000 &
cd apps/web && pnpm generate:api && cd ../..
kill %1
```

`apps/web/src/lib/api-types.ts` must now contain `InvoiceRead`, `InvoiceLineRead`, `InvoicePage`, `InvoiceArtifact`, `FiscalProfileRead` and the `/api/invoices*` paths. If it does not, the routers are not registered — go back to Task 14 rather than hand-writing a type.

- [ ] **Step 2: Write the failing formatting test**

`apps/web/src/features/invoices/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { formatDate, formatInvoiceNumber, formatMoney, formatQuantity, formatRate, sumLineTotals } from './format'

describe('formatMoney', () => {
  it('always shows the thousands separator', () => {
    // `useGrouping: 'always'` is not optional: the default withholds the separator
    // below five integer digits, so 1.500,00 EUR would print as 1500,00 EUR.
    expect(formatMoney('1500.00')).toContain('1.500,00')
  })

  it('renders a null as an em dash, not as zero', () => {
    expect(formatMoney(null)).toBe('—')
  })

  it('keeps a negative line readable', () => {
    expect(formatMoney('-200.00')).toContain('200,00')
  })
})

describe('sumLineTotals', () => {
  it('adds integer cents, never JS floats', () => {
    // Number('0.29') * 100 is 28.999999999999996. On an invoice that is a wrong total.
    expect(sumLineTotals([{ prezzo_totale: '0.29' }, { prezzo_totale: '0.01' }])).toBe('0.30')
  })

  it('handles a negative discount line', () => {
    expect(sumLineTotals([{ prezzo_totale: '1000.00' }, { prezzo_totale: '-200.00' }])).toBe('800.00')
  })

  it('is zero for no lines', () => {
    expect(sumLineTotals([])).toBe('0.00')
  })
})

describe('formatQuantity and formatRate', () => {
  it('shows a quantity with its six decimals trimmed to what matters', () => {
    expect(formatQuantity('3.000000')).toBe('3')
    expect(formatQuantity('3.500000')).toBe('3,5')
  })

  it('shows a rate as a percentage', () => {
    expect(formatRate('0.00')).toBe('0%')
    expect(formatRate('22.00')).toBe('22%')
  })
})

describe('formatInvoiceNumber', () => {
  it('is year slash number for an issued invoice', () => {
    expect(formatInvoiceNumber({ anno: 2026, numero: 7, riferimento: null })).toBe('2026/7')
  })

  it('is the reference for a proforma', () => {
    expect(formatInvoiceNumber({ anno: null, numero: null, riferimento: 'PROV-2026-0007' })).toBe(
      'PROV-2026-0007',
    )
  })

  it('is an em dash for a draft with neither', () => {
    expect(formatInvoiceNumber({ anno: null, numero: null, riferimento: null })).toBe('—')
  })
})

describe('formatDate', () => {
  it('renders an ISO date in Italian without touching the timezone', () => {
    // Parsed field by field, never `new Date('2026-01-01')`, which is UTC midnight and
    // renders as 31 December west of Greenwich -- the same class of defect as
    // `toISOString()` on the backend.
    expect(formatDate('2026-01-01')).toBe('1/1/2026')
  })

  it('renders a null as an em dash', () => {
    expect(formatDate(null)).toBe('—')
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/features/invoices/format.test.ts`
Expected: FAIL — the module does not exist.

- [ ] **Step 4: Implement the formatters**

`apps/web/src/features/invoices/format.ts`:

```ts
import type { Invoice, InvoiceLine } from './queries'

const EMPTY = '—'

// `useGrouping: 'always'` is mandatory: the default withholds the thousands separator
// below five integer digits, so 1500.00 would print as "1500,00 €". Typing it needs
// "ES2023.Intl" in tsconfig's `lib`, which is already there.
const euro = new Intl.NumberFormat('it-IT', {
  style: 'currency',
  currency: 'EUR',
  useGrouping: 'always',
})
const quantity = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 6 })
const italianDate = new Intl.DateTimeFormat('it-IT')

/**
 * Integer cents parsed out of the decimal string the API sends.
 *
 * A local copy rather than an import from `features/deals/columns.tsx`, where the
 * same helper is private: the codebase's precedent is a small per-feature display
 * helper, and exporting that one would widen a module's public surface and its test.
 */
function centsFromDecimalString(value: string): number {
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [wholePart, fractionPart = ''] = unsigned.split('.')
  const cents = Number(wholePart || '0') * 100 + Number((fractionPart + '00').slice(0, 2))
  return negative ? -cents : cents
}

export function formatMoney(value: string | null): string {
  return value === null ? EMPTY : euro.format(centsFromDecimalString(value) / 100)
}

export function formatQuantity(value: string | null): string {
  return value === null ? EMPTY : quantity.format(Number(value))
}

export function formatRate(value: string | null): string {
  return value === null ? EMPTY : `${quantity.format(Number(value))}%`
}

/**
 * An ISO date, parsed field by field.
 *
 * Never `new Date('2026-01-01')`: that is UTC midnight, which renders as 31 December
 * anywhere west of Greenwich. It is the same defect as `toISOString()` on the backend,
 * in the other direction, and on an invoice it shows the wrong fiscal year.
 */
export function formatDate(value: string | null): string {
  if (value === null) return EMPTY
  const [year, month, day] = value.split('-').map(Number)
  if (year === undefined || month === undefined || day === undefined) return value
  return italianDate.format(new Date(year, month - 1, day))
}

/**
 * The label a human reads. Two integers joined by a slash is presentation, not
 * business logic -- and a proforma's reference deliberately cannot be produced by this
 * function from a number, because it never has one.
 */
export function formatInvoiceNumber(
  invoice: Pick<Invoice, 'anno' | 'numero' | 'riferimento'>,
): string {
  if (invoice.anno !== null && invoice.numero !== null) return `${invoice.anno}/${invoice.numero}`
  return invoice.riferimento ?? EMPTY
}

/**
 * The sum of the line totals, for the editor's live preview only.
 *
 * The authoritative totals are the ones the API stored; this exists so the editor can
 * show a running figure before saving, and it adds integer cents because
 * `Number('0.29') * 100` is `28.999999999999996`.
 */
export function sumLineTotals(lines: Pick<InvoiceLine, 'prezzo_totale'>[]): string {
  const cents = lines.reduce((sum, line) => sum + centsFromDecimalString(line.prezzo_totale), 0)
  const negative = cents < 0
  const absolute = Math.abs(cents)
  return `${negative ? '-' : ''}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, '0')}`
}
```

- [ ] **Step 5: Add the query keys**

In `apps/web/src/lib/query.ts`, add to the `queryKeys` object, keeping the established convention that a list key takes `(params?: unknown)` so calling it with no argument is an invalidation wildcard:

```ts
  invoices: (params?: unknown) => ['invoices', params ?? {}] as const,
  invoice: (id: string) => ['invoice', id] as const,
  invoiceLines: (id: string) => ['invoice-lines', id] as const,
  fiscalProfile: ['fiscal-profile'] as const,
```

- [ ] **Step 6: Write the failing hooks test**

`apps/web/src/features/invoices/queries.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useInvoice, useInvoices } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/invoices?')) {
        return new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ id: 'x' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useInvoice', () => {
  it('does not fire a request for an empty id', async () => {
    // B1: `useCustomer('')` once produced a 307 to the *list* endpoint with an
    // absolute URL, bypassing even the Vite proxy. The guard is on the hook, and this
    // is the test the original fix never got.
    const { result } = renderHook(() => useInvoice(''), { wrapper })
    await waitFor(() => expect(result.current.fetchStatus).toBe('idle'))
    expect(result.current.isPending).toBe(true)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('fires for a real id', async () => {
    const { result } = renderHook(() => useInvoice('0192f0aa-0000-7000-8000-000000000001'), {
      wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetch).toHaveBeenCalled()
  })
})

describe('useInvoices', () => {
  it('passes the filters through as query parameters', async () => {
    const { result } = renderHook(() => useInvoices({ tipo: 'proforma', anno: 2026 }), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const called = String((fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]?.[0])
    expect(called).toContain('tipo=proforma')
    expect(called).toContain('anno=2026')
  })
})
```

- [ ] **Step 7: Implement the hooks**

`apps/web/src/features/invoices/queries.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toProblem, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

export type Invoice = components['schemas']['InvoiceRead']
export type InvoiceLine = components['schemas']['InvoiceLineRead']
export type InvoiceLineInput = components['schemas']['InvoiceLineIn']
export type InvoicePage = components['schemas']['InvoicePage']
export type InvoiceArtifact = components['schemas']['InvoiceArtifact']
export type FiscalProfile = components['schemas']['FiscalProfileRead']
export type Activity = components['schemas']['ActivityRead']

export type InvoiceTipo = 'fattura' | 'proforma'
export type InvoiceStato = 'bozza' | 'emessa' | 'annullata' | 'confermata' | 'consumata'
export type StatoPagamento = 'da_incassare' | 'incassato'

export interface InvoiceFilters {
  customer_id?: string
  deal_id?: string
  tipo?: InvoiceTipo
  stato?: InvoiceStato
  anno?: number
  stato_pagamento?: StatoPagamento
  limit?: number
  cursor?: string
}

export const INVOICE_TYPE_LABELS: Record<InvoiceTipo, string> = {
  fattura: 'Fattura',
  proforma: 'Proforma',
}

export const INVOICE_STATE_LABELS: Record<InvoiceStato, string> = {
  bozza: 'Bozza',
  emessa: 'Emessa',
  annullata: 'Annullata',
  confermata: 'Confermata',
  consumata: 'Consumata',
}

export const PAYMENT_STATE_LABELS: Record<StatoPagamento, string> = {
  da_incassare: 'Da incassare',
  incassato: 'Incassato',
}

/**
 * Which buttons a row can offer, mirroring `STATO_TRANSITIONS` in
 * `packages/core/.../invoices/schemas.py`.
 *
 * A mirror for rendering only: the server validates every transition and its 409
 * message is what gets shown. This is the same convention `OFFER_TRANSITIONS` in
 * `features/documents/queries.ts` already established.
 */
export const INVOICE_TRANSITIONS: Record<InvoiceStato, InvoiceStato[]> = {
  bozza: ['emessa', 'confermata'],
  confermata: ['consumata', 'bozza'],
  emessa: ['annullata'],
  annullata: [],
  consumata: [],
}

export function useInvoices(filters: InvoiceFilters = {}) {
  return useQuery({
    queryKey: queryKeys.invoices(filters),
    queryFn: () => unwrap(api.GET('/api/invoices', { params: { query: filters } })),
  })
}

export function useInvoice(invoiceId: string) {
  return useQuery({
    // B1: an empty id must not produce a request at all. `useCustomer('')` once
    // redirected to the list endpoint with an absolute URL, bypassing the Vite proxy.
    enabled: invoiceId !== '',
    queryKey: queryKeys.invoice(invoiceId),
    queryFn: () =>
      unwrap(
        api.GET('/api/invoices/{invoice_id}', { params: { path: { invoice_id: invoiceId } } }),
      ),
  })
}

export function useInvoiceLines(invoiceId: string) {
  return useQuery({
    enabled: invoiceId !== '',
    queryKey: queryKeys.invoiceLines(invoiceId),
    queryFn: () =>
      unwrap(
        api.GET('/api/invoices/{invoice_id}/lines', {
          params: { path: { invoice_id: invoiceId } },
        }),
      ),
  })
}

export function useInvoiceTimeline(invoiceId: string) {
  return useQuery({
    enabled: invoiceId !== '',
    queryKey: queryKeys.timeline('invoice', invoiceId),
    queryFn: () =>
      unwrap(
        api.GET('/api/invoices/{invoice_id}/timeline', {
          params: { path: { invoice_id: invoiceId } },
        }),
      ),
  })
}

export function useFiscalProfile() {
  return useQuery({
    queryKey: queryKeys.fiscalProfile,
    queryFn: async (): Promise<FiscalProfile | null> => {
      // A 404 here means "not configured yet", which is a legitimate state and not an
      // error -- the same treatment `useEmitter` in features/settings/queries.ts gives
      // its own singleton row.
      const { data, error, response } = await api.GET('/api/fiscal-profile')
      if (response.status === 404) return null
      if (error !== undefined) throw toProblem(error, response.status)
      return data ?? null
    },
  })
}

function useInvoiceInvalidation() {
  const queryClient = useQueryClient()
  return (invoiceId?: string) => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.invoices() })
    if (invoiceId !== undefined) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.invoice(invoiceId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.invoiceLines(invoiceId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('invoice', invoiceId) })
    }
  }
}

export function useCreateInvoice() {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/invoices', { body: body as never })),
    onSuccess: (invoice) => invalidate(invoice.id),
  })
}

export function useUpdateInvoice(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/api/invoices/{invoice_id}', {
          params: { path: { invoice_id: invoiceId } },
          body: body as never,
        }),
      ),
    onSuccess: () => invalidate(invoiceId),
  })
}

export function useReplaceLines(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (righe: InvoiceLineInput[]) =>
      unwrap(
        api.PUT('/api/invoices/{invoice_id}/lines', {
          params: { path: { invoice_id: invoiceId } },
          body: { righe },
        }),
      ),
    onSuccess: () => invalidate(invoiceId),
  })
}

export function useConfirmProforma(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/invoices/{invoice_id}/confirm', {
          params: { path: { invoice_id: invoiceId } },
        }),
      ),
    onSuccess: () => invalidate(invoiceId),
  })
}

export function useIssueInvoice(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (body: { data_emissione?: string | null }) =>
      unwrap(
        api.POST('/api/invoices/{invoice_id}/issue', {
          params: { path: { invoice_id: invoiceId } },
          body,
        }),
      ),
    onSuccess: (issued) => {
      // The issued row may be a *different* row when the source was a proforma, so
      // both are invalidated: the proforma is now `consumata`.
      invalidate(invoiceId)
      invalidate(issued.id)
    },
  })
}

export function useAnnulInvoice(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (motivo: string) =>
      unwrap(
        api.POST('/api/invoices/{invoice_id}/annul', {
          params: { path: { invoice_id: invoiceId } },
          body: { motivo },
        }),
      ),
    onSuccess: () => invalidate(invoiceId),
  })
}

export function useMarkTransmitted(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (data: string) =>
      unwrap(
        api.POST('/api/invoices/{invoice_id}/transmitted', {
          params: { path: { invoice_id: invoiceId } },
          body: { data },
        }),
      ),
    onSuccess: () => invalidate(invoiceId),
  })
}

export function useSetPaymentState(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (body: { stato_pagamento: StatoPagamento; data_incasso?: string | null }) =>
      unwrap(
        api.PATCH('/api/invoices/{invoice_id}/payment', {
          params: { path: { invoice_id: invoiceId } },
          body,
        }),
      ),
    onSuccess: () => invalidate(invoiceId),
  })
}

export function useProduceArtifacts(invoiceId: string) {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/invoices/{invoice_id}/artifacts', {
          params: { path: { invoice_id: invoiceId } },
        }),
      ),
    onSuccess: () => invalidate(invoiceId),
  })
}

export function useDeleteInvoice() {
  const invalidate = useInvoiceInvalidation()
  return useMutation({
    mutationFn: (invoiceId: string) =>
      unwrap(
        api.DELETE('/api/invoices/{invoice_id}', {
          params: { path: { invoice_id: invoiceId } },
        }),
      ),
    onSuccess: () => invalidate(),
  })
}

export function useSaveFiscalProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.PUT('/api/fiscal-profile', { body: body as never })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.fiscalProfile })
    },
  })
}

/**
 * A blob download, the one documented exception to "no `fetch` inside components"
 * already established by `downloadDocument` in `features/documents/queries.ts`:
 * `openapi-fetch` cannot express a binary response, and the server's own
 * `Content-Disposition` is what names the file -- which for the XML is the SdI's
 * convention and matters to whoever receives it.
 */
export async function downloadInvoiceArtifact(
  invoiceId: string,
  kind: 'pdf' | 'xml',
): Promise<void> {
  const response = await fetch(`/api/invoices/${invoiceId}/${kind}`, { credentials: 'include' })
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    throw toProblem(payload, response.status)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = ''
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
```

- [ ] **Step 8: Run the tests and the compiler**

Run: `cd apps/web && pnpm exec vitest run src/features/invoices && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS and clean.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/lib/query.ts apps/web/src/lib/api-types.ts apps/web/src/features/invoices/
git commit -m "feat(web): invoice query hooks and exact-cents money formatting"
```

---
### Task 17: The Fatture list

**Files:**
- Create: `apps/web/src/features/invoices/columns.tsx`
- Create: `apps/web/src/features/invoices/InvoiceStateBadge.tsx`
- Create: `apps/web/src/routes/app/fatture/index.tsx`
- Modify: `apps/web/src/components/AppShell.tsx`
- Modify: `apps/web/src/components/AppShell.test.tsx`
- Modify: `apps/web/eslint.config.js`
- Test: `apps/web/src/features/invoices/columns.test.ts`

**Interfaces:**
- Consumes: `DataTable`, `DataTableFeatures`; `useInvoices`, `Invoice`, `INVOICE_STATE_LABELS`, `PAYMENT_STATE_LABELS`, `INVOICE_TYPE_LABELS`; `formatMoney`, `formatDate`, `formatInvoiceNumber`.
- Produces:
  - `buildInvoiceColumns(): ColumnDef<DataTableFeatures, Invoice>[]`
  - `InvoiceStateBadge({ invoice }: { invoice: Pick<Invoice, 'stato' | 'stato_pagamento' | 'tipo'> })`
  - route `/app/fatture/` rendering `InvoicesPage`
  - `NAV` in `AppShell.tsx` gains `{ to: '/app/fatture', label: 'Fatture', icon: Receipt }`

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/invoices/columns.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildInvoiceColumns } from './columns'
import type { Invoice } from './queries'

const ISSUED = {
  anno: 2026,
  numero: 7,
  riferimento: null,
  tipo: 'fattura',
  stato: 'emessa',
  stato_pagamento: 'da_incassare',
  data_emissione: '2026-08-20',
  totale: '1500.00',
} as unknown as Invoice

const PROFORMA = {
  anno: null,
  numero: null,
  riferimento: 'PROV-2026-0007',
  tipo: 'proforma',
  stato: 'confermata',
  stato_pagamento: 'da_incassare',
  data_emissione: null,
  totale: '500.00',
} as unknown as Invoice

function accessor(id: string, row: Invoice): unknown {
  const column = buildInvoiceColumns().find((candidate) => candidate.id === id)
  if (column === undefined || !('accessorFn' in column) || column.accessorFn === undefined) {
    throw new Error(`nessuna colonna con id ${id}`)
  }
  return column.accessorFn(row, 0)
}

describe('buildInvoiceColumns', () => {
  it('shows the fiscal number for an invoice and the reference for a proforma', () => {
    expect(accessor('numero', ISSUED)).toBe('2026/7')
    expect(accessor('numero', PROFORMA)).toBe('PROV-2026-0007')
  })

  it('formats the total as grouped euros', () => {
    expect(String(accessor('totale', ISSUED))).toContain('1.500,00')
  })

  it('shows an em dash where a proforma has no issue date', () => {
    expect(accessor('data_emissione', PROFORMA)).toBe('—')
  })

  it('does not offer a payment column value for a proforma', () => {
    // A proforma is never collected: showing "Da incassare" next to something nobody
    // owes is the kind of small lie a fiscal list should not tell.
    expect(accessor('stato_pagamento', PROFORMA)).toBe('—')
    expect(accessor('stato_pagamento', ISSUED)).toBe('Da incassare')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/features/invoices/columns.test.ts`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement the badge**

`apps/web/src/features/invoices/InvoiceStateBadge.tsx`:

```tsx
import { Badge } from '@/components/ui/badge'
import {
  INVOICE_STATE_LABELS,
  PAYMENT_STATE_LABELS,
  type Invoice,
  type InvoiceStato,
  type StatoPagamento,
} from './queries'

const VARIANT: Record<InvoiceStato, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  bozza: 'outline',
  confermata: 'secondary',
  consumata: 'secondary',
  emessa: 'default',
  annullata: 'destructive',
}

/**
 * The state, and the collection state when there is one to show.
 *
 * `annullata` is the one destructive-coloured state in the product: a struck-through
 * page in a fiscal register is not a neutral fact, and the colour is what stops it
 * from reading like an ordinary status in a list of twenty rows.
 */
export function InvoiceStateBadge({
  invoice,
}: {
  invoice: Pick<Invoice, 'stato' | 'stato_pagamento' | 'tipo'>
}) {
  const stato = invoice.stato as InvoiceStato
  const pagamento = invoice.stato_pagamento as StatoPagamento
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge variant={VARIANT[stato]}>{INVOICE_STATE_LABELS[stato]}</Badge>
      {invoice.tipo === 'fattura' && stato === 'emessa' && (
        <Badge variant={pagamento === 'incassato' ? 'secondary' : 'outline'}>
          {PAYMENT_STATE_LABELS[pagamento]}
        </Badge>
      )}
    </span>
  )
}
```

- [ ] **Step 4: Implement the columns**

`apps/web/src/features/invoices/columns.tsx`:

```tsx
import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { formatDate, formatInvoiceNumber, formatMoney } from './format'
import {
  INVOICE_STATE_LABELS,
  INVOICE_TYPE_LABELS,
  PAYMENT_STATE_LABELS,
  type Invoice,
  type InvoiceStato,
  type InvoiceTipo,
  type StatoPagamento,
} from './queries'

const EMPTY = '—'

/**
 * No custom-field columns, unlike `buildCustomerColumns`/`buildDealColumns`.
 *
 * Deliberate: `invoice` is a real entity type with custom fields (they are on
 * `InvoiceRead`), but a fiscal list is read to find a document by number, date and
 * amount, and widening it with arbitrary columns is how it stops being scannable.
 * Custom fields are rendered on the detail page instead, which is where they were
 * defined to be read.
 */
export function buildInvoiceColumns(): ColumnDef<DataTableFeatures, Invoice>[] {
  return [
    { header: 'Numero', id: 'numero', accessorFn: (row) => formatInvoiceNumber(row) },
    {
      header: 'Tipo',
      id: 'tipo',
      accessorFn: (row) => INVOICE_TYPE_LABELS[row.tipo as InvoiceTipo] ?? row.tipo,
    },
    {
      header: 'Stato',
      id: 'stato',
      accessorFn: (row) => INVOICE_STATE_LABELS[row.stato as InvoiceStato] ?? row.stato,
    },
    { header: 'Data', id: 'data_emissione', accessorFn: (row) => formatDate(row.data_emissione) },
    { header: 'Totale', id: 'totale', accessorFn: (row) => formatMoney(row.totale) },
    {
      header: 'Incasso',
      id: 'stato_pagamento',
      accessorFn: (row) =>
        row.tipo === 'proforma' || row.stato !== 'emessa'
          ? EMPTY
          : (PAYMENT_STATE_LABELS[row.stato_pagamento as StatoPagamento] ?? row.stato_pagamento),
    },
  ]
}
```

- [ ] **Step 5: Implement the route**

`apps/web/src/routes/app/fatture/index.tsx`:

```tsx
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { InvoiceForm } from '@/features/invoices/InvoiceForm'
import { buildInvoiceColumns } from '@/features/invoices/columns'
import {
  INVOICE_STATE_LABELS,
  INVOICE_TYPE_LABELS,
  useCreateInvoice,
  useInvoices,
  type InvoiceStato,
  type InvoiceTipo,
} from '@/features/invoices/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'

const TIPI: InvoiceTipo[] = ['fattura', 'proforma']
const STATI: InvoiceStato[] = ['bozza', 'confermata', 'emessa', 'annullata', 'consumata']

function InvoicesPage() {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [tipo, setTipo] = useState<InvoiceTipo | undefined>(undefined)
  const [stato, setStato] = useState<InvoiceStato | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const invoices = useInvoices({ tipo, stato })
  const create = useCreateInvoice()

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Fatture</h1>
        {canWrite && (
          <Button
            onClick={() => {
              setProblem(null)
              setOpen(true)
            }}
          >
            <Plus className="mr-2 size-4" />
            Nuovo documento
          </Button>
        )}
      </header>

      <div className="mb-4 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={tipo === undefined && stato === undefined ? 'default' : 'secondary'}
          onClick={() => {
            setTipo(undefined)
            setStato(undefined)
          }}
        >
          Tutti
        </Button>
        {TIPI.map((candidate) => (
          <Button
            key={candidate}
            size="sm"
            variant={tipo === candidate ? 'default' : 'secondary'}
            onClick={() => setTipo(tipo === candidate ? undefined : candidate)}
          >
            {INVOICE_TYPE_LABELS[candidate]}
          </Button>
        ))}
        {STATI.map((candidate) => (
          <Button
            key={candidate}
            size="sm"
            variant={stato === candidate ? 'default' : 'secondary'}
            onClick={() => setStato(stato === candidate ? undefined : candidate)}
          >
            {INVOICE_STATE_LABELS[candidate]}
          </Button>
        ))}
      </div>

      <DataTable
        columns={buildInvoiceColumns()}
        data={invoices.data?.items ?? []}
        isLoading={invoices.isLoading}
        isError={invoices.isError}
        error={invoices.error}
        onRowClick={(row) =>
          void navigate({ to: '/app/fatture/$invoiceId', params: { invoiceId: row.id } })
        }
        emptyMessage="Nessun documento. Creane uno per iniziare."
      />

      <InvoiceForm
        title="Nuovo documento"
        open={open}
        onOpenChange={setOpen}
        problem={problem}
        busy={create.isPending}
        onSubmit={(values) => {
          setProblem(null)
          create.mutate(values, {
            onSuccess: (created) => {
              setOpen(false)
              toast.success(
                created.tipo === 'proforma' ? 'Proforma creata' : 'Bozza di fattura creata',
              )
              void navigate({
                to: '/app/fatture/$invoiceId',
                params: { invoiceId: created.id },
              })
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}

export const Route = createFileRoute('/app/fatture/')({ component: InvoicesPage })
```

- [ ] **Step 6: Add the nav entry**

In `apps/web/src/components/AppShell.tsx`, add `Receipt` to the `lucide-react` import and the entry to `NAV`, between Deal and Token:

```tsx
const NAV = [
  { to: '/app', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/app/clienti', label: 'Clienti', icon: Building2 },
  { to: '/app/persone', label: 'Persone', icon: Users },
  { to: '/app/deal', label: 'Deal', icon: Handshake },
  { to: '/app/fatture', label: 'Fatture', icon: Receipt },
  { to: '/app/token', label: 'Token', icon: KeyRound },
] as const
```

In `apps/web/src/components/AppShell.test.tsx`, update whichever assertion enumerates the nav labels so it includes `Fatture` — that test exists precisely so a nav change is a deliberate edit rather than a surprise.

- [ ] **Step 7: Add the eslint override**

In `apps/web/eslint.config.js`, add a block alongside the existing per-file overrides:

```js
  {
    files: ['src/routes/app/fatture/index.tsx', 'src/routes/app/fatture/$invoiceId.tsx'],
    rules: {
      'react-refresh/only-export-components': ['warn', { allowExportNames: ['Route'] }],
    },
  },
```

- [ ] **Step 8: Run the tests and the compiler**

Run: `cd apps/web && pnpm exec vitest run && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS and clean. `tsc` will fail until Task 18 creates `InvoiceForm`; write that file's skeleton now only if you are executing Tasks 17 and 18 out of order — otherwise run this step after Task 18 and keep the commit below.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/features/invoices/columns.tsx apps/web/src/features/invoices/InvoiceStateBadge.tsx apps/web/src/routes/app/fatture/index.tsx apps/web/src/components/AppShell.tsx apps/web/src/components/AppShell.test.tsx apps/web/eslint.config.js apps/web/src/features/invoices/columns.test.ts
git commit -m "feat(web): the Fatture list, with state and collection badges"
```

---

### Task 18: The line editor and the create form

**Files:**
- Create: `apps/web/src/features/invoices/InvoiceLinesEditor.tsx`
- Create: `apps/web/src/features/invoices/InvoiceForm.tsx`
- Modify: `apps/web/eslint.config.js`
- Test: `apps/web/src/features/invoices/InvoiceLinesEditor.test.tsx`

**Interfaces:**
- Consumes: `useReplaceLines`, `InvoiceLine`, `InvoiceLineInput`, `Invoice`; `formatMoney`, `sumLineTotals`; `useCreateInvoice`; `DynamicForm` is **not** used here (see below).
- Produces:
  - `InvoiceLinesEditor({ invoice, lines, readOnly }: { invoice: Invoice; lines: InvoiceLine[]; readOnly: boolean })`
  - `InvoiceForm({ open, onOpenChange, problem, busy, onSubmit, title }: InvoiceFormProps)`
  - `emptyLine(): DraftLine` and `type DraftLine` from `InvoiceLinesEditor.tsx`

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/invoices/InvoiceLinesEditor.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { InvoiceLinesEditor } from './InvoiceLinesEditor'
import type { Invoice, InvoiceLine } from './queries'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
}

const DRAFT = { id: 'inv-1', tipo: 'fattura', stato: 'bozza' } as unknown as Invoice

const LINE: InvoiceLine = {
  id: 'line-1',
  invoice_id: 'inv-1',
  numero_linea: 1,
  descrizione: 'Consulenza',
  quantita: '3.000000',
  unita_misura: 'ore',
  prezzo_unitario: '500.000000',
  sconto_percentuale: null,
  sconto_importo: null,
  prezzo_totale: '1500.00',
  aliquota_iva: '0.00',
  natura: 'N2.2',
  riferimento_normativo: 'art. 1',
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ id: 'inv-1', totale: '1500.00' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('InvoiceLinesEditor', () => {
  it('shows the stored line total, never a recomputed one', () => {
    // The authoritative total is the API's. The running figure below the table is
    // explicitly labelled as a preview so nobody reads it as the document's total.
    wrap(<InvoiceLinesEditor invoice={DRAFT} lines={[LINE]} readOnly={false} />)
    expect(screen.getByDisplayValue('Consulenza')).toBeInTheDocument()
    expect(screen.getByText(/1\.500,00/)).toBeInTheDocument()
  })

  it('adds and removes rows', async () => {
    const user = userEvent.setup()
    wrap(<InvoiceLinesEditor invoice={DRAFT} lines={[LINE]} readOnly={false} />)
    await user.click(screen.getByRole('button', { name: /aggiungi riga/i }))
    expect(screen.getAllByLabelText(/descrizione/i)).toHaveLength(2)
    await user.click(screen.getAllByRole('button', { name: /rimuovi riga/i })[1] as HTMLElement)
    expect(screen.getAllByLabelText(/descrizione/i)).toHaveLength(1)
  })

  it('treats a zero discount as a value, not a blank', async () => {
    // `0` and `false` are values, never blanks -- mirroring `is_blank`. A zero
    // percentage discount must survive the round trip as `0`, not vanish.
    const user = userEvent.setup()
    wrap(<InvoiceLinesEditor invoice={DRAFT} lines={[LINE]} readOnly={false} />)
    const discount = screen.getByLabelText(/sconto %/i)
    await user.clear(discount)
    await user.type(discount, '0')
    await user.click(screen.getByRole('button', { name: /salva righe/i }))
    const body = JSON.parse(
      String((fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]?.[1] && (((fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]?.[1]) as RequestInit).body),
    ) as { righe: { sconto_percentuale: string | null }[] }
    expect(body.righe[0]?.sconto_percentuale).toBe('0')
  })

  it('sends an emptied optional field as null so the bulk replace clears it', async () => {
    const user = userEvent.setup()
    wrap(<InvoiceLinesEditor invoice={DRAFT} lines={[LINE]} readOnly={false} />)
    await user.clear(screen.getByLabelText(/unità/i))
    await user.click(screen.getByRole('button', { name: /salva righe/i }))
    const body = JSON.parse(
      String((((fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]?.[1]) as RequestInit).body),
    ) as { righe: { unita_misura: string | null }[] }
    expect(body.righe[0]?.unita_misura).toBeNull()
  })

  it('is read-only for an issued invoice, with no save button at all', () => {
    const issued = { ...DRAFT, stato: 'emessa' } as unknown as Invoice
    wrap(<InvoiceLinesEditor invoice={issued} lines={[LINE]} readOnly />)
    expect(screen.queryByRole('button', { name: /salva righe/i })).not.toBeInTheDocument()
    expect(screen.getByText('Consulenza')).toBeInTheDocument()
  })

  it('does not offer a VAT rate field, because the regime decides it', () => {
    // Accepting a rate here would put the table constraint
    // `(aliquota_iva = 0) = (natura IS NOT NULL)` within reach of a form.
    wrap(<InvoiceLinesEditor invoice={DRAFT} lines={[LINE]} readOnly={false} />)
    expect(screen.queryByLabelText(/aliquota/i)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/features/invoices/InvoiceLinesEditor.test.tsx`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement the editor**

`apps/web/src/features/invoices/InvoiceLinesEditor.tsx`:

```tsx
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { formatMoney, formatQuantity, formatRate, sumLineTotals } from './format'
import { useReplaceLines, type Invoice, type InvoiceLine, type InvoiceLineInput } from './queries'

/** A row being edited. Every field is a string, because that is what an `<input>` has
 * and what a `Numeric` column arrives as -- parsing to a JS number in between is the
 * one thing that must not happen to money. */
export interface DraftLine {
  descrizione: string
  quantita: string
  unita_misura: string
  prezzo_unitario: string
  sconto_percentuale: string
  sconto_importo: string
}

export function emptyLine(): DraftLine {
  return {
    descrizione: '',
    quantita: '1',
    unita_misura: '',
    prezzo_unitario: '',
    sconto_percentuale: '',
    sconto_importo: '',
  }
}

function toDraft(line: InvoiceLine): DraftLine {
  return {
    descrizione: line.descrizione,
    quantita: line.quantita,
    unita_misura: line.unita_misura ?? '',
    prezzo_unitario: line.prezzo_unitario,
    sconto_percentuale: line.sconto_percentuale ?? '',
    sconto_importo: line.sconto_importo ?? '',
  }
}

/**
 * An empty string means "no value" and is sent as `null`; anything else is sent as
 * typed.
 *
 * `'0'` therefore survives as `'0'`, which is the whole point: `0` and `false` are
 * values, never blanks. The bulk replacement is also what makes clearing possible at
 * all -- with `exclude_none=True` there is no partial-update spelling that empties
 * `sconto_importo` (A14).
 */
function optional(value: string): string | null {
  return value.trim() === '' ? null : value
}

function toPayload(line: DraftLine): InvoiceLineInput {
  return {
    descrizione: line.descrizione,
    quantita: line.quantita.trim() === '' ? '1' : line.quantita,
    unita_misura: optional(line.unita_misura),
    prezzo_unitario: line.prezzo_unitario.trim() === '' ? '0' : line.prezzo_unitario,
    sconto_percentuale: optional(line.sconto_percentuale),
    sconto_importo: optional(line.sconto_importo),
    // `aliquota_iva` is deliberately never sent: the `RegimeStrategy` on the server
    // decides the rate, the Natura and the normative reference together, because the
    // SdI validates the three as a set.
  } as InvoiceLineInput
}

export function InvoiceLinesEditor({
  invoice,
  lines,
  readOnly,
}: {
  invoice: Invoice
  lines: InvoiceLine[]
  readOnly: boolean
}) {
  const [draft, setDraft] = useState<DraftLine[]>(lines.map(toDraft))
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const replace = useReplaceLines(invoice.id)

  function update(index: number, field: keyof DraftLine, value: string) {
    setDraft((previous) =>
      previous.map((line, position) =>
        position === index ? { ...line, [field]: value } : line,
      ),
    )
  }

  if (readOnly) {
    return (
      <div className="rounded-md border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">Descrizione</th>
              <th className="px-3 py-2 text-right">Qtà</th>
              <th className="px-3 py-2 text-right">Prezzo</th>
              <th className="px-3 py-2 text-center">IVA</th>
              <th className="px-3 py-2 text-right">Totale</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.id} className="border-b last:border-0">
                <td className="px-3 py-2 text-muted-foreground">{line.numero_linea}</td>
                <td className="px-3 py-2">{line.descrizione}</td>
                <td className="px-3 py-2 text-right">
                  {formatQuantity(line.quantita)} {line.unita_misura ?? ''}
                </td>
                <td className="px-3 py-2 text-right">{formatMoney(line.prezzo_unitario)}</td>
                <td className="px-3 py-2 text-center">{formatRate(line.aliquota_iva)}</td>
                <td className="px-3 py-2 text-right">{formatMoney(line.prezzo_totale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {problem && <QueryErrorBanner error={problem} />}
      <div className="space-y-2">
        {draft.map((line, index) => (
          <div key={index} className="grid gap-2 rounded-md border bg-card p-3 sm:grid-cols-12">
            <label className="sm:col-span-5 text-xs text-muted-foreground">
              Descrizione
              <Input
                value={line.descrizione}
                onChange={(event) => update(index, 'descrizione', event.target.value)}
              />
            </label>
            <label className="sm:col-span-2 text-xs text-muted-foreground">
              Quantità
              <Input
                inputMode="decimal"
                value={line.quantita}
                onChange={(event) => update(index, 'quantita', event.target.value)}
              />
            </label>
            <label className="sm:col-span-1 text-xs text-muted-foreground">
              Unità
              <Input
                value={line.unita_misura}
                onChange={(event) => update(index, 'unita_misura', event.target.value)}
              />
            </label>
            <label className="sm:col-span-2 text-xs text-muted-foreground">
              Prezzo unitario
              <Input
                inputMode="decimal"
                value={line.prezzo_unitario}
                onChange={(event) => update(index, 'prezzo_unitario', event.target.value)}
              />
            </label>
            <label className="sm:col-span-1 text-xs text-muted-foreground">
              Sconto %
              <Input
                inputMode="decimal"
                value={line.sconto_percentuale}
                onChange={(event) => update(index, 'sconto_percentuale', event.target.value)}
              />
            </label>
            <div className="flex items-end sm:col-span-1">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Rimuovi riga"
                onClick={() =>
                  setDraft((previous) => previous.filter((_, position) => position !== index))
                }
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setDraft((previous) => [...previous, emptyLine()])}
        >
          <Plus className="mr-2 size-4" />
          Aggiungi riga
        </Button>
        <p className="text-sm text-muted-foreground">
          Anteprima totale righe: {formatMoney(sumLineTotals(lines))}
        </p>
        <Button
          disabled={replace.isPending}
          onClick={() => {
            setProblem(null)
            replace.mutate(draft.map(toPayload), {
              onSuccess: () => toast.success('Righe salvate'),
              onError: (error) => setProblem(toProblem(error)),
            })
          }}
        >
          {replace.isPending ? 'Salvataggio…' : 'Salva righe'}
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Implement the create form**

`apps/web/src/features/invoices/InvoiceForm.tsx`:

```tsx
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { DynamicForm } from '@/components/DynamicForm'
import type { ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'
import { emptyLine, type DraftLine } from './InvoiceLinesEditor'

const NATIVE_FIELDS: FieldDefinition[] = [
  { key: 'customer_id', label: 'Cliente (id)', type: 'text', required: true, options: [] },
  { key: 'deal_id', label: 'Deal (id)', type: 'text', required: false, options: [] },
  {
    key: 'tipo',
    label: 'Tipo',
    type: 'select',
    required: true,
    options: ['fattura', 'proforma'],
  },
  { key: 'causale', label: 'Causale', type: 'text', required: false, options: [] },
  { key: 'note_interne', label: 'Note interne', type: 'textarea', required: false, options: [] },
]

const NATIVE_FIELD_KEYS = NATIVE_FIELDS.map((field) => field.key)

export interface InvoiceFormProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  problem?: ProblemDetail | null
  busy?: boolean
  onSubmit: (values: Record<string, unknown>) => void
  title: string
  /** Pre-selected customer, when the form is opened from a customer's own tab. */
  customerId?: string
}

const DEFAULTS: Record<string, unknown> = { tipo: 'fattura' }

/** Mirrors `is_blank` in `packages/core/.../fields/validator.py`, and the shipped
 * `isBlank` in `CustomerForm.tsx`: `0` and `false` are values, never blanks. */
function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

export function InvoiceForm({
  open,
  onOpenChange,
  problem,
  busy,
  onSubmit,
  title,
  customerId,
}: InvoiceFormProps) {
  const seed = customerId === undefined ? DEFAULTS : { ...DEFAULTS, customer_id: customerId }
  const [values, setValues] = useState<Record<string, unknown>>(seed)
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()])
  const [wasOpen, setWasOpen] = useState(open)
  // Render-time reset rather than a `useEffect`, the same shape `CustomerForm` uses:
  // an effect would let one frame render with the previous document's values.
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setValues(seed)
      setLines([emptyLine()])
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <DynamicForm
          fields={NATIVE_FIELDS}
          values={values}
          onChange={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
          problem={problem}
          mode="create"
        />

        <div className="space-y-2">
          <p className="text-sm font-medium">Prima riga</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="text-xs text-muted-foreground">
              Descrizione
              <input
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
                value={lines[0]?.descrizione ?? ''}
                onChange={(event) =>
                  setLines(([first = emptyLine()]) => [
                    { ...first, descrizione: event.target.value },
                  ])
                }
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Quantità
              <input
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
                inputMode="decimal"
                value={lines[0]?.quantita ?? '1'}
                onChange={(event) =>
                  setLines(([first = emptyLine()]) => [{ ...first, quantita: event.target.value }])
                }
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Prezzo unitario
              <input
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
                inputMode="decimal"
                value={lines[0]?.prezzo_unitario ?? ''}
                onChange={(event) =>
                  setLines(([first = emptyLine()]) => [
                    { ...first, prezzo_unitario: event.target.value },
                  ])
                }
              />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            Le altre righe si aggiungono nella scheda del documento.
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annulla
          </Button>
          <Button
            disabled={busy}
            onClick={() => {
              const native: Record<string, unknown> = {}
              for (const key of NATIVE_FIELD_KEYS) {
                const value = values[key]
                if (!isBlank(value)) native[key] = value
              }
              const first = lines[0]
              const righe =
                first === undefined || isBlank(first.descrizione)
                  ? []
                  : [
                      {
                        descrizione: first.descrizione,
                        quantita: isBlank(first.quantita) ? '1' : first.quantita,
                        prezzo_unitario: isBlank(first.prezzo_unitario)
                          ? '0'
                          : first.prezzo_unitario,
                      },
                    ]
              onSubmit({ ...native, righe })
            }}
          >
            {busy ? 'Salvataggio…' : 'Crea'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 5: Add the eslint override**

In `apps/web/eslint.config.js`, add:

```js
  {
    files: ['src/features/invoices/InvoiceLinesEditor.tsx'],
    rules: {
      'react-refresh/only-export-components': ['warn', { allowExportNames: ['emptyLine'] }],
    },
  },
```

- [ ] **Step 6: Run the tests and the compiler**

Run: `cd apps/web && pnpm exec vitest run src/features/invoices && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS and clean.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/invoices/InvoiceLinesEditor.tsx apps/web/src/features/invoices/InvoiceForm.tsx apps/web/src/features/invoices/InvoiceLinesEditor.test.tsx apps/web/eslint.config.js
git commit -m "feat(web): a bulk line editor and the create dialog"
```

---
### Task 19: The invoice detail page and its actions

**Files:**
- Create: `apps/web/src/features/invoices/InvoiceActions.tsx`
- Create: `apps/web/src/features/invoices/InvoicesTab.tsx`
- Create: `apps/web/src/routes/app/fatture/$invoiceId.tsx`
- Create: `apps/web/src/routes/app/fatture/$invoiceId.test.tsx`
- Modify: `apps/web/src/components/EntityDetailLayout.tsx`
- Modify: `apps/web/src/routes/app/clienti/$customerId.tsx`
- Modify: `apps/web/src/routes/app/deal/$dealId.tsx`
- Test: `apps/web/src/features/invoices/InvoiceActions.test.tsx`

**Interfaces:**
- Consumes: every hook from Task 16; `InvoiceLinesEditor`, `InvoiceForm` (Task 18); `InvoiceStateBadge` (Task 17); `EntityDetailLayout`, `QueryErrorBanner`, `DataTable`.
- Produces:
  - `InvoiceActions({ invoice }: { invoice: Invoice })`
  - `InvoicesTab({ owner }: { owner: { customerId: string } | { dealId: string } })`
  - route `/app/fatture/$invoiceId` exporting both `Route` and `InvoiceDetail`
  - `EntityDetailLayout` gains an optional `invoices?: ReactNode` prop and a "Fatture" tab

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/invoices/InvoiceActions.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { InvoiceActions } from './InvoiceActions'
import type { Invoice } from './queries'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
}

const BASE = {
  id: 'inv-1',
  tipo: 'fattura',
  stato: 'bozza',
  stato_pagamento: 'da_incassare',
  anno: null,
  numero: null,
  riferimento: null,
  trasmessa_esternamente_il: null,
  xml_document_id: null,
  pdf_document_id: null,
  data_incasso: null,
  motivo_annullamento: null,
} as unknown as Invoice

function invoice(overrides: Partial<Invoice>): Invoice {
  return { ...BASE, ...overrides } as Invoice
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ ...BASE, stato: 'emessa', anno: 2026, numero: 1 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('InvoiceActions', () => {
  it('offers Emetti on a draft and nothing about annulment', () => {
    wrap(<InvoiceActions invoice={invoice({ stato: 'bozza' })} />)
    expect(screen.getByRole('button', { name: /emetti/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /annulla fattura/i })).not.toBeInTheDocument()
  })

  it('asks for confirmation before consuming a number', async () => {
    // Emission is the only irreversible creation in the product. One click is the
    // price of keeping it away from the agentic surface; a confirmation is the price
    // of it being irreversible.
    const user = userEvent.setup()
    wrap(<InvoiceActions invoice={invoice({ stato: 'bozza' })} />)
    await user.click(screen.getByRole('button', { name: /emetti/i }))
    expect(screen.getByText(/consuma un numero del registro/i)).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('offers annulment on an issued invoice and requires a reason', async () => {
    const user = userEvent.setup()
    wrap(<InvoiceActions invoice={invoice({ stato: 'emessa', anno: 2026, numero: 1 })} />)
    await user.click(screen.getByRole('button', { name: /annulla fattura/i }))
    const confirm = screen.getByRole('button', { name: /conferma annullamento/i })
    expect(confirm).toBeDisabled()
    await user.type(screen.getByLabelText(/motivo/i), 'importo errato')
    expect(confirm).toBeEnabled()
  })

  it('replaces annulment with an explanation once the file has been handed over', () => {
    // Spec 4.1: the application says where the correction has to happen, instead of
    // offering a button that pretends to solve it.
    wrap(
      <InvoiceActions
        invoice={invoice({
          stato: 'emessa',
          anno: 2026,
          numero: 1,
          trasmessa_esternamente_il: '2026-08-21',
        })}
      />,
    )
    expect(screen.queryByRole('button', { name: /annulla fattura/i })).not.toBeInTheDocument()
    expect(screen.getByText(/nota di credito/i)).toBeInTheDocument()
  })

  it('offers Converti in fattura on a confirmed proforma', () => {
    wrap(<InvoiceActions invoice={invoice({ tipo: 'proforma', stato: 'confermata' })} />)
    expect(screen.getByRole('button', { name: /converti in fattura/i })).toBeInTheDocument()
  })

  it('offers no XML download for a proforma', () => {
    wrap(<InvoiceActions invoice={invoice({ tipo: 'proforma', stato: 'confermata' })} />)
    expect(screen.queryByRole('button', { name: /xml/i })).not.toBeInTheDocument()
  })

  it('offers the XML download only once one exists', () => {
    wrap(<InvoiceActions invoice={invoice({ stato: 'emessa', anno: 2026, numero: 1 })} />)
    expect(screen.queryByRole('button', { name: /scarica xml/i })).not.toBeInTheDocument()
    wrap(
      <InvoiceActions
        invoice={invoice({ stato: 'emessa', anno: 2026, numero: 1, xml_document_id: 'doc-1' })}
      />,
    )
    expect(screen.getByRole('button', { name: /scarica xml/i })).toBeInTheDocument()
  })

  it('offers the payment toggle only on an issued invoice', () => {
    wrap(<InvoiceActions invoice={invoice({ stato: 'bozza' })} />)
    expect(screen.queryByRole('button', { name: /incassata/i })).not.toBeInTheDocument()
    wrap(<InvoiceActions invoice={invoice({ stato: 'emessa', anno: 2026, numero: 1 })} />)
    expect(screen.getByRole('button', { name: /incassata/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/features/invoices/InvoiceActions.test.tsx`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement the actions**

`apps/web/src/features/invoices/InvoiceActions.tsx`:

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useIsAdmin } from '@/lib/auth'
import { formatDate, formatInvoiceNumber } from './format'
import {
  downloadInvoiceArtifact,
  useAnnulInvoice,
  useConfirmProforma,
  useIssueInvoice,
  useMarkTransmitted,
  useProduceArtifacts,
  useSetPaymentState,
  type Invoice,
} from './queries'

const BANNER = 'rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive'

export function InvoiceActions({ invoice }: { invoice: Invoice }) {
  const isAdmin = useIsAdmin()
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [confirmingIssue, setConfirmingIssue] = useState(false)
  const [annulling, setAnnulling] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [transmittedOn, setTransmittedOn] = useState('')

  const issue = useIssueInvoice(invoice.id)
  const annul = useAnnulInvoice(invoice.id)
  const transmit = useMarkTransmitted(invoice.id)
  const confirm = useConfirmProforma(invoice.id)
  const payment = useSetPaymentState(invoice.id)
  const artifacts = useProduceArtifacts(invoice.id)

  const isProforma = invoice.tipo === 'proforma'
  const issued = invoice.stato === 'emessa'
  const transmitted = invoice.trasmessa_esternamente_il !== null

  function fail(error: unknown) {
    setProblem(toProblem(error))
  }

  return (
    <div className="space-y-3">
      {problem && (
        <p role="alert" className={BANNER}>
          {problem.detail}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {invoice.pdf_document_id !== null && (
          <Button
            variant="secondary"
            onClick={() => void downloadInvoiceArtifact(invoice.id, 'pdf').catch(fail)}
          >
            Scarica PDF
          </Button>
        )}
        {!isProforma && invoice.xml_document_id !== null && (
          <Button
            variant="secondary"
            onClick={() => void downloadInvoiceArtifact(invoice.id, 'xml').catch(fail)}
          >
            Scarica XML
          </Button>
        )}
        {invoice.stato !== 'bozza' && (
          <Button
            variant="ghost"
            disabled={artifacts.isPending}
            onClick={() => {
              setProblem(null)
              artifacts.mutate(undefined, {
                onSuccess: () => toast.success('Allegati rigenerati'),
                onError: fail,
              })
            }}
          >
            {artifacts.isPending ? 'Rigenerazione…' : 'Rigenera PDF e XML'}
          </Button>
        )}

        {isProforma && invoice.stato === 'bozza' && (
          <Button
            disabled={confirm.isPending}
            onClick={() => {
              setProblem(null)
              confirm.mutate(undefined, {
                onSuccess: () => toast.success('Proforma confermata'),
                onError: fail,
              })
            }}
          >
            Conferma proforma
          </Button>
        )}

        {isAdmin && !confirmingIssue && (invoice.stato === 'bozza' || (isProforma && invoice.stato === 'confermata')) && (
          <Button onClick={() => setConfirmingIssue(true)}>
            {isProforma ? 'Converti in fattura' : 'Emetti'}
          </Button>
        )}

        {isAdmin && issued && !transmitted && !annulling && (
          <Button variant="destructive" onClick={() => setAnnulling(true)}>
            Annulla fattura
          </Button>
        )}

        {issued && (
          <Button
            variant={invoice.stato_pagamento === 'incassato' ? 'secondary' : 'default'}
            disabled={payment.isPending}
            onClick={() => {
              setProblem(null)
              const collecting = invoice.stato_pagamento !== 'incassato'
              payment.mutate(
                collecting
                  ? {
                      stato_pagamento: 'incassato',
                      data_incasso: new Date().toISOString().slice(0, 10),
                    }
                  : { stato_pagamento: 'da_incassare', data_incasso: null },
                {
                  onSuccess: () =>
                    toast.success(collecting ? 'Segnata incassata' : 'Segnata da incassare'),
                  onError: fail,
                },
              )
            }}
          >
            {invoice.stato_pagamento === 'incassato' ? 'Segna da incassare' : 'Segna incassata'}
          </Button>
        )}
      </div>

      {confirmingIssue && (
        <div className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-3">
          <p className="text-sm">
            L&apos;emissione <strong>consuma un numero del registro</strong> e non si annulla: si
            corregge solo con un annullamento e una nuova fattura. Vuoi procedere?
          </p>
          <div className="flex gap-2">
            <Button
              disabled={issue.isPending}
              onClick={() => {
                setProblem(null)
                issue.mutate(
                  {},
                  {
                    onSuccess: (result) => {
                      setConfirmingIssue(false)
                      toast.success(`Fattura ${formatInvoiceNumber(result)} emessa`)
                    },
                    onError: fail,
                  },
                )
              }}
            >
              {issue.isPending ? 'Emissione…' : 'Conferma emissione'}
            </Button>
            <Button variant="ghost" onClick={() => setConfirmingIssue(false)}>
              Annulla
            </Button>
          </div>
        </div>
      )}

      {annulling && (
        <div className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
          <p className="text-sm">
            Il numero {formatInvoiceNumber(invoice)} resta consumato: la riga resta leggibile, come
            una pagina barrata su un registro cartaceo.
          </p>
          <label className="block text-xs text-muted-foreground">
            Motivo
            <Input value={motivo} onChange={(event) => setMotivo(event.target.value)} />
          </label>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              disabled={motivo.trim() === '' || annul.isPending}
              onClick={() => {
                setProblem(null)
                annul.mutate(motivo, {
                  onSuccess: () => {
                    setAnnulling(false)
                    toast.success('Fattura annullata')
                  },
                  onError: fail,
                })
              }}
            >
              Conferma annullamento
            </Button>
            <Button variant="ghost" onClick={() => setAnnulling(false)}>
              Annulla
            </Button>
          </div>
        </div>
      )}

      {issued && transmitted && (
        <p className="rounded-lg border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Consegnata all&apos;intermediario il {formatDate(invoice.trasmessa_esternamente_il)}. Da
          questo punto una correzione richiede una <strong>nota di credito</strong>, che PigroCRM non
          emette: va fatta dal tuo intermediario o dal portale dell&apos;Agenzia delle Entrate.
        </p>
      )}

      {isAdmin && issued && !transmitted && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-muted-foreground">
            Consegnata all&apos;intermediario il
            <Input
              type="date"
              value={transmittedOn}
              onChange={(event) => setTransmittedOn(event.target.value)}
            />
          </label>
          <Button
            variant="secondary"
            disabled={transmittedOn === '' || transmit.isPending}
            onClick={() => {
              setProblem(null)
              transmit.mutate(transmittedOn, {
                onSuccess: () => toast.success('Consegna registrata'),
                onError: fail,
              })
            }}
          >
            Registra consegna
          </Button>
          <p className="text-xs text-muted-foreground">
            Si registra una volta sola: da quel momento l&apos;annullamento non è più possibile.
          </p>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Implement the detail route**

`apps/web/src/routes/app/fatture/$invoiceId.tsx`:

```tsx
import { createFileRoute, useParams } from '@tanstack/react-router'
import { EntityDetailLayout } from '@/components/EntityDetailLayout'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { InvoiceActions } from '@/features/invoices/InvoiceActions'
import { InvoiceLinesEditor } from '@/features/invoices/InvoiceLinesEditor'
import { InvoiceStateBadge } from '@/features/invoices/InvoiceStateBadge'
import { formatDate, formatInvoiceNumber, formatMoney } from '@/features/invoices/format'
import {
  INVOICE_TYPE_LABELS,
  useInvoice,
  useInvoiceLines,
  type InvoiceTipo,
} from '@/features/invoices/queries'
import { toProblem } from '@/lib/api'

export function InvoiceDetail() {
  const { invoiceId } = useParams({ from: '/app/fatture/$invoiceId' })
  const invoice = useInvoice(invoiceId)
  const lines = useInvoiceLines(invoiceId)

  if (invoice.isError) {
    if (toProblem(invoice.error).status === 404) {
      return <p className="p-8">Documento non trovato.</p>
    }
    return (
      <div className="p-8">
        <QueryErrorBanner error={invoice.error} />
      </div>
    )
  }
  if (!invoice.data) return <div className="p-8 text-muted-foreground">Caricamento…</div>

  const record = invoice.data
  const editable =
    record.tipo === 'proforma'
      ? record.stato === 'bozza' || record.stato === 'confermata'
      : record.stato === 'bozza'

  return (
    <EntityDetailLayout
      title={`${INVOICE_TYPE_LABELS[record.tipo as InvoiceTipo] ?? record.tipo} ${formatInvoiceNumber(record)}`}
      subtitle={record.causale ?? undefined}
      entityType="invoice"
      entityId={record.id}
      actions={<InvoiceStateBadge invoice={record} />}
      overview={
        <div className="space-y-6">
          <InvoiceActions invoice={record} />

          <dl className="grid gap-4 sm:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Data</dt>
              <dd className="text-sm">{formatDate(record.data_emissione)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Scadenza</dt>
              <dd className="text-sm">{formatDate(record.data_scadenza)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Imponibile</dt>
              <dd className="text-sm">{formatMoney(record.imponibile)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Imposta</dt>
              <dd className="text-sm">{formatMoney(record.imposta)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Bollo</dt>
              <dd className="text-sm">{formatMoney(record.bollo)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Totale</dt>
              <dd className="text-sm font-semibold">{formatMoney(record.totale)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Incasso</dt>
              <dd className="text-sm">{formatDate(record.data_incasso)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Note interne</dt>
              <dd className="text-sm">{record.note_interne ?? '—'}</dd>
            </div>
          </dl>

          {record.motivo_annullamento !== null && (
            <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm">
              Annullata il {formatDate(record.annullata_il)}: {record.motivo_annullamento}
            </p>
          )}

          <section className="space-y-2">
            <h2 className="text-sm font-medium">Righe</h2>
            {lines.isError && <QueryErrorBanner error={lines.error} />}
            {lines.data && (
              <InvoiceLinesEditor invoice={record} lines={lines.data} readOnly={!editable} />
            )}
          </section>
        </div>
      }
    />
  )
}

export const Route = createFileRoute('/app/fatture/$invoiceId')({ component: InvoiceDetail })
```

`apps/web/src/routes/app/fatture/$invoiceId.test.tsx` follows the shape of the shipped `app/clienti/$customerId.test.tsx` exactly: render `InvoiceDetail` with a stubbed `fetch`, and assert that a 404 renders `Documento non trovato.` while a 503 renders the `role="alert"` banner. That split is the one thing a detail route must get right — a failed request must never look like an absent record.

- [ ] **Step 5: Add the Fatture tab**

In `apps/web/src/components/EntityDetailLayout.tsx`, add the prop and the tab pair:

```ts
  /** The Fatture tab's contents. Optional because a Person has no invoices. */
  invoices?: ReactNode
```

```tsx
    {documents && <TabsTrigger value="documenti">Documenti</TabsTrigger>}
    {invoices && <TabsTrigger value="fatture">Fatture</TabsTrigger>}
```

```tsx
    {invoices && (
      <TabsContent value="fatture" className="mt-6">
        {invoices}
      </TabsContent>
    )}
```

Create `apps/web/src/features/invoices/InvoicesTab.tsx`:

```tsx
import { useNavigate } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { InvoiceForm } from './InvoiceForm'
import { buildInvoiceColumns } from './columns'
import { useCreateInvoice, useInvoices } from './queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'

export type InvoiceOwner = { customerId: string } | { dealId: string }

export function InvoicesTab({ owner }: { owner: InvoiceOwner }) {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const filters =
    'customerId' in owner ? { customer_id: owner.customerId } : { deal_id: owner.dealId }
  const invoices = useInvoices(filters)
  const create = useCreateInvoice()

  return (
    <div className="space-y-4">
      {canWrite && (
        <Button
          size="sm"
          onClick={() => {
            setProblem(null)
            setOpen(true)
          }}
        >
          <Plus className="mr-2 size-4" />
          Nuovo documento
        </Button>
      )}

      <DataTable
        columns={buildInvoiceColumns()}
        data={invoices.data?.items ?? []}
        isLoading={invoices.isLoading}
        isError={invoices.isError}
        error={invoices.error}
        onRowClick={(row) =>
          void navigate({ to: '/app/fatture/$invoiceId', params: { invoiceId: row.id } })
        }
        emptyMessage="Nessuna fattura."
      />

      <InvoiceForm
        title="Nuovo documento"
        open={open}
        onOpenChange={setOpen}
        problem={problem}
        busy={create.isPending}
        customerId={'customerId' in owner ? owner.customerId : undefined}
        onSubmit={(values) => {
          setProblem(null)
          const body = 'dealId' in owner ? { ...values, deal_id: owner.dealId } : values
          create.mutate(body, {
            onSuccess: (created) => {
              setOpen(false)
              toast.success('Documento creato')
              void navigate({
                to: '/app/fatture/$invoiceId',
                params: { invoiceId: created.id },
              })
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}
```

Then in `apps/web/src/routes/app/clienti/$customerId.tsx` and `apps/web/src/routes/app/deal/$dealId.tsx`, add the prop to the existing `<EntityDetailLayout …>` call:

```tsx
      invoices={<InvoicesTab owner={{ customerId: record.id }} />}
```

and, in the deal route:

```tsx
      invoices={<InvoicesTab owner={{ dealId: record.id }} />}
```

A Person deliberately gets no Fatture tab, exactly as it gets no Documenti tab: an invoice belongs to a customer.

- [ ] **Step 6: Add the eslint override**

`apps/web/eslint.config.js` gains:

```js
  {
    files: ['src/features/invoices/InvoicesTab.tsx'],
    rules: {
      'react-refresh/only-export-components': ['warn', { allowExportNames: ['InvoiceOwner'] }],
    },
  },
```

- [ ] **Step 7: Run the tests and the compiler**

Run: `cd apps/web && pnpm exec vitest run && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS and clean.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/invoices/InvoiceActions.tsx apps/web/src/features/invoices/InvoicesTab.tsx apps/web/src/routes/app/fatture/ apps/web/src/components/EntityDetailLayout.tsx apps/web/src/routes/app/clienti/\$customerId.tsx apps/web/src/routes/app/deal/\$dealId.tsx apps/web/eslint.config.js apps/web/src/features/invoices/InvoiceActions.test.tsx
git commit -m "feat(web): the invoice detail page, issue with confirmation, annul with a reason"
```

---

### Task 20: The fiscal profile settings panel

**Files:**
- Create: `apps/web/src/features/settings/FiscalProfilePanel.tsx`
- Create: `apps/web/src/routes/app/impostazioni/fiscale.tsx`
- Modify: `apps/web/src/routes/app/impostazioni.tsx` (the settings nav)
- Modify: `apps/web/eslint.config.js`
- Test: `apps/web/src/features/settings/FiscalProfilePanel.test.tsx`

**Interfaces:**
- Consumes: `useFiscalProfile`, `useSaveFiscalProfile` (Task 16); `DynamicForm`; `QueryErrorBanner`.
- Produces:
  - `FiscalProfilePanel()`
  - `fiscalProfileToFormValues(profile: FiscalProfile): Record<string, unknown>`
  - route `/app/impostazioni/fiscale`

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/settings/FiscalProfilePanel.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FiscalProfilePanel } from './FiscalProfilePanel'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
}

const PROFILE = {
  id: 'fp-1',
  codice_regime: 'RF19',
  aliquota_iva_default: '0.00',
  natura_default: 'N2.2',
  riferimento_normativo: 'Operazione non soggetta a IVA…',
  applica_bollo: true,
  soglia_bollo: '77.47',
  importo_bollo: '2.00',
  condizioni_pagamento: 'TP02',
  modalita_pagamento: 'MP05',
  giorni_scadenza: 30,
  iban: null,
  created_at: '2026-08-20T10:00:00Z',
  updated_at: '2026-08-20T10:00:00Z',
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(PROFILE), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FiscalProfilePanel', () => {
  it('shows the stored values, including a zero rate as zero and not as blank', async () => {
    wrap(<FiscalProfilePanel />)
    await waitFor(() => expect(screen.getByDisplayValue('RF19')).toBeInTheDocument())
    // `0` is a value, never a blank: a forfettario rate of 0.00 must render as 0.00.
    expect(screen.getByDisplayValue('0.00')).toBeInTheDocument()
    expect(screen.getByDisplayValue('77.47')).toBeInTheDocument()
  })

  it('sends the whole profile on save, because it is one row with required fields', async () => {
    const user = userEvent.setup()
    wrap(<FiscalProfilePanel />)
    await waitFor(() => expect(screen.getByDisplayValue('RF19')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /salva/i }))
    const request = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.at(-1)
    const body = JSON.parse(String((request?.[1] as RequestInit).body)) as Record<string, unknown>
    expect(body.codice_regime).toBe('RF19')
    expect(body.applica_bollo).toBe(true)
    expect(body.giorni_scadenza).toBe(30)
  })

  it('says the profile is missing rather than showing an empty form as if it were saved', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('null', { status: 404, headers: { 'content-type': 'application/json' } })),
    )
    wrap(<FiscalProfilePanel />)
    await waitFor(() =>
      expect(screen.getByText(/non è ancora configurato/i)).toBeInTheDocument(),
    )
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/features/settings/FiscalProfilePanel.test.tsx`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement the panel**

`apps/web/src/features/settings/FiscalProfilePanel.tsx`:

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { DynamicForm } from '@/components/DynamicForm'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { useFiscalProfile, useSaveFiscalProfile, type FiscalProfile } from '@/features/invoices/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'

const FIELDS: FieldDefinition[] = [
  {
    key: 'codice_regime',
    label: 'Regime fiscale',
    type: 'select',
    required: true,
    // Only the two regimes that have a strategy. A code such as RF07 is real FPR12 and
    // still has no implementation, and offering it would let someone configure a
    // profile that refuses at emission time instead of here.
    options: ['RF19', 'RF01'],
  },
  { key: 'aliquota_iva_default', label: 'Aliquota IVA di default', type: 'text', required: true, options: [] },
  { key: 'natura_default', label: 'Natura (per aliquota zero)', type: 'text', required: false, options: [] },
  { key: 'riferimento_normativo', label: 'Riferimento normativo', type: 'textarea', required: false, options: [] },
  { key: 'applica_bollo', label: 'Applica imposta di bollo', type: 'checkbox', required: false, options: [] },
  { key: 'soglia_bollo', label: 'Soglia bollo (EUR)', type: 'text', required: true, options: [] },
  { key: 'importo_bollo', label: 'Importo bollo (EUR)', type: 'text', required: true, options: [] },
  { key: 'condizioni_pagamento', label: 'Condizioni pagamento', type: 'text', required: true, options: [] },
  { key: 'modalita_pagamento', label: 'Modalità pagamento', type: 'text', required: true, options: [] },
  { key: 'giorni_scadenza', label: 'Giorni di scadenza', type: 'number', required: true, options: [] },
  { key: 'iban', label: 'IBAN', type: 'text', required: false, options: [] },
]

const KEYS = FIELDS.map((field) => field.key)

const DEFAULTS: Record<string, unknown> = {
  codice_regime: 'RF19',
  aliquota_iva_default: '0.00',
  natura_default: 'N2.2',
  riferimento_normativo:
    'Operazione non soggetta a IVA ai sensi dell’art. 1, commi 54-89, L. 190/2014 — regime forfettario',
  applica_bollo: true,
  soglia_bollo: '77.47',
  importo_bollo: '2.00',
  condizioni_pagamento: 'TP02',
  modalita_pagamento: 'MP05',
  giorni_scadenza: 30,
  iban: '',
}

export function fiscalProfileToFormValues(profile: FiscalProfile): Record<string, unknown> {
  const values: Record<string, unknown> = {}
  for (const key of KEYS) {
    values[key] = (profile as unknown as Record<string, unknown>)[key] ?? ''
  }
  return values
}

/**
 * One row with required fields, so the whole object is sent on every save -- the same
 * shape `EmitterPanel` uses for `emitter_profile`, and the reason both endpoints are a
 * `PUT` rather than a `PATCH`. There is no partial update to get wrong, so A14 has no
 * surface here at all.
 */
export function FiscalProfilePanel() {
  const profile = useFiscalProfile()
  const save = useSaveFiscalProfile()
  const [values, setValues] = useState<Record<string, unknown> | null>(null)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  if (profile.isError) return <QueryErrorBanner error={profile.error} />
  if (profile.isLoading) return <p className="text-muted-foreground">Caricamento…</p>

  const stored = profile.data
  const current =
    values ?? (stored === null ? DEFAULTS : fiscalProfileToFormValues(stored))

  return (
    <div className="space-y-5">
      {stored === null && (
        <p className="rounded-lg border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Il profilo fiscale non è ancora configurato. Senza di esso non si può emettere
          nessuna fattura: i valori proposti qui sotto sono quelli del regime forfettario.
        </p>
      )}

      <DynamicForm
        fields={FIELDS}
        values={current}
        onChange={(key, value) =>
          setValues({ ...current, [key]: value })
        }
        problem={problem}
        mode={stored === null ? 'create' : 'edit'}
      />

      <div className="flex items-center gap-2">
        <Button
          disabled={save.isPending}
          onClick={() => {
            setProblem(null)
            const body: Record<string, unknown> = {}
            for (const key of KEYS) {
              const value = current[key]
              // An empty string means "no value" for the two nullable fields and is
              // sent as null; `0`, `false` and `'0.00'` are values and go through
              // untouched.
              body[key] = typeof value === 'string' && value.trim() === '' ? null : value
            }
            body.giorni_scadenza = Number(current.giorni_scadenza)
            save.mutate(body, {
              onSuccess: () => toast.success('Profilo fiscale salvato'),
              onError: (error) => setProblem(toProblem(error)),
            })
          }}
        >
          {save.isPending ? 'Salvataggio…' : 'Salva'}
        </Button>
        <p className="text-xs text-muted-foreground">
          Ogni modifica lascia una voce in cronologia: cambiare regime senza traccia non è
          un&apos;opzione.
        </p>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add the route and the settings nav entry**

`apps/web/src/routes/app/impostazioni/fiscale.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { FiscalProfilePanel } from '@/features/settings/FiscalProfilePanel'

function FiscalSettingsPage() {
  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold tracking-tight">Profilo fiscale</h2>
        <p className="text-sm text-muted-foreground">
          Regime, aliquote, bollo e condizioni di pagamento. Guidano i totali e il file
          FatturaPA di ogni fattura emessa da qui in avanti; una fattura già emessa resta
          congelata sui parametri che aveva.
        </p>
      </header>
      <FiscalProfilePanel />
    </div>
  )
}

export const Route = createFileRoute('/app/impostazioni/fiscale')({
  component: FiscalSettingsPage,
})
```

In `apps/web/src/routes/app/impostazioni.tsx`, add `{ to: '/app/impostazioni/fiscale', label: 'Fiscale' }` to whichever array of settings links that layout renders, next to the existing `Emittente` entry — the two belong together: one is the issuer's identity, the other its fiscal parameters.

- [ ] **Step 5: Add the eslint override**

```js
  {
    files: ['src/features/settings/FiscalProfilePanel.tsx'],
    rules: {
      'react-refresh/only-export-components': [
        'warn',
        { allowExportNames: ['fiscalProfileToFormValues'] },
      ],
    },
  },
```

- [ ] **Step 6: Run the tests and the compiler**

Run: `cd apps/web && pnpm exec vitest run && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS and clean.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/settings/FiscalProfilePanel.tsx apps/web/src/routes/app/impostazioni/fiscale.tsx apps/web/src/routes/app/impostazioni.tsx apps/web/eslint.config.js apps/web/src/features/settings/FiscalProfilePanel.test.tsx
git commit -m "feat(web): the fiscal profile settings panel"
```

---

### Task 21: The full cycle, end to end, from both adapters

**Files:**
- Create: `apps/web/e2e/fatture.spec.ts`
- Modify: `apps/web/e2e/helpers.ts` (two new helpers)
- Test: `packages/core/tests/test_full_invoice_cycle.py`

**Interfaces:**
- Consumes: everything. This task adds no production code.
- Produces:
  - `e2e/helpers.ts`: `createFiscalProfile(page: Page): Promise<void>`, `createEmitterProfile(page: Page): Promise<void>`
  - `e2e/fatture.spec.ts`: the browser half of spec criterion 10
  - `packages/core/tests/test_full_invoice_cycle.py`: the in-process half — MCP prepares, a human issues, both artefacts validate, and the timeline distinguishes the two actors

- [ ] **Step 1: Write the failing cross-adapter test**

`packages/core/tests/test_full_invoice_cycle.py`:

```python
"""Spec criterion 10, in process: the whole cycle from both adapters.

Claude prepares a three-line proforma through the MCP call path; a human converts it
into an invoice; the XML validates against the official schema; the customer's timeline
distinguishes `mcp` from `user`; and there is no tool for the agent to call in order to
issue.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fpr12 import assert_valid
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceIssue, InvoiceLineIn
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage.local import LocalFileStorage

AGENT = Actor(id=None, type="mcp", role="collaboratore")
HUMAN = Actor(id=None, type="user", role="admin")


@pytest.fixture
def world(db_session: Session, tmp_path) -> tuple[InvoiceService, UUID]:  # type: ignore[no-untyped-def]
    FiscalProfileService(db_session).upsert(
        FiscalProfileUpsert(codice_regime="RF19", iban="IT60X0542811101000000123456"), HUMAN
    )
    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(
            ragione_sociale="Humancraft di Ivan Sala",
            partita_iva="14518240966",
            codice_fiscale="HMCRFT00A01H501K",
            indirizzo="Via Vittorio Veneto 12",
            cap="20124",
            comune="Milano",
            provincia="MI",
            nazione="IT",
            email="someone@example.com",
        ),
        HUMAN,
    )
    customer = Customer(
        ragione_sociale="Acme S.r.l.",
        partita_iva="12345678901",
        codice_sdi="ABCDEFG",
        indirizzo="Corso Italia 5",
        cap="00100",
        comune="Roma",
        provincia="RM",
        nazione="IT",
    )
    db_session.add(customer)
    db_session.flush()
    return InvoiceService(db_session, LocalFileStorage(tmp_path / "documents")), customer.id


def test_an_agent_prepares_and_a_human_issues(
    world: tuple[InvoiceService, UUID], db_session: Session
) -> None:
    service, customer_id = world

    # 1. The agent prepares a three-line proforma. It consumes no number.
    proforma = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            causale="Consulenza agosto",
            tipo="proforma",
            righe=[
                InvoiceLineIn(descrizione="Analisi", prezzo_unitario=Decimal("500.00")),
                InvoiceLineIn(descrizione="Sviluppo", prezzo_unitario=Decimal("1500.00")),
                InvoiceLineIn(descrizione="Sconto", prezzo_unitario=Decimal("-200.00")),
            ],
        ),
        AGENT,
    )
    assert proforma.numero is None
    assert proforma.totale == Decimal("1800.00")

    # 2. The human confirms and converts. A new row, and the proforma is consumed.
    service.confirm_proforma(proforma.id, HUMAN)
    issued = service.issue(proforma.id, InvoiceIssue(), HUMAN)
    assert issued.id != proforma.id
    assert issued.numero == 1
    assert issued.origine_proforma_id == proforma.id
    assert service.get(proforma.id, HUMAN).stato == "consumata"

    # 3. Both artefacts exist and the XML passes the official schema.
    data, content_type, filename = service.download(issued.id, "xml", HUMAN)
    assert content_type == "application/xml"
    assert filename.startswith("IT")
    assert_valid(data)
    pdf, pdf_type, _ = service.download(issued.id, "pdf", HUMAN)
    assert pdf_type == "application/pdf"
    assert pdf.startswith(b"%PDF")

    # 4. The timeline distinguishes the agent from the human.
    proforma_entries = ActivityService(db_session).timeline("invoice", proforma.id)
    invoice_entries = ActivityService(db_session).timeline("invoice", issued.id)
    assert {entry.actor_type for entry in proforma_entries} == {"mcp", "user"}
    assert {entry.actor_type for entry in invoice_entries} == {"user"}
    assert "issued" in {entry.kind for entry in invoice_entries}


def test_the_agent_role_cannot_issue_at_all(world: tuple[InvoiceService, UUID]) -> None:
    """Belt and braces beside the structural ban: even if a tool existed, the MCP
    context's actor is a collaborator and `issue` requires admin. The *reason* the tool
    does not exist is that R10 lets a PAT inherit the owner's admin role, so this check
    alone would not be enough -- which is exactly why both are here."""
    from pigrocrm.core.errors import PermissionDenied

    service, customer_id = world
    draft = service.create(
        InvoiceCreate(
            customer_id=customer_id,
            righe=[InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("100.00"))],
        ),
        AGENT,
    )
    with pytest.raises(PermissionDenied):
        service.issue(draft.id, InvoiceIssue(), AGENT)
```

- [ ] **Step 2: Run it to verify it fails, then passes**

Run: `uv run pytest packages/core/tests/test_full_invoice_cycle.py -v`
Expected: PASS once Tasks 1–13 are done; if it fails, the failure names which stage of the cycle broke, which is the point of having it as one test rather than five.

- [ ] **Step 3: Add the two E2E helpers**

In `apps/web/e2e/helpers.ts`, append:

```ts
export async function createFiscalProfile(page: Page): Promise<void> {
  await page.goto('/app/impostazioni/fiscale')
  await page.getByRole('button', { name: 'Salva' }).click()
  await expect(page.getByText('Profilo fiscale salvato')).toBeVisible()
}

export async function createEmitterProfile(page: Page): Promise<void> {
  await page.goto('/app/impostazioni/emittente')
  await page.getByLabel('Ragione sociale').fill('Humancraft di Ivan Sala')
  await page.getByLabel('P.IVA').fill('14518240966')
  await page.getByLabel('Codice fiscale').fill('HMCRFT00A01H501K')
  await page.getByLabel('Indirizzo').fill('Via Vittorio Veneto 12')
  await page.getByLabel('CAP').fill('20124')
  await page.getByLabel('Comune').fill('Milano')
  await page.getByLabel('Provincia').fill('MI')
  await page.getByRole('button', { name: 'Salva' }).click()
}
```

`expect` must be imported there if it is not already; use the field labels the shipped `EmitterPanel` actually renders rather than these if they differ.

- [ ] **Step 4: Write the browser spec**

`apps/web/e2e/fatture.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { createCustomer, createEmitterProfile, createFiscalProfile, loginAsAdmin } from './helpers'

test.describe('Fatture', () => {
  test('il ciclo completo: bozza, righe, emissione, PDF e XML', async ({ page }) => {
    await loginAsAdmin(page)
    await createFiscalProfile(page)
    await createEmitterProfile(page)

    // A customer with the fiscal columns filled in: without them the emission refuses,
    // by design, naming the field.
    await page.goto('/app/clienti')
    await page.getByRole('button', { name: /nuovo cliente/i }).click()
    const name = `Fatture ${Date.now()}`
    await page.getByLabel('Ragione sociale').fill(name)
    await page.getByLabel('P.IVA').fill('12345678901')
    await page.getByLabel('Codice destinatario').fill('ABCDEFG')
    await page.getByLabel('Indirizzo').fill('Corso Italia 5')
    await page.getByLabel('CAP').fill('00100')
    await page.getByLabel('Comune').fill('Roma')
    await page.getByLabel('Provincia').fill('RM')
    await page.getByRole('button', { name: 'Salva' }).click()

    await page.getByText(name).click()
    await page.getByRole('tab', { name: 'Fatture' }).click()
    await expect(page.getByText('Nessuna fattura.')).toBeVisible()

    await page.getByRole('button', { name: /nuovo documento/i }).click()
    await page.getByLabel('Causale').fill('Consulenza agosto')
    await page.getByLabel('Descrizione').fill('Consulenza tecnica')
    await page.getByLabel('Prezzo unitario').fill('1500.00')
    await page.getByRole('button', { name: 'Crea' }).click()

    await expect(page.getByText('Bozza')).toBeVisible()
    await expect(page.getByText('1.500,00')).toBeVisible()

    await page.getByRole('button', { name: 'Emetti' }).click()
    await expect(page.getByText(/consuma un numero del registro/i)).toBeVisible()
    await page.getByRole('button', { name: /conferma emissione/i }).click()

    await expect(page.getByText('Emessa')).toBeVisible()
    await expect(page.getByRole('button', { name: /scarica pdf/i })).toBeVisible()

    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: /scarica xml/i }).click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(/^IT[A-Z0-9]+_[A-Z0-9]{5}\.xml$/)
  })

  test('una fattura emessa non si modifica e non si elimina', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/app/fatture')
    await page.getByRole('button', { name: 'Emessa' }).click()
    const first = page.getByRole('row').nth(1)
    if ((await first.count()) === 0) return
    await first.click()
    // The line editor is read-only: no save button exists at all, rather than one that
    // fails when pressed.
    await expect(page.getByRole('button', { name: /salva righe/i })).toHaveCount(0)
  })

  test('un annullamento richiede un motivo e conserva il numero', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/app/fatture')
    await page.getByRole('button', { name: 'Emessa' }).click()
    const first = page.getByRole('row').nth(1)
    if ((await first.count()) === 0) return
    const numero = (await first.getByRole('cell').first().textContent()) ?? ''
    await first.click()
    await page.getByRole('button', { name: /annulla fattura/i }).click()
    await expect(page.getByRole('button', { name: /conferma annullamento/i })).toBeDisabled()
    await page.getByLabel('Motivo').fill('importo errato')
    await page.getByRole('button', { name: /conferma annullamento/i }).click()
    await expect(page.getByText('Annullata')).toBeVisible()
    await expect(page.getByText(numero.trim())).toBeVisible()
  })

  test('una proforma dichiara di non essere una fattura e non offre XML', async ({ page }) => {
    await loginAsAdmin(page)
    await createFiscalProfile(page)
    const customerName = await createCustomer(page)
    await page.goto('/app/fatture')
    await page.getByRole('button', { name: /nuovo documento/i }).click()
    await page.getByLabel('Cliente (id)').fill('')
    // Filled through the customer's own tab instead, where the id is known.
    await page.getByRole('button', { name: 'Annulla' }).click()

    await page.goto('/app/clienti')
    await page.getByText(customerName).click()
    await page.getByRole('tab', { name: 'Fatture' }).click()
    await page.getByRole('button', { name: /nuovo documento/i }).click()
    await page.getByLabel('Tipo').click()
    await page.getByRole('option', { name: 'proforma' }).click()
    await page.getByLabel('Descrizione').fill('Prospetto')
    await page.getByLabel('Prezzo unitario').fill('500.00')
    await page.getByRole('button', { name: 'Crea' }).click()

    await expect(page.getByText(/^PROV-/)).toBeVisible()
    await expect(page.getByRole('button', { name: /scarica xml/i })).toHaveCount(0)
  })

  test('la lista mostra un banner quando la richiesta fallisce, non una tabella vuota', async ({
    page,
  }) => {
    await loginAsAdmin(page)
    await page.route('**/api/invoices?**', (route) => route.abort())
    await page.goto('/app/fatture')
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText('Nessun documento. Creane uno per iniziare.')).toHaveCount(0)
  })
})
```

- [ ] **Step 5: Run the suite**

Run: `cd apps/web && pnpm test:e2e`
Expected: PASS. `fullyParallel` is `false` and `workers` is `1` in `playwright.config.ts` because the suite shares one database — this spec depends on that and must not change it.

- [ ] **Step 6: Run everything, once**

```bash
uv run pytest
uv run mypy
uv run ruff check .
cd apps/web && pnpm exec tsc --noEmit && pnpm lint && pnpm exec vitest run && cd ../..
```
Expected: all green, nothing skipped.

- [ ] **Step 7: Commit**

```bash
git add packages/core/tests/test_full_invoice_cycle.py apps/web/e2e/fatture.spec.ts apps/web/e2e/helpers.ts
git commit -m "test: the full invoice cycle, from both adapters"
```

---

## Definition of done for slice 3

Every one of the spec's ten success criteria maps to a test that runs in CI:

| Criterion | Where it lives |
|---|---|
| 1 — the official schema validates, on five cases including both stamp-duty boundaries | Task 6, `test_invoice_fatturapa.py` |
| 2 — a hostile name corrupts neither the XML nor the PDF | Task 6 (`test_a_hostile_name_*`), Task 12 (`test_the_hostile_customer_name_survives_the_whole_round_trip`), Task 13 (`test_a_hostile_customer_name_appears_in_the_pdf_as_text`) |
| 3 — numbering under concurrency, and a failed emission consuming nothing | Task 10, `test_invoice_numbering_concurrency.py` |
| 4 — immutability enforced by the database, including raw SQL | Task 8, `test_invoice_models.py`; Task 11, `test_invoice_immutability.py`; Task 14, `test_deleting_an_issued_invoice_is_a_409` |
| 5 — a proforma produces no XML, declares itself, and its reference matches no fiscal pattern | Task 5, Task 12, Task 13 |
| 6 — faithful regeneration a year later, byte for byte | Task 12 (`test_a_regenerated_export_is_byte_identical_to_the_original`), Task 13 (`test_re_rendering_is_byte_identical_and_writes_no_second_version`) |
| 7 — the MCP ban is in the build | Task 15, `test_mcp_invoice_ban.py` |
| 8 — the rounding rules are behaviour, via a synthetic `RF01` | Task 2, Task 3, Task 6 (`test_two_rates_produce_one_summary_group_each_with_group_computed_tax`) |
| 9 — every refusal names the field | Task 6, Task 10, Task 14 (`test_a_refusal_names_the_field_in_the_problem_document`) |
| 10 — the full cycle from both adapters | Task 21 |

## Self-review

Run after the plan is written, against the spec with fresh eyes.

**Spec coverage.** §1–2 (what is carried and what is rewritten) → Tasks 1, 2, 5, 6, and the "Contradictions" section. §3 numbering → Tasks 8, 10. §4 immutability and correction → Tasks 8, 11, 12. §5 proformas → Tasks 5, 8, 9, 10, 13. §6 money and rounding, §6.1 the two divergent rules, §6.2 the issue date → Tasks 2, 4, 10. §7 the regime, §7.1 `fiscal_profile`, §7.2 how it drives totals and XML → Tasks 3, 7. §8 the data model, §8.1–8.3 → Tasks 4, 8; §8.4 where the bytes live → Tasks 5, 12, 13; §8.5 `entity_type` → Task 4. §9 XML generation → Task 6. §10 PDF and templates → Task 13. §11 the MCP and API surface → Tasks 14, 15. §12 residuals → the "Known open defects" section, and R1/R10 specifically in Task 15's own test docstring. §13 out of scope → nothing is planned for any of it; the two places a user could expect otherwise (a credit note, a foreign customer) return a refusal that says where to go instead, in Tasks 11 and 6. §14 the ten criteria → the table above.

**Not turned into a concrete task, and why.** Nothing in the spec is left unplanned. Two of its statements are deliberately implemented as *refusals with an explanation* rather than as features, because that is what the spec asks for: the credit note (§13) and the foreign customer (§12, R12). One is implemented differently from the spec's letter and the difference is recorded: the FPR12 schema version, the `xmllint` invocation, the per-year proforma sequence, the SdI file name as a download name, the `issue` signature, where the invoice templates live, and the shape of the MCP exclusion list — all eleven resolutions are in the "Contradictions" section with the file and line that settled each.

**Placeholder scan.** No step says "add appropriate error handling", "similar to Task N", "TBD" or "write tests for the above". Four places tell the implementer to prefer what the repository actually has over what this plan sketched — the `apps/api/tests/conftest.py` client fixtures (Task 14), the `apps/mcp/tests/conftest.py` context fixture and `build_server` enumeration (Task 15), `test_documents_service.py`'s existing helpers (Task 12), and the `EmitterPanel` field labels (Task 21). Each names the file to read and the reason, which is a check against drift rather than a gap.

**Type consistency.** `InvoiceService`'s method names are identical everywhere they appear: `create`, `update`, `replace_lines`, `confirm_proforma`, `issue`, `annul`, `mark_transmitted_externally`, `set_payment_state`, `export_xml`, `render_pdf`, `produce_artifacts`, `download`, `get`, `lines`, `soft_delete`, `list`. `lines` is defined above `list` in Tasks 9 and asserted to be so by `test_list_is_the_last_method_of_the_service_class`. `check_party_exportable` and `check_recipient_routing` are module-level in Task 6 and called from both Task 6 and Task 10. `InvoiceArtifact` has the same five fields in Task 4, Task 12, Task 13 and Task 14. `formatMoney`/`formatDate`/`formatInvoiceNumber`/`sumLineTotals` are declared in Task 16 and used unchanged in Tasks 17, 18 and 19. `queryKeys.invoices`/`invoice`/`invoiceLines`/`fiscalProfile` are added in Task 16 and used with those exact names afterwards. The migration chain is `0003 → 0004 (fiscal_profile) → 0005 (invoices)`, and both `assert revision == …` lines in `test_migrations.py` are updated in the task that adds each revision.

