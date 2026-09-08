"""The thin half. Everything that matters happened in `AutomationConfigService`.

Shaped exactly like `tools/search.py`: resolve the service on the context's session, call
it, `model_dump(mode="json")`.

**One tool, and the missing one is the point.** Spec §11.1 puts `describe_automations` on
both surfaces and `update_automation_config` on the API only, and requires the slice-6
exclusion list to be exactly that one name. `packages/core/tests/test_architecture.py`
asserts both halves -- that no tool source anywhere contains a call to that method, and
that every *other* public method of an audited slice-6 service is reachable from a tool.
(The check is a substring match on the call site, so this docstring cannot spell the call
out: writing the banned text here would fail the very test being described, which is a
sharper demonstration of the matcher than any comment about it.)

The ban is imposed by not writing the tool rather than by a permission check,
because residuo R10 leaves a personal access token carrying its owner's full role: an
admin's token would pass any check written inside a registered tool.

Reading what the system does by itself is the opposite case. An agent that cannot see the
automations would attribute their effects to somebody's manual edit -- it would watch a
deal move to «vinto» with no tool call to explain it -- which is a worse position to
reason from than knowing the rule and knowing it cannot change it.
"""

from typing import Any

from pigrocrm.core.automations.config_service import AutomationConfigService
from pigrocrm_mcp.context import McpContext


def describe_automations(context: McpContext) -> dict[str, Any]:
    return (
        AutomationConfigService(context.session)
        .describe_automations(context.actor)
        .model_dump(mode="json")
    )
