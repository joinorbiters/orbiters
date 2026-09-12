# ORB-171, uno spazio nasce pronto: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uno spazio appena creato ha già gli stati di pipeline, i template dei documenti (compresa un'offerta predefinita) e le categorie di costo; gli otto spazi esistenti si mettono in pari al primo avvio dopo il deploy; il profilo emittente nasce con la ragione sociale già scritta.

**Architecture:** Monorepo Orbiters, progetto `projects/pigrocrm/` (i percorsi sotto sono relativi a quella cartella; i comandi si lanciano dalla radice del repository, nel worktree `../pigrocrm-orb171`). Tutto in `packages/core` più una riga nel `CMD` di `Dockerfile.api`: una funzione `ensure_defaults(session)` che chiama i tre `seed_defaults` esistenti solo quando la tabella è vuota, chiamata da `TenantService.provision` e da un nuovo comando CLI `ensure-space-defaults` che scorre il registro. Nessuna migrazione. Niente in `apps/api/deps.py` o `tenancy.py`: ORB-170 li sta spostando.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Pydantic 2, pytest con testcontainers (Postgres 17), ruff, mypy strict.

**Spec:** `projects/pigrocrm/docs/superpowers/specs/2026-09-12-onboarding-product-led-design.md`, §6.5 (e §6.4 per la ragione sociale dell'emittente).

## Global Constraints

- Commit in inglese, Conventional Commits, prima persona, **nessun trailer AI** (root `AGENTS.md`); ultima riga del body `ORB-171.`; `git add` con pathspec, mai `-A`.
- `packages/core` non importa gli adapter; il test `test_architecture.py` legge le dipendenze da `pyproject.toml`: nessuna libreria nuova.
- I `seed_defaults` esistenti restano come sono (idempotenti, admin-only): si chiamano con `Actor.system()`.
- Il seme si applica **solo se la tabella è vuota**: un template predefinito cancellato apposta non ricompare.
- L'installazione radice non è toccata dal comando CLI (solo il registro degli spazi).
- Pandoc e Typst devono essere sul `PATH` per la suite completa; per i test di questo piano non servono.
- Test DB-backed: mai due invocazioni pytest in parallelo su questa macchina; usare `-n 0`.

---

### Task 1: il template «Offerta» entra nei predefiniti

**Files:**
- Create: `packages/core/src/pigrocrm/core/render/assets/template-offerta-default.md`
- Modify: `packages/core/src/pigrocrm/core/templates/service.py` (il metodo `seed_defaults`, righe 236-306)
- Test: `packages/core/tests/test_templates_service.py`

**Interfaces:**
- Produces: costanti `OFFERTA_TEMPLATE_NOME = "Offerta"` e `OFFERTA_TEMPLATE_VARIABLES` in `templates/service.py`; `TemplateService.seed_defaults` crea tre template (rapporto ore, sollecito, offerta) su un database vuoto.

- [ ] **Step 1: Scrivere il test che fallisce**

In `packages/core/tests/test_templates_service.py`, in coda al file:

```python
import re

from pigrocrm.core.templates.service import OFFERTA_TEMPLATE_NOME

# Quello che il corpo può leggere senza che il form lo chieda: il cliente e
# l'emittente li mette `DocumentService._template_scope`, `oggi` idem.
_SCOPE_PREFIXES = ("cliente.", "emittente.")
_SCOPE_KEYS = {"oggi"}


def test_seed_creates_a_default_offer_a_space_can_render_without_editing(
    db_session: Session,
) -> None:
    service = TemplateService(db_session)
    created = service.seed_defaults(ADMIN)
    offerta = next(t for t in created if t.nome == OFFERTA_TEMPLATE_NOME)
    assert offerta.tipo == "offerta"
    assert offerta.attivo is True
    declared = {v.nome for v in offerta.variabili_dichiarate}
    assert declared == {"oggetto", "ambito", "attivita", "compenso", "pagamento"}
    # Every placeholder in the body is either declared or supplied by the document
    # scope, so the first render of a fresh space cannot fail on a missing variable.
    placeholders = set(re.findall(r"\{\{([a-z_.]+)\}\}", offerta.corpo_markdown))
    for name in placeholders:
        assert (
            name in declared or name in _SCOPE_KEYS or name.startswith(_SCOPE_PREFIXES)
        ), name
    assert "{{#each" not in offerta.corpo_markdown


def test_seed_skips_the_offer_when_a_template_with_that_name_exists(
    db_session: Session,
) -> None:
    service = TemplateService(db_session)
    service.create(
        TemplateCreate(nome=OFFERTA_TEMPLATE_NOME, tipo="offerta", corpo_markdown="mia"),
        ADMIN,
    )
    created = service.seed_defaults(ADMIN)
    assert OFFERTA_TEMPLATE_NOME not in {t.nome for t in created}
    kept = TemplateRepository(db_session).get_by_nome(OFFERTA_TEMPLATE_NOME)
    assert kept is not None and kept.corpo_markdown == "mia"
```

`TemplateCreate` è già importato in testa al file (riga 10-15); se non lo fosse, aggiungerlo all'import da `pigrocrm.core.templates.schemas`.

- [ ] **Step 2: Eseguire il test e vederlo fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_templates_service.py -k "default_offer or skips_the_offer"`
Expected: FAIL con `ImportError: cannot import name 'OFFERTA_TEMPLATE_NOME'`.

- [ ] **Step 3: Scrivere l'asset del template**

`packages/core/src/pigrocrm/core/render/assets/template-offerta-default.md`, con esattamente questo contenuto (variabili piatte, perché una variabile dichiarata è un campo del form e non può essere una lista o un oggetto; `render/assets/template-offer.md`, quello con `{{#each offerta.righe}}`, resta l'asset del renderer e non si tocca):

```markdown
{{oggi}}

Spett.le **{{cliente.ragione_sociale}}**

**Oggetto: {{oggetto}}**

Facendo seguito ai contatti intercorsi, {{emittente.ragione_sociale}} sottopone la presente proposta di conferimento d'incarico per la prestazione di servizi professionali.

1. **Ambito del progetto e obiettivi**

{{ambito}}

2. **Attività**

{{attivita}}

3. **Esclusioni**

Non costituisce oggetto della presente proposta ogni altra attività non espressamente indicata in questo documento. Ogni estensione o modifica richiede conferma scritta e può comportare una revisione di tempi e costi.

4. **Condizioni economiche**

{{compenso}}

5. **Modalità di fatturazione e pagamento**

{{pagamento}}

6. **Riservatezza e proprietà intellettuale**

Le Parti mantengono riservate le informazioni ricevute e le utilizzano solo per l'esecuzione del progetto. {{emittente.ragione_sociale}} mantiene la titolarità di metodi, componenti riusabili e know-how; il Cliente ottiene il diritto d'uso dei deliverable per le finalità del progetto.

7. **Validità**

La presente proposta è valida per 30 giorni dalla data in testa. Per accettazione, restituire il documento firmato o confermare per email.

{{emittente.ragione_sociale}}
```

- [ ] **Step 4: Aggiungere l'offerta a `seed_defaults`**

In `packages/core/src/pigrocrm/core/templates/service.py`, sopra la classe `TemplateService` (dopo gli import, vicino a `ASSETS_DIR`):

```python
# The default offer a space is born with (spec 2026-09-12 §6.5). Flat variables on
# purpose: a declared variable is one field of the compilation form, so the body cannot
# iterate a list the way `render/assets/template-offer.md` does with `offerta.righe`.
# `cliente.*`, `emittente.*` and `oggi` come from `DocumentService._template_scope`.
OFFERTA_TEMPLATE_NOME = "Offerta"
OFFERTA_TEMPLATE_VARIABLES: tuple[dict[str, Any], ...] = (
    {"nome": "oggetto", "etichetta": "Oggetto", "tipo": "text", "obbligatoria": True},
    {"nome": "ambito", "etichetta": "Ambito e obiettivi", "tipo": "textarea", "obbligatoria": True},
    {"nome": "attivita", "etichetta": "Attività", "tipo": "textarea", "obbligatoria": True},
    {"nome": "compenso", "etichetta": "Condizioni economiche", "tipo": "textarea", "obbligatoria": True},
    {"nome": "pagamento", "etichetta": "Fatturazione e pagamento", "tipo": "textarea", "obbligatoria": True},
)
```

Se `Any` non è già importato, aggiungere `from typing import Any`. Poi, dentro `seed_defaults`, aggiungere una terza tupla a `seeds`, dopo quella del sollecito:

```python
            # The offer every space starts from (spec 2026-09-12 §6.5): the one
            # document the landing promises, editable in Impostazioni → Template like
            # the other two. `template-offer.md` stays the renderer's own asset.
            (
                OFFERTA_TEMPLATE_NOME,
                "offerta",
                (ASSETS_DIR / "template-offerta-default.md").read_text(encoding="utf-8"),
                OFFERTA_TEMPLATE_VARIABLES,
            ),
```

e aggiornare la frase della docstring «Seeds two templates: the timesheet, and slice 5's payment reminder.» in «Seeds three templates: the timesheet, slice 5's payment reminder and the default offer (spec 2026-09-12 §6.5).» lasciando il resto della docstring com'è.

- [ ] **Step 5: Eseguire i test e vederli passare**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_templates_service.py projects/pigrocrm/packages/core/tests/test_sollecito_template.py`
Expected: PASS, nessun test esistente rotto (chi contava «due template creati» va aggiornato a tre se esiste: cercare `len(created) == 2` nel file e correggere in 3, con la ragione nel test).

- [ ] **Step 6: Lint e tipi**

Run: `uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: puliti. Se `ruff format --check` segnala il file, eseguire `uv run ruff format projects/pigrocrm/packages/core/src/pigrocrm/core/templates/service.py`.

- [ ] **Step 7: Commit**

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/render/assets/template-offerta-default.md \
        projects/pigrocrm/packages/core/src/pigrocrm/core/templates/service.py \
        projects/pigrocrm/packages/core/tests/test_templates_service.py
git commit -m "feat(core): the default templates include an offer a space can render as is" -m "The landing promises offers in PDF from your templates; a space had only the timesheet and the reminder, and the offer asset uses a list no compilation form can fill. This seeds an editable «Offerta» with five flat variables and leaves render/assets/template-offer.md alone.

ORB-171."
```

Controllare `git log -1 --format=%B`: nessun trailer `Co-Authored-By`.

---

### Task 2: `ensure_defaults`, il seme che agisce solo su tabelle vuote

**Files:**
- Create: `packages/core/src/pigrocrm/core/tenants/defaults.py`
- Modify: `packages/core/src/pigrocrm/core/tenants/__init__.py` (export)
- Test: `packages/core/tests/test_space_defaults.py` (nuovo)

**Interfaces:**
- Consumes: `PipelineService(session).seed_defaults(actor)`, `TemplateService(session).seed_defaults(actor)`, `CostCategoryService(session).seed_defaults(actor)`; i modelli `PipelineStage` (`pipeline.models`), `Template` (`templates.models`), `CostCategory` (`timetracking.models`).
- Produces: `ensure_defaults(session: Session) -> DefaultsReport` con `DefaultsReport(stages: int, templates: int, categories: int)` e la proprietà `seeded: bool`.

- [ ] **Step 1: Scrivere il test che fallisce**

`packages/core/tests/test_space_defaults.py`:

```python
"""`ensure_defaults`: what a space contains before anyone types, and only when the
table is empty (spec 2026-09-12 §6.5)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.service import DEFAULT_STAGES
from pigrocrm.core.templates.models import Template
from pigrocrm.core.templates.schemas import TemplateCreate
from pigrocrm.core.templates.service import TemplateService
from pigrocrm.core.tenants import ensure_defaults
from pigrocrm.core.timetracking.categories import SEED_CATEGORIES
from pigrocrm.core.timetracking.models import CostCategory

ADMIN = Actor(id=None, type="system", role="admin")


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_an_empty_space_gets_stages_templates_and_categories(db_session: Session) -> None:
    report = ensure_defaults(db_session)
    assert report.seeded is True
    assert _count(db_session, PipelineStage) == len(DEFAULT_STAGES)
    assert _count(db_session, CostCategory) == len(SEED_CATEGORIES)
    assert _count(db_session, Template) == 3
    assert (report.stages, report.categories, report.templates) == (
        len(DEFAULT_STAGES),
        len(SEED_CATEGORIES),
        3,
    )


def test_a_table_that_is_not_empty_is_left_alone(db_session: Session) -> None:
    TemplateService(db_session).create(
        TemplateCreate(nome="Il mio contratto", tipo="contratto", corpo_markdown="x"), ADMIN
    )
    report = ensure_defaults(db_session)
    # Templates: the one row the person made, and nothing added beside it.
    assert report.templates == 0
    assert [t.nome for t in db_session.scalars(select(Template)).all()] == ["Il mio contratto"]
    # The other two families were empty and are seeded regardless.
    assert report.stages == len(DEFAULT_STAGES)
    assert report.categories == len(SEED_CATEGORIES)


def test_a_second_call_seeds_nothing(db_session: Session) -> None:
    ensure_defaults(db_session)
    again = ensure_defaults(db_session)
    assert again.seeded is False
    assert (again.stages, again.templates, again.categories) == (0, 0, 0)
```

- [ ] **Step 2: Eseguire il test e vederlo fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_space_defaults.py`
Expected: FAIL con `ImportError: cannot import name 'ensure_defaults' from 'pigrocrm.core.tenants'`.

- [ ] **Step 3: Scrivere `defaults.py`**

`packages/core/src/pigrocrm/core/tenants/defaults.py`:

```python
"""What a space contains before anyone types (spec 2026-09-12 §6.5).

The three seeds already exist and are idempotent on their own key (`code` for stages
and categories, `lower(nome)` for templates). What this adds is the one rule they do
not have: **a family is seeded only while its table is empty**. A person who deleted a
default template to make their own must not find it back at the next boot, and a
pipeline that somebody reshaped is theirs. Called from `TenantService.provision` for a
new space and from `pigrocrm ensure-space-defaults` for the spaces that already exist.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm.core.templates.models import Template
from pigrocrm.core.templates.service import TemplateService
from pigrocrm.core.timetracking.categories import CostCategoryService
from pigrocrm.core.timetracking.models import CostCategory


@dataclass(frozen=True)
class DefaultsReport:
    """How many rows each family gained. Zero everywhere means the space was already
    furnished, which is what the CLI prints as «già a posto»."""

    stages: int
    templates: int
    categories: int

    @property
    def seeded(self) -> bool:
        return bool(self.stages or self.templates or self.categories)


def _is_empty(session: Session, model: type[PipelineStage | Template | CostCategory]) -> bool:
    return (session.scalar(select(func.count()).select_from(model)) or 0) == 0


def ensure_defaults(session: Session) -> DefaultsReport:
    """On a session of one space (never of the registry). Commits, through the seeds."""
    actor = Actor.system()
    stages = templates = categories = 0
    if _is_empty(session, PipelineStage):
        # `PipelineService.seed_defaults` answers the whole list, not only what it
        # created; on an empty table the two are the same.
        stages = len(PipelineService(session).seed_defaults(actor))
    if _is_empty(session, Template):
        templates = len(TemplateService(session).seed_defaults(actor))
    if _is_empty(session, CostCategory):
        categories = len(CostCategoryService(session).seed_defaults(actor))
    return DefaultsReport(stages=stages, templates=templates, categories=categories)
```

- [ ] **Step 4: Esportare da `tenants/__init__.py`**

In `packages/core/src/pigrocrm/core/tenants/__init__.py` aggiungere l'import

```python
from pigrocrm.core.tenants.defaults import DefaultsReport, ensure_defaults
```

e le due voci `"DefaultsReport"` e `"ensure_defaults"` in `__all__`, in ordine alfabetico (dopo `"TenantsBase"`, prima di `"ensure_tenants_database"` per `ensure_defaults`; `"DefaultsReport"` va prima di `"RESERVED_SLUGS"`).

Se l'import crea un ciclo (`pipeline.service` → … → `tenants`), il sintomo è un `ImportError` all'import di `pigrocrm.core.tenants`: in quel caso spostare l'import di `defaults` in fondo a `__init__.py` con un commento che dice perché, come fa `templates/service.py` con gli import locali in `seed_defaults`.

- [ ] **Step 5: Eseguire i test e vederli passare**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_space_defaults.py projects/pigrocrm/packages/core/tests/test_architecture.py`
Expected: PASS.

- [ ] **Step 6: Lint e tipi**

Run: `uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: puliti.

- [ ] **Step 7: Commit**

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/defaults.py \
        projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/__init__.py \
        projects/pigrocrm/packages/core/tests/test_space_defaults.py
git commit -m "feat(core): ensure_defaults seeds a space's stages, templates and categories while their tables are empty" -m "The three seeds existed and were manual. This is the rule they lacked: a family is seeded only while its table is empty, so a default somebody deleted on purpose never comes back.

ORB-171."
```

---

### Task 3: il provisioning semina i predefiniti e scrive la ragione sociale

**Files:**
- Modify: `packages/core/src/pigrocrm/core/tenants/service.py` (`provision`, righe 100-136)
- Test: `packages/core/tests/test_tenants.py` (`test_provisioning_creates_a_migrated_database_with_one_admin`, righe 107-139)

**Interfaces:**
- Consumes: `ensure_defaults(session)` (Task 2); `EmitterProfileService(session).upsert(EmitterProfileUpsert(ragione_sociale=...), Actor.system())` da `pigrocrm.core.emitter.service` e `.schemas`; `RAGIONE_SOCIALE_MAX_LENGTH = 255` in `emitter/schemas.py`.
- Produces: uno spazio provisionato ha 6 stati, 3 template, 5 categorie e una riga in `emitter_profile` con la sola `ragione_sociale`.

- [ ] **Step 1: Estendere il test esistente**

In `packages/core/tests/test_tenants.py`, dentro `test_provisioning_creates_a_migrated_database_with_one_admin`, dopo l'assert su `customers`:

```python
                # Born ready (spec 2026-09-12 §6.5): the first deal, the first offer and
                # the first cost need nothing from Impostazioni.
                assert connection.execute(text("select count(*) from pipeline_stages")).scalar() == 6
                names = connection.execute(text("select nome from templates order by nome")).scalars().all()
                assert "Offerta" in names and len(names) == 3
                assert connection.execute(text("select count(*) from cost_categories")).scalar() == 5
                # The emitter carries the name and nothing fiscal: that is the person's.
                emitter = connection.execute(
                    text("select ragione_sociale, partita_iva, codice_fiscale from emitter_profile")
                ).all()
                assert emitter == [("Ada Lovelace", None, None)]
```

- [ ] **Step 2: Eseguire il test e vederlo fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_tenants.py -k provisioning_creates`
Expected: FAIL su `assert 0 == 6`.

- [ ] **Step 3: Chiamare `ensure_defaults` e l'emittente in `provision`**

In `packages/core/src/pigrocrm/core/tenants/service.py`, aggiungere agli import:

```python
from pigrocrm.core.emitter.schemas import RAGIONE_SOCIALE_MAX_LENGTH, EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.tenants.defaults import ensure_defaults
```

e nel blocco `with session_factory(engine)() as space:` di `provision`, dopo la chiamata a `UserService(space).create(...)`, nello stesso `try`:

```python
                    # Born ready (spec 2026-09-12 §6.5): stages, templates and
                    # categories, then an emitter that carries the name and nothing
                    # fiscal. Inside the same try: a space that fails here is undone
                    # like one whose migration failed.
                    ensure_defaults(space)
                    EmitterProfileService(space).upsert(
                        EmitterProfileUpsert(
                            ragione_sociale=data.nome[:RAGIONE_SOCIALE_MAX_LENGTH]
                        ),
                        Actor.system(),
                    )
```

Aggiornare la prima riga della docstring del modulo (`"""Provisioning a space: a registry row, a database, its schema, its first admin.`) in `"""Provisioning a space: a registry row, a database, its schema, its first admin, its defaults.`

- [ ] **Step 4: Eseguire i test dei tenant e vederli passare**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_tenants.py`
Expected: PASS, compresi `test_the_same_name_twice...` e `test_a_short_password_provisions_nothing...` (la password corta fallisce prima dei semi e l'`_undo` resta identico).

- [ ] **Step 5: I test API degli spazi**

Run: `uv run pytest -q -n 0 projects/pigrocrm/apps/api/tests/test_tenants_api.py`
Expected: PASS. Se un test conta i template o gli stati di uno spazio nuovo, aggiornare il numero con una riga che spiega il perché.

- [ ] **Step 6: Lint e tipi**

Run: `uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: puliti.

- [ ] **Step 7: Commit**

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/service.py \
        projects/pigrocrm/packages/core/tests/test_tenants.py
git commit -m "feat(core): a provisioned space is born with its defaults and an emitter that carries the name" -m "Read in production on 2026-09-12: eight spaces, zero stages, zero templates. The seeds were a button in Impostazioni. Now provision runs them, and the emitter profile opens with ragione_sociale already filled; fiscal data stays the person's to type.

ORB-171."
```

---

### Task 4: `pigrocrm ensure-space-defaults`, per gli spazi che esistono già

**Files:**
- Modify: `packages/core/src/pigrocrm/core/cli.py` (nuova funzione e il sottocomando in `main`, righe 278-305)
- Test: `packages/core/tests/test_tenants.py` (nuovo test in coda)

**Interfaces:**
- Consumes: `TenantService(registry_session, settings).list()` (`TenantRead`: `slug`, `owner_email`, `created_at`); `tenant_database_name(slug)`, `tenant_database_url(settings, db_name)`; `ensure_defaults(session)`.
- Produces: `cli.ensure_space_defaults() -> int`, sottocomando `ensure-space-defaults`. Ritorna sempre 0: un errore su uno spazio va su stderr e non ferma gli altri, perché il comando gira nel `CMD` del container prima di uvicorn e non deve mai impedire all'API di partire.

- [ ] **Step 1: Scrivere il test che fallisce**

In coda a `packages/core/tests/test_tenants.py`:

```python
def test_the_cli_furnishes_an_existing_space_that_has_nothing(
    settings: Settings, registry_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pigrocrm.core import cli

    service = TenantService(registry_session, settings)
    slug = "prova-arredo"
    try:
        service.provision(
            TenantSignup(slug=slug, nome="Ada", email="ada@studio.it", password="lunghissima1")
        )
        space = create_engine(
            tenant_database_url(settings, tenant_database_name(slug)), future=True
        )
        try:
            # The state the eight production spaces are in: born before the seeds.
            with space.begin() as connection:
                connection.execute(text("delete from pipeline_stages"))
                connection.execute(text("delete from cost_categories"))
            monkeypatch.setattr(cli, "get_settings", lambda: settings)
            assert cli.main(["ensure-space-defaults"]) == 0
            out = capsys.readouterr().out
            assert slug in out and "stati 6" in out and "categorie 5" in out
            with space.connect() as connection:
                assert connection.execute(text("select count(*) from pipeline_stages")).scalar() == 6
                assert connection.execute(text("select count(*) from cost_categories")).scalar() == 5
                # Templates were not empty and are untouched: still the three seeds.
                assert connection.execute(text("select count(*) from templates")).scalar() == 3
            # A second run has nothing to do and says so.
            assert cli.main(["ensure-space-defaults"]) == 0
            assert "già a posto" in capsys.readouterr().out
        finally:
            space.dispose()
    finally:
        _drop(settings, slug)
        registry_session.execute(text("delete from tenants where slug = :s"), {"s": slug})
        registry_session.commit()
```

`pytest` è già importato nel file. Nota: il registro dei test può contenere gli spazi di altri test dello stesso modulo solo mentre girano; ognuno li rimuove nel proprio `finally`, quindi qui il registro ha una riga sola.

- [ ] **Step 2: Eseguire il test e vederlo fallire**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_tenants.py -k furnishes`
Expected: FAIL: `argparse` esce con `SystemExit(2)` («invalid choice: 'ensure-space-defaults'»).

- [ ] **Step 3: Scrivere il comando**

In `packages/core/src/pigrocrm/core/cli.py`, dopo `seed_templates`:

```python
def ensure_space_defaults() -> int:
    """`pigrocrm ensure-space-defaults`: every space in the registry gets the stages,
    templates and categories it lacks, table by table, only where the table is empty
    (spec 2026-09-12 §6.5). Runs in the API image's CMD after the migrations, so the
    spaces created before the seeds existed catch up at the first boot after the deploy.

    Always answers 0. One space that cannot be reached is reported on stderr and skipped:
    this runs before uvicorn, and a furnishing problem must never keep the API down. The
    root installation is not in the registry and is not touched."""
    from sqlalchemy import create_engine

    from pigrocrm.core.tenants import TenantService, ensure_defaults, ensure_tenants_database
    from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url

    settings = get_settings()
    registry = ensure_tenants_database(settings)
    try:
        with session_factory(registry)() as session:
            spaces = TenantService(session, settings).list()
    finally:
        registry.dispose()
    if not spaces:
        print("nessuno spazio nel registro")
        return 0
    for tenant in spaces:
        url = tenant_database_url(settings, tenant_database_name(tenant.slug))
        engine = create_engine(url, future=True)
        try:
            with session_factory(engine)() as space:
                report = ensure_defaults(space)
        except Exception as exc:  # noqa: BLE001 - one space must not stop the others
            print(f"{tenant.slug}: non raggiungibile ({type(exc).__name__})", file=sys.stderr)
            continue
        finally:
            engine.dispose()
        if report.seeded:
            print(
                f"{tenant.slug}: stati {report.stages}, template {report.templates}, "
                f"categorie {report.categories}"
            )
        else:
            print(f"{tenant.slug}: già a posto")
    return 0
```

In `main`, dopo `sub.add_parser("seed-templates", ...)`:

```python
    sub.add_parser(
        "ensure-space-defaults",
        help="Dà a ogni spazio del registro stati, template e categorie predefiniti, se le tabelle sono vuote",
    )
```

e dopo il ramo `if args.command == "seed-templates":`:

```python
    if args.command == "ensure-space-defaults":
        return ensure_space_defaults()
```

Nel messaggio su stderr va solo il tipo dell'eccezione, mai il suo testo: una `OperationalError` di psycopg può contenere l'URL con la password.

- [ ] **Step 4: Eseguire i test e vederli passare**

Run: `uv run pytest -q -n 0 projects/pigrocrm/packages/core/tests/test_tenants.py projects/pigrocrm/packages/core/tests/test_cli_gmail.py`
Expected: PASS.

- [ ] **Step 5: Lint e tipi**

Run: `uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy`
Expected: puliti. Se ruff segnala `BLE001` nonostante il `noqa`, il codice della regola nel repo potrebbe essere un altro: leggere il messaggio e usare quel codice.

- [ ] **Step 6: Commit**

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/cli.py \
        projects/pigrocrm/packages/core/tests/test_tenants.py
git commit -m "feat(core): pigrocrm ensure-space-defaults furnishes every registered space whose tables are empty" -m "For the spaces created before the seeds existed. Walks the registry, one engine per space, and never fails the process: it will run before uvicorn.

ORB-171."
```

---

### Task 5: il container esegue il comando a ogni avvio

**Files:**
- Modify: `Dockerfile.api:74` (il `CMD`)
- Modify: `AGENTS.md` (progetto, sezione «Migrations live in ...», una frase)

**Interfaces:**
- Consumes: `python -m pigrocrm.core.cli ensure-space-defaults` (il modulo ha `if __name__ == "__main__": raise SystemExit(main())`).

- [ ] **Step 1: Cambiare il `CMD`**

In `projects/pigrocrm/Dockerfile.api`, riga 74, il `CMD` diventa (una riga sola):

```dockerfile
CMD ["sh", "-c", "cd projects/pigrocrm/packages/core && uv run --no-sync alembic upgrade head && cd /app && uv run --no-sync python -m pigrocrm.core.cli ensure-space-defaults && uv run --no-sync uvicorn pigrocrm_api.main:app --host 0.0.0.0 --port 8000"]
```

`--no-sync` è obbligatorio, come per gli altri due comandi (`AGENTS.md`, «`--no-sync` on the container's `uv run` calls is load-bearing»).

- [ ] **Step 2: Verificare che l'immagine si costruisca e il comando esista nel container**

Run, dalla radice del repository (richiede Docker; se il demone non è disponibile, dirlo nella PR e saltare):

```bash
docker build -f projects/pigrocrm/Dockerfile.api -t pigrocrm-api:orb171 . && \
docker run --rm pigrocrm-api:orb171 sh -c "cd /app && uv run --no-sync python -m pigrocrm.core.cli --help"
```

Expected: build ok e l'help elenca `ensure-space-defaults` fra i sottocomandi.

- [ ] **Step 3: Una frase in `AGENTS.md` del progetto**

In `projects/pigrocrm/AGENTS.md`, nel paragrafo che inizia con «**Migrations live in `packages/core/migrations`**», aggiungere in coda:

```markdown
After the migrations the same `CMD` runs `pigrocrm ensure-space-defaults`, which gives
every space in the registry its default stages, templates and cost categories where a
table is empty, and never fails the boot (spec 2026-09-12 §6.5).
```

- [ ] **Step 4: Commit**

```bash
git add projects/pigrocrm/Dockerfile.api projects/pigrocrm/AGENTS.md
git commit -m "chore(api): the container furnishes the registered spaces after the migrations" -m "So the eight spaces that exist today catch up at the first boot after the deploy, with no command run by hand.

ORB-171."
```

---

### Task 6: la spec, questo piano, la decisione e la riga del progetto

**Files:**
- Already created: `docs/superpowers/specs/2026-09-12-onboarding-product-led-design.md`, `docs/superpowers/plans/2026-09-12-orb-171-uno-spazio-nasce-pronto.md`
- Modify: `docs/design/DECISIONS.md` (radice del repository, una riga in coda)
- Modify: `docs/tracker.md` (radice, tabella dei progetti, una riga)

- [ ] **Step 1: La riga in `DECISIONS.md`**

In coda a `docs/design/DECISIONS.md` (mai riscrivere una riga esistente):

```markdown
| 2026-09-12 | Eight spaces were created in three days and none has a customer, a deal or an invoice; a new space is born with no pipeline stages, no templates and no cost categories, and the seeds are a button in Impostazioni or a CLI on the server. What does a space contain when it is born, and what happens to the ones that exist? | A space is provisioned with the default stages, the default templates (an editable «Offerta» included) and the default cost categories, and an emitter profile that carries only the signup name; `pigrocrm ensure-space-defaults` runs in the API image's `CMD` after the migrations and furnishes every registered space whose table is empty (ORB-171, spec `projects/pigrocrm/docs/superpowers/specs/2026-09-12-onboarding-product-led-design.md` §6.5). | A default is seeded only while its table is empty: what a person deleted on purpose never comes back. A command that runs before the API starts never fails the boot. The root installation keeps the defaults Ivan chose and is not in the registry. |
```

Se `origin/main` ha già aggiunto righe nel frattempo, la propria va **dopo** le loro: prendere il file di `main` e riappendere questa riga (memoria: quasi ogni PR tocca questo file).

- [ ] **Step 2: La riga del progetto in `docs/tracker.md`**

Nella tabella dei progetti, dopo la riga `PigroCRM v1 - first deploy from CI, with green gates`:

```markdown
| `PigroCRM` | `PigroCRM v2 - a space is born ready, and you enter with your email` | Ivan | In Progress, opened 2026-09-12 |
```

- [ ] **Step 3: Commit**

```bash
git add docs/design/DECISIONS.md docs/tracker.md \
        projects/pigrocrm/docs/superpowers/specs/2026-09-12-onboarding-product-led-design.md \
        projects/pigrocrm/docs/superpowers/plans/2026-09-12-orb-171-uno-spazio-nasce-pronto.md
git commit -m "docs(pigrocrm): the product-led onboarding spec, the ORB-171 plan, the decision and the v2 project row" -m "The design record for the PigroCRM v2 project, decided with Ivan on 2026-09-12, and the plan this branch executes.

ORB-171."
```

---

### Task 7: verifica completa e PR

- [ ] **Step 1: La suite Python di core e api, in serie**

Run (in background, 4-5 minuti; mai in parallelo con un'altra pytest DB-backed):

```bash
uv run pytest -q -n 0 -m "not slow and not planner" projects/pigrocrm/packages/core/tests projects/pigrocrm/apps/api/tests 2>&1 | tail -15
```

Expected: tutto verde. Un singolo errore `Port mapping ... 8080` all'avvio è un flake di ryuk: rilanciare una volta.

- [ ] **Step 2: Lint, formato, tipi, e i test MCP**

```bash
uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && uv run mypy && \
uv run pytest -q -n 0 projects/pigrocrm/apps/mcp/tests 2>&1 | tail -3
```

Expected: puliti e verdi.

- [ ] **Step 3: Rebase su `origin/main` e push**

```bash
git fetch origin && git rebase origin/main
git push -u origin ivansala/orb-171-a-new-space-has-no-pipeline-stages-no-document-templates-and
```

Se `DECISIONS.md` va in conflitto: il file di `main` più questa riga in coda.

- [ ] **Step 4: Aprire la PR con il template del repository**

Titolo: `feat(core): a space is born with its default stages, templates and categories`

Body nelle quattro sezioni di `.github/PULL_REQUEST_TEMPLATE.md`: cosa cambia (provision + ensure_defaults + CLI nel CMD + l'offerta predefinita), come l'ho verificato (i comandi degli step 1 e 2 con il conteggio dei test), cosa guardare due volte (il `CMD` che ora ha tre passi e non deve mai fallire l'avvio; la scelta «solo se la tabella è vuota»), Screenshots: «Nessun cambiamento visibile: la Home di uno spazio nuovo mostra gli stati nella pipeline dove prima era vuota, ma la pagina è la stessa». Nessuna riga «Generated with» nel body (regola del repo).

Poi, su Linear: `save_issue` ORB-171 → `In Review`, e un commento `PR: <url> (branch ...)` con una frase su cosa contiene.

- [ ] **Step 5: Merge**

Aspettare i check (`gh pr checks --watch`; se «no checks reported» dopo un minuto, leggere `gh pr view --json mergeable`: quasi sempre `DECISIONS.md` in conflitto), poi `gh pr merge --squash --delete-branch`? **No**: il repo mergia come nelle PR precedenti (merge commit, vedere `git log --first-parent origin/main`); usare `gh pr merge --merge --delete-branch`. Poi `git worktree prune`. Su Linear: `Done` con il commento di chiusura (`**Merged:** <url> (merge commit ...)`, `Evidence:` con i job verdi e i conteggi), e dire a Ivan che è su `main`/preview e arriva in produzione al prossimo tag `pigrocrm-v*`, quando lo chiede lui.
