from typing import Union

from telethon.errors import UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError, \
    InputUserDeactivatedError


class EntityNotFoundError(ValueError):
    def __init__(self, peer: Union[int, str]):
        self.peer = peer
        super().__init__(f"Entity not found: {peer}")


UserBlockedErrors = (UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError,
                     InputUserDeactivatedError, EntityNotFoundError)
