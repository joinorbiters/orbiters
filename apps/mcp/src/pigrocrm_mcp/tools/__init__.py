from collections.abc import Callable
from typing import Annotated, Any, cast
from uuid import UUID

from mcp.server import MCPServer
from pydantic import WithJsonSchema

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.analytics.schemas import BudgetQuery, PeriodPnlQuery
from pigrocrm.core.customers.schemas import CustomerListQuery, CustomerUpdate
from pigrocrm.core.dashboard.schemas import PeriodoQuery
from pigrocrm.core.db import SortDirection
from pigrocrm.core.deals.schemas import DealListQuery, DealUpdate
from pigrocrm.core.documents.schemas import DocumentListQuery
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.invoices.schemas import InvoiceListQuery
from pigrocrm.core.people.schemas import PersonListQuery, PersonUpdate
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm.core.search.schemas import PER_CLASS_LIMIT, SearchQuery
from pigrocrm.core.timetracking.schemas import (
    ANNO_MAX,
    ANNO_MIN,
    CostListQuery,
    CostUpdate,
    TimeEntryListQuery,
    TimeEntryUpdate,
)
from pigrocrm_mcp.context import McpContext
from pigrocrm_mcp.tools import automations as automation_tools
from pigrocrm_mcp.tools import customers, deals, documents, invoices, people, timetracking
from pigrocrm_mcp.tools import dashboard as dashboard_tools
from pigrocrm_mcp.tools import search as search_tools

# `changes` stays a plain `dict[str, Any]` at runtime -- deliberately, not an
# oversight. Typing it directly as `CustomerUpdate` (etc.) would make the MCP SDK
# validate the nested object *before* calling the guarded tool function at all
# (`FuncMetadata.validate_arguments`, invoked from `Tool.run` ahead of `self.fn`,
# confirmed by instrumenting both and observing which one a nested type error
# actually reaches — the guarded function body never runs). A caller's malformed
# value would then surface as raw pydantic text, one guard-decorator edit
# powerless to fix, since the exception never reaches the decorator's own
# try/except in the first place.
#
# `WithJsonSchema` overrides only the *displayed* schema, not the runtime type:
# the model advertised to `list_tools()` is the real Customer/Person/DealUpdate
# shape (so a caller sees the actual field names instead of an opaque empty
# object), while the value the tool function receives is still an unvalidated
# dict. The real `CustomerUpdate(**data)` construction that validates it happens
# inside `tools/customers.py::update` (unchanged from before this override),
# squarely inside the guarded call — exactly where `_guard`'s `except ValueError`
# can turn a bad value into rendered guidance instead of a raw pydantic dump.
# Verified against the installed SDK with a throwaway tool before adopting this
# for real: `list_tools()` showed the nested model's real properties, and a
# wrong-typed nested value reached the guard rather than bypassing it.
CustomerChanges = Annotated[dict[str, Any], WithJsonSchema(CustomerUpdate.model_json_schema())]
PersonChanges = Annotated[dict[str, Any], WithJsonSchema(PersonUpdate.model_json_schema())]
DealChanges = Annotated[dict[str, Any], WithJsonSchema(DealUpdate.model_json_schema())]

# Same runtime-permissive / schema-only-strict split as the `*Changes` aliases
# above, applied to a scalar instead of a nested object: the parameter stays a
# plain `str | None` (so a malformed date string is rejected by `DealCreate`'s
# own `date` field inside the guarded call, not by the SDK ahead of it), while
# `format: date` is added purely for what `list_tools()` displays.
IsoDateStr = Annotated[
    str | None,
    WithJsonSchema(
        {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}], "default": None}
    ),
]

# Final review item 9: the same runtime-permissive / schema-only-strict split as
# `*Changes`/`IsoDateStr` above, applied to every remaining *scalar* numeric
# parameter -- `limit` and `probabilita` named explicitly by the review, the three
# deal money fields swept in alongside them for the identical reason. A bare
# `int`/`float` type on a tool parameter is what let a wrong-TYPE argument (not a
# wrong-value one) be rejected by the SDK's own pre-call argument coercion, before
# the guarded call -- and therefore before `_guard`'s `except ValueError` -- ever
# ran: `search_customers(limit="molti")` came back as a raw, multi-line, English
# pydantic dump with an `errors.pydantic.dev` link, exactly what spec §8.2 forbids,
# the same failure `changes`/`data_chiusura_prevista` were already fixed for.
# `int | str`/`float | str` accept anything a JSON number *or* a JSON string can be
# at the SDK layer -- confirmed against the installed SDK: a real number passes
# through unchanged, and a non-numeric string like "molti" passes through as a
# string instead of being rejected there. The `*ListQuery`/`DealCreate` schema each
# of these feeds into is what actually enforces "must be a number" -- inside the
# guarded call, where pydantic's own lax coercion still accepts a numeric *string*
# (e.g. "50" -> 50) and a genuine mismatch becomes rendered guidance instead of a
# raw dump.
BoundedLimit = Annotated[
    int | str,
    WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 200, "default": 50}),
]
# The palette's own per-class limit, and deliberately not `BoundedLimit`: that alias
# advertises 1..200 with a default of 50, which are the paged entity lists' bounds and not
# these. An agent told it may ask for two hundred results per class would be told something
# `SearchQuery.limite` (1..20, default 5) then refuses. The runtime type stays `int | str`
# for exactly the reason `BoundedLimit`'s own comment gives above.
SearchLimite = Annotated[
    int | str,
    WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 20, "default": PER_CLASS_LIMIT}),
]
OptionalProbabilita = Annotated[
    int | str | None,
    WithJsonSchema(
        {
            "anyOf": [{"type": "integer", "minimum": 0, "maximum": 100}, {"type": "null"}],
            "default": None,
        }
    ),
]
OptionalMoney = Annotated[
    float | str | None,
    WithJsonSchema({"anyOf": [{"type": "number"}, {"type": "null"}], "default": None}),
]

