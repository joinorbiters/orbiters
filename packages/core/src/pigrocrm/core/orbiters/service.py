from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.orbiters.models import Signup
from pigrocrm.core.orbiters.schemas import SignupCreate, SignupRead


class SignupService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def subscribe(self, data: SignupCreate) -> SignupRead:
        """Idempotent: the same address twice is one row and two successes.

        A signup form is retried by people, not by clients that read status codes -- a
        double click, a page reloaded on a slow connection. Refusing the second attempt
        would show an error to someone who did exactly what the page asked.
        """
        email = data.email.strip().lower()
        existing = self._find(email)
        if existing is not None:
            return _read(existing, nuova=False)

        row = Signup(email=email)
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError:
            # Two requests for the same new address can both pass `_find` before either
            # commits; the functional unique index decides, and the loser reads the
            # winner's row instead of reporting a conflict nobody caused.
            self.session.rollback()
            winner = self._find(email)
            assert winner is not None
            return _read(winner, nuova=False)
        return _read(row, nuova=True)

    def _find(self, email: str) -> Signup | None:
        return self.session.scalar(select(Signup).where(func.lower(Signup.email) == email))


def _read(row: Signup, *, nuova: bool) -> SignupRead:
    return SignupRead(id=row.id, email=row.email, created_at=row.created_at, nuova=nuova)
