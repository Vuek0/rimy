"""/stickers: choose which stickers the persona sends, per emotion. Plus: forward any sticker to add it."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import texts
from bot.db.models import Persona, PersonaArt, User
from bot.db.repo import Repo
from bot.images import arts
from bot.images.arts import STICKER_EMOTIONS
from bot.persona.card import PersonaCard
from bot.utils import esc

from bot.i18n import tr

router = Router(name="stickers")

NEW_PER_PAGE = 4  # fresh candidates per "show more"
FORWARD_HINT = "📥 Можно переслать мне <b>любой стикер</b> из Telegram - привяжу его к эмоции."


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def art_keyboard(art: PersonaArt) -> InlineKeyboardMarkup:
    pin = _btn("✅ В наборе" if art.pinned else "➕ В набор", f"st:p:{art.id}")
    return InlineKeyboardMarkup(inline_keyboard=[[pin, _btn("👎 Убрать", f"st:b:{art.id}")]])


async def _menu(repo: Repo, persona_row: Persona) -> tuple[str, InlineKeyboardMarkup]:
    card = PersonaCard.model_validate(persona_row.card)
    rows = []
    for emotion, label in STICKER_EMOTIONS.items():
        mine = sum(a.pinned for a in await repo.cached_arts(persona_row.id, f"st:{emotion}"))
        rows.append([_btn(f"{label}" + (f" - свой набор: {mine}" if mine else " - авто"), f"st:e:{emotion}")])
    text = (
        f"🎭 Стикеры <b>{esc(card.name)}</b> по эмоциям.\n\n"
        "<b>Авто</b> - бот сам подбирает арты. Если собрать <b>свой набор</b>, реакции будут только из него.\n\n"
        + FORWARD_HINT
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("stickers"))
async def cmd_stickers(message: Message, state: FSMContext, repo: Repo, persona_row: Persona) -> None:
    await state.clear()
    text, keyboard = await _menu(repo, persona_row)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("st:"))
async def on_stickers(
    callback: CallbackQuery, state: FSMContext, repo: Repo, user: User, persona_row: Persona, persona: PersonaCard
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer()
        return
    parts = (callback.data or "").split(":")
    action, arg = parts[1], parts[2] if len(parts) > 2 else ""

    if action == "menu":
        await callback.answer()
        text, keyboard = await _menu(repo, persona_row)
        await message.answer(text, reply_markup=keyboard)

    elif action in ("e", "m") and arg in STICKER_EMOTIONS:  # open an emotion / show more variants
        await callback.answer()
        await _show_emotion(message, repo, persona_row, persona, arg, first_page=action == "e")

    elif action in ("p", "b") and arg.isdigit():  # toggle "in my set" / remove
        art = await repo.get_art(user, int(arg))
        if art is None:
            await callback.answer(tr("stale"))
            return
        if action == "p":
            art.pinned = not art.pinned
            await callback.answer("Добавила в набор ✅" if art.pinned else "Убрала из набора")
            await message.edit_reply_markup(reply_markup=art_keyboard(art))
        else:
            art.banned, art.pinned = True, False
            await callback.answer("Больше не пришлю этот стикер 👌")
            await message.delete()

    elif action == "a" and arg in STICKER_EMOTIONS:  # bind a forwarded sticker
        data = await state.get_data()
        if not data.get("forwarded_sticker"):
            await callback.answer(tr("stale"))
            return
        file_id, unique_id = data["forwarded_sticker"], data["forwarded_unique"]
        await repo.add_art(persona_row.id, f"st:{arg}", f"tg:{unique_id}:{arg}"[:80], file_id, "", pinned=True)
        await state.update_data(forwarded_sticker=None)
        await callback.answer("Готово!")
        await message.edit_text(
            f"✅ Добавила в набор «{STICKER_EMOTIONS[arg]}». {esc(persona.name)} будет присылать его, "
            "когда почувствует эту эмоцию. Все наборы: /stickers"
        )
    else:
        await callback.answer(tr("stale"))


async def _show_emotion(
    message: Message, repo: Repo, persona_row: Persona, persona: PersonaCard, emotion: str, first_page: bool
) -> None:
    label = STICKER_EMOTIONS[emotion]
    if first_page:
        mine = [a for a in await repo.cached_arts(persona_row.id, f"st:{emotion}") if a.pinned]
        await message.answer(
            f"<b>{label}</b>\n"
            + (f"Твой набор: {len(mine)} шт. - вот они 👇" if mine else "Своего набора пока нет - выбирай из вариантов 👇")
        )
        for art in mine:
            await message.answer_sticker(art.file_id, reply_markup=art_keyboard(art))
    status = await message.answer("Подбираю новые варианты… 🔍")
    candidates = await arts.fresh_sticker_candidates(message, repo, persona_row, persona, emotion, NEW_PER_PAGE)
    for sent, art in candidates:
        await sent.edit_reply_markup(reply_markup=art_keyboard(art))
    if candidates:
        await status.edit_text("👆 Жми «➕ В набор» на тех, что нравятся, и «👎» на неудачных.")
    else:
        await status.edit_text("Новых артов для этой эмоции не нашла 😿\n" + FORWARD_HINT)
    await message.answer(
        f"<b>{label}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔄 Ещё варианты", f"st:m:{emotion}"), _btn("⬅️ Все эмоции", "st:menu")]
        ]),
    )


@router.message(F.sticker)
async def on_forwarded_sticker(message: Message, state: FSMContext, persona: PersonaCard) -> None:
    """Any sticker sent to the bot: offer to add it to the persona's set."""
    sticker = message.sticker
    assert sticker is not None
    await state.update_data(forwarded_sticker=sticker.file_id, forwarded_unique=sticker.file_unique_id)
    rows = [[_btn(label, f"st:a:{emotion}")] for emotion, label in STICKER_EMOTIONS.items()]
    await message.answer(
        f"Классный! К какой эмоции {esc(persona.name)} привязать этот стикер?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
