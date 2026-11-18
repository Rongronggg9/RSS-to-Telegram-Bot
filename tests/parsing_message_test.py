from types import SimpleNamespace

import pytest
from telethon.errors.rpcbaseerrors import TimedOutError
from telethon.errors.rpcerrorlist import FloodWaitError, MediaInvalidError, ServerError
from telethon.tl import functions, types

from src import env, locks
from src.parsing.medium import ANIMATION, IMAGE, MEDIA_GROUP, VIDEO
from src.parsing.message import Message, MessageDispatcher


class _FakeInvalidMediaNode:
    def __init__(self, html: str):
        self._html = html

    def get_html(self) -> str:
        return self._html


class _FakeMedia:
    def __init__(self, media_and_types, invalid_html=None):
        self._media_and_types = list(media_and_types)
        self._invalid_html = invalid_html
        self.upload_calls = []

    async def upload_all(self, user_id: int):
        self.upload_calls.append(user_id)
        return list(self._media_and_types), (
            _FakeInvalidMediaNode(self._invalid_html) if self._invalid_html is not None else None
        )


def test_message_dispatcher_requires_html_or_media():
    with pytest.raises(ValueError, match='At least one of html or media must be specified'):
        MessageDispatcher(user_id=101)


def test_message_dispatcher_generate_messages_with_invalid_media_and_trailing_media():
    media = _FakeMedia(
        media_and_types=[('img1', IMAGE), ('img2', IMAGE)],
        invalid_html='<b>Skipped</b>\n<i>bad image</i>',
    )
    dispatcher = MessageDispatcher(
        user_id=102,
        html='<b>Headline</b>',
        media=media,
        link_preview=True,
        silent=True,
    )

    env.loop.run_until_complete(dispatcher.generate_messages())

    assert media.upload_calls == [102]
    assert len(dispatcher.messages) == 2
    first, second = dispatcher.messages
    assert first.plain_text == 'Headline\n\nSkipped bad image'
    assert first.media == 'img1'
    assert first.media_type == IMAGE
    assert first.link_preview is True
    assert first.silent is True
    assert second.plain_text is None
    assert second.format_entities is None
    assert second.media == 'img2'
    assert second.media_type == IMAGE


def test_message_dispatcher_generate_messages_media_only():
    media = _FakeMedia(media_and_types=[('vid1', VIDEO)], invalid_html=None)
    dispatcher = MessageDispatcher(user_id=103, html=None, media=media)

    env.loop.run_until_complete(dispatcher.generate_messages())

    assert len(dispatcher.messages) == 1
    msg = dispatcher.messages[0]
    assert msg.plain_text is None
    assert msg.media == 'vid1'
    assert msg.media_type == VIDEO
    assert msg.attributes == (types.DocumentAttributeVideo(0, 0, 0),)


def test_message_dispatcher_preserves_multiline_invalid_media_html():
    media = _FakeMedia(
        media_and_types=[],
        invalid_html='<b>Skipped</b>\n<i>bad 1</i>\n<i>bad 2</i>',
    )
    dispatcher = MessageDispatcher(user_id=104, html='<b>Body</b>', media=media)

    env.loop.run_until_complete(dispatcher.generate_messages())

    assert len(dispatcher.messages) == 1
    assert dispatcher.messages[0].plain_text == 'Body\n\nSkipped\nbad 1\nbad 2'


def test_message_attributes_by_media_type():
    video_msg = Message(user_id=1, media='v', media_type=VIDEO)
    anim_msg = Message(user_id=1, media='a', media_type=ANIMATION)
    photo_msg = Message(user_id=1, media='p', media_type=IMAGE)

    assert video_msg.attributes == (types.DocumentAttributeVideo(0, 0, 0),)
    assert anim_msg.attributes == (types.DocumentAttributeAnimated(),)
    assert photo_msg.attributes is None


def test_message_send_non_album_and_album_dispatch(monkeypatch):
    sent_calls = []
    rpc_requests = []
    fake_peer = types.InputPeerEmpty()

    class _FakeBot:
        async def send_message(self, **kwargs):
            sent_calls.append(kwargs)
            return SimpleNamespace(id=10)

        async def _file_to_media(self, medium):
            return None, types.InputMediaEmpty(), None

        async def get_input_entity(self, user_id):
            assert user_id == 201
            return fake_peer

        async def __call__(self, request):
            rpc_requests.append(request)
            return 'raw-updates'

        def _get_response_message(self, random_ids, result, entity):
            assert len(random_ids) == 2
            assert result == 'raw-updates'
            assert entity is fake_peer
            return [SimpleNamespace(id=20), SimpleNamespace(id=21)]

    monkeypatch.setattr(env, 'bot', _FakeBot(), raising=False)

    text_msg = Message(
        user_id=201,
        plain_text='hello',
        format_entities=[],
        link_preview=True,
        silent=True,
    )
    album_msg = Message(
        user_id=201,
        plain_text='album caption',
        format_entities=[types.MessageEntityBold(0, 5)],
        media=['m1', 'm2'],
        media_type=MEDIA_GROUP,
        silent=True,
    )

    first_res = env.loop.run_until_complete(text_msg.send())
    second_res = env.loop.run_until_complete(album_msg.send(reply_to=first_res.id))

    assert first_res.id == 10
    assert [m.id for m in second_res] == [20, 21]
    assert sent_calls[0]['entity'] == 201
    assert sent_calls[0]['message'] == 'hello'
    assert sent_calls[0]['reply_to'] is None
    assert len(rpc_requests) == 1
    req = rpc_requests[0]
    assert isinstance(req, functions.messages.SendMultiMediaRequest)
    assert req.reply_to == types.InputReplyToMessage(10)
    assert req.multi_media[0].message == ''
    assert req.multi_media[1].message == 'album caption'
    assert len(req.multi_media[1].entities) == 1
    assert req.silent is True


