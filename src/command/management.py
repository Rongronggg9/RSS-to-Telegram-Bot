import asyncio
from typing import Union, Optional
from telethon import events, Button
from telethon.tl.custom import Message
from telethon.tl import types

from src import env, web, db
from src.i18n import i18n, ALL_LANGUAGES
from .utils import permission_required, parse_command, logger, escape_html, set_bot_commands, get_commands_list
from . import inner
from ..parsing.post import get_post_from_entry


@permission_required(only_manager=False)
async def cmd_start(event: Union[events.NewMessage.Event, Message], lang=None, *args, **kwargs):
    if lang is None:
        await cmd_lang.__wrapped__(event)
        return
    await cmd_help.__wrapped__(event, lang)


@permission_required(only_manager=False)
async def cmd_lang(event: Union[events.NewMessage.Event, Message], *args, **kwargs):
    msg = '\n'.join(f"{i18n[lang]['select_lang_prompt']}"
                    for lang in ALL_LANGUAGES)
    buttons = inner.utils.arrange_grid((Button.inline(i18n[lang]['lang_native_name'], data=f'set_lang_{lang}')
                                        for lang in ALL_LANGUAGES),
                                       columns=3)
    await event.respond(msg, buttons=buttons)


@permission_required(only_manager=False)
async def callback_set_lang(event: events.CallbackQuery.Event, *args, **kwargs):  # callback data: set_lang_{lang_code}
    lang = event.data.decode().strip().split('set_lang_')[-1]
    welcome_msg = i18n[lang]['welcome_prompt']
    await db.User.update_or_create(defaults={'lang': lang}, id=event.chat_id)
    await set_bot_commands(scope=types.BotCommandScopePeer(await event.get_input_chat()),
                           lang_code='',
                           commands=get_commands_list(lang=lang, manager=event.chat_id == env.MANAGER))
    logger.info(f'Changed language to {lang} for {event.chat_id}')
    await event.edit(welcome_msg)


@permission_required(only_manager=False)
async def cmd_help(event: Union[events.NewMessage.Event, Message], lang: Optional[str] = None, *args, **kwargs):
    await event.respond(
        f"<a href='https://github.com/Rongronggg9/RSS-to-Telegram-Bot'>{escape_html(i18n[lang]['rsstt_slogan'])}</a>\n"
        f"\n"
        f"{escape_html(i18n[lang]['commands'])}:\n"
        f"<b>/sub</b>: {escape_html(i18n[lang]['cmd_description_sub'])}\n"
        f"<b>/unsub</b>: {escape_html(i18n[lang]['cmd_description_unsub'])}\n"
        f"<b>/unsub_all</b>: {escape_html(i18n[lang]['cmd_description_unsub_all'])}\n"
        f"<b>/list</b>: {escape_html(i18n[lang]['cmd_description_list'])}\n"
        f"<b>/import</b>: {escape_html(i18n[lang]['cmd_description_import'])}\n"
        f"<b>/export</b>: {escape_html(i18n[lang]['cmd_description_export'])}\n"
        f"<b>/version</b>: {escape_html(i18n[lang]['cmd_description_version'])}\n"
        f"<b>/lang</b>: {escape_html(' / '.join(i18n[_lang]['cmd_description_lang'] for _lang in ALL_LANGUAGES))}\n"
        f"<b>/help</b>: {escape_html(i18n[lang]['cmd_description_help'])}\n\n",
        parse_mode='html'
    )


@permission_required(only_manager=True)
async def cmd_test(event: Union[events.NewMessage.Event, Message], lang: Optional[str] = None, *args, **kwargs):
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
async def cmd_version(event: Union[events.NewMessage.Event, Message], *args, **kwargs):
    await event.respond(env.VERSION)
