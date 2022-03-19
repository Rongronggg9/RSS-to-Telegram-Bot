# Deployment Guide

## Preparation

> For more env variables and detailed information, read [Advanced Settings](advanced-settings.md).

1. Turn to [@BotFather](https://t.me/BotFather), send `/newbot` create a new bot, then get its token (env variable: `TOKEN`). After that, send `/setinline`, select your bot, and reply with an inline placeholder you like to enable inline mode for your bot. For example, [@RSStT_Bot](https://t.me/RSStT_Bot) is using `Please input a command to continue...`.
2. Turn to [@userinfobot](https://t.me/userinfobot) to get your user ID (env variable: `MANAGER`).
3. [Get Telegraph API access tokens](https://api.telegra.ph/createAccount?short_name=RSStT&author_name=Generated%20by%20RSStT&author_url=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot) (env variable: `TELEGRAPH_TOKEN`). Refresh the page every time you get a new token. If you have a lot of subscriptions, make sure to get at least 5 tokens.

## Option 1: Docker Compose

For the docker images go to: https://hub.docker.com/r/rongronggg9/rss-to-telegram

### Deploy

```sh
mkdir rsstt
cd rsstt
wget https://raw.githubusercontent.com/Rongronggg9/RSS-to-Telegram-Bot/master/docker-compose.yml.sample -O docker-compose.yml
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

### Deploy

> Uncheck the checkbox `Private repository`! Or you are not able to update with ease.

|                             master                              |                            dev                            |
|:---------------------------------------------------------------:|:---------------------------------------------------------:|
| [![Deploy on Railway (master)][railway_button]][railway_master] | [![Deploy on Railway (dev)][railway_button]][railway_dev] |

[railway_button]: https://railway.app/button.svg

[railway_master]: https://railway.app/new/template/UojxgA?referralCode=PEOFMi

[railway_dev]: https://railway.app/new/template/1_Wcri?referralCode=PEOFMi

After deployed, check the bot log to see if it is using PostgreSQL (`postgre`), otherwise, all the data will be lost when updating.

_Please note that if you deploy RSStT without using the above buttons, you must manually add the PostgreSQL plug-in._

### Update

Turn to the fork automatically created by Railway and switch to the branch you've deployed, then click `Fetch upstream` and `Fetch and merge`.

## Option 3: Heroku

> Heroku accounts with no verified payment method have only 550 hours of credit per month (about 23 days), and up to 1,000 hours per month with any verified payment methods.

### Deploy

|                            master                            |                          dev                           |
|:------------------------------------------------------------:|:------------------------------------------------------:|
| [![Deploy to Heroku (master)][heroku_button]][heroku_master] | [![Deploy to Heroku (dev)][heroku_button]][heroku_dev] |

[heroku_button]: https://www.herokucdn.com/deploy/button.svg

[heroku_master]: https://heroku.com/deploy?template=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot%2Ftree%2Fmaster

[heroku_dev]: https://heroku.com/deploy?template=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot%2Ftree%2Fdev

### Keep the dyno "awake"

> **IMPORTANT**  
> If you deploy RSStT as a **free dyno**, it will sleep if the dyno receives no web traffic in 30 minutes. Sending commands to the bot will NOT help.

Turn to [Kaffeine](https://kaffeine.herokuapp.com/), filling your Heroku app name, and click `Give my app a caffeine shot every 30 minutes ☕`. You do not need to check `I want a bedtime!` as long as your account has a verified payment method since Heroku has no longer enforced 6-hour-per-day sleeps since 2017. However, if your account has no verified payment method, you may still want to check `I want a bedtime!`. By checking it, your dyno will have a 6-hour sleep per day, which ensures that it will not exhaust your 550-hour credit.

### Update

1. [Fork RSStT](https://github.com/Rongronggg9/RSS-to-Telegram-Bot/fork) to your GitHub account.
2. Use the instant deploy buttons above to deploy RSStT to Heroku.
3. Switch the `Deployment method` to `GitHub` (`Deploy` tab -> `Deployment method`) and connect the app to your fork.
4. Enable `Automatic deploys` (`Deploy` tab -> `Automatic deploys` -> `Enable Automatic Deploys`).
5. Each time upstream updates, turn to your fork and switch to the branch you've deployed, then click `Fetch upstream` and `Fetch and merge`.

## Option 4: Dirty run

Minimal: Python 3.7+ (x86 / amd64), Python 3.8+ (arm64)  
Recommended: Python 3.9+

```sh
git clone https://github.com/Rongronggg9/RSS-to-Telegram-Bot.git
cd RSS-to-Telegram-Bot
pip3 install -r requirements.txt
vi .env  # fill in env variables
python3 -u telegramRSSbot.py
```
