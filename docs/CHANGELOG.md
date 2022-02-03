# Changelog

## Multi-user, i18n, improved user-friendliness, and more (v2.0.0)

Official public bot: [@RSStT_Bot](https://t.me/RSStT_Bot)

**This is a major release. It introduces some major breaking changes. You must migrate to the new version manually.**  
**PLEASE READ THE [MIGRATION GUIDE](migration-guide-v2.md) BEFORE UPDATING!**

### BREAKING CHANGES

- User and subscription management has been rewritten. The bot now can be used by multiple users and each subscription may have its individual monitoring interval. Thus, env variables `CHATID` and `DELAY` are deprecated and of no use.
    - The default behavior is to run as a multi-user bot. If you still would like to limit the bot to serve you only, follow the [migration guide](migration-guide-v2.md).
- Redis support has been dropped. Only SQLite and PostgreSQL are supported.

### Additions

#### Highlights

- **Multi-user**: The bot can be used by any users, or in channels and groups (unless env variable `MULTIUSER` is set to `0`).
- **I18n**: The bot now supports multiple languages. Currently, <u>English (en)</u>, <u>Simplified Chinese (简体中文, zh-Hans)</u> and <u>Cantonese (廣東話, yue)</u> are supported. You can contribute by translating the bot to your language following the [translation guide](translation-guide.md).
- **User-friendly**: You can use most commands interactively, no need to remember their syntax.
- **HTTP Caching**: The bot has implemented the necessary parts of [RFC7234](https://datatracker.ietf.org/doc/html/rfc7234) to "cache" feeds. It can reduce the servers loads of both the bot and the feed provider.

#### Other additions

- **Customizing subscriptions**: Subscriptions can be customized. Currently, only the settings below can be customized. Other settings are WIP.
    - **Pausing**: You can deactivate a subscription. In this way, you can make the bot pause to send updates of it.
    - **Muting**: You can mute a subscription. In this way, when the bot sends updates of it, silent messages will be sent. (You will still receive notifications, but no sound.)
    - **Interval**: You can change the monitoring interval of a subscription.
- **Documentation**: The bot now has documentation. You can find it at [docs]().

### Enhancements

- **Better feed history management**: All posts in a feed are now hashed and stored. This allows you to subscribe to almost any feeds without missing posts.
- **Better error handling**: The bot now has better error handling. It will now try to recover from errors and retry.
- **Better logging**: The bot now has better logging.
- **Better performance**: The bot now has a better performance.
- **Dependence bump**: Dependencies have been bumped to the latest version. Potential security vulnerabilities have been fixed.
- **Proxy bypassing**: If env variable `PROXY_BYPASS_PRIVATE` is set, the bot will bypass proxy for private IPs. And will bypass proxy for domains listed in env variable `PROXY_BYPASS_DOMAINS`.
- **Bugfixes**: A few bugfixes.

## Rushed release to fix login (v1.6.1)

**This is a rushed release. It bumps the dependency `telethon` to the latest version. Please upgrade to this version immediately to avoid being unable to login due to the outdated dependency.**

The bot is currently being actively developed on the `multiuser` branch but has not been merged back yet to avoid introducing breaking changes too early. If you would like to try the multi-user version, there is a public demo [@RSStT_Bot](https://t.me/RSStT_Bot).

### Additions

- `.env` file support (only for manual execution, not for docker)
- Unescape HTML-escaped post title
- Use the title as the content of a post if the latter is of no text

### Enhancements

- Minor bug fixes
- Introduce some workarounds to avoid being flood-controlled frequently
- Introduce some deps to speed up HTTP requests

## Switching to MTProto, OPML support, and more (v1.6.0)

### BREAKING CHANGES

- The telegram bot library has been migrated from `python-telegram-bot` (which uses HTTP Bot API and is synchronous) to `telethon` (which uses MTProto Bot API and is asynchronous)
    - However, to use MTProto Bot API, an API key is needed. The bot has 7 built-in API keys (collected from the Internet) and in most cases, it should not be unable to log in. But if so, please obtain your own API key
      (see [docker-compose.yml.sample](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/53f11a4739/docker-compose.yml.sample#L43) for details)

### Additions

- Thanks to the migration of the Telegram bot library, the bot can now connect to its DC directly, need not detour through the HTTP Bot API, and keep polling to get new messages. Which makes the bot receive and reply to messages more rapidly and lightweight. Even if the HTTP Bot API is down, the bot can still run unaffectedly.
  (more details: [Advantages of MTProto over Bot API](https://docs.telethon.dev/en/latest/concepts/botapi-vs-mtproto.html#advantages-of-mtproto-over-bot-api), [MTProto vs HTTP Bot API](https://github.com/LonamiWebs/Telethon/wiki/MTProto-vs-HTTP-Bot-API))
- Support parsing more HTML elements
    - `<iframe>`
    - `<video><source><source>...</video>`
    - `<code>`
    - `<pre>`
- Support OPML importing and exporting
- Support sending too-long post via Telegraph (env variable `TELEGRAPH_TOKEN` must be set)
- Support using Redis as DB
    - Note: This is a workaround for deploying the bot on [railway.app](), will be dropped in the future
- Support arm64 (docker build)
- Support resending a message using a media relay server if Telegram cannot send a message with media due to Telegram server instability or network instability between the media server and Telegram server
- Support colored logging
- `docker-compose.yml.sample`
- `/version` command to check bot version
- Automatically use proxy if global proxy (env variable `SOCKS_PROXY`/`HTTP_PROXY`) set

### Enhancements

- Assign feed monitoring tasks to every minute, instead of executing all at once each `DELAY`
    - Thus, env variable `DELAY` can only be 60~3600
    - Note: env variable `DELAY` will be deprecated in the future
- Recognize a post by its `guid`/`id` instead of `link`
- Simplify the output of `/list`
- Bump Python to 3.9 (docker build)
- Minor fixes

## Complete rewrite of the post parser (v1.5.0)

- The Post parser is completely rewritten, more stable, and can keep text formatting as much as possible
- GIF Support
- When the message is more than 10 pieces of media, send it in pieces
- Support video and pictures to be mixed in the same message arbitrarily
- Invalid media are no longer directly discarded, but attached to the end of the message as a link
- Automatically determine whether the title of the RSS feed is auto-filled, if so, omit the title
- Automatically show the author-name
- Automatically replace emoji shortcodes with emoji
- Automatically replace emoji images with emoji or its description text
- When an image cannot be sent due to the instability of telegram API, the image server will be automatically replaced and resent
    - Only for Weibo images, non-Weibo images will be attached to the end of the message as a link
- Improve the text length counting method, no longer cause the message to be divided wrongly due to a long link URL
- Change the user-agent, because some websites have banned the UA of Requests
- Logging improvement

## Initial release (v1.0.0)

initial public release
