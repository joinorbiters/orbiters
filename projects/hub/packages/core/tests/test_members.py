"""The member area: a freelancer's way back in, and what they may change once in."""

import pytest
from pydantic import ValidationError

from orbiters_core.schemas import FreelancerCreate, MemberProfile, MemberUpdate

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
