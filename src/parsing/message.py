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
from collections.abc import Sequence

import asyncio
from telethon.tl import types, functions
from telethon.errors.rpcbaseerrors import TimedOutError
from telethon.errors.rpcerrorlist import SlowModeWaitError, FloodWaitError, ServerError
from telethon.utils import get_message_id
from collections import defaultdict

from .. import log, env, locks
from ..errors_collection import MediaSendFailErrors
from .medium import Media, TypeMessage, TypeMessageMedia, VIDEO, ANIMATION, MEDIA_GROUP
from .splitter import html_to_telegram_split

logger = log.getLogger('RSStT.message')


class MessageDispatcher:
    user_sending_lock = defaultdict(asyncio.Lock)

    def __init__(self,
                 user_id: int,
                 html: Optional[str] = None,
                 media: Optional[Media] = None,
                 link_preview: bool = False,
                 silent: bool = False):
        if not any((html, media)):
            raise ValueError('At least one of html or media must be specified')
        self.user_id = user_id
        self.html = html
        self.original_html = html
        self.media = media
        self.link_preview = link_preview
        self.silent = silent

        self.messages: list[Message] = []

    async def generate_messages(self):
        media_msg_count: int = 0
        invalid_media_html: Optional[str] = None
        media_and_types = None
        if self.media:
            media_and_types, invalid_media_html_node = await self.media.upload_all(self.user_id)
            invalid_media_html = invalid_media_html_node.get_html() if invalid_media_html_node else None
            media_msg_count = len(media_and_types)

        if invalid_media_html:
            invalid_media_html = (' '.join(invalid_media_html.split('\n'))
                                  if len(invalid_media_html.split('\n')) == 2
                                  else invalid_media_html)  # if only one invalid media, trim the newline
            self.html += '\n\n' + invalid_media_html

        if self.html:
            tel = html_to_telegram_split(html=self.html,
                                         length_limit_head=1024 if media_msg_count else 4096,
                                         head_count=media_msg_count or -1,
                                         length_limit_tail=4096)
        else:
            tel = []

        while tel:
            plain_text, format_entities = tel.pop(0)
            if media_and_types:
                media, media_type = media_and_types.pop(0)
            else:
                media = media_type = None
            message = Message(self.user_id, plain_text, format_entities, media, media_type, self.link_preview,
                              self.silent)
            self.messages.append(message)

        while media_and_types:
            media, media_type = media_and_types.pop(0)
            message = Message(self.user_id, None, None, media, media_type, self.link_preview, self.silent)
            self.messages.append(message)

    async def send_messages(self):
        if not self.messages:
            await self.generate_messages()
        sent_msgs: list[types.Message] = []
        try:
            async with self.user_sending_lock[self.user_id]:
                for message in self.messages:
                    msg = await message.send(reply_to=sent_msgs[-1] if sent_msgs else None)
                    if msg:
                        sent_msgs.extend(msg) if isinstance(msg, list) else sent_msgs.append(msg)
        except MediaSendFailErrors as e:
            if sent_msgs:
                await asyncio.gather(
                    *(env.bot.delete_messages(self.user_id, msg, revoke=True) for msg in sent_msgs),
                    return_exceptions=True
                )
            raise e


class Message:
    no_retry = False
    max_tries = 2 * 2  # telethon internally tries twice
    __overall_concurrency = 30
    __overall_semaphore = asyncio.BoundedSemaphore(__overall_concurrency)

    def __init__(self,
                 user_id: int,
                 plain_text: Optional[str] = None,
                 format_entities: Optional[list[types.TypeMessageEntity]] = None,
                 media: Optional[Union[Sequence[TypeMessageMedia], TypeMessageMedia]] = None,
                 media_type: Optional[TypeMessage] = None,
                 link_preview: bool = False,
                 silent: bool = False):
        self.user_id = user_id
        self.plain_text = plain_text
        self.format_entities = format_entities
        self.media = media
        self.media_type = media_type
        self.link_preview = link_preview
        self.silent = silent
        self.tries = 0

        self.attributes = (
            (types.DocumentAttributeVideo(0, 0, 0),)
            if media_type == VIDEO
            else (
                (types.DocumentAttributeAnimated(),)
                if media_type == ANIMATION
                else None
            )
        )

    # noinspection PyProtectedMember
    async def send(self, reply_to: Union[int, types.Message, None] = None) \
            -> Optional[Union[types.Message, list[types.Message]]]:
        msg_lock, flood_lock = locks.user_msg_locks(self.user_id)
        while True:
            try:
                async with flood_lock:
                    pass  # wait for flood wait

                async with msg_lock:  # acquire a msg lock
                    # only acquire overall semaphore when sending
                    async with self.__overall_semaphore:
                        if self.media_type == MEDIA_GROUP:
                            # Extracted from telethon.client.uploads.UploadMethods._send_album()
                            media = []
                            for medium in self.media:
                                _, fm, _ = await env.bot._file_to_media(medium)
                                media.append(types.InputSingleMedia(fm, message=''))
                            media[-1].message = self.plain_text or ''
                            media[-1].entities = self.format_entities or None
                            entity = await env.bot.get_input_entity(self.user_id)
                            reply_to = get_message_id(reply_to)
                            request = functions.messages.SendMultiMediaRequest(
                                entity,
                                reply_to=None if reply_to is None else types.InputReplyToMessage(reply_to),
                                multi_media=media,
                                silent=self.silent
                            )
                            result = await env.bot(request)
                            random_ids = [m.random_id for m in media]
                            return env.bot._get_response_message(random_ids, result, entity)
                        # non-album
                        return await env.bot.send_message(entity=self.user_id,
                                                          message=self.plain_text,
                                                          formatting_entities=self.format_entities,
                                                          file=self.media,
                                                          attributes=self.attributes,
                                                          reply_to=reply_to,
                                                          link_preview=self.link_preview,
                                                          silent=self.silent)
            # except locks.ContextTimeoutError:
            #     logger.error(f'Msg dropped due to lock acquisition timeout ({self.user_id})')
            #     return None
            except (FloodWaitError, SlowModeWaitError) as e:
                # telethon internally catches these errors and retries for us
                self.tries += 2
                if self.tries >= self.max_tries:
                    logger.error(f'Msg dropped due to too many flood control retries ({self.user_id})')
                    return None
                await locks.user_flood_wait_background(self.user_id, seconds=e.seconds)  # acquire a flood wait
            except ServerError as e:
                # telethon internally catches this error and retries for us
                self.tries += 2
                if self.tries >= self.max_tries:
                    raise e
            except TimedOutError as e:
                # telethon does not catch this error or retry for us, so we do it ourselves
                self.tries += 1
                if self.tries >= self.max_tries:
                    raise e
