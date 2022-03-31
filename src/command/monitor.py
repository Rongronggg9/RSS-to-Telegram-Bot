from __future__ import annotations
from typing import Union
from typing_extensions import Final
from collections.abc import MutableMapping

import gc
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from collections import defaultdict, Counter
from traceback import format_exc

from . import inner
from .utils import escape_html
from .inner.utils import get_hash, update_interval, deactivate_feed
from .. import log, db, env, web
from ..errors_collection import EntityNotFoundError, UserBlockedErrors
from ..i18n import i18n
from ..parsing.post import get_post_from_entry, Post
from ..parsing.utils import html_space_stripper

logger = log.getLogger('RSStT.monitor')

NOT_UPDATED: Final = 'not_updated'
CACHED: Final = 'cached'
EMPTY: Final = 'empty'
FAILED: Final = 'failed'
UPDATED: Final = 'updated'
SKIPPED: Final = 'skipped'

# it may cause memory leak, but they are too small that leaking thousands of that is still not a big deal!
__user_unsub_all_lock_bucket: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
__user_blocked_counter = Counter()


class MonitoringLogs:
    monitoring_counts = 0
    not_updated = 0
    cached = 0
    empty = 0
    failed = 0
    updated = 0
    skipped = 0
    timeout = 0

    @classmethod
    def log(cls, not_updated: int, cached: int, empty: int, failed: int, updated: int, skipped: int, timeout: int):
        cls.not_updated += not_updated
        cls.cached += cached
        cls.empty += empty
        cls.failed += failed
        cls.updated += updated
        cls.skipped += skipped
        cls.timeout += timeout
        logger.debug(f'Finished feeds monitoring task: '
                     f'updated({updated}), '
                     f'not updated({not_updated}, including {cached} cached and {empty} empty), '
                     f'fetch failed({failed}), '
                     f'skipped({skipped}), '
                     f'timeout({timeout})')
        cls.monitoring_counts += 1
        if cls.monitoring_counts == 10:
            cls.print_summary()
            gc.collect()

    @classmethod
    def print_summary(cls):
        logger.info(
            f'Monitoring tasks summary in last 10 minutes: '
            f'updated({cls.updated}), '
            f'not updated({cls.not_updated}, including {cls.cached} cached and {cls.empty} empty), '
            f'fetch failed({cls.failed}), '
            f'skipped({cls.skipped}), '
            f'timeout({cls.timeout})'
        )
        cls.not_updated = cls.cached = cls.empty = cls.failed = cls.updated = cls.skipped = cls.timeout = 0
        cls.monitoring_counts = 0


async def run_monitor_task():
    feed_id_to_monitor = db.effective_utils.EffectiveTasks.get_tasks()
    if not feed_id_to_monitor:
        return

    feeds = await db.Feed.filter(id__in=feed_id_to_monitor)

    logger.debug('Started feeds monitoring task.')
    wait_for = 10 * 60
    timeout_errors = []

    result = await asyncio.gather(*(asyncio.wait_for(__monitor(feed), timeout=wait_for) for feed in feeds),
                                  return_exceptions=True)

    not_updated = 0
    cached = 0
    empty = 0
    failed = 0
    updated = 0
    skipped = 0
    timeout = 0

    for f, r in zip(feeds, result):
        if r is NOT_UPDATED:
            not_updated += 1
        elif r is CACHED:
            not_updated += 1
            cached += 1
        elif r is EMPTY:
            not_updated += 1
            empty += 1
        elif r is UPDATED:
            updated += 1
        elif r is FAILED:
            failed += 1
        elif r is SKIPPED:
            skipped += 1
        elif isinstance(r, asyncio.TimeoutError):
            timeout += 1
            timeout_errors.append((f, r))
        elif isinstance(r, BaseException):
            raise r
        else:
            raise TypeError(f'Unknown monitor result type: {r}')

    MonitoringLogs.log(not_updated, cached, empty, failed, updated, skipped, timeout)
    if timeout_errors:
        logger.error(f'Timeout detected during a feeds monitoring task, '
                     f'totally {timeout} feed(s) timed out after {wait_for}s:')
        for feed, error in timeout_errors:
            logger.error(f'The TimeoutError of the feed ({feed.link}) in the task:', exc_info=error)


