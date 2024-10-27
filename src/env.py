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
from typing import Optional, Union
from typing_extensions import Final

import asyncio
import yarl
import os
import sys
import colorlog
import re
import argparse
from contextlib import suppress
from telethon import TelegramClient
from telethon.tl.types import User, InputPeerUser
from python_socks import parse_proxy_url
from dotenv import load_dotenv
from pathlib import Path
from functools import partial

from .version import __version__


# ----- utils -----
def __bool_parser(var: Optional[str], default_value: bool = False) -> bool:
    if not var:
        return default_value

    if var.isdecimal() or var.lstrip('-').isdecimal():
        return int(var) > 0

    var = var.upper()
    if var in ('FALSE', 'NONE', 'NULL', 'NO', 'NOT', 'DISABLE', 'DISABLED', 'INACTIVE', 'DEACTIVATED', 'OFF'):
        return False
    if var in ('TRUE', 'YES', 'OK', 'ENABLE', 'ENABLED', 'ACTIVE', 'ACTIVATED', 'ON'):
        return True
    return default_value


def __list_parser(var: Optional[str]) -> list[str]:
    return re.split(r'[\s,;，；]+', var.strip()) if var else []


def __decompose_version(version: str) -> list[Union[int, str]]:
    def buf_put(as_int: bool):
        nonlocal buf
        if not buf:
            raise ValueError(f'Empty part in version string: {version}')
        parts.append(int(buf) if as_int else buf)
        buf = ''

    parts = []
    buf = ''
    for i, char in enumerate(version):
        if char == '.':
            buf_put(as_int=True)
            continue
        if not char.isdecimal():
            buf_put(as_int=True)
            parts.append(version[i:])
            break
        buf += char
    if buf:
        buf_put(as_int=True)
    return parts


def __compare_version(version1: str, version2: str) -> tuple[int, list[Union[int, str]], list[Union[int, str]]]:
    """loose comparison, only compare the numeric parts"""
    parts1 = __decompose_version(version1)
    parts2 = __decompose_version(version2)

    if not parts1:
        return -1, parts1, parts2
    if not parts2:
        return 1, parts1, parts2

    marker = 0
    for part1, part2 in zip(parts1, parts2):
        if part1 == part2:
            continue
        part1_is_int = isinstance(part1, int)
        part2_is_int = isinstance(part2, int)
        if part1_is_int and part2_is_int:
            marker = 1 if part1 > part2 else -1
        elif part1_is_int and part1 > 0:
            marker = 1
        elif part2_is_int and part2 > 0:
            marker = -1
        break
    return marker, parts1, parts2


# ----- setup logging -----
__configure_logging = partial(
    colorlog.basicConfig,
    format='%(log_color)s%(asctime)s:%(levelname)s:%(name)s - %(message)s',
    datefmt='%Y-%m-%d-%H:%M:%S'
)
__configure_logging(level=colorlog.DEBUG if __bool_parser(os.environ.get('DEBUG')) else colorlog.INFO)
logger = colorlog.getLogger('RSStT.env')

# ----- determine the environment -----
user_home = os.path.expanduser('~')
self_path = os.path.dirname(__file__)
self_module_name = os.path.basename(self_path)
cli_entry = sys.argv[0]  # expect `-m` or `/path/to/telegramRSSbot.py`
is_self_run_as_a_whole_package = cli_entry.endswith('telegramRSSbot.py')

__arg_parser = argparse.ArgumentParser(
    prog=cli_entry if cli_entry != '-m' else f'python3 -m {self_module_name}',
    description='RSS to Telegram Bot, a Telegram RSS bot that cares about your reading experience.')
__arg_parser.add_argument('-c', '--config', metavar='/path/to/config/folder', type=str, nargs=1,
                          help='path to the config folder')
__arg_parser.add_argument('--dummy', type=str, action='append', nargs=1,
                          help='dummy argument, can be repeated for multiple times. '
                               'Useful to distinguish multiple bot instances on the same host with command line')
cli_args = __arg_parser.parse_args()
custom_config_path = cli_args.config[0] if cli_args.config else None

if custom_config_path:
    config_folder_path = os.path.normpath(os.path.abspath(custom_config_path))
elif is_self_run_as_a_whole_package:
    config_folder_path = os.path.normpath(os.path.join(self_path, '..', 'config'))
else:
    config_folder_path = os.path.join(user_home, '.rsstt')

Path(config_folder_path).mkdir(parents=True, exist_ok=True)
logger.info(f'Config folder: {config_folder_path}')

# ----- load .env -----
dot_env_paths = (os.path.join(config_folder_path, '.env'),
                 os.path.join(os.path.abspath('.'), '.env'))
if is_self_run_as_a_whole_package:
    dot_env_paths = (os.path.normpath(os.path.join(self_path, '..', '.env')),) + dot_env_paths
for dot_env_path in dict.fromkeys(dot_env_paths):  # remove duplicates while keeping the order
    if os.path.isfile(dot_env_path):
        load_dotenv(dot_env_path, override=True)
        logger.info(f'Found .env file at "{dot_env_path}", loaded')


