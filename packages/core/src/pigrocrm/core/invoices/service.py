"""The only writer of `invoices` and `invoice_lines`.

This task covers everything that happens before a number exists. A draft and a
proforma are ordinary mutable rows; the number, the freezing and the artefacts belong
to `issue`, `annul` and the artefact methods added by the following tasks.
"""

import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.clock import ITALY_TZ, oggi_in_italia
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.schemas import DocumentCreate
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, ImmutableField, NotFound, ValidationFailed
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.fiscal.regime import RegimeStrategy, resolve_regime
from pigrocrm.core.fiscal.schemas import FiscalSnapshot
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices import pdf as invoice_pdf
from pigrocrm.core.invoices.fatturapa import (
    FatturaPAExporter,
    check_party_exportable,
    check_recipient_routing,
    normalise_fiscal_id,
)
from pigrocrm.core.invoices.models import Invoice, InvoiceLine, InvoiceRegisterGap
from pigrocrm.core.invoices.naming import (
    invoice_storage_prefix,
    numero_completo,
    proforma_riferimento,
    proforma_storage_prefix,
    sdi_filename,
)
from pigrocrm.core.invoices.repository import InvoiceRepository
from pigrocrm.core.invoices.schemas import (
    ANNO_MAX,
    ANNO_MIN,
    DIVISA,
    SNAPSHOT_VERSIONE,
    TIPO_DOCUMENTO,
    ArtifactKind,
    InvoiceAnnul,
    InvoiceArtifact,
    InvoiceCreate,
    InvoiceForExport,
    InvoiceImport,
    InvoiceIssue,
    InvoiceLineIn,
    InvoiceLineRead,
    InvoiceListQuery,
    InvoicePage,
    InvoiceRead,
    InvoiceSnapshot,
    InvoiceTransmitted,
    InvoiceUpdate,
    PartySnapshot,
    PaymentState,
    RegisterGapRead,
    RegisterGapsDeclare,
)
from pigrocrm.core.invoices.totals import (
    MONEY_MAX_EXCLUSIVE,
    ComputedLine,
    build_riepilogo,
    line_total,
    overflows_money_column,
    round_money,
    sum_totals,
)
from pigrocrm.core.schemas import reject_cleared_columns, supplied_changes
from pigrocrm.core.storage.base import DocumentStorage

ENTITY: EntityType = "invoice"
ZERO = Decimal("0.00")
IMPORT_ACTION = "import_issued_invoice"
GAPS_ACTION = "declare_invoice_register_gaps"

# What stays writable once a `fattura` has left the `bozza` state (spec 4). Everything
# else on the row is frozen, and an attempt raises `ImmutableField` naming the field.
# `stato_pagamento`/`data_incasso` are absent because they have their own method, which
# is what makes their agreement checkable; `stato` is absent for the same reason.
MUTABLE_AFTER_ISSUE: frozenset[str] = frozenset({"note_interne", "custom_fields"})


