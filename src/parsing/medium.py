import asyncio
import re
from telethon.tl.types import InputMediaPhotoExternal, InputMediaDocumentExternal
from typing import List

from src import env, log, web
from src.parsing import post

logger = log.getLogger('RSStT.medium')

sizes = ['large', 'mw2048', 'mw1024', 'mw720', 'middle']
sizeParser = re.compile(r'(?P<domain>^https?://\w+\.sinaimg\.\S+/)'
                        r'(?P<size>large|mw2048|mw1024|mw720|middle)'
                        r'(?P<filename>/\w+\.\w+$)')
serverParser = re.compile(r'(?P<url_prefix>^https?://[a-zA-Z_-]+)'
                          r'(?P<server_id>\d)'
                          r'(?P<url_suffix>\.sinaimg\.\S+$)')

_web_semaphore = asyncio.BoundedSemaphore(5)

class Medium:
    type = 'medium_base_class'
    max_size = 20971520

    def __init__(self, url: str):
        self.url = url
        self.original_url = url
        self.valid = None
        self._server_change_count = 0

    def telegramize(self):
        pass

    def get_link(self, only_invalid: bool = True):
        return post.Link(self.type, param=self.original_url) if not (self.valid and only_invalid) else None

    def get_url(self):
        return self.url

    def invalidate(self):
        self.valid = False

    async def validate(self):  # warning: only design for weibo
        if self.valid is not None:  # already validated
            return

        max_size = self.max_size
        url = self.url
        try:
            size, width, height = await get_medium_info(url)
            if size is None:
                raise IOError
        except Exception as e:
            logger.debug(f'Dropped medium {url}: can not be fetched: ' + str(e), exc_info=e)
            self.valid = False
            return

        if not (0.05 < width / height < 20):  # always invalid
            self.valid = False
            return

        if size <= max_size and width + height < 10000:  # valid
            self.valid = True
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
        await self.validate()

    def __bool__(self):
        if self.valid is None:
            raise TypeError('You must validate a medium before judging its validation')
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
        return InputMediaPhotoExternal(self.url)

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
        return InputMediaDocumentExternal(self.url)


class Animation(Medium):
    type = 'animation'

    def telegramize(self):
        return InputMediaDocumentExternal(self.url)


class Media:
    def __init__(self):
        self._media: List[Medium] = []

    def add(self, medium: Medium):
        if medium in self._media:
            return
        self._media.append(medium)

    def invalidate_all(self):
        any(map(lambda m: m.invalidate(), self._media))

    async def validate(self):
        if not self._media:
            return
        await asyncio.gather(*(medium.validate() for medium in self._media))

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

    def __len__(self):
        return len(self._media)

    def __bool__(self):
        return bool(self._media)


async def get_medium_info(url):
    session = await web.get_session()
    try:
        async with _web_semaphore:
            async with session.get(url) as response:
                size = int(response.headers.get('Content-Length', 256))
                content_type = response.headers.get('Content-Type')

                height = width = -1
                if content_type != 'image/jpeg' and url.find('jpg') == -1 and url.find('jpeg') == -1:  # if not jpg
                    return size, width, height

                pic_header = await response.content.read(min(256, size))
    finally:
        await session.close()

    pointer = -1
    for marker in (b'\xff\xc2', b'\xff\xc1', b'\xff\xc0'):
        p = pic_header.find(marker)
        if p != -1:
            pointer = p
    if pointer != -1:
        width = int(pic_header[pointer + 7:pointer + 9].hex(), 16)
        height = int(pic_header[pointer + 5:pointer + 7].hex(), 16)

    return size, width, height
