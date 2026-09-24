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


def _recording_client(captured: list[httpx.Request], reply: dict[str, object]) -> WriterClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=reply)

    transport = httpx.MockTransport(handler)
    c = WriterClient(base_url="http://writer.test", token="tok", recall_url="http://index.test")
    c._client = httpx.AsyncClient(  # noqa: SLF001
        base_url="http://writer.test", headers={"Authorization": "Bearer tok"}, transport=transport
    )
    c._recall = httpx.AsyncClient(  # noqa: SLF001
        base_url="http://index.test", headers={"Authorization": "Bearer tok"}, transport=transport
    )
    return c


@pytest.mark.asyncio
async def test_recall_goes_to_the_index() -> None:
    seen: list[httpx.Request] = []
    c = _recording_client(seen, {"query": "q", "results": []})
    try:
        await c.call_tool("obsidian_recall", {"q": "heat pump", "k": 3, "invented": 1})
    finally:
        await c.aclose()
    assert seen[0].url.host == "index.test"
    assert seen[0].url.path == "/recall"
    assert dict(seen[0].url.params) == {"q": "heat pump", "k": "3"}


@pytest.mark.asyncio
async def test_recall_without_an_index_reports_it() -> None:
    c = WriterClient(base_url="http://writer.test", token="tok")
    try:
        out = json.loads(await c.call_tool("obsidian_recall", {"q": "x"}))
    finally:
        await c.aclose()
    assert "ATHENAEUM_URL" in out["error"]


@pytest.mark.asyncio
async def test_writes_name_the_caller_and_drop_invented_arguments() -> None:
    seen: list[httpx.Request] = []
    c = _recording_client(seen, {"kind": "updated", "path": "Core/Preferences.md"})
    try:
        await c.call_tool(
            "obsidian_write_section",
            {"path": "Core/Preferences.md", "heading": "Dev", "content": "- x", "mode": "append",
             "confidence": 0.9},
            actor="lobehub",
        )
        await c.call_tool(
            "obsidian_edit", {"path": "Core/Preferences.md", "old": "a", "new": "b"}, actor="n8n"
        )
    finally:
        await c.aclose()
    section, edit = seen
    assert (section.method, section.url.path) == ("PUT", "/section")
    assert json.loads(section.content) == {
        "path": "Core/Preferences.md", "heading": "Dev", "content": "- x", "mode": "append"
    }
    assert section.headers["X-Obsidian-Actor"] == "lobehub"
    assert (edit.method, edit.url.path) == ("POST", "/edit")
    assert edit.headers["X-Obsidian-Actor"] == "n8n"


@pytest.mark.asyncio
async def test_history_is_a_read() -> None:
    seen: list[httpx.Request] = []
    c = _recording_client(seen, {"path": None, "entries": []})
    try:
        await c.call_tool("obsidian_history", {"path": "Core/Values.md", "limit": 5}, actor="x")
    finally:
        await c.aclose()
    assert (seen[0].method, seen[0].url.path) == ("GET", "/history")
    assert dict(seen[0].url.params) == {"path": "Core/Values.md", "limit": "5"}
    assert "X-Obsidian-Actor" not in seen[0].headers


@pytest.mark.asyncio
async def test_whole_line_delete_is_forwarded_with_an_empty_new() -> None:
    seen: list[httpx.Request] = []
    c = _recording_client(seen, {"kind": "updated", "path": "Inbox/Memory Review.md"})
    try:
        await c.call_tool(
            "obsidian_edit",
            {"path": "Inbox/Memory Review.md", "old": "^lh-mem-a1", "new": "", "whole_line": True},
        )
    finally:
        await c.aclose()
    assert json.loads(seen[0].content) == {
        "path": "Inbox/Memory Review.md",
        "old": "^lh-mem-a1",
        "new": "",
        "whole_line": True,
    }


@pytest.mark.asyncio
async def test_write_section_appends_unless_replace_is_asked_for() -> None:
    seen: list[httpx.Request] = []
    c = _recording_client(seen, {"kind": "updated", "path": "Areas/Home/Homelab.md"})
    try:
        await c.call_tool(
            "obsidian_write_section",
            {"path": "Areas/Home/Homelab.md", "heading": "Current state", "content": "- x"},
        )
        await c.call_tool(
            "obsidian_write_section",
            {"path": "Areas/Home/Homelab.md", "heading": "Current state", "content": "- y",
             "mode": "replace"},
        )
    finally:
        await c.aclose()
    assert [json.loads(r.content)["mode"] for r in seen] == ["append", "replace"]
