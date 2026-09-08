"""What the automations expose, and the four reasons one may decline to run.

The `motivo` values are a closed `Literal` in Python and a JSONB value in the database --
not a sized `String` column. A `String(24)` sized exactly to `stage_bersaglio_ambiguo`
would be a column sized precisely to its legal set, which is the defect slice 3 just fixed
on `invoices.tipo`: the width rejects a wrong value before the CHECK beside it can, and
Postgres answers with a raw truncation error instead of the named violation.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# New `kind` values. No migration: `activities.kind` is an open value by project
# (slice 1 §5.8) and `ActivityService.record` takes `kind: str` and truncates to the
# column width without consulting any Literal.
KIND_STAGE_MOVED = "automazione.stage_spostato"
KIND_NOT_EXECUTED = "automazione.non_eseguita"
KIND_CONFIG_CHANGED = "automazione.configurazione_modificata"
AUTOMATION_KINDS: tuple[str, ...] = (
    KIND_STAGE_MOVED,
    KIND_NOT_EXECUTED,
    KIND_CONFIG_CHANGED,
)

AutomationRule = Literal["A1", "A2"]

# The four declared conditions the runner absorbs. Anything not in this list propagates
# and rolls the trigger back (§9.3): a database that cannot write is not an automation
# that did not fire.
AutomationSkipReason = Literal[
    "stage_bersaglio_assente",
    "stage_bersaglio_ambiguo",
    "gia_nello_stato",
    "regola_disattivata",
]


class AutomationConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    a1_offerta_accettata_vince_deal: bool
    a2_offerta_inviata_avanza_deal: bool


class AutomationConfigUpdate(BaseModel):
    """Both optional, and read with `exclude_unset=True`.

    With two booleans, `None` and "not sent" must be distinguishable: `exclude_none` would
    make "switch A1 off without mentioning A2" indistinguishable from "switch A1 off and
    A2 on". This is residuo A14's shape, avoided rather than inherited -- there is no
    nullable typed column here, so no spelling of "clear it" is needed at all.

    `extra="forbid"`, because the only thing a misspelled key can do on a settings form is
    report success for a change that was not made.
    """

    model_config = ConfigDict(extra="forbid")

    a1_offerta_accettata_vince_deal: bool | None = None
    a2_offerta_inviata_avanza_deal: bool | None = None


class AutomationRuleDescription(BaseModel):
    codice: AutomationRule
    titolo: str
    descrizione: str
    attiva: bool


class AutomationRun(BaseModel):
    kind: str
    occurred_at: datetime
    deal_id: UUID | None
    regola: str | None
    motivo: str | None
    payload: dict[str, Any]


class AutomationsDescription(BaseModel):
    configurazione: AutomationConfigRead
    regole: list[AutomationRuleDescription]
    esecuzioni: list[AutomationRun]


# The prose an agent and a human both read. Here rather than in the service so the two
# surfaces cannot drift, and in Italian like every other user-facing string.
RULE_DESCRIPTIONS: dict[AutomationRule, tuple[str, str]] = {
    "A1": (
        "Offerta accettata → deal vinto",
        "Quando un'offerta passa da «inviata» ad «accettata», il deal collegato viene "
        "spostato nello stato con code «vinto», o nell'unico stato di tipo «won». Se lo "
        "stato manca o ce ne sono due, l'automazione non indovina: non fa nulla e "
        "registra il motivo.",
    ),
    "A2": (
        "Offerta inviata → il deal avanza",
        "Quando un'offerta passa da «bozza» a «inviata», il deal collegato avanza allo "
        "stato con code «offerta», ma solo se la sua posizione attuale è precedente. Non "
        "torna mai indietro: un deal già in negoziazione non retrocede perché è stata "
        "mandata una seconda offerta.",
    ),
}
