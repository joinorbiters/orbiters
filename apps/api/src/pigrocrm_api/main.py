from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pigrocrm.core.errors import DomainError
from pigrocrm_api.errors import domain_error_handler
from pigrocrm_api.routers import auth


def create_app() -> FastAPI:
    app = FastAPI(
        title="PigroCRM API",
        version="0.1.0",
        description=(
            "API pubblica di PigroCRM. La UI e il server MCP usano esclusivamente questi servizi."
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
    app.include_router(auth.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
