from pathlib import Path

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.storage.base import DocumentStorage
from pigrocrm.core.storage.gdrive import GDriveStorage
from pigrocrm.core.storage.lazy_drive import LazyUserDriveStorage, SessionFactory
from pigrocrm.core.storage.local import LocalFileStorage


def _gdrive_not_configured() -> ValidationFailed:
    """Two ways to configure Drive, so the error names both: the service-account
    variables, and the connected Google account whose own credential writes into a
    folder the titolare picks. A message naming only the first sends the reader to the
    Google Cloud console for a setup they may have no reason to create, and this error
    is the only place they are looking.

    Neither half names a slice. This sentence is read by an operator watching an API
    fail to start, who has no map of this project's slices and no way to act on one --
    and a slice number is a fact about when the code was written, which stops being
    true the moment it ships.

    Built here rather than raised in two branches below: the half-configured service
    account and the missing session factory are the same problem to the reader (Drive
    is selected and finished being configured by neither route), and two copies of this
    paragraph would eventually be two different paragraphs.
    """
    return ValidationFailed(
        "settings",
        "storage_backend",
        "gdrive richiede PIGROCRM_GDRIVE_SERVICE_ACCOUNT_JSON e "
        "PIGROCRM_GDRIVE_ROOT_FOLDER_ID, oppure collega "
        "Drive da Impostazioni e scegli la cartella di scrittura",
        expected="le due variabili del service account, oppure un account "
        "Drive collegato con cartella di scrittura",
    )


def storage_from_settings(
    settings: Settings, *, session_factory: SessionFactory | None = None
) -> DocumentStorage:
    """The single place a backend is chosen. Services take a `DocumentStorage` and
    never call this, which is what makes swapping backends a configuration change
    rather than a code change (spec 11 criterion 5).

    `session_factory` is what the second Drive route needs and the first does not: the
    titolare's credential and the folder it writes into live in `google_drive_accounts`,
    so that storage has to be able to open a session later, at each operation. It is
    optional because two of the three outcomes here have no use for one -- and because
    an adapter with no database (there is none today, but the parameter should not
    invent one) can still ask for `local`.

    Which of the two Drive routes is chosen is settled by the environment alone, never
    by which one happens to work: naming *either* service-account variable selects the
    service account and makes the other one required, so a half-finished service-account
    setup fails loudly at startup instead of silently falling through to somebody's
    personal Drive credential.
    """
    if settings.storage_backend == "gdrive":
        if settings.gdrive_service_account_json or settings.gdrive_root_folder_id:
            if not settings.gdrive_service_account_json or not settings.gdrive_root_folder_id:
                raise _gdrive_not_configured()
            storage = GDriveStorage.from_service_account(
                service_account_json=settings.gdrive_service_account_json,
                root_folder_id=settings.gdrive_root_folder_id,
            )
            # Fails here, at startup, with a message that says what to fix -- rather
            # than at the first customer's upload as a bare 404 or a
            # storageQuotaExceeded three requests deep (decision 4, task-5 brief).
            storage.verify_root_accessible()
            return storage
        if session_factory is None:
            raise _gdrive_not_configured()
        # No verification here, and none is possible: the folder this will write into is
        # a row that may not exist yet, which is the entire reason this storage resolves
        # at its first operation instead of now (see `LazyUserDriveStorage`). The
        # equivalent of `verify_root_accessible` for this route is the write that
        # happens when somebody chooses the folder, not a check at startup.
        return LazyUserDriveStorage(session_factory, settings)
    return LocalFileStorage(Path(settings.storage_local_root))
