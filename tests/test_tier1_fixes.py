"""Tests for Tier-1 gap fixes: cost reporting, episodic memory depth, output schema."""

from __future__ import annotations

import tempfile
from typing import Any, Dict

import pytest

from agent_runtime.cli import _estimate_step_cost_usd, _to_int
from agent_runtime.core import Executor, StepDefinition, _validate_output_schema
from agent_runtime.errors import StepExecutionError
from agent_runtime.memory.episodic import EpisodicMemory, _truncated_json
from agent_runtime.tools.registry import ToolRegistry
from conftest import make_memory_manager, make_storage


# ── Fix 1: Cost Reporting ──────────────────────────────────────────────


class TestCostReporting:
    def test_estimate_cost_with_wildcard_pricing(self) -> None:
        pricing = {"*": {"input": 0.01, "output": 0.03}}
        usage = {"input_tokens": 1000, "output_tokens": 500}
        cost = _estimate_step_cost_usd(usage, pricing)
        assert cost is not None
        assert abs(cost - 0.025) < 1e-9  # (1000/1000)*0.01 + (500/1000)*0.03

    def test_estimate_cost_with_openai_keys(self) -> None:
        pricing = {"*": {"input": 0.01, "output": 0.03}}
        usage = {"prompt_tokens": 2000, "completion_tokens": 1000}
        cost = _estimate_step_cost_usd(usage, pricing)
        assert cost is not None
        assert abs(cost - 0.05) < 1e-9

    def test_estimate_cost_no_pricing_returns_none(self) -> None:
        assert _estimate_step_cost_usd({"input_tokens": 100}, {}) is None

    def test_estimate_cost_empty_usage_returns_none(self) -> None:
        assert _estimate_step_cost_usd({}, {"*": {"input": 0.01}}) is None

    def test_to_int_coercion(self) -> None:
        assert _to_int(42) == 42
        assert _to_int(3.7) == 3
        assert _to_int("nope") == 0
        assert _to_int(None) == 0


# ── Fix 2: Episodic Memory Depth ──────────────────────────────────────


class TestEpisodicMemoryDepth:
    def test_truncated_json_short(self) -> None:
        result = _truncated_json({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_truncated_json_long(self) -> None:
        big = {"key": "x" * 1000}
        result = _truncated_json(big, max_bytes=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_write_stores_actual_values(self) -> None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.close()
        mem = EpisodicMemory(db_path=tmp.name)

        payload = {
            "runtime": {"workflow_id": "test_wf", "run_id": "r1", "status": "COMPLETED"},
            "inputs": {"repo_url": "https://github.com/example/repo", "branch": "main"},
            "steps": {"classify": {"severity": "P0", "category": "bug"}},
        }
        mem.write(payload)

        episodes = mem.recall("test_wf")
        assert len(episodes) == 1
        ep = episodes[0]
        # Values should be present, not just key names
        assert "https://github.com/example/repo" in ep["inputs_summary"]
        assert "main" in ep["inputs_summary"]
        assert "P0" in ep["outputs_summary"]
        mem.close()

    def test_write_backward_compat_stub_mode(self) -> None:
        """In-memory (stub) mode should not crash."""
        mem = EpisodicMemory()
        mem.write({"runtime": {"workflow_id": "w"}, "inputs": {"x": 1}, "steps": {}})
        # Stub mode stores the full payload as fallback
        result = mem.read({})
        assert "runtime" in result


# ── Fix 3: Output Schema Validation ──────────────────────────────────


class TestOutputSchemaValidation:
    def test_type_validation_passes(self) -> None:
        _validate_output_schema("s1", {"severity": "P0"}, {"severity": {"type": "str"}})

    def test_type_validation_fails(self) -> None:
        with pytest.raises(StepExecutionError, match="expected type str"):
            _validate_output_schema("s1", {"severity": 123}, {"severity": {"type": "str"}})

    def test_enum_validation_passes(self) -> None:
        _validate_output_schema(
            "s1", {"severity": "P0"}, {"severity": {"enum": ["P0", "P1", "P2"]}}
        )

    def test_enum_validation_fails(self) -> None:
        with pytest.raises(StepExecutionError, match="not in allowed values"):
            _validate_output_schema(
                "s1", {"severity": "it's bad"}, {"severity": {"enum": ["P0", "P1", "P2"]}}
            )

    def test_regex_validation_passes(self) -> None:
        _validate_output_schema(
            "s1", {"code": "ABC-123"}, {"code": {"regex": r"[A-Z]+-\d+"}}
        )

    def test_regex_validation_fails(self) -> None:
        with pytest.raises(StepExecutionError, match="does not match regex"):
            _validate_output_schema(
                "s1", {"code": "nope"}, {"code": {"regex": r"[A-Z]+-\d+"}}
            )

    def test_combined_rules(self) -> None:
        schema = {"severity": {"type": "str", "enum": ["P0", "P1"], "regex": r"P\d"}}
        _validate_output_schema("s1", {"severity": "P0"}, schema)

    def test_combined_rules_multiple_errors(self) -> None:
        schema = {"severity": {"type": "int", "enum": ["P0"]}}
        with pytest.raises(StepExecutionError, match="expected type int.*not in allowed"):
            _validate_output_schema("s1", {"severity": "bad"}, schema)

    def test_missing_key_skipped_by_schema(self) -> None:
        """Schema validation skips missing keys (handled by output_contract)."""
        _validate_output_schema("s1", {}, {"severity": {"type": "str"}})

    def test_runtime_output_schema_enforced(self) -> None:
        """Integration: Executor rejects step output that violates schema."""
        storage = make_storage()

        def bad_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
            return {"severity": "it's pretty bad"}

        steps = [
            StepDefinition(
                step_id="classify",
                step_type="function",
                function_callable=bad_function,
                input_spec={"issue": "inputs.issue"},
                output_contract=["severity"],
                output_schema={"severity": {"type": "str", "enum": ["P0", "P1", "P2"]}},
            )
        ]

        executor = Executor(steps, storage, None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {"issue": "test"})
        assert run.status == "FAILED"
        assert "Output schema violation" in (run.error or "")

    def test_runtime_output_schema_passes(self) -> None:
        """Integration: valid output passes both contract and schema."""
        storage = make_storage()

        def good_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
            return {"severity": "P0"}

        steps = [
            StepDefinition(
                step_id="classify",
                step_type="function",
                function_callable=good_function,
                input_spec={"issue": "inputs.issue"},
                output_contract=["severity"],
                output_schema={"severity": {"type": "str", "enum": ["P0", "P1", "P2"]}},
            )
        ]

        executor = Executor(steps, storage, None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {"issue": "test"})
        assert run.status == "COMPLETED"
        assert run.state.data["steps"]["classify"]["severity"] == "P0"
