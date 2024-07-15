"""
Shared locks.
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
from typing import Union
from contextlib import AbstractAsyncContextManager

import asyncio
from time import time
from collections import defaultdict
from functools import partial
from urllib.parse import urlparse

from . import log, env
from .errors_collection import ContextTimeoutError
from .compat import nullcontext

_USER_LIKE = Union[int, str]

logger = log.getLogger('RSStT.locks')
logger.setLevel(log.logger_level_muted)


# ----- context with timeout -----
# noinspection PyProtocol
class ContextWithTimeout(AbstractAsyncContextManager):
    def __init__(self, context: AbstractAsyncContextManager, timeout: float):
        self.context = context
        self.timeout = timeout

    async def __aenter__(self):
        try:
            return await asyncio.wait_for(self.context.__aenter__(), self.timeout)
        except asyncio.TimeoutError as e:
            raise ContextTimeoutError from e

    async def __aexit__(self, *args, **kwargs):
        return await self.context.__aexit__(*args, **kwargs)


class ContextTimeoutManager:
    def __init__(self, timeout: float = None):
        self.call_time = time()
        self.timeout = timeout

    def __call__(self, context: AbstractAsyncContextManager, timeout: float = None):
        timeout = self.timeout if timeout is None else timeout
        if timeout is None:
            raise RuntimeError('`timeout` must be set either when creating the instance or in the call')
        curr_time = time()
        left_time = timeout - (curr_time - self.call_time)
        if left_time <= 0:
            raise ContextTimeoutError
        return ContextWithTimeout(context, left_time)


# ----- user locks -----

class _UserLockBucket:
    def __init__(self):
        self.msg_lock = asyncio.Lock()
        self.flood_lock = asyncio.Lock()
        self.media_upload_semaphore = asyncio.BoundedSemaphore(3)
        self.pending_callbacks = set()


_user_bucket: defaultdict[_USER_LIKE, _UserLockBucket] = defaultdict(_UserLockBucket)


def user_msg_lock(user: _USER_LIKE) -> asyncio.Lock:
    return _user_bucket[user].msg_lock


def user_flood_lock(user: _USER_LIKE) -> asyncio.Lock:
    return _user_bucket[user].flood_lock


def user_media_upload_semaphore(user: _USER_LIKE) -> asyncio.BoundedSemaphore:
    return _user_bucket[user].media_upload_semaphore


def user_msg_locks(user: _USER_LIKE) -> tuple[asyncio.Lock, asyncio.Lock]:
    """
    :return: user_msg_lock, user_flood_lock
    """
    return user_msg_lock(user), user_flood_lock(user)


def user_pending_callbacks(user: _USER_LIKE) -> set:
    return _user_bucket[user].pending_callbacks


async def user_flood_wait(user: _USER_LIKE, seconds: int, call_time: float = None) -> bool:
    if call_time is None:
        call_time = time()
    flood_lock = user_flood_lock(user)
    seconds += 1
    async with flood_lock:
        lock_got_time = time()
        time_left = seconds - (lock_got_time - call_time)
        if time_left > 0.1:
            logger.log(
                level=log.INFO if time_left < 120 else log.WARNING,
                msg=f'Blocking any further messages for {user} due to flood control, {time_left:0.2f}s left'
                    + (f' ({seconds}s requested)' if seconds - time_left > 5 else '')
            )
            await asyncio.sleep(time_left)
            return True
        logger.info(f'Skipped flood wait for {user} because the wait had been finished before the lock was acquired')
        return False


async def user_flood_wait_background(user: _USER_LIKE, seconds: int) -> asyncio.Task:
    task = env.loop.create_task(user_flood_wait(user=user, seconds=seconds, call_time=time()))
    await asyncio.sleep(1)  # allowing other tasks (especially the above one) to run.
    return task


# ----- web locks -----
overall_web_semaphore = (asyncio.BoundedSemaphore(env.HTTP_CONCURRENCY)
                         if env.HTTP_CONCURRENCY > 0
                         else nullcontext())

if env.HTTP_CONCURRENCY_PER_HOST > 0:
    _hostname_semaphore_bucket: defaultdict[str, asyncio.BoundedSemaphore] = \
        defaultdict(partial(asyncio.BoundedSemaphore, env.HTTP_CONCURRENCY_PER_HOST))


    def hostname_semaphore(url: str, parse: bool = True) -> asyncio.BoundedSemaphore:
        hostname = urlparse(url).hostname if parse else url
        return _hostname_semaphore_bucket[hostname]

else:
    _null_semaphore = nullcontext()


    def hostname_semaphore(*_, **__) -> nullcontext:
        return _null_semaphore
