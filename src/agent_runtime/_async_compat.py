"""Async/sync bridging helpers for sync entry points.

When a sync entry point is invoked from inside an already-running event loop
(FastAPI route handler, Jupyter cell), ``asyncio.run()`` raises. The helper
below dispatches the coroutine to a dedicated worker thread that owns its
own event loop, joins, and re-raises any exception in the caller's thread.
Stdlib only — no nest_asyncio dependency.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine


def run_coro_blocking(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion, blocking the caller.

    If no event loop is running in the current thread, behaves like
    ``asyncio.run(coro)``. Otherwise runs the coroutine in a worker thread
    with a fresh event loop so sync entry points work from inside
    FastAPI / Jupyter / other async contexts.
    """
    # Detect a running loop without leaving the RuntimeError live in the
    # exception context — if asyncio.run(coro) ran inside this except block
    # and the coroutine raised, the user's exception would chain to
    # "no running event loop" and render the misleading
    # "During handling of the above exception, another exception occurred."
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if not in_loop:
        return asyncio.run(coro)

    result: list[Any] = [None]
    exc: list[BaseException | None] = [None]

    def _runner() -> None:
        try:
            result[0] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            exc[0] = e

    thread = threading.Thread(target=_runner, name="forrestrun-sync-bridge", daemon=True)
    thread.start()
    thread.join()
    if exc[0] is not None:
        raise exc[0]
    return result[0]
