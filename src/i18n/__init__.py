from json import load
from os import listdir, path
from typing import Optional, Tuple
from multidict import CIMultiDict, istr

I18N_PATH = path.split(path.realpath(__file__))[0]
ALL_LANGUAGES = tuple(lang[:-5] for lang in listdir(I18N_PATH) if lang.endswith('.json'))
FALLBACK_LANGUAGE = istr('en')


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
            self.__iso_639_1_d: CIMultiDict[str] = CIMultiDict()
            for lang in ALL_LANGUAGES:
                l10n = _L10N(lang)
                iso_639_1_code = l10n['iso_639_1_code']
                self.__l10n_d[lang] = l10n
                if iso_639_1_code:
                    self.__iso_639_1_d[iso_639_1_code] = lang

            self.__initialized = True

    def __getitem__(self, lang_code: Optional[str]) -> "_L10N":
        if not lang_code or not isinstance(lang_code, str):
            return self.get_fallback_l10n()
        return self.__l10n_d[lang_code] if lang_code in self.__l10n_d else self.get_fallback_l10n(lang_code)

    def get_all_l10n_string(self, key: str) -> Tuple[str, ...]:
        res = tuple(self[lang_code][key] for lang_code in ALL_LANGUAGES if self[lang_code].key_exist(key))
        return res or (key,)

    def get_fallback_l10n(self, lang_code: Optional[str] = None) -> "_L10N":
        if not lang_code or not isinstance(lang_code, str):
            return self.__l10n_d[FALLBACK_LANGUAGE]
        iso_639_1_code = lang_code[:2]
        if iso_639_1_code in self.__iso_639_1_d:
            return self.__l10n_d[self.__iso_639_1_d[iso_639_1_code]]
        return self.__l10n_d[FALLBACK_LANGUAGE]


class _L10N:
    def __init__(self, lang_code: str):
        self.__lang_code: str = lang_code
        self.__l10n_lang: CIMultiDict[str]
        with open(path.join(I18N_PATH, lang_code + '.json'), encoding='utf-8') as f:
            self.__l10n_lang = CIMultiDict(load(f))

    def key_exist(self, key: str):
        return key in self.__l10n_lang

    def __getitem__(self, key: str):
        if self.key_exist(key):
            return self.__l10n_lang[key]
        elif self.__lang_code != FALLBACK_LANGUAGE:
            return _I18N().get_fallback_l10n(self.__lang_code)[key]
        else:
            return key


i18n = _I18N()
