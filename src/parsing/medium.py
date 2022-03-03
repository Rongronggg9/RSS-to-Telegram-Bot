from __future__ import annotations
from src.compat import Final
from typing import Optional, Union

import asyncio
import re
import PIL.Image
import PIL.ImageFile
from io import BytesIO
from collections import defaultdict
from telethon.tl.functions.messages import UploadMediaRequest
from telethon.tl.types import InputMediaPhotoExternal, InputMediaDocumentExternal, \
    MessageMediaPhoto, MessageMediaDocument
from telethon.errors import FloodWaitError, SlowModeWaitError, ServerError
from asyncstdlib.functools import lru_cache

from src import env, log, web, locks
from src.parsing.html_node import Link, Br, Text, HtmlTree
from src.exceptions import InvalidMediaErrors, ExternalMediaFetchFailedErrors, UserBlockedErrors

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
AUDIO: Final = 'audio'
FILE: Final = 'file'
MEDIUM_BASE_CLASS: Final = 'medium'
TypeMedium = Union[IMAGE, VIDEO, ANIMATION, FILE]

MEDIA_GROUP: Final = 'media_group'
TypeMessage = Union[MEDIA_GROUP, TypeMedium]

TypeMessageMedia = Union[MessageMediaPhoto, MessageMediaDocument]

IMAGE_MAX_SIZE: Final = 5242880
MEDIA_MAX_SIZE: Final = 20971520


# Note:
# One message can have 10 media at most, but there are some exceptions.
# 1. A GIF (Animation) and webp (although as a file) must occupy a SINGLE message.
# 2. Videos and Images can be mixed in a media group, but any other type of media cannot be in the same message.
# 3. Images uploaded as MessageMediaPhoto will be considered as an image. While MessageMediaDocument not, it's a file.
# 4. Any other type of media except Image must be uploaded as MessageMediaDocument.
# 5. Telegram will not take notice of attributes provided if it already decoded the necessary metadata of a media.
# 6. Because of (5), we can't force send GIFs and videos as ordinary files.
# 7. Audios can be sent in a media group, but can not be mixed with other types of media.
# 8. Other files (including images sent as files) should be able to be mixed in a media group.
#
# Type fallback notes:
# 1. A video can fall back to an image if its poster is available.
# 2. An image can fall back to a file if it is: 5MB < size <= 20MB, width + height >= 10000.
# 3. A GIF need not any fallback, because of (5) above.
# 4. The only possible fallback chain is: video -> image(poster) -> file.
# 5. If an image fall back to a file, rest images must fall back to file too!

