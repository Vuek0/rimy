"""🔊 buttons: hear a word or its example pronounced by a native neural voice."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from bot import texts
from bot.audio import tts
from bot.db.models import Deck, User, Word
from bot.db.repo import Repo
from bot.i18n import tr
from bot.persona.card import PersonaCard

router = Router(name="speech")


def speech_buttons(word: Word) -> list[InlineKeyboardButton]:
    row = [InlineKeyboardButton(text=tr("speech.word"), callback_data=f"tts:w:{word.id}")]
    if word.example:
        row.append(InlineKeyboardButton(text=tr("speech.example"), callback_data=f"tts:e:{word.id}"))
    return row


@router.callback_query(F.data.startswith("tts:"))
async def on_speak(callback: CallbackQuery, repo: Repo, user: User, persona: PersonaCard) -> None:
    _, what, word_id = (callback.data or "tts:w:0").split(":")
    word = await repo.word_of_user(user, int(word_id)) if word_id.isdigit() else None
    if word is None or not isinstance(callback.message, Message):
        await callback.answer(tr("stale"))
        return
    deck = await repo.s.get(Deck, word.deck_id)
    text = word.example if what == "e" else (word.display or word.lemma)
    await callback.answer("🔊")
    if not await tts.send_speech(callback.message, repo, text, deck.target_lang, persona.gender):
        await callback.message.answer(tr("speech.unavailable"))
