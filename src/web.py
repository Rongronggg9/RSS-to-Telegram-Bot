from __future__ import annotations
from typing import Union, Optional, AnyStr
from typing_extensions import Final
from collections.abc import Callable
from .compat import nullcontext, ssl_create_default_context, AiohttpUvloopTransportHotfix

import re
import asyncio
import aiohttp
import feedparser
import PIL.Image
import PIL.ImageFile
from contextlib import suppress
from PIL import UnidentifiedImageError
from bs4 import BeautifulSoup
from io import BytesIO, SEEK_END
from aiohttp_socks import ProxyConnector
from dns.asyncresolver import resolve
from dns.exception import DNSException
from ssl import SSLError
from ipaddress import ip_network, ip_address
from urllib.parse import urlparse
from socket import AF_INET, AF_INET6
from multidict import CIMultiDictProxy
from attr import define
from functools import partial
from asyncstdlib.functools import lru_cache

from . import env, log, locks
from .compat import bozo_exception_removal_wrapper
from .aio_helper import run_async_on_demand
from .i18n import i18n
from .errors_collection import RetryInIpv4

SOI: Final = b'\xff\xd8'
EOI: Final = b'\xff\xd9'

IMAGE_MAX_FETCH_SIZE: Final = 1024 * (1 if env.TRAFFIC_SAVING else 5)
IMAGE_ITER_CHUNK_SIZE: Final = 128
IMAGE_READ_BUFFER_SIZE: Final = 1

DEFAULT_READ_BUFFER_SIZE: Final = 2 ** 16

PROXY: Final = env.R_PROXY.replace('socks5h', 'socks5').replace('sock4a', 'socks4') if env.R_PROXY else None
PRIVATE_NETWORKS: Final = tuple(ip_network(ip_block) for ip_block in
                                ('127.0.0.0/8', '::1/128',
                                 # loopback is not a private network, list in here for convenience
                                 '169.254.0.0/16', 'fe80::/10',  # link-local address
                                 '10.0.0.0/8',  # class A private network
                                 '172.16.0.0/12',  # class B private networks
                                 '192.168.0.0/16',  # class C private networks
                                 'fc00::/7',  # ULA
                                 ))

HEADER_TEMPLATE: Final = {
    'User-Agent': env.USER_AGENT,
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
}
FEED_ACCEPT: Final = 'application/rss+xml, application/rdf+xml, application/atom+xml, ' \
                     'application/xml;q=0.9, text/xml;q=0.8, text/*;q=0.7, application/*;q=0.6'

EXCEPTIONS_SHOULD_RETRY: Final = (asyncio.TimeoutError,
                                  # aiohttp.ClientPayloadError,
                                  # aiohttp.ClientResponseError,
                                  # aiohttp.ClientConnectionError,
                                  aiohttp.ClientConnectorError,  # connection refused, etc
                                  aiohttp.ServerConnectionError,
                                  RetryInIpv4,
                                  TimeoutError,
                                  ConnectionError)

MAX_TRIES: Final = 2

PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True

logger = log.getLogger('RSStT.web')

contentDispositionFilenameParser = partial(re.compile(r'(?<=filename=")[^"]+(?=")').search, flags=re.I)


class WebError(Exception):
    def __init__(self, error_name: str, status: Union[int, str] = None, url: str = None,
                 base_error: Exception = None, hide_base_error: bool = False, log_level: int = log.DEBUG):
        super().__init__(error_name)
        self.error_name = error_name
        self.status = status
        self.url = url
        self.base_error = base_error
        self.hide_base_error = hide_base_error
        log_msg = f'Fetch failed ({error_name}'
        log_msg += (f', {type(base_error).__name__}'
                    if not hide_base_error and base_error and log_level < log.ERROR
                    else '')
        log_msg += f', {status}' if status else ''
        log_msg += ')'
        log_msg += f': {url}' if url else ''
        logger.log(log_level,
                   log_msg,
                   exc_info=base_error if not hide_base_error and base_error and log_level >= log.ERROR else None)

    def i18n_message(self, lang: str = None) -> str:
        error_key = self.error_name.lower().replace(' ', '_')
        msg = f'ERROR: {i18n[lang][error_key]}'
        if not self.hide_base_error and self.base_error:
            msg += f' ({type(self.base_error).__name__})'
        if self.status:
            msg += f' ({self.status})'
        return msg

    def __str__(self) -> str:
        return self.i18n_message()


