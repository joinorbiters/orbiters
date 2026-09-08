import re
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.emitter.models import EmitterProfile
from pigrocrm.core.emitter.repository import EmitterProfileRepository
from pigrocrm.core.emitter.schemas import EmitterProfileRead, EmitterProfileUpsert
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed

ENTITY = "emitter_profile"
# `.fullmatch()`, not `.match()`: `$` matches before a trailing newline, so
# "12345678901" -- 12 characters, one more than the String(11) column -- would pass
# a `.match()` check and reach flush() as a raw, session-poisoning DataError. The same
# defect this project has already paid for once on `customers.partita_iva`.
PARTITA_IVA_RE = re.compile(r"\d{11}")
CODICE_SDI_LENGTH = 7


def _check_fiscal(data: dict[str, Any]) -> None:
    for field in ("partita_iva", "codice_sdi"):
        if data.get(field) == "":
            data[field] = None
    piva = data.get("partita_iva")
    if piva and not PARTITA_IVA_RE.fullmatch(piva):
        raise ValidationFailed(
            ENTITY, "partita_iva", "deve essere di 11 cifre", expected="11 cifre numeriche"
        )
    sdi = data.get("codice_sdi")
    if sdi and len(sdi) != CODICE_SDI_LENGTH:
        raise ValidationFailed(
            ENTITY, "codice_sdi", "deve essere di 7 caratteri", expected="7 caratteri"
        )


class EmitterProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = EmitterProfileRepository(session)
        self.activities = ActivityService(session)

    def get(self, actor: Actor) -> EmitterProfileRead:
        profile = self.repo.get()
        if profile is None:
            raise NotFound(ENTITY, "singleton")
        return EmitterProfileRead.model_validate(profile)

    def upsert(self, data: EmitterProfileUpsert, actor: Actor) -> EmitterProfileRead:
        """Create-or-update the one `EmitterProfile` row.

        The brief this method was drafted from called `self.repo.add(...)` --
        which flushes, and is the only statement that can actually violate the
        `singleton` unique constraint -- *before* the `try/except IntegrityError`,
        which only wrapped the later `self.session.commit()`. That leaves the
        constraint-violating statement unguarded: two concurrent first-time saves
        both see `repo.get() is None`, both construct a row, and the second one's
        `repo.add` flush raises `IntegrityError` right there, uncaught, poisoning
        the session instead of surfacing as a clean `Conflict`. Confirmed by
        reproducing the race deterministically in
        `test_upsert_converts_a_true_insert_race_into_a_clean_conflict` (forcing
        `repo.get()` to report "no row" for two successive calls, since a single
        savepoint-backed test session cannot produce real thread concurrency):
        with `repo.add` called outside this method's `try`, that test's second
        `upsert` call raised a raw `sqlalchemy.exc.IntegrityError` instead of
        `Conflict`. Fixed by moving `repo.add` (mirroring `PipelineService.
        create`'s identical shape in pipeline/service.py) inside the same `try`
        as the commit, so the constraint can only ever be violated where it is
        caught.
        """
        actor.require_admin("upsert_emitter_profile")
        payload = data.model_dump()
        _check_fiscal(payload)

        profile = self.repo.get()
        try:
            if profile is None:
                profile = self.repo.add(EmitterProfile(**payload))
            else:
                for key, value in payload.items():
                    setattr(profile, key, value)

            self.activities.record(
                ENTITY, profile.id, "updated", actor, {"changed": sorted(payload)}
            )
            self.session.commit()
        except IntegrityError as exc:
            # The `repo.get()` pre-check cannot cover two concurrent first-time saves:
            # both see no row, both insert, and only the `singleton` unique constraint
            # stops the second. The rollback is mandatory -- without it the caller's
            # session is unusable on its next statement.
            self.session.rollback()
            raise Conflict(ENTITY, "il profilo emittente esiste gia'") from exc
        return EmitterProfileRead.model_validate(profile)

    def as_template_values(self, actor: Actor) -> dict[str, Any]:
        """The profile as a template scope, under the name `emittente`.

        This is what makes `{{emittente.ragione_sociale}}` work in a template and what
        replaces the hardcoded issuer data in Acme's `header.typ`. `singleton` is
        excluded: it is a storage mechanism, not a fact about the business (and is
        already absent from `EmitterProfileRead` for the same reason).
        """
        profile = self.get(actor)
        return {
            "emittente": profile.model_dump(mode="json", exclude={"id", "created_at", "updated_at"})
        }
