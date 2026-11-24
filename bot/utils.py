from datetime import date, datetime, timedelta, timezone
from html import escape


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def esc(text: str | None) -> str:
    return escape(text or "", quote=False)


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def format_interval(td: timedelta) -> str:
    seconds = td.total_seconds()
    if seconds < 60:
        return "<1 мин"
    minutes = seconds / 60
    if minutes < 60:
        return f"{round(minutes)} мин"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)} ч"
    days = hours / 24
    if days < 30:
        return f"{round(days)} дн"
    if days < 365:
        return f"{days / 30:.1f}".removesuffix(".0") + " мес"
    return f"{days / 365:.1f}".removesuffix(".0") + " г"


def compute_streak(days: set[date], today: date) -> int:
    """Consecutive days with reviews, ending today (or yesterday if today is not done yet)."""
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak
