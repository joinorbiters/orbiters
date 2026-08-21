"""Queries only. A repository never commits (project rule): every method reads or
flushes, and the surrounding `InvoiceService` method is the one transaction."""

from datetime import date
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from pigrocrm.core.invoices.models import (
    PROFORMA_SEQUENCE_NAME,
    Invoice,
    InvoiceCounter,
    InvoiceLine,
)
from pigrocrm.core.invoices.schemas import InvoiceListQuery


class InvoiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, invoice_id: UUID, *, include_deleted: bool = False) -> Invoice | None:
        invoice = self.session.get(Invoice, invoice_id)
        if invoice is None:
            return None
        if invoice.deleted_at is not None and not include_deleted:
            return None
        return invoice

    def add(self, invoice: Invoice) -> Invoice:
        self.session.add(invoice)
        self.session.flush()
        return invoice

    def lines(self, invoice_id: UUID) -> list[InvoiceLine]:
        stmt = (
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice_id)
            .order_by(InvoiceLine.numero_linea)
        )
        return list(self.session.execute(stmt).scalars())

    def clear_lines(self, invoice_id: UUID) -> None:
        """A real `DELETE`, then a fresh insert of the whole list.

        Bulk replacement rather than a per-line diff, for the reason spec 11 gives: it
        is the natural shape of a line editor, and it is what makes clearing an
        optional numeric column possible at all (A14 -- with `exclude_none=True` there
        is no spelling that means "set `sconto_importo` back to nothing").
        """
        self.session.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id))
        self.session.flush()

    def add_line(self, line: InvoiceLine) -> InvoiceLine:
        self.session.add(line)
        self.session.flush()
        return line

    def next_proforma_sequence(self) -> int:
        """`nextval` on the one proforma sequence.

        A `SEQUENCE` is the right tool here and the wrong one for the fiscal number,
        for the same property: it does not roll back. A gap in a proforma reference
        means nothing -- a proforma is not a register -- and in exchange this counter
        serialises nobody, which is exactly what the fiscal counter cannot afford to
        do and must do anyway.
        """
        return int(
            self.session.execute(text(f"SELECT nextval('{PROFORMA_SEQUENCE_NAME}')")).scalar_one()
        )

    def lock_counter(self, anno: int) -> InvoiceCounter:
        """The year's counter row, locked for the rest of this transaction.

        Two statements, in this order and for these reasons:

        1. `INSERT ... ON CONFLICT (anno) DO NOTHING` -- two concurrent
           first-invoices-of-the-year: one inserts, the other does nothing, both carry
           on. Without `ON CONFLICT` the loser would take a `UniqueViolation` and have
           to be retried by the caller.
        2. `SELECT ... FOR UPDATE` -- from here on every other emission for the same
           year waits. This is deliberately **the first row lock the emission
           transaction takes**, and no later statement in that transaction takes a lock
           a concurrent emission could already hold, so two emissions cannot deadlock
           against each other.

        Not a `SEQUENCE`, and that is the whole design: `nextval()` is
        non-transactional by design and does not roll back, so a sequence guarantees
        uniqueness while prohibiting exactly the property required here -- the absence
        of gaps. Every aborted transaction would leave a permanent hole in the
        register.

        The `SELECT` is `.one()`, not `.first()`: after step 1 the row must exist, and
        a `None` here would mean the insert silently did nothing for a reason worth
        crashing over rather than working around.
        """
        self.session.execute(
            text(
                "INSERT INTO invoice_counters (anno, ultimo_numero) "
                "VALUES (:anno, 0) ON CONFLICT (anno) DO NOTHING"
            ),
            {"anno": anno},
        )
        stmt = select(InvoiceCounter).where(InvoiceCounter.anno == anno).with_for_update()
        return self.session.execute(stmt).scalars().one()

    def last_issued_date(self, anno: int) -> date | None:
        """The `data_emissione` of the highest-numbered invoice of `anno`.

        Safe to read only *after* `lock_counter` has run, which is the one place it is
        called from: without the lock, a concurrent emission could commit a later
        number between this read and the write that depends on it. Includes
        `annullata` rows on purpose -- an annulled invoice keeps its number and its
        place in the chronological order, which is what makes the register monotonic
        rather than merely gap-free.
        """
        stmt = (
            select(Invoice.data_emissione)
            .where(Invoice.anno == anno, Invoice.numero.is_not(None))
            .order_by(Invoice.numero.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    # `list` must stay the last method defined in this class -- an unconditional
    # project rule (`test_module_imports.py`). Defining a method named `list` rebinds
    # that name in the *class* namespace, so any later method whose own return
    # annotation is a bare `list[...]` would resolve `list` to this method instead of
    # the builtin and fail at import time on Python 3.13.
    def list(self, query: InvoiceListQuery) -> list[Invoice]:
        stmt = select(Invoice).where(Invoice.deleted_at.is_(None))
        if query.customer_id:
            stmt = stmt.where(Invoice.customer_id == query.customer_id)
        if query.deal_id:
            stmt = stmt.where(Invoice.deal_id == query.deal_id)
        if query.tipo:
            stmt = stmt.where(Invoice.tipo == query.tipo)
        if query.stato:
            stmt = stmt.where(Invoice.stato == query.stato)
        if query.anno:
            stmt = stmt.where(Invoice.anno == query.anno)
        if query.stato_pagamento:
            stmt = stmt.where(Invoice.stato_pagamento == query.stato_pagamento)
        if query.cursor:
            stmt = stmt.where(Invoice.id > query.cursor)
        # Keyset pagination on a UUIDv7 id: ordered by creation, stable under inserts.
        # No caller-supplied sort -- R9 is open and this adds no half-feature.
        return list(
            self.session.execute(stmt.order_by(Invoice.id).limit(query.limit + 1)).scalars()
        )
