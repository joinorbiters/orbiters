"""**Criterion 3.** The search uses its indexes, measured on the plan and not on the clock.

A good time on a fast machine hides a sequential scan; a plan assertion does not. And a
plan assertion on a small table is meaningless -- Postgres picks a sequential scan on a
table of a few pages because it *is* the cheapest plan -- so this is the one test that pays
for the inflated corpus: every searched table at 50 000 rows -- all five of them, since
Task C12 added the invoice branch.

Note the difference from spec §7.3, which forbids asserting on the plan for `deals`. That
exemption is about the *dashboard* queries on the *reference* corpus, where `deals` holds
two thousand rows. Here `deals` holds fifty thousand like every other table, so the
assertion is made. Keeping the two straight is why this paragraph exists.

**What is explained is what production runs, not a hand-written lookalike.** Every
statement a branch emits is captured off the engine with a `before_cursor_execute`
listener and explained exactly as it was sent, parameters included. The scored query, the
bounded count, and the deal branch's label lookup are therefore all covered, and a
repository that stopped using its `LIMIT` cannot pass by having a test that never saw it.

**`VACUUM (ANALYZE)`, not `ANALYZE`, and this is the finding this file exists to record.**
A GIN index keeps its planner statistics -- entry pages, data pages, entry count -- in its
own metapage, and `ginGetStats` reads them at plan time. `ANALYZE` does not write them;
only `VACUUM` does. An index created by `create_all` on an empty table and then bulk-loaded
therefore reports "no statistics" until something vacuums it, and `gincostestimate` falls
back to an estimate an order of magnitude too high: measured here, the same
`Bitmap Index Scan on ix_customers_ragione_sociale_trgm` is costed at 1990.43 before the
vacuum and 12.83 after. Before it, Postgres reads the four-way `BitmapOr` on `customers`
as more expensive than reading the whole table and falls back to a `Parallel Seq Scan` for
*every* term, including one matching no rows at all; the estimates also drift mid-session
as autovacuum catches up, so the plan for one term changes between two identical
`EXPLAIN`s. In production autovacuum does this within minutes of any load; a benchmark that
skips it measures a state the database does not stay in. With the vacuum, the planner is
left entirely free -- no `enable_seqscan = off` anywhere in this file -- and picks the
trigram indexes for all four branches, on every term tried, in a plan that is stable across
repeats.

That freedom is what makes the assertions falsifiable, and two tests prove they are rather
than assume it: one drops a trigram index inside a savepoint and requires the assertion to
fail, and one runs it against `lower(col) LIKE '%…%'` -- a predicate the trigram indexes
cannot serve -- and requires it to fail there too. An assertion that also passes without
the index is not measuring the index.

Measured on this corpus (50 000 rows per table, Postgres 17), `search_everything` end to
end: 20-25 ms for a term matching nothing, 51-90 ms for the three-character term below,
64-82 ms for the twelve-character one, and 367-379 ms for `'ing'`, which the generator's
ten-word vocabulary makes match 9 575 customers, 4 951 deals and 4 969 documents -- a fifth
of the corpus. That last figure is over §7.3's 300 ms and is not a plan defect: the index
is used there too, and what costs the time is scoring and ordering nineteen thousand rows
that genuinely contain the term. It is asserted for what it is instead -- the bounded count
stays cheap -- and the budget is asserted on the two term lengths §16 actually names.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from corpus import INFLATED, build_corpus
from sqlalchemy import Engine, delete, event, func, select, text
from sqlalchemy.orm import Session

from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db import session_factory
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.people.models import Person
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.search.repository import (
    CUSTOMER_FIELDS,
    DEAL_FIELDS,
    DOCUMENT_FIELDS,
    INVOICE_FIELDS,
    PERSON_FIELDS,
    SearchRepository,
)
from pigrocrm.core.search.schemas import COUNT_CEILING, PER_CLASS_LIMIT, SearchQuery
from pigrocrm.core.search.scoring import ScoredField
from pigrocrm.core.search.service import SearchService

pytestmark = pytest.mark.slow

# Spec §16: "per un termine di 3 caratteri e per uno di 12". Three characters is the
# shortest a trigram index can serve, and the shortest the palette will send (§8.2).
#
# Both terms are chosen for their selectivity, and the numbers are part of the test rather
# than an accident of it: on this corpus "345" matches 201 customers, 200 people, 200 deals
# and 200 documents -- it is the fragment of a VAT number, a fiscal code and a generated
# suffix all at once, so it exercises every branch with real hits -- and "Ingegneria 4"
# matches 1 059 deals and 1 040 documents. A term matching a fifth of a table is not a
# search term, it is a category, and Postgres is right to scan for it; that case is
# measured separately below rather than asserted against the budget.
_TERM_SHORT = "345"
_TERM_LONG = "Ingegneria 4"
# The invoice branch cannot be probed with `_TERM_SHORT`, and the reason is the branch's
# own design rather than an inconvenience: `parse_fiscal_number("345")` is `(None, 345)`,
# so a purely numeric term takes the *equality* path and never touches the trigram index at
# all. Asserting `Bitmap Index Scan on ix_invoices_causale_trgm` for `"345"` would be
# asserting that the exclusivity of the two paths does not work. The equality path is
# measured on its own below, against the index that actually serves it.
_TERM_SHORT_CAUSALE = "Col"
# 9 575 customers, 4 951 deals, 4 969 documents on this corpus: the generator draws company
# names from ten sector words, so any fragment of one of them matches a tenth of everything.
_TERM_UNSELECTIVE = "ing"

# Spec §7.3 and §16: 300 ms for the whole endpoint, and the endpoint is this fan-out plus
# serialisation.
_ENDPOINT_BUDGET_MS = 300

_SEARCHED_TABLES = ("customers", "people", "deals", "documents", "invoices")


class _Branch:
    """One entity's searched surface, with the handle needed to run and to explain it.

    A tuple would do, but four unlabelled positions at every call site is how the model and
    the field set drift apart without the test noticing.
    """

    def __init__(
        self,
        table: str,
        model: Any,
        fields: Sequence[ScoredField],
        method: Callable[[SearchRepository], Callable[[str, int], Any]],
        terms: tuple[str, str] = (_TERM_SHORT, _TERM_LONG),
    ) -> None:
        self.table = table
        self.model = model
        self.fields = fields
        self.method = method
        # (three-character, twelve-character) -- §16 names both lengths. Per branch,
        # because `invoices` reads a purely numeric term as a fiscal number and would
        # never reach its trigram index for `_TERM_SHORT`.
        self.terms = terms

    @property
    def index_names(self) -> tuple[str, ...]:
        """The trigram indexes task A2 declared for this entity, by construction.

        Derived from the table and the field names rather than listed: a renamed index or a
        field added to the searched surface without its index then fails here, which is the
        failure worth having.
        """
        return tuple(f"ix_{self.table}_{field.name}_trgm" for field in self.fields)

    def __repr__(self) -> str:
        return self.table


_BRANCHES = (
    _Branch("customers", Customer, CUSTOMER_FIELDS, lambda repo: repo.customers),
    _Branch("people", Person, PERSON_FIELDS, lambda repo: repo.people),
    _Branch("deals", Deal, DEAL_FIELDS, lambda repo: repo.deals),
    _Branch("documents", Document, DOCUMENT_FIELDS, lambda repo: repo.documents),
    _Branch(
        "invoices",
        Invoice,
        INVOICE_FIELDS,
        lambda repo: repo.invoices,
        terms=(_TERM_SHORT_CAUSALE, _TERM_LONG),
    ),
)


@pytest.fixture(scope="module")
def inflated(db_engine: Engine) -> Iterator[Engine]:
    """50 000 rows per searched table, committed, vacuumed and analysed, removed afterwards.

    Module-scoped and committed: `ANALYZE` and `VACUUM` cannot run inside the savepoint the
    `db_session` fixture holds open, and building the corpus once per test would multiply
    the minute and a half it costs by the number of tests in the file.

    `VACUUM (ANALYZE)` rather than `ANALYZE`: see the module docstring. It is the step that
    gives the GIN indexes their metapage statistics, and without it this whole file measures
    a planner reading "no statistics" as "very expensive". It runs on an `AUTOCOMMIT`
    connection because `VACUUM` cannot run inside a transaction block at all.

    The three pipeline stages the corpus creates are removed too, and only the ones this
    fixture created: every other test in the suite runs inside a transaction that is rolled
    back, so leaving committed rows behind would be the one way this file could change what
    a later test sees.
    """
    factory = session_factory(db_engine)
    with factory() as session:
        pre_existing_stages = set(session.scalars(select(PipelineStage.id)).all())
        build_corpus(session, INFLATED)
        session.commit()
    with db_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for table in _SEARCHED_TABLES:
            connection.execute(text(f"VACUUM (ANALYZE) {table}"))
    try:
        yield db_engine
    finally:
        with factory() as session:
            # Children first: `invoices.customer_id`/`invoices.deal_id`,
            # `people.customer_id` and `deals.customer_id` reference `customers`,
            # `documents` references both, and `deals` references a stage. Invoices lead
            # because they are the only table referencing `deals`.
            session.execute(delete(Invoice))
            session.execute(delete(Document))
            session.execute(delete(Deal))
            session.execute(delete(Person))
            session.execute(delete(Customer))
            session.execute(
                delete(PipelineStage).where(PipelineStage.id.notin_(pre_existing_stages))
            )
            session.commit()


@pytest.fixture
def inflated_session(inflated: Engine) -> Iterator[Session]:
    """A plain session on the committed corpus.

    Not `db_session`: that fixture wraps every statement in a savepoint it rolls back, which
    is exactly right for every other test in the suite and wrong here, because the corpus
    this file measures is already committed and nothing in this file writes.
    """
    with session_factory(inflated)() as session:
        yield session


def _capture(session: Session, run: Callable[[], object]) -> list[tuple[str, Any]]:
    """Every statement `run()` sends to the server, verbatim, with its parameters.

    Explaining a hand-written copy of the repository's SQL would measure the copy. This
    listens on the engine instead, so what is explained below is exactly what production
    executes -- including the bounded count and the deal branch's label lookup, neither of
    which any caller can reach as a statement object.
    """
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
    placeholders, which SQLAlchemy's own `text()` would read as literal text and then fail
    to bind. Either way the driver runs its placeholder pass -- SQLAlchemy supplies an empty
    mapping when none is given -- so every literal `%` in a statement written by hand here
    has to be doubled, exactly as it is in the statements SQLAlchemy itself emits.
    """
    sql = f"EXPLAIN (ANALYZE, BUFFERS) {statement}"
    connection = session.connection()
    result = (
        connection.exec_driver_sql(sql)
        if parameters is None
        else connection.exec_driver_sql(sql, parameters)
    )
    return "\n".join(str(row[0]) for row in result)


