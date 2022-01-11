from __future__ import annotations

from asyncio import BoundedSemaphore
from collections import defaultdict
from typing import Union
from readerwriterlock.rwlock_async import RWLockWrite

_USER_LIKE = Union[int, str]


class _UserLockBucket:
    _max_concurrency_of_semaphore = 3

    def __init__(self):
        self.msg_semaphore = BoundedSemaphore(self._max_concurrency_of_semaphore)
        self.msg_rwlock = RWLockWrite()
        self.flood_rwlock = RWLockWrite()
        self.pending_callbacks = set()


_user_bucket: defaultdict[_USER_LIKE, _UserLockBucket] = defaultdict(_UserLockBucket)


def user_msg_semaphore(user: _USER_LIKE) -> BoundedSemaphore:
    return _user_bucket[user].msg_semaphore


def user_msg_rwlock(user: _USER_LIKE) -> RWLockWrite:
    return _user_bucket[user].msg_rwlock


def user_flood_rwlock(user: _USER_LIKE) -> RWLockWrite:
    return _user_bucket[user].flood_rwlock


def user_msg_locks(user: _USER_LIKE) -> tuple[BoundedSemaphore, RWLockWrite, RWLockWrite]:
    """
    :return: user_msg_semaphore, user_msg_rwlock, user_flood_rwlock
    """
    return user_msg_semaphore(user), user_msg_rwlock(user), user_flood_rwlock(user)


def user_pending_callbacks(user: _USER_LIKE) -> set:
    return _user_bucket[user].pending_callbacks

# Q: Why msg rwlock is needed?
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
