#  RSS to Telegram Bot
#  Copyright (C) 2020-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from typing import Optional

# the event loop and basic configurations are initialized in env, so import it first
# some logger configurations are set in log, so import it second to make them effective in child processes
from . import env, log
from . import aio_helper

# the process pool need to be initialized once the event loop is ready to reduce memory consumption
aio_helper.init()

# register main-process-only log handlers
log.init()

import os
import signal
import asyncio
from functools import partial
from itertools import chain
from time import sleep
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telethon import TelegramClient, events
from telethon.errors import ApiIdPublishedFloodError, RPCError
from telethon.tl import types
from random import sample

from . import log, db, command
from .monitor import Monitor
from .i18n import i18n, ALL_LANGUAGES, get_commands_list
from .parsing import tgraph
from .helpers.bg import bg
from .helpers.queue import queued

# log
logger = log.getLogger('RSStT')

loop = env.loop
bot: Optional[TelegramClient] = None
pre_tasks = []

monitor = Monitor()
scheduler = AsyncIOScheduler(event_loop=loop)


def init():
    global bot

    if not env.API_ID or not env.API_HASH:
        logger.info('API_ID and/or API_HASH not set, use sample APIs instead. API_ID_PUBLISHED_FLOOD_ERROR may occur.')
        api_keys = {api_id: env.SAMPLE_APIS[api_id]
                    for api_id in sample(tuple(env.SAMPLE_APIS.keys()), len(env.SAMPLE_APIS))}
    else:
        api_keys = {env.API_ID: env.API_HASH}

    # pre tasks
    pre_tasks.extend((
        loop.create_task(db.init()),
        loop.create_task(tgraph.init()),
        loop.create_task(bg.init(loop=loop)),
        loop.create_task(queued.init(loop=loop)),
    ))

    if env.PORT:
        # enable redirect server for Railway, Heroku, etc
        from . import redirect_server

        pre_tasks.append(loop.create_task(redirect_server.run(port=env.PORT)))

    if env.TOKEN.lower() == 'test':
        # no login, just for test
        logger.info('Test mode, no login.')
        loop.run_until_complete(asyncio.gather(*pre_tasks))
        exit(0)

    sleep_for = 0
    while api_keys:
        sleep_for += 10
        api_id, api_hash = api_keys.popitem()
        try:
            bot = TelegramClient(os.path.join(env.config_folder_path, 'bot'), api_id, api_hash,
                                 proxy=env.TELEGRAM_PROXY_DICT, request_retries=2, flood_sleep_threshold=60,
                                 raise_last_call_error=True, loop=loop).start(bot_token=env.TOKEN)
            break
        except ApiIdPublishedFloodError:
            if not api_keys:
                logger.warning('API_ID_PUBLISHED_FLOOD_ERROR occurred.')
                break
            logger.warning(f'API_ID_PUBLISHED_FLOOD_ERROR occurred. Sleep for {sleep_for}s and retry.')
            sleep(sleep_for)
        except Exception as e:
            logger.critical('Unknown error occurred during login:', exc_info=e)
            break

    if bot is None:
        logger.critical('LOGIN FAILED!')
        exit(1)

    env.bot = bot
    env.bot_peer = loop.run_until_complete(bot.get_me(input_peer=False))
    env.bot_input_peer = loop.run_until_complete(bot.get_me(input_peer=True))
    env.bot_id = env.bot_peer.id


