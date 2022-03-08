from __future__ import annotations
from src.compat import Final
from typing import Union, Optional

import asyncio
from aiographfix.utils import exceptions
from aiohttp import ClientError

# python-Levenshtein cannot handle UTF-8 input properly, mute the annoying warning from fuzzywuzzy
import warnings

warnings.original_warn = warnings.warn
warnings.warn = lambda *args, **kwargs: None
from fuzzywuzzy import fuzz

warnings.warn = warnings.original_warn

from . import utils, tgraph
from .splitter import get_plain_text_length
from .html_parser import parse
from .html_node import *
from .medium import Media, Image, Video, Audio, File, construct_images_weserv_nl_url

AUTO: Final = 0
DISABLE: Final = -1
FORCE_DISPLAY: Final = 1
FORCE_ENABLE: Final = 1
FORCE_LINK: Final = -1
FORCE_TELEGRAPH: Final = 1
FORCE_MESSAGE: Final = 2
DISABLE_BUT_DISPLAY_LINK: Final = -1
COMPLETELY_DISABLE: Final = -2
RSSTT: Final = 0
FLOWERSS: Final = 1

# via type
NO_VIA: Final = 'no_via'
FEED_TITLE_VIA: Final = 'feed_title_via'
LINK_VIA: Final = 'link_via'
TypeViaType = Union[NO_VIA, FEED_TITLE_VIA, LINK_VIA]

# message type
NORMAL_MESSAGE: Final = 'normal_message'
TELEGRAPH_MESSAGE: Final = 'telegraph_message'
LINK_MESSAGE: Final = 'link_message'
TypeMessageType = Union[NORMAL_MESSAGE, TELEGRAPH_MESSAGE, LINK_MESSAGE]

# message style
NORMAL_STYLE: Final = 'normal_style'
FLOWERSS_STYLE: Final = 'flowerss_style'
TypeMessageStyle = Union[NORMAL_STYLE, FLOWERSS_STYLE]

logger = utils.logger


