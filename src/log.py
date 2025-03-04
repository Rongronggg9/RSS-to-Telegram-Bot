#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
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
from typing_extensions import Awaitable

import asyncio
import logging
import colorlog
import os
import signal

from . import env

getLogger = colorlog.getLogger
DEBUG = colorlog.DEBUG
INFO = colorlog.INFO
WARNING = colorlog.WARNING
ERROR = colorlog.ERROR
CRITICAL = colorlog.CRITICAL

logger_level_muted = colorlog.INFO if env.DEBUG else colorlog.WARNING
logger_level_shut_upped = colorlog.ERROR if env.DEBUG else colorlog.CRITICAL

getLogger('aiohttp_retry').setLevel(logger_level_muted)
getLogger('asyncio').setLevel(logger_level_muted)
getLogger('telethon').setLevel(logger_level_muted)
getLogger('aiosqlite').setLevel(logger_level_muted)
getLogger('tortoise').setLevel(logger_level_muted)
getLogger('asyncpg').setLevel(logger_level_muted)
getLogger('PIL').setLevel(logger_level_muted)
getLogger('matplotlib').setLevel(logger_level_muted)
getLogger('matplotlib.font_manager').setLevel(logger_level_shut_upped)

_logger = getLogger('RSStT.watchdog')


async def exit_handler(prerequisite: Awaitable = None):
    try:
        if prerequisite and env.bot.is_connected():
            try:
                await asyncio.wait_for(prerequisite, timeout=10)
            except asyncio.TimeoutError:
                _logger.critical('Failed to gracefully exit: prerequisite timed out')
    except Exception as e:
        _logger.critical('Failed to gracefully exit:', exc_info=e)
    finally:
        exit(1)


def shutdown(prerequisite: Awaitable = None):
    if not env.loop.is_running():
        exit(1)
    env.loop.call_later(20, lambda: os.kill(os.getpid(), signal.SIGKILL))  # double insurance
    asyncio.gather(env.loop.create_task(exit_handler(prerequisite)), return_exceptions=True)


class _Watchdog:
    def __init__(self, delay: int = 10 * 60):
        self._watchdog = env.loop.call_later(delay, self._exit_bot, delay)

    @staticmethod
    def _exit_bot(delay):
        msg = f'Never heard from the bot for {delay} seconds. Exiting...'
        _logger.critical(msg)
        coro = None
        if env.bot is not None:
            coro = env.loop.create_task(env.bot.send_message(env.ERROR_LOGGING_CHAT, f'WATCHDOG: {msg}'))
        shutdown(prerequisite=coro)

    def feed(self, delay: int = 15 * 60):
        self._watchdog.cancel()
        self._watchdog = env.loop.call_later(delay, self._exit_bot, delay)


# flit log from apscheduler.scheduler
class _APSCFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.count = 0
        self.watchdog = _Watchdog()

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg % record.args
        if 'skipped: maximum number of running instances reached' in msg:
            self.count += 1
            if self.count != 0 and self.count % 5 == 0:
                coro = env.bot.send_message(
                    env.ERROR_LOGGING_CHAT,
                    f'RSS monitor tasks have conflicted too many times ({self.count})!\n'
                    + ('Please store the log and restart.\n(sometimes it may be caused by too many subscriptions)'
                       if self.count < 15 else
                       'Now the bot will restart.')
                    + '\n\n' + msg
                )
                if self.count >= 15:
                    _logger.critical(f'RSS monitor tasks have conflicted too many times ({self.count})! Exiting...')
                    shutdown(prerequisite=coro)
                else:
                    env.loop.create_task(coro)
            return True
        if ' executed successfully' in msg:
            return False
        if 'Running job "Monitor.run_periodic_task' in msg:
            self.count = 0
            self.watchdog.feed()
            return False
        return True


class _AiohttpAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg % record.args
        if record.levelno <= logging.INFO and 'Mozilla' not in msg:
            return False
        return True


class _TelethonClientUpdatesFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg % record.args
        if 'Fatal error' in msg:
            coro = env.bot.send_message(
                env.ERROR_LOGGING_CHAT,
                msg + '\n\n' + 'Now the bot will restart.'
            )
            _logger.critical('Telethon client fatal error! Exiting...')
            shutdown(prerequisite=coro)
        return True


def init():
    apsc_filter = _APSCFilter()
    getLogger('apscheduler').setLevel(colorlog.WARNING)
    getLogger('apscheduler.executors.default').setLevel(colorlog.INFO)
    getLogger('apscheduler.scheduler').addFilter(apsc_filter)
    getLogger('apscheduler.executors.default').addFilter(apsc_filter)

    getLogger('aiohttp.access').addFilter(_AiohttpAccessFilter())

    getLogger('telethon.client.updates').addFilter(_TelethonClientUpdatesFilter())
