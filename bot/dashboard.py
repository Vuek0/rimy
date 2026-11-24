"""Live product dashboard for the team (admins only): headline numbers, daily series, funnel, leads.

Days are local days in the bot's timezone (Asia/Tashkent), so "today" matches the stand's clock.
The data is small (a hackathon-sized database), so rows since the start of the period are bucketed in Python.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Card, Deck, Event, Payment, ReviewLog, Usage, User, Word

FUNNEL = [
    ("start", "Открыли бота"),
    ("first_word", "Добавили первое слово"),
    ("first_review", "Первое повторение"),
    ("app_open", "Открыли Mini App"),
    ("limit_reached", "Упёрлись в лимит"),
    ("paywall_view", "Смотрели Premium"),
    ("purchase", "Купили Premium"),
    ("promo_redeemed", "Ввели промокод"),
]
AI_KINDS = {"word": "AI-слова", "voice": "Голосовые", "chat": "Сообщения Рими", "check": "AI-проверки"}


async def dashboard(s: AsyncSession, now: datetime, tz_name: str, days: int) -> dict[str, Any]:
    tz = ZoneInfo(tz_name)
    today = now.astimezone(tz).date()
    first = today - timedelta(days=days - 1)
    since = datetime.combine(first, datetime.min.time(), tzinfo=tz)
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    span = [first + timedelta(days=i) for i in range(days)]

    def local(dt: datetime) -> date:
        return dt.astimezone(tz).date()

    def series(counter: dict[date, int]) -> list[dict[str, Any]]:
        return [{"day": d.isoformat(), "value": counter.get(d, 0)} for d in span]

    # daily buckets
    new_users: dict[date, int] = defaultdict(int)
    for (created,) in (await s.execute(select(User.created_at).where(User.created_at >= since))).all():
        new_users[local(created)] += 1

    words: dict[date, int] = defaultdict(int)
    for (created,) in (await s.execute(select(Word.created_at).where(Word.created_at >= since))).all():
        words[local(created)] += 1

    reviews: dict[date, int] = defaultdict(int)
    active: dict[date, set[int]] = defaultdict(set)
    review_rows = await s.execute(
        select(ReviewLog.reviewed_at, Deck.user_id)
        .join(Card, Card.id == ReviewLog.card_id)
        .join(Word, Word.id == Card.word_id)
        .join(Deck, Deck.id == Word.deck_id)
        .where(ReviewLog.reviewed_at >= since)
    )
    for reviewed_at, user_id in review_rows.all():
        reviews[local(reviewed_at)] += 1
        active[local(reviewed_at)].add(user_id)

    for created, user_id in (await s.execute(select(Event.created_at, Event.user_id).where(Event.created_at >= since))).all():
        active[local(created)].add(user_id)

    ai_today: dict[str, int] = defaultdict(int)
    ai: dict[date, int] = defaultdict(int)
    usage_rows = await s.execute(select(Usage.day, Usage.kind, Usage.user_id, Usage.count).where(Usage.day >= first.isoformat()))
    for day_str, kind, user_id, count in usage_rows.all():
        day = date.fromisoformat(day_str)
        ai[day] += count
        active[day].add(user_id)
        if day == today:
            ai_today[kind] += count

    # headline numbers
    users_total = await s.scalar(select(func.count(User.id))) or 0
    active_now = await s.scalar(select(func.count(User.id)).where(User.last_active_at >= day_start)) or 0
    premium = await s.scalar(select(func.count(User.id)).where(User.premium_until > now)) or 0
    words_total = await s.scalar(select(func.count(Word.id))) or 0
    reviews_total = await s.scalar(select(func.count(ReviewLog.id))) or 0
    stars_total = await s.scalar(select(func.coalesce(func.sum(Payment.amount), 0))) or 0
    payments_total = await s.scalar(select(func.count(Payment.id))) or 0

    # funnel over the period: unique users per step
    funnel_rows = await s.execute(
        select(Event.name, func.count(func.distinct(Event.user_id))).where(Event.created_at >= since).group_by(Event.name)
    )
    reached = dict(funnel_rows.all())
    refs = await s.execute(
        select(User.ref, func.count(User.id)).where(User.ref != "").group_by(User.ref).order_by(func.count(User.id).desc())
    )

    return {
        "generated_at": now.isoformat(),
        "today": today.isoformat(),
        "days": days,
        "totals": {
            "users": users_total,
            "new_today": new_users.get(today, 0),
            "active_today": max(active_now, len(active.get(today, ()))),
            "words": words_total,
            "reviews": reviews_total,
            "premium": premium,
            "payments": payments_total,
            "stars": stars_total,
        },
        "series": {
            "new_users": series(new_users),
            "active_users": series({d: len(u) for d, u in active.items()}),
            "words": series(words),
            "reviews": series(reviews),
            "ai": series(ai),
        },
        "funnel": [{"key": key, "label": label, "users": reached.get(key, 0)} for key, label in FUNNEL],
        "ai_today": [{"kind": k, "label": label, "count": ai_today.get(k, 0)} for k, label in AI_KINDS.items()],
        "refs": [{"ref": ref, "users": count} for ref, count in refs.all()],
    }
