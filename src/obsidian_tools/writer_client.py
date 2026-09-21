"""Async client for the obsidian-writer service.

A thin wrapper that maps the eight tool names to writer endpoints and
returns the response as a string (which becomes the tool message body
in the chat completion loop).

The writer enforces all safety rules (path traversal, reserved entries,
rate limits). The plugin just translates tool calls to HTTP.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .tools import is_obsidian_tool

log = logging.getLogger("obsidian_tools.writer_client")


class WriterClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatch a tool call to the writer and return a JSON-encoded string.

        The string is what we feed back as a `tool` message in the chat
        completion loop. Errors are returned as `{"error": "..."}` so the
        model can react to them in the next iteration.
        """
        if not is_obsidian_tool(name):
            return json.dumps({"error": f"unknown tool: {name}"})

        try:
            match name:
                case "obsidian_search":
                    result = await self._get(
                        "/search",
                        {"q": arguments["q"], "limit": arguments.get("limit", 20)},
                    )
                case "obsidian_read":
                    result = await self._get("/note", {"path": arguments["path"]})
                case "obsidian_list":
                    result = await self._get("/list", {"path": arguments.get("path", "")})
                case "obsidian_create":
                    result = await self._post("/create", arguments)
                case "obsidian_append":
                    result = await self._post("/append", arguments)
                case "obsidian_patch_frontmatter":
                    result = await self._patch("/frontmatter", arguments)
                case "obsidian_map":
                    result = await self._map_action(arguments)
                case "obsidian_propose_delete":
                    result = await self._post(
                        "/trash",
                        {"path": arguments["path"], "reason": arguments.get("reason", "")},
                    )
                case _:
                    return json.dumps({"error": f"unhandled tool: {name}"})  # pragma: no cover
        except httpx.HTTPStatusError as exc:
            log.warning("writer call %s failed: %s", name, exc)
            return json.dumps({"error": str(exc), "status": exc.response.status_code})
        except httpx.HTTPError as exc:
            log.warning("writer call %s transport error: %s", name, exc)
            return json.dumps({"error": f"transport error: {exc}"})

        return json.dumps(result, default=str)

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.post(path, json=body)
        r.raise_for_status()
        return r.json()

    async def _patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.patch(path, json=body)
        r.raise_for_status()
        return r.json()

    async def _map_action(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = arguments.get("action", "get")
        if action == "get":
            return await self._get("/map", {})
        if action == "patch":
            return await self._patch("/map", {"patch": arguments.get("patch", {})})
        return {"error": f"unknown map action: {action}"}
