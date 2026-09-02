r"""Spec §8.5's score, as a SQL expression.

Computed in the database, not in Python, and that is a decision rather than a shortcut:
the tail of a trigram scan on 50 000 rows is thousands of rows, and ranking in Python
would mean fetching all of them to throw almost all away. Ranking in SQL lets
`ORDER BY … LIMIT` discard the tail before it crosses the wire, which is what makes
criterion 3's 300 ms budget reachable. The cost of the decision is that this expression
*is* the formula: §8.5 is pinned by tests against real Postgres rather than by unit tests
over pure functions.

Three details that are easy to get wrong and expensive to rediscover.

**`similarity()` returns `real`.** It is cast to `numeric` the moment it appears. A float
would violate the project's no-float rule for no benefit and would render as
`0.6000000238418579` in JSON, which also breaks criterion 4's byte-identical requirement.
A `real` cast to `numeric` is exact and deterministic for a given input, and the whole
expression comes back as a `Decimal` at the declared scale. (`sqlalchemy.cast` and
`func.cast` compile identically here -- SQLAlchemy special-cases the name -- so the
spelling is a matter of reading, not of behaviour; verified, not assumed.)

**The prefix arm builds a LIKE pattern, so it escapes.** Without `escape_like`, a term
ending in `_` prefix-matches any character in that position, and the score for
`Rossi_Ingegneria` and `RossiXIngegneria` would be identical. The substring filter has
always escaped; the prefix arm is new here and needs the same treatment. Task A2 measured
that the `ESCAPE` clause costs the trigram indexes nothing -- identical plans node for
node, on all nine columns -- so it stays here exactly as it stands in the four
repositories.

There is no `lower()` around the trigram column anywhere: `similarity()` normalises to
lower case internally (`similarity('Rossi','rossi') = 1`), and wrapping the column would
make the `*_trgm` indexes unusable by the `ILIKE` this module emits (spec §8.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Numeric, case, cast, func, literal, or_
from sqlalchemy.orm.attributes import InstrumentedAttribute

from pigrocrm.core.db import escape_like

SCORE_EXACT = Decimal("1.00")
SCORE_PREFIX = Decimal("0.80")
SCORE_SUBSTRING_FACTOR = Decimal("0.60")
# Rows below this are discarded: the tail of a trigram match is noise, and showing noise
# in a palette teaches the user to ignore it.
SCORE_FLOOR = Decimal("0.20")
# Four places. Two would collapse distinct substring matches into ties and make the
# ordering depend on the third sort key more often than it should.
SCORE_SCALE = 4

WEIGHT_IDENTIFYING = Decimal("1.00")
# A match on a fiscal code is wanted, not incidental: someone typing a VAT fragment knows
# exactly what they are looking for.
WEIGHT_CODE = Decimal("1.00")
WEIGHT_EMAIL = Decimal("0.90")
WEIGHT_CAUSALE = Decimal("0.80")

# Precision 6 leaves room the formula cannot actually use (its ceiling is 1.0000) and
# costs nothing; the scale is the one that matters, and it is the same number the
# `SearchHit.punteggio` field declares.
_NUMERIC = Numeric(6, SCORE_SCALE)
_ZERO = literal(Decimal("0.0000"), type_=_NUMERIC)


@dataclass(frozen=True)
class ScoredField:
    """One column that a search term is matched against, with its §8.5 weight.

    The column is an `InstrumentedAttribute` rather than a name: a name would have to be
    resolved by `getattr` somewhere, and the whole point of declaring the searchable
    surface in code is that no caller-supplied string ever reaches a SQL expression.
    """

    name: str
    # `Any` as the attribute's own type parameter: the searched columns are `str` and
    # `str | None` across five entities, and pinning either here would make the other an
    # error at every declaration site in task A8's repository.
    column: InstrumentedAttribute[Any]
    weight: Decimal


def _like_prefix(term: str) -> str:
    return f"{escape_like(term.lower())}%"


def _like_anywhere(term: str) -> str:
    return f"%{escape_like(term.lower())}%"


def field_score(field: ScoredField, term: str) -> ColumnElement[Decimal]:
    """`peso × punteggio_campo`, or `0` when the column is NULL or does not match.

    Zero rather than NULL for the miss case: `GREATEST` ignores NULLs, but a row whose
    every field were NULL would score NULL, and in Postgres a NULL sorts *first* under
    `ORDER BY … DESC` -- so the rows that match nothing would head the palette.
    """
    column = field.column
    weight = literal(field.weight, type_=_NUMERIC)
    return func.coalesce(
        case(
            (column.is_(None), _ZERO),
            (func.lower(column) == term.lower(), literal(SCORE_EXACT, type_=_NUMERIC)),
            (
                func.lower(column).like(_like_prefix(term), escape="\\"),
                literal(SCORE_PREFIX, type_=_NUMERIC),
            ),
            else_=func.round(
                literal(SCORE_SUBSTRING_FACTOR, type_=_NUMERIC)
                * cast(func.similarity(column, term), _NUMERIC),
                SCORE_SCALE,
            ),
        )
        * weight,
        _ZERO,
    ).label(f"score_{field.name}")


def row_score(fields: Sequence[ScoredField], term: str) -> ColumnElement[Decimal]:
    """`max(peso × punteggio_campo)` over the fields that matched.

    The maximum and not the sum: summing would let two mediocre matches outrank one exact
    one, and would rank a row higher merely for having more populated columns -- an order
    no user could explain to themselves.
    """
    scores = [field_score(field, term) for field in fields]
    if len(scores) == 1:
        # `greatest` of one argument is legal in Postgres, but writing it would put a
        # function call around every single-field entity's score for nothing.
        return func.round(scores[0], SCORE_SCALE).label("punteggio")
    return func.round(func.greatest(*scores), SCORE_SCALE).label("punteggio")


def best_field(fields: Sequence[ScoredField], term: str) -> ColumnElement[str]:
    """The name of the field that produced the row score.

    Declared in the same order as `fields`, so ties resolve to the earlier field -- which
    is the identifying one by convention, and which keeps the output deterministic
    (criterion 4). `CASE` evaluates its arms in written order, which is what makes that a
    guarantee rather than a habit of the planner.
    """
    top = row_score(fields, term)
    branches = [
        (func.round(field_score(field, term), SCORE_SCALE) == top, literal(field.name))
        for field in fields
    ]
    return case(*branches, else_=literal(fields[0].name)).label("campo")


def matches_any(fields: Sequence[ScoredField], term: str) -> ColumnElement[bool]:
    """The filter, kept separate from the score so the planner sees a plain
    `ILIKE '%…%'` on an indexed column.

    This is the predicate the `*_trgm` indexes of task A2 serve. Filtering on
    `row_score(...) >= floor` instead would be correct and would also be a sequential scan
    on every searched table, because a `CASE` over `similarity()` is not an indexable
    expression.
    """
    pattern = _like_anywhere(term)
    return or_(*(field.column.ilike(pattern, escape="\\") for field in fields))
