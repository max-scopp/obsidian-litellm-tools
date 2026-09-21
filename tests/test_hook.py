"""Tests for the LiteLLM hook.

These tests use a fake WriterClient and a fake `litellm.acompletion` so
the loop logic can be exercised in isolation. The transport layer is
not under test here — that's what the writer service has its own tests
for.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from obsidian_tools.hook import ObsidianToolHook
from obsidian_tools.tools import as_tool_list


class _FakeFunction:
    def __init__(self, name: str, arguments: dict[str, Any] | str) -> None:
        self.name = name
        self.arguments = (
            json.dumps(arguments) if isinstance(arguments, dict) else arguments
        )


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: dict[str, Any] | str) -> None:
        self.id = id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]


@pytest.fixture
def hook() -> ObsidianToolHook:
    return ObsidianToolHook()


# ----------------------------------------------------------------------------
# Pre-call hook
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_call_injects_tools_and_system_marker(hook: ObsidianToolHook) -> None:
    data: dict[str, Any] = {
        "messages": [{"role": "user", "content": "hello"}],
        "model": "openrouter/foo",
    }
    out = await hook.async_pre_call_hook(None, None, data, "acompletion")
    assert out is not None
    tool_names = {t["function"]["name"] for t in out["tools"]}
    assert "obsidian_search" in tool_names
    assert "obsidian_create" in tool_names
    # System prompt added with the marker
    sys_msg = out["messages"][0]
    assert sys_msg["role"] == "system"
    assert "<!-- obsidian-tools: vault tools available -->" in sys_msg["content"]


@pytest.mark.asyncio
async def test_pre_call_merges_with_client_tools(hook: ObsidianToolHook) -> None:
    data: dict[str, Any] = {
        "messages": [{"role": "user", "content": "x"}],
        "tools": [
            {
                "type": "function",
                "function": {"name": "web_search", "description": "Search the web"},
            }
        ],
    }
    out = await hook.async_pre_call_hook(None, None, data, "acompletion")
    names = {t["function"]["name"] for t in out["tools"]}
    assert "web_search" in names
    assert "obsidian_search" in names


@pytest.mark.asyncio
async def test_pre_call_appends_to_existing_system_message(
    hook: ObsidianToolHook,
) -> None:
    data: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "x"},
        ],
    }
    out = await hook.async_pre_call_hook(None, None, data, "acompletion")
    sys_msg = out["messages"][0]
    assert sys_msg["content"].startswith("You are helpful.")
    assert "<!-- obsidian-tools: vault tools available -->" in sys_msg["content"]


@pytest.mark.asyncio
async def test_pre_call_does_not_double_marker(hook: ObsidianToolHook) -> None:
    data: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": "<!-- obsidian-tools: vault tools available -->"},
            {"role": "user", "content": "x"},
        ],
    }
    out = await hook.async_pre_call_hook(None, None, data, "acompletion")
    # Only one marker, no duplicate fragment added
    sys_msg = out["messages"][0]
    assert sys_msg["content"].count("<!-- obsidian-tools:") == 1


@pytest.mark.asyncio
async def test_pre_call_skips_non_completion_calls(hook: ObsidianToolHook) -> None:
    data: dict[str, Any] = {"messages": [{"role": "user", "content": "x"}]}
    out = await hook.async_pre_call_hook(None, None, data, "aembedding")
    assert out is None


# ----------------------------------------------------------------------------
# Post-call hook
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_call_returns_unchanged_when_no_tool_calls(
    hook: ObsidianToolHook,
) -> None:
    response = _FakeResponse(_FakeMessage(content="just text"))
    data: dict[str, Any] = {
        "messages": [{"role": "user", "content": "hi"}],
        "model": "openrouter/foo",
        "tools": as_tool_list(),
    }
    out = await hook.async_post_call_success_hook(data, None, response)
    assert out is response


@pytest.mark.asyncio
async def test_post_call_dispatches_obsidian_tool_calls(
    monkeypatch: pytest.MonkeyPatch, hook: ObsidianToolHook
) -> None:
    """The hook should:
       1. See a tool_call for obsidian_search.
       2. Call the writer.
       3. Loop back to the LLM with a tool message.
       4. Return the final response.
    """

    # Fake writer: record the call and return a canned result.
    captured: list[tuple[str, dict[str, Any]]] = []

    async def fake_call_tool(name: str, args: dict[str, Any]) -> str:
        captured.append((name, args))
        return json.dumps({"matches": [], "total": 0})

    monkeypatch.setattr(hook.writer, "call_tool", fake_call_tool)

    # Fake litellm.acompletion: the FIRST internal call (after the writer
    # has run) returns a final answer with no further tool calls.
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs: Any) -> _FakeResponse:
        call_count["n"] += 1
        # Any subsequent call would loop again; in this test we expect
        # exactly one internal re-call before the model is done.
        return _FakeResponse(_FakeMessage(content="Found nothing."))

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    initial_response = _FakeResponse(
        _FakeMessage(
            content=None,
            tool_calls=[
                _FakeToolCall(
                    id="call_1", name="obsidian_search", arguments={"q": "vllm"}
                )
            ],
        )
    )
    data: dict[str, Any] = {
        "messages": [{"role": "user", "content": "find vllm"}],
        "model": "openrouter/foo",
        "tools": as_tool_list(),
    }

    out = await hook.async_post_call_success_hook(data, None, initial_response)

    # The writer was called once with the search.
    assert captured == [("obsidian_search", {"q": "vllm"})]
    # The final response is the (single) fake_acompletion result.
    assert isinstance(out, _FakeResponse)
    assert out.choices[0].message.content == "Found nothing."
    # litellm.acompletion was called exactly once inside the loop.
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_post_call_respects_max_iterations(
    monkeypatch: pytest.MonkeyPatch, hook: ObsidianToolHook
) -> None:
    """If the model keeps calling tools forever, the loop must terminate."""

    async def fake_call_tool(name: str, args: dict[str, Any]) -> str:
        return json.dumps({"ok": True})

    monkeypatch.setattr(hook.writer, "call_tool", fake_call_tool)

    async def always_tool_call(**kwargs: Any) -> _FakeResponse:
        tool_call = _FakeToolCall(
            id=f"call_{kwargs.get('_iter', 0)}",
            name="obsidian_list",
            arguments={},
        )
        return _FakeResponse(_FakeMessage(content=None, tool_calls=[tool_call]))

    import litellm

    monkeypatch.setattr(litellm, "acompletion", always_tool_call)

    initial_response = _FakeResponse(
        _FakeMessage(
            content=None,
            tool_calls=[
                _FakeToolCall(id="call_0", name="obsidian_list", arguments={})
            ],
        )
    )
    data: dict[str, Any] = {
        "messages": [{"role": "user", "content": "loop forever"}],
        "model": "openrouter/foo",
        "tools": as_tool_list(),
    }

    # max_iterations is 3 from the env fixture
    out = await hook.async_post_call_success_hook(data, None, initial_response)

    # Should not raise; should return a response.
    assert out is not None
