import asyncio
from typing import Union, Optional
from telethon import events
from telethon.tl.patched import Message

from src import web, db, env
from src.i18n import i18n
from src.parsing.post import get_post_from_entry
from .utils import command_gatekeeper, parse_command, logger
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
        all_feeds = await db.Feed.all()
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
        end = int(args[3]) + 1
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
