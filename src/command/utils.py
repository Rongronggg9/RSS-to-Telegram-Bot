#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
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
from typing import Union, Optional, AnyStr, Any
from collections.abc import Callable

import asyncio
import re
from contextlib import suppress
from functools import partial, wraps
from cachetools import TTLCache
from telethon import events, hints
from telethon.utils import get_peer_id, resolve_id
from telethon.tl import types
from telethon.tl.patched import Message, MessageService
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import (
    FloodError, MessageNotModifiedError, UserNotParticipantError, QueryIdInvalidError, EntitiesTooLongError,
    MessageTooLongError, BadRequestError, ChatIdInvalidError
)

from .. import env, log, db, locks, errors_collection
from ..i18n import i18n
from . import inner
from .types import *
from ..errors_collection import UserBlockedErrors
from ..compat import cached_async

logger = log.getLogger('RSStT.command')

splitByWhitespace = re.compile(r'\s+').split
stripInlineHeader = partial(re.compile(r'^@\w{4,}\s+').sub, '')


# ANONYMOUS_ADMIN = 1087968824  # no need for MTProto, user_id will be `None` for anonymous admins

def parse_command(
        command: str,
        max_split: int = 0,
        strip_target_chat: bool = True,
        strip_inline_header: bool = False,
) -> list[AnyStr]:
    if strip_inline_header:
        command = stripInlineHeader(command)
    command = command.strip()
    if strip_target_chat:
        temp = splitByWhitespace(command, maxsplit=2)
        if len(temp) >= 2 and temp[1].startswith(('@', '-100')):
            del temp[1]
        command = ' '.join(temp)
    return splitByWhitespace(command, maxsplit=max_split)


async def parse_command_get_sub_or_user_and_param(
        command: str,
        user_id: int,
        max_split: int = 0,
        allow_setting_user_default: bool = False,
) -> tuple[Optional[db.Sub], Optional[str]]:
    args = parse_command(command, max_split=max_split, strip_inline_header=True)
    sub_or_user = param = None
    if len(args) >= 2 and args[1] == 'default' and allow_setting_user_default:
        sub_or_user = await db.User.get_or_none(id=user_id)
    if len(args) >= 2 and args[1].isdecimal() and int(args[1]) >= 1:
        sub_id = int(args[1])
        sub_or_user = await db.Sub.get_or_none(id=sub_id, user_id=user_id)
    if len(args) > 2:
        param = args[2]
    return sub_or_user, param


def parse_callback_data_with_page(callback_data: bytes) -> tuple[str, int]:
    """
    callback data = command={params}[|{page}]

    :param callback_data: callback data
    :return: params, page
    """
    callback_data = callback_data.decode().strip()
    callback_data = callback_data.rsplit('%', 1)[0]
    params_and_page = callback_data.split('|')
    params = params_and_page[0].split('=')[-1]
    page = int(params_and_page[1]) if len(params_and_page) > 1 else 1
    return params, page


def parse_customization_callback_data(
        callback_data: bytes,
) -> tuple[
    Optional[int],
    Optional[str],
    Optional[Union[int, str]],
    int,
]:
    """
    callback data = command[={id}[,{action}[,{param}]]][|{page_number}] or command[={action}[,{param}]]

    :param callback_data: callback data
    :return: id, action, param
    """
    callback_data = callback_data.decode().strip()
    callback_data = callback_data.rsplit('%', 1)[0]
    args = callback_data.split('|')
    page = int(args[1]) if len(args) > 1 else 1
    args = args[0].split('=', 1)
    if len(args) == 1:
        return None, None, None, page
    args = args[-1].split(',', 2)

    _id: Optional[int] = None
    if args[0].lstrip('-').isdecimal():
        _id = int(args[0])
        args = args[1:]
    elif len(args) >= 3:
        args = args[1:]
    action: Optional[str] = args[0] if len(args) >= 1 else None
    param: Optional[Union[int, str]] = args[1] if len(args) >= 2 else None
    if param and param.lstrip('-').isdecimal():
        param = int(param)

    return _id, action, param, page


