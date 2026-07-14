from __future__ import annotations

import asyncio

import pytest

from src.helpers.timeout import BatchTimeout


@pytest.mark.unit
async def test_batch_timeout_cancels_pending_task_and_calls_timeout_callback() -> None:
    timeout_calls: list[tuple[type[BaseException], str]] = []
    blocker = asyncio.Event()

    async def wait_forever(label: str) -> None:
        await blocker.wait()

    def on_timeout(error: asyncio.CancelledError, label: str) -> None:
        timeout_calls.append((type(error), label))

    async with BatchTimeout(wait_forever, timeout=0, on_timeout=on_timeout) as batch:
        task = batch("pending")

    assert task.cancelled()
    assert timeout_calls == [(asyncio.CancelledError, "pending")]


@pytest.mark.unit
async def test_batch_timeout_routes_completed_task_exception_to_error_callback() -> None:
    error_calls: list[tuple[type[Exception], str, str]] = []

    async def fail(label: str) -> None:
        raise ValueError("characterized task failure")

    def on_error(error: Exception, label: str) -> None:
        error_calls.append((type(error), str(error), label))

    async with BatchTimeout(fail, timeout=60, on_error=on_error) as batch:
        task = batch("failed")

    assert task.done()
    assert error_calls == [
        (ValueError, "characterized task failure", "failed"),
    ]


@pytest.mark.unit
async def test_batch_timeout_routes_external_context_cancellation_to_canceled_callback() -> None:
    started = asyncio.Event()
    blocker = asyncio.Event()
    canceled_calls: list[tuple[type[BaseException], str]] = []
    timeout_calls: list[str] = []

    async def wait_forever(label: str) -> None:
        started.set()
        await blocker.wait()

    def on_canceled(error: asyncio.CancelledError, label: str) -> None:
        canceled_calls.append((type(error), label))

    def on_timeout(error: asyncio.CancelledError, label: str) -> None:
        timeout_calls.append(label)

    async def run_batch() -> None:
        async with BatchTimeout(
            wait_forever,
            timeout=60,
            on_canceled=on_canceled,
            on_timeout=on_timeout,
        ) as batch:
            batch("externally-canceled")
            await started.wait()
            await blocker.wait()

    outer_task = asyncio.create_task(run_batch())
    await started.wait()
    outer_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await outer_task

    assert canceled_calls == [
        (asyncio.CancelledError, "externally-canceled"),
    ]
    assert timeout_calls == []
