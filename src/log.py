from __future__ import annotations

import logging
import colorlog
from time import sleep

from src import env

getLogger = colorlog.getLogger
DEBUG = colorlog.DEBUG
INFO = colorlog.INFO
WARNING = colorlog.WARNING
ERROR = colorlog.ERROR
CRITICAL = colorlog.CRITICAL

colorlog.basicConfig(format='%(log_color)s%(asctime)s:%(levelname)s:%(name)s - %(message)s',
                     datefmt='%Y-%m-%d-%H:%M:%S',
                     level=colorlog.DEBUG if env.DEBUG else colorlog.INFO)

_muted = colorlog.INFO if env.DEBUG else colorlog.WARNING
_shut_upped = colorlog.ERROR if env.DEBUG else colorlog.CRITICAL

getLogger('apscheduler').setLevel(colorlog.WARNING)
getLogger('aiohttp_retry').setLevel(_muted)
getLogger('asyncio').setLevel(_muted)
getLogger('telethon').setLevel(_muted)
getLogger('aiosqlite').setLevel(_muted)
getLogger('tortoise').setLevel(_muted)
getLogger('asyncpg').setLevel(_muted)
getLogger('PIL').setLevel(_muted)

_logger = getLogger('rsstt.watchdog')


# flit log from apscheduler.scheduler
class APSCFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg % record.args
        if 'skipped: maximum number of running instances reached' in msg:
            self.count += 1
            if self.count != 0 and self.count % 5 == 0:
                coro = env.bot.send_message(
                    env.MANAGER,
                    f'RSS monitor tasks have conflicted too many times ({self.count})!\n'
                    + ('Please store the log and restart.\n(sometimes it may be caused by too many subscriptions)'
                       if self.count < 15 else
                       'Now the bot will restart.')
                    + '\n\n' + msg
                )
                env.loop.create_task(coro)
                if self.count >= 15:
                    _logger.critical(f'RSS monitor tasks have conflicted too many times ({self.count})! Exiting...')
                    sleep(1)  # wait for message to be sent
                    exit(-1)
            return True
        if ' executed successfully' in msg:
            self.count = 0
            return False
        if 'Running job "rss_monitor ' in msg:
            return False
        return True


apsc_filter = APSCFilter()
getLogger('apscheduler.scheduler').addFilter(apsc_filter)
getLogger('apscheduler.executors.default').addFilter(apsc_filter)


class AiohttpAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg % record.args
        if record.levelno <= logging.INFO and 'Mozilla' not in msg:
            return False
        return True


aiohttp_access_filter = AiohttpAccessFilter()
getLogger('aiohttp.access').addFilter(aiohttp_access_filter)
