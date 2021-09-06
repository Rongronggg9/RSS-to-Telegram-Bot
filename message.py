import traceback
import telegram.error
import datetime
import time
from typing import List, Union, Optional, Tuple

from medium import Medium
import env


class Message:
    retry_after: datetime.datetime = datetime.datetime.min

    def __init__(self,
                 text: Optional[str] = None,
                 media: Optional[Union[List[Medium], Tuple[Medium]]] = None,
                 parse_mode: Optional[str] = 'HTML'):
        self.text = text
        self.media = media
        self.parse_mode = parse_mode
        self.retries = 0

    def send(self, chat_id: Union[str, int]):
        if self.retries >= 3:
            print('retried too many times! message dropped!')
            return
        sleep_time = (Message.retry_after - datetime.datetime.utcnow()).total_seconds()
        if sleep_time > 0:
            time.sleep(sleep_time + 1)
        try:
            self._send(chat_id)
            self.retries = 0
        except telegram.error.RetryAfter as e:  # exceed flood control
            if env.debug:
                raise e
            print(e)
            self.retries += 1
            Message.retry_after = datetime.datetime.utcnow() + datetime.timedelta(seconds=e.retry_after)
            self.send(chat_id)
        except telegram.error.TimedOut as e:
            if env.debug:
                raise e
            print(e)
            self.retries += 1
            time.sleep(1)
            self.send(chat_id)
        except Exception as e:
            if env.debug:
                raise e
            traceback.print_exc()
            raise e

    def _send(self, chat_id: Union[str, int]):
        pass


class TextMsg(Message):
    def _send(self, chat_id: Union[str, int]):
        env.bot.send_message(chat_id, self.text, parse_mode=self.parse_mode)


class PhotoMsg(Message):
    def _send(self, chat_id: Union[str, int]):
        env.bot.send_photo(chat_id, self.media[0].get_url(),
                           caption=self.text, parse_mode=self.parse_mode)


class VideoMsg(Message):
    def _send(self, chat_id: Union[str, int]):
        env.bot.send_video(chat_id, self.media[0].get_url(),
                           caption=self.text, parse_mode=self.parse_mode)


class MediaGroupMsg(Message):
    def _send(self, chat_id: Union[str, int]):
        media_list = list(map(lambda m: m.telegramize(), self.media))
        media_list[0].caption = self.text
        media_list[0].parse_mode = self.parse_mode
        env.bot.send_media_group(chat_id, media_list)

# def send(chatid, post, feed_title, context):
#     xml = post['content'][0]['value'] \
#         if ('content' in post) and (len(post['content']) > 0) \
#         else post['summary']
#     url = post['link']
#     author = post['author'] if ('author' in post and type(post['author']) is str) else None
#     title = post['title']
#     for _ in range(2):
#         try:
#             send_message(chatid, xml, feed_title, url, context, title=title, author=author)
#             break
#         except Exception as e:
#             print(f'\t\t- Send {url} failed!')
#             traceback.print_exc()
#             # send an error message to manager (if set) or chatid
#             try:
#                 send_message(env.manager, 'Something went wrong while sending this message. Please check:<br><br>' +
#                              traceback.format_exc().replace('\n', '<br>'), feed_title, url, context)
#             except:
#                 send_message(env.manager,
#                              'Something went wrong while sending this message, but error msg sent failed.\n'
#                              'Please check logs manually.', feed_title, url, context)
#
#
# def send_message(chatid, xml, feed_title, url, context, title=None, author=None):
#     video, pics = get_valid_media(xml)
#     if video:
#         print('\t\t- Detected video, send video message(s).')
#         send_media_message(chatid, xml, feed_title, url, video, context, title=title, author=author)
#         return  # for weibo, only 1 video can be attached, without any other pics
#
#     if pics:
#         print('\t\t- Detected pic(s), ', end="")
#         if pics:
#             print('send pic(s) message(s).')
#             send_media_message(chatid, xml, feed_title, url, pics, context, title=title, author=author)
#             return
#         else:
#             print('but too large.')
#
#     print('\t\t- No media, send text message(s).')
#     send_text_message(chatid, xml, feed_title, url, False, context, title=title, author=author)
#
#
# def send_text_message(chatid, xml, feed_title, url, is_tail, context, title=None, author=None):
#     if not is_tail:
#         text_list = get_md(xml, feed_title, url, _title=title, _author=author)
#     else:
#         text_list = xml
#
#     number = len(text_list)
#     head = ''
#
#     for i in range(is_tail, number):
#         if number > 1:
#             head = rf'\({i + 1}/{number}\)' + '\n'
#         context.bot.send_message(chatid, head + text_list[i], parse_mode='MarkdownV2', disable_web_page_preview=True)
#         print('\t\t\t- Text message.')
#
#
# def send_media_message(chatid, xml, feed_title, url, media, context, title=None, author=None):
#     text_list = get_md(xml, feed_title, url, 1024, _title=title, _author=author)
#     number = len(text_list)
#
#     head = ''
#     if number > 1:
#         head = rf'\(1/{number}\)' + '\n'
#
#     if type(media) == str:  # TODO: just a temporary workaround
#         context.bot.send_video(chatid, media, caption=head + text_list[0], parse_mode='MarkdownV2',
#                                supports_streaming=True)
#         print('\t\t\t- Video message.')
#     elif len(media) == 1:
#         context.bot.send_photo(chatid, media[0], head + text_list[0], parse_mode='MarkdownV2')
#         print('\t\t\t-Single pic message.')
#     else:
#         pic_objs = get_pic_objs(media, head + text_list[0])
#         context.bot.send_media_group(chatid, pic_objs)
#         print(f'\t\t\t- {len(pic_objs)} pics message.')
#
#     if number > 1:
#         send_text_message(chatid, text_list, feed_title, url, True, context)
#
#
# def get_pic_objs(pics, caption):
#     pic_objs = []
#     for url in pics:
#         pic_objs.append(telegram.InputMediaPhoto(url, caption, parse_mode='MarkdownV2'))
#         if caption:
#             caption = ''
#     return pic_objs
