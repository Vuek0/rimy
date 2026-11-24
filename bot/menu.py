"""The main menu: a persistent keyboard under the input field, in the learner's base language (ru / uz / en).

Handlers match a button with `button(REVIEW)` etc., which accepts its label in any of the languages.
"""

from aiogram import F
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Button ids (= the Russian labels)
REVIEW = "📚 Повторить"
WORDS = "📋 Мои слова"
STATS = "📊 Статистика"
PERSONA = "🎭 Персонаж"
PREMIUM = "⭐ Premium"
PRACTICE = "🗣 Практика"
LANGUAGE = "🌍 Язык"
MORE = "⚙️ Ещё"

BUTTONS = (REVIEW, WORDS, STATS, PREMIUM, LANGUAGE, PRACTICE, MORE)
LAYOUT = ((REVIEW, WORDS), (STATS, PREMIUM), (LANGUAGE, PRACTICE, MORE))

LABELS: dict[str, dict[str, str]] = {
    "ru": {b: b for b in BUTTONS},
    "uz": {
        REVIEW: "📚 Takrorlash",
        WORDS: "📋 So'zlarim",
        STATS: "📊 Statistika",
        PREMIUM: "⭐ Premium",
        LANGUAGE: "🌍 Til",
        PRACTICE: "🗣 Amaliyot",
        MORE: "⚙️ Yana",
    },
    "en": {
        REVIEW: "📚 Review",
        WORDS: "📋 My words",
        STATS: "📊 Stats",
        PREMIUM: "⭐ Premium",
        LANGUAGE: "🌍 Language",
        PRACTICE: "🗣 Practice",
        MORE: "⚙️ More",
    },
}

PLACEHOLDER = {
    "ru": "Слово текстом или голосовым 🎙",
    "uz": "So'zni yozing yoki ovozli yuboring 🎙",
    "en": "Type a word or send a voice message 🎙",
}

ALL_LABELS = {label for labels in LABELS.values() for label in labels.values()} | {PERSONA}


def button(button_id: str):
    """Filter: the message is this menu button, in any language."""
    return F.text.in_({labels.get(button_id, button_id) for labels in LABELS.values()} | {button_id})


# Text handlers waiting for free input (a word, a translation) must not take menu buttons
NOT_MENU = ~F.text.in_(ALL_LABELS)

MORE_TEXTS = {
    "ru": (
        "⚙️ <b>Ещё команды</b> - нажми на нужную:\n\n"
        "/app - открыть приложение\n"
        "/premium - Premium без лимитов\n"
        "/remind - напоминания\n"
        "/memory - что Рими помнит о тебе\n"
        "/lang - сменить изучаемый язык\n"
        "/base - язык общения с ботом\n"
        "/delete <i>слово</i> - удалить слово\n"
        "/help - помощь"
    ),
    "uz": (
        "⚙️ <b>Boshqa buyruqlar</b>:\n\n"
        "/app - ilovani ochish\n"
        "/premium - cheklovsiz Premium\n"
        "/remind - eslatmalar\n"
        "/lang - o'rganiladigan tilni almashtirish\n"
        "/base - bot tilini almashtirish\n"
        "/delete <i>so'z</i> - so'zni o'chirish\n"
        "/help - yordam"
    ),
    "en": (
        "⚙️ <b>More commands</b>:\n\n"
        "/app - open the app\n"
        "/premium - Premium, no limits\n"
        "/remind - reminders\n"
        "/memory - what Rimy remembers about you\n"
        "/lang - change the language you learn\n"
        "/base - change the bot's language\n"
        "/delete <i>word</i> - delete a word\n"
        "/help - help"
    ),
}
MORE_TEXT = MORE_TEXTS["ru"]


def more_text(native: str) -> str:
    return MORE_TEXTS.get(native, MORE_TEXT)


def main_keyboard(native: str = "ru") -> ReplyKeyboardMarkup:
    labels = LABELS.get(native, LABELS["ru"])
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=labels[b]) for b in row] for row in LAYOUT],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=PLACEHOLDER.get(native, PLACEHOLDER["ru"]),
    )
