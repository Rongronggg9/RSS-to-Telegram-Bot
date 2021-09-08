import json
import re
import traceback
import telegram.error

from bs4 import BeautifulSoup
from bs4.element import NavigableString
from typing import Optional, Union, List
from emoji import emojize

import message
import env
from medium import Video, Image, Media, Animation

# python-Levenshtein cannot handle UTF-8 input properly, mute the annoying warning from fuzzywuzzy
import warnings

warnings.original_warn = warnings.warn
warnings.warn = lambda *args, **kwargs: None
from fuzzywuzzy import fuzz

warnings.warn = warnings.original_warn

stripNewline = re.compile(r'\n{3,}', )
stripLineEnd = re.compile(r'[ \t\xa0]+\n')
isEmoticon = re.compile(r'(width|height): ?[012]?\dpx')

# load emoji dict
with open('emojify.json', 'r', encoding='utf-8') as emojify_json:
    emoji_dict = json.load(emojify_json)


def emojify(xml):
    # emojify, get all emoticons: https://api.weibo.com/2/emotions.json?source=1362404091
    xml = emojize(xml, use_aliases=True)
    for emoticon, emoji in emoji_dict.items():
        xml = xml.replace(f'[{emoticon}]', emoji)
    return xml


def get_post_from_entry(entry, feed_title):
    xml = entry['content'][0]['value'] \
        if ('content' in entry) and (len(entry['content']) > 0) \
        else entry['summary']
    link = entry['link']
    author = entry['author'] if ('author' in entry and type(entry['author']) is str) else None
    title = entry['title']
    return Post(xml, title, feed_title, link, author)


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
                 plain: bool = False):
        """
        :param xml: post content (xml or html)
        :param title: post title
        :param feed_title: feed title
        :param link: post link
        :param author: post author
        :param plain: do not need to be parsed?
        """
        self.retries = 0
        xml = xml.replace('\n', '')
        xml = emojify(xml)
        self.soup = BeautifulSoup(xml, 'html.parser')
        self.media: Media = Media()
        self.text = Text(self._get_item(self.soup))
        self.title = title
        self.feed_title = feed_title
        self.link = link
        self.author = author
        self.messages: Optional[List[message.Message]] = None
        self.origin_text = self.text.copy()
        self._add_metadata()
        self._add_invalid_media()

    def send_message(self, chat_ids: Union[List[Union[str, int]], str, int]):
        if type(chat_ids) is not list:
            chat_ids = [chat_ids]
        if not self.messages:
            self.generate_message()
        message_count = len(self.messages)
        tot_success_count = 0
        while len(chat_ids) >= 1:
            chat_id = chat_ids[0]
            user_success_count = 0
            for msg in self.messages:
                try:
                    msg.send(chat_id)
                    user_success_count += 1
                    tot_success_count += 1
                except telegram.error.BadRequest as e:
                    error_caption = e.message
                    if error_caption.startswith('Have no rights to send a message'):
                        chat_ids.pop(0)
                        break  # TODO: disable all feeds for this chat_id
                    if error_caption.startswith('Wrong file identifier/http url specified') \
                            or error_caption.startswith('Failed to get http url content') \
                            or error_caption.startswith('Wrong type of the web page content') \
                            or error_caption.startswith('Group send failed'):
                        if self.media.change_all_sinaimg_server():
                            self.send_message(chat_ids)
                            return
                        self.invalidate_all_media()
                        self.generate_message()
                        self.send_message(chat_ids)
                        return

                    print(e)
                    error_message = Post('Something went wrong while sending this message. Please check:<br><br>' +
                                         traceback.format_exc(),
                                         self.title, self.feed_title, self.link, self.author)
                    error_message.send_message(env.manager)

                except Exception as e:
                    print(e)
                    error_message = Post('Something went wrong while sending this message. Please check:<br><br>' +
                                         traceback.format_exc().replace('\n', '<br>'),
                                         self.title, self.feed_title, self.link, self.author)
                    error_message.send_message(env.manager)

            chat_ids.pop(0)

    def generate_pure_message(self):
        self.text = Text('Content decoding failed!\n内容解码失败！')
        self._add_metadata()

    def generate_message(self):
        media_tuple = tuple(self.media.get_valid_media())
        media_msg_count = len(media_tuple)
        self.messages = []

        # only text
        if not media_tuple:
            self.messages = [message.TextMsg(text) for text in self.get_split_html(4096)]
            return

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

    def invalidate_all_media(self):
        self.media.invalidate_all()
        self.text = self.origin_text
        self._add_metadata()
        self._add_invalid_media()

    def get_split_html(self, length_limit_head: int, head_count: int = -1, length_limit_tail: int = 4096):
        split_html = [stripNewline.sub('\n\n',
                                       stripLineEnd.sub('\n', p))
                      for p in self.text.split_html(length_limit_head, head_count, length_limit_tail)]
        if env.debug:
            print(split_html)
        return split_html

    def _add_metadata(self):
        plain_text = self.text.get_html(plain=True)
        if self.title and ('微博' not in self.feed_title or env.debug):
            title = emojify(self.title)
            title_tbc = title.replace('[图片]', '').replace('[视频]', '').strip().rstrip('.…')
            similarity = fuzz.partial_ratio(title_tbc, plain_text[0:len(title) + 10])
            if env.debug:
                print(similarity)
            if similarity < 90:
                self._add_title(title)
        if self.feed_title:
            author = self.author if self.author and self.author not in self.feed_title else None
            self._add_via(self.feed_title, self.link, author)

    def _add_title(self, title: str):
        text_title = Text([Bold(Underline(title)), Br(), Br()])
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

    def _get_item(self, soup: BeautifulSoup):
        result = []
        if isinstance(soup, type(iter([]))):
            for child in soup:
                item = self._get_item(child)
                if item:
                    result.append(item)
            return result[0] if len(result) == 1 else Text(result)

        if type(soup) is NavigableString:
            if str(soup) == ' ':
                return None
            return Text(str(soup))

        tag = soup.name

        if tag is None:
            return None

        if tag == 'p' or tag == 'section':
            parent = soup.parent.name
            text = self._get_item(soup.children)
            if text:
                return Text([Br(), text, Br()]) if parent != 'li' else text
            else:
                return None

        if tag == 'blockquote':
            quote = self._get_item(soup.children)
            quote.strip()
            return Text([Hr(), quote, Hr()])

        if tag == 'br':
            return Br()

        if tag == 'a':
            href = soup.get("href")
            if href and '://' in href:
                return Link(self._get_item(soup.children), href)
            return None

        if tag == 'img':
            src, alt, _class, style = soup.get('src'), soup.get('alt'), soup.get('class', ''), soup.get('style', '')
            if not src:
                return None
            if alt and (isEmoticon.search(style) or 'emoji' in _class or (alt.startswith(':') and alt.endswith(':'))):
                return Text(alt)
            if src.endswith('.gif'):
                self.media.add(Animation(src))
                return None
            self.media.add(Image(src))
            return None

        if tag == 'video':
            src = soup.get('src')
            if not src:
                return None
            self.media.add(Video(src))
            return None

        if tag == 'b' or tag == 'strong':
            text = self._get_item(soup.children)
            return Bold(text) if text else None

        if tag == 'i' or tag == 'em':
            text = self._get_item(soup.children)
            return Italic(text) if text else None

        if tag == 'u' or tag == 'ins':
            text = self._get_item(soup.children)
            return Underline(text) if text else None

        if tag == 'h1':
            text = self._get_item(soup.children)
            return Text([Br(2), Bold(Underline(text)), Br()]) if text else None

        if tag == 'h2':
            text = self._get_item(soup.children)
            return Text([Br(2), Bold(text), Br()]) if text else None

        if tag == 'hr':
            return Hr()

        if tag.startswith('h') and len(tag) == 2:
            text = self._get_item(soup.children)
            return Text([Br(2), Underline(text), Br()]) if text else None

        in_list = tag == 'ol' or tag == 'ul'
        for child in soup.children:
            item = self._get_item(child)
            if item and (not in_list or type(child) is not NavigableString):
                result.append(item)
        if tag == 'ol':
            return Text([Br(), OrderedList(result), Br()])
        elif tag == 'ul':
            return Text([Br(), UnorderedList(result), Br()])
        else:
            return result[0] if len(result) == 1 else Text(result)

    def __repr__(self):
        return repr(self.text)

    def __str__(self):
        return str(self.text)


