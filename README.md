# RSS to Telegram Bot

**关心你的阅读体验的 Telegram RSS 机器人**

[![Build Status](https://img.shields.io/github/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/Publish%20Docker%20image)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)
[![Docker Pulls](https://img.shields.io/docker/pulls/rongronggg9/rss-to-telegram)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)
[![GitHub stars](https://img.shields.io/github/stars/Rongronggg9/Rss-to-Telegram-Bot?style=social)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/stargazers)

[@RSStT_Bot](https://t.me/RSStT_Bot) (w/ English l10n)

<a href="https://t.me/RSStT_Bot"><img src="https://rongronggg9.github.io/external-resources/RSS-to-Telegram-Bot/RSStT_icon.svg" width = "256" height = "256"  alt="RSStT_icon"/><a/>

[更新日志 CHANGELOG](CHANGELOG.md)

使用公共 demo [@RSStT_Bot](https://t.me/RSStT_Bot) 以体验本机器人；加入频道 [@RSStT_Channel](https://t.me/RSStT_Channel)
以获取更新资讯；加入群组 [@RSStT_Group](https://t.me/RSStT_Group) 以参与讨论或反馈问题。

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot%2Ftree%2Fdev&plugins=redis&envs=TOKEN%2CCHATID%2CMANAGER%2CDELAY&optionalEnvs=DELAY&TOKENDesc=%E4%BD%A0%E5%9C%A8+%40BotFather+%E7%94%B3%E8%AF%B7%E5%88%B0%E7%9A%84+bot+%E7%9A%84+token&CHATIDDesc=%E4%BD%A0%E7%9A%84+userid%EF%BC%88%E7%BA%AF%E6%95%B0%E5%AD%97%EF%BC%8C%E4%BB%8E+%40userinfobot%EF%BC%89%E8%8E%B7%E5%8F%96%EF%BC%9B%E6%88%96%E8%80%85%E9%9C%80%E8%A6%81%E6%8E%A8%E9%80%81%E5%88%B0%E7%9A%84%E9%A2%91%E9%81%93%E7%94%A8%E6%88%B7%E5%90%8D%EF%BC%88%E6%A0%BC%E5%BC%8F%EF%BC%9A%40channel%EF%BC%89&MANAGERDesc=%E4%BD%A0%E7%9A%84+userid&DELAYDesc=%E9%97%B4%E9%9A%94%E5%A4%9A%E4%B9%85%E6%A3%80%E6%9F%A5%E4%B8%80%E6%AC%A1%E8%AE%A2%E9%98%85%E6%9B%B4%E6%96%B0%EF%BC%88%E5%8D%95%E4%BD%8D%EF%BC%9A%E7%A7%92%EF%BC%89&referralCode=PEOFMi)

[Railway 部署教程](https://telegra.ph/%E9%80%9A%E8%BF%87-Railway-%E9%83%A8%E7%BD%B2-RSS-to-Telegram-Bot-09-13)

## 功能

- 将 RSS 全文发送到 Telegram
    - 还原原有格式
    - 自动判断 RSS 源的标题是否为自动填充，并自动选择是否略去标题
    - 自动显示作者名
    - 将微博表情或 emoji shortcodes 转化为 emoji
        - 仅限有同义 emoji 的微博表情
    - 超长消息自动分割
        - 如果配置了 Telegraph，则会自动通过 Telegraph 发送
    - 支持对 Telegram Bot API 和 RSS 订阅分别配置代理
- 支持含媒体消息转发
    - 至多 10 个媒体，可以是图片或视频
    - 自动缩小大于 5MB 或尺寸过大 (宽度 + 高度 <= 10000) 的图片
        - 仅限微博图源，其他图源的图片将被转为链接附加至消息末尾
- 支持 OPML 导入导出
- 转发失败时向 `MANAGER` 发送含错误信息的提示 **(未设定则直接发送至 `CHATID` )**
- **设定 `MANAGER` 时只会响应对应用户的命令 (未设定则只响应 `CHATID` 对应用户的命令)**

<img src="https://rongronggg9.github.io/external-resources/RSS-to-Telegram-Bot/example1.png" width = "500" alt="example1"/>
<img src="https://rongronggg9.github.io/external-resources/RSS-to-Telegram-Bot/example3.png" width = "500" alt="example3"/>

## 已知的问题

- 用于频道时，无法接受频道内的命令，需直接对 bot 在私人对话中发送命令
    - **必须设定 `MANAGER` 并使用其对应的用户操作，否则不会响应**
- 没有多用户功能，仅可向一个用户/频道 ( `CHATID` ) 推送 RSS

## 使用

> [RSS to Telegram bot，专为短动态类消息设计的 RSS Bot。](https://github.com/Rongronggg9/RSS-to-Telegram-Bot)
>
> 成功添加一个 RSS 源后, 机器人就会开始检查订阅，每 300 秒一次。 (可修改)
>
> 标题为只是为管理 RSS 源而设的，可随意选取，但不可有空格。
>
> 命令:  
> **<u>/add</u>** **<u>标题</u>** **<u>RSS</u>** : 添加订阅  
> **<u>/remove</u>** **<u>标题</u>** : 移除订阅  
> **<u>/list</u>** : 列出数据库中的所有订阅  
> **<u>/test</u>** **<u>RSS</u>** **<u>编号起点(可选)</u>** **<u>编号终点(可选)</u>** : 从 RSS 源处获取一条 post (编号为 0-based, 不填或超出范围默认为 0，不填编号终点默认只获取一条 post)，或者直接用 all 获取全部  
> **<u>/import</u>** : 导入订阅  
> **<u>/export</u>** : 导出订阅  
> **<u>/version</u>** : 查看版本  
> **<u>/help</u>** : 发送这条消息
>
> 您的 chatid 是: 0123456789

### 准备

1. 前往 [@BotFather](https://t.me/BotFather) 创建一个 bot ，并记录下 token ，稍后填入 `TOKEN`
2. 获得您的 userid (可使用 [@userinfobot](https://t.me/userinfobot) 获取) 并记录下来，稍后填入 `CHATID`
    - 您也可使用一个频道来接收推送，此时 `CHATID` 格式为 `@channelusername` (不要忘记将 bot 添加到频道里!)
3. 获得管理员 (通常为您) 的 userid ，方法同上，稍后填入 `MANAGER`

### Docker Compose

For the docker images go to: https://hub.docker.com/r/rongronggg9/rss-to-telegram

```sh
mkdir rsstt
cd rsstt
wget https://raw.githubusercontent.com/Rongronggg9/RSS-to-Telegram-Bot/master/docker-compose.yml.sample -O docker-compose.yml
vi docker-compose.yml  # 自行按文件中的注释修改 docker-compose.yml
docker-compose up -d
```

### Manual Execution

Python 3.8+

```sh
git clone https://github.com/Rongronggg9/RSS-to-Telegram-Bot.git
cd RSS-to-Telegram-Bot
pip3 install -r requirements.txt
vi .env # 参照 docker-compose.yml 设置环境变量
python3 -u telegramRSSbot.py
```

## 备注

本项目原是 [BoKKeR/RSS-to-Telegram-Bot](https://github.com/BoKKeR/RSS-to-Telegram-Bot) 的 fork ，目前除了数据库和命令名已经没有任何相像的地方了。