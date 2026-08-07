from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

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


class ProblemDetail(BaseModel):
    """RFC 9457 problem document -- the exact shape `domain_error_handler` above
    renders every `DomainError` into. Documented once here and attached, as a
    shared `responses=` dict, to every router at construction time (see
    `PROBLEM_RESPONSES` below and its use in each `routers/*.py`), rather than
    enumerated per endpoint: any route that resolves an `Actor` or looks up an
    entity can raise `NotFound`/`Conflict`/`ValidationFailed`/`PermissionDenied`,
    so restating that per route, 37 times over, would document nothing a reader
    couldn't already infer.

    Extra fields are allowed on purpose: `domain_error_handler` spreads
    `exc.details` at the top level -- e.g. `active_deals` on a delete conflict,
    `expected` on a validation failure -- and those vary by error, not by route,
    so they are not modeled as individual named fields here.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str
    code: str
    instance: str


_PROBLEM_DETAIL_SCHEMA: dict[str, Any] = ProblemDetail.model_json_schema()
# Pydantic copies the class docstring above into the schema's own "description" --
# useful reading the source, pure noise repeated in the rendered OpenAPI document:
# this same dict is deep-copied into every one of the ~150 response entries below
# (37 routes x 4 codes), and each entry already carries its own short, specific
# `description` (see `_problem_response`) at the response-object level, one level
# up from this schema. Dropping the duplicate here is the difference between a
# `/openapi.json` a client generator can skim and one padded with the same essay
# repeated 150 times.
_PROBLEM_DETAIL_SCHEMA.pop("description", None)


def _problem_response(description: str) -> dict[str, Any]:
    """A hand-built `content` mapping, not FastAPI's `"model": ProblemDetail`
    shortcut: that shortcut always files the schema under the route's own success
    media type (`application/json` here), which would misdocument every one of
    these as the wrong content type -- `domain_error_handler` above always
    responds `application/problem+json`, never plain `application/json`."""
    return {
        "description": description,
        "content": {"application/problem+json": {"schema": _PROBLEM_DETAIL_SCHEMA}},
    }


# Attached to every router in main.py's registration loop: the domain-error
# outcomes any endpoint that resolves an Actor or touches an entity can produce,
# described once instead of per-route -- see ProblemDetail's docstring for why
# enumerating which codes each individual endpoint can raise would not be worth
# it. Passing this blanket means an endpoint that cannot actually raise, say, 409
# still lists it -- an accepted over-approximation, not an attempt to model each
# route's exact exception set.
#
# Declaring "422" here also replaces FastAPI's own auto-generated entry for it
# (the generic `{"detail": [...]}` shape raised before an endpoint ever runs, on
# a malformed body/query/path). That generic shape is still what the server
# actually returns for a request FastAPI itself rejects; only the *documented*
# schema for 422 changes, to the domain shape that is what these routers' own
# code raises far more often (e.g. an invalid custom-field value, a bad VAT
# number) and is what a client generator most needs to see modeled.
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: _problem_response("Permesso negato: l'actor non ha il ruolo richiesto."),
    404: _problem_response("La risorsa richiesta non esiste o è stata rimossa."),
    409: _problem_response("La richiesta è in conflitto con lo stato attuale della risorsa."),
    422: _problem_response("Una regola di dominio non è stata rispettata."),
}