@define
class WebResponse:
    url: str  # redirected url
    ori_url: str  # original url
    content: Optional[AnyStr]
    headers: CIMultiDictProxy[str]
    status: int
    reason: Optional[str]


@define
class WebFeed:
    url: str  # redirected url
    ori_url: str  # original url
    content: Optional[AnyStr] = None
    headers: Optional[CIMultiDictProxy[str]] = None
    status: int = -1
    reason: Optional[str] = None
    rss_d: Optional[feedparser.FeedParserDict] = None
    error: Optional[WebError] = None


def proxy_filter(url: str, parse: bool = True) -> bool:
    if not (env.PROXY_BYPASS_PRIVATE or env.PROXY_BYPASS_DOMAINS):
        return True

    hostname = urlparse(url).hostname if parse else url
    if env.PROXY_BYPASS_PRIVATE:
        with suppress(ValueError):  # if not an IP, continue
            ip_a = ip_address(hostname)
            is_private = any(ip_a in network for network in PRIVATE_NETWORKS)
            if is_private:
                return False
    if env.PROXY_BYPASS_DOMAINS:
        is_bypassed = any(hostname.endswith(domain) and (hostname == domain or hostname[-len(domain) - 1] == '.')
                          for domain in env.PROXY_BYPASS_DOMAINS)
        if is_bypassed:
            return False
    return True


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


async def get(url: str, timeout: Optional[float] = None, semaphore: Union[bool, asyncio.Semaphore] = None,
              headers: Optional[dict] = None, decode: bool = False,
              max_size: Optional[int] = None, intended_content_type: Optional[str] = None) -> WebResponse:
    """
    :param url: URL to fetch
    :param timeout: timeout in seconds
    :param semaphore: semaphore to use for limiting concurrent connections
    :param headers: headers to use
    :param decode: whether to decode the response body
    :param max_size: maximum size of the response body (in bytes), None=unlimited, 0=ignore response body
    :param intended_content_type: if specified, only return response if the content-type matches
    :return: {url, content, headers, status}
    """
    if not timeout:
        timeout = 12
    return await _get(
        url=url, timeout=timeout, semaphore=semaphore, headers=headers,
        resp_callback=partial(__norm_callback,
                              decode=decode, max_size=max_size, intended_content_type=intended_content_type),
        read_bufsize=min(max_size, DEFAULT_READ_BUFFER_SIZE) if max_size is not None else DEFAULT_READ_BUFFER_SIZE,
        read_until_eof=max_size is None
    )


async def _get(url: str, resp_callback: Callable, timeout: Optional[float] = None,
               semaphore: Union[bool, asyncio.Semaphore] = None, headers: Optional[dict] = None,
               read_bufsize: int = DEFAULT_READ_BUFFER_SIZE, read_until_eof: bool = True) -> WebResponse:
    host = urlparse(url).hostname
    semaphore_to_use = locks.hostname_semaphore(host, parse=False) if semaphore in (None, True) \
        else (semaphore or nullcontext())
    v6_rr_set = None
    try:
        v6_rr_set = (await asyncio.wait_for(resolve(host, 'AAAA', lifetime=1), 1.1)).rrset if env.IPV6_PRIOR else None
    except DNSException:
        pass
    except asyncio.TimeoutError:
        pass
    except Exception as e:
        logger.debug(f'Error occurred when querying {url} AAAA:', exc_info=e)
    socket_family = AF_INET6 if v6_rr_set else 0

    _headers = HEADER_TEMPLATE.copy()
    if headers:
        _headers.update(headers)

    async def _fetch():
        async with aiohttp.ClientSession(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout),
                                         headers=_headers) as session:
            async with session.get(url, read_bufsize=read_bufsize, read_until_eof=read_until_eof) as response:
                async with AiohttpUvloopTransportHotfix(response):
                    status = response.status
                    content = await resp_callback(response) if status == 200 else None
                    return WebResponse(url=str(response.url),
                                       ori_url=url,
                                       content=content,
                                       headers=response.headers,
                                       status=status,
                                       reason=response.reason)

    tries = 0
    retry_in_v4_flag = False
    max_tries = MAX_TRIES * (1 if socket_family == 0 else 2)
    while tries < max_tries:
        tries += 1

        if retry_in_v4_flag or tries > MAX_TRIES:
            socket_family = AF_INET
        ssl_context = ssl_create_default_context()
        proxy_connector = (
            ProxyConnector.from_url(PROXY, family=socket_family, ssl=ssl_context)
            if (PROXY and proxy_filter(host, parse=False))
            else aiohttp.TCPConnector(family=socket_family, ssl=ssl_context)
        )

        try:
            async with semaphore_to_use:
                async with locks.overall_web_semaphore:
                    ret = await asyncio.wait_for(_fetch(), timeout + 0.1)
                    if socket_family == AF_INET6 and tries < max_tries \
                            and ret.status in {400,  # Bad Request (some feed providers return 400 for banned IPs)
                                               403,  # Forbidden
                                               429,  # Too Many Requests
                                               451}:  # Unavailable For Legal Reasons
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


