from __future__ import annotations
from typing import Union, Optional, AnyStr, Any
from collections.abc import Callable

import asyncio
import re
from functools import partial, wraps
from telethon import events
from telethon.tl import types
from telethon.tl.patched import Message, MessageService
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import FloodError, MessageNotModifiedError, UserNotParticipantError, \
    UserIsBlockedError, ChatWriteForbiddenError, UserIdInvalidError, ChannelPrivateError

from src import env, log, db, locks
from src.i18n import i18n

logger = log.getLogger('RSStT.command')


# ANONYMOUS_ADMIN = 1087968824  # no need for MTProto, user_id will be `None` for anonymous admins


def parse_command(command: str) -> list[AnyStr]:
    return re.split(r'\s+', command.strip())


def parse_callback_data_with_page(callback_data: bytes) -> tuple[int, int]:
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
        -> tuple[Optional[int], Optional[str], Optional[Union[int, str]], int]:
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
    Respond to a ``NewMessage`` event, or answer to an unanswered ``CallbackQuery`` event.

    :param event: a telethon Event object, NewMessage or CallbackQuery
    :param msg: the message to send
    :param alert: alert or not? (only for CallbackQuery)
    :param cache_time: cache the answer for how many seconds on the server side? (only for CallbackQuery)
    :param args: additional params (only for NewMessage)
    :param kwargs: additional params (only for NewMessage)
    """
    try:
        async with await locks.user_flood_rwlock(event.chat_id).gen_rlock():
            # noinspection PyProtectedMember
            if isinstance(event, events.CallbackQuery.Event) and not event._answered:
                await event.answer(msg, alert=alert, cache_time=cache_time)
            else:
                await event.respond(msg, *args, **kwargs)
    except (UserIsBlockedError, UserIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError):
        pass


def command_gatekeeper(func: Optional[Callable] = None,
                       *,
                       only_manager: bool = False,
                       only_in_private_chat: bool = False,
                       ignore_tg_lang: bool = False,
                       timeout: int = 60):
    if func is None:
        return partial(command_gatekeeper,
                       only_manager=only_manager,
                       only_in_private_chat=only_in_private_chat,
                       ignore_tg_lang=ignore_tg_lang,
                       timeout=timeout)

    @wraps(func)
    async def wrapper(event: Union[events.NewMessage.Event, Message,
                                   events.CallbackQuery.Event,
                                   events.ChatAction.Event],
                      *args, **kwargs):
        # placeholders
        lang = None
        command: Optional[str] = None
        sender: Optional[Union[types.User, types.Channel]] = None
        sender_fullname: Optional[str] = None
        chat_title: Optional[str] = None
        participant_type: Optional[str] = None

        sender_id = event.sender_id
        chat_id = event.chat_id
        flood_rwlock = locks.user_flood_rwlock(chat_id)
        pending_callbacks = locks.user_pending_callbacks(chat_id)
        is_callback = isinstance(event, events.CallbackQuery.Event)
        is_chat_action = isinstance(event, events.ChatAction.Event)

        def describe_user():
            chat_info = None
            if (chat_title or chat_id) and chat_id != sender_id:
                chat_info = f'{chat_title or chat_id}' + (f' ({chat_id})' if chat_title and chat_id else '')
            return f'{sender_fullname} ({sender_id}' \
                   + (f', {participant_type}' if participant_type and chat_info else '') \
                   + ')' \
                   + (f' in {chat_info}' if chat_info else '')

        async def execute():
            callback_msg_id = event.message_id if is_callback else None
            # skip if already executing a callback for this msg
            if callback_msg_id and callback_msg_id in pending_callbacks:
                logger.info(f'Skipped {describe_user()} to use {command}: already executing a callback for this msg')
                await respond_or_answer(event, i18n[lang]['callback_already_running_prompt'], cache_time=0)
                raise events.StopPropagation

            if callback_msg_id:
                pending_callbacks.add(callback_msg_id)
            try:
                if lang_in_db is None:
                    await db.User.get_or_create(id=chat_id, lang='null')  # create the user if it doesn't exist
                logger.info(f'Allow {describe_user()} to use {command}')
                async with await flood_rwlock.gen_rlock():
                    await asyncio.wait_for(func(event, *args, lang=lang, **kwargs), timeout=timeout)
            except asyncio.TimeoutError as _e:
                logger.error(f'Cancel {command} for {describe_user()} due to timeout ({timeout}s)', exc_info=_e)
            finally:
                if callback_msg_id:
                    try:
                        pending_callbacks.remove(callback_msg_id)
                    except KeyError:
                        pass

        try:
            command = (event.raw_text
                       if hasattr(event, 'raw_text') and event.raw_text else
                       f'(Callback){event.data.decode()}'
                       if is_callback else
                       f'(ChatAction, {event.action_message and event.action_message.action.__class__.__name__})'
                       if is_chat_action else
                       '(no command, other message)')
            command_header = parse_command(command)[0]
            if command_header.startswith('/') and '@' in command_header:
                mention = command_header.split('@')[-1]
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
                logger.warning(f'Refused {describe_user()} to use {command} '
                               f'because the command can only be used by a bot manager')
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
                await execute()
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
                    logger.warning(f'Refused {describe_user()} to use {command} '
                                   f'because the command can only be used in a private chat')
                    raise events.StopPropagation

                if isinstance(input_chat, types.InputPeerChat):
                    # oops, the group hasn't been migrated to a supergroup. a migration is needed
                    await event.respond('\n\n'.join(i18n.get_all_l10n_string('group_upgrade_needed_prompt')))
                    logger.warning(f'Refused {describe_user()} to use {command} '
                                   f'because a group migration to supergroup is needed')
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
                        logger.warning(f'Refused Refused {describe_user()} to use {command} '
                                       f'because they is not a participant')
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
                        f'Refused {describe_user()} to use {command}')
                    raise events.StopPropagation

                await execute()
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
            try:
                if isinstance(e, FloodError):
                    # blocking other commands to be executed and messages to be sent
                    async with await flood_rwlock.gen_wlock():
                        if hasattr(e, 'seconds') and e.seconds is not None:
                            await asyncio.sleep(e.seconds + 1)
                        await respond_or_answer(event, 'ERROR: ' + i18n[lang]['flood_wait_prompt'])
                        await env.bot(e.request)  # resend
                # usually occurred because the user hits the same button during auto flood wait
                elif isinstance(e, MessageNotModifiedError):
                    await respond_or_answer(event, 'ERROR: ' + i18n[lang]['edit_conflict_prompt'])
                else:
                    await respond_or_answer(event, 'ERROR: ' + i18n[lang]['uncaught_internal_error'])
            except (FloodError, MessageNotModifiedError):
                pass  # we can do nothing but be a pessimism to drop it
            except Exception as e:
                logger.error('Uncaught error occurred when dealing with an uncaught error', exc_info=e)
            finally:
                raise events.StopPropagation

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


def get_commands_list(lang: Optional[str] = None, manager: bool = False) -> list[types.BotCommand]:
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
                           commands: list[types.BotCommand]):
    await env.bot(
        SetBotCommandsRequest(scope=scope, lang_code=lang_code, commands=commands)
    )
