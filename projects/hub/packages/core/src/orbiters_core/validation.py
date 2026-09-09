"""`SafeStr`: a string that refuses a NUL byte before it reaches Postgres.

`"\\x00"` is valid JSON and an ordinary Python `str`, so it sails through pydantic and
reaches `flush()`, where Postgres refuses a NUL byte in `text`/`varchar` and the driver
raises a raw, uncaught exception. Rejected rather than stripped: the caller is choosing
a value for their own record and can be told to fix it, and silently deleting one
invisible byte is how a character disappears with nobody noticing. The same type, with
the same reasoning, that PigroCRM's `validation.py` applies to every user-supplied string.
"""

from typing import Annotated, Any

from pydantic import BeforeValidator, ValidationInfo


def _reject_nul(value: Any, info: ValidationInfo) -> Any:
    if isinstance(value, str) and "\x00" in value:
        field = info.field_name or "valore"
        raise ValueError(f"{field}: il testo contiene un carattere nullo (\\x00), non ammesso")
    return value


SafeStr = Annotated[str, BeforeValidator(_reject_nul)]
