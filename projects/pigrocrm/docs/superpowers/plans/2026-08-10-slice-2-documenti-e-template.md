# PigroCRM Slice 2 — Documenti e template — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give customers and deals a versioned document store, a template engine that turns Markdown into offers with context-correct escaping, a Pandoc→Typst PDF renderer, offer states, pluggable storage (local filesystem and Google Drive), a configurable emitter profile replacing the hardcoded issuer data.

**Architecture:** Everything new lives in `packages/core` as domain services that know nothing about HTTP or MCP, exactly as slice 1: `templates/` (a pure, database-free rendering engine), `storage/` (a `Protocol` and two implementations), `render/` (subprocess invocation of Pandoc and Typst), `documents/` and `emitter/` (the usual models/schemas/repository/service quartet). The two thin adapters — FastAPI routers and MCP tools — import those same services in-process, and `packages/core/tests/test_architecture.py` keeps the dependency direction one-way. The template engine is a parser, not a `str.replace`: it segments the template into Markdown, raw-Typst and URL regions first, so every placeholder carries the escaping rule of the region it lands in.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · psycopg 3 · PostgreSQL 17 · MCP SDK v2 · pytest + testcontainers · Pandoc 3.1.12.2 · Typst 0.11.0 · Vite · React 19 · TanStack Router/Query/Table · shadcn/ui · Tailwind v4 · Playwright

**Spec:** `docs/superpowers/specs/2026-08-10-slice-2-documenti-e-template-design.md`

**Prerequisite:** slice 1 (`2026-08-06-slice-1a-backend.md` and `2026-08-06-slice-1b-frontend.md`) complete and in `main`.

---

## Global Constraints

These apply to **every** task. They are not repeated per task. Everything from `## Global Constraints` in the two slice-1 plans that still applies is carried here with its exact values; the last block is new to this slice.

### Carried from plan 1A (backend)

- **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Managed by **uv workspaces**. Do not use pip, poetry, or venv directly.
- **`packages/core` must never import from `apps.`** — enforced by `packages/core/tests/test_architecture.py`. That test is an *allowlist*: core may import the stdlib, the `pigrocrm` namespace, and only what `packages/core/pyproject.toml` declares under `[project].dependencies`. If a task seems to require anything else, either declare the dependency there or the design is wrong; stop and flag it.
- **Services receive and return Pydantic models only.** No `Request`, `Response`, `HTTPException`, or status codes inside `packages/core`.
- **Every service method that writes takes `actor: Actor`** as an explicit parameter. Never read the actor from global or contextual state.
- **One service method = one transaction.** The service commits; repositories never commit.
- **Money is `Numeric(12, 2)`; hours are `Numeric(8, 2)`.** Never `Float` for either.
- **All timestamps are `TIMESTAMP WITH TIME ZONE` in UTC.** Use `datetime.now(timezone.utc)` (imported as `from datetime import UTC, datetime` → `datetime.now(UTC)`, matching `db/base.py`), never `datetime.utcnow()`.
- **All primary keys are UUIDv7** via `uuid_utils.uuid7()`, stored as native `UUID`. Use the shared `pigrocrm.core.db.base.uuid7` wrapper, never `uuid_utils` directly in a model.
- **Soft delete**: entities carry `deleted_at`. Repository queries filter `deleted_at IS NULL` unless explicitly asked otherwise. No physical delete exists anywhere in this slice either.
- **Tests use real PostgreSQL via testcontainers.** Never SQLite — JSONB and GIN indexes do not exist there. Use the existing `db_engine`/`db_session` fixtures in `packages/core/tests/conftest.py`.
- **TDD is mandatory for `packages/core`.** Write the failing test, watch it fail, then implement.
- **Commit after every task**, using the message given in the task's final step.
- **UI language is Italian.** Field labels, buttons, and error messages shown to users are Italian. Code identifiers, table names, and column names are English except the Italian fiscal and domain terms already fixed in slice 1 (`partita_iva`, `codice_fiscale`, `codice_sdi`, `pec`, `ragione_sociale`, `indirizzo`, `cap`, `comune`, `provincia`, `nazione`) and the ones this slice's spec fixes (`tipo`, `titolo`, `stato`, `versione_corrente`, `numero`, `sorgente_markdown`, `variabili`, `variabili_dichiarate`, `corpo_markdown`, `attivo`, `creato_da`, `dimensione`).
- **The `Expected: PASS (N passed)` counts are indicative, not contractual.** Parametrised tests expand to different totals than the number of test functions. What matters is that every test passes and none is skipped — a differing total is not a failure and must not be "fixed" by deleting or merging cases.
- **A uniqueness pre-check never replaces the database constraint.** Wherever a service does "SELECT to check, then INSERT", it must also catch `sqlalchemy.exc.IntegrityError` around the commit, `session.rollback()`, and re-raise the domain `Conflict`. Two concurrent requests both pass the SELECT; only the constraint stops the second, and without the rollback the caller's session is left poisoned (`PendingRollbackError` on its next statement).
- **Case-insensitive uniqueness needs a functional index, not a convention.** A plain `unique=True` on a text column is case-sensitive: lowercasing in a Pydantic validator protects only the paths that go through it. Where identity is case-insensitive (template names here), declare `Index("uq_…", func.lower(col), unique=True)` in `__table_args__`.
- **A method named `list` must be the last method in its class.** `def list(...)` rebinds `list` in the class namespace, so any later method annotated `-> list[Something]` resolves it to that method and raises `TypeError: 'function' object is not subscriptable` at import time. Python 3.13 evaluates annotations eagerly, so this is a hard failure here; 3.14's PEP 649 would hide it. Calling `self.list()` from an earlier method is fine — that is a call-time attribute lookup, not an annotation. The rule is unconditional: do not reason about whether a later method *currently* returns a `list[...]`. `packages/core/tests/test_module_imports.py` is the real guard; keep it green.
- **Every `Numeric(p, s)` column needs a matching Pydantic `Field(max_digits=p, decimal_places=s)`** on both schemas. Without it, a value beyond the column's capacity reaches Postgres and raises `NumericValueOutOfRange` — the same uncaught-`DataError`, poisoned-session failure as the string case — and a sub-scale value like `Decimal("0.005")` is silently rounded by the database while the object returned to the caller still shows the original. Reject rather than round.
- **Every `String(n)` column needs a matching Pydantic `max_length=n`** on both the Create and the Update schema. Without it an over-long value reaches Postgres, raises `sqlalchemy.exc.DataError` — **not** a subclass of `IntegrityError`, so no existing handler catches it — and leaves the caller's session poisoned. Where an exact-format check already bounds the length, that check must use **`re.fullmatch`, never `re.match` with `$`**: Python's `$` matches before a trailing newline, so `^\d{11}$` accepts a 12-character string and the value still reaches the database. **This rule applies to every regex in this slice, including the template engine's own path and storage-key patterns, which are not database-bound at all** — the habit is what protects the ones that are.
- **Every `Integer` column needs a bounded Pydantic field** (`Field(ge=..., le=...)`) on both schemas, picked to be defensible for that field's meaning. Without a bound, a value like `2**40` reaches Postgres raw as `IntegerOutOfRange`, the same uncaught-`DataError`, poisoned-session failure. **Exception, not violation**: a field already fully bounded by an equivalent service-level range check does not also need a schema-level bound — adding one changes which exception type fires (`pydantic.ValidationError` instead of this project's own `ValidationFailed`) for a same-shaped value the service already rejects correctly, which is a regression. Document any omission in a comment.
- **A NUL byte (`"\x00"`) in a native `String`/`Text` field is rejected, not stored.** Use the shared `pigrocrm.core.validation.SafeStr` annotated type on every user-supplied string field on every Create/Update schema, including inside `list[str]` fields. Reject, never strip. A field already passing through a transformation that structurally cannot leave a NUL byte behind does not need `SafeStr` layered on top — document why rather than adding a check that can be shown to never fire.
- **Every foreign key column is validated against the table it references, in both `create` and `update`**, including one that is optional (`nullable`) — a nullable FK is skipped only when the caller supplies nothing, never when the caller supplies a value. Without this, any syntactically valid UUID reaches `flush()`/`commit()` and comes back as a raw `sqlalchemy.exc.IntegrityError` (`ForeignKeyViolation`) instead of this project's own `NotFound`.
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

### Pinned versions

Backend (slice 1A, resolved and verified 2026-08-06 — unchanged): `fastapi 0.141.1` · `uvicorn 0.52.1` · `sqlalchemy 2.0.51` · `alembic 1.19.0` · `psycopg[binary] 3.3.4` · `pydantic 2.13.4` · `pydantic-settings 2.14.2` · `argon2-cffi 25.1.0` · `pyjwt 2.13.0` · `mcp 2.0.0` · `uuid-utils 0.17.0` · `pytest 9.1.1` · `testcontainers[postgres] 4.15.0` · `ruff 0.16.1` · `mypy 2.3.0`

Frontend (slice 1B — unchanged): `vite 8.2.0` · `react 19.2.8` · `react-dom 19.2.8` · `typescript 5.9` (**not** 7.x) · `@tanstack/react-router 1.170.20` · `@tanstack/router-plugin 1.168.25` · `@tanstack/react-query 5.101.4` · `@tanstack/react-table 9.0.0` · `tailwindcss 4.3.3` · `@tailwindcss/vite 4.3.3` · `shadcn 4.16.1` (CLI) · `@dnd-kit/core 6.3.1` · `@dnd-kit/sortable 10.0.0` · `openapi-typescript 7.13.0` · `openapi-fetch 0.17.0` · `@playwright/test 1.62.1` · `lucide-react` latest · `@tabler/icons-react` latest (**brand icons only**). Package manager: **pnpm 10**.

**New to this slice:** `PANDOC_VERSION=3.1.12.2` and `TYPST_VERSION=0.11.0`, pinned as build args in `Dockerfile.api`. These are the exact versions `.reference-acme/Dockerfile` pins (lines 3–4); the Typst template and `header.typ` are carried over unmodified, so the toolchain that is known to compile them is carried over too. **No new Python dependency is added to `packages/core`** — the Google Drive client is built on `urllib.request` and `json` from the stdlib, which the architecture test already allows.

### Design tokens (exact values — do not improvise)

| Token | Hex | Role |
|---|---|---|
| Watermelon | `#ED254E` | primary action, destructive state |
| Royal Gold | `#F9DC5C` | warning, attention |
| Mint Cream | `#F4FFFD` | app background (light) |
| Prussian Blue | `#011936` | foreground text, dark surface |
| Charcoal Blue | `#465362` | muted / secondary text |

Font: **Outfit** only. `Reenie Beanie` belongs to the landing page in slice 5 — do **not** load it here. Contrast must reach **WCAG AA**; for body copy on light backgrounds use Prussian Blue.

### New to slice 2

- **No user input ever reaches a command line.** `subprocess.run` is always called with an argument *list*, never a string, and never with `shell=True`. Every value a user or an agent supplied travels inside the source file the renderer writes; every path in the argument list is generated by the service from `tempfile.mkdtemp()`, never from a request. There is no exception to this rule anywhere in `packages/core/src/pigrocrm/core/render/`.
- **A subprocess call is always bounded.** `subprocess.run(..., timeout=RENDER_TIMEOUT_SECONDS, capture_output=True, check=False)`. `RENDER_TIMEOUT_SECONDS = 30`. Never `check=True`: the whole point is to read the compiler's own diagnostics and translate them.
- **Raw compiler stderr never reaches the user.** A Typst failure is translated into the offending *template* line before it becomes a `ValidationFailed`. The raw stderr belongs in the server log, not in a problem document.
- **Escaping is decided by context, never by a single pass.** No function in this slice may escape a value without being told which of `"markdown"`, `"typst"`, `"url"` it is escaping for. A `str.replace` over a whole rendered document is the defect this slice exists to prevent.
- **`content_type` is chosen from a fixed allowlist, never echoed from the request.** `ALLOWED_CONTENT_TYPES` in `documents/schemas.py` is the authority.

---

## Known open defects this slice must not walk into

From `docs/superpowers/specs/2026-08-07-slice-1a-residui.md` and `2026-08-06-slice-1b-residui.md`. Each entry below either constrains a task in this plan or is explicitly out of scope.

- **R1 — the MCP server shares one SQLAlchemy `Session` across concurrent calls.** Still open, still the first thing to fix on MCP. This slice's MCP tools (Task 15) add *more* traffic to that shared session, and `create_document_from_template` is a long call (a subprocess render) that will hold it far longer than any slice-1 tool did — which widens the window R1 describes. Task 15 therefore adds no new session handling of its own and changes nothing about `context.session`; it must not be read as having fixed R1, and the plan does not claim to.
- **R2 — the MCP SDK validates some arguments before `_guard` runs.** Task 15 uses the same `WithJsonSchema` technique already in `apps/mcp/src/pigrocrm_mcp/tools/__init__.py` for every strict scalar it introduces (`BoundedLimit` reused verbatim, and a new `OfferState` alias), so no new raw pydantic dump is added.
- **R5 — no audit trail for configuration.** This slice records timeline entries for every document and offer-state change (`ActivityService.record`, entity type `document`), so documents do not repeat the gap. Templates and the emitter profile are configuration and are recorded too, in Tasks 8 and 6 — cheap here, and it is the same gap R5 names.
- **R9 — sorting does not exist in either adapter.** Not fixed here. Document lists are ordered by `numero`/`created_at` server-side with no caller-supplied sort, so no half-feature is added.
- **A13 — a custom-field key can collide with a native column.** `FieldDefinitionService.create` still checks only other definitions, never `native_fields()`. Task 7 makes `document` a real entity type, so `native_fields("document")` starts returning `["customer_id", "deal_id", "tipo", "titolo", "stato"]` — five more names an administrator could slugify into by accident. The fix belongs to slice 1A and is not smuggled in here; instead Task 7's `DocumentCreate` keeps its native field names short and unambiguous, and the plan records that the collision remains reachable.
- **A14 — `exclude_none=True` means a typed native column cannot be cleared.** `DocumentUpdate` in Task 7 exposes only `titolo` (a text column, clearable with `""`) and `custom_fields`. `stato` is deliberately **not** on `DocumentUpdate`: it is changed only through `DocumentService.set_offer_state`, which takes a required, non-nullable literal. That removes the A14 shape from this slice's surface rather than reproducing it.
- **B1 — no automatic test on a hook called with an empty id.** Task 16's `useDocuments` is called with a `customerId` or a `dealId` that is always a real route param, and the hook takes a discriminated argument (`{customerId: string} | {dealId: string}`) so there is no "empty string" spelling to get wrong. Task 16 ships a test for it.

---

## Contradictions between the spec and the existing code, and how they were resolved

Resolved in favour of the existing code, as instructed. Each is implemented in the task named.

1. **`entity_type` is not open — it is a closed `Literal`.** Spec §4.1 says `document` is added "senza migrazione del validator né dello schema dei campi custom … Era il punto del disegno." The code says otherwise: `packages/core/src/pigrocrm/core/fields/schemas.py:12` declares `EntityType = Literal["customer", "person", "deal"]`, with the comment "Open by design: later slices append `document` and `invoice` with no schema change." "Open by design" meant *one line to append*, not *nothing to change*. **Resolution (Task 7):** append `"document"` to that `Literal`, to `ENTITY_TYPES` and `CREATE_MODELS` in `schema_registry.py`, and to `EntityType` in `apps/web/src/lib/schema.ts`. No database migration, no validator change — the spec's substantive claim holds; its literal claim does not.
2. **The spec says `enum`; the codebase has no `sa.Enum` anywhere.** Slice 1 spells every closed set as `String(n)` on the column plus a Pydantic `Literal` on the schema (`pipeline_stages.tipo` is `String(10)`, `PipelineStage.code` is `String(30)`). **Resolution (Task 7):** `documents.tipo` is `String(20)` and `documents.stato` is `String(20)`, each with a Pydantic `Literal`. A Postgres `ENUM` type would need its own `ALTER TYPE` migration for every future value; a `String` + `Literal` does not, and it matches every other closed set in the schema. The one `CheckConstraint` in this slice is the customer-or-deal exclusivity rule, which the spec names explicitly ("vincolo di check") and for which no existing convention competes.
3. **`DocumentStorage.put` returns `None`, but Google Drive returns a file id.** Spec §5's Protocol is kept byte-for-byte. **Resolution (Task 4/5):** `GDriveStorage` never needs to persist an id, because it *derives* the location from the key on every call — nested folders looked up by name under a configured root, exactly as Acme's `ensureDriveFolder`/`findDriveFileInFolder` do (`.reference-acme/website/vite.config.js:2527-2576`). The key is therefore a path, and `DocumentService.storage_key_for` builds it as `{ragione_sociale-slug}-{customer_id first 8 chars}/{document_id}/v{numero}.pdf`. The customer-id fragment is what keeps the folder stable when a customer is renamed, and the slug is what makes "chi migra da Acme ritrova le sue cartelle" true.
4. **The spec says Drive uses a service account; Acme uses an OAuth refresh-token flow** (`getGoogleAccessToken`, `.reference-acme/website/vite.config.js:2286`). The spec governs and a service account is the right choice for an unattended server. **Consequence recorded in Task 5:** a service account has no Drive storage quota of its own, so `PIGROCRM_GDRIVE_ROOT_FOLDER_ID` must name a folder on a **Shared Drive**, or one explicitly shared with the service account, or `files.create` fails with `storageQuotaExceeded`. Every Drive call therefore carries `supportsAllDrives=true`, as Acme's already do.
5. **Acme renders in one Pandoc invocation with `--pdf-engine=typst`; this slice runs the two stages separately.** Acme: `pandoc … --to=pdf --pdf-engine=typst` (`vite.config.js:2744-2762`). **Resolution (Task 10):** run `pandoc … --to=typst -o intermediate.typ`, then `typst compile intermediate.typ out.pdf`. Owning the intermediate `.typ` is the only way to satisfy spec §6's "l'errore che torna all'utente contiene la riga del template", because Typst's diagnostics name a line in that file and nothing else can map it back. This is a deliberate deviation from the carried-over pipeline, and it changes no output: the same template, the same header, the same engine.
6. **Acme escaped Typst-sensitive characters with a chain of `String.replace` calls** (`escapeTypstText`, `vite.config.js:71-77`, escaping `\ @ [ ] #`) applied uniformly regardless of destination. That is the design spec §3.3 rejects. **Resolution (Tasks 1–3):** escaping is a function of a parsed node's context. The character set is also widened past both Acme's five and the spec's seven — see Task 1's comments for each addition and why.
7. **`document_versions.creato_da` is `UUID` in the spec, but `Actor.id` is `UUID | None`** (`actor.py:22` — a `system` actor has no id). **Resolution (Task 7):** the column is nullable and is populated from `actor.id`. It is *not* validated as a foreign key on input, unlike every other FK in this slice, because no caller supplies it: it is read from the already-authenticated actor. That is the documented exception to the FK constraint above.

---

## File Structure

```
packages/core/src/pigrocrm/core/
├── fields/schemas.py                  # MODIFIED: EntityType gains "document"
├── schema_registry.py                 # MODIFIED: ENTITY_TYPES + CREATE_MODELS gain "document"
├── models_registry.py                 # MODIFIED: imports the four new models
├── config.py                          # MODIFIED: storage + render + gdrive settings
├── templates/                         # the engine — pure, no DB, no I/O
│   ├── escaping.py                    # escape_markdown / escape_typst / escape_url
│   ├── ast.py                         # Text · Variable · If · Each · RenderContext
│   ├── parser.py                      # segment() + parse_template()
│   ├── renderer.py                    # render_template() -> compiled Markdown
│   ├── models.py · schemas.py · repository.py · service.py    # the `templates` table
├── storage/
│   ├── base.py                        # DocumentStorage Protocol + validate_storage_key
│   ├── local.py                       # LocalFileStorage
│   ├── gdrive.py                      # GDriveStorage (service account, stdlib HTTP)
│   └── factory.py                     # storage_from_settings()
├── render/
│   ├── assets/                        # carried from Acme: pandoc-template.typst, header.typ.j2, media/
│   ├── pdf.py                         # render_pdf() — subprocess, list args, no shell
│   └── diagnostics.py                 # typst stderr -> template line
├── emitter/{models,schemas,repository,service}.py
├── documents/{models,schemas,repository,service}.py

packages/core/migrations/versions/
└── 0003_documents_templates_emitter.py

apps/api/src/pigrocrm_api/routers/
├── documents.py · templates.py · emitter.py      # new

apps/mcp/src/pigrocrm_mcp/tools/
└── documents.py                                   # new; registered from tools/__init__.py

apps/web/src/
├── lib/schema.ts                      # MODIFIED: EntityType gains 'document'
├── lib/query.ts                       # MODIFIED: document/template/emitter query keys
├── features/documents/{queries.ts,DocumentsTab.tsx,UploadDropzone.tsx,
│                      NewFromTemplateDialog.tsx,OfferStatePicker.tsx,VersionHistory.tsx}
├── features/settings/{TemplatesPanel.tsx,EmitterPanel.tsx}
└── routes/app/impostazioni/{template.tsx,emittente.tsx}
```

**Why these boundaries:** `templates/` is split into four files because the engine is the hard part and each piece has to be provable on its own — `escaping.py` is testable with no parser, `parser.py` with no renderer. `storage/` separates the Protocol from both implementations so the conformance suite in Task 5 can run the identical tests against each. `render/` is the only place in the codebase that spawns a process, and it is one file plus its diagnostics translator, so the "no user input on a command line" rule has exactly one file to hold.

---

# Phase 1 — The template engine

Three tasks, no database, no I/O. This phase is first because it is the part with no precedent in the codebase and the part the rest depends on.

### Task 1: Context-aware escaping

**Files:**
- Create: `packages/core/src/pigrocrm/core/templates/__init__.py`
- Create: `packages/core/src/pigrocrm/core/templates/escaping.py`
- Test: `packages/core/tests/test_template_escaping.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RenderContext = Literal["markdown", "typst", "url"]`
  - `escape_markdown(value: str) -> str`
  - `escape_typst(value: str) -> str`
  - `escape_url(value: str) -> str`
  - `escape_for(context: RenderContext, value: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_template_escaping.py
import pytest

from pigrocrm.core.templates.escaping import (
    escape_for,
    escape_markdown,
    escape_typst,
    escape_url,
)

# The two adversarial values the spec names (§3.3, "Test di accettazione"). Every
# assertion below is about one of these two reaching the page as the literal text
# somebody typed, in whichever of the two contexts it lands in.
TYPST_INJECTION = '#import "/etc/passwd"'
MARKDOWN_INJECTION = "**Grassetto** & <script>"


def test_markdown_escapes_emphasis_so_it_is_not_bold() -> None:
    assert escape_markdown(MARKDOWN_INJECTION) == r"\*\*Grassetto\*\* \& \<script\>"


def test_markdown_escapes_the_backslash_first_and_only_once() -> None:
    # If "\" were escaped after the others, the backslash this function itself
    # introduced would be escaped again and the output would double for every pass.
    assert escape_markdown(r"a\*b") == r"a\\\*b"


def test_markdown_escapes_hash_only_at_the_start_of_a_line() -> None:
    # A "#" mid-sentence is literal in Markdown; one at line start is a heading.
    assert escape_markdown("C# e #hashtag") == r"C# e #hashtag"
    assert escape_markdown("# Titolo") == r"\# Titolo"
    assert escape_markdown("prima\n## Sotto") == "prima\n" + r"\## Sotto"


def test_markdown_escapes_brackets_so_a_name_is_not_a_link() -> None:
    assert escape_markdown("[NOME](http://x)") == r"\[NOME\](http://x)"


def test_typst_escapes_hash_so_an_import_is_not_executed() -> None:
    assert escape_typst(TYPST_INJECTION) == r'\#import \"/etc/passwd\"'


def test_typst_escapes_at_dollar_and_angle_brackets() -> None:
    assert escape_typst("a@b $x$ <lab>") == r"a\@b \$x\$ \<lab\>"


def test_typst_escapes_brackets_that_would_close_a_content_block() -> None:
    # A raw {=typst} table cell is written as [ ... ]; an unbalanced "]" in a value
    # ends the cell early and the document stops compiling with a syntax error that
    # points at the template, not at the data.
    assert escape_typst("costo [IVA]") == r"costo \[IVA\]"


def test_typst_collapses_newlines_to_a_space() -> None:
    # A value lands inside a syntactic unit (a table cell, a header field). Keeping a
    # raw newline changes the layout of a document nobody proof-read; a space does not.
    assert escape_typst("riga1\nriga2") == "riga1 riga2"
    assert escape_typst("riga1\r\nriga2") == "riga1 riga2"


def test_typst_escapes_the_backslash_first_and_only_once() -> None:
    assert escape_typst(r"a\#b") == r"a\\\#b"


def test_url_percent_encodes_everything_unsafe() -> None:
    assert escape_url("a b/c?d=e&f") == "a%20b%2Fc%3Fd%3De%26f"
    assert escape_url(TYPST_INJECTION) == "%23import%20%22%2Fetc%2Fpasswd%22"


def test_escape_for_dispatches_on_context() -> None:
    assert escape_for("markdown", MARKDOWN_INJECTION) == escape_markdown(MARKDOWN_INJECTION)
    assert escape_for("typst", TYPST_INJECTION) == escape_typst(TYPST_INJECTION)
    assert escape_for("url", "a b") == escape_url("a b")


def test_escape_for_rejects_an_unknown_context() -> None:
    with pytest.raises(ValueError, match="contesto di escaping sconosciuto"):
        escape_for("latex", "x")  # type: ignore[arg-type]


def test_a_nul_byte_is_rejected_not_stripped_in_every_context() -> None:
    # Same rule as pigrocrm.core.validation.SafeStr: silently deleting one invisible
    # byte from a user's text is a lost character nobody notices.
    for escaper in (escape_markdown, escape_typst, escape_url):
        with pytest.raises(ValueError, match="carattere nullo"):
            escaper("a\x00b")


def test_escaping_is_idempotent_in_meaning_not_in_text() -> None:
    # Escaping twice must not silently produce the same string as escaping once --
    # if it did, a double-escape bug would be invisible. This test exists to make
    # that failure loud if anyone "optimises" the escapers into being idempotent.
    once = escape_markdown("*x*")
    assert escape_markdown(once) != once
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_template_escaping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.templates'`

- [ ] **Step 3: Write the implementation**

```python
# packages/core/src/pigrocrm/core/templates/__init__.py
```

(empty file)

```python
# packages/core/src/pigrocrm/core/templates/escaping.py
"""Escaping a value for the context it lands in, never once for the whole document.

The render is two-staged: a Markdown template becomes compiled Markdown, Pandoc turns
that into Typst, Typst composes the PDF. A value in an ordinary paragraph is escaped
for Markdown and Pandoc handles the Typst layer for it; a value inside a raw
`{=typst}` block is passed through by Pandoc untouched, so nothing but this module
stands between it and the compiler. Acme applied one uniform `escapeTypstText` to
everything (`website/vite.config.js:71-77`) and patched the character list each time a
new symbol broke a document -- the commit `fix(pdf): escape @ and other
typst-sensitive chars in placeholders` is that pattern in its final form. The fix is
not a longer list; it is knowing which list applies.
"""

import re
from typing import Literal
from urllib.parse import quote

RenderContext = Literal["markdown", "typst", "url"]

# Pandoc's Markdown accepts a backslash escape before any ASCII punctuation mark, so
# every character here becomes literal text rather than syntax.
#
# `&` is not in the spec's §3.3 list and is added deliberately: Pandoc reads `&amp;`
# as a character entity, so a customer whose name really contains the six characters
# `&amp;` would otherwise see a bare `&` in the PDF -- data quietly altered, which is
# the same class of defect as stripping a NUL byte.
#
# `#` is absent from this tuple on purpose: it is only syntax at the start of a line
# (an ATX heading) and is handled separately below, because escaping every `#` would
# turn "C#" into "C\#" in the output of engines less forgiving than Pandoc.
_MARKDOWN_SPECIALS: tuple[str, ...] = ("\\", "`", "*", "_", "[", "]", "<", ">", "&")

# Typst treats `\` followed by any non-alphanumeric character as that character
# literally, so the same one-backslash rule applies here.
#
# The spec's §3.3 list is `\ # $ @ " < >`. Four characters are added:
#   `[` `]` -- a raw {=typst} block in this project's own carried-over template writes
#             each table cell as `[...]` (see render/assets/template-offer.md, the
#             `#table(...)` block); an unbalanced bracket in a value closes the cell
#             early and the compile fails.
#   `*` `_` -- Typst's own strong/emphasis markers. Unescaped, a value containing them
#             renders bold inside a raw block, which is the Markdown bug one layer down.
# The backtick is added for the same reason as `*`: it opens a raw block in Typst markup.
_TYPST_SPECIALS: tuple[str, ...] = (
    "\\", "#", "$", "@", '"', "<", ">", "[", "]", "*", "_", "`",
)

# `re.fullmatch` is used everywhere in this project rather than `re.match` with `$`,
# because `$` matches before a trailing newline. Here the pattern is used with `sub`,
# where that distinction does not arise -- but the anchor is written `\Z`-free and
# line-anchored explicitly so nobody has to reason about it.
_LINE_LEADING_HASH = re.compile(r"^([ \t]*)#", re.MULTILINE)
_ANY_NEWLINE = re.compile(r"\r\n|\r|\n")


def _reject_nul(value: str) -> str:
    """Rejects, never strips -- the same decision `pigrocrm.core.validation.SafeStr`
    makes, for the same reason. A NUL byte here would also survive into a file this
    module writes and be handed to a subprocess."""
    if "\x00" in value:
        raise ValueError("il testo contiene un carattere nullo (\\x00), non ammesso")
    return value


def _escape_each(value: str, specials: tuple[str, ...]) -> str:
    """One pass over the *original* characters.

    Escaping character by character in a single loop is what makes the backslash
    rule work: each input `\\` becomes `\\\\`, and the backslashes this function
    itself emits are never re-examined. A chain of `str.replace` calls cannot do
    that -- whichever replacement runs second sees the first one's output -- which
    is why Acme's chain had to put `\\` first and could still be broken by adding a
    new rule above it.
    """
    marked = set(specials)
    return "".join("\\" + ch if ch in marked else ch for ch in value)


def escape_markdown(value: str) -> str:
    """For a placeholder that lands in ordinary Markdown body text."""
    escaped = _escape_each(_reject_nul(value), _MARKDOWN_SPECIALS)
    return _LINE_LEADING_HASH.sub(r"\1\\#", escaped)


def escape_typst(value: str) -> str:
    """For a placeholder that lands inside a raw ```{=typst} block or span.

    Newlines collapse to a single space: the value is landing inside a syntactic
    unit -- a table cell, a header field -- and a raw newline there changes the
    layout of a document nobody is going to proof-read before it is sent.
    """
    flattened = _ANY_NEWLINE.sub(" ", _reject_nul(value))
    return _escape_each(flattened, _TYPST_SPECIALS)


def escape_url(value: str) -> str:
    """For a placeholder that lands in a link or image destination.

    `safe=""` on purpose: a destination is a single opaque component here, so even
    `/` and `:` are encoded. A placeholder is never the whole URL in this project's
    templates -- it is always a path segment or a query value.
    """
    return quote(_reject_nul(value), safe="")


def escape_for(context: RenderContext, value: str) -> str:
    match context:
        case "markdown":
            return escape_markdown(value)
        case "typst":
            return escape_typst(value)
        case "url":
            return escape_url(value)
    raise ValueError(f"contesto di escaping sconosciuto: {context!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/core && uv run pytest tests/test_template_escaping.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `cd packages/core && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/templates packages/core/tests/test_template_escaping.py
git commit -m "feat(templates): context-aware escaping for markdown, typst and url"
```

### Task 2: The template parser — segmentation and the node tree

**Files:**
- Create: `packages/core/src/pigrocrm/core/templates/ast.py`
- Create: `packages/core/src/pigrocrm/core/templates/parser.py`
- Test: `packages/core/tests/test_template_parser.py`

**Interfaces:**
- Consumes: `RenderContext` from `pigrocrm.core.templates.escaping`.
- Produces:
  - `@dataclass(frozen=True) class TextNode: text: str`
  - `@dataclass(frozen=True) class VariableNode: path: tuple[str, ...]; context: RenderContext; line: int`
  - `@dataclass(frozen=True) class IfNode: path: tuple[str, ...]; line: int; then: tuple[Node, ...]; otherwise: tuple[Node, ...]`
  - `@dataclass(frozen=True) class EachNode: path: tuple[str, ...]; line: int; body: tuple[Node, ...]`
  - `Node = TextNode | VariableNode | IfNode | EachNode`
  - `@dataclass(frozen=True) class Segment: text: str; context: RenderContext; line: int`
  - `segment(source: str) -> tuple[Segment, ...]`
  - `parse_template(source: str) -> tuple[Node, ...]`
  - `declared_paths(nodes: tuple[Node, ...]) -> tuple[tuple[str, ...], ...]`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_template_parser.py
import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.ast import EachNode, IfNode, TextNode, VariableNode
from pigrocrm.core.templates.parser import declared_paths, parse_template, segment

TYPST_BLOCK_TEMPLATE = """Gentile {{cliente.ragione_sociale}},

```{=typst}
#table(
  columns: (0.8fr, 0.2fr),
  [{{riga.servizio}}],
  [{{riga.totale}}],
)
```

Cordiali saluti.
"""


def test_segment_marks_a_fenced_typst_block_as_typst_context() -> None:
    segments = segment(TYPST_BLOCK_TEMPLATE)
    contexts = [s.context for s in segments]
    assert "typst" in contexts
    typst_segment = next(s for s in segments if s.context == "typst")
    assert "#table(" in typst_segment.text
    assert "{{riga.servizio}}" in typst_segment.text


def test_segment_marks_everything_outside_a_fence_as_markdown() -> None:
    segments = segment(TYPST_BLOCK_TEMPLATE)
    markdown_text = "".join(s.text for s in segments if s.context == "markdown")
    assert "{{cliente.ragione_sociale}}" in markdown_text
    assert "#table(" not in markdown_text


def test_segment_marks_an_inline_typst_span_as_typst_context() -> None:
    segments = segment("prima `#emph[{{x}}]`{=typst} dopo")
    assert [(s.context, s.text) for s in segments] == [
        ("markdown", "prima "),
        ("typst", "`#emph[{{x}}]`{=typst}"),
        ("markdown", " dopo"),
    ]


def test_segment_marks_a_link_destination_as_url_context() -> None:
    segments = segment("vedi [il sito]({{cliente.sito_web}}) per i dettagli")
    assert [(s.context, s.text) for s in segments] == [
        ("markdown", "vedi [il sito"),
        ("url", "]({{cliente.sito_web}})"),
        ("markdown", " per i dettagli"),
    ]


def test_segment_records_the_line_each_segment_starts_on() -> None:
    segments = segment(TYPST_BLOCK_TEMPLATE)
    typst_segment = next(s for s in segments if s.context == "typst")
    # The fence opens on line 3 of TYPST_BLOCK_TEMPLATE.
    assert typst_segment.line == 3


def test_parse_gives_each_variable_the_context_of_its_segment() -> None:
    nodes = parse_template(TYPST_BLOCK_TEMPLATE)
    variables = {n.path: n.context for n in nodes if isinstance(n, VariableNode)}
    assert variables[("cliente", "ragione_sociale")] == "markdown"
    assert variables[("riga", "servizio")] == "typst"
    assert variables[("riga", "totale")] == "typst"


def test_the_same_placeholder_gets_two_different_contexts_in_two_places() -> None:
    # This is the single fact the whole engine exists for.
    source = "Nome: {{c.nome}}\n\n```{=typst}\n#text[{{c.nome}}]\n```\n"
    contexts = sorted(
        n.context for n in parse_template(source) if isinstance(n, VariableNode)
    )
    assert contexts == ["markdown", "typst"]


def test_parse_records_the_template_line_of_every_variable() -> None:
    nodes = parse_template("riga1\nriga2 {{a}}\nriga3\n")
    variable = next(n for n in nodes if isinstance(n, VariableNode))
    assert variable.line == 2


def test_parse_builds_an_if_node_with_both_branches() -> None:
    nodes = parse_template("{{#if offerta.iva}}con IVA{{else}}senza IVA{{/if}}")
    assert len(nodes) == 1
    node = nodes[0]
    assert isinstance(node, IfNode)
    assert node.path == ("offerta", "iva")
    assert node.then == (TextNode("con IVA"),)
    assert node.otherwise == (TextNode("senza IVA"),)


def test_parse_builds_an_if_node_with_no_else_branch() -> None:
    nodes = parse_template("{{#if x}}solo{{/if}}")
    node = nodes[0]
    assert isinstance(node, IfNode)
    assert node.otherwise == ()


def test_parse_builds_an_each_node_and_resolves_this() -> None:
    nodes = parse_template("{{#each righe}}{{this}}-{{nome}};{{/each}}")
    node = nodes[0]
    assert isinstance(node, EachNode)
    assert node.path == ("righe",)
    paths = [n.path for n in node.body if isinstance(n, VariableNode)]
    assert paths == [("this",), ("nome",)]


def test_parse_nests_blocks() -> None:
    nodes = parse_template("{{#each r}}{{#if r.iva}}X{{/if}}{{/each}}")
    outer = nodes[0]
    assert isinstance(outer, EachNode)
    assert isinstance(outer.body[0], IfNode)


def test_parse_rejects_an_unclosed_block_naming_the_line() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("prima\n{{#if x}}mai chiuso\n")
    assert excinfo.value.details["field"] == "corpo_markdown"
    assert "riga 2" in excinfo.value.details["reason"]
    assert "#if" in excinfo.value.details["reason"]


