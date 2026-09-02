"""The §16 reference corpus, and the inflated variant criterion 3 needs.

Two scales, one generator. The reference scale is ten years of a five-person practice;
the inflated one brings every searched table to 50 000 rows, because an assertion about
a query plan means nothing on a table that fits in a handful of pages -- Postgres picks
a sequential scan there because it *is* the cheapest plan, and a test asserting
otherwise would go red without a defect.

Rows are inserted with `session.execute(insert(Model), [dicts])` rather than through the
ORM: at 50 000 rows per table the unit-of-work overhead is the difference between a test
that runs and a test nobody runs. `flush()` is called, never `commit()` -- the caller's
transaction owns the lifetime, which is what lets `db_session` roll the whole corpus
back.

Determinism is by seed, not by luck. `random.Random(seed)` is instantiated locally and
never the module-level `random` functions, so a concurrent test that seeds the global
generator cannot change what this one produces.

A module rather than a fixture: three sub-plans and six test files need it, at two
scales, and `INFLATED` takes long enough that a function callable once from a
session-scoped fixture is the only affordable shape.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from pigrocrm.core.customers.models import Customer
from pigrocrm.core.db.base import uuid7
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.documents.models import Document
from pigrocrm.core.people.models import Person
from pigrocrm.core.pipeline.models import PipelineStage

# The one customer every search test looks for. Both values are deliberately ordinary:
# a VAT number whose middle five digits ("34567") are a realistic fragment to type, and
# a company name whose first four characters ("Ross") are a realistic prefix.
KNOWN_PARTITA_IVA = "01234567890"
KNOWN_RAGIONE_SOCIALE = "Rossi Ingegneria Srl"

_SURNAMES = (
    "Rossi",
    "Bianchi",
    "Ferrari",
    "Russo",
    "Esposito",
    "Colombo",
    "Ricci",
    "Marino",
    "Greco",
    "Bruno",
    "Gallo",
    "Conti",
    "De Luca",
    "Costa",
    "Giordano",
    "Mancini",
    "Rizzo",
    "Lombardi",
    "Moretti",
    "Barbieri",
)
_FIRST_NAMES = (
    "Marco",
    "Giulia",
    "Luca",
    "Chiara",
    "Andrea",
    "Sara",
    "Matteo",
    "Elena",
    "Francesco",
    "Alessia",
    "Davide",
    "Martina",
    "Simone",
    "Federica",
    "Alessandro",
    "Valentina",
)
_SECTORS = (
    "Ingegneria",
    "Consulenza",
    "Logistica",
    "Impianti",
    "Servizi",
    "Costruzioni",
    "Informatica",
    "Trasporti",
    "Manutenzioni",
    "Progettazione",
)
_LEGAL_FORMS = ("Srl", "Spa", "Snc", "Sas", "Srls")
_DEAL_WORDS = (
    "Rifacimento",
    "Ampliamento",
    "Adeguamento",
    "Collaudo",
    "Fornitura",
    "Revisione",
    "Migrazione",
    "Assistenza",
    "Ristrutturazione",
    "Certificazione",
)
_DOC_WORDS = ("Offerta", "Contratto", "Verbale", "Relazione", "Preventivo", "Capitolato")

# `customers.partita_iva` is String(11) and the known customer already owns
# "01234567890", so the generated ones start above it and can never collide with it
# however large `scale.customers` grows -- 10_000_000_000 + 50_000 is still 11 digits.
_GENERATED_PIVA_BASE = 10_000_000_000


@dataclass(frozen=True)
class CorpusScale:
    customers: int
    people: int
    deals: int
    documents: int


REFERENCE = CorpusScale(customers=500, people=800, deals=2000, documents=1000)
INFLATED = CorpusScale(customers=50_000, people=50_000, deals=50_000, documents=50_000)


@dataclass(frozen=True)
class CorpusIds:
    stage_open_id: UUID
    stage_won_id: UUID
    stage_lost_id: UUID
    customer_ids: list[UUID] = field(default_factory=list)
    deal_ids: list[UUID] = field(default_factory=list)


def _stages(session: Session) -> tuple[UUID, UUID, UUID]:
    """Three stages, resolved by `code` and created only if absent.

    By `code`, never by `nome`: `PipelineStage`'s own docstring gives the reason, and a
    corpus that deduplicated on the renamable label would create a second "Vinto" the
    moment a test renamed the first one. The three codes are a subset of
    `pipeline/service.py::DEFAULT_STAGES`, so a corpus built after `seed_defaults` has
    run reuses those rows instead of tripping `uq_pipeline_stage_code`.
    """
    wanted = (
        ("offerta", "Offerta", 2, 50, "open"),
        ("vinto", "Vinto", 4, 100, "won"),
        ("perso", "Perso", 5, 0, "lost"),
    )
    ids: list[UUID] = []
    for code, nome, posizione, probabilita, tipo in wanted:
        existing = session.scalar(select(PipelineStage).where(PipelineStage.code == code))
        if existing is None:
            existing = PipelineStage(
                code=code,
                nome=nome,
                posizione=posizione,
                probabilita_default=probabilita,
                tipo=tipo,
            )
            session.add(existing)
            session.flush()
        ids.append(existing.id)
    return ids[0], ids[1], ids[2]


def build_corpus(session: Session, scale: CorpusScale, *, seed: int = 20260821) -> CorpusIds:
    rng = random.Random(seed)
    stage_open, stage_won, stage_lost = _stages(session)

    customer_ids: list[UUID] = []
    customer_rows: list[dict[str, object]] = []
    for index in range(scale.customers):
        cid = uuid7()
        customer_ids.append(cid)
        if index == 0:
            ragione, piva = KNOWN_RAGIONE_SOCIALE, KNOWN_PARTITA_IVA
        else:
            ragione = (
                f"{rng.choice(_SURNAMES)} {rng.choice(_SECTORS)} {rng.choice(_LEGAL_FORMS)} {index}"
            )
            piva = str(_GENERATED_PIVA_BASE + index)
        customer_rows.append(
            {
                "id": cid,
                "ragione_sociale": ragione[:255],
                "partita_iva": piva,
                # Exactly 16 characters, which is what `codice_fiscale` is sized for.
                "codice_fiscale": f"CF{index:014d}",
                "email": f"info{index}@{rng.choice(_SECTORS).lower()}.example",
                "nazione": "IT",
                "stato": rng.choice(("attivo", "prospect", None)),
                "custom_fields": {},
            }
        )
    session.execute(insert(Customer), customer_rows)

    person_rows: list[dict[str, object]] = []
    for index in range(scale.people):
        # Every fifth person has no surname: `people.cognome` is nullable, and Task A3's
        # NULLS LAST cursor has no exerciser without rows in the null tail.
        cognome = None if index % 5 == 0 else rng.choice(_SURNAMES)
        person_rows.append(
            {
                "id": uuid7(),
                "customer_id": customer_ids[index % len(customer_ids)],
                "nome": rng.choice(_FIRST_NAMES),
                "cognome": cognome,
                "email": f"persona{index}@example.it",
                "custom_fields": {},
            }
        )
    session.execute(insert(Person), person_rows)

    deal_ids: list[UUID] = []
    deal_rows: list[dict[str, object]] = []
    for index in range(scale.deals):
        did = uuid7()
        deal_ids.append(did)
        stage = (stage_open, stage_won, stage_lost)[index % 3]
        # Every seventh deal has no expected value. Task B9 counts these under
        # "senza valore" and never sums them as zero.
        #
        # `Decimal`, not the string the brief proposed: `deals.valore_previsto` is
        # Numeric(12, 2), and money is never a float anywhere in this codebase.
        valore = None if index % 7 == 0 else Decimal(f"{1000 + index % 90000}.00")
        deal_rows.append(
            {
                "id": did,
                "nome": f"{rng.choice(_DEAL_WORDS)} {rng.choice(_SECTORS)} {index}",
                "customer_id": customer_ids[index % len(customer_ids)],
                "pipeline_stage_id": stage,
                "valore_previsto": valore,
                "probabilita": (index % 11) * 10,
                "custom_fields": {},
            }
        )
    session.execute(insert(Deal), deal_rows)

    document_rows: list[dict[str, object]] = []
    for index in range(scale.documents):
        # `ck_documents_customer_xor_deal`: exactly one of the two, never both.
        owner_is_deal = index % 2 == 0
        document_rows.append(
            {
                "id": uuid7(),
                "customer_id": None if owner_is_deal else customer_ids[index % len(customer_ids)],
                "deal_id": deal_ids[index % len(deal_ids)] if owner_is_deal else None,
                "tipo": "offerta" if index % 3 == 0 else "documento",
                "titolo": f"{rng.choice(_DOC_WORDS)} {rng.choice(_SECTORS)} {index}",
                # `documents.stato` is meaningful only for `tipo = 'offerta'` and NULL
                # for every other type -- the model's own docstring says so.
                "stato": "inviata" if index % 3 == 0 else None,
                "versione_corrente": 1,
                "custom_fields": {},
            }
        )
    session.execute(insert(Document), document_rows)

    session.flush()
    return CorpusIds(
        stage_open_id=stage_open,
        stage_won_id=stage_won,
        stage_lost_id=stage_lost,
        customer_ids=customer_ids,
        deal_ids=deal_ids,
    )
