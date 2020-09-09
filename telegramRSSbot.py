import feedparser
import logging
import sqlite3
import os
from telegram.ext import Updater, CommandHandler
from pathlib import Path
import message

Path("config").mkdir(parents=True, exist_ok=True)

# Docker env
if os.environ.get('TOKEN'):
    Token = os.environ['TOKEN']
    chatid = os.environ['CHATID']
    delay = int(os.environ['DELAY'])
else:
    Token = "X"
    chatid = "X"
    delay = 120

# TODO: only respond to commands sent by manager
if os.environ.get('MANAGER'):
    manager = os.environ['MANAGER']
else:
    manager = chatid

if Token == "X":
    print("Token not set!")

rss_dict = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)


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


# RSS________________________________________
def rss_load():
    # if the dict is not empty, empty it.
    if bool(rss_dict):
        rss_dict.clear()

    for row in sqlite_load_all():
        rss_dict[row[0]] = (row[1], row[2])


def cmd_rss_list(update, context):
    if bool(rss_dict) is False:

        update.effective_message.reply_text('数据库为空')
    else:
        for title, url_list in rss_dict.items():
            update.effective_message.reply_text(
                '标题: ' + title +
                '\nRSS 源: ' + url_list[0] +
                '\n最后检查的文章: ' + url_list[1])


def cmd_rss_add(update, context):
    # try if there are 2 arguments passed
    try:
        context.args[1]
    except IndexError:
        update.effective_message.reply_text(
            'ERROR: 格式需要为: /add 标题 RSS')
        raise
    # try if the url is a valid RSS feed
    try:
        rss_d = feedparser.parse(context.args[1])
        rss_d.entries[0]['title']
    except IndexError:
        update.effective_message.reply_text(
            'ERROR: 链接看起来不像是个 RSS 源，或该源不受支持')
        raise
    sqlite_write(context.args[0], context.args[1],
                 str(rss_d.entries[0]['link']))
    rss_load()
    update.effective_message.reply_text(
        '已添加 \n标题: %s\nRSS 源: %s' % (context.args[0], context.args[1]))


def cmd_rss_remove(update, context):
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


def cmd_help(update, context):
    print(context.chat_data)
    update.effective_message.reply_text(
        f"""RSS to Telegram bot (Weibo Ver.)
\n成功添加一个 RSS 源后, 机器人就会开始检查订阅，每 {delay} 秒一次。 (可修改)
\n标题为只是为管理 RSS 源而设的，可随意选取，但不可有空格。
\n命令:
*/help* : 发送这条消息
*/add 标题 RSS* : 添加订阅
*/remove 标题* : 移除订阅
*/list* : 列出数据库中的所有订阅，包括它们的标题和 RSS 源
*/test* : 内置命令，将会获取广州地铁的最新一条微博
\n您的 chatid 是: {update.message.chat.id}""",
        parse_mode='Markdown'
    )


def rss_monitor(context):
    update_flag = False
    for name, url_list in rss_dict.items():
        rss_d = feedparser.parse(url_list[0])
        if not rss_d.entries:
            # print(f'Get {name} feed failed!')
            print('x', end='')
            break
        if url_list[1] == rss_d.entries[0]['link']:
            print('-', end='')
        else:
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
                    message.send(chatid, entry['summary'], rss_d.feed.title, entry['link'], context)

                if url_list[1] == entry['link']:  # a sent post detected, the rest of posts in the list will be sent
                    last_flag = True

            sqlite_write(name, url_list[0], str(rss_d.entries[0]['link']), True)  # update db

    if update_flag:
        print('Updated.')
        rss_load()  # update rss_dict


def cmd_test(update, context):
    url = "https://rsshub.app/weibo/user/2612249974/1"
    rss_d = feedparser.parse(url)
    rss_d.entries[0]['link']
    # update.effective_message.reply_text(rss_d.entries[0]['link'])
    message.send(chatid, rss_d.entries[0]['summary'], rss_d.feed.title, rss_d.entries[0]['link'], context)


def init_sqlite():
    conn = sqlite3.connect('config/rss.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE rss (name text, link text, last text)''')


def main():
    updater = Updater(token=Token, use_context=True)
    job_queue = updater.job_queue
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("add", cmd_rss_add))
    dp.add_handler(CommandHandler("help", cmd_help))
    dp.add_handler(CommandHandler("test", cmd_test, ))
    dp.add_handler(CommandHandler("list", cmd_rss_list))
    dp.add_handler(CommandHandler("remove", cmd_rss_remove))

    # try to create a database if missing
    try:
        init_sqlite()
    except sqlite3.OperationalError:
        pass
    rss_load()

    job_queue.run_repeating(rss_monitor, delay)
    rss_monitor(updater)

    updater.start_polling()
    updater.idle()
    conn.close()


if __name__ == '__main__':
    main()
