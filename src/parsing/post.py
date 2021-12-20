import json
import re
import traceback
import asyncio.exceptions
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag
from typing import List, Iterator, Iterable
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
    VideoContentTypeInvalidError, VideoFileInvalidError,

    # errors caused by server instability or network instability between img server and telegram server
    WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError,

    # errors caused by lack of permission
    UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError
)

from src import env, message, log, web
from src.parsing import tgraph
from src.parsing.medium import Video, Image, Media, Animation
from src.parsing.html_text import *

logger = log.getLogger('RSStT.post')

# python-Levenshtein cannot handle UTF-8 input properly, mute the annoying warning from fuzzywuzzy
import warnings

warnings.original_warn = warnings.warn
warnings.warn = lambda *args, **kwargs: None
from fuzzywuzzy import fuzz

warnings.warn = warnings.original_warn

stripNewline = re.compile(r'\n{3,}', )
stripLineEnd = re.compile(r'[ \t\xa0]+\n')
isEmoticon = re.compile(r'(width|height): ?(([012]?\d|30)(\.\d)?px|[01](\.\d)?em)')

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
        xml = xml.replace('\n', '')
        xml = emojify(xml)
        self.xml = xml
        self.soup = BeautifulSoup(xml, 'lxml')
        self.media: Media = Media()
        self.text = Text('')
        self.service_msg = service_msg
        self.telegraph_url = telegraph_url
        self.messages: Optional[List[message.Message]] = None
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

    async def send_message(self, chat_ids: Union[List[Union[str, int]], str, int], reply_to_msg_id: int = None):
        if not self.messages and not self.telegraph_post:
            await self.generate_message()

        if self.telegraph_post:
            await self.telegraph_post.send_message(chat_ids, reply_to_msg_id)
            return

        if type(chat_ids) is not list:
            chat_ids = [chat_ids]

        if self.messages and len(self.messages) >= 5:
            logger.debug(f'Too large, send a pure link message instead: "{self.title}"')
            pure_link_post = Post(xml='', title=self.title, feed_title=self.feed_title,
                                  link=self.link, author=self.author, telegraph_url=self.link)
            await pure_link_post.send_message(chat_ids, reply_to_msg_id)
            return

        while len(chat_ids) >= 1:
            chat_id = chat_ids[0]
            for msg in self.messages:
                try:
                    await msg.send(chat_id, reply_to_msg_id)

                # errors caused by invalid img/video(s)
                except (PhotoInvalidDimensionsError, PhotoSaveFileInvalidError, PhotoInvalidError,
                        PhotoCropSizeSmallError, PhotoContentUrlEmptyError, PhotoContentTypeInvalidError,
                        GroupedMediaInvalidError, MediaGroupedInvalidError, MediaInvalidError,
                        VideoContentTypeInvalidError, VideoFileInvalidError) as e:
                    logger.debug(f'All media was set invalid because some of them are invalid '
                                 f'({e.__class__.__name__}: {str(e)})')
                    self.invalidate_all_media()
                    await self.generate_message()
                    await self.send_message(chat_ids)
                    return

                # errors caused by server instability or network instability between img server and telegram server
                except (WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError) as e:
                    if await self.media.change_all_server():
                        logger.debug(f'Telegram cannot fetch some media ({e.__class__.__name__}). '
                                     f'Changed img server and retrying...')
                        await self.send_message(chat_ids)
                        return
                    logger.debug('All media was set invalid '
                                 'because Telegram still cannot fetch some media after changing img server.')
                    self.invalidate_all_media()
                    await self.generate_message()
                    await self.send_message(chat_ids)
                    return

                except (UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError) as e:
                    raise e  # let monitoring task to deal with it

                except Exception as e:
                    logger.warning(f'Sending {self.link} failed: ', exc_info=e)
                    error_message = Post('Something went wrong while sending this message. Please check:<br><br>' +
                                         traceback.format_exc().replace('\n', '<br>'),
                                         self.title, self.feed_title, self.link, self.author, service_msg=True)
                    await error_message.send_message(env.MANAGER)

            chat_ids.pop(0)

    async def telegraph_ify(self):
        try:
            telegraph_url = await tgraph.TelegraphIfy(self.xml, title=self.title, link=self.link,
                                                      feed_title=self.feed_title, author=self.author).telegraph_ify()
            telegraph_post = Post(xml='', title=self.title, feed_title=self.feed_title,
                                  link=self.link, author=self.author, telegraph_url=telegraph_url)
            return telegraph_post
        except exceptions.TelegraphError as e:
            if str(e) == 'CONTENT_TOO_BIG':
                logger.debug(f'Content too big, send a pure link message instead: "{self.title}"')
                pure_link_post = Post(xml='', title=self.title, feed_title=self.feed_title,
                                      link=self.link, author=self.author, telegraph_url=self.link)
                return pure_link_post
            logger.debug('Telegraph API error: ' + str(e))
            return None
        except (TimeoutError, asyncio.exceptions.TimeoutError):
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

    async def generate_message(self, no_telegraph: bool = False) -> Optional[int]:
        # generate telegraph post if the post is too long
        if not no_telegraph and tgraph.apis and not self.service_msg and not self.telegraph_url \
                and (len(self.soup.getText()) >= 4096
                     or (len(self.messages) if self.messages else await self.generate_message(no_telegraph=True)) >= 2):
            logger.debug(f'Will be sent via Telegraph: "{self.title}"')
            self.telegraph_post = await self.telegraph_ify()  # telegraph post sent successful
            if self.telegraph_post:
                return
            logger.debug(f'Cannot be sent via Telegraph, fallback to normal message: "{self.title}"')

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
            if curr_type == 'image':
                self.messages.append(message.PhotoMsg(curr_text, curr_media))
                continue
            if curr_type == 'video':
                self.messages.append(message.VideoMsg(curr_text, curr_media))
                continue
            if curr_type == 'animation':
                self.messages.append(message.AnimationMsg(curr_text, curr_media))
                continue
            if curr_type == 'media_group':
                self.messages.append(message.MediaGroupMsg(curr_text, curr_media))
                continue
        if msg_texts:
            self.messages.extend([message.TextMsg(text) for text in msg_texts])

        return len(self.messages)

    def invalidate_all_media(self):
        self.media.invalidate_all()
        self.text = self.origin_text
        self._add_metadata()
        self._add_invalid_media()

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
            title_tbc = self.title.replace('[图片]', '').replace('[视频]', '').strip().rstrip('.…')
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

    async def _get_item(self, soup: Union[PageElement, BeautifulSoup, Tag, NavigableString, Iterable[PageElement]],
                        get_source: bool = False):
        result = []
        if isinstance(soup, Iterator):  # a Tag is also Iterable, but we only expect an Iterator here
            for child in soup:
                item = await self._get_item(child, get_source)
                if item and get_source and isinstance(item, list):
                    result.extend(item)
                if item:
                    result.append(item)
            if not result:
                return None
            if get_source:
                return result
            return result[0] if len(result) == 1 else Text(result)

        if isinstance(soup, NavigableString):
            if type(soup) is NavigableString:
                if str(soup) == ' ' or get_source:
                    return None
                return Text(str(soup))
            return None  # we do not expect a subclass of NavigableString here

        if not isinstance(soup, Tag):
            return None

        tag = soup.name

        if get_source:
            if tag != 'source':
                return None
            src = soup.get('src')
            if not src:
                return None
            return src

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
            src, alt, _class, style = soup.get('src'), soup.get('alt'), soup.get('class', ''), soup.get('style', '')
            if alt and (isEmoticon.search(style) or 'emoji' in _class or (alt.startswith(':') and alt.endswith(':'))):
                return Text(emojify(alt))
            if not src:
                return None
            if not src.startswith('http'):
                src = urljoin(self.feed_link, src)
            if src.endswith('.gif'):
                self.media.add(Animation(src))
                return None
            self.media.add(Image(src))
            return None

        if tag == 'video':
            video = None
            _src = soup.get('src')
            if _src:
                multi_src = [_src]
            else:
                multi_src = await self._get_item(soup.children, get_source=True)
            if not multi_src:
                return None
            for src in multi_src:
                if not isinstance(src, str):
                    continue
                if not src.startswith('http'):
                    src = urljoin(self.feed_link, src)
                video = Video(src)
                await video.validate()
                if video:  # if video is valid
                    break
            if video is not None:
                self.media.add(video)
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
                    page = (await web.get(src, decode=True))['content']
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
