from typing import List, Union, Optional, Tuple
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAnimated
from telethon.errors.rpcerrorlist import FloodError

from src import log, env
from src.parsing.medium import Medium

logger = log.getLogger('RSStT.message')


class Message:
    no_retry = False

    def __init__(self,
                 text: Optional[str] = None,
                 media: Optional[Union[List[Medium], Tuple[Medium], Medium]] = None,
                 parse_mode: Optional[str] = 'HTML'):
        self.text = text
        self.media = media
        self.parse_mode = parse_mode
        self.retries = 0

    async def send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        # do not need flood control waiting or network error retrying because telethon will automatically perform them
        try:
            await self._send(chat_id, reply_to_msg_id)
        except FloodError:  # telethon has retried due to flood control for too many times
            logger.warning('Msg dropped due to too many flood control retries')
            return

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
    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        media_list = list(map(lambda m: m.telegramize(), self.media))
        await env.bot.send_message(chat_id, self.text,
                                   file=media_list,
                                   parse_mode=self.parse_mode,
                                   reply_to=reply_to_msg_id)
