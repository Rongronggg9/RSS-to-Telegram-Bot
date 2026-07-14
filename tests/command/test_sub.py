from __future__ import annotations

from pathlib import Path
from zlib import crc32

import feedparser
import pytest

from tests.support.http import LocalFeedServer
from tests.support.models import create_active_subscription
from tests.support.telegram import RecordingTelegram


_FEED_FIXTURES = Path(__file__).parents[1] / "fixtures" / "feeds"


@pytest.mark.telegram
@pytest.mark.http
@pytest.mark.sqlite
async def test_first_subscription_records_existing_entries_without_delivery(
    sqlite_state: None,
    local_feed_server: LocalFeedServer,
    recording_telegram: RecordingTelegram,
) -> None:
    from src import db
    from src.command.inner.sub import sub
    from src.command.inner.utils import calculate_update

    baseline = (_FEED_FIXTURES / "baseline.xml").read_bytes()
    parsed = feedparser.parse(baseline)
    assert not parsed.bozo
    user = await db.User.create(id=1101, state=1)
    local_feed_server.enqueue(
        headers={"Content-Type": "application/rss+xml"},
        body=baseline,
    )

    result = await sub(user.id, local_feed_server.feed_url)

    feed = await db.Feed.get(link=local_feed_server.feed_url)
    assert result["sub"] is not None
    assert result["sub"].feed_id == feed.id
    assert feed.entry_hashes == list(
        calculate_update(old_hashes=None, entries=parsed.entries)[0]
    )
    assert await db.Sub.filter(user_id=user.id, feed_id=feed.id).exists()
    assert recording_telegram.messages == []


@pytest.mark.unit
def test_calculate_update_prefers_guid_then_link_title_summary_and_content() -> None:
    from src.command.inner.utils import calculate_update

    entries = [
        {
            "guid": "identity-guid",
            "link": "https://example.test/ignored-link",
            "title": "ignored title",
            "summary": "ignored summary",
            "content": [{"value": "ignored content"}],
        },
        {
            "link": "https://example.test/identity-link",
            "title": "ignored title",
            "summary": "ignored summary",
            "content": [{"value": "ignored content"}],
        },
        {
            "title": "identity title",
            "summary": "ignored summary",
            "content": [{"value": "ignored content"}],
        },
        {
            "summary": "identity summary",
            "content": [{"value": "ignored content"}],
        },
        {
            "content": [
                {"value": ""},
                {"value": "identity content"},
                {"value": "ignored later content"},
            ],
        },
    ]
    identities = (
        "identity-guid",
        "https://example.test/identity-link",
        "identity title",
        "identity summary",
        "identity content",
    )

    hashes, updated_entries = calculate_update(old_hashes=None, entries=entries)

    assert list(hashes) == [f"{crc32(identity.encode('utf-8')):x}" for identity in identities]
    assert list(updated_entries) == entries


@pytest.mark.sqlite
async def test_sub_reactivates_existing_inactive_subscription_without_duplicate(
    sqlite_state: None,
) -> None:
    from src import db
    from src.command.inner.sub import sub

    user, feed, subscription = await create_active_subscription(
        user_id=1102,
        link="https://example.test/reactivate",
        interval=9,
    )
    subscription.state = 0
    await subscription.save(update_fields=("state",))

    result = await sub(user.id, feed.link)

    persisted = await db.Sub.get(id=subscription.id)
    assert result["sub"] is not None
    assert result["sub"].id == subscription.id
    assert persisted.state == 1
    assert await db.Sub.filter(user_id=user.id, feed_id=feed.id).count() == 1