def test_parse_rejects_a_stray_closing_tag_naming_the_line() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("a\nb\n{{/each}}")
    assert "riga 3" in excinfo.value.details["reason"]


def test_parse_rejects_a_mismatched_closing_tag() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("{{#if x}}{{/each}}")
    assert "non corrisponde" in excinfo.value.details["reason"]


def test_parse_rejects_an_else_outside_an_if() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("{{else}}")
    assert "else" in excinfo.value.details["reason"]


@pytest.mark.parametrize(
    "bad",
    ["{{ }}", "{{1abc}}", "{{a..b}}", "{{a.}}", "{{a b}}", "{{a-b}}", "{{a\n}}"],
)
def test_parse_rejects_a_malformed_path(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        parse_template(bad)


def test_parse_rejects_a_helper_call_because_the_engine_has_no_helpers() -> None:
    # Deliberate: "un template e' un documento, non un programma" (spec 3.2).
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("{{uppercase cliente.nome}}")
    assert "non ammessa" in excinfo.value.details["reason"]


def test_declared_paths_collects_every_variable_once_in_order() -> None:
    nodes = parse_template("{{a.b}}{{#each r}}{{nome}}{{/each}}{{a.b}}{{c}}")
    assert declared_paths(nodes) == (("a", "b"), ("nome",), ("c",))


def test_a_template_with_no_placeholders_is_one_text_node() -> None:
    assert parse_template("solo testo") == (TextNode("solo testo"),)


def test_an_empty_template_parses_to_nothing() -> None:
    assert parse_template("") == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_template_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.templates.ast'`

- [ ] **Step 3: Write `ast.py`**

```python
# packages/core/src/pigrocrm/core/templates/ast.py
"""The parsed shape of a template.

Every node is frozen and carries the template line it came from. The line is what
turns "qualcosa e' andato storto" into "riga 42 del template": both the parser's own
syntax errors and, later, Typst's compile errors are reported against it.
"""

from dataclasses import dataclass

from pigrocrm.core.templates.escaping import RenderContext


@dataclass(frozen=True)
class TextNode:
    """Literal template text. Never escaped -- it is the author's own markup."""

    text: str


@dataclass(frozen=True)
class VariableNode:
    """A `{{path.to.value}}`.

    `context` is decided by the segment this placeholder was found in, not by
    guessing at render time. It is the whole point of parsing rather than replacing.
    """

    path: tuple[str, ...]
    context: RenderContext
    line: int


@dataclass(frozen=True)
class IfNode:
    path: tuple[str, ...]
    line: int
    then: tuple["Node", ...]
    otherwise: tuple["Node", ...]


@dataclass(frozen=True)
class EachNode:
    path: tuple[str, ...]
    line: int
    body: tuple["Node", ...]


Node = TextNode | VariableNode | IfNode | EachNode
```

- [ ] **Step 4: Write `parser.py`**

```python
# packages/core/src/pigrocrm/core/templates/parser.py
"""Segment first, then tokenise. Never a regex over the whole document at once.

Segmentation is what gives every placeholder its destination context. Tokenisation
runs *inside* a segment, so a placeholder cannot acquire the wrong escaping rule by
being near something else on the page.
"""

import re

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.ast import EachNode, IfNode, Node, TextNode, VariableNode
from pigrocrm.core.templates.escaping import RenderContext
from dataclasses import dataclass

ENTITY = "template"
FIELD = "corpo_markdown"

# The three regions that are not ordinary Markdown body text, in one alternation so a
# single left-to-right scan cannot produce overlapping or out-of-order segments:
#   fence  -- ```{=typst} ... ``` , Pandoc's raw-attribute block. DOTALL, and lazy, so
#             it stops at the first closing fence rather than the last one in the file.
#   inline -- `...`{=typst} , the span form of the same thing.
#   url    -- ](...) , a Markdown link or image destination.
_SEGMENT_RE = re.compile(
    r"(?P<fence>^```\{=typst\}[ \t]*\n.*?^```[ \t]*$)"
    r"|(?P<inline>`[^`\n]*`\{=typst\})"
    r"|(?P<url>\]\([^)\n]*\))",
    re.DOTALL | re.MULTILINE,
)

_TOKEN_RE = re.compile(r"\{\{(?P<body>.*?)\}\}", re.DOTALL)

# `re.fullmatch` against this, never `re.match` with `$`: `$` matches before a
# trailing newline, so `{{a\n}}` would be accepted as the path `a` and the newline
# would silently vanish. The project has already paid for that distinction once, on a
# 12-character P.IVA that reached Postgres as an uncaught DataError.
_PATH_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True)
class Segment:
    text: str
    context: RenderContext
    line: int


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _fail(line: int, reason: str, expected: str | None = None) -> None:
    raise ValidationFailed(ENTITY, FIELD, f"riga {line}: {reason}", expected=expected)


def segment(source: str) -> tuple[Segment, ...]:
    """Split `source` into typed regions, in order, covering it completely."""
    segments: list[Segment] = []
    cursor = 0
    for match in _SEGMENT_RE.finditer(source):
        if match.start() > cursor:
            segments.append(
                Segment(source[cursor : match.start()], "markdown", _line_of(source, cursor))
            )
        context: RenderContext = "url" if match.lastgroup == "url" else "typst"
        segments.append(Segment(match.group(0), context, _line_of(source, match.start())))
        cursor = match.end()
    if cursor < len(source):
        segments.append(Segment(source[cursor:], "markdown", _line_of(source, cursor)))
    return tuple(segments)


def _parse_path(raw: str, line: int) -> tuple[str, ...]:
    if not _PATH_RE.fullmatch(raw):
        _fail(
            line,
            f"percorso '{raw}' non valido",
            expected="un percorso puntato, es. cliente.ragione_sociale",
        )
    return tuple(raw.split("."))


class _Frame:
    """One open block on the stack, plus where its children accumulate."""

    def __init__(self, kind: str, path: tuple[str, ...], line: int) -> None:
        self.kind = kind
        self.path = path
        self.line = line
        self.children: list[Node] = []
        self.otherwise: list[Node] | None = None

    def emit(self, node: Node) -> None:
        (self.otherwise if self.otherwise is not None else self.children).append(node)


def parse_template(source: str) -> tuple[Node, ...]:
    """Parse a template into a node tree, or raise `ValidationFailed` naming the line."""
    root = _Frame("root", (), 1)
    stack: list[_Frame] = [root]

    for seg in segment(source):
        cursor = 0
        for match in _TOKEN_RE.finditer(seg.text):
            if match.start() > cursor:
                stack[-1].emit(TextNode(seg.text[cursor : match.start()]))
            line = seg.line + seg.text.count("\n", 0, match.start())
            body = match.group("body").strip()
            _consume_token(stack, body, line, seg.context)
            cursor = match.end()
        if cursor < len(seg.text):
            stack[-1].emit(TextNode(seg.text[cursor:]))

    if len(stack) > 1:
        open_frame = stack[-1]
        _fail(open_frame.line, f"blocco {{{{#{open_frame.kind}}}}} non chiuso")
    return tuple(root.children)


def _consume_token(stack: list[_Frame], body: str, line: int, context: RenderContext) -> None:
    """One `{{...}}`. Mutates `stack`; appends to the frame on top of it."""
    if body.startswith("#"):
        keyword, _, rest = body[1:].partition(" ")
        if keyword not in ("if", "each"):
            _fail(line, f"blocco '{keyword}' sconosciuto", expected="if oppure each")
        stack.append(_Frame(keyword, _parse_path(rest.strip(), line), line))
        return

    if body.startswith("/"):
        keyword = body[1:].strip()
        if len(stack) == 1:
            _fail(line, f"chiusura {{{{/{keyword}}}}} senza blocco aperto")
        frame = stack.pop()
        if frame.kind != keyword:
            _fail(line, f"{{{{/{keyword}}}}} non corrisponde a {{{{#{frame.kind}}}}}")
        node: Node = (
            IfNode(frame.path, frame.line, tuple(frame.children), tuple(frame.otherwise or ()))
            if frame.kind == "if"
            else EachNode(frame.path, frame.line, tuple(frame.children))
        )
        stack[-1].emit(node)
        return

    if body == "else":
        if len(stack) == 1 or stack[-1].kind != "if":
            _fail(line, "{{else}} fuori da un blocco {{#if}}")
        stack[-1].otherwise = []
        return

    # A space in the body would be a helper call -- `{{uppercase nome}}`. The engine
    # has none, by design: a template is a document, not a program, and an engine that
    # executes code inside a template is an attack surface this product has no reason
    # to have (spec 3.2).
    if " " in body or "\n" in body:
        _fail(
            line,
            f"sintassi '{body}' non ammessa: il motore non ha helper ne' espressioni",
            expected="un percorso puntato, es. cliente.ragione_sociale",
        )
    stack[-1].emit(VariableNode(_parse_path(body, line), context, line))


def declared_paths(nodes: tuple[Node, ...]) -> tuple[tuple[str, ...], ...]:
    """Every distinct variable path a template reads, in first-seen order.

    Used by `describe_template` so an agent can ask what a template wants *before*
    asking the user, and by the template service to check declared variables against
    what the body actually uses.
    """
    seen: list[tuple[str, ...]] = []

    def walk(items: tuple[Node, ...]) -> None:
        for node in items:
            match node:
                case VariableNode(path=path):
                    if path not in seen:
                        seen.append(path)
                case IfNode(then=then, otherwise=otherwise):
                    walk(then)
                    walk(otherwise)
                case EachNode(body=body):
                    walk(body)
                case TextNode():
                    pass

    walk(nodes)
    return tuple(seen)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd packages/core && uv run pytest tests/test_template_parser.py -v`
Expected: PASS

- [ ] **Step 6: Lint and type-check**

Run: `cd packages/core && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/templates packages/core/tests/test_template_parser.py
git commit -m "feat(templates): parser that segments by destination context"
```

---

### Task 3: The renderer — values in, compiled Markdown out

**Files:**
- Create: `packages/core/src/pigrocrm/core/templates/renderer.py`
- Test: `packages/core/tests/test_template_renderer.py`

**Interfaces:**
- Consumes: `parse_template`, `segment`, `Segment` from `pigrocrm.core.templates.parser`; `TextNode`, `VariableNode`, `IfNode`, `EachNode`, `Node` from `pigrocrm.core.templates.ast`; `escape_for` from `pigrocrm.core.templates.escaping`; `ValidationFailed` from `pigrocrm.core.errors`.
- Produces:
  - `TYPST_LINE_MARKER_PREFIX: str = "// pigrocrm:line="`
  - `@dataclass(frozen=True) class DeclaredVariable: nome: str; etichetta: str; tipo: str; obbligatoria: bool`
  - `render_template(source: str, values: dict[str, Any], declared: tuple[DeclaredVariable, ...] = ()) -> str`
  - `format_value(value: Any) -> str`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_template_renderer.py
from datetime import date
from decimal import Decimal

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.renderer import (
    TYPST_LINE_MARKER_PREFIX,
    DeclaredVariable,
    format_value,
    render_template,
)

TYPST_INJECTION = '#import "/etc/passwd"'
MARKDOWN_INJECTION = "**Grassetto** & <script>"

BOTH_CONTEXTS = """Spett.le **{{cliente.ragione_sociale}}**

```{=typst}
#table(
  columns: (0.8fr, 0.2fr),
  [{{cliente.ragione_sociale}}],
  [{{offerta.totale}}],
)
```
"""


def test_a_plain_variable_is_substituted() -> None:
    assert render_template("Ciao {{nome}}!", {"nome": "Ivan"}) == "Ciao Ivan!"


def test_a_dotted_path_walks_nested_dicts() -> None:
    out = render_template("{{cliente.sede.comune}}", {"cliente": {"sede": {"comune": "Milano"}}})
    assert out == "Milano"


def test_typst_injection_is_literal_text_in_the_markdown_context() -> None:
    out = render_template("Spett.le {{c}}", {"c": TYPST_INJECTION})
    # `#` is not at line start here, so only the quotes-free Markdown rules apply.
    assert out == 'Spett.le #import "/etc/passwd"'


def test_typst_injection_is_neutralised_in_the_typst_context() -> None:
    out = render_template("```{=typst}\n#text[{{c}}]\n```\n", {"c": TYPST_INJECTION})
    assert r"\#import" in out
    assert "\n#import" not in out


def test_markdown_injection_is_literal_text_in_the_markdown_context() -> None:
    out = render_template("Spett.le {{c}}", {"c": MARKDOWN_INJECTION})
    assert out == r"Spett.le \*\*Grassetto\*\* \& \<script\>"


def test_markdown_injection_is_neutralised_in_the_typst_context() -> None:
    out = render_template("```{=typst}\n#text[{{c}}]\n```\n", {"c": MARKDOWN_INJECTION})
    assert r"\*\*Grassetto\*\*" in out
    assert r"\<script\>" in out


def test_the_same_value_is_escaped_differently_in_the_two_contexts() -> None:
    # The acceptance test of spec 3.3, in one assertion.
    out = render_template(BOTH_CONTEXTS, {
        "cliente": {"ragione_sociale": TYPST_INJECTION},
        "offerta": {"totale": MARKDOWN_INJECTION},
    })
    markdown_part, typst_part = out.split("```{=typst}", 1)
    assert '#import "/etc/passwd"' in markdown_part     # markdown rules: # is not special mid-line
    assert r"\#import" in typst_part                     # typst rules: # is
    assert r"\*\*Grassetto\*\*" in typst_part            # and so is *


def test_a_typst_block_carries_a_line_marker_naming_its_template_line() -> None:
    out = render_template(BOTH_CONTEXTS, {
        "cliente": {"ragione_sociale": "ACME"},
        "offerta": {"totale": "100,00"},
    })
    assert f"{TYPST_LINE_MARKER_PREFIX}4" in out
    # The marker is the first line inside the fence, so Pandoc passes it through and
    # the line arithmetic in render/diagnostics.py holds.
    body = out.split("```{=typst}\n", 1)[1]
    assert body.splitlines()[0] == f"{TYPST_LINE_MARKER_PREFIX}4"


def test_if_renders_the_then_branch_when_truthy() -> None:
    assert render_template("{{#if iva}}con{{else}}senza{{/if}}", {"iva": True}) == "con"


def test_if_renders_the_else_branch_when_falsy() -> None:
    assert render_template("{{#if iva}}con{{else}}senza{{/if}}", {"iva": False}) == "senza"


@pytest.mark.parametrize("falsy", [False, None, "", [], {}, 0])
def test_if_treats_every_empty_shape_as_false(falsy: object) -> None:
    assert render_template("{{#if x}}s{{else}}n{{/if}}", {"x": falsy}) == "n"


def test_if_with_a_missing_path_takes_the_else_branch_rather_than_failing() -> None:
    # A conditional's whole job is to ask whether something is there.
    assert render_template("{{#if x}}s{{else}}n{{/if}}", {}) == "n"


def test_each_iterates_and_exposes_item_properties() -> None:
    out = render_template(
        "{{#each righe}}{{nome}}={{totale}};{{/each}}",
        {"righe": [{"nome": "A", "totale": "1"}, {"nome": "B", "totale": "2"}]},
    )
    assert out == "A=1;B=2;"


def test_each_exposes_this_for_a_list_of_scalars() -> None:
    assert render_template("{{#each r}}[{{this}}]{{/each}}", {"r": ["x", "y"]}) == "[x][y]"


def test_each_over_a_missing_or_empty_path_renders_nothing() -> None:
    assert render_template("a{{#each r}}X{{/each}}b", {}) == "ab"
    assert render_template("a{{#each r}}X{{/each}}b", {"r": []}) == "ab"


def test_each_falls_back_to_the_outer_scope_for_a_path_the_item_lacks() -> None:
    out = render_template(
        "{{#each r}}{{nome}}@{{azienda}};{{/each}}",
        {"azienda": "ACME", "r": [{"nome": "A"}, {"nome": "B"}]},
    )
    assert out == "A@ACME;B@ACME;"


def test_each_over_a_non_list_fails_naming_the_line() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        render_template("x\n{{#each r}}X{{/each}}", {"r": "non una lista"})
    assert "riga 2" in excinfo.value.details["reason"]
    assert "lista" in excinfo.value.details["reason"]


def test_an_unresolvable_variable_fails_naming_the_path_and_the_line() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        render_template("riga1\nriga2 {{cliente.inesistente}}", {"cliente": {}})
    assert "riga 2" in excinfo.value.details["reason"]
    assert "cliente.inesistente" in excinfo.value.details["reason"]


def test_a_missing_required_declared_variable_fails_before_rendering() -> None:
    declared = (
        DeclaredVariable(nome="oggetto", etichetta="Oggetto", tipo="text", obbligatoria=True),
    )
    with pytest.raises(ValidationFailed) as excinfo:
        render_template("{{oggetto}}", {}, declared)
    assert excinfo.value.details["field"] == "oggetto"
    assert "obbligatoria" in excinfo.value.details["reason"]


def test_a_missing_optional_declared_variable_renders_as_empty() -> None:
    declared = (
        DeclaredVariable(nome="note", etichetta="Note", tipo="text", obbligatoria=False),
    )
    assert render_template("[{{note}}]", {}, declared) == "[]"


def test_a_blank_string_does_not_satisfy_a_required_variable() -> None:
    declared = (
        DeclaredVariable(nome="oggetto", etichetta="Oggetto", tipo="text", obbligatoria=True),
    )
    with pytest.raises(ValidationFailed):
        render_template("{{oggetto}}", {"oggetto": "   "}, declared)


def test_false_and_zero_satisfy_a_required_variable() -> None:
    # Mirrors `is_blank` in fields/validator.py: False and 0 are values, not blanks.
    declared = (
        DeclaredVariable(nome="x", etichetta="X", tipo="checkbox", obbligatoria=True),
    )
    assert render_template("{{#if x}}s{{else}}n{{/if}}", {"x": False}, declared) == "n"
    assert render_template("{{x}}", {"x": 0}, declared) == "0"


def test_format_value_renders_money_as_a_decimal_string_never_a_float() -> None:
    assert format_value(Decimal("1234.56")) == "1234.56"
    assert format_value(Decimal("0.10")) == "0.10"


def test_format_value_renders_a_date_as_iso() -> None:
    assert format_value(date(2026, 8, 10)) == "2026-08-10"


def test_format_value_renders_booleans_in_italian() -> None:
    assert format_value(True) == "Si"
    assert format_value(False) == "No"


def test_format_value_renders_none_as_empty() -> None:
    assert format_value(None) == ""


