"""Uzbek is written in Latin and in Cyrillic; Rimy speaks Latin. Detection and transliteration helpers."""

import re

# Official Uzbek Cyrillic → Latin (1995 alphabet); е/ё/ю/я and ц have position-dependent forms below.
_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "x", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ь": "", "ы": "i", "э": "e", "ё": "yo", "ю": "yu",
    "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h", "ц": "ts",
}
_VOWELS = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LETTER = re.compile(r"[^\W\d_]")
UZBEK_ONLY = set("ўқғҳЎҚҒҲ")  # letters Russian doesn't have
RUSSIAN_ONLY = set("ыщЫЩ")  # letters Uzbek Cyrillic doesn't have


def has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text))


def cyrillic_share(text: str) -> float:
    letters = _LETTER.findall(text)
    return sum(1 for ch in letters if _CYRILLIC.match(ch)) / len(letters) if letters else 0.0


def looks_russian(text: str) -> bool:
    """Mostly Cyrillic and not Uzbek Cyrillic: the model answered in Russian instead of Uzbek."""
    if cyrillic_share(text) < 0.3:
        return False
    return not any(ch in UZBEK_ONLY for ch in text) or any(ch in RUSSIAN_ONLY for ch in text)


def uz_to_latin(text: str) -> str:
    """Uzbek Cyrillic → Latin; text that is already Latin (and the learned words) is left as it is."""
    out: list[str] = []
    for i, ch in enumerate(text):
        low = ch.lower()
        if low not in _MAP and low != "е":
            out.append(ch)
            continue
        prev = text[i - 1] if i else " "
        if low == "е":  # "ye" at the start of a word and after a vowel, otherwise "e"
            latin = "ye" if not prev.isalpha() or prev in _VOWELS else "e"
        elif low == "ц":  # "s" at the start of a word, "ts" inside
            latin = "s" if not prev.isalpha() else "ts"
        else:
            latin = _MAP[low]
        if ch != low and latin:  # keep capitals: Қ → Q, Ш → Sh
            latin = latin[0].upper() + latin[1:]
        out.append(latin)
    return "".join(out)
