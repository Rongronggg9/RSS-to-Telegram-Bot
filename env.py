import os
import telegram
import logging
from typing import Optional

TOKEN = os.environ.get('TOKEN')
CHATID = os.environ.get('CHATID')
DELAY = int(os.environ.get('DELAY', 300))

if TOKEN is None or CHATID is None:
    logging.critical('TOKEN OR CHATID NOT SET!')
    exit(1)

MANAGER = os.environ.get('MANAGER', CHATID)

TELEGRAM_PROXY = os.environ.get('T_PROXY', '')

if os.environ.get('R_PROXY'):
    REQUESTS_PROXIES = {
        'all': os.environ['R_PROXY']
    }
else:
    REQUESTS_PROXIES = {}

IMG_RELAY_SERVER = os.environ.get('IMG_RELAY_SERVER', 'https://rsstt-img-relay.rongrong.workers.dev/')
if not IMG_RELAY_SERVER.endswith('/'):
    IMG_RELAY_SERVER += '/'

REDIS_HOST = os.environ.get('REDISHOST')
REDIS_USER = os.environ.get('REDISUSER')
REDIS_PORT = int(os.environ.get('REDISPORT', 6379))
REDIS_PASSWORD = os.environ.get('REDISPASSWORD')
REDIS_NUM = os.environ.get('REDIS_NUM')

if os.environ.get('DEBUG'):
    DEBUG = True
else:
    DEBUG = False

bot: Optional[telegram.Bot] = None  # placeholder

REQUESTS_HEADERS = {
    'user-agent': 'RSStT'
}
