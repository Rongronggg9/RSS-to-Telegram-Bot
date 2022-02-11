from __future__ import annotations
from typing import AnyStr, Any, Union, Optional
from collections.abc import Iterable, Mapping

import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
from zlib import crc32
from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

from src import db
from src.i18n import i18n


def get_hash(string: AnyStr) -> str:
    if isinstance(string, str):
        string = string.encode('utf-8')
    return hex(crc32(string))[2:]


def filter_urls(urls: Optional[Iterable[str]]) -> tuple[str, ...]:
    if not urls:
        return tuple()

    return tuple(filter(lambda x: x.startswith('http://') or x.startswith('https://'), urls))


def get_http_caching_headers(headers: Optional[Mapping]) -> dict[str, Optional[Union[str, datetime]]]:
    """
    :param headers: dict of headers
    :return: a dict containing "Etag" (`str` or `None`) and "Last-Modified" (`datetime.datetime` or `None`) headers
    """
    if not headers:
        return {
            'Last-Modified': None,
            'ETag': None
        }

    last_modified = headers.get('Last-Modified', headers.get('Date'))
    last_modified = parsedate_to_datetime(last_modified) if last_modified else datetime.utcnow()
    return {
        'Last-Modified': last_modified,
        'ETag': headers.get('ETag')
    }


def arrange_grid(to_arrange: Iterable, columns: int = 8, rows: int = 13) -> Optional[tuple[tuple[Any, ...], ...]]:
    """
    :param to_arrange: `Iterable` containing objects to arrange
    :param columns: 1-based, telegram limit: 8 (row 1-12), 4 (row 13)
    :param rows: 1-based, telegram limit: 13
    :return: grid (2D tuple) with objects arranged
    """
    if rows <= 0 or columns <= 0:
        raise ValueError('Invalid grid size')
    to_arrange = list(to_arrange)
    counts = min(len(to_arrange), rows * columns)
    columns = min(columns, len(to_arrange))
    return tuple(
        tuple(to_arrange[i:i + columns]) for i in range(0, counts, columns)
    ) if counts > 0 else None


async def get_sub_list_by_page(user_id: int, page_number: int, size: int, *args, **kwargs) \
        -> tuple[int, int, list[db.Sub], int]:
    """
    :param user_id: user id
    :param page_number: page number (1-based)
    :param size: page size
    :param args: args for `Sub.filter`
    :param kwargs: kwargs for `Sub.filter`
    :return: (page_count, page_number, subs_page, total_count)
    """
    if page_number <= 0:
        # raise IndexError('Page number must be positive.')
        page_number = 1

    sub_count = await db.Sub.filter(user=user_id, *args, **kwargs).count()
    if sub_count == 0:
        return 0, 0, [], 0

    page_count = (sub_count - 1) // size + 1
    if page_number > page_count:
        # raise IndexError(f'Page {page} does not exist.')
        page_number = page_count

    offset = (page_number - 1) * size
    page = await db.Sub.filter(user=user_id, *args, **kwargs).order_by('id').limit(size).offset(offset) \
        .prefetch_related('feed')
    return page_number, page_count, page, sub_count


def get_page_buttons(page_number: int,
                     page_count: int,
                     get_page_callback: str,
                     total_count: Optional[int] = None,
                     display_cancel: bool = False,
                     lang: Optional[str] = None) -> list[Button]:
    page_number = min(page_number, page_count)
    page_info = f'{page_number} / {page_count}' + (f' ({total_count})' if total_count else '')
    page_buttons = [
        Button.inline(f'< {i18n[lang]["previous_page"]}', data=f'{get_page_callback}_{page_number - 1}')
        if page_number > 1
        else Button.inline(' ', data='null'),

        Button.inline(page_info + ' | ' + i18n[lang]['cancel'], data='cancel')
        if display_cancel
        else Button.inline(page_info, data='null'),

        Button.inline(f'{i18n[lang]["next_page"]} >', data=f'{get_page_callback}_{page_number + 1}')
        if page_number < page_count
        else Button.inline(' ', data='null'),
    ]
    return page_buttons


