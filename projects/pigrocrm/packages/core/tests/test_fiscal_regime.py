"""A regime decides three things and nothing else (spec 7.2): the default rate on a
line, the Natura/RiferimentoNormativo pair, and whether the stamp duty applies.

`ORDINARIO` (RF01) ships with the product but is exercised only by tests and by
whoever changes regime: it exists so the rounding rules of spec 6.1 -- which the
forfettario reduces to zero -- are verifiable behaviour rather than documentation.
"""

from decimal import Decimal

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fiscal.regime import FORFETTARIO, ORDINARIO, resolve_regime
from pigrocrm.core.fiscal.schemas import DEFAULT_RIFERIMENTO_NORMATIVO, FiscalSnapshot
from pigrocrm.core.invoices.totals import RiepilogoGroup


def _profile(**overrides: object) -> FiscalSnapshot:
    base: dict[str, object] = {
        "codice_regime": "RF19",
        "aliquota_iva_default": Decimal("0.00"),
        "natura_default": "N2.2",
        "riferimento_normativo": DEFAULT_RIFERIMENTO_NORMATIVO,
        "applica_bollo": True,
        "soglia_bollo": Decimal("77.47"),
        "importo_bollo": Decimal("2.00"),
        "condizioni_pagamento": "TP02",
        "modalita_pagamento": "MP05",
        "giorni_scadenza": 30,
        "iban": "IT60X0542811101000000123456",
    }
    base.update(overrides)
    return FiscalSnapshot(**base)  # type: ignore[arg-type]


def _group(aliquota: str, imponibile: str, natura: str | None) -> RiepilogoGroup:
    return RiepilogoGroup(
        aliquota_iva=Decimal(aliquota),
        natura=natura,
        riferimento_normativo=None,
        imponibile=Decimal(imponibile),
        imposta=Decimal("0.00"),
    )


def test_resolve_regime_picks_the_strategy_from_the_code() -> None:
    assert resolve_regime("RF19") is FORFETTARIO
    assert resolve_regime("RF01") is ORDINARIO


def test_an_unknown_regime_code_names_the_field() -> None:
    with pytest.raises(ValidationFailed) as caught:
        resolve_regime("RF07")
    assert caught.value.details["entity"] == "fiscal_profile"
    assert caught.value.details["field"] == "codice_regime"


def test_a_code_that_is_not_a_regime_at_all_is_refused_by_fullmatch() -> None:
    """`.fullmatch`, never `.match` with `$`: "RF19\\n" is 5 characters and would
    reach a String(4) column as a raw DataError."""
    with pytest.raises(ValidationFailed):
        resolve_regime("RF19\n")


def test_forfettario_forces_zero_rate_with_the_natura_and_the_reference() -> None:
    aliquota, natura, riferimento = FORFETTARIO.resolve_line_vat(None, _profile())
    assert aliquota == Decimal("0.00")
    assert natura == "N2.2"
    assert riferimento == DEFAULT_RIFERIMENTO_NORMATIVO


def test_forfettario_accepts_an_explicit_zero_and_refuses_anything_else() -> None:
    """Two SdI checks applied as a pair: a zero rate without a Natura is rejected,
    and a Natura with a non-zero rate is rejected. Whoever does not know that
    discovers the second only after fixing the first."""
    assert FORFETTARIO.resolve_line_vat(Decimal("0.00"), _profile())[0] == Decimal("0.00")
    with pytest.raises(ValidationFailed) as caught:
        FORFETTARIO.resolve_line_vat(Decimal("22.00"), _profile())
    assert caught.value.details["field"] == "aliquota_iva"


def test_forfettario_applies_the_stamp_duty_only_above_the_threshold() -> None:
    """Spec 14.1's two boundary cases: 77.47 is not above the threshold, 77.48 is."""
    profile = _profile()
    assert FORFETTARIO.bollo([_group("0.00", "77.47", "N2.2")], profile) == Decimal("0.00")
    assert FORFETTARIO.bollo([_group("0.00", "77.48", "N2.2")], profile) == Decimal("2.00")


def test_forfettario_honours_applica_bollo_false() -> None:
    profile = _profile(applica_bollo=False)
    assert FORFETTARIO.bollo([_group("0.00", "5000.00", "N2.2")], profile) == Decimal("0.00")


def test_the_stamp_duty_looks_only_at_the_untaxed_base() -> None:
    """`DatiBollo` is due on the amount not subject to VAT. A taxed group must not
    push a mostly-taxed invoice over the threshold."""
    profile = _profile()
    groups = [_group("22.00", "5000.00", None), _group("0.00", "10.00", "N2.2")]
    assert FORFETTARIO.bollo(groups, profile) == Decimal("0.00")


def test_ordinario_uses_the_requested_rate_with_no_natura() -> None:
    profile = _profile(
        codice_regime="RF01",
        aliquota_iva_default=Decimal("22.00"),
        natura_default=None,
        riferimento_normativo=None,
    )
    assert ORDINARIO.resolve_line_vat(Decimal("10.00"), profile) == (
        Decimal("10.00"),
        None,
        None,
    )
    assert ORDINARIO.resolve_line_vat(None, profile) == (Decimal("22.00"), None, None)


def test_ordinario_refuses_a_zero_rate_because_it_has_no_natura_to_pair_with_it() -> None:
    profile = _profile(
        codice_regime="RF01",
        aliquota_iva_default=Decimal("22.00"),
        natura_default=None,
        riferimento_normativo=None,
    )
    with pytest.raises(ValidationFailed) as caught:
        ORDINARIO.resolve_line_vat(Decimal("0.00"), profile)
    assert caught.value.details["field"] == "aliquota_iva"


def test_ordinario_never_charges_the_stamp_duty() -> None:
    profile = _profile(codice_regime="RF01", natura_default=None)
    assert ORDINARIO.bollo([_group("22.00", "9999.00", None)], profile) == Decimal("0.00")
