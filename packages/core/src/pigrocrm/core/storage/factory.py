from pathlib import Path

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.storage.base import DocumentStorage
from pigrocrm.core.storage.gdrive import GDriveStorage
from pigrocrm.core.storage.local import LocalFileStorage


def storage_from_settings(settings: Settings) -> DocumentStorage:
    """The single place a backend is chosen. Services take a `DocumentStorage` and
    never call this, which is what makes swapping backends a configuration change
    rather than a code change (spec 11 criterion 5)."""
    if settings.storage_backend == "gdrive":
        if not settings.gdrive_service_account_json or not settings.gdrive_root_folder_id:
            raise ValidationFailed(
                "settings",
                "storage_backend",
                "gdrive richiede PIGROCRM_GDRIVE_SERVICE_ACCOUNT_JSON e "
                "PIGROCRM_GDRIVE_ROOT_FOLDER_ID",
                expected="entrambe le variabili valorizzate",
            )
        storage = GDriveStorage.from_service_account(
            service_account_json=settings.gdrive_service_account_json,
            root_folder_id=settings.gdrive_root_folder_id,
        )
        # Fails here, at startup, with a message that says what to fix -- rather than
        # at the first customer's upload as a bare 404 or a storageQuotaExceeded three
        # requests deep (decision 4, task-5 brief).
        storage.verify_root_accessible()
        return storage
    return LocalFileStorage(Path(settings.storage_local_root))
