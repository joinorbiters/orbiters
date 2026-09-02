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

from pigrocrm.core.db import month_bounds, today_local, window_from
from pigrocrm.core.errors import ValidationFailed

# Ten years and a bit -- the span of the §16 reference corpus. A ceiling exists because
# §7.3 requires the predicate to always carry a bounded period: without one,
# `da=0001-01-01` is a full table scan requested from a query string.
MAX_PERIOD_DAYS = 3660


class Periodo(BaseModel):
    """Normalised and echoed back, always. A screenshot of a dashboard with no explicit
    period is a number with no unit (§4)."""

    da: date
    a: date


class PeriodoQuery(BaseModel):
    """The period, or nothing at all.

    Both bounds or neither. Supplying one and letting the service guess the other would
    silently answer a different question from the one asked, and the reader would have no
    way to see it -- the response echoes the period back for exactly this reason.
    """

    model_config = ConfigDict(extra="forbid")

    da: date | None = None
    a: date | None = None

    def resolve(self) -> Periodo:
        """The normalised period, or a named `ValidationFailed`.

        The `field` of every error here is the bound the caller must change, because
        `fieldErrorFrom` in the web client and an MCP agent both read it.
        """
        if (self.da is None) != (self.a is None):
            raise ValidationFailed(
                "periodo",
                "da" if self.da is None else "a",
                "il periodo richiede entrambe le date, o nessuna",
                expected="da e a insieme, oppure nessuna delle due",
            )
        if self.da is None or self.a is None:
            today = today_local()
            first, last = month_bounds(today.year, today.month)
            return Periodo(da=first, a=last)
        if self.da > self.a:
            raise ValidationFailed(
                "periodo",
                "da",
                "la data iniziale è successiva a quella finale",
                expected=f"da <= {self.a.isoformat()}",
            )
        # The ceiling is expressed as "the last day still admitted" rather than as
        # `(self.a - self.da).days`, for two reasons that happen to agree: a `-` anywhere
        # under `core/dashboard/` is forbidden without exception (§3, and
        # `test_dashboard_no_arithmetic.py`, whose BinOp exemption list is empty and
        # includes this file), and `window_from` is the same inclusive convention every
        # other period in slices 4 and 6 uses. A period of exactly MAX_PERIOD_DAYS days'
        # difference is admitted; the next day is not.
        _, ultimo_ammesso = window_from(self.da, MAX_PERIOD_DAYS)
        if self.a > ultimo_ammesso:
            raise ValidationFailed(
                "periodo",
                "a",
                "periodo troppo lungo",
                expected=f"al massimo {MAX_PERIOD_DAYS} giorni",
            )
        return Periodo(da=self.da, a=self.a)


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
