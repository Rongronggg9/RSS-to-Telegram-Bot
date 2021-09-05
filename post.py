import json
import re
import telegram.error
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from typing import Optional, Union, List
from fuzzywuzzy import fuzz
from emoji import emojize

import message
import env
from medium import Video, Image, Medium

stripNewline = re.compile(r'\n{3,}', )
stripLineEnd = re.compile(r'[ \t]+\n')
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
        self.all_media_invalidated = False
        xml = emojify(xml)
        self.soup = BeautifulSoup(xml, 'html.parser')
        self.media: List[Medium] = []
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
                    error_caption = str(e)
                    if error_caption.startswith('Have no rights to send a message'):
                        chat_ids.pop(0)
                        break  # TODO: disable all feeds for this chat_id
                    if error_caption.startswith('Wrong file identifier/http url specified') \
                            or error_caption.startswith('Failed to get http url content') \
                            or error_caption.startswith('Wrong type of the web page content') \
                            or error_caption.startswith('Group send failed'):
                        # TODO: change sinaimg server, or download the media then upload
                        if self.all_media_invalidated:
                            return
                        self.invalidate_all_media()
                        self.generate_message()
                        self.send_message(chat_ids)
                        return

                    if error_caption.startswith("Can't parse entities"):
                        pass
                    pass  # TODO: retry once
                except Exception as e:
                    print(e)
                    if sum(bool(m) for m in self.media):  # no media
                        pass

            chat_ids.pop(0)

    def generate_pure_message(self):
        self.text = Text('Content decoding failed!\n内容解码失败！')
        self._add_metadata()

    def generate_message(self):
        media = tuple(m for m in self.media if m)
        media_count = len(media)
        self.messages = []

        if not media:  # only text
            self.messages = [message.TextMsg(text) for text in self.get_split_html(4096)]
            return

        # TODO: text msgs after media msgs should have 4096-character length limit
        _flag = True
        if media_count == 1:  # single media
            for text in self.get_split_html(1024):
                if _flag and media[0].type == 'image':
                    self.messages.append(message.PhotoMsg(text, media))
                    _flag = False
                elif _flag and media[0].type == 'video':
                    self.messages.append(message.VideoMsg(text, media))
                    _flag = False
                else:
                    self.messages.append(message.TextMsg(text))
            return
        # multiple media
        media_list = [media[_i:_i + 10] for _i in range(0, media_count, 10)]
        for text in self.get_split_html(1024):
            if media_list:
                curr_media = media_list.pop(0)
                self.messages.append(message.MediaGroupMsg(text, curr_media))
            else:
                self.messages.append(message.TextMsg(text))
        return

    def invalidate_all_media(self):
        any(map(lambda m: m.invalidate(), self.media))
        self.all_media_invalidated = True
        self.text = self.origin_text
        self._add_metadata()
        self._add_invalid_media()

    def get_split_html(self, length_limit: int):
        split_html = [stripNewline.sub('\n\n',
                                       stripLineEnd.sub('\n', p)).strip()
                      for p in self.text.split_html(length_limit)]
        if env.debug:
            print(split_html)
        return split_html

    def _add_metadata(self):
        plain_text = self.text.get_html(plain=True)
        if self.title and ('微博' not in self.feed_title or env.debug):
            title = emojify(self.title.replace('[图片]', '').replace('[视频]', '').strip().rstrip('.').rstrip('…'))
            similarity = fuzz.partial_ratio(title, plain_text[0:len(title) + 10])
            if env.debug:
                print(similarity)
            if similarity < 90:
                self._add_title(self.title)
        if self.feed_title:
            author = self.author if self.author not in self.feed_title else None
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
        for medium in self.media:
            link = medium.get_link()
            if link:
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
                return Text([text, Br()]) if parent != 'li' else text
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
            if alt and (isEmoticon.search(style) or 'emoji' in _class):
                return Text(alt)
            self.media.append(Image(src))
            return None

        if tag == 'video':
            src = soup.get('src')
            if not src:
                return None
            self.media.append(Video(src))
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
            return Text([Bold(Underline(text)), Br()]) if text else None

        if tag == 'h2':
            text = self._get_item(soup.children)
            return Text([Bold(text), Br()]) if text else None

        if tag == 'hr':
            return Hr()

        if tag.startswith('h') and len(tag) == 2:
            text = self._get_item(soup.children)
            return Text([Underline(text), Br()]) if text else None

        in_list = tag == 'ol' or tag == 'ul'
        for child in soup.children:
            item = self._get_item(child)
            if item and (not in_list or type(child) is not NavigableString):
                result.append(item)
        if tag == 'ol':
            return OrderedList(result)
        elif tag == 'ul':
            return UnorderedList(result)
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
            self.content = content.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
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

    def strip(self):
        if not self.is_listed():
            return
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

    def split_html(self, length_limit: int):
        if type(self.content) == list:
            result = ''
            length = 0
            for subText in self.content:
                curr_length = len(subText)
                if length + curr_length >= length_limit and result:
                    yield result
                    result = ''
                    length = 0
                if curr_length >= length_limit:
                    for subSubText in subText.split_html(length_limit):
                        yield subSubText
                    continue
                length += curr_length
                result += subText.get_html()
        elif type(self.content) == str:
            result = self.content
            if len(result) >= length_limit:
                for i in range(0, len(result), length_limit - 1):
                    yield result[i:i + length_limit - 1]
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
    def __init__(self):
        super().__init__('\n')


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
