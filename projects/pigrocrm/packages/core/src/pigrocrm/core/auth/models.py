from decimal import Decimal

from sqlalchemy import Boolean, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class User(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    # No unique=True here: a plain unique index on the raw column is case-sensitive and
    # would let "a@b.it" and "A@B.it" both in. Uniqueness is enforced below by a
    # functional index on lower(email) instead -- a real database constraint, not just
    # the app-level lowering that UserCreate and UserRepository.get_by_email also do.
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    ruolo: Mapped[str] = mapped_column(String(20), nullable=False, default="collaboratore")
    attivo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Level 3 of slice 4 §5.1's resolution order, for both numbers. There is
    # deliberately no `costo_orario` on `deals`: an hour's cost is a property of who
    # works it, not of the client they work it for, and adding the level would let
    # somebody declare that the same person costs differently on two projects -- an
    # accounting entry, not CRM data. Both Numeric(12,6): they are factors, and slice
    # 3's `invoice_lines.prezzo_unitario` fixes that precision.
    tariffa_oraria_default: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    costo_orario_default: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)
