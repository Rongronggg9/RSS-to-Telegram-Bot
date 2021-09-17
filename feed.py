import fasteners
import feedparser
import listparser
import requests
import threading
from bs4 import BeautifulSoup
from bs4.element import Tag
from requests.adapters import HTTPAdapter
from io import BytesIO
from typing import Optional, Dict, Union, Iterator
from datetime import datetime

import log
import env
from db import db
from post import get_post_from_entry

logger = log.getLogger('RSStT.feed')


# send threads pool
class SendPool:
    max_concurrent = 5
    _send_semaphore = threading.BoundedSemaphore(max_concurrent)
    _generate_semaphore = threading.BoundedSemaphore(max_concurrent)

    def __init__(self):
        self.endLock = threading.RLock()

    def send(self, uid, entry, feed_title):
        post = get_post_from_entry(entry, feed_title)

        with self._generate_semaphore:
            post.generate_message()

        with self._send_semaphore:
            logger.debug(f"Sending {entry['title']} ({entry['link']})...")
            post.send_message(uid)


class Feed:
    def __init__(self, link: str, fid: Optional[int] = None, name: Optional[str] = None, last: Optional[str] = None):
        self.fid = fid
        self.name = name
        self.link = link
        self.last = last
        self.rss_d = None

    def monitor(self):
        rss_d = feed_get(self.link)
        if rss_d is None:
            return

        feed_last = str(rss_d.entries[0]['link'])
        if self.last == feed_last:
            logger.debug(f'{self.link} fetched, no new post.')
            return

        last = self.last
        self.last = feed_last
        db.write(self.name, self.link, feed_last, True)  # update db

        logger.info(f'{self.link} updated!')
        # Workaround, avoiding deleted post causing the bot send all posts in the feed.
        # Known issues:
        # If a post was deleted while another post was sent between feed fetching duration,
        #  the latter won't be sent.
        # If your bot has stopped for too long that last sent post do not exist in current RSS feed,
        #  all posts won't be sent and last sent post will be reset to the newest post (though not sent).
        end = None
        for i in range(len(rss_d.entries)):
            if last == rss_d.entries[i]['link']:
                end = i
                break

        if not end:  # end is None or end == 0
            logger.warning('Cannot find the last sent post in current feed, all posts will not be sent.')
        else:
            self.rss_d = rss_d
            # threading.Thread(target=self.send,
            #                  kwargs={'uid': env.CHATID, 'start': 0, 'end': end, 'reverse': True}).start()
            self.send(env.CHATID, start=0, end=end, reverse=True)
        return

    def send(self, uid, start: int = 0, end: Optional[int] = 1, reverse: bool = False):
        rss_d = self.rss_d if self.rss_d else feed_get(self.link, uid=uid)
        if rss_d is None:
            return

        self.rss_d = None  # release

        if start >= len(rss_d.entries):
            start = 0
            end = 1
        elif end is not None and start > 0 and start >= end:
            end = start + 1

        entries_to_send = rss_d.entries[start:end]
        if reverse:
            entries_to_send = entries_to_send[::-1]

        send_poll = SendPool()
        for thread in (threading.Thread(target=send_poll.send,
                                        kwargs={'uid': uid, 'entry': entry, 'feed_title': rss_d.feed.title})
                       for entry in entries_to_send):
            thread.setDaemon(True)
            thread.start()

    def __eq__(self, other):
        return isinstance(other, Feed) and self.name == other.name


class Feeds:
    def __init__(self):
        self._feeds = {fid: Feed(fid=fid, name=name, link=feed_url, last=last_url)
                       for fid, (name, (feed_url, last_url)) in enumerate(db.read_all().items())}
        self._lock = fasteners.ReaderWriterLock()
        with open('opml_template.opml', 'r') as template:
            self._opml_template = template.read()

    @fasteners.lock.read_locked
    def monitor(self):
        any(map(lambda feed: feed.monitor(), self._feeds.values()))

    @fasteners.lock.read_locked
    def find(self, name: Optional[str] = None, link: Optional[str] = None, strict: bool = True) -> Optional[Feed]:
        if not (name or link):
            return
        for feed in self._feeds.values():
            if (name is None or feed.name == name) and (link is None or feed.link == link) if strict \
                    else feed.name == name or feed.link == link:
                return feed
        return None

    def add_feed(self, name, link, uid: Optional[int] = None, timeout: Optional[int] = 10):
        if self.find(name, link, strict=False):
            env.bot.send_message(uid, 'ERROR: 订阅名已被使用或 RSS 源已订阅') if uid else None
            logger.warning(f'Refused to add an existing feed: {name} ({link})')
            return None
        rss_d = feed_get(link, uid=uid, timeout=timeout)
        if rss_d is None:
            return None
        last = str(rss_d.entries[0]['link'])
        fid = self.current_fid
        feed = Feed(fid=fid, name=name, link=link, last=last)

        # acquire w lock
        with self._lock.write_lock():
            self._feeds[fid] = feed
            db.write(name, link, last)

        logger.info(f'Added feed {link}.')
        return feed

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

    def import_opml(self, opml_file: Union[bytearray, bytes]) -> Optional[Dict[str, list]]:
        valid_feeds = []
        invalid_feeds = []
        opml_d = listparser.parse(opml_file.decode())
        if not opml_d.feeds:
            return None
        for _feed in opml_d.feeds:
            if not _feed.title:
                _feed.title = '不支持无标题订阅！'
                invalid_feeds.append(_feed)
                continue
            _feed.title = _feed.title.replace(' ', '_')

            # do not need to acquire lock because add_feed will acquire one
            successful = self.add_feed(name=_feed.title, link=_feed.url, timeout=5)

            valid_feeds.append(_feed) if successful else invalid_feeds.append(_feed)
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


def web_get(url: str, timeout: Optional[int] = 15) -> BytesIO:
    if timeout is None:
        timeout = 15
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=1))
    session.mount('https://', HTTPAdapter(max_retries=1))

    response = session.get(url, timeout=timeout, proxies=env.REQUESTS_PROXIES,
                           headers=env.REQUESTS_HEADERS)
    content = BytesIO(response.content)
    return content


def feed_get(url: str, uid: Optional[int] = None, timeout: Optional[int] = None):
    try:
        rss_content = web_get(url, timeout=timeout)
        rss_d = feedparser.parse(rss_content, sanitize_html=False, resolve_relative_uris=False)
        _ = rss_d.entries[0]['title']  # try if the url is a valid RSS feed
    except IndexError:
        logger.warning(f'{url} fetch failed: feed error.')
        if uid:
            env.bot.send_message(uid, 'ERROR: 链接看起来不像是个 RSS 源，或该源不受支持')
        return None
    except requests.exceptions.RequestException:
        logger.warning(f'{url} fetch failed: network error.')
        if uid:
            env.bot.send_message(uid, 'ERROR: 网络超时')
        return None
    except Exception as e:
        logger.warning(f'{url} fetch failed: ', exc_info=e)
        if uid:
            env.bot.send_message(uid, 'ERROR: 内部错误')
        return None

    return rss_d
