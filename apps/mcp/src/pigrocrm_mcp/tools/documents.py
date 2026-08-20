from typing import Any
from uuid import UUID

from pigrocrm.core.documents.schemas import DocumentFromTemplate, DocumentListQuery
from pigrocrm.core.documents.service import DocumentService
from pigrocrm.core.templates.schemas import TemplateListQuery
from pigrocrm.core.templates.service import TemplateService
from pigrocrm_mcp.context import McpContext


def _documents(context: McpContext) -> DocumentService:
    return DocumentService(context.session, context.storage)


def search(context: McpContext, query: DocumentListQuery) -> dict[str, Any]:
    page = _documents(context).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def get(context: McpContext, document_id: str) -> dict[str, Any]:
    return _documents(context).get(UUID(document_id), context.actor).model_dump(mode="json")


def create_from_template(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    result = _documents(context).create_from_template(DocumentFromTemplate(**data), context.actor)
    return result.model_dump(mode="json")


def set_state(context: McpContext, document_id: str, stato: str) -> dict[str, Any]:
    result = _documents(context).set_offer_state(UUID(document_id), stato, context.actor)  # type: ignore[arg-type]
    return result.model_dump(mode="json")


def versions(context: McpContext, document_id: str) -> dict[str, Any]:
    entries = _documents(context).versions(UUID(document_id), context.actor)
    return {"versions": [entry.model_dump(mode="json") for entry in entries]}


def list_templates(context: McpContext, include_archived: bool) -> dict[str, Any]:
    """`TemplateService.list` takes a `TemplateListQuery` and returns a paginated
    `TemplatePage` -- not `(actor, include_archived=...)` returning a plain list.
    The plan this tool was drafted from predates that signature; `include_archived`
    (the tool's own public parameter name, unchanged, since it is what an agent
    already sees in the registered schema) maps onto the service's own
    `include_inactive` field."""
    page = TemplateService(context.session).list(
        TemplateListQuery(include_inactive=include_archived), context.actor
    )
    return {
        "templates": [
            {"id": str(t.id), "nome": t.nome, "tipo": t.tipo, "attivo": t.attivo}
            for t in page.items
        ],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def describe_template(context: McpContext, template_id: str) -> dict[str, Any]:
    described = TemplateService(context.session).describe(UUID(template_id), context.actor)
    return described.model_dump(mode="json")
