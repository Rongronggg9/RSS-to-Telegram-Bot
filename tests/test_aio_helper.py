from __future__ import annotations

import asyncio
import logging

import pytest


class _SignalHandler(logging.Handler):
    def __init__(self, emitted: asyncio.Event) -> None:
        super().__init__()
        self._emitted = emitted

    def emit(self, record: logging.LogRecord) -> None:
        self._emitted.set()


@pytest.mark.unit
async def test_run_async_uses_the_bound_pytest_loop_without_initialized_executor() -> None:
    from src import aio_helper, env

    running_loop = asyncio.get_running_loop()
    assert env.loop is running_loop
    assert aio_helper.aioThreadExecutor is None
    assert aio_helper.aioProcessExecutor is None

    def identify_call() -> tuple[str, int]:
        return "executor-result", 37

    assert await aio_helper.run_async(identify_call) == ("executor-result", 37)


@pytest.mark.unit
async def test_background_exception_is_retrieved_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.helpers.bg import BgHelper

    emitted = asyncio.Event()
    handler = _SignalHandler(emitted)
    logger = logging.getLogger("RSStT.helpers.bg")

    async def fail_in_background() -> None:
        raise RuntimeError("characterized background failure")

    helper: BgHelper[[], None] = BgHelper(fail_in_background)
    helper.init_sync(asyncio.get_running_loop())
    logger.addHandler(handler)
    try:
        with caplog.at_level(logging.ERROR, logger="RSStT.helpers.bg"):
            helper.bg_sync()
            await asyncio.wait_for(emitted.wait(), timeout=1)

        matching = [
            record
            for record in caplog.records
            if record.name == "RSStT.helpers.bg"
            and "Traceback of uncaught exception" in record.getMessage()
        ]
        assert len(matching) == 1
        assert matching[0].exc_info is not None
        assert matching[0].exc_info[0] is RuntimeError
        assert str(matching[0].exc_info[1]) == "characterized background failure"
    finally:
        logger.removeHandler(handler)
        await helper.close()


@pytest.mark.unit
async def test_background_close_cancels_and_awaits_remaining_task() -> None:
    from src.helpers.bg import BgHelper

    started = asyncio.Event()
    cancellation_finished = asyncio.Event()
    blocker = asyncio.Event()

    async def wait_forever() -> None:
        started.set()
        try:
            await blocker.wait()
        finally:
            cancellation_finished.set()

    helper: BgHelper[[], None] = BgHelper(wait_forever)
    helper.init_sync(asyncio.get_running_loop())
    helper.bg_sync()
    await started.wait()

    await helper.close()

    assert cancellation_finished.is_set()
