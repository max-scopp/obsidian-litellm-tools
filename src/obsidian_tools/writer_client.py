"""Async client for the obsidian-writer service and the athenaeum index.

A thin wrapper that maps the tool names to service endpoints and returns
the response as a string (which becomes the tool message body in the chat
completion loop). `obsidian_recall` goes to athenaeum; everything else to
obsidian-writer. Both accept the same token.

The services enforce all safety rules (path traversal, reserved entries,
rate limits). The plugin just translates tool calls to HTTP - and names the
caller it writes for in `X-Obsidian-Actor`, so the vault history can tell
LobeHub's writes from Home Assistant's.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .tools import is_obsidian_tool

log = logging.getLogger("obsidian_tools.writer_client")


class WriterClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        recall_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        self._recall = (
            httpx.AsyncClient(
                base_url=recall_url.rstrip("/"),
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
            if recall_url
            else None
        )

    async def aclose(self) -> None:
        await self._client.aclose()
        if self._recall:
            await self._recall.aclose()

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, actor: str | None = None
    ) -> str:
        """Dispatch a tool call to the writer and return a JSON-encoded string.

        The string is what we feed back as a `tool` message in the chat
        completion loop. Errors are returned as `{"error": "..."}` so the
        model can react to them in the next iteration.
        """
        if not is_obsidian_tool(name):
            return json.dumps({"error": f"unknown tool: {name}"})

        headers = {"X-Obsidian-Actor": actor} if actor else {}
        try:
            match name:
                case "obsidian_recall":
                    result = await self._recall_passages(arguments)
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
                    result = await self._post("/create", arguments, headers)
                case "obsidian_append":
                    result = await self._post("/append", arguments, headers)
                case "obsidian_edit":
                    result = await self._post(
                        "/edit",
                        _pick(arguments, "path", "old", "new", "replace_all", "whole_line"),
                        headers,
                    )
                case "obsidian_write_section":
                    # Append unless the model asked for a rewrite by name: a model
                    # that forgets the mode must not be able to wipe a section.
                    section = _pick(arguments, "path", "heading", "content", "mode", "level")
                    section.setdefault("mode", "append")
                    result = await self._put("/section", section, headers)
                case "obsidian_patch_frontmatter":
                    result = await self._patch("/frontmatter", arguments, headers)
                case "obsidian_read_canvas":
                    result = await self._get("/canvas", {"path": arguments["path"]})
                case "obsidian_write_canvas":
                    result = await self._put(
                        "/canvas",
                        {
                            "path": arguments["path"],
                            "nodes": arguments.get("nodes", []),
                            "edges": arguments.get("edges", []),
                        },
                    )
                case "obsidian_map":
                    result = await self._map_action(arguments, headers)
                case "obsidian_propose_delete":
                    result = await self._post(
                        "/trash",
                        {"path": arguments["path"], "reason": arguments.get("reason", "")},
                        headers,
                    )
                case "obsidian_history":
                    result = await self._get("/history", _pick(arguments, "path", "limit"))
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

    async def _post(
        self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        r = await self._client.post(path, json=body, headers=headers)
        r.raise_for_status()
        return r.json()

    async def _put(
        self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        r = await self._client.put(path, json=body, headers=headers)
        r.raise_for_status()
        return r.json()

    async def _patch(
        self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        r = await self._client.patch(path, json=body, headers=headers)
        r.raise_for_status()
        return r.json()

    async def _map_action(
        self, arguments: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        action = arguments.get("action", "get")
        if action == "get":
            return await self._get("/map", {})
        if action == "patch":
            return await self._patch("/map", {"patch": arguments.get("patch", {})}, headers)
        return {"error": f"unknown map action: {action}"}

    async def _recall_passages(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._recall is None:
            return {"error": "recall is not configured (ATHENAEUM_URL is unset)"}
        r = await self._recall.get("/recall", params=_pick(arguments, "q", "k", "types", "prefix"))
        r.raise_for_status()
        return r.json()

    # -- vault context ---------------------------------------------------------

    async def read_note(self, path: str) -> dict[str, Any]:
        return await self._get("/note", {"path": path})

    async def list_folder(self, path: str) -> dict[str, Any]:
        return await self._get("/list", {"path": path})

    async def read_map(self) -> dict[str, Any]:
        return await self._get("/map", {})


def _pick(arguments: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Forward only the keys a service accepts; models do invent extras."""
    return {k: arguments[k] for k in keys if arguments.get(k) is not None}
