"""payment reminders, and the mailbox a draft was sent from

Revision ID: 0020
Revises: 0019

Two things, and the second is a fix the task that found it could not make.

**`payment_reminders`.** One row per reminder per invoice, with the unique constraint on
`(invoice_id, sequence)` that is the first of the three layers of spec 7.3. It is the
database that guarantees it and not application code: two concurrent creates both pass
the count that precedes them, and only the constraint stops the second. the previous system kept the
equivalent in a JSON file with a non-atomic read-modify-write and lost it under exactly
this race.

The two foreign keys point in opposite directions -- `payment_reminders.email_draft_id`
at the draft, `email_drafts.payment_reminder_id` back at the reminder -- so the second is
added by `ALTER TABLE` after both tables exist. It is the constraint 0018 recorded as
deliberately absent, «because `payment_reminders` does not exist until B2-8; that task
adds the constraint in its own revision». This is that revision. Both are `SET NULL`: a
draft is somebody's own text and a reminder is the record that one was prepared, and
neither should vanish because the other did.

**`email_drafts.google_account_id`.** The mailbox a draft was *sent from*, written by the
send claim. It closes a defect B2-6 could only mitigate: `reconcile_all` walked every
draft in `incerto`/`in_invio` regardless of whose it was, and it runs inside each user's
own sync cycle -- so on a multi-user install user A's cycle picked up user B's unresolved
send, looked for it in A's mailbox, found nothing, and past the grace window wrote
`fallito` on a message sitting in B's client's inbox. Telling somebody an email failed
when it was delivered is the one outcome in this slice that cannot be walked back,
because the answer to it is to send the message again. B2-6 mitigated it -- the header
lookup is deliberately not account-scoped, the draft stays intact, and the sentence tells
the person to check «Posta inviata» -- but the real fix is this column.

The backfill is deliberately conditional. On an installation with exactly one connected
mailbox every existing draft belongs to it, and attributing them is both correct and what
keeps their reconciliation working across this upgrade. On one with two or more there is
no way to tell, so those rows stay NULL -- and a NULL is read as "in nobody's automatic
list", never as "in everybody's". That leaves an unresolved draft waiting for a person to
ask about it by hand, which is the safe direction of the two: an `incerto` that stays
`incerto` keeps its text and its instruction to check Sent, while a wrong `fallito` is an
invitation to resend.

`SET NULL` on this one too, and not `CASCADE`: disconnecting a mailbox must not delete
the text somebody wrote from it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_reminders",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        # NULL until the draft actually leaves. `EmailSendService` stamps it; nothing on
        # the creation path may, because creating a reminder sends nothing.
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_draft_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["email_draft_id"], ["email_drafts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id", "sequence", name="uq_payment_reminders_invoice_sequence"),
    )

    # The constraint 0018 left off, now that the table it points at exists.
    op.create_foreign_key(
        "fk_email_drafts_payment_reminder",
        "email_drafts",
        "payment_reminders",
        ["payment_reminder_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("email_drafts", sa.Column("google_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_email_drafts_google_account",
        "email_drafts",
        "google_accounts",
        ["google_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Attribute the existing drafts only where the answer is not a guess: exactly one
    # connected mailbox means every draft came from it. Two or more and the rows stay
    # NULL, which the reconciliation reads as "not mine" rather than "anyone's".
    op.execute(
        sa.text(
            "UPDATE email_drafts SET google_account_id = (SELECT id FROM google_accounts) "
            "WHERE (SELECT count(*) FROM google_accounts) = 1"
        )
    )


def downgrade() -> None:
    op.drop_constraint("fk_email_drafts_google_account", "email_drafts", type_="foreignkey")
    op.drop_column("email_drafts", "google_account_id")
    op.drop_constraint("fk_email_drafts_payment_reminder", "email_drafts", type_="foreignkey")
    op.drop_table("payment_reminders")
