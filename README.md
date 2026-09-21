# obsidian-litellm-tools

A [LiteLLM proxy](https://github.com/BerriAI/litellm) plugin that registers
an `obsidian_*` tool set for AI agents and dispatches tool calls to a
companion [obsidian-writer](https://github.com/max-scopp/obsidian-writer)
service.

The plugin implements server-side tool execution: any client that talks
to the LiteLLM proxy (LobeHub, Home Assistant, curl, anything) gets the
vault read/write tools without knowing about them. The model can call
`obsidian_search`, `obsidian_read`, `obsidian_create`, etc., and the
plugin executes them against `obsidian-writer` before returning the
final response.

## What this plugin does

- **Registers** 8 tools (`obsidian_search`, `obsidian_read`, `obsidian_list`,
  `obsidian_create`, `obsidian_append`, `obsidian_patch_frontmatter`,
  `obsidian_map`, `obsidian_propose_delete`) on every chat completion.
- **Intercepts** the model's tool calls in the `obsidian_*` namespace.
- **Executes** them against the configured `obsidian-writer` URL.
- **Loops** back into the model with the tool results until the model
  produces a final answer (or hits a safety limit).
- **Reads and updates** the agent's `.obsidian-map.yaml` so the agent
  can reason about its own knowledge of the vault's structure.

## What this plugin deliberately does NOT do

- **It is not the data layer.** The vault lives on a real filesystem
  behind `obsidian-writer`; this plugin is pure orchestration.
- **It does not edit the model's `tools` list to add non-obsidian
  tools.** Any other tools the client passes through are left alone.
- **It does not cache.** Every tool call hits the writer. The writer
  is local to the same network; latency is sub-millisecond.
- **It does not implement soft-delete itself.** `obsidian_propose_delete`
  is just a thin wrapper that calls the writer's `/trash` endpoint.

## Architecture

```
Client ── /v1/chat/completions ──> LiteLLM proxy
                                       │
       ┌───────────────────────────────┘
       │ async_pre_call_hook
       │  ├─ read .obsidian-map.yaml (cached)
       │  ├─ inject obsidian_* tools into kwargs
       │  └─ rewrite system prompt with vault context
       ▼
   vLLM / OpenRouter (Qwen3-8B-AWQ, etc.)
       │
       │ response with tool_calls
       ▼
   async_post_call_success_deployment_hook
       │
       │ for each obsidian_* tool call:
       │   POST /search | /create | /append | /trash | ...  to obsidian-writer
       │   build synthetic tool message
       │
       │ if any tool calls were processed:
       │   loop back to LLM with messages += tool results
       │
       ▼
   final response returned to client
```

## Configuration

In your `config.yaml`:

```yaml
litellm_settings:
  callbacks:
    - obsidian_tools.hook:ObsidianToolHook

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

The plugin reads its configuration from environment variables:

| Variable | Default | Notes |
|---|---|---|
| `OBSIDIAN_WRITER_URL` | `http://127.0.0.1:4040` | Base URL of the writer service |
| `OBSIDIAN_WRITER_TOKEN` | _(required)_ | Bearer token for the writer |
| `OBSIDIAN_MAX_TOOL_ITERATIONS` | `5` | Per-request safety limit on the agent loop |

## Development

```bash
make install   # editable install
make test      # unit tests
make lint
```

Tests mock the writer service and exercise the hook in isolation.

## Related

- [`obsidian-writer`](https://github.com/max-scopp/obsidian-writer) —
  the FastAPI service this plugin talks to.