def _actual_rows(node_line: str) -> int:
    """The row count a plan node really produced, not the one the planner guessed.

    An `EXPLAIN ANALYZE` node carries both -- `(cost=… rows=3684 …) (actual time=… rows=9575
    loops=1)` -- and every assertion in this file that reads a row count means the second.
    Reading the first would make a `LIMIT` assertion pass on the planner's own arithmetic.
    """
    assert "(actual" in node_line, f"node was not measured, only estimated:\n{node_line}"
    measured = node_line.split("(actual", 1)[1]
    return int(measured.split("rows=", 1)[1].split()[0])


def _plans_of(session: Session, branch: _Branch, term: str) -> list[str]:
    repo = SearchRepository(session)
    captured = _capture(session, lambda: branch.method(repo)(term, PER_CLASS_LIMIT))
    assert captured, f"{branch.table} for {term!r} sent no statement at all"
    return [_explain(session, statement, parameters) for statement, parameters in captured]


def _assert_served_by_its_trigram_indexes(branch: _Branch, term: str, plans: list[str]) -> None:
    """The criterion itself, as one function so the falsifiers below can require it to fail.

    Two halves, and neither is enough alone. No sequential scan of any searched table, in
    *any* statement the branch sent -- the count degenerating while the scored query stays
    indexed is precisely the regression a test that looked only at the scored query would
    miss. And every one of the entity's trigram indexes actually read: a four-way `OR` is
    planned as a `BitmapOr` over four index scans, and a single unindexed arm collapses the
    whole thing into one heap scan with a filter, so seeing three of the four named is
    seeing the defect.
    """
    joined = "\n\n".join(plans)
    for table in _SEARCHED_TABLES:
        # "Parallel Seq Scan on customers" contains "Seq Scan on customers", so one
        # substring catches both shapes.
        assert f"Seq Scan on {table}" not in joined, (
            f"{branch.table} for {term!r} sequentially scanned {table}:\n{joined}"
        )
    for index_name in branch.index_names:
        assert f"Bitmap Index Scan on {index_name}" in joined, (
            f"{branch.table} for {term!r} never read {index_name}:\n{joined}"
        )