async def feed_get(url: str, timeout: Optional[float] = None, web_semaphore: Union[bool, asyncio.Semaphore] = None,
                   headers: Optional[dict] = None, verbose: bool = True) -> WebFeed:
    ret = WebFeed(url=url, ori_url=url)

    log_level = log.WARNING if verbose else log.DEBUG
    _headers = {}
    if headers:
        _headers.update(headers)
    if 'Accept' not in _headers:
        _headers['Accept'] = FEED_ACCEPT

    try:
        resp = await get(url, timeout, web_semaphore, decode=False, headers=_headers)
        rss_content = resp.content
        ret.content = rss_content
        ret.url = resp.url
        ret.headers = resp.headers
        ret.status = resp.status

        # some rss feed implement http caching improperly :(
        if resp.status == 200 and int(resp.headers.get('Content-Length', '1')) == 0:
            ret.status = 304
            # ret.msg = f'"Content-Length" is 0'
            return ret

        if resp.status == 304:
            # ret.msg = f'304 Not Modified'
            return ret  # 304 Not Modified, feed not updated

        if rss_content is None:
            status_caption = f'{resp.status}' + (f' {resp.reason}' if resp.reason else '')
            ret.error = WebError(error_name='status code error', status=status_caption, url=url, log_level=log_level)
            return ret

        with BytesIO(rss_content) as rss_content_io:
            rss_d = await run_async_on_demand(
                partial(bozo_exception_removal_wrapper,
                        feedparser.parse, rss_content_io, sanitize_html=False,
                        response_headers={k.lower(): v for k, v in resp.headers.items()}),
                condition=len(rss_content) > 64 * 1024
            )

        if not rss_d.feed.get('title'):  # why there is no feed hospital?
            # feed.description cannot be used to determine if this is likely to be a feed since HTML tag <body> may be
            # considered to be the description of the "feed"
            if not rss_d.entries and (rss_d.bozo or not (rss_d.feed.get('link') or rss_d.feed.get('updated'))):
                ret.error = WebError(error_name='feed invalid', url=resp.url, log_level=log_level)
                return ret
            rss_d.feed['title'] = resp.url  # instead of `rss_d.feed.title = resp.url`, which does not affect the dict

        ret.rss_d = rss_d
    except aiohttp.InvalidURL:
        ret.error = WebError(error_name='URL invalid', url=url, log_level=log_level)
    except (asyncio.TimeoutError,
            aiohttp.ClientError,
            SSLError,
            OSError,
            ConnectionError,
            TimeoutError) as e:
        ret.error = WebError(error_name='network error', url=url, base_error=e, log_level=log_level)
    except Exception as e:
        ret.error = WebError(error_name='internal error', url=url, base_error=e, log_level=log.ERROR)

    return ret


