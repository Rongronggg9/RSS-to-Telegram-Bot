#  RSS to Telegram Bot
#  Copyright (C) 2023-2025  Rongrong <i@rong.moe>
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

import copy

import listparser.common
import listparser.opml


class OpmlMixin(listparser.opml.OpmlMixin):
    """
    Add `title_orig`.

    Originated from listparser v0.20 (MIT License)
    https://github.com/kurtmckee/listparser/blob/v0.20/src/listparser/opml.py#L21-L76
    Copyright 2009-2024 Kurt McKee <contactme@kurtmckee.org>
    Copyright 2023-2024 RSS to Telegram Bot contributors
    Distributed along with RSS to Telegram Bot under AGPLv3 License
    """

    def start_opml_outline(self, attrs: dict[str, str]) -> None:
        # Find an appropriate title in @text or @title (else empty)
        # ================ DIFF ================
        # if attrs.get("text", "").strip():
        #     title = attrs["text"].strip()
        # else:
        #     title = attrs.get("title", "").strip()
        text = attrs.get("text", "").strip()
        title_orig = attrs.get("title", "").strip()
        title = text or title_orig

        url = None
        append_to = None

        # Determine whether the outline is a feed or subscription list
        if "xmlurl" in attrs:
            # It's a feed
            url = attrs.get("xmlurl", "").strip()
            append_to = "feeds"
            if attrs.get("type", "").strip().lower() == "source":
                # Actually, it's a subscription list!
                append_to = "lists"
        elif attrs.get("type", "").lower() in ("link", "include"):
            # It's a subscription list
            append_to = "lists"
            url = attrs.get("url", "").strip()
        elif title:
            # Assume that this is a grouping node
            self.hierarchy.append(title)
            return
        # Look for an opportunity URL
        if not url and "htmlurl" in attrs:
            url = attrs["htmlurl"].strip()
            append_to = "opportunities"
        if not url:
            # Maintain the hierarchy
            self.hierarchy.append("")
            return
        if url not in self.found_urls and append_to:
            # This is a brand-new URL
            # ================ DIFF ================
            # obj = common.SuperDict({"url": url, "title": title})
            obj = listparser.common.SuperDict({"url": url, "title": title, "text": text, "title_orig": title_orig})
            self.found_urls[url] = (append_to, obj)
            self.harvest[append_to].append(obj)
        else:
            obj = self.found_urls[url][1]

        # Handle categories and tags
        obj.setdefault("categories", [])
        if "category" in attrs.keys():
            for i in attrs["category"].split(","):
                tmp = [j.strip() for j in i.split("/") if j.strip()]
                if tmp and tmp not in obj["categories"]:
                    obj["categories"].append(tmp)
        # Copy the current hierarchy into `categories`
        if self.hierarchy and self.hierarchy not in obj["categories"]:
            obj["categories"].append(copy.copy(self.hierarchy))
        # Copy all single-element `categories` into `tags`
        obj["tags"] = [i[0] for i in obj["categories"] if len(i) == 1]

        self.hierarchy.append("")
