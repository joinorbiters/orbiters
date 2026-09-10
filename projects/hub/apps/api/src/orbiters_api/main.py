from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from orbiters_api.deps import SessionDep
from orbiters_api.routers import admin, companies, freelancers, members, signups
from orbiters_core.errors import DomainError, NotFound, ValidationFailed


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A domain error is a sentence and a status, never a stack trace. `NotFound` is a
    404, `ValidationFailed` a 422 in FastAPI's own shape so a form can point at the
    field, anything else a 409."""
    assert isinstance(exc, DomainError)
    if isinstance(exc, NotFound):
        return JSONResponse({"detail": exc.message}, status_code=404)
    if isinstance(exc, ValidationFailed):
        return JSONResponse(
            {
                "detail": [
                    {
                        "loc": ["body", exc.details["field"]],
                        "msg": exc.details["reason"],
                        "type": "value_error",
                    }
                ]
            },
            status_code=422,
        )
    return JSONResponse({"detail": exc.message}, status_code=409)


def create_app() -> FastAPI:
    app = FastAPI(title="Orbiters API", version="0.1.0")
    app.add_exception_handler(DomainError, domain_error_handler)
    app.include_router(signups.router)
    app.include_router(freelancers.router)
    app.include_router(companies.router)
    app.include_router(admin.router)
    app.include_router(members.router)

    @app.get("/health")
    def health(session: SessionDep) -> dict[str, str]:
        """Touches the database on purpose: a probe that answers from configuration
        alone reports a healthy deploy with Postgres on the floor
        (`docs/adding-a-project.md` §7)."""
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
