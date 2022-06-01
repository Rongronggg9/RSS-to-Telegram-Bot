"""
Asyncio helper functions.
"""
from __future__ import annotations
from typing import Callable, Union

import os
from functools import partial
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from time import sleep
from signal import signal, SIGINT, SIGTERM

from . import env

CPU_COUNT = os.cpu_count()
AVAIL_CPU_COUNT = len(os.sched_getaffinity(0))
PROCESS_COUNT = 1 if env.NO_MULTIPROCESSING else min(AVAIL_CPU_COUNT, 3)

# Asyncio executor. Either a thread pool or a process pool.
aioExecutor = (
    ThreadPoolExecutor(max_workers=1)
    if PROCESS_COUNT == 1
    else ProcessPoolExecutor(max_workers=PROCESS_COUNT - 1,
                             initializer=lambda: (
                                     signal(SIGINT, lambda *_, **__: exit(1))
                                     and
                                     signal(SIGTERM, lambda *_, **__: exit(1))
                             ))
)


async def run_async_on_demand(func: Callable, *args, condition: Union[Callable, bool] = None, **kwargs):
    return (
        await run_async(func, *args, **kwargs)
        if condition and (condition is True or condition(*args, **kwargs)) else
        func(*args, **kwargs)
    )


async def run_async(func: Callable, *args, **kwargs):
    """
    Run a CPU-consuming function asynchronously.
    """
    return (
        await env.loop.run_in_executor(aioExecutor, partial(func, *args, **kwargs))
        if kwargs else
        await env.loop.run_in_executor(aioExecutor, func, *args)
    )


def init():
    if PROCESS_COUNT > 1:
        [aioExecutor.submit(sleep, 0.01 * (i + 1)) for i in range(PROCESS_COUNT - 1)]


def shutdown():
    aioExecutor.shutdown()
