"""ForrestRun — import alias for agent_runtime.

Both ``import forrestrun`` and ``import agent_runtime`` expose the
same public API.  Use whichever you prefer::

    from forrestrun import RuntimeBuilder, run_workflow
    # equivalent to:
    from agent_runtime import RuntimeBuilder, run_workflow
"""

from agent_runtime import *  # noqa: F401,F403
from agent_runtime import __all__  # noqa: F401
