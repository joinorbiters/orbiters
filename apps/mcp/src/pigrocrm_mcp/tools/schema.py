from typing import Any

from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.schema_registry import ENTITY_TYPES, describe_entity
from pigrocrm_mcp.context import McpContext

__all__ = ["ENTITY_TYPES", "entity_schema"]


def entity_schema(context: McpContext, entity_type: EntityType) -> dict[str, Any]:
    return describe_entity(context.session, entity_type)
