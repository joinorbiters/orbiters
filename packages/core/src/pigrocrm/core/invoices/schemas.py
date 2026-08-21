"""Every Pydantic shape the invoice domain exposes.

Widths and scales mirror `invoices/models.py` exactly. That is not defensive
duplication: without it an over-long string reaches Postgres as `DataError` and a
value beyond a `Numeric`'s capacity as `NumericValueOutOfRange`, neither of which is
an `IntegrityError`, so no handler catches either and the caller's session is left
poisoned. This project has paid for that class of defect seven times.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.fiscal.schemas import FiscalSnapshot
from pigrocrm.core.validation import SafeStr

InvoiceTipo = Literal["fattura", "proforma"]
InvoiceStato = Literal["bozza", "emessa", "annullata", "confermata", "consumata"]
StatoPagamento = Literal["da_incassare", "incassato"]
ArtifactKind = Literal["pdf", "xml"]

# Two state machines share one column, so the legal pairs are declared once here and
# enforced as a table `CHECK` in the migration. A convention in the service would
# leave `stato = 'consumata'` reachable on a `fattura` from any other write path.
ALLOWED_STATI: dict[str, frozenset[str]] = {
    "fattura": frozenset({"bozza", "emessa", "annullata"}),
    "proforma": frozenset({"bozza", "confermata", "consumata"}),
}

# Transitions, as a table rather than a chain of `if`s -- the same shape
# `documents/service.py::OFFER_TRANSITIONS` already uses, and read by the UI to decide
# which buttons exist. `emessa`, `annullata` and `consumata` are terminal.
STATO_TRANSITIONS: dict[str, frozenset[str]] = {
    "bozza": frozenset({"emessa", "confermata"}),
    "confermata": frozenset({"consumata", "bozza"}),
    "emessa": frozenset({"annullata"}),
    "annullata": frozenset(),
    "consumata": frozenset(),
}

SNAPSHOT_VERSIONE = 1
TIPO_DOCUMENTO = "TD01"
DIVISA = "EUR"

# FPR12 widths, which the columns mirror: Descrizione is String1000Type, Causale is
# String200Type, UnitaMisura is String10Type, Natura is 2-4 characters.
DESCRIZIONE_MAX_LENGTH = 1000
CAUSALE_MAX_LENGTH = 200
UNITA_MISURA_MAX_LENGTH = 10
NATURA_MAX_LENGTH = 4
RIFERIMENTO_MAX_LENGTH = 30
MOTIVO_ANNULLAMENTO_MAX_LENGTH = 500
TIPO_DOCUMENTO_MAX_LENGTH = 4
DIVISA_MAX_LENGTH = 3
HASH_LENGTH = 64

MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
FACTOR_MAX_DIGITS = 12
FACTOR_DECIMAL_PLACES = 6
RATE_MAX_DIGITS = 5
RATE_DECIMAL_PLACES = 2

# A `numero_linea` is contiguous from 1, so this doubles as the ceiling on both the
# line count and the line number. 200 lines is far more document than anyone posts,
# and the bound is what stops an unbounded list from becoming an unbounded number of
# INSERTs in one transaction.
MAX_LINES = 200
# Spec 8.4: the SdI file name embeds `anno * 10000 + numero`, so a five-digit numero
# would collide with the next year's. Emission is refused past this rather than a name
# quietly becoming ambiguous.
MAX_NUMERO = 9999
ANNO_MIN = 2000
ANNO_MAX = 2999


class PartySnapshot(BaseModel):
    """One party's identity and address as it was at emission.

    Frozen, and `extra="forbid"`: a stored snapshot that carries a field this model
    does not know about must fail loudly rather than be read with that field silently
    dropped, because the thing being reconstructed is a fiscal document.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ragione_sociale: str
    partita_iva: str | None
    codice_fiscale: str | None
    codice_sdi: str | None
    pec: str | None
    indirizzo: str
    cap: str
    comune: str
    provincia: str
    nazione: str
    email: str | None
    telefono: str | None
    sito_web: str | None


