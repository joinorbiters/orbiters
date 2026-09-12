"""The CRM's outbound mail: a seam, Resend behind it, and the one mail this slice sends."""

from pigrocrm.core.config import Settings
from pigrocrm.core.mail import (
    RESEND_URL,
    Mail,
    RecordingSender,
    ResendSender,
    magic_link_mail,
    sender_from_settings,
    welcome_mail,
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_without_a_key_there_is_no_sender() -> None:
    assert sender_from_settings(_settings()) is None


def test_with_a_key_the_sender_is_resend_with_the_configured_from() -> None:
    sender = sender_from_settings(
        _settings(resend_api_key="re_x", mail_from="PigroCRM <ciao@x.it>")
    )
    assert isinstance(sender, ResendSender)
    assert sender.sender == "PigroCRM <ciao@x.it>"


def test_resend_posts_one_json_object_with_the_key_as_bearer() -> None:
    calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def http(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        calls.append((method, url, headers, body))
        return 200, b"{}"

    sender = ResendSender("re_x", "PigroCRM <ciao@x.it>", http=http)
    assert sender.send(Mail(to="ada@x.it", subject="s", text="t", html="<p>t</p>")) is True
    (method, url, headers, body) = calls[0]
    assert (method, url) == ("POST", RESEND_URL)
    assert headers["Authorization"] == "Bearer re_x"
    assert b'"to": ["ada@x.it"]' in body and b'"html": "<p>t</p>"' in body


def test_resend_never_raises_and_answers_false_on_a_failure() -> None:
    def boom(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        raise OSError("down")

    mail = Mail(to="a@x.it", subject="s", text="t")
    assert ResendSender("re_x", "x", http=boom).send(mail) is False
    assert ResendSender("re_x", "x", http=lambda *a: (500, b"")).send(mail) is False


def test_the_magic_link_mail_carries_every_link_and_the_minutes() -> None:
    mail = magic_link_mail(
        "ada@x.it",
        [
            ("studio-ada", "https://pigro.test/studio-ada/app/entra?t=abc"),
            ("secondo", "https://pigro.test/secondo/app/entra?t=def"),
        ],
        15,
    )
    assert mail.to == "ada@x.it"
    assert "15 minuti" in mail.text
    assert "https://pigro.test/studio-ada/app/entra?t=abc" in mail.text
    assert "https://pigro.test/secondo/app/entra?t=def" in mail.text
    assert mail.html is not None and "studio-ada" in mail.html and "&lt;" not in mail.text
    # One space: no label, just the door.
    one = magic_link_mail("a@x.it", [("x", "https://pigro.test/x/app/entra?t=abc")], 15)
    assert one.text.count("https://pigro.test/x/app/entra?t=abc") == 1 and "x:" not in one.text
    # A token that tried to close the tag is escaped in the HTML.
    hostile = magic_link_mail("a@x.it", [("x", 'https://pigro.test/x/app/entra?t="><script>')], 15)
    assert hostile.html is not None and "<script>" not in hostile.html


def test_the_recording_sender_keeps_what_it_was_given() -> None:
    recording = RecordingSender()
    mail = Mail(to="a@x.it", subject="s", text="t")
    assert recording.send(mail) is True
    assert recording.sent == [mail]


def test_the_welcome_mail_says_where_to_enter_and_what_to_do_first() -> None:
    member = welcome_mail("ada@x.it", "Ada", "https://pigro.test/ada/app/login", membro=True)
    assert member.subject == "Il tuo spazio PigroCRM è pronto"
    assert member.text.startswith("Ciao Ada,")
    assert "https://pigro.test/ada/app/login" in member.text
    assert (
        "assistente" in member.text
        and "dati fiscali" in member.text
        and "primo cliente" in member.text
    )
    assert "joinorbiters.com/hub/freelance" not in member.text
    guest = welcome_mail("bob@x.it", None, "https://pigro.test/bob/app/login", membro=False)
    assert guest.text.startswith("Ciao,")
    assert "joinorbiters.com/hub/freelance" in guest.text
    assert guest.html is not None and "hub/freelance" in guest.html
    hostile = welcome_mail("x@x.it", "<b>Ada</b>", "https://pigro.test/x/app/login", membro=True)
    assert hostile.html is not None and "<b>Ada</b>" not in hostile.html
