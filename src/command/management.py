import asyncio
from typing import Union, Optional
from telethon import events, Button
from telethon.tl.patched import Message
from telethon.tl import types

from src import env, web, db
from src.i18n import i18n, ALL_LANGUAGES
from .utils import permission_required, parse_command, logger, set_bot_commands, get_commands_list, \
    parse_callback_data_with_page
from . import inner
from ..parsing.post import get_post_from_entry


@permission_required(only_manager=False, ignore_tg_lang=True)
async def cmd_start(event: Union[events.NewMessage.Event, Message], *args, lang=None, **kwargs):
    if lang is None:
        await cmd_lang.__wrapped__(event)
        return
    await cmd_or_callback_help.__wrapped__(event, lang=lang)


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
    help_button = Button.inline(text=i18n[lang]['cmd_description_help'], data='help')
    await event.edit(welcome_msg, buttons=help_button)


@permission_required(only_manager=False)
async def cmd_activate_or_deactivate_subs(event: Union[events.NewMessage.Event, Message],
                                          activate: bool,
                                          *args,
                                          lang: Optional[str] = None,
                                          **kwargs):  # cmd: activate_subs | deactivate_subs
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=1)


@permission_required(only_manager=False)
async def callback_get_activate_or_deactivate_page(event: Union[events.CallbackQuery.Event,
                                                                events.NewMessage.Event,
                                                                Message],
                                                   activate: bool,
                                                   *args,
                                                   lang: Optional[str] = None,
                                                   page: Optional[int] = None,
                                                   **kwargs):  # callback data: get_(activate|deactivate)_page_{page}
    event_is_msg = not isinstance(event, events.CallbackQuery.Event)
    origin_msg = None  # placeholder
    if not event_is_msg:
        origin_msg = (await event.get_message()).text
    if page is None:
        page = int(event.data.decode().strip().split('_')[-1]) if not event_is_msg else 1
    have_subs = await inner.utils.have_subs(event.chat_id)
    if not have_subs:
        no_subscription_msg = i18n[lang]['no_subscription']
        await (event.respond(no_subscription_msg) if event_is_msg
               else event.edit(no_subscription_msg if not no_subscription_msg == origin_msg else None))
        return
    sub_buttons = await inner.utils.get_sub_choosing_buttons(
        event.chat_id,
        page=page,
        callback='activate_sub' if activate else 'deactivate_sub',
        get_page_callback='get_activate_page' if activate else 'get_deactivate_page',
        lang=lang,
        rows=11,
        state=0 if activate else 1
    )
    msg = i18n[lang]['choose_sub_to_be_activated' if sub_buttons else 'all_subs_are_activated'] if activate \
        else i18n[lang]['choose_sub_to_be_deactivated' if sub_buttons else 'all_subs_are_deactivated']
    activate_or_deactivate_all_subs_str = 'activate_all_subs' if activate else 'deactivate_all_subs'
    buttons = (
            (
                (Button.inline(i18n[lang][activate_or_deactivate_all_subs_str],
                               data=activate_or_deactivate_all_subs_str),),
            )
            + sub_buttons
    ) if sub_buttons else None
    await (event.respond(msg, buttons=buttons) if event_is_msg
           else event.edit(msg if not msg == origin_msg else None, buttons=buttons))


@permission_required(only_manager=False)
async def callback_activate_or_deactivate_all_subs(event: events.CallbackQuery.Event,
                                                   activate: bool,
                                                   *args,
                                                   lang: Optional[str] = None,
                                                   **kwargs):  # callback data: (activate|deactivate)_all_subs
    await inner.utils.activate_or_deactivate_all_subs(event.chat_id, activate=activate)
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=1)


@permission_required(only_manager=False)
async def callback_activate_or_deactivate_sub(event: events.CallbackQuery.Event,
                                              activate: bool,
                                              *args,
                                              lang: Optional[str] = None,
                                              **kwargs):  # callback data: (activate|deactivate)_sub_{id}|{page}
    sub_id, page = parse_callback_data_with_page(event.data)
    unsub_res = await inner.utils.activate_or_deactivate_sub(event.chat_id, sub_id, activate=activate)
    if unsub_res is None:
        await event.answer('ERROR: ' + i18n[lang]['subscription_not_exist'], alert=True)
        return
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=page)


@permission_required(only_manager=False)
async def cmd_or_callback_help(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                               *args,
                               lang: Optional[str] = None,
                               **kwargs):  # callback data: help; command: /help
    msg = i18n[lang]['help_msg_html']
    await event.respond(msg, parse_mode='html') if isinstance(event, events.NewMessage.Event) \
        else await event.edit(msg, parse_mode='html')


@permission_required(only_manager=True)
async def cmd_test(event: Union[events.NewMessage.Event, Message], *args, lang: Optional[str] = None, **kwargs):
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
