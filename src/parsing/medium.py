from __future__ import annotations
from src.compat import Final
from typing import Optional, Union

import asyncio
import re
import PIL.Image
import PIL.ImageFile
from io import BytesIO
from telethon.tl.types import InputMediaPhotoExternal, InputMediaDocumentExternal

from src import env, log, web
from src.parsing.html_text import Link

PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True

logger = log.getLogger('RSStT.medium')

weibo_sizes = ['large', 'mw2048', 'mw1024', 'mw720', 'middle']
weibo_size_parser = re.compile(r'(?P<domain>^https?://wx\d\.sinaimg\.\w+/)'
                               r'(?P<size>\w+)'
                               r'(?P<filename>/\w+\.\w+$)').match
pixiv_sizes = ['original', 'master']
pixiv_size_parser = re.compile(r'(?P<url_prefix>^https?://i\.pixiv\.(cat|re)/img-)'
                               r'(?P<size>\w+)'
                               r'(?P<url_infix>/img/\d{4}/(\d{2}/){5})'
                               r'(?P<filename>\d+_p\d+)'
                               r'(?P<file_ext>\.\w+$)').match
weibo_server_parser = re.compile(r'(?P<url_prefix>^https?://wx)'
                                 r'(?P<server_id>\d)'
                                 r'(?P<url_suffix>\.sinaimg\.\S+$)').match
isTelegramCannotFetch = re.compile(r'^https?://(\w+\.)?telesco\.pe').match

IMAGE: Final = 'image'
VIDEO: Final = 'video'
ANIMATION: Final = 'animation'
MEDIUM_BASE_CLASS: Final = 'medium'
TypeMedium = Union[IMAGE, VIDEO, ANIMATION]

MEDIA_GROUP: Final = 'media_group'

IMAGE_MAX_SIZE: Final = 5242880
MEDIA_MAX_SIZE: Final = 20971520


class Medium:
    type = MEDIUM_BASE_CLASS
    max_size = MEDIA_MAX_SIZE

    def __init__(self, urls: Union[str, list[str]]):
        self.urls: list[str] = urls if isinstance(urls, list) else [urls]
        self.original_urls: tuple[str, ...] = tuple(self.urls)
        self.chosen_url: Optional[str] = self.urls[0]
        self.valid: Optional[bool] = None
        self._server_change_count: int = 0
        self.size = self.width = self.height = None

    def telegramize(self):
        raise NotImplementedError

    def get_link(self):
        return Link(self.type, param=self.original_urls[0])

    def get_url(self):
        return self.chosen_url

    async def invalidate(self) -> bool:
        if self.valid:
            self.valid = False
            return True
        return False

    async def validate(self):
        if self.valid is not None:  # already validated
            return

        for url in self.urls:
            medium_info = await get_medium_info(url, medium_type=self.type)
            if medium_info is None:
                continue
            self.size, self.width, self.height, self.valid = medium_info

            if self.valid:
                self.chosen_url = url
                if isTelegramCannotFetch(self.chosen_url):
                    await self.change_server()
                return

            # TODO: reduce non-weibo pic size

        logger.debug(f'Dropped medium {self.chosen_url}: invalid or fetch failed')
        self.valid = False

    def __bool__(self):
        if self.valid is None:
            raise RuntimeError('You must validate a medium before judging its validation')
        return self.valid

    def __eq__(self, other):
        return type(self) == type(other) and self.original_urls == other.original_urls

    async def change_server(self):
        if self._server_change_count >= 1:
            return False
        self._server_change_count += 1
        self.chosen_url = env.IMG_RELAY_SERVER + self.chosen_url
        # noinspection PyBroadException
        try:
            await web.get(url=self.chosen_url, semaphore=False, max_size=0)  # let the img relay sever cache the img
        except Exception:
            pass
        return True


class Image(Medium):
    type = IMAGE
    max_size = IMAGE_MAX_SIZE

    def __init__(self, url: Union[str, list[str]]):
        super().__init__(url)
        new_urls = []
        for url in self.urls:
            sinaimg_match = weibo_size_parser(url)
            pixiv_match = pixiv_size_parser(url)
            if not any([sinaimg_match, pixiv_match]):
                new_urls.append(url)
                continue
            if sinaimg_match:
                parsed_sinaimg = sinaimg_match.groupdict()  # is a weibo img
                for size_name in weibo_sizes:
                    new_url = parsed_sinaimg['domain'] + size_name + parsed_sinaimg['filename']
                    if new_url not in new_urls:
                        new_urls.append(new_url)
            elif pixiv_match:
                parsed_pixiv = pixiv_match.groupdict()  # is a pixiv img
                for size_name in pixiv_sizes:
                    new_url = parsed_pixiv['url_prefix'] + size_name + parsed_pixiv['url_infix'] \
                              + parsed_pixiv['filename'] + parsed_pixiv['file_ext']
                    if size_name == "master":
                        new_url = new_url.replace(parsed_pixiv['file_ext'], '_master1200.jpg')
                    if new_url not in new_urls:
                        new_urls.append(new_url)
            if url not in new_urls:
                new_urls.append(url)
        self.urls = new_urls

    def telegramize(self):
        return InputMediaPhotoExternal(self.chosen_url)

    async def change_server(self):
        if not weibo_server_parser(self.chosen_url):  # is not a weibo img
            return await super().change_server()

        self._server_change_count += 1
        if self._server_change_count >= 4:
            return False
        parsed = weibo_server_parser(self.chosen_url).groupdict()
        new_server_id = int(parsed['server_id']) + 1
        if new_server_id > 4:
            new_server_id = 1
        self.chosen_url = f"{parsed['url_prefix']}{new_server_id}{parsed['url_suffix']}"
        return True


