from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from pigrocrm.core.errors import DomainError

STATUS_BY_CODE: dict[str, int] = {
    "not_found": 404,
    "validation_failed": 422,
    "conflict": 409,
    "permission_denied": 403,
    "immutable_field": 409,
    "domain_error": 400,
}

TITLE_BY_CODE: dict[str, str] = {
    "not_found": "Risorsa non trovata",
    "validation_failed": "Dati non validi",
    "conflict": "Conflitto con lo stato attuale",
    "permission_denied": "Permesso negato",
    "immutable_field": "Campo non modificabile",
    "domain_error": "Errore di dominio",
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """RFC 9457 problem details. The structured `details` survive to the client, which
    is what lets the UI highlight the offending field instead of showing a toast.

    `details` is typed `Any` at the source (`DomainError.__init__(self, message,
    **details)`) -- nothing there stops a caller from putting a UUID, a Decimal, or a
    datetime in it. `JSONResponse` renders through stdlib `json.dumps`, which cannot
    serialise any of those: passing the content straight through would let a single
    UUID in an error's details crash this handler while it builds the response, i.e.
    turn what should be a clean 4xx into an opaque, unhandled 500. `jsonable_encoder`
    is FastAPI's own recursive converter for exactly this gap (UUID/Decimal/datetime/
    enum/pydantic models -> JSON-safe primitives) and is run on the whole content dict,
    not just `details`, so it never needs to know the fixed keys from the variable
    ones."""
    assert isinstance(exc, DomainError)
    status = STATUS_BY_CODE.get(exc.code, 400)
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content=jsonable_encoder(
            {
                "type": f"https://pigrocrm.dev/errors/{exc.code}",
                "title": TITLE_BY_CODE.get(exc.code, "Errore"),
                "status": status,
                "detail": exc.message,
                "code": exc.code,
                "instance": str(request.url.path),
                **exc.details,
            }
        ),
    )
