"""Small urllib HTTP helper. Adapters take a ``transport`` so tests can replay request shapes
without the network; the default one talks to the real APIs."""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

# (method, url, headers, body, timeout) -> (status, lower-cased headers, body bytes)
Transport = Callable[[str, str, Dict[str, str], Optional[bytes], float], Tuple[int, Dict[str, str], bytes]]


class HttpError(Exception):
    def __init__(self, method: str, url: str, status: int, body: bytes):
        self.status = status
        self.body = body.decode("utf-8", "replace")[:1500]
        # never echo tokens from query strings into logs or the db
        safe = urllib.parse.urlsplit(url)._replace(query="").geturl()
        super().__init__(f"{method} {safe} -> HTTP {status}: {self.body}")

    @property
    def retryable(self) -> bool:
        return self.status == 429 or self.status >= 500 or self.status == 0


def urllib_transport(method, url, headers, body, timeout):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https API hosts
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return 0, {}, str(exc).encode()


def call(transport: Transport, method: str, url: str, *, params: Optional[Dict[str, Any]] = None,
         json_body: Any = None, form: Optional[Dict[str, Any]] = None, body: Optional[bytes] = None,
         headers: Optional[Dict[str, str]] = None, ok: Tuple[int, ...] = (200, 201), timeout: float = 120,
         raw: bool = False):
    """Send one request; return parsed JSON (or ``(status, headers, bytes)`` with ``raw``)."""
    headers = dict(headers or {})
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers.setdefault("Content-Type", "application/json; charset=UTF-8")
    elif form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    status, resp_headers, data = transport(method, url, headers, body, timeout)
    if status not in ok:
        raise HttpError(method, url, status, data)
    if raw:
        return status, resp_headers, data
    return json.loads(data or b"{}")
