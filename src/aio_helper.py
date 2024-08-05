"""
Asyncio helper functions.
"""
#  RSS to Telegram Bot
#  Copyright (C) 2022-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from typing import Callable, Optional
from typing_extensions import Literal

import os
from functools import partial
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, Future
from time import sleep
from signal import signal, SIGINT, SIGTERM
from collections import deque
from multiprocessing import get_context, current_process

from . import env, log

MP_CTX = get_context()

CPU_COUNT = os.cpu_count()
AVAIL_CPU_COUNT = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else CPU_COUNT
PROCESS_COUNT = min(AVAIL_CPU_COUNT, 3) if env.MULTIPROCESSING else 1

# Though multithreading in CPython cannot improve performance due to GIL, having more threads is still useful for
# improving responsiveness under high loads.
# TODO: consider using a PriorityQueue to prioritize tasks from interactive operations.
THREAD_POOL_WEIGHT = 2
PROCESS_POOL_WEIGHT = PROCESS_COUNT - 1

POOL_TYPE = Literal['thread', 'process']

assert min(CPU_COUNT, AVAIL_CPU_COUNT, PROCESS_COUNT) > 0
assert min(THREAD_POOL_WEIGHT, PROCESS_POOL_WEIGHT) >= 0

aioThreadExecutor: Optional[ThreadPoolExecutor] = None
aioProcessExecutor: Optional[ProcessPoolExecutor] = None
__aioExecutorsDeque: Optional[deque] = None

logger = log.getLogger('RSStT.aio_helper')


def _process_exit(_signum, _frame):
    exit(1)


def _common_initializer():
    if hasattr(os, 'nice'):
        try:
            niceness = os.nice(env.EXECUTOR_NICENESS_INCREMENT)
        except Exception as e:
            logger.warning('Failed to nice subprocess/thread', exc_info=e)
        else:
            logger.debug(f'The niceness of the subprocess/thread has been set to {niceness}')
    elif env.EXECUTOR_NICENESS_INCREMENT:
        logger.warning('The current platform does not support nice(), ignoring EXECUTOR_NICENESS_INCREMENT')
    logger.debug('Subprocess/thread initialized')


def _process_initializer():
    signal(SIGINT, _process_exit)
    signal(SIGTERM, _process_exit)
    _common_initializer()


def init():
    global aioThreadExecutor, aioProcessExecutor, __aioExecutorsDeque

    if current_process().name != 'MainProcess':
        return  # avoid re-initialization in subprocesses

    # asyncio executors
    aioThreadExecutor = ThreadPoolExecutor(
        max_workers=THREAD_POOL_WEIGHT,
        thread_name_prefix="rsstt_aio_thread_",
        initializer=_common_initializer
    ) if THREAD_POOL_WEIGHT else None
    aioProcessExecutor = ProcessPoolExecutor(
        max_workers=PROCESS_POOL_WEIGHT,
        mp_context=MP_CTX,
        initializer=_process_initializer
    ) if PROCESS_POOL_WEIGHT else None

    __aioExecutorsDeque = deque(
        (
            *((aioThreadExecutor,) * THREAD_POOL_WEIGHT),
            *((aioProcessExecutor,) * PROCESS_POOL_WEIGHT),
        )
    ) if aioThreadExecutor and aioProcessExecutor else None

    if env.EXECUTOR_NICENESS_INCREMENT < 0:
        logger.warning('Lowering the niceness of subprocesses/threads may impact the performance of the main process')

    # initialize all subprocesses/threads now
    # here we use sleep to ensure all subprocesses/threads are launched
    futures: list[Future] = []
    if aioProcessExecutor and type(MP_CTX).__name__ == 'ForkContext':
        futures.extend(aioProcessExecutor.submit(sleep, 0.01 * (i + 1)) for i in range(PROCESS_POOL_WEIGHT * 2))
    if aioThreadExecutor:
        futures.extend(aioThreadExecutor.submit(sleep, 0.01 * (i + 1)) for i in range(THREAD_POOL_WEIGHT * 2))
    for future in futures:
        future.result()  # wait for subprocesses/threads


def _get_executor():
    if not __aioExecutorsDeque:
        return aioThreadExecutor or aioProcessExecutor
    chosen_executor = __aioExecutorsDeque[0]
    __aioExecutorsDeque.rotate(1)
    return chosen_executor


async def run_async(func: Callable, *args, prefer_pool: POOL_TYPE = None, **kwargs):
    """
    Run a CPU-consuming function asynchronously.
    """
    rotate_deque_flag = False
    if prefer_pool == 'thread':
        executor = aioThreadExecutor or aioProcessExecutor
        rotate_deque_flag = True
    elif prefer_pool == 'process':
        executor = aioProcessExecutor or aioThreadExecutor
        rotate_deque_flag = True
    else:
        executor = _get_executor()

    if rotate_deque_flag and __aioExecutorsDeque and executor is __aioExecutorsDeque[0]:
        __aioExecutorsDeque.rotate(1)

    return (
        await env.loop.run_in_executor(executor, partial(func, *args, **kwargs))
        if kwargs else
        await env.loop.run_in_executor(executor, func, *args)
    )


def shutdown():
    if aioProcessExecutor:
        aioProcessExecutor.shutdown(wait=True)
    if aioProcessExecutor:
        aioThreadExecutor.shutdown(wait=False)
