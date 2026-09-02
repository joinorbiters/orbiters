"""The complement of `test_mcp_invoice_ban.py`, and the half of the product's central
claim that had no test at all.

That file proves sixteen named operations are **not** reachable as MCP tools. Nothing
proved the other direction: that every *other* public service method is. The claim the
product actually makes is "an agent can do anything a user can, minus a deliberate,
named, tested list of exclusions", and a ban list on its own only tests the subtraction.
A service method added without a tool is a silent hole -- the ban list stays honest while
the coverage quietly rots, and nobody finds out, because the only artefact that would
have noticed is a list somebody has to remember to update.

So this is mechanical on both sides. The **inventory** is an AST sweep of every
`*Service` class under `packages/core`, and the **reachability** is an AST walk of every
call in `tools/` and `resources/`, resolved back to the class that receives it. Neither
is a list. What is a list -- deliberately, and in one place -- is the *taxonomy of
exclusions* below: each unexposed method carries the category it belongs to and the
reason it is in that category, because "there is no tool for this" and "there must never
be a tool for this" are different statements and only one of them is a policy.

Adding a public service method therefore fails this file until somebody either writes
the tool or writes down why not. That is the entire point: the decision is forced at the
moment it is cheap, and it is recorded next to the sixteen refusals it has to live
beside.

Two properties of the walk are worth stating, because they are what makes the result
trustworthy rather than merely green:

  * reachability resolves the *receiver*, not the method name. `.create(` appears in the
    tool modules a dozen times over six different services, so a substring scan would
    call every `create` in the codebase covered. The walk binds `ServiceClass(...)`,
    `x = ServiceClass(...)` and the module-private factories (`_invoices(context) ->
    InvoiceService`) that `tools/invoices.py` and `tools/documents.py` actually use, and
    attributes each call to the class it lands on.
  * it covers `resources/` as well as `tools/`. The ban test scans only `tools/`, which
    is right for its question -- `@mcp.tool()` decorators exist nowhere else -- but wrong
    for this one: a resource read is agent-reachable too, and `PipelineService.get` is
    reachable *only* from there. The same breadth also closes a gap in the ban itself,
    asserted below: a forbidden method reached from a resource template would evade a
    tools-only scan while being just as callable by an agent.
"""

import ast
from pathlib import Path

import pytest
from test_mcp_invoice_ban import FORBIDDEN_QUALIFIED_CALLS, FORBIDDEN_SERVICE_CALLS

MCP_SRC = Path(__file__).resolve().parents[1] / "src" / "pigrocrm_mcp"
TOOLS_DIR = MCP_SRC / "tools"
RESOURCES_DIR = MCP_SRC / "resources"
CORE_DIR = Path(__file__).resolve().parents[3] / "packages" / "core" / "src" / "pigrocrm" / "core"

Method = tuple[str, str]


# --- the taxonomy ------------------------------------------------------------------
#
# Six categories, because there are six genuinely different reasons a public service
# method has no tool, and collapsing them into one regex or one "unexposed" set would
# hide the only distinction that matters: which of these are decisions and which are
# accidents. Every entry is keyed by `(service class, method)` -- never by the bare
# method name, which `create`, `get`, `list`, `update` and `restore` all share across
# half a dozen services.


