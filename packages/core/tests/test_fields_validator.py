from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fields.types import FieldSpec
from pigrocrm.core.fields.validator import validate_custom_fields


def spec(key: str, field_type: str, **kw: Any) -> FieldSpec:
    return FieldSpec(key=key, label=key.title(), field_type=field_type, **kw)  # type: ignore[arg-type]


def test_empty_specs_and_empty_values_produce_empty_result() -> None:
    assert validate_custom_fields("customer", [], {}) == {}


def test_unknown_key_is_rejected_rather_than_silently_stored() -> None:
    """Silently accepting unknown keys turns JSONB into a junk drawer and hides typos
    from agents that guessed a field name."""
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("customer", [spec("settore", "text")], {"setore": "IT"})
    assert exc.value.details["field"] == "setore"
    assert "settore" in exc.value.details["reason"]


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("customer", [spec("settore", "text", required=True)], {})
    assert exc.value.details["field"] == "settore"


def test_required_field_rejects_empty_string() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields(
            "customer", [spec("settore", "text", required=True)], {"settore": "   "}
        )


def test_optional_field_accepts_none_and_is_dropped() -> None:
    assert validate_custom_fields("customer", [spec("settore", "text")], {"settore": None}) == {}


def test_text_is_trimmed() -> None:
    result = validate_custom_fields("customer", [spec("settore", "text")], {"settore": "  IT  "})
    assert result == {"settore": "IT"}


def test_number_accepts_int_float_and_numeric_string() -> None:
    specs = [spec("n", "number")]
    assert validate_custom_fields("c", specs, {"n": 5})["n"] == 5.0
    assert validate_custom_fields("c", specs, {"n": 5.5})["n"] == 5.5
    assert validate_custom_fields("c", specs, {"n": "5.5"})["n"] == 5.5


def test_number_rejects_non_numeric() -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [spec("n", "number")], {"n": "molto"})
    assert exc.value.details["expected"] == "un numero"


def test_currency_is_stored_as_a_two_decimal_string_not_a_float() -> None:
    """JSON has no decimal type. Storing money as float rounds wrong on invoices,
    so currency is serialised as a fixed-scale string."""
    result = validate_custom_fields("c", [spec("budget", "currency")], {"budget": "1234.567"})
    assert result == {"budget": "1234.57"}
    assert Decimal(result["budget"]) == Decimal("1234.57")


def test_currency_rejects_non_numeric() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [spec("budget", "currency")], {"budget": "gratis"})


def test_date_accepts_iso_string_and_date_and_normalises_to_iso() -> None:
    specs = [spec("scadenza", "date")]
    assert (
        validate_custom_fields("c", specs, {"scadenza": "2026-08-06"})["scadenza"] == "2026-08-06"
    )
    assert (
        validate_custom_fields("c", specs, {"scadenza": date(2026, 8, 6)})["scadenza"]
        == "2026-08-06"
    )


@pytest.mark.parametrize("bad", ["06/08/2026", "2026-13-01", "domani"])
def test_date_rejects_non_iso(bad: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [spec("scadenza", "date")], {"scadenza": bad})
    assert exc.value.details["expected"] == "una data ISO (YYYY-MM-DD)"


def test_select_accepts_a_declared_option() -> None:
    s = spec("stato", "select", options=["attivo", "sospeso"])
    assert validate_custom_fields("c", [s], {"stato": "attivo"})["stato"] == "attivo"


def test_select_rejects_an_undeclared_option_and_lists_the_valid_ones() -> None:
    """The error must name the allowed values: an agent that gets 'invalid' retries
    at random, one that gets the list corrects itself."""
    s = spec("stato", "select", options=["attivo", "sospeso"])
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [s], {"stato": "chiuso"})
    assert "attivo" in exc.value.details["expected"]
    assert "sospeso" in exc.value.details["expected"]


def test_multiselect_accepts_a_list_and_deduplicates_preserving_order() -> None:
    s = spec("tag", "multiselect", options=["a", "b", "c"])
    assert validate_custom_fields("c", [s], {"tag": ["b", "a", "b"]})["tag"] == ["b", "a"]


def test_multiselect_rejects_a_bare_string() -> None:
    s = spec("tag", "multiselect", options=["a"])
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [s], {"tag": "a"})
    assert exc.value.details["expected"] == "una lista di valori"


def test_multiselect_rejects_an_undeclared_member() -> None:
    s = spec("tag", "multiselect", options=["a", "b"])
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [s], {"tag": ["a", "z"]})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(True, True), (False, False), ("true", True), ("false", False), (1, True), (0, False)],
)
def test_checkbox_coerces_common_truthy_representations(raw: Any, expected: bool) -> None:
    assert validate_custom_fields("c", [spec("ok", "checkbox")], {"ok": raw})["ok"] is expected


def test_checkbox_rejects_ambiguous_values() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [spec("ok", "checkbox")], {"ok": "forse"})


@pytest.mark.parametrize("url", ["https://example.com", "http://localhost:5173/x?y=1"])
def test_url_accepts_http_and_https(url: str) -> None:
    assert validate_custom_fields("c", [spec("sito", "url")], {"sito": url})["sito"] == url


@pytest.mark.parametrize("bad", ["example.com", "javascript:alert(1)", "ftp://x.it"])
def test_url_rejects_anything_that_is_not_http_or_https(bad: str) -> None:
    """javascript: in particular would become a stored-XSS vector the moment the UI
    renders a custom field as a link."""
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("c", [spec("sito", "url")], {"sito": bad})
    assert exc.value.details["expected"] == "un URL http:// o https://"


def test_archived_specs_are_simply_not_passed_in_so_their_values_are_rejected() -> None:
    with pytest.raises(ValidationFailed):
        validate_custom_fields("c", [], {"vecchio": "valore"})


def test_all_errors_name_the_entity() -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_custom_fields("deal", [spec("n", "number")], {"n": "x"})
    assert exc.value.details["entity"] == "deal"
