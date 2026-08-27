import subprocess
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.fiscal.repository import FiscalProfileRepository
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.storage.local import LocalFileStorage
from pigrocrm.core.timetracking.models import CostCategory, TimeEntry


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Real PostgreSQL. JSONB and GIN do not exist in SQLite, so there is no shortcut."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        settings = Settings(database_url=container.get_connection_url())
        engine = create_engine_from_settings(settings)
        import pigrocrm.core.models_registry  # noqa: F401  (imports every model)

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Each test runs in a transaction that is rolled back, so tests never see each other."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = session_factory(db_engine)(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


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
    stage = PipelineStage(
        nome=f"Aperto {uuid4()}", posizione=0, probabilita_default=10, tipo="open"
    )
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


@pytest.fixture
def local_storage(tmp_path) -> LocalFileStorage:
    """A tmp-dir backend, never the default `./var/documents` root -- a test must not
    write real files into this repository's working tree."""
    return LocalFileStorage(str(tmp_path / "documents"))


@pytest.fixture
def extract_pdf_text() -> Callable[[LocalFileStorage, Session, UUID], str]:
    """Reads the stored PDF back and extracts its text with `pdftotext`, which ships in
    the same API image as Pandoc and Typst. Reading the produced artefact rather than
    the intermediate Markdown is the only assertion that proves what the client
    actually receives.

    A fixture returning the callable, deliberately, rather than a plain module-level
    function a test imports as `from conftest import extract_pdf_text`. This repository
    has three test roots -- `packages/core/tests`, `apps/api/tests`, `apps/mcp/tests` --
    each with its own `conftest.py` and none with an `__init__.py`, so `conftest` is an
    ambiguous top-level module name: whichever one pytest imports first claims
    `sys.modules["conftest"]` and every later import binds to *that* file. Running one
    root at a time hid it; `uv run pytest` with no path -- the CI command, which
    collects all three -- resolved the import against `apps/mcp/tests/conftest.py` and
    died at collection. Fixture resolution is scoped per directory by pytest itself, so
    it cannot collide however the roots are combined."""

    def _extract(storage: LocalFileStorage, session: Session, document_id: UUID) -> str:
        from pigrocrm.core.documents.repository import DocumentRepository

        version = DocumentRepository(session).version(document_id, 1)
        assert version is not None
        data = storage.get(version.storage_key)
        result = subprocess.run(
            ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
        )
        return result.stdout.decode("utf-8", errors="replace")

    return _extract


# --- slice 3 invoices, as states rather than as rows -------------------------------
#
# The three fixtures below build a real invoice through `InvoiceService` instead of
# inserting `invoice_lines` by hand, so `(tipo, stato)`, the line invariants and the
# register number are the ones that service produces. Task 4B-3 needs them because
# `time_entries.invoice_line_id` is a real foreign key from migration 0012 on: a random
# UUID no longer stands in for a line, and the rule the column feeds -- "frozen only
# when the invoice is *issued*" -- is a question about the invoice's state that only a
# genuinely issued row can answer.
#
# The imports are inside the functions, not at module scope: this file is loaded for
# every test in the package, and the invoices service drags in storage, rendering and
# the emitter with it.


def _invoice_service(session: Session, storage: LocalFileStorage) -> Any:
    """`InvoiceService` with the two profiles `issue()` reads already in place."""
    from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
    from pigrocrm.core.emitter.service import EmitterProfileService
    from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
    from pigrocrm.core.fiscal.service import FiscalProfileService
    from pigrocrm.core.invoices.service import InvoiceService

    admin = Actor(id=None, type="system", role="admin")
    if FiscalProfileRepository(session).get() is None:
        FiscalProfileService(session).upsert(FiscalProfileUpsert(codice_regime="RF19"), admin)
        EmitterProfileService(session).upsert(
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
            admin,
        )
    return InvoiceService(session, storage)


