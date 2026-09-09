"""Residuo R9's indexes are actually used, measured on the plan and not on the order.

`test_migrations.py` asserts that the thirteen indexes of migration 0022 *exist*, and
`test_sort_cursor.py` asserts that the rows come back in the declared *order*. Neither
asserts a plan, and that gap is exactly what let `dir=desc` sequentially scan every one of
the four tables for as long as it did: an in-memory sort returns the same rows in the same
order as an index scan, so both existing files stayed green while eleven of the thirteen
indexes were dead for half of their traffic.

**Postgres matches ordering pathkeys including nulls placement.** A backward scan of an
ascending `(col, id)` B-tree yields `DESC NULLS FIRST`; it does not satisfy
`DESC NULLS LAST`, and the planner will not use a `NOT NULL` constraint to unify the two.
So `ORDER BY col DESC NULLS LAST, id DESC` on a non-nullable column is a sequential scan
plus a sort, while the identical-by-construction `ORDER BY col DESC, id DESC` is an
`Index Scan Backward`. `people.cognome` is the one column where `NULLS LAST` has to be
spelled out descending, and it is the one column that carries a second, descending index
for it.

**`ANALYZE` is what the statistics need; `VACUUM (ANALYZE)` is what a shared database needs.**
`test_search_plan.py` records that a GIN index keeps its planner statistics in its own
metapage, which only `VACUUM` writes, so a bulk-loaded GIN index reports "no statistics"
until vacuumed. A B-tree keeps nothing equivalent: what the planner costs it with is
`pg_class.reltuples`/`relpages` for the index relation, and `do_analyze_rel` updates those
for every index of the table it analyses. Checked rather than assumed -- these assertions
pass with `ANALYZE` alone on a freshly bulk-loaded corpus, which is what says the B-tree
case is not the GIN case. The fixture still vacuums, for a different reason: in a full
run the corpus is loaded into tables that other modules have filled and emptied, and the
dead tuples they leave change the plan (see `ordered_corpus`).

**The corpus is smaller than `test_search_plan.py`'s.** That file needs 50 000 rows per
table because a `BitmapOr` over four trigram indexes only wins against a parallel
sequential scan at that scale. An ordering does not: `ORDER BY col LIMIT 51` served by an
index reads fifty-one entries whatever the table holds, so the crossover is far below
50 000, and the falsifiers at the bottom of this file prove the margin is real at the scale
actually used -- with the index dropped, these queries stop using it, either by falling back
to a sequential scan or by reading a lesser index under an `Incremental Sort`.

**What is explained is what production runs.** Each statement is captured off the engine
with a `before_cursor_execute` listener and explained exactly as the repository sent it,
parameters included -- so a repository that stopped calling `order_by` cannot pass by
having a test that only ever saw a hand-written lookalike.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from corpus import CorpusScale, build_corpus
from sqlalchemy import Engine, delete, event, select, text
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.customers.repository import CustomerRepository
from pigrocrm.core.customers.schemas import CUSTOMER_SORTS, CustomerListQuery
from pigrocrm.core.db import encode_cursor, session_factory
from pigrocrm.core.db.sort import SortDirection, SortSpec, SortWhitelist
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.deals.schemas import DEAL_SORTS, DealListQuery
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.documents.schemas import DOCUMENT_SORTS, DocumentListQuery
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.people.models import Person
from pigrocrm.core.people.repository import PersonRepository
from pigrocrm.core.people.schemas import PERSON_SORTS, PersonListQuery
from pigrocrm.core.pipeline.models import PipelineStage

# `planner` as well as `slow`: every assertion in this file is about which plan Postgres
# chooses, and that is a property of the machine it runs on. It passed two trunk runs and
# then failed a third on a commit that touched no Python at all (34294151175, the four
# `customers`/`ragione_sociale` cases), on a hosted runner with two cores and different
# memory settings from the box where the margins were measured. CI deselects `planner`;
# preflight runs it, on one known machine, which is the only place the answer means
# anything. ORB-9 covers the family.
pytestmark = [pytest.mark.slow, pytest.mark.planner]

# Twenty thousand rows per ordered table. See the module docstring for why this is not the
# 50 000 of `test_search_plan.py`, and `test_the_assertion_fails_without_the_index` for the
# measurement that says the margin is real here.
#
# `invoices=1` rather than `0`: `build_corpus` bulk-inserts with
# `session.execute(insert(Model), rows)`, which raises on an empty list. Invoices carry no
# sort whitelist, so one row is exactly as useful as none and does not cost a minute.
_SCALE = CorpusScale(customers=20_000, people=20_000, deals=20_000, documents=20_000, invoices=1)

_ORDERED_TABLES = ("customers", "people", "deals", "documents")

# Pages walked before the plan of the *resumed* query is explained. The defect this
# measures is that a keyset written as `col > v OR (col = v AND id > rid) OR col IS NULL`
# lands as a `Filter` rather than an `Index Cond`, so page N re-reads the N-1 pages before
# it. At twenty pages of fifty that is a thousand index entries discarded to return fifty,
# which no amount of noise can hide.
_PAGES = 20
_PAGE_SIZE = 50


@dataclass(frozen=True)
class _Ordered:
    """One entity's ordered `list()`, with the handle needed to run and to explain it."""

    table: str
    whitelist: SortWhitelist
    make_repo: Callable[[Session], Any]
    make_query: Callable[..., Any]

    def __repr__(self) -> str:
        return self.table