def test_a_nul_byte_in_a_value_is_rejected() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        render_template("{{x}}", {"x": "a\x00b"})
    assert "carattere nullo" in excinfo.value.details["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_template_renderer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.templates.renderer'`

- [ ] **Step 3: Write the implementation**

```python
# packages/core/src/pigrocrm/core/templates/renderer.py
"""Walk the parsed tree, escaping each value for the context its node recorded.

The output is *compiled Markdown*, not a PDF: Pandoc and Typst are somebody else's
job (`pigrocrm.core.render.pdf`). Keeping this module free of I/O is what lets the
adversarial escaping cases be tested as pure string comparisons, with no container,
no subprocess and no PDF to parse.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.ast import EachNode, IfNode, Node, TextNode, VariableNode
from pigrocrm.core.templates.escaping import escape_for
from pigrocrm.core.templates.parser import parse_template

ENTITY = "template"
FIELD = "corpo_markdown"

# Emitted as the first line inside every raw ```{=typst} block. Pandoc copies a raw
# block through verbatim, line for line, so this comment survives into the
# intermediate .typ -- which is what lets `render/diagnostics.py` turn "error at
# intermediate.typ:57" into "riga 12 del template" by arithmetic rather than by
# guessing. `//` is a Typst comment and produces no output.
TYPST_LINE_MARKER_PREFIX = "// pigrocrm:line="

_FENCE_OPEN = "```{=typst}\n"


@dataclass(frozen=True)
class DeclaredVariable:
    """One entry of a template's `variabili_dichiarate`.

    Declared, not deduced (spec 4.3): the compilation form shows label, type and
    whether it is required, and the render fails with a precise error if a required
    one is missing -- instead of producing a PDF with a hole in it.

    `tipo` is one of the nine `FieldType` values in fields/types.py, so the frontend
    can render it with the existing `DynamicFieldRenderer` and nothing new has to
    learn a tenth type.
    """

    nome: str
    etichetta: str
    tipo: str
    obbligatoria: bool


def _is_blank(value: Any) -> bool:
    """Mirrors `pigrocrm.core.fields.validator.is_blank` exactly.

    Deliberately re-stated rather than imported: importing it would tie this pure,
    database-free module to the custom-fields subsystem for four lines. The rule that
    matters -- `False` and `0` are values, not blanks -- is identical, and
    `test_false_and_zero_satisfy_a_required_variable` fails loudly if the two ever
    disagree.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def format_value(value: Any) -> str:
    """A value as text, before escaping.

    `Decimal` is formatted with `str`, never `float`: a binary float cannot represent
    1234.56 exactly, and the drift is a bug the moment it reaches an offer. The same
    rule the `Numeric(12, 2)` columns exist for.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _resolve(path: tuple[str, ...], scopes: list[dict[str, Any]]) -> tuple[bool, Any]:
    """Walk `path` against the innermost scope that has its first segment.

    Returns `(found, value)` rather than raising, because `#if` and `#each` treat a
    missing path as "nothing here" while a bare variable treats it as an error, and
    only the caller knows which of the two it is.
    """
    for scope in reversed(scopes):
        if path[0] not in scope:
            continue
        current: Any = scope[path[0]]
        for part in path[1:]:
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
        return True, current
    return False, None


def _check_declared(declared: tuple[DeclaredVariable, ...], values: dict[str, Any]) -> None:
    for variable in declared:
        if variable.obbligatoria and _is_blank(values.get(variable.nome)):
            raise ValidationFailed(
                ENTITY,
                variable.nome,
                f"variabile obbligatoria mancante: {variable.etichetta}",
                expected="un valore non vuoto",
            )


def render_template(
    source: str,
    values: dict[str, Any],
    declared: tuple[DeclaredVariable, ...] = (),
) -> str:
    """Compile `source` with `values`. Raises `ValidationFailed` naming the template line."""
    _check_declared(declared, values)
    nodes = parse_template(source)
    optional_defaults = {v.nome: "" for v in declared if not v.obbligatoria}
    scopes: list[dict[str, Any]] = [{**optional_defaults, **values}]
    out: list[str] = []
    _render_nodes(nodes, scopes, out)
    return "".join(out)


def _render_nodes(nodes: tuple[Node, ...], scopes: list[dict[str, Any]], out: list[str]) -> None:
    for node in nodes:
        match node:
            case TextNode(text=text):
                out.append(_with_line_marker(text) if _FENCE_OPEN in text else text)
            case VariableNode(path=path, context=context, line=line):
                out.append(_render_variable(path, context, line, scopes))
            case IfNode(path=path, then=then, otherwise=otherwise):
                found, value = _resolve(path, scopes)
                _render_nodes(then if found and not _is_blank(value) else otherwise, scopes, out)
            case EachNode(path=path, line=line, body=body):
                _render_each(path, line, body, scopes, out)


def _render_variable(
    path: tuple[str, ...], context: str, line: int, scopes: list[dict[str, Any]]
) -> str:
    found, value = _resolve(path, scopes)
    if not found:
        raise ValidationFailed(
            ENTITY,
            FIELD,
            f"riga {line}: variabile '{'.'.join(path)}' non risolta",
            expected="una variabile dichiarata dal template",
        )
    try:
        return escape_for(context, format_value(value))  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValidationFailed(
            ENTITY, FIELD, f"riga {line}: {exc}", expected="testo senza caratteri di controllo"
        ) from exc


def _render_each(
    path: tuple[str, ...],
    line: int,
    body: tuple[Node, ...],
    scopes: list[dict[str, Any]],
    out: list[str],
) -> None:
    found, value = _resolve(path, scopes)
    if not found or value is None:
        return
    if not isinstance(value, (list, tuple)):
        raise ValidationFailed(
            ENTITY,
            FIELD,
            f"riga {line}: '{'.'.join(path)}' non e' una lista",
            expected="una lista di elementi",
        )
    for item in value:
        # `this` is the item itself; a dict item's own keys also become a scope, so
        # `{{nome}}` inside `{{#each righe}}` reads the row's `nome` and falls back to
        # the outer scope when the row has none.
        frame: dict[str, Any] = {"this": item}
        if isinstance(item, dict):
            frame.update(item)
        scopes.append(frame)
        try:
            _render_nodes(body, scopes, out)
        finally:
            scopes.pop()


def _with_line_marker(text: str) -> str:
    """Insert `// pigrocrm:line=<N>` as the first line inside every raw typst fence.

    `text` is a `TextNode` produced from a typst segment, so it starts at the fence
    and the fence's own template line is recoverable from how many newlines precede
    it in the fully rendered document -- except the renderer does not know that yet.
    What it does know is the parser's own line numbering, carried on the segment; the
    parser therefore prefixes the marker at parse time for a fence with no
    placeholders in it too. See `parser.segment` for the segment boundaries this
    relies on.
    """
    head, _, rest = text.partition(_FENCE_OPEN)
    if not rest:
        return text
    line = head.count("\n") + 1
    return f"{head}{_FENCE_OPEN}{TYPST_LINE_MARKER_PREFIX}{line}\n{rest}"
```

- [ ] **Step 4: Move the line marker into the parser so it is computed from real template lines**

`_with_line_marker` above can only count the newlines it can see, which is wrong for any fence that is not the first thing in the template. Replace it with a marker emitted by the parser, which knows the true line. Edit `packages/core/src/pigrocrm/core/templates/parser.py`, in `parse_template`, replacing the segment loop's first `TextNode` emission:

```python
    for seg in segment(source):
        # A raw typst fence gets a `// pigrocrm:line=<N>` comment as the first line of
        # its body. Pandoc copies a raw block through verbatim, so the marker reaches
        # the intermediate .typ and `render/diagnostics.py` can map a compiler error
        # back to this exact template line by arithmetic. Done here, not in the
        # renderer, because this is the only place the true template line is known.
        text = seg.text
        if seg.context == "typst" and text.startswith("```{=typst}\n"):
            body_line = seg.line + 1
            text = text.replace(
                "```{=typst}\n", f"```{{=typst}}\n// pigrocrm:line={body_line}\n", 1
            )
        cursor = 0
        for match in _TOKEN_RE.finditer(text):
            if match.start() > cursor:
                stack[-1].emit(TextNode(text[cursor : match.start()]))
            line = seg.line + text.count("\n", 0, match.start())
            body = match.group("body").strip()
            _consume_token(stack, body, line, seg.context)
            cursor = match.end()
        if cursor < len(text):
            stack[-1].emit(TextNode(text[cursor:]))
```

Note the line arithmetic: inserting the marker adds one line *before* every placeholder in the block, so `seg.line + text.count(...)` would over-count by one for placeholders inside a fence. Compensate by subtracting the inserted line:

```python
            offset = 1 if (seg.context == "typst" and text != seg.text) else 0
            line = seg.line + text.count("\n", 0, match.start()) - offset
```

Then delete `_with_line_marker` and its call from `renderer.py`, so `TextNode` is emitted verbatim:

```python
            case TextNode(text=text):
                out.append(text)
```

- [ ] **Step 5: Run both engine test files to verify they pass**

Run: `cd packages/core && uv run pytest tests/test_template_parser.py tests/test_template_renderer.py -v`
Expected: PASS

- [ ] **Step 6: Lint and type-check**

Run: `cd packages/core && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/templates packages/core/tests/test_template_renderer.py
git commit -m "feat(templates): renderer with per-context escaping and typst line markers"
```

---

# Phase 2 — Pluggable storage

The interface comes before either implementation, and the conformance suite is written once and run against both — spec §11 criterion 5 ("i test lo dimostrano girando su entrambi").

### Task 4: The `DocumentStorage` protocol and `LocalFileStorage`

**Files:**
- Create: `packages/core/src/pigrocrm/core/storage/__init__.py`
- Create: `packages/core/src/pigrocrm/core/storage/base.py`
- Create: `packages/core/src/pigrocrm/core/storage/local.py`
- Test: `packages/core/tests/test_storage_local.py`

**Interfaces:**
- Consumes: `NotFound`, `ValidationFailed` from `pigrocrm.core.errors`.
- Produces:
  - `class DocumentStorage(Protocol)` with `put(self, key: str, data: bytes, content_type: str) -> None`, `get(self, key: str) -> bytes`, `delete(self, key: str) -> None`, `signed_url(self, key: str, ttl: timedelta) -> str | None`
  - `validate_storage_key(key: str) -> str`
  - `MAX_KEY_LENGTH: int = 255`
  - `class LocalFileStorage:` with `__init__(self, root: Path) -> None` and the four Protocol methods
- Re-exported from `pigrocrm.core.storage`: `DocumentStorage`, `LocalFileStorage`, `validate_storage_key`, `MAX_KEY_LENGTH`.

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_storage_local.py
from datetime import timedelta
from pathlib import Path

import pytest

from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.storage import LocalFileStorage, validate_storage_key

PDF = b"%PDF-1.7\nfinto\n"
KEY = "acme-01234567/0199abcd/v1.pdf"


def test_put_then_get_round_trips_the_bytes(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put(KEY, PDF, "application/pdf")
    assert storage.get(KEY) == PDF


def test_put_creates_the_nested_directories(tmp_path: Path) -> None:
    LocalFileStorage(tmp_path).put(KEY, PDF, "application/pdf")
    assert (tmp_path / KEY).is_file()


def test_put_overwrites_an_existing_key(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put(KEY, PDF, "application/pdf")
    storage.put(KEY, b"nuovo", "application/pdf")
    assert storage.get(KEY) == b"nuovo"


def test_put_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    # The write is atomic (write to .tmp, then os.replace) so a crash mid-write can
    # never leave a half-written PDF readable under the real key.
    LocalFileStorage(tmp_path).put(KEY, PDF, "application/pdf")
    assert [p.name for p in (tmp_path / "acme-01234567" / "0199abcd").iterdir()] == ["v1.pdf"]


def test_get_of_a_missing_key_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFound) as excinfo:
        LocalFileStorage(tmp_path).get(KEY)
    assert excinfo.value.details["entity"] == "document_blob"


def test_delete_removes_the_file(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put(KEY, PDF, "application/pdf")
    storage.delete(KEY)
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_delete_of_a_missing_key_is_silent(tmp_path: Path) -> None:
    # Delete is idempotent: a retried request must not fail because the first attempt
    # already succeeded.
    LocalFileStorage(tmp_path).delete(KEY)


def test_signed_url_is_none_because_authorisation_lives_in_the_api(tmp_path: Path) -> None:
    assert LocalFileStorage(tmp_path).signed_url(KEY, timedelta(minutes=5)) is None


@pytest.mark.parametrize(
    "bad",
    [
        "../fuori.pdf",
        "a/../../fuori.pdf",
        "/assoluto.pdf",
        "a//b.pdf",
        "",
        " ",
        "a\x00b.pdf",
        "a/b\\c.pdf",
        "x" * 256,
        "-inizia-con-trattino.pdf",
    ],
)
def test_an_unsafe_key_is_refused_before_any_filesystem_call(bad: str) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        validate_storage_key(bad)
    assert excinfo.value.details["field"] == "storage_key"


@pytest.mark.parametrize("good", ["a.pdf", "a/b.pdf", "acme-01/0199ab/v12.pdf", "A_b.C-1/x.pdf"])
def test_a_safe_key_is_accepted(good: str) -> None:
    assert validate_storage_key(good) == good


def test_traversal_is_refused_by_put_and_get_and_delete(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    for call in (
        lambda: storage.put("../escape.pdf", PDF, "application/pdf"),
        lambda: storage.get("../escape.pdf"),
        lambda: storage.delete("../escape.pdf"),
    ):
        with pytest.raises(ValidationFailed):
            call()
    assert not (tmp_path.parent / "escape.pdf").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_storage_local.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.storage'`

- [ ] **Step 3: Write `base.py`**

```python
# packages/core/src/pigrocrm/core/storage/base.py
"""One interface, two implementations. The metadata always lives in Postgres.

Search, permissions, timeline and versions work identically on both backends, and
changing backend loses nothing but the bytes already uploaded -- for which an explicit
migration is needed, not a change of environment variable (spec 5).
"""

import re
from datetime import timedelta
from typing import Protocol

from pigrocrm.core.errors import ValidationFailed

MAX_KEY_LENGTH = 255

# A key is a relative POSIX-style path: segments of `[A-Za-z0-9._-]`, separated by a
# single `/`, each segment starting with an alphanumeric. `re.fullmatch` below, never
# `re.match` with `$`, because `$` matches before a trailing newline -- which would let
# "a.pdf\n" through and reach the filesystem, and reach the `String(255)` column, as
# something neither had agreed to.
_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")


def validate_storage_key(key: str) -> str:
    """The one gate every backend calls before touching anything.

    Checked here rather than inside each implementation so `LocalFileStorage` and
    `GDriveStorage` cannot drift: a key that is safe for one and not the other is a
    key that is not safe.

    `".."` is refused explicitly on top of the pattern. The pattern alone already
    rejects it (a segment must start with an alphanumeric), but a future widening of
    the character class would silently reopen path traversal, and this line will
    still be here.
    """
    if not _KEY_RE.fullmatch(key) or len(key) > MAX_KEY_LENGTH or ".." in key:
        raise ValidationFailed(
            "document_version",
            "storage_key",
            "chiave di storage non valida",
            expected="segmenti alfanumerici separati da '/', max 255 caratteri",
        )
    return key


class DocumentStorage(Protocol):
    """`signed_url` returns `None` on a backend that has no such concept.

    On `LocalFileStorage` that is the whole design: the download goes through the
    API, which is the only place authorisation exists.
    """

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def signed_url(self, key: str, ttl: timedelta) -> str | None: ...
```

- [ ] **Step 4: Write `local.py` and the package export**

```python
# packages/core/src/pigrocrm/core/storage/local.py
"""The default backend. A directory on disk, and no external dependency at all --
which is what makes the product genuinely self-hostable (spec 5)."""

import os
from datetime import timedelta
from pathlib import Path

from pigrocrm.core.errors import NotFound
from pigrocrm.core.storage.base import validate_storage_key


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / validate_storage_key(key)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """`content_type` is accepted and ignored: a filesystem has no place to record
        it, and the authoritative copy is `document_versions.content_type` in Postgres
        -- which is where every reader already looks. Storing it in a sidecar file
        would create a second answer that can disagree with the first."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: os.replace is atomic on the same filesystem, so a crash
        # mid-write can never leave a truncated PDF readable under the real key.
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise NotFound("document_blob", key) from exc

    def delete(self, key: str) -> None:
        """Idempotent: a retried request must not fail because the first one worked."""
        self._path(key).unlink(missing_ok=True)

    def signed_url(self, key: str, ttl: timedelta) -> str | None:
        """Always `None`. The download passes through the API, which is the only place
        authorisation exists (spec 5)."""
        validate_storage_key(key)
        return None
```

```python
# packages/core/src/pigrocrm/core/storage/__init__.py
from pigrocrm.core.storage.base import (
    MAX_KEY_LENGTH,
    DocumentStorage,
    validate_storage_key,
)
from pigrocrm.core.storage.local import LocalFileStorage

__all__ = [
    "MAX_KEY_LENGTH",
    "DocumentStorage",
    "LocalFileStorage",
    "validate_storage_key",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd packages/core && uv run pytest tests/test_storage_local.py -v`
Expected: PASS

- [ ] **Step 6: Lint and type-check**

Run: `cd packages/core && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/storage packages/core/tests/test_storage_local.py
git commit -m "feat(storage): DocumentStorage protocol and LocalFileStorage"
```

---

### Task 5: `GDriveStorage`, and one conformance suite run against both backends

**Files:**
- Create: `packages/core/src/pigrocrm/core/storage/gdrive.py`
- Create: `packages/core/src/pigrocrm/core/storage/factory.py`
- Create: `packages/core/tests/test_storage_conformance.py`
- Create: `packages/core/tests/fakes/fake_drive.py`
- Create: `packages/core/tests/fakes/__init__.py`
- Modify: `packages/core/src/pigrocrm/core/storage/__init__.py`
- Modify: `packages/core/src/pigrocrm/core/config.py`
- Modify: `packages/core/pyproject.toml:5-15` (`pyjwt` gains the `crypto` extra)

**Interfaces:**
- Consumes: `DocumentStorage`, `validate_storage_key` from `pigrocrm.core.storage.base`; `LocalFileStorage` from `pigrocrm.core.storage.local`; `Settings` from `pigrocrm.core.config`.
- Produces:
  - `class GDriveStorage:` with `__init__(self, *, service_account_json: str, root_folder_id: str, http: HttpCall | None = None) -> None` and the four Protocol methods
  - `HttpCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]` — `(method, url, headers, body) -> (status, body)`
  - `storage_from_settings(settings: Settings) -> DocumentStorage`
  - New settings on `Settings`: `storage_backend: Literal["local", "gdrive"] = "local"`, `storage_local_root: str = "./var/documents"`, `gdrive_service_account_json: str = ""`, `gdrive_root_folder_id: str = ""`

- [ ] **Step 1: Write the failing conformance test and the fake Drive**

```python
# packages/core/tests/fakes/__init__.py
```

(empty file)

```python
# packages/core/tests/fakes/fake_drive.py
"""An in-memory Google Drive that speaks the same HTTP surface `GDriveStorage` uses.

Deliberately a fake of the *transport*, not of `GDriveStorage` itself: the URL
building, the query escaping, the multipart body and the error handling are exactly
the parts most likely to be wrong, so they must run for real. What it replaces is the
network, nothing above it.

The API surface it implements is the one Acme proved it needs
(.reference-acme/website/vite.config.js:2527-2647): files.list with a `q` filter,
files.create for a folder, multipart upload, media download, and delete -- all with
`supportsAllDrives=true`, because a service account's files live on a Shared Drive.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass
class _File:
    id: str
    name: str
    parent: str
    mime: str
    data: bytes = b""


@dataclass
class FakeDrive:
    root_id: str = "ROOT"
    files: dict[str, _File] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    next_id: int = 1
    token_requests: int = 0
    fail_next_with: int | None = None

    def _new_id(self) -> str:
        self.next_id += 1
        return f"id{self.next_id}"

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        self.calls.append((method, url))
        if self.fail_next_with is not None:
            status, self.fail_next_with = self.fail_next_with, None
            return status, json.dumps({"error": {"message": "boom"}}).encode()
        parsed = urlparse(url)
        if parsed.netloc == "oauth2.googleapis.com":
            self.token_requests += 1
            return 200, json.dumps({"access_token": "at-1", "expires_in": 3600}).encode()
        query = parse_qs(parsed.query)
        if method == "GET" and parsed.path.endswith("/files") and "q" in query:
            return self._list(query["q"][0])
        if method == "GET" and query.get("alt") == ["media"]:
            return self._download(parsed.path)
        if method == "POST" and "upload" in parsed.path:
            return self._upload(headers, body or b"")
        if method == "POST" and parsed.path.endswith("/files"):
            return self._create_folder(json.loads((body or b"{}").decode()))
        if method == "DELETE":
            self.files.pop(parsed.path.rsplit("/", 1)[-1], None)
            return 204, b""
        return 404, json.dumps({"error": {"message": f"unhandled {method} {url}"}}).encode()

    def _list(self, q: str) -> tuple[int, bytes]:
        name = re.search(r"name='((?:[^'\\]|\\.)*)'", q)
        parent = re.search(r"'([^']+)' in parents", q)
        assert name and parent, q
        wanted = name.group(1).replace("\\'", "'")
        matches = [
            {"id": f.id, "name": f.name}
            for f in self.files.values()
            if f.name == wanted
            and f.parent == parent.group(1)
            and (FOLDER_MIME in q) == (f.mime == FOLDER_MIME)
        ]
        return 200, json.dumps({"files": matches}).encode()

    def _create_folder(self, payload: dict[str, Any]) -> tuple[int, bytes]:
        new = _File(self._new_id(), payload["name"], payload["parents"][0], FOLDER_MIME)
        self.files[new.id] = new
        return 200, json.dumps({"id": new.id, "name": new.name}).encode()

    def _upload(self, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        boundary = re.search(r'boundary="?([^";]+)"?', headers["Content-Type"])
        assert boundary, headers
        parts = body.split(b"--" + boundary.group(1).encode())
        metadata = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n").decode())
        data = parts[2].split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n")
        existing = [
            f
            for f in self.files.values()
            if f.name == metadata["name"] and f.parent == metadata["parents"][0]
        ]
        if existing:
            existing[0].data = data
            return 200, json.dumps({"id": existing[0].id}).encode()
        new = _File(self._new_id(), metadata["name"], metadata["parents"][0], "application/pdf", data)
        self.files[new.id] = new
        return 200, json.dumps({"id": new.id}).encode()

    def _download(self, path: str) -> tuple[int, bytes]:
        file_id = path.rsplit("/", 1)[-1]
        found = self.files.get(file_id)
        return (200, found.data) if found else (404, b'{"error":{"message":"not found"}}')
```

```python
# packages/core/tests/test_storage_conformance.py
"""The same suite against both backends -- spec 11 criterion 5.

Switching `LocalFileStorage` for `GDriveStorage` must require no change to any
service's code, and this file is the proof: every test below is parametrised over
both, and nothing in it names either one except the fixture that builds it.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.storage import DocumentStorage, GDriveStorage, LocalFileStorage
from tests.fakes.fake_drive import FakeDrive

PDF = b"%PDF-1.7\nfinto\n"
KEY = "acme-01234567/0199abcd/v1.pdf"

# A real RSA key is not needed: the fake transport answers the token endpoint without
# verifying the assertion, and `GDriveStorage` is injected with a signer in the tests
# so no private key material appears in this repository at all.
SERVICE_ACCOUNT_JSON = (
    '{"type":"service_account","client_email":"pigro@example.iam.gserviceaccount.com",'
    '"private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n",'
    '"token_uri":"https://oauth2.googleapis.com/token"}'
)


@pytest.fixture(params=["local", "gdrive"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> DocumentStorage:
    if request.param == "local":
        return LocalFileStorage(tmp_path)
    drive = FakeDrive()
    made = GDriveStorage(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id=drive.root_id,
        http=drive,
        sign_assertion=lambda claims: "assertion",
    )
    request.node.stash["drive"] = drive  # type: ignore[index]
    return made


def test_put_then_get_round_trips(storage: DocumentStorage) -> None:
    storage.put(KEY, PDF, "application/pdf")
    assert storage.get(KEY) == PDF


def test_put_twice_overwrites_rather_than_duplicating(storage: DocumentStorage) -> None:
    storage.put(KEY, PDF, "application/pdf")
    storage.put(KEY, b"nuovo", "application/pdf")
    assert storage.get(KEY) == b"nuovo"


def test_get_of_a_missing_key_raises_not_found(storage: DocumentStorage) -> None:
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_delete_then_get_raises_not_found(storage: DocumentStorage) -> None:
    storage.put(KEY, PDF, "application/pdf")
    storage.delete(KEY)
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_delete_of_a_missing_key_is_silent(storage: DocumentStorage) -> None:
    storage.delete(KEY)


def test_two_keys_under_the_same_folder_do_not_collide(storage: DocumentStorage) -> None:
    storage.put("acme-0123/doc/v1.pdf", b"uno", "application/pdf")
    storage.put("acme-0123/doc/v2.pdf", b"due", "application/pdf")
    assert storage.get("acme-0123/doc/v1.pdf") == b"uno"
    assert storage.get("acme-0123/doc/v2.pdf") == b"due"


def test_an_unsafe_key_is_refused_by_every_backend(storage: DocumentStorage) -> None:
    with pytest.raises(ValidationFailed):
        storage.put("../fuori.pdf", PDF, "application/pdf")


def test_signed_url_is_either_none_or_a_https_url(storage: DocumentStorage) -> None:
    storage.put(KEY, PDF, "application/pdf")
    url = storage.signed_url(KEY, timedelta(minutes=5))
    assert url is None or url.startswith("https://")


# --- Drive-only behaviour, tested through the same public surface -------------------


def _drive_storage() -> tuple[GDriveStorage, FakeDrive]:
    drive = FakeDrive()
    return (
        GDriveStorage(
            service_account_json=SERVICE_ACCOUNT_JSON,
            root_folder_id=drive.root_id,
            http=drive,
            sign_assertion=lambda claims: "assertion",
        ),
        drive,
    )


def test_drive_creates_one_folder_per_key_segment() -> None:
    storage, drive = _drive_storage()
    storage.put(KEY, PDF, "application/pdf")
    names = sorted(f.name for f in drive.files.values())
    assert names == ["0199abcd", "acme-01234567", "v1.pdf"]


def test_drive_reuses_an_existing_folder_instead_of_creating_a_second() -> None:
    # "chi migra da Acme ritrova le sue cartelle" (spec 5) only holds if a second
    # upload finds the folder the first one made.
    storage, drive = _drive_storage()
    storage.put("acme-0123/doc/v1.pdf", b"uno", "application/pdf")
    storage.put("acme-0123/doc/v2.pdf", b"due", "application/pdf")
    assert sorted(f.name for f in drive.files.values()) == ["acme-0123", "doc", "v1.pdf", "v2.pdf"]


def test_drive_asks_for_an_access_token_once_and_reuses_it() -> None:
    storage, drive = _drive_storage()
    storage.put("a/b.pdf", PDF, "application/pdf")
    storage.get("a/b.pdf")
    assert drive.token_requests == 1


def test_drive_sends_supports_all_drives_on_every_call() -> None:
    # A service account has no Drive quota of its own, so the root folder must be on a
    # Shared Drive -- and every request has to say it can handle one.
    storage, drive = _drive_storage()
    storage.put(KEY, PDF, "application/pdf")
    api_calls = [url for _, url in drive.calls if "googleapis.com" in url]
    assert api_calls and all("supportsAllDrives=true" in url for url in api_calls)


def test_drive_escapes_a_quote_in_a_folder_name_in_the_q_filter() -> None:
    # A customer called   Bar 'da Gino'   would otherwise break the query and, worse,
    # let a name terminate the filter early.
    storage, drive = _drive_storage()
    storage.put("bar-d.gino-01/doc/v1.pdf", PDF, "application/pdf")
    assert storage.get("bar-d.gino-01/doc/v1.pdf") == PDF


def test_drive_turns_a_transport_failure_into_a_domain_conflict() -> None:
    storage, drive = _drive_storage()
    drive.fail_next_with = 403
    with pytest.raises(Conflict) as excinfo:
        storage.put(KEY, PDF, "application/pdf")
    assert excinfo.value.details["entity"] == "document_blob"
    assert "403" in excinfo.value.details["reason"]


def test_drive_signed_url_is_none_so_downloads_stay_behind_the_api() -> None:
    # Drive *can* mint a link, but a link that outlives a permission check is a leak
    # nobody revokes. The API is the only place authorisation exists (spec 5).
    storage, _ = _drive_storage()
    assert storage.signed_url(KEY, timedelta(minutes=5)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_storage_conformance.py -v`
Expected: FAIL with `ImportError: cannot import name 'GDriveStorage' from 'pigrocrm.core.storage'`

- [ ] **Step 3: Add the `crypto` extra to PyJWT**

Edit `packages/core/pyproject.toml`, replacing the `"pyjwt==2.13.0",` line inside `[project].dependencies`:

```toml
  # The `crypto` extra pulls in `cryptography`, needed for the RS256 assertion a
  # Google service account signs to obtain an access token (storage/gdrive.py). The
  # architecture test resolves this entry to the module root `jwt` through
  # DIST_TO_MODULE_OVERRIDES and strips the extra exactly as it already does for
  # `psycopg[binary]`, so no test change is needed.
  "pyjwt[crypto]==2.13.0",
```

Then: `cd /Users/ivansala/emdash/repositories/pigrocrm/.claude/worktrees/slice-1b-frontend && uv lock && uv sync`

- [ ] **Step 4: Write `gdrive.py`**

```python
# packages/core/src/pigrocrm/core/storage/gdrive.py
"""Google Drive through a service account, over the stdlib.

No Google client library: `urllib.request` and `json` are enough for six endpoints,
and adding `google-api-python-client` to `packages/core` would drag a large
transitive tree into the one package the architecture test keeps deliberately small.

**Operational requirement, not a detail:** a service account has no Drive storage
quota of its own. `PIGROCRM_GDRIVE_ROOT_FOLDER_ID` must name a folder on a *Shared
Drive*, or a folder explicitly shared with the service account's address, or
`files.create` fails with `storageQuotaExceeded`. Every call below carries
`supportsAllDrives=true` for that reason -- as Acme's already do
(.reference-acme/website/vite.config.js:2537).

The key is a path. `GDriveStorage` maps `a/b/c.pdf` onto nested folders `a` then `b`
under the configured root, and a file `c.pdf` inside. That is what makes
`DocumentStorage.put` able to honestly return `None`: nothing needs to remember a
file id, because the location is recomputed from the key every time.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import jwt

from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.storage.base import validate_storage_key

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_LIFETIME_SECONDS = 3600
# Refresh a minute early rather than discovering expiry mid-upload.
TOKEN_REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 30
_MULTIPART_BOUNDARY = "pigrocrm-boundary-7f3c1a"

# (method, url, headers, body) -> (status, body). Injected in tests; the default is
# `_urllib_call` below. Nothing above this seam knows what a socket is.
HttpCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]
SignAssertion = Callable[[dict[str, Any]], str]


def _urllib_call(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _escape_drive_query(value: str) -> str:
    """Escapes `\\` and `'` for a Drive `q` filter, backslash first.

    Backslash first is load-bearing for the same reason it is in the template
    escapers: escaping the quote first would then have its own backslash escaped by
    the second pass. Acme escaped only the quote
    (.reference-acme/website/vite.config.js:2360), which leaves a trailing backslash
    in a name able to swallow the closing quote.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GDriveStorage:
    def __init__(
        self,
        *,
        service_account_json: str,
        root_folder_id: str,
        http: HttpCall | None = None,
        sign_assertion: SignAssertion | None = None,
    ) -> None:
        self._credentials: dict[str, Any] = json.loads(service_account_json)
        self._root_folder_id = root_folder_id
        self._http: HttpCall = http or _urllib_call
        self._sign: SignAssertion = sign_assertion or self._sign_with_private_key
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ---- transport ----------------------------------------------------------

    def _sign_with_private_key(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._credentials["private_key"], algorithm="RS256")

    def _access_token(self) -> str:
        if self._token is not None and time.time() < self._token_expires_at:
            return self._token
        issued = int(time.time())
        assertion = self._sign(
            {
                "iss": self._credentials["client_email"],
                "scope": DRIVE_SCOPE,
                "aud": self._credentials.get("token_uri", GOOGLE_TOKEN_URL),
                "iat": issued,
                "exp": issued + TOKEN_LIFETIME_SECONDS,
            }
        )
        body = urlencode(
            {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        ).encode()
        status, payload = self._http(
            "POST",
            self._credentials.get("token_uri", GOOGLE_TOKEN_URL),
            {"Content-Type": "application/x-www-form-urlencoded"},
            body,
        )
        parsed = self._decode(status, payload, "autenticazione Google")
        self._token = str(parsed["access_token"])
        self._token_expires_at = time.time() + TOKEN_LIFETIME_SECONDS - TOKEN_REFRESH_MARGIN_SECONDS
        return self._token

    def _decode(self, status: int, payload: bytes, what: str) -> dict[str, Any]:
        if status >= 400:
            # Google's own message is included but the raw body is not: it can carry
            # the folder tree and the service-account address, neither of which
            # belongs in a problem document a browser will render.
            detail = ""
            try:
                detail = str(json.loads(payload.decode()).get("error", {}).get("message", ""))
            except (ValueError, AttributeError):
                detail = ""
            raise Conflict(
                "document_blob",
                f"{what} fallita ({status}){': ' + detail if detail else ''}",
                status=status,
            )
        return json.loads(payload.decode()) if payload else {}

    def _api(
        self, method: str, url: str, *, body: bytes | None = None, content_type: str | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        status, payload = self._http(method, url, headers, body)
        return self._decode(status, payload, "richiesta a Google Drive")

    @staticmethod
    def _url(base: str, **params: str) -> str:
        return f"{base}?{urlencode({'supportsAllDrives': 'true', **params})}"

    # ---- folder / file resolution -------------------------------------------

    def _find(self, parent_id: str, name: str, *, folder: bool) -> str | None:
        clauses = [
            "trashed=false",
            f"name='{_escape_drive_query(name)}'",
            f"'{parent_id}' in parents",
            f"mimeType{'=' if folder else '!='}'{FOLDER_MIME}'",
        ]
        url = self._url(
            DRIVE_FILES_URL,
            q=" and ".join(clauses),
            fields="files(id,name)",
            includeItemsFromAllDrives="true",
        )
        files = self._api("GET", url).get("files") or []
        return str(files[0]["id"]) if files else None

    def _ensure_folder(self, parent_id: str, name: str) -> str:
        existing = self._find(parent_id, name, folder=True)
        if existing:
            return existing
        created = self._api(
            "POST",
            self._url(DRIVE_FILES_URL, fields="id,name"),
            body=json.dumps({"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}).encode(),
            content_type="application/json",
        )
        return str(created["id"])

    def _walk(self, key: str, *, create: bool) -> tuple[str | None, str]:
        """`(parent folder id, file name)` for a validated key."""
        *folders, filename = validate_storage_key(key).split("/")
        parent = self._root_folder_id
        for name in folders:
            if create:
                parent = self._ensure_folder(parent, name)
            else:
                found = self._find(parent, name, folder=True)
                if found is None:
                    return None, filename
                parent = found
        return parent, filename

    # ---- DocumentStorage ----------------------------------------------------

    def put(self, key: str, data: bytes, content_type: str) -> None:
        parent, filename = self._walk(key, create=True)
        assert parent is not None  # create=True never returns None
        metadata = json.dumps({"name": filename, "parents": [parent]}).encode()
        body = b"".join(
            [
                f"--{_MULTIPART_BOUNDARY}\r\n".encode(),
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
                metadata,
                f"\r\n--{_MULTIPART_BOUNDARY}\r\n".encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                data,
                f"\r\n--{_MULTIPART_BOUNDARY}--\r\n".encode(),
            ]
        )
        self._api(
            "POST",
            self._url(DRIVE_UPLOAD_URL, uploadType="multipart", fields="id"),
            body=body,
            content_type=f"multipart/related; boundary={_MULTIPART_BOUNDARY}",
        )

    def get(self, key: str) -> bytes:
        parent, filename = self._walk(key, create=False)
        file_id = self._find(parent, filename, folder=False) if parent else None
        if file_id is None:
            raise NotFound("document_blob", key)
        url = self._url(f"{DRIVE_FILES_URL}/{file_id}", alt="media")
        status, payload = self._http(
            "GET", url, {"Authorization": f"Bearer {self._access_token()}"}, None
        )
        if status == 404:
            raise NotFound("document_blob", key)
        self._decode(status, payload if status >= 400 else b"", "download da Google Drive")
        return payload

    def delete(self, key: str) -> None:
        parent, filename = self._walk(key, create=False)
        file_id = self._find(parent, filename, folder=False) if parent else None
        if file_id is None:
            return  # idempotent, like LocalFileStorage.delete
        self._api("DELETE", self._url(f"{DRIVE_FILES_URL}/{file_id}"))

    def signed_url(self, key: str, ttl: timedelta) -> str | None:
        """Always `None`, exactly like `LocalFileStorage`.

        Drive can mint a shareable link, but a link that outlives a permission check
        is a leak nobody revokes, and it would make the two backends behave
        differently for the same call -- which is the one thing spec 5 asks not to
        happen. Downloads go through the API on both backends.
        """
        validate_storage_key(key)
        return None
```

- [ ] **Step 5: Write `factory.py`, extend `Settings`, and export**

```python
# packages/core/src/pigrocrm/core/storage/factory.py
from pathlib import Path

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.storage.base import DocumentStorage
from pigrocrm.core.storage.gdrive import GDriveStorage
from pigrocrm.core.storage.local import LocalFileStorage


def storage_from_settings(settings: Settings) -> DocumentStorage:
    """The single place a backend is chosen. Services take a `DocumentStorage` and
    never call this, which is what makes swapping backends a configuration change
    rather than a code change (spec 11 criterion 5)."""
    if settings.storage_backend == "gdrive":
        if not settings.gdrive_service_account_json or not settings.gdrive_root_folder_id:
            raise ValidationFailed(
                "settings",
                "storage_backend",
                "gdrive richiede PIGROCRM_GDRIVE_SERVICE_ACCOUNT_JSON e "
                "PIGROCRM_GDRIVE_ROOT_FOLDER_ID",
                expected="entrambe le variabili valorizzate",
            )
        return GDriveStorage(
            service_account_json=settings.gdrive_service_account_json,
            root_folder_id=settings.gdrive_root_folder_id,
        )
    return LocalFileStorage(Path(settings.storage_local_root))
```

Add to `packages/core/src/pigrocrm/core/config.py`, inside `class Settings`, after `cookie_secure`:

```python
    # Storage. `local` by default: no external dependency is what makes the product
    # genuinely self-hostable (spec 5). Switching to `gdrive` moves *new* bytes only
    # -- the ones already written stay where they are, and moving them is an explicit
    # migration, not a side effect of an environment variable.
    storage_backend: Literal["local", "gdrive"] = "local"
    storage_local_root: str = "./var/documents"
    # The service account's JSON key, inline. `PIGROCRM_GDRIVE_ROOT_FOLDER_ID` must
    # name a folder on a Shared Drive (or one shared with the service account): a
    # service account has no Drive quota of its own and `files.create` otherwise
    # fails with storageQuotaExceeded.
    gdrive_service_account_json: str = ""
    gdrive_root_folder_id: str = ""
    # Rendering. The image installs Pandoc and Typst at these names (Dockerfile.api).
    pandoc_binary: str = "pandoc"
    typst_binary: str = "typst"
```

and extend the import at the top of `config.py` from `from functools import lru_cache` to also carry `from typing import Literal`.

Replace `packages/core/src/pigrocrm/core/storage/__init__.py` with:

```python
from pigrocrm.core.storage.base import (
    MAX_KEY_LENGTH,
    DocumentStorage,
    validate_storage_key,
)
from pigrocrm.core.storage.factory import storage_from_settings
from pigrocrm.core.storage.gdrive import GDriveStorage
from pigrocrm.core.storage.local import LocalFileStorage

__all__ = [
    "MAX_KEY_LENGTH",
    "DocumentStorage",
    "GDriveStorage",
    "LocalFileStorage",
    "storage_from_settings",
    "validate_storage_key",
]
```

- [ ] **Step 6: Run both storage test files to verify they pass**

Run: `cd packages/core && uv run pytest tests/test_storage_local.py tests/test_storage_conformance.py -v`
Expected: PASS

- [ ] **Step 7: Verify the architecture guard still passes with the new dependency**

Run: `cd packages/core && uv run pytest tests/test_architecture.py tests/test_module_imports.py -v`
Expected: PASS — `pyjwt[crypto]` resolves to the module root `jwt`, which was already allowed.

- [ ] **Step 8: Lint and type-check**

Run: `cd packages/core && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add packages/core/src/pigrocrm/core/storage packages/core/src/pigrocrm/core/config.py \
        packages/core/pyproject.toml packages/core/tests/fakes \
        packages/core/tests/test_storage_conformance.py uv.lock
git commit -m "feat(storage): GDriveStorage and one conformance suite for both backends"
```

---

# Phase 3 — Data model and services

### Task 6: The four tables, and `document` as a real entity type

**Files:**
- Create: `packages/core/src/pigrocrm/core/emitter/__init__.py`, `packages/core/src/pigrocrm/core/emitter/models.py`
- Create: `packages/core/src/pigrocrm/core/templates/models.py`
- Create: `packages/core/src/pigrocrm/core/documents/__init__.py`, `packages/core/src/pigrocrm/core/documents/models.py`
- Create: `packages/core/migrations/versions/0003_documents_templates_emitter.py`
- Modify: `packages/core/src/pigrocrm/core/models_registry.py`
- Modify: `packages/core/src/pigrocrm/core/fields/schemas.py:12`
- Modify: `packages/core/src/pigrocrm/core/schema_registry.py:21-27`
- Test: `packages/core/tests/test_documents_models.py`

**Interfaces:**
- Consumes: `Base`, `PrimaryKeyMixin`, `SoftDeleteMixin`, `TimestampMixin` from `pigrocrm.core.db`.
- Produces:
  - `class EmitterProfile(Base, PrimaryKeyMixin, TimestampMixin)` — table `emitter_profile`
  - `class Template(Base, PrimaryKeyMixin, TimestampMixin)` — table `templates`
  - `class Document(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin)` — table `documents`
  - `class DocumentVersion(Base, PrimaryKeyMixin, TimestampMixin)` — table `document_versions`
  - `EntityType` widened to `Literal["customer", "person", "deal", "document"]`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_documents_models.py
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.emitter.models import EmitterProfile
from pigrocrm.core.schema_registry import ENTITY_TYPES, native_fields
from pigrocrm.core.templates.models import Template


def _customer(db_session: Session) -> Customer:
    customer = Customer(ragione_sociale="ACME")
    db_session.add(customer)
    db_session.flush()
    return customer


def test_a_document_belongs_to_a_customer(db_session: Session) -> None:
    customer = _customer(db_session)
    document = Document(customer_id=customer.id, tipo="offerta", titolo="Offerta 1", stato="bozza")
    db_session.add(document)
    db_session.flush()
    assert document.versione_corrente == 0
    assert document.custom_fields == {}


def test_a_document_with_neither_customer_nor_deal_is_refused(db_session: Session) -> None:
    db_session.add(Document(tipo="documento", titolo="Orfano"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_document_with_both_customer_and_deal_is_refused(db_session: Session) -> None:
    customer = _customer(db_session)
    db_session.add(
        Document(customer_id=customer.id, deal_id=uuid4(), tipo="documento", titolo="Doppio")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_versions_cannot_share_a_number(db_session: Session) -> None:
    customer = _customer(db_session)
    document = Document(customer_id=customer.id, tipo="offerta", titolo="O")
    db_session.add(document)
    db_session.flush()
    for _ in range(2):
        db_session.add(
            DocumentVersion(
                document_id=document.id,
                numero=1,
                storage_key="a/b/v1.pdf",
                content_type="application/pdf",
                dimensione=10,
                hash_sha256="0" * 64,
            )
        )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_emitter_profile_row_can_exist(db_session: Session) -> None:
    for _ in range(2):
        db_session.add(EmitterProfile(ragione_sociale="X", partita_iva="12345678901"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_templates_cannot_share_a_name_case_insensitively(db_session: Session) -> None:
    db_session.add(Template(nome="Consulenza CTO", tipo="offerta", corpo_markdown="x"))
    db_session.add(Template(nome="consulenza cto", tipo="offerta", corpo_markdown="y"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_document_is_a_recognised_entity_type() -> None:
    assert "document" in ENTITY_TYPES
    assert native_fields("document") == ["customer_id", "deal_id", "tipo", "titolo", "stato"]


def test_documents_has_a_gin_index_on_custom_fields(db_session: Session) -> None:
    indexes = inspect(db_session.get_bind()).get_indexes("documents")
    assert any(index["name"] == "ix_documents_custom_fields" for index in indexes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_documents_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.documents'`

- [ ] **Step 3: Write the models**

```python
# packages/core/src/pigrocrm/core/emitter/__init__.py
```

(empty file — likewise `packages/core/src/pigrocrm/core/documents/__init__.py`)

```python
# packages/core/src/pigrocrm/core/emitter/models.py
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class EmitterProfile(Base, PrimaryKeyMixin, TimestampMixin):
    """Who is issuing the document. One row, ever.

    This is what replaces "Humancraft di Ivan Sala", the P.IVA, the PEC and the
    address hardcoded into Acme's `offer/header.typ` (lines 16-28). A CRM for
    Italian freelancers cannot have one freelancer's name in its source. Slice 3
    builds FatturaPA on these same columns, which is why the fiscal ones mirror
    `customers` exactly rather than being free text.

    Single-row is enforced by the database, not by a convention: `singleton` is
    `unique=True` and always `True`, so a second insert fails on the constraint. A
    "select then insert" pre-check alone would let two concurrent first-time saves
    both pass.
    """

    __tablename__ = "emitter_profile"

    singleton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, unique=True)
    ragione_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    partita_iva: Mapped[str | None] = mapped_column(String(11), default=None)
    codice_fiscale: Mapped[str | None] = mapped_column(String(16), default=None)
    indirizzo: Mapped[str | None] = mapped_column(String(255), default=None)
    cap: Mapped[str | None] = mapped_column(String(10), default=None)
    comune: Mapped[str | None] = mapped_column(String(120), default=None)
    provincia: Mapped[str | None] = mapped_column(String(2), default=None)
    nazione: Mapped[str] = mapped_column(String(2), nullable=False, default="IT")
    pec: Mapped[str | None] = mapped_column(String(320), default=None)
    codice_sdi: Mapped[str | None] = mapped_column(String(7), default=None)
    telefono: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    sito_web: Mapped[str | None] = mapped_column(String(255), default=None)
    # Storage keys, not filesystem paths: the logo and signature live in the same
    # DocumentStorage as everything else, so a Drive-backed install keeps them too.
    logo_key: Mapped[str | None] = mapped_column(String(255), default=None)
    firma_key: Mapped[str | None] = mapped_column(String(255), default=None)
    regime_fiscale: Mapped[str | None] = mapped_column(String(200), default=None)
```

```python
# packages/core/src/pigrocrm/core/templates/models.py
from typing import Any

from sqlalchemy import Boolean, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class Template(Base, PrimaryKeyMixin, TimestampMixin):
    """A document body plus the variables it declares.

    `variabili_dichiarate` is declared, never deduced (spec 4.3): the compilation
    form shows each variable with its label, type and whether it is required, and the
    render fails with a precise error if a required one is missing -- instead of
    producing a PDF with a hole in it.

    The unique index is on `lower(nome)`, not on `nome`: a plain `unique=True` on a
    text column is case-sensitive, and lowercasing in a Pydantic validator would
    protect only the paths that go through it.
    """

    __tablename__ = "templates"
    __table_args__ = (Index("uq_templates_nome", func.lower("nome"), unique=True),)

    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="offerta")
    corpo_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    variabili_dichiarate: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    attivo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

```python
# packages/core/src/pigrocrm/core/documents/models.py
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin


class Document(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A document belongs to a customer **or** to a deal -- never both, never neither.

    `tipo` and `stato` are `String` + a Pydantic `Literal`, not a Postgres `ENUM`:
    that is how every closed set in this schema is already spelled (`pipeline_stages.
    tipo` is `String(10)`), and it means a future value costs a schema constant rather
    than an `ALTER TYPE` migration. The one thing that *is* a database constraint is
    the exclusivity rule below, which the spec names explicitly and which no
    application-level check can guarantee under concurrency.

    `stato` is only meaningful for `tipo = 'offerta'`; it is `NULL` for every other
    type. `DocumentService.set_offer_state` is the only writer.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "(customer_id IS NOT NULL) <> (deal_id IS NOT NULL)",
            name="ck_documents_customer_xor_deal",
        ),
        Index("ix_documents_custom_fields", "custom_fields", postgresql_using="gin"),
    )

    customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id"), default=None, index=True
    )
    deal_id: Mapped[UUID | None] = mapped_column(ForeignKey("deals.id"), default=None, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    titolo: Mapped[str] = mapped_column(String(200), nullable=False)
    stato: Mapped[str | None] = mapped_column(String(20), default=None)
    versione_corrente: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class DocumentVersion(Base, PrimaryKeyMixin, TimestampMixin):
    """Every change makes a version; nothing is ever overwritten (spec 4.2).

    Keeping `template_id` **and** `variabili` together is what makes a version
    reproducible: the PDF of a six-month-old offer can be regenerated without the
    person who wrote it being in the room (spec 11 criterion 4).

    `creato_da` is nullable and is *not* validated as a foreign key on input, unlike
    every other FK in this slice. It is never supplied by a caller -- it is read from
    the already-authenticated `Actor`, whose `id` is `None` for a `system` actor
    (actor.py:22). That is the documented exception to the FK-validation rule.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "numero", name="uq_document_versions_document_numero"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    sorgente_markdown: Mapped[str | None] = mapped_column(Text, default=None)
    template_id: Mapped[UUID | None] = mapped_column(ForeignKey("templates.id"), default=None)
    variabili: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensione: Mapped[int] = mapped_column(Integer, nullable=False)
    # Deduplication and integrity check. 64 hex characters, exactly.
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    creato_da: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)
```

- [ ] **Step 4: Widen `EntityType` and register everything**

In `packages/core/src/pigrocrm/core/fields/schemas.py`, replace line 11–12:

```python
# Open by design: slice 2 appended "document" here and in schema_registry.ENTITY_TYPES /
# CREATE_MODELS, which is the whole change -- no migration, no validator edit, no
# custom-field schema change. A later slice appends "invoice" the same way.
EntityType = Literal["customer", "person", "deal", "document"]
```

In `packages/core/src/pigrocrm/core/schema_registry.py`, add the import and both entries:

```python
from pigrocrm.core.documents.schemas import DocumentCreate

ENTITY_TYPES: tuple[EntityType, ...] = ("customer", "person", "deal", "document")

CREATE_MODELS: dict[str, type[BaseModel]] = {
    "customer": CustomerCreate,
    "person": PersonCreate,
    "deal": DealCreate,
    "document": DocumentCreate,
}
```

In `packages/core/src/pigrocrm/core/models_registry.py`, append:

```python
from pigrocrm.core.documents.models import Document, DocumentVersion  # noqa: F401
from pigrocrm.core.emitter.models import EmitterProfile  # noqa: F401
from pigrocrm.core.templates.models import Template  # noqa: F401
```

`DocumentCreate` does not exist yet — write the minimal version now in a new file `packages/core/src/pigrocrm/core/documents/schemas.py`; Task 9 fills in the rest:

```python
# packages/core/src/pigrocrm/core/documents/schemas.py
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pigrocrm.core.validation import SafeStr

DocumentTipo = Literal["offerta", "contratto", "verbale", "documento"]
OfferState = Literal["bozza", "inviata", "accettata", "rifiutata"]

TITOLO_MAX_LENGTH = 200


class DocumentCreate(BaseModel):
    """`customer_id` and `deal_id` are both optional here and mutually exclusive; the
    service raises `ValidationFailed` when neither or both is given, and the database
    check constraint is the second line under concurrency."""

    customer_id: UUID | None = None
    deal_id: UUID | None = None
    tipo: DocumentTipo = "documento"
    titolo: SafeStr = Field(max_length=TITOLO_MAX_LENGTH)
    stato: OfferState | None = None
    custom_fields: dict[str, Any] = {}
```

- [ ] **Step 5: Generate and hand-check the migration**

Run: `cd packages/core && uv run alembic revision --autogenerate -m "documents templates emitter"`

Rename the generated file to `packages/core/migrations/versions/0003_documents_templates_emitter.py` and set `revision = "0003"` / `down_revision = "0002"`. Then verify by hand that it contains, in `upgrade()`: `op.create_table("emitter_profile", ...)`, `op.create_table("templates", ...)` with `op.create_index("uq_templates_nome", "templates", [sa.text("lower(nome)")], unique=True)`, `op.create_table("documents", ...)` with the `CheckConstraint` and the GIN index `op.create_index("ix_documents_custom_fields", "documents", ["custom_fields"], postgresql_using="gin")`, and `op.create_table("document_versions", ...)` with the `UniqueConstraint`. Autogenerate does not emit functional indexes or `postgresql_using`; add both by hand if missing. `downgrade()` drops the four tables in reverse dependency order: `document_versions`, `documents`, `templates`, `emitter_profile`.

- [ ] **Step 6: Run the tests**

Run: `cd packages/core && uv run pytest tests/test_documents_models.py tests/test_migrations.py tests/test_module_imports.py tests/test_schema_registry.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core packages/core/migrations packages/core/tests/test_documents_models.py
git commit -m "feat(documents): documents, versions, templates and emitter tables"
```

---

### Task 7: `EmitterProfileService`

**Files:**
- Create: `packages/core/src/pigrocrm/core/emitter/schemas.py`, `packages/core/src/pigrocrm/core/emitter/repository.py`, `packages/core/src/pigrocrm/core/emitter/service.py`
- Test: `packages/core/tests/test_emitter.py`

**Interfaces:**
- Consumes: `EmitterProfile` from `pigrocrm.core.emitter.models`; `Actor`; `ActivityService`; `Conflict`, `NotFound`, `ValidationFailed`.
- Produces:
  - `class EmitterProfileRead(BaseModel)` — every column of `EmitterProfile` except `singleton`, plus `id`, `created_at`, `updated_at`
  - `class EmitterProfileUpsert(BaseModel)` — `ragione_sociale: SafeStr = Field(max_length=255)` and every other column optional with matching `max_length`
  - `class EmitterProfileService:` with `get(self, actor: Actor) -> EmitterProfileRead`, `upsert(self, data: EmitterProfileUpsert, actor: Actor) -> EmitterProfileRead`, `as_template_values(self, actor: Actor) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_emitter.py
import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import NotFound, PermissionDenied, ValidationFailed

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")


def _upsert(**overrides: object) -> EmitterProfileUpsert:
    payload: dict[str, object] = {
        "ragione_sociale": "Humancraft di Ivan Sala",
        "partita_iva": "14518240966",
        "pec": "someone@example.com",
        "indirizzo": "Via Roma 1",
        "comune": "Milano",
        "cap": "20053",
        "provincia": "MI",
        "telefono": "+39 02 1234567",
        "email": "ivansala@humancraft.tech",
        "regime_fiscale": "Regime forfettario, L. 190/2014 art. 1 commi 54-89",
    }
    payload.update(overrides)
    return EmitterProfileUpsert(**payload)  # type: ignore[arg-type]


def test_get_before_any_save_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        EmitterProfileService(db_session).get(ADMIN)


def test_upsert_creates_the_single_row(db_session: Session) -> None:
    profile = EmitterProfileService(db_session).upsert(_upsert(), ADMIN)
    assert profile.ragione_sociale == "Humancraft di Ivan Sala"
    assert profile.partita_iva == "14518240966"


def test_a_second_upsert_updates_rather_than_creating_a_second_row(db_session: Session) -> None:
    service = EmitterProfileService(db_session)
    first = service.upsert(_upsert(), ADMIN)
    second = service.upsert(_upsert(ragione_sociale="Nuovo Nome"), ADMIN)
    assert second.id == first.id
    assert second.ragione_sociale == "Nuovo Nome"


def test_a_readonly_actor_cannot_write(db_session: Session) -> None:
    with pytest.raises(PermissionDenied):
        EmitterProfileService(db_session).upsert(_upsert(), READONLY)


def test_a_malformed_partita_iva_is_refused(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        EmitterProfileService(db_session).upsert(_upsert(partita_iva="1234567890"), ADMIN)
    assert excinfo.value.details["field"] == "partita_iva"


def test_a_partita_iva_with_a_trailing_newline_is_refused(db_session: Session) -> None:
    # `re.match` with `$` would accept this -- `$` matches before a final newline --
    # and the 12-character value would reach the String(11) column as a raw DataError.
    with pytest.raises(ValidationFailed):
        EmitterProfileService(db_session).upsert(_upsert(partita_iva="12345678901"), ADMIN)


def test_as_template_values_exposes_the_profile_under_emittente(db_session: Session) -> None:
    service = EmitterProfileService(db_session)
    service.upsert(_upsert(), ADMIN)
    values = service.as_template_values(ADMIN)
    assert values["emittente"]["ragione_sociale"] == "Humancraft di Ivan Sala"
    assert values["emittente"]["partita_iva"] == "14518240966"
    assert "singleton" not in values["emittente"]


def test_as_template_values_before_any_save_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        EmitterProfileService(db_session).as_template_values(ADMIN)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_emitter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.emitter.schemas'`

- [ ] **Step 3: Write the schemas**

```python
# packages/core/src/pigrocrm/core/emitter/schemas.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.validation import SafeStr

# Mirror EmitterProfile's column widths exactly (emitter/models.py). Without these an
# over-long value reaches Postgres and raises sqlalchemy.exc.DataError, which is not
# an IntegrityError subclass, so no handler catches it and the session is poisoned.
RAGIONE_SOCIALE_MAX_LENGTH = 255
CODICE_FISCALE_MAX_LENGTH = 16
INDIRIZZO_MAX_LENGTH = 255
CAP_MAX_LENGTH = 10
COMUNE_MAX_LENGTH = 120
PROVINCIA_MAX_LENGTH = 2
NAZIONE_MAX_LENGTH = 2
PEC_MAX_LENGTH = 320
TELEFONO_MAX_LENGTH = 40
EMAIL_MAX_LENGTH = 320
SITO_WEB_MAX_LENGTH = 255
STORAGE_KEY_MAX_LENGTH = 255
REGIME_FISCALE_MAX_LENGTH = 200


class EmitterProfileUpsert(BaseModel):
    """One shape for create and update: there is only ever one row, so "create" and
    "update" are the same operation with the same required fields.

    `partita_iva` and `codice_sdi` carry no `max_length`, exactly as
    `CustomerCreate` does: the service's `_check_fiscal` already requires an exact
    11-digit / 7-character match, which is stricter, and adding a Pydantic bound would
    make a 12-digit input raise pydantic's own `ValidationError` instead of this
    project's `ValidationFailed` -- a regression, not a fix.
    """

    model_config = ConfigDict(extra="forbid")

    ragione_sociale: SafeStr = Field(max_length=RAGIONE_SOCIALE_MAX_LENGTH)
    partita_iva: SafeStr | None = None
    codice_fiscale: SafeStr | None = Field(default=None, max_length=CODICE_FISCALE_MAX_LENGTH)
    indirizzo: SafeStr | None = Field(default=None, max_length=INDIRIZZO_MAX_LENGTH)
    cap: SafeStr | None = Field(default=None, max_length=CAP_MAX_LENGTH)
    comune: SafeStr | None = Field(default=None, max_length=COMUNE_MAX_LENGTH)
    provincia: SafeStr | None = Field(default=None, max_length=PROVINCIA_MAX_LENGTH)
    nazione: SafeStr = Field(default="IT", max_length=NAZIONE_MAX_LENGTH)
    pec: SafeStr | None = Field(default=None, max_length=PEC_MAX_LENGTH)
    codice_sdi: SafeStr | None = None
    telefono: SafeStr | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    email: SafeStr | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    sito_web: SafeStr | None = Field(default=None, max_length=SITO_WEB_MAX_LENGTH)
    logo_key: SafeStr | None = Field(default=None, max_length=STORAGE_KEY_MAX_LENGTH)
    firma_key: SafeStr | None = Field(default=None, max_length=STORAGE_KEY_MAX_LENGTH)
    regime_fiscale: SafeStr | None = Field(default=None, max_length=REGIME_FISCALE_MAX_LENGTH)


class EmitterProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ragione_sociale: str
    partita_iva: str | None
    codice_fiscale: str | None
    indirizzo: str | None
    cap: str | None
    comune: str | None
    provincia: str | None
    nazione: str
    pec: str | None
    codice_sdi: str | None
    telefono: str | None
    email: str | None
    sito_web: str | None
    logo_key: str | None
    firma_key: str | None
    regime_fiscale: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Write the repository and service**

```python
# packages/core/src/pigrocrm/core/emitter/repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.emitter.models import EmitterProfile


class EmitterProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> EmitterProfile | None:
        return self.session.execute(select(EmitterProfile).limit(1)).scalars().first()

    def add(self, profile: EmitterProfile) -> EmitterProfile:
        self.session.add(profile)
        self.session.flush()
        return profile
```

```python
# packages/core/src/pigrocrm/core/emitter/service.py
import re
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.emitter.models import EmitterProfile
from pigrocrm.core.emitter.repository import EmitterProfileRepository
from pigrocrm.core.emitter.schemas import EmitterProfileRead, EmitterProfileUpsert
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed

ENTITY = "emitter_profile"
# `.fullmatch()`, not `.match()`: `$` matches before a trailing newline, so
# "12345678901" -- 12 characters, one more than the String(11) column -- would pass
# a `.match()` check and reach flush() as a raw, session-poisoning DataError. The same
# defect this project has already paid for once on `customers.partita_iva`.
PARTITA_IVA_RE = re.compile(r"\d{11}")
CODICE_SDI_LENGTH = 7


def _check_fiscal(data: dict[str, Any]) -> None:
    for field in ("partita_iva", "codice_sdi"):
        if data.get(field) == "":
            data[field] = None
    piva = data.get("partita_iva")
    if piva and not PARTITA_IVA_RE.fullmatch(piva):
        raise ValidationFailed(
            ENTITY, "partita_iva", "deve essere di 11 cifre", expected="11 cifre numeriche"
        )
    sdi = data.get("codice_sdi")
    if sdi and len(sdi) != CODICE_SDI_LENGTH:
        raise ValidationFailed(
            ENTITY, "codice_sdi", "deve essere di 7 caratteri", expected="7 caratteri"
        )


class EmitterProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = EmitterProfileRepository(session)
        self.activities = ActivityService(session)

    def get(self, actor: Actor) -> EmitterProfileRead:
        profile = self.repo.get()
        if profile is None:
            raise NotFound(ENTITY, "singleton")
        return EmitterProfileRead.model_validate(profile)

    def upsert(self, data: EmitterProfileUpsert, actor: Actor) -> EmitterProfileRead:
        actor.require_admin("upsert_emitter_profile")
        payload = data.model_dump()
        _check_fiscal(payload)

        profile = self.repo.get()
        if profile is None:
            profile = self.repo.add(EmitterProfile(**payload))
        else:
            for key, value in payload.items():
                setattr(profile, key, value)

        self.activities.record(ENTITY, profile.id, "updated", actor, {"changed": sorted(payload)})
        try:
            self.session.commit()
        except IntegrityError as exc:
            # The `repo.get()` pre-check cannot cover two concurrent first-time saves:
            # both see no row, both insert, and only the `singleton` unique constraint
            # stops the second. The rollback is mandatory -- without it the caller's
            # session is unusable on its next statement.
            self.session.rollback()
            raise Conflict(ENTITY, "il profilo emittente esiste gia'") from exc
        return EmitterProfileRead.model_validate(profile)

    def as_template_values(self, actor: Actor) -> dict[str, Any]:
        """The profile as a template scope, under the name `emittente`.

        This is what makes `{{emittente.ragione_sociale}}` work in a template and what
        replaces the hardcoded issuer data in Acme's `header.typ`. `singleton` is
        excluded: it is a storage mechanism, not a fact about the business.
        """
        profile = self.get(actor)
        return {"emittente": profile.model_dump(mode="json", exclude={"id", "created_at", "updated_at"})}
```

- [ ] **Step 5: Run the test**

Run: `cd packages/core && uv run pytest tests/test_emitter.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/emitter packages/core/tests/test_emitter.py
git commit -m "feat(emitter): configurable emitter profile replacing hardcoded issuer data"
```

---

### Task 8: `TemplateService` and `describe_template`

**Files:**
- Create: `packages/core/src/pigrocrm/core/templates/schemas.py`, `packages/core/src/pigrocrm/core/templates/repository.py`, `packages/core/src/pigrocrm/core/templates/service.py`
- Test: `packages/core/tests/test_templates_service.py`

**Interfaces:**
- Consumes: `Template` from `pigrocrm.core.templates.models`; `parse_template`, `declared_paths` from `pigrocrm.core.templates.parser`; `DeclaredVariable`, `render_template` from `pigrocrm.core.templates.renderer`; `FieldType` from `pigrocrm.core.fields.types`.
- Produces:
  - `class TemplateVariable(BaseModel)` — `nome: SafeStr = Field(max_length=60)`, `etichetta: SafeStr = Field(max_length=120)`, `tipo: FieldType = "text"`, `obbligatoria: bool = False`, `options: list[SafeStr] = []`
  - `class TemplateCreate(BaseModel)` / `class TemplateUpdate(BaseModel)` / `class TemplateRead(BaseModel)` / `class TemplateDescription(BaseModel)`
  - `class TemplateService:` with `create`, `update`, `get`, `describe(self, template_id: UUID, actor: Actor) -> TemplateDescription`, `preview(self, template_id: UUID, values: dict[str, Any], actor: Actor) -> str`, `archive`, and `list` **last**
  - `TemplateService.declared_variables(self, template: Template) -> tuple[DeclaredVariable, ...]`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_templates_service.py
import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.templates.schemas import TemplateCreate, TemplateUpdate, TemplateVariable
from pigrocrm.core.templates.service import TemplateService

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")

BODY = "Spett.le {{cliente.ragione_sociale}}\n\nOggetto: {{oggetto}}\n"
VARIABLES = [
    TemplateVariable(nome="oggetto", etichetta="Oggetto", tipo="text", obbligatoria=True),
]


def _create(service: TemplateService, **overrides: object) -> object:
    payload: dict[str, object] = {
        "nome": "Consulenza CTO",
        "tipo": "offerta",
        "corpo_markdown": BODY,
        "variabili_dichiarate": VARIABLES,
    }
    payload.update(overrides)
    return service.create(TemplateCreate(**payload), ADMIN)  # type: ignore[arg-type]


def test_create_stores_the_body_and_the_declared_variables(db_session: Session) -> None:
    template = _create(TemplateService(db_session))
    assert template.nome == "Consulenza CTO"  # type: ignore[attr-defined]
    assert template.variabili_dichiarate[0].nome == "oggetto"  # type: ignore[attr-defined]
    assert template.attivo is True  # type: ignore[attr-defined]


def test_create_rejects_a_body_that_does_not_parse(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        _create(TemplateService(db_session), corpo_markdown="{{#if x}}mai chiuso")
    assert excinfo.value.details["field"] == "corpo_markdown"


def test_create_rejects_a_duplicate_name_case_insensitively(db_session: Session) -> None:
    service = TemplateService(db_session)
    _create(service)
    with pytest.raises(Conflict):
        _create(service, nome="consulenza cto")


def test_a_readonly_actor_cannot_create(db_session: Session) -> None:
    with pytest.raises(PermissionDenied):
        TemplateService(db_session).create(
            TemplateCreate(nome="X", tipo="offerta", corpo_markdown="a"), READONLY
        )


def test_describe_reports_the_declared_variables_and_the_paths_used(db_session: Session) -> None:
    service = TemplateService(db_session)
    template = _create(service)
    described = service.describe(template.id, ADMIN)  # type: ignore[attr-defined]
    assert [v.nome for v in described.variabili] == ["oggetto"]
    assert ("cliente", "ragione_sociale") in [tuple(p) for p in described.percorsi_usati]


def test_describe_flags_a_declared_variable_the_body_never_uses(db_session: Session) -> None:
    service = TemplateService(db_session)
    template = _create(
        service,
        variabili_dichiarate=[
            TemplateVariable(nome="oggetto", etichetta="Oggetto", obbligatoria=True),
            TemplateVariable(nome="inutile", etichetta="Inutile"),
        ],
    )
    described = service.describe(template.id, ADMIN)  # type: ignore[attr-defined]
    assert described.variabili_non_usate == ["inutile"]


def test_preview_renders_the_body_with_the_supplied_values(db_session: Session) -> None:
    service = TemplateService(db_session)
    template = _create(service)
    out = service.preview(
        template.id,  # type: ignore[attr-defined]
        {"cliente": {"ragione_sociale": "ACME"}, "oggetto": "Advisory"},
        ADMIN,
    )
    assert "Spett.le ACME" in out
    assert "Oggetto: Advisory" in out


def test_preview_fails_when_a_required_variable_is_missing(db_session: Session) -> None:
    service = TemplateService(db_session)
    template = _create(service)
    with pytest.raises(ValidationFailed) as excinfo:
        service.preview(
            template.id, {"cliente": {"ragione_sociale": "ACME"}}, ADMIN  # type: ignore[attr-defined]
        )
    assert excinfo.value.details["field"] == "oggetto"


def test_update_rejects_a_body_that_does_not_parse(db_session: Session) -> None:
    service = TemplateService(db_session)
    template = _create(service)
    with pytest.raises(ValidationFailed):
        service.update(
            template.id, TemplateUpdate(corpo_markdown="{{/each}}"), ADMIN  # type: ignore[attr-defined]
        )


def test_archive_hides_a_template_from_the_default_list(db_session: Session) -> None:
    service = TemplateService(db_session)
    template = _create(service)
    service.archive(template.id, ADMIN)  # type: ignore[attr-defined]
    assert service.list(ADMIN) == []
    assert len(service.list(ADMIN, include_archived=True)) == 1


def test_get_of_an_unknown_id_raises_not_found(db_session: Session) -> None:
    from uuid import uuid4

    with pytest.raises(NotFound):
        TemplateService(db_session).get(uuid4(), ADMIN)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_templates_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.templates.schemas'`

- [ ] **Step 3: Write the schemas**

```python
# packages/core/src/pigrocrm/core/templates/schemas.py
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.fields.types import FieldType
from pigrocrm.core.validation import SafeStr

# Mirror templates/models.py's column widths.
NOME_MAX_LENGTH = 120
VARIABILE_NOME_MAX_LENGTH = 60
VARIABILE_ETICHETTA_MAX_LENGTH = 120

TemplateTipo = Literal["offerta", "contratto", "verbale", "documento"]


class TemplateVariable(BaseModel):
    """One declared variable.

    `tipo` reuses `FieldType` -- the same nine types custom fields already have -- so
    the compilation form renders with the existing `DynamicFieldRenderer` and nothing
    new has to learn a tenth type (spec 9).
    """

    nome: SafeStr = Field(max_length=VARIABILE_NOME_MAX_LENGTH)
    etichetta: SafeStr = Field(max_length=VARIABILE_ETICHETTA_MAX_LENGTH)
    tipo: FieldType = "text"
    obbligatoria: bool = False
    options: list[SafeStr] = []


class TemplateCreate(BaseModel):
    nome: SafeStr = Field(max_length=NOME_MAX_LENGTH)
    tipo: TemplateTipo = "offerta"
    corpo_markdown: SafeStr
    variabili_dichiarate: list[TemplateVariable] = []


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: SafeStr | None = Field(default=None, max_length=NOME_MAX_LENGTH)
    tipo: TemplateTipo | None = None
    corpo_markdown: SafeStr | None = None
    variabili_dichiarate: list[TemplateVariable] | None = None
    attivo: bool | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    tipo: str
    corpo_markdown: str
    variabili_dichiarate: list[TemplateVariable]
    attivo: bool
    created_at: datetime
    updated_at: datetime


class TemplateDescription(BaseModel):
    """What `describe_template` answers: what this template wants, before anyone is
    asked for it (spec 7)."""

    id: UUID
    nome: str
    tipo: str
    variabili: list[TemplateVariable]
    # Every dotted path the body reads, so an agent can see that `cliente.*` comes
    # from the record rather than from the user.
    percorsi_usati: list[list[str]]
    # Declared but never referenced: a form field nobody's document will ever show.
    variabili_non_usate: list[str]
```

- [ ] **Step 4: Write the repository and service**

```python
# packages/core/src/pigrocrm/core/templates/repository.py
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.templates.models import Template


class TemplateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, template_id: UUID) -> Template | None:
        return self.session.get(Template, template_id)

    def get_by_name(self, nome: str) -> Template | None:
        stmt = select(Template).where(func.lower(Template.nome) == nome.lower())
        return self.session.execute(stmt).scalars().first()

    def add(self, template: Template) -> Template:
        self.session.add(template)
        self.session.flush()
        return template

    def list(self, *, include_archived: bool = False) -> list[Template]:
        stmt = select(Template)
        if not include_archived:
            stmt = stmt.where(Template.attivo.is_(True))
        return list(self.session.execute(stmt.order_by(Template.nome)).scalars())
```

```python
# packages/core/src/pigrocrm/core/templates/service.py
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.templates.models import Template
from pigrocrm.core.templates.parser import declared_paths, parse_template
from pigrocrm.core.templates.renderer import DeclaredVariable, render_template
from pigrocrm.core.templates.repository import TemplateRepository
from pigrocrm.core.templates.schemas import (
    TemplateCreate,
    TemplateDescription,
    TemplateRead,
    TemplateUpdate,
    TemplateVariable,
)

ENTITY = "template"


class TemplateService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = TemplateRepository(session)
        self.activities = ActivityService(session)

    def create(self, data: TemplateCreate, actor: Actor) -> TemplateRead:
        actor.require_admin("create_template")
        # Parsing here, not at render time, is what makes a broken template
        # unsaveable rather than a surprise six months later when somebody presses
        # Genera. `parse_template` raises ValidationFailed naming the line.
        parse_template(data.corpo_markdown)
        if self.repo.get_by_name(data.nome):
            raise Conflict(ENTITY, "esiste gia' un template con questo nome", nome=data.nome)

        payload = data.model_dump()
        template = Template(**payload)
        try:
            self.repo.add(template)
            self.activities.record(ENTITY, template.id, "created", actor, {"nome": template.nome})
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a race between two concurrent requests:
            # there the `lower(nome)` unique index is the only authority. The rollback
            # is mandatory -- without it the caller's session is unusable.
            self.session.rollback()
            raise Conflict(
                ENTITY, "esiste gia' un template con questo nome", nome=data.nome
            ) from exc
        return TemplateRead.model_validate(template)

    def update(self, template_id: UUID, data: TemplateUpdate, actor: Actor) -> TemplateRead:
        actor.require_admin("update_template")
        template = self._require(template_id)
        changes = data.model_dump(exclude_none=True)
        if "corpo_markdown" in changes:
            parse_template(changes["corpo_markdown"])
        for key, value in changes.items():
            setattr(template, key, value)
        self.activities.record(ENTITY, template.id, "updated", actor, {"changed": sorted(changes)})
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise Conflict(ENTITY, "esiste gia' un template con questo nome") from exc
        return TemplateRead.model_validate(template)

    def get(self, template_id: UUID, actor: Actor) -> TemplateRead:
        return TemplateRead.model_validate(self._require(template_id))

    def archive(self, template_id: UUID, actor: Actor) -> TemplateRead:
        """Archive, never delete: a document version still points at this template so
        it can be regenerated, and deleting the row would break that promise."""
        actor.require_admin("archive_template")
        template = self._require(template_id)
        template.attivo = False
        self.activities.record(ENTITY, template.id, "archived", actor)
        self.session.commit()
        return TemplateRead.model_validate(template)

    def describe(self, template_id: UUID, actor: Actor) -> TemplateDescription:
        """What this template wants, before anyone is asked for it (spec 7)."""
        template = self._require(template_id)
        declared = [TemplateVariable(**v) for v in template.variabili_dichiarate]
        used = declared_paths(parse_template(template.corpo_markdown))
        # A declared variable is "used" when its name is the first segment of some
        # path the body reads -- `{{oggetto}}` and `{{oggetto.riga}}` both count.
        first_segments = {path[0] for path in used}
        return TemplateDescription(
            id=template.id,
            nome=template.nome,
            tipo=template.tipo,
            variabili=declared,
            percorsi_usati=[list(path) for path in used],
            variabili_non_usate=[v.nome for v in declared if v.nome not in first_segments],
        )

    def declared_variables(self, template: Template) -> tuple[DeclaredVariable, ...]:
        """Bridge from the stored JSONB to the renderer's own dataclass."""
        return tuple(
            DeclaredVariable(
                nome=v["nome"],
                etichetta=v["etichetta"],
                tipo=v.get("tipo", "text"),
                obbligatoria=bool(v.get("obbligatoria", False)),
            )
            for v in template.variabili_dichiarate
        )

    def preview(self, template_id: UUID, values: dict[str, Any], actor: Actor) -> str:
        """The compiled Markdown, with no PDF and no storage. What the UI shows before
        anyone presses Genera (spec 9)."""
        template = self._require(template_id)
        return render_template(
            template.corpo_markdown, values, self.declared_variables(template)
        )

    def _require(self, template_id: UUID) -> Template:
        template = self.repo.get(template_id)
        if template is None:
            raise NotFound(ENTITY, template_id)
        return template

    # `list` must stay the last method defined in this class -- an unconditional
    # project rule. Defining a method named `list` rebinds that name in the class
    # namespace, so any later method whose return annotation is a bare `list[...]`
    # would resolve `list` to this method and fail at import time on Python 3.13.
    def list(self, actor: Actor, *, include_archived: bool = False) -> list[TemplateRead]:
        return [
            TemplateRead.model_validate(t)
            for t in self.repo.list(include_archived=include_archived)
        ]
```

- [ ] **Step 5: Run the test**

Run: `cd packages/core && uv run pytest tests/test_templates_service.py tests/test_module_imports.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/pigrocrm/core/templates packages/core/tests/test_templates_service.py
git commit -m "feat(templates): template service with declared variables and describe"
```

---

### Task 9: `DocumentService` — documents, versions and upload

**Files:**
- Modify: `packages/core/src/pigrocrm/core/documents/schemas.py`
- Create: `packages/core/src/pigrocrm/core/documents/repository.py`, `packages/core/src/pigrocrm/core/documents/service.py`
- Test: `packages/core/tests/test_documents_service.py`

**Interfaces:**
- Consumes: `Document`, `DocumentVersion`; `DocumentStorage`, `LocalFileStorage`; `FieldDefinitionService`, `validate_custom_fields`; `ActivityService`; `Customer`, `Deal` models for FK validation.
- Produces:
  - `class DocumentUpdate(BaseModel)` — `titolo: SafeStr | None = Field(default=None, max_length=200)`, `custom_fields: dict[str, Any] | None = None`, `model_config = ConfigDict(extra="forbid")`
  - `class DocumentRead(BaseModel)`, `class DocumentVersionRead(BaseModel)`, `class DocumentListQuery(BaseModel)`, `class DocumentPage(BaseModel)`
  - `ALLOWED_CONTENT_TYPES: dict[str, str]` — content type → file extension
  - `class DocumentService:` `__init__(self, session: Session, storage: DocumentStorage)`, `create`, `update`, `get`, `soft_delete`, `restore`, `add_version(self, document_id: UUID, data: bytes, content_type: str, actor: Actor, *, sorgente_markdown: str | None = None, template_id: UUID | None = None, variabili: dict[str, Any] | None = None) -> DocumentVersionRead`, `versions(self, document_id: UUID, actor: Actor) -> list[DocumentVersionRead]`, `download(self, document_id: UUID, numero: int | None, actor: Actor) -> tuple[bytes, str, str]`, `storage_key_for(self, document: Document, numero: int, content_type: str) -> str`, and `list` **last**

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_documents_service.py
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.schemas import DocumentCreate, DocumentListQuery, DocumentUpdate
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm.core.storage import LocalFileStorage

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")
PDF = b"%PDF-1.7\nfinto\n"


@pytest.fixture
def service(db_session: Session, tmp_path: Path) -> DocumentService:
    return DocumentService(db_session, LocalFileStorage(tmp_path))


@pytest.fixture
def customer(db_session: Session) -> Customer:
    row = Customer(ragione_sociale="ACME S.r.l.")
    db_session.add(row)
    db_session.flush()
    return row


def test_create_on_a_customer(service: DocumentService, customer: Customer) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta 2026-01"), ADMIN
    )
    assert document.customer_id == customer.id
    assert document.versione_corrente == 0
    # An offer starts as a draft; nothing else has a state at all.
    assert document.stato == "bozza"


def test_create_of_a_non_offer_has_no_state(service: DocumentService, customer: Customer) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="verbale", titolo="Verbale"), ADMIN
    )
    assert document.stato is None


def test_create_with_neither_customer_nor_deal_is_refused(service: DocumentService) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        service.create(DocumentCreate(tipo="documento", titolo="Orfano"), ADMIN)
    assert "customer_id" in excinfo.value.details["field"]


def test_create_with_both_customer_and_deal_is_refused(
    service: DocumentService, customer: Customer
) -> None:
    with pytest.raises(ValidationFailed):
        service.create(
            DocumentCreate(customer_id=customer.id, deal_id=uuid4(), tipo="documento", titolo="X"),
            ADMIN,
        )


def test_create_with_an_unknown_customer_raises_not_found(service: DocumentService) -> None:
    # Without this the syntactically valid UUID reaches flush() and comes back as a
    # raw IntegrityError (ForeignKeyViolation) instead of this project's NotFound.
    with pytest.raises(NotFound):
        service.create(DocumentCreate(customer_id=uuid4(), tipo="documento", titolo="X"), ADMIN)


def test_create_with_an_unknown_deal_raises_not_found(service: DocumentService) -> None:
    with pytest.raises(NotFound):
        service.create(DocumentCreate(deal_id=uuid4(), tipo="documento", titolo="X"), ADMIN)


def test_a_readonly_actor_cannot_create(service: DocumentService, customer: Customer) -> None:
    with pytest.raises(PermissionDenied):
        service.create(DocumentCreate(customer_id=customer.id, tipo="documento", titolo="X"), READONLY)


def test_add_version_stores_the_bytes_and_bumps_the_current_version(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    version = service.add_version(document.id, PDF, "application/pdf", ADMIN)
    assert version.numero == 1
    assert version.dimensione == len(PDF)
    assert version.hash_sha256 == hashlib.sha256(PDF).hexdigest()
    assert service.get(document.id, ADMIN).versione_corrente == 1


def test_a_second_version_does_not_overwrite_the_first(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    service.add_version(document.id, PDF, "application/pdf", ADMIN)
    service.add_version(document.id, b"%PDF-1.7\nsecondo\n", "application/pdf", ADMIN)
    numbers = [v.numero for v in service.versions(document.id, ADMIN)]
    assert numbers == [2, 1]
    assert service.download(document.id, 1, ADMIN)[0] == PDF


def test_download_without_a_number_returns_the_current_version(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    service.add_version(document.id, PDF, "application/pdf", ADMIN)
    service.add_version(document.id, b"ultimo", "application/pdf", ADMIN)
    data, content_type, filename = service.download(document.id, None, ADMIN)
    assert data == b"ultimo"
    assert content_type == "application/pdf"
    assert filename.endswith(".pdf")


def test_download_of_a_document_with_no_version_raises_not_found(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    with pytest.raises(NotFound):
        service.download(document.id, None, ADMIN)


def test_an_unallowed_content_type_is_refused(
    service: DocumentService, customer: Customer
) -> None:
    # The content type is chosen from a fixed allowlist, never echoed from the
    # request: a caller-supplied value reaches a Content-Disposition header later.
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="X"), ADMIN
    )
    with pytest.raises(ValidationFailed) as excinfo:
        service.add_version(document.id, b"<script>", "text/html", ADMIN)
    assert excinfo.value.details["field"] == "content_type"


def test_the_storage_key_carries_the_customer_slug_and_id_fragment(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    version = service.add_version(document.id, PDF, "application/pdf", ADMIN)
    prefix = f"acme-s-r-l-{str(customer.id)[:8]}"
    assert version.storage_key == f"{prefix}/{document.id}/v1.pdf"


def test_a_customer_rename_does_not_change_an_existing_key(
    service: DocumentService, customer: Customer, db_session: Session
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="Offerta"), ADMIN
    )
    first = service.add_version(document.id, PDF, "application/pdf", ADMIN)
    customer.ragione_sociale = "Nuovo Nome"
    db_session.flush()
    assert service.download(document.id, 1, ADMIN)[0] == PDF
    assert first.storage_key.startswith("acme-s-r-l-")


def test_update_changes_the_title_and_clears_it_with_an_empty_string(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="Vecchio"), ADMIN
    )
    assert service.update(document.id, DocumentUpdate(titolo="Nuovo"), ADMIN).titolo == "Nuovo"


def test_soft_delete_hides_the_document_from_the_list(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="X"), ADMIN
    )
    service.soft_delete(document.id, ADMIN)
    assert service.list(DocumentListQuery(customer_id=customer.id), ADMIN).items == []
    assert service.restore(document.id, ADMIN).titolo == "X"


def test_soft_delete_keeps_the_bytes_so_a_restore_is_a_real_restore(
    service: DocumentService, customer: Customer
) -> None:
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="X"), ADMIN
    )
    service.add_version(document.id, PDF, "application/pdf", ADMIN)
    service.soft_delete(document.id, ADMIN)
    service.restore(document.id, ADMIN)
    assert service.download(document.id, 1, ADMIN)[0] == PDF


def test_list_filters_by_customer_and_by_deal(
    service: DocumentService, customer: Customer, db_session: Session
) -> None:
    stage = PipelineService(db_session).seed_defaults(ADMIN)[0]
    deal = Deal(nome="D", customer_id=customer.id, pipeline_stage_id=stage.id)
    db_session.add(deal)
    db_session.flush()
    service.create(DocumentCreate(customer_id=customer.id, tipo="documento", titolo="C"), ADMIN)
    service.create(DocumentCreate(deal_id=deal.id, tipo="offerta", titolo="D"), ADMIN)
    assert [d.titolo for d in service.list(DocumentListQuery(customer_id=customer.id), ADMIN).items] == ["C"]
    assert [d.titolo for d in service.list(DocumentListQuery(deal_id=deal.id), ADMIN).items] == ["D"]


def test_list_limit_is_bounded(service: DocumentService) -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        DocumentListQuery(limit=1000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_documents_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.documents.service'`

- [ ] **Step 3: Finish the schemas**

Append to `packages/core/src/pigrocrm/core/documents/schemas.py`:

```python
from datetime import datetime

from pydantic import ConfigDict

# The content type is chosen from this allowlist, never echoed from the request: the
# value reaches a `Content-Disposition` header and a browser's own sniffing later, and
# `text/html` there is a stored XSS with the CRM's own origin behind it.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

CONTENT_TYPE_MAX_LENGTH = 100
STORAGE_KEY_MAX_LENGTH = 255
# Postgres `Integer` tops out at 2**31-1; 100 MB is far below it and is a defensible
# ceiling for a document nobody wants to email either.
DIMENSIONE_MAX = 100 * 1024 * 1024


class DocumentUpdate(BaseModel):
    """`stato` is deliberately absent: an offer's state changes only through
    `DocumentService.set_offer_state`, which takes a required non-nullable literal.
    That keeps this slice clear of the A14 defect -- `model_dump(exclude_none=True)`
    drops a `None`, so a nullable typed column on an Update schema has no spelling
    that means "clear it"."""

    model_config = ConfigDict(extra="forbid")

    titolo: SafeStr | None = Field(default=None, max_length=TITOLO_MAX_LENGTH)
    custom_fields: dict[str, Any] | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID | None
    deal_id: UUID | None
    tipo: str
    titolo: str
    stato: str | None
    versione_corrente: int
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    numero: int
    template_id: UUID | None
    storage_key: str
    content_type: str
    dimensione: int
    hash_sha256: str
    creato_da: UUID | None
    created_at: datetime


class DocumentListQuery(BaseModel):
    customer_id: UUID | None = None
    deal_id: UUID | None = None
    tipo: DocumentTipo | None = None
    stato: OfferState | None = None
    # Bounded here, not only on the router: the MCP tool builds this object directly.
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class DocumentPage(BaseModel):
    items: list[DocumentRead]
    next_cursor: UUID | None
```

- [ ] **Step 4: Write the repository**

```python
# packages/core/src/pigrocrm/core/documents/repository.py
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.documents.schemas import DocumentListQuery


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: UUID, *, include_deleted: bool = False) -> Document | None:
        document = self.session.get(Document, document_id)
        if document is None:
            return None
        if document.deleted_at is not None and not include_deleted:
            return None
        return document

    def add(self, document: Document) -> Document:
        self.session.add(document)
        self.session.flush()
        return document

    def add_version(self, version: DocumentVersion) -> DocumentVersion:
        self.session.add(version)
        self.session.flush()
        return version

    def version(self, document_id: UUID, numero: int) -> DocumentVersion | None:
        stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id, DocumentVersion.numero == numero
        )
        return self.session.execute(stmt).scalars().first()

    def versions(self, document_id: UUID) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(desc(DocumentVersion.numero))
        )
        return list(self.session.execute(stmt).scalars())

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
        if query.cursor:
            stmt = stmt.where(Document.id > query.cursor)
        # Keyset pagination on a UUIDv7 id: ordered by creation, stable under inserts.
        return list(
            self.session.execute(stmt.order_by(Document.id).limit(query.limit + 1)).scalars()
        )
```

- [ ] **Step 5: Write the service**

```python
# packages/core/src/pigrocrm/core/documents/service.py
import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.documents.schemas import (
    ALLOWED_CONTENT_TYPES,
    DIMENSIONE_MAX,
    DocumentCreate,
    DocumentListQuery,
    DocumentPage,
    DocumentRead,
    DocumentUpdate,
    DocumentVersionRead,
)
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.storage.base import DocumentStorage

ENTITY: EntityType = "document"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_CUSTOMER_ID_FRAGMENT = 8


def slugify_folder(raw: str) -> str:
    """A customer name as a storage folder segment.

    Mirrors `fields/schemas.slugify_key` in spirit -- NFKD, drop the combining marks,
    collapse the rest -- but joins with "-" rather than "_", because these segments are
    read by a human browsing Google Drive, which is the whole point of "chi migra da
    Acme ritrova le sue cartelle" (spec 5).
    """
    decomposed = unicodedata.normalize("NFKD", raw)
    transliterated = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SLUG_STRIP.sub("-", transliterated.strip().lower()).strip("-") or "senza-nome"


class DocumentService:
    def __init__(self, session: Session, storage: DocumentStorage) -> None:
        self.session = session
        self.storage = storage
        self.repo = DocumentRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)

    # ---- owner resolution ---------------------------------------------------

    def _check_owner(self, customer_id: UUID | None, deal_id: UUID | None) -> None:
        """Exactly one owner, and it must exist.

        The database check constraint is the second line under concurrency; this is
        the first, and it is what turns a syntactically valid but unknown UUID into
        this project's own `NotFound` instead of a raw `ForeignKeyViolation`.
        """
        if (customer_id is None) == (deal_id is None):
            raise ValidationFailed(
                ENTITY,
                "customer_id",
                "un documento appartiene a un cliente oppure a un deal, mai a entrambi",
                expected="esattamente uno fra customer_id e deal_id",
            )
        if customer_id is not None and self.session.get(Customer, customer_id) is None:
            raise NotFound("customer", customer_id)
        if deal_id is not None and self.session.get(Deal, deal_id) is None:
            raise NotFound("deal", deal_id)

    def _customer_of(self, document: Document) -> Customer | None:
        if document.customer_id is not None:
            return self.session.get(Customer, document.customer_id)
        deal = self.session.get(Deal, document.deal_id) if document.deal_id else None
        return self.session.get(Customer, deal.customer_id) if deal else None

    def storage_key_for(self, document: Document, numero: int, content_type: str) -> str:
        """`{cliente-slug}-{id[:8]}/{document_id}/v{numero}{ext}`.

        The customer-id fragment is what keeps the folder stable when a customer is
        renamed -- the slug alone would send the next version into a different folder
        and orphan the earlier ones. The slug is what makes the folder legible to a
        human browsing Drive.
        """
        customer = self._customer_of(document)
        folder = (
            f"{slugify_folder(customer.ragione_sociale)}-{str(customer.id)[:_CUSTOMER_ID_FRAGMENT]}"
            if customer
            else "senza-cliente"
        )
        return f"{folder}/{document.id}/v{numero}{ALLOWED_CONTENT_TYPES[content_type]}"

    # ---- custom fields ------------------------------------------------------

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def _update_custom_fields(self, document: Document, provided: dict[str, Any]) -> dict[str, Any]:
        """Validates only the keys the caller is touching, never the merge with what
        is stored. Identical to `CustomerService._update_custom_fields`; see that
        method's docstring for the archiving contract this preserves."""
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
        merged = {k: v for k, v in document.custom_fields.items() if k not in to_remove}
        merged.update(validate_custom_fields(ENTITY, touched, to_set))
        return merged

    # ---- documents ----------------------------------------------------------

    def create(self, data: DocumentCreate, actor: Actor) -> DocumentRead:
        actor.require_write("create_document")
        payload = data.model_dump()
        self._check_owner(payload["customer_id"], payload["deal_id"])
        # Only an offer has a state; everything else keeps NULL. A new offer starts as
        # a draft rather than stateless, so the Kanban-style state picker always has a
        # value to show.
        payload["stato"] = (payload.get("stato") or "bozza") if payload["tipo"] == "offerta" else None
        payload["custom_fields"] = self._validated_custom(payload.get("custom_fields") or {})

        document = self.repo.add(Document(**payload))
        self.activities.record(
            ENTITY, document.id, "created", actor, {"titolo": document.titolo, "tipo": document.tipo}
        )
        self.session.commit()
        return DocumentRead.model_validate(document)

    def update(self, document_id: UUID, data: DocumentUpdate, actor: Actor) -> DocumentRead:
        actor.require_write("update_document")
        document = self._require(document_id)
        changes = data.model_dump(exclude_none=True, exclude={"custom_fields"})
        if data.custom_fields is not None:
            changes["custom_fields"] = self._update_custom_fields(document, data.custom_fields)
        for key, value in changes.items():
            setattr(document, key, value)
        self.activities.record(ENTITY, document.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return DocumentRead.model_validate(document)

    def get(self, document_id: UUID, actor: Actor) -> DocumentRead:
        return DocumentRead.model_validate(self._require(document_id))

    def soft_delete(self, document_id: UUID, actor: Actor) -> None:
        """Sets `deleted_at`. The stored bytes are left alone: a restore that came
        back without the file would not be a restore."""
        actor.require_write("delete_document")
        document = self._require(document_id)
        document.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, document.id, "deleted", actor)
        self.session.commit()

    def restore(self, document_id: UUID, actor: Actor) -> DocumentRead:
        actor.require_write("restore_document")
        document = self.repo.get(document_id, include_deleted=True)
        if document is None:
            raise NotFound(ENTITY, document_id)
        was_deleted = document.deleted_at is not None
        document.deleted_at = None
        if was_deleted:
            self.activities.record(ENTITY, document.id, "restored", actor)
        self.session.commit()
        return DocumentRead.model_validate(document)

    # ---- versions -----------------------------------------------------------

    def add_version(
        self,
        document_id: UUID,
        data: bytes,
        content_type: str,
        actor: Actor,
        *,
        sorgente_markdown: str | None = None,
        template_id: UUID | None = None,
        variabili: dict[str, Any] | None = None,
    ) -> DocumentVersionRead:
        """Every change makes a version; nothing is overwritten (spec 4.2).

        The bytes are written to storage *before* the commit and left in place if the
        commit then fails: an orphaned blob costs disk, while a row pointing at bytes
        that were never written is a download that 500s forever.
        """
        actor.require_write("add_document_version")
        document = self._require(document_id)
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValidationFailed(
                ENTITY,
                "content_type",
                f"tipo di file non ammesso: {content_type}",
                expected=", ".join(sorted(ALLOWED_CONTENT_TYPES)),
            )
        if not data:
            raise ValidationFailed(ENTITY, "file", "il file e' vuoto", expected="almeno un byte")
        if len(data) > DIMENSIONE_MAX:
            raise ValidationFailed(
                ENTITY,
                "dimensione",
                f"il file supera {DIMENSIONE_MAX} byte",
                expected=f"al massimo {DIMENSIONE_MAX} byte",
            )

        numero = document.versione_corrente + 1
        key = self.storage_key_for(document, numero, content_type)
        self.storage.put(key, data, content_type)

        version = self.repo.add_version(
            DocumentVersion(
                document_id=document.id,
                numero=numero,
                sorgente_markdown=sorgente_markdown,
                template_id=template_id,
                variabili=variabili,
                storage_key=key,
                content_type=content_type,
                dimensione=len(data),
                hash_sha256=hashlib.sha256(data).hexdigest(),
                creato_da=actor.id,
            )
        )
        document.versione_corrente = numero
        self.activities.record(ENTITY, document.id, "version_added", actor, {"numero": numero})
        self.session.commit()
        return DocumentVersionRead.model_validate(version)

    def versions(self, document_id: UUID, actor: Actor) -> list[DocumentVersionRead]:
        self._require(document_id)
        return [
            DocumentVersionRead.model_validate(v) for v in self.repo.versions(document_id)
        ]

    def download(
        self, document_id: UUID, numero: int | None, actor: Actor
    ) -> tuple[bytes, str, str]:
        """`(bytes, content_type, filename)`.

        The filename is built from the document's title, slugified: the title is user
        input and reaches a `Content-Disposition` header, where a quote or a newline
        would be header injection.
        """
        document = self._require(document_id)
        wanted = numero if numero is not None else document.versione_corrente
        version = self.repo.version(document_id, wanted) if wanted else None
        if version is None:
            raise NotFound("document_version", f"{document_id}#{wanted}")
        extension = ALLOWED_CONTENT_TYPES[version.content_type]
        filename = f"{slugify_folder(document.titolo)}-v{version.numero}{extension}"
        return self.storage.get(version.storage_key), version.content_type, filename

    def _require(self, document_id: UUID) -> Document:
        document = self.repo.get(document_id)
        if document is None:
            raise NotFound(ENTITY, document_id)
        return document

    # `list` must stay the last method defined in this class -- an unconditional
    # project rule. `def list` rebinds the name in the class namespace, so any later
    # method annotated `-> list[...]` would fail at import time on Python 3.13.
    def list(self, query: DocumentListQuery, actor: Actor) -> DocumentPage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return DocumentPage(
            items=[DocumentRead.model_validate(d) for d in items],
            next_cursor=items[-1].id if has_more and items else None,
        )
```

- [ ] **Step 6: Run the test**

Run: `cd packages/core && uv run pytest tests/test_documents_service.py tests/test_module_imports.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/documents packages/core/tests/test_documents_service.py
git commit -m "feat(documents): document service with immutable version history"
```

---

### Task 10: The PDF renderer — Pandoc and Typst, with template-line diagnostics

**Files:**
- Create: `packages/core/src/pigrocrm/core/render/__init__.py`, `packages/core/src/pigrocrm/core/render/diagnostics.py`, `packages/core/src/pigrocrm/core/render/pdf.py`
- Create: `packages/core/src/pigrocrm/core/render/assets/pandoc-template.typst` (copy of `.reference-acme/offer/pandoc-template.typst`, unmodified)
- Create: `packages/core/src/pigrocrm/core/render/assets/header.typ.template`
- Create: `packages/core/src/pigrocrm/core/render/assets/media/` (copy of `.reference-acme/offer/media/`)
- Create: `packages/core/src/pigrocrm/core/render/assets/template-offer.md` (the carried-over legal body, placeholders rewritten)
- Modify: `Dockerfile.api:1-6`
- Modify: `packages/core/pyproject.toml` (package data)
- Test: `packages/core/tests/test_render_diagnostics.py`, `packages/core/tests/test_render_pdf.py`

**Interfaces:**
- Consumes: `TYPST_LINE_MARKER_PREFIX` from `pigrocrm.core.templates.renderer`; `Settings` from `pigrocrm.core.config`.
- Produces:
  - `RENDER_TIMEOUT_SECONDS: int = 30`
  - `ASSETS_DIR: Path`
  - `template_line_for(typst_source: str, typst_line: int) -> int | None`
  - `translate_typst_failure(stderr: str, typst_source: str) -> str`
  - `render_pdf(markdown: str, *, header_typst: str, settings: Settings) -> bytes`
  - `build_header(profile: dict[str, Any]) -> str`

- [ ] **Step 1: Write the failing diagnostics test**

```python
# packages/core/tests/test_render_diagnostics.py
from pigrocrm.core.render.diagnostics import template_line_for, translate_typst_failure

TYPST_SOURCE = """#set page(margin: 1in)

// pigrocrm:line=12
#table(
  columns: (1fr,),
  [#import "x"],
)

// pigrocrm:line=40
#text[ok]
"""

TYPST_STDERR = """error: unexpected keyword `import`
  ┌─ /tmp/pigrocrm-render-abc/intermediate.typ:6:4
  │
6 │   [#import "x"],
  │    ^^^^^^^
"""


def test_template_line_is_the_marker_plus_the_offset_inside_the_block() -> None:
    # Marker on typst line 3 names template line 12, so typst line 6 is template
    # line 12 + (6 - 3 - 1) = 14. Pandoc copies a raw block through verbatim, line
    # for line, which is what makes the arithmetic exact rather than approximate.
    assert template_line_for(TYPST_SOURCE, 6) == 14


def test_template_line_uses_the_nearest_preceding_marker() -> None:
    assert template_line_for(TYPST_SOURCE, 10) == 40


def test_template_line_is_none_before_any_marker() -> None:
    assert template_line_for(TYPST_SOURCE, 1) is None


def test_translate_names_the_template_line_and_the_compiler_message() -> None:
    message = translate_typst_failure(TYPST_STDERR, TYPST_SOURCE)
    assert "riga 14" in message
    assert "unexpected keyword `import`" in message


def test_translate_never_leaks_the_temporary_path() -> None:
    # The path names a directory on the server and is meaningless to the user.
    assert "/tmp/pigrocrm-render-abc" not in translate_typst_failure(TYPST_STDERR, TYPST_SOURCE)


def test_translate_falls_back_when_there_is_no_location() -> None:
    message = translate_typst_failure("error: file not found\n", TYPST_SOURCE)
    assert "file not found" in message
    assert "riga" not in message


def test_translate_falls_back_when_stderr_is_empty() -> None:
    assert "compilazione" in translate_typst_failure("", TYPST_SOURCE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_render_diagnostics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pigrocrm.core.render'`

- [ ] **Step 3: Write `diagnostics.py`**

```python
# packages/core/src/pigrocrm/core/render/diagnostics.py
"""Turn a Typst compiler error into "riga N del template".

Spec 6: "Se Typst fallisce, l'errore che torna all'utente contiene la riga del
template che l'ha causato, non lo stderr grezzo del compilatore."

The mechanism is arithmetic, not guesswork. `templates/parser.py` inserts
`// pigrocrm:line=<N>` as the first line inside every raw ```{=typst} block. Pandoc
copies a raw block through **verbatim, line for line**, so that comment survives into
the intermediate .typ at a known offset. Given an error at .typ line L, the nearest
preceding marker at .typ line M naming template line N puts the offending template
line at exactly `N + (L - M - 1)`.
"""

import re

from pigrocrm.core.templates.renderer import TYPST_LINE_MARKER_PREFIX

# Typst 0.11 renders a diagnostic as:
#     error: unexpected keyword `import`
#       ┌─ /path/to/intermediate.typ:6:4
_ERROR_RE = re.compile(r"^error: (?P<message>.+)$", re.MULTILINE)
_LOCATION_RE = re.compile(r"┌─\s*\S+?:(?P<line>\d+):(?P<column>\d+)")
_MARKER_RE = re.compile(rf"^\s*{re.escape(TYPST_LINE_MARKER_PREFIX)}(?P<line>\d+)\s*$")


def template_line_for(typst_source: str, typst_line: int) -> int | None:
    """The template line that produced line `typst_line` of the intermediate .typ."""
    lines = typst_source.splitlines()
    for index in range(min(typst_line, len(lines)) - 1, -1, -1):
        match = _MARKER_RE.match(lines[index])
        if match:
            marker_typst_line = index + 1
            return int(match.group("line")) + (typst_line - marker_typst_line - 1)
    return None


def translate_typst_failure(stderr: str, typst_source: str) -> str:
    """A message for a human, never the compiler's raw output.

    The temporary path in Typst's own location line is dropped: it names a directory
    on the server, is different on every render, and tells the user nothing. The raw
    stderr belongs in the server log, which is where the caller of `render_pdf` puts
    it.
    """
    error = _ERROR_RE.search(stderr)
    message = error.group("message").strip() if error else ""
    location = _LOCATION_RE.search(stderr)
    if location:
        line = template_line_for(typst_source, int(location.group("line")))
        if line is not None:
            return f"errore nella riga {line} del template: {message or 'sintassi Typst non valida'}"
    if message:
        return f"errore di composizione del PDF: {message}"
    return "errore di composizione del PDF: la compilazione Typst e' fallita senza dettagli"
```

- [ ] **Step 4: Write the failing renderer test**

```python
# packages/core/tests/test_render_pdf.py
import shutil

import pytest

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.render.pdf import ASSETS_DIR, build_header, render_pdf

pytestmark = pytest.mark.skipif(
    shutil.which("pandoc") is None or shutil.which("typst") is None,
    reason="pandoc e typst vivono nell'immagine dell'API (Dockerfile.api)",
)

SETTINGS = Settings(jwt_secret="x" * 32)
PROFILE = {
    "ragione_sociale": "Humancraft di Ivan Sala",
    "partita_iva": "14518240966",
    "email": "ivansala@humancraft.tech",
    "telefono": "+39 02 1234567",
    "pec": "someone@example.com",
    "sito_web": "www.humancraft.tech",
    "indirizzo": "Via Roma 1",
    "cap": "20053",
    "comune": "Milano",
    "provincia": "MI",
}


def test_a_minimal_document_renders_to_a_pdf() -> None:
    pdf = render_pdf("# Titolo\n\nCorpo.\n", header_typst=build_header(PROFILE), settings=SETTINGS)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_the_emitter_profile_reaches_the_header() -> None:
    header = build_header(PROFILE)
    assert "Humancraft di Ivan Sala" in header
    assert "14518240966" in header
    # The `@` in an email is Typst syntax for a reference and must arrive escaped.
    assert r"ivansala\@humancraft.tech" in header


def test_a_broken_raw_typst_block_names_the_template_line() -> None:
    markdown = "Testo\n\n```{=typst}\n// pigrocrm:line=7\n#nonesiste(\n```\n"
    with pytest.raises(ValidationFailed) as excinfo:
        render_pdf(markdown, header_typst=build_header(PROFILE), settings=SETTINGS)
    assert "riga 7" in excinfo.value.details["reason"]


def test_the_error_never_contains_the_temporary_directory() -> None:
    markdown = "```{=typst}\n// pigrocrm:line=3\n#nonesiste(\n```\n"
    with pytest.raises(ValidationFailed) as excinfo:
        render_pdf(markdown, header_typst=build_header(PROFILE), settings=SETTINGS)
    assert "/tmp/" not in excinfo.value.details["reason"]


def test_no_temporary_directory_survives_a_success_or_a_failure(tmp_path: object) -> None:
    import tempfile
    from pathlib import Path

    before = {p.name for p in Path(tempfile.gettempdir()).glob("pigrocrm-render-*")}
    render_pdf("ok\n", header_typst=build_header(PROFILE), settings=SETTINGS)
    with pytest.raises(ValidationFailed):
        render_pdf(
            "```{=typst}\n// pigrocrm:line=2\n#nonesiste(\n```\n",
            header_typst=build_header(PROFILE),
            settings=SETTINGS,
        )
    after = {p.name for p in Path(tempfile.gettempdir()).glob("pigrocrm-render-*")}
    assert after == before


def test_the_media_assets_are_reachable_from_the_rendered_document() -> None:
    assert (ASSETS_DIR / "media" / "sign_is.png").is_file()
    pdf = render_pdf(
        "![](./media/sign_is.png){ width=90pt }\n",
        header_typst=build_header(PROFILE),
        settings=SETTINGS,
    )
    assert pdf.startswith(b"%PDF")


def test_a_value_that_looks_like_a_shell_argument_is_just_text() -> None:
    # No user input ever reaches a command line: the value travels in the source file.
    pdf = render_pdf(
        "Cliente: `--output=/etc/passwd`\n",
        header_typst=build_header(PROFILE),
        settings=SETTINGS,
    )
    assert pdf.startswith(b"%PDF")
```

- [ ] **Step 5: Copy the Acme assets and write the header template**

```bash
mkdir -p packages/core/src/pigrocrm/core/render/assets/media
cp /Users/ivansala/emdash/repositories/pigrocrm/.reference-acme/offer/pandoc-template.typst \
   packages/core/src/pigrocrm/core/render/assets/pandoc-template.typst
cp /Users/ivansala/emdash/repositories/pigrocrm/.reference-acme/offer/media/*.png \
   packages/core/src/pigrocrm/core/render/assets/media/
```

Create `packages/core/src/pigrocrm/core/render/assets/header.typ.template` — this is Acme's `offer/header.typ` with every hardcoded issuer datum replaced by a placeholder the same engine fills in (`{{emittente.*}}`), which is exactly what the emitter profile exists for:

```
#set page(
  margin: (x: 1.25in, y: 1.25in),
  numbering: "1",
  header: [
    #grid(
      columns: (auto, 1fr),
      column-gutter: 0.6cm,
      [
        #box(inset: (top: 20pt))[
          #image("./media/logo.png", width: 60pt)
        ]
      ],
      [
        #align(right)[
          #text(size: 8pt)[
            {{emittente.ragione_sociale}} \
            P.IVA {{emittente.partita_iva}}
          ]
        ]
      ],
    )
  ],
  footer: [
    #align(left)[
      #text(size: 7pt)[
        contatti: {{emittente.email}} | {{emittente.telefono}} | {{emittente.pec}} \
        web: {{emittente.sito_web}} \
        sede: {{emittente.indirizzo}}, {{emittente.comune}}, {{emittente.cap}}, {{emittente.provincia}}
      ]
    ]
  ],
)
```

Rename the logo so the header does not hardcode a brand: `mv packages/core/src/pigrocrm/core/render/assets/media/humancraftTech-logo-nobg.png packages/core/src/pigrocrm/core/render/assets/media/logo.png`.

Also create `packages/core/src/pigrocrm/core/render/assets/template-offer.md` — a copy of `.reference-acme/offer/template-offer.md` with the legal text carried over **verbatim** and only the placeholder syntax rewritten, plus `Humancraft di Ivan Sala` replaced by `{{emittente.ragione_sociale}}` throughout. The mapping, applied literally:

| Acme | PigroCRM |
|---|---|
| `[DATA_OFFERTA]` | `{{offerta.data}}` |
| `[NOME_CLIENTE]` | `{{cliente.ragione_sociale}}` |
| `[INDIRIZZO_CLIENTE]` | `{{cliente.indirizzo}}` |
| `[VAT_NUMBER]` | `{{cliente.partita_iva}}` |
| `[REFERENTE_NOME]` | `{{referente.nome}}` |
| `[REFERENTE_EMAIL]` | `{{referente.email}}` |
| `[OGGETTO]` | `{{offerta.oggetto}}` |
| `[AMBITO_PROGETTO_E_OBIETTIVI]` | `{{offerta.ambito}}` |
| `[ATTIVITA_EXTENDED]` | `{{offerta.attivita}}` |
| `[SERVIZIO_ATTIVITA]` / `[TOTALE]` | `{{#each offerta.righe}} … {{/each}}` over `{{servizio}}` / `{{totale}}` |
| `[MODALITA_FATTURAZIONE_E_PAGAMENTO]` | `{{offerta.pagamento}}` |
| `Humancraft di Ivan Sala` (9 occurrences) | `{{emittente.ragione_sociale}}` |
| the fixed forfettario sentence | `{{emittente.regime_fiscale}}` |
| `![](./media/sign_is.png){ width=90pt }` | unchanged |

The cost table becomes a loop, which is the point of having `#each` at all — Acme needed one template per number of cost lines:

````
```{=typst}
#table(
  columns: (0.8fr, 0.2fr),
  align: (auto, center),
  stroke: none,
  table.header([#strong[Servizio/Attività]], [#strong[Totale]]),
  {{#each offerta.righe}}[{{servizio}}], [{{totale}}],{{/each}}
)
```
````

- [ ] **Step 6: Write `pdf.py`**

```python
# packages/core/src/pigrocrm/core/render/pdf.py
"""Pandoc, then Typst. Two subprocesses, no shell, no user input on either argv.

Acme ran a single `pandoc --pdf-engine=typst`. This runs the two stages separately
so the intermediate .typ exists as a file we own -- which is the only way to satisfy
spec 6's "l'errore contiene la riga del template", because Typst's diagnostics name a
line in that file and nothing else can map it back.

Every path in either argument list is generated here from `tempfile.mkdtemp()`. Every
value a user or an agent supplied is already inside `markdown`, already escaped by
`pigrocrm.core.templates.renderer`. There is no code path in this module where a
request-derived string becomes a command-line argument.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.render.diagnostics import translate_typst_failure
from pigrocrm.core.templates.renderer import render_template

ENTITY = "document"
RENDER_TIMEOUT_SECONDS = 30
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PANDOC_TEMPLATE = ASSETS_DIR / "pandoc-template.typst"
HEADER_TEMPLATE = ASSETS_DIR / "header.typ.template"
# Acme's own reader extensions, carried over unchanged: `raw_attribute` is what makes
# ```{=typst} a raw block rather than a code listing, and without it the whole
# two-context escaping design has only one context.
PANDOC_FROM = "markdown+link_attributes+pipe_tables+raw_attribute"
# Typst 0.11 embeds Libertinus Serif, so no font package is needed in the image.
MAIN_FONT = "Libertinus Serif"


def build_header(profile: dict[str, Any]) -> str:
    """The Typst page header, filled from the emitter profile.

    Rendered through the same engine as the document body, so the issuer's own values
    get the same Typst escaping -- an `@` in an email address is a Typst reference and
    would otherwise fail the compile, which is precisely the bug Acme's `header.typ`
    worked around by hand-writing `ivansala\\@humancraft.tech` in the source.
    """
    return render_template(
        HEADER_TEMPLATE.read_text(encoding="utf-8"), {"emittente": profile}
    )


def _run(argv: list[str], workdir: Path) -> subprocess.CompletedProcess[bytes]:
    """Always a list, never a string; never `shell=True`; always bounded.

    `check=False` on purpose: the whole point is to read the compiler's diagnostics
    and translate them, which `check=True` would replace with a `CalledProcessError`
    nobody can render for a user.
    """
    try:
        return subprocess.run(
            argv,
            cwd=workdir,
            capture_output=True,
            check=False,
            timeout=RENDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationFailed(
            ENTITY,
            "corpo_markdown",
            f"la composizione del PDF ha superato {RENDER_TIMEOUT_SECONDS} secondi",
            expected="un documento piu' semplice",
        ) from exc
    except FileNotFoundError as exc:
        raise ValidationFailed(
            ENTITY,
            "render",
            f"strumento di composizione non installato: {argv[0]}",
            expected="pandoc e typst nell'immagine dell'API",
        ) from exc


def render_pdf(markdown: str, *, header_typst: str, settings: Settings) -> bytes:
    """Compiled Markdown in, PDF bytes out.

    The whole render happens inside one throwaway directory that is removed on every
    path, success or failure. `media/` is copied in rather than referenced in place,
    so `--root` can be the workdir: a shared, possibly read-only assets directory as
    `--root` would let two concurrent renders write into the same place.
    """
    workdir = Path(tempfile.mkdtemp(prefix="pigrocrm-render-"))
    try:
        shutil.copytree(ASSETS_DIR / "media", workdir / "media")
        source = workdir / "source.md"
        header = workdir / "header.typ"
        intermediate = workdir / "intermediate.typ"
        output = workdir / "out.pdf"
        source.write_text(markdown, encoding="utf-8")
        header.write_text(header_typst, encoding="utf-8")

        pandoc = _run(
            [
                settings.pandoc_binary,
                f"--from={PANDOC_FROM}",
                "--to=typst",
                "--standalone",
                "--template",
                str(PANDOC_TEMPLATE),
                "--include-in-header",
                str(header),
                "--resource-path",
                str(workdir),
                "-V",
                f"mainfont={MAIN_FONT}",
                "-o",
                str(intermediate),
                str(source),
            ],
            workdir,
        )
        if pandoc.returncode != 0:
            raise ValidationFailed(
                ENTITY,
                "corpo_markdown",
                "il Markdown del documento non e' convertibile",
                expected="Markdown valido",
            )

        typst_source = intermediate.read_text(encoding="utf-8")
        typst = _run(
            [
                settings.typst_binary,
                "compile",
                "--root",
                str(workdir),
                str(intermediate),
                str(output),
            ],
            workdir,
        )
        if typst.returncode != 0 or not output.is_file():
            raise ValidationFailed(
                ENTITY,
                "corpo_markdown",
                translate_typst_failure(typst.stderr.decode("utf-8", "replace"), typst_source),
                expected="un template Typst valido",
            )
        return output.read_bytes()
    finally:
        # `ignore_errors=True`: a failed cleanup must never mask the real error, and
        # the directory is disposable by construction.
        shutil.rmtree(workdir, ignore_errors=True)
```

```python
# packages/core/src/pigrocrm/core/render/__init__.py
from pigrocrm.core.render.diagnostics import template_line_for, translate_typst_failure
from pigrocrm.core.render.pdf import (
    ASSETS_DIR,
    RENDER_TIMEOUT_SECONDS,
    build_header,
    render_pdf,
)

__all__ = [
    "ASSETS_DIR",
    "RENDER_TIMEOUT_SECONDS",
    "build_header",
    "render_pdf",
    "template_line_for",
    "translate_typst_failure",
]
```

- [ ] **Step 7: Install Pandoc and Typst in the API image**

Replace `Dockerfile.api` lines 1–6 with:

```dockerfile
FROM python:3.13-slim-bookworm

# Pinned to the exact versions the carried-over Typst template and header are known to
# compile under (.reference-acme/Dockerfile:3-4). Typst 0.11 embeds Libertinus Serif,
# so no font package is needed.
ARG TYPST_VERSION=0.11.0
ARG PANDOC_VERSION=3.1.12.2

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq5 ca-certificates curl xz-utils \
    && curl -fL "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz" \
       | tar -xz -C /tmp \
    && mv /tmp/pandoc-${PANDOC_VERSION}/bin/pandoc /usr/local/bin/pandoc \
    && chmod +x /usr/local/bin/pandoc \
    && curl -fL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-x86_64-unknown-linux-musl.tar.xz" \
       | tar -xJ -C /tmp \
    && mv /tmp/typst-x86_64-unknown-linux-musl/typst /usr/local/bin/typst \
    && chmod +x /usr/local/bin/typst \
    && apt-get purge -y curl xz-utils && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/pandoc-${PANDOC_VERSION} /tmp/typst-x86_64-unknown-linux-musl
```

Add the assets to the wheel by appending to `packages/core/pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/pigrocrm/core/render/assets" = "pigrocrm/core/render/assets"
```

- [ ] **Step 8: Run the diagnostics test (it needs no binaries) and the renderer test**

Run: `cd packages/core && uv run pytest tests/test_render_diagnostics.py -v`
Expected: PASS

Run: `cd packages/core && uv run pytest tests/test_render_pdf.py -v`
Expected: PASS if `pandoc` and `typst` are on `PATH`; otherwise every test in the file is reported as skipped, which is correct on a developer machine — the binaries live in the API image. **Do not delete the skip guard to make the file "pass"**: it exists so CI, which builds the image, runs these for real.

- [ ] **Step 9: Commit**

```bash
git add packages/core/src/pigrocrm/core/render packages/core/tests/test_render_diagnostics.py \
        packages/core/tests/test_render_pdf.py Dockerfile.api packages/core/pyproject.toml
git commit -m "feat(render): pandoc+typst pipeline with template-line diagnostics"
```

---

### Task 11: `create_document_from_template`, regeneration, and offer states

**Files:**
- Modify: `packages/core/src/pigrocrm/core/documents/service.py`
- Modify: `packages/core/src/pigrocrm/core/documents/schemas.py`
- Test: `packages/core/tests/test_documents_from_template.py`

**Interfaces:**
- Consumes: `TemplateService`, `EmitterProfileService`, `render_template`, `render_pdf`, `build_header`, `Settings`.
- Produces, on `DocumentService`:
  - `__init__(self, session: Session, storage: DocumentStorage, settings: Settings | None = None)`
  - `create_from_template(self, data: DocumentFromTemplate, actor: Actor) -> DocumentRead`
  - `regenerate(self, document_id: UUID, numero: int, actor: Actor) -> DocumentVersionRead`
  - `set_offer_state(self, document_id: UUID, stato: OfferState, actor: Actor) -> DocumentRead`
  - `OFFER_TRANSITIONS: dict[str, frozenset[str]]`
  - `class DocumentFromTemplate(BaseModel)` in `documents/schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/core/tests/test_documents_from_template.py
import shutil
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.documents.schemas import DocumentCreate, DocumentFromTemplate
from pigrocrm.core.documents.service import OFFER_TRANSITIONS, DocumentService
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm.core.templates.schemas import TemplateCreate, TemplateVariable
from pigrocrm.core.templates.service import TemplateService

ADMIN = Actor(id=None, type="system", role="admin")
needs_binaries = pytest.mark.skipif(
    shutil.which("pandoc") is None or shutil.which("typst") is None,
    reason="pandoc e typst vivono nell'immagine dell'API",
)

BODY = """{{offerta.data}}

Spett.le **{{cliente.ragione_sociale}}**

Oggetto: {{offerta.oggetto}}

```{=typst}
#table(
  columns: (0.8fr, 0.2fr),
  [{{cliente.ragione_sociale}}],
  [{{offerta.oggetto}}],
)
```

{{emittente.ragione_sociale}}
"""


@pytest.fixture
def setup(db_session: Session, tmp_path: Path) -> tuple[DocumentService, Customer, object]:
    EmitterProfileService(db_session).upsert(
        EmitterProfileUpsert(ragione_sociale="Humancraft di Ivan Sala", partita_iva="14518240966"),
        ADMIN,
    )
    template = TemplateService(db_session).create(
        TemplateCreate(
            nome="Consulenza CTO",
            tipo="offerta",
            corpo_markdown=BODY,
            variabili_dichiarate=[
                TemplateVariable(nome="offerta", etichetta="Offerta", obbligatoria=True),
            ],
        ),
        ADMIN,
    )
    customer = Customer(ragione_sociale="ACME S.r.l.")
    db_session.add(customer)
    db_session.flush()
    return DocumentService(db_session, LocalFileStorage(tmp_path)), customer, template


def _payload(customer: Customer, template: object, **overrides: object) -> DocumentFromTemplate:
    values: dict[str, object] = {
        "template_id": template.id,  # type: ignore[attr-defined]
        "customer_id": customer.id,
        "titolo": "Offerta 2026-01",
        "variabili": {"offerta": {"data": "10/08/2026", "oggetto": "Advisory"}},
    }
    values.update(overrides)
    return DocumentFromTemplate(**values)  # type: ignore[arg-type]


@needs_binaries
def test_create_from_template_produces_a_pdf_version(setup: tuple) -> None:
    service, customer, template = setup
    document = service.create_from_template(_payload(customer, template), ADMIN)
    assert document.versione_corrente == 1
    data, content_type, _ = service.download(document.id, None, ADMIN)
    assert data.startswith(b"%PDF")
    assert content_type == "application/pdf"


def test_the_version_keeps_the_template_and_the_variables_for_regeneration(setup: tuple) -> None:
    service, customer, template = setup
    document = service.create_from_template(_payload(customer, template), ADMIN)
    version = service.versions(document.id, ADMIN)[0]
    assert version.template_id == template.id  # type: ignore[attr-defined]
    stored = service.repo.version(document.id, 1)
    assert stored is not None
    assert stored.variabili["offerta"]["oggetto"] == "Advisory"
    assert "Advisory" in stored.sorgente_markdown


def test_the_customer_is_injected_into_the_template_scope(setup: tuple) -> None:
    service, customer, template = setup
    document = service.create_from_template(_payload(customer, template), ADMIN)
    stored = service.repo.version(document.id, 1)
    assert stored is not None
    assert "ACME S.r.l." in stored.sorgente_markdown


def test_an_injecting_customer_name_is_literal_in_both_contexts(
    setup: tuple, db_session: Session
) -> None:
    service, customer, template = setup
    customer.ragione_sociale = '#import "/etc/passwd"'
    db_session.flush()
    document = service.create_from_template(_payload(customer, template), ADMIN)
    stored = service.repo.version(document.id, 1)
    assert stored is not None
    markdown_part, typst_part = stored.sorgente_markdown.split("```{=typst}", 1)
    assert '#import "/etc/passwd"' in markdown_part
    assert r"\#import" in typst_part


def test_a_missing_required_variable_fails_before_anything_is_written(setup: tuple) -> None:
    service, customer, template = setup
    with pytest.raises(ValidationFailed) as excinfo:
        service.create_from_template(_payload(customer, template, variabili={}), ADMIN)
    assert excinfo.value.details["field"] == "offerta"
    assert service.list.__self__ is service  # sanity: the service is intact
    from pigrocrm.core.documents.schemas import DocumentListQuery

    assert service.list(DocumentListQuery(customer_id=customer.id), ADMIN).items == []


def test_an_unknown_template_raises_not_found(setup: tuple) -> None:
    from uuid import uuid4

    service, customer, _ = setup
    with pytest.raises(NotFound):
        service.create_from_template(
            DocumentFromTemplate(
                template_id=uuid4(), customer_id=customer.id, titolo="X", variabili={}
            ),
            ADMIN,
        )


def test_without_an_emitter_profile_the_render_fails_with_a_clear_error(
    setup: tuple, db_session: Session
) -> None:
    from pigrocrm.core.emitter.models import EmitterProfile

    service, customer, template = setup
    db_session.query(EmitterProfile).delete()
    db_session.flush()
    with pytest.raises(NotFound) as excinfo:
        service.create_from_template(_payload(customer, template), ADMIN)
    assert excinfo.value.details["entity"] == "emitter_profile"


@needs_binaries
def test_regenerate_reproduces_an_old_version_as_a_new_one(setup: tuple) -> None:
    service, customer, template = setup
    document = service.create_from_template(_payload(customer, template), ADMIN)
    first = service.repo.version(document.id, 1)
    regenerated = service.regenerate(document.id, 1, ADMIN)
    assert regenerated.numero == 2
    second = service.repo.version(document.id, 2)
    assert second is not None and first is not None
    # Identical source means identical bytes: the whole promise of storing both
    # template_id and variabili (spec 11 criterion 4).
    assert second.sorgente_markdown == first.sorgente_markdown
    assert second.hash_sha256 == first.hash_sha256


def test_regenerate_of_an_uploaded_version_is_refused(setup: tuple, tmp_path: Path) -> None:
    service, customer, _ = setup
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="documento", titolo="Scansione"), ADMIN
    )
    service.add_version(document.id, b"%PDF-1.7\n", "application/pdf", ADMIN)
    with pytest.raises(ValidationFailed) as excinfo:
        service.regenerate(document.id, 1, ADMIN)
    assert "template" in excinfo.value.details["reason"]


def test_the_offer_state_machine_allows_only_the_declared_transitions(setup: tuple) -> None:
    service, customer, template = setup
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="O"), ADMIN
    )
    assert service.get(document.id, ADMIN).stato == "bozza"
    assert service.set_offer_state(document.id, "inviata", ADMIN).stato == "inviata"
    assert service.set_offer_state(document.id, "accettata", ADMIN).stato == "accettata"


def test_an_undeclared_transition_is_refused(setup: tuple) -> None:
    service, customer, _ = setup
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="O"), ADMIN
    )
    with pytest.raises(Conflict) as excinfo:
        service.set_offer_state(document.id, "accettata", ADMIN)
    assert "bozza" in excinfo.value.details["reason"]


