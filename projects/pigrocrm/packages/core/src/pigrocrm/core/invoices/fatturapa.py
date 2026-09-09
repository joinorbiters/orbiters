"""The FatturaPA FPR12 generator.

Built as an `lxml` element tree and serialised exactly once. There is no point in this
module where a fragment of XML exists as a string, which is what makes markup
injection impossible *by structure* rather than by every interpolation site
remembering to call an escaper -- the property the previous system's string-concatenated generator
could only ever approximate.

Three consequences, spelled out because each replaces a specific defect:

1. A value enters as the `.text` of a node, in its domain form, and the serialiser
   escapes it once. `escape_xml` is applied first and substitutes nothing; it only
   refuses code points XML 1.0 cannot represent. No value in this module has been
   through another escaper -- the previous system's `normalizeSingleLine` ran `escapeTypstText`
   before `escapeXml`, so "Rossi & C. #1" reached the Agenzia delle Entrate as
   "Rossi &amp; C. \\#1", with a literal backslash inside a fiscal record.
2. `lxml`, not `xml.etree.ElementTree`: an explicit `nsmap` on the root keeps the
   `ds:` and `xsi:` declarations this document does not reference. ElementTree prunes
   them. The prologue is reproduced identically because it is one the SdI and the
   intermediaries' own validators have already accepted, and there is no upside to
   changing it.
3. Nothing here reads the database. The input is an `InvoiceForExport`, whose
   `snapshot` was frozen at emission, so a re-export is reproducible and the whole
   generator is testable with no session at all.

Order is not negotiable: every FPR12 complex type is an `xs:sequence`, so an element
in the wrong position is an invalid document even when every value is right.
Reconstructing that order from the schema is the bulk of the work, and it is carried
over from a generator whose output the Sistema di Interscambio accepted.
"""

import re
from datetime import date
from decimal import Decimal

from lxml import etree

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.invoices.naming import FISCAL_ID_RE, numero_completo, progressivo_invio
from pigrocrm.core.invoices.schemas import InvoiceForExport, InvoiceLineRead, PartySnapshot
from pigrocrm.core.invoices.totals import (
    ComputedLine,
    RiepilogoGroup,
    build_riepilogo,
    format_amount_2,
    format_amount_8,
    format_rate,
)
from pigrocrm.core.templates.escaping import escape_xml

FPR12_NAMESPACE = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
DS_NAMESPACE = "http://www.w3.org/2000/09/xmldsig#"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
FORMATO_TRASMISSIONE = "FPR12"

# All three prefixes are declared on the root, `ds:` and `xsi:` included even though
# nothing in this file uses either. `ds:` becomes load-bearing only with the digital
# signature, which is out of scope; keeping both is how the prologue stays identical
# to one already accepted downstream. This is the reason for lxml -- see the module
# docstring.
NSMAP: dict[str | None, str] = {"p": FPR12_NAMESPACE, "ds": DS_NAMESPACE, "xsi": XSI_NAMESPACE}

# `CodiceDestinatario` for a private recipient with no SDI code, paired with
# `PECDestinatario`. Not deducible from the schema, where the field is simply
# mandatory.
CODICE_DESTINATARIO_FALLBACK = "0000000"
# And for a recipient outside Italy, whom the SdI does not route to at all. Seven
# X's is what the specification reserves for that case; a foreign customer has no SDI
# code and no PEC and is not supposed to have either.
CODICE_DESTINATARIO_ESTERO = "XXXXXXX"
# `CAP` is a five-digit numeric string in FPR12 and the technical specifications fill
# it with `00000` for an address outside Italy, where `Provincia` is left out. The
# writer applies the convention whatever the customer row holds: a London company keeps
# `EC1V 9HL` in its record, the PDF prints it, and `_indirizzo_xml` carries it at the
# end of `Indirizzo` so the document does not lose it (ORB-38).
CAP_ESTERO = "00000"
# Immediate VAT liability. The deferred and cash-basis variants are out of scope.
ESIGIBILITA_IVA = "I"
BOLLO_VIRTUALE = "SI"

# FPR12 widths. Every one is narrower than the Postgres column it comes from, so each
# is a real check and not a restatement of the schema's own bound.
_DENOMINAZIONE_MAX = 80
_INDIRIZZO_MAX = 60
_COMUNE_MAX = 60
_DESCRIZIONE_MAX = 1000
_CAUSALE_MAX = 200
_RIFERIMENTO_NORMATIVO_MAX = 100
_EMAIL_MAX = 256
_TELEFONO_MAX = 12

