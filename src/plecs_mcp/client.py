"""Minimal JSON-RPC 2.0 client for the PLECS Standalone RPC server."""

from __future__ import annotations

import threading
from typing import Any

import httpx

from .config import load_config


class PlecsError(RuntimeError):
    """Base class for PLECS RPC failures."""


class PlecsUnreachable(PlecsError):
    """The RPC endpoint is not listening or refused the connection."""


class PlecsRpcError(PlecsError):
    """PLECS answered with a JSON-RPC error object."""

    HINTS = {
        -32601: "method not supported by this PLECS version",
        -32602: "invalid method parameters",
        -32500: "method execution error (see message)",
        -32000: "server error (batch/notification are not supported)",
    }

    def __init__(self, method: str, code: int, message: str) -> None:
        self.method = method
        self.code = code
        self.message = message
        hint = self.HINTS.get(code)
        text = f"{method} failed [{code}]: {message}"
        if hint and hint not in message:
            text += f" ({hint})"
        super().__init__(text)


class PlecsClient:
    """Thread-safe client; every RPC call is serialized like the PLECS server itself."""

    def __init__(self, host: str | None = None, port: int | None = None, timeout: float | None = None) -> None:
        cfg = load_config()
        self.host = host or cfg.host
        self.port = int(port or cfg.port)
        self.timeout = float(timeout or cfg.timeout)
        self.source = cfg.source
        self._url = f"http://{self.host}:{self.port}/"
        # PLECS only ever listens on localhost: never route through system/env proxies.
        self._http = httpx.Client(base_url=self._url, trust_env=False)
        self._lock = threading.Lock()
        self._id = 0

    def _timeout(self, seconds: float | None) -> httpx.Timeout:
        read = self.timeout if seconds is None else float(seconds)
        return httpx.Timeout(connect=5.0, read=read, write=30.0, pool=5.0)

    def call(self, method: str, params: list[Any] | None = None, timeout: float | None = None) -> Any:
        """Invoke one RPC method and return its ``result`` field."""
        with self._lock:
            self._id += 1
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or [],
                "id": self._id,
            }
            try:
                response = self._http.post("", json=payload, timeout=self._timeout(timeout))
            except httpx.HTTPError as exc:
                raise PlecsUnreachable(
                    f"cannot reach PLECS at {self._url}: {exc}. "
                    "Is PLECS running with the RPC interface enabled (Preferences > RPC)?"
                ) from exc

        if response.status_code != 200:
            raise PlecsError(f"{method} failed: HTTP {response.status_code}: {response.text[:500]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise PlecsError(f"{method} failed: response is not JSON: {response.text[:500]}") from exc

        error = body.get("error")
        if error:
            raise PlecsRpcError(method, int(error.get("code", 0)), str(error.get("message", "")))
        return body.get("result")

    def close(self) -> None:
        self._http.close()


_client: PlecsClient | None = None
_client_lock = threading.Lock()


def get_client() -> PlecsClient:
    """Process-wide singleton client (shares the call lock across tools)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = PlecsClient()
        return _client


def set_client(client: PlecsClient) -> PlecsClient:
    """Replace the singleton (used by plecs_connect after an explicit handshake)."""
    global _client
    with _client_lock:
        previous, _client = _client, client
    if previous is not None and previous is not client:
        previous.close()
    return client
