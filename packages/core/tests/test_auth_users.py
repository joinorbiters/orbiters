import statistics
import time
from collections.abc import Callable

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.passwords import hash_password, verify_password
from pigrocrm.core.auth.schemas import NOME_MAX_LENGTH, UserCreate, UserUpdate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.errors import Conflict, PermissionDenied, ValidationFailed

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")


def test_password_hash_is_argon2_and_never_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2")
    assert "correct horse" not in hashed
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_the_same_password_hashes_differently_each_time() -> None:
    assert hash_password("same") != hash_password("same"), "argon2 must salt per hash"


def test_create_user_stores_a_hash_and_normalises_the_email(db_session: Session) -> None:
    service = UserService(db_session)
    user = service.create(
        UserCreate(email="someone@example.com", password="supersegreta1", nome="Ivan", ruolo="admin"),
        ADMIN,
    )
    assert user.email == "someone@example.com"
    assert user.ruolo == "admin"
    assert user.attivo is True
    assert not hasattr(user, "password_hash"), "UserRead must never expose the hash"


def test_duplicate_email_is_a_conflict(db_session: Session) -> None:
    service = UserService(db_session)
    service.create(
        UserCreate(email="a@b.it", password="supersegreta1", nome="A", ruolo="admin"), ADMIN
    )
    with pytest.raises(Conflict) as exc:
        service.create(
            UserCreate(email="A@B.it", password="supersegreta1", nome="A2", ruolo="admin"), ADMIN
        )
    assert exc.value.details["entity"] == "user"


def test_short_password_is_rejected(db_session: Session) -> None:
    service = UserService(db_session)
    with pytest.raises(ValidationFailed) as exc:
        service.create(UserCreate(email="c@d.it", password="corta", nome="C", ruolo="admin"), ADMIN)
    assert exc.value.details["field"] == "password"


def test_only_admins_manage_users(db_session: Session) -> None:
    service = UserService(db_session)
    with pytest.raises(PermissionDenied) as exc:
        service.create(
            UserCreate(email="e@f.it", password="supersegreta1", nome="E", ruolo="readonly"), COLLAB
        )
    assert exc.value.details["required_roles"] == ["admin"]


def test_authenticate_accepts_correct_credentials(db_session: Session) -> None:
    service = UserService(db_session)
    service.create(
        UserCreate(email="g@h.it", password="supersegreta1", nome="G", ruolo="admin"), ADMIN
    )
    assert service.authenticate("G@H.it", "supersegreta1").email == "g@h.it"


@pytest.mark.parametrize(
    "email,password", [("g@h.it", "sbagliata"), ("nope@h.it", "supersegreta1")]
)
def test_authenticate_rejects_bad_credentials_without_saying_which(
    db_session: Session, email: str, password: str
) -> None:
    """Distinguishing 'unknown user' from 'wrong password' leaks which emails exist."""
    service = UserService(db_session)
    service.create(
        UserCreate(email="g@h.it", password="supersegreta1", nome="G", ruolo="admin"), ADMIN
    )
    with pytest.raises(ValidationFailed) as exc:
        service.authenticate(email, password)
    assert exc.value.details["reason"] == "credenziali non valide"


def test_deactivated_user_cannot_authenticate(db_session: Session) -> None:
    service = UserService(db_session)
    user = service.create(
        UserCreate(email="i@j.it", password="supersegreta1", nome="I", ruolo="admin"), ADMIN
    )
    service.update(user.id, UserUpdate(attivo=False), ADMIN)
    with pytest.raises(ValidationFailed) as exc:
        service.authenticate("i@j.it", "supersegreta1")
    assert exc.value.details["reason"] == "credenziali non valide", (
        "a deactivated account must fail identically to a wrong password or unknown "
        "email, or the error itself becomes a way to tell active accounts apart"
    )


def _mean_seconds(action: Callable[[], None], repeats: int = 10) -> float:
    """Average wall-clock time of `action` over `repeats` runs. `action` is expected to
    always raise `ValidationFailed` — that is the behaviour under measurement, not an
    error in the measurement itself."""
    samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        with pytest.raises(ValidationFailed):
            action()
        samples.append(time.perf_counter() - start)
    return statistics.mean(samples)


def test_authenticate_timing_does_not_reveal_whether_the_email_exists(
    db_session: Session,
) -> None:
    """Measured, not deduced. An attacker who can time login attempts must not be able
    to tell 'no such email' apart from 'right email, wrong password' from latency alone.
    Asserted as a ratio of two means, not as absolute milliseconds, so this does not
    flake on a slower or faster machine than whatever ran it last."""
    service = UserService(db_session)
    service.create(
        UserCreate(email="timing@race.it", password="supersegreta1", nome="T", ruolo="admin"),
        ADMIN,
    )

    unknown_email = _mean_seconds(lambda: service.authenticate("nobody@race.it", "whatever12"))
    wrong_password = _mean_seconds(lambda: service.authenticate("timing@race.it", "wrongpass1"))
    ratio = unknown_email / wrong_password

    # Visible with `-s`: real measured numbers for a human reviewing this, not guessed.
    print(
        f"\ntiming: unknown-email={unknown_email * 1000:.1f}ms "
        f"wrong-password={wrong_password * 1000:.1f}ms ratio={ratio:.2f}"
    )
    # Bound is 1.5, not 2.0: hash and verify cost almost exactly the same in argon2, so
    # an unfixed miss path (hash + verify) measures ~1.9-2.05x a hit path (verify only)
    # on this machine across repeated runs -- right on top of a 2.0 boundary, which made
    # that boundary catch the regression in only 1 of 5 trial runs. 1.5 sits with margin
    # on both sides of the two real clusters (~1.0x fixed, ~2.0x broken) instead of on
    # top of one of them.
    assert 0.5 < ratio < 1.5, (
        f"unknown-email path took {unknown_email * 1000:.1f}ms, known-email-wrong-password "
        f"path took {wrong_password * 1000:.1f}ms (ratio {ratio:.2f}) -- response time "
        "leaks whether the email is registered"
    )


