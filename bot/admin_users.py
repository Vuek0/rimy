"""Who joined the bot: the people list and one person's profile for the team dashboard (admins only).

Product data only (languages, words, reviews, payments, funnel steps). What the person told Rimi in
chat and the facts Rimi remembers stay out of it: the team doesn't need to read private conversations.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.dashboard import FUNNEL
from bot.db.models import Card, Deck, Event, Payment, PromoCode, PromoRedemption, ReviewLog, Usage, User, Word
from bot.langs import get_lang

PAGE = 50


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _lang(code: str) -> dict[str, str]:
    lang = get_lang(code)
    return {"code": code, "name": lang.name("ru"), "flag": lang.flag}


async def users_list(s: AsyncSession, now: datetime, query: str = "", offset: int = 0) -> dict[str, Any]:
    """Newest first. `query` matches the name, @username, ref or the Telegram id."""
    words = (
        select(Deck.user_id, func.count(Word.id).label("words"))
        .join(Word, Word.deck_id == Deck.id)
        .group_by(Deck.user_id)
        .subquery()
    )
    stmt = select(User, func.coalesce(words.c.words, 0)).outerjoin(words, words.c.user_id == User.id)
    q = query.strip().lstrip("@")
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.first_name).like(like),
                func.lower(User.username).like(like),
                func.lower(User.ref).like(like),
                cast(User.id, String).like(f"%{q}%"),
            )
        )
    total = await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await s.execute(stmt.order_by(User.created_at.desc()).offset(max(0, offset)).limit(PAGE))
    return {
        "total": total,
        "users": [
            {
                "id": u.id,
                "first_name": u.first_name,
                "username": u.username,
                "native_lang": u.native_lang,
                "premium": u.is_premium(now),
                "words": count,
                "ref": u.ref,
                "created_at": _iso(u.created_at),
                "last_active_at": _iso(u.last_active_at),
            }
            for u, count in rows.all()
        ],
    }


async def user_profile(s: AsyncSession, user_id: int, now: datetime) -> dict[str, Any] | None:
    user = await s.get(User, user_id)
    if user is None:
        return None

    decks = (
        await s.execute(
            select(Deck.id, Deck.target_lang, func.count(Word.id))
            .outerjoin(Word, Word.deck_id == Deck.id)
            .where(Deck.user_id == user_id)
            .group_by(Deck.id)
            .order_by(func.count(Word.id).desc())
        )
    ).all()
    deck_ids = [d for d, _, _ in decks]

    reviews = (
        await s.execute(
            select(func.count(ReviewLog.id), func.max(ReviewLog.reviewed_at))
            .join(Card, Card.id == ReviewLog.card_id)
            .join(Word, Word.id == Card.word_id)
            .where(Word.deck_id.in_(deck_ids))
        )
    ).one()
    due = await s.scalar(
        select(func.count(Card.id)).join(Word, Word.id == Card.word_id).where(Word.deck_id.in_(deck_ids), Card.due <= now)
    ) or 0
    recent_words = (
        await s.execute(
            select(Word.display, Word.translations, Word.created_at)
            .where(Word.deck_id.in_(deck_ids))
            .order_by(Word.created_at.desc())
            .limit(10)
        )
    ).all()

    usage = dict((await s.execute(select(Usage.kind, func.sum(Usage.count)).where(Usage.user_id == user_id).group_by(Usage.kind))).all())
    payments = (
        await s.execute(select(Payment.amount, Payment.created_at).where(Payment.user_id == user_id).order_by(Payment.created_at.desc()))
    ).all()
    promos = (
        await s.execute(
            select(PromoCode.code, PromoCode.days, PromoRedemption.created_at, PromoRedemption.applied_at)
            .join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
            .where(PromoRedemption.user_id == user_id)
        )
    ).all()
    first_steps = dict(
        (await s.execute(select(Event.name, func.min(Event.created_at)).where(Event.user_id == user_id).group_by(Event.name))).all()
    )

    return {
        "id": user.id,
        "first_name": user.first_name,
        "username": user.username,
        "ref": user.ref,
        "native_lang": _lang(user.native_lang),
        "decks": [{**_lang(lang), "words": words} for _, lang, words in decks],
        "premium": user.is_premium(now),
        "premium_until": _iso(user.premium_until),
        "onboarded": user.onboarded,
        "reminders": user.reminders_enabled,
        "practice_mode": user.practice_mode,
        "timezone": user.timezone,
        "created_at": _iso(user.created_at),
        "last_active_at": _iso(user.last_active_at),
        "stats": {
            "words": sum(w for _, _, w in decks),
            "reviews": reviews[0] or 0,
            "last_review_at": _iso(reviews[1]),
            "due": due,
        },
        "ai_total": {kind: int(count or 0) for kind, count in usage.items()},
        "payments": [{"stars": amount, "at": _iso(at)} for amount, at in payments],
        "promos": [{"code": code, "days": days, "at": _iso(at), "applied": applied is not None} for code, days, at, applied in promos],
        "funnel": [{"key": key, "label": label, "at": _iso(first_steps.get(key))} for key, label in FUNNEL],
        "recent_words": [
            {"display": display, "translation": ", ".join(tr[:2]) if tr else "", "at": _iso(at)} for display, tr, at in recent_words
        ],
    }
