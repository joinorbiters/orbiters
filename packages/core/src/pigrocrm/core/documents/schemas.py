from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pigrocrm.core.validation import SafeStr

DocumentTipo = Literal["offerta", "contratto", "verbale", "documento"]
OfferState = Literal["bozza", "inviata", "accettata", "rifiutata"]

TITOLO_MAX_LENGTH = 200


class DocumentCreate(BaseModel):
    """`customer_id` and `deal_id` are both optional here and mutually exclusive; the
    service raises `ValidationFailed` when neither or both is given, and the database
    check constraint (`ck_documents_customer_xor_deal`) is the second line under
    concurrency. Task 9 fills in the rest of this module (updates, reads, versions)."""

    customer_id: UUID | None = None
    deal_id: UUID | None = None
    tipo: DocumentTipo = "documento"
    titolo: SafeStr = Field(max_length=TITOLO_MAX_LENGTH)
    stato: OfferState | None = None
    custom_fields: dict[str, Any] = {}
