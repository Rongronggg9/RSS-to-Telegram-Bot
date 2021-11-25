import asyncio
from time import sleep
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.errors import ApiIdPublishedFloodError
from telethon.tl import types
from telethon.tl.functions.bots import SetBotCommandsRequest
from random import sample
from pathlib import Path

from src import env, log, db, command
from src.parsing import tgraph

# log
logger = log.getLogger('RSStT')

# initializing bot
Path("config").mkdir(parents=True, exist_ok=True)
bot: Optional[TelegramClient] = None
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
    bot = TelegramClient('config/bot', env.API_ID, env.API_HASH, proxy=env.TELEGRAM_PROXY_DICT, request_retries=4) \
        .start(bot_token=env.TOKEN)

if bot is None:
    logger.critical('LOGIN FAILED!')
    exit(1)

env.bot = bot
env.bot_peer = asyncio.get_event_loop().run_until_complete(bot.get_me())
env.bot_id = env.bot_peer.id


def main():
    logger.info(f"RSS-to-Telegram-Bot ({', '.join(env.VERSION.split())}) started!\n"
                f"MANAGER: {env.MANAGER}\n"
                f"T_PROXY (for Telegram): {env.TELEGRAM_PROXY if env.TELEGRAM_PROXY else 'not set'}\n"
                f"R_PROXY (for RSS): {env.REQUESTS_PROXIES['all'] if env.REQUESTS_PROXIES else 'not set'}\n"
                f"DATABASE: {env.DATABASE_URL.split('://', 1)[0]}\n"
                f"TELEGRAPH: {f'Enable ({tgraph.apis.count} accounts)' if tgraph.apis else 'Disable'}\n"
                f"MULTIUSER: {f'Enable' if env.MULTIUSER else 'Disable'}")

    commands = [types.BotCommand(command="sub", description="添加订阅"),
                types.BotCommand(command="unsub", description="移除订阅"),
                types.BotCommand(command="unsub_all", description="移除所有订阅"),
                types.BotCommand(command="list", description="列出所有订阅"),
                types.BotCommand(command="import", description="导入订阅"),
                types.BotCommand(command="export", description="导出订阅"),
                types.BotCommand(command="version", description="查看版本"),
                types.BotCommand(command="help", description="查看帮助")]

    commands_manager = [types.BotCommand(command="test", description="测试"), ]
    try:
        bot.loop.run_until_complete(asyncio.gather(
            bot(SetBotCommandsRequest(scope=types.BotCommandScopeDefault(), lang_code='', commands=commands)),
            bot(SetBotCommandsRequest(scope=types.BotCommandScopePeer(types.InputPeerUser(env.MANAGER, 0)),
                                      lang_code='', commands=commands + commands_manager))
        ))
    except Exception as e:
        logger.warning('Set command error: ', exc_info=e)

    # command handler
    bot.add_event_handler(command.sub.cmd_sub, events.NewMessage(pattern='/add|/sub'))
    bot.add_event_handler(command.sub.cmd_sub, command.utils.PrivateMessage(pattern=r'https?://'))
    bot.add_event_handler(command.sub.cmd_sub, command.utils.ReplyMessage(pattern=r'https?://'))
    bot.add_event_handler(command.sub.cmd_unsub, events.NewMessage(pattern='(/remove|/unsub)([^_]|$)'))
    bot.add_event_handler(command.sub.cmd_unsub_all, events.NewMessage(pattern='/remove_all|/unsub_all'))
    bot.add_event_handler(command.sub.cmd_list, events.NewMessage(pattern='/list'))
    bot.add_event_handler(command.opml.cmd_import, events.NewMessage(pattern='/import'))
    bot.add_event_handler(command.opml.cmd_export, events.NewMessage(pattern='/export'))
    bot.add_event_handler(command.opml.opml_import, command.utils.NewFileMessage(filename_pattern=r'^.*\.opml$'))
    bot.add_event_handler(command.management.cmd_help, events.NewMessage(pattern='/help|/start'))
    bot.add_event_handler(command.management.cmd_test, events.NewMessage(pattern='/test'))
    bot.add_event_handler(command.management.cmd_version, events.NewMessage(pattern='/version'))

    # callback query handler
    bot.add_event_handler(command.sub.callback_unsub, events.CallbackQuery(pattern=r'^unsub_\d+$'))
    bot.add_event_handler(command.sub.callback_get_unsub_page, events.CallbackQuery(pattern=r'^get_unsub_page_\d+$'))

    asyncio.get_event_loop().run_until_complete(db.init())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(command.monitor.run_monitor_task, trigger='cron', minute='*/1', max_instances=5, timezone='UTC')
    scheduler.start()

    bot.run_until_disconnected()

    asyncio.get_event_loop().run_until_complete(db.close())


if __name__ == '__main__':
    main()
