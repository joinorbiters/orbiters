"""`orbiters`: the operator's commands."""

import argparse
import getpass
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from orbiters_core.admin import AdminService
from orbiters_core.config import Settings, get_settings
from orbiters_core.conversions import pixel_from_settings
from orbiters_core.db import create_engine_from_settings, session_factory
from orbiters_core.errors import DomainError
from orbiters_core.mail import CardSummary, EmailSender, sender_from_settings, welcome_mail
from orbiters_core.models import Freelancer, Signup


def createadmin(email: str | None, nome: str | None) -> int:
    """`orbiters createadmin`: the first (or another) reader of the admin area.

    The password is read from a prompt, or from stdin when there is no terminal -- so a
    deploy script can pipe it -- and never from an argument, which would leave it in the
    shell history and in `ps`.
    """
    settings = get_settings()
    email = email or input("Email: ")
    nome = nome or input("Nome: ")
    password = (
        getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
    )
    session = session_factory(create_engine_from_settings(settings))()
    try:
        created = AdminService(session, settings).create(email, nome, password)
    except DomainError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    finally:
        session.close()
    print(f"Amministratore creato: {created.email}")
    return 0


def conversions_check() -> int:
    """`orbiters conversions-check`: does the Conversions API key work?

    Sends one event with `validate_only: true`, which asks OpenAI to check it and record
    nothing. The real events are deliberately invisible -- sent from a background task,
    never logged -- so a wrong key would mean a campaign with no conversions and no sign
    anywhere that the key was the reason. This is how somebody finds out in ten seconds.
    Prints the status and nothing else: the key is never echoed.
    """
    settings = get_settings()
    pixel = pixel_from_settings(settings)
    if pixel is None:
        print(
            "Nessun pixel configurato: servono ORBITERS_OPENAI_PIXEL_ID e "
            "ORBITERS_OPENAI_CONVERSIONS_API_KEY.",
            file=sys.stderr,
        )
        return 1
    outcome = pixel.send(
        # A validation-only event needs an id like any other, and this one must not look
        # like a conversion in case the flag is ever ignored.
        event_id=f"verifica-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        source_url=settings.signup_url,
        validate_only=True,
    )
    if outcome.sent:
        print(f"La chiave funziona: evento validato ({outcome.status}), niente registrato.")
        return 0
    print(
        f"OpenAI ha rifiutato la verifica: {outcome.status} {outcome.detail}".strip(),
        file=sys.stderr,
    )
    return 1


def send_welcome(
    session: Session, settings: Settings, sender: EmailSender, emails: Sequence[str] | None
) -> list[tuple[str, str]]:
    """One welcome mail per address the hub knows (ORB-157): every signup and every card,
    or the addresses given. The voice follows what we hold for the address: a card the
    person filled, a card we drafted from public sources, or no card at all (the wizard,
    then). Answers one line per address -- `inviata` with the kind, or `rifiutata dal
    provider` -- which is the whole record of the mailing."""
    cards = {
        row.email.lower(): row
        for row in session.scalars(
            select(Freelancer).order_by(Freelancer.created_at, Freelancer.id)
        ).all()
    }
    signups = {
        row.email.lower(): row
        for row in session.scalars(select(Signup).order_by(Signup.created_at, Signup.id)).all()
    }
    if emails is not None:
        targets = [email.strip().lower() for email in emails]
    else:
        targets = list(dict.fromkeys([*signups, *cards]))
    base = settings.hub_url.rstrip("/")
    accedi, wizard = f"{base}/accedi", f"{base}/freelance"
    outcomes: list[tuple[str, str]] = []
    for email in targets:
        card = cards.get(email)
        signup = signups.get(email)
        if card is None and signup is None:
            outcomes.append((email, "indirizzo sconosciuto"))
            continue
        if card is not None and card.compilata_da == "persona":
            kind = "persona"
            mail = welcome_mail(card.email, card.nome, accedi, kind=kind, posizione=card.posizione)
        elif card is not None:
            kind = "admin"
            mail = welcome_mail(
                card.email,
                card.nome,
                accedi,
                kind=kind,
                summary=CardSummary(
                    nome=card.nome,
                    cognome=card.cognome,
                    posizione=card.posizione,
                    linkedin_url=card.linkedin_url,
                    links=tuple(card.links),
                ),
            )
        else:
            assert signup is not None
            kind = "nessuna"
            mail = welcome_mail(signup.email, signup.nome, accedi, kind=kind, wizard_link=wizard)
        sent = sender.send(mail)
        outcomes.append((email, f"inviata ({kind})" if sent else "rifiutata dal provider"))
    return outcomes


def welcome(emails: Sequence[str], everyone: bool) -> int:
    """`orbiters welcome --email a@b.it [--email ...]` or `orbiters welcome --all`."""
    if everyone == bool(emails):
        print("Serve --all oppure almeno un --email, non entrambi.", file=sys.stderr)
        return 2
    settings = get_settings()
    sender = sender_from_settings(settings)
    if sender is None:
        print("Nessuna chiave per la posta: serve ORBITERS_RESEND_API_KEY.", file=sys.stderr)
        return 1
    session = session_factory(create_engine_from_settings(settings))()
    try:
        outcomes = send_welcome(session, settings, sender, None if everyone else emails)
    finally:
        session.close()
    for email, outcome in outcomes:
        print(f"{email}: {outcome}")
    return 0 if all(outcome.startswith("inviata") for _, outcome in outcomes) else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orbiters")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "conversions-check",
        help="Verifica la chiave della Conversions API senza registrare una conversione",
    )
    admin = sub.add_parser("createadmin", help="Crea un amministratore dell'area admin")
    admin.add_argument("--email")
    admin.add_argument("--nome")
    welcome_parser = sub.add_parser(
        "welcome",
        help="Manda la mail «la tua area è aperta» a un indirizzo o a tutti quelli noti",
    )
    welcome_parser.add_argument("--email", action="append", default=[])
    welcome_parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "conversions-check":
        return conversions_check()
    if args.command == "createadmin":
        return createadmin(args.email, args.nome)
    if args.command == "welcome":
        return welcome(args.email, args.all)
    parser.error(f"comando sconosciuto: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
