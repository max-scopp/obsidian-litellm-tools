"""The LiteLLM callback that gives every client of the proxy the vault.

All the machinery — injecting the tools, executing the calls the model makes,
holding a streamed tool call back so a client never sees one, re-asking the
model with the results — is `ToolPackHook` from
[litellm-toolbelt](https://github.com/max-scopp/litellm-toolbelt). This module
is the wiring: build the obsidian pack from the environment and hand it over.

Register it in `config.yaml`:

    litellm_settings:
      callbacks:
        - obsidian_tools.hook:proxy_handler_instance

Configuration is read from environment variables at import time:

| Variable | Default | Meaning |
|---|---|---|
| `OBSIDIAN_WRITER_URL` | `http://127.0.0.1:4040` | obsidian-writer base URL |
| `OBSIDIAN_WRITER_TOKEN` | _(required)_ | bearer token for the writer |
| `ATHENAEUM_URL` | _(unset)_ | passage recall service, if you run one |
| `OBSIDIAN_REVIEW_NOTE` | `Inbox/Memory Review.md` | where inferred facts are proposed |
| `OBSIDIAN_CORE_CONTEXT` | `1` | `0` leaves the vault's core notes out of the prompt |
| `OBSIDIAN_MAX_TOOL_ITERATIONS` | `5` | per-request cap on loop rounds |
| `OBSIDIAN_FOLLOWUP_RETRIES` | `3` | retries for a follow-up that died before streaming |
"""

from __future__ import annotations

import os

from litellm_toolbelt import ToolPackHook, caller_name

from .pack import SYSTEM_PROMPT_MARKER, ObsidianPack, system_fragment

__all__ = [
    "SYSTEM_PROMPT_MARKER",
    "ObsidianToolHook",
    "caller_name",
    "proxy_handler_instance",
    "system_fragment",
]


class ObsidianToolHook(ToolPackHook):
    """`ToolPackHook` carrying the obsidian pack, configured from the environment."""

    def __init__(self, pack: ObsidianPack | None = None) -> None:
        super().__init__(
            pack or ObsidianPack.from_env(),
            max_iterations=int(os.environ.get("OBSIDIAN_MAX_TOOL_ITERATIONS", "5")),
            followup_retries=int(os.environ.get("OBSIDIAN_FOLLOWUP_RETRIES", "3")),
            marker=SYSTEM_PROMPT_MARKER,
        )


# Module-level singleton. LiteLLM 1.101+ requires a proxy_handler_instance
# reference, not a class — see the litellm callback loading contract.
proxy_handler_instance = ObsidianToolHook()
