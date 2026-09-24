"""The obsidian tool pack: what the tools are, and what running one means.

This is the whole obsidian-specific half of the plugin. The loop that executes
a tool call, holds back a streamed one and re-asks the model lives in
[litellm-toolbelt](https://github.com/max-scopp/litellm-toolbelt); what a call
*does* lives here and in `writer_client`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .context import VaultContext
from .tools import as_tool_list, is_obsidian_tool
from .writer_client import WriterClient

log = logging.getLogger("obsidian_tools.pack")

# The marker the hook adds to a single system message so the loop's own
# follow-ups don't keep prepending a fresh vault context.
SYSTEM_PROMPT_MARKER = "<!-- obsidian-tools: vault tools available -->"

DEFAULT_REVIEW_NOTE = "Inbox/Memory Review.md"


def system_fragment(review_note: str, vault_context: str = "") -> str:
    """The system prompt addition: how to treat the vault, then what it says.

    The rule it teaches is "asked -> written, inferred -> proposed": the user
    decides what becomes long-term memory, so a model writes a canonical note
    only on the user's word and files everything it merely inferred in the
    review note for the user to accept or reject.
    """
    lines = [
        "",
        "",
        "## The vault",
        "The user's Obsidian vault is the long-term memory shared by all of their "
        "agents. You reach it through the obsidian_* tools.",
        "- Recall first: when an answer may depend on what the user noted, decided "
        "or prefers, call obsidian_recall and cite the note path. Say so when a "
        "passage is unverified.",
        "- Write only what the user asked you to remember or clearly confirmed, and "
        "write it into the canonical note: find it with obsidian_recall, then update "
        "it in place (obsidian_edit, obsidian_write_section). Create a note only when "
        "none exists, and never store credentials.",
        "- Something you merely inferred is a proposal, not a memory: add it with "
        f"obsidian_write_section (mode append, heading \"Proposed\") to {review_note} "
        "as one line: `- [ ] <the fact> → [[<target note>]]`. The user reviews it there.",
    ]
    if vault_context:
        lines += ["", vault_context]
    return "\n".join(lines)


class ObsidianPack:
    """The `obsidian_*` tools, dispatched to the obsidian-writer service."""

    name = "obsidian"

    def __init__(
        self,
        writer: WriterClient,
        *,
        review_note: str = DEFAULT_REVIEW_NOTE,
        context: VaultContext | None = None,
    ) -> None:
        self.writer = writer
        self.review_note = review_note
        # The vault's core notes and rules, read from the vault itself.
        self.context = context

    @classmethod
    def from_env(cls) -> ObsidianPack:
        """Build the pack the way the proxy runs it.

        The env vars MUST be set before this module is imported, which is
        guaranteed when litellm is launched with `env_file: .env`.
        """
        writer = WriterClient(
            base_url=os.environ.get("OBSIDIAN_WRITER_URL", "http://127.0.0.1:4040"),
            token=os.environ.get("OBSIDIAN_WRITER_TOKEN", ""),
            recall_url=os.environ.get("ATHENAEUM_URL") or None,
        )
        if not writer._token:  # noqa: SLF001 — peer access for early validation
            log.warning(
                "OBSIDIAN_WRITER_TOKEN is unset; obsidian_* tools will fail at runtime"
            )
        return cls(
            writer,
            review_note=os.environ.get("OBSIDIAN_REVIEW_NOTE", DEFAULT_REVIEW_NOTE),
            # The core notes and vault rules go into every chat unless turned off.
            context=(
                VaultContext(writer)
                if os.environ.get("OBSIDIAN_CORE_CONTEXT", "1") != "0"
                else None
            ),
        )

    # -- the ToolPack contract ----------------------------------------------

    def tools(self) -> list[dict[str, Any]]:
        return as_tool_list()

    def owns(self, tool_name: str) -> bool:
        return is_obsidian_tool(tool_name)

    async def system_prompt(self) -> str:
        vault_context = await self.context.text() if self.context else ""
        return system_fragment(self.review_note, vault_context)

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        actor: str | None = None,
    ) -> str:
        return await self.writer.call_tool(tool_name, arguments, actor=actor)