class Medium:
    type = MEDIUM_BASE_CLASS
    maxSize = MEDIA_MAX_SIZE
    # noinspection PyTypeChecker
    typeFallbackTo: Optional[type[Medium]] = None
    typeFallbackAllowSelfUrls: bool = False
    # noinspection PyTypeChecker
    inputMediaExternalType: Optional[Union[type[InputMediaPhotoExternal], type[InputMediaDocumentExternal]]] = None

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
        self.type_fallback_urls: list[str] = type_fallback_urls if isinstance(type_fallback_urls, list) \
            else [type_fallback_urls] if type_fallback_urls and isinstance(type_fallback_urls, str) \
            else []  # use for fallback if not type_fallback_allow_self_urls
        self.type_fallback_medium: Optional[Medium] = None
        self.need_type_fallback: bool = False
        self.content_type: Optional[str] = None
        self.drop_silently: bool = False  # if True, will not be included in invalid media
        self.uploaded_bucket: defaultdict[int, Optional[tuple[TypeMessageMedia, TypeMedium]]] \
            = defaultdict(lambda: None)
        self.uploading_lock = asyncio.Lock()
        self.validating_lock = asyncio.Lock()

    def telegramize(self):
        if self.inputMediaExternalType is None:
            raise NotImplementedError
        return self.inputMediaExternalType(self.chosen_url)

    def type_fallback_chain(self) -> Optional[Medium]:
        return (
            self
            if self.valid
            else
            (self.type_fallback_medium.type_fallback_chain()
             if self.need_type_fallback and self.type_fallback_medium is not None
             else None)
        )

    async def upload(self, chat_id: int, force_upload: bool = False) \
            -> tuple[Optional[TypeMessageMedia], Optional[TypeMedium]]:
        """
        :return: tuple(MessageMedia, self)
        """
        if self.valid is None:
            await self.validate()
        medium_to_upload = self.type_fallback_chain()
        if medium_to_upload is None:
            return None, None
        if self.uploaded_bucket[chat_id]:
            cached = self.uploaded_bucket[chat_id]
            if not force_upload and cached[1] == medium_to_upload.type:
                return cached

        tries = 0
        error_tries = 0
        max_tries = 10
        server_change_count = 0
        media_fallback_count = 0
        err_list = []
        flood_lock = locks.user_flood_lock(chat_id)
        while True:
            peer = await env.bot.get_input_entity(chat_id)
            try:
                async with flood_lock:
                    pass  # wait for flood wait

                async with self.uploading_lock:
                    medium_to_upload = self.type_fallback_chain()
                    if medium_to_upload is None:
                        return None, None
                    if self.uploaded_bucket[chat_id]:
                        cached = self.uploaded_bucket[chat_id]
                        if not force_upload and cached[1] == medium_to_upload.type:
                            return cached
                    while True:
                        medium_to_upload = self.type_fallback_chain()
                        if medium_to_upload is None:
                            return None, None
                        tries += 1
                        if tries > max_tries:
                            self.valid = False
                            return None, None
                        try:
                            async with flood_lock:
                                pass  # wait for flood wait

                            uploaded_media = await env.bot(
                                UploadMediaRequest(peer, medium_to_upload.telegramize())
                            )
                            self.uploaded_bucket[chat_id] = uploaded_media, medium_to_upload.type
                            return uploaded_media, medium_to_upload.type

                        # errors caused by invalid img/video(s)
                        except InvalidMediaErrors as e:
                            err_list.append(e)
                            if await self.fallback():
                                media_fallback_count += 1
                            else:
                                self.valid = False
                                return None, None
                            continue

                        # errors caused by server or network instability between img server and telegram server
                        except ExternalMediaFetchFailedErrors as e:
                            err_list.append(e)
                            if await self.change_server():
                                server_change_count += 1
                            elif await self.fallback():
                                media_fallback_count += 1
                            else:
                                self.valid = False
                                return None, None
                            continue

            except (FloodWaitError, SlowModeWaitError) as e:
                # telethon has retried for us, but we release locks and retry again here to see if it will be better
                if error_tries >= 1:
                    logger.error(f'Medium dropped due to too many flood control retries ({chat_id}): '
                                 f'{self.original_urls[0]}')
                    return None, None

                error_tries += 1
                await locks.user_flood_wait(chat_id, seconds=e.seconds)  # acquire a flood wait
            except ServerError as e:
                # telethon has retried for us, so we just retry once more
                if error_tries >= 1:
                    logger.error(f'Medium dropped due to Telegram internal server error '
                                 f'({chat_id}, {type(e).__name__}): '
                                 f'{self.original_urls[0]}')

                error_tries += 1

    def get_link_html_node(self):
        return Link(self.type, param=self.original_urls[0])

    async def validate(self, flush: bool = False) -> bool:
        if self.valid is not None and not flush:  # already validated
            return self.valid

        if self.drop_silently:
            return False

        async with self.validating_lock:
            while self.urls:
                url = self.urls.pop(0)
                medium_info = await get_medium_info(url)
                if medium_info is None:
                    continue
                self.size, self.width, self.height, self.content_type = medium_info

                if self.type == IMAGE:
                    # drop SVG
                    if self.content_type and self.content_type.lower().startswith('image/svg'):
                        self.valid = False
                        self.drop_silently = True
                        return False
                    # always invalid
                    elif self.width + self.height > 10000 or self.size > self.maxSize:
                        self.valid = False
                    # Telegram accepts 0.05 < w/h < 20. But after downsized, it will be ugly. Narrow the range down
                    elif 0.4 <= self.width / self.height <= 2.5:
                        self.valid = True
                    elif (
                            # if already fall backed, bypass rest checks
                            url in self.original_urls and self.original_urls.index(url) == 0
                            and
                            # ensure the image is valid
                            0.05 < self.width / self.height < 20
                            and
                            # Telegram downsizes images to fit 1280x1280. If not downsized a lot, passing
                            max(self.width, self.height) <= 1280 * 1.5
                    ):
                        self.valid = True
                    # let long images fall back to file
                    else:
                        self.valid = False
                        self.urls = []  # clear the urls, force fall back to file
                elif self.size <= self.maxSize:  # valid
                    self.valid = True

                if self.valid:
                    self.chosen_url = url
                    self._server_change_count = 0
                    if isTelegramCannotFetch(self.chosen_url):
                        await self.change_server()
                    return True

                # TODO: reduce non-weibo pic size

            self.valid = False
            return await self.type_fallback()

    async def type_fallback(self) -> bool:
        fallback_urls = self.type_fallback_urls + (list(self.original_urls) if self.typeFallbackAllowSelfUrls else [])
        self.valid = False
        if self.type_fallback_medium is None and fallback_urls and self.typeFallbackTo:
            # create type fallback medium
            self.type_fallback_medium = self.typeFallbackTo(fallback_urls)
            if await self.type_fallback_medium.validate():
                logger.debug(f"Medium {self.original_urls[0]}"
                             + (f' ({self.info})' if self.info else '')
                             + f" type fallback to '{self.type_fallback_medium.type}'"
                             + (f'({self.type_fallback_medium.original_urls[0]})'
                                if not self.typeFallbackAllowSelfUrls
                                else ''))
                self.need_type_fallback = True
                # self.type_fallback_medium.type = self.type
                # self.type_fallback_medium.original_urls = self.original_urls
                return True
        elif self.need_type_fallback and self.type_fallback_medium is not None:
            return await self.type_fallback_medium.fallback()
        logger.debug(f'Dropped medium {self.original_urls[0]}'
                     + (f' ({self.info})' if self.info else '')
                     + ': invalid or fetch failed')
        return False

    async def fallback(self) -> bool:
        if self.need_type_fallback:
            if not await self.type_fallback_medium.fallback():
                self.need_type_fallback = False
                self.valid = False
            return True
        else:
            urls_len = len(self.urls)
            formerly_valid = self.valid
            if formerly_valid:
                await self.validate(flush=True)
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
        if self.drop_silently:
            return ''
        return '|'.join(
            str(s) for s in (self.valid,
                             self.chosen_url,
                             self.need_type_fallback,
                             self.type_fallback_medium.hash if self.need_type_fallback else None)
        )

    @property
    def info(self):
        return (
                (f'{self.size / 1024 / 1024:.2f}MB'
                 if self.size not in {-1, None}
                 else '')
                + (', '
                   if (self.size not in {-1, None} and (self.width not in {-1, None} or self.height not in {-1, None}))
                   else '')
                + (f'{self.width}x{self.height}'
                   if self.width not in {-1, None} and self.height not in {-1, None}
                   else '')
        )


