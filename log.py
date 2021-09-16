import logging
import colorlog

import env

getLogger = colorlog.getLogger

colorlog.basicConfig(format='%(log_color)s%(asctime)s:%(levelname)s:%(name)s - %(message)s',
                     datefmt='%Y-%m-%d-%H:%M:%S',
                     level=logging.DEBUG if env.DEBUG else logging.INFO)

getLogger("telegram").setLevel(colorlog.INFO)
getLogger("requests").setLevel(colorlog.ERROR if env.DEBUG else colorlog.CRITICAL)
getLogger("urllib3").setLevel(colorlog.ERROR if env.DEBUG else colorlog.CRITICAL)
getLogger('apscheduler').setLevel(colorlog.INFO if env.DEBUG else colorlog.WARNING)


# flit log from apscheduler.scheduler
class APSCFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.count = -3  # first 3 times muted

    def filter(self, record: logging.LogRecord) -> bool:
        if 'skipped: maximum number of running instances reached' in record.msg:
            self.count += 1
            if self.count % 10 == 0:
                env.bot.send_message(
                    env.MANAGER, 'RSS 更新检查发生冲突，程序可能出现问题，请记录日志并重启。\n'
                                 '（这也可能是由过短的检查间隔和过多的订阅引起，请适度调整后观察是否还有错误）\n\n'
                                 + (record.msg % record.args if record.args else record.msg)
                )
        elif ' executed successfully' in record.msg:
            self.count = -3  # only >= 4 concective failures lead to a manager warning
        return True


getLogger('apscheduler.scheduler').addFilter(APSCFilter())
