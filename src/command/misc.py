#  RSS to Telegram Bot
#  Copyright (C) 2022-2024  Rongrong <i@rong.moe>
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

from contextlib import suppress
from telethon import events, types, Button
from telethon.errors import RPCError

from .. import env, db
from .utils import (
    command_gatekeeper, get_group_migration_help_msg, set_bot_commands, logger, parse_callback_data_with_page,
    get_callback_tail,
)
from ..i18n import i18n, get_commands_list
from . import inner
from .types import *


@command_gatekeeper(only_manager=False, ignore_tg_lang=True)
async def cmd_start(
        event: TypeEventCollectionMsgOrChatAction,
        *_,
        lang=None,
        **__,
):
    if lang is None:
        await cmd_lang.__wrapped__(event)
        return
    await cmd_or_callback_help.__wrapped__(event, lang=lang)


@command_gatekeeper(only_manager=False)
async def cmd_lang(
        event: TypeEventCollectionMsgOrChatAction,
        *_,
        chat_id: Optional[int] = None,
        **__,
):
    chat_id = chat_id or event.chat_id
    callback_tail = get_callback_tail(event, chat_id)
    buttons, langs = inner.utils.get_lang_buttons(callback='set_lang', tail=callback_tail)
    msg = '\n'.join(f"{i18n[lang]['select_lang_prompt']}" for lang in langs)
    await event.respond(msg, buttons=buttons)


@command_gatekeeper(only_manager=False)
async def callback_set_lang(
        event: TypeEventCb,
        *_,
        chat_id: Optional[int] = None,
        **__,
):  # callback data: set_lang={lang_code}
    chat_id = chat_id or event.chat_id
    lang, _ = parse_callback_data_with_page(event.data)
    welcome_msg = i18n[lang]['welcome_prompt']
    await db.User.update_or_create(defaults={'lang': lang}, id=chat_id)
    await set_bot_commands(
        scope=types.BotCommandScopePeer(await event.get_input_chat()),
        lang_code='',
        commands=get_commands_list(lang=lang, manager=chat_id in env.MANAGER),
    )
    logger.info(f'Changed language to {lang} for {chat_id}')
    help_button = Button.inline(text=i18n[lang]['cmd_description_help'], data='help')
    await event.edit(welcome_msg, buttons=help_button)


@command_gatekeeper(only_manager=False)
async def cmd_or_callback_help(
        event: TypeEventCollectionMsgLike,
        *_,
        lang: Optional[str] = None,
        **__,
):  # callback data: help; command: /help
    msg = i18n[lang]['manager_help_msg_html' if event.chat_id in env.MANAGER else 'help_msg_html']
    if event.is_private:
        msg += '\n\n' + i18n[lang]['usage_in_channel_or_group_prompt_html']
    await (
        event.respond(msg, parse_mode='html', link_preview=False)
        if isinstance(event, TypeEventMsg) or not hasattr(event, 'edit')
        else event.edit(msg, parse_mode='html', link_preview=False)
    )


@command_gatekeeper(only_manager=False)
async def cmd_version(event: TypeEventMsgHint, *_, **__):
    await event.respond(env.VERSION)


@command_gatekeeper(only_manager=False)
async def callback_cancel(
        event: TypeEventCb,
        *_,
        lang: Optional[str] = None,
        **__,
):  # callback data = cancel
    await event.edit(i18n[lang]['canceled_by_user'])


@command_gatekeeper(only_manager=False, allow_in_old_fashioned_groups=True)
async def callback_get_group_migration_help(
        event: TypeEventCb,
        *_,
        **__,
):  # callback data: get_group_migration_help={lang_code}
    lang, _ = parse_callback_data_with_page(event.data)
    chat = await event.get_chat()
    if not isinstance(chat, types.Chat) or chat.migrated_to:  # already a supergroup
        with suppress(RPCError):
            await event.delete()
        return
    msg, buttons = get_group_migration_help_msg(lang)
    await event.edit(msg, buttons=buttons, parse_mode='html')


# bypassing command gatekeeper
async def callback_null(event: TypeEventCb):  # callback data = null
    await event.answer(cache_time=3600)
    raise events.StopPropagation


@command_gatekeeper(only_manager=False)
async def callback_del_buttons(
        event: TypeEventCb,
        *_,
        **__,
):  # callback data = del_buttons
    msg = await event.get_message()
    await event.answer(cache_time=3600)
    await msg.edit(buttons=None)


@command_gatekeeper(only_manager=False, allow_in_others_private_chat=False, quiet=True)
async def inline_command_constructor(
        event: TypeEventInline,
        *_,
        lang: Optional[str] = None,
        **__,
):
    query: types.UpdateBotInlineQuery = event.query
    builder = event.builder
    text = query.query.strip()
    if not text:
        await event.answer(
            switch_pm=i18n[lang]['permission_denied_input_command'],
            switch_pm_param=str(event.id),
            cache_time=3600,
            private=False,
        )
        return
    await event.answer(
        results=[builder.article(title=text, text=text)],
        cache_time=3600,
        private=False,
    )
