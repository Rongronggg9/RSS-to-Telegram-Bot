import os
import telegram
import logging
from typing import Optional

# ----- base config -----
TOKEN = os.environ.get('TOKEN')
CHATID = os.environ.get('CHATID')
DELAY = int(os.environ.get('DELAY', 300))

if TOKEN is None or CHATID is None:
    logging.critical('TOKEN OR CHATID NOT SET! PLEASE CHECK YOUR SETTINGS!')
    exit(1)

MANAGER = os.environ.get('MANAGER', CHATID)

TELEGRAPH_TOKEN = os.environ.get('TELEGRAPH_TOKEN')
if TELEGRAPH_TOKEN:
    TELEGRAPH_TOKEN = TELEGRAPH_TOKEN.strip(). \
        replace('\n', ',') \
        .replace('，', ',') \
        .replace(';', ',') \
        .replace('；', ',') \
        .replace(' ', ',')

# ----- proxy config -----
DEFAULT_PROXY = os.environ.get('SOCKS_PROXY', os.environ.get('HTTP_PROXY', None))

TELEGRAM_PROXY = os.environ.get('T_PROXY', DEFAULT_PROXY)

R_PROXY = os.environ.get('R_PROXY', DEFAULT_PROXY)

if R_PROXY:
    REQUESTS_PROXIES = {
        'all': R_PROXY
    }
else:
    REQUESTS_PROXIES = {}

# ----- img relay server config -----
IMG_RELAY_SERVER = os.environ.get('IMG_RELAY_SERVER', 'https://rsstt-img-relay.rongrong.workers.dev/')
if not IMG_RELAY_SERVER.endswith('/'):
    IMG_RELAY_SERVER += '/'

# ----- redis config -----
REDIS_HOST = os.environ.get('REDISHOST')
REDIS_PORT = os.environ.get('REDISPORT')
REDIS_USER = os.environ.get('REDISUSER')
REDIS_PASSWORD = os.environ.get('REDISPASSWORD')
REDIS_NUM = os.environ.get('REDIS_NUM')
if REDIS_PORT:
    REDIS_PORT = int(REDIS_PORT)
if REDIS_NUM:
    REDIS_PORT = int(REDIS_NUM)

# ----- debug config -----
if os.environ.get('DEBUG'):
    DEBUG = True
else:
    DEBUG = False

# ----- get version -----
try:
    with open('.version', 'r') as v:
        VERSION = v.read().strip()
except:
    VERSION = 'dirty'

if VERSION == 'dirty':
    from subprocess import Popen, PIPE, DEVNULL

    try:
        with Popen('git describe --tags', shell=True, stdout=PIPE, stderr=DEVNULL, bufsize=-1) as __:
            __.wait(3)
            VERSION = __.stdout.read().decode().strip()
        with Popen('git branch --show-current', shell=True, stdout=PIPE, stderr=DEVNULL, bufsize=-1) as __:
            __.wait(3)
            __ = __.stdout.read().decode().strip()
            if __:
                VERSION += f'@{__}'
    except:
        VERSION = 'dirty'

if not VERSION or VERSION == '@':
    VERSION = 'dirty'

# ----- shared var -----
bot: Optional[telegram.Bot] = None  # placeholder

REQUESTS_HEADERS = {
    'user-agent': 'RSStT'
}
