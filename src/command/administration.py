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
from typing import Optional
from typing_extensions import Final

import asyncio
import re
from telethon import Button
from telethon.tl import types
from telethon.utils import get_peer_id

from .. import web, db, env
from ..i18n import i18n
from ..parsing.post import get_post_from_entry
from .utils import command_gatekeeper, parse_command, logger, parse_customization_callback_data
from . import inner
from .types import *

SELECTED_EMOJI: Final = '🔘'
UNSELECTED_EMOJI: Final = '⚪️'

parseKeyValuePair = re.compile(r'^/\S+\s+([^\s=]+)(?:\s*=\s*|\s+)?(.+)?$')


@command_gatekeeper(only_manager=True)
async def cmd_set_option(event: TypeEventMsgHint, *_, lang: Optional[str] = None, **__):
    kv = parseKeyValuePair.match(event.raw_text)
    if not kv:  # return options info
        options = db.EffectiveOptions.options
        msg = '\n\n'.join((
            f'<b>{i18n[lang]["current_options"]}</b>',
            '\n'.join(
                f'<code>{key}</code> = <code>{value}</code> '
                f'({i18n[lang]["option_value_type"]}: <code>{type(value).__name__}</code>)'
                for key, value in options.items()
            ),
            i18n[lang]['cmd_set_option_usage_prompt_html'],
        ))
        await event.respond(msg, parse_mode='html')
        return
    key, value = kv.groups()

    try:
        await db.EffectiveOptions.set(key, value)
    except KeyError:
        await event.respond(f'ERROR: {i18n[lang]["option_key_invalid"]}')
        return
    except TypeError as e:
        await event.respond(f'ERROR: {i18n[lang]["option_value_invalid"]}\n\n{e}')
        return

    value = db.EffectiveOptions.get(key)

    logger.info(f"Set option {key} to {value}")

    if key == 'default_interval':
        all_feeds = await db.Feed.filter(state=1)
        for feed in all_feeds:
            env.loop.create_task(inner.utils.update_interval(feed))
        logger.info("Flushed the interval of all feeds")

    await event.respond(
        f'<b>{i18n[lang]["option_updated"]}</b>\n'
        f'<code>{key}</code> = <code>{value}</code>',
        parse_mode='html',
    )


@command_gatekeeper(only_manager=True, only_in_private_chat=False, timeout=None if env.DEBUG else 300)
async def cmd_test(
        event: TypeEventMsgHint,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):
    chat_id = chat_id or event.chat_id

    args = parse_command(event.raw_text)
    if len(args) < 2:
        await event.respond(i18n[lang]['cmd_test_usage_prompt_html'], parse_mode='html')
        return
    url = args[1]

    if len(args) > 2 and args[2] == 'all':
        start = 0
        end = None
    elif len(args) == 3:
        start = int(args[2])
        end = int(args[2]) + 1
    elif len(args) == 4:
        start = int(args[2])
        end = int(args[3])
    else:
        start = 0
        end = 1

    try:
        wf = await web.feed_get(url, web_semaphore=False)
        rss_d = wf.rss_d

        if rss_d is None:
            await event.respond(wf.error.i18n_message(lang))
            return

        if start == -1 and end == 0:
            end = len(rss_d.entries)

        entries_to_send = rss_d.entries[start:end]

        if len(entries_to_send) == 0:
            await event.respond(i18n[lang]['action_invalid'])
            return

        await asyncio.gather(
            *(
                __send(chat_id, entry, rss_d.feed.title, wf.url)
                for entry in entries_to_send
            )
        )

    except Exception as e:
        logger.warning("Sending failed:", exc_info=e)
        await event.respond('ERROR: ' + i18n[lang]['internal_error'])
        return


async def __send(chat_id, entry, feed_title, link):
    post = await get_post_from_entry(entry, feed_title, link)
    logger.debug(f"Sending {entry.get('title', 'Untitled')} ({entry.get('link', 'No link')}) to {chat_id}...")
    await post.test_format(chat_id)


