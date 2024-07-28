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
from typing import Union, Optional

from telethon import Button

from . import inner, misc
from .types import *
from .utils import command_gatekeeper, parse_customization_callback_data, parse_callback_data_with_page, \
    escape_html, parse_command_get_sub_or_user_and_param, get_callback_tail
from .. import db, env
from ..i18n import i18n


@command_gatekeeper(only_manager=False)
async def cmd_set_or_callback_get_set_page(
        event: TypeEventCollectionMsgOrCb,
        *_,
        lang: Optional[str] = None,
        page: Optional[int] = None,
        chat_id: Optional[int] = None,
        **__,
):  # command: /set ; callback data: get_set_page|{page_number}
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    is_callback = isinstance(event, TypeEventCb)
    if not page:
        _, page = parse_callback_data_with_page(event.data) if is_callback else (None, 1)

    have_subs = await inner.utils.have_subs(chat_id)
    if not have_subs:
        msg = i18n[lang]['no_subscription']
        buttons = None
    else:
        msg = i18n[lang]['set_choose_sub_prompt']
        buttons = await inner.utils.get_sub_choosing_buttons(
            chat_id, page_number=page, lang=lang,
            callback='set',
            get_page_callback='get_set_page',
            tail=callback_tail,
        )

    await (
        event.edit(msg, buttons=buttons)
        if is_callback
        else event.respond(msg, buttons=buttons)
    )


@command_gatekeeper(only_manager=False)
async def callback_set(
        event: TypeEventCb,
        set_user_default: bool,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):
    # callback data = set={sub_id}[,{action}[,{param}]][|{page_number}]
    # or set_default[={action}[,{param}]]
    """
    send_mode: -1=force link, 0=auto, 1=force Telegraph, 2=force message
    length_limit: Telegraph length limit, valid when send_mode==0. If exceeded, send via Telegraph; If is 0,
        send via Telegraph when a post cannot be sent in a single message
    link_preview: 0=auto, 1=force enable
    display_author: -1=disable, 0=auto, 1=force display
    display_via: -2=completely disable, -1=disable but display link, 0=auto, 1=force display
    display_title: -1=disable, 0=auto, 1=force display
    display_entry_tags: -1=disable, 1=force display
    style: 0=RSStT, 1=flowerss
    """
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    sub_id, action, param, page = parse_customization_callback_data(event.data)

    if sub_id is None and not set_user_default:
        await cmd_set_or_callback_get_set_page.__wrapped__(event, lang=lang, page=page, chat_id=chat_id)
        return

    sub_or_user: Union[db.Sub, db.User] = await (
        db.User.get_or_none(id=chat_id)
        if set_user_default
        else db.Sub.get_or_none(id=sub_id, user=chat_id).prefetch_related('feed', 'user')
    )
    if sub_or_user is None:
        await event.edit(i18n[lang]['subscription_not_exist'])
        return

    if (
            action is None
            or
            (
                    action in {'interval', 'length_limit'}
                    and (isinstance(param, int) or param == 'default')
            )
            or (action == 'activate' and not set_user_default)
            or action in inner.customization.SUB_OPTIONS_EXHAUSTIVE_VALUES
    ):
        if action == 'interval' and (isinstance(param, int) or param == 'default'):
            await inner.customization.set_interval(sub_or_user, param if param != 'default' else -100)
        elif action == 'length_limit' and (isinstance(param, int) or param == 'default'):
            await inner.customization.set_length_limit(sub_or_user, param if param != 'default' else -100)
        elif action == 'activate' and not set_user_default:
            await inner.customization.set_sub_activate(sub_or_user)
        elif (
                action == 'display_media'
                and not set_user_default
                and
                (
                        sub_or_user.send_mode
                        if sub_or_user.send_mode != -100
                        else sub_or_user.user.send_mode
                ) in {1, -1}
        ):
            await event.answer(i18n[lang]['display_media_only_effective_if_send_mode_auto_and_telegram'],
                               alert=True)
            return
        elif action is not None and action in inner.customization.SUB_OPTIONS_EXHAUSTIVE_VALUES:
            await inner.customization.set_exhaustive_option(sub_or_user, action)

        info = '\n\n'.join((
            i18n[lang]['set_user_default_description'],
            i18n[lang]['read_formatting_settings_guidebook_html']
            if set_user_default
            else await inner.customization.get_sub_info(sub_or_user, lang, additional_guide=True),
        ))
        buttons = await inner.customization.get_customization_buttons(
            sub_or_user, lang=lang, page=page, tail=callback_tail,
        )
        await event.edit(info, buttons=buttons, parse_mode='html', link_preview=False)
        return

    if action == 'interval':
        msg = i18n[lang]['set_interval_prompt']
        buttons = await inner.customization.get_set_interval_buttons(
            sub_or_user, lang=lang, page=page, tail=callback_tail,
        )
        await event.edit(msg, buttons=buttons)
        return
    if action == 'length_limit':
        if (
                not set_user_default
                and
                (
                        sub_or_user.send_mode
                        if sub_or_user.send_mode != -100
                        else sub_or_user.user.send_mode
                ) != 0
        ):
            await event.answer(i18n[lang]['length_limit_only_effective_if_send_mode_auto'], alert=True)
            return
        msg = i18n[lang]['set_length_limit_prompt']
        buttons = await inner.customization.get_set_length_limit_buttons(
            sub_or_user, lang=lang, page=page, tail=callback_tail,
        )
        await event.edit(msg, buttons=buttons)
        return

    await event.edit(i18n[lang]['action_invalid'])


