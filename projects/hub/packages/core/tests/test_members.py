"""The member area: a freelancer's way back in, and what they may change once in."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from orbiters_core.comments import CommentService
from orbiters_core.config import Settings
from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.freelancers import FreelancerService
from orbiters_core.members import MemberService
from orbiters_core.models import Freelancer, MagicLinkToken, MemberSession
from orbiters_core.schemas import FreelancerCreate, MemberProfile, MemberUpdate, StatusChange

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"

GOOD = {
    "nome": "Ada",
    "cognome": "Lovelace",
    "linkedin_url": "https://www.linkedin.com/in/ada",
    "tariffa_giornaliera": "450",
    "posizione": "Backend developer",
    "remoto": "remoto",
    "links": ["https://github.com/ada", " "],
}


def test_member_update_applies_the_wizards_rules_and_nothing_else() -> None:
    update = MemberUpdate(**GOOD)
    assert update.links == ["https://github.com/ada"]
    for bad in (
        {**GOOD, "linkedin_url": "http://www.linkedin.com/in/ada"},
        {**GOOD, "tariffa_giornaliera": "0"},
        {**GOOD, "posizione": "   "},
        {**GOOD, "remoto": "da casa"},
        {**GOOD, "links": ["ftp://x.it"]},
        {**GOOD, "email": "ada@studio.it"},
        {**GOOD, "stato": "attivo"},
    ):
        with pytest.raises(ValidationError):
            MemberUpdate(**bad)
    # The wizard still accepts what it accepted: the base class changed, the rules did not.
    assert FreelancerCreate(**GOOD, email="ada@studio.it").links == ["https://github.com/ada"]


def test_member_profile_carries_no_admin_field() -> None:
    fields = set(MemberProfile.model_fields)
    assert {"nome", "cognome", "email", "cv_filename", "cv_size", "links"} <= fields
    assert not fields & {"stato", "note", "utm_source", "utm_campaign", "cv_bytes"}


@pytest.fixture
def members(hub_engine: Engine, hub_session: Session) -> MemberService:
    settings = Settings(
        database_url=hub_engine.url.render_as_string(hide_password=False),
        hub_url="http://localhost:5180/hub",
        _env_file=None,  # type: ignore[call-arg]
    )
    yield MemberService(hub_session, settings)  # type: ignore[misc]
    hub_session.rollback()
    for table in ("member_sessions", "magic_link_tokens", "comments", "freelancers"):
        hub_session.execute(text(f"DELETE FROM {table}"))
    hub_session.commit()


def _apply(session: Session, email: str = "ada@studio.it") -> UUID:
    return (
        FreelancerService(session)
        .apply(FreelancerCreate(**GOOD, email=email), PDF, "Ada CV.pdf", "application/pdf")
        .id
    )


def _token_from(mail_text: str) -> str:
    match = re.search(r"/entra\?t=([A-Za-z0-9_-]+)", mail_text)
    assert match, mail_text
    return match.group(1)


def test_a_link_is_written_only_for_an_address_that_applied(
    members: MemberService, hub_session: Session
) -> None:
    assert members.request_link("nessuno@studio.it") is None
    assert hub_session.scalar(select(MagicLinkToken)) is None

    _apply(hub_session)
    mail = members.request_link("  ADA@studio.it ")
    assert mail is not None and mail.to == "ada@studio.it"
    assert "http://localhost:5180/hub/entra?t=" in mail.text
    row = hub_session.scalar(select(MagicLinkToken))
    assert row is not None and row.used_at is None
    assert row.token_hash != _token_from(mail.text) and len(row.token_hash) == 64


def test_a_link_opens_a_session_once_and_never_twice(
    members: MemberService, hub_session: Session
) -> None:
    _apply(hub_session)
    mail = members.request_link("ada@studio.it")
    assert mail is not None
    raw = _token_from(mail.text)

    outcome = members.enter(raw)
    assert outcome is not None
    profile, session_token = outcome
    assert profile.email == "ada@studio.it"
    assert members.resolve(session_token) is not None
    assert members.enter(raw) is None, "a spent link opens nothing"
    assert members.enter("non-un-token-vero-ma-lungo-abbastanza") is None
    assert members.enter("") is None


def test_an_expired_link_opens_nothing_and_is_swept_by_the_next_request(
    members: MemberService, hub_session: Session
) -> None:
    _apply(hub_session)
    mail = members.request_link("ada@studio.it")
    assert mail is not None
    row = hub_session.scalar(select(MagicLinkToken))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    hub_session.commit()
    assert members.enter(_token_from(mail.text)) is None

    members.request_link("ada@studio.it")
    tokens = hub_session.scalars(select(MagicLinkToken)).all()
    assert len(tokens) == 1 and tokens[0].id != row.id


def test_a_member_session_is_hashed_sliding_and_closable(
    members: MemberService, hub_session: Session
) -> None:
    _apply(hub_session)
    mail = members.request_link("ada@studio.it")
    assert mail is not None
    outcome = members.enter(_token_from(mail.text))
    assert outcome is not None
    _, raw = outcome
    row = hub_session.scalar(select(MemberSession))
    assert row is not None and row.token_hash != raw and len(row.token_hash) == 64
    row.expires_at = row.expires_at - timedelta(days=1)
    hub_session.commit()
    before = row.expires_at
    assert members.resolve(raw) is not None
    hub_session.refresh(row)
    assert row.expires_at > before

    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    hub_session.commit()
    assert members.resolve(raw) is None
    assert hub_session.scalar(select(MemberSession)) is None

    outcome = members.enter(_token_from(members.request_link("ada@studio.it").text))  # type: ignore[union-attr]
    assert outcome is not None
    members.close_session(outcome[1])
    assert members.resolve(outcome[1]) is None
    assert members.resolve(None) is None


def test_an_update_changes_the_row_and_leaves_one_comment_naming_what_moved(
    members: MemberService, hub_session: Session
) -> None:
    freelancer_id = _apply(hub_session)
    FreelancerService(hub_session).set_status(
        freelancer_id, StatusChange(stato="contattato", note="da sentire")
    )

    unchanged = members.update(freelancer_id, MemberUpdate(**GOOD))
    assert unchanged.tariffa_giornaliera == Decimal("450")
    assert CommentService(hub_session).list("freelancer", freelancer_id) == []

    changed = members.update(
        freelancer_id,
        MemberUpdate(**{**GOOD, "tariffa_giornaliera": "500", "links": []}),
    )
    assert changed.tariffa_giornaliera == Decimal("500") and changed.links == []
    thread = CommentService(hub_session).list("freelancer", freelancer_id)
    assert len(thread) == 1
    assert thread[0].testo == "Profilo aggiornato dalla persona: tariffa giornaliera, link"
    assert thread[0].autore == "Ada Lovelace"

    admin_view = FreelancerService(hub_session).get(freelancer_id)
    assert (admin_view.stato, admin_view.note) == ("contattato", "da sentire")


def test_a_new_cv_is_checked_like_the_wizards_and_leaves_its_comment(
    members: MemberService, hub_session: Session
) -> None:
    freelancer_id = _apply(hub_session)
    with pytest.raises(ValidationFailed) as refused:
        members.replace_cv(freelancer_id, b"non un pdf", "cv.pdf", "application/pdf")
    assert refused.value.details["field"] == "cv"

    new_pdf = PDF + b"\n% versione 2\n"
    profile = members.replace_cv(freelancer_id, new_pdf, "Ada 2026.pdf", "application/pdf")
    assert (profile.cv_filename, profile.cv_size) == ("Ada 2026.pdf", len(new_pdf))
    assert members.cv(freelancer_id).content == new_pdf
    thread = CommentService(hub_session).list("freelancer", freelancer_id)
    assert [comment.testo for comment in thread] == ["CV aggiornato dalla persona"]


def test_a_row_that_is_not_there_is_not_found(members: MemberService) -> None:
    missing = UUID("00000000-0000-7000-8000-000000000000")
    with pytest.raises(NotFound):
        members.profile(missing)
    with pytest.raises(NotFound):
        members.update(missing, MemberUpdate(**GOOD))


# ---- completing a card an admin wrote from a signup (ORB-155) -------------------------


def _draft_card(session: Session, email: str = "ada@studio.it") -> UUID:
    from orbiters_core.schemas import FreelancerDraft, SignupCreate
    from orbiters_core.service import SignupService

    signup = SignupService(session).subscribe(
        SignupCreate(email=email, nome="Ada", cognome="Lovelace")
    )
    draft = FreelancerDraft(
        nome="Ada",
        cognome="Lovelace",
        posizione="Backend developer",
        fonti=["https://www.linkedin.com/in/ada"],
    )
    return FreelancerService(session).draft_from_signup(signup.id, draft, "Claude").id


def test_an_incomplete_card_reads_as_such_and_has_no_cv_to_download(
    members: MemberService, hub_session: Session
) -> None:
    freelancer_id = _draft_card(hub_session)
    profile = members.profile(freelancer_id)
    assert profile.completa is False
    assert (profile.cv_filename, profile.tariffa_giornaliera, profile.remoto) == (None, None, None)
    with pytest.raises(NotFound):
        members.cv(freelancer_id)


def test_the_person_completes_the_card_and_takes_it_over(
    members: MemberService, hub_session: Session
) -> None:
    freelancer_id = _draft_card(hub_session)
    after_answers = members.update(freelancer_id, MemberUpdate(**GOOD))
    assert after_answers.completa is False  # the CV is still missing
    after_cv = members.replace_cv(freelancer_id, PDF, "Ada CV.pdf", "application/pdf")
    assert after_cv.completa is True and after_cv.cv_filename == "Ada CV.pdf"
    row = hub_session.scalar(select(Freelancer).where(Freelancer.id == freelancer_id))
    assert row is not None and row.compilata_da == "persona"
    texts = [c.testo for c in CommentService(hub_session).list("freelancer", freelancer_id)]
    assert texts[0] == "CV caricato dalla persona"
    assert texts[1].startswith("Profilo aggiornato dalla persona: ")
    assert "tariffa giornaliera" in texts[1] and "modalità di lavoro" in texts[1]


def test_confirming_a_researched_card_unchanged_still_makes_it_the_persons(
    members: MemberService, hub_session: Session
) -> None:
    freelancer_id = _draft_card(hub_session)
    members.update(
        freelancer_id,
        MemberUpdate(**{**GOOD, "linkedin_url": None, "links": []}),
    )
    # Nothing but the rate and the remote option moved the first time; the second call
    # sends the very same answers, and the card still says «persona» afterwards.
    row = hub_session.scalar(select(Freelancer).where(Freelancer.id == freelancer_id))
    assert row is not None
    row.compilata_da = "admin"
    hub_session.commit()
    members.update(freelancer_id, MemberUpdate(**{**GOOD, "linkedin_url": None, "links": []}))
    hub_session.refresh(row)
    assert row.compilata_da == "persona"
    texts = [c.testo for c in CommentService(hub_session).list("freelancer", freelancer_id)]
    assert texts[0] == "Scheda confermata dalla persona"


# ---- who entered, and when (ORB-158) ----------------------------------------------------


def test_entering_is_recorded_and_the_card_and_the_stats_read_it_back(
    members: MemberService, hub_session: Session
) -> None:
    from orbiters_core.logins import LoginService

    ada = _apply(hub_session, "ada@studio.it")
    _apply(hub_session, "bob@studio.it")
    before = LoginService(hub_session).stats()
    assert (before.totale, before.membri, before.membri_totali) == (0, 0, 2)
    assert FreelancerService(hub_session).get(ada).accessi == 0

    for _ in range(2):
        mail = members.request_link("ada@studio.it")
        assert mail is not None
        assert members.enter(_token_from(mail.text)) is not None
    # A spent link and a wrong token open nothing, so they record nothing either.
    assert members.enter("non-un-token-vero-ma-lungo-abbastanza") is None

    card = FreelancerService(hub_session).get(ada)
    assert card.accessi == 2 and card.ultimo_accesso is not None
    listed = {item.email: item for item in FreelancerService(hub_session).list_recent().items}
    assert listed["ada@studio.it"].accessi == 2
    assert listed["bob@studio.it"].accessi == 0 and listed["bob@studio.it"].ultimo_accesso is None

    stats = LoginService(hub_session).stats()
    assert (stats.totale, stats.membri, stats.membri_totali, stats.ultimi_7_giorni) == (2, 1, 2, 2)
    assert [login.email for login in stats.recenti] == ["ada@studio.it", "ada@studio.it"]
    assert stats.recenti[0].logged_at >= stats.recenti[1].logged_at
    assert stats.recenti[0].freelancer_id == ada
