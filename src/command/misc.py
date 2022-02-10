from typing import Optional
from telethon import events

from .utils import command_gatekeeper
from src.i18n import i18n


# bypassing command gatekeeper
async def callback_null(event: events.CallbackQuery.Event):  # callback data = null
    await event.answer(cache_time=3600)


@command_gatekeeper(only_manager=False)
async def callback_cancel(event: events.CallbackQuery.Event,
                          *_,
                          lang: Optional[str] = None,
                          **__):  # callback data = cancel
    await event.edit(i18n[lang]['canceled_by_user'])
