"""`pigrocrm gmail-sync`: the cron's way in.

There is no daemon in this product and no queue (see `gmail/sync.py`), so "every
fifteen minutes" is somebody else's job -- cron's. This command is the whole of the
contract with it: one cycle, one line on stdout, and an exit status a shell can read.

Two properties are asserted here rather than described:

* **Who the cron is.** `sync` refuses an actor with no id (`solo un utente può
  sincronizzare una casella`) because the mailbox belongs to a person, so the command
  cannot simply pass `Actor.system()` the way `createadmin` does. It builds a *system*
  actor carrying the mailbox owner's id, and the timeline says so: `actor_type` is
  `system`, because nobody pressed anything.
* **A cron job must not need a human to read a traceback.** Every failure the command
  can foresee -- no mailbox, an ambiguous one, a revoked credential -- ends as one
  sentence on stderr and exit 1.

The transport is a `FakeGmail` for the reason every test in this package uses one: what
runs is the real URL building, the real `q` and the real error handling, and only the
socket is replaced.
"""

from collections.abc import Iterator
from uuid import UUID

import pytest
from fakes.fake_gmail import FakeGmail
from fakes.gmail_fixtures import connected_account, gmail_settings
from sqlalchemy import Engine, text

import pigrocrm.core.cli as cli
from pigrocrm.core.db import session_factory
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.transport import GmailTransport


@pytest.fixture
def cli_gmail(db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGmail]:
    """The CLI builds its own settings, engine and transport, exactly as it does in the
    container; here all three are the test's own, and the rows it commits for real are
    removed afterwards."""
    fake = FakeGmail()
    monkeypatch.setattr(cli, "get_settings", gmail_settings)
    monkeypatch.setattr(cli, "create_engine_from_settings", lambda settings: db_engine)
    monkeypatch.setattr(
        cli, "GmailTransport", lambda: GmailTransport(http=fake, sleep=lambda _: None)
    )
    yield fake
    with db_engine.begin() as connection:
        connection.execute(text("delete from activities where entity_type = 'google_account'"))
        connection.execute(text("delete from gmail_known_addresses"))
        connection.execute(text("delete from google_accounts"))
        connection.execute(text("delete from users where email like 'user-%@example.it'"))


def _connect(engine: Engine, *, email_address: str, status: str = "active") -> UUID:
    """A mailbox the CLI's own session can see: committed, not merely flushed."""
    with session_factory(engine)() as session:
        account = connected_account(session, email_address=email_address, status=status)
        owner_id = account.user_id
        session.commit()
    return owner_id


def _run(*args: str) -> int:
    return cli.main(["gmail-sync", *args])


def test_gmail_sync_runs_a_cycle_and_says_so_in_one_line(
    cli_gmail: FakeGmail, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    _connect(db_engine, email_address="cron@example.it")

    assert _run() == 0

    out = capsys.readouterr().out.strip()
    assert out.count("\n") == 0
    assert "cron@example.it" in out
    # The counters, which are the only thing a cron log has to say. No subject, no
    # address of a correspondent, no body: a `SyncReport` has no room for one.
    assert "0 messaggi" in out


def test_the_cycle_is_recorded_as_the_system_acting_for_the_mailbox_owner(
    cli_gmail: FakeGmail, db_engine: Engine
) -> None:
    """The actor question, which has a wrong answer that would pass every other test
    here: the owner's own `user` actor. Cron is not the owner, and a timeline that says
    a person synchronised at 03:15 is a small lie the timeline exists not to tell."""
    owner_id = _connect(db_engine, email_address="cron@example.it")

    assert _run() == 0

    with db_engine.connect() as connection:
        actor_type, actor_id = connection.execute(
            text(
                "select actor_type, actor_id from activities "
                "where kind = 'gmail.sync_eseguito' order by occurred_at desc limit 1"
            )
        ).one()
    assert actor_type == "system"
    assert actor_id == owner_id


def test_gmail_sync_on_an_installation_with_no_mailbox_fails_with_a_sentence(
    cli_gmail: FakeGmail, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run() == 1
    captured = capsys.readouterr()
    assert "nessuna casella" in captured.err
    assert captured.out == ""


def test_gmail_sync_on_a_revoked_credential_exits_one(
    cli_gmail: FakeGmail, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    """The status cron has to be able to act on. Exit 0 here would make a dead
    integration look like fifteen minutes of nothing happening, forever."""
    _connect(db_engine, email_address="cron@example.it", status="revoked")

    assert _run() == 1
    assert "revocato" in capsys.readouterr().err


def test_gmail_sync_picks_the_mailbox_named_on_the_command_line(
    cli_gmail: FakeGmail, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    _connect(db_engine, email_address="prima@example.it")
    _connect(db_engine, email_address="seconda@example.it")

    assert _run("--email", "seconda@example.it") == 0
    assert "seconda@example.it" in capsys.readouterr().out


def test_two_mailboxes_and_no_email_is_refused_rather_than_guessed(
    cli_gmail: FakeGmail, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    """Picking one would mean the other silently stops being synchronised, and the log
    would look identical either way."""
    _connect(db_engine, email_address="prima@example.it")
    _connect(db_engine, email_address="seconda@example.it")

    assert _run() == 1
    err = capsys.readouterr().err
    assert "--email" in err
    assert "prima@example.it" in err
    assert "seconda@example.it" in err


def test_an_email_that_is_not_connected_names_the_ones_that_are(
    cli_gmail: FakeGmail, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    _connect(db_engine, email_address="cron@example.it")

    assert _run("--email", "altra@example.it") == 1
    err = capsys.readouterr().err
    assert "altra@example.it" in err
    assert "cron@example.it" in err


def test_a_cycle_already_running_is_reported_and_is_not_a_failure(
    cli_gmail: FakeGmail, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cron every fifteen minutes and somebody pressing Sincronizza is the collision the
    advisory lock exists for. The second caller spent nothing, so an error in the log
    here would be an error for the system working as designed -- and a log that cries
    wolf every quarter of an hour is a log nobody reads."""
    owner_id = _connect(db_engine, email_address="cron@example.it")
    with session_factory(db_engine)() as holder:
        # The real lock, on a real second connection: `pg_try_advisory_lock` is session
        # scoped, so nothing short of another session can hold it against this one.
        repo = GmailRepository(holder)
        account = repo.account_for_user(owner_id)
        assert account is not None
        assert repo.try_sync_lock(account.id)
        try:
            assert _run() == 0
        finally:
            repo.release_sync_lock(account.id)

    assert "già in corso" in capsys.readouterr().out
