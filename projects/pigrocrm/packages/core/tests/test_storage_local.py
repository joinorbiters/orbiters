import os
import threading
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
    # The write is atomic (mkstemp + os.replace) so a crash mid-write can never leave a
    # half-written PDF readable under the real key, and no stray temp file survives a
    # successful call either.
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
        # Fix round 1: uppercase is refused outright (see the case-collision test
        # below for why) -- a bare uppercase letter, an uppercase extension, and one
        # letter capitalised in an otherwise-ordinary key.
        "A.pdf",
        "acme-01234567/0199abcd/V1.PDF",
        "ACME-01234567/0199abcd/v1.pdf",
        # Fix round 1: pinned explicitly, not just implied by "the charset is
        # ASCII-only" -- URL-encoded and doubly-encoded traversal (a decoding step
        # this function must never perform), an RTL-override and a zero-width
        # character (either could make a rendered filename lie about what bytes it
        # actually is), and two Unicode lookalikes for "/" (a real second path
        # separator would reintroduce traversal; none of `%`, U+202E, U+200B, U+2044,
        # U+FF0F is in `[a-z0-9._-]`, so all five are refused, same as any other
        # non-ASCII byte).
        "%2e%2e%2f",
        "..%2ffuori.pdf",
        "a%2fb.pdf",
        "..%c0%affuori.pdf",
        "acme‮/report.pdf",  # RTL override
        "a​.pdf",  # zero-width space
        "a⁄b.pdf",  # fraction slash, reads like "/"
        "a／b.pdf",  # fullwidth solidus, reads like "/"
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
        # Fix round 1: lowercase-only is now enforced (see the bad-key list and the
        # case-collision test below), so the brief's own original example here --
        # "A_b.C-1/x.pdf" -- is replaced by its lowercase equivalent rather than kept
        # as a now-invalid "good" case.
        "a_b.c-1/x.pdf",
        # Exactly at MAX_KEY_LENGTH: the boundary the overlength case above sits one
        # character past.
        "x" * 255,
        # Multiple dots, none of them trailing: proves the trailing-dot check looks at
        # the segment's last character, not merely whether a dot is present.
        "acme-01/relazione.finale.pdf",
        # A stem that merely starts with a reserved prefix ("com", "aux") but is not
        # equal to it: the reserved-name check must not over-match by substring.
        "com-mercio/auxiliary.pdf",
        # Fix round 1: an ordinary segment containing ".." in the middle is not a
        # traversal attempt and must not be refused by a substring check on the whole
        # key (it now is not -- ".." is compared per segment, exactly, not as a
        # substring; see validate_storage_key's docstring).
        "a..b/c.pdf",
    ],
)
def test_a_safe_key_is_accepted(good: str) -> None:
    assert validate_storage_key(good) == good


def test_a_key_that_differs_only_in_case_is_refused_not_silently_collided(
    tmp_path: Path,
) -> None:
    """Fix round 1: on a case-insensitive filesystem (macOS/APFS, Windows/NTFS by
    default) `KEY` and `KEY.upper()` can name the *same* file even though they are
    different Python strings -- reproduced, before this fix, by writing one and then
    the other and finding the first document silently gone. Lowercase-only in
    `validate_storage_key` closes this by refusing the second spelling outright, rather
    than trying to detect or merge the collision after the fact. Proved through the
    real API: the first document's bytes must still be exactly what was written."""
    storage = LocalFileStorage(tmp_path)
    storage.put(KEY, PDF, "application/pdf")

    with pytest.raises(ValidationFailed):
        storage.put(KEY.upper(), b"contenuto di un attaccante o di un bug", "application/pdf")

    assert storage.get(KEY) == PDF


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


def test_a_self_referential_symlink_segment_raises_a_domain_error_not_a_raw_oserror(
    tmp_path: Path,
) -> None:
    """Fix round 1: a symlink pointing at itself makes real `resolve()` raise a raw
    `OSError` (errno 62, "too many levels of symbolic links") from *inside* the
    containment check itself -- confirmed against this Python on this host before
    fixing it, not assumed. `_resolve_or_refuse` catches it and refuses the key with
    the same domain error any other unsafe destination gets, on all three methods."""
    root = tmp_path / "storage"
    root.mkdir()
    loop = root / "acme-01234567"
    loop.symlink_to(loop)

    storage = LocalFileStorage(root)
    for call in (
        lambda: storage.put(KEY, PDF, "application/pdf"),
        lambda: storage.get(KEY),
        lambda: storage.delete(KEY),
    ):
        with pytest.raises(ValidationFailed):
            call()


