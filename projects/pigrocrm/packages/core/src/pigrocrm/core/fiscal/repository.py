from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.fiscal.models import FiscalProfile


class FiscalProfileRepository:
    """A repository never commits (project rule): every method here reads or flushes,
    and the surrounding service method is the one transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> FiscalProfile | None:
        return self.session.execute(select(FiscalProfile)).scalars().first()

    def add(self, profile: FiscalProfile) -> FiscalProfile:
        self.session.add(profile)
        self.session.flush()
        return profile
