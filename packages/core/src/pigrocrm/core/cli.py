import argparse
import getpass
import sys

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory


def createadmin(email: str | None, nome: str | None) -> int:
    """Bootstrap the first administrator. There is no default account and no known
    default password — the direct lesson from Acme's hardcoded credentials."""
    email = email or input("Email: ").strip()
    nome = nome or input("Nome: ").strip()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Conferma password: "):
        print("Le password non coincidono.", file=sys.stderr)
        return 1

    engine = create_engine_from_settings(get_settings())
    with session_factory(engine)() as session:
        service = UserService(session)
        user = service.create(
            UserCreate(email=email, password=password, nome=nome, ruolo="admin"),
            Actor.system(),
        )
    print(f"Creato amministratore {user.email}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="pigrocrm")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("createadmin", help="Crea il primo utente amministratore")
    admin.add_argument("--email")
    admin.add_argument("--nome")

    args = parser.parse_args()
    if args.command == "createadmin":
        return createadmin(args.email, args.nome)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