def test_a_file_where_a_key_needs_a_directory_raises_a_domain_error_not_a_raw_oserror(
    tmp_path: Path,
) -> None:
    """Fix round 1: if a segment of the key already exists as a plain *file* (an
    upstream bug reusing an id, or a stale write -- not necessarily an attacker),
    descending into it as if it were a directory raises a raw `NotADirectoryError` on
    all three methods, confirmed against the code as it stood before this fix. Now
    caught once, in `_resolve_or_refuse`, rather than needing a separate guard in each
    method."""
    (tmp_path / "acme-01234567").write_bytes(b"un file, non una directory")

    storage = LocalFileStorage(tmp_path)
    for call in (
        lambda: storage.put(KEY, PDF, "application/pdf"),
        lambda: storage.get(KEY),
        lambda: storage.delete(KEY),
    ):
        with pytest.raises(ValidationFailed):
            call()


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


# --- Fix round 1, the CRITICAL item: `put`'s old temporary file was `key + ".tmp"`,
# itself an ordinary-looking storage key, derived by string concatenation outside
# `_path`'s containment check, with no uniqueness guarantee of its own. Each test below
# proves one of the three ways that was reachable -- and, for the ordinary-collision
# case, that it is now impossible -- by writing through the real API and inspecting the
# actual bytes on disk afterward.


def test_put_does_not_destroy_an_unrelated_document_whose_key_is_the_old_tmp_name(
    tmp_path: Path,
) -> None:
    """Before this fix: no attacker at all needed. `KEY + ".tmp"` is itself a
    perfectly valid, ordinary storage key; a real document living there was silently
    destroyed -- no exception, no warning -- the instant `put(KEY, ...)` ran."""
    storage = LocalFileStorage(tmp_path)
    sibling_key = KEY + ".tmp"
    storage.put(sibling_key, b"documento legittimo precedente", "application/pdf")

    storage.put(KEY, PDF, "application/pdf")

    assert storage.get(sibling_key) == b"documento legittimo precedente"
    assert storage.get(KEY) == PDF


def test_put_ignores_a_symlink_planted_at_the_old_deterministic_tmp_name(
    tmp_path: Path,
) -> None:
    """Before this fix: a symlink planted at `<key>.tmp`, pointing outside root, made
    `os.replace` move the *symlink itself* onto the real key -- the upload's bytes
    landed on the symlink's target, outside root, and the real key became a symlink
    pointing there too. `put` no longer ever writes to that deterministic name, so a
    symlink planted there is simply never touched."""
    root = tmp_path / "storage"
    (root / "acme-01234567" / "0199abcd").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "vittima.txt"
    victim.write_bytes(b"contenuto originale della vittima")
    planted = root / "acme-01234567" / "0199abcd" / "v1.pdf.tmp"
    planted.symlink_to(victim)

    LocalFileStorage(root).put(KEY, PDF, "application/pdf")

    assert victim.read_bytes() == b"contenuto originale della vittima"
    assert planted.is_symlink() and os.readlink(planted) == str(victim)
    assert LocalFileStorage(root).get(KEY) == PDF


def test_put_ignores_a_hard_link_planted_at_the_old_deterministic_tmp_name(
    tmp_path: Path,
) -> None:
    """Before this fix: a hard link planted at `<key>.tmp` shares an inode with some
    unrelated file elsewhere on the same filesystem; writing to it (open-with-truncate)
    overwrote that file's content directly. Confirmed here by inode equality, exactly
    as the mechanism that found this checked it -- not merely by comparing bytes, which
    a coincidental copy could also satisfy."""
    root = tmp_path / "storage"
    (root / "acme-01234567" / "0199abcd").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.pdf"
    elsewhere.write_bytes(b"contenuto originale altrove")
    planted = root / "acme-01234567" / "0199abcd" / "v1.pdf.tmp"
    os.link(elsewhere, planted)
    original_inode = elsewhere.stat().st_ino

    LocalFileStorage(root).put(KEY, PDF, "application/pdf")

    assert elsewhere.read_bytes() == b"contenuto originale altrove"
    assert planted.stat().st_ino == original_inode
    assert LocalFileStorage(root).get(KEY) == PDF


def test_concurrent_put_to_the_same_key_never_leaks_a_raw_oserror(tmp_path: Path) -> None:
    """Before this fix: the temp name was deterministic, so concurrent writers to the
    same key shared it, and the loser's `os.replace` raised a raw `FileNotFoundError`
    once the winner's had already consumed the file -- reproduced with real threads
    (25-ish failures out of 40, every run) before this fix, and re-checked here that it
    is now exactly zero, not merely "rare"."""
    storage = LocalFileStorage(tmp_path)
    attempts = 40
    errors: list[BaseException] = []
    lock = threading.Lock()

    def write(i: int) -> None:
        try:
            storage.put(KEY, bytes([i % 256]) * 1000, "application/pdf")
        except BaseException as exc:  # noqa: BLE001 - recording every failure, not swallowing it
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    # Whichever writer won, the result is one coherent, complete payload -- not a mix
    # of two writers' bytes and not a truncated one.
    result = storage.get(KEY)
    assert any(result == bytes([i % 256]) * 1000 for i in range(attempts))
