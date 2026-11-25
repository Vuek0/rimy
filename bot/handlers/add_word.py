"""Adding words: text/voice → AI analysis → clarify (typo? which meaning?) → preview → save."""

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import achievements, texts
from bot.ai.service import AIService
from bot.ai.schemas import AIError, Sense, WordAnalysis
from bot.billing import Billing
from bot.db.models import Deck, Persona, User
from bot.db.repo import Repo
from bot.handlers import review
from bot.handlers.speech import speech_buttons
from bot.handlers.talk import answer_as_persona, looks_like_word
from bot.images import arts
from bot.persona.card import PersonaCard, phrase
from bot.persona.memory import ChatMemory
from bot.utils import esc, norm, utcnow
from bot import menu
from bot.i18n import tr

log = logging.getLogger(__name__)
router = Router(name="add_word")

MAX_INPUT_CHARS = 120  # a word or phrase for a flashcard
MAX_MESSAGE_CHARS = 1500  # a question / chat message
MAX_VOICE_SECONDS = 30
MAX_SENSES = 4


class AddWord(StatesGroup):
    fix = State()  # "did you mean …?"
    sense = State()  # "which meaning?"
    confirm = State()  # preview with Save / Edit / Cancel
    edit = State()  # waiting for a custom translation


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(tr("add.save_btn"), "add:save")],
            [_btn(tr("add.edit_btn"), "add:edit"), _btn(tr("add.cancel_btn"), "add:cancel")],
        ]
    )


def make_draft(analysis: WordAnalysis, senses: list[Sense], fallback: str) -> dict[str, Any]:
    lemma = analysis.lemma.strip() or fallback.strip()
    first = senses[0] if senses else None
    return {
        "lemma": lemma,
        "display": analysis.display.strip() or lemma,
        "reading": analysis.reading.strip(),
        "pos": analysis.pos.strip(),
        "translations": [s.translation.strip() for s in senses],
        "example": first.example.strip() if first else "",
        "example_translation": first.example_translation.strip() if first else "",
        "notes": analysis.notes.strip(),
    }


# --- entry points: text & voice ---


@router.message(AddWord.edit, F.text, ~F.text.startswith("/"), menu.NOT_MENU)
async def on_custom_translation(message: Message, state: FSMContext, repo: Repo, deck: Deck) -> None:
    data = await state.get_data()
    draft = data.get("draft")
    if not draft:
        await state.clear()
        await message.answer(tr("stale"))
        return
    translations = [part.strip() for part in re.split(r"[;,\n]", message.text or "") if part.strip()]
    if not translations:
        await message.answer(tr("add.write_translation"))
        return
    draft["translations"] = translations
    status = await message.answer("👌")
    await show_preview(status, state, repo, deck, draft)


@router.message(F.text, ~F.text.startswith("/"))
async def on_text(
    message: Message,
    state: FSMContext,
    ai: AIService,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    memory: ChatMemory,
    billing: Billing,
) -> None:
    text = (message.text or "").strip()
    if len(text) > MAX_MESSAGE_CHARS:
        await message.answer(tr("too_long"))
        return
    await state.clear()
    if memory.waiting_answer(user.id) and len(text) <= MAX_INPUT_CHARS:  # an answer to the open review card?
        status = await message.answer(tr("add.checking"))
        if await review.answer_card(message, text, False, ai, repo, user, deck, persona, memory, billing=billing):
            await status.delete()
            return
        await status.edit_text(phrase(persona, "thinking", texts.THINKING))
    else:
        status = await message.answer(phrase(persona, "thinking", texts.THINKING))
    await dispatch(
        status, text, state, ai, repo, user, deck, persona, persona_row, memory,
        replied=replied_text(message), billing=billing,
    )