def test_an_accepted_offer_is_terminal(setup: tuple) -> None:
    service, customer, _ = setup
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="O"), ADMIN
    )
    service.set_offer_state(document.id, "inviata", ADMIN)
    service.set_offer_state(document.id, "accettata", ADMIN)
    assert OFFER_TRANSITIONS["accettata"] == frozenset()
    with pytest.raises(Conflict):
        service.set_offer_state(document.id, "bozza", ADMIN)


def test_a_non_offer_has_no_state_to_set(setup: tuple) -> None:
    service, customer, _ = setup
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="verbale", titolo="V"), ADMIN
    )
    with pytest.raises(ValidationFailed) as excinfo:
        service.set_offer_state(document.id, "inviata", ADMIN)
    assert excinfo.value.details["field"] == "stato"


def test_a_state_change_leaves_a_timeline_entry(setup: tuple, db_session: Session) -> None:
    from pigrocrm.core.activities.service import ActivityService

    service, customer, _ = setup
    document = service.create(
        DocumentCreate(customer_id=customer.id, tipo="offerta", titolo="O"), ADMIN
    )
    service.set_offer_state(document.id, "inviata", ADMIN)
    kinds = [a.kind for a in ActivityService(db_session).timeline("document", document.id)]
    assert "state_changed" in kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/core && uv run pytest tests/test_documents_from_template.py -v`
Expected: FAIL with `ImportError: cannot import name 'DocumentFromTemplate'`

- [ ] **Step 3: Add the schema**

Append to `packages/core/src/pigrocrm/core/documents/schemas.py`:

```python
class DocumentFromTemplate(BaseModel):
    """One call: pick a template, fill its variables, get a document with a PDF."""

    template_id: UUID
    customer_id: UUID | None = None
    deal_id: UUID | None = None
    titolo: SafeStr = Field(max_length=TITOLO_MAX_LENGTH)
    # The values for the template's declared variables. Free-form by nature -- the
    # template decides what it wants, and `render_template` rejects a missing required
    # one by name before anything is written.
    variabili: dict[str, Any] = {}
    custom_fields: dict[str, Any] = {}
