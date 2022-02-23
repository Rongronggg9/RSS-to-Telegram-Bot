from __future__ import annotations
from collections.abc import Iterator, Iterable

import json
import re
import traceback
import asyncio
import minify_html
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag
from emoji import emojize
from urllib.parse import urlparse, urljoin
from aiographfix import exceptions
from aiohttp import ClientError
from html import unescape

from telethon.errors.rpcerrorlist import (
    # errors caused by invalid img/video(s)
    PhotoInvalidDimensionsError, PhotoSaveFileInvalidError, PhotoInvalidError,
    PhotoCropSizeSmallError, PhotoContentUrlEmptyError, PhotoContentTypeInvalidError,
    GroupedMediaInvalidError, MediaGroupedInvalidError, MediaInvalidError,
    VideoContentTypeInvalidError, VideoFileInvalidError, ExternalUrlInvalidError,

    # errors caused by server instability or network instability between img server and telegram server
    WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError, FileReferenceExpiredError,
    BadRequestError,  # only FILE_REFERENCE_\d_EXPIRED

    # errors caused by too much entity data
    EntitiesTooLongError
)

from src import env, message, log, web
from src.parsing import tgraph
from src.parsing.medium import Video, Image, Media, Animation, VIDEO, IMAGE, ANIMATION, MEDIA_GROUP
from src.parsing.html_text import *
from src.exceptions import UserBlockedErrors

logger = log.getLogger('RSStT.post')

# python-Levenshtein cannot handle UTF-8 input properly, mute the annoying warning from fuzzywuzzy
import warnings

warnings.original_warn = warnings.warn
warnings.warn = lambda *args, **kwargs: None
from fuzzywuzzy import fuzz

warnings.warn = warnings.original_warn

stripNewline = re.compile(r'\n{3,}', )
stripLineEnd = re.compile(r'[ \t\xa0]+\n')
isSmallIcon = re.compile(r'(width|height): ?(([012]?\d|30)(\.\d)?px|([01](\.\d)?|2)r?em)').search
srcsetParser = re.compile(r'(?:^|,\s*)'
                          r'(?P<url>\S+)'  # allow comma here because it is valid in URL
                          r'(?:\s+'
                          r'(?P<number>\d+(\.\d+)?)'
                          r'(?P<unit>[wx])'
                          r')?'
                          r'\s*'
                          r'(?=,|$)').finditer  # e.g.: url,url 1x,url 2x,url 100w,url 200w
isFileReferenceNExpired = re.compile(r'FILE_REFERENCE_(?:\d_)?EXPIRED').search

# load emoji dict
with open('src/parsing/emojify.json', 'r', encoding='utf-8') as emojify_json:
    emoji_dict = json.load(emojify_json)


def emojify(xml):
    # emojify, get all emoticons: https://api.weibo.com/2/emotions.json?source=1362404091
    xml = emojize(xml, use_aliases=True)
    for emoticon, emoji in emoji_dict.items():
        xml = xml.replace(f'[{emoticon}]', emoji)
    return xml


def get_post_from_entry(entry, feed_title: str, feed_link: str = None) -> 'Post':
    # entry.summary returns summary(Atom) or description(RSS)
    content = entry.get('content') or entry.get('summary', '')

    if isinstance(content, list):  # Atom
        if len(content) == 1:
            content = content[0]
        else:
            for _content in content:
                content_type = _content.get('type', '')
                if 'html' in content_type or 'xml' in content_type:
                    content = _content
                    break
            else:
                content = content[0]
        content = content.get('value', '')

    link = entry.get('link') or entry.get('guid')
    author = entry['author'] if ('author' in entry and type(entry['author']) is str) else None
    title = entry.get('title')  # hmm, some entries do have no title, should we really set up a feed hospital?
    return Post(content, title, feed_title, link, author, feed_link=feed_link)


