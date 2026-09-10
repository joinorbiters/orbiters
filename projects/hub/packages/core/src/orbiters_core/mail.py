"""Outbound mail: a seam, one provider, and the one text the hub sends today.

The seam exists so tests never send and production never guesses: `sender_from_settings`
answers `None` without a key, and the API turns that into a 503 sentence rather than a
mail that does not arrive. Like `conversions.py`, nothing here raises past `send` and
nothing logs an address or the key.
"""

import json
from dataclasses import dataclass
from typing import Protocol

from orbiters_core.config import Settings
from orbiters_core.http import HttpCall, urllib_call

RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class Mail:
    """Plain text only: a login link needs no HTML, and plain text is what arrives."""

    to: str
    subject: str
    text: str


class EmailSender(Protocol):
    def send(self, mail: Mail) -> bool:
        """`True` when the provider accepted it. Never raises."""
        ...


class RecordingSender:
    """Keeps every mail in a list. For tests, and for reading the link in development."""

    def __init__(self) -> None:
        self.sent: list[Mail] = []

    def send(self, mail: Mail) -> bool:
        self.sent.append(mail)
        return True


class ResendSender:
    """Resend's `POST /emails`: one JSON object, the key as a bearer token."""

    def __init__(self, api_key: str, sender: str, http: HttpCall | None = None) -> None:
        self.api_key = api_key
        self.sender = sender
        self.http = http or urllib_call

    def send(self, mail: Mail) -> bool:
        payload = json.dumps(
            {"from": self.sender, "to": [mail.to], "subject": mail.subject, "text": mail.text}
        ).encode()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            status, _ = self.http("POST", RESEND_URL, headers, payload)
        except Exception:  # noqa: BLE001 - the seam's contract is "never raises"
            return False
        return 200 <= status < 300


def sender_from_settings(settings: Settings) -> EmailSender | None:
    if not settings.resend_api_key:
        return None
    return ResendSender(settings.resend_api_key, settings.mail_from)


def magic_link_mail(to: str, link: str, minutes: int) -> Mail:
    """The one mail the hub sends: the link, how long it lasts, and that ignoring it is
    fine. In the voice of `docs/design/positioning.md`."""
    text = (
        "Ciao,\n"
        "\n"
        "questo è il link per entrare nella tua area su Orbiters:\n"
        "\n"
        f"{link}\n"
        "\n"
        f"Vale {minutes} minuti e funziona una volta sola. Se non l'hai chiesto tu, ignora "
        "questa mail: non succede niente.\n"
        "\n"
        "Noi di Orbiters\n"
    )
    return Mail(to=to, subject="Il tuo accesso a Orbiters", text=text)
