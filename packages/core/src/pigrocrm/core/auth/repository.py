from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> list[User]:
        return list(self.session.execute(select(User).order_by(User.nome)).scalars())

    def count(self) -> int:
        return self.session.execute(select(func.count()).select_from(User)).scalar_one()

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user
