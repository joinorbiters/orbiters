from fastapi import FastAPI
from sqlalchemy import text

from orbiters_api.deps import SessionDep
from orbiters_api.routers import companies, freelancers, signups


def create_app() -> FastAPI:
    app = FastAPI(title="Orbiters API", version="0.1.0")
    app.include_router(signups.router)
    app.include_router(freelancers.router)
    app.include_router(companies.router)

    @app.get("/health")
    def health(session: SessionDep) -> dict[str, str]:
        """Touches the database on purpose: a probe that answers from configuration
        alone reports a healthy deploy with Postgres on the floor
        (`docs/adding-a-project.md` §7)."""
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
