from __future__ import annotations
from typing import Union, Final, Optional, ClassVar
from collections.abc import MutableMapping, Iterable

import enum
import gc
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from collections import defaultdict, Counter
from itertools import islice, chain, repeat
from traceback import format_exc
from telethon.errors import BadRequestError

from . import inner
from .utils import escape_html, unsub_all_and_leave_chat
from .. import log, db, env, web, locks
from ..helpers.queue import queued
from ..helpers.timeout import BatchTimeout
from ..errors_collection import EntityNotFoundError, UserBlockedErrors
from ..i18n import i18n
from ..parsing.post import get_post_from_entry, Post
from ..parsing.utils import html_space_stripper

logger = log.getLogger('RSStT.monitor')

TIMEOUT: Final[int] = 10 * 60  # 10 minutes

# it may cause memory leak, but they are too small that leaking thousands of that is still not a big deal!
__user_unsub_all_lock_bucket: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
__user_blocked_counter = Counter()


# TODO: move inside MonitoringCounter once the minimum Python requirement is 3.10
# @staticmethod
def _gen_property(key: str):
    def getter(self):
        return self[key]

    def setter(self, value):
        self[key] = value

    return property(getter, setter)


class MonitoringCounter(Counter[str, int]):
    FINISHED: int = _gen_property('FINISHED')

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
    deferred: int = _gen_property('deferred')
    resubmitted: int = _gen_property('resubmitted')


class MonitoringStat:
    def __init__(self):
        self._counter_tier1: MonitoringCounter = MonitoringCounter()  # periodical summary
        self._counter_tier2: MonitoringCounter = MonitoringCounter()  # unconditional summary
        self._tier1_last_summary_time: Optional[float] = None
        self._tier2_last_summary_time: Optional[float] = self._tier1_last_summary_time
        self._tier1_summary_period: float = TIMEOUT  # seconds
        # No need to set _tier2_summary_period since _counter_tier2 is unconditionally summarized in print_summary.
        self._in_progress_count: int = 0

    def not_updated(self):
        self._counter_tier2['not_updated'] += 1

    def cached(self):
        self._counter_tier2['cached'] += 1
        self.not_updated()

    def empty(self):
        self._counter_tier2['empty'] += 1
        self.not_updated()

    def failed(self):
        self._counter_tier2['failed'] += 1

    def updated(self):
        self._counter_tier2['updated'] += 1

    def skipped(self):
        self._counter_tier2['skipped'] += 1

    def timeout(self):
        self._counter_tier2['timeout'] += 1

    def cancelled(self):
        self._counter_tier2['cancelled'] += 1

    def unknown_error(self):
        self._counter_tier2['unknown_error'] += 1

    def timeout_unknown_error(self):
        self._counter_tier2['timeout_unknown_error'] += 1

    def deferred(self):
        self._counter_tier2['deferred'] += 1

    def resubmitted(self):
        self._counter_tier2['resubmitted'] += 1

    def start(self):
        self._in_progress_count += 1

    def finish(self):
        self._in_progress_count -= 1
        self._counter_tier2['FINISHED'] += 1

    def _stat(self, counter: MonitoringCounter) -> str:
        scheduling_stat = ', '.join(filter(None, (
            f'in progress({self._in_progress_count})' if self._in_progress_count else '',
            f'deferred({counter.deferred})' if counter.deferred else '',
            f'resubmitted({counter.resubmitted})' if counter.resubmitted else '',
        )))
        if not counter.FINISHED:
            return scheduling_stat
        finished_stat = f'finished({counter.FINISHED}). Details of finished subtasks: ' + ', '.join(filter(None, (
            f'updated({counter.updated})' if counter.updated else '',
            f'not updated({counter.not_updated}, including {counter.cached} cached and {counter.empty} empty)'
            if counter.not_updated
            else '',
            f'fetch failed({counter.failed})' if counter.failed else '',
            f'skipped({counter.skipped})' if counter.skipped else '',
            f'cancelled({counter.cancelled})' if counter.cancelled else '',
            f'unknown error({counter.unknown_error})' if counter.unknown_error else '',
            f'timeout({counter.timeout})' if counter.timeout else '',
            f'timeout w/ unknown error({counter.timeout_unknown_error})' if counter.timeout_unknown_error else '',
        )))
        return ', '.join(filter(None, (scheduling_stat, finished_stat)))

    def _summarize(self, counter: MonitoringCounter, default_log_level: int, time_diff: int):
        stat = self._stat(counter) or 'nothing was submitted'
        logger.log(
            logging.WARNING
            if counter.cancelled or counter.unknown_error or counter.timeout or counter.timeout_unknown_error
            else default_log_level,
            f'Summary of monitoring subtasks in the past {time_diff}s: {stat}.'
        )

    def print_summary(self):
        now = env.loop.time()

        if self._tier1_last_summary_time is None:
            self._tier1_last_summary_time = now
            self._tier2_last_summary_time = now
            return

        if self._in_progress_count < 0:
            logger.error(f'Unexpected negative in-progress count ({self._in_progress_count})')

        tier2_time_diff = round(now - self._tier2_last_summary_time)
        self._summarize(self._counter_tier2, logging.DEBUG, tier2_time_diff)
        self._tier2_last_summary_time = now
        self._counter_tier1 += self._counter_tier2
        self._counter_tier2.clear()
        gc.collect()

        tier1_time_diff = round(now - self._tier1_last_summary_time)
        if tier1_time_diff < self._tier1_summary_period:
            return
        self._summarize(self._counter_tier1, logging.INFO, tier1_time_diff)
        self._tier1_last_summary_time = now
        self._counter_tier1.clear()


