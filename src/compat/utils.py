#  RSS to Telegram Bot
#  Copyright (C) 2022-2025  Rongrong <i@rong.moe>
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

import functools
import itertools
import ssl
import sys

from contextlib import AbstractAsyncContextManager, AbstractContextManager, suppress
from typing import Callable

from aiohttp import ClientResponse
from bs4 import BeautifulSoup
from cachetools.keys import hashkey
from minify_html import minify as minify_html
from typing_extensions import Final

try:
    from minify_html_onepass import minify as minify_html_onepass
except ImportError:
    minify_html_onepass = None

# all supported architectures are 64-bit, so the below constants will be a native int (efficient)
INT64_T_MAX: Final = 2 ** 63 - 1

# backport `contextlib.nullcontext` for Python 3.9
if sys.version_info[1] >= 10:
    # noinspection PyUnresolvedReferences
    from contextlib import nullcontext
else:
    class nullcontext(AbstractContextManager, AbstractAsyncContextManager):
        """Backported `contextlib.nullcontext` from Python 3.10"""

        def __init__(self, enter_result=None):
            self.enter_result = enter_result

        def __enter__(self):
            return self.enter_result

        def __exit__(self, *excinfo):
            pass

        async def __aenter__(self):
            return self.enter_result

        async def __aexit__(self, exc_type, exc_value, traceback):
            pass


class AiohttpUvloopTransportHotfix(AbstractAsyncContextManager):
    def __init__(self, response: ClientResponse):
        self.transport = response.connection and response.connection.transport

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self.transport:
            self.transport.abort()


# Python 3.10+ disabled some legacy cipher, while some websites still use them.
# The function will merge the default cipher list with the one from Python 3.9.
# Some distributions (e.g., Debian) set `PY_SSL_DEFAULT_CIPHERS=2` for Python 3.11+,
# effectively re-enabling all these legacy ciphers.
# So we can assume that re-enabling them is not a major security issue.
if sys.version_info[1] >= 10:
    def ssl_create_default_context():
        context = ssl.create_default_context()
        if sys.version_info[1] >= 10:  # Python 3.10+ also disabled TLS 1.1, here we only care about cipher
            py39_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            # https://github.com/python/cpython/blob/50c21ad35372983680b44130be560d856c5f27ca/Modules/_ssl.c#L163
            py39_ctx.set_ciphers('DEFAULT:!aNULL:!eNULL:!MD5:!3DES:!DES:!RC4:!IDEA:!SEED:!aDSS:!SRP:!PSK')
            context.set_ciphers(':'.join(set(map(
                lambda cipher: cipher['name'],
                itertools.chain(py39_ctx.get_ciphers(), context.get_ciphers())
            ))))
        return context
else:
    ssl_create_default_context = ssl.create_default_context


def _parsing_utils_html_validator_minify_preprocess(html: str, drop_sr_only: bool) -> str:
    # fix malformed HTML first, since minify-html is not so robust
    # (resulting in RecursionError or unexpected format while html_parser parsing the minified HTML)
    # https://github.com/wilsonzlin/minify-html/issues/86
    soup = BeautifulSoup(html, 'lxml')
    if drop_sr_only:
        for tag in soup.find_all(attrs={'class': 'sr-only'}):
            with suppress(ValueError, AttributeError):
                tag.decompose()
    html = str(soup)
    soup.decompose()
    return html


def parsing_utils_html_validator_minify(html: str) -> str:
    contains_sr_only = 'sr-only' in html
    preprocessed = False
    if (
            minify_html_onepass is None  # requires minify-html-onepass to workaround upstream issue
            or
            contains_sr_only  # clear sr-only first, otherwise minify-html cannot strip spaces around them
    ):
        html = _parsing_utils_html_validator_minify_preprocess(html, contains_sr_only)
        preprocessed = True

    if minify_html_onepass is not None:
        try:
            # workaround for https://github.com/wilsonzlin/minify-html/issues/86#issuecomment-1237677552
            # minify-html-onepass does not allow invalid closing tags
            return minify_html_onepass(html)
        except SyntaxError:
            if not preprocessed:
                html = _parsing_utils_html_validator_minify_preprocess(html, contains_sr_only)

    return minify_html(html)


def cached_async(cache, key=hashkey):
    """
    https://github.com/tkem/cachetools/commit/3f073633ed4f36f05b57838a3e5655e14d3e3524
    """

    def decorator(func):
        if cache is None:

            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

        else:

            async def wrapper(*args, **kwargs):
                k = key(*args, **kwargs)
                with suppress(KeyError):  # key not found
                    return cache[k]
                v = await func(*args, **kwargs)
                with suppress(ValueError):  # value too large
                    cache[k] = v
                return v

        return functools.update_wrapper(wrapper, func)

    return decorator


def bozo_exception_removal_wrapper(func: Callable, *args, **kwargs):
    """
    bozo_exception is un-pickle-able, preventing ret from returning from ProcessPoolExecutor, so remove it
    """
    ret = func(*args, **kwargs)

    if ret.get('bozo_exception'):
        del ret['bozo_exception']

    return ret
