from __future__ import annotations
from typing import Optional

from html import unescape

from src import db, env, exceptions
from .utils import emojify, parse_entry, stripAnySpace, logger
from .post_formatter import PostFormatter
from .message import MessageDispatcher


def get_post_from_entry(entry, feed_title: str, feed_link: str = None) -> 'Post':
    entry_parsed = parse_entry(entry)
    return Post(entry_parsed.content, entry_parsed.title, feed_title, entry_parsed.link, entry_parsed.author,
                feed_link=feed_link)


class Post:
    def __init__(self,
                 html: str,
                 title: Optional[str] = None,
                 feed_title: Optional[str] = None,
                 link: Optional[str] = None,
                 author: Optional[str] = None,
                 feed_link: Optional[str] = None):
        """
        :param html: HTML content
        :param title: post title
        :param feed_title: feed title
        :param link: post link
        :param author: post author
        :param feed_link: the url of the feed where the post from
        """
        self.html = html
        title = (stripAnySpace(title.strip()) if title.find('\n') != -1 else title) if title else None
        self.title = emojify(unescape(title.strip())) if title else None
        self.feed_title = feed_title
        self.link = link
        self.author = author
        self.feed_link = feed_link

        self.post_formatter = PostFormatter(html=self.html,
                                            title=self.title,
                                            feed_title=self.feed_title,
                                            link=self.link,
                                            author=self.author,
                                            feed_link=self.feed_link)

    async def send_formatted_post_according_to_sub(self, sub: db.Sub):
        await self.send_formatted_post(user_id=sub.user_id,
                                       sub_title=sub.title,
                                       tags=sub.tags.split(' ') if sub.tags else [],
                                       send_mode=sub.send_mode,
                                       length_limit=sub.length_limit,
                                       link_preview=sub.link_preview,
                                       display_author=sub.display_author,
                                       display_via=sub.display_via,
                                       display_title=sub.display_title,
                                       style=sub.style,
                                       silent=not sub.notify)

    async def send_formatted_post(self,
                                  user_id: int,
                                  sub_title: Optional[str] = None,
                                  tags: Optional[list[str]] = None,
                                  send_mode: int = 0,
                                  length_limit: int = 0,
                                  link_preview: int = 0,
                                  display_author: int = 0,
                                  display_via: int = 0,
                                  display_title: int = 0,
                                  style: int = 0,
                                  silent: bool = False):
        """
        Send formatted post.

        :param user_id: user id
        :param sub_title: Sub title, overriding feed title if set
        :param tags: Tags of the sub
        :param send_mode: -1=force link, 0=auto, 1=force Telegraph, 2=force message
        :param length_limit: Telegraph length limit, valid when send_mode==0. If exceeded, send via Telegraph; If is 0,
            send via Telegraph when a post cannot be sent in a single message
        :param link_preview: 0=auto, 1=force enable
        :param display_author: -1=disable, 0=auto, 1=force display
        :param display_via: -2=completely disable, -1=disable but display link, 0=auto, 1=force display
        :param display_title: -1=disable, 0=auto, 1=force display
        :param style: 0=RSStT, 1=flowerss
        :param silent: whether to send with notification sound
        """
        for _ in range(2):
            if not self.post_formatter.parsed:
                await self.post_formatter.parse_html()

            formatted_post, need_media, need_link_preview = \
                await self.post_formatter.get_formatted_post(sub_title=sub_title,
                                                             tags=tags,
                                                             send_mode=send_mode,
                                                             length_limit=length_limit,
                                                             link_preview=link_preview,
                                                             display_author=display_author,
                                                             display_via=display_via,
                                                             display_title=display_title,
                                                             style=style)

            message_dispatcher = MessageDispatcher(user_id=user_id,
                                                   html=formatted_post,
                                                   media=self.post_formatter.media if need_media else None,
                                                   link_preview=need_link_preview,
                                                   silent=silent)
            try:
                return await message_dispatcher.send_messages()
            except exceptions.MediaSendFailErrors as e:
                logger.error(f'Failed to send post to user {user_id} (feed: {self.feed_link}, post: {self.link}), '
                             'dropped all media and retrying...', exc_info=e)
                self.post_formatter.media.invalidate_all()
                continue

    async def test_all_format(self, user_id: int):
        if user_id != env.MANAGER:
            return

        dedup_cache = set()

        for sub_title in ('Test Subscription Title', None):
            for tags in (['tag1', 'tag2', 'tag3'], None):
                for send_mode in (-1, 0, 1, 2):
                    for link_preview in (0, 1):
                        for display_author in (-1, 0, 1):
                            for display_via in (-2, -1, 0, 1):
                                for display_title in (-1, 0, 1):
                                    for style in (0, 1):
                                        formatted_post, need_media, need_link_preview = \
                                            await self.post_formatter.get_formatted_post(sub_title=sub_title,
                                                                                         tags=tags,
                                                                                         send_mode=send_mode,
                                                                                         link_preview=link_preview,
                                                                                         display_author=display_author,
                                                                                         display_via=display_via,
                                                                                         display_title=display_title,
                                                                                         style=style)
                                        if (formatted_post, need_media, need_link_preview) in dedup_cache:
                                            continue
                                        dedup_cache.add((formatted_post, need_media, need_link_preview))
                                        message_dispatcher = MessageDispatcher(user_id=user_id,
                                                                               html=formatted_post,
                                                                               media=self.post_formatter.media
                                                                               if need_media else None,
                                                                               link_preview=need_link_preview)
                                        await message_dispatcher.send_messages()
