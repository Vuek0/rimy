"""/admin - product report for the team: users, funnel, leads by ref code, revenue (admins only)."""

from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.billing import Billing
from bot.middlewares import AdminFilter
from bot.utils import esc, utcnow

router = Router(name="admin")

FUNNEL = [
    ("start", "Открыли бота"),
    ("first_word", "Добавили первое слово"),
    ("first_review", "Первое повторение"),
    ("app_open", "Открыли Mini App"),
    ("limit_reached", "Упёрлись в лимит"),
    ("paywall_view", "Смотрели Premium"),
    ("purchase", "Купили Premium"),
]


@router.message(Command("admin"), AdminFilter())
async def cmd_admin(message: Message, command: CommandObject, billing: Billing) -> None:
    """/admin [days] - the report for the last N days (default 1: today's event)."""
    days = int(command.args) if command.args and command.args.strip().isdigit() else 1
    report = await billing.report(utcnow() - timedelta(days=days))
    funnel = report["funnel"]
    lines = [
        f"📊 <b>Отчёт за {days} дн.</b>",
        f"👥 Пользователей: <b>{report['users_total']}</b> (новых: {report['users_new']})",
        f"⭐ Premium активен: <b>{report['premium_active']}</b>, Stars получено: <b>{report['stars']}</b>",
        "",
        "<b>Воронка</b> (уникальные пользователи):",
        *(f"• {label}: {funnel.get(name, 0)}" for name, label in FUNNEL),
    ]
    if report["refs"]:
        lines += ["", "<b>Лиды по ссылкам</b> (за всё время):"]
        lines += [f"• {esc(ref)}: {count}" for ref, count in report["refs"].items()]
    await message.answer("\n".join(lines))