class TaskState(enum.IntFlag):
    EMPTY = 0
    LOCKED = 1 << 0
    IN_PROGRESS = 1 << 1
    DEFERRED = 1 << 2


FEED_OR_ID = Union[int, db.Feed]


class Monitor:
    _singleton: ClassVar[Monitor] = None

    def __new__(cls, *args, **kwargs):
        if cls._singleton is None:
            return object.__new__(cls)
        raise RuntimeError('A singleton instance already exists, use get_instance() instead.')

    @classmethod
    def get_instance(cls):
        if cls._singleton is None:
            cls._singleton = cls()  # implicitly calls __new__ then __init__
        return cls._singleton

    def __init__(self):
        self._stat = MonitoringStat()
        self._bg_task: Optional[asyncio.Task] = None
        # Synchronous operations are atomic from the perspective of asynchronous coroutines, so we can just use a map
        # plus additional prologue & epilogue to simulate an asynchronous lock.
        # In the meantime, the deferring logic is implemented using this map.
        self._subtask_defer_map: defaultdict[int, TaskState] = defaultdict(lambda: TaskState.EMPTY)
        self._lock_up_period: int = 0  # in seconds

        # update _lock_up_period on demand
        db.effective_utils.EffectiveOptions.add_set_callback('minimal_interval', self._update_lock_up_period_cb)

    def _update_lock_up_period_cb(self, key: str, value: int, expected_key: str = 'minimal_interval'):
        if key != expected_key:
            raise KeyError(f'Invalid key: {key}, expected: {expected_key}')
        if not isinstance(value, int):
            raise TypeError(f'Invalid type of value: {type(value)}, expected: int')
        if value <= 1:
            # The minimal scheduling interval is 1 minute, it is meaningless to lock.
            self._lock_up_period = 0  # which means locks are disabled
            return
        # Convert minutes to seconds, then subtract 10 seconds to prevent locks from being released too late
        # (i.e., released only after causing a new subtask being deferred).
        self._lock_up_period = value * 60 - 10

    async def _ensure_db_feeds(self, feeds: Iterable[FEED_OR_ID]) -> Optional[Iterable[db.Feed]]:
        if not feeds:
            return None

        db_feeds: set[db.Feed] = set()
        feed_ids: set[int] = set()
        for feed in feeds:
            if isinstance(feed, db.Feed):
                if not self._defer_feed_id(feed.id, feed.link):
                    db_feeds.add(feed)
            else:
                feed_id = feed
                if not self._defer_feed_id(feed_id):
                    feed_ids.add(feed_id)
        if feed_ids:
            db_feeds_to_merge = await db.Feed.filter(id__in=feed_ids)
            db_feeds.update(db_feeds_to_merge)
            if len(db_feeds_to_merge) != len(feed_ids):
                feed_ids_not_found = feed_ids - {feed.id for feed in db_feeds_to_merge}
                logger.error(f'Feeds {feed_ids_not_found} not found, but they were submitted to the monitor queue.')

        return db_feeds

    def _on_subtask_canceled(self, err: BaseException, feed: db.Feed):
        self._stat.cancelled()
        logger.error(f'Monitoring subtask failed due to CancelledError: {feed.id}: {feed.link}', exc_info=err)

    def _on_subtask_unknown_error(self, err: BaseException, feed: db.Feed):
        self._stat.unknown_error()
        logger.error(f'Monitoring subtask failed due to an unknown error: {feed.id}: {feed.link}', exc_info=err)

    def _on_subtask_timeout(self, err: BaseException, feed: db.Feed):
        self._stat.timeout()
        logger.error(f'Monitoring subtask timed out after {TIMEOUT}s: {feed.id}: {feed.link}', exc_info=err)

    def _on_subtask_timeout_unknown_error(self, err: BaseException, feed: db.Feed):
        self._stat.timeout_unknown_error()
        logger.error(
            f'Monitoring subtask timed out after {TIMEOUT}s and caused an unknown error: {feed.id}: {feed.link}',
            exc_info=err
        )

    # In the foreseeable future, we may use a PriorityQueue here to prioritize some jobs.
    @queued
    async def _do_monitor_task(self, feeds: Iterable[FEED_OR_ID]):
        # Previously, this was a tail call (self._ensure_db_feeds() calls self._do_monitor_task() at the end).
        # It turned out that the tail call made the frame of self._ensure_db_feeds(), which keep referencing all db.Feed
        # objects produced there, persisted until self._do_monitor_task() was done.
        # The garbage collector was unable to collect any db.Feed objects in such a circumstance.
        # So it is now a head call to solve this issue.
        feeds: Iterable[db.Feed] = await self._ensure_db_feeds(feeds)
        if not feeds:
            return

        _do_monitor_subtask: BatchTimeout[db.Feed, None]
        async with BatchTimeout(
                self._do_monitor_subtask,
                timeout=TIMEOUT,
                loop=env.loop,
                on_canceled=self._on_subtask_canceled,
                on_error=self._on_subtask_unknown_error,
                on_timeout=self._on_subtask_timeout,
                on_timeout_error=self._on_subtask_timeout_unknown_error,
        ) as _do_monitor_subtask:
            for feed in feeds:
                self._lock_feed_id(feed.id)
                _do_monitor_subtask(feed, _task_name_suffix=feed.id)
            # Release unnecessary references to db.Feed objects so that they can be garbage collected later.
            del feeds

    _do_monitor_task_queued_nowait = _do_monitor_task.queued_nowait

    async def _do_monitor_subtask(self, feed: db.Feed):
        self._subtask_defer_map[feed.id] |= TaskState.IN_PROGRESS
        self._stat.start()
        try:
            await _do_monitor_a_feed(feed, self._stat)
        finally:
            self._erase_state_for_feed_id(feed.id, TaskState.IN_PROGRESS)
            self._stat.finish()

    def _lock_feed_id(self, feed_id: int):
        if not self._lock_up_period:  # lock disabled
            return
        # Caller MUST ensure that self._subtask_defer_map[feed_id] can be overwritten safely.
        self._subtask_defer_map[feed_id] = TaskState.LOCKED
        # unlock after the lock-up period
        env.loop.call_later(
            self._lock_up_period,
            self._erase_state_for_feed_id,
            feed_id, TaskState.LOCKED
        )

    def _erase_state_for_feed_id(self, feed_id: int, flag_to_erase: TaskState):
        task_state = self._subtask_defer_map[feed_id]
        if not task_state:
            logger.warning(f'Unexpected empty state ({repr(task_state)}): {feed_id}')
            return
        erased_state = task_state & ~flag_to_erase
        if erased_state == TaskState.DEFERRED:  # deferred with any other flag erased, resubmit it
            self._subtask_defer_map[feed_id] = TaskState.EMPTY
            self.submit_feed(feed_id)
            self._stat.resubmitted()
            logger.debug(f'Resubmitted a deferred subtask ({repr(task_state)}): {feed_id}')
            return
        self._subtask_defer_map[feed_id] = erased_state  # update the state

    def _defer_feed_id(self, feed_id: int, feed_link: str = None) -> bool:
        feed_description = f'{feed_id}: {feed_link}' if feed_link else str(feed_id)
        task_state = self._subtask_defer_map[feed_id]
        if task_state == TaskState.DEFERRED:
            # This should not happen, but just in case.
            logger.warning(f'A deferred subtask ({repr(task_state)}) was never resubmitted: {feed_description}')
            # fall through
        elif task_state:  # defer if any other flag is set
            # Set the DEFERRED flag, this can be done for multiple times safely.
            self._subtask_defer_map[feed_id] = task_state | TaskState.DEFERRED
            self._stat.deferred()
            logger.debug(f'Deferred ({repr(task_state)}): {feed_description}')
            return True  # deferred, later operations should be skipped
        return False  # not deferred

    def submit_feeds(self, feeds: Iterable[FEED_OR_ID]):
        self._do_monitor_task_queued_nowait(feeds)

    def submit_feed(self, feed: FEED_OR_ID):
        self.submit_feeds((feed,))

    async def run_periodic_task(self):
        self._stat.print_summary()
        feed_ids_set = db.effective_utils.EffectiveTasks.get_tasks()
        if not feed_ids_set:
            return

        # Assuming the method is called once per minute, let's divide feed_ids into 60 chunks and submit one by one
        # every second.
        feed_ids: list[int] = list(feed_ids_set)
        feed_count = len(feed_ids)
        chunk_count = 60
        larger_chunk_count = feed_count % chunk_count
        smaller_chunk_size = feed_count // chunk_count
        smaller_chunk_count = chunk_count - larger_chunk_count
        larger_chunk_size = smaller_chunk_size + 1
        pos = 0
        for delay, count in enumerate(chain(
                repeat(larger_chunk_size, larger_chunk_count),
                repeat(smaller_chunk_size, smaller_chunk_count)
        )):
            if count == 0:
                break
            env.loop.call_later(delay, self.submit_feeds, feed_ids[pos:pos + count])
            pos += count
        assert pos == feed_count

        logger.debug('Started a periodic monitoring task.')


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


