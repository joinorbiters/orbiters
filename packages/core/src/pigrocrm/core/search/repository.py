"""One branch per searched entity, and nothing that crosses two of them.

The shape of every branch is the same and the repetition is deliberate: a generic
"search any model" helper would need the label rule, the subtitle rule, the field set and
the weight set as parameters, which is four dictionaries keyed by entity plus a dispatch --
strictly more code than four explicit methods, and unreadable at the point where a plan
goes wrong.

`etichetta` and `sottotitolo` are built **here**, from the entity's own columns. Not in
the browser: composing "nome cognome" client-side is business logic in the frontend, and
the whole point of the two-adapter architecture is that an MCP agent sees the same label a
human does.

The floor is applied by repeating the score expression in `WHERE`, not by wrapping the
query in a subquery. Postgres cannot reference a select alias in `WHERE`, and the extra
evaluation costs nothing: `matches_any` has already narrowed the row set through the
trigram index, which is the only place a plan could go wrong.

The count and the hits are two queries over **one** predicate, written once in
`_predicate` and used by both. A card and its drill-through are the same calculation
(Global Constraints); two hand-copied `where` clauses are how they stop being one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, literal, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.people.models import Person
from pigrocrm.core.search.schemas import COUNT_CEILING, SearchEntity, SearchGroup, SearchHit
from pigrocrm.core.search.scoring import (
    SCORE_FLOOR,
    WEIGHT_CODE,
    WEIGHT_EMAIL,
    WEIGHT_IDENTIFYING,
    ScoredField,
    best_field,
    matches_any,
    row_score,
)

# Spec §8.1's searched surface, one tuple per entity. Declaration order is load-bearing
# twice over: `best_field` resolves a tie to the earlier field, so the identifying column
# comes first, and `matches_any` builds its `OR` in this order.
CUSTOMER_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("ragione_sociale", Customer.ragione_sociale, WEIGHT_IDENTIFYING),
    ScoredField("partita_iva", Customer.partita_iva, WEIGHT_CODE),
    ScoredField("codice_fiscale", Customer.codice_fiscale, WEIGHT_CODE),
    ScoredField("email", Customer.email, WEIGHT_EMAIL),
)
PERSON_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("cognome", Person.cognome, WEIGHT_IDENTIFYING),
    ScoredField("nome", Person.nome, WEIGHT_IDENTIFYING),
    ScoredField("email", Person.email, WEIGHT_EMAIL),
)
DEAL_FIELDS: tuple[ScoredField, ...] = (ScoredField("nome", Deal.nome, WEIGHT_IDENTIFYING),)
DOCUMENT_FIELDS: tuple[ScoredField, ...] = (
    ScoredField("titolo", Document.titolo, WEIGHT_IDENTIFYING),
)

# The four models this repository searches all carry `PrimaryKeyMixin`, `TimestampMixin`
# and `SoftDeleteMixin`, which is what lets the shared plumbing name `deleted_at`,
# `updated_at` and `id` without a per-entity accessor. `Any` rather than a Protocol: the
# alternative is a structural type that restates three mixins this package does not own.
_Model = Any


class SearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- shared plumbing -------------------------------------------------------

    def _predicate(
        self, model: _Model, fields: Sequence[ScoredField], term: str
    ) -> tuple[ColumnElement[bool], ...]:
        """What a search result *is*, written once.

        Three clauses, and each is load-bearing. `deleted_at IS NULL` because a soft
        delete is a delete as far as a reader is concerned. `matches_any` because it is
        the indexable half -- the one the nine partial trigram indexes serve. The floor
        because the tail of a trigram match is noise, and a palette that shows noise
        teaches the user to ignore the palette.
        """
        return (
            model.deleted_at.is_(None),
            matches_any(fields, term),
            row_score(fields, term) >= SCORE_FLOOR,
        )

    def _count(self, model: _Model, fields: Sequence[ScoredField], term: str) -> tuple[int, bool]:
        """Exact up to COUNT_CEILING, then declared as a minimum.

        `count(*)` over a subquery with `LIMIT ceiling + 1`: the database stops reading
        once it has 201 rows, so the cost is bounded no matter how many rows match, and
        the answer is exact whenever exactness is what is being shown.
        """
        inner = (
            select(literal(1))
            .select_from(model)
            .where(*self._predicate(model, fields, term))
            .limit(COUNT_CEILING + 1)
            .subquery()
        )
        found = self.session.scalar(select(func.count()).select_from(inner)) or 0
        if found > COUNT_CEILING:
            return COUNT_CEILING, True
        return found, False

    def _scored(
        self, model: _Model, fields: Sequence[ScoredField], term: str, limit: int
    ) -> Select[Any]:
        """`punteggio DESC, updated_at DESC, id DESC`, limited.

        The third key exists because the order must be **total**: without it two runs over
        the same data can return the same set in a different order, and §16 criterion 4
        checks twenty runs for a byte-identical response. The second key is §8.5's own --
        at equal score, what was touched most recently is more likely what is wanted.
        """
        return (
            select(model, row_score(fields, term), best_field(fields, term))
            .where(*self._predicate(model, fields, term))
            .order_by(
                row_score(fields, term).desc(),
                model.updated_at.desc(),
                model.id.desc(),
            )
            .limit(limit)
        )

    def _group(
        self,
        entity: SearchEntity,
        model: _Model,
        fields: Sequence[ScoredField],
        term: str,
        limit: int,
        label: Callable[[Any], str],
        subtitle: Callable[[Any], str | None],
    ) -> SearchGroup:
        rows = self.session.execute(self._scored(model, fields, term, limit)).all()
        totale, is_minimum = self._count(model, fields, term)
        hits = [
            SearchHit(
                entity=entity,
                id=row[0].id,
                etichetta=label(row[0]),
                sottotitolo=subtitle(row[0]),
                punteggio=row[1],
                campo=row[2],
            )
            for row in rows
        ]
        return SearchGroup(entity=entity, hits=hits, totale=totale, totale_e_un_minimo=is_minimum)

    # -- one branch per entity -------------------------------------------------

    def customers(self, term: str, limit: int) -> SearchGroup:
        return self._group(
            "customer",
            Customer,
            CUSTOMER_FIELDS,
            term,
            limit,
            label=lambda row: row.ragione_sociale,
            subtitle=lambda row: row.partita_iva,
        )

    def people(self, term: str, limit: int) -> SearchGroup:
        # `cognome` is nullable, so the label is joined from the parts that exist rather
        # than formatted with a placeholder: "Ludovica" and not "Ludovica None".
        return self._group(
            "person",
            Person,
            PERSON_FIELDS,
            term,
            limit,
            label=lambda row: " ".join(part for part in (row.nome, row.cognome) if part),
            subtitle=lambda row: row.email,
        )

    def deals(self, term: str, limit: int) -> SearchGroup:
        group = self._group(
            "deal",
            Deal,
            DEAL_FIELDS,
            term,
            limit,
            label=lambda row: row.nome,
            subtitle=lambda row: None,
        )
        return SearchGroup(
            entity=group.entity,
            hits=self._with_customer_names(group.hits),
            totale=group.totale,
            totale_e_un_minimo=group.totale_e_un_minimo,
        )

    def _with_customer_names(self, hits: list[SearchHit]) -> list[SearchHit]:
        """One extra lookup, after the limit, for at most `limit` rows.

        Resolving the customer name inside the scored query would mean a join evaluated
        over every trigram match rather than over the five rows that survive. A `COUNT`
        may cross a join and a `SUM` may not (spec §3); this is neither -- it is a label
        lookup, and it is placed after `LIMIT` so its cost is bounded by the page.
        """
        if not hits:
            return hits
        deal_ids = [hit.id for hit in hits]
        pairs = self.session.execute(
            select(Deal.id, Customer.ragione_sociale)
            .join(Customer, Customer.id == Deal.customer_id)
            .where(Deal.id.in_(deal_ids))
        ).all()
        names: dict[UUID, str] = {row[0]: row[1] for row in pairs}
        return [hit.model_copy(update={"sottotitolo": names.get(hit.id)}) for hit in hits]

    def documents(self, term: str, limit: int) -> SearchGroup:
        return self._group(
            "document",
            Document,
            DOCUMENT_FIELDS,
            term,
            limit,
            label=lambda row: row.titolo,
            subtitle=lambda row: row.tipo,
        )