```

- [ ] **Step 4: Extend `DocumentService`**

Add these imports at the top of `packages/core/src/pigrocrm/core/documents/service.py`:

```python
from datetime import date

from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.customers.schemas import CustomerRead
from pigrocrm.core.documents.schemas import DocumentFromTemplate, OfferState
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.render.pdf import build_header, render_pdf
from pigrocrm.core.templates.renderer import render_template
from pigrocrm.core.templates.service import TemplateService
```

Add the state machine as a module constant, above the class:

```python
# The offer lifecycle, as a table rather than a chain of `if`s: the UI reads it to
# decide which buttons to show, and the MCP tool reads it to tell an agent what it may
# do next. `accettata` and `rifiutata` are terminal -- an offer that was answered is a
# fact, and editing that fact is a new offer, not a state change.
OFFER_TRANSITIONS: dict[str, frozenset[str]] = {
    "bozza": frozenset({"inviata"}),
    "inviata": frozenset({"accettata", "rifiutata", "bozza"}),
    "accettata": frozenset(),
    "rifiutata": frozenset(),
}
```

Change `__init__` to accept settings, and add the three methods **before** `_require` (so `list` stays last):

```python
    def __init__(
        self, session: Session, storage: DocumentStorage, settings: Settings | None = None
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings or get_settings()
        self.repo = DocumentRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)
        self.templates = TemplateService(session)
        self.emitter = EmitterProfileService(session)

    def _template_scope(self, document: Document, variabili: dict[str, Any], actor: Actor) -> dict[str, Any]:
        """What a template can read: the caller's variables, plus `cliente` and
        `emittente` from the record itself.

        The caller's own keys go in first and the record's go in second, so a caller
        cannot shadow `cliente` or `emittente` with values of their own -- an offer
        must state the customer the document is filed under, not the one whoever
        pressed the button typed.
        """
        customer = self._customer_of(document)
        scope: dict[str, Any] = dict(variabili)
        scope["emittente"] = self.emitter.as_template_values(actor)["emittente"]
        scope["cliente"] = (
            CustomerRead.model_validate(customer).model_dump(mode="json") if customer else {}
        )
        scope.setdefault("oggi", date.today().isoformat())
        return scope

    def _render_to_pdf(self, corpo: str, scope: dict[str, Any], declared: tuple[Any, ...]) -> tuple[str, bytes]:
        markdown = render_template(corpo, scope, declared)
        header = build_header(scope["emittente"])
        return markdown, render_pdf(markdown, header_typst=header, settings=self.settings)

    def create_from_template(self, data: DocumentFromTemplate, actor: Actor) -> DocumentRead:
        """The call behind "Claude, prepara una nuova offerta usando il template
        Consulenza CTO" (spec 7) and behind the UI's Genera button. One transaction:
        the document, its first version and the timeline entry commit together, and a
        render failure leaves nothing behind."""
        actor.require_write("create_document_from_template")
        template = self.templates._require(data.template_id)
        self._check_owner(data.customer_id, data.deal_id)

        document = self.repo.add(
            Document(
                customer_id=data.customer_id,
                deal_id=data.deal_id,
                tipo=template.tipo,
                titolo=data.titolo,
                stato="bozza" if template.tipo == "offerta" else None,
                custom_fields=self._validated_custom(data.custom_fields or {}),
            )
        )
        scope = self._template_scope(document, data.variabili, actor)
        markdown, pdf = self._render_to_pdf(
            template.corpo_markdown, scope, self.templates.declared_variables(template)
        )

        key = self.storage_key_for(document, 1, "application/pdf")
        self.storage.put(key, pdf, "application/pdf")
        self.repo.add_version(
            DocumentVersion(
                document_id=document.id,
                numero=1,
                sorgente_markdown=markdown,
                template_id=template.id,
                variabili=data.variabili,
                storage_key=key,
                content_type="application/pdf",
                dimensione=len(pdf),
                hash_sha256=hashlib.sha256(pdf).hexdigest(),
                creato_da=actor.id,
            )
        )
        document.versione_corrente = 1
        self.activities.record(
            ENTITY, document.id, "created_from_template", actor, {"template": template.nome}
        )
        self.session.commit()
        return DocumentRead.model_validate(document)

    def regenerate(self, document_id: UUID, numero: int, actor: Actor) -> DocumentVersionRead:
        """Rebuild an old version as a new one.

        Reads the version's own `template_id` and `variabili` -- which is exactly why
        both are stored (spec 4.2) -- so a six-month-old offer regenerates identically
        without the person who wrote it being in the room.
        """
        actor.require_write("regenerate_document")
        document = self._require(document_id)
        source = self.repo.version(document_id, numero)
        if source is None:
            raise NotFound("document_version", f"{document_id}#{numero}")
        if source.template_id is None or source.variabili is None:
            raise ValidationFailed(
                ENTITY,
                "numero",
                "questa versione non e' stata generata da un template e non si rigenera",
                expected="una versione creata da un template",
            )
        template = self.templates._require(source.template_id)
        scope = self._template_scope(document, source.variabili, actor)
        markdown, pdf = self._render_to_pdf(
            template.corpo_markdown, scope, self.templates.declared_variables(template)
        )
        return self.add_version(
            document_id,
            pdf,
            "application/pdf",
            actor,
            sorgente_markdown=markdown,
            template_id=template.id,
            variabili=source.variabili,
        )

    def set_offer_state(self, document_id: UUID, stato: OfferState, actor: Actor) -> DocumentRead:
        """The only writer of `documents.stato`.

        Deliberately not a field on `DocumentUpdate`: `model_dump(exclude_none=True)`
        drops a `None`, so a nullable typed column on an Update schema has no spelling
        that means "clear it" -- the A14 defect. A dedicated method with a required,
        non-nullable literal has no such shape.
        """
        actor.require_write("set_offer_state")
        document = self._require(document_id)
        if document.tipo != "offerta" or document.stato is None:
            raise ValidationFailed(
                ENTITY,
                "stato",
                "solo un documento di tipo offerta ha uno stato",
                expected="un documento di tipo offerta",
            )
        allowed = OFFER_TRANSITIONS[document.stato]
        if stato not in allowed:
            raise Conflict(
                ENTITY,
                f"da '{document.stato}' non si puo' passare a '{stato}'",
                stato_attuale=document.stato,
                transizioni_ammesse=sorted(allowed),
            )
        previous, document.stato = document.stato, stato
        self.activities.record(
            ENTITY, document.id, "state_changed", actor, {"da": previous, "a": stato}
        )
        self.session.commit()
        return DocumentRead.model_validate(document)