_ENTITIES = (
    _Ordered("customers", CUSTOMER_SORTS, CustomerRepository, CustomerListQuery),
    _Ordered("people", PERSON_SORTS, PersonRepository, PersonListQuery),
    _Ordered("deals", DEAL_SORTS, DealRepository, DealListQuery),
    _Ordered("documents", DOCUMENT_SORTS, DocumentRepository, DocumentListQuery),
)

# Every (entity, sort key, direction) the four whitelists admit: 4 x 3 x 2 = 24 cases,
# derived from the whitelists rather than listed, so a key added to one of them without an
# index fails here instead of quietly sorting the table.
_CASES = tuple(
    (entity, spec, direction)
    for entity in _ENTITIES
    for spec in entity.whitelist.specs
    for direction in ("asc", "desc")
)
_CASE_IDS = tuple(f"{entity.table}-{spec.key}-{d}" for entity, spec, d in _CASES)


def _expected_node(entity: _Ordered, spec: SortSpec, direction: SortDirection) -> str:
    """The plan node that must appear, by construction from the ordering contract.

    Ascending, and descending on a non-nullable column, are both served by the ascending
    `(col, id)` index -- forwards and backwards respectively, which is the whole reason the
    whitelist can cost one index per column. A nullable column descending cannot be: a
    backward scan yields `NULLS FIRST`, so `people.cognome` reads its own
    `(cognome DESC NULLS LAST, id DESC)` index forwards.
    """
    if direction == "desc" and spec.nullable:
        return f"Index Scan using ix_{entity.table}_{spec.key}_desc_id"
    ascending_index = f"ix_{entity.table}_{spec.key}_id"
    if direction == "asc":
        return f"Index Scan using {ascending_index}"
    return f"Index Scan Backward using {ascending_index}"


@pytest.fixture(scope="module")
def ordered_corpus(db_engine: Engine) -> Iterator[Engine]:
    """20 000 rows per ordered table, committed and analysed, removed afterwards.

    Module-scoped and committed for the reason `test_search_plan.py` gives: `ANALYZE`
    cannot run inside the savepoint the `db_session` fixture holds open, and a planner with
    no statistics costs a 20 000-row table as though it held ten.

    Plain `ANALYZE` would be enough for the *statistics* -- see the module docstring on why
    a B-tree is not a GIN index -- but the corpus is only fresh when this module runs alone.
    In a whole-directory run the tables arrive carrying the dead tuples of whatever ran
    before (`test_search_plan.py` deletes 50 000 rows per table), and `relpages` of the
    composite indexes are then costed on pages this corpus never wrote: the planner picks
    the narrower single-column index under an `Incremental Sort` and the assertions below
    fail on a plan the production data would never produce. `VACUUM (ANALYZE)` reclaims
    them first. It runs on an `AUTOCOMMIT` connection because `VACUUM` cannot run inside a
    transaction block at all.
    """
    factory = session_factory(db_engine)
    with factory() as session:
        pre_existing_stages = set(session.scalars(select(PipelineStage.id)).all())
        build_corpus(session, _SCALE)
        session.commit()
    with db_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for table in _ORDERED_TABLES:
            connection.execute(text(f"VACUUM (ANALYZE) {table}"))
    try:
        yield db_engine
    finally:
        with factory() as session:
            # Children first, exactly as `test_search_plan.py` orders them: invoices
            # reference deals and customers, documents reference both, people and deals
            # reference customers, and deals reference a stage.
            session.execute(delete(Invoice))
            session.execute(delete(Document))
            session.execute(delete(Deal))
            session.execute(delete(Person))
            session.execute(delete(Customer))
            session.execute(
                delete(PipelineStage).where(PipelineStage.id.notin_(pre_existing_stages))
            )
            session.commit()
        # And reclaim what the deletes left behind, so the next module's planner does not
        # cost these tables on 20 000 dead tuples (see `test_search_plan.py`'s teardown).
        with db_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for table in _ORDERED_TABLES:
                connection.execute(text(f"VACUUM (ANALYZE) {table}"))


