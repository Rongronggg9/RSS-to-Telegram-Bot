from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.env_probe import run_env_probe

CONTAINMENT_DEFAULTS = {
    "HTTP_TIMEOUT": 12,
    "HTTP_CONCURRENCY": 1024,
    "HTTP_CONCURRENCY_PER_HOST": 16,
    "HTTP_MAX_LINE_SIZE": 16384,
    "HTTP_MAX_FIELD_SIZE": 16384,
    "HTTP_MAX_COMPRESSED_BODY_BYTES": 8 * 1024 * 1024,
    "HTTP_MAX_DECOMPRESSED_BODY_BYTES": 32 * 1024 * 1024,
    "HTTP_MAX_REDIRECTS": 5,
    "PARSE_CONCURRENCY": 4,
    "FEED_MAX_ENTRIES": 1000,
    "OPML_MAX_BYTES": 8 * 1024 * 1024,
    "OPML_MAX_OUTLINES": 5000,
    "OPML_MAX_DEPTH": 32,
    "OPML_PARSE_TIMEOUT": 30,
    "SUBS_MAX_URLS_PER_REQUEST": 100,
    "SUBS_MAX_SUBSCRIPTIONS_PER_REQUEST": 100,
    "SUBS_CONCURRENCY": 8,
    "MANAGER_TEST_MAX_ENTRIES": 20,
    "MANAGER_TEST_CONCURRENCY": 4,
    "MONITOR_MAX_PENDING_TASKS": 256,
    "MONITOR_CONCURRENCY": 64,
}

STRICTLY_POSITIVE_SETTINGS = tuple(
    name
    for name in CONTAINMENT_DEFAULTS
    if name not in {"HTTP_TIMEOUT", "HTTP_MAX_REDIRECTS"}
)


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


@pytest.mark.unit
def test_containment_defaults_are_exact(tmp_path: Path) -> None:
    result = run_env_probe(tmp_path)

    assert {name: result[name] for name in CONTAINMENT_DEFAULTS} == (
        CONTAINMENT_DEFAULTS
    )


@pytest.mark.unit
@pytest.mark.parametrize("setting", STRICTLY_POSITIVE_SETTINGS)
@pytest.mark.parametrize(
    ("value", "expected_message"),
    (
        pytest.param("0", "must be a positive integer", id="zero"),
        pytest.param("-1", "must be a positive integer", id="negative"),
        pytest.param("not-an-int", "must be an integer", id="non-integer"),
    ),
)
def test_positive_integer_settings_reject_zero_negative_and_non_integer_values(
    tmp_path: Path,
    setting: str,
    value: str,
    expected_message: str,
) -> None:
    result = run_env_probe(tmp_path, overrides={setting: value})

    assert result == {
        "error_type": "ValueError",
        "error_message": f"{setting} {expected_message}",
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected_value", "expected_message"),
    (
        pytest.param("0", 0, None, id="zero"),
        pytest.param("-1", None, "must be a non-negative integer", id="negative"),
        pytest.param("not-an-int", None, "must be an integer", id="non-integer"),
    ),
)
def test_redirect_limit_accepts_zero_and_rejects_negative_values(
    tmp_path: Path,
    value: str,
    expected_value: int | None,
    expected_message: str | None,
) -> None:
    result = run_env_probe(tmp_path, overrides={"HTTP_MAX_REDIRECTS": value})

    if expected_message is None:
        assert result["HTTP_MAX_REDIRECTS"] == expected_value
    else:
        assert result == {
            "error_type": "ValueError",
            "error_message": f"HTTP_MAX_REDIRECTS {expected_message}",
        }


@pytest.mark.unit
def test_new_settings_follow_existing_dotenv_override_order(tmp_path: Path) -> None:
    result = run_env_probe(
        tmp_path,
        config_values={
            "HTTP_MAX_COMPRESSED_BODY_BYTES": "4096",
            "PARSE_CONCURRENCY": "3",
            "MONITOR_MAX_PENDING_TASKS": "17",
        },
        cwd_values={
            "PARSE_CONCURRENCY": "7",
            "MONITOR_MAX_PENDING_TASKS": "23",
        },
    )

    assert {
        "HTTP_MAX_COMPRESSED_BODY_BYTES": result[
            "HTTP_MAX_COMPRESSED_BODY_BYTES"
        ],
        "PARSE_CONCURRENCY": result["PARSE_CONCURRENCY"],
        "MONITOR_MAX_PENDING_TASKS": result["MONITOR_MAX_PENDING_TASKS"],
    } == {
        "HTTP_MAX_COMPRESSED_BODY_BYTES": 4096,
        "PARSE_CONCURRENCY": 7,
        "MONITOR_MAX_PENDING_TASKS": 23,
    }
