from __future__ import annotations

import asyncio

from pathlib import Path

import aiohttp
import pytest

from tests.support.env_probe import run_env_probe
from tests.support.http import LocalFeedServer
from tests.support.models import create_active_subscription
from tests.support.telegram import (
    RecordingTelegram,
    SentTelegramMessage,
    recording_telegram as recording_telegram_fixture,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "dsn",
    (
        "sqlite:/tmp/developer.db",
        "postgres:///missing-host",
        "postgresql:///missing-host",
    ),
)
def test_postgres_dsn_validation_rejects_unsafe_values(dsn: str) -> None:
    from conftest import _canonical_postgres_dsn

    with pytest.raises(pytest.UsageError, match="TEST_POSTGRES_DSN"):
        _canonical_postgres_dsn(dsn)


@pytest.mark.unit
def test_postgres_dsn_validation_normalizes_postgresql_scheme() -> None:
    from conftest import _canonical_postgres_dsn

    assert (
        _canonical_postgres_dsn("postgresql://user:pass@db.test/app")
        == "postgres://user:pass@db.test/app"
    )


@pytest.mark.unit
def test_missing_or_empty_postgres_dsn_selects_no_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from conftest import _selected_postgres_dsn

    monkeypatch.delenv("TEST_POSTGRES_DSN", raising=False)
    assert _selected_postgres_dsn() is None
    monkeypatch.setenv("TEST_POSTGRES_DSN", "")
    assert _selected_postgres_dsn() is None


@pytest.mark.unit
async def test_initialized_runtime_closes_import_loop_and_installs_pytest_loop() -> None:
    from conftest import _IMPORT_TIME_LOOP

    running_loop = asyncio.get_running_loop()

    assert _IMPORT_TIME_LOOP is not None
    assert _IMPORT_TIME_LOOP is not running_loop
    assert _IMPORT_TIME_LOOP.is_closed()
    assert asyncio.get_event_loop() is running_loop


@pytest.mark.sqlite
async def test_isolated_runtime_uses_real_sqlite_without_inherited_proxy(
    sqlite_state: None,
) -> None:
    from src import db, env

    assert db.DB_TYPE is db.DBType.SQLITE
    assert not env.DEFAULT_PROXY
    assert not env.R_PROXY

    user, feed, subscription = await create_active_subscription(
        user_id=7101,
        link="https://example.test/harness-feed",
    )
    assert await db.User.get(id=user.id) == user
    assert await db.Feed.get(id=feed.id) == feed
    assert await db.Sub.get(id=subscription.id) == subscription


@pytest.mark.http
async def test_local_feed_server_serves_fifo_responses_and_records_requests(
    local_feed_server: LocalFeedServer,
) -> None:
    local_feed_server.enqueue(
        status=201,
        headers={"X-Fixture": "first"},
        body=b"first body",
    )
    local_feed_server.enqueue(status=202, body=b"second body")

    async with aiohttp.ClientSession() as client:
        async with client.get(f"{local_feed_server.feed_url}?page=1") as response:
            assert response.status == 201
            assert response.headers["X-Fixture"] == "first"
            assert await response.read() == b"first body"
        async with client.post(local_feed_server.feed_url) as response:
            assert response.status == 202
            assert await response.read() == b"second body"

    assert [(request.method, request.path_qs) for request in local_feed_server.requests] == [
        ("GET", "/feed?page=1"),
        ("POST", "/feed"),
    ]


@pytest.mark.http
async def test_local_feed_server_waits_for_response_gate(
    local_feed_server: LocalFeedServer,
) -> None:
    gate = asyncio.Event()
    local_feed_server.enqueue(body=b"released", wait_for=gate)

    async with aiohttp.ClientSession() as client:
        request_task = asyncio.create_task(client.get(local_feed_server.feed_url))
        try:
            while not local_feed_server.requests:
                await asyncio.sleep(0)
            assert not request_task.done()
            gate.set()
            response = await request_task
            async with response:
                assert await response.read() == b"released"
        finally:
            gate.set()
            if not request_task.done():
                request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)


@pytest.mark.telegram
async def test_recording_telegram_captures_messages_without_delivery(
    recording_telegram: RecordingTelegram,
) -> None:
    entity = object()
    assert await recording_telegram.get_input_entity(entity) is entity

    sent = await recording_telegram.send_message(
        entity,
        "fixture message",
        parse_mode="html",
    )

    expected = SentTelegramMessage(
        entity=entity,
        message="fixture message",
        kwargs={"parse_mode": "html"},
    )
    assert sent == expected
    assert recording_telegram.messages == [expected]


@pytest.mark.telegram
def test_recording_telegram_fixture_isolates_process_lifetime_state() -> None:
    from src import locks
    from src.monitor._notifier import Notifier
    from src.parsing.message import MessageDispatcher

    user_id = 7201
    first_context_patch = pytest.MonkeyPatch()
    first_context = recording_telegram_fixture.__wrapped__(first_context_patch)
    next(first_context)
    first_state = (
        Notifier._on_blocked_lock_bucket,
        Notifier._user_blocked_counter,
        Notifier._stat,
        MessageDispatcher.user_sending_lock,
        locks._user_bucket,
    )
    try:
        Notifier._on_blocked_lock_bucket[user_id]
        Notifier._user_blocked_counter[user_id] += 1
        Notifier._stat.start()
        MessageDispatcher.user_sending_lock[user_id]
        locks.user_msg_lock(user_id)

        with pytest.raises(StopIteration):
            next(first_context)
        first_context_patch.undo()

        second_context_patch = pytest.MonkeyPatch()
        second_context = recording_telegram_fixture.__wrapped__(second_context_patch)
        next(second_context)
        second_state = (
            Notifier._on_blocked_lock_bucket,
            Notifier._user_blocked_counter,
            Notifier._stat,
            MessageDispatcher.user_sending_lock,
            locks._user_bucket,
        )
        try:
            assert all(
                current is not previous
                for current, previous in zip(second_state, first_state)
            )
            assert all(
                user_id not in state
                for state in (
                    Notifier._on_blocked_lock_bucket,
                    Notifier._user_blocked_counter,
                    MessageDispatcher.user_sending_lock,
                    locks._user_bucket,
                )
            )
        finally:
            with pytest.raises(StopIteration):
                next(second_context)
            second_context_patch.undo()
    finally:
        Notifier._on_blocked_lock_bucket.pop(user_id, None)
        Notifier._user_blocked_counter.pop(user_id, None)
        first_state[2].finish()
        MessageDispatcher.user_sending_lock.pop(user_id, None)
        locks._user_bucket.pop(user_id, None)


@pytest.mark.unit
def test_env_probe_drops_inherited_database_and_proxy_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://developer:secret@db.invalid/app")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("R_PROXY", "socks5://proxy.invalid:1080")

    result = run_env_probe(tmp_path)

    assert result["DATABASE_URL"] == f"sqlite:{result['config_folder_path']}/db.sqlite3"
    assert result["DEFAULT_PROXY"] is None
    assert result["R_PROXY"] is None
