from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import pytest

from tests.support.http import LocalFeedServer
from tests.support.models import create_active_subscription
from tests.support.telegram import RecordingTelegram

_FEED_FIXTURES = Path(__file__).parents[1] / "fixtures" / "feeds"


def _feed_bytes(name: str) -> bytes:
    return (_FEED_FIXTURES / name).read_bytes()


def _entry_hashes(name: str) -> list[str]:
    from src.command.inner.utils import calculate_update

    parsed = feedparser.parse(_feed_bytes(name))
    assert not parsed.bozo
    return list(calculate_update(None, parsed.entries)[0])


async def _monitor(feed: object, now: datetime) -> None:
    from src.monitor import Monitor

    await Monitor()._do_monitor_a_feed(feed, now)


@pytest.mark.http
@pytest.mark.telegram
@pytest.mark.sqlite
async def test_monitor_sends_only_unseen_entries_oldest_first(
    sqlite_state: None,
    local_feed_server: LocalFeedServer,
    recording_telegram: RecordingTelegram,
) -> None:
    _, feed, _ = await create_active_subscription(
        link=local_feed_server.feed_url,
        entry_hashes=_entry_hashes("baseline.xml"),
        send_mode=2,
    )
    local_feed_server.enqueue(body=_feed_bytes("updated.xml"))
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    await _monitor(feed, now)

    assert [message.message.split("\n", 1)[0] for message in recording_telegram.messages] == [
        "new-1",
        "new-2",
    ]
    assert all("old-" not in message.message for message in recording_telegram.messages)

    local_feed_server.enqueue(body=_feed_bytes("updated.xml"))
    await _monitor(feed, now + timedelta(minutes=1))
    assert len(recording_telegram.messages) == 2


@pytest.mark.http
@pytest.mark.telegram
@pytest.mark.sqlite
async def test_monitor_does_not_deliver_or_mutate_hashes_for_304(
    sqlite_state: None,
    local_feed_server: LocalFeedServer,
    recording_telegram: RecordingTelegram,
) -> None:
    hashes = _entry_hashes("baseline.xml")
    _, feed, _ = await create_active_subscription(
        link=local_feed_server.feed_url,
        entry_hashes=hashes,
        etag='"fixture-etag"',
        send_mode=2,
    )
    last_modified = datetime(2025, 12, 31, 12, tzinfo=timezone.utc)
    feed.last_modified = last_modified
    await feed.save(update_fields=("last_modified",))
    local_feed_server.enqueue(status=304, headers={"ETag": '"replacement"'})

    await _monitor(feed, datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    await feed.refresh_from_db()

    assert feed.entry_hashes == hashes
    assert feed.etag == '"fixture-etag"'
    assert feed.last_modified == last_modified
    assert recording_telegram.messages == []


@pytest.mark.http
@pytest.mark.telegram
@pytest.mark.sqlite
async def test_monitor_defers_next_check_at_tenth_error(
    sqlite_state: None,
    local_feed_server: LocalFeedServer,
    recording_telegram: RecordingTelegram,
) -> None:
    _, feed, _ = await create_active_subscription(
        link=local_feed_server.feed_url,
        error_count=9,
        interval=10,
        send_mode=2,
    )
    local_feed_server.enqueue(status=503, body=b"unavailable")
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    await _monitor(feed, now)
    await feed.refresh_from_db()

    assert feed.error_count == 10
    assert feed.next_check_time == now + timedelta(minutes=20)
    assert feed.state == 1
    assert recording_telegram.messages == []


@pytest.mark.http
@pytest.mark.telegram
@pytest.mark.sqlite
async def test_monitor_deactivates_and_notifies_at_hundredth_error(
    sqlite_state: None,
    local_feed_server: LocalFeedServer,
    recording_telegram: RecordingTelegram,
) -> None:
    from src import db

    user, feed, sub = await create_active_subscription(
        link=local_feed_server.feed_url,
        error_count=99,
        interval=10,
        send_mode=2,
    )
    user.lang = "en"
    user.notify = 1
    await user.save(update_fields=("lang", "notify"))
    local_feed_server.enqueue(status=503, body=b"unavailable")

    await _monitor(feed, datetime(2026, 1, 1, 12, tzinfo=timezone.utc))

    persisted_feed = await db.Feed.get(id=feed.id)
    persisted_sub = await db.Sub.get(id=sub.id)
    assert persisted_feed.state == 0
    assert persisted_feed.error_count == 0
    assert persisted_sub.state == 0
    assert len(recording_telegram.messages) == 1
    assert recording_telegram.messages[0].entity == user.id
    assert "failed 100 consecutive times" in recording_telegram.messages[0].message


@pytest.mark.http
@pytest.mark.telegram
@pytest.mark.sqlite
async def test_monitor_uses_server_cache_deferral_with_frozen_clock(
    sqlite_state: None,
    local_feed_server: LocalFeedServer,
    recording_telegram: RecordingTelegram,
) -> None:
    _, feed, _ = await create_active_subscription(
        link=local_feed_server.feed_url,
        entry_hashes=_entry_hashes("baseline.xml"),
        send_mode=2,
    )
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    local_feed_server.enqueue(
        headers={
            "Cache-Control": "max-age=900",
            "CF-Cache-Status": "HIT",
            "Date": "Thu, 01 Jan 2026 12:00:00 GMT",
        },
        body=_feed_bytes("baseline.xml"),
    )

    await _monitor(feed, now)
    await feed.refresh_from_db()

    assert feed.next_check_time == now + timedelta(minutes=15)
    assert feed.entry_hashes == _entry_hashes("baseline.xml")
    assert recording_telegram.messages == []
