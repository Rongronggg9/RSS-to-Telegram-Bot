# Translation Guide

You can contribute by helping us to translate the bot to your language.

## Steps

1. Copy the [src/i18n/](../src/i18n)`en.json` to [src/i18n/](../src/i18n)`<lang_code>.json`.

2. Ensure the following keys are correct:

| key                | e.g. 1    | e.g. 2               | e.g. 3      | e.g. 4                |
|--------------------|-----------|----------------------|-------------|-----------------------|
| "lang_code"[^1]    | "en"      | "zh-Hans"            | "yue"[^2]   | "zh-Hant"             |
| "iso_639_code"[^3] | "en"      | "zh"                 | "yue"       | ""[^4]                |
| "language_name"    | "English" | "Simplified Chinese" | "Cantonese" | "Traditional Chinese" |
| "lang_native_name" | "English" | "简体中文"               | "廣東話"       | "正體中文"                |

3. Translate other keys to your language.

4. Commit your translation and create a Pull Request.

[^1]: Shorter is better. Usually, it's the same as `iso_639_code`. However, if a language does have multiple common variants and of which no one can be a common standard, consider using an extended [IETF language tag](https://en.wikipedia.org/wiki/IETF_language_tag) instead. Please make sure the language code is [IANA-registered](https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry) and not deprecated or not about to be deprecated.

[^2]: `yue` is a valid ISO 639-3 code, while `zh-yue` is non-standard.

[^3]: Use for fallback. If your language has an ISO 639-1 code, use it. Otherwise, use an ISO 639-2/3 code. Ref: [List of ISO 639-1 codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes)

[^4]: If a language has multiple variants, only the most widely-used one can set `iso_639_code`.