@command_gatekeeper(only_manager=False)
async def cmd_set_default(
        event: TypeEventMsgHint,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):  # cmd: set_default
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    user = await db.User.get_or_none(id=chat_id)
    msg = f"{i18n[lang]['set_user_default_description']}\n\n{i18n[lang]['read_formatting_settings_guidebook_html']}"
    buttons = await inner.customization.get_customization_buttons(user, lang=lang, tail=callback_tail)
    await event.respond(msg, buttons=buttons, parse_mode='html', link_preview=False)


@command_gatekeeper(only_manager=False)
async def callback_reset(
        event: TypeEventCb,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):  # callback data = reset={sub_id}
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    sub_id, _, _, page = parse_customization_callback_data(event.data)
    sub = await db.Sub.get_or_none(id=sub_id, user=chat_id)
    if sub is None:
        await event.answer(i18n[lang]['subscription_not_exist'])
        return

    update_interval_flag = False
    if sub.interval is not None:
        sub.interval = None
        update_interval_flag = True
    sub.length_limit = sub.notify = sub.send_mode = sub.link_preview = sub.display_author = sub.display_media = \
        sub.display_title = sub.display_entry_tags = sub.display_via = sub.style = -100
    await sub.save()
    if update_interval_flag:
        await inner.utils.update_interval(sub)
    info = await inner.customization.get_sub_info(sub, lang, additional_guide=True)
    buttons = await inner.customization.get_customization_buttons(sub, lang=lang, page=page, tail=callback_tail)
    await event.edit(info, buttons=buttons, parse_mode='html', link_preview=False)


@command_gatekeeper(only_manager=False)
async def callback_reset_all_confirm(
        event: TypeEventCb,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):  # callback data = reset_all_confirm
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    if await inner.utils.have_subs(chat_id):
        await event.edit(
            i18n[lang]['reset_all_confirm_prompt'],
            buttons=[
                [Button.inline(i18n[lang]['reset_all_confirm'], data=f'reset_all{callback_tail}')],
                [Button.inline(i18n[lang]['reset_all_cancel'], data=f'set_default{callback_tail}')],
            ],
        )
        return
    await event.edit(i18n[lang]['no_subscription'])


@command_gatekeeper(only_manager=False)
async def callback_reset_all(
        event: TypeEventCb,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):  # callback data = reset_all
    chat_id = chat_id or event.chat_id
    subs = await db.Sub.filter(user=chat_id)
    tasks = []
    for sub in subs:
        if sub.interval is not None:
            sub.interval = None
            tasks.append(inner.utils.update_interval(sub))
        sub.interval = None
        sub.length_limit = sub.notify = sub.send_mode = sub.link_preview = sub.display_author = sub.display_media = \
            sub.display_title = sub.display_entry_tags = sub.display_via = sub.style = -100
    await db.Sub.bulk_update(
        subs,
        (
            'interval', 'length_limit', 'notify', 'send_mode', 'link_preview', 'display_author', 'display_media',
            'display_title', 'display_entry_tags', 'display_via', 'style',
        )
    )
    for task in tasks:
        env.loop.create_task(task)
    await event.edit(i18n[lang]['reset_all_successful'])


