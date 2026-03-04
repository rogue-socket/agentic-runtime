from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict
import json
import sys


class StructuredLogger:
    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stdout

    def info(self, event: str, payload: Dict[str, Any]) -> None:
        record = {"event": event, **payload}
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def error(self, event: str, payload: Dict[str, Any]) -> None:
        record = {"event": event, **payload}
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def from_dataclass(self, event: str, obj: Any) -> None:
        self.info(event, asdict(obj))
