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
from typing import Callable, Literal, Awaitable, Union, Generic, TypeVar
from typing_extensions import ParamSpec

import asyncio
from functools import partial

from ._helper import QueuedHelper
from ..bg import BgDecorator

QueuedHelperT_co = TypeVar('QueuedHelperT_co', bound=QueuedHelper, covariant=True)
P = ParamSpec('P')
R = TypeVar('R')
QP = ParamSpec('QP')


class QueuedDecorator(BgDecorator[P, R, QueuedHelperT_co], Generic[P, R, QueuedHelperT_co, QP]):
    def __init__(
            self,
            queue_constructor: Callable[QP, asyncio.Queue] = asyncio.Queue,
            _bound_helper_cls: type[QueuedHelperT_co] = QueuedHelper
    ):
        super().__init__(_bound_helper_cls=_bound_helper_cls)
        self._queue_constructor = queue_constructor
        self._helpers: list[QueuedHelperT_co]

    def __call__(
            self,
            func: Callable[P, Awaitable[R]] = None,
            *args: QP.args,
            maxsize: int = 0,
            default: Literal['queued', 'queued_nowait', 'bg', 'bg_sync', 'raw'] = 'queued',
            **kwargs: QP.kwargs,
    ) -> Callable[P, Union[Awaitable[R], Awaitable[None], None]]:
        """
        Make any call to the decorated function queued.

        Restrictions on methods:
        Though ``object.method()`` equals to ``object.__class__.method(object)``, ``object.method.whatever()`` equals to
        ``object.__class__.method.whatever()``.
        In the latter case, the object itself (``self``) is not passed to the method.
        Thus, never call ``object.method.whatever()`` directly, but to define a new method in the class body (e.g.,
        ``method_nowait = method.queued_nowait``) and call ``object.method_nowait()`` instead.

        There is no such restriction on functions. You can call ``function.whatever()`` directly.

        :param func: The function to be decorated.
        :param args: The positional arguments to be passed to the queue constructor.
        :param maxsize: The maximum number of items allowed in the queue.
        :param default: The default behavior of the decorated function.
        :param kwargs: The keyword arguments to be passed to the queue constructor.
        """
        if func is None:
            return partial(self, *args, maxsize=maxsize, default=default, **kwargs)

        kwargs['maxsize'] = maxsize
        self._helpers.append(helper := self._bound_helper_cls(func, self._queue_constructor, *args, **kwargs))

        wrappers = self._create_wrappers(helper, func, ('queued_nowait_async', *helper.available_wrapped_methods))

        if maxsize <= 0:
            wrappers['queued'] = wrappers['queued_nowait_async']
        del wrappers['queued_nowait_async']

        return self._create_composite_wrapper(wrappers, default)
