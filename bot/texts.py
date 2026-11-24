"""All user-facing texts in one place, so a persona can restyle them later."""

import random

from bot.langs import Lang
from bot.utils import esc

STALE = "Эта кнопка уже неактуальна 🙂"
AI_ERROR = "Ой, у меня не получилось достучаться до AI 😿 Попробуй ещё раз чуть позже."
TOO_LONG = "Это длинновато 😅 Пришли одно слово или короткую фразу."

THINKING = ["Секундочку, смотрю… 🔎", "Так-так, сейчас проверю… 🤔", "Листаю словарик… 📖"]
SAVED = ["Сохранила! 🎉", "Готово, слово в колоде! ✨", "Записала! 📝"]


def pick(options: list[str]) -> str:
    return random.choice(options)


# --- texts in the learner's base language (ru / uz / en): onboarding and help ---

UI: dict[str, dict[str, str]] = {
    "ru": {
        "choose_base": "🦥 Привет! Я Рими, ленивец-полиглот.\n\nНа каком языке тебе удобнее со мной общаться?",
        "choose_target": "Отлично! А какой язык будем учить? 🌍",
        "base_set": "Готово: общаемся на русском 🇷🇺",
        "greeting": "Привет! 👋 Я Рими, ленивец-полиглот 🦥",
        "learning": "Сейчас учим",
        "help": (
            "🎙 <b>Самое удобное: просто отправь голосовое со словом.</b> Зажми микрофон справа внизу и скажи слово, "
            "можно даже по-русски. Я пойму, переведу и сам сделаю карточку, печатать ничего не нужно.\n\n"
            "📝 Можно и текстом: напиши слово или фразу.\n"
            "💬 Спроси что угодно, например «как сказать „я опоздал“?», и я отвечу.\n\n"
            "/app - открыть приложение\n"
            "/review - повторить карточки\n"
            "/list - мои слова\n"
            "/stats - статистика\n"
            "/lang - сменить изучаемый язык\n"
            "/base - сменить язык общения с ботом\n"
            "/practice - разговорная практика\n"
            "/premium - Premium без лимитов\n"
            "/remind - напоминания\n"
            "/memory - что Рими помнит о тебе"
        ),
    },
    "uz": {
        "choose_base": "🦥 Salom! Men Rimi - poliglot yalqov.\n\nMen bilan qaysi tilda gaplashish qulay?",
        "choose_target": "Ajoyib! Qaysi tilni o'rganamiz? 🌍",
        "base_set": "Tayyor: o'zbek tilida gaplashamiz 🇺🇿",
        "greeting": "Salom! 👋 Men Rimi - poliglot yalqov 🦥",
        "learning": "Hozir o'rganyapmiz",
        "help": (
            "🎙 <b>Eng qulayi: so'zni ovozli xabar bilan yubor.</b> Pastki o'ngdagi mikrofonni bosib turing va so'zni ayting, "
            "o'zbekcha ham bo'ladi. Men tushunaman, tarjima qilaman va kartochkani o'zim yarataman, hech narsa yozish shart emas.\n\n"
            "📝 Matn bilan ham mumkin: so'z yoki iborani yozing.\n"
            "💬 Istalgan savolni bering, javob beraman.\n\n"
            "/app - ilovani ochish\n"
            "/review - kartochkalarni takrorlash\n"
            "/list - mening so'zlarim\n"
            "/stats - statistika\n"
            "/lang - o'rganiladigan tilni almashtirish\n"
            "/base - bot tilini almashtirish\n"
            "/practice - suhbat amaliyoti\n"
            "/premium - cheklovsiz Premium\n"
            "/remind - eslatmalar"
        ),
    },
    "en": {
        "choose_base": "🦥 Hi! I'm Rimy, a polyglot sloth.\n\nWhich language would you like to talk to me in?",
        "choose_target": "Great! Which language are we learning? 🌍",
        "base_set": "Done: we'll talk in English 🇬🇧",
        "greeting": "Hi! 👋 I'm Rimy, a polyglot sloth 🦥",
        "learning": "Now learning",
        "help": (
            "🎙 <b>The easiest way: just send a voice message with the word.</b> Hold the mic button at the bottom right "
            "and say it, even in your own language. I'll understand, translate it and make the flashcard myself, no typing needed.\n\n"
            "📝 Text works too: type a word or a phrase.\n"
            "💬 Ask me anything, like \"how do I say 'I'm late'?\", and I'll answer.\n\n"
            "/app - open the app\n"
            "/review - review cards\n"
            "/list - my words\n"
            "/stats - statistics\n"
            "/lang - change the language you learn\n"
            "/base - change the bot's language\n"
            "/practice - conversation practice\n"
            "/premium - Premium, no limits\n"
            "/remind - reminders"
        ),
    },
}


def ui(native: str, key: str) -> str:
    return UI.get(native, UI["ru"])[key]


def help_text(lang: Lang, greeting: str, native: str = "ru") -> str:
    """Start / help message in the learner's base language."""
    if native != "ru":  # the mascot's canned phrases are Russian: use the localized greeting instead
        greeting = ui(native, "greeting")
    return (
        f"{esc(greeting)}\n\n{ui(native, 'learning')}: {lang.flag} <b>{esc(lang.name(native))}</b>.\n\n"
        + ui(native, "help")
    )


def render_word(w: dict, *, show_notes: bool = True) -> str:
    """Card body. Accepts a draft dict or a Word converted with word_to_dict()."""
    lines = [f"<b>{esc(w['display'] or w['lemma'])}</b>" + (f"  <i>{esc(w['pos'])}</i>" if w.get("pos") else "")]
    if w.get("reading"):
        lines.append(f"🔤 {esc(w['reading'])}")
    if w.get("translations"):
        lines.append("➜ " + esc("; ".join(w["translations"])))
    if w.get("example"):
        lines.append(f"\n📝 <i>{esc(w['example'])}</i>")
        if w.get("example_translation"):
            lines.append(f"     {esc(w['example_translation'])}")
    if show_notes and w.get("notes"):
        lines.append(f"\n💡 {esc(w['notes'])}")
    return "\n".join(lines)


def word_to_dict(word) -> dict:
    return {
        "lemma": word.lemma,
        "display": word.display,
        "reading": word.reading,
        "pos": word.pos,
        "translations": list(word.translations or []),
        "example": word.example,
        "example_translation": word.example_translation,
        "notes": word.notes,
    }
