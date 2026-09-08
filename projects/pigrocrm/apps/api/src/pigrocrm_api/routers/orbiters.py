"""The one public write in the API: an email address for the Orbiters community.

No `ActorDep`, deliberately. The page that posts here is the landing, and its visitor
has no account -- that is the whole point of the form. Everything else that protects
the CRM stays where it was: this router reaches only the `orbiters` database
(`OrbitersSessionDep`), never the CRM's session, so an unauthenticated request cannot
touch a customer, a deal or an invoice through it.
"""

from fastapi import APIRouter, Response, status

from pigrocrm.core.orbiters import SignupCreate, SignupRead, SignupService
from pigrocrm_api.deps import OrbitersSessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/orbiters", tags=["orbiters"], responses=PROBLEM_RESPONSES)


@router.post("/signups", response_model=SignupRead, status_code=status.HTTP_201_CREATED)
def subscribe(data: SignupCreate, session: OrbitersSessionDep, response: Response) -> SignupRead:
    """201 the first time an address is seen, 200 when it was already on the list. Both
    are the same body and the same outcome for the person: they are on the list."""
    result = SignupService(session).subscribe(data)
    if not result.nuova:
        response.status_code = status.HTTP_200_OK
    return result
