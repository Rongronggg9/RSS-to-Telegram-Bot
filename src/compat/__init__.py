#  RSS to Telegram Bot
#  Copyright (C) 2022-2025  Rongrong <i@rong.moe>
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

import sys

if sys.version_info < (3, 9):
    raise RuntimeError("This bot requires Python 3.9 or later")

import listparser.opml

from .listparser_opml_mixin import OpmlMixin
from .utils import (
    INT64_T_MAX,
    nullcontext,
    AiohttpUvloopTransportHotfix,
    ssl_create_default_context,
    parsing_utils_html_validator_minify,
    cached_async,
    bozo_exception_removal_wrapper,
)

__all__ = [
    "INT64_T_MAX",
    "nullcontext",
    "AiohttpUvloopTransportHotfix",
    "ssl_create_default_context",
    "parsing_utils_html_validator_minify",
    "cached_async",
    "bozo_exception_removal_wrapper",
]

# Monkey-patching `listparser.opml.OpmlMixin` to support `text` and `title_orig`
# https://github.com/kurtmckee/listparser/issues/71
listparser.opml.OpmlMixin.start_opml_outline = OpmlMixin.start_opml_outline
