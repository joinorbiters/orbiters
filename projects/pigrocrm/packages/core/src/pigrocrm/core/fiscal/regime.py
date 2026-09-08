"""A regime decides three things and nothing else: the rate a line defaults to, the
`Natura`/`RiferimentoNormativo` pair, and whether the stamp duty applies (spec 7.2).

the previous system hardcoded all three in the generator, which is why "what regime was this
invoice in" had no answer other than reading the source at the time. Here they come
from `fiscal_profile` through one of these objects, so a different regime is a second
object -- no new column, no migration -- and the rounding rules of `totals.py`, already
written, simply start producing non-zero values.

Deliberately out of scope and named rather than half-designed: withholding tax,
social-security fund, split payment, reverse charge, deferred or cash-basis VAT
liability. Each is a distinct XML block the forfettario never exercises.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fiscal.schemas import (
    CODICE_REGIME_RE,
    DEFAULT_RIFERIMENTO_NORMATIVO,
    FiscalSnapshot,
)
from pigrocrm.core.invoices.totals import RiepilogoGroup, round_money

ENTITY = "fiscal_profile"
ZERO = Decimal("0.00")


@runtime_checkable
class RegimeStrategy(Protocol):
    codice: str

    def resolve_line_vat(
        self, requested: Decimal | None, profile: FiscalSnapshot
    ) -> tuple[Decimal, str | None, str | None]:
        """`(aliquota_iva, natura, riferimento_normativo)` for one line.

        The three are returned together because the SdI validates them together: a
        zero rate without a `Natura` is rejected, and a `Natura` alongside a non-zero
        rate is rejected too. Returning them separately would let a caller pair them
        wrongly, and the table constraint `(aliquota_iva = 0) = (natura IS NOT NULL)`
        would then be the first thing to notice.
        """
        ...

    def bollo(self, riepilogo: Sequence[RiepilogoGroup], profile: FiscalSnapshot) -> Decimal:
        """The virtual stamp duty for the whole invoice, or `0.00`.

        Reads the summary groups rather than a single total because the duty is owed on
        the portion **not subject to VAT**: a large taxed amount must not push a
        mostly-taxed invoice over the threshold.
        """
        ...


class _Forfettario:
    """`RF19`. No VAT, `Natura N2.2`, and the normative declaration on every line and
    every summary group."""

    codice = "RF19"

    def resolve_line_vat(
        self, requested: Decimal | None, profile: FiscalSnapshot
    ) -> tuple[Decimal, str | None, str | None]:
        if requested is not None and requested != ZERO:
            raise ValidationFailed(
                "invoice_line",
                "aliquota_iva",
                f"il regime {self.codice} non applica IVA, quindi l'aliquota deve essere zero",
                expected="0.00",
            )
        natura = profile.natura_default or "N2.2"
        riferimento = profile.riferimento_normativo or DEFAULT_RIFERIMENTO_NORMATIVO
        return ZERO, natura, riferimento

    def bollo(self, riepilogo: Sequence[RiepilogoGroup], profile: FiscalSnapshot) -> Decimal:
        if not profile.applica_bollo:
            return ZERO
        untaxed = sum(
            (group.imponibile for group in riepilogo if group.aliquota_iva == ZERO),
            start=ZERO,
        )
        if round_money(untaxed) > profile.soglia_bollo:
            return round_money(profile.importo_bollo)
        return ZERO


class _Ordinario:
    """`RF01`. Present so the arithmetic of spec 6.1 is observable.

    The product ships the forfettario; this strategy is what a `test` fixture selects
    to put a 22% and a 10% group on the same invoice and watch `build_riepilogo` and
    `sum_totals` produce values that are not all zero. It is a real strategy, not a
    mock: switching `fiscal_profile.codice_regime` to `RF01` selects it in production
    too, and everything it needs already exists.
    """

    codice = "RF01"

    def resolve_line_vat(
        self, requested: Decimal | None, profile: FiscalSnapshot
    ) -> tuple[Decimal, str | None, str | None]:
        aliquota = requested if requested is not None else profile.aliquota_iva_default
        if aliquota == ZERO:
            # The table constraint requires a `natura` whenever the rate is zero, and
            # an ordinary regime has none to offer: refusing here names the field,
            # instead of letting the insert fail on a CHECK whose message names a
            # constraint.
            raise ValidationFailed(
                "invoice_line",
                "aliquota_iva",
                f"il regime {self.codice} non ha una natura da abbinare a un'aliquota zero",
                expected="un'aliquota maggiore di zero",
            )
        return aliquota, None, None

    def bollo(self, riepilogo: Sequence[RiepilogoGroup], profile: FiscalSnapshot) -> Decimal:
        # An ordinary regime taxes its operations, so there is no untaxed base for the
        # duty to be owed on. Returning zero unconditionally is the honest answer, not
        # a placeholder: an `RF01` invoice with an exempt line would need that line's
        # own `Natura`, which this strategy refuses to invent (see resolve_line_vat).
        return ZERO


FORFETTARIO: RegimeStrategy = _Forfettario()
ORDINARIO: RegimeStrategy = _Ordinario()

_BY_CODE: dict[str, RegimeStrategy] = {
    FORFETTARIO.codice: FORFETTARIO,
    ORDINARIO.codice: ORDINARIO,
}


def resolve_regime(codice_regime: str) -> RegimeStrategy:
    """The strategy for a stored `codice_regime`, or `ValidationFailed` naming it.

    Two checks, not one: the value must be a syntactically valid `RF01`-`RF19` code
    (`.fullmatch`, so a trailing newline is refused rather than accepted and passed
    on), and a strategy must exist for it. A code such as `RF07` is real FPR12 and
    still has no implementation here, and saying so is more useful than resolving it
    to the forfettario and silently issuing an invoice under the wrong regime.
    """
    if not CODICE_REGIME_RE.fullmatch(codice_regime):
        raise ValidationFailed(
            ENTITY,
            "codice_regime",
            f"codice regime non valido: {codice_regime!r}",
            expected="un codice da RF01 a RF19",
        )
    strategy = _BY_CODE.get(codice_regime)
    if strategy is None:
        raise ValidationFailed(
            ENTITY,
            "codice_regime",
            f"il regime {codice_regime} non e' implementato in questa versione",
            expected=f"uno tra: {', '.join(sorted(_BY_CODE))}",
        )
    return strategy


__all__ = ["FORFETTARIO", "ORDINARIO", "RegimeStrategy", "resolve_regime"]
