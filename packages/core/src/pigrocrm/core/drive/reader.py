"""Read-only Drive, confined to the folders the titolare pointed at.

Spec 9C names the failure to avoid: reading somebody's Drive. A personal Drive holds
the photos of their children, their rent contract, the folder of another job. So this
module can do exactly three things -- list the children of a folder, fetch the bytes of
one file, turn those bytes into text -- and each of them refuses outright unless the
subject is inside `google_drive_accounts.root_folder_ids`.

**Where the confinement lives.** `drive/query.py` is the first guard: it will not build
a `files.list` that is not scoped to one folder, and it has no search-string builder at
all. That is not enough on its own, because `children_query("<a folder of somebody's
Drive>")` is perfectly well-formed. The second guard is here, and it is
`is_within_roots`: `files.get?fields=id,parents` walked upward until a configured root
is reached, the Drive's own root is reached, or `MAX_ROOT_WALK_LEVELS` levels have been
spent. Outside the roots, `list_children` and the two `read_*` raise `NotFound` --
**before** any `files.list` is issued, so there is no window in which Google was asked
about a folder nobody configured. The third guard is
`tests/test_drive_reader.py`'s closing test, which re-reads every request the fake
transport received across the whole module and checks each listing named a folder of
the hierarchy.

**One sentence for three different situations.** A file that does not exist, a file in
an unconfigured corner of the titolare's own Drive and a file in a stranger's Drive all
answer `NotFound("drive_file", <id>)`, in the same words. Distinguishing them would
answer "is there a file with this id?" for anybody who can reach the tool, which is an
existence oracle over all of Google Drive.

**Two severities for an id, from `query.py`.** Every id a *caller* supplies -- the
`folder_id` of a listing, the `file_id` of a read -- is checked against the strict
pattern before anything happens, and that check is `query.py`'s own rather than a
second regex here: two patterns for one rule is one pattern that will drift. Ids that
came out of Drive's own answers (a child of a listing, a parent of a metadata call)
pass only the builders' laxer check, for the reason that module's docstring gives at
length.

**Nothing here writes.** Not a `files.create`, not a `files.delete`, not an upload:
`storage/gdrive.py` remains the only writer of Drive, on its own credential, and 9D is
what imports a file into a document. A reader that could also write would make "read
these folders" a promise held up by nobody checking.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import DRIVE_TEXT_MAX_BYTES_DEFAULT, Settings, decode_google_token_key
from pigrocrm.core.drive.account import GoogleDriveAccountService
from pigrocrm.core.drive.errors import DriveCredentialRevoked
from pigrocrm.core.drive.query import (
    FOLDER_MIME,
    # The strict shape of an id that arrives from outside, imported rather than
    # rewritten: `query.py` is where that shape is defined, and a copy here would be a
    # second pattern to keep in step with it. The `field=` is what makes it usable for
    # a file as well as a folder -- see that function's docstring.
    checked_outside_id,
    children_query,
    file_export_url,
    file_media_url,
    file_meta_url,
    files_list_url,
)
from pigrocrm.core.drive.schemas import DRIVE_SCOPE_READONLY
from pigrocrm.core.drive.text import PLAIN_TEXT_MIME, DriveText, drive_text
from pigrocrm.core.drive.transport import DriveTransport, UserTokens
from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.gmail.crypto import unseal
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport

# The entity every refusal of this module is reported under. One name for a folder and
# a file alike, deliberately: the entity is part of what a caller reads, and saying
# `drive_folder` for one and `drive_file` for the other would tell apart the two cases
# the identical message above exists to keep indistinguishable.
ENTITY = "drive_file"

# How far up the parent chain a file may be from a configured root. Drive lets a file
# have several parents, so "walk upward" is a graph and not a path: without a bound, a
# cycle (which a Drive bug can produce, and which this code must survive rather than
# trust away) would spin against Google forever. Twenty is far past any real filing --
# a folder nested twenty deep under a root is a folder nobody navigates by hand.
MAX_ROOT_WALK_LEVELS = 20

# And how many `files.get` calls that walk may spend in total. The level bound is not
# enough on its own: a file may have many parents, so one level can be three hundred
# folders wide, and twenty levels of that is a walk that spends somebody's Drive quota
# to answer one question. A file whose ancestry fans out past this is reported outside
# the roots -- the safe direction, and a filing with two hundred distinct ancestors is
# not one anybody navigates.
MAX_ROOT_WALK_REQUESTS = 200

# The ceiling on the bytes of a single file, and the reason it is not the text ceiling:
# a 4 MB PDF is an ordinary contract whose text is eight kilobytes, so sharing one
# number with `read_text` would refuse the documents this slice exists to read. Above
# it a read is refused rather than cut, because half a PDF is not a PDF -- truncation
# is meaningful for text and meaningless for bytes. Same 20 MB as
# `gmail_attachment_max_bytes`, which is the same question about the same kind of file.
DOWNLOAD_MAX_BYTES = 20_971_520

# `application/vnd.google-apps.document` and its siblings. A native Google file has no
# bytes of its own on Drive -- `alt=media` on one answers 403 -- so a Doc is read
# through `files.export`, and a Sheet or a Slide deck has no text export this slice
# would know what to do with.
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."

# What each call asks for, in the words a failure will carry (`DriveTransport` puts
# `what` into the `Conflict` a person reads). Italian, like every other user-facing
# sentence in this codebase.
_WHAT_LIST = "elenco dei file della cartella Drive"
_WHAT_META = "lettura dei dati del file Drive"
_WHAT_DOWNLOAD = "download del file da Drive"
_WHAT_EXPORT = "conversione in testo del documento Google"

_ENTRY_FIELDS = "id, name, mimeType, size, modifiedTime, parents"
_LIST_FIELDS = f"nextPageToken, files({_ENTRY_FIELDS})"
# The walk upward needs nothing but the edges of the graph.
_PARENT_FIELDS = "id, parents"

_NOT_A_FOLDER = "una cartella non ha byte da leggere: elencane i figli"
_NO_BYTES = "un file {mime} non ha byte da scaricare né un export in testo"
_TOO_BIG = "il file supera {max_bytes} byte: aprilo su Drive invece di importarlo"

_REVOKED_REASON = (
    "Il consenso Google Drive per {email} è stato revocato: la lettura dei documenti "
    "è sospesa finché non ricolleghi Drive da Impostazioni → Drive."
)

_T = TypeVar("_T")


@dataclass(frozen=True)
class DriveEntry:
    """One child of a folder. Italian field names, like every other schema a person or
    an agent reads.

    `dimensione` is `None` and not `0` for a folder or a native Google file: those have
    no bytes on Drive to measure, and `0` would say "an empty file", which is a
    different and false statement. Same for `modificato_il`, which Drive can omit.
    """

    id: str
    nome: str
    mime: str
    dimensione: int | None
    modificato_il: datetime | None
    cartella: bool


@dataclass(frozen=True)
class DriveListing:
    """One page of children. `next_page_token` is Drive's own: the reader never chooses
    a page size (`files_list_url` cannot even express one), so how a folder is split
    into pages is Drive's business and this token is how the caller asks for the rest.
    """

    items: list[DriveEntry]
    next_page_token: str | None


class DriveReader:
    """Three operations on the configured roots, and no way to reach anything else.

    Holds a `DriveTransport` and a list of root folder ids -- no session, no settings,
    no `Actor`: whether this credential may be used at all was decided before it was
    built (`GoogleDriveAccountService.usable`, through `drive_reader_for`), and a reader
    that could re-decide it would be a second gate to keep in step with the first.

    `on_revoked` is the one callback: a revoked grant is learned here, deep in an HTTP
    call, and recorded by whoever owns the account row. See `drive_reader_for`.
    """

    def __init__(
        self,
        transport: DriveTransport,
        *,
        roots: Sequence[str],
        text_max_bytes: int = DRIVE_TEXT_MAX_BYTES_DEFAULT,
        download_max_bytes: int = DOWNLOAD_MAX_BYTES,
        on_revoked: Callable[[], None] | None = None,
    ) -> None:
        self._transport = transport
        self._roots = tuple(roots)
        self._text_max_bytes = text_max_bytes
        self._download_max_bytes = download_max_bytes
        self._on_revoked = on_revoked

    # ---- the three operations --------------------------------------------------------

    def list_children(self, folder_id: str, *, page_token: str | None = None) -> DriveListing:
        """The children of a folder inside the roots, one Drive page at a time."""
        checked = checked_outside_id(folder_id, field="folder_id")
        return self._guarded(lambda: self._list_children(checked, page_token))

    def is_within_roots(self, file_id: str) -> bool:
        """Whether a configured root is this file's ancestor -- or is this file.

        A folder the titolare named is inside the roots by definition, and answering
        that needs no call to Google at all. Everything else is `files.get` on the
        parents, level by level, with a cache for the duration of this one call: a file
        with several parents whose paths meet again is otherwise walked once per path.
        """
        # `folder_id`, because this is the one entry point that answers about a
        # *folder* as readily as about a file, and `list_children` is what calls it.
        checked = checked_outside_id(file_id, field="folder_id")
        return self._guarded(lambda: self._within_roots(checked, {}))

    def read_bytes(self, file_id: str, *, max_bytes: int | None = None) -> tuple[bytes, str]:
        """The bytes of one file and the mime they are in.

        A Google Doc has no bytes of its own, so what comes back is Drive's
        `text/plain` export and the mime says `text/plain` rather than repeating the
        native type -- the caller is being handed text, and telling it otherwise would
        make every extractor downstream guess.

        `max_bytes` can only *tighten* the reader's own ceiling (see `_ceiling`): it is
        a caller's budget, not a permission, and a tool that asked for 500 MB must not
        thereby raise a limit it does not decide.
        """
        checked = checked_outside_id(file_id, field="file_id")
        limit = self._ceiling(max_bytes)
        return self._guarded(lambda: self._read_bytes(checked, limit))

    def read_text(self, file_id: str, *, max_bytes: int | None = None) -> DriveText:
        """The text of one file, cut at `max_bytes` and stamped with its provenance.

        Two ceilings, not one: the bytes are fetched under the download ceiling (a 4 MB
        PDF is an ordinary contract) and the *text* is cut at `max_bytes`, which
        defaults to `settings.drive_text_max_bytes`. See `DOWNLOAD_MAX_BYTES`.
        """
        checked = checked_outside_id(file_id, field="file_id")
        limit = self._text_max_bytes if max_bytes is None else max_bytes

        def work() -> DriveText:
            content, mime = self._read_bytes(checked, self._ceiling(None))
            return drive_text(content, mime=mime, max_bytes=limit)

        return self._guarded(work)

    # ---- internals -------------------------------------------------------------------

    def _ceiling(self, max_bytes: int | None) -> int:
        """The smaller of the caller's budget and this reader's own ceiling.

        `min`, not "the caller's if given": a `max_bytes` above the ceiling would let
        whoever calls this decide how many bytes of somebody's Drive may be pulled into
        this process, which is the one thing the ceiling exists to take away from them.
        """
        if max_bytes is None:
            return self._download_max_bytes
        return min(max_bytes, self._download_max_bytes)

    def _guarded(self, work: Callable[[], _T]) -> _T:
        """Every public operation, with the one exception that has a *reaction* attached.

        `DriveCredentialRevoked` is not swallowed and not re-worded: the callback
        records the fact (and commits it, on its own transaction) and the exception
        continues, so the caller stops instead of carrying on against a dead
        credential. Wrapped here, once, rather than at the four call sites -- and the
        public methods call the private internals below precisely so that a nested
        operation cannot fire the callback twice for one failure.
        """
        try:
            return work()
        except DriveCredentialRevoked:
            if self._on_revoked is not None:
                self._on_revoked()
            raise

    def _list_children(self, folder_id: str, page_token: str | None) -> DriveListing:
        if not self._within_roots(folder_id, {}):
            # Before `files.list`, not after: a listing of a folder nobody configured
            # must never be *sent*, which is the whole point of this module.
            raise NotFound(ENTITY, folder_id)
        url = files_list_url(children_query(folder_id), page_token=page_token, fields=_LIST_FIELDS)
        payload = self._transport.json("GET", url, what=_WHAT_LIST)
        files = payload.get("files") or []
        token = payload.get("nextPageToken")
        return DriveListing(
            items=[_entry(item) for item in files if isinstance(item, dict)],
            next_page_token=str(token) if token else None,
        )

    def _read_bytes(self, file_id: str, max_bytes: int) -> tuple[bytes, str]:
        meta = self._metadata(file_id)
        # The metadata call already carries the file's parents, so seeding the walk's
        # cache with them spends no second `files.get` on the file itself.
        cache: dict[str, list[str]] = {file_id: _parents(meta)}
        if not self._within_roots(file_id, cache):
            raise NotFound(ENTITY, file_id)

        mime = str(meta.get("mimeType") or "")
        if mime == FOLDER_MIME:
            raise Conflict(ENTITY, _NOT_A_FOLDER, file_id=file_id, mime=mime)
        declared = _as_int(meta.get("size"))
        if declared is not None and declared > max_bytes:
            # Refused on what Drive says the size is, so a 900 MB video costs nothing
            # to turn down. The check is repeated on what arrives, below, because an
            # export has no declared size at all.
            raise Conflict(
                ENTITY, _TOO_BIG.format(max_bytes=max_bytes), file_id=file_id, size=declared
            )

        if mime == GOOGLE_DOC_MIME:
            content = self._transport.bytes(
                "GET", file_export_url(file_id, PLAIN_TEXT_MIME), what=_WHAT_EXPORT
            )
            mime = PLAIN_TEXT_MIME
        elif mime.startswith(_GOOGLE_NATIVE_PREFIX):
            raise Conflict(ENTITY, _NO_BYTES.format(mime=mime), file_id=file_id, mime=mime)
        else:
            content = self._transport.bytes("GET", file_media_url(file_id), what=_WHAT_DOWNLOAD)

        # Not a memory bound, and it would be dishonest to describe it as one: by the
        # time this runs, `DriveTransport` has already buffered the whole response in
        # memory (`urllib` reads it in one `response.read()`), so what this refuses is
        # *returning* an oversized answer, not allocating it. The bound that actually
        # limits allocation is the declared-size check above, and above that Google's
        # own per-file limits. Kept regardless: an export declares no size at all, so
        # without this a Google Doc of any length would come back whole.
        if len(content) > max_bytes:
            raise Conflict(
                ENTITY, _TOO_BIG.format(max_bytes=max_bytes), file_id=file_id, size=len(content)
            )
        return content, mime

    def _within_roots(self, file_id: str, cache: dict[str, list[str]]) -> bool:
        if file_id in self._roots:
            return True
        seen = {file_id}
        frontier = [file_id]
        spent = 0
        for _level in range(MAX_ROOT_WALK_LEVELS):
            above: list[str] = []
            for current in frontier:
                if spent >= MAX_ROOT_WALK_REQUESTS and current not in cache:
                    return False
                spent += 1
                for parent in self._parents_of(current, cache):
                    if parent in self._roots:
                        return True
                    if parent not in seen:
                        seen.add(parent)
                        above.append(parent)
            if not above:
                # The Drive's own root, or a file with no parents at all: there is
                # nothing above it, and no configured root was met on the way.
                return False
            frontier = above
        return False

    def _parents_of(self, file_id: str, cache: dict[str, list[str]]) -> list[str]:
        """The parents of one id, asked once per `is_within_roots` call.

        A 404 answers "no parents", not an error: the walk's question is only ever
        "does a configured root sit above this?", and an id that does not exist has no
        root above it. Turning it into a refusal here would also make the refusal
        *different* from the one an unconfigured folder gets, which is exactly the
        distinction this module withholds.

        Only a 404, deliberately, and it is a trade rather than a free choice: a 403
        ("you may not see this file") also means no root can be proven above it, and it
        propagates as a `Conflict` instead. That is the right answer for the caller --
        an outage or a permission change is worth reporting as itself, and swallowing
        it would make an unshared parent look like an unconfigured one -- but it does
        mean a 403 on a *parent* of a file the titolare can read surfaces as a Drive
        error rather than as `NotFound`. It has not been seen, and inventing a
        translation for it would be inventing which of the two it was.
        """
        cached = cache.get(file_id)
        if cached is not None:
            return cached
        try:
            payload = self._transport.json(
                "GET", file_meta_url(file_id, fields=_PARENT_FIELDS), what=_WHAT_META
            )
        except Conflict as refusal:
            if refusal.details.get("status") != 404:
                raise
            payload = {}
        parents = _parents(payload)
        cache[file_id] = parents
        return parents

    def _metadata(self, file_id: str) -> dict[str, Any]:
        try:
            return self._transport.json(
                "GET", file_meta_url(file_id, fields=_ENTRY_FIELDS), what=_WHAT_META
            )
        except Conflict as refusal:
            if refusal.details.get("status") == 404:
                # Same sentence as a file outside the roots: see the module docstring.
                raise NotFound(ENTITY, file_id) from refusal
            raise


def drive_reader_for(
    session: Session, actor: Actor, settings: Settings, *, feature: str
) -> DriveReader:
    """A reader on this actor's connected Drive account, or the refusal that says why not.

    The order is the point. The gate comes first (`usable`, which holds no transport and
    therefore *cannot* have called Google), so somebody whose grant is revoked, whose
    consent expired or who never granted `drive.readonly` learns it at the ask rather
    than from a failed Drive call. Only then is the refresh token unsealed, wrapped in
    `UserTokens` and handed to a `DriveTransport`; and the roots come from the row, so
    a reader cannot be pointed at a folder the titolare did not configure.

    `feature` is the name the refusal uses ("la lettura dei documenti da Drive"), so a
    missing scope reads as a feature that is off rather than as a broken credential.

    `on_revoked` closes the last gap: a revocation can only be *learned* by a refresh
    that answers `invalid_grant`, which happens deep inside a read. `mark_revoked`
    commits on its own behalf, so the fact outlives the rollback of whatever operation
    discovered it, and then the exception continues.

    The `GoogleTokenClient` is built here and lives as long as the reader. Unlike
    `routers/gmail.py`'s per-process cache, that means one token exchange per reader
    rather than one per hour per process -- the price of `packages/core` not owning a
    process-wide cache, and the same choice `apps/mcp`'s privileged tools already make.
    """
    accounts = GoogleDriveAccountService(session, settings=settings)
    account = accounts.usable(actor, scope=DRIVE_SCOPE_READONLY, feature=feature)
    refresh_token = unseal(
        account.refresh_token_ciphertext,
        account.refresh_token_nonce,
        decode_google_token_key(settings),
    )
    tokens = UserTokens(
        account_id=account.id,
        email_address=account.email_address,
        refresh_token=refresh_token,
        tokens=GoogleTokenClient(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            transport=GmailTransport(),
        ),
    )

    def on_revoked() -> None:
        accounts.mark_revoked(
            account,
            # Google revoked this, nobody in this CRM did.
            Actor.system(),
            # The sentence a person reads, written here: no upstream prose, no error
            # code, no token.
            _REVOKED_REASON.format(email=account.email_address),
        )

    return DriveReader(
        DriveTransport(tokens=tokens),
        roots=account.root_folder_ids,
        text_max_bytes=settings.drive_text_max_bytes,
        on_revoked=on_revoked,
    )


def _entry(item: dict[str, Any]) -> DriveEntry:
    mime = str(item.get("mimeType") or "")
    return DriveEntry(
        id=str(item.get("id") or ""),
        nome=str(item.get("name") or ""),
        mime=mime,
        dimensione=_as_int(item.get("size")),
        modificato_il=_moment(item.get("modifiedTime")),
        cartella=mime == FOLDER_MIME,
    )


def _parents(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("parents") or []
    return [str(parent) for parent in raw if isinstance(parent, str)]


def _as_int(value: Any) -> int | None:
    """Drive reports `size` as a *string*, and omits it entirely for anything without
    bytes. Anything unparseable is `None` for the reason `gmail/parse.py` gives: a
    strange answer from Google is not worth failing a whole read over."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _moment(value: Any) -> datetime | None:
    """Drive's RFC 3339 timestamp, always UTC-aware.

    `fromisoformat` reads the trailing `Z` from Python 3.11 on. A naive result cannot
    happen with Drive's own format, but is stamped UTC rather than returned naive: a
    naive datetime compared against an aware one raises, and a listing is not the place
    to discover that.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