async def respond_or_answer(
        event: TypeEventCollectionAll,
        msg: str,
        alert: bool = True,
        cache_time: int = 120,
        *args,
        **kwargs,
):
    """
    Respond to a ``NewMessage`` event, or answer to an unanswered ``CallbackQuery`` event.

    :param event: a telethon Event object, NewMessage or CallbackQuery
    :param msg: the message to send
    :param alert: alert or not? (only for CallbackQuery)
    :param cache_time: cache the answer for how many seconds on the server side? (only for CallbackQuery)
    :param args: additional params (only for NewMessage)
    :param kwargs: additional params (only for NewMessage)
    """
    with suppress(*UserBlockedErrors):  # silently ignore
        # noinspection PyProtectedMember
        if isinstance(event, TypeEventCb) and not event._answered:
            # answering callback query is of a tolerant rate limit, no lock needed
            with suppress(QueryIdInvalidError):  # callback query expired, respond instead
                await event.answer(msg, alert=alert, cache_time=cache_time)
                return  # return if answering successfully
        elif isinstance(event, TypeEventInline):
            # noinspection PyProtectedMember
            if event._answered:
                return
            await event.answer(switch_pm=msg, switch_pm_param=str(event.id), private=True)
            return  # return if answering successfully

        async with locks.ContextWithTimeout(locks.user_flood_lock(event.chat_id), timeout=30):
            pass  # wait for flood wait

        await event.respond(
            msg,
            *args,
            **kwargs,
            reply_to=(
                event.message
                if isinstance(event, TypeEventMsg) and event.is_group
                else None
            ),
        )


async def is_self_admin(chat_id: hints.EntityLike) -> Optional[bool]:
    """
    Check if the bot itself is an admin in the chat.

    :param chat_id: chat id
    :return: True if the bot is an admin, False if not, None if self not in the chat
    """
    ret, _ = await is_user_admin(chat_id, env.bot_id)
    return ret


@cached_async(cache=TTLCache(maxsize=64, ttl=20))
async def is_user_admin(chat_id: hints.EntityLike, user_id: hints.EntityLike) -> tuple[Optional[bool], Optional[str]]:
    """
    Check if the user is an admin in the chat.

    :param chat_id: chat id
    :param user_id: user id
    :return: True if user is admin, False if not, None if self / the user not in the chat
    """
    try:
        input_chat = await env.bot.get_input_entity(chat_id)
        input_user = await env.bot.get_input_entity(user_id)
        # noinspection PyTypeChecker
        participant: types.channels.ChannelParticipant = await env.bot(
            GetParticipantRequest(input_chat, input_user))
        is_admin = isinstance(
            participant.participant,
            (types.ChannelParticipantAdmin, types.ChannelParticipantCreator),
        )
        participant_type = type(participant.participant).__name__
        return is_admin, participant_type
    except (UserNotParticipantError, ValueError):
        return None, None


async def leave_chat(chat_id: hints.EntityLike) -> bool:
    if isinstance(chat_id, int) and chat_id > 0:
        return False  # a bot cannot delete the dialog with a user
    try:
        ret = await env.bot.delete_dialog(chat_id)
        if ret:
            logger.warning(f"Left chat {chat_id}")
        return bool(ret)
    except (BadRequestError, ValueError):
        return False


async def unsub_all_and_leave_chat(user_id: hints.EntityLike):
    await asyncio.gather(
        inner.sub.unsub_all(user_id),
        leave_chat(user_id),
    )


