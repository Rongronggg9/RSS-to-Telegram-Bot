from __future__ import annotations
from typing import Optional, Union

from contextlib import suppress
from telethon import events, types, Button
from telethon.tl.patched import Message
from telethon.errors import RPCError

from .. import env, db
from .utils import command_gatekeeper, get_group_migration_help_msg, set_bot_commands, logger, \
    parse_callback_data_with_page
from ..i18n import i18n, ALL_LANGUAGES, get_commands_list
from . import inner


@command_gatekeeper(only_manager=False, ignore_tg_lang=True)
async def cmd_start(event: Union[events.NewMessage.Event, Message], *_, lang=None, **__):
    if lang is None:
        await cmd_lang.__wrapped__(event)
        return
    await cmd_or_callback_help.__wrapped__(event, lang=lang)


@command_gatekeeper(only_manager=False)
async def cmd_lang(event: Union[events.NewMessage.Event, Message], *_, **__):
    buttons, langs = inner.utils.get_lang_buttons(callback='set_lang')
    msg = '\n'.join(f"{i18n[lang]['select_lang_prompt']}" for lang in langs)
    await event.respond(msg, buttons=buttons)


@command_gatekeeper(only_manager=False)
async def callback_set_lang(event: events.CallbackQuery.Event, *_, **__):  # callback data: set_lang={lang_code}
    lang, _ = parse_callback_data_with_page(event.data)
    welcome_msg = i18n[lang]['welcome_prompt']
    await db.User.update_or_create(defaults={'lang': lang}, id=event.chat_id)
    await set_bot_commands(scope=types.BotCommandScopePeer(await event.get_input_chat()),
                           lang_code='',
                           commands=get_commands_list(lang=lang, manager=event.chat_id == env.MANAGER))
    logger.info(f'Changed language to {lang} for {event.chat_id}')
    help_button = Button.inline(text=i18n[lang]['cmd_description_help'], data='help')
    await event.edit(welcome_msg, buttons=help_button)


@command_gatekeeper(only_manager=False)
async def cmd_or_callback_help(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                               *_,
                               lang: Optional[str] = None,
                               **__):  # callback data: help; command: /help
    msg = i18n[lang]['help_msg_html' if event.chat_id != env.MANAGER else 'manager_help_msg_html']
    if event.is_private:
        msg += '\n\n' + i18n[lang]['usage_in_channel_or_group_prompt_html']
    await event.respond(msg, parse_mode='html', link_preview=False) \
        if isinstance(event, events.NewMessage.Event) or not hasattr(event, 'edit') \
        else await event.edit(msg, parse_mode='html', link_preview=False)


@command_gatekeeper(only_manager=False)
async def cmd_version(event: Union[events.NewMessage.Event, Message], *_, **__):
    await event.respond(env.VERSION)


@command_gatekeeper(only_manager=False)
async def callback_cancel(event: events.CallbackQuery.Event,
                          *_,
                          lang: Optional[str] = None,
                          **__):  # callback data = cancel
    await event.edit(i18n[lang]['canceled_by_user'])


@command_gatekeeper(only_manager=False, allow_in_old_fashioned_groups=True)
async def callback_get_group_migration_help(event: events.CallbackQuery.Event,
                                            *_,
                                            **__):  # callback data: get_group_migration_help={lang_code}
    lang, _ = parse_callback_data_with_page(event.data)
    chat = await event.get_chat()
    if not isinstance(chat, types.Chat) or chat.migrated_to:  # already a supergroup
        with suppress(RPCError):
            await event.delete()
        return
    msg, buttons = get_group_migration_help_msg(lang)
    await event.edit(msg, buttons=buttons, parse_mode='html')


# bypassing command gatekeeper
async def callback_null(event: events.CallbackQuery.Event):  # callback data = null
    await event.answer(cache_time=3600)
    raise events.StopPropagation


@command_gatekeeper(only_manager=False)
async def callback_del_buttons(event: events.CallbackQuery.Event,
                               *_,
                               **__):  # callback data = del_buttons
    msg = await event.get_message()
    await event.answer(cache_time=3600)
    await msg.edit(buttons=None)


@command_gatekeeper(only_manager=False, allow_in_others_private_chat=False, quiet=True)
async def inline_command_constructor(event: events.InlineQuery.Event,
                                     *_,
                                     lang: Optional[str] = None,
                                     **__):
    query: types.UpdateBotInlineQuery = event.query
    builder = event.builder
    text = query.query.strip()
    if not text:
        await event.answer(switch_pm=i18n[lang]['permission_denied_input_command'],
                           switch_pm_param=str(event.id),
                           cache_time=3600,
                           private=False)
        return
    await event.answer(results=[builder.article(title=text, text=text)],
                       cache_time=3600,
                       private=False)
