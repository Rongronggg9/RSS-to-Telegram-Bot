from typing import Union, Optional
from telethon import events, Button
from telethon.tl import types
from telethon.tl.patched import Message

from src.i18n import i18n
from . import inner
from .utils import command_gatekeeper, parse_command, escape_html, parse_callback_data_with_page, \
    send_success_and_failure_msg


@command_gatekeeper(only_manager=False)
async def cmd_sub(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    args = parse_command(event.raw_text)
    filtered_urls = inner.utils.filter_urls(args)

    prompt = (i18n[lang]['sub_reply_feed_url_prompt_html'] if not event.is_channel or event.is_group
              else i18n[lang]['sub_usage_in_channel_html'])

    if not filtered_urls:
        await event.respond(prompt,
                            parse_mode='html',
                            buttons=Button.force_reply(single_use=True,
                                                       selective=True,
                                                       placeholder='url1 url2 url3 ...'),
                            reply_to=event.id if event.is_group else None)
        return

    msg: Message = await event.respond(i18n[lang]['processing'])

    sub_result = await inner.sub.subs(event.chat_id, filtered_urls, lang=lang, bypass_url_filter=True)

    if sub_result is None:
        await msg.edit(prompt, parse_mode='html')
        return

    await send_success_and_failure_msg(msg, **sub_result, lang=lang, edit=True)


@command_gatekeeper(only_manager=False)
async def cmd_unsub(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    args = parse_command(event.raw_text)
    user_id = event.chat_id

    unsub_result = await inner.sub.unsubs(user_id, args, lang=lang)

    if unsub_result is None:
        buttons = await inner.utils.get_sub_choosing_buttons(user_id, lang=lang, page_number=1, callback='unsub',
                                                             get_page_callback='get_unsub_page')
        await event.respond(i18n[lang]['unsub_choose_sub_prompt_html'] if buttons else i18n[lang]['no_subscription'],
                            buttons=buttons,
                            parse_mode='html')
        return

    await send_success_and_failure_msg(event, **unsub_result, lang=lang, edit=False)


@command_gatekeeper(only_manager=False)
async def cmd_or_callback_unsub_all(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                                    *_,
                                    lang: Optional[str] = None,
                                    **__):  # command = /unsub_all, callback data = unsub_all
    is_callback = isinstance(event, events.CallbackQuery.Event)
    user_id = event.chat_id
    if is_callback:
        backup_file = await inner.sub.export_opml(user_id)
        if backup_file is None:
            await event.respond(i18n[lang]['no_subscription'])
            return
        await event.respond(
            file=backup_file,
            attributes=(
                types.DocumentAttributeFilename(f"RSStT_unsub_all_backup.opml"),
            )
        )

        unsub_all_result = await inner.sub.unsub_all(user_id)
        await send_success_and_failure_msg(event, **unsub_all_result, lang=lang, edit=True)
        return

    if await inner.utils.have_subs(user_id):
        await event.respond(
            i18n[lang]['unsub_all_confirm_prompt'],
            buttons=[
                [Button.inline(i18n[lang]['unsub_all_confirm'], data='unsub_all')],
                [Button.inline(i18n[lang]['unsub_all_cancel'], data='cancel')]
            ]
        )
        return
    await event.respond(i18n[lang]['no_subscription'])


@command_gatekeeper(only_manager=False)
async def cmd_list_or_callback_get_list_page(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                                             *_,
                                             lang: Optional[str] = None,
                                             **__):  # command = /list, callback data = get_list_page|{page_number}
    is_callback = isinstance(event, events.CallbackQuery.Event)
    if is_callback:
        _, page_number = parse_callback_data_with_page(event.data)
    else:
        page_number = 1

    user_id = event.chat_id

    # Telegram only allow <= 100 parsing entities in a message
    page_number, page_count, page, sub_count = \
        await inner.utils.get_sub_list_by_page(user_id=user_id, page_number=page_number, size=99)

    if page_count == 0:
        await event.respond(i18n[lang]['no_subscription'])
        return

    list_result = (
            f'<b>{i18n[lang]["subscription_list"]}</b>'  # it occupies a parsing entity
            + '\n'
            + '\n'.join(f'<a href="{sub.feed.link}">{escape_html(sub.title or sub.feed.title)}</a>' for sub in page)
    )

    page_buttons = inner.utils.get_page_buttons(page_number=page_number,
                                                page_count=page_count,
                                                get_page_callback='get_list_page',
                                                total_count=sub_count,
                                                lang=lang)

    await event.edit(list_result, parse_mode='html', buttons=page_buttons) if is_callback else \
        await event.respond(list_result, parse_mode='html', buttons=page_buttons)


@command_gatekeeper(only_manager=False)
async def callback_unsub(event: events.CallbackQuery.Event, *_, lang: Optional[str] = None, **__):
    # callback data = unsub={sub_id}|{page}
    sub_id, page = parse_callback_data_with_page(event.data)
    sub_id = int(sub_id)
    unsub_d = await inner.sub.unsub(event.chat_id, sub_id=sub_id)

    msg = (
            f'<b>{i18n[lang]["unsub_successful" if unsub_d["sub"] else "unsub_failed"]}</b>\n'
            + (
                f'<a href="{unsub_d["sub"].feed.link}">'
                f'{escape_html(unsub_d["sub"].feed.title or unsub_d["sub"].title)}</a>'
                if unsub_d['sub']
                else f'{escape_html(unsub_d["url"])} ({unsub_d["msg"]})</a>'
            )
    )

    if unsub_d['sub']:  # successfully unsubed
        await callback_get_unsub_page.__wrapped__(event, lang=lang, page=page)

    # await event.edit(msg, parse_mode='html')
    await event.respond(msg, parse_mode='html')  # make unsubscribing multiple subscriptions more efficiency


@command_gatekeeper(only_manager=False)
async def callback_get_unsub_page(event: events.CallbackQuery.Event,
                                  *_,
                                  page: Optional[int] = None,
                                  lang: Optional[str] = None,
                                  **__):  # callback data = get_unsub_page|{page_number}
    if not page:
        _, page = parse_callback_data_with_page(event.data)
    buttons = await inner.utils.get_sub_choosing_buttons(event.chat_id, page, callback='unsub',
                                                         get_page_callback='get_unsub_page', lang=lang)
    await event.edit(None if buttons else i18n[lang]['no_subscription'], buttons=buttons)
