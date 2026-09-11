"""`build_server`: the tools, over a session factory a test can replace.

An admin's own tool by construction. The process is started by an MCP client on a
machine that already holds the hub's database URL, and everything it can do is what
the hub's admin API will do behind its login (hub spec, step 3). There is no actor and
no permission check here because there is exactly one kind of caller; when a personal
token arrives for the hub, this is where it is resolved.

One session per tool call, closed whatever happened: the SDK dispatches sync tools on
a thread pool, and a session shared across calls is the defect PigroCRM's MCP server
measured as zero rows written under concurrency.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from orbiters_core.comments import CommentService
from orbiters_core.companies import CompanyService
from orbiters_core.errors import DomainError
from orbiters_core.freelancers import FreelancerService
from orbiters_core.logins import LoginService
from orbiters_core.perks import PerkService
from orbiters_core.schemas import FreelancerDraft, StatusChange
from orbiters_core.service import LIST_LIMIT_DEFAULT, SignupService

SessionFactory = sessionmaker[Session]

INSTRUCTIONS = (
    "Orbiters, la community di freelance di joinorbiters.com. Gli strumenti leggono chi "
    "ha chiesto di entrare (iscrizioni), i freelance che hanno compilato il profilo con il "
    "CV e le aziende che cercano persone; possono cambiare lo stato di una candidatura, "
    "annotarla e lasciare un commento datato nel suo thread; da un'iscrizione possono "
    "creare la scheda freelance con quanto si trova in pubblico su quella persona, che poi "
    "lei completa dalla sua area. Sono dati di altre persone: da usare solo per decidere "
    "quando e cosa scrivere loro, mai da riportare altrove."
)

# Who signs a comment when the caller does not say: the MCP client has no login, so the
# thread records the channel rather than pretending to know the person behind it.
DEFAULT_AUTHOR = "MCP"


def build_server(factory: SessionFactory) -> MCPServer:
    mcp = MCPServer("Orbiters", instructions=INSTRUCTIONS)

    @mcp.tool()
    def list_signups(limit: int = LIST_LIMIT_DEFAULT) -> dict[str, Any]:
        """Chi ha lasciato nome, cognome ed email su joinorbiters.com per entrare nella
        community Orbiters, dal più recente, con il profilo LinkedIn quando l'ha dato.
        Solo lettura. `nome` e `cognome` sono vuoti solo per le iscrizioni raccolte
        quando il form chiedeva la sola email. `totale` conta tutta la lista anche
        quando `limit` ne restituisce una parte."""
        return _run(lambda s: SignupService(s).list_recent(limit=limit))

    @mcp.tool()
    def create_freelancer_from_signup(
        signup_id: str,
        nome: str,
        cognome: str,
        fonti: list[str],
        linkedin_url: str | None = None,
        posizione: str | None = None,
        tariffa_giornaliera: str | None = None,
        remoto: str | None = None,
        links: list[str] | None = None,
        autore: str | None = None,
    ) -> dict[str, Any]:
        """Crea (o riscrive) la scheda freelance di un'iscrizione con quanto si trova in
        pubblico su quella persona: nome e cognome obbligatori, poi il profilo LinkedIn,
        la posizione come la dichiara lei, altri link (sito, GitHub, portfolio). Tariffa e
        modalità di lavoro solo se una fonte pubblica le dice, altrimenti restano vuote
        con il CV: la persona le completa dalla sua area. `fonti` sono gli indirizzi https
        da cui vengono le informazioni, da una a dieci, e finiscono nel thread della
        scheda firmate da `autore` ("MCP" se non dici chi sta scrivendo). Una scheda che
        la persona ha già compilato non si tocca: il tool rifiuta."""
        draft = FreelancerDraft(
            nome=nome,
            cognome=cognome,
            linkedin_url=linkedin_url,
            posizione=posizione,
            tariffa_giornaliera=(
                Decimal(tariffa_giornaliera) if tariffa_giornaliera is not None else None
            ),
            remoto=remoto,  # type: ignore[arg-type]
            links=links or [],
            fonti=fonti,
        )
        return _run(
            lambda s: FreelancerService(s).draft_from_signup(
                UUID(signup_id), draft, autore or DEFAULT_AUTHOR
            )
        )

    @mcp.tool()
    def list_freelancers(
        limit: int = LIST_LIMIT_DEFAULT, stato: str | None = None
    ) -> dict[str, Any]:
        """I freelance che hanno compilato il profilo sull'hub, dal più recente: nome,
        email, posizione, tariffa a giornata, disponibilità (remoto/ibrido/in_sede), link,
        stato della candidatura (nuovo, contattato, attivo, scartato) e note. Mai il CV:
        quello si scarica dall'area admin. `stato` filtra; `totale` conta tutto. `lead`
        sono le iscrizioni senza scheda (nome se c'è, email, quando), `totale_lead` quante:
        piene senza filtro o con `stato="lead"`, vuote con un altro stato."""
        return _run(lambda s: FreelancerService(s).list_recent(limit=limit, stato=stato))

    @mcp.tool()
    def get_freelancer(freelancer_id: str) -> dict[str, Any]:
        """Un freelance, per id, con `commenti`: il thread di chi lo ha seguito, dal più
        recente, ognuno con autore e data."""
        return _run(lambda s: FreelancerService(s).get(UUID(freelancer_id)))

    @mcp.tool()
    def set_freelancer_status(
        freelancer_id: str, stato: str, note: str | None = None
    ) -> dict[str, Any]:
        """Sposta una candidatura fra nuovo, contattato, attivo e scartato, con una nota
        opzionale per chi la rileggerà. Non tocca quello che la persona ha scritto."""
        return _run(
            lambda s: FreelancerService(s).set_status(
                UUID(freelancer_id), StatusChange(stato=stato, note=note)
            )
        )

    @mcp.tool()
    def add_freelancer_comment(
        freelancer_id: str, testo: str, autore: str | None = None
    ) -> dict[str, Any]:
        """Aggiunge un commento al thread di un freelance, senza toccare stato e note: una
        telefonata fatta, un'impressione, una cosa da ricordare. Resta com'è scritto, con
        data e autore; non si modifica e non si cancella. Fino a 4000 caratteri, anche su
        più righe. `autore` è "MCP" se non dici chi sta scrivendo."""
        return _run(
            lambda s: CommentService(s).add(
                "freelancer", UUID(freelancer_id), testo, autore or DEFAULT_AUTHOR
            )
        )

    @mcp.tool()
    def list_companies(limit: int = LIST_LIMIT_DEFAULT, stato: str | None = None) -> dict[str, Any]:
        """Le aziende che hanno descritto un progetto sull'hub, dal più recente: azienda,
        referente, email, progetto, da quando e per quanto, budget a giornata, stato
        (nuovo, contattato, in_corso, chiuso) e note."""
        return _run(lambda s: CompanyService(s).list_recent(limit=limit, stato=stato))

    @mcp.tool()
    def get_company(company_id: str) -> dict[str, Any]:
        """Una richiesta di un'azienda, per id, con `commenti`: il thread di chi l'ha
        seguita, dal più recente, ognuno con autore e data."""
        return _run(lambda s: CompanyService(s).get(UUID(company_id)))

    @mcp.tool()
    def set_company_status(company_id: str, stato: str, note: str | None = None) -> dict[str, Any]:
        """Sposta una richiesta fra nuovo, contattato, in_corso e chiuso, con una nota."""
        return _run(
            lambda s: CompanyService(s).set_status(
                UUID(company_id), StatusChange(stato=stato, note=note)
            )
        )

    @mcp.tool()
    def add_company_comment(
        company_id: str, testo: str, autore: str | None = None
    ) -> dict[str, Any]:
        """Aggiunge un commento al thread di una richiesta di un'azienda, senza toccare
        stato e note: come è andata la call, cosa hanno chiesto, cosa resta da fare. Resta
        com'è scritto, con data e autore; non si modifica e non si cancella. Fino a 4000
        caratteri, anche su più righe. `autore` è "MCP" se non dici chi sta scrivendo."""
        return _run(
            lambda s: CommentService(s).add(
                "company", UUID(company_id), testo, autore or DEFAULT_AUTHOR
            )
        )

    @mcp.tool()
    def guide_stats() -> dict[str, Any]:
        """Quanti hanno scaricato la guida ai primi passi da freelance: `totale` i
        download, `membri` le persone diverse dietro, `membri_totali` quante potevano,
        `ultimi_7_giorni` i download dell'ultima settimana e `recenti` gli ultimi con
        nome ed email. Solo lettura."""
        return _run(lambda s: PerkService(s).guide_stats())

    @mcp.tool()
    def login_stats() -> dict[str, Any]:
        """Chi è entrato nella sua area e quando: `totale` gli accessi con il link via
        email, `membri` le persone diverse dietro, `membri_totali` quante hanno una
        scheda, `ultimi_7_giorni` gli accessi dell'ultima settimana e `recenti` gli
        ultimi con nome ed email. Ogni scheda in `list_freelancers` e `get_freelancer`
        porta anche `accessi` e `ultimo_accesso`."""
        return _run(lambda s: LoginService(s).stats())

    def _run(call: Callable[[Session], BaseModel]) -> dict[str, Any]:
        """One session per call, closed whatever happened, and a domain error rendered
        as its own sentence rather than a stack trace."""
        session = factory()
        try:
            return call(session).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(exc.message) from exc
        finally:
            session.close()

    return mcp
