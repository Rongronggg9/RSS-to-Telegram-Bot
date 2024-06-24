from typing import Any, Callable, Awaitable, Generic
from typing_extensions import ParamSpec

import contextlib
from collections import deque

P = ParamSpec('P')


class SameFuncPipelineContextManager(contextlib.AbstractAsyncContextManager, Generic[P]):
    def __init__(self, func: Callable[P, Awaitable[Any]]):
        self._func = func
        self._pending_arguments: deque[tuple[P.args, P.kwargs]] = deque()

    def __call__(self, *args, **kwargs):
        self._pending_arguments.append((args, kwargs))

    # noinspection PyProtocol
    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            return

        pending_arguments = self._pending_arguments
        func = self._func
        while pending_arguments:
            args, kwargs = pending_arguments.popleft()
            await func(*args, **kwargs)
