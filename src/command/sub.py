from typing import Union, Optional
from telethon import events, Button
from telethon.tl.custom import Message

from . import inner
from .utils import permission_required, parse_command, escape_html


@permission_required(only_manager=False)
async def cmd_sub(event: Union[events.NewMessage.Event, Message], args: Optional[str] = None):
    args = parse_command(event.text if args is None else args)

    sub_result = await inner.subs(event.chat_id, *args)

    if sub_result is None:
        await event.respond("请回复订阅链接", buttons=Button.force_reply())
        return

    await event.respond(sub_result["msg"], parse_mode='html')


@permission_required(only_manager=False)
async def cmd_unsub(event: Union[events.NewMessage.Event, Message], args: Optional[str] = None):
    args = parse_command(event.text if args is None else args)

    unsub_result = await inner.unsubs(event.chat_id, *args)

    if unsub_result is None:
        await event.respond("ERROR: 请指定订阅链接")
        return

    await event.respond(unsub_result["msg"], parse_mode='html')


@permission_required(only_manager=False)
async def cmd_unsub_all(event: Union[events.NewMessage.Event, Message]):
    unsub_all_result = await inner.unsub_all(event.chat_id)
    await event.respond(unsub_all_result["msg"], parse_mode='html')


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
