"""An agent must not be able to issue a fiscal document, nor touch the handful of
slice-4 operations that are closer to configuration or to rewriting the past than to
recording an entity.

The guarantee is *structural*: the tool is not registered. It is deliberately not a
permission check, because a personal access token inherits its owner's full role and
never expires (residuo R10) -- so a check inside a registered tool is a check an
administrator's token passes, and "give a token to Claude" would mean "let Claude issue
invoices in your name", or recalculate what a quarter's work was worth.

A comment saying so protects nothing. These tests read every module under `tools/` and
fail if any forbidden operation ever appears as a tool, or is called under another name,
so the guarantee survives someone adding one without reading the comment. Slice 4 and
slice 6 extend the same two lists rather than writing a parallel mechanism -- which is
why `FORBIDDEN`/`FORBIDDEN_SERVICE_CALLS` are module-level constants with one name per
line rather than inline literals, and why the source scan below covers every file in
`tools/`, not only `tools/__init__.py`: slice 4's tool call-throughs live in their own
module (`tools/timetracking.py`, mirroring `tools/invoices.py`), and a registered tool
that called a same-named wrapper in that module which itself called a forbidden service
method would leave no trace in `tools/__init__.py` alone.
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_mcp.server import build_server

TOOLS_DIR = Path(__file__).resolve().parents[1] / "src" / "pigrocrm_mcp" / "tools"

# The one module the scans below skip, and the only one allowed to reach a forbidden
# operation. Its whole existence is conditional: `server.py` imports and registers it only
# when `Settings.mcp_full_access` is true, so on a default installation its calls are as
# unreachable as if the file were not there. The scans therefore ask a narrower and truer
# question than "does this call appear anywhere" -- they ask whether it appears anywhere
# that runs unconditionally.
#
# `test_the_privileged_module_is_the_only_place_they_appear` closes the obvious hole in
# that exemption: a second file quietly added to the skip list, or `privileged` imported
# outside the guard, both fail there.
PRIVILEGED = TOOLS_DIR / "privileged.py"

# Sixteen operations: the five fiscal ones that turn a draft into a fiscal fact or
# change what one says after the fact, and the eleven that are closer to configuration
# or to rewriting the past than to recording an entity. Each is reachable over REST by a
# human with the right role; none is reachable by an agent at all. `bind_time_to_invoice`
# and `get_fiscal_estimate` belong to `AnalyticsService`, which does not exist until plan
# 4B -- declared here regardless, because the ban is a decision made now and plan 4B must
# not have to touch this list to honour it.
#
# Two of the sixteen were added after an audit found the repo stating this policy twice
# and the two statements disagreeing:
#
#   * `update_fiscal_profile` is one of the *four* names slice 3 §11 actually banned
#     (`issue_invoice`, `annul_invoice`, `mark_transmitted_externally`,
#     `update_fiscal_profile`); this list dropped it and put `export_invoice_xml` -- a
#     real, correct addition -- in its place, while `tools/invoices.py` went on declaring
#     it forbidden in a table nothing imported. That row decides the VAT rate, the
#     natura, the bollo and the normative reference printed on every invoice line: it is
#     the configuration this ban exists for, not an exception to it.
#   * `unarchive_cost_category` is `archive_cost_category` in the other direction, and
#     the same decision about which categories the CRM offers. Its absence from slice 4
#     §11's list of ten is an omission rather than a distinction -- there is no reading
#     under which creating, renaming and archiving a category are configuration and
#     bringing one back is not.
FORBIDDEN = (
    "issue_invoice",
    "annul_invoice",
    "mark_invoice_transmitted",
    "export_invoice_xml",
    "update_fiscal_profile",
    "recalculate_rates",
    "update_user_rates",
    "update_deal_rate",
    "create_cost_category",
    "update_cost_category",
    "archive_cost_category",
    "unarchive_cost_category",
    "close_period",
    "reopen_period",
    "bind_time_to_invoice",
    "get_fiscal_estimate",
    # The seventeenth, and the first that is not fiscal: asking Gmail who at a customer's
    # domain the owner has corresponded with. Not irreversible -- it stores nothing --
    # but it spends the owner's Gmail quota under the owner's OAuth consent, which is
    # the exact reason `sync` and `backfill` are refused to agents outright. It is on
    # this list rather than on `FORBIDDEN_GMAIL` because, unlike those two, the
    # installation *can* opt in: the same switch that hands an agent the fiscal acts.
    "discover_gmail_correspondents",
    # The eighteenth and nineteenth, and both fiscal again: writing a numbered, issued
    # row straight into the register (slice 9 §3), and declaring the numbers it will
    # never carry (slice 9 §3.2).
    "import_issued_invoice",
    "declare_invoice_register_gaps",
)

# The tools above that exist only on an installation where Gmail is configured as well:
# on one without Google there is no mailbox to ask, so the switch alone does not make
# them appear. `test_the_sixteen_are_registered_exactly_when_the_installation_opted_in`
# accounts for them by building both kinds of installation.
FORBIDDEN_NEEDING_GMAIL = frozenset({"discover_gmail_correspondents"})

# The service methods behind them. Listed separately because a future tool could call one
# under an innocuous name -- `finalise_invoice` registering a tool that calls `issue`
# would pass a name check and defeat the point. Fifteen, not sixteen: the sixteenth is
# `FiscalProfileService.upsert`, which a bare name cannot express and which is banned by
# `FORBIDDEN_QUALIFIED_CALLS` below.
FORBIDDEN_SERVICE_CALLS = (
    "issue",
    "annul",
    "mark_transmitted_externally",
    "export_xml",
    "recalculate_rates",
    "update_user_rates",
    "update_deal_rate",
    "create_cost_category",
    "update_cost_category",
    "archive_cost_category",
    "unarchive_cost_category",
    "close_period",
    "reopen_period",
    "bind_time_to_invoice",
    "get_fiscal_estimate",
    "discover",
    "import_issued",
    "declare_gaps",
)

# The bans a bare method name cannot express, because the name is not the operation.
# `update_fiscal_profile` is `FiscalProfileService.upsert`, and `upsert` is exactly the
# kind of name a second service already carries: `EmitterProfileService.upsert` writes
# the issuer's identity, and `EmitterProfileService.get` is *on* the MCP surface -- the
# PDF header needs it for every role. Putting "upsert" in the tuple above would ban the
# substring, so any call spelled that way, on any service, would fail this file with a
# message about the fiscal profile. A ban on a name is not a ban on an operation, and the
# fifteen names above are safe only because each of them happens to be unique; this one
# is not, so it names its receiver and `_receivers_of` resolves it.
FORBIDDEN_QUALIFIED_CALLS = (("FiscalProfileService", "upsert"),)

_REASON = (
    "e' un'operazione esclusa dalla superficie MCP per costruzione (slice 3 §11 per "
    "gli atti fiscali e per il profilo fiscale, slice 4 §11 per le tariffe, le "
    "categorie di costo e le chiusure di periodo), non per controllo di permessi: un "
    "PAT eredita il ruolo pieno del proprietario e non scade (residuo R10), quindi "
    "l'assenza del tool e' l'unico meccanismo che regge."
)


# Gmail (slice 5B). Nomi di strumenti, non metodi di servizio, e per due ragioni
# diverse fra loro.
#
# I primi due non hanno ancora un metodo dietro: l'invio arriva in 5B-2, e il divieto e'
# una decisione presa adesso -- come per `bind_time_to_invoice`, dichiarato qui prima
# che `AnalyticsService` esistesse. Un'email partita dalla tua casella non si richiama e
# il cliente la legge come parole tue; e un agente che tiene la *lettura* della posta e
# l'*invio* sulla stessa cintura ha la sorgente di injection e il canale di
# esfiltrazione sullo stesso canale. Il corpo di un'email che arriva a un agente e'
# testo scritto da qualcun altro: quello che impedisce che sia un buco e' che non ci sia
# niente con cui mandare fuori qualcosa. La persona preme Invia.
#
# Gli altri quattro hanno un metodo dietro, gia' escluso in `test_mcp_surface_coverage.
# py`, e sono ripetuti qui come *nomi* perche' le due liste rispondono a domande
# diverse: quella e' "questo metodo e' raggiungibile", questa e' "questo strumento
# esiste". Uno strumento chiamato `sync_gmail` che chiamasse qualcosa d'altro passerebbe
# la prima e fallirebbe questa.
#
# Non c'e' `FORBIDDEN_GMAIL_SERVICE_CALLS`: i metodi corrispondenti sono gia' coperti
# dal divieto per costruzione dell'altro file, e aggiungerli qui romperebbe l'uguaglianza
# fra `_VIETATE` e queste tuple che `test_the_forbidden_block_names_exactly_what_the_
# ban_test_bans` verifica -- due liste che si ripetono divergono, ed e' esattamente il
# difetto che quel test esiste per prendere.
FORBIDDEN_GMAIL = (
    "send_email",
    "send_payment_reminder",
    "sync_gmail",
    "backfill_gmail",
    "connect_google_account",
    "disconnect_google_account",
    "set_gmail_settings",
    "search_gmail",
)

# Il substring che nessun nome di strumento puo' contenere. Piu' forte dell'elenco
# sopra, che sa solo le grafie a cui qualcuno ha pensato: la garanzia e' che nessuno
# strumento invii, non che quattro nomi particolari siano assenti.
FORBIDDEN_TOOL_NAME_FRAGMENTS = ("send", "invia")

_REASON_GMAIL = (
    "e' escluso dalla superficie MCP di slice 5B per costruzione. La riga non e' "
    "lettura contro scrittura ma di chi e' la risorsa e di chi la decisione: l'agente "
    "legge la copia gia' archiviata in `gmail_messages` e lo stato della credenziale, "
    "mentre andare a prendere la posta (quota e consenso della persona), collegare o "
    "scollegare una casella, decidere se il CRM conserva i corpi, e inviare, "
    "appartengono alla persona. Come per gli atti fiscali, non e' un controllo di "
    "permessi: un PAT eredita il ruolo pieno del proprietario e non scade (residuo "
    "R10), quindi l'assenza del tool e' l'unico meccanismo che regge."
)


def _modules(base: Path = TOOLS_DIR) -> list[ast.Module]:
    return [
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(base.rglob("*.py"))
        if path != PRIVILEGED
    ]


def _registered_tool_names(base: Path = TOOLS_DIR) -> set[str]:
    """Every function carrying an `@mcp.tool()` decorator, at any nesting depth, in any
    module under `tools/`.

    Walks the whole tree rather than the top level: the registrations live inside
    `build_server`'s body and inside each `register(...)` function, so a top-level-only
    scan would report nothing and pass vacuously -- which is the failure mode this file
    exists to avoid in the code it guards.

    It used to be scoped to `tools/__init__.py`, on the true-at-the-time observation
    that every `@mcp.tool()` decorator lived there. Slice 5B's `tools/gmail.py` carries
    its own, and that is exactly the shape a future forbidden tool would take: a new
    domain module registering its own tools, invisible to a scan of one file. A ban that
    only reads the file the last author happened to use is not a ban.
    """
    names: set[str] = set()
    for module in _modules(base):
        for node in ast.walk(module):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    names.add(node.name)
    return names


def _tools_source(base: Path = TOOLS_DIR) -> str:
    """Every `.py` file under `tools/`, concatenated.

    Whole-package, like `_registered_tool_names` above and for a second reason of its
    own: the actual call into a service lives one file over, in the
    domain-specific module a registered tool calls through (`tools/invoices.py`,
    `tools/timetracking.py`, ...). A forbidden method reached only from there --
    directly, or through a same-named wrapper function called under a different tool
    name -- must fail exactly as if it were called inline in `tools/__init__.py`
    itself; scanning the whole package is what makes that true regardless of which
    file the call physically sits in.
    """
    return "\n".join(
        path.read_text(encoding="utf-8") for path in base.rglob("*.py") if path != PRIVILEGED
    )


def _receivers_of(method: str, base: Path = TOOLS_DIR) -> list[str | None]:
    """For every call spelled `.method(` anywhere under `base`, the service class it
    lands on -- or `None` where this cannot tell.

    Exists for `FORBIDDEN_QUALIFIED_CALLS`, and only for it: the substring scan below is
    the right instrument for a method name that belongs to exactly one service, and the
    wrong one for `upsert`. Resolves the three call shapes this package actually uses --
    `ServiceClass(context.session).m(...)`, `svc = ServiceClass(...)` then `svc.m(...)`,
    and the module-private factories (`_invoices(context) -> InvoiceService`) that
    `tools/invoices.py` and `tools/documents.py` use -- recognising a service by this
    codebase's own naming rule, a class whose name ends in `Service`, so that this file
    stays readable without importing anything from `packages/core`.

    An unresolved receiver is reported as `None` and counted as an offence by the caller.
    That is the whole point of returning `None` rather than dropping the call: "we could
    not work out whose `upsert` this is" must not read as "it is not the forbidden one".
    A ban that fails open is not a ban.
    """
    receivers: list[str | None] = []
    for path in sorted(base.rglob("*.py")):
        if path == PRIVILEGED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        factories: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                returns = node.returns
                if isinstance(returns, ast.Name) and returns.id.endswith("Service"):
                    factories[node.name] = returns.id

        def produced(func: ast.expr, factories: dict[str, str] = factories) -> str | None:
            if not isinstance(func, ast.Name):
                return None
            return func.id if func.id.endswith("Service") else factories.get(func.id)

        bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                owner = produced(node.value.func)
                if owner is not None:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            bindings[target.id] = owner

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != method:
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Call):
                receivers.append(produced(receiver.func))
            elif isinstance(receiver, ast.Name):
                receivers.append(bindings.get(receiver.id))
            else:
                receivers.append(None)
    return receivers


def test_the_ast_walk_actually_finds_the_registered_tools() -> None:
    """Guards the guard. If `_registered_tool_names` returned an empty set -- because the
    decorator spelling changed, or because the registrations moved -- every ban test
    below would pass while checking nothing. Anchored on tools that exist today and on a
    plausible count, so a silent break is a failure and not a green run."""
    names = _registered_tool_names()
    assert "list_invoices" in names
    assert "get_invoice" in names
    assert "create_customer" in names
    assert len(names) > 20


def test_the_source_scan_actually_reads_more_than_one_file() -> None:
    """Guards the *other* guard. If `_tools_source` only ever returned
    `tools/__init__.py`'s own text -- because `rglob` found nothing, or `TOOLS_DIR` was
    pointed at the wrong directory -- `test_no_registered_tool_calls_a_fiscal_write_
    under_another_name` would silently stop seeing `tools/invoices.py` and
    `tools/timetracking.py` at all, which is exactly the gap the whole-package scan
    exists to close."""
    source = _tools_source()
    assert "def search(" in source  # tools/invoices.py
    assert "def log_time(" in source  # tools/timetracking.py


def test_the_registration_scan_reads_every_module_and_not_only_the_first() -> None:
    """Guards the widening. `tools/gmail.py` is the first module outside
    `tools/__init__.py` to register tools of its own, and it is the shape every future
    domain module will take. If the scan silently narrowed back to one file, the Gmail
    bans below would pass while checking a file that contains none of them."""
    names = _registered_tool_names()
    assert "list_gmail_messages" in names  # tools/gmail.py
    assert "create_customer" in names  # tools/__init__.py


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_no_tool_is_registered_for_a_forbidden_operation(forbidden: str) -> None:
    assert forbidden not in _registered_tool_names(), (
        f"'{forbidden}' e' registrato come tool MCP, ma {_REASON}"
    )


@pytest.mark.parametrize("forbidden", FORBIDDEN_GMAIL)
def test_no_tool_is_registered_for_a_forbidden_gmail_operation(forbidden: str) -> None:
    assert forbidden not in _registered_tool_names(), (
        f"'{forbidden}' e' registrato come tool MCP, ma {_REASON_GMAIL}"
    )


@pytest.mark.parametrize("fragment", FORBIDDEN_TOOL_NAME_FRAGMENTS)
def test_no_registered_tool_name_can_even_suggest_sending(fragment: str) -> None:
    """The stronger form of the two send bans above. A list of names knows only the
    spellings somebody thought of; this knows that nothing on this surface sends."""
    offenders = sorted(name for name in _registered_tool_names() if fragment in name)
    assert not offenders, f"{offenders} contengono '{fragment}', ma l'invio {_REASON_GMAIL}"


@pytest.mark.parametrize("method", FORBIDDEN_SERVICE_CALLS)
def test_no_tool_reaches_a_forbidden_operation_under_another_name(method: str) -> None:
    """The name check alone is not enough: a tool called `finalise_paperwork` that calls
    `.issue(...)`, or one called `tidy_up_rates` whose own call-through wrapper in
    `tools/timetracking.py` calls `.recalculate_rates(...)`, would both pass it. This
    looks at what the whole `tools/` package actually calls, not at any one tool's own
    name."""
    offenders_in_source = f".{method}(" in _tools_source()
    assert not offenders_in_source, (
        f"'.{method}(' compare in qualche modulo sotto tools/, ma quell'operazione "
        f"{_REASON} Il divieto vale sulla chiamata, non sul nome del tool che vi "
        "arriva: rinominare il tool o spostare la chiamata in un altro modulo non la "
        "rende ammissibile."
    )


def test_the_qualified_scan_tells_two_services_with_the_same_method_apart(tmp_path: Path) -> None:
    """Guards the guard, on the one property that makes it worth having. If
    `_receivers_of` collapsed to "some `.upsert(` exists", banning
    `FiscalProfileService.upsert` would also ban `EmitterProfileService.upsert` -- and a
    future tool for the issuer's own identity would fail the build with a message about
    the fiscal regime, which is how a policy stops being believed."""
    (tmp_path / "m.py").write_text(
        "def a(context):\n"
        "    return EmitterProfileService(context.session).upsert(data, context.actor)\n"
        "\n"
        "def b(context):\n"
        "    return FiscalProfileService(context.session).upsert(data, context.actor)\n",
        encoding="utf-8",
    )
    assert sorted(str(r) for r in _receivers_of("upsert", tmp_path)) == [
        "EmitterProfileService",
        "FiscalProfileService",
    ]


def test_the_qualified_scan_fails_closed_on_a_receiver_it_cannot_resolve(tmp_path: Path) -> None:
    """The other half, and the one that decides whether this mechanism is a ban or a
    suggestion: a call whose receiver the walk cannot attribute to a class is reported as
    unresolved, and the ban test below treats unresolved as forbidden. Anything else
    would let `some_container.fiscal.upsert(...)` through on the grounds that nobody
    could prove what it was."""
    (tmp_path / "m.py").write_text(
        "def a(context):\n    return context.services.fiscal.upsert(data)\n", encoding="utf-8"
    )
    assert _receivers_of("upsert", tmp_path) == [None]


@pytest.mark.parametrize(("service", "method"), FORBIDDEN_QUALIFIED_CALLS)
def test_no_tool_reaches_a_forbidden_operation_on_the_service_that_owns_it(
    service: str, method: str
) -> None:
    """The qualified half of `test_no_tool_reaches_a_forbidden_operation_under_another_
    name`. Same guarantee, expressed against the receiver instead of the bare name,
    because the bare name would either miss the operation or ban an unrelated one."""
    offenders = [
        owner or "un ricevitore non risolvibile"
        for owner in _receivers_of(method)
        if owner is None or owner == service
    ]
    assert not offenders, (
        f"'.{method}(' e' chiamato su {offenders} da qualche modulo sotto tools/, ma "
        f"'{service}.{method}' {_REASON} Il divieto vale su questa coppia "
        "servizio/metodo: un ricevitore che questo controllo non sa attribuire conta "
        "come violazione, perche' un divieto che si arrende all'ambiguita' non e' un "
        "divieto."
    )


def test_the_structural_ban_has_a_second_line_on_the_credential_itself() -> None:
    """The tool being absent is not, on its own, the guarantee this file claims.

    Everything above proves these operations are unreachable over *this transport*. A
    personal access token is not confined to it: `PatService.resolve` answers with
    `Actor(type="mcp", role=<the owner's role>)`, and `apps/api`'s `get_actor` accepts
    the same `Bearer pgc_...` header on every REST route. Until `AGENT_FORBIDDEN_ACTIONS`
    existed nothing in that package read `actor.type`, so a token handed to an agent on
    the written promise that it "may prepare but may not emit" could issue an invoice
    with one curl -- spending a register number and producing a FatturaPA.

    So the two lists have to stay one list. This test is the seam: `FORBIDDEN` names the
    tools that must not be registered, `AGENT_FORBIDDEN_ACTIONS` names the operations
    that must refuse an agent whatever transport it arrives on, and a name added to one
    and forgotten in the other is that gap coming back. The mapping is identity except
    for one pair, where the tool's advertised name and the action string the service
    passes to `require_admin` were chosen separately -- mapped here rather than renamed,
    because the tool name is the agent-facing contract and the action string is the
    audited one.
    """
    from pigrocrm.core.actor import AGENT_FORBIDDEN_ACTIONS

    tool_name_to_action = {"mark_invoice_transmitted": "mark_transmitted_externally"}
    attesi = {tool_name_to_action.get(name, name) for name in FORBIDDEN}

    assert attesi == set(AGENT_FORBIDDEN_ACTIONS), (
        "le due meta' del divieto sono divergenti: FORBIDDEN vieta il tool, "
        "AGENT_FORBIDDEN_ACTIONS vieta l'operazione a qualunque credenziale di tipo "
        "agente. Un nome aggiunto a una sola delle due lascia proprio il buco che la "
        "seconda e' stata scritta per chiudere -- l'assenza del tool non impedisce la "
        "stessa chiamata via REST con lo stesso token.\n"
        f"solo in FORBIDDEN: {sorted(attesi - set(AGENT_FORBIDDEN_ACTIONS))}\n"
        f"solo in AGENT_FORBIDDEN_ACTIONS: {sorted(set(AGENT_FORBIDDEN_ACTIONS) - attesi)}"
    )


async def test_the_sixteen_are_registered_exactly_when_the_installation_opted_in(
    mcp_session: Session, tmp_path: Path
) -> None:
    """Both halves of the switch, in one assertion, because them disagreeing is the
    failure worth catching.

    Everything above proves the tools are absent on a default installation -- the
    guarantee for everyone who never touches the setting. This adds the other direction:
    with `mcp_full_access` on, all sixteen are there.

    A half-open switch is worse than either honest state. Sixteen registered tools that
    all refuse wastes an agent's turns and reads as a broken product; sixteen open
    capabilities with no tool to reach them is a setting that does nothing. Worst is
    fifteen of sixteen: the operator believes the switch is on and the one refusal
    arrives at the moment somebody is issuing an invoice.

    This test asks the built server rather than reading the source, which is why it sits
    apart from its neighbours: registration is conditional at *runtime*, on a value no
    AST walk can see.

    `Settings(_env_file=None, ...)` and never the ambient settings -- this repository's
    own `.env` has the switch **on**, so a test that inherited it would assert the
    opposite of what it claims and pass anyway.
    """
    attore = Actor(id=None, type="mcp", role="admin")

    async def tool_names(full_access: bool, *, gmail: bool) -> set[str]:
        google = (
            {
                "google_client_id": "cid.apps.googleusercontent.com",
                "google_client_secret": "the-secret",
                "google_token_key": "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s=",
                "public_url": "https://crm.example.it",
            }
            if gmail
            else {}
        )
        server = build_server(
            lambda: mcp_session,
            lambda: attore,
            LocalFileStorage(str(tmp_path)),
            Settings(_env_file=None, mcp_full_access=full_access, **google),  # type: ignore[call-arg]
        )
        return {tool.name for tool in await server.list_tools()}

    # Without Google, the switch adds every forbidden tool except the ones that need a
    # mailbox to exist at all: those stay absent, not broken, exactly as `tools/gmail.py`
    # does on the same installation.
    chiusa = await tool_names(False, gmail=False)
    aperta = await tool_names(True, gmail=False)

    assert not (chiusa & set(FORBIDDEN)), "un'installazione chiusa non registra nessuno dei divieti"
    senza_google = set(FORBIDDEN) - FORBIDDEN_NEEDING_GMAIL
    mancanti = senza_google - aperta
    assert not mancanti, f"interruttore aperto ma questi tool non esistono: {sorted(mancanti)}"
    # And nothing else moved: opting in means exactly these more tools, not a different server.
    assert aperta - chiusa == senza_google

    # With Google configured as well, the switch adds all of them -- and still nothing
    # else.
    chiusa_google = await tool_names(False, gmail=True)
    aperta_google = await tool_names(True, gmail=True)

    assert not (chiusa_google & set(FORBIDDEN))
    assert aperta_google - chiusa_google == set(FORBIDDEN)


def test_the_privileged_module_is_the_only_place_they_appear() -> None:
    """Guards the exemption.

    The three scans above skip `privileged.py`, which is sound only while that file is
    genuinely the sole exemption and its calls are genuinely conditional. Both halves are
    checked here: every forbidden service call that appears anywhere under `tools/` must
    appear in that one file, and `server.py` must reach it only behind
    `mcp_full_access`.

    Without this, the exemption is a hole with a comment on it: a second file added to
    the skip list, or `privileged` imported unconditionally, would leave every test above
    green while the sixteen became reachable on an installation that never opted in.
    """
    unconditional = _tools_source()
    privileged = PRIVILEGED.read_text(encoding="utf-8")

    for method in FORBIDDEN_SERVICE_CALLS:
        assert f".{method}(" not in unconditional, (
            f"'.{method}(' compare in un modulo che viene registrato sempre"
        )
        assert f".{method}(" in privileged, (
            f"'.{method}(' non compare in privileged.py: o il tool non esiste, o e' "
            "altrove, e in entrambi i casi l'esenzione qui sopra sta coprendo la cosa "
            "sbagliata"
        )

    server_source = (TOOLS_DIR.parent / "server.py").read_text(encoding="utf-8")
    assert "mcp_full_access" in server_source
    guardia = server_source.index("if resolved_settings.mcp_full_access:")
    assert server_source.index("import privileged") > guardia, (
        "privileged e' importato fuori dalla guardia: il modulo verrebbe registrato "
        "sempre e l'esenzione delle scansioni diventerebbe un buco"
    )
