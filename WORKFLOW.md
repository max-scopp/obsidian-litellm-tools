# The Obsidian agent workflow

What talks to what, where the data lives, and — the question that matters most
when debugging search — **how the vault is (not) indexed**.

```
Any client (chat UI, Home Assistant, n8n, curl)
   │  POST /v1/chat/completions — streaming or not
   ▼
LiteLLM proxy
   │  litellm-toolbelt's ToolPackHook + this repo's ObsidianPack:
   │  injects the obsidian_* tools and executes their calls server-side
   ▼
obsidian-writer (FastAPI, :4040)
   │  bearer tokens · rate limits · atomic writes · path safety · git history
   ▼
/vault  =  a plain directory, however you mount it (NFS from a NAS here)
   ▼
Obsidian on any device that mounts the share · soft deletes land in .trash/
```

## The stack

| Layer | Repo | Role |
|---|---|---|
| Chat client | — | Anything that speaks the OpenAI API; it needs to know nothing about the vault |
| LLM proxy | [litellm-toolbelt](https://github.com/max-scopp/litellm-toolbelt) | The hook: tool injection, the loop, the streaming translator |
| Tool pack | [obsidian-litellm-tools](https://github.com/max-scopp/obsidian-litellm-tools) | Registers and executes the `obsidian_*` tools |
| Vault API | [obsidian-writer](https://github.com/max-scopp/obsidian-writer) | The only thing that writes the vault |
| Recall index | [athenaeum](https://github.com/max-scopp/athenaeum) | Embeddings + passages behind `obsidian_recall` |
| Vault store | — | Plain Markdown + YAML frontmatter on a filesystem |
| Client app | — | Obsidian; the human edits here directly |

## The tool surface

The pack's tools map onto writer endpoints (plus one on the recall index):

| Tool | Endpoint | Notes |
|---|---|---|
| `obsidian_recall` | `GET /recall` (athenaeum) | search by meaning; reports itself unconfigured without `ATHENAEUM_URL` |
| `obsidian_search` | `GET /search` | substring search — see below |
| `obsidian_read` | `GET /note` | exact vault-relative path, `.md` required |
| `obsidian_list` | `GET /list` | immediate children of a folder |
| `obsidian_create` | `POST /create` | 409 if the path exists — search first |
| `obsidian_append` | `POST /append` | adds a Markdown section |
| `obsidian_edit` | `POST /edit` | replace one exact passage, with an `expect_sha` guard |
| `obsidian_write_section` | `PUT /section` | replace or append the body under a heading |
| `obsidian_patch_frontmatter` | `PATCH /frontmatter` | typed fields only |
| `obsidian_read_canvas` / `obsidian_write_canvas` | `GET`/`PUT /canvas` | JSONCanvas, validated before it is written |
| `obsidian_map` | `GET`/`PATCH /map` | the structure cache (below) |
| `obsidian_propose_delete` | `POST /trash` | soft delete to `.trash/YYYY-MM-DD/` |
| `obsidian_history` | `GET /history` | who changed a note, and what it said before |

Read endpoints need the read token; writes need a write token and are rate
limited (30/min, 200/day per token) with a 256 KiB body cap.

## How it is indexed — it isn't

`obsidian-writer` has **no index**: no SQLite, no FTS, no daemon, no background
crawler. It is deliberately request/response only.

- **Search is a live linear scan.** `GET /search` walks `vault_root.rglob("*.md")`
  on every request and case-insensitively substring-matches the query against
  the vault-relative path *and* the full note text. The first `limit` matches
  (default 20) win. Reserved top-level entries (`.obsidian`, `.trash`, …) are
  skipped. Cost is O(vault size) per call — fine for a personal vault; if it
  ever isn't, replace the scan with SQLite FTS5 and keep the response shape.
- **Search by meaning is a separate service.** `obsidian_recall` goes to
  athenaeum, which holds the embeddings and returns passages with their note
  paths. It is optional: without `ATHENAEUM_URL` the tool says so rather than
  failing the turn.
- **What *is* persisted here is the structure map.** `.obsidian-map.yaml` at the
  vault root is the agent's learned knowledge of the layout: per folder a
  `kind` (inbox | journal | reference | project | area | resource | core |
  trash | unknown), one-sentence `purpose`, `writable`, `examples`, a
  `confidence` that grows with use, and `last_updated`; plus free-form `rules`
  invariants and `aliases`. Seeded with `INITIAL_MAP` defaults (Inbox → unfiled
  notes, Daily → time-anchored entries) on first use; after that it is
  agent-owned and updated through `obsidian_map` PATCH (folders deep-merge per
  entry, `rules` replace wholesale). **No fixed folder schema is enforced** —
  the agent learns your structure as it changes.
- **Note metadata lives in the notes.** `obsidian_create` writes frontmatter
  server-side (title, tags, created, modified, `source: chat`, conversation
  trace id). That is the only "metadata index", and it travels with the file.

The practical consequence: "search before create to avoid duplicates" is in the
tool descriptions because the vault cannot enforce uniqueness beyond the
per-path 409.

## Storage & sync semantics

- All writers converge on one mount, so there is no sync step: Obsidian and the
  agent see the same bytes. **There is no Obsidian plugin involved.**
- Every write goes through `atomic_write()`: `path.tmp` → `fsync(2)` →
  `rename(2)`, atomic even over NFS-on-ZFS. Stale `*.tmp.*` files (>24 h) are
  swept on writer start.
- `safe_resolve()` rejects any requested path that resolves outside the vault
  root; reserved top-level names are unwriteable.
- Deletes never destroy: the note moves to `.trash/YYYY-MM-DD/<basename>` with
  a `meta.md` sidecar; the user bulk-deletes from Obsidian.
- History is a git repo *outside* the vault, so no `.git` syncs to devices.
  Each write is committed as its client; a hand edit found in the same paths is
  committed first as `obsidian`, so the human's changes are never miscredited.

## Operating it

```bash
# Ship pack changes to the proxy host, then rebuild — restart does NOT pick up
# a new image:
docker build -f Dockerfile.litellm -t litellm-with-obsidian:local .
docker compose up -d --force-recreate litellm

# Smoke test both response modes against a model that tool-calls reliably:
curl -s localhost:4000/v1/chat/completions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<model>","messages":[{"role":"user","content":"what do my notes say about X?"}]}'
# then the same with "stream": true
```

Failure forensics: a client that records the tool calls it saw is the fastest
way to catch a leak. In LobeHub that is the `message_plugins` table — a row with
`state: {"type":"blocked","reason":"tool_name_unresolved"}` means a tool call
got past the hook to the client, which is exactly what the streaming translator
exists to prevent.
