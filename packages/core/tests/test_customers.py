import pytest
from sqlalchemy import Column, Integer, Table
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate, CustomerListQuery, CustomerUpdate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.db import Base
from pigrocrm.core.errors import NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")
READONLY = Actor(id=None, type="user", role="readonly")


def test_create_requires_only_the_company_name(db_session: Session) -> None:
    customer = CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME Srl"), ADMIN)
    assert customer.ragione_sociale == "ACME Srl"
    assert customer.nazione == "IT", "Italian default, because that is the target market"
    assert customer.custom_fields == {}


def test_fiscal_fields_are_first_class_columns(db_session: Session) -> None:
    """Acme guessed among vat_number / vat / piva because these were external
    attributes. Here they are columns, so slice 3 can build FatturaPA on them."""
    customer = CustomerService(db_session).create(
        CustomerCreate(
            ragione_sociale="ACME Srl",
            partita_iva="12345678901",
            codice_fiscale="RSSMRA80A01H501U",
            codice_sdi="ABCDEFG",
            pec="acme@pec.it",
        ),
        ADMIN,
    )
    assert customer.partita_iva == "12345678901"
    assert customer.codice_sdi == "ABCDEFG"


@pytest.mark.parametrize("bad", ["1234567890", "123456789012", "1234567890A"])
def test_partita_iva_must_be_eleven_digits(db_session: Session, bad: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        CustomerService(db_session).create(
            CustomerCreate(ragione_sociale="X", partita_iva=bad), ADMIN
        )
    assert exc.value.details["field"] == "partita_iva"


def test_codice_sdi_must_be_seven_characters(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as exc:
        CustomerService(db_session).create(
            CustomerCreate(ragione_sociale="X", codice_sdi="ABC"), ADMIN
        )
    assert exc.value.details["field"] == "codice_sdi"


def test_custom_fields_are_validated_against_the_definitions(db_session: Session) -> None:
    FieldDefinitionService(db_session).create(
        FieldDefinitionCreate(
            entity_type="customer",
            key="stato_cliente",
            label="Stato",
            field_type="select",
            options=["attivo", "sospeso"],
        ),
        ADMIN,
    )
    service = CustomerService(db_session)

    ok = service.create(
        CustomerCreate(ragione_sociale="ACME", custom_fields={"stato_cliente": "attivo"}), ADMIN
    )
    assert ok.custom_fields == {"stato_cliente": "attivo"}

    with pytest.raises(ValidationFailed):
        service.create(
            CustomerCreate(ragione_sociale="B", custom_fields={"stato_cliente": "chiuso"}), ADMIN
        )


def test_undefined_custom_field_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValidationFailed):
        CustomerService(db_session).create(
            CustomerCreate(ragione_sociale="X", custom_fields={"inventato": "v"}), ADMIN
        )


def test_create_records_a_timeline_entry_naming_the_actor(db_session: Session) -> None:
    from pigrocrm.core.activities.service import ActivityService

    customer = CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    entries = ActivityService(db_session).timeline("customer", customer.id)
    assert [e.kind for e in entries] == ["created"]
    assert entries[0].actor_type == "system"


def test_update_records_only_the_changed_fields(db_session: Session) -> None:
    from pigrocrm.core.activities.service import ActivityService

    service = CustomerService(db_session)
    customer = service.create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    service.update(customer.id, CustomerUpdate(telefono="0212345"), ADMIN)

    updates = [
        e
        for e in ActivityService(db_session).timeline("customer", customer.id)
        if e.kind == "updated"
    ]
    assert updates[0].payload["changed"] == ["telefono"]


def test_readonly_cannot_write_but_can_read(db_session: Session) -> None:
    service = CustomerService(db_session)
    customer = service.create(CustomerCreate(ragione_sociale="ACME"), ADMIN)

    assert service.get(customer.id, READONLY).id == customer.id
    with pytest.raises(PermissionDenied):
        service.create(CustomerCreate(ragione_sociale="B"), READONLY)


def test_collaborator_can_write(db_session: Session) -> None:
    assert CustomerService(db_session).create(CustomerCreate(ragione_sociale="ACME"), COLLAB)


def test_soft_delete_hides_the_row_without_removing_it(db_session: Session) -> None:
    service = CustomerService(db_session)
    customer = service.create(CustomerCreate(ragione_sociale="ACME"), ADMIN)
    service.soft_delete(customer.id, ADMIN)

    with pytest.raises(NotFound):
        service.get(customer.id, ADMIN)
    assert service.list(CustomerListQuery(), ADMIN).items == []
    assert service.restore(customer.id, ADMIN).ragione_sociale == "ACME"


def test_soft_delete_fails_loudly_if_the_deals_table_lacks_the_expected_column(
    db_session: Session,
) -> None:
    """Returning 0 from `count_active_deals` is only correct when `deals` does not
    exist yet. If it exists but without the expected column, that is a bug in this
    code, not "no deals" -- silently returning 0 would let `soft_delete` remove a
    customer that might still have deals attached. Registers a bare `deals` table
    directly in `Base.metadata` (no `customer_id`) rather than waiting for the real
    table to exist; this only exercises the Python-side column lookup, never issues
    SQL against it, so no real DDL is needed. Mirrors
    `test_delete_fails_loudly_if_the_deals_table_lacks_the_expected_column` in
    test_pipeline.py."""
    fake_deals = Table("deals", Base.metadata, Column("id", Integer, primary_key=True))
    try:
        service = CustomerService(db_session)
        customer = service.create(CustomerCreate(ragione_sociale="ACME"), ADMIN)

        with pytest.raises(RuntimeError):
            service.soft_delete(customer.id, ADMIN)
    finally:
        Base.metadata.remove(fake_deals)


def test_search_matches_name_vat_and_email(db_session: Session) -> None:
    service = CustomerService(db_session)
    service.create(
        CustomerCreate(ragione_sociale="ACME Srl", partita_iva="12345678901", email="a@acme.it"),
        ADMIN,
    )
    service.create(CustomerCreate(ragione_sociale="Beta Spa"), ADMIN)

    assert len(service.list(CustomerListQuery(search="acme"), ADMIN).items) == 1
    assert len(service.list(CustomerListQuery(search="12345678901"), ADMIN).items) == 1
    assert len(service.list(CustomerListQuery(search="a@acme.it"), ADMIN).items) == 1
    assert len(service.list(CustomerListQuery(search="zzz"), ADMIN).items) == 0


def test_filter_by_custom_field_uses_jsonb_containment(db_session: Session) -> None:
    FieldDefinitionService(db_session).create(
        FieldDefinitionCreate(
            entity_type="customer", key="settore", label="Settore", field_type="text"
        ),
        ADMIN,
    )
    service = CustomerService(db_session)
    service.create(CustomerCreate(ragione_sociale="A", custom_fields={"settore": "IT"}), ADMIN)
    service.create(CustomerCreate(ragione_sociale="B", custom_fields={"settore": "Retail"}), ADMIN)

    page = service.list(CustomerListQuery(custom={"settore": "IT"}), ADMIN)
    assert [c.ragione_sociale for c in page.items] == ["A"]


def test_pagination_returns_a_cursor_and_does_not_repeat_rows(db_session: Session) -> None:
    service = CustomerService(db_session)
    for index in range(5):
        service.create(CustomerCreate(ragione_sociale=f"Cliente {index:02d}"), ADMIN)

    first = service.list(CustomerListQuery(limit=2), ADMIN)
    assert len(first.items) == 2
    assert first.next_cursor is not None

    second = service.list(CustomerListQuery(limit=2, cursor=first.next_cursor), ADMIN)
    assert {c.id for c in first.items}.isdisjoint({c.id for c in second.items})


def test_last_page_has_no_cursor(db_session: Session) -> None:
    service = CustomerService(db_session)
    service.create(CustomerCreate(ragione_sociale="Solo"), ADMIN)
    assert service.list(CustomerListQuery(limit=10), ADMIN).next_cursor is None


def test_get_missing_customer_raises_not_found(db_session: Session) -> None:
    from uuid import uuid4

    with pytest.raises(NotFound):
        CustomerService(db_session).get(uuid4(), ADMIN)