async def get_sub_choosing_buttons(user_id: int,
                                   page_number: int,
                                   callback: str,
                                   get_page_callback: Optional[str],
                                   callback_contain_page_num: bool = True,
                                   lang: Optional[str] = None,
                                   rows: int = 12,
                                   columns: int = 1,
                                   *args, **kwargs) -> Optional[tuple[tuple[KeyboardButtonCallback, ...], ...]]:
    """
    :param user_id: user id
    :param page_number: page number (1-based)
    :param callback: callback data header
    :param get_page_callback: callback data header for getting another page
    :param callback_contain_page_num: callback data should be followed by current page number or not?
    :param lang: language code
    :param rows: the number of rows
    :param columns: the number of columns
    :param args: args for `list_sub`
    :param kwargs: kwargs for `list_sub`
    :return: ReplyMarkup
    """
    if page_number <= 0:
        raise IndexError('Page number must be positive.')

    size = columns * rows
    page_number, page_count, page, sub_count = \
        await get_sub_list_by_page(user_id=user_id, page_number=page_number, size=size, *args, **kwargs)

    if page_count == 0:
        return None

    buttons_to_arrange = tuple(Button.inline(_sub.feed.title,
                                             data=f'{callback}_{_sub.id}'
                                                  + (f'|{page_number}' if callback_contain_page_num else ''))
                               for _sub in page)
    buttons = arrange_grid(to_arrange=buttons_to_arrange, columns=columns, rows=rows)

    page_buttons = get_page_buttons(page_number=page_number,
                                    page_count=page_count,
                                    get_page_callback=get_page_callback,
                                    total_count=sub_count,
                                    display_cancel=True,
                                    lang=lang)

    return buttons + (tuple(page_buttons),) if page_buttons else buttons


async def update_interval(feed: Union[db.Feed, int], new_interval: Optional[int] = None, force_update: bool = False):
    if new_interval is not None and (not isinstance(new_interval, int) or new_interval <= 0):
        raise ValueError('`new_interval` must be `None` or a positive integer')

    if isinstance(feed, int):
        feed = await db.Feed.get_or_none(id=feed)

    if feed is None:
        return

    default_interval = db.EffectiveOptions.default_interval
    curr_interval = feed.interval or default_interval
    default_flag = False

    if not new_interval:
        sub_exist = await feed.subs.all().exists()
        intervals = await feed.subs.filter(state=1).values_list('interval', flat=True)
        if not sub_exist:  # no sub subs the feed, del the feed
            await feed.delete()
            db.effective_utils.EffectiveTasks.delete(feed.id)
            return
        if not intervals:  # no active sub subs the feed, deactivate the feed
            await deactivate_feed(feed)
            return
        new_interval = min(intervals, key=lambda _: default_interval if _ is None else _) or default_interval
        default_flag = new_interval == default_interval and new_interval not in intervals
        force_update = True

    force_update = force_update and new_interval != curr_interval

    if new_interval < curr_interval or force_update:  # if not force_update, will only reduce the interval
        feed.interval = new_interval if not default_flag else None
        await feed.save()
        return

    if db.effective_utils.EffectiveTasks.get_interval(feed.id) != new_interval:
        db.effective_utils.EffectiveTasks.update(feed.id, new_interval)


async def list_sub(user_id: int, *args, **kwargs) -> list[db.Sub]:
    return await db.Sub.filter(user=user_id, *args, **kwargs).prefetch_related('feed')


async def have_subs(user_id: int) -> bool:
    return await db.Sub.filter(user=user_id).exists()


async def activate_feed(feed: db.Feed) -> db.Feed:
    if feed.state == 1:
        return feed

    feed.state = 1
    feed.error_count = 0
    feed.next_check_time = None
    await feed.save()
    await update_interval(feed)
    return feed


async def deactivate_feed(feed: db.Feed) -> db.Feed:
    db.effective_utils.EffectiveTasks.delete(feed.id)

    subs = await feed.subs.all()
    if not subs:
        await feed.delete()
        return feed

    feed.state = 0
    feed.next_check_time = None
    await feed.save()
    await asyncio.gather(
        *(activate_or_deactivate_sub(sub.user_id, sub, activate=False, _update_interval=False) for sub in subs)
    )

    return feed


async def activate_or_deactivate_sub(user_id: int, sub: Union[db.Sub, int], activate: bool,
                                     _update_interval: bool = True) -> Optional[db.Sub]:
    """
    :param user_id: user id
    :param sub: `db.Sub` or sub id
    :param activate: activate the sub if `Ture`, deactivate if `False`
    :param _update_interval: update interval or not?
    :return: the updated sub, `None` if the sub does not exist
    """
    if isinstance(sub, int):
        sub = await db.Sub.get_or_none(id=sub, user_id=user_id).prefetch_related('feed')
        if not sub:
            return None
    elif sub.user_id != user_id:
        return None

    sub.state = 1 if activate else 0
    await sub.save()
    await sub.fetch_related('feed')

    if activate:
        await activate_feed(sub.feed)

    interval = sub.interval or db.EffectiveOptions.default_interval
    if _update_interval:
        await update_interval(sub.feed, new_interval=interval if activate else None)

    return sub


async def activate_or_deactivate_all_subs(user_id: int, activate: bool) -> tuple[Optional[db.Sub], ...]:
    """
    :param user_id: user id
    :param activate: activate all subs if `Ture`, deactivate if `False`
    :return: the updated sub, `None` if the sub does not exist
    """
    subs = await list_sub(user_id, state=0 if activate else 1)
    return await asyncio.gather(*(activate_or_deactivate_sub(user_id, sub, activate=activate) for sub in subs))
