import asyncio
from datetime import datetime
from json import dumps
from typing import Dict, Union, Optional
from zlib import crc32

from bs4 import BeautifulSoup, Tag

from src import db, web
from src.command.utils import logger, escape_html

with open('src/opml_template.opml', 'r') as __template:
    OPML_TEMPLATE = __template.read()


async def sub(user_id: int, feed_url: str) -> Dict[str, Union[int, str, db.Sub, None]]:
    ret = {'url': feed_url,
           'sub': None,
           'status': -1,
           'msg': None}

    try:
        feed = await db.Feed.get_or_none(link=feed_url)

        if feed:
            sub = await db.Sub.get_or_none(user=user_id, feed=feed)
            if sub:
                ret['sub'] = None
                ret['msg'] = 'ERROR: 订阅已存在'
                return ret
        else:
            d = await web.feed_get(feed_url)
            rss_d = d['rss_d']
            ret['status'] = d['status']
            ret['msg'] = d['msg']

            if rss_d is None:
                logger.warning(f'Sub {feed_url} for {user_id} failed')
                return ret

            feed = db.Feed(title=rss_d.feed.title, link=feed_url)
            feed.etag = d['headers'].get('etag') if d['headers'] else None
            feed.entry_hashes = dumps(
                [hex(crc32(entry.get('guid', entry['link']).encode()))[2:] for entry in rss_d.entries])
            await feed.save()  # now we get the id
            db.effective_utils.EffectiveTasks.update(feed.id)

        sub = await db.Sub.create(user_id=user_id, feed=feed)
        ret['sub'] = sub
        logger.info(f'Subed {feed_url} for {user_id}')
        return ret

    except Exception as e:
        ret['msg'] = 'ERROR: 内部错误'
        logger.warning(f'Sub {feed_url} for {user_id} failed: ', exc_info=e)
        return ret


async def subs(user_id: int, *feed_urls: str) -> Dict[str, Union[Dict[str, Union[int, str, db.Sub, None]], str]]:
    filtered_feed_urls = tuple(filter(lambda x: x.startswith('http://') or x.startswith('https://'), feed_urls))
    if not filtered_feed_urls:
        return None

    result = await asyncio.gather(*(sub(user_id, url) for url in filtered_feed_urls))

    success = tuple(sub_d for sub_d in result if sub_d['sub'])
    failure = tuple(sub_d for sub_d in result if not sub_d['sub'])

    msg = (
            ('<b>订阅成功</b>\n' if success else '')
            + '\n'.join(f'<a href="{sub_d["sub"].feed.link}">{escape_html(sub_d["sub"].feed.title)}</a>'
                        for sub_d in success)
            + ('\n\n' if success and failure else '')
            + ('<b>订阅失败</b>\n' if failure else '')
            + '\n'.join(f'{escape_html(sub_d["url"])} ({sub_d["msg"]})' for sub_d in failure)
    )

    ret = {'sub_d_l': result, 'msg': msg}

    return ret


async def unsub(user_id: int, feed_url: str) -> Dict[str, Union[str, db.Sub, None]]:
    ret = {'url': feed_url,
           'sub': None,
           'msg': None}
    try:
        feed: db.Feed = await db.Feed.get_or_none(link=feed_url).prefetch_related('subs')
        sub_to_delete: Optional[db.Sub] = None
        default_interval = db.effective_utils.EffectiveOptions.get('default_interval')
        new_interval = curr_interval = None
        if feed:
            curr_interval = feed.interval or default_interval
            new_interval = float('inf')
            for sub in feed.subs:
                if sub.user_id == user_id:
                    sub_to_delete = sub
                    continue
                new_interval = min(new_interval, sub.interval or default_interval)

        if sub_to_delete is None:
            ret['msg'] = 'ERROR: 订阅不存在！'
            return ret

        if len(feed.subs) <= 1:  # only this/no sub subs the feed, del the feed and the sub will be deleted cascaded
            await feed.delete()
            db.effective_utils.EffectiveTasks.delete(feed.id)
        else:  # several subs subs the feed, only del the sub
            await sub_to_delete.delete()
            if curr_interval != new_interval:
                feed.interval = new_interval
                await feed.save()
                db.effective_utils.EffectiveTasks.update(feed.id, new_interval)
        sub_to_delete.feed = feed
        ret['sub'] = sub_to_delete
        logger.info(f'Unsubed {feed_url} for {user_id}')
        return ret

    except Exception as e:
        ret['msg'] = 'ERROR: 内部错误'
        logger.warning(f'Unsub {feed_url} for {user_id} failed: ', exc_info=e)
        return ret


async def list_sub(user_id: int):
    return await db.Sub.filter(user=user_id).prefetch_related('feed')


async def export_opml(user_id: int) -> Optional[bytes]:
    sub_list = await list_sub(user_id)
    opml = BeautifulSoup(OPML_TEMPLATE, 'lxml-xml')
    create_time = Tag(name='dateCreated')
    create_time.string = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S UTC')
    opml.head.append(create_time)
    empty_flags = True
    for _sub in sub_list:
        empty_flags = False
        outline = Tag(name='outline', attrs={'text': _sub.feed.title, 'xmlUrl': _sub.feed.link})
        opml.body.append(outline)
    if empty_flags:
        return None
    logger.info('Exported feed(s).')
    return opml.prettify().encode()
