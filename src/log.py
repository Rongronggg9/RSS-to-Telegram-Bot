import asyncio
import logging
import colorlog
from threading import Thread

from src import env

getLogger = colorlog.getLogger

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


# flit log from apscheduler.scheduler
class APSCFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.count = -3  # first 3 times muted

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg % record.args
        if 'skipped: maximum number of running instances reached' in msg:
            self.count += 1
            if self.count % 5 == 0:
                if self.count >= 15:
                    exit(-1)
                coro = env.bot.send_message(
                    env.MANAGER,
                    'RSS monitor tasks have conflicted too many times! Please store the log and restart.\n'
                    ' (sometimes it may be caused by too many subscriptions)\n\n'
                    + msg
                )
                Thread(target=asyncio.run, args=(coro,)).start()
            return True
        if ' executed successfully' in msg:
            self.count = -3  # only >= 4 consecutive failures lead to a manager warning
            return False
        if 'Running job "rss_monitor ' in msg:
            return False
        return True


apsc_filter = APSCFilter()
getLogger('apscheduler.scheduler').addFilter(apsc_filter)
getLogger('apscheduler.executors.default').addFilter(apsc_filter)
