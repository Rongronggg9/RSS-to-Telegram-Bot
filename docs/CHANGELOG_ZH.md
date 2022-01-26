# 更新日志

[English version](CHANGELOG.md)


## v2.0.0

## v1.6.1

**这是一个仓促的发布。它将依赖 `telethon` 升级到了最新版本。请立即升级到这个版本以免由于依赖过时而无法登录。**

机器人正在 `multiuser` 分支上被活跃开发，但尚未被合并回来，以免过早引入重大变更。如果你想要尝试多用户版本，这里有一个公开的 demo [@RSStT_Bot](https://t.me/RSStT_Bot) 。

### 新特性

- `.env` 文件支持 (仅在手动执行时支持，不支持 docker)
- 反转义受到 HTML 转义的文章标题
- 当文章内容不含有文本时，将标题作为文章的内容

### 增强

- 一些小的错误修复
- 引入了一些变通解决方案以免频繁受到泛洪控制
- 引入了一些依赖以加速 HTTP 请求

## v1.6.0

### 重大变更

- 与 Telegram 交互的库由使用 HTTP Bot API 的同步库 `python-telegram-bot` 改为使用 MTProto Bot API 的异步库 `telethon`
    - 这引入了 API key 的需求，程序已经内置了 7 个公开的 API key，通常情况下不应无法登入。如果无法登入，可以自己申请 API key (详见 [docker-compose.yml.sample](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/53f11a4739/docker-compose.yml.sample#L43) 中的说明)

### 新功能

- 由于 Telegram bot 库的替换，bot 可以直接连接到 bot 所属的 DC，不需绕经 HTTP Bot API；也不需轮询获得消息更新，它在接收及发送消息方面都更为迅速，资源占用也更低； 即使 HTTP Bot API 宕机，bot 也可以正常工作 (详见 [Advantages of MTProto over Bot API](https://docs.telethon.dev/en/latest/concepts/botapi-vs-mtproto.html#advantages-of-mtproto-over-bot-api) 和 [MTProto vs HTTP Bot API](https://github.com/LonamiWebs/Telethon/wiki/MTProto-vs-HTTP-Bot-API))
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
- 支持日志着色
- `docker-compose.yml.sample`
- 用于检查 bot 版本的 `/version` 命令
- 如果设置了全局代理 (环境变量 `SOCKS_PROXY`/`HTTP_PROXY`)，会使用它们

### 增强

- 将 feed 监视任务分配到每分钟，而不是每次 `DELAY` 一次性全部执行
    - 因此，环境变量 `DELAY` 将只能被设置为 60~3600
    - 注意：环境变量 `DELAY` 未来将被弃用
- 使用 `guid`/`id` 来辨识一个 post，而不是 `link`
- 简化了 `/list` 的输出
- 升级为 Python 3.9 (docker 构建)
- 次要的修复

## v1.5.0

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

第一个公开发布
