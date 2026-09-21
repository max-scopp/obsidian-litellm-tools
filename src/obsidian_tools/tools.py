"""The eight tools exposed by the plugin.

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
    "obsidian_search": {
        "type": "function",
        "function": {
            "name": "obsidian_search",
            "description": (
                "Search the user's Obsidian vault by title, tag, or path substring. "
                "Use before creating a note to check for duplicates and before "
                "answering questions about prior work. Returns up to 20 matches with "
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
                "Create a new note at a vault-relative path. The path's parent "
                "folder is created automatically if needed. The writer generates "
                "frontmatter server-side (created, modified, source=chat, and the "
                "current conversation trace id). If a note already exists at the "
                "path, the call fails with 409 — search first."
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
    "obsidian_patch_frontmatter": {
        "type": "function",
        "function": {
            "name": "obsidian_patch_frontmatter",
            "description": (
                "Patch typed frontmatter fields on an existing note. Useful for "
                "status changes, due dates, or tag toggles. Cannot change reserved "
                "fields (created, source, conversation, path). Types must match "
                "existing fields; e.g. a `tags` list cannot be replaced with a "
                "string."
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
}


def as_tool_list() -> list[dict[str, Any]]:
    """Return the tools in the OpenAI-compatible list-of-functions format."""
    return list(TOOLS.values())


def is_obsidian_tool(name: str) -> bool:
    return name in TOOLS
