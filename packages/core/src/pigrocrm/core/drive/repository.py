"""Queries only. Never commits -- the service owns the transaction.

The in-flight authorisation state is not duplicated here: `google_oauth_states` serves
both the Gmail and the Drive flow (see `GoogleOAuthState.purpose`), and
`GmailRepository.add_state`/`consume_state` already implement the one-statement,
race-safe redemption that a second copy of the same logic could only get wrong by
drifting from it. This repository owns the one table that is Drive's alone.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.drive.models import GoogleDriveAccount


class DriveRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def account_for_user(self, user_id: UUID) -> GoogleDriveAccount | None:
        return self.session.execute(
            select(GoogleDriveAccount).where(GoogleDriveAccount.user_id == user_id)
        ).scalar_one_or_none()

    def add(self, account: GoogleDriveAccount) -> GoogleDriveAccount:
        self.session.add(account)
        self.session.flush()
        return account