@pytest.mark.parametrize("length", [0, 1], ids=["3-char", "12-char"])
@pytest.mark.parametrize("branch", _BRANCHES, ids=[branch.table for branch in _BRANCHES])
def test_no_branch_sequentially_scans_a_searched_table(
    inflated_session: Session, branch: _Branch, length: int
) -> None:
    """Parametrised over the *position* in each branch's own pair rather than over two
    module-level constants: §16 asks for a three-character term and a twelve-character one,
    and `invoices` needs a non-numeric three-character term to reach its trigram index at
    all. The ids still say `3-char` and `12-char`, because that is what is being varied."""
    term = branch.terms[length]
    _assert_served_by_its_trigram_indexes(branch, term, _plans_of(inflated_session, branch, term))


@pytest.mark.parametrize("branch", _BRANCHES, ids=[branch.table for branch in _BRANCHES])
def test_the_index_is_used_even_for_a_term_that_matches_a_fifth_of_the_corpus(
    inflated_session: Session, branch: _Branch
) -> None:
    """The unselective case, asserted for the property it can actually have.

    `'ing'` matches 9 575 customers, 4 951 deals and 4 969 documents here, and the fan-out
    takes some 370 ms -- over §7.3's budget, and not because of the plan: the index is still
    what finds the rows, and the time goes on scoring and ordering nineteen thousand rows
    that all genuinely contain the term. Asserting the budget here would be asserting that
    the corpus generator has a large vocabulary.
    """
    _assert_served_by_its_trigram_indexes(
        branch, _TERM_UNSELECTIVE, _plans_of(inflated_session, branch, _TERM_UNSELECTIVE)
    )


