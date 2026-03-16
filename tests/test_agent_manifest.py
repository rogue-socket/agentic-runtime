"""Tests for agent manifest system — loading, validation, export, import."""

from __future__ import annotations

import os
import tarfile
from typing import Any

import pytest

from agent_runtime.agent import (
    export_agent,
    import_agent,
    load_agent_manifest,
    validate_agent,
)
from agent_runtime.errors import AgentValidationError
from agent_runtime.llm import LLMProvider, LLMRegistry, ModelConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


MINIMAL_MANIFEST = """\
agent:
  id: test_agent
  version: v1
workflow: workflows/test.yaml
"""

FULL_MANIFEST = """\
agent:
  id: full_agent
  version: v2
  description: "A fully declared agent"
  runtime: ">=0.2"
workflow: workflows/triage.yaml
handlers:
  - handlers/classify.py
  - handlers/summarize.py
tools:
  - tools/github_tool.py
providers:
  - name: openai
    models: [gpt-4, gpt-4o-mini]
  - name: anthropic
    models: [claude-3-opus]
env:
  - GITHUB_TOKEN
  - SLACK_URL
defaults:
  issue: "default issue text"
"""

MINIMAL_WORKFLOW = """\
workflow:
  id: test_workflow
  version: v1
on_error: fail_fast
steps:
  - id: step_one
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
"""


# ---------------------------------------------------------------------------
# Loading tests
# ---------------------------------------------------------------------------

