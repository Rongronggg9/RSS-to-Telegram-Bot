from __future__ import annotations
from typing import Optional, Sequence, Union

import re
import json
from bs4 import BeautifulSoup
from bs4.element import Tag
from minify_html import minify
from html import unescape
from emoji import emojize
from telethon.tl.types import TypeMessageEntity
from telethon.helpers import add_surrogate
from functools import partial
from urllib.parse import urljoin
from os import path

from .. import log

logger = log.getLogger('RSStT.parsing')

stripBr = partial(re.compile(r'\s*<br\s*/?>\s*').sub, '<br/>')
stripLineEnd = partial(re.compile(r'[ 　\t\r\u2028\u2029]+\n').sub, '\n')  # use firstly
stripNewline = partial(re.compile(r'[\f\n\u2028\u2029]{3,}').sub, '\n\n')  # use secondly
stripAnySpace = partial(re.compile(r'\s+').sub, ' ')
replaceInvalidSpace = partial(
    re.compile(r'[\xa0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b\u200c\u200d]').sub, ' '
)
isAbsoluteHttpLink = re.compile(r'^https?://').match
isSmallIcon = re.compile(r'(width|height): ?(([012]?\d|30)(\.\d)?px|([01](\.\d)?|2)r?em)').search


class Enclosure:
    def __init__(self, url: str, length: Union[int, str], _type: str, duration: str = None):
        self.url = url
        self.length = (
            int(length)
            if isinstance(length, str) and length.isdigit()
            else length
            if isinstance(length, int)
            else None
        )
        self.type = _type
        self.duration = duration


# load emoji dict
with open(path.join(path.dirname(__file__), 'emojify.json'), 'r', encoding='utf-8') as emojify_json:
    emoji_dict = json.load(emojify_json)


def resolve_relative_link(base: str, url: str) -> str:
    if not (base and url) or isAbsoluteHttpLink(url) or not isAbsoluteHttpLink(base):
        return url
    return urljoin(base, url)


def emojify(xml):
    xml = emojize(xml, language='alias', variant='emoji_type')
    for emoticon, emoji in emoji_dict.items():
        # emojify weibo emoticons, get all here: https://api.weibo.com/2/emotions.json?source=1362404091
        xml = xml.replace(f'[{emoticon}]', emoji)
    return xml


def is_emoticon(tag: Tag) -> bool:
    if tag.name != 'img':
        return False
    src = tag.get('src', '')
    alt, _class = tag.get('alt', ''), tag.get('class', '')
    style, width, height = tag.get('style', ''), tag.get('width', ''), tag.get('height', '')
    width = int(width) if width and width.isdigit() else float('inf')
    height = int(height) if height and height.isdigit() else float('inf')
    return (width <= 30 or height <= 30 or isSmallIcon(style)
            or 'emoji' in _class or 'emoticon' in _class or (alt.startswith(':') and alt.endswith(':'))
            or src.startswith('data:'))


def html_validator(html: str) -> str:
    html = stripBr(html)
    # validate invalid HTML first, since minify_html is not so robust
    html = BeautifulSoup(html, 'lxml').decode()
    html = minify(html,
                  do_not_minify_doctype=True,
                  keep_closing_tags=True,
                  keep_spaces_between_attributes=True,
                  ensure_spec_compliant_unquoted_attribute_values=True,
                  remove_processing_instructions=True)
    html = replaceInvalidSpace(html)
    return html


def html_space_stripper(s: str, enable_emojify: bool = False) -> str:
    if not s:
        return s
    s = stripAnySpace(replaceInvalidSpace(unescape(s))).strip()
    return emojify(s) if enable_emojify else s


