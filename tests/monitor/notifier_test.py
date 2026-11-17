from __future__ import annotations

from collections.abc import MutableMapping

import feedparser
import pytest
from telethon.errors import FloodWaitError, UserIsBlockedError
from telethon.tl.types import MessageEntityTextUrl

from tests.support.models import create_active_subscription
from tests.support.telegram import RecordingTelegram


def _parsed_entry(
    *,
    title: str = "Entry Title",
    link: str = "https://example.test/entry",
    body: str = "Body marker",
    author: str = "Alice",
    tags: tuple[str, ...] = ("entry tag",),
) -> MutableMapping[str, object]:
    categories = "".join(f"<category>{tag}</category>" for tag in tags)
    parsed = feedparser.parse(
        f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Fixture Feed</title>
          <link>https://example.test/feed</link>
          <description>Fixture feed</description>
          <item><guid>urn:fixture:{title}</guid><title>{title}</title>
            <link>{link}</link><author>{author}</author>{categories}
            <description><![CDATA[{body}]]></description>
          </item>
        </channel></rss>""".encode()
    )
    assert not parsed.bozo
    return parsed.entries[0]


async def _notify_entries(feed: object, subs: list[object], entries: list[MutableMapping[str, object]]) -> None:
    from src.monitor._notifier import Notifier

    notifier = Notifier(feed=feed, subs=subs, entries=entries)
    await Notifier.notify_all.raw(notifier)


@pytest.mark.telegram
@pytest.mark.sqlite
async def test_notifier_delivers_parsed_entry_to_recording_telegram(
    sqlite_state: None,
    recording_telegram: RecordingTelegram,
) -> None:
    user, feed, sub = await create_active_subscription(send_mode=2)
    user.notify = 1
    user.display_author = 1
    user.display_via = 0
    user.display_title = 1
    user.display_entry_tags = -1
    await user.save()

    await _notify_entries(feed, [sub], [_parsed_entry()])

    assert [message.entity for message in recording_telegram.messages] == [sub.user_id]
    delivered = recording_telegram.messages[0]
    assert delivered.message == "Entry Title\n\nBody marker\n\nvia Fixture Feed (author: Alice)"
    assert delivered.kwargs["silent"] is False


@pytest.mark.telegram
@pytest.mark.sqlite
async def test_notifier_deactivation_delivery_records_html_message(
    sqlite_state: None,
    recording_telegram: RecordingTelegram,
) -> None:
    from src import db
    from src.monitor._notifier import Notifier

    user, feed, sub = await create_active_subscription(title="Fixture <Feed>")
    user.lang = "en"
    user.notify = 1
    await user.save(update_fields=("lang", "notify"))

    notifier = Notifier(feed=feed, subs=[sub], reason="upstream rejected the feed")
    await Notifier.notify_all.raw(notifier)

    assert len(recording_telegram.messages) == 1
    delivered = recording_telegram.messages[0]
    assert delivered.entity == user.id
    assert delivered.message == (
        f'<a href="{feed.link}">Fixture &lt;Feed&gt;</a>\n'
        "The monitoring task had failed 100 consecutive times. Your subscription to the RSS feed has been "
        "deactivated.\nTo reactivate it, please use the /activate_subs command.\nupstream rejected the feed"
    )
    assert delivered.kwargs == {"parse_mode": "html", "silent": False}
    assert (await db.Feed.get(id=feed.id)).state == 0
    assert (await db.Sub.get(id=sub.id)).state == 0


@pytest.mark.telegram
@pytest.mark.sqlite
async def test_notifier_formats_effective_title_link_author_tags_and_preview_options(
    sqlite_state: None,
    recording_telegram: RecordingTelegram,
) -> None:
    user, feed, sub = await create_active_subscription(send_mode=-100)
    user.send_mode = 2
    user.link_preview = 1
    user.display_author = 1
    user.display_via = 0
    user.display_title = 1
    user.display_entry_tags = 1
    user.notify = 0
    await user.save()
    sub.title = "Custom Feed"
    sub.tags = "subscription"
    sub.send_mode = -100
    await sub.save()

    await _notify_entries(feed, [sub], [_parsed_entry()])

    assert len(recording_telegram.messages) == 1
    delivered = recording_telegram.messages[0]
    assert delivered.message == (
        "Entry Title\n#subscription #entry_tag\n\nBody marker\n\nvia Custom Feed (author: Alice)"
    )
    assert delivered.kwargs["link_preview"] is True
    assert delivered.kwargs["silent"] is True
    link_entities = [
        entity
        for entity in delivered.kwargs["formatting_entities"]
        if isinstance(entity, MessageEntityTextUrl)
    ]
    assert [(entity.url, delivered.message[entity.offset : entity.offset + entity.length]) for entity in link_entities] == [
        ("https://example.test/entry", "Custom Feed")
    ]


@pytest.mark.telegram
@pytest.mark.sqlite
async def test_notifier_splits_oversize_formatted_post_in_order(
    sqlite_state: None,
    recording_telegram: RecordingTelegram,
) -> None:
    user, feed, sub = await create_active_subscription(send_mode=2)
    user.notify = 1
    user.display_author = 1
    user.display_via = 0
    user.display_title = 1
    user.display_entry_tags = -1
    await user.save()
    paragraphs = (("FIRST", "a"), ("SECOND", "b"), ("THIRD", "c"))
    body = "".join(f"<p>{marker}:{letter * 3500}</p>" for marker, letter in paragraphs)
    expected_text = (
        "Entry Title\n\n"
        + "".join(f"{marker}:{letter * 3500}" for marker, letter in paragraphs)
        + "\n\nvia Fixture Feed (author: Alice)"
    )

    await _notify_entries(feed, [sub], [_parsed_entry(body=body)])

    assert len(recording_telegram.messages) == 3
    assert all(len(message.message) <= 4096 for message in recording_telegram.messages)
    joined = "".join(message.message for message in recording_telegram.messages)
    assert joined == expected_text
    assert recording_telegram.messages[1].kwargs["reply_to"].id == recording_telegram.messages[0].id
    assert recording_telegram.messages[2].kwargs["reply_to"].id == recording_telegram.messages[1].id


@pytest.mark.telegram
@pytest.mark.sqlite
async def test_notifier_flood_wait_skips_only_affected_user_and_keeps_other_delivery(
    sqlite_state: None,
    recording_telegram: RecordingTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src import db, locks

    _, feed, first_sub = await create_active_subscription(user_id=101, send_mode=2)
    second_user = await db.User.create(id=202, state=1)
    second_sub = await db.Sub.create(user=second_user, feed=feed, state=1, send_mode=2)
    for _ in range(2):
        recording_telegram.fail_next_send(101, FloodWaitError(None, 1))

    async def finish_flood_wait_immediately(user: int, seconds: int) -> None:
        return None

    monkeypatch.setattr(locks, "user_flood_wait_background", finish_flood_wait_immediately)

    await _notify_entries(feed, [first_sub, second_sub], [_parsed_entry()])

    assert [attempt.entity for attempt in recording_telegram.send_attempts].count(101) == 2
    assert [message.entity for message in recording_telegram.messages] == [202]
    assert recording_telegram.messages[0].message.startswith("Entry Title\n\nBody marker")


@pytest.mark.telegram
@pytest.mark.sqlite
async def test_notifier_authorization_error_preserves_existing_block_and_deactivation_policy(
    sqlite_state: None,
    recording_telegram: RecordingTelegram,
) -> None:
    from src import db
    from src.monitor._notifier import Notifier

    _, feed, sub = await create_active_subscription(send_mode=2)
    Notifier._user_blocked_counter.pop(sub.user_id, None)
    for _ in range(6):
        recording_telegram.fail_next_send(sub.user_id, UserIsBlockedError(None))

    try:
        for _ in range(5):
            await _notify_entries(feed, [sub], [_parsed_entry()])
            assert (await db.Sub.get(id=sub.id)).state == 1

        await _notify_entries(feed, [sub], [_parsed_entry()])
        assert (await db.Sub.get(id=sub.id)).state == 0
        assert (await db.Feed.get(id=feed.id)).state == 1
        assert recording_telegram.messages == []
    finally:
        Notifier._user_blocked_counter.pop(sub.user_id, None)
