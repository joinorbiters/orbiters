# Slice 9A — Import dello storico fatture: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrare nel CRM le fatture già emesse con the previous system come fatture `emessa` con numero e data originali, senza consumare numeri né produrre XML, portando il contatore dell'anno al numero più alto importato e dichiarando esplicitamente i buchi del registro.

**Architecture:** Un nuovo metodo `InvoiceService.import_issued` che riusa il lock del contatore, lo snapshot del regime e le righe dello slice 3 ma prende `(anno, numero)` dal chiamante; una colonna `invoices.importata_da` che spegne export XML e rigenerazione PDF su quelle righe; una tabella `invoice_register_gaps` per i numeri mancanti dichiarati. Esposto via REST (`admin`) e via due tool MCP in `privileged.py` (solo con `mcp_full_access`), coerentemente con la lista dei divieti agli agenti.

**Tech Stack:** Python 3.13, SQLAlchemy 2 + Alembic, Pydantic 2, FastAPI, `mcp` 2.0 (`MCPServer`), pytest + testcontainers Postgres, React/TypeScript (Vite) per il badge.

**Spec:** `docs/superpowers/specs/2026-09-04-slice-9-import-storico-e-google-drive-design.md` §3 (e §2.3 per il prerequisito).

## Global Constraints

- Tutti i test DB-backed vanno lanciati con `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest ...` dalla radice del worktree `.claude/worktrees/slice-1b-frontend` (Ryuk fallisce su questa macchina).
- Nessuna query Gmail o Drive in questo piano: la sorgente PDF è un `documents` già caricato (`pdf_sorgente = {"document_id": ...}`); la variante `drive_file_id` arriva con 9C.
- Ogni metodo di servizio = una transazione, `self.session.commit()` alla fine, `rollback()` su `IntegrityError` (pattern di `issue`).
- Testi rivolti all'utente in italiano, senza apostrofi tipografici nei messaggi d'errore (`e'`, non `è`, come il resto di `invoices/service.py`).
- Importi `Decimal`, mai `float`; verifiche al centesimo con `round_money`.
- I nomi dei tool MCP di scrittura fiscale stanno **solo** in `apps/mcp/src/pigrocrm_mcp/tools/privileged.py` e in `AGENT_FORBIDDEN_ACTIONS`, e i due elenchi (`FORBIDDEN` in `test_mcp_invoice_ban.py`, `_VIETATE` in `test_mcp_surface_coverage.py`) devono restare uguali fra loro: i test lo verificano.
- Formattazione: `uv run ruff format` + `uv run ruff check` + `uv run mypy` sui file toccati prima di ogni commit.
- Commit piccoli, uno per task, messaggio `feat(invoices): ...` / `test(...)`, con la riga `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File Structure

| File | Responsabilità |
|---|---|
| `packages/core/migrations/versions/0025_invoice_import.py` | Colonna `invoices.importata_da`, tabella `invoice_register_gaps` |
| `packages/core/src/pigrocrm/core/invoices/models.py` | `Invoice.importata_da`; nuovo modello `InvoiceRegisterGap` |
| `packages/core/src/pigrocrm/core/invoices/schemas.py` | `InvoiceLineImport`, `InvoiceImport`, `RegisterGapIn`, `RegisterGapRead`; `InvoiceRead.importata_da` |
| `packages/core/src/pigrocrm/core/invoices/repository.py` | `neighbour_dates`, `numbers_present`, `declared_gaps`, `add_gap`, `first_native_number` |
| `packages/core/src/pigrocrm/core/invoices/service.py` | `import_issued`, `declare_gaps`, guardia `importata_da` in `export_xml` e `produce_artifacts` |
| `packages/core/tests/test_invoice_import.py` | Tutti i test di servizio e repository dell'import |
| `apps/api/src/pigrocrm_api/routers/invoices.py` | `POST /api/invoices/import`, `POST /api/invoices/register/{anno}/gaps`, `GET /api/invoices/register/{anno}/gaps` |
| `apps/api/tests/test_invoices_import_api.py` | Test REST |
| `apps/mcp/src/pigrocrm_mcp/tools/privileged.py` | `import_issued_invoice`, `declare_invoice_register_gaps` |
| `packages/core/src/pigrocrm/core/actor.py` | Due voci in `AGENT_FORBIDDEN_ACTIONS` |
| `apps/mcp/tests/test_mcp_invoice_ban.py`, `apps/mcp/tests/test_mcp_surface_coverage.py` | Liste a diciannove |
| `apps/mcp/tests/test_invoice_import_tools.py` | Test dei due tool |
| `apps/web/src/features/invoices/InvoiceStateBadge.tsx`, `InvoiceActions.tsx`, `src/lib/api-types.ts` | Badge «importata da the previous system», niente XML/rigenera |
| `docs/superpowers/data/2026-09-04-the previous system-fatture-2026.json` | Le 14 fatture da importare, nel formato di `InvoiceImport` |

---

### Task 1: Migrazione e modelli

**Files:**
- Create: `packages/core/migrations/versions/0025_invoice_import.py`
- Modify: `packages/core/src/pigrocrm/core/invoices/models.py` (classe `Invoice`, dopo `custom_fields`; nuova classe in coda al file)
- Test: `packages/core/tests/test_invoice_import.py` (nuovo)

**Interfaces:**
- Produces: `Invoice.importata_da: str | None`; `InvoiceRegisterGap(anno: int, numero: int, motivo: str, dichiarato_da: UUID | None, dichiarato_il: datetime)` con `UniqueConstraint("anno", "numero", name="uq_invoice_register_gaps_anno_numero")`.

- [ ] **Step 1: Scrivere il test che fallisce**

```python
"""Import dello storico fatture (slice 9 §3)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.invoices.models import Invoice, InvoiceRegisterGap

ADMIN = Actor(id=None, type="system", role="admin")


def test_an_invoice_records_where_it_was_imported_from(db_session: Session) -> None:
    from conftest import _fiscal_customer_id

    row = Invoice(
        customer_id=_fiscal_customer_id(db_session),
        tipo="fattura",
        stato="emessa",
        anno=2026,
        numero=7,
        data_emissione=date(2026, 5, 5),
        importata_da="the previous system",
        imponibile=Decimal("2700.00"),
        imposta=Decimal("0.00"),
        bollo=Decimal("2.00"),
        totale=Decimal("3422.00"),
    )
    db_session.add(row)
    db_session.flush()
    assert db_session.get(Invoice, row.id).importata_da == "the previous system"


def test_a_register_gap_is_unique_per_year_and_number(db_session: Session) -> None:
    db_session.add(InvoiceRegisterGap(anno=2026, numero=4, motivo="annullata in the previous system"))
    db_session.flush()
    db_session.add(InvoiceRegisterGap(anno=2026, numero=4, motivo="di nuovo"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
```

Nota: `conftest` è importabile come modulo top-level nei test core (`from conftest import _fiscal_customer_id` è già il pattern in `test_invoice_service.py`; se non lo è, copiare la funzione `_fiscal_customer_id` di `conftest.py:274-290` in testa al file di test).

- [ ] **Step 2: Eseguire il test e vederlo fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py -q`
Expected: FAIL — `ImportError: cannot import name 'InvoiceRegisterGap'`

- [ ] **Step 3: Modello**

In `models.py`, dentro `class Invoice`, dopo `custom_fields`:

```python
    # `'the previous system'` for a row registered by slice 9's import: issued elsewhere, numbered
    # elsewhere, and therefore without an XML or a PDF this CRM produced. `NULL` is the
    # ordinary case. A string rather than a boolean because the *source* is the fact
    # worth keeping: a second migration one day would not be "imported = true" twice.
    importata_da: Mapped[str | None] = mapped_column(String(20), default=None)
```

In coda al file:

```python
class InvoiceRegisterGap(Base, PrimaryKeyMixin):
    """A number the register does not carry, on purpose, with the reason why.

    The register has to be gap-free (spec 3), and an import from another system meets
    numbers that were consumed there and never became an invoice -- annulled before
    transmission, a test run, a numbering slip. Refusing the import would lock the
    history out; inventing rows would forge documents. So the gap is *declared*: one
    row, one number, one reason, one author. `test_invoice_import.py` proves the import
    refuses an undeclared gap.
    """

    __tablename__ = "invoice_register_gaps"

    anno: Mapped[int] = mapped_column(Integer, nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    motivo: Mapped[str] = mapped_column(String(500), nullable=False)
    dichiarato_da: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)
    dichiarato_il: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("anno", "numero", name="uq_invoice_register_gaps_anno_numero"),
        CheckConstraint("numero >= 1", name="ck_invoice_register_gaps_numero_positive"),
    )
```

Aggiungere agli import di `models.py` ciò che manca fra `DateTime`, `UniqueConstraint`, `CheckConstraint`, `ForeignKey`, `datetime`, `UTC`. Registrare il modello in `pigrocrm/core/models_registry.py` se quel modulo elenca le classi esplicitamente (verificare con `grep -n Invoice packages/core/src/pigrocrm/core/models_registry.py`).

- [ ] **Step 4: Migrazione**

`packages/core/migrations/versions/0025_invoice_import.py`:

```python
"""invoices.importata_da and invoice_register_gaps

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-04

