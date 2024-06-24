from __future__ import annotations
from typing import Optional, ClassVar, TypeVar, Generic

import gc
import logging
from abc import ABC, abstractmethod
from collections import Counter

from ._common import logger, TIMEOUT
from .. import env


def _gen_property(key: str):
    def getter(self):
        return self[key]

    def setter(self, value):
        self[key] = value

    return property(getter, setter)


class StatCounter(Counter[str, int]):
    FINISHED: int = _gen_property('FINISHED')

    timeout: int = _gen_property('timeout')
    cancelled: int = _gen_property('cancelled')
    unknown_error: int = _gen_property('unknown_error')
    timeout_unknown_error: int = _gen_property('timeout_unknown_error')


SC = TypeVar('SC', bound=StatCounter)


class Stat(ABC, Generic[SC]):
    _do_gc_after_summarizing_tier2: ClassVar[bool] = False

    def __init__(self, _bound_counter_cls: type[SC] = StatCounter):
        self._bound_counter_cls = _bound_counter_cls

        self._counter_tier1: SC = self._bound_counter_cls()  # periodical summary
        self._counter_tier2: SC = self._bound_counter_cls()  # unconditional summary
        self._tier1_last_summary_time: Optional[float] = None
        self._tier2_last_summary_time: Optional[float] = self._tier1_last_summary_time
        self._tier1_summary_period: float = float(TIMEOUT)  # seconds
        # No need to set _tier2_summary_period since _counter_tier2 is unconditionally summarized in print_summary.
        self._in_progress_count: int = 0

    def start(self):
        self._in_progress_count += 1

    def finish(self):
        self._in_progress_count -= 1
        self._counter_tier2['FINISHED'] += 1

    def timeout(self):
        self._counter_tier2['timeout'] += 1

    def cancelled(self):
        self._counter_tier2['cancelled'] += 1

    def unknown_error(self):
        self._counter_tier2['unknown_error'] += 1

    def timeout_unknown_error(self):
        self._counter_tier2['timeout_unknown_error'] += 1

    def _describe_in_progress(self) -> str:
        return f'in progress({self._in_progress_count})' if self._in_progress_count else ''

    @staticmethod
    def _describe_abnormal(counter: SC) -> str:
        return ', '.join(filter(None, (
            f'cancelled({counter.cancelled})' if counter.cancelled else '',
            f'unknown error({counter.unknown_error})' if counter.unknown_error else '',
            f'timeout({counter.timeout})' if counter.timeout else '',
            f'timeout w/ unknown error({counter.timeout_unknown_error})' if counter.timeout_unknown_error else '',
        )))

    @abstractmethod
    def _stat(self, counter: SC) -> str:
        pass

    def _summarize(self, counter: MC, default_log_level: int, time_diff: int):
        stat = self._stat(counter) or 'nothing was submitted'
        logger.log(
            logging.WARNING
            if counter.cancelled or counter.unknown_error or counter.timeout or counter.timeout_unknown_error
            else default_log_level,
            f'Summary of {self.__class__.__name__} in the past {time_diff}s: {stat}.'
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
        if self._do_gc_after_summarizing_tier2:
            gc.collect()

        tier1_time_diff = round(now - self._tier1_last_summary_time)
        if tier1_time_diff < self._tier1_summary_period:
            return
        self._summarize(self._counter_tier1, logging.INFO, tier1_time_diff)
        self._tier1_last_summary_time = now
        self._counter_tier1.clear()


class MonitorCounter(StatCounter):
    not_updated: int = _gen_property('not_updated')
    cached: int = _gen_property('cached')
    empty: int = _gen_property('empty')
    failed: int = _gen_property('failed')
    updated: int = _gen_property('updated')
    skipped: int = _gen_property('skipped')
    deferred: int = _gen_property('deferred')
    resubmitted: int = _gen_property('resubmitted')


MC = TypeVar('MC', bound=MonitorCounter)


class MonitorStat(Stat[MC]):
    _do_gc_after_summarizing_tier2 = True

    def __init__(self, _bound_counter_cls: type[MC] = MonitorCounter):
        super().__init__(_bound_counter_cls=_bound_counter_cls)

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

    def deferred(self):
        self._counter_tier2['deferred'] += 1

    def resubmitted(self):
        self._counter_tier2['resubmitted'] += 1

    def _stat(self, counter: MC) -> str:
        scheduling_stat = ', '.join(filter(None, (
            self._describe_in_progress(),
            f'deferred({counter.deferred})' if counter.deferred else '',
            f'resubmitted({counter.resubmitted})' if counter.resubmitted else '',
        )))
        if not counter.FINISHED:
            return scheduling_stat
        finished_stat = f'finished({counter.FINISHED}). Details of finished: ' + ', '.join(filter(None, (
            f'updated({counter.updated})' if counter.updated else '',
            f'not updated({counter.not_updated}, including {counter.cached} cached and {counter.empty} empty)'
            if counter.not_updated
            else '',
            f'fetch failed({counter.failed})' if counter.failed else '',
            f'skipped({counter.skipped})' if counter.skipped else '',
            self._describe_abnormal(counter),
        )))
        return ', '.join(filter(None, (scheduling_stat, finished_stat)))


class NotifierCounter(StatCounter):
    notified: int = _gen_property('notified')
    deactivated: int = _gen_property('deactivated')


NC = TypeVar('NC', bound=NotifierCounter)


class NotifierStat(Stat[NC]):
    def __init__(self, _bound_counter_cls: type[NC] = NotifierCounter):
        super().__init__(_bound_counter_cls=_bound_counter_cls)

    def notified(self):
        self._counter_tier2['notified'] += 1

    def deactivated(self):
        self._counter_tier2['deactivated'] += 1

    def _stat(self, counter: NC) -> str:
        return ', '.join(filter(None, (
            self._describe_in_progress(),
            f'notified({counter.notified})' if counter.notified else '',
            f'deactivated({counter.deactivated})' if counter.deactivated else '',
            self._describe_abnormal(counter),
        )))
