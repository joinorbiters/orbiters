"""The one urllib call every outbound request goes through."""

import urllib.request
from typing import Any

import pytest

from orbiters_core.http import USER_AGENT, urllib_call


class _Response:
    status = 200

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


def test_every_call_names_itself_unless_the_caller_already_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloudflare in front of Resend and of OpenAI's conversions endpoint answers
    `403 error code: 1010` to urllib's default signature: without a name of our own
    every login mail and every conversion is refused before reaching the API."""
    seen: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        seen.append(request)
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    urllib_call("POST", "https://api.example.test/x", {"Content-Type": "application/json"}, b"{}")
    urllib_call("GET", "https://api.example.test/y", {"User-Agent": "altro/1"}, b"")
    assert seen[0].get_header("User-agent") == USER_AGENT
    assert USER_AGENT.startswith("orbiters-hub/")
    assert seen[1].get_header("User-agent") == "altro/1"
    assert seen[0].get_header("Content-type") == "application/json"
    # A GET with nothing to send carries no body at all: `data=b""` would make urllib
    # write `Content-Length: 0` and a form content type on a request some proxies then
    # refuse (the registry read of ORB-142 is such a GET).
    assert seen[1].data is None
    assert seen[0].data == b"{}"


def test_an_http_error_is_a_status_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def refuse(request: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    status, _ = urllib_call("GET", "https://api.example.test/z", {}, b"")
    assert status == 403
