"""Proof that the project's socket guard is live, and that nothing opts out.

The guard itself is in `conftest.py` at the root of this project -- see its docstring
for why it is there and not in a test root. These two tests exist because a guard
nobody verifies is a comment: `pytest_configure` running is not the same fact as
`socket.connect` actually refusing, and the two would drift apart silently the first
time somebody reorganised the plugin loading.
"""

import socket
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# pytest's configuration is at the monorepo root, two levels above this project, and
# names every project's test roots. See docs/architecture.md for why it is not
# per-project: `testpaths` resolves against the working directory rather than against
# the file it is written in.
MONOREPO_ROOT = PROJECT_ROOT.parents[1]
TEST_ROOTS = (
    PROJECT_ROOT / "packages" / "core" / "tests",
    PROJECT_ROOT / "apps" / "api" / "tests",
    PROJECT_ROOT / "apps" / "mcp" / "tests",
)


def test_the_guard_refuses_a_connection_to_a_public_host() -> None:
    with pytest.raises(AssertionError, match="never touches the network"):
        socket.create_connection(("gmail.googleapis.com", 443), timeout=0.1)


def test_the_guard_refuses_a_connection_to_a_public_ip_without_needing_dns() -> None:
    """The refusal must not depend on name resolution: an IP literal skips DNS
    entirely, and a guard hooked only into `getaddrinfo` would wave this straight
    through to a real SYN packet."""
    with pytest.raises(AssertionError, match="never touches the network"):
        socket.create_connection(("142.250.184.174", 443), timeout=0.1)


def test_the_guard_refuses_a_bare_name_lookup() -> None:
    """A DNS query is itself traffic leaving the machine."""
    with pytest.raises(AssertionError, match="never touches the network"):
        socket.getaddrinfo("gmail.googleapis.com", 443)


def test_the_guard_still_lets_the_test_container_through() -> None:
    """The other half of the guarantee, and the one that would break the entire
    repository if it regressed: every migration and repository test in this suite
    talks to a real PostgreSQL on a mapped loopback port. A guard that blocked
    localhost would be discovered as several hundred unrelated failures.

    Asserted against a closed port so that nothing is actually served: reaching
    `ConnectionRefusedError` proves the guard let the call through to the kernel,
    which is the whole claim.
    """
    with pytest.raises((ConnectionRefusedError, TimeoutError, OSError)) as caught:
        socket.create_connection(("127.0.0.1", 1), timeout=0.5)
    assert not isinstance(caught.value, AssertionError)

    # And name resolution for localhost is untouched, which is how psycopg reaches it.
    assert socket.getaddrinfo("localhost", 5432)


def test_no_test_in_this_repository_skips_itself_when_a_credential_is_absent() -> None:
    """`skipif` on an environment variable is how an integration suite comes to prove
    nothing: green everywhere, having executed none of the code it names. Checked as
    text over every test file in all three roots, because the rule is not specific to
    Gmail -- it is what "no test opens a socket" buys us in exchange.
    """
    this_file = Path(__file__).resolve()
    offenders: list[str] = []
    for root in TEST_ROOTS:
        for path in root.rglob("test_*.py"):
            # This file names both halves of the pattern in order to forbid them, so
            # it would otherwise be its own only offender.
            if path.resolve() == this_file:
                continue
            source = path.read_text(encoding="utf-8")
            if "skipif" not in source:
                continue
            if any(marker in source for marker in ("environ", "getenv", "PIGROCRM_")):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], (
        "these tests skip themselves based on the environment, which is how a suite "
        f"stays green without ever running: {offenders}"
    )


def test_the_three_test_roots_this_guard_claims_to_cover_all_exist() -> None:
    """The check above walks three directories by name. If a root were renamed or
    added, it would quietly walk fewer of them and keep passing -- so the set is
    asserted against `testpaths` rather than trusted.

    `testpaths` is monorepo-wide and will name other projects' roots as they arrive,
    so the comparison is against the part of it that belongs to this project. An
    equality over the whole list would turn every future project into a failure here,
    which is the kind of assertion people delete rather than fix.
    """
    import tomllib

    config = tomllib.loads((MONOREPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        MONOREPO_ROOT / path for path in config["tool"]["pytest"]["ini_options"]["testpaths"]
    }
    mine = {path for path in declared if path.is_relative_to(PROJECT_ROOT)}
    assert mine == set(TEST_ROOTS)
