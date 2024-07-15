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
from typing import Optional, Union

__all__ = ["HtmlTree", "Text", "Link", "Bold", "Italic", "Underline", "Strike", "Blockquote", "Code", "Pre", "Br", "Hr",
           "ListItem", "OrderedList", "UnorderedList", "TypeTextContent"]

TypeTextContent = Union["Text", str, list["Text"]]


class Text:
    tag: Optional[str] = None
    attr: Optional[str] = None

    def __init__(self, content: TypeTextContent, param: Optional[str] = None, *_args, **_kwargs):
        if content is None:
            content = ''
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
        return type(self)(self.content.copy(), self.param, copy=True) if self.is_nested() else self

    def strip(self, deeper: bool = False, strip_l: Optional[bool] = True, strip_r: Optional[bool] = True):
        if not self.is_nested():  # str
            if strip_l:
                self.content.lstrip()
            if strip_r:
                self.content.rstrip()
            return
        if not self.is_listed():  # nested
            if deeper:
                self.content.strip()
            return
        # listed
        while strip_l and self.content and type(self.content[0]) is Br:
            self.content.pop(0)
        while strip_r and self.content and type(self.content[-1]) is Br:
            self.content.pop()
        if deeper:
            any(map(lambda text: text.strip(deeper=deeper, strip_l=strip_l, strip_r=strip_r), self.content))

    def lstrip(self, deeper: bool = False):
        self.strip(deeper=deeper, strip_r=False)

    def rstrip(self, deeper: bool = False):
        self.strip(deeper=deeper, strip_l=False)

    def is_empty(self, allow_whitespace: bool = False):
        if self.is_listed():
            return all(subText.is_empty(allow_whitespace=allow_whitespace) for subText in self.content)
        elif self.is_nested():
            return self.content.is_empty(allow_whitespace=allow_whitespace)
        else:
            return not (self.content if allow_whitespace else self.content and self.content.strip())

    def get_html(self, plain: bool = False) -> str:
        if self.is_listed():
            result = ''.join(subText.get_html(plain=plain) for subText in self.content)
        elif self.is_nested():
            result = self.content.get_html(plain=plain)
        else:
            result = self.content

        if not plain:
            if self.attr and self.param:
                return f'<{self.tag} {self.attr}="{self.param}">{result}</{self.tag}>'
            if self.tag:
                return f'<{self.tag}>{result}</{self.tag}>'
        return result

    def split_html(self, length_limit_head: int, head_count: int = -1, length_limit_tail: int = 4096) -> list:
        split_list = []
        if type(self.content) == list:
            curr_length = 0
            sub_text = None
            split_count = 0
            result = ''
            length = 0
            for sub_text in self.content:
                curr_length = len(sub_text)
                curr_length_limit = length_limit_head if head_count == -1 or split_count < head_count \
                    else length_limit_tail
                if length + curr_length >= curr_length_limit and result:
                    stripped = result.strip()
                    result = ''
                    length = 0
                    if stripped:
                        split_count += 1
                        curr_length_limit = length_limit_head if head_count == -1 or split_count < head_count \
                            else length_limit_tail
                        split_list.append(stripped)  # split
                if curr_length >= curr_length_limit:
                    for subSubText in sub_text.split_html(curr_length_limit):
                        split_count += 1
                        split_list.append(subSubText)  # split
                    continue
                length += curr_length
                result += sub_text.get_html()

            curr_length_limit = length_limit_head if head_count == -1 or split_count < head_count \
                else length_limit_tail
            if length < curr_length_limit and result:
                stripped = result.strip()
                if stripped:
                    split_list.append(stripped)  # split
            elif curr_length >= curr_length_limit and sub_text:
                split_list.extend(sub_text.split_html(curr_length_limit))  # split

            return split_list

        if type(self.content) == str:
            result = self.content
            if len(result) >= length_limit_head:
                split_list = [result[i:i + length_limit_head - 1]
                              for i in range(0, len(result), length_limit_head - 1)]  # split
        else:  # nested
            split_list = self.content.split_html(length_limit_head)  # split

        return [f'<{self.tag} {self.attr}={self.param}>{text}</{self.tag}>' if self.attr and self.param
                else (f'<{self.tag}>{text}</{self.tag}>' if self.tag
                      else text)
                for text in split_list]

    def find_instances(self, _class, shallow: Optional[bool] = False) -> Optional[list]:
        result = []
        if isinstance(self, _class):
            result.append(self)
        if self.is_listed():
            if shallow:
                return [subText for subText in self.content if isinstance(subText, _class)]
            for subText in self.content:
                instance = subText.find_instances(_class)
                if instance:
                    result.extend(instance)
            return result or None
        if self.is_nested():
            instance = self.content.find_instances(_class, shallow)
            if instance:
                result.extend(instance)
        return result or None

    def __len__(self):
        if type(self.content) == list:
            return sum(len(subText) for subText in self.content)
        return len(self.content)

    def __bool__(self):
        return bool(self.content)

    def __eq__(self, other):
        return type(self) == type(other) and self.content == other.content and self.param == other.param

    def __repr__(self):
        return f'{type(self).__name__}:{repr(self.content)}'

    def __str__(self):
        return self.get_html()


