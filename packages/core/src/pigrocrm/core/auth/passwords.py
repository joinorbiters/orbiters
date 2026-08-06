from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


# Computed once, at import time, not per call. hash and verify cost almost exactly the
# same in argon2, so a real hash + a real verify (the old "no such user" path) costs
# about double a verify alone (the "wrong password" path) -- an oracle, just with the
# sign flipped from the classic one. Comparing against this constant instead makes both
# paths cost exactly one verify.
_DUMMY_HASH = hash_password("pigrocrm-constant-time-dummy")


def dummy_hash() -> str:
    """A precomputed constant hash to verify against when no real user exists, so that
    authentication's response time does not reveal whether an email is registered."""
    return _DUMMY_HASH


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        # VerifyMismatchError is a VerificationError subclass, already covered.
        # InvalidHashError (a malformed password_hash value) is not -- add it
        # explicitly so a corrupt stored hash fails closed instead of raising.
        return False