def _fiscal_customer_id(session: Session) -> UUID:
    """A customer with enough identity to appear on an issued document."""
    customer = Customer(
        ragione_sociale=f"Acme {uuid4()}",
        partita_iva="12345678901",
        codice_sdi="ABCDEFG",
        indirizzo="Corso Italia 5",
        cap="00100",
        comune="Roma",
        provincia="RM",
        nazione="IT",
    )
    session.add(customer)
    session.flush()
    return customer.id


def _invoice_of(session: Session, line_id: UUID) -> UUID:
    invoice_id: UUID = session.execute(
        text("SELECT invoice_id FROM invoice_lines WHERE id = :line"), {"line": line_id}
    ).scalar_one()
    return invoice_id


@pytest.fixture
def draft_invoice_line_id(db_session: Session, local_storage: LocalFileStorage) -> UUID:
    """A line on a `bozza`.

    The invoice carries its own customer and no `deal_id`: `_check_owner` requires the
    deal to belong to the invoice's customer, and the customer `seeded_deal_id` builds
    has only a `ragione_sociale`, which is not identity enough to issue against. What
    the tests using these fixtures need from an invoice is its *state*, never its link
    to a deal.
    """
    from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceLineIn

    invoice = _invoice_service(db_session, local_storage).create(
        InvoiceCreate(
            customer_id=_fiscal_customer_id(db_session),
            tipo="fattura",
            righe=[
                InvoiceLineIn(
                    descrizione="Attività",
                    quantita=Decimal("1.000000"),
                    prezzo_unitario=Decimal("100.000000"),
                )
            ],
        ),
        Actor(id=None, type="system", role="admin"),
    )
    line_id: UUID = db_session.execute(
        text("SELECT id FROM invoice_lines WHERE invoice_id = :inv ORDER BY numero_linea LIMIT 1"),
        {"inv": invoice.id},
    ).scalar_one()
    return line_id


@pytest.fixture
def proforma_invoice_line_id(db_session: Session, local_storage: LocalFileStorage) -> UUID:
    """A line on a `confermata` proforma -- the state closest to an emission that is not
    one. It never touches the register (slice 3 §5)."""
    from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceLineIn

    service = _invoice_service(db_session, local_storage)
    admin = Actor(id=None, type="system", role="admin")
    invoice = service.create(
        InvoiceCreate(
            customer_id=_fiscal_customer_id(db_session),
            tipo="proforma",
            righe=[
                InvoiceLineIn(
                    descrizione="Attività",
                    quantita=Decimal("1.000000"),
                    prezzo_unitario=Decimal("100.000000"),
                )
            ],
        ),
        admin,
    )
    service.confirm_proforma(invoice.id, admin)
    line_id: UUID = db_session.execute(
        text("SELECT id FROM invoice_lines WHERE invoice_id = :inv ORDER BY numero_linea LIMIT 1"),
        {"inv": invoice.id},
    ).scalar_one()
    return line_id


@pytest.fixture
def issued_invoice_line_id(
    db_session: Session, local_storage: LocalFileStorage, draft_invoice_line_id: UUID
) -> UUID:
    """The same line, once `issue()` has consumed a register number for it."""
    from pigrocrm.core.invoices.schemas import InvoiceIssue

    _invoice_service(db_session, local_storage).issue(
        _invoice_of(db_session, draft_invoice_line_id),
        InvoiceIssue(),
        Actor(id=None, type="system", role="admin"),
    )
    return draft_invoice_line_id


@pytest.fixture
def annulled_invoice_line_id(
    db_session: Session, local_storage: LocalFileStorage, issued_invoice_line_id: UUID
) -> UUID:
    """The same line again, on an invoice that keeps its number and loses its revenue."""
    from pigrocrm.core.invoices.schemas import InvoiceAnnul

    _invoice_service(db_session, local_storage).annul(
        _invoice_of(db_session, issued_invoice_line_id),
        InvoiceAnnul(motivo="errore di emissione"),
        Actor(id=None, type="system", role="admin"),
    )
    return issued_invoice_line_id
