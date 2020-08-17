import re
import telegram.ext
from htmlparser import get_md

isPic = re.compile(r'<img src="(.+?)"')


def send(chatid, html, feed_title, url, context):
    if isPic.search(html):
        pics = isPic.findall(html)
        send_media_message(chatid, html, feed_title, url, pics, context)
    else:
        send_text_message(chatid, html, feed_title, url, False, context)


def send_text_message(chatid, html, feed_title, url, is_tail, context):
    if not is_tail:
        text_list = get_md(html, feed_title, url)
    else:
        text_list = html

    number = len(text_list)
    if number == 1:
        context.bot.send_message(chatid, text_list[0], parse_mode='MarkdownV2')
    else:
        for i in range(number):
            context.bot.send_message(chatid, rf'\({i + 1 + is_tail}/{number + is_tail}\)' + '\n' + text_list[i]
                                     , parse_mode='MarkdownV2')


def send_media_message(chatid, html, feed_title, url, pics, context):
    text_list = get_md(html, feed_title, url, 1024)
    number = len(text_list)

    if len(pics) == 1:
        context.bot.send_photo(chatid, pics[0], text_list[0], parse_mode='MarkdownV2')
    else:
        pic_objs = get_pic_objs(pics, text_list[0])
        context.bot.send_media_group(chatid, pic_objs)

    if number > 1:
        for i in range(1, number):
            send_text_message(chatid, text_list, feed_title, url, True, context)


def get_pic_objs(pics, caption):
    pic_objs = []
    for url in pics:
        pic_objs.append(telegram.InputMediaPhoto(url, caption, parse_mode='MarkdownV2'))
        if caption:
            caption = ''
    return pic_objs
