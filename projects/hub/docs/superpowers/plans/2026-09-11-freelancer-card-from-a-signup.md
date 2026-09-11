# Freelancer card from a signup: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A freelancer card can be created from a signup with the fields the public web
gives, shown incomplete in the admin area, and completed by the person from the member
area.

**Architecture:** The `freelancers` table loosens seven columns and records who wrote
the answers last (`compilata_da`). `FreelancerService.draft_from_signup` is the one
writer for research, exposed as `POST /api/hub/signups/{id}/scheda` and the MCP tool
`create_freelancer_from_signup`. The web reads the new nullable shape everywhere it
already reads a card.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, FastAPI, the `mcp`
SDK; React 19, TanStack Router and Query, vitest with Testing Library.

**Spec:** `projects/hub/docs/superpowers/specs/2026-09-11-freelancer-card-from-a-signup-design.md`

## Global Constraints

- Nothing in `projects/hub` imports PigroCRM (`ruff.toml` bans it).
- Conventional Commits, English, first person, no AI trailer, `ORB-155.` as the last line
  of every body. `git add <paths>`, never `-A`. The migration in a commit of its own.
- Strings the product shows are Italian; code, comments and tests are English.
- Tests run against a real Postgres brought to head by the migrations (testcontainers).
- Run Python from the repository root: `uv run pytest -q projects/hub/...`; web from the
  root: `pnpm --filter hub test`, `pnpm --filter hub lint`, `pnpm --filter hub build`.

---

### Task 1: Migration 0006 and the model

**Files:**
- Create: `projects/hub/packages/core/migrations/versions/0006_freelancer_card_from_signup.py`
- Modify: `projects/hub/packages/core/src/orbiters_core/models.py` (`Freelancer`)
- Test: `projects/hub/packages/core/tests/test_migrations.py` (existing, must stay green)

**Produces:** `COMPILATA_DA = ("persona", "admin")`; `Freelancer.cv_bytes`, `cv_filename`,
`cv_mime`, `cv_size`, `tariffa_giornaliera`, `posizione`, `remoto` as `Mapped[... | None]`
with `default=None`; `Freelancer.compilata_da: Mapped[str]` with `default="persona"`.

- [ ] Change the model columns to nullable and add `compilata_da` (String(10), nullable=False, default="persona").
- [ ] Run `uv run pytest -q projects/hub/packages/core/tests/test_migrations.py` and see it fail: metadata and schema disagree.
- [ ] Write the migration: `op.alter_column("freelancers", <col>, nullable=True)` for the seven; `op.add_column("freelancers", sa.Column("compilata_da", sa.String(10), nullable=False, server_default="persona"))` then `op.alter_column(..., server_default=None)`. Downgrade: drop the column, set the seven back to `nullable=False`.
- [ ] Run the migration test again: PASS.
- [ ] Commit: `feat(hub): a freelancer card may lack the CV, the rate, the position and the remote option` (migration only, with the model change).

### Task 2: Schemas

**Files:**
- Modify: `projects/hub/packages/core/src/orbiters_core/schemas.py`
- Test: `projects/hub/packages/core/tests/test_freelancers_companies.py`

**Produces:**
```python
class FreelancerDraft(BaseModel):
    nome: SafeStr; cognome: SafeStr
    linkedin_url: SafeStr | None = None
    posizione: SafeStr | None = None
    tariffa_giornaliera: Decimal | None = None
    remoto: Remoto | None = None
    links: list[SafeStr] = []
    fonti: list[SafeStr]  # 1..10 https URLs
```
`FreelancerRead` and `MemberProfile`: `cv_filename: str | None`, `cv_mime: str | None`
(read only), `cv_size: int | None`, `tariffa_giornaliera: Decimal | None`,
`posizione: str | None`, `remoto: str | None`, `compilata_da: str` (read only),
`completa: bool` as a `@computed_field`. `SignupListItem.freelancer_id: UUID | None = None`.

- [ ] Tests: `FreelancerDraft(nome="Ada", cognome="Lovelace", fonti=[])` raises; `fonti=["http://x"]` raises; a valid draft keeps `tariffa_giornaliera=None`; `FreelancerRead.completa` is False when `cv_size is None`.
- [ ] Implement; `completa = all(x is not None for x in (cv_size, tariffa_giornaliera, posizione, remoto))`.
- [ ] Run the core tests for schemas: PASS. Commit `feat(hub): the card's schemas carry what the web cannot answer as null`.

### Task 3: `FreelancerService.draft_from_signup` and `compilata_da` on writes

**Files:**
- Modify: `projects/hub/packages/core/src/orbiters_core/freelancers.py`, `members.py`, `service.py` (signups)
- Test: `projects/hub/packages/core/tests/test_freelancers_companies.py`, `test_members.py`, `test_signups.py`

**Produces:** `FreelancerService.draft_from_signup(signup_id: UUID, data: FreelancerDraft, autore: str) -> FreelancerRead`; `SignupService.list_recent` fills `freelancer_id`.

