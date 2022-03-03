from __future__ import annotations
from typing import Optional

from json import load
from os import listdir, path
from multidict import CIMultiDict, istr

I18N_PATH = path.split(path.realpath(__file__))[0]
ALL_LANGUAGES = tuple(lang[:-5] for lang in listdir(I18N_PATH) if lang.endswith('.json'))
FALLBACK_LANGUAGE = istr('en')
NO_FALLBACK_KEYS = {istr('iso_639_code')}


class _I18N:
    __instance: Optional["_I18N"] = None
    __initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if not self.__initialized:
            self.__l10n_d: CIMultiDict[_L10N] = CIMultiDict()
            self.__iso_639_d: CIMultiDict[str] = CIMultiDict()
            for lang in ALL_LANGUAGES:
                l10n = _L10N(lang)
                iso_639_code = l10n['iso_639_code']
                self.__l10n_d[lang] = l10n
                if iso_639_code:
                    self.__iso_639_d[iso_639_code] = lang

            self.__initialized = True
            self.set_help_msg_html()

    def __getitem__(self, lang_code: Optional[str]) -> "_L10N":
        if not lang_code or not isinstance(lang_code, str):
            return self.get_fallback_l10n()
        return self.__l10n_d[lang_code] if lang_code in self.__l10n_d else self.get_fallback_l10n(lang_code)

    def get_all_l10n_string(self, key: str, html_escaped: bool = False,
                            only_iso_639: bool = False) -> tuple[str, ...]:
        languages = ALL_LANGUAGES if not only_iso_639 else self.__iso_639_d.keys()
        res = (
            tuple(self[lang_code][key] for lang_code in languages if self[lang_code].key_exist(key))
            if not html_escaped else
            tuple(self[lang_code].html_escaped(key) for lang_code in languages if self[lang_code].key_exist(key))
        )
        return res or (key,)

    def get_fallback_l10n(self, lang_code: Optional[str] = None) -> "_L10N":
        if not lang_code or not isinstance(lang_code, str):
            return self.__l10n_d[FALLBACK_LANGUAGE]
        iso_639_code = lang_code.split('-')[0].split('_')[0]
        if iso_639_code in self.__iso_639_d:
            return self.__l10n_d[self.__iso_639_d[iso_639_code]]
        return self.__l10n_d[FALLBACK_LANGUAGE]

    def set_help_msg_html(self):
        cmd_lang_description = ' / '.join(self.get_all_l10n_string('cmd_description_lang', html_escaped=True,
                                                                   only_iso_639=True))
        for l10n in self.__l10n_d.values():
            l10n_cmd_description_lang = l10n['cmd_description_lang']
            _cmd_description_lang = (
                    (f'{l10n_cmd_description_lang} / '
                     if not l10n['iso_639_code'] and l10n_cmd_description_lang not in cmd_lang_description else '')
                    + cmd_lang_description
            )
            help_msg_html = (
                f"<a href='https://github.com/Rongronggg9/RSS-to-Telegram-Bot'>{l10n.html_escaped('rsstt_slogan')}</a>\n"
                f"\n"
                f"{l10n.html_escaped('commands')}:\n"
                f"<b>/sub</b>: {l10n.html_escaped('cmd_description_sub')}\n"
                f"<b>/unsub</b>: {l10n.html_escaped('cmd_description_unsub')}\n"
                f"<b>/unsub_all</b>: {l10n.html_escaped('cmd_description_unsub_all')}\n"
                f"<b>/list</b>: {l10n.html_escaped('cmd_description_list')}\n"
                f"<b>/set</b>: {l10n.html_escaped('cmd_description_set')}\n"
                f"<b>/import</b>: {l10n.html_escaped('cmd_description_import')}\n"
                f"<b>/export</b>: {l10n.html_escaped('cmd_description_export')}\n"
                f"<b>/activate_subs</b>: {l10n.html_escaped('cmd_description_activate_subs')}\n"
                f"<b>/deactivate_subs</b>: {l10n.html_escaped('cmd_description_deactivate_subs')}\n"
                f"<b>/version</b>: {l10n.html_escaped('cmd_description_version')}\n"
                f"<b>/lang</b>: {_cmd_description_lang}\n"
                f"<b>/help</b>: {l10n.html_escaped('cmd_description_help')}\n\n"
            )
            l10n.set_help_msg_html(help_msg_html)


class _L10N:
    def __init__(self, lang_code: str):
        self.__lang_code: str = lang_code
        self.__l10n_lang: CIMultiDict[str]
        with open(path.join(I18N_PATH, lang_code + '.json'), encoding='utf-8') as f:
            l10n_d = load(f)
        l10n_d_flatten = {}
        assert isinstance(l10n_d, dict)
        for key, value in l10n_d.items():
            assert isinstance(value, dict)
            for k, v in value.items():
                assert isinstance(v, str) and k not in l10n_d_flatten
                l10n_d_flatten[k] = v
        self.__l10n_lang = CIMultiDict(l10n_d_flatten)

    def key_exist(self, key: str):
        return key in self.__l10n_lang and (self.__l10n_lang[key] or key in NO_FALLBACK_KEYS)

    def __getitem__(self, key: str) -> str:
        if self.key_exist(key):
            return self.__l10n_lang[key]
        elif self.__lang_code != FALLBACK_LANGUAGE:
            return _I18N().get_fallback_l10n(
                self.__lang_code if not self.__l10n_lang['iso_639_code'] else None  # get ISO 639 fallback if needed
            )[key]
        else:
            return key

    def html_escaped(self, key: str):
        return self[key].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def set_help_msg_html(self, msg_html: str):
        self.__l10n_lang['help_msg_html'] = msg_html


i18n = _I18N()
