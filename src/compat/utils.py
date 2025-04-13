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
    # Fix malformed HTML, or else minify-html may produce infinite nesting elements, resulting in RecursionError or
    # unexpected format when the minified HTML is parsed later.
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
    preprocessed: bool = False
    if 'sr-only' in html:
        # Clear .sr-only elements first, otherwise minify-html cannot strip spaces around them.
        # Invalid closing tags are also fixed during the preprocessing, so we can skip minify-html-onepass.
        html = _parsing_utils_html_validator_minify_preprocess(html, True)
        preprocessed = True
    elif minify_html_onepass is not None:
        # This is a workaround for https://github.com/wilsonzlin/minify-html/issues/86#issuecomment-1237677552
        try:
            # The result has no use since minify-html-onepass v0.16.0+ does not switch to WHATWG-compliant behavior like
            # minify-html v0.16.0+.
            # See also:
            #   https://github.com/wilsonzlin/minify-html/issues/109
            #   https://github.com/wilsonzlin/minify-html/issues/234
            # Moreover, we need to pass some parameters to minify-html to tune its behavior, which is not supported by
            # minify-html-onepass.
            minify_html_onepass(html)
        except SyntaxError:
            pass
        else:
            # Happy path for valid HTML so that we can avoid unnecessary preprocessing.
            preprocessed = True

    if not preprocessed:
        # Fix invalid closing tags when minify_html_onepass() raised SyntaxError or when it is unavailable.
        html = _parsing_utils_html_validator_minify_preprocess(html, False)

    return minify_html(
        html,
        # These parameters are not necessary and are passed just in case.
        # The only necessary parameter is `allow_optimal_entities=False`, which is added in v0.16.0 and defaults to
        # False. There are also some optional but preferred parameters that become the defaults in v0.16.0+ as part of
        # the efforts to make the library more compliant with WHATWG specifications. Since we are using v0.16.0+, we
        # don't need to pass them explicitly.
        keep_closing_tags=True,
        keep_html_and_head_opening_tags=True,
        keep_input_type_text_attr=True,
    )


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
