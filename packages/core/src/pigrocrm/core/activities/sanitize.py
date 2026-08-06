"""Sanitizes an activity payload instead of validating it.

An audit entry must never be able to fail the operation it is auditing: recording,
say, an inbound email's subject line must not stop that email from being linked to
its deal just because the subject contained an odd character. `sanitize_payload`
therefore never raises. Applied recursively to every `dict` and `list` value it finds:

  - non-finite floats (`nan`, `inf`, `-inf`) become their textual name (`"NaN"`,
    `"Infinity"`, `"-Infinity"`). Postgres JSONB rejects them outright; keeping a
    readable string loses less information than the alternative (letting the whole
    write fail) or silently dropping the key.
  - NUL bytes are stripped from strings. Postgres text storage cannot hold one at all.
  - strings longer than `MAX_STRING_LENGTH` are truncated with a trailing "…" -- a
    generous limit that only bites on genuinely oversized input, not a real payload.
  - nesting deeper than `MAX_DEPTH` is replaced with a placeholder string, which stops
    both unbounded recursion and unboundedly large stored documents.

This is the same class of defect the custom-field validator closes (see
`pigrocrm.core.fields.validator`): untrusted data reaching a strict storage layer with
no controlled failure path. The remedy here is deliberately different: the field
validator *rejects*, because a user is actively choosing a value and can be told to fix
it. Nothing here is shown to a human to correct -- sanitizing and moving on is the only
option that does not fail the write this payload is merely riding along with.
"""

import math
from typing import Any

MAX_STRING_LENGTH = 2000
MAX_DEPTH = 10
_TRUNCATION_SUFFIX = "…"
_DEPTH_PLACEHOLDER = "…(troncato: profondità massima superata)…"


def _sanitize_float(value: float) -> float | str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _sanitize_string(value: str) -> str:
    cleaned = value.replace("\x00", "")
    if len(cleaned) > MAX_STRING_LENGTH:
        return cleaned[:MAX_STRING_LENGTH] + _TRUNCATION_SUFFIX
    return cleaned


def _sanitize_value(value: Any, depth: int) -> Any:
    if isinstance(value, dict):
        if depth >= MAX_DEPTH:
            return _DEPTH_PLACEHOLDER
        return {key: _sanitize_value(inner, depth + 1) for key, inner in value.items()}
    if isinstance(value, list):
        if depth >= MAX_DEPTH:
            return _DEPTH_PLACEHOLDER
        return [_sanitize_value(inner, depth + 1) for inner in value]
    if isinstance(value, float):
        return _sanitize_float(value)
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitizes every value in `payload`, recursively. The payload's own top-level
    keys are never dropped or replaced by the depth limit -- only nested values, from
    depth 1 downward, are subject to it."""
    return {key: _sanitize_value(value, depth=1) for key, value in payload.items()}
