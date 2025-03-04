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
from typing import Callable, Optional, Awaitable, Generic, TypeVar, Any, Union
from typing_extensions import ParamSpec

import asyncio
from contextlib import AbstractAsyncContextManager

P = ParamSpec('P')
R = TypeVar('R')


def noop(*_, **__):
    pass


class BatchTimeout(AbstractAsyncContextManager, Generic[P, R]):
    def __init__(
            self,
            func: Callable[P, Awaitable[R]],
            timeout: float,
            loop: asyncio.AbstractEventLoop = None,
            on_success: Callable[[R, P], None] = noop,
            on_canceled: Callable[[asyncio.CancelledError, P], None] = noop,
            on_error: Callable[[Exception, P], None] = noop,
            on_timeout: Callable[[asyncio.CancelledError, P], None] = noop,
            on_timeout_error: Callable[[Union[asyncio.CancelledError, Exception], P], None] = noop,
    ):
        """
        A context manager aims to solve these issues:

        * asyncio.timeout/wait_for() raises TimeoutError from CancelledError, which breaks some internal logic of some
          libraries (e.g., aiohttp), so we need to prevent TimeoutError from being raised in such a circumstance.

        * asyncio.wait() only returns when the timeout is reached or all tasks are done. Even if some tasks have long
          been done, they cannot be garbage collected until asyncio.wait() returns, which is inefficient and may cause
          memory leaks.

        * It is hard to distinguish TimeoutError raised by asyncio.timeout/wait_for() from the one raised by other
          routines.

        The mechanism of the context manager is quite straightforward:

        1. A queue is created along with the creation of the context manager.

        2. When the context manager is entered, it creates a timeout handle to put ``None`` into the queue after
           ``timeout`` seconds.

        3. Each call to the context manager creates a task with a done callback. The done callback will put the task
           into the queue once it is done.

        4. When the context manager is exited, it consumes the queue and calls registered callbacks accordingly. Once
           it encounters a ``None``, it cancels all remaining tasks and calls registered callbacks accordingly.

        :param func: Function to be batched.
        :param timeout: Timeout in seconds.
        :param loop: Event loop.
        :param on_success: Callback when a task is done successfully.
        :param on_canceled: Callback when a task is canceled.
        :param on_error: Callback when a task raises an exception.
        :param on_timeout: Callback when a task reaches the timeout.
        :param on_timeout_error: Callback when a task raises an exception after reaching the timeout.
        """
        self._func = func
        self._name = f'{self.__class__.__name__}-{func.__qualname__}'
        self._timeout = timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = loop or asyncio.get_running_loop()

        self._on_success = on_success
        self._on_canceled = on_canceled
        self._on_error = on_error
        self._on_timeout = on_timeout
        self._on_timeout_error = on_timeout_error

        # Unbounded, safe to use `{put,get}_nowait()`.
        self._done_queue: asyncio.Queue[Optional[asyncio.Task]] = asyncio.Queue()
        # The presence of timeout handle indicates that the timeout has not been reached or the context manager has not
        # been entered yet.
        self._timeout_handle: Optional[asyncio.TimerHandle] = None
        self._task_params_map: dict[asyncio.Task, tuple[P.args, P.kwargs]] = {}

    def _on_done(self, task: asyncio.Task):
        # Put the task into the done queue once it is done (if not timed out).
        if self._timeout_handle is not None:
            self._done_queue.put_nowait(task)

    def __call__(self, *args: P.args, _task_name_suffix: Any = '', **kwargs: P.kwargs) -> asyncio.Task:
        if self._timeout_handle is None:
            raise RuntimeError("The context manager has not been entered.")
        task = self._loop.create_task(
            self._func(*args, **kwargs),
            name=f'{self._name}-{self._loop.time()}-{_task_name_suffix}'
        )
        task.add_done_callback(self._on_done)
        self._task_params_map[task] = (args, kwargs)
        return task

    async def __aenter__(self):
        # Use None to indicate timeout.
        self._timeout_handle = self._loop.call_later(self._timeout, self._done_queue.put_nowait, None)
        return self

    # noinspection PyProtocol
    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            for task in self._task_params_map:
                task.cancel()
            # fall through to consume the queue and call registered callbacks accordingly

        # These attributes are accessed frequently and are constant.
        # Let's cache them to avoid the overhead of attribute access.
        task_params_map = self._task_params_map
        done_queue = self._done_queue
        on_success = self._on_success
        on_canceled = self._on_canceled
        on_error = self._on_error
        on_timeout = self._on_timeout
        on_timeout_error = self._on_timeout_error

        while task_params_map:
            task = await done_queue.get()  # wait for the next task to be done
            if task is None:
                # Oops, the timeout has been reached.
                # The handle should be done, just in case.
                self._timeout_handle.cancel()
                # Indicate that the timeout has been reached so that _on_done() does nothing.
                self._timeout_handle = None
                break
            args, kwargs = task_params_map.pop(task)  # pop the subtask and retrieve the feed
            try:
                # The task is guaranteed to be done here since it is put into the queue by the done callback.
                # Thus, no need to check `if task.done()` here.
                on_success(task.result(), *args, **kwargs)
            except asyncio.CancelledError as e:
                # Usually, this should not happen, but let's handle it for debugging purposes and prevent it from
                # breaking the whole context manager.
                on_canceled(e, *args, **kwargs)
            except Exception as e:
                on_error(e, *args, **kwargs)
            # Release references so that they can be garbage collected while waiting for the next task to be done.
            del task, args, kwargs
        else:
            # All tasks are done before the timeout is reached.
            self._timeout_handle.cancel()
            self._timeout_handle = None
            return

        # The below procedure should be fast, so we don't explicitly release any references.

        for task in task_params_map:
            # Cancel all remaining tasks together before awaiting any of them to ensure timely cancellation.
            task.cancel()
            # There could be several event loop iterations between `None` being put into the queue by the timeout_handle
            # and being consumed above. It is a chance that some tasks are done during this period. In such a case,
            # these tasks will not be canceled (cancelling a done task is a no-op), so...

        for task, (args, kwargs) in task_params_map.items():
            try:
                # If the cancellation really occurs, several event loop iterations are needed to actually cancel
                # the task, so we probably need to wait for the task to be canceled, preventing us from using
                # `task.result()` directly.
                on_success(await task, *args, **kwargs)
                # ...it may succeed...
            except asyncio.CancelledError as e:
                on_timeout(e, *args, **kwargs)
            except Exception as e:
                # ...or fail.
                on_timeout_error(e, *args, **kwargs)
