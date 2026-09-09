"""attivita: the commitment with a due date and a state

Revision ID: 0032
Revises: 0031

The table slice 7 specified (2026-09-03 §3) and slice 10 built, unchanged from that
spec. `scadenza` is nullable because the commonest to-do has no date, and the
consequence is honoured everywhere: an undated activity is not late and is in no count
ordered by date.

Three states, not two: `annullata` records that a commitment stopped mattering, which a
deleted row does not. Hence the equivalence check on `completata_il` -- set when, and
only when, the state is `completata` -- and the soft delete kept for the typo.

At most one of the four references, and zero allowed: «do March's e-invoicing» belongs
to no customer, while two would be an activity that gets closed on one record and left
open on the other.

Every foreign key is plain (no cascade): nothing in this product is hard-deleted, and an
`ON DELETE CASCADE` here would make a customer's removal silently take its history of
commitments with it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attivita",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("titolo", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("scadenza", sa.Date(), nullable=True),
        sa.Column("stato", sa.String(length=20), nullable=False, server_default="aperta"),
        sa.Column("completata_il", sa.Date(), nullable=True),
        sa.Column("assegnata_a", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("people.id"), nullable=True),
        sa.Column("deal_id", sa.Uuid(), sa.ForeignKey("deals.id"), nullable=True),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("origine", sa.String(length=20), nullable=False, server_default="manuale"),
        sa.Column("regola", sa.String(length=50), nullable=True),
        sa.Column(
            "custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(stato = 'completata') = (completata_il IS NOT NULL)",
            name="ck_attivita_completata_il",
        ),
        sa.CheckConstraint(
            "stato IN ('aperta', 'completata', 'annullata')", name="ck_attivita_stato"
        ),
        sa.CheckConstraint(
            "origine IN ('manuale', 'automazione', 'sollecito')", name="ck_attivita_origine"
        ),
        sa.CheckConstraint(
            "regola IS NULL OR origine = 'automazione'", name="ck_attivita_regola_origine"
        ),
        sa.CheckConstraint(
            "(customer_id IS NOT NULL)::int + (person_id IS NOT NULL)::int "
            "+ (deal_id IS NOT NULL)::int + (invoice_id IS NOT NULL)::int <= 1",
            name="ck_attivita_un_solo_riferimento",
        ),
    )
    # The three indexes of spec §3.3, partial on the soft-delete predicate.
    op.create_index(
        "ix_attivita_scadenza",
        "attivita",
        ["stato", "scadenza"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_attivita_entity",
        "attivita",
        ["customer_id", "deal_id", "person_id", "invoice_id", "scadenza"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_attivita_assegnata",
        "attivita",
        ["assegnata_a", "stato", "scadenza"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_attivita_custom_fields", "attivita", ["custom_fields"], postgresql_using="gin"
    )
    # Residuo R9: one `(column, id)` B-tree per admitted sort key, plus the descending
    # one a nullable sort column costs -- a backward scan of the ascending index yields
    # NULLS FIRST and cannot serve `scadenza dir=desc`.
    op.create_index("ix_attivita_created_at_id", "attivita", ["created_at", "id"])
    op.create_index("ix_attivita_scadenza_id", "attivita", ["scadenza", "id"])
    op.execute(
        "CREATE INDEX ix_attivita_scadenza_desc_id ON attivita (scadenza DESC NULLS LAST, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_attivita_scadenza_desc_id")
    for name in (
        "ix_attivita_scadenza_id",
        "ix_attivita_created_at_id",
        "ix_attivita_custom_fields",
        "ix_attivita_assegnata",
        "ix_attivita_entity",
        "ix_attivita_scadenza",
    ):
        op.drop_index(name, table_name="attivita")
    op.drop_table("attivita")
