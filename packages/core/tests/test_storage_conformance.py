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
from fakes.fake_drive import FakeDrive

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.storage import (
    DocumentStorage,
    GDriveStorage,
    LocalFileStorage,
    storage_from_settings,
)
from pigrocrm.core.storage.gdrive import _escape_drive_query

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
        GDriveStorage(
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


# --- Drive-only behaviour, tested through the same public surface -------------------


def test_drive_creates_one_folder_per_key_segment() -> None:
    storage, drive = _drive_storage()
    storage.put(KEY, PDF, "application/pdf")
    names = sorted(f.name for f in drive.files.values())
    assert names == ["0199abcd", "acme-01234567", "v1.pdf"]


def test_drive_reuses_an_existing_folder_instead_of_creating_a_second() -> None:
    # "chi migra da the previous system ritrova le sue cartelle" (spec 5) only holds if a second
    # upload finds the folder the first one made.
    storage, drive = _drive_storage()
    storage.put("acme-0123/doc/v1.pdf", b"uno", "application/pdf")
    storage.put("acme-0123/doc/v2.pdf", b"due", "application/pdf")
    assert sorted(f.name for f in drive.files.values()) == ["acme-0123", "doc", "v1.pdf", "v2.pdf"]


def test_drive_lookup_ignores_a_duplicate_folder_left_behind_by_a_create_race() -> None:
    """Decision 3's whole point: two concurrent first-uploads for a customer can each
    create a folder of the same name under the same parent, leaving the tree
    genuinely ambiguous. A lookup keyed on the file's `appProperties` must not care --
    it must find the file even when a second, empty folder sharing its parent's name
    exists and could just as easily have been the one a name-based walk chose."""
    storage, drive = _drive_storage()
    storage.put(KEY, PDF, "application/pdf")
    real_leaf_folder = next(f for f in drive.files.values() if f.name == "0199abcd")
    drive._create_folder({"name": "0199abcd", "parents": [real_leaf_folder.parent]})

    assert storage.get(KEY) == PDF


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
    drive.fail_next_with = 403
    with pytest.raises(Conflict) as excinfo:
        storage.put(KEY, PDF, "application/pdf")
    assert excinfo.value.details["entity"] == "document_blob"
    assert "403" in excinfo.value.details["reason"]


def test_drive_signed_url_is_none_so_downloads_stay_behind_the_api() -> None:
    # Drive *can* mint a link, but a link that outlives a permission check is a leak
    # nobody revokes. The API is the only place authorisation exists (spec 5).
    storage, _ = _drive_storage()
    assert storage.signed_url(KEY, timedelta(minutes=5)) is None


def test_escape_drive_query_escapes_backslash_before_quote() -> None:
    """Direct test of the escaper itself: no storage key can actually contain a quote
    or backslash (`validate_storage_key`'s character class forbids both), so a test
    that only calls `put`/`get` with a "quoted" key would never exercise this function
    at all -- it would just prove that dots and hyphens survive, which nothing was
    ever in doubt about. Escaping the backslash first is load-bearing: escaping the
    quote first would leave a lone trailing backslash in a name like `a\\` able to
    escape the filter's own closing quote instead of the name's."""
    assert _escape_drive_query("bar's") == "bar\\'s"
    assert _escape_drive_query("a\\b") == "a\\\\b"
    assert _escape_drive_query("a\\'b") == "a\\\\\\'b"


def test_drive_verify_root_accessible_passes_when_root_is_reachable() -> None:
    storage, _ = _drive_storage()
    storage.verify_root_accessible()  # does not raise


def test_drive_verify_root_accessible_fails_clearly_when_root_is_unreachable() -> None:
    drive = FakeDrive()
    storage = GDriveStorage(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id="cartella-mai-condivisa",
        http=drive,
        sign_assertion=lambda claims: "assertion",
    )
    with pytest.raises(RuntimeError, match="GDRIVE_ROOT_FOLDER_ID"):
        storage.verify_root_accessible()


def test_drive_verify_root_accessible_fails_clearly_when_root_is_not_on_a_shared_drive() -> None:
    drive = FakeDrive(root_on_shared_drive=False)
    storage = GDriveStorage(
        service_account_json=SERVICE_ACCOUNT_JSON,
        root_folder_id=drive.root_id,
        http=drive,
        sign_assertion=lambda claims: "assertion",
    )
    with pytest.raises(RuntimeError, match="Shared Drive"):
        storage.verify_root_accessible()


# --- storage_from_settings: the single place a backend is chosen --------------------


def test_storage_from_settings_defaults_to_local(tmp_path: Path) -> None:
    settings = Settings(storage_local_root=str(tmp_path))
    assert isinstance(storage_from_settings(settings), LocalFileStorage)


def test_storage_from_settings_gdrive_requires_credentials_and_root() -> None:
    settings = Settings(storage_backend="gdrive")
    with pytest.raises(ValidationFailed):
        storage_from_settings(settings)


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
