"""Containing something makes the bot compatible with Python 3.7 ~ 3.10, ThreadPoolExecutor/ProcessPoolExecutor."""
from __future__ import annotations
from typing import Callable

import sys
import functools

import telethon.helpers
from aiohttp import ClientResponse
from cachetools.keys import hashkey

_version_info = sys.version_info
if _version_info < (3, 7):
    raise RuntimeError("This bot requires Python 3.7 or later")

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


def apply_monkey_patches():
    def _telethon_helpers_strip_text(text, entities):
        """
        https://github.com/LonamiWebs/Telethon/blob/046e2cb605e4def4d38c2f0d665ea49babb90093/telethon/helpers.py#L65
        """
        if not entities:
            return text.strip()

        len_ori = len(text)
        text = text.lstrip()
        left_offset = len_ori - len(text)
        text = text.rstrip()
        len_final = len(text)

        for i in reversed(range(len(entities))):
            e = entities[i]
            if e.length == 0:
                del entities[i]
                continue

            if e.offset + e.length > left_offset:
                if e.offset >= left_offset:
                    e.offset -= left_offset
                else:
                    e.length = e.offset + e.length - left_offset
                    e.offset = 0
            else:
                del entities[i]
                continue

            if e.offset + e.length <= len_final:
                continue
            if e.offset >= len_final:
                del entities[i]
            else:
                e.length = len_final - e.offset

        return text

    telethon.helpers.strip_text = _telethon_helpers_strip_text
