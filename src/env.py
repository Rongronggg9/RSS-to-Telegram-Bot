import os
import logging
from telethon import TelegramClient
from typing import Optional, Final
from python_socks import parse_proxy_url
from dotenv import load_dotenv

# ----- load .env -----
load_dotenv(override=True)

# ----- basic config -----
SAMPLE_APIS: Final = {
    # https://github.com/DrKLO/Telegram/blob/master/TMessagesProj/src/main/java/org/telegram/messenger/BuildVars.java
    4: '014b35b6184100b085b0d0572f9b5103',
    # https://github.com/TelegramMessenger/Telegram-iOS/blob/master/build-system/verify.sh
    8: '7245de8e747a0d6fbe11f7cc14fcc0bb',
    # https://github.com/overtake/TelegramSwift/blob/master/Telegram-Mac/Config.swift
    9: '3975f648bb682ee889f35483bc618d1c',
    # https://github.com/vysheng/tg/blob/master/loop.h
    2899: '36722c72256a24c1225de00eb6a1ca74',
    # https://github.com/telegramdesktop/tdesktop/blob/dev/docs/api_credentials.md
    17349: '344583e45741c457fe1862106095a5eb',
    # https://github.com/tdlib/td/blob/master/example/uwp/app/MainPage.xaml.cs
    94575: 'a3406de8d171bb422bb6ddf3bbd800e2',
    # https://github.com/morethanwords/tweb/blob/master/t.py
    1025907: '452b0359b988148995f22ff0f4229750'
}

API_ID: Final = int(os.environ['API_ID']) if os.environ.get('API_ID') else None
API_HASH: Final = os.environ.get('API_HASH')
TOKEN: Final = os.environ.get('TOKEN')

try:
    _chatid = os.environ.get('CHATID')
    _chatid = int(_chatid) if isinstance(_chatid, str) and _chatid.lstrip('-').isdecimal() else _chatid
    _manager = os.environ.get('MANAGER', _chatid)
    MANAGER: Final = int(_manager) if isinstance(_manager, str) and _manager.lstrip('-').isdecimal() else _manager
    del _chatid
    del _manager

    if TOKEN is None or MANAGER is None:
        logging.critical('"TOKEN" OR "MANAGER" NOT SET! PLEASE CHECK YOUR SETTINGS!')
        exit(1)
except Exception as e:
    logging.critical('INVALID "MANAGER"! PLEASE CHECK YOUR SETTINGS!', exc_info=e)
    exit(1)

_telegraph_token = os.environ.get('TELEGRAPH_TOKEN')
if _telegraph_token:
    TELEGRAPH_TOKEN: Final = _telegraph_token.strip(). \
        replace('\n', ',') \
        .replace('，', ',') \
        .replace(';', ',') \
        .replace('；', ',') \
        .replace(' ', ',')
else:
    TELEGRAPH_TOKEN: Final = None

del _telegraph_token

_multiuser = os.environ.get('MULTIUSER', '')
if _multiuser is None or _multiuser == '0' or _multiuser.lower() == 'false':
    MULTIUSER: Final = False
else:
    MULTIUSER: Final = True

# ----- proxy config -----
DEFAULT_PROXY: Final = os.environ.get('SOCKS_PROXY', os.environ.get('HTTP_PROXY', None))

TELEGRAM_PROXY: Final = os.environ.get('T_PROXY', DEFAULT_PROXY)
if TELEGRAM_PROXY:
    _parsed = parse_proxy_url(TELEGRAM_PROXY.replace('socks5h', 'socks5'))
    TELEGRAM_PROXY_DICT: Final = {
        'proxy_type': _parsed[0],
        'addr': _parsed[1],
        'port': _parsed[2],
        'username': _parsed[3],
        'password': _parsed[4],
        'rdns': True
    }
    TELEGRAPH_PROXY_DICT: Final = {
        'proxy_type': _parsed[0],
        'host': _parsed[1],
        'port': _parsed[2],
        'username': _parsed[3],
        'password': _parsed[4],
        'rdns': True
    }
    del _parsed
