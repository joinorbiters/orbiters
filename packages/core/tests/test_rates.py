"""§5.1's resolution order and, more importantly, §5's guarantee: what happens to last
quarter's margin when you raise a rate today. The answer must be "nothing", and not
out of discipline -- by construction, because no report ever reads a rate column."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User
from pigrocrm.core.deals.models import Deal
from pigrocrm.core.money import line_value
from pigrocrm.core.timetracking.models import TimeEntry
from pigrocrm.core.timetracking.rates import RateResolver


def _set_deal_rate(db_session: Session, deal_id: UUID, value: Decimal | None) -> None:
    db_session.get(Deal, deal_id).tariffa_oraria = value
    db_session.flush()


def _set_user_rates(
    db_session: Session, user_id: UUID, tariffa: Decimal | None, costo: Decimal | None
) -> None:
    user = db_session.get(User, user_id)
    user.tariffa_oraria_default = tariffa
    user.costo_orario_default = costo
    db_session.flush()


def test_an_explicit_value_wins_and_is_marked_manuale(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, Decimal("120.000000"), Decimal("40.000000"))
    resolved = RateResolver(db_session).resolve(
        deal_id=seeded_deal_id,
        user_id=seeded_user_id,
        tariffa_esplicita=Decimal("99.500000"),
        costo_esplicito=Decimal("10.250000"),
    )
    assert resolved.tariffa == Decimal("99.500000")
    assert resolved.tariffa_origine == "manuale"
    assert resolved.costo == Decimal("10.250000")
    assert resolved.costo_origine == "manuale"


def test_the_deal_rate_is_level_two(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, Decimal("120.000000"), Decimal("40.000000"))
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert (resolved.tariffa, resolved.tariffa_origine) == (Decimal("150.000000"), "deal")
    # The internal cost has no deal level at all: it is a property of who works the
    # hour, not of the client they work it for. So it falls to the user level here.
    assert (resolved.costo, resolved.costo_origine) == (Decimal("40.000000"), "utente")


def test_the_user_default_is_level_three(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, None)
    _set_user_rates(db_session, seeded_user_id, Decimal("120.000000"), Decimal("40.000000"))
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert (resolved.tariffa, resolved.tariffa_origine) == (Decimal("120.000000"), "utente")


def test_nothing_resolves_to_none_never_to_zero(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """No global default and no silent fall back to zero. A `0.00` would say "this
    work was free", which is a lie that sums; a global default would be a number
    nobody chose quietly becoming everybody's rate."""
    _set_deal_rate(db_session, seeded_deal_id, None)
    _set_user_rates(db_session, seeded_user_id, None, None)
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert resolved.tariffa is None and resolved.tariffa_origine == "assente"
    assert resolved.costo is None and resolved.costo_origine == "assente"


def test_costo_origine_is_never_deal(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """A consequence to read off the table, not a coincidence: `costo_origine`'s
    possible values are `manuale`, `utente`, `assente` and nothing else."""
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, None, None)
    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert resolved.costo_origine == "assente"


def test_an_explicit_zero_is_a_choice_and_survives(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """`0` is a value, never a blank -- the same rule the frontend's `isBlank` follows.
    Somebody writing 0.000000 is declaring free work on purpose, and the resolver must
    not fall through to a deal rate behind their back."""
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    resolved = RateResolver(db_session).resolve(
        deal_id=seeded_deal_id, user_id=seeded_user_id, tariffa_esplicita=Decimal("0.000000")
    )
    assert resolved.tariffa == Decimal("0.000000")
    assert resolved.tariffa_origine == "manuale"


def test_describe_answers_before_anything_is_written(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    _set_deal_rate(db_session, seeded_deal_id, Decimal("150.000000"))
    _set_user_rates(db_session, seeded_user_id, None, Decimal("40.000000"))
    described = RateResolver(db_session).describe(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert described.tariffa == Decimal("150.000000")
    assert described.tariffa_origine == "deal"
    assert described.costo == Decimal("40.000000")
    assert described.costo_origine == "utente"


def test_raising_a_rate_today_does_not_move_an_already_written_entrys_value(
    db_session: Session, seeded_deal_id: UUID, seeded_user_id: UUID
) -> None:
    """The slice's central guarantee, proved by breaking it rather than asserted in
    prose: an entry logged at last quarter's rate freezes that rate onto the row
    (`tariffa_applicata`), the same way `TimeEntryService` (Task 4A-9) will. Raising
    the deal's rate today must not move a margin already computed from that frozen
    column -- and this test also computes what *would* happen under the design that
    was rejected (re-resolving the rate live at read time instead of freezing it),
    to show the two disagree. If the freeze were ever removed and reads went back to
    `RateResolver.resolve()` at report time, the first assertion below would fail."""
    _set_deal_rate(db_session, seeded_deal_id, Decimal("100.000000"))
    _set_user_rates(db_session, seeded_user_id, None, None)

    resolved = RateResolver(db_session).resolve(deal_id=seeded_deal_id, user_id=seeded_user_id)
    assert (resolved.tariffa, resolved.tariffa_origine) == (Decimal("100.000000"), "deal")

    entry = TimeEntry(
        deal_id=seeded_deal_id,
        user_id=seeded_user_id,
        data=date(2026, 3, 10),
        ore=Decimal("8.00"),
        descrizione="Analisi effettuata lo scorso trimestre",
        tariffa_applicata=resolved.tariffa,
        tariffa_origine=resolved.tariffa_origine,
    )
    db_session.add(entry)
    db_session.flush()

    frozen_value_last_quarter = line_value(entry.ore, entry.tariffa_applicata)
    assert frozen_value_last_quarter == Decimal("800.00")

    # The rate change this test is about: raised well after the entry was written.
    _set_deal_rate(db_session, seeded_deal_id, Decimal("250.000000"))

    # The guarantee: the row's own frozen value is untouched by the later change.
    db_session.refresh(entry)
    assert entry.tariffa_applicata == Decimal("100.000000")
    assert line_value(entry.ore, entry.tariffa_applicata) == frozen_value_last_quarter

    # The design that was rejected, made concrete: re-resolving live instead of
    # reading the frozen column moves the same entry's value purely because time
    # passed and an unrelated write happened -- exactly what §5's guarantee forbids.
    re_resolved_today = RateResolver(db_session).resolve(
        deal_id=seeded_deal_id, user_id=seeded_user_id
    )
    naive_recomputed_value = line_value(entry.ore, re_resolved_today.tariffa)
    assert naive_recomputed_value == Decimal("2000.00")
    assert naive_recomputed_value != frozen_value_last_quarter