async def _do_monitor_a_feed(feed: db.Feed, stat: MonitoringStat):
    """
    Monitor the update of a feed.

    :param feed: Feed object to be monitored
    :return: None
    """
    now = datetime.now(timezone.utc)
    if feed.next_check_time and now < feed.next_check_time:
        stat.skipped()
        return  # skip this monitor task

    subs = await feed.subs.filter(state=1)
    if not subs:  # nobody has subbed it
        logger.warning(f'Feed {feed.id} ({feed.link}) has no active subscribers.')
        await inner.utils.update_interval(feed)
        stat.skipped()
        return

    if all(locks.user_flood_lock(sub.user_id).locked() for sub in subs):
        stat.skipped()
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
            stat.cached()
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
                stat.failed()
                return
            if feed.error_count >= 10:  # too much error, defer next check
                interval = feed.interval or db.EffectiveOptions.default_interval
                if (next_check_interval := min(interval, 15) * min(feed.error_count // 10 + 1, 5)) > interval:
                    new_next_check_time = now + timedelta(minutes=next_check_interval)
            logger.debug(f'Fetched (failed, {feed.error_count}th retry, {wf.error}): {feed.link}')
            stat.failed()
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
            stat.empty()
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
            stat.not_updated()
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
    stat.updated()
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