# Same runtime-permissive / schema-only-strict split as `BoundedLimit` above: the
# parameter stays a plain `str` so a wrong value is rejected by `set_offer_state`'s
# own `Literal` inside the guarded call (rendered as guidance, not a raw SDK
# rejection), while `list_tools()` shows the real four states an agent may choose
# from.
OfferStateArg = Annotated[
    str,
    WithJsonSchema({"type": "string", "enum": ["bozza", "inviata", "accettata", "rifiutata"]}),
]

# Same runtime-permissive / schema-only-strict split as the existing `*Changes`
# aliases: the parameter stays an unvalidated dict so a bad nested value is rejected by
# `TimeEntryUpdate(**data)`/`CostUpdate(**data)` *inside* the guarded call and becomes
# rendered guidance, while `list_tools()` still advertises the real field names.
TimeEntryChanges = Annotated[dict[str, Any], WithJsonSchema(TimeEntryUpdate.model_json_schema())]
CostChanges = Annotated[dict[str, Any], WithJsonSchema(CostUpdate.model_json_schema())]

# `HoursArg`/`MoneyArg`/`OptionalFactor` mirror `BoundedLimit`/`OptionalMoney` exactly,
# for the same SDK-bypass reason: a bare `float` parameter lets a wrong-TYPE argument be
# rejected by the SDK's own pre-call coercion, before `_guard` runs, producing the raw
# English pydantic dump spec §8.2 forbids. `HoursArg` and `MoneyArg` are both required
# (no `None` branch, no default) because `ore` on `TimeEntryCreate` and `importo` on
# `CostCreate` both are -- unlike every existing `Optional*` alias in this module, which
# all back an optional schema field. Giving a required field an `Optional*` alias would
# make `list_tools()` advertise `"default": None` for an argument the schema will
# actually refuse to construct without.
HoursArg = Annotated[
    float | str, WithJsonSchema({"type": "number", "exclusiveMinimum": 0, "maximum": 24})
]
MoneyArg = Annotated[float | str, WithJsonSchema({"type": "number"})]
OptionalFactor = Annotated[
    float | str | None,
    WithJsonSchema(
        {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}], "default": None}
    ),
]

# Two more integers on the same pattern, and for the same reason as `BoundedLimit`: a
# bare `int` lets the SDK reject a wrong-typed argument ahead of `_guard`. Neither has a
# `*ListQuery` behind it to do the validating, so the call-throughs
# (`tools/timetracking.py::_ANNO`, `tools/documents.py::_NUMERO`) each carry a
# `TypeAdapter` for the bounds advertised here -- the alias decides what `list_tools()`
# shows, never what is enforced.
OptionalAnno = Annotated[
    int | str | None,
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "integer", "minimum": ANNO_MIN, "maximum": ANNO_MAX},
                {"type": "null"},
            ],
            "default": None,
        }
    ),
]
VersionNumber = Annotated[int | str, WithJsonSchema({"type": "integer", "minimum": 1})]


