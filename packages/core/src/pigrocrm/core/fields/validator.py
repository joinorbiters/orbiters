import math
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn
from urllib.parse import urlparse

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fields.types import FieldSpec

TRUE_VALUES = {True, "1", "true", "True", "si", "sì", "yes"}
FALSE_VALUES = {False, "0", "false", "False", "no"}
ALLOWED_URL_SCHEMES = {"http", "https"}
# text/textarea/url all funnel through _clean_text: only these become text, so a
# dict or a list can never be silently stringified into "{'a': 1}"-shaped garbage.
TEXT_SCALAR_TYPES = (str, int, float, bool, Decimal)


def _fail(entity: str, key: str, reason: str, expected: str | None = None) -> NoReturn:
    """`NoReturn` is load-bearing: it tells mypy every call ends the function, so no
    caller needs an unreachable `raise` after it just to satisfy the return type."""
    raise ValidationFailed(entity, key, reason, expected=expected)


def _coerce_number(entity: str, spec: FieldSpec, value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: JSON has no size limit on integers, so json.loads can hand
        # us an int float() cannot represent - e.g. an integer with hundreds of
        # digits. That is exactly as invalid as a non-numeric string.
        _fail(entity, spec.key, f"'{value}' non è un numero", "un numero")
    if not math.isfinite(result):
        # float("1e1000") becomes inf without float() raising anything, so
        # finiteness has to be checked after conversion, not inferred from it.
        # Postgres rejects a bare NaN/Infinity token in JSONB outright.
        _fail(entity, spec.key, f"'{value}' non è un numero finito", "un numero finito")
    return result


def _coerce_currency(entity: str, spec: FieldSpec, value: Any) -> str:
    """Money is stored as a fixed-scale string: JSON has no decimal type, and float
    rounding on money is a bug that only shows up on an invoice."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        _fail(entity, spec.key, f"'{value}' non è un importo", "un importo numerico")
    if not amount.is_finite():
        # Decimal("NaN").quantize(...) does not raise - it silently propagates NaN -
        # while Decimal("Infinity").quantize(...) does. Checking is_finite() first
        # means both fail the same way instead of NaN slipping through as "NaN".
        _fail(entity, spec.key, f"'{value}' non è un importo finito", "un importo finito")
    try:
        return str(amount.quantize(Decimal("0.01")))
    except InvalidOperation:
        # A value with more significant digits than the decimal context allows
        # (e.g. a 400-digit integer) is finite but still cannot be quantized.
        _fail(entity, spec.key, f"'{value}' non è un importo", "un importo numerico")


def _coerce_date(entity: str, spec: FieldSpec, value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        _fail(entity, spec.key, f"'{value}' non è una data valida", "una data ISO (YYYY-MM-DD)")


def _coerce_select(entity: str, spec: FieldSpec, value: Any) -> str:
    text = str(value).strip()
    if text not in spec.options:
        _fail(
            entity,
            spec.key,
            f"'{text}' non è tra le opzioni ammesse",
            f"uno tra: {', '.join(spec.options)}",
        )
    return text


def _coerce_multiselect(entity: str, spec: FieldSpec, value: Any) -> list[str]:
    if not isinstance(value, list):
        _fail(entity, spec.key, "il valore deve essere una lista", "una lista di valori")
    seen: list[str] = []
    for item in value:
        text = str(item).strip()
        if text not in spec.options:
            _fail(
                entity,
                spec.key,
                f"'{text}' non è tra le opzioni ammesse",
                f"valori tra: {', '.join(spec.options)}",
            )
        if text not in seen:
            seen.append(text)
    return seen


def _coerce_checkbox(entity: str, spec: FieldSpec, value: Any) -> bool:
    try:
        if value in TRUE_VALUES:
            return True
        if value in FALSE_VALUES:
            return False
    except TypeError:
        # An unhashable value (a list, a dict) cannot be tested for set membership.
        # A client sending arbitrary JSON can easily produce one; that is just
        # another way of saying "not a recognisable boolean", not a crash.
        pass
    _fail(entity, spec.key, f"'{value}' non è un booleano", "true oppure false")


def _clean_text(entity: str, spec: FieldSpec, value: Any) -> str:
    """Shared by text, textarea and url. Only scalars become text - str() on a dict
    or a list produces silent garbage like "{'a': 1}" with no signal to whoever sent
    it - and a NUL byte is rejected outright rather than stripped, because stripping
    would change the user's data without telling them, and Postgres refuses \\x00 in
    a text column regardless."""
    if not isinstance(value, TEXT_SCALAR_TYPES):
        _fail(entity, spec.key, f"'{value}' non è un valore testuale", "un valore testuale")
    text = str(value).strip()
    if "\x00" in text:
        _fail(
            entity,
            spec.key,
            "il testo contiene un carattere nullo",
            "testo senza caratteri di controllo",
        )
    return text


def _coerce_url(entity: str, spec: FieldSpec, value: Any) -> str:
    text = _clean_text(entity, spec, value)
    parsed = urlparse(text)
    # Rejecting javascript: here is what stops a stored-XSS the moment the UI
    # renders a custom field as a link.
    if parsed.scheme not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        _fail(entity, spec.key, f"'{text}' non è un URL valido", "un URL http:// o https://")
    return text


def coerce_value(entity: str, spec: FieldSpec, value: Any) -> Any:
    match spec.field_type:
        case "text" | "textarea":
            return _clean_text(entity, spec, value)
        case "number":
            return _coerce_number(entity, spec, value)
        case "currency":
            return _coerce_currency(entity, spec, value)
        case "date":
            return _coerce_date(entity, spec, value)
        case "select":
            return _coerce_select(entity, spec, value)
        case "multiselect":
            return _coerce_multiselect(entity, spec, value)
        case "checkbox":
            return _coerce_checkbox(entity, spec, value)
        case "url":
            return _coerce_url(entity, spec, value)
    _fail(entity, spec.key, f"tipo di campo sconosciuto: {spec.field_type}")


def _is_blank(value: Any) -> bool:
    """None, a whitespace-only string, or an empty sequence all mean "nothing was
    provided". False and 0 do not: they are legitimate values, not missing ones."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return False


def validate_custom_fields(
    entity: str, specs: list[FieldSpec], values: dict[str, Any]
) -> dict[str, Any]:
    """The single authority on custom-field validity.

    Routers, MCP tools and the UI all defer to this. Duplicating any part of it
    elsewhere is how the three interfaces start disagreeing about what is valid.
    """
    by_key = {spec.key: spec for spec in specs}

    for key in values:
        if key not in by_key:
            known = ", ".join(sorted(by_key)) or "nessuno"
            _fail(entity, key, f"campo non definito (campi disponibili: {known})")

    result: dict[str, Any] = {}
    for spec in specs:
        raw = values.get(spec.key)
        if _is_blank(raw):
            if spec.required:
                _fail(entity, spec.key, "campo obbligatorio", "un valore non vuoto")
            continue
        result[spec.key] = coerce_value(entity, spec, raw)
    return result