async def pre():
    # wait for pre tasks
    await asyncio.gather(*pre_tasks)

    bare_target_matcher = r'(?P<target>@\w{4,}|(-100|\+)\d+)'
    target_matcher = rf'(\s+{bare_target_matcher})?'
    _command_matcher = r'(?P<command>{}(?=[\s@]|$))(@\w+)?'
    construct_command_matcher = _command_matcher.format
    construct_remote_command_matcher = partial((_command_matcher + '{target}').format, target=target_matcher)
    urls_matcher = r'(\s+(?P<url>\S+))*'
    # command handler
    bot.add_event_handler(command.sub.cmd_sub,
                          events.NewMessage(pattern=construct_remote_command_matcher('/add|/sub') + urls_matcher))
    bot.add_event_handler(command.sub.cmd_sub,
                          command.utils.PrivateMessage(pattern=r'https?://'))
    bot.add_event_handler(command.sub.cmd_sub,
                          command.utils.ReplyMessage(pattern=r'https?://'))
    bot.add_event_handler(command.sub.cmd_unsub,
                          events.NewMessage(pattern=construct_remote_command_matcher('/remove|/unsub') + urls_matcher))
    bot.add_event_handler(command.sub.cmd_or_callback_unsub_all,
                          events.NewMessage(pattern=construct_remote_command_matcher('/remove_all|/unsub_all')))
    bot.add_event_handler(command.sub.cmd_list_or_callback_get_list_page,
                          events.NewMessage(pattern=construct_remote_command_matcher('/list')))
    bot.add_event_handler(command.opml.cmd_import,
                          events.NewMessage(pattern=construct_remote_command_matcher('/import')))
    bot.add_event_handler(command.opml.cmd_export,
                          events.NewMessage(pattern=construct_remote_command_matcher('/export')))
    bot.add_event_handler(command.customization.cmd_set_or_callback_get_set_page,
                          events.NewMessage(pattern=construct_remote_command_matcher('/set')))
    bot.add_event_handler(command.customization.cmd_set_default,
                          events.NewMessage(pattern=construct_remote_command_matcher('/set_default')))
    bot.add_event_handler(command.opml.opml_import,
                          command.utils.NewFileMessage(pattern=rf'.*?{bare_target_matcher}?',
                                                       filename_pattern=r'^.*\.opml$'))
    bot.add_event_handler(command.misc.cmd_start,
                          events.NewMessage(pattern=construct_command_matcher('/start')))
    bot.add_event_handler(command.misc.cmd_or_callback_help,
                          events.NewMessage(pattern=construct_command_matcher('/help')))
    bot.add_event_handler(partial(command.customization.cmd_activate_or_deactivate_subs, activate=True),
                          events.NewMessage(pattern=construct_remote_command_matcher('/activate_subs')))
    bot.add_event_handler(partial(command.customization.cmd_activate_or_deactivate_subs, activate=False),
                          events.NewMessage(pattern=construct_remote_command_matcher('/deactivate_subs')))
    bot.add_event_handler(command.misc.cmd_lang,
                          events.NewMessage(pattern=construct_remote_command_matcher('/lang')))
    bot.add_event_handler(command.misc.cmd_version,
                          events.NewMessage(pattern=construct_command_matcher('/version')))
    bot.add_event_handler(command.administration.cmd_test,
                          events.NewMessage(pattern=construct_remote_command_matcher('/test')))
    bot.add_event_handler(command.administration.cmd_user_info_or_callback_set_user,
                          events.NewMessage(pattern=construct_command_matcher('/user_info')))
    bot.add_event_handler(command.administration.cmd_set_option,
                          events.NewMessage(pattern=construct_command_matcher('/set_option')))

    # trigger bt inline query
    inline_query_matcher = rf'(@{env.bot_peer.username}\s+)?'
    bot.add_event_handler(command.administration.cmd_set_sub_limit,
                          events.NewMessage(
                              pattern=inline_query_matcher + construct_command_matcher('/set_sub_limit')))
    bot.add_event_handler(command.customization.cmd_set_title,
                          events.NewMessage(
                              pattern=inline_query_matcher + construct_remote_command_matcher('/set_title')))
    bot.add_event_handler(command.customization.cmd_set_interval,
                          events.NewMessage(
                              pattern=inline_query_matcher + construct_remote_command_matcher('/set_interval')))
    bot.add_event_handler(command.customization.cmd_set_hashtags,
                          events.NewMessage(
                              pattern=inline_query_matcher + construct_remote_command_matcher('/set_hashtags')))

    callback_target_matcher = r'(%(?P<target>\+?\d+))?'
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
                          events.CallbackQuery(pattern=rf'^set_lang=[\w_\-]+{callback_target_matcher}$'))
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
    bot.add_event_handler(command.administration.callback_reset_sub_limit,
                          events.CallbackQuery(pattern=r'^reset_sub_limit=-?\d+$'))
    # inline query handler
    bot.add_event_handler(command.misc.inline_command_constructor,
                          events.InlineQuery())
    # being added to a group handler
    bot.add_event_handler(command.misc.cmd_start,
                          command.utils.AddedToGroupAction())
    bot.add_event_handler(command.misc.cmd_start,
                          command.utils.GroupMigratedAction())


async def lazy():
    manager_lang_d: dict[int, str] = dict(await db.User.filter(id__in=env.MANAGER).values_list('id', 'lang'))

    cmd_coro_chain = chain(
        (
            command.utils.set_bot_commands(scope=types.BotCommandScopeDefault(),
                                           lang_code='',
                                           commands=get_commands_list()),
        ), (
            command.utils.set_bot_commands(scope=types.BotCommandScopeDefault(),
                                           lang_code=i18n[lang]['iso_639_code'],
                                           commands=get_commands_list(lang=lang))
            for lang in ALL_LANGUAGES if len(i18n[lang]['iso_639_code']) == 2
        ), (
            command.utils.set_bot_commands(scope=types.BotCommandScopePeer(types.InputPeerUser(manager, 0)),
                                           lang_code='',
                                           commands=get_commands_list(lang=lang, manager=True))
            for manager, lang in manager_lang_d.items()
        ),
    )

    for coro in cmd_coro_chain:
        try:
            await asyncio.gather(asyncio.sleep(1.5), coro)  # sleep to avoid flood
        except RPCError as e:
            logger.warning('Set command error: ', exc_info=e)


