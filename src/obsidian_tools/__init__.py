"""obsidian-litellm-tools: an Obsidian vault as a LiteLLM tool pack."""

from .hook import ObsidianToolHook
from .pack import ObsidianPack

__version__ = "0.2.0"
__all__ = ["ObsidianPack", "ObsidianToolHook"]
