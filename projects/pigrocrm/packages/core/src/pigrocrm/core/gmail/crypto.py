"""AES-256-GCM for the one secret this slice stores at rest.

Why encrypt at all, when the database belongs to the user: not to protect them from
themselves, but because a dump, a backup, or a `pg_dump` attached to a bug report are
different exposure surfaces from the running system -- and this credential grants
access to a *third-party* account, not merely to this application. The key lives
outside the database. That is the entire point.

Access tokens are never stored, here or anywhere: they live in memory for the duration
of one sync or one send. An access token is valid for an hour; persisting it would add
a second secret to protect for no gain. `storage/gdrive.py` already made that call.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pigrocrm.core.errors import Conflict

# 96 bits, the size AES-GCM is specified for. A longer nonce is hashed down and a
# shorter one narrows the space needlessly.
NONCE_BYTES = 12


def seal(plaintext: str, key: bytes) -> tuple[bytes, bytes]:
    """Returns `(ciphertext, nonce)`. A fresh nonce per call, from `os.urandom`."""
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def unseal(ciphertext: bytes, nonce: bytes, key: bytes) -> str:
    """Raises `Conflict` naming the environment variable and nothing else.

    Never the ciphertext, never the key, never a partial decryption: an authentication
    failure means either the key is wrong or the row was altered, and both are the
    same instruction to the operator. Distinguishing them in the message would leak
    which one, and an oracle on 'is this the right key' is the one thing GCM's
    authenticator exists to withhold.

    `ValueError` is caught alongside `InvalidTag` because a nonce or key of the wrong
    *length* fails there instead -- a distinction that matters to the cipher and not at
    all to the caller, for whom every branch means the same thing: this row cannot be
    read with this key. `from exc` keeps the real cause in the traceback, where an
    operator debugging their own installation can see it, without putting it in the
    message that anything might format on its own.
    """
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise Conflict(
            "google_account",
            "il refresh token memorizzato non è decifrabile: verifica "
            "PIGROCRM_GOOGLE_TOKEN_KEY, oppure ricollega la casella",
        ) from exc
