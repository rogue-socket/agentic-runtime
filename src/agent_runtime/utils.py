from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import json


StateDict = Dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def json_loads(raw: str) -> Any:
    return json.loads(raw)


def format_template(value: Any, state: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        return value.format(**state)
    if isinstance(value, dict):
        return {k: format_template(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [format_template(v, state) for v in value]
    return value
