"""The repository must not carry a real person's or a real client's identity.

Why this runs on every change. On 2026-09-09 the working tree was sanitised and proved
clean by hand. Within the hour a branch cut *before* that merge landed *after* it, git
merged it with no conflict, and a real client's name was back in three test files with
nothing anywhere saying so. A hand-run inventory cannot defend a repository against its
own branches in flight.

## What this file checks, and what it deliberately does not

It checks **shapes**: a codice fiscale, a partita IVA, a codice SDI, an IBAN, an Italian
telephone number, an email domain. Every one of those is matched structurally and then
compared against a small allowlist of values this repository is allowed to contain. That
is the half that catches identity nobody has thought of yet, a new client's included, and
it is the half worth having in a public repository, because a regular expression for the
*shape* of a partita IVA discloses nothing about whose it was.

It does **not** carry a list of forbidden names any more, and that is the point of this
rewrite. The previous version stored them as truncated sha256 with a label per entry
("a client", "a client's employee", "the freelancer's comune"). Ivan inverted 17 of the 18
in seconds, with a dictionary built from the words in the repository's own history plus a
system word list, and recovered the complete set: the clients, their employees, the
products and a comune. Salting does not fix that. A salt stored beside the hashes only
defeats a precomputed table, and these are short real words: a dictionary attack with a
known salt is the same few seconds. A key derivation function with a large work factor
buys hours, not secrecy. In a public repository such a file is a labelled index of exactly
what somebody wanted hidden, which is worse than the words themselves.

So the name check moved out of the repository, where it can stay in plaintext and be
useful: `bin/identity-scan` in the maintainers' own environment, wired into
`.github/preflight.json`, which runs locally before a push and never in public CI. That
split is deliberate. The half that needs secret input runs where the secret already is;
the half that runs in front of everybody needs no secret at all.

Adding a value to an allowlist below is a decision, not a fix: it means someone read the
value and concluded it is synthetic. Anything real gets removed from the repository
instead.
"""

import re
import subprocess
from pathlib import Path

import pytest

# Values in a fiscal shape that this repository is allowed to contain, each one checked by
# hand and synthetic. A real value never joins this list; it leaves the repository.
_ALLOWED_CODICI_FISCALI = frozenset(
    {
        "HMCRFT00A01H501K",  # the emitter fixture
        "RSSMRA80A01H501U",  # Mario Rossi, the suite's stock customer
        "BNCRSS80A01H501U",  # Rossi Bianchi, the second stock customer
    }
)
_ALLOWED_PARTITE_IVA = frozenset(
    {
        "12345678901",  # the fixtures' stock company
        "01234567890",  # the second stock company
        "09876543210",
        "98765432109",
        "97531864200",
        "12345678903",  # one digit off the stock value, for a checksum test
        "10000000000",  # a checksum boundary case
    }
)
# Seven characters, and every one of these spells what it is.
_ALLOWED_CODICI_SDI = frozenset({"0000000", "XXXXXXX", "ABCDEFG", "1234567"})
_ALLOWED_IBANS = frozenset(
    {
        # Italy's example IBAN from the ISO 13616 registry: valid check digits, no account.
        "IT60X0542811101000000123456",
    }
)
_ALLOWED_TELEPHONES = frozenset({"+39 02 1234567", "+39 333 1234567"})
# The two pages where a real value is there by law. Italian law requires a public site to
# name the titolare del trattamento and its partita IVA, so these carry the company's real
# ones and always will. Everywhere else in this repository the same values are fixtures and
# are synthetic. This is a two-entry list with a reason, not an escape hatch: a third path
# joining it means somebody put real data somewhere it is not required.
_PATHS_WHERE_REAL_VALUES_ARE_REQUIRED = frozenset(
    {"projects/website/src/privacy.html", "projects/website/src/termini.html"}
)
# There is deliberately no check on email *domains* here. It was written, measured and
# removed: on this tree it reported 35 domains that all had to be allowlisted
# (`altrove.it`, `cliente.it`, `dominio.tld`, `rival.com` and so on, every one of them an
# obviously invented Italian word) and no mechanical rule separates those from a real
# company's domain. A check whose allowlist has to grow to forty entries is a check the
# next person in a hurry deletes. A domain is a name, not a shape, so it belongs in the
# name list that `bin/identity-scan` reads from outside the repository, where the
# knowledge of which company is real already lives.

