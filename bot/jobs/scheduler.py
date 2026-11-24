"""Background jobs: the persona reminds about reviews, misses you when you're away, and sends a daily backup."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.ai.schemas import AIError
from bot.ai.service import AIService, Nudge
from bot.config import Settings
from bot.db.models import User
from bot.db.repo import Repo
from bot.images import arts
from bot.jobs.backup import make_backup
from bot.jobs.target import ChatTarget
from bot.persona.card import PersonaCard, markdown_to_html
from bot.persona.context import context_block, snapshot
from bot.utils import utcnow

from bot.i18n import tr, set_lang

log = logging.getLogger(__name__)

TICK_SECONDS = 300
SLOT_WINDOW = timedelta(hours=2)  # a reminder is sent within 2h after its hour, never later (e.g. after downtime)
QUIET_AFTER_ACTIVITY = timedelta(hours=3)  # don't nudge someone who was just here
MISS_YOU_AFTER = timedelta(hours=20)
BACKUP_HOUR = 3  # local time
BACKUP_KEY = "last_backup_date"
SEND_PAUSE = 0.05  # seconds between reminders to different users

def start_review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("review.start_btn"), callback_data="rv:start")]])


def parse_hours(value: str) -> list[int]:
    hours = set()
    for part in value.split(","):
        if part.strip().isdigit() and 0 <= int(part) <= 23:
            hours.add(int(part))
    return sorted(hours)


def current_slot(user: User, now: datetime) -> datetime | None:
    """Start (UTC) of the reminder slot we're in right now, or None outside every slot's window."""
    local = now.astimezone(ZoneInfo(user.timezone))
    for hour in reversed(parse_hours(user.reminder_hours)):
        start = local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if start <= local < start + SLOT_WINDOW:
            return start.astimezone(now.tzinfo)
    return None


@dataclass
class Decision:
    kind: str  # review / miss_you
    due: int


def decide(user: User, now: datetime, due: int, reviewed_today: int) -> Decision | None:
    """What (if anything) the persona should say in the current slot."""
    away = now - user.last_active_at if user.last_active_at else None
    if away is not None and away < QUIET_AFTER_ACTIVITY:
        return None
    if away is not None and away >= MISS_YOU_AFTER:
        return Decision("miss_you", due)
    if due > 0 and reviewed_today == 0:
        return Decision("review", due)
    return None


class Scheduler:
    def __init__(self, bot: Bot, sessionmaker: async_sessionmaker, ai: AIService, settings: Settings):
        self.bot = bot
        self.sessionmaker = sessionmaker
        self.ai = ai
        self.settings = settings

    async def run(self) -> None:
        while True:
            try:
                await self.tick(utcnow())
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)

    async def tick(self, now: datetime) -> None:
        async with self.sessionmaker() as session:
            repo = Repo(session)
            for user in await repo.all_users():
                if not user.reminders_enabled:
                    continue
                try:
                    if await self.maybe_remind(repo, user, now):
                        await asyncio.sleep(SEND_PAUSE)  # stay well under Telegram's ~30 messages/second
                except TelegramForbiddenError:
                    user.reminders_enabled = False  # the user blocked the bot: stop writing to them
                except Exception:
                    log.exception("reminder for %s failed", user.id)
                await session.commit()
            await self.maybe_backup(repo, now)
            await session.commit()

    # --- reminders ---

    async def maybe_remind(self, repo: Repo, user: User, now: datetime) -> bool:
        slot = current_slot(user, now)
        if slot is None or (user.last_reminded_at and user.last_reminded_at >= slot):
            return False
        user.last_reminded_at = now  # one try per slot, whatever happens below
        set_lang(user.native_lang)  # outside an update: speak this user's language
        _, deck = await repo.ensure_user(
            user.id, native_lang=user.native_lang, timezone=user.timezone, target_lang=self.settings.default_target_lang
        )
        # previous_active=None: the "glad you are back" mood is for when they return, not while they are away
        snap = await snapshot(repo, user, deck, now, None)
        decision = decide(user, now, snap.due, snap.reviewed_today)
        if decision is None:
            return False

        persona_row = await repo.active_persona(user)
        card = PersonaCard.model_validate(persona_row.card)
        nudge = await self._nudge(card, decision.kind, deck.target_lang, user.native_lang, context_block(snap))
        target = ChatTarget(self.bot, user.id)
        emotion = "sad" if decision.kind == "miss_you" else nudge.emotion
        await arts.send_reaction(target, repo, persona_row, card, "nudge", emotion=emotion, force=True)
        text = markdown_to_html(nudge.text)
        if decision.due:
            text += tr("review.due", n=decision.due)
        await target.answer(text, reply_markup=start_review_kb() if decision.due else None)
        log.info("sent a %s reminder to %s", decision.kind, user.id)
        return True

    async def _nudge(self, card: PersonaCard, kind: str, target: str, native: str, context: str) -> Nudge:
        try:
            return await self.ai.nudge(card, kind, target, native, context)
        except AIError:
            log.warning("nudge generation failed, using a canned line")
            return Nudge(tr(f"nudge.{kind}"), "sad" if kind == "miss_you" else "happy")

    # --- daily backup ---

    async def maybe_backup(self, repo: Repo, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(self.settings.timezone))
        today = local.date().isoformat()
        if local.hour < BACKUP_HOUR or await repo.meta_get(BACKUP_KEY) == today:
            return False
        sent = await self.send_backup(repo, now)
        await repo.meta_set(BACKUP_KEY, today)  # also when it failed: try again tomorrow, don't spam
        return sent

    async def send_backup(self, repo: Repo, now: datetime) -> bool:
        """The whole database goes to the admins only (it holds every user's data)."""
        data = await make_backup(self.settings.database_url)
        if data is None:
            log.info("backup skipped: not an SQLite database")
            return False
        users = await repo.count_users()
        date = now.astimezone(ZoneInfo(self.settings.timezone)).strftime("%Y-%m-%d")
        for admin_id in self.settings.admins:
            await self.bot.send_document(
                admin_id,
                BufferedInputFile(data, filename=f"rimy-{date}.db.gz"),
                caption=f"💾 Бэкап базы за {date}\n👥 Пользователей: <b>{users}</b>",
            )
        log.info("backup sent to %d admin(s) (%d KB)", len(self.settings.admins), len(data) // 1024)
        return bool(self.settings.admins)
