"""Promo codes: the team generates them in the admin dashboard and hands them out in person.

A code adds `days` of Premium, but only to someone who has PAID for Premium at least once:
entered before paying, it is accepted and waits; the first payment applies it automatically.
Each user can use a code once; `max_uses` limits how many people can use it (0 = unlimited).
"""

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Event, Payment, PromoCode, PromoRedemption, User

CODE_RE = re.compile(r"^[A-Z0-9-]{4,32}$")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: easy to read off a card


def normalize(code: str) -> str:
    return code.strip().upper()


def looks_like_code(text: str) -> bool:
    return bool(CODE_RE.match(normalize(text)))


def generate_code(prefix: str = "RIMY") -> str:
    return f"{prefix}-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


@dataclass
class PromoResult:
    status: str  # applied | pending | unknown | inactive | exhausted | already
    days: int = 0
    premium_until: datetime | None = None


MESSAGES = {
    "ru": {
        "applied": "🎁 Промокод активирован: +{days} дн. Premium! Теперь он действует до {until}.",
        "pending": (
            "🎁 Промокод принят! Он добавит +{days} дн. к Premium.\n"
            "Оформи Premium, и бонус начислится автоматически."
        ),
        "already": "Этот промокод у тебя уже есть 🙂",
        "unknown": "Такого промокода нет. Проверь, правильно ли он написан.",
        "inactive": "Этот промокод больше не действует.",
        "exhausted": "Этот промокод уже закончился.",
    },
    "uz": {
        "applied": "🎁 Promokod faollashdi: Premium'ga +{days} kun! Endi u {until} gacha amal qiladi.",
        "pending": (
            "🎁 Promokod qabul qilindi! U Premium'ga +{days} kun qo'shadi.\n"
            "Premium'ni rasmiylashtir, bonus avtomatik qo'shiladi."
        ),
        "already": "Bu promokod senda allaqachon bor 🙂",
        "unknown": "Bunday promokod yo'q. To'g'ri yozilganini tekshir.",
        "inactive": "Bu promokod endi amal qilmaydi.",
        "exhausted": "Bu promokod tugagan.",
    },
    "en": {
        "applied": "🎁 Promo code applied: +{days} days of Premium! It now lasts until {until}.",
        "pending": (
            "🎁 Promo code accepted! It adds +{days} days to Premium.\n"
            "Get Premium and the bonus is added automatically."
        ),
        "already": "You already have this promo code 🙂",
        "unknown": "There's no such promo code. Check the spelling.",
        "inactive": "This promo code no longer works.",
        "exhausted": "This promo code has run out.",
    },
}


def message(result: PromoResult, lang: str = "ru") -> str:
    until = result.premium_until.strftime("%d.%m.%Y") if result.premium_until else ""
    return MESSAGES.get(lang, MESSAGES["ru"])[result.status].format(days=result.days, until=until)


async def has_paid(s: AsyncSession, user: User) -> bool:
    return await s.scalar(select(Payment.id).where(Payment.user_id == user.id).limit(1)) is not None


def extend(user: User, now: datetime, days: int) -> None:
    start = max(now, user.premium_until or now)
    user.premium_until = start + timedelta(days=days)


async def redeem(s: AsyncSession, user: User, raw_code: str, now: datetime) -> PromoResult:
    promo = await s.scalar(select(PromoCode).where(PromoCode.code == normalize(raw_code)))
    if promo is None:
        return PromoResult("unknown")
    if not promo.active:
        return PromoResult("inactive")
    mine = await s.scalar(
        select(PromoRedemption).where(PromoRedemption.user_id == user.id, PromoRedemption.promo_id == promo.id)
    )
    if mine is not None:
        return PromoResult("already", promo.days, user.premium_until)
    used = await s.scalar(select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_id == promo.id)) or 0
    if promo.max_uses and used >= promo.max_uses:
        return PromoResult("exhausted")

    redemption = PromoRedemption(user_id=user.id, promo_id=promo.id, created_at=now)
    s.add(redemption)
    status = "pending"
    if await has_paid(s, user):
        extend(user, now, promo.days)
        redemption.applied_at = now
        status = "applied"
    s.add(Event(user_id=user.id, name="promo_redeemed", props={"code": promo.code, "status": status}, created_at=now))
    await s.flush()
    return PromoResult(status, promo.days, user.premium_until)


async def pending_days(s: AsyncSession, user: User) -> int:
    total = await s.scalar(
        select(func.coalesce(func.sum(PromoCode.days), 0))
        .join(PromoRedemption, PromoRedemption.promo_id == PromoCode.id)
        .where(PromoRedemption.user_id == user.id, PromoRedemption.applied_at.is_(None))
    )
    return int(total or 0)


async def apply_pending(s: AsyncSession, user: User, now: datetime) -> int:
    """After a payment: add the days of every code this user entered before paying."""
    rows = await s.execute(
        select(PromoRedemption, PromoCode.days)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
        .where(PromoRedemption.user_id == user.id, PromoRedemption.applied_at.is_(None))
    )
    added = 0
    for redemption, days in rows.all():
        extend(user, now, days)
        redemption.applied_at = now
        added += days
    return added


# --- admin ---


async def create(s: AsyncSession, now: datetime, days: int, max_uses: int, code: str = "") -> PromoCode:
    code = normalize(code) if code else generate_code()
    if not CODE_RE.match(code):
        raise ValueError("код: 4-32 символа, латиница, цифры и дефис")
    if await s.scalar(select(PromoCode.id).where(PromoCode.code == code)) is not None:
        raise ValueError("такой код уже есть")
    promo = PromoCode(code=code, days=days, max_uses=max_uses, active=True, created_at=now)
    s.add(promo)
    await s.flush()
    return promo


async def set_active(s: AsyncSession, promo_id: int, active: bool) -> PromoCode | None:
    promo = await s.get(PromoCode, promo_id)
    if promo is not None:
        promo.active = active
        await s.flush()
    return promo


async def overview(s: AsyncSession) -> list[dict[str, Any]]:
    used = (
        select(
            PromoRedemption.promo_id,
            func.count(PromoRedemption.id).label("used"),
            func.count(PromoRedemption.applied_at).label("applied"),
        )
        .group_by(PromoRedemption.promo_id)
        .subquery()
    )
    rows = await s.execute(
        select(PromoCode, func.coalesce(used.c.used, 0), func.coalesce(used.c.applied, 0))
        .outerjoin(used, used.c.promo_id == PromoCode.id)
        .order_by(PromoCode.created_at.desc())
    )
    return [
        {
            "id": promo.id,
            "code": promo.code,
            "days": promo.days,
            "max_uses": promo.max_uses,
            "active": promo.active,
            "used": used_count,
            "applied": applied_count,
            "created_at": promo.created_at.isoformat(),
        }
        for promo, used_count, applied_count in rows.all()
    ]
