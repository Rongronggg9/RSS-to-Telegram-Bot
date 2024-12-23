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
from typing import Optional, Sequence, Union, Final, Iterable, Iterator

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
from itertools import chain, count, groupby, islice, zip_longest

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
INVALID_CHARACTERS_IN_HASHTAG: Final[str] = ''.join(
    sorted(
        # Known characters that break hashtags.
        set(chain(
            SPACES, INVALID_CHARACTERS, string.punctuation, string.whitespace,
            '・',  # Though '・' breaks hashtags, it is not the case of '·'.
        ))
        # Characters included in `string.punctuation` but valid in hashtags.
        - set(
            '@'  # Used in "chat-specific hashtags".
        )
    )
)

escapeSpecialCharInReSet = partial(
    re.compile(r'([\\\-\[\]])').sub,  # \-[]
    r'\\\1',
)


def __merge_chars_into_ranged_set(sorted_chars: str) -> str:
    monotonic: Iterator[int] = count()
    groups: Iterator[str] = (
        ''.join(g)
        for _, g in groupby(sorted_chars, key=lambda char: ord(char) - next(monotonic))
    )
    ranged_set: str = ''.join(
        f'{escapeSpecialCharInReSet(g[0])}-{escapeSpecialCharInReSet(g[-1])}'
        # Merging 0~1 chars results in an invalid set, while merging two chars is meaningless.
        if len(g) > 2
        else escapeSpecialCharInReSet(g)
        for g in groups
    )
    assert re.fullmatch(rf'[{ranged_set}]+', sorted_chars)
    return ranged_set


# false positive:
# noinspection RegExpUnnecessaryNonCapturingGroup
EMOJIFY_RE: Final[re.Pattern] = re.compile(rf'\[(?:{"|".join(re.escape(phrase[1:-1]) for phrase in EMOJIFY_MAP)})]')
emojifyReSub = partial(
    EMOJIFY_RE.sub,
    lambda match: EMOJIFY_MAP[match.group(0)],
)

replaceInvalidCharacter = partial(
    re.compile(rf'[{__merge_chars_into_ranged_set(INVALID_CHARACTERS)}]').sub,
    ' ',
)  # use initially
replaceSpecialSpace = partial(
    re.compile(rf'[{__merge_chars_into_ranged_set(SPACES[1:])}]').sub,
    ' ',
)  # use carefully
stripBr = partial(
    re.compile(r'\s*<br\s*/?\s*>\s*').sub,
    '<br>',
)
stripLineEnd = partial(
    re.compile(rf'[{__merge_chars_into_ranged_set(SPACES)}]+\n').sub,
    '\n',
)  # use firstly
stripNewline = partial(
    re.compile(r'\n{3,}').sub,
    '\n\n',
)  # use secondly
stripAnySpace = partial(
    re.compile(r'\s+').sub,
    ' ',
)
escapeHashtag = partial(
    re.compile(rf'[{__merge_chars_into_ranged_set(INVALID_CHARACTERS_IN_HASHTAG)}]+').sub,
    '_',
)
isAbsoluteHttpLink = re.compile(r'^https?://').match
isSmallIcon = re.compile(r'(width|height): ?(([012]?\d|30)(\.\d)?px|([01](\.\d)?|2)r?em)').search


class Enclosure:
    def __init__(
            self,
            url: str,
            length: Union[int, str] = None,
            _type: str = '',
            duration: str = None,
            thumbnail: str = None,
    ):
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

    content = (
            entry.get('content')  # Atom: <content>; JSON Feed: .content_html, .content_text
            or entry.get('summary', '')  # Atom: <summary>; RSS: <description>
    )

    if isinstance(content, list) and len(content) > 0:  # Atom
        for _content in content:
            content_type = _content.get('type', '')
            if 'html' in content_type or 'xml' in content_type:
                content = _content
                break
        else:
            content = content[0]
        content = content.get('value', '')
    elif isinstance(content, dict):  # JSON Feed
        # TODO: currently feedparser always prefer content_text rather than content_html, we'd like to change that
        content = content.get('value', '')

    EntryParsed.content = await html_validator(content)
    EntryParsed.link = entry.get('link') or entry.get('guid')

    if (author := entry.get('author')) and isinstance(author, str):
        EntryParsed.author = await ensure_plain(author) or None
    if (title := entry.get('title')) and isinstance(title, str):
        EntryParsed.title = await ensure_plain(title, enable_emojify=True) or None
    if (tags := entry.get('tags')) and isinstance(tags, list) and len(tags) > 0:
        EntryParsed.tags = list(filter(
            None,
            (tag.get('term') for tag in tags)
        ))

    # Collect enclosures (attachment in RSS entries)
    enclosures = []

    # RSS/Atom
    if (links := entry.get('links')) and isinstance(links, list) and len(links) > 0:
        for link in links:
            if link.get('rel') == 'enclosure' and (link_href := link.get('href')):
                enclosures.append(
                    Enclosure(
                        url=resolve_relative_link(feed_link, link_href),
                        length=link.get('length'),
                        _type=link.get('type'),
                    )
                )

    # Media RSS
    # TODO: utilize <media:group> once feedparser supports them, see https://github.com/kurtmckee/feedparser/issues/195
    if (media_content := entry.get('media_content')) and isinstance(media_content, list) and len(media_content) > 0:
        if not ((media_thumbnail := entry.get('media_thumbnail')) and isinstance(media_thumbnail, list)):
            media_thumbnail = ()
        for media, thumbnail in zip_longest(
                media_content,
                islice(media_thumbnail, len(media_content)),
                fillvalue={},
        ):
            if (media_type := media.get('type') or media.get('medium')) and 'flash' in media_type:
                # Skip application/x-shockwave-flash if it has no thumbnail
                if not (thumbnail_url := thumbnail.get('url')):
                    continue
                # Or replace it with is thumbnail otherwise
                enclosures.append(
                    Enclosure(
                        url=resolve_relative_link(feed_link, thumbnail_url),
                        _type=thumbnail.get('type', 'image'),
                    )
                )
                continue
            if not (media_url := media.get('url')):
                continue
            enclosures.append(
                Enclosure(
                    url=resolve_relative_link(feed_link, media_url),
                    length=media.get('fileSize'),
                    _type=media_type,
                    duration=media.get('duration'),
                    thumbnail=thumbnail.get('url'),
                ),
            )

    if len(enclosures) == 1:
        single = enclosures[0]
        if single.duration is None and (itunes_duration := entry.get('itunes_duration')):
            single.duration = itunes_duration

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
    return list(dict.fromkeys(chain.from_iterable(tag_lists)))