class File(Medium):
    type = FILE
    maxSize = MEDIA_MAX_SIZE
    typeFallbackTo = None
    typeFallbackAllowSelfUrls = False
    inputMediaExternalType = InputMediaDocumentExternal


class Image(Medium):
    type = IMAGE
    maxSize = IMAGE_MAX_SIZE
    typeFallbackTo = File
    typeFallbackAllowSelfUrls = True
    inputMediaExternalType = InputMediaPhotoExternal

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
    maxSize = MEDIA_MAX_SIZE
    typeFallbackTo = Image
    typeFallbackAllowSelfUrls = False
    inputMediaExternalType = InputMediaDocumentExternal


class Audio(Medium):
    type = AUDIO
    maxSize = MEDIA_MAX_SIZE
    typeFallbackTo = None
    typeFallbackAllowSelfUrls = False
    inputMediaExternalType = InputMediaDocumentExternal


class Animation(Image):
    type = ANIMATION
    maxSize = MEDIA_MAX_SIZE
    # typeFallbackTo = Image
    # typeFallbackAllowSelfUrls = True
    typeFallbackTo = None
    typeFallbackAllowSelfUrls = False
    inputMediaExternalType = InputMediaDocumentExternal


class Media:
    def __init__(self):
        self._media: list[Medium] = []
        self.modify_lock = asyncio.Lock()

    def add(self, medium: Medium):
        if medium in self._media:
            return
        self._media.append(medium)

    def url_exists(self, url: str) -> bool:
        return any(url in medium.original_urls for medium in self._media)

    async def fallback_all(self) -> bool:
        if not self._media:
            return False
        fallback_flag = False
        for medium in self._media:
            if not medium.drop_silently and await medium.fallback():
                fallback_flag = True
        return fallback_flag

    def invalidate_all(self) -> bool:
        invalidated_some_flag = False
        for medium in self._media:
            if not medium.drop_silently and medium.valid or medium.need_type_fallback:
                medium.valid = False
                medium.need_type_fallback = False
                invalidated_some_flag = True
        return invalidated_some_flag

    async def validate(self, flush: bool = False):
        if not self._media:
            return
        await asyncio.gather(*(medium.validate(flush=flush) for medium in self._media if not medium.drop_silently))

    async def upload_all(self, chat_id: Optional[int]) \
            -> tuple[
                list[
                    tuple[
                        Union[
                            tuple[
                                Union[
                                    TypeMessageMedia,  # uploaded media
                                    Medium  # origin media (if chat_id is None)
                                ], ...
                            ],  # uploaded media list of the media group
                            Union[
                                TypeMessageMedia,  # uploaded media
                                Medium  # origin media (if chat_id is None)
                            ]
                        ],
                        TypeMessage,  # message type
                    ]
                ],
                Optional[HtmlTree]
            ]:
        """
        Upload all media to telegram.
        :param chat_id: chat_id to upload to. If None, the origin media will be returned.
        :return: ((uploaded/original medium, medium type)), invalid media html node)
        """
        await self.validate()
        async with self.modify_lock:
            # at least a file and an image
            if (
                    sum(isinstance(medium.type_fallback_chain(), File)
                        for medium in self._media
                        if not medium.drop_silently) > 0
                    and
                    sum(isinstance(medium.type_fallback_chain(), Image)
                        for medium in self._media
                        if not medium.drop_silently) > 0
            ):
                # fall back all image to files
                await asyncio.gather(
                    *(medium.type_fallback()
                      for medium in self._media
                      if isinstance(medium.type_fallback_chain(), Image) and not medium.drop_silently)
                )

        media_and_types: tuple[
            Union[tuple[Union[TypeMessageMedia, Medium, None], Optional[TypeMedium]], BaseException],
            ...]
        if chat_id:
            # tuple[Union[tuple[Optional[TypeMessageMedia], Optional[TypeMedium]], BaseException], ...]
            media_and_types = await asyncio.gather(
                *(medium.upload(chat_id) for medium in self._media if not medium.drop_silently),
                return_exceptions=True
            )
        else:
            # tuple[tuple[Optional[Medium], Optional[TypeMedium]], ...]
            media_and_types = tuple((medium.type_fallback_chain(), medium.type_fallback_chain().type)
                                    if medium.type_fallback_chain() is not None
                                    else (None, None)
                                    for medium in self._media if not medium.drop_silently)

        media: list[tuple[Union[TypeMessageMedia, Image, Video], Union[IMAGE, VIDEO]]] = []
        gifs: list[tuple[Union[MessageMediaDocument, Animation], ANIMATION]] = []
        audios: list[tuple[Union[MessageMediaDocument, Audio], AUDIO]] = []
        files: list[tuple[Union[MessageMediaDocument, File], FILE]] = []

        link_nodes: list[Link] = []
        for medium, medium_and_type in zip(self._media, media_and_types):
            if isinstance(medium_and_type, Exception):
                if type(medium_and_type) in UserBlockedErrors:  # user blocked, let it go
                    raise medium_and_type
                logger.debug('Upload media failed:', exc_info=medium_and_type)
                link_nodes.append(medium.get_link_html_node())
                continue
            file, file_type = medium_and_type
            if file_type in {IMAGE, VIDEO}:
                media.append(medium_and_type)
            elif file_type == ANIMATION:
                gifs.append(medium_and_type)
            elif file_type == AUDIO:
                audios.append(medium_and_type)
            elif file_type == FILE:
                files.append(medium_and_type)
            else:
                link_nodes.append(medium.get_link_html_node())
            if file_type in {IMAGE, FILE} and isinstance(medium, Video) and file_type != medium.type:
                link_nodes.append(medium.get_link_html_node())

        ret = []
        for list_to_process in (media, audios, files):
            while list_to_process:
                _ = list_to_process[:10]
                list_to_process = list_to_process[10:]
                if len(_) == 1:
                    ret.append(_[0])
                else:
                    # media group
                    media_group = tuple(medium_and_type[0] for medium_and_type in _)
                    ret.append((media_group, MEDIA_GROUP))
        ret.extend(gifs)

        html_nodes = []
        invalid_html_node: Optional[HtmlTree] = None
        for link in link_nodes:
            html_nodes.append(link)
            html_nodes.append(Br())
        if html_nodes:
            html_nodes.pop()
            html_nodes.insert(0, Text('Invalid media:\n'))
            invalid_html_node = HtmlTree(html_nodes)

        return ret, invalid_html_node

    async def estimate_message_counts(self):
        media = await self.upload_all(chat_id=None)
        return sum(1 for _ in media[0])

    def __len__(self):
        return len(self._media)

    def __bool__(self):
        return bool(self._media)

    @property
    def valid_count(self):
        return sum(1 for medium in self._media if medium.valid and not medium.drop_silently)

    @property
    def invalid_count(self):
        return sum(1 for medium in self._media if medium.valid is False and not medium.drop_silently)

    @property
    def pending_count(self):
        return sum(1 for medium in self._media if medium.valid is None and not medium.drop_silently)

    @property
    def need_type_fallback_count(self):
        return sum(1 for medium in self._media if medium.need_type_fallback and medium.type_fallback_medium is not None
                   and not medium.drop_silently)

    def stat(self):
        class MediaStat:
            valid = self.valid_count
            invalid = self.invalid_count
            pending = self.pending_count
            need_type_fallback = self.need_type_fallback_count

            def __eq__(self, other):
                return isinstance(self, other) and self.valid == other.valid and self.invalid == other.invalid \
                       and self.pending == other.pending and self.need_type_fallback == other.need_type_fallback

        return MediaStat()

    @property
    def hash(self):
        return '|'.join(medium.hash for medium in self._media)


@lru_cache(maxsize=1024)
async def get_medium_info(url: str) -> Optional[tuple[int, int, int, Optional[str]]]:
    if url.startswith('data:'):
        return None
    try:
        r = await web.get(url=url, max_size=256, intended_content_type='image')
        if r.status != 200:
            raise ValueError('status code not 200')
    except Exception as e:
        logger.debug(f'Dropped medium {url}: can not be fetched: ', exc_info=e)
        return None

    size = int(r.headers.get('Content-Length') or -1)
    content_type = r.headers.get('Content-Type')
    is_image = content_type and content_type.startswith('image/')

    width = height = -1
    file_header = r.content
    if not is_image or not file_header:
        return size, width, height, content_type

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

    return size, width, height, content_type