# 1. Forbidden. The sixteen operations of `test_mcp_invoice_ban.py`, which owns the
#    policy; they appear here only so that the sweep's arithmetic accounts for them, and
#    a test below asserts this block names exactly the same methods that file bans. If
#    the two ever disagree, one of them is out of date and neither can be trusted.
#    `FiscalProfileService.upsert` is the one banned as a `(service, method)` pair rather
#    than by bare name -- `EmitterProfileService` has an `upsert` too -- which is the
#    shape this table has used all along, and the reason the comparison test below
#    compares the qualified bans as pairs and the rest as names.
_VIETATE: dict[Method, str] = {
    ("InvoiceService", "issue"): "atto fiscale irreversibile (slice 3 §11)",
    ("InvoiceService", "annul"): "atto fiscale irreversibile (slice 3 §11)",
    ("InvoiceService", "mark_transmitted_externally"): "atto fiscale (slice 3 §11)",
    ("InvoiceService", "export_xml"): "esiste solo per una fattura emessa (slice 3 §11)",
    ("TimeEntryService", "recalculate_rates"): "riscrive il passato (slice 4 §11)",
    ("TimeEntryService", "update_user_rates"): "configurazione tariffaria (slice 4 §11)",
    ("TimeEntryService", "update_deal_rate"): "configurazione tariffaria (slice 4 §11)",
    ("CostCategoryService", "create_cost_category"): "configurazione (slice 4 §11)",
    ("CostCategoryService", "update_cost_category"): "configurazione (slice 4 §11)",
    ("CostCategoryService", "archive_cost_category"): "configurazione (slice 4 §11)",
    ("CostCategoryService", "unarchive_cost_category"): (
        "configurazione: e' `archive_cost_category` nel verso opposto, e slice 4 §11 "
        "non l'aveva elencata per omissione, non per distinzione"
    ),
    ("FiscalProfileService", "upsert"): (
        "decide aliquota, natura, bollo e riferimento normativo di ogni riga emessa "
        "(slice 3 §11: `update_fiscal_profile`)"
    ),
    ("PeriodLockService", "close_period"): "chiusura di periodo (slice 4 §11)",
    ("PeriodLockService", "reopen_period"): "riapertura di periodo (slice 4 §11)",
    ("AnalyticsService", "bind_time_to_invoice"): "precede l'emissione (slice 4 §11)",
    ("AnalyticsService", "get_fiscal_estimate"): "posizione fiscale del titolare (slice 4 §11)",
}


# 2. Internal. Called by other code inside `packages/core`, not by an adapter: none of
#    them takes an `actor`, which is the mechanical signature of "this is not an
#    operation somebody performs" -- there is no permission to check because there is no
#    caller with a role. `TimeReportService.variables_for` is the one exception to the
#    no-actor rule and is listed for the same reason: it is the intermediate step of
#    `render_pdf`, not an operation of its own.
_INTERNE: dict[Method, str] = {
    ("ActivityService", "record"): "scrive la timeline per conto di un altro servizio",
    ("CostCategoryService", "require_active"): "validazione interna di CostService",
    ("DocumentService", "storage_key_for"): "costruisce una chiave di storage",
    ("EmitterProfileService", "as_template_values"): "alimenta il renderer dei template",
    ("FieldDefinitionService", "specs_for"): "alimenta la validazione dei campi custom",
    ("FiscalProfileService", "snapshot"): "lettura interna del regime, senza actor",
    ("GmailOAuthService", "redirect_uri"): "e' l'URL fisso che Google confronta "
    "carattere per carattere, non un'operazione",
    ("PeriodLockService", "assert_writable"): "guardia invocata dagli altri servizi",
    ("PeriodLockService", "is_closed"): "guardia invocata dagli altri servizi",
    ("PipelineService", "default_stage"): "risolve lo stage iniziale di un nuovo deal",
    ("TemplateService", "declared_variables"): "parsing interno usato da describe",
    ("EmailDraftService", "repo_draft"): "restituisce la riga ORM al percorso di invio "
    "(B2-5) e alla riconciliazione (B2-6), che scrivono `send_state` e "
    "`sent_gmail_message_id`: colonne che nessuno schema accetta in ingresso perche' "
    "sono fatti, non input. Non prende `actor`, che e' la firma di \"non e' "
    "un'operazione che qualcuno compie\"",
    ("TimeReportService", "variables_for"): "passo intermedio di render_pdf/build_xlsx",
    ("UserService", "count"): "conta gli utenti per il bootstrap del primo admin",
}


