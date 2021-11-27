from typing import AnyStr, Iterable, Tuple, Any, Union, Optional
from zlib import crc32
from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

from src import db


def get_hash(string: AnyStr) -> str:
    if isinstance(string, str):
        string = string.encode('utf-8')
    return hex(crc32(string))[2:]


def arrange_grid(to_arrange: Iterable, columns: int = 8, rows: int = 13) -> Optional[Tuple[Tuple[Any, ...], ...]]:
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


async def get_sub_choosing_buttons(user_id: int, page: int, callback: str, get_page_callback: str) \
        -> Tuple[Tuple[KeyboardButtonCallback, ...], ...]:
    """
    :param user_id: user id
    :param page: page number (1-based)
    :param callback: callback data header
    :param get_page_callback: callback data header for getting another page
    :return: ReplyMarkup
    """
    if page <= 0:
        raise IndexError('Page number must be positive.')

    max_row_count = 12
    max_column_count = 2
    subs_count_per_page = max_column_count * max_row_count
    page_start = (page - 1) * subs_count_per_page
    page_end = page_start + subs_count_per_page
    user_sub_list = await list_sub(user_id)
    buttons_to_arrange = tuple(Button.inline(_sub.feed.title, data=f'{callback}_{_sub.id}|{page}')
                               for _sub in user_sub_list[page_start:page_end])
    buttons = arrange_grid(to_arrange=buttons_to_arrange, columns=max_column_count, rows=max_row_count)

    rest_subs_count = len(user_sub_list[page * subs_count_per_page:])
    page_buttons = []
    if page > 1:
        page_buttons.append(Button.inline('< 上一页', data=f'{get_page_callback}_{page - 1}'))
    if rest_subs_count > 0:
        page_buttons.append(Button.inline('下一页 >', data=f'{get_page_callback}_{page + 1}'))

    return buttons + (tuple(page_buttons),) if page_buttons else buttons


async def update_interval(feed: Union[db.Feed, int], new_interval: Optional[int] = None):
    if new_interval is not None and (not isinstance(new_interval, int) or new_interval <= 0):
        raise ValueError('`new_interval` must be `None` or a positive integer')

    if isinstance(feed, int):
        feed = await db.Feed.get_or_none(id=feed)

    if feed is None:
        return

    default_interval = db.effective_utils.EffectiveOptions.get('default_interval')
    curr_interval = feed.interval or default_interval

    if not new_interval:
        intervals = await feed.subs.all().values_list('interval', flat=True)
        if not intervals:  # no sub subs the feed, del the feed
            await feed.delete()
            db.effective_utils.EffectiveTasks.delete(feed.id)
            return
        new_interval = min(intervals, key=lambda _: default_interval if _ is None else _) or default_interval

    if curr_interval != new_interval:
        feed.interval = new_interval
        await feed.save()
        db.effective_utils.EffectiveTasks.update(feed.id, new_interval)


async def list_sub(user_id: int):
    return await db.Sub.filter(user=user_id).prefetch_related('feed')
