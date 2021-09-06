import feedparser
import logging
import sqlite3
import requests
import telegram
from requests.adapters import HTTPAdapter
from telegram.error import TelegramError
from telegram.ext import Updater, CommandHandler, Filters
from pathlib import Path
from io import BytesIO

import env
from post import Post, get_post_from_entry

Path("config").mkdir(parents=True, exist_ok=True)

rss_dict = {}

# TODO: use logging to log
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

logging.getLogger('apscheduler').setLevel(logging.WARNING)


# MANAGER
def is_manager(update):
    chat = update.message.chat
    userid = str(chat.id)
    username = chat.username
    if chat.last_name:
        name = chat.first_name + ' ' + chat.last_name
    else:
        name = chat.first_name
    command = update.message.text
    print(f'\n{name} ({username}/{userid}) attempted to use "{command}", ', end='')
    if env.manager != userid:
        update.effective_message.reply_text('您没有权限使用这个机器人。')
        print('forbade.')
        raise
    else:
        print('allowed.')


# SQLITE
def sqlite_connect():
    global conn
    conn = sqlite3.connect('config/rss.db', check_same_thread=False)


def sqlite_load_all():
    sqlite_connect()
    c = conn.cursor()
    c.execute('SELECT * FROM rss')
    rows = c.fetchall()
    conn.close()
    return rows


def sqlite_write(name, link, last, update=False):
    sqlite_connect()
    c = conn.cursor()
    p = [last, name]
    q = [name, link, last]
    if update:
        c.execute('''UPDATE rss SET last = ? WHERE name = ?;''', p)
    else:
        c.execute('''INSERT INTO rss('name','link','last') VALUES(?,?,?)''', q)
    conn.commit()
    conn.close()


# REQUESTS
def web_get(url):
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=1))
    session.mount('https://', HTTPAdapter(max_retries=1))

    response = session.get(url, timeout=(10, 10), proxies=env.requests_proxies)
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
            print('Feed ERROR:', e)
        raise IndexError(e)
    except requests.exceptions.RequestException as e:
        if verbose:
            update.effective_message.reply_text('ERROR: 网络超时')
            print('Network ERROR:', e)
        raise requests.exceptions.RequestException(e)
    return rss_d


# RSS________________________________________
def rss_load():
    # if the dict is not empty, empty it.
    if bool(rss_dict):
        rss_dict.clear()

    for row in sqlite_load_all():
        rss_dict[row[0]] = (row[1], row[2])


def cmd_rss_list(update: telegram.Update, context: telegram.ext.CallbackContext):
    is_manager(update)

    if bool(rss_dict) is False:
        update.effective_message.reply_text('数据库为空')
    else:
        for title, url_list in rss_dict.items():
            update.effective_message.reply_text(
                '标题: ' + title +
                '\nRSS 源: ' + url_list[0] +
                '\n最后检查的文章: ' + url_list[1])


def cmd_rss_add(update: telegram.Update, context: telegram.ext.CallbackContext):
    is_manager(update)

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
    sqlite_write(title, url, str(rss_d.entries[0]['link']))
    rss_load()
    update.effective_message.reply_text(
        '已添加 \n标题: %s\nRSS 源: %s' % (title, url))


def cmd_rss_remove(update: telegram.Update, context: telegram.ext.CallbackContext):
    is_manager(update)

    conn = sqlite3.connect('config/rss.db')
    c = conn.cursor()
    q = (context.args[0],)
    try:
        c.execute("DELETE FROM rss WHERE name = ?", q)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print('Error %s:' % e.args[0])
    rss_load()
    update.effective_message.reply_text("已移除: " + context.args[0])


def cmd_help(update: telegram.Update, context: telegram.ext.CallbackContext):
    is_manager(update)

    update.effective_message.reply_text(
        f"""RSS to Telegram bot \\(Weibo Ver\\.\\)
\n成功添加一个 RSS 源后, 机器人就会开始检查订阅，每 {env.delay} 秒一次。 \\(可修改\\)
\n标题为只是为管理 RSS 源而设的，可随意选取，但不可有空格。
\n命令:
__*/help*__ : 发送这条消息
__*/add*__ __*标题*__ __*RSS*__ : 添加订阅
__*/remove*__ __*标题*__ : 移除订阅
__*/list*__ : 列出数据库中的所有订阅，包括它们的标题和 RSS 源
__*/test*__ __*RSS*__ __*编号起点\\(可选\\)*__ __*编号终点\\(可选\\)*__: 从 RSS 源处获取一条 post \\(编号为 0\\-based, 不填或超出范围默认为 0\\)
\n您的 chatid 是: {update.message.chat.id}""",
        parse_mode='MarkdownV2'
    )


