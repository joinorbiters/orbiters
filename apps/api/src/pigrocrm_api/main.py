from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pigrocrm.core.errors import DomainError
from pigrocrm_api.errors import domain_error_handler
from pigrocrm_api.routers import (
    auth,
    customers,
    deals,
    fields,
    people,
    pipeline,
    schema,
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

    for module in (auth, customers, people, deals, fields, pipeline, users, tokens, schema):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
