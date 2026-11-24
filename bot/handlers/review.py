"""Flashcard review session: front → answer (typed, spoken, or «show answer») → Again/Hard/Good/Easy → next.

A shown card waits for an answer: text or a voice message is checked by the AI (synonyms, typos,
pronunciation), then the answer is revealed with a suggested grade - the user still picks the grade.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import menu, srs, texts
from bot.ai.schemas import AIError
from bot.ai.service import AIService, AnswerCheck
from bot.billing import Billing
from bot.db.models import Card, Deck, Persona, User
from bot.db.repo import Repo
from bot.handlers.speech import speech_buttons
from bot.images import arts
from bot.langs import get_lang
from bot.persona.card import PersonaCard, phrase
from bot.persona.memory import ChatMemory
from bot.utils import esc, format_interval, utcnow

router = Router(name="review")

RATINGS = {1: ("🔁", "Снова"), 2: ("😬", "Трудно"), 3: ("👍", "Хорошо"), 4: ("😎", "Легко")}
VERDICT_LINES = {"correct": "✅ Верно!", "almost": "🟡 Почти!", "wrong": "❌ Не совсем"}
ANSWER_HINT = "\n\n<i>💬 Ответь текстом или голосом - или открой ответ</i>"


def front_text(card: Card, deck: Deck, user: User) -> str:
    word = card.word
    if card.direction == "fwd":
        return f"{get_lang(deck.target_lang).flag} <b>{esc(word.display)}</b>\n\n<i>Как переводится?</i>"
    target = get_lang(deck.target_lang)
    return (
        f"{get_lang(user.native_lang).flag} <b>{esc('; '.join(word.translations))}</b>\n\n"
        f"<i>Как будет {target.adverb_ru}?</i>"
    )


def answer_view(card: Card, deck: Deck, user: User, suggested: int | None = None, extra: str = "") -> tuple[str, InlineKeyboardMarkup]:
    """The revealed card: question, answer, optional verdict, grade buttons (the suggested one marked 👉)."""
    intervals = srs.preview(card.fsrs, utcnow())
    buttons = [
        InlineKeyboardButton(
            text=("👉 " if rating == suggested else "") + f"{emoji} {label} · {format_interval(intervals[rating])}",
            callback_data=f"rate:{card.id}:{rating}",
        )
        for rating, (emoji, label) in RATINGS.items()
    ]
    text = (
        front_text(card, deck, user) + extra + "\n\n━━━━━━━━━━\n" + texts.render_word(texts.word_to_dict(card.word))
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:], speech_buttons(card.word)])


async def send_next_card(
    message: Message,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    just_reviewed: int | None = None,
    memory: ChatMemory | None = None,
) -> None:
    now = utcnow()
    card = await repo.next_due_card(deck.id, now, just_reviewed)
    if card is None:
        if memory is not None:
            memory.stop_waiting(user.id)
        next_at = await repo.next_due_at(deck.id)
        if next_at is None:
            await message.answer("В колоде пока нет слов. Пришли мне слово - и начнём! ✨")
        else:
            done = phrase(persona, "review_done", ["На сейчас всё повторено! 🎉"])
            text = f"{esc(done)}\nСледующая карточка через {format_interval(next_at - now)}."
            if not await arts.send_reaction(message, repo, persona_row, persona, "review_done", text):
                await message.answer(text)
        return
    left = await repo.count_due(deck.id, now)
    header = f"<i>Осталось: {left}</i>\n\n" if left > 1 else ""
    rows = [[InlineKeyboardButton(text="👀 Показать ответ", callback_data=f"show:{card.id}")]]
    if card.direction == "fwd":  # the front is the foreign word: hearing it gives nothing away
        rows[0].append(InlineKeyboardButton(text="🔊", callback_data=f"tts:w:{card.word_id}"))
    hint = ANSWER_HINT if memory is not None else ""
    sent = await message.answer(
        header + front_text(card, deck, user) + hint, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    if memory is not None:
        memory.await_answer(user.id, card.id, sent.chat.id, sent.message_id)


@router.message(Command("review"))
@router.message(menu.button(menu.REVIEW))
async def cmd_review(
    message: Message,
    state: FSMContext,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    memory: ChatMemory,
) -> None:
    await state.clear()
    await send_next_card(message, repo, user, deck, persona, persona_row, memory=memory)


@router.callback_query(F.data == "rv:start")
async def on_start_review(
    callback: CallbackQuery,
    state: FSMContext,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    memory: ChatMemory,
) -> None:
    """«📚 Начать повторение» under a reminder."""
    await callback.answer()
    if isinstance(callback.message, Message):
        await state.clear()
        await callback.message.edit_reply_markup(reply_markup=None)
        await send_next_card(callback.message, repo, user, deck, persona, persona_row, memory=memory)


@router.callback_query(F.data.startswith("show:"))
async def on_show(callback: CallbackQuery, repo: Repo, user: User, deck: Deck, memory: ChatMemory) -> None:
    card = await repo.get_card(int((callback.data or "").split(":")[1]))
    message = callback.message
    if card is None or not isinstance(message, Message):
        await callback.answer(texts.STALE)
        return
    await callback.answer()
    memory.stop_waiting(user.id)
    text, keyboard = answer_view(card, deck, user)
    await message.edit_text(text, reply_markup=keyboard)


# --- answering a card by text or voice ---


def expected_answer(card: Card, deck: Deck, user: User) -> tuple[str, str, str]:
    """(question, correct answer, language the answer is in) for the AI check."""
    word = card.word
    translations = "; ".join(word.translations)
    target_answer = word.display + (f" ({word.reading})" if word.reading else "")
    if card.direction == "fwd":
        return f"translate «{word.display}»", translations, user.native_lang
    return f"say in the target language: «{translations}»", target_answer, deck.target_lang


def answer_language(card: Card, deck: Deck, user: User) -> str:
    return user.native_lang if card.direction == "fwd" else deck.target_lang


async def answer_card(
    message: Message,
    answer: str,
    voice: bool,
    ai: AIService,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    memory: ChatMemory,
    billing: Billing | None = None,
) -> bool:
    """Check an answer to the waiting card. False if the message wasn't an answer (handle it as usual).

    On the free plan past today's AI-check limit the answer is still accepted, just shown without a verdict.
    """
    waiting = memory.waiting_answer(user.id)
    if waiting is None:
        return False
    card_id, chat_id, card_message_id = waiting
    card = await repo.get_card(card_id)
    if card is None:
        memory.stop_waiting(user.id)
        return False
    question, expected, lang = expected_answer(card, deck, user)
    quota = await billing.try_consume(user, "check", utcnow()) if billing is not None else None
    if quota is not None and quota.exceeded:
        check = AnswerCheck("unknown", 0, "AI-проверки на сегодня закончились - сравни сам(а) и выбери оценку. /premium ⭐")
    else:
        try:
            check = await ai.check_answer(
                persona, question, expected, answer, voice, lang, deck.target_lang, user.native_lang, user.gender
            )
        except AIError:
            check = AnswerCheck("unknown", 0, "")
    if check.verdict == "not_answer":
        return False  # a question or chat while a card is open: the usual flow handles it

    memory.stop_waiting(user.id)
    try:  # the card's «show answer» button is no longer needed
        await message.bot.edit_message_reply_markup(chat_id=chat_id, message_id=card_message_id, reply_markup=None)
    except Exception:
        pass
    heard = f"\n\n🎧 Ты сказал(а): <b>{esc(answer)}</b>" if voice else f"\n\n✍️ Твой ответ: <b>{esc(answer)}</b>"
    verdict = VERDICT_LINES.get(check.verdict, "")
    comment = f"\n<i>{esc(check.comment)}</i>" if check.comment else ""
    text, keyboard = answer_view(card, deck, user, check.rating or None, heard + (f"\n{verdict}" if verdict else "") + comment)
    await message.answer(text, reply_markup=keyboard)
    return True


@router.callback_query(F.data.startswith("rate:"))
async def on_rate(
    callback: CallbackQuery,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    memory: ChatMemory,
    billing: Billing,
) -> None:
    _, card_id, rating_str = (callback.data or "").split(":")
    card = await repo.card_of_deck(deck.id, int(card_id))
    message = callback.message
    if card is None or not isinstance(message, Message):
        await callback.answer(texts.STALE)
        return
    last = await repo.last_review_at(card.id)
    if last is not None and last >= message.date:
        await callback.answer("Уже оценено 🙂")
        return
    await callback.answer()

    rating = int(rating_str)
    now = utcnow()
    new_state, due = srs.review(card.fsrs, rating, now)
    await repo.record_review(card, rating, new_state, due, now)
    await billing.track_once(user.id, "first_review", now, source="bot")

    emoji, label = RATINGS[rating]
    if rating == 1:
        reaction = phrase(persona, "wrong", ["Ничего, повторим! 💪"])
    else:
        reaction = phrase(persona, "correct", ["Отлично! ✨"])
    await message.edit_text(
        message.html_text
        + f"\n\n{emoji} {label} · следующий раз через {format_interval(due - now)}\n<i>{esc(reaction)}</i>"
    )
    await arts.send_reaction(message, repo, persona_row, persona, "wrong" if rating == 1 else "correct")
    await send_next_card(message, repo, user, deck, persona, persona_row, just_reviewed=card.id, memory=memory)
