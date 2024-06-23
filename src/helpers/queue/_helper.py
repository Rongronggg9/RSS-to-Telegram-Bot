from __future__ import annotations
from typing import Callable, Optional, Awaitable, Any, Union, Generic, TypeVar, Final
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
        self._func: Final[Callable[P, Awaitable[R]]] = func
        self._name: Final[str] = f'{self.__class__.__name__}-{func.__qualname__}'
        self._queue_constructor: Final[Callable[[], asyncio.Queue]] = partial(queue_constructor, *args, **kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[
            Union[
                tuple[tuple[Any], dict[Any]],
                tuple[None, None]
            ]
        ]] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._bg_tasks: Final[set[asyncio.Task]] = set()

    # noinspection PyAsyncCall
    async def _consumer(self):
        # These attributes are accessed frequently and are constant during the lifetime of the instance.
        # Let's cache them to avoid the overhead of attribute access.
        func = self._func
        name = self._name
        queue = self._queue
        bg_tasks = self._bg_tasks
        create_task = self._loop.create_task
        time = self._loop.time

        while True:
            try:
                args, kwargs = await queue.get()
                # All producer methods always put (args: tuple[Any], kwargs: dict[Any]) into the queue.
                # Only self.close() or self.close_sync() puts (None, None) into the queue.
                if args is None:
                    break
                task = create_task(
                    func(*args, **kwargs),
                    name=f'{name}-{time()}'
                )
                bg_tasks.add(task)
                task.add_done_callback(bg_tasks.discard)
                # Release the references so that they can be garbage collected while waiting for the next task.
                del args, kwargs, task
            except Exception as e:  # does not catch CancelledError
                logger.error(f"Error in {name}'s consumer task:", exc_info=e)

    def init_sync(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        if self._consumer_task is not None and not self._consumer_task.done():
            return
        self._queue = self._queue_constructor()
        self._consumer_task = self._loop.create_task(
            self._consumer(),
            name=f'{self._name}-consumer'
        )

    async def init(self, loop: asyncio.AbstractEventLoop):
        self.init_sync(loop)

    def close_sync(self) -> tuple[bool, list[asyncio.Task]]:
        canceled_tasks = [
            task for task in self._bg_tasks
            if task.cancel()
        ]
        if self._consumer_task is None or self._consumer_task.done():
            return False, canceled_tasks
        try:
            if self._queue.empty():
                self._queue.put_nowait((None, None))  # gracefully stop the bg_task
                return True, canceled_tasks
            # The queue is not empty, just cancel the bg_task to prevent it from consuming more.
            return self._consumer_task.cancel(), canceled_tasks
        except Exception as e:
            logger.error(f"Failed to terminate {self._consumer_task}:", exc_info=e)
            return False, canceled_tasks  # cannot cancel the task, just return

    async def close(self):
        consumer_canceled, canceled_tasks = self.close_sync()
        if consumer_canceled and (task := self._consumer_task) is not None:
            try:
                await task
            except BaseException as e:  # also catches CancelledError
                logger.error(f"Traceback of the termination of {task}:", exc_info=e)
        for task in canceled_tasks:
            try:
                await task
            except BaseException as e:
                logger.error(f"Traceback of the termination of {task}:", exc_info=e)
        if self._bg_tasks:
            logger.warning(
                f'{self._name} has {len(self._bg_tasks)} unfinished background tasks left:\n' +
                "\n".join(str(task) for task in self._bg_tasks)
            )

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