def test_the_fiscal_number_path_is_served_by_the_unique_index(
    inflated_session: Session,
) -> None:
    """The invoice branch's *other* half, which no trigram index serves and none should.

    `parse_fiscal_number` turns a numeric term into an equality on `(anno, numero)`, and
    `uq_invoices_anno_numero` -- the partial unique index slice 3 §3 already creates for the
    register's own integrity -- is what makes it a lookup instead of a scan of fifty
    thousand rows. Asserted because "no new index is needed for the number half" is a claim
    about the planner, and a claim about the planner that nobody measured is a guess.

    `"345"` is the term: three characters, purely numeric, and therefore exactly the term
    `test_no_branch_sequentially_scans_a_searched_table` cannot use for this branch.
    """
    branch = next(candidate for candidate in _BRANCHES if candidate.table == "invoices")
    plans = _plans_of(inflated_session, branch, _TERM_SHORT)
    joined = "\n\n".join(plans)
    assert "Seq Scan on invoices" not in joined, joined
    assert "uq_invoices_anno_numero" in joined, joined
    # And the trigram index is *not* read: the two paths are exclusive, and a plan that
    # touched both would mean the branch was doing the work this test says it skips.
    assert "ix_invoices_causale_trgm" not in joined, joined


def test_the_bounded_count_stops_at_the_ceiling(inflated_session: Session) -> None:
    """The `LIMIT 201` inside the count subquery is what keeps a term matching 9 575 rows as
    cheap as one matching two.

    The assertion is on the `Limit` node's *actual* row count, not on the SQL text: `rows=`
    on an `EXPLAIN ANALYZE` node is what the node really produced, so `rows=201` says the
    scan stopped after 201 rows rather than that the output was capped afterwards. The
    matching set is counted independently first, because `rows=201` would also be what a
    full read of a 201-row match set looked like, and then the assertion would be about
    nothing.
    """
    repo = SearchRepository(inflated_session)
    matching = inflated_session.scalar(
        select(func.count())
        .select_from(Customer)
        .where(*repo._predicate(Customer, CUSTOMER_FIELDS, _TERM_UNSELECTIVE))
    )
    assert matching is not None and matching > COUNT_CEILING * 10, (
        f"{_TERM_UNSELECTIVE!r} matches only {matching} customers, which is not enough for "
        "this test to be about the ceiling at all"
    )

    plans = _plans_of(inflated_session, _BRANCHES[0], _TERM_UNSELECTIVE)
    limits = [
        _actual_rows(line)
        for plan in plans
        for line in plan.splitlines()
        if line.strip().startswith(("Limit", "->  Limit"))
    ]
    assert COUNT_CEILING + 1 in limits, (
        f"no Limit node stopped at {COUNT_CEILING + 1} rows while {matching} customers "
        f"matched {_TERM_UNSELECTIVE!r}; the counted limits were {limits}:\n" + "\n\n".join(plans)
    )


