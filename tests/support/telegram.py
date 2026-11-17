from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import ClassVar

import pytest
from telethon.tl import types


@dataclass(frozen=True)
class SentTelegramMessage:
    SUBCLASS_OF_ID: ClassVar[int] = 0x790009E3
    entity: object
    message: object
    kwargs: Mapping[str, object]
    id: int = field(default=0, compare=False)


class RecordingTelegram:
    def __init__(self) -> None:
        self.messages: list[SentTelegramMessage] = []
        self.send_attempts: list[SentTelegramMessage] = []
        self.requests: list[object] = []
        self._send_errors: defaultdict[object, deque[BaseException]] = defaultdict(deque)
        self._request_outcomes: deque[object | BaseException] = deque()
        self._pending_notifications: deque[
            tuple[Callable[[object], Awaitable[None]], object]
        ] = deque()

    def fail_next_send(self, entity: object, error: BaseException) -> None:
        self._send_errors[entity].append(error)

    def enqueue_request_outcome(self, outcome: object | BaseException) -> None:
        self._request_outcomes.append(outcome)

    def defer_notification(
        self,
        notify: Callable[[object], Awaitable[None]],
        notifier: object,
    ) -> None:
        self._pending_notifications.append((notify, notifier))

    async def complete_notifications(self) -> None:
        while self._pending_notifications:
            notify, notifier = self._pending_notifications.popleft()
            await notify(notifier)


    async def get_input_entity(self, entity: object) -> object:
        return entity

    async def send_message(
        self,
        entity: object,
        message: object = None,
        **kwargs: object,
    ) -> SentTelegramMessage:
        sent = SentTelegramMessage(
            entity=entity,
            message=message,
            kwargs=kwargs,
            id=len(self.send_attempts) + 1,
        )
        self.send_attempts.append(sent)
        if errors := self._send_errors.get(entity):
            raise errors.popleft()
        self.messages.append(sent)
        return sent

    async def __call__(self, request: object) -> object:
        self.requests.append(request)
        if self._request_outcomes:
            outcome = self._request_outcomes.popleft()
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        media = getattr(request, "media", None)
        message_id = len(self.requests)
        if isinstance(media, types.InputMediaPhotoExternal):
            return types.MessageMediaPhoto(photo=types.PhotoEmpty(id=message_id))
        if isinstance(media, types.InputMediaDocumentExternal):
            return types.MessageMediaDocument(document=types.DocumentEmpty(id=message_id))
        return request


@pytest.fixture
def recording_telegram(monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingTelegram]:
    from src import env, locks
    from src.monitor import Monitor
    from src.monitor._notifier import Notifier
    from src.parsing.message import MessageDispatcher

    recorder = RecordingTelegram()
    original_notify_all = Notifier.notify_all
    original_monitor = Monitor._do_monitor_a_feed

    async def defer_notify_all(self: object) -> None:
        recorder.defer_notification(original_notify_all.raw, self)

    async def monitor_and_complete(
        self: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        try:
            return await original_monitor(self, *args, **kwargs)
        finally:
            await recorder.complete_notifications()

    setattr(defer_notify_all, "raw", original_notify_all.raw)
    monkeypatch.setattr(Notifier, "notify_all", defer_notify_all)
    monkeypatch.setattr(Monitor, "_do_monitor_a_feed", monitor_and_complete)
    monkeypatch.setattr(
        Notifier,
        "_on_blocked_lock_bucket",
        type(Notifier._on_blocked_lock_bucket)(
            Notifier._on_blocked_lock_bucket.default_factory
        ),
    )
    monkeypatch.setattr(
        Notifier,
        "_user_blocked_counter",
        type(Notifier._user_blocked_counter)(),
    )
    monkeypatch.setattr(Notifier, "_stat", type(Notifier._stat)())
    monkeypatch.setattr(
        MessageDispatcher,
        "user_sending_lock",
        type(MessageDispatcher.user_sending_lock)(
            MessageDispatcher.user_sending_lock.default_factory
        ),
    )
    monkeypatch.setattr(
        locks,
        "_user_bucket",
        type(locks._user_bucket)(locks._user_bucket.default_factory),
    )

    monkeypatch.setattr(env, "bot", recorder)
    yield recorder
    assert not recorder._pending_notifications
