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
from typing import Callable, Optional, Awaitable, Union, Generic, TypeVar, Final, ClassVar
from typing_extensions import ParamSpec

import asyncio

from ._common import logger as bg_logger

P = ParamSpec('P')
R = TypeVar('R')


class BgHelper(Generic[P, R]):
    _logger: ClassVar = bg_logger
    available_wrapped_methods: ClassVar[tuple[str, ...]] = (
        'bg',
        'bg_sync',
        'raw'
    )

    def __init__(
            self,
            func: Callable[P, Awaitable[R]],
    ):
        self._func: Final[Callable[P, Awaitable[R]]] = func
        self._name: Final[str] = f'{self.__class__.__name__}-{func.__qualname__}'
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bg_tasks: Final[set[asyncio.Task]] = set()

    def init_sync(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def init(self, loop: asyncio.AbstractEventLoop):
        self.init_sync(loop)

    def close_sync(self) -> list[asyncio.Task]:
        return [
            task for task in self._bg_tasks
            if task.cancel()
        ]

    async def close(self):
        logger = self._logger
        bg_tasks = self._bg_tasks
        for task in self.close_sync():
            try:
                # The done callback is NOT ALWAYS called RIGHT AFTER the task is awaited.
                # Remove the done callback and manually discard it from bg_tasks,
                # so that it won't lead to unnecessary logs.
                task.remove_done_callback(self._on_done)
                await task
            except (Exception, asyncio.CancelledError) as e:
                logger.error(f'Traceback of the termination of {task}:', exc_info=e)
            finally:
                bg_tasks.discard(task)
        if bg_tasks:
            logger.warning(
                f'{self._name} has {len(bg_tasks)} unfinished background tasks left:\n' +
                "\n".join(str(task) for task in bg_tasks)
            )

    def _on_done(self, task: asyncio.Task):
        self._bg_tasks.discard(task)
        try:
            task.result()
        except (Exception, asyncio.CancelledError) as e:
            self._logger.error(f'Traceback of uncaught exception in {task}:', exc_info=e)

    # ----- start wrapped methods -----

    def bg_sync(self, *args: P.args, **kwargs: P.kwargs) -> None:
        loop = self._loop
        task = loop.create_task(
            self._func(*args, **kwargs),
            name=f'{self._name}-{loop.time()}'
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._on_done)

    async def bg(self, *args: P.args, **kwargs: P.kwargs) -> None:
        return self.bg_sync(*args, **kwargs)

    def raw(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[R]:
        return self._func(*args, **kwargs)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Union[Awaitable[R], Awaitable[None], None]:
        raise NotImplementedError
