from __future__ import annotations

import pytest
from telethon.errors import PhotoInvalidDimensionsError
from telethon.tl.types import InputMediaDocumentExternal, InputMediaPhotoExternal, MessageMediaDocument

from tests.support.telegram import RecordingTelegram


@pytest.mark.telegram
async def test_image_media_fallback_chain_preserves_text_delivery_contract(
    recording_telegram: RecordingTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src import env
    from src.parsing.post import Post

    monkeypatch.setattr(env, "LAZY_MEDIA_VALIDATION", True)
    recording_telegram.enqueue_request_outcome(PhotoInvalidDimensionsError(None))
    recording_telegram.enqueue_request_outcome(PhotoInvalidDimensionsError(None))
    post = Post(
        html=(
            '<p>Text that must survive media fallback.</p>'
            '<img src="https://images.example.test/photo.jpg">'
        ),
        title="Fallback entry",
        feed_title="Fixture Feed",
        link="https://example.test/fallback-entry",
        feed_link="https://example.test/feed",
    )

    await post.send_formatted_post(
        user_id=101,
        send_mode=2,
        display_title=1,
        display_via=-2,
    )

    uploaded_media = [request.media for request in recording_telegram.requests]
    assert [type(media) for media in uploaded_media] == [
        InputMediaPhotoExternal,
        InputMediaPhotoExternal,
        InputMediaDocumentExternal,
    ]
    assert len(recording_telegram.messages) == 1
    delivered = recording_telegram.messages[0]
    assert delivered.message == "Fallback entry\n\nText that must survive media fallback."
    assert isinstance(delivered.kwargs["file"], MessageMediaDocument)