def test_message_dispatcher_send_messages_chains_replies_and_rolls_back_on_media_error(monkeypatch):
    deleted = []
    send_results = [
        SimpleNamespace(id=101),
        [SimpleNamespace(id=102), SimpleNamespace(id=103)],
        MediaInvalidError(None),
    ]
    recorded_replies = []

    class _FakeBot:
        async def delete_messages(self, user_id, msg, revoke=True):
            deleted.append((user_id, msg.id, revoke))

    monkeypatch.setattr(env, 'bot', _FakeBot(), raising=False)

    dispatcher = MessageDispatcher(user_id=301, html='<b>Part 1</b>')
    m1 = Message(user_id=301, plain_text='one')
    m2 = Message(user_id=301, plain_text='two')
    m3 = Message(user_id=301, plain_text='three')
    dispatcher.messages = [m1, m2, m3]

    async def fake_send(self, reply_to=None):
        recorded_replies.append(reply_to.id if reply_to is not None else None)
        outcome = send_results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(Message, 'send', fake_send)

    with pytest.raises(MediaInvalidError):
        env.loop.run_until_complete(dispatcher.send_messages())

    assert recorded_replies == [None, 101, 103]
    assert deleted == [(301, 101, True), (301, 102, True), (301, 103, True)]


def test_message_dispatcher_send_messages_auto_generates_and_completes(monkeypatch):
    sent = []

    class _FakeBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)
            return SimpleNamespace(id=501)

    monkeypatch.setattr(env, 'bot', _FakeBot(), raising=False)

    dispatcher = MessageDispatcher(user_id=302, html='<b>Auto</b>')
    env.loop.run_until_complete(dispatcher.send_messages())

    assert len(sent) == 1
    assert sent[0]['message'] == 'Auto'


def test_message_send_retry_handling_for_flood_server_and_timeout(monkeypatch):
    flood_waits = []

    async def fake_flood_wait(user_id, seconds):
        flood_waits.append((user_id, seconds))

    monkeypatch.setattr(locks, 'user_flood_wait_background', fake_flood_wait)

    # FloodWaitError: retries once (tries=2), drops on second failure (tries=4 >= 4)
    class _FloodBot:
        def __init__(self, succeed_after=None):
            self.calls = 0
            self.succeed_after = succeed_after

        async def send_message(self, **kwargs):
            self.calls += 1
            if self.succeed_after and self.calls > self.succeed_after:
                return 'recovered'
            raise FloodWaitError(None, 2)

    flood_drop_bot = _FloodBot()
    monkeypatch.setattr(env, 'bot', flood_drop_bot, raising=False)
    msg_drop = Message(user_id=401, plain_text='hi')
    assert env.loop.run_until_complete(msg_drop.send()) is None
    assert flood_waits == [(401, 2)]
    assert msg_drop.tries == 4

    # ServerError: retries once (tries=2), re-raises at tries=4
    class _ServerErrorBot:
        async def send_message(self, **kwargs):
            raise ServerError(None, 'SERVER_ERROR')

    monkeypatch.setattr(env, 'bot', _ServerErrorBot(), raising=False)
    msg_srv = Message(user_id=402, plain_text='hi')
    with pytest.raises(ServerError):
        env.loop.run_until_complete(msg_srv.send())
    assert msg_srv.tries == 4

    # TimedOutError: retries up to 3 times (+1 each), succeeds on 4th try or raises on 4th failure
    class _TimeoutThenOkBot:
        def __init__(self, fail_count):
            self.fail_count = fail_count
            self.calls = 0

        async def send_message(self, **kwargs):
            self.calls += 1
            if self.calls <= self.fail_count:
                raise TimedOutError(None, 'TIMEOUT')
            return 'ok-after-timeout'

    monkeypatch.setattr(env, 'bot', _TimeoutThenOkBot(fail_count=3), raising=False)
    msg_ok = Message(user_id=403, plain_text='hi')
    assert env.loop.run_until_complete(msg_ok.send()) == 'ok-after-timeout'
    assert msg_ok.tries == 3

    monkeypatch.setattr(env, 'bot', _TimeoutThenOkBot(fail_count=4), raising=False)
    msg_fail = Message(user_id=404, plain_text='hi')
    with pytest.raises(TimedOutError):
        env.loop.run_until_complete(msg_fail.send())
    assert msg_fail.tries == 4