def test_the_ranking_and_the_truncation_both_happen_in_the_database(
    inflated_session: Session,
) -> None:
    """Task A7's "one SQL expression", measured instead of restated.

    A score computed in Python could not appear in a `Sort Key`, and a page taken in Python
    would mean the scan node handing every matching row to the client. Both are asserted on
    the executed plan: the sort key names `word_similarity`, and the scan produced far more
    rows than the limit while the top node produced exactly the limit.
    """
    branch = _BRANCHES[0]
    plans = _plans_of(inflated_session, branch, _TERM_UNSELECTIVE)
    scored = next((plan for plan in plans if "Sort Key:" in plan), None)
    assert scored is not None, "no statement sorted anything:\n" + "\n\n".join(plans)

    sort_key = next(line for line in scored.splitlines() if "Sort Key:" in line)
    assert "word_similarity" in sort_key, (
        "the §8.5 score is not what the database ordered by; it was computed somewhere "
        f"else:\n{sort_key}"
    )

    heap = next(line for line in scored.splitlines() if "Bitmap Heap Scan on customers" in line)
    scanned = _actual_rows(heap)
    top = _actual_rows(scored.splitlines()[0])
    assert scanned > PER_CLASS_LIMIT * 100, (
        f"only {scanned} rows reached the sort, so the truncation cannot be shown:\n{scored}"
    )
    assert top == PER_CLASS_LIMIT, (
        f"the database returned {top} rows for a page of {PER_CLASS_LIMIT}; the tail was "
        f"discarded somewhere else:\n{scored}"
    )