@router.message(F.voice | F.audio)
async def on_voice(
    message: Message,
    bot: Bot,
    state: FSMContext,
    ai: AIService,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    memory: ChatMemory,
    billing: Billing,
) -> None:
    media = message.voice or message.audio
    assert media is not None
    if media.duration and media.duration > MAX_VOICE_SECONDS:
        await message.answer(tr("add.voice_too_long", n=MAX_VOICE_SECONDS))
        return
    await state.clear()
    quota = await billing.try_consume(user, "voice", utcnow())
    if quota.refused:
        await message.answer(billing.limit_message(quota, user.native_lang) + tr("add.text_now"))
        return
    status = await message.answer(tr("add.listening"))
    buffer = await bot.download(media)
    if buffer is None:
        await status.edit_text(tr("add.download_failed"))
        return
    # An answer to the open review card is expected in a known language: tell speech recognition first
    waiting = memory.waiting_answer(user.id)
    card = await repo.get_card(waiting[0]) if waiting else None
    expect = review.answer_language(card, deck, user) if card else deck.target_lang
    other = user.native_lang if expect == deck.target_lang else deck.target_lang
    try:
        # In practice mode or when answering a card the language is known: tell recognition not to guess
        force = card is not None or user.practice_mode
        heard = await ai.transcribe(buffer.read(), media.mime_type or "audio/ogg", expect, other, force)
    except AIError:
        log.exception("transcription failed")
        await status.edit_text(tr("ai_error"))
        return
    if not heard:
        await status.edit_text(tr("add.not_heard"))
        return
    if card is not None:
        await status.edit_text(tr("add.heard", text=esc(heard)) + "\n" + tr("add.checking"))
        if await review.answer_card(message, heard, True, ai, repo, user, deck, persona, memory, billing=billing):
            await status.delete()
            return
    await dispatch(
        status, heard, state, ai, repo, user, deck, persona, persona_row, memory,
        heard=True, replied=replied_text(message), billing=billing,
    )


def replied_text(message: Message) -> str:
    """If the user answered one of the bot's messages with Telegram's "Reply", that message's text."""
    original = message.reply_to_message
    if original is None or original.from_user is None or not original.from_user.is_bot:
        return ""
    return (original.text or original.caption or "").strip()


async def dispatch(
    status: Message,
    text: str,
    state: FSMContext,
    ai: AIService,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    memory: ChatMemory,
    heard: bool = False,
    replied: str = "",
    billing: Billing | None = None,
) -> None:
    """A word → flashcard flow; a question or small talk → the persona answers.

    billing: counts the free plan's daily AI actions (None in tests: no limits).

    replied: text of the bot message the user answered with Telegram's "Reply".
    While a conversation is going on, even a one-word message may be an answer, so the AI decides
    (seeing what the persona said last) instead of the quick "1-3 words = a word" rule.
    """
    prefix = tr("add.heard", text=esc(text)) + "\n\n" if heard else ""
    previous = replied or (memory.last_reply(user.id) if memory.in_conversation(user.id) else "")
    word = text
    if previous or user.practice_mode or not looks_like_word(text):
        try:
            route = await ai.route(text, deck.target_lang, user.native_lang, previous)
        except AIError:
            log.exception("routing failed")
            await status.edit_text(tr("ai_error"))
            return
        if route.intent != "word":
            # a voice message was already counted as "voice": one message = one action from the quota
            if not heard and not await _consume(status, billing, user, "chat", prefix):
                return
            await answer_as_persona(
                status, text, ai, repo, memory, user, deck, persona, prefix,
                persona_row=persona_row, small_talk=route.intent == "chat", replied=replied,
            )
            return
        word = route.word or text
    memory.end_conversation(user.id)  # adding words now: the next short messages are words again
    if len(word) > MAX_INPUT_CHARS:
        await status.edit_text(prefix + tr("too_long"))
        return
    if not heard and not await _consume(status, billing, user, "word", prefix):
        return
    await analyze_and_handle(status, word, state, ai, repo, user, deck, prefix)


async def _consume(status: Message, billing: Billing | None, user: User, kind: str, prefix: str = "") -> bool:
    """Count one AI action of the free plan; False (and the paywall message) if today's limit is used up."""
    if billing is None:
        return True
    quota = await billing.try_consume(user, kind, utcnow())
    if quota.refused:
        await status.edit_text(prefix + billing.limit_message(quota, user.native_lang))
        return False
    return True


async def analyze_and_handle(
    status: Message,
    word: str,
    state: FSMContext,
    ai: AIService,
    repo: Repo,
    user: User,
    deck: Deck,
    prefix: str = "",
    meaning: str = "",
    context: str = "",
) -> None:
    try:
        analysis = await ai.analyze_text(word, deck.target_lang, user.native_lang, meaning, context)
    except AIError:
        log.exception("text analysis failed")
        await status.edit_text(tr("ai_error"))
        return
    await handle_analysis(status, state, repo, deck, analysis, original=word, prefix=prefix)


