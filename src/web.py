import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
from aiohttp_retry import RetryClient
from typing import Union

from src import env

_proxy = env.R_PROXY.replace('socks5h', 'socks5').replace('sock4a', 'socks4') if env.R_PROXY else None

_semaphore = asyncio.BoundedSemaphore(5)


async def get(url: str, timeout: int = None, semaphore: Union[bool, asyncio.Semaphore] = None) -> bytes:
    if not timeout:
        timeout = 12

    proxy_connector = ProxyConnector.from_url(_proxy) if _proxy else None

    await _semaphore.acquire() if semaphore is None or semaphore is True else \
        await semaphore.acquire() if semaphore else None

    try:
        async with RetryClient(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout),
                               headers=env.REQUESTS_HEADERS) as session:
            async with session.get(url) as response:
                return await response.read()
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
