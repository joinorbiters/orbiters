from datetime import timedelta
from pathlib import Path

import pytest

from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.storage import (
    MAX_KEY_LENGTH,
    DocumentStorage,
    LocalFileStorage,
    validate_storage_key,
)

PDF = b"%PDF-1.7\nfinto\n"
KEY = "acme-01234567/0199abcd/v1.pdf"


def test_put_then_get_round_trips_the_bytes(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put(KEY, PDF, "application/pdf")
    assert storage.get(KEY) == PDF


def test_put_creates_the_nested_directories(tmp_path: Path) -> None:
    LocalFileStorage(tmp_path).put(KEY, PDF, "application/pdf")
    assert (tmp_path / KEY).is_file()


def test_put_overwrites_an_existing_key(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put(KEY, PDF, "application/pdf")
    storage.put(KEY, b"nuovo", "application/pdf")
    assert storage.get(KEY) == b"nuovo"


def test_put_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    # The write is atomic (write to .tmp, then os.replace) so a crash mid-write can
    # never leave a half-written PDF readable under the real key.
    LocalFileStorage(tmp_path).put(KEY, PDF, "application/pdf")
    assert [p.name for p in (tmp_path / "acme-01234567" / "0199abcd").iterdir()] == ["v1.pdf"]


def test_get_of_a_missing_key_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFound) as excinfo:
        LocalFileStorage(tmp_path).get(KEY)
    assert excinfo.value.details["entity"] == "document_blob"


def test_delete_removes_the_file(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put(KEY, PDF, "application/pdf")
    storage.delete(KEY)
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_delete_of_a_missing_key_is_silent(tmp_path: Path) -> None:
    # Delete is idempotent: a retried request must not fail because the first attempt
    # already succeeded.
    LocalFileStorage(tmp_path).delete(KEY)


def test_signed_url_is_none_because_authorisation_lives_in_the_api(tmp_path: Path) -> None:
    assert LocalFileStorage(tmp_path).signed_url(KEY, timedelta(minutes=5)) is None


def test_local_file_storage_satisfies_the_document_storage_protocol(tmp_path: Path) -> None:
    """Not just a runtime smoke test: the annotation on `storage` makes mypy check
    that `LocalFileStorage`'s four methods structurally match `DocumentStorage`
    exactly -- the same shape the next task's `GDriveStorage` must also satisfy."""
    storage: DocumentStorage = LocalFileStorage(tmp_path)
    assert storage.signed_url(KEY, timedelta(minutes=1)) is None


def test_max_key_length_is_255() -> None:
    assert MAX_KEY_LENGTH == 255


@pytest.mark.parametrize(
    "bad",
    [
        # From the brief: traversal, absolute paths, embedded/empty segments, NUL,
        # backslash, overlength, a segment that cannot start with a hyphen.
        "../fuori.pdf",
        "a/../../fuori.pdf",
        "/assoluto.pdf",
        "a//b.pdf",
        "",
        " ",
        "a\x00b.pdf",
        "a/b\\c.pdf",
        "x" * 256,
        "-inizia-con-trattino.pdf",
        # Trailing slash and lone-dot segments: structurally an empty or "current
        # directory" component, same family as "a//b.pdf" above.
        "a/b/",
        "a/./b.pdf",
        "..",
        ".",
        # A tab is not a NUL byte but is just as far outside the allowed charset.
        "a\tb.pdf",
        # A Windows-style absolute path: no leading "/", but still not a relative key.
        "C:/windows/system32/config.pdf",
        "C:\\windows\\x",
        # Trailing dot: legal on POSIX, silently stripped by Windows, so "a." and "a"
        # can name the same file there. Checked on a bare segment and behind a
        # directory, and with an extension after an *earlier* dot to prove it is the
        # segment's own trailing character that matters, not merely "contains a dot".
        "a.",
        "acme-01/nota.",
        "acme-01/nota.pdf.",
        # Windows-reserved device names, bare and with an extension, case-insensitive,
        # and not just as the final segment.
        "con",
        "CON.pdf",
        "Aux.pdf",
        "com3",
        "lpt9.pdf",
        "aux/report.pdf",
        # A key that normalises differently under NFC vs NFD is refused outright in
        # both forms -- not silently accepted under one spelling and not the other.
        "caff\u00e8.pdf",  # "caffè", NFC: e-grave as one codepoint
        "caffe\u0300.pdf",  # "caffè", NFD: "e" + combining grave accent
    ],
)
def test_an_unsafe_key_is_refused_before_any_filesystem_call(bad: str) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        validate_storage_key(bad)
    assert excinfo.value.details["field"] == "storage_key"


@pytest.mark.parametrize(
    "good",
    [
        "a.pdf",
        "a/b.pdf",
        "acme-01/0199ab/v12.pdf",
        "A_b.C-1/x.pdf",
        # Exactly at MAX_KEY_LENGTH: the boundary the overlength case above sits one
        # character past.
        "x" * 255,
        # Multiple dots, none of them trailing: proves the trailing-dot check looks at
        # the segment's last character, not merely whether a dot is present.
        "acme-01/relazione.finale.pdf",
        # A stem that merely starts with a reserved prefix ("com", "aux") but is not
        # equal to it: the reserved-name check must not over-match by substring.
        "com-mercio/auxiliary.pdf",
    ],
)
def test_a_safe_key_is_accepted(good: str) -> None:
    assert validate_storage_key(good) == good


def test_traversal_is_refused_by_put_and_get_and_delete(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    for call in (
        lambda: storage.put("../escape.pdf", PDF, "application/pdf"),
        lambda: storage.get("../escape.pdf"),
        lambda: storage.delete("../escape.pdf"),
    ):
        with pytest.raises(ValidationFailed):
            call()
    assert not (tmp_path.parent / "escape.pdf").exists()


# --- Symlink containment: a key that is a perfectly safe *string* can still resolve
# outside root if a symlink was already sitting on disk at one of its segments before
# the call. `validate_storage_key` cannot see this (it never touches the filesystem);
# `LocalFileStorage._path` closes the gap by resolving the real destination and
# checking it is still inside root. Each test below plants the symlink first, then
# proves containment by calling the real API and inspecting the filesystem
# afterwards -- not by asserting anything about the key string.


def test_a_preexisting_symlink_cannot_redirect_put_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # Planted before the call: the customer segment of KEY is a symlink to `outside`.
    (root / "acme-01234567").symlink_to(outside)

    with pytest.raises(ValidationFailed):
        LocalFileStorage(root).put(KEY, PDF, "application/pdf")

    assert list(outside.iterdir()) == []


def test_a_preexisting_symlink_cannot_redirect_get_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    (root / "acme-01234567" / "0199abcd").mkdir(parents=True)
    secret = tmp_path / "segreto.txt"
    secret.write_bytes(b"non deve essere leggibile tramite la chiave")
    # Planted before the call: the leaf of KEY is a symlink to a file outside root.
    (root / "acme-01234567" / "0199abcd" / "v1.pdf").symlink_to(secret)

    with pytest.raises(ValidationFailed):
        LocalFileStorage(root).get(KEY)


def test_a_preexisting_symlink_cannot_redirect_delete_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    (root / "acme-01234567" / "0199abcd").mkdir(parents=True)
    victim = tmp_path / "vittima.pdf"
    victim.write_bytes(b"non deve essere cancellato tramite la chiave")
    (root / "acme-01234567" / "0199abcd" / "v1.pdf").symlink_to(victim)

    with pytest.raises(ValidationFailed):
        LocalFileStorage(root).delete(KEY)

    assert victim.exists()


# --- A key that is not a symlink trick but still collides with an existing directory
# (an upstream bug reusing an id, or a stale write) must not surface a raw OSError
# either: `get` and `delete` translate it into the same domain errors as any other
# unreadable/undeletable key.


def test_get_of_a_key_that_is_actually_a_directory_raises_not_found(tmp_path: Path) -> None:
    (tmp_path / "acme-01234567" / "0199abcd" / "v1.pdf").mkdir(parents=True)
    with pytest.raises(NotFound):
        LocalFileStorage(tmp_path).get(KEY)


def test_delete_of_a_key_that_is_actually_a_directory_raises_validation_failed(
    tmp_path: Path,
) -> None:
    (tmp_path / "acme-01234567" / "0199abcd" / "v1.pdf").mkdir(parents=True)
    with pytest.raises(ValidationFailed):
        LocalFileStorage(tmp_path).delete(KEY)
