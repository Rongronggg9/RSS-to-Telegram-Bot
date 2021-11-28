from json import load
from os import listdir, path
from typing import Optional, Dict

I18N_PATH = path.split(path.realpath(__file__))[0]
ALL_LANGUAGES = tuple(lang[:-5] for lang in listdir(I18N_PATH) if lang.endswith('.json'))


class _I18N:
    __instance: Optional["_I18N"] = None
    __initialized: bool = False
    __fallback_lang: str = 'en'

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if not self.__initialized:
            self.__l10n: Dict[str, _L10N] = {}
            for lang_code in ALL_LANGUAGES:
                self.__l10n[lang_code] = _L10N(lang_code)

            self.__initialized = True

    def __getitem__(self, lang_code: str) -> "_L10N":
        return self.__l10n[lang_code] if lang_code in self.__l10n else self.get_fallback_l10n()

    def get_fallback_l10n(self) -> "_L10N":
        return self.__l10n[self.__fallback_lang]


class _L10N:
    def __init__(self, lang_code: str):
        self.__lang_code: str = lang_code
        self.__l10n_lang: Dict[str, str] = {}
        with open(path.join(I18N_PATH, lang_code + '.json'), encoding='utf-8') as f:
            self.__l10n_lang = load(f)

    def __getitem__(self, key_string):
        return self.__l10n_lang[key_string] if key_string in self.__l10n_lang \
            else _I18N().get_fallback_l10n()[key_string]


i18n = _I18N()
