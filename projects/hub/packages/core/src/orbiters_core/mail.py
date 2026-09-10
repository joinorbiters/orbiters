"""Outbound mail: a seam, one provider, and the one mail the hub sends today.

The seam exists so tests never send and production never guesses: `sender_from_settings`
answers `None` without a key, and the API turns that into a 503 sentence rather than a
mail that does not arrive. Like `conversions.py`, nothing here raises past `send` and
nothing logs an address or the key.

The HTML version is the landing's visual system (`projects/website/src/landing.css`)
translated into what mail clients render: tables, inline styles, the five brand values
written out because a mail has no stylesheet to read them from, and none of the things
Gmail and Outlook drop (gradients, box shadows, web fonts). The plain text stays beside
it as the fallback and as what every test reads.
"""

import html as html_escape
import json
from dataclasses import dataclass
from typing import Protocol

from orbiters_core.config import Settings
from orbiters_core.http import HttpCall, urllib_call

RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class Mail:
    """The text is required and is what arrives everywhere; the HTML, when there is one,
    is the same words in the landing's box for the clients that render it."""

    to: str
    subject: str
    text: str
    html: str | None = None


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
        body: dict[str, object] = {
            "from": self.sender,
            "to": [mail.to],
            "subject": mail.subject,
            "text": mail.text,
        }
        if mail.html is not None:
            body["html"] = mail.html
        payload = json.dumps(body).encode()
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


# ---- the landing's box, as a mail --------------------------------------------------------
#
# `shared/brand/palette.css` is the source of these six values; a mail cannot read a
# stylesheet, so they are written out here and `test_mail.py` pins them.
PAPER = "#f1f2f3"
INK = "#011936"
INK_QUIET = "#465362"
ROYAL_GOLD = "#f9dc5c"
WATERMELON = "#ed254e"
# White on raw Watermelon fails the body-text contrast floor; the landing's `.cta` uses
# this darker step for the same reason (`--color-watermelon-strong`).
CTA = "#e5133e"
FONT = "Outfit, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Arial, sans-serif"
# The landing's stepped shadow: the border colour, moved 8px right and down. A mail
# client draws no box-shadow, so the step is a cell of ink behind the card.
STEP = 8
# Every layout table in a mail is this: no spacing, no borders of its own, invisible to
# a screen reader.
TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'
SITE = "https://joinorbiters.com"


def _quiet_link(href: str, label: str) -> str:
    return f'<a href="{href}" style="color:{INK_QUIET};text-decoration:underline;">{label}</a>'


def _tile(colour: str) -> str:
    size = "width:10px;height:10px;line-height:0;font-size:0;"
    return f'<td width="10" height="10" bgcolor="{colour}" style="{size}">&nbsp;</td>'


def _mark() -> str:
    """The four tiles, in `shared/brand/mark.ts` order: ink, royal gold, watermelon, ink."""
    return (
        f'<table {TABLE} style="border-collapse:collapse;">'
        f"<tr>{_tile(INK)}{_tile(ROYAL_GOLD)}</tr>"
        f"<tr>{_tile(WATERMELON)}{_tile(INK)}</tr>"
        "</table>"
    )


def _button(href: str, label: str) -> str:
    """The landing's `.cta`: a filled rectangle, hard edges, white text at weight 500."""
    text = f"font-family:{FONT};font-size:17px;font-weight:500;color:#ffffff;"
    # The padding sits on the cell as well as on the anchor: Outlook's engine ignores
    # `display:inline-block` on a link and would shrink the box to the text.
    cell = (
        f'bgcolor="{CTA}" style="background-color:{CTA};border:2px solid {CTA};padding:14px 24px;"'
    )
    return (
        f'<table {TABLE} style="border-collapse:collapse;">'
        f"<tr><td {cell}>"
        f'<a href="{href}" style="display:inline-block;{text}text-decoration:none;">{label}</a>'
        "</td></tr></table>"
    )