# `xs:pattern` restrictions the schema applies. `.fullmatch` at every call site, never
# `.match` with `$`.
_CAP_RE = re.compile(r"\d{5}")
_PROVINCIA_RE = re.compile(r"[A-Z]{2}")
_NAZIONE_RE = re.compile(r"[A-Z]{2}")
_IBAN_RE = re.compile(r"[A-Z]{2}\d{2}[A-Za-z0-9]{11,30}")
_CODICE_DESTINATARIO_RE = re.compile(r"[A-Z0-9]{7}")
_TIPO_PAGAMENTO_RE = re.compile(r"(TP|MP)\d{2}")
# The schema's `String*LatinType` family restricts every one of them to
# `[\p{IsBasicLatin}\p{IsLatin-1Supplement}]`, i.e. Unicode code points U+0000-U+00FF
# only (confirmed against the vendored XSD's own `String80LatinType`,
# `String1000LatinType`, etc.). A code point outside that range is an SdI rejection,
# so it is refused here with the field named instead, rather than emitted and left to
# be rejected downstream with no context.
_LATIN_RE = re.compile(r"[\x00-\xff]*")
# Punctuation and the "IT" prefix are stripped before a fiscal identifier is matched,
# exactly as the previous system's own normalisation did.
_FISCAL_ID_NOISE = re.compile(r"[^0-9A-Za-z]")


def normalise_fiscal_id(value: str | None) -> str | None:
    """An 11-digit VAT number or a 16-character fiscal code, or `None`.

    Strips the `IT` prefix and any punctuation, upper-cases, and then accepts only the
    two shapes FPR12 recognises. **Anything else returns `None` so the caller omits
    the element** rather than emitting it malformed -- the highest-value line carried
    over from the previous system's generator, because a malformed `IdCodice` is an outright
    rejection while an absent element usually passes.
    """
    if not value:
        return None
    cleaned = _FISCAL_ID_NOISE.sub("", value).upper()
    if cleaned.startswith("IT") and len(cleaned) == 13:
        cleaned = cleaned[2:]
    return cleaned if FISCAL_ID_RE.fullmatch(cleaned) else None


# FPR12 allows an `IdCodice` of up to 28 characters, which is what makes room for the
# registers of other countries. Italy's own two shapes are narrower and are checked by
# `normalise_fiscal_id`; outside Italy there is no shape this exporter can meaningfully
# assert, since every country issues its own.
_ID_CODICE_MAX = 28


def normalise_foreign_fiscal_id(value: str | None) -> str | None:
    """The same cleaning as `normalise_fiscal_id`, without Italy's shape rule.

    That function accepts exactly two forms -- an eleven-digit VAT number or a
    sixteen-character fiscal code -- and answers `None` to everything else so the caller
    omits a malformed element rather than emitting one. Correct for an Italian party, and
    the third place a foreign one was silently dropped: a British VAT of nine digits is
    not malformed, it is simply not Italian, and returning `None` for it produced an
    invoice with no `IdFiscaleIVA` at all rather than an error anybody could see.

    Nothing is asserted about the shape here on purpose. Twenty-eight countries' registers
    have twenty-eight shapes, and a guess at one of them would refuse a valid number --
    the failure this whole change exists to stop. Length is the one bound FPR12 itself
    gives, and it is enforced where every other width is, in `_text`.
    """
    if not value:
        return None
    cleaned = _FISCAL_ID_NOISE.sub("", value).upper()
    return cleaned or None


def _is_italian(party: PartySnapshot) -> bool:
    return (party.nazione or "").strip().upper() == "IT"


def _indirizzo_xml(party: PartySnapshot) -> str:
    """The text `_sede` writes into `Indirizzo`, and the text `_check_widths` measures.

    One function for both on purpose: the pre-check exists to refuse before a register
    number is spent whatever the writer would refuse after, and a foreign address is
    the one case where the two texts differ. `CAP` carries the `00000` placeholder for
    a party outside Italy, so the real postcode has no element of its own and is
    appended here instead. A record that already holds the placeholder (every foreign
    customer entered before ORB-38 does) gets the address alone: `00000` is the SdI's
    convention, not a postcode.
    """
    indirizzo = (party.indirizzo or "").strip()
    if _is_italian(party):
        return indirizzo
    cap = (party.cap or "").strip()
    if not cap or cap == CAP_ESTERO:
        return indirizzo
    return f"{indirizzo}, {cap}"