# 3. Credentials and accounts. The one category where exposure would be a privilege
#    escalation *by construction* rather than by degree: the agent's own key is a PAT,
#    which inherits its owner's full role and never expires (residuo R10), so a tool that
#    minted or revoked one would let a token extend or destroy its own access. Creating
#    users is the same hole with a longer fuse.
#    Tutto Gmail, tranne le tre letture, sta qui -- e la decisione e' stata presa in
#    B1-14, che possiede la superficie MCP di 5B. La riga che la divide non e'
#    "lettura contro scrittura" ma *di chi e' la risorsa, e di chi la decisione*:
#
#      * quello che l'agente puo' fare e' leggere lo specchio gia' archiviato in
#        `gmail_messages` e lo stato della credenziale (`list_gmail_messages`,
#        `get_gmail_message`, `describe_gmail_account`). Nessuna delle tre chiama
#        Google, nessuna consuma la quota Gmail di qualcuno, nessuna esercita un
#        consenso: leggono righe che questo CRM ha gia' deciso di tenere;
#      * quello che non puo' fare e' *andare a prendere* la posta (`sync`,
#        `backfill`), collegare o scollegare una casella, decidere cosa il CRM
#        conserva, e inviare. In ognuno di questi casi la risorsa o la decisione
#        appartengono alla persona, non all'agente.
#
#    `start` restituisce un URL di consenso che solo un browser umano puo' percorrere
#    -- un agente che lo ricevesse non potrebbe fare altro che passarlo a qualcuno --
#    e `complete` richiede un `code` che esiste solo dentro quel redirect, quindi
#    nessuno dei due e' eseguibile da un canale strumentale. `disconnect` e' il verso
#    opposto: distrugge una credenziale verso un servizio *terzo* e, con
#    `delete_messages`, la corrispondenza archiviata.
#
#    L'assenza dell'invio non e' registrata qui perche' in 5B-1 non esiste ancora un
#    servizio che invii: il divieto strutturale sui nomi degli strumenti vive in
#    `test_mcp_invoice_ban.py`, che possiede i divieti per costruzione.
_CREDENZIALI: dict[Method, str] = {
    ("GmailOAuthService", "start"): "il consenso Google si da' da un browser, non da "
    "un tool: l'URL di autorizzazione non e' percorribile da un agente",
    ("GmailOAuthService", "complete"): "il `code` esiste solo dentro il redirect di "
    "Google verso il callback: nessun agente puo' averlo",
    ("GmailOAuthService", "disconnect"): "revocare l'accesso a una casella di terzi (e "
    "cancellarne la corrispondenza) e' una decisione della persona",
    ("GmailSyncService", "sync"): (
        "il consenso a leggere la casella e' della persona, e lo e' anche il momento in "
        "cui viene esercitato: `sync` va a prendere posta da un servizio terzo, sotto "
        "l'autorizzazione OAuth di quella persona e a carico della sua quota Gmail, "
        "quindi un agente che lo invocasse (o lo ritentasse) spenderebbe una risorsa "
        "che non e' sua. Non toglie nulla all'agente: quello che serve leggere e' la "
        "copia gia' archiviata in `gmail_messages`, che il pulsante o il cron della "
        "persona tengono aggiornata, ed e' su quella che B1-14 ha costruito "
        "`list_gmail_messages` e `get_gmail_message`"
    ),
    ("GmailSyncService", "backfill"): (
        "stessa ragione di `sync`, e con una scala diversa: `backfill(full=True)` "
        "rilegge una casella dall'inizio, quindi e' la richiesta piu' costosa che "
        "questa fetta sappia fare sulla quota Gmail di quella persona, e la spec 4.4 la "
        "vuole esplicita e iniziata da un umano proprio per questo. B1-14 aveva "
        "previsto un `backfill_gmail` e ha deciso di non scriverlo: esporre la "
        "richiesta *piu'* costosa mentre `sync` -- la meno costosa, e per la stessa "
        "ragione -- resta chiusa non e' una superficie che qualcuno possa spiegare. "
        "L'esclusione e' quindi permanente come le tre di `GmailOAuthService`, non piu' "
        "provvisoria"
    ),
    ("GoogleAccountService", "usable"): (
        "non e' un'operazione ma un cancello: lo chiamano `sync` e il percorso di invio "
        "*prima* di comporre qualsiasi cosa. Un tool che lo esponesse offrirebbe "
        "all'agente di chiedere un permesso invece di esercitarlo"
    ),
    ("GoogleAccountService", "mark_revoked"): (
        "registra un fatto che comunica Google, non una decisione di qualcuno: la "
        "chiama il solo punto che puo' apprenderlo, il rinnovo del token che riceve "
        "`invalid_grant`. Un agente che potesse marcare revocata una credenziale sana "
        "spegnerebbe Gmail a una persona senza che nulla sia successo"
    ),
    ("GoogleAccountService", "set_store_bodies"): (
        "decide se il CRM conserva il *corpo* della corrispondenza di qualcuno: e' la "
        "stessa famiglia di `disconnect`, una scelta della persona sui propri dati e "
        "non un'operazione che l'agente compie al posto suo"
    ),
    ("EmailSendService", "send"): (
        "**l'invio non sara' mai un tool**, e questa e' l'unica riga di 5B-2 che non "
        "aspetta B2-10: e' la decisione permanente gia' registrata piu' sotto, ora che "
        "il metodo dietro esiste. Un'email che parte dall'indirizzo del titolare parla "
        "in suo nome a un cliente, non si richiama, e il destinatario e' una persona "
        "esterna al CRM: stessa famiglia di `GmailOAuthService.disconnect`, con in piu' "
        "che un agente che tenesse la *lettura* della posta e l'*invio* sullo stesso "
        "canale avrebbe la sorgente di injection e il canale di esfiltrazione insieme. "
        "Il divieto per costruzione sui nomi degli strumenti vive in "
        "`test_mcp_invoice_ban.py`, che possiede i divieti"
    ),
    ("EmailSendService", "reconcile"): (
        "stessa ragione di `sync`, in piccolo: va a chiedere a Gmail, sotto il consenso "
        "OAuth della persona e a carico della sua quota, se un messaggio partito dalla "
        "sua casella e' arrivato. E' la meta' di riparazione dell'invio -- il pulsante "
        "«verifica» accanto a «esito da verificare» -- quindi appartiene a chi ha premuto "
        "Invia. Se B2-10 decidesse altrimenti dovrebbe spiegare perche' un agente puo' "
        "interrogare una casella che non puo' sincronizzare"
    ),
    ("EmailSendService", "reconcile_all"): (
        "non e' un'operazione che qualcuno compie: la chiama `GmailSyncService._run_cycle` "
        "all'inizio di ogni ciclo, sotto il consenso gia' verificato li'. Esporla "
        "significherebbe offrire all'agente il ciclo di sync per un'altra porta"
    ),
    ("PatService", "create"): "un agente non conia le proprie credenziali",
    ("PatService", "list"): "l'elenco dei token e' materiale di sicurezza",
    ("PatService", "revoke"): "revocare token e' amministrazione dell'account",
    ("PatService", "resolve"): "e' il passo di autenticazione, non un'operazione",
    ("RefreshTokenService", "issue"): "sessione del browser, non superficie agentica",
    ("RefreshTokenService", "consume"): "sessione del browser, non superficie agentica",
    ("UserService", "create"): "creare utenti e' amministrazione dell'account",
    ("UserService", "update"): "cambiare ruoli e' amministrazione dell'account",
    ("UserService", "list"): "l'anagrafica utenti non serve a nessun tool",
    ("UserService", "authenticate"): "e' il passo di login, non un'operazione",
}


