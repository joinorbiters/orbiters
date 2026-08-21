from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class FiscalProfile(Base, PrimaryKeyMixin, TimestampMixin):
    """The fiscal parameters of the one issuer. One row, ever.

    `emitter_profile` (slice 2) holds the issuer's *identity*; this holds the numbers
    and codes the SdI validates. They are not duplicates, and
    `emitter_profile.regime_fiscale` -- a `String(200)` of free text, already shipped
    and already read by `render/assets/header.typ.template` -- keeps its own meaning as
    a human-readable caption on the PDF. `codice_regime` here is the machine value,
    `String(4)`, and the only input to the XML's `RegimeFiscale`.

    Not historicised, and the alternative was considered rather than overlooked: a
    regime changes on 1 January, but spec 6.2 forbids back-dating an invoice past the
    start of the current year, so no emission ever needs a previous period's
    parameters. A `valido_da`/`valido_a` pair would only answer a question the
    per-invoice `snapshot` already answers, and answers better.

    Single-row is enforced by the database, exactly as `EmitterProfile` does it:
    `singleton` is `unique=True` and always `True`, so a second insert fails on the
    constraint. A "select then insert" pre-check alone would let two concurrent
    first-time saves both pass.
    """

    __tablename__ = "fiscal_profile"

    singleton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, unique=True)
    # RF01..RF19, as FPR12's RegimeFiscaleType enumerates them.
    codice_regime: Mapped[str] = mapped_column(String(4), nullable=False)
    aliquota_iva_default: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00")
    )
    natura_default: Mapped[str | None] = mapped_column(String(4), default=None)
    riferimento_normativo: Mapped[str | None] = mapped_column(Text, default=None)
    # Values of law, not preferences: configurable because the law has changed them.
    applica_bollo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    soglia_bollo: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("77.47")
    )
    importo_bollo: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("2.00")
    )
    condizioni_pagamento: Mapped[str] = mapped_column(String(4), nullable=False, default="TP02")
    modalita_pagamento: Mapped[str] = mapped_column(String(4), nullable=False, default="MP05")
    giorni_scadenza: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    iban: Mapped[str | None] = mapped_column(String(34), default=None)
