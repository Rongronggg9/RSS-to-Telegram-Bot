from typing import List, Union, Optional, Tuple
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAnimated

from src import log, env
from src.parsing.medium import Medium

logger = log.getLogger('RSStT.message')


class Message:
    no_retry = False

    # _fc_lock = threading.Lock()

    def __init__(self,
                 text: Optional[str] = None,
                 media: Optional[Union[List[Medium], Tuple[Medium], Medium]] = None,
                 parse_mode: Optional[str] = 'HTML'):
        self.text = text
        self.media = media
        self.parse_mode = parse_mode
        self.retries = 0

    async def send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        # if self.no_retry and self.retries >= 1:
        #     logger.warning('Message dropped: this message was configured not to retry.')
        #     return
        # elif self.retries >= 3:  # retried twice, tried 3 times in total
        #     logger.warning('Message dropped: retried for too many times.')
        #     raise OverflowError
        #
        # try:
        #     with self._fc_lock:  # if not blocked, continue; otherwise, wait
        #         pass
        #
        #     if self.retries > 0:
        #         time.sleep(random.uniform(0, 3))
        #         logger.info('Retrying...')
        #
        #     await self._send(chat_id, reply_to_msg_id)
        # except telegram.error.RetryAfter as e:  # exceed flood control
        #     logger.warning(e.message)
        #     self.retries += 1
        #
        #     if self._fc_lock.acquire(blocking=False):  # if not already blocking
        #         try:  # block any other sending tries
        #             logger.info('Blocking any sending tries due to flood control...')
        #             time.sleep(e.retry_after + 1)
        #             logger.info('Unblocked.')
        #         finally:
        #             self._fc_lock.release()
        #
        #     await self.send(chat_id)
        #     return
        # except telegram.error.BadRequest as e:
        #     if self.no_retry:
        #         logger.warning('Something went wrong while sending a message. Please check: ', exc_info=e)
        #         return
        #     raise e  # let post.py to deal with it
        # except telegram.error.NetworkError as e:
        #     logger.warning(f'Network error({e.message}).')
        #     self.retries += 1
        #     await self.send(chat_id)
        await self._send(chat_id, reply_to_msg_id)

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


class MediaGroupMsg(Message):
    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        media_list = list(map(lambda m: m.telegramize(), self.media))
        await env.bot.send_message(chat_id, self.text,
                                   file=media_list,
                                   parse_mode=self.parse_mode,
                                   reply_to=reply_to_msg_id)
