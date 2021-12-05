import asyncio
import re
from time import sleep
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.errors import ApiIdPublishedFloodError
from telethon.tl.custom import Message, Button
from telethon.tl import types
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.bots import SetBotCommandsRequest
from re import compile as re_compile
from typing import Optional, Union
from datetime import datetime
from functools import wraps, partial
from random import sample
from pathlib import Path

from src import env, log
from src.parsing import tgraph
from src.feed import Feed, Feeds
from src.parsing.post import Post

# log
logger = log.getLogger('RSStT')

# global var placeholder
feeds: Optional[Feeds] = None
conflictCount = 0

# permission verification
ANONYMOUS_ADMIN = 1087968824

# parser
commandParser = re_compile(r'\s')

# initializing bot
Path("config").mkdir(parents=True, exist_ok=True)
bot = None
if not env.API_ID or not env.API_HASH:
    _use_sample_api = True
    logger.info('API_ID and/or API_HASH not set, use sample APIs instead. API_ID_PUBLISHED_FLOOD_ERROR may occur.')
    API_IDs = sample(tuple(env.SAMPLE_APIS.keys()), len(env.SAMPLE_APIS))
    sleep_for = 0
    while API_IDs:
        sleep_for += 10
        API_ID = API_IDs.pop()
        API_HASH = env.SAMPLE_APIS[API_ID]
        try:
            bot = TelegramClient('config/bot', API_ID, API_HASH, proxy=env.TELEGRAM_PROXY_DICT, request_retries=3) \
                .start(bot_token=env.TOKEN)
            break
        except ApiIdPublishedFloodError:
            logger.warning(f'API_ID_PUBLISHED_FLOOD_ERROR occurred. Sleep for {sleep_for}s and retry.')
            sleep(sleep_for)

else:
    _use_sample_api = False
    bot = TelegramClient('config/bot', env.API_ID, env.API_HASH, proxy=env.TELEGRAM_PROXY_DICT, request_retries=3) \
        .start(bot_token=env.TOKEN)

if bot is None:
    logger.critical('LOGIN FAILED!')
    exit(1)

env.bot = bot
bot_peer: types.InputPeerUser = asyncio.get_event_loop().run_until_complete(bot.get_me(input_peer=True))
env.bot_id = bot_peer.user_id


