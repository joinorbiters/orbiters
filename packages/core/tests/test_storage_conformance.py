"""The same suite against both backends -- spec 11 criterion 5.

Switching `LocalFileStorage` for `GDriveStorage` must require no change to any
service's code, and this file is the proof: every test in the first section is
parametrised over both, and nothing in it names either one except the fixture that
builds it. A test that can only pass on one backend is a finding about the protocol,
not a reason to special-case the test -- so it either becomes a backend-specific test
in the section below (documented as exactly that), or the protocol's contract changes.

Tests never touch the network: `GDriveStorage` is driven entirely by `FakeDrive`
(tests/fakes/fake_drive.py), an in-memory stand-in for the transport, not for
`GDriveStorage` itself. It is the default and only path here, not a fallback used
when real credentials are absent -- a suite that silently skips without credentials
proves nothing.
"""

import threading
from datetime import timedelta
from pathlib import Path

import pytest
from fakes.fake_drive import FakeDrive, _File

from pigrocrm.core.config import Settings
from pigrocrm.core.drive.query import escape_query_value
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.storage import (
    DocumentStorage,
    GDriveStorage,
    LocalFileStorage,
    storage_from_settings,
)
from pigrocrm.core.storage.gdrive import APP_PROPERTY_KEY

PDF = b"%PDF-1.7\nfinto\n"
KEY = "acme-01234567/0199abcd/v1.pdf"

# A real RSA key is not needed: the fake transport answers the token endpoint without
# verifying the assertion, and `GDriveStorage` is injected with a signer in the tests
# below, so no private key material appears in this repository at all.
SERVICE_ACCOUNT_JSON = (
    '{"type":"service_account","client_email":"pigro@example.iam.gserviceaccount.com",'
    '"private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n",'
    '"token_uri":"https://oauth2.googleapis.com/token"}'
)


def _drive_storage() -> tuple[GDriveStorage, FakeDrive]:
    drive = FakeDrive()
    return (
        GDriveStorage.from_service_account(
            service_account_json=SERVICE_ACCOUNT_JSON,
            root_folder_id=drive.root_id,
            http=drive,
            sign_assertion=lambda claims: "assertion",
        ),
        drive,
    )


