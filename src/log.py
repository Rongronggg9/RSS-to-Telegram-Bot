import logging
import colorlog

from src import env

getLogger = colorlog.getLogger

colorlog.basicConfig(format='%(log_color)s%(asctime)s:%(levelname)s:%(name)s - %(message)s',
                     datefmt='%Y-%m-%d-%H:%M:%S',
                     level=logging.DEBUG if env.DEBUG else logging.INFO)

_muted = colorlog.INFO if env.DEBUG else colorlog.WARNING
_shut_upped = colorlog.ERROR if env.DEBUG else colorlog.CRITICAL

getLogger("telegram").setLevel(colorlog.INFO)
getLogger("requests").setLevel(_shut_upped)
getLogger("urllib3").setLevel(_shut_upped)
getLogger('apscheduler').setLevel(_muted)
getLogger('aiohttp_retry').setLevel(_muted)
getLogger('asyncio').setLevel(_muted)
getLogger('telethon').setLevel(_muted)


# flit log from apscheduler.scheduler
class APSCFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.count = -3  # first 3 times muted

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg % record.args
        if 'skipped: maximum number of running instances reached' in msg:
            self.count += 1
            if self.count % 10 == 0:
                env.bot.send_message(
                    env.MANAGER, 'RSS 更新检查发生冲突，程序可能出现问题，请记录日志并重启。\n'
                                 '（这也可能是由过短的检查间隔和过多的订阅引起，请适度调整后观察是否还有错误）\n\n'
                                 + msg
                )
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
