"""What the global search accepts and returns.

Spec §8.1 fixes the searched fields, §8.5 the ordering and the counting, §8.6 the three
interface states. The shape here is what makes those three states expressible without the
client inferring anything: `totale` is the real count and `totale_e_un_minimo` says
whether it was truncated, so "5 of 500" and "5 of 5" are different responses rather than
the same list of five.
"""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.validation import SafeStr

# Spec §8.3: a trigram index cannot serve a pattern from which no trigram can be
# extracted, so below three characters the search would be a sequential scan; and a
# two-character term on 50 000 customers returns thousands of rows, which is not an answer
# either. The palette says "continua a scrivere" and issues no request; this bound is the
# server-side half of the same rule.
MIN_TERM_LENGTH = 3
# A term longer than this is not a search, and the column being searched is at most 320
# characters anyway (`customers.email`).
MAX_TERM_LENGTH = 100
# Spec §8.5: the palette does not paginate. Five per class plus the real count.
PER_CLASS_LIMIT = 5
# Exact up to here, then declared as a minimum. Implemented as `count(*)` over a subquery
# with `LIMIT 201`: exact when exactness matters, cheap when it does not, never a lie.
COUNT_CEILING = 200

SearchEntity = Literal["customer", "person", "deal", "document", "invoice"]


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    termine: SafeStr = Field(min_length=MIN_TERM_LENGTH, max_length=MAX_TERM_LENGTH)
    limite: int = Field(default=PER_CLASS_LIMIT, ge=1, le=20)


class SearchHit(BaseModel):
    entity: SearchEntity
    id: UUID
    # What the palette renders on the row. Built by the repository from the entity's own
    # identifying columns, never by the frontend concatenating fields -- that would be
    # business logic in the browser.
    etichetta: str
    sottotitolo: str | None
    # `Decimal`, never float: a float score renders as 0.6000000238418579 and would break
    # criterion 4's byte-identical requirement. The bounds match the `Numeric(6, 4)` the
    # SQL expression produces, so a value the expression could not have produced is
    # refused here rather than rounded silently.
    punteggio: Decimal = Field(max_digits=6, decimal_places=4)
    # Which field produced the score. Shown as a hint ("P.IVA", "email") so a match on a
    # column the row does not display is not a mystery.
    campo: str


class SearchGroup(BaseModel):
    entity: SearchEntity
    hits: list[SearchHit]
    # The real count of matching rows, exact up to COUNT_CEILING.
    totale: int
    # True when `totale` is COUNT_CEILING and the real count may be higher. The palette
    # renders "oltre 200" for this case; it never renders "200".
    totale_e_un_minimo: bool


class SearchResults(BaseModel):
    termine: str
    gruppi: list[SearchGroup]
