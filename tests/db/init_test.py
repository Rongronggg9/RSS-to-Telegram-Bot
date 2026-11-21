from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from tortoise.exceptions import IntegrityError


async def _create_nondefault_graph(*, user_id: int, feed_id: int, sub_id: int) -> None:
    from src import db

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
        link=f"https://schema.example.test/{feed_id}",
        title="Schema fixture feed",
        interval=17,
        entry_hashes=[10101, 20202],
        etag="schema-etag",
        last_modified=datetime(2024, 4, 25, 2, 8, 49, tzinfo=timezone.utc),
        error_count=7,
        next_check_time=datetime(2024, 4, 26, 2, 8, 49, tzinfo=timezone.utc),
    )
    await db.Sub.create(
        id=sub_id,
        state=1,
        user=user,
        feed=feed,
        title="Schema fixture subscription",
        tags="schema,fixture",
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


@pytest_asyncio.fixture
async def sqlite_schema_state() -> AsyncIterator[None]:
    from src import db

    if db.DB_TYPE is not db.DBType.SQLITE:
        pytest.skip("requires the isolated SQLite runtime")
    for model in (db.Sub, db.Feed, db.User, db.Option):
        await model.all().delete()
    try:
        yield
    finally:
        for model in (db.Sub, db.Feed, db.User, db.Option):
            await model.all().delete()


@pytest.mark.sqlite
async def test_db_init_is_idempotent_on_current_temporary_sqlite_schema(
    sqlite_schema_state: None,
) -> None:
    from src import db

    await _create_nondefault_graph(user_id=8101, feed_id=8201, sub_id=8301)
    await db.Option.create(id=8401, key="schema_fixture", value="retained")

    await db.init()

    user = await db.User.get(id=8101)
    feed = await db.Feed.get(id=8201)
    subscription = await db.Sub.get(id=8301)
    option = await db.Option.get(id=8401)
    assert (user.lang, user.admin, user.interval, user.display_entry_tags) == (
        "en",
        9001,
        19,
        1,
    )
    assert (feed.link, feed.entry_hashes, feed.etag, feed.error_count) == (
        "https://schema.example.test/8201",
        [10101, 20202],
        "schema-etag",
        7,
    )
    assert (
        subscription.user_id,
        subscription.feed_id,
        subscription.tags,
        subscription.display_entry_tags,
    ) == (8101, 8201, "schema,fixture", 1)
    assert (option.key, option.value) == ("schema_fixture", "retained")


@pytest.mark.sqlite
async def test_sqlite_persists_current_model_defaults(
    sqlite_schema_state: None,
) -> None:
    from src import db

    created_user = await db.User.create(id=8501)
    created_feed = await db.Feed.create(
        id=8601,
        link="https://defaults.example.test/feed",
        title="Defaults fixture feed",
    )
    await db.Sub.create(id=8701, user=created_user, feed=created_feed)

    user = await db.User.get(id=8501)
    feed = await db.Feed.get(id=8601)
    subscription = await db.Sub.get(id=8701)

    assert (
        user.state,
        user.lang,
        user.admin,
        user.sub_limit,
        user.interval,
        user.notify,
        user.send_mode,
        user.length_limit,
        user.link_preview,
        user.display_author,
        user.display_via,
        user.display_title,
        user.display_entry_tags,
        user.style,
        user.display_media,
    ) == (
        0,
        "zh-Hans",
        None,
        None,
        None,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        -1,
        0,
        0,
    )
    assert (
        feed.state,
        feed.interval,
        feed.entry_hashes,
        feed.etag,
        feed.last_modified,
        feed.error_count,
        feed.next_check_time,
    ) == (1, None, None, None, None, 0, None)
    assert (
        subscription.state,
        subscription.title,
        subscription.tags,
        subscription.interval,
        subscription.notify,
        subscription.send_mode,
        subscription.length_limit,
        subscription.link_preview,
        subscription.display_author,
        subscription.display_via,
        subscription.display_title,
        subscription.display_entry_tags,
        subscription.style,
        subscription.display_media,
    ) == (
        1,
        None,
        None,
        None,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        -100,
        0,
        0,
    )


@pytest.mark.sqlite
async def test_sqlite_rejects_duplicate_subscription(
    sqlite_schema_state: None,
) -> None:
    from src import db

    await _create_nondefault_graph(user_id=8801, feed_id=8901, sub_id=9001)
    user = await db.User.get(id=8801)
    feed = await db.Feed.get(id=8901)

    with pytest.raises(IntegrityError):
        await db.Sub.create(id=9002, user=user, feed=feed)

    assert await db.Sub.filter(user_id=8801, feed_id=8901).count() == 1


@pytest.mark.sqlite
async def test_sqlite_deleting_user_cascades_subscription_but_preserves_feed(
    sqlite_schema_state: None,
) -> None:
    from src import db

    await _create_nondefault_graph(user_id=9101, feed_id=9201, sub_id=9301)
    user = await db.User.get(id=9101)

    await user.delete()

    assert not await db.Sub.filter(id=9301).exists()
    assert await db.Feed.filter(id=9201).exists()
