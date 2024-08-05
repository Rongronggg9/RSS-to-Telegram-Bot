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
from typing import Optional, Sequence, Union, Final, Iterable

import re
import string
from contextlib import suppress
from bs4 import BeautifulSoup
from bs4.element import Tag
from html import unescape
from emoji import emojize
from telethon.tl.types import TypeMessageEntity
from functools import partial
from urllib.parse import urljoin
from itertools import chain

from .weibo_emojify_map import EMOJIFY_MAP
from .. import log
from ..aio_helper import run_async
from ..compat import parsing_utils_html_validator_minify, INT64_T_MAX

logger = log.getLogger('RSStT.parsing')

# noinspection SpellCheckingInspection
SPACES: Final[str] = (
    # all characters here, except for \u200c, \u200d and \u2060, are converted to space on TDesktop, but Telegram
    # Android preserves all
    ' '  # '\x20', SPACE
    '\xa0'  # NO-BREAK SPACE
    '\u2002'  # EN SPACE
    '\u2003'  # EM SPACE
    '\u2004'  # THREE-PER-EM SPACE
    '\u2005'  # FOUR-PER-EM SPACE
    '\u2006'  # SIX-PER-EM SPACE
    '\u2007'  # FIGURE SPACE
    '\u2008'  # PUNCTUATION SPACE
    '\u2009'  # THIN SPACE
    '\u200a'  # HAIR SPACE
    '\u200b'  # ZERO WIDTH SPACE, ZWSP
    # '\u200c'  # ZERO WIDTH NON-JOINER, ZWNJ, important for emoji or some languages
    # '\u200d'  # ZERO WIDTH JOINER, ZWJ, important for emoji or some languages
    '\u202f'  # NARROW NO-BREAK SPACE
    '\u205f'  # MEDIUM MATHEMATICAL SPACE, MMSP
    # '\u2060'  # WORD JOINER
    '\u3000'  # IDEOGRAPHIC SPACE
)
INVALID_CHARACTERS: Final[str] = (
    # all characters here are converted to space server-side
    '\x00'  # NULL
    '\x01'  # START OF HEADING
    '\x02'  # START OF TEXT
    '\x03'  # END OF TEXT
    '\x04'  # END OF TRANSMISSION
    '\x05'  # ENQUIRY
    '\x06'  # ACKNOWLEDGE
    '\x07'  # BELL
    '\x08'  # BACKSPACE
    '\x09'  # '\t', # HORIZONTAL TAB
    '\x0b'  # LINE TABULATION
    '\x0c'  # FORM FEED
    '\x0e'  # SHIFT OUT
    '\x0f'  # SHIFT IN
    '\x10'  # DATA LINK ESCAPE
    '\x11'  # DEVICE CONTROL ONE
    '\x12'  # DEVICE CONTROL TWO
    '\x13'  # DEVICE CONTROL THREE
    '\x14'  # DEVICE CONTROL FOUR
    '\x15'  # NEGATIVE ACKNOWLEDGE
    '\x16'  # SYNCHRONOUS IDLE
    '\x17'  # END OF TRANSMISSION BLOCK
    '\x18'  # CANCEL
    '\x19'  # END OF MEDIUM
    '\x1a'  # SUBSTITUTE
    '\x1b'  # ESCAPE
    '\x1c'  # FILE SEPARATOR
    '\x1d'  # GROUP SEPARATOR
    '\x1e'  # RECORD SEPARATOR
    '\x1f'  # UNIT SEPARATOR
    '\u2028'  # LINE SEPARATOR
    '\u2029'  # PARAGRAPH SEPARATOR
)
CHARACTERS_TO_ESCAPE_IN_HASHTAG: Final[str] = ''.join(
    # all characters here will be replaced with '_'
    sorted(set(SPACES + INVALID_CHARACTERS + string.punctuation + string.whitespace))
)

# false positive:
# noinspection RegExpUnnecessaryNonCapturingGroup
EMOJIFY_RE: Final[re.Pattern] = re.compile(rf'\[(?:{"|".join(re.escape(phrase[1:-1]) for phrase in EMOJIFY_MAP)})]')
emojifyReSub = partial(EMOJIFY_RE.sub, lambda match: EMOJIFY_MAP[match.group(0)])

replaceInvalidCharacter = partial(re.compile(rf'[{INVALID_CHARACTERS}]').sub, ' ')  # use initially
replaceSpecialSpace = partial(re.compile(rf'[{SPACES[1:]}]').sub, ' ')  # use carefully
stripBr = partial(re.compile(r'\s*<br\s*/?\s*>\s*').sub, '<br>')
stripLineEnd = partial(re.compile(rf'[{SPACES}]+\n').sub, '\n')  # use firstly
stripNewline = partial(re.compile(r'\n{3,}').sub, '\n\n')  # use secondly
stripAnySpace = partial(re.compile(r'\s+').sub, ' ')
escapeHashtag = partial(re.compile(rf'[{CHARACTERS_TO_ESCAPE_IN_HASHTAG}]+').sub, '_')
isAbsoluteHttpLink = re.compile(r'^https?://').match
isSmallIcon = re.compile(r'(width|height): ?(([012]?\d|30)(\.\d)?px|([01](\.\d)?|2)r?em)').search