def command_gatekeeper(
        func: Optional[Callable] = None,
        *,
        only_manager: bool = False,
        only_in_private_chat: bool = None,
        allow_in_others_private_chat: bool = False,
        allow_in_old_fashioned_groups: bool = False,
        ignore_tg_lang: bool = False,
        timeout: Optional[int] = 120,
        quiet: bool = False,
):
    if func is None:
        return partial(
            command_gatekeeper,
            only_manager=only_manager,
            only_in_private_chat=only_in_private_chat,
            allow_in_old_fashioned_groups=allow_in_old_fashioned_groups,
            ignore_tg_lang=ignore_tg_lang,
            timeout=timeout,
            quiet=quiet,
        )

    # assume that managing commands are only allowed in private chat, unless specified
    only_in_private_chat = only_manager if only_in_private_chat is None else only_in_private_chat
    # block contradicting settings
    assert not (only_in_private_chat and allow_in_old_fashioned_groups)

    @wraps(func)
    async def wrapper(
            # Note: `events.ChatAction.Event` only have ChatGetter, do not have SenderGetter like others
            event: TypeEventCollectionAll,
            *args,
            **kwargs,
    ):
        # placeholders
        lang = None
        command: Optional[str] = None
        sender: Optional[Union[types.User, types.Channel]] = None
        sender_fullname: Optional[str] = None
        chat_title: Optional[str] = None
        participant_type: Optional[str] = None
        sender_id: Optional[int] = None

        chat_id = event.chat_id
        flood_lock = locks.user_flood_lock(chat_id)
        pending_callbacks = locks.user_pending_callbacks(chat_id)
        is_callback = isinstance(event, TypeEventCb)
        is_inline = isinstance(event, TypeEventInline)
        is_chat_action = isinstance(event, TypeEventChatAction)

        def describe_user():
            chat_info = None
            if (chat_title or chat_id) and chat_id != sender_id:
                chat_info = f'{chat_title or chat_id}' + (
                    f' ({chat_id})'
                    if chat_title and chat_id
                    else ''
                )
            return ''.join((
                f'{sender_fullname} ({sender_id}',
                f', {participant_type}' if participant_type and chat_info else '',
                f', {type(event.query.peer_type).__name__}' if is_inline else '',
                ')',
                f' in {chat_info}' if chat_info else '',
            ))

        async def user_and_chat_permission_check():
            sender_state = chat_state = 0
            if sender_id:
                sender_in_db, _ = await db.User.get_or_create(id=sender_id, defaults={'lang': 'null'})
                sender_state = sender_in_db.state
            if chat_id == sender_id:
                chat_state = sender_state
            elif chat_id:
                chat_in_db, _ = await db.User.get_or_create(id=chat_id, defaults={'lang': 'null'})
                chat_state = chat_in_db.state

            permission_denied_not_manager = only_manager and sender_id not in env.MANAGER
            permission_denied_no_permission = (
                    sender_id not in env.MANAGER
                    and
                    (
                            (
                                    not env.MULTIUSER
                                    and
                                    max(sender_state, chat_state) < 1
                            )
                            or
                            min(sender_state, chat_state) < 0
                    )
            )
            if permission_denied_not_manager or permission_denied_no_permission:
                if is_chat_action:  # chat action, bypassing
                    raise events.StopPropagation
                await respond_or_answer(
                    event,
                    i18n[lang]['permission_denied_not_bot_manager']
                    if permission_denied_not_manager
                    else i18n[lang]['permission_denied_no_permission'],
                )
                logger.warning(
                    f'Refused {describe_user()} to use {command} because ' + (
                        'the command can only be used by the bot manager'
                        if permission_denied_not_manager else
                        'the user has no permission to use the command'
                    )
                )
                raise events.StopPropagation

        async def execute():
            callback_msg_id = event.message_id if is_callback else None
            log_level = log.DEBUG if quiet else log.INFO
            # skip if already executing a callback for this msg
            if callback_msg_id and callback_msg_id in pending_callbacks:
                logger.log(
                    log_level,
                    f'Skipped {describe_user()} to use {command}: already executing a callback for this msg',
                )
                await respond_or_answer(event, i18n[lang]['callback_already_running_prompt'], cache_time=0)
                raise events.StopPropagation

            if callback_msg_id:
                pending_callbacks.add(callback_msg_id)
            try:
                logger.log(log_level, f'Allow {describe_user()} to use {command}')
                async with locks.ContextWithTimeout(flood_lock, timeout=timeout):
                    pass  # wait for flood wait
                await asyncio.wait_for(
                    func(event, *args, lang=lang, chat_id=chat_id, **kwargs),  # execute the command!
                    timeout=timeout,
                )
            except locks.ContextTimeoutError:
                logger.error(f'Cancel {command} for {describe_user()} due to flood wait timeout ({timeout}s)')
                # await respond_or_answer(event, 'ERROR: ' + i18n[lang]['flood_wait_prompt'])
            except asyncio.TimeoutError as _e:
                logger.error(f'Cancel {command} for {describe_user()} due to timeout ({timeout}s)', exc_info=_e)
                await respond_or_answer(event, 'ERROR: ' + i18n[lang]['operation_timeout_error'])
            finally:
                if callback_msg_id:
                    with suppress(KeyError):
                        pending_callbacks.remove(callback_msg_id)

        try:
            if command := getattr(event, 'raw_text', None):
                pass
            elif is_callback:
                command = f'(Callback){event.data.decode()}'
            elif is_inline:
                command = f'(Inline){event.text}'
            elif is_chat_action:
                command = f'(ChatAction, {event.action_message and event.action_message.action.__class__.__name__})'
            else:
                command = '(no command, other message)'
            command_header = parse_command(command, max_split=1, strip_target_chat=False)[0]
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

            if isinstance(sender, types.Channel):
                sender_fullname = sender.title
            elif sender is not None:
                sender_fullname = sender.first_name + (
                    f' {sender.last_name}'
                    if sender.last_name
                    else ''
                )
            elif is_chat_action:
                sender_fullname = '__chat_action__'
            else:
                sender_fullname = '__anonymous_admin__'

            # get the user's lang
            lang_in_db = await db.User.get_or_none(id=chat_id).values_list('lang', flat=True)
            lang = lang_in_db if lang_in_db != 'null' else None
            if not lang and not ignore_tg_lang:
                lang = sender.lang_code if hasattr(sender, 'lang_code') else None
                if not lang and sender_id != chat_id:
                    lang = db.User.get_or_none(id=sender_id).values_list('lang', flat=True)

            # inline refusing check
            if is_inline:
                query: types.UpdateBotInlineQuery = event.query
                if (
                        (
                                not allow_in_others_private_chat
                                and
                                isinstance(query.peer_type, types.InlineQueryPeerTypePM)
                        )
                        or
                        (
                                only_in_private_chat
                                and
                                not isinstance(
                                    query.peer_type,
                                    (types.InlineQueryPeerTypeSameBotPM, types.InlineQueryPeerTypePM)
                                )
                        )
                        or
                        (
                                not allow_in_old_fashioned_groups
                                and
                                isinstance(query.peer_type, types.InlineQueryPeerTypeChat)
                        )
                ):
                    # Redirect to the private chat with the bot
                    await respond_or_answer(event, i18n[lang]['permission_denied_switch_pm'])
                    logger.warning(f'Redirected {describe_user()} (using {command}) to the private chat with the bot')
                    raise events.StopPropagation

            await user_and_chat_permission_check()

            # operating channel/group in private chat ("remote" command), firstly get base info
            pattern_match: re.Match = event.pattern_match if not is_chat_action else None
            target_chat_id = (pattern_match and pattern_match.groupdict().get('target')) or ''
            target_chat_id: Union[str, int, None] = (
                target_chat_id.decode()
                if isinstance(target_chat_id, bytes)
                else target_chat_id
            )
            if target_chat_id.startswith(('-100', '+')) and target_chat_id.lstrip('+-').isdecimal():
                target_chat_id = int(target_chat_id)
            elif target_chat_id.isdecimal():
                target_chat_id = -(1000000000000 + int(target_chat_id))
            elif target_chat_id.lstrip('-').isdecimal():
                # target_chat_id = int(target_chat_id)
                target_chat_id = None  # disallow old-fashioned group
            elif target_chat_id.startswith('@'):
                target_chat_id = target_chat_id[1:]
            else:
                target_chat_id = None

            if (
                    # if a target chat is specified ("remote" command), jump to admin check
                    not target_chat_id
                    and
                    (
                            is_inline  # allow inline
                            or
                            event.is_private  # allow commands in private chats
                            or
                            # we are not in a private chat.
                            (
                                    # if receiving a callback, we must verify that the sender is an admin.
                                    # jump to admin check
                                    not is_callback
                                    and
                                    # if the command can only be used in a private chat, jump below
                                    not only_in_private_chat
                                    and
                                    # finally, allow commands in channels
                                    # a supergroup is also a channel, but we only expect a "real" channel here
                                    event.is_channel and not event.is_group
                            )
                    )
            ):
                await execute()
                raise events.StopPropagation

            # admin check
            if (
                    # operating channel/group in private chats ("remote" command)
                    target_chat_id
                    or
                    # commands in groups
                    event.is_group
                    or
                    # commands in channels
                    event.is_channel
            ):
                if isinstance(sender, types.Channel):
                    raise events.StopPropagation  # channel messages are none of my business

                if only_in_private_chat or (target_chat_id and not event.is_private):
                    await respond_or_answer(event, i18n[lang]['permission_denied_not_in_private_chat'])
                    logger.warning(
                        f'Refused {describe_user()} to use {command} '
                        'because the command can only be used in a private chat'
                    )
                    raise events.StopPropagation

                if target_chat_id:
                    try:
                        input_chat = await env.bot.get_input_entity(target_chat_id)
                        chat = await env.bot.get_entity(input_chat)
                        chat_id = get_peer_id(chat, add_mark=True)
                        if not isinstance(chat, types.Channel):
                            # only allow operating channel/group in private chats
                            if sender_id not in env.MANAGER or not env.MANAGER_PRIVILEGED:
                                raise TypeError
                        await user_and_chat_permission_check()
                    except (TypeError, ValueError, ChatIdInvalidError) as e:
                        if isinstance(e, TypeError):
                            logger.warning(
                                f'Refused {describe_user()} to use {command} '
                                'because only a privileged bot manager can manipulate ordinary users'
                            )
                        else:
                            logger.warning(
                                f'Refused {describe_user()} to use {command} because the target chat was not found'
                            )
                        await respond_or_answer(event, i18n[lang]['channel_or_group_not_found'])
                        raise events.StopPropagation
                else:
                    # supergroup is a special form of channel
                    input_chat: Optional[
                        Union[
                            types.InputChannel,
                            types.InputPeerChannel,
                            types.InputPeerChat
                        ]
                    ] = await event.get_input_chat()
                    chat: Optional[Union[types.Chat, types.Channel]] = await event.get_chat()

                chat_title = chat and (
                    chat.first_name + (
                        f' {chat.last_name}'
                        if chat.last_name
                        else ''
                    )
                    if isinstance(chat, types.User)
                    else chat.title
                )

                if isinstance(input_chat, types.InputPeerChat):
                    if allow_in_old_fashioned_groups:
                        # old-fashioned groups lacks of permission management, no need to check
                        await execute()
                        raise events.StopPropagation
                    # oops, the group hasn't been migrated to a supergroup. a migration is needed
                    guide_msg, guide_buttons = get_group_migration_help_msg(lang)
                    await event.respond(guide_msg, buttons=guide_buttons)
                    logger.warning(
                        f'Refused {describe_user()} to use {command} because a group migration to supergroup is needed'
                    )
                    raise events.StopPropagation

                if sender_id in env.MANAGER and env.MANAGER_PRIVILEGED:
                    participant_type = 'PrivilegedBotManager'
                    await execute()
                    raise events.StopPropagation

                # check if self is in the group/chanel and if is an admin
                self_is_admin = True
                # bypass check if the event is not a callback query or a remote operation, set to True for convenience
                if is_callback or target_chat_id:
                    self_is_admin = await is_self_admin(chat_id)
                    if self_is_admin is None:  # I am not a participant of the group/channel, none of my business!
                        await respond_or_answer(event, i18n[lang]['permission_denied_bot_not_member'], cache_time=15)
                        raise events.StopPropagation

                # user permission check
                if is_chat_action:
                    is_admin = True
                    participant_type = 'ChatAction, bypassing admin check'
                elif sender_id is not None:  # a "real" user triggering the command
                    is_admin, participant_type = await is_user_admin(chat_id, sender_id)
                    if is_admin is None:
                        await respond_or_answer(
                            event,
                            i18n[lang]['permission_denied_not_member']
                            if (self_is_admin or (chat and chat.broadcast))
                            else (
                                    (
                                        f"{i18n[lang]['permission_denied_not_member']}\n\n"
                                        if not is_callback
                                        else ''
                                    )
                                    + i18n[lang]['promote_to_admin_prompt']
                            ),
                            cache_time=15,
                        )
                        logger.warning(
                            f'Refused Refused {describe_user()} to use {command} because they is not a participant'
                        )
                        raise events.StopPropagation
                else:  # an anonymous admin
                    is_admin = True
                    participant_type = 'AnonymousAdmin'

                if not is_admin:
                    await respond_or_answer(event, i18n[lang]['permission_denied_not_chat_admin'], cache_time=15)
                    logger.warning(f'Refused {describe_user()} to use {command}')
                    raise events.StopPropagation

                await execute()
                raise events.StopPropagation

        except events.StopPropagation as e:
            raise e
        except Exception as e:
            logger.error(
                ''.join((
                    f'Uncaught error occurred when {sender_fullname} ({sender_id}',
                    f', {participant_type}' if participant_type else '',
                    f') attempting to use {command}',
                    f' in {chat_title} ({chat_id})' if chat_id != sender_id else '',
                )),
                exc_info=e,
            )
            try:
                if isinstance(e, (FloodError, locks.ContextTimeoutError)):
                    # blocking other commands to be executed and messages to be sent
                    if (e_seconds := getattr(e, 'seconds', None)) is not None:
                        await locks.user_flood_wait_background(chat_id, e_seconds)  # acquire a flood wait
                    await respond_or_answer(event, 'ERROR: ' + i18n[lang]['flood_wait_prompt'])
                    await env.bot(e.request)  # resend
                # usually occurred because the user hits the same button during auto flood wait
                elif isinstance(e, MessageNotModifiedError):
                    await respond_or_answer(event, 'ERROR: ' + i18n[lang]['edit_conflict_prompt'])
                elif isinstance(e, (EntitiesTooLongError, MessageTooLongError)):
                    await respond_or_answer(event, 'ERROR: ' + i18n[lang]['message_too_long_prompt'])
                elif isinstance(e, errors_collection.UserBlockedErrors):
                    await unsub_all_and_leave_chat(chat_id)
                elif isinstance(e, BadRequestError) and e.message == 'TOPIC_CLOSED':
                    await unsub_all_and_leave_chat(chat_id)
                else:
                    await respond_or_answer(event, 'ERROR: ' + i18n[lang]['uncaught_internal_error'])
            except (FloodError, MessageNotModifiedError, locks.ContextTimeoutError):
                pass  # we can do nothing but be a pessimism to drop it
            except Exception as e:
                logger.error('Uncaught error occurred when dealing with another uncaught error', exc_info=e)
            finally:
                raise events.StopPropagation

    return wrapper


