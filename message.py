import re
import traceback
import telegram.ext
from urllib import request
from htmlparser import get_md
from telegramRSSbot import manager

getPic = re.compile(r'<img src="(.+?)"')
getVideo = re.compile(r'<video src="(.+?)"')
getSize = re.compile(r'^Content-Length: (\d+)$', re.M)
sizes = ['large', 'mw2048', 'mw1024', 'mw720']
sizeParser = re.compile(r'(^https?://\w+\.sinaimg\.\S+/)(large|mw2048|mw1024|mw720)(/\w+\.\w+$)')


def send(chatid, xml, feed_title, url, context):
    try:
        send_message(chatid, xml, feed_title, url, context)
    except Exception as e:
        traceback.print_exc()
        # send an error message to manager (if set) or chatid
        send_message(manager, 'Something went wrong while sending this message. Please check:<br><br>' +
                     traceback.format_exc(), feed_title, url, context)
        print()
        pass


def send_message(chatid, xml, feed_title, url, context):
    if getVideo.search(xml):
        video = validate_medium(getVideo.findall(xml)[0], 20971520)
        if video:
            send_media_message(chatid, xml, feed_title, url, video, context)
            return  # for weibo, only 1 video can be attached, without any other pics

    if getPic.search(xml):
        pics = validate_media(getPic.findall(xml))
        if pics:
            send_media_message(chatid, xml, feed_title, url, pics, context)
            return

    send_text_message(chatid, xml, feed_title, url, False, context)


def validate_medium(url, max_size=5242880):  # warning: only design for weibo
    max_size -= max_size % 1000
    headers = request.urlopen(url).info()
    size = getSize.search(str(headers)).group(1)
    if int(size) > 5240000:  # should be 5242880, but preventatively set to 5240000
        if sizeParser.search(url):  # is a large weibo pic
            parsed = sizeParser.search(url).groups()
            reduced = parsed[0] + sizes[sizes.index(parsed[1]) + 1] + parsed[2]
            return validate_medium(reduced)
        else:  # TODO: reduce non-weibo pic size
            return None
    else:
        return url


def validate_media(media):  # reduce pic size to <5MB
    reduced_pics = []
    for url in media:
        reduced = validate_medium(url)
        if reduced:  # warning: too large non-weibo pic will be discarded
            reduced_pics.append(reduced)
    return reduced_pics


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


def send_media_message(chatid, xml, feed_title, url, media, context):
    text_list = get_md(xml, feed_title, url, 1024)
    number = len(text_list)

    head = ''
    if number > 1:
        head = rf'\(1/{number}\)' + '\n'

    if type(media) == str:  # TODO: just a temporary workaround
        context.bot.send_video(chatid, media, caption=head + text_list[0], parse_mode='MarkdownV2',
                               supports_streaming=True)
    elif len(media) == 1:
        context.bot.send_photo(chatid, media[0], head + text_list[0], parse_mode='MarkdownV2')
    else:
        pic_objs = get_pic_objs(media, head + text_list[0])
        context.bot.send_media_group(chatid, pic_objs)

    if number > 1:
        send_text_message(chatid, text_list, feed_title, url, True, context)


def get_pic_objs(pics, caption):
    pic_objs = []
    for url in pics:
        pic_objs.append(telegram.InputMediaPhoto(url, caption, parse_mode='MarkdownV2'))
        if caption:
            caption = ''
    return pic_objs
