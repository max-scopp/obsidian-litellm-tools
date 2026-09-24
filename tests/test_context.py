"""The vault context: core notes and rules, built from the map, cached."""

from __future__ import annotations

from typing import Any

import pytest

from obsidian_tools.context import VaultContext
from obsidian_tools.hook import ObsidianToolHook, caller_name, system_fragment

MAP = {
    "folders": {
        "Core": {"kind": "core", "rank": "high"},
        "Memory": {"kind": "memory"},
    },
    "rules": ["Update the canonical note; never create a second note on the same subject"],
    "frontmatter": {"source": ["reconstruction", "inferred"]},
}

NOTES = {
    "Core/About.md": {"frontmatter": {"type": "index"}, "body": "# Core\n\nWhat this is."},
    "Core/Preferences.md": {
        "frontmatter": {"type": "core", "source": "reconstruction"},
        "body": "# Preferences\n\n## Development\n\n- pnpm",
    },
    "Core/Identity.md": {"frontmatter": {"type": "core"}, "body": "# Identity\n\nMax, in Prüm."},
}


class FakeReader:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def read_map(self) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("writer down")
        return MAP

    async def list_folder(self, path: str) -> dict[str, Any]:
        return {"notes": [{"path": p} for p in NOTES if p.startswith(path + "/")]}

    async def read_note(self, path: str) -> dict[str, Any]:
        return NOTES[path]


@pytest.mark.asyncio
async def test_context_holds_rules_and_core_notes_but_not_index_notes() -> None:
    text = await VaultContext(FakeReader()).text()
    assert "Vault rules:\n- Update the canonical note" in text
    assert "### Core/Identity.md\n\nMax, in Prüm." in text
    assert "What this is." not in text  # Core/About.md is an index note
    assert "# Identity" not in text  # the title line is dropped


@pytest.mark.asyncio
async def test_unverified_core_notes_are_labelled() -> None:
    text = await VaultContext(FakeReader()).text()
    assert "### Core/Preferences.md (unverified" in text


@pytest.mark.asyncio
async def test_context_is_cached_and_survives_an_outage() -> None:
    reader = FakeReader()
    ctx = VaultContext(reader, ttl=0, retry_after=0)
    first = await ctx.text()
    reader.fail = True
    assert await ctx.text() == first  # last good context, not an empty one
    assert reader.calls == 2

    cached = VaultContext(FakeReader(), ttl=300)
    await cached.text()
    await cached.text()


@pytest.mark.asyncio
async def test_context_is_truncated_to_its_budget() -> None:
    text = await VaultContext(FakeReader(), max_chars=40).text()
    assert text.endswith("…(truncated; obsidian_read for the rest)")


@pytest.mark.asyncio
async def test_pre_call_carries_the_vault_context(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = ObsidianToolHook()
    hook.pack.context = VaultContext(FakeReader())
    data: dict[str, Any] = {"messages": [{"role": "system", "content": "You are Vector."}]}
    out = await hook.async_pre_call_hook(None, None, data, "acompletion")
    content = out["messages"][0]["content"]
    assert content.startswith("You are Vector.\n\n## The vault")
    assert "Max, in Prüm." in content
    assert content.rstrip().endswith("<!-- obsidian-tools: vault tools available -->")


def test_fragment_teaches_asked_written_inferred_proposed() -> None:
    fragment = system_fragment("Inbox/Memory Review.md")
    assert "obsidian_recall" in fragment
    assert "Inbox/Memory Review.md" in fragment
    assert "- [ ] <the fact> → [[<target note>]]" in fragment


class _Key:
    def __init__(self, **kw: Any) -> None:
        self.key_alias = kw.get("key_alias")
        self.team_alias = kw.get("team_alias")
        self.user_id = kw.get("user_id")


def test_caller_name_prefers_the_key_alias() -> None:
    assert caller_name(_Key(key_alias="lobehub", user_id="u1")) == "lobehub"
    assert caller_name(_Key(team_alias="home", user_id="u1")) == "home"
    assert caller_name(_Key(user_id="default_user_id")) is None
    assert caller_name(None) is None
