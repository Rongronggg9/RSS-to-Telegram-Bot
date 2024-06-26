from typing import Callable, Awaitable, Generic, TypeVar, Optional
from typing_extensions import ParamSpec

import contextlib
from collections import deque

from ._exceptions import StopPipeline

P = ParamSpec('P')
R = TypeVar('R')


def noop(*_, **__):
    pass


class SameFuncPipelineContextManager(contextlib.AbstractAsyncContextManager, Generic[P, R]):
    def __init__(
            self,
            func: Callable[P, Awaitable[R]],
            on_success: Callable[[R, P], None] = noop,
            on_error: Callable[[Exception, P], None] = noop,
    ):
        """
        A context manager that serializes the execution of the same function with different arguments.

        The ``StopPipeline`` exception can be raised to stop the pipeline. While other exceptions will be caught and
        passed to the ``on_error`` callback, without interrupting the pipeline. Wrapping an exception with
        ``StopPipeline`` will result in the pipeline being stopped, and the wrapped exception being re-raised.

        :param func: Function to be serialized.
        :param on_success: Callback when the function is executed successfully.
        :param on_error: Callback when the function raises an exception.
        """
        self._func = func
        self._on_success = on_success
        self._on_error = on_error

        self._pending_arguments: deque[tuple[P.args, P.kwargs]] = deque()
        self._finished_cleanly: Optional[bool] = None

    def is_finished_cleanly(self) -> bool:
        if self._finished_cleanly is None:
            raise RuntimeError('The pipeline has not finished yet')
        return self._finished_cleanly

    def __call__(self, *args, **kwargs):
        self._pending_arguments.append((args, kwargs))

    # noinspection PyProtocol
    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            return

        func = self._func
        on_success = self._on_success
        on_error = self._on_error
        pending_arguments = self._pending_arguments
        finished_cleanly: bool = True
        try:
            while pending_arguments:
                args, kwargs = pending_arguments.popleft()
                try:
                    on_success(await func(*args, **kwargs), *args, **kwargs)
                except StopPipeline as e:
                    finished_cleanly = False
                    if e.exception is None:
                        return
                    raise e.exception from e
                except Exception as e:
                    finished_cleanly = False
                    on_error(e, *args, **kwargs)
        finally:
            self._finished_cleanly = finished_cleanly
