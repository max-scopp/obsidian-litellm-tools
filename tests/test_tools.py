"""Tests for the tool catalogue."""

from __future__ import annotations

from obsidian_tools.tools import TOOLS, as_tool_list, is_obsidian_tool


def test_all_tools_defined() -> None:
    expected = {
        "obsidian_recall",
        "obsidian_search",
        "obsidian_read",
        "obsidian_list",
        "obsidian_create",
        "obsidian_append",
        "obsidian_edit",
        "obsidian_write_section",
        "obsidian_patch_frontmatter",
        "obsidian_read_canvas",
        "obsidian_write_canvas",
        "obsidian_map",
        "obsidian_propose_delete",
        "obsidian_history",
    }
    assert set(TOOLS.keys()) == expected


def test_each_tool_has_function_name_and_schema() -> None:
    for name, tool in TOOLS.items():
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] == name
        assert isinstance(fn["description"], str) and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)


def test_is_obsidian_tool_recognises_known_names() -> None:
    assert is_obsidian_tool("obsidian_search")
    assert is_obsidian_tool("obsidian_create")


def test_is_obsidian_tool_rejects_unknown() -> None:
    assert not is_obsidian_tool("web_search")
    assert not is_obsidian_tool("")


def test_as_tool_list_returns_list() -> None:
    tools = as_tool_list()
    assert isinstance(tools, list)
    assert len(tools) == len(TOOLS)
