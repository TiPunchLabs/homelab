"""Fixed HTTPS transport for the two services the plugin may reach: AgentMail (GET) and the model.

The only network egress of the plugin goes through ``Transport.request``. It allows:
- exactly two operations of AgentMail (list messages, get one message) of ONE configured inbox;
- one POST to the configured model endpoint.
Hosts are allowlisted, redirects are never followed (a 3xx is an error and the credential is
not resent), TLS is verified, bodies are read with a byte ceiling, and every call is counted
against the per-request budget; the wall-clock deadline is enforced during the exchange,
including while a response body is streamed.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from collections.abc import Callable
from urllib.parse import quote, urlencode, urlsplit

from .config import AGENTMAIL_HOSTS, MODEL_HOSTS, Settings

MESSAGE_ID_RE = re.compile(r"^[\x21-\x7e]{1,512}$")
PAGE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{1,2048}$")


class MailError(Exception):
    """Base class; ``code`` selects the fixed French message, never the exception text."""

    code = "unavailable"


class PolicyError(MailError):
    code = "policy"


class AuthError(MailError):
    code = "auth"


class RateLimited(MailError):
    code = "rate_limited"


class Unavailable(MailError):
    code = "unavailable"


class TooLarge(MailError):
    code = "too_large"


class Malformed(MailError):
    code = "malformed"


class BudgetExceeded(MailError):
    code = "budget"


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HttpBackend(Protocol):
    """Pluggable wire; the real one is httpx, tests inject a recording fake."""

    def send(self, method: str, url: str, headers: dict[str, str], body: bytes | None,
             timeout: float, max_bytes: int, *, remaining: Callable[[], float]) -> RawResponse: ...


class HttpxBackend:
    """httpx without redirects, with TLS verification, a streamed byte ceiling and a hard deadline.

    ``timeout`` bounds each network operation; ``remaining`` bounds the whole exchange. A watchdog
    shuts the TCP socket down when the time left runs out, which aborts a blocked connect, write
    or read, and the stream loop re-checks the time after every chunk, so a server that trickles
    bytes cannot hold the worker past the request deadline. Residual: name resolution happens
    before a socket exists and is bounded by the system resolver, not by the watchdog.
    """

    def send(self, method: str, url: str, headers: dict[str, str], body: bytes | None,
             timeout: float, max_bytes: int, *, remaining: Callable[[], float]) -> RawResponse:
        import httpx

        left = remaining()
        if left <= 0:
            raise BudgetExceeded()
        expired = threading.Event()
        sockets: list[Any] = []
        guard = threading.Lock()

        def trace(name: str, info: dict[str, Any]) -> None:
            if name == "connection.connect_tcp.complete":
                sock = info["return_value"].get_extra_info("socket")
                with guard:
                    sockets.append(sock)
                    if expired.is_set():
                        _shutdown(sock)

        def fire() -> None:
            with guard:
                expired.set()
                for sock in sockets:
                    _shutdown(sock)

        watchdog = threading.Timer(left, fire)
        watchdog.daemon = True
        watchdog.start()
        try:
            with httpx.Client(follow_redirects=False, verify=True, timeout=min(timeout, left),
                              trust_env=False) as client:
                with client.stream(method, url, headers=headers, content=body,
                                   extensions={"trace": trace}) as resp:
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        if expired.is_set() or remaining() <= 0:
                            raise BudgetExceeded()
                        size += len(chunk)
                        if size > max_bytes:
                            raise TooLarge()
                        chunks.append(chunk)
                    if expired.is_set() or remaining() <= 0:
                        raise BudgetExceeded()
                    return RawResponse(resp.status_code, {k.lower(): v for k, v in resp.headers.items()},
                                       b"".join(chunks))
        except (TooLarge, BudgetExceeded):
            raise
        except (httpx.HTTPError, OSError) as exc:
            if expired.is_set():
                raise BudgetExceeded() from exc
            raise Unavailable() from exc
        finally:
            watchdog.cancel()


def _shutdown(sock: Any) -> None:
    """Abort any blocked I/O on the socket; errors (already closed) are irrelevant."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except (OSError, AttributeError):
        pass


@dataclass
class Budget:
    """Per-request counters and deadline; exceeding any of them raises ``BudgetExceeded``."""

    deadline: float
    http_calls_max: int
    model_calls_max: int
    clock: Callable[[], float] = time.monotonic
    http_calls: int = 0
    model_calls: int = 0
    retries: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def remaining(self) -> float:
        """Seconds left before the wall-clock ceiling."""
        return self.deadline - self.clock()

    def check_time(self, needed: float = 0.5) -> None:
        """Refuse to start an operation that cannot finish in time."""
        if self.remaining() < needed:
            raise BudgetExceeded()


