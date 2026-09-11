"""What leaves the process when a member asks for a link, and what a test sees instead.

The network is the only thing faked, as in `test_conversions.py`: the URL, the header,
the JSON and the failure classification run for real.
"""

import json

from orbiters_core.config import Settings
from orbiters_core.mail import (
    RESEND_URL,
    Mail,
    RecordingSender,
    ResendSender,
    magic_link_mail,
    sender_from_settings,
    welcome_mail,
)

KEY = "re_non_una_chiave_vera"
FROM = "Orbiters <ciao@joinorbiters.com>"


class FakeHttp:
    def __init__(self, status: int = 200, raises: bool = False) -> None:
        self.status = status
        self.raises = raises
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, headers, body))
        if self.raises:
            raise OSError("la rete non c'e'")
        return self.status, b'{"id":"x"}'


def test_resend_posts_one_json_object_with_the_bearer_key() -> None:
    http = FakeHttp()
    sender = ResendSender(KEY, FROM, http=http)
    mail = Mail(to="ada@studio.it", subject="Il tuo accesso a Orbiters", text="ciao")
    assert sender.send(mail) is True
    method, url, headers, body = http.calls[0]
    assert (method, url) == ("POST", RESEND_URL)
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {
        "from": FROM,
        "to": ["ada@studio.it"],
        "subject": "Il tuo accesso a Orbiters",
        "text": "ciao",
    }


def test_resend_sends_the_html_beside_the_text_when_there_is_one() -> None:
    http = FakeHttp()
    mail = Mail(to="ada@studio.it", subject="x", text="ciao", html="<p>ciao</p>")
    assert ResendSender(KEY, FROM, http=http).send(mail) is True
    body = json.loads(http.calls[0][3])
    assert body["text"] == "ciao" and body["html"] == "<p>ciao</p>"


def test_resend_answers_false_and_never_raises_on_any_failure() -> None:
    mail = Mail(to="ada@studio.it", subject="x", text="y")
    assert ResendSender(KEY, FROM, http=FakeHttp(status=422)).send(mail) is False
    assert ResendSender(KEY, FROM, http=FakeHttp(status=500)).send(mail) is False
    assert ResendSender(KEY, FROM, http=FakeHttp(raises=True)).send(mail) is False


def test_the_recording_sender_keeps_what_was_sent() -> None:
    sender = RecordingSender()
    mail = Mail(to="ada@studio.it", subject="x", text="y")
    assert sender.send(mail) is True
    assert sender.sent == [mail]


def test_no_key_means_no_sender() -> None:
    assert sender_from_settings(Settings(_env_file=None)) is None  # type: ignore[call-arg]
    configured = sender_from_settings(
        Settings(resend_api_key=KEY, _env_file=None)  # type: ignore[call-arg]
    )
    assert isinstance(configured, ResendSender)


def test_the_magic_link_mail_carries_the_link_and_how_long_it_lasts() -> None:
    mail = magic_link_mail("ada@studio.it", "https://joinorbiters.com/hub/entra?t=abc", 15)
    assert mail.to == "ada@studio.it"
    assert mail.subject == "Il tuo accesso a Orbiters"
    assert "https://joinorbiters.com/hub/entra?t=abc" in mail.text
    assert "15 minuti" in mail.text
    assert "una volta sola" in mail.text


def test_the_magic_link_mail_has_an_html_version_in_the_landings_system() -> None:
    """The HTML is the landing's box: paper ground, Prussian Blue ink, the four tiles,
    the Watermelon call to action, hard edges. The text version stays the fallback."""
    mail = magic_link_mail("ada@studio.it", "https://joinorbiters.com/hub/entra?t=abc", 15)
    assert mail.html is not None
    html = mail.html
    # The link three times: the button's href, and the bare URL as href and as text for
    # the clients that block buttons.
    assert html.count("https://joinorbiters.com/hub/entra?t=abc") == 3
    assert "Entra nella tua area" in html
    assert "15 minuti" in html and "una volta sola" in html
    # The brand's five values and nothing rounded.
    for colour in ("#f1f2f3", "#011936", "#465362", "#f9dc5c", "#ed254e", "#e5133e"):
        assert colour in html, colour
    assert "border-radius" not in html
    assert 'name="supported-color-schemes"' in html
    assert "Outfit" in html
    assert "Privacy" in html and "Termini" in html
    # Nothing the person typed is interpolated unescaped: the link is the only variable
    # and it is attribute-safe.
    hostile = magic_link_mail("ada@studio.it", 'https://x.it/?t="><script>', 15)
    assert hostile.html is not None and "<script>" not in hostile.html


# ---- the welcome mail (ORB-157) ---------------------------------------------------------

ACCEDI = "https://joinorbiters.com/hub/accedi"


def test_the_welcome_mail_says_how_to_enter_what_waits_inside_and_where_the_jobs_are() -> None:
    mail = welcome_mail(
        "ada@studio.it", "Ada", ACCEDI, completa=True, posizione="Backend developer"
    )
    assert mail.subject == "La tua area su Orbiters è aperta"
    assert mail.text.startswith("Ciao Ada,")
    assert ACCEDI in mail.text and "senza password" in mail.text
    assert "sei Backend developer" in mail.text and "scheda è completa" in mail.text
    assert "PigroCRM, gratis" in mail.text and "I primi passi da freelance" in mail.text
    assert "disponibili dopo il login" in mail.text
    assert "https://www.linkedin.com/company/joinorbiters" in mail.text
    assert "Forward Deployed Engineer" in mail.text


def test_the_welcome_mail_asks_an_incomplete_card_for_the_persons_part() -> None:
    mail = welcome_mail("ada@studio.it", "Ada", ACCEDI, completa=False, posizione="AI Architect")
    assert "quello che si trova in pubblico" in mail.text
    assert "Ti abbiamo segnato come AI Architect." in mail.text
    assert "il CV, la tariffa a giornata" in mail.text
    bare = welcome_mail("ada@studio.it", "Ada", ACCEDI, completa=False, posizione=None)
    assert "segnato come" not in bare.text and "Manca la tua parte" in bare.text


def test_the_welcome_mail_has_the_landings_box_and_escapes_the_persons_words() -> None:
    mail = welcome_mail("ada@studio.it", "<Ada>", ACCEDI, completa=False, posizione="<b>x</b>")
    assert mail.html is not None
    html = mail.html
    assert html.count(ACCEDI) == 3 and "Entra nella tua area" in html
    assert "<Ada>" not in html and "&lt;Ada&gt;" in html
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert 'href="https://www.linkedin.com/company/joinorbiters"' in html
    for colour in ("#f1f2f3", "#011936", "#ed254e", "#e5133e"):
        assert colour in html, colour
    assert "border-radius" not in html and "Privacy" in html
