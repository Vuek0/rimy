from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    code: str
    english: str  # for AI prompts
    name_ru: str  # «итальянский»
    adverb_ru: str  # «по-итальянски»
    flag: str


LANGS: dict[str, Lang] = {
    lang.code: lang
    for lang in [
        Lang("it", "Italian", "итальянский", "по-итальянски", "🇮🇹"),
        Lang("en", "English", "английский", "по-английски", "🇬🇧"),
        Lang("es", "Spanish", "испанский", "по-испански", "🇪🇸"),
        Lang("fr", "French", "французский", "по-французски", "🇫🇷"),
        Lang("de", "German", "немецкий", "по-немецки", "🇩🇪"),
        Lang("pt", "Portuguese", "португальский", "по-португальски", "🇵🇹"),
        Lang("ja", "Japanese", "японский", "по-японски", "🇯🇵"),
        Lang("ko", "Korean", "корейский", "по-корейски", "🇰🇷"),
        Lang("zh", "Chinese (Mandarin)", "китайский", "по-китайски", "🇨🇳"),
        Lang("tr", "Turkish", "турецкий", "по-турецки", "🇹🇷"),
        Lang("ru", "Russian", "русский", "по-русски", "🇷🇺"),
        Lang("uz", "Uzbek", "узбекский", "по-узбекски", "🇺🇿"),
    ]
}

# Languages the bot can work in (the learner's base language: translations, explanations, the mascot's replies)
BASE_LANGS: dict[str, str] = {"ru": "🇷🇺 Русский", "uz": "🇺🇿 O'zbekcha", "en": "🇬🇧 English"}


def learnable(native: str) -> list[Lang]:
    """Languages one can learn from this base language (everything except the base itself)."""
    return [lang for lang in LANGS.values() if lang.code != native]


def get_lang(code: str) -> Lang:
    return LANGS.get(code) or Lang(code, code, code, f"на «{code}»", "🏳️")
