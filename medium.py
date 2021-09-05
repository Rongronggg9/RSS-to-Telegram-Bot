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
sizeParser = re.compile(r'(^https?://\w+\.sinaimg\.\S+/)(large|mw2048|mw1024|mw720|middle)(/\w+\.\w+$)')


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

        if size > max_size or width + height > 10000:  # too large
            if sizeParser.search(url):  # is a large weibo pic
                parsed = sizeParser.search(url).groups()
                if parsed[1] == sizes[-1]:
                    print('\t\t- Medium too large, dropped: reduced, but still too large.\n'
                          f'\t\t\t- {url}')
                    self.valid = False
                    return
                self.url = parsed[0] + sizes[sizes.index(parsed[1]) + 1] + parsed[2]
                self._validate()
                return
            # TODO: reduce non-weibo pic size
            print('\t\t- Medium too large, dropped: non-weibo medium.\n'
                  f'\t\t\t- {url}')
            self.valid = False
            return

    def __bool__(self):
        return self.valid


class Image(Medium):
    type = 'image'
    max_size = 5242880

    def telegramize(self):
        return telegram.InputMediaPhoto(self.url)


class Video(Medium):
    type = 'video'
    max_size = 20971520

    def telegramize(self):
        return telegram.InputMediaVideo(self.url)


def get_medium_info(url):
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=1))
    session.mount('https://', HTTPAdapter(max_retries=1))

    with session.get(url, timeout=(10, 10), proxies=env.requests_proxies, stream=True) as response:
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