@pytest.fixture(params=["local", "gdrive"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> DocumentStorage:
    if request.param == "local":
        return LocalFileStorage(tmp_path)
    made, drive = _drive_storage()
    request.node.stash["drive"] = drive  # type: ignore[index]
    return made


# --- Common contract, both backends --------------------------------------------------


def test_put_then_get_round_trips(storage: DocumentStorage) -> None:
    """Read-your-own-writes, the Protocol's stated minimum (see `DocumentStorage`'s
    docstring): a `get` that follows a `put` for the same key must see it, immediately,
    not eventually."""
    storage.put(KEY, PDF, "application/pdf")
    assert storage.get(KEY) == PDF


def test_put_twice_overwrites_rather_than_duplicating(storage: DocumentStorage) -> None:
    storage.put(KEY, PDF, "application/pdf")
    storage.put(KEY, b"nuovo", "application/pdf")
    assert storage.get(KEY) == b"nuovo"


def test_get_of_a_missing_key_raises_not_found(storage: DocumentStorage) -> None:
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_delete_then_get_raises_not_found(storage: DocumentStorage) -> None:
    storage.put(KEY, PDF, "application/pdf")
    storage.delete(KEY)
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_delete_of_a_missing_key_is_silent(storage: DocumentStorage) -> None:
    storage.delete(KEY)


def test_two_keys_under_the_same_folder_do_not_collide(storage: DocumentStorage) -> None:
    storage.put("acme-0123/doc/v1.pdf", b"uno", "application/pdf")
    storage.put("acme-0123/doc/v2.pdf", b"due", "application/pdf")
    assert storage.get("acme-0123/doc/v1.pdf") == b"uno"
    assert storage.get("acme-0123/doc/v2.pdf") == b"due"


def test_an_unsafe_key_is_refused_by_every_backend(storage: DocumentStorage) -> None:
    """Containment, at the one gate every backend shares: `validate_storage_key`
    refuses a traversal attempt before either backend ever touches the filesystem or
    the network for it. `LocalFileStorage`'s own, deeper containment check (a symlink
    already planted on disk) has no equivalent concept on a remote backend, so it stays
    a local-only test in test_storage_local.py -- this is the shared floor both must
    clear."""
    with pytest.raises(ValidationFailed):
        storage.put("../fuori.pdf", PDF, "application/pdf")


def test_put_of_a_key_ending_in_tmp_does_not_collide_with_anything(
    storage: DocumentStorage,
) -> None:
    """`LocalFileStorage.put` used to write its temporary file at `key + ".tmp"`, an
    ordinary-looking storage key of its own -- so a real document already living at
    that literal key was silently destroyed the moment the "real" key was written
    (task-4-report.md). That bug is fixed by never deriving a temp name from the key at
    all, but the fix is only proven by a key of exactly this shape continuing to behave
    like any other key, on every backend -- not only the one the bug was found on."""
    sibling_key = KEY + ".tmp"
    storage.put(sibling_key, b"documento la cui chiave finisce in .tmp", "application/pdf")
    storage.put(KEY, PDF, "application/pdf")
    assert storage.get(sibling_key) == b"documento la cui chiave finisce in .tmp"
    assert storage.get(KEY) == PDF


def test_concurrent_put_to_the_same_key_converges_on_one_coherent_value(
    storage: DocumentStorage,
) -> None:
    """Every backend must survive concurrent writers to the same key without raising
    or corrupting the payload into a mix of two writers' bytes. It must *not* be read
    as a promise that only one writer's bytes survive as the sole file on the backend
    -- Drive has no atomic create-if-absent, so two writers racing to create a
    brand-new key can each succeed in creating a file (see `GDriveStorage._find_file_by_key`).
    What both backends do guarantee is that every reader converges on the *same*
    coherent value afterwards, which is what is actually checked here."""
    attempts = 12
    errors: list[BaseException] = []
    lock = threading.Lock()

    def write(i: int) -> None:
        try:
            storage.put(KEY, bytes([i % 256]) * 500, "application/pdf")
        except BaseException as exc:  # noqa: BLE001 - recording every failure, not swallowing it
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    first_read = storage.get(KEY)
    assert any(first_read == bytes([i % 256]) * 500 for i in range(attempts))
    assert storage.get(KEY) == first_read


def test_signed_url_is_either_none_or_a_https_url(storage: DocumentStorage) -> None:
    storage.put(KEY, PDF, "application/pdf")
    url = storage.signed_url(KEY, timedelta(minutes=5))
    assert url is None or url.startswith("https://")


def test_an_empty_payload_round_trips(storage: DocumentStorage) -> None:
    """A zero-byte document is a legitimate, if odd, thing to store -- an upload that
    failed after creating the record but before any bytes arrived, say. Neither
    backend should treat "no bytes" as "no file": `LocalFileStorage.get` would raise
    `NotFound` here if `put` had ever skipped the write for empty data, and Drive's
    multipart body construction (gdrive.py's `put`) has an empty media part to get
    right, not just a small one."""
    storage.put(KEY, b"", "application/pdf")
    assert storage.get(KEY) == b""


def test_a_large_payload_round_trips_intact(storage: DocumentStorage) -> None:
    """Large enough to catch a backend that silently truncates or chunks incorrectly
    -- comfortably past any small internal buffer size either implementation might
    otherwise get away with using -- without being slow enough to make the suite
    itself slow."""
    large = bytes(range(256)) * 20_000  # ~5.1 MB, not a round number of any buffer
    storage.put(KEY, large, "application/pdf")
    assert storage.get(KEY) == large


def test_a_payload_ending_in_crlf_round_trips_intact(storage: DocumentStorage) -> None:
    """Not a hypothetical: `FakeDrive._create`'s multipart parser has to distinguish
    the framing `\\r\\n` before Drive's own closing boundary from a `\\r\\n` that is
    part of the document's *own* last two bytes -- confirmed against a real payload of
    exactly this shape the first time that parser ran, not merely reasoned about in a
    comment. A payload that happens to end in `\\r\\n` must come back whole, on every
    backend, not just on the one whose multipart framing this originally broke."""
    payload = b"contenuto legittimo che termina con una sequenza CRLF\r\n"
    storage.put(KEY, payload, "application/pdf")
    assert storage.get(KEY) == payload


# --- Drive-only behaviour, tested through the same public surface -------------------


def test_drive_creates_one_folder_per_key_segment() -> None:
    storage, drive = _drive_storage()
    storage.put(KEY, PDF, "application/pdf")
    names = sorted(f.name for f in drive.files.values())
    assert names == ["0199abcd", "acme-01234567", "v1.pdf"]


def test_drive_reuses_an_existing_folder_instead_of_creating_a_second() -> None:
    # "chi migra da Acme ritrova le sue cartelle" (spec 5) only holds if a second
    # upload finds the folder the first one made.
    storage, drive = _drive_storage()
    storage.put("acme-0123/doc/v1.pdf", b"uno", "application/pdf")
    storage.put("acme-0123/doc/v2.pdf", b"due", "application/pdf")
    assert sorted(f.name for f in drive.files.values()) == ["acme-0123", "doc", "v1.pdf", "v2.pdf"]


def test_get_and_delete_never_query_by_folder_membership() -> None:
    """The structural property decision 3 exists to guarantee: `get` and `delete`
    locate a file purely by its `appProperties`, never by asking Drive "what is in
    this folder" (a `q` filter containing `'<id>' in parents`). Proven here by
    inspecting the actual call log for that clause, not by planting a decoy folder and
    checking the *outcome* -- an earlier version of this test did exactly that
    (`test_drive_lookup_ignores_a_duplicate_folder_left_behind_by_a_create_race`) and
    was decorative: `get`'s call sequence was byte-for-byte identical whether or not
    the decoy existed, because `get` never queries folders at all, so planting one
    could not have made the test fail for the reason its name claimed. Confirmed this
    version can fail: temporarily routing `get` through `_walk`-style folder
    resolution made this test fail with a real `'... in parents'` clause in the log,
    before being reverted.
    """
    storage, drive = _drive_storage()
    storage.put(KEY, PDF, "application/pdf")
    drive.calls.clear()

    storage.get(KEY)
    storage.delete(KEY)

    folder_scoped_queries = [url for _, url in drive.calls if "parents" in url]
    assert folder_scoped_queries == []


def test_drive_asks_for_an_access_token_once_and_reuses_it() -> None:
    storage, drive = _drive_storage()
    storage.put("a/b.pdf", PDF, "application/pdf")
    storage.get("a/b.pdf")
    assert drive.token_requests == 1


def test_drive_sends_supports_all_drives_on_every_call() -> None:
    # A service account has no Drive quota of its own, so the root folder must be on a
    # Shared Drive -- and every request has to say it can handle one.
    storage, drive = _drive_storage()
    storage.put(KEY, PDF, "application/pdf")
    # Excludes the OAuth token endpoint deliberately: it is not a Drive API call and
    # has no `supportsAllDrives` parameter to carry.
    api_calls = [url for _, url in drive.calls if "www.googleapis.com" in url]
    assert api_calls and all("supportsAllDrives=true" in url for url in api_calls)


def test_drive_turns_a_transport_failure_into_a_domain_conflict() -> None:
    storage, drive = _drive_storage()
    drive.fail_with = [403]
    with pytest.raises(Conflict) as excinfo:
        storage.put(KEY, PDF, "application/pdf")
    assert excinfo.value.details["entity"] == "document_blob"
    assert "403" in excinfo.value.details["reason"]


def test_drive_signed_url_is_none_so_downloads_stay_behind_the_api() -> None:
    # Drive *can* mint a link, but a link that outlives a permission check is a leak
    # nobody revokes. The API is the only place authorisation exists (spec 5).
    storage, _ = _drive_storage()
    assert storage.signed_url(KEY, timedelta(minutes=5)) is None


def test_escape_query_value_escapes_backslash_before_quote() -> None:
    """Direct test of the escaper itself: no storage key can actually contain a quote
    or backslash (`validate_storage_key`'s character class forbids both), so a test
    that only calls `put`/`get` with a "quoted" key would never exercise this function
    at all -- it would just prove that dots and hyphens survive, which nothing was
    ever in doubt about. Escaping the backslash first is load-bearing: escaping the
    quote first would leave a lone trailing backslash in a name like `a\\` able to
    escape the filter's own closing quote instead of the name's."""
    assert escape_query_value("bar's") == "bar\\'s"
    assert escape_query_value("a\\b") == "a\\\\b"
    assert escape_query_value("a\\'b") == "a\\\\\\'b"


def test_drive_verify_root_accessible_passes_when_root_is_reachable() -> None:
    storage, _ = _drive_storage()
    storage.verify_root_accessible()  # does not raise


def test_drive_verify_root_accessible_fails_clearly_when_root_is_unreachable() -> None:
    drive = FakeDrive()
    storage = GDriveStorage.from_service_account(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id="cartella-mai-condivisa",
        http=drive,
        sign_assertion=lambda claims: "assertion",
    )
    with pytest.raises(RuntimeError, match="GDRIVE_ROOT_FOLDER_ID"):
        storage.verify_root_accessible()


def test_drive_verify_root_accessible_fails_clearly_when_root_is_not_on_a_shared_drive() -> None:
    drive = FakeDrive(root_on_shared_drive=False)
    storage = GDriveStorage.from_service_account(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id=drive.root_id,
        http=drive,
        sign_assertion=lambda claims: "assertion",
    )
    with pytest.raises(RuntimeError, match="Shared Drive"):
        storage.verify_root_accessible()


# --- The create-race: two concurrent first-writers for a brand-new key can each miss
# the other's not-yet-visible file and each create one carrying the same
# `appProperties`. Reproduced here by planting both files directly rather than by
# racing real threads against the fake -- a deterministic reproduction, not a
# probabilistic one, of exactly what a reviewer found by instrumenting the fake's
# call log. `test_concurrent_put_to_the_same_key_converges_on_one_coherent_value`
# above covers the same race through real concurrency, for both backends; these two
# are Drive-specific because only Drive can produce this particular duplicate shape.


def test_delete_removes_every_file_left_by_a_create_race() -> None:
    """The bug a reviewer found: `delete` used to remove only the one file
    `_find_file_by_key` resolved to (the lowest id), leaving the other sitting on
    Drive under the same `appProperties`. The next `get` would then resolve to the
    survivor and return content the caller had just been told was deleted. This
    reproduces the duplicate directly and proves both are gone, and that `get`
    afterwards raises `NotFound` rather than resurrecting the second file."""
    storage, drive = _drive_storage()
    drive.files["id-a"] = _File(
        "id-a", "v1.pdf", drive.root_id, "application/pdf", b"from-A", {APP_PROPERTY_KEY: KEY}
    )
    drive.files["id-b"] = _File(
        "id-b", "v1.pdf", drive.root_id, "application/pdf", b"from-B", {APP_PROPERTY_KEY: KEY}
    )

    storage.delete(KEY)

    assert drive.files == {}
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_put_heals_duplicates_left_by_a_create_race_onto_one_file() -> None:
    """What `put` does when it finds duplicates already present, decided here rather
    than left implicit: it converges on the lowest id as canonical (the same one
    `get` already reads), writes the new bytes there, and deletes the rest -- so a
    write to a raced key is also a repair of it. `delete` does not depend on this ever
    happening (see the test above), but there is no reason to leave a known duplicate
    sitting on Drive once a write has already found it."""
    storage, drive = _drive_storage()
    drive.files["id-a"] = _File(
        "id-a", "v1.pdf", drive.root_id, "application/pdf", b"from-A", {APP_PROPERTY_KEY: KEY}
    )
    drive.files["id-b"] = _File(
        "id-b", "v1.pdf", drive.root_id, "application/pdf", b"from-B", {APP_PROPERTY_KEY: KEY}
    )

    storage.put(KEY, b"versione-pulita", "application/pdf")

    assert list(drive.files.keys()) == ["id-a"]
    assert storage.get(KEY) == b"versione-pulita"


# --- Retry-with-backoff: a 429 or a transient 5xx is retried, bounded; anything else
# is not.


def test_drive_retries_a_transient_failure_and_succeeds() -> None:
    sleeps: list[float] = []
    drive = FakeDrive()
    drive.fail_with = [429, 503]  # two transient failures, then the real handling
    storage = GDriveStorage.from_service_account(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id=drive.root_id,
        http=drive,
        sign_assertion=lambda claims: "assertion",
        sleep=sleeps.append,
    )

    storage.put(KEY, PDF, "application/pdf")

    assert storage.get(KEY) == PDF
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]  # backoff increases between attempts


def test_drive_gives_up_after_the_retry_bound_and_raises_conflict() -> None:
    """Not just "eventually raises" -- that would hold even with no retrying at all,
    since a permanent 503 fails on the very first attempt either way. What is
    actually being protected is boundedness: with 10 consecutive 503s queued, ten
    times more than the retry bound, this must still stop and raise rather than
    consuming the whole queue (or, with an unbounded retry loop, never returning at
    all)."""
    drive = FakeDrive()
    drive.fail_with = [503] * 10  # far more than the retry bound
    sleeps: list[float] = []
    storage = GDriveStorage.from_service_account(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id=drive.root_id,
        http=drive,
        sign_assertion=lambda claims: "assertion",
        sleep=sleeps.append,
    )

    with pytest.raises(Conflict):
        storage.put(KEY, PDF, "application/pdf")

    # Bounded: only 3 retries (4 attempts total) were made, so most of the queued
    # failures were never even consumed.
    assert len(sleeps) == 3
    assert len(drive.fail_with) > 0


def test_drive_does_not_retry_a_non_transient_client_error() -> None:
    """A 404 (or any 4xx other than 429) will not fix itself by waiting, so retrying
    it only delays reporting a real failure -- proven here by making a sleep call
    itself the test failure, not just by counting attempts afterwards."""

    def _fail_if_called(seconds: float) -> None:
        raise AssertionError(f"should not have slept {seconds}s for a non-transient error")

    drive = FakeDrive()
    drive.fail_with = [404]
    storage = GDriveStorage.from_service_account(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id=drive.root_id,
        http=drive,
        sign_assertion=lambda claims: "assertion",
        sleep=_fail_if_called,
    )

    with pytest.raises(Conflict):
        storage.put(KEY, PDF, "application/pdf")


# --- storage_from_settings: the single place a backend is chosen --------------------


def test_storage_from_settings_defaults_to_local(tmp_path: Path) -> None:
    settings = Settings(storage_local_root=str(tmp_path))
    assert isinstance(storage_from_settings(settings), LocalFileStorage)


def test_storage_from_settings_gdrive_requires_credentials_and_root() -> None:
    """And the refusal names *both* ways to configure Drive. A message that mentions
    only the two service-account variables sends the reader to the Google Cloud console
    when, from slice 9D, connecting Drive from Impostazioni is the other sanctioned
    answer -- and this error is the only place that reader is looking."""
    settings = Settings(storage_backend="gdrive")
    with pytest.raises(ValidationFailed) as excinfo:
        storage_from_settings(settings)

    reason = excinfo.value.details["reason"]
    assert "PIGROCRM_GDRIVE_SERVICE_ACCOUNT_JSON" in reason
    assert "collega Drive da Impostazioni e scegli la cartella di scrittura" in reason
    assert "service account" in excinfo.value.details["expected"]


def test_storage_from_settings_gdrive_fails_fast_when_root_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the factory wires `verify_root_accessible` in, without making a real
    network call: `GDriveStorage.__init__` never touches the network by itself, so the
    only thing to fake here is the verification step -- exactly the seam
    `storage_from_settings` is supposed to call."""

    def _raise(self: GDriveStorage) -> None:
        raise RuntimeError("cartella radice non raggiungibile")

    monkeypatch.setattr(GDriveStorage, "verify_root_accessible", _raise)
    settings = Settings(
        storage_backend="gdrive",
        gdrive_service_account_json=SERVICE_ACCOUNT_JSON,
        gdrive_root_folder_id="qualsiasi",
    )
    with pytest.raises(RuntimeError, match="non raggiungibile"):
        storage_from_settings(settings)
