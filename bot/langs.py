from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    code: str
    english: str  # for AI prompts
    name_ru: str  # «итальянский»
    adverb_ru: str  # «по-итальянски»
    flag: str
    name_uz: str = ""  # «italyan»

    def name(self, native: str) -> str:
        """The language's name in the learner's base language (for menus and the Mini App)."""
        if native == "en":
            return self.english
        if native == "uz":
            return self.name_uz or self.english
        return self.name_ru


LANGS: dict[str, Lang] = {
    lang.code: lang
    for lang in [
        Lang("it", "Italian", "итальянский", "по-итальянски", "🇮🇹", "italyan"),
        Lang("en", "English", "английский", "по-английски", "🇬🇧", "ingliz"),
        Lang("es", "Spanish", "испанский", "по-испански", "🇪🇸", "ispan"),
        Lang("fr", "French", "французский", "по-французски", "🇫🇷", "fransuz"),
        Lang("de", "German", "немецкий", "по-немецки", "🇩🇪", "nemis"),
        Lang("pt", "Portuguese", "португальский", "по-португальски", "🇵🇹", "portugal"),
        Lang("ja", "Japanese", "японский", "по-японски", "🇯🇵", "yapon"),
        Lang("ko", "Korean", "корейский", "по-корейски", "🇰🇷", "koreys"),
        Lang("zh", "Chinese (Mandarin)", "китайский", "по-китайски", "🇨🇳", "xitoy"),
        Lang("tr", "Turkish", "турецкий", "по-турецки", "🇹🇷", "turk"),
        Lang("ru", "Russian", "русский", "по-русски", "🇷🇺", "rus"),
        Lang("uz", "Uzbek", "узбекский", "по-узбекски", "🇺🇿", "o'zbek"),
    ]
}

# Languages the bot can work in (the learner's base language: translations, explanations, the mascot's replies)
BASE_LANGS: dict[str, str] = {"ru": "🇷🇺 Русский", "uz": "🇺🇿 O'zbekcha", "en": "🇬🇧 English"}


def learnable(native: str) -> list[Lang]:
    """Languages one can learn from this base language (everything except the base itself)."""
    return [lang for lang in LANGS.values() if lang.code != native]


def get_lang(code: str) -> Lang:
    return LANGS.get(code) or Lang(code, code, code, f"на «{code}»", "🏳️")


def card_question(direction: str, target: str, native: str) -> str:
    """The question under a flashcard's front, in the learner's base language."""
    lang = get_lang(target)
    if direction == "fwd":
        return {"uz": "Qanday tarjima qilinadi?", "en": "What does it mean?"}.get(native, "Как переводится?")
    if native == "uz":
        return f"{lang.name_uz or lang.english} tilida qanday bo'ladi?"
    if native == "en":
        return f"How do you say it in {lang.english}?"
    return f"Как будет {lang.adverb_ru}?"
