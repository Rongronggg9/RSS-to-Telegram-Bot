import requests
import re
import telegram
from requests.adapters import HTTPAdapter
from typing import List

import log
import env
import post

logger = log.getLogger('RSStT.medium')

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
    max_size = 20971520

    def __init__(self, url: str):
        self.url = url
        self.original_url = url
        self.valid = True
        self._validate()
        self._server_change_count = 0

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
            logger.debug(f'Dropped medium {url}: can not be fetched.')
            self.valid = False
            return

        if not (0.05 < width / height < 20):  # always invalid
            self.valid = False
            return

        if size <= max_size and width + height < 10000:  # valid
            return

        if not sizeParser.search(url):  # invalid but is not a weibo img
            # TODO: reduce non-weibo pic size
            logger.debug(f'Dropped medium {url}: invalid.')
            self.valid = False
            return

        parsed = sizeParser.search(url).groupdict()  # invalid and is a weibo img
        if parsed['size'] == sizes[-1]:
            logger.debug(f'Dropped medium {url}: invalid.')
            self.valid = False
            return
        self.url = parsed['domain'] + sizes[sizes.index(parsed['size']) + 1] + parsed['filename']
        self._validate()

    def __bool__(self):
        return self.valid

    def __eq__(self, other):
        return type(self) == type(other) and self.original_url == other.original_url

    def change_server(self):
        if self._server_change_count >= 1:
            return False
        self._server_change_count += 1
        self.url = env.IMG_RELAY_SERVER + self.url
        return True


class Image(Medium):
    type = 'image'
    max_size = 5242880

    def telegramize(self):
        return telegram.InputMediaPhoto(self.url)

    def change_server(self):
        if not serverParser.search(self.url):  # is not a weibo img
            return super().change_server()

        if self._server_change_count >= 4:
            return False
        self._server_change_count += 1
        parsed = serverParser.search(self.url).groupdict()
        new_server_id = int(parsed['server_id']) + 1
        if new_server_id > 4:
            new_server_id = 1
        self.url = f"{parsed['url_prefix']}{new_server_id}{parsed['url_suffix']}"
        return True


class Video(Medium):
    type = 'video'

    def telegramize(self):
        return telegram.InputMediaVideo(self.url)


class Animation(Medium):
    type = 'animation'

    def telegramize(self):
        return telegram.InputMediaAnimation(self.url)  # hmm, you don't need it


def get_medium_info(url):
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=1))
    session.mount('https://', HTTPAdapter(max_retries=1))

    response = session.get(url, timeout=(5, 5), proxies=env.REQUESTS_PROXIES, stream=True, headers=env.REQUESTS_HEADERS)
    size = int(response.headers.get('Content-Length', 256))
    content_type = response.headers.get('Content-Type')

    height = width = -1
    if content_type != 'image/jpeg' and url.find('jpg') == -1 and url.find('jpeg') == -1:  # if not jpg
        response.close()
        return size, width, height

    pic_header = response.raw.read(min(256, size))
    response.close()
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

    def add(self, medium: Medium):
        if medium in self._media:
            return
        self._media.append(medium)

    def invalidate_all(self):
        any(map(lambda m: m.invalidate(), self._media))

    def get_valid_media(self):
        result = []
        gifs = []
        for medium in self._media:
            if not medium:
                continue
            if medium.type == 'animation':
                # if len(result) > 0:
                #     yield {'type': result[0].type, 'media': result[0]} if len(result) == 1 \
                #         else {'type': 'media_group', 'media': result}
                #     result = []
                # yield {'type': 'animation', 'media': medium}
                gifs.append({'type': 'animation', 'media': medium})
                continue
            result.append(medium)
            if len(result) == 10:
                yield {'type': 'media_group', 'media': result}
                result = []
        if result:
            yield {'type': result[0].type, 'media': result[0]} if len(result) == 1 \
                else {'type': 'media_group', 'media': result}
        for gif in gifs:
            yield gif

    def get_invalid_link(self):
        return tuple(m.get_link(only_invalid=True) for m in self._media if not m)

    def change_all_server(self):
        if sum(map(lambda m: m.change_server(), self._media)):
            return True
        return False
