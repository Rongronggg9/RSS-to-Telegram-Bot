from collections import defaultdict
from typing import List, Union, Optional, Tuple, Dict
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAnimated
from telethon.errors.rpcerrorlist import FloodError
from readerwriterlock.rwlock_async import RWLockWrite
from asyncio import BoundedSemaphore
from functools import partial

from src import log, env
from src.parsing.medium import Medium

logger = log.getLogger('RSStT.message')


class Message:
    no_retry = False
    __max_concurrency = 3
    __semaphore_bucket: Dict[Union[int, str], BoundedSemaphore] = defaultdict(
        partial(BoundedSemaphore, __max_concurrency))
    __lock_bucket: Dict[Union[int, str], RWLockWrite] = defaultdict(RWLockWrite)
    __lock_type = 'r'

    # Q: Why rwlock is needed?
    #
    # A: We are using an async telegram lib `telethon`. It sends messages asynchronously. Unfortunately,
    # sending messages to telegram is not "thread safe". Yup, you heard me right. That's all telegram's fault!
    #
    # In detail: Telegram needs time to send an album msg (media group msg) and each medium in the album is actually
    # a single media msg — telegram just displays them as an album. However, if we send multiple msgs (some of them
    # are album msgs), telegram cannot ensure that an album msg won't be interrupted by another msg. There's an
    # example. Each msg in a chat has its own id ("msg_id"). An album has no msg_id but each medium in the album has
    # a msg_id. Given that an empty chat (of no msg), let's send two msgs asynchronously — a media msg ("msg0") with
    # an image ("img0") and an album msg ("msg1") with four images ("img1"–"img4"). Sending msgs asynchronously means
    # that two sending requests will be sent almost at the same time. However, due to some reasons, for example,
    # an unstable network, it took a long time until img0 was uploaded successfully. Before that, img1 and img2 had
    # already been uploaded and were immediately sent to the chat by telegram. Img1 got the msg_id of 1 and img2 got
    # 2. Since telegram had received img0 at that moment, img0 (aka. msg0) was sent immediately and got the msg_id of
    # 3. Now the rest two images (img3 and img4) of msg1 were uploaded. Telegram sent them to the chat and gave them
    # msg_id of 4 and 5. You see, the msg_id 1,2,3,4,5 corresponded to img1,img2,img0,img3,img4 — msg1 was divided
    # into two parts! Some telegram apps (e.g. Telegram Desktop) can deal with a divided album properly while others
    # (e.g. Telegram for Android) cannot. On the latter, the two msgs becomes three msgs: album(img1,img2),
    # msg0(img0), album(img3,img4). Another issue is that sending album msgs is more easily to be flood-controlled
    # because telegram treat each medium as a single msg. Therefore, sending non-media-group msg asynchronously is
    # acceptable but sending media group msg must wait for any pending sending requests to finish and blocking any
    # coming sending requests. Rwlock fits the demand.
    #
    # TL;DR: To avoid album msg being interrupted on some telegram apps and to avoid getting flood-controlled
    # frequently.

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
            rwlock = self.__lock_bucket[chat_id]
            rlock_or_wlock = (await rwlock.gen_wlock() if self.__lock_type == 'w' else await rwlock.gen_rlock())
            semaphore = self.__semaphore_bucket[chat_id]
            async with rlock_or_wlock:
                async with semaphore:
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
    __lock_type = 'w'

    async def _send(self, chat_id: Union[str, int], reply_to_msg_id: int = None):
        media_list = list(map(lambda m: m.telegramize(), self.media))
        await env.bot.send_message(chat_id, self.text,
                                   file=media_list,
                                   parse_mode=self.parse_mode,
                                   reply_to=reply_to_msg_id)
