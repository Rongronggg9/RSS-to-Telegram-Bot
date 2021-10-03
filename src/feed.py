import asyncio
import functools
import aiohttp.client_exceptions
import fasteners
import feedparser
import listparser
from bs4 import BeautifulSoup
from bs4.element import Tag
from typing import Optional, Dict, Union, Iterator, List, MutableMapping, Tuple, Iterable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from src import log, env, web
from src.db import db
from src.parsing.post import get_post_from_entry

logger = log.getLogger('RSStT.feed')

_feedparser_thread_pool = ThreadPoolExecutor(1, 'feedparser_')


class Feed:
    def __init__(self, link: str, fid: Optional[int] = None, name: Optional[str] = None, last: Optional[str] = None):
        self.fid = fid
        self.name = name
        self.link = link
        self.last = last

    async def monitor(self) -> Optional[bool]:
        rss_d = await feed_get(self.link)
        if rss_d is None:
            return False

        feed_last = str(rss_d.entries[0]['guid'] if 'guid' in rss_d.entries[0] else rss_d.entries[0]['link'])
        if self.last == feed_last:
            logger.debug(f'Fetched (not updated): {self.link}')
            return None

        last = self.last
        self.last = feed_last
        db.write(self.name, self.link, feed_last, True)  # update db

        logger.info(f'Updated: {self.link}')
        # Workaround, avoiding deleted post causing the bot send all posts in the feed.
        # Known issues:
        # If a post was deleted while another post was sent between feed fetching duration,
        #  the latter won't be sent.
        # If your bot has stopped for too long that last sent post do not exist in current RSS feed,
        #  all posts won't be sent and last sent post will be reset to the newest post (though not sent).
        end = None
        for i in range(len(rss_d.entries)):
            if last == str(rss_d.entries[i]['guid'] if 'guid' in rss_d.entries[i] else rss_d.entries[i]['link']):
                end = i
                break

        if not end:  # end is None or end == 0
            logger.warning(f'Cannot find the last sent post in current feed, all posts will not be sent: {self.link}')
        else:
            await self.send(env.CHATID, start=0, end=end, reverse=True, rss_d=rss_d)
        return True

    async def send(self, uid, start: int = 0, end: Optional[int] = 1, reverse: bool = False, rss_d=None,
                   web_semaphore: Union[bool, asyncio.Semaphore] = None):
        if rss_d is None:
            rss_d = await feed_get(self.link, uid=uid, web_semaphore=web_semaphore)

        if rss_d is None and uid is not None:
            return  # error occurred and have notified user

        if start >= len(rss_d.entries):
            start = 0
            end = 1
        elif end is not None and start > 0 and start >= end:
            end = start + 1

        entries_to_send = rss_d.entries[start:end]
        if reverse:
            entries_to_send = entries_to_send[::-1]

        await asyncio.gather(*(self._send(uid, entry, rss_d.feed.title) for entry in entries_to_send))

    async def _send(self, uid, entry, feed_title):
        post = get_post_from_entry(entry, feed_title, self.link)
        await post.generate_message()
        logger.debug(f"Sending {entry['title']} ({entry['link']})...")
        await post.send_message(uid)

    def __eq__(self, other):
        return isinstance(other, Feed) and self.name == other.name

    def __lt__(self, other):
        if self.fid is None:
            return True
        return self.fid < other.fid