- [ ] Tests (core, freelancers): creates an incomplete card with the signup's email and utm, `compilata_da == "admin"`, `completa is False`, one comment whose text starts with «Scheda creata dall'iscrizione» and contains each source, `autore` as given; second call replaces `posizione` and leaves `stato`/`note`; on a `persona` card raises `ValidationFailed` with `field == "email"`; unknown signup raises `NotFound`; `apply` writes `compilata_da == "persona"`; `cv()` on a card without one raises `NotFound`.
- [ ] Tests (members): `update` on an `admin` card flips to `persona` and comments «Scheda confermata dalla persona» when nothing else moved; `replace_cv` on a CV-less card comments «CV caricato dalla persona»; `cv()` raises `NotFound` without one.
- [ ] Tests (signups): `list_recent` carries `freelancer_id` for an address that has a card, matched case-insensitively, `None` otherwise.
- [ ] Implement, run `uv run pytest -q projects/hub/packages/core/tests`: PASS. Commit `feat(hub): a freelancer card can be written from a signup, and records who filled it`.

### Task 4: API

**Files:**
- Modify: `projects/hub/apps/api/src/orbiters_api/routers/admin.py`, `routers/members.py` (cv 404 comes from `NotFound` already), `downloads.py` if it assumes a CV
- Test: `projects/hub/apps/api/tests/test_admin_api.py`, `test_member_api.py`

- [ ] Tests: `POST /api/hub/signups/{id}/scheda` without cookie → 401; with cookie and a valid body → 201, `compilata_da == "admin"`, `completa is False`, `commenti[0].autore` is the admin's name; wrong id → 404; on a card the person filled → 422 with `loc` ending in `email`; `GET /api/hub/signups` items have `freelancer_id`; `GET /freelancers/{id}/cv` on a CV-less card → 404; member flow: `PATCH /me` + `PUT /me/cv` complete an `admin` card, `GET /me` then says `completa: true`.
- [ ] Implement the route after `list_signups`: `FreelancerService(session).draft_from_signup(signup_id, payload, admin.nome)`, `status_code=201`.
- [ ] Run `uv run pytest -q projects/hub/apps/api/tests`: PASS. Commit `feat(api): an admin writes a freelancer card from a signup`.

### Task 5: MCP

**Files:**
- Modify: `projects/hub/apps/mcp/src/orbiters_mcp/server.py`
- Test: `projects/hub/apps/mcp/tests/test_tools.py`

- [ ] Test: seed a signup, call `create_freelancer_from_signup` with `nome`, `cognome`, `fonti`, `posizione`; the payload has `compilata_da == "admin"` and a comment by «MCP»; `list_signups` then shows the `freelancer_id`; the ban test still passes.
- [ ] Implement the tool with the signature in the spec; `Decimal(tariffa_giornaliera)` only when given.
- [ ] Run `uv run pytest -q projects/hub/apps/mcp/tests`: PASS. Commit `feat(mcp): create_freelancer_from_signup writes a card from an iscrizione`.

### Task 6: Web

**Files:**
- Modify: `projects/hub/apps/web/src/lib/api.ts`, `lib/member.tsx`, `pages/admin/lists.tsx`, `pages/member/Area.tsx`, `pages/member/Modifica.tsx`
- Test: `pages/admin/lists.test.tsx` (new), `pages/member/Area.test.tsx`, `pages/member/Modifica.test.tsx`

- [ ] Types: `Freelancer.cv_filename: string | null`, `cv_size: number | null`, `tariffa_giornaliera: string | null`, `posizione: string | null`, `remoto: Remoto | null`, `compilata_da: 'persona' | 'admin'`, `completa: boolean`; `Signup.freelancer_id: string | null`; `MemberProfile` the same nullables plus `completa`.
- [ ] `AdminSignups`: column «Scheda», link «apri» to `/admin/freelance/$id` or «—». Test: a row with a card renders a link with `href` ending in the id; a row without prints «—».
- [ ] `AdminFreelancers` and `AdminFreelancerDetail`: «—» for nulls, pill «Da completare» when `!completa`, CV button only with a CV, row «Scheda» with the ownership sentence. Test: an incomplete card renders the pill and no CV link.
- [ ] `Area`: notice when `!completa` with a link to `/io/modifica`; «Nessun CV» without a CV. `toApplication` maps nulls to `''`. Test: notice present for an incomplete profile and absent for a complete one.
- [ ] `Modifica`: `EDIT_STEPS` becomes a function `editSteps(hasCv: boolean)`; the CV step is optional only when `hasCv`. Test: saving an incomplete card without a CV shows the CV error and sends no request.
- [ ] `pnpm --filter hub test && pnpm --filter hub lint && pnpm --filter hub build`: PASS. Commit `feat(web): the admin sees an incomplete card and the member is asked to complete it`.

### Task 7: Docs and the PR

- [ ] `projects/hub/README.md` § What it does: one sentence on the card from a signup. `docs/design/DECISIONS.md`: a row dated 2026-09-11.
- [ ] `preflight --list`, then run what it selects. Screenshots before/after for «Iscrizioni», the freelancer detail and `/hub/io`.
- [ ] Open the PR with the template's sections, move ORB-155 to In Review with the URL, merge when green, tag `hub-v0.9.0` annotated on the merge commit, confirm `https://joinorbiters.com/health` and the new column in production.
