import functools
import feedparser
import logging
import requests
import telegram
from requests.adapters import HTTPAdapter
from telegram.error import TelegramError
from telegram.ext import Updater, CommandHandler, Filters
from pathlib import Path
from io import BytesIO
from typing import Optional

import env
from db import db
from post import Post, get_post_from_entry

Path("config").mkdir(parents=True, exist_ok=True)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.DEBUG if env.DEBUG else logging.INFO)

logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.ERROR if env.DEBUG else logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.ERROR if env.DEBUG else logging.CRITICAL)
logging.getLogger('apscheduler').setLevel(logging.INFO if env.DEBUG else logging.WARNING)

# permission verification
GROUP = 1087968824


def permission_required(func=None, *, only_manager=False, only_in_private_chat=False):
    if func is None:
        return functools.partial(permission_required, only_manager=only_manager,
                                 only_in_private_chat=only_in_private_chat)

    @functools.wraps(func)
    def wrapper(update: telegram.Update, context: Optional[telegram.ext.CallbackContext] = None, *args, **kwargs):
        message = update.message
        command = message.text
        user_id = update.effective_user.id
        user_fullname = update.effective_user.full_name
        if only_manager and str(user_id) != env.MANAGER:
            update.effective_message.reply_text('此命令只可由机器人的管理员使用。\n'
                                                'This command can be only used by the bot manager.')
            logging.info(f'Refused {user_fullname} ({user_id}) to use {command}.')
            return

        if message.chat.type == 'private':
            logging.info(f'Allowed {user_fullname} ({user_id}) to use {command}.')
            return func(update, context, *args, **kwargs)

        if message.chat.type in ('supergroup', 'group'):
            if only_in_private_chat:
                update.effective_message.reply_text('此命令不允许在群聊中使用。\n'
                                                    'This command can not be used in a group.')
                logging.info(f'Refused {user_fullname} ({user_id}) to use {command} in a group chat.')
                return

            user_status = update.effective_chat.get_member(user_id).status
            if user_id != GROUP and user_status not in ('administrator', 'creator'):
                update.effective_message.reply_text('此命令只可由群管理员使用。\n'
                                                    'This command can be only used by an administrator.')
                logging.info(
                    f'Refused {user_fullname} ({user_id}, {user_status}) to use {command} in {message.chat.title} ({message.chat.id}).')
                return
            logging.info(
                f'Allowed {user_fullname} ({user_id}, {user_status}) to use {command} in {message.chat.title} ({message.chat.id}).')
            return func(update, context, *args, **kwargs)
        return

    return wrapper


# REQUESTS
def web_get(url):
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=1))
    session.mount('https://', HTTPAdapter(max_retries=1))

    response = session.get(url, timeout=(10, 10), proxies=env.REQUESTS_PROXIES, headers=env.REQUESTS_HEADERS)
    content = BytesIO(response.content)
    return content


def feed_get(url, update=None, verbose=False):
    # try if the url is a valid RSS feed
    try:
        rss_content = web_get(url)
        rss_d = feedparser.parse(rss_content, sanitize_html=False, resolve_relative_uris=False)
        rss_d.entries[0]['title']
    except IndexError as e:
        if verbose:
            update.effective_message.reply_text('ERROR: 链接看起来不像是个 RSS 源，或该源不受支持')
        raise e
    except requests.exceptions.RequestException as e:
        if verbose:
            update.effective_message.reply_text('ERROR: 网络超时')
        raise e
    return rss_d


@permission_required(only_manager=True)
def cmd_rss_list(update: telegram.Update, context: telegram.ext.CallbackContext):
    if not db.read_all():
        update.effective_message.reply_text('数据库为空')
    else:
        for title, url_list in db.read_all().items():
            update.effective_message.reply_text(
                '标题: ' + title +
                '\nRSS 源: ' + url_list[0] +
                '\n最后检查的文章: ' + url_list[1])


@permission_required(only_manager=True)
def cmd_rss_add(update: telegram.Update, context: telegram.ext.CallbackContext):
    # try if there are 2 arguments passed
    try:
        title = context.args[0]
        url = context.args[1]
    except IndexError:
        update.effective_message.reply_text(
            'ERROR: 格式需要为: /add 标题 RSS')
        raise
    try:
        rss_d = feed_get(url, update, verbose=True)
    except (IndexError, requests.exceptions.RequestException):
        return
    db.write(title, url, str(rss_d.entries[0]['link']))
    update.effective_message.reply_text(
        '已添加 \n标题: %s\nRSS 源: %s' % (title, url))


@permission_required(only_manager=True)
def cmd_rss_remove(update: telegram.Update, context: telegram.ext.CallbackContext):
    if not context.args:
        update.effective_message.reply_text("ERROR: 请指定订阅名！")
        return
    name = context.args[0]
    if not db.read(name):
        update.effective_message.reply_text("ERROR: 没有这个订阅: " + context.args[0])
        return
    db.delete(name)
    update.effective_message.reply_text("已移除: " + context.args[0])


