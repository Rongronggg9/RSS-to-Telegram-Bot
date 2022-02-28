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

sinaimg_sizes = ['large', 'mw2048', 'mw1024', 'mw720', 'middle']
sinaimg_size_parser = re.compile(r'(?P<domain>^https?://wx\d\.sinaimg\.\w+/)'
                                 r'(?P<size>\w+)'
                                 r'(?P<filename>/\w+\.\w+$)').match
pixiv_sizes = ['original', 'master']
pixiv_size_parser = re.compile(r'(?P<url_prefix>^https?://i\.pixiv\.(cat|re)/img-)'
                               r'(?P<size>\w+)'
                               r'(?P<url_infix>/img/\d{4}/(\d{2}/){5})'
                               r'(?P<filename>\d+_p\d+)'
                               r'(?P<file_ext>\.\w+$)').match
sinaimg_server_parser = re.compile(r'(?P<url_prefix>^https?://wx)'
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
    # noinspection PyTypeChecker
    type_fallback_to: Optional[type[Medium]] = None
    type_fallback_allow_self_urls: bool = False

    def __init__(self, urls: Union[str, list[str]], type_fallback_urls: Optional[Union[str, list[str]]] = None):
        urls = urls if isinstance(urls, list) else [urls]
        self.urls: list[str] = []
        for url in urls:  # dedup, should not use a set because sequence is important
            if url not in self.urls:
                self.urls.append(url)
        self.original_urls: tuple[str, ...] = tuple(self.urls)
        self.chosen_url: Optional[str] = self.urls[0]
        self.valid: Optional[bool] = None
        self._server_change_count: int = 0
        self.size = self.width = self.height = None
        self.valid_urls: list[str] = []  # use for fallback if type_fallback_allow_self_urls
        self.type_fallback_urls: list[str] = type_fallback_urls if isinstance(type_fallback_urls, list) \
            else [type_fallback_urls] if type_fallback_urls and isinstance(type_fallback_urls, str) \
            else []  # use for fallback if not type_fallback_allow_self_urls
        self.type_fallback_medium: Optional[Medium] = None
        self.need_type_fallback: bool = False

    def telegramize(self):
        raise NotImplementedError

    def get_link(self):
        return Link(self.type, param=self.original_urls[0])

    def get_url(self):
        return self.chosen_url

    async def validate(self, force: bool = False):
        if self.valid is not None and not force:  # already validated
            return

        while self.urls:
            url = self.urls.pop(0)
            medium_info = await get_medium_info(url, medium_type=self.type)
            if medium_info is None:
                continue
            self.size, self.width, self.height, self.valid = medium_info

            if self.valid:
                self.valid_urls.append(url)
                self.chosen_url = url
                self._server_change_count = 0
                if isTelegramCannotFetch(self.chosen_url):
                    await self.change_server()
                return

            # TODO: reduce non-weibo pic size

        logger.debug(f'Dropped medium {self.original_urls[0]}: invalid or fetch failed')
        self.valid = False

        fallback_urls = self.type_fallback_urls + (self.valid_urls if self.type_fallback_allow_self_urls else [])
        if not self.valid and self.type_fallback_medium is None and fallback_urls and self.type_fallback_to:
            self.type_fallback_medium = self.type_fallback_to(fallback_urls)
            await self.type_fallback_medium.validate()
            if self.type_fallback_medium.valid:
                self.need_type_fallback = True
                self.type_fallback_medium.type = self.type
                self.type_fallback_medium.original_urls = self.original_urls

    async def fallback(self) -> bool:
        if self.need_type_fallback:
            if not await self.type_fallback_medium.fallback():
                self.need_type_fallback = False
                self.valid = False
                return True
        urls_len = len(self.urls)
        formerly_valid = self.valid
        if formerly_valid:
            await self.validate(force=True)
        fallback_flag = (self.valid != formerly_valid
                         or (self.valid and urls_len != len(self.urls))
                         or self.need_type_fallback)
        return fallback_flag

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

    def __bool__(self):
        if self.valid is None:
            raise RuntimeError('You must validate a medium before judging its validation')
        return self.valid

    def __eq__(self, other):
        return type(self) == type(other) and self.original_urls == other.original_urls

    @property
    def hash(self):
        return '|'.join(
            str(s) for s in (self.valid,
                             self.chosen_url,
                             self.need_type_fallback,
                             self.type_fallback_medium.hash if self.need_type_fallback else None)
        )


class Image(Medium):
    type = IMAGE
    max_size = IMAGE_MAX_SIZE
    type_fallback_to = None

    def __init__(self, url: Union[str, list[str]]):
        super().__init__(url)
        new_urls = []
        for url in self.urls:
            sinaimg_match = sinaimg_size_parser(url)
            pixiv_match = pixiv_size_parser(url)
            if not any([sinaimg_match, pixiv_match]):
                new_urls.append(url)
                continue
            if sinaimg_match:
                parsed_sinaimg = sinaimg_match.groupdict()  # is a sinaimg img
                for size_name in sinaimg_sizes:
                    new_url = parsed_sinaimg['domain'] + size_name + parsed_sinaimg['filename']
                    if new_url not in new_urls:
                        new_urls.append(new_url)
            elif pixiv_match:
                parsed_pixiv = pixiv_match.groupdict()  # is a pixiv img
                for size_name in pixiv_sizes:
                    new_url = parsed_pixiv['url_prefix'] + size_name + parsed_pixiv['url_infix'] \
                              + parsed_pixiv['filename'] \
                              + ('_master1200.jpg' if size_name == 'master' else parsed_pixiv['file_ext'])
                    if new_url not in new_urls:
                        new_urls.append(new_url)
            if url not in new_urls:
                new_urls.append(url)
        self.urls = new_urls

    def telegramize(self):
        return InputMediaPhotoExternal(self.chosen_url)

    async def change_server(self):
        sinaimg_server_match = sinaimg_server_parser(self.chosen_url)
        if not sinaimg_server_match:  # is not a sinaimg img
            return await super().change_server()

        self._server_change_count += 1
        if self._server_change_count >= 1:
            return False
        parsed = sinaimg_server_match.groupdict()
        new_server_id = int(parsed['server_id']) + 1
        if new_server_id > 4:
            new_server_id = 1
        self.chosen_url = f"{parsed['url_prefix']}{new_server_id}{parsed['url_suffix']}"
        return True


class Video(Medium):
    type = VIDEO
    type_fallback_to = Image

    def telegramize(self):
        return InputMediaDocumentExternal(self.chosen_url)


class Animation(Image):
    type = ANIMATION
    type_fallback_to = Image
    type_fallback_allow_self_urls = True

    def telegramize(self):
        return InputMediaDocumentExternal(self.chosen_url)


class Media:
    def __init__(self):
        self._media: list[Medium] = []
        self.modify_lock = asyncio.Lock()

    def add(self, medium: Medium):
        if medium in self._media:
            return
        self._media.append(medium)

    async def fallback_all(self) -> bool:
        if not self._media:
            return False
        fallback_flag = False
        for medium in self._media:
            if await medium.fallback():
                fallback_flag = True
        if fallback_flag:
            self.type_fallback()
        return fallback_flag

    def invalidate_all(self) -> bool:
        invalidated_some_flag = False
        for medium in self._media:
            if medium.valid:
                medium.valid = False
                invalidated_some_flag = True
        return invalidated_some_flag

    async def validate(self):
        if not self._media:
            return
        await asyncio.gather(*(medium.validate() for medium in self._media))
        self.type_fallback()

    def type_fallback(self):
        if not self._media:
            return
        new_media_list = []
        for medium in self._media:
            if medium.type_fallback_to and medium.need_type_fallback and medium.type_fallback_medium:
                new_media_list.append(medium.type_fallback_medium)
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

    @property
    def hash(self):
        return '|'.join(medium.hash for medium in self._media)


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

    if size <= media_max_size and width + height <= 10000:  # valid
        valid = True

    return size, width, height, valid
