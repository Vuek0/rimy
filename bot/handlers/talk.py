"""Talking to the persona: explanations, questions, small talk, practice mode."""

import logging
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import texts
from bot.ai.schemas import AIError
from bot.ai.service import AIService, PersonaReply, SuggestedWord
from bot.db.models import Deck, Persona, User
from bot.db.repo import Repo
from bot.images import arts
from bot.langs import get_lang
from bot.persona.card import PersonaCard, markdown_to_html
from bot.persona.context import context_block, snapshot
from bot.persona.memory import ChatMemory
from bot.utils import norm, utcnow
from bot import menu

log = logging.getLogger(__name__)
router = Router(name="talk")

MAX_REPLY_CHARS = 3500  # Telegram limit is 4096 after HTML conversion
MAX_CALLBACK_BYTES = 64

# Starts of messages that are clearly not "a word to add" - skip the AI router for obvious words.
_NOT_A_WORD = re.compile(
    r"^(как|что|почему|зачем|когда|где|какой|какая|какое|какие|чем|объясни|расскажи|поясни|переведи|скажи|"
    r"можно|а\b|привет|здравствуй|спасибо|пока|hi|hello|ciao|grazie|buongiorno|buonasera)",
    re.IGNORECASE,
)


def looks_like_word(text: str) -> bool:
    """1-3 words, no question: almost certainly a word or phrase to add."""
    return len(text.split()) <= 3 and not re.search(r"[?!]", text) and not _NOT_A_WORD.match(text.strip())


async def split_known(
    repo: Repo, deck_id: int, words: list[SuggestedWord]
) -> tuple[list[SuggestedWord], list[SuggestedWord]]:
    """Dedupe suggested words and split them into (new, already in the deck)."""
    new: list[SuggestedWord] = []
    known: list[SuggestedWord] = []
    seen: set[str] = set()
    for item in words:
        key = norm(item.word)
        if not key or key in seen:
            continue
        seen.add(key)
        (known if await repo.find_words(deck_id, item.word) else new).append(item)
    return new, known


def _label(item: SuggestedWord, limit: int = 45) -> str:
    text = f"{item.word} - {item.meaning}" if item.meaning else item.word
    return text if len(text) <= limit else text[: limit - 1] + "…"


def add_word_buttons(new: list[SuggestedWord], known: list[SuggestedWord] = ()) -> InlineKeyboardMarkup | None:
    rows = [
        [InlineKeyboardButton(text=f"➕ {_label(w)}", callback_data=f"aw:{w.word}")]
        for w in new
        if len(f"aw:{w.word}".encode()) <= MAX_CALLBACK_BYTES
    ]
    rows += [[InlineKeyboardButton(text=f"✅ {w.word} - уже в колоде", callback_data="awknown")] for w in known]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def words_hint(new: list, known: list) -> str:
    if new:
        return "\n\n<i>👇 Слова из ответа можно добавить себе в колоду - жми ➕</i>"
    if known:
        return "\n\n<i>✅ Все слова отсюда уже есть в твоей колоде</i>"
    return ""


@router.callback_query(F.data == "awknown")
async def on_known_word(callback: CallbackQuery) -> None:
    await callback.answer("Это слово уже есть в колоде 🙂")


def _mentioned(replied: str, history: list[dict[str, str]]) -> bool:
    """Is this (rendered) bot message already in the history (stored as raw markdown)?"""
    sample = norm(replied.replace("*", ""))[:60]
    return any(sample and sample in norm(m["content"].replace("*", "")) for m in history)


async def answer_as_persona(
    status: Message,
    text: str,
    ai: AIService,
    repo: Repo,
    memory: ChatMemory,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    prefix: str = "",
    persona_row: Persona | None = None,
    small_talk: bool = False,
    replied: str = "",
) -> None:
    """Persona answers. A sticker may follow only in small talk with a strong emotion - never on questions.

    replied: the bot message the user answered with "Reply". If it's not in memory (older, or the bot
    restarted), it's added to the context so the persona knows what is being answered.
    """
    history = memory.history(user.id)
    if replied and not _mentioned(replied, history):
        history = [*history, {"role": "assistant", "content": replied}]
    now = utcnow()
    snap = await snapshot(repo, user, deck, now, memory.previous_active(user.id))
    try:
        reply = await ai.persona_reply(
            persona, history, text, deck.target_lang, user.native_lang, user.practice_mode, context_block(snap)
        )
    except AIError:
        log.exception("persona reply failed")
        await status.edit_text(texts.AI_ERROR)
        return
    memory.add(user.id, "user", text)
    memory.add(user.id, "assistant", reply.text)
    await remember_from_reply(repo, user, text, reply, now)
    body = reply.text if len(reply.text) <= MAX_REPLY_CHARS else reply.text[:MAX_REPLY_CHARS] + "…"
    new, known = await split_known(repo, deck.id, reply.words)
    # ➕ buttons only carry the word (64-byte limit): remember its meaning and the reply for when one is pressed
    memory.remember_words(status.chat.id, status.message_id, {w.word: w.meaning for w in new}, reply.text)
    await status.edit_text(
        prefix + markdown_to_html(body) + words_hint(new, known), reply_markup=add_word_buttons(new, known)
    )
    if persona_row is None:
        return
    if reply.sticker:  # asked for a sticker, or a big moment: always, even outside small talk
        emotion = reply.emotion if reply.emotion != "none" else "happy"
        await arts.send_reaction(status, repo, persona_row, persona, "chat", emotion=emotion, force=True)
    elif small_talk and reply.emotion != "none":
        await arts.send_reaction(status, repo, persona_row, persona, "chat", emotion=reply.emotion)


async def remember_from_reply(repo: Repo, user: User, text: str, reply: PersonaReply, now: datetime) -> None:
    """Long-term memory: keep the conversation, new facts, the user's name and gender."""
    await repo.add_chat(user.id, "user", text, now)
    await repo.add_chat(user.id, "assistant", reply.text, now)
    if reply.remember:
        added = await repo.add_facts(user.id, reply.remember, now)
        if added:
            log.info("remembered about the user: %s", added)
    if reply.user_name:
        user.name = reply.user_name
    if reply.user_gender:
        user.gender = reply.user_gender


async def reset_conversation(memory: ChatMemory, repo: Repo, user_id: int) -> None:
    """A new persona starts a new conversation (facts about the user are kept: they're about the user)."""
    memory.clear(user_id)
    await repo.clear_chat(user_id)


@router.message(Command("practice"))
@router.message(menu.button(menu.PRACTICE))
async def cmd_practice(
    message: Message, state: FSMContext, user: User, deck: Deck, persona: PersonaCard, memory: ChatMemory
) -> None:
    await state.clear()
    user.practice_mode = not user.practice_mode
    lang = get_lang(deck.target_lang)
    if user.practice_mode:
        await message.answer(
            f"🗣 Режим практики включён! {persona.name} будет болтать с тобой {lang.adverb_ru} и поправлять ошибки.\n\n"
            "Слова в колоду добавляются как обычно: пришли одно слово или нажми ➕ под ответом.\n"
            "Выключить: /practice"
        )
    else:
        await message.answer(f"Режим практики выключен. {persona.name} снова говорит по-русски 🙂")
