"""Tests for the wiring between the obsidian pack and the proxy.

The loop itself — executing a tool call, holding a streamed one back, re-asking
the model, retrying a dead follow-up — belongs to `litellm_toolbelt` and is
tested there. What matters here is that the pack satisfies that contract and
that the proxy ends up with the vault: the right tools, the right prompt, the
env knobs honoured, and a call that reaches the writer with its caller named.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from litellm_toolbelt import ToolPack

from obsidian_tools.hook import ObsidianToolHook
from obsidian_tools.pack import SYSTEM_PROMPT_MARKER, ObsidianPack
from obsidian_tools.tools import TOOLS


class _FakeFunction:
    def __init__(self, name: str, arguments: dict[str, Any] | str) -> None:
        self.name = name
        self.arguments = json.dumps(arguments) if isinstance(arguments, dict) else arguments


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


class _Key:
    def __init__(self, alias: str) -> None:
        self.key_alias = alias


@pytest.fixture
def hook() -> ObsidianToolHook:
    return ObsidianToolHook()


def test_the_pack_satisfies_the_toolpack_contract() -> None:
    assert isinstance(ObsidianPack.from_env(), ToolPack)


def test_the_hook_carries_the_obsidian_pack_and_its_marker(hook: ObsidianToolHook) -> None:
    assert isinstance(hook.pack, ObsidianPack)
    assert hook.marker == SYSTEM_PROMPT_MARKER
    # From the env fixture, not the ToolPackHook defaults.
    assert hook.max_iterations == 3


def test_the_module_level_instance_is_the_one_config_yaml_names() -> None:
    from obsidian_tools.hook import proxy_handler_instance

    assert isinstance(proxy_handler_instance, ObsidianToolHook)


def test_from_env_reads_the_writer_and_the_review_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBSIDIAN_REVIEW_NOTE", "Inbox/Proposals.md")
    pack = ObsidianPack.from_env()

    assert pack.review_note == "Inbox/Proposals.md"
    assert pack.writer._base_url == "http://writer.test"  # noqa: SLF001
    # OBSIDIAN_CORE_CONTEXT=0 in the env fixture.
    assert pack.context is None


def test_core_context_is_on_unless_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OBSIDIAN_CORE_CONTEXT", raising=False)
    assert ObsidianPack.from_env().context is not None


async def test_pre_call_injects_every_obsidian_tool_and_the_vault_prompt(
    hook: ObsidianToolHook,
) -> None:
    data: dict[str, Any] = {"messages": [{"role": "user", "content": "hi"}]}
    out = await hook.async_pre_call_hook(None, None, data, "acompletion")

    assert out is not None
    assert {t["function"]["name"] for t in out["tools"]} == set(TOOLS)
    system = next(m for m in out["messages"] if m["role"] == "system")
    assert "## The vault" in system["content"]
    assert "obsidian_recall" in system["content"]
    assert system["content"].rstrip().endswith(SYSTEM_PROMPT_MARKER)


async def test_pre_call_leaves_a_clients_own_tools_alone(hook: ObsidianToolHook) -> None:
    client_tool = {"type": "function", "function": {"name": "web_search"}}
    data: dict[str, Any] = {"messages": [], "tools": [client_tool]}
    out = await hook.async_pre_call_hook(None, None, data, "acompletion")

    assert out is not None
    assert out["tools"][0] is client_tool
    assert len(out["tools"]) == len(TOOLS) + 1


async def test_a_tool_call_reaches_the_writer_with_its_caller_named(
    monkeypatch: pytest.MonkeyPatch, hook: ObsidianToolHook
) -> None:
    captured: list[tuple[str, dict[str, Any], str | None]] = []

    async def fake_call_tool(
        name: str, args: dict[str, Any], *, actor: str | None = None
    ) -> str:
        captured.append((name, args, actor))
        return json.dumps({"matches": [], "total": 0})

    monkeypatch.setattr(hook.pack.writer, "call_tool", fake_call_tool)

    async def fake_acompletion(**kwargs: Any) -> _FakeResponse:
        return _FakeResponse(_FakeMessage(content="Found nothing."))

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    response = _FakeResponse(
        _FakeMessage(tool_calls=[_FakeToolCall("call_1", "obsidian_search", {"q": "vllm"})])
    )
    data: dict[str, Any] = {"messages": [], "model": "openrouter/foo"}

    out = await hook.async_post_call_success_hook(data, _Key("lobehub"), response)

    assert captured == [("obsidian_search", {"q": "vllm"}, "lobehub")]
    assert out.choices[0].message.content == "Found nothing."


async def test_a_foreign_tool_call_is_left_to_the_client(
    monkeypatch: pytest.MonkeyPatch, hook: ObsidianToolHook
) -> None:
    async def never(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("the writer must not run for a foreign tool call")

    monkeypatch.setattr(hook.pack.writer, "call_tool", never)

    response = _FakeResponse(
        _FakeMessage(tool_calls=[_FakeToolCall("call_1", "web_search", {"q": "x"})])
    )
    data: dict[str, Any] = {"messages": [], "model": "openrouter/foo"}

    assert await hook.async_post_call_success_hook(data, None, response) is response
