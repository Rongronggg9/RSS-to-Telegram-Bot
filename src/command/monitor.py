from __future__ import annotations
from typing import Union, Final, Optional
from collections.abc import MutableMapping, Iterable, Mapping

import gc
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from collections import defaultdict, Counter
from contextlib import AbstractContextManager
from itertools import islice
from traceback import format_exc
from telethon.errors import BadRequestError

from . import inner
from .utils import escape_html, unsub_all_and_leave_chat
from .. import log, db, env, web, locks
from ..errors_collection import EntityNotFoundError, UserBlockedErrors
from ..i18n import i18n
from ..parsing.post import get_post_from_entry, Post
from ..parsing.utils import html_space_stripper

logger = log.getLogger('RSStT.monitor')

TIMEOUT: Final[int] = 10 * 60  # 10 minutes

# it may cause memory leak, but they are too small that leaking thousands of that is still not a big deal!
__user_unsub_all_lock_bucket: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
__user_blocked_counter = Counter()


# TODO: move inside MonitoringStat once the minimum Python requirement is 3.10
# @staticmethod
def _gen_property(key: str):
    def getter(self):
        return self.counter[key]

    def setter(self, value):
        self.counter[key] = value

    return property(getter, setter)


class MonitoringStat(AbstractContextManager):
    # TODO: make __monitor directly call this class's method to log and make statistics
    class Meta:
        counter: MutableMapping[str, int] = Counter()
        last_summary_time: float = env.loop.time()
        task_finished: set[object] = set()
        task_in_progress: set[object] = set()
        task_stuck: set[object] = set()
        summary_period: float = TIMEOUT  # seconds

    not_updated: int = _gen_property('not_updated')
    cached: int = _gen_property('cached')
    empty: int = _gen_property('empty')
    failed: int = _gen_property('failed')
    updated: int = _gen_property('updated')
    skipped: int = _gen_property('skipped')
    timeout: int = _gen_property('timeout')
    cancelled: int = _gen_property('cancelled')
    unknown_error: int = _gen_property('unknown_error')
    timeout_unknown_error: int = _gen_property('timeout_unknown_error')

    @staticmethod
    def _stat(counter: Mapping) -> str:
        return ', '.join(filter(None, (
            f'updated({counter["updated"]})',
            f'not updated({counter["not_updated"]}, including {counter["cached"]} cached and {counter["empty"]} empty)',
            f'fetch failed({counter["failed"]})' if counter["failed"] else '',
            f'skipped({counter["skipped"]})' if counter["skipped"] else '',
            f'timeout({counter["timeout"]})' if counter["timeout"] else '',
            f'cancelled({counter["cancelled"]})' if counter["cancelled"] else '',
            f'unknown error({counter["unknown_error"]})' if counter["unknown_error"] else '',
            f'timeout w/ unknown error({counter["timeout_unknown_error"]})' if counter["timeout_unknown_error"] else '',
        )))

    def __init__(self):
        self.print_summary()
        self.counter: MutableMapping[str, int] = Counter()
        self._token = object()
        self.Meta.task_in_progress.add(self._token)

    def __exit__(self, *args):
        meta = self.Meta
        try:
            meta.counter += self.counter
            level = logging.DEBUG
            if self.timeout or self.cancelled or self.unknown_error or self.timeout_unknown_error:
                level = logging.WARNING
            msg = f'Finished a monitoring task: {self._stat(self.counter)}'
            logger.log(level, msg)
        finally:
            meta.task_in_progress.discard(self._token)
            meta.task_stuck.discard(self._token)
            meta.task_finished.add(self._token)
            self.print_summary()

    @classmethod
    def print_summary(cls):
        meta = cls.Meta
        now = env.loop.time()
        time_diff = round(now - meta.last_summary_time)
        if time_diff < meta.summary_period:
            return
        logger.info(
            f'{len(meta.task_finished)} monitoring tasks finished in the past {time_diff}s'
            + (f', while {len(meta.task_in_progress)} are still in progress' if meta.task_in_progress else '') +
            f'. Subtask summary of finished tasks: {cls._stat(meta.counter)}'
        )
        if meta.task_stuck:
            logger.warning(
                f'{len(meta.task_stuck)} monitoring tasks are still in progress after >{time_diff}s, '
                'are they stuck?'
            )
        meta.last_summary_time = now
        meta.task_stuck |= meta.task_in_progress
        meta.task_in_progress.clear()
        meta.task_finished.clear()
        meta.counter.clear()
        gc.collect()


