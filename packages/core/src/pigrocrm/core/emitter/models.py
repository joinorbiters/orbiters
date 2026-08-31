from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class EmitterProfile(Base, PrimaryKeyMixin, TimestampMixin):
    """Who is issuing the document. One row, ever.

    This is what replaces "Humancraft di Ivan Sala", the P.IVA, the PEC and the
    address hardcoded into Acme's `offer/header.typ` (lines 16-28). A CRM for
    Italian freelancers cannot have one freelancer's name in its source. Slice 3
    builds FatturaPA on these same columns, which is why the fiscal ones mirror
    `customers` exactly rather than being free text.

    Single-row is enforced by the database, not by a convention: `singleton` is
    `unique=True` and always `True`, so a second insert fails on the constraint. A
    "select then insert" pre-check alone would let two concurrent first-time saves
    both pass.
    """

    __tablename__ = "emitter_profile"

    singleton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, unique=True)
    ragione_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    partita_iva: Mapped[str | None] = mapped_column(String(11), default=None)
    codice_fiscale: Mapped[str | None] = mapped_column(String(16), default=None)
    indirizzo: Mapped[str | None] = mapped_column(String(255), default=None)
    cap: Mapped[str | None] = mapped_column(String(10), default=None)
    comune: Mapped[str | None] = mapped_column(String(120), default=None)
    provincia: Mapped[str | None] = mapped_column(String(2), default=None)
    nazione: Mapped[str] = mapped_column(String(2), nullable=False, default="IT")
    pec: Mapped[str | None] = mapped_column(String(320), default=None)
    codice_sdi: Mapped[str | None] = mapped_column(String(7), default=None)
    telefono: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    sito_web: Mapped[str | None] = mapped_column(String(255), default=None)
    # Storage keys, not filesystem paths: the logo and signature live in the same
    # DocumentStorage as everything else, so a Drive-backed install keeps them too.
    logo_key: Mapped[str | None] = mapped_column(String(255), default=None)
    firma_key: Mapped[str | None] = mapped_column(String(255), default=None)
    # A text block -- name and role of the person signing. NOT the same thing as
    # `firma_key` above, which is the storage key of a signature *image* used on the
    # PDF: an email does not attach an image of a signature, it wants text. The phone
    # number, the website and the company name are deliberately NOT repeated here; the
    # reminder template reads them from their own columns, so the number cannot diverge
    # between two places. Acme hardcoded all of it, twice, verbatim, in two builders.
    firma_email: Mapped[str | None] = mapped_column(Text, default=None)
    regime_fiscale: Mapped[str | None] = mapped_column(String(200), default=None)