class Enclosure:
    def __init__(self, url: str, length: Union[int, str], _type: str, duration: str = None, thumbnail: str = None):
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
        self.thumbnail = thumbnail


def resolve_relative_link(base: Optional[str], url: Optional[str]) -> str:
    if not base or not url or isAbsoluteHttpLink(url) or not isAbsoluteHttpLink(base):
        return url or ''
    return urljoin(base, url)


def emojify(xml):
    return emojifyReSub(
        emojize(xml, language='alias', variant='emoji_type')
    )


def is_emoticon(tag: Tag) -> bool:
    if tag.name != 'img':
        return False
    src = tag.get('src', '')
    alt, _class = tag.get('alt', ''), tag.get('class', '')
    style, width, height = tag.get('style', ''), tag.get('width', ''), tag.get('height', '')
    width = int(width) if width and width.isdigit() else INT64_T_MAX
    height = int(height) if height and height.isdigit() else INT64_T_MAX
    return (width <= 30 or height <= 30 or isSmallIcon(style)
            or 'emoji' in _class or 'emoticon' in _class or (alt.startswith(':') and alt.endswith(':'))
            or src.startswith('data:'))


def _html_validator(html: str) -> str:
    html = parsing_utils_html_validator_minify(html)
    html = stripBr(html)
    html = replaceInvalidCharacter(html)
    return html


async def html_validator(html: str) -> str:
    return await run_async(_html_validator, html, prefer_pool='thread')


def _bs_html_get_text(s: str) -> str:
    return BeautifulSoup(s, 'lxml').get_text()


async def ensure_plain(s: str, enable_emojify: bool = False) -> str:
    if not s:
        return s
    s = stripAnySpace(
        replaceSpecialSpace(
            replaceInvalidCharacter(
                await run_async(_bs_html_get_text, s, prefer_pool='thread')
                if '<' in s and '>' in s
                else unescape(s)
            )
        )
    ).strip()
    return emojify(s) if enable_emojify else s


async def parse_entry(entry, feed_link: Optional[str] = None):
    class EntryParsed:
        content: str = ''
        link: Optional[str] = None
        author: Optional[str] = None
        tags: Optional[list[str]] = None
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

    EntryParsed.content = await html_validator(content)
    EntryParsed.link = entry.get('link') or entry.get('guid')
    author = entry['author'] if ('author' in entry and type(entry['author']) is str) else None
    author = await ensure_plain(author) if author else None
    EntryParsed.author = author or None  # reject empty string
    # hmm, some entries do have no title, should we really set up a feed hospital?
    title = entry.get('title')
    title = await ensure_plain(title, enable_emojify=True) if title else None
    EntryParsed.title = title or None  # reject empty string
    if (tags := entry.get('tags')) and isinstance(tags, list):
        EntryParsed.tags = list(filter(None, (tag.get('term') for tag in tags)))

    enclosures = []

    if isinstance(entry.get('links'), list):
        for link in (link for link in entry['links'] if link.get('rel') == 'enclosure' and link.get('href')):
            enclosures.append(Enclosure(url=resolve_relative_link(feed_link, link['href']),
                                        length=link.get('length'),
                                        _type=link.get('type')))
        if enclosures and entry.get('itunes_duration'):
            enclosures[0].duration = entry['itunes_duration']

    if isinstance(entry.get('media_content'), list):
        enclosures_media = []
        for media in (media for media in entry['media_content'] if media.get('url')):
            media_type = media.get('type') or media.get('medium')
            if media_type and 'flash' in media_type:  # application/x-shockwave-flash or so on
                continue  # false media
            enclosures_media.append(Enclosure(url=resolve_relative_link(feed_link, media['url']),
                                              length=media.get('fileSize'),
                                              _type=media_type,
                                              duration=media.get('duration')))
        if enclosures_media:
            if isinstance(entry.get('media_thumbnail'), list) and entry['media_thumbnail'] \
                    and isinstance(entry['media_thumbnail'][0], dict):
                enclosures_media[0].thumbnail = entry['media_thumbnail'][0].get('url')
            enclosures.extend(enclosures_media)

    EntryParsed.enclosures = enclosures or None

    return EntryParsed


def surrogate_len(s: str) -> int:
    # in theory, the condition should be `0x10000 <= ord(c) <= 0x10FFFF`
    # but in practice, it is impossible to have a character with `ord(c) > 0x10FFFF`
    # >>> chr(0x110000)
    # ValueError: chr() arg not in range(0x110000)
    # >>> '\U00110000'
    # SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes in position 0-9: illegal Unicode character
    return sum(2 if 0x10000 <= ord(c) else 1
               for c in s)


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
    if type(a) is type(b):
        return False

    a_dict = a.to_dict()
    b_dict = b.to_dict()
    if ignore_position:
        for d in (a_dict, b_dict):
            for key in ('offset', 'length'):
                with suppress(KeyError):
                    del d[key]

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


def escape_hashtag(tag: str) -> str:
    return escapeHashtag(tag).strip('_')


def escape_hashtags(tags: Optional[Iterable[str]]) -> Iterable[str]:
    return filter(None, map(escape_hashtag, tags)) if tags else ()


def merge_tags(*tag_lists: Optional[Iterable[str]]) -> list[str]:
    return list(dict.fromkeys(chain(*tag_lists)))
