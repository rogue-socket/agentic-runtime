"""Tests for safe_eval and _SafeExprValidator in utils.py.

Covers valid expressions, edge cases, and adversarial inputs
that attempt to escape the restricted evaluation sandbox.
"""

from __future__ import annotations

import pytest

from agent_runtime.utils import safe_eval


# ---------------------------------------------------------------------------
# Valid expressions that should evaluate correctly
# ---------------------------------------------------------------------------

class TestSafeEvalValid:

    def test_simple_equality(self) -> None:
        assert safe_eval("state.inputs.x == 1", {"inputs": {"x": 1}}) is True

    def test_simple_inequality(self) -> None:
        assert safe_eval("state.inputs.x == 1", {"inputs": {"x": 2}}) is False

    def test_string_comparison(self) -> None:
        assert safe_eval("state.inputs.level == 'high'", {"inputs": {"level": "high"}}) is True

    def test_not_equal(self) -> None:
        assert safe_eval("state.inputs.v != 'a'", {"inputs": {"v": "b"}}) is True

    def test_greater_than(self) -> None:
        assert safe_eval("state.inputs.count > 5", {"inputs": {"count": 10}}) is True

    def test_less_than_or_equal(self) -> None:
        assert safe_eval("state.inputs.count <= 5", {"inputs": {"count": 5}}) is True

    def test_boolean_and(self) -> None:
        assert safe_eval(
            "state.inputs.a == 1 and state.inputs.b == 2",
            {"inputs": {"a": 1, "b": 2}},
        ) is True

    def test_boolean_or(self) -> None:
        assert safe_eval(
            "state.inputs.a == 1 or state.inputs.b == 99",
            {"inputs": {"a": 1, "b": 2}},
        ) is True

    def test_boolean_not(self) -> None:
        assert safe_eval("not state.inputs.flag", {"inputs": {"flag": False}}) is True

    def test_nested_state_access(self) -> None:
        state = {"steps": {"classify": {"severity": "critical"}}}
        assert safe_eval("state.steps.classify.severity == 'critical'", state) is True

    def test_len_function(self) -> None:
        assert safe_eval("len(state.inputs.items) > 2", {"inputs": {"items": [1, 2, 3]}}) is True

    def test_numeric_arithmetic(self) -> None:
        assert safe_eval("state.inputs.a + state.inputs.b > 5", {"inputs": {"a": 3, "b": 4}}) is True

    def test_truthiness_of_empty_string(self) -> None:
        assert safe_eval("state.inputs.val", {"inputs": {"val": ""}}) is False

    def test_truthiness_of_nonempty_string(self) -> None:
        assert safe_eval("state.inputs.val", {"inputs": {"val": "yes"}}) is True

    def test_constant_true(self) -> None:
        assert safe_eval("1 == 1", {}) is True

    def test_constant_false(self) -> None:
        assert safe_eval("1 == 2", {}) is False

    def test_membership_in_list(self) -> None:
        assert safe_eval(
            "state.inputs.level in ['high', 'critical']",
            {"inputs": {"level": "critical"}},
        ) is True

    def test_membership_not_in(self) -> None:
        assert safe_eval(
            "state.inputs.level not in ['low', 'medium']",
            {"inputs": {"level": "critical"}},
        ) is True

    def test_string_startswith(self) -> None:
        assert safe_eval(
            "state.inputs.issue.startswith('Login')",
            {"inputs": {"issue": "Login API fails"}},
        ) is True

    def test_string_endswith(self) -> None:
        assert safe_eval(
            "state.inputs.issue.endswith('fails')",
            {"inputs": {"issue": "Login fails"}},
        ) is True

    def test_string_lower_chain(self) -> None:
        assert safe_eval(
            "state.inputs.level.lower() == 'critical'",
            {"inputs": {"level": "CRITICAL"}},
        ) is True

    def test_string_strip(self) -> None:
        assert safe_eval(
            "state.inputs.issue.strip() == 'bug'",
            {"inputs": {"issue": "  bug  "}},
        ) is True

    def test_math_helpers_min_max_abs(self) -> None:
        assert safe_eval("max(state.inputs.a, state.inputs.b) == 9", {"inputs": {"a": 4, "b": 9}}) is True
        assert safe_eval("min(state.inputs.a, state.inputs.b) == 4", {"inputs": {"a": 4, "b": 9}}) is True
        assert safe_eval("abs(state.inputs.delta) < 5", {"inputs": {"delta": -3}}) is True


# ---------------------------------------------------------------------------
# Adversarial / malicious expressions that MUST be rejected
# ---------------------------------------------------------------------------

class TestSafeEvalRejected:

    def test_import_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("__import__('os')", {})

    def test_dunder_globals_blocked(self) -> None:
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("state.__class__.__bases__", {"inputs": {}})

    def test_dunder_init_blocked(self) -> None:
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("state.__init__", {})

    def test_arbitrary_name_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("os.system('echo pwned')", {})

    def test_builtin_print_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("print('hello')", {})

    def test_lambda_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("(lambda: 1)()", {})

    def test_list_comprehension_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("[x for x in range(10)]", {})

    def test_attribute_on_literal_blocked(self) -> None:
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("''.__class__", {})

    def test_call_non_len_function_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("str(state.inputs)", {"inputs": {}})

    def test_unsupported_string_method_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("state.inputs.issue.replace('a', 'b') == 'x'", {"inputs": {"issue": "a"}})

    def test_string_method_on_non_state_receiver_blocked(self) -> None:
        with pytest.raises(AttributeError):
            safe_eval("state.inputs.num.startswith('1')", {"inputs": {"num": 123}})

    def test_keyword_arguments_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("state.inputs.issue.startswith(prefix='x')", {"inputs": {"issue": "xyz"}})

    def test_exec_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("exec('1+1')", {})

    def test_eval_blocked(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            safe_eval("eval('1+1')", {})

    def test_dunder_subclasses_blocked(self) -> None:
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("state.__class__.__subclasses__", {})

    def test_walrus_operator_blocked(self) -> None:
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval("(x := 1)", {})

    def test_multiline_blocked(self) -> None:
        with pytest.raises(SyntaxError):
            safe_eval("1 == 1\nimport os", {})

    def test_semicolon_multistatement_blocked(self) -> None:
        # ast.parse in eval mode rejects multiple statements
        with pytest.raises(SyntaxError):
            safe_eval("1; import os", {})


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestSafeEvalEdgeCases:

    def test_missing_key_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            safe_eval("state.inputs.nonexistent == 1", {"inputs": {}})

    def test_empty_state(self) -> None:
        with pytest.raises(AttributeError):
            safe_eval("state.inputs.x == 1", {})

    def test_deeply_nested(self) -> None:
        state = {"a": {"b": {"c": {"d": 42}}}}
        assert safe_eval("state.a.b.c.d == 42", state) is True

    def test_integer_zero_is_falsy(self) -> None:
        assert safe_eval("state.val", {"val": 0}) is False

    def test_none_is_falsy(self) -> None:
        assert safe_eval("state.val", {"val": None}) is False

    def test_empty_expression_rejected(self) -> None:
        with pytest.raises(SyntaxError):
            safe_eval("", {})