class PostFormatter:
    def __init__(self,
                 html: str,
                 title: Optional[str] = None,
                 feed_title: Optional[str] = None,
                 link: Optional[str] = None,
                 author: Optional[str] = None,
                 feed_link: str = None,
                 enclosures: list[utils.Enclosure] = None):
        """
        :param html: HTML content
        :param title: post title
        :param feed_title: feed title
        :param link: post link
        :param author: post author
        :param feed_link: the url of the feed where the post from
        """
        self.html = html
        self.title = title
        self.feed_title = feed_title
        self.link = link
        self.author = author
        self.feed_link = feed_link
        self.enclosures = enclosures

        self.parsed: bool = False
        self.html_tree: Optional[HtmlTree] = None
        self.media: Optional[Media] = None
        self.parsed_html: Optional[str] = None
        self.plain_length: Optional[int] = None
        self.telegraph_link: Optional[Union[str, False]] = None  # if generating failed, will be False

        self.__title_similarity: Optional[int] = None

        self.__lock = asyncio.Lock()
        self.__post_bucket: dict[
            str,  # option hash
            tuple[
                str,  # formatted post
                bool,  # need media
                bool  # need linkpreview
            ]
        ] = {}
        self.__param_to_option_cache: dict[
            str,  # param hash
            str  # option hash
        ] = {}

    async def get_formatted_post(self,
                                 sub_title: Optional[str] = None,
                                 tags: Optional[list[str]] = None,
                                 send_mode: int = 0,
                                 length_limit: int = 0,
                                 link_preview: int = 0,
                                 display_author: int = 0,
                                 display_via: int = 0,
                                 display_title: int = 0,
                                 style: int = 0,
                                 display_media: int = 0) -> tuple[str, bool, bool]:
        """
        Get formatted post.

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
        :param display_media: -1=disable, 0=enable
        :return: (formatted post, need media, need linkpreview)
        """
        assert send_mode in {FORCE_LINK, AUTO, FORCE_TELEGRAPH, FORCE_MESSAGE}
        assert isinstance(length_limit, int) and length_limit >= 0
        assert link_preview in {AUTO, FORCE_ENABLE}
        assert display_author in {DISABLE, AUTO, FORCE_DISPLAY}
        assert display_via in {COMPLETELY_DISABLE, DISABLE_BUT_DISPLAY_LINK, AUTO, FORCE_DISPLAY}
        assert display_title in {DISABLE, AUTO, FORCE_DISPLAY}
        assert style in {RSSTT, FLOWERSS}

        sub_title = (sub_title or self.feed_title)
        tags = tags or []

        param_hash = f'{sub_title}|{tags}|{send_mode}|{length_limit}|{link_preview}|' \
                     f'{display_author}|{display_via}|{display_title}|{style}'

        if param_hash in self.__param_to_option_cache:
            option_hash = self.__param_to_option_cache[param_hash]
            if option_hash in self.__post_bucket:
                return self.__post_bucket[option_hash]

        # ---- generate parsed_html if needed ----
        if not self.parsed:
            async with self.__lock:
                if not self.parsed:  # double check
                    await self.parse_html()

        # ---- determine need_title ----
        if self.title and self.__title_similarity is None and display_title == AUTO:  # get title similarity
            async with self.__lock:
                if self.__title_similarity is None:  # double check
                    plain_text = utils.stripAnySpace(self.html_tree.get_html(plain=True))
                    title_tbc = self.title.replace('[图片]', '').replace('[视频]', '').replace('发布了: ', '') \
                        .strip().rstrip('.…')
                    title_tbc = utils.stripAnySpace(title_tbc)
                    self.__title_similarity = fuzz.partial_ratio(title_tbc, plain_text[0:len(self.title) + 10])
                    logger.debug(f'{self.title} ({self.link}) '
                                 f'is {self.__title_similarity}% likely to be of no title.')

        need_title = display_title != DISABLE and self.title and (
                display_title == FORCE_DISPLAY
                or (display_title == AUTO and self.__title_similarity < 90)
        )

        # ---- determine via_type ----  # FORCE_DISPLAY is now considered as AUTO
        if display_via == COMPLETELY_DISABLE or not (self.feed_title or self.link):
            via_type = NO_VIA
        elif display_via == DISABLE_BUT_DISPLAY_LINK and self.link:
            via_type = LINK_VIA
        elif display_via in {AUTO, FORCE_DISPLAY} and self.feed_title:
            via_type = FEED_TITLE_VIA
        elif display_via in {AUTO, FORCE_DISPLAY} and not self.feed_title and self.link:
            via_type = LINK_VIA
        else:
            via_type = NO_VIA

        # ---- determine need_author ----
        need_author = display_author != DISABLE and self.author and (
                display_author == FORCE_DISPLAY
                or (
                        display_author == AUTO
                        and (
                                not (self.author and sub_title and self.author in sub_title)
                                or via_type != FEED_TITLE_VIA
                        )
                )
        )

        # ---- determine message_style ----
        if style == FLOWERSS:
            message_style = FLOWERSS_STYLE
        else:  # RSSTT
            message_style = NORMAL_STYLE

        # ---- determine message_type ----
        normal_msg_post = None
        if send_mode == FORCE_MESSAGE:
            message_type = NORMAL_MESSAGE
        elif send_mode == FORCE_LINK and self.link:
            message_type = LINK_MESSAGE
        elif send_mode == FORCE_TELEGRAPH and self.telegraph_link is not False:
            message_type = TELEGRAPH_MESSAGE
        elif send_mode == FORCE_TELEGRAPH and self.telegraph_link is False:
            message_type = LINK_MESSAGE if self.link else NORMAL_MESSAGE
        else:  # AUTO
            if display_media != DISABLE and self.media:
                await self.media.validate()  # check media validity
            media_msg_count = await self.media.estimate_message_counts() \
                if (display_media != DISABLE and self.media) else 0
            normal_msg_post = self.generate_formatted_post(sub_title=sub_title,
                                                           tags=tags,
                                                           need_title=need_title,
                                                           via_type=via_type,
                                                           need_author=need_author,
                                                           message_type=NORMAL_MESSAGE,
                                                           message_style=message_style)
            normal_msg_len = get_plain_text_length(normal_msg_post)
            if (
                    (0 < length_limit <= self.plain_length)  # length_limit == 0 means no limit
                    or
                    normal_msg_len > (4096 if not media_msg_count else 1024)
                    or
                    media_msg_count > 1
            ):
                message_type = TELEGRAPH_MESSAGE
            else:
                message_type = NORMAL_MESSAGE

        if message_type == TELEGRAPH_MESSAGE and self.telegraph_link is None:  # generate telegraph post
            async with self.__lock:
                if self.telegraph_link is None:  # double check
                    await self.telegraph_ify()

        if self.telegraph_link is False and message_type == TELEGRAPH_MESSAGE:  # fallback to normal message if needed
            message_type = LINK_MESSAGE if self.link else NORMAL_MESSAGE

        # ---- determine need_media ----
        need_media = display_media != DISABLE and message_type == NORMAL_MESSAGE and self.media

        # ---- determine need_link_preview ----
        need_link_preview = not need_media and (link_preview == FORCE_ENABLE or message_type != NORMAL_MESSAGE)

        option_hash = f'{sub_title}|{tags}|{need_title}|{via_type}|{need_author}|{message_type}|{message_style}'
        self.__param_to_option_cache[param_hash] = option_hash

        if option_hash in self.__post_bucket:
            return self.__post_bucket[option_hash]

        if message_type == NORMAL_MESSAGE and normal_msg_post:
            self.__post_bucket[option_hash] = normal_msg_post, need_media, need_link_preview
            return normal_msg_post, need_media, need_link_preview

        async with self.__lock:
            if option_hash in self.__post_bucket:  # double check
                return self.__post_bucket[option_hash]
            post = self.generate_formatted_post(sub_title=sub_title,
                                                tags=tags,
                                                need_title=need_title,
                                                via_type=via_type,
                                                need_author=need_author,
                                                message_type=message_type,
                                                message_style=message_style)
            self.__post_bucket[option_hash] = post, need_media, need_link_preview
            return post, need_media, need_link_preview

    def get_post_header_and_footer(self,
                                   sub_title: Optional[str],
                                   tags: list,
                                   need_title: bool,
                                   via_type: TypeViaType,
                                   need_author: bool,
                                   message_type: TypeMessageType,
                                   message_style: TypeMessageStyle) -> tuple[str, str]:
        # RSStT style:
        # {title}
        # {hashtag}  (* optional)
        #
        # {content}  (* only present when NORMAL_MESSAGE)
        #
        # {via} {author}  (* determined by need_author)
        #
        # title:
        #   NORMAL_MESSAGE && need_title: <b><u>Title</u></b>
        #   NORMAL_MESSAGE && !need_title: (* nothing)
        #   TELEGRAPH_MESSAGE || LINK_MESSAGE: <b><u>Title (* text link)</u></b>
        #
        # via:
        #   FEED_TITLE_VIA: via Feed Title (* text link if possible)
        #   LINK_VIA: source (* text link)
        #   NO_VIA: (* nothing)

        # flowerss style:
        # {feed_title}
        # {title}
        # {hashtag}  (* optional)
        #
        # {content}  (* only present when NORMAL_MESSAGE)
        #
        # {sourcing}
        # {author}  (* determined by need_author)
        #
        # feed_title:
        #   FEED_TITLE_VIA: <b>Feed Title</b>
        #   LINK_VIA / NO_VIA: (* nothing)
        #
        # title:
        #   LINK_MESSAGE: <b><u>Title (* text link)</u></b>
        #   need_title: <b><u>Title</u></b>
        #   !need_title: (* nothing)
        #
        # sourcing:
        #   TELEGRAPH_MESSAGE && NO_VIA: Telegraph (* text link)
        #   TELEGRAPH_MESSAGE: Telegraph | Source (* both text link)
        #   LINK_MESSAGE || NO_VIA: (* nothing)
        #   NORMAL_MESSAGE: source (* text link)

        feed_title = sub_title or self.feed_title
        title = self.title or 'Untitled'

        # ---- hashtags ----
        tags_html = Text(' '.join('#' + tag for tag in tags)).get_html() if tags else None

        # ---- author ----
        author_html = Text(f'(author: {self.author})').get_html() if need_author and self.author else None

        if message_style == NORMAL_STYLE:
            # ---- title ----
            if message_type == TELEGRAPH_MESSAGE:
                title_text = Link(title, param=self.telegraph_link)
            elif message_type == LINK_MESSAGE:
                title_text = Link(title, param=self.link)
            else:  # NORMAL_MESSAGE
                title_text = title if need_title else None
            title_html = Bold(Underline(title_text)).get_html() if title_text else None

            # ---- via ----
            if via_type == FEED_TITLE_VIA:
                via_text = Text([Text('via '), Link(feed_title, param=self.link) if self.link else Text(feed_title)])
            elif via_type == LINK_VIA and self.link:
                via_text = Link('source', param=self.link)
            else:
                via_text = None
            via_html = via_text.get_html() if via_text else None

            header = (
                    (title_html or '')
                    + ('\n' if title_html and tags_html else '')
                    + (tags_html or '')
            )

            footer = (
                    (via_html or '')
                    + (' ' if via_html and author_html else '')
                    + (author_html or '')
            )

            return header, footer
        elif message_style == FLOWERSS_STYLE:
            # ---- feed title ----
            if via_type == FEED_TITLE_VIA:
                feed_title_html = Bold(feed_title).get_html() if feed_title else None
            else:
                feed_title_html = None

            # ---- title ----
            if message_type == LINK_MESSAGE:
                title_html = Bold(Underline(Link(title, param=self.link))).get_html()
            else:
                title_html = Bold(Underline(title)).get_html() if need_title else None

            # ---- sourcing ----
            if message_type == TELEGRAPH_MESSAGE:
                sourcing_html = Link('Telegraph', param=self.telegraph_link).get_html()
                if not via_type == NO_VIA:
                    sourcing_html += (' | ' + Link('source', param=self.link).get_html()) if self.link else ''
            elif message_type == LINK_MESSAGE or via_type == NO_VIA:
                sourcing_html = None
            else:  # NORMAL_MESSAGE
                sourcing_html = Link('source', param=self.link).get_html() if self.link else None

            header = (
                    (feed_title_html or '')
                    + ('\n' if feed_title_html and title_html else '')
                    + (title_html or '')
                    + ('\n' if (feed_title_html or title_html) and tags_html else '')
                    + (tags_html or '')
            )

            footer = (
                    (sourcing_html or '')
                    + ('\n' if sourcing_html and author_html else '')
                    + (author_html or '')
            )

            return header, footer

    def generate_formatted_post(self,
                                sub_title: Optional[str],
                                tags: list,
                                need_title: bool,
                                via_type: TypeViaType,
                                need_author: bool,
                                message_type: TypeMessageType,
                                message_style: TypeMessageStyle) -> str:
        header, footer = self.get_post_header_and_footer(sub_title=sub_title,
                                                         tags=tags,
                                                         need_title=need_title,
                                                         via_type=via_type,
                                                         need_author=need_author,
                                                         message_type=message_type,
                                                         message_style=message_style)
        content = self.parsed_html if message_type == NORMAL_MESSAGE else ''
        return (
                header
                + ('\n\n' if header and content else '')
                + content
                + ('\n\n' if (header or content) and footer else '')
                + footer
        )

    async def parse_html(self):
        parsed = await parse(html=self.html, feed_link=self.feed_link)
        self.html_tree = parsed.html_tree
        self.media = parsed.media
        self.parsed_html = parsed.html
        self.plain_length = get_plain_text_length(self.parsed_html)
        self.html = parsed.parser.html  # use a validated HTML
        self.parsed = True
        if self.enclosures:
            for enclosure in self.enclosures:
                # https://www.iana.org/assignments/media-types/media-types.xhtml
                if not enclosure.url or self.media.url_exists(enclosure.url):
                    continue
                elif not enclosure.type:
                    medium = File(enclosure.url)
                elif enclosure.type.find('webp') != -1 or enclosure.type.find('svg') != -1:
                    medium = Image(enclosure.url)
                    medium.url = construct_images_weserv_nl_url(enclosure.url)
                elif enclosure.type.startswith('image/gif'):
                    medium = Audio(enclosure.url)
                elif enclosure.type.startswith('audio'):
                    medium = Audio(enclosure.url)
                elif enclosure.type.startswith('video'):
                    medium = Video(enclosure.url)
                elif enclosure.type.startswith('image'):
                    medium = Image(enclosure.url)
                else:
                    medium = File(enclosure.url)
                self.media.add(medium)

    async def telegraph_ify(self):
        if isinstance(self.telegraph_link, str) or self.telegraph_link is False:
            return self.telegraph_link

        try:
            self.telegraph_link = await tgraph.TelegraphIfy(self.html,
                                                            title=self.title,
                                                            link=self.link,
                                                            feed_title=self.feed_title,
                                                            author=self.author).telegraph_ify()
            return self.telegraph_link
        except exceptions.TelegraphError as e:
            if str(e) == 'CONTENT_TOO_BIG':
                logger.debug(f'Content too big, send a pure link message instead: {self.link}')
            else:
                logger.debug(f'Telegraph API error ({e}): {self.link}')
        except (TimeoutError, asyncio.TimeoutError):
            logger.debug(f'Generate Telegraph post error (network timeout):  {self.link}')
        except (ClientError, ConnectionError) as e:
            logger.debug(f'Generate Telegraph post error (network error, {type(e).__name__}): {self.link}')
        except OverflowError:
            logger.debug(f'Generate Telegraph post error (retried for too many times): {self.link}')
        except Exception as e:
            logger.debug('Generate Telegraph post error: {self.link}', exc_info=e)

        self.telegraph_link = False
        return self.telegraph_link
