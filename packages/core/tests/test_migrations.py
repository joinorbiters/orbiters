from datetime import date
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.command import upgrade
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

import pigrocrm.core.models_registry  # noqa: F401
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import Base

CORE_ROOT = Path(__file__).resolve().parents[1]

# Autogenerate is known to silently omit exactly these shapes: a unique index over a SQL
# expression rather than a bare column (`uq_users_email_lower`), a plain unique index on a
# nullable column (`uq_pipeline_stage_code`), a GIN index -- losing one of those turns a
# JSONB containment filter into a sequential scan -- and, from slice 6, a *partial* GIN
# index over an operator class (`*_trgm`). Named explicitly here so a regression fails
# with the missing index's name instead of a generic metadata diff.
HAND_MAINTAINED_INDEXES = {
    "uq_users_email_lower",
    "uq_pipeline_stage_code",
    "ix_customers_custom_fields",
    "ix_people_custom_fields",
    "ix_deals_custom_fields",
    "uq_invoices_anno_numero",
    "ix_invoices_custom_fields",
    # Same shape as `uq_pipeline_stage_code`: a plain unique index on a nullable
    # column, one of the two shapes autogenerate is known to silently omit.
    "uq_cost_categories_code",
    "ix_time_entries_custom_fields",
    "ix_costs_custom_fields",
    # Same shape as `uq_users_email_lower`: a functional unique index over lower(nome).
    "uq_cost_categories_nome",
    # Slice 6, migration 0021. A *partial* GIN index over an operator class is a fourth
    # shape autogenerate handles poorly, and nine trigram indexes omitted in silence are
    # nine sequential scans that come back a month later.
    "ix_customers_ragione_sociale_trgm",
    "ix_customers_partita_iva_trgm",
    "ix_customers_codice_fiscale_trgm",
    "ix_customers_email_trgm",
    "ix_people_nome_trgm",
    "ix_people_cognome_trgm",
    "ix_people_email_trgm",
    "ix_deals_nome_trgm",
    "ix_documents_titolo_trgm",
    # Slice 6, migration 0022. Residuo R9's other half: one `(column, id)` B-tree per
    # admitted sort key, plus the one descending index the single nullable sort column
    # costs. The twelve ascending ones are ordinary composite indexes that autogenerate
    # handles correctly -- they are listed anyway, because a composite index dropped in
    # silence is the same sequential scan as a GIN index dropped in silence, and the
    # thirteenth is an expression index over `DESC NULLS LAST` that autogenerate cannot
    # compare at all.
    "ix_customers_created_at_id",
    "ix_customers_updated_at_id",
    "ix_customers_ragione_sociale_id",
    "ix_people_created_at_id",
    "ix_people_updated_at_id",
    "ix_people_cognome_id",
    "ix_people_cognome_desc_id",
    "ix_deals_created_at_id",
    "ix_deals_updated_at_id",
    "ix_deals_nome_id",
    "ix_documents_created_at_id",
    "ix_documents_updated_at_id",
    "ix_documents_titolo_id",
    # Slice 6, migration 0023. The two period-filter columns of §4.1. Both are ordinary
    # single-column B-trees that autogenerate handles correctly; they are listed here for
    # the same reason the twelve ascending sort indexes are, which is that an index
    # dropped in silence is a sequential scan on every dashboard load, and this file is
    # where a missing index is supposed to fail by name.
    "ix_deals_chiuso_il",
    "ix_documents_stato_dal",
    # Slice 6, migration 0024. A *descending* expression index over two columns, which is
    # the fifth shape autogenerate cannot compare: `compare_metadata` does not look at
    # index expressions at all, so this one would be dropped in total silence and the
    # global activity feed would go back to sorting the whole table on every dashboard
    # load. Its declared shape is asserted below, on `indexdef` text.
    "ix_activities_recent",
}

TRGM_INDEX_NAMES = frozenset(n for n in HAND_MAINTAINED_INDEXES if n.endswith("_trgm"))