# --------------------------
# Start various text classes
# --------------------------
class Text:
    tag: Optional[str] = None
    attr: Optional[str] = None

    def __init__(self, content, param=None):
        # type: (Union[Text, str, list], Optional[str]) -> None
        self.param = param
        if type(content) is type(self) or type(content) is Text:
            self.content = content.content
        elif type(content) is str:
            self.content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        else:
            self.content = content

    def is_nested(self):
        return type(self.content) is not str

    def is_listed(self):
        return type(self.content) is list

    def copy(self):
        if not self.is_nested():
            return self
        return type(self)(self.content.copy(), param=self.param)

    def strip(self, deep: bool = False):
        if not self.is_nested():  # str
            self.content.strip()
        if not self.is_listed():  # nested
            if not deep:
                return
            self.content.strip()
        while type(self.content[-1]) is Br:
            self.content.pop()
        while type(self.content[0]) is Br:
            self.content.pop(0)

    def get_html(self, plain: bool = False):
        if self.is_listed():
            result = ''
            for subText in self.content:
                result += subText.get_html(plain=plain)
        elif self.is_nested():
            result = self.content.get_html(plain=plain)
        else:
            result = self.content

        if plain:
            return result.replace('\n', '')

        if self.attr and self.param:
            return f'<{self.tag} {self.attr}="{self.param}">{result}</{self.tag}>'
        if self.tag:
            return f'<{self.tag}>{result}</{self.tag}>'
        return result

    def split_html(self, length_limit_head: int, head_count: int = -1, length_limit_tail: int = 4096):
        # TODO: when result to be yield < length_limit*0.5, add subSubText to it
        if type(self.content) == list:
            yield_count = 0
            result = ''
            length = 0
            for subText in self.content:
                curr_length = len(subText)
                curr_length_limit = length_limit_head if head_count == -1 or yield_count < head_count \
                    else length_limit_tail
                if length + curr_length >= curr_length_limit and result:
                    stripped = result.strip()
                    result = ''
                    length = 0
                    if stripped:
                        yield_count += 1
                        curr_length_limit = length_limit_head if head_count == -1 or yield_count < head_count \
                            else length_limit_tail
                        yield stripped
                if curr_length >= curr_length_limit:
                    for subSubText in subText.split_html(curr_length_limit):
                        stripped = subSubText.strip()
                        if stripped:
                            yield_count += 1
                            yield subSubText
                    continue
                length += curr_length
                result += subText.get_html()
        elif type(self.content) == str:
            result = self.content
            if len(result) >= length_limit_head:
                for i in range(0, len(result), length_limit_head - 1):
                    yield result[i:i + length_limit_head - 1]
                return
        else:
            result = self.content.get_html()
        if result:
            if self.attr and self.param:
                yield f'<{self.tag} {self.attr}={self.param}>{result}</{self.tag}>'
            elif self.tag:
                yield f'<{self.tag}>{result}</{self.tag}>'
            else:
                yield result

    def __len__(self):
        length = 0
        if type(self.content) == list:
            for subText in self.content:
                length += len(subText)
            return length
        return len(self.content)

    def __eq__(self, other):
        return type(self) == type(other) and self.content == other.content and self.param == other.param

    def __repr__(self):
        return f'{type(self).__name__}:{repr(self.content)}'

    def __str__(self):
        return self.get_html()


