from __future__ import annotations
from typing import Union, Optional, AnyStr
from typing_extensions import Final

import aiohttp
import aiohttp.abc
import feedparser
from contextlib import suppress
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse
from multidict import CIMultiDictProxy

from .. import env, log
from ..i18n import i18n

logger = log.getLogger('RSStT.web')
PRIVATE_NETWORKS: Final = tuple(ip_network(ip_block) for ip_block in
                                ('127.0.0.0/8', '::1/128',
                                 # loopback is not a private network, list in here for convenience
                                 '169.254.0.0/16', 'fe80::/10',  # link-local address
                                 '10.0.0.0/8',  # class A private network
                                 '172.16.0.0/12',  # class B private networks
                                 '192.168.0.0/16',  # class C private networks
                                 'fc00::/7',  # ULA
                                 ))
sentinel = object()


class YummyCookieJar(aiohttp.abc.AbstractCookieJar):
    """
    A cookie jar that acts as a DummyCookieJar in the initial state.
    Then it only switches to CookieJar when there is any cookie (``update_cookies`` is called).
    In our use case, it is common that the response does not contain any cookie, as we mostly fetch RSS feeds and
    multimedia files.
    As a result, the cookie jar is mostly empty, and the overhead of CookieJar, which is expensive, is unnecessary.
    So it is expected that YummyCookieJar will seldom switch to CookieJar, acting as a DummyCookieJar most of the time.

    See also https://github.com/aio-libs/aiohttp/issues/7583
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__real_cookie_jar = aiohttp.DummyCookieJar(*args, **kwargs)
        self.__init_args = args
        self.__init_kwargs = kwargs
        self.__is_dummy = True

    def update_cookies(self, *args, **kwargs):
        if self.__is_dummy:
            self.__real_cookie_jar = aiohttp.CookieJar(*self.__init_args, **self.__init_kwargs)
            self.__is_dummy = False
        return self.__real_cookie_jar.update_cookies(*args, **kwargs)

    def __iter__(self):
        return self.__real_cookie_jar.__iter__()

    def __len__(self) -> int:
        return self.__real_cookie_jar.__len__()

    def clear(self, *args, **kwargs):
        return self.__real_cookie_jar.clear(*args, **kwargs)

    def clear_domain(self, *args, **kwargs):
        return self.__real_cookie_jar.clear_domain(*args, **kwargs)

    def filter_cookies(self, *args, **kwargs):
        return self.__real_cookie_jar.filter_cookies(*args, **kwargs)


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


@dataclass
class WebResponse:
    url: str  # redirected url
    ori_url: str  # original url
    content: Optional[AnyStr]
    headers: CIMultiDictProxy[str]
    status: int
    reason: Optional[str]


@dataclass
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
