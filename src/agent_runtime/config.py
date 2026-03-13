"""Runtime configuration loader.

Loads settings from ``runtime.yaml`` (if present), provides sensible defaults,
and allows CLI flags to override any value.

Precedence (highest wins):
    CLI flag  >  runtime.yaml  >  built-in default
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict

import yaml


@dataclass
class RuntimeConfig:
    """Resolved runtime configuration."""

    db_path: str = "runtime.db"
    workflows_dir: str = "workflows"
    handlers_dir: str = "handlers"
    tools_dir: str = "tools"

    # Model backend (placeholder for future LLM integration)
    model: Dict[str, Any] = field(default_factory=dict)

    # Logging
    log_level: str = "info"
    log_format: str = "json"


_DEFAULTS = RuntimeConfig()

# Keys in runtime.yaml that map to flat RuntimeConfig fields
_FLAT_KEYS = {"db_path", "workflows_dir", "handlers_dir", "tools_dir"}


def load_config(config_path: str = "runtime.yaml") -> RuntimeConfig:
    """Load config from *config_path*, falling back to defaults for missing keys."""
    cfg = RuntimeConfig()

    if not os.path.isfile(config_path):
        return cfg

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return cfg

    for key in _FLAT_KEYS:
        if key in raw:
            setattr(cfg, key, raw[key])

    if isinstance(raw.get("model"), dict):
        cfg.model = raw["model"]

    logging_block = raw.get("logging")
    if isinstance(logging_block, dict):
        if "level" in logging_block:
            cfg.log_level = logging_block["level"]
        if "format" in logging_block:
            cfg.log_format = logging_block["format"]

    return cfg


def apply_cli_overrides(cfg: RuntimeConfig, args: Any) -> RuntimeConfig:
    """Override config values with explicit CLI flags.

    Only overrides when the CLI flag was explicitly provided (differs from
    argparse default), so that runtime.yaml values are preserved when the
    flag is not passed.
    """
    # --db-path overrides config if explicitly passed
    if hasattr(args, "db_path") and args.db_path is not None:
        cfg.db_path = args.db_path

    return cfg
