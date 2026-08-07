from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server import MCPServer

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.customers.schemas import CustomerListQuery
from pigrocrm.core.deals.schemas import DealListQuery
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.people.schemas import PersonListQuery
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm_mcp.context import McpContext
from pigrocrm_mcp.tools import customers, deals, people


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
    def update_customer(customer_id: str, changes: dict[str, Any]) -> dict[str, Any]:
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
        search: str | None = None, stato: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Cerca clienti per ragione sociale, P.IVA, codice fiscale o email."""
        return customers.search(context, CustomerListQuery(search=search, stato=stato, limit=limit))

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
    def update_person(person_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Aggiorna una persona. Per staccarla dal cliente passa `{"detach": true}`."""
        return people.update(context, person_id, changes)

    @mcp.tool()
    @guard
    def get_person(person_id: str) -> dict[str, Any]:
        """Legge una persona."""
        return people.get(context, person_id)

    @mcp.tool()
    @guard
    def search_people(
        search: str | None = None, customer_id: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Cerca persone per nome, cognome o email, opzionalmente entro un cliente."""
        return people.search(
            context,
            PersonListQuery(
                search=search,
                customer_id=UUID(customer_id) if customer_id else None,
                limit=limit,
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
        valore_previsto: float | None = None,
        probabilita: int | None = None,
        data_chiusura_prevista: str | None = None,
        note: str | None = None,
        ore_preventivate: float | None = None,
        valore_preventivato: float | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crea un deal. Il cliente è obbligatorio; lo stato iniziale è il primo della
        pipeline. Chiama prima `describe_schema` per i campi personalizzati.
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
    def update_deal(deal_id: str, changes: dict[str, Any]) -> dict[str, Any]:
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
        limit: int = 50,
    ) -> dict[str, Any]:
        """Cerca deal per nome, cliente o stato di pipeline."""
        return deals.search(
            context,
            DealListQuery(
                search=search,
                customer_id=UUID(customer_id) if customer_id else None,
                stage_id=UUID(stage_id) if stage_id else None,
                limit=limit,
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
    def get_timeline(entity_type: EntityType, entity_id: str, limit: int = 50) -> dict[str, Any]:
        """Cronologia di un'entità. `actor_type` distingue le azioni umane da quelle di
        un agente."""
        entries = ActivityService(context.session).timeline(
            entity_type, UUID(entity_id), limit=limit
        )
        return {"entries": [entry.model_dump(mode="json") for entry in entries]}
