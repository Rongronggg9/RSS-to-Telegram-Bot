<a href="https://t.me/RSStT_Bot"><img width="150" height="150" align="left" style="float: left; margin: 0 10px 0 0;" alt="RSStT icon" src="docs/resources/RSStT_icon.svg"/><a/>

# [RSS to Telegram Bot](https://t.me/RSStT_Bot)

**A Telegram RSS bot that cares about your reading experience**

[简体中文 README](README.zh.md)

[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/Rongronggg9/RSS-to-Telegram-Bot?logo=git&label=commit)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/commits)
[![Translating status](https://img.shields.io/weblate/progress/rss-to-telegram-bot?logo=weblate&color=informational)](https://hosted.weblate.org/engage/rss-to-telegram-bot/)
[![Code quality](https://img.shields.io/codefactor/grade/github/Rongronggg9/RSS-to-Telegram-Bot?logo=codefactor)](https://www.codefactor.io/repository/github/rongronggg9/rss-to-telegram-bot)
[![GitHub stars](https://img.shields.io/github/stars/Rongronggg9/Rss-to-Telegram-Bot?style=social)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Rongronggg9/RSS-to-Telegram-Bot?style=social)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/fork)

[![Telegram bot](https://img.shields.io/badge/bot-%40RSStT__Bot-229ed9?logo=telegram&style=for-the-badge)](https://t.me/RSStT_Bot)
[![Telegram group](https://img.shields.io/badge/chat-%40RSStT__Group-229ed9?logo=telegram&style=for-the-badge)](https://t.me/RSStT_Group)
[![Telegram channel](https://img.shields.io/badge/channel-%40RSStT__Channel-229ed9?logo=telegram&style=for-the-badge)](https://t.me/RSStT_Channel)

| [CHANGELOG] | [FAQ] | [Documentation] | [Channels Using RSStT] |
|:-----------:|:-----:|-----------------|:----------------------:|

[CHANGELOG]: docs/CHANGELOG.md

[FAQ]: docs/FAQ.md

[Documentation]: docs

[Channels Using RSStT]: docs/channels-using-rsstt.md


**Important**: If you have your own RSStT bot (v1), please read the [migration guide](docs/migration-guide-v2.md) to learn how to migrate to v2.

## Highlights

- Multi-user
- I18n
    - English, Chinese, Cantonese, Italian, and [more](docs/translation-guide.md)!
- The content of the posts of an RSS feed will be sent to Telegram
    - Keep rich-text format
    - Keep media (customizable)
        - Images, Videos, and Audio both in the post content and enclosure; Documents in the post enclosure
        - Long images will be sent as files to prevent Telegram from compressing the image and making it unreadable
        - Drop annoying icons, they break the reading experience
    - Automatically replace emoji shortcodes with emoji
    - Automatically replace emoji images with emoji or its description text
    - Automatically determine whether the title of the RSS feed is auto-filled, if so, omit the title (customizable)
    - Automatically show the author-name (customizable)
    - Automatically split too-long messages
        - If configured Telegraph, the message will be sent via Telegraph (customizable)
- [Various customizable formatting settings](docs/formatting-settings.md)
    - Hashtags, custom title, etc.
- Individual proxy settings for Telegram and RSS feeds
- OPML importing and exporting (keep custom title)
- Optimized performance (see also the [FAQ](docs/FAQ.md#q-how-is-the-performance-of-the-bot))
- User-friendly
- HTTP Caching

<img src="docs/resources/example1.png" width = "300" alt=""/><img src="docs/resources/example3.png" width = "300" alt=""/><img src="docs/resources/example4.png" width = "300" alt=""/>

## Deployment

[![PyPI](https://img.shields.io/pypi/v/rsstt?logo=pypi&logoColor=white)](https://pypi.org/project/rsstt/)
[![PyPI publish status](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-to-pypi.yml?label=publish&logo=pypi&logoColor=white)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-to-pypi.yml)
[![TestPyPI publish status](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-to-test-pypi.yml?label=publish%20(TestPyPI)&logo=pypi&logoColor=white)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-to-pypi.yml)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/rsstt?logo=pypi&logoColor=white)](https://pypi.org/project/rsstt/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/rsstt?logo=python&label=&labelColor=white)](https://www.python.org)

[![Docker Image Size (tag)](https://img.shields.io/docker/image-size/rongronggg9/rss-to-telegram/latest?logo=docker)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)
[![Build status (master)](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-docker-image.yml?branch=master&label=build&logo=docker)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-docker-image.yml?query=branch%3Amaster)
[![Build status (dev)](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-docker-image.yml?branch=dev&label=build%20%28dev%29&logo=docker)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-docker-image.yml?query=branch%3Adev)
[![Docker pulls](https://img.shields.io/docker/pulls/rongronggg9/rss-to-telegram?label=pulls&logo=docker&color=informational)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)

It is quite easy to deploy your RSStT instance. The most recommended way to deploy RSStT is Docker Compose: it is suitable for virtually all VPS. [Railway.app](https://railway.app) (a PaaS platform) is also officially supported. You may also install RSStT from PyPI (tracking `master` branch) or TestPyPI (tracking `dev` branch, which is latest) using pip. For developers or experienced users, dirty run from source is also an option.

<a href="docs/deployment-guide.md#option-2-railwayapp"><img src="https://railway.app/button.svg" height="30" alt="Deploy on Railway"></a>

For more details, refer to the [deployment guide](docs/deployment-guide.md).

## Translation

Read the translation guide [here](docs/translation-guide.md).

You can help to translate the bot using [Hosted Weblate](https://hosted.weblate.org/projects/rss-to-telegram-bot/). Special thanks to their free hosting service for libre projects!

<a href="https://hosted.weblate.org/engage/rss-to-telegram-bot/"><img src="https://hosted.weblate.org/widgets/rss-to-telegram-bot/-/glossary/multi-auto.svg" width = "500" alt="" /></a>

## Using the public bot

The [public bot](https://t.me/RSStT_Bot) comes with absolutely no warranty. I will try my best to maintain it, but I cannot guarantee that it will always work perfectly. Meanwhile, you should "fair use" the bot, avoid subscribing to too many RSS feeds.  
If you use the [public bot](https://t.me/RSStT_Bot) in your Channel, consider mentioning the bot (or this project) in your channel description (or pinned message) to let more people know about it. That's not a compulsion.

## Known channels using RSStT

Want to preview what the messages sent by RSStT look like? Here is a [list of channels using RSStT](docs/channels-using-rsstt.md).

## License

This project is licensed under [AGPLv3](LICENSE). Closed-source distribution or bot-hosting are strictly prohibited. If you modify the code and distribute or host it, make sure any users who can use your bot can get the source code (by editing the repo URL in [`src/i18n/__init__.py`](src/i18n/__init__.py)).

The repository was formerly a fork of [BoKKeR/RSS-to-Telegram-Bot](https://github.com/BoKKeR/RSS-to-Telegram-Bot). They have been entirely different projects since the early days of this project.
