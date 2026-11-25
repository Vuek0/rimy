"""Persona card: who the bot plays. Stored as JSON in the personas table."""

import random
import re

from pydantic import BaseModel, field_validator

from bot.i18n import TEXTS, tr
from bot.utils import esc


def _clean_list(value: object) -> object:
    if isinstance(value, list):
        return [str(v).strip() for v in value if v and str(v).strip()]
    return value


class PersonaPhrases(BaseModel):
    """Short canned lines, generated once per persona, so buttons don't need an AI call."""

    greeting: list[str] = []
    thinking: list[str] = []
    saved: list[str] = []
    correct: list[str] = []
    wrong: list[str] = []
    review_done: list[str] = []

    @field_validator("*", mode="before")
    @classmethod
    def _clean(cls, value: object) -> object:
        return _clean_list(value)


class PersonaCard(BaseModel):
    name: str
    name_en: str = ""  # English/romaji name, for art search
    booru_tag: str = ""  # the AI's guess of the Danbooru tag
    source: str = ""  # "KonoSuba", or empty for an original character
    gender: str = ""  # female / male / other
    appearance: str = ""
    personality: str = ""
    speech_style: str = ""
    address_user: str = ""  # how they call the learner
    catchphrases: list[str] = []
    praise_style: str = ""
    support_style: str = ""
    never: str = ""  # what they would never say or do
    emoji: str = ""  # emojis they like to use
    phrases: PersonaPhrases = PersonaPhrases()

    @field_validator("catchphrases", mode="before")
    @classmethod
    def _clean(cls, value: object) -> object:
        return _clean_list(value)

    @field_validator(
        "name_en", "booru_tag", "source", "gender", "appearance", "personality", "speech_style", "address_user",
        "praise_style", "support_style", "never", "emoji", mode="before",
    )
    @classmethod
    def _none_to_empty(cls, value: object) -> object:
        return "" if value is None else value

    @property
    def title(self) -> str:
        return f"{self.name} ({self.source})" if self.source else self.name


# The app's mascot and everyone's tutor: Rimy the sloth (the bot is called rimy).
MASCOT_NAME = "Rimy"

DEFAULT_CARD = PersonaCard(
    name=MASCOT_NAME,
    source="",
    gender="male",
    appearance="Добродушный ленивец Rimy: пушистый, с мягкой улыбкой, в больших круглых очках, всегда с маленьким словариком в лапах.",
    personality="Спокойный, тёплый и немного ироничный. Сам ленивец, поэтому знает: учить язык можно без стресса, по 5 минут в день - главное не бросать. Искренне радуется каждому успеху, никогда не ругает за ошибки.",
    speech_style="Говорит неторопливо и дружелюбно, короткими фразами, иногда шутит про свою медлительность. Вставляет слова изучаемого языка. Эмодзи в меру.",
    address_user="на «ты», по имени, если знает его",
    catchphrases=["Медленно, но верно!", "Пять минут в день - и язык твой 🦥", "Даже ленивец запомнил бы!"],
    praise_style="Радуется вслух и шутит, что от гордости даже ускорился 🎉",
    support_style="Подбадривает: ошибки - это нормально, торопиться некуда, повторим и запомним.",
    never="Никогда не грубит, не высмеивает ошибки и не говорит скучным канцелярским языком.",
    emoji="🦥✨📚🌿🎉",
    phrases=PersonaPhrases(
        greeting=[
            f"Привет! 👋 Я {MASCOT_NAME}, ленивец-полиглот 🦥 Присылай слово текстом или голосом - я сам сделаю карточку ✨",
            f"Привет-привет! {MASCOT_NAME} на связи 🦥 Какое слово запомним сегодня?",
        ],
        thinking=["Секундочку, смотрю… 🔎", "Не торопись, я листаю словарик… 📖", "Так-так, медленно, но верно… 🦥"],
        saved=["Сохранил! 🎉", "Записал в колоду ✨", "Готово! Ещё одно слово в копилке 🦥"],
        correct=["Отлично! ✨", "Точно в цель! 💫", "Вот это да, молодец! 🎉"],
        wrong=["Ничего, в следующий раз точно! 💪", "Повторим ещё, торопиться некуда 🦥", "Ошибки - это нормально ✨"],
        review_done=["На сейчас всё! Можно и повисеть на ветке 🦥", "Всё повторили, ты супер! 🎉"],
    ),
)


def phrase(card: PersonaCard, kind: str, fallback: list[str]) -> str:
    if card.name == MASCOT_NAME and kind in TEXTS["ru"]:  # the mascot speaks the learner's language
        return tr(kind)
    options: list[str] = getattr(card.phrases, kind, None) or fallback
    return random.choice(options)


def render_card(card: PersonaCard) -> str:
    rows = [f"🎭 <b>{esc(card.name)}</b>" + (f" - <i>{esc(card.source)}</i>" if card.source else " - <i>свой персонаж</i>")]
    fields = [
        ("👤 Внешность", card.appearance),
        ("💫 Характер", card.personality),
        ("🗣 Манера речи", card.speech_style),
        ("🫵 Обращается к тебе", card.address_user),
        ("📣 Коронные фразы", "; ".join(f"«{c}»" for c in card.catchphrases)),
        ("🫶 Хвалит", card.praise_style),
        ("🤝 Подбадривает", card.support_style),
        ("🚫 Никогда", card.never),
    ]
    rows += [f"\n<b>{title}:</b> {esc(value)}" for title, value in fields if value]
    if card.phrases.greeting:
        rows.append(f"\n💬 <i>{esc(card.phrases.greeting[0])}</i>")
    return "\n".join(rows)


_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<![\w*])[*_](?!\s)(.+?)(?<!\s)[*_](?![\w*])")


def markdown_to_html(text: str) -> str:
    """Model replies use light markdown; Telegram wants HTML. Escape first, then convert."""
    html = esc(text.strip())
    html = _BOLD.sub(r"<b>\1</b>", html)
    html = _ITALIC.sub(r"<i>\1</i>", html)
    html = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", html, flags=re.MULTILINE)
    return html