Slice 9 §3. One column and one table, in one revision because neither means anything
without the other: an imported invoice exists to fill a register whose gaps are
declared in the second.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("importata_da", sa.String(length=20), nullable=True))
    op.create_table(
        "invoice_register_gaps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("anno", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.String(length=500), nullable=False),
        sa.Column("dichiarato_da", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("dichiarato_il", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("anno", "numero", name="uq_invoice_register_gaps_anno_numero"),
        sa.CheckConstraint("numero >= 1", name="ck_invoice_register_gaps_numero_positive"),
    )


def downgrade() -> None:
    op.drop_table("invoice_register_gaps")
    op.drop_column("invoices", "importata_da")
```

Verificare il tipo della colonna `id` usato dalle altre tabelle in `0023_automations_and_dates.py` (`sa.Uuid()` vs `postgresql.UUID(as_uuid=True)`) e allinearsi.

- [ ] **Step 5: Eseguire i test e la migrazione**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py packages/core/tests/test_invoice_models.py -q`
Expected: PASS. Poi `uv run --directory . alembic -c packages/core/alembic.ini upgrade head` sul DB locale (leggere il path dell'`alembic.ini` reale con `ls packages/core`), e `alembic check`/`heads` deve dare `0025`.

- [ ] **Step 6: Commit**

```bash
git add packages/core/migrations/versions/0025_invoice_import.py packages/core/src/pigrocrm/core/invoices/models.py packages/core/tests/test_invoice_import.py
git commit -m "feat(invoices): importata_da column and declared register gaps (slice 9 §3.1-3.2)"
```

---

### Task 2: Schemi di ingresso e lettura

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/schemas.py`
- Test: `packages/core/tests/test_invoice_schemas.py` (append)

**Interfaces:**
- Produces:
  - `InvoiceLineImport(descrizione: SafeStr, quantita: Decimal = 1, unita_misura: SafeStr | None, prezzo_unitario: Decimal, prezzo_totale: Decimal, aliquota_iva: Decimal, natura: SafeStr | None = None, riferimento_normativo: SafeStr | None = None)` — `extra="forbid"`.
  - `PdfSorgente(document_id: UUID)`.
  - `InvoiceImport(anno: int, numero: int, data_emissione: date, data_scadenza: date | None, customer_id: UUID, deal_id: UUID | None, causale: SafeStr | None, righe: list[InvoiceLineImport] (min 1, max MAX_LINES), imponibile: Decimal, imposta: Decimal, bollo: Decimal, totale: Decimal, stato_pagamento: StatoPagamento = "da_incassare", data_incasso: date | None, trasmessa_esternamente_il: date | None, pdf_sorgente: PdfSorgente | None, note_interne: SafeStr | None, importata_da: Literal["the previous system"] = "the previous system")` — `extra="forbid"`, `anno` fra 2000 e 2100, `numero >= 1`.
  - `RegisterGapIn(numero: int >= 1, motivo: SafeStr max 500)`, `RegisterGapsDeclare(buchi: list[RegisterGapIn], min 1)`, `RegisterGapRead(anno, numero, motivo, dichiarato_da, dichiarato_il)`.
  - `InvoiceRead.importata_da: str | None`.

- [ ] **Step 1: Test che fallisce**

Append a `packages/core/tests/test_invoice_schemas.py`:

```python
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pigrocrm.core.invoices.schemas import InvoiceImport, InvoiceLineImport, RegisterGapsDeclare


def _line(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "descrizione": "900142/0426/Consulenza AI CTO progetto Aurora",
        "quantita": Decimal("9"),
        "prezzo_unitario": Decimal("300"),
        "prezzo_totale": Decimal("2700.00"),
        "aliquota_iva": Decimal("0"),
        "natura": "N2.2",
    }
    base.update(overrides)
    return base


def _import(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "anno": 2026,
        "numero": 7,
        "data_emissione": date(2026, 5, 5),
        "customer_id": uuid4(),
        "righe": [_line()],
        "imponibile": Decimal("2700.00"),
        "imposta": Decimal("0.00"),
        "bollo": Decimal("2.00"),
        "totale": Decimal("3422.00"),
    }
    base.update(overrides)
    return base


def test_an_import_defaults_to_esterno_and_da_incassare() -> None:
    data = InvoiceImport(**_import())
    assert data.importata_da == "the previous system"
    assert data.stato_pagamento == "da_incassare"
    assert data.pdf_sorgente is None


def test_an_import_refuses_unknown_fields_and_a_zero_number() -> None:
    with pytest.raises(ValidationError):
        InvoiceImport(**_import(numero=0))
    with pytest.raises(ValidationError):
        InvoiceImport(**_import(xml_hash_sha256="abc"))
    with pytest.raises(ValidationError):
        InvoiceImport(**_import(righe=[]))


def test_an_imported_line_carries_its_own_natura_and_total() -> None:
    line = InvoiceLineImport(**_line())
    assert line.natura == "N2.2"
    assert line.prezzo_totale == Decimal("2700.00")


def test_gaps_need_a_reason_each() -> None:
    with pytest.raises(ValidationError):
        RegisterGapsDeclare(buchi=[{"numero": 4}])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        RegisterGapsDeclare(buchi=[])
```

- [ ] **Step 2: Vederlo fallire**

Run: `uv run --directory . pytest packages/core/tests/test_invoice_schemas.py -q -k "import or gaps"`
Expected: FAIL — `ImportError` su `InvoiceImport`.

- [ ] **Step 3: Implementare gli schemi**

In `schemas.py`, dopo `PaymentState`:

```python
class InvoiceLineImport(BaseModel):
    """One line of an invoice issued elsewhere, exactly as that document printed it.

    Unlike `InvoiceLineIn`, `natura`, `riferimento_normativo` and `prezzo_totale` are
    accepted: the regime strategy did not compute this document and must not rewrite it.
    The service still checks that the declared totals add up (§3.3).
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
    prezzo_totale: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=2)
    aliquota_iva: Decimal = Field(max_digits=5, decimal_places=2)
    natura: SafeStr | None = Field(default=None, max_length=NATURA_MAX_LENGTH)
    riferimento_normativo: SafeStr | None = None


class PdfSorgente(BaseModel):
    """Where the original PDF already is. Slice 9A knows one place -- a `documents` row
    with an uploaded version; 9C adds `drive_file_id`."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID


class InvoiceImport(BaseModel):
    """A fattura issued by the previous system, declared field by field (spec 9 §3.3).

    `anno`/`numero` come from the caller because they are facts about a document that
    exists; the counter follows them (§3.2 rule 3). Totals are declared **and** verified,
    never recomputed: the document commands, the CRM checks the sums."""

    model_config = ConfigDict(extra="forbid")

    anno: int = Field(ge=2000, le=2100)
    numero: int = Field(ge=1)
    data_emissione: date
    data_scadenza: date | None = None
    customer_id: UUID
    deal_id: UUID | None = None
    causale: SafeStr | None = Field(default=None, max_length=CAUSALE_MAX_LENGTH)
    righe: list[InvoiceLineImport] = Field(min_length=1, max_length=MAX_LINES)
    imponibile: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=2)
    imposta: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=2)
    bollo: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=2)
    totale: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=2)
    stato_pagamento: StatoPagamento = "da_incassare"
    data_incasso: date | None = None
    trasmessa_esternamente_il: date | None = None
    pdf_sorgente: PdfSorgente | None = None
    note_interne: SafeStr | None = None
    importata_da: Literal["the previous system"] = "the previous system"


class RegisterGapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero: int = Field(ge=1)
    motivo: SafeStr = Field(max_length=MOTIVO_ANNULLAMENTO_MAX_LENGTH)


class RegisterGapsDeclare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buchi: list[RegisterGapIn] = Field(min_length=1, max_length=200)


class RegisterGapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    anno: int
    numero: int
    motivo: str
    dichiarato_da: UUID | None
    dichiarato_il: datetime
```

Se `MONEY_MAX_DIGITS` non esiste, usare la costante che `InvoiceLineIn`/`totals.py` già usano per `Numeric(12,2)` (cercare `max_digits=12` nel file) e definirla una volta. Aggiungere `importata_da: str | None` a `InvoiceRead` dopo `xml_document_id`. Importare `datetime` e `Literal` se mancano.

- [ ] **Step 4: Verde**

Run: `uv run --directory . pytest packages/core/tests/test_invoice_schemas.py -q`
Expected: PASS (tutti, non solo i nuovi).

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/schemas.py packages/core/tests/test_invoice_schemas.py
git commit -m "feat(invoices): InvoiceImport, RegisterGaps schemas and importata_da on InvoiceRead"
```

---

### Task 3: Repository — vicini, numeri presenti, buchi

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/repository.py` (dopo `last_issued_date`)
- Test: `packages/core/tests/test_invoice_import.py` (append)

**Interfaces:**
- Produces:
  - `neighbour_dates(anno: int, numero: int) -> tuple[date | None, date | None]` — `data_emissione` del numero più alto **inferiore** a `numero` e del più basso **superiore**, fra fatture con `numero IS NOT NULL` (emesse e annullate).
  - `numbers_present(anno: int) -> set[int]`.
  - `declared_gaps(anno: int) -> set[int]`.
  - `add_gap(gap: InvoiceRegisterGap) -> InvoiceRegisterGap`.
  - `gaps(anno: int) -> list[InvoiceRegisterGap]` ordinati per numero.
  - `first_native_number(anno: int) -> int | None` — il minimo `numero` con `importata_da IS NULL`.

- [ ] **Step 1: Test che fallisce**

```python
def _issued(session: Session, *, anno: int, numero: int, giorno: date, importata: bool = True) -> Invoice:
    from conftest import _fiscal_customer_id

    row = Invoice(
        customer_id=_fiscal_customer_id(session),
        tipo="fattura",
        stato="emessa",
        anno=anno,
        numero=numero,
        data_emissione=giorno,
        importata_da="the previous system" if importata else None,
        imponibile=Decimal("100.00"),
        imposta=Decimal("0.00"),
        bollo=Decimal("0.00"),
        totale=Decimal("100.00"),
    )
    session.add(row)
    session.flush()
    return row


