from __future__ import annotations
from typing import Union, Optional

import listparser
from datetime import datetime
from telethon import events, Button
from telethon.tl import types
from telethon.tl.patched import Message

from .. import env, db
from ..i18n import i18n
from . import inner
from .utils import command_gatekeeper, logger, send_success_and_failure_msg, get_callback_tail


@command_gatekeeper(only_manager=False)
async def cmd_import(event: Union[events.NewMessage.Event, Message],
                     *_,
                     lang: Optional[str] = None,
                     **__):
    await event.respond(
        i18n[lang]['send_opml_prompt'] + (
            '\n\n'
            + i18n[lang]['import_for_channel_or_group_prompt'] if event.is_private else ''
        ),
        buttons=Button.force_reply(single_use=True,
                                   selective=True,
                                   placeholder=i18n[lang]['send_opml_reply_placeholder']),
        reply_to=event.id if event.is_group else None
    )


@command_gatekeeper(only_manager=False)
async def cmd_export(event: Union[events.NewMessage.Event, Message],
                     *_,
                     lang: Optional[str] = None,
                     chat_id: Optional[int] = None,
                     **__):
    chat_id = chat_id or event.chat_id
    opml_file = await inner.sub.export_opml(chat_id)
    if opml_file is None:
        await event.respond(i18n[lang]['no_subscription'])
        return
    await event.respond(file=opml_file,
                        attributes=(types.DocumentAttributeFilename(
                            f"RSStT_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.opml"),))


@command_gatekeeper(only_manager=False, timeout=300)
async def opml_import(event: Union[events.NewMessage.Event, Message],
                      *_,
                      lang: Optional[str] = None,
                      chat_id: Optional[int] = None,
                      **__):
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    reply_message: Message = await event.get_reply_message()
    if not (event.is_private or event.is_channel and not event.is_group) and reply_message.sender_id != env.bot_id:
        return  # must reply to the bot in a group to import opml
    try:
        opml_file = await event.download_media(file=bytes)
    except Exception as e:
        await event.reply('ERROR: ' + i18n[lang]['fetch_file_failed'])
        logger.warning(f'Failed to get opml file from {chat_id}: ', exc_info=e)
        return

    reply: Message = await event.reply(i18n[lang]['processing'] + '\n' + i18n[lang]['opml_import_processing'])
    logger.info(f'Got an opml file from {chat_id}')

    opml_d = listparser.parse(opml_file.decode())
    if not opml_d.feeds:
        await reply.edit('ERROR: ' + i18n[lang]['opml_parse_error'])
        return

    import_result = await inner.sub.subs(chat_id,
                                         tuple((feed.url, feed.title) for feed in opml_d.feeds),
                                         lang=lang)
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
                sub_ranges.append((curr_start if curr_start else curr_id, curr_id))
                break
            next_id = sub_ids[0]
            if next_id == curr_id + 1 or next_id == curr_id:
                continue
            elif sum(sub.title is not None for sub in subs
                     if sub.id in range(curr_start, curr_id + 1)):  # if any sub has custom title
                subs_between_w_title_count = await db.Sub.filter(user_id=chat_id,
                                                                 id__in=(curr_id + 1, next_id - 1),
                                                                 title__not_isnull=True).count()
                if not subs_between_w_title_count:
                    continue
                sub_ranges.append((curr_start, curr_id))
                curr_start = next_id
            else:
                curr_start = next_id

        if not sub_ranges:
            return  # no subscription set custom title

        button_data = f'del_subs_title=' + '|'.join(f'{start}-{end}' for start, end in sub_ranges) + callback_tail
        if len(button_data) <= 64:  # Telegram API limit
            button = [
                [Button.inline(i18n[lang]['delete_subs_title_button'], button_data)],
                [Button.inline(i18n[lang]['keep_subs_title_button'], 'del_buttons')],
            ]
            await msg.edit(text=msg.text, buttons=button)