@pytest.fixture
def ordered_session(ordered_corpus: Engine) -> Iterator[Session]:
    """A plain session on the committed corpus; nothing in this file writes."""
    with session_factory(ordered_corpus)() as session:
        yield session


def _capture(session: Session, run: Callable[[], object]) -> list[tuple[str, Any]]:
    """Every statement `run()` sends to the server, verbatim, with its parameters."""
    captured: list[tuple[str, Any]] = []

    def listener(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        captured.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", listener)
    try:
        run()
    finally:
        event.remove(bind, "before_cursor_execute", listener)
    return captured


def _explain(session: Session, statement: str, parameters: Any = None) -> str:
    """`EXPLAIN (ANALYZE, BUFFERS)` of a captured statement, in the driver's own paramstyle.

    `exec_driver_sql` and not `text()`: the captured SQL carries psycopg's `%(name)s`
    placeholders, which `text()` would read as literal text and then fail to bind.
    """
    sql = f"EXPLAIN (ANALYZE, BUFFERS) {statement}"
    connection = session.connection()
    result = (
        connection.exec_driver_sql(sql)
        if parameters is None
        else connection.exec_driver_sql(sql, parameters)
    )
    return "\n".join(str(row[0]) for row in result)


def _plan_of(
    session: Session,
    entity: _Ordered,
    spec: SortSpec,
    direction: SortDirection,
    cursor: str | None = None,
) -> str:
    """The plan of the single statement `list()` sends for this ordering."""
    repository = entity.make_repo(session)
    query = entity.make_query(sort=spec.key, dir=direction, limit=_PAGE_SIZE, cursor=cursor)
    captured = _capture(session, lambda: repository.list(query))
    assert len(captured) == 1, (
        f"{entity.table} sorted by {spec.key} sent {len(captured)} statements, not one; "
        "the assertions below would be about whichever one came first"
    )
    statement, parameters = captured[0]
    return _explain(session, statement, parameters)


def _assert_served_by_its_index(
    entity: _Ordered, spec: SortSpec, direction: SortDirection, plan: str
) -> None:
    """The criterion itself, as one function so the falsifiers can require it to fail.

    Two halves. No sequential scan of the ordered table -- which is what a `Sort` node over
    a whole table looks like, and what `dir=desc` did on eleven of the thirteen indexes.
    And the *named* index read in the *right direction*: an assertion that accepted any
    index scan would pass on a plan that read the primary key and sorted afterwards.
    """
    assert f"Seq Scan on {entity.table}" not in plan, (
        f"{entity.table} sorted by {spec.key} {direction} sequentially scanned the table:\n{plan}"
    )
    expected = _expected_node(entity, spec, direction)
    assert expected in plan, (
        f"{entity.table} sorted by {spec.key} {direction} did not read its index as "
        f"{expected!r}:\n{plan}"
    )
    # A `Sort` node anywhere means the index did not supply the ordering, even if it was
    # read for something else. This is the assertion that a `NULLS LAST` mismatch trips.
    assert "Sort Key:" not in plan, (
        f"{entity.table} sorted by {spec.key} {direction} sorted in memory despite reading "
        f"an index:\n{plan}"
    )


@pytest.mark.parametrize(("entity", "spec", "direction"), _CASES, ids=_CASE_IDS)
def test_every_admitted_ordering_is_served_by_an_index_in_both_directions(
    ordered_session: Session, entity: _Ordered, spec: SortSpec, direction: SortDirection
) -> None:
    """The twenty-four orderings the four whitelists admit, each on its own index.

    Twenty-two of them were served by the twelve ascending indexes of migration 0022 only
    in theory: `order_by` spelled `DESC NULLS LAST` on columns that cannot be null, and
    Postgres matched that against no index at all.
    """
    _assert_served_by_its_index(
        entity, spec, direction, _plan_of(ordered_session, entity, spec, direction)
    )


def _walk(
    session: Session, entity: _Ordered, spec: SortSpec, direction: SortDirection, pages: int
) -> str:
    """The cursor that opens page `pages + 1`, obtained by actually paging there.

    Forged rather than walked would be quicker and would test something else: the cursor a
    client replays is the one `next_cursor` handed it, and building one by hand would let
    this file pass with an encoder that produced cursors no repository could consume.
    """
    repository = entity.make_repo(session)
    cursor: str | None = None
    for page in range(pages):
        query = entity.make_query(sort=spec.key, dir=direction, limit=_PAGE_SIZE, cursor=cursor)
        rows = repository.list(query)
        assert len(rows) > _PAGE_SIZE, (
            f"{entity.table} ran out of rows at page {page + 1}; the corpus is too small "
            "for this test to be about a deep page at all"
        )
        last = rows[_PAGE_SIZE - 1]
        cursor = encode_cursor(spec, getattr(last, spec.key), last.id)
    assert cursor is not None
    return cursor


def _rows_removed_by_filter(plan: str) -> int:
    return sum(
        int(line.split("Rows Removed by Filter:", 1)[1].strip())
        for line in plan.splitlines()
        if "Rows Removed by Filter:" in line
    )


@pytest.mark.parametrize(
    ("entity", "spec", "direction"),
    [case for case in _CASES if not case[1].nullable],
    ids=[case_id for case, case_id in zip(_CASES, _CASE_IDS, strict=True) if not case[1].nullable],
)
def test_a_deep_page_seeks_into_the_index_instead_of_filtering_its_way_there(
    ordered_session: Session, entity: _Ordered, spec: SortSpec, direction: SortDirection
) -> None:
    """Page twenty-one costs what page one costs, which is the point of keyset pagination.

    The disjunctive spelling `col > v OR (col = v AND id > rid)` is not an indexable
    condition: Postgres reads it as a `Filter` on top of a scan that starts at the
    beginning of the index, so page N discards (N-1) x 50 entries before returning
    anything -- the same asymptotic cost as the `OFFSET` this module was written to avoid.
    The row-value spelling `(col, id) > (v, rid)` is a single `Index Cond`, and the scan
    starts where the previous page stopped.

    Measured on the executed plan and not on the SQL text: `Rows Removed by Filter` is what
    the node really discarded. Nothing in this corpus is soft-deleted, so the
    `deleted_at IS NULL` every `list()` carries removes nothing, and the count left over is
    the keyset's alone.
    """
    cursor = _walk(ordered_session, entity, spec, direction, _PAGES)
    plan = _plan_of(ordered_session, entity, spec, direction, cursor)

    _assert_served_by_its_index(entity, spec, direction, plan)
    assert "Index Cond:" in plan, (
        f"{entity.table} resumed by {spec.key} {direction} had no index condition at all, "
        f"so the scan began at the start of the index:\n{plan}"
    )
    index_cond = next(line for line in plan.splitlines() if "Index Cond:" in line)
    assert spec.key in index_cond, (
        f"{entity.table} resumed by {spec.key} {direction} seeks on something other than "
        f"its sort column:\n{index_cond}"
    )
    assert _rows_removed_by_filter(plan) == 0, (
        f"{entity.table} resumed by {spec.key} {direction} discarded "
        f"{_rows_removed_by_filter(plan)} rows it had already returned on earlier pages; "
        f"the keyset landed as a filter rather than a seek:\n{plan}"
    )


def test_the_nullable_column_keeps_its_disjunction_and_still_reaches_the_null_tail(
    ordered_session: Session,
) -> None:
    """`people.cognome` is the exception, deliberately and not by omission.

    A row-value comparison on a nullable column is not merely slower, it is *wrong*: SQL
    row comparison with a NULL member yields NULL, so `(cognome, id) > (v, rid)` is never
    true for a person without a surname and the whole null tail -- a fifth of this corpus --
    disappears from an otherwise complete scan. That is the exact failure keyset pagination
    was chosen to avoid, so `cognome` keeps `OR cognome IS NULL` and pays for it with a
    filter. The ordering is still served by an index, which is what this asserts; the
    completeness is asserted in `test_sort_cursor.py`.
    """
    spec = PERSON_SORTS.resolve("cognome")
    entity = next(candidate for candidate in _ENTITIES if candidate.table == "people")
    cursor = _walk(ordered_session, entity, spec, "asc", 2)
    plan = _plan_of(ordered_session, entity, spec, "asc", cursor)

    _assert_served_by_its_index(entity, spec, "asc", plan)
    assert "cognome IS NULL" in plan, (
        "the null tail is no longer reachable from a non-null cursor; without that arm a "
        f"scan by cognome stops at the last surname:\n{plan}"
    )

    without_surname = ordered_session.scalar(
        select(Person.id).where(Person.cognome.is_(None)).limit(1)
    )
    assert without_surname is not None, (
        "the corpus has no person without a surname, so this test is about nothing"
    )


@pytest.mark.parametrize(
    ("entity", "spec", "direction"),
    [
        (_ENTITIES[0], CUSTOMER_SORTS.resolve("ragione_sociale"), "asc"),
        (_ENTITIES[0], CUSTOMER_SORTS.resolve("ragione_sociale"), "desc"),
        (_ENTITIES[1], PERSON_SORTS.resolve("cognome"), "desc"),
    ],
    ids=["customers-asc", "customers-desc", "people-cognome-desc"],
)
def test_the_assertion_fails_without_the_index(
    ordered_session: Session, entity: _Ordered, spec: SortSpec, direction: SortDirection
) -> None:
    """The test that makes this file worth having.

    A plan assertion that also passes with the index dropped is measuring nothing, and at
    20 000 rows rather than 50 000 the margin is the thing most worth checking. Both
    directions of one ascending index are dropped here, and the dedicated descending index
    of the one nullable column -- the three shapes the file asserts.

    The two `customers` cases are also what says the *second* half of the assertion earns
    its place. Dropping `ix_customers_ragione_sociale_id` does not produce a sequential
    scan: slice 1's single-column `ix_customers_ragione_sociale` is still there, so Postgres
    reads it for `ragione_sociale` alone and puts an `Incremental Sort` on top to break the
    ties by `id`. An assertion that only looked for "no sequential scan" would call that a
    pass -- it is an index scan, of the wrong index, with a sort the ordering was supposed
    to remove. Naming the index is what catches it, so the match below admits either
    refusal rather than only the sequential-scan one.

    The drop happens inside a savepoint and is undone by a rollback, rather than by a
    `CREATE INDEX` in a `finally` that could itself fail and leave every later test in this
    module running against a degraded database.
    """
    index = (
        f"ix_{entity.table}_{spec.key}_desc_id"
        if direction == "desc" and spec.nullable
        else f"ix_{entity.table}_{spec.key}_id"
    )
    savepoint = ordered_session.begin_nested()
    try:
        ordered_session.execute(text(f"DROP INDEX {index}"))
        plan = _plan_of(ordered_session, entity, spec, direction)
        with pytest.raises(
            AssertionError, match="sequentially scanned the table|did not read its index"
        ):
            _assert_served_by_its_index(entity, spec, direction, plan)
    finally:
        savepoint.rollback()

    # And the index is back, so the falsifier cannot be why a later test passes or fails.
    _assert_served_by_its_index(
        entity, spec, direction, _plan_of(ordered_session, entity, spec, direction)
    )


def test_the_assertion_fails_for_an_ordering_no_index_can_serve(
    ordered_session: Session,
) -> None:
    """The second falsifier, and the one that says the assertion reads nulls placement.

    Dropping an index proves the assertion notices a missing index. It does not prove it
    notices the mistake actually made, which was an ordering *spelling* no index matches
    while every index was present. `ragione_sociale` is `NOT NULL`, so
    `DESC NULLS LAST` and `DESC` return byte-identical rows -- and only one of them is an
    index scan. This is the defect, reproduced against the live schema.
    """
    plan = _explain(
        ordered_session,
        "SELECT customers.id FROM customers WHERE customers.deleted_at IS NULL "
        "ORDER BY customers.ragione_sociale DESC NULLS LAST, customers.id DESC LIMIT 51",
    )
    with pytest.raises(AssertionError, match="sequentially scanned the table"):
        _assert_served_by_its_index(
            _ENTITIES[0], CUSTOMER_SORTS.resolve("ragione_sociale"), "desc", plan
        )
