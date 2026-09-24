"""The tools exposed by the plugin.

Tool descriptions are the *exact strings* the model reads when deciding
whether to call. They are deliberately concrete: include the rules the
agent needs to follow ("search first", "cannot change reserved fields"),
so the model has the contract in front of it.

The JSON schemas are OpenAI-compatible function-calling format. LiteLLM
forwards them as-is to vLLM and OpenRouter.
"""

from __future__ import annotations

from typing import Any

# All tool definitions, indexed by their canonical name. The keys are the
# function names; the values are the JSON Schema the model sees.
TOOLS: dict[str, dict[str, Any]] = {
    "obsidian_recall": {
        "type": "function",
        "function": {
            "name": "obsidian_recall",
            "description": (
                "Find what the vault knows about a question or topic, by meaning - "
                "not only by name. Use it first whenever an answer may depend on the "
                "user's notes, preferences, people, projects or past decisions, and "
                "before writing, to find the canonical note to update. Returns the "
                "best passages with note path and heading; cite the path. A result "
                "with `unverified: true` comes from a note marked as reconstructed "
                "or inferred - say it is unconfirmed before acting on it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                        "description": "The question or topic, in plain words",
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 8,
                        "description": "How many passages to return",
                    },
                    "types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Only notes of these frontmatter types, e.g. core, memory, "
                            "knowledge, project, area, journal"
                        ),
                    },
                    "prefix": {
                        "type": "string",
                        "maxLength": 256,
                        "description": "Only notes under this folder, e.g. Memory/People/",
                    },
                },
                "required": ["q"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_search": {
        "type": "function",
        "function": {
            "name": "obsidian_search",
            "description": (
                "Search the user's Obsidian vault by title, tag, or path substring - "
                "for a name or exact term you already know. For questions by "
                "meaning, use obsidian_recall. Returns up to 20 matches with "
                "path, title, tags, size, and modified time. The search is case-"
                "insensitive and matches anywhere in the path or note content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "Substring to search for",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20,
                        "description": "Max matches to return",
                    },
                },
                "required": ["q"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_read": {
        "type": "function",
        "function": {
            "name": "obsidian_read",
            "description": (
                "Return the full content of a single note by its vault-relative path "
                "(including the .md extension). Use after obsidian_search to confirm "
                "before reading. Path must be exact; the writer rejects near-misses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Vault-relative path, including .md",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_list": {
        "type": "function",
        "function": {
            "name": "obsidian_list",
            "description": (
                "List the immediate children of a folder: subfolders and notes. Use "
                "to discover the layout of a folder you have not visited before. "
                "Hidden entries (.obsidian, .trash) are filtered out."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "maxLength": 512,
                        "default": "",
                        "description": "Vault-relative folder path; empty for root",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_create": {
        "type": "function",
        "function": {
            "name": "obsidian_create",
            "description": (
                "Create a new note at a vault-relative path - only when no note on "
                "the subject exists yet (obsidian_recall first; update the existing "
                "note instead when there is one). Pass `frontmatter` with the vault's "
                "`type` and `topics`, and `source: inferred` for anything the user "
                "did not confirm; the note is then written in the vault's template "
                "shape. The parent folder is created if needed. Fails with 409 if a "
                "note already exists at the path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": (
                            "Vault-relative path; .md is appended automatically if "
                            "missing"
                        ),
                    },
                    "title": {
                        "type": "string",
                        "maxLength": 200,
                        "description": (
                            "Human-readable title. Defaults to the file's stem if "
                            "omitted"
                        ),
                    },
                    "body": {
                        "type": "string",
                        "maxLength": 262144,
                        "default": "",
                        "description": "Markdown body content (UTF-8).",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 50},
                        "description": (
                            "Tags are lowercased, deduped, and sorted server-side"
                        ),
                    },
                    "frontmatter": {
                        "type": "object",
                        "description": "The vault's frontmatter contract for the new note",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": (
                                    "core, memory, knowledge, project, area, "
                                    "agent-context, journal or index"
                                ),
                            },
                            "scope": {"type": "string", "enum": ["shared", "agent"]},
                            "agent": {"type": "string"},
                            "topics": {"type": "array", "items": {"type": "string"}},
                            "status": {"type": "string"},
                            "source": {
                                "type": "string",
                                "enum": ["reconstruction", "inferred"],
                                "description": "Omit when the user confirmed the content",
                            },
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_append": {
        "type": "function",
        "function": {
            "name": "obsidian_append",
            "description": (
                "Append a Markdown section to an existing note. The note must "
                "already exist (search first if unsure). The new section is "
                "appended at the end of the file with a timestamp heading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Vault-relative path of an existing note",
                    },
                    "heading": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "Section heading text (without leading #)",
                    },
                    "content": {
                        "type": "string",
                        "default": "",
                        "description": "Markdown body for the new section",
                    },
                },
                "required": ["path", "heading"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_edit": {
        "type": "function",
        "function": {
            "name": "obsidian_edit",
            "description": (
                "Correct a note in place: replace one exact passage of its body. Use "
                "it to fix a wrong fact where it stands instead of appending a "
                "correction. `old` must occur exactly once - read the note first and "
                "quote enough surrounding text. To replace or delete a whole line, set "
                "whole_line and give in `old` only a short unique part of that line "
                "(its ^block-id if it has one); an empty `new` deletes the line. The "
                "note's `updated` date is set for you. Frontmatter is edited with "
                "obsidian_patch_frontmatter instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Vault-relative path of an existing note",
                    },
                    "old": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Exact text to replace",
                    },
                    "new": {"type": "string", "description": "Replacement text"},
                    "replace_all": {
                        "type": "boolean",
                        "default": False,
                        "description": "Replace every occurrence instead of exactly one",
                    },
                    "whole_line": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "`old` is a unique fragment of one line; replace that whole "
                            "line with `new`, or delete it when `new` is empty"
                        ),
                    },
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_write_section": {
        "type": "function",
        "function": {
            "name": "obsidian_write_section",
            "description": (
                "Write the section under a heading of an existing note. mode=append "
                "(the default) adds your content at the end of the section and never "
                "touches what is there - use it to add a fact or a list item. "
                "mode=replace rewrites everything up to the next heading of the same "
                "or higher level, subsections included: send the complete new "
                "content, because whatever you leave out is deleted. Use replace only "
                "to restructure a section you have just read. A missing heading is "
                "added at the end of the note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Vault-relative path of an existing note",
                    },
                    "heading": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "Heading text without the leading #",
                    },
                    "content": {"type": "string", "description": "Markdown for the section"},
                    "mode": {"type": "string", "enum": ["append", "replace"], "default": "append"},
                    "level": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 6,
                        "description": "Heading depth, when two headings share the text",
                    },
                },
                "required": ["path", "heading", "content"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_patch_frontmatter": {
        "type": "function",
        "function": {
            "name": "obsidian_patch_frontmatter",
            "description": (
                "Patch typed frontmatter fields on an existing note. Useful for "
                "status changes, due dates, or tag toggles. `source` may only be set "
                "to `inferred` or `reconstruction`, or to null once the user confirms "
                "the note. Other reserved fields (created, conversation, path) cannot "
                "change. Types must match existing fields; e.g. a `tags` list cannot "
                "be replaced with a string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Vault-relative path of an existing note",
                    },
                    "patch": {
                        "type": "object",
                        "description": "Frontmatter fields to add or replace",
                    },
                },
                "required": ["path", "patch"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_read_canvas": {
        "type": "function",
        "function": {
            "name": "obsidian_read_canvas",
            "description": (
                "Read an Obsidian canvas (*.canvas) and return its nodes and "
                "edges. Read before editing: a canvas is written whole, so "
                "anything you omit on write is lost."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative path, e.g. 'Tech/Architecture.canvas'.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_write_canvas": {
        "type": "function",
        "function": {
            "name": "obsidian_write_canvas",
            "description": (
                "Create or replace an Obsidian canvas (*.canvas). The whole "
                "document is written at once, so read it first and send back "
                "the full node and edge lists including what you keep. "
                "Coordinates are pixels; width 300 / height 120 spaced about "
                "400 apart reads well. Every edge must point at node ids that "
                "exist or the write is rejected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Vault-relative path; the .canvas extension is "
                            "appended when missing."
                        ),
                    },
                    "nodes": {
                        "type": "array",
                        "description": (
                            "Each node needs id, type "
                            "('text'|'file'|'link'|'group'), x, y, width, "
                            "height. 'text' needs text (markdown), 'file' "
                            "needs file (a vault path), 'link' needs url. "
                            "Optional color is '1'-'6' or hex."
                        ),
                        "items": {"type": "object"},
                    },
                    "edges": {
                        "type": "array",
                        "description": (
                            "Each edge needs id, fromNode, toNode. Optional "
                            "fromSide/toSide ('top'|'right'|'bottom'|'left'), "
                            "fromEnd/toEnd ('none'|'arrow'), label, color."
                        ),
                        "items": {"type": "object"},
                    },
                },
                "required": ["path", "nodes"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_map": {
        "type": "function",
        "function": {
            "name": "obsidian_map",
            "description": (
                "Read or update the agent's structure cache (.obsidian-map.yaml). "
                "Pass `action: get` to retrieve the current map, or `action: patch` "
                "with a `patch` object to update folders, rules, or aliases. Use "
                "this to record what you have learned about the vault's layout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "patch"],
                        "description": "Whether to read or update the structure map",
                    },
                    "patch": {
                        "type": "object",
                        "description": (
                            "When action=patch, the fields to merge into the map. "
                            "Supports a deep merge on the `folders` key."
                        ),
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_propose_delete": {
        "type": "function",
        "function": {
            "name": "obsidian_propose_delete",
            "description": (
                "Move a note to .trash/YYYY-MM-DD/<basename>. The note is not "
                "permanently deleted; the user reviews .trash/ in Obsidian and "
                "bulk-deletes when ready. Always include a reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Vault-relative path of the note to trash",
                    },
                    "reason": {
                        "type": "string",
                        "maxLength": 500,
                        "description": "Why the note is being trashed",
                    },
                },
                "required": ["path", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "obsidian_history": {
        "type": "function",
        "function": {
            "name": "obsidian_history",
            "description": (
                "Show who changed the vault, or one note, and when. Agent writes are "
                "attributed to the caller they wrote for; the user's own edits in "
                "Obsidian show as `obsidian`. Use it to answer what changed recently, "
                "or before undoing a change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "maxLength": 512,
                        "description": "Vault-relative note path; omit for the whole vault",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
}


def as_tool_list() -> list[dict[str, Any]]:
    """Return the tools in the OpenAI-compatible list-of-functions format."""
    return list(TOOLS.values())


def is_obsidian_tool(name: str) -> bool:
    return name in TOOLS
