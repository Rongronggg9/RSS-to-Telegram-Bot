#  RSS to Telegram Bot
#  Copyright (C) 2025  Rongrong <i@rong.moe>
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

from typing import Optional, AbstractSet, Callable, Any

import lxml.html
import re
from yarl import URL

from .presets import ACCEPTABLE_URI_SCHEMES, TAG_ATTR_MAP_RSSTT


def _always_true():
    return True


class UriResolver:
    def __init__(
            self,
            allowed_schemes: Optional[AbstractSet[str]] = ...,
            tag_attr_map: Optional[dict[str, AbstractSet[str]]] = ...,
    ):
        self._allowed_schemes: AbstractSet[str] = (
            ACCEPTABLE_URI_SCHEMES
            if allowed_schemes is ...
            else allowed_schemes or set()
        )
        self._tag_attr_map: dict[str, AbstractSet[str]] = (
            TAG_ATTR_MAP_RSSTT
            if tag_attr_map is ...
            else tag_attr_map or {}
        )
        self._scheme_matcher: Callable[[str], Optional[Any]] = (
            re.compile(
                f'^({"|".join(self._allowed_schemes)}):',
                re.IGNORECASE,
            ).match
            if self._allowed_schemes
            else _always_true
        )
        self._xpath: str = '|'.join((
            '//{tag_name}[{attrs}]'.format(
                tag_name=tag_name,
                attrs=' or '.join((
                    f'@{attr_name}'
                    for attr_name in attr_names
                ))
            )
            for tag_name, attr_names in self._tag_attr_map.items()
        ))

    def resolve(self, html: str, base: str, type_: str) -> str:
        if not base:
            return html

        if '<' not in html:
            # Not an HTML.
            return html

        xpath = self._xpath
        if not xpath:
            # Nothing to resolve.
            return html

        scheme_matcher = self._scheme_matcher
        if not scheme_matcher(base):
            # The base is relative or without an allowed scheme.
            return html

        tag_attr_map = self._tag_attr_map

        base_url = URL(base)

        html_tree = lxml.html.fragment_fromstring(html, create_parent='URI_RESOLVER')

        allowed_schemes = self._allowed_schemes
        element: lxml.html.HtmlElement
        for element in html_tree.xpath(xpath):
            for attr_name in tag_attr_map[element.tag]:
                relative = element.attrib.get(attr_name)
                if relative is None:
                    continue

                relative = relative.strip()

                if not relative:
                    element.attrib[attr_name] = base
                    continue

                if scheme_matcher(relative):
                    # Absolute URL with an allowed scheme, happy path.
                    continue

                relative_url = URL(relative)
                if relative_url.absolute:
                    # Absolute URL without an allowed scheme, erase it.
                    element.attrib[attr_name] = ''
                    continue

                absolute_url = base_url.join(relative_url)
                element.attrib[attr_name] = (
                    absolute_url.human_repr()
                    if absolute_url.scheme in allowed_schemes
                    else ''
                )

        return lxml.html.tostring(
            html_tree,
            encoding='unicode',
            method='xml' if type_ == 'application/xhtml+xml' else 'html',
        ).partition('<URI_RESOLVER>')[2].rpartition('</URI_RESOLVER>')[0]


uri_resolver = UriResolver()


def resolve_relative_uris(html_source, base_uri, encoding, type_):
    return uri_resolver.resolve(html_source, base_uri, type_)
