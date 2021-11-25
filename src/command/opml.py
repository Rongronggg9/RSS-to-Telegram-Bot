import listparser
from datetime import datetime
from typing import Union
from telethon import events, Button
from telethon.tl import types
from telethon.tl.custom import Message

from src import env
from . import inner
from .utils import permission_required, logger


@permission_required(only_manager=False)
async def cmd_import(event: Union[events.NewMessage.Event, Message]):
    await event.respond('请发送需要导入的 OPML 文档',
                        buttons=Button.force_reply())
    # single_use=False, selective=Ture, placeholder='请发送需要导入的 OPML 文档'


@permission_required(only_manager=False)
async def cmd_export(event: Union[events.NewMessage.Event, Message]):
    opml_file = await inner.export_opml(event.chat_id)
    if opml_file is None:
        await event.respond('无订阅')
        return
    await event.respond(file=opml_file,
                        attributes=(types.DocumentAttributeFilename(
                            f"RSStT_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.opml"),))


@permission_required(only_manager=False)
async def opml_import(event: Union[events.NewMessage.Event, Message]):
    reply_message: Message = await event.get_reply_message()
    if not (event.is_private or event.is_channel and not event.is_group) and reply_message.sender_id != env.bot_id:
        return  # must reply to the bot in a group to import opml
    try:
        opml_file = await event.download_media(file=bytes)
    except Exception as e:
        await event.reply('ERROR: 获取文件失败')
        logger.warning(f'Failed to get opml file from {event.chat_id}: ', exc_info=e)
        return
    reply: Message = await event.reply('正在处理中...\n'
                                       '如订阅较多或订阅所在的服务器太慢，将会处理较长时间，请耐心等待')
    logger.info(f'Got an opml file from {event.chat_id}')

    opml_d = listparser.parse(opml_file.decode())
    if not opml_d.feeds:
        await reply.edit('ERROR: 解析失败或文档不含订阅')
        return

    import_result = await inner.subs(event.chat_id, *(feed.url for feed in opml_d.feeds))
    logger.info(f'Imported feed(s) for {event.chat_id}')
    await reply.edit(import_result["msg"], parse_mode='html')
