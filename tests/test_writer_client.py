"""Tests for the writer client.

We use httpx's MockTransport to fake the writer service so the tests
stay offline.
"""

from __future__ import annotations

import json

import httpx
import pytest

from obsidian_tools.writer_client import WriterClient


def _client(handler) -> WriterClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    # We override the internal httpx client with a MockTransport-backed one.
    c = WriterClient(base_url="http://writer.test", token="tok")
    c._client = httpx.AsyncClient(  # noqa: SLF001
        base_url="http://writer.test",
        headers={"Authorization": "Bearer tok"},
        transport=transport,
    )
    return c


@pytest.mark.asyncio
async def test_obsidian_search_dispatches() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"matches": [], "total": 0})

    c = _client(handler)
    try:
        out = await c.call_tool("obsidian_search", {"q": "vllm", "limit": 5})
    finally:
        await c.aclose()

    assert captured["path"] == "/search"
    assert captured["params"]["q"] == "vllm"
    assert captured["params"]["limit"] == "5"
    assert json.loads(out) == {"matches": [], "total": 0}


@pytest.mark.asyncio
async def test_obsidian_create_dispatches_post() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"kind": "created", "path": "Inbox/x.md", "sha": "abc"})

    c = _client(handler)
    try:
        out = await c.call_tool(
            "obsidian_create",
            {"path": "Inbox/x.md", "title": "X", "body": "hi", "tags": ["t"]},
        )
    finally:
        await c.aclose()

    assert captured["method"] == "POST"
    assert captured["path"] == "/create"
    assert captured["body"]["path"] == "Inbox/x.md"
    assert json.loads(out)["kind"] == "created"


@pytest.mark.asyncio
async def test_obsidian_map_get_dispatches() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(200, json={"folders": {}, "rules": []})

    c = _client(handler)
    try:
        out = await c.call_tool("obsidian_map", {"action": "get"})
    finally:
        await c.aclose()

    assert captured["method"] == "GET"
    assert captured["path"] == "/map"
    assert json.loads(out) == {"folders": {}, "rules": []}


@pytest.mark.asyncio
async def test_unknown_tool_returns_error() -> None:
    c = _client(lambda req: httpx.Response(200))
    try:
        out = await c.call_tool("not_a_tool", {})
    finally:
        await c.aclose()
    assert "unknown tool" in out


@pytest.mark.asyncio
async def test_writer_http_error_returns_error_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    c = _client(handler)
    try:
        out = await c.call_tool("obsidian_read", {"path": "missing.md"})
    finally:
        await c.aclose()
    body = json.loads(out)
    assert "error" in body
    assert body["status"] == 404
