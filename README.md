<p align="center">
<img src="docs/resources/RSStT_icon.svg" alt="RSS to Telegram Bot" width="100">
</p>
<h1 align="center">RSS to Telegram Bot</h1>

<p align="center"><b>A Telegram RSS bot that cares about your reading experience</b></p>

[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/Rongronggg9/RSS-to-Telegram-Bot?logo=git&label=commit)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/commits)
[![Translating status](https://img.shields.io/weblate/progress/rss-to-telegram-bot?logo=weblate&color=informational)](https://hosted.weblate.org/engage/rss-to-telegram-bot/)
[![Code quality](https://img.shields.io/codefactor/grade/github/Rongronggg9/RSS-to-Telegram-Bot?logo=codefactor)](https://www.codefactor.io/repository/github/rongronggg9/rss-to-telegram-bot)
[![GitHub stars](https://img.shields.io/github/stars/Rongronggg9/Rss-to-Telegram-Bot?style=social)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Rongronggg9/RSS-to-Telegram-Bot?style=social)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/fork)

[![Telegram bot](https://img.shields.io/badge/Telegram%20Bot-%40RSStT__Bot-229ed9?logo=telegram&style=for-the-badge)](https://t.me/RSStT_Bot)
[![Telegram group](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.swo.moe%2Fstats%2Ftelegram%2FRSStT_Group&query=count&color=2CA5E0&label=Telegram%20Group&logo=telegram&cacheSeconds=3600&style=for-the-badge)](https://t.me/RSStT_Group)
[![Telegram channel](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.swo.moe%2Fstats%2Ftelegram%2FRSStT_Channel&query=count&color=2CA5E0&label=Telegram%20Channel&logo=telegram&cacheSeconds=3600&style=for-the-badge)](https://t.me/RSStT_Channel)

| [简体中文 README] | [CHANGELOG] | [FAQ] | [Documentation] | [Channels Using RSStT] |
|:-------------:|:-----------:|:-----:|-----------------|:----------------------:|

[简体中文 README]: README.zh.md

[CHANGELOG]: docs/CHANGELOG.md

[FAQ]: docs/FAQ.md

[Documentation]: docs

[Channels Using RSStT]: docs/channels-using-rsstt.md

<table>
    <tr>
        <td><img src="docs/resources/example5.png" alt="Screenshot"></td>
        <td rowspan="2"><img src="docs/resources/example7.png" alt="Screenshot"></td>
        <td rowspan="2"><img src="docs/resources/example8.png" alt="Screenshot"></td>
    </tr>
    <tr>
        <td><img src="docs/resources/example6.png" alt="Screenshot"></td>
    </tr>
</table>

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
    - Messages can be sent as Telegraph posts (customizable)
- [Various customizable formatting settings](docs/formatting-settings.md)
    - Hashtags, custom title, etc.
- Individual proxy settings for Telegram and RSS feeds
- OPML importing and exporting (keep custom title)
- Optimized performance (see also the [FAQ](docs/FAQ.md#q-how-is-the-performance-of-the-bot))
- User-friendly
- HTTP Caching

## Deployment

[![dockeri.co](https://dockerico.blankenship.io/image/rongronggg9/rss-to-telegram)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)\
[![Build status (master)](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-docker-image.yml?branch=master&label=build&logo=docker)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-docker-image.yml?query=branch%3Amaster)
[![Build status (dev)](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-docker-image.yml?branch=dev&label=build%20%28dev%29&logo=docker)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-docker-image.yml?query=branch%3Adev)

[![PyPI](https://img.shields.io/pypi/v/rsstt?logo=pypi&logoColor=white&label=PyPI)](https://pypi.org/project/rsstt/)
[![TestPyPI](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Ftest.pypi.org%2Fpypi%2Frsstt%2Fjson&query=%24.info.version&prefix=v&logo=pypi&logoColor=white&label=TestPyPI)](https://test.pypi.org/project/rsstt/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/rsstt?logo=python&label=&labelColor=white)](https://www.python.org)\
[![PyPI publish status](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-to-pypi.yml?label=publish&logo=pypi&logoColor=white)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-to-pypi.yml)
[![TestPyPI publish status](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-to-test-pypi.yml?label=publish%20(TestPyPI)&logo=pypi&logoColor=white)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-to-test-pypi.yml)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/rsstt?logo=pypi&logoColor=white)](https://pypi.org/project/rsstt/)

It is quite easy to deploy your RSStT instance. The most recommended way to deploy RSStT is Docker Compose: it is suitable for virtually all VPS. [Railway.app](https://railway.app) (a PaaS platform) is also officially supported. You may also install RSStT from [PyPI](https://pypi.org/project/rsstt/) (tracking `master` branch) or [TestPyPI](https://test.pypi.org/project/rsstt/) (tracking `dev` branch, which is always up-to-date) using pip. For developers or experienced users, dirty run from source is also an option.

<a href="docs/deployment-guide.md#option-2-railwayapp"><img src="https://railway.app/button.svg" height="30" alt="Deploy on Railway"></a>

For more details, refer to the [deployment guide](docs/deployment-guide.md).

## Translation

Read the translation guide [here](docs/translation-guide.md).

You can help to translate the bot using [Hosted Weblate](https://hosted.weblate.org/projects/rss-to-telegram-bot/). Special thanks to their free hosting service for libre projects!

<a href="https://hosted.weblate.org/engage/rss-to-telegram-bot/"><img src="https://hosted.weblate.org/widgets/rss-to-telegram-bot/-/glossary/multi-auto.svg" width = "500" alt="" /></a>

## Using the public bot

The [public bot](https://t.me/RSStT_Bot) comes with absolutely no warranty. I will try my best to maintain it, but I cannot guarantee that it will always work perfectly. Meanwhile, you should "fair use" the bot, avoid subscribing to too many RSS feeds.\
If you use the [public bot](https://t.me/RSStT_Bot) in your Channel, consider mentioning the bot (or this project) in your channel description (or pinned message) to let more people know about it. That's not a compulsion.

## Known channels using RSStT

Want to preview what the messages sent by RSStT look like? Here is a [list of channels using RSStT](docs/channels-using-rsstt.md).

## Licensing

<img src="https://www.gnu.org/graphics/agplv3-with-text-162x68.png" alt="AGPLv3 logo" width="100" align="right">

This project is licensed under [AGPLv3+](LICENSE). Closed-source distribution or bot-hosting are strictly prohibited. If you distribute or host it with code modifications, make sure the source code is available to anyone who can use the bot (by editing the repo URL in [`src/i18n/__init__.py`](src/i18n/__init__.py)).

    RSS to Telegram Bot
    Copyright (C) 2020-2024  Rongrong <i@rong.moe>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

The repository was forked from [BoKKeR/RSS-to-Telegram-Bot](https://github.com/BoKKeR/RSS-to-Telegram-Bot) in 2020. Since some time in 2021, they share no common codebase and should be considered as completely different projects.