def escape_html(raw: Any) -> str:
    raw = str(raw)
    return raw.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class NewFileMessage(events.NewMessage):
    def __init__(
            self,
            chats=None,
            *,
            blacklist_chats=False,
            func=None,
            incoming=None,
            outgoing=None,
            from_users=None,
            forwards=None,
            pattern=None,
            filename_pattern: str = None,
    ):
        self.filename_pattern = re.compile(filename_pattern).match
        super().__init__(
            chats,
            blacklist_chats=blacklist_chats,
            func=func,
            incoming=incoming,
            outgoing=outgoing,
            from_users=from_users,
            forwards=forwards,
            pattern=pattern,
        )

    def filter(self, event: TypeEventMsgHint):
        document: types.Document = event.message.document
        if not document:
            return
        if self.filename_pattern:
            filename = next(
                (
                    attr.file_name
                    for attr in document.attributes
                    if isinstance(attr, types.DocumentAttributeFilename)
                ),
                None
            )
            if not self.filename_pattern(filename or ''):
                return
        return super().filter(event)


class ReplyMessage(events.NewMessage):
    def __init__(
            self,
            chats=None,
            *,
            blacklist_chats=False,
            incoming=None,
            outgoing=None,
            from_users=None,
            forwards=None,
            pattern=None,
            reply_to_peer_id: int = None,
    ):
        self.reply_to_peer_id = reply_to_peer_id or env.bot_id
        super().__init__(
            chats,
            blacklist_chats=blacklist_chats,
            func=self.__reply_verify,
            incoming=incoming,
            outgoing=outgoing,
            from_users=from_users,
            forwards=forwards,
            pattern=pattern,
        )

    async def __reply_verify(self, event: TypeEventMsgHint):
        if event.is_reply:
            reply_to_msg: Optional[Message] = await event.get_reply_message()
            if reply_to_msg is not None and self.reply_to_peer_id == reply_to_msg.sender_id:
                return True
        return False


