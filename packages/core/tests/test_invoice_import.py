"""Import dello storico fatture (slice 9 §3)."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.invoices.models import Invoice, InvoiceRegisterGap

ADMIN = Actor(id=None, type="system", role="admin")


def _fiscal_customer_id(session: Session) -> UUID:
    """A customer with enough identity to appear on an issued document.

    Copied from `conftest.py` rather than imported: `conftest` is an ambiguous
    top-level module name across this repository's three test roots, and only the
    directory pytest resolves first would ever bind `from conftest import ...`
    correctly when the whole suite is collected in one run.
    """
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


def test_an_invoice_records_where_it_was_imported_from(db_session: Session) -> None:
    row = Invoice(
        customer_id=_fiscal_customer_id(db_session),
        tipo="fattura",
        stato="emessa",
        anno=2026,
        numero=7,
        data_emissione=date(2026, 5, 5),
        importata_da="acme",
        imponibile=Decimal("3420.00"),
        imposta=Decimal("0.00"),
        bollo=Decimal("2.00"),
        totale=Decimal("3422.00"),
    )
    db_session.add(row)
    db_session.flush()
    assert db_session.get(Invoice, row.id).importata_da == "acme"


def test_a_register_gap_is_unique_per_year_and_number(db_session: Session) -> None:
    db_session.add(InvoiceRegisterGap(anno=2026, numero=4, motivo="annullata in Acme"))
    db_session.flush()
    db_session.add(InvoiceRegisterGap(anno=2026, numero=4, motivo="di nuovo"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
