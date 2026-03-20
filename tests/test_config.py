"""Tests for RuntimeConfig loading from YAML and CLI overrides."""

from __future__ import annotations

import os
import tempfile

from agent_runtime.config import RuntimeConfig, load_config, apply_cli_overrides


class TestDefaults:

    def test_default_values(self) -> None:
        cfg = RuntimeConfig()
        assert cfg.db_path == "runtime.db"
        assert cfg.workflows_dir == "workflows"
        assert cfg.tools_dir == "tools"
        assert cfg.agents_dir == "agents"
        assert cfg.functions_dir == "functions"
        assert cfg.overwrite_policy == "warn"
        assert cfg.log_level == "info"
        assert cfg.log_format == "json"
        assert cfg.working_memory_max_entries == 50
        assert cfg.working_memory_max_scratch_bytes == 256_000
        assert cfg.shell_allowlist == []
        assert cfg.shell_denylist == []
        assert cfg.default_llm_provider == ""


class TestLoadConfig:

    def test_missing_file_returns_defaults(self) -> None:
        cfg = load_config("/nonexistent/path/runtime.yaml")
        assert cfg.db_path == "runtime.db"

    def test_empty_file_returns_defaults(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.db_path == "runtime.db"

    def test_flat_keys_override(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("db_path: custom.db\nworkflows_dir: my_workflows\noverwrite_policy: strict\n")
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.db_path == "custom.db"
        assert cfg.workflows_dir == "my_workflows"
        assert cfg.overwrite_policy == "strict"

    def test_logging_block(self) -> None:
        yaml_text = "logging:\n  level: debug\n  format: text\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.log_level == "debug"
        assert cfg.log_format == "text"

    def test_memory_block(self) -> None:
        yaml_text = "memory:\n  working:\n    max_entries: 100\n    max_scratch_bytes: 500000\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.working_memory_max_entries == 100
        assert cfg.working_memory_max_scratch_bytes == 500_000

    def test_shell_block(self) -> None:
        yaml_text = "shell:\n  allowlist:\n    - echo\n    - cat\n  denylist:\n    - rm\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.shell_allowlist == ["echo", "cat"]
        assert cfg.shell_denylist == ["rm"]

    def test_llm_provider_wiring(self) -> None:
        yaml_text = (
            "default_llm_provider: gemini\n"
            "llm:\n"
            "  providers:\n"
            "    gemini:\n"
            "      api_key_env: GEMINI_API_KEY\n"
            "      models:\n"
            "        gemini-2.5-flash:\n"
            "          temperature: 0.3\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.llm_registry.default_provider == "gemini"
        provider = cfg.llm_registry.get_provider("gemini")
        assert provider is not None

    def test_non_dict_yaml_returns_defaults(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("just a string\n")
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.db_path == "runtime.db"

    def test_unknown_keys_ignored(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("unknown_setting: 42\ndb_path: test.db\n")
            f.flush()
            cfg = load_config(f.name)
        os.unlink(f.name)
        assert cfg.db_path == "test.db"
        assert not hasattr(cfg, "unknown_setting")


class TestCLIOverrides:

    def test_db_path_override(self) -> None:
        cfg = RuntimeConfig()

        class Args:
            db_path = "override.db"

        cfg = apply_cli_overrides(cfg, Args())
        assert cfg.db_path == "override.db"

    def test_no_override_when_none(self) -> None:
        cfg = RuntimeConfig(db_path="from_yaml.db")

        class Args:
            db_path = None

        cfg = apply_cli_overrides(cfg, Args())
        assert cfg.db_path == "from_yaml.db"

    def test_no_override_when_missing_attr(self) -> None:
        cfg = RuntimeConfig(db_path="original.db")

        class Args:
            pass

        cfg = apply_cli_overrides(cfg, Args())
        assert cfg.db_path == "original.db"