def register_entity_tools(mcp: MCPServer, context: McpContext, guard: Callable[..., Any]) -> None:
    """Every tool is a thin call into a core service.

    A tool that contained business logic would be logic the web app cannot reach —
    exactly the failure this architecture exists to prevent. Custom fields travel as
    a plain dict validated by the core validator; call `describe_schema` to learn
    which keys are legal right now.
    """

    # ---- customers -------------------------------------------------------

    @mcp.tool()
    @guard
    def create_customer(
        ragione_sociale: str,
        partita_iva: str | None = None,
        codice_fiscale: str | None = None,
        codice_sdi: str | None = None,
        pec: str | None = None,
        indirizzo: str | None = None,
        cap: str | None = None,
        comune: str | None = None,
        provincia: str | None = None,
        email: str | None = None,
        telefono: str | None = None,
        note: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea un cliente. Chiama prima `describe_schema` per i campi personalizzati."""
        return customers.create(
            context,
            {
                "ragione_sociale": ragione_sociale,
                "partita_iva": partita_iva,
                "codice_fiscale": codice_fiscale,
                "codice_sdi": codice_sdi,
                "pec": pec,
                "indirizzo": indirizzo,
                "cap": cap,
                "comune": comune,
                "provincia": provincia,
                "email": email,
                "telefono": telefono,
                "note": note,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_customer(customer_id: str, changes: CustomerChanges) -> dict[str, Any]:
        """Aggiorna un cliente. `changes` contiene solo i campi da modificare."""
        return customers.update(context, customer_id, changes)

    @mcp.tool()
    @guard
    def get_customer(customer_id: str) -> dict[str, Any]:
        """Legge un cliente. Per il contesto completo usa la risorsa `customer://<id>`."""
        return customers.get(context, customer_id)

    @mcp.tool()
    @guard
    def search_customers(
        search: str | None = None,
        stato: str | None = None,
        custom: dict[str, Any] | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
        sort: str | None = None,
        # `str` and not `Literal["asc", "desc"]`, following this file's own
        # runtime-permissive/schema-strict convention: an out-of-range value then
        # raises `pydantic.ValidationError` inside `_guard`, which renders it as a
        # domain error the agent can read, instead of failing in the SDK's pre-call
        # `validate_arguments` where the message is not ours.
        dir: str = "asc",
    ) -> dict[str, Any]:
        """Cerca clienti per ragione sociale, P.IVA, codice fiscale o email.
        `custom` filtra sui campi personalizzati per uguaglianza esatta (es.
        {"settore": "IT"}); chiama `describe_schema` per conoscere le chiavi
        disponibili. `sort` accetta `created_at`, `updated_at` o `ragione_sociale`,
        `dir` accetta `asc` o `desc`. Per leggere la pagina successiva passa
        `next_cursor` come `cursor` nella chiamata seguente, senza interpretarlo.
        """
        return customers.search(
            context,
            CustomerListQuery(
                search=search,
                stato=stato,
                custom=custom,
                # cast: limit is `int | str` at runtime for the SDK-bypass reason
                # documented on BoundedLimit above; the *ListQuery schema this
                # feeds is what actually enforces (and coerces) "must be an int".
                limit=cast(int, limit),
                # Since slice 6 the cursor is an opaque string, not a UUID: it encodes
                # `(sort value, id)`. Passing it through unparsed is the whole
                # contract -- `UUID(cursor)` here would raise a bare `ValueError` on
                # every `next_cursor` this tool itself just handed the agent. The
                # tool's own signature and JSON Schema are unchanged, so nothing an
                # agent sees moves. `list_invoices` and the time-tracking tools keep
                # their `UUID(cursor)`: those pages still key on the id alone.
                cursor=cursor,
                sort=sort,
                dir=cast(SortDirection, dir),
            ),
        )

    @mcp.tool()
    @guard
    def archive_customer(customer_id: str) -> dict[str, str]:
        """Archivia un cliente (reversibile con `restore_customer`). Fallisce se ha
        deal attivi."""
        return customers.archive(context, customer_id)

    @mcp.tool()
    @guard
    def restore_customer(customer_id: str) -> dict[str, Any]:
        """Ripristina un cliente archiviato."""
        return customers.restore(context, customer_id)

    # ---- people ----------------------------------------------------------

    @mcp.tool()
    @guard
    def create_person(
        nome: str,
        cognome: str | None = None,
        email: str | None = None,
        telefono: str | None = None,
        ruolo: str | None = None,
        linkedin: str | None = None,
        note: str | None = None,
        customer_id: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea una persona. `customer_id` è facoltativo: un contatto può non avere
        ancora un cliente. Chiama prima `describe_schema` per i campi personalizzati.
        """
        return people.create(
            context,
            {
                "nome": nome,
                "cognome": cognome,
                "email": email,
                "telefono": telefono,
                "ruolo": ruolo,
                "linkedin": linkedin,
                "note": note,
                "customer_id": UUID(customer_id) if customer_id else None,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_person(person_id: str, changes: PersonChanges) -> dict[str, Any]:
        """Aggiorna una persona. Per staccarla dal cliente attuale senza assegnarne uno
        nuovo, passa `changes.detach = true` invece di un `customer_id`.
        """
        return people.update(context, person_id, changes)

    @mcp.tool()
    @guard
    def get_person(person_id: str) -> dict[str, Any]:
        """Legge una persona."""
        return people.get(context, person_id)

    @mcp.tool()
    @guard
    def search_people(
        search: str | None = None,
        customer_id: str | None = None,
        custom: dict[str, Any] | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
        sort: str | None = None,
        # `str`, not a Literal -- see `search_customers`.
        dir: str = "asc",
    ) -> dict[str, Any]:
        """Cerca persone per nome, cognome o email, opzionalmente entro un cliente.
        `custom` filtra sui campi personalizzati per uguaglianza esatta; chiama
        `describe_schema` per conoscere le chiavi disponibili. `sort` accetta
        `created_at`, `updated_at` o `cognome`, `dir` accetta `asc` o `desc`. Per
        leggere la pagina successiva passa `next_cursor` come `cursor` nella chiamata
        seguente, senza interpretarlo.
        """
        return people.search(
            context,
            PersonListQuery(
                search=search,
                customer_id=UUID(customer_id) if customer_id else None,
                custom=custom,
                # cast: limit is `int | str` at runtime for the SDK-bypass reason
                # documented on BoundedLimit above; the *ListQuery schema this
                # feeds is what actually enforces (and coerces) "must be an int".
                limit=cast(int, limit),
                # An opaque string since slice 6 -- see `search_customers`.
                cursor=cursor,
                sort=sort,
                dir=cast(SortDirection, dir),
            ),
        )

    @mcp.tool()
    @guard
    def archive_person(person_id: str) -> dict[str, str]:
        """Archivia una persona (reversibile con `restore_person`)."""
        return people.archive(context, person_id)

    @mcp.tool()
    @guard
    def restore_person(person_id: str) -> dict[str, Any]:
        """Ripristina una persona archiviata."""
        return people.restore(context, person_id)

    # ---- deals -----------------------------------------------------------

    @mcp.tool()
    @guard
    def create_deal(
        nome: str,
        customer_id: str,
        valore_previsto: OptionalMoney = None,
        probabilita: OptionalProbabilita = None,
        data_chiusura_prevista: IsoDateStr = None,
        note: str | None = None,
        ore_preventivate: OptionalMoney = None,
        valore_preventivato: OptionalMoney = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea un deal. Il cliente è obbligatorio; lo stato iniziale è il primo della
        pipeline. `data_chiusura_prevista` va in formato YYYY-MM-DD. Chiama prima
        `describe_schema` per i campi personalizzati.
        """
        return deals.create(
            context,
            {
                "nome": nome,
                "customer_id": UUID(customer_id),
                "valore_previsto": valore_previsto,
                "probabilita": probabilita,
                "data_chiusura_prevista": data_chiusura_prevista,
                "note": note,
                "ore_preventivate": ore_preventivate,
                "valore_preventivato": valore_preventivato,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_deal(deal_id: str, changes: DealChanges) -> dict[str, Any]:
        """Aggiorna un deal. Per cambiare stato usa `move_deal`."""
        return deals.update(context, deal_id, changes)

    @mcp.tool()
    @guard
    def get_deal(deal_id: str) -> dict[str, Any]:
        """Legge un deal."""
        return deals.get(context, deal_id)

    @mcp.tool()
    @guard
    def search_deals(
        search: str | None = None,
        customer_id: str | None = None,
        stage_id: str | None = None,
        custom: dict[str, Any] | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
        sort: str | None = None,
        # `str`, not a Literal -- see `search_customers`.
        dir: str = "asc",
    ) -> dict[str, Any]:
        """Cerca deal per nome, cliente o stato di pipeline. `custom` filtra sui
        campi personalizzati per uguaglianza esatta; chiama `describe_schema` per
        conoscere le chiavi disponibili. `sort` accetta `created_at`, `updated_at` o
        `nome`, `dir` accetta `asc` o `desc`. Per leggere la pagina successiva passa
        `next_cursor` come `cursor` nella chiamata seguente, senza interpretarlo.
        """
        return deals.search(
            context,
            DealListQuery(
                search=search,
                customer_id=UUID(customer_id) if customer_id else None,
                stage_id=UUID(stage_id) if stage_id else None,
                custom=custom,
                # cast: limit is `int | str` at runtime for the SDK-bypass reason
                # documented on BoundedLimit above; the *ListQuery schema this
                # feeds is what actually enforces (and coerces) "must be an int".
                limit=cast(int, limit),
                # An opaque string since slice 6 -- see `search_customers`.
                cursor=cursor,
                sort=sort,
                dir=cast(SortDirection, dir),
            ),
        )

    @mcp.tool()
    @guard
    def move_deal(deal_id: str, stage_id: str) -> dict[str, Any]:
        """Sposta un deal in un altro stato. Uno stato vinto/perso fissa la probabilità
        a 100/0."""
        return deals.move(context, deal_id, stage_id)

    @mcp.tool()
    @guard
    def archive_deal(deal_id: str) -> dict[str, str]:
        """Archivia un deal (reversibile con `restore_deal`)."""
        return deals.archive(context, deal_id)

    @mcp.tool()
    @guard
    def restore_deal(deal_id: str) -> dict[str, Any]:
        """Ripristina un deal archiviato."""
        return deals.restore(context, deal_id)

    # ---- shared ------------------------------------------------------------

    @mcp.tool()
    @guard
    def list_pipeline_stages() -> dict[str, Any]:
        """Elenca gli stati della pipeline, con il tipo (open/won/lost) di ciascuno."""
        stages = PipelineService(context.session).list()
        return {"stages": [stage.model_dump(mode="json") for stage in stages]}

    @mcp.tool()
    @guard
    def get_timeline(
        entity_type: EntityType, entity_id: str, limit: BoundedLimit = 50
    ) -> dict[str, Any]:
        """Cronologia di un'entità. `actor_type` distingue le azioni umane da quelle di
        un agente."""
        entries = ActivityService(context.session).timeline(
            entity_type, UUID(entity_id), limit=cast(int, limit)
        )
        return {"entries": [entry.model_dump(mode="json") for entry in entries]}

    @mcp.tool()
    @guard
    def search_everything(termine: str, limite: SearchLimite = PER_CLASS_LIMIT) -> dict[str, Any]:
        """Cerca in tutto il CRM — clienti, persone, deal e documenti — con una sola
        chiamata: ragione sociale, P.IVA, codice fiscale, email, nome e cognome, nome del
        deal, titolo del documento. Accetta anche un frammento in mezzo a una parola (per
        esempio «34567» trova la P.IVA 01234567890). Servono almeno 3 caratteri.
        Restituisce fino a `limite` risultati per classe di entità più il conteggio reale
        di quella classe: se `totale_e_un_minimo` è true il conteggio è un minimo e i
        risultati completi stanno sull'elenco della singola entità.
        """
        # `termine` is a bare `str` with no `Annotated` bound, following this file's own
        # runtime-permissive / schema-only-strict convention: the length check happens
        # inside `SearchQuery`, inside the guarded call, so a two-character term produces a
        # domain error the agent can act on instead of an SDK rejection whose wording is
        # not ours.
        return search_tools.search_everything(
            context, SearchQuery(termine=termine, limite=cast(int, limite))
        )

    # ---- automations -------------------------------------------------------
    # One tool, and its counterpart is deliberately absent: `update_automation_config`
    # changes what the system will do to *future* data with nobody in the loop, and
    # `MCP_EXCLUDED_SLICE6` in `packages/core/tests/test_architecture.py` declares it as
    # the slice's one exclusion. Registered here, in `tools/automations.py`, rather than
    # alongside the dashboard: the two answer different questions and share no service.
    #
    # Registered by Task B3 rather than by Task B12, which owns 6B's surface: the moment
    # `AutomationConfigService` exists, both coverage tests demand that each of its public
    # methods be a tool or a named exclusion, and deferring one to a later task is exactly
    # the placeholder Task A11 cleared out of the taxonomy. Task B12 must not register a
    # second `describe_automations`.

    @mcp.tool()
    @guard
    def describe_automations() -> dict[str, Any]:
        """Che cosa fa il CRM da solo: le regole di automazione, se sono attive, e le
        ultime esecuzioni con il loro esito (compresi i casi in cui una regola ha deciso
        di non agire, con il motivo). Leggila prima di concludere che un deal è stato
        spostato a mano. La configurazione si cambia solo dall'interfaccia web.
        """
        return automation_tools.describe_automations(context)

    # ---- dashboard ---------------------------------------------------------
    # Registered by Task B8, which created `DashboardService`, and for the same reason
    # Task B3 registered `describe_automations` above: the moment the service exists both
    # coverage tests demand that each of its public methods be a tool or a named exclusion,
    # and "a later task decides" is the placeholder Task A11 spent a whole task deleting.
    # Task B12 owns the rest of 6B's surface -- the REST routers and this tool's own MCP
    # test -- and must not register a second `get_commercial_dashboard`.
    #
    # No resource counterpart, deliberately (§11.1): a resource is addressed by a URI and a
    # dashboard is a question with a period.

    @mcp.tool()
    @guard
    def get_commercial_dashboard(da: IsoDateStr = None, a: IsoDateStr = None) -> dict[str, Any]:
        """Il quadro commerciale in una sola chiamata: pipeline per stato, deal chiusi nel
        periodo con il tasso di conversione, offerte inviate ancora in attesa con da quanti
        giorni, chiusure previste nei 30 giorni successivi al periodo e le offerte accettate
        il cui deal non risulta vinto. Ogni cifra è letta nello stesso istante, indicato da
        `calcolato_alle`. `da` e `a` sono date `YYYY-MM-DD` e vanno insieme: senza, il
        periodo è il mese corrente. `valore_ponderato` è una stima e non è fatturato.
        """
        # `IsoDateStr`, the alias this file already uses for a date parameter: the runtime
        # type stays `str | None` so a malformed date is rejected inside `PeriodoQuery`,
        # inside the guarded call, and the agent gets this project's own rendered guidance
        # instead of an SDK rejection whose wording is not ours -- while `list_tools()`
        # still advertises `format: date`. `model_validate` on a dict rather than
        # `PeriodoQuery(da=da, a=a)`: the two do the same coercion, and the keyword form
        # would be a type error to a reader (and to mypy) that says nothing true about the
        # runtime.
        return dashboard_tools.get_commercial_dashboard(
            context, PeriodoQuery.model_validate({"da": da, "a": a})
        )

    # Registered by Task C4, which created `get_economic_dashboard`, for the reason given
    # beside the tool above: a service method with no tool and no named exclusion turns
    # both coverage tests red the moment it exists, and deferring one to a later task is
    # the placeholder Task A11 spent a whole task deleting. Task C7 owns the rest of 6C's
    # surface -- the REST routes and this tool's own MCP test -- and must not register a
    # second `get_economic_dashboard`.

    @mcp.tool()
    @guard
    def get_economic_dashboard(da: IsoDateStr = None, a: IsoDateStr = None) -> dict[str, Any]:
        """Il conto economico del periodo in una sola chiamata: ricavi, costi diretti, costo
        del lavoro e margine, in due colonne separate -- `chiusi` e `in_corso` -- che non
        vanno sommate fra loro, più le spese generali, il valore maturato non ancora
        fatturato, il totale da incassare e la quota già scaduta. `da_incassare` e `scaduto`
        non hanno periodo: una fattura di febbraio non pagata è dovuta anche guardando
        marzo. Ogni cifra è letta nello stesso istante, indicato da `calcolato_alle`. `da` e
        `a` sono date `YYYY-MM-DD` e vanno insieme: senza, il periodo è il mese corrente.
        Non contiene nessuna stima fiscale.
        """
        return dashboard_tools.get_economic_dashboard(
            context, PeriodoQuery.model_validate({"da": da, "a": a})
        )

    # ---- documents ---------------------------------------------------------
    # The download of bytes never goes through MCP (spec 7): a tool returning a
    # base64 PDF inside a model's own context is waste and risk. Every tool below
    # returns an identifier -- the bytes are fetched separately, over the REST API,
    # by whatever already holds the download URL.
    #
    # `preview_template` is the one that returns text, and it is not an exception to
    # that rule: it renders the Markdown from values the caller just supplied and
    # stores nothing, so there is no artefact being pulled out of the storage layer
    # that versions and audits it. `DocumentService.download` remains unexposed;
    # so does `add_version`, which would need bytes MCP does not produce.

    @mcp.tool()
    @guard
    def list_documents(
        customer_id: str | None = None,
        deal_id: str | None = None,
        tipo: str | None = None,
        stato: str | None = None,
        search: str | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
        sort: str | None = None,
        # `str`, not a Literal -- see `search_customers`.
        dir: str = "asc",
    ) -> dict[str, Any]:
        """Elenca i documenti di un cliente o di un deal. `search` filtra per titolo.
        `sort` accetta `created_at`, `updated_at` o `titolo`, `dir` accetta `asc` o
        `desc`. Passa `next_cursor` come `cursor` per la pagina successiva, senza
        interpretarlo. Per scaricare i byte usa l'API REST: MCP restituisce
        identificativi, non file."""
        return documents.search(
            context,
            DocumentListQuery(
                customer_id=UUID(customer_id) if customer_id else None,
                deal_id=UUID(deal_id) if deal_id else None,
                tipo=tipo,  # type: ignore[arg-type]
                stato=stato,  # type: ignore[arg-type]
                search=search,
                limit=cast(int, limit),
                # An opaque string since slice 6 -- see `search_customers`.
                cursor=cursor,
                sort=sort,
                dir=cast(SortDirection, dir),
            ),
        )

    @mcp.tool()
    @guard
    def get_document(document_id: str) -> dict[str, Any]:
        """Legge un documento: tipo, titolo, stato e versione corrente."""
        return documents.get(context, document_id)

    @mcp.tool()
    @guard
    def get_document_versions(document_id: str) -> dict[str, Any]:
        """Storico delle versioni di un documento, dalla piu' recente. Ogni versione
        conserva il template e le variabili con cui e' stata generata, quindi si puo'
        rigenerare identica."""
        return documents.versions(context, document_id)

    @mcp.tool()
    @guard
    def list_templates(include_archived: bool = False) -> dict[str, Any]:
        """Elenca i template disponibili."""
        return documents.list_templates(context, include_archived)

    @mcp.tool()
    @guard
    def describe_template(template_id: str) -> dict[str, Any]:
        """Che variabili vuole un template, con etichetta, tipo e obbligatorieta'.
        Chiamalo **prima** di chiedere qualcosa all'utente: e' come si scopre cosa
        serve senza indovinarlo."""
        return documents.describe_template(context, template_id)

    @mcp.tool()
    @guard
    def preview_template(
        template_id: str, variabili: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Rende un template con le variabili indicate e restituisce il Markdown, senza
        creare nessun documento e senza produrre nessun file. Serve a verificare un
        testo prima di `create_document_from_template`: se una variabile obbligatoria
        manca lo dice qui, dove non resta niente da annullare."""
        return documents.preview_template(context, template_id, variabili or {})

    @mcp.tool()
    @guard
    def create_document_from_template(
        template_id: str,
        titolo: str,
        customer_id: str | None = None,
        deal_id: str | None = None,
        variabili: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea un documento da un template e ne genera il PDF. Indica `customer_id`
        oppure `deal_id`, mai entrambi. Chiama prima `describe_template` per sapere
        quali variabili servono. Restituisce l'identificativo del documento, non il
        file: i byte si scaricano dall'API REST."""
        return documents.create_from_template(
            context,
            {
                "template_id": UUID(template_id),
                "titolo": titolo,
                "customer_id": UUID(customer_id) if customer_id else None,
                "deal_id": UUID(deal_id) if deal_id else None,
                "variabili": variabili or {},
            },
        )

    @mcp.tool()
    @guard
    def set_offer_state(document_id: str, stato: OfferStateArg) -> dict[str, Any]:
        """Cambia lo stato di un'offerta. Transizioni ammesse: bozza -> inviata;
        inviata -> accettata | rifiutata | bozza. Accettata e rifiutata sono finali."""
        return documents.set_state(context, document_id, stato)

    @mcp.tool()
    @guard
    def regenerate_document_version(document_id: str, numero: VersionNumber) -> dict[str, Any]:
        """Rigenera una versione gia' prodotta come nuova versione, dal template e dalle
        variabili congelate su quella di partenza: non decide niente di nuovo, e la
        versione originale resta nello storico. `cliente`, `emittente` e la data vengono
        riletti al momento del rendering, quindi il PDF coincide con l'originale finche'
        quei dati non cambiano. Non si rigenera una versione caricata a mano: senza
        template non c'e' niente da riprodurre. Restituisce l'identificativo della nuova
        versione, non i byte."""
        return documents.regenerate_version(context, document_id, numero)

    @mcp.tool()
    @guard
    def archive_document(document_id: str) -> dict[str, str]:
        """Archivia un documento (reversibile con `restore_document`). I file restano
        dove sono: un ripristino che tornasse senza il PDF non sarebbe un ripristino."""
        return documents.archive(context, document_id)

    @mcp.tool()
    @guard
    def restore_document(document_id: str) -> dict[str, Any]:
        """Ripristina un documento archiviato."""
        return documents.restore(context, document_id)

    # -- Invoices -------------------------------------------------------------
    #
    # Reads, and the proforma. `issue`, `annul`, `mark_transmitted_externally`,
    # `export_xml` and the write behind the fiscal profile
    # (`FiscalProfileService.upsert`) are deliberately absent, and the absence is the
    # mechanism: a personal access token inherits its owner's full role and never
    # expires, so a permission check inside a registered tool would be a check an
    # admin's token passes. A tool that does not exist cannot be called by anyone.
    #
    # Reading the profile is exposed and writing it is not, which is the whole line
    # this surface draws: `describe_fiscal_profile` tells an agent which VAT rate,
    # natura and bollo its proforma will inherit, and deciding what those are is the
    # part a person does. The write is banned as a `(service, method)` pair rather
    # than by name, since `EmitterProfileService.upsert` is a different operation
    # spelled identically.
    #
    # `test_mcp_invoice_ban.py` reads this module's AST and fails if any of those five
    # names appears as a registered tool, so the guarantee survives someone adding one
    # later without reading this comment.

    @mcp.tool()
    @guard
    def list_invoices(
        customer_id: str | None = None,
        deal_id: str | None = None,
        tipo: str | None = None,
        stato: str | None = None,
        anno: int | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Elenca fatture e proforma. Passa `next_cursor` come `cursor` per la pagina
        successiva. Per scaricare il PDF o l'XML usa l'API REST: MCP restituisce
        identificativi, non file."""
        return invoices.search(
            context,
            InvoiceListQuery(
                customer_id=UUID(customer_id) if customer_id else None,
                deal_id=UUID(deal_id) if deal_id else None,
                tipo=tipo,  # type: ignore[arg-type]
                stato=stato,  # type: ignore[arg-type]
                anno=anno,
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def get_invoice(invoice_id: str) -> dict[str, Any]:
        """Legge una fattura o una proforma: numero, stato, totali e righe."""
        return invoices.get(context, invoice_id)

    @mcp.tool()
    @guard
    def create_proforma(
        customer_id: str,
        righe: list[dict[str, Any]],
        deal_id: str | None = None,
        causale: str | None = None,
    ) -> dict[str, Any]:
        """Crea una proforma. Una proforma non e' un documento fiscale: non prende un
        numero, non produce un file per il Sistema di Interscambio, e diventa una
        fattura solo quando una persona la emette dall'applicazione."""
        return invoices.create_proforma(
            context,
            {
                "customer_id": UUID(customer_id),
                "deal_id": UUID(deal_id) if deal_id else None,
                "causale": causale,
                "righe": righe,
            },
        )

    @mcp.tool()
    @guard
    def replace_proforma_lines(invoice_id: str, righe: list[dict[str, Any]]) -> dict[str, Any]:
        """Sostituisce **tutte** le righe di una proforma e ricalcola i totali. Rifiuta
        una fattura emessa: le sue righe sono immutabili."""
        return invoices.replace_proforma_lines(context, invoice_id, righe)

    @mcp.tool()
    @guard
    def render_proforma_pdf(invoice_id: str) -> dict[str, Any]:
        """Genera il PDF di una proforma e restituisce l'identificativo del documento.
        I byte si scaricano dall'API REST."""
        return invoices.render_proforma_pdf(context, invoice_id)

    @mcp.tool()
    @guard
    def get_invoice_xml_url(invoice_id: str) -> dict[str, Any]:
        """Il percorso REST da cui scaricare il file FatturaPA di una fattura emessa.
        Non restituisce i byte: un XML fiscale dentro il contesto di un modello e'
        spreco e rischio insieme."""
        return invoices.xml_url(context, invoice_id)

    @mcp.tool()
    @guard
    def set_invoice_payment_state(
        invoice_id: str, stato_pagamento: str, data_incasso: str | None = None
    ) -> dict[str, Any]:
        """Registra un incasso o lo annulla. Non cambia lo stato fiscale della
        fattura, che resta emessa."""
        return invoices.set_payment_state(context, invoice_id, stato_pagamento, data_incasso)

    @mcp.tool()
    @guard
    def describe_fiscal_profile() -> dict[str, Any]:
        """Il regime fiscale configurato e i parametri che decidono aliquote, natura
        e bollo. Utile per capire perche' una riga ha una certa IVA."""
        return invoices.describe_fiscal_profile(context)

    @mcp.tool()
    @guard
    def describe_emitter_profile() -> dict[str, Any]:
        """Chi emette: ragione sociale, partita IVA, indirizzo e recapiti che finiscono
        nell'intestazione di ogni fattura e di ogni documento. Da leggere prima di
        scrivere un testo che li ripete, invece di chiederli all'utente."""
        return invoices.describe_emitter_profile(context)

    # ---- time tracking -----------------------------------------------------
    # An agent may record and read. It may not change what already-recorded numbers
    # mean. Eleven methods are therefore deliberately absent from this module and from
    # `tools/timetracking.py` -- `recalculate_rates`, `update_user_rates`,
    # `update_deal_rate`, the four cost-category writes (`unarchive_cost_category`
    # included: slice 4 §11 listed only the other three, but bringing a category back
    # is the same decision as archiving it, taken in the other direction),
    # `bind_time_to_invoice`, `close_period`, `reopen_period`, `get_fiscal_estimate` --
    # and
    # `apps/mcp/tests/test_mcp_invoice_ban.py` fails the build if a tool for any of
    # them appears anywhere under `tools/`, or if that list changes. The defence is
    # structural rather than permission-based because residual R10 is open: a PAT has
    # no scopes and inherits its owner's full role, so an admin token would pass any
    # authorisation check. Not registering the tool is the only mechanism that holds.

    @mcp.tool()
    @guard
    def log_time(
        deal_id: str,
        user_id: str,
        data: str,
        ore: HoursArg,
        descrizione: str,
        fatturabile: bool = True,
        tariffa_applicata: OptionalFactor = None,
        costo_applicato: OptionalFactor = None,
        note_interne: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra ore su un deal. `data` in formato YYYY-MM-DD, non futura.

        `deal_id` è obbligatorio e deve essere un id reale: usa prima `search_deals`
        per risolvere il nome del progetto. Questo strumento non crea nulla che non
        trovi -- attribuire ore fatturabili al cliente sbagliato è un errore che
        emerge solo su una fattura.

        La tariffa viene congelata sulla riga al momento della scrittura: chiama
        `describe_rates` per sapere quale si applicherebbe. Se non ne risulta nessuna
        la voce viene registrata comunque, senza tariffa, e comparirà fra le "ore
        senza tariffa".
        """
        return timetracking.log_time(
            context,
            {
                "deal_id": UUID(deal_id),
                "user_id": UUID(user_id),
                "data": data,
                "ore": ore,
                "descrizione": descrizione,
                "fatturabile": fatturabile,
                "tariffa_applicata": tariffa_applicata,
                "costo_applicato": costo_applicato,
                "note_interne": note_interne,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_time_entry(entry_id: str, changes: TimeEntryChanges) -> dict[str, Any]:
        """Aggiorna una voce di ore. Una voce già su una fattura emessa ha ore, data,
        tariffa e descrizione congelate: solo `note_interne` e i campi personalizzati
        restano modificabili."""
        return timetracking.update_time_entry(context, entry_id, changes)

    @mcp.tool()
    @guard
    def archive_time_entry(entry_id: str) -> dict[str, str]:
        """Archivia una voce di ore (reversibile con `restore_time_entry`). Fallisce se
        la voce è legata a una riga di fattura."""
        return timetracking.archive_time_entry(context, entry_id)

    @mcp.tool()
    @guard
    def restore_time_entry(entry_id: str) -> dict[str, Any]:
        """Ripristina una voce di ore archiviata."""
        return timetracking.restore_time_entry(context, entry_id)

    @mcp.tool()
    @guard
    def get_time_entry(entry_id: str) -> dict[str, Any]:
        """Legge una voce di ore, con il valore di riga già calcolato."""
        return timetracking.get_time_entry(context, entry_id)

    @mcp.tool()
    @guard
    def list_time_entries(
        deal_id: str | None = None,
        user_id: str | None = None,
        da: IsoDateStr = None,
        a: IsoDateStr = None,
        fatturabile: bool | None = None,
        fatturato: bool | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Elenca le voci di ore, dalla più recente. `fatturato = false` risponde alla
        domanda "quanto ho da fatturare"."""
        return timetracking.list_time_entries(
            context,
            TimeEntryListQuery(
                deal_id=UUID(deal_id) if deal_id else None,
                user_id=UUID(user_id) if user_id else None,
                da=da,  # type: ignore[arg-type]
                a=a,  # type: ignore[arg-type]
                fatturabile=fatturabile,
                fatturato=fatturato,
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def get_deal_time_summary(deal_id: str) -> dict[str, Any]:
        """Ore totali, ore da fatturare, valore delle ore non fatturate, costo del
        lavoro e stato del deal. Il ricavo non è qui: il ricavo è la fattura."""
        return timetracking.get_deal_time_summary(context, deal_id)

    @mcp.tool()
    @guard
    def describe_rates(deal_id: str, user_id: str) -> dict[str, Any]:
        """Quale tariffa e quale costo verrebbero congelati su una nuova voce, e da
        quale livello arrivano (`manuale`, `deal`, `utente`, `assente`). Chiamalo prima
        di `log_time`."""
        return timetracking.describe_rates(context, deal_id, user_id)

    @mcp.tool()
    @guard
    def create_cost(
        category_id: str,
        data: str,
        importo: MoneyArg,
        descrizione: str,
        deal_id: str | None = None,
        fornitore: str | None = None,
        document_id: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra un costo. `deal_id` assente significa spesa generale, che entra nel
        conto economico di periodo e non viene ripartita su nessun deal. `importo` è il
        totale pagato, IVA inclusa; un valore negativo è un rimborso; zero è rifiutato.
        Chiama `list_cost_categories` per le categorie disponibili."""
        return timetracking.create_cost(
            context,
            {
                "category_id": UUID(category_id),
                "data": data,
                "importo": importo,
                "descrizione": descrizione,
                "deal_id": UUID(deal_id) if deal_id else None,
                "fornitore": fornitore,
                "document_id": UUID(document_id) if document_id else None,
                "custom_fields": custom_fields or {},
            },
        )

    @mcp.tool()
    @guard
    def update_cost(cost_id: str, changes: CostChanges) -> dict[str, Any]:
        """Aggiorna un costo."""
        return timetracking.update_cost(context, cost_id, changes)

    @mcp.tool()
    @guard
    def archive_cost(cost_id: str) -> dict[str, str]:
        """Archivia un costo (reversibile)."""
        return timetracking.archive_cost(context, cost_id)

    @mcp.tool()
    @guard
    def restore_cost(cost_id: str) -> dict[str, Any]:
        """Ripristina un costo archiviato."""
        return timetracking.restore_cost(context, cost_id)

    @mcp.tool()
    @guard
    def get_cost(cost_id: str) -> dict[str, Any]:
        """Legge un costo."""
        return timetracking.get_cost(context, cost_id)

    @mcp.tool()
    @guard
    def list_costs(
        deal_id: str | None = None,
        solo_generali: bool = False,
        category_id: str | None = None,
        da: IsoDateStr = None,
        a: IsoDateStr = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Elenca i costi, dal più recente. `solo_generali = true` mostra solo le spese
        senza deal."""
        return timetracking.list_costs(
            context,
            CostListQuery(
                deal_id=UUID(deal_id) if deal_id else None,
                solo_generali=solo_generali,
                category_id=UUID(category_id) if category_id else None,
                da=da,  # type: ignore[arg-type]
                a=a,  # type: ignore[arg-type]
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def list_cost_categories(include_archived: bool = False) -> dict[str, Any]:
        """Elenca le categorie di costo configurate. Crearle, archiviarle e
        ripristinarle è configurazione e si fa dall'app, non da qui."""
        return timetracking.list_cost_categories(context, include_archived)

    @mcp.tool()
    @guard
    def list_period_locks(anno: OptionalAnno = None) -> dict[str, Any]:
        """Elenca i mesi chiusi, dal più recente. Un mese chiuso rifiuta ogni scrittura
        di ore e costi datata in quel mese: leggi qui prima di registrare voci vecchie,
        invece di scoprirlo un rifiuto alla volta. Chiudere e riaprire un periodo si fa
        dall'app, non da qui."""
        return timetracking.list_period_locks(context, anno)

    # ---- analytics ---------------------------------------------------------
    # Reads only. `bind_time_to_invoice` has no tool because binding hours to a draft
    # is the step that determines their freezing at issue, and choosing *which* hours
    # to invoice is a commercial decision -- slice 3 §11 withdrew `issue_invoice` with
    # the same reasoning and this is the rung below it. `get_fiscal_estimate` has no
    # tool for a different reason: taxable income, contributions and estimated net for
    # a real person are the most sensitive data this product holds, and residual R10
    # leaves a PAT indistinguishable from full account access.

    @mcp.tool()
    @guard
    def get_deal_pnl(deal_id: str) -> dict[str, Any]:
        """Conto economico di un deal: ricavi fatturati, costi diretti, costo del lavoro,
        margine e stato. `margine_percentuale` è `null` quando i ricavi sono zero — non
        zero per cento: significa che non è ancora stato incassato niente, non che tutto
        se n'è andato in costi. `valore_maturato` non è un ricavo: è una stima."""
        return timetracking.get_deal_pnl(context, deal_id)

    @mcp.tool()
    @guard
    def get_period_pnl(da: str, a: str, customer_id: str | None = None) -> dict[str, Any]:
        """Conto economico di periodo, in due colonne: deal chiusi e deal in corso. Il
        numero riportabile è il primo. `periodo_chiuso` e `voci_scritte_in_ritardo` dicono
        se la cifra può ancora muoversi. Le spese generali stanno in una riga a parte e non
        vengono ripartite su nessun deal."""
        return timetracking.get_period_pnl(
            context,
            PeriodPnlQuery(
                da=da,  # type: ignore[arg-type]
                a=a,  # type: ignore[arg-type]
                customer_id=UUID(customer_id) if customer_id else None,
            ),
        )

    @mcp.tool()
    @guard
    def get_unbilled_backlog() -> dict[str, Any]:
        """Le ore fatturabili non ancora finite su una fattura emessa, in **totale** e
        senza periodo: quante ore, il valore maturato corrispondente (somma di ore ×
        tariffa, arrotondata per riga), e quante voci non hanno una tariffa. Le voci senza
        tariffa sono contate nelle ore ma valgono zero nel valore maturato: tariffa assente
        e tariffa zero sono cose diverse. Le ore già legate a una **bozza** di fattura
        contano ancora: una bozza non è un ricavo. Il valore maturato **non è un ricavo** e
        non entra in nessun margine: il ricavo è la fattura.
        """
        return timetracking.get_unbilled_backlog(context)

    @mcp.tool()
    @guard
    def get_budget_vs_actual(
        da: str,
        a: str,
        customer_id: str | None = None,
        limit: BoundedLimit = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Preventivo contro consuntivo per deal. Lo scostamento di valore è calcolato
        contro il preventivo **pro-rata** (preventivo × avanzamento ore), non contro quello
        pieno. Una riga con `non_preventivato = true` non ha alcun preventivo: non è un
        preventivo di zero, ed è esclusa dagli aggregati."""
        return timetracking.get_budget_vs_actual(
            context,
            BudgetQuery(
                da=da,  # type: ignore[arg-type]
                a=a,  # type: ignore[arg-type]
                customer_id=UUID(customer_id) if customer_id else None,
                limit=cast(int, limit),
                cursor=UUID(cursor) if cursor else None,
            ),
        )
