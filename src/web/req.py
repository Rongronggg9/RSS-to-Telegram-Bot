#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
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
from typing import Union, Optional, AnyStr
from typing_extensions import Final
from collections.abc import Callable

import re
import asyncio
import aiohttp
import aiohttp.hdrs
import aiohttp.helpers
from contextlib import suppress
from bs4 import BeautifulSoup
from aiohttp_socks import ProxyConnector
from dns.asyncresolver import resolve
from dns.exception import DNSException
from urllib.parse import urlparse
from socket import AF_INET, AF_INET6
from functools import partial
from asyncstdlib.functools import lru_cache

from .. import env, locks
from ..compat import nullcontext, ssl_create_default_context, AiohttpUvloopTransportHotfix
from ..aio_helper import run_async
from ..errors_collection import RetryInIpv4
from .utils import YummyCookieJar, WebResponse, proxy_filter, logger, sentinel

# Reuse SSLContext as aiohttp does:
# https://github.com/aio-libs/aiohttp/blob/f1e4213fb06634584f8d7a1eb90f5397736a18cc/aiohttp/connector.py#L959
__SSL_CONTEXT: Final = ssl_create_default_context() if env.VERIFY_TLS else False

DEFAULT_READ_BUFFER_SIZE: Final = 2 ** 16

PROXY: Final = env.R_PROXY.replace('socks5h', 'socks5').replace('sock4a', 'socks4') if env.R_PROXY else None

HEADER_TEMPLATE: Final = {
    'User-Agent': env.USER_AGENT,
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
}

EXCEPTIONS_SHOULD_RETRY: Final = (
    asyncio.TimeoutError,
    # aiohttp.ClientPayloadError,
    # aiohttp.ClientResponseError,
    # aiohttp.ClientConnectionError,
    aiohttp.ClientConnectorError,  # connection refused, etc
    aiohttp.ServerConnectionError,
    RetryInIpv4,
    TimeoutError,
    ConnectionError
)
STATUSES_SHOULD_RETRY_IN_IPV4: Final = {
    400,  # Bad Request (some feed providers return 400 for banned IPs)
    403,  # Forbidden
    429,  # Too Many Requests
    451,  # Unavailable For Legal Reasons
}
STATUSES_PERMANENT_REDIRECT: Final = {
    301,  # Moved Permanently
    308,  # Permanent Redirect
}

MAX_TRIES: Final = 2

contentDispositionFilenameParser = partial(re.compile(r'(?<=filename=")[^"]+(?=")').search, flags=re.I)


async def __norm_callback(response: aiohttp.ClientResponse, decode: bool = False, max_size: Optional[int] = None,
                          intended_content_type: Optional[str] = None) -> Optional[AnyStr]:
    content_type = response.headers.get('Content-Type')
    if not intended_content_type or not content_type or content_type.startswith(intended_content_type):
        body: Optional[bytes] = None
        if max_size is None:
            body = await response.read()
        elif max_size > 0:
            body = await response.content.read(max_size)
        if decode and body:
            xml_header = body.split(b'\n', 1)[0]
            if xml_header.startswith(b'<?xml') and b'?>' in xml_header and b'encoding' in xml_header:
                with suppress(LookupError, RuntimeError):
                    encoding = BeautifulSoup(xml_header, 'lxml-xml').original_encoding
                    return body.decode(encoding=encoding, errors='replace')
            try:
                encoding = response.get_encoding()
                return body.decode(encoding=encoding, errors='replace')
            except (LookupError, RuntimeError):
                return body.decode(encoding='utf-8', errors='replace')
        return body
    return None


async def request(
        method: str,
        url: str,
        timeout: Optional[float] = sentinel,
        semaphore: Union[bool, asyncio.Semaphore] = None,
        headers: Optional[dict] = None,
        decode: bool = False,
        max_size: Optional[int] = None,
        intended_content_type: Optional[str] = None,
        allow_redirects: bool = True,
) -> WebResponse:
    """
    :param method: HTTP method
    :param url: URL to fetch
    :param timeout: timeout in seconds
    :param semaphore: semaphore to use for limiting concurrent connections
    :param headers: headers to use
    :param decode: whether to decode the response body
    :param max_size: maximum size of the response body (in bytes), None=unlimited, 0=ignore response body
    :param intended_content_type: if specified, only return response if the content-type matches
    :param allow_redirects: whether to allow redirects
    :return: {url, content, headers, status}
    """
    return await _request(
        method=method, url=url,
        timeout=timeout, semaphore=semaphore, headers=headers, allow_redirects=allow_redirects,
        resp_callback=partial(__norm_callback,
                              decode=decode, max_size=max_size, intended_content_type=intended_content_type),
        read_bufsize=min(max_size, DEFAULT_READ_BUFFER_SIZE) if max_size is not None else DEFAULT_READ_BUFFER_SIZE,
        read_until_eof=max_size is None,
    )


