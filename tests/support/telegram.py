from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class SentTelegramMessage:
    entity: object
    message: object
    kwargs: Mapping[str, object]


class RecordingTelegram:
    def __init__(self) -> None:
        self.messages: list[SentTelegramMessage] = []

    async def get_input_entity(self, entity: object) -> object:
        return entity

    async def send_message(
        self,
        entity: object,
        message: object = None,
        **kwargs: object,
    ) -> SentTelegramMessage:
        sent = SentTelegramMessage(entity=entity, message=message, kwargs=kwargs)
        self.messages.append(sent)
        return sent

    async def wait_for_message_count(self, count: int, timeout: float = 1.0) -> None:
        async def wait_until_ready() -> None:
            while len(self.messages) < count:
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_until_ready(), timeout)


@pytest.fixture
def recording_telegram(monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingTelegram]:
    from src import env

    recorder = RecordingTelegram()
    monkeypatch.setattr(env, "bot", recorder)
    yield recorder
