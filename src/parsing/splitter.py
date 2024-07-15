#  RSS to Telegram Bot
#  Copyright (C) 2022-2024  Rongrong <i@rong.moe>
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
from typing import Optional
from collections.abc import Sequence

from contextlib import suppress
from telethon.extensions.html import parse
from telethon.helpers import strip_text, add_surrogate, del_surrogate
from telethon.tl.types import TypeMessageEntity

from .utils import surrogate_len, copy_entity, copy_entities, merge_contiguous_entities, filter_entities_by_range


def get_plain_text_length(html: str) -> int:
    return len(parse(html)[0])


def split_entities(pos: int, entities: Sequence[TypeMessageEntity]) -> tuple[list[TypeMessageEntity],
                                                                             list[TypeMessageEntity]]:
    before = []
    after = []
    for entity in entities:
        if entity.offset < pos:
            end = entity.offset + entity.length
            if end <= pos:
                before.append(copy_entity(entity))
            else:
                before_entity = copy_entity(entity)
                before_entity.length = pos - entity.offset
                before.append(before_entity)
                after_entity = copy_entity(entity)
                after_entity.offset = pos
                after_entity.length = end - pos
                after.append(after_entity)
        else:
            after.append(copy_entity(entity))
    return before, after


def split_text(text: str,
               length_limit_queue: Optional[Sequence[int]] = None,
               length_limit_tail: int = 4096) -> list[str]:
    if length_limit_queue is None:
        length_limit_queue = []
    ret = []

    while text:
        curr_length_limit = length_limit_queue.pop(0) if length_limit_queue else length_limit_tail
        if len(text) <= curr_length_limit:
            ret.append(text)
            break
        for sep in ('\n', '。', '. ', '；', '; ', '，', ', ', '？', '? ', '！', '! ', '：', ': ', '\t', ' ', '\xa0', ''):
            sep_pos = text.rfind(sep, int(curr_length_limit * 0.5), curr_length_limit)
            if sep_pos != -1:
                ret.append(text[:sep_pos + len(sep)])
                text = text[sep_pos + len(sep):]
                break

    return ret


# noinspection PyProtectedMember
def text_and_format_entities_split(plain_text: str,
                                   format_entities: Sequence[TypeMessageEntity],
                                   length_limit_head: int = 4096,
                                   head_count: int = -1,
                                   length_limit_tail: int = 4096) \
        -> list[tuple[str, list[TypeMessageEntity]]]:
    format_entities = merge_contiguous_entities(copy_entities(format_entities))  # sort and merge

    chunks = []

    pending_text = plain_text
    pending_entities = format_entities[:]
    surrogate_len_sum = 0
    while pending_text:
        curr_length_limit = length_limit_head if head_count <= -1 or len(chunks) < head_count else length_limit_tail
        curr_length_limit = min(curr_length_limit, len(pending_text))
        # note: Telegram only allows up to 10000-Byte formatting entities per message
        # here the limit is set to 9500 Bytes to avoid possible problems
        if len(pending_text) == curr_length_limit and len(pending_entities) <= 100 and len(
                b''.join(x._bytes() for x in pending_entities)) < 9500:
            if surrogate_len_sum > 0:
                for entity in pending_entities:
                    entity.offset -= surrogate_len_sum
            chunks.append((pending_text, pending_entities))
            break
        for curr_length_limit in range(curr_length_limit, 0, -100):
            with suppress(OverflowError):
                for sep in ('\n', '。', '. ', '；', '; ', '，', ', ', '？', '? ', '！', '! ', '：', ': ', '\t',
                            ' ', '\xa0', ''):
                    sep_pos = pending_text.rfind(sep, int(curr_length_limit * 0.5), curr_length_limit)
                    if sep_pos != -1:
                        curr_text = pending_text[:sep_pos + len(sep)]
                        surrogate_end_pos = surrogate_len_sum + surrogate_len(curr_text)
                        _curr_entities = filter_entities_by_range(surrogate_len_sum, surrogate_end_pos,
                                                                  pending_entities)
                        if len(_curr_entities) > 100 or len(b''.join(x._bytes() for x in _curr_entities)) >= 9500:
                            raise OverflowError('Too many entities')
                        curr_entities, pending_entities = split_entities(surrogate_end_pos, pending_entities)
                        if surrogate_len_sum > 0:
                            for entity in curr_entities:
                                entity.offset -= surrogate_len_sum
                        surrogate_len_sum = surrogate_end_pos
                        chunks.append((curr_text, curr_entities))
                        pending_text = pending_text[sep_pos + len(sep):]
                        break
                break

    stripped_chunks = []
    for text, entity in chunks:
        text = strip_text(add_surrogate(text), entity)
        stripped_chunks.append((del_surrogate(text), entity))

    return stripped_chunks


def html_to_telegram_split(html: str,
                           length_limit_head: int = 4096,
                           head_count: int = -1,
                           length_limit_tail: int = 4096) -> list[tuple[str, list[TypeMessageEntity]]]:
    full_text, all_entities = parse(html)
    return text_and_format_entities_split(full_text, all_entities, length_limit_head, head_count, length_limit_tail)


def text_and_format_entities_concat(*plain_text_and_format_entities: tuple[str, list[TypeMessageEntity]]) \
        -> tuple[str, list[TypeMessageEntity]]:
    plain_text = ''
    format_entities = []
    surrogate_len_sum = 0
    for text, entities in plain_text_and_format_entities:
        plain_text += text
        new_entities = []
        for entity in entities:
            new_entity = copy_entity(entity)
            new_entity.offset += surrogate_len_sum
            new_entities.append(new_entity)
        surrogate_len_sum += surrogate_len(text)
        format_entities.extend(new_entities)

    format_entities = merge_contiguous_entities(format_entities)
    return plain_text, format_entities
