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
from collections.abc import Sequence

import re
import asyncio
from datetime import datetime
from bs4 import BeautifulSoup
from bs4.element import SoupStrainer
from urllib.parse import urljoin
from cachetools import TTLCache
from os import path

from ... import db, web, env
from ...aio_helper import run_async
from ...i18n import i18n
from .utils import update_interval, list_sub, filter_urls, logger, escape_html, \
    check_sub_limit, calculate_update
from ...parsing.utils import ensure_plain

FeedSnifferCache = TTLCache(maxsize=256, ttl=60 * 60 * 24)

with open(path.normpath(path.join(path.dirname(__file__), '../..', 'opml_template.opml')), 'r') as __template:
    OPML_TEMPLATE = __template.read()


async def sub(user_id: int,
              feed_url: Union[str, tuple[str, str]],
              lang: Optional[str] = None,
              bypass_feed_sniff: bool = False) -> dict[str, Union[int, str, db.Sub, None]]:
    if not bypass_feed_sniff and feed_url in FeedSnifferCache and FeedSnifferCache[feed_url]:
        return await sub(user_id, FeedSnifferCache[feed_url], lang=lang, bypass_feed_sniff=True)

    ret = {'url': feed_url,
           'sub': None,
           'status': -1,
           'msg': None}

    sub_title = None
    if isinstance(feed_url, tuple):
        feed_url, sub_title = feed_url

    try:
        feed = await db.Feed.get_or_none(link=feed_url)
        _sub = None
        created_new_sub = False

        if feed:
            _sub = await db.Sub.get_or_none(user=user_id, feed=feed)
        if not feed or feed.state == 0:
            wf = await web.feed_get(feed_url, verbose=False)
            rss_d = wf.rss_d
            ret['status'] = wf.status
            ret['msg'] = wf.error and wf.error.i18n_message(lang)
            feed_url_original = feed_url
            ret['url'] = feed_url = wf.url  # get the redirected url

            if rss_d is None:
                # try sniffing a feed for the web page
                if not bypass_feed_sniff and wf.status == 200 and wf.content:
                    sniffed_feed_url = await feed_sniffer(feed_url, wf.content)
                    if sniffed_feed_url:
                        sniff_ret = await sub(user_id, sniffed_feed_url, lang=lang, bypass_feed_sniff=True)
                        if sniff_ret['sub']:
                            return sniff_ret
                        FeedSnifferCache[feed_url] = None
                        FeedSnifferCache[feed_url_original] = None
                logger.warning(f'Sub {feed_url} for {user_id} failed: ({wf.error})')
                return ret

            if feed_url_original != feed_url:
                logger.info(f'Sub {feed_url_original} redirected to {feed_url}')
                if feed:
                    await migrate_to_new_url(feed, feed_url)

            wr = wf.web_response
            assert wr is not None

            # need to use get_or_create because we've changed feed_url to the redirected one
            title = rss_d.feed.title
            title = await ensure_plain(title) if title else ''
            feed, created_new_feed = await db.Feed.get_or_create(defaults={'title': title}, link=feed_url)
            if created_new_feed or feed.state == 0:
                feed.state = 1
                feed.error_count = 0
                feed.next_check_time = None
                etag = wr.etag
                if etag:
                    feed.etag = etag
                feed.last_modified = wr.last_modified
                feed.entry_hashes = list(calculate_update(old_hashes=None, entries=rss_d.entries)[0])
                await feed.save()  # now we get the id
                db.effective_utils.EffectiveTasks.update(feed.id)

        sub_title = sub_title if feed.title != sub_title else None

        if not _sub:  # create a new sub if needed
            _sub, created_new_sub = await db.Sub.get_or_create(
                user_id=user_id, feed=feed,
                defaults={
                    'title': sub_title if sub_title else None,
                    'interval': None,
                    'notify': -100,
                    'send_mode': -100,
                    'length_limit': -100,
                    'link_preview': -100,
                    'display_author': -100,
                    'display_via': -100,
                    'display_title': -100,
                    'display_entry_tags': -100,
                    'style': -100,
                    'display_media': -100
                }
            )

        if not created_new_sub:
            if _sub.title == sub_title and _sub.state == 1:
                ret['sub'] = None
                ret['msg'] = 'ERROR: ' + i18n[lang]['already_subscribed']
                return ret

            if _sub.title != sub_title:
                _sub.state = 1
                _sub.title = sub_title
                await _sub.save()
                logger.info(f'Sub {feed_url} for {user_id} updated title to {sub_title}')
            else:
                _sub.state = 1
                await _sub.save()
                logger.info(f'Sub {feed_url} for {user_id} activated')

        _sub.feed = feed  # by doing this we don't need to fetch_related
        ret['sub'] = _sub
        if created_new_sub:
            logger.info(f'Subed {feed_url} for {user_id}')

        await asyncio.shield(update_interval(feed=feed))

        return ret

    except Exception as e:
        ret['msg'] = 'ERROR: ' + i18n[lang]['internal_error']
        logger.warning(f'Sub {feed_url} for {user_id} failed: ', exc_info=e)
        return ret


