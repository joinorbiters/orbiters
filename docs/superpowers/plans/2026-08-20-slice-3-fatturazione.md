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
- **Form state keeps `{native, custom}` as two namespaces, decided once at seed time and never re-derived at submit.** Provenance is structural. A native column clears on `""` and only on `""`; a custom field clears on `null` and only on `null`; an omitted key clears nothing. `0` and `false` are values, never blanks — mirror `is_blank` exactly. **Never sum money as a JS float**: format `Numeric` values as the strings the API sends, and where a sum is unavoidable use the exact-cents helper `centsFromDecimalString` already in `apps/web/src/features/deals/columns.tsx` (`Number("0.29") * 100 === 28.999999999999996`).
- **`DynamicForm` takes a required, undefaulted `mode: 'create' | 'edit'` prop.** Every new call site answers the question explicitly.
- **A failed request must never look like an empty result.** A query in `isError` renders `QueryErrorBanner`, never an empty table or an empty list.
- **`DataTable` is TanStack Table v9** (`@tanstack/react-table 9.0.0`): `tableFeatures({})` + `useTable`, `ColumnDef<DataTableFeatures, T>` with the feature type parameter **first**, and rendering through the table-bound `<table.FlexRender header={…} />` / `<table.FlexRender cell={…} />`. There is no `useReactTable`, no `getCoreRowModel`, and no standalone `flexRender()` in v9.

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
10. **The proforma reference comes from one sequence, not a sequence per year.** Spec §5 says the proforma's `riferimento` comes from "una `SEQUENCE` Postgres per anno". A sequence per year means either creating a sequence with runtime DDL inside a request, or pre-creating a hundred of them in a migration. **Resolution (Task 8):** one `proforma_riferimento_seq`, never reset, with the label `PROV-{anno}-{nextval:04d}`. The spec's *reason* for choosing a sequence here is honoured exactly — `nextval()` does not roll back, gaps on a proforma mean nothing, and in exchange the counter serialises nobody — and "per year" was only ever cosmetic, since the number carries no fiscal meaning and the year is already in the label.

9. **The invoice and proforma layouts are repo assets, not rows in the `templates` table.** Spec §10 says "due template nuovi, `fattura` e `proforma`" without saying where they live. **Verified:** `templates` rows are user-editable with no per-row version history, and `render/assets/template-offer.md` shows the shipped precedent for a layout that lives in the package. A fiscal document whose layout can be silently edited between issue and re-render cannot satisfy §14.6's byte-for-byte re-render. **Resolution (Task 13):** `render/assets/template-invoice.md` and `render/assets/template-proforma.md`, read from disk, filled from the frozen `snapshot`. `"fattura"`/`"proforma"` are still added to `DocumentTipo` because `documents.tipo` needs them (§8.4); that they become legal `templates.tipo` values too is harmless.

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
│   ├── queries.ts                              # types, hooks, labels, money formatting
│   ├── columns.tsx                             # DataTable columns + state badges
│   ├── InvoiceLinesEditor.tsx                  # the multi-line editor
│   ├── InvoiceForm.tsx                         # create draft / proforma
│   ├── InvoiceActions.tsx                      # issue · annul · transmitted · payment
│   ├── InvoicesTab.tsx                         # the customer/deal detail tab
│   └── FiscalProfilePanel.tsx                  # settings
└── routes/app/fatture/{index.tsx,$invoiceId.tsx}
    routes/app/impostazioni/fiscale.tsx
apps/web/e2e/fatture.spec.ts
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
  - `ALLOWED_STATI: dict[str, frozenset[str]]` keyed by `tipo`
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


def test_update_exposes_only_what_is_mutable_after_emission() -> None:
    """A14 is sidestepped rather than reproduced: the only clearable native column
    here is `note_interne`, which is Text and clears with ""."""
    assert set(InvoiceUpdate.model_fields) == {"note_interne", "custom_fields"}


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
    `issue`/`annul`. `note_interne` is `Text`, so `""` is its own "clear it" spelling.
    """

    model_config = ConfigDict(extra="forbid")

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
_LATIN_RE = re.compile(r"[ -ÿ]*")
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
        self._check_party(emittente, "emitter_profile")
        self._check_party(cliente, "customer")

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

    def _check_party(self, party: PartySnapshot, entity: str) -> None:
        """Every refusal names the field on the record the user can go and fix
        (spec 14.9). Acme guessed the address parts out of free text with a regex
        over Italian street prefixes; these are four real columns."""
        if party.nazione != "IT":
            raise ValidationFailed(
                entity,
                "nazione",
                "questo slice non emette fatture verso l'estero: "
                "richiedono un IdPaese diverso e CodiceDestinatario XXXXXXX",
                expected="IT",
            )
        for field in ("indirizzo", "cap", "comune", "provincia"):
            if not (getattr(party, field) or "").strip():
                raise ValidationFailed(
                    entity, field, "campo obbligatorio per la fattura elettronica",
                    expected="un valore non vuoto",
                )
        if not party.ragione_sociale.strip():
            raise ValidationFailed(
                entity, "ragione_sociale", "campo obbligatorio", expected="un valore non vuoto"
            )

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


__all__ = ["FPR12_NAMESPACE", "FORMATO_TRASMISSIONE", "NSMAP", "FatturaPAExporter", "normalise_fiscal_id"]
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
<!-- PART -->
