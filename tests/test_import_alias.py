"""Tests for the forrestrun import alias package."""

from __future__ import annotations


class TestForrestrunAlias:
    def test_import_forrestrun(self):
        import forrestrun
        assert hasattr(forrestrun, "run_workflow")
        assert hasattr(forrestrun, "RuntimeBuilder")

    def test_same_objects(self):
        import forrestrun
        import agent_runtime
        assert forrestrun.run_workflow is agent_runtime.run_workflow
        assert forrestrun.RuntimeBuilder is agent_runtime.RuntimeBuilder
        assert forrestrun.Run is agent_runtime.Run

    def test_from_import(self):
        from forrestrun import RuntimeBuilder, run_workflow, Run
        from agent_runtime import RuntimeBuilder as AR_Builder
        assert RuntimeBuilder is AR_Builder

    def test_all_exports_available(self):
        import forrestrun
        for name in forrestrun.__all__:
            assert hasattr(forrestrun, name), f"Missing: {name}"
