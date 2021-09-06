from typing import List

import requests
import re
import telegram
from requests.adapters import HTTPAdapter

import env
import post

# getPic = re.compile(r'<img[^>]*\bsrc="([^"]*)"')
# getVideo = re.compile(r'<video[^>]*\bsrc="([^"]*)"')
# getSize = re.compile(r'^Content-Length: (\d+)$', re.M)
sizes = ['large', 'mw2048', 'mw1024', 'mw720', 'middle']
sizeParser = re.compile(r'(?P<domain>^https?://\w+\.sinaimg\.\S+/)'
                        r'(?P<size>large|mw2048|mw1024|mw720|middle)'
                        r'(?P<filename>/\w+\.\w+$)')
serverParser = re.compile(r'(?P<url_prefix>^https?:\/\/[a-zA-Z_-]+)'
                          r'(?P<server_id>\d)'
                          r'(?P<url_suffix>\.sinaimg\.\S+$)')


class Medium:
    type = 'medium_base_class'
    max_size = 5242880

    def __init__(self, url: str):
        self.url = url
        self.original_url = url
        self.valid = True
        self._validate()

    def telegramize(self):
        pass

    def get_link(self, only_invalid: bool = True):
        return post.Link(self.type, param=self.original_url) if not (self.valid and only_invalid) else None

    def get_url(self):
        return self.url

    def invalidate(self):
        self.valid = False

    def _validate(self):  # warning: only design for weibo
        max_size = self.max_size
        url = self.url
        try:
            size, width, height = get_medium_info(url)
        except Exception as e:
            print('\t\t- Get medium failed, dropped.\n'
                  f'\t\t\t- {url}\n'
                  f'\t\t\t\t- {e}')
            self.valid = False
            return

        if size <= max_size and height <= 10000:  # valid
            return

        if not sizeParser.search(url):  # is not a weibo pic
            # TODO: reduce non-weibo pic size
            print('\t\t- Medium too large, dropped: non-weibo medium.\n'
                  f'\t\t\t- {url}')
            self.valid = False
            return

        parsed = sizeParser.search(url).groupdict()
        if parsed['size'] == sizes[-1]:
            print('\t\t- Medium too large, dropped: reduced, but still too large.\n'
                  f'\t\t\t- {url}')
            self.valid = False
            return
        self.url = parsed['domain'] + sizes[sizes.index(parsed['size']) + 1] + parsed['filename']
        self._validate()

    def __bool__(self):
        return self.valid

    def __eq__(self, other):
        return type(self) == type(other) and self.original_url == other.original_url

    def change_sinaimg_server(self):
        return False


class Image(Medium):
    type = 'image'
    max_size = 5242880

    def telegramize(self):
        return telegram.InputMediaPhoto(self.url)

    def change_sinaimg_server(self):
        if not serverParser.search(self.url):  # is not a weibo pic
            return False

        parsed = serverParser.search(self.url).groupdict()
        new_server_id = int(parsed['server_id']) + 1
        if new_server_id > 4:
            new_server_id = 1
        self.url = f"{parsed['url_prefix']}{new_server_id}{parsed['url_suffix']}"
        return True


class Video(Medium):
    type = 'video'
    max_size = 20971520

    def telegramize(self):
        return telegram.InputMediaVideo(self.url)


def get_medium_info(url):
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=1))
    session.mount('https://', HTTPAdapter(max_retries=1))

    with session.get(url, timeout=(5, 5), proxies=env.requests_proxies, stream=True) as response:
        size = int(response.headers['Content-Length']) if 'Content-Length' in response.headers else -1
        content_type = response.headers.get('Content-Type')
        pic_header = response.raw.read(min(256, size))

    height = width = -1
    if content_type != 'image/jpeg' and url.find('jpg') == -1 and url.find('jpeg') == -1:  # if not jpg
        return size, width, height

    pointer = -1
    for marker in (b'\xff\xc2', b'\xff\xc1', b'\xff\xc0'):
        p = pic_header.find(marker)
        if p != -1:
            pointer = p
    if pointer != -1:
        width = int(pic_header[pointer + 7:pointer + 9].hex(), 16)
        height = int(pic_header[pointer + 5:pointer + 7].hex(), 16)

    return size, width, height


class Media:
    def __init__(self):
        self._media: List[Medium] = []
        self._server_change_count = 0

    def add(self, medium: Medium):
        if medium in self._media:
            return
        self._media.append(medium)

    def invalidate_all(self):
        any(map(lambda m: m.invalidate(), self._media))

    def get_valid_media(self):
        return tuple(m for m in self._media if m)

    def get_invalid_link(self):
        return tuple(m.get_link(only_invalid=True) for m in self._media if not m)

    def change_all_sinaimg_server(self):
        if self._server_change_count < 3 and sum(map(lambda m: m.change_sinaimg_server(), self._media)):
            self._server_change_count += 1
            return True
        return False
