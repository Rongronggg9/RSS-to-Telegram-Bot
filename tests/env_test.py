from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.env_probe import run_env_probe


@pytest.mark.unit
def test_cwd_dotenv_overrides_config_dotenv(tmp_path: Path) -> None:
    result = run_env_probe(
        tmp_path,
        config_values={"HTTP_TIMEOUT": "21"},
        cwd_values={"HTTP_TIMEOUT": "34"},
    )

    assert result["HTTP_TIMEOUT"] == 34


@pytest.mark.unit
def test_postgresql_database_url_is_normalized_to_postgres(tmp_path: Path) -> None:
    result = run_env_probe(
        tmp_path,
        cwd_values={"DATABASE_URL": "postgresql://user:pass@db.test/app"},
    )

    assert result["DATABASE_URL"] == "postgres://user:pass@db.test/app"


@pytest.mark.unit
def test_selected_config_folder_anchors_implicit_sqlite_database(tmp_path: Path) -> None:
    result = run_env_probe(tmp_path)

    assert result["DATABASE_URL"] == (
        f"sqlite:{result['config_folder_path']}/db.sqlite3"
    )