# ----- get version -----
def __get_version():
    version = 'dirty'
    if is_self_run_as_a_whole_package:
        # noinspection PyBroadException
        try:
            with open(os.path.normpath(os.path.join(self_path, '..', '.version')), 'r') as v:
                version = v.read().strip()
        except Exception:
            version = 'dirty'

        if not version or version == '@':
            version = 'dirty'

    if version == 'dirty':
        import subprocess

        with suppress(Exception):
            # vMAJ.MIN.PAT-N-gHASH[-(broken|dirty)][@BRANCH]
            version = '@'.join(
                subprocess.run(
                    args,
                    cwd=self_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    check=True,
                    timeout=3,
                ).stdout.strip()
                for args in (
                    ['git', 'describe', '--tags', '--long', '--dirty', '--broken', '--always'],
                    ['git', 'branch', '--show-current'],
                )
            )

    try:
        sign, version_decomposed, version_pkg_decomposed = __compare_version(version.lstrip('v'), __version__)
        if sign <= -1:  # outdated version: older than pkg ver
            version = __version__
            if isinstance(version_decomposed[-1], str) and not isinstance(version_pkg_decomposed[-1], str):
                # -N-gHASH[-(broken|dirty)][@BRANCH]
                # ^^
                version += re.sub(r'^-\d+(?=-)', '', version_decomposed[-1])  # trim the marked part
            version = f'v{version}'
    except (TypeError, ValueError):
        version = f'v{__version__}'

    # empty guard
    if not version:
        version = 'dirty'

    return version


VERSION: Final = __get_version()

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
    _manager = tuple(map(int, __list_parser(os.environ.get('MANAGER') or os.environ.get('CHATID'))))
    MANAGER: Final = set(_manager)  # optimize membership test

    if not all((TOKEN, MANAGER)):
        logger.critical('"TOKEN" OR "MANAGER" NOT SET! PLEASE CHECK YOUR SETTINGS!')
        exit(1)
except Exception as e:
    logger.critical('INVALID "MANAGER"! PLEASE CHECK YOUR SETTINGS!', exc_info=e)
    exit(1)

_error_logging_chat = os.environ.get('ERROR_LOGGING_CHAT')
ERROR_LOGGING_CHAT: Final = int(_error_logging_chat) if _error_logging_chat else _manager[0]
del _error_logging_chat
del _manager

MANAGER_PRIVILEGED: Final = __bool_parser(os.environ.get('MANAGER_PRIVILEGED'))

TELEGRAPH_TOKEN: Final = __list_parser(os.environ.get('TELEGRAPH_TOKEN'))

MULTIUSER: Final = __bool_parser(os.environ.get('MULTIUSER'), default_value=True)

CRON_SECOND: Final = int(os.environ.get('CRON_SECOND') or 0) % 60

# ----- network config -----
DEFAULT_PROXY: Final = os.environ.get('SOCKS_PROXY') or os.environ.get('socks_proxy') \
                       or os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy') \
                       or os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')

TELEGRAM_PROXY: Final = os.environ.get('T_PROXY') or DEFAULT_PROXY
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

R_PROXY: Final = os.environ.get('R_PROXY') or DEFAULT_PROXY

REQUESTS_PROXIES: Final = {'all': R_PROXY} if R_PROXY else {}

PROXY_BYPASS_PRIVATE: Final = __bool_parser(os.environ.get('PROXY_BYPASS_PRIVATE'))
PROXY_BYPASS_DOMAINS: Final = __list_parser(os.environ.get('PROXY_BYPASS_DOMAINS'))
USER_AGENT: Final = os.environ.get('USER_AGENT') or f'RSStT/{__version__} RSS Reader (+https://git.io/RSStT)'
IPV6_PRIOR: Final = __bool_parser(os.environ.get('IPV6_PRIOR'))
VERIFY_TLS: Final = __bool_parser(os.environ.get('VERIFY_TLS'), default_value=True)

HTTP_TIMEOUT: Final = int(os.environ.get('HTTP_TIMEOUT') or 12)
HTTP_CONCURRENCY: Final = int(os.environ.get('HTTP_CONCURRENCY') or 1024)
HTTP_CONCURRENCY_PER_HOST: Final = int(os.environ.get('HTTP_CONCURRENCY_PER_HOST') or 16)

# ----- img relay server config -----
_img_relay_server = os.environ.get('IMG_RELAY_SERVER') or 'https://rsstt-img-relay.rongrong.workers.dev/'
IMG_RELAY_SERVER: Final = (
        ('' if _img_relay_server.startswith('http') else 'https://')
        + _img_relay_server
        + ('' if _img_relay_server.endswith(('/', '=')) else '/')
)
del _img_relay_server

# ----- wsrv.nl config -----
_images_weserv_nl = os.environ.get('IMAGES_WESERV_NL') or 'https://wsrv.nl/'
IMAGES_WESERV_NL: Final = (
        ('' if _images_weserv_nl.startswith('http') else 'https://')
        + _images_weserv_nl
        + ('' if _images_weserv_nl.endswith('/') else '/')
)
del _images_weserv_nl


