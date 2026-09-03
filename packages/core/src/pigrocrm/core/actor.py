from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from pigrocrm.core.errors import AgentForbidden, PermissionDenied

ActorType = Literal["user", "mcp", "system"]
Role = Literal["admin", "collaboratore", "readonly"]

WRITE_ROLES: tuple[str, ...] = ("admin", "collaboratore")
ADMIN_ROLES: tuple[str, ...] = ("admin",)

# The sixteen operations an agent may perform only on an installation that has opted
# in. Named by the string each service already passes to `require_write`/`require_admin`,
# so the rule attaches to the operation itself rather than to a route or a tool
# registration.
#
# **Why the list exists.** These are not merely privileged: they are irreversible in a
# way the rest of the product is not. Issuing consumes a number from a gap-free fiscal
# register that cannot be handed back; annulling and `mark_transmitted_externally` change
# what an immutable document says after the fact; the rate and period-lock operations
# rewrite what a quarter's work was worth. The worst outcome is not "the agent made a
# mistake" but "the agent made a mistake and nobody can undo it".
#
# **Why the check is here and not in a tool registration.** Until this list existed the
# ban was only half true. `apps/mcp/tests/test_mcp_invoice_ban.py` keeps these unreachable
# *structurally* -- the MCP tool is not registered -- and argues, correctly, that a role
# check would guarantee nothing, since a personal access token inherits its owner's full
# role and an administrator's token passes any role check. But the credential is not
# confined to the MCP transport: `PatService.resolve` answers with `Actor(type="mcp",
# role=<the owner's role>)`, and `apps/api`'s `get_actor` accepts that same `Bearer pgc_…`
# header on every REST route. Nothing in that package read `actor.type`. So a token handed
# to an agent on the promise that it "may prepare but may not emit" could issue an invoice
# with one `curl`. The tool was absent; the capability was not.
#
# The check below is a permission check, which is the thing that file argues against --
# and it is sound here for the reason that argument turns on: it keys on the *credential*,
# not on the role. An administrator's token does not pass it by being an administrator.
#
# **Why it is a switch and not a wall.** The product is single-tenant and self-hosted, and
# the person running it may reasonably want their own agent to do everything they can do.
# `Settings.mcp_full_access` is read once, in `PatService.resolve`, and stamped onto the
# actor as `full_access`. The default is closed, so nobody has to know this exists to be
# safe; opening it is a decision about one installation, recorded in its `.env`.
#
# The list does not change when the switch flips -- it *is* what the switch is about,
# which is why every argument above stays here in full. The real cure remains scopes on a
# token (residuo R10), which would let a token say what it is *for* rather than inherit
# everything and then be told no.
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
    # What this credential may do, carried on the credential itself rather than read
    # from a global at the point of use. `PatService.resolve` sets it from
    # `Settings.mcp_full_access`; a browser session never sets it because a `user` actor
    # is not subject to the list at all. Keeping it here is what makes a REST request
    # presenting a PAT behave exactly like the MCP transport -- the asymmetry that let a
    # `curl` issue an invoice while the tool was unregistered (commit 086c561).
    full_access: bool = False

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
        if self.type == "mcp" and not self.full_access and action in AGENT_FORBIDDEN_ACTIONS:
            raise AgentForbidden(action)

    def require_write(self, action: str) -> None:
        self._refuse_if_agent(action)
        if not self.can_write:
            raise PermissionDenied(action, list(WRITE_ROLES), self.role)

    def require_admin(self, action: str) -> None:
        self._refuse_if_agent(action)
        if not self.can_administer:
            raise PermissionDenied(action, list(ADMIN_ROLES), self.role)
