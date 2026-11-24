"""/remind - reminder times, /memory - what the persona remembers (and forgetting it), /backup - backup now."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db.models import User
from bot.db.repo import Repo
from bot.i18n import tr
from bot.handlers.talk import reset_conversation
from bot.jobs.scheduler import Scheduler, parse_hours
from bot.middlewares import AdminFilter
from bot.persona.card import PersonaCard
from bot.persona.memory import ChatMemory
from bot.utils import esc, utcnow

router = Router(name="settings")

HOUR_PRESETS = ["12,20", "9,19", "10,15,21", "20"]


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _hours_label(value: str) -> str:
    hours = [f"{h}:00" for h in parse_hours(value)]
    return tr("remind.and").join([", ".join(hours[:-1]), hours[-1]]) if len(hours) > 1 else (hours[0] if hours else "-")


# --- /remind ---


def _remind_view(user: User) -> tuple[str, InlineKeyboardMarkup]:
    if user.reminders_enabled:
        text = tr("remind.on", hours=_hours_label(user.reminder_hours), tz=esc(user.timezone))
        rows = [[_btn(("✅ " if p == user.reminder_hours else "") + _hours_label(p), f"rm:h:{p}")] for p in HOUR_PRESETS]
        rows.append([_btn(tr("remind.off_btn"), "rm:off")])
    else:
        text = tr("remind.off")
        rows = [[_btn(tr("remind.on_btn"), "rm:on")]]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("remind"))
async def cmd_remind(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    text, keyboard = _remind_view(user)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("rm:"))
async def on_remind(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    action = (callback.data or "").split(":", 2)
    if action[1] == "on":
        user.reminders_enabled = True
    elif action[1] == "off":
        user.reminders_enabled = False
    elif action[1] == "h" and len(action) == 3 and action[2] in HOUR_PRESETS:
        user.reminder_hours = action[2]
    if isinstance(callback.message, Message):
        text, keyboard = _remind_view(user)
        await callback.message.edit_text(text, reply_markup=keyboard)


# --- /memory ---


@router.message(Command("memory"))
async def cmd_memory(message: Message, state: FSMContext, repo: Repo, user: User, persona: PersonaCard) -> None:
    await state.clear()
    facts = await repo.facts(user.id)
    gender = tr(f"memory.{user.gender}") if user.gender in ("male", "female") else ""
    lines = [tr("memory.title", name=esc(persona.name))]
    if user.name:
        lines.append(tr("memory.user_name", name=esc(user.name)))
    if gender:
        lines.append(tr("memory.gender", g=gender))
    lines += [f"• {esc(f)}" for f in facts]
    if len(lines) == 1:
        lines.append(tr("memory.empty"))
    lines.append(tr("memory.note"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[_btn(tr("memory.forget_btn"), "mem:ask")]])
    await message.answer("\n".join(lines), reply_markup=keyboard)


@router.callback_query(F.data.startswith("mem:"))
async def on_memory(callback: CallbackQuery, repo: Repo, user: User, memory: ChatMemory) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    action = (callback.data or "").split(":", 1)[1]
    if action == "ask":
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[_btn(tr("memory.yes_btn"), "mem:wipe"), _btn(tr("cancel"), "mem:keep")]]
        )
        await message.edit_reply_markup(reply_markup=keyboard)
    elif action == "wipe":
        await repo.forget_facts(user.id)
        await reset_conversation(memory, repo, user.id)
        user.name, user.gender = "", ""
        await message.edit_text(tr("memory.wiped"))
    else:
        await message.edit_reply_markup(reply_markup=None)


# --- /backup ---


@router.message(Command("backup"), AdminFilter())
async def cmd_backup(message: Message, state: FSMContext, repo: Repo, scheduler: Scheduler) -> None:
    await state.clear()
    status = await message.answer("Делаю бэкап… 💾")
    if await scheduler.send_backup(repo, utcnow()):
        await status.delete()
    else:
        await status.edit_text("Бэкап через бота доступен только для базы SQLite.")
