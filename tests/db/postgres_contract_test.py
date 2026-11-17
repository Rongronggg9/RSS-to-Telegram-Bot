from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from tortoise.exceptions import IntegrityError
from yarl import URL

from tests.support.migration_runner import run_migration_child

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_DUMP = (
    _REPOSITORY_ROOT / "tests/fixtures/migrations/postgres-aerich-0.6.sql"
)
_EXPECTED_REVISIONS = [
    "0_20211117110249_init.py",
    "1_20211130051128_update.py",
    "2_20220306045951_update.py",
    "3_20220415030554_update.py",
    "4_20240425020849_display_entry_tags.py",
]


def _dsn_for_database(dsn: str, database: str) -> str:
    parsed = URL(dsn)
    return str(parsed.with_path(f"/{database}").with_query(parsed.query))


@pytest.mark.postgres
async def test_postgres_current_schema_enforces_subscription_unique_and_cascade(
    postgres_dsn: str,
) -> None:
    from src import db

    user_id = 9101
    feed_id = 9201
    await db.Sub.filter(user_id=user_id).delete()
    await db.Feed.filter(id=feed_id).delete()
    await db.User.filter(id=user_id).delete()
    try:
        user = await db.User.create(
            id=user_id,
            state=1,
            lang="en",
            admin=9001,
            sub_limit=37,
            interval=19,
            notify=0,
            send_mode=2,
            length_limit=777,
            link_preview=1,
            display_author=1,
            display_via=-1,
            display_title=1,
            display_entry_tags=1,
            style=1,
            display_media=-1,
        )
        feed = await db.Feed.create(
            id=feed_id,
            state=1,
            link="https://postgres-schema.example.test/feed",
            title="PostgreSQL schema fixture",
            interval=17,
            entry_hashes=[10101, 20202],
            etag="postgres-schema-etag",
            last_modified=datetime(2024, 4, 25, 2, 8, 49, tzinfo=timezone.utc),
            error_count=7,
            next_check_time=datetime(2024, 4, 26, 2, 8, 49, tzinfo=timezone.utc),
        )
        await db.Sub.create(
            id=9301,
            state=1,
            user=user,
            feed=feed,
            title="PostgreSQL subscription",
            tags="postgres,schema",
            interval=23,
            notify=0,
            send_mode=2,
            length_limit=511,
            link_preview=1,
            display_author=1,
            display_via=-1,
            display_title=1,
            display_entry_tags=1,
            style=1,
            display_media=-1,
        )

        with pytest.raises(IntegrityError):
            await db.Sub.create(
                id=9302,
                state=0,
                user=user,
                feed=feed,
                title="Duplicate PostgreSQL subscription",
                tags="duplicate",
                interval=29,
                notify=0,
                send_mode=-1,
                length_limit=333,
                link_preview=1,
                display_author=-1,
                display_via=-2,
                display_title=-1,
                display_entry_tags=0,
                style=1,
                display_media=-1,
            )

        await user.delete()

        assert not await db.Sub.filter(id=9301).exists()
        assert await db.Feed.filter(id=feed_id).exists()
    finally:
        await db.Sub.filter(user_id=user_id).delete()
        await db.Feed.filter(id=feed_id).delete()
        await db.User.filter(id=user_id).delete()


async def _inspect_migrated_postgres(database_dsn: str) -> None:
    connection = await asyncpg.connect(database_dsn)
    try:
        user = await connection.fetchrow(
            'SELECT id, created_at, updated_at, state, lang, admin, sub_limit, '
            'interval, notify, send_mode, length_limit, link_preview, display_author, '
            'display_via, display_title, style, display_media, display_entry_tags '
            'FROM "user" WHERE id = 101'
        )
        feed = await connection.fetchrow(
            'SELECT id, created_at, updated_at, state, link, title, interval, '
            'entry_hashes, etag, last_modified, error_count, next_check_time '
            'FROM "feed" WHERE id = 201'
        )
        subscription = await connection.fetchrow(
            'SELECT id, created_at, updated_at, state, user_id, feed_id, title, tags, '
            'interval, notify, send_mode, length_limit, link_preview, display_author, '
            'display_via, display_title, style, display_media, display_entry_tags '
            'FROM "sub" WHERE id = 301'
        )
        option = await connection.fetchrow(
            'SELECT id, created_at, updated_at, key, value FROM "option" WHERE id = 401'
        )
        revisions = await connection.fetch(
            'SELECT version FROM "aerich" WHERE app = $1 ORDER BY id',
            "models",
        )
    finally:
        await connection.close()

    assert tuple(user) == (
        101,
        datetime(2024, 4, 25, 2, 8, 49, tzinfo=timezone.utc),
        datetime(2024, 4, 25, 3, 8, 49, tzinfo=timezone.utc),
        1,
        "en",
        9101,
        42,
        11,
        0,
        2,
        777,
        1,
        1,
        -1,
        1,
        1,
        -1,
        -1,
    )
    assert tuple(feed) == (
        201,
        datetime(2024, 4, 25, 2, 8, 49, tzinfo=timezone.utc),
        datetime(2024, 4, 25, 3, 8, 49, tzinfo=timezone.utc),
        1,
        "https://legacy-user:legacy-pass@legacy.example.test/feed?token=legacy-token",
        "Legacy Fixture Feed",
        17,
        "[111, 222]",
        "legacy-etag",
        datetime(2024, 4, 24, 2, 8, 49, tzinfo=timezone.utc),
        7,
        datetime(2024, 4, 26, 2, 8, 49, tzinfo=timezone.utc),
    )
    assert tuple(subscription) == (
        301,
        datetime(2024, 4, 25, 2, 8, 49, tzinfo=timezone.utc),
        datetime(2024, 4, 25, 3, 8, 49, tzinfo=timezone.utc),
        1,
        101,
        201,
        "Legacy Subscription",
        "legacy,fixture",
        23,
        0,
        2,
        511,
        1,
        1,
        -1,
        1,
        1,
        -1,
        -100,
    )
    assert tuple(option) == (
        401,
        datetime(2024, 4, 25, 2, 8, 49, tzinfo=timezone.utc),
        datetime(2024, 4, 25, 3, 8, 49, tzinfo=timezone.utc),
        "default_interval",
        "29",
    )
    assert [row["version"] for row in revisions] == _EXPECTED_REVISIONS


@pytest.mark.postgres
@pytest.mark.migration
async def test_legacy_postgres_dump_startup_migrates_without_row_changes(
    tmp_path: Path,
    postgres_dsn: str,
) -> None:
    maintenance_dsn = _dsn_for_database(postgres_dsn, "postgres")

    for launch_mode in ("script", "module"):
        database_name = f"rsstt_migration_{uuid4().hex}"
        database_dsn = _dsn_for_database(postgres_dsn, database_name)
        created = False
        try:
            maintenance = await asyncpg.connect(maintenance_dsn)
            try:
                await maintenance.execute(f'CREATE DATABASE "{database_name}"')
                created = True
            finally:
                await maintenance.close()

            connection = await asyncpg.connect(database_dsn)
            try:
                await connection.execute(_LEGACY_DUMP.read_text(encoding="utf-8"))
            finally:
                await connection.close()

            case_dir = tmp_path / launch_mode
            case_dir.mkdir()
            run_migration_child(
                case_dir,
                database_url=database_dsn,
                expected_db_type="postgres",
                launch_mode=launch_mode,
            )
            await _inspect_migrated_postgres(database_dsn)
        finally:
            if created:
                maintenance = await asyncpg.connect(maintenance_dsn)
                try:
                    await maintenance.execute(
                        f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
                    )
                finally:
                    await maintenance.close()
