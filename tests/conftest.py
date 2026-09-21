"""Pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSIDIAN_WRITER_URL", "http://writer.test")
    monkeypatch.setenv("OBSIDIAN_WRITER_TOKEN", "writer-token-xyz")
    monkeypatch.setenv("OBSIDIAN_MAX_TOOL_ITERATIONS", "3")