async def post():
    logger.info('Exiting gracefully...')
    tasks = [
        asyncio.shield(loop.create_task(db.close())),
        loop.create_task(tgraph.close()),
        loop.create_task(bg.close()),
        loop.create_task(queued.close()),
    ]
    if scheduler.running:
        scheduler.shutdown(wait=False)
    if bot and bot.is_connected():
        tasks.append(bot.disconnect())
    res = await asyncio.gather(*tasks, return_exceptions=True)
    for e in (e for e in res if isinstance(e, BaseException)):
        logger.error('Error when exiting gracefully: ', exc_info=e)
    aio_helper.shutdown()


def force_quit(*_):
    logger.critical('Force quitting...', stack_info=True)
    os.kill(os.getpid(), signal.SIGKILL)


def sig_handler(signum, *_, **__):
    try:
        logger.warning(f'Received signal {signal.Signals(signum).name}')
    except ValueError:
        logger.warning(f'Received signal {signum}')
    exit(128 + signum)


def main():
    # bot.disconnected usually means the bot is logged out due to a network error or Telegram DC degradation,
    # so we should exit with a non-zero code to indicate an error.
    # This aims to avoid confusion when running the bot in a container or as a service.
    exit_code = 100

    try:
        signal.signal(signal.SIGTERM, sig_handler)  # graceful exit handler

        init()

        loop.run_until_complete(pre())

        logger.info(
            f"RSS-to-Telegram-Bot ({', '.join(env.VERSION.split())}) started!\n"
            f"SELF: {env.bot_peer.first_name} @{env.bot_peer.username} ({env.bot_peer.id})\n"  # bot has no last name
            f"MANAGER: {', '.join(map(str, env.MANAGER))}\n"
            f"ERROR_LOGGING_CHAT: {env.ERROR_LOGGING_CHAT}\n"
            f"T_PROXY (for Telegram): {env.TELEGRAM_PROXY or 'not set'}\n"
            f"R_PROXY (for RSS): {env.REQUESTS_PROXIES['all'] if env.REQUESTS_PROXIES else 'not set'}\n"
            f"DATABASE: {env.DATABASE_URL.split('://', 1)[0]}\n"
            f"TELEGRAPH: {f'Enable ({tgraph.apis.count} accounts)' if tgraph.apis else 'Disable'}\n"
            f"UVLOOP: {'Enable' if env.uvloop_enabled else 'Disable'}\n"
            f"MULTIUSER: {'Enable' if env.MULTIUSER else 'Disable'}\n"
            f"CPU: {aio_helper.PROCESS_COUNT} (usable) / "
            f"{aio_helper.AVAIL_CPU_COUNT} (available) / "
            f"{aio_helper.CPU_COUNT} (total)"
        )
        if env.MANAGER_PRIVILEGED:
            logger.warning('Bot manager privileged mode is enabled! '
                           'Use with caution and should be disabled in production!')

        loop.create_task(lazy())

        scheduler.add_job(func=monitor.run_periodic_task,
                          trigger=CronTrigger(minute='*', second=env.CRON_SECOND, timezone='UTC'),
                          max_instances=10,
                          misfire_grace_time=10)
        scheduler.start()

        loop.run_until_complete(bot.disconnected)
    except (KeyboardInterrupt, SystemExit) as e:
        logger.error(f'Received {type(e).__name__}, exiting...', exc_info=e)
        exit_code = e.code if isinstance(e, SystemExit) and e.code is not None else 0
    except Exception as e:
        logger.critical('Uncaught error:', exc_info=e)
        exit_code = 99
    finally:
        try:
            if getattr(signal, 'SIGALRM', None):
                signal.alarm(15)
                signal.signal(signal.SIGALRM, force_quit)  # double insurance
            loop.call_later(10, force_quit)
        except Exception as e:
            logger.warning('Error when setting exit timeout (this is a bug, please report it):', exc_info=e)
        for _ in range(3):
            try:
                loop.run_until_complete(asyncio.shield(post()))
            except RuntimeError as e:
                logger.error('Event loop stopped when exiting gracefully (probably caused by a race condition):',
                             exc_info=e)
            except Exception as e:
                logger.critical('Error when exiting gracefully (this is a bug, please report it):', exc_info=e)
                force_quit()
            else:
                break
        else:
            force_quit()
        logger.log(log.INFO if exit_code == 0 else log.ERROR, f'Exited with code {exit_code}')
        exit(exit_code)


if __name__ == '__main__':
    main()
