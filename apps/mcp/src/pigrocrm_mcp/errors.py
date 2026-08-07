from pigrocrm.core.errors import DomainError

HINT_BY_CODE: dict[str, str] = {
    "not_found": "Verifica l'identificativo, oppure cerca l'entità con lo strumento di ricerca.",
    "validation_failed": "Correggi il valore indicato e riprova.",
    "conflict": (
        "Lo stato attuale impedisce l'operazione: risolvi il conflitto descritto e riprova."
    ),
    "permission_denied": "Servono permessi diversi: chiedi all'utente di procedere manualmente.",
    "immutable_field": "Questo campo non è modificabile: archivia e ricrea invece di aggiornare.",
}


def to_agent_message(exc: DomainError) -> str:
    """A numeric status makes a model retry at random; a diagnosis makes it stop or fix.

    So the MCP rendering states what failed, what was expected, and what to do next —
    the same structured details the API renders as a problem document.
    """
    lines = [exc.message]

    expected = exc.details.get("expected")
    if expected:
        lines.append(f"Valore atteso: {expected}.")

    if exc.code == "permission_denied":
        required = ", ".join(exc.details.get("required_roles", []))
        actual = exc.details.get("actual_role", "sconosciuto")
        lines.append(f"Ruolo attuale: {actual}. Ruoli sufficienti: {required}.")

    extras = {
        key: value
        for key, value in exc.details.items()
        if key not in {"expected", "required_roles", "actual_role", "entity", "field", "reason"}
    }
    if extras:
        lines.append("Contesto: " + ", ".join(f"{k}={v}" for k, v in sorted(extras.items())))

    lines.append(HINT_BY_CODE.get(exc.code, "Rivedi i parametri e riprova."))
    return " ".join(lines)
