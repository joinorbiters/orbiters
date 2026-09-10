"""One HTTP seam for everything the hub sends out: the conversions pixel and the mail.

`HttpCall` is `(method, url, headers, body) -> (status, body)`. Production hands
`urllib_call`; a test hands a fake and reads what would have left. No dependency, no
retry, and a network error travels as `NETWORK_ERROR_STATUS` rather than as a second
failure path, the convention PigroCRM's transports set.
"""

import urllib.error
import urllib.request
from collections.abc import Callable

HTTP_TIMEOUT_SECONDS = 10
# Both endpoints the hub calls, api.resend.com and bzr.openai.com, sit behind Cloudflare,
# which answers `403 error code: 1010` to urllib's default `Python-urllib/3.x` signature
# and never reaches the application behind it. Found on 2026-09-10 by sending a mail for
# real: curl with the same JSON went through, the seam did not. The name says who calls.
USER_AGENT = "orbiters-hub/0.1 (+https://joinorbiters.com)"
# "No HTTP response was ever received", travelling through the same channel as a real
# status rather than a second failure path -- the convention PigroCRM's Gmail and Drive
# transports use, and the same number.
NETWORK_ERROR_STATUS = 599

# (method, url, headers, body) -> (status, body). Narrower than the Gmail seam on
# purpose: there is no retry here, so a `Retry-After` would have nothing to inform.
HttpCall = Callable[[str, str, dict[str, str], bytes], tuple[int, bytes]]


def urllib_call(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    """`urllib`, no dependency.

    An HTTP error is a *status*, not an exception: `urllib` raises `HTTPError` for a
    4xx, and unwrapping it here is what lets `send` treat "OpenAI refused the event"
    and "OpenAI accepted it" through one path.
    """
    sent = {"User-Agent": USER_AGENT, **headers}
    request = urllib.request.Request(url, data=body, headers=sent, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()
