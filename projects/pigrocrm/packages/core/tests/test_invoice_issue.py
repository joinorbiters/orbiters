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
from pigrocrm.core.clock import oggi_in_italia
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
# `oggi_in_italia()`, not `date.today()`: this test asserts the service's own output
# against this constant, and the two must agree regardless of the host running this
# suite -- a bare `date.today()` here would only coincidentally match the service if
# the test machine happened to be configured for Europe/Rome, which nothing enforces.
TODAY = oggi_in_italia()
# The other end of the legal issue window. `issue()` refuses a `data_emissione` after
# today *and* one before 1 January, so `CAPODANNO` and `TODAY` are the only pair of dates
# guaranteed to be accepted whatever day the suite runs on. The obvious "some date in
# this year" -- `date(TODAY.year, 6, 1)`, which these tests used to spell -- is in the
# future from 1 January to 31 May and is refused by the *other* limit, so writing it that
# way only moves the annual failure from one January to five months of winter.
CAPODANNO = date(TODAY.year, 1, 1)
# On 1 January those two are the same date: the register is one day old and the whole
# legal window is a single day, so there is no *pair* of dates for a rule about ordering
# between them to be about. The two tests that need two are skipped on that one day
# rather than left to assert the wrong thing -- a back-date to 31 December is refused by
# the closed-year check, which reports the same `field`, so the assertions below would
# still pass while proving nothing at all.
DUE_DATE_LEGALI = pytest.mark.skipif(
    TODAY == CAPODANNO,
    reason="il 1 gennaio l'unica data di emissione ammessa e' quella di oggi",
)


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
        service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN).numero for _ in range(3)
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


def test_a_failed_emission_consumes_no_number(service: InvoiceService, db_session: Session) -> None:
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
    document. `oggi_in_italia()` is the local civil date in Europe/Rome regardless of
    the process's own system timezone, and `anno` is derived from it, so the year in
    the number and the year on the document cannot disagree."""
    invoice = service.issue(_draft(service, _customer(db_session)), InvoiceIssue(), ADMIN)
    assert invoice.data_emissione == TODAY
    assert invoice.anno == invoice.data_emissione.year


@DUE_DATE_LEGALI
def test_back_dating_inside_the_current_year_is_allowed(
    service: InvoiceService, db_session: Session
) -> None:
    invoice = service.issue(
        _draft(service, _customer(db_session)), InvoiceIssue(data_emissione=CAPODANNO), ADMIN
    )
    assert invoice.data_emissione == CAPODANNO
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


@DUE_DATE_LEGALI
def test_the_register_must_stay_chronologically_monotonic(
    service: InvoiceService, db_session: Session
) -> None:
    """Read inside the locked transaction, where "the date of the previous number" is
    a safe thing to read."""
    customer_id = _customer(db_session)
    service.issue(_draft(service, customer_id), InvoiceIssue(data_emissione=TODAY), ADMIN)
    with pytest.raises(ValidationFailed) as caught:
        service.issue(
            _draft(service, customer_id),
            InvoiceIssue(data_emissione=CAPODANNO),
            ADMIN,
        )
    assert caught.value.details["field"] == "data_emissione"
    # The message, not only the field: `CAPODANNO` is a legal date on its own, so the
    # only refusal it can draw is this one. Asserting the field alone would also accept
    # the closed-year refusal, which is what a back-date across 31 December would raise.
    assert "cronologicamente monotono" in caught.value.message


def test_the_same_date_as_the_previous_invoice_is_allowed(
    service: InvoiceService, db_session: Session
) -> None:
    customer_id = _customer(db_session)
    same = CAPODANNO
    service.issue(_draft(service, customer_id), InvoiceIssue(data_emissione=same), ADMIN)
    assert (
        service.issue(_draft(service, customer_id), InvoiceIssue(data_emissione=same), ADMIN).numero
        == 2
    )


def test_the_due_date_comes_from_the_profile(service: InvoiceService, db_session: Session) -> None:
    invoice = service.issue(_draft(service, _customer(db_session)), InvoiceIssue(), ADMIN)
    assert invoice.data_scadenza == invoice.data_emissione + timedelta(days=30)


# --- the refusals, each naming the field (criterion 9) ------------------------------


def test_an_invoice_with_no_lines_is_refused(service: InvoiceService, db_session: Session) -> None:
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


def test_a_foreign_customer_is_issued_rather_than_refused_by_name(
    service: InvoiceService, db_session: Session
) -> None:
    """Residual R12, closed. This test used to assert the opposite and was right to:
    `customers.partita_iva` accepted only eleven digits, so a foreign VAT could not even
    be stored, and the slice declared foreign customers out of scope rather than issuing
    a file the SdI would reject.

    All four of those layers are gone -- the Italian shape rule now applies only to an
    Italian customer, `check_party_exportable` no longer refuses on `nazione`, `Provincia`
    is omitted where there is none, and `IdPaese` is read from the customer instead of
    being hard-coded to `IT`. Inverted rather than deleted, so that the change of decision
    is visible in the file that recorded the old one.

    A German customer with no SDI code and no PEC: exactly the shape that was
    unrepresentable, and exactly the shape a European client has.
    """
    customer_id = _customer(db_session, nazione="DE", codice_sdi=None, pec=None, provincia="")
    issued = service.issue(_draft(service, customer_id), InvoiceIssue(), ADMIN)

    assert issued.stato == "emessa"
    assert issued.numero is not None, "una fattura estera consuma un numero come le altre"


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
