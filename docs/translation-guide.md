# Translation Guide

[![Translating Status](https://hosted.weblate.org/widgets/rss-to-telegram-bot/-/svg-badge.svg)](https://hosted.weblate.org/engage/rss-to-telegram-bot/)

You can contribute by helping us to translate the bot to your language.

## GitHub Pull Request

1. Copy the [src/i18n/`en.json`][en] to [src/i18n/][i18n]`<lang_code>.json`.

2. Ensure the following keys are correct:

| key                | e.g. 1    | e.g. 2               | e.g. 3      | e.g. 4                |
|--------------------|-----------|----------------------|-------------|-----------------------|
| `lang_code`[^1]    | `en`      | `zh-Hans`            | `yue`[^2]   | `zh-Hant`             |
| `iso_639_code`[^3] | `en`      | `zh`                 | `yue`       | [^4]                  |
| `language_name`    | `English` | `Simplified Chinese` | `Cantonese` | `Traditional Chinese` |
| `lang_native_name` | `English` | `简体中文`               | `廣東話`       | `正體中文`                |

3. Translate other keys to your language.

4. Commit your translation and create a Pull Request.

## Hosted Weblate

> Special thanks to their free hosting service for libre projects!

Recommended for those who are not familiar with Git or GitHub. You may both improve existing translations or start a new translation for your language.

<a href="https://hosted.weblate.org/engage/rss-to-telegram-bot/"><img src="https://hosted.weblate.org/widgets/rss-to-telegram-bot/-/open-graph.png" width = "500" alt="" /></a>
<a href="https://hosted.weblate.org/engage/rss-to-telegram-bot/"><img src="https://hosted.weblate.org/widgets/rss-to-telegram-bot/-/multi-auto.svg" width = "500" alt="" /></a>

https://hosted.weblate.org/projects/rss-to-telegram-bot/glossary/

## Translators
| Language                               | Translator(s)                 |
|----------------------------------------|-------------------------------|
| [en] / English                         | [@Rongronggg9]                |
| [zh-Hans] / Simplified Chinese / 简体中文  | [@Rongronggg9]                |
| [zh-Hant] / Traditional Chinese / 正體中文 | [@Rongronggg9]                |
| [yue] / Cantonese / 廣東話                | [@Rongronggg9]                |
| [it] / Italian / Italiano              | [DeepL], Alfonso ([@AlfyT96]) |

[i18n]: ../src/i18n
[en]: ../src/i18n/en.json
[zh-Hans]: ../src/i18n/zh-Hans.json
[zh-Hant]: ../src/i18n/zh-Hant.json
[yue]: ../src/i18n/yue.json
[it]: ../src/i18n/it.json
[@Rongronggg9]: https://github.com/Rongronggg9
[DeepL]: https://www.deepl.com/translator
[@AlfyT96]: https://t.me/AlfyT96

[^1]: Shorter is better. Usually, it's the same as `iso_639_code`. However, if a language does have multiple common variants and of which no one can be a common standard, consider using an extended [IETF language tag](https://en.wikipedia.org/wiki/IETF_language_tag) instead. Please make sure the language code is [IANA-registered](https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry) and not deprecated or not about to be deprecated.

[^2]: `yue` is a valid ISO 639-3 code, while `zh-yue` is non-standard.

[^3]: Use for fallback. If your language has an ISO 639-1 code, use it. Otherwise, use an ISO 639-2/3 code. Ref: [List of ISO 639-1 codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes)

[^4]: If a language has multiple variants, only the most widely-used one can set `iso_639_code`.