```

Also add `Conflict` to the `pigrocrm.core.errors` import line at the top of the file.

- [ ] **Step 5: Run the tests**

Run: `cd packages/core && uv run pytest tests/test_documents_from_template.py -v`
Expected: PASS (the three `needs_binaries` tests skip on a machine without Pandoc/Typst; every other test runs).

- [ ] **Step 6: Run the whole core suite**

Run: `cd packages/core && uv run pytest -q`
Expected: PASS, no failures, no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/pigrocrm/core/documents packages/core/tests/test_documents_from_template.py
git commit -m "feat(documents): create from template, regenerate, and offer states"
```

---

# Phase 4 — Adapters

Both adapters call the same services in-process. Neither contains a business rule.

### Task 12: FastAPI routers for documents, templates and the emitter profile

**Files:**
- Create: `apps/api/src/pigrocrm_api/routers/documents.py`, `apps/api/src/pigrocrm_api/routers/templates.py`, `apps/api/src/pigrocrm_api/routers/emitter.py`
- Modify: `apps/api/src/pigrocrm_api/deps.py` (add `StorageDep`)
- Modify: `apps/api/src/pigrocrm_api/main.py` (register the three routers)
- Modify: `apps/api/pyproject.toml` (add `python-multipart==0.0.20` for `UploadFile`)
- Test: `apps/api/tests/test_documents_api.py`

**Interfaces:**
- Consumes: `DocumentService`, `TemplateService`, `EmitterProfileService` and their schemas; `SessionDep`, `ActorDep` from `pigrocrm_api.deps`; `PROBLEM_RESPONSES` from `pigrocrm_api.errors`.
- Produces the HTTP surface:
  - `POST /api/documents` · `GET /api/documents` · `GET /api/documents/{document_id}` · `PATCH /api/documents/{document_id}` · `DELETE /api/documents/{document_id}` · `POST /api/documents/{document_id}/restore`
  - `POST /api/documents/from-template` · `POST /api/documents/{document_id}/stato` · `GET /api/documents/{document_id}/versions` · `POST /api/documents/{document_id}/versions` (multipart upload) · `POST /api/documents/{document_id}/versions/{numero}/regenerate` · `GET /api/documents/{document_id}/download` · `GET /api/documents/{document_id}/timeline`
  - `GET /api/templates` · `POST /api/templates` · `GET /api/templates/{template_id}` · `PATCH /api/templates/{template_id}` · `DELETE /api/templates/{template_id}` · `GET /api/templates/{template_id}/describe` · `POST /api/templates/{template_id}/preview`
  - `GET /api/emitter` · `PUT /api/emitter`
  - `StorageDep = Annotated[DocumentStorage, Depends(get_storage)]`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_documents_api.py
from uuid import uuid4

from fastapi.testclient import TestClient


def _customer(client: TestClient) -> str:
    response = client.post("/api/customers", json={"ragione_sociale": "ACME S.r.l."})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_create_a_document_on_a_customer(admin_client: TestClient) -> None:
    customer_id = _customer(admin_client)
    response = admin_client.post(
        "/api/documents",
        json={"customer_id": customer_id, "tipo": "offerta", "titolo": "Offerta 1"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["stato"] == "bozza"


def test_a_document_with_neither_owner_is_a_422_problem_document(admin_client: TestClient) -> None:
    response = admin_client.post("/api/documents", json={"tipo": "documento", "titolo": "X"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "validation_failed"


def test_an_unknown_customer_is_a_404_problem_document(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/documents",
        json={"customer_id": str(uuid4()), "tipo": "documento", "titolo": "X"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_list_filters_by_customer(admin_client: TestClient) -> None:
    customer_id = _customer(admin_client)
    admin_client.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "documento", "titolo": "A"}
    )
    response = admin_client.get("/api/documents", params={"customer_id": customer_id})
    assert response.status_code == 200
    assert [d["titolo"] for d in response.json()["items"]] == ["A"]


def test_a_limit_over_the_ceiling_is_refused(admin_client: TestClient) -> None:
    assert admin_client.get("/api/documents", params={"limit": 1000}).status_code == 422


def test_upload_a_version_and_download_it_back(admin_client: TestClient) -> None:
    customer_id = _customer(admin_client)
    document_id = admin_client.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "documento", "titolo": "Doc"}
    ).json()["id"]

    upload = admin_client.post(
        f"/api/documents/{document_id}/versions",
        files={"file": ("scansione.pdf", b"%PDF-1.7\nfinto\n", "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["numero"] == 1

    download = admin_client.get(f"/api/documents/{document_id}/download")
    assert download.status_code == 200
    assert download.content == b"%PDF-1.7\nfinto\n"
    assert download.headers["content-type"] == "application/pdf"
    assert "attachment" in download.headers["content-disposition"]


def test_an_unallowed_upload_type_is_refused(admin_client: TestClient) -> None:
    customer_id = _customer(admin_client)
    document_id = admin_client.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "documento", "titolo": "Doc"}
    ).json()["id"]
    response = admin_client.post(
        f"/api/documents/{document_id}/versions",
        files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


def test_the_download_filename_cannot_inject_a_header(admin_client: TestClient) -> None:
    customer_id = _customer(admin_client)
    document_id = admin_client.post(
        "/api/documents",
        json={"customer_id": customer_id, "tipo": "documento", "titolo": 'a"\r\nX-Evil: 1'},
    ).json()["id"]
    admin_client.post(
        f"/api/documents/{document_id}/versions",
        files={"file": ("a.pdf", b"%PDF-1.7\n", "application/pdf")},
    )
    response = admin_client.get(f"/api/documents/{document_id}/download")
    assert response.status_code == 200
    assert "X-Evil" not in response.headers


def test_set_offer_state_and_refuse_an_undeclared_transition(admin_client: TestClient) -> None:
    customer_id = _customer(admin_client)
    document_id = admin_client.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "offerta", "titolo": "O"}
    ).json()["id"]
    assert (
        admin_client.post(f"/api/documents/{document_id}/stato", json={"stato": "inviata"})
        .json()["stato"]
        == "inviata"
    )
    conflict = admin_client.post(f"/api/documents/{document_id}/stato", json={"stato": "bozza"})
    assert conflict.status_code == 200  # inviata -> bozza is allowed
    forbidden = admin_client.post(f"/api/documents/{document_id}/stato", json={"stato": "accettata"})
    assert forbidden.status_code == 409
    assert forbidden.json()["code"] == "conflict"


def test_a_readonly_actor_cannot_create_a_document(readonly_client: TestClient) -> None:
    response = readonly_client.post(
        "/api/documents", json={"customer_id": str(uuid4()), "tipo": "documento", "titolo": "X"}
    )
    assert response.status_code == 403


def test_templates_crud_and_describe(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/templates",
        json={
            "nome": "Consulenza CTO",
            "tipo": "offerta",
            "corpo_markdown": "Spett.le {{cliente.ragione_sociale}} — {{oggetto}}",
            "variabili_dichiarate": [
                {"nome": "oggetto", "etichetta": "Oggetto", "tipo": "text", "obbligatoria": True}
            ],
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    described = admin_client.get(f"/api/templates/{template_id}/describe")
    assert described.status_code == 200
    assert [v["nome"] for v in described.json()["variabili"]] == ["oggetto"]

    preview = admin_client.post(
        f"/api/templates/{template_id}/preview",
        json={"variabili": {"cliente": {"ragione_sociale": "ACME"}, "oggetto": "Advisory"}},
    )
    assert preview.status_code == 200
    assert preview.json()["markdown"] == "Spett.le ACME — Advisory"


def test_a_template_body_that_does_not_parse_is_a_422(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/templates", json={"nome": "Rotto", "tipo": "offerta", "corpo_markdown": "{{#if x}}"}
    )
    assert response.status_code == 422
    assert "riga 1" in response.json()["reason"]


def test_emitter_profile_is_404_before_it_is_saved_then_readable(admin_client: TestClient) -> None:
    assert admin_client.get("/api/emitter").status_code == 404
    saved = admin_client.put(
        "/api/emitter",
        json={"ragione_sociale": "Humancraft di Ivan Sala", "partita_iva": "14518240966"},
    )
    assert saved.status_code == 200, saved.text
    assert admin_client.get("/api/emitter").json()["partita_iva"] == "14518240966"


def test_a_non_admin_cannot_write_the_emitter_profile(collaborator_client: TestClient) -> None:
    response = collaborator_client.put("/api/emitter", json={"ragione_sociale": "X"})
    assert response.status_code == 403


def test_the_openapi_document_declares_the_new_routes(admin_client: TestClient) -> None:
    paths = admin_client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/documents",
        "/api/documents/from-template",
        "/api/documents/{document_id}/download",
        "/api/templates/{template_id}/describe",
        "/api/emitter",
    ):
        assert path in paths, path
```

If `apps/api/tests/conftest.py` does not already provide `admin_client`, `collaborator_client` and `readonly_client`, reuse whatever fixtures `apps/api/tests/test_entities_api.py` uses and rename the calls above to match — do not invent a second fixture set.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_documents_api.py -v`
Expected: FAIL with 404s on every new path.

- [ ] **Step 3: Add `StorageDep`**

Append to `apps/api/src/pigrocrm_api/deps.py`:

```python
from pigrocrm.core.storage import DocumentStorage, storage_from_settings


def get_storage(settings: SettingsDep) -> DocumentStorage:
    """One backend per process, chosen from settings. Cached by `get_settings`'s own
    `lru_cache`, so this builds at most one `GDriveStorage` and its token cache is
    shared across requests rather than re-authenticating on each one."""
    return storage_from_settings(settings)


StorageDep = Annotated[DocumentStorage, Depends(get_storage)]
```

- [ ] **Step 4: Write the routers**

```python
# apps/api/src/pigrocrm_api/routers/documents.py
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.documents.schemas import (
    DocumentCreate,
    DocumentFromTemplate,
    DocumentListQuery,
    DocumentPage,
    DocumentRead,
    DocumentTipo,
    DocumentUpdate,
    DocumentVersionRead,
    OfferState,
)
from pigrocrm.core.documents.service import DocumentService
from pigrocrm_api.deps import ActorDep, SessionDep, SettingsDep, StorageDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/documents", tags=["documents"], responses=PROBLEM_RESPONSES)


class OfferStateBody(BaseModel):
    stato: OfferState


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create(
    data: DocumentCreate,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> DocumentRead:
    return DocumentService(session, storage, settings).create(data, actor)


@router.post("/from-template", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_from_template(
    data: DocumentFromTemplate,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> DocumentRead:
    """Renders synchronously: a few pages compose in well under a second, and a job
    queue is complexity that does not pay for itself today (spec 6)."""
    return DocumentService(session, storage, settings).create_from_template(data, actor)


@router.get("", response_model=DocumentPage)
def list_documents(
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
    customer_id: Annotated[UUID | None, Query()] = None,
    deal_id: Annotated[UUID | None, Query()] = None,
    tipo: Annotated[DocumentTipo | None, Query()] = None,
    stato: Annotated[OfferState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> DocumentPage:
    query = DocumentListQuery(
        customer_id=customer_id, deal_id=deal_id, tipo=tipo, stato=stato, limit=limit, cursor=cursor
    )
    return DocumentService(session, storage, settings).list(query, actor)


@router.get("/{document_id}", response_model=DocumentRead)
def get(
    document_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> DocumentRead:
    return DocumentService(session, storage, settings).get(document_id, actor)


@router.patch("/{document_id}", response_model=DocumentRead)
def update(
    document_id: UUID,
    data: DocumentUpdate,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> DocumentRead:
    return DocumentService(session, storage, settings).update(document_id, data, actor)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(
    document_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> None:
    DocumentService(session, storage, settings).soft_delete(document_id, actor)


@router.post("/{document_id}/restore", response_model=DocumentRead)
def restore(
    document_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> DocumentRead:
    return DocumentService(session, storage, settings).restore(document_id, actor)


@router.post("/{document_id}/stato", response_model=DocumentRead)
def set_offer_state(
    document_id: UUID,
    body: OfferStateBody,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> DocumentRead:
    return DocumentService(session, storage, settings).set_offer_state(document_id, body.stato, actor)


@router.get("/{document_id}/versions", response_model=list[DocumentVersionRead])
def versions(
    document_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> list[DocumentVersionRead]:
    return DocumentService(session, storage, settings).versions(document_id, actor)


@router.post(
    "/{document_id}/versions",
    response_model=DocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_version(
    document_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
    file: Annotated[UploadFile, File()],
) -> DocumentVersionRead:
    """`file.content_type` is a client-supplied string and is validated against
    `ALLOWED_CONTENT_TYPES` inside the service, never trusted here."""
    data = await file.read()
    return DocumentService(session, storage, settings).add_version(
        document_id, data, file.content_type or "application/octet-stream", actor
    )


@router.post(
    "/{document_id}/versions/{numero}/regenerate",
    response_model=DocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def regenerate(
    document_id: UUID,
    numero: int,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> DocumentVersionRead:
    return DocumentService(session, storage, settings).regenerate(document_id, numero, actor)


@router.get("/{document_id}/download")
def download(
    document_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: ActorDep,
    numero: Annotated[int | None, Query(ge=1, le=100_000)] = None,
) -> Response:
    """The download always goes through the API: it is the only place authorisation
    exists, on both storage backends (spec 5).

    The filename is percent-encoded into `filename*` (RFC 5987) rather than
    interpolated into `filename=`. The service already slugified it, so nothing
    dangerous should reach here -- encoding it anyway means a future change to that
    slug cannot turn a document title into a response header.
    """
    data, content_type, filename = DocumentService(session, storage, settings).download(
        document_id, numero, actor
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            # A stored file is served from the app's own origin; without this a
            # browser may sniff a benign content type into something executable.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{document_id}/timeline", response_model=list[ActivityRead])
def timeline(
    document_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    return ActivityService(session).timeline("document", document_id, limit)
```

```python
# apps/api/src/pigrocrm_api/routers/templates.py
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from pigrocrm.core.templates.schemas import (
    TemplateCreate,
    TemplateDescription,
    TemplateRead,
    TemplateUpdate,
)
from pigrocrm.core.templates.service import TemplateService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/templates", tags=["templates"], responses=PROBLEM_RESPONSES)


class PreviewBody(BaseModel):
    variabili: dict[str, Any] = {}


class PreviewResult(BaseModel):
    markdown: str


@router.post("", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create(data: TemplateCreate, session: SessionDep, actor: ActorDep) -> TemplateRead:
    return TemplateService(session).create(data, actor)


@router.get("", response_model=list[TemplateRead])
def list_templates(
    session: SessionDep,
    actor: ActorDep,
    include_archived: Annotated[bool, Query()] = False,
) -> list[TemplateRead]:
    return TemplateService(session).list(actor, include_archived=include_archived)


@router.get("/{template_id}", response_model=TemplateRead)
def get(template_id: UUID, session: SessionDep, actor: ActorDep) -> TemplateRead:
    return TemplateService(session).get(template_id, actor)


@router.patch("/{template_id}", response_model=TemplateRead)
def update(
    template_id: UUID, data: TemplateUpdate, session: SessionDep, actor: ActorDep
) -> TemplateRead:
    return TemplateService(session).update(template_id, data, actor)


@router.delete("/{template_id}", response_model=TemplateRead)
def archive(template_id: UUID, session: SessionDep, actor: ActorDep) -> TemplateRead:
    """Archive, not delete: a document version still points at this template so it can
    be regenerated."""
    return TemplateService(session).archive(template_id, actor)


@router.get("/{template_id}/describe", response_model=TemplateDescription)
def describe(template_id: UUID, session: SessionDep, actor: ActorDep) -> TemplateDescription:
    return TemplateService(session).describe(template_id, actor)


@router.post("/{template_id}/preview", response_model=PreviewResult)
def preview(
    template_id: UUID, body: PreviewBody, session: SessionDep, actor: ActorDep
) -> PreviewResult:
    return PreviewResult(markdown=TemplateService(session).preview(template_id, body.variabili, actor))
```

```python
# apps/api/src/pigrocrm_api/routers/emitter.py
from fastapi import APIRouter

from pigrocrm.core.emitter.schemas import EmitterProfileRead, EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/emitter", tags=["emitter"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=EmitterProfileRead)
def get(session: SessionDep, actor: ActorDep) -> EmitterProfileRead:
    """404 until it is saved once: an empty profile and an unsaved one are different
    facts, and a document cannot be rendered without it."""
    return EmitterProfileService(session).get(actor)


@router.put("", response_model=EmitterProfileRead)
def upsert(
    data: EmitterProfileUpsert, session: SessionDep, actor: ActorDep
) -> EmitterProfileRead:
    return EmitterProfileService(session).upsert(data, actor)
```

Register all three in `apps/api/src/pigrocrm_api/main.py`, in the same list the existing routers are registered from, and add `"python-multipart==0.0.20"` to `apps/api/pyproject.toml`'s `[project].dependencies` (FastAPI needs it for `UploadFile`; without it the upload route raises at import time).

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_documents_api.py -v`
Expected: PASS

Run: `cd apps/api && uv run pytest -q`
Expected: PASS — in particular `tests/test_input_bounds_sweep.py`, which walks every route in the OpenAPI document and will now cover the new ones.

- [ ] **Step 6: Commit**

```bash
git add apps/api uv.lock
git commit -m "feat(api): document, template and emitter routers"
```

---

### Task 13: MCP tools

**Files:**
- Create: `apps/mcp/src/pigrocrm_mcp/tools/documents.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`
- Modify: `apps/mcp/src/pigrocrm_mcp/context.py` (expose a `storage` on the context)
- Test: `apps/mcp/tests/test_mcp_documents.py`

**Interfaces:**
- Consumes: `DocumentService`, `TemplateService` and their schemas; `McpContext`; `BoundedLimit` from `pigrocrm_mcp.tools`.
- Produces the seven tools spec §7 names: `list_documents`, `get_document`, `create_document_from_template`, `list_templates`, `describe_template`, `set_offer_state`, `get_document_versions`.
- Adds `OfferStateArg = Annotated[str, WithJsonSchema({"type": "string", "enum": ["bozza", "inviata", "accettata", "rifiutata"]})]`

- [ ] **Step 1: Write the failing test**

```python
# apps/mcp/tests/test_mcp_documents.py
import json
from typing import Any

import pytest


def _call(server: Any, name: str, **arguments: Any) -> dict[str, Any]:
    """Calls a tool through the SDK exactly as an agent would, so the SDK's own
    argument validation runs too -- which is where R2's raw pydantic dumps escape."""
    result = server.call_tool_sync(name, arguments)
    return json.loads(result.content[0].text)


def test_the_seven_spec_tools_are_registered(mcp_server: Any) -> None:
    names = {tool.name for tool in mcp_server.list_tools_sync()}
    assert {
        "list_documents",
        "get_document",
        "create_document_from_template",
        "list_templates",
        "describe_template",
        "set_offer_state",
        "get_document_versions",
    } <= names


def test_no_tool_returns_document_bytes(mcp_server: Any) -> None:
    # "Il download dei byte non passa da MCP: un tool che restituisce un PDF in base64
    # dentro un contesto e' uno spreco e un rischio" (spec 7).
    for tool in mcp_server.list_tools_sync():
        assert "download" not in tool.name
        assert "base64" not in (tool.description or "").lower()


def test_describe_template_reports_the_variables_before_anyone_is_asked(
    mcp_server: Any, seeded_template_id: str
) -> None:
    described = _call(mcp_server, "describe_template", template_id=seeded_template_id)
    assert [v["nome"] for v in described["variabili"]] == ["oggetto"]
    assert described["nome"] == "Consulenza CTO"


def test_create_document_from_template_returns_an_identifier_not_bytes(
    mcp_server: Any, seeded_template_id: str, seeded_customer_id: str
) -> None:
    created = _call(
        mcp_server,
        "create_document_from_template",
        template_id=seeded_template_id,
        customer_id=seeded_customer_id,
        titolo="Offerta 2026-01",
        variabili={"oggetto": "Advisory"},
    )
    assert "id" in created
    assert "pdf" not in json.dumps(created).lower()


def test_list_documents_filters_by_customer(mcp_server: Any, seeded_customer_id: str) -> None:
    listed = _call(mcp_server, "list_documents", customer_id=seeded_customer_id)
    assert "items" in listed and isinstance(listed["items"], list)


def test_a_wrong_typed_limit_produces_guidance_not_a_pydantic_dump(
    mcp_server: Any, seeded_customer_id: str
) -> None:
    # R2: the SDK validates some arguments before the guard runs. `BoundedLimit`'s
    # `int | str` runtime type is what keeps this inside the guard.
    result = _call(mcp_server, "list_documents", customer_id=seeded_customer_id, limit="molti")
    assert "errors.pydantic.dev" not in json.dumps(result)


def test_set_offer_state_refuses_an_undeclared_transition_with_guidance(
    mcp_server: Any, seeded_offer_id: str
) -> None:
    result = _call(mcp_server, "set_offer_state", document_id=seeded_offer_id, stato="accettata")
    assert "bozza" in json.dumps(result)
    assert "errors.pydantic.dev" not in json.dumps(result)


def test_get_document_versions_lists_them_newest_first(
    mcp_server: Any, seeded_offer_id: str
) -> None:
    result = _call(mcp_server, "get_document_versions", document_id=seeded_offer_id)
    assert "versions" in result
```

Add the `seeded_template_id`, `seeded_customer_id` and `seeded_offer_id` fixtures to `apps/mcp/tests/conftest.py`, built with the same in-process services the existing `mcp_server` fixture uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/mcp && uv run pytest tests/test_mcp_documents.py -v`
Expected: FAIL — the seven tool names are not registered.

- [ ] **Step 3: Write the tool module**

```python
# apps/mcp/src/pigrocrm_mcp/tools/documents.py
from typing import Any
from uuid import UUID

from pigrocrm.core.documents.schemas import DocumentFromTemplate, DocumentListQuery
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.templates.service import TemplateService
from pigrocrm_mcp.context import McpContext


def _documents(context: McpContext) -> DocumentService:
    return DocumentService(context.session, context.storage)


def search(context: McpContext, query: DocumentListQuery) -> dict[str, Any]:
    page = _documents(context).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def get(context: McpContext, document_id: str) -> dict[str, Any]:
    return _documents(context).get(UUID(document_id), context.actor).model_dump(mode="json")


def create_from_template(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    result = _documents(context).create_from_template(DocumentFromTemplate(**data), context.actor)
    return result.model_dump(mode="json")


def set_state(context: McpContext, document_id: str, stato: str) -> dict[str, Any]:
    result = _documents(context).set_offer_state(UUID(document_id), stato, context.actor)  # type: ignore[arg-type]
    return result.model_dump(mode="json")


def versions(context: McpContext, document_id: str) -> dict[str, Any]:
    entries = _documents(context).versions(UUID(document_id), context.actor)
    return {"versions": [entry.model_dump(mode="json") for entry in entries]}


def list_templates(context: McpContext, include_archived: bool) -> dict[str, Any]:
    templates = TemplateService(context.session).list(
        context.actor, include_archived=include_archived
    )
    return {
        "templates": [
            {"id": str(t.id), "nome": t.nome, "tipo": t.tipo, "attivo": t.attivo}
            for t in templates
        ]
    }


def describe_template(context: McpContext, template_id: str) -> dict[str, Any]:
    described = TemplateService(context.session).describe(UUID(template_id), context.actor)
    return described.model_dump(mode="json")
```

- [ ] **Step 4: Register the tools**

Add to `apps/mcp/src/pigrocrm_mcp/tools/__init__.py`: extend the `from pigrocrm_mcp.tools import ...` line with `documents`, add the alias next to the existing ones, and add the seven tools at the end of `register_entity_tools`.

```python
# Same runtime-permissive / schema-only-strict split as BoundedLimit above: the
# parameter stays a plain `str` so a wrong value is rejected by `set_offer_state`'s own
# Literal inside the guarded call, while `list_tools()` shows the real four states an
# agent may choose from.
OfferStateArg = Annotated[
    str,
    WithJsonSchema({"type": "string", "enum": ["bozza", "inviata", "accettata", "rifiutata"]}),
]
```

```python
    # ---- documents -------------------------------------------------------

    @mcp.tool()
    @guard
    def list_documents(
        customer_id: str | None = None,
        deal_id: str | None = None,
        tipo: str | None = None,
        stato: str | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Elenca i documenti di un cliente o di un deal. Passa `next_cursor` come
        `cursor` per la pagina successiva. Per scaricare i byte usa l'API REST:
        MCP restituisce identificativi, non file."""
        return documents.search(
            context,
            DocumentListQuery(
                customer_id=UUID(customer_id) if customer_id else None,
                deal_id=UUID(deal_id) if deal_id else None,
                tipo=tipo,  # type: ignore[arg-type]
                stato=stato,  # type: ignore[arg-type]
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def get_document(document_id: str) -> dict[str, Any]:
        """Legge un documento: tipo, titolo, stato e versione corrente."""
        return documents.get(context, document_id)

    @mcp.tool()
    @guard
    def get_document_versions(document_id: str) -> dict[str, Any]:
        """Storico delle versioni di un documento, dalla piu' recente. Ogni versione
        conserva il template e le variabili con cui e' stata generata, quindi si puo'
        rigenerare identica."""
        return documents.versions(context, document_id)

    @mcp.tool()
    @guard
    def list_templates(include_archived: bool = False) -> dict[str, Any]:
        """Elenca i template disponibili."""
        return documents.list_templates(context, include_archived)

    @mcp.tool()
    @guard
    def describe_template(template_id: str) -> dict[str, Any]:
        """Che variabili vuole un template, con etichetta, tipo e obbligatorieta'.
        Chiamalo **prima** di chiedere qualcosa all'utente: e' come si scopre cosa
        serve senza indovinarlo."""
        return documents.describe_template(context, template_id)

    @mcp.tool()
    @guard
    def create_document_from_template(
        template_id: str,
        titolo: str,
        customer_id: str | None = None,
        deal_id: str | None = None,
        variabili: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea un documento da un template e ne genera il PDF. Indica `customer_id`
        oppure `deal_id`, mai entrambi. Chiama prima `describe_template` per sapere
        quali variabili servono. Restituisce l'identificativo del documento, non il
        file: i byte si scaricano dall'API REST."""
        return documents.create_from_template(
            context,
            {
                "template_id": UUID(template_id),
                "titolo": titolo,
                "customer_id": UUID(customer_id) if customer_id else None,
                "deal_id": UUID(deal_id) if deal_id else None,
                "variabili": variabili or {},
            },
        )

    @mcp.tool()
    @guard
    def set_offer_state(document_id: str, stato: OfferStateArg) -> dict[str, Any]:
        """Cambia lo stato di un'offerta. Transizioni ammesse: bozza -> inviata;
        inviata -> accettata | rifiutata | bozza. Accettata e rifiutata sono finali."""
        return documents.set_state(context, document_id, stato)
```

Add a `storage` attribute to `McpContext` in `apps/mcp/src/pigrocrm_mcp/context.py`, built once at server construction from `storage_from_settings(get_settings())` — the same single-backend-per-process rule the API uses. Do **not** change how `context.session` is obtained: R1 (the shared session) is a known open defect and fixing it is its own task, out of this slice's scope.

- [ ] **Step 5: Run the tests**

Run: `cd apps/mcp && uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Verify the architecture guard**

Run: `cd packages/core && uv run pytest tests/test_architecture.py -v`
Expected: PASS — nothing in `packages/core` imports `pigrocrm_mcp`.

- [ ] **Step 7: Commit**

```bash
git add apps/mcp
git commit -m "feat(mcp): document and template tools calling the same services"
```

---

# Phase 5 — Web interface

Every task in this phase consumes only the REST API from Phase 4, through the generated client. Regenerate the types first, once, in Task 14; every later task depends on that having happened.

### Task 14: Generated types, query keys and the document data layer

**Files:**
- Modify: `apps/web/src/lib/api-types.ts` (regenerated, never hand-edited)
- Modify: `apps/web/src/lib/schema.ts:43` (`EntityType` gains `'document'`)
- Modify: `apps/web/src/lib/query.ts:20-40` (new query keys)
- Create: `apps/web/src/features/documents/queries.ts`
- Create: `apps/web/src/features/documents/queries.test.ts`

**Interfaces:**
- Consumes: `api`, `unwrap` from `@/lib/api`; `queryKeys` from `@/lib/query`; `components` from `@/lib/api-types`.
- Produces:
  - `export type Document = components['schemas']['DocumentRead']`
  - `export type DocumentVersion = components['schemas']['DocumentVersionRead']`
  - `export type Template = components['schemas']['TemplateRead']`
  - `export type TemplateDescription = components['schemas']['TemplateDescription']`
  - `export type TemplateVariable = components['schemas']['TemplateVariable']`
  - `export type EmitterProfile = components['schemas']['EmitterProfileRead']`
  - `export type DocumentOwner = { customerId: string } | { dealId: string }`
  - `export type OfferState = 'bozza' | 'inviata' | 'accettata' | 'rifiutata'`
  - `OFFER_TRANSITIONS: Record<OfferState, OfferState[]>`
  - `OFFER_STATE_LABELS: Record<OfferState, string>`
  - `useDocuments(owner: DocumentOwner)`, `useDocument(documentId: string)`, `useDocumentVersions(documentId: string)`
  - `useCreateDocument(owner: DocumentOwner)`, `useUploadVersion(documentId: string)`, `useDeleteDocument(owner: DocumentOwner)`
  - `useSetOfferState(documentId: string)`, `useRegenerateVersion(documentId: string)`, `useCreateFromTemplate(owner: DocumentOwner)`
  - `useTemplates()`, `useTemplateDescription(templateId: string | null)`, `useTemplatePreview()`
  - `downloadDocument(documentId: string, numero?: number): Promise<void>`
  - New query keys: `queryKeys.documents(owner)`, `queryKeys.document(id)`, `queryKeys.documentVersions(id)`, `queryKeys.templates()`, `queryKeys.templateDescription(id)`, `queryKeys.emitter`

- [ ] **Step 1: Regenerate the API types against the running API**

The API from Phase 4 must be running (the human's stack serves it on port 8000). Run:

```bash
cd apps/web && pnpm generate:api
```

Confirm the new schemas landed: `grep -c "DocumentRead\|TemplateDescription\|EmitterProfileRead" src/lib/api-types.ts` must print a number greater than 0. Never hand-edit this file — a contract change must break `tsc`, not production.

- [ ] **Step 2: Write the failing test**

```tsx
// apps/web/src/features/documents/queries.test.ts
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OFFER_TRANSITIONS, useDocument, useDocuments } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

afterEach(() => {
  vi.restoreAllMocks()
})

function mockJson(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  )
}

describe('useDocuments', () => {
  it('asks for the customer it was given', async () => {
    const fetchSpy = mockJson({ items: [], next_cursor: null })
    renderHook(() => useDocuments({ customerId: 'c-1' }), { wrapper })
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const url = String(fetchSpy.mock.calls[0]?.[0])
    expect(url).toContain('/api/documents')
    expect(url).toContain('customer_id=c-1')
    expect(url).not.toContain('deal_id')
  })

  it('asks for the deal it was given', async () => {
    const fetchSpy = mockJson({ items: [], next_cursor: null })
    renderHook(() => useDocuments({ dealId: 'd-1' }), { wrapper })
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const url = String(fetchSpy.mock.calls[0]?.[0])
    expect(url).toContain('deal_id=d-1')
    expect(url).not.toContain('customer_id')
  })

  it('surfaces a failure as an error, never as an empty list', async () => {
    mockJson({ code: 'not_found', detail: 'Non trovato' }, 404)
    const { result } = renderHook(() => useDocuments({ customerId: 'c-1' }), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})

describe('useDocument', () => {
  it('never fires with an empty id', () => {
    // B1: `useCustomer('')` once produced a 307 to the *list* endpoint with an
    // absolute URL that bypassed Vite's proxy entirely. Disabling the query is the
    // structural fix; this test is what keeps a refactor from undoing it.
    const fetchSpy = mockJson({})
    const { result } = renderHook(() => useDocument(''), { wrapper })
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(result.current.fetchStatus).toBe('idle')
  })
})

describe('OFFER_TRANSITIONS', () => {
  it('mirrors the backend state machine exactly', () => {
    // The table is the backend's own (documents/service.py OFFER_TRANSITIONS). The UI
    // reads it to decide which buttons to draw; it never re-decides the rule, and a
    // refused transition still comes back as the server's own 409 message.
    expect(OFFER_TRANSITIONS.bozza).toEqual(['inviata'])
    expect(OFFER_TRANSITIONS.inviata).toEqual(['accettata', 'rifiutata', 'bozza'])
    expect(OFFER_TRANSITIONS.accettata).toEqual([])
    expect(OFFER_TRANSITIONS.rifiutata).toEqual([])
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/features/documents/queries.test.ts`
Expected: FAIL — `Failed to resolve import "./queries"`.

- [ ] **Step 4: Extend the shared types and query keys**

In `apps/web/src/lib/schema.ts`, replace line 43:

```ts
// Mirrors `EntityType` in packages/core/src/pigrocrm/core/fields/schemas.py, which
// slice 2 widened with "document" -- documents carry custom fields through the same
// mechanism as every other entity, with `entity_type = 'document'`.
export type EntityType = 'customer' | 'person' | 'deal' | 'document'
```

In `apps/web/src/lib/query.ts`, add inside `queryKeys`:

```ts
  // `owner` is the discriminated `{customerId} | {dealId}` object, so a customer's
  // documents and a deal's documents can never share a cache entry, and
  // `invalidateQueries({queryKey: ['documents']})` still matches both.
  documents: (owner?: unknown) => ['documents', owner ?? {}] as const,
  document: (id: string) => ['document', id] as const,
  documentVersions: (id: string) => ['document-versions', id] as const,
  templates: () => ['templates'] as const,
  templateDescription: (id: string) => ['template-description', id] as const,
  emitter: ['emitter'] as const,
```

- [ ] **Step 5: Write the data layer**

```tsx
// apps/web/src/features/documents/queries.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toProblem, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

export type Document = components['schemas']['DocumentRead']
export type DocumentVersion = components['schemas']['DocumentVersionRead']
export type DocumentPage = components['schemas']['DocumentPage']
export type Template = components['schemas']['TemplateRead']
export type TemplateDescription = components['schemas']['TemplateDescription']
export type TemplateVariable = components['schemas']['TemplateVariable']
export type EmitterProfile = components['schemas']['EmitterProfileRead']

export type OfferState = 'bozza' | 'inviata' | 'accettata' | 'rifiutata'

/**
 * A document belongs to a customer **or** to a deal, never both -- so the hooks take
 * a discriminated object rather than two optional strings. There is no "empty id"
 * spelling to get wrong (B1), and a call site physically cannot ask for both.
 */
export type DocumentOwner = { customerId: string } | { dealId: string }

/**
 * The backend's own state machine (`OFFER_TRANSITIONS` in
 * packages/core/src/pigrocrm/core/documents/service.py), read here only to decide
 * which buttons to draw. It is not a second copy of the rule: a transition the UI
 * offers is still checked server-side, and a refused one comes back as the server's
 * own 409 message, which is what the user sees.
 */
export const OFFER_TRANSITIONS: Record<OfferState, OfferState[]> = {
  bozza: ['inviata'],
  inviata: ['accettata', 'rifiutata', 'bozza'],
  accettata: [],
  rifiutata: [],
}

export const OFFER_STATE_LABELS: Record<OfferState, string> = {
  bozza: 'Bozza',
  inviata: 'Inviata',
  accettata: 'Accettata',
  rifiutata: 'Rifiutata',
}

export const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  offerta: 'Offerta',
  contratto: 'Contratto',
  verbale: 'Verbale',
  documento: 'Documento',
}

function ownerQuery(owner: DocumentOwner): { customer_id?: string; deal_id?: string } {
  return 'customerId' in owner ? { customer_id: owner.customerId } : { deal_id: owner.dealId }
}

export function useDocuments(owner: DocumentOwner) {
  return useQuery({
    queryKey: queryKeys.documents(owner),
    queryFn: () => unwrap(api.GET('/api/documents', { params: { query: ownerQuery(owner) } })),
  })
}

export function useDocument(documentId: string) {
  return useQuery({
    // Disabled rather than conditionally called: a hook cannot be called
    // conditionally, and an empty id used to produce a 307 to the *list* endpoint
    // with an absolute URL that bypassed Vite's proxy (residuo B1).
    enabled: documentId !== '',
    queryKey: queryKeys.document(documentId),
    queryFn: () =>
      unwrap(
        api.GET('/api/documents/{document_id}', {
          params: { path: { document_id: documentId } },
        }),
      ),
  })
}

export function useDocumentVersions(documentId: string) {
  return useQuery({
    enabled: documentId !== '',
    queryKey: queryKeys.documentVersions(documentId),
    queryFn: () =>
      unwrap(
        api.GET('/api/documents/{document_id}/versions', {
          params: { path: { document_id: documentId } },
        }),
      ),
  })
}

export function useCreateDocument(owner: DocumentOwner) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.POST('/api/documents', {
          body: { ...ownerQuery(owner), ...body } as never,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents() })
    },
  })
}

export function useCreateFromTemplate(owner: DocumentOwner) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { template_id: string; titolo: string; variabili: Record<string, unknown> }) =>
      unwrap(
        api.POST('/api/documents/from-template', {
          body: { ...ownerQuery(owner), ...body } as never,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents() })
    },
  })
}

/**
 * `openapi-fetch` cannot send a `FormData` body for a multipart route, so this one
 * mutation uses `fetch` directly -- the single documented exception to "no fetch
 * outside the generated client", and it is still inside a hook, never in a component.
 * `credentials: 'include'` matches the shared client so the httpOnly session cookie
 * travels; no `Content-Type` is set by hand, because the browser must append its own
 * multipart boundary.
 */
export function useUploadVersion(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File): Promise<DocumentVersion> => {
      const body = new FormData()
      body.append('file', file)
      const response = await fetch(`/api/documents/${documentId}/versions`, {
        method: 'POST',
        credentials: 'include',
        body,
      })
      const payload: unknown = await response.json().catch(() => null)
      if (!response.ok) throw toProblem(payload, response.status)
      return payload as DocumentVersion
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.document(documentId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.documentVersions(documentId) })
    },
  })
}

