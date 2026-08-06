from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class User(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    ruolo: Mapped[str] = mapped_column(String(20), nullable=False, default="collaboratore")
    attivo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
