"""Tests for the sync→async bridge that lets sync entry points run inside an event loop."""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime._async_compat import run_coro_blocking


def test_runs_when_no_loop_active() -> None:
    async def coro() -> int:
        return 42

    assert run_coro_blocking(coro()) == 42


def test_dispatches_to_worker_thread_when_loop_active() -> None:
    async def coro() -> int:
        await asyncio.sleep(0)
        return 7

    async def outer() -> int:
        return run_coro_blocking(coro())

    assert asyncio.run(outer()) == 7


def test_propagates_exceptions_from_no_loop_path() -> None:
    async def coro() -> None:
        raise ValueError("boom-no-loop")

    with pytest.raises(ValueError, match="boom-no-loop"):
        run_coro_blocking(coro())


def test_propagates_exceptions_from_worker_thread() -> None:
    async def coro() -> None:
        raise ValueError("boom-worker")

    async def outer() -> None:
        run_coro_blocking(coro())

    with pytest.raises(ValueError, match="boom-worker"):
        asyncio.run(outer())


def test_worker_thread_uses_isolated_loop() -> None:
    """The coroutine must see its own running loop, not the caller's."""
    captured = {}

    async def coro() -> None:
        captured["worker_loop"] = asyncio.get_running_loop()

    async def outer() -> None:
        captured["outer_loop"] = asyncio.get_running_loop()
        run_coro_blocking(coro())

    asyncio.run(outer())
    assert captured["worker_loop"] is not captured["outer_loop"]
