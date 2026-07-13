from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src import db


async def create_active_subscription(
    *,
    user_id: int = 101,
    link: str = "https://example.test/feed",
    title: str = "Fixture Feed",
    entry_hashes: Sequence[str] | None = None,
    etag: str | None = None,
    error_count: int = 0,
    interval: int | None = 10,
    send_mode: int = -1,
) -> tuple[db.User, db.Feed, db.Sub]:
    from src import db

    user = await db.User.create(id=user_id, state=1)
    feed = await db.Feed.create(
        state=1,
        link=link,
        title=title,
        entry_hashes=list(entry_hashes) if entry_hashes is not None else None,
        etag=etag,
        error_count=error_count,
        interval=interval,
    )
    sub = await db.Sub.create(
        state=1,
        user=user,
        feed=feed,
        interval=interval,
        notify=-100,
        send_mode=send_mode,
        length_limit=-100,
        link_preview=-100,
        display_author=-100,
        display_via=-100,
        display_title=-100,
        display_entry_tags=-100,
        style=-100,
        display_media=-100,
    )
    return user, feed, sub
