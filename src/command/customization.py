from typing import Union, Optional
from telethon import events, Button
from telethon.tl.patched import Message

from . import inner
from .utils import command_gatekeeper, parse_sub_customization_callback_data, parse_callback_data_with_page
from src import db
from src.i18n import i18n


@command_gatekeeper(only_manager=False)
async def cmd_set_or_callback_get_set_page(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                                           *_,
                                           lang: Optional[str] = None,
                                           page: Optional[int] = None,
                                           **__):  # command: /set ; callback data: get_set_page_{page_number}
    is_callback = isinstance(event, events.CallbackQuery.Event)
    user_id = event.chat_id
    if not page:
        page, _ = parse_callback_data_with_page(event.data) if is_callback else (1, None)

    buttons = await inner.utils.get_sub_choosing_buttons(user_id, page=page, lang=lang,
                                                         callback='set',
                                                         get_page_callback='get_set_page')
    msg = i18n[lang]['set_choose_sub_prompt']
    await event.respond(msg, buttons=buttons) if not is_callback else \
        await event.edit(msg, buttons=buttons)


@command_gatekeeper(only_manager=False)
async def callback_set(event: events.CallbackQuery.Event,
                       *_,
                       lang: Optional[str] = None,
                       **__):  # callback data = set_{sub_id}[_{action}[_{param}]][|{page_number}]

    sub_id, action, param, page = parse_sub_customization_callback_data(event.data)

    if sub_id is None:
        await cmd_set_or_callback_get_set_page.__wrapped__(event, lang=lang, page=page)
        return

    sub = await db.Sub.get_or_none(id=sub_id, user=event.chat_id).prefetch_related('feed')
    if sub is None:
        await event.edit(i18n[lang]['subscription_not_exist'])
        return

    if (
            action is None
            or (action == 'interval' and isinstance(param, int))
            or action == 'notify'
            or action == 'activate'
    ):
        if action == 'interval' and isinstance(param, int):
            await inner.customization.set_sub_interval(sub, param)
        elif action == 'notify':
            await inner.customization.set_sub_notification(sub)
        elif action == 'activate':
            await inner.customization.set_sub_activate(sub)

        info = await inner.customization.get_sub_info(sub, lang)
        buttons = await inner.customization.get_sub_customization_buttons(sub, lang=lang, page=page)
        await event.edit(info, buttons=buttons, parse_mode='html')
        return

    if action == 'interval':
        msg = i18n[lang]['set_interval_prompt']
        buttons = await inner.customization.get_set_interval_buttons(sub, lang=lang, page=page)
        await event.edit(msg, buttons=buttons)
        return

    await event.edit(i18n[lang]['action_invalid'])
    return


@command_gatekeeper(only_manager=False)
async def cmd_activate_or_deactivate_subs(event: Union[events.NewMessage.Event, Message],
                                          activate: bool,
                                          *_,
                                          lang: Optional[str] = None,
                                          **__):  # cmd: activate_subs | deactivate_subs
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=1)


@command_gatekeeper(only_manager=False)
async def callback_get_activate_or_deactivate_page(event: Union[events.CallbackQuery.Event,
                                                                events.NewMessage.Event,
                                                                Message],
                                                   activate: bool,
                                                   *_,
                                                   lang: Optional[str] = None,
                                                   page: Optional[int] = None,
                                                   **__):  # callback data: get_(activate|deactivate)_page_{page}
    event_is_msg = not isinstance(event, events.CallbackQuery.Event)
    if page is None:
        page = int(event.data.decode().strip().split('_')[-1]) if not event_is_msg else 1
    have_subs = await inner.utils.have_subs(event.chat_id)
    if not have_subs:
        no_subscription_msg = i18n[lang]['no_subscription']
        await (event.respond(no_subscription_msg) if event_is_msg
               else event.edit(no_subscription_msg))
        return
    sub_buttons = await inner.utils.get_sub_choosing_buttons(
        event.chat_id,
        page=page,
        callback='activate_sub' if activate else 'deactivate_sub',
        get_page_callback='get_activate_page' if activate else 'get_deactivate_page',
        lang=lang,
        rows=11,
        state=0 if activate else 1
    )
    msg = i18n[lang]['choose_sub_to_be_activated' if sub_buttons else 'all_subs_are_activated'] if activate \
        else i18n[lang]['choose_sub_to_be_deactivated' if sub_buttons else 'all_subs_are_deactivated']
    activate_or_deactivate_all_subs_str = 'activate_all_subs' if activate else 'deactivate_all_subs'
    buttons = (
            (
                (Button.inline(i18n[lang][activate_or_deactivate_all_subs_str],
                               data=activate_or_deactivate_all_subs_str),),
            )
            + sub_buttons
    ) if sub_buttons else None
    await (event.respond(msg, buttons=buttons) if event_is_msg
           else event.edit(msg, buttons=buttons))


@command_gatekeeper(only_manager=False)
async def callback_activate_or_deactivate_all_subs(event: events.CallbackQuery.Event,
                                                   activate: bool,
                                                   *_,
                                                   lang: Optional[str] = None,
                                                   **__):  # callback data: (activate|deactivate)_all_subs
    await inner.utils.activate_or_deactivate_all_subs(event.chat_id, activate=activate)
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=1)


@command_gatekeeper(only_manager=False)
async def callback_activate_or_deactivate_sub(event: events.CallbackQuery.Event,
                                              activate: bool,
                                              *_,
                                              lang: Optional[str] = None,
                                              **__):  # callback data: (activate|deactivate)_sub_{id}|{page}
    sub_id, page = parse_callback_data_with_page(event.data)
    unsub_res = await inner.utils.activate_or_deactivate_sub(event.chat_id, sub_id, activate=activate)
    if unsub_res is None:
        await event.answer('ERROR: ' + i18n[lang]['subscription_not_exist'], alert=True)
        return
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=page)
