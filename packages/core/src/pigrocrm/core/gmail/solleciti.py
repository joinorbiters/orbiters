"""Which invoices are worth chasing.

A query, not an event. And **this call sends nothing** -- it prepares the list, which is
the part that was actually laborious: crossing due dates against payments against what
has already gone out. Pressing a button was never the work.

The comparison with the previous system justifies each of the conditions. There, the reminder was
chosen by `emailSentCount > 0` -- "is this the second email" -- with no due date, no
interval and no ceiling anywhere. Here the due date is the only thing that makes a
reminder legitimate, the interval is the only thing that makes it bearable, and the
ceiling is what stops a disputed invoice becoming an automated persecution.

Two further conditions come from slice 3's real shape rather than from the brief's
table, and they are not milder: an invoice that has not been *issued* has no number and
no legal existence, and one that has been `annullata` has been withdrawn. A payment
demand for either is the same mistake as chasing a paid invoice, with a fiscal document
attached to it.

Nothing here logs, and nothing that leaves this module carries a body or a recipient.
The candidate carries the client's *name*, which is what a list of invoices to chase has
to show; the addresses it will be sent to are resolved at composition time and stay
there.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.clock import oggi_in_italia
from pigrocrm.core.config import Settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.gmail.models import GoogleAccount, PaymentReminder
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.schemas import SollecitoCandidate
from pigrocrm.core.invoices.models import Invoice
from pigrocrm.core.invoices.naming import numero_completo
from pigrocrm.core.people.models import Person

# What `_query` yields per row: the invoice, its customer, how many reminder rows exist,
# how many of them were actually sent, when the last one left, and when the last one was
# either sent or prepared.
CandidateRow = tuple[Invoice, Customer, int, int, datetime | None, datetime | None]

# The one state in `invoices.stato_pagamento` that means the money arrived. Compared
# positively -- `!= 'incassato'` -- rather than against a list of the others, so a value
# added to `StatoPagamento` later defaults to *chaseable* and shows up in a test instead
# of silently disappearing from the list.
INCASSATO = "incassato"

# An invoice is chaseable only from here. `tipo` and `stato` together, because slice 3
# runs two state machines through one column: `emessa` is a fattura that consumed a
# register number, while `confermata` on the same column is a proforma -- not a fiscal
# document, and not something anybody owes money against.
CHASEABLE_TIPO = "fattura"
CHASEABLE_STATO = "emessa"


class SollecitiService:
    """Payment reminders: the list, and the preparation of one.

    Takes no transport and no `GoogleTokenClient`, and that absence is the design rather
    than an omission: nothing in this class may reach Google. The list is a database
    query, and preparing a reminder writes a row and a draft -- the draft then leaves
    through `EmailSendService.send`, which is the one send path in the slice.
    """

    def __init__(self, session: Session, *, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = GmailRepository(session)

    def candidates(self, actor: Actor) -> list[SollecitoCandidate]:
        """Every invoice that may legitimately be chased, worst first.

        Reading the list is not role-gated -- a `readonly` user may see which invoices are
        late, and that is a plain read of their own register. What is gated is preparing
        the reminder and sending it.
        """
        today = oggi_in_italia()
        grace_cutoff = today - timedelta(days=self.settings.solleciti_grace_days)
        interval_cutoff = datetime.now(UTC) - timedelta(
            days=self.settings.solleciti_min_interval_days
        )

        account = self._mailbox_of(actor)
        candidates: list[SollecitoCandidate] = []
        for invoice, customer, righe, inviati, ultimo, ultima_attivita in self.session.execute(
            self._query(grace_cutoff)
        ).all():
            # Condition 3: no reminder, sent *or merely prepared*, inside the minimum
            # interval. `ultima_attivita` is `max(coalesce(sent_at, created_at))`, and the
            # coalesce is the point: `create_reminder` writes a row before anything
            # leaves, so measuring only over `sent_at` would leave the invoice on the list
            # with a draft already waiting in it -- and the double send this layer exists
            # to prevent begins as a double draft.
            if ultima_attivita is not None and ultima_attivita >= interval_cutoff:
                continue
            # Condition 4: below the ceiling. Rows, not sends: three prepared reminders
            # occupy the three positions `(invoice_id, sequence)` has, and offering a
            # fourth here that `create_reminder` would refuse is a list that lies.
            if righe >= self.settings.solleciti_max_reminders:
                continue

            scadenza = invoice.data_scadenza
            if scadenza is None:  # pragma: no cover - the query's own WHERE excludes it
                continue
            candidates.append(
                SollecitoCandidate(
                    invoice_id=invoice.id,
                    numero=numero_completo(invoice.anno or 0, invoice.numero or 0),
                    data_fattura=invoice.data_emissione or scadenza,
                    data_scadenza=scadenza,
                    giorni_di_ritardo=(today - scadenza).days,
                    # The invoice's own frozen figure, straight off the column. Never a
                    # sum recomputed from the lines: a demand naming an amount the
                    # client's copy does not carry is a demand they are right to ignore.
                    importo=invoice.totale,
                    cliente=customer.ragione_sociale,
                    customer_id=customer.id,
                    solleciti_inviati=int(inviati),
                    ultimo_sollecito_il=ultimo.date() if ultimo is not None else None,
                    # The wording escalates on what *left*, not on how many rows exist:
                    # «nonostante il precedente sollecito» about a letter still sitting in
                    # the drafts folder describes something that never happened.
                    prossimo_livello=int(inviati) + 1,
                    ultima_risposta_il=self._replied_on(account, invoice, customer),
                )
            )

        # Repliers last, then most overdue first. Ordered here rather than in SQL because
        # the reply signal is not a column: it is the result of the per-customer lookup
        # above, and pushing it into the query would mean a join on `gmail_messages` that
        # says nothing clearer.
        candidates.sort(
            key=lambda candidate: (
                candidate.ultima_risposta_il is not None,
                -candidate.giorni_di_ritardo,
            )
        )
        return candidates

    # ---- internals ------------------------------------------------------------------

    def _query(self, grace_cutoff: date) -> Select[CandidateRow]:
        """The invoice/customer/reminder join, with conditions 1 and 2 in the `WHERE`.

        One aggregate over `payment_reminders` rather than N follow-up queries, and it is
        an `OUTER JOIN` on a grouped subquery so that an invoice with no reminders at all
        -- the common case, and the one the whole feature starts from -- still appears.
        """
        reminders = (
            select(
                PaymentReminder.invoice_id.label("invoice_id"),
                func.count().label("righe"),
                # Counted separately from `righe` because they answer different questions:
                # how many positions are occupied, and how many letters a client actually
                # received. See `PaymentReminder`'s own docstring.
                func.count(PaymentReminder.sent_at).label("inviati"),
                func.max(PaymentReminder.sent_at).label("ultimo"),
                func.max(func.coalesce(PaymentReminder.sent_at, PaymentReminder.created_at)).label(
                    "ultima_attivita"
                ),
            )
            .group_by(PaymentReminder.invoice_id)
            .subquery()
        )

        return (
            select(
                Invoice,
                Customer,
                func.coalesce(reminders.c.righe, 0),
                func.coalesce(reminders.c.inviati, 0),
                reminders.c.ultimo,
                reminders.c.ultima_attivita,
            )
            .join(Customer, Customer.id == Invoice.customer_id)
            .outerjoin(reminders, reminders.c.invoice_id == Invoice.id)
            .where(
                # Only an issued fiscal invoice. A `bozza` never left the building and a
                # proforma is not a document anybody owes against; `annullata` is the one
                # that would be actively harmful, because the issuer has withdrawn it.
                Invoice.tipo == CHASEABLE_TIPO,
                Invoice.stato == CHASEABLE_STATO,
                Invoice.deleted_at.is_(None),
                # 1. not collected
                Invoice.stato_pagamento != INCASSATO,
                # 2. overdue by more than the grace period -- chasing the day after the
                #    due date is aggressive and often wrong: the transfer has left.
                #    `data_scadenza` is nullable, and `NULL < date` is NULL rather than
                #    true, so this predicate already excludes an invoice with no agreed
                #    due date. Stated explicitly beside it anyway: it is the only thing
                #    that makes a reminder legitimate, and relying on three-valued logic
                #    to enforce the load-bearing condition is how it goes missing in a
                #    later edit.
                Invoice.data_scadenza.is_not(None),
                Invoice.data_scadenza < grace_cutoff,
                Customer.deleted_at.is_(None),
            )
            .order_by(Invoice.data_scadenza)
        )

    def _mailbox_of(self, actor: Actor) -> GoogleAccount | None:
        """The mailbox whose correspondence answers "did the client write back".

        The asker's own first, because a reply lives in the mailbox that received it and
        another user's inbox cannot answer this user's question. `any_account()` is the
        fallback for the two callers that have no user behind them -- the cron and a
        system actor -- and `None` is a supported answer: an installation with no Gmail
        connected still has invoices to chase, it simply carries no reply signal.
        """
        if actor.id is not None:
            mine = self.repo.account_for_user(actor.id)
            if mine is not None:
                return mine
        return self.repo.any_account()

    def _replied_on(
        self, account: GoogleAccount | None, invoice: Invoice, customer: Customer
    ) -> date | None:
        """When this client last wrote back about this invoice, or `None`.

        The signal the previous system could not have had: from the moment the CRM reads the mail, the
        list can say "the client replied on 12 August". It does not suppress the candidate
        -- a reply is not a payment, and sometimes the reply is exactly what needs chasing
        -- but it sorts last and it says so.

        The window opens at the invoice's own emission date, so a conversation from
        before the invoice existed cannot be mistaken for an answer to it.
        """
        if account is None:
            return None
        since = invoice.data_emissione or invoice.data_scadenza
        if since is None:  # pragma: no cover - the query's own WHERE excludes it
            return None
        reply = self.repo.last_inbound_from(
            account.id,
            self._addresses_of(customer),
            datetime.combine(since, datetime.min.time(), tzinfo=UTC),
        )
        return reply.internal_date.date() if reply is not None else None

    def _addresses_of(self, customer: Customer) -> list[str]:
        """The customer's own address plus every live person on it.

        Both, and not just the first: on a small company the person who answers is rarely
        the generic address on the customer row, so reading only `customers.email` would
        report "nobody replied" about a conversation that is already open.
        """
        addresses = [customer.email.lower()] if customer.email else []
        addresses.extend(
            address.lower()
            for address in self.session.execute(
                select(Person.email).where(
                    Person.customer_id == customer.id,
                    Person.email.is_not(None),
                    Person.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
            if address
        )
        return list(dict.fromkeys(addresses))


__all__ = ["SollecitiService"]
