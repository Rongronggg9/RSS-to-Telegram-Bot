import asyncio
from typing import Union, Optional
from telethon import events
from telethon.tl.patched import Message

from src import web, db
from src.i18n import i18n
from src.parsing.post import get_post_from_entry
from .utils import permission_required, parse_command, logger
from . import inner


@permission_required(only_manager=True)
async def cmd_set_option(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    args = parse_command(event.raw_text)
    if len(args) < 3:  # return options info
        options = db.EffectiveOptions.options
        msg = (
                f'<b>{i18n[lang]["current_options"]}</b>\n\n'
                + '\n'.join(f'<code>{key}</code> = <code>{value}</code> '
                            f'({i18n[lang]["option_value_type"]}: <code>{type(value).__name__}</code>)'
                            for key, value in options.items())
                + '\n\n' + i18n[lang]['set_option_cmd_usage_prompt_html']
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
        await asyncio.gather(
            *(inner.utils.update_interval(feed) for feed in all_feeds)
        )
        logger.info(f"Flushed the interval of all feeds")

    await event.respond(f'<b>{i18n[lang]["option_updated"]}</b>\n'
                        f'<code>{key}</code> = <code>{value}</code>',
                        parse_mode='html')


@permission_required(only_manager=True)
async def cmd_test(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    args = parse_command(event.raw_text)
    if len(args) < 2:
        await event.respond(i18n[lang]['test_cmd_usage_prompt_html'], parse_mode='html')
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
        d = await web.feed_get(url, web_semaphore=False, lang=lang)
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