_CODICE_FISCALE = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b")
_IBAN = re.compile(r"\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b")
# Both ends anchored on a non-word, non-dot character, and the bare form is exactly ten
# digits, which is what an Italian mobile number has. Neither constraint is cosmetic:
# without the anchor every sha256 in `uv.lock` contains a match, and at nine digits the
# OKLab colour matrix in `tokens.test.ts` reads as five mobile numbers. The spaced branch
# matters too: the number this check was written for was grouped 3-2-2-3, not 3-3-4.
_TELEPHONE = re.compile(r"(?<![\w.])(?:\+39[\s.]?\d[\d\s.]{7,}\d|3\d{2}(?:[\s.]?\d){7})(?![\w.])")
# A partita IVA and a codice SDI are matched *in context* rather than by bare shape. Eleven
# digits on their own also describe a GitHub run id and half the numbers in a changelog,
# and seven alphanumerics describe most identifiers in the language: `ByLabel`, `Decimal`
# and `SafeStr` all matched a bare-shape version of this check. The context is the field
# name, which is exactly where a real one would be planted.
_PARTITA_IVA_IN_CONTEXT = re.compile(
    r"(?i:partita_iva|partita IVA|p\.?iva)\W{0,6}(?<!\d)(\d{11})(?!\d)"
)
# The label is matched case-insensitively, the *value* is not: a codice SDI is uppercase
# alphanumeric, and an earlier version that lowercased the group reported `codice_sdi:
# Mapped[str]`, `codice_sdi: SafeStr` and `codice sdi is a string` as codes. The type
# annotation is the commonest neighbour of that field name, so it is the one form the
# pattern has to not match.
_CODICE_SDI_IN_CONTEXT = re.compile(r"(?i:codice[_ ](?:sdi|destinatario))\W{0,6}([A-Z0-9]{6,7})\b")


