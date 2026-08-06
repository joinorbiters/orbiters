from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pigrocrm.core.db import escape_like
from pigrocrm.core.people.models import Person
from pigrocrm.core.people.schemas import PersonListQuery


class PersonRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, person_id: UUID, *, include_deleted: bool = False) -> Person | None:
        person = self.session.get(Person, person_id)
        if person is None:
            return None
        if person.deleted_at is not None and not include_deleted:
            return None
        return person

    def add(self, person: Person) -> Person:
        self.session.add(person)
        self.session.flush()
        return person

    def list(self, query: PersonListQuery) -> list[Person]:
        stmt = select(Person).where(Person.deleted_at.is_(None))

        if query.search:
            # escape_like neutralizes "%"/"_"/"\" in the *user's* term before it is
            # wrapped in the wildcard "%...%" this method builds -- otherwise a
            # literal "_" in the search box matches "any one character" and a
            # trailing "\" combines with the wildcard just after it into an
            # accidental escape sequence that swallows the match entirely. escape="\\"
            # states explicitly which character escape_like used, rather than relying
            # on ILIKE's default. Mirrors CustomerRepository.list exactly.
            like = f"%{escape_like(query.search.lower())}%"
            stmt = stmt.where(
                or_(
                    Person.nome.ilike(like, escape="\\"),
                    Person.cognome.ilike(like, escape="\\"),
                    Person.email.ilike(like, escape="\\"),
                )
            )
        if query.customer_id:
            stmt = stmt.where(Person.customer_id == query.customer_id)
        if query.custom:
            # JSONB containment, served by the GIN index.
            stmt = stmt.where(Person.custom_fields.contains(query.custom))
        if query.cursor:
            stmt = stmt.where(Person.id > query.cursor)

        # Keyset pagination on a UUIDv7 id: ordered by creation, stable under inserts.
        return list(self.session.execute(stmt.order_by(Person.id).limit(query.limit + 1)).scalars())