# ----------------
# Start post class
# ----------------
class Post:
    def __init__(self,
                 xml: str,
                 title: Optional[str] = None,
                 feed_title: Optional[str] = None,
                 link: Optional[str] = None,
                 author: Optional[str] = None,
                 plain: bool = False,
                 service_msg: bool = False,
                 telegraph_url: str = None,
                 feed_link: str = None):
        """
        :param xml: post content (xml or html)
        :param title: post title
        :param feed_title: feed title
        :param link: post link
        :param author: post author
        :param plain: do not need to add metadata?
        :param service_msg: is this post a bot service msg?
        :param telegraph_url: if set, a telegraph post will be sent
        :param feed_link: the url of the feed where the post from
        """
        self.retries = 0
        self.xml = minify_html.minify(xml)
        self.soup = BeautifulSoup(xml, 'lxml')
        self.media: Media = Media()
        self.text = Text('')
        self.service_msg = service_msg
        self.telegraph_url = telegraph_url
        self.messages: Optional[list[message.Message]] = None
        self.origin_text = self.text.copy()
        self.title = emojify(unescape(title.strip())) if title else None
        self.feed_title = feed_title
        self.link = link
        self.author = author
        self.plain = plain
        self.telegraph_post: Optional[Post] = None
        self.feed_link = feed_link if feed_link else link

    async def generate_text(self):
        self.text = Text(await self._get_item(self.soup))
        self.origin_text = self.text.copy()
        if self.plain:
            return
        await self.media.validate()
        self._add_metadata()
        self._add_invalid_media()

    async def send_message(self, chat_id: Union[str, int], reply_to_msg_id: int = None, silent: bool = None):
        if not self.messages and not self.telegraph_post:
            await self.generate_message()

        if self.telegraph_post:
            await self.telegraph_post.send_message(chat_id, reply_to_msg_id, silent)
            return

        if self.messages and len(self.messages) >= 5:
            logger.debug(f'Too large, send a pure link message instead: "{self.link}"')
            pure_link_post = Post(xml='', title=self.title, feed_title=self.feed_title, link=self.link,
                                  author=self.author, telegraph_url=self.link, feed_link=self.feed_link)
            await pure_link_post.send_message(chat_id, reply_to_msg_id, silent)
            return

        tries = 0
        max_tries = 10
        last_try = False
        server_change_count = 0
        media_fallback_count = 0
        invalidate_count = 0
        useless_invalidate_count = 0
        err_list = []
        while True:
            if not (invalidate_count or useless_invalidate_count) and tries > max_tries and not last_try:
                last_try = True  # try the last time
            elif last_try or invalidate_count > 1 or useless_invalidate_count > 0 or tries > max_tries:
                logger.error(
                    f'Sending {self.link} failed (feed: {self.feed_link}, user: {chat_id}). \n'
                    f'Counters: [tries={tries}, server_change_count={server_change_count}, '
                    f'media_fallback_count={media_fallback_count}, invalidate_count={invalidate_count}, '
                    f'useless_invalidate_count={useless_invalidate_count}]. \n'
                    f'Errors: {err_list}'
                    + (
                        f'\nSometimes it means that there may be some bugs in the code :('
                        if (
                                last_try or invalidate_count > 1 or useless_invalidate_count > 0
                                or sum((server_change_count, media_fallback_count,
                                        invalidate_count, useless_invalidate_count)) != tries
                        ) else ''
                    )
                )
                return
            tries += 1

            try:
                for msg in self.messages:
                    await msg.send(chat_id, reply_to_msg_id, silent)
                return

            # errors caused by too much entity data
            except EntitiesTooLongError as e:
                err_list.append(e)
                await self.generate_message(force_telegraph=True)
                await self.telegraph_post.send_message(chat_id, reply_to_msg_id, silent)
                return

            # errors caused by invalid img/video(s)
            except (PhotoInvalidDimensionsError, PhotoSaveFileInvalidError, PhotoInvalidError,
                    PhotoCropSizeSmallError, PhotoContentUrlEmptyError, PhotoContentTypeInvalidError,
                    GroupedMediaInvalidError, MediaGroupedInvalidError, MediaInvalidError,
                    VideoContentTypeInvalidError, VideoFileInvalidError, ExternalUrlInvalidError) as e:
                err_list.append(e)
                if not last_try and await self.fallback_media():
                    logger.debug(f'Media fall backed because some of them are invalid '
                                 f'({e.__class__.__name__}): {self.link}')
                    await self.generate_message()
                    media_fallback_count += 1
                else:
                    if await self.fallback_media(force_invalidate_all=True):
                        logger.debug(f'All media was set invalid because some of them are invalid '
                                     f'({e.__class__.__name__}): {self.link}')
                        await self.generate_message()
                        invalidate_count += 1
                    else:
                        useless_invalidate_count += 1
                continue

            except UserBlockedErrors as e:
                err_list.append(e)
                raise e  # let monitoring task to deal with it

            # errors caused by server instability or network instability between img server and telegram server
            except (WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError) as e:
                err_list.append(e)
                if not last_try and await self.media.change_all_server():
                    logger.debug(f'Telegram cannot fetch some media ({e.__class__.__name__}). '
                                 f'Changed img server and retrying: {self.link}')
                    server_change_count += 1
                elif not last_try and await self.fallback_media():
                    logger.debug(f'Media fall backed '
                                 f'because Telegram still cannot fetch some media after changing img server '
                                 f'({e.__class__.__name__}): {self.link}')
                    await self.generate_message()
                    media_fallback_count += 1
                else:
                    if await self.fallback_media(force_invalidate_all=True):
                        logger.debug(f'All media was set invalid '
                                     f'because Telegram still cannot fetch some media after changing img server '
                                     f'({e.__class__.__name__}): {self.link}')
                        await self.generate_message()
                        invalidate_count += 1
                    else:
                        useless_invalidate_count += 1
                continue

            except Exception as e:
                if isinstance(e, FileReferenceExpiredError) \
                        or (type(e) == BadRequestError and isFileReferenceNExpired(str(e))):
                    err_list.append(e if isinstance(e, FileReferenceExpiredError)
                                    else FileReferenceExpiredError(e.request))
                    continue
                err_list.append(e)
                logger.warning(f'Sending {self.link} failed (feed: {self.feed_link}, user: {chat_id}): ', exc_info=e)
                error_message = Post(f'Something went wrong while sending this message '
                                     f'(feed: {self.feed_link}, user: {chat_id}). '
                                     f'Please check:<br><br>' +
                                     traceback.format_exc().replace('\n', '<br>'),
                                     self.title, self.feed_title, self.link, self.author, feed_link=self.feed_link,
                                     service_msg=True)
                await error_message.send_message(env.MANAGER)
                return

    async def telegraph_ify(self):
        try:
            telegraph_url = await tgraph.TelegraphIfy(self.xml, title=self.title, link=self.link,
                                                      feed_title=self.feed_title, author=self.author).telegraph_ify()
            telegraph_post = Post(xml='', title=self.title, feed_title=self.feed_title, link=self.link,
                                  author=self.author, telegraph_url=telegraph_url, feed_link=self.feed_link)
            return telegraph_post
        except exceptions.TelegraphError as e:
            if str(e) == 'CONTENT_TOO_BIG':
                logger.debug(f'Content too big, send a pure link message instead: "{self.link}"')
                pure_link_post = Post(xml='', title=self.title, feed_title=self.feed_title, link=self.link,
                                      author=self.author, telegraph_url=self.link, feed_link=self.feed_link)
                return pure_link_post
            logger.debug('Telegraph API error: ' + str(e))
            return None
        except (TimeoutError, asyncio.TimeoutError):
            logger.debug('Generate Telegraph post error: network timeout.')
            return None
        except (ClientError, ConnectionError) as e:
            logger.debug(f'Generate Telegraph post error: network error ({e.__class__.__name__}).')
            return None
        except OverflowError:
            logger.debug(f'Generate Telegraph post error: retried for too many times.')
            return None
        except Exception as e:
            logger.debug('Generate Telegraph post error: ', exc_info=e)
            return None

    def generate_pure_message(self):
        self.text = Text('Content decoding failed!\n内容解码失败！')
        self._add_metadata()

    async def generate_message(self, no_telegraph: bool = False, force_telegraph: bool = False) -> Optional[int]:
        # generate telegraph post if the post is too long
        if (
                force_telegraph or
                (
                        (
                                not no_telegraph and tgraph.apis and not self.service_msg and not self.telegraph_url
                        )
                        and
                        (
                                len(self.soup.getText()) >= 4096
                                or
                                (
                                        (
                                                len(self.messages) if self.messages
                                                else await self.generate_message(no_telegraph=True)
                                        ) >= 2
                                )
                        )
                )
        ):
            logger.debug(f'Will be sent via Telegraph: "{self.link}"')
            self.telegraph_post = await self.telegraph_ify()  # telegraph post sent successful
            if self.telegraph_post:
                return
            logger.debug(f'Cannot be sent via Telegraph, fallback to normal message: "{self.link}"')

        if not self.text:
            await self.generate_text()

        self.messages = []

        # service msg
        if self.service_msg:
            self.messages = [message.BotServiceMsg(text) for text in self.get_split_html(4096)]
            return len(self.messages)

        # Telegraph msg
        if self.telegraph_url:
            self.messages = [message.TelegraphMsg(text) for text in self.get_split_html(4096)]
            return len(self.messages)

        media_tuple = tuple(self.media.get_valid_media())
        media_msg_count = len(media_tuple)

        # only text
        if not media_tuple:
            self.messages = [message.TextMsg(text) for text in self.get_split_html(4096)]
            return len(self.messages)

        # containing media
        msg_texts = self.get_split_html(1024, media_msg_count, 4096)
        for curr in media_tuple:
            curr_type = curr['type']
            curr_media = curr['media']
            curr_text = msg_texts.pop(0) if msg_texts \
                else f'<b><i><u>Media of "{Text(self.title).get_html()}"</u></i></b>'
            if curr_type == IMAGE:
                self.messages.append(message.PhotoMsg(curr_text, curr_media))
                continue
            if curr_type == VIDEO:
                self.messages.append(message.VideoMsg(curr_text, curr_media))
                continue
            if curr_type == ANIMATION:
                self.messages.append(message.AnimationMsg(curr_text, curr_media))
                continue
            if curr_type == MEDIA_GROUP:
                self.messages.append(message.MediaGroupMsg(curr_text, curr_media))
                continue
        if msg_texts:
            self.messages.extend([message.TextMsg(text) for text in msg_texts])

        return len(self.messages)

    async def fallback_media(self, force_invalidate_all: bool = False) -> bool:
        if not (await self.media.fallback_all() if not force_invalidate_all else self.media.invalidate_all()):
            return False
        self.text = self.origin_text.copy()
        self._add_metadata()
        self._add_invalid_media()
        return True

    def get_split_html(self, length_limit_head: int, head_count: int = -1, length_limit_tail: int = 4096):
        split_html = [stripNewline.sub('\n\n',
                                       stripLineEnd.sub('\n', p))
                      for p in self.text.split_html(length_limit_head, head_count, length_limit_tail)]
        return split_html

    def _add_metadata(self):
        plain_text = self.text.get_html(plain=True)
        if self.telegraph_url:
            self._add_title(self.title)
        elif len(self.text) == 0 and self.title:
            self.text = Text(self.title)
        elif self.title and ('微博' not in self.feed_title or env.DEBUG):
            title_tbc = self.title.replace('[图片]', '').replace('[视频]', '').replace('发布了: ', '') \
                .strip().rstrip('.…')
            similarity = fuzz.partial_ratio(title_tbc, plain_text[0:len(self.title) + 10])
            logger.debug(f'{self.title} ({self.link}) is {similarity}% likely to be of no title.')
            if similarity < 90:
                self._add_title(self.title)
        if self.feed_title:
            author = self.author if self.author and self.author not in self.feed_title else None
            self._add_via(self.feed_title, self.link, author)

    def _add_title(self, title: str):
        if self.telegraph_url:
            title = Link(title, param=self.telegraph_url)
        title = Bold(Underline(title))
        text_title = Text([title, Br(), Br()])
        if self.text.is_listed():
            self.text.content.insert(0, text_title)
            return
        self.text = Text([text_title, self.text])

    def _add_via(self, feed: str, link: Optional[str] = None, author: Optional[str] = None):
        text_via = Text([Text('\n\nvia '), Link(feed, param=link) if link else Text(feed)])
        if author:
            text_via.content.append(Text(f' (author: {author})'))
        if self.text.is_listed():
            self.text.content.append(text_via)
            return
        self.text = Text([self.text, text_via])

    def _add_invalid_media(self):
        links = []
        for link in self.media.get_invalid_link():
            links.append(link)
            links.append(Br())
        if not links:
            return
        text_invalid_media = Text([Text('\n\nInvalid media:\n')] + links[:-1])
        if self.text.is_listed():
            self.text.content.append(text_invalid_media)
            return
        self.text = Text([self.text, text_invalid_media])

    async def _get_item(self, soup: Union[PageElement, BeautifulSoup, Tag, NavigableString, Iterable[PageElement]]):
        result = []
        if isinstance(soup, Iterator):  # a Tag is also Iterable, but we only expect an Iterator here
            for child in soup:
                item = await self._get_item(child)
                if item:
                    result.append(item)
            if not result:
                return None
            return result[0] if len(result) == 1 else Text(result)

        if isinstance(soup, NavigableString):
            if type(soup) is NavigableString:
                return Text(emojify(str(soup)))
            return None  # we do not expect a subclass of NavigableString here, drop it

        if not isinstance(soup, Tag):
            return None

        tag = soup.name
        if tag is None:
            return None

        if tag == 'p' or tag == 'section':
            parent = soup.parent.name
            text = await self._get_item(soup.children)
            if text:
                return Text([Br(), text, Br()]) if parent != 'li' else text
            else:
                return None

        if tag == 'blockquote':
            quote = await self._get_item(soup.children)
            if not quote:
                return None
            quote.strip()
            return Text([Hr(), quote, Hr()])

        if tag == 'pre':
            return Pre(await self._get_item(soup.children))

        if tag == 'code':
            return Code(await self._get_item(soup.children))

        if tag == 'br':
            return Br()

        if tag == 'a':
            text = await self._get_item(soup.children)
            if not text:
                return None
            href = soup.get("href")
            if not href:
                return None
            if not href.startswith('http'):
                href = urljoin(self.feed_link, href)
            return Link(await self._get_item(soup.children), href)

        if tag == 'img':
            src, srcset, alt, _class, style = \
                soup.get('src'), soup.get('srcset'), soup.get('alt', ''), soup.get('class', ''), soup.get('style', '')
            if isSmallIcon(style) or 'emoji' in _class or (alt.startswith(':') and alt.endswith(':')):
                return Text(emojify(alt)) if alt else None
            is_gif = src.endswith('.gif')
            _multi_src = []
            if srcset:
                srcset_matches: list[dict[str, Union[int, str]]] = [{
                    'url': match['url'],
                    'number': float(match['number']) if match['number'] else 1,
                    'unit': match['unit'] if match['unit'] else 'x'
                } for match in (
                    match.groupdict() for match in srcsetParser(srcset)
                )] + ([{'url': src, 'number': 1, 'unit': 'x'}] if src else [])
                if srcset_matches:
                    srcset_matches_unit_w = [match for match in srcset_matches if match['unit'] == 'w']
                    srcset_matches_unit_x = [match for match in srcset_matches if match['unit'] == 'x']
                    srcset_matches_unit_w.sort(key=lambda match: float(match['number']), reverse=True)
                    srcset_matches_unit_x.sort(key=lambda match: float(match['number']), reverse=True)
                    while True:
                        src_match_unit_w = srcset_matches_unit_w.pop(0) if srcset_matches_unit_w else None
                        src_match_unit_x = srcset_matches_unit_x.pop(0) if srcset_matches_unit_x else None
                        if not (src_match_unit_w or src_match_unit_x):
                            break
                        if src_match_unit_w:
                            _multi_src.append(src_match_unit_w['url'])
                        if src_match_unit_x:
                            if float(src_match_unit_x['number']) <= 1 and srcset_matches_unit_w:
                                srcset_matches_unit_x.insert(0, src_match_unit_x)
                                continue  # let src using unit w win
                            _multi_src.append(src_match_unit_x['url'])
            else:
                _multi_src.append(src) if src else None
            multi_src = []
            for _src in _multi_src:
                if not isinstance(_src, str):
                    continue
                if not _src.startswith('http'):
                    _src = urljoin(self.feed_link, _src)
                multi_src.append(_src)
            if multi_src:
                self.media.add(Image(multi_src) if not is_gif else Animation(multi_src))
            return None

        if tag == 'video':
            src = soup.get('src')
            poster = soup.get('poster')
            _multi_src = [t['src'] for t in soup.find_all(name='source') if t.get('src')]
            if src:
                _multi_src.append(src)
            multi_src = []
            for _src in _multi_src:
                if not isinstance(_src, str):
                    continue
                if not _src.startswith('http'):
                    _src = urljoin(self.feed_link, _src)
                multi_src.append(_src)
            if multi_src:
                self.media.add(Video(multi_src, poster=poster))
            return None

        if tag == 'b' or tag == 'strong':
            text = await self._get_item(soup.children)
            return Bold(text) if text else None

        if tag == 'i' or tag == 'em':
            text = await self._get_item(soup.children)
            return Italic(text) if text else None

        if tag == 'u' or tag == 'ins':
            text = await self._get_item(soup.children)
            return Underline(text) if text else None

        if tag == 'h1':
            text = await self._get_item(soup.children)
            return Text([Br(2), Bold(Underline(text)), Br()]) if text else None

        if tag == 'h2':
            text = await self._get_item(soup.children)
            return Text([Br(2), Bold(text), Br()]) if text else None

        if tag == 'hr':
            return Hr()

        if tag.startswith('h') and len(tag) == 2:
            text = await self._get_item(soup.children)
            return Text([Br(2), Underline(text), Br()]) if text else None

        if tag == 'li':
            text = await self._get_item(soup.children)
            return ListItem(text) if text else None

        if tag == 'iframe':
            text = await self._get_item(soup.children)
            src = soup.get('src')
            if not src:
                return None
            if not src.startswith('http'):
                src = urljoin(self.feed_link, src)
            if not text:
                # noinspection PyBroadException
                try:
                    page = (await web.get(src, decode=True, semaphore=False)).content
                    text = BeautifulSoup(page, 'lxml').title.text
                except Exception:
                    pass
                finally:
                    if not text:
                        text = urlparse(src).netloc
            return Text([Br(2), Link(f'iframe ({text})', param=src), Br(2)])

        in_list = tag == 'ol' or tag == 'ul'
        for child in soup.children:
            item = await self._get_item(child)
            if item and (not in_list or type(child) is not NavigableString):
                result.append(item)
        if tag == 'ol':
            return OrderedList([Br(), *result, Br()])
        elif tag == 'ul':
            return UnorderedList([Br(), *result, Br()])
        else:
            return result[0] if len(result) == 1 else Text(result)

    def __repr__(self):
        return repr(self.text)

    def __str__(self):
        return str(self.text)
