from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from tests.support.env_probe import ISOLATED_ENV_KEYS

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _write_case_environment(case_dir: Path, database_url: str) -> None:
    (case_dir / ".env").write_text(
        "\n".join(
            (
                "TOKEN=test",
                "MANAGER=-1",
                "NO_UVLOOP=1",
                "MULTIPROCESSING=0",
                "DEBUG=0",
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


def run_migration_child(
    case_dir: Path,
    *,
    database_url: str,
    expected_db_type: str,
    launch_mode: str,
) -> None:
    _write_case_environment(case_dir, database_url)
    child_environment = dict(os.environ)
    for key in (*ISOLATED_ENV_KEYS, "TEST_POSTGRES_DSN"):
        child_environment.pop(key, None)
    child_environment.update(
        {
            "PYTHONPATH": str(_REPOSITORY_ROOT),
            "REPOSITORY_ROOT": str(_REPOSITORY_ROOT),
            "EXPECTED_DATABASE_URL": database_url,
            "EXPECTED_DB_TYPE": expected_db_type,
        }
    )

    completed = subprocess.run(
        [sys.executable, "-m", "tests.support.migration_runner", launch_mode],
        cwd=case_dir,
        env=child_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"migration child failed ({launch_mode})\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _set_launch_argv(launch_mode: str, repository_root: Path, config_dir: Path) -> None:
    if launch_mode == "script":
        sys.argv[:] = [
            str(repository_root / "telegramRSSbot.py"),
            "--config",
            str(config_dir),
        ]
    elif launch_mode == "module":
        sys.argv[:] = ["-m", "--config", str(config_dir)]
    else:
        raise AssertionError(f"unsupported launch mode: {launch_mode}")


async def _initialize_and_close() -> None:
    from src import db, env

    expected_database_url = os.environ["EXPECTED_DATABASE_URL"]
    expected_db_type = os.environ["EXPECTED_DB_TYPE"]
    assert env.DATABASE_URL == expected_database_url, (
        repr(env.DATABASE_URL),
        repr(expected_database_url),
    )
    assert db.DB_TYPE is None

    await db.init()
    try:
        assert db.DB_TYPE.value == expected_db_type
    finally:
        await db.close()


def main() -> None:
    launch_mode = sys.argv[1]
    repository_root = Path(os.environ["REPOSITORY_ROOT"]).resolve()
    config_dir = Path.cwd().resolve()
    _set_launch_argv(launch_mode, repository_root, config_dir)
    asyncio.run(_initialize_and_close())


if __name__ == "__main__":
    main()