def test_neighbour_dates_look_both_ways(db_session: Session) -> None:
    from pigrocrm.core.invoices.repository import InvoiceRepository

    _issued(db_session, anno=2026, numero=7, giorno=date(2026, 5, 5))
    _issued(db_session, anno=2026, numero=11, giorno=date(2026, 7, 13))
    repo = InvoiceRepository(db_session)
    assert repo.neighbour_dates(2026, 9) == (date(2026, 5, 5), date(2026, 7, 13))
    assert repo.neighbour_dates(2026, 2) == (None, date(2026, 5, 5))
    assert repo.neighbour_dates(2026, 12) == (date(2026, 7, 13), None)
    assert repo.numbers_present(2026) == {7, 11}
    assert repo.first_native_number(2026) is None
    _issued(db_session, anno=2026, numero=18, giorno=date(2026, 9, 10), importata=False)
    assert repo.first_native_number(2026) == 18


def test_gaps_round_trip(db_session: Session) -> None:
    from pigrocrm.core.invoices.repository import InvoiceRepository

    repo = InvoiceRepository(db_session)
    repo.add_gap(InvoiceRegisterGap(anno=2026, numero=6, motivo="test"))
    repo.add_gap(InvoiceRegisterGap(anno=2026, numero=1, motivo="test"))
    assert repo.declared_gaps(2026) == {1, 6}
    assert [g.numero for g in repo.gaps(2026)] == [1, 6]
    assert repo.declared_gaps(2025) == set()
```

- [ ] **Step 2: Vederlo fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py -q -k "neighbour or gaps_round"`
Expected: FAIL — `AttributeError: 'InvoiceRepository' object has no attribute 'neighbour_dates'`

- [ ] **Step 3: Implementare**

```python
    def neighbour_dates(self, anno: int, numero: int) -> tuple[date | None, date | None]:
        """The dates on either side of `numero` in the register of `anno`.

        `last_issued_date` answers "what came last"; an import inserts *between*
        existing numbers, so monotonicity has to be checked against the nearest lower
        and the nearest higher number, whatever their states -- an annulled row keeps
        its place in the order exactly as it does for `last_issued_date`.
        """
        before = (
            select(Invoice.data_emissione)
            .where(Invoice.anno == anno, Invoice.numero.is_not(None), Invoice.numero < numero)
            .order_by(Invoice.numero.desc())
            .limit(1)
        )
        after = (
            select(Invoice.data_emissione)
            .where(Invoice.anno == anno, Invoice.numero.is_not(None), Invoice.numero > numero)
            .order_by(Invoice.numero.asc())
            .limit(1)
        )
        return (
            self.session.execute(before).scalars().first(),
            self.session.execute(after).scalars().first(),
        )

    def numbers_present(self, anno: int) -> set[int]:
        stmt = select(Invoice.numero).where(Invoice.anno == anno, Invoice.numero.is_not(None))
        return set(self.session.execute(stmt).scalars().all())

    def first_native_number(self, anno: int) -> int | None:
        """The lowest number this CRM itself issued in `anno` (§3.2 rule 6)."""
        stmt = select(func.min(Invoice.numero)).where(
            Invoice.anno == anno, Invoice.numero.is_not(None), Invoice.importata_da.is_(None)
        )
        return self.session.execute(stmt).scalar_one()

    def declared_gaps(self, anno: int) -> set[int]:
        stmt = select(InvoiceRegisterGap.numero).where(InvoiceRegisterGap.anno == anno)
        return set(self.session.execute(stmt).scalars().all())

    def gaps(self, anno: int) -> list[InvoiceRegisterGap]:
        stmt = (
            select(InvoiceRegisterGap)
            .where(InvoiceRegisterGap.anno == anno)
            .order_by(InvoiceRegisterGap.numero)
        )
        return list(self.session.execute(stmt).scalars().all())

    def add_gap(self, gap: InvoiceRegisterGap) -> InvoiceRegisterGap:
        self.session.add(gap)
        self.session.flush()
        return gap
```

Importare `func` da `sqlalchemy` e `InvoiceRegisterGap` dai modelli.

- [ ] **Step 4: Verde**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/repository.py packages/core/tests/test_invoice_import.py
git commit -m "feat(invoices): repository queries for import — neighbours, present numbers, declared gaps"
```

---

### Task 4: `InvoiceService.import_issued` — percorso felice e regole di registro

> Ruling (review Task 4): `riferimento` non fa parte di `InvoiceImport` — su `invoices` è il riferimento di una proforma per vincolo `ck_invoices_riferimento_only_on_proforma`; la descrizione the previous system va in `causale`. Il servizio verifica inoltre `anno == data_emissione.year` e rifiuta `data_incasso` senza `stato_pagamento = incassato`.

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/service.py` (nuovo metodo dopo `issue`; costante `IMPORT_ACTION`)
- Test: `packages/core/tests/test_invoice_import.py` (append)

**Interfaces:**
- Consumes: Task 2 (`InvoiceImport`), Task 3 (repository), `self.repo.lock_counter(anno)`, `self._regime()`, `self._build_snapshot(invoice, profile, actor)`, `self._check_owner(customer_id, deal_id)`, `self.repo.add_line(InvoiceLine(...))`, `self.activities.record(...)`, `round_money`.
- Produces: `import_issued(data: InvoiceImport, actor: Actor) -> InvoiceRead`; azione `"import_issued_invoice"` passata a `actor.require_admin`.

- [ ] **Step 1: Test che fallisce**

```python
def _svc(session: Session, tmp_path):  # noqa: ANN001
    from conftest import _invoice_service
    from pigrocrm.core.storage.local import LocalFileStorage

    return _invoice_service(session, LocalFileStorage(tmp_path))


def _payload(customer_id: UUID, *, numero: int, giorno: date, **overrides: object) -> "InvoiceImport":
    from pigrocrm.core.invoices.schemas import InvoiceImport

    base: dict[str, object] = {
        "anno": giorno.year,
        "numero": numero,
        "data_emissione": giorno,
        "data_scadenza": date(giorno.year, giorno.month, 28),
        "customer_id": customer_id,
        "causale": "900142/0426/Consulenza AI CTO progetto Aurora",
        "righe": [
            {
                "descrizione": "900142/0426/Consulenza AI CTO progetto Aurora",
                "quantita": Decimal("9"),
                "prezzo_unitario": Decimal("300"),
                "prezzo_totale": Decimal("2700.00"),
                "aliquota_iva": Decimal("0"),
                "natura": "N2.2",
            }
        ],
        "imponibile": Decimal("2700.00"),
        "imposta": Decimal("0.00"),
        "bollo": Decimal("2.00"),
        "totale": Decimal("3422.00"),
        "stato_pagamento": "incassato",
        "data_incasso": date(giorno.year, giorno.month, 20),
        "trasmessa_esternamente_il": giorno,
    }
    base.update(overrides)
    return InvoiceImport(**base)


def test_an_imported_invoice_is_issued_numbered_and_moves_the_counter(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.invoices.models import InvoiceCounter

    service = _svc(db_session, tmp_path)
    customer_id = _fiscal_customer_id(db_session)
    read = service.import_issued(_payload(customer_id, numero=7, giorno=date(2026, 5, 5)), ADMIN)

    assert (read.anno, read.numero, read.stato, read.tipo) == (2026, 7, "emessa", "fattura")
    assert read.importata_da == "the previous system"
    assert read.totale == Decimal("3422.00") and read.bollo == Decimal("2.00")
    assert read.stato_pagamento == "incassato" and read.data_incasso == date(2026, 5, 20)
    assert read.xml_hash_sha256 is None and read.pdf_document_id is None
    assert db_session.get(InvoiceCounter, 2026).ultimo_numero == 7
    lines = service.repo.lines(read.id)
    assert [(l.numero_linea, l.prezzo_totale, l.natura) for l in lines] == [(1, Decimal("2700.00"), "N2.2")]
    row = db_session.get(Invoice, read.id)
    assert row.snapshot is not None and row.snapshot["versione"] == 1


def test_the_counter_never_moves_backwards(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.invoices.models import InvoiceCounter

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=11, giorno=date(2026, 7, 13)), ADMIN)
    service.import_issued(_payload(cid, numero=9, giorno=date(2026, 6, 5)), ADMIN)
    assert db_session.get(InvoiceCounter, 2026).ultimo_numero == 11


def test_a_duplicate_number_is_a_conflict(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.errors import Conflict

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)
    with pytest.raises(Conflict):
        service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)


def test_the_register_stays_chronological_against_both_neighbours(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.errors import ValidationFailed

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)
    service.import_issued(_payload(cid, numero=11, giorno=date(2026, 7, 13)), ADMIN)
    with pytest.raises(ValidationFailed) as before:
        service.import_issued(_payload(cid, numero=9, giorno=date(2026, 5, 4)), ADMIN)
    assert before.value.details["field"] == "data_emissione"
    with pytest.raises(ValidationFailed):
        service.import_issued(_payload(cid, numero=9, giorno=date(2026, 7, 14)), ADMIN)
    service.import_issued(_payload(cid, numero=9, giorno=date(2026, 6, 5)), ADMIN)


def test_declared_totals_must_add_up_to_the_cent(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.errors import ValidationFailed

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    with pytest.raises(ValidationFailed) as caught:
        service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5), totale=Decimal("3421.99")), ADMIN)
    assert "3422.00" in caught.value.message and "3421.99" in caught.value.message
    with pytest.raises(ValidationFailed):
        service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5), imponibile=Decimal("3400.00"), totale=Decimal("3402.00")), ADMIN)


def test_a_future_date_and_a_collaborator_are_refused(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from datetime import timedelta

    from conftest import _fiscal_customer_id
    from pigrocrm.core.clock import oggi_in_italia
    from pigrocrm.core.errors import PermissionDenied, ValidationFailed

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    domani = oggi_in_italia() + timedelta(days=1)
    with pytest.raises(ValidationFailed):
        service.import_issued(_payload(cid, numero=7, giorno=domani), ADMIN)
    with pytest.raises(PermissionDenied):
        service.import_issued(
            _payload(cid, numero=7, giorno=date(2026, 5, 5)),
            Actor(id=None, type="user", role="collaboratore"),
        )


def test_the_import_writes_one_activity(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.activities.models import Activity

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    read = service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)
    kinds = db_session.execute(
        select(Activity.kind).where(Activity.entity_type == "invoice", Activity.entity_id == read.id)
    ).scalars().all()
    assert kinds == ["imported"]
```

