from __future__ import annotations
from typing import Union, Optional
from collections.abc import Iterable

from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

from src import db, env
from src.i18n import i18n
from .utils import arrange_grid, update_interval, activate_or_deactivate_sub

SUB_OPTIONS_EXHAUSTIVE_VALUES = {
    "notify": (0, 1),
    "send_mode": (-1, 0, 1, 2),
    "link_preview": (0, 1),
    "display_author": (-1, 0, 1),
    "display_via": (-2, -1, 0, 1),
    "display_title": (-1, 0, 1),
    "style": (0, 1)
}


async def get_sub_info(sub: db.Sub,
                       lang: Optional[str] = None) -> str:
    info = (
            f"<b>{i18n[lang]['subscription_info']}</b>\n\n"
            f"{i18n[lang]['feed_title']}: {sub.feed.title}\n"
            + (f"{i18n[lang]['subscription_title']}: {sub.title}\n" if sub.title else '') +
            f"{i18n[lang]['feed_url']}: {sub.feed.link}\n"
    )
    return info


async def get_sub_customization_buttons(sub: db.Sub,
                                        lang: Optional[str] = None,
                                        page: Optional[int] = None) -> tuple[tuple[KeyboardButtonCallback, ...], ...]:
    page = page or 1
    buttons = (
        (
            Button.inline(i18n[lang]['status'] + ': ' +
                          i18n[lang]['status_activated' if sub.state == 1 else 'status_deactivated'],
                          data=f'set={sub.id},activate|{page}'),
        ),
        (
            Button.inline(i18n[lang]['notification'] + ': ' +
                          i18n[lang]['notification_normal' if sub.notify else 'notification_muted'],
                          data=f'set={sub.id},notify|{page}'),
            Button.inline(i18n[lang]['monitor_interval'] + ': ' +
                          str(sub.interval or db.EffectiveOptions.default_interval),
                          data=f'set={sub.id},interval|{page}'),
        ),
        (
            Button.inline(f"{i18n[lang]['send_mode']}: {sub.send_mode}",
                          data=f'set={sub.id},send_mode|{page}'),
        ),
        (
            Button.inline(f"{i18n[lang]['length_limit']}: {sub.length_limit}",
                          data=f'set={sub.id},length_limit|{page}'),
        ),
        (
            Button.inline(f"{i18n[lang]['display_title']}: {sub.display_title}",
                          data=f'set={sub.id},display_title|{page}'),
        ),
        (
            Button.inline(f"{i18n[lang]['display_via']}: {sub.display_via}",
                          data=f'set={sub.id},display_via|{page}'),
        ),
        (
            Button.inline(f"{i18n[lang]['display_author']}: {sub.display_author}",
                          data=f'set={sub.id},display_author|{page}'),
        ),
        (
            Button.inline(f"{i18n[lang]['link_preview']}: {sub.link_preview}",
                          data=f'set={sub.id},link_preview|{page}'),
            Button.inline(f"{i18n[lang]['style']}: {sub.style}",
                          data=f'set={sub.id},style|{page}'),
        ),
        (
            Button.inline(f'< {i18n[lang]["back"]}', data=f'get_set_page|{page}'),
        )
    )
    return buttons


async def get_set_interval_buttons(sub: Union[db.Sub, int],
                                   lang: Optional[str] = None,
                                   page: Optional[int] = None) -> tuple[tuple[KeyboardButtonCallback, ...], ...]:
    sub_id = sub if isinstance(sub, int) else sub.id
    page = page or 1

    minimal_interval: int = db.EffectiveOptions.minimal_interval
    default_interval: int = db.EffectiveOptions.default_interval

    if sub.user_id == env.MANAGER:
        minimal_interval = min(minimal_interval, 5)

    interval_range = list(range(minimal_interval, minimal_interval + 125, 5))
    try:
        interval_range.remove(sub.interval or default_interval)
    except ValueError:
        pass

    buttons = arrange_grid(
        to_arrange=(
            Button.inline(str(interval), data=f'set={sub_id},interval,{interval}|{page}')
            for interval in interval_range[:24]
        ),
        columns=4
    ) + ((Button.inline(f'< {i18n[lang]["back"]}', data=f'set={sub_id}|{page}'),),)
    return buttons


