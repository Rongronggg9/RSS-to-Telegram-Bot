from json import load
from os import listdir, path
from typing import Optional, Dict

I18N_PATH = path.split(path.realpath(__file__))[0]
ALL_LANGUAGES = tuple(lang[:-5] for lang in listdir(I18N_PATH) if lang.endswith('.json'))
FALLBACK_LANGUAGE = 'en'


class _I18N:
    __instance: Optional["_I18N"] = None
    __initialized: bool = False

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
        return self.__l10n[FALLBACK_LANGUAGE]


class _L10N:
    def __init__(self, lang_code: str):
        self.__lang_code: str = lang_code
        self.__l10n_lang: Dict[str, str] = {}
        with open(path.join(I18N_PATH, lang_code + '.json'), encoding='utf-8') as f:
            self.__l10n_lang = load(f)

    def __getitem__(self, key_string):
        if key_string in self.__l10n_lang:
            return self.__l10n_lang[key_string]
        elif self.__lang_code != FALLBACK_LANGUAGE:
            return _I18N().get_fallback_l10n()[key_string]
        else:
            return key_string


i18n = _I18N()
