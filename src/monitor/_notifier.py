from __future__ import annotations
from typing import Iterable, MutableMapping, Union, Final

import asyncio
from collections import defaultdict, Counter
from telethon.errors import BadRequestError
from traceback import format_exc

from ._common import logger
from .. import db, env, web
from ..command import inner
from ..command.utils import unsub_all_and_leave_chat, escape_html
from ..errors_collection import EntityNotFoundError, UserBlockedErrors
from ..helpers.singleton import Singleton
from ..i18n import i18n
from ..parsing.post import get_post_from_entry, Post


class Notifier(Singleton):
    def __init__(self):
        # it may cause memory leak, but they are too small that leaking thousands of that is still not a big deal!
        self._user_unsub_all_lock_bucket: Final[dict[int, asyncio.Lock]] = defaultdict(asyncio.Lock)
        self._user_blocked_counter: Final[Counter] = Counter()

    async def notify_all(self, feed: db.Feed, subs: Iterable[db.Sub], entry: MutableMapping) -> None:
        link = entry.get('link')
        try:
            post = await get_post_from_entry(entry, feed.title, feed.link)
        except Exception as e:
            logger.error(f'Failed to parse the post {link} (feed: {feed.link}) from entry:', exc_info=e)
            try:
                error_message = Post(f'Something went wrong while parsing the post {link} '
                                     f'(feed: {feed.link}). '
                                     f'Please check:<br><br>' +
                                     format_exc().replace('\n', '<br>'),
                                     feed_title=feed.title, link=link)
                await error_message.send_formatted_post(env.ERROR_LOGGING_CHAT, send_mode=2)
            except Exception as e:
                logger.error(f'Failed to send parsing error message for {link} (feed: {feed.link}):', exc_info=e)
                await env.bot.send_message(env.ERROR_LOGGING_CHAT,
                                           'A parsing error message cannot be sent, please check the logs.')
            return
        res = await asyncio.gather(
            *(asyncio.wait_for(self._send(sub, post), 8.5 * 60) for sub in subs),
            return_exceptions=True
        )
        for sub, exc in zip(subs, res):
            if not isinstance(exc, Exception):
                continue
            if not isinstance(exc, asyncio.TimeoutError):  # should not happen, but just in case
                raise exc
            logger.error(f'Failed to send {post.link} (feed: {post.feed_link}, user: {sub.user_id}) due to timeout')

    async def deactivate_feed_and_notify_all(
            self,
            feed: db.Feed,
            subs: Iterable[db.Sub],
            reason: Union[web.WebError, str] = None
    ) -> None:
        await inner.utils.deactivate_feed(feed)

        if not subs:  # nobody has subbed it or no active sub exists
            return

        langs: tuple[str, ...] = await asyncio.gather(
            *(sub.user.get_or_none().values_list('lang', flat=True) for sub in subs)
        )

        await asyncio.gather(
            *(
                self._send(
                    sub=sub,
                    post=(
                            f'<a href="{feed.link}">{escape_html(sub.title or feed.title)}</a>\n'
                            + i18n[lang]['feed_deactivated_warn']
                            + (
                                f'\n{reason.i18n_message(lang) if isinstance(reason, web.WebError) else reason}'
                                if reason else ''
                            )
                    )
                )
                for sub, lang in (zip(subs, langs))
            )
        )

    async def _send(self, sub: db.Sub, post: Union[str, Post]) -> None:
        user_id = sub.user_id
        try:
            try:
                await env.bot.get_input_entity(user_id)  # verify that the input entity can be gotten first
            except ValueError:  # cannot get the input entity, the user may have banned the bot
                return await self._locked_unsub_all_and_leave_chat(user_id=user_id,
                                                                   err_msg=type(EntityNotFoundError).__name__)
            try:
                if isinstance(post, str):
                    await env.bot.send_message(user_id, post, parse_mode='html', silent=not sub.notify)
                    return
                await post.send_formatted_post_according_to_sub(sub)
                if self._user_blocked_counter[user_id]:  # reset the counter if success
                    del self._user_blocked_counter[user_id]
            except UserBlockedErrors as e:
                return await self._locked_unsub_all_and_leave_chat(user_id=user_id, err_msg=type(e).__name__)
            except BadRequestError as e:
                if e.message == 'TOPIC_CLOSED':
                    return await self._locked_unsub_all_and_leave_chat(user_id=user_id, err_msg=e.message)
        except Exception as e:
            logger.error(f'Failed to send {post.link} (feed: {post.feed_link}, user: {sub.user_id}):', exc_info=e)
            try:
                error_message = Post('Something went wrong while sending this post '
                                     f'(feed: {post.feed_link}, user: {sub.user_id}). '
                                     'Please check:<br><br>' +
                                     format_exc().replace('\n', '<br>'),
                                     title=post.title, feed_title=post.feed_title, link=post.link, author=post.author,
                                     feed_link=post.feed_link)
                await error_message.send_formatted_post(env.ERROR_LOGGING_CHAT, send_mode=2)
            except Exception as e:
                logger.error(f'Failed to send sending error message for {post.link} '
                             f'(feed: {post.feed_link}, user: {sub.user_id}):',
                             exc_info=e)
                await env.bot.send_message(env.ERROR_LOGGING_CHAT,
                                           'An sending error message cannot be sent, please check the logs.')

    async def _locked_unsub_all_and_leave_chat(self, user_id: int, err_msg: str) -> None:
        user_unsub_all_lock = self._user_unsub_all_lock_bucket[user_id]
        if user_unsub_all_lock.locked():
            return  # no need to unsub twice!
        async with user_unsub_all_lock:
            if self._user_blocked_counter[user_id] < 5:
                self._user_blocked_counter[user_id] += 1
                return  # skip once
            # fail for 5 times, consider been banned
            del self._user_blocked_counter[user_id]
            logger.error(f'User blocked ({err_msg}): {user_id}')
            await unsub_all_and_leave_chat(user_id)