async def __monitor(feed: db.Feed) -> str:
    """
    Monitor the update of a feed.

    :param feed: the feed object to be monitored
    :return: monitoring result
    """
    now = datetime.now(timezone.utc)
    if feed.next_check_time and now < feed.next_check_time:
        return SKIPPED  # skip this monitor task

    headers = {
        'If-Modified-Since': format_datetime(feed.last_modified or feed.updated_at)
    }
    if feed.etag:
        headers['If-None-Match'] = feed.etag

    wf = await web.feed_get(feed.link, headers=headers, verbose=False)
    rss_d = wf.rss_d

    if (rss_d is not None or wf.status == 304) and (feed.error_count > 0 or feed.next_check_time):
        feed.error_count = 0
        feed.next_check_time = None
        await feed.save()

    if wf.status == 304:  # cached
        logger.debug(f'Fetched (not updated, cached): {feed.link}')
        return CACHED

    if rss_d is None:  # error occurred
        feed.error_count += 1
        if feed.error_count % 20 == 0:  # error_count is always > 0
            logger.warning(f'Fetch failed ({feed.error_count}th retry, {wf.error}): {feed.link}')
        if feed.error_count >= 100:
            logger.error(f'Deactivated feed due to too many errors: {feed.link}')
            await __deactivate_feed_and_notify_all(feed, reason=wf.error)
            return FAILED
        if feed.error_count >= 10:  # too much error, delay next check
            interval = feed.interval or db.EffectiveOptions.default_interval
            next_check_interval = min(interval, 15) * min(feed.error_count // 10 + 1, 5)
            if next_check_interval > interval:
                feed.next_check_time = now + timedelta(minutes=next_check_interval)
        await feed.save()
        return FAILED

    if not rss_d.entries:  # empty
        if wf.url != feed.link:
            await inner.sub.migrate_to_new_url(feed, wf.url)
        logger.debug(f'Fetched (empty): {feed.link}')
        return EMPTY

    title = rss_d.feed.title
    title = html_space_stripper(title) if title else ''
    if title != feed.title:
        logger.debug(f'Feed title changed ({feed.title} -> {title}): {feed.link}')
        feed.title = title
        await feed.save()

    # sequence matters so we cannot use a set
    old_hashes: list = feed.entry_hashes if isinstance(feed.entry_hashes, list) else []
    updated_hashes = []
    updated_entries = []
    for entry in rss_d.entries:
        guid = entry.get('guid') or entry.get('link')
        if not guid:
            continue  # IDK why there are some feeds containing entries w/o a link, should we set up a feed hospital?
        h = get_hash(guid)
        if h in old_hashes:
            continue
        updated_hashes.append(h)
        updated_entries.append(entry)

    if not updated_hashes:  # not updated
        logger.debug(f'Fetched (not updated): {feed.link}')
        return NOT_UPDATED

    logger.debug(f'Updated: {feed.link}')
    length = max(len(rss_d.entries) * 2, 100)
    new_hashes = updated_hashes + old_hashes[:length - len(updated_hashes)]
    feed.entry_hashes = new_hashes
    http_caching_d = inner.utils.get_http_caching_headers(wf.headers)
    feed.etag = http_caching_d['ETag']
    feed.last_modified = http_caching_d['Last-Modified']
    await feed.save()

    if wf.url != feed.link:
        new_url_feed = await inner.sub.migrate_to_new_url(feed, wf.url)
        feed = new_url_feed if isinstance(new_url_feed, db.Feed) else feed

    await asyncio.gather(*(__notify_all(feed, entry) for entry in updated_entries[::-1]))

    return UPDATED


async def __notify_all(feed: db.Feed, entry: MutableMapping):
    subs = await db.Sub.filter(feed=feed, state=1)
    if not subs:  # nobody has subbed it
        await update_interval(feed)
    link = entry.get('link')
    try:
        post = get_post_from_entry(entry, feed.title, feed.link)
    except Exception as e:
        logger.error(f'Failed to parse the post {link} (feed: {feed.link}) from entry:', exc_info=e)
        try:
            error_message = Post(f'Something went wrong while parsing the post {link} '
                                 f'(feed: {feed.link}). '
                                 f'Please check:<br><br>' +
                                 format_exc().replace('\n', '<br>'),
                                 feed_title=feed.title, link=link)
            await error_message.send_formatted_post(env.MANAGER, send_mode=2)
        except Exception as e:
            logger.error(f'Failed to send parsing error message for {link} (feed: {feed.link}):', exc_info=e)
            await env.bot.send_message(env.MANAGER, f'A parsing error message cannot be sent, please check the logs.')
        return
    await asyncio.gather(
        *(__send(sub, post) for sub in subs)
    )


async def __send(sub: db.Sub, post: Union[str, Post]):
    user_id = sub.user_id
    try:
        try:
            try:
                await env.bot.get_input_entity(user_id)  # verify that the input entity can be gotten first
            except ValueError:  # cannot get the input entity, the bot may be banned by the user
                raise EntityNotFoundError(user_id)
            if isinstance(post, str):
                await env.bot.send_message(user_id, post, parse_mode='html', silent=not sub.notify)
                return
            await post.send_formatted_post_according_to_sub(sub)
            if __user_blocked_counter[user_id]:  # reset the counter if success
                del __user_blocked_counter[user_id]
        except UserBlockedErrors as e:
            user_unsub_all_lock = __user_unsub_all_lock_bucket[user_id]
            if user_unsub_all_lock.locked():
                return  # no need to unsub twice!
            async with user_unsub_all_lock:
                # TODO: leave the group/channel if still in it
                if __user_blocked_counter[user_id] < 5:
                    __user_blocked_counter[user_id] += 1
                    return  # skip once
                # fail for 5 times, consider been banned
                del __user_blocked_counter[user_id]
                if await inner.utils.have_subs(user_id):
                    logger.error(f'User blocked ({type(e).__name__}): {user_id}')
                    await inner.sub.unsub_all(user_id)
    except Exception as e:
        logger.error(f'Failed to send {post.link} (feed: {post.feed_link}, user: {sub.user_id}):', exc_info=e)
        try:
            error_message = Post(f'Something went wrong while sending this post '
                                 f'(feed: {post.feed_link}, user: {sub.user_id}). '
                                 f'Please check:<br><br>' +
                                 format_exc().replace('\n', '<br>'),
                                 title=post.title, feed_title=post.feed_title, link=post.link, author=post.author,
                                 feed_link=post.feed_link)
            await error_message.send_formatted_post(env.MANAGER, send_mode=2)
        except Exception as e:
            logger.error(f'Failed to send sending error message for {post.link} '
                         f'(feed: {post.feed_link}, user: {sub.user_id}):',
                         exc_info=e)
            await env.bot.send_message(env.MANAGER, f'An sending error message cannot be sent, please check the logs.')


async def __deactivate_feed_and_notify_all(feed: db.Feed, reason: Union[web.WebError, str] = None):
    subs = await db.Sub.filter(feed=feed, state=1).prefetch_related('user')
    await deactivate_feed(feed)

    if not subs:  # nobody has subbed it or no active sub exists
        return

    await asyncio.gather(
        *(
            __send(
                sub=sub,
                post=(
                        f'<a href="{feed.link}">{escape_html(sub.title or feed.title)}</a>\n'
                        + i18n[sub.user.lang]['feed_deactivated_warn']
                        + (
                            f'\n{reason.i18n_message(sub.user.lang) if isinstance(reason, web.WebError) else reason}'
                            if reason else ''
                        )
                )
            )
            for sub in subs)
    )
