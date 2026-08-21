"""The fiscal parameters, as a value object and as the API's Create/Read pair.

`FiscalSnapshot` is what gets frozen onto an issued invoice and what the exporter and
the PDF read. It is a plain Pydantic model with no `id` and no timestamps precisely so
that it can be serialised into `invoices.snapshot` and read back three years later
without the row it came from still existing in its original shape.
"""

import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.validation import SafeStr

# `RF01`..`RF19`, the codes FPR12's own `RegimeFiscaleType` enumerates. `.fullmatch`
# is what the callers use, never `.match` with `$`: "RF19\n" is five characters and
# would reach the String(4) column as a raw, session-poisoning DataError.
CODICE_REGIME_RE = re.compile(r"RF(0[1-9]|1[0-9])")

CODICE_REGIME_MAX_LENGTH = 4
NATURA_MAX_LENGTH = 4
CONDIZIONI_PAGAMENTO_MAX_LENGTH = 4
MODALITA_PAGAMENTO_MAX_LENGTH = 4
IBAN_MAX_LENGTH = 34
MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
RATE_MAX_DIGITS = 5
RATE_DECIMAL_PLACES = 2
GIORNI_SCADENZA_MIN = 0
GIORNI_SCADENZA_MAX = 365

# the previous system shipped `RiferimentoNormativo` as "N2.2 (non soggette - altri casi)", which is
# the *description of the code*, not a normative reference. This is the real one for
# the forfettario, and it is a default rather than a constant because the article
# numbers have changed before.
DEFAULT_RIFERIMENTO_NORMATIVO = (
    "Operazione non soggetta a IVA ai sensi dell'art. 1, commi 54-89, "
    "L. 190/2014 - regime forfettario"
)

# Values of law, not preferences: 77.47 EUR is the threshold above which the stamp
# duty is due and 2.00 EUR is its amount. Configurable because the law has already
# changed them once.
DEFAULT_SOGLIA_BOLLO = Decimal("77.47")
DEFAULT_IMPORTO_BOLLO = Decimal("2.00")


class FiscalSnapshot(BaseModel):
    """The parameters as they were when an invoice was issued.

    Frozen, so nothing downstream of `InvoiceService.issue` can mutate a value the
    document was built from; `extra="forbid"` so a stored snapshot written by a later
    version of this model is a loud failure rather than a silently ignored field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    codice_regime: str = Field(max_length=CODICE_REGIME_MAX_LENGTH)
    aliquota_iva_default: Decimal = Field(
        max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES
    )
    natura_default: str | None = Field(default=None, max_length=NATURA_MAX_LENGTH)
    riferimento_normativo: str | None = None
    applica_bollo: bool
    soglia_bollo: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    importo_bollo: Decimal = Field(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    condizioni_pagamento: str = Field(max_length=CONDIZIONI_PAGAMENTO_MAX_LENGTH)
    modalita_pagamento: str = Field(max_length=MODALITA_PAGAMENTO_MAX_LENGTH)
    giorni_scadenza: int = Field(ge=GIORNI_SCADENZA_MIN, le=GIORNI_SCADENZA_MAX)
    iban: str | None = Field(default=None, max_length=IBAN_MAX_LENGTH)


__all__ = [
    "CODICE_REGIME_RE",
    "DEFAULT_IMPORTO_BOLLO",
    "DEFAULT_RIFERIMENTO_NORMATIVO",
    "DEFAULT_SOGLIA_BOLLO",
    "FiscalSnapshot",
    "SafeStr",
]
