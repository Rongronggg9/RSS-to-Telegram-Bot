import re
from functools import partial, wraps
from typing import Union, Optional, AnyStr, Any, List, Tuple, Callable
from telethon import events
from telethon.tl import types
from telethon.tl.patched import Message, MessageService
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import FloodError, UserNotParticipantError, UserIsBlockedError, ChatWriteForbiddenError, \
    UserIdInvalidError

from src import env, log, db
from src.i18n import i18n

logger = log.getLogger('RSStT.command')


# ANONYMOUS_ADMIN = 1087968824  # no need for MTProto, user_id will be `None` for anonymous admins


def parse_command(command: str) -> list[AnyStr]:
    return re.compile(r'\s+').split(command.strip())


def parse_callback_data_with_page(callback_data: bytes) -> Tuple[int, int]:
    """
    callback data = command_{id}[|{page}]

    :param callback_data: callback data
    :return: id, page
    """
    callback_data = callback_data.decode().strip()
    id_and_page = callback_data.split('|')
    _id = int(id_and_page[0].split('_')[-1])
    page = int(id_and_page[1]) if len(id_and_page) > 1 else 1
    return _id, page


def parse_sub_customization_callback_data(callback_data: bytes) \
        -> Tuple[Optional[int], Optional[str], Optional[Union[int, str]], int]:
    """
    callback data = command[_{id}[_{action}[_{param}]]][|{page_number}]

    :param callback_data: callback data
    :return: id, action, param
    """
    callback_data = callback_data.decode().strip()
    args = callback_data.split('|')
    page = int(args[1]) if len(args) > 1 else 1
    args = args[0].split('_')

    _id: Optional[int] = int(args[1]) if len(args) > 1 else None
    action: Optional[str] = args[2] if len(args) > 2 else None
    param: Optional[Union[int, str]] = args[3] if len(args) > 3 else None
    if param and param.lstrip('-').isdecimal():
        param = int(param)

    return _id, action, param, page


async def respond_or_answer(event: Union[events.NewMessage.Event, events.CallbackQuery.Event, Message], msg: str,
                            alert: bool = True, cache_time: int = 120, *args, **kwargs):
    """
    Respond to a ``NewMessage`` event, or answer to a ``CallbackQuery`` event.

    :param event: a telethon Event object, NewMessage or CallbackQuery
    :param msg: the message to send
    :param alert: alert or not? (only for CallbackQuery)
    :param cache_time: cache the answer for how many seconds on the server side? (only for CallbackQuery)
    :param args: additional params (only for NewMessage)
    :param kwargs: additional params (only for NewMessage)
    """
    if isinstance(event, events.CallbackQuery.Event):
        await event.answer(msg, alert=alert, cache_time=cache_time)
    else:
        try:
            await event.respond(msg, *args, **kwargs)
        except (UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError):
            pass