class InvoiceService:
    def __init__(
        self, session: Session, storage: DocumentStorage, settings: Settings | None = None
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings or get_settings()
        self.repo = InvoiceRepository(session)
        self.fields = FieldDefinitionService(session)
        self.activities = ActivityService(session)
        self.fiscal = FiscalProfileService(session)
        self.emitter = EmitterProfileService(session)
        self.documents = DocumentService(session, storage, self.settings)

    # ---- shared helpers -------------------------------------------------------

    def _check_owner(self, customer_id: UUID, deal_id: UUID | None) -> None:
        """A syntactically valid but unknown UUID becomes this project's own
        `NotFound` instead of a raw `ForeignKeyViolation` reaching the caller from
        `flush()`. The nullable `deal_id` is checked too whenever a value is supplied
        -- skipping a nullable FK is the defect `deals.owner_id` shipped with."""
        if self.session.get(Customer, customer_id) is None:
            raise NotFound("customer", customer_id)
        if deal_id is None:
            return
        deal = self.session.get(Deal, deal_id)
        if deal is None:
            raise NotFound("deal", deal_id)
        if deal.customer_id != customer_id:
            raise ValidationFailed(
                ENTITY,
                "deal_id",
                "il deal appartiene a un altro cliente",
                expected=f"un deal del cliente {customer_id}",
            )

    def _regime(self) -> tuple[RegimeStrategy, FiscalSnapshot]:
        """The strategy and the parameters, read together so a caller cannot pair a
        profile with the wrong strategy. Raises `NotFound("fiscal_profile", ...)` when
        nothing is configured, which tells the user which screen to go to."""
        profile = self.fiscal.snapshot()
        return resolve_regime(profile.codice_regime), profile

    def _computed_lines(
        self, righe: Sequence[InvoiceLineIn], profile: FiscalSnapshot
    ) -> tuple[ComputedLine, ...]:
        """Caller input plus the regime's answer, renumbered from 1.

        Renumbering here is what maintains contiguity: the unique constraint on
        `(invoice_id, numero_linea)` and the `>= 1` check are the database's half, and
        no single-row `CHECK` can see the other rows.
        """
        strategy = resolve_regime(profile.codice_regime)
        computed: list[ComputedLine] = []
        for index, riga in enumerate(righe, start=1):
            aliquota, natura, riferimento = strategy.resolve_line_vat(riga.aliquota_iva, profile)
            prezzo_totale = line_total(
                quantita=riga.quantita,
                prezzo_unitario=riga.prezzo_unitario,
                sconto_percentuale=riga.sconto_percentuale,
                sconto_importo=riga.sconto_importo,
            )
            # The factors mirror `Numeric(12, 6)` in the schema; their product goes to
            # `invoice_lines.prezzo_totale`, which is `Numeric(12, 2)`, and no Pydantic
            # bound on two factors can express a bound on their product. Refused here,
            # before anything is flushed: Postgres answers an overflow with
            # `NumericValueOutOfRange`, which SQLAlchemy raises as `DataError` and not
            # `IntegrityError`, so no handler catches it -- an unhandled 500 with the
            # caller's transaction already aborted. The line is named because an invoice
            # may carry `MAX_LINES` of them.
            if overflows_money_column(prezzo_totale):
                raise ValidationFailed(
                    ENTITY,
                    "righe",
                    f"l'importo della riga {index} non e' rappresentabile: quantita per "
                    "prezzo unitario, al netto degli sconti, supera il massimo",
                    expected=f"un importo con valore assoluto inferiore a {MONEY_MAX_EXCLUSIVE}",
                )
            computed.append(
                ComputedLine(
                    numero_linea=index,
                    descrizione=riga.descrizione,
                    quantita=riga.quantita,
                    unita_misura=riga.unita_misura,
                    prezzo_unitario=riga.prezzo_unitario,
                    sconto_percentuale=riga.sconto_percentuale,
                    sconto_importo=riga.sconto_importo,
                    prezzo_totale=prezzo_totale,
                    aliquota_iva=aliquota,
                    natura=natura,
                    riferimento_normativo=riferimento,
                )
            )
        return tuple(computed)

    def _apply_totals(
        self, invoice: Invoice, computed: Sequence[ComputedLine], profile: FiscalSnapshot
    ) -> None:
        """Compute and **store**. Never recomputed by a client: a total computed in
        the browser is the structural defect inherited from Acme, and on an invoice it
        costs more."""
        strategy = resolve_regime(profile.codice_regime)
        riepilogo = build_riepilogo(computed)
        imponibile, imposta, totale = sum_totals(riepilogo)
        # The stamp duty is stored but does not enter the total: `DatiBollo` declares
        # that the issuer settled it virtually (spec 7.2).
        bollo = strategy.bollo(riepilogo, profile)

        # Summation reaches the same overflow with no oversized line anywhere:
        # `InvoiceCreate.righe` admits `MAX_LINES` of them, and two hundred lines of
        # fifty million each are two hundred perfectly ordinary amounts whose sum is not.
        # Checked before a single attribute is assigned, so a refused invoice leaves no
        # unstorable value sitting on a mapped object for the next autoflush to find.
        for field, value in (
            ("imponibile", imponibile),
            ("imposta", imposta),
            ("totale", totale),
            ("bollo", bollo),
        ):
            if overflows_money_column(value):
                raise ValidationFailed(
                    ENTITY,
                    field,
                    f"la somma delle righe non e' rappresentabile: {field} supera il massimo",
                    expected=f"un importo con valore assoluto inferiore a {MONEY_MAX_EXCLUSIVE}",
                )

        invoice.imponibile = imponibile
        invoice.imposta = imposta
        invoice.totale = totale
        invoice.bollo = bollo

    def _persist_lines(self, invoice: Invoice, computed: Sequence[ComputedLine]) -> None:
        self.repo.clear_lines(invoice.id)
        for riga in computed:
            self.repo.add_line(
                InvoiceLine(
                    invoice_id=invoice.id,
                    numero_linea=riga.numero_linea,
                    descrizione=riga.descrizione,
                    quantita=riga.quantita,
                    unita_misura=riga.unita_misura,
                    prezzo_unitario=riga.prezzo_unitario,
                    sconto_percentuale=riga.sconto_percentuale,
                    sconto_importo=riga.sconto_importo,
                    prezzo_totale=riga.prezzo_totale,
                    aliquota_iva=riga.aliquota_iva,
                    natura=riga.natura,
                    riferimento_normativo=riga.riferimento_normativo,
                )
            )

    def _validated_custom(self, values: dict[str, Any]) -> dict[str, Any]:
        return validate_custom_fields(ENTITY, self.fields.specs_for(ENTITY), values)

    def _update_custom_fields(self, invoice: Invoice, provided: dict[str, Any]) -> dict[str, Any]:
        """Validates only the keys the caller is touching, never the merge with what is
        stored -- identical in shape to `CustomerService._update_custom_fields`, and for
        the same reason: re-validating the merge would let archiving a field block every
        future custom-field update on rows that still hold it."""
        active_by_key = {spec.key: spec for spec in self.fields.specs_for(ENTITY)}
        to_remove: set[str] = set()
        for key, value in provided.items():
            if value is not None:
                continue
            spec = active_by_key.get(key)
            if spec is not None and spec.required:
                raise ValidationFailed(
                    ENTITY, key, "campo obbligatorio", expected="un valore non vuoto"
                )
            to_remove.add(key)
        to_set = {key: value for key, value in provided.items() if value is not None}
        touched = [spec for spec in active_by_key.values() if spec.key in to_set]
        merged = {k: v for k, v in invoice.custom_fields.items() if k not in to_remove}
        merged.update(validate_custom_fields(ENTITY, touched, to_set))
        return merged

    def _is_editable(self, invoice: Invoice) -> bool:
        """A `fattura` is editable only as a `bozza`; a `proforma` is editable until it
        is `consumata`. That asymmetry is the point of a proforma (spec 5): agree the
        amount, correct it as many times as needed, without touching the register."""
        if invoice.tipo == "proforma":
            return invoice.stato in ("bozza", "confermata")
        return invoice.stato == "bozza"

    def _require_editable(self, invoice: Invoice, field: str) -> None:
        if not self._is_editable(invoice):
            raise ImmutableField(
                ENTITY,
                field,
                f"una fattura in stato '{invoice.stato}' e' un documento fiscale: "
                "si corregge con un annullamento e una nuova emissione, non con una modifica",
            )

    # ---- writes ---------------------------------------------------------------

    def create(self, data: InvoiceCreate, actor: Actor) -> InvoiceRead:
        """A draft or a proforma. Neither has a number, which is why a failed creation
        cannot burn one -- not as a matter of care, but because there is nothing to
        burn until `issue` runs."""
        actor.require_write("create_invoice")
        self._check_owner(data.customer_id, data.deal_id)
        _, profile = self._regime()

        invoice = Invoice(
            customer_id=data.customer_id,
            deal_id=data.deal_id,
            tipo=data.tipo,
            stato="bozza",
            tipo_documento=TIPO_DOCUMENTO,
            divisa=DIVISA,
            causale=data.causale,
            note_interne=data.note_interne,
            imponibile=ZERO,
            imposta=ZERO,
            bollo=ZERO,
            totale=ZERO,
            stato_pagamento="da_incassare",
            custom_fields=self._validated_custom(data.custom_fields or {}),
        )
        if data.tipo == "proforma":
            # `oggi_in_italia()`, not `date.today()`: see `clock.py`'s module docstring
            # for why a bare `date.today()` on a host that is not running in
            # Europe/Rome (this project's own `Dockerfile.api` pins no `TZ`, so its
            # base image defaults to UTC) reproduces Acme's UTC-instant defect
            # through the standard library's default rather than an explicit
            # conversion. Low-stakes here specifically -- `riferimento` is a
            # non-fiscal, internal-only identifier, not a register entry -- but there
            # is no reason to let the wrong clock answer the question at all.
            invoice.riferimento = proforma_riferimento(
                oggi_in_italia().year, self.repo.next_proforma_sequence()
            )
        computed = self._computed_lines(data.righe, profile)
        self._apply_totals(invoice, computed, profile)
        self.repo.add(invoice)
        self._persist_lines(invoice, computed)
        self.activities.record(
            ENTITY,
            invoice.id,
            "created",
            actor,
            {"tipo": invoice.tipo, "righe": len(computed), "totale": str(invoice.totale)},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def update(self, invoice_id: UUID, data: InvoiceUpdate, actor: Actor) -> InvoiceRead:
        actor.require_write("update_invoice")
        invoice = self._require(invoice_id)
        changes = supplied_changes(data, exclude={"custom_fields"})
        reject_cleared_columns(ENTITY, Invoice, changes)
        frozen = [key for key in changes if key not in MUTABLE_AFTER_ISSUE]
        if frozen and not self._is_editable(invoice):
            raise ImmutableField(
                ENTITY,
                sorted(frozen)[0],
                f"campo congelato su un documento in stato '{invoice.stato}'",
            )
        if data.custom_fields is not None:
            changes["custom_fields"] = self._update_custom_fields(invoice, data.custom_fields)
        for key, value in changes.items():
            setattr(invoice, key, value)
        self.activities.record(ENTITY, invoice.id, "updated", actor, {"changed": sorted(changes)})
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def replace_lines(
        self, invoice_id: UUID, righe: list[InvoiceLineIn], actor: Actor
    ) -> InvoiceRead:
        """The whole list, never a partial patch.

        The reason from spec 11 that still stands: it is the natural shape of a line
        editor, and a line's totals are derived from the whole list, so patching one
        line in place would leave the invoice's totals to be reconciled separately. The
        second reason it was written for -- that while `exclude_none=True` was the
        update contract no optional numeric or date column could be cleared at all
        (A14) -- was retired by task 4B-1, which closed that defect rather than
        continuing to sidestep it.
        """
        actor.require_write("replace_invoice_lines")
        invoice = self._require(invoice_id)
        self._require_editable(invoice, "righe")
        _, profile = self._regime()
        computed = self._computed_lines(righe, profile)
        self._apply_totals(invoice, computed, profile)
        self._persist_lines(invoice, computed)
        self.activities.record(
            ENTITY,
            invoice.id,
            "lines_replaced",
            actor,
            {"righe": len(computed), "totale": str(invoice.totale)},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def confirm_proforma(self, invoice_id: UUID, actor: Actor) -> InvoiceRead:
        """`bozza` -> `confermata` on a proforma: the amount is agreed and the document
        is ready to be sent, still without touching the register."""
        actor.require_write("confirm_proforma")
        invoice = self._require(invoice_id)
        if invoice.tipo != "proforma":
            raise Conflict(
                ENTITY, "solo una proforma si conferma", tipo=invoice.tipo, stato=invoice.stato
            )
        if invoice.stato != "bozza":
            raise Conflict(
                ENTITY,
                f"da '{invoice.stato}' non si puo' passare a 'confermata'",
                stato_attuale=invoice.stato,
            )
        if not self.repo.lines(invoice.id):
            raise ValidationFailed(
                ENTITY,
                "righe",
                "una proforma senza righe non si conferma",
                expected="almeno una riga",
            )
        invoice.stato = "confermata"
        self.activities.record(ENTITY, invoice.id, "confirmed", actor)
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def soft_delete(self, invoice_id: UUID, actor: Actor) -> None:
        """Only what never consumed a number, and never a `consumata` proforma.

        Checked here **and** by `ck_invoices_no_delete_once_consumed`, which is what
        makes the rule true for a psql session too. Without the gap-free register the
        numbering guarantee of spec 3 would be worth nothing: a number that can be
        deleted is a gap with extra steps.
        """
        actor.require_write("delete_invoice")
        invoice = self._require(invoice_id)
        if invoice.numero is not None or invoice.stato == "consumata":
            raise Conflict(
                ENTITY,
                "un documento che ha consumato un numero non si elimina: "
                "si annulla, conservando il numero",
                stato=invoice.stato,
                numero=invoice.numero,
            )
        invoice.deleted_at = datetime.now(UTC)
        self.activities.record(ENTITY, invoice.id, "deleted", actor)
        try:
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a row that was issued concurrently: the
            # CHECK is the real authority, and the rollback is mandatory or the
            # caller's session is unusable on its next statement.
            self.session.rollback()
            raise Conflict(
                ENTITY, "il documento e' stato emesso nel frattempo e non si elimina piu'"
            ) from exc

    def set_payment_state(self, invoice_id: UUID, data: PaymentState, actor: Actor) -> InvoiceRead:
        """Collection is a subsequent fact, not part of the document (spec 4), so this
        is the one invoice write a collaborator -- and an agent -- may perform."""
        actor.require_write("set_payment_state")
        invoice = self._require(invoice_id)
        if invoice.stato != "emessa":
            raise Conflict(
                ENTITY,
                "solo una fattura emessa ha un incasso da registrare",
                stato=invoice.stato,
            )
        if data.stato_pagamento == "incassato" and data.data_incasso is None:
            raise ValidationFailed(
                ENTITY,
                "data_incasso",
                "un incasso senza data non e' un incasso",
                expected="la data in cui il pagamento e' arrivato",
            )
        invoice.stato_pagamento = data.stato_pagamento
        # Cleared rather than left dangling: the table's own
        # `ck_invoices_incasso_requires_state` would refuse the inconsistent pair
        # anyway, and a stale date on an uncollected invoice is a lie either way.
        invoice.data_incasso = data.data_incasso if data.stato_pagamento == "incassato" else None
        self.activities.record(
            ENTITY,
            invoice.id,
            "payment_state_changed",
            actor,
            {"stato_pagamento": invoice.stato_pagamento},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def _party_from_customer(self, customer: Customer) -> PartySnapshot:
        return PartySnapshot(
            ragione_sociale=customer.ragione_sociale,
            partita_iva=customer.partita_iva,
            codice_fiscale=customer.codice_fiscale,
            codice_sdi=customer.codice_sdi,
            pec=customer.pec,
            indirizzo=customer.indirizzo or "",
            cap=customer.cap or "",
            comune=customer.comune or "",
            provincia=customer.provincia or "",
            nazione=customer.nazione,
            email=customer.email,
            telefono=customer.telefono,
            sito_web=customer.sito_web,
        )

    def _party_from_emitter(self, actor: Actor) -> PartySnapshot:
        """The issuer's identity from `emitter_profile` (slice 2).

        `emitter_profile.regime_fiscale` is deliberately not read here: it is a
        human-readable caption for the PDF header, `String(200)` of free text, and the
        machine value the SdI validates is `fiscal_profile.codice_regime`. Two columns,
        two jobs; conflating them is how a caption ends up inside `RegimeFiscale`.
        """
        profile = self.emitter.get(actor)
        return PartySnapshot(
            ragione_sociale=profile.ragione_sociale,
            partita_iva=profile.partita_iva,
            codice_fiscale=profile.codice_fiscale,
            codice_sdi=profile.codice_sdi,
            pec=profile.pec,
            indirizzo=profile.indirizzo or "",
            cap=profile.cap or "",
            comune=profile.comune or "",
            provincia=profile.provincia or "",
            nazione=profile.nazione,
            email=profile.email,
            telefono=profile.telefono,
            sito_web=profile.sito_web,
        )

    def _build_snapshot(
        self, invoice: Invoice, profile: FiscalSnapshot, actor: Actor
    ) -> InvoiceSnapshot:
        customer = self.session.get(Customer, invoice.customer_id)
        if customer is None:  # pragma: no cover - the FK makes this unreachable
            raise NotFound("customer", invoice.customer_id)
        return InvoiceSnapshot(
            versione=SNAPSHOT_VERSIONE,
            emittente=self._party_from_emitter(actor),
            cliente=self._party_from_customer(customer),
            fiscale=profile,
        )

    def _check_issue_date(self, data_emissione: date, anno_corrente: int) -> None:
        """Two limits, both from spec 6.2.

        `data_emissione` is a `date` in the issuer's own calendar, never the UTC
        projection of an instant: `toISOString()` on 31 December at 23:30 CET yields
        1 January, which puts an immutable document in the wrong fiscal year. That is
        the defect this whole method exists around, and the fix is `oggi_in_italia()`
        -- not a bare `date.today()`, which would only be safe if this process were
        guaranteed to run with Italy's own timezone, and it is not (see `clock.py`).
        """
        oggi = oggi_in_italia()
        if data_emissione > oggi:
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "una fattura non si emette con data futura",
                expected=f"una data non successiva a {oggi.isoformat()}",
            )
        if data_emissione < date(anno_corrente, 1, 1):
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "un anno chiuso e' chiuso: non si inserisce nel registro di un anno "
                "precedente dopo che ne e' iniziato uno nuovo",
                expected=f"una data dal {anno_corrente}-01-01 in poi",
            )

    def _check_issuable(self, source: Invoice, from_proforma: bool) -> None:
        """Whether this row may still become a fiscal document.

        Extracted because `issue` asks it twice — cheaply before taking the year's
        counter lock, and authoritatively after — and two copies of a refusal message
        drift. See `issue`'s docstring for why once is not enough.
        """
        if from_proforma:
            if source.stato != "confermata":
                raise Conflict(
                    ENTITY,
                    "solo una proforma confermata si converte in fattura",
                    stato_attuale=source.stato,
                    stato_richiesto="confermata",
                )
        elif source.stato != "bozza":
            raise Conflict(
                ENTITY,
                f"una fattura in stato '{source.stato}' e' gia' stata emessa: "
                "una correzione e' un annullamento e una nuova fattura",
                stato_attuale=source.stato,
            )

    def issue(self, invoice_id: UUID, data: InvoiceIssue, actor: Actor) -> InvoiceRead:
        """Consume a register number. **One transaction, in this exact order.**

        `invoice_id` names either a `bozza` **fattura**, issued in place, or a
        `confermata` **proforma**, in which case a *new* `emessa` row is created with
        the proforma's lines copied and `origine_proforma_id` pointing back at it, and
        the proforma is marked `consumata` (spec 5). One method, because emitting from
        scratch and from a proforma share the lock, the validations, the freezing and
        the numbering, and splitting them would mean two paths to keep aligned on
        exactly the part that must not diverge.

        Ordering, and why each step is where it is:

        1. resolve the source row and the issue date, and check the date against
           "not in the future, not before 1 January of the current year". No lock yet:
           these are pure checks on the caller's own input;
        2. `lock_counter(anno)` -- the **first** row lock this transaction takes;
        3. every fiscal validation, the totals, and the chronological-monotonicity
           check. All of it after the lock, so "the date of the previous number" is a
           safe thing to read, and all of it *before* the counter is touched, so a
           refusal never even reaches the increment;
        4. increment the counter, write the row with `(anno, numero)`, write the
           frozen `snapshot`, write the activity;
        5. `COMMIT`.

        **The number does not exist before the commit.** If any step fails, the
        rollback returns `ultimo_numero` to its previous value and nothing was
        consumed -- the property a `SEQUENCE` does not have.

        The PDF and the XML are produced **after** this commit, in a second
        transaction, from the snapshot. Holding a row lock for the duration of a Typst
        subprocess would serialise every emission on PDF compile time, and an invoice
        is a legal fact independent of its printout: if the render fails, the invoice
        exists with its number and its artefacts regenerate deterministically. That is
        the one documented exception to "one service method = one transaction", and
        spec 3 mandates it.

        Two concurrent `issue()` calls on the same `invoice_id` are **in** scope, and
        this is the one method in the class where that matters. The others --
        `update`, `replace_lines`, `confirm_proforma`, `soft_delete` -- also read via
        `_require` without a lock, and a race there is an ordinary lost update: the
        second write wins and the row is consistent. Here the loser would consume a
        register number and then overwrite the winner's number on the very same row,
        leaving the first number owned by no invoice. `uq_invoices_anno_numero` cannot
        see it, because the row simply carries a different number. That is a permanent
        gap in the register -- the single property this whole design exists to
        guarantee, and the reason it is a locked counter row rather than a `SEQUENCE`.

        The cure needs no new lock and no lock-order decision. The state is checked
        twice: once before the counter lock, to refuse an obviously-doomed request
        without serialising on it, and once *after*, which is the authoritative one.
        `lock_counter` blocks until the other emission's transaction ends, so by the
        time this transaction holds that lock the competing commit is visible, and the
        re-read sees `emessa`. The order stays counter-then-row throughout, so the
        deadlock argument in `lock_counter`'s own docstring is unchanged.
        """
        actor.require_admin("issue_invoice")
        source = self._require(invoice_id)
        data_emissione = data.data_emissione or oggi_in_italia()
        anno = data_emissione.year
        self._check_issue_date(data_emissione, oggi_in_italia().year)

        from_proforma = source.tipo == "proforma"
        self._check_issuable(source, from_proforma)

        # Step 2. From here on, every other emission for this year waits.
        counter = self.repo.lock_counter(anno)

        # An imported register can arrive with numbers out of order -- the whole point
        # of slice 9 is that the history is not imported number-by-number in sequence.
        # A gap in it is *silent* until someone names it (`declare_gaps`), and native
        # issuing must not resume on top of a silent gap: doing so would make the next
        # native number look like it continues a register that in fact has an
        # unexplained hole underneath it. Checked here, inside the same lock that
        # protects the increment below, so a concurrent import cannot close the gap
        # and let this call through on a stale read.
        buchi = self.undeclared_gaps(anno)
        if buchi:
            raise Conflict(
                ENTITY,
                f"il registro importato ha buchi non dichiarati ai numeri {buchi}: "
                "dichiarali (o importali) prima di riprendere a emettere",
                anno=anno,
                numeri=buchi,
            )

        # And only now is the state answer trustworthy. The check above ran against a
        # read taken before any lock: a competing `issue()` on this same row could have
        # been between its own check and its own commit at that moment. Acquiring the
        # counter lock is what orders the two transactions -- it is released only at the
        # other one's commit -- so re-reading here sees whatever that emission actually
        # did. Without this, both calls pass the check, both take a number, and the
        # second overwrites the first: one number consumed and carried by nobody.
        self.session.refresh(source)
        self._check_issuable(source, from_proforma)

        # Step 3. Validations and totals, after the lock and before the increment.
        _, profile = self._regime()
        snapshot = self._build_snapshot(source, profile, actor)
        check_party_exportable(snapshot.emittente, "emitter_profile")
        check_party_exportable(snapshot.cliente, "customer")
        check_recipient_routing(snapshot.cliente)

        righe = self.repo.lines(source.id)
        if not righe:
            raise ValidationFailed(
                ENTITY,
                "righe",
                "una fattura senza righe non si emette",
                expected="almeno una riga",
            )
        computed = tuple(
            ComputedLine(
                numero_linea=r.numero_linea,
                descrizione=r.descrizione,
                quantita=r.quantita,
                unita_misura=r.unita_misura,
                prezzo_unitario=r.prezzo_unitario,
                sconto_percentuale=r.sconto_percentuale,
                sconto_importo=r.sconto_importo,
                prezzo_totale=r.prezzo_totale,
                aliquota_iva=r.aliquota_iva,
                natura=r.natura,
                riferimento_normativo=r.riferimento_normativo,
            )
            for r in righe
        )
        riepilogo = build_riepilogo(computed)
        imponibile, imposta, totale = sum_totals(riepilogo)
        if totale <= ZERO:
            raise ValidationFailed(
                ENTITY,
                "totale",
                "una TD01 a zero o negativa non e' una fattura",
                expected="un totale maggiore di zero",
            )

        previous = self.repo.last_issued_date(anno)
        if previous is not None and data_emissione < previous:
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "il registro deve restare cronologicamente monotono rispetto al numero: "
                f"l'ultima fattura del {anno} porta la data {previous.isoformat()}",
                expected=f"una data dal {previous.isoformat()} in poi",
            )

        # Step 4. Increment, write, freeze.
        counter.ultimo_numero += 1
        numero = counter.ultimo_numero

        target = source
        if from_proforma:
            target = self.repo.add(
                Invoice(
                    customer_id=source.customer_id,
                    deal_id=source.deal_id,
                    tipo="fattura",
                    stato="bozza",
                    tipo_documento=TIPO_DOCUMENTO,
                    divisa=DIVISA,
                    causale=source.causale,
                    note_interne=source.note_interne,
                    imponibile=ZERO,
                    imposta=ZERO,
                    bollo=ZERO,
                    totale=ZERO,
                    stato_pagamento="da_incassare",
                    origine_proforma_id=source.id,
                    custom_fields=dict(source.custom_fields),
                )
            )
            self._persist_lines(target, computed)
            source.stato = "consumata"

        strategy = resolve_regime(profile.codice_regime)
        target.stato = "emessa"
        target.anno = anno
        target.numero = numero
        target.data_emissione = data_emissione
        target.data_scadenza = data_emissione + timedelta(days=profile.giorni_scadenza)
        target.imponibile = imponibile
        target.imposta = imposta
        target.totale = totale
        target.bollo = strategy.bollo(riepilogo, profile)
        target.snapshot = snapshot.model_dump(mode="json")
        target.snapshot_versione = SNAPSHOT_VERSIONE

        self.activities.record(
            ENTITY,
            target.id,
            "issued",
            actor,
            {
                "anno": anno,
                "numero": numero,
                "totale": str(target.totale),
                "origine_proforma_id": str(source.id) if from_proforma else None,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as exc:
            # The partial unique index `uq_invoices_anno_numero` is the net under the
            # row lock, not the mechanism (spec 3). Reaching it means something wrote
            # a number without taking the lock -- an importer, a direct INSERT, a
            # second service -- and this is what makes that failure observable instead
            # of a silent duplicate. The rollback is mandatory or the caller's session
            # is unusable on its next statement.
            self.session.rollback()
            raise Conflict(
                ENTITY,
                "un altro processo ha scritto lo stesso numero senza passare dal "
                "contatore: riprova e verifica il registro",
                anno=anno,
                numero=numero,
            ) from exc

        # Spec 3 asks for the render to happen **after** this commit, in a second
        # transaction, and it is right: holding the counter's row lock for the duration
        # of a Typst subprocess would serialise every emission on PDF compile time, and
        # an invoice is a legal fact independent of its printout.
        #
        # But the second transaction belongs to the **caller**, not to this method. When
        # `issue` called `produce_artifacts` itself, `issue` stopped being one
        # transaction: the artefact commit survived the test fixture's rollback, so an
        # issued invoice leaked across tests and the next first-invoice-of-2026 collided
        # on `uq_invoices_anno_numero`. Eight tests failed that way, and three more on
        # the `documents` row pinning a customer that teardown then could not remove.
        #
        # A leak that only shows up as someone else's failing test is the cheap version
        # of the same defect in production, where the transaction boundary would be
        # equally invisible and the consequence a partially-committed emission. So
        # `issue` returns here, one method and one transaction, and the adapters call
        # `produce_artifacts` next -- which is idempotent and regenerates from the
        # snapshot, so a crash between the two leaves an invoice that is fiscally
        # complete and merely unprinted.
        return InvoiceRead.model_validate(target)

    def import_issued(self, data: InvoiceImport, actor: Actor) -> InvoiceRead:
        """Register a fattura that another system issued (slice 9 §3).

        Same lock, same snapshot, same lines as `issue`; the two differences are the
        whole feature. The number is *declared*, so the counter follows it instead of
        producing it (§3.2 rule 3). And the totals are *declared*, so they are checked
        against the lines to the cent instead of recomputed (§3.3): the document the
        customer holds is the fact, and this method refuses to record a different one.

        Order: pure checks on the input, then `lock_counter(anno)` -- the first and only
        row lock -- then every check that reads the register (duplicates, neighbours,
        gaps, native numbers), then the write. Nothing is consumed on failure: the
        counter is only ever raised to a number that is being written in the same
        transaction.
        """
        actor.require_admin(IMPORT_ACTION)
        self._check_owner(data.customer_id, data.deal_id)
        self._check_import_date(data.data_emissione)
        self._check_declared_totals(data)
        if data.anno != data.data_emissione.year:
            raise ValidationFailed(
                ENTITY,
                "anno",
                "l'anno del registro deve essere quello della data di emissione",
                expected=f"anno = {data.data_emissione.year}",
            )
        if data.stato_pagamento == "incassato" and data.data_incasso is None:
            raise ValidationFailed(
                ENTITY,
                "data_incasso",
                "un incasso senza data non e' un incasso",
                expected="la data in cui il pagamento e' arrivato",
            )
        if data.stato_pagamento != "incassato" and data.data_incasso is not None:
            raise ValidationFailed(
                ENTITY,
                "data_incasso",
                "una data di incasso senza incasso non ha senso",
                expected="stato_pagamento = incassato, oppure nessuna data",
            )
        counter = self.repo.lock_counter(data.anno)
        if data.numero in self.repo.numbers_present(data.anno):
            raise Conflict(
                ENTITY,
                "il registro porta gia' questo numero",
                anno=data.anno,
                numero=data.numero,
            )
        if data.numero in self.repo.declared_gaps(data.anno):
            raise Conflict(
                ENTITY,
                "questo numero e' dichiarato come buco del registro: togli la dichiarazione "
                "prima di importarlo",
                anno=data.anno,
                numero=data.numero,
            )
        first_native = self.repo.first_native_number(data.anno)
        if first_native is not None and data.numero > first_native:
            raise Conflict(
                ENTITY,
                "PigroCRM ha gia' emesso fatture in questo anno: si importa solo lo storico "
                "precedente alla prima emessa qui",
                anno=data.anno,
                numero=data.numero,
                prima_nativa=first_native,
            )
        before, after = self.repo.neighbour_dates(data.anno, data.numero)
        if before is not None and data.data_emissione < before:
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "il registro deve restare cronologico: il numero precedente porta la data "
                f"{before.isoformat()}",
                expected=f"una data dal {before.isoformat()} in poi",
            )
        if after is not None and data.data_emissione > after:
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "il registro deve restare cronologico: il numero successivo porta la data "
                f"{after.isoformat()}",
                expected=f"una data fino al {after.isoformat()}",
            )
        _, profile = self._regime()
        invoice = self.repo.add(
            Invoice(
                customer_id=data.customer_id,
                deal_id=data.deal_id,
                tipo="fattura",
                stato="emessa",
                anno=data.anno,
                numero=data.numero,
                data_emissione=data.data_emissione,
                data_scadenza=data.data_scadenza
                or data.data_emissione + timedelta(days=profile.giorni_scadenza),
                tipo_documento=TIPO_DOCUMENTO,
                divisa=DIVISA,
                causale=data.causale,
                imponibile=data.imponibile,
                imposta=data.imposta,
                bollo=data.bollo,
                totale=data.totale,
                stato_pagamento=data.stato_pagamento,
                data_incasso=data.data_incasso,
                trasmessa_esternamente_il=data.trasmessa_esternamente_il,
                note_interne=data.note_interne,
                importata_da=data.importata_da,
                custom_fields={},
            )
        )
        for index, riga in enumerate(data.righe, start=1):
            self.repo.add_line(
                InvoiceLine(
                    invoice_id=invoice.id,
                    numero_linea=index,
                    descrizione=riga.descrizione,
                    quantita=riga.quantita,
                    unita_misura=riga.unita_misura,
                    prezzo_unitario=riga.prezzo_unitario,
                    prezzo_totale=riga.prezzo_totale,
                    aliquota_iva=riga.aliquota_iva,
                    natura=riga.natura,
                    riferimento_normativo=riga.riferimento_normativo,
                )
            )
        snapshot = self._build_snapshot(invoice, profile, actor)
        invoice.snapshot = snapshot.model_dump(mode="json")
        invoice.snapshot_versione = SNAPSHOT_VERSIONE
        if data.pdf_sorgente is not None:
            invoice.pdf_document_id = self._adopt_original_pdf(
                invoice, data.pdf_sorgente.document_id
            )
        counter.ultimo_numero = max(counter.ultimo_numero, data.numero)
        self.activities.record(
            ENTITY,
            invoice.id,
            "imported",
            actor,
            {
                "anno": data.anno,
                "numero": data.numero,
                "totale": str(data.totale),
                "importata_da": data.importata_da,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise Conflict(
                ENTITY,
                "un altro processo ha scritto lo stesso numero: riprova e verifica il registro",
                anno=data.anno,
                numero=data.numero,
            ) from exc
        return self.get(invoice.id, actor)

    def _check_import_date(self, data_emissione: date) -> None:
        """Only "not in the future" (§3.2 rule 5). `_check_issue_date` also refuses a
        closed year, and a closed year is exactly what an import fills."""
        oggi = oggi_in_italia()
        if data_emissione > oggi:
            raise ValidationFailed(
                ENTITY,
                "data_emissione",
                "una fattura non si importa con data futura",
                expected=f"una data non successiva a {oggi.isoformat()}",
            )

    def _check_declared_totals(self, data: InvoiceImport) -> None:
        somma_righe = round_money(sum((r.prezzo_totale for r in data.righe), Decimal("0")))
        if somma_righe != round_money(data.imponibile):
            raise ValidationFailed(
                ENTITY,
                "imponibile",
                f"l'imponibile dichiarato ({data.imponibile}) non e' la somma delle righe "
                f"({somma_righe})",
                expected="imponibile uguale alla somma dei prezzi totali di riga",
            )
        atteso = round_money(data.imponibile + data.imposta + data.bollo)
        if atteso != round_money(data.totale):
            raise ValidationFailed(
                ENTITY,
                "totale",
                f"il totale dichiarato ({data.totale}) non e' imponibile + imposta + bollo "
                f"({atteso})",
                expected="totale uguale a imponibile + imposta + bollo",
            )
        if data.totale <= ZERO:
            raise ValidationFailed(
                ENTITY,
                "totale",
                "una TD01 a zero o negativa non e' una fattura",
                expected="un totale maggiore di zero",
            )

    def _adopt_original_pdf(self, invoice: Invoice, document_id: UUID) -> UUID:
        raise NotImplementedError  # Task 6

    def _check_register_year(self, anno: int) -> None:
        """Bound `anno` before it reaches a lock or a query.

        Every other `anno` in this domain is bounded the same way
        (`InvoiceImport.anno`, `InvoiceListQuery.anno`, both `Field(ge=ANNO_MIN,
        le=ANNO_MAX)`), and these three methods are the one place a bare `int` from a
        caller reaches `lock_counter`'s raw `INSERT INTO invoice_counters` or a
        register query directly. An out-of-range value would otherwise surface as a
        Postgres `integer out of range` `DataError` -- not something a caller can act
        on -- or, for a smaller-but-still-nonsense year, silently create junk
        counter/gap rows for a year nothing else in the system will ever ask about.
        """
        if not ANNO_MIN <= anno <= ANNO_MAX:
            raise ValidationFailed(
                ENTITY,
                "anno",
                "anno fuori dal registro",
                expected=f"un anno fra {ANNO_MIN} e {ANNO_MAX}",
            )

    def declare_gaps(
        self, anno: int, data: RegisterGapsDeclare, actor: Actor
    ) -> list[RegisterGapRead]:
        """Name the numbers the register will never carry, and why (spec 9 §3.2 rule 4).

        A declared gap is the honest alternative to two dishonest ones: inventing a row
        to fill it, or leaving it silent so that it looks like a lost invoice. It is
        refused for a number that *is* an invoice, and the import refuses a number that
        is a declared gap: the two sets never overlap.

        `lock_counter(anno)` first, for the same reason `import_issued` takes it before
        reading `numbers_present`/`declared_gaps`: without it, a gap declared here and
        an import of the same number could each read the register before the other's
        write, and both would go through.

        `data.buchi` carries no uniqueness rule of its own, so `seen` refuses a
        same-batch duplicate `numero` before it ever reaches `add_gap`'s flush -- and
        the loop plus the final commit are wrapped together, because a *concurrent*
        declaration of the same number can still reach the unique index underneath
        `uq_invoice_register_gaps_anno_numero` after this transaction's own read of
        `already`. Either way the rollback is mandatory, or the caller's session is
        unusable on its next statement (see `issue` and `import_issued`, which wrap
        their own commits for exactly this reason).
        """
        actor.require_admin(GAPS_ACTION)
        self._check_register_year(anno)
        self.repo.lock_counter(anno)
        present = self.repo.numbers_present(anno)
        already = self.repo.declared_gaps(anno)
        seen: set[int] = set()
        try:
            for buco in data.buchi:
                if buco.numero in present:
                    raise Conflict(
                        ENTITY,
                        "questo numero e' una fattura del registro, non un buco",
                        anno=anno,
                        numero=buco.numero,
                    )
                if buco.numero in already or buco.numero in seen:
                    raise Conflict(ENTITY, "buco gia' dichiarato", anno=anno, numero=buco.numero)
                seen.add(buco.numero)
                self.repo.add_gap(
                    InvoiceRegisterGap(
                        anno=anno,
                        numero=buco.numero,
                        motivo=buco.motivo,
                        dichiarato_da=actor.id,
                    )
                )
                # The register has no row of its own to hang a timeline entry on, so
                # the entity id is derived deterministically from the year rather than
                # left unrecorded: `ActivityService.record` accepts any `entity_type`
                # string (it is not constrained to `EntityType`), and `uuid5` gives the
                # same id every time this year's register is touched again.
                self.activities.record(
                    "invoice_register",
                    uuid5(NAMESPACE_URL, f"pigrocrm:invoice_register:{anno}"),
                    "gap_declared",
                    actor,
                    {"anno": anno, "numero": buco.numero, "motivo": buco.motivo},
                )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise Conflict(
                ENTITY, "un altro processo ha dichiarato lo stesso buco: riprova", anno=anno
            ) from exc
        return self.register_gaps(anno, actor)

    def register_gaps(self, anno: int, actor: Actor) -> list[RegisterGapRead]:
        self._check_register_year(anno)
        return [RegisterGapRead.model_validate(g) for g in self.repo.gaps(anno)]

    def undeclared_gaps(self, anno: int) -> list[int]:
        """Numbers between the lowest imported one and the highest that are neither an
        invoice nor a declared gap. Empty is the only state in which native issuing may
        resume (spec 9 §3.2 rule 4): an import can arrive in any order, so a hole is
        expected until the operator has looked at every one of them and either imported
        or declared it.
        """
        self._check_register_year(anno)
        present = self.repo.numbers_present(anno)
        if not present:
            return []
        declared = self.repo.declared_gaps(anno)
        top = max(present)
        return [n for n in range(min(present), top) if n not in present and n not in declared]

    def annul(self, invoice_id: UUID, data: InvoiceAnnul, actor: Actor) -> InvoiceRead:
        """Strike the page through; keep the number.

        The number **stays consumed** and the row stays readable: that is what
        preserves the gap-free property of spec 3, which would otherwise be worth
        nothing -- a number that can disappear is a gap with extra steps.

        Refused once the file has been handed to the intermediary. From that point the
        correction requires a credit note (`TD04`), which this slice does not produce
        for a structural reason rather than as a deferral: a credit note corrects an
        invoice **already accepted by the SdI**, and nothing here is transmitted. So
        the application says where the correction has to happen, instead of offering a
        button that pretends to solve it.
        """
        actor.require_admin("annul_invoice")
        invoice = self._require(invoice_id)
        if invoice.stato != "emessa":
            raise Conflict(
                ENTITY,
                "si annulla solo una fattura emessa: una bozza si elimina, "
                "una fattura gia' annullata non si annulla due volte",
                stato_attuale=invoice.stato,
            )
        if invoice.trasmessa_esternamente_il is not None:
            raise Conflict(
                ENTITY,
                "la fattura e' stata consegnata all'intermediario il "
                f"{invoice.trasmessa_esternamente_il.isoformat()}: da questo punto la "
                "correzione richiede una nota di credito, che PigroCRM non emette. "
                "Va fatta dal tuo intermediario o dal portale dell'Agenzia delle Entrate.",
                trasmessa_esternamente_il=invoice.trasmessa_esternamente_il.isoformat(),
            )
        invoice.stato = "annullata"
        # `oggi_in_italia()`, never a bare `date.today()`: see `clock.py`. The date
        # printed on an annulment record is subject to the same "issuer's own
        # calendar" requirement as `data_emissione`.
        invoice.annullata_il = oggi_in_italia()
        invoice.motivo_annullamento = data.motivo
        self.activities.record(
            ENTITY,
            invoice.id,
            "annulled",
            actor,
            {"numero": invoice.numero, "anno": invoice.anno, "motivo": data.motivo},
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def mark_transmitted_externally(
        self, invoice_id: UUID, data: InvoiceTransmitted, actor: Actor
    ) -> InvoiceRead:
        """Record that the XML has been handed to the intermediary. Settable **once**.

        This is the column that makes annulment safe rather than optimistic: without
        it the system could not distinguish an invoice that never left -- annullable --
        from one already deposited with the Agenzia delle Entrate, and would treat the
        two the same. Freezing it after the first write is what stops that distinction
        from being editable away.
        """
        actor.require_admin("mark_transmitted_externally")
        invoice = self._require(invoice_id)
        if invoice.stato != "emessa":
            raise Conflict(
                ENTITY,
                "solo una fattura emessa si consegna a un intermediario",
                stato_attuale=invoice.stato,
            )
        if invoice.trasmessa_esternamente_il is not None:
            raise ImmutableField(
                ENTITY,
                "trasmessa_esternamente_il",
                "la consegna si registra una volta sola: e' il fatto su cui si decide "
                "se un annullamento e' ancora possibile",
            )
        oggi = oggi_in_italia()
        if data.data > oggi:
            raise ValidationFailed(
                ENTITY,
                "trasmessa_esternamente_il",
                "una consegna non si registra con data futura",
                expected=f"una data non successiva a {oggi.isoformat()}",
            )
        if invoice.data_emissione is not None and data.data < invoice.data_emissione:
            raise ValidationFailed(
                ENTITY,
                "trasmessa_esternamente_il",
                "la consegna non puo' precedere l'emissione "
                f"({invoice.data_emissione.isoformat()})",
                expected=f"una data dal {invoice.data_emissione.isoformat()} in poi",
            )
        invoice.trasmessa_esternamente_il = data.data
        self.activities.record(
            ENTITY, invoice.id, "transmitted_externally", actor, {"data": data.data.isoformat()}
        )
        self.session.commit()
        return InvoiceRead.model_validate(invoice)

    def _for_export(self, invoice: Invoice) -> InvoiceForExport:
        """The frozen view the exporter and the PDF read. Never the live profiles.

        `InvoiceSnapshot.model_validate` on the stored JSONB is deliberate: the model
        is `extra="forbid"` and `versione` has no default, so a payload written by a
        different version of this code is a loud failure rather than one silently read
        with a field dropped. This is a fiscal document; guessing is the failure mode
        the version column exists to prevent.
        """
        if invoice.snapshot is None or invoice.anno is None or invoice.numero is None:
            raise Conflict(
                ENTITY,
                "un documento senza numero e senza congelamento non si esporta",
                stato=invoice.stato,
            )
        if invoice.data_emissione is None:  # pragma: no cover - the CHECKs make this unreachable
            raise Conflict(ENTITY, "manca la data di emissione", stato=invoice.stato)
        return InvoiceForExport(
            anno=invoice.anno,
            numero=invoice.numero,
            data_emissione=invoice.data_emissione,
            data_scadenza=invoice.data_scadenza,
            tipo_documento=invoice.tipo_documento,
            divisa=invoice.divisa,
            imponibile=invoice.imponibile,
            imposta=invoice.imposta,
            bollo=invoice.bollo,
            totale=invoice.totale,
            causale=invoice.causale,
            snapshot=InvoiceSnapshot.model_validate(invoice.snapshot),
            righe=tuple(InvoiceLineRead.model_validate(r) for r in self.repo.lines(invoice.id)),
        )

    def _for_export_proforma(self, invoice: Invoice, actor: Actor) -> InvoiceForExport:
        """A live view for a proforma's PDF: a proforma never freezes (only `issue`
        writes `snapshot`/`anno`/`numero`), so there is nothing to read back. Built
        from the *current* customer/emitter/fiscal profile instead, and from
        `created_at` converted to Europe/Rome -- not `oggi_in_italia()` -- so
        re-rendering later reproduces the same displayed date rather than drifting
        with the clock. `anno`/`numero` are placeholders that satisfy the schema's
        non-nullable bounds; `build_scope` never reads them here because
        `riferimento is not None` skips the `numero_completo` branch entirely.
        """
        _, profile = self._regime()
        snapshot = self._build_snapshot(invoice, profile, actor)
        return InvoiceForExport(
            anno=invoice.created_at.year,
            numero=1,
            data_emissione=invoice.created_at.astimezone(ITALY_TZ).date(),
            data_scadenza=None,
            tipo_documento=invoice.tipo_documento,
            divisa=invoice.divisa,
            imponibile=invoice.imponibile,
            imposta=invoice.imposta,
            bollo=invoice.bollo,
            totale=invoice.totale,
            causale=invoice.causale,
            snapshot=snapshot,
            righe=tuple(InvoiceLineRead.model_validate(r) for r in self.repo.lines(invoice.id)),
        )

    def _artifact_document(
        self, invoice: Invoice, tipo: str, titolo: str, actor: Actor
    ) -> Document:
        """The `documents` row for one artefact stream, created on first use.

        Two rows per issued invoice, not one (spec 8.4): a `document_versions` chain is
        a linear history of *one* logical file with one `hash_sha256` used for
        deduplication and integrity, so mixing the PDF and the XML would make
        "version 3" ambiguous and the two hashes incomparable. Two streams, two hashes,
        two integrity checks -- and re-rendering the PDF never touches the XML.

        `documents.stato` is left `NULL` for all three invoice artefact types: the
        authoritative state is `invoices.stato`, and duplicating a state machine across
        two tables produces two truths.
        """
        existing_id = invoice.xml_document_id if tipo == "fattura_xml" else invoice.pdf_document_id
        if existing_id is not None:
            document = self.documents.repo.get(existing_id)
            if document is not None:
                return document
        created = self.documents.create(
            DocumentCreate(customer_id=invoice.customer_id, tipo=tipo, titolo=titolo),  # type: ignore[arg-type]
            actor,
        )
        document = self.documents.repo.get(created.id)
        if document is None:  # pragma: no cover - just created in this transaction
            raise NotFound("document", created.id)
        if tipo == "fattura_xml":
            invoice.xml_document_id = document.id
        else:
            invoice.pdf_document_id = document.id
        return document

    def _artifact_prefix(self, invoice: Invoice) -> str:
        if invoice.tipo == "proforma":
            return proforma_storage_prefix(invoice.id)
        if invoice.anno is None or invoice.numero is None:  # pragma: no cover
            raise Conflict(ENTITY, "un documento senza numero non ha un prefisso fiscale")
        return invoice_storage_prefix(invoice.anno, invoice.numero)

    def _xml_filename(self, export: InvoiceForExport) -> str:
        """`IT{cf_o_piva}_{progressivo}.xml`, from the **frozen** emitter identity.

        Fiscal code first, then VAT number: the same order `IdTrasmittente` uses, and
        for the same reason -- the SdI accepts either, and this is what the working
        generator sent. Reading the snapshot rather than the live profile is what keeps
        the name stable after the issuer edits their own data.
        """
        emittente = export.snapshot.emittente
        id_fiscale = normalise_fiscal_id(emittente.codice_fiscale) or normalise_fiscal_id(
            emittente.partita_iva
        )
        if id_fiscale is None:
            raise ValidationFailed(
                "emitter_profile",
                "codice_fiscale",
                "il nome del file XML richiede un codice fiscale o una partita IVA "
                "validi dell'emittente",
                expected="11 cifre oppure 16 caratteri",
            )
        return sdi_filename(id_fiscale, export.anno, export.numero)

    def _store_artifact(
        self,
        invoice: Invoice,
        *,
        kind: ArtifactKind,
        tipo: str,
        titolo: str,
        content_type: str,
        filename: str,
        data: bytes,
        expected_hash: str | None,
        actor: Actor,
    ) -> InvoiceArtifact:
        """Write the bytes, or prove the bytes already there are the same bytes.

        Three outcomes, and they are spec 4's three:

        * no previous hash -- the first successful production, the only moment with
          nothing to compare against. Write version 1 and record the hash;
        * the hash matches and the stored bytes still hash to it -- nothing to do.
          Return the existing version rather than writing an identical one, so a
          download does not grow the history;
        * the hash matches but the bytes are gone or corrupt -- a **repair**: write a
          new version with identical content. Spec 4 allows exactly this and calls it a
          repair, not a modification;
        * the hash differs -- an error to report, never a version to save.
        """
        digest = hashlib.sha256(data).hexdigest()
        if expected_hash is not None and digest != expected_hash:
            raise Conflict(
                ENTITY,
                f"il {kind} rigenerato non coincide con quello originale: e' una "
                "divergenza da segnalare, non una nuova versione da salvare",
                atteso=expected_hash,
                ottenuto=digest,
                campo="xml_hash_sha256" if kind == "xml" else "hash_sha256",
            )

        document = self._artifact_document(invoice, tipo, titolo, actor)
        current = (
            self.documents.repo.version(document.id, document.versione_corrente)
            if document.versione_corrente
            else None
        )
        if current is not None and current.hash_sha256 == digest:
            try:
                stored_ok = (
                    hashlib.sha256(self.storage.get(current.storage_key)).hexdigest() == digest
                )
            except Exception:
                stored_ok = False
            if stored_ok:
                return InvoiceArtifact(
                    kind=kind,
                    document_id=document.id,
                    version_numero=current.numero,
                    filename=filename,
                    content_type=content_type,
                    hash_sha256=digest,
                )

        version = self.documents.add_version(
            document.id,
            data,
            content_type,
            actor,
            storage_prefix=self._artifact_prefix(invoice),
        )
        return InvoiceArtifact(
            kind=kind,
            document_id=document.id,
            version_numero=version.numero,
            filename=filename,
            content_type=content_type,
            hash_sha256=digest,
        )

    def export_xml(self, invoice_id: UUID, actor: Actor) -> InvoiceArtifact:
        """Produce -- or verify -- the FatturaPA file.

        Refuses a proforma and a draft on the basis of the row's own **state**, never a
        flag the caller passed: that is the second of the four independent mechanisms
        that stop a proforma from being mistaken for an invoice, and the only one that
        cannot be bypassed by a caller who believes otherwise.

        `xml_hash_sha256` is written by the **first** successful export -- the one
        moment with no previous value to compare against -- and from then on every
        export compares and does not rewrite. Until then the column is `NULL` and the
        export is freely repeatable, which is exactly what makes the out-of-transaction
        render of spec 3 harmless.
        """
        actor.require_write("export_invoice_xml")
        invoice = self._require(invoice_id)
        if invoice.tipo != "fattura":
            raise Conflict(
                ENTITY,
                "una proforma non produce un file FatturaPA: non e' un documento fiscale",
                tipo=invoice.tipo,
                stato=invoice.stato,
            )
        if invoice.stato == "bozza":
            raise Conflict(
                ENTITY,
                "una bozza non ha ancora un numero e non produce un file FatturaPA",
                stato=invoice.stato,
            )

        export = self._for_export(invoice)
        # Re-checked here even though `issue` already checked: the snapshot could have
        # been edited out of band, and the two callers of these functions are the whole
        # reason they are module-level rather than methods.
        check_party_exportable(export.snapshot.emittente, "emitter_profile")
        check_party_exportable(export.snapshot.cliente, "customer")
        check_recipient_routing(export.snapshot.cliente)

        data = FatturaPAExporter().to_bytes(export)
        artifact = self._store_artifact(
            invoice,
            kind="xml",
            tipo="fattura_xml",
            titolo=f"Fattura {numero_completo(export.anno, export.numero)} (XML)",
            content_type="application/xml",
            filename=self._xml_filename(export),
            data=data,
            expected_hash=invoice.xml_hash_sha256,
            actor=actor,
        )
        if invoice.xml_hash_sha256 is None:
            invoice.xml_hash_sha256 = artifact.hash_sha256
        self.session.commit()
        return artifact

    def produce_artifacts(self, invoice_id: UUID, actor: Actor) -> list[InvoiceArtifact]:
        """Render the PDF, and for an issued invoice the XML too.

        Called by `issue` after its commit, and callable again at any time: both
        artefacts regenerate deterministically from the frozen snapshot, so this is
        idempotent by construction rather than by a guard. That is the property that
        makes the post-commit render of spec 3 safe -- a crash between the commit and
        the render leaves an invoice that is fiscally complete and merely unprinted,
        and the next call finishes the job.

        Byte-identical on re-render, which is only true because `render_pdf` pins
        `--creation-timestamp 0`: Typst otherwise stamps wall-clock compile time into
        every PDF's `/CreationDate`, and slice 2 had to discover that by comparing two
        renders rather than by trusting that the call succeeded.

        The PDF is produced for a proforma as well, from a live view built by
        `_for_export_proforma` rather than the frozen `_for_export` (a proforma never
        freezes); the XML is not, because a proforma is not a fiscal document.
        `export_xml` refuses one on the row's own state. Returns both artefacts
        (`[pdf]`, or `[pdf, xml]` once the fattura is issued) rather than only the
        last one produced, so a caller sees the whole result of one call.
        """
        actor.require_write("produce_invoice_artifacts")
        invoice = self._require(invoice_id)
        export = (
            self._for_export_proforma(invoice, actor)
            if invoice.tipo == "proforma"
            else self._for_export(invoice)
        )
        riferimento = invoice.riferimento if invoice.tipo == "proforma" else None

        _, data = invoice_pdf.render_invoice_pdf(
            export, riferimento=riferimento, settings=self.settings
        )
        # `fattura`/`proforma`, the names `DocumentTipo` actually declares -- the PDF is
        # *the* document of its kind, and `fattura_xml` is the one that needs qualifying
        # because it is the second stream for the same invoice.
        if invoice.tipo == "proforma":
            titolo = f"Proforma {invoice.riferimento or invoice.id} (PDF)"
            filename = f"proforma-{(invoice.riferimento or str(invoice.id)).lower()}.pdf"
            tipo = "proforma"
        else:
            titolo = f"Fattura {numero_completo(export.anno, export.numero)} (PDF)"
            filename = f"fattura-{invoice.anno}-{invoice.numero}.pdf"
            tipo = "fattura"

        # No `expected_hash`: unlike the XML, the PDF's bytes are not a fiscal identity
        # the system promises never to change. A template correction should produce a new
        # version, not a divergence error.
        pdf_artifact = self._store_artifact(
            invoice,
            kind="pdf",
            tipo=tipo,
            titolo=titolo,
            content_type="application/pdf",
            filename=filename,
            data=data,
            expected_hash=None,
            actor=actor,
        )
        self.session.commit()
        artifacts = [pdf_artifact]
        if invoice.tipo == "fattura" and invoice.stato != "bozza":
            artifacts.append(self.export_xml(invoice_id, actor))
        return artifacts

    def download(
        self, invoice_id: UUID, kind: ArtifactKind, actor: Actor
    ) -> tuple[bytes, str, str]:
        """`(bytes, content_type, filename)`.

        The download always goes through the API, which is the only place authorisation
        exists on either storage backend (slice 2 §5). The XML's name is the SdI
        convention; the PDF's is a plain, slug-safe name, because nothing downstream
        validates it.
        """
        invoice = self._require(invoice_id)
        document_id = invoice.xml_document_id if kind == "xml" else invoice.pdf_document_id
        if document_id is None:
            raise NotFound("invoice_artifact", f"{invoice_id}#{kind}")
        document = self.documents.repo.get(document_id)
        if document is None or not document.versione_corrente:
            raise NotFound("invoice_artifact", f"{invoice_id}#{kind}")
        version = self.documents.repo.version(document.id, document.versione_corrente)
        if version is None:  # pragma: no cover - versione_corrente points at a real row
            raise NotFound("invoice_artifact", f"{invoice_id}#{kind}")
        if kind == "xml":
            filename = self._xml_filename(self._for_export(invoice))
        elif invoice.tipo == "proforma":
            filename = f"proforma-{(invoice.riferimento or str(invoice.id)).lower()}.pdf"
        else:
            filename = f"fattura-{invoice.anno}-{invoice.numero}.pdf"
        return self.storage.get(version.storage_key), version.content_type, filename

    # ---- reads ---------------------------------------------------------------

    def get(self, invoice_id: UUID, actor: Actor) -> InvoiceRead:
        return InvoiceRead.model_validate(self._require(invoice_id))

    def lines(self, invoice_id: UUID, actor: Actor) -> list[InvoiceLineRead]:
        self._require(invoice_id)
        return [InvoiceLineRead.model_validate(r) for r in self.repo.lines(invoice_id)]

    def _require(self, invoice_id: UUID) -> Invoice:
        invoice = self.repo.get(invoice_id)
        if invoice is None:
            raise NotFound(ENTITY, invoice_id)
        return invoice

    # `list` must stay the last method defined in this class -- an unconditional
    # project rule (`test_module_imports.py`). `lines` above returns
    # `list[InvoiceLineRead]`, so it must be defined before this point or its
    # annotation resolves `list` to this method and fails at import on Python 3.13.
    def list(self, query: InvoiceListQuery, actor: Actor) -> InvoicePage:
        rows = self.repo.list(query)
        has_more = len(rows) > query.limit
        items = rows[: query.limit]
        return InvoicePage(
            items=[InvoiceRead.model_validate(i) for i in items],
            next_cursor=items[-1].id if has_more and items else None,
        )


__all__ = ["ENTITY", "InvoiceService"]
