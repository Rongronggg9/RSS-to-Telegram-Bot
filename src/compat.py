"""Containing something make the bot compatible with Python 3.7 ~ 3.10"""
from __future__ import annotations

import sys
import functools

from cachetools.keys import hashkey

_version_info = sys.version_info
if not (_version_info[0] == 3 and _version_info[1] >= 7):
    raise RuntimeError("This bot requires Python 3.7 or later")

import ssl
from contextlib import AbstractContextManager, AbstractAsyncContextManager

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

        async def __aexit__(self, *excinfo):
            pass

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
                try:
                    return cache[k]
                except KeyError:
                    pass  # key not found
                v = await func(*args, **kwargs)
                try:
                    cache[k] = v
                except ValueError:
                    pass  # value too large
                return v

        return functools.update_wrapper(wrapper, func)

    return decorator
