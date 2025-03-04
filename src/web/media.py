#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
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
from typing import Union, Optional
from typing_extensions import Final

import aiohttp
import json
import PIL.Image
import PIL.ImageFile
from PIL import UnidentifiedImageError
from io import BytesIO, SEEK_END
from asyncstdlib import lru_cache

from .. import env
from ..compat import INT64_T_MAX
from .req import get, _get
from .utils import logger

SOI: Final = b'\xff\xd8'
EOI: Final = b'\xff\xd9'
IMAGE_MAX_FETCH_SIZE: Final = 1024 * (1 if env.TRAFFIC_SAVING else 5)
IMAGE_ITER_CHUNK_SIZE: Final = 128
IMAGE_READ_BUFFER_SIZE: Final = 1

PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True

LRU_CACHE_MAXSIZE: Final = 1024


async def __medium_info_callback(response: aiohttp.ClientResponse) -> tuple[int, int]:
    content_type = response.headers.get('Content-Type', '').lower()
    content_length = int(response.headers.get('Content-Length', INT64_T_MAX))
    content = response.content
    preloaded_length = content.total_bytes  # part of response body already came with the response headers
    eof_flag = content.at_eof()
    fetch_full = False
    fetch_rest = False
    if 'svg' in content_type:  # svg
        return -1, -1
    if 'webp' in content_type or 'application' in content_type:  # webp or other binary files
        if content_length <= max(preloaded_length, IMAGE_MAX_FETCH_SIZE) or eof_flag:
            # the fetch limit will not result in a truncated image
            fetch_full = True
        else:
            # PIL cannot handle a truncated webp image
            return -1, -1
    is_jpeg = None
    already_read = 0
    exit_flag = False
    with BytesIO() as buffer:
        while not exit_flag:
            curr_chunk_length = 0
            preloaded_length = content.total_bytes - already_read
            while preloaded_length > IMAGE_READ_BUFFER_SIZE or curr_chunk_length < IMAGE_ITER_CHUNK_SIZE:
                if content.is_eof():
                    chunk = await content.readany()
                    eof_flag = True
                elif fetch_full:
                    chunk = await content.read()
                    eof_flag = True
                else:
                    read_length = max(
                        # get almost all preloaded bytes, but leaving some to avoid next automatic preloading
                        preloaded_length - IMAGE_READ_BUFFER_SIZE,
                        IMAGE_ITER_CHUNK_SIZE,
                        IMAGE_MAX_FETCH_SIZE - already_read if fetch_rest else 0
                    )
                    chunk = await content.read(read_length)
                    eof_flag = not chunk or content.at_eof()
                if is_jpeg is None:
                    is_jpeg = chunk.startswith(SOI)
                already_read += len(chunk)
                curr_chunk_length += len(chunk)
                buffer.seek(0, SEEK_END)
                buffer.write(chunk)
                if eof_flag:
                    break
                preloaded_length = content.total_bytes - already_read

            if eof_flag or already_read >= IMAGE_MAX_FETCH_SIZE:
                response.close()  # immediately close the connection to block any incoming data or retransmission
                exit_flag = True

            # noinspection PyBroadException
            try:
                image = PIL.Image.open(buffer)
                width, height = image.size
                return width, height
            except UnidentifiedImageError:
                return -1, -1  # not a format that PIL can handle
            except Exception:
                if is_jpeg:
                    file_header = buffer.getvalue()
                    find_start_pos = 0
                    for _ in range(3):
                        for marker in (b'\xff\xc2', b'\xff\xc1', b'\xff\xc0'):
                            p = file_header.find(marker, find_start_pos)
                            if p != -1:
                                pointer = p
                                break
                        else:
                            break

                        if pointer + 9 <= len(file_header):
                            if file_header.count(EOI, 0, pointer) != file_header.count(SOI, 0, pointer) - 1:
                                # we are currently entering the thumbnail in Exif, bypassing...
                                # (why the specifications makers made Exif so freaky?)
                                eoi_pos = file_header.find(EOI, pointer)
                                if eoi_pos == -1:
                                    fetch_rest = True  # a thumbnail is huge
                                    break  # no EOI found, we could never leave the thumbnail...
                                find_start_pos = eoi_pos + len(EOI)
                                continue
                            width = int(file_header[pointer + 7:pointer + 9].hex(), 16)
                            height = int(file_header[pointer + 5:pointer + 7].hex(), 16)
                            if min(width, height) <= 0:
                                find_start_pos = pointer + 1
                                continue
                            return width, height
                        break
    return -1, -1


@lru_cache(maxsize=1024)
async def get_medium_info(url: str) -> Optional[tuple[int, int, int, Optional[str]]]:
    if url.startswith('data:'):
        return None
    try:
        r = await _get(url, resp_callback=__medium_info_callback,
                       read_bufsize=IMAGE_READ_BUFFER_SIZE, read_until_eof=False)
        if r.status != 200:
            raise ValueError(f'status code is not 200, but {r.status}')
    except Exception as e:
        logger.debug(f'Medium fetch failed: {url}', exc_info=e)
        return None

    width, height = -1, -1
    size = int(r.headers.get('Content-Length') or -1)
    content_type = r.headers.get('Content-Type')
    if isinstance(r.content, tuple):
        width, height = r.content

    return size, width, height, content_type


