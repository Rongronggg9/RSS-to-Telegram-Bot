from typing import Union, Optional
from telethon import events, Button
from telethon.tl.patched import Message

from . import inner, misc
from .utils import command_gatekeeper, parse_sub_customization_callback_data, parse_callback_data_with_page, \
    escape_html, parse_command_get_sub_and_param
from src import db, env
from src.i18n import i18n


@command_gatekeeper(only_manager=False)
async def cmd_set_or_callback_get_set_page(event: Union[events.NewMessage.Event, Message, events.CallbackQuery.Event],
                                           *_,
                                           lang: Optional[str] = None,
                                           page: Optional[int] = None,
                                           **__):  # command: /set ; callback data: get_set_page|{page_number}
    is_callback = isinstance(event, events.CallbackQuery.Event)
    user_id = event.chat_id
    if not page:
        _, page = parse_callback_data_with_page(event.data) if is_callback else (None, 1)

    have_subs = await inner.utils.have_subs(event.chat_id)
    if not have_subs:
        msg = i18n[lang]['no_subscription']
        buttons = None
    else:
        msg = i18n[lang]['set_choose_sub_prompt']
        buttons = await inner.utils.get_sub_choosing_buttons(user_id, page_number=page, lang=lang,
                                                             callback='set',
                                                             get_page_callback='get_set_page')

    await event.respond(msg, buttons=buttons) if not is_callback else \
        await event.edit(msg, buttons=buttons)


@command_gatekeeper(only_manager=False)
async def callback_set(event: events.CallbackQuery.Event,
                       *_,
                       lang: Optional[str] = None,
                       **__):  # callback data = set={sub_id}[,{action}[,{param}]][|{page_number}]
    """
    send_mode: -1=force link, 0=auto, 1=force Telegraph, 2=force message
    length_limit: Telegraph length limit, valid when send_mode==0. If exceeded, send via Telegraph; If is 0,
        send via Telegraph when a post cannot be sent in a single message
    link_preview: 0=auto, 1=force enable
    display_author: -1=disable, 0=auto, 1=force display
    display_via: -2=completely disable, -1=disable but display link, 0=auto, 1=force display
    display_title: -1=disable, 0=auto, 1=force display
    style: 0=RSStT, 1=flowerss
    """
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
            or (action in {'interval', 'length_limit'} and isinstance(param, int))
            or action == 'activate'
            or action in inner.customization.SUB_OPTIONS_EXHAUSTIVE_VALUES
    ):
        if action == 'interval' and isinstance(param, int):
            await inner.customization.set_sub_interval(sub, param)
        elif action == 'length_limit' and isinstance(param, int):
            await inner.customization.set_sub_length_limit(sub, param)
        elif action == 'activate':
            await inner.customization.set_sub_activate(sub)
        elif action is not None and action in inner.customization.SUB_OPTIONS_EXHAUSTIVE_VALUES:
            await inner.customization.set_sub_exhaustive_option(sub, action)

        info = await inner.customization.get_sub_info(sub, lang)
        buttons = await inner.customization.get_sub_customization_buttons(sub, lang=lang, page=page)
        await event.edit(info, buttons=buttons, parse_mode='html')
        return

    if action == 'interval':
        msg = i18n[lang]['set_interval_prompt']
        buttons = await inner.customization.get_set_interval_buttons(sub, lang=lang, page=page)
        await event.edit(msg, buttons=buttons)
        return
    if action == 'length_limit':
        if sub.send_mode != 0:
            await event.answer(i18n[lang]['length_limit_only_effective_if_send_mode_auto'], alert=True)
            return
        msg = i18n[lang]['set_length_limit_prompt']
        buttons = await inner.customization.get_set_length_limit_buttons(sub, lang=lang, page=page)
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
                                                   **__):  # callback data: get_(activate|deactivate)_page|{page}
    event_is_msg = not isinstance(event, events.CallbackQuery.Event)
    if page is None:
        page = int(parse_callback_data_with_page(event.data)[1]) if not event_is_msg else 1
    have_subs = await inner.utils.have_subs(event.chat_id)
    if not have_subs:
        no_subscription_msg = i18n[lang]['no_subscription']
        await (event.respond(no_subscription_msg) if event_is_msg
               else event.edit(no_subscription_msg))
        return
    sub_buttons = await inner.utils.get_sub_choosing_buttons(
        event.chat_id,
        page_number=page,
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
                                              **__):  # callback data: (activate|deactivate)_sub={id}|{page}
    sub_id, page = parse_callback_data_with_page(event.data)
    sub_id = int(sub_id)
    unsub_res = await inner.utils.activate_or_deactivate_sub(event.chat_id, sub_id, activate=activate)
    if unsub_res is None:
        await event.answer('ERROR: ' + i18n[lang]['subscription_not_exist'], alert=True)
        return
    await callback_get_activate_or_deactivate_page.__wrapped__(event, activate, lang=lang, page=page)