async def get_set_length_limit_buttons(sub: Union[db.Sub, int],
                                       lang: Optional[str] = None,
                                       page: Optional[int] = None) -> tuple[tuple[KeyboardButtonCallback, ...], ...]:
    sub_id = sub if isinstance(sub, int) else sub.id
    page = page or 1

    length_limit_range = list(range(256, 4096 + 1, 256))

    buttons = arrange_grid(
        to_arrange=(
            Button.inline(str(interval), data=f'set={sub_id},length_limit,{interval}|{page}')
            for interval in length_limit_range
        ),
        columns=4
    ) + ((Button.inline(f'< {i18n[lang]["back"]}', data=f'set={sub_id}|{page}'),),)
    return buttons


async def set_sub_interval(sub: db.Sub,
                           interval: int) -> db.Sub:
    minimal_interval = db.EffectiveOptions.minimal_interval
    if interval < minimal_interval and sub.user_id != env.MANAGER:
        interval = minimal_interval

    if interval == sub.interval:
        return sub

    sub.interval = interval
    await sub.save()
    await update_interval(sub.feed, interval)

    return sub


async def set_sub_length_limit(sub: db.Sub,
                               length_limit: int) -> db.Sub:
    if length_limit == sub.length_limit or not 256 <= length_limit <= 4096:
        return sub

    sub.length_limit = length_limit
    await sub.save()
    return sub


async def set_sub_activate(sub: db.Sub) -> db.Sub:
    activated = sub.state == 1
    await activate_or_deactivate_sub(sub.user_id, sub, activate=not activated)

    return sub


async def set_sub_exhaustive_option(sub: db.Sub, option: str) -> db.Sub:
    if option not in SUB_OPTIONS_EXHAUSTIVE_VALUES:
        raise KeyError(f'Invalid option: {option}')
    valid_values = SUB_OPTIONS_EXHAUSTIVE_VALUES[option]
    if option == 'notify':
        if sub.notify not in valid_values:
            sub.notify = 1
        sub.notify = sub.notify + 1 if sub.notify < valid_values[-1] else valid_values[0]
    elif option == 'send_mode':
        if sub.send_mode not in valid_values:
            sub.send_mode = 0
        sub.send_mode = sub.send_mode + 1 if sub.send_mode < valid_values[-1] else valid_values[0]
    elif option == 'link_preview':
        if sub.link_preview not in valid_values:
            sub.link_preview = 0
        sub.link_preview = sub.link_preview + 1 if sub.link_preview < valid_values[-1] else valid_values[0]
    elif option == 'display_author':
        if sub.display_author not in valid_values:
            sub.display_author = 0
        sub.display_author = sub.display_author + 1 if sub.display_author < valid_values[-1] else valid_values[0]
    elif option == 'display_via':
        if sub.display_via not in valid_values:
            sub.display_via = 0
        sub.display_via = sub.display_via + 1 if sub.display_via < valid_values[-1] else valid_values[0]
    elif option == 'display_title':
        if sub.display_title not in valid_values:
            sub.display_title = 0
        sub.display_title = sub.display_title + 1 if sub.display_title < valid_values[-1] else valid_values[0]
    elif option == 'style':
        if sub.style not in valid_values:
            sub.style = 0
        sub.style = sub.style + 1 if sub.style < valid_values[-1] else valid_values[0]
    await sub.save()
    return sub

async def del_subs_title(subs: Union[Iterable[db.Sub], db.Sub]) -> int:
    if isinstance(subs, db.Sub):
        subs = (subs,)
    for sub in subs:
        sub.title = None
    return await db.Sub.bulk_update(subs, ['title'])
