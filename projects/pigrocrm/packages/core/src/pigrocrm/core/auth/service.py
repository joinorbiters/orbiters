from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.activities.diff import field_changes
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.passwords import dummy_hash, hash_password, verify_password
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import MIN_PASSWORD_LENGTH, UserCreate, UserRead, UserUpdate
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.schemas import reject_cleared_columns, supplied_changes

INVALID_CREDENTIALS = "credenziali non valide"

# The whole account is one timeline: `created`/`updated` here, and the `pat_*` kinds
# `PatService` writes against this same entity. A personal access token is not
# something a user browses as an object of its own -- the question it raises is always
# about an *account* ("who gave an agent the keys to this one, and is that key still
# live?"), so its lifecycle belongs on the owner's timeline rather than on a per-token
# one nobody would think to open. `activities.kind` is an open string by design, which
# is what makes hanging a second family of events off this entity free.
ENTITY = "user"

# What `update` may touch, mirroring `UserUpdate`'s own fields. `ruolo` and `attivo`
# are the two that matter: between them they are the answer to "who made this account
# an administrator" and "who turned this account off", which is the entire reason this
# audit exists. `password_hash` is not here and must never be -- it is not reachable
# through `UserUpdate` at all, and the absence tests pin that.
_AUDITED_FIELDS = ("nome", "ruolo", "attivo")


def _snapshot(user: User) -> dict[str, object]:
    return {name: getattr(user, name) for name in _AUDITED_FIELDS}


UNVERIFIED_IDENTITY = (
    "prima conferma il tuo indirizzo: entra dal link che ti abbiamo mandato per email"
)


def require_verified_identity(session: Session, actor: Actor, action: str) -> None:
    """An account that never had a password and never used a link by mail is an address
    somebody typed (spec 2026-09-12 §6.4): it may work in its space for the length of an
    access token, and nothing more durable than that. Minting a personal token or
    creating a user would outlive the revocation the first link performs, so both wait
    for the address to be proven. The system and every account with a password or a
    verified address pass."""
    if actor.id is None:
        return
    user = UserRepository(session).get(actor.id)
    if user is None:
        return
    if user.password_hash is None and user.email_verificata_il is None:
        raise ValidationFailed("user", "email", UNVERIFIED_IDENTITY, expected=action)


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = UserRepository(session)
        self.activities = ActivityService(session)

    def create(self, data: UserCreate, actor: Actor) -> UserRead:
        actor.require_admin("create_user")
        require_verified_identity(self.session, actor, "create_user")
        if data.password is None:
            # A user with no password enters with a link by mail (spec 2026-09-12 §6.2).
            # Only the provisioning of a space may create one: an admin adding a
            # colleague still hands them a password, as before.
            if actor.type != "system":
                raise ValidationFailed(
                    "user",
                    "password",
                    "obbligatoria",
                    expected=f">= {MIN_PASSWORD_LENGTH} caratteri",
                )
        elif len(data.password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(
                "user",
                "password",
                f"deve avere almeno {MIN_PASSWORD_LENGTH} caratteri",
                expected=f">= {MIN_PASSWORD_LENGTH} caratteri",
            )
        if self.repo.get_by_email(data.email):
            raise Conflict("user", "esiste già un utente con questa email", email=data.email)

        user = User(
            email=data.email,
            password_hash=hash_password(data.password) if data.password is not None else None,
            nome=data.nome,
            ruolo=data.ruolo,
            attivo=True,
            tariffa_oraria_default=data.tariffa_oraria_default,
            costo_orario_default=data.costo_orario_default,
        )
        try:
            self.repo.add(user)
            # `email` and `ruolo` only. The password never appears -- not the plaintext
            # the caller sent, not the argon2 hash stored on the row -- because a
            # timeline entry is read by more people, and kept for longer, than the
            # column it would have been copied from.
            self.activities.record(
                ENTITY, user.id, "created", actor, {"email": user.email, "ruolo": user.ruolo}
            )
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a race between two concurrent requests:
            # both can pass the SELECT before either has committed. Here the database
            # constraint is the only authority left, and the rollback is mandatory --
            # without it the session stays unusable for whatever the caller does next.
            self.session.rollback()
            raise Conflict(
                "user", "esiste già un utente con questa email", email=data.email
            ) from exc
        return UserRead.model_validate(user)

    def update(self, user_id: UUID, data: UserUpdate, actor: Actor) -> UserRead:
        actor.require_admin("update_user")
        user = self.repo.get(user_id)
        if user is None:
            raise NotFound("user", user_id)
        # Taken before the loop, because `field_changes` below compares it against the
        # object *after* the writes and an entry is recorded only if the two differ.
        before = _snapshot(user)
        # Not listed among task 4B-1's files, converted anyway: leaving two services on
        # `exclude_none` would mean the codebase has two update contracts, which is how
        # A14 survived four slices in the first place. It matters here on its own terms
        # too -- `tariffa_oraria_default` and `costo_orario_default` are nullable, and an
        # unclearable default rate is a number nobody chose staying in force forever.
        #
        # `supplied_changes`, never `model_dump(exclude_none=True)`: under `exclude_none`
        # a field cleared to `null` is indistinguishable from a field the caller never
        # mentioned, so the audit entry would report nothing for exactly the change most
        # worth recording -- somebody removing a default rate.
        changes = supplied_changes(data)
        reject_cleared_columns("user", User, changes)
        for field, value in changes.items():
            setattr(user, field, value)

        # Nothing is recorded when the patch changed nothing: a deactivation that was
        # already in force is not a decision anyone took today. See `field_changes`.
        delta = field_changes(before, _snapshot(user))
        if delta:
            self.activities.record(
                ENTITY, user.id, "updated", actor, {"email": user.email, **delta}
            )
        self.session.commit()
        return UserRead.model_validate(user)

    def reset_password(self, email: str, password: str, actor: Actor) -> UserRead:
        """A new password for an existing account, set by an admin -- in practice by the
        operator at the server's terminal (`pigrocrm resetpassword`), since the product has
        no e-mail flow to hand a link to anyone. Same floor as `create`; the timeline
        records that it happened and for whom, never what was set."""
        actor.require_admin("reset_password")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(
                "user",
                "password",
                f"deve avere almeno {MIN_PASSWORD_LENGTH} caratteri",
                expected=f">= {MIN_PASSWORD_LENGTH} caratteri",
            )
        user = self.repo.get_by_email(email)
        if user is None:
            raise NotFound("user", email)
        user.password_hash = hash_password(password)
        self.activities.record(ENTITY, user.id, "password_reset", actor, {"email": user.email})
        self.session.commit()
        return UserRead.model_validate(user)

    def list(self, actor: Actor) -> list[UserRead]:
        actor.require_admin("list_users")
        return [UserRead.model_validate(u) for u in self.repo.list_all()]

    def count(self) -> int:
        return self.repo.count()

    def authenticate(self, email: str, password: str) -> UserRead:
        user = self.repo.get_by_email(email)
        # Compare against a precomputed constant hash when the user is missing or has
        # never had a password (a link-by-mail account, spec 2026-09-12 §6.2), so every
        # path costs exactly one verify and timing does not reveal which case it was.
        stored = user.password_hash if user is not None else None
        reference = stored if stored is not None else dummy_hash()
        ok = verify_password(password, reference)
        if user is None or stored is None or not ok or not user.attivo:
            raise ValidationFailed("user", "credentials", INVALID_CREDENTIALS)
        return UserRead.model_validate(user)
