"""The relevance mechanism, as pure functions.

Spec 4 names the failure mode to avoid: synchronising a mailbox. A mailbox holds the
newsletters, the Amazon receipts, the messages from the children's school, and the
conversations with clients. Ingesting all of it and filtering afterwards means all of
it went through the process -- a broken promise even if 98% is then discarded.

So the filter is applied *server-side*, inside the `q`, and this module is the only
place a Gmail URL can be built at all. Two guards, because either alone is one edit
from being defeated:

  * `messages_list_url` refuses a `q` with no address-bearing clause, which makes the
    bug spec 4.1 names unconstructible rather than merely forbidden;
  * `tests/test_gmail_query.py` walks the AST of every source file in the repository
    and fails if any of them holds a Gmail host or a listing path in a string literal,
    so a caller that wants to bypass this module has nowhere left to write the URL.

`tests/test_gmail_sync.py` adds the third once there is a sync to run: the same
property asserted over the requests the fake transport actually received.

Everything here is a pure function over validated input. Nothing in this module reads
the database, and nothing in it accepts free text: there is deliberately no builder
that takes a caller-supplied Gmail search string, because spec 8.2 and 12 say no
surface in this slice offers one, and the cheapest way to keep that true is to have
nothing to call.
"""

import re
from collections.abc import Sequence
from urllib.parse import urlencode

from pigrocrm.core.errors import ValidationFailed

GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
# Twenty: Gmail's `q` has a practical length limit, and twenty addresses at two clauses
# each fit with margin. Configurable via PIGROCRM_GMAIL_SYNC_ADDRESS_BATCH_SIZE so the
# number can be corrected without touching code.
ADDRESS_BATCH_DEFAULT = 20
MAX_RESULTS_PER_PAGE = 100

# Deliberately stricter than RFC 5322: this string is interpolated into a Gmail query
# expression, so anything that could terminate a clause or introduce an operator has to
# be impossible, not merely unusual. `re.fullmatch`, never `re.match` with `$` -- `$`
# also matches before a trailing newline, which is exactly the character an injection
# would use.
_SAFE_ADDRESS = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,63}")
# The local part of a Message-ID is case-sensitive (RFC 5322 3.6.4), so this one is not
# folded to lower case the way an address is. Same shape otherwise, and the same
# reason: it is interpolated into a query expression.
_SAFE_MESSAGE_ID = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}")
# What makes a query legitimate: at least one clause naming an actual address. The `@`
# is load-bearing and not decoration -- `from:acme` is not a filter on a known
# correspondent, it is a Gmail free-text search over sender display names, which is the
# broad search this whole module exists to prevent.
_HAS_ADDRESS_CLAUSE = re.compile(r"\b(?:from|to|cc|bcc|rfc822msgid):\S*@\S")
# Gmail's own ids, which are hex-ish but documented only as opaque. Constrained here
# because they are interpolated into a *path*: a `/` or a `..` in one would address a
# different endpoint entirely.
_SAFE_ID = re.compile(r"[A-Za-z0-9_\-]{1,128}")


def _checked(address: str) -> str:
    normalised = address.strip().lower()
    if not _SAFE_ADDRESS.fullmatch(normalised):
        raise ValidationFailed(
            "gmail_query",
            "address",
            "non è un indirizzo email interpolabile in una query Gmail",
            expected="local@dominio.tld, senza spazi, parentesi o virgolette",
        )
    return normalised


def _checked_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValidationFailed(
            "gmail_query", "id", "un id Gmail contiene solo lettere, cifre, - e _"
        )
    return value


def build_address_clause(addresses: Sequence[str]) -> str:
    """`(from:a OR to:a OR from:b OR to:b …)` -- both directions per address, because a
    conversation is relevant whoever started it."""
    if not addresses:
        raise ValidationFailed(
            "gmail_query", "addresses", "una clausola di indirizzi non può essere vuota"
        )
    terms: list[str] = []
    for address in addresses:
        safe = _checked(address)
        terms.append(f"from:{safe}")
        terms.append(f"to:{safe}")
    return "(" + " OR ".join(terms) + ")"


def build_list_queries(
    addresses: Sequence[str], *, after_epoch: int, batch_size: int = ADDRESS_BATCH_DEFAULT
) -> tuple[str, ...]:
    """One query per batch of addresses. An empty roster yields **no** queries -- not
    one unfiltered query, which is the whole point.

    Duplicates are collapsed, in order: the roster is assembled from customers, people
    and deals, so the same address arrives more than once routinely, and three
    identical clauses would spend a third of the `q`'s length limit on nothing.

    `after:` takes epoch seconds, not a date: a date loses the hours and forces
    re-reading an entire day on every cycle.
    """
    if batch_size < 1:
        raise ValidationFailed("gmail_query", "batch_size", "deve essere almeno 1", expected=">= 1")
    if after_epoch < 0:
        raise ValidationFailed("gmail_query", "after_epoch", "non può essere negativo")
    unique = list(dict.fromkeys(_checked(address) for address in addresses))
    return tuple(
        f"{build_address_clause(unique[start : start + batch_size])} after:{after_epoch}"
        for start in range(0, len(unique), batch_size)
    )


def messages_list_url(
    query: str, *, page_token: str | None = None, max_results: int = MAX_RESULTS_PER_PAGE
) -> str:
    """The only way to build a `users.messages.list` URL in this codebase.

    It refuses a `q` with no address-bearing clause. That refusal is the mechanism of
    spec 4.1: a listing without an address filter cannot be constructed, so it cannot
    be shipped by accident.
    """
    if not _HAS_ADDRESS_CLAUSE.search(query):
        raise ValidationFailed(
            "gmail_query",
            "q",
            "un elenco di messaggi senza un filtro su un indirizzo noto è un bug, "
            "non una ricerca ampia",
            expected="una clausola from:, to: o rfc822msgid: che nomini un indirizzo",
        )
    params: dict[str, str] = {"q": query, "maxResults": str(max_results)}
    if page_token:
        params["pageToken"] = page_token
    return f"{GMAIL_API_ROOT}/messages?{urlencode(params)}"


def thread_get_url(thread_id: str) -> str:
    return f"{GMAIL_API_ROOT}/threads/{_checked_id(thread_id)}?format=full"


def message_get_url(message_id: str) -> str:
    return f"{GMAIL_API_ROOT}/messages/{_checked_id(message_id)}?format=full"


def rfc822msgid_query(message_id_header: str) -> str:
    """Finds one exact message by the `Message-ID` we generated ourselves. This is the
    one query in the slice that is not built from the address roster, and it is allowed
    because it is *more* specific, not less: it names a single message, and one we
    created. Used only by the send reconciliation of spec 6.3."""
    stripped = message_id_header.strip().strip("<>")
    if not _SAFE_MESSAGE_ID.fullmatch(stripped):
        raise ValidationFailed(
            "gmail_query", "message_id_header", "non è un Message-ID interpolabile"
        )
    return f"rfc822msgid:{stripped}"
