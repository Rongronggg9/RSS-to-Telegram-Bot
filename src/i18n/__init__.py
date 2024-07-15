#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from typing import Optional

from json import load
from os import listdir, path
from multidict import CIMultiDict, istr
from cjkwrap import cjklen
from telethon.tl import types

I18N_PATH = path.split(path.realpath(__file__))[0]
ALL_LANGUAGES = tuple(sorted(lang[:-5] for lang in listdir(I18N_PATH) if lang.endswith('.json')))
FALLBACK_LANGUAGE = istr('en')
NO_FALLBACK_KEYS = {istr('iso_639_code')}

REPO_TYPE = 'GitHub'
REPO_URL = 'https://github.com/Rongronggg9/RSS-to-Telegram-Bot'

NEED_PRE_FILL = {
    # istr('default_emoji_header_description'):
    #     ('↩',),
    istr('read_formatting_settings_guidebook_html'):
        ('https://github.com/Rongronggg9/RSS-to-Telegram-Bot/blob/dev/docs/formatting-settings.md',),
}

COMMANDS = ('sub', 'unsub', 'unsub_all', 'list', 'set', 'set_default', 'import', 'export', 'activate_subs',
            'deactivate_subs', 'version', 'help', 'lang')
MANAGER_COMMANDS = ('test', 'set_option', 'user_info')
REQUIRED_KEYS = {istr('lang_code'), istr('lang_native_name'), istr('select_lang_prompt')}


class _I18N:
    __instance: Optional["_I18N"] = None
    __initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        global ALL_LANGUAGES

        if self.__initialized:
            return
        self.__l10n_d: CIMultiDict[_L10N] = CIMultiDict()
        self.__iso_639_d: CIMultiDict[str] = CIMultiDict()
        self.lang_n_per_row = {1: [], 2: [], 3: []}
        for lang in ALL_LANGUAGES:
            l10n = _L10N(lang)
            iso_639_code = l10n['iso_639_code']
            if not all(l10n.key_exist(key) for key in REQUIRED_KEYS):
                ALL_LANGUAGES = tuple(filter(lambda l: l != lang, ALL_LANGUAGES))
                continue
            self.__l10n_d[lang] = l10n
            if iso_639_code:
                self.__iso_639_d[iso_639_code] = lang
            cjklen_native_name = cjklen(l10n['lang_native_name'])
            if cjklen_native_name <= 7:
                self.lang_n_per_row[3].append(lang)
            elif 7 < cjklen_native_name <= 12:
                self.lang_n_per_row[2].append(lang)
            else:
                self.lang_n_per_row[1].append(lang)

        self.__initialized = True
        self.set_help_msg_html()

    def __getitem__(self, lang_code: Optional[str]) -> "_L10N":
        if not lang_code or not isinstance(lang_code, str):
            return self.get_fallback_l10n()
        return self.__l10n_d[lang_code] if lang_code in self.__l10n_d else self.get_fallback_l10n(lang_code)

    def get_all_l10n_string(self, key: str, html_escaped: bool = False,
                            only_iso_639: bool = False) -> tuple[str, ...]:
        languages = self.__iso_639_d.keys() if only_iso_639 else ALL_LANGUAGES
        all_l10n = tuple(self[lang_code] for lang_code in languages)
        res = tuple(
            l10n.html_escaped(key) if html_escaped else l10n[key]
            for l10n in all_l10n
            if l10n.key_exist(key)
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
                f"{l10n.html_escaped('rsstt_slogan')}\n\n"
                f"{REPO_TYPE}: {REPO_URL}\n\n"
                f"{l10n.html_escaped('commands')}:\n"
            )
            help_msg_html += '\n'.join(
                f"<b>/{command}</b>: "
                f"{l10n.html_escaped(f'cmd_description_{command}') if command != 'lang' else _cmd_description_lang}"
                for command in COMMANDS
            )
            manager_help_msg_html = help_msg_html + '\n\n' + '\n'.join(
                f"<b>/{command}</b>: {l10n.html_escaped(f'cmd_description_{command}')}"
                for command in MANAGER_COMMANDS
            )
            l10n.set_help_msg_html(help_msg_html, manager_help_msg_html)


class _L10N:
    def __init__(self, lang_code: str):
        self.__lang_code: str = lang_code
        self.__l10n_lang: CIMultiDict[str]
        with open(path.join(I18N_PATH, f'{lang_code}.json'), encoding='utf-8') as f:
            l10n_d = load(f)
        l10n_d_flatten = {}
        assert isinstance(l10n_d, dict)
        for key, value in l10n_d.items():
            assert isinstance(value, dict)
            for k, v in value.items():
                assert isinstance(v, str) and k not in l10n_d_flatten
                if v and k in NEED_PRE_FILL:
                    try:
                        v = v % NEED_PRE_FILL[k]
                    except TypeError:
                        v = ""
                l10n_d_flatten[k] = v
        self.__l10n_lang = CIMultiDict(l10n_d_flatten)

    def key_exist(self, key: str):
        return key in self.__l10n_lang and (self.__l10n_lang[key] or key in NO_FALLBACK_KEYS)

    def __getitem__(self, key: str) -> str:
        if self.key_exist(key):
            return self.__l10n_lang[key]
        if self.__lang_code != FALLBACK_LANGUAGE:
            # get ISO 639 fallback if needed
            return _I18N().get_fallback_l10n(None if self.__l10n_lang['iso_639_code'] else self.__lang_code)[key]

        return key

    @property
    def lang_code(self):
        return self.__lang_code

    def html_escaped(self, key: str):
        return self[key].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def set_help_msg_html(self, msg_html: str, manager_msg_html: str = None):
        self.__l10n_lang['help_msg_html'] = msg_html
        self.__l10n_lang['manager_help_msg_html'] = manager_msg_html or msg_html


i18n = _I18N()


def get_commands_list(lang: Optional[str] = None, manager: bool = False) -> list[types.BotCommand]:
    commands = [types.BotCommand(command=command, description=i18n[lang][f'cmd_description_{command}'])
                for command in COMMANDS]

    if manager:
        commands.extend(types.BotCommand(command=command, description=i18n[lang][f'cmd_description_{command}'])
                        for command in MANAGER_COMMANDS)

    return commands
