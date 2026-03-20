"""Prompt registry — load, version, and reference reusable prompts.

Prompts live in a ``prompts/`` directory as YAML files.  Agents reference
them by id (``prompts.<prompt_id>`` or ``prompts.<prompt_id>@v2``) so
developers can swap prompts without touching agent logic.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class PromptEntry:
    """A single versioned prompt."""

    prompt_id: str
    version: str
    text: str
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class PromptRegistry:
    """Registry of reusable prompts loaded from YAML files.

    Agents reference prompts as ``prompts.<id>`` (latest version) or
    ``prompts.<id>@v2`` (pinned version).
    """

    def __init__(self) -> None:
        self._prompts: Dict[str, Dict[str, PromptEntry]] = {}  # id -> {version -> entry}

    # -- public api --------------------------------------------------------

    def register(self, entry: PromptEntry) -> None:
        """Register a single prompt entry.  Raises on duplicate id+version."""
        versions = self._prompts.setdefault(entry.prompt_id, {})
        if entry.version in versions:
            raise ValueError(
                f"Prompt '{entry.prompt_id}' version '{entry.version}' already registered"
            )
        versions[entry.version] = entry

    def get(self, prompt_id: str, version: Optional[str] = None) -> PromptEntry:
        """Return a prompt by id.  If *version* is ``None``, return the latest."""
        versions = self._prompts.get(prompt_id)
        if not versions:
            raise KeyError(f"Prompt '{prompt_id}' not found in registry")
        if version:
            entry = versions.get(version)
            if not entry:
                raise KeyError(
                    f"Prompt '{prompt_id}' version '{version}' not found"
                )
            return entry
        return self._latest(versions)

    def list_prompts(self) -> Dict[str, List[str]]:
        """Return ``{prompt_id: [versions]}``."""
        return {pid: sorted(vs.keys()) for pid, vs in self._prompts.items()}

    def resolve(self, ref: str) -> str:
        """Resolve a prompt reference and return the prompt text.

        Formats:
            ``prompts.my_prompt``       → latest version
            ``prompts.my_prompt@v2``    → pinned version
        """
        if not ref.startswith("prompts."):
            raise ValueError(
                f"Invalid prompt reference '{ref}': must start with 'prompts.'"
            )
        rest = ref[len("prompts."):]
        if "@" in rest:
            prompt_id, version = rest.split("@", 1)
        else:
            prompt_id, version = rest, None
        return self.get(prompt_id, version).text

    # -- loading -----------------------------------------------------------

    @classmethod
    def from_directory(cls, prompts_dir: str) -> "PromptRegistry":
        """Scan a directory recursively for ``*.yaml`` / ``*.yml`` prompt files."""
        registry = cls()
        if not os.path.isdir(prompts_dir):
            return registry
        for pattern in ("*.yaml", "*.yml"):
            for path in sorted(
                glob.glob(os.path.join(prompts_dir, "**", pattern), recursive=True)
            ):
                entries = _load_prompt_file(path)
                for entry in entries:
                    registry.register(entry)
        return registry

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _latest(versions: Dict[str, PromptEntry]) -> PromptEntry:
        key = sorted(versions.keys(), key=_version_sort_key)[-1]
        return versions[key]


# -- file loading ----------------------------------------------------------


def _load_prompt_file(path: str) -> List[PromptEntry]:
    """Parse a prompt YAML file.

    **Single prompt**::

        prompt:
          id: code_review_system
          version: v1
          text: "You are a senior code reviewer..."

    **Multiple prompts**::

        prompts:
          - id: code_review_system
            version: v1
            text: "You are a senior code reviewer..."
          - id: summarizer_system
            version: v1
            text: "Summarize the following..."
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not raw:
        return []
    if "prompts" in raw:
        items = raw["prompts"]
        if not isinstance(items, list):
            raise ValueError(f"{path}: 'prompts' must be a list")
    elif "prompt" in raw:
        items = [raw["prompt"]]
    else:
        raise ValueError(f"{path}: expected 'prompt' or 'prompts' top-level key")

    entries: List[PromptEntry] = []
    for item in items:
        _validate_prompt_item(item, path)
        entries.append(
            PromptEntry(
                prompt_id=item["id"],
                version=str(item.get("version", "v1")),
                text=item["text"],
                description=item.get("description", ""),
                metadata={
                    k: v
                    for k, v in item.items()
                    if k not in ("id", "version", "text", "description")
                },
            )
        )
    return entries


def _validate_prompt_item(item: dict, path: str) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"{path}: each prompt must be a mapping")
    for key in ("id", "text"):
        if key not in item:
            raise ValueError(f"{path}: prompt missing required field '{key}'")


def _version_sort_key(v: str):
    """Sort key that handles 'v1', 'v2', ..., 'v10' correctly."""
    stripped = v.lstrip("vV")
    try:
        return (0, int(stripped))
    except ValueError:
        return (1, v)
