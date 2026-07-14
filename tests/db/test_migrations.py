from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.support.migration_runner import run_migration_child

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _REPOSITORY_ROOT / "tests/fixtures/migrations/sqlite-aerich-0.6.db"

_EXPECTED_REVISIONS = [
    "0_20211117110249_init.py",
    "1_20211130051128_update.py",
    "2_20220306045951_update.py",
    "3_20220415025716_update.py",
    "4_20240425020849_display_entry_tags.py",
]




def _inspect_migrated_sqlite(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        user = connection.execute(
            'SELECT id, created_at, updated_at, state, lang, admin, sub_limit, '
            'interval, notify, send_mode, length_limit, link_preview, display_author, '
            'display_via, display_title, style, display_media, display_entry_tags '
            'FROM "user" WHERE id = 101'
        ).fetchone()
        feed = connection.execute(
            'SELECT id, created_at, updated_at, state, link, title, interval, '
            'entry_hashes, etag, last_modified, error_count, next_check_time '
            'FROM "feed" WHERE id = 201'
        ).fetchone()
        subscription = connection.execute(
            'SELECT id, created_at, updated_at, state, user_id, feed_id, title, tags, '
            'interval, notify, send_mode, length_limit, link_preview, display_author, '
            'display_via, display_title, style, display_media, display_entry_tags '
            'FROM "sub" WHERE id = 301'
        ).fetchone()
        option = connection.execute(
            'SELECT id, created_at, updated_at, key, value FROM "option" WHERE id = 401'
        ).fetchone()
        revisions = [
            row[0]
            for row in connection.execute(
                'SELECT version FROM "aerich" WHERE app = ? ORDER BY id',
                ("models",),
            )
        ]

    assert user == (
        101,
        "2024-04-25 02:08:49+00:00",
        "2024-04-25 03:08:49+00:00",
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
    assert feed == (
        201,
        "2024-04-25 02:08:49+00:00",
        "2024-04-25 03:08:49+00:00",
        1,
        "https://legacy-user:legacy-pass@legacy.example.test/feed?token=legacy-token",
        "Legacy Fixture Feed",
        17,
        "[111, 222]",
        "legacy-etag",
        "2024-04-24 02:08:49+00:00",
        7,
        "2024-04-26 02:08:49+00:00",
    )
    assert subscription == (
        301,
        "2024-04-25 02:08:49+00:00",
        "2024-04-25 03:08:49+00:00",
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
    assert option == (
        401,
        "2024-04-25 02:08:49+00:00",
        "2024-04-25 03:08:49+00:00",
        "default_interval",
        "29",
    )
    assert revisions == _EXPECTED_REVISIONS


@pytest.mark.migration
@pytest.mark.sqlite
@pytest.mark.parametrize("launch_mode", ("script", "module"))
def test_legacy_sqlite_startup_migrates_sql_aerich_revisions_without_row_changes(
    tmp_path: Path,
    launch_mode: str,
) -> None:
    case_dir = tmp_path / launch_mode
    case_dir.mkdir()
    database_path = case_dir / "legacy.sqlite3"
    shutil.copyfile(_FIXTURE, database_path)
    database_url = "sqlite://legacy.sqlite3"

    run_migration_child(
        case_dir,
        database_url=database_url,
        expected_db_type="sqlite",
        launch_mode=launch_mode,
    )

    _inspect_migrated_sqlite(database_path)
