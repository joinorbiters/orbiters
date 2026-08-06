from typing import Any
from uuid import UUID


class DomainError(Exception):
    """Base for every business-rule failure.

    Carries structured `details`, never a pre-formatted sentence: the API renders
    them as RFC 9457 problem details, the MCP adapter renders them as guidance an
    LLM can act on. Those are two different renderings of the same fact.
    """

    code: str = "domain_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details


class NotFound(DomainError):
    code = "not_found"

    def __init__(self, entity: str, identifier: str | UUID) -> None:
        super().__init__(
            f"{entity} {identifier} not found", entity=entity, identifier=str(identifier)
        )


class ValidationFailed(DomainError):
    code = "validation_failed"

    def __init__(
        self, entity: str, field: str, reason: str, *, expected: str | None = None
    ) -> None:
        details: dict[str, Any] = {
            "entity": entity,
            "field": field,
            "reason": reason,
        }
        if expected is not None:
            details["expected"] = expected
        super().__init__(f"{entity}.{field}: {reason}", **details)


class Conflict(DomainError):
    code = "conflict"

    def __init__(self, entity: str, reason: str, **details: Any) -> None:
        super().__init__(f"{entity}: {reason}", entity=entity, reason=reason, **details)


class PermissionDenied(DomainError):
    code = "permission_denied"

    def __init__(self, action: str, required_roles: list[str], actual_role: str) -> None:
        super().__init__(
            f"{action} requires one of {required_roles}, actor has {actual_role}",
            action=action,
            required_roles=required_roles,
            actual_role=actual_role,
        )


class ImmutableField(DomainError):
    code = "immutable_field"

    def __init__(self, entity: str, field: str, reason: str) -> None:
        super().__init__(
            f"{entity}.{field} cannot be changed: {reason}",
            entity=entity,
            field=field,
            reason=reason,
        )