def weserv_param_encode(param: str) -> str:
    hash_index = param.find('#')
    if hash_index != -1:
        param = param[:hash_index]  # remove fragment
    # & will mess up the query string
    # leaving % as is will let weserv decode the encoded character before requesting the source image
    return param.replace('%', '%25').replace('&', '%26')


def construct_weserv_url(url: str,
                         width: Optional[int] = None,
                         height: Optional[int] = None,
                         fit: Optional[str] = None,
                         output_format: Optional[str] = None,
                         quality: Optional[int] = None,
                         without_enlargement: Optional[bool] = None,
                         default_image: Optional[str] = None) -> str:
    return (
            f'{env.IMAGES_WESERV_NL}?'
            f'url={weserv_param_encode(url)}'
            + (f'&w={width}' if width else '')
            + (f'&h={height}' if height else '')
            + (f'&fit={fit}' if fit else '')
            + (f'&output={output_format}' if output_format else '')
            + (f'&q={quality}' if quality else '')
            + (f'&we=1' if without_enlargement else '')
            + (f'&default={weserv_param_encode(default_image)}' if default_image else '')
    )


def construct_weserv_url_convert_to_2560(url: str) -> str:
    return construct_weserv_url(
        url,
        width=2560,
        height=2560,
        # fit='inside',  # is default
        output_format='jpg',
        # In the worst case, 89% ensures the size won't exceed 5MB
        # E.g.:
        # 2560x2560 white noise truecolor --89% JPEG--> 4.98MiB
        # 2560x2560 white noise truecolor --90% JPEG--> 10.26MiB
        # See also:
        # https://robson.plus/white-noise-image-generator/
        # https://fotoforensics.com/tutorial-estq.php
        quality=89,
        without_enlargement=True
    )


def construct_weserv_url_convert_to_jpg(url: str) -> str:
    return construct_weserv_url(url, output_format='jpg')


HEAD_IMAGES_WESERV_NL_URL: Final = construct_weserv_url('')
HEAD_IMAGES_WESERV_NL_URL_RELAYED: Final = construct_weserv_url(env.IMG_RELAY_SERVER)
LEN_HEAD_IMAGES_WESERV_NL_URL: Final = len(HEAD_IMAGES_WESERV_NL_URL)


def insert_image_relay_into_weserv_url(url: str) -> Optional[str]:
    """
    Ensure weserv fetches the image via the relay server.
    Useful when:
    1. The image is from a domain/TLD banned by weserv; or
    2. The image is from a CDN that bans weserv.
    """
    if not url.startswith(HEAD_IMAGES_WESERV_NL_URL):
        return None  # not a weserv url
    if url.startswith(HEAD_IMAGES_WESERV_NL_URL_RELAYED):
        return None  # already relayed
    return HEAD_IMAGES_WESERV_NL_URL_RELAYED + url[LEN_HEAD_IMAGES_WESERV_NL_URL:]


async def _get_medium_info_via_weserv(url: str) -> Optional[tuple[int, int, int, Optional[str]]]:
    try:
        r = await get(url)
        if r.status != 200:
            raise ValueError(f'status code is not 200, but {r.status}')
        data: dict[str, Union[str, int, bool]] = json.loads(r.content)
    except Exception as e:
        logger.debug(f'Medium info via weserv fetch failed: {url}', exc_info=e)
        return None

    width, height = data.get('width', -1), data.get('height', -1)
    size = int(r.headers.get('X-Upstream-Response-Length') or -1)
    content_type = data.get('format')
    content_type = content_type and f'image/{content_type}'

    return size, width, height, content_type


@lru_cache(maxsize=LRU_CACHE_MAXSIZE)
async def get_medium_info_via_weserv(url: str) -> Optional[tuple[int, int, int, Optional[str]]]:
    url = construct_weserv_url(url, output_format='json')
    res = await _get_medium_info_via_weserv(url)
    if res:
        return res
    url = insert_image_relay_into_weserv_url(url)
    if url:
        return await _get_medium_info_via_weserv(url)


async def detect_image_dimension_via_weserv(url: str) -> tuple[int, int]:
    res = await get_medium_info_via_weserv(url)
    if not res:
        return -1, -1
    _, width, height, _ = res
    return width, height


IMG_RELAY_SERVER_UPLOAD_TO_TELEGRAPH_PATH = 'upload_graph/'


@lru_cache(maxsize=LRU_CACHE_MAXSIZE)
async def upload_to_telegraph(url: str) -> Optional[str]:
    try:
        resp = await get(
            env.IMG_RELAY_SERVER + IMG_RELAY_SERVER_UPLOAD_TO_TELEGRAPH_PATH + url,
            allow_redirects=False,
            max_size=0
        )
        if location := resp.headers.get('Location'):
            return location
        if err := resp.headers.get('X-Telegraph-Error'):
            logger.debug(f'Upload to telegraph failed (Telegraph error): {err}')
        else:
            logger.debug(f'Upload to telegraph failed (status code): {resp.status} {resp.reason}')
    except Exception as e:
        logger.debug('Upload to telegraph failed', exc_info=e)
