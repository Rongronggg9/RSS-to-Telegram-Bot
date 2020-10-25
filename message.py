import traceback
import telegram.ext
from media import get_valid_media
from xmlparser import get_md
from telegramRSSbot import manager


def send(chatid, xml, feed_title, url, context):
    for _ in range(2):
        try:
            send_message(chatid, xml, feed_title, url, context)
            break
        except Exception as e:
            print(f'\t\t- Send {url} failed!')
            traceback.print_exc()
            # send an error message to manager (if set) or chatid
            try:
                send_message(manager, 'Something went wrong while sending this message. Please check:<br><br>' +
                             traceback.format_exc().replace('\n', '<br>'), feed_title, url, context)
            except:
                send_message(manager, 'Something went wrong while sending this message, but error msg sent failed.\n'
                                      'Please check logs manually.', feed_title, url, context)


def send_message(chatid, xml, feed_title, url, context):
    video, pics = get_valid_media(xml)
    if video:
        print('\t\t- Detected video, send video message(s).')
        send_media_message(chatid, xml, feed_title, url, video, context)
        return  # for weibo, only 1 video can be attached, without any other pics

    if pics:
        print('\t\t- Detected pic(s), ', end="")
        if pics:
            print('send pic(s) message(s).')
            send_media_message(chatid, xml, feed_title, url, pics, context)
            return
        else:
            print('but too large.')

    print('\t\t- No media, send text message(s).')
    send_text_message(chatid, xml, feed_title, url, False, context)


def send_text_message(chatid, xml, feed_title, url, is_tail, context):
    if not is_tail:
        text_list = get_md(xml, feed_title, url)
    else:
        text_list = xml

    number = len(text_list)
    head = ''

    for i in range(is_tail, number):
        if number > 1:
            head = rf'\({i + 1}/{number}\)' + '\n'
        context.bot.send_message(chatid, head + text_list[i], parse_mode='MarkdownV2', disable_web_page_preview=True)
        print('\t\t\t- Text message.')


def send_media_message(chatid, xml, feed_title, url, media, context):
    text_list = get_md(xml, feed_title, url, 1024)
    number = len(text_list)

    head = ''
    if number > 1:
        head = rf'\(1/{number}\)' + '\n'

    if type(media) == str:  # TODO: just a temporary workaround
        context.bot.send_video(chatid, media, caption=head + text_list[0], parse_mode='MarkdownV2',
                               supports_streaming=True)
        print('\t\t\t- Video message.')
    elif len(media) == 1:
        context.bot.send_photo(chatid, media[0], head + text_list[0], parse_mode='MarkdownV2')
        print('\t\t\t-Single pic message.')
    else:
        pic_objs = get_pic_objs(media, head + text_list[0])
        context.bot.send_media_group(chatid, pic_objs)
        print(f'\t\t\t- {len(pic_objs)} pics message.')

    if number > 1:
        send_text_message(chatid, text_list, feed_title, url, True, context)


def get_pic_objs(pics, caption):
    pic_objs = []
    for url in pics:
        pic_objs.append(telegram.InputMediaPhoto(url, caption, parse_mode='MarkdownV2'))
        if caption:
            caption = ''
    return pic_objs