# ----- db config -----
def __get_database_url() -> str:
    # Railway.app provides DATABASE_PRIVATE_URL, DATABASE_URL and/or DATABASE_PUBLIC_URL.
    # DATABASE_PRIVATE_URL is for private networking, while DATABASE_PUBLIC_URL is for public networking.
    # If private networking is disabled, the former still exists but is invalid (i.e., missing host).
    # If public networking is disabled, both host and port are missing in the latter, resulting in an invalid URL too.
    # A legacy Postgres addon may provide only DATABASE_URL (for PUBLIC networking) and DATABASE_PRIVATE_URL,
    # while a modern one may provide only DATABASE_URL (for PRIVATE networking) and DATABASE_PUBLIC_URL.
    # Thus, we need to select a valid one from them.
    urls: tuple[str, ...] = tuple(filter(None, map(os.environ.get, (
        'DATABASE_URL',  # Generic, Railway.app compatible
        'DATABASE_PRIVATE_URL',  # Railway.app specific
        'DATABASE_PUBLIC_URL',  # Railway.app specific
    ))))
    if not urls:
        return f'sqlite:{config_folder_path}/db.sqlite3'
    err: Optional[BaseException] = None
    for url in urls:
        try:
            y_url = yarl.URL(url)
        except ValueError as _err:
            err = _err
        else:
            return str(
                # Tortoise-ORM does not recognize 'postgresql' scheme
                y_url.with_scheme('postgres')
                if y_url.scheme == 'postgresql'
                else y_url
            )
    else:
        logger.critical('INVALID DATABASE URL!', exc_info=err)


DATABASE_URL: Final = __get_database_url()

# ----- misc config -----
TABLE_TO_IMAGE: Final = __bool_parser(os.environ.get('TABLE_TO_IMAGE'))
TRAFFIC_SAVING: Final = __bool_parser(os.environ.get('TRAFFIC_SAVING'))
LAZY_MEDIA_VALIDATION: Final = __bool_parser(os.environ.get('LAZY_MEDIA_VALIDATION'))
NO_UVLOOP: Final = __bool_parser(os.environ.get('NO_UVLOOP'))
MULTIPROCESSING: Final = __bool_parser(os.environ.get('MULTIPROCESSING'))
EXECUTOR_NICENESS_INCREMENT: Final = int(os.environ.get('EXECUTOR_NICENESS_INCREMENT') or (2 * hasattr(os, 'nice')))
DEBUG: Final = __bool_parser(os.environ.get('DEBUG'))
__configure_logging(  # config twice to make .env file work
    level=colorlog.DEBUG if DEBUG else colorlog.INFO,
    force=True
)
if DEBUG:
    logger.debug('DEBUG mode enabled')

# ----- environment config -----
RAILWAY_STATIC_URL: Final = os.environ.get('RAILWAY_STATIC_URL')
PORT: Final = int(os.environ.get('PORT', 0)) or (8080 if RAILWAY_STATIC_URL else None)

# !!!!! DEPRECATED WARNING !!!!!
if os.environ.get('DELAY'):
    logger.warning('Env var "DELAY" is DEPRECATED and of no use!\n'
                   'To avoid this warning, remove this env var.')

if os.environ.get('CHATID'):
    logger.warning('Env var "CHATID" is DEPRECATED!\n'
                   'To avoid this warning, remove this env var.')

if any((os.environ.get('REDISHOST'), os.environ.get('REDISUSER'), os.environ.get('REDISPASSWORD'),
        os.environ.get('REDISPORT'), os.environ.get('REDIS_NUM'),)):
    logger.warning('Redis DB is DEPRECATED!\n'
                   'ALL SUBS IN THE OLD DB WILL NOT BE MIGRATED. '
                   'IF YOU NEED TO BACKUP YOUR SUBS, DOWNGRADE AND USE "/export" COMMAND TO BACKUP.\n\n'
                   'Please remove these env vars (if exist):\n'
                   'REDISHOST\n'
                   'REDISUSER\n'
                   'REDISPASSWORD\n'
                   'REDISPORT\n'
                   'REDIS_NUM')

if is_self_run_as_a_whole_package and os.path.exists(os.path.join(config_folder_path, 'rss.db')):
    os.rename(os.path.join(config_folder_path, 'rss.db'), os.path.join(config_folder_path, 'rss.db.bak'))
    logger.warning('Sqlite DB "rss.db" with old schema is DEPRECATED and renamed to "rss.db.bak" automatically!\n'
                   'ALL SUBS IN THE OLD DB WILL NOT BE MIGRATED. '
                   'IF YOU NEED TO BACKUP YOUR SUBS, DOWNGRADE AND USE "/export" COMMAND TO BACKUP.')

# ----- shared var -----
bot: Optional[TelegramClient] = None  # placeholder
bot_id: Optional[int] = None  # placeholder
bot_peer: Optional[User] = None  # placeholder
bot_input_peer: Optional[InputPeerUser] = None  # placeholder

# ----- loop initialization -----
uvloop_enabled = False
if not NO_UVLOOP:
    try:
        import uvloop

        uvloop.install()
        uvloop_enabled = True
    except ImportError:  # not installed (e.g. Windows)
        uvloop = None
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
