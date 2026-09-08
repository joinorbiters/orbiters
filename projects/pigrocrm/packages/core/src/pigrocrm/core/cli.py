import argparse
import getpass
import sys

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.errors import DomainError


def createadmin(email: str | None, nome: str | None) -> int:
    """Bootstrap the first administrator. There is no default account and no known
    default password — the direct lesson from Acme's hardcoded credentials."""
    email = email or input("Email: ").strip()
    nome = nome or input("Nome: ").strip()
    password = _read_password("Password: ")
    if sys.stdin.isatty() and password != getpass.getpass("Conferma password: "):
        print("Le password non coincidono.", file=sys.stderr)
        return 1

    engine = create_engine_from_settings(get_settings())
    with session_factory(engine)() as session:
        service = UserService(session)
        try:
            user = service.create(
                UserCreate(email=email, password=password, nome=nome, ruolo="admin"),
                Actor.system(),
            )
        except DomainError as exc:
            # A short password is the single most likely first mistake a new operator
            # will make with this tool; a raw traceback here is a bad first impression.
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Creato amministratore {user.email}")
    return 0


def _read_password(prompt: str) -> str:
    """From the terminal when there is one, hidden; from stdin when there is not.

    `getpass` needs a tty and raises `EOFError` without one -- which is what happens
    inside `docker compose exec` without `-t`, and in any shell that pipes into this.
    The non-tty branch reads one line, so `echo "$PW" | pigrocrm resetpassword --email x`
    works from a script the operator controls; the password still never appears on a
    command line or in `ps`."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return sys.stdin.readline().rstrip("\n")


def resetpassword(email: str | None) -> int:
    """`pigrocrm resetpassword --email chi@dove.it`: a new password for an account that
    exists. The product has no e-mail flow for this on purpose; the operator at the
    server is the reset."""
    email = email or input("Email: ").strip()
    password = _read_password("Nuova password: ")
    if sys.stdin.isatty() and password != getpass.getpass("Conferma password: "):
        print("Le password non coincidono.", file=sys.stderr)
        return 1

    engine = create_engine_from_settings(get_settings())
    with session_factory(engine)() as session:
        try:
            user = UserService(session).reset_password(email, password, Actor.system())
        except DomainError as exc:
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Password aggiornata per {user.email}")
    return 0


def seed_templates() -> int:
    """`pigrocrm seed-templates`. Idempotent, so it is safe on every deploy -- which is
    the point: the timesheet template has to exist before anyone presses Scarica, and
    requiring a manual step there is how a feature ships broken."""
    from pigrocrm.core.actor import Actor
    from pigrocrm.core.config import get_settings
    from pigrocrm.core.db import create_engine_from_settings, session_factory
    from pigrocrm.core.templates.service import TemplateService

    with session_factory(create_engine_from_settings(get_settings()))() as session:
        created = TemplateService(session).seed_defaults(Actor.system())
    for template in created:
        print(f"creato: {template.nome} ({template.tipo})")
    if not created:
        print("nessun template da creare: sono già presenti")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="pigrocrm")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("createadmin", help="Crea il primo utente amministratore")
    admin.add_argument("--email")
    admin.add_argument("--nome")
    reset = sub.add_parser("resetpassword", help="Imposta una nuova password a un utente esistente")
    reset.add_argument("--email")
    sub.add_parser("seed-templates", help="Crea i template predefiniti, se mancano")

    args = parser.parse_args()
    if args.command == "createadmin":
        return createadmin(args.email, args.nome)
    if args.command == "resetpassword":
        return resetpassword(args.email)
    if args.command == "seed-templates":
        return seed_templates()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
