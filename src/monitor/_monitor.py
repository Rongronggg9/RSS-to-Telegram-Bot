#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from typing import Union, Optional, Final
from collections.abc import Iterable

import enum
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from collections import defaultdict
from itertools import islice, chain, repeat

from ._common import logger, TIMEOUT
from ._notifier import Notifier
from ._stat import MonitorStat
from .. import db, env, web, locks
from ..command import inner
from ..helpers.bg import bg
from ..helpers.singleton import Singleton
from ..helpers.timeout import BatchTimeout
from ..parsing.utils import ensure_plain


class TaskState(enum.IntFlag):
    EMPTY = 0
    LOCKED = 1 << 0
    IN_PROGRESS = 1 << 1
    DEFERRED = 1 << 2


FEED_OR_ID = Union[int, db.Feed]


class Monitor(Singleton):
    def __init__(self):
        self._stat: Final[MonitorStat] = MonitorStat()
        self._bg_task: Optional[asyncio.Task] = None
        # Synchronous operations are atomic from the perspective of asynchronous coroutines, so we can just use a map
        # plus additional prologue & epilogue to simulate an asynchronous lock.
        # In the meantime, the deferring logic is implemented using this map.
        self._subtask_defer_map: Final[defaultdict[int, TaskState]] = defaultdict(lambda: TaskState.EMPTY)
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

    async def _ensure_db_feeds(self, feeds: Iterable[FEED_OR_ID]) -> Optional[set[db.Feed]]:
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

    # In the foreseeable future, we may limit the number of concurrent monitoring tasks and use
    # helpers.queue.QueuedDecorator(PriorityQueue) to prioritize some jobs.
    # Since the execution of monitoring tasks is completely unlimited now, we can use the simpler `bg` decorator to
    # avoid the extra overhead of `queued`.
    @bg
    async def _do_monitor_task(self, feeds: Iterable[FEED_OR_ID], description: str):
        # Previously, this was a tail call (self._ensure_db_feeds() calls self._do_monitor_task() at the end).
        # It turned out that the tail call made the frame of self._ensure_db_feeds(), which keep referencing all db.Feed
        # objects produced there, persisted until self._do_monitor_task() was done.
        # The garbage collector was unable to collect any db.Feed objects in such a circumstance.
        # So it is now a head call to solve this issue.
        feeds: set[db.Feed] = await self._ensure_db_feeds(feeds)
        if not feeds:
            return

        feed_count = len(feeds)
        handle_id = id(feeds)
        logger.debug(f'Start monitoring {feed_count} feeds (handle: {handle_id}): {description}')

        _do_monitor_subtask: BatchTimeout[[db.Feed], None]
        async with BatchTimeout[[db.Feed], None](
                func=self._do_monitor_subtask,
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
            del feed, feeds

        logger.debug(f'Finished monitoring {feed_count} feeds (handle: {handle_id}): {description}')

    _do_monitor_task_bg_sync = _do_monitor_task.bg_sync

    async def _do_monitor_subtask(self, feed: db.Feed):
        self._subtask_defer_map[feed.id] |= TaskState.IN_PROGRESS
        self._stat.start()
        try:
            await self._do_monitor_a_feed(feed)
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
            self.submit_feed(feed_id, 'resubmit deferred subtask')
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

    def submit_feeds(self, feeds: Iterable[FEED_OR_ID], description: str = ''):
        self._do_monitor_task_bg_sync(feeds, description)

    def submit_feed(self, feed: FEED_OR_ID, description: str = ''):
        self.submit_feeds((feed,), description)

    async def run_periodic_task(self):
        self._stat.print_summary()
        Notifier.on_periodic_task()
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
            env.loop.call_later(delay, self.submit_feeds, feed_ids[pos:pos + count], 'periodic task')
            pos += count
        assert pos == feed_count

    async def _do_monitor_a_feed(self, feed: db.Feed):
        """
        Monitor the update of a feed.

        :param feed: Feed object to be monitored
        :return: None
        """
        stat = self._stat
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
                    await Notifier(feed=feed, subs=subs, reason=wf.error).notify_all()
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
            title = await ensure_plain(title) if title else ''
            if title != feed.title:
                logger.debug(f'Feed title changed ({feed.title} -> {title}): {feed.link}')
                feed.title = title
                feed_updated_fields.add('title')

            new_hashes, updated_entries = inner.utils.calculate_update(feed.entry_hashes, rss_d.entries)
            updated_entries = list(updated_entries)

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

        updated_entries.reverse()  # send the earliest entry first
        await Notifier(feed=feed, subs=subs, entries=updated_entries).notify_all()
        stat.updated()
        return


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