class InvoiceSnapshot(BaseModel):
    """What makes a re-render faithful: a customer who moves does not rewrite an
    invoice from two years ago (spec 8.3).

    `versione` is required and has no default on purpose. A default would let a
    payload with no version validate as version 1, which is exactly the guess the
    column exists to prevent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    versione: int
    emittente: PartySnapshot
    cliente: PartySnapshot
    fiscale: FiscalSnapshot


class InvoiceLineIn(BaseModel):
    """One line as a caller supplies it.

    `natura` and `riferimento_normativo` are deliberately absent: they are the
    `RegimeStrategy`'s answer, and accepting them here would put the table constraint
    `(aliquota_iva = 0) = (natura IS NOT NULL)` within reach of a request body.
    `aliquota_iva` is optional and means "use the regime's default"; under the
    forfettario the regime refuses anything but zero anyway.
    """

    model_config = ConfigDict(extra="forbid")

    descrizione: SafeStr = Field(max_length=DESCRIZIONE_MAX_LENGTH)
    quantita: Decimal = Field(
        default=Decimal("1.000000"),
        max_digits=FACTOR_MAX_DIGITS,
        decimal_places=FACTOR_DECIMAL_PLACES,
    )
    unita_misura: SafeStr | None = Field(default=None, max_length=UNITA_MISURA_MAX_LENGTH)
    prezzo_unitario: Decimal = Field(
        max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_DECIMAL_PLACES
    )
    sconto_percentuale: Decimal | None = Field(
        default=None, max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES
    )
    sconto_importo: Decimal | None = Field(
        default=None, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    aliquota_iva: Decimal | None = Field(
        default=None, max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES
    )


class InvoiceLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    numero_linea: int
    descrizione: str
    quantita: Decimal
    unita_misura: str | None
    prezzo_unitario: Decimal
    sconto_percentuale: Decimal | None
    sconto_importo: Decimal | None
    prezzo_totale: Decimal
    aliquota_iva: Decimal
    natura: str | None
    riferimento_normativo: str | None


class InvoiceCreate(BaseModel):
    """A draft invoice or a proforma. Neither has a number: a number is assigned only
    at emission, which is why "a failed creation burns a number" is impossible by
    construction rather than by care."""

    customer_id: UUID
    deal_id: UUID | None = None
    tipo: InvoiceTipo = "fattura"
    causale: SafeStr | None = Field(default=None, max_length=CAUSALE_MAX_LENGTH)
    note_interne: SafeStr | None = None
    righe: list[InvoiceLineIn] = Field(default_factory=list, max_length=MAX_LINES)
    custom_fields: dict[str, Any] = {}


class InvoiceUpdate(BaseModel):
    """Only what stays mutable after emission (spec 4).

    Everything typed and clearable is absent, which removes the A14 shape from this
    surface instead of reproducing it: lines are replaced in bulk, `stato_pagamento`
    and `data_incasso` go through `set_payment_state`, and `stato` goes through
    `issue`/`annul`. Both native fields here are text-shaped, so `""` is a real
    "clear it" spelling for each.

    `causale` is on this schema because a draft has to be correctable before it is
    issued, and it is frozen afterwards by `InvoiceService.update`, which raises
    `ImmutableField` -- not by leaving it off the schema, which would have made a
    draft's own subject line unfixable.
    """

    model_config = ConfigDict(extra="forbid")

    causale: SafeStr | None = Field(default=None, max_length=CAUSALE_MAX_LENGTH)
    note_interne: SafeStr | None = None
    custom_fields: dict[str, Any] | None = None


class InvoiceIssue(BaseModel):
    """`data_emissione` may be back-dated within the current year (spec 6.2); omitted
    means today in the issuer's own calendar, never a UTC projection of an instant."""

    model_config = ConfigDict(extra="forbid")

    data_emissione: date | None = None


class InvoiceAnnul(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: SafeStr = Field(min_length=1, max_length=MOTIVO_ANNULLAMENTO_MAX_LENGTH)


class InvoiceTransmitted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: date


class PaymentState(BaseModel):
    """`stato_pagamento` and `data_incasso` move together: "collected with no date" and
    "a date but not collected" are both nonsense, and a single method taking both
    required values has no spelling for either."""

    model_config = ConfigDict(extra="forbid")

    stato_pagamento: StatoPagamento
    data_incasso: date | None = None


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    deal_id: UUID | None
    tipo: str
    stato: str
    anno: int | None
    numero: int | None
    riferimento: str | None
    data_emissione: date | None
    data_scadenza: date | None
    tipo_documento: str
    divisa: str
    imponibile: Decimal
    imposta: Decimal
    bollo: Decimal
    totale: Decimal
    causale: str | None
    stato_pagamento: str
    data_incasso: date | None
    trasmessa_esternamente_il: date | None
    xml_hash_sha256: str | None
    pdf_document_id: UUID | None
    xml_document_id: UUID | None
    origine_proforma_id: UUID | None
    annullata_il: date | None
    motivo_annullamento: str | None
    note_interne: str | None
    snapshot_versione: int | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class InvoiceListQuery(BaseModel):
    customer_id: UUID | None = None
    deal_id: UUID | None = None
    tipo: InvoiceTipo | None = None
    stato: InvoiceStato | None = None
    anno: int | None = Field(default=None, ge=ANNO_MIN, le=ANNO_MAX)
    stato_pagamento: StatoPagamento | None = None
    # Bounded here, not only on the router: an MCP tool builds this object directly,
    # with no `Query(...)` bound sitting between it and this schema.
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class InvoicePage(BaseModel):
    items: list[InvoiceRead]
    next_cursor: UUID | None


class InvoiceArtifact(BaseModel):
    """What `export_xml`/`render_pdf` report. Never the bytes: an MCP tool returns an
    identifier and the bytes are fetched over REST (slice 2 §7)."""

    kind: ArtifactKind
    document_id: UUID
    version_numero: int
    filename: str
    content_type: str
    hash_sha256: str = Field(min_length=HASH_LENGTH, max_length=HASH_LENGTH)


class InvoiceForExport(BaseModel):
    """Everything `FatturaPAExporter` reads, and nothing else.

    A distinct type rather than `InvoiceRead` plus its lines, because the exporter must
    be provably unable to read `emitter_profile`, `customers` or `fiscal_profile`: what
    it can see is what was frozen. That is what makes a re-export reproducible and
    what lets the whole generator be tested with no database at all.
    """

    model_config = ConfigDict(frozen=True)

    anno: int = Field(ge=ANNO_MIN, le=ANNO_MAX)
    numero: int = Field(ge=1, le=MAX_NUMERO)
    data_emissione: date
    data_scadenza: date | None
    tipo_documento: str = Field(max_length=TIPO_DOCUMENTO_MAX_LENGTH)
    divisa: str = Field(max_length=DIVISA_MAX_LENGTH)
    imponibile: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    imposta: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    bollo: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    totale: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    causale: str | None = Field(default=None, max_length=CAUSALE_MAX_LENGTH)
    snapshot: InvoiceSnapshot
    righe: tuple[InvoiceLineRead, ...]