export function useSetOfferState(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (stato: OfferState) =>
      unwrap(
        api.POST('/api/documents/{document_id}/stato', {
          params: { path: { document_id: documentId } },
          body: { stato },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.document(documentId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('document', documentId) })
    },
  })
}

export function useRegenerateVersion(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (numero: number) =>
      unwrap(
        api.POST('/api/documents/{document_id}/versions/{numero}/regenerate', {
          params: { path: { document_id: documentId, numero } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.document(documentId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.documentVersions(documentId) })
    },
  })
}

export function useDeleteDocument(owner: DocumentOwner) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) =>
      unwrap(
        api.DELETE('/api/documents/{document_id}', {
          params: { path: { document_id: documentId } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents() })
    },
  })
}

export function useTemplates() {
  return useQuery({
    queryKey: queryKeys.templates(),
    queryFn: () => unwrap(api.GET('/api/templates', { params: { query: {} } })),
  })
}

export function useTemplateDescription(templateId: string | null) {
  return useQuery({
    enabled: templateId !== null && templateId !== '',
    queryKey: queryKeys.templateDescription(templateId ?? ''),
    queryFn: () =>
      unwrap(
        api.GET('/api/templates/{template_id}/describe', {
          params: { path: { template_id: templateId as string } },
        }),
      ),
  })
}

export function useTemplatePreview() {
  return useMutation({
    mutationFn: (args: { templateId: string; variabili: Record<string, unknown> }) =>
      unwrap(
        api.POST('/api/templates/{template_id}/preview', {
          params: { path: { template_id: args.templateId } },
          body: { variabili: args.variabili },
        }),
      ),
  })
}

/**
 * Downloads through the API, which is the only place authorisation exists on either
 * storage backend. The `Content-Disposition` the server sets is what names the file;
 * this only has to hand the blob to the browser and release the object URL, or the
 * page leaks one per download for as long as it stays open.
 */
export async function downloadDocument(documentId: string, numero?: number): Promise<void> {
  const search = numero === undefined ? '' : `?numero=${numero}`
  const response = await fetch(`/api/documents/${documentId}/download${search}`, {
    credentials: 'include',
  })
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    throw toProblem(payload, response.status)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  // Empty `download` keeps the server's own Content-Disposition filename, which is
  // already slugified server-side; naming it here would re-derive a name the server
  // already decided.
  anchor.download = ''
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
```

- [ ] **Step 6: Run the test and the type check**

Run: `cd apps/web && pnpm vitest run src/features/documents/queries.test.ts && pnpm tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/documents apps/web/src/lib
git commit -m "feat(web): document, template and emitter data layer"
```

---

### Task 15: The Documenti tab on Customer and Deal, with drag-and-drop upload

**Files:**
- Modify: `apps/web/src/components/EntityDetailLayout.tsx`
- Create: `apps/web/src/features/documents/UploadDropzone.tsx`
- Create: `apps/web/src/features/documents/DocumentsTab.tsx`
- Create: `apps/web/src/features/documents/DocumentsTab.test.tsx`
- Modify: `apps/web/src/routes/app/clienti/$customerId.tsx`
- Modify: `apps/web/src/routes/app/deal/$dealId.tsx`
- Create: `apps/web/e2e/documents.spec.ts`

**Interfaces:**
- Consumes from Task 14: `useDocuments`, `useUploadVersion`, `useCreateDocument`, `useDeleteDocument`, `downloadDocument`, `Document`, `DocumentOwner`, `OFFER_STATE_LABELS`, `DOCUMENT_TYPE_LABELS`.
- Produces:
  - `EntityDetailLayout` gains `documents?: ReactNode` — when given, a fourth tab labelled "Documenti" appears after "Panoramica"
  - `export function UploadDropzone({ onFiles, busy, accept }: { onFiles: (files: File[]) => void; busy?: boolean; accept: string })`
  - `export function DocumentsTab({ owner }: { owner: DocumentOwner })`
  - `ACCEPTED_UPLOAD_TYPES: string` — the `accept` attribute matching the backend's `ALLOWED_CONTENT_TYPES`

- [ ] **Step 1: Write the failing test**

```tsx
// apps/web/src/features/documents/DocumentsTab.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentsTab } from './DocumentsTab'

const DOCUMENT = {
  id: 'doc-1',
  customer_id: 'c-1',
  deal_id: null,
  tipo: 'offerta',
  titolo: 'Offerta 2026-01',
  stato: 'bozza',
  versione_corrente: 1,
  custom_fields: {},
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T09:00:00Z',
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function mockJson(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
  )
}

afterEach(() => vi.restoreAllMocks())

describe('DocumentsTab', () => {
  it('lists the documents with type, state and version', async () => {
    mockJson({ items: [DOCUMENT], next_cursor: null })
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    expect(await screen.findByText('Offerta 2026-01')).toBeInTheDocument()
    expect(screen.getByText('Offerta')).toBeInTheDocument()
    expect(screen.getByText('Bozza')).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument()
  })

  it('shows an explicit empty state when there really are none', async () => {
    mockJson({ items: [], next_cursor: null })
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    expect(await screen.findByText('Nessun documento.')).toBeInTheDocument()
  })

  it('shows the server error instead of an empty list when the request fails', async () => {
    // A failed request must never look like an empty result.
    mockJson({ code: 'http_error', detail: 'Servizio non disponibile' }, 503)
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    expect(await screen.findByRole('alert')).toHaveTextContent('Servizio non disponibile')
    expect(screen.queryByText('Nessun documento.')).not.toBeInTheDocument()
  })

  it('accepts a dropped file and uploads it', async () => {
    const fetchSpy = mockJson({ items: [], next_cursor: null })
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    const dropzone = await screen.findByTestId('upload-dropzone')
    const file = new File([new Uint8Array([37, 80, 68, 70])], 'offerta.pdf', {
      type: 'application/pdf',
    })
    const dataTransfer = { files: [file], items: [], types: ['Files'] }
    const { fireEvent } = await import('@testing-library/react')
    fireEvent.drop(dropzone, { dataTransfer })
    await waitFor(() => {
      const posted = fetchSpy.mock.calls.some(
        ([url, init]) =>
          String(url).includes('/versions') && (init as RequestInit | undefined)?.method === 'POST',
      )
      expect(posted).toBe(true)
    })
  })

  it('names the file types it accepts so a refusal is never a surprise', async () => {
    mockJson({ items: [], next_cursor: null })
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    const input = await screen.findByLabelText('Carica un documento')
    expect(input).toHaveAttribute('accept', expect.stringContaining('application/pdf'))
  })

  it('downloads through the API when the download button is pressed', async () => {
    const fetchSpy = mockJson({ items: [DOCUMENT], next_cursor: null })
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:x')
    globalThis.URL.revokeObjectURL = vi.fn()
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: 'Scarica Offerta 2026-01' }))
    await waitFor(() => {
      const called = fetchSpy.mock.calls.some(([url]) => String(url).includes('/download'))
      expect(called).toBe(true)
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/features/documents/DocumentsTab.test.tsx`
Expected: FAIL — `Failed to resolve import "./DocumentsTab"`.

- [ ] **Step 3: Add the tab slot to `EntityDetailLayout`**

In `apps/web/src/components/EntityDetailLayout.tsx`, add to `EntityDetailLayoutProps`:

```tsx
  /**
   * The Documenti tab's contents. Optional because Person has no documents: a
   * document belongs to a customer or to a deal, never to a contact. When absent the
   * tab is not rendered at all rather than rendered empty -- an empty tab invites the
   * user to look for something that does not exist for this entity.
   */
  documents?: ReactNode
```

and render it, keeping the existing three tabs untouched:

```tsx
        <TabsList>
          <TabsTrigger value="panoramica">Panoramica</TabsTrigger>
          {documents && <TabsTrigger value="documenti">Documenti</TabsTrigger>}
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="collegamenti">Collegamenti</TabsTrigger>
        </TabsList>

        <TabsContent value="panoramica" className="mt-6">
          {overview}
        </TabsContent>
        {documents && (
          <TabsContent value="documenti" className="mt-6">
            {documents}
          </TabsContent>
        )}
```

destructuring `documents` alongside the other props.

- [ ] **Step 4: Write `UploadDropzone.tsx`**

```tsx
// apps/web/src/features/documents/UploadDropzone.tsx
import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  onFiles: (files: File[]) => void
  busy?: boolean
  /** The `accept` attribute, mirroring the backend's own ALLOWED_CONTENT_TYPES. */
  accept: string
}

/**
 * Drag and drop, plus a real `<input type="file">` behind it.
 *
 * The input is not decoration: a dropzone that only accepts a drag is unusable with a
 * keyboard and invisible to a screen reader, and it is the input's `accept` attribute
 * -- not the drag handler -- that tells the file picker what to offer. The drag path
 * does no type filtering of its own: the backend's `ALLOWED_CONTENT_TYPES` is the
 * authority, and a client-side second opinion is how the two start disagreeing.
 */
export function UploadDropzone({ onFiles, busy, accept }: Props) {
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div
      data-testid="upload-dropzone"
      onDragOver={(event) => {
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        const files = Array.from(event.dataTransfer?.files ?? [])
        if (files.length > 0) onFiles(files)
      }}
      className={cn(
        'rounded-lg border-2 border-dashed p-6 text-center transition-colors',
        over ? 'border-primary bg-primary/5' : 'border-muted-foreground/30',
        busy && 'opacity-60',
      )}
    >
      <Upload aria-hidden className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">
        {busy ? 'Caricamento…' : 'Trascina qui un file, oppure'}{' '}
        {!busy && (
          <button
            type="button"
            className="underline underline-offset-2"
            onClick={() => inputRef.current?.click()}
          >
            scegline uno
          </button>
        )}
      </p>
      <input
        ref={inputRef}
        type="file"
        aria-label="Carica un documento"
        accept={accept}
        className="sr-only"
        disabled={busy}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? [])
          if (files.length > 0) onFiles(files)
          // Reset so choosing the same file twice in a row still fires a change.
          event.target.value = ''
        }}
      />
    </div>
  )
}
```

- [ ] **Step 5: Write `DocumentsTab.tsx`**

```tsx
// apps/web/src/features/documents/DocumentsTab.tsx
import { useState } from 'react'
import { Download, Trash2 } from 'lucide-react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { NewFromTemplateDialog } from './NewFromTemplateDialog'
import {
  DOCUMENT_TYPE_LABELS,
  OFFER_STATE_LABELS,
  downloadDocument,
  useCreateDocument,
  useDeleteDocument,
  useDocuments,
  useUploadVersion,
  type Document,
  type DocumentOwner,
  type OfferState,
} from './queries'
import { UploadDropzone } from './UploadDropzone'

/** Mirrors ALLOWED_CONTENT_TYPES in
 *  packages/core/src/pigrocrm/core/documents/schemas.py. The backend is the authority
 *  and rejects anything else with its own message; this only stops the file picker
 *  from offering a type that would be refused a moment later. */
