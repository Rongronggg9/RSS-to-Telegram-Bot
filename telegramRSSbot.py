import asyncio
from functools import partial
from time import sleep
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.errors import ApiIdPublishedFloodError
from telethon.tl import types
from random import sample
from pathlib import Path

from src import env, log, db, command
from src.i18n import i18n, ALL_LANGUAGES
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

    bot.loop.run_until_complete(
        db.init()
    )

    manager_lang = bot.loop.run_until_complete(db.User.get_or_none(id=env.MANAGER).values_list('lang', flat=True))

    try:  # set bot command
        bot.loop.run_until_complete(asyncio.gather(
            command.utils.set_bot_commands(scope=types.BotCommandScopeDefault(), lang_code='',
                                           commands=command.utils.get_commands_list()),
            *(
                command.utils.set_bot_commands(scope=types.BotCommandScopeDefault(),
                                               lang_code=i18n[lang]['iso_639_1_code'],
                                               commands=command.utils.get_commands_list(lang=lang))
                for lang in ALL_LANGUAGES if i18n[lang]['iso_639_1_code']
            ),
            command.utils.set_bot_commands(scope=types.BotCommandScopePeer(types.InputPeerUser(env.MANAGER, 0)),
                                           lang_code='',
                                           commands=command.utils.get_commands_list(lang=manager_lang, manager=True)),
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
    bot.add_event_handler(command.management.cmd_start, events.NewMessage(pattern='/start'))
    bot.add_event_handler(command.management.cmd_help, events.NewMessage(pattern='/help'))
    bot.add_event_handler(partial(command.management.cmd_activate_or_deactivate_subs, activate=True),
                          events.NewMessage(pattern='/activate_subs'))
    bot.add_event_handler(partial(command.management.cmd_activate_or_deactivate_subs, activate=False),
                          events.NewMessage(pattern='/deactivate_subs'))
    bot.add_event_handler(command.management.cmd_test, events.NewMessage(pattern='/test'))
    bot.add_event_handler(command.management.cmd_version, events.NewMessage(pattern='/version'))
    bot.add_event_handler(command.management.cmd_lang, events.NewMessage(pattern='/lang'))
    # callback query handler
    bot.add_event_handler(command.sub.callback_unsub, events.CallbackQuery(pattern=r'^unsub_\d+(\|\d+)$'))
    bot.add_event_handler(command.sub.callback_get_unsub_page, events.CallbackQuery(pattern=r'^get_unsub_page_\d+$'))
    bot.add_event_handler(command.management.callback_set_lang, events.CallbackQuery(pattern=r'^set_lang_[\w_\-]+$'))
    bot.add_event_handler(partial(command.management.callback_activate_or_deactivate_all_subs, activate=True),
                          events.CallbackQuery(pattern=r'^activate_all_subs$'))
    bot.add_event_handler(partial(command.management.callback_activate_or_deactivate_all_subs, activate=False),
                          events.CallbackQuery(pattern=r'^deactivate_all_subs$'))
    bot.add_event_handler(partial(command.management.callback_activate_or_deactivate_sub, activate=True),
                          events.CallbackQuery(pattern=r'^activate_sub_\d+(\|\d+)$'))
    bot.add_event_handler(partial(command.management.callback_activate_or_deactivate_sub, activate=False),
                          events.CallbackQuery(pattern=r'^deactivate_sub_\d+(\|\d+)$'))
    bot.add_event_handler(partial(command.management.callback_get_activate_or_deactivate_page, activate=True),
                          events.CallbackQuery(pattern=r'^get_activate_page_\d+$'))
    bot.add_event_handler(partial(command.management.callback_get_activate_or_deactivate_page, activate=False),
                          events.CallbackQuery(pattern=r'^get_deactivate_page_\d+$'))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(command.monitor.run_monitor_task, trigger='cron', minute='*/1', max_instances=5, timezone='UTC')
    scheduler.start()

    bot.run_until_disconnected()

    bot.loop.run_until_complete(
        db.close()
    )


if __name__ == '__main__':
    main()
