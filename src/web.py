import asyncio
import functools
import aiohttp
import aiohttp.client_exceptions
import feedparser
from concurrent.futures import ThreadPoolExecutor
from aiohttp_socks import ProxyConnector
from aiohttp_retry import RetryClient
from typing import Union, Optional, Mapping, Dict

from src import env, log

logger = log.getLogger('RSStT.web')

_feedparser_thread_pool = ThreadPoolExecutor(1, 'feedparser_')

_proxy = env.R_PROXY.replace('socks5h', 'socks5').replace('sock4a', 'socks4') if env.R_PROXY else None

_semaphore = asyncio.BoundedSemaphore(5)


async def get(url: str, timeout: int = None, semaphore: Union[bool, asyncio.Semaphore] = None,
              headers: Optional[dict] = None, decode: bool = False) -> dict[str, Union[Mapping[str, str], bytes, str]]:
    if not timeout:
        timeout = 12

    _headers = env.REQUESTS_HEADERS.copy()

    if headers:
        _headers.update(headers)

    proxy_connector = ProxyConnector.from_url(_proxy) if _proxy else None

    await _semaphore.acquire() if semaphore is None or semaphore is True else \
        await semaphore.acquire() if semaphore else None

    try:
        async with RetryClient(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout),
                               headers=_headers) as session:
            async with session.get(url) as response:
                status = response.status
                content = await (response.text() if decode else response.read()) if status == 200 else None
                return {'content': content,
                        'headers': response.headers,
                        'status': status}
    finally:
        _semaphore.release() if semaphore is None or semaphore is True else \
            semaphore.release() if semaphore else None


async def get_session(timeout: int = None):
    if not timeout:
        timeout = 12

    proxy_connector = ProxyConnector.from_url(_proxy) if _proxy else None

    session = RetryClient(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout),
                          headers=env.REQUESTS_HEADERS)

    return session


async def feed_get(url: str, timeout: Optional[int] = None, web_semaphore: Union[bool, asyncio.Semaphore] = None,
                   headers: Optional[dict] = None) \
        -> Dict[str, Union[Mapping[str, str], feedparser.FeedParserDict, str, int, None]]:
    ret = {'rss_d': None,
           'headers': None,
           'status': -1,
           'msg': None}
    try:
        _ = await get(url, timeout, web_semaphore, headers=headers)
        rss_content = _['content']
        ret['headers'] = _['headers']
        ret['status'] = _['status']

        if ret['status'] == 304:
            ret['msg'] = f'304 Not Modified'
            return ret  # 304 Not Modified, feed not updated

        if rss_content is None:
            logger.warning(f'Fetch failed (status code error, {ret["status"]}): {url}')
            ret['msg'] = f'ERROR: 状态码错误 ({_["status"]})'
            return ret

        if len(rss_content) <= 524288:
            rss_d = feedparser.parse(rss_content, sanitize_html=False)
        else:  # feed too large, run in another thread to avoid blocking the bot
            rss_d = await asyncio.get_event_loop().run_in_executor(_feedparser_thread_pool,
                                                                   functools.partial(feedparser.parse,
                                                                                     rss_content,
                                                                                     sanitize_html=False))

        if 'title' not in rss_d.feed:
            logger.warning(f'Fetch failed (feed invalid): {url}')
            ret['msg'] = f'ERROR: feed 不合法'
            return ret

        ret['rss_d'] = rss_d
    except aiohttp.client_exceptions.InvalidURL:
        logger.warning(f'Fetch failed (URL invalid): {url}')
        ret['msg'] = 'ERROR: URL 不合法'
    except (asyncio.exceptions.TimeoutError, aiohttp.client_exceptions.ClientError, ConnectionError, TimeoutError) as e:
        logger.warning(f'Fetch failed (network error, {e.__class__.__name__}): {url}')
        ret['msg'] = 'ERROR: 网络错误'
    except Exception as e:
        logger.warning(f'Fetch failed: {url}', exc_info=e)
        ret['msg'] = 'ERROR: 内部错误'
    return ret
