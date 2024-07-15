#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from collections.abc import Iterator, Iterable, Awaitable
from typing import Union, Optional

import re
import asyncio
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag
from urllib.parse import urlparse
from dataclasses import dataclass

from .. import web, env
from .medium import Video, Image, Media, Animation, Audio, UploadedImage
from .html_node import *
from .utils import stripNewline, stripLineEnd, isAbsoluteHttpLink, resolve_relative_link, emojify, is_emoticon
from ..aio_helper import run_async

convert_table_to_png: Optional[Awaitable]
if env.TABLE_TO_IMAGE:
    from .table_drawer import convert_table_to_png
else:
    convert_table_to_png = None

srcsetParser = re.compile(r'(?:^|,\s*)'
                          r'(?P<url>\S+)'  # allow comma here because it is valid in URL
                          r'(?:\s+'
                          r'(?P<number>\d+(\.\d+)?)'
                          r'(?P<unit>[wx])'
                          r')?'
                          r'\s*'
                          r'(?=,|$)').finditer  # e.g.: url,url 1x,url 2x,url 100w,url 200w


def effective_link(content: TypeTextContent, href: str, base: str = None) -> Union[TypeTextContent, Link, Text]:
    if href.startswith('javascript'):  # drop javascript links
        return content
    href = resolve_relative_link(base, href)
    if not isAbsoluteHttpLink(href):
        return Text([Text(f'{content} ('), Code(href), Text(')')])
    return Link(content, href)


