from __future__ import annotations

from tortoise import Tortoise
from aerich import Command
from os import path

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


async def init():
    if env.DATABASE_URL.startswith('sqlite'):
        aerich_command = Command(tortoise_config=config.TORTOISE_ORM,
                                 location=path.join(path.dirname(__file__), 'migrations_sqlite'))
    elif env.DATABASE_URL.startswith('postgres'):
        aerich_command = Command(tortoise_config=config.TORTOISE_ORM,
                                 location=path.join(path.dirname(__file__), 'migrations_pgsql'))
    else:
        aerich_command = None
        logger.critical('INVALID DB SCHEME! ONLY "sqlite" AND "postgres" ARE SUPPORTED!')
        exit(1)
    await aerich_command.init()
    await aerich_command.upgrade()
    # await Tortoise.init(config=config.TORTOISE_ORM)
    await effective_utils.init()
    logger.info('Successfully connected to the DB')


async def close():
    await Tortoise.close_connections()
