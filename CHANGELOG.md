# Changelog

## v1.6.0

### en

#### BREAKING CHANGE

- Telegram bot library has been migrated from `python-telegram-bot` (which uses HTTP Bot API and is synchronous)
  to `telethon` (which uses MTProto Bot API and is asynchronous)
    - However, to use MTProto Bot API, an API key is needed. The bot has 7 built-in API keys (collected on the Internet)
      and in most cases it will not be unable to log in. But if so, please obtain your own API key (
      see [docker-compose.yml.sample](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/53f11a473933e620d707c9d15f6d48737bd7a982/docker-compose.yml.sample#L43)
      for details)

#### New features

- Thanks to the migration of Telegram bot library, bot can now connect to its DC directly, need not detour through the
  HTTP Bot API and keep polling to get new messages. Which makes the bot receive and reply messages more rapidly and
  lightweightedly. Even if the HTTP Bot API is down, the bot can still run unaffectedly. (more
  details: [Advantages of MTProto over Bot API](https://docs.telethon.dev/en/latest/concepts/botapi-vs-mtproto.html#advantages-of-mtproto-over-bot-api)
  , [MTProto vs HTTP Bot API](https://github.com/LonamiWebs/Telethon/wiki/MTProto-vs-HTTP-Bot-API))
- Support parsing more HTML elements
    - `<iframe>`
    - `<video><source><source>...</video>`
    - `<code>`
    - `<pre>`
- Support OPML importing and exporting
- Support sending too-long post via Telegraph (env var `TELEGRAPH_TOKEN` must be set)
- Support redis as db
    - Note: This is a workaround for deploying the bot on [railway.app](), will be dropped in the future
- Support arm64 (docker build)
- Support resending a message using a media relay server if Telegram cannot send a message with media due to Telegram
  server instability or network instability between media server and Telegram server
- Support colored logging
- `docker-compose.yml.sample`
- `/version` command to check bot version
- Automatically use proxy if global proxy (env var `SOCKS_PROXY`/`HTTP_PROXY`) set

#### Changes

- Assign feed monitoring tasks to every minute, instead of executing all at once each `DELAY`
    - Thus, env var `DELAY` can only be 60~3600
    - Note: env var `DELAY` will be deprecated in the future
- Recognize a post by its `guid`/`id` instead of `link`
- Simplify the output of `/list`
- Bump Python to 3.9 (docker build)
- Minor fixes

### zh-Hans

#### 重大变更

- 与 Telegram 交互的库由使用 HTTP Bot API 的同步库 `python-telegram-bot` 改为使用 MTProto Bot API 的异步库 `telethon`
    - 这引入了 API key 的需求，程序已经内置了 7 个公开的 API key，通常情况下不应无法登入。如果无法登入，可以自己申请 API key (
      详见 [docker-compose.yml.sample](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/53f11a473933e620d707c9d15f6d48737bd7a982/docker-compose.yml.sample#L43)
      中的说明)

#### 新功能

- 由于 Telegram bot 库的替换，bot 可以直接连接到 bot 所属的 DC，不需绕经 HTTP Bot API；也不需轮询获得消息更新，它在接收及发送消息方面都更为迅速，资源占用也更低； 即使 HTTP Bot API
  宕机，bot 也可以正常工作 (
  详见 [Advantages of MTProto over Bot API](https://docs.telethon.dev/en/latest/concepts/botapi-vs-mtproto.html#advantages-of-mtproto-over-bot-api)
  和 [MTProto vs HTTP Bot API](https://github.com/LonamiWebs/Telethon/wiki/MTProto-vs-HTTP-Bot-API))
- 支持更多元素的解析
    - `<iframe>`
    - `<video><source><source>...</video>`
    - `<code>`
    - `<pre>`
- 支持 OPML 导入导出
- 支持超长文章通过 Telegraph 发送 (必须先设置 `TELEGRAPH_TOKEN` 环境变量)
- 支持使用 redis 作为数据库
    - 注意：这是为了在 [railway.app]() 上部署而设计的变通解决方案，未来很可能丢弃
- 支持 arm64 (docker 构建)
- 支持在由于 Telegram 服务器不稳定或 Telegram 服务器与媒体服务器之间的网络连接不稳定而导致 Telegram 无法发出带有媒体的消息时，使用媒体反代服务器重新发送。
- Support colored logging
- `docker-compose.yml.sample`
- 用于检查 bot 版本的 `/version` 命令
- 如果设置了全局代理 (环境变量 `SOCKS_PROXY`/`HTTP_PROXY`)，会使用它们

#### 变更

- 将 feed 监视任务分配到每分钟，而不是每次 `DELAY` 一次性全部执行
    - 因此，环境变量 `DELAY` 将只能被设置为 60~3600
    - 注意：环境变量 `DELAY` 未来将被弃用
- 使用 `guid`/`id` 来辨识一个 post，而不是 `link`
- 简化了 `/list` 的输出
- 升级为 Python 3.9 (docker 构建)
- 次要的修复

## v1.5.0

### en

- Post parser is completely rewritten, more stable and can keep text formatting as much as possible
- GIF Support
- When the message is more than 10 pieces of media, send it in pieces
- Support video and pictures to be mixed in the same message arbitrarily
- Invalid media are no longer directly discarded, but attached to the end of the message as a link
- Automatically determine whether the title of the RSS feed is auto-filled, if so, omit the title
- Automatically show the author name
- Automatically replace emoji shortcodes with emoji
- Automatically replace emoji images with emoji or its description text
- When an image cannot be sent due to the instability of telegram api, the image server will be automatically replaced
  and resent
    - Only for Weibo images, non-Weibo images will be attached to the end of the message as a link
- Improve the text length counting method, no longer cause the message to be divided wrongly due to a long link URL
- Change the user-agent, because some websites have banned the UA of Requests
- Logging improvement

### zh-Hans

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

## v1.0.0

initial public release