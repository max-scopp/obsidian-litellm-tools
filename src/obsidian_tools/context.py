"""What every agent should know without asking: the vault's core and rules.

A vault that follows the Athenaeum layout keeps a handful of short notes that
apply to every conversation - who the user is, what they value and prefer,
who matters to them, what is going on. LobeHub injects its own memory into
each of its chats; this is the shared equivalent, and it reaches every client
of the proxy: LobeHub, Home Assistant, n8n, opencode.

Everything comes from the vault map, nothing is hard-coded: the notes are
those in folders whose `kind` is `core` (index notes skipped), and the rules
are the map's `rules`. A note marked `source: reconstruction` or `inferred`
is labelled unverified. The result is cached for a few minutes; when the
vault cannot be reached the chat goes ahead without it.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

log = logging.getLogger("obsidian_tools.context")

DEFAULT_UNVERIFIED = ("reconstruction", "inferred")


class VaultReader(Protocol):
    async def read_map(self) -> dict[str, Any]: ...
    async def list_folder(self, path: str) -> dict[str, Any]: ...
    async def read_note(self, path: str) -> dict[str, Any]: ...


class VaultContext:
    def __init__(
        self,
        reader: VaultReader,
        *,
        ttl: float = 300.0,
        retry_after: float = 60.0,
        max_chars: int = 8000,
    ) -> None:
        self._reader = reader
        self._ttl = ttl
        self._retry_after = retry_after
        self._max_chars = max_chars
        self._text = ""
        self._expires = 0.0

    async def text(self) -> str:
        now = time.monotonic()
        if now < self._expires:
            return self._text
        try:
            self._text = await self._build()
            self._expires = now + self._ttl
        except Exception as exc:
            # Keep serving the last good context, and do not retry on every call.
            log.warning("vault context unavailable: %s", exc)
            self._expires = now + self._retry_after
        return self._text

    async def _build(self) -> str:
        vault_map = await self._reader.read_map()
        folders = vault_map.get("folders") or {}
        unverified = set((vault_map.get("frontmatter") or {}).get("source") or DEFAULT_UNVERIFIED)

        notes: list[str] = []
        for name, spec in folders.items():
            if not isinstance(spec, dict) or spec.get("kind") != "core":
                continue
            listing = await self._reader.list_folder(str(name))
            for summary in listing.get("notes") or []:
                note = await self._reader.read_note(summary["path"])
                front = note.get("frontmatter") or {}
                if front.get("type") == "index":
                    continue
                flag = " (unverified: reconstructed, confirm before relying on it)"
                label = summary["path"] + (flag if front.get("source") in unverified else "")
                notes.append(f"### {label}\n\n{_without_title(note.get('body') or '')}")

        rules = [str(r) for r in vault_map.get("rules") or []]
        parts = []
        if rules:
            parts.append("Vault rules:\n" + "\n".join(f"- {r}" for r in rules))
        if notes:
            parts.append("What the vault's core notes say about the user:\n\n" + "\n\n".join(notes))
        text = "\n\n".join(parts)
        if len(text) > self._max_chars:
            text = text[: self._max_chars].rstrip() + "\n…(truncated; obsidian_read for the rest)"
        return text


def _without_title(body: str) -> str:
    """Drop the `# Title` line - the path already names the note."""
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()
