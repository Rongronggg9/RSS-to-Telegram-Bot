from __future__ import annotations
from typing import Optional, Sequence, Union

import re
import json
from emoji import emojize
from telethon.tl.types import TypeMessageEntity
from telethon.helpers import add_surrogate
from functools import partial

from src import log

logger = log.getLogger('RSStT.parsing')

stripLineEnd = partial(re.compile(r'[ 　\xa0\t\r\u200b\u2006\u2028\u2029]+\n').sub, '\n')  # use firstly
stripNewline = partial(re.compile(r'[\f\n\u2028\u2029]{3,}').sub, '\n\n')  # use secondly
stripAnySpace = partial(re.compile(r'\s+').sub, ' ')


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
with open('src/parsing/emojify.json', 'r', encoding='utf-8') as emojify_json:
    emoji_dict = json.load(emojify_json)


def is_absolute_link(link: str) -> bool:
    return link.startswith('http://') or link.startswith('https://')


def emojify(xml):
    xml = emojize(xml, use_aliases=True)
    for emoticon, emoji in emoji_dict.items():
        # emojify weibo emoticons, get all here: https://api.weibo.com/2/emotions.json?source=1362404091
        xml = xml.replace(f'[{emoticon}]', emoji)
    return xml


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

    EntryParsed.content = content
    EntryParsed.link = entry.get('link') or entry.get('guid')
    EntryParsed.author = entry['author'] if ('author' in entry and type(entry['author']) is str) else None
    # hmm, some entries do have no title, should we really set up a feed hospital?
    EntryParsed.title = entry.get('title')
    if isinstance(entry.get('links'), list):
        EntryParsed.enclosures = []
        for link in entry['links']:
            if link.get('rel') == 'enclosure':
                EntryParsed.enclosures.append(Enclosure(url=link.get('href'),
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