class Parser:
    def __init__(self, html: str, feed_link: Optional[str] = None):
        """
        :param html: HTML content
        :param feed_link: feed link (use for resolve relative urls)
        """
        self.html = html
        self.soup: Optional[BeautifulSoup] = None
        self.media = Media()
        self.html_tree = HtmlTree('')
        self.feed_link = feed_link
        self.parsed = False
        self._parse_item_count = 0

    async def parse(self):
        self.soup = await run_async(BeautifulSoup, self.html, 'lxml', prefer_pool='thread')
        self.html_tree = HtmlTree(await self._parse_item(self.soup))
        self.parsed = True

    def get_parsed_html(self):
        if not self.parsed:
            raise RuntimeError('You must parse the HTML first')
        return stripNewline(stripLineEnd(self.html_tree.get_html().strip()))

    async def _parse_item(
            self,
            soup: Union[PageElement, BeautifulSoup, Tag, NavigableString, Iterable[PageElement]],
            in_list: bool = False
    ) -> Optional[Text]:
        self._parse_item_count += 1
        if self._parse_item_count % 64 == 0:
            await asyncio.sleep(0)  # yield to other coroutines, avoid blocking
        result = []
        if isinstance(soup, Iterator):  # a Tag is also Iterable, but we only expect an Iterator here
            prev_tag_name = None
            for child in soup:
                item = await self._parse_item(child)
                if item:
                    tag_name = child.name if isinstance(child, Tag) else None
                    if (tag_name == 'div' or prev_tag_name == 'div') \
                            and not (
                            (result and result[-1].get_html().endswith('\n')) or item.get_html().startswith('\n')
                    ):
                        result.append(Br())
                    result.append(item)
                    prev_tag_name = tag_name

            if not result:
                return None
            return result[0] if len(result) == 1 else Text(result)

        if isinstance(soup, NavigableString):
            if type(soup) is NavigableString:
                text = str(soup)
                return Text(emojify(text)) if text else None
            return None  # we do not expect a subclass of NavigableString here, drop it

        if not isinstance(soup, Tag):
            return None

        tag = soup.name
        if tag is None or tag == 'script':
            return None

        if tag == 'table':
            rows = soup.findAll('tr')
            if not rows:
                return None
            rows_content = []
            for i, row in enumerate(rows):
                columns = row.findAll(('td', 'th'))
                if len(rows) > 1 and len(columns) > 1:  # allow single-row or single-column tables
                    if env.TABLE_TO_IMAGE:
                        self.media.add(UploadedImage(convert_table_to_png(str(soup)), 'table.png'))
                    return None
                for j, column in enumerate(columns):  # transpose single-row tables into single-column tables
                    row_content = await self._parse_item(column)
                    if row_content:
                        rows_content.append(row_content)
                        if i < len(rows) - 1 or j < len(columns) - 1:
                            rows_content.append(Br(2))
            return Text(rows_content) or None

        if tag == 'p' or tag == 'section':
            parent = soup.parent.name
            text = await self._parse_item(soup.children)
            if text:
                if parent == 'li':
                    return text
                text_l = [text]
                ps, ns = soup.previous_sibling, soup.next_sibling
                if not (isinstance(ps, Tag) and ps.name == 'blockquote'):
                    text_l.insert(0, Br())
                if not (isinstance(ns, Tag) and ns.name == 'blockquote'):
                    text_l.append(Br())
                return Text(text_l) if len(text_l) > 1 else text
            return None

        if tag == 'blockquote':
            quote = await self._parse_item(soup.children)
            if not quote:
                return None
            quote.strip()
            if quote.is_empty():
                return None
            return Blockquote(quote)

        if tag == 'q':
            quote = await self._parse_item(soup.children)
            if not quote:
                return None
            quote.strip()
            if quote.is_empty():
                return None
            cite = soup.get('cite')
            if cite:
                quote = effective_link(quote, cite, self.feed_link)
            return Text([Text('“'), quote, Text('”')])

        if tag == 'pre':
            return Pre(await self._parse_item(soup.children))

        if tag == 'code':
            class_ = soup.get('class')
            if isinstance(class_, list):
                try:
                    class_ = next(filter(lambda x: x.startswith('language-'), class_))
                except StopIteration:
                    class_ = None
            elif class_ and isinstance(class_, str) and not class_.startswith('language-'):
                class_ = f'language-{class_}'
            else:
                class_ = None
            return Code(await self._parse_item(soup.children), param=class_)

        if tag == 'br':
            return Br()

        if tag == 'a':
            text = await self._parse_item(soup.children)
            if not text or text.is_empty():
                return None
            href = soup.get("href")
            if not href:
                return None
            return effective_link(text, href, self.feed_link)

        if tag == 'img':
            src, srcset = soup.get('src'), soup.get('srcset')
            if not (src or srcset):
                return None
            if is_emoticon(soup):
                alt = soup.get('alt')
                return Text(emojify(alt)) if alt else None
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
            is_gif = False
            for _src in _multi_src:
                if not isinstance(_src, str):
                    continue
                _src = resolve_relative_link(self.feed_link, _src)
                path = urlparse(_src).path
                if path.endswith(('.gif', '.gifv', '.webm', '.mp4', '.m4v')):
                    is_gif = True
                multi_src.append(_src)
            if multi_src:
                self.media.add(Animation(multi_src) if is_gif else Image(multi_src))
            return None

        if tag == 'video':
            poster = soup.get('poster')
            multi_src = self._get_multi_src(soup)
            if multi_src:
                self.media.add(Video(multi_src, type_fallback_urls=poster))
            return None

        if tag == 'audio':
            multi_src = self._get_multi_src(soup)
            if multi_src:
                self.media.add(Audio(multi_src))
            return None

        if tag == 'b' or tag == 'strong':
            text = await self._parse_item(soup.children)
            return Bold(text) if text else None

        if tag == 'i' or tag == 'em':
            text = await self._parse_item(soup.children)
            return Italic(text) if text else None

        if tag == 'u' or tag == 'ins':
            text = await self._parse_item(soup.children)
            return Underline(text) if text else None

        if tag == 'h1':
            text = await self._parse_item(soup.children)
            return Text([Br(2), Bold(Underline(text)), Br()]) if text else None

        if tag == 'h2':
            text = await self._parse_item(soup.children)
            return Text([Br(2), Bold(text), Br()]) if text else None

        if tag == 'hr':
            return Hr()

        if tag.startswith('h') and len(tag) == 2:
            text = await self._parse_item(soup.children)
            return Text([Br(2), Underline(text), Br()]) if text else None

        if tag == 'iframe':
            # text = await self._parse_item(soup.children)
            src = soup.get('src')
            if not src:
                return None
            src = resolve_relative_link(self.feed_link, src)
            title = urlparse(src).hostname if env.TRAFFIC_SAVING else await web.get_page_title(src)
            return Text([Br(2), effective_link(f'iframe ({title})', src), Br(2)])

        if (ordered := tag == 'ol') or tag in ('ul', 'menu', 'dir'):
            texts = []
            list_items = soup.findAll('li', recursive=False)
            if not list_items:
                return None
            for list_item in list_items:
                text = await self._parse_item(list_item, in_list=True)
                if text:
                    texts.append(text)
            if not texts:
                return None
            return OrderedList([Br(), *texts, Br()]) if ordered else UnorderedList([Br(), *texts, Br()])

        if tag == 'li':
            # <li> tags should be wrapped in <ol> or <ul>, but some feeds do not obey this rule
            # we do an "ugly fix" here to ensure that linebreaks are not missing
            text = await self._parse_item(soup.children)
            if not text:
                return None
            text.strip(deeper=True)
            if not text.get_html().strip():
                return None
            return ListItem(text) if in_list else UnorderedList([Br(), ListItem(text), Br()])

        text = await self._parse_item(soup.children)
        return text or None

    def _get_multi_src(self, soup: Tag) -> list[str]:
        src = soup.get('src')
        _multi_src = [t['src'] for t in soup.find_all(name='source') if t.get('src')]
        if src:
            _multi_src.append(src)
        multi_src = []
        for _src in _multi_src:
            if not isinstance(_src, str):
                continue
            _src = resolve_relative_link(self.feed_link, _src)
            multi_src.append(_src)
        return multi_src

    def __repr__(self):
        return repr(self.html_tree)

    def __str__(self):
        return str(self.html_tree)


@dataclass
class Parsed:
    html_tree: HtmlTree
    media: Media
    html: str
    parser: Parser


async def parse(html: str, feed_link: Optional[str] = None):
    """
    :param html: HTML content
    :param feed_link: feed link (use for resolve relative urls)
    """
    parser = Parser(html=html, feed_link=feed_link)
    await parser.parse()
    return Parsed(html_tree=parser.html_tree, media=parser.media, html=parser.get_parsed_html(), parser=parser)