@command_gatekeeper(only_manager=False)
async def cmd_activate_or_deactivate_subs(
        event: TypeEventMsgHint,
        activate: bool,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):  # cmd: activate_subs | deactivate_subs
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, chat_id=chat_id, page=1)


@command_gatekeeper(only_manager=False)
async def callback_get_activate_or_deactivate_page(
        event: TypeEventCollectionMsgOrCb,
        activate: bool,
        *_,
        lang: Optional[str] = None,
        page: Optional[int] = None,
        chat_id: Optional[int] = None,
        **__,
):  # callback data: get_(activate|deactivate)_page|{page}
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    event_is_msg = not isinstance(event, TypeEventCb)
    if page is None:
        page = 1 if event_is_msg else int(parse_callback_data_with_page(event.data)[1])
    have_subs = await inner.utils.have_subs(chat_id)
    if not have_subs:
        no_subscription_msg = i18n[lang]['no_subscription']
        await (
            event.respond(no_subscription_msg)
            if event_is_msg
            else event.edit(no_subscription_msg)
        )
        return
    sub_buttons = await inner.utils.get_sub_choosing_buttons(
        chat_id,
        page_number=page,
        callback='activate_sub' if activate else 'deactivate_sub',
        get_page_callback='get_activate_page' if activate else 'get_deactivate_page',
        lang=lang,
        rows=11,
        state=0 if activate else 1,
        tail=callback_tail,
    )
    msg = (
        i18n[lang]['choose_sub_to_be_activated' if sub_buttons else 'all_subs_are_activated']
        if activate
        else i18n[lang]['choose_sub_to_be_deactivated' if sub_buttons else 'all_subs_are_deactivated']
    )
    activate_or_deactivate_all_subs_str = 'activate_all_subs' if activate else 'deactivate_all_subs'
    buttons = (
        (Button.inline(
            i18n[lang][activate_or_deactivate_all_subs_str],
            data=f'{activate_or_deactivate_all_subs_str}{callback_tail}',
        ),),
        *sub_buttons,
    ) if sub_buttons else None
    await (
        event.respond(msg, buttons=buttons)
        if event_is_msg
        else event.edit(msg, buttons=buttons)
    )


@command_gatekeeper(only_manager=False)
async def callback_activate_or_deactivate_all_subs(
        event: TypeEventCb,
        activate: bool,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):  # callback data: (activate|deactivate)_all_subs
    chat_id = chat_id or event.chat_id
    await inner.utils.activate_or_deactivate_all_subs(chat_id, activate=activate)
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, chat_id=chat_id, page=1)


@command_gatekeeper(only_manager=False)
async def callback_activate_or_deactivate_sub(
        event: TypeEventCb,
        activate: bool,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):  # callback data: (activate|deactivate)_sub={id}|{page}
    chat_id = chat_id or event.chat_id
    sub_id, page = parse_callback_data_with_page(event.data)
    sub_id = int(sub_id)
    unsub_res = await inner.utils.activate_or_deactivate_sub(chat_id, sub_id, activate=activate)
    if unsub_res is None:
        await event.answer('ERROR: ' + i18n[lang]['subscription_not_exist'], alert=True)
        return
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=page, chat_id=chat_id)


@command_gatekeeper(only_manager=False)
async def callback_del_subs_title(
        event: TypeEventCb,
        *_,
        chat_id: Optional[int] = None,
        **__,
):  # callback data: del_subs_title={id_start}-{id_end}|{id_start}-{id_end}|...
    chat_id = chat_id or event.chat_id
    id_ranges_str = event.data.decode().strip().split('=')[-1].split('%')[0].split('|')
    subs = []
    for id_range_str in id_ranges_str:
        id_range = id_range_str.split('-')
        id_start = int(id_range[0])
        id_end = int(id_range[1])
        subs.extend(await db.Sub.filter(user_id=chat_id, id__range=(id_start, id_end)).all())
    await inner.customization.del_subs_title(subs)
    await misc.callback_del_buttons.__wrapped__(event)


