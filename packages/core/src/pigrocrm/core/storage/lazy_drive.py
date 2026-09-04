"""Drive as a `DocumentStorage`, on the titolare's own credential, resolved late.

**Why late.** The service-account backend is fully described by two environment
variables, so `storage_from_settings` can build it, verify its root folder, and fail at
startup if either is wrong. This one is described by a *row*: the connected Google
account and the folder its owner chose in Impostazioni → Drive. That row does not exist
on a fresh installation, and the API has to start anyway -- otherwise the only screen
that could create it is unreachable, and `PIGROCRM_STORAGE_BACKEND=gdrive` becomes a
setting nobody can ever finish configuring. So construction reads nothing at all, and
the first `put`/`get`/`delete` is where the answer is either found or refused with
`StorageNotConfigured`.

**Why it re-reads the row.** The folder is a settings field a person edits while the
process is running. A storage that resolved once and cached forever would keep writing
into the folder that was configured at the time of the first upload -- after the
titolare moved it, after they disconnected Drive, after Google revoked the grant -- with
nothing on any screen to say why the documents are not where they should be. So every
operation reads the row (one indexed statement on a single-tenant table) and rebuilds
the transport only when `updated_at` says the row changed. That distinction is what
keeps the `GoogleTokenClient`'s access-token cache alive across uploads: rebuilding it
per call would turn one upload into one OAuth round-trip per Drive request.

**What it does not do.** No placement, no keys, no HTTP: it holds a `GDriveStorage` and
delegates. The only behaviour of its own is resolution, and reacting to the one failure
that invalidates it -- a revoked grant, recorded on the row so the shell banner can say
so, then re-raised unchanged.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.drive.account import GoogleDriveAccountService
from pigrocrm.core.drive.errors import DriveCredentialRevoked
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.repository import DriveRepository
from pigrocrm.core.drive.transport import HttpCall, user_transport_for
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.storage.errors import StorageNotConfigured
from pigrocrm.core.storage.gdrive import GDriveStorage

# A callable that opens a `Session` the storage then owns and closes -- in production
# the `sessionmaker` the adapter already builds. Not a `Session`: this object outlives
# any single request (it is built once per process, like the storage it replaces),
# while a session must not.
SessionFactory = Callable[[], Session]

_T = TypeVar("_T")

# What the user reads on the settings page after Google drops the grant. Written here,
# at the call site, rather than derived from the exception -- the same rule
# `gmail/sync.py` follows when it records a revoked mailbox: no error code, no upstream
# prose, no token, and a sentence that says what to do.
_REVOKED_REASON = (
    "Il consenso Google Drive per {email} è stato revocato: la scrittura dei documenti "
    "è sospesa finché non ricolleghi Drive da Impostazioni → Drive."
)


@dataclass(frozen=True)
class _Resolution:
    """One answer to "which account, which folder", and the stamp that dates it.

    `updated_at` is the whole reason this is a class and not just the storage: it is
    compared against the row on every operation, and a difference means the person
    changed something and the transport has to be rebuilt.
    """

    account_id: UUID
    email_address: str
    updated_at: datetime
    storage: GDriveStorage


class LazyUserDriveStorage:
    """A `DocumentStorage` that finds its Drive account at the first operation.

    `session_factory` rather than a `Session`, and `settings` rather than pre-built
    credentials, because this object is constructed once per process while both the
    session and the credential are things it has to obtain again later.

    **Not thread-safe yet, and that is a note for whoever wires it up.** `_resolution`
    is read and written with no lock. Nothing here corrupts -- the field is replaced
    wholesale by a single assignment, never mutated in place, so a concurrent reader
    sees either the old resolution or the new one and both are coherent -- but two
    threads meeting a cold or newly-invalidated cache will each resolve and each build a
    transport, so one of the two `GoogleTokenClient`s is thrown away along with its
    cached access token, and a revocation can be recorded twice. The instance that
    reaches production is process-scoped and shared across requests (FastAPI runs sync
    endpoints in a thread pool), so the task that wires it into `deps.py` should guard
    the resolution with a lock -- the same shape, and the same reason, as `deps.py`'s
    own `_engine_lock`. Deliberately not added here: a lock in this class with no
    concurrent caller yet would be untested code protecting a scenario this task cannot
    reach.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        settings: Settings,
        *,
        http: HttpCall | None = None,
        tokens: GoogleTokenClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        # Both are seams for the tests, and both are the ones `user_transport_for`
        # already declares: `http` is the Drive network, `tokens` is Google's token
        # endpoint. Two, not one, because they are two different hosts behind two
        # different fakes -- and because a single fake for both would let a composition
        # that used the wrong credential still pass.
        self._http = http
        self._tokens = tokens
        self._resolution: _Resolution | None = None

    # ---- resolution -------------------------------------------------------------

    def _resolve(self) -> _Resolution:
        """The account that may be written into, right now.

        Raises `StorageNotConfigured` when there is none -- which is the same answer for
        "Drive was never connected", "no folder was chosen yet", "the person
        disconnected it" and "the grant was revoked": all four are fixed on the same
        screen, and telling them apart here would only invite four sentences that
        describe the same next action.
        """
        with self._session_factory() as session:
            account = DriveRepository(session).storage_account()
            if account is None or account.storage_folder_id is None:
                # Dropped, not kept: a stale resolution would otherwise keep writing
                # into a folder the row no longer names if the account came back.
                self._resolution = None
                raise StorageNotConfigured()
            current = self._resolution
            if current is not None and (
                current.account_id == account.id and current.updated_at == account.updated_at
            ):
                return current
            resolved = _Resolution(
                account_id=account.id,
                email_address=account.email_address,
                updated_at=account.updated_at,
                storage=GDriveStorage(
                    transport=user_transport_for(
                        account, self._settings, http=self._http, tokens=self._tokens
                    ),
                    root_folder_id=account.storage_folder_id,
                ),
            )
        # Outside the `with`: the session is closed and the account row is detached,
        # and nothing above this line reads it again. Assigned after the block for the
        # same reason -- a failure while composing must not leave a half-built
        # resolution cached.
        self._resolution = resolved
        return resolved

    def _record_revocation(self) -> None:
        """Marks the row revoked, in its own session, and forgets the resolution.

        Its own session because `mark_revoked` commits: the operation that discovered
        this is about to raise and its caller's transaction will be rolled back, so the
        fact has to be written on its own behalf or it does not survive the request
        that learned it. Same contract, same reason, as `GmailSyncService._access_token`.

        The row may already be gone (a user deleted between the failed refresh and
        here), in which case there is nothing to record and the revocation still
        propagates: the caller's failure does not depend on the bookkeeping succeeding.

        **And that sentence is enforced, not merely intended.** Everything about this
        second session can fail on its own account -- a pool with no connection left,
        a row somebody else is holding, a `commit` that loses a race -- and every one of
        those failures would, unguarded, escape from inside `except
        DriveCredentialRevoked` and *replace* the revocation. The caller would then read
        a database error instead of "il consenso è stato revocato" (a 500 where a 409
        belongs), and the row would be left `active` regardless, so the reader would
        lose both the sentence and the record. So the whole body is guarded and nothing
        is re-raised: the original refusal always wins.

        Swallowing is the right trade here and not merely the convenient one. The state
        this failed to write is re-derivable -- the next refresh meets the same
        `invalid_grant` and tries again, which is exactly the retry a momentarily
        unavailable database needs -- while the exception it would have replaced is not
        re-derivable at all, because it is what the caller is being told.
        """
        resolution = self._resolution
        self._resolution = None
        if resolution is None:
            return
        try:
            session = self._session_factory()
            try:
                account = session.get(GoogleDriveAccount, resolution.account_id)
                if account is not None:
                    GoogleDriveAccountService(session, settings=self._settings).mark_revoked(
                        account,
                        # Google revoked this, nobody in this CRM did -- the actor every
                        # `mark_revoked` call site passes.
                        Actor.system(),
                        _REVOKED_REASON.format(email=account.email_address),
                    )
            except Exception:
                # A half-applied `mark_revoked` (status set, activity not yet recorded,
                # commit not reached) must not be left pending on a session something
                # later could flush, and a pooled connection must go back clean rather
                # than mid-transaction. `close()` below would roll back anyway; saying
                # so here is what makes it a decision instead of a side effect.
                session.rollback()
                raise
            finally:
                session.close()
        except Exception:
            # Deliberately swallowed -- see the docstring. The outer `try` wraps the
            # factory call, the rollback and the close as well as the write, because a
            # guard that only covered the write would still let a failing `rollback()`
            # or a failing `close()` escape and do the exact harm this exists to
            # prevent.
            #
            # `Exception` and not a list of SQLAlchemy classes: the point is that
            # *nothing* raised in here may reach the caller in place of the revocation,
            # and a list is a list somebody has to keep complete. `BaseException` still
            # passes, so a `KeyboardInterrupt` or a task cancellation is not absorbed by
            # bookkeeping.
            pass

    def _run(self, operation: Callable[[GDriveStorage], _T]) -> _T:
        """Resolve, delegate, and turn a revoked grant into a recorded fact.

        One place, four methods: a revocation can surface from any Drive call (the token
        refresh happens inside each of them), so a per-method `try` would be four
        chances to forget one. The exception is re-raised as the very class
        `UserTokens` raised, not flattened -- a caller that reacts to a revocation has
        to be able to match on it, which is why `drive/errors.py` made it a type.
        """
        storage = self._resolve().storage
        try:
            return operation(storage)
        except DriveCredentialRevoked:
            self._record_revocation()
            raise

    # ---- DocumentStorage --------------------------------------------------------

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._run(lambda storage: storage.put(key, data, content_type))

    def get(self, key: str) -> bytes:
        return self._run(lambda storage: storage.get(key))

    def delete(self, key: str) -> None:
        self._run(lambda storage: storage.delete(key))

    def signed_url(self, key: str, ttl: timedelta) -> str | None:
        """`None`, like both other backends -- but only after resolving.

        `GDriveStorage.signed_url` never calls Drive, so this is the one method that
        could have skipped resolution. It does not: `None` from a backend that is not
        configured is indistinguishable from `None` from one that is, so a caller
        checking whether a direct link exists would learn nothing and the
        misconfiguration would surface somewhere else entirely.
        """
        return self._run(lambda storage: storage.signed_url(key, ttl))
