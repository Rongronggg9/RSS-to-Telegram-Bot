from __future__ import annotations
from typing import Callable, Optional, Literal, Awaitable, Union, Generic, TypeVar, ClassVar
from typing_extensions import ParamSpec

import asyncio
from functools import partial, wraps

from ._helper import BgHelper

P = ParamSpec('P')
R = TypeVar('R')


class BgDecorator(Generic[P, R]):
    _bound_helper: ClassVar[type[BgHelper]] = BgHelper

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._helpers: list[BgHelper] = []

    def init_sync(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        for helpers in self._helpers:
            helpers.init(loop=loop)

    async def init(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        await asyncio.gather(*(helper.init(loop=loop) for helper in self._helpers))

    def close_sync(self):
        for helper in self._helpers:
            helper.close_sync()

    async def close(self):
        await asyncio.gather(*(helper.close() for helper in self._helpers))

    @staticmethod
    def _create_wrappers(
            helper: BgHelper,
            func: Callable[P, Awaitable[R]],
            available_wrapped_methods: tuple[str, ...],
    ) -> dict[str, Union[Callable[P, Awaitable[R]], Callable[P, Awaitable[None]], Callable[P, None]]]:
        # Here we must create wrappers instead of just returning helper.
        # The methods from helper are so-called "bound methods" with `self` bounded, preventing the `self` of wrapped
        # methods from being passed.
        wraps_factory = wraps(func)

        def wrapper_factory(f):
            return wraps_factory(lambda *_args, **_kwargs: f(*_args, **_kwargs))

        return {
            wrapper_name: wrapper_factory(getattr(helper, wrapper_name))
            for wrapper_name in available_wrapped_methods
        }

    @staticmethod
    def _create_composite_wrapper(
            wrappers: dict[str, Callable],
            default: str,
    ):
        wrapper = wrappers[default]
        for wrapper_name in wrappers:
            setattr(wrapper, wrapper_name, wrappers[wrapper_name])

        return wrapper

    def __call__(
            self,
            func: Callable[P, Awaitable[R]] = None,
            default: Literal['bg', 'bg_sync', 'raw'] = 'bg',
    ) -> Callable[P, Union[Awaitable[R], Awaitable[None], None]]:
        """
        Make any call to the decorated function run in the background.

        Restrictions on methods:
        Though ``object.method()`` equals to ``object.__class__.method(object)``, ``object.method.whatever()`` equals to
        ``object.__class__.method.whatever()``.
        In the latter case, the object itself (``self``) is not passed to the method.
        Thus, never call ``object.method.whatever()`` directly, but to define a new method in the class body (e.g.,
        ``bg_sync = method.bg_sync``) and call ``object.bg_sync()`` instead.

        There is no such restriction on functions. You can call ``function.whatever()`` directly.

        :param func: The function to be decorated.
        :param default: The default behavior of the decorated function.
        """
        if func is None:
            return partial(self, default=default)

        self._helpers.append(helper := self._bound_helper(func))
        wrappers = self._create_wrappers(helper, func, helper.available_wrapped_methods)
        return self._create_composite_wrapper(wrappers, default)
