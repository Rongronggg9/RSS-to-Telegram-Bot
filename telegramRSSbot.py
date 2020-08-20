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

        update.effective_message.reply_text("The database is empty")
    else:
        for title, url_list in rss_dict.items():
            update.effective_message.reply_text(
                "Title: " + title +
                "\nrss url: " + url_list[0] +
                "\nlast checked article: " + url_list[1])


def cmd_rss_add(update, context):
    # try if there are 2 arguments passed
    try:
        context.args[1]
    except IndexError:
        update.effective_message.reply_text(
            "ERROR: The format needs to be: /add title http://www.URL.com")
        raise
    # try if the url is a valid RSS feed
    try:
        rss_d = feedparser.parse(context.args[1])
        rss_d.entries[0]['title']
    except IndexError:
        update.effective_message.reply_text(
            "ERROR: The link does not seem to be a RSS feed or is not supported")
        raise
    sqlite_write(context.args[0], context.args[1],
                 str(rss_d.entries[0]['link']))
    rss_load()
    update.effective_message.reply_text(
        "added \nTITLE: %s\nRSS: %s" % (context.args[0], context.args[1]))


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
    update.effective_message.reply_text("Removed: " + context.args[0])


def cmd_help(update, context):
    print(context.chat_data)
    update.effective_message.reply_text(
        f"""RSS to Telegram bot
\nAfter successfully adding a RSS link, the bot starts fetching the feed every {delay} seconds. (This can be set)
\nTitles are used to easily manage RSS feeds and need to contain only one word
\ncommands:
/help : Posts this help message.
/add title http://www(.)RSS-URL(.)com
/remove !Title! : Removes the RSS link.
/list : Lists all the titles and the RSS links from the DB.
/test : Inbuilt command that fetches a post from Reddits RSS.
\nThe current chatId is: {update.message.chat.id}"""
    )


def rss_monitor(context):
    update_flag = False
    for name, url_list in rss_dict.items():
        rss_d = feedparser.parse(url_list[0])
        if rss_d.entries and url_list[1] != rss_d.entries[0]['link']:
            print('Updating', name)
            update_flag = True
            for entry in rss_d.entries:  # push all messages not pushed
                if url_list[1] == entry['link']:  # finish if current message already sent
                    break
                # context.bot.send_message(chatid, rss_d.entries[0]['link'])
                print('\tPushing', entry['link'])
                message.send(chatid, entry['summary'], rss_d.feed.title, entry['link'], context)

            sqlite_write(name, url_list[0], str(rss_d.entries[0]['link']), True)  # update db

    if update_flag:
        print('Updated.')
        rss_load()  # update rss_dict


def cmd_test(update, context):
    url = "https://uneasy.win/rss/weibo/user/2612249974/1"
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

    rss_monitor(updater)
    job_queue.run_repeating(rss_monitor, delay)

    updater.start_polling()
    updater.idle()
    conn.close()


if __name__ == '__main__':
    main()