class Video(Medium):
    type = VIDEO

    def __init__(self, url: Union[str, list[str]], poster: Optional[str] = None):
        super().__init__(url)
        self.poster: Optional[Union[str, Image]] = poster
        self.fallback_to_poster: bool = False

    async def validate(self):
        await super().validate()
        if not self.valid and self.poster is not None and isinstance(self.poster, str):
            self.poster = Image(self.poster)
            await self.poster.validate()
            if self.poster.valid:  # valid
                self.fallback_to_poster = True
                self.poster.type = VIDEO
                self.poster.original_urls = self.original_urls

    def telegramize(self):
        return InputMediaDocumentExternal(self.chosen_url)

    async def invalidate(self) -> bool:
        if self.valid:
            self.valid = False
            await self.validate()
            return True
        if self.fallback_to_poster:
            await self.poster.invalidate()
            self.fallback_to_poster = False
            return True
        return False


class Animation(Medium):
    type = ANIMATION

    def telegramize(self):
        return InputMediaDocumentExternal(self.chosen_url)


class Media:
    def __init__(self):
        self._media: list[Medium] = []

    def add(self, medium: Medium):
        if medium in self._media:
            return
        self._media.append(medium)

    async def invalidate_all(self) -> bool:
        if not self._media:
            return False
        invalidated = False
        for medium in self._media:
            if await medium.invalidate():
                invalidated = True
        if invalidated:
            self.video_fallback_to_poster()
        return invalidated

    async def validate(self):
        if not self._media:
            return
        await asyncio.gather(*(medium.validate() for medium in self._media))
        self.video_fallback_to_poster()

    def video_fallback_to_poster(self):
        if not self._media:
            return
        new_media_list = []
        for medium in self._media:
            if isinstance(medium, Video) and medium.fallback_to_poster:
                new_media_list.append(medium.poster)
                continue
            new_media_list.append(medium)
        self._media = new_media_list
        return

    def get_valid_media(self):
        result = []
        gifs = []
        for medium in self._media:
            if not medium:  # invalid
                continue
            if isinstance(medium, Animation):
                # if len(result) > 0:
                #     yield {'type': result[0].type, 'media': result[0]} if len(result) == 1 \
                #         else {'type': MEDIA_GROUP, 'media': result}
                #     result = []
                # yield {'type': ANIMATION, 'media': medium}
                gifs.append({'type': ANIMATION, 'media': medium})
                continue
            result.append(medium)
            if len(result) == 10:
                yield {'type': MEDIA_GROUP, 'media': result}
                result = []
        if result:
            yield {'type': result[0].type, 'media': result[0]} if len(result) == 1 \
                else {'type': MEDIA_GROUP, 'media': result}
        for gif in gifs:
            yield gif

    def get_invalid_link(self):
        return tuple(m.get_link() for m in self._media if not m or type(m).type != m.type)  # invalid and fallback

    async def change_all_server(self):
        return bool(self._media
                    and sum(await asyncio.gather(*(medium.change_server() for medium in self._media if medium))))

    def __len__(self):
        return len(self._media)

    def __bool__(self):
        return bool(self._media)


async def get_medium_info(url: str, medium_type: Optional[TypeMedium]) -> Optional[tuple[int, int, int, bool]]:
    is_image = medium_type is None or medium_type == IMAGE
    media_max_size = IMAGE_MAX_SIZE if is_image else MEDIA_MAX_SIZE
    valid = False

    try:
        r = await web.get(url=url, max_size=256 if is_image else 0)
        if r.status != 200:
            raise ValueError('status code not 200')
    except Exception as e:
        logger.debug(f'Dropped medium {url}: can not be fetched: ' + str(e), exc_info=e)
        return None

    size = int(r.headers.get('Content-Length') or -1)
    content_type = r.headers.get('Content-Type')

    width = height = -1
    if not is_image:
        valid = size <= media_max_size
        return size, width, height, valid

    file_header = r.content

    # noinspection PyBroadException
    try:
        image = PIL.Image.open(BytesIO(file_header))
        width, height = image.size
    except Exception:
        if content_type == 'image/jpeg' or url.find('jpg') != -1 or url.find('jpeg') != -1:  # if jpg
            pointer = -1
            for marker in (b'\xff\xc2', b'\xff\xc1', b'\xff\xc0'):
                p = file_header.find(marker)
                if p != -1:
                    pointer = p
                    break
            if pointer != -1 and pointer + 9 <= len(file_header):
                width = int(file_header[pointer + 7:pointer + 9].hex(), 16)
                height = int(file_header[pointer + 5:pointer + 7].hex(), 16)

    if not (0.05 < width / height < 20):  # always invalid
        valid = False

    if size <= media_max_size and width + height < 10000:  # valid
        valid = True

    return size, width, height, valid
