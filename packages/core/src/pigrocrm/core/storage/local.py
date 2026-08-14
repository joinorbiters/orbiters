"""The default backend. A directory on disk, and no external dependency at all --
which is what makes the product genuinely self-hostable (spec 5)."""

import os
from datetime import timedelta
from pathlib import Path

from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.storage.base import validate_storage_key


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        """The one place every method maps a key to a real filesystem location.

        Two independent gates, in order. `validate_storage_key` rejects an unsafe
        *string* before any filesystem call -- traversal, absolute paths, reserved
        names, length. The containment check below then catches what that first gate
        cannot: a key made of only safe segments still resolves through whatever is
        physically sitting at each of those segments, and if a symlink was planted at
        one of them ahead of time, pointing outside `root`, the resolved path lands
        outside `root` even though the key string itself was fine. Comparing resolved
        paths, rather than trusting the join, is what catches that.
        """
        validated = validate_storage_key(key)
        candidate = self.root / validated
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise ValidationFailed(
                "document_version",
                "storage_key",
                "il percorso risolto punta fuori dalla radice di storage",
                expected="una chiave la cui destinazione reale resti dentro la radice",
            )
        return candidate

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """`content_type` is accepted and ignored: a filesystem has no place to record
        it, and the authoritative copy is `document_versions.content_type` in Postgres
        -- which is where every reader already looks. Storing it in a sidecar file
        would create a second answer that can disagree with the first."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: os.replace is atomic on the same filesystem, so a crash
        # mid-write can never leave a truncated PDF readable under the real key.
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError) as exc:
            # IsADirectoryError alongside FileNotFoundError: a key that collides with
            # an existing directory (a bug upstream, or a wrong id reused) is just as
            # much "no such document blob" as a key nothing was ever written under --
            # neither is the raw OSError this project has already let reach a caller
            # six times for other input shapes.
            raise NotFound("document_blob", key) from exc

    def delete(self, key: str) -> None:
        """Idempotent: a retried request must not fail because the first one worked.

        Checks `is_dir()` before unlinking rather than catching the error `unlink`
        raises for a directory, because that error is not portable: the same
        directory target raises `IsADirectoryError` (EISDIR) on Linux but
        `PermissionError` (EPERM) on macOS/BSD -- confirmed against the Python
        installed here, not assumed. Catching only the Linux shape would let the
        macOS one through as a raw, unrelated-looking `PermissionError`; checking the
        actual filesystem type first sidesteps the platform difference entirely.
        """
        path = self._path(key)
        if path.is_dir():
            raise ValidationFailed(
                "document_version",
                "storage_key",
                "la chiave indica una directory, non un singolo blob",
                expected="una chiave che identifica un unico file",
            )
        path.unlink(missing_ok=True)

    def signed_url(self, key: str, ttl: timedelta) -> str | None:
        """Always `None`. The download passes through the API, which is the only place
        authorisation exists (spec 5)."""
        validate_storage_key(key)
        return None