def permission_required(func: Optional[Callable] = None,
                        *,
                        only_manager: bool = False,
                        only_in_private_chat: bool = False,
                        ignore_tg_lang: bool = False):
    if func is None:
        return partial(permission_required, only_manager=only_manager,
                       only_in_private_chat=only_in_private_chat)

    @wraps(func)
    async def wrapper(event: Union[events.NewMessage.Event, Message,
                                   events.CallbackQuery.Event,
                                   events.ChatAction.Event],
                      *args, **kwargs):
        # placeholders
        lang = None
        command: Optional[str] = None
        sender_id: Optional[int] = None
        sender: Optional[Union[types.User, types.Channel]] = None
        sender_fullname: Optional[str] = None
        chat_id: Optional[int] = None
        chat_title: Optional[str] = None
        participant_type: Optional[str] = None

        try:
            chat_id = event.chat_id
            is_callback = isinstance(event, events.CallbackQuery.Event)
            is_chat_action = isinstance(event, events.ChatAction.Event)
            command = (event.text
                       if hasattr(event, 'text') and event.text else
                       f'(Callback){event.data.decode()}'
                       if is_callback else
                       f'(ChatAction, {event.action_message and event.action_message.action.__class__.__name__})'
                       if is_chat_action else
                       '(no command, other message)')
            if command.startswith('/') and '@' in command:
                mention = parse_command(command)[0].split('@')[-1]
                if mention != env.bot_peer.username:
                    raise events.StopPropagation  # none of my business!

            if is_chat_action and event.action_message:  # service message
                action_message: MessageService = event.action_message
                sender_id = action_message.sender_id
                sender = await action_message.get_sender()
            elif not is_chat_action:  # message or callback
                sender_id = event.sender_id  # `None` if the sender is an anonymous admin in a group
                sender = await event.get_sender()  # ditto

            sender_fullname = (
                sender.title
                if isinstance(sender, types.Channel) else
                (sender.first_name + (f' {sender.last_name}' if sender.last_name else ''))
                if sender is not None else
                '__anonymous_admin__'
                if not is_chat_action else
                '__chat_action__'
            )

            # get the user's lang
            lang_in_db = await db.User.get_or_none(id=chat_id).values_list('lang', flat=True)
            lang = lang_in_db if lang_in_db != 'null' else None
            if not lang and not ignore_tg_lang:
                lang = sender.lang_code if hasattr(sender, 'lang_code') else None
                if not lang and sender_id != chat_id:
                    lang = db.User.get_or_none(id=sender_id).values_list('lang', flat=True)

            if (only_manager or not env.MULTIUSER) and sender_id != env.MANAGER:
                await respond_or_answer(event, i18n[lang]['permission_denied_not_bot_manager'])
                logger.warning(f'Refused {sender_fullname} ({sender_id}) to use {command} '
                               f'because the command can only be used by a bot manager.')
                raise events.StopPropagation

            if (
                    event.is_private or  # deal with commands in private chats
                    (
                            (event.is_channel  # deal with commands in channels
                             # a supergroup is also a channel, but we only expect a "real" channel here
                             and not event.is_group)
                            # if receiving a callback, we must verify that the sender is an admin. jump below
                            and not is_callback
                    )
                    and not only_manager and not only_in_private_chat
            ):  # we can deal with private chats and channels in the same way
                if lang_in_db is None:
                    await db.User.get_or_create(id=sender_id, lang='null')  # create the user if it doesn't exist
                logger.info(f'Allowed {sender_fullname} ({sender_id}) to use {command}.')
                await func(event, lang=lang, *args, **kwargs)
                raise events.StopPropagation

            if (
                    (
                            event.is_group or  # deal with commands in groups
                            (event.is_channel and is_callback)  # deal with callback in channels
                    )
                    and not only_manager
            ):  # receiving a command in a group, or, a callback in a channel
                if isinstance(sender, types.Channel):
                    raise events.StopPropagation  # channel messages are none of my business

                # supergroup is a special form of channel
                input_chat: Optional[Union[types.InputChannel,
                                           types.InputPeerChannel,
                                           types.InputPeerChat]] = await event.get_input_chat()
                chat: Optional[Union[types.Chat, types.Channel]] = await event.get_chat()
                chat_title = chat and chat.title

                if only_in_private_chat:
                    await respond_or_answer(event, i18n[lang]['permission_denied_not_in_private_chat'])
                    logger.warning(f'Refused {sender_fullname} ({sender_id}) to use {command} in '
                                   f'{chat_title} ({chat_id}) because the command can only be used in a private chat')
                    raise events.StopPropagation

                if isinstance(input_chat, types.InputPeerChat):
                    # oops, the group hasn't been migrated to a supergroup. a migration is needed
                    await event.respond('\n\n'.join(i18n.get_all_l10n_string('group_upgrade_needed_prompt')))
                    logger.warning(f'Refused {sender_fullname} ({sender_id}) to use {command} in '
                                   f'{chat_title} ({chat_id}) because a group migration to supergroup is needed')
                    raise events.StopPropagation

                # check if self is in the group/chanel and if is an admin
                self_is_admin = True  # bypass check if the event is a callback query, set to True for convenience
                if is_callback:
                    try:
                        self_participant: types.channels.ChannelParticipant = await env.bot(
                            GetParticipantRequest(input_chat, env.bot_input_peer))
                        self_is_admin = isinstance(self_participant.participant,
                                                   (types.ChannelParticipantAdmin, types.ChannelParticipantCreator))
                    except UserNotParticipantError:  # I am not a participant of the group/channel, none of my business!
                        await respond_or_answer(event, i18n[lang]['permission_denied_bot_not_member'], cache_time=15)
                        raise events.StopPropagation

                # user permission check
                if is_chat_action:
                    is_admin = True
                    participant_type = 'ChatAction, bypassing admin check'
                elif sender_id is not None:  # a "real" user triggering the command
                    input_sender: types.InputPeerUser = await event.get_input_sender()
                    try:
                        participant: types.channels.ChannelParticipant = await env.bot(
                            GetParticipantRequest(input_chat, input_sender))
                    except UserNotParticipantError:
                        await respond_or_answer(event,
                                                i18n[lang]['permission_denied_not_member'] if self_is_admin else
                                                i18n[lang]['promote_to_admin_prompt'],
                                                cache_time=15)
                        logger.warning(f'Refused {sender_fullname} ({sender_id}) to use {command} in '
                                       f'{chat_title} ({chat_id}) because they is not a participant')
                        raise events.StopPropagation
                    is_admin = isinstance(participant.participant,
                                          (types.ChannelParticipantAdmin, types.ChannelParticipantCreator))
                    participant_type = type(participant.participant).__name__
                else:  # an anonymous admin
                    is_admin = True
                    participant_type = 'AnonymousAdmin'

                if not is_admin:
                    await respond_or_answer(event, i18n[lang]['permission_denied_not_chat_admin'], cache_time=15)
                    logger.warning(
                        f'Refused {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                        f'in {chat_title} ({chat_id}).')
                    raise events.StopPropagation

                if lang_in_db is None:
                    await db.User.get_or_create(id=chat_id, lang='null')  # create the user if it doesn't exist
                logger.info(
                    f'Allowed {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                    f'in {chat_title} ({chat_id}).')
                await func(event, lang=lang, *args, **kwargs)
                raise events.StopPropagation

        except events.StopPropagation as e:
            raise e
        except Exception as e:
            logger.error(
                f'Uncaught error occurred when {sender_fullname} '
                + f'({sender_id}'
                + (f', {participant_type}' if participant_type else '')
                + f') '
                + f'attempting to use {command}'
                + (f' in {chat_title} ({chat_id})' if chat_id != sender_id else ''),
                exc_info=e
            )
            if isinstance(e, FloodError):
                return  # if a flood error occurred, mostly we cannot send an error msg...
            await respond_or_answer(event, 'ERROR: ' + i18n[lang]['uncaught_internal_error'])

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


class AddedToGroupAction(events.ChatAction):
    """Chat actions that are triggered when the bot has been added to a group."""

    def __init__(self, chats=None, *, blacklist_chats=False):
        super().__init__(chats, blacklist_chats=blacklist_chats, func=self.__added_to_group)

    @staticmethod
    def __added_to_group(event: events.ChatAction.Event):
        if not event.is_group:
            return False
        if event.created:
            return True  # group created or migrated
        if event.user_added or isinstance(event.action_message.action, types.MessageActionChatAddUser):
            return env.bot_id in event.user_ids  # added to a group
        return False


class GroupMigratedAction(events.ChatAction):
    """Chat actions that are triggered when a group has been migrated to a supergroup."""

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if (isinstance(update, (
                types.UpdateNewMessage, types.UpdateNewChannelMessage))
                and isinstance(update.message, types.MessageService)):
            msg = update.message
            action = update.message.action
            if isinstance(action, types.MessageActionChannelMigrateFrom):
                return cls.Event(msg)


def get_commands_list(lang: Optional[str] = None, manager: bool = False) -> List[types.BotCommand]:
    commands = [
        types.BotCommand(command="sub", description=i18n[lang]['cmd_description_sub']),
        types.BotCommand(command="unsub", description=i18n[lang]['cmd_description_unsub']),
        types.BotCommand(command="unsub_all", description=i18n[lang]['cmd_description_unsub_all']),
        types.BotCommand(command="list", description=i18n[lang]['cmd_description_list']),
        types.BotCommand(command="set", description=i18n[lang]['cmd_description_set']),
        types.BotCommand(command="import", description=i18n[lang]['cmd_description_import']),
        types.BotCommand(command="export", description=i18n[lang]['cmd_description_export']),
        types.BotCommand(command="activate_subs", description=i18n[lang]['cmd_description_activate_subs']),
        types.BotCommand(command="deactivate_subs", description=i18n[lang]['cmd_description_deactivate_subs']),
        types.BotCommand(command="version", description=i18n[lang]['cmd_description_version']),
        types.BotCommand(command="lang", description=i18n[lang]['cmd_description_lang']),
        types.BotCommand(command="help", description=i18n[lang]['cmd_description_help']),
    ]

    if manager:
        commands.extend(
            (
                types.BotCommand(command="test", description=i18n[lang]['cmd_description_test']),
                types.BotCommand(command="set_option", description=i18n[lang]['cmd_description_set_option']),
            )
        )

    return commands


async def set_bot_commands(scope: Union[types.BotCommandScopeDefault,
                                        types.BotCommandScopePeer,
                                        types.BotCommandScopePeerAdmins,
                                        types.BotCommandScopeUsers,
                                        types.BotCommandScopeChats,
                                        types.BotCommandScopePeerUser,
                                        types.BotCommandScopeChatAdmins],
                           lang_code: str,
                           commands: List[types.BotCommand]):
    await env.bot(
        SetBotCommandsRequest(scope=scope, lang_code=lang_code, commands=commands)
    )
