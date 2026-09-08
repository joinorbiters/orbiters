from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.gmail.roster import AddressRoster, EntityRef
from pigrocrm.core.people.models import Person


def _customer(session: Session, *, ragione_sociale: str, email: str | None) -> Customer:
    customer = Customer(ragione_sociale=ragione_sociale, email=email)
    session.add(customer)
    session.flush()
    return customer


def test_roster_collects_both_tables_lowercased_and_deduplicated(db_session: Session) -> None:
    customer = _customer(db_session, ragione_sociale="Acme", email="Info@Acme.IT")
    db_session.add(
        Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id)
    )
    # The same address on a person and on a customer is one address, not two: a `q`
    # that repeats a clause wastes the length budget the 20-address batch depends on.
    db_session.add(
        Person(nome="Bob", cognome="Rossi", email="info@acme.it", customer_id=customer.id)
    )
    db_session.flush()

    assert AddressRoster(db_session).known_addresses() == ("ada@acme.it", "info@acme.it")


def test_roster_ignores_soft_deleted_and_null_addresses(db_session: Session) -> None:
    kept = _customer(db_session, ragione_sociale="Kept", email="kept@example.it")
    gone = _customer(db_session, ragione_sociale="Gone", email="gone@example.it")
    gone.deleted_at = datetime.now(UTC)
    _customer(db_session, ragione_sociale="Blank", email=None)
    db_session.add(
        Person(
            nome="Via",
            cognome="Via",
            email="via@example.it",
            customer_id=kept.id,
            deleted_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    assert AddressRoster(db_session).known_addresses() == ("kept@example.it",)


def test_resolve_returns_every_entity_the_address_touches(
    db_session: Session, seeded_open_stage_id: UUID
) -> None:
    customer = _customer(db_session, ragione_sociale="Acme", email="info@acme.it")
    person = Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=customer.id)
    db_session.add(person)
    db_session.flush()
    deal = Deal(nome="Rinnovo", customer_id=customer.id, pipeline_stage_id=seeded_open_stage_id)
    db_session.add(deal)
    db_session.flush()

    # One email concerns the person, her customer, and that customer's open deals at
    # once. This is why gmail_message_links is many-to-many and not three nullable
    # foreign keys: a single FK would force a choice the data does not support.
    assert set(AddressRoster(db_session).resolve("Ada@Acme.it")) == {
        EntityRef("person", person.id),
        EntityRef("customer", customer.id),
        EntityRef("deal", deal.id),
    }


def test_resolve_ignores_soft_deleted_entities(
    db_session: Session, seeded_open_stage_id: UUID
) -> None:
    """A deleted person, customer or deal is not a reason to file an email against it.
    Without this, archiving a contact would leave their conversations linked to a row
    the rest of the CRM refuses to show, and the link would be unreachable rubbish."""
    live_customer = _customer(db_session, ragione_sociale="Viva", email="shared@acme.it")
    dead_customer = _customer(db_session, ragione_sociale="Morta", email="shared@acme.it")
    dead_customer.deleted_at = datetime.now(UTC)
    dead_person = Person(
        nome="Ex",
        cognome="Collega",
        email="shared@acme.it",
        customer_id=live_customer.id,
        deleted_at=datetime.now(UTC),
    )
    db_session.add(dead_person)
    db_session.flush()
    dead_deal = Deal(
        nome="Chiuso",
        customer_id=live_customer.id,
        pipeline_stage_id=seeded_open_stage_id,
        deleted_at=datetime.now(UTC),
    )
    db_session.add(dead_deal)
    db_session.flush()

    assert AddressRoster(db_session).resolve("shared@acme.it") == (
        EntityRef("customer", live_customer.id),
    )


def test_resolve_does_not_reach_a_deleted_customer_through_a_live_person(
    db_session: Session, seeded_open_stage_id: UUID
) -> None:
    """`people.customer_id` is a foreign key, not a liveness check: it keeps pointing at
    a customer after that customer is archived. Following it without re-checking
    `deleted_at` would file the message against the archived company *and* pull in its
    deals, which is the one path a soft-delete filter on the two direct lookups misses.
    """
    dead_customer = _customer(db_session, ragione_sociale="Archiviata", email=None)
    dead_customer.deleted_at = datetime.now(UTC)
    person = Person(nome="Ada", cognome="Byron", email="ada@acme.it", customer_id=dead_customer.id)
    db_session.add(person)
    db_session.flush()
    db_session.add(
        Deal(
            nome="Vecchio",
            customer_id=dead_customer.id,
            pipeline_stage_id=seeded_open_stage_id,
        )
    )
    db_session.flush()

    assert AddressRoster(db_session).resolve("ada@acme.it") == (EntityRef("person", person.id),)


def test_resolve_is_empty_for_an_address_nobody_owns(db_session: Session) -> None:
    _customer(db_session, ragione_sociale="Acme", email="info@acme.it")
    db_session.flush()

    assert AddressRoster(db_session).resolve("stranger@example.com") == ()


def test_resolve_of_a_blank_address_touches_nothing(db_session: Session) -> None:
    """A message with an empty From is not a message about everybody. `resolve("")`
    must not fall through to a `lower(email) = ''` that would match a row somebody
    saved with an empty string instead of NULL."""
    _customer(db_session, ragione_sociale="Vuoto", email="")
    db_session.flush()

    assert AddressRoster(db_session).resolve("   ") == ()


def test_customers_email_is_indexed_like_people_email(db_session: Session) -> None:
    """people.email has had an index since slice 1; customers.email has not, and the
    relevance resolution queries both on every message. Same query shape, same cost,
    so the same index."""
    columns = {
        tuple(index["column_names"])
        for index in inspect(db_session.get_bind()).get_indexes("customers")
    }
    assert ("email",) in columns
