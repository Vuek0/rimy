"""/list, /delete, /stats."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import texts
from bot.db.models import Deck, User
from bot.db.repo import Repo
from bot.i18n import tr
from bot.langs import get_lang
from bot.utils import compute_streak, esc, utcnow
from bot import menu

router = Router(name="words")

LIST_LIMIT = 50


@router.message(Command("list"))
@router.message(menu.button(menu.WORDS))
async def cmd_list(message: Message, state: FSMContext, repo: Repo, deck: Deck) -> None:
    await state.clear()
    lang = get_lang(deck.target_lang)
    total = await repo.count_words(deck.id)
    if total == 0:
        await message.answer(tr("words.empty"))
        return
    words = await repo.list_words(deck.id, LIST_LIMIT)
    lines = [f"{lang.flag} <b>" + tr("words.title", n=total) + "</b>" + (tr("words.last", n=LIST_LIMIT) if total > LIST_LIMIT else ":")]
    lines += [f"• <b>{esc(w.display)}</b> - {esc('; '.join(w.translations))}" for w in words]
    await message.answer("\n".join(lines))


@router.message(Command("delete"))
async def cmd_delete(message: Message, command: CommandObject, state: FSMContext, repo: Repo, deck: Deck) -> None:
    await state.clear()
    query = (command.args or "").strip()
    if not query:
        await message.answer(tr("delete.usage"))
        return
    found = await repo.find_words(deck.id, query)
    if not found:
        await message.answer(tr("delete.not_found", q=esc(query)))
        return
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 {w.display} - {'; '.join(w.translations)}"[:60], callback_data=f"del:{w.id}"
            )
        ]
        for w in found[:5]
    ]
    rows.append([InlineKeyboardButton(text=tr("cancel"), callback_data="del:no")])
    await message.answer(tr("delete.what"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("del:"))
async def on_delete(callback: CallbackQuery, repo: Repo, deck: Deck) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    choice = (callback.data or "").split(":", 1)[1]
    if choice == "no":
        await message.edit_text(tr("delete.nothing"))
        return
    word = await repo.get_word(int(choice))
    if word is None or word.deck_id != deck.id:
        await message.edit_text(tr("stale"))
        return
    display = word.display
    await repo.delete_word(word.id)
    await message.edit_text(tr("delete.done", w=esc(display)))


@router.message(Command("stats"))
@router.message(menu.button(menu.STATS))
async def cmd_stats(message: Message, state: FSMContext, repo: Repo, user: User, deck: Deck) -> None:
    await state.clear()
    tz = ZoneInfo(user.timezone)
    now = utcnow()
    today = now.astimezone(tz).date()

    total = await repo.count_words(deck.id)
    due = await repo.count_due(deck.id, now)
    times = await repo.review_times(deck.id, since=now - timedelta(days=366))
    days = {t.astimezone(tz).date() for t in times}
    reviewed_today = sum(1 for t in times if t.astimezone(tz).date() == today)
    streak = compute_streak(days, today)

    lang = get_lang(deck.target_lang)
    await message.answer(
        f"📊 {lang.flag} <b>{lang.name(user.native_lang)}</b>\n\n"
        + tr("stats.body", total=total, due=due, today=reviewed_today, streak=streak)
    )
