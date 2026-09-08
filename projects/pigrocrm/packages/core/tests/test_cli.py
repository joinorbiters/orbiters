"""`pigrocrm resetpassword` read from a pipe, the way an operator without a tty runs it."""

import io
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

import pigrocrm.core.cli as cli
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.passwords import verify_password
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService


@pytest.fixture
def cli_engine(db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """The CLI builds its own engine from settings; here it gets the test container's,
    and the rows it writes are removed afterwards (the CLI commits for real)."""
    monkeypatch.setattr(cli, "create_engine_from_settings", lambda settings: db_engine)
    yield db_engine
    with db_engine.begin() as connection:
        connection.execute(text("delete from activities where entity_type = 'user'"))
        connection.execute(text("delete from refresh_tokens"))
        connection.execute(text("delete from users where email like 'cli-%'"))


def test_resetpassword_reads_the_new_password_from_stdin_when_there_is_no_tty(
    cli_engine: Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pigrocrm.core.db import session_factory

    with session_factory(cli_engine)() as session:
        UserService(session).create(
            UserCreate(
                email="cli-reset@studio.it", password="vecchia-password-1", nome="C", ruolo="admin"
            ),
            Actor.system(),
        )
    monkeypatch.setattr("sys.stdin", io.StringIO("nuova-password-2026\n"))
    monkeypatch.setattr("sys.argv", ["pigrocrm", "resetpassword", "--email", "cli-reset@studio.it"])

    assert cli.main() == 0
    assert "Password aggiornata per cli-reset@studio.it" in capsys.readouterr().out
    with cli_engine.connect() as connection:
        stored = connection.execute(
            text("select password_hash from users where email = 'cli-reset@studio.it'")
        ).scalar_one()
    assert verify_password("nuova-password-2026", stored)


def test_resetpassword_reports_a_short_password_without_a_traceback(
    cli_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("corta\n"))
    monkeypatch.setattr(
        "sys.argv", ["pigrocrm", "resetpassword", "--email", "cli-nessuno@studio.it"]
    )
    assert cli.main() == 1
    assert "almeno" in capsys.readouterr().err
