"""What a dashboard returns. Sub-plan 6C appends two more dashboards to this file.

Every money field is `Decimal` with `max_digits`/`decimal_places` matching the column it
came from, and every one arrives already summed. The frontend formats; it never adds
(§13, and Task B13's AST test).

This is the one module of `core/dashboard/` allowed to import `Decimal`, and Task B9's
scan names it as such: declaring a `Decimal` field performs no arithmetic, and the clause
exists to forbid arithmetic. Every other module in the package -- `service.py` and
whatever 6C adds -- may neither import `Decimal` nor contain a `*`, `/` or `-` operator,
so that a composition layer provably cannot invent a figure.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Periodo(BaseModel):
    """Normalised and echoed back, always. A screenshot of a dashboard with no explicit
    period is a number with no unit (§4)."""

    da: date
    a: date


class PipelineStageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage_id: str
    stage_code: str | None
    stage_nome: str
    posizione: int
    numero: int
    valore_totale: Decimal = Field(max_digits=12, decimal_places=2)
    # Counted, never summed as zero (§4). A missing expected value is not a value of zero,
    # and a reader has no way to tell the two apart from a total alone.
    senza_valore: int
    # §3 exception 1. Labelled "stima" in every rendering and never added to revenue.
    valore_ponderato: Decimal = Field(max_digits=12, decimal_places=2)


class ClosedInPeriod(BaseModel):
    vinti: int
    persi: int
    # `Σ valore_previsto` of the deals won in the period. **Not revenue** and not
    # comparable with it: it is what the deal *claimed*. The revenue of those same deals
    # is on the economic dashboard, and the two figures live on two pages for exactly this
    # reason (§4).
    valore_vinto: Decimal = Field(max_digits=12, decimal_places=2)
    # §3 exception 2. Per cent, two places. `None` -- never `0` -- when nothing closed:
    # zero per cent means "I lost everything", no closed deals means something else. Same
    # rule as slice 4 §7.1's margin percentage, computed by the same `money.percentage_of`
    # so that it is one rule and not two that agree today.
    tasso_conversione: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)


class PendingOffer(BaseModel):
    document_id: str
    titolo: str
    deal_id: str | None
    customer_id: str | None
    stato_dal: date | None
    # `None`, not 0, when `stato_dal` is unknown: zero days would read as "sent today".
    giorni: int | None


class CommercialDashboard(BaseModel):
    """One endpoint, one transaction, one instant (§7.1).

    `calcolato_alle` is the `transaction_timestamp()` of *that* transaction, and the
    browser shows its age. A number with no age is a number the user believes is
    instantaneous.
    """

    periodo: Periodo
    calcolato_alle: datetime
    pipeline: list[PipelineStageSummary]
    chiusure: ClosedInPeriod
    offerte_in_attesa: list[PendingOffer]
    offerte_in_attesa_totale: int
    chiusure_previste_30_giorni: int
    # §4.1: deals closed before `chiuso_il` existed cannot be attributed to a period. The
    # dashboard declares how many rather than counting them as zero.
    chiusure_non_attribuibili: int
    # §6.2's first signal, and the permanent cross-check on automation A1.
    offerte_accettate_deal_non_vinto: int
