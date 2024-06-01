from __future__ import annotations
from typing import Callable, Optional, Awaitable, Any, Union, Generic, TypeVar
from typing_extensions import ParamSpec

import asyncio
from functools import partial

from ._common import logger

P = ParamSpec('P')
R = TypeVar('R')
QP = ParamSpec('QP')


class QueuedHelper(Generic[P, R, QP]):
    def __init__(
            self,
            func: Callable[P, Awaitable[R]],
            queue_constructor: Callable[QP, asyncio.Queue],
            *args: QP.args,
            **kwargs: QP.kwargs,
    ):
        self._func = func
        self._name = func.__qualname__
        self._queue_constructor = partial(queue_constructor, *args, **kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[
            Union[
                tuple[tuple[Any], dict[Any]],
                tuple[None, None]
            ]
        ]] = None
        self._bg_task: Optional[asyncio.Task] = None

    # noinspection PyAsyncCall
    async def _consumer_bg(self):
        while True:
            try:
                args, kwargs = await self._queue.get()
                # All producer methods always put (args: tuple[Any], kwargs: dict[Any]) into the queue.
                # Only self.close() or self.close_sync() puts (None, None) into the queue.
                if args is None:
                    break
                self._loop.create_task(
                    self._func(*args, **kwargs),
                    name=f'{self._name}-{self._loop.time()}'
                )
                # Release the references so that they can be garbage collected while waiting for the next task.
                del args, kwargs
            except Exception as e:
                logger.error(f"Error in {self._name}'s background task:", exc_info=e)

    def init_sync(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        if self._bg_task is not None and not self._bg_task.done():
            return
        self._queue = self._queue_constructor()
        self._bg_task = self._loop.create_task(
            self._consumer_bg(),
            name=f'QueuedWrapper-{self._name}-bg-task'
        )

    async def init(self, loop: asyncio.AbstractEventLoop):
        self.init_sync(loop)

    def close_sync(self) -> bool:
        # This won't cancel tasks put into the queue,
        # but that's fine since asyncio will cancel them and print traceback when exiting.
        if self._bg_task is None or self._bg_task.done():
            return False
        try:
            if self._queue.empty():
                self._queue.put_nowait((None, None))  # gracefully stop the bg_task
                return True
            # The queue is not empty, just cancel the bg_task to prevent it from consuming more.
            return self._bg_task.cancel()
        except Exception as e:
            logger.error(f"Failed to terminate {self._name}'s background task of :", exc_info=e)
            return False  # cannot cancel the task, just return

    async def close(self):
        canceled = self.close_sync()
        if canceled:
            try:
                await self._bg_task
            except Exception as e:
                logger.error(f"Traceback of {self._name}'s background task termination:", exc_info=e)

    # ----- start producer methods -----

    # This returns a coroutine!
    def queued(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[None]:
        return self._queue.put((args, kwargs))

    # This is intended to be used with maxsize=0
    async def queued_nowait_async(self, *args: P.args, **kwargs: P.kwargs) -> None:
        self._queue.put_nowait((args, kwargs))

    def queued_nowait(self, *args: P.args, **kwargs: P.kwargs) -> None:
        self._queue.put_nowait((args, kwargs))

    def raw(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[R]:
        return self._func(*args, **kwargs)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Union[Awaitable[R], Awaitable[None], None]:
        raise NotImplementedError
