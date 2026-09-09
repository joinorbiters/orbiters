"""Attività: a commitment with a due date and a state.

The table slice 7 specified on 2026-09-03 and slice 10 built on 2026-09-09, when the
calendar needed something to put in a day. Everything about the shape -- why `scadenza`
is nullable, why there are three states and not two, why at most one reference -- is in
`2026-09-03-slice-7-attivita-e-promemoria-design.md` §3 and repeated where the code
would otherwise be surprising.
"""

from pigrocrm.core.attivita.models import Attivita
from pigrocrm.core.attivita.repository import AttivitaRepository
from pigrocrm.core.attivita.schemas import (
    ATTIVITA_SORTS,
    AttivitaCreate,
    AttivitaListQuery,
    AttivitaOrigine,
    AttivitaPage,
    AttivitaRead,
    AttivitaStato,
    AttivitaUpdate,
)
from pigrocrm.core.attivita.service import AttivitaService

__all__ = [
    "ATTIVITA_SORTS",
    "Attivita",
    "AttivitaCreate",
    "AttivitaListQuery",
    "AttivitaOrigine",
    "AttivitaPage",
    "AttivitaRead",
    "AttivitaRepository",
    "AttivitaService",
    "AttivitaStato",
    "AttivitaUpdate",
]