async def run_monitor_task():
    feed_id_to_monitor = db.effective_utils.EffectiveTasks.get_tasks()
    if not feed_id_to_monitor:
        return

    feeds = await db.Feed.filter(id__in=feed_id_to_monitor)

    logger.debug('Started a monitoring task.')
    wait_for = TIMEOUT

    with MonitoringStat() as stat:
        task_feed_map = {
            env.loop.create_task(__monitor(feed, stat)): feed
            for feed in feeds
        }
        done, pending = await asyncio.wait(task_feed_map.keys(), timeout=wait_for)

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError as e:
                stat.timeout += 1
                feed = task_feed_map[task]
                logger.error(f'Monitoring subtask timed out after {wait_for}s: {feed.link}', exc_info=e)
            except Exception as e:
                stat.timeout_unknown_error += 1
                feed = task_feed_map[task]
                logger.error(
                    f'Monitoring subtask timed out after {wait_for}s and caused an unknown error: {feed.link}',
                    exc_info=e
                )

        for task in done:
            try:
                await task
            except asyncio.CancelledError as e:
                stat.cancelled += 1
                feed = task_feed_map[task]
                logger.error(f'Monitoring subtask failed due to CancelledError: {feed.link}', exc_info=e)
            except Exception as e:
                stat.unknown_error += 1
                feed = task_feed_map[task]
                logger.error(f'Monitoring failed due to an unknown error: {feed.link}', exc_info=e)


def _defer_next_check_as_per_server_side_cache(wf: web.WebFeed) -> Optional[datetime]:
    wr = wf.web_response
    assert wr is not None
    expires = wr.expires
    now = wr.now

    # defer next check as per Cloudflare cache
    # https://developers.cloudflare.com/cache/concepts/cache-responses/
    # https://developers.cloudflare.com/cache/how-to/edge-browser-cache-ttl/
    if expires and wf.headers.get('cf-cache-status') in {'HIT', 'MISS', 'EXPIRED', 'REVALIDATED'} and expires > now:
        return expires

    # defer next check as per RSSHub TTL (or Cache-Control max-age)
    # only apply when TTL > 5min,
    # as it is the default value of RSSHub and disabling cache won't change it in some legacy versions
    rss_d = wf.rss_d
    if rss_d.feed.get('generator') == 'RSSHub' and (updated_str := rss_d.feed.get('updated')):
        ttl_in_minute_str: str = rss_d.feed.get('ttl', '')
        ttl_in_second = int(ttl_in_minute_str) * 60 if ttl_in_minute_str.isdecimal() else None
        if ttl_in_second is None:
            ttl_in_second = wr.max_age
        if ttl_in_second and ttl_in_second > 300:
            updated = web.utils.rfc_2822_8601_to_datetime(updated_str)
            if updated and (next_check_time := updated + timedelta(seconds=ttl_in_second)) > now:
                return next_check_time

    return None


