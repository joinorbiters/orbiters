from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.automations.models import AutomationConfig


class AutomationConfigRepository:
    """Single row, created on first read.

    Created here rather than by the migration alone so that a database restored from
    before this slice, or a test using `Base.metadata.create_all`, behaves identically to
    a freshly migrated one -- both paths must work, and slice 3 lost a sequence to exactly
    this gap. `flush`, never `commit`: the service owns the transaction.

    Nothing is cached on `self`: two `AutomationConfigService` instances over one session
    must see one row, and a per-instance cache would hide a second insert until the
    commit failed.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self) -> AutomationConfig:
        row = self.session.scalar(select(AutomationConfig).limit(1))
        if row is None:
            row = AutomationConfig()
            self.session.add(row)
            self.session.flush()
        return row
