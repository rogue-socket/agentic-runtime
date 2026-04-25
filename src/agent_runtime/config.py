"""Runtime configuration loader.

Loads settings from ``runtime.yaml`` (if present), provides sensible defaults,
and allows CLI flags to override any value.

Precedence (highest wins):
    CLI flag  >  runtime.yaml  >  built-in default


"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict

import yaml

from .errors import ConfigValidationError
from .llm import LLMRegistry
from .schema_versioning import (
    RUNTIME_CONFIG_SCHEMA_VERSION_CURRENT,
    parse_required_schema_version,
)

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _interpolate_env_vars(value: Any) -> Any:
    """Recursively substitute ``${VAR}`` placeholders with env-var values.

    Unset variables are left as-is (safe-substitute semantics).
    """
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            """Function implementation."""
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env_vars(v) for v in value]
    return value


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merge *overlay* into *base* recursively (overlay wins on conflicts)."""
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class RuntimeConfig:
    """Resolved runtime configuration."""

    schema_version: str = RUNTIME_CONFIG_SCHEMA_VERSION_CURRENT
    db_path: str = "runtime.db"
    workflows_dir: str = "workflows"
    tools_dir: str = "tools"
    agents_dir: str = "agents"
    functions_dir: str = "functions"

    # Legacy model configuration (prefer llm_registry for new workflows)
    model: Dict[str, Any] = field(default_factory=dict)

    # LLM provider registry
    llm_registry: LLMRegistry = field(default_factory=LLMRegistry)

    # Logging
    log_level: str = "info"
    log_format: str = "json"

    # State overwrite policy: 'warn', 'strict', or 'allow'
    overwrite_policy: str = "warn"

    # Working memory limits
    working_memory_max_entries: int = 50
    working_memory_max_scratch_bytes: int = 256_000

    # Shell tool command restrictions (regex patterns)
    shell_allowlist: list = field(default_factory=list)
    shell_denylist: list = field(default_factory=list)

    # Default LLM provider (used when model string has no provider/ prefix)
    default_llm_provider: str = ""

    # Default model for agent steps that don't specify one
    default_model: str = ""

    # LLM runtime controls (0/None disables the limit)
    llm_rate_limit_rpm: int = 0
    llm_max_requests_per_run: int = 0
    llm_max_total_tokens_per_run: int = 0
    llm_max_cost_usd_per_run: float = 0.0
    llm_pricing_usd_per_1k_tokens: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # [Pain Point Solved] Config Drift Between Environments - Resolved via
    #   _interpolate_env_vars() for ${VAR} substitution and overlay loading
    #   (runtime.{RUNTIME_ENV}.yaml merged on top of runtime.yaml).


# Keys in runtime.yaml that map to flat RuntimeConfig fields
_FLAT_KEYS = {
    "db_path", "workflows_dir", "tools_dir",
    "agents_dir", "functions_dir",
    "overwrite_policy", "default_llm_provider", "default_model",
}


