"""The sixteen operations closed to agents, closed on the credential and not on the tool.

Found by review, and it is the one finding that changed the project's threat model.

`apps/mcp/tests/test_mcp_invoice_ban.py` guarantees these operations are unreachable
*structurally* — the MCP tool is not registered — and argues, correctly, that a role
check would guarantee nothing, because a personal access token inherits its owner's full
role and an administrator's token passes any role check.

The gap was that the credential is not confined to the transport. `PatService.resolve`
answers with `Actor(type="mcp", role=<owner's role>)`, and `apps/api`'s `get_actor`
accepts the same `Bearer pgc_…` header on **every** REST route; nothing in that package
ever read `actor.type`. A token given to an agent on the written promise that it "may
prepare but may not emit" could issue an invoice with one `curl` — spending a register
number and producing a FatturaPA, with no way back.

These tests are on `Actor` rather than on a route on purpose. The defect was that the
rule lived in one adapter's tool registry; putting the fix in `packages/core` is what
makes it true of every caller, including one nobody has written yet.
"""

import pytest

from pigrocrm.core.actor import AGENT_FORBIDDEN_ACTIONS, Actor
from pigrocrm.core.errors import AgentForbidden, PermissionDenied

AGENT_ADMIN = Actor(id=None, type="mcp", role="admin")
AGENT_READONLY = Actor(id=None, type="mcp", role="readonly")
HUMAN_ADMIN = Actor(id=None, type="user", role="admin")
SYSTEM = Actor.system()


@pytest.mark.parametrize("action", sorted(AGENT_FORBIDDEN_ACTIONS))
def test_an_admin_agent_is_refused_every_forbidden_action(action: str) -> None:
    """The whole point: *admin* is the role a PAT most often carries, because a PAT
    carries whatever its owner has and the person wiring an agent up is usually the
    owner of the install. A check that only stopped a `readonly` agent would stop
    nobody who matters."""
    with pytest.raises(AgentForbidden) as caught:
        AGENT_ADMIN.require_admin(action)
    assert caught.value.details["action"] == action

    with pytest.raises(AgentForbidden):
        AGENT_ADMIN.require_write(action)


@pytest.mark.parametrize("action", sorted(AGENT_FORBIDDEN_ACTIONS))
def test_a_human_admin_is_refused_none_of_them(action: str) -> None:
    """The other half, and the one that keeps this from being a way to break the
    product: a person with the right role may still do all sixteen. If this passed
    while the product had stopped working, the test above would be satisfied by a
    service that refuses everybody."""
    HUMAN_ADMIN.require_admin(action)
    HUMAN_ADMIN.require_write(action)


def test_the_refusal_names_the_credential_and_not_the_role() -> None:
    """A `readonly` agent gets `AgentForbidden`, never `PermissionDenied`.

    The distinction is not cosmetic. `PermissionDenied` means "ask somebody senior",
    and acting on that advice here means giving the token a bigger role — which does
    nothing, because the ban does not ask about roles, and leaves an over-privileged
    credential behind. The refusal has to say the operation is closed to agents.
    """
    with pytest.raises(AgentForbidden):
        AGENT_READONLY.require_admin("issue_invoice")


def test_an_agent_keeps_everything_that_was_never_banned() -> None:
    """The ban is sixteen named operations, not a second role. An agent recording a
    time entry or creating a customer is the product working as designed."""
    AGENT_ADMIN.require_write("log_time")
    AGENT_ADMIN.require_write("create_invoice")
    AGENT_ADMIN.require_write("confirm_proforma")


def test_a_readonly_agent_still_fails_the_role_check_on_an_allowed_action() -> None:
    """The agent check runs first but does not replace the role check: an unbanned
    action still asks the ordinary question."""
    with pytest.raises(PermissionDenied):
        AGENT_READONLY.require_write("log_time")


def test_the_system_actor_is_not_an_agent() -> None:
    """Migrations, the CLI and `seed_defaults` run as `Actor.system()`. Sweeping them
    into the ban would make the installer unable to install."""
    SYSTEM.require_admin("issue_invoice")
    SYSTEM.require_write("export_invoice_xml")
