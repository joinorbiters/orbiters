import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.emitter.repository import EmitterProfileRepository
from pigrocrm.core.emitter.schemas import EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")


def _upsert(**overrides: object) -> EmitterProfileUpsert:
    payload: dict[str, object] = {
        "ragione_sociale": "Humancraft di Ivan Sala",
        "partita_iva": "14518240966",
        "pec": "someone@example.com",
        "indirizzo": "Via Roma 1",
        "comune": "Milano",
        "cap": "20053",
        "provincia": "MI",
        "telefono": "+39 02 1234567",
        "email": "ivansala@humancraft.tech",
        "regime_fiscale": "Regime forfettario, L. 190/2014 art. 1 commi 54-89",
    }
    payload.update(overrides)
    return EmitterProfileUpsert(**payload)  # type: ignore[arg-type]


def test_get_before_any_save_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        EmitterProfileService(db_session).get(ADMIN)


def test_upsert_creates_the_single_row(db_session: Session) -> None:
    profile = EmitterProfileService(db_session).upsert(_upsert(), ADMIN)
    assert profile.ragione_sociale == "Humancraft di Ivan Sala"
    assert profile.partita_iva == "14518240966"


def test_a_second_upsert_updates_rather_than_creating_a_second_row(db_session: Session) -> None:
    service = EmitterProfileService(db_session)
    first = service.upsert(_upsert(), ADMIN)
    second = service.upsert(_upsert(ragione_sociale="Nuovo Nome"), ADMIN)
    assert second.id == first.id
    assert second.ragione_sociale == "Nuovo Nome"


def test_a_readonly_actor_cannot_write(db_session: Session) -> None:
    with pytest.raises(PermissionDenied):
        EmitterProfileService(db_session).upsert(_upsert(), READONLY)


def test_a_malformed_partita_iva_is_refused(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        EmitterProfileService(db_session).upsert(_upsert(partita_iva="1234567890"), ADMIN)
    assert excinfo.value.details["field"] == "partita_iva"


def test_a_partita_iva_with_a_trailing_newline_is_refused(db_session: Session) -> None:
    # `re.match` with `$` would accept this -- `$` matches before a final newline --
    # and the 12-character value would reach the String(11) column as a raw DataError.
    with pytest.raises(ValidationFailed):
        EmitterProfileService(db_session).upsert(_upsert(partita_iva="12345678901"), ADMIN)


def test_as_template_values_exposes_the_profile_under_emittente(db_session: Session) -> None:
    service = EmitterProfileService(db_session)
    service.upsert(_upsert(), ADMIN)
    values = service.as_template_values(ADMIN)
    assert values["emittente"]["ragione_sociale"] == "Humancraft di Ivan Sala"
    assert values["emittente"]["partita_iva"] == "14518240966"
    assert "singleton" not in values["emittente"]


def test_as_template_values_before_any_save_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        EmitterProfileService(db_session).as_template_values(ADMIN)


def test_upsert_converts_a_true_insert_race_into_a_clean_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates two concurrent first-time saves: `repo.get()` reports no row for
    both, so both take the insert branch, and only the `singleton` unique
    constraint stops the second.

    This is the case an earlier draft of `upsert` got wrong: it called
    `repo.add(...)` -- which flushes -- *before* the `try/except IntegrityError`,
    so the constraint violation from this exact scenario escaped as a raw,
    session-poisoning `IntegrityError` instead of a clean `Conflict`. Forcing
    `repo.get()` to always report "no row" (rather than relying on real thread
    concurrency, which a single savepoint-backed test session cannot produce) is
    what reproduces that race deterministically.
    """
    service = EmitterProfileService(db_session)
    monkeypatch.setattr(EmitterProfileRepository, "get", lambda self: None)
    service.upsert(_upsert(), ADMIN)
    with pytest.raises(Conflict):
        service.upsert(_upsert(ragione_sociale="Secondo"), ADMIN)

    # The session must still be usable after the rollback, not poisoned.
    monkeypatch.undo()
    profile = EmitterProfileService(db_session).get(ADMIN)
    assert profile.ragione_sociale == "Humancraft di Ivan Sala"