# 4. Configuration. These change the *shape* of the CRM -- which stages exist, which
#    custom fields exist, which templates exist, who the issuer is -- rather than its
#    content. The line is the same one slice 4 §11 already drew for cost categories and
#    rates: an agent records and reads within a configuration, and a person decides what
#    the configuration is. Exposing them would also mean an agent could rewrite the field
#    definitions its own `describe_schema` output is derived from.
_CONFIGURAZIONE: dict[Method, str] = {
    ("CostCategoryService", "seed_defaults"): "installa le categorie iniziali",
    ("EmitterProfileService", "upsert"): "identita' fiscale dell'emittente",
    ("FieldDefinitionService", "create"): "definisce lo schema, non lo popola",
    ("FieldDefinitionService", "update"): "definisce lo schema, non lo popola",
    ("FieldDefinitionService", "archive"): "definisce lo schema, non lo popola",
    ("FieldDefinitionService", "unarchive"): "definisce lo schema, non lo popola",
    ("FieldDefinitionService", "list"): "describe_schema espone gia' i campi vivi",
    ("PipelineService", "create"): "la forma della pipeline e' una decisione umana",
    ("PipelineService", "update"): "la forma della pipeline e' una decisione umana",
    ("PipelineService", "delete"): "la forma della pipeline e' una decisione umana",
    ("PipelineService", "seed_defaults"): "installa la pipeline iniziale",
    ("TemplateService", "create"): "i template sono configurazione documentale",
    ("TemplateService", "update"): "i template sono configurazione documentale",
    ("TemplateService", "activate"): "i template sono configurazione documentale",
    ("TemplateService", "deactivate"): "i template sono configurazione documentale",
    ("TemplateService", "seed_defaults"): "installa i template iniziali",
}


