# Deployment Guide

## Preparation

> For more env variables and detailed information, read [Advanced Settings](advanced-settings.md).

1. Turn to [@BotFather](https://t.me/BotFather) to create a new bot, then get its token (env variable: `TOKEN`).
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

> Uncheck the checkbox `Private repo?`! Or you are not able to update with ease.

|                      master                       |                     dev                     |
|:-------------------------------------------------:|:-------------------------------------------:|
|  [![Deploy on Railway (master)][button]][master]  |  [![Deploy on Railway (dev)][button]][dev]  |

[button]: https://railway.app/button.svg

[master]: https://railway.app/new/template?template=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot%2Ftree%2Fmaster&plugins=postgresql&envs=TOKEN%2CMANAGER%2CMULTIUSER%2CTELEGRAPH_TOKEN&optionalEnvs=MULTIUSER%2CTELEGRAPH_TOKEN&TOKENDesc=Your+bot+token&MANAGERDesc=Your+Telegram+user+ID&MULTIUSERDesc=If+set+to+0%2C+only+the+manager+can+use+the+bot&TELEGRAPH_TOKENDesc=To+enable+sending+via+Telegraph%2C+you+need+to+set+this&referralCode=PEOFMi

[dev]: https://railway.app/new/template?template=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot%2Ftree%2Fdev&plugins=postgresql&envs=TOKEN%2CMANAGER%2CMULTIUSER%2CTELEGRAPH_TOKEN&optionalEnvs=MULTIUSER%2CTELEGRAPH_TOKEN&TOKENDesc=Your+bot+token&MANAGERDesc=Your+Telegram+user+ID&MULTIUSERDesc=If+set+to+0%2C+only+the+manager+can+use+the+bot&TELEGRAPH_TOKENDesc=To+enable+sending+via+Telegraph%2C+you+need+to+set+this&referralCode=PEOFMi

### Update

Turn to your GitHub repository and switch to the branch you've deployed, then click `Fetch upstream` and `Fetch and merge`.

## Option 3: Dirty run

Minimal: Python 3.7+  
Recommended: Python 3.9+

```sh
git clone https://github.com/Rongronggg9/RSS-to-Telegram-Bot.git
cd RSS-to-Telegram-Bot
pip3 install -r requirements.txt
vi .env  # fill in env variables
python3 -u telegramRSSbot.py
```