async def _request(
        method: str,
        url: str,
        resp_callback: Callable,
        timeout: Optional[float] = sentinel,
        semaphore: Union[bool, asyncio.Semaphore] = None,
        headers: Optional[dict] = None,
        read_bufsize: int = DEFAULT_READ_BUFFER_SIZE,
        read_until_eof: bool = True,
        allow_redirects: bool = True,
) -> WebResponse:
    if timeout is sentinel:
        timeout = env.HTTP_TIMEOUT

    host = urlparse(url).hostname
    semaphore_to_use = locks.hostname_semaphore(host, parse=False) if semaphore in (None, True) \
        else (semaphore or nullcontext())

    # Happy Eyeballs, available since aiohttp 3.10, cause AssertionError when setting both proxy and socket family.
    # Make them mutually exclusive (proxy takes precedence) since it is always meaningless to set them together.
    # TODO: Is it time to deprecate IPV6_PRIOR and completely rely on Happy Eyeballs (RFC 8305)?
    use_proxy: bool = PROXY and proxy_filter(host, parse=False)
    socket_family = 0
    if env.IPV6_PRIOR and not use_proxy:
        try:
            if (
                    await asyncio.wait_for(resolve(host, 'AAAA', lifetime=1), 1.1)
            ).rrset:
                socket_family = AF_INET6
        except (DNSException, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.debug(f'Error occurred when querying {url} AAAA:', exc_info=e)

    _headers = HEADER_TEMPLATE.copy()
    if headers:
        _headers.update(headers)

    async def _fetch():
        async with aiohttp.ClientSession(
                connector=proxy_connector,
                headers=_headers,
                cookie_jar=YummyCookieJar()
        ) as session:
            async with session.request(
                    method,
                    url,
                    read_bufsize=read_bufsize,
                    read_until_eof=read_until_eof,
                    allow_redirects=allow_redirects,
            ) as response:
                async with AiohttpUvloopTransportHotfix(response):
                    status = response.status
                    content = await resp_callback(response) if status == 200 else None
        status_url_history = [(resp.status, resp.url) for resp in response.history]
        status_url_history.append((response.status, response.url))
        url_obj = status_url_history[0][1]
        for (status0, url_obj0), (status1, url_obj1) in zip(status_url_history, status_url_history[1:]):
            if not (status0 in STATUSES_PERMANENT_REDIRECT or url_obj0.with_scheme('https') == url_obj1):
                break  # fail fast
            url_obj = url_obj1  # permanent redirect, update url
        if auth_header := response.request_info.headers.get('Authorization'):
            auth = aiohttp.helpers.BasicAuth.decode(auth_header)
            url_obj = url_obj.with_user(auth.login or None).with_password(auth.password or None)
        return WebResponse(
            url=str(url_obj),
            ori_url=url,
            content=content,
            headers=response.headers,
            status=status,
            reason=response.reason
        )

    tries = 0
    retry_in_v4_flag = False
    max_tries = MAX_TRIES * (1 if socket_family == 0 else 2)
    while tries < max_tries:
        tries += 1

        if retry_in_v4_flag or tries > MAX_TRIES:
            socket_family = AF_INET
        proxy_connector = (
            ProxyConnector.from_url(PROXY, family=socket_family, ssl=__SSL_CONTEXT)
            if use_proxy
            else aiohttp.TCPConnector(family=socket_family, ssl=__SSL_CONTEXT)
        )

        try:
            async with semaphore_to_use:
                async with locks.overall_web_semaphore:
                    ret = await asyncio.wait_for(_fetch(), timeout)
                    if socket_family == AF_INET6 and tries < max_tries \
                            and ret.status in STATUSES_SHOULD_RETRY_IN_IPV4:
                        raise RetryInIpv4(ret.status, ret.reason)
                    return ret
        except EXCEPTIONS_SHOULD_RETRY as e:
            if isinstance(e, RetryInIpv4):
                retry_in_v4_flag = True
            elif socket_family == AF_INET6 and tries >= MAX_TRIES:
                retry_in_v4_flag = True
                err_msg = str(e).strip()
                e = RetryInIpv4(reason=f'{type(e).__name__}' + (f': {err_msg}' if err_msg else ''))
            elif tries >= MAX_TRIES:
                raise e
            err_msg = str(e).strip()
            logger.debug(f'Fetch failed ({type(e).__name__}' + (f': {err_msg}' if err_msg else '')
                         + f'), retrying: {url}')
            await asyncio.sleep(0.1)
            continue


_get = partial(_request, aiohttp.hdrs.METH_GET)
get = partial(request, aiohttp.hdrs.METH_GET)


@lru_cache(maxsize=256)
async def get_page_title(url: str, allow_hostname=True, allow_path: bool = False, allow_filename: bool = True) \
        -> Optional[str]:
    r = None
    # noinspection PyBroadException
    try:
        r = await get(url=url, decode=False, intended_content_type='text/html', max_size=2 * 1024)
        if r.status != 200 or not r.content:
            raise ValueError('not an HTML page')
        # if len(r.content) <= 27:  # len of `<html><head><title></title>`
        #     raise ValueError('invalid HTML')
        soup = await run_async(BeautifulSoup, r.content, 'lxml', prefer_pool='thread')
        title = soup.title.text
        return title.strip()
    except Exception:
        content_disposition = r.headers.get('Content-Disposition') if r else None
        filename_match = contentDispositionFilenameParser(content_disposition) if content_disposition else None
        if filename_match and allow_filename:
            return filename_match.group()
        url_parsed = urlparse(url)
        if allow_path:
            path = url_parsed.path
            return path.rsplit('/', 1)[-1] if path else None
        if allow_hostname:
            return url_parsed.hostname