def _alembic_config(url: str) -> Config:
    config = Config(str(CORE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(CORE_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migrations_produce_exactly_the_models_schema() -> None:
    """A drift between migrations and models is invisible until deploy day, when the
    application meets a table the code does not expect."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, Base.metadata)
        engine.dispose()

    assert diff == [], f"migrations and models disagree: {diff}"


def test_every_table_the_slice_needs_exists() -> None:
    expected = {
        "users",
        "personal_access_tokens",
        "refresh_tokens",
        "field_definitions",
        "pipeline_stages",
        "activities",
        "customers",
        "people",
        "deals",
        "fiscal_profile",
        "invoices",
        "invoice_lines",
        "invoice_counters",
        "time_entries",
        "costs",
        "cost_categories",
        "period_locks",
        "google_accounts",
        "google_oauth_states",
        "gmail_messages",
        "gmail_message_links",
        "email_drafts",
        "payment_reminders",
        "automation_config",
    }
    assert expected <= set(Base.metadata.tables)


def test_hand_maintained_indexes_survive_the_migration() -> None:
    """`compare_metadata` (above) already proves migrations and models agree overall, but
    a diff report names a mismatch, not a silent gap -- this test names the exact indexes
    that autogenerate is known to drop, so a future regression fails as a missing name
    instead of a generic diff someone has to go decode."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            ).all()
        engine.dispose()

    indexes = {row.indexname: row.indexdef for row in rows}

    missing = HAND_MAINTAINED_INDEXES - set(indexes)
    assert not missing, f"migration did not create these indexes: {missing}"

    # Postgres normalizes the expression to `lower((email)::text)` -- the explicit cast is
    # its own reflection detail, not something to pin exactly; what matters is that this is
    # still a functional index over `email` through `lower()`, not a plain column index.
    email_lower_def = indexes["uq_users_email_lower"]
    assert "UNIQUE" in email_lower_def, "uq_users_email_lower must be a unique index"
    assert "lower(" in email_lower_def and "email" in email_lower_def, (
        f"uq_users_email_lower is not a functional index over lower(email): {email_lower_def}"
    )

    for gin_index in (
        "ix_customers_custom_fields",
        "ix_people_custom_fields",
        "ix_deals_custom_fields",
        "ix_time_entries_custom_fields",
        "ix_costs_custom_fields",
    ):
        assert "USING gin" in indexes[gin_index], f"{gin_index} was not created as a GIN index"

    assert "USING gin" in indexes["ix_invoices_custom_fields"], (
        "ix_invoices_custom_fields was not created as a GIN index"
    )

    cost_categories_code_def = indexes["uq_cost_categories_code"]
    assert "UNIQUE" in cost_categories_code_def, "uq_cost_categories_code must be a unique index"

    cost_categories_nome_def = indexes["uq_cost_categories_nome"]
    assert "UNIQUE" in cost_categories_nome_def, "uq_cost_categories_nome must be a unique index"
    assert "lower(" in cost_categories_nome_def and "nome" in cost_categories_nome_def, (
        f"uq_cost_categories_nome is not a functional index over lower(nome): "
        f"{cost_categories_nome_def}"
    )

    anno_numero_def = indexes["uq_invoices_anno_numero"]
    assert "UNIQUE" in anno_numero_def, "uq_invoices_anno_numero must be a unique index"
    assert "WHERE" in anno_numero_def and "numero IS NOT NULL" in anno_numero_def, (
        "uq_invoices_anno_numero lost its partial predicate, so every unnumbered draft "
        f"is now a duplicate of every other: {anno_numero_def}"
    )


def test_every_trigram_index_is_a_partial_gin_index_over_gin_trgm_ops() -> None:
    """A trigram index created without `gin_trgm_ops` is an ordinary GIN index that
    cannot serve `ILIKE '%x%'` at all, and one created without the `WHERE` clause is
    bigger than it needs to be and leaves residuo R7 open for that table. Both mistakes
    produce a green `compare_metadata`, so they are asserted on the definition text.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            ).all()
        engine.dispose()

    indexes = {row.indexname: row.indexdef for row in rows}
    # Nine, and the count is asserted: a set comprehension that silently matched nothing
    # would make every assertion below vacuous.
    assert len(TRGM_INDEX_NAMES) == 9
    for name in sorted(TRGM_INDEX_NAMES):
        definition = indexes[name]
        assert "USING gin" in definition, f"{name} is not a GIN index: {definition}"
        assert "gin_trgm_ops" in definition, f"{name} lacks gin_trgm_ops: {definition}"
        assert "WHERE (deleted_at IS NULL)" in definition, (
            f"{name} is not partial on deleted_at IS NULL: {definition}"
        )
        assert "lower(" not in definition, (
            f"{name} wraps the column in lower(), which stops ILIKE on the raw column "
            f"from using it (spec §8.2): {definition}"
        )


# (index name, the exact `USING btree (...)` body Postgres must report). Residuo R9's
# ordering contract is `ORDER BY <col> <dir> NULLS LAST, id <dir>`, and an index only
# serves it when both members are present in that order -- a single-column index on
# `created_at` leaves the `id` tie-break to an in-memory sort, which is the cost the
# thirteen exist to avoid. Pinned as text because the *order* of the members and the
# `DESC NULLS LAST` qualifier are observable nowhere else.
SORT_INDEX_BODIES: dict[str, str] = {
    "ix_customers_created_at_id": "(created_at, id)",
    "ix_customers_updated_at_id": "(updated_at, id)",
    "ix_customers_ragione_sociale_id": "(ragione_sociale, id)",
    "ix_people_created_at_id": "(created_at, id)",
    "ix_people_updated_at_id": "(updated_at, id)",
    "ix_people_cognome_id": "(cognome, id)",
    "ix_people_cognome_desc_id": "(cognome DESC NULLS LAST, id DESC)",
    "ix_deals_created_at_id": "(created_at, id)",
    "ix_deals_updated_at_id": "(updated_at, id)",
    "ix_deals_nome_id": "(nome, id)",
    "ix_documents_created_at_id": "(created_at, id)",
    "ix_documents_updated_at_id": "(updated_at, id)",
    "ix_documents_titolo_id": "(titolo, id)",
}


def test_every_sort_index_is_a_btree_over_the_column_and_the_identifier() -> None:
    """Residuo R9's other half, asserted on the definition text rather than on the name.

    `compare_metadata` does not compare index expressions at all, so the one index that
    matters most here is exactly the one a schema diff would let through:
    `ix_people_cognome_desc_id`. Without it a descending scan of `people.cognome` reads
    the ascending index backwards, which yields NULLS FIRST -- not the order
    `db/sort.py::order_by` declares -- and Postgres sorts the whole table in memory
    instead.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            ).all()
        engine.dispose()

    indexes = {row.indexname: row.indexdef for row in rows}
    # Twelve ascending, plus the one the single nullable sort column costs.
    assert len(SORT_INDEX_BODIES) == 13
    for name, body in SORT_INDEX_BODIES.items():
        definition = indexes[name]
        assert f"USING btree {body}" in definition, definition
        # None of the thirteen is partial, unlike the trigram indexes above: ordering has
        # to reach every row the filters admit, and a `WHERE deleted_at IS NULL` predicate
        # here would make the index unusable for any future listing that asks for the
        # deleted ones.
        assert " WHERE " not in definition, definition


def _applied_revision(url: str) -> str:
    engine: Engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def test_env_prefers_an_explicit_config_url_over_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for a real finding: `env.py` must not unconditionally prefer
    `get_settings()` over whatever URL the `Config` object already carries -- that is
    exactly what made a hand-edited `alembic.ini` (Alembic's own documented mechanism)
    silently do nothing. Proven adversarially: `get_settings()` is pointed at a URL that
    cannot possibly connect (nothing listens on port 1), while `_alembic_config` gives
    `upgrade()` the real container's URL. If `env.py` ever went back to always
    overriding with settings, this fails with a connection error instead of quietly
    passing.
    """
    monkeypatch.setenv(
        "PIGROCRM_DATABASE_URL", "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nobody"
    )
    get_settings.cache_clear()
    try:
        with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
            url = container.get_connection_url()
            upgrade(_alembic_config(url), "head")
            revision = _applied_revision(url)
    finally:
        get_settings.cache_clear()

    assert revision == "0024"


def test_env_falls_back_to_settings_when_config_has_no_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The brief's own default path, which must keep working exactly as before: a
    `Config` that nobody pointed anywhere (still carrying `alembic.ini`'s placeholder
    `sqlalchemy.url`) falls back to `get_settings()`, the same application-wide
    configuration source the rest of the codebase uses.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        monkeypatch.setenv("PIGROCRM_DATABASE_URL", url)
        get_settings.cache_clear()
        try:
            config = Config(str(CORE_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(CORE_ROOT / "migrations"))
            # `sqlalchemy.url` deliberately left untouched -- still the ini's placeholder.
            upgrade(config, "head")
            revision = _applied_revision(url)
        finally:
            get_settings.cache_clear()

    assert revision == "0024"


def test_stato_dal_is_backfilled_from_the_timeline_and_chiuso_il_is_not() -> None:
    """The asymmetry of spec §4.1, asserted rather than described.

    A migration that quietly backfilled `chiuso_il` from the stage-change payload would
    pass every other test in this file and would silently attribute deals to months
    derived from a renamable string. Asserted on the migration's source text because the
    absence of a statement is observable nowhere else: a schema comparison sees identical
    columns whether they were filled or left null.
    """
    source = (CORE_ROOT / "migrations" / "versions" / "0023_automations_and_dates.py").read_text(
        encoding="utf-8"
    )
    assert "UPDATE documents" in source
    assert "state_changed" in source
    assert "UPDATE deals" not in source, (
        "deals.chiuso_il must not be backfilled: move_stage records stage *names*, which "
        "are renamable (residuo R15). See spec §4.1."
    )
    assert "stage_changed" not in source


def test_the_backfill_reaches_only_offers_and_reads_the_emitters_day() -> None:
    """Two clauses that a passing schema comparison cannot see either.

    `d.stato IS NOT NULL` is what keeps the backfill to offers: `documents.stato` is NULL
    on every non-offer document, and stamping a `stato_dal` on a row with no state would
    make "this offer has been sitting for N days" answer for a contract.

    `AT TIME ZONE 'Europe/Rome'` is the same rule as `db/clock.py`, applied to history: a
    state set at 00:30 CET on 1 January was set on 1 January, and a bare `::date` on a
    `timestamptz` would record it as the previous year.
    """
    source = (CORE_ROOT / "migrations" / "versions" / "0023_automations_and_dates.py").read_text(
        encoding="utf-8"
    )
    assert "d.stato IS NOT NULL" in source
    assert "AT TIME ZONE" in source
    assert 'Europe/Rome"' in source or "Europe/Rome'" in source


def test_the_backfill_actually_fills_the_right_day_on_the_right_rows() -> None:
    """The backfill run against real rows, not read as text.

    Every other assertion about migration 0023 is a substring check, and a substring check
    cannot tell a correct `DISTINCT ON` from one that picks the *first* state change, nor
    a `AT TIME ZONE` that is applied from one that is written and ignored. This runs the
    revision over rows planted at 0022 and reads back what it wrote.

    The newest state change is at 22:30 UTC on 30 June, which is 00:30 on 1 July in Rome
    (CEST, +02:00). Four distinct defects each change the answer:

      * taking the oldest state change instead of the newest -> 10 March;
      * dropping the `kind` filter -> 1 August, the day of the unrelated activity;
      * projecting through UTC instead of the emitter's zone -> 30 June;
      * dropping `d.stato IS NOT NULL` -> the contract gets a `stato_dal` too.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        config = _alembic_config(url)
        upgrade(config, "0022")

        engine: Engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO customers (id, ragione_sociale, nazione, custom_fields,
                                           created_at, updated_at)
                    VALUES ('00000000-0000-7000-8000-0000000000c1', 'Cliente Storico', 'IT',
                            '{}'::jsonb, now(), now());

                    INSERT INTO pipeline_stages (id, nome, posizione, probabilita_default,
                                                 tipo, created_at, updated_at)
                    VALUES ('00000000-0000-7000-8000-0000000000e1', 'Vinto', 0, 100, 'won',
                            now(), now());

                    INSERT INTO deals (id, nome, customer_id, pipeline_stage_id, probabilita,
                                       custom_fields, created_at, updated_at)
                    VALUES ('00000000-0000-7000-8000-0000000000d0', 'Affare chiuso',
                            '00000000-0000-7000-8000-0000000000c1',
                            '00000000-0000-7000-8000-0000000000e1', 100, '{}'::jsonb,
                            now(), now());

                    INSERT INTO documents (id, customer_id, tipo, titolo, stato,
                                           versione_corrente, custom_fields,
                                           created_at, updated_at)
                    VALUES ('00000000-0000-7000-8000-0000000000a1',
                            '00000000-0000-7000-8000-0000000000c1', 'offerta', 'Offerta',
                            'inviata', 0, '{}'::jsonb, now(), now()),
                           ('00000000-0000-7000-8000-0000000000a2',
                            '00000000-0000-7000-8000-0000000000c1', 'verbale', 'Verbale',
                            NULL, 0, '{}'::jsonb, now(), now());

                    INSERT INTO activities (id, entity_type, entity_id, kind, actor_type,
                                            payload, occurred_at)
                    VALUES ('00000000-0000-7000-8000-0000000000b1', 'document',
                            '00000000-0000-7000-8000-0000000000a1', 'state_changed', 'system',
                            '{"da": "bozza", "a": "inviata"}'::jsonb,
                            '2026-03-10T09:00:00+00:00'),
                           ('00000000-0000-7000-8000-0000000000b2', 'document',
                            '00000000-0000-7000-8000-0000000000a1', 'state_changed', 'system',
                            '{"da": "inviata", "a": "accettata"}'::jsonb,
                            '2026-06-30T22:30:00+00:00'),
                           ('00000000-0000-7000-8000-0000000000b3', 'document',
                            '00000000-0000-7000-8000-0000000000a1', 'version_added', 'system',
                            '{}'::jsonb, '2026-08-01T12:00:00+00:00'),
                           ('00000000-0000-7000-8000-0000000000b4', 'document',
                            '00000000-0000-7000-8000-0000000000a2', 'state_changed', 'system',
                            '{"da": "bozza", "a": "inviata"}'::jsonb,
                            '2026-05-05T12:00:00+00:00'),
                           ('00000000-0000-7000-8000-0000000000b5', 'deal',
                            '00000000-0000-7000-8000-0000000000d0', 'stage_changed', 'system',
                            '{"from": "Offerta", "to": "Vinto"}'::jsonb,
                            '2026-04-04T12:00:00+00:00');
                    """
                )
            )
        engine.dispose()

        upgrade(config, "0023")

        engine = create_engine(url)
        with engine.connect() as connection:
            offerta, verbale = (
                connection.execute(text("SELECT stato_dal FROM documents ORDER BY id"))
                .scalars()
                .all()
            )
            chiuso_il = connection.execute(text("SELECT chiuso_il FROM deals")).scalar_one()
        engine.dispose()

    assert offerta == date(2026, 7, 1), offerta
    assert verbale is None, "a document with no stato must not acquire a stato_dal"
    assert chiuso_il is None, (
        "deals.chiuso_il must stay null: a closure deduced from a renamable stage name is "
        "a conversion rate that is plausible and wrong (spec §4.1)"
    )


def test_the_migration_seeds_exactly_one_automation_config_row() -> None:
    """Two paths build this schema and both must produce one row.

    `Base.metadata.create_all` (the test suite) leaves the table empty and
    `AutomationConfigRepository.get_or_create` fills it on first read; a migrated
    installation gets the row from `0023` before the first request. A migration that
    created the table and forgot the `INSERT` would still pass every schema comparison in
    this file -- slice 3 lost `proforma_riferimento_seq` to exactly that gap -- and the
    first `GET` would then be the request that writes.

    Asserted as a count, not as "at least one": a second seeded row would make
    `get_or_create`'s `LIMIT 1` return whichever the planner preferred, so an operator's
    change to the configuration could stop taking effect between one request and the next.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT a1_offerta_accettata_vince_deal, a2_offerta_inviata_avanza_deal "
                    "FROM automation_config"
                )
            ).all()
        engine.dispose()

    assert len(rows) == 1, rows
    # Both defaults are `true`, and they arrive from the *server* default: the migration's
    # INSERT names only `id`. An automation nobody switched on is one nobody knows exists.
    assert rows[0] == (True, True)


def test_the_activity_feed_index_is_descending_on_both_columns() -> None:
    """An ascending index would still be used -- backwards -- but a backward scan of
    `(occurred_at, id)` yields the tie-break ascending within each instant, which is not
    the order `ActivityRepository.recent` declares. Asserting the declared shape is what
    stops a future "simplification" to a single-column ascending index that cannot serve
    the tie-break at all.

    On `indexdef` text and not through `compare_metadata`, which does not compare index
    expressions: a descending expression index is exactly the shape a schema diff lets
    through in silence.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade(_alembic_config(url), "head")
        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            definition = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' AND indexname = 'ix_activities_recent'"
                )
            ).scalar_one()
        engine.dispose()
    assert "occurred_at DESC" in definition, definition
    assert "id DESC" in definition, definition
    # Both members, in this order: an index on `occurred_at DESC` alone leaves the
    # tie-break to an in-memory sort, which is the cost this index exists to remove.
    assert "USING btree (occurred_at DESC, id DESC)" in definition, definition
