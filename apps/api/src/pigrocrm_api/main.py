from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pigrocrm.core.errors import DomainError
from pigrocrm_api.errors import domain_error_handler, ensure_validation_error_schemas_are_declared
from pigrocrm_api.routers import (
    analytics,
    auth,
    cost_categories,
    costs,
    customers,
    deals,
    documents,
    emitter,
    fields,
    fiscal_profile,
    gmail,
    invoices,
    people,
    period_locks,
    pipeline,
    schema,
    templates,
    time_entries,
    tokens,
    users,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="PigroCRM API",
        version="0.1.0",
        description=(
            "API pubblica di PigroCRM. La UI e il server MCP usano esclusivamente questi servizi. "
            "Il campo `custom_fields` di ogni entità è deliberatamente un oggetto libero in "
            "questo documento: le chiavi realmente presenti dipendono dalle field_definitions "
            "configurate a runtime da ciascun tenant e non sono, e non possono essere, fissate "
            "qui. Chiama `GET /api/schema/{entity_type}` per scoprire, in ogni momento, quali "
            "campi custom esistono per una data entità, con il loro tipo e le eventuali opzioni."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(DomainError, domain_error_handler)

    for module in (
        auth,
        customers,
        people,
        deals,
        fields,
        pipeline,
        users,
        tokens,
        schema,
        documents,
        templates,
        emitter,
        invoices,
        fiscal_profile,
        time_entries,
        costs,
        cost_categories,
        period_locks,
        analytics,
        gmail,
    ):
        app.include_router(module.router)

    # PROBLEM_RESPONSES (attached to every router above) declares a 422 that
    # `$ref`s HTTPValidationError alongside ProblemDetail -- see
    # ensure_validation_error_schemas_are_declared's docstring for why that
    # reference would otherwise point at nothing: declaring 422 at all, on every
    # router, suppresses the automatic registration FastAPI would otherwise do.
    # `generate_openapi` (the bound method, captured before it is replaced below)
    # already handles the title/version/description/routes wiring and the
    # `self.openapi_schema` caching; this only post-processes its result.
    generate_openapi = app.openapi

    def openapi_with_validation_error_schemas() -> dict[str, Any]:
        return ensure_validation_error_schemas_are_declared(generate_openapi())

    app.openapi = openapi_with_validation_error_schemas  # type: ignore[method-assign]

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
