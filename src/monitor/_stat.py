from __future__ import annotations
from typing import Optional

import gc
import logging
from collections import Counter

from ._common import logger, TIMEOUT
from .. import env


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
