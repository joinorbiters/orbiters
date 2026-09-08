"""Which space a request belongs to, read from the first segment of its path.

`/<slug>/api/...` and `/<slug>/health` are a space's requests: the middleware strips
the prefix -- so every router keeps its `/api/...` paths and knows nothing about
tenants -- and records the slug on the request. `deps.get_session` then opens that
space's database, and `routers/auth.py` scopes the cookies to `/<slug>/`. A path with
no such prefix is the root installation, exactly as before this module existed.

Pure ASGI rather than `BaseHTTPMiddleware`: the path has to change *before* routing,
and the slug must travel on `scope["state"]`, which is what `Request.state` reads.
"""

import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import Request

from pigrocrm.core.tenants import RESERVED_SLUGS, SLUG_PATTERN

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# The slug's own grammar, then the two path families the API answers on.
_PREFIXED = re.compile(r"^/([a-z0-9][a-z0-9-]{1,30}[a-z0-9])(/(?:api|health)(?:/.*)?)$")


def split_tenant_prefix(path: str) -> tuple[str | None, str]:
    """`("studio", "/api/customers")` for `/studio/api/customers`; `(None, path)` when
    there is no prefix, or when the would-be slug is a reserved word -- `/api/...` is
    never anybody's space, and `/app/...` never reaches the API at all."""
    match = _PREFIXED.match(path)
    if not match:
        return None, path
    slug, rest = match.group(1), match.group(2)
    if slug in RESERVED_SLUGS or not SLUG_PATTERN.match(slug):
        return None, path
    return slug, rest


class TenantPrefixMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            slug, rest = split_tenant_prefix(scope["path"])
            if slug is not None:
                scope["path"] = rest
                scope["raw_path"] = rest.encode("utf-8")
                scope.setdefault("state", {})["tenant"] = slug
        await self.app(scope, receive, send)


def tenant_slug(request: Request) -> str | None:
    """The space this request is for, or None for the root installation."""
    slug = getattr(request.state, "tenant", None)
    return slug if isinstance(slug, str) else None


def cookie_path(request: Request) -> str:
    """Session cookies live under the space's prefix, so two spaces in one browser
    never see each other's session; the root keeps `/` as it always did."""
    slug = tenant_slug(request)
    return f"/{slug}/" if slug else "/"
