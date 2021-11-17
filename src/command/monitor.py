import asyncio
from email.utils import format_datetime
from json import loads, dumps
from typing import Optional, Union, MutableMapping
from zlib import crc32
from src import log, db
from src.parsing.post import get_post_from_entry, Post
from src.web import feed_get

logger = log.getLogger('RSStT.feed')


async def run_monitor_task():
    feed_id_to_monitor = db.effective_utils.EffectiveTasks.get_tasks()
    if not feed_id_to_monitor:
        return

    feeds = await db.Feed.filter(id__in=feed_id_to_monitor)

    logger.info('Started feeds monitoring task.')

    result = await asyncio.gather(*(__monitor(feed) for feed in feeds))

    no_update = 0
    fail = 0
    updated = 0

    for r in result:
        if r is None:
            no_update += 1
        elif r:
            updated += 1
        else:
            fail += 1

    logger.info(f'Finished feeds monitoring task: '
                f'updated({updated}), not updated({no_update}), fetch failed({fail})')


async def __monitor(feed: db.Feed) -> Optional[bool]:
    headers = {
        'If-Modified-Since': format_datetime(feed.updated_at)
    }
    if feed.etag:
        headers['If-None-Match'] = feed.etag

    d = await feed_get(feed.link, headers=headers)

    if d['status'] == 304:
        logger.debug(f'Fetched (not updated): {feed.link}')
        return None

    rss_d = d['rss_d']
    if rss_d is None:  # error occurred
        feed.error_count += 1
        await feed.save()
        return False

    if not rss_d.entries:  # empty
        logger.debug(f'Fetched (empty): {feed.link}')
        return None

    # python version >= 3.7: dict order is guaranteed to be insertion order
    # python version >= 3: crc32 output is an unsigned int
    entries = {hex(crc32(entry.get('guid', entry['link']).encode()))[2:]: entry
               for entry in rss_d.entries}
    old_hashes = loads(feed.entry_hashes) if feed.entry_hashes else []
    # sequence matters so we cannot use a set
    updated_hashes = [updated_hash for updated_hash in entries.keys() if updated_hash not in old_hashes]

    if not updated_hashes:  # not updated
        logger.debug(f'Fetched (not updated): {feed.link}')
        return None

    logger.info(f'Updated: {feed.link}')
    length = max(len(entries) * 2, 20)
    new_hashes = updated_hashes + old_hashes[:length - len(updated_hashes)]
    feed.entry_hashes = dumps(new_hashes) if new_hashes else None
    await asyncio.gather(
        *(__notify_all(feed, entries[updated_hash]) for updated_hash in updated_hashes),
        feed.save()
    )


async def __notify_all(feed, entry: MutableMapping):
    subs = await db.Sub.filter(feed=feed)
    if not subs:  # nobody has sub it
        feed.state = 1
        await feed.save()
        return
    post = get_post_from_entry(entry, feed.title, feed.link)
    await post.generate_message()
    await asyncio.gather(
        *(__send(sub, post) for sub in subs)
    )


async def __send(sub: db.Sub, post: Union[str, Post]):
    # TODO: customized format
    if isinstance(post, str):
        post = Post(post)
    await post.send_message(sub.user_id)
