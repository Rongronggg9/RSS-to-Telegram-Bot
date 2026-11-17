from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from yarl import URL

from tests.support.env_probe import ISOLATED_ENV_KEYS
from tests.support.http import local_feed_server
from tests.support.telegram import recording_telegram

_ORIGINAL_CWD: Path
_ORIGINAL_ARGV: list[str]
_ORIGINAL_ENV: dict[str, str]
_TEST_ROOT: Path
_IMPORT_TIME_LOOP: asyncio.AbstractEventLoop | None = None


def _canonical_postgres_dsn(value: str) -> str:
    try:
        parsed = URL(value)
        valid = (
            parsed.is_absolute()
            and parsed.scheme in {"postgres", "postgresql"}
            and parsed.host is not None
        )
    except ValueError:
        valid = False
    if not valid:
        raise pytest.UsageError(
            "TEST_POSTGRES_DSN must be an absolute postgres:// or postgresql:// URL with a host"
        )
    return str(parsed.with_scheme("postgres"))


def _selected_postgres_dsn() -> str | None:
    value = os.environ.get("TEST_POSTGRES_DSN")
    return _canonical_postgres_dsn(value) if value else None


def pytest_sessionstart(session: pytest.Session) -> None:
    global _ORIGINAL_CWD, _ORIGINAL_ARGV, _ORIGINAL_ENV, _TEST_ROOT
    _ORIGINAL_CWD = Path.cwd()
    _ORIGINAL_ARGV = list(sys.argv)
    _ORIGINAL_ENV = dict(os.environ)
    postgres_dsn = _selected_postgres_dsn()
    for key in ISOLATED_ENV_KEYS:
        os.environ.pop(key, None)
    if postgres_dsn:
        os.environ["TEST_POSTGRES_DSN"] = postgres_dsn
    _TEST_ROOT = Path(tempfile.mkdtemp(prefix="rsstt-pytest-"))
    database_url = postgres_dsn or (
        f"sqlite:{(_TEST_ROOT / 'db.sqlite3').resolve()}"
    )
    (_TEST_ROOT / ".env").write_text(
        "\n".join(
            (
                "TOKEN=test",
                "MANAGER=-1",
                "NO_UVLOOP=1",
                "MULTIPROCESSING=0",
                "DEBUG=0",
                "HTTP_CONCURRENCY=4",
                "HTTP_CONCURRENCY_PER_HOST=4",
                f"DATABASE_URL={database_url}",
                "DATABASE_PRIVATE_URL=",
                "DATABASE_PUBLIC_URL=",
                "SOCKS_PROXY=",
                "socks_proxy=",
                "HTTP_PROXY=",
                "http_proxy=",
                "HTTPS_PROXY=",
                "https_proxy=",
                "ALL_PROXY=",
                "all_proxy=",
                "R_PROXY=",
                "T_PROXY=",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    os.chdir(_TEST_ROOT)
    sys.argv[:] = [_ORIGINAL_ARGV[0], "--config", str(_TEST_ROOT)]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    os.chdir(_ORIGINAL_CWD)
    sys.argv[:] = _ORIGINAL_ARGV
    os.environ.clear()
    os.environ.update(_ORIGINAL_ENV)
    shutil.rmtree(_TEST_ROOT)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("TEST_POSTGRES_DSN"):
        return
    skip = pytest.mark.skip(reason="TEST_POSTGRES_DSN is not set")
    for item in items:
        if item.get_closest_marker("postgres") is not None:
            item.add_marker(skip)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def initialized_runtime() -> AsyncIterator[None]:
    global _IMPORT_TIME_LOOP
    from src import db, env
    from src.helpers.bg import bg
    from src.monitor import Monitor

    running_loop = asyncio.get_running_loop()
    _IMPORT_TIME_LOOP = env.loop
    if _IMPORT_TIME_LOOP is not running_loop and not _IMPORT_TIME_LOOP.is_running():
        _IMPORT_TIME_LOOP.close()
    env.loop = running_loop
    asyncio.set_event_loop(running_loop)
    await bg.init(loop=running_loop)
    await db.init()
    expected_postgres = _selected_postgres_dsn()
    if expected_postgres is None:
        assert db.DB_TYPE is db.DBType.SQLITE
    else:
        assert env.DATABASE_URL == expected_postgres
        assert db.DB_TYPE is db.DBType.PGSQL
    try:
        yield
    finally:
        await bg.close()
        await db.close()


@pytest_asyncio.fixture(autouse=True)
async def enforce_selected_backend(
    request: pytest.FixtureRequest,
    initialized_runtime: None,
) -> None:
    from src import db, env

    if request.node.get_closest_marker("postgres") is not None:
        expected = _selected_postgres_dsn()
        assert expected is not None
        assert env.DATABASE_URL == expected
        assert db.DB_TYPE is db.DBType.PGSQL


@pytest_asyncio.fixture
async def sqlite_state() -> AsyncIterator[None]:
    from src import db

    for model in (db.Sub, db.Feed, db.User, db.Option):
        await model.all().delete()
    await db.EffectiveOptions.cache()
    await db.EffectiveTasks.init(flush=True)
    try:
        yield
    finally:
        for model in (db.Sub, db.Feed, db.User, db.Option):
            await model.all().delete()
        await db.EffectiveOptions.cache()
        await db.EffectiveTasks.init(flush=True)


@pytest.fixture
def postgres_dsn(request: pytest.FixtureRequest) -> str:
    value = _selected_postgres_dsn()
    if request.node.get_closest_marker("postgres") is None or value is None:
        pytest.fail("postgres_dsn requires a postgres-marked test and TEST_POSTGRES_DSN")
    from src import db, env

    assert env.DATABASE_URL == value
    assert db.DB_TYPE is db.DBType.PGSQL
    return value


__all__ = (
    "initialized_runtime",
    "local_feed_server",
    "postgres_dsn",
    "recording_telegram",
    "sqlite_state",
)
