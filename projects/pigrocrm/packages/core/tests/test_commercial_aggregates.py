"""§4's figures, each from its one stated source.

The two §3 exceptions are here and the tests say so out loud, because an exception that is
not written down is a rule that does not hold. Everything else in this file is a `COUNT` or
a `SUM` over a single table.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from orologio import OGGI_DEL_PROCESSO, OGGI_IN_ITALIA, congela
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.models import Customer
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.deals.repository import DealRepository
from pigrocrm.core.documents.models import Document
from pigrocrm.core.documents.repository import DocumentRepository
from pigrocrm.core.pipeline.models import PipelineStage
from pigrocrm.core.pipeline.service import PipelineService

SEED = Actor(id=None, type="system", role="admin")


@pytest.fixture
def stages(db_session: Session) -> dict[str, Any]:
    PipelineService(db_session).seed_defaults(SEED)
    return {s.code: s for s in PipelineService(db_session).list() if s.code is not None}


@pytest.fixture
def customer(db_session: Session) -> Customer:
    row = Customer(ragione_sociale="Cliente Srl", nazione="IT", custom_fields={})
    db_session.add(row)
    db_session.flush()
    return row


def _deal(
    db_session: Session,
    customer: Customer,
    stage_id: object,
    *,
    valore: str | None = "1000.00",
    probabilita: int = 50,
    chiuso_il: date | None = None,
    data_chiusura_prevista: date | None = None,
) -> Deal:
    row = Deal(
        nome="Impianto",
        customer_id=customer.id,
        pipeline_stage_id=stage_id,
        valore_previsto=Decimal(valore) if valore is not None else None,
        probabilita=probabilita,
        chiuso_il=chiuso_il,
        data_chiusura_prevista=data_chiusura_prevista,
        custom_fields={},
    )
    db_session.add(row)
    db_session.flush()
    return row


def _offerta(
    db_session: Session,
    customer: Customer,
    titolo: str,
    *,
    stato: str = "inviata",
    stato_dal: date | None = date(2026, 3, 1),
) -> Document:
    row = Document(
        customer_id=customer.id,
        tipo="offerta",
        titolo=titolo,
        stato=stato,
        stato_dal=stato_dal,
        versione_corrente=1,
        custom_fields={},
    )
    db_session.add(row)
    db_session.flush()
    return row


# -- pipeline_summary ------------------------------------------------------------


def test_pipeline_summary_groups_open_deals_by_stage(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    _deal(db_session, customer, stages["lead"].id, valore="1000.00")
    _deal(db_session, customer, stages["lead"].id, valore="2000.00")
    _deal(db_session, customer, stages["offerta"].id, valore="500.00")

    rows = {row.stage_code: row for row in DealRepository(db_session).pipeline_summary()}
    assert rows["lead"].numero == 2
    assert rows["lead"].valore_totale == Decimal("3000.00")
    assert rows["offerta"].numero == 1
    assert rows["offerta"].valore_totale == Decimal("500.00")


def test_pipeline_summary_includes_the_closed_stages_last(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """Every configured stage, in `posizione` order, closed ones included.

    It used to be `tipo='open'` only, on the reasoning that a won deal is history and
    not pipeline. The card that reads this then stopped at the last open stage and never
    said where the work ended up, which is the one thing a pipeline exists to answer --
    so since 2026-09-09 the closed stages are returned too, each carrying its
    `stage_tipo` so the renderer can group them by that rather than by a `nome` the user
    is free to rename. What they count is what sits in the stage *today*: there is no
    period filter in this query and never was, and the period question belongs to
    `closed_in_period` on the same card.
    """
    _deal(db_session, customer, stages["vinto"].id)
    _deal(db_session, customer, stages["perso"].id)

    rows = DealRepository(db_session).pipeline_summary()

    per_code = {row.stage_code: row for row in rows}
    assert per_code["vinto"].numero == 1
    assert per_code["perso"].numero == 1
    assert per_code["vinto"].stage_tipo == "won"
    assert per_code["perso"].stage_tipo == "lost"
    # In `posizione` order, which is what puts the two closed stages at the end: the
    # order is the contract, because the card renders the rows as they arrive.
    assert [row.stage_code for row in rows] == sorted(
        per_code, key=lambda code: stages[code].posizione
    )


def test_pipeline_summary_excludes_soft_deleted_deals(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    row = _deal(db_session, customer, stages["lead"].id)
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    summary = {r.stage_code: r for r in DealRepository(db_session).pipeline_summary()}
    assert summary["lead"].numero == 0
    assert summary["lead"].valore_totale == Decimal("0.00")
    # And it is not counted as a deal *without* a value either: it is not a deal here at
    # all. A soft-deleted row leaking into `senza_valore` would inflate the one column
    # whose whole job is to say "these figures are missing something".
    assert summary["lead"].senza_valore == 0


def test_a_deal_without_a_value_is_counted_separately_and_never_summed_as_zero(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """§4's own note. Counting a missing value as zero understates the pipeline and there
    is no way for the reader to tell -- so it is a column of its own."""
    _deal(db_session, customer, stages["lead"].id, valore="1000.00")
    _deal(db_session, customer, stages["lead"].id, valore=None)

    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    assert row.numero == 2
    assert row.senza_valore == 1
    assert row.valore_totale == Decimal("1000.00")


def test_a_stage_with_no_deals_still_appears_with_zeroes(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """A missing stage and an empty stage render identically in a bar chart, and the
    reader cannot tell which they are looking at.

    Every column is asserted, not just the stage's presence: under a LEFT JOIN the empty
    stage still produces one row whose `deals` columns are all `NULL`, so a `senza_valore`
    written as `COUNT(CASE WHEN valore_previsto IS NULL THEN 1 END)` counts that phantom
    row and reports one value-less deal in a stage that has no deals at all.
    """
    rows = {r.stage_code: r for r in DealRepository(db_session).pipeline_summary()}
    assert {"lead", "contattato", "offerta", "negoziazione"} <= set(rows)
    vuoto = rows["negoziazione"]
    assert vuoto.numero == 0
    assert vuoto.senza_valore == 0
    assert vuoto.valore_totale == Decimal("0.00")
    assert vuoto.valore_ponderato == Decimal("0.00")


def test_stages_come_back_in_pipeline_order(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """A pipeline chart whose bars reorder between loads is unreadable.

    The extra stage is created *last* and positioned *first*, so insertion order and
    `posizione` order disagree: an implementation that orders by `id` (or by nothing,
    which in Postgres means whatever the group-by hash produces) puts it at the end and
    fails both assertions.
    """
    db_session.add(
        PipelineStage(nome="Ricontatto", posizione=-1, probabilita_default=5, tipo="open")
    )
    db_session.flush()

    rows = DealRepository(db_session).pipeline_summary()
    assert [row.posizione for row in rows] == sorted(row.posizione for row in rows)
    assert rows[0].stage_nome == "Ricontatto"


# -- the first §3 exception: the weighted value ----------------------------------


def test_the_weighted_value_is_the_product_of_two_columns_of_deals(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """**§3 exception 1.** `Σ ROUND(valore_previsto × probabilita / 100, 2)`. Allowed
    because it combines only columns of `deals` and is not money received; labelled
    *stima* everywhere it appears."""
    _deal(db_session, customer, stages["lead"].id, valore="1000.00", probabilita=50)
    _deal(db_session, customer, stages["lead"].id, valore="333.33", probabilita=33)

    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    # 500.00 + ROUND(109.99890, 2) = 500.00 + 110.00
    assert row.valore_ponderato == Decimal("610.00")
    # And the unweighted total is untouched by the estimate: the two columns are two
    # figures, and the weighted one is never the one added to anything.
    assert row.valore_totale == Decimal("1333.33")


def test_the_weighted_value_rounds_per_row_then_sums(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """`Σ ROUND(row, 2)`, never `ROUND(Σ exact, 2)`, and HALF_UP not HALF_EVEN -- the
    project-wide rule from slice 4. Three rows at 0.005 differ between the two by a cent,
    which is exactly how a reconciliation stops reconciling."""
    for _ in range(3):
        _deal(db_session, customer, stages["lead"].id, valore="0.01", probabilita=50)
    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    # ROUND(0.005, 2) = 0.01 half-up, three times. ROUND(Σ 0.015, 2) would be 0.02, and
    # half-even on either would give 0.00 and 0.02.
    assert row.valore_ponderato == Decimal("0.03")


def test_a_deal_without_a_value_contributes_nothing_to_the_weighted_value(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    _deal(db_session, customer, stages["lead"].id, valore=None, probabilita=90)
    row = next(r for r in DealRepository(db_session).pipeline_summary() if r.stage_code == "lead")
    assert row.valore_ponderato == Decimal("0.00")
    assert row.numero == 1


# -- closed_in_period and the second §3 exception --------------------------------


def test_closed_in_period_counts_won_and_lost_by_chiuso_il(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10), valore="1000.00")
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 20), valore="2000.00")
    _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 15))
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 4, 1))

    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 2
    assert result.persi == 1
    # The lost deal's own 1000.00 is not in here: `valore_vinto` is the value of what was
    # won, not of everything that closed.
    assert result.valore_vinto == Decimal("3000.00")


def test_closed_in_period_ignores_a_soft_deleted_deal(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    row = _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10))
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 0
    assert result.valore_vinto == Decimal("0.00")


def test_the_period_bounds_are_inclusive(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 1))
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 31))
    # One day outside each end, to prove the bounds are bounds and not decoration.
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 2, 28))
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 4, 1))
    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 2


def test_the_conversion_rate_is_a_ratio_of_two_counts(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """**§3 exception 2.** `vinti / (vinti + persi)`, two decimals."""
    for _ in range(3):
        _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10))
    _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 10))

    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.tasso_conversione == Decimal("75.00")


def test_the_conversion_rate_rounds_half_up(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """1 of 32 is 3.125 per cent exactly: 3.13 half-up, 3.12 half-even.

    `Decimal.quantize` defaults to the context's `ROUND_HALF_EVEN`, so a rate quantized
    without naming a mode passes every other test in this file and fails this one. That is
    the whole reason `money.round_money` exists and is used here rather than a local
    `quantize`.
    """
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10))
    for _ in range(31):
        _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 10))

    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 1 and result.persi == 31
    assert result.tasso_conversione == Decimal("3.13")


def test_the_conversion_rate_is_null_when_nothing_closed(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """`null`, not `0`. Zero per cent means "I lost everything"; no closed deals means
    something else. Same rule as slice 4 §7.1's margin percentage, and the *same* rule so
    there is one."""
    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.vinti == 0 and result.persi == 0
    assert result.tasso_conversione is None


def test_the_conversion_rate_is_zero_when_everything_was_lost(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """The other half of the same distinction, which a `null`-only test would not catch."""
    _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 10))
    result = DealRepository(db_session).closed_in_period(date(2026, 3, 1), date(2026, 3, 31))
    assert result.tasso_conversione == Decimal("0.00")


def test_deals_closed_before_the_column_existed_are_reported_not_counted(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """§4.1: `chiuso_il` is not backfilled, so historical closures are unattributable. The
    dashboard says how many rather than counting them as zero or putting them in the wrong
    month -- a guessed conversion rate is plausible and wrong, which is the worst
    combination."""
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=None)
    _deal(db_session, customer, stages["perso"].id, chiuso_il=None)
    _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 10))

    repo = DealRepository(db_session)
    assert repo.closed_in_period(date(2026, 3, 1), date(2026, 3, 31)).vinti == 1
    assert repo.unattributable_closures() == 2


def test_an_open_deal_with_no_chiuso_il_is_not_an_unattributable_closure(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """Nearly every deal in the table is open and has no `chiuso_il`; counting those would
    make the warning meaningless the day it shipped."""
    _deal(db_session, customer, stages["lead"].id, chiuso_il=None)
    assert DealRepository(db_session).unattributable_closures() == 0


def test_expected_closures_counts_open_deals_in_the_window(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    _deal(db_session, customer, stages["lead"].id, data_chiusura_prevista=date(2026, 3, 15))
    _deal(db_session, customer, stages["lead"].id, data_chiusura_prevista=date(2026, 6, 1))
    # A won deal with a future expected date is not an expected closure.
    _deal(
        db_session,
        customer,
        stages["vinto"].id,
        data_chiusura_prevista=date(2026, 3, 20),
        chiuso_il=date(2026, 2, 1),
    )
    # Nor is a deal with no expected date at all, which is most of them.
    _deal(db_session, customer, stages["lead"].id, data_chiusura_prevista=None)

    assert DealRepository(db_session).expected_closures(date(2026, 3, 1), date(2026, 3, 31)) == 1


# -- the documents side ----------------------------------------------------------


def test_pending_offers_carries_the_age_in_days(
    db_session: Session, customer: Customer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The age is the emitter's day minus `stato_dal`, not the database server's.

    The clock is frozen at an instant where Italy and a UTC process disagree about the
    day, so an implementation computing the age from `CURRENT_DATE` -- or from
    `date.today()` on a UTC host -- reports one day less and fails here. Freezing is the
    only way this assertion says anything: against the real clock every candidate
    implementation agrees.
    """
    congela(monkeypatch)
    _offerta(db_session, customer, "Offerta ferma", stato_dal=date(2025, 12, 25))

    rows = DocumentRepository(db_session).pending_offers()
    assert len(rows) == 1
    assert rows[0].titolo == "Offerta ferma"
    assert rows[0].stato_dal == date(2025, 12, 25)
    assert rows[0].giorni == (OGGI_IN_ITALIA - date(2025, 12, 25)).days
    assert rows[0].giorni != (OGGI_DEL_PROCESSO - date(2025, 12, 25)).days