class PrivateMessage(events.NewMessage):
    def __init__(
            self,
            chats=None,
            *,
            blacklist_chats=False,
            incoming=None,
            outgoing=None,
            from_users=None,
            forwards=None,
            pattern=None,
    ):
        super().__init__(
            chats,
            blacklist_chats=blacklist_chats,
            func=self.__in_private_chat,
            incoming=incoming,
            outgoing=outgoing,
            from_users=from_users,
            forwards=forwards,
            pattern=pattern,
        )

    @staticmethod
    def __in_private_chat(event: TypeEventMsgHint):
        return event.is_private


class AddedToGroupAction(events.ChatAction):
    """Chat actions that are triggered when the bot has been added to a group."""

    def __init__(self, chats=None, *, blacklist_chats=False):
        super().__init__(chats, blacklist_chats=blacklist_chats, func=self.__added_to_group)

    @staticmethod
    def __added_to_group(event: TypeEventChatAction):
        if not event.is_group:
            return False
        if event.created:
            return True  # group created or migrated
        if (
                event.user_added
                or
                (
                        event.action_message
                        and
                        isinstance(event.action_message.action, types.MessageActionChatAddUser)
                )
        ):
            return env.bot_id in event.user_ids  # added to a group
        return False


class GroupMigratedAction(events.ChatAction):
    """
    Chat actions that are triggered when a group has been migrated to a supergroup.

    After a group migration, below updates will be sent:
    UpdateChannel(*),
    UpdateNewChannelMessage(message=MessageService(action=MessageActionChatMigrateTo(*)))
    UpdateNewChannelMessage(message=MessageService(action=MessageActionChannelMigrateFrom(*))),

    This class only listens to the latest one.
    """

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if (
                isinstance(
                    update,
                    (types.UpdateNewMessage, types.UpdateNewChannelMessage)
                )
                and
                isinstance(update.message, types.MessageService)
        ):
            msg = update.message
            action = update.message.action
            if isinstance(action, types.MessageActionChannelMigrateFrom):
                return cls.Event(msg)