# 5. Bytes. The MCP surface returns identifiers and URLs, never file content (spec slice
#    2 §7): an agent that could pull a PDF or an XLSX down a tool channel would be moving
#    the artefact out of the storage layer that versions and audits it.
_BYTE: dict[Method, str] = {
    ("DocumentService", "download"): "l'MCP restituisce URL, mai byte",
    ("InvoiceService", "download"): "l'MCP restituisce URL, mai byte",
    ("TimeReportService", "build_xlsx"): "l'MCP restituisce URL, mai byte",
    ("TimeReportService", "render_pdf"): "l'MCP restituisce URL, mai byte",
}


# 6. Reached under another name, or reserved for the person. The residue: operations an
#    existing tool already covers through a different service method, and the handful
#    that are deliberately the human's half of a two-step. They are not forbidden -- a
#    future slice could expose any of them -- which is exactly why they are not in the
#    ban list and why each has to say so out loud.
#
#    Five entries left this block, and they are the reason it must stay small.
#    `PeriodLockService.list_locks`, `TemplateService.preview`,
#    `DocumentService.regenerate`, `soft_delete` and `restore` were all recorded here as
#    "non ha ancora un tool" / "e' una decisione della persona" -- and each turned out to
#    be a plain read, or a reversible audited write whose inverse this surface already
#    exposes for customers, deals, people, costs and time entries. A reason that only
#    says "nobody wrote the tool" is a placeholder wearing the clothes of a decision;
#    this category is for the ones that survive being asked why, and the only way to keep
#    that true is to delete the ones that do not the moment the tool is written.
_COPERTE_O_UMANE: dict[Method, str] = {
    ("DocumentService", "create"): "create_document_from_template e' l'unica creazione "
    "che non richieda di caricare byte",
    ("DocumentService", "update"): "titolo e campi custom: nessun agente ha motivo di "
    "riscriverli su un documento gia' reso",
    ("DocumentService", "add_version"): "richiede byte gia' resi, che l'MCP non produce",
    ("FiscalProfileService", "get"): "describe_fiscal_profile espone gia' il regime",
    ("InvoiceService", "update"): "note interne e campi custom, congelati dopo "
    "l'emissione: nessuna audience agentica",
    ("InvoiceService", "soft_delete"): "cancellare una bozza di fattura resta una "
    "decisione della persona",
    ("InvoiceService", "confirm_proforma"): "e' la conferma umana che precede "
    "l'emissione: l'agente prepara, la persona conferma",
    ("TemplateService", "get"): "describe_template espone gia' il template",
    # Le cinque righe qui sotto sono di 5B-2 e hanno una scadenza dichiarata: **B2-10 e'
    # il task che decide la superficie MCP di questa fetta**, come B1-14 ha deciso quella
    # di 5B-1. Fino a li' la ragione non e' "nessuno ha scritto il tool" -- che questo
    # blocco vieta esplicitamente -- ma questa: **l'invio non sara' mai un tool** (la
    # riga permanente e' su `EmailSendService.send`, in `_CREDENZIALI`), quindi un
    # `create_email_draft` offrirebbe a un agente di scrivere un messaggio che nessuno
    # strumento potra' mai spedire: meta' operazione, e l'altra meta' non e' rinviata,
    # e' esclusa. Se quella meta' bozza valga comunque la superficie lo decide B2-10.
    ("EmailDraftService", "create"): "il composer e' della persona finche' B2-10 non "
    "decide la superficie di 5B-2: un agente scriverebbe una bozza che nessun tool "
    "puo' inviare, perche' l'invio non sara' mai esposto",
    ("EmailDraftService", "update"): "riscrivere il testo che partira' a nome del "
    "titolare e' la stessa decisione di `create`, e la prende B2-10",
    ("EmailDraftService", "get"): "leggere una bozza non ancora inviata non serve a "
    "nessun tool esistente: `list_gmail_messages` espone la corrispondenza gia' "
    "archiviata, che e' l'unica di cui un agente abbia bisogno per lavorare",
    ("EmailDraftService", "delete"): "cancellare il testo non spedito di qualcuno e' "
    "una decisione della persona, e non ha inverso: la riga sparisce davvero",
    ("EmailDraftService", "list"): "elenca bozze non inviate, cioe' corrispondenza "
    "privata che non e' ancora partita: se servira' a un agente lo dira' B2-10",
    ("SollecitiService", "candidates"): "e' una lettura pura -- nessuna chiamata a "
    "Google, nessuna quota, nessun invio -- e per questo l'unica di 5B-2 che potrebbe "
    "davvero diventare un tool: e' *la* parte laboriosa, incrociare scadenze e "
    "pagamenti, ed e' esattamente cio' che un agente farebbe bene. Non e' esposta qui "
    "solo perche' la superficie MCP di questa fetta la decide B2-10, che possiede la "
    'scelta; la ragione non e\' "nessuno ha scritto il tool" ma "la decisione ha un '
    'proprietario e una scadenza"',
}


