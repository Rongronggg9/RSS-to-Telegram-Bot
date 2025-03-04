#  RSS to Telegram Bot
#  Copyright (C) 2024  Rongrong <i@rong.moe>
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
from typing import Callable, Optional, Awaitable, Any, Union, Generic, TypeVar, Final, ClassVar
from typing_extensions import ParamSpec

import asyncio
from functools import partial

from ._common import logger as queue_logger
from ..bg import BgHelper

P = ParamSpec('P')
R = TypeVar('R')
QP = ParamSpec('QP')


class QueuedHelper(BgHelper[P, R], Generic[P, R, QP]):
    _logger: ClassVar = queue_logger
    available_wrapped_methods: ClassVar[tuple[str, ...]] = (
        'queued',
        'queued_nowait',
        *BgHelper.available_wrapped_methods
    )

    def __init__(
            self,
            func: Callable[P, Awaitable[R]],
            queue_constructor: Callable[QP, asyncio.Queue],
            *args: QP.args,
            **kwargs: QP.kwargs,
    ):
        super().__init__(func)
        self._queue_constructor: Final[Callable[[], asyncio.Queue]] = partial(queue_constructor, *args, **kwargs)
        self._queue: Optional[asyncio.Queue[
            Union[
                tuple[tuple[Any], dict[Any]],
                tuple[None, None]
            ]
        ]] = None
        self._consumer_task: Optional[asyncio.Task] = None

    # noinspection PyAsyncCall
    async def _consumer(self):
        # These attributes are accessed frequently and are constant during the lifetime of the instance.
        # Let's cache them to avoid the overhead of attribute access.
        name = self._name
        queue = self._queue
        bg_sync = self.bg_sync

        while True:
            try:
                args, kwargs = await queue.get()
                # All producer methods always put (args: tuple[Any], kwargs: dict[Any]) into the queue.
                # Only self.close() or self.close_sync() puts (None, None) into the queue.
                if args is None:
                    break
                bg_sync(*args, **kwargs)
                # Release the references so that they can be garbage collected while waiting for the next task.
                del args, kwargs
            except Exception as e:  # does not catch CancelledError
                self._logger.error(f"Error in {name}'s consumer task:", exc_info=e)

    def init_sync(self, loop: asyncio.AbstractEventLoop):
        super().init_sync(loop)
        if self._consumer_task is not None and not self._consumer_task.done():
            return
        self._queue = self._queue_constructor()
        self._consumer_task = self._loop.create_task(
            self._consumer(),
            name=f'{self._name}-consumer'
        )

    def close_sync(self) -> list[asyncio.Task]:
        canceled_tasks = super().close_sync()

        consumer_task = self._consumer_task
        if consumer_task is None:
            pass  # fall through
        elif consumer_task.cancelled():
            # The consumer task has been canceled somehow, return it so that the caller can handle it.
            canceled_tasks.append(consumer_task)
        elif consumer_task.done():
            # NOTE: Future.cancelled() == True implies Future.done() == True.
            pass  # fall through
        elif not self._queue.empty():
            # The queue is not empty, so cancel the consumer task to prevent it from consuming more tasks.
            if consumer_task.cancel():
                # NOTE: Future.cancel() returns False if the future is already done.
                canceled_tasks.append(consumer_task)
        else:
            try:
                # Gracefully stop the consumer task so that we don't need to return it to the caller.
                self._queue.put_nowait((None, None))
            except Exception as e:
                self._logger.error(f"Failed to gracefully stop {consumer_task}:", exc_info=e)
                if consumer_task.cancel():
                    canceled_tasks.append(consumer_task)

        return canceled_tasks  # cannot cancel the consumer task, just return

    # ----- start wrapped methods -----

    # This returns a coroutine!
    def queued(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[None]:
        return self._queue.put((args, kwargs))

    # This is intended to be used with maxsize=0
    async def queued_nowait_async(self, *args: P.args, **kwargs: P.kwargs) -> None:
        self._queue.put_nowait((args, kwargs))

    def queued_nowait(self, *args: P.args, **kwargs: P.kwargs) -> None:
        self._queue.put_nowait((args, kwargs))