def test_duplicate_email_race_past_the_precheck_still_becomes_a_domain_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SELECT-then-INSERT precheck cannot see a row another request commits between
    its own SELECT and its own INSERT -- that gap is exactly what makes it a race. This
    simulates that race deterministically (no threads, no flakiness): force the precheck
    to report "not found" while a real duplicate already exists, so the INSERT hits the
    database's own unique constraint. `create()` must convert that into a domain
    `Conflict`, never let a raw `IntegrityError` escape, and must leave the session
    usable for whatever the caller does next."""
    service = UserService(db_session)
    service.create(
        UserCreate(email="race@conflict.it", password="supersegreta1", nome="R1", ruolo="admin"),
        ADMIN,
    )

    monkeypatch.setattr(service.repo, "get_by_email", lambda email: None)

    with pytest.raises(Conflict) as exc:
        service.create(
            UserCreate(
                email="race@conflict.it", password="supersegreta1", nome="R2", ruolo="admin"
            ),
            ADMIN,
        )
    assert exc.value.details["entity"] == "user"

    # The session must still be usable right after -- a leftover PendingRollbackError
    # would blow up on the very next statement issued on it.
    assert service.count() == 1


def test_case_insensitive_email_uniqueness_is_enforced_by_the_database(
    db_session: Session,
) -> None:
    """Constructs `User` rows directly, bypassing `UserCreate`'s normalising validator,
    so only the database's own constraint can catch a same-email-different-case
    duplicate. A plain `unique=True` on the raw column is case-sensitive and would let
    both rows through silently."""
    db_session.add(
        User(
            email="CaseTest@Example.com",
            password_hash=hash_password("supersegreta1"),
            nome="Case1",
            ruolo="admin",
            attivo=True,
        )
    )
    db_session.commit()

    db_session.add(
        User(
            email="casetest@example.com",
            password_hash=hash_password("supersegreta1"),
            nome="Case2",
            ruolo="admin",
            attivo=True,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_users_email_has_a_case_insensitive_unique_index_in_postgres(
    db_session: Session,
) -> None:
    """Measures the actual database catalog rather than only inferring it from
    behaviour: the previous test would also pass with, say, a `citext` column, an
    application-level lock, or (before the fix) not pass at all for a different reason.
    This pins down the specific mechanism this schema commits to."""
    indexdefs = [
        row[0]
        for row in db_session.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = 'users'")
        ).all()
    ]
    # Postgres renders the functional index with an explicit cast, e.g.
    # "lower((email)::text)" rather than the "lower(email)" written in the model --
    # measured here rather than assumed, matching indexdefs loosely enough to survive
    # that rendering while still requiring a real UNIQUE index over lower(...email...).
    assert any(
        "unique" in d.lower() and "lower(" in d.lower() and "email" in d.lower() for d in indexdefs
    ), indexdefs


# --- Final review item 4 (CRITICAL): UserCreate/UserUpdate.nome had no max_length -
#
# `users.nome` is `String(200)` (auth/models.py). Every other domain's Create/Update
# schema mirrors its own String columns' widths; `UserCreate`/`UserUpdate` predate
# that sweep and were missed until the final review. Without this bound, an
# over-length value sails past Pydantic, reaches flush(), and comes back as a raw
# sqlalchemy.exc.DataError (StringDataRightTruncation) -- not a subclass of
# IntegrityError, so `UserService.create`'s own `except IntegrityError` (guarding the
# email-uniqueness race) does not catch it, and it poisons the session.


def test_nome_over_the_column_width_is_rejected_on_create() -> None:
    with pytest.raises(ValidationError):
        UserCreate(email="x@example.it", password="supersegreta1", nome="x" * (NOME_MAX_LENGTH + 1))


def test_nome_over_the_column_width_is_rejected_on_update() -> None:
    with pytest.raises(ValidationError):
        UserUpdate(nome="x" * (NOME_MAX_LENGTH + 1))


def test_nome_at_the_column_width_is_accepted_on_create() -> None:
    user = UserCreate(email="x@example.it", password="supersegreta1", nome="x" * NOME_MAX_LENGTH)
    assert len(user.nome) == NOME_MAX_LENGTH


def test_a_nul_byte_in_nome_is_rejected_not_stored(db_session: Session) -> None:
    """Same family as the max_length gap above (final review item 1): a NUL byte in
    a native string column reaches Postgres raw unless SafeStr catches it first."""
    with pytest.raises(ValidationError):
        UserCreate(email="y@example.it", password="supersegreta1", nome="Mario\x00Rossi")
