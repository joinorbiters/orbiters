"""The two wizards' rows: what is kept, what is refused, what an admin may change."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from orbiters_core.companies import CompanyService
from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.freelancers import FreelancerService, check_cv
from orbiters_core.models import CV_MAX_BYTES
from orbiters_core.schemas import (
    CompanyCreate,
    FreelancerCreate,
    FreelancerDraft,
    SignupUtm,
    StatusChange,
)

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _application(email: str = "ada@studio.it", **extra: object) -> FreelancerCreate:
    payload: dict[str, object] = {
        "nome": "Ada",
        "cognome": "Lovelace",
        "email": email,
        "tariffa_giornaliera": Decimal("450.00"),
        "posizione": "Backend developer",
        "remoto": "remoto",
        "links": ["https://github.com/ada"],
    }
    payload.update(extra)
    return FreelancerCreate(**payload)  # type: ignore[arg-type]


@pytest.fixture
def clean(hub_session: Session) -> Session:
    yield hub_session  # type: ignore[misc]
    hub_session.rollback()
    hub_session.execute(text("DELETE FROM comments"))
    hub_session.execute(text("DELETE FROM freelancers"))
    hub_session.execute(text("DELETE FROM companies"))
    hub_session.commit()


def test_an_application_is_stored_with_its_cv_and_read_back_without_the_bytes(
    clean: Session,
) -> None:
    service = FreelancerService(clean)
    read = service.apply(
        _application(utm=SignupUtm(utm_source="linkedin")), PDF, "Ada CV.pdf", "application/pdf"
    )
    assert read.email == "ada@studio.it"
    assert (read.cv_filename, read.cv_mime, read.cv_size) == (
        "Ada CV.pdf",
        "application/pdf",
        len(PDF),
    )
    assert read.tariffa_giornaliera == Decimal("450.00")
    assert read.links == ["https://github.com/ada"]
    assert read.stato == "nuovo" and read.utm_source == "linkedin"
    assert "cv_bytes" not in type(read).model_fields
    cv = service.cv(read.id)
    assert (cv.filename, cv.mime, cv.content) == ("Ada CV.pdf", "application/pdf", PDF)


def test_a_second_application_from_the_same_address_corrects_the_first(clean: Session) -> None:
    service = FreelancerService(clean)
    first = service.apply(_application(), PDF, "cv.pdf", "application/pdf")
    service.set_status(first.id, StatusChange(stato="contattato", note="ha risposto"))
    again = service.apply(
        _application(
            email="ADA@studio.it", posizione="Tech lead", tariffa_giornaliera=Decimal("600")
        ),
        PDF + b"v2",
        "cv-2.pdf",
        "application/pdf",
    )
    assert again.id == first.id
    assert (again.posizione, again.tariffa_giornaliera, again.cv_filename) == (
        "Tech lead",
        Decimal("600.00"),
        "cv-2.pdf",
    )
    # What the admin wrote survives what the person corrected.
    assert (again.stato, again.note) == ("contattato", "ha risposto")
    assert clean.execute(text("SELECT count(*) FROM freelancers")).scalar() == 1


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", "serve il CV"),
        (b"not a pdf at all", "deve essere un PDF"),
        (b"%PDF-" + b"x" * CV_MAX_BYTES, "al massimo 5 MB"),
    ],
)
def test_a_cv_that_is_not_a_small_pdf_is_refused_naming_the_field(
    content: bytes, reason: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_cv(content, "cv.pdf", "application/pdf")
    assert refused.value.details["field"] == "cv"
    assert reason in refused.value.details["reason"]


def test_the_filename_keeps_only_its_last_segment() -> None:
    name, mime = check_cv(PDF, "..\\..\\etc\\Ada.pdf", "application/octet-stream")
    assert (name, mime) == ("Ada.pdf", "application/pdf")


@pytest.mark.parametrize(
    "bad",
    [
        {"tariffa_giornaliera": Decimal("0")},
        {"tariffa_giornaliera": Decimal("100000")},
        {"remoto": "quando capita"},
        {"links": ["http://insecure.example/x"]},
        {"links": ["https://ok.example/" + "x" * 300]},
        {"links": [f"https://l{i}.example/" for i in range(11)]},
        {"posizione": "   "},
        {"linkedin_url": "https://example.com/ada"},
        {"nome": "Ada‮"},
    ],
)
def test_an_application_outside_the_form_is_refused_before_the_database(
    bad: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _application(**bad)


def test_links_are_trimmed_and_blank_ones_dropped() -> None:
    assert _application(links=["  https://ada.dev/ ", "", "   "]).links == ["https://ada.dev/"]


def test_the_list_is_newest_first_filters_by_state_and_counts_the_whole(clean: Session) -> None:
    service = FreelancerService(clean)
    ids = [
        service.apply(_application(email=f"p{i}@studio.it"), PDF, "cv.pdf", "").id for i in range(3)
    ]
    service.set_status(ids[0], StatusChange(stato="scartato"))
    page = service.list_recent(limit=2)
    assert page.totale == 3 and [item.id for item in page.items] == [ids[2], ids[1]]
    only_new = service.list_recent(stato="nuovo")
    assert only_new.totale == 2 and {item.id for item in only_new.items} == {ids[1], ids[2]}


def test_a_state_outside_the_four_is_refused_and_a_missing_row_is_not_found(clean: Session) -> None:
    service = FreelancerService(clean)
    row = service.apply(_application(), PDF, "cv.pdf", "")
    with pytest.raises(ValidationFailed):
        service.set_status(row.id, StatusChange(stato="forse"))
    with pytest.raises(NotFound):
        service.get(uuid4())


def test_a_company_request_is_a_row_every_time(clean: Session) -> None:
    service = CompanyService(clean)
    data = CompanyCreate(
        nome_azienda="ACME Srl",
        referente="Wile E.",
        email="Wile@ACME.it",
        progetto="Serve un backend developer\nper tre mesi, da settembre.",
        periodo_da=date(2026, 10, 1),
        durata="3 mesi",
        budget_giornaliero=Decimal("500"),
    )
    first = service.request(data)
    second = service.request(data)
    assert first.id != second.id
    assert first.email == "wile@acme.it"
    assert "\n" in first.progetto
    assert service.list_recent().totale == 2
    moved = service.set_status(first.id, StatusChange(stato="in_corso", note="  "))
    assert (moved.stato, moved.note) == ("in_corso", None)
    with pytest.raises(ValidationFailed):
        service.set_status(first.id, StatusChange(stato="aperto"))


@pytest.mark.parametrize(
    "bad",
    [
        {"progetto": "   "},
        {"progetto": "ok\x00"},
        {"budget_giornaliero": Decimal("-1")},
        {"nome_azienda": ""},
    ],
)
def test_a_company_request_outside_the_form_is_refused(bad: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "nome_azienda": "ACME Srl",
        "referente": "Wile E.",
        "email": "wile@acme.it",
        "progetto": "Un progetto",
        "periodo_da": date(2026, 10, 1),
        "durata": "3 mesi",
        "budget_giornaliero": Decimal("500"),
    }
    payload.update(bad)
    with pytest.raises(ValidationError):
        CompanyCreate(**payload)  # type: ignore[arg-type]


# ---- a card born from a signup (ORB-155) ---------------------------------------------


def _signup(session: Session, email: str = "ada@studio.it", **extra: object) -> UUID:
    from orbiters_core.schemas import SignupCreate
    from orbiters_core.service import SignupService

    payload: dict[str, object] = {"email": email, "nome": "Ada", "cognome": "Lovelace"}
    payload.update(extra)
    read = SignupService(session).subscribe(SignupCreate(**payload))  # type: ignore[arg-type]
    return read.id


def _draft(**extra: object) -> FreelancerDraft:
    payload: dict[str, object] = {
        "nome": "Ada",
        "cognome": "Lovelace",
        "linkedin_url": "https://www.linkedin.com/in/ada",
        "posizione": "Backend developer",
        "links": ["https://github.com/ada"],
        "fonti": ["https://www.linkedin.com/in/ada", "https://ada.dev"],
    }
    payload.update(extra)
    return FreelancerDraft(**payload)  # type: ignore[arg-type]


def test_a_draft_needs_a_source_and_takes_only_https_ones() -> None:
    assert _draft().tariffa_giornaliera is None and _draft().remoto is None
    for bad in ({"fonti": []}, {"fonti": ["http://ada.dev"]}, {"posizione": "   "}):
        with pytest.raises(ValidationError):
            _draft(**bad)


def test_a_card_from_a_signup_is_incomplete_and_carries_the_signup_attribution(
    clean: Session,
) -> None:
    signup_id = _signup(clean, utm=SignupUtm(utm_source="openai"))
    read = FreelancerService(clean).draft_from_signup(signup_id, _draft(), "Claude")
    assert read.email == "ada@studio.it" and read.utm_source == "openai"
    assert read.compilata_da == "admin" and read.completa is False
    assert (read.cv_filename, read.cv_size, read.tariffa_giornaliera, read.remoto) == (
        None,
        None,
        None,
        None,
    )
    assert read.posizione == "Backend developer" and read.links == ["https://github.com/ada"]
    assert read.stato == "nuovo"
    assert len(read.commenti) == 1
    comment = read.commenti[0]
    assert comment.autore == "Claude"
    assert comment.testo.startswith("Scheda creata dall'iscrizione del ")
    assert "https://www.linkedin.com/in/ada" in comment.testo and "https://ada.dev" in comment.testo
    # «Iscrizioni» can now point at it.
    from orbiters_core.service import SignupService

    item = SignupService(clean).list_recent().iscrizioni[0]
    assert item.freelancer_id == read.id


def test_a_second_research_replaces_the_researched_fields_and_leaves_the_admins(
    clean: Session,
) -> None:
    service = FreelancerService(clean)
    signup_id = _signup(clean)
    first = service.draft_from_signup(signup_id, _draft(), "Claude")
    service.set_status(first.id, StatusChange(stato="contattato", note="chiamata fatta"))
    again = service.draft_from_signup(
        signup_id, _draft(posizione="CTO", fonti=["https://ada.dev/about"]), "Claude"
    )
    assert again.id == first.id
    assert again.posizione == "CTO"
    assert (again.stato, again.note) == ("contattato", "chiamata fatta")
    assert again.commenti[0].testo.startswith("Scheda aggiornata dalla ricerca.")
    assert len(again.commenti) == 2


def test_research_never_overwrites_a_card_the_person_filled(clean: Session) -> None:
    service = FreelancerService(clean)
    service.apply(_application(), PDF, "Ada CV.pdf", "application/pdf")
    signup_id = _signup(clean)
    with pytest.raises(ValidationFailed) as refused:
        service.draft_from_signup(signup_id, _draft(posizione="CTO"), "Claude")
    assert refused.value.details["field"] == "email"
    assert service.list_recent().items[0].posizione == "Backend developer"


def test_a_draft_on_an_unknown_signup_is_not_found(clean: Session) -> None:
    with pytest.raises(NotFound):
        FreelancerService(clean).draft_from_signup(uuid4(), _draft(), "Claude")


def test_the_wizard_takes_over_a_researched_card(clean: Session) -> None:
    service = FreelancerService(clean)
    signup_id = _signup(clean)
    drafted = service.draft_from_signup(signup_id, _draft(), "Claude")
    assert drafted.compilata_da == "admin"
    applied = service.apply(_application(), PDF, "Ada CV.pdf", "application/pdf")
    assert applied.id == drafted.id
    assert applied.compilata_da == "persona" and applied.completa is True


def test_a_card_without_a_cv_has_none_to_download(clean: Session) -> None:
    service = FreelancerService(clean)
    drafted = service.draft_from_signup(_signup(clean), _draft(), "Claude")
    with pytest.raises(NotFound) as missing:
        service.cv(drafted.id)
    assert missing.value.details["entity"] == "cv"