def _frame(title: str, body: str) -> str:
    """The landing's card around `body` (already HTML): paper ground, the mark and the
    name, a white box with a 2px ink border and the 8px step, the fine footer."""
    ground = f'bgcolor="{PAPER}" style="background-color:{PAPER};"'
    name = f"font-family:{FONT};font-size:18px;font-weight:500;color:{INK};"
    step = f'bgcolor="{INK}" style="background-color:{INK};padding:0 {STEP}px {STEP}px 0;"'
    card = f'bgcolor="#ffffff" style="background-color:#ffffff;border:2px solid {INK};"'
    copy = f"font-family:{FONT};font-size:17px;font-weight:400;line-height:1.6;color:{INK};"
    fine = f"font-family:{FONT};font-size:13px;line-height:1.6;color:{INK_QUIET};"
    gap = "&nbsp;&nbsp;&nbsp;"
    footer = gap.join(
        (
            _quiet_link(f"{SITE}/", "Orbiters"),
            _quiet_link(f"{SITE}/privacy", "Privacy"),
            _quiet_link(f"{SITE}/termini", "Termini"),
        )
    )
    return "\n".join(
        (
            "<!DOCTYPE html>",
            '<html lang="it">',
            '<head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            # Both, or Apple Mail and Outlook.com invert the brand colours in dark mode.
            '<meta name="color-scheme" content="light">',
            '<meta name="supported-color-schemes" content="light">',
            f"<title>{html_escape.escape(title)}</title></head>",
            f'<body style="margin:0;padding:0;background-color:{PAPER};">',
            f'<table {TABLE} width="100%" {ground}>',
            '<tr><td align="center" style="padding:32px 16px 40px 16px;">',
            f'<table {TABLE} width="560" style="width:560px;max-width:100%;">',
            '<tr><td style="padding:0 0 20px 0;">',
            f"<table {TABLE}><tr>",
            f'<td valign="middle" style="padding-right:10px;">{_mark()}</td>',
            f'<td valign="middle" style="{name}">Orbiters</td>',
            "</tr></table>",
            "</td></tr>",
            f"<tr><td {step}>",
            f'<table {TABLE} width="100%" {card}>',
            f'<tr><td style="padding:36px 36px 32px 36px;{copy}">',
            body,
            "</td></tr></table>",
            "</td></tr>",
            f'<tr><td style="padding:24px 0 0 0;{fine}">{footer}</td></tr>',
            "</table>",
            "</td></tr></table>",
            "</body></html>",
        )
    )


def magic_link_mail(to: str, link: str, minutes: int) -> Mail:
    """The one mail the hub sends: the link, how long it lasts, and that ignoring it is
    fine. In the voice of `docs/design/positioning.md`, as text and as the landing's box."""
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
    # The link is the only variable and it goes into an attribute and into text: escaped
    # both times, so a token that is not ours cannot close the tag it sits in.
    safe_link = html_escape.escape(link, quote=True)
    paragraph = 'style="margin:24px 0 0 0;"'
    small = f'style="margin:24px 0 0 0;font-size:13px;line-height:1.5;color:{INK_QUIET};'
    body = "\n".join(
        (
            '<p style="margin:0 0 20px 0;">Ciao,</p>',
            '<p style="margin:0 0 24px 0;">'
            "questo è il link per entrare nella tua area su Orbiters.</p>",
            _button(safe_link, "Entra nella tua area"),
            f'<p {small}word-break:break-all;">'
            "Se il bottone non si apre, copia questo indirizzo nel browser:<br>"
            f"{_quiet_link(safe_link, safe_link)}</p>",
            f"<p {paragraph}>Vale {minutes} minuti e funziona una volta sola. "
            "Se non l'hai chiesto tu, ignora questa mail: non succede niente.</p>",
            f"<p {paragraph}>Noi di Orbiters</p>",
        )
    )
    return Mail(
        to=to,
        subject="Il tuo accesso a Orbiters",
        text=text,
        html=_frame("Il tuo accesso a Orbiters", body),
    )