@router.callback_query(F.data.startswith("aw:"))
async def on_add_suggested(
    callback: CallbackQuery,
    state: FSMContext,
    ai: AIService,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    memory: ChatMemory,
    billing: Billing,
) -> None:
    """➕ under a persona reply: add that word with the meaning it had in that reply."""
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    word = (callback.data or "")[3:].strip()
    meaning, context = memory.word_hint(message.chat.id, message.message_id, word)
    await state.clear()
    status = await message.answer(phrase(persona, "thinking", texts.THINKING))
    if not await _consume(status, billing, user, "word"):
        return
    await analyze_and_handle(status, word, state, ai, repo, user, deck, meaning=meaning, context=context)


# --- flow ---


async def handle_analysis(
    status: Message,
    state: FSMContext,
    repo: Repo,
    deck: Deck,
    analysis: WordAnalysis,
    original: str,
    prefix: str = "",
) -> None:
    issues = "".join(f"\n• {esc(issue)}" for issue in analysis.issues)
    same = {norm(original), norm(analysis.lemma)} if analysis.user_translation else {norm(original)}
    suggestions = [s for s in analysis.suggestions if norm(s) not in same][:3]

    if suggestions:
        await state.set_state(AddWord.fix)
        await state.update_data(
            original=original, suggestions=suggestions, analysis=analysis.model_dump(), prefix=prefix
        )
        rows = [[_btn(f"✨ {_short(s)}", f"fix:{i}")] for i, s in enumerate(suggestions)]
        rows.append([_btn(tr("add.keep", word=_short(original, 30)), "fix:keep")])
        await status.edit_text(
            prefix + tr("add.did_you_mean", word=esc(original), issues=issues),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return

    if not analysis.is_valid and not analysis.senses:
        await state.clear()
        await status.edit_text(prefix + tr("add.not_found", issues=issues))
        return

    await go_senses(status, state, repo, deck, analysis, original, prefix)


@router.callback_query(AddWord.fix, F.data.startswith("fix:"))
async def on_fix(callback: CallbackQuery, state: FSMContext, ai: AIService, repo: Repo, user: User, deck: Deck) -> None:
    await callback.answer()
    message = callback.message
    data = await state.get_data()
    if not isinstance(message, Message) or "analysis" not in data:
        return
    choice = (callback.data or "").split(":", 1)[1]
    prefix = data.get("prefix", "")
    if choice == "keep":
        analysis = WordAnalysis.model_validate(data["analysis"])
        word = data["original"]
    else:
        word = data["suggestions"][int(choice)]
        await message.edit_text(tr("add.looking", word=esc(word)))
        try:
            analysis = await ai.analyze_text(word, deck.target_lang, user.native_lang)
        except AIError:
            log.exception("re-analysis failed")
            await state.clear()
            await message.edit_text(tr("ai_error"))
            return
    await go_senses(message, state, repo, deck, analysis, word, prefix)


async def go_senses(
    message: Message, state: FSMContext, repo: Repo, deck: Deck, analysis: WordAnalysis, original: str, prefix: str
) -> None:
    senses = analysis.senses[:MAX_SENSES]

    if analysis.user_translation:  # "macchina - машина": the learner's own translation, no meaning to pick
        draft = make_draft(analysis, senses[:1], original)
        draft["translations"] = [analysis.user_translation]
        await show_preview(message, state, repo, deck, draft, prefix)
        return

    if not senses:
        draft = make_draft(analysis, [], original)
        await state.set_state(AddWord.edit)
        await state.update_data(draft=draft)
        await message.edit_text(
            prefix + tr("add.no_translation", word=esc(draft["display"]))
        )
        return

    if len(senses) == 1:
        await show_preview(message, state, repo, deck, make_draft(analysis, senses, original), prefix)
        return

    await state.set_state(AddWord.sense)
    await state.update_data(analysis=analysis.model_dump(), original=original, prefix=prefix)
    display = analysis.display or analysis.lemma or original
    lines = [
        f"{i + 1}. {esc(s.translation)}" + (f" <i>({esc(s.note)})</i>" if s.note else "")
        for i, s in enumerate(senses)
    ]
    rows = [[_btn(f"{i + 1}. {_short(s.translation)}", f"sense:{i}")] for i, s in enumerate(senses)]
    rows.append([_btn(tr("add.all_senses"), "sense:all")])
    await message.edit_text(
        prefix + tr("add.which_sense", word=esc(display)) + "\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(AddWord.sense, F.data.startswith("sense:"))
async def on_sense(callback: CallbackQuery, state: FSMContext, repo: Repo, deck: Deck) -> None:
    await callback.answer()
    data = await state.get_data()
    if not isinstance(callback.message, Message) or "analysis" not in data:
        return
    analysis = WordAnalysis.model_validate(data["analysis"])
    senses = analysis.senses[:MAX_SENSES]
    choice = (callback.data or "").split(":", 1)[1]
    chosen = senses if choice == "all" else [senses[int(choice)]]
    draft = make_draft(analysis, chosen, data.get("original", ""))
    await show_preview(callback.message, state, repo, deck, draft, data.get("prefix", ""))


async def show_preview(
    message: Message, state: FSMContext, repo: Repo, deck: Deck, draft: dict[str, Any], prefix: str = ""
) -> None:
    await state.set_state(AddWord.confirm)
    await state.update_data(draft=draft)
    text = prefix + texts.render_word(draft)
    duplicates = await repo.find_duplicates(deck.id, draft["lemma"])
    if duplicates:
        existing = "; ".join(t for d in duplicates for t in d.translations)
        text += tr("add.duplicate", t=esc(existing))
    await message.edit_text(text, reply_markup=confirm_kb())


@router.callback_query(AddWord.confirm, F.data.startswith("add:"))
async def on_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    repo: Repo,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    user: User,
    billing: Billing,
) -> None:
    await callback.answer()
    message = callback.message
    data = await state.get_data()
    draft = data.get("draft")
    if not isinstance(message, Message) or not draft:
        return
    action = (callback.data or "").split(":", 1)[1]

    if action == "save":
        now = utcnow()
        word = await repo.add_word(deck.id, draft, now)
        await billing.track_once(user.id, "first_word", now, source="bot")
        await billing.track(user.id, "word_saved", now, source="bot", lang=deck.target_lang)
        await state.clear()
        await message.edit_text(
            texts.render_word(draft) + f"\n\n{esc(phrase(persona, 'saved', texts.SAVED))} " + tr("add.review_later"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[speech_buttons(word)]),
        )
        # A shareable card for a streak or vocabulary milestone; otherwise a sticker for smaller occasions.
        if message.bot and await achievements.celebrate(message.bot, repo, billing, user, deck, now, word_saved=True):
            return
        if milestone := await word_milestone(repo, deck.id, word.id, user.timezone, now):
            if not await arts.send_reaction(message, repo, persona_row, persona, "milestone", milestone, force=True):
                await message.answer(milestone)
    elif action == "edit":
        await state.set_state(AddWord.edit)
        await message.edit_reply_markup(reply_markup=None)
        await message.answer(tr("add.own_translation"))
    else:
        await state.clear()
        await message.edit_text(texts.render_word(draft) + "\n\n" + tr("add.not_saving"))


# --- milestones: the only time saving a word gets a sticker ---

TOTAL_MILESTONES = {25, 50, 100, 200, 300, 500, 750, 1000}
DAILY_MILESTONE = 10
COMEBACK_AFTER = timedelta(days=3)


async def word_milestone(repo: Repo, deck_id: int, word_id: int, timezone: str, now: datetime) -> str | None:
    """Text to celebrate with, or None. Checked right after a word is saved."""
    total = await repo.count_words(deck_id)
    if total in TOTAL_MILESTONES or (total > 1000 and total % 500 == 0):
        return tr("milestone.total", n=total)
    previous = await repo.previous_word_at(deck_id, word_id)
    if previous is not None and now - previous >= COMEBACK_AFTER:
        return tr("milestone.comeback", n=(now - previous).days)
    tz = ZoneInfo(timezone)
    midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    if await repo.count_words_since(deck_id, midnight) == DAILY_MILESTONE:
        return tr("milestone.daily", n=DAILY_MILESTONE)
    return None
