import logging
import colorlog

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

_logger = getLogger('watchdog')

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
                if self.count >= 15:
                    _logger.critical(f'RSS monitor tasks have conflicted too many times ({self.count})! Exiting...')
                    exit(-1)
                coro = env.bot.send_message(
                    env.MANAGER,
                    f'RSS monitor tasks have conflicted too many times ({self.count})! '
                    'Please store the log and restart.\n'
                    ' (sometimes it may be caused by too many subscriptions)\n\n'
                    + msg
                )
                env.loop.create_task(coro)
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