@pytest.mark.sqlite
async def test_unsub_by_url_then_id_deletes_exact_rows_and_preserves_result_order(
    sqlite_state: None,
) -> None:
    from src import db
    from src.command.inner.sub import unsubs

    user, by_url_feed, by_url_sub = await create_active_subscription(
        user_id=1103,
        link="https://reader:secret@example.test/by-url",
        interval=7,
    )
    by_id_feed = await db.Feed.create(
        state=1,
        link="https://example.test/by-id",
        title="By ID",
        interval=11,
    )
    by_id_sub = await db.Sub.create(
        state=1,
        user=user,
        feed=by_id_feed,
        interval=11,
    )
    preserved_feed = await db.Feed.create(
        state=1,
        link="https://example.test/preserved",
        title="Preserved",
        interval=13,
    )
    preserved_sub = await db.Sub.create(
        state=1,
        user=user,
        feed=preserved_feed,
        interval=13,
    )

    result = await unsubs(
        user.id,
        feed_urls=(by_url_feed.link,),
        sub_ids=(by_id_sub.id,),
    )

    assert result is not None
    assert [
        (item["url"], item["sub"].id if item["sub"] is not None else None)
        for item in result["unsub_d_l"]
    ] == [
        (by_url_feed.link, by_url_sub.id),
        (by_id_feed.link, by_id_sub.id),
    ]
    assert result["success_count"] == 2
    assert result["failure_count"] == 0
    assert not await db.Sub.filter(id__in=(by_url_sub.id, by_id_sub.id)).exists()
    assert await db.Sub.filter(id=preserved_sub.id).exists()


@pytest.mark.sqlite
async def test_unsub_all_deletes_every_persisted_subscription(
    sqlite_state: None,
) -> None:
    from src import db
    from src.command.inner.sub import unsub_all

    user, first_feed, first_sub = await create_active_subscription(
        user_id=1104,
        link="https://example.test/all-first",
        interval=6,
    )
    second_feed = await db.Feed.create(
        state=0,
        link="https://example.test/all-second",
        title="All Second",
        interval=12,
    )
    second_sub = await db.Sub.create(
        state=0,
        user=user,
        feed=second_feed,
        interval=12,
    )
    other_user = await db.User.create(id=1105, state=1)
    preserved_sub = await db.Sub.create(
        state=1,
        user=other_user,
        feed=first_feed,
        interval=14,
    )

    result = await unsub_all(user.id)

    assert result is not None
    assert result["success_count"] == 2
    assert result["failure_count"] == 0
    assert {
        item["sub"].id
        for item in result["unsub_d_l"]
        if item["sub"] is not None
    } == {first_sub.id, second_sub.id}
    assert not await db.Sub.filter(user_id=user.id).exists()
    assert await db.Sub.filter(id=preserved_sub.id).exists()


@pytest.mark.sqlite
async def test_redirect_migration_preserves_subscriptions_and_recomputes_effective_interval(
    sqlite_state: None,
) -> None:
    from src import db
    from src.command.inner.sub import migrate_to_new_url

    authenticated_old_url = "http://reader:secret@example.test/old-feed"
    authenticated_new_url = "https://reader:secret@example.test/new-feed"
    first_user, source, first_sub = await create_active_subscription(
        user_id=1106,
        link=authenticated_old_url,
        interval=8,
    )
    second_user = await db.User.create(id=1107, state=1)
    second_sub = await db.Sub.create(
        state=1,
        user=second_user,
        feed=source,
        interval=12,
    )
    destination = await db.Feed.create(
        state=1,
        link=authenticated_new_url,
        title="Occupied Destination",
        interval=30,
    )
    destination_user = await db.User.create(id=1108, state=1)
    destination_sub = await db.Sub.create(
        state=1,
        user=destination_user,
        feed=destination,
        interval=30,
    )
    db.EffectiveTasks.update(destination.id, 30)

    migrated = await migrate_to_new_url(source, authenticated_new_url)

    assert migrated is not True and migrated is not False
    assert migrated.id == destination.id
    destination = await db.Feed.get(id=destination.id)
    assert destination.link == authenticated_new_url
    assert not await db.Feed.filter(id=source.id).exists()
    assert set(
        await db.Sub.filter(feed_id=destination.id).values_list("id", flat=True)
    ) == {first_sub.id, second_sub.id, destination_sub.id}
    assert await db.Sub.filter(user_id=first_user.id, feed_id=destination.id).exists()
    assert destination.interval == 8
    assert db.EffectiveTasks.get_interval(destination.id) == 8
