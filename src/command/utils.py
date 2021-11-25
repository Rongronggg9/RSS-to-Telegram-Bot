import re
from functools import partial, wraps
from typing import Union, Optional, AnyStr, Any
from zlib import crc32
from telethon import events
from telethon.tl import types
from telethon.tl.custom import Message
from telethon.tl.functions.channels import GetParticipantRequest

from src import env, log, db

logger = log.getLogger('RSStT.command')


# ANONYMOUS_ADMIN = 1087968824  # no need for MTProto, user_id will be `None` for anonymous admins


def parse_command(command: str) -> list[AnyStr]:
    return re.compile(r'\s+').split(command.strip())


def get_hash(string: AnyStr) -> str:
    if isinstance(string, str):
        string = string.encode('utf-8')
    return hex(crc32(string))[2:]


def permission_required(func=None, *, only_manager=False, only_in_private_chat=False):
    if func is None:
        return partial(permission_required, only_manager=only_manager,
                       only_in_private_chat=only_in_private_chat)

    @wraps(func)
    async def wrapper(event: Union[events.NewMessage.Event, events.CallbackQuery.Event, Message], *args, **kwargs):
        try:
            command = (event.text if hasattr(event, 'text') and event.text else
                       f'(callback){event.data.decode()}' if hasattr(event, 'data') else '(no command, file message)')
            if command.startswith('/') and '@' in command:
                mention = parse_command(command)[0].split('@')[1]
                if mention != env.bot_peer.username:
                    raise events.StopPropagation  # none of my business!

            sender_id: Optional[int] = event.sender_id  # `None` if the sender is an anonymous admin in a group
            sender: Optional[Union[types.User, types.Channel]] = await event.get_sender()  # ditto
            sender_fullname = (
                sender.title if isinstance(sender, types.Channel) else
                (sender.first_name + (f' {sender.last_name}' if sender.last_name else '')) if sender is not None else
                '__anonymous_admin__'
            )

            if (only_manager or not env.MULTIUSER) and sender_id != env.MANAGER:
                await event.respond('此命令只可由机器人的管理员使用。\n'
                                    'This command can be only used by the bot manager.')
                logger.info(f'Refused {sender_fullname} ({sender_id}) to use {command}.')
                raise events.StopPropagation

            if (
                    event.is_private or
                    (  # a supergroup is also a channel but we only expect a "real" channel here
                            event.is_channel and not event.is_group
                    )
                    and not only_manager and not only_in_private_chat
            ):  # we can deal with private chats and channels in the same way
                await db.User.get_or_create(id=sender_id)
                logger.info(f'Allowed {sender_fullname} ({sender_id}) to use {command}.')
                await func(event, *args, **kwargs)
                raise events.StopPropagation

            if event.is_group and not only_manager:
                if isinstance(sender, types.Channel):
                    raise events.StopPropagation  # bound channel messages in discussion groups are none of my business

                chat: types.Chat = await event.get_chat()

                if only_in_private_chat:
                    await event.respond('此命令不允许在群聊中使用。\n'
                                        'This command can not be used in a group.')
                    logger.info(f'Refused {sender_fullname} ({sender_id}) to use {command} in '
                                f'{chat.title} ({event.chat_id}).')
                    raise events.StopPropagation

                input_chat: types.InputChannel = await event.get_input_chat()  # supergroup is a special form of channel
                input_sender: types.InputPeerUser = await event.get_input_sender()

                if sender_id is not None:  # a "real" user
                    participant: types.channels.ChannelParticipant = await env.bot(
                        GetParticipantRequest(input_chat, input_sender))
                    is_admin = (isinstance(participant.participant, types.ChannelParticipantAdmin)
                                or isinstance(participant.participant, types.ChannelParticipantCreator))
                    participant_type = type(participant.participant).__name__
                else:  # an anonymous admin
                    is_admin = True
                    participant_type = 'AnonymousAdmin'

                if not is_admin:
                    await event.respond('此命令只可由群管理员使用。\n'
                                        'This command can be only used by an administrator.')
                    logger.info(
                        f'Refused {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                        f'in {chat.title} ({event.chat_id}).')
                    raise events.StopPropagation

                await db.User.get_or_create(id=event.chat_id)
                logger.info(
                    f'Allowed {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                    f'in {chat.title} ({event.chat_id}).')
                await func(event, *args, **kwargs)
                raise events.StopPropagation
        except events.StopPropagation as e:
            raise e
        except Exception as e:
            await event.respond('ERROR: 未被捕捉的内部错误')
            raise e

    return wrapper


def escape_html(raw: Any) -> str:
    raw = str(raw)
    return raw.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class NewFileMessage(events.NewMessage):
    def __init__(self, chats=None, *, blacklist_chats=False, func=None, incoming=None, outgoing=None, from_users=None,
                 forwards=None, pattern=None, filename_pattern: str = None):
        self.filename_pattern = re.compile(filename_pattern).match
        super().__init__(chats, blacklist_chats=blacklist_chats, func=func, incoming=incoming, outgoing=outgoing,
                         from_users=from_users, forwards=forwards, pattern=pattern)

    def filter(self, event: Union[events.NewMessage.Event, Message]):
        document: types.Document = event.message.document
        if not document:
            return
        if self.filename_pattern:
            filename = None
            for attr in document.attributes:
                if isinstance(attr, types.DocumentAttributeFilename):
                    filename = attr.file_name
                    break
            if not self.filename_pattern(filename or ''):
                return
        return super().filter(event)


class ReplyMessage(events.NewMessage):
    def __init__(self, chats=None, *, blacklist_chats=False, incoming=None, outgoing=None, from_users=None,
                 forwards=None, pattern=None, reply_to_peer_id: int = None):
        self.reply_to_peer_id = reply_to_peer_id or env.bot_id
        super().__init__(chats, blacklist_chats=blacklist_chats, func=self.__reply_verify, incoming=incoming,
                         outgoing=outgoing, from_users=from_users, forwards=forwards, pattern=pattern)

    async def __reply_verify(self, event: Union[events.NewMessage.Event, Message]):
        if event.is_reply:
            reply_to_msg: Optional[Message] = await event.get_reply_message()
            if reply_to_msg is not None and self.reply_to_peer_id == reply_to_msg.sender_id:
                return True
        return False


class PrivateMessage(events.NewMessage):
    def __init__(self, chats=None, *, blacklist_chats=False, incoming=None, outgoing=None, from_users=None,
                 forwards=None, pattern=None):
        super().__init__(chats, blacklist_chats=blacklist_chats, func=self.__in_private_chat, incoming=incoming,
                         outgoing=outgoing, from_users=from_users, forwards=forwards, pattern=pattern)

    @staticmethod
    def __in_private_chat(event: Union[events.NewMessage.Event, Message]):
        return event.is_private