async def __monitor(feed: db.Feed, stat: MonitoringStat) -> None:
    """
    Monitor the update of a feed.

    :param feed: Feed object to be monitored
    :return: None
    """
    now = datetime.now(timezone.utc)
    if feed.next_check_time and now < feed.next_check_time:
        stat.skipped += 1
        return  # skip this monitor task

    subs = await feed.subs.filter(state=1)
    if not subs:  # nobody has subbed it
        logger.warning(f'Feed {feed.id} ({feed.link}) has no active subscribers.')
        await inner.utils.update_interval(feed)
        stat.skipped += 1
        return

    if all(locks.user_flood_lock(sub.user_id).locked() for sub in subs):
        stat.skipped += 1
        return  # all subscribers are experiencing flood wait, skip this monitor task

    headers = {
        'If-Modified-Since': format_datetime(feed.last_modified or feed.updated_at)
    }
    if feed.etag:
        headers['If-None-Match'] = feed.etag

    wf = await web.feed_get(feed.link, headers=headers, verbose=False)
    rss_d = wf.rss_d

    no_error = True
    new_next_check_time: Optional[datetime] = None  # clear next_check_time by default
    feed_updated_fields = set()
    try:
        if wf.status == 304:  # cached
            logger.debug(f'Fetched (not updated, cached): {feed.link}')
            stat.not_updated += 1
            stat.cached += 1
            return

        if rss_d is None:  # error occurred
            no_error = False
            feed.error_count += 1
            feed_updated_fields.add('error_count')
            if feed.error_count % 20 == 0:  # error_count is always > 0
                logger.warning(f'Fetch failed ({feed.error_count}th retry, {wf.error}): {feed.link}')
            if feed.error_count >= 100:
                logger.error(f'Deactivated due to too many ({feed.error_count}) errors '
                             f'(current: {wf.error}): {feed.link}')
                await __deactivate_feed_and_notify_all(feed, subs, reason=wf.error)
                stat.failed += 1
                return
            if feed.error_count >= 10:  # too much error, defer next check
                interval = feed.interval or db.EffectiveOptions.default_interval
                if (next_check_interval := min(interval, 15) * min(feed.error_count // 10 + 1, 5)) > interval:
                    new_next_check_time = now + timedelta(minutes=next_check_interval)
            logger.debug(f'Fetched (failed, {feed.error_count}th retry, {wf.error}): {feed.link}')
            stat.failed += 1
            return

        wr = wf.web_response
        assert wr is not None
        wr.now = now

        if (etag := wr.etag) and etag != feed.etag:
            feed.etag = etag
            feed_updated_fields.add('etag')

        new_next_check_time = _defer_next_check_as_per_server_side_cache(wf)

        if not rss_d.entries:  # empty
            logger.debug(f'Fetched (not updated, empty): {feed.link}')
            stat.not_updated += 1
            stat.empty += 1
            return

        title = rss_d.feed.title
        title = html_space_stripper(title) if title else ''
        if title != feed.title:
            logger.debug(f'Feed title changed ({feed.title} -> {title}): {feed.link}')
            feed.title = title
            feed_updated_fields.add('title')

        new_hashes, updated_entries = inner.utils.calculate_update(feed.entry_hashes, rss_d.entries)
        updated_entries = tuple(updated_entries)

        if not updated_entries:  # not updated
            logger.debug(f'Fetched (not updated): {feed.link}')
            stat.not_updated += 1
            return

        logger.debug(f'Updated: {feed.link}')
        feed.last_modified = wr.last_modified
        feed.entry_hashes = list(islice(new_hashes, max(len(rss_d.entries) * 2, 100))) or None
        feed_updated_fields.update({'last_modified', 'entry_hashes'})
    finally:
        if no_error:
            if feed.error_count > 0:
                feed.error_count = 0
                feed_updated_fields.add('error_count')
            if wf.url != feed.link:
                new_url_feed = await inner.sub.migrate_to_new_url(feed, wf.url)
                feed = new_url_feed if isinstance(new_url_feed, db.Feed) else feed

        if new_next_check_time != feed.next_check_time:
            feed.next_check_time = new_next_check_time
            feed_updated_fields.add('next_check_time')

        if feed_updated_fields:
            await feed.save(update_fields=feed_updated_fields)

    await asyncio.gather(*(__notify_all(feed, subs, entry) for entry in reversed(updated_entries)))
    stat.updated += 1
    return


async def __notify_all(feed: db.Feed, subs: Iterable[db.Sub], entry: MutableMapping):
    link = entry.get('link')
    try:
        post = await get_post_from_entry(entry, feed.title, feed.link)
    except Exception as e:
        logger.error(f'Failed to parse the post {link} (feed: {feed.link}) from entry:', exc_info=e)
        try:
            error_message = Post(f'Something went wrong while parsing the post {link} '
                                 f'(feed: {feed.link}). '
                                 f'Please check:<br><br>' +
                                 format_exc().replace('\n', '<br>'),
                                 feed_title=feed.title, link=link)
            await error_message.send_formatted_post(env.ERROR_LOGGING_CHAT, send_mode=2)
        except Exception as e:
            logger.error(f'Failed to send parsing error message for {link} (feed: {feed.link}):', exc_info=e)
            await env.bot.send_message(env.ERROR_LOGGING_CHAT,
                                       'A parsing error message cannot be sent, please check the logs.')
        return
    res = await asyncio.gather(
        *(asyncio.wait_for(__send(sub, post), 8.5 * 60) for sub in subs),
        return_exceptions=True
    )
    for sub, exc in zip(subs, res):
        if not isinstance(exc, Exception):
            continue
        if not isinstance(exc, asyncio.TimeoutError):  # should not happen, but just in case
            raise exc
        logger.error(f'Failed to send {post.link} (feed: {post.feed_link}, user: {sub.user_id}) due to timeout')


async def __send(sub: db.Sub, post: Union[str, Post]):
    user_id = sub.user_id
    try:
        try:
            await env.bot.get_input_entity(user_id)  # verify that the input entity can be gotten first
        except ValueError:  # cannot get the input entity, the user may have banned the bot
            return await __locked_unsub_all_and_leave_chat(user_id=user_id, err_msg=type(EntityNotFoundError).__name__)
        try:
            if isinstance(post, str):
                await env.bot.send_message(user_id, post, parse_mode='html', silent=not sub.notify)
                return
            await post.send_formatted_post_according_to_sub(sub)
            if __user_blocked_counter[user_id]:  # reset the counter if success
                del __user_blocked_counter[user_id]
        except UserBlockedErrors as e:
            return await __locked_unsub_all_and_leave_chat(user_id=user_id, err_msg=type(e).__name__)
        except BadRequestError as e:
            if e.message == 'TOPIC_CLOSED':
                return await __locked_unsub_all_and_leave_chat(user_id=user_id, err_msg=e.message)
    except Exception as e:
        logger.error(f'Failed to send {post.link} (feed: {post.feed_link}, user: {sub.user_id}):', exc_info=e)
        try:
            error_message = Post('Something went wrong while sending this post '
                                 f'(feed: {post.feed_link}, user: {sub.user_id}). '
                                 'Please check:<br><br>' +
                                 format_exc().replace('\n', '<br>'),
                                 title=post.title, feed_title=post.feed_title, link=post.link, author=post.author,
                                 feed_link=post.feed_link)
            await error_message.send_formatted_post(env.ERROR_LOGGING_CHAT, send_mode=2)
        except Exception as e:
            logger.error(f'Failed to send sending error message for {post.link} '
                         f'(feed: {post.feed_link}, user: {sub.user_id}):',
                         exc_info=e)
            await env.bot.send_message(env.ERROR_LOGGING_CHAT,
                                       'An sending error message cannot be sent, please check the logs.')


async def __locked_unsub_all_and_leave_chat(user_id: int, err_msg: str):
    user_unsub_all_lock = __user_unsub_all_lock_bucket[user_id]
    if user_unsub_all_lock.locked():
        return  # no need to unsub twice!
    async with user_unsub_all_lock:
        if __user_blocked_counter[user_id] < 5:
            __user_blocked_counter[user_id] += 1
            return  # skip once
        # fail for 5 times, consider been banned
        del __user_blocked_counter[user_id]
        logger.error(f'User blocked ({err_msg}): {user_id}')
        await unsub_all_and_leave_chat(user_id)


async def __deactivate_feed_and_notify_all(feed: db.Feed,
                                           subs: Iterable[db.Sub],
                                           reason: Union[web.WebError, str] = None):
    await inner.utils.deactivate_feed(feed)

    if not subs:  # nobody has subbed it or no active sub exists
        return

    langs: tuple[str, ...] = await asyncio.gather(
        *(sub.user.get_or_none().values_list('lang', flat=True) for sub in subs)
    )

    await asyncio.gather(
        *(
            __send(
                sub=sub,
                post=(
                        f'<a href="{feed.link}">{escape_html(sub.title or feed.title)}</a>\n'
                        + i18n[lang]['feed_deactivated_warn']
                        + (
                            f'\n{reason.i18n_message(lang) if isinstance(reason, web.WebError) else reason}'
                            if reason else ''
                        )
                )
            )
            for sub, lang in (zip(subs, langs))
        )
    )
