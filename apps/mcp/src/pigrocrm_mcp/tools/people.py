from typing import Any
from uuid import UUID

from pigrocrm.core.people.schemas import PersonCreate, PersonListQuery, PersonUpdate
from pigrocrm.core.people.service import PersonService
from pigrocrm_mcp.context import McpContext


def create(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    return (
        PersonService(context.session)
        .create(PersonCreate(**data), context.actor)
        .model_dump(mode="json")
    )


def update(context: McpContext, person_id: str, data: dict[str, Any]) -> dict[str, Any]:
    result = PersonService(context.session).update(
        UUID(person_id), PersonUpdate(**data), context.actor
    )
    return result.model_dump(mode="json")


def get(context: McpContext, person_id: str) -> dict[str, Any]:
    return (
        PersonService(context.session).get(UUID(person_id), context.actor).model_dump(mode="json")
    )


def search(context: McpContext, query: PersonListQuery) -> dict[str, Any]:
    page = PersonService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def archive(context: McpContext, person_id: str) -> dict[str, str]:
    PersonService(context.session).soft_delete(UUID(person_id), context.actor)
    return {"status": "archiviato", "person_id": person_id}


def restore(context: McpContext, person_id: str) -> dict[str, Any]:
    return (
        PersonService(context.session)
        .restore(UUID(person_id), context.actor)
        .model_dump(mode="json")
    )
