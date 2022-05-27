"""
Various pools.
"""
from __future__ import annotations
from typing import Optional

import os
from asyncio import AbstractEventLoop
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from time import sleep
from signal import signal, SIGINT

CPU_COUNT = os.cpu_count()
AVAIL_CPU_COUNT = len(os.sched_getaffinity(0))
PROCESS_COUNT = min(AVAIL_CPU_COUNT, 3)
LOOP: Optional[AbstractEventLoop] = None

del os

# Asyncio executor. Either a thread pool or a process pool.
aioExecutor = (
    ThreadPoolExecutor(max_workers=1)
    if PROCESS_COUNT == 1
    else ProcessPoolExecutor(max_workers=PROCESS_COUNT - 1,
                             initializer=lambda: signal(SIGINT, lambda *_, **__: exit(1)))
)


async def run_async(func, *args):
    """
    Run a CPU-consuming function asynchronously.
    """
    return await LOOP.run_in_executor(aioExecutor, func, *args)


def init(loop: AbstractEventLoop):
    global LOOP

    if CPU_COUNT > 1:
        [aioExecutor.submit(sleep, 0.01 * (i + 1)) for i in range(PROCESS_COUNT - 1)]

    LOOP = loop


def shutdown():
    aioExecutor.shutdown()
