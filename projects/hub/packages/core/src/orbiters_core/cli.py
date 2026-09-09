"""`orbiters`: the operator's commands."""

import argparse
import getpass
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from orbiters_core.admin import AdminService
from orbiters_core.config import get_settings
from orbiters_core.conversions import pixel_from_settings
from orbiters_core.db import create_engine_from_settings, session_factory
from orbiters_core.errors import DomainError


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
    args = parser.parse_args(argv)
    if args.command == "conversions-check":
        return conversions_check()
    if args.command == "createadmin":
        return createadmin(args.email, args.nome)
    parser.error(f"comando sconosciuto: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