class TestLoadAgentManifest:
    def test_load_minimal(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), MINIMAL_MANIFEST)
        m = load_agent_manifest(path)
        assert m.agent_id == "test_agent"
        assert m.version == "v1"
        assert m.workflow == "workflows/test.yaml"
        assert m.handlers == []
        assert m.tools == []
        assert m.providers == []
        assert m.env == []
        assert m.defaults == {}

    def test_load_full(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(path)
        assert m.agent_id == "full_agent"
        assert m.version == "v2"
        assert m.description == "A fully declared agent"
        assert m.runtime_constraint == ">=0.2"
        assert m.workflow == "workflows/triage.yaml"
        assert m.handlers == ["handlers/classify.py", "handlers/summarize.py"]
        assert m.tools == ["tools/github_tool.py"]
        assert len(m.providers) == 2
        assert m.providers[0].name == "openai"
        assert set(m.providers[0].models) == {"gpt-4", "gpt-4o-mini"}
        assert m.env == ["GITHUB_TOKEN", "SLACK_URL"]
        assert m.defaults == {"issue": "default issue text"}

    def test_load_missing_file(self) -> None:
        with pytest.raises(AgentValidationError, match="not found"):
            load_agent_manifest("/nonexistent/agent.yaml")

    def test_load_missing_agent_block(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), "workflow: x.yaml\n")
        with pytest.raises(AgentValidationError, match="agent"):
            load_agent_manifest(path)

    def test_load_missing_id(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), "agent:\n  version: v1\nworkflow: x.yaml\n")
        with pytest.raises(AgentValidationError, match="agent.id"):
            load_agent_manifest(path)

    def test_load_missing_version(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), "agent:\n  id: x\nworkflow: x.yaml\n")
        with pytest.raises(AgentValidationError, match="agent.version"):
            load_agent_manifest(path)

    def test_load_missing_workflow(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), "agent:\n  id: x\n  version: v1\n")
        with pytest.raises(AgentValidationError, match="workflow"):
            load_agent_manifest(path)

    def test_provider_string_shorthand(self, tmp_path: Any) -> None:
        content = MINIMAL_MANIFEST + "providers:\n  - openai\n  - anthropic\n"
        path = _write(str(tmp_path / "agent.yaml"), content)
        m = load_agent_manifest(path)
        assert m.providers[0].name == "openai"
        assert m.providers[0].models == []
        assert m.providers[1].name == "anthropic"


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestManifestSerialization:
    def test_to_dict_roundtrip(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(path)
        d = m.to_dict()
        assert d["agent"]["id"] == "full_agent"
        assert d["workflow"] == "workflows/triage.yaml"
        assert len(d["handlers"]) == 2
        assert len(d["providers"]) == 2

    def test_to_yaml(self, tmp_path: Any) -> None:
        path = _write(str(tmp_path / "agent.yaml"), MINIMAL_MANIFEST)
        m = load_agent_manifest(path)
        yaml_str = m.to_yaml()
        assert "test_agent" in yaml_str
        assert "workflows/test.yaml" in yaml_str


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidateAgent:
    def _setup_project(self, tmp_path: Any) -> str:
        """Create a minimal project structure for validation."""
        root = str(tmp_path)
        _write(os.path.join(root, "workflows", "triage.yaml"), MINIMAL_WORKFLOW)
        _write(os.path.join(root, "handlers", "classify.py"), "def classify(state): return {}\n")
        _write(os.path.join(root, "handlers", "summarize.py"), "def summarize(state): return {}\n")
        _write(os.path.join(root, "tools", "github_tool.py"), "# tool\n")
        return root

    def test_all_files_present(self, tmp_path: Any) -> None:
        root = self._setup_project(tmp_path)
        manifest_path = _write(os.path.join(root, "agents", "full.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)
        results = validate_agent(m, project_root=root)

        file_results = [r for r in results if r.category in ("workflow", "handler", "tool")]
        assert all(r.ok for r in file_results), [r for r in file_results if not r.ok]

    def test_missing_workflow_file(self, tmp_path: Any) -> None:
        root = str(tmp_path)
        manifest_path = _write(os.path.join(root, "agents", "a.yaml"), MINIMAL_MANIFEST)
        m = load_agent_manifest(manifest_path)
        results = validate_agent(m, project_root=root)

        wf_results = [r for r in results if r.category == "workflow"]
        assert len(wf_results) == 1
        assert not wf_results[0].ok

    def test_missing_handler_file(self, tmp_path: Any) -> None:
        root = str(tmp_path)
        _write(os.path.join(root, "workflows", "triage.yaml"), MINIMAL_WORKFLOW)
        # handlers/classify.py exists, handlers/summarize.py does NOT
        _write(os.path.join(root, "handlers", "classify.py"), "# h\n")
        manifest_path = _write(os.path.join(root, "agents", "a.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)
        results = validate_agent(m, project_root=root)

        handler_results = [r for r in results if r.category == "handler"]
        ok_names = {r.name for r in handler_results if r.ok}
        fail_names = {r.name for r in handler_results if not r.ok}
        assert "handlers/classify.py" in ok_names
        assert "handlers/summarize.py" in fail_names

    def test_missing_env_var(self, tmp_path: Any, monkeypatch: Any) -> None:
        root = self._setup_project(tmp_path)
        manifest_path = _write(os.path.join(root, "agents", "a.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_URL", raising=False)
        results = validate_agent(m, project_root=root)

        env_results = [r for r in results if r.category == "env"]
        assert len(env_results) == 2
        assert not any(r.ok for r in env_results)

    def test_env_var_present(self, tmp_path: Any, monkeypatch: Any) -> None:
        root = self._setup_project(tmp_path)
        manifest_path = _write(os.path.join(root, "agents", "a.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        monkeypatch.setenv("SLACK_URL", "https://hooks.slack.com/xxx")
        results = validate_agent(m, project_root=root)

        env_results = [r for r in results if r.category == "env"]
        assert all(r.ok for r in env_results)

    def test_provider_validation_with_registry(self, tmp_path: Any, monkeypatch: Any) -> None:
        root = self._setup_project(tmp_path)
        manifest_path = _write(os.path.join(root, "agents", "a.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)

        registry = LLMRegistry()
        p = LLMProvider(name="openai", api_key_env="TEST_OAI_KEY")
        p.add_model(ModelConfig(model_id="gpt-4"))
        p.add_model(ModelConfig(model_id="gpt-4o-mini"))
        registry.register_provider(p)
        monkeypatch.setenv("TEST_OAI_KEY", "sk-test")

        results = validate_agent(m, project_root=root, llm_registry=registry)

        prov_results = [r for r in results if r.category == "provider"]
        openai_r = [r for r in prov_results if r.name == "openai"]
        anthropic_r = [r for r in prov_results if r.name == "anthropic"]
        assert len(openai_r) == 1 and openai_r[0].ok
        assert len(anthropic_r) == 1 and not anthropic_r[0].ok

    def test_provider_missing_models(self, tmp_path: Any, monkeypatch: Any) -> None:
        root = self._setup_project(tmp_path)
        manifest_path = _write(os.path.join(root, "agents", "a.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)

        registry = LLMRegistry()
        p = LLMProvider(name="openai", api_key_env="TEST_OAI_KEY")
        p.add_model(ModelConfig(model_id="gpt-4"))
        # gpt-4o-mini NOT configured
        registry.register_provider(p)
        monkeypatch.setenv("TEST_OAI_KEY", "sk-test")

        results = validate_agent(m, project_root=root, llm_registry=registry)
        openai_r = [r for r in results if r.category == "provider" and r.name == "openai"]
        assert len(openai_r) == 1
        assert not openai_r[0].ok
        assert "gpt-4o-mini" in openai_r[0].message

    def test_no_llm_registry(self, tmp_path: Any) -> None:
        root = self._setup_project(tmp_path)
        manifest_path = _write(os.path.join(root, "agents", "a.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)
        results = validate_agent(m, project_root=root, llm_registry=None)

        prov_results = [r for r in results if r.category == "provider"]
        assert all(not r.ok for r in prov_results)


# ---------------------------------------------------------------------------
# Export / Import tests
# ---------------------------------------------------------------------------

class TestExportImport:
    def _setup_full_project(self, root: str) -> str:
        """Create a full project and return manifest path."""
        _write(os.path.join(root, "workflows", "triage.yaml"), MINIMAL_WORKFLOW)
        _write(os.path.join(root, "handlers", "classify.py"), "def classify(state): return {}\n")
        _write(os.path.join(root, "handlers", "summarize.py"), "def summarize(state): return {}\n")
        _write(os.path.join(root, "tools", "github_tool.py"), "# tool placeholder\n")
        manifest_path = _write(os.path.join(root, "agents", "full.yaml"), FULL_MANIFEST)
        return manifest_path

    def test_export_creates_archive(self, tmp_path: Any) -> None:
        root = str(tmp_path / "proj")
        manifest_path = self._setup_full_project(root)
        m = load_agent_manifest(manifest_path)

        output = str(tmp_path / "export.tar.gz")
        result_path = export_agent(m, output, project_root=root)
        assert os.path.isfile(result_path)

        with tarfile.open(result_path, "r:gz") as tar:
            names = tar.getnames()
        assert "agent.yaml" in names
        assert "workflows/triage.yaml" in names
        assert "handlers/classify.py" in names
        assert "tools/github_tool.py" in names

    def test_export_missing_file_raises(self, tmp_path: Any) -> None:
        root = str(tmp_path / "proj")
        _write(os.path.join(root, "workflows", "triage.yaml"), MINIMAL_WORKFLOW)
        # handlers/classify.py is MISSING
        _write(os.path.join(root, "handlers", "summarize.py"), "# h\n")
        _write(os.path.join(root, "tools", "github_tool.py"), "# t\n")
        manifest_path = _write(os.path.join(root, "agents", "full.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)

        with pytest.raises(AgentValidationError, match="not found"):
            export_agent(m, str(tmp_path / "out.tar.gz"), project_root=root)

    def test_import_into_new_project(self, tmp_path: Any) -> None:
        # 1. Setup source project and export
        src = str(tmp_path / "src_proj")
        manifest_path = self._setup_full_project(src)
        m = load_agent_manifest(manifest_path)
        archive = str(tmp_path / "agent.tar.gz")
        export_agent(m, archive, project_root=src)

        # 2. Import into empty target
        dst = str(tmp_path / "dst_proj")
        os.makedirs(dst)
        imported = import_agent(archive, project_root=dst)

        assert imported.agent_id == "full_agent"
        assert imported.version == "v2"

        # Files should exist in the target project
        assert os.path.isfile(os.path.join(dst, "workflows", "triage.yaml"))
        assert os.path.isfile(os.path.join(dst, "handlers", "classify.py"))
        assert os.path.isfile(os.path.join(dst, "handlers", "summarize.py"))
        assert os.path.isfile(os.path.join(dst, "tools", "github_tool.py"))
        assert os.path.isfile(os.path.join(dst, "agents", "full_agent.yaml"))

    def test_import_nonexistent_archive(self, tmp_path: Any) -> None:
        with pytest.raises(AgentValidationError, match="not found"):
            import_agent(str(tmp_path / "nope.tar.gz"))

    def test_roundtrip_preserves_content(self, tmp_path: Any) -> None:
        """Export then import, verify tool file content is preserved."""
        src = str(tmp_path / "src")
        tool_content = "class MyTool:\n    name = 'tools.my'\n"
        _write(os.path.join(src, "workflows", "triage.yaml"), MINIMAL_WORKFLOW)
        _write(os.path.join(src, "handlers", "classify.py"), "# classify\n")
        _write(os.path.join(src, "handlers", "summarize.py"), "# summarize\n")
        _write(os.path.join(src, "tools", "github_tool.py"), tool_content)
        manifest_path = _write(os.path.join(src, "agents", "a.yaml"), FULL_MANIFEST)
        m = load_agent_manifest(manifest_path)

        archive = str(tmp_path / "rt.tar.gz")
        export_agent(m, archive, project_root=src)

        dst = str(tmp_path / "dst")
        os.makedirs(dst)
        import_agent(archive, project_root=dst)

        with open(os.path.join(dst, "tools", "github_tool.py"), "r") as f:
            assert f.read() == tool_content
