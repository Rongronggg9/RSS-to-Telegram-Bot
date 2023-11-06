from __future__ import annotations

import sys

_version_info = sys.version_info
if _version_info < (3, 9):
    raise RuntimeError("This bot requires Python 3.9 or later")

from typing import Callable

import copy
import functools
import itertools
import listparser.opml
import listparser.common
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

# backport `contextlib.nullcontext` for Python 3.9
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


# Reuse SSLContext as aiohttp does:
# https://github.com/aio-libs/aiohttp/blob/b51610b93b2ae15c4062e3a1680a536ba5f4c5c4/aiohttp/connector.py#L906
@functools.lru_cache(None)
def ssl_create_default_context():
    """
    Python 3.10+ disabled some legacy cipher, while some websites still use them.
    The function will merge the default cipher list with the one from Python 3.9.
    Some distributions (e.g., Debian) set `PY_SSL_DEFAULT_CIPHERS=2` for Python 3.11+,
    effectively re-enabling all these legacy ciphers.
    So we can assume that re-enabling them is not a major security issue.
    """
    context = ssl.create_default_context()
    if _version_info[1] >= 10:  # Python 3.10+ also disabled TLS 1.1, here we only care about cipher
        py39_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # https://github.com/python/cpython/blob/50c21ad35372983680b44130be560d856c5f27ca/Modules/_ssl.c#L163
        py39_ctx.set_ciphers('DEFAULT:!aNULL:!eNULL:!MD5:!3DES:!DES:!RC4:!IDEA:!SEED:!aDSS:!SRP:!PSK')
        context.set_ciphers(':'.join(set(map(
            lambda cipher: cipher['name'],
            itertools.chain(py39_ctx.get_ciphers(), context.get_ciphers())
        ))))
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


class OpmlMixin(listparser.opml.OpmlMixin):
    """
    Monkey-patching `listparser.opml.OpmlMixin` to support `text` and `title_orig`
    https://github.com/kurtmckee/listparser/issues/71
    Copied and modified from
    https://github.com/kurtmckee/listparser/blob/1910c45232f679e63294c1bc1bcc1520a10b0383/src/listparser/opml.py#L20-L82
    """

    def start_opml_outline(self, attrs):
        url = None
        # Find an appropriate title in @text or @title (else empty)
        text = attrs.get('text', '').strip()
        title_orig = attrs.get('title', '').strip()
        title = text or title_orig

        # Search for the URL regardless of xmlUrl's case
        for k, v in attrs.items():
            if k.lower() == 'xmlurl':
                url = v.strip()
                break

        append_to = None

        # Determine whether the outline is a feed or subscription list
        if url is not None:
            # It's a feed
            append_to = 'feeds'
            if attrs.get('type', '').strip().lower() == 'source':
                # Actually, it's a subscription list!
                append_to = 'lists'
        elif attrs.get('type', '').lower() in ('link', 'include'):
            # It's a subscription list
            append_to = 'lists'
            url = attrs.get('url', '').strip()
        elif title:
            # Assume that this is a grouping node
            self.hierarchy.append(title)
            return
        # Look for an opportunity URL
        if not url and 'htmlurl' in (k.lower() for k in attrs.keys()):
            for k, v in attrs.items():
                if k.lower() == 'htmlurl':
                    url = v.strip()
            append_to = 'opportunities'
        if not url:
            # Maintain the hierarchy
            self.hierarchy.append('')
            return
        if url not in self.found_urls and append_to:
            # This is a brand new URL
            obj = listparser.common.SuperDict({'url': url, 'title': title, 'text': text, 'title_orig': title_orig})
            self.found_urls[url] = (append_to, obj)
            self.harvest[append_to].append(obj)
        else:
            obj = self.found_urls[url][1]

        # Handle categories and tags
        obj.setdefault('categories', [])
        if 'category' in attrs.keys():
            for i in attrs['category'].split(','):
                tmp = [j.strip() for j in i.split('/') if j.strip()]
                if tmp and tmp not in obj['categories']:
                    obj['categories'].append(tmp)
        # Copy the current hierarchy into `categories`
        if self.hierarchy and self.hierarchy not in obj['categories']:
            obj['categories'].append(copy.copy(self.hierarchy))
        # Copy all single-element `categories` into `tags`
        obj['tags'] = [i[0] for i in obj['categories'] if len(i) == 1]

        self.hierarchy.append('')


listparser.opml.OpmlMixin.start_opml_outline = OpmlMixin.start_opml_outline