async def subs(user_id: int,
               feed_urls: Sequence[Union[str, tuple[str, str]]],
               lang: Optional[str] = None) \
        -> Optional[dict[str, Union[tuple[dict[str, Union[int, str, db.Sub, None]], ...], str, int]]]:
    if not feed_urls:
        return None

    limit_reached, count, limit, _ = await check_sub_limit(user_id)
    if limit > 0:
        remaining = limit - count if not limit_reached else 0
        remaining_feed_urls = feed_urls[:remaining]
        failure = [{'url': url, 'msg': 'ERROR: ' + i18n[lang]['sub_limit_reached']}
                   for url in feed_urls[remaining:]]
        if failure:
            logger.info(f'Sub limit reached for {user_id}, rejected {len(failure)} feeds of {len(feed_urls)}')
    else:
        remaining_feed_urls = feed_urls
        failure = []

    result = await asyncio.gather(*(sub(user_id, url, lang=lang) for url in remaining_feed_urls))

    success = tuple(sub_d for sub_d in result if sub_d['sub'])
    failure.extend(sub_d for sub_d in result if not sub_d['sub'])

    success_msg = (
            (f'<b>{i18n[lang]["sub_successful"]}</b>\n' if success else '')
            + '\n'.join(f'<a href="{sub_d["sub"].feed.link}">'
                        f'{escape_html(sub_d["sub"].title or sub_d["sub"].feed.title)}</a>'
                        for sub_d in success)
    )
    failure_msg = (
            (f'<b>{i18n[lang]["sub_failed"]}</b>\n' if failure else '')
            + '\n'.join(f'{escape_html(sub_d["url"])} ({sub_d["msg"]})' for sub_d in failure)
    )

    msg = (
            success_msg
            + ('\n\n' if success and failure else '')
            + failure_msg
    )

    ret = {'sub_d_l': result, 'msg': msg,
           'success_count': len(success), 'failure_count': len(failure),
           'success_msg': success_msg, 'failure_msg': failure_msg}

    return ret


async def unsub(user_id: int, feed_url: str = None, sub_id: int = None, lang: Optional[str] = None) \
        -> dict[str, Union[str, db.Sub, None]]:
    ret = {'url': feed_url,
           'sub': None,
           'msg': None}

    if (feed_url and sub_id) or not (feed_url or sub_id):
        ret['msg'] = 'ERROR: ' + i18n[lang]['internal_error']
        return ret

    try:
        if feed_url:
            feed: db.Feed = await db.Feed.get_or_none(link=feed_url)
            sub_to_delete: Optional[db.Sub] = await feed.subs.filter(user=user_id).first() if feed else None
        else:  # elif sub_id:
            sub_to_delete: db.Sub = await db.Sub.get_or_none(id=sub_id, user=user_id).prefetch_related('feed')
            feed: Optional[db.Feed] = await sub_to_delete.feed if sub_to_delete else None

        if sub_to_delete is None or feed is None:
            ret['msg'] = 'ERROR: ' + i18n[lang]['subscription_not_exist']
            return ret

        await sub_to_delete.delete()
        await update_interval(feed=feed)

        sub_to_delete.feed = feed
        ret['sub'] = sub_to_delete
        ret['url'] = feed.link
        logger.info(f'Unsubed {feed.link} for {user_id}')
        return ret

    except Exception as e:
        ret['msg'] = 'ERROR: ' + i18n[lang]['internal_error']
        logger.warning(f'Unsub {feed_url} for {user_id} failed: ', exc_info=e)
        return ret


async def unsubs(user_id: int,
                 feed_urls: Sequence[str] = None,
                 sub_ids: Sequence[int] = None,
                 lang: Optional[str] = None,
                 bypass_url_filter: bool = False) \
        -> Optional[dict[str, Union[dict[str, Union[int, str, db.Sub, None]], str]]]:
    feed_urls = filter_urls(feed_urls) if not bypass_url_filter else feed_urls
    if not (feed_urls or sub_ids):
        return None

    coroutines = (
            (tuple(unsub(user_id, feed_url=url, lang=lang) for url in feed_urls) if feed_urls else ())
            + (tuple(unsub(user_id, sub_id=sub_id, lang=lang) for sub_id in sub_ids) if sub_ids else ())
    )

    result = await asyncio.gather(*coroutines)

    success = tuple(unsub_d for unsub_d in result if unsub_d['sub'])
    failure = tuple(unsub_d for unsub_d in result if not unsub_d['sub'])

    success_msg = (
            (f'<b>{i18n[lang]["unsub_successful"]}</b>\n' if success else '')
            + '\n'.join(f'<a href="{sub_d["sub"].feed.link}">'
                        f'{escape_html(sub_d["sub"].title or sub_d["sub"].feed.title)}</a>'
                        for sub_d in success)
    )
    failure_msg = (
            (f'<b>{i18n[lang]["unsub_failed"]}</b>\n' if failure else '')
            + '\n'.join(f'{escape_html(sub_d["url"])} ({sub_d["msg"]})' for sub_d in failure)
    )
    msg = (
            success_msg
            + ('\n\n' if success and failure else '')
            + failure_msg
    )

    ret = {'unsub_d_l': result, 'msg': msg,
           'success_count': len(success), 'failure_count': len(failure),
           'success_msg': success_msg, 'failure_msg': failure_msg}

    return ret


