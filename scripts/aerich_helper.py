#!/usr/bin/env python3

#  RSS to Telegram Bot
#  Copyright (C) 2024  Rongrong <i@rong.moe>
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

from typing import Final, ClassVar, Callable, Awaitable

import aerich
import argparse
import importlib.util
import inspect
import logging
import sys
from enum import Enum
from pathlib import Path
from tortoise import run_async

SELF_DIR: Final[Path] = Path(__file__).parent
PROJECT_ROOT: Final[Path] = SELF_DIR.parent
CONFIG_DIR: Final[Path] = PROJECT_ROOT / 'config'
DB_PKG_DIR: Final[Path] = PROJECT_ROOT / 'src' / 'db'

# import only models.py, without importing the db package
_models_module_name: Final[str] = 'models'
_models_path: Final[Path] = DB_PKG_DIR / f'{_models_module_name}.py'
_module_spec = importlib.util.spec_from_file_location(_models_module_name, _models_path)
models = importlib.util.module_from_spec(_module_spec)
sys.modules[_models_module_name] = models
_module_spec.loader.exec_module(models)


def bool_helper(value: str) -> bool:
    try:
        return int(value) != 0
    except ValueError:
        return value.lower() not in {'', 'false', 'no', 'n'}


class DBType(Enum):
    SQLITE = 'sqlite'
    PGSQL = 'postgres'


class MigrationHelper:
    DEFAULT_DB_URL: ClassVar[str] = f'{DBType.SQLITE.value}://{CONFIG_DIR.as_posix()}/db.sqlite3'
    MIGRATION_DIR: ClassVar[dict[DBType, str]] = {
        DBType.SQLITE: str(DB_PKG_DIR / 'migrations_sqlite'),
        DBType.PGSQL: str(DB_PKG_DIR / 'migrations_pgsql')
    }

    commands_registered: Final[dict[str, Callable]] = dict(
        upgrade=aerich.Command.upgrade,
        downgrade=aerich.Command.downgrade,
        heads=aerich.Command.heads,
        history=aerich.Command.history,
        # inspectdb=aerich.Command.inspectdb,
        migrate=aerich.Command.migrate,
        init_db=aerich.Command.init_db,  # USE WITH CAUTION
    )

    @classmethod
    def register_sub_parser(cls, arg_parser: argparse.ArgumentParser):
        sub_parsers = arg_parser.add_subparsers(dest='command', required=True)
        for command, func in cls.commands_registered.items():
            command_arguments: list[dict] = []
            for param in inspect.signature(func).parameters.values():
                if param.name == 'self':
                    continue
                param_type = param.annotation
                param_type_helper = param_type
                if param_type is bool:
                    param_type_helper = bool_helper
                elif param_type not in {str, int, float}:
                    raise ValueError(f'Unsupported type: {param.annotation}')
                if param.default is inspect.Parameter.empty:
                    command_arguments.append(dict(
                        name=param.name,
                        type=param_type_helper,
                        help=f'{param_type.__name__}',
                    ))
                else:
                    command_arguments.append(dict(
                        name=param.name,
                        type=param_type_helper,
                        default=param.default,
                        nargs='?',
                        help=f'{param_type.__name__}, default: {param.default}',
                    ))
            sub_parser = sub_parsers.add_parser(
                command,
                help=(
                        'Parameters: '
                        + (
                            ', '.join(f'{param["name"]} ({param["help"]})' for param in command_arguments)
                            if command_arguments
                            else '-'
                        )
                )
            )
            for param in command_arguments:
                param_name = param.pop('name')
                sub_parser.add_argument(param_name, **param)

    @staticmethod
    def generate_tortoise_orm_config(db_url: str) -> dict:
        return {
            "connections": {"default": db_url},
            "apps": {
                "models": {
                    "models": ["aerich.models", models],
                    "default_connection": "default"
                },
            },
        }

    def __init__(self, db_url: str):
        db_type = DBType(db_url.partition('://')[0])
        self.aerich_cmd = aerich.Command(
            tortoise_config=self.generate_tortoise_orm_config(db_url),
            location=self.MIGRATION_DIR[db_type],
        )
        self.aerich_initialized = False

    async def init(self):
        if not self.aerich_initialized:
            await self.aerich_cmd.init()
            self.aerich_initialized = True

    async def exec_command(self, command: str, *args, **kwargs):
        if command not in self.commands_registered:
            raise ValueError(f'Command {command} not registered.')
        if not self.aerich_initialized:
            await self.init()
            logging.info('Aerich initialized')
        logging.info(f'Executing command {command} with args: {args}, kwargs: {kwargs}')
        maybe_coro = await self.commands_registered[command](self.aerich_cmd, *args, **kwargs)
        if isinstance(maybe_coro, Awaitable):
            result = await maybe_coro
        else:
            result = maybe_coro
        logging.info(f'Command "{command}" executed with result:\n{result}')


def main():
    parser = argparse.ArgumentParser(
        description='Aerich helper script\n\n',
        epilog=(
            'To create a new migration:\n'
            '  1. Create a new branch <foo> and make your changes there.\n'
            '  2. Switch to the "dev" branch.\n'
            '  3. Create a temporary database for the migration.\n'
            '  4. Execute "aerich_helper.py --db-url <temp_db_url> upgrade True" to set up the temporary database.\n'
            '  5. Switch back to the <foo> branch.\n'
            '  6. Execute "aerich_helper.py --db-url <temp_db_url> migrate" to create the migration.\n'
            '  7. Now you can safely delete the temporary database.\n'
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging',
    )
    parser.add_argument(
        '--db-url', '-u',
        type=str,
        default=MigrationHelper.DEFAULT_DB_URL,
        help=(
            f'Database URL, default to {MigrationHelper.DEFAULT_DB_URL}\n'
            f'Examples:\n'
            f'  {DBType.SQLITE.value}://path/to/db.sqlite3\n'
            f'  {DBType.PGSQL.value}://<user>:<password>@<host>:<port>/<dbname>\n'
        ),
    )
    MigrationHelper.register_sub_parser(parser)
    args = parser.parse_args()
    args_d = vars(args)
    logging.basicConfig(level=logging.DEBUG if args_d.pop('verbose') else logging.INFO)
    migration_helper = MigrationHelper(args_d.pop('db_url'))
    run_async(migration_helper.exec_command(**args_d))


if __name__ == '__main__':
    main()