def check_party_exportable(party: PartySnapshot, entity: str) -> None:
    """Refuse, naming the field on the record the user can go and fix (spec 14.9).

    A module-level function rather than a method, because it has **two** callers and
    they must not drift: this exporter, and `InvoiceService.issue`, which runs it
    *before* consuming a number. Checking only here would be too late -- the export
    happens after the emission transaction has committed (spec 3), so a customer
    missing a CAP would already own a register number that can never produce a valid
    file, and the only remaining remedy would be an annulment.

    The previous system guessed `indirizzo`, `cap`, `comune` and `provincia` out of one free-text
    field with a regex over Italian street prefixes. They are four real columns on
    `customers`; nothing is guessed, and a missing one refuses.
    """
    nazione = (party.nazione or "").strip().upper()
    if not _NAZIONE_RE.fullmatch(nazione):
        raise ValidationFailed(
            entity, "nazione", "codice paese non valido", expected="due lettere ISO 3166-1"
        )
    italiano = nazione == "IT"

    # `provincia` is required for an Italian address and meaningless outside one: FPR12
    # makes `Provincia` optional precisely so that a London address is not forced to
    # invent one. Requiring it of everybody is what made a foreign customer
    # unrepresentable -- along with the outright refusal that used to stand here, which
    # this replaces. `cap` is not required outside Italy either, since `CAP` carries the
    # `00000` placeholder there. `comune` is required of everybody: the schema's
    # `Comune` is one to sixty characters with no `minOccurs="0"`, and leaving it out
    # of this list let an emission through that the writer could never serialise.
    obbligatori = (
        ("indirizzo", "cap", "comune", "provincia") if italiano else ("indirizzo", "comune")
    )
    for field in obbligatori:
        if not (getattr(party, field) or "").strip():
            raise ValidationFailed(
                entity,
                field,
                "campo obbligatorio per la fattura elettronica",
                expected="un valore non vuoto",
            )
    if not party.ragione_sociale.strip():
        raise ValidationFailed(
            entity, "ragione_sociale", "campo obbligatorio", expected="un valore non vuoto"
        )

    # The formats, and not merely the presence — checked *here* because this function's
    # whole reason for existing is that `InvoiceService.issue` calls it before consuming
    # a register number. Presence alone was not enough: `customers.ragione_sociale` is
    # `String(255)` against FPR12's 80, `indirizzo` and `comune` are `String(255)` and
    # `String(120)` against 60, and `cap` is `String(10)` where the schema wants exactly
    # five digits. So an ordinary customer — a long consortium name, a mistyped CAP —
    # passed this check, the emission committed, and every later `export_xml` raised
    # forever, leaving annulment as the only remedy. A refusal before the number is spent
    # costs the user one correction; a refusal after costs them a hole in the register.
    _check_widths(party, entity, italiano)


def _check_widths(party: PartySnapshot, entity: str, italiano: bool) -> None:
    """The FPR12 constraints that a database column is too wide to enforce.

    Mirrors exactly what `_text` will apply during the export; the two are deliberately
    the same values, because a check here that were laxer than the writer would let a
    number be spent on a document that still cannot be produced.
    """
    # `indirizzo` is measured as `_sede` will write it: for a foreign party that is the
    # address with the postcode appended, so the bound is checked on the composite and a
    # London address one character too long is refused here, by the field the user can
    # shorten, rather than by the writer after the number is spent.
    for field, value, limit in (
        ("ragione_sociale", party.ragione_sociale.strip(), _DENOMINAZIONE_MAX),
        ("indirizzo", _indirizzo_xml(party), _INDIRIZZO_MAX),
        ("comune", (party.comune or "").strip(), _COMUNE_MAX),
    ):
        if len(value) > limit:
            raise ValidationFailed(
                entity,
                field,
                f"troppo lungo per la fattura elettronica: {len(value)} caratteri",
                expected=f"al massimo {limit} caratteri",
            )

    # Outside Italy the stored postcode has no shape to check: the writer puts the
    # `00000` placeholder in `CAP` and the real one at the end of `Indirizzo`, measured
    # above. Inside Italy the schema's five digits are the customer's own CAP and a
    # mistyped one is refused before it costs a register number.
    cap = (party.cap or "").strip()
    if italiano and not _CAP_RE.fullmatch(cap):
        raise ValidationFailed(entity, "cap", "CAP non valido", expected="esattamente 5 cifre")

    # `Provincia` is written only for an Italian address (the specifications fill it only
    # when `Nazione` is `IT`), so a county or a state stored there for a foreign customer
    # is neither emitted nor a reason to refuse.
    provincia = (party.provincia or "").strip().upper()
    if italiano and provincia and not _PROVINCIA_RE.fullmatch(provincia):
        raise ValidationFailed(entity, "provincia", "sigla non valida", expected="due lettere")


