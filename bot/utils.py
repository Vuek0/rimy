from datetime import date, datetime, timedelta, timezone
from html import escape


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def esc(text: str | None) -> str:
    return escape(text or "", quote=False)


def norm(text: str) -> str:
    return " ".join(text.lower().split())


INTERVAL_UNITS = {  # minute, hour, day, month, year
    "ru": ("мин", "ч", "дн", "мес", "г"),
    "uz": ("daq", "soat", "kun", "oy", "yil"),
    "en": ("min", "h", "d", "mo", "y"),
}


def format_interval(td: timedelta, lang: str = "ru") -> str:
    minute, hour, day, month, year = INTERVAL_UNITS.get(lang, INTERVAL_UNITS["ru"])
    seconds = td.total_seconds()
    if seconds < 60:
        return f"<1 {minute}"
    minutes = seconds / 60
    if minutes < 60:
        return f"{round(minutes)} {minute}"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)} {hour}"
    days = hours / 24
    if days < 30:
        return f"{round(days)} {day}"
    if days < 365:
        return f"{days / 30:.1f}".removesuffix(".0") + f" {month}"
    return f"{days / 365:.1f}".removesuffix(".0") + f" {year}"


LAZY_DAY_EVERY = 7  # "even a sloth needs a day off": one missed day per week doesn't break the streak


def compute_streak(days: set[date], today: date) -> int:
    """The "lazy streak": days in a row with learning, ending today (or yesterday if today isn't done yet).

    A single missed day is forgiven once per week (it counts as a rest day); two missed days in a row,
    or a second miss within 7 days, end the streak.
    """
    day = today if today in days else today - timedelta(days=1)  # today isn't over: not a miss yet
    streak = 0
    last_rest: date | None = None
    while True:
        if day in days:
            streak += 1
        elif (
            day - timedelta(days=1) in days
            and (last_rest is None or (last_rest - day).days >= LAZY_DAY_EVERY)
        ):
            last_rest = day
            streak += 1  # a rest day keeps the chain and counts as part of it
        else:
            return streak
        day -= timedelta(days=1)
