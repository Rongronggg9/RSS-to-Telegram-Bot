from __future__ import annotations
from typing import Callable, Optional, Awaitable, Union, Generic, TypeVar, Final, ClassVar
from typing_extensions import ParamSpec

import asyncio

from ._common import logger as bg_logger

P = ParamSpec('P')
R = TypeVar('R')


class BgHelper(Generic[P, R]):
    _logger: ClassVar = bg_logger

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
                await task
            except BaseException as e:  # also catches CancelledError
                logger.error(f"Traceback of the termination of {task}:", exc_info=e)
            finally:
                # The done callback may not be called now.
                # Manually discard it from bg_tasks so that it won't lead to unnecessary logs.
                bg_tasks.discard(task)
        if bg_tasks:
            logger.warning(
                f'{self._name} has {len(bg_tasks)} unfinished background tasks left:\n' +
                "\n".join(str(task) for task in bg_tasks)
            )

    # ----- start wrapped methods -----

    def bg_sync(self, *args: P.args, **kwargs: P.kwargs) -> None:
        loop = self._loop
        bg_tasks = self._bg_tasks
        task = loop.create_task(
            self._func(*args, **kwargs),
            name=f'{self._name}-{loop.time()}'
        )
        bg_tasks.add(task)
        task.add_done_callback(bg_tasks.discard)

    async def bg(self, *args: P.args, **kwargs: P.kwargs) -> None:
        return self.bg_sync(*args, **kwargs)

    def raw(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[R]:
        return self._func(*args, **kwargs)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Union[Awaitable[R], Awaitable[None], None]:
        raise NotImplementedError
