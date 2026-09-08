"""Attachments come from `document_version_id` and from nowhere else.

The thing anyone actually wants to attach is the offer's PDF -- slice 2 explicitly
deferred sending the offer to this slice -- and going through the document means going
through the layer that already has the authorisation, the hash and the versioning. A
free-form upload in the composer would be a second route for bytes to enter the system,
with a second authorisation to write and a second place for it to be wrong.

The size cap is checked **before** anything is fetched or composed, and that ordering is
the whole of spec 13 criterion 11. Gmail refuses above 25 MB, and its refusal arrives
mid-upload as a message nobody can act on; ours arrives before the first byte leaves the
backend, and it says what the attachments weigh and what the limit is.

Nothing here logs, and nothing that leaves this module names a document title or a
storage key: a title is usually a client's name and a key is a path into the backend.
The caller already knows which version ids it passed, which is all an error needs to say.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.documents.models import Document, DocumentVersion
from pigrocrm.core.documents.schemas import ALLOWED_CONTENT_TYPES
from pigrocrm.core.documents.service import slugify_folder
from pigrocrm.core.errors import NotFound, ValidationFailed
from pigrocrm.core.gmail.rfc822 import OutgoingAttachment
from pigrocrm.core.storage.base import DocumentStorage

ENTITY = "email_draft"
FIELD = "attachment_version_ids"
_MB = 1024 * 1024


def _refuse_total(total: int, max_bytes: int) -> None:
    raise ValidationFailed(
        ENTITY,
        FIELD,
        f"gli allegati pesano {total / _MB:.1f} MB, il limite è {max_bytes / _MB:.0f} MB",
        expected=f"totale non oltre {max_bytes / _MB:.0f} MB",
    )


def resolve_attachments(
    session: Session,
    storage: DocumentStorage,
    version_ids: Sequence[UUID],
    *,
    max_bytes: int,
) -> tuple[OutgoingAttachment, ...]:
    """Names the files, weighs them, and only then reads them.

    Three passes on purpose, in this order:

    1. resolve every id to a row, so an unknown id is a `NotFound` naming the id rather
       than a half-built message;
    2. add up the *recorded* sizes and refuse an oversized total -- no fetch, no payload,
       nothing composed;
    3. read the bytes, and weigh them again.

    Step 3's second weighing is not redundant. `dimensione` is metadata: no constraint
    ties it to what the storage backend actually holds, so a stale or simply wrong row
    would walk an oversized payload straight past the only guard there is. Step 2 is the
    cheap check and step 3 is the true one; dropping either loses something real.
    """
    if not version_ids:
        # The overwhelmingly common case. Worth the branch so a plain mail costs neither
        # a query nor a round trip to storage.
        return ()

    rows: list[tuple[DocumentVersion, Document]] = []
    for version_id in version_ids:
        row = session.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id == version_id)
        ).one_or_none()
        if row is None:
            raise NotFound("document_version", version_id)
        rows.append((row[0], row[1]))

    declared = sum(version.dimensione for version, _ in rows)
    if declared > max_bytes:
        _refuse_total(declared, max_bytes)

    resolved: list[OutgoingAttachment] = []
    total = 0
    for version, document in rows:
        extension = ALLOWED_CONTENT_TYPES.get(version.content_type)
        if extension is None:
            # The allowlist is the authority in both directions. A row carrying a type it
            # does not contain has no extension we can honestly give the file, and
            # guessing one is how an executable arrives looking like a document.
            raise ValidationFailed(
                ENTITY,
                FIELD,
                "un allegato ha un tipo di file non ammesso",
                expected=", ".join(sorted(ALLOWED_CONTENT_TYPES)),
            )

        # `storage.get` raises `NotFound("document_blob", key)` on a dangling key, which
        # is exactly right and is left to propagate: an email carrying a 0-byte PDF would
        # reach the recipient as a broken file with nobody able to say why.
        content = storage.get(version.storage_key)
        total += len(content)
        if total > max_bytes:
            _refuse_total(total, max_bytes)

        resolved.append(
            OutgoingAttachment(
                # The same three pieces `DocumentService.download` assembles, and for the
                # same reason: the title is user input on its way into a MIME header, so
                # it is slugified, and the extension comes from the recorded type rather
                # than being assumed to be `.pdf`.
                filename=f"{slugify_folder(document.titolo)}-v{version.numero}{extension}",
                mime=version.content_type,
                content=content,
            )
        )

    return tuple(resolved)
