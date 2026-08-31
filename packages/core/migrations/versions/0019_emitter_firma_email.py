"""emitter signature block for email

Revision ID: 0019
Revises: 0018

`emitter_profile.firma_key` has always been the storage key of a signature *image*,
composed onto the PDF. An email does not attach an image of a signature: it wants a
text block, name and role, above the company line. Two columns, not one overloaded one.

Nullable with no backfill and no default, deliberately. An install that has been running
since slice 2 has an emitter profile with no signature block, and inventing one from
`ragione_sociale` would put a company name where a person's name belongs -- on outgoing
correspondence, in the freelancer's own name. The reminder template treats it as
optional and renders the company line alone when it is absent, which is a correct
signature; a fabricated one is not.

`Text`, not `String(n)`: a signature block is prose with line breaks in it. The 2,000
character bound lives in `EmitterProfileUpsert` instead, where exceeding it is a clean
`ValidationFailed` rather than a `DataError` from the driver.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("emitter_profile", sa.Column("firma_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("emitter_profile", "firma_email")
