"""Thin async wrapper around the addy.io REST API (https://app.addy.io/docs/)."""

from __future__ import annotations

import logging
import os
import ssl
from pathlib import Path
from typing import Any

import httpx
import truststore
from mcp.server.mcpserver.exceptions import ToolError

from addy_mcp import __version__

# httpx logs every request URL at INFO, which would put alias searches in the client's log files.
logging.getLogger("httpx").setLevel(logging.WARNING)

DEFAULT_BASE_URL = "https://app.addy.io"
USER_AGENT = f"addy-mcp/{__version__} (+https://github.com/Former-Stranger/addy-mcp)"


class AddyClient:
    """Makes authenticated requests to the addy.io API.

    The API key is read from the file named by ``ADDY_API_KEY_FILE`` if set, otherwise from
    ``ADDY_API_KEY``. ``ADDY_BASE_URL`` only matters for self-hosted instances.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or os.environ.get("ADDY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            api_key = self._api_key or _api_key_from_environment()
            self._http = httpx.AsyncClient(
                base_url=f"{self._base_url}/api/v1",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "User-Agent": USER_AGENT,
                },
                timeout=30.0,
                # Verify TLS against the OS trust store (works behind corporate proxies).
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                transport=self._transport,
            )
        return self._http

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        raw: bool = False,
    ) -> Any:
        """Send a request and return the decoded JSON body.

        Returns ``{"success": True}`` for empty (204) responses and the response text
        when ``raw`` is set. Raises ``ToolError`` with the API's message on failure so
        the model can see what went wrong.
        """
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self._client().request(method, path, params=params or None, json=json)
        except httpx.HTTPError as exc:
            raise ToolError(f"Could not reach addy.io ({self._base_url}): {exc}") from exc

        if response.is_error:
            raise ToolError(_format_error(response))
        if raw:
            return response.text
        if response.status_code == 204 or not response.content:
            return {"success": True}
        try:
            return response.json()
        except ValueError:
            return {"success": True, "body": response.text}

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


def _api_key_from_environment() -> str:
    key_file = os.environ.get("ADDY_API_KEY_FILE")
    if key_file:
        try:
            key = Path(key_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ToolError(f"Could not read ADDY_API_KEY_FILE ({key_file}): {exc.strerror}") from exc
        if not key:
            raise ToolError(f"ADDY_API_KEY_FILE ({key_file}) is empty.")
        return key
    key = os.environ.get("ADDY_API_KEY", "").strip()
    if not key:
        raise ToolError(
            "No API key: set ADDY_API_KEY (or ADDY_API_KEY_FILE) in this MCP server's environment. "
            "Create a key at https://app.addy.io/settings/api"
        )
    return key


_STATUS_HINTS = {
    401: "Unauthenticated - the API key is missing, wrong, or expired",
    403: "Forbidden - your plan or API key does not allow this action",
    404: "Not found - check the id",
    422: "Validation error",
    429: "Too many requests, or you've reached your limit for new aliases",
}


def _format_error(response: httpx.Response) -> str:
    hint = _STATUS_HINTS.get(response.status_code, response.reason_phrase)
    detail = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        parts = []
        if body.get("message"):
            parts.append(str(body["message"]))
        errors = body.get("errors")
        if isinstance(errors, dict):
            for field, messages in errors.items():
                if isinstance(messages, list):
                    messages = "; ".join(str(m) for m in messages)
                parts.append(f"{field}: {messages}")
        elif body.get("error"):
            parts.append(str(body["error"]))
        detail = " | ".join(parts)
    elif response.text:
        detail = response.text[:500]
    message = f"addy.io API error {response.status_code} ({hint})"
    return f"{message}: {detail}" if detail else message