class Transport:
    """Allowlisted operations only; there is no generic request method."""

    def __init__(self, settings: Settings, backend: HttpBackend, secrets: Callable[[str], str | None],
                 budget: Budget, sleep: Callable[[float], None] = time.sleep) -> None:
        self._s = settings
        self._backend = backend
        self._secrets = secrets
        self._budget = budget
        self._sleep = sleep

    def _agentmail_key(self) -> str:
        key = self._secrets(self._s.agentmail_key_env)
        if not key or not isinstance(key, str) or any(c.isspace() for c in key):
            raise AuthError()
        return key

    def _inbox_path(self) -> str:
        return f"{self._s.agentmail_base}/inboxes/{quote(self._s.inbox_id, safe='@')}/messages"

    def _guard_url(self, url: str, hosts: frozenset[str]) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in hosts or parts.port not in (None, 443) \
                or parts.username or parts.password or parts.fragment:
            raise PolicyError()

    def _get_json(self, url: str, max_bytes: int) -> dict[str, Any]:
        self._guard_url(url, AGENTMAIL_HOSTS)
        if not url.startswith(self._inbox_path()):
            raise PolicyError()
        limits = self._s.limits
        attempt = 0
        while True:
            if self._budget.http_calls >= self._budget.http_calls_max:
                raise BudgetExceeded()
            self._budget.check_time()
            self._budget.http_calls += 1
            started = self._budget.clock()
            resp = self._backend.send(
                "GET", url, {"Authorization": f"Bearer {self._agentmail_key()}", "Accept": "application/json"},
                None, min(limits.http_timeout_s, max(self._budget.remaining(), 0.1)), max_bytes,
                remaining=self._budget.remaining)
            self._budget.events.append({"op": "agentmail_get", "status": resp.status,
                                        "bytes": len(resp.body), "ms": int((self._budget.clock() - started) * 1000)})
            if resp.status == 429 or resp.status >= 500:
                if attempt >= limits.http_retries:
                    raise RateLimited() if resp.status == 429 else Unavailable()
                wait = _retry_after(resp.headers.get("retry-after"), limits.retry_after_max_s)
                if wait is None or self._budget.remaining() < wait + 1.0:
                    raise RateLimited() if resp.status == 429 else Unavailable()
                attempt += 1
                self._budget.retries += 1
                self._sleep(wait)
                continue
            if resp.status in (401, 403):
                raise AuthError()
            if 300 <= resp.status < 400:
                raise PolicyError()
            if resp.status == 404:
                raise Malformed()
            if resp.status != 200:
                raise Unavailable()
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype.lower():
                raise Malformed()
            try:
                data = json.loads(resp.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise Malformed() from exc
            if not isinstance(data, dict):
                raise Malformed()
            return data

    def list_messages(self, limit: int, page_token: str | None) -> dict[str, Any]:
        """``GET /v0/inboxes/{inbox}/messages`` with only ``limit`` and ``page_token``."""
        params: dict[str, str] = {"limit": str(int(limit))}
        if page_token is not None:
            if not PAGE_TOKEN_RE.fullmatch(page_token):
                raise PolicyError()
            params["page_token"] = page_token
        return self._get_json(f"{self._inbox_path()}?{urlencode(params)}", self._s.limits.list_response_max_bytes)

    def get_message(self, message_id: str) -> dict[str, Any]:
        """``GET /v0/inboxes/{inbox}/messages/{id}``; the id must come from this inbox's list."""
        if not isinstance(message_id, str) or not MESSAGE_ID_RE.fullmatch(message_id) or ".." in message_id:
            raise PolicyError()
        url = f"{self._inbox_path()}/{quote(message_id, safe='')}"
        return self._get_json(url, self._s.limits.get_response_max_bytes)

    def complete(self, messages: list[dict[str, str]]) -> str:
        """One chat-completions call with no tools; returns the assistant text."""
        limits = self._s.limits
        if self._budget.model_calls >= self._budget.model_calls_max:
            raise BudgetExceeded()
        url = self._s.model_url
        self._guard_url(url, MODEL_HOSTS)
        key = self._secrets(self._s.model_key_env)
        if not key or any(c.isspace() for c in key):
            raise AuthError()
        self._budget.check_time(2.0)
        self._budget.model_calls += 1
        payload = {
            "model": self._s.model, "messages": messages, "temperature": 0.2, "stream": False,
            "max_tokens": limits.model_max_output_tokens, "response_format": {"type": "json_object"},
        }
        started = self._budget.clock()
        resp = self._backend.send(
            "POST", url, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            min(limits.model_timeout_s, max(self._budget.remaining(), 0.1)), limits.model_response_max_bytes,
            remaining=self._budget.remaining)
        self._budget.events.append({"op": "model_post", "status": resp.status, "bytes": len(resp.body),
                                    "ms": int((self._budget.clock() - started) * 1000)})
        if resp.status in (401, 403):
            raise AuthError()
        if resp.status != 200:
            raise Unavailable()
        try:
            data = json.loads(resp.body.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise Malformed() from exc
        if not isinstance(content, str):
            raise Malformed()
        return content


def _retry_after(value: str | None, cap: float) -> float | None:
    """Seconds to wait from a Retry-After header, or None when absent/over the cap."""
    if value is None:
        return min(1.0, cap) if cap >= 1.0 else None
    try:
        wait = float(value)
    except ValueError:
        return None
    if wait < 0 or wait > cap:
        return None
    return wait
