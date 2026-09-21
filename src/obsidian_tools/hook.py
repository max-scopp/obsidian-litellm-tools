"""The LiteLLM CustomLogger that wires the obsidian_* tools into every chat.

Two hooks are involved:

1. `async_pre_call_hook` runs on the way *into* the LLM call. We:
   - Inject our 8 tool definitions into `data["tools"]`, merging with any
     tools the client already passed (non-obsidian tools pass through
     unchanged).
   - Inject a short system prompt that reminds the model about the vault
     context (only on the first iteration; we use a marker message).

2. `async_post_call_success_hook` runs after the LLM responds. We:
   - Inspect the response for `tool_calls` whose `function.name` is in
     our namespace.
   - For each one, call the writer via `WriterClient`.
   - Append synthetic `tool` messages to the conversation and re-call
     the LLM until the model produces a final answer (no tool calls)
     or we hit `OBSIDIAN_MAX_TOOL_ITERATIONS`.

The hook is registered in `config.yaml` via:

    litellm_settings:
      callbacks:
        - obsidian_tools.hook:ObsidianToolHook

Configuration is read from environment variables at construction time.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

from .tools import as_tool_list, is_obsidian_tool
from .writer_client import WriterClient

log = logging.getLogger("obsidian_tools.hook")

# The marker we add to a single system message so subsequent iterations
# of the loop don't keep prepending a fresh "vault context" reminder.
SYSTEM_PROMPT_MARKER = "<!-- obsidian-tools: vault tools available -->"

SYSTEM_PROMPT_FRAGMENT = (
    "\n\nYou have access to the user's Obsidian vault via the obsidian_* tool "
    "set. Use these tools whenever the answer involves their notes, projects, "
    "or journal. Before creating a new note, search to avoid duplicates. "
    "Before writing, read the agent's structure map (.obsidian-map.yaml) "
    "if you are unsure where a note belongs.\n"
    f"{SYSTEM_PROMPT_MARKER}\n"
)


class ObsidianToolHook(CustomLogger):
    """LiteLLM callback that injects and dispatches the obsidian_* tools."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.writer = WriterClient(
            base_url=os.environ.get("OBSIDIAN_WRITER_URL", "http://127.0.0.1:4040"),
            token=os.environ.get("OBSIDIAN_WRITER_TOKEN", ""),
        )
        self.max_iterations = int(
            os.environ.get("OBSIDIAN_MAX_TOOL_ITERATIONS", "5")
        )
        if not self.writer._token:  # noqa: SLF001 — peer access for early validation
            log.warning(
                "OBSIDIAN_WRITER_TOKEN is unset; obsidian_* tools will fail at runtime"
            )

    async def async_pre_call_hook(
        self,
        user_api_key_dict: Any,
        cache: Any,
        data: dict[str, Any],
        call_type: str,
    ) -> dict[str, Any] | None:
        """Inject our tools + system prompt fragment before the LLM call."""
        if call_type != "acompletion":
            return None

        # 1. Tools: merge our 8 with whatever the client supplied.
        existing: list[dict[str, Any]] = list(data.get("tools") or [])
        client_obsidian = {
            t.get("function", {}).get("name")
            for t in existing
            if isinstance(t, dict)
        }
        merged = list(existing)
        for tool in as_tool_list():
            name = tool["function"]["name"]
            if name not in client_obsidian:
                merged.append(tool)
        data["tools"] = merged

        # 2. System prompt fragment: append to the first system message,
        #    or insert one if none exists. The marker prevents us from
        #    re-adding the fragment on each loop iteration.
        messages: list[dict[str, Any]] = list(data.get("messages") or [])
        if not any(_has_marker(m) for m in messages):
            for m in messages:
                if m.get("role") == "system":
                    m["content"] = (m.get("content") or "") + SYSTEM_PROMPT_FRAGMENT
                    break
            else:
                messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT_FRAGMENT})
        data["messages"] = messages

        return data

    async def async_post_call_success_hook(
        self,
        data: dict[str, Any],
        user_api_key_dict: Any,
        response: Any,
    ) -> Any:
        """If the model asked for obsidian_* tool calls, execute them and loop.

        Otherwise, return the response unchanged.
        """
        try:
            choices = getattr(response, "choices", None) or []
            if not choices:
                return response

            # Only the first choice drives the loop for now; multi-choice
            # loops are an obvious extension but not required for the
            # primary use case (single-stream chat in LobeHub etc.).
            choice = choices[0]
            message = getattr(choice, "message", None)
            tool_calls = getattr(message, "tool_calls", None) or []
            obsidian_calls = [tc for tc in tool_calls if _is_obsidian_call(tc)]
            if not obsidian_calls:
                return response

            # Execute every obsidian_* tool call in order, build tool
            # result messages, append them to the conversation, and call
            # the model again.
            await self._execute_and_continue(
                data=data,
                user_api_key_dict=user_api_key_dict,
                original_response=response,
                obsidian_calls=obsidian_calls,
            )

            # Return whatever the final loop iteration produced.
            return self._loop_state[data["_obsidian_call_id"]]["final_response"]
        except Exception:
            log.exception("obsidian hook post-call failed")
            return response

    async def _execute_and_continue(
        self,
        *,
        data: dict[str, Any],
        user_api_key_dict: Any,
        original_response: Any,
        obsidian_calls: list[Any],
    ) -> None:
        """Run the agent loop, mutating `self._loop_state[call_id]`."""
        import litellm

        call_id = f"{id(data)}"
        self._loop_state[call_id] = {"final_response": original_response}
        try:
            messages: list[dict[str, Any]] = list(data.get("messages") or [])
            model = data.get("model")
            tools = data.get("tools")
            tool_choice = data.get("tool_choice", "auto")

            # Convert the model's assistant message (with tool_calls) to a
            # plain dict so we can append it and the corresponding tool
            # result messages to the next call.
            assistant_msg = _assistant_message_from_response(original_response)
            if assistant_msg:
                messages.append(assistant_msg)

            for iteration in range(self.max_iterations):
                log.debug(
                    "obsidian loop iteration %d, %d messages so far",
                    iteration,
                    len(messages),
                )
                # Build tool result messages for every obsidian call.
                for tc in obsidian_calls:
                    fn = tc.function
                    name = fn.name
                    try:
                        args = json.loads(fn.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = await self.writer.call_tool(name, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )

                # Re-call the model with the updated messages.
                kwargs = {
                    "model": model,
                    "messages": messages,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice
                # Pass through other relevant kwargs.
                for key in (
                    "temperature",
                    "top_p",
                    "max_tokens",
                    "stream",
                    "stop",
                    "user",
                    "api_base",
                    "api_key",
                ):
                    if key in data and data[key] is not None:
                        kwargs[key] = data[key]

                next_response = await litellm.acompletion(**kwargs)
                next_choices = getattr(next_response, "choices", None) or []
                if not next_choices:
                    self._loop_state[call_id]["final_response"] = next_response
                    return

                next_message = getattr(next_choices[0], "message", None)
                next_tool_calls = getattr(next_message, "tool_calls", None) or []
                obsidian_calls = [
                    tc for tc in next_tool_calls if _is_obsidian_call(tc)
                ]
                if not obsidian_calls:
                    # Model produced a final answer.
                    self._loop_state[call_id]["final_response"] = next_response
                    return

                # Append the assistant's tool-call message and continue.
                assistant_msg = _assistant_message_from_response(next_response)
                if assistant_msg:
                    messages.append(assistant_msg)

            # Hit the iteration cap — return whatever the last response was.
            log.warning(
                "obsidian loop hit max_iterations=%d; returning last response",
                self.max_iterations,
            )
            self._loop_state[call_id]["final_response"] = next_response
        finally:
            data["_obsidian_call_id"] = call_id

    # In-memory scratch space for the loop's final response. This is fine
    # for a single-process proxy; for multi-worker scale-out, move to Redis.
    _loop_state: dict[str, Any] = {}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _is_obsidian_call(tc: Any) -> bool:
    fn = getattr(tc, "function", None)
    name = getattr(fn, "name", None) if fn else None
    return bool(name) and is_obsidian_tool(name)


def _has_marker(message: dict[str, Any]) -> bool:
    content = message.get("content") or ""
    return SYSTEM_PROMPT_MARKER in content


def _assistant_message_from_response(response: Any) -> dict[str, Any] | None:
    """Build an `assistant` message dict from a chat completion response.

    Includes `tool_calls` (if any) so subsequent iterations preserve the
    model's intent.
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    if message is None:
        return None
    msg: dict[str, Any] = {"role": "assistant"}
    content = getattr(message, "content", None)
    if content:
        msg["content"] = content
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in tool_calls
        ]
    return msg
