"""refresh_tokens.successor_jti: which token a rotation handed out

Revision ID: 0030
Revises: 0029

One nullable column, and the reason it exists is a forced logout the owner reported: two
browser tabs (or one browser restoring two) both wake up past the fifteen-minute access
cookie, both POST /api/auth/refresh with the same rotating refresh cookie -- the only one
the jar holds -- and the second presentation looks exactly like a stolen token being
replayed. `RefreshTokenService.consume` answered that the only way it could, by revoking
every token the user held, and every tab landed on the login screen.

Recording the successor is what makes the two cases distinguishable at all: inside
`REFRESH_GRACE_SECONDS` the second presentation is answered with the *same* pair the
first one produced (`RefreshTokenService.rotate`), and outside it -- or once the
successor has itself been used -- the old reading stands and the family dies.

Nullable, with no backfill: every row that predates this migration has no recorded
successor, which reads as "no same-pair answer available" and so keeps exactly the
pre-migration behaviour for tokens issued before the deploy. No index either -- the
column is only ever read through a row already fetched by `jti` (which is uniquely
indexed), never searched by.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("successor_jti", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("refresh_tokens", "successor_jti")
