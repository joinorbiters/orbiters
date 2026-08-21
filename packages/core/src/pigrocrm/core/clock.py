"""The one clock the fiscal parts of this system read "today" from.

`date.today()` and `datetime.now()` (no argument) both read the *process's* system
timezone, and this project does not control that end to end: `Dockerfile.api` pins no
`TZ`, so the `python:3.13-slim-bookworm` image it starts from runs in UTC by default,
and a developer's own machine can be anywhere at all. the previous system's own defect
(`formatIsoDate` calling `toISOString()`, which moved an invoice issued at 23:30 CET
on 31 December into 1 January -- the wrong fiscal year on an immutable document) was a
UTC projection of an instant. A bare `date.today()` on a host running in UTC -- or in
any zone other than Italy's -- reproduces that exact defect through the standard
library's own default rather than through an explicit conversion, which is precisely
why it is not safe to treat as "no instant here to mis-project".

`oggi_in_italia()` is what actually closes it: `zoneinfo.ZoneInfo("Europe/Rome")`
resolves CET/CEST -- including the daylight-saving transition -- correctly regardless
of the process's own system timezone. The `tzdata` package is a declared dependency
specifically so this does not depend on the host shipping the IANA database itself
(a base image is not guaranteed to; Python's own documentation recommends `tzdata` for
exactly that reason).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

ITALY_TZ = ZoneInfo("Europe/Rome")


def oggi_in_italia() -> date:
    """Today's date in the issuer's own calendar.

    This is what spec 6.2 means by "today" when `data_emissione` is omitted, and it is
    the reference every "not in the future" / "not before this year" check in
    `InvoiceService.issue` compares against. There is no instant to mis-project here
    *only* because the conversion is explicit and always targets Europe/Rome, not
    because `datetime.now()` was avoided.
    """
    return datetime.now(ITALY_TZ).date()


__all__ = ["ITALY_TZ", "oggi_in_italia"]
