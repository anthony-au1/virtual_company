"""Tests for heartbeat supervision independent of repositories."""

from __future__ import annotations

import asyncio

import pytest

from virtual_company.task_queue.lifecycle import (
    ExecutionOwnershipLostError,
    run_with_heartbeat,
)


class _Heartbeat:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.cancelled = False

    async def run(self) -> None:
        try:
            if self.error is None:
                await asyncio.Future()
            raise self.error
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_successful_operation_stops_heartbeat() -> None:
    heartbeat = _Heartbeat()

    result = await run_with_heartbeat(heartbeat, asyncio.sleep(0, result="done"))

    assert result == "done"
    assert heartbeat.cancelled


@pytest.mark.asyncio
async def test_ownership_loss_cancels_active_operation() -> None:
    heartbeat = _Heartbeat(error=ExecutionOwnershipLostError("lost"))
    operation_cancelled = asyncio.Event()

    async def operation() -> None:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            operation_cancelled.set()
            raise

    with pytest.raises(ExecutionOwnershipLostError, match="lost"):
        await run_with_heartbeat(heartbeat, operation())

    assert operation_cancelled.is_set()


@pytest.mark.asyncio
async def test_business_error_wins_if_heartbeat_fails_at_same_time() -> None:
    heartbeat = _Heartbeat(error=ExecutionOwnershipLostError("heartbeat error"))

    async def operation() -> None:
        raise ValueError("business error")

    with pytest.raises(ValueError, match="business error"):
        await run_with_heartbeat(heartbeat, operation())


@pytest.mark.asyncio
async def test_caller_cancellation_cleans_up_both_tasks() -> None:
    heartbeat = _Heartbeat()
    operation_cancelled = asyncio.Event()

    async def operation() -> None:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            operation_cancelled.set()
            raise

    task = asyncio.create_task(run_with_heartbeat(heartbeat, operation()))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert heartbeat.cancelled
    assert operation_cancelled.is_set()
