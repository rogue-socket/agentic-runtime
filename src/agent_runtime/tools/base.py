from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


@dataclass
class ToolResult:
    success: bool
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    metadata: Optional[Dict[str, Any]]


@dataclass
class RuntimeContext:
    run_id: str
    step_id: str
    state: Dict[str, Any]
    logger: Any


class Tool(Protocol):
    name: str
    description: str
    input_schema: Dict[str, Any]
    timeout: Optional[float]
    retries: Optional[int]

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        ...