def permission_required(func=None, *, only_manager=False, only_in_private_chat=False):
    if func is None:
        return partial(permission_required, only_manager=only_manager,
                       only_in_private_chat=only_in_private_chat)

    @wraps(func)
    async def wrapper(event: Union[events.NewMessage.Event, Message], *args, **kwargs):
        command = event.text if event.text else '(no command, file message)'
        sender_id = event.sender_id
        sender: Optional[types.User] = await event.get_sender()
        sender_fullname = sender.first_name + (f' {sender.last_name}' if sender.last_name else '')

        if only_manager and sender_id != env.MANAGER:
            await event.respond('此命令只可由机器人的管理员使用。\n'
                                'This command can be only used by the bot manager.')
            logger.info(f'Refused {sender_fullname} ({sender_id}) to use {command}.')
            return

        if event.is_private:
            logger.info(f'Allowed {sender_fullname} ({sender_id}) to use {command}.')
            return await func(event, *args, **kwargs)

        if event.is_group:
            chat: types.Chat = await event.get_chat()
            input_chat: types.InputChannel = await event.get_input_chat()  # supergroup is a special form of channel
            if only_in_private_chat:
                await event.respond('此命令不允许在群聊中使用。\n'
                                    'This command can not be used in a group.')
                logger.info(f'Refused {sender_fullname} ({sender_id}) to use {command} in '
                            f'{chat.title} ({chat.id}).')
                return

            input_sender = await event.get_input_sender()

            if sender_id != ANONYMOUS_ADMIN:
                participant: types.channels.ChannelParticipant = await bot(
                    GetParticipantRequest(input_chat, input_sender))
                is_admin = (isinstance(participant.participant, types.ChannelParticipantAdmin)
                            or isinstance(participant.participant, types.ChannelParticipantCreator))
                participant_type = type(participant.participant).__name__
            else:
                is_admin = True
                participant_type = 'AnonymousAdmin'

            if not is_admin:
                await event.respond('此命令只可由群管理员使用。\n'
                                    'This command can be only used by an administrator.')
                logger.info(
                    f'Refused {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                    f'in {chat.title} ({chat.id}).')
                return
            logger.info(
                f'Allowed {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                f'in {chat.title} ({chat.id}).')
            return await func(event, *args, **kwargs)
        return

    return wrapper


@bot.on(events.NewMessage(pattern='/list'))
@permission_required(only_manager=True)
async def cmd_list(event: Union[events.NewMessage.Event, Message]):
    list_result = '<br>'.join(f'<a href="{feed.link}">{feed.name}</a>' for feed in feeds)
    if not list_result:
        await event.respond('数据库为空')
        return
    result_post = Post('<b><u>订阅列表</u></b><br><br>' + list_result, plain=True, service_msg=True)
    await result_post.send_message(event.chat_id, event.id if not event.is_private else None)


@bot.on(events.NewMessage(pattern='/add'))
@permission_required(only_manager=True)
async def cmd_add(event: Union[events.NewMessage.Event, Message]):
    args = commandParser.split(event.text)
    if len(args) < 3:
        await event.respond('ERROR: 格式需要为: /add 标题 RSS')
        return
    title = args[1]
    url = args[2]
    if await feeds.add_feed(name=title, link=url, uid=event.chat_id):
        await event.respond('已添加 \n标题: %s\nRSS 源: %s' % (title, url))


@bot.on(events.NewMessage(pattern='/remove'))
@permission_required(only_manager=True)
async def cmd_remove(event: Union[events.NewMessage.Event, Message]):
    args = commandParser.split(event.text)
    if len(args) < 2:
        await event.respond("ERROR: 请指定订阅名")
        return
    name = args[1]
    if feeds.del_feed(name):
        await event.respond("已移除: " + name)
        return
    await event.respond("ERROR: 未能找到这个订阅名: " + name)


@bot.on(events.NewMessage(pattern='/help|/start'))
@permission_required(only_manager=True)
async def cmd_help(event: Union[events.NewMessage.Event, Message]):
    await event.respond(
        "<a href='https://github.com/Rongronggg9/RSS-to-Telegram-Bot'>"
        "RSS to Telegram bot，专为短动态类消息设计的 RSS Bot。</a>\n\n"
        f"成功添加一个 RSS 源后, 机器人就会开始检查订阅，每 {env.DELAY} 秒一次。 (可修改)\n\n"
        "标题为只是为管理 RSS 源而设的，可随意选取，但不可有空格。\n\n"
        "命令:\n"
        "<u><b>/add</b></u> <u><b>标题</b></u> <u><b>RSS</b></u> : 添加订阅\n"
        "<u><b>/remove</b></u> <u><b>标题</b></u> : 移除订阅\n"
        "<u><b>/list</b></u> : 列出数据库中的所有订阅\n"
        "<u><b>/test</b></u> <u><b>RSS</b></u> <u><b>编号起点(可选)</b></u> <u><b>编号终点(可选)</b></u> : "
        "从 RSS 源处获取一条 post (编号为 0-based, 不填或超出范围默认为 0，不填编号终点默认只获取一条 post)，"
        "或者直接用 <code>all</code> 获取全部\n"
        "<u><b>/import</b></u> : 导入订阅\n"
        "<u><b>/export</b></u> : 导出订阅\n"
        "<u><b>/version</b></u> : 查看版本\n"
        "<u><b>/help</b></u> : 发送这条消息\n\n"
        f"您的 chatid 是: {event.chat_id}",
        parse_mode='html'
    )


@bot.on(events.NewMessage(pattern='/test'))
@permission_required(only_manager=True)
async def cmd_test(event: Union[events.NewMessage.Event, Message]):
    args = commandParser.split(event.text)
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

    try:
        await Feed(link=url).send(event.chat_id, start, end, web_semaphore=False)
    except Exception as e:
        logger.warning(f"Sending failed:", exc_info=e)
        await event.respond('ERROR: 内部错误')
        return


@bot.on(events.NewMessage(pattern='/import'))
@permission_required(only_manager=True)
async def cmd_import(event: Union[events.NewMessage.Event, Message]):
    await event.respond('请发送需要导入的 OPML 文档',
                        buttons=Button.force_reply())
    # single_use=False, selective=Ture, placeholder='请发送需要导入的 OPML 文档'


@bot.on(events.NewMessage(pattern='/export'))
@permission_required(only_manager=True)
async def cmd_export(event: Union[events.NewMessage.Event, Message]):
    opml_file = feeds.export_opml()
    if opml_file is None:
        await event.respond('数据库为空')
        return
    await event.respond(file=opml_file,
                        attributes=(types.DocumentAttributeFilename(
                            f"RSStT_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.opml"),))


class NewFileMessage(events.NewMessage):
    def __init__(self, chats=None, *, blacklist_chats=False, func=None, incoming=None, outgoing=None, from_users=None,
                 forwards=None, pattern=None, filename_pattern: str = None):
        self.filename_pattern = re.compile(filename_pattern).match
        super().__init__(chats, blacklist_chats=blacklist_chats, func=func, incoming=incoming, outgoing=outgoing,
                         from_users=from_users, forwards=forwards, pattern=pattern)

    def filter(self, event):
        document: types.Document = event.message.document
        if not document:
            return
        if self.filename_pattern:
            filename = None
            for attr in document.attributes:
                if isinstance(attr, types.DocumentAttributeFilename):
                    filename = attr.file_name
                    break
            if not self.filename_pattern(filename or ''):
                return
        return super().filter(event)


@bot.on(NewFileMessage(filename_pattern=r'^.*\.opml$'))
@permission_required(only_manager=True)
async def opml_import(event: Union[events.NewMessage.Event, Message]):
    reply_message: Message = await event.get_reply_message()
    if not event.is_private and reply_message.sender_id != env.bot_id:
        return
    try:
        opml_file = await event.download_media(file=bytes)
    except Exception as e:
        await event.reply('ERROR: 获取文件失败')
        logger.warning(f'Failed to get opml file: ', exc_info=e)
        return
    await event.reply('正在处理中...\n'
                      '如订阅较多或订阅所在的服务器太慢，将会处理较长时间，请耐心等待')
    logger.info(f'Got an opml file.')
    res = await feeds.import_opml(opml_file)
    if res is None:
        await event.reply('ERROR: 解析失败或文档不含订阅')
        return

    valid = res['valid']
    invalid = res['invalid']
    import_result = '<b><u>导入结果</u></b><br><br>' \
                    + ('导入成功：<br>' if valid else '') \
                    + '<br>'.join(f'<a href="{feed["link"]}">{feed["name"]}</a>' for feed in valid) \
                    + ('<br><br>' if valid and invalid else '') \
                    + ('导入失败：<br>' if invalid else '') \
                    + '<br>'.join(f'<a href="{feed["link"]}">{feed["name"]}</a>' for feed in invalid)
    result_post = Post(import_result, plain=True, service_msg=True)
    await result_post.send_message(event.chat_id, event.message.id)


@bot.on(events.NewMessage(pattern='/version'))
@permission_required(only_manager=True)
async def cmd_version(event: Union[events.NewMessage.Event, Message]):
    await event.respond(env.VERSION)


async def rss_monitor(fetch_all: bool = False):
    await feeds.monitor(fetch_all)


def main():
    global feeds
    logger.info(f"RSS-to-Telegram-Bot ({', '.join(env.VERSION.split())}) started!\n"
                f"CHATID: {env.CHATID}\n"
                f"MANAGER: {env.MANAGER}\n"
                f"DELAY: {env.DELAY}s\n"
                f"T_PROXY (for Telegram): {env.TELEGRAM_PROXY if env.TELEGRAM_PROXY else 'not set'}\n"
                f"R_PROXY (for RSS): {env.REQUESTS_PROXIES['all'] if env.REQUESTS_PROXIES else 'not set'}\n"
                f"DATABASE: {'Redis' if env.REDIS_HOST else 'Sqlite'}\n"
                f"TELEGRAPH: {f'Enable ({tgraph.apis.count} accounts)' if tgraph.apis else 'Disable'}")

    commands = [types.BotCommand(command="add", description="添加订阅"),
                types.BotCommand(command="remove", description="移除订阅"),
                types.BotCommand(command="list", description="列出所有订阅"),
                types.BotCommand(command="test", description="测试"),
                types.BotCommand(command="import", description="导入订阅"),
                types.BotCommand(command="export", description="导出订阅"),
                types.BotCommand(command="version", description="查看版本"),
                types.BotCommand(command="help", description="查看帮助")]
    try:
        asyncio.get_event_loop().run_until_complete(
            bot(SetBotCommandsRequest(scope=types.BotCommandScopeDefault(), lang_code='', commands=commands)))
    except Exception as e:
        logger.warning('Set command error: ', exc_info=e)

    feeds = Feeds()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(rss_monitor, trigger='cron', minute='*/1', max_instances=5, timezone='utc')
    scheduler.start()

    bot.run_until_disconnected()


if __name__ == '__main__':
    main()
