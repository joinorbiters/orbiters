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

    assert revision == "0022"


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

    assert revision == "0022"
