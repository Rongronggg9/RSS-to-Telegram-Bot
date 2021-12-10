import listparser
from datetime import datetime
from typing import Union, Optional
from telethon import events, Button
from telethon.tl import types
from telethon.tl.patched import Message

from src import env
from src.i18n import i18n
from . import inner
from .utils import permission_required, logger


@permission_required(only_manager=False)
async def cmd_import(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    await event.respond(i18n[lang]['send_opml_prompt'],
                        buttons=Button.force_reply(single_use=True,
                                                   selective=True,
                                                   placeholder=i18n[lang]['send_opml_reply_placeholder']),
                        reply_to=event.id if event.is_group else None)


@permission_required(only_manager=False)
async def cmd_export(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    opml_file = await inner.sub.export_opml(event.chat_id)
    if opml_file is None:
        await event.respond(i18n[lang]['no_subscription'])
        return
    await event.respond(file=opml_file,
                        attributes=(types.DocumentAttributeFilename(
                            f"RSStT_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.opml"),))


@permission_required(only_manager=False)
async def opml_import(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    reply_message: Message = await event.get_reply_message()
    if not (event.is_private or event.is_channel and not event.is_group) and reply_message.sender_id != env.bot_id:
        return  # must reply to the bot in a group to import opml
    try:
        opml_file = await event.download_media(file=bytes)
    except Exception as e:
        await event.reply('ERROR: ' + i18n[lang]['fetch_file_failed'])
        logger.warning(f'Failed to get opml file from {event.chat_id}: ', exc_info=e)
        return

    reply: Message = await event.reply(i18n[lang]['processing'] + '\n' + i18n[lang]['opml_import_processing'])
    logger.info(f'Got an opml file from {event.chat_id}')

    opml_d = listparser.parse(opml_file.decode())
    if not opml_d.feeds:
        await reply.edit('ERROR: ' + i18n[lang]['opml_parse_error'])
        return

    import_result = await inner.sub.subs(event.chat_id, tuple(feed.url for feed in opml_d.feeds), lang=lang)
    logger.info(f'Imported feed(s) for {event.chat_id}')
    await reply.edit(import_result["msg"], parse_mode='html')
