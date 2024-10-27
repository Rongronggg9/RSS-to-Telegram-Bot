# Advanced Settings

## Env variables

### Required

| Key       | Description                                                             | Example                                            |
|-----------|-------------------------------------------------------------------------|----------------------------------------------------|
| `TOKEN`   | Your bot token. Get it from [@BotFather]                                | `1234567890:A1BCd2EF3gH45IJK6lMN7oPqr8ST9UvWX0Yz0` |
| `MANAGER` | Telegram user ID(s) that can manage the bot. Get it from [@userinfobot] | `1234567890` or `1234567890;987654321` [^1]        |

### API settings

| Key               | Description                                                    | Example                                                             | Default      |
|-------------------|----------------------------------------------------------------|---------------------------------------------------------------------|--------------|
| `API_ID`          | [Your Telegram API ID][telegram_api]                           | `1025907`                                                           | (predefined) |
| `API_HASH`        | [Your Telegram API hash][telegram_api]                         | `452b0359b988148995f22ff0f4229750`                                  | (predefined) |
| `TELEGRAPH_TOKEN` | Telegraph API access token(s). Get [here][telegraph_api]. [^2] | `1a23b456c78de90f1a23b456c78de90f1a23b456c78de90f1a23b456c78d` [^1] |              |

[@BotFather]: https://t.me/BotFather

[@userinfobot]: https://t.me/userinfobot

[telegram_api]: https://core.telegram.org/api/obtaining_api_id

[telegraph_api]: https://api.telegra.ph/createAccount?short_name=RSStT&author_name=Generated%20by%20RSStT&author_url=https%3A%2F%2Fgithub.com%2FRongronggg9%2FRSS-to-Telegram-Bot

### Network settings

| Key                         | Description                                           | Example                        | Default                                             |
|-----------------------------|-------------------------------------------------------|--------------------------------|-----------------------------------------------------|
| `T_PROXY`                   | Proxy used to connect to the Telegram API [^3]        | `socks5://172.17.0.1:1080`     |                                                     |
| `R_PROXY`                   | Proxy used to fetch feeds [^3]                        | `socks5://172.17.0.1:1080`     |                                                     |
| `PROXY_BYPASS_PRIVATE`      | Bypass proxy for private IPs or not?                  | `1`                            | `0`                                                 |
| `PROXY_BYPASS_DOMAINS`      | Bypass proxy for listed domains                       | `example.com;example.net` [^1] |                                                     |
| `USER_AGENT`                | User-Agent                                            | `Mozilla/5.0`                  | `RSStT/$VERSION RSS Reader (+https://git.io/RSStT)` |
| `IPV6_PRIOR`                | Enforce fetching feeds over IPv6 firstly or not? [^4] | `1`                            | `0`                                                 |
| `VERIFY_TLS`                | Verify TLS certificate or not?                        | `0`                            | `1`                                                 |
| `TRAFFIC_SAVING`            | Enable network traffic saving mode or not? [^5]       | `1`                            | `0`                                                 |
| `LAZY_MEDIA_VALIDATION`     | Let Telegram DC to validate media or not? [^6]        | `1`                            | `0`                                                 |
| `HTTP_TIMEOUT`              | HTTP request timeout in seconds                       | `60`                           | `12`                                                |
| `HTTP_CONCURRENCY`          | HTTP request concurrency overall (0=unlimited)        | `0`                            | `1024`                                              |
| `HTTP_CONCURRENCY_PER_HOST` | HTTP request concurrency per host (0=unlimited)       | `0`                            | `16`                                                |

### Misc settings

