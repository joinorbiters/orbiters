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


def _issued(
    session: Session, *, anno: int, numero: int, giorno: date, importata: bool = True
) -> Invoice:
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
