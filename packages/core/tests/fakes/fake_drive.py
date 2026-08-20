"""An in-memory Google Drive that speaks the same HTTP surface `GDriveStorage` uses.

Deliberately a fake of the *transport*, not of `GDriveStorage` itself: the URL
building, the query escaping, the multipart body, the `appProperties` filter and the
error handling are exactly the parts most likely to be wrong, so they must run for
real. What it replaces is the network, nothing above it.

Implements: files.get (single file/folder metadata, used by `verify_root_accessible`),
files.list with a `q` filter (name+parent for folders, `appProperties has {...}` for
files), files.create for a folder, multipart create and media-only update for a file,
media download, and delete -- all with `supportsAllDrives=true`, because a service
account's files live on a Shared Drive.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass
class _File:
    id: str
    name: str
    parent: str
    mime: str
    data: bytes = b""
    app_properties: dict[str, str] = field(default_factory=dict)


@dataclass
class FakeDrive:
    root_id: str = "ROOT"
    # Whether `files.get` on `root_id` itself reports a `driveId` -- i.e. whether the
    # configured root behaves as if it were on a Shared Drive. Set to False to
    # exercise `verify_root_accessible`'s second failure mode.
    root_on_shared_drive: bool = True
    files: dict[str, _File] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    next_id: int = 1
    token_requests: int = 0
    # A queue of statuses to return, consumed one per call (FIFO), before falling
    # through to the real handling below. A single-shot failure is `fail_with = [403]`;
    # `fail_with = [429, 429]` simulates two transient failures followed by a normal
    # response, for testing retry-then-succeed. Every call while this is non-empty is
    # intercepted -- including the OAuth token request -- since a real transient
    # failure does not know or care which endpoint it happens to hit.
    fail_with: list[int] = field(default_factory=list)

    def _new_id(self) -> str:
        self.next_id += 1
        return f"id{self.next_id}"

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        self.calls.append((method, url))
        if self.fail_with:
            status = self.fail_with.pop(0)
            return status, json.dumps({"error": {"message": "boom"}}).encode()
        parsed = urlparse(url)
        if parsed.netloc == "oauth2.googleapis.com":
            self.token_requests += 1
            return 200, json.dumps({"access_token": "at-1", "expires_in": 3600}).encode()
        query = parse_qs(parsed.query)
        if method == "GET" and parsed.path.endswith("/files") and "q" in query:
            return self._list(query["q"][0])
        if method == "GET" and query.get("alt") == ["media"]:
            return self._download(parsed.path)
        if method == "GET" and re.search(r"/files/[^/]+$", parsed.path):
            return self._get_metadata(parsed.path.rsplit("/", 1)[-1])
        if method == "POST" and "upload" in parsed.path:
            return self._create(headers, body or b"")
        if method == "PATCH" and "upload" in parsed.path:
            return self._update_media(parsed.path, body or b"")
        if method == "POST" and parsed.path.endswith("/files"):
            return self._create_folder(json.loads((body or b"{}").decode()))
        if method == "DELETE":
            self.files.pop(parsed.path.rsplit("/", 1)[-1], None)
            return 204, b""
        return 404, json.dumps({"error": {"message": f"unhandled {method} {url}"}}).encode()

    def _get_metadata(self, file_id: str) -> tuple[int, bytes]:
        if file_id == self.root_id:
            payload: dict[str, Any] = {"id": self.root_id}
            if self.root_on_shared_drive:
                payload["driveId"] = "shared-drive-1"
            return 200, json.dumps(payload).encode()
        found = self.files.get(file_id)
        if found is None:
            return 404, json.dumps({"error": {"message": "File not found"}}).encode()
        return 200, json.dumps({"id": found.id, "name": found.name}).encode()

    def _list(self, q: str) -> tuple[int, bytes]:
        app_property = re.search(
            r"appProperties has \{ key='([^']*)' and value='((?:[^'\\]|\\.)*)' \}", q
        )
        if app_property:
            wanted_value = app_property.group(2).replace("\\'", "'").replace("\\\\", "\\")
            matches = [
                {"id": f.id}
                for f in self.files.values()
                if f.app_properties.get(app_property.group(1)) == wanted_value
            ]
            return 200, json.dumps({"files": matches}).encode()
        name = re.search(r"name='((?:[^'\\]|\\.)*)'", q)
        parent = re.search(r"'([^']+)' in parents", q)
        assert name and parent, q
        wanted = name.group(1).replace("\\'", "'")
        matches = [
            {"id": f.id, "name": f.name}
            for f in self.files.values()
            if f.name == wanted and f.parent == parent.group(1) and f.mime == FOLDER_MIME
        ]
        return 200, json.dumps({"files": matches}).encode()

    def _create_folder(self, payload: dict[str, Any]) -> tuple[int, bytes]:
        new = _File(self._new_id(), payload["name"], payload["parents"][0], FOLDER_MIME)
        self.files[new.id] = new
        return 200, json.dumps({"id": new.id, "name": new.name}).encode()

    def _create(self, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        boundary = re.search(r'boundary="?([^";]+)"?', headers["Content-Type"])
        assert boundary, headers
        parts = body.split(b"--" + boundary.group(1).encode())
        metadata = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n").decode())
        # The trailing `\r\n` before the closing boundary is part of the multipart
        # framing, not the payload -- and must be removed as a fixed two-byte suffix,
        # not with `.rstrip(b"\r\n")`: `rstrip` deletes every trailing byte that is
        # *either* `\r` or `\n`, so a payload legitimately ending in its own `\n` (an
        # ordinary text/PDF byte) would have that byte eaten too. A real PDF written by
        # `put()` and read back by `get()` caught this the first time this fake ran for
        # real, which is exactly why this fake exists.
        data_with_framing = parts[2].split(b"\r\n\r\n", 1)[1]
        data = data_with_framing[:-2] if data_with_framing.endswith(b"\r\n") else data_with_framing
        new = _File(
            self._new_id(),
            metadata["name"],
            metadata["parents"][0],
            "application/octet-stream",
            data,
            dict(metadata.get("appProperties") or {}),
        )
        self.files[new.id] = new
        return 200, json.dumps({"id": new.id}).encode()

    def _update_media(self, path: str, data: bytes) -> tuple[int, bytes]:
        file_id = path.rsplit("/", 1)[-1]
        found = self.files.get(file_id)
        if found is None:
            return 404, json.dumps({"error": {"message": "File not found"}}).encode()
        found.data = data
        return 200, json.dumps({"id": found.id}).encode()

    def _download(self, path: str) -> tuple[int, bytes]:
        file_id = path.rsplit("/", 1)[-1]
        found = self.files.get(file_id)
        return (200, found.data) if found else (404, b'{"error":{"message":"not found"}}')