def load_config(config_path: str = "runtime.yaml") -> RuntimeConfig:
    """Load config from *config_path*, falling back to defaults for missing keys.

    Supports environment overlay files and ``${VAR}`` interpolation:
    - If ``RUNTIME_ENV`` is set (e.g. ``prod``), loads
      ``runtime.prod.yaml`` and deep-merges it on top of the base.
    - All string values undergo ``${ENV_VAR}`` substitution from
      ``os.environ`` before being applied to the config object.
    """
    cfg = RuntimeConfig()

    if not os.path.isfile(config_path):
        return cfg

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return cfg

    # --- Environment overlay ---
    runtime_env = os.environ.get("RUNTIME_ENV")
    if runtime_env:
        base_name, ext = os.path.splitext(config_path)
        overlay_path = f"{base_name}.{runtime_env}{ext}"
        if os.path.isfile(overlay_path):
            with open(overlay_path, "r", encoding="utf-8") as f:
                overlay_raw = yaml.safe_load(f)
            if isinstance(overlay_raw, dict):
                raw = _deep_merge(raw, overlay_raw)

    # --- Env-var interpolation ---
    raw = _interpolate_env_vars(raw)

    try:
        cfg.schema_version = parse_required_schema_version(
            raw,
            expected_version=RUNTIME_CONFIG_SCHEMA_VERSION_CURRENT,
            component_name="runtime config",
        )
    except ValueError as exc:
        raise ConfigValidationError(str(exc)) from exc

    for key in _FLAT_KEYS:
        if key in raw:
            setattr(cfg, key, raw[key])

    if isinstance(raw.get("model"), dict):
        cfg.model = raw["model"]

    def _apply_limits_block(limits_block: Any) -> None:
        """Function implementation."""
        if isinstance(limits_block, dict):
            if "rate_limit_rpm" in limits_block:
                cfg.llm_rate_limit_rpm = int(limits_block["rate_limit_rpm"])
            if "max_requests_per_run" in limits_block:
                cfg.llm_max_requests_per_run = int(limits_block["max_requests_per_run"])
            if "max_total_tokens_per_run" in limits_block:
                cfg.llm_max_total_tokens_per_run = int(limits_block["max_total_tokens_per_run"])
            if "max_cost_usd_per_run" in limits_block:
                cfg.llm_max_cost_usd_per_run = float(limits_block["max_cost_usd_per_run"])
            pricing_block = limits_block.get("pricing_usd_per_1k_tokens")
            if isinstance(pricing_block, dict):
                cleaned: Dict[str, Dict[str, float]] = {}
                for model_ref, prices in pricing_block.items():
                    if not isinstance(model_ref, str) or not isinstance(prices, dict):
                        continue
                    input_rate = prices.get("input")
                    output_rate = prices.get("output")
                    out: Dict[str, float] = {}
                    if isinstance(input_rate, (int, float)):
                        out["input"] = float(input_rate)
                    if isinstance(output_rate, (int, float)):
                        out["output"] = float(output_rate)
                    if out:
                        cleaned[model_ref] = out
                cfg.llm_pricing_usd_per_1k_tokens = cleaned

    if isinstance(raw.get("llm"), dict):
        cfg.llm_registry = LLMRegistry.from_config(raw["llm"])
        _apply_limits_block(raw["llm"].get("limits"))

    _apply_limits_block(raw.get("llm_limits"))

    # Apply top-level default_llm_provider if the llm section didn't set one
    if (cfg.default_llm_provider or "").strip() and not cfg.llm_registry.default_provider:
        cfg.llm_registry.default_provider = cfg.default_llm_provider

    logging_block = raw.get("logging")
    if isinstance(logging_block, dict):
        if "level" in logging_block:
            cfg.log_level = logging_block["level"]
        if "format" in logging_block:
            cfg.log_format = logging_block["format"]

    memory_block = raw.get("memory")
    if isinstance(memory_block, dict):
        working = memory_block.get("working")
        if isinstance(working, dict):
            if "max_entries" in working:
                cfg.working_memory_max_entries = int(working["max_entries"])
            if "max_scratch_bytes" in working:
                cfg.working_memory_max_scratch_bytes = int(working["max_scratch_bytes"])

    shell_block = raw.get("shell")
    if isinstance(shell_block, dict):
        if isinstance(shell_block.get("allowlist"), list):
            cfg.shell_allowlist = shell_block["allowlist"]
        if isinstance(shell_block.get("denylist"), list):
            cfg.shell_denylist = shell_block["denylist"]

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

    if hasattr(args, "llm_rate_limit_rpm") and args.llm_rate_limit_rpm is not None:
        cfg.llm_rate_limit_rpm = int(args.llm_rate_limit_rpm)

    if hasattr(args, "max_llm_requests") and args.max_llm_requests is not None:
        cfg.llm_max_requests_per_run = int(args.max_llm_requests)

    if hasattr(args, "max_llm_tokens") and args.max_llm_tokens is not None:
        cfg.llm_max_total_tokens_per_run = int(args.max_llm_tokens)

    if hasattr(args, "max_llm_cost_usd") and args.max_llm_cost_usd is not None:
        cfg.llm_max_cost_usd_per_run = float(args.max_llm_cost_usd)

    return cfg
