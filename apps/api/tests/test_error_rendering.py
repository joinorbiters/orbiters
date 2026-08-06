from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pigrocrm.core.errors import Conflict, DomainError
from pigrocrm_api.errors import domain_error_handler


def _throwaway_app() -> FastAPI:
    """A minimal app, not the real one: nothing in the real auth router raises a
    domain error carrying a UUID in its details yet, so this is the only way to
    exercise the rendering bug without waiting for a later task's entity routers."""
    app = FastAPI()
    app.add_exception_handler(DomainError, domain_error_handler)

    @app.get("/boom")
    def boom() -> None:
        raise Conflict("pipeline_stage", "ha ancora dei deal collegati", stage_id=uuid4())

    return app


def test_a_uuid_in_domain_error_details_still_renders_a_clean_problem_document() -> None:
    """`DomainError`'s **details is typed Any -- nothing stops a caller from putting a
    UUID in it, and json.dumps (what JSONResponse uses to render its body) cannot
    serialise one. Before jsonable_encoder, this raised inside domain_error_handler
    itself while building the response, turning what should be a clean 409 into an
    opaque, unhandled 500."""
    with TestClient(_throwaway_app()) as client:
        response = client.get("/boom")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "conflict"
    # jsonable_encoder turns the UUID into its string form -- json.dumps could not
    # have produced this body at all otherwise.
    assert isinstance(body["stage_id"], str)
    assert len(body["stage_id"]) == 36
