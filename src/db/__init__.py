#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
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
from typing import Optional, Final

import aerich
import aerich.models
import aerich.version
from enum import Enum
from pathlib import Path
from tortoise import Tortoise
from tortoise.exceptions import OperationalError
from tortoise.transactions import in_transaction

from . import config, models
from .. import env, log
from . import effective_utils

logger = log.getLogger('RSStT.db')

User = models.User
Feed = models.Feed
Sub = models.Sub
Option = models.Option
EffectiveOptions = effective_utils.EffectiveOptions
EffectiveTasks = effective_utils.EffectiveTasks


class DBType(Enum):  # TODO: use StrEnum once the minimum Python requirement is 3.11
    SQLITE = 'sqlite'
    PGSQL = 'postgres'


DB_TYPE: Optional[DBType] = None

__DB_PKG_DIR: Final[Path] = Path(__file__).parent
__MIGRATIONS_DIRS: Final[dict[DBType, Path]] = {
    DBType.SQLITE: __DB_PKG_DIR / 'migrations_sqlite',
    DBType.PGSQL: __DB_PKG_DIR / 'migrations_pgsql',
}
assert all(path.is_dir() for path in __MIGRATIONS_DIRS.values())


async def __upgrade_migrations_in_db():
    aerich_version = aerich.version.__version__
    if int(aerich_version[0]) == 0 and int(aerich_version[2]) < 7:
        logger.critical(f'UNSUPPORTED AERICH VERSION: {aerich_version}, PLEASE UPGRADE TO >=0.7.0')
        exit(1)

    async with in_transaction():
        try:
            outdated_revisions = await aerich.models.Aerich.filter(version__endswith='.sql')
        except OperationalError as e:
            skip_upgrade_msg = 'skipping migration upgrade (probably a fresh DB)'
            err_msg = str(e)
            if 'does not exist' in err_msg or 'no such table' in err_msg:
                logger.info(f'"aerich" table not found, {skip_upgrade_msg}: {err_msg}')
            else:
                logger.warning(f'Failed to fetch "aerich" records, {skip_upgrade_msg}', exc_info=e)
            return
        for revisions in outdated_revisions:
            old_migration_file = __MIGRATIONS_DIRS[DB_TYPE] / revisions.app / revisions.version
            assert old_migration_file.suffix == '.sql'
            new_migration_file = old_migration_file.with_suffix('.py')
            if not new_migration_file.is_file():
                logger.critical(f'MIGRATION FILE NOT FOUND: {new_migration_file}')
                exit(1)
            new_version = new_migration_file.name
            logger.info(f'Upgrading migration: {revisions.app}/{revisions.version} -> {revisions.app}/{new_version}')
            revisions.version = new_version
            await revisions.save(update_fields=['version'])


async def init():
    global DB_TYPE
    try:
        DB_TYPE = DBType(env.DATABASE_URL.partition(':')[0])
    except ValueError:
        logger.critical(f'INVALID DB SCHEME (EXPECTED: {", ".join(t.value for t in DBType)}): {env.DATABASE_URL}')
        exit(1)
    aerich_command = aerich.Command(
        tortoise_config=config.TORTOISE_ORM,
        location=str(__MIGRATIONS_DIRS[DB_TYPE]),
    )

    # await Tortoise.init(config=config.TORTOISE_ORM)
    await aerich_command.init()
    await __upgrade_migrations_in_db()
    try:
        if applied_migrations := await aerich_command.upgrade(run_in_transaction=True):
            logger.info(f'Applied migrations due to DB schema changes: {", ".join(applied_migrations)}')
    except Exception as e:
        logger.critical('FAILED TO APPLY MIGRATIONS', exc_info=e)
        try:
            if migrations_to_apply := await aerich_command.heads():
                logger.critical(f'UNAPPPLIED MIGRATIONS: {", ".join(migrations_to_apply)}')
        except Exception as e:
            logger.error('Failed to fetch unapplied migrations', exc_info=e)
        exit(1)
    await effective_utils.init()
    logger.info('Successfully connected to the DB')


async def close():
    await Tortoise.close_connections()
