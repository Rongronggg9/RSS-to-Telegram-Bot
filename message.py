import re
import traceback
import telegram.ext
from urllib import request
from xmlparser import get_md
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
        print(f'\t\t- Push {url} failed!')
        traceback.print_exc()
        # send an error message to manager (if set) or chatid
        send_message(manager, 'Something went wrong while sending this message. Please check:<br><br>' +
                     traceback.format_exc().replace('/n', '<br>'), feed_title, url, context)


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


def get_pic_info(url):
    urlopen = request.urlopen(url)
    headers = urlopen.info()
    pic_header = urlopen.read(256)

    size = getSize.search(str(headers)).group(1)

    height = width = -1
    if url.find('jpg') == -1 and url.find('jpeg') == -1:  # only for jpg
        return size, width, height

    pointer = -1
    if pic_header.find(b'\xff\xc2') != -1:
        pointer = pic_header.find(b'\xff\xc2')
    elif pic_header.find(b'\xff\xc0') != - 1:
        pointer = pic_header.find(b'\xff\xc0') + 1
    if pointer != -1:
        width = int(pic_header[pointer + 7:pointer + 9].hex(), 16)
        height = int(pic_header[pointer + 5:pointer + 7].hex(), 16)

    return size, width, height


def validate_medium(url, max_size=5242880):  # warning: only design for weibo
    max_size -= max_size % 1000
    size, width, height = get_pic_info(url)

    if int(size) > max_size or width > 4000 or height > 3000:
        if sizeParser.search(url):  # is a large weibo pic
            parsed = sizeParser.search(url).groups()
            if parsed[1] == sizes[-1]:
                return None
            reduced = parsed[0] + sizes[sizes.index(parsed[1]) + 1] + parsed[2]
            return validate_medium(reduced)
        else:  # TODO: reduce non-weibo pic size
            return None
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
