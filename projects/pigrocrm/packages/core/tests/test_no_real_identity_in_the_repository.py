"""The repository must not carry a real person's or a real client's identity.

Why this is a test and not a checklist. On 2026-09-09 the working tree was sanitised
(ORB-46 through ORB-52) and proved clean by hand. Within the hour a branch that had been
cut *before* that merge landed *after* it, and git merged it without a conflict, because
adding a fixture to a file nobody else touched on those lines is not a conflict. A real
client's name was back in three test files, and nothing anywhere said so. A hand-run
inventory cannot defend a repository against its own branches in flight; only a check
that runs on every change can.

Two halves, and they fail for different reasons:

* `test_no_forbidden_name_appears_anywhere` is a denylist of the names this repository is
  not allowed to carry. It is stored as **hashes**, because a denylist written in plain
  text is itself the disclosure it exists to prevent: the file would reintroduce every
  value on the next `git grep`. Hashing also buys accuracy for free, since a hash is
  compared against whole words. A regex pass over the same tree produced three false
  positives of exactly that kind, where a dependency's name contained a client's and an
  ordinary Italian verb contained a street's; a whole-word hash cannot make that mistake.
* `test_no_unapproved_fiscal_identifier_appears_anywhere` works the other way round: it
  matches codice-fiscale, IBAN and Italian-telephone *shapes*, and fails on any value not
  in the allowlist below. That is the half that catches identity nobody has thought of
  yet, including a new client's, which is exactly what a denylist cannot do.

Adding a real value to `ALLOWED_*` is a decision, not a fix. The synthetic values there
are documented one by one; anything else that lands in one of those shapes is either
replaced with a synthetic value or discussed before it is allowed.

The scan covers **every tracked file in the monorepo**, not just this project, because
`git ls-files` is the only definition of "in the repository" that cannot drift. The cost
of living in this project's suite is that a change touching only `projects/website` does
not run it; the values this defends against are PigroCRM's fixtures, so that is where the
check earns its place. If a second project ever grows fixtures of its own, this moves to a
gate of its own rather than being copied.
"""

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

# sha256, truncated to 32 hex characters: enough that a preimage search is not the easy
# way to read this list, and a collision at this length is not a practical worry for a
# vocabulary of a few thousand words per file.
_FORBIDDEN_HASHES = {
    "f7302ee1cbc8376878c6e6189682efc7": "a client that cannot be named",
    "b7b322321464e53c6808bde2ead12371": "the same client, written as a domain",
    "5f144e040eccec09348c10cd8f9f8b50": "the same client, as two words",
    "c497ece874cbb6e517ddc16993070c98": "a client",
    "f5f5a0684b2c5e4158ea74bac8ba5636": "a client",
    "004e38da70876a44baa6215bb03889cc": "a client",
    "4e10177d905a0ab01bbd2cb70172e244": "a client",
    "5d682f9680754648ac39c2a8d80cac2f": "a client's product",
    "491c67666c4fd254968da071644325e7": "a client's project codename",
    "ab7309141385f7c35b3529e0956c1bdb": "a client's product",
    "6da675dc22dc488103d37a7d70f9cc7f": "the same product, shortened",
    "6793493623b38fe105e42cb010f2ce0a": "the accountant's platform",
    "67b8957da97dc943f201dcb516de1081": "a customer who is a natural person",
    "78a6ea014b380d9ddbdb0c3186b2a6fc": "a client's employee",
    "18ccba186d8757c20cbf05d7a98b2c64": "a client's employee",
    "e8e9689deac5bac977b64e85c1105bd1": "a client's employee",
    "e27d8bd97d136e803daec3bac4c74d32": "the freelancer's street",
    "b77c7addf635dd3a9f853a7f341273ff": "the freelancer's comune",
    "ef7c6cba58cf82997b990feec6b78b1c": "the previous product this replaced",
}

# Every value in these shapes that the repository is allowed to contain, and why.
_ALLOWED_CODICI_FISCALI = frozenset(
    {
        "HMCRFT00A01H501K",  # the emitter fixture, synthetic (ORB-47)
        "RSSMRA80A01H501U",  # Mario Rossi, the suite's stock customer
        "BNCRSS80A01H501U",  # Rossi Bianchi, the second stock customer
    }
)
_ALLOWED_IBANS = frozenset(
    {
        # Italy's example IBAN, from the ISO 13616 registry and Wikipedia. It is not a
        # bank account: the check digits are valid and the account does not exist.
        "IT60X0542811101000000123456",
    }
)
_ALLOWED_TELEPHONES = frozenset(
    {
        "+39 02 1234567",  # the landline placeholder the fixtures share
        "+39 333 1234567",  # the mobile placeholder the fixtures share
    }
)

