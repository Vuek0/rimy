"""/start with onboarding (base language → language to learn), /help, /app, /lang, /base and fallbacks."""

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from bot import menu, texts
from bot.billing import Billing
from bot.config import Settings
from bot.db.models import Deck, Persona, User
from bot.db.repo import Repo
from bot.images.arts import answer_with_avatar
from bot.langs import BASE_LANGS, LANGS, get_lang, learnable
from bot.persona.card import PersonaCard, phrase
from bot.utils import utcnow

router = Router(name="common")
fallback_router = Router(name="fallback")

REF_PREFIX = "ref_"
APP_BUTTON = {"ru": "📱 Открыть приложение", "uz": "📱 Ilovani ochish", "en": "📱 Open the app"}
APP_HINT = {
    "ru": "Карточки, повторение и статистика - в приложении 👇",
    "uz": "Kartochkalar, takrorlash va statistika - ilovada 👇",
    "en": "Cards, reviews and stats - in the app 👇",
}


def app_keyboard(settings: Settings, native: str = "ru") -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    text = APP_BUTTON.get(native, APP_BUTTON["ru"])
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.webapp_url))]]
    )


def base_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=f"base:{code}")] for code, label in BASE_LANGS.items()]
    )


def langs_keyboard(native: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{lang.flag} {lang.english if native == 'en' else lang.name_ru}", callback_data=f"lang:{lang.code}"
        )
        for lang in learnable(native)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)])


async def send_welcome(
    message: Message, repo: Repo, user: User, deck: Deck, persona: PersonaCard, persona_row: Persona, settings: Settings
) -> None:
    greeting = phrase(persona, "greeting", ["Привет! 👋"])
    await answer_with_avatar(
        message, repo, persona_row, texts.help_text(get_lang(deck.target_lang), greeting, user.native_lang),
        reply_markup=menu.main_keyboard(user.native_lang),
    )
    if keyboard := app_keyboard(settings, user.native_lang):
        await message.answer(APP_HINT.get(user.native_lang, APP_HINT["ru"]), reply_markup=keyboard)


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    repo: Repo,
    user: User,
    deck: Deck,
    persona: PersonaCard,
    persona_row: Persona,
    billing: Billing,
    settings: Settings,
    command: CommandObject | None = None,
) -> None:
    await state.clear()
    args = (command.args or "").strip() if command else ""
    # Deep link t.me/<bot>?start=ref_<code>: who brought this user (a QR at the stand, a channel post…)
    if args.startswith(REF_PREFIX) and not user.ref:
        user.ref = args[len(REF_PREFIX):][:64]
    await billing.track_once(user.id, "start", utcnow(), ref=user.ref)
    if not user.onboarded:  # first visit: pick the base language, then the language to learn
        await message.answer(texts.ui("ru", "choose_base"), reply_markup=base_keyboard())
        return
    await send_welcome(message, repo, user, deck, persona, persona_row, settings)


