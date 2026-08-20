"""Google Drive through a service account, over the stdlib.

No Google client library: `urllib.request` and `json` are enough for the handful of
endpoints this needs, and adding `google-api-python-client` to `packages/core` would
drag a large transitive tree into the one package the architecture test keeps
deliberately small.

**Operational requirement, not a detail:** a service account has no Drive storage
quota of its own. `PIGROCRM_GDRIVE_ROOT_FOLDER_ID` must name a folder on a *Shared
Drive*, or a folder explicitly shared with the service account's address, or
`files.create` fails with `storageQuotaExceeded`. Every call below carries
`supportsAllDrives=true` for that reason, and `verify_root_accessible` (called once by
`storage_from_settings`, not by anything in this class automatically) turns a
misconfigured root into a startup failure instead of a first-upload one.

**Placement vs. identity.** The key is a path, and `a/b/c.pdf` is filed under nested
folders `a` then `b` beneath the configured root, with a file `c.pdf` inside -- one
folder per customer, matching how the system this replaces already organised things,
so a person migrating finds their documents where they expect (spec 5).

But Drive does not enforce name-uniqueness among siblings: two concurrent uploads for
a brand-new customer can each fail to see the other's just-created folder and each
create one of the same name under the same parent. From that point on the *tree* is
ambiguous -- a lookup that walks it by name can land on either folder, including one
that does not contain the file being looked for. So the tree is for placement and
human navigation only, never for identity: every file this class writes carries the
full storage key in its `appProperties`, and `get`/`delete` locate it with a
property-filtered query that does not care which folder it ended up in. `_ensure_folder`
still has to cope with the same raciness for *placement* (two `put()`s for a new
customer's first document must not scatter their files across two duplicate folders
forever) by re-querying after a create and adopting one candidate deterministically.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import jwt

from pigrocrm.core.errors import Conflict, NotFound
from pigrocrm.core.storage.base import validate_storage_key

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"
# Not "drive.file". That narrower scope only grants visibility into files the app
# itself created or that a user opened through an interactive picker -- neither of
# which happens for decision 4's second sanctioned setup, "a folder explicitly shared
# with [the service account]" by an admin who created it beforehand. A service
# account cannot drive a picker, so under `drive.file` that folder would simply not
# exist as far as this class could see, and every call would 404. The broad `drive`
# scope is what a service account managing a pre-existing, admin-shared root actually
# needs.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
# Operator note, not a code fix: this scope is bearer-broad -- wider than a single
# Shared-Drive deployment strictly needs, since a leaked access token would grant
# access to every Shared Drive and folder this service account can see, not only
# PigroCRM's own root. Keep the blast radius small at the Google Cloud console
# instead: share only PIGROCRM_GDRIVE_ROOT_FOLDER_ID (and nothing else) with this
# service account's address, and never reuse the same service account for any other
# integration.
# The custom property every file this class writes carries, holding the full storage
# key. This -- not the folder it happens to sit in -- is what `get`/`delete` search
# for; see the module docstring.
APP_PROPERTY_KEY = "pigrocrm_key"
TOKEN_LIFETIME_SECONDS = 3600
# Refresh a minute early rather than discovering expiry mid-upload.
TOKEN_REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 30
_MULTIPART_BOUNDARY = "pigrocrm-boundary-7f3c1a"

# A synthetic status for "no HTTP response was ever received" (DNS failure,
# connection refused, a timeout) -- the "network connect timeout" code some proxies
# use for exactly this shape, chosen so `_call`'s retry logic and `_decode`'s error
# reporting can treat it exactly like any server-issued status, rather than needing a
# second failure channel only `_urllib_call` knows about.
NETWORK_ERROR_STATUS = 599
# 429 (rate limited) and 5xx (transient server-side failure) are worth retrying;
# anything else -- a 4xx other than 429 in particular -- is a client error that will
# not go away on its own, so retrying it only delays reporting a failure.
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, NETWORK_ERROR_STATUS})
# First attempt plus up to three retries. Exponential: 0.5s, 1s, 2s between them.
_MAX_HTTP_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 0.5


def _retry_delay_seconds(attempt: int) -> float:
    # `1 << attempt`, not `2**attempt`: typeshed types `int.__pow__` as returning
    # `Any` (to accommodate a negative exponent producing a float), which would make
    # this whole expression -- and this function's return value -- `Any` under mypy
    # strict mode. A left shift has no such escape hatch and stays a plain `int`.
    return _RETRY_BASE_DELAY_SECONDS * (1 << attempt)


# (method, url, headers, body) -> (status, body). Injected in tests; the default is
# `_urllib_call` below. Nothing above this seam knows what a socket is.
#
# Deliberately does not carry response headers: Google's real `Retry-After` header on
# a 429 cannot be read through this seam, so `_call`'s backoff below is a fixed
# exponential schedule, not one driven by the server's own hint. Widening this type to
# `tuple[int, bytes, dict[str, str]]` would fix that properly, but it is an interface
# every test and the fake transport already depend on; changing it is out of scope for
# a fix that has to land without breaking the contract the rest of this module was
# reviewed against.
HttpCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]
SignAssertion = Callable[[dict[str, Any]], str]
SleepFn = Callable[[float], None]


def _urllib_call(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        # No HTTP response was ever received, so there is no real status code to
        # report -- `URLError` wraps DNS failure and connection-refused, and a bare
        # `OSError`/`TimeoutError` covers the rest. `str(exc)` names the failure
        # reason (and possibly the target host, always a googleapis.com address, never
        # sensitive) but never the request's headers or body, so no bearer token or
        # key material can reach it.
        return NETWORK_ERROR_STATUS, json.dumps({"error": {"message": str(exc)}}).encode()


def _escape_drive_query(value: str) -> str:
    """Escapes `\\` and `'` for a Drive `q` filter, backslash first.

    Backslash first is load-bearing for the same reason it is in the template
    escapers: escaping the quote first would then have its own backslash escaped by
    the second pass, leaving a trailing backslash able to swallow the filter's closing
    quote.

    Every value this module puts through the filter -- folder names and the
    `appProperties` key value -- is currently a segment of a `validate_storage_key`-
    validated key, whose character class (`[a-z0-9._-]`) cannot contain either
    character, so this function is unreachable through any call this class makes
    today. Kept anyway, for the same reason `base.py` keeps its own already-redundant
    checks: a future widening of that character class must not silently reopen query
    injection just because nothing currently exercises the escaping.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GDriveStorage:
    def __init__(
        self,
        *,
        service_account_json: str,
        root_folder_id: str,
        http: HttpCall | None = None,
        sign_assertion: SignAssertion | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._credentials: dict[str, Any] = json.loads(service_account_json)
        self._root_folder_id = root_folder_id
        self._http: HttpCall = http or _urllib_call
        # Injectable so tests can prove the rest of this class -- URL building, query
        # escaping, multipart framing, error handling -- without a real RSA key ever
        # existing in this repository.
        self._sign: SignAssertion = sign_assertion or self._sign_with_private_key
        # Injectable so retry-with-backoff tests don't actually block for seconds at a
        # time; production gets real `time.sleep`.
        self._sleep: SleepFn = sleep or time.sleep
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ---- transport ------------------------------------------------------------

    def _sign_with_private_key(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._credentials["private_key"], algorithm="RS256")

    def _call(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        """Every HTTP call this class makes goes through here, not through `self._http`
        directly, so retry-with-backoff applies uniformly instead of being
        reimplemented -- or forgotten -- at each call site.

        Retries a `429` or a transient `5xx` (`_RETRYABLE_STATUSES`) with exponential
        backoff, up to `_MAX_HTTP_ATTEMPTS` attempts total, then returns whatever the
        last attempt got so the caller's own error handling (`_decode`) reports it.
        Anything else -- including a network failure normalised to
        `NETWORK_ERROR_STATUS` by `_urllib_call` -- is retried the same way, since it is
        just as transient; anything *not* in that set is returned immediately.
        """
        status, payload = self._http(method, url, headers, body)
        for attempt in range(_MAX_HTTP_ATTEMPTS - 1):
            if status not in _RETRYABLE_STATUSES:
                break
            self._sleep(_retry_delay_seconds(attempt))
            status, payload = self._http(method, url, headers, body)
        return status, payload

    def _access_token(self) -> str:
        if self._token is not None and time.time() < self._token_expires_at:
            return self._token
        issued = int(time.time())
        assertion = self._sign(
            {
                "iss": self._credentials["client_email"],
                "scope": DRIVE_SCOPE,
                "aud": self._credentials.get("token_uri", GOOGLE_TOKEN_URL),
                "iat": issued,
                "exp": issued + TOKEN_LIFETIME_SECONDS,
            }
        )
        body = urlencode(
            {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        ).encode()
        status, payload = self._call(
            "POST",
            self._credentials.get("token_uri", GOOGLE_TOKEN_URL),
            {"Content-Type": "application/x-www-form-urlencoded"},
            body,
        )
        parsed = self._decode(status, payload, "autenticazione Google")
        self._token = str(parsed["access_token"])
        self._token_expires_at = time.time() + TOKEN_LIFETIME_SECONDS - TOKEN_REFRESH_MARGIN_SECONDS
        return self._token

    def _decode(self, status: int, payload: bytes, what: str) -> dict[str, Any]:
        if status >= 400:
            # Google's own message is included but the raw body is not: it can carry
            # the folder tree and the service-account address, neither of which
            # belongs in a problem document a browser will render. Never the request
            # headers or body either, so no bearer token or key material can reach an
            # exception message from here.
            detail = ""
            try:
                detail = str(json.loads(payload.decode()).get("error", {}).get("message", ""))
            except (ValueError, AttributeError):
                detail = ""
            raise Conflict(
                "document_blob",
                f"{what} fallita ({status}){': ' + detail if detail else ''}",
                status=status,
            )
        return json.loads(payload.decode()) if payload else {}

    def _api(
        self, method: str, url: str, *, body: bytes | None = None, content_type: str | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        status, payload = self._call(method, url, headers, body)
        return self._decode(status, payload, "richiesta a Google Drive")

    @staticmethod
    def _url(base: str, **params: str) -> str:
        return f"{base}?{urlencode({'supportsAllDrives': 'true', **params})}"

    # ---- folders: placement and human navigation only, never identity ---------

    def _find_folder(self, parent_id: str, name: str) -> str | None:
        """The id of a folder named `name` directly under `parent_id`, or `None`.

        Returns the *lowest* id when more than one matches -- the deterministic
        convergence rule `_ensure_folder` needs for the race it documents -- rather
        than an arbitrary "first" result Drive's own ordering happens to return.
        """
        clauses = [
            "trashed=false",
            f"name='{_escape_drive_query(name)}'",
            f"'{parent_id}' in parents",
            f"mimeType='{FOLDER_MIME}'",
        ]
        url = self._url(
            DRIVE_FILES_URL,
            q=" and ".join(clauses),
            fields="files(id)",
            includeItemsFromAllDrives="true",
        )
        files = self._api("GET", url).get("files") or []
        return str(min((f["id"] for f in files), key=str)) if files else None

    def _ensure_folder(self, parent_id: str, name: str) -> str:
        """Finds-or-creates, race-tolerant.

        Two concurrent uploads for a customer's *first* document can both miss the
        folder in `_find_folder` (neither has created it yet) and both call
        `files.create`: Drive does not enforce unique names among siblings, so this
        legitimately produces two folders named alike under the same parent.
        Re-querying after the create -- rather than trusting the id `files.create`
        just handed back -- lets every racing caller see the same full candidate set
        and adopt the same one (lowest id), so a second `put()` for that customer
        files into the folder the first one converged on, not into a third one.
        """
        existing = self._find_folder(parent_id, name)
        if existing:
            return existing
        self._api(
            "POST",
            self._url(DRIVE_FILES_URL, fields="id"),
            body=json.dumps(
                {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
            ).encode(),
            content_type="application/json",
        )
        converged = self._find_folder(parent_id, name)
        assert converged is not None  # our own create just landed, if nothing else
        return converged

    def _ensure_folder_chain(self, segments: list[str]) -> str:
        parent = self._root_folder_id
        for name in segments:
            parent = self._ensure_folder(parent, name)
        return parent

    # ---- files: identity lives in appProperties, never in the folder path -----

    def _find_all_file_ids_by_key(self, key: str) -> list[str]:
        """Every file currently carrying `key` in its `appProperties`, found without
        walking the folder tree (see the module docstring for why a name-based walk
        would be ambiguous), sorted low-to-high id.

        Not scoped to any folder: the query runs across every Shared Drive this
        service account can see, which is safe because a PigroCRM deployment
        provisions one service account per instance and every file it writes carries
        this property.

        Normally returns at most one id. More than one means a create-race: Drive
        offers no atomic create-if-absent, so two concurrent `put()`s for a key that
        does not yet exist can each miss the other and each create a file. `put`
        converges on the lowest id and reaps the rest (see `put`'s own docstring for
        why); `delete` cannot make the same simplification -- it must remove every id
        this returns, or a document the caller was told was deleted could still be
        read back through the survivor (see `delete`'s docstring).
        """
        escaped_key = _escape_drive_query(key)
        clauses = [
            "trashed=false",
            f"appProperties has {{ key='{APP_PROPERTY_KEY}' and value='{escaped_key}' }}",
        ]
        url = self._url(
            DRIVE_FILES_URL,
            q=" and ".join(clauses),
            fields="files(id)",
            includeItemsFromAllDrives="true",
            corpora="allDrives",
        )
        files = self._api("GET", url).get("files") or []
        return sorted((str(f["id"]) for f in files), key=str)

    def _find_file_by_key(self, key: str) -> str | None:
        """The single, canonical id for `key` -- the lowest, when more than one file
        matches (see `_find_all_file_ids_by_key`). Used by `get`, for which reading
        any one coherent, converged-upon file is correct; `delete` uses
        `_find_all_file_ids_by_key` directly instead, because leaving a second one
        behind is exactly the bug this class was fixed to not have.
        """
        ids = self._find_all_file_ids_by_key(key)
        return ids[0] if ids else None

    # ---- DocumentStorage --------------------------------------------------------

    def put(self, key: str, data: bytes, content_type: str) -> None:
        validated = validate_storage_key(key)
        existing_ids = self._find_all_file_ids_by_key(validated)
        if existing_ids:
            # Media-only update: the file already lives in the right folder under the
            # right name, only its bytes change. When a create-race (module
            # docstring) has left more than one file carrying this key, the lowest id
            # is the canonical one -- the same one `get` would already be reading --
            # and every other id is a duplicate nothing should still be pointing at.
            # Deleting them here, on the next write, heals the exact situation that
            # created the bug `delete` was fixed for: it is what stops "leftover
            # storage" from also becoming "delete doesn't delete" the moment a caller
            # writes to the key again. `delete` does not depend on `put` ever having
            # run, though -- it removes every matching id itself, so a key that is
            # only ever read after a race is still deleted correctly.
            canonical, *duplicates = existing_ids
            self._api(
                "PATCH",
                self._url(f"{DRIVE_UPLOAD_URL}/{canonical}", uploadType="media"),
                body=data,
                content_type=content_type,
            )
            for duplicate_id in duplicates:
                self._api("DELETE", self._url(f"{DRIVE_FILES_URL}/{duplicate_id}"))
            return
        *folders, filename = validated.split("/")
        parent = self._ensure_folder_chain(folders)
        metadata = json.dumps(
            {"name": filename, "parents": [parent], "appProperties": {APP_PROPERTY_KEY: validated}}
        ).encode()
        body = b"".join(
            [
                f"--{_MULTIPART_BOUNDARY}\r\n".encode(),
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
                metadata,
                f"\r\n--{_MULTIPART_BOUNDARY}\r\n".encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                data,
                f"\r\n--{_MULTIPART_BOUNDARY}--\r\n".encode(),
            ]
        )
        self._api(
            "POST",
            self._url(DRIVE_UPLOAD_URL, uploadType="multipart", fields="id"),
            body=body,
            content_type=f"multipart/related; boundary={_MULTIPART_BOUNDARY}",
        )

    def get(self, key: str) -> bytes:
        validated = validate_storage_key(key)
        file_id = self._find_file_by_key(validated)
        if file_id is None:
            raise NotFound("document_blob", key)
        url = self._url(f"{DRIVE_FILES_URL}/{file_id}", alt="media")
        status, payload = self._call(
            "GET", url, {"Authorization": f"Bearer {self._access_token()}"}, None
        )
        if status == 404:
            # Found a moment ago by `_find_file_by_key`, gone now: a concurrent
            # delete, not a bug in the query. Either way, "no such document" is the
            # honest answer to give this caller.
            raise NotFound("document_blob", key)
        if status >= 400:
            self._decode(status, payload, "download da Google Drive")
        return payload

    def delete(self, key: str) -> None:
        """Removes every file carrying `key`, not only the one a lookup would
        currently resolve to.

        A create-race (module docstring) can leave two files sharing the same
        `appProperties` value after concurrent first-writers, and `put` only reaps
        the extras when a write happens to land on the key afterwards. Deleting just
        the canonical one and leaving a duplicate behind would mean the *next* `get`
        resolves to that duplicate and returns content the caller was told was gone
        -- a document a customer asked to have erased coming back is a correctness
        failure, not a storage-hygiene one, so this removes all of them. Reproduced
        directly against a planted duplicate, not only reasoned about -- see
        test_storage_conformance.py's
        `test_delete_removes_every_file_left_by_a_create_race`.
        """
        validated = validate_storage_key(key)
        for file_id in self._find_all_file_ids_by_key(validated):
            self._api("DELETE", self._url(f"{DRIVE_FILES_URL}/{file_id}"))

    def signed_url(self, key: str, ttl: timedelta) -> str | None:
        """Always `None`, exactly like `LocalFileStorage`.

        Drive can mint a shareable link on demand, and that is precisely why this
        method must not: such a link is a bearer credential on a clock Google
        controls, not PigroCRM's, and it keeps granting access after the document is
        archived, the customer is deleted, or a user is offboarded -- entirely outside
        this system's own permission checks and audit trail. Routing every download
        through the API instead means there is exactly one place authorisation is
        decided, on both backends, and exactly one place it shows up in the audit
        log. "Drive could mint a link" is true and is not a reason to let it; anyone
        tempted to add one back should re-read this paragraph first, the same way
        `config.py` asks for `cookie_secure`.
        """
        validate_storage_key(key)
        return None

    def verify_root_accessible(self) -> None:
        """Confirms the configured root folder exists, this service account can see
        it, and it lives on a Shared Drive -- so a misconfiguration surfaces once, at
        startup, with a message that says what to fix, instead of showing up later as
        a bare 404 or a `storageQuotaExceeded` on some customer's first upload.

        Not called by anything else in this class: `storage_from_settings` calls it
        once, right after constructing a `GDriveStorage`, which is what makes this a
        startup check rather than a per-request one. A script or a test that only
        needs the type is free to skip the network round trip entirely.
        """
        url = self._url(
            f"{DRIVE_FILES_URL}/{self._root_folder_id}",
            fields="id,driveId",
            includeItemsFromAllDrives="true",
        )
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        status, payload = self._call("GET", url, headers, None)
        if status >= 400:
            raise RuntimeError(
                "PIGROCRM_GDRIVE_ROOT_FOLDER_ID non e' raggiungibile dal service "
                f"account (HTTP {status}). Verificare che la cartella esista e sia "
                "stata condivisa con l'indirizzo email del service account, "
                "direttamente o tramite uno Shared Drive."
            )
        parsed = json.loads(payload.decode()) if payload else {}
        if "driveId" not in parsed:
            raise RuntimeError(
                "PIGROCRM_GDRIVE_ROOT_FOLDER_ID non si trova su uno Shared Drive: un "
                "service account non ha una propria quota di storage su Google Drive, "
                "quindi ogni upload fallirebbe con storageQuotaExceeded. Spostare la "
                "cartella su uno Shared Drive (o su una sua sottocartella)."
            )
