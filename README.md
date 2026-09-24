# obsidian-litellm-tools

An Obsidian vault as a server-side tool pack for a
[LiteLLM proxy](https://github.com/BerriAI/litellm). Any client that talks to
the proxy — a chat UI, Home Assistant, n8n, curl — can read and write the vault
without implementing tool calling: the model calls `obsidian_recall`,
`obsidian_read`, `obsidian_edit`, and the proxy executes them against a
companion [obsidian-writer](https://github.com/max-scopp/obsidian-writer)
service before returning one ordinary answer.

The loop that does that — inject, intercept, execute, re-ask, and hold back a
*streamed* tool call so it never reaches a client that cannot resolve it — is
[litellm-toolbelt](https://github.com/max-scopp/litellm-toolbelt)'s
`ToolPackHook`. This repo is the vault half: the tools, the prompt, and the
writer client. `pack.py` is the whole contract.

## The chain

| Piece | Repo | Role |
|---|---|---|
| Tool pack | this repo | The `obsidian_*` tools, the vault prompt, the writer client |
| Proxy hook | [litellm-toolbelt](https://github.com/max-scopp/litellm-toolbelt) | Server-side tool execution, streaming included |
| Vault API | [obsidian-writer](https://github.com/max-scopp/obsidian-writer) | The only thing that writes the vault: tokens, rate limits, atomic writes, history |
| Recall index | [obsidian-recall](https://github.com/max-scopp/obsidian-recall) | Search by meaning behind `obsidian_recall` (optional) |
| Vault | — | Plain Markdown on a filesystem, edited by hand in Obsidian too |

See [WORKFLOW.md](WORKFLOW.md) for how the pieces sit together in a running
deployment, and what "search" does and does not mean here.

## What this pack does

- **Registers 14 tools** on every chat completion: `obsidian_recall` (search by
  meaning), `obsidian_search`, `obsidian_read`, `obsidian_list`,
  `obsidian_create`, `obsidian_append`, `obsidian_edit` and
  `obsidian_write_section` (edit in place), `obsidian_patch_frontmatter`,
  `obsidian_read_canvas` and `obsidian_write_canvas`, `obsidian_map`,
  `obsidian_propose_delete`, `obsidian_history`.
- **Tells the model what the vault already says.** The system prompt gains the
  vault's rules and its core notes about the user (folders whose `kind` is
  `core` in the map), cached for five minutes — so every client knows the user
  without a tool call. It also teaches the one rule that keeps memory honest:
  write what the user asked you to remember, and *propose* what you merely
  inferred, as a line in the review note, for the user to decide.
- **Names the caller** on every write (`X-Obsidian-Actor`, from the LiteLLM
  key's alias), so the vault history tells one client's writes from another's.
- **Reads and updates `.obsidian-map.yaml`**, the agent's own knowledge of the
  vault's layout, so no folder schema has to be hard-coded.

## What this pack deliberately does NOT do

- **It is not the data layer.** The vault lives on a real filesystem behind
  `obsidian-writer`; this pack is orchestration only.
- **It does not touch the client's own tools.** Tools the client passed through
  are left alone, and a turn mixing them with ours is handed back for the client
  to resolve.
- **It does not cache tool calls.** Every call hits the writer, which is on the
  same network. Only the prompt's vault context is cached.
- **It does not implement soft-delete itself.** `obsidian_propose_delete` is a
  thin wrapper around the writer's `/trash` endpoint.

## Architecture

```
Client ── /v1/chat/completions ──> LiteLLM proxy
                                       │
       ┌───────────────────────────────┘
       │ ToolPackHook.async_pre_call_hook
       │  ├─ skip structured-output and pinned-tool_choice calls
       │  ├─ inject obsidian_* tools
       │  └─ append ObsidianPack.system_prompt(): rules + core notes (cached)
       ▼
   the model (any provider the proxy routes to)
       │
       │ ToolPackHook post-call / streaming-iterator hook
       │
       │ for each obsidian_* call → ObsidianPack.execute():
       │   GET /recall on athenaeum, or /note | /edit | /section | ... on the writer
       │   append the result as a tool message
       │
       │ loop back through the proxy's router with the tool results
       │ (streaming: the follow-up stream replaces the held tool-call region —
       │  the client never sees an obsidian_* tool call)
       ▼
   final response returned to client
```

## Configuration

```yaml
# config.yaml
litellm_settings:
  callbacks:
    - obsidian_tools.hook:proxy_handler_instance

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

Configuration is read from environment variables at import time, so they must be
set before the proxy loads the callback (`env_file:` in compose does this):

| Variable | Default | Notes |
|---|---|---|
| `OBSIDIAN_WRITER_URL` | `http://127.0.0.1:4040` | Base URL of the writer service |
| `OBSIDIAN_WRITER_TOKEN` | _(required)_ | Bearer token for the writer |
| `ATHENAEUM_URL` | _(unset)_ | The recall index; without it `obsidian_recall` reports itself unconfigured |
| `OBSIDIAN_REVIEW_NOTE` | `Inbox/Memory Review.md` | Where models propose what they inferred |
| `OBSIDIAN_CORE_CONTEXT` | `1` | `0` leaves the vault's core notes out of the prompt |
| `OBSIDIAN_MAX_TOOL_ITERATIONS` | `5` | Per-request cap on loop rounds |
| `OBSIDIAN_FOLLOWUP_RETRIES` | `3` | Retries for a follow-up that died before streaming anything |

Install it into the proxy image with [`Dockerfile.litellm`](Dockerfile.litellm).

## Development

```bash
make install   # editable install (pulls litellm-toolbelt from git)
make test      # unit tests
make lint      # ruff + mypy
```

Tests mock the writer service. They cover the vault half — the pack satisfies
the `ToolPack` contract, injects what it should, dispatches to the writer with
its caller named — while the loop and streaming behaviour is tested in
litellm-toolbelt, where it lives.

## License

MIT
