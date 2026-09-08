"""pg_trgm and the partial trigram search indexes

Revision ID: 0021
Revises: 0020

Closes residuo R6 for customers, people, deals and documents, and residuo R7 for those
four tables as a side effect of the indexes being partial on `deleted_at IS NULL`.

Nine indexes and not four. `CustomerRepository.list` and `PersonRepository.list` each OR
several columns together, and a four-way OR is planned as a BitmapOr over four bitmap
index scans -- a single unindexed branch collapses the whole thing back into one
sequential scan, so indexing only the display name would have bought nothing.

`CREATE EXTENSION` is deliberately not guarded by a capability check. Migrations run at
API start-up (slice 1 §12), so on a managed Postgres whose allowlist forbids `pg_trgm`
the deploy fails loudly here -- which is what is wanted. The alternative is an
application that starts and scans sequentially in silence, which is the defect being
cured, with one index fewer.

`CONCURRENTLY` is not used: Alembic runs each migration inside a transaction, and
`CREATE INDEX CONCURRENTLY` cannot run in one. On a table of this size the exclusive lock
is short; on a live installation large enough for it to matter, the operator builds the
indexes by hand out-of-band and this migration finds them already present -- which is why
every statement carries `IF NOT EXISTS`.

The tenth index, on `invoices.causale`, belongs to slice 6C. It is absent here because
this slice's search never reads that column, not because the table is missing.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, column). Mirrors the `__table_args__` declarations on the four
# models exactly -- `test_migrations_produce_exactly_the_models_schema` is what keeps the
# two honest, and `Base.metadata.create_all` is what makes them visible under test.
_TRGM_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_customers_ragione_sociale_trgm", "customers", "ragione_sociale"),
    ("ix_customers_partita_iva_trgm", "customers", "partita_iva"),
    ("ix_customers_codice_fiscale_trgm", "customers", "codice_fiscale"),
    ("ix_customers_email_trgm", "customers", "email"),
    ("ix_people_nome_trgm", "people", "nome"),
    ("ix_people_cognome_trgm", "people", "cognome"),
    ("ix_people_email_trgm", "people", "email"),
    ("ix_deals_nome_trgm", "deals", "nome"),
    ("ix_documents_titolo_trgm", "documents", "titolo"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in _TRGM_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"USING gin ({column} gin_trgm_ops) WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    for name, _table, _column in reversed(_TRGM_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    # The extension is left installed. Dropping it would fail if anything else in the
    # database came to depend on it, and an extension costs nothing to leave behind.
