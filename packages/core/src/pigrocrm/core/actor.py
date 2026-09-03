from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from pigrocrm.core.errors import AgentForbidden, PermissionDenied

ActorType = Literal["user", "mcp", "system"]
Role = Literal["admin", "collaboratore", "readonly"]

WRITE_ROLES: tuple[str, ...] = ("admin", "collaboratore")
ADMIN_ROLES: tuple[str, ...] = ("admin",)

# The operations no agent may perform, whatever role its owner holds. Named by the
# string each service already passes to `require_write`/`require_admin`, so the ban
# attaches to the operation itself rather than to a route or a tool registration.
#
# This exists because the ban it enforces was, until it was written, only half true.
# `apps/mcp/tests/test_mcp_invoice_ban.py` guarantees these sixteen are unreachable
# *structurally* — the MCP tool is simply not registered — and argues, correctly, that a
# permission check would be no guarantee at all, since a personal access token inherits
# its owner's full role and an administrator's token passes any role check.
#
# But the credential is not confined to the MCP transport. `PatService.resolve` answers
# with `Actor(type="mcp", role=<the owner's role>)`, and `apps/api`'s `get_actor` accepts
# that same `Bearer pgc_…` header on **every** REST route. Nothing in that package ever
# looked at `actor.type`. So the token handed to an agent on the promise that it "may
# prepare but may not emit" could issue an invoice with one `curl` — consuming a register
# number and producing a FatturaPA, irreversibly. The tool was absent; the capability was
# not.
#
# The check below is a permission check, which is the thing that file argues against —
# and it is sound here for the reason that argument turns on: it keys on the *credential
# type*, not on the role. An administrator's token does not pass it, because being an
# administrator is not what it asks about. It lives in `packages/core` so both adapters
# inherit it and a future router cannot forget it, and it is the second line, not the
# first: the tool stays unregistered.
#
# The real cure is scopes on a token (residuo R10), which would let a token say what it
# is for instead of inheriting everything. Until that exists, this is the floor.
AGENT_FORBIDDEN_ACTIONS: frozenset[str] = frozenset(
    {
        # Fiscal acts: they consume a register number or change what an immutable
        # document says after the fact (slice 3 §11).
        "issue_invoice",
        "annul_invoice",
        "mark_transmitted_externally",
        "export_invoice_xml",
        "update_fiscal_profile",
        # Rates, cost categories and period locks: configuration, or rewriting what a
        # quarter's work was worth (slice 4 §11).
        "recalculate_rates",
        "update_user_rates",
        "update_deal_rate",
        "create_cost_category",
        "update_cost_category",
        "archive_cost_category",
        "unarchive_cost_category",
        "close_period",
        "reopen_period",
        # The bridge from hours to an invoice line, and the annual estimate.
        "bind_time_to_invoice",
        "get_fiscal_estimate",
    }
)


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

    def _refuse_if_agent(self, action: str) -> None:
        """Checked before the role, deliberately.

        A `readonly` agent asking to issue an invoice should be told the operation is
        closed to agents, not that it needs a better role — the second answer invites
        somebody to hand the token a bigger role, which is exactly the wrong move.
        """
        if self.type == "mcp" and action in AGENT_FORBIDDEN_ACTIONS:
            raise AgentForbidden(action)

    def require_write(self, action: str) -> None:
        self._refuse_if_agent(action)
        if not self.can_write:
            raise PermissionDenied(action, list(WRITE_ROLES), self.role)

    def require_admin(self, action: str) -> None:
        self._refuse_if_agent(action)
        if not self.can_administer:
            raise PermissionDenied(action, list(ADMIN_ROLES), self.role)
