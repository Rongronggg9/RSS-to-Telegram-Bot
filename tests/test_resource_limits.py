from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest


@pytest.mark.unit
async def test_gather_factories_is_lazy_bounded_and_ordered() -> None:
    from src.locks import gather_factories

    active = 0
    maximum_active = 0
    created: list[int] = []
    release = asyncio.Event()

    async def operation(value: int) -> int:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            await release.wait()
            return value
        finally:
            active -= 1

    def make_factory(value: int):
        def factory():
            created.append(value)
            return operation(value)

        return factory

    factories = tuple(make_factory(value) for value in range(6))
    task = asyncio.create_task(gather_factories(factories, 2))
    try:
        while maximum_active < 2:
            await asyncio.sleep(0)

        assert maximum_active == 2
        assert active == 2
        assert created == [0, 1]

        release.set()
        assert await task == tuple(range(6))
        assert created == list(range(6))
        assert maximum_active == 2
    finally:
        release.set()
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.unit
async def test_timed_out_lease_remains_held_until_underlying_work_finishes() -> None:
    from src.locks import run_with_lease

    semaphore = asyncio.Semaphore(1)
    operation_started = asyncio.Event()
    operation_release = asyncio.Event()
    operation_settled = asyncio.Event()
    contender_attempted = asyncio.Event()
    contender_admitted = asyncio.Event()
    contender_release = asyncio.Event()
    underlying_task: asyncio.Task[str] | None = None
    contender_task: asyncio.Task[None] | None = None

    async def operation() -> str:
        nonlocal underlying_task
        current_task = asyncio.current_task()
        assert current_task is not None
        underlying_task = current_task
        operation_started.set()
        try:
            await operation_release.wait()
            return "settled"
        finally:
            operation_settled.set()

    async def contend() -> None:
        contender_attempted.set()
        async with semaphore:
            contender_admitted.set()
            await contender_release.wait()

    try:
        with pytest.raises(TimeoutError):
            await run_with_lease(operation, semaphore, timeout=0)
        await operation_started.wait()

        assert semaphore.locked()
        contender_task = asyncio.create_task(contend())
        await contender_attempted.wait()
        await asyncio.sleep(0)
        assert not contender_admitted.is_set()

        operation_release.set()
        await operation_settled.wait()
        await contender_admitted.wait()
        assert semaphore.locked()

        contender_release.set()
        await contender_task
        assert not semaphore.locked()
    finally:
        operation_release.set()
        contender_release.set()
        for task in (contender_task, underlying_task):
            if task is None:
                continue
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@pytest.mark.unit
async def test_run_with_lease_accepts_scheduled_task_and_holds_lease_until_settlement() -> None:
    from src.locks import run_with_lease

    semaphore = asyncio.Semaphore(1)
    factory_called = asyncio.Event()
    operation_started = asyncio.Event()
    operation_release = asyncio.Event()
    operation_settled = asyncio.Event()
    contender_attempted = asyncio.Event()
    contender_admitted = asyncio.Event()
    contender_release = asyncio.Event()
    factory_had_lease = False
    underlying_task: asyncio.Task[str] | None = None
    lease_task: asyncio.Task[str] | None = None
    contender_task: asyncio.Task[None] | None = None

    async def operation() -> str:
        operation_started.set()
        try:
            await operation_release.wait()
            return "settled"
        finally:
            operation_settled.set()

    def factory() -> asyncio.Task[str]:
        nonlocal factory_had_lease, underlying_task
        factory_had_lease = semaphore.locked()
        underlying_task = asyncio.create_task(operation())
        factory_called.set()
        return underlying_task

    async def contend() -> None:
        contender_attempted.set()
        async with semaphore:
            contender_admitted.set()
            await contender_release.wait()

    try:
        lease_task = asyncio.create_task(run_with_lease(factory, semaphore))
        await factory_called.wait()
        await asyncio.sleep(0)

        assert factory_had_lease
        if lease_task.done():
            await lease_task

        await operation_started.wait()
        assert semaphore.locked()
        contender_task = asyncio.create_task(contend())
        await contender_attempted.wait()
        await asyncio.sleep(0)
        assert not contender_admitted.is_set()

        operation_release.set()
        await operation_settled.wait()
        assert await lease_task == "settled"
        await contender_admitted.wait()
        assert semaphore.locked()

        contender_release.set()
        await contender_task
        assert not semaphore.locked()
    finally:
        operation_release.set()
        contender_release.set()
        for task in (contender_task, underlying_task, lease_task):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