async def set_bot_commands(
        scope: Union[
            types.BotCommandScopeDefault,
            types.BotCommandScopePeer,
            types.BotCommandScopePeerAdmins,
            types.BotCommandScopeUsers,
            types.BotCommandScopeChats,
            types.BotCommandScopePeerUser,
            types.BotCommandScopeChatAdmins
        ],
        lang_code: str,
        commands: list[types.BotCommand],
):
    await env.bot(
        SetBotCommandsRequest(scope=scope, lang_code=lang_code, commands=commands)
    )


async def send_success_and_failure_msg(
        message: TypeEventCollectionMsgOrCb,
        success_msg: str,
        failure_msg: str,
        success_count: int,
        failure_count: int,
        *_,
        lang: Optional[str] = None,
        edit: bool = False,
        **__,
) -> TypeEventCollectionMsgOrCb:
    success_msg_raw = success_msg
    failure_msg_raw = failure_msg
    success_msg_short = (
        '\n'.join((
            success_msg.split('\n', 1)[0],
            i18n[lang]['n_subscriptions_in_total'] % success_count,
        ))
    ) if success_count else ''
    failure_msg_short = (
        '\n'.join((
            failure_msg.split('\n', 1)[0],
            i18n[lang]['n_subscriptions_in_total'] % failure_count,
        ))
    ) if failure_count else ''

    for success_msg, failure_msg, reraise_on_error in (
            (success_msg_raw, failure_msg_raw, False),
            (success_msg_short, failure_msg_raw, False),
            (success_msg_raw, failure_msg_short, False),
            (success_msg_short, failure_msg_short, True),
    ):
        msg_html = '\n\n'.join(
            filter(None, (
                success_msg,
                failure_msg,
            ))
        )

        try:
            msg = await (message.edit(msg_html, parse_mode='html') if edit
                         else message.respond(msg_html, parse_mode='html'))
            return msg if msg is not None else message
        except (EntitiesTooLongError, MessageTooLongError):
            if reraise_on_error:
                raise


