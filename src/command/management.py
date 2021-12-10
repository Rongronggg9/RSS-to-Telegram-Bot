import asyncio
from typing import Union, Optional
from telethon import events, Button
from telethon.tl.patched import Message
from telethon.tl import types

from src import env, web, db
from src.i18n import i18n, ALL_LANGUAGES
from .utils import permission_required, parse_command, logger, set_bot_commands, get_commands_list
from . import inner
from ..parsing.post import get_post_from_entry


@permission_required(only_manager=False, ignore_tg_lang=True)
async def cmd_start(event: Union[events.NewMessage.Event, Message], *_, lang=None, **__):
    if lang is None:
        await cmd_lang.__wrapped__(event)
        return
    await cmd_or_callback_help.__wrapped__(event, lang=lang)


@permission_required(only_manager=False)
async def cmd_lang(event: Union[events.NewMessage.Event, Message], *_, **__):
    msg = '\n'.join(f"{i18n[lang]['select_lang_prompt']}"
                    for lang in ALL_LANGUAGES)
    buttons = inner.utils.arrange_grid((Button.inline(i18n[lang]['lang_native_name'], data=f'set_lang_{lang}')
                                        for lang in ALL_LANGUAGES),
                                       columns=3)
    await event.respond(msg, buttons=buttons)


@permission_required(only_manager=False)
async def callback_set_lang(event: events.CallbackQuery.Event, *_, **__):  # callback data: set_lang_{lang_code}
    lang = event.data.decode().strip().split('set_lang_')[-1]
    welcome_msg = i18n[lang]['welcome_prompt']
    await db.User.update_or_create(defaults={'lang': lang}, id=event.chat_id)
    await set_bot_commands(scope=types.BotCommandScopePeer(await event.get_input_chat()),
                           lang_code='',
                           commands=get_commands_list(lang=lang, manager=event.chat_id == env.MANAGER))
    logger.info(f'Changed language to {lang} for {event.chat_id}')
    help_button = Button.inline(text=i18n[lang]['cmd_description_help'], data='help')
    await event.edit(welcome_msg, buttons=help_button)


@permission_required(only_manager=False)
async def cmd_or_callback_help(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                               *_,
                               lang: Optional[str] = None,
                               **__):  # callback data: help; command: /help
    msg = i18n[lang]['help_msg_html']
    await event.respond(msg, parse_mode='html') if isinstance(event, events.NewMessage.Event) \
        else await event.edit(msg, parse_mode='html')


@permission_required(only_manager=True)
async def cmd_test(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    args = parse_command(event.text)
    if len(args) < 2:
        await event.respond('ERROR: ' + i18n[lang]['test_command_usage_prompt'])
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
        end = int(args[3]) + 1
    else:
        start = 0
        end = 1

    uid = event.chat_id

    try:
        d = await web.feed_get(url, web_semaphore=False)
        rss_d = d['rss_d']

        if rss_d is None:
            await event.respond(d['msg'])
            return

        if start >= len(rss_d.entries):
            start = 0
            end = 1
        elif end is not None and start > 0 and start >= end:
            end = start + 1

        entries_to_send = rss_d.entries[start:end]

        await asyncio.gather(
            *(__send(uid, entry, rss_d.feed.title, url) for entry in entries_to_send)
        )

    except Exception as e:
        logger.warning(f"Sending failed:", exc_info=e)
        await event.respond('ERROR: ' + i18n[lang]['internal_error'])
        return


async def __send(uid, entry, feed_title, link):
    post = get_post_from_entry(entry, feed_title, link)
    await post.generate_message()
    logger.debug(f"Sending {entry['title']} ({entry['link']})...")
    await post.send_message(uid)


@permission_required(only_manager=False)
async def cmd_version(event: Union[events.NewMessage.Event, Message], *_, **__):
    await event.respond(env.VERSION)
