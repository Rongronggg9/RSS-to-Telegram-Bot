import asyncio
from datetime import datetime
from json import dumps
from typing import Dict, Union, Optional, Sequence, List
from bs4 import BeautifulSoup, Tag
from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

from src import db, web
from src.command.utils import logger, escape_html, get_hash

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
            _sub = await db.Sub.get_or_none(user=user_id, feed=feed)
            if _sub:
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
                [get_hash(entry.get('guid', entry['link'])) for entry in rss_d.entries])
            await feed.save()  # now we get the id
            db.effective_utils.EffectiveTasks.update(feed.id)

        _sub = await db.Sub.create(user_id=user_id, feed=feed)
        ret['sub'] = _sub
        logger.info(f'Subed {feed_url} for {user_id}')
        return ret

    except Exception as e:
        ret['msg'] = 'ERROR: 内部错误'
        logger.warning(f'Sub {feed_url} for {user_id} failed: ', exc_info=e)
        return ret


async def subs(user_id: int, *feed_urls: str) \
        -> Optional[Dict[str, Union[Dict[str, Union[int, str, db.Sub, None]], str]]]:
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


async def unsub(user_id: int, feed_url: str = None, sub_id: int = None) -> Dict[str, Union[str, db.Sub, None]]:
    ret = {'url': feed_url,
           'sub': None,
           'msg': None}

    if (feed_url and sub_id) or not (feed_url or sub_id):
        ret['msg'] = 'ERROR: 内部错误'
        return ret

    try:
        default_interval = db.effective_utils.EffectiveOptions.get('default_interval')
        new_interval = curr_interval = None

        if feed_url:
            feed: db.Feed = await db.Feed.get_or_none(link=feed_url).prefetch_related('subs')
            sub_to_delete: Optional[db.Sub] = None
        else:  # elif sub_id:
            sub_to_delete: db.Sub = await db.Sub.get_or_none(id=sub_id, user=user_id).prefetch_related('feed')
            feed: Optional[db.Feed] = None
            if sub_to_delete:
                await sub_to_delete.feed.fetch_related('subs')
                feed = sub_to_delete.feed

        if feed:
            curr_interval = feed.interval or default_interval
            new_interval = float('inf')
            for _sub in feed.subs:
                if _sub.user_id != user_id:
                    new_interval = min(new_interval, _sub.interval or default_interval)
                    continue
                if sub_to_delete is None:
                    sub_to_delete = _sub
                    continue

        if sub_to_delete is None or feed is None:
            ret['msg'] = 'ERROR: 订阅不存在'
            return ret

        if len(feed.subs) <= 1:  # only this/no sub subs the feed, del the feed and the sub will be deleted cascaded
            await feed.delete()
            db.effective_utils.EffectiveTasks.delete(feed.id)
        else:  # several subs subs the feed, only del the sub
            await sub_to_delete.delete()
            if curr_interval != new_interval and new_interval != float('inf'):
                feed.interval = new_interval
                await feed.save()
                db.effective_utils.EffectiveTasks.update(feed.id, new_interval)
        sub_to_delete.feed = feed
        ret['sub'] = sub_to_delete
        ret['url'] = feed.link
        logger.info(f'Unsubed {feed.link} for {user_id}')
        return ret

    except Exception as e:
        ret['msg'] = 'ERROR: 内部错误'
        logger.warning(f'Unsub {feed_url} for {user_id} failed: ', exc_info=e)
        return ret


async def unsubs(user_id: int, feed_urls: Sequence[str] = None, sub_ids: Sequence[int] = None) \
        -> Optional[Dict[str, Union[Dict[str, Union[int, str, db.Sub, None]], str]]]:
    filtered_feed_urls = (tuple(filter(lambda x: x.startswith('http://') or x.startswith('https://'), feed_urls))
                          if feed_urls else None)
    if not (filtered_feed_urls or sub_ids):
        return None

    coroutines = (tuple(unsub(user_id, url) for url in filtered_feed_urls) if filtered_feed_urls else tuple()
                                                                                                      + tuple(
        unsub(user_id, sub_id=sub_id) for sub_id in sub_ids) if sub_ids else tuple())

    result = await asyncio.gather(*coroutines)

    success = tuple(unsub_d for unsub_d in result if unsub_d['sub'])
    failure = tuple(unsub_d for unsub_d in result if not unsub_d['sub'])

    msg = (
            ('<b>退订成功</b>\n' if success else '')
            + '\n'.join(f'<a href="{sub_d["sub"].feed.link}">{escape_html(sub_d["sub"].feed.title)}</a>'
                        for sub_d in success)
            + ('\n\n' if success and failure else '')
            + ('<b>退订失败</b>\n' if failure else '')
            + '\n'.join(f'{escape_html(sub_d["url"])} ({sub_d["msg"]})' for sub_d in failure)
    )

    ret = {'unsub_d_l': result, 'msg': msg}

    return ret


async def unsub_all(user_id: int) -> Optional[Dict[str, Union[Dict[str, Union[int, str, db.Sub, None]], str]]]:
    user_sub_list = await db.Sub.filter(user=user_id)
    sub_ids = tuple(_sub.id for _sub in user_sub_list)
    return await unsubs(user_id, sub_ids=sub_ids)


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


async def get_unsub_buttons(user_id: int, page: int) -> List[List[KeyboardButtonCallback]]:
    """
    :param user_id: user id
    :param page: page number (1-based)
    :return: ReplyMarkup
    """
    if page <= 0:
        raise IndexError('Page number must be positive.')

    user_sub_list = await list_sub(user_id)
    buttons: List[List[KeyboardButtonCallback]] = []

    row = 0  # 0-based
    column = 0  # 0-based
    max_row_count = 12  # 1-based, telegram limit: 13
    max_column_count = 2  # 1-based, telegram limit: 8 (row 1-12), 4 (row 13)
    subs_count_per_page = max_column_count * max_row_count
    page_start = (page - 1) * subs_count_per_page
    page_end = page_start + subs_count_per_page
    for _sub in user_sub_list[page_start:page_end]:
        if row >= max_row_count:
            break
        button = Button.inline(_sub.feed.title, data=f'unsub_{_sub.id}')
        if column == 0:
            buttons.append([])
            buttons[row] = [button]
            column += 1
        elif column < 2:
            buttons[row].append(button)
            if column == max_column_count - 1:
                row += 1
                column = 0

    if column != 0:
        row += 1

    rest_subs_count = len(user_sub_list[page * subs_count_per_page:])
    if page > 1 or rest_subs_count > 0:
        buttons.append([])
    if page > 1:
        buttons[row].append(Button.inline('上一页', data=f'get_unsub_page_{page - 1}'))
    if rest_subs_count > 0:
        buttons[row].append(Button.inline('下一页', data=f'get_unsub_page_{page + 1}'))

    return buttons