def get_group_migration_help_msg(
        lang: Optional[str] = None,
) -> tuple[str, tuple[tuple[types.KeyboardButtonCallback, ...], ...]]:
    msg = i18n[lang]['group_upgrade_needed_prompt']
    buttons, _ = inner.utils.get_lang_buttons(callback='get_group_migration_help', current_lang=lang)
    return msg, buttons


def get_callback_tail(
        event: TypeEventCollectionMsgOrCb,
        chat_id: int,
) -> str:
    if not event.is_private or event.chat.id == chat_id:
        return ''
    ori_chat_id, peer_type = resolve_id(chat_id)
    if peer_type is types.PeerChat:
        raise ValueError('Old-fashioned group chat is not supported')
    return f'%{ori_chat_id}' if ori_chat_id < 0 else f'%+{ori_chat_id}'


async def check_sub_limit(event: TypeEventMsgHint, user_id: int, lang: Optional[str] = None):
    limit_reached, curr_count, limit, _ = await inner.utils.check_sub_limit(user_id)
    if limit_reached:
        logger.warning(f'Refused user {user_id} to add new subscriptions due to limit reached ({curr_count}/{limit})')
        msg = i18n[lang]['sub_limit_reached_prompt'] % (curr_count, limit)
        if db.EffectiveOptions.sub_limit_reached_message:
            msg += f'\n\n{db.EffectiveOptions.sub_limit_reached_message}'
        await event.respond(msg)
        raise events.StopPropagation
