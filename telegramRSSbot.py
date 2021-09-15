import functools
import logging
import telegram
from telegram.error import TelegramError
from telegram.ext import Updater, CommandHandler, Filters, MessageHandler
from pathlib import Path
from typing import Optional
from datetime import datetime

import env
from feed import Feed, Feeds

# global var placeholder
feeds: Optional[Feeds] = None

# initial
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
                logging.info(f'Refused {user_fullname} ({user_id}) to use {command} in '
                             f'{message.chat.title} ({message.chat.id}).')
                return

            user_status = update.effective_chat.get_member(user_id).status
            if user_id != GROUP and user_status not in ('administrator', 'creator'):
                update.effective_message.reply_text('此命令只可由群管理员使用。\n'
                                                    'This command can be only used by an administrator.')
                logging.info(
                    f'Refused {user_fullname} ({user_id}, {user_status}) to use {command} '
                    f'in {message.chat.title} ({message.chat.id}).')
                return
            logging.info(
                f'Allowed {user_fullname} ({user_id}, {user_status}) to use {command} '
                f'in {message.chat.title} ({message.chat.id}).')
            return func(update, context, *args, **kwargs)
        return

    return wrapper


@permission_required(only_manager=True)
def cmd_list(update: telegram.Update, context: telegram.ext.CallbackContext):
    empty_flags = True
    for feed in feeds:
        empty_flags = False
        update.effective_message.reply_text(f'标题: {feed.name}\nRSS 源: {feed.link}\n最后检查的文章: {feed.last}')
    if empty_flags:
        update.effective_message.reply_text('数据库为空')


@permission_required(only_manager=True)
def cmd_add(update: telegram.Update, context: telegram.ext.CallbackContext):
    # try if there are 2 arguments passed
    try:
        title = context.args[0]
        url = context.args[1]
    except IndexError:
        update.effective_message.reply_text('ERROR: 格式需要为: /add 标题 RSS')
        return
    if feeds.add_feed(name=title, link=url, uid=update.effective_chat.id):
        update.effective_message.reply_text('已添加 \n标题: %s\nRSS 源: %s' % (title, url))


@permission_required(only_manager=True)
def cmd_remove(update: telegram.Update, context: telegram.ext.CallbackContext):
    if not context.args:
        update.effective_message.reply_text("ERROR: 请指定订阅名")
        return
    name = context.args[0]
    if feeds.del_feed(name):
        update.effective_message.reply_text("已移除: " + name)
        return
    update.effective_message.reply_text("ERROR: 未能找到这个订阅名: " + name)


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

        if len(context.args) > 1 and context.args[1] == 'all':
            start = 0
            end = None
        elif len(context.args) == 2:
            start = int(context.args[1])
            end = int(context.args[1]) + 1
        elif len(context.args) == 3:
            start = int(context.args[1])
            end = int(context.args[2]) + 1
        else:
            start = 0
            end = 1
    except (IndexError, ValueError):
        update.effective_message.reply_text('ERROR: 格式需要为: /test RSS 条目编号起点(可选) 条目编号终点(可选)')
        return

    Feed(link=url).send(update.effective_chat.id, start, end)
    logging.info('Test finished.')


@permission_required(only_manager=True)
def cmd_import(update: telegram.Update, context: telegram.ext.CallbackContext):
    update.effective_message.reply_text('请发送需要导入的 OPML 文档',
                                        reply_markup=telegram.ForceReply(selective=True,
                                                                         input_field_placeholder='OPML'))


def cmd_export(update: telegram.Update, context: telegram.ext.CallbackContext):
    opml_file = feeds.export_opml()
    update.effective_message.reply_document(opml_file,
                                            filename=f"RSStT_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.opml")


@permission_required(only_manager=True)
def opml_import(update: telegram.Update, context: telegram.ext.CallbackContext):
    if update.effective_chat.type != 'private' and update.effective_message.reply_to_message.from_user.id != env.bot.id:
        return
    try:
        opml_file = update.effective_message.document.get_file(timeout=7).download_as_bytearray()
    except telegram.error.TelegramError as e:
        update.effective_message.reply_text('ERROR: 获取文件失败', quote=True)
        logging.warning(f'Failed to get opml file: ' + e.message)
        return
    update.effective_message.reply_text('正在处理中...\n'
                                        '如订阅较多或订阅所在的服务器太慢，将会处理较长时间，请耐心等待', quote=True)
    logging.info(f'Got an opml file.')
    res = feeds.import_opml(opml_file)
    if res is None:
        update.effective_message.reply_text('ERROR: 解析失败或文档不含订阅', quote=True)
        return

    valid = res['valid']
    invalid = res['invalid']
    import_result = '<b>导入结果</b>\n\n' \
                    + ('导入成功：\n' if valid else '') \
                    + '\n'.join(f'<a href="{feed.url}">{feed.title}</a>' for feed in valid) \
                    + ('\n\n' if valid and invalid else '') \
                    + ('导入失败：\n' if invalid else '') \
                    + '\n'.join(f'<a href="{feed.url}">{feed.title}</a>' for feed in invalid)
    update.effective_message.reply_html(import_result, quote=True)


def rss_monitor(updater):
    feeds.monitor()


def main():
    global feeds
    logging.info(f"RSS-to-Telegram-Bot started!\n"
                 f"CHATID: {env.CHATID}\n"
                 f"MANAGER: {env.MANAGER}\n"
                 f"DELAY: {env.DELAY}s\n"
                 f"T_PROXY (for Telegram): {env.TELEGRAM_PROXY}\n"
                 f"R_PROXY (for RSS): {env.REQUESTS_PROXIES['all'] if env.REQUESTS_PROXIES else ''}\n"
                 f"DATABASE: {'Redis' if env.REDIS_HOST else 'Sqlite'}")

    updater: telegram.ext.Updater = Updater(token=env.TOKEN, use_context=True,
                                            request_kwargs={'proxy_url': env.TELEGRAM_PROXY})
    env.bot = updater.bot
    job_queue: telegram.ext.JobQueue = updater.job_queue
    dp: telegram.ext.Dispatcher = updater.dispatcher

    dp.add_handler(CommandHandler("add", callback=cmd_add, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("start", callback=cmd_help, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("help", callback=cmd_help, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("test", callback=cmd_test, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("list", callback=cmd_list, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("remove", callback=cmd_remove, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("import", callback=cmd_import, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(CommandHandler("export", callback=cmd_export, run_async=True,
                                  filters=~Filters.update.edited_message))
    dp.add_handler(MessageHandler(callback=opml_import, run_async=True,
                                  filters=Filters.document & ~Filters.update.edited_message & (
                                          Filters.reply | Filters.chat_type.private)))

    commands = [telegram.BotCommand(command="add", description="+标题 RSS : 添加订阅"),
                telegram.BotCommand(command="remove", description="+标题 : 移除订阅"),
                telegram.BotCommand(command="list", description="列出数据库中的所有订阅，包括它们的标题和 RSS 源"),
                telegram.BotCommand(command="test", description="+RSS 编号(可选) : 从 RSS 源处获取一条 post"),
                telegram.BotCommand(command="import", description="导入订阅"),
                telegram.BotCommand(command="export", description="导出订阅"),
                telegram.BotCommand(command="help", description="发送这条消息")]
    try:
        updater.bot.set_my_commands(commands)
    except TelegramError as e:
        logging.warning('Set command error: ' + e.message)

    feeds = Feeds()

    job_queue.run_repeating(rss_monitor, env.DELAY)

    updater.start_polling()
    rss_monitor(updater)
    updater.idle()


if __name__ == '__main__':
    main()
