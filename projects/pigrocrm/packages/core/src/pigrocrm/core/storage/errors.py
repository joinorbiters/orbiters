"""The one refusal a document backend can produce before it exists.

Everything else `DocumentStorage` raises is about a *key* or about Google -- an unsafe
key is `ValidationFailed` from `storage/base.py`, a missing blob is `NotFound`, a Drive
outage is a `Conflict` from `drive/transport.py`. This one is about the installation:
the backend chosen is `gdrive`, no service account is configured, and the titolare has
not yet connected Drive and chosen the folder that generated documents are written
into. Nothing is broken and nothing is missing; a setup step has not happened.

It is a module of its own rather than a line in `core/errors.py` for the reason
`drive/errors.py` gives for itself: the sentence has to survive the trip to the screen,
and the sentence is the whole value of this class. `core/errors.py` holds the five
shapes every domain shares; this holds the one thing storage knows how to say.
"""

from pigrocrm.core.errors import Conflict

# The entity every failure about a document's bytes is reported under -- the same one
# `drive/transport.py` uses (`_ENTITY`), because the API and the MCP adapter both
# render `Conflict.details["entity"]` and an adapter that routed on it would otherwise
# send the reader to a different place for two failures of the same feature.
STORAGE_ENTITY = "document_blob"

# The whole point of the class. An operator setting `PIGROCRM_STORAGE_BACKEND=gdrive`
# has two ways to finish the job, and this is the one that needs no Google Cloud
# console: connect Drive as yourself and say which folder to write into. The sentence
# names the screen, because this error is the only place the reader is looking.
NOT_CONFIGURED_REASON = (
    "Google Drive non è pronto a ricevere i documenti: collega Drive e scegli la "
    "cartella di scrittura in Impostazioni → Drive"
)


class StorageNotConfigured(Conflict):
    """Raised at the first operation, never at construction.

    A `Conflict` and not a `ValidationFailed`, deliberately: nothing about the caller's
    request is wrong, and a 422 with a field name would send somebody looking for a bad
    parameter. It is the state of the installation that conflicts with the operation
    asked for, which is what `Conflict` means everywhere else in this codebase -- and it
    is already mapped (409 by the API, guidance by the MCP adapter), so no adapter has
    to learn a new code for it.

    Deliberately built with no arguments: there is exactly one thing to say and one
    place to say it, and a `reason` parameter would let two call sites word it
    differently.
    """

    def __init__(self) -> None:
        super().__init__(STORAGE_ENTITY, NOT_CONFIGURED_REASON)