ESCLUSIONI: dict[Method, str] = {
    **_VIETATE,
    **_INTERNE,
    **_CREDENZIALI,
    **_CONFIGURAZIONE,
    **_BYTE,
    **_COPERTE_O_UMANE,
}


# --- the sweep ---------------------------------------------------------------------


def _service_methods() -> dict[str, list[str]]:
    """Every `*Service` class under `packages/core`, with its public methods.

    The naming convention is the enumeration: a class ending in `Service` is a domain
    service by this codebase's own rule, and every adapter reaches the domain through
    one. Methods starting with `_` are private by the same convention and are not part
    of anybody's surface.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(CORE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and node.name.endswith("Service")):
                continue
            found[node.name] = sorted(
                member.name
                for member in node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
                and not member.name.startswith("_")
            )
    return found


def _produced_by(func: ast.expr, known: set[str], factories: dict[str, str]) -> str | None:
    """Which service class a call expression yields: the class itself when the callee is
    one, and the class a module-private factory declares as its return type otherwise."""
    if not isinstance(func, ast.Name):
        return None
    return func.id if func.id in known else factories.get(func.id)


def _reachable(known: set[str]) -> set[Method]:
    """Every `(service class, method)` an agent can reach through `tools/` or
    `resources/`.

    Resolves the receiver rather than matching the method name, which is what makes the
    answer usable: the three call shapes this package actually uses are
    `ServiceClass(context.session).m(...)`, `svc = ServiceClass(...)` followed by
    `svc.m(...)`, and the module-private factories `_invoices(context)` /
    `_documents(context)` whose return annotation names the class. A name-only scan
    would report `CustomerService.create` as covered because *some* `.create(` exists
    somewhere under `tools/`, which is precisely the false green this file exists to
    avoid.
    """
    found: set[Method] = set()
    for base in (TOOLS_DIR, RESOURCES_DIR):
        for path in sorted(base.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            factories: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    returns = node.returns
                    if isinstance(returns, ast.Name) and returns.id in known:
                        factories[node.name] = returns.id

            bindings: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    produced = _produced_by(node.value.func, known, factories)
                    if produced is not None:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                bindings[target.id] = produced

            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                receiver = node.func.value
                owner = None
                if isinstance(receiver, ast.Call):
                    owner = _produced_by(receiver.func, known, factories)
                elif isinstance(receiver, ast.Name):
                    owner = bindings.get(receiver.id)
                if owner is not None:
                    found.add((owner, node.func.attr))
    return found


SERVICES = _service_methods()
REACHABLE = _reachable(set(SERVICES))
PUBLIC_METHODS = [(cls, method) for cls, methods in SERVICES.items() for method in methods]


# --- guards on the guard -----------------------------------------------------------
#
# Both halves of this file are AST walks over paths built from `__file__`. Either one
# returning an empty set would make every assertion below pass while checking nothing,
# and an empty set is exactly what a moved directory or a renamed convention produces.


def test_the_service_sweep_finds_the_services_it_should() -> None:
    assert {"CustomerService", "InvoiceService", "TimeEntryService"} <= set(SERVICES)
    assert len(SERVICES) > 15
    assert "create" in SERVICES["CustomerService"]
    # Private helpers stay out: `_check_owner` is not part of anybody's surface.
    assert not [m for methods in SERVICES.values() for m in methods if m.startswith("_")]


def test_the_reachability_walk_resolves_all_three_call_shapes() -> None:
    """One assertion per shape, named after the module that uses it. If the resolver
    silently stopped understanding the factory shape, every method of `InvoiceService`
    and `DocumentService` would look unexposed and this file would demand exclusions for
    operations that have working tools."""
    assert ("CustomerService", "create") in REACHABLE  # ServiceClass(...).m(...)
    assert ("CustomerService", "list") in REACHABLE  # svc = ServiceClass(...); svc.m()
    assert ("InvoiceService", "create") in REACHABLE  # _invoices(context).m(...)
    assert ("PipelineService", "get") in REACHABLE  # reached only from resources/


def test_the_walk_attributes_a_call_to_its_own_receiver() -> None:
    """The property that separates this from a substring scan. `.create(` appears under
    `tools/` for customers, people, deals, costs, time entries and invoices -- and for
    none of the four services below, each of which defines a `create` of its own. A
    name-only scan would report all four as covered."""
    for service in ("UserService", "PatService", "PipelineService", "FieldDefinitionService"):
        assert "create" in SERVICES[service]
        assert (service, "create") not in REACHABLE


# --- the claim ---------------------------------------------------------------------


@pytest.mark.parametrize(("service", "method"), PUBLIC_METHODS, ids=lambda p: p)
def test_every_public_service_method_is_a_tool_or_a_named_exclusion(
    service: str, method: str
) -> None:
    """The half of the product's claim that had no test. A new service method fails here
    until it has a tool or a reason -- which is the only moment at which writing the
    reason is cheap."""
    assert (service, method) in REACHABLE or (service, method) in ESCLUSIONI, (
        f"'{service}.{method}' non e' raggiungibile da nessun tool o resource MCP e non "
        "compare fra le esclusioni dichiarate in questo file. Il prodotto promette che "
        "un agente possa fare tutto quello che puo' fare una persona, meno un elenco "
        "deliberato: o esiste un tool, o esiste una riga che dice perche' no. Scegliere "
        "la categoria e' la decisione; lasciarla implicita e' il buco."
    )


@pytest.mark.parametrize(("service", "method"), sorted(ESCLUSIONI), ids=lambda p: p)
def test_every_declared_exclusion_still_names_a_real_method(service: str, method: str) -> None:
    """The other direction, which is what keeps the taxonomy from becoming folklore: a
    renamed or deleted service method must not leave a reason behind explaining why
    something that no longer exists is not exposed."""
    assert service in SERVICES, f"'{service}' non e' piu' un servizio di packages/core"
    assert method in SERVICES[service], (
        f"'{service}.{method}' non esiste piu': l'esclusione va rimossa insieme al metodo"
    )


@pytest.mark.parametrize(("service", "method"), sorted(ESCLUSIONI), ids=lambda p: p)
def test_no_declared_exclusion_is_actually_reachable(service: str, method: str) -> None:
    """An exclusion that is reachable is a false statement, and the most expensive kind:
    it reads as a considered refusal while the operation is in fact exposed. This is what
    catches somebody adding a tool for a method and forgetting the table -- including,
    and especially, one of the fourteen forbidden ones."""
    assert (service, method) not in REACHABLE, (
        f"'{service}.{method}' e' dichiarato non esposto ma un tool o una resource lo "
        "chiama davvero"
    )


def test_the_forbidden_block_names_exactly_what_the_ban_test_bans() -> None:
    """The two files must not drift. `test_mcp_invoice_ban.py` owns the policy; this file
    re-states it as a category so that the arithmetic of the sweep adds up, and
    re-stating a list is how lists diverge. Compared the way each half of the ban is
    written: the bare-name bans on names, and the qualified ones as the `(service,
    method)` pairs they are -- comparing those on the name alone would accept
    `EmitterProfileService.upsert` standing in for `FiscalProfileService.upsert`, which
    is the exact confusion the qualified list exists to prevent."""
    assert {method for _, method in _VIETATE} == set(FORBIDDEN_SERVICE_CALLS) | {
        method for _, method in FORBIDDEN_QUALIFIED_CALLS
    }
    assert set(FORBIDDEN_QUALIFIED_CALLS) <= set(_VIETATE)


@pytest.mark.parametrize(("service", "method"), FORBIDDEN_QUALIFIED_CALLS)
def test_no_qualified_ban_is_reachable_from_a_resource_either(service: str, method: str) -> None:
    """The same extension for the qualified half, asserted on the pair: a resource that
    called `FiscalProfileService(...).upsert(...)` would be as agent-reachable as a tool
    that did, while the ban test's own scan reads `tools/` only."""
    assert (service, method) not in REACHABLE, (
        f"'{service}.{method}' e' raggiungibile attraverso tools/ o resources/, ma e' "
        "una delle operazioni escluse per costruzione dalla superficie MCP"
    )


@pytest.mark.parametrize("method", sorted(set(FORBIDDEN_SERVICE_CALLS)))
def test_no_forbidden_operation_is_reachable_from_a_resource_either(method: str) -> None:
    """Extends the ban's guarantee by the one directory the ban test does not read.
    `test_mcp_invoice_ban.py` scans `tools/` only, which is right for its own question --
    `@mcp.tool()` decorators live nowhere else -- but a resource template that called
    `.issue(...)` would be just as reachable by an agent while leaving no trace under
    `tools/` at all. `REACHABLE` covers both directories, so asserting against it closes
    that gap without duplicating the ban."""
    offenders = [service for service, reached in REACHABLE if reached == method]
    assert not offenders, (
        f"'.{method}(' e' raggiungibile da {offenders} attraverso tools/ o resources/, "
        "ma e' una delle operazioni escluse per costruzione dalla superficie MCP"
    )