class HtmlTree(Text):
    pass


# ---- HTML tags super class ----
class TagWithParam(Text):
    def __init__(self, content: TypeTextContent, param: str, *_args, **_kwargs):
        super().__init__(content, param)


class TagWithOptionalParam(Text):
    pass


class TagWithoutParam(Text):
    def __init__(self, content: TypeTextContent, *_args, **_kwargs):
        super().__init__(content)


class ListParent(TagWithoutParam):
    pass


# ---- HTML tags ----
class Link(TagWithParam):
    tag = 'a'
    attr = 'href'


class Bold(TagWithoutParam):
    tag = 'b'


class Italic(TagWithoutParam):
    tag = 'i'


class Underline(TagWithoutParam):
    tag = 'u'


class Strike(TagWithoutParam):
    tag = 's'


class Blockquote(TagWithoutParam):
    tag = 'blockquote'


class Code(TagWithOptionalParam):
    tag = 'code'
    attr = 'class'


class Pre(TagWithoutParam):
    tag = 'pre'


class Br(TagWithoutParam):
    def __init__(self, count: int = 1, copy: bool = False, *_args, **_kwargs):
        if copy:
            super().__init__(self.content)
            return
        if not isinstance(count, int):
            count = 1
        super().__init__('\n' * count)

    def get_html(self, plain: bool = False):
        return '' if plain else super().get_html()


class Hr(TagWithoutParam):
    def __init__(self, *_args, **_kwargs):
        super().__init__('\n----------------------\n')

    def get_html(self, plain: bool = False):
        return '' if plain else super().get_html()


class ListItem(TagWithoutParam):
    def __init__(self, content, *_args, copy: bool = False, **_kwargs):
        super().__init__(content)
        if copy:
            return
        nested_lists = self.find_instances(ListParent)
        if not nested_lists:
            return
        for nested_list in nested_lists:
            nested_list.rstrip()
            nested_list_items = nested_list.find_instances(ListItem, shallow=True)
            if not nested_list_items:
                return
            for nested_list_item in nested_list_items:
                nested_list_item.content = [Text('    '), Text(nested_list_item.content)]
            nested_list_items[-1].rstrip(deeper=True)


class OrderedList(ListParent):
    def __init__(self, content, *_args, copy: bool = False, **_kwargs):
        super().__init__(content)
        if copy:
            return
        list_items = self.find_instances(ListItem, shallow=True)
        if not list_items:
            return
        for index, list_item in enumerate(list_items, start=1):
            list_item.content = [Bold(f'{index}. '), Text(list_item.content), Br()]


class UnorderedList(ListParent):
    def __init__(self, content, *_args, copy: bool = False, **_kwargs):
        super().__init__(content)
        if copy:
            return
        list_items = self.find_instances(ListItem, shallow=True)
        if not list_items:
            return
        for list_item in list_items:
            list_item.content = [Bold('● '), Text(list_item.content), Br()]