_WORD = re.compile(r"[A-Za-z][A-Za-z']{2,}")
_CODICE_FISCALE = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b")
_IBAN = re.compile(r"\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b")
# Both ends are anchored on a non-word, non-dot character, and the bare form is exactly
# ten digits, which is what an Italian mobile number has. Neither constraint is cosmetic:
# without the anchor every sha256 in `uv.lock` contains a match, and at nine digits the
# OKLab colour matrix in `tokens.test.ts` reads as five mobile numbers (`3.3077115913`),
# a hash constant in `field.js` as a sixth and a formatted P.IVA as a seventh. The
# spaced branch matters too: the number this check was written for was grouped as
# 3-2-2-3 rather than 3-3-4, and a fixed grouping would have walked straight past it.
_TELEPHONE = re.compile(r"(?<![\w.])(?:\+39[\s.]?\d[\d\s.]{7,}\d|3\d{2}(?:[\s.]?\d){7})(?![\w.])")


def _repository_root() -> Path:
    """Derived, never written down: this file is committed and the checkout is not."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent,
        capture_output=True,
        check=True,
    )
    return Path(out.stdout.decode().strip())


def _tracked_files() -> list[Path]:
    root = _repository_root()
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [root / name for name in out.stdout.decode().split("\0") if name]


def _hash(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()[:32]


@pytest.fixture(scope="module")
def tracked_text() -> list[tuple[Path, str]]:
    """Read once for both tests: about a thousand files, and reading them twice is the
    difference between a check people keep and a check people mark slow."""
    out = []
    for path in _tracked_files():
        try:
            out.append((path, path.read_text(encoding="utf-8", errors="ignore")))
        except (OSError, UnicodeDecodeError):
            continue  # a binary asset carries no words to match
    return out


def test_the_denylist_can_still_fail(tracked_text: list[tuple[Path, str]]) -> None:
    """The guard's own guard.

    A denylist of hashes is unreadable by design, so a typo in one entry, or a change to
    the tokeniser, degrades it to matching nothing at all -- silently, and reported as a
    pass. This proves the machinery still detects a name: it plants one, in the same shape
    the tokeniser sees, and requires the scanner to find it.
    """
    # An invented word, not one of the real entries: a self-test that had to name a
    # client in order to prove the scanner works would put that name back in the tree and
    # defeat the file it lives in.
    planted = "Zyrtank Holdings Srl in a sentence, and zyrtankconfig beside it"
    hits = _scan_words(planted, {_hash("zyrtank"): "the planted name"})
    assert hits == {"the planted name"}, "the word scanner no longer detects a plain name"

    # The near miss stays a miss: a dependency whose name merely starts with the same
    # letters is a different word, and this is the property the hashes buy.
    assert _scan_words("someone@example.com", {_hash("zyrtank"): "x"}) == set()

    # And a two-word entry is found across the space, which the bigram pass exists for.
    assert _scan_words(
        "the Zyrtank Holdings account", {_hash("zyrtank holdings"): "the planted pair"}
    ) == {"the planted pair"}

    assert len(tracked_text) > 500, (
        f"only {len(tracked_text)} files scanned: `git ls-files` returned almost nothing, "
        "so a pass here would mean nothing"
    )


def _scan_words(text: str, hashes: dict[str, str]) -> set[str]:
    words = [w.lower() for w in _WORD.findall(text)]
    found = set()
    for index, word in enumerate(words):
        candidates = [word]
        if index + 1 < len(words):
            candidates.append(f"{word} {words[index + 1]}")
        for candidate in candidates:
            label = hashes.get(_hash(candidate))
            if label is not None:
                found.add(label)
    return found


def test_no_forbidden_name_appears_anywhere(tracked_text: list[tuple[Path, str]]) -> None:
    offenders: dict[str, list[str]] = {}
    for path, text in tracked_text:
        for label in _scan_words(text, _FORBIDDEN_HASHES):
            offenders.setdefault(label, []).append(path.name)
    assert not offenders, "a name this repository must not carry is back in the tree: " + "; ".join(
        f"{label} in {sorted(set(files))}" for label, files in offenders.items()
    )


def test_no_unapproved_fiscal_identifier_appears_anywhere(
    tracked_text: list[tuple[Path, str]],
) -> None:
    offenders: list[str] = []
    for path, text in tracked_text:
        for pattern, allowed, what in (
            (_CODICE_FISCALE, _ALLOWED_CODICI_FISCALI, "codice fiscale"),
            (_IBAN, _ALLOWED_IBANS, "IBAN"),
            (_TELEPHONE, _ALLOWED_TELEPHONES, "telephone number"),
        ):
            for match in pattern.finditer(text):
                value = " ".join(match.group(0).split())
                if value not in allowed:
                    offenders.append(f"{what} {value!r} in {path.name}")
    assert not offenders, (
        "an identifier in a fiscal shape is not in the allowlist. Either it is real, in "
        "which case it does not belong in the repository, or it is synthetic, in which "
        "case add it to the allowlist with a note saying so: " + "; ".join(sorted(set(offenders)))
    )