@command_gatekeeper(only_manager=True)
async def cmd_user_info_or_callback_set_user(
        event: TypeEventCollectionMsgOrCb,
        *_,
        lang: Optional[str] = None,
        user_id: Optional[int] = None,
        **__,
):
    """
    command = `/user_info user_id` or `/user_info @username` or `/user_info`
    callback data = set_user={user_id},{state}
    """
    is_callback = isinstance(event, TypeEventCb)
    if user_id:
        state = None
        user_entity_like = user_id
    elif is_callback:
        user_entity_like, state, _, _ = parse_customization_callback_data(event.data)
        assert user_entity_like is not None
        state = int(state)
    else:
        state = None
        args = parse_command(event.raw_text, strip_target_chat=False)
        if (
                len(args) < 2
                or
                not (
                        args[1].lstrip('-').isdecimal()
                        or
                        args[1].startswith('@')
                )

        ):
            await event.respond(i18n[lang]['cmd_user_info_usage_prompt_html'], parse_mode='html')
            return
        user_entity_like = int(args[1]) if args[1].lstrip('-').isdecimal() else args[1].lstrip('@')

    try:
        entity = await env.bot.get_entity(user_entity_like)
        if isinstance(entity, types.User):
            username = entity.username
            name = entity.first_name + (f' {entity.last_name}' if entity.last_name else '')
            user_type = i18n[lang]['user']
            participant_count = None
        elif isinstance(entity, types.Channel):
            username = entity.username
            name = entity.title
            user_type = i18n[lang]['channel'] if entity.broadcast else i18n[lang]['group']
            participant_count = entity.participants_count
        else:
            # refuse to handle other types of entities
            raise ValueError(f"Unknown type: {type(entity)}")
        user_id = get_peer_id(peer=entity)
    except ValueError:
        if not isinstance(user_entity_like, int):
            await event.respond(i18n[lang]['user_not_found'], parse_mode='html')
            return
        name = username = participant_count = None
        user_id = user_entity_like
        user_type = i18n[lang]['user'] if user_id > 0 else None

    user, user_created = await db.User.get_or_create(id=user_id, defaults={'lang': 'null'})
    if state is not None:
        user.state = state
        await user.save()
    state = None if user_id in env.MANAGER else user.state
    default_sub_limit = (
        db.EffectiveOptions.user_sub_limit
        if user_id > 0
        else db.EffectiveOptions.channel_or_group_sub_limit
    )
    if user_created:
        sub_count = 0
        sub_limit = default_sub_limit
        is_default_limit = True
    else:
        _, sub_count, sub_limit, is_default_limit = await inner.utils.check_sub_limit(user_id, force_count_current=True)

    msg_text = '\n\n'.join(filter(None, (
        f"<b>{i18n[lang]['user_info']}</b>",
        '\n'.join(filter(None, (
            name,
            (f'{user_type} ' if user_type else '') + f'<code>{user_id}</code>',
            f'@{username}' if username else '',
        ))),
        '\n'.join(filter(None, (
            f"{i18n[lang]['sub_count']}: {sub_count}",
            f"{i18n[lang]['sub_limit']}: {sub_limit if sub_limit > 0 else i18n[lang]['sub_limit_unlimited']}" + (
                f" ({i18n[lang]['sub_limit_default']})" if is_default_limit else ''
            ),
            f"{i18n[lang]['participant_count']}: {participant_count}" if participant_count else '',
        ))),
        ''
        if state is None
        else f"{i18n[lang]['user_state']}: {i18n[lang][f'user_state_{state}']} "
             f"({i18n[lang][f'user_state_description_{state}']})",
    )))
    buttons = (
        None
        if user_id in env.MANAGER
        else tuple(filter(None, (
            *(
                (Button.inline(
                    '{emoji}{prompt} "{state}"'.format(
                        emoji=SELECTED_EMOJI if user.state == btn_state else UNSELECTED_EMOJI,
                        prompt=i18n[lang]['set_user_state_as'],
                        state=i18n[lang][f'user_state_{btn_state}'],
                    ),
                    data='null' if user.state == btn_state else f"set_user={user_id},{btn_state}"
                ),)
                for btn_state in range(-1, 2)
            ),
            None
            if is_default_limit
            else (Button.inline(
                f"{i18n[lang]['reset_sub_limit_to_default']} "
                f"({default_sub_limit if default_sub_limit > 0 else i18n[lang]['sub_limit_unlimited']})",
                data=f"reset_sub_limit={user_id}",
            ),),
            (Button.switch_inline(
                i18n[lang]['set_sub_limit_to'],
                query=f'/set_sub_limit {user_id} ',
                same_peer=True,
            ),),
        )))
    )
    await (
        event.edit(msg_text, parse_mode='html', buttons=buttons)
        if is_callback
        else event.respond(msg_text, parse_mode='html', buttons=buttons)
    )


@command_gatekeeper(only_manager=True)
async def callback_reset_sub_limit(event: TypeEventCb, *_, lang: Optional[str] = None, **__):
    """
    callback data = reset_sub_limit={user_id}
    """
    user_id = int(parse_customization_callback_data(event.data)[0])
    user = await db.User.get_or_none(id=user_id)
    if user:
        user.sub_limit = None
        await user.save()
    await cmd_user_info_or_callback_set_user.__wrapped__(event, user_id=user_id, lang=lang)
    return


@command_gatekeeper(only_manager=True)
async def cmd_set_sub_limit(event: TypeEventMsgHint, *_, lang: Optional[str] = None, **__):
    """
    command = `/set_sub_limit user_id sub_limit`
    """
    args = parse_command(event.raw_text, strip_target_chat=False, strip_inline_header=True)
    if len(args) < 2 or not args[1].lstrip('-').isdecimal():
        await event.respond(i18n[lang]['permission_denied_no_direct_use'] % '/user_info')
        return
    if len(args) < 3 or not args[2].lstrip('-').isdecimal():
        await event.respond(i18n[lang]['cmd_set_sub_limit_prompt_html'], parse_mode='html')
        return
    user_id, sub_limit = int(args[1]), int(args[2])
    sub_limit = max(sub_limit, -1)
    user, user_created = await db.User.get_or_create(id=user_id, defaults={'lang': 'null', 'sub_limit': sub_limit})
    if not user_created:
        user.sub_limit = sub_limit
        await user.save()
    await cmd_user_info_or_callback_set_user.__wrapped__(event, user_id=user_id, lang=lang)
    return