def _repository_root() -> Path:
    """Derived, never written down: this file is committed and the checkout is not."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent,
        capture_output=True,
        check=True,
    )
    return Path(out.stdout.decode().strip())


@pytest.fixture(scope="module")
def tracked_text() -> list[tuple[Path, str]]:
    """Every tracked file in the monorepo, read once.

    `git ls-files` is the only definition of "in the repository" that cannot drift. The
    cost of living in this project's suite is that a change touching only
    `projects/website` does not run it; the values this defends against are PigroCRM's
    fixtures, so that is where it earns its place. If a second project grows fixtures of
    its own, this moves to a gate of its own rather than being copied.
    """
    root = _repository_root()
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    out: list[tuple[Path, str]] = []
    for name in listing.stdout.decode().split("\0"):
        if not name:
            continue
        if name in _PATHS_WHERE_REAL_VALUES_ARE_REQUIRED:
            continue
        path = root / name
        try:
            out.append((path, path.read_text(encoding="utf-8", errors="ignore")))
        except (OSError, UnicodeDecodeError):
            continue  # a binary asset carries no value to match
    return out


_CHECKS = (
    (_CODICE_FISCALE, _ALLOWED_CODICI_FISCALI, "codice fiscale", None),
    (_IBAN, _ALLOWED_IBANS, "IBAN", None),
    (_TELEPHONE, _ALLOWED_TELEPHONES, "telephone number", None),
    (_PARTITA_IVA_IN_CONTEXT, _ALLOWED_PARTITE_IVA, "partita IVA", 1),
    (_CODICE_SDI_IN_CONTEXT, _ALLOWED_CODICI_SDI, "codice SDI", 1),
)


def _offenders(text: str) -> list[str]:
    found = []
    for pattern, allowed, what, group in _CHECKS:
        for match in pattern.finditer(text):
            value = " ".join((match.group(group) if group else match.group(0)).split())
            if value.lower() in {a.lower() for a in allowed}:
                continue
            found.append(f"{what} {value!r}")
    return found


def test_every_check_can_still_fail() -> None:
    """The guard's own guard.

    Five patterns and five allowlists is enough machinery to stop matching anything at
    all after an edit, and a check that matches nothing reports a pass forever. So each
    one is fired here against a planted value of its own shape.

    Every planted value is **assembled at runtime from fragments** rather than written
    out. That is not decoration: this file is tracked, the scan below reads every tracked
    file, and the first version of this test failed on its own planted IBAN. A literal
    here would either poison the scan or force this file to be excluded from it, and an
    excluded file is the one place a real value could then hide.
    """
    planted = " ".join(
        (
            'codice_fiscale="' + "ZZZZZZ" + "99Z99Z999Z" + '"',
            'iban="' + "IT99Z" + "9999999999" + "999999999999" + '"',
            'telefono="+39 ' + "321" + " " + "9876543" + '"',
            'partita_iva="' + "5" * 11 + '"',
            'codice_sdi="' + "ZZZ" + "9999" + '"',
        )
    )

    found = _offenders(planted)
    assert len(found) >= 5, f"a check stopped matching its own shape: only {found}"
    for what in ("codice fiscale", "IBAN", "telephone", "partita", "codice SDI"):
        assert any(what in f for f in found), f"the {what} check no longer fires: {found}"

    # A type annotation is the commonest neighbour of `codice_sdi` and must not read as a
    # code, or the guard fails on a clean tree and gets switched off by the next person.
    assert _offenders("codice_sdi: Mapped[str | None]") == []
    assert _offenders('partita_iva="12345678901"') == []


def test_the_scan_actually_reads_the_repository(tracked_text: list[tuple[Path, str]]) -> None:
    """A `git ls-files` that returns nothing would make every other assertion vacuous."""
    assert len(tracked_text) > 500, (
        f"only {len(tracked_text)} tracked files were read, so a pass here means nothing"
    )


def test_no_unapproved_identifier_appears_anywhere(
    tracked_text: list[tuple[Path, str]],
) -> None:
    offenders: list[str] = []
    for path, text in tracked_text:
        for hit in _offenders(text):
            offenders.append(f"{hit} in {path.name}")
    assert not offenders, (
        "an identifier in a fiscal shape, or an email domain, is not on the allowlist. "
        "Either it is real, in which case it does not belong in this repository, or it is "
        "synthetic, in which case add it to the allowlist above with a note saying so: "
        + "; ".join(sorted(set(offenders)))
    )


# `return 302 /<segment>/app/` and `return 302 /<segment>$request_uri` are the two shapes
# in the deploy vhosts that carry the root installation's slug, which is a real company's
# name. The public-page redirects are absolute URLs and do not match.
_VHOST_SLUG_REDIRECT = re.compile(r"return\s+30\d\s+/([A-Za-z0-9_-]+)(?:/app/|\$request_uri)")


def test_the_deploy_vhosts_keep_the_root_slug_as_a_placeholder() -> None:
    """The installed copy must never come back into the repository.

    The vhosts on the server are edited in place and hold the real slug; the copies here
    are the source of truth for the rules and hold `__ROOT_SLUG__`. Pasting the server's
    copy back is how the name returned once already (ORB-104), and it is invisible: nginx
    accepts it, the login keeps working, and only the deep links land on a space that
    does not exist.
    """
    confs = sorted((_repository_root() / "projects/pigrocrm/deploy/nginx").glob("*.conf"))
    assert confs, "no CRM vhost was found, so a pass here means nothing"

    matches = [(c.name, m) for c in confs for m in _VHOST_SLUG_REDIRECT.findall(c.read_text())]
    assert len(matches) >= 12, (
        f"the slug-carrying redirects stopped matching, so this test guards nothing: {matches}"
    )
    offenders = sorted({f"{name}: /{slug}" for name, slug in matches if slug != "__ROOT_SLUG__"})
    assert not offenders, (
        "a deploy vhost redirects under a literal space name instead of `__ROOT_SLUG__`. "
        "The repository copy is plain and substituted at install time: " + "; ".join(offenders)
    )


# What a browser downloads: the two SPAs' sources and the static site. Not the tests
# beside them, which are meant to be full of fixtures, and not the Python packages,
# whose docstrings discuss the fixtures on purpose.
_SHIPPED_WEB_SURFACES = (
    "projects/pigrocrm/apps/web/src",
    "projects/hub/apps/web/src",
    "projects/website/src",
)
_NOT_SHIPPED = re.compile(r"\.(test|spec)\.[jt]sx?$|/__tests__/|/e2e/")

# Two shapes, and they are separate because their false positives are.
#
# A stock company name is a defect wherever it appears in shipped copy: the hub's footer
# told every visitor for a week that «Orbiters è un progetto di Studio Rossi» (ORB-97).
#
# A placeholder domain from RFC 2606 is only a defect when it is *linked*, which is the
# other half of the same footer (`href="https://example.com/"`). Naming one in a comment
# is normal and useful -- `orbiters.js` explains an attack with
# `example.com/?u=linkedin.com/x` -- so matching the bare word would train the next
# person to reach for the allowlist instead of reading the failure.
_FIXTURE_COMPANY = re.compile(r"Studio Rossi|(?i:\bacme\b)|Cliente Srl|Committente Srl|Example Ltd")
_PLACEHOLDER_LINK = re.compile(
    r"""(?i:(?:href|src|action|url)\s*[=:]\s*["'`]\s*(?:https?:)?//?[^"'`]*example\.(?:com|org|net))"""
)

# A hit that was read and kept. A form's example value is the honest use of a stock
# company name, and a code comment naming one is discussing it rather than displaying it.
_ALLOWED_ON_SHIPPED_SURFACES = frozenset(
    {
        # the ragione sociale field's own example, shown greyed inside the empty input
        ("projects/hub/apps/web/src/pages/CompanyWizard.tsx", "ACME"),
        # both are comments about how a screen reader announces a company cell
        ("projects/pigrocrm/apps/web/src/features/people/columns.tsx", "ACME"),
        ("projects/pigrocrm/apps/web/src/components/cells.tsx", "ACME"),
    }
)


def _shipped_web_files(root: Path) -> list[str]:
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [
        n
        for n in listing.stdout.decode().split("\0")
        if n and n.startswith(_SHIPPED_WEB_SURFACES) and not _NOT_SHIPPED.search(n) and "." in n
    ]


def test_both_shipped_surface_shapes_can_still_fail() -> None:
    """Two regexes with an allowlist is enough machinery to stop matching anything."""
    assert _FIXTURE_COMPANY.findall("progetto di " + "Studio" + " Rossi") == ["Studio Rossi"]
    assert _FIXTURE_COMPANY.findall('placeholder="' + "ACME" + ' Srl"') == ["ACME"]
    assert _PLACEHOLDER_LINK.search('<a href="https://' + "example.com" + '/">x</a>')
    assert _PLACEHOLDER_LINK.search("src: '//" + "example.org" + "/a.js'")

    # The two neighbours that must not fire, or the failure gets muted instead of read:
    # a placeholder domain discussed in a comment, and a real word containing "acme".
    assert not _PLACEHOLDER_LINK.search("accepted " + "example.com" + "/?u=linkedin.com/x")
    assert _FIXTURE_COMPANY.findall("pharmacme e Sacmea") == []


def test_no_fixture_identity_reaches_a_shipped_web_surface() -> None:
    """A fixture name in a bundle is invisible to every check that existed.

    The allowlists above are about *real* identity, so a synthetic one passes them by
    design, and the shapes are fiscal, so a company name matches nothing. That is how the
    hub shipped an attribution to a test company: published, served and screenshotted for
    a week, and what caught it was reading the live page (ORB-97).

    So this asks a different question. Not "is this real", but "is this a fixture, in a
    file a browser downloads". A form's example value is the honest exception and is
    allowlisted by path, which is what makes an unlisted hit worth reading rather than
    muting.
    """
    root = _repository_root()
    shipped = _shipped_web_files(root)
    assert len(shipped) > 50, f"only {len(shipped)} shipped files were read, so this proves little"

    offenders: list[str] = []
    for name in shipped:
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for hit in _FIXTURE_COMPANY.findall(text):
            if (name, hit.upper()) in _ALLOWED_ON_SHIPPED_SURFACES:
                continue
            offenders.append(f"the company {hit!r} in {name}")
        if _PLACEHOLDER_LINK.search(text):
            offenders.append(f"a link to a placeholder domain in {name}")

    assert not offenders, (
        "a fixture company name, or a link to a placeholder domain, is in a file the "
        "browser downloads. A visitor reads it as the product's own copy, which is what "
        "ORB-97 was. Remove it, or if it is a deliberate example in a form, add its path "
        "to _ALLOWED_ON_SHIPPED_SURFACES with a note: " + "; ".join(sorted(set(offenders)))
    )
