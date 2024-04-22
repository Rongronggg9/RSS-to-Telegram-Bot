#!/usr/bin/env python3

from typing import Final

from pathlib import Path

DB_PKG_DIR: Final[Path] = Path(__file__).parent.parent / 'src' / 'db'

MIGRATE_TEMPLATE: Final[str] = """from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return \"\"\"
        {upgrade_sql}\"\"\"


async def downgrade(db: BaseDBAsyncClient) -> str:
    return \"\"\"
        {downgrade_sql}\"\"\"
"""

for migrations_dir in [DB_PKG_DIR / 'migrations_sqlite', DB_PKG_DIR / 'migrations_pgsql']:
    for sql_migration in migrations_dir.glob('**/*.sql'):
        sql = sql_migration.read_text()
        upgrade_sql, _, downgrade_sql = sql.partition('-- upgrade --')[2].partition('-- downgrade --')
        py_migration = sql_migration.with_suffix('.py')
        py_migration.write_text(
            MIGRATE_TEMPLATE.format(
                upgrade_sql=upgrade_sql.strip(),
                downgrade_sql=downgrade_sql.strip(),
            ),
            newline='\n',
        )
