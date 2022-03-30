from __future__ import annotations

import asyncio

try:
    import uvloop

    uvloop.install()
except ImportError:  # uvloop do not support Windows
    uvloop = None

from functools import partial
from time import sleep
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telethon import TelegramClient, events
from telethon.errors import ApiIdPublishedFloodError
from telethon.tl import types
from random import sample
from os import path

from . import env, log, db, command
from .i18n import i18n, ALL_LANGUAGES, get_commands_list
from .parsing import tgraph

# log
logger = log.getLogger('RSStT')

# initializing bot
loop = env.loop

bot: Optional[TelegramClient] = None
if not env.API_ID or not env.API_HASH:
    logger.info('API_ID and/or API_HASH not set, use sample APIs instead. API_ID_PUBLISHED_FLOOD_ERROR may occur.')
    API_KEYs = {api_id: env.SAMPLE_APIS[api_id]
                for api_id in sample(tuple(env.SAMPLE_APIS.keys()), len(env.SAMPLE_APIS))}
else:
    API_KEYs = {env.API_ID: env.API_HASH}

sleep_for = 0
while API_KEYs:
    sleep_for += 10
    API_ID, API_HASH = API_KEYs.popitem()
    try:
        bot = TelegramClient(path.join(env.config_folder_path, 'bot'),
                             API_ID, API_HASH, proxy=env.TELEGRAM_PROXY_DICT, request_retries=2,
                             raise_last_call_error=True, loop=loop).start(bot_token=env.TOKEN)
        break
    except ApiIdPublishedFloodError:
        if not API_KEYs:
            logger.warning(f'API_ID_PUBLISHED_FLOOD_ERROR occurred.')
            break
        logger.warning(f'API_ID_PUBLISHED_FLOOD_ERROR occurred. Sleep for {sleep_for}s and retry.')
        sleep(sleep_for)

if bot is None:
    logger.critical('LOGIN FAILED!')
    exit(1)

env.bot = bot
env.bot_peer = loop.run_until_complete(bot.get_me(input_peer=False))
env.bot_input_peer = loop.run_until_complete(bot.get_me(input_peer=True))
env.bot_id = env.bot_peer.id


