# Deployment Guide

## Preparation

> [!TIP]\
> For more env variables and detailed information, read [Advanced Settings](advanced-settings.md).

1. Turn to [@BotFather](https://t.me/BotFather), send `/newbot` create a new bot, then get its token (env variable: `TOKEN`). After that, send `/setinline`, select your bot, and reply with an inline placeholder you like to enable inline mode for your bot. For example, [@RSStT_Bot](https://t.me/RSStT_Bot) is using `Please input a command to continue...`.
2. Turn to [@userinfobot](https://t.me/userinfobot) to get your user ID (env variable: `MANAGER`).
3. [Get Telegraph API access tokens](https://api.telegra.ph/createAccount?short_name=RSStT&author_name=Generated%20by%20RSStT&author_url=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot) (env variable: `TELEGRAPH_TOKEN`). Refresh the page every time you get a new token. If you have a lot of subscriptions, make sure to get at least 5 tokens.

## Option 1: Docker Compose

[![dockeri.co](https://dockerico.blankenship.io/image/rongronggg9/rss-to-telegram)](https://hub.docker.com/r/rongronggg9/rss-to-telegram)\
[![Build status (master)](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-docker-image.yml?branch=master&label=build&logo=docker)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-docker-image.yml?query=branch%3Amaster)
[![Build status (dev)](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-docker-image.yml?branch=dev&label=build%20%28dev%29&logo=docker)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-docker-image.yml?query=branch%3Adev)

> [!TIP]\
> An x86_64 (amd64) or arm64v8 (aarch64) machine is required. If you need a VPS, [Vultr (affiliate link, w/ 14-days-valid $100 trial credit)](https://www.vultr.com/?ref=8947246-8H) High Performance (Intel) NVMe SSD Cloud Servers (starting at $6/month) are recommended.

### Deploy

```sh
mkdir rsstt
cd rsstt
wget https://raw.githubusercontent.com/Rongronggg9/RSS-to-Telegram-Bot/dev/docker-compose.yml.sample -O docker-compose.yml
vi docker-compose.yml  # fill in env variables
docker-compose up -d
```

### Update

```sh
docker-compose down
docker-compose pull
docker-compose up -d
```

## Option 2: Railway.app

> [!TIP]\
> ~~Railway accounts without any verified payment method or prepaid balance can only consume 500 execution hours per month, which means that RSStT will be paused after 500 hours of uptime. To get rid of the execution time limit, either associate a credit/debit card to your account or prepaid $5 **once**. You will get $5 free credit each month without execution time limit, which is pretty enough for RSStT. Except the prepaid balance (if you don't want to associate a credit/debit card), hosting RSStT should be free of charge.~~\
> [Railway no longer offers free plans](https://blog.railway.app/p/pricing-and-plans-migration-guide-2023). Deploying RSStT on Railway could cost you at least $5 per month (Hobby Plan).

### Deploy

|                             master                              |                     dev (recommended)                     |
|:---------------------------------------------------------------:|:---------------------------------------------------------:|
| [![Deploy on Railway (master)][railway_button]][railway_master] | [![Deploy on Railway (dev)][railway_button]][railway_dev] |

[railway_button]: https://railway.app/button.svg

[railway_master]: https://railway.app/new/template/UojxgA?referralCode=PEOFMi

[railway_dev]: https://railway.app/new/template/1_Wcri?referralCode=PEOFMi

After deployed, check the bot log to see if it is using PostgreSQL (`postgre`), otherwise, all the data will be lost when updating.

_Please note that if you deploy RSStT without using the above buttons, you must manually add the PostgreSQL plug-in._

### Update

`https://railway.app/dashboard` -> your RSStT project -> `RSS-to-Telegram-Bot` -> `Settings` -> `Check for updates`

## Option 3: ~~Heroku~~

> [!TIP]\
> ~~Heroku accounts with no verified payment method have only 550 hours of credit per month (about 23 days), and up to 1,000 hours per month with any verified payment methods.~~\
> [Heroku no longer offers free plans](https://blog.heroku.com/next-chapter). Deploying RSStT on Heroku could cost you at least $16 per month ($7 for Heroku Dyno and $9 for Heroku Postgres). [Railway.app](#option-2-railwayapp) offers lower price and better performance.

### Deploy

|                            master                            |                   dev (recommended)                    |
|:------------------------------------------------------------:|:------------------------------------------------------:|
| [![Deploy to Heroku (master)][heroku_button]][heroku_master] | [![Deploy to Heroku (dev)][heroku_button]][heroku_dev] |

[heroku_button]: https://www.herokucdn.com/deploy/button.svg

[heroku_master]: https://heroku.com/deploy?template=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot%2Ftree%2Fmaster

[heroku_dev]: https://heroku.com/deploy?template=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot%2Ftree%2Fdev

### Update

1. [Fork RSStT](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/fork) to your GitHub account.
2. Use the instant deploy buttons above to deploy RSStT to Heroku.
3. Switch the `Deployment method` to `GitHub` (`Deploy` tab -> `Deployment method`) and connect the app to your fork.
4. Enable `Automatic deploys` (`Deploy` tab -> `Automatic deploys` -> `Enable Automatic Deploys`).
5. Each time upstream updates, turn to your fork and switch to the branch you've deployed, then click `Fetch upstream` and `Fetch and merge`.

## Option 4: Install from PyPI / Dirty run from source

> [!IMPORTANT]\
> It is **highly recommended** to [set up a virtual environment (`venv`)](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/).

### System requirements

> [!NOTE]\
> RSStT is tested only under the recommended system requirements.

|                      | **Minimum**           | **Recommended** |
|----------------------|-----------------------|-----------------|
| **Operating system** | Linux, Windows, macOS | Linux           |
| **Architecture**     | x86_64, arm64         | x86_64          |
| **Python (CPython)** | 3.9                   | 3.12            |
| **Free memory**      | 128MB                 | \> 384MB        |

### Prerequisites

> [!NOTE]\
> These fonts are used for HTML table rendering (to enable it, set the environment variable `TABLE_TO_IMAGE` to `1`). You may use WenQuanYi Zen Hei, WenQuanYI Micro Hei, Noto Sans CJK, Microsoft YaHei, or SimHei.

#### Debian / Ubuntu

```sh
sudo apt install -y fonts-wqy-microhei
```

#### Other Linux distributions / Windows / macOS

You know what to do. However, I cannot guarantee that the fonts can be recognized properly by matplotlib.

### Option 4.1: Install from PyPI

[![PyPI](https://img.shields.io/pypi/v/rsstt?logo=pypi&logoColor=white&label=PyPI)](https://pypi.org/project/rsstt/)
[![TestPyPI](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Ftest.pypi.org%2Fpypi%2Frsstt%2Fjson&query=%24.info.version&prefix=v&logo=pypi&logoColor=white&label=TestPyPI)](https://test.pypi.org/project/rsstt/)
[![PyPI - Implementation](https://img.shields.io/pypi/implementation/rsstt?logo=python&label=&labelColor=white)](https://www.python.org)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/rsstt?logo=python&label=&labelColor=white)](https://www.python.org)\
[![PyPI publish status](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-to-pypi.yml?label=publish&logo=pypi&logoColor=white)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-to-pypi.yml)
[![TestPyPI publish status](https://img.shields.io/github/actions/workflow/status/Rongronggg9/RSS-to-Telegram-Bot/publish-to-test-pypi.yml?label=publish%20(TestPyPI)&logo=pypi&logoColor=white)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/actions/workflows/publish-to-test-pypi.yml)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/rsstt?logo=pypi&logoColor=white)](https://pypi.org/project/rsstt/)

> [!NOTE]\
> The default config folder is `~/.rsstt`.

> [!IMPORTANT]
> * `python3 -m pip install -U rsstt` will install the latest **stable** version from [PyPI](https://pypi.org/project/rsstt), which **may be outdated**.
> * `python3 -m pip install -U --extra-index-url https://test.pypi.org/simple rsstt` will install the latest **dev** version from [TestPyPI](https://test.pypi.org/project/rsstt), which is **always up-to-date**.

```sh
python3 -m pip install -U pip setuptools wheel
python3 -m pip install -U rsstt
# python3 -m pip install -U --extra-index-url https://test.pypi.org/simple rsstt
mkdir -p ~/.rsstt
wget https://raw.githubusercontent.com/Rongronggg9/RSS-to-Telegram-Bot/dev/.env.sample -O ~/.rsstt/.env
vi ~/.rsstt/.env  # fill in env variables
python3 -m rsstt
```

### Option 4.2: Dirty run from source

[![GitHub repo size](https://img.shields.io/github/repo-size/Rongronggg9/RSS-to-Telegram-Bot?logo=github)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/archive/refs/heads/dev.zip)
[![GitHub release (latest SemVer including pre-releases)](https://img.shields.io/github/v/release/Rongronggg9/RSS-to-Telegram-Bot?include_prereleases&sort=semver&logo=github)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/releases)
[![GitHub commits since latest release (by SemVer including pre-releases)](https://img.shields.io/github/commits-since/Rongronggg9/RSS-to-Telegram-Bot/latest?include_prereleases&sort=semver&logo=github)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/commits/dev)
[![GitHub last commit (dev)](https://img.shields.io/github/last-commit/Rongronggg9/RSS-to-Telegram-Bot/dev?logo=github)](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/commits/dev)

> [!NOTE]
> The default config folder is `./config`, default `.env` path is `./.env` (placing it inside the config folder is also supported).

```sh
git clone https://github.com/Rongronggg9/RSS-to-Telegram-Bot.git
cd RSS-to-Telegram-Bot
python3 -m pip install -r requirements.txt
cp .env.sample .env
vi .env  # fill in env variables
python3 -u telegramRSSbot.py
```

### \* Advanced command line arguments

- `-h`, `--help`: show the help message and exit
- `-c`, `--config`: path to the config folder
