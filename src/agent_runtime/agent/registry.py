"""Agent registry — discover and look up agent definitions."""

from __future__ import annotations

import glob
import os
from typing import Dict, List, Optional

from .definition import AgentDefinition, load_agent_definition


class AgentRegistry:
    """In-memory index of agent definitions, keyed by ``(agent_id, version)``."""

    def __init__(self) -> None:
        self._agents: Dict[str, Dict[str, AgentDefinition]] = {}

    def register(self, defn: AgentDefinition) -> None:
        """Register an agent definition.  Raises on duplicate id+version."""
        versions = self._agents.setdefault(defn.agent_id, {})
        if defn.version in versions:
            raise ValueError(
                f"Agent '{defn.agent_id}' version '{defn.version}' "
                "already registered"
            )
        versions[defn.version] = defn

    def get(self, agent_id: str, version: Optional[str] = None) -> AgentDefinition:
        """Get an agent by id.  If *version* is ``None``, return the latest."""
        versions = self._agents.get(agent_id)
        if not versions:
            raise KeyError(f"Agent '{agent_id}' not found in registry")
        if version:
            defn = versions.get(version)
            if not defn:
                raise KeyError(
                    f"Agent '{agent_id}' version '{version}' not found"
                )
            return defn
        return self._latest(versions)

    def list_agents(self) -> Dict[str, List[str]]:
        """Return ``{agent_id: [versions]}``."""
        return {aid: sorted(vs.keys()) for aid, vs in self._agents.items()}

    @classmethod
    def from_directory(cls, agents_dir: str) -> "AgentRegistry":
        """Scan a directory for ``*.yaml`` / ``*.yml`` agent definition files."""
        registry = cls()
        if not os.path.isdir(agents_dir):
            return registry
        for pattern in ("*.yaml", "*.yml"):
            for path in sorted(
                glob.glob(os.path.join(agents_dir, "**", pattern), recursive=True)
            ):
                try:
                    defn = load_agent_definition(path)
                    registry.register(defn)
                except Exception as exc:
                    import warnings
                    warnings.warn(
                        f"Skipping invalid agent file {path}: {exc}",
                        stacklevel=2,
                    )
                    continue  # skip invalid files during directory scan
        return registry

    @staticmethod
    def _latest(versions: Dict[str, AgentDefinition]) -> AgentDefinition:
        key = sorted(versions.keys(), key=_version_sort_key)[-1]
        return versions[key]


from ..utils import version_sort_key as _version_sort_key
