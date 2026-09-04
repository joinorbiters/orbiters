"""Import dello storico fatture (slice 9 §3)."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
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


def _svc(session: Session, tmp_path):  # noqa: ANN001
    """`InvoiceService` with the two profiles it reads already in place.

    Copied from `conftest._invoice_service` rather than imported, for the same
    reason `_fiscal_customer_id` above is copied and not imported: `conftest` is an
    ambiguous top-level module name across this repository's three test roots.
    """
    from pigrocrm.core.emitter.repository import EmitterProfileRepository
    from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
    from pigrocrm.core.emitter.service import EmitterProfileService
    from pigrocrm.core.fiscal.repository import FiscalProfileRepository
    from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
    from pigrocrm.core.fiscal.service import FiscalProfileService
    from pigrocrm.core.invoices.service import InvoiceService
    from pigrocrm.core.storage.local import LocalFileStorage

    if FiscalProfileRepository(session).get() is None:
        FiscalProfileService(session).upsert(FiscalProfileUpsert(codice_regime="RF19"), ADMIN)
    if EmitterProfileRepository(session).get() is None:
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
            ADMIN,
        )
    return InvoiceService(session, LocalFileStorage(tmp_path))


def _payload(
    customer_id: UUID, *, numero: int, giorno: date, **overrides: object
) -> "InvoiceImport":  # noqa: F821
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
                "prezzo_unitario": Decimal("380"),
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


def test_an_imported_invoice_is_issued_numbered_and_moves_the_counter(
    db_session: Session, tmp_path
) -> None:  # noqa: ANN001
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
    assert [(riga.numero_linea, riga.prezzo_totale, riga.natura) for riga in lines] == [
        (1, Decimal("2700.00"), "N2.2")
    ]
    row = db_session.get(Invoice, read.id)
    assert row.snapshot is not None and row.snapshot["versione"] == 1


def test_the_counter_never_moves_backwards(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.invoices.models import InvoiceCounter

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=11, giorno=date(2026, 7, 13)), ADMIN)
    service.import_issued(_payload(cid, numero=9, giorno=date(2026, 6, 5)), ADMIN)
    assert db_session.get(InvoiceCounter, 2026).ultimo_numero == 11


def test_a_duplicate_number_is_a_conflict(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import Conflict

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)
    with pytest.raises(Conflict):
        service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)


def test_the_register_stays_chronological_against_both_neighbours(
    db_session: Session, tmp_path
) -> None:  # noqa: ANN001
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
    from pigrocrm.core.errors import ValidationFailed

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    with pytest.raises(ValidationFailed) as caught:
        service.import_issued(
            _payload(cid, numero=7, giorno=date(2026, 5, 5), totale=Decimal("3421.99")), ADMIN
        )
    assert "3422.00" in caught.value.message and "3421.99" in caught.value.message
    with pytest.raises(ValidationFailed):
        service.import_issued(
            _payload(
                cid,
                numero=7,
                giorno=date(2026, 5, 5),
                imponibile=Decimal("3400.00"),
                totale=Decimal("3402.00"),
            ),
            ADMIN,
        )


def test_a_future_date_and_a_collaborator_are_refused(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from datetime import timedelta

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
    from pigrocrm.core.activities.models import Activity

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    read = service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)
    kinds = (
        db_session.execute(
            select(Activity.kind).where(
                Activity.entity_type == "invoice", Activity.entity_id == read.id
            )
        )
        .scalars()
        .all()
    )
    assert kinds == ["imported"]


def test_a_collection_date_without_a_collected_state_is_refused(
    db_session: Session, tmp_path
) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import ValidationFailed

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    with pytest.raises(ValidationFailed) as caught:
        service.import_issued(
            _payload(cid, numero=7, giorno=date(2026, 5, 5), stato_pagamento="da_incassare"),
            ADMIN,
        )
    assert caught.value.details["field"] == "data_incasso"


def test_anno_must_match_the_issue_dates_year(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import ValidationFailed

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    with pytest.raises(ValidationFailed) as caught:
        service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5), anno=2025), ADMIN)
    assert caught.value.details["field"] == "anno"


def test_a_declared_gap_refuses_the_import_of_that_number(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import Conflict

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.repo.add_gap(InvoiceRegisterGap(anno=2026, numero=8, motivo="annullata in the previous system"))
    with pytest.raises(Conflict):
        service.import_issued(_payload(cid, numero=8, giorno=date(2026, 5, 5)), ADMIN)


def test_import_is_refused_above_the_first_native_number(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import Conflict

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    _issued(db_session, anno=2026, numero=5, giorno=date(2026, 4, 1), importata=False)
    with pytest.raises(Conflict):
        service.import_issued(_payload(cid, numero=6, giorno=date(2026, 4, 2)), ADMIN)
    service.import_issued(_payload(cid, numero=3, giorno=date(2026, 3, 1)), ADMIN)


def test_gaps_are_declared_with_a_reason_and_listed(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.invoices.schemas import RegisterGapsDeclare

    service = _svc(db_session, tmp_path)
    out = service.declare_gaps(
        2026,
        RegisterGapsDeclare(
            buchi=[
                {"numero": 1, "motivo": "annullata in the previous system"},
                {"numero": 4, "motivo": "test di emissione"},
            ]
        ),  # type: ignore[list-item]
        ADMIN,
    )
    assert [(g.numero, g.motivo) for g in out] == [
        (1, "annullata in the previous system"),
        (4, "test di emissione"),
    ]
    assert [g.numero for g in service.register_gaps(2026, ADMIN)] == [1, 4]


def test_declaring_a_number_that_is_an_invoice_is_a_conflict(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import Conflict
    from pigrocrm.core.invoices.schemas import RegisterGapsDeclare

    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=7, giorno=date(2026, 5, 5)), ADMIN)
    with pytest.raises(Conflict):
        service.declare_gaps(2026, RegisterGapsDeclare(buchi=[{"numero": 7, "motivo": "x"}]), ADMIN)  # type: ignore[list-item]


def test_undeclared_gaps_are_named_and_block_native_issuing(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.clock import oggi_in_italia
    from pigrocrm.core.errors import Conflict
    from pigrocrm.core.invoices.schemas import (
        InvoiceCreate,
        InvoiceIssue,
        InvoiceLineIn,
        RegisterGapsDeclare,
    )

    anno = oggi_in_italia().year
    service = _svc(db_session, tmp_path)
    cid = _fiscal_customer_id(db_session)
    service.import_issued(_payload(cid, numero=2, giorno=date(anno, 2, 4)), ADMIN)
    service.import_issued(_payload(cid, numero=5, giorno=date(anno, 4, 7)), ADMIN)
    assert service.undeclared_gaps(anno) == [3, 4]

    draft = service.create(
        InvoiceCreate(
            customer_id=cid, righe=[InvoiceLineIn(descrizione="x", prezzo_unitario=Decimal("100"))]
        ),
        ADMIN,
    )
    with pytest.raises(Conflict) as caught:
        service.issue(draft.id, InvoiceIssue(), ADMIN)
    assert "3" in str(caught.value) and "4" in str(caught.value)

    service.declare_gaps(
        anno,
        RegisterGapsDeclare(buchi=[{"numero": 3, "motivo": "a"}, {"numero": 4, "motivo": "b"}]),  # type: ignore[list-item]
        ADMIN,
    )
    assert service.undeclared_gaps(anno) == []
    issued = service.issue(draft.id, InvoiceIssue(), ADMIN)
    assert issued.numero == 6


def test_a_same_batch_duplicate_number_is_a_conflict_and_leaves_the_session_usable(
    db_session: Session, tmp_path
) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import Conflict
    from pigrocrm.core.invoices.schemas import RegisterGapsDeclare

    service = _svc(db_session, tmp_path)
    with pytest.raises(Conflict):
        service.declare_gaps(
            2026,
            RegisterGapsDeclare(buchi=[{"numero": 3, "motivo": "a"}, {"numero": 3, "motivo": "b"}]),  # type: ignore[list-item]
            ADMIN,
        )
    # The session must still answer a query after the Conflict: a poisoned
    # transaction (an unrolled-back IntegrityError) would raise on this next
    # statement instead of returning a result. This particular Conflict never
    # touches Postgres -- it is refused in Python, from the batch-local `seen` set,
    # before the duplicate's own `add_gap` flush -- so it does not poison the
    # session the way an actual `IntegrityError` would; the point of this test is
    # only that the call below does not raise.
    service.register_gaps(2026, ADMIN)


def test_anno_out_of_range_is_refused_before_any_write(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from pigrocrm.core.errors import ValidationFailed
    from pigrocrm.core.invoices.schemas import RegisterGapsDeclare

    service = _svc(db_session, tmp_path)
    with pytest.raises(ValidationFailed) as caught:
        service.declare_gaps(
            10**12,
            RegisterGapsDeclare(buchi=[{"numero": 1, "motivo": "x"}]),  # type: ignore[list-item]
            ADMIN,
        )
    assert caught.value.details["field"] == "anno"
    assert db_session.execute(select(InvoiceRegisterGap)).first() is None
