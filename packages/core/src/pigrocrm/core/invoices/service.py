"""The only writer of `invoices` and `invoice_lines`.

This task covers everything that happens before a number exists. A draft and a
proforma are ordinary mutable rows; the number, the freezing and the artefacts belong
to `issue`, `annul` and the artefact methods added by the following tasks.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.clock import oggi_in_italia
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, ImmutableField, NotFound, ValidationFailed
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.fields.validator import validate_custom_fields
from pigrocrm.core.fiscal.regime import RegimeStrategy, resolve_regime
from pigrocrm.core.fiscal.schemas import FiscalSnapshot
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.fatturapa import check_party_exportable, check_recipient_routing
from pigrocrm.core.invoices.models import Invoice, InvoiceLine
from pigrocrm.core.invoices.naming import proforma_riferimento
from pigrocrm.core.invoices.repository import InvoiceRepository
from pigrocrm.core.invoices.schemas import (
    DIVISA,
    SNAPSHOT_VERSIONE,
    TIPO_DOCUMENTO,
    InvoiceCreate,
    InvoiceIssue,
    InvoiceLineIn,
    InvoiceLineRead,
    InvoiceListQuery,
    InvoicePage,
    InvoiceRead,
    InvoiceSnapshot,
    InvoiceUpdate,
    PartySnapshot,
    PaymentState,
)
from pigrocrm.core.invoices.totals import ComputedLine, build_riepilogo, line_total, sum_totals
from pigrocrm.core.storage.base import DocumentStorage

ENTITY: EntityType = "invoice"
ZERO = Decimal("0.00")

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
            computed.append(
                ComputedLine(
                    numero_linea=index,
                    descrizione=riga.descrizione,
                    quantita=riga.quantita,
                    unita_misura=riga.unita_misura,
                    prezzo_unitario=riga.prezzo_unitario,
                    sconto_percentuale=riga.sconto_percentuale,
                    sconto_importo=riga.sconto_importo,
                    prezzo_totale=line_total(
                        quantita=riga.quantita,
                        prezzo_unitario=riga.prezzo_unitario,
                        sconto_percentuale=riga.sconto_percentuale,
                        sconto_importo=riga.sconto_importo,
                    ),
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
        invoice.imponibile = imponibile
        invoice.imposta = imposta
        invoice.totale = totale
        # The stamp duty is stored but does not enter the total: `DatiBollo` declares
        # that the issuer settled it virtually (spec 7.2).
        invoice.bollo = strategy.bollo(riepilogo, profile)

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
        changes = data.model_dump(exclude_none=True, exclude={"custom_fields"})
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

        Two reasons, both from spec 11: it is the natural shape of a line editor, and
        it is the only way an optional numeric or date column can be cleared at all
        while `exclude_none=True` is the update contract (A14). Replacing the list
        sidesteps that defect instead of pretending it is closed.
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

        Deliberately out of scope: two concurrent `issue()` calls racing on the exact
        *same* `invoice_id`. Nothing below locks the source row itself (only the
        year's counter), which every other write method in this class shares --
        `update`, `replace_lines`, `confirm_proforma` and `soft_delete` all read via
        `_require` with no lock either. Closing that would mean deciding a lock order
        between a source row and the counter row for the one method that touches both,
        a change with no test in this task's brief to prove it against; recorded here
        rather than fixed silently.
        """
        actor.require_admin("issue_invoice")
        source = self._require(invoice_id)
        data_emissione = data.data_emissione or oggi_in_italia()
        anno = data_emissione.year
        self._check_issue_date(data_emissione, oggi_in_italia().year)

        from_proforma = source.tipo == "proforma"
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

        # Step 2. From here on, every other emission for this year waits.
        counter = self.repo.lock_counter(anno)

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
        return InvoiceRead.model_validate(target)

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