@router.message(Command("base"))
async def cmd_base(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await message.answer(texts.ui(user.native_lang, "choose_base"), reply_markup=base_keyboard())


@router.callback_query(F.data.startswith("base:"))
async def on_base(
    callback: CallbackQuery, repo: Repo, user: User, deck: Deck, persona: PersonaCard, persona_row: Persona,
    settings: Settings,
) -> None:
    await callback.answer()
    message = callback.message
    code = (callback.data or "").split(":", 1)[1]
    if not isinstance(message, Message) or code not in BASE_LANGS:
        return
    user.native_lang = code
    await message.edit_reply_markup(reply_markup=None)
    # Telegram updates the bottom keyboard only with a new message: send it right away in the new language
    await message.answer(texts.ui(code, "base_set"), reply_markup=menu.main_keyboard(code))
    # A new user, or the language being learned is now the base language: pick what to learn
    if not user.onboarded or deck.target_lang == code:
        await message.answer(texts.ui(code, "choose_target"), reply_markup=langs_keyboard(code))
        return
    await send_welcome(message, repo, user, deck, persona, persona_row, settings)


@router.message(Command("app"))
async def cmd_app(message: Message, settings: Settings, user: User) -> None:
    keyboard = app_keyboard(settings, user.native_lang)
    if keyboard is None:
        await message.answer("Приложение скоро появится 🙂 А пока всё работает прямо здесь, в чате.")
        return
    await message.answer("👇", reply_markup=keyboard)


@router.message(menu.button(menu.MORE))
async def on_more(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await message.answer(menu.more_text(user.native_lang), reply_markup=menu.main_keyboard(user.native_lang))


LANGUAGE_MENU = {
    "ru": ("🌍 <b>Языки</b>", "🗣 Язык общения: {base}", "📚 Учу: {target}"),
    "uz": ("🌍 <b>Tillar</b>", "🗣 Bot tili: {base}", "📚 O'rganyapman: {target}"),
    "en": ("🌍 <b>Languages</b>", "🗣 Bot language: {base}", "📚 Learning: {target}"),
}


@router.message(menu.button(menu.LANGUAGE))
async def on_language_menu(message: Message, state: FSMContext, user: User, deck: Deck) -> None:
    """The 🌍 menu button: change either the base language or the language being learned."""
    await state.clear()
    title, base_label, target_label = LANGUAGE_MENU.get(user.native_lang, LANGUAGE_MENU["ru"])
    target = get_lang(deck.target_lang)
    target_name = target.english if user.native_lang == "en" else target.name_ru
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=base_label.format(base=BASE_LANGS.get(user.native_lang, user.native_lang)), callback_data="lm:base")],
        [InlineKeyboardButton(text=target_label.format(target=f"{target.flag} {target_name}"), callback_data="lm:target")],
    ])
    await message.answer(title, reply_markup=keyboard)


@router.callback_query(F.data.startswith("lm:"))
async def on_language_choice(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    if callback.data == "lm:base":
        await message.edit_text(texts.ui(user.native_lang, "choose_base"), reply_markup=base_keyboard())
    else:
        await message.edit_text(texts.ui(user.native_lang, "choose_target"), reply_markup=langs_keyboard(user.native_lang))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Окей, отменил 🙂")


@router.message(Command("lang"))
async def cmd_lang(message: Message, command: CommandObject, state: FSMContext, repo: Repo, user: User) -> None:
    await state.clear()
    code = (command.args or "").strip().lower()
    if code:
        await _switch(message, repo, user, code)
        return
    await message.answer(texts.ui(user.native_lang, "choose_target"), reply_markup=langs_keyboard(user.native_lang))


@router.callback_query(F.data.startswith("lang:"))
async def on_lang(
    callback: CallbackQuery, repo: Repo, user: User, persona: PersonaCard, persona_row: Persona, settings: Settings
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await message.edit_reply_markup(reply_markup=None)
    deck = await _switch(message, repo, user, (callback.data or "").split(":", 1)[1])
    if deck is not None and not user.onboarded:  # end of onboarding: show what the bot can do
        user.onboarded = True
        await send_welcome(message, repo, user, deck, persona, persona_row, settings)


async def _switch(message: Message, repo: Repo, user: User, code: str) -> Deck | None:
    if code not in LANGS or code == user.native_lang:
        await message.answer("Такого языка я пока не знаю 🤔 Выбери из списка: /lang")
        return None
    deck = await repo.switch_language(user, code)
    lang = get_lang(code)
    count = await repo.count_words(deck.id)
    await message.answer(f"{lang.flag} <b>{lang.english if user.native_lang == 'en' else lang.name_ru}</b> - {count} 📚")
    return deck


@fallback_router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE)


@fallback_router.message()
async def unknown_message(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        await message.answer("Не знаю такой команды 🤔 /help")
    else:
        await message.answer("Я пока понимаю только текст и голосовые 🙂 /help")
