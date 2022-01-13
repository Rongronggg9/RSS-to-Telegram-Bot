from __future__ import annotations
from typing import Union, Optional

import asyncio
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAnimated
from telethon.errors.rpcerrorlist import SlowModeWaitError, FloodWaitError
from asyncio import BoundedSemaphore

from src import log, env, locks
from src.parsing.medium import Medium

logger = log.getLogger('RSStT.message')


class Message:
    no_retry = False
    __overall_concurrency = 30
    __overall_semaphore = BoundedSemaphore(__overall_concurrency)

    __lock_type = 'r'

    def __init__(self,
                 text: Optional[str] = None,
                 media: Optional[Union[list[Medium], list[Medium], Medium]] = None,
                 parse_mode: Optional[str] = 'HTML'):
        self.text = text
        self.media = media
        self.parse_mode = parse_mode
        self.retries = 0

    async def send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        semaphore, rwlock, flood_rwlock = locks.user_msg_locks(chat_id)
        rlock_or_wlock = await rwlock.gen_wlock() if self.__lock_type == 'w' else await rwlock.gen_rlock()
        flood_rlock_or_wlock = await flood_rwlock.gen_rlock()  # always acquire a read lock first

        async with semaphore:  # acquire user semaphore first to reduce per user concurrency
            while True:
                try:
                    async with rlock_or_wlock:  # acquire a msg rwlock
                        async with flood_rlock_or_wlock:  # acquire a flood rwlock
                            async with self.__overall_semaphore:  # only acquire overall semaphore when sending
                                await self._send(chat_id, reply_to_msg_id)
                    return
                except (FloodWaitError, SlowModeWaitError) as e:
                    # telethon has retried for us, but we release locks and retry again here to see if it will be better
                    if self.retries >= 1:
                        logger.error(f'Msg dropped due to too many flood control retries ({chat_id})')
                        return

                    self.retries += 1
                    flood_rlock_or_wlock = await flood_rwlock.gen_wlock()  # enforce a wlock here block other attempts
                    if not flood_rwlock.v_write_count:  # only flood wait once, thus only lock once
                        async with flood_rlock_or_wlock:  # acquire a flood rwlock
                            await asyncio.sleep(e.seconds + 1)  # sleep

    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        pass


class TextMsg(Message):
    link_preview = False

    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        await env.bot.send_message(chat_id, self.text,
                                   parse_mode=self.parse_mode,
                                   link_preview=self.link_preview,
                                   reply_to=reply_to_msg_id)


class BotServiceMsg(TextMsg):
    no_retry = True


class TelegraphMsg(TextMsg):
    link_preview = True


class MediaMsg(Message):
    pass


class PhotoMsg(MediaMsg):
    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        await env.bot.send_message(chat_id, self.text,
                                   file=self.media.telegramize(),
                                   parse_mode=self.parse_mode,
                                   reply_to=reply_to_msg_id)


class VideoMsg(MediaMsg):
    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        await env.bot.send_message(chat_id, self.text,
                                   file=self.media.telegramize(),
                                   attributes=(DocumentAttributeVideo(0, 0, 0),),
                                   parse_mode=self.parse_mode,
                                   reply_to=reply_to_msg_id)


class AnimationMsg(MediaMsg):
    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        await env.bot.send_message(chat_id, self.text,
                                   file=self.media.telegramize(),
                                   attributes=(DocumentAttributeAnimated(),),
                                   parse_mode=self.parse_mode,
                                   reply_to=reply_to_msg_id)


class MediaGroupMsg(MediaMsg):
    __lock_type = 'w'

    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        media_list = list(map(lambda m: m.telegramize(), self.media))
        await asyncio.sleep(0.25)  # extra sleep to avoid flood control
        await env.bot.send_message(chat_id, self.text,
                                   file=media_list,
                                   parse_mode=self.parse_mode,
                                   reply_to=reply_to_msg_id)
        await asyncio.sleep(0.25)  # extra sleep to avoid flood control
