import asyncio
import functools
import aiohttp
import aiohttp.client_exceptions
import feedparser
from concurrent.futures import ThreadPoolExecutor
from aiohttp_socks import ProxyConnector
from aiohttp_retry import RetryClient
from typing import Union, Optional, Mapping, Dict
from ssl import SSLError
from ipaddress import ip_network, ip_address
from urllib.parse import urlparse

from src import env, log
from src.i18n import i18n

logger = log.getLogger('RSStT.web')

_feedparser_thread_pool = ThreadPoolExecutor(1, 'feedparser_')
_semaphore = asyncio.BoundedSemaphore(5)

PROXY = env.R_PROXY.replace('socks5h', 'socks5').replace('sock4a', 'socks4') if env.R_PROXY else None
PRIVATE_NETWORKS = tuple(ip_network(ip_block) for ip_block in
                         ('127.0.0.0/8', '::1/128',  # loopback is not a private network, list in here for convenience
                          '169.254.0.0/16', 'fe80::/10',  # link-local address
                          '10.0.0.0/8',  # class A private network
                          '172.16.0.0/12',  # class B private networks
                          '192.168.0.0/16',  # class C private networks
                          'fc00::/7',  # ULA
                          ))


def proxy_filter(url: str) -> bool:
    if not (env.PROXY_BYPASS_PRIVATE or env.PROXY_BYPASS_DOMAINS):
        return True

    hostname = urlparse(url).hostname
    if env.PROXY_BYPASS_PRIVATE:
        try:
            ip_a = ip_address(hostname)
            is_private = any(ip_a in network for network in PRIVATE_NETWORKS)
            if is_private:
                return False
        except ValueError:
            pass  # not an IP, continue
    if env.PROXY_BYPASS_DOMAINS:
        is_bypassed = any(hostname.endswith(domain) and hostname[-len(domain) - 1] == '.'
                          for domain in env.PROXY_BYPASS_DOMAINS)
        if is_bypassed:
            return False
    return True


async def get(url: str, timeout: int = None, semaphore: Union[bool, asyncio.Semaphore] = None,
              headers: Optional[dict] = None, decode: bool = False) -> Dict[str,
                                                                            Union[Mapping[str, str], bytes, str, int]]:
    if not timeout:
        timeout = 12

    _headers = env.REQUESTS_HEADERS.copy()

    if headers:
        _headers.update(headers)

    proxy_connector = ProxyConnector.from_url(PROXY) if (PROXY and proxy_filter(url)) else None

    await _semaphore.acquire() if semaphore is None or semaphore is True else \
        await semaphore.acquire() if semaphore else None

    try:
        async with RetryClient(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout),
                               headers=_headers) as session:
            async with session.get(url) as response:
                status = response.status
                content = await (response.text() if decode else response.read()) if status == 200 else None
                return {'url': str(response.url),  # get the redirected url
                        'content': content,
                        'headers': response.headers,
                        'status': status}
    finally:
        _semaphore.release() if semaphore is None or semaphore is True else \
            semaphore.release() if semaphore else None


async def get_session(timeout: int = None):
    if not timeout:
        timeout = 12

    proxy_connector = ProxyConnector.from_url(PROXY) if PROXY else None

    session = RetryClient(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout),
                          headers=env.REQUESTS_HEADERS)

    return session


async def feed_get(url: str, timeout: Optional[int] = None, web_semaphore: Union[bool, asyncio.Semaphore] = None,
                   headers: Optional[dict] = None, lang: Optional[str] = None, verbose: bool = True) \
        -> Dict[str, Union[Mapping[str, str], feedparser.FeedParserDict, str, int, None]]:
    auto_warning = logger.warning if verbose else logger.debug
    ret = {'url': url,
           'rss_d': None,
           'headers': None,
           'status': -1,
           'msg': None}
    try:
        _ = await get(url, timeout, web_semaphore, headers=headers)
        rss_content = _['content']
        ret['url'] = _['url']
        ret['headers'] = _['headers']
        ret['status'] = _['status']

        # some rss feed implement http caching improperly :(
        if ret['status'] == 200 and int(ret['headers'].get('Content-Length', 1)) == 0:
            ret['status'] = 304
            ret['msg'] = f'"Content-Length" is 0'
            return ret

        if ret['status'] == 304:
            ret['msg'] = f'304 Not Modified'
            return ret  # 304 Not Modified, feed not updated

        if rss_content is None:
            auto_warning(f'Fetch failed (status code error, {ret["status"]}): {url}')
            ret['msg'] = f'ERROR: {i18n[lang]["status_code_error"]} ({_["status"]})'
            return ret

        if len(rss_content) <= 524288:
            rss_d = feedparser.parse(rss_content, sanitize_html=False)
        else:  # feed too large, run in another thread to avoid blocking the bot
            rss_d = await asyncio.get_event_loop().run_in_executor(_feedparser_thread_pool,
                                                                   functools.partial(feedparser.parse,
                                                                                     rss_content,
                                                                                     sanitize_html=False))

        if 'title' not in rss_d.feed:
            auto_warning(f'Fetch failed (feed invalid): {url}')
            ret['msg'] = 'ERROR: ' + i18n[lang]['feed_invalid']
            return ret

        ret['rss_d'] = rss_d
    except aiohttp.client_exceptions.InvalidURL:
        auto_warning(f'Fetch failed (URL invalid): {url}')
        ret['msg'] = 'ERROR: ' + i18n[lang]['url_invalid']
    except (asyncio.exceptions.TimeoutError,
            aiohttp.client_exceptions.ClientError,
            SSLError,
            OSError,
            ConnectionError,
            TimeoutError) as e:
        auto_warning(f'Fetch failed (network error, {e.__class__.__name__}): {url}')
        ret['msg'] = 'ERROR: ' + i18n[lang]['network_error']
    except Exception as e:
        auto_warning(f'Fetch failed: {url}', exc_info=e)
        ret['msg'] = 'ERROR: ' + i18n[lang]['internal_error']
    return ret
