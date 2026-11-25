"""Free-plan quotas, Premium (Telegram Stars subscription) and product analytics events.

Free users get a few AI actions a day (see Settings.free_*); reviews by button are always free because
they cost nothing. Premium removes the limits. Every important step is also logged as an Event, which
gives the funnel (start → first word → first review → paywall → purchase) and the lead count by ref code.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import promo
from bot.config import Settings
from bot.db.models import Event, Payment, Usage, User
from bot.utils import utcnow

log = logging.getLogger(__name__)

KINDS = ("word", "voice", "chat", "check")
PREMIUM_PAYLOAD = "premium_30d"

LIMIT_TEXT = {
    "ru": {
        "word": "Сегодня бесплатные AI-слова закончились ({limit} в день).",
        "voice": "Сегодня бесплатные голосовые закончились ({limit} в день).",
        "chat": "Сегодня бесплатные сообщения маскоту закончились ({limit} в день).",
        "check": "Сегодня бесплатные AI-проверки ответов закончились ({limit} в день).",
        "tail": "\n\nПовторение карточек остаётся бесплатным. Premium снимает все лимиты - /premium ⭐",
    },
    "uz": {
        "word": "Bugungi bepul AI so'zlar tugadi (kuniga {limit} ta).",
        "voice": "Bugungi bepul ovozli xabarlar tugadi (kuniga {limit} ta).",
        "chat": "Bugungi bepul Rimy bilan suhbat tugadi (kuniga {limit} ta).",
        "check": "Bugungi bepul AI javob tekshiruvlari tugadi (kuniga {limit} ta).",
        "tail": "\n\nKartalarni takrorlash bepul qoladi. Premium barcha cheklovlarni olib tashlaydi - /premium ⭐",
    },
    "en": {
        "word": "You've used today's free AI words ({limit} a day).",
        "voice": "You've used today's free voice words ({limit} a day).",
        "chat": "You've used today's free chat with Rimy ({limit} a day).",
        "check": "You've used today's free AI answer checks ({limit} a day).",
        "tail": "\n\nReviewing cards stays free. Premium removes every limit - /premium ⭐",
    },
}


def local_day(user: User, now: datetime) -> str:
    return now.astimezone(ZoneInfo(user.timezone)).date().isoformat()


@dataclass
class Quota:
    kind: str
    used: int
    limit: int  # 0 = unlimited (premium)
    refused: bool = False  # try_consume: the limit was already used up, the action was not counted

    @property
    def left(self) -> int | None:
        return None if self.limit == 0 else max(0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        return self.limit != 0 and self.used >= self.limit

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "used": self.used, "limit": self.limit, "left": self.left}


class Billing:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.s = session
        self.settings = settings

    # --- quotas ---

    async def _row(self, user: User, kind: str, now: datetime) -> Usage | None:
        return await self.s.scalar(
            select(Usage).where(Usage.user_id == user.id, Usage.day == local_day(user, now), Usage.kind == kind)
        )

    async def quota(self, user: User, kind: str, now: datetime) -> Quota:
        row = await self._row(user, kind, now)
        limit = 0 if user.is_premium(now) else self.settings.limit(kind)
        return Quota(kind, row.count if row else 0, limit)

    async def quotas(self, user: User, now: datetime) -> list[Quota]:
        return [await self.quota(user, kind, now) for kind in KINDS]

    async def try_consume(self, user: User, kind: str, now: datetime) -> Quota:
        """Count one AI action. Returns the quota; if `refused` is set, nothing was counted - refuse the action.

        (Not `exceeded`: after the last allowed action of the day used == limit, yet that action is allowed.)
        """
        quota = await self.quota(user, kind, now)
        if quota.exceeded:
            await self.track(user.id, "limit_reached", now, kind=kind)
            quota.refused = True
            return quota
        row = await self._row(user, kind, now)
        if row is None:
            self.s.add(Usage(user_id=user.id, day=local_day(user, now), kind=kind, count=1))
        else:
            row.count += 1
        await self.s.flush()
        return Quota(kind, quota.used + 1, quota.limit)

    def limit_message(self, quota: Quota, lang: str = "ru") -> str:
        texts = LIMIT_TEXT.get(lang, LIMIT_TEXT["ru"])
        return texts[quota.kind].format(limit=quota.limit) + texts["tail"]

    # --- premium ---

    async def grant_premium(self, user: User, now: datetime, charge_id: str, amount: int, payload: str) -> datetime:
        """Extend Premium by `premium_days` from now or from the current end, whichever is later."""
        existing = await self.s.scalar(select(Payment).where(Payment.charge_id == charge_id))
        if existing is None:  # Telegram may deliver the same successful_payment twice
            self.s.add(Payment(user_id=user.id, amount=amount, payload=payload, charge_id=charge_id, created_at=now))
            start = max(now, user.premium_until or now)
            user.premium_until = start + timedelta(days=self.settings.premium_days)
            await promo.apply_pending(self.s, user, now)  # promo codes entered before paying
            await self.track(user.id, "purchase", now, amount=amount, payload=payload)
            await self.s.flush()
        assert user.premium_until is not None
        return user.premium_until

    # --- analytics ---

    async def track(self, user_id: int, name: str, now: datetime, **props: Any) -> None:
        self.s.add(Event(user_id=user_id, name=name, props=props, created_at=now))
        await self.s.flush()

    async def track_once(self, user_id: int, name: str, now: datetime, **props: Any) -> bool:
        """Log an event only the first time for this user (first_word, first_review…)."""
        seen = await self.s.scalar(select(Event.id).where(Event.user_id == user_id, Event.name == name).limit(1))
        if seen is not None:
            return False
        await self.track(user_id, name, now, **props)
        return True

    async def report(self, since: datetime) -> dict[str, Any]:
        """Admin report: users, funnel since `since`, leads by ref code, revenue."""
        users_total = await self.s.scalar(select(func.count(User.id))) or 0
        users_new = await self.s.scalar(select(func.count(User.id)).where(User.created_at >= since)) or 0
        premium = await self.s.scalar(select(func.count(User.id)).where(User.premium_until > utcnow())) or 0
        funnel_rows = await self.s.execute(
            select(Event.name, func.count(func.distinct(Event.user_id)))
            .where(Event.created_at >= since)
            .group_by(Event.name)
        )
        refs = await self.s.execute(
            select(User.ref, func.count(User.id)).where(User.ref != "").group_by(User.ref).order_by(func.count(User.id).desc())
        )
        stars = await self.s.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.created_at >= since))
        return {
            "users_total": users_total,
            "users_new": users_new,
            "premium_active": premium,
            "funnel": dict(funnel_rows.all()),
            "refs": dict(refs.all()),
            "stars": stars or 0,
        }