async def unsub_all(user_id: int, lang: Optional[str] = None) \
        -> Optional[dict[str, Union[dict[str, Union[int, str, db.Sub, None]], str]]]:
    user_sub_list = await db.Sub.filter(user=user_id).values_list('id', flat=True)
    return await unsubs(user_id, sub_ids=user_sub_list, lang=lang) if user_sub_list else None


async def export_opml(user_id: int) -> Optional[bytes]:
    sub_list = await list_sub(user_id)
    opml = BeautifulSoup(OPML_TEMPLATE, 'lxml-xml')
    create_time = opml.new_tag('dateCreated')
    create_time.string = opml.new_string(datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S UTC'))
    opml.head.append(create_time)
    empty_flags = True
    for _sub in sub_list:
        empty_flags = False
        outline = opml.new_tag(name='outline', attrs=dict(
            type='rss',
            text=_sub.title or _sub.feed.title,
            title=_sub.feed.title,
            xmlUrl=_sub.feed.link
        ))
        opml.body.append(outline)
    if empty_flags:
        return None
    logger.info(f'Exported feed(s) for {user_id}')
    return opml.prettify().encode()


async def migrate_to_new_url(feed: db.Feed, new_url: str) -> Union[bool, db.Feed]:
    """
    Migrate feed's link to new url, useful when a feed is redirected to a new url.
    :param feed:
    :param new_url:
    :return:
    """
    if feed.link == new_url:
        return False

    logger.info(f'Migrating {feed.link} to {new_url}')
    new_url_feed = await db.Feed.get_or_none(link=new_url)
    if new_url_feed is None:  # new_url not occupied
        feed.link = new_url
        await feed.save()
        return True

    # new_url has been occupied by another feed
    new_url_feed.state = 1
    new_url_feed.title = feed.title
    new_url_feed.entry_hashes = feed.entry_hashes
    new_url_feed.etag = feed.etag
    new_url_feed.last_modified = feed.last_modified
    new_url_feed.error_count = 0
    new_url_feed.next_check_time = None
    await new_url_feed.save()

    # migrate all subs to the new feed
    tasks_migrate = []
    async for exist_sub in feed.subs:
        if await db.Sub.filter(feed=new_url_feed, user_id=exist_sub.user_id).exists():
            continue  # sub already exists, skip it, delete cascade later
        exist_sub.feed = new_url_feed
        tasks_migrate.append(env.loop.create_task(exist_sub.save()))

    await asyncio.gather(*tasks_migrate)
    await asyncio.gather(update_interval(new_url_feed), feed.delete())
    return new_url_feed


FeedLinkTypeMatcher = re.compile(r'(application|text)/(rss|rdf|atom)(\+xml)?', re.I)
FeedLinkHrefMatcher = re.compile(r'(rss|rdf|atom)', re.I)
FeedAHrefMatcher = re.compile(r'/(feed|rss|atom)(\.(xml|rss|atom))?$', re.I)
FeedATextMatcher = re.compile(r'([^a-zA-Z]|^)(rss|atom)([^a-zA-Z]|$)', re.I)


async def feed_sniffer(url: str, html: AnyStr) -> Optional[str]:
    if url in FeedSnifferCache:
        return FeedSnifferCache[url]
    # if len(html) < 69:  # len of `<html><head></head><body></body></html>` + `<link rel="alternate" href="">`
    #     return None  # too short to sniff

    soup = await run_async(BeautifulSoup, html, 'lxml',
                           parse_only=SoupStrainer(name=('a', 'link'), attrs={'href': True}),
                           prefer_pool='thread')
    links = (
            soup.find_all(name='link', attrs={'rel': 'alternate', 'type': FeedLinkTypeMatcher})
            or
            soup.find_all(name='link', attrs={'rel': 'alternate', 'href': FeedLinkHrefMatcher})
            or
            soup.find_all(name='a', attrs={'class': FeedATextMatcher})
            or
            soup.find_all(name='a', attrs={'title': FeedATextMatcher})
            or
            soup.find_all(name='a', attrs={'href': FeedAHrefMatcher})
            or
            soup.find_all(name='a', string=FeedATextMatcher)
    )
    if links:
        feed_url = urljoin(url, links[0]['href'])
        FeedSnifferCache[url] = feed_url
        return feed_url
    return None
