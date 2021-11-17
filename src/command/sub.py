from typing import Union
from telethon import events, Button
from telethon.tl.custom import Message

from . import inner
from .utils import permission_required, commandParser, escape_html


@permission_required(only_manager=False)
async def cmd_sub(event: Union[events.NewMessage.Event, Message]):
    args = commandParser(event.text)

    sub_result = await inner.subs(event.chat_id, *args)

    if sub_result is None:
        await event.respond("请回复订阅链接", buttons=Button.force_reply())
        return

    await event.respond(sub_result["msg"], parse_mode='html')


@permission_required(only_manager=False)
async def cmd_unsub(event: Union[events.NewMessage.Event, Message]):
    args = commandParser(event.text)
    if len(args) < 2:
        await event.respond("ERROR: 请指定订阅链接")
        return
    feed_url = args[1]
    unsub_d = await inner.unsub(event.chat_id, feed_url)
    sub = unsub_d['sub']
    if sub:
        await event.respond(f'<b>已移除</b>\n'
                            f'<a href="{sub.feed.link}">{escape_html(sub.feed.title)}</a>',
                            parse_mode='html')
        return
    await event.respond(unsub_d['msg'])


@permission_required(only_manager=False)
async def cmd_list(event: Union[events.NewMessage.Event, Message]):
    subs = await inner.list_sub(event.chat_id)
    if not subs:
        await event.respond('无订阅')
        return

    list_result = (
            '<b>订阅列表</b>\n'
            + '\n'.join(f'<a href="{sub.feed.link}">{escape_html(sub.feed.title)}</a>' for sub in subs)
    )

    await event.respond(list_result, parse_mode='html')
