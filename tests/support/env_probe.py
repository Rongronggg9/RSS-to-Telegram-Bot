from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

ISOLATED_ENV_KEYS = (
    "DATABASE_URL",
    "DATABASE_PRIVATE_URL",
    "DATABASE_PUBLIC_URL",
    "SOCKS_PROXY",
    "socks_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "R_PROXY",
    "T_PROXY",
    "API_ID",
    "API_HASH",
    "TOKEN",
    "MANAGER",
    "CHATID",
    "ERROR_LOGGING_CHAT",
    "MANAGER_PRIVILEGED",
    "TELEGRAPH_TOKEN",
    "MULTIUSER",
    "CRON_SECOND",
    "PROXY_BYPASS_PRIVATE",
    "PROXY_BYPASS_DOMAINS",
    "USER_AGENT",
    "IPV6_PRIOR",
    "VERIFY_TLS",
    "HTTP_TIMEOUT",
    "HTTP_CONCURRENCY",
    "HTTP_CONCURRENCY_PER_HOST",
    "HTTP_MAX_LINE_SIZE",
    "HTTP_MAX_FIELD_SIZE",
    "IMG_RELAY_SERVER",
    "IMAGES_WESERV_NL",
    "TABLE_TO_IMAGE",
    "TRAFFIC_SAVING",
    "LAZY_MEDIA_VALIDATION",
    "NO_UVLOOP",
    "MULTIPROCESSING",
    "EXECUTOR_NICENESS_INCREMENT",
    "DEBUG",
    "PORT",
    "RAILWAY_STATIC_URL",
    "DELAY",
    "REDISHOST",
    "REDISUSER",
    "REDISPASSWORD",
    "REDISPORT",
    "REDIS_NUM",
    "HTTP_MAX_COMPRESSED_BODY_BYTES",
    "HTTP_MAX_DECOMPRESSED_BODY_BYTES",
    "HTTP_MAX_REDIRECTS",
    "HTTP_PRIVATE_ALLOWLIST",
    "PARSE_CONCURRENCY",
    "FEED_MAX_ENTRIES",
    "OPML_MAX_BYTES",
    "OPML_MAX_OUTLINES",
    "OPML_MAX_DEPTH",
    "OPML_PARSE_TIMEOUT",
    "SUBS_MAX_URLS_PER_REQUEST",
    "SUBS_MAX_SUBSCRIPTIONS_PER_REQUEST",
    "SUBS_CONCURRENCY",
    "MANAGER_TEST_MAX_ENTRIES",
    "MANAGER_TEST_CONCURRENCY",
    "MONITOR_MAX_PENDING_TASKS",
    "MONITOR_CONCURRENCY",
)

_PROBE = """
import json
import sys

config_folder = sys.argv[1]
sys.argv[:] = [sys.argv[0], "--config", config_folder]
from src import env

print(json.dumps({
    "config_folder_path": env.config_folder_path,
    "DATABASE_URL": env.DATABASE_URL,
    "HTTP_TIMEOUT": env.HTTP_TIMEOUT,
    "DEFAULT_PROXY": env.DEFAULT_PROXY or None,
    "R_PROXY": env.R_PROXY or None,
}))
"""


def _write_dotenv(path: Path, values: Mapping[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def run_env_probe(
    tmp_path: Path,
    *,
    config_values: Mapping[str, str] | None = None,
    cwd_values: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, object]:
    config_folder = tmp_path / "config"
    working_directory = tmp_path / "cwd"
    config_folder.mkdir()
    working_directory.mkdir()

    deterministic = {
        "TOKEN": "test",
        "MANAGER": "-1",
        "NO_UVLOOP": "1",
        "MULTIPROCESSING": "0",
    }
    _write_dotenv(config_folder / ".env", {**deterministic, **(config_values or {})})
    _write_dotenv(working_directory / ".env", cwd_values or {})

    child_environment = dict(os.environ)
    for key in (*ISOLATED_ENV_KEYS, "TEST_POSTGRES_DSN"):
        child_environment.pop(key, None)
    child_environment.update(deterministic)
    child_environment.update(overrides or {})
    child_environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, str(config_folder)],
        cwd=working_directory,
        env=child_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)