@command_gatekeeper(only_manager=False)
async def cmd_set_title(
        event: TypeEventMsgHint,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    sub, title = await parse_command_get_sub_or_user_and_param(event.raw_text, chat_id, max_split=2)
    title = title.strip() if title else None
    if not sub:
        await event.respond(i18n[lang]['permission_denied_no_direct_use'] % '/set')
        return
    if not title and not sub.title:
        await event.respond(i18n[lang]['cmd_set_title_usage_prompt_html'], parse_mode='html')
        return
    await inner.customization.set_sub_title(sub, title)
    await event.respond(
        '\n\n'.join((
            (
                f"{i18n[lang]['set_title_success']}\n<code>{escape_html(title)}</code>"
                if title
                else i18n[lang]['set_title_success_cleared']
            ),
            await inner.customization.get_sub_info(sub, lang=lang),
        )),
        buttons=(Button.inline(i18n[lang]['other_settings_button'], data=f'set={sub.id}{callback_tail}'),),
        parse_mode='html',
        link_preview=False,
    )


@command_gatekeeper(only_manager=False)
async def cmd_set_interval(
        event: TypeEventMsgHint,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    sub_or_user, interval = await parse_command_get_sub_or_user_and_param(
        event.raw_text, chat_id, allow_setting_user_default=True,
    )
    interval = int(interval) if interval and interval.isdigit() and int(interval) >= 1 else None
    minimal_interval = db.EffectiveOptions.minimal_interval
    if not sub_or_user:
        await event.respond(i18n[lang]['permission_denied_no_direct_use'] % '/set')
        return
    if not interval:
        await event.respond(i18n[lang]['cmd_set_interval_usage_prompt_html'], parse_mode='html')
        return
    if interval < minimal_interval:
        await event.respond(
            i18n[lang]['set_interval_failure_too_small_html'] % minimal_interval, parse_mode='html',
        )
        return
    await inner.customization.set_interval(sub_or_user, interval)
    await event.respond(
        (
            '{msg}\n\n{sub_info}'.format(
                msg=i18n[lang]['set_interval_success_html'] % interval,
                sub_info=await inner.customization.get_sub_info(sub_or_user, lang=lang),
            )
            if isinstance(sub_or_user, db.Sub)
            else i18n[lang]['set_default_interval_success_html'] % interval
        ),
        buttons=(Button.inline(
            i18n[lang]['other_settings_button'],
            data=(f'set={sub_or_user.id}' if isinstance(sub_or_user, db.Sub) else 'set_default') + callback_tail
        ),),
        parse_mode='html',
        link_preview=False,
    )


@command_gatekeeper(only_manager=False)
async def cmd_set_hashtags(
        event: TypeEventMsgHint,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    sub, hashtags = await parse_command_get_sub_or_user_and_param(event.raw_text, chat_id, max_split=2)
    hashtags = inner.utils.parse_hashtags(hashtags) if hashtags else None
    if not sub:
        await event.respond(i18n[lang]['permission_denied_no_direct_use'] % '/set')
        return
    if not hashtags and not sub.tags:
        await event.respond(i18n[lang]['cmd_set_hashtags_usage_prompt_html'], parse_mode='html')
        return
    try:
        await inner.customization.set_sub_hashtags(sub, hashtags)
    except inner.customization.TooManyHashtagsError:
        await event.respond(i18n[lang]['set_hashtags_failure_too_many'])
        return
    await event.respond(
        '\n\n'.join((
            (
                f"{i18n[lang]['set_hashtags_success_html']}\n<b>{inner.utils.construct_hashtags(sub.tags)}</b>"
                if sub.tags
                else i18n[lang]['set_hashtags_success_cleared']
            ),
            await inner.customization.get_sub_info(sub, lang=lang),
        )),
        buttons=(Button.inline(i18n[lang]['other_settings_button'], data=f'set={sub.id}' + callback_tail),),
        parse_mode='html',
        link_preview=False,
    )
