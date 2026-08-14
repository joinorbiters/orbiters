"""One interface, two implementations. The metadata always lives in Postgres.

Search, permissions, timeline and versions work identically on both backends, and
changing backend loses nothing but the bytes already uploaded -- for which an explicit
migration is needed, not a change of environment variable (spec 5).
"""

import re
from datetime import timedelta
from typing import Protocol

from pigrocrm.core.errors import ValidationFailed

MAX_KEY_LENGTH: int = 255

# A key is a relative POSIX-style path: segments of `[A-Za-z0-9._-]`, separated by a
# single `/`, each segment starting with an alphanumeric. `re.fullmatch` below, never
# `re.match` with `$`, because `$` matches before a trailing newline -- which would let
# "a.pdf\n" through and reach the filesystem, and reach the `String(255)` column, as
# something neither had agreed to.
#
# The character class is ASCII-only by construction (no `\w`, no Unicode letters), which
# is also what makes Unicode normalisation a non-issue: none of `A-Za-z0-9._-` or `/` has
# more than one Unicode Normalization Form, so any key this pattern accepts is already
# identical under NFC and NFD. A key that is *not* ASCII is refused outright, not
# silently re-encoded.
_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")

# Windows reserves these as device names regardless of extension or case: "con",
# "CON" and "con.pdf" are all illegal there, even though ext4/APFS do not care. This
# backend runs fine without the check, but `validate_storage_key` is the one gate a
# future remote backend shares (see the module docstring), and a key that is safe for
# one and not the other is not safe.
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{digit}" for digit in range(1, 10)),
    *(f"LPT{digit}" for digit in range(1, 10)),
}


def _unsafe_segment(segment: str) -> bool:
    """A segment the character-class regex above lets through but that is still unsafe
    to hand to *some* real filesystem.

    A trailing dot: Windows' own API layer silently strips it, so "a." and "a" can name
    the same file there even though POSIX treats them as different names -- exactly the
    kind of divergence `validate_storage_key` exists to prevent (module docstring).

    A reserved device name, matched on the segment's stem (before the first dot) so
    both "aux" and "aux.pdf" are caught: Windows refuses to create either, in any
    directory, regardless of case.
    """
    if segment.endswith("."):
        return True
    stem = segment.split(".", 1)[0]
    return stem.upper() in _WINDOWS_RESERVED_NAMES


def validate_storage_key(key: str) -> str:
    """The one gate every backend calls before touching anything.

    Checked here rather than inside each implementation so `LocalFileStorage` and
    `GDriveStorage` cannot drift: a key that is safe for one and not the other is a
    key that is not safe.

    `".."` is refused explicitly on top of the pattern. The pattern alone already
    rejects it (a segment must start with an alphanumeric), but a future widening of
    the character class would silently reopen path traversal, and this line will
    still be here.

    Pure string checking, no filesystem access: this function has no way to see a
    symlink planted at the destination, so `LocalFileStorage` layers its own
    containment check on top after this one passes.
    """
    if (
        not _KEY_RE.fullmatch(key)
        or len(key) > MAX_KEY_LENGTH
        or ".." in key
        or any(_unsafe_segment(segment) for segment in key.split("/"))
    ):
        raise ValidationFailed(
            "document_version",
            "storage_key",
            "chiave di storage non valida",
            expected="segmenti alfanumerici separati da '/', max 255 caratteri",
        )
    return key


class DocumentStorage(Protocol):
    """`signed_url` returns `None` on a backend that has no such concept.

    On `LocalFileStorage` that is the whole design: the download goes through the
    API, which is the only place authorisation exists.
    """

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def signed_url(self, key: str, ttl: timedelta) -> str | None: ...
