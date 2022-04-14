from __future__ import annotations
from typing import Union, Optional

import asyncio
from telethon import events, Button
from telethon.tl.patched import Message
from telethon.tl import types
from telethon.utils import get_peer_id

from .. import web, db, env
from ..i18n import i18n
from ..parsing.post import get_post_from_entry
from .utils import command_gatekeeper, parse_command, logger, parse_customization_callback_data
from . import inner


@command_gatekeeper(only_manager=True)
async def cmd_set_option(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    raw_text = event.raw_text.replace('=', ' ')
    args = parse_command(raw_text)
    if len(args) < 3:  # return options info
        options = db.EffectiveOptions.options
        msg = (
                f'<b>{i18n[lang]["current_options"]}</b>\n\n'
                + '\n'.join(f'<code>{key}</code> = <code>{value}</code> '
                            f'({i18n[lang]["option_value_type"]}: <code>{type(value).__name__}</code>)'
                            for key, value in options.items())
                + '\n\n' + i18n[lang]['cmd_set_option_usage_prompt_html']
        )
        await event.respond(msg, parse_mode='html')
        return
    key = args[1]
    value = args[2]

    try:
        await db.EffectiveOptions.set(key, value)
    except KeyError:
        await event.respond(f'ERROR: {i18n[lang]["option_key_invalid"]}')
        return
    except ValueError:
        await event.respond(f'ERROR: {i18n[lang]["option_value_invalid"]}')
        return

    logger.info(f"Set option {key} to {value}")

    if key == 'default_interval':
        all_feeds = await db.Feed.filter(state=1)
        for feed in all_feeds:
            env.loop.create_task(inner.utils.update_interval(feed))
        logger.info(f"Flushed the interval of all feeds")

    await event.respond(f'<b>{i18n[lang]["option_updated"]}</b>\n'
                        f'<code>{key}</code> = <code>{value}</code>',
                        parse_mode='html')


@command_gatekeeper(only_manager=True, timeout=None if env.DEBUG else 300)
async def cmd_test(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
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

    uid = event.chat_id

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
            *(__send(uid, entry, rss_d.feed.title, url) for entry in entries_to_send)
        )

    except Exception as e:
        logger.warning(f"Sending failed:", exc_info=e)
        await event.respond('ERROR: ' + i18n[lang]['internal_error'])
        return


async def __send(uid, entry, feed_title, link):
    post = get_post_from_entry(entry, feed_title, link)
    logger.debug(f"Sending {entry.get('title', 'Untitled')} ({entry.get('link', 'No link')})...")
    await post.test_format(uid)


@command_gatekeeper(only_manager=True)
async def cmd_user_info_or_callback_set_user(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                                             *_,
                                             lang: Optional[str] = None,
                                             **__):
    """
    command = `/user_info user_id` or `/user_info @username` or `/user_info`
    callback data = set_user={user_id},{state}
    """
    is_callback = isinstance(event, events.CallbackQuery.Event)
    if is_callback:
        user_entity_like, state, _, _ = parse_customization_callback_data(event.data)
        state = int(state)
    else:
        state = None
        args = parse_command(event.raw_text, strip_target_chat=False)
        if len(args) < 2 or not (args[1].lstrip('-').isdecimal() or args[1].startswith('@')):
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
    state = user.state if user_id != env.MANAGER else None
    sub_count = await inner.utils.count_sub(user_id) if not user_created else 0

    msg_text = (
            f"<b>{i18n[lang]['user_info']}</b>\n\n"
            + (f"{name}\n" if name else '')
            + (f"{user_type} " if user_type else '') + f"<code>{user_id}</code>\n"
            + (f"@{username}\n" if username else '')
            + f"\n{i18n[lang]['sub_count']}: {sub_count}"
            + (f"\n{i18n[lang]['participant_count']}: {participant_count}" if participant_count else '')
            + (f"\n\n{i18n[lang]['user_state']}: {i18n[lang][f'user_state_{state}']} "
               f"({i18n[lang][f'user_state_description_{state}']})" if state is not None else '')
    )
    buttons = (
        (Button.inline(f"{i18n[lang]['set_user_state_as']} \"{i18n[lang]['user_state_-1']}\"",
                       data=f"set_user={user_id},-1") if user.state != -1 else inner.utils.emptyButton,),
        (Button.inline(f"{i18n[lang]['set_user_state_as']} \"{i18n[lang]['user_state_0']}\"",
                       data=f"set_user={user_id},0") if user.state != 0 else inner.utils.emptyButton,),
        (Button.inline(f"{i18n[lang]['set_user_state_as']} \"{i18n[lang]['user_state_1']}\"",
                       data=f"set_user={user_id},1") if user.state != 1 else inner.utils.emptyButton,),
    ) if user_id != env.MANAGER else None
    await event.respond(msg_text, parse_mode='html', buttons=buttons) if not is_callback \
        else await event.edit(msg_text, parse_mode='html', buttons=buttons)
