from typing import Union

from telethon.errors import (
    UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError, InputUserDeactivatedError,
    PhotoInvalidDimensionsError, PhotoSaveFileInvalidError, PhotoInvalidError, PhotoCropSizeSmallError,
    PhotoContentUrlEmptyError, PhotoContentTypeInvalidError, GroupedMediaInvalidError, MediaGroupedInvalidError,
    MediaInvalidError, VideoContentTypeInvalidError, VideoFileInvalidError, ExternalUrlInvalidError,
    WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError
)


class EntityNotFoundError(ValueError):
    def __init__(self, peer: Union[int, str]):
        self.peer = peer
        super().__init__(f"Entity not found: {peer}")


UserBlockedErrors = (UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError,
                     InputUserDeactivatedError, EntityNotFoundError)
InvalidMediaErrors = (PhotoInvalidDimensionsError, PhotoSaveFileInvalidError, PhotoInvalidError,
                      PhotoCropSizeSmallError, PhotoContentUrlEmptyError, PhotoContentTypeInvalidError,
                      GroupedMediaInvalidError, MediaGroupedInvalidError, MediaInvalidError,
                      VideoContentTypeInvalidError, VideoFileInvalidError, ExternalUrlInvalidError)
ExternalMediaFetchFailedErrors = (WebpageCurlFailedError, WebpageMediaEmptyError, MediaEmptyError)
