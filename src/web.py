import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
from aiohttp_retry import RetryClient

from src import env

_proxy = env.R_PROXY.replace('socks5h', 'socks5').replace('sock4a', 'socks4') if env.R_PROXY else None


async def get_async(url: str, timeout: int = None, semaphore: asyncio.Semaphore = None) -> bytes:
    if not timeout:
        timeout = 12

    proxy_connector = ProxyConnector.from_url(_proxy) if _proxy else None
    if semaphore is not None:
        await semaphore.acquire()
    try:
        async with RetryClient(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout),
                               headers=env.REQUESTS_HEADERS) as session:
            async with session.get(url) as response:
                return await response.content.read()
    finally:
        if semaphore is not None:
            semaphore.release()


def get(url: str, timeout: int = None, semaphore: asyncio.Semaphore = None) -> str:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(get_async(url, timeout, semaphore))
