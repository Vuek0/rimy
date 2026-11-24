"""/persona: create a character (anime/manga/etc. or original), preview, tweak, switch, delete."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import texts
from bot.ai.schemas import AIError
from bot.ai.service import AIService
from bot.db.models import Deck, Persona, User
from bot.images import arts
from bot.db.repo import Repo
from bot.persona.card import PersonaCard, phrase, render_card
from bot.handlers.talk import reset_conversation
from bot.persona.memory import ChatMemory
from bot.utils import esc
from bot import menu

from bot.i18n import tr

log = logging.getLogger(__name__)
router = Router(name="persona")

MAX_REQUEST_CHARS = 500


class PersonaFlow(StatesGroup):
    request = State()  # waiting for "who should I be?"
    preview = State()  # card shown with Save / Tweak / Redo / Cancel
    revise = State()  # waiting for "what to change?"
    upload = State()  # waiting for the user's own avatar picture


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


PREVIEW_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [_btn("✅ Сохранить", "pd:save")],
        [_btn("✏️ Поправить", "pd:edit"), _btn("🔄 Заново", "pd:redo")],
        [_btn("❌ Отмена", "pd:cancel")],
    ]
)

ASK_REQUEST = (
    "Кем мне быть? 🎭\n\n"
    "• Персонаж из аниме, манги, ранобэ, игры: <i>«Мегумин из KonoSuba»</i>\n"
    "• Или опиши своего: <i>«спокойный парень-библиотекарь, немного саркастичный»</i>\n\n"
    "/cancel - отмена"
)


# --- menu ---


@router.message(Command("persona"))
@router.message(menu.button(menu.PERSONA))
async def cmd_persona(message: Message, state: FSMContext, repo: Repo, user: User, persona_row: Persona) -> None:
    await state.clear()
    personas = await repo.list_personas(user)
    rows = [[_btn(f"🔁 {p.name}", f"p:use:{p.id}")] for p in personas if p.id != persona_row.id]
    rows.append([_btn("👀 Карточка", f"p:show:{persona_row.id}"), _btn("➕ Новый", "p:new")])
    others = f"\n\nДругие персонажи: {len(personas) - 1}" if len(personas) > 1 else ""
    title = esc(PersonaCard.model_validate(persona_row.card).title)
    text = f"Сейчас с тобой: 🎭 <b>{title}</b>{others}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await arts.answer_with_avatar(message, repo, persona_row, text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("p:"))
async def on_menu(
    callback: CallbackQuery,
    state: FSMContext,
    ai: AIService,
    repo: Repo,
    user: User,
    persona_row: Persona,
    memory: ChatMemory,
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    _, action, *rest = (callback.data or "").split(":")
    persona = await repo.get_persona(user, int(rest[0])) if rest else None

    if action == "new":
        await state.set_state(PersonaFlow.request)
        await message.answer(ASK_REQUEST)
        return
    if persona is None:
        await message.answer(tr("stale"))
        return

    card = PersonaCard.model_validate(persona.card)
    if action == "show":
        rows = [
            [_btn("🖼 Подобрать арт", f"p:art:{persona.id}"), _btn("📤 Своя картинка", f"p:upl:{persona.id}")],
            [_btn("✏️ Поправить", f"p:edit:{persona.id}"), _btn("🗑 Удалить", f"p:del:{persona.id}")],
        ]
        if not persona.is_active:
            rows.insert(0, [_btn("⭐ Выбрать", f"p:use:{persona.id}")])
        await message.answer(render_card(card), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    elif action == "use":
        await repo.activate_persona(user, persona.id)
        await reset_conversation(memory, repo, user.id)
        await greet(message, repo, persona, card)
    elif action == "edit":
        await state.set_state(PersonaFlow.revise)
        await state.update_data(card=card.model_dump(), persona_id=persona.id, request="")
        await message.answer(f"Что поменять в <b>{esc(card.name)}</b>? Например: <i>«пусть будет более дерзкой»</i>")
    elif action == "art":
        await state.set_state(None)
        status = await message.answer("Ищу арты… 🔍 (только настоящие рисунки художников, без ИИ)")
        if not (card.name_en or card.booru_tag) and not persona.art_tag:
            # Personas made before art support (or original ones) have no English name: identify once.
            card = await _fill_identity(ai, repo, persona, card)
        exclude = set((await state.get_data()).get("avatar_seen", []))
        candidates = await arts.send_avatar_candidates(message, persona, card, exclude)
        if not candidates:
            await status.edit_text(
                "Не нашла артов этого персонажа 😿 Можешь прислать свою картинку:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_btn("📤 Своя картинка", f"p:upl:{persona.id}")]]),
            )
            return
        await status.delete()
        await state.update_data(
            avatar_candidates=candidates,
            avatar_persona_id=persona.id,
            avatar_seen=list(exclude | {c["post_id"] for c in candidates}),
        )
        numbers = [_btn(str(i + 1), f"av:{i}") for i in range(len(candidates))]
        rows = [numbers[i : i + 3] for i in range(0, len(numbers), 3)]
        rows.append([_btn("🔄 Другие", f"p:art:{persona.id}"), _btn("📤 Своя", f"p:upl:{persona.id}")])
        await message.answer("Какую сделать аватаркой? 👆", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    elif action == "upl":
        await state.set_state(PersonaFlow.upload)
        await state.update_data(avatar_persona_id=persona.id)
        await message.answer("Пришли картинку (как фото) - сделаю её аватаркой 🖼\n/cancel - отмена")
    elif action == "del":
        if await repo.delete_persona(user, persona.id):
            await reset_conversation(memory, repo, user.id)
            await message.edit_text(f"Удалила персонажа <b>{esc(card.name)}</b> 🗑")
        else:
            await message.answer("Это единственный персонаж - сначала создай другого: /persona")


# --- creating & tweaking ---


@router.message(PersonaFlow.request, F.text, ~F.text.startswith("/"), menu.NOT_MENU)
async def on_request(message: Message, state: FSMContext, ai: AIService, user: User, deck: Deck) -> None:
    request = (message.text or "").strip()[:MAX_REQUEST_CHARS]
    await state.update_data(request=request, persona_id=None)
    status = await message.answer("Изучаю персонажа… 🔍 Это займёт несколько секунд.")
    await _create(status, state, ai, user, deck, request)


async def _create(status: Message, state: FSMContext, ai: AIService, user: User, deck: Deck, request: str) -> None:
    try:
        card = await ai.create_persona(request, deck.target_lang, user.native_lang)
    except AIError:
        log.exception("persona creation failed")
        await state.set_state(PersonaFlow.request)
        await status.edit_text(tr("ai_error") + "\n\nМожешь прислать запрос ещё раз.")
        return
    await _preview(status, state, card)


async def _preview(status: Message, state: FSMContext, card: PersonaCard) -> None:
    await state.set_state(PersonaFlow.preview)
    await state.update_data(card=card.model_dump())
    await status.edit_text(render_card(card), reply_markup=PREVIEW_KB)


@router.message(PersonaFlow.revise, F.text, ~F.text.startswith("/"), menu.NOT_MENU)
async def on_revise(message: Message, state: FSMContext, ai: AIService, user: User, deck: Deck) -> None:
    data = await state.get_data()
    if "card" not in data:
        await state.clear()
        await message.answer(tr("stale"))
        return
    status = await message.answer("Переделываю… ✏️")
    try:
        card = await ai.revise_persona(
            PersonaCard.model_validate(data["card"]), (message.text or "")[:MAX_REQUEST_CHARS],
            deck.target_lang, user.native_lang,
        )
    except AIError:
        log.exception("persona revision failed")
        await status.edit_text(tr("ai_error") + "\n\nНапиши, что поменять, ещё раз.")
        return
    await _preview(status, state, card)


@router.callback_query(PersonaFlow.preview, F.data.startswith("pd:"))
async def on_preview_action(
    callback: CallbackQuery, state: FSMContext, ai: AIService, repo: Repo, user: User, deck: Deck, memory: ChatMemory
) -> None:
    await callback.answer()
    message = callback.message
    data = await state.get_data()
    if not isinstance(message, Message) or "card" not in data:
        return
    action = (callback.data or "").split(":", 1)[1]
    card = PersonaCard.model_validate(data["card"])

    if action == "save":
        if data.get("persona_id") and (existing := await repo.get_persona(user, data["persona_id"])):
            await repo.update_persona(existing, card.model_dump())
            await repo.activate_persona(user, existing.id)
            saved = existing
        else:
            saved = await repo.add_persona(user, card.model_dump(), activate=True)
        await state.clear()
        await reset_conversation(memory, repo, user.id)
        await message.edit_reply_markup(reply_markup=None)
        if saved.avatar_file_id:
            await greet(message, repo, saved, card)
            return
        rows = [[_btn("📤 Своя картинка", f"p:upl:{saved.id}")]]
        if card.name_en or card.booru_tag:
            rows.insert(0, [_btn("🖼 Подобрать арт", f"p:art:{saved.id}")])
        await message.answer(
            f"✅ Готово!\n\n🎭 {esc(phrase(card, 'greeting', ['Привет! 👋']))}\n\nДобавим аватарку?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    elif action == "edit":
        await state.set_state(PersonaFlow.revise)
        await message.edit_reply_markup(reply_markup=None)
        await message.answer("Что поменять? Например: <i>«пусть говорит короче»</i>, <i>«добавь больше японских словечек»</i>")
    elif action == "redo":
        if not data.get("request"):
            await message.answer("Напиши, что поменять: /persona → Карточка → Поправить")
            return
        await message.edit_reply_markup(reply_markup=None)
        status = await message.answer("Пробую ещё раз… 🔄")
        await _create(status, state, ai, user, deck, data["request"])
    else:
        await state.clear()
        await message.edit_reply_markup(reply_markup=None)
        await message.answer("Окей, оставляем всё как было 🙂")


# --- avatar ---


async def _fill_identity(ai: AIService, repo: Repo, persona: Persona, card: PersonaCard) -> PersonaCard:
    request = f"{card.name} из {card.source}" if card.source else card.name
    try:
        identified = await ai.identify_character(request)
    except AIError:
        return card
    if not identified.get("existing"):
        return card
    card = card.model_copy(
        update={
            "name_en": str(identified.get("name_en") or ""),
            "booru_tag": str(identified.get("danbooru_tag") or ""),
        }
    )
    await repo.update_persona(persona, card.model_dump())
    return card


async def greet(message: Message, repo: Repo, persona: Persona, card: PersonaCard) -> None:
    text = f"🎭 <b>{esc(card.title)}</b>\n\n{esc(phrase(card, 'greeting', ['Привет! 👋']))}"
    await arts.answer_with_avatar(message, repo, persona, text)


@router.callback_query(F.data.startswith("av:"))
async def on_avatar_pick(callback: CallbackQuery, state: FSMContext, repo: Repo, user: User) -> None:
    data = await state.get_data()
    candidates = data.get("avatar_candidates") or []
    index = int((callback.data or "av:-1").split(":")[1])
    persona = await repo.get_persona(user, data.get("avatar_persona_id") or 0)
    if persona is None or not 0 <= index < len(candidates) or not isinstance(callback.message, Message):
        await callback.answer(tr("stale"))
        return
    await callback.answer()
    chosen = candidates[index]
    await repo.set_avatar(persona, chosen["file_id"], chosen["credit"])
    await state.update_data(avatar_candidates=None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await greet(callback.message, repo, persona, PersonaCard.model_validate(persona.card))


@router.message(PersonaFlow.upload, F.photo)
async def on_avatar_upload(message: Message, state: FSMContext, repo: Repo, user: User) -> None:
    data = await state.get_data()
    persona = await repo.get_persona(user, data.get("avatar_persona_id") or 0)
    await state.clear()
    if persona is None or not message.photo:
        await message.answer(tr("stale"))
        return
    await repo.set_avatar(persona, message.photo[-1].file_id, "")
    await greet(message, repo, persona, PersonaCard.model_validate(persona.card))


@router.message(PersonaFlow.upload, ~F.text.startswith("/"))
async def on_avatar_upload_not_photo(message: Message) -> None:
    await message.answer("Нужна картинка, отправленная как фото 🖼 Или /cancel")
