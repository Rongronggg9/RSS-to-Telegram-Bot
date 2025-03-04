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

import listparser
from datetime import datetime, timezone
from functools import partial
from telethon import Button
from telethon.tl import types
from telethon.tl.patched import Message

from .. import env, db
from ..compat import bozo_exception_removal_wrapper
from ..aio_helper import run_async
from ..i18n import i18n
from . import inner
from .types import *
from .utils import command_gatekeeper, logger, send_success_and_failure_msg, get_callback_tail, check_sub_limit


@command_gatekeeper(only_manager=False)
async def cmd_import(
        event: TypeEventMsgHint,
        *_,
        chat_id: Optional[int] = None,
        lang: Optional[str] = None,
        **__,
):
    chat_id = chat_id or event.chat_id

    await check_sub_limit(event, user_id=chat_id, lang=lang)

    await event.respond(
        '\n\n'.join(filter(None, (
            i18n[lang]['send_opml_prompt'],
            i18n[lang]['import_for_channel_or_group_prompt'] if event.is_private else '',
        ))),
        buttons=(
            Button.force_reply(
                single_use=True,
                selective=True,
                placeholder=i18n[lang]['send_opml_reply_placeholder'],
            )
            if event.is_group and chat_id == event.chat_id
            else None
        ),
        reply_to=event.id if event.is_group else None
    )


@command_gatekeeper(only_manager=False)
async def cmd_export(
        event: TypeEventMsgHint,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):
    chat_id = chat_id or event.chat_id
    opml_file = await inner.sub.export_opml(chat_id)
    if opml_file is None:
        await event.respond(i18n[lang]['no_subscription'])
        return
    await event.respond(
        file=opml_file,
        attributes=(
            types.DocumentAttributeFilename(f"RSStT_export_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.opml"),
        ),
    )


@command_gatekeeper(only_manager=False, timeout=300)
async def opml_import(
        event: TypeEventMsgHint,
        *_,
        lang: Optional[str] = None,
        chat_id: Optional[int] = None,
        **__,
):
    chat_id = chat_id or event.chat_id

    reply_message: Optional[Message] = await event.get_reply_message()
    if reply_message and reply_message.sender_id == env.bot_id:
        if isinstance(reply_message.reply_markup, types.ReplyKeyboardForceReply):
            env.loop.create_task(reply_message.delete())
    elif event.is_group:  # in group but not a reply to the bot
        return  # only respond to reply in groups

    await check_sub_limit(event, user_id=chat_id, lang=lang)

    try:
        opml_file: bytes = await event.download_media(file=bytes)
    except Exception as e:
        await event.reply('ERROR: ' + i18n[lang]['fetch_file_failed'])
        logger.warning(f'Failed to get opml file from {chat_id}: ', exc_info=e)
        return

    reply: Message = await event.reply(
        '\n'.join((
            i18n[lang]['processing'],
            i18n[lang]['opml_import_processing'],
        ))
    )
    logger.info(f'Got an opml file from {chat_id}')

    opml_d = await run_async(
        partial(
            bozo_exception_removal_wrapper,
            listparser.parse, opml_file,
        ),
        prefer_pool='thread' if len(opml_file) < 64 * 1024 else None,
    )
    if not opml_d.feeds:
        await reply.edit('ERROR: ' + i18n[lang]['opml_parse_error'])
        logger.warning(f'Failed to parse opml file from {chat_id}')
        return

    import_result = await inner.sub.subs(
        chat_id,
        tuple(
            (
                (feed.url, feed.text)
                if feed.text and feed.text != feed.title_orig
                else feed.url
            ) for feed in opml_d.feeds
        ),
        lang=lang
    )
    logger.info(f'Imported feed(s) for {chat_id}')
    msg = await send_success_and_failure_msg(reply, **import_result, lang=lang, edit=True)

    subs = tuple(sub_d['sub'] for sub_d in import_result['sub_d_l'] if sub_d['sub'])
    if subs:
        if not sum(sub.title is not None for sub in subs):
            return  # no subscription set custom title
        sub_ids: list[int] = sorted(sub.id for sub in subs if sub.id)
        sub_ranges: list[tuple[int, int]] = []
        curr_start = sub_ids[0]
        while sub_ids:
            curr_id = sub_ids.pop(0)
            if not sub_ids:
                sub_ranges.append((curr_start or curr_id, curr_id))
                break
            next_id = sub_ids[0]
            if next_id in [curr_id + 1, curr_id]:
                continue
            elif sum(sub.title is not None for sub in subs
                     if sub.id in range(curr_start, curr_id + 1)):  # if any sub has custom title
                subs_between_w_title_count = await db.Sub.filter(
                    user_id=chat_id,
                    id__in=(curr_id + 1, next_id - 1),
                    title__not_isnull=True,
                ).count()
                if not subs_between_w_title_count:
                    continue
                sub_ranges.append((curr_start, curr_id))
                curr_start = next_id
            else:
                curr_start = next_id

        if not sub_ranges:
            return  # no subscription set custom title

        button_data = ''.join((
            'del_subs_title=',
            '|'.join(f'{start}-{end}' for start, end in sub_ranges),
            get_callback_tail(event, chat_id),
        ))
        if len(button_data) <= 64:  # Telegram API limit
            button = [
                [Button.inline(i18n[lang]['delete_subs_title_button'], button_data)],
                [Button.inline(i18n[lang]['keep_subs_title_button'], 'del_buttons')],
            ]
            await msg.edit(text=msg.text, buttons=button)
