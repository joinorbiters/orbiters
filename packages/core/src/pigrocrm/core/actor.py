from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from pigrocrm.core.errors import PermissionDenied

ActorType = Literal["user", "mcp", "system"]
Role = Literal["admin", "collaboratore", "readonly"]

WRITE_ROLES: tuple[str, ...] = ("admin", "collaboratore")
ADMIN_ROLES: tuple[str, ...] = ("admin",)


class Actor(BaseModel):
    """Who is performing an operation. Always passed explicitly — never inferred
    from global state — so that authorization is testable and the timeline is honest
    about whether a human or an agent made the change."""

    model_config = ConfigDict(frozen=True)

    id: UUID | None
    type: ActorType
    role: Role

    @classmethod
    def system(cls) -> Self:
        return cls(id=None, type="system", role="admin")

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    @property
    def can_administer(self) -> bool:
        return self.role in ADMIN_ROLES

    def require_write(self, action: str) -> None:
        if not self.can_write:
            raise PermissionDenied(action, list(WRITE_ROLES), self.role)

    def require_admin(self, action: str) -> None:
        if not self.can_administer:
            raise PermissionDenied(action, list(ADMIN_ROLES), self.role)