@pytest.mark.parametrize("term", [_TERM_SHORT, _TERM_LONG], ids=["3-char", "12-char"])
def test_the_whole_fan_out_stays_inside_the_endpoint_budget(
    inflated_session: Session, term: str
) -> None:
    """Latency as well as plan. The plan assertion catches the regression that matters; the
    clock catches the one where every branch uses its index and there are simply too many of
    them.

    The median of five samples after a warm-up run, not a single sample: the first statement
    of a session pays for connection warm-up and plan caching, and one sample on a container
    sharing a laptop with a test suite is noise, not a measurement. Measured here: 51-90 ms
    for the three-character term and 64-82 ms for the twelve-character one.
    """
    service = SearchService(inflated_session)
    query = SearchQuery(termine=term)
    actor = Actor.system()
    service.search_everything(query, actor)

    samples = []
    for _ in range(5):
        started = time.perf_counter()
        service.search_everything(query, actor)
        samples.append((time.perf_counter() - started) * 1000)

    median = statistics.median(samples)
    assert median < _ENDPOINT_BUDGET_MS, (
        f"the fan-out took {median:.0f} ms for {term!r} (samples: "
        + ", ".join(f"{sample:.0f}" for sample in samples)
        + ")"
    )


def test_the_assertion_fails_without_the_index(inflated_session: Session) -> None:
    """The test that makes this file worth having.

    A plan assertion that also passes with the index dropped is not measuring the index.
    The drop happens inside a savepoint, so it is undone by a rollback rather than by a
    `CREATE INDEX` in a `finally` that could itself fail and leave the rest of the session
    running against a degraded database. Measured: with
    `ix_customers_ragione_sociale_trgm` gone, the four-way `BitmapOr` cannot be built at all
    and the branch falls back to a `Parallel Seq Scan on customers`, 53.9 ms against 5.0.
    """
    branch = _BRANCHES[0]
    savepoint = inflated_session.begin_nested()
    try:
        inflated_session.execute(text("DROP INDEX ix_customers_ragione_sociale_trgm"))
        plans = _plans_of(inflated_session, branch, _TERM_SHORT)
        with pytest.raises(AssertionError, match="sequentially scanned customers"):
            _assert_served_by_its_trigram_indexes(branch, _TERM_SHORT, plans)
    finally:
        savepoint.rollback()

    # And the index is back, so the falsifier cannot be the reason a later test passes or
    # fails. Asserted rather than trusted: a savepoint that failed to roll back would
    # otherwise be discovered as an unrelated failure somewhere further down the file.
    _assert_served_by_its_trigram_indexes(
        branch, _TERM_SHORT, _plans_of(inflated_session, branch, _TERM_SHORT)
    )


def test_the_assertion_fails_for_a_predicate_the_index_cannot_serve(
    inflated_session: Session,
) -> None:
    """The second falsifier, and the one that says the vacuum is not doing the work.

    Dropping an index proves the assertion notices a missing index. It does not prove the
    assertion notices a *predicate* that cannot use one -- which is the mistake that would
    actually be made, because it is one `lower()` away at every call site. `pg_trgm`
    normalises case internally, so wrapping the column adds nothing and costs the index;
    with every trigram index present and the planner free, this predicate is a sequential
    scan of `customers`, and the assertion says so.
    """
    # `%%`, doubled, even though nothing is bound here: SQLAlchemy hands psycopg an empty
    # parameter mapping rather than no mapping at all, so the driver still runs its
    # placeholder pass and a single `%i` is rejected outright as an unknown placeholder.
    plan = _explain(
        inflated_session,
        "SELECT customers.id FROM customers WHERE customers.deleted_at IS NULL "
        "AND lower(customers.ragione_sociale) LIKE '%%ing%%'",
    )
    with pytest.raises(AssertionError, match="sequentially scanned customers"):
        _assert_served_by_its_trigram_indexes(_BRANCHES[0], _TERM_UNSELECTIVE, [plan])


# --- the global activity feed (slice 6 §6.1, §7.3) -----------------------------------
#
# Not a search branch, and it lives here anyway for the one reason this file exists: a
# plan assertion needs a table big enough that a sequential scan is not simply the
# cheapest plan. `activities` is empty in every other test -- they all roll back -- so the
# rows are planted committed and removed again, exactly as `inflated` does for the four
# searched tables.
#
# The rows carry a `kind` nothing else writes, and the cleanup deletes by that `kind`
# rather than truncating: `activities` is the one table a stray committed row in would be
# invisible to every schema check and visible to every later feed assertion.

