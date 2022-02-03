# 更新日志

## 多用户、国际化、改进的用户友好性和更多 (v2.0.0)

官方的公开 bot: [@RSStT_Bot](https://t.me/RSStT_Bot)

**这是一个重大的发布。它引入了一些重大变更，因此迁移至新版本需要手动完成。**  
**更新前请务必阅读[迁移指南](migration-guide-v2.zh.md)！**

### 重大变更

- 重写用户及订阅管理。Bot 现在可以被多个用户同时使用，且各个订阅都可以独立设置监视间隔。因此，环境变量 `CHATID` 和 `DELAY` 已经被弃用且不再有效。
    - 默认情况下，bot 将作为多用户机器人运行。如果你仍然希望限制 bot 仅为你服务，请按照[迁移指南](migration-guide-v2.zh.md)进行设置。
- 不再支持 Redis，仅支持 SQLite 和 PostgreSQL。

### 新特性

#### 亮点

- **多用户**: 任何用户都可以使用 bot，也可以在频道和群组中使用（除非环境变量 `MULTIUSER` 设置为 `0`）。
- **国际化**: Bot 现在支持多语言。目前，<u>英语 (English, en)</u>, <u>简体中文 (zh-Hans)</u> 和 <u>粤语 (廣東話, yue)</u> 已被支持。你可以参考 [翻译指南](translation-guide.md)，通过将 bot 翻译为你的语言，为项目作出贡献。
- **用户友好**: 你可以交互式地使用大部分命令，而不需要记住他们的语法。
- **HTTP 缓存**: Bot 已经实现了 [RFC7234](https://datatracker.ietf.org/doc/html/rfc7234) 中的必要部分，以“缓存”订阅源。这可以帮助 bot 所在的服务器和订阅源所在的服务器降低负载。

#### 其他新特性

- **自定义订阅**: 订阅可被自定义。目前，只有下面列出的设置可被自定义。其他设置正在开发中。
    - **暂停订阅**: 你可以暂停订阅。这样的话，你就可以让 bot 暂停发送订阅更新。
    - **静音订阅**: 你可以静音订阅。这样的话，当 bot 发送更新时，会发送静音消息。(你仍然会收到通知，但不会有声音)
    - **监视间隔**: 你可以更改订阅的监视间隔。
- **文档**: Bot 现在有了文档。请查阅 [docs]()。

### 增强

- **更好的订阅源历史管理**: 订阅源中的所有文章都会经过散列并储存，这样你就可以订阅几乎任何订阅源而不必担心遗漏文章。
- **更好的错误处理**: Bot 现在能更好地处理错误，它将会尝试恢复并重试。
- **更好的日志**: Bot 现在能更好地记录日志。
- **更佳的性能**: Bot 现在有着更佳的性能。
- **依赖更新**: 依赖已被更新至最新版本。潜在的漏洞已被修复。
- **代理绕过**: 如果设置了环境变量 `PROXY_BYPASS_PRIVATE` ，bot 会为私有网络绕过代理。在环境变量 `PROXY_BYPASS_DOMAINS` 中列出的域名也会被绕过。
- **Bug 修复**: 修复了一些 bug。

## 修复登录的仓促发布 (v1.6.1)

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

## 切换到 MTProto、OPML 支持和更多 (v1.6.0)

### 重大变更

- 与 Telegram 交互的库由使用 HTTP Bot API 的同步库 `python-telegram-bot` 改为使用 MTProto Bot API 的异步库 `telethon`
    - 这引入了 API key 的需求，程序已经内置了 7 个公开的 API key，通常情况下不应无法登入。如果无法登入，可以自己申请 API key (详见 [docker-compose.yml.sample](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/53f11a4739/docker-compose.yml.sample#L43) 中的说明)

### 新特性

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

## 完全重写的文章解码 (v1.5.0)

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

## 初始发布 (v1.0.0)

第一个公开发布
