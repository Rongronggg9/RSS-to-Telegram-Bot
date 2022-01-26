# Changelog

[简体中文版](CHANGELOG_ZH.md)

## Multi-user, i18n, improved user friendliness and more (v2.0.0)

**This is a major release. It introduces some major breaking changes. You must migrate to the new version manually.**  
**PLEASE READ THE MIGRATION GUIDE BEFORE UPDATING!**

### BREAKING CHANGES

- User and subscription management has been rewritten. The bot now can be used by multiple users and each subscription may have its individual monitoring interval. Thus, env var `CHATID` and `DELAY` are deprecated and of no use.
    - The default behavior is to run as a multi-user bot. If you still would like to limit the bot to serve you only, follow the guide above.
- Redis support has been dropped. Only SQLite and PostgreSQL are supported.

### Additions

#### Highlights

- **Multi-user**: The bot can be used by any users, or in channels and groups (unless env var `MULTIUSER` is set to `0`).
- **I18n**: The bot now supports multiple languages. Currently, <u>English (en)</u>, <u>Simplified Chinese (简体中文, zh-Hans)</u> and <u>Cantonese (廣東話, zh-yue)</u> are supported. You can contribute by translating the bot to your language following the [translation guide](translation-guide.md).
- **User-friendly**: You can use most commands interactively, no need to remember their syntax.
- **HTTP Caching**: The bot has implemented the necessary parts of [RFC7234](https://datatracker.ietf.org/doc/html/rfc7234) to "cache" feeds. It can reduce the servers loads of both the bot and the feed provider.

#### Other additions

- **Pausing subscriptions**: You can deactivate a subscription. By this way, you can make the bot pause to send updates of it.
- **Muting subscriptions**: You can mute a subscription. By this way, you can make the bot mute to send updates of it.
- **Documentation**: The bot now has documents. You can find it at [docs]().

## Rushed release to fix login (v1.6.1)

**This is a rushed release. It bumps the dependency `telethon` to the latest version. Please upgrade to this version immediately to avoid being unable to login due to the outdated dependency.**

The bot is currently being actively developed on the `multiuser` branch, but has not been merged back yet to avoid introducing breaking changes too early. If you would like to try the multi-user version, there is a public demo [@RSStT_Bot](https://t.me/RSStT_Bot) .

### Additions

- `.env` file support (only for manual execution, not for docker)
- Unescape HTML-escaped post title
- Use the title as the content of a post if the latter is of no text

### Enhancements

- Minor bug fixes
- Introduce some workarounds to avoid being flood-controlled frequently
- Introduce some deps to speedup HTTP requests

## Switching to MTProto, OPML support and more (v1.6.0)

### BREAKING CHANGES

- Telegram bot library has been migrated from `python-telegram-bot` (which uses HTTP Bot API and is synchronous) to `telethon` (which uses MTProto Bot API and is asynchronous)
    - However, to use MTProto Bot API, an API key is needed. The bot has 7 built-in API keys (collected from the Internet) and in most cases it should not be unable to log in. But if so, please obtain your own API key
      (see [docker-compose.yml.sample](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/53f11a4739/docker-compose.yml.sample#L43) for details)

### Additions

- Thanks to the migration of Telegram bot library, bot can now connect to its DC directly, need not detour through the HTTP Bot API and keep polling to get new messages. Which makes the bot receive and reply messages more rapidly and lightweightedly. Even if the HTTP Bot API is down, the bot can still run unaffectedly.
  (more details: [Advantages of MTProto over Bot API](https://docs.telethon.dev/en/latest/concepts/botapi-vs-mtproto.html#advantages-of-mtproto-over-bot-api), [MTProto vs HTTP Bot API](https://github.com/LonamiWebs/Telethon/wiki/MTProto-vs-HTTP-Bot-API))
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
- Support resending a message using a media relay server if Telegram cannot send a message with media due to Telegram server instability or network instability between media server and Telegram server
- Support colored logging
- `docker-compose.yml.sample`
- `/version` command to check bot version
- Automatically use proxy if global proxy (env var `SOCKS_PROXY`/`HTTP_PROXY`) set

### Enhancements

- Assign feed monitoring tasks to every minute, instead of executing all at once each `DELAY`
    - Thus, env var `DELAY` can only be 60~3600
    - Note: env var `DELAY` will be deprecated in the future
- Recognize a post by its `guid`/`id` instead of `link`
- Simplify the output of `/list`
- Bump Python to 3.9 (docker build)
- Minor fixes

## Complete rewrite of the post parser (v1.5.0)

- Post parser is completely rewritten, more stable and can keep text formatting as much as possible
- GIF Support
- When the message is more than 10 pieces of media, send it in pieces
- Support video and pictures to be mixed in the same message arbitrarily
- Invalid media are no longer directly discarded, but attached to the end of the message as a link
- Automatically determine whether the title of the RSS feed is auto-filled, if so, omit the title
- Automatically show the author name
- Automatically replace emoji shortcodes with emoji
- Automatically replace emoji images with emoji or its description text
- When an image cannot be sent due to the instability of telegram api, the image server will be automatically replaced and resent
    - Only for Weibo images, non-Weibo images will be attached to the end of the message as a link
- Improve the text length counting method, no longer cause the message to be divided wrongly due to a long link URL
- Change the user-agent, because some websites have banned the UA of Requests
- Logging improvement

## Initial release (v1.0.0)

initial public release
