"""What the persona knows when it talks: memory about the user, learning progress and its own mood."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.db.models import Deck, User
from bot.db.repo import Repo
from bot.utils import compute_streak


@dataclass
class Snapshot:
    name: str = ""
    gender: str = ""
    facts: list[str] = field(default_factory=list)
    words: int = 0
    due: int = 0
    reviewed_today: int = 0
    streak: int = 0
    hard_words: list[str] = field(default_factory=list)
    days_away: int = 0  # how long the user was gone before this message


async def snapshot(repo: Repo, user: User, deck: Deck, now: datetime, previous_active: datetime | None) -> Snapshot:
    tz = ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    times = await repo.review_times(deck.id, since=now - timedelta(days=366))
    # a learning day = reviewed cards or added words (new learners at the stand add before they review)
    learned = times + await repo.word_times(deck.id, since=now - timedelta(days=366))
    return Snapshot(
        name=user.name,
        gender=user.gender,
        facts=await repo.facts(user.id),
        words=await repo.count_words(deck.id),
        due=await repo.count_due(deck.id, now),
        reviewed_today=sum(1 for t in times if t.astimezone(tz).date() == today),
        streak=compute_streak({t.astimezone(tz).date() for t in learned}, today),
        hard_words=await repo.hard_words(deck.id, since=now - timedelta(days=30)),
        days_away=(now - previous_active).days if previous_active else 0,
    )


def mood(s: Snapshot) -> str:
    """The persona's mood follows the learner's progress (in English, for the prompt)."""
    if s.days_away >= 2:
        return (f"you missed the user: they were away for {s.days_away} days. Show you're glad they're back "
                "(a little pouty/teasing if it fits your character), then encourage them gently.")
    if s.streak >= 7:
        return f"proud and excited: the user keeps a {s.streak}-day streak! You may mention it."
    if s.streak >= 3:
        return f"cheerful: the user is on a {s.streak}-day streak."
    if s.due >= 20:
        return f"a bit worried: {s.due} cards are waiting for review. You may nudge them, kindly."
    return "normal: friendly and warm."


def context_block(s: Snapshot) -> str:
    """Prompt section with memory, progress and mood."""
    about = []
    if s.name:
        about.append(f"name: {s.name}")
    if s.gender:
        about.append(f"gender: {s.gender}")
    about += s.facts
    memory = "\n".join(f"- {line}" for line in about) or "- nothing yet"
    hard = ", ".join(s.hard_words) or "none"
    return f"""What you remember about the user (use it naturally when it fits; never recite the list):
{memory}

Their learning progress: {s.words} words in the deck, {s.due} cards due now, {s.reviewed_today} reviewed today,
streak {s.streak} days. Words they often forget: {hard}.

Your mood right now: {mood(s)}"""
