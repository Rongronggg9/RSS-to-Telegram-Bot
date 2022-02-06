from typing import Union, Optional
from telethon import events, Button
from telethon.tl.patched import Message

from src.i18n import i18n
from . import inner
from .utils import command_gatekeeper, parse_command, escape_html, parse_callback_data_with_page


@command_gatekeeper(only_manager=False)
async def cmd_sub(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    args = parse_command(event.raw_text)
    filtered_urls = inner.utils.filter_urls(args)

    if not filtered_urls:
        await event.respond(i18n[lang]['sub_reply_feed_url_prompt_html'] if not event.is_channel or event.is_group
                            else i18n[lang]['sub_usage_in_channel_html'],
                            parse_mode='html',
                            buttons=Button.force_reply(single_use=True,
                                                       selective=True,
                                                       placeholder='url1 url2 url3 ...'),
                            reply_to=event.id if event.is_group else None)
        return

    msg: Message = await event.respond(i18n[lang]['processing'])

    sub_result = await inner.sub.subs(event.chat_id, filtered_urls, lang=lang, bypass_url_filter=True)

    if sub_result is None:
        await msg.edit(i18n[lang]['sub_reply_feed_url_prompt_html'],
                       parse_mode='html')
        return

    await msg.edit(sub_result["msg"], parse_mode='html')


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

    await event.respond(unsub_result['msg'], parse_mode='html')


@command_gatekeeper(only_manager=False)
async def cmd_unsub_all(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    unsub_all_result = await inner.sub.unsub_all(event.chat_id)
    await event.respond(unsub_all_result['msg'] if unsub_all_result else i18n[lang]['no_subscription'],
                        parse_mode='html')


@command_gatekeeper(only_manager=False)
async def cmd_list(event: Union[events.NewMessage.Event, Message], *_, lang: Optional[str] = None, **__):
    subs = await inner.utils.list_sub(event.chat_id)
    if not subs:
        await event.respond(i18n[lang]['no_subscription'])
        return

    list_result = (
            f'<b>{i18n[lang]["subscription_list"]}</b>\n'
            + '\n'.join(f'<a href="{sub.feed.link}">{escape_html(sub.feed.title)}</a>' for sub in subs)
    )

    await event.respond(list_result, parse_mode='html')


@command_gatekeeper(only_manager=False)
async def callback_unsub(event: events.CallbackQuery.Event, *_, lang: Optional[str] = None, **__):
    # callback data = unsub_{sub_id}|{page}
    sub_id, page = parse_callback_data_with_page(event.data)
    unsub_d = await inner.sub.unsub(event.chat_id, sub_id=sub_id)

    msg = (
            f'<b>{i18n[lang]["unsub_successful" if unsub_d["sub"] else "unsub_failed"]}</b>\n'
            + (
                f'<a href="{unsub_d["sub"].feed.link}">{escape_html(unsub_d["sub"].feed.title)}</a>' if unsub_d['sub']
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
                                  **__):  # callback data = get_unsub_page_{page_number}
    page = page or int(event.data.decode().strip().split('_')[-1])
    buttons = await inner.utils.get_sub_choosing_buttons(event.chat_id, page, callback='unsub',
                                                         get_page_callback='get_unsub_page', lang=lang)
    await event.edit(None if buttons else i18n[lang]['no_subscription'], buttons=buttons)