@command_gatekeeper(only_manager=False)
async def callback_del_subs_title(event: events.CallbackQuery.Event,
                                  *_,
                                  **__):  # callback data: del_subs_title={id_start}-{id_end}|{id_start}-{id_end}|...
    user_id = event.chat_id
    id_ranges_str = event.data.decode().strip().split('=')[-1].split('|')
    subs = []
    for id_range_str in id_ranges_str:
        id_range = id_range_str.split('-')
        id_start = int(id_range[0])
        id_end = int(id_range[1])
        subs.extend(await db.Sub.filter(user_id=user_id, id__range=(id_start, id_end)).all())
    await inner.customization.del_subs_title(subs)
    await misc.callback_del_buttons.__wrapped__(event)


@command_gatekeeper(only_manager=False)
async def cmd_set_title(event: Union[events.NewMessage.Event, Message],
                        *_,
                        lang: Optional[str] = None,
                        **__):
    sub, title = await parse_command_get_sub_and_param(event.raw_text, event.chat_id, max_split=3)
    title = title.strip() if title else None
    if not sub:
        await event.respond(i18n[lang]['permission_denied_no_direct_use'])
        return
    if not title and not sub.title:
        await event.respond(i18n[lang]['cmd_set_title_usage_prompt_html'], parse_mode='html')
        return
    await inner.customization.set_sub_title(sub, title)
    await event.respond(
        (
                ((i18n[lang]['set_title_success'] + '\n' + f'<code>{escape_html(title)}</code>')
                 if title
                 else i18n[lang]['set_title_success_cleared'])
                + '\n\n' +
                await inner.customization.get_sub_info(sub, lang=lang)
        ),
        buttons=(Button.inline(i18n[lang]['other_settings_button'], data=f'set={sub.id}'),),
        parse_mode='html')


@command_gatekeeper(only_manager=False)
async def cmd_set_interval(event: Union[events.NewMessage.Event, Message],
                           *_,
                           lang: Optional[str] = None,
                           **__):
    sub, interval = await parse_command_get_sub_and_param(event.raw_text, event.chat_id)
    interval = int(interval) if interval and interval.isdigit() and int(interval) >= 1 else None
    minimal_interval = db.EffectiveOptions.minimal_interval
    if not sub:
        await event.respond(i18n[lang]['permission_denied_no_direct_use'])
        return
    if not interval:
        await event.respond(i18n[lang]['cmd_set_interval_usage_prompt_html'], parse_mode='html')
        return
    if interval < minimal_interval and event.chat_id != env.MANAGER:
        await event.respond(i18n[lang]['set_interval_failure_too_small_html'] % minimal_interval,
                            parse_mode='html')
        return
    await inner.customization.set_sub_interval(sub, interval)
    await event.respond(
        (
                (i18n[lang]['set_interval_success_html'] % (interval,))
                + '\n\n' +
                await inner.customization.get_sub_info(sub, lang=lang)
        ),
        buttons=(Button.inline(i18n[lang]['other_settings_button'], data=f'set={sub.id}'),),
        parse_mode='html')
