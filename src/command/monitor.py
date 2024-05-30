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

        tier1_time_diff = round(now - self._tier1_last_summary_time)
        if tier1_time_diff < self._tier1_summary_period:
            return
        self._summarize(self._counter_tier1, logging.INFO, tier1_time_diff)
        self._tier1_last_summary_time = now
        self._counter_tier1.clear()
        gc.collect()


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
        # In the foreseeable future, we may use a PriorityQueue here to prioritize some jobs
        # It is an unbounded queue, so we can just use {put,get}_nowait() anywhere.
        # For now, there is no need to use a bounded queue since all items are consumed immediately.
        self._queue: asyncio.Queue[Iterable[FEED_OR_ID]] = asyncio.Queue()
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

    async def init(self):
        if self._bg_task is not None and not self._bg_task.done():
            return
        self._bg_task = env.loop.create_task(
            self._bg_queue_consumer(),
            name='Monitor-bg-task'
        )

    async def close(self):
        # This won't cancel _do_monitor_task() tasks,
        # but that's fine since asyncio will cancel them and print traceback when exiting.
        if self._bg_task is not None and not self._bg_task.done():
            try:
                cancelled = self._bg_task.cancel()
            except Exception as e:
                logger.error("Failed to terminate Monitor's background task of :", exc_info=e)
                return  # cannot cancel the task, just return
            if cancelled:
                return
            try:
                await self._bg_task
            except Exception as e:
                logger.error("Traceback of Monitor's background task termination:", exc_info=e)

    async def _bg_queue_consumer(self):
        while True:
            # Consumes the queue immediately without blocking.
            # Here we don't use get_nowait since we do want to wait for the next feed to be submitted.
            feed = await self._queue.get()
            env.loop.create_task(
                self._do_monitor_task(feed),
                name=f'Monitor-task-{env.loop.time()}'
            )

    async def _do_monitor_task(self, feeds: Iterable[FEED_OR_ID]):
        if not feeds:
            return

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

        if db_feeds:
            await self._do_monitor_task_ensure_db_feeds(db_feeds)

    async def _do_monitor_task_ensure_db_feeds(self, feeds: Iterable[db.Feed]):
        # A technique to solve these three issues:
        # 1. asyncio.timeout/wait_for() raises TimeoutError from CancelledError, which breaks some internal logic of
        # aiohttp, so we have to prevent TimeoutError from being raised in such a circumstance.
        # 2. It is hard to distinguish TimeoutError raised by asyncio.timeout/wait_for() from the one raised by other
        # routines.
        # 3. The previously used `asyncio.wait()` technique pends tasks for TIMEOUT seconds, even if some tasks have
        # long been done, which is inefficient and causes memory leak until the timeout is reached.
        #
        # The technique itself is, however, quite straightforward:
        # 1. Create a queue to store done tasks.
        # 2. Make each task put itself into the queue once it is done.
        # 3. Create a timeout handle to put None into the queue after TIMEOUT seconds.
        # 4. Consume the queue until None is put into it.
        # 5. Cancel all remaining tasks.
        done: asyncio.Queue[Optional[asyncio.Task]] = asyncio.Queue()  # unbounded, safe to use `{put,get}_nowait()`
        timeout_handle = env.loop.call_later(TIMEOUT, done.put_nowait, None)  # use None to indicate timeout
        timed_out = False

        # Put the task into the done queue once it is done (if not timed out).
        def _on_done(t: asyncio.Task):
            if not timed_out:
                done.put_nowait(t)

        subtask_feed_map: dict[asyncio.Task: db.Feed] = {}
        for feed in feeds:
            self._lock_feed_id(feed.id)
            subtask = env.loop.create_task(
                self._do_monitor_subtask(feed),
                name=f'Monitor-subtask-{env.loop.time()}-{feed.id}'
            )
            subtask.add_done_callback(_on_done)
            subtask_feed_map[subtask] = feed

        while subtask_feed_map:
            subtask = await done.get()  # wait for the next subtask to be done
            if subtask is None:
                timed_out = True
                break
            feed = subtask_feed_map.pop(subtask)  # pop the subtask and retrieve the feed
            try:
                # Here we use `await subtask` instead of `subtask.exception()` due to:
                # 1. The divergence that Future.exception() **returns** exception or None if done but **raises**
                # CancelledError if canceled causes huge inconvenience.
                # 2. Ensure the traceback is complete.
                await subtask
            except asyncio.CancelledError as e:
                # Usually, this should not happen, but let's handle it for debugging purposes and prevent it from
                # breaking the whole monitoring task.
                self._stat.cancelled()
                logger.error(f'Monitoring subtask failed due to CancelledError: {feed.link}', exc_info=e)
            except Exception as e:
                self._stat.unknown_error()
                logger.error(f'Monitoring subtask failed due to an unknown error: {feed.link}', exc_info=e)

        timeout_handle.cancel()
        if not timed_out:
            return

        for subtask in subtask_feed_map:
            # Cancel all remaining subtasks together before awaiting any of them to ensure timely cancellation.
            subtask.cancel()
            # There is a chance that some subtasks are done right after the timeout_handle.
            # In such a case, these subtasks will not be canceled (cancelling a done task is a no-op)...

        for subtask, feed in subtask_feed_map.items():
            try:
                # ...It may succeed...
                await subtask
            except asyncio.CancelledError as e:
                self._stat.timeout()
                logger.error(f'Monitoring subtask timed out after {TIMEOUT}s: {feed.link}', exc_info=e)
            except Exception as e:
                # ...or fail.
                self._stat.timeout_unknown_error()
                logger.error(
                    f'Monitoring subtask timed out after {TIMEOUT}s and caused an unknown error: {feed.link}',
                    exc_info=e
                )

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
        self._queue.put_nowait(feeds)

    def submit_feed(self, feed: FEED_OR_ID):
        self.submit_feeds((feed,))

    async def run_periodic_task(self):
        self._stat.print_summary()
        feed_ids_to_monitor = db.effective_utils.EffectiveTasks.get_tasks()
        if not feed_ids_to_monitor:
            return

        self.submit_feeds(feed_ids_to_monitor)

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
