# RSS to Telegram bot

**专为短动态类消息设计的 RSS Bot**

[![Build Status](https://img.shields.io/github/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/Publish%20Docker%20image)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)
[![Docker Pulls](https://img.shields.io/docker/pulls/rongronggg9/rss-to-telegram)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)
[![GitHub stars](https://img.shields.io/github/stars/Rongronggg9/Rss-to-Telegram-Bot?style=social)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/stargazers)

<a href="https://github.com/Rongronggg9/RSS-to-Telegram-Bot"><img src="https://rongronggg9.github.io/external-resources/RSS-to-Telegram-Bot/RSStT_icon.svg" width = "256" height = "256"  alt="RSStT_icon"/><a/>

本项目现改以 AGPLv3 许可证分发，这是为了将来的多用户功能准备的。

加入频道 [@RSStT_Channel](https://t.me/RSStT_Channel) 以获取更新资讯；加入群组 [@RSStT_Group](https://t.me/RSStT_Group) 以参与讨论或反馈问题。

## 新功能 in v1.5
> 注意：由于未来可能加入多用户功能而导致数据库及配置文件变更，请时常备份订阅列表（目前仅可通过 `/test` 备份）
- **文章解码完全重写，更加稳定及更加忠实还原原有格式**
    - **针对大量短动态类 RSS 源进行了测试**
    - **即使是长文 RSS 源，也可以正确处理**
- **支持 GIF**
- **消息多于 10 张媒体时支持分条发送**
- **支持视频与图片任意混合于同一条消息**
- 超限媒体不再直接丢弃，而是作为链接附加到消息末尾
- 自动判断 RSS 源的标题是否为自动填充，并自动选择是否略去标题
- 自动显示作者名
- 自动替换 emoji shortcodes 为 emoji
- 自动替换满足某些特征的表情图片为 emoji 或其描述文本
- 因 telegram api 不稳定而无法发出图片时，自动更换图床服务器重发
    - 仅限微博图源，非微博图源自动将所有媒体转为链接附加到消息末尾
- 改进文本长度计数方式，不再因为链接 url 过长而导致消息被提前分割
- 更改 user-agent，规避某些网站屏蔽 requests UA 的问题
- 改进的日志记录

## 功能

- 将 RSS 全文转发到 Telegram
    - 转发时尽量还原原有格式
    - 转发时自动将微博表情转化为同义 emoji
        - 仅限有同义 emoji 的微博表情
    - 超长消息自动分割
        - 多媒体消息编码后大于 1024 字，无图消息编码后大于 4096 字
    - 支持对 Telegram Bot API 和 RSS 订阅分别配置代理
- 支持含图消息转发
    - 至多 10 张图片
    - 自动缩小大于 5MB 或尺寸过大 (宽度 + 高度 <= 10000) 的图片
        - 仅限微博图源，~~其他图源的过大图片将被直接丢弃~~
- ~~(alpha)~~ 支持视频转发
- 转发失败时向 `MANAGER` 发送含错误信息的提示 **(未设定则直接发送至 `CHATID` )**
- **设定 `MANAGER` 时只会响应对应用户的命令 (未设定则只响应 `CHATID` 对应用户的命令)**

<img src="https://rongronggg9.github.io/external-resources/RSS-to-Telegram-Bot/example1.png" width = "500" alt="example1"/>
<img src="https://rongronggg9.github.io/external-resources/RSS-to-Telegram-Bot/example3.png" width = "500" alt="example3"/>

## 已知的问题

- ~~针对 RSSHub 生成的微博 RSS 源编写，对于其他 RSS 源可能出现不可预料的问题~~
    - ~~非微博图源的过大图片/视频将被直接丢弃~~
    - ~~图片至多 10 张 (考虑到微博已推出超九图功能，将在未来修复)~~
- 微博视频转发清晰度较低，~~若视频过大也将被直接丢弃~~
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
>
> **<u>/help</u>** : 发送这条消息
>
> **<u>/add</u> <u>标题</u> <u>RSS</u>** : 添加订阅
>
> **<u>/remove</u> <u>标题</u>** : 移除订阅
>
> **<u>/list</u>** : 列出数据库中的所有订阅，包括它们的标题和 RSS 源
>
> **<u>/test</u> <u>RSS</u> <u>编号起点(可选)</u> <u>编号终点(可选)</u>** : 从 RSS 源处获取一条 post (编号为 0-based, 不填或超出范围默认为 0，不填编号终点默认只获取一条 post)，或者直接用 `all` 获取全部
>
> 您的 chatid 是: 0123456789

### 准备

1. 前往 [@BotFather](https://t.me/BotFather) 创建一个 bot ，并记录下 token ，稍后填入 `TOKEN`
2. 获得您的 userid (可使用 [@userinfobot](https://t.me/userinfobot) 获取) 并记录下来，稍后填入 `CHATID`
    - 您也可使用一个频道来接收推送，此时 `CHATID` 格式为 `@channelusername` (不要忘记将 bot 添加到频道里!)
3. 获得管理员 (通常为您) 的 userid ，方法同上，稍后填入 `MANAGER`

### Docker

For the docker image go to: https://hub.docker.com/r/rongronggg9/rss-to-telegram

```sh
docker create \
    --name <container name> \
    --restart unless-stopped \
    -v </path/to/config>:/app/config \
    -e DELAY=<delay> \
    -e TOKEN=<bot_token> \
    -e CHATID=<target_user_userid / @channel_username> \
    -e MANAGER=<bot_manager_userid> \
    -e T_PROXY=<scheme://host:port/> \
    -e R_PROXY=<scheme://host:port/> \
    rongronggg9/rss-to-telegram
```

```sh
docker start <container name>
```

#### Note

- 如果想测试最新的功能，请将最后的 `rongronggg9/rss-to-telegram` 替换为 `rongronggg9/rss-to-telegram:dev`
- 尖括号`<>`表示需要用户填入自己的配置，尖括号`<>`本身不是命令的一部分
- 请务必设置`-v </path/to/config>:/app/config`，否则重新配置容器后订阅数据将丢失
- `T_PROXY` 对 Telegram Bot API 生效，`R_PROXY` 对 RSS 订阅生效，不使用代理可直接略去。考虑到 DNS 污染问题，请尽量使用 socks5 代理，并在填入的代理 URL 里使用`socks5h`
  而不是`socks5`，示例: `socks5h://127.0.0.1:1080/`
- 版本号没有特别意义，目前没有针对各版本号特别构建 docker 镜像

### Installation

Python 3.8+

Remember to replace `<arg>`, `<` and `>` should be deleted.

```sh
git clone https://github.com/Rongronggg9/RSS-to-Telegram-Bot.git
cd RSS-to-Telegram-Bot
pip install -r requirements.txt
export PYTHONUNBUFFERED 1
export DELAY <delay>
export TOKEN <bot token>
export CHATID <target user userid / @channel_username>
export MANAGER <bot manager userid>
export T_PROXY <scheme://host:port/>
export R_PROXY <scheme://host:port/>
python3 -u telegramRSSbot.py
```

## 备注

本项目原是 [BoKKeR/RSS-to-Telegram-Bot](https://github.com/BoKKeR/RSS-to-Telegram-Bot) 的 fork ，考虑到改动较大， 因此复制成独立的 repository 。