def test_pending_offers_ignores_offers_in_any_other_state(
    db_session: Session, customer: Customer
) -> None:
    for stato in ("bozza", "accettata", "rifiutata"):
        _offerta(db_session, customer, f"Offerta {stato}", stato=stato)
    assert DocumentRepository(db_session).pending_offers() == []


def test_pending_offers_ignores_a_soft_deleted_offer(
    db_session: Session, customer: Customer
) -> None:
    row = _offerta(db_session, customer, "Offerta cestinata")
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    repo = DocumentRepository(db_session)
    assert repo.pending_offers() == []
    assert repo.count_pending_offers() == 0


def test_pending_offers_are_oldest_first_with_unknown_ages_last(
    db_session: Session, customer: Customer
) -> None:
    """Oldest first because the list exists to be acted on from the top, and an offer with
    no known start date is not the oldest one.

    Postgres already puts NULLs last on an ASC sort, so the explicit `nulls_last()` in the
    repository changes nothing today -- this test does not pretend otherwise. What it does
    catch is the direction: reversed, the newest offer leads the list *and* the row with no
    date leads it, because the NULL default flips with the direction.
    """
    _offerta(db_session, customer, "Recente", stato_dal=date(2026, 3, 5))
    _offerta(db_session, customer, "Ignota", stato_dal=None)
    _offerta(db_session, customer, "Antica", stato_dal=date(2026, 3, 1))

    assert [r.titolo for r in DocumentRepository(db_session).pending_offers()] == [
        "Antica",
        "Recente",
        "Ignota",
    ]


