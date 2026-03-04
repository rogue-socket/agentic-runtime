from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]


class ToolDiscovery:
    def discover(self, context: Dict[str, Any]) -> List[ToolSpec]:
        # [SCAFFOLD:TOOL_DISCOVERY] Wire to dynamic discovery backends.
        return []
