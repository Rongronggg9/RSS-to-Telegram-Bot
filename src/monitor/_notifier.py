from __future__ import annotations
from typing import Sequence, MutableMapping, Union, Final, ClassVar, Optional

import asyncio
from collections import defaultdict, Counter
from telethon.errors import BadRequestError
from traceback import format_exc

from ._common import logger, TIMEOUT
from ._stat import NotifierStat
from .. import db, env, web
from ..command import inner
from ..command.utils import unsub_all_and_leave_chat, escape_html
from ..compat import nullcontext
from ..errors_collection import EntityNotFoundError, UserBlockedErrors
from ..helpers.bg import bg
from ..helpers.pipeline import SameFuncPipelineContextManager
from ..helpers.timeout import BatchTimeout
from ..i18n import i18n
from ..parsing.post import get_post_from_entry, Post


class Notifier:
    _stat: ClassVar[NotifierStat] = NotifierStat()

    # it may cause memory leak, but they are too small that leaking thousands of that is still not a big deal!
    _user_unsub_all_lock_bucket: ClassVar[dict[int, asyncio.Lock]] = defaultdict(asyncio.Lock)
    _user_blocked_counter: ClassVar[Counter] = Counter()

    def __init__(
            self,
            feed: db.Feed,
            subs: Sequence[db.Sub],
            entries: Optional[Sequence[MutableMapping]] = None,
            reason: Optional[Union[web.WebError, str]] = None,
    ):
        if entries is not None and reason is not None:
            raise ValueError('entries and reason cannot be set at the same time')
        self._feed: Final[db.Feed] = feed
        self._subs: Final[set[db.Sub]] = set(subs)
        self._entries: Final[Optional[Sequence[MutableMapping]]] = entries
        self._reason: Final[Optional[Union[web.WebError, str]]] = reason

        self._entry_count: Final[int] = len(entries) if entries is not None else 0
        self._sub_count: Final[int] = len(subs)
        self._cached_posts: dict[int, Union[Post, None, False]] = {}
        self._posts_got_counter: Final[Counter] = Counter()

        self._get_post_lock: Union[dict[int, asyncio.Lock], dict[int, nullcontext]] = (
            defaultdict(asyncio.Lock)
            if self._sub_count > 1
            else defaultdict(nullcontext)
        )

    def _describe_subtask(self, sub: db.Sub, *_, **__) -> str:
        return f'{sub.id} (feed: {sub.feed_id}, user: {sub.user_id}): {self._feed.link}'

    def _on_subtask_notified(self, *_, **__):
        self._stat.notified()

    def _on_subtask_deactivated(self, *_, **__):
        self._stat.deactivated()

    def _on_subtask_canceled(self, err: BaseException, sub: db.Sub, post: Union[str, Post]):
        self._stat.cancelled()
        logger.error(
            f'Notifier subtask failed due to CancelledError: {self._describe_subtask(sub, post)}',
            exc_info=err,
        )

    def _on_subtask_unknown_error(self, err: BaseException, sub: db.Sub, post: Union[str, Post]):
        self._stat.unknown_error()
        logger.error(
            f'Notifier subtask failed due to an unknown error: {self._describe_subtask(sub, post)}',
            exc_info=err,
        )

    def _on_subtask_timeout(self, err: BaseException, sub: db.Sub, post: Union[str, Post]):
        self._stat.timeout()
        logger.error(
            f'Notifier subtask timed out after {TIMEOUT}s: {self._describe_subtask(sub, post)}',
            exc_info=err,
        )

    def _on_subtask_timeout_unknown_error(self, err: BaseException, sub: db.Sub, post: Union[str, Post]):
        self._stat.timeout_unknown_error()
        logger.error(
            f'Notifier subtask timed out after {TIMEOUT}s '
            f'and caused an unknown error: {self._describe_subtask(sub, post)}',
            exc_info=err,
        )

    @classmethod
    def on_periodic_task(cls):
        cls._stat.print_summary()

    async def _get_post(self, idx: int) -> Union[Post, None, False]:
        cached_posts = self._cached_posts
        posts_got_counter = self._posts_got_counter

        if (cached := cached_posts.get(idx)) is not None:
            got_count = posts_got_counter[idx] = posts_got_counter[idx] + 1
            if got_count >= self._sub_count and cached is not False:
                # Release references so that it can be garbage collected while some other posts are being notified.
                cached_posts[idx] = None
            return cached

        feed = self._feed
        entry = self._entries[idx]
        link = entry.get('link')
        try:
            post = await get_post_from_entry(entry, feed.title, feed.link)
        except Exception as e:
            logger.error(f'Failed to parse the post {link} (feed: {feed.link}) from entry:', exc_info=e)
            try:
                error_message = Post(
                    f'Something went wrong while parsing the post {link} (feed: {feed.link}). '
                    f'Please check:<br><br>' + format_exc().replace('\n', '<br>'),
                    feed_title=feed.title,
                    link=link,
                )
                await error_message.send_formatted_post(env.ERROR_LOGGING_CHAT, send_mode=2)
            except Exception as e:
                logger.error(f'Failed to send parsing error message for {link} (feed: {feed.link}):', exc_info=e)
                await env.bot.send_message(
                    env.ERROR_LOGGING_CHAT,
                    'A parsing error message cannot be sent, please check the logs.',
                )
            cached_posts[idx] = False
            return False
        else:
            if self._sub_count > 1:
                # Only cache the post when it may be used by other subs.
                cached_posts[idx] = post
            assert posts_got_counter[idx] == 0
            posts_got_counter[idx] = 1
            return post

    async def _notify_sub_with_entry_idx(self, idx: int, sub: db.Sub) -> None:
        async with self._get_post_lock[idx]:
            post = await self._get_post(idx)
        if post:
            await self._do_send(sub, post)

    async def _notify_sub(self, sub: db.Sub) -> None:
        async with SameFuncPipelineContextManager(
                func=self._notify_sub_with_entry_idx,
        ) as _notify_sub_with_entry_idx:
            for idx in range(self._entry_count):
                _notify_sub_with_entry_idx(idx, sub)
        # Release references so that it can be garbage collected while some other subs are being notified.
        self._subs.discard(sub)

    async def _notify_all(self) -> None:
        subs = self._subs

        if not subs:
            return

        _notify_sub: BatchTimeout[[db.Sub, Post], None]
        async with BatchTimeout[[db.Sub, Post], None](
                func=self._notify_sub,
                timeout=TIMEOUT,
                loop=env.loop,
                on_success=self._on_subtask_notified,
                on_canceled=self._on_subtask_canceled,
                on_error=self._on_subtask_unknown_error,
                on_timeout=self._on_subtask_timeout,
                on_timeout_error=self._on_subtask_timeout_unknown_error,
        ) as _notify_sub:
            for sub in subs:
                _notify_sub(sub)
            del sub

        logger.debug(f'Notified {self._sub_count} subs: {self._feed.id}: {self._feed.link}')

    async def _deactivate_feed_and_notify_all(self) -> None:
        feed = self._feed
        subs = self._subs
        reason = self._reason

        await inner.utils.deactivate_feed(feed)

        if not subs:  # nobody has subbed it or no active sub exists
            return

        user_id_lang_map: dict[int, str] = dict(
            await db.User.filter(id__in={sub.user_id for sub in subs}).values_list('id', 'lang')
        )
        lang_msg_body_map: dict[str, str] = {
            lang: '\n'.join((
                i18n[lang]['feed_deactivated_warn'],
                (
                    (
                        reason.i18n_message(lang)
                        if isinstance(reason, web.WebError)
                        else reason
                    )
                    if reason
                    else ''
                )
            ))
            for lang in user_id_lang_map.values()
        }

        sub_count = len(subs)
        feed_description = f'{feed.id}: {feed.link}'
        del reason

        _do_send: BatchTimeout[[db.Sub, str], None]
        async with BatchTimeout[[db.Sub, str], None](
                func=self._do_send,
                timeout=TIMEOUT,
                loop=env.loop,
                on_success=self._on_subtask_deactivated,
                on_canceled=self._on_subtask_canceled,
                on_error=self._on_subtask_unknown_error,
                on_timeout=self._on_subtask_timeout,
                on_timeout_error=self._on_subtask_timeout_unknown_error,
        ) as _do_send:
            for sub in subs:
                _do_send(
                    sub=sub,
                    post=(
                            f'<a href="{feed.link}">{escape_html(sub.title or feed.title)}</a>\n' +
                            lang_msg_body_map[user_id_lang_map[sub.user_id]]
                    )
                )
            del sub, subs, feed, user_id_lang_map, lang_msg_body_map

        logger.debug(f'Deactivated {sub_count} subs: {feed_description}')

    async def _do_send(self, sub: db.Sub, post: Union[str, Post]) -> None:
        self._stat.start()
        try:
            await self._send(sub, post)
        finally:
            self._stat.finish()

    async def _send(self, sub: db.Sub, post: Union[str, Post]) -> None:
        user_id = sub.user_id
        try:
            try:
                await env.bot.get_input_entity(user_id)  # verify that the input entity can be gotten first
            except ValueError:  # cannot get the input entity, the user may have banned the bot
                return await self._locked_unsub_all_and_leave_chat(
                    user_id=user_id,
                    err_msg=type(EntityNotFoundError).__name__,
                )
            try:
                if isinstance(post, str):
                    await env.bot.send_message(user_id, post, parse_mode='html', silent=not sub.notify)
                    return None
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
                error_message = Post(
                    f'Something went wrong while sending this post (feed: {post.feed_link}, user: {sub.user_id}). '
                    'Please check:<br><br>' + format_exc().replace('\n', '<br>'),
                    title=post.title,
                    feed_title=post.feed_title,
                    link=post.link,
                    author=post.author,
                    feed_link=post.feed_link,
                )
                await error_message.send_formatted_post(env.ERROR_LOGGING_CHAT, send_mode=2)
            except Exception as e:
                logger.error(
                    f'Failed to send sending error message for {post.link} '
                    f'(feed: {post.feed_link}, user: {sub.user_id}):',
                    exc_info=e,
                )
                await env.bot.send_message(
                    env.ERROR_LOGGING_CHAT,
                    'An sending error message cannot be sent, please check the logs.',
                )
        return None

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

    @bg
    async def notify_all(self) -> None:
        if self._reason is not None:
            await self._deactivate_feed_and_notify_all()
        else:
            await self._notify_all()
        return None
