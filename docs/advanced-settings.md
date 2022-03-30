# Advanced Settings

## Env variables

### Required

| Key       | Description                                       | Example                                            |
|-----------|---------------------------------------------------|----------------------------------------------------|
| `TOKEN`   | Your bot token. Get it from [@BotFather]          | `1234567890:A1BCd2EF3gH45IJK6lMN7oPqr8ST9UvWX0Yz0` |
| `MANAGER` | Your Telegram user ID. Get it from [@userinfobot] | `1234567890`                                       |

### API settings

| Key               | Description                                                 | Example                                                             | Default      |
|-------------------|-------------------------------------------------------------|---------------------------------------------------------------------|--------------|
| `API_ID`          | [Your Telegram API ID][telegram_api]                        | `1025907`                                                           | (predefined) |
| `API_HASH`        | [Your Telegram API hash][telegram_api]                      | `452b0359b988148995f22ff0f4229750`                                  | (predefined) |
| `TELEGRAPH_TOKEN` | Telegraph API access token. Get [here][telegraph_api]. [^1] | `1a23b456c78de90f1a23b456c78de90f1a23b456c78de90f1a23b456c78d` [^2] |              |

[@BotFather]: https://t.me/BotFather

[@userinfobot]: https://t.me/userinfobot

[telegram_api]: https://core.telegram.org/api/obtaining_api_id

[telegraph_api]: https://api.telegra.ph/createAccount?short_name=RSStT&author_name=Generated%20by%20RSStT&author_url=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot

### Network settings

| Key                    | Description                                           | Example                        | Default                     |
|------------------------|-------------------------------------------------------|--------------------------------|-----------------------------|
| `T_PROXY`              | Proxy used to connect to the Telegram API [^3]        | `socks5://172.17.0.1:1080`     |                             |
| `R_PROXY`              | Proxy used to fetch feeds [^3]                        | `socks5://172.17.0.1:1080`     |                             |
| `PROXY_BYPASS_PRIVATE` | Pypass proxy for private IPs or not?                  | `1`                            | `0`                         |
| `PROXY_BYPASS_DOMAINS` | Pypass proxy for listed domains                       | `example.com;example.net` [^2] |                             |
| `USER_AGENT`           | User-Agent                                            | `Mozilla/5.0`                  | `RSStT/$VERSION RSS Reader` |
| `IPV6_PRIOR`           | Enforce fetching feeds over IPv6 firstly or not? [^4] | `1`                            | `0`                         |

### Misc settings

| Key                | Description                                                            | Example                                       | Default                                                |
|--------------------|------------------------------------------------------------------------|-----------------------------------------------|--------------------------------------------------------|
| `MULTIUSER`        | Enable multi-user feature or not?                                      | `0`                                           | `1`                                                    |
| `CRON_SECOND`      | Run the feed monitoring task at the n-th second of each minute? (0-59) | `30`                                          | `0`                                                    |
| `IMG_RELAY_SERVER` | Media relay server URL                                                 | `https://images.weserv.nl/?url=`              | `https://rsstt-img-relay.rongrong.workers.dev/`        |
| `IMAGES_WESERV_NL` | images.weserv.nl URL                                                   | `https://t0.nl/`                              | `https://images.weserv.nl/`                            |
| `DATABASE_URL`     | Database URL [^5]                                                      | `postgres://user:pass@example.com:5432/table` | `sqlite://$PATH_TO_CONFIG/db.sqlite3?journal_mode=OFF` |
| `TABLE_TO_IMAGE`   | Convert tables to image (causing high CPU usage) or just drop them?    | `1`                                           | `0`                                                    |
| `DEBUG`            | Enable debug logging or not?                                           | `1`                                           | `0`                                                    |

## Manager options

> Manager options are options stored in the database. The bot manager can change it by using the `/set_option` command.

| Key                | Description                           | Example | Default |
|--------------------|---------------------------------------|---------|---------|
| `default_interval` | Default feed monitoring interval [^6] | `5`     | `10`    |
| `minimal_interval` | Minimal feed monitoring interval [^7] | `10`    | `5`     |

[^1]: Refresh the page every time you get a new token. If you have a lot of subscriptions, make sure to get at least 5 tokens.
[^2]: Can be a list, separated by `;`, `,`, `(space)`, `(linebreak)`, or `(tab)`
[^3]: If you would like to use a proxy in a docker container, but your proxy is in your host machine, the hostname should be `172.17.0.1` (Linux) or `host.docker.internal` (macOS/Windows). Note: your proxy program should also listen to it.
[^4]: Use with caution. Enabling it will enforce the bot to try to fetch feeds over IPv6 (fallback to IPv4 if failed), which may be helpful if your IPv4 address gets banned by some feed providers. If it is disabled (by default), the bot will still try to fetch feeds over IPv4 and IPv6, but there is no clear priority. You should firstly ensure that the bot has IPv6 connectivity, especially if run in docker.
[^5]: Ref: [https://tortoise-orm.readthedocs.io/en/latest/databases.html](). Note that Railway.app will automatically fill this env variable.
[^6]: After a user subscribes to a feed, the default monitoring interval is applied.
[^7]: The minimal monitoring interval a user can set for a subscription. Note that the bot manager will not be limited by this value.
