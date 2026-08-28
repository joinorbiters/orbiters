from typing import Any
from uuid import UUID

from pigrocrm.core.customers.schemas import CustomerCreate, CustomerListQuery, CustomerUpdate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm_mcp.context import McpContext


def create(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    service = CustomerService(context.session)
    return service.create(CustomerCreate(**data), context.actor).model_dump(mode="json")


def update(context: McpContext, customer_id: str, data: dict[str, Any]) -> dict[str, Any]:
    service = CustomerService(context.session)
    result = service.update(UUID(customer_id), CustomerUpdate(**data), context.actor)
    return result.model_dump(mode="json")


def get(context: McpContext, customer_id: str) -> dict[str, Any]:
    return (
        CustomerService(context.session)
        .get(UUID(customer_id), context.actor)
        .model_dump(mode="json")
    )


def search(context: McpContext, query: CustomerListQuery) -> dict[str, Any]:
    page = CustomerService(context.session).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def archive(context: McpContext, customer_id: str) -> dict[str, str]:
    CustomerService(context.session).soft_delete(UUID(customer_id), context.actor)
    return {"status": "archiviato", "customer_id": customer_id}


def restore(context: McpContext, customer_id: str) -> dict[str, Any]:
    return (
        CustomerService(context.session)
        .restore(UUID(customer_id), context.actor)
        .model_dump(mode="json")
    )
