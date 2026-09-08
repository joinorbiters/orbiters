"""google_drive_accounts.storage_folder_verified

Revision ID: 0027
Revises: 0026

One boolean, and the whole of what it buys: `set_roots` can only prove a chosen write
folder is reachable while the credential is `active` and holds both Drive scopes, so a
folder chosen from a revoked or expired account is saved unverified -- and since the
settings panel resends the same id on *every* save, "unchanged, skip it" meant that
folder was never proven at all and the mistake surfaced as a failed upload on the first
generated document. With this column the skip is decided on the id *and* on whether the
folder was ever proven, so the first save after a reconnection is the one that proves it.
See `drive/account.py::GoogleDriveAccountService.set_roots`.

`server_default=false` and not just an ORM-side default, the same reasoning
`google_oauth_states.purpose` used in 0026: it is what keeps every row this table
already holds valid without a data migration. And `false` is the honest value for them
-- `set_roots` verified a new folder and had nowhere to record it, so there is nothing
to backfill from; a `true` default would make the first save after this upgrade skip the
very verification the column exists to run.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_drive_accounts",
        sa.Column(
            "storage_folder_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("google_drive_accounts", "storage_folder_verified")