| Key                           | Description                                                                 | Example                                       | Default                                         |
|-------------------------------|-----------------------------------------------------------------------------|-----------------------------------------------|-------------------------------------------------|
| `ERROR_LOGGING_CHAT`          | Chat (user/channel/group) ID for error logging.                             | `-1001234567890`                              | The first user ID in `MANAGER`                  |
| `MULTIUSER`                   | Enable multi-user feature or not?                                           | `0`                                           | `1`                                             |
| `CRON_SECOND`                 | Run the feed monitoring task at the n-th second of each minute? (0-59)      | `30`                                          | `0`                                             |
| `IMG_RELAY_SERVER`            | Media relay server (https://github.com/Rongronggg9/rsstt-img-relay) URL     | `https://wsrv.nl/?url=`                       | `https://rsstt-img-relay.rongrong.workers.dev/` |
| `IMAGES_WESERV_NL`            | https://github.com/weserv/images instance                                   | `https://t0.nl/`                              | `https://wsrv.nl/`                              |
| `DATABASE_URL`                | Database URL [^7]                                                           | `postgres://user:pass@example.com:5432/table` | `sqlite:/path/to/config/db.sqlite3`             |
| `TABLE_TO_IMAGE`              | Convert tables to image (causing higher CPU load) or just drop them?        | `1`                                           | `0`                                             |
| `MANAGER_PRIVILEGED`          | Allow the bot manager to manipulate any users' subscriptions or not? [^8]   | `1`                                           | `0`                                             |
| `NO_UVLOOP`                   | Never enable `uvloop` (even if it is found) or not?                         | `1`                                           | `0`                                             |
| `MULTIPROCESSING`             | Enable multiprocessing (up to `min(3, CPU_COUNT)`) or not? [^9]             | `1`                                           | `0`                                             |
| `EXECUTOR_NICENESS_INCREMENT` | The niceness increment of subprocesses (if `MULTIPROCESSING=1`) and threads | `5`                                           | `2`                                             |
| `DEBUG`                       | Enable debug logging or not?                                                | `1`                                           | `0`                                             |

## Manager options

> Manager options are options stored in the database. The bot manager can change it by using the `/set_option` command.

| Key                          | Description                                                | Example                         | Default          |
|------------------------------|------------------------------------------------------------|---------------------------------|------------------|
| `default_interval`           | Default feed monitoring interval [^10]                     | `15`                            | `10`             |
| `minimal_interval`           | Minimal feed monitoring interval [^11] [^12]               | `10`                            | `5`              |
| `user_sub_limit`             | Subscription number limit for ordinary user [^13] [^12]    | `150`                           | `-1` (unlimited) |
| `channel_or_group_sub_limit` | Subscription number limit for channel or group [^13] [^12] | `150`                           | `-1` (unlimited) |
| `sub_limit_reached_message`  | Additional message attached to the limit reached warning   | `https://t.me/RSStT_Channel/58` |                  |

[^1]: Can be a list separated by `;`, `,`, `(space)`, `(linebreak)`, or `(tab)`.
[^2]: Refresh the page every time you get a new token. If you have a lot of subscriptions, make sure to get at least 5 tokens.
[^3]: If you would like to use a proxy in a docker container, but your proxy is in your host machine, the hostname should be `172.17.0.1` (Linux) or `host.docker.internal` (macOS/Windows). Note: your proxy program should also listen to it.
[^4]: Use with caution. Enabling it will enforce the bot to try to fetch feeds over IPv6 (fallback to IPv4 if failed), which may be helpful if your IPv4 address gets banned by some feed providers. If it is disabled (by default), the bot will still try to fetch feeds over IPv4 and IPv6, but there is no clear priority. You should firstly ensure that the bot has IPv6 connectivity, especially if run in docker.
[^5]: Use with caution. May cause media validating and sending slightly unreliable. Meanwhile, effectively disable webpage title detection for `<iframe>` tags, instead, the title will always be URL hostname.
[^6]: Use with caution. Help cut down network traffic further. If enabled, RSStT no longer fetches media and validates it. Effectively disable long-pic detection and partially disable icon detection.
[^7]: Ref: [https://tortoise-orm.readthedocs.io/en/latest/databases.html](). Note that Railway.app will automatically fill this env variable.
[^8]: Use with caution. If enabled, the bot manager can bypass the permission check before manipulating any users'/channels'/groups' subscriptions. The command format is like `/sub @username`, `/sub +9999999999` (ordinary user) or `/sub -1009999999999` (channel/group). Should only be used temporarily and be disabled after finishing the manipulation. This option is considered safe for bot users since the bot manager can always manipulate their subscriptions by manipulating the database manually.
[^9]: Only valid when there are more than 1 CPU core, otherwise the process count is always `1`. Enabling multiprocessing may help improve the performance on multicore CPUs if there are tons of subscriptions but consumes more memory. If your VPS comes with multiple cores but the performance of each is poor, you may want to enable this feature.
[^10]: After a user subscribes to a feed, the default monitoring interval is applied.
[^11]: The minimal monitoring interval a user can set for a subscription.
[^12]: The bot manager will not be limited by this value.
[^13]: Once reached the limit, no more subscriptions can be created. However, existing subscriptions will not be removed even if reaching the limit. As a bot manager, you can enable `MANAGER_PRIVILEGED` mode to manually unsubscribe their subscriptions.