async def pre():
    logger.info(f"RSS-to-Telegram-Bot ({', '.join(env.VERSION.split())}) started!\n"
                f"MANAGER: {env.MANAGER}\n"
                f"T_PROXY (for Telegram): {env.TELEGRAM_PROXY if env.TELEGRAM_PROXY else 'not set'}\n"
                f"R_PROXY (for RSS): {env.REQUESTS_PROXIES['all'] if env.REQUESTS_PROXIES else 'not set'}\n"
                f"DATABASE: {env.DATABASE_URL.split('://', 1)[0]}\n"
                f"TELEGRAPH: {f'Enable ({tgraph.apis.count} accounts)' if tgraph.apis else 'Disable'}\n"
                f"UVLOOP: {f'Enable' if uvloop is not None else 'Disable'}\n"
                f"MULTIUSER: {f'Enable' if env.MULTIUSER else 'Disable'}")

    await db.init()

    # enable redirect server for Railway, Heroku, etc
    if env.PORT:
        from . import redirect_server
        await redirect_server.run(port=env.PORT)

    # noinspection PyTypeChecker
    manager_lang: Optional[str] = await db.User.get_or_none(id=env.MANAGER).values_list('lang', flat=True)

    try:  # set bot command
        await asyncio.gather(
            command.utils.set_bot_commands(scope=types.BotCommandScopeDefault(), lang_code='',
                                           commands=get_commands_list()),
            *(
                command.utils.set_bot_commands(scope=types.BotCommandScopeDefault(),
                                               lang_code=i18n[lang]['iso_639_code'],
                                               commands=get_commands_list(lang=lang))
                for lang in ALL_LANGUAGES if len(i18n[lang]['iso_639_code']) == 2
            ),
            command.utils.set_bot_commands(scope=types.BotCommandScopePeer(types.InputPeerUser(env.MANAGER, 0)),
                                           lang_code='',
                                           commands=get_commands_list(lang=manager_lang, manager=True)),
        )
    except Exception as e:
        logger.warning('Set command error: ', exc_info=e)

    bare_target_matcher = r'(?P<target>@\w{5,}|-100\d+)'
    target_matcher = rf'(\s+{bare_target_matcher})?'
    # command handler
    bot.add_event_handler(command.sub.cmd_sub,
                          events.NewMessage(pattern=r'(?P<command>/add|/sub)(@\w+)?'
                                                    + target_matcher +
                                                    r'(\s+(?P<url>.*))?\s*$'))
    bot.add_event_handler(command.sub.cmd_sub,
                          command.utils.PrivateMessage(pattern=r'https?://'))
    bot.add_event_handler(command.sub.cmd_sub,
                          command.utils.ReplyMessage(pattern=r'https?://'))
    bot.add_event_handler(command.sub.cmd_unsub,
                          events.NewMessage(pattern=r'(?P<command>/remove|/unsub)(@\w+)?'
                                                    + target_matcher +
                                                    r'(\s+(?P<url>.*))?\s*$'))
    bot.add_event_handler(command.sub.cmd_or_callback_unsub_all,
                          events.NewMessage(pattern=r'(?P<command>/remove_all|/unsub_all)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.sub.cmd_list_or_callback_get_list_page,
                          events.NewMessage(pattern=r'(?P<command>/list)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.opml.cmd_import,
                          events.NewMessage(pattern=r'(?P<command>/import)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.opml.cmd_export,
                          events.NewMessage(pattern=r'(?P<command>/export)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.customization.cmd_set_or_callback_get_set_page,
                          events.NewMessage(pattern=r'(?P<command>/set(?!_))(@\w+)?' + target_matcher))
    bot.add_event_handler(command.customization.cmd_set_default,
                          events.NewMessage(pattern=r'(?P<command>/set_default)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.customization.cmd_set_title,
                          events.NewMessage(pattern=r'(?P<command>/set_title)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.customization.cmd_set_interval,
                          events.NewMessage(pattern=r'(?P<command>/set_interval)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.customization.cmd_set_hashtags,
                          events.NewMessage(pattern=r'(?P<command>/set_hashtags)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.opml.opml_import,
                          command.utils.NewFileMessage(pattern='.*?' + bare_target_matcher + '?',
                                                       filename_pattern=r'^.*\.opml$'))
    bot.add_event_handler(command.misc.cmd_start,
                          events.NewMessage(pattern='/start'))
    bot.add_event_handler(command.misc.cmd_or_callback_help,
                          events.NewMessage(pattern='/help'))
    bot.add_event_handler(partial(command.customization.cmd_activate_or_deactivate_subs, activate=True),
                          events.NewMessage(pattern=r'(?P<command>/activate_subs)(@\w+)?' + target_matcher))
    bot.add_event_handler(partial(command.customization.cmd_activate_or_deactivate_subs, activate=False),
                          events.NewMessage(pattern=r'(?P<command>/deactivate_subs)(@\w+)?' + target_matcher))
    bot.add_event_handler(command.misc.cmd_lang,
                          events.NewMessage(pattern='/lang'))
    bot.add_event_handler(command.misc.cmd_version,
                          events.NewMessage(pattern='/version'))
    bot.add_event_handler(command.administration.cmd_test,
                          events.NewMessage(pattern='/test'))
    bot.add_event_handler(command.administration.cmd_user_info_or_callback_set_user,
                          events.NewMessage(pattern='/user_info'))
    bot.add_event_handler(command.administration.cmd_set_option,
                          events.NewMessage(pattern='/set_option'))

    callback_target_matcher = r'(%(?P<target>\d+))?'
    # callback query handler
    bot.add_event_handler(command.misc.callback_del_buttons,  # delete buttons
                          events.CallbackQuery(pattern='^del_buttons$'))
    bot.add_event_handler(command.misc.callback_null,  # null callback query
                          events.CallbackQuery(pattern='^null$'))
    bot.add_event_handler(command.misc.callback_cancel,
                          events.CallbackQuery(pattern='^cancel$'))
    bot.add_event_handler(command.misc.callback_get_group_migration_help,
                          events.CallbackQuery(pattern=r'^get_group_migration_help=[\w_\-]+$'))
    bot.add_event_handler(command.sub.cmd_list_or_callback_get_list_page,
                          events.CallbackQuery(pattern=rf'^get_list_page\|\d+{callback_target_matcher}$'))
    bot.add_event_handler(command.sub.callback_unsub,
                          events.CallbackQuery(pattern=rf'^unsub=\d+(\|\d+)?{callback_target_matcher}$'))
    bot.add_event_handler(command.sub.callback_get_unsub_page,
                          events.CallbackQuery(pattern=rf'^get_unsub_page\|\d+{callback_target_matcher}$'))
    bot.add_event_handler(command.sub.cmd_or_callback_unsub_all,
                          events.CallbackQuery(pattern=rf'unsub_all{callback_target_matcher}$'))
    bot.add_event_handler(command.misc.callback_set_lang,
                          events.CallbackQuery(pattern=r'^set_lang=[\w_\-]+$'))
    bot.add_event_handler(command.misc.cmd_or_callback_help,
                          events.CallbackQuery(pattern='^help$'))
    bot.add_event_handler(partial(command.customization.callback_activate_or_deactivate_all_subs, activate=True),
                          events.CallbackQuery(pattern=rf'^activate_all_subs{callback_target_matcher}$'))
    bot.add_event_handler(partial(command.customization.callback_activate_or_deactivate_all_subs, activate=False),
                          events.CallbackQuery(pattern=rf'^deactivate_all_subs{callback_target_matcher}$'))
    bot.add_event_handler(partial(command.customization.callback_activate_or_deactivate_sub, activate=True),
                          events.CallbackQuery(pattern=rf'^activate_sub=\d+(\|\d+)?{callback_target_matcher}$'))
    bot.add_event_handler(partial(command.customization.callback_activate_or_deactivate_sub, activate=False),
                          events.CallbackQuery(pattern=rf'^deactivate_sub=\d+(\|\d+)?{callback_target_matcher}$'))
    bot.add_event_handler(partial(command.customization.callback_get_activate_or_deactivate_page, activate=True),
                          events.CallbackQuery(pattern=rf'^get_activate_page\|\d+{callback_target_matcher}$'))
    bot.add_event_handler(partial(command.customization.callback_get_activate_or_deactivate_page, activate=False),
                          events.CallbackQuery(pattern=rf'^get_deactivate_page\|\d+{callback_target_matcher}$'))
    bot.add_event_handler(command.customization.cmd_set_or_callback_get_set_page,
                          events.CallbackQuery(pattern=rf'^get_set_page\|\d+{callback_target_matcher}$'))
    bot.add_event_handler(partial(command.customization.callback_set, set_user_default=False),
                          events.CallbackQuery(pattern=rf'^set(=\d+(,\w+(,\w+)?)?)?(\|\d+)?{callback_target_matcher}$'))
    bot.add_event_handler(partial(command.customization.callback_set, set_user_default=True),
                          events.CallbackQuery(pattern=rf'^set_default(=\w+(,\w+)?)?{callback_target_matcher}$'))
    bot.add_event_handler(command.customization.callback_reset,
                          events.CallbackQuery(pattern=rf'^reset=\d+(\|\d+)?{callback_target_matcher}$'))
    bot.add_event_handler(command.customization.callback_reset_all,
                          events.CallbackQuery(pattern=rf'^reset_all{callback_target_matcher}$'))
    bot.add_event_handler(command.customization.callback_reset_all_confirm,
                          events.CallbackQuery(pattern=rf'^reset_all_confirm{callback_target_matcher}$'))
    bot.add_event_handler(command.customization.callback_del_subs_title,
                          events.CallbackQuery(pattern=r'^del_subs_title=(\d+-\d+\|)*(\d+-\d+)'
                                                       rf'{callback_target_matcher}$'))
    bot.add_event_handler(command.administration.cmd_user_info_or_callback_set_user,
                          events.CallbackQuery(pattern=r'^set_user=-?\d+,(-1|0|1)$'))
    # inline query handler
    bot.add_event_handler(command.misc.inline_command_constructor,
                          events.InlineQuery())
    # being added to a group handler
    bot.add_event_handler(command.misc.cmd_start,
                          command.utils.AddedToGroupAction())
    bot.add_event_handler(command.misc.cmd_start,
                          command.utils.GroupMigratedAction())


async def post():
    await db.close()


def main():
    loop.run_until_complete(
        pre()
    )

    scheduler = AsyncIOScheduler(event_loop=loop)
    scheduler.add_job(func=command.monitor.run_monitor_task,
                      trigger=CronTrigger(minute='*', second=env.CRON_SECOND, timezone='UTC'),
                      max_instances=10,
                      misfire_grace_time=10)
    scheduler.start()

    bot.run_until_disconnected()

    loop.run_until_complete(
        post()
    )


if __name__ == '__main__':
    main()
