CUSTOM_QUERY_DESCRIPTION = (
    "Filtro sui campi personalizzati (JSONB), ripetibile per più chiavi: "
    "?custom=settore:IT&custom=priorita:alta restituisce solo le righe che "
    "soddisfano entrambe (stessa semantica di contenimento JSONB usata dal "
    "service). Ogni valore è confrontato come stringa esatta; un valore senza "
    "il separatore ':' vale come chiave con valore vuoto, non genera un errore. "
    "Chiama GET /api/schema/{entity_type} per conoscere le chiavi disponibili."
)


def parse_custom_filter(raw: list[str] | None) -> dict[str, str] | None:
    """Turns a repeated `?custom=key:value` query parameter into the dict
    `CustomerListQuery.custom`/`PersonListQuery.custom`/`DealListQuery.custom`
    already accept and pass straight through to the service's JSONB containment
    filter (`custom_fields.contains(...)`).

    `str.partition` never raises: an entry with no `:` becomes `(entry, "", "")`,
    so this returns `{entry: ""}` rather than a 500 from a malformed query
    string -- there is no single "correct" interpretation of a value with no
    key/value separator, so degrading to an empty-string value is the one
    behaviour that cannot itself become a new bug. The last occurrence of a
    repeated key wins, the same convention most `key=value`-shaped query
    parameters already follow.

    Deliberately shared across the three list routers (customers, people,
    deals) rather than duplicated per domain, unlike the domain-specific
    services/repositories those routers call: this is adapter-only, purely
    mechanical string parsing with no business rule in it, the same class of
    thing `pigrocrm.core.db.search.escape_like` already is for its own layer.
    """
    if not raw:
        return None
    return dict(item.partition(":")[::2] for item in raw)