def parse_entry(entry):
    class EntryParsed:
        content: str = ''
        link: Optional[str] = None
        author: Optional[str] = None
        title: Optional[str] = None
        enclosures: list[Enclosure] = None

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

    EntryParsed.content = html_validator(content)
    EntryParsed.link = entry.get('link') or entry.get('guid')
    author = entry['author'] if ('author' in entry and type(entry['author']) is str) else None
    author = html_space_stripper(author) if author else None
    EntryParsed.author = author if author else None  # reject empty string
    # hmm, some entries do have no title, should we really set up a feed hospital?
    title = entry.get('title')
    title = html_space_stripper(title, enable_emojify=True) if title else None
    EntryParsed.title = title if title else None  # reject empty string
    if isinstance(entry.get('links'), list):
        EntryParsed.enclosures = []
        for link in entry['links']:
            if link.get('rel') == 'enclosure':
                enclosure_url = link.get('href')
                if not enclosure_url:
                    continue
                enclosure_url = resolve_relative_link(EntryParsed.link, enclosure_url)
                EntryParsed.enclosures.append(Enclosure(url=enclosure_url,
                                                        length=link.get('length'),
                                                        _type=link.get('type')))
        if EntryParsed.enclosures and entry.get('itunes_duration'):
            EntryParsed.enclosures[0].duration = entry['itunes_duration']

    return EntryParsed


def surrogate_len(s: str) -> int:
    return len(add_surrogate(s))


def sort_entities(entities: Sequence[TypeMessageEntity]) -> list[TypeMessageEntity]:
    entities = list(entities)
    _entities = []
    while entities:
        e = entities.pop(0)
        is_duplicated = any(compare_entity(e, _e) for _e in entities)
        if not is_duplicated:
            _entities.append(e)
    return sorted(_entities, key=lambda entity: entity.offset)


def is_position_within_entity(pos: int, entity: TypeMessageEntity) -> bool:
    return entity.offset <= pos < entity.offset + entity.length


def filter_entities_by_position(pos: int, entities: Sequence[TypeMessageEntity]) -> list[TypeMessageEntity]:
    return [entity for entity in entities if is_position_within_entity(pos, entity)]


def filter_entities_by_range(start: int, end: int, entities: Sequence[TypeMessageEntity]) -> list[TypeMessageEntity]:
    return [entity for entity in entities if start <= entity.offset < end]


def copy_entity(entity: TypeMessageEntity) -> TypeMessageEntity:
    entity_dict = entity.to_dict()
    del entity_dict['_']
    return type(entity)(**entity_dict)


def copy_entities(entities: Sequence[TypeMessageEntity]) -> list[TypeMessageEntity]:
    return [copy_entity(entity) for entity in entities]


def compare_entity(a: TypeMessageEntity, b: TypeMessageEntity, ignore_position: bool = False) -> bool:
    if type(a) != type(b):
        return False

    a_dict = a.to_dict()
    b_dict = b.to_dict()
    if ignore_position:
        for d in (a_dict, b_dict):
            for key in ('offset', 'length'):
                try:
                    del d[key]
                except KeyError:
                    pass

    return a_dict == b_dict


def merge_contiguous_entities(entities: Sequence[TypeMessageEntity]) -> list[TypeMessageEntity]:
    if len(entities) < 2:
        return list(entities)

    merged_entities = []
    entities = sort_entities(entities)
    while entities:
        entity = entities.pop(0)
        start_pos = entity.offset
        end_pos = entity.offset + entity.length
        for contiguous_entity in (_entity
                                  for _entity in entities
                                  if (
                                          (start_pos <= _entity.offset <= end_pos
                                           or _entity.offset <= start_pos <= _entity.offset + _entity.length)
                                          and compare_entity(entity, _entity, ignore_position=True)
                                  )):
            new_start_pos = min(start_pos, contiguous_entity.offset)
            new_end_pos = max(end_pos, contiguous_entity.offset + contiguous_entity.length)
            entity = copy_entity(entity)
            entity.offset = new_start_pos
            entity.length = new_end_pos - new_start_pos
        merged_entities.append(entity)
    return merged_entities
