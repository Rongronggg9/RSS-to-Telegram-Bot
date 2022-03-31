"""
Shared locks.
"""
from __future__ import annotations
from typing import Union

import asyncio
from time import time
from collections import defaultdict
from functools import partial
from urllib.parse import urlparse

from . import log

_USER_LIKE = Union[int, str]

logger = log.getLogger('RSStT.locks')
logger.setLevel(log.logger_level_muted)


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


async def user_flood_wait(user: _USER_LIKE, seconds: int) -> bool:
    call_time = time()
    flood_lock = user_flood_lock(user)
    seconds = seconds + 1
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


# ----- web locks -----
_hostname_semaphore_bucket: defaultdict[str, asyncio.BoundedSemaphore] = defaultdict(
    partial(asyncio.BoundedSemaphore, 5))
overall_web_semaphore = asyncio.BoundedSemaphore(100)


def hostname_semaphore(url: str, parse: bool = True) -> asyncio.BoundedSemaphore:
    hostname = urlparse(url).hostname if parse else url
    return _hostname_semaphore_bucket[hostname]
