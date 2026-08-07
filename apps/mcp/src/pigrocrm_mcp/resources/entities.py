from uuid import UUID

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.people.schemas import PersonListQuery
from pigrocrm.core.people.service import PersonService
from pigrocrm_mcp.context import McpContext


def _timeline_lines(context: McpContext, entity: str, entity_id: UUID) -> list[str]:
    entries = ActivityService(context.session).timeline(entity, entity_id, limit=10)
    if not entries:
        return ["_Nessuna attività registrata._"]
    return [f"- {e.occurred_at:%Y-%m-%d %H:%M} · **{e.kind}** · da {e.actor_type}" for e in entries]


def _custom_lines(custom_fields: dict[str, object]) -> list[str]:
    if not custom_fields:
        return []
    return ["", "## Campi personalizzati", ""] + [
        f"- **{key}**: {value}" for key, value in sorted(custom_fields.items())
    ]


def render_customer(context: McpContext, customer_id: UUID) -> str:
    customer = CustomerService(context.session).get(customer_id, context.actor)
    people = PersonService(context.session).list(
        PersonListQuery(customer_id=customer_id, limit=50), context.actor
    )
    from pigrocrm.core.deals.schemas import DealListQuery

    deals = DealService(context.session).list(
        DealListQuery(customer_id=customer_id, limit=50), context.actor
    )

    lines = [
        f"# {customer.ragione_sociale}",
        "",
        "## Dati fiscali",
        "",
        f"- P.IVA: {customer.partita_iva or '—'}",
        f"- Codice fiscale: {customer.codice_fiscale or '—'}",
        f"- Codice SDI: {customer.codice_sdi or '—'}",
        f"- PEC: {customer.pec or '—'}",
        f"- Indirizzo: {customer.indirizzo or '—'}, {customer.cap or ''} "
        f"{customer.comune or ''} ({customer.provincia or ''}) {customer.nazione}",
        "",
        "## Contatti",
        "",
    ]
    lines += [
        f"- {p.nome} {p.cognome or ''} — {p.ruolo or 'ruolo non indicato'} — {p.email or '—'}"
        for p in people.items
    ] or ["_Nessun contatto._"]
    lines += ["", "## Deal", ""]
    lines += [
        f"- {d.nome} — valore previsto {d.valore_previsto or '—'} — probabilità {d.probabilita}%"
        for d in deals.items
    ] or ["_Nessun deal._"]
    lines += _custom_lines(customer.custom_fields)
    lines += ["", "## Timeline", ""] + _timeline_lines(context, "customer", customer_id)
    if customer.note:
        lines += ["", "## Note", "", customer.note]
    return "\n".join(lines)


def render_person(context: McpContext, person_id: UUID) -> str:
    person = PersonService(context.session).get(person_id, context.actor)
    lines = [
        f"# {person.nome} {person.cognome or ''}".strip(),
        "",
        f"- Ruolo: {person.ruolo or '—'}",
        f"- Email: {person.email or '—'}",
        f"- Telefono: {person.telefono or '—'}",
        f"- LinkedIn: {person.linkedin or '—'}",
    ]
    if person.customer_id:
        customer = CustomerService(context.session).get(person.customer_id, context.actor)
        lines.append(f"- Cliente: {customer.ragione_sociale} (`customer://{customer.id}`)")
    else:
        lines.append("- Cliente: non associato")
    lines += _custom_lines(person.custom_fields)
    lines += ["", "## Timeline", ""] + _timeline_lines(context, "person", person_id)
    if person.note:
        lines += ["", "## Note", "", person.note]
    return "\n".join(lines)


def render_deal(context: McpContext, deal_id: UUID) -> str:
    deal = DealService(context.session).get(deal_id, context.actor)
    customer = CustomerService(context.session).get(deal.customer_id, context.actor)

    from pigrocrm.core.pipeline.service import PipelineService

    stage = PipelineService(context.session).get(deal.pipeline_stage_id)

    lines = [
        f"# {deal.nome}",
        "",
        f"- Cliente: {customer.ragione_sociale} (`customer://{customer.id}`)",
        f"- Stato: {stage.nome} ({stage.tipo})",
        f"- Valore previsto: {deal.valore_previsto or '—'}",
        f"- Probabilità: {deal.probabilita}%",
        f"- Chiusura prevista: {deal.data_chiusura_prevista or '—'}",
        f"- Ore preventivate: {deal.ore_preventivate or '—'}",
        f"- Valore preventivato: {deal.valore_preventivato or '—'}",
    ]
    lines += _custom_lines(deal.custom_fields)
    lines += ["", "## Timeline", ""] + _timeline_lines(context, "deal", deal_id)
    if deal.note:
        lines += ["", "## Note", "", deal.note]
    return "\n".join(lines)
