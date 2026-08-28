from typing import Any
from uuid import UUID

from pigrocrm.core.deals.schemas import DealCreate, DealListQuery, DealUpdate
from pigrocrm.core.deals.service import DealService
from pigrocrm_mcp.context import McpContext


def create(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    return (
        DealService(context.session)
        .create(DealCreate(**data), context.actor)
        .model_dump(mode="json")
    )


def update(context: McpContext, deal_id: str, data: dict[str, Any]) -> dict[str, Any]:
    result = DealService(context.session).update(UUID(deal_id), DealUpdate(**data), context.actor)
    return result.model_dump(mode="json")


def get(context: McpContext, deal_id: str) -> dict[str, Any]:
    return DealService(context.session).get(UUID(deal_id), context.actor).model_dump(mode="json")


def search(context: McpContext, query: DealListQuery) -> dict[str, Any]:
    page = DealService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def move(context: McpContext, deal_id: str, stage_id: str) -> dict[str, Any]:
    result = DealService(context.session).move_stage(UUID(deal_id), UUID(stage_id), context.actor)
    return result.model_dump(mode="json")


def archive(context: McpContext, deal_id: str) -> dict[str, str]:
    DealService(context.session).soft_delete(UUID(deal_id), context.actor)
    return {"status": "archiviato", "deal_id": deal_id}


def restore(context: McpContext, deal_id: str) -> dict[str, Any]:
    return (
        DealService(context.session).restore(UUID(deal_id), context.actor).model_dump(mode="json")
    )
