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

from pigrocrm.core.config import get_settings
from pigrocrm.core.tenants import RESERVED_SLUGS, SLUG_PATTERN

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# The slug's own grammar, then the two path families the API answers on.
_PREFIXED = re.compile(r"^/([a-z0-9][a-z0-9-]{1,30}[a-z0-9])(/(?:api|health)(?:/.*)?)$")


def split_tenant_prefix(path: str, root_slug: str = "") -> tuple[str | None, str]:
    """`("studio", "/api/customers")` for `/studio/api/customers`; `(None, path)` when
    there is no prefix, or when the would-be slug is a reserved word -- `/api/...` is
    never anybody's space, and `/app/...` never reaches the API at all.

    `root_slug` is the root installation's own name (`PIGROCRM_ROOT_SLUG`): its prefix
    is stripped like a space's, but the request stays the root's -- `(None, rest)` --
    so it opens the root database with the root's settings, Gmail and Drive included."""
    match = _PREFIXED.match(path)
    if not match:
        return None, path
    slug, rest = match.group(1), match.group(2)
    if root_slug and slug == root_slug:
        return None, rest
    if slug in RESERVED_SLUGS or not SLUG_PATTERN.match(slug):
        return None, path
    return slug, rest


class TenantPrefixMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            # Read per request rather than captured at construction: `get_settings` is
            # cached, so this costs nothing, and a test that clears the cache after
            # setting PIGROCRM_ROOT_SLUG is honoured.
            root_slug = get_settings().root_slug
            slug, rest = split_tenant_prefix(scope["path"], root_slug)
            if rest != scope["path"]:
                scope["path"] = rest
                scope["raw_path"] = rest.encode("utf-8")
                # The prefix the request wore, space or root alias: what cookies are
                # scoped to, so two spaces in one browser never share a session and the
                # root under its own name is no exception.
                scope.setdefault("state", {})["prefix"] = slug or root_slug
            if slug is not None:
                scope.setdefault("state", {})["tenant"] = slug
        await self.app(scope, receive, send)


def tenant_slug(request: Request) -> str | None:
    """The space this request is for, or None for the root installation."""
    slug = getattr(request.state, "tenant", None)
    return slug if isinstance(slug, str) else None


def cookie_path(request: Request) -> str:
    """Session cookies live under a space's prefix, so two spaces in one browser never
    see each other's session. The root keeps `/` -- under its own name too, since
    2026-09-09: the root logs in at the bare `/app/login` and works under
    `/<root_slug>/app`, and one jar at `/` is the only thing both paths can read. A
    root cookie that reaches a space's API names a user that space does not have, and
    `get_actor` answers 401 like for any stranger."""
    slug = tenant_slug(request)
    return f"/{slug}/" if slug else "/"


def cookie_paths_to_clear(request: Request, root_slug: str = "") -> list[str]:
    """Every path a session cookie of this installation may have been set at, most
    specific first: the one `cookie_path` uses now, the prefix the request wore, the
    root's own name (`/studiorossi/`, where the root's cookies lived before 2026-09-09)
    and `/`.

    A browser removes a cookie only for a matching path, and it *sends* every cookie
    whose path matches, longest path first. So a stale pair left at `/studiorossi/`
    does worse than survive a logout: it shadows the live pair at `/` on every request
    under the alias, `first_cookie` reads the dead token, and the session dies within
    the access cookie's lifetime. Login and refresh therefore clear the other jars
    too, not only logout -- see `routers/auth.py`."""
    paths = {cookie_path(request), "/"}
    prefix = getattr(request.state, "prefix", None)
    if isinstance(prefix, str) and prefix:
        paths.add(f"/{prefix}/")
    if root_slug and tenant_slug(request) is None:
        paths.add(f"/{root_slug}/")
    return sorted(paths, key=len, reverse=True)


def first_cookie(request: Request, name: str) -> str | None:
    """The value of `name` as the browser ranks it: the first in the header.

    A browser sends every cookie whose path matches, longer paths first (RFC 6265
    §5.4), so when a space's `/studio/` jar and the root's `/` jar both hold a session
    the first value is the space's own. `request.cookies` is `SimpleCookie`, which
    keeps the *last* -- the root's -- and would hand a space the wrong session. Values
    are JWTs: no `;`, no `=` beyond the first, nothing quoted."""
    for pair in request.headers.get("cookie", "").split(";"):
        key, sep, value = pair.strip().partition("=")
        if sep and key.strip() == name and value.strip():
            return value.strip()
    return None