def check_recipient_routing(party: PartySnapshot) -> None:
    """A customer must have an SDI code or a PEC, or there is no `CodiceDestinatario`.

    Split from `check_party_exportable` because it applies only to the *recipient*,
    and shared with `InvoiceService.issue` for the same reason: the previous system emitted an empty
    `CodiceDestinatario` here, producing an invalid file with no error at all.
    """
    if (party.nazione or "").strip().upper() != "IT":
        # A foreign customer has no SDI code and no PEC, and is not supposed to: the SdI
        # routes nothing to them. `CODICE_DESTINATARIO_ESTERO` is the placeholder the
        # specification reserves for exactly this, and `_dati_trasmissione` writes it.
        # Demanding a code here would make a foreign invoice impossible to issue, which
        # is what used to happen one function up.
        return
    if not (party.codice_sdi or "").strip() and not (party.pec or "").strip():
        raise ValidationFailed(
            "customer",
            "codice_sdi",
            "serve un codice destinatario (SDI) oppure una PEC per emettere la fattura",
            expected="codice_sdi di 7 caratteri oppure pec",
        )


class FatturaPAExporter:
    """`InvoiceForExport` in, `bytes` out. No database, no profile lookup, no clock."""

    def to_bytes(self, invoice: InvoiceForExport) -> bytes:
        if not invoice.righe:
            raise ValidationFailed(
                "invoice",
                "righe",
                "una fattura senza righe non e' esportabile",
                expected="almeno una riga",
            )
        emittente = invoice.snapshot.emittente
        cliente = invoice.snapshot.cliente
        check_party_exportable(emittente, "emitter_profile")
        check_party_exportable(cliente, "customer")

        # `lxml-stubs` types `nsmap` as `Mapping[str, str]` here even though the
        # *property* it defines a few lines above is `Dict[Optional[str], str]` --
        # the `None` key (default namespace) is real and readable at runtime, the
        # stub is simply incomplete for the write side. `NSMAP` has no `None` key in
        # this module, so this is a stub gap, not a real type mismatch.
        root = etree.Element(f"{{{FPR12_NAMESPACE}}}FatturaElettronica", nsmap=NSMAP)  # type: ignore[arg-type]
        root.set("versione", FORMATO_TRASMISSIONE)

        header = etree.SubElement(root, "FatturaElettronicaHeader")
        self._dati_trasmissione(header, invoice)
        self._cedente(header, invoice)
        self._cessionario(header, cliente)

        body = etree.SubElement(root, "FatturaElettronicaBody")
        self._dati_generali(body, invoice)
        self._dati_beni_servizi(body, invoice)
        self._dati_pagamento(body, invoice)

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    # ---- value writers ---------------------------------------------------------

    def _text(
        self,
        parent: etree._Element,
        tag: str,
        value: str,
        *,
        entity: str,
        field: str,
        max_length: int | None = None,
        pattern: re.Pattern[str] | None = None,
        latin_only: bool = True,
    ) -> etree._Element:
        """Append `<tag>value</tag>`, with `value` as the node's text and nothing else.

        `escape_xml` runs first and substitutes nothing (see its docstring): it refuses
        a code point XML 1.0 cannot represent. The serialiser is the single escaping
        pass, which is why no second escaper is applied here and why one applied
        earlier would be a defect rather than extra safety.
        """
        value = escape_xml(value)
        if max_length is not None and len(value) > max_length:
            raise ValidationFailed(
                entity,
                field,
                f"il valore supera i {max_length} caratteri ammessi da FPR12 per {tag}",
                expected=f"al massimo {max_length} caratteri",
            )
        if latin_only and not _LATIN_RE.fullmatch(value):
            raise ValidationFailed(
                entity,
                field,
                f"FPR12 ammette in {tag} solo caratteri latini di base o Latin-1",
                expected="solo caratteri latini",
            )
        if pattern is not None and not pattern.fullmatch(value):
            raise ValidationFailed(
                entity,
                field,
                f"il valore non ha la forma richiesta da FPR12 per {tag}: {value!r}",
                expected=pattern.pattern,
            )
        element = etree.SubElement(parent, tag)
        element.text = value
        return element

    def _anagrafica(self, parent: etree._Element, party: PartySnapshot, entity: str) -> None:
        """`Anagrafica/Denominazione`, even for a natural person with only a fiscal
        code: FPR12 allows `Nome`/`Cognome` instead, but `customers` has a single
        `ragione_sociale`, so there is no choice to make."""
        anagrafica = etree.SubElement(parent, "Anagrafica")
        self._text(
            anagrafica,
            "Denominazione",
            party.ragione_sociale,
            entity=entity,
            field="ragione_sociale",
            max_length=_DENOMINAZIONE_MAX,
        )

    def _sede(self, parent: etree._Element, party: PartySnapshot, entity: str) -> None:
        """`Indirizzo`, `CAP`, `Comune`, `Provincia?`, `Nazione`, the way the technical
        specifications want them for the party's country.

        An Italian address is written as stored. A foreign one is written the way the
        SdI describes it: `CAP` is the `00000` placeholder whatever the record holds,
        `Provincia` is left out, and the real postcode rides at the end of `Indirizzo`
        (see `_indirizzo_xml`, shared with the pre-check). Applying the five-digit
        pattern to a real foreign postcode here is what ORB-38 was: `issue` had already
        spent the number by the time this method refused.
        """
        italiano = _is_italian(party)
        sede = etree.SubElement(parent, "Sede")
        self._text(
            sede,
            "Indirizzo",
            _indirizzo_xml(party),
            entity=entity,
            field="indirizzo",
            max_length=_INDIRIZZO_MAX,
        )
        self._text(
            sede,
            "CAP",
            party.cap.strip() if italiano else CAP_ESTERO,
            entity=entity,
            field="cap",
            pattern=_CAP_RE,
        )
        self._text(
            sede, "Comune", party.comune, entity=entity, field="comune", max_length=_COMUNE_MAX
        )
        # Omitted rather than emitted empty when there is none. `Provincia` is optional
        # in FPR12 for exactly this reason -- a London address has no two-letter Italian
        # province and inventing one would be a false statement about where the customer
        # is. Writing it as `""` would be worse still: `check_party_exportable` keeps it
        # mandatory for an Italian address, so a blank one here can only mean a party
        # that is legitimately without. Outside Italy it is omitted whatever the record
        # holds, since the element is the code of an Italian province and nothing else.
        provincia = (party.provincia or "").strip().upper()
        if italiano and provincia:
            self._text(
                sede,
                "Provincia",
                provincia,
                entity=entity,
                field="provincia",
                pattern=_PROVINCIA_RE,
            )
        self._text(
            sede,
            "Nazione",
            party.nazione.strip().upper(),
            entity=entity,
            field="nazione",
            pattern=_NAZIONE_RE,
        )

    def _id_fiscale(
        self,
        parent: etree._Element,
        tag: str,
        id_codice: str,
        entity: str,
        field: str,
        paese: str = "IT",
    ) -> None:
        """`IdPaese` says which country's register `IdCodice` belongs to.

        It was hard-coded to `IT`, which was true of every party this exporter could
        reach while a foreign customer was refused outright — and became a lie the
        moment one was allowed through: a British VAT number announced as an Italian
        one. The emitter is Italian by definition of this product and keeps the default;
        the customer's is read from the customer.
        """
        block = etree.SubElement(parent, tag)
        elemento = etree.SubElement(block, "IdPaese")
        elemento.text = paese.strip().upper()
        self._text(
            block,
            "IdCodice",
            id_codice,
            entity=entity,
            field=field,
            max_length=_ID_CODICE_MAX,
        )

    # ---- header ----------------------------------------------------------------

    def _dati_trasmissione(self, header: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: IdTrasmittente, ProgressivoInvio, FormatoTrasmissione,
        CodiceDestinatario, ContattiTrasmittente?, PECDestinatario?."""
        emittente = invoice.snapshot.emittente
        cliente = invoice.snapshot.cliente
        block = etree.SubElement(header, "DatiTrasmissione")

        # `IdTrasmittente/IdCodice` may be the issuer's *fiscal code* rather than the
        # VAT number, which is not obvious from the schema. Fiscal code first because
        # that is what the working generator sent.
        trasmittente = normalise_fiscal_id(emittente.codice_fiscale) or normalise_fiscal_id(
            emittente.partita_iva
        )
        if trasmittente is None:
            raise ValidationFailed(
                "emitter_profile",
                "codice_fiscale",
                "serve un codice fiscale o una partita IVA dell'emittente per il "
                "blocco IdTrasmittente",
                expected="11 cifre oppure 16 caratteri",
            )
        self._id_fiscale(block, "IdTrasmittente", trasmittente, "emitter_profile", "codice_fiscale")

        progressivo = etree.SubElement(block, "ProgressivoInvio")
        progressivo.text = progressivo_invio(invoice.anno, invoice.numero)

        formato = etree.SubElement(block, "FormatoTrasmissione")
        # Not redundant with the root's own `versione` attribute: the SdI reads it here.
        formato.text = FORMATO_TRASMISSIONE

        codice_sdi = (cliente.codice_sdi or "").strip().upper()
        if (cliente.nazione or "").strip().upper() != "IT":
            # Checked before the SDI code, not after: a foreign customer that happens to
            # carry one — copied in by hand, or left behind by a country change — is
            # still a foreign customer, and routing the file to an Italian recipient's
            # code would send it to somebody else entirely.
            destinatario = etree.SubElement(block, "CodiceDestinatario")
            destinatario.text = CODICE_DESTINATARIO_ESTERO
        elif codice_sdi:
            self._text(
                block,
                "CodiceDestinatario",
                codice_sdi,
                entity="customer",
                field="codice_sdi",
                pattern=_CODICE_DESTINATARIO_RE,
            )
        elif (cliente.pec or "").strip():
            destinatario = etree.SubElement(block, "CodiceDestinatario")
            destinatario.text = CODICE_DESTINATARIO_FALLBACK
        else:
            # The previous system emitted an empty element here: an invalid file, produced with no
            # error at all.
            raise ValidationFailed(
                "customer",
                "codice_sdi",
                "serve un codice destinatario (SDI) oppure una PEC per emettere la fattura",
                expected="codice_sdi di 7 caratteri oppure pec",
            )

        if (emittente.email or "").strip():
            contatti = etree.SubElement(block, "ContattiTrasmittente")
            self._text(
                contatti,
                "Email",
                emittente.email or "",
                entity="emitter_profile",
                field="email",
                max_length=_EMAIL_MAX,
            )
        if not codice_sdi and (cliente.pec or "").strip():
            self._text(
                block,
                "PECDestinatario",
                cliente.pec or "",
                entity="customer",
                field="pec",
                max_length=_EMAIL_MAX,
            )

    def _cedente(self, header: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: DatiAnagrafici(IdFiscaleIVA, CodiceFiscale?, Anagrafica,
        ..., RegimeFiscale), Sede, ..., Contatti?.

        `IdFiscaleIVA` is **mandatory** in the vendored schema's own
        `DatiAnagraficiCedenteType` -- unlike `DatiAnagraficiCessionarioType`, where it
        is `minOccurs="0"` -- so, unlike the customer side, a `CedentePrestatore` with
        only a fiscal code and no VAT number would validate the element order but not
        the content: `IdFiscaleIVA` would simply be missing from a required position.
        This also matches Italian practice: an entity with no partita IVA is not a VAT
        subject and cannot be a `CedentePrestatore` on a FatturaPA document at all.
        """
        emittente = invoice.snapshot.emittente
        cedente = etree.SubElement(header, "CedentePrestatore")
        anagrafici = etree.SubElement(cedente, "DatiAnagrafici")

        piva = normalise_fiscal_id(emittente.partita_iva)
        if piva is None:
            raise ValidationFailed(
                "emitter_profile",
                "partita_iva",
                "l'emittente deve avere una partita IVA valida: IdFiscaleIVA e' "
                "obbligatorio per il cedente/prestatore",
                expected="11 cifre",
            )
        self._id_fiscale(anagrafici, "IdFiscaleIVA", piva, "emitter_profile", "partita_iva")
        codice_fiscale = normalise_fiscal_id(emittente.codice_fiscale)
        if codice_fiscale is not None:
            self._text(
                anagrafici,
                "CodiceFiscale",
                codice_fiscale,
                entity="emitter_profile",
                field="codice_fiscale",
            )
        self._anagrafica(anagrafici, emittente, "emitter_profile")
        regime = etree.SubElement(anagrafici, "RegimeFiscale")
        # From `fiscal_profile.codice_regime`, never a constant in the source: the
        # whole point of the profile.
        regime.text = invoice.snapshot.fiscale.codice_regime

        self._sede(cedente, emittente, "emitter_profile")

        telefono = (emittente.telefono or "").strip()
        email = (emittente.email or "").strip()
        if telefono or email:
            contatti = etree.SubElement(cedente, "Contatti")
            if telefono:
                # FPR12's Telefono is 5-12 characters with no spaces or plus sign
                # allowed by the pattern; strip the presentation characters a user
                # typed rather than refusing a perfectly good number.
                digits = re.sub(r"[^0-9]", "", telefono)[:_TELEFONO_MAX]
                if len(digits) >= 5:
                    node = etree.SubElement(contatti, "Telefono")
                    node.text = digits
            if email:
                self._text(
                    contatti,
                    "Email",
                    email,
                    entity="emitter_profile",
                    field="email",
                    max_length=_EMAIL_MAX,
                )

    def _cessionario(self, header: etree._Element, cliente: PartySnapshot) -> None:
        cessionario = etree.SubElement(header, "CessionarioCommittente")
        anagrafici = etree.SubElement(cessionario, "DatiAnagrafici")
        paese = (cliente.nazione or "IT").strip().upper()
        # Italy's two shapes are checked; every other country's is not, because there is
        # no shape to check. See `normalise_foreign_fiscal_id`.
        piva = (
            normalise_fiscal_id(cliente.partita_iva)
            if paese == "IT"
            else normalise_foreign_fiscal_id(cliente.partita_iva)
        )
        if piva is not None:
            self._id_fiscale(
                anagrafici,
                "IdFiscaleIVA",
                piva,
                "customer",
                "partita_iva",
                paese=paese,
            )
        codice_fiscale = normalise_fiscal_id(cliente.codice_fiscale)
        if codice_fiscale is not None:
            self._text(
                anagrafici,
                "CodiceFiscale",
                codice_fiscale,
                entity="customer",
                field="codice_fiscale",
            )
        self._anagrafica(anagrafici, cliente, "customer")
        self._sede(cessionario, cliente, "customer")

    # ---- body ------------------------------------------------------------------

    def _dati_generali(self, body: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: TipoDocumento, Divisa, Data, Numero, DatiRitenuta*, DatiBollo?,
        DatiCassaPrevidenziale*, ScontoMaggiorazione*, ImportoTotaleDocumento?,
        Arrotondamento?, Causale*, Art73?."""
        generali = etree.SubElement(body, "DatiGenerali")
        documento = etree.SubElement(generali, "DatiGeneraliDocumento")

        tipo = etree.SubElement(documento, "TipoDocumento")
        tipo.text = invoice.tipo_documento
        divisa = etree.SubElement(documento, "Divisa")
        divisa.text = invoice.divisa
        data = etree.SubElement(documento, "Data")
        # A `date`, formatted with `isoformat()`. Never `toISOString()` on an instant:
        # that is what put an invoice issued on 31 December at 23:30 CET into the next
        # fiscal year.
        data.text = self._iso(invoice.data_emissione)
        numero = etree.SubElement(documento, "Numero")
        numero.text = numero_completo(invoice.anno, invoice.numero)

        if invoice.bollo > Decimal("0.00"):
            bollo = etree.SubElement(documento, "DatiBollo")
            virtuale = etree.SubElement(bollo, "BolloVirtuale")
            virtuale.text = BOLLO_VIRTUALE
            importo = etree.SubElement(bollo, "ImportoBollo")
            importo.text = format_amount_2(invoice.bollo)

        totale = etree.SubElement(documento, "ImportoTotaleDocumento")
        # The stamp duty is not part of the total: `DatiBollo` declares that the
        # issuer settled it virtually, and charging it back would need a line with
        # `Natura N1` -- explicitly out of scope.
        totale.text = format_amount_2(invoice.totale)

        if (invoice.causale or "").strip():
            self._text(
                documento,
                "Causale",
                invoice.causale or "",
                entity="invoice",
                field="causale",
                max_length=_CAUSALE_MAX,
            )

    def _dati_beni_servizi(self, body: etree._Element, invoice: InvoiceForExport) -> None:
        beni = etree.SubElement(body, "DatiBeniServizi")
        for riga in invoice.righe:
            self._dettaglio_linea(beni, riga, invoice)
        for group in build_riepilogo(
            [
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
                for r in invoice.righe
            ]
        ):
            self._dati_riepilogo(beni, group)

    def _dettaglio_linea(
        self, parent: etree._Element, riga: InvoiceLineRead, invoice: InvoiceForExport
    ) -> None:
        """Sequence: NumeroLinea, TipoCessionePrestazione?, CodiceArticolo*,
        Descrizione, Quantita?, UnitaMisura?, DataInizioPeriodo?, DataFinePeriodo?,
        PrezzoUnitario, ScontoMaggiorazione*, PrezzoTotale, AliquotaIVA, Ritenuta?,
        Natura?, RiferimentoAmministrazione?, AltriDatiGestionali*.

        `UnitaMisura` comes *after* `Quantita` and *before* `PrezzoUnitario`: getting
        that wrong is a schema-invalid file with every value correct. The two period
        dates sit between the two and are the invoice's, not the line's (ORB-61): the
        period is header level on the row, and every line repeats it because the schema
        has no place for it on the document.
        """
        linea = etree.SubElement(parent, "DettaglioLinee")
        numero = etree.SubElement(linea, "NumeroLinea")
        # A real line number per real line. The previous system hardcoded 1, quantity 1 and the
        # whole total as the unit price, so the detail of the work never reached the
        # customer.
        numero.text = str(riga.numero_linea)
        self._text(
            linea,
            "Descrizione",
            riga.descrizione,
            entity="invoice_line",
            field="descrizione",
            max_length=_DESCRIZIONE_MAX,
        )
        quantita = etree.SubElement(linea, "Quantita")
        quantita.text = format_amount_8(riga.quantita)
        if (riga.unita_misura or "").strip():
            self._text(
                linea,
                "UnitaMisura",
                riga.unita_misura or "",
                entity="invoice_line",
                field="unita_misura",
            )
        if invoice.competenza_da is not None and invoice.competenza_a is not None:
            # Both or neither, which the row's own CHECK already guarantees: an empty
            # `<DataInizioPeriodo/>` would be a schema error, and a period invented from
            # the emission date would be a fact nobody stated.
            inizio = etree.SubElement(linea, "DataInizioPeriodo")
            inizio.text = self._iso(invoice.competenza_da)
            fine = etree.SubElement(linea, "DataFinePeriodo")
            fine.text = self._iso(invoice.competenza_a)
        prezzo = etree.SubElement(linea, "PrezzoUnitario")
        prezzo.text = format_amount_8(riga.prezzo_unitario)
        # `ScontoMaggiorazione` is deliberately not emitted: the discount is already
        # inside `prezzo_totale` (totals.py::line_total), and declaring it twice would
        # make the SdI's own check on PrezzoTotale fail.
        totale = etree.SubElement(linea, "PrezzoTotale")
        totale.text = format_amount_2(riga.prezzo_totale)
        aliquota = etree.SubElement(linea, "AliquotaIVA")
        aliquota.text = format_rate(riga.aliquota_iva)
        if riga.natura:
            natura = etree.SubElement(linea, "Natura")
            natura.text = riga.natura

    def _dati_riepilogo(self, parent: etree._Element, group: RiepilogoGroup) -> None:
        """Sequence: AliquotaIVA, Natura?, SpeseAccessorie?, Arrotondamento?,
        ImponibileImporto, Imposta, EsigibilitaIVA?, RiferimentoNormativo?."""
        riepilogo = etree.SubElement(parent, "DatiRiepilogo")
        aliquota = etree.SubElement(riepilogo, "AliquotaIVA")
        aliquota.text = format_rate(group.aliquota_iva)
        if group.natura:
            natura = etree.SubElement(riepilogo, "Natura")
            natura.text = group.natura
        imponibile = etree.SubElement(riepilogo, "ImponibileImporto")
        imponibile.text = format_amount_2(group.imponibile)
        imposta = etree.SubElement(riepilogo, "Imposta")
        imposta.text = format_amount_2(group.imposta)
        esigibilita = etree.SubElement(riepilogo, "EsigibilitaIVA")
        esigibilita.text = ESIGIBILITA_IVA
        if group.natura and group.riferimento_normativo:
            # A real normative reference, from the profile. The previous system sent the
            # *description of the code* ("N2.2 (non soggette - altri casi)") in this field.
            self._text(
                riepilogo,
                "RiferimentoNormativo",
                group.riferimento_normativo,
                entity="fiscal_profile",
                field="riferimento_normativo",
                max_length=_RIFERIMENTO_NORMATIVO_MAX,
            )

    def _dati_pagamento(self, body: etree._Element, invoice: InvoiceForExport) -> None:
        """Sequence: CondizioniPagamento, DettaglioPagamento+; and inside it
        Beneficiario?, ModalitaPagamento, DataRiferimentoTerminiPagamento?,
        GiorniTerminiPagamento?, DataScadenzaPagamento?, ImportoPagamento, ..., IBAN?."""
        fiscale = invoice.snapshot.fiscale
        pagamento = etree.SubElement(body, "DatiPagamento")
        self._text(
            pagamento,
            "CondizioniPagamento",
            fiscale.condizioni_pagamento,
            entity="fiscal_profile",
            field="condizioni_pagamento",
            pattern=_TIPO_PAGAMENTO_RE,
        )
        dettaglio = etree.SubElement(pagamento, "DettaglioPagamento")
        self._text(
            dettaglio,
            "ModalitaPagamento",
            fiscale.modalita_pagamento,
            entity="fiscal_profile",
            field="modalita_pagamento",
            pattern=_TIPO_PAGAMENTO_RE,
        )
        if invoice.data_scadenza is not None:
            scadenza = etree.SubElement(dettaglio, "DataScadenzaPagamento")
            scadenza.text = self._iso(invoice.data_scadenza)
        importo = etree.SubElement(dettaglio, "ImportoPagamento")
        importo.text = format_amount_2(invoice.totale)
        if (fiscale.iban or "").strip():
            self._text(
                dettaglio,
                "IBAN",
                (fiscale.iban or "").strip().replace(" ", ""),
                entity="fiscal_profile",
                field="iban",
                pattern=_IBAN_RE,
            )

    @staticmethod
    def _iso(value: date) -> str:
        """A `date`'s own ISO form.

        Deliberately not a timestamp conversion. The previous system's `formatIsoDate` called
        `toISOString()`, i.e. projected an instant through UTC: an invoice created on
        31 December at 23:30 CET came out dated 1 January, so its fiscal year was
        wrong on an immutable document. There is no instant here to get wrong.
        """
        return value.isoformat()


__all__ = [
    "FPR12_NAMESPACE",
    "FORMATO_TRASMISSIONE",
    "NSMAP",
    "FatturaPAExporter",
    "check_party_exportable",
    "check_recipient_routing",
    "normalise_fiscal_id",
]
