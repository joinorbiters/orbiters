"""google_accounts.status becomes wide enough for 'disconnected'

Revision ID: 0017
Revises: 0016

`status` used to hold three values in ten characters. A mailbox the user disconnected
shared `revoked` with a consent Google had withdrawn, told apart only by
`disconnected_at` being non-null -- so every banner and every gate that read `status`
told somebody who had just pressed «scollega» that Google had revoked their consent, and
offered to reconnect what they had deliberately unhooked.

They are two events and now they are two states. `disconnected` is twelve characters, so
the column widens to twenty; widening a `varchar` in Postgres is a catalogue change and
does not rewrite the table.

No data migration. Existing `revoked` rows keep that value: for a row disconnected
before this revision, `disconnected_at` is still the only evidence of which event it
was, and rewriting history from a nullable timestamp is exactly the inference this
revision exists to stop making. The next disconnect on such an account records the
truthful state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "google_accounts",
        "status",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing back would truncate a stored `disconnected`, so the rows that carry it
    # are put back onto the value they used to share before the column is narrowed.
    op.execute(
        "UPDATE google_accounts SET status = 'revoked' WHERE status = 'disconnected'"  # noqa: S608
    )
    op.alter_column(
        "google_accounts",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