_FEED_PROBE_KIND = "feed_plan_probe"
_FEED_PROBE_ROWS = 5_000


@pytest.fixture
def activity_feed_corpus(inflated: Engine) -> Iterator[Session]:
    """`_FEED_PROBE_ROWS` committed activities, analysed, then removed.

    Inserted with one `generate_series` statement rather than through `ActivityService`:
    five thousand ORM flushes would cost more than the corpus this fixture hangs off, and
    nothing about the plan depends on how the rows got there. Distinct `occurred_at` values
    one second apart, so the ordering the index serves is a real ordering and not five
    thousand ties.

    `ANALYZE` and not `VACUUM (ANALYZE)`: the metapage statistics the module docstring is
    about belong to GIN indexes. This one is a B-tree, whose selectivity the planner reads
    from the ordinary column statistics `ANALYZE` writes.
    """
    factory = session_factory(inflated)
    try:
        with factory() as session:
            session.execute(
                text(
                    "INSERT INTO activities "
                    "(id, entity_type, entity_id, kind, actor_type, payload, occurred_at) "
                    "SELECT gen_random_uuid(), 'deal', gen_random_uuid(), :kind, 'system', "
                    "'{}'::jsonb, "
                    "TIMESTAMPTZ '2026-01-01 00:00:00+00' + (g * interval '1 second') "
                    "FROM generate_series(1, :rows) AS g"
                ),
                {"kind": _FEED_PROBE_KIND, "rows": _FEED_PROBE_ROWS},
            )
            session.execute(text("ANALYZE activities"))
            session.commit()
        with factory() as session:
            yield session
    finally:
        with factory() as session:
            session.execute(
                text("DELETE FROM activities WHERE kind = :kind"), {"kind": _FEED_PROBE_KIND}
            )
            session.execute(text("ANALYZE activities"))
            session.commit()


def _feed_plan(session: Session) -> str:
    """The plan of the statement `ActivityRepository.recent` actually sends.

    Captured off the engine rather than written out here, for the reason this whole file
    gives: a hand-written lookalike measures the lookalike, and a repository that lost its
    `ORDER BY` would still pass a test that explained the SQL the test wrote itself.
    """
    captured = _capture(session, lambda: ActivityRepository(session).recent())
    assert len(captured) == 1, captured
    statement, parameters = captured[0]
    return _explain(session, statement, parameters)


def test_the_global_activity_feed_uses_its_own_index(activity_feed_corpus: Session) -> None:
    """§6.1 and §7.3: no `Seq Scan` on `activities`.

    `ix_activities_entity` puts the ordering column third and cannot serve a global feed
    ordered by date, so a dedicated `(occurred_at DESC, id DESC)` index has to exist and
    has to be chosen.
    """
    plan = _feed_plan(activity_feed_corpus)
    assert "ix_activities_recent" in plan, plan
    assert "Seq Scan on activities" not in plan, plan


def test_the_feed_assertion_fails_without_its_index(activity_feed_corpus: Session) -> None:
    """The falsifier, in the same shape as `test_the_assertion_fails_without_the_index`.

    Without it the test above is a claim about five thousand rows that would pass on five,
    where a sequential scan is simply the cheapest plan and the index name never appears
    either. Dropped inside a savepoint so the rollback -- not a `CREATE INDEX` in a
    `finally` that could itself fail -- is what puts it back.
    """
    savepoint = activity_feed_corpus.begin_nested()
    try:
        activity_feed_corpus.execute(text("DROP INDEX ix_activities_recent"))
        degraded = _feed_plan(activity_feed_corpus)
        assert "ix_activities_recent" not in degraded, degraded
        assert "Seq Scan on activities" in degraded, degraded
    finally:
        savepoint.rollback()

    # And it is back, so the falsifier cannot be why a later test passes or fails.
    assert "ix_activities_recent" in _feed_plan(activity_feed_corpus)