@permission_required(only_manager=True)
def cmd_help(update: telegram.Update, context: telegram.ext.CallbackContext):
    update.effective_message.reply_text(
        f"""[RSS to Telegram bot，专为短动态类消息设计的 RSS Bot。](https://github.com/Rongronggg9/RSS-to-Telegram-Bot)
\n成功添加一个 RSS 源后, 机器人就会开始检查订阅，每 {env.DELAY} 秒一次。 \\(可修改\\)
\n标题为只是为管理 RSS 源而设的，可随意选取，但不可有空格。
\n命令:
__*/help*__ : 发送这条消息
__*/add*__ __*标题*__ __*RSS*__ : 添加订阅
__*/remove*__ __*标题*__ : 移除订阅
__*/list*__ : 列出数据库中的所有订阅，包括它们的标题和 RSS 源
__*/test*__ __*RSS*__ __*编号起点\\(可选\\)*__ __*编号终点\\(可选\\)*__ : 从 RSS 源处获取一条 post \\(编号为 0\\-based, 不填或超出范围默认为 0，不填编号终点默认只获取一条 post\\)，或者直接用 `all` 获取全部
\n您的 chatid 是: {update.message.chat.id}""",
        parse_mode='MarkdownV2'
    )


@permission_required(only_manager=True)
def cmd_test(update: telegram.Update, context: telegram.ext.CallbackContext):
    # try if there are 2 arguments passed
    try:
        url = context.args[0]
    except IndexError:
        update.effective_message.reply_text('ERROR: 格式需要为: /test RSS 条目编号起点(可选) 条目编号终点(可选)')
        raise
    try:
        rss_d = feed_get(url, update, verbose=True)
    except (IndexError, requests.exceptions.RequestException):
        update.effective_message.reply_text('ERROR: 获取订阅失败')
        return
    index1 = 0
    index2 = 1
    if len(context.args) > 1 and context.args[1] == 'all':
        index1 = 0
        index2 = None
    elif len(context.args) == 2 and len(rss_d.entries) > int(context.args[1]):
        index1 = int(context.args[1])
        index2 = int(context.args[1]) + 1
    elif len(context.args) > 2 and len(rss_d.entries) > int(context.args[1]):
        index1 = int(context.args[1])
        index2 = int(context.args[2]) + 1
    # update.effective_message.reply_text(rss_d.entries[0]['link'])
    # message.send(env.chatid, rss_d.entries[index], rss_d.feed.title, context)
    try:
        for entry in rss_d.entries[index1:index2]:
            logging.info(f"Sending {entry['link']}...")
            post = get_post_from_entry(entry, rss_d.feed.title)
            post.send_message(update.effective_chat.id)
    except Exception as e:
        logging.warning(f"Sending failed:", exc_info=e)
        update.effective_message.reply_text('ERROR: 内部错误')
        raise
    finally:
        logging.info('Test finished.')


def rss_monitor(context):
    update_flag = False
    for name, (feed_url, last_url) in db.read_all().items():
        try:
            rss_d = feed_get(feed_url)
        except IndexError:
            logging.warning(f'Feed {feed_url} fetch failed: feed error.')
            continue
        except requests.exceptions.RequestException:
            logging.warning(f'Feed {feed_url} fetch failed: network error.')
            continue
        except Exception as e:
            logging.warning(f'Feed {feed_url} fetch failed: ', exc_info=e)
            continue

        if last_url == rss_d.entries[0]['link']:
            logging.debug(f'Feed {feed_url} fetched, no new post.')
            continue

        logging.info(f'Feed {feed_url} updated!')
        update_flag = True
        # Workaround, avoiding deleted post causing the bot send all posts in the feed.
        # Known issues:
        # If a post was deleted while another post was sent between feed fetching duration,
        #  the latter won't be sent.
        # If your bot has stopped for too long that last sent post do not exist in current RSS feed,
        #  all posts won't be sent and last sent post will be reset to the newest post (though not sent).
        last_flag = False
        for entry in rss_d.entries[::-1]:
            if last_flag:
                logging.info(f"Sending {entry['link']}...")
                post = get_post_from_entry(entry, rss_d.feed.title)
                post.send_message(env.CHATID)

            if last_url == entry['link']:  # a sent post detected, the rest of posts in the list will be sent
                last_flag = True

        db.write(name, feed_url, str(rss_d.entries[0]['link']), True)  # update db



def main():
    logging.info(f"RSS-to-Telegram-Bot started!\n"
                 f"CHATID: {env.CHATID}\n"
                 f"MANAGER: {env.MANAGER}\n"
                 f"DELAY: {env.DELAY}s\n"
                 f"T_PROXY (for Telegram): {env.TELEGRAM_PROXY}\n"
                 f"R_PROXY (for RSS): {env.REQUESTS_PROXIES['all'] if env.REQUESTS_PROXIES else ''}")

    updater = Updater(token=env.TOKEN, use_context=True, request_kwargs={'proxy_url': env.TELEGRAM_PROXY})
    env.bot = updater.bot
    job_queue = updater.job_queue
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("add", cmd_rss_add, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("start", cmd_help, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("help", cmd_help, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("test", cmd_test, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("list", cmd_rss_list, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("remove", cmd_rss_remove, filters=~Filters.update.edited_message))

    commands = [telegram.BotCommand(command="add", description="+标题 RSS : 添加订阅"),
                telegram.BotCommand(command="remove", description="+标题 : 移除订阅"),
                telegram.BotCommand(command="list", description="列出数据库中的所有订阅，包括它们的标题和 RSS 源"),
                telegram.BotCommand(command="test", description="+RSS 编号(可选) : 从 RSS 源处获取一条 post"),
                telegram.BotCommand(command="help", description="发送这条消息")]
    try:
        updater.bot.set_my_commands(commands)
    except TelegramError as e:
        logging.warning(e.message)

    rss_monitor(updater)
    job_queue.run_repeating(rss_monitor, env.DELAY)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