class Link(Text):
    tag = 'a'
    attr = 'href'


class Bold(Text):
    tag = 'b'


class Italic(Text):
    tag = 'i'


class Underline(Text):
    tag = 'u'


class Strike(Text):
    tag = 's'


class Code(Text):
    tag = 'code'


class Pre(Text):
    tag = 'pre'


class Br(Text):
    def __init__(self, count: int = 1):
        super().__init__('\n' * count)


class Hr(Text):
    def __init__(self):
        super().__init__('\n----------------------\n')

    def get_html(self, plain: bool = False):
        if plain:
            return ''
        return super().get_html()


class OrderedList(Text):
    def get_html(self, plain: bool = False):
        result = ''
        for index, subText in enumerate(self.content, start=1):
            result += f'{index}. {subText.get_html(plain=plain)}\n'
        return result

    def split_html(self, length_limit):
        result = ''
        length = 0
        for index, subText in enumerate(self.content, start=1):
            curr_length = len(subText)
            if length + curr_length >= length_limit and result:
                yield result
                result = ''
                length = 0
            length += curr_length
            result += f'{index}. {subText.get_html()}\n'
        if result:
            yield result


class UnorderedList(Text):
    def get_html(self, plain: bool = False):
        result = ''
        for subText in self.content:
            result += f'● {subText.get_html(plain=plain)}\n'
        return result
