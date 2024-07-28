#  RSS to Telegram Bot
#  Copyright (C) 2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from typing import Union

from telethon import events
from telethon.tl.patched import Message

__all__ = [
    'TypeEventMsg', 'TypeEventMsgHint', 'TypeEventCb', 'TypeEventInline', 'TypeEventChatAction',
    'TypeEventCollectionAll', 'TypeEventCollectionMsgLike', 'TypeEventCollectionMsgOrCb',
    'TypeEventCollectionMsgOrChatAction'
]

# Has: respond(), reply(), edit(), delete(), get_reply_message()
TypeEventMsg = events.NewMessage.Event
TypeEventMsgHint = Union[events.NewMessage.Event, Message]
# Has: respond(), reply(), edit(), delete(), answer()
TypeEventCb = events.CallbackQuery.Event
# Has: answer()
TypeEventInline = events.InlineQuery.Event
# Has: respond(), reply(), delete()
# Note: `events.ChatAction.Event` only have ChatGetter, do not have SenderGetter like others
TypeEventChatAction = events.ChatAction.Event

# All have: get_chat(), get_input_chat()
TypeEventCollectionAll = Union[
    events.NewMessage.Event, Message,  # Has: respond(), reply(), edit(), delete(), get_reply_message()
    events.CallbackQuery.Event,  # Has: respond(), reply(), edit(), delete(), answer()
    events.InlineQuery.Event,  # Has: answer()
    events.ChatAction.Event,  # Has: respond(), reply(), delete()
]
TypeEventCollectionMsgLike = Union[
    events.NewMessage.Event, Message,
    events.CallbackQuery.Event,
    events.ChatAction.Event,
]
TypeEventCollectionMsgOrCb = Union[
    events.NewMessage.Event, Message,
    events.CallbackQuery.Event,
]
TypeEventCollectionMsgOrChatAction = Union[
    events.NewMessage.Event, Message,
    events.ChatAction.Event,
]