Il campo dell'attributo `message`/`details` di `ValidationFailed` va verificato in `packages/core/src/pigrocrm/core/errors.py` (i test esistenti usano `caught.value.details["field"]`); adattare il nome se il messaggio sta in `str(caught.value)`. Il nome del ruolo non-admin (`collaboratore`) va letto da `WRITE_ROLES`/`Role` in `actor.py`.

- [ ] **Step 2: Vederlo fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py -q`
Expected: FAIL — `AttributeError: 'InvoiceService' object has no attribute 'import_issued'`

- [ ] **Step 3: Implementare**

In `service.py`, subito dopo `issue` (e prima di `_backfill`-style internals), con `IMPORT_ACTION = "import_issued_invoice"` accanto a `ENTITY`:

```python
    def import_issued(self, data: InvoiceImport, actor: Actor) -> InvoiceRead:
        """Register a fattura that another system issued (slice 9 §3).

        Same lock, same snapshot, same lines as `issue`; the two differences are the
        whole feature. The number is *declared*, so the counter follows it instead of
        producing it (§3.2 rule 3). And the totals are *declared*, so they are checked
        against the lines to the cent instead of recomputed (§3.3): the document the
        customer holds is the fact, and this method refuses to record a different one.

        Order: pure checks on the input, then `lock_counter(anno)` -- the first and only
        row lock -- then every check that reads the register (duplicates, neighbours,
        gaps, native numbers), then the write. Nothing is consumed on failure: the
        counter is only ever raised to a number that is being written in the same
        transaction.
        """
        actor.require_admin(IMPORT_ACTION)
        self._check_owner(data.customer_id, data.deal_id)
        self._check_import_date(data.data_emissione)
        self._check_declared_totals(data)
        if data.stato_pagamento == "incassato" and data.data_incasso is None:
            raise ValidationFailed(
                ENTITY, "data_incasso", "un incasso senza data non e' un incasso",
                expected="la data in cui il pagamento e' arrivato",
            )
        counter = self.repo.lock_counter(data.anno)
        if data.numero in self.repo.numbers_present(data.anno):
            raise Conflict(
                ENTITY,
                "il registro porta gia' questo numero",
                anno=data.anno,
                numero=data.numero,
            )
        if data.numero in self.repo.declared_gaps(data.anno):
            raise Conflict(
                ENTITY,
                "questo numero e' dichiarato come buco del registro: togli la dichiarazione "
                "prima di importarlo",
                anno=data.anno,
                numero=data.numero,
            )
        first_native = self.repo.first_native_number(data.anno)
        if first_native is not None and data.numero > first_native:
            raise Conflict(
                ENTITY,
                "PigroCRM ha gia' emesso fatture in questo anno: si importa solo lo storico "
                "precedente alla prima emessa qui",
                anno=data.anno,
                numero=data.numero,
                prima_nativa=first_native,
            )
        before, after = self.repo.neighbour_dates(data.anno, data.numero)
        if before is not None and data.data_emissione < before:
            raise ValidationFailed(
                ENTITY, "data_emissione",
                "il registro deve restare cronologico: il numero precedente porta la data "
                f"{before.isoformat()}",
                expected=f"una data dal {before.isoformat()} in poi",
            )
        if after is not None and data.data_emissione > after:
            raise ValidationFailed(
                ENTITY, "data_emissione",
                "il registro deve restare cronologico: il numero successivo porta la data "
                f"{after.isoformat()}",
                expected=f"una data fino al {after.isoformat()}",
            )
        _, profile = self._regime()
        invoice = self.repo.add(
            Invoice(
                customer_id=data.customer_id,
                deal_id=data.deal_id,
                tipo="fattura",
                stato="emessa",
                anno=data.anno,
                numero=data.numero,
                data_emissione=data.data_emissione,
                data_scadenza=data.data_scadenza
                or data.data_emissione + timedelta(days=profile.giorni_scadenza),
                tipo_documento=TIPO_DOCUMENTO,
                divisa=DIVISA,
                causale=data.causale,
                imponibile=data.imponibile,
                imposta=data.imposta,
                bollo=data.bollo,
                totale=data.totale,
                stato_pagamento=data.stato_pagamento,
                data_incasso=data.data_incasso,
                trasmessa_esternamente_il=data.trasmessa_esternamente_il,
                note_interne=data.note_interne,
                importata_da=data.importata_da,
                custom_fields={},
            )
        )
        for index, riga in enumerate(data.righe, start=1):
            self.repo.add_line(
                InvoiceLine(
                    invoice_id=invoice.id,
                    numero_linea=index,
                    descrizione=riga.descrizione,
                    quantita=riga.quantita,
                    unita_misura=riga.unita_misura,
                    prezzo_unitario=riga.prezzo_unitario,
                    prezzo_totale=riga.prezzo_totale,
                    aliquota_iva=riga.aliquota_iva,
                    natura=riga.natura,
                    riferimento_normativo=riga.riferimento_normativo,
                )
            )
        snapshot = self._build_snapshot(invoice, profile, actor)
        invoice.snapshot = snapshot.model_dump(mode="json")
        invoice.snapshot_versione = SNAPSHOT_VERSIONE
        if data.pdf_sorgente is not None:
            invoice.pdf_document_id = self._adopt_original_pdf(invoice, data.pdf_sorgente.document_id)
        counter.ultimo_numero = max(counter.ultimo_numero, data.numero)
        self.activities.record(
            ENTITY, invoice.id, "imported", actor,
            {
                "anno": data.anno,
                "numero": data.numero,
                "totale": str(data.totale),
                "importata_da": data.importata_da,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise Conflict(
                ENTITY,
                "un altro processo ha scritto lo stesso numero: riprova e verifica il registro",
                anno=data.anno,
                numero=data.numero,
            ) from exc
        return self.get(invoice.id, actor)

    def _check_import_date(self, data_emissione: date) -> None:
        """Only "not in the future" (§3.2 rule 5). `_check_issue_date` also refuses a
        closed year, and a closed year is exactly what an import fills."""
        oggi = oggi_in_italia()
        if data_emissione > oggi:
            raise ValidationFailed(
                ENTITY, "data_emissione", "una fattura non si importa con data futura",
                expected=f"una data non successiva a {oggi.isoformat()}",
            )

    def _check_declared_totals(self, data: InvoiceImport) -> None:
        somma_righe = round_money(sum((r.prezzo_totale for r in data.righe), Decimal("0")))
        if somma_righe != round_money(data.imponibile):
            raise ValidationFailed(
                ENTITY, "imponibile",
                f"l'imponibile dichiarato ({data.imponibile}) non e' la somma delle righe "
                f"({somma_righe})",
                expected="imponibile uguale alla somma dei prezzi totali di riga",
            )
        atteso = round_money(data.imponibile + data.imposta + data.bollo)
        if atteso != round_money(data.totale):
            raise ValidationFailed(
                ENTITY, "totale",
                f"il totale dichiarato ({data.totale}) non e' imponibile + imposta + bollo "
                f"({atteso})",
                expected="totale uguale a imponibile + imposta + bollo",
            )
        if data.totale <= ZERO:
            raise ValidationFailed(
                ENTITY, "totale", "una TD01 a zero o negativa non e' una fattura",
                expected="un totale maggiore di zero",
            )
```

`_adopt_original_pdf` arriva nel Task 6; per far passare questo task, definirlo provvisoriamente così (verrà sostituito):

```python
    def _adopt_original_pdf(self, invoice: Invoice, document_id: UUID) -> UUID:
        raise NotImplementedError  # Task 6
```

Aggiungere `round_money` all'import da `totals`, `InvoiceImport` a quello da `schemas`, `InvoiceLine` è già importato.

- [ ] **Step 4: Verde**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py packages/core/tests/test_invoice_issue.py -q`
Expected: PASS. `uv run --directory . mypy packages/core/src/pigrocrm/core/invoices/service.py` pulito.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_import.py
git commit -m "feat(invoices): import_issued — declared number and totals, counter follows, register stays chronological (slice 9 §3.2-3.4)"
```

---

### Task 5: Buchi dichiarati e chiusura dell'import

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/service.py`
- Test: `packages/core/tests/test_invoice_import.py` (append)

**Interfaces:**
- Produces: `declare_gaps(anno: int, data: RegisterGapsDeclare, actor: Actor) -> list[RegisterGapRead]` (azione `"declare_invoice_register_gaps"`, `require_admin`); `register_gaps(anno: int, actor: Actor) -> list[RegisterGapRead]`; `undeclared_gaps(anno: int) -> list[int]` (i numeri fra il minimo importato e `ultimo_numero` che non sono né fatture né buchi dichiarati).
- Regola §3.2.4: l'import **non** viene bloccato numero per numero (i buchi possono essere dichiarati dopo); è `undeclared_gaps` a rendere visibile il registro incompleto, e la REST/MCP lo restituisce nella risposta dell'import (`buchi_non_dichiarati`) così l'operatore vede subito cosa manca. `issue` (emissione nativa) **rifiuta** con `Conflict` finché `undeclared_gaps(anno)` non è vuoto: il registro non riparte sopra un buco muto.

- [ ] **Step 1: Test che fallisce**

```python
def test_gaps_are_declared_with_a_reason_and_listed(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.invoices.schemas import RegisterGapsDeclare

    service = _svc(db_session, tmp_path)
    out = service.declare_gaps(
        2026,
        RegisterGapsDeclare(buchi=[{"numero": 1, "motivo": "annullata in the previous system"}, {"numero": 4, "motivo": "test di emissione"}]),  # type: ignore[list-item]
        ADMIN,
    )
    assert [(g.numero, g.motivo) for g in out] == [(1, "annullata in the previous system"), (4, "test di emissione")]
    assert [g.numero for g in service.register_gaps(2026, ADMIN)] == [1, 4]


def test_declaring_a_number_that_is_an_invoice_is_a_conflict(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.errors import Conflict
    from pigrocrm.core.invoices.schemas import RegisterGapsDeclare

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)
    with pytest.raises(Conflict):
        service.declare_gaps(2026, RegisterGapsDeclare(buchi=[{"numero": 7, "motivo": "x"}]), ADMIN)  # type: ignore[list-item]


def test_undeclared_gaps_are_named_and_block_native_issuing(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.errors import Conflict
    from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceIssue, InvoiceLineIn, RegisterGapsDeclare

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=2, giorno=date(2026, 2, 4)), ADMIN)
    service.import_issued(_payload(cid, numero=5, giorno=date(2026, 4, 7)), ADMIN)
    assert service.undeclared_gaps(2026) == [3, 4]

    draft = service.create(
        InvoiceCreate(customer_id=cid, righe=[InvoiceLineIn(descrizione="x", prezzo_unitario=Decimal("100"))]),
        ADMIN,
    )
    with pytest.raises(Conflict) as caught:
        service.issue(draft.id, InvoiceIssue(), ADMIN)
    assert "3" in str(caught.value) and "4" in str(caught.value)

    service.declare_gaps(2026, RegisterGapsDeclare(buchi=[{"numero": 3, "motivo": "a"}, {"numero": 4, "motivo": "b"}]), ADMIN)  # type: ignore[list-item]
    assert service.undeclared_gaps(2026) == []
    issued = service.issue(draft.id, InvoiceIssue(), ADMIN)
    assert issued.numero == 6
```

Il test dell'emissione nativa richiede che oggi sia nel 2026 e successivo al 7/04/2026 (vero fino a fine anno); se il test dovesse girare nel 2027, `_check_issue_date` rifiuterebbe: usare `oggi_in_italia().year` al posto di `2026` nei payload di questo test, con date `date(anno, 2, 4)` e `date(anno, 4, 7)`.

- [ ] **Step 2: Vederlo fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py -q -k gaps`
Expected: FAIL — `AttributeError: ... 'declare_gaps'`

- [ ] **Step 3: Implementare**

```python
    def declare_gaps(
        self, anno: int, data: RegisterGapsDeclare, actor: Actor
    ) -> list[RegisterGapRead]:
        """Name the numbers the register will never carry, and why (§3.2 rule 4).

        A declared gap is the honest alternative to two dishonest ones: inventing a row
        to fill it, or leaving it silent so that it looks like a lost invoice. It is
        refused for a number that *is* an invoice, and the import refuses a number that
        is a declared gap: the two sets never overlap.
        """
        actor.require_admin(GAPS_ACTION)
        self.repo.lock_counter(anno)
        present = self.repo.numbers_present(anno)
        already = self.repo.declared_gaps(anno)
        for buco in data.buchi:
            if buco.numero in present:
                raise Conflict(
                    ENTITY, "questo numero e' una fattura del registro, non un buco",
                    anno=anno, numero=buco.numero,
                )
            if buco.numero in already:
                raise Conflict(
                    ENTITY, "buco gia' dichiarato", anno=anno, numero=buco.numero,
                )
            self.repo.add_gap(
                InvoiceRegisterGap(
                    anno=anno, numero=buco.numero, motivo=buco.motivo, dichiarato_da=actor.id,
                )
            )
            self.activities.record(
                "invoice_register", uuid5(NAMESPACE_URL, f"pigrocrm:invoice_register:{anno}"),
                "gap_declared", actor, {"anno": anno, "numero": buco.numero, "motivo": buco.motivo},
            )
        self.session.commit()
        return self.register_gaps(anno, actor)

    def register_gaps(self, anno: int, actor: Actor) -> list[RegisterGapRead]:
        return [RegisterGapRead.model_validate(g) for g in self.repo.gaps(anno)]

    def undeclared_gaps(self, anno: int) -> list[int]:
        """Numbers between the lowest imported one and the counter that are neither an
        invoice nor a declared gap. Empty is the only state in which native issuing may
        resume (§3.2 rule 4)."""
        present = self.repo.numbers_present(anno)
        if not present:
            return []
        declared = self.repo.declared_gaps(anno)
        top = max(present)
        return [n for n in range(min(present), top) if n not in present and n not in declared]
```

`GAPS_ACTION = "declare_invoice_register_gaps"` accanto a `IMPORT_ACTION`. `uuid5`, `NAMESPACE_URL` da `uuid`: l'`activities.entity_id` è un UUID obbligatorio e il registro non ha una riga propria, quindi l'id è derivato deterministicamente dall'anno (verificare che `ActivityService.record` non richieda che `entity_type` sia in `EntityType`; se lo richiede, usare `ENTITY` e come `entity_id` l'id della fattura con il numero più alto dell'anno, documentando la scelta).

In `issue`, subito dopo `counter = self.repo.lock_counter(anno)`:

```python
        buchi = self.undeclared_gaps(anno)
        if buchi:
            raise Conflict(
                ENTITY,
                "il registro importato ha numeri mancanti non dichiarati: dichiarali come "
                "buchi (o importali) prima di emettere",
                anno=anno,
                numeri=buchi,
            )
```

- [ ] **Step 4: Verde**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py packages/core/tests/test_invoice_issue.py packages/core/tests/test_invoice_numbering_concurrency.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_import.py
git commit -m "feat(invoices): declared register gaps; native issuing waits for an accounted-for register"
```

---

### Task 6: PDF originale e artefatti spenti

**Files:**
- Modify: `packages/core/src/pigrocrm/core/invoices/service.py` (`_adopt_original_pdf`, guardie in `export_xml` e `produce_artifacts`)
- Test: `packages/core/tests/test_invoice_import.py` (append)

**Interfaces:**
- Consumes: `DocumentService.create(DocumentCreate, actor)`, `DocumentService.add_version(document_id, data, content_type, actor)`, `self.documents.repo.get(document_id)`, `self.documents.repo.version(document_id, numero)`.
- Produces: `_adopt_original_pdf(invoice, document_id) -> UUID` che valida: documento esiste, non cancellato, `tipo == "fattura"`, stesso `customer_id`, ha `versione_corrente` con `content_type == "application/pdf"`, e non è già il PDF di un'altra fattura.

- [ ] **Step 1: Test che fallisce**

```python
def _pdf_document(session: Session, tmp_path, customer_id: UUID) -> UUID:  # noqa: ANN001
    from pigrocrm.core.config import get_settings
    from pigrocrm.core.documents.schemas import DocumentCreate
    from pigrocrm.core.documents.service import DocumentService
    from pigrocrm.core.storage.local import LocalFileStorage

    docs = DocumentService(session, LocalFileStorage(tmp_path), get_settings())
    doc = docs.create(DocumentCreate(customer_id=customer_id, tipo="fattura", titolo="Fattura 7/2026 (the previous system)"), ADMIN)
    docs.add_version(doc.id, b"%PDF-1.4 fake", "application/pdf", ADMIN)
    return doc.id


def test_the_original_pdf_is_adopted_not_rendered(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.errors import Conflict
    from pigrocrm.core.invoices.schemas import PdfSorgente

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    doc_id = _pdf_document(db_session, tmp_path, cid)
    read = service.import_issued(
        _payload(cid, numero=7, giorno=date(2026, 5, 5), pdf_sorgente=PdfSorgente(document_id=doc_id)), ADMIN
    )
    assert read.pdf_document_id == doc_id
    data, content_type, _ = service.download(read.id, "pdf", ADMIN)
    assert (data, content_type) == (b"%PDF-1.4 fake", "application/pdf")
    with pytest.raises(Conflict):
        service.export_xml(read.id, ADMIN)
    with pytest.raises(Conflict):
        service.produce_artifacts(read.id, ADMIN)


def test_a_pdf_of_another_customer_or_without_bytes_is_refused(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from conftest import _fiscal_customer_id
    from pigrocrm.core.config import get_settings
    from pigrocrm.core.documents.schemas import DocumentCreate
    from pigrocrm.core.documents.service import DocumentService
    from pigrocrm.core.errors import ValidationFailed
    from pigrocrm.core.invoices.schemas import PdfSorgente
    from pigrocrm.core.storage.local import LocalFileStorage

    service = _svc(db_session, tmp_path)
    cid, other = _fiscal_customer_id(db_session), _fiscal_customer_id(db_session)
    foreign = _pdf_document(db_session, tmp_path, other)
    with pytest.raises(ValidationFailed):
        service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5), pdf_sorgente=PdfSorgente(document_id=foreign)), ADMIN)
    empty = DocumentService(db_session, LocalFileStorage(tmp_path), get_settings()).create(
        DocumentCreate(customer_id=cid, tipo="fattura", titolo="vuoto"), ADMIN
    )
    with pytest.raises(ValidationFailed):
        service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5), pdf_sorgente=PdfSorgente(document_id=empty.id)), ADMIN)
```

- [ ] **Step 2: Vederlo fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py -q -k pdf`
Expected: FAIL — `NotImplementedError` dal segnaposto del Task 4.

- [ ] **Step 3: Implementare**

Sostituire il segnaposto:

```python
    def _adopt_original_pdf(self, invoice: Invoice, document_id: UUID) -> UUID:
        """Link the PDF the customer actually received. Never rendered: a PDF produced
        today with today's layout would not be that document (§3.5)."""
        document = self.documents.repo.get(document_id)
        if document is None or document.deleted_at is not None:
            raise NotFound("document", document_id)
        if document.tipo != "fattura":
            raise ValidationFailed(
                ENTITY, "pdf_sorgente", "il documento non e' di tipo fattura",
                expected="un documento con tipo 'fattura'",
            )
        if document.customer_id != invoice.customer_id:
            raise ValidationFailed(
                ENTITY, "pdf_sorgente", "il documento appartiene a un altro cliente",
                expected=f"un documento del cliente {invoice.customer_id}",
            )
        if not document.versione_corrente:
            raise ValidationFailed(
                ENTITY, "pdf_sorgente", "il documento non ha ancora un file caricato",
                expected="un documento con almeno una versione PDF",
            )
        current = self.documents.repo.version(document.id, document.versione_corrente)
        if current is None or current.content_type != "application/pdf":
            raise ValidationFailed(
                ENTITY, "pdf_sorgente", "la versione corrente del documento non e' un PDF",
                expected="application/pdf",
            )
        taken = self.session.execute(
            select(Invoice.id).where(Invoice.pdf_document_id == document_id)
        ).scalars().first()
        if taken is not None:
            raise Conflict(
                ENTITY, "questo PDF e' gia' collegato a un'altra fattura", document_id=str(document_id),
            )
        return document.id
```

Verificare i nomi reali degli attributi di `Document`/`DocumentVersion` (`versione_corrente`, `content_type`, `deleted_at`) in `documents/models.py` e adattare.

In `export_xml`, dopo il controllo su `tipo != "fattura"`:

```python
        if invoice.importata_da is not None:
            raise Conflict(
                ENTITY,
                f"fattura importata da {invoice.importata_da}: l'XML e' quello gia' trasmesso "
                "allo SdI dal gestionale precedente, questo CRM non ne produce un secondo",
                anno=invoice.anno,
                numero=invoice.numero,
            )
```

In `produce_artifacts`, dopo `invoice = self._require(invoice_id)`:

```python
        if invoice.importata_da is not None:
            raise Conflict(
                ENTITY,
                f"fattura importata da {invoice.importata_da}: il PDF e' l'originale caricato, "
                "non si rigenera",
                anno=invoice.anno,
                numero=invoice.numero,
            )
```

- [ ] **Step 4: Verde**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest packages/core/tests/test_invoice_import.py packages/core/tests/test_invoice_artifacts.py packages/core/tests/test_invoice_artifacts_xml.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/invoices/service.py packages/core/tests/test_invoice_import.py
git commit -m "feat(invoices): imported invoices adopt their original PDF and never produce XML or a re-render"
```

---

### Task 7: REST

**Files:**
- Modify: `apps/api/src/pigrocrm_api/routers/invoices.py`
- Test: `apps/api/tests/test_invoices_import_api.py` (nuovo)

**Interfaces:**
- Produces: `POST /api/invoices/import` (body `InvoiceImport`, 201, `InvoiceImportResult = {fattura: InvoiceRead, buchi_non_dichiarati: list[int]}`), `POST /api/invoices/register/{anno}/gaps` (body `RegisterGapsDeclare`, 200, `list[RegisterGapRead]`), `GET /api/invoices/register/{anno}/gaps` (200, `list[RegisterGapRead]`). Le rotte `register/...` vanno dichiarate **prima** di `/{invoice_id}` nel file, o FastAPI proverà a leggere `register` come UUID.

- [ ] **Step 1: Test che fallisce**

```python
"""REST surface of the historical import (slice 9 §3.6)."""

from datetime import date
from typing import Any

from fastapi.testclient import TestClient


def _body(customer_id: str, numero: int, giorno: str) -> dict[str, Any]:
    return {
        "anno": 2026,
        "numero": numero,
        "data_emissione": giorno,
        "customer_id": customer_id,
        "causale": "900142/0426/Consulenza AI CTO progetto Aurora",
        "righe": [
            {
                "descrizione": "900142/0426/Consulenza AI CTO progetto Aurora",
                "quantita": "9",
                "prezzo_unitario": "300",
                "prezzo_totale": "2700.00",
                "aliquota_iva": "0",
                "natura": "N2.2",
            }
        ],
        "imponibile": "2700.00",
        "imposta": "0.00",
        "bollo": "2.00",
        "totale": "3422.00",
        "stato_pagamento": "incassato",
        "data_incasso": "2026-05-20",
    }


def test_an_admin_imports_and_sees_the_undeclared_gaps(
    logged_in: TestClient, customer: dict[str, Any], fiscal_profile: dict[str, Any], emitter: dict[str, Any]
) -> None:
    first = logged_in.post("/api/invoices/import", json=_body(customer["id"], 7, "2026-05-05"))
    assert first.status_code == 201, first.text
    assert first.json()["fattura"]["importata_da"] == "the previous system"
    assert first.json()["buchi_non_dichiarati"] == []

    second = logged_in.post("/api/invoices/import", json=_body(customer["id"], 9, "2026-06-05"))
    assert second.status_code == 201, second.text
    assert second.json()["buchi_non_dichiarati"] == [8]

    gaps = logged_in.post("/api/invoices/register/2026/gaps", json={"buchi": [{"numero": 8, "motivo": "annullata"}]})
    assert gaps.status_code == 200, gaps.text
    assert [g["numero"] for g in gaps.json()] == [8]
    assert logged_in.get("/api/invoices/register/2026/gaps").json()[0]["motivo"] == "annullata"

    xml = logged_in.get(f"/api/invoices/{first.json()['fattura']['id']}/xml")
    assert xml.status_code == 409


def test_a_collaborator_cannot_import(collaborator_client: TestClient, customer: dict[str, Any]) -> None:
    response = collaborator_client.post("/api/invoices/import", json=_body(customer["id"], 7, "2026-05-05"))
    assert response.status_code == 403
```

Leggere in `apps/api/tests/test_invoices_api.py` i nomi esatti delle fixture `customer`, `fiscal_profile`, `emitter` e ricopiarli/importarli (sono definite lì o in `conftest.py`).

- [ ] **Step 2: Vederlo fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest apps/api/tests/test_invoices_import_api.py -q`
Expected: FAIL — 404/405 su `/api/invoices/import`.

- [ ] **Step 3: Implementare**

In `routers/invoices.py`, prima della prima rotta con `/{invoice_id}`:

```python
class InvoiceImportResult(BaseModel):
    fattura: InvoiceRead
    buchi_non_dichiarati: list[int]


@router.post("/import", response_model=InvoiceImportResult, status_code=status.HTTP_201_CREATED)
def import_issued(
    data: InvoiceImport, session: SessionDep, storage: StorageDep, settings: SettingsDep, actor: ActorDep
) -> InvoiceImportResult:
    """Slice 9 §3: a fattura issued by the previous system. Admin only, enforced by the
    service. No artefacts are produced: the PDF, if any, is the original."""
    service = _service(session, storage, settings)
    fattura = service.import_issued(data, actor)
    return InvoiceImportResult(fattura=fattura, buchi_non_dichiarati=service.undeclared_gaps(data.anno))


@router.get("/register/{anno}/gaps", response_model=list[RegisterGapRead])
def register_gaps(
    anno: int, session: SessionDep, storage: StorageDep, settings: SettingsDep, actor: ActorDep
) -> list[RegisterGapRead]:
    return _service(session, storage, settings).register_gaps(anno, actor)


@router.post("/register/{anno}/gaps", response_model=list[RegisterGapRead])
def declare_register_gaps(
    anno: int, data: RegisterGapsDeclare, session: SessionDep, storage: StorageDep, settings: SettingsDep, actor: ActorDep
) -> list[RegisterGapRead]:
    return _service(session, storage, settings).declare_gaps(anno, data, actor)
```

Importare `InvoiceImport`, `RegisterGapsDeclare`, `RegisterGapRead` dagli schemi core.

- [ ] **Step 4: Verde**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest apps/api/tests/test_invoices_import_api.py apps/api/tests/test_invoices_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/pigrocrm_api/routers/invoices.py apps/api/tests/test_invoices_import_api.py
git commit -m "feat(api): POST /api/invoices/import and the register gaps endpoints"
```

---

### Task 8: Tool MCP privilegiati e liste dei divieti

**Files:**
- Modify: `packages/core/src/pigrocrm/core/actor.py` (`AGENT_FORBIDDEN_ACTIONS`)
- Modify: `apps/mcp/src/pigrocrm_mcp/tools/privileged.py`
- Modify: `apps/mcp/tests/test_mcp_invoice_ban.py` (`FORBIDDEN`, `FORBIDDEN_SERVICE_CALLS`), `apps/mcp/tests/test_mcp_surface_coverage.py` (`_VIETATE`)
- Test: `apps/mcp/tests/test_invoice_import_tools.py` (nuovo)

**Interfaces:**
- Produces: tool `import_issued_invoice(dati: dict[str, Any]) -> dict[str, Any]` (valida `InvoiceImport(**dati)`, restituisce `{"fattura": ..., "buchi_non_dichiarati": [...]}`) e `declare_invoice_register_gaps(anno: int, buchi: list[dict[str, Any]]) -> list[dict[str, Any]]`.
- Le due azioni `"import_issued_invoice"` e `"declare_invoice_register_gaps"` entrano in `AGENT_FORBIDDEN_ACTIONS`; `FORBIDDEN` (tool names) riceve le stesse due stringhe; `FORBIDDEN_SERVICE_CALLS` riceve `"import_issued"` e `"declare_gaps"`; `_VIETATE` riceve `("InvoiceService", "import_issued")` e `("InvoiceService", "declare_gaps")`.

- [ ] **Step 1: Aggiornare le liste (è il test che fallisce)**

In `actor.py`, dopo `"discover_gmail_correspondents"`:

```python
        # Slice 9 §3.6: writing a numbered, issued row straight into the fiscal register,
        # and declaring the numbers it will never carry. Both change what the register
        # says about the past, which is the property every other entry here protects.
        "import_issued_invoice",
        "declare_invoice_register_gaps",
```

In `test_mcp_invoice_ban.py`: aggiungere `"import_issued_invoice", "declare_invoice_register_gaps"` a `FORBIDDEN` (dopo `discover_gmail_correspondents`, con un commento di due righe) e `"import_issued", "declare_gaps"` a `FORBIDDEN_SERVICE_CALLS`. In `test_mcp_surface_coverage.py` aggiungere a `_VIETATE`:

```python
    ("InvoiceService", "import_issued"): "scrive nel registro fiscale un numero deciso altrove (slice 9 §3)",
    ("InvoiceService", "declare_gaps"): "dichiara i buchi del registro fiscale (slice 9 §3.2)",
```

Nuovo file `apps/mcp/tests/test_invoice_import_tools.py`:

```python
"""The two import tools exist only behind `mcp_full_access` and write the register."""

from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_mcp.server import build_server

TOOLS = {"import_issued_invoice", "declare_invoice_register_gaps"}


def _server(session: Session, tmp_path: Path, *, full_access: bool) -> Any:
    return build_server(
        lambda: session,
        lambda: Actor(id=None, type="mcp", role="admin", full_access=full_access),
        LocalFileStorage(tmp_path),
        settings=Settings(_env_file=None, mcp_full_access=full_access),  # type: ignore[call-arg]
    )


@pytest.mark.parametrize("full_access", [False, True])
async def test_the_tools_exist_only_when_the_installation_opted_in(mcp_session: Session, tmp_path: Path, full_access: bool) -> None:
    names = {tool.name for tool in await _server(mcp_session, tmp_path, full_access=full_access).list_tools()}
    assert (TOOLS <= names) is full_access


async def test_import_registers_the_invoice_and_names_the_gaps(mcp_session: Session, tmp_path: Path) -> None:
    from conftest import _invoice_service  # seeds the two profiles the import freezes

    _invoice_service(mcp_session, LocalFileStorage(tmp_path))
    customer = Customer(ragione_sociale="Acme S.r.l.", partita_iva="12345678901", codice_sdi="ABCDEFG", indirizzo="Via Roma 1", cap="20154", comune="Milano", provincia="MI", nazione="IT")
    mcp_session.add(customer)
    mcp_session.flush()
    dati = {
        "anno": 2026, "numero": 9, "data_emissione": "2026-06-05", "customer_id": str(customer.id),
        "righe": [{"descrizione": "900142/0526/Consulenza AI CTO progetto Aurora", "quantita": "20", "prezzo_unitario": "300", "prezzo_totale": "6000.00", "aliquota_iva": "0", "natura": "N2.2"}],
        "imponibile": "6000.00", "imposta": "0.00", "bollo": "2.00", "totale": "6002.00",
    }
    async with Client(_server(mcp_session, tmp_path, full_access=True)) as client:
        result = await client.call_tool("import_issued_invoice", {"dati": dati})
        payload = result.structured_content
        assert payload["fattura"]["numero"] == 9 and payload["fattura"]["importata_da"] == "the previous system"
        gaps = await client.call_tool("declare_invoice_register_gaps", {"anno": 2026, "buchi": [{"numero": 8, "motivo": "annullata in the previous system"}]})
        assert gaps.structured_content["result"][0]["numero"] == 8
```

Se `conftest` dei test core non è importabile dai test MCP (radici separate), ricopiare in testa al file il seeding dei due profili (`FiscalProfileService(...).upsert(FiscalProfileUpsert(codice_regime="RF19"), admin)` e l'`EmitterProfileUpsert` di `packages/core/tests/conftest.py:240-270`). La forma di `structured_content` per una lista (`{"result": [...]}`) va verificata con `_payload` di `test_gmail_tools.py`.

- [ ] **Step 2: Vederli fallire**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest apps/mcp/tests/test_invoice_import_tools.py apps/mcp/tests/test_mcp_invoice_ban.py apps/mcp/tests/test_mcp_surface_coverage.py -q`
Expected: FAIL — i tool non esistono; `test_the_sixteen_are_registered_exactly_when_the_installation_opted_in` fallisce perché mancano due nomi; `test_the_privileged_module_is_the_only_place_they_appear` perché `.import_issued(` non compare in `privileged.py`.

- [ ] **Step 3: Implementare i tool**

In `privileged.py`, nella sezione «fiscal acts», dopo `export_invoice_xml`:

```python
    @mcp.tool()
    @guard
    def import_issued_invoice(dati: dict[str, Any]) -> dict[str, Any]:
        """Registra una fattura **gia' emessa dal gestionale precedente** (the previous system) con il
        suo numero e la sua data: il contatore dell'anno sale fino a quel numero e non
        viene prodotto nessun XML, perche' quello e' gia' stato trasmesso allo SdI.

        `dati` ha la forma di `InvoiceImport`: anno, numero, data_emissione, customer_id,
        righe (con prezzo_totale, aliquota_iva e natura come stampati sul documento),
        imponibile, imposta, bollo, totale, stato_pagamento, data_incasso,
        trasmessa_esternamente_il, pdf_sorgente {document_id}. I totali devono tornare al
        centesimo. La risposta elenca in `buchi_non_dichiarati` i numeri che mancano fra
        quelli importati: vanno dichiarati con `declare_invoice_register_gaps` prima che
        PigroCRM possa emettere la fattura successiva.
        """
        service = InvoiceService(context.session, context.storage)
        payload = InvoiceImport(**dati)
        fattura = service.import_issued(payload, context.actor)
        return {
            "fattura": fattura.model_dump(mode="json"),
            "buchi_non_dichiarati": service.undeclared_gaps(payload.anno),
        }

    @mcp.tool()
    @guard
    def declare_invoice_register_gaps(anno: int, buchi: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Dichiara i numeri che il registro di `anno` **non** portera' mai, con il
        motivo di ciascuno (es. annullata nel gestionale precedente prima della
        trasmissione). Un buco dichiarato resta tale: non si inventa una fattura per
        riempirlo. Finche' un numero mancante non e' dichiarato, l'emissione di nuove
        fatture in quell'anno e' bloccata.
        """
        service = InvoiceService(context.session, context.storage)
        result = service.declare_gaps(anno, RegisterGapsDeclare(buchi=buchi), context.actor)  # type: ignore[arg-type]
        return [g.model_dump(mode="json") for g in result]
```

Importare `InvoiceImport`, `RegisterGapsDeclare` da `pigrocrm.core.invoices.schemas`.

- [ ] **Step 4: Verde, comprese le guardie**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run --directory . pytest apps/mcp/tests/test_invoice_import_tools.py apps/mcp/tests/test_mcp_invoice_ban.py apps/mcp/tests/test_mcp_surface_coverage.py apps/mcp/tests/test_mcp_tools.py -q`
Expected: PASS. Se `test_no_tool_schema_accepts_a_gmail_search_string` o un test di schema si lamenta del parametro `dati: dict`, quel test riguarda solo i tool Gmail; verificare che il nuovo tool non rientri nel suo insieme.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/pigrocrm/core/actor.py apps/mcp/src/pigrocrm_mcp/tools/privileged.py apps/mcp/tests/test_invoice_import_tools.py apps/mcp/tests/test_mcp_invoice_ban.py apps/mcp/tests/test_mcp_surface_coverage.py
git commit -m "feat(mcp): import_issued_invoice and declare_invoice_register_gaps behind mcp_full_access; ban lists at nineteen"
```

---

### Task 9: Badge «importata da the previous system» e niente XML nel frontend

**Files:**
- Modify: `apps/web/src/lib/api-types.ts` (rigenerato), `apps/web/src/features/invoices/InvoiceStateBadge.tsx`, `apps/web/src/features/invoices/InvoiceActions.tsx`
- Test: `apps/web/src/features/invoices/InvoiceActions.test.tsx` (append)

**Interfaces:**
- Consumes: `Invoice.importata_da: string | null` dal tipo generato.

- [ ] **Step 1: Rigenerare i tipi**

Con l'API in esecuzione dal worktree (`uvicorn pigrocrm_api.main:app --port 8000`, oppure quella già attiva dopo un restart che includa il Task 7): `cd apps/web && npm run generate:api`. Verificare con `grep -n importata_da src/lib/api-types.ts`.

- [ ] **Step 2: Test che fallisce**

Append a `InvoiceActions.test.tsx`, seguendo il render helper già presente nel file:

```tsx
it('hides the XML and regenerate actions for an invoice imported from the previous system', () => {
  const imported = { ...issuedInvoice, importata_da: 'the previous system' }
  renderActions(imported)
  expect(screen.queryByRole('button', { name: /XML FatturaPA/i })).toBeNull()
  expect(screen.queryByRole('button', { name: /Rigenera/i })).toBeNull()
  expect(screen.getByText(/importata da the previous system/i)).toBeInTheDocument()
})
```

Usare i nomi reali del fixture (`issuedInvoice`) e dell'helper (`renderActions`) presenti nel file; il testo del pulsante «Rigenera» va letto da `InvoiceActions.tsx:120-127`.

- [ ] **Step 3: Vederlo fallire**

Run: `cd apps/web && npx vitest run src/features/invoices/InvoiceActions.test.tsx`
Expected: FAIL — il pulsante XML è presente.

- [ ] **Step 4: Implementare**

`InvoiceStateBadge.tsx`: dopo il badge dello stato, se `invoice.importata_da` è valorizzato, un secondo `<Badge variant="outline">importata da {invoice.importata_da === 'the previous system' ? 'the previous system' : invoice.importata_da}</Badge>`, entrambi dentro un `<span className="inline-flex gap-1">`.

`InvoiceActions.tsx`: introdurre `const isImported = invoice.importata_da != null` e condizionare a `isIssued && !isImported` i pulsanti «XML FatturaPA» e «Rigenera PDF/XML» (righe 111-127). Il download PDF resta: è l'originale.

- [ ] **Step 5: Verde e lint**

Run: `cd apps/web && npx vitest run src/features/invoices && npm run lint && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/api-types.ts apps/web/src/features/invoices/InvoiceStateBadge.tsx apps/web/src/features/invoices/InvoiceActions.tsx apps/web/src/features/invoices/InvoiceActions.test.tsx
git commit -m "feat(web): imported-from-the previous system badge; no XML or re-render on imported invoices"
```

---

### Task 10: Il dataset delle 14 fatture e il runbook

**Files:**
- Create: `docs/superpowers/data/2026-09-04-the previous system-fatture-2026.json`
- Create: `docs/superpowers/notes/2026-09-04-import-the previous system-runbook.md`

**Interfaces:**
- Consumes: `InvoiceImport` (Task 2), tool `import_issued_invoice` (Task 8).

- [ ] **Step 1: Scrivere il dataset**

Un array JSON di 14 oggetti nel formato di `InvoiceImport` con `customer_id` da risolvere per `ragione_sociale` (campo ausiliario `_cliente`, rimosso dallo script di invio). `data_scadenza`, `data_incasso` e `trasmessa_esternamente_il` da compilare dal titolare dove indicato `null`.

> **I valori qui sotto sono sintetici.** Il dataset reale (clienti, importi, tariffe, id Drive dei PDF) è stato rimosso da questo repository il 2026-09-09, prima della pubblicazione, insieme al file JSON che questo task creava: erano dati di clienti veri e il fatturato di un anno. Quello che resta è la forma, che è ciò di cui il piano ha bisogno per essere leggibile: 14 righe, i buchi di registro 1, 4 e 6 assenti, una fattura su due righe, una verso l'estero con `natura` diversa, e tre righe sotto la soglia del bollo. Chi rieseguisse questo task su dati propri parte da qui.

| numero | data | `_cliente` | descrizione riga | quantità × prezzo | imponibile | stato_pagamento |
|---|---|---|---|---|---|---|
| 2 | 2026-02-04 | Alfa S.r.l. | Consulenza sito vetrina | 1 × 200 | 200.00 | incassato |
| 3 | 2026-02-04 | Beta Service S.r.l. | Servizi di consulenza progetto Delta (ODA 2026-012-ACM-BET) | 1 × 900 | 900.00 | incassato |
| 5 | 2026-04-07 | Mario Rossi | Consulenza AI prototipo Delta — anticipo | 1 × 2000 | 2200.00 (seconda riga: spese accessorie 200.00) | incassato; `trasmessa_esternamente_il: null` (non consegnata) |
| 7 | 2026-05-05 | Acme S.r.l. | 900142/0426/Consulenza AI CTO progetto Aurora | 9 × 300 | 2700.00 | incassato |
| 8 | 2026-05-05 | Gamma Società Cooperativa | Servizi di consulenza progetto Vega — pre-analisi console remota | 3 × 300 | 900.00 | incassato |
| 9 | 2026-06-05 | Acme S.r.l. | 900142/0526/Consulenza AI CTO progetto Aurora | 20 × 300 | 6000.00 | incassato |
| 10 | 2026-06-05 | Acme S.r.l. | 900142/0526/Rimborso spese | 1 × 60.50 | 60.50 | incassato |
| 11 | 2026-07-13 | Acme S.r.l. | 900142/0626/Consulenza AI CTO progetto Aurora | 21 × 300 | 6300.00 | incassato |
| 12 | 2026-07-13 | Acme S.r.l. | 900142/0626/Rimborso hosting | 1 × 15.00 | 15.00 | incassato |
| 13 | 2026-08-03 | Example Ltd | Consulting services for project Vega — July 2026 (pro-rata) | 1 × 5000 | 5000.00 | incassato |
| 14 | 2026-08-03 | Acme S.r.l. | 900143/0726/Consulenza AI CTO progetto Aurora | 21 × 310 | 6510.00 | da_incassare (scaduta) |
| 15 | 2026-08-03 | Gamma Società Cooperativa | Consulenza console remota Vega — acconto 30% | 1 × 2500 | 2500.00 | da_incassare (scaduta) |
| 16 | 2026-08-11 | Gamma Società Cooperativa | Consulenza console remota Vega — 20% post UAT | 1 × 1600 | 1600.00 | da_incassare |
| 17 | 2026-08-11 | Acme S.r.l. | 900143/0726/Rimborso hosting | 1 × 20.00 | 20.00 | da_incassare |

Per ogni riga: `aliquota_iva: "0"`, `natura: "N2.2"`, `imposta: "0.00"`; `bollo: "2.00"` sulle fatture con imponibile > 77,47 (tutte tranne 10, 12, 17) e `totale = imponibile + bollo`. **Il bollo va confermato dal titolare** contro i PDF: se il registro di partenza non lo applicava, `bollo: "0.00"` e `totale = imponibile`. Il dataset nasce con `bollo: "0.00"` e una nota che lo dice. La fattura 13 (cliente UK) porta `natura: "N2.1"`.

- [ ] **Step 2: Scrivere il runbook**

`docs/superpowers/notes/2026-09-04-import-the previous system-runbook.md`, in ordine:
1. Compilare profilo fiscale ed emittente in Impostazioni (o `PUT /api/fiscal-profile`, `PUT /api/emitter-profile`).
2. Riavviare l'API dal worktree (non ha `--reload`).
3. Per ogni riga del dataset, in ordine di numero, chiamare `import_issued_invoice` dal server MCP `pigrocrm` (o `POST /api/invoices/import`); alla fine dichiarare i buchi 1, 4, 6 con `declare_invoice_register_gaps` (motivo da chiedere al titolare; default «numero non emesso in the previous system»).
4. Verifiche: `list_invoices` → 14 righe con `importata_da = "the previous system"`; contatore 2026 = 17 (`SELECT * FROM invoice_counters`); `get_unbilled_backlog`/scadenziario mostrano 14 e 15 scadute; `export_invoice_xml` su una importata risponde 409.
5. Caricare i PDF originali dalla cartella Drive `Fatture` come documenti `tipo = fattura` (a mano via `POST /api/documents` + upload versione finché 9C non esiste) e ricollegarli con `pdf_sorgente` — oppure attendere 9C e farlo con `import_drive_file`.

- [ ] **Step 3: Validare il dataset contro lo schema**

```bash
uv run --directory . python - <<'EOF'
import json
from pigrocrm.core.invoices.schemas import InvoiceImport
rows = json.load(open("docs/superpowers/data/2026-09-04-the previous system-fatture-2026.json"))
for row in rows:
    row = {k: v for k, v in row.items() if not k.startswith("_")}
    row["customer_id"] = "00000000-0000-0000-0000-000000000000"
    InvoiceImport(**row)
print(len(rows), "righe valide")
EOF
```

Expected: `14 righe valide`.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/data/2026-09-04-the previous system-fatture-2026.json docs/superpowers/notes/2026-09-04-import-the previous system-runbook.md
git commit -m "docs: the previous system 2026 invoice dataset and import runbook (slice 9A)"
```

---

## Self-review

- **Spec §3.1** colonna e assenza XML/PDF → Task 1, 6. **§3.2** regole 1–6 → Task 3–5 (unicità: constraint esistente + `numbers_present`; monotonia a due vicini; contatore `max`; buchi dichiarati con blocco dell'emissione nativa; data non futura; nessun import sopra la prima nativa). **§3.3** dati e totali dichiarati → Task 2, 4. **§3.4** snapshot → Task 4. **§3.5** PDF → Task 6 (solo `document_id`; `drive_file_id` è 9C, dichiarato nei Global Constraints). **§3.6** superficie → Task 7, 8, 9. **§3.7** import concreto → Task 10.
- Nomi coerenti: `import_issued`, `declare_gaps`, `register_gaps`, `undeclared_gaps`, `neighbour_dates`, `numbers_present`, `declared_gaps`, `first_native_number`, `_adopt_original_pdf`, `IMPORT_ACTION = "import_issued_invoice"`, `GAPS_ACTION = "declare_invoice_register_gaps"`; tool `import_issued_invoice`, `declare_invoice_register_gaps`; FORBIDDEN_SERVICE_CALLS `import_issued`, `declare_gaps`.
- Punti da verificare sul codice reale, esplicitati nei task: attributi di `Document`/`DocumentVersion`, forma di `ValidationFailed.details`, importabilità di `conftest` nei test MCP, nome del ruolo non-admin, tipo `id` nelle migrazioni, `EntityType` accettati da `ActivityService.record`.