class Feeds:
    def __init__(self):
        self._feeds = {fid: Feed(fid=fid, name=name, link=feed_url, last=last_url)
                       for fid, (name, (feed_url, last_url)) in enumerate(db.read_all().items())}
        self._lock = fasteners.ReaderWriterLock()
        with open('src/opml_template.opml', 'r') as template:
            self._opml_template = template.read()
        self._interval = min(round(env.DELAY / 60), 60)  # cannot greater than 60

    async def monitor(self, fetch_all: bool = False):
        feeds_to_be_monitored: Iterable[Feed]
        # acquire r lock
        with self._lock.read_lock():
            if fetch_all:
                feeds_to_be_monitored = self._feeds.values()
            else:
                # divide monitor tasks evenly to every minute
                sorted_feeds = sorted(self)
                head = datetime.utcnow().minute % self._interval
                feeds_to_be_monitored = sorted_feeds[head::self._interval]

        if not feeds_to_be_monitored:  # nothing to do
            return

        logger.info('Started feeds monitoring task.')

        result = await asyncio.gather(*(feed.monitor() for feed in feeds_to_be_monitored))

        no_update = 0
        fail = 0
        updated = 0

        for r in result:
            if r is None:
                no_update += 1
                continue
            if r:
                updated += 1
                continue
            fail += 1

        logger.info(f'Finished feeds monitoring task: '
                    f'updated({updated}), not updated({no_update}), fetch failed({fail})')

    @fasteners.lock.read_locked
    def find(self, name: Optional[str] = None, link: Optional[str] = None, strict: bool = True) -> Optional[Feed]:
        if not (name or link):
            return
        for feed in self._feeds.values():
            if (name is None or feed.name == name) and (link is None or feed.link == link) if strict \
                    else feed.name == name or feed.link == link:
                return feed
        return None

    async def add_feed(self, name, link, uid: Optional[int] = None, timeout: Optional[int] = 10) \
            -> Tuple[Union[bool, 'Feed'], Dict[str, Union[str, int]]]:
        feed_dict = {'name': name, 'link': link, 'uid': uid}
        if self.find(name, link, strict=False):
            env.bot.send_message(uid, 'ERROR: 订阅名已被使用或 RSS 源已订阅') if uid else None
            logger.warning(f'Refused to add an existing feed: {name} ({link})')
            return False, feed_dict
        rss_d = await feed_get(link, uid=uid, timeout=timeout)
        if rss_d is None:
            return False, feed_dict
        last = str(rss_d.entries[0]['guid'] if 'guid' in rss_d.entries[0] else rss_d.entries[0]['link'])
        fid = self.current_fid
        feed = Feed(fid=fid, name=name, link=link, last=last)

        # acquire w lock
        with self._lock.write_lock():
            self._feeds[fid] = feed
            db.write(name, link, last)

        logger.info(f'Added feed {link}.')
        return feed, feed_dict

    def del_feed(self, name):
        feed_to_delete = self.find(name)
        if feed_to_delete is None:
            return None

        # acquire w lock
        with self._lock.write_lock():
            self._feeds.pop(feed_to_delete.fid)
            db.delete(name)

        logger.info(f'Removed feed {name}.')
        return feed_to_delete

    @property
    @fasteners.lock.read_locked
    def current_fid(self):
        return max(self._feeds.keys()) + 1 if self._feeds else 1

    @fasteners.lock.read_locked
    def get_user_feeds(self) -> Optional[tuple]:
        if not self._feeds:
            return None
        else:
            return tuple(self._feeds)

    async def import_opml(self, opml_file: Union[bytearray, bytes]) -> Optional[Dict[str, list]]:
        opml_d = listparser.parse(opml_file.decode())
        if not opml_d.feeds:
            return None
        valid_feeds: List[MutableMapping] = []
        invalid_feeds: List[MutableMapping] = []

        coroutines = []
        for _feed in opml_d.feeds:
            if not _feed.title:
                _feed.title = '不支持无标题订阅！'
                invalid_feeds.append(_feed)
                continue

            _feed.title = _feed.title.replace(' ', '_')
            coroutines.append(self.add_feed(name=_feed.title, link=_feed.url))

        # do not need to acquire lock because add_feed will acquire one
        result = await asyncio.gather(*coroutines)

        for feed, feed_dict in result:
            valid_feeds.append(feed_dict) if feed else invalid_feeds.append(feed_dict)

        logger.info('Imported feed(s).')
        return {'valid': valid_feeds, 'invalid': invalid_feeds}

    @fasteners.lock.read_locked
    def export_opml(self) -> Optional[bytes]:
        opml = BeautifulSoup(self._opml_template, 'lxml-xml')
        create_time = Tag(name='dateCreated')
        create_time.string = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S UTC')
        opml.head.append(create_time)
        empty_flags = True
        for feed in self:
            empty_flags = False
            outline = Tag(name='outline', attrs={'text': feed.name, 'xmlUrl': feed.link})
            opml.body.append(outline)
        if empty_flags:
            return None
        logger.info('Exported feed(s).')
        return opml.prettify().encode()

    @fasteners.lock.read_locked
    def __iter__(self) -> Iterator[Feed]:
        return iter(self._feeds.values())

    @fasteners.lock.read_locked
    def __getitem__(self, item) -> Feed:
        return self._feeds[item]


async def feed_get(url: str, uid: Optional[int] = None, timeout: Optional[int] = None,
                   web_semaphore: Union[bool, asyncio.Semaphore] = None):
    try:
        rss_content = await web.get(url, timeout, web_semaphore)
        if len(rss_content) <= 524288:
            rss_d = feedparser.parse(rss_content, sanitize_html=False)
        else:  # feed too large, run in another thread to avoid blocking the bot
            rss_d = await asyncio.get_event_loop().run_in_executor(_feedparser_thread_pool,
                                                                   functools.partial(feedparser.parse, rss_content,
                                                                                     sanitize_html=False))
        if not rss_d.entries:
            logger.warning(f'Fetch failed (feed error): {url}')
            if uid:
                await env.bot.send_message(uid, 'ERROR: 链接看起来不像是个 RSS 源，或该源不受支持')
            return None
    except aiohttp.client_exceptions.InvalidURL:
        logger.warning(f'Fetch failed (URL invalid): {url}')
        if uid:
            await env.bot.send_message(uid, 'ERROR: URL 不合法')
        return None
    except (asyncio.exceptions.TimeoutError, aiohttp.client_exceptions.ClientError, ConnectionError, TimeoutError) as e:
        logger.warning(f'Fetch failed (network error, {e.__class__.__name__}): {url}')
        if uid:
            await env.bot.send_message(uid, 'ERROR: 网络错误')
        return None
    except Exception as e:
        logger.warning(f'Fetch failed: {url}', exc_info=e)
        if uid:
            await env.bot.send_message(uid, 'ERROR: 内部错误')
        return None
    return rss_d
