from typing import Union, Optional
from telethon import events, Button
from telethon.tl.custom import Message

from . import inner
from .utils import permission_required, parse_command, escape_html


@permission_required(only_manager=False)
async def cmd_sub(event: Union[events.NewMessage.Event, Message], args: Optional[str] = None):
    args = parse_command(event.text if args is None else args)

    sub_result = await inner.sub.subs(event.chat_id, *args)

    if sub_result is None:
        await event.respond("请回复订阅链接", buttons=Button.force_reply())
        return

    await event.respond(sub_result["msg"], parse_mode='html')


@permission_required(only_manager=False)
async def cmd_unsub(event: Union[events.NewMessage.Event, Message], args: Optional[str] = None):
    args = parse_command(event.text if args is None else args)
    user_id = event.chat_id

    unsub_result = await inner.sub.unsubs(user_id, args)

    if unsub_result is None:
        buttons = await inner.utils.get_sub_choosing_buttons(user_id, page=1, callback='unsub',
                                                             get_page_callback='get_unsub_page')
        await event.respond('请选择你要退订的订阅' if buttons else '无订阅', buttons=buttons)
        return

    await event.respond(unsub_result['msg'], parse_mode='html')


@permission_required(only_manager=False)
async def cmd_unsub_all(event: Union[events.NewMessage.Event, Message]):
    unsub_all_result = await inner.sub.unsub_all(event.chat_id)
    await event.respond(unsub_all_result['msg'] if unsub_all_result else '无订阅', parse_mode='html')


@permission_required(only_manager=False)
async def cmd_list(event: Union[events.NewMessage.Event, Message]):
    subs = await inner.utils.list_sub(event.chat_id)
    if not subs:
        await event.respond('无订阅')
        return

    list_result = (
            '<b>订阅列表</b>\n'
            + '\n'.join(f'<a href="{sub.feed.link}">{escape_html(sub.feed.title)}</a>' for sub in subs)
    )

    await event.respond(list_result, parse_mode='html')


@permission_required(only_manager=False)
async def callback_unsub(event: events.CallbackQuery.Event):  # callback data = unsub_{sub_id}|{page}
    data = event.data.decode().strip()
    sub_id = int(data.split('|')[0].split('_')[-1])
    page = int(data.split('|')[1]) if len(data.split('|')) > 1 else 1
    unsub_d = await inner.sub.unsub(event.chat_id, sub_id=sub_id)

    msg = (
            f'<b>退订{"成功" if unsub_d["sub"] else "失败"}</b>\n'
            + (
                f'<a href="{unsub_d["sub"].feed.link}">{escape_html(unsub_d["sub"].feed.title)}</a>' if unsub_d['sub']
                else f'{escape_html(unsub_d["url"])} ({unsub_d["msg"]})</a>'
            )
    )

    if unsub_d['sub']:  # successfully unsubed
        await callback_get_unsub_page.__wrapped__(event, page)

    # await event.edit(msg, parse_mode='html')
    await event.respond(msg, parse_mode='html')  # make unsubscribing multiple subscriptions more efficiency


@permission_required(only_manager=False)
async def callback_get_unsub_page(event: events.CallbackQuery.Event,
                                  page: Optional[int] = None):  # callback data = get_unsub_page_{page_number}
    page = page or int(event.data.decode().strip().split('_')[-1])
    buttons = await inner.utils.get_sub_choosing_buttons(event.chat_id, page, callback='unsub',
                                                         get_page_callback='get_unsub_page')
    await event.edit(None if buttons else '无订阅', buttons=buttons)
