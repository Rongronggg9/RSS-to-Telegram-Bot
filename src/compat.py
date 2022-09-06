"""Containing something makes the bot compatible with Python 3.7 ~ 3.10, ThreadPoolExecutor/ProcessPoolExecutor."""
from __future__ import annotations

import sys

_version_info = sys.version_info
if _version_info < (3, 7):
    raise RuntimeError("This bot requires Python 3.7 or later")

from typing import Callable

import functools

from aiohttp import ClientResponse
from bs4 import BeautifulSoup
from cachetools.keys import hashkey
from minify_html import minify as minify_html

try:
    from minify_html_onepass import minify as minify_html_onepass
except ImportError:
    minify_html_onepass = None

import ssl
from contextlib import AbstractContextManager, AbstractAsyncContextManager, suppress

# backport `contextlib.nullcontext` for Python 3.7 ~ 3.9
if _version_info[1] >= 10:
    # noinspection PyUnresolvedReferences
    from contextlib import nullcontext
else:
    # noinspection SpellCheckingInspection
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


# default cipher list in Python 3.9
_ciphers_py39 = (
    'TLS_AES_256_GCM_SHA384:'
    'TLS_CHACHA20_POLY1305_SHA256:'
    'TLS_AES_128_GCM_SHA256:'
    'ECDHE-ECDSA-AES256-GCM-SHA384:'
    'ECDHE-RSA-AES256-GCM-SHA384:'
    'ECDHE-ECDSA-AES128-GCM-SHA256:'
    'ECDHE-RSA-AES128-GCM-SHA256:'
    'ECDHE-ECDSA-CHACHA20-POLY1305:'
    'ECDHE-RSA-CHACHA20-POLY1305:'
    'ECDHE-ECDSA-AES256-SHA384:'
    'ECDHE-RSA-AES256-SHA384:'
    'ECDHE-ECDSA-AES128-SHA256:'
    'ECDHE-RSA-AES128-SHA256:'
    'DHE-RSA-AES256-GCM-SHA384:'
    'DHE-RSA-AES128-GCM-SHA256:'
    'DHE-RSA-AES256-SHA256:'
    'DHE-RSA-AES128-SHA256:'
    'DHE-RSA-CHACHA20-POLY1305:'
    'ECDHE-ECDSA-AES256-SHA:'
    'ECDHE-RSA-AES256-SHA:'
    'DHE-RSA-AES256-SHA:'
    'ECDHE-ECDSA-AES128-SHA:'
    'ECDHE-RSA-AES128-SHA:'
    'DHE-RSA-AES128-SHA:'
    'AES256-GCM-SHA384:'
    'AES128-GCM-SHA256:'
    'AES256-SHA256:'
    'AES128-SHA256:'
    'AES256-SHA:'
    'AES128-SHA'
)


def ssl_create_default_context():
    """`ssl.create_default_context`"""
    context = ssl.create_default_context()
    if _version_info[1] >= 10:  # However, TLSv1.1 still not enabled
        context.set_ciphers(_ciphers_py39)
    return context


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
            _version_info[1] < 8  # minify-html >0.6.10 requires Python 3.8+
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
