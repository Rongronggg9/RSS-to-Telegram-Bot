# RSS to Telegram bot

![每日羊角观察](resources/GZMTR_Pill.png)

这是为 [每日羊角观察](https://t.me/GZMTR_Pill) 频道的附属频道 [羊角微博观察](https://t.me/GZMTR) 编写的 RSS bot。

本项目原是 [BoKKeR/RSS-to-Telegram-Bot](https://github.com/BoKKeR/RSS-to-Telegram-Bot) 的 fork ，考虑到改动较大，亦不打算往源项目发送 Pull Request ，因此已单独复制成独立的 Repository 。

## 功能

- 将 RSS 全文转发到 Telegram (包含所有图片)
- 转发时不丢失原有格式
- 转发失败时向 `MANAGER` 发送提示 (未设定则直接发送至 `CHATID` )

<img src="resources/example1.png" width = "449" height = "337" /><img src="resources/example2.png" width = "452" height = "656" />

## 已知的问题

- 针对 RSSHub 生成的微博 RSS 源编写，对于其他 RSS 源可能出现不可预料的问题
- 用于频道时，无法接受频道内的命令，需直接对 bot 在私人对话中发送命令
- 没有多用户功能，仅可向一个用户/频道 ( `CHATID` ) 推送 RSS
- bot 会响应所有人发送的命令 (将在未来修复)

## Usage

> RSS to Telegram bot
>
> After successfully adding a RSS link, the bot starts fetching the feed every 120 seconds. (This can be set)
> Titles are used to easily manage RSS feeds and need to contain only one word
>
> commands:
>
> **/add** title http://www(.)URL(.)com
>
> **/help** Shows this text
>
> **/remove** !Title! removes the RSS link
>
> **/list** Lists all the titles and the RSS links from the DB
>
> **/test** Inbuilt command that fetches a post from Reddits RSS.
>
> The current chatId is: *********

### Docker

For the docker image go to: https://hub.docker.com/r/rongronggg9/rss-to-telegram

```
docker run -d \
    -v [config path]:/app/config \
    -e DELAY=[delay] \
    -e TOKEN=[bot token] \
    -e CHATID=[target user chatid / @channelusername] \
    -e MANAGER=[bot manager chatid] \
    rongronggg9/rss-to-telegram
```

### Installation

Python 3.6+

```sh
pip install feedparser
pip install python-telegram-bot
html2text
```

A telegram bot is needed that the script will connect to. https://botsfortelegram.com/project/the-bot-father/
Running the script and typing in /help will reveal the current chatId, this needs to be set also in the script

1. Clone the script
2. Replace your chatID and Token on the top of the script.
3. Edit the delay. (seconds)
4. Save and run
5. Use the telegram commands to manage feeds

Warning! Without chatID the bot wont be able to send automated messages and will only be able to respond to messages.




## 源项目 README

![RSSTT](resources/rsstt.png)

A self-hosted telegram python bot that dumps posts from RSS feeds to a telegram chat. This script was created because all the third party services were unreliable.

![Image of help menu](https://bokker.github.io/telegram.png)

### Docker

For the docker image go to: https://hub.docker.com/r/bokker/rss.to.telegram/

### Installation

Python 3.X

```sh
pip install feedparser
pip install python-telegram-bot
```

A telegram bot is needed that the script will connect to. https://botsfortelegram.com/project/the-bot-father/
Running the script and typing in /help will reveal the current chatId, this needs to be set also in the script

1. Clone the script
2. Replace your chatID and Token on the top of the script.
3. Edit the delay. (seconds)
4. Save and run
5. Use the telegram commands to manage feeds

Warning! Without chatID the bot wont be able to send automated messages and will only be able to respond to messages.

# Usage

send /help to the bot to get this message:

> RSS to Telegram bot
>
> After successfully adding a RSS link, the bot starts fetching the feed every 60 seconds. (This can be set)
> Titles are used to easily manage RSS feeds and need to contain only one word
>
> commands:
>
> **/add** title http://www(.)URL(.)com
>
> **/help** Shows this text
>
> **/remove** !Title! removes the RSS link
>
> **/list** Lists all the titles and the RSS links from the DB
>
> **/test** Inbuilt command that fetches a post from Reddits RSS.
>
> The current chatId is: 20416xxxx

# Known issues

If the bot is set to for example 5 minutes and one feed manages to get 2 new posts before the bot can check. Only the newest post will show up on telegram.
(注：本项目已修复)

# Docker

```
docker create \
  --name=rss.to.telegram \
  -e DELAY=60 \
  -e TOKEN=InsertToken \
  -e CHATID=InsertChatID \
  -v /path/to/host/config:/config \
  --restart unless-stopped \
  bokker/rss.to.telegram
```
