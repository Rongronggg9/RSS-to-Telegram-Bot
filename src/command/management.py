import asyncio
from typing import Union
from telethon import events
from telethon.tl.custom import Message

from src import env, web
from .utils import permission_required, parse_command, logger
from ..parsing.post import get_post_from_entry


@permission_required(only_manager=False)
async def cmd_help(event: Union[events.NewMessage.Event, Message]):
    await event.respond(
        "<a href='https://github.com/Rongronggg9/RSS-to-Telegram-Bot'>"
        "RSS to Telegram bot，专为短动态类消息设计的 RSS Bot。</a>\n\n"
        "命令:\n"
        "<u><b>/sub</b></u> <u><b>RSS链接</b></u> : 添加订阅\n"
        "<u><b>/unsub</b></u> <u><b>RSS链接</b></u> : 移除订阅\n"
        "<u><b>/list</b></u> : 列出所有订阅\n"
        # "<u><b>/test</b></u> <u><b>RSS</b></u> <u><b>编号起点(可选)</b></u> <u><b>编号终点(可选)</b></u> : "
        # "从 RSS 源处获取一条 post (编号为 0-based, 不填或超出范围默认为 0，不填编号终点默认只获取一条 post)，"
        # "或者直接用 <code>all</code> 获取全部\n"
        "<u><b>/import</b></u> : 导入订阅\n"
        "<u><b>/export</b></u> : 导出订阅\n"
        "<u><b>/version</b></u> : 查看版本\n"
        "<u><b>/help</b></u> : 发送这条消息\n\n",
        # f"您的 chatid 是: {event.chat_id}",
        parse_mode='html'
    )


@permission_required(only_manager=True)
async def cmd_test(event: Union[events.NewMessage.Event, Message]):
    args = parse_command(event.text)
    if len(args) < 2:
        await event.respond('ERROR: 格式需要为: /test RSS 条目编号起点(可选) 条目编号终点(可选)')
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
        await event.respond('ERROR: 内部错误')
        return


async def __send(uid, entry, feed_title, link):
    post = get_post_from_entry(entry, feed_title, link)
    await post.generate_message()
    logger.debug(f"Sending {entry['title']} ({entry['link']})...")
    await post.send_message(uid)


@permission_required(only_manager=False)
async def cmd_version(event: Union[events.NewMessage.Event, Message]):
    await event.respond(env.VERSION)
