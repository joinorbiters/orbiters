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
# The custom property every file this class writes carries, holding the full storage
# key. This -- not the folder it happens to sit in -- is what `get`/`delete` search
# for; see the module docstring.
APP_PROPERTY_KEY = "pigrocrm_key"
TOKEN_LIFETIME_SECONDS = 3600
# Refresh a minute early rather than discovering expiry mid-upload.
TOKEN_REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 30
_MULTIPART_BOUNDARY = "pigrocrm-boundary-7f3c1a"

# (method, url, headers, body) -> (status, body). Injected in tests; the default is
# `_urllib_call` below. Nothing above this seam knows what a socket is.
HttpCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]
SignAssertion = Callable[[dict[str, Any]], str]


def _urllib_call(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


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
    ) -> None:
        self._credentials: dict[str, Any] = json.loads(service_account_json)
        self._root_folder_id = root_folder_id
        self._http: HttpCall = http or _urllib_call
        # Injectable so tests can prove the rest of this class -- URL building, query
        # escaping, multipart framing, error handling -- without a real RSA key ever
        # existing in this repository.
        self._sign: SignAssertion = sign_assertion or self._sign_with_private_key
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ---- transport ------------------------------------------------------------

    def _sign_with_private_key(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._credentials["private_key"], algorithm="RS256")

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
        status, payload = self._http(
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
        status, payload = self._http(method, url, headers, body)
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

    def _find_file_by_key(self, key: str) -> str | None:
        """The id of the file holding `key`'s bytes, found by its `appProperties` --
        never by walking the folder tree (see the module docstring for why that would
        be ambiguous).

        Not scoped to any folder: the query runs across every Shared Drive this
        service account can see, which is safe because a PigroCRM deployment
        provisions one service account per instance and every file it writes carries
        this property. Returns the lowest id when more than one file matches, the
        same convergence rule `_find_folder` uses for the identical create-race on
        folders -- Drive offers no atomic create-if-absent, so two concurrent
        `put()`s for a key that does not yet exist can each create one.
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
        return str(min((f["id"] for f in files), key=str)) if files else None

    # ---- DocumentStorage --------------------------------------------------------

    def put(self, key: str, data: bytes, content_type: str) -> None:
        validated = validate_storage_key(key)
        existing = self._find_file_by_key(validated)
        if existing is not None:
            # Media-only update: the file already lives in the right folder under the
            # right name, only its bytes change.
            self._api(
                "PATCH",
                self._url(f"{DRIVE_UPLOAD_URL}/{existing}", uploadType="media"),
                body=data,
                content_type=content_type,
            )
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
        status, payload = self._http(
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
        validated = validate_storage_key(key)
        file_id = self._find_file_by_key(validated)
        if file_id is None:
            return  # idempotent, like LocalFileStorage.delete
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
        status, payload = self._http("GET", url, headers, None)
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