def cmd_test(update: telegram.Update, context: telegram.ext.CallbackContext):
    is_manager(update)

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
            post = get_post_from_entry(entry, rss_d.feed.title)
            post.send_message(update.effective_chat.id)
    except:
        update.effective_message.reply_text('ERROR: 内部错误')
        raise


def rss_monitor(context):
    update_flag = False
    for name, (feed_url, last_url) in rss_dict.items():
        try:
            rss_d = feed_get(feed_url)
        except IndexError:
            # print(f'Get {name} feed failed!')
            print('F', end='')
            continue
        except requests.exceptions.RequestException:
            print('N', end='')
            continue

        if last_url == rss_d.entries[0]['link']:
            print('-', end='')
            continue

        print('\nUpdating', name)
        update_flag = True
        # workaround, avoiding deleted weibo causing the bot send all posts in the feed
        # TODO: log recently sent weibo, so deleted weibo won't be harmful. (If a weibo was deleted while another
        #  weibo was sent between delay duration, the latter won't be fetched.) BTW, if your bot has stopped for
        #  too long that last fetched post do not exist in current RSS feed, all posts won't be fetched and last
        #  fetched post will be reset to the newest post (through it is not fetched).
        last_flag = False
        for entry in rss_d.entries[::-1]:  # push all messages not pushed
            if last_flag:
                # context.bot.send_message(chatid, rss_d.entries[0]['link'])
                print('\t- Pushing', entry['link'])
                # message.send(env.chatid, entry, rss_d.feed.title, context)
                post = get_post_from_entry(entry, rss_d.feed.title)
                post.send_message(env.chatid)

            if last_url == entry['link']:  # a sent post detected, the rest of posts in the list will be sent
                last_flag = True

        sqlite_write(name, feed_url, str(rss_d.entries[0]['link']), True)  # update db

    if update_flag:
        print('Updated.')
        rss_load()  # update rss_dict


def init_sqlite():
    conn = sqlite3.connect('config/rss.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE rss (name text, link text, last text)''')


def error_handler(update: telegram.Update, context: telegram.ext.CallbackContext):
    raise context.error


def main():
    print(f"""CHATID: {env.chatid}
MANAGER: {env.manager}
DELAY: {env.delay}s
T_PROXY (for Telegram): {env.telegram_proxy}
R_PROXY (for RSS): {env.requests_proxies['all'] if env.requests_proxies else ''}\n""")

    updater = Updater(token=env.token, use_context=True, request_kwargs={'proxy_url': env.telegram_proxy})
    env.bot = updater.bot
    job_queue = updater.job_queue
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("add", cmd_rss_add, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("start", cmd_help, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("help", cmd_help, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("test", cmd_test, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("list", cmd_rss_list, filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("remove", cmd_rss_remove, filters=~Filters.update.edited_message))
    if env.debug:
        dp.add_error_handler(error_handler)

    commands = [telegram.BotCommand(command="add", description="+标题 RSS : 添加订阅"),
                telegram.BotCommand(command="remove", description="+标题 : 移除订阅"),
                telegram.BotCommand(command="list", description="列出数据库中的所有订阅，包括它们的标题和 RSS 源"),
                telegram.BotCommand(command="test", description="+RSS 编号(可选) : 从 RSS 源处获取一条 post"),
                telegram.BotCommand(command="help", description="发送这条消息")]
    try:
        updater.bot.set_my_commands(commands)
    except TelegramError as e:
        logging.warning(e.message)

    # try to create a database if missing
    try:
        init_sqlite()
    except sqlite3.OperationalError:
        pass
    rss_load()

    rss_monitor(updater)
    job_queue.run_repeating(rss_monitor, env.delay)

    updater.start_polling()
    updater.idle()
    conn.close()


if __name__ == '__main__':
    main()
