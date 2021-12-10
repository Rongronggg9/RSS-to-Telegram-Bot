from typing import Optional, Dict, Final, Callable, Any, NoReturn, Set, Union
from math import ceil

from src.db import models


async def init():
    await EffectiveOptions.init()
    await EffectiveTasks.init()


class EffectiveOptions:
    """
    EffectiveOptions class.

    Implement a write-through cache that caches all options to reduce db load.
    """
    __options: Dict[str, Union[str, int]] = {}
    __initialized = False
    __default_options: Dict[str, Union[str, int]] = {
        "default_interval": 10,
        "minimal_interval": 5,
    }

    @classmethod
    @property
    def options(cls) -> Dict[str, Union[str, int]]:
        return cls.__options.copy()

    @classmethod
    @property
    def default_options(cls) -> Dict[str, Union[str, int]]:
        return cls.__default_options.copy()

    @classmethod
    @property
    def default_interval(cls) -> int:
        return cls.get('default_interval')

    @classmethod
    @property
    def minimal_interval(cls) -> int:
        return cls.get("minimal_interval")

    @classmethod
    def validate(cls, key: str, value: Union[int, str], ignore_type_error: bool = False) -> Union[int, str]:
        if len(key) > 255:
            raise KeyError("Option key must be 255 characters or less")

        value_type = type(cls.__default_options[key])
        if value_type is str:
            return str(value)

        if value_type is int and type(value) is str:
            if value.lstrip('-').isdecimal():
                return int(value)

            if ignore_type_error:
                return cls.__default_options[key]
            raise ValueError("Option value must be an integer")

        return value

    @classmethod
    def get(cls, key: str) -> Union[str, int]:
        """
        Get the value of an Option.

        :param key: option key
        :return: option value
        """
        if not cls.__initialized:
            raise RuntimeError("EffectiveOptions not initialized")
        return cls.__options[key]

    @classmethod
    async def set(cls, key: str, value: Union[int, str]) -> NoReturn:
        """
        Set the value of an Option. (write-through to the DB)

        :param key: option key
        :param value: option value
        """
        value = cls.validate(key, value)
        await models.Option.update_or_create(defaults={'value': str(value)}, key=key)
        cls.__options[key] = value

    @classmethod
    async def init(cls) -> NoReturn:
        """
        Cache all options from the DB.
        """
        options = await models.Option.all()
        for option in options:
            if option.key not in cls.__default_options:  # invalid option
                continue
            cls.__options[option.key] = cls.validate(option.key, option.value, ignore_type_error=True)

        for key, value in cls.__default_options.items():
            if key in cls.__options:
                continue
            cls.__options[key] = value
            # await models.Option.create(key=key, value=value)  # init option

        cls.__initialized = True


class EffectiveTasks:
    """
    EffectiveTasks class.

    A task dispatcher.
    """
    __task_buckets: Dict[int, "EffectiveTasks"] = {}  # key: interval, value: EffectiveTasks
    __all_tasks: Dict[int, int] = {}  # key: id, value: interval

    def __init__(self, interval: int) -> NoReturn:
        self.interval: Final = interval
        self.__all_feeds = set()
        self.__pending_feeds = set()
        # self.__checked_feeds = set()
        self.__run_count = 0

    @staticmethod
    def __ignore_key_error(func: Callable, *args, **kwargs) -> Optional[Any]:
        try:
            return func(*args, **kwargs)
        except KeyError:
            return None

    @classmethod
    async def init(cls, flush: bool = False) -> NoReturn:
        """
        Load a feeds from the DB and initialize tasks.

        :param flush: if already initialized, re-initialize?
        """
        if not cls.__task_buckets or flush:
            cls.__all_tasks = {}
            cls.__task_buckets = {}
            feeds = await models.Feed.filter(state=1).values('id', 'interval')
            default_interval = EffectiveOptions.default_interval
            for feed in feeds:
                cls.update(feed_id=feed['id'], interval=feed['interval'] or default_interval)

    def __update(self, feed_id: int):
        self.__all_feeds.add(feed_id)
        self.__pending_feeds.add(feed_id)

    @classmethod
    def update(cls, feed_id: int, interval: int = None) -> NoReturn:
        """
        Update or add a task.

        :param feed_id: the id of the feed in the task
        :param interval: the interval of the task
        """
        interval = interval or EffectiveOptions.default_interval
        if feed_id in cls.__all_tasks:  # if already have a task
            if cls.__all_tasks[feed_id] == interval:  # no need to update
                return
            cls.delete(feed_id, _preserve_in_all_tasks=True)  # delete the old one

        if interval not in cls.__task_buckets:  # if lack of bucket
            cls.__task_buckets[interval] = cls(interval)  # create one

        cls.__all_tasks[feed_id] = interval  # log the new task
        cls.__task_buckets[interval].__update(feed_id)  # update task

    def __delete(self, feed_id: int) -> NoReturn:
        self.__ignore_key_error(self.__all_feeds.remove, feed_id)
        self.__ignore_key_error(self.__pending_feeds.remove, feed_id)

    @classmethod
    def delete(cls, feed_id: int, _preserve_in_all_tasks: bool = False) -> NoReturn:
        """
        Delete a task.

        :param feed_id: the id of the feed in the task
        :param _preserve_in_all_tasks: for internal use
        """
        try:
            old_interval = cls.__all_tasks[feed_id]
            cls.__task_buckets[old_interval].__delete(feed_id)

            if not _preserve_in_all_tasks:
                del cls.__all_tasks[feed_id]
        except KeyError:
            pass

    @classmethod
    def exist(cls, feed_id: int) -> bool:
        """
        Check if a task exists.

        :param feed_id: the id of the feed in the task
        """
        return feed_id in cls.__all_tasks

    def __get_tasks(self) -> Set[int]:
        if len(self.__all_feeds) == 0:
            return set()  # nothing to run
        if self.__run_count == 0:
            self.__pending_feeds.update(self.__all_feeds)

        pop_count = ceil(len(self.__pending_feeds) / (self.interval - self.__run_count))
        tasks_to_run = set(self.__pending_feeds.pop() for _ in range(pop_count) if self.__pending_feeds)
        self.__run_count = self.__run_count + 1 if self.__run_count + 1 < self.interval else 0
        return tasks_to_run

    @classmethod
    def get_tasks(cls) -> Set[int]:
        """
        Get tasks to be run.

        :return: a `set` contains the ids of feeds in tasks to be run
        """
        tasks_to_run = set()
        for effective_tasks in cls.__task_buckets.values():
            tasks = effective_tasks.__get_tasks()
            if tasks:
                tasks_to_run.update(tasks)

        return tasks_to_run
