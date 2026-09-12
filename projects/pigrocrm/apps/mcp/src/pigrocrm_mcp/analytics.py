"""PostHog on the MCP surface: every tool call an agent makes, counted.

The web reports pageviews and the activation events (ORB-184); the MCP is the surface
the onboarding spec sells first, and until this module nothing recorded whether an
agent used it. PostHog's own adapter wraps the `MCPServer` and emits `$mcp_tool_call`,
`$mcp_tools_list`, `$mcp_initialize` and `$mcp_exception` with the tool name, the
parameters, the response, the duration and the error flag; this module decides three
things around it.

- **Off by default.** An empty `PIGROCRM_POSTHOG_KEY` builds no client and changes
  nothing: a self-hosted CRM measures nothing unless its operator says so, and the test
  suite never sends an event. The key is the public project key
  (`shared/analytics/posthog.ts` carries the same one for the browsers), read from the
  environment rather than imported because this process runs in the API image.
- **The same identity as the web.** The actor's user id is the `distinct_id` and the
  installation's slug is the `spazio` group, so a customer created from Claude and one
  created from the UI land on the same person and the same space. An actor with no id
  (the fixtures' `mcp` admin) stays anonymous.
- **No schema change.** The adapter would inject a required `context` argument on every
  tool to capture the agent's intent; that alters every tool's input schema, which the
  surface tests pin and which every connected agent has already learned. Off.

Design: `docs/design/2026-09-12-posthog-analytics-design.md`, ORB-186.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pigrocrm.core.config import Settings
from pigrocrm_mcp.context import ActorProvider

if TYPE_CHECKING:
    from mcp.server import MCPServer
    from posthog import Posthog
    from posthog.mcp.types import UserIdentity

GROUP_TYPE = "spazio"
ROOT_GROUP = "root"


def space_group(settings: Settings) -> str:
    """The `spazio` group key: the installation's slug, `root` when it has none."""
    return settings.root_slug or ROOT_GROUP


def identity_for(actor_provider: ActorProvider, spazio: str) -> Any:
    """The callback the adapter calls per request: the actor of *this* call.

    Reads the provider each time rather than once, because the HTTP transport
    (ORB-170) resolves the actor per request from the bearer token; the stdio process
    resolves it once at start-up and the provider simply keeps answering the same one.
    """
    from posthog.mcp.types import UserIdentity

    def identify(request: object, extra: object) -> UserIdentity | None:
        actor = actor_provider()
        if actor.id is None:
            return None
        return UserIdentity(
            distinct_id=str(actor.id),
            properties={"ruolo": actor.role, "via": actor.type},
            groups={GROUP_TYPE: spazio},
        )

    return identify


def build_client(settings: Settings) -> Posthog | None:
    """A client when the installation has a key, `None` when it has not."""
    if not settings.posthog_key:
        return None
    from posthog import Posthog

    return Posthog(settings.posthog_key, host=settings.posthog_host)


def install(
    mcp: MCPServer,
    settings: Settings,
    actor_provider: ActorProvider,
    client: Posthog | None = None,
) -> bool:
    """Wrap `mcp` for PostHog when the installation asks for it; answers whether it did.

    `client` is injectable so a test can hand one whose `capture` it observes; every
    other caller lets `build_client` decide from the settings. Idempotent per server
    instance, like the adapter underneath.
    """
    resolved = client if client is not None else build_client(settings)
    if resolved is None:
        return False
    from posthog.mcp import instrument
    from posthog.mcp.types import MCPAnalyticsOptions

    instrument(
        mcp,
        resolved,
        MCPAnalyticsOptions(
            context=False,
            identify=identity_for(actor_provider, space_group(settings)),
        ),
    )
    return True
