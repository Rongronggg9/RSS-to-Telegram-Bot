from __future__ import annotations
from typing import Union

from telethon.errors import (
    UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError, InputUserDeactivatedError,
    PhotoInvalidDimensionsError, PhotoSaveFileInvalidError, PhotoInvalidError, PhotoCropSizeSmallError,
    PhotoContentUrlEmptyError, PhotoContentTypeInvalidError, GroupedMediaInvalidError, MediaGroupedInvalidError,
    MediaInvalidError, VideoContentTypeInvalidError, VideoFileInvalidError, ExternalUrlInvalidError,
    WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError, ChatAdminRequiredError
)


class EntityNotFoundError(ValueError):
    def __init__(self, peer: Union[int, str]):
        self.peer = peer
        super().__init__(f"Entity not found: {peer}")


UserBlockedErrors: tuple = (UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError,
                            InputUserDeactivatedError, ChatAdminRequiredError, EntityNotFoundError)
InvalidMediaErrors: tuple = (PhotoInvalidDimensionsError, PhotoSaveFileInvalidError, PhotoInvalidError,
                             PhotoCropSizeSmallError, PhotoContentUrlEmptyError, PhotoContentTypeInvalidError,
                             GroupedMediaInvalidError, MediaGroupedInvalidError, MediaInvalidError,
                             VideoContentTypeInvalidError, VideoFileInvalidError, ExternalUrlInvalidError)
ExternalMediaFetchFailedErrors: tuple = (WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError)
MediaSendFailErrors = InvalidMediaErrors + ExternalMediaFetchFailedErrors