def test_the_list_is_truncated_but_the_count_is_the_real_total(
    db_session: Session, customer: Customer
) -> None:
    """A dashboard showing twenty of ninety must say ninety: a truncated list presented as
    the whole is the "partial results without saying so" failure §12 names."""
    for giorno in (1, 2, 3):
        _offerta(db_session, customer, f"Offerta {giorno}", stato_dal=date(2026, 3, giorno))

    repo = DocumentRepository(db_session)
    assert len(repo.pending_offers(limit=2)) == 2
    assert repo.count_pending_offers() == 3


def test_an_offer_with_no_stato_dal_has_a_null_age_rather_than_zero(
    db_session: Session, customer: Customer
) -> None:
    """The backfill covers documents with a `state_changed` in their timeline; one written
    directly by a fixture or an import has none. Zero days would read as "sent today"."""
    _offerta(db_session, customer, "Senza data", stato_dal=None)
    rows = DocumentRepository(db_session).pending_offers()
    assert rows[0].giorni is None
    assert rows[0].stato_dal is None


def test_the_signal_counts_accepted_offers_whose_deal_is_not_won(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """§6.2's first signal, and the permanent cross-check on automation A1: if the
    automation goes quiet, this count speaks. A `COUNT` across a join, which §3 permits --
    a `SUM` across one it does not."""
    open_deal = _deal(db_session, customer, stages["lead"].id)
    won_deal = _deal(db_session, customer, stages["vinto"].id, chiuso_il=date(2026, 3, 1))
    lost_deal = _deal(db_session, customer, stages["perso"].id, chiuso_il=date(2026, 3, 1))
    for deal, titolo in (
        (open_deal, "Da sistemare"),
        (won_deal, "A posto"),
        # A lost deal with an accepted offer is the same inconsistency as an open one: the
        # offer was accepted and the deal says otherwise.
        (lost_deal, "Anche questa"),
    ):
        db_session.add(
            Document(
                deal_id=deal.id,
                tipo="offerta",
                titolo=titolo,
                stato="accettata",
                stato_dal=date(2026, 3, 1),
                versione_corrente=1,
                custom_fields={},
            )
        )
    db_session.flush()

    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 2


def test_the_signal_ignores_an_offer_that_was_never_accepted(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    """An offer still out for signature on an open deal is the normal case, not a signal."""
    deal = _deal(db_session, customer, stages["lead"].id)
    db_session.add(
        Document(
            deal_id=deal.id,
            tipo="offerta",
            titolo="Ancora in attesa",
            stato="inviata",
            stato_dal=date(2026, 3, 1),
            versione_corrente=1,
            custom_fields={},
        )
    )
    db_session.flush()
    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 0


def test_the_signal_ignores_an_accepted_offer_with_no_deal(
    db_session: Session, customer: Customer
) -> None:
    """An offer attached to a customer has no deal to be won, so it is not an
    inconsistency."""
    _offerta(db_session, customer, "Senza deal", stato="accettata")
    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 0


def test_the_signal_ignores_a_soft_deleted_deal(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    deal = _deal(db_session, customer, stages["lead"].id)
    deal.deleted_at = datetime.now(UTC)
    db_session.add(
        Document(
            deal_id=deal.id,
            tipo="offerta",
            titolo="Deal archiviato",
            stato="accettata",
            stato_dal=date(2026, 3, 1),
            versione_corrente=1,
            custom_fields={},
        )
    )
    db_session.flush()
    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 0


def test_the_signal_ignores_a_soft_deleted_offer(
    db_session: Session, customer: Customer, stages: dict[str, Any]
) -> None:
    deal = _deal(db_session, customer, stages["lead"].id)
    offer = Document(
        deal_id=deal.id,
        tipo="offerta",
        titolo="Offerta cestinata",
        stato="accettata",
        stato_dal=date(2026, 3, 1),
        versione_corrente=1,
        custom_fields={},
        deleted_at=datetime.now(UTC),
    )
    db_session.add(offer)
    db_session.flush()
    assert DocumentRepository(db_session).count_accepted_with_unwon_deal() == 0
