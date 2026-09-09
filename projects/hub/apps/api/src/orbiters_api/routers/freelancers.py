"""`POST /api/hub/freelancers`: the wizard's application, CV included.

Multipart, because the CV is a file: the fields arrive as form values and the PDF as
`cv`. Everything is validated by `FreelancerCreate` and `check_cv` exactly as the MCP
server would validate it, so the two adapters cannot accept different things. Public,
rate-limited, and mute like the signup: the answer is `{"ok": true}` whether this was a
first application or a correction of one.
"""

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import ValidationError

from orbiters_api.deps import SessionDep
from orbiters_api.ratelimit import spend_one
from orbiters_core.freelancers import FreelancerService
from orbiters_core.schemas import Ack, FreelancerCreate, SignupUtm

router = APIRouter(prefix="/api/hub", tags=["hub"])


def _decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"loc": ["body", field], "msg": "serve un numero", "type": "value_error"}],
        ) from exc


def _validation_422(exc: ValidationError) -> HTTPException:
    """The same shape FastAPI gives a JSON body's errors, so the wizard can point at the
    field: `detail[].loc[-1]` is the field name, whatever the transport was."""
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {"loc": ["body", *error["loc"]], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ],
    )


@router.post("/freelancers", response_model=Ack, status_code=status.HTTP_201_CREATED)
def apply(
    request: Request,
    session: SessionDep,
    nome: Annotated[str, Form()],
    cognome: Annotated[str, Form()],
    email: Annotated[str, Form()],
    tariffa_giornaliera: Annotated[str, Form()],
    posizione: Annotated[str, Form()],
    remoto: Annotated[str, Form()],
    cv: Annotated[UploadFile, File()],
    linkedin_url: Annotated[str | None, Form()] = None,
    links: Annotated[list[str] | None, Form()] = None,
    utm_source: Annotated[str | None, Form()] = None,
    utm_medium: Annotated[str | None, Form()] = None,
    utm_campaign: Annotated[str | None, Form()] = None,
    utm_content: Annotated[str | None, Form()] = None,
    utm_term: Annotated[str | None, Form()] = None,
    utm_id: Annotated[str | None, Form()] = None,
) -> Ack:
    spend_one(request)
    try:
        data = FreelancerCreate(
            nome=nome,
            cognome=cognome,
            email=email,
            linkedin_url=linkedin_url or None,
            tariffa_giornaliera=_decimal(tariffa_giornaliera, "tariffa_giornaliera"),
            posizione=posizione,
            remoto=remoto,  # type: ignore[arg-type]
            links=links or [],
            utm=SignupUtm(
                utm_source=utm_source,
                utm_medium=utm_medium,
                utm_campaign=utm_campaign,
                utm_content=utm_content,
                utm_term=utm_term,
                utm_id=utm_id,
            ),
        )
    except ValidationError as exc:
        raise _validation_422(exc) from exc
    content = cv.file.read()
    # A CV that is not a small PDF raises `ValidationFailed`, which the app's handler
    # renders as the same 422 shape as the fields above.
    FreelancerService(session).apply(data, content, cv.filename or "", cv.content_type or "")
    return Ack()