async def __medium_info_callback(response: aiohttp.ClientResponse) -> tuple[int, int]:
    content_type = response.headers.get('Content-Type', '').lower()
    content_length = int(response.headers.get('Content-Length', '1024'))
    content = response.content
    preloaded_length = content.total_bytes  # part of response body already came with the response headers
    if not (  # hey, here is a `not`!
            # a non-webp-or-svg image
            (content_type.startswith('image') and all(keyword not in content_type for keyword in ('webp', 'svg')))
            or (
                    # an un-truncated webp image
                    any(keyword in content_type for keyword in ('webp', 'application'))
                    # PIL cannot handle a truncated webp image
                    and content_length <= max(preloaded_length, IMAGE_MAX_FETCH_SIZE)
            )
    ):
        return -1, -1
    is_jpeg = None
    already_read = 0
    eof_flag = False
    exit_flag = False
    with BytesIO() as buffer:
        while not exit_flag:
            curr_chunk_length = 0
            preloaded_length = content.total_bytes - already_read
            while preloaded_length > IMAGE_READ_BUFFER_SIZE or curr_chunk_length < IMAGE_ITER_CHUNK_SIZE:
                # get almost all preloaded bytes, but leaving some to avoid next automatic preloading
                chunk = await content.read(max(preloaded_length - IMAGE_READ_BUFFER_SIZE, IMAGE_READ_BUFFER_SIZE))
                if chunk == b'':  # EOF
                    eof_flag = True
                    break
                if is_jpeg is None:
                    is_jpeg = chunk.startswith(SOI)
                already_read += len(chunk)
                curr_chunk_length += len(chunk)
                buffer.seek(0, SEEK_END)
                buffer.write(chunk)
                preloaded_length = content.total_bytes - already_read

            if eof_flag or already_read >= IMAGE_MAX_FETCH_SIZE:
                response.close()  # immediately close the connection to block any incoming data or retransmission
                exit_flag = True

            # noinspection PyBroadException
            try:
                image = PIL.Image.open(buffer)
                width, height = image.size
                return width, height
            except UnidentifiedImageError:
                return -1, -1  # not a format that PIL can handle
            except Exception:
                if is_jpeg:
                    file_header = buffer.getvalue()
                    find_start_pos = 0
                    for _ in range(3):
                        pointer = -1
                        for marker in (b'\xff\xc2', b'\xff\xc1', b'\xff\xc0'):
                            p = file_header.find(marker, find_start_pos)
                            if p != -1:
                                pointer = p
                                break
                        if pointer != -1 and pointer + 9 <= len(file_header):
                            if file_header.count(EOI, 0, pointer) != file_header.count(SOI, 0, pointer) - 1:
                                # we are currently entering the thumbnail in Exif, bypassing...
                                # (why the specifications makers made Exif so freaky?)
                                eoi_pos = file_header.find(EOI, pointer)
                                if eoi_pos == -1:
                                    break  # no EOI found, we could never leave the thumbnail...
                                find_start_pos = eoi_pos + len(EOI)
                                continue
                            width = int(file_header[pointer + 7:pointer + 9].hex(), 16)
                            height = int(file_header[pointer + 5:pointer + 7].hex(), 16)
                            if min(width, height) <= 0:
                                find_start_pos = pointer + 1
                                continue
                            return width, height
                        break
    return -1, -1


@lru_cache(maxsize=1024)
async def get_medium_info(url: str) -> Optional[tuple[int, int, int, Optional[str]]]:
    if url.startswith('data:'):
        return None
    try:
        r = await _get(url, timeout=12, resp_callback=__medium_info_callback,
                       read_bufsize=IMAGE_READ_BUFFER_SIZE, read_until_eof=False)
        if r.status != 200:
            raise ValueError(f'status code is not 200, but {r.status}')
    except Exception as e:
        logger.debug(f'Medium fetch failed: {url}', exc_info=e)
        return None

    width, height = -1, -1
    size = int(r.headers.get('Content-Length') or -1)
    content_type = r.headers.get('Content-Type')
    if isinstance(r.content, tuple):
        width, height = r.content

    return size, width, height, content_type


@lru_cache(maxsize=256)
async def get_page_title(url: str, allow_hostname=True, allow_path: bool = False, allow_filename: bool = True) \
        -> Optional[str]:
    r = None
    # noinspection PyBroadException
    try:
        r = await get(url=url, timeout=2, decode=False, intended_content_type='text/html', max_size=2 * 1024)
        if r.status != 200 or not r.content:
            raise ValueError('not an HTML page')
        # if len(r.content) <= 27:  # len of `<html><head><title></title>`
        #     raise ValueError('invalid HTML')
        soup = await run_async_on_demand(BeautifulSoup, r.content, 'lxml',
                                         prefer_pool='thread', condition=len(r.content) > 64 * 1024)
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
