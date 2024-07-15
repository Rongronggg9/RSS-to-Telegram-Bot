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
from typing import Optional, Union
from typing_extensions import Final

import asyncio
import aiohttp
import feedparser
from io import BytesIO
from ssl import SSLError
from functools import partial

from .. import log
from ..aio_helper import run_async
from ..compat import bozo_exception_removal_wrapper
from .req import get
from .utils import WebResponse, WebFeed, WebError, sentinel

FEED_ACCEPT: Final = 'application/rss+xml, application/rdf+xml, application/atom+xml, ' \
                     'application/xml;q=0.9, text/xml;q=0.8, text/*;q=0.7, application/*;q=0.6'


async def feed_get(url: str, timeout: Optional[float] = sentinel, web_semaphore: Union[bool, asyncio.Semaphore] = None,
                   headers: Optional[dict] = None, verbose: bool = True) -> WebFeed:
    ret = WebFeed(url=url, ori_url=url)

    log_level = log.WARNING if verbose else log.DEBUG
    _headers = {}
    if headers:
        _headers.update(headers)
    if 'Accept' not in _headers:
        _headers['Accept'] = FEED_ACCEPT

    try:
        resp: WebResponse = await get(url, timeout, web_semaphore, decode=False, headers=_headers)
        rss_content = resp.content
        ret.content = rss_content
        ret.url = resp.url
        ret.headers = resp.headers
        ret.status = resp.status
        ret.web_response = resp

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
            rss_d = await run_async(
                partial(bozo_exception_removal_wrapper,
                        feedparser.parse, rss_content_io, sanitize_html=False,
                        response_headers={k.lower(): v for k, v in resp.headers.items()}),
                prefer_pool='thread' if len(rss_content) < 64 * 1024 else None
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
