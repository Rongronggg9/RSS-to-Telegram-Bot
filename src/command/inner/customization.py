from typing import Union, Tuple, Optional
from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

from src import db, env
from src.i18n import i18n
from .utils import arrange_grid, update_interval, activate_or_deactivate_sub


async def get_sub_info(sub: db.Sub,
                       lang: Optional[str] = None) -> str:
    info = (
        f"<b>{i18n[lang]['subscription_info']}</b>\n\n"
        f"{i18n[lang]['subscription_title']}: {sub.title or sub.feed.title}\n"
        f"{i18n[lang]['feed_url']}: {sub.feed.link}\n"
    )
    return info


async def get_sub_customization_buttons(sub: db.Sub,
                                        lang: Optional[str] = None,
                                        page: Optional[int] = None) -> Tuple[Tuple[KeyboardButtonCallback, ...], ...]:
    page = page or 1
    buttons = (
        (
            Button.inline(i18n[lang]['status'] + ': ' +
                          i18n[lang]['status_activated' if sub.state == 1 else 'status_deactivated'],
                          data=f'set_{sub.id}_activate|{page}'),
        ),
        (
            Button.inline(i18n[lang]['notification'] + ': ' +
                          i18n[lang]['notification_normal' if sub.notify else 'notification_muted'],
                          data=f'set_{sub.id}_notify|{page}'),
            Button.inline(i18n[lang]['monitor_interval'] + ': ' +
                          str(sub.interval or db.EffectiveOptions.default_interval),
                          data=f'set_{sub.id}_interval|{page}'),
        ),
        (
            Button.inline(f'< {i18n[lang]["back"]}', data=f'get_set_page_{page}'),
        )
    )
    return buttons


async def get_set_interval_buttons(sub: Union[db.Sub, int],
                                   lang: Optional[str] = None,
                                   page: Optional[int] = None) -> Tuple[Tuple[KeyboardButtonCallback, ...], ...]:
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
            Button.inline(str(interval), data=f'set_{sub_id}_interval_{interval}|{page}')
            for interval in interval_range[:24]
        ),
        columns=4
    ) + ((Button.inline(f'< {i18n[lang]["back"]}', data=f'set_{sub_id}|{page}'),),)
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


async def set_sub_notification(sub: db.Sub) -> db.Sub:
    sub.notify = not sub.notify
    await sub.save()

    return sub


async def set_sub_activate(sub: db.Sub) -> db.Sub:
    activated = sub.state == 1
    await activate_or_deactivate_sub(sub.user_id, sub, activate=not activated)

    return sub