export const ACCEPTED_UPLOAD_TYPES = [
  'application/pdf',
  'text/markdown',
  'text/plain',
  'image/png',
  'image/jpeg',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
].join(',')

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('it-IT', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

/**
 * One tab, two owners. Everything it shows comes from `GET /api/documents` filtered by
 * the owner it was given; nothing is recomputed client-side, and every failure is
 * rendered as the server's own message rather than as an empty list.
 */
export function DocumentsTab({ owner }: { owner: DocumentOwner }) {
  const documents = useDocuments(owner)
  const createDocument = useCreateDocument(owner)
  const deleteDocument = useDeleteDocument(owner)
  const [pendingDocumentId, setPendingDocumentId] = useState<string | null>(null)
  const upload = useUploadVersion(pendingDocumentId ?? '')
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [templateOpen, setTemplateOpen] = useState(false)

  /**
   * An uploaded file becomes a *new* document holding its first version -- a document
   * and its bytes arrive together, so there is no moment where a row exists with
   * nothing behind it. The title is the file name; the user renames it afterwards if
   * they want to.
   */
  async function handleFiles(files: File[]) {
    setProblem(null)
    for (const file of files) {
      try {
        const created = (await createDocument.mutateAsync({
          tipo: 'documento',
          titolo: file.name,
        })) as Document
        setPendingDocumentId(created.id)
        await upload.mutateAsync(file)
      } catch (error) {
        setProblem(toProblem(error))
        return
      } finally {
        setPendingDocumentId(null)
      }
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-medium">Documenti</h2>
        <Button onClick={() => setTemplateOpen(true)}>Nuovo da template</Button>
      </div>

      {problem && <p role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">{problem.detail}</p>}

      <UploadDropzone
        onFiles={(files) => void handleFiles(files)}
        busy={createDocument.isPending || upload.isPending}
        accept={ACCEPTED_UPLOAD_TYPES}
      />

      {documents.isError && <QueryErrorBanner error={documents.error} />}

      {!documents.isError && documents.data && documents.data.items.length === 0 && (
        <p className="text-muted-foreground">Nessun documento.</p>
      )}

      {!documents.isError && documents.data && documents.data.items.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {documents.data.items.map((document) => (
            <li key={document.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <a
                  href={`/app/documenti/${document.id}`}
                  className="block truncate font-medium underline-offset-2 hover:underline"
                >
                  {document.titolo}
                </a>
                <p className="text-sm text-muted-foreground">
                  {formatDate(document.created_at)}
                </p>
              </div>
              <Badge variant="secondary">
                {DOCUMENT_TYPE_LABELS[document.tipo] ?? document.tipo}
              </Badge>
              {document.stato && (
                <Badge>{OFFER_STATE_LABELS[document.stato as OfferState] ?? document.stato}</Badge>
              )}
              <span className="text-sm text-muted-foreground">v{document.versione_corrente}</span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Scarica ${document.titolo}`}
                disabled={document.versione_corrente === 0}
                onClick={() => {
                  setProblem(null)
                  void downloadDocument(document.id).catch((error: unknown) =>
                    setProblem(toProblem(error)),
                  )
                }}
              >
                <Download className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Archivia ${document.titolo}`}
                onClick={() => {
                  setProblem(null)
                  deleteDocument.mutate(document.id, {
                    onError: (error: unknown) => setProblem(toProblem(error)),
                  })
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <NewFromTemplateDialog
        open={templateOpen}
        onOpenChange={setTemplateOpen}
        owner={owner}
      />
    </div>
  )
}
```

`NewFromTemplateDialog` is written in Task 16. Until then this file will not type-check — that is expected and is why Task 16 immediately follows; run Task 15's own test with the dialog stubbed as `export function NewFromTemplateDialog() { return null }` in `apps/web/src/features/documents/NewFromTemplateDialog.tsx`, and Task 16 replaces the stub with the real component.

- [ ] **Step 6: Wire the tab into both detail routes**

In `apps/web/src/routes/app/clienti/$customerId.tsx`, add the import and pass the prop to the existing `<EntityDetailLayout>`:

```tsx
import { DocumentsTab } from '@/features/documents/DocumentsTab'
```

```tsx
      documents={<DocumentsTab owner={{ customerId }} />}
```

In `apps/web/src/routes/app/deal/$dealId.tsx`, the same with the deal's own id:

```tsx
import { DocumentsTab } from '@/features/documents/DocumentsTab'
```

```tsx
      documents={<DocumentsTab owner={{ dealId }} />}
```

Do **not** add it to `apps/web/src/routes/app/persone/$personId.tsx`: a document belongs to a customer or a deal, never to a contact.

- [ ] **Step 7: Write the E2E spec**

```ts
// apps/web/e2e/documents.spec.ts
import { expect, test } from '@playwright/test'
import { login, createCustomer } from './helpers'

test.describe('Documenti', () => {
  test('una tab Documenti compare su un cliente e accetta un caricamento', async ({ page }) => {
    await login(page)
    const customerName = await createCustomer(page)

    await page.getByRole('link', { name: customerName }).click()
    await page.getByRole('tab', { name: 'Documenti' }).click()
    await expect(page.getByText('Nessun documento.')).toBeVisible()

    await page.getByLabel('Carica un documento').setInputFiles({
      name: 'offerta.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.7\nfinto\n'),
    })

    await expect(page.getByText('offerta.pdf')).toBeVisible()
    await expect(page.getByText('v1')).toBeVisible()
  })

  test('un file di tipo non ammesso mostra il messaggio del server', async ({ page }) => {
    await login(page)
    const customerName = await createCustomer(page)
    await page.getByRole('link', { name: customerName }).click()
    await page.getByRole('tab', { name: 'Documenti' }).click()

    await page.getByLabel('Carica un documento').setInputFiles({
      name: 'pagina.html',
      mimeType: 'text/html',
      buffer: Buffer.from('<script>alert(1)</script>'),
    })

    await expect(page.getByRole('alert')).toContainText('tipo di file non ammesso')
  })

  test('una persona non ha una tab Documenti', async ({ page }) => {
    await login(page)
    await page.goto('/app/persone')
    const firstPerson = page.getByRole('link').first()
    if (await firstPerson.isVisible()) {
      await firstPerson.click()
      await expect(page.getByRole('tab', { name: 'Documenti' })).toHaveCount(0)
    }
  })
})
```

If `apps/web/e2e/helpers.ts` does not export `createCustomer`, add it there following the shape of whatever helper `crm.spec.ts` already uses to create a customer — do not duplicate the logic inside this spec.

- [ ] **Step 8: Run the unit tests and the type check**

Run: `cd apps/web && pnpm vitest run src/features/documents src/components/EntityDetailLayout.test.tsx && pnpm tsc --noEmit`
Expected: PASS.

**Do not run `apps/web/scripts/e2e.sh` or `e2e-teardown.sh`** — they tear down port 5173, where a dev server may be running. Run the Playwright spec against an already-running stack instead: `cd apps/web && pnpm exec playwright test e2e/documents.spec.ts`.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/features/documents apps/web/src/components/EntityDetailLayout.tsx \
        apps/web/src/routes/app/clienti/\$customerId.tsx apps/web/src/routes/app/deal/\$dealId.tsx \
        apps/web/e2e/documents.spec.ts
git commit -m "feat(web): Documenti tab with drag-and-drop upload on customer and deal"
```

---

### Task 16: New document from template — declared variables, preview, generate

**Files:**
- Create (replacing the Task 15 stub): `apps/web/src/features/documents/NewFromTemplateDialog.tsx`
- Create: `apps/web/src/features/documents/NewFromTemplateDialog.test.tsx`

**Interfaces:**
- Consumes from Task 14: `useTemplates`, `useTemplateDescription`, `useTemplatePreview`, `useCreateFromTemplate`, `Template`, `TemplateVariable`, `DocumentOwner`. From slice 1: `DynamicForm` (`{ fields, values, onChange, problem, mode }`), `FieldDefinition` from `@/lib/schema`, `toProblem`/`ProblemDetail` from `@/lib/api`, `QueryErrorBanner`.
- Produces:
  - `export function NewFromTemplateDialog({ open, onOpenChange, owner }: { open: boolean; onOpenChange: (open: boolean) => void; owner: DocumentOwner })`
  - `export function variablesToFields(variables: TemplateVariable[]): FieldDefinition[]`
  - `export interface TemplateFormValues { native: Record<string, unknown>; custom: Record<string, unknown> }`

- [ ] **Step 1: Write the failing test**

```tsx
// apps/web/src/features/documents/NewFromTemplateDialog.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NewFromTemplateDialog, variablesToFields } from './NewFromTemplateDialog'

const TEMPLATE = {
  id: 't-1',
  nome: 'Consulenza CTO',
  tipo: 'offerta',
  corpo_markdown: 'Oggetto: {{oggetto}}',
  variabili_dichiarate: [],
  attivo: true,
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T09:00:00Z',
}

const DESCRIPTION = {
  id: 't-1',
  nome: 'Consulenza CTO',
  tipo: 'offerta',
  variabili: [
    { nome: 'oggetto', etichetta: 'Oggetto', tipo: 'text', obbligatoria: true, options: [] },
    { nome: 'urgente', etichetta: 'Urgente', tipo: 'checkbox', obbligatoria: false, options: [] },
  ],
  percorsi_usati: [['oggetto'], ['cliente', 'ragione_sociale']],
  variabili_non_usate: [],
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function routeFetch(routes: Record<string, { body: unknown; status?: number }>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input)
    const match = Object.keys(routes).find((key) => url.includes(key))
    const entry = match ? routes[match] : undefined
    return Promise.resolve(
      new Response(JSON.stringify(entry?.body ?? {}), {
        status: entry?.status ?? 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
  })
}

afterEach(() => vi.restoreAllMocks())

describe('variablesToFields', () => {
  it('maps a declared variable onto the FieldDefinition DynamicFieldRenderer expects', () => {
    expect(variablesToFields(DESCRIPTION.variabili)).toEqual([
      { key: 'oggetto', label: 'Oggetto', type: 'text', required: true, options: [] },
      { key: 'urgente', label: 'Urgente', type: 'checkbox', required: false, options: [] },
    ])
  })
})

describe('NewFromTemplateDialog', () => {
  it('lists the available templates', async () => {
    routeFetch({ '/api/templates': { body: [TEMPLATE] } })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    expect(await screen.findByText('Consulenza CTO')).toBeInTheDocument()
  })

  it('shows the declared variables once a template is chosen', async () => {
    routeFetch({
      '/describe': { body: DESCRIPTION },
      '/api/templates': { body: [TEMPLATE] },
    })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    expect(await screen.findByLabelText(/Oggetto/)).toBeInTheDocument()
    expect(await screen.findByLabelText(/Urgente/)).toBeInTheDocument()
  })

  it('sends an untouched checkbox as false, because create mode says so', async () => {
    const fetchSpy = routeFetch({
      '/describe': { body: DESCRIPTION },
      '/api/templates': { body: [TEMPLATE] },
      '/preview': { body: { markdown: 'Oggetto: Advisory' } },
      '/from-template': { body: { id: 'doc-1' } },
    })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    await userEvent.type(await screen.findByLabelText(/Oggetto/), 'Advisory')
    await userEvent.type(screen.getByLabelText('Titolo'), 'Offerta 2026-01')
    await userEvent.click(screen.getByRole('button', { name: 'Genera' }))

    await waitFor(() => {
      const call = fetchSpy.mock.calls.find(([url]) => String(url).includes('/from-template'))
      expect(call).toBeDefined()
      const body = JSON.parse(String((call?.[1] as RequestInit).body)) as {
        variabili: Record<string, unknown>
      }
      // `false` is a value, never a blank: an unchecked box the user looked at is an
      // answer, and `mode="create"` is what makes DynamicForm seed it.
      expect(body.variabili.urgente).toBe(false)
      expect(body.variabili.oggetto).toBe('Advisory')
    })
  })

  it('shows the preview the server rendered, never a client-side render', async () => {
    routeFetch({
      '/describe': { body: DESCRIPTION },
      '/api/templates': { body: [TEMPLATE] },
      '/preview': { body: { markdown: 'Oggetto: Advisory' } },
    })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    await userEvent.type(await screen.findByLabelText(/Oggetto/), 'Advisory')
    await userEvent.click(screen.getByRole('button', { name: 'Anteprima' }))
    expect(await screen.findByText('Oggetto: Advisory')).toBeInTheDocument()
  })

  it('shows the server validation message on the offending field', async () => {
    routeFetch({
      '/describe': { body: DESCRIPTION },
      '/api/templates': { body: [TEMPLATE] },
      '/from-template': {
        status: 422,
        body: {
          code: 'validation_failed',
          detail: 'template.oggetto: variabile obbligatoria mancante',
          field: 'oggetto',
          reason: 'variabile obbligatoria mancante: Oggetto',
        },
      },
    })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    await userEvent.type(screen.getByLabelText('Titolo'), 'Offerta')
    await userEvent.click(screen.getByRole('button', { name: 'Genera' }))
    expect(await screen.findByText(/variabile obbligatoria mancante: Oggetto/)).toBeInTheDocument()
  })

  it('shows an error banner when the template list fails, not an empty list', async () => {
    routeFetch({ '/api/templates': { status: 503, body: { code: 'http_error', detail: 'Giù' } } })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Giù')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/features/documents/NewFromTemplateDialog.test.tsx`
Expected: FAIL — `variablesToFields` is not exported by the stub.

- [ ] **Step 3: Write the component**

```tsx
// apps/web/src/features/documents/NewFromTemplateDialog.tsx
import { useState } from 'react'
import { DynamicForm } from '@/components/DynamicForm'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toProblem, type ProblemDetail } from '@/lib/api'
import type { FieldDefinition, FieldType } from '@/lib/schema'
import {
  useCreateFromTemplate,
  useTemplateDescription,
  useTemplatePreview,
  useTemplates,
  type DocumentOwner,
  type TemplateVariable,
} from './queries'

/**
 * A declared template variable, as the field renderer already understands it.
 *
 * `TemplateVariable.tipo` is deliberately one of the same nine `FieldType` values
 * custom fields use (see `templates/schemas.py`), so this is a rename, not a
 * translation, and `DynamicFieldRenderer` covers every case with no new code.
 */
export function variablesToFields(variables: TemplateVariable[]): FieldDefinition[] {
  return variables.map((variable) => ({
    key: variable.nome,
    label: variable.etichetta,
    type: variable.tipo as FieldType,
    required: variable.obbligatoria,
    options: [...(variable.options ?? [])],
  }))
}

/**
 * The form's state, in the two namespaces it will be sent in -- and never flattened.
 *
 * `native` holds the document's own fields (only `titolo` here); `custom` holds the
 * template's declared variables, which travel inside `variabili`. The split is
 * decided once, when the dialog seeds itself from the chosen template, and is never
 * re-derived at submit from the currently-described variable list. Re-deriving it is
 * the bug `CustomerFormValues` documents: a variable that disappears from the
 * description between seed and submit would be reclassified as a document field and
 * sent at the top level, where `DocumentFromTemplate` would reject it.
 */
export interface TemplateFormValues {
  native: Record<string, unknown>
  custom: Record<string, unknown>
}

const TITLE_FIELD_KEY = 'titolo'

/** Mirrors `is_blank` in packages/core/src/pigrocrm/core/fields/validator.py:
 *  `null`/`undefined`, a whitespace-only string, or an empty array mean "no value".
 *  `false` and `0` do not -- they are real answers. */
function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  owner: DocumentOwner
}

export function NewFromTemplateDialog({ open, onOpenChange, owner }: Props) {
  const templates = useTemplates()
  const [templateId, setTemplateId] = useState<string | null>(null)
  const description = useTemplateDescription(templateId)
  const preview = useTemplatePreview()
  const create = useCreateFromTemplate(owner)

  const [values, setValues] = useState<TemplateFormValues>({ native: {}, custom: {} })
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [previewText, setPreviewText] = useState<string | null>(null)

  const fields = description.data ? variablesToFields(description.data.variabili) : []

  /** A key present in `custom` stays custom for as long as the dialog is open, even
   *  if the description changes underneath it. Provenance is structural, never
   *  re-decided from a list that can change. */
  function change(key: string, value: unknown) {
    setValues((previous) =>
      key === TITLE_FIELD_KEY && !(key in previous.custom)
        ? { ...previous, native: { ...previous.native, [key]: value } }
        : { ...previous, custom: { ...previous.custom, [key]: value } },
    )
  }

  function chooseTemplate(id: string) {
    setTemplateId(id)
    setProblem(null)
    setPreviewText(null)
    // Seeded once, here. `custom` starts empty and DynamicForm's create-mode effect
    // fills in each checkbox with `false`; every other type stays absent until typed.
    setValues({ native: {}, custom: {} })
  }

  function collectVariables(): Record<string, unknown> {
    const variabili: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values.custom)) {
      // `false` and `0` pass this check: only a genuine blank is dropped, and a
      // dropped key is what lets the server report "variabile obbligatoria mancante"
      // by name instead of rendering an empty hole.
      if (!isBlank(value)) variabili[key] = value
    }
    return variabili
  }

  function runPreview() {
    if (!templateId) return
    setProblem(null)
    preview.mutate(
      { templateId, variabili: collectVariables() },
      {
        onSuccess: (result) => setPreviewText(result.markdown),
        onError: (error: unknown) => {
          setPreviewText(null)
          setProblem(toProblem(error))
        },
      },
    )
  }

  function generate() {
    if (!templateId) return
    setProblem(null)
    create.mutate(
      {
        template_id: templateId,
        titolo: String(values.native[TITLE_FIELD_KEY] ?? ''),
        variabili: collectVariables(),
      },
      {
        onSuccess: () => {
          onOpenChange(false)
          setTemplateId(null)
          setValues({ native: {}, custom: {} })
          setPreviewText(null)
        },
        onError: (error: unknown) => setProblem(toProblem(error)),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Nuovo documento da template</DialogTitle>
        </DialogHeader>

        {templates.isError && <QueryErrorBanner error={templates.error} />}

        {!templateId && !templates.isError && (
          <ul className="divide-y rounded-lg border">
            {(templates.data ?? []).map((template) => (
              <li key={template.id}>
                <button
                  type="button"
                  className="w-full px-4 py-3 text-left hover:bg-muted"
                  onClick={() => chooseTemplate(template.id)}
                >
                  <span className="font-medium">{template.nome}</span>
                  <span className="ml-2 text-sm text-muted-foreground">{template.tipo}</span>
                </button>
              </li>
            ))}
            {templates.data?.length === 0 && (
              <li className="px-4 py-3 text-muted-foreground">
                Nessun template. Creane uno in Impostazioni → Template.
              </li>
            )}
          </ul>
        )}

        {templateId && (
          <div className="space-y-5">
            {description.isError && <QueryErrorBanner error={description.error} />}

            <div className="space-y-1">
              <Label htmlFor="document-titolo">Titolo</Label>
              <Input
                id="document-titolo"
                value={String(values.native[TITLE_FIELD_KEY] ?? '')}
                onChange={(event) => change(TITLE_FIELD_KEY, event.target.value)}
              />
            </div>

            <DynamicForm
              fields={fields}
              values={values.custom}
              onChange={change}
              problem={problem}
              // Always "create": this dialog only ever composes a document that does
              // not exist yet, so an untouched checkbox is an honest `false` rather
              // than a value written on a record nobody edited.
              mode="create"
            />

            {previewText !== null && (
              <pre className="max-h-64 overflow-auto rounded-lg border bg-muted p-3 text-sm">
                {previewText}
              </pre>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annulla
          </Button>
          {templateId && (
            <>
              <Button variant="secondary" onClick={runPreview} disabled={preview.isPending}>
                {preview.isPending ? 'Anteprima…' : 'Anteprima'}
              </Button>
              <Button onClick={generate} disabled={create.isPending}>
                {create.isPending ? 'Generazione…' : 'Genera'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 4: Run the test and the type check**

Run: `cd apps/web && pnpm vitest run src/features/documents && pnpm tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/documents
git commit -m "feat(web): new document from template with declared variables and preview"
```

---

### Task 17: The document page — offer state, version history, regeneration

**Files:**
- Create: `apps/web/src/features/documents/OfferStatePicker.tsx`
- Create: `apps/web/src/features/documents/VersionHistory.tsx`
- Create: `apps/web/src/routes/app/documenti/$documentId.tsx`
- Create: `apps/web/src/features/documents/OfferStatePicker.test.tsx`
- Create: `apps/web/src/features/documents/VersionHistory.test.tsx`

**Interfaces:**
- Consumes from Task 14: `useDocument`, `useDocumentVersions`, `useSetOfferState`, `useRegenerateVersion`, `downloadDocument`, `OFFER_TRANSITIONS`, `OFFER_STATE_LABELS`, `Document`, `DocumentVersion`, `OfferState`. From slice 1: `EntityDetailLayout`, `QueryErrorBanner`.
- Produces:
  - `export function OfferStatePicker({ document }: { document: Document })`
  - `export function VersionHistory({ documentId }: { documentId: string })`
  - Route `/app/documenti/$documentId`

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/features/documents/OfferStatePicker.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OfferStatePicker } from './OfferStatePicker'
import type { Document } from './queries'

const OFFER: Document = {
  id: 'doc-1',
  customer_id: 'c-1',
  deal_id: null,
  tipo: 'offerta',
  titolo: 'Offerta 2026-01',
  stato: 'bozza',
  versione_corrente: 1,
  custom_fields: {},
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T09:00:00Z',
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

afterEach(() => vi.restoreAllMocks())

describe('OfferStatePicker', () => {
  it('offers only the transitions the backend allows from the current state', () => {
    render(<OfferStatePicker document={OFFER} />, { wrapper })
    expect(screen.getByRole('button', { name: 'Segna come Inviata' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Segna come Accettata' })).not.toBeInTheDocument()
  })

  it('offers nothing at all from a terminal state', () => {
    render(<OfferStatePicker document={{ ...OFFER, stato: 'accettata' }} />, { wrapper })
    expect(screen.getByText('Accettata')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Segna come/ })).not.toBeInTheDocument()
  })

  it('renders nothing for a document that is not an offer', () => {
    const { container } = render(
      <OfferStatePicker document={{ ...OFFER, tipo: 'verbale', stato: null }} />,
      { wrapper },
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('posts the chosen state', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ...OFFER, stato: 'inviata' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    render(<OfferStatePicker document={OFFER} />, { wrapper })
    await userEvent.click(screen.getByRole('button', { name: 'Segna come Inviata' }))
    await waitFor(() => {
      const call = fetchSpy.mock.calls.find(([url]) => String(url).includes('/stato'))
      expect(call).toBeDefined()
      expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ stato: 'inviata' })
    })
  })

  it('shows the server message when a transition is refused', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'conflict',
          detail: "document: da 'bozza' non si puo' passare a 'accettata'",
        }),
        { status: 409, headers: { 'content-type': 'application/json' } },
      ),
    )
    render(<OfferStatePicker document={OFFER} />, { wrapper })
    await userEvent.click(screen.getByRole('button', { name: 'Segna come Inviata' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('non si puo\' passare')
  })
})
```

```tsx
// apps/web/src/features/documents/VersionHistory.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VersionHistory } from './VersionHistory'

const VERSIONS = [
  {
    id: 'v-2',
    document_id: 'doc-1',
    numero: 2,
    template_id: 't-1',
    storage_key: 'acme-0123/doc-1/v2.pdf',
    content_type: 'application/pdf',
    dimensione: 12345,
    hash_sha256: 'a'.repeat(64),
    creato_da: null,
    created_at: '2026-08-10T10:00:00Z',
  },
  {
    id: 'v-1',
    document_id: 'doc-1',
    numero: 1,
    template_id: null,
    storage_key: 'acme-0123/doc-1/v1.pdf',
    content_type: 'application/pdf',
    dimensione: 999,
    hash_sha256: 'b'.repeat(64),
    creato_da: null,
    created_at: '2026-08-09T10:00:00Z',
  },
]

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function mockJson(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
  )
}

afterEach(() => vi.restoreAllMocks())

describe('VersionHistory', () => {
  it('lists every version newest first, with its size', async () => {
    mockJson(VERSIONS)
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    const items = await screen.findAllByRole('listitem')
    expect(items[0]).toHaveTextContent('v2')
    expect(items[1]).toHaveTextContent('v1')
    expect(items[0]).toHaveTextContent('12,1 kB')
  })

  it('offers regeneration only for a version that came from a template', async () => {
    mockJson(VERSIONS)
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    expect(await screen.findByRole('button', { name: 'Rigenera la versione 2' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rigenera la versione 1' })).not.toBeInTheDocument()
  })

  it('shows the server error instead of an empty history when the request fails', async () => {
    mockJson({ code: 'http_error', detail: 'Non disponibile' }, 503)
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    expect(await screen.findByRole('alert')).toHaveTextContent('Non disponibile')
  })

  it('posts a regeneration for the version it was asked about', async () => {
    const fetchSpy = mockJson(VERSIONS)
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: 'Rigenera la versione 2' }))
    await waitFor(() => {
      const called = fetchSpy.mock.calls.some(([url]) =>
        String(url).includes('/versions/2/regenerate'),
      )
      expect(called).toBe(true)
    })
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/web && pnpm vitest run src/features/documents/OfferStatePicker.test.tsx src/features/documents/VersionHistory.test.tsx`
Expected: FAIL — both modules are missing.

- [ ] **Step 3: Write `OfferStatePicker.tsx`**

```tsx
// apps/web/src/features/documents/OfferStatePicker.tsx
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { toProblem, type ProblemDetail } from '@/lib/api'
import {
  OFFER_STATE_LABELS,
  OFFER_TRANSITIONS,
  useSetOfferState,
  type Document,
  type OfferState,
} from './queries'

/**
 * The buttons come from the backend's own transition table, so the UI never offers a
 * move the server would refuse. It is not a second copy of the rule: the server still
 * checks, and a refusal is shown with the server's own message -- which is what
 * happens when the document changed underneath the page.
 */
export function OfferStatePicker({ document }: { document: Document }) {
  const setState = useSetOfferState(document.id)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  if (document.tipo !== 'offerta' || document.stato === null) return null

  const current = document.stato as OfferState
  const allowed = OFFER_TRANSITIONS[current] ?? []

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Stato:</span>
        <Badge>{OFFER_STATE_LABELS[current]}</Badge>
        {allowed.map((next) => (
          <Button
            key={next}
            size="sm"
            variant="secondary"
            disabled={setState.isPending}
            onClick={() => {
              setProblem(null)
              setState.mutate(next, { onError: (error: unknown) => setProblem(toProblem(error)) })
            }}
          >
            Segna come {OFFER_STATE_LABELS[next]}
          </Button>
        ))}
      </div>
      {problem && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {problem.detail}
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Write `VersionHistory.tsx`**

```tsx
// apps/web/src/features/documents/VersionHistory.tsx
import { useState } from 'react'
import { Download, RefreshCw } from 'lucide-react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { downloadDocument, useDocumentVersions, useRegenerateVersion } from './queries'

/** Bytes as the browser's own locale would write them. `Intl.NumberFormat` with a
 *  byte unit does the rounding, so nothing here does arithmetic on a size that could
 *  drift from what the server reported. */
function formatSize(bytes: number): string {
  return new Intl.NumberFormat('it-IT', {
    style: 'unit',
    unit: bytes >= 1000 ? 'kilobyte' : 'byte',
    maximumFractionDigits: 1,
  }).format(bytes >= 1000 ? bytes / 1000 : bytes)
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('it-IT', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Every version, newest first. Nothing here overwrites anything: regeneration adds a
 * new version rather than replacing the one it was built from, which is what makes
 * "una versione di sei mesi prima si rigenera identica" a check anyone can run.
 */
export function VersionHistory({ documentId }: { documentId: string }) {
  const versions = useDocumentVersions(documentId)
  const regenerate = useRegenerateVersion(documentId)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  if (versions.isError) return <QueryErrorBanner error={versions.error} />

  const items = versions.data ?? []

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium">Storico versioni</h3>
      {problem && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {problem.detail}
        </p>
      )}
      {items.length === 0 && <p className="text-muted-foreground">Nessuna versione.</p>}
      {items.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {items.map((version) => (
            <li key={version.id} className="flex items-center gap-3 px-4 py-3">
              <span className="w-10 font-medium">v{version.numero}</span>
              <span className="flex-1 text-sm text-muted-foreground">
                {formatDateTime(version.created_at)} · {formatSize(version.dimensione)}
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Scarica la versione ${version.numero}`}
                onClick={() => {
                  setProblem(null)
                  void downloadDocument(documentId, version.numero).catch((error: unknown) =>
                    setProblem(toProblem(error)),
                  )
                }}
              >
                <Download className="h-4 w-4" />
              </Button>
              {/* Only a version generated from a template can be regenerated: an
                  uploaded scan has no template and no variables to rebuild it from,
                  and the server refuses that call by name. */}
              {version.template_id !== null && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Rigenera la versione ${version.numero}`}
                  disabled={regenerate.isPending}
                  onClick={() => {
                    setProblem(null)
                    regenerate.mutate(version.numero, {
                      onError: (error: unknown) => setProblem(toProblem(error)),
                    })
                  }}
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Write the route**

```tsx
// apps/web/src/routes/app/documenti/$documentId.tsx
import { createFileRoute } from '@tanstack/react-router'
import { EntityDetailLayout } from '@/components/EntityDetailLayout'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { OfferStatePicker } from '@/features/documents/OfferStatePicker'
import { VersionHistory } from '@/features/documents/VersionHistory'
import { DOCUMENT_TYPE_LABELS, downloadDocument, useDocument } from '@/features/documents/queries'

export const Route = createFileRoute('/app/documenti/$documentId')({
  component: DocumentDetail,
})

function DocumentDetail() {
  const { documentId } = Route.useParams()
  const document = useDocument(documentId)

  if (document.isError) {
    return (
      <div className="p-8">
        <QueryErrorBanner error={document.error} />
      </div>
    )
  }
  if (!document.data) return <div className="p-8 text-muted-foreground">Caricamento…</div>

  const record = document.data

  return (
    <EntityDetailLayout
      title={record.titolo}
      subtitle={DOCUMENT_TYPE_LABELS[record.tipo] ?? record.tipo}
      entityType="document"
      entityId={record.id}
      actions={
        <Button
          disabled={record.versione_corrente === 0}
          onClick={() => void downloadDocument(record.id)}
        >
          Scarica
        </Button>
      }
      overview={
        <div className="space-y-6">
          <OfferStatePicker document={record} />
          <VersionHistory documentId={record.id} />
        </div>
      }
    />
  )
}
```

Regenerate the route tree: `cd apps/web && pnpm dev --help >/dev/null 2>&1 || true` is **not** how — the TanStack router plugin rewrites `src/routeTree.gen.ts` on build, so run `cd apps/web && pnpm build` once and commit the regenerated `routeTree.gen.ts` alongside the new route file.

- [ ] **Step 6: Run the tests and the type check**

Run: `cd apps/web && pnpm vitest run src/features/documents && pnpm tsc --noEmit`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/documents apps/web/src/routes/app/documenti apps/web/src/routeTree.gen.ts
git commit -m "feat(web): document page with offer state and version history"
```

---

### Task 18: Impostazioni — the Template editor and the Emittente profile

**Files:**
- Create: `apps/web/src/features/settings/TemplatesPanel.tsx`
- Create: `apps/web/src/features/settings/EmitterPanel.tsx`
- Create: `apps/web/src/features/settings/TemplatesPanel.test.tsx`
- Create: `apps/web/src/features/settings/EmitterPanel.test.tsx`
- Create: `apps/web/src/routes/app/impostazioni/template.tsx`
- Create: `apps/web/src/routes/app/impostazioni/emittente.tsx`
- Modify: `apps/web/src/features/settings/SettingsLayout.tsx:7-11` (two more tabs)
- Modify: `apps/web/src/features/settings/queries.ts` (emitter and template mutations)

**Interfaces:**
- Consumes from Task 14: `useTemplates`, `Template`, `EmitterProfile`. From slice 1: `DynamicForm`, `FieldDefinition`, `QueryErrorBanner`, `toProblem`/`ProblemDetail`.
- Produces:
  - In `features/settings/queries.ts`: `useCreateTemplate()`, `useUpdateTemplate(templateId: string)`, `useArchiveTemplate()`, `useEmitter()`, `useSaveEmitter()`
  - `export function TemplatesPanel()`
  - `export function EmitterPanel()`
  - Routes `/app/impostazioni/template` and `/app/impostazioni/emittente`

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/features/settings/TemplatesPanel.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TemplatesPanel } from './TemplatesPanel'

const TEMPLATE = {
  id: 't-1',
  nome: 'Consulenza CTO',
  tipo: 'offerta',
  corpo_markdown: 'Oggetto: {{oggetto}}',
  variabili_dichiarate: [
    { nome: 'oggetto', etichetta: 'Oggetto', tipo: 'text', obbligatoria: true, options: [] },
  ],
  attivo: true,
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T09:00:00Z',
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function routeFetch(routes: Record<string, { body: unknown; status?: number }>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input)
    const match = Object.keys(routes).find((key) => url.includes(key))
    const entry = match ? routes[match] : undefined
    return Promise.resolve(
      new Response(JSON.stringify(entry?.body ?? {}), {
        status: entry?.status ?? 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
  })
}

afterEach(() => vi.restoreAllMocks())

describe('TemplatesPanel', () => {
  it('lists the templates', async () => {
    routeFetch({ '/api/templates': { body: [TEMPLATE] } })
    render(<TemplatesPanel />, { wrapper })
    expect(await screen.findByText('Consulenza CTO')).toBeInTheDocument()
  })

  it('shows an error banner instead of an empty list when the request fails', async () => {
    routeFetch({ '/api/templates': { status: 503, body: { code: 'http_error', detail: 'Giù' } } })
    render(<TemplatesPanel />, { wrapper })
    expect(await screen.findByRole('alert')).toHaveTextContent('Giù')
    expect(screen.queryByText('Nessun template.')).not.toBeInTheDocument()
  })

  it('opens an editor with the Markdown body when a template is chosen', async () => {
    routeFetch({ '/api/templates': { body: [TEMPLATE] } })
    render(<TemplatesPanel />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: 'Modifica Consulenza CTO' }))
    expect(await screen.findByLabelText('Corpo del template (Markdown)')).toHaveValue(
      'Oggetto: {{oggetto}}',
    )
  })

  it('previews through the server, never by rendering the template client-side', async () => {
    const fetchSpy = routeFetch({
      '/api/templates': { body: [TEMPLATE] },
      '/preview': { body: { markdown: 'Oggetto: Advisory' } },
    })
    render(<TemplatesPanel />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: 'Modifica Consulenza CTO' }))
    await userEvent.click(screen.getByRole('button', { name: 'Anteprima' }))
    await waitFor(() => {
      expect(fetchSpy.mock.calls.some(([url]) => String(url).includes('/preview'))).toBe(true)
    })
    expect(await screen.findByText('Oggetto: Advisory')).toBeInTheDocument()
  })

  it('shows the parse error the server reports, with its template line', async () => {
    routeFetch({
      '/api/templates': { body: [TEMPLATE] },
      '/api/templates/t-1': {
        status: 422,
        body: {
          code: 'validation_failed',
          detail: 'template.corpo_markdown: riga 1: blocco {{#if}} non chiuso',
          field: 'corpo_markdown',
          reason: 'riga 1: blocco {{#if}} non chiuso',
        },
      },
    })
    render(<TemplatesPanel />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: 'Modifica Consulenza CTO' }))
    await userEvent.click(screen.getByRole('button', { name: 'Salva' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('riga 1')
  })
})
```

```tsx
// apps/web/src/features/settings/EmitterPanel.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EmitterPanel } from './EmitterPanel'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function mockJson(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
  )
}

afterEach(() => vi.restoreAllMocks())

describe('EmitterPanel', () => {
  it('offers an empty form when no profile has been saved yet', async () => {
    mockJson({ code: 'not_found', detail: 'emitter_profile singleton not found' }, 404)
    render(<EmitterPanel />, { wrapper })
    expect(await screen.findByLabelText(/Ragione sociale/)).toHaveValue('')
    // A 404 here means "not configured yet", not "the request failed": it is the one
    // status this panel treats as an empty form rather than as an error.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows an error banner for a real failure', async () => {
    mockJson({ code: 'http_error', detail: 'Servizio non disponibile' }, 503)
    render(<EmitterPanel />, { wrapper })
    expect(await screen.findByRole('alert')).toHaveTextContent('Servizio non disponibile')
  })

  it('sends the whole profile with PUT', async () => {
    const fetchSpy = mockJson({ code: 'not_found', detail: 'x' }, 404)
    render(<EmitterPanel />, { wrapper })
    await userEvent.type(await screen.findByLabelText(/Ragione sociale/), 'Humancraft')
    await userEvent.type(screen.getByLabelText(/P.IVA/), '14518240966')
    await userEvent.click(screen.getByRole('button', { name: 'Salva' }))
    await waitFor(() => {
      const call = fetchSpy.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === 'PUT',
      )
      expect(call).toBeDefined()
      const body = JSON.parse(String((call?.[1] as RequestInit).body)) as Record<string, unknown>
      expect(body.ragione_sociale).toBe('Humancraft')
      expect(body.partita_iva).toBe('14518240966')
    })
  })

  it('shows the server validation message on the offending field', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((_, init) =>
      Promise.resolve(
        (init as RequestInit | undefined)?.method === 'PUT'
          ? new Response(
              JSON.stringify({
                code: 'validation_failed',
                detail: 'emitter_profile.partita_iva: deve essere di 11 cifre',
                field: 'partita_iva',
                reason: 'deve essere di 11 cifre',
                expected: '11 cifre numeriche',
              }),
              { status: 422, headers: { 'content-type': 'application/json' } },
            )
          : new Response(JSON.stringify({ code: 'not_found', detail: 'x' }), {
              status: 404,
              headers: { 'content-type': 'application/json' },
            }),
      ),
    )
    render(<EmitterPanel />, { wrapper })
    await userEvent.type(await screen.findByLabelText(/Ragione sociale/), 'X')
    await userEvent.click(screen.getByRole('button', { name: 'Salva' }))
    expect(await screen.findByText(/deve essere di 11 cifre/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/web && pnpm vitest run src/features/settings/TemplatesPanel.test.tsx src/features/settings/EmitterPanel.test.tsx`
Expected: FAIL — both modules are missing.

- [ ] **Step 3: Add the settings mutations**

Append to `apps/web/src/features/settings/queries.ts`:

```ts
import type { EmitterProfile, Template } from '@/features/documents/queries'

export function useCreateTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/templates', { body: body as never })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.templates() }),
  })
}

export function useUpdateTemplate(templateId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/api/templates/{template_id}', {
          params: { path: { template_id: templateId } },
          body: body as never,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.templates() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.templateDescription(templateId) })
    },
  })
}

export function useArchiveTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (templateId: string) =>
      unwrap(
        api.DELETE('/api/templates/{template_id}', {
          params: { path: { template_id: templateId } },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.templates() }),
  })
}

/**
 * A 404 here is "not configured yet", not a failure: `GET /api/emitter` answers 404
 * until the profile is saved once, on purpose (an empty profile and an unsaved one
 * are different facts). `retry: false` keeps the query from re-asking three times for
 * an answer that will not change, and the panel reads `error.status === 404` to
 * decide between an empty form and an error banner.
 */
export function useEmitter() {
  return useQuery({
    retry: false,
    queryKey: queryKeys.emitter,
    queryFn: (): Promise<EmitterProfile> => unwrap(api.GET('/api/emitter', {})),
  })
}

export function useSaveEmitter() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.PUT('/api/emitter', { body: body as never })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.emitter }),
  })
}
```

Add whatever of `useMutation`, `useQuery`, `useQueryClient`, `api`, `unwrap`, `queryKeys` is not already imported at the top of that file.

- [ ] **Step 4: Write `TemplatesPanel.tsx`**

```tsx
// apps/web/src/features/settings/TemplatesPanel.tsx
import { useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useTemplatePreview, useTemplates, type Template } from '@/features/documents/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCreateTemplate, useUpdateTemplate } from './queries'

const EMPTY_BODY = `Spett.le **{{cliente.ragione_sociale}}**

**Oggetto: {{oggetto}}**

{{corpo}}

{{emittente.ragione_sociale}}
`

interface EditorState {
  id: string | null
  nome: string
  corpo_markdown: string
}

/**
 * The Markdown editor and its preview.
 *
 * The preview is rendered *by the server* (`POST /api/templates/{id}/preview`), never
 * by re-implementing the engine in TypeScript. A client-side renderer would be a
 * second implementation of the escaping rules -- exactly the three-interfaces-disagree
 * failure this project keeps closing -- and it would show the user something the PDF
 * will not contain.
 */
export function TemplatesPanel() {
  const templates = useTemplates()
  const [editor, setEditor] = useState<EditorState | null>(null)
  const create = useCreateTemplate()
  const update = useUpdateTemplate(editor?.id ?? '')
  const preview = useTemplatePreview()
  const [previewText, setPreviewText] = useState<string | null>(null)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  function open(template: Template | null) {
    setProblem(null)
    setPreviewText(null)
    setEditor(
      template === null
        ? { id: null, nome: '', corpo_markdown: EMPTY_BODY }
        : { id: template.id, nome: template.nome, corpo_markdown: template.corpo_markdown },
    )
  }

  function save() {
    if (!editor) return
    setProblem(null)
    const body = { nome: editor.nome, corpo_markdown: editor.corpo_markdown }
    const onError = (error: unknown) => setProblem(toProblem(error))
    if (editor.id === null) {
      create.mutate({ ...body, tipo: 'offerta' }, { onSuccess: () => setEditor(null), onError })
    } else {
      update.mutate(body, { onSuccess: () => setEditor(null), onError })
    }
  }

  return (
    <div className="space-y-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Template</h1>
        <Button onClick={() => open(null)}>Nuovo template</Button>
      </div>

      {templates.isError && <QueryErrorBanner error={templates.error} />}

      {!templates.isError && !editor && (
        <ul className="divide-y rounded-lg border">
          {(templates.data ?? []).map((template) => (
            <li key={template.id} className="flex items-center gap-3 px-4 py-3">
              <span className="flex-1 font-medium">{template.nome}</span>
              <span className="text-sm text-muted-foreground">{template.tipo}</span>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Modifica ${template.nome}`}
                onClick={() => open(template)}
              >
                Modifica
              </Button>
            </li>
          ))}
          {templates.data?.length === 0 && (
            <li className="px-4 py-3 text-muted-foreground">Nessun template.</li>
          )}
        </ul>
      )}

      {editor && (
        <div className="space-y-4">
          {problem && (
            <p
              role="alert"
              className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {problem.detail}
            </p>
          )}

          <div className="space-y-1">
            <Label htmlFor="template-nome">Nome</Label>
            <Input
              id="template-nome"
              value={editor.nome}
              onChange={(event) => setEditor({ ...editor, nome: event.target.value })}
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="template-corpo">Corpo del template (Markdown)</Label>
            <Textarea
              id="template-corpo"
              rows={20}
              className="font-mono text-sm"
              value={editor.corpo_markdown}
              onChange={(event) => setEditor({ ...editor, corpo_markdown: event.target.value })}
            />
            <p className="text-sm text-muted-foreground">
              Variabili: <code>{'{{cliente.ragione_sociale}}'}</code>, condizioni{' '}
              <code>{'{{#if x}}…{{/if}}'}</code>, cicli <code>{'{{#each righe}}…{{/each}}'}</code>.
            </p>
          </div>

          {previewText !== null && (
            <pre className="max-h-80 overflow-auto rounded-lg border bg-muted p-3 text-sm">
              {previewText}
            </pre>
          )}

          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setEditor(null)}>
              Annulla
            </Button>
            <Button
              variant="secondary"
              disabled={editor.id === null || preview.isPending}
              onClick={() => {
                if (editor.id === null) return
                setProblem(null)
                preview.mutate(
                  { templateId: editor.id, variabili: {} },
                  {
                    onSuccess: (result) => setPreviewText(result.markdown),
                    onError: (error: unknown) => {
                      setPreviewText(null)
                      setProblem(toProblem(error))
                    },
                  },
                )
              }}
            >
              Anteprima
            </Button>
            <Button onClick={save} disabled={create.isPending || update.isPending}>
              Salva
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Write `EmitterPanel.tsx`**

```tsx
// apps/web/src/features/settings/EmitterPanel.tsx
import { useState } from 'react'
import { DynamicForm } from '@/components/DynamicForm'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { toProblem, type ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'
import { useEmitter, useSaveEmitter } from './queries'

/** Exactly the fields `EmitterProfileUpsert` accepts (emitter/schemas.py), in the
 *  order a human fills them in. Listing them here rather than deriving them from the
 *  schema keeps the labels Italian and the order deliberate; `extra="forbid"` on the
 *  server is what catches a key that should not be here. */
const EMITTER_FIELDS: FieldDefinition[] = [
  { key: 'ragione_sociale', label: 'Ragione sociale', type: 'text', required: true, options: [] },
  { key: 'partita_iva', label: 'P.IVA', type: 'text', required: false, options: [] },
  { key: 'codice_fiscale', label: 'Codice fiscale', type: 'text', required: false, options: [] },
  { key: 'indirizzo', label: 'Indirizzo', type: 'text', required: false, options: [] },
  { key: 'cap', label: 'CAP', type: 'text', required: false, options: [] },
  { key: 'comune', label: 'Comune', type: 'text', required: false, options: [] },
  { key: 'provincia', label: 'Provincia', type: 'text', required: false, options: [] },
  { key: 'nazione', label: 'Nazione', type: 'text', required: false, options: [] },
  { key: 'pec', label: 'PEC', type: 'text', required: false, options: [] },
  { key: 'codice_sdi', label: 'Codice SDI', type: 'text', required: false, options: [] },
  { key: 'telefono', label: 'Telefono', type: 'text', required: false, options: [] },
  { key: 'email', label: 'Email', type: 'text', required: false, options: [] },
  { key: 'sito_web', label: 'Sito web', type: 'url', required: false, options: [] },
  { key: 'regime_fiscale', label: 'Regime fiscale', type: 'textarea', required: false, options: [] },
]

const EMITTER_FIELD_KEYS = EMITTER_FIELDS.map((field) => field.key)

/**
 * The single row that replaces the issuer data Acme hardcoded into `header.typ`.
 *
 * There is only one namespace here, not the usual `{native, custom}` split: the
 * emitter profile has no custom fields at all (it is not an `entity_type`), so there
 * is no second namespace to keep provenance for. The rule that split exists to
 * protect -- never re-derive at submit what was decided at seed -- is satisfied
 * trivially: `EMITTER_FIELD_KEYS` is a constant, not a runtime schema.
 *
 * `PUT` sends the whole profile every time, so a cleared text field arrives as `""`
 * and the server's own `_check_fiscal` normalises it to `None` -- the same "a native
 * column clears on an empty string" contract as everywhere else.
 */
export function EmitterPanel() {
  const emitter = useEmitter()
  const save = useSaveEmitter()
  const [values, setValues] = useState<Record<string, unknown> | null>(null)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const status = (emitter.error as { status?: number } | null)?.status
  const notConfigured = emitter.isError && status === 404
  if (emitter.isError && !notConfigured) {
    return (
      <div className="p-8">
        <QueryErrorBanner error={emitter.error} />
      </div>
    )
  }
  if (emitter.isPending && !notConfigured) {
    return <div className="p-8 text-muted-foreground">Caricamento…</div>
  }

  // Seeded once from whatever the server has (or from nothing, on a 404). `values`
  // stays null until the first edit, so a background refetch cannot overwrite what
  // the user is typing.
  const seeded: Record<string, unknown> =
    values ??
    Object.fromEntries(
      EMITTER_FIELD_KEYS.map((key) => [
        key,
        (emitter.data as Record<string, unknown> | undefined)?.[key] ?? '',
      ]),
    )

  return (
    <div className="space-y-6 p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Emittente</h1>
      <p className="text-muted-foreground">
        Questi dati compaiono nell'intestazione di ogni documento generato.
      </p>

      <DynamicForm
        fields={EMITTER_FIELDS}
        values={seeded}
        onChange={(key, value) => setValues({ ...seeded, [key]: value })}
        problem={problem}
        // Always "edit": there is exactly one profile and it is always the same row,
        // whether it has been saved before or not, so nothing here should ever write a
        // value the user did not choose.
        mode="edit"
      />

      <Button
        disabled={save.isPending}
        onClick={() => {
          setProblem(null)
          save.mutate(seeded, { onError: (error: unknown) => setProblem(toProblem(error)) })
        }}
      >
        {save.isPending ? 'Salvataggio…' : 'Salva'}
      </Button>
    </div>
  )
}
```

- [ ] **Step 6: Add the two routes and the two tabs**

```tsx
// apps/web/src/routes/app/impostazioni/template.tsx
import { createFileRoute } from '@tanstack/react-router'
import { TemplatesPanel } from '@/features/settings/TemplatesPanel'

export const Route = createFileRoute('/app/impostazioni/template')({
  component: TemplatesPanel,
})
```

```tsx
// apps/web/src/routes/app/impostazioni/emittente.tsx
import { createFileRoute } from '@tanstack/react-router'
import { EmitterPanel } from '@/features/settings/EmitterPanel'

export const Route = createFileRoute('/app/impostazioni/emittente')({
  component: EmitterPanel,
})
```

In `apps/web/src/features/settings/SettingsLayout.tsx`, extend `TABS` — both new panels are admin-only at the service layer (`TemplateService` and `EmitterProfileService` both call `actor.require_admin` on every write), so they belong inside the existing gate:

```tsx
const TABS = [
  { value: 'campi', label: 'Campi' },
  { value: 'pipeline', label: 'Pipeline' },
  { value: 'template', label: 'Template' },
  { value: 'emittente', label: 'Emittente' },
  { value: 'utenti', label: 'Utenti' },
] as const
```

Run `cd apps/web && pnpm build` once to regenerate `src/routeTree.gen.ts`, and commit it.

- [ ] **Step 7: Run the tests and the type check**

Run: `cd apps/web && pnpm vitest run src/features/settings && pnpm tsc --noEmit`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/settings apps/web/src/routes/app/impostazioni apps/web/src/routeTree.gen.ts
git commit -m "feat(web): template editor and emitter profile in settings"
```

---

# Fase 6 — RIMOSSA il 2026-08-20: nessun importer Attio

Il proprietario ha deciso di non usare più Attio, quindi non c'è nulla da importare. Il Task 19 è
rimosso dall'ambito: non rinviato, non esiste. **Il piano ha 18 task, non 19.**

Resta valida la ragione per cui Attio andava via, e sta nella spec dello slice 1: Acme leggeva le
anagrafiche da Attio tirando a indovinare gli slug dei campi fiscali — `vat_number` o `vat` o
`piva`, `sdi_code` o `codice_destinatario` o `codice_sdi` — così ogni fattura era un tiro di dado
sull'anagrafica. La sostituzione sono le colonne di prima classe per P.IVA, codice fiscale, SDI e
PEC, già spedite nello slice 1. Un eventuale import CSV generico, se un giorno servisse, è una
funzionalità diversa e va progettata come tale.

---

## Definition of done for slice 2

Every one of the spec's own success criteria (§11), checked by running something rather than by reading:

1. **An offer is created from a template, filled in, generated as a PDF and found again on the deal — without leaving the app.** Task 16's dialog, Task 15's tab, Task 17's page. Verified end to end by `apps/web/e2e/documents.spec.ts` and by hand against the running stack.
2. **The same result through Claude via MCP, calling the same services.** Task 13's `create_document_from_template`, and `packages/core/tests/test_architecture.py` still green — nothing in `packages/core` imports either adapter.
3. **A company name containing `#`, `@`, `$` or Markdown appears in the PDF as text, not as code.** `test_the_same_value_is_escaped_differently_in_the_two_contexts` (Task 3) and `test_an_injecting_customer_name_is_literal_in_both_contexts` (Task 11).
4. **A six-month-old version regenerates identically.** `test_regenerate_reproduces_an_old_version_as_a_new_one` (Task 11) asserts the identical `hash_sha256`.
5. **Swapping `LocalFileStorage` for `GDriveStorage` needs no service-code change, and the tests prove it on both.** `packages/core/tests/test_storage_conformance.py` (Task 5) is parametrised over both backends.

Plus the whole suite green: `cd packages/core && uv run pytest -q`, `cd apps/api && uv run pytest -q`, `cd apps/mcp && uv run pytest -q`, `cd apps/web && pnpm vitest run && pnpm tsc --noEmit`.

**Do not run `apps/web/scripts/e2e.sh` or `apps/web/scripts/e2e-teardown.sh` while a development server is running on port 5173** — they tear it down. Run Playwright directly against an already-running stack: `cd apps/web && pnpm exec playwright test`.

---

## Self-review

Run against the spec with fresh eyes, as `superpowers:writing-plans` requires. Findings, and what was changed inline.

### Spec coverage

| Spec section | Task |
|---|---|
| §3.1–3.2 placeholder syntax, `#if`/`#each`, no helpers | 2 (`_consume_token` rejects a helper call by name) |
| §3.3 per-context escaping, both adversarial values | 1, 3 |
| §4.1 `documents` | 6, 9 |
| §4.1 `entity_type = 'document'` for custom fields | 6 (`EntityType` widened, `CREATE_MODELS` entry) |
| §4.2 `document_versions`, nothing overwritten, reproducible | 6, 9, 11 |
| §4.3 `templates`, declared variables, precise failure | 6, 8 |
| §4.4 `emitter_profile` | 6, 7, 18 |
| §5 `DocumentStorage` protocol, both backends, `signed_url` `None` | 4, 5 |
| §6 Pandoc/Typst in the image, pinned, synchronous, no input on argv, template line in the error | 10 |
| §7 the seven MCP tools, same services, no bytes over MCP | 13 |
| §8 nessun importer Attio (deciso il 2026-08-20) | rimosso |
| §9 Documenti tab, drag & drop, new-from-template with `DynamicFieldRenderer`, preview, offer state, version history, regeneration, Template page | 15, 16, 17, 18 |
| §10 out of scope (email, e-signature, OCR, Office preview, realtime) | not planned, correctly |
| §11 all six criteria | Definition of done above |

**Gap found and closed:** §4.4 lists `logo` and `firma` on the emitter profile, and Acme's header embeds both images. Tasks 6/7 store them as `logo_key`/`firma_key` (storage keys, so a Drive-backed install keeps them too), but no task uploaded them. **Resolution, recorded rather than silently dropped:** Task 10 ships the logo and signature as the assets `render/assets/media/logo.png` and `render/assets/media/sign_is.png`, referenced by `header.typ.template` and by the offer body, so both render today. The two columns exist and are read by `EmitterProfileRead`; the *upload* UI for replacing them is not in this slice, and `EmitterPanel` (Task 18) deliberately does not render them as fields. That is a real, named limitation, not an oversight — a self-hoster replaces the two files in the image until a later slice adds the upload.

### Placeholder scan

Searched for `TBD`, `TODO`, `implement later`, `add appropriate`, `handle edge cases`, `similar to Task`, and `write tests for the above`. One real instance found and fixed: Task 15 originally referenced `NewFromTemplateDialog` before Task 16 defines it. Fixed inline by naming the exact one-line stub to write (`export function NewFromTemplateDialog() { return null }`) and stating that Task 16 replaces it — a fresh engineer executing Task 15 alone now has everything they need.

Two forward references remain and are deliberate, each with the exact content spelled out at the point of use rather than deferred: Task 6 writes the minimal `DocumentCreate` that `schema_registry` imports (Task 9 completes the module), and Task 15's stub above. Neither says "see Task N".

### Type consistency

Checked every name a later task uses against the task that defines it.

- `DocumentStorage` methods — `put/get/delete/signed_url` — identical in Task 4's Protocol, Task 4's `LocalFileStorage`, Task 5's `GDriveStorage`, and Task 9's call sites. ✅
- `render_template(source, values, declared)` — Task 3's signature is what Task 8's `preview`, Task 10's `build_header` and Task 11's `_render_to_pdf` all call. ✅
- `DeclaredVariable(nome, etichetta, tipo, obbligatoria)` — Task 3's dataclass; Task 8's `declared_variables` constructs exactly those four. ✅ Note the deliberate asymmetry: `TemplateVariable` (Task 8's Pydantic schema) also carries `options`, which the renderer has no use for; `declared_variables` drops it, which is why the two types are separate rather than one.
- `TYPST_LINE_MARKER_PREFIX` — defined in Task 3's `renderer.py`, imported by Task 10's `diagnostics.py`, emitted by Task 2's parser (after Task 3 Step 4 moves it there). **Inconsistency found:** the constant lives in `renderer.py` but the parser is what writes it, which would make `parser.py` import `renderer.py` and `renderer.py` import `parser.py` — a cycle. **Fixed inline:** Task 3 Step 4's replacement code writes the literal `"```{=typst}\n// pigrocrm:line="` rather than importing the constant, and the constant in `renderer.py` stays the single name that `diagnostics.py` reads. Task 3's own test asserts the two agree (`assert body.splitlines()[0] == f"{TYPST_LINE_MARKER_PREFIX}4"`), so a divergence fails loudly instead of silently breaking diagnostics.
- `OFFER_TRANSITIONS` — Task 11's Python `dict[str, frozenset[str]]` and Task 14's TypeScript `Record<OfferState, OfferState[]>` carry the same four entries; Task 14's test asserts each one, so a backend change that is not mirrored fails the frontend suite. ✅
- `DocumentService.__init__` — Task 9 defines `(session, storage)`, Task 11 widens it to `(session, storage, settings=None)` with a default, so every Task 9 call site still compiles. Task 12's routers pass all three. ✅
- `ALLOWED_CONTENT_TYPES` — Task 9's dict is the authority; Task 15's `ACCEPTED_UPLOAD_TYPES` lists the same seven values for the file picker's `accept` attribute only, with a comment saying the backend decides. ✅
- `DocumentOwner` — Task 14's `{customerId} | {dealId}`, used unchanged by Tasks 15, 16. ✅
- `queryKeys.documents/document/documentVersions/templates/templateDescription/emitter` — added in Task 14, used in 14, 15, 16, 17, 18. ✅
- `EntityType` — widened to include `document` in Task 6 (Python) and Task 14 (TypeScript); Task 17's document route passes `entityType="document"` to `EntityDetailLayout`, which types the prop as `EntityType`. ✅ Without Task 14's widening that route would not compile, which is why the two changes are named together.

### One further correction made inline

Task 12's `upload_version` route reads `file.content_type`, which is client-supplied. The first draft validated it in the router. That is business logic in an adapter — the exact thing this architecture forbids. Corrected: the router passes it straight through and `DocumentService.add_version` (Task 9) is the only place `ALLOWED_CONTENT_TYPES` is consulted, so the MCP path and any future adapter get the identical check for free.

