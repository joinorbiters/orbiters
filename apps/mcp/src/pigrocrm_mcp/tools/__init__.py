from collections.abc import Callable
from typing import Annotated, Any, cast
from uuid import UUID

from mcp.server import MCPServer
from pydantic import WithJsonSchema

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.customers.schemas import CustomerListQuery, CustomerUpdate
from pigrocrm.core.deals.schemas import DealListQuery, DealUpdate
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.people.schemas import PersonListQuery, PersonUpdate
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm_mcp.context import McpContext
from pigrocrm_mcp.tools import customers, deals, people

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
    ) -> dict[str, Any]:
        """Cerca clienti per ragione sociale, P.IVA, codice fiscale o email.
        `custom` filtra sui campi personalizzati per uguaglianza esatta (es.
        {"settore": "IT"}); chiama `describe_schema` per conoscere le chiavi
        disponibili. Per leggere la pagina successiva passa `next_cursor` come
        `cursor` nella chiamata seguente.
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
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def archive_customer(customer_id: str) -> dict[str, str]:
        """Archivia un cliente (reversibile). Fallisce se ha deal attivi."""
        return customers.archive(context, customer_id)

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
    ) -> dict[str, Any]:
        """Cerca persone per nome, cognome o email, opzionalmente entro un cliente.
        `custom` filtra sui campi personalizzati per uguaglianza esatta; chiama
        `describe_schema` per conoscere le chiavi disponibili. Per leggere la
        pagina successiva passa `next_cursor` come `cursor` nella chiamata
        seguente.
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
                cursor=UUID(cursor) if cursor else None,
            ),
        )

    @mcp.tool()
    @guard
    def archive_person(person_id: str) -> dict[str, str]:
        """Archivia una persona (reversibile)."""
        return people.archive(context, person_id)

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
    ) -> dict[str, Any]:
        """Cerca deal per nome, cliente o stato di pipeline. `custom` filtra sui
        campi personalizzati per uguaglianza esatta; chiama `describe_schema` per
        conoscere le chiavi disponibili. Per leggere la pagina successiva passa
        `next_cursor` come `cursor` nella chiamata seguente.
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
                cursor=UUID(cursor) if cursor else None,
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
        """Archivia un deal (reversibile)."""
        return deals.archive(context, deal_id)

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
