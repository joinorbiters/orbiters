from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.emitter.models import EmitterProfile


class EmitterProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> EmitterProfile | None:
        return self.session.execute(select(EmitterProfile).limit(1)).scalars().first()

    def add(self, profile: EmitterProfile) -> EmitterProfile:
        # Flushes: this is what actually sends the `INSERT` to Postgres and is the
        # only place the `singleton` unique constraint can be violated, and also
        # what populates `profile.id` (a flush-time column default, not a
        # construction-time one -- see `PrimaryKeyMixin`) before `service.upsert`
        # needs it for `ActivityService.record`. Callers MUST invoke this from
        # inside their own `try/except IntegrityError`: see `EmitterProfileService.
        # upsert`'s docstring for the concurrency bug this project already made
        # once by calling `add` outside that block.
        self.session.add(profile)
        self.session.flush()
        return profile