else:
    TELEGRAM_PROXY_DICT: Final = None
    TELEGRAPH_PROXY_DICT: Final = None

R_PROXY: Final = os.environ.get('R_PROXY', DEFAULT_PROXY)

if R_PROXY:
    REQUESTS_PROXIES: Final = {
        'all': R_PROXY
    }
else:
    REQUESTS_PROXIES: Final = {}

# ----- img relay server config -----
_img_relay_server = os.environ.get('IMG_RELAY_SERVER', 'https://rsstt-img-relay.rongrong.workers.dev/')
IMG_RELAY_SERVER: Final = _img_relay_server + ('' if _img_relay_server.endswith('/') else '/')
del _img_relay_server

# ----- db config -----
_database_url = os.environ.get('DATABASE_URL', 'sqlite://config/db.sqlite3?journal_mode=OFF')
DATABASE_URL: Final = (_database_url.replace('postgresql', 'postgres', 1) if _database_url.startswith('postgresql')
                       else _database_url)
del _database_url

# ----- debug config -----
if os.environ.get('DEBUG'):
    DEBUG: Final = True
else:
    DEBUG: Final = False

# ----- get version -----
try:
    with open('.version', 'r') as v:
        _version = v.read().strip()
except Exception:
    _version = 'dirty'

if _version == 'dirty':
    from subprocess import Popen, PIPE, DEVNULL

    try:
        with Popen('git describe --tags', shell=True, stdout=PIPE, stderr=DEVNULL, bufsize=-1) as __:
            __.wait(3)
            _version = __.stdout.read().decode().strip()
        with Popen('git branch --show-current', shell=True, stdout=PIPE, stderr=DEVNULL, bufsize=-1) as __:
            __.wait(3)
            __ = __.stdout.read().decode().strip()
            if __:
                _version += f'@{__}'
    except Exception:
        _version = 'dirty'

if not _version or _version == '@':
    _version = 'dirty'

VERSION: Final = _version
del _version

# !!!!! DEPRECATED WARNING !!!!!
if os.environ.get('DELAY'):
    logging.warning('Env var "DELAY" is DEPRECATED and of no use!\n'
                    'To avoid this warning, remove this env var.')

if os.environ.get('CHATID'):
    logging.warning('Env var "CHATID" is DEPRECATED!\n'
                    'To avoid this warning, remove this env var.')

if any((os.environ.get('REDISHOST'), os.environ.get('REDISUSER'), os.environ.get('REDISPASSWORD'),
        os.environ.get('REDISPORT'), os.environ.get('REDIS_NUM'),)):
    logging.warning('Redis DB is DEPRECATED!\n'
                    'ALL SUBS IN THE OLD DB WILL NOT BE MIGRATED. '
                    'IF YOU NEED TO BACKUP YOUR SUBS, DOWNGRADE AND USE "/export" COMMAND TO BACKUP.\n\n'
                    'Please remove these env vars (if exist):\n'
                    'REDISHOST\n'
                    'REDISUSER\n'
                    'REDISPASSWORD\n'
                    'REDISPORT\n'
                    'REDIS_NUM')

if os.path.exists('config/rss.db'):
    os.rename('config/rss.db', 'config/rss.db.bak')
    logging.warning('Sqlite DB "rss.db" with old schema is DEPRECATED and renamed to "rss.db.bak" automatically!\n'
                    'ALL SUBS IN THE OLD DB WILL NOT BE MIGRATED. '
                    'IF YOU NEED TO BACKUP YOUR SUBS, DOWNGRADE AND USE "/export" COMMAND TO BACKUP.')

# ----- shared var -----
bot: Optional[TelegramClient] = None  # placeholder
bot_id: Optional[int] = None  # placeholder

REQUESTS_HEADERS: Final = {
    'user-agent': os.environ.get('USER_AGENT', 'RSStT')
}
