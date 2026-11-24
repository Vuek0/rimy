"""Thin wrapper around the FSRS algorithm (same one modern Anki uses)."""

from datetime import datetime, timedelta
from typing import Any

from fsrs import Card as FsrsCard
from fsrs import Rating, Scheduler

_scheduler = Scheduler()

RATINGS = (1, 2, 3, 4)  # Again, Hard, Good, Easy


def new_card_state(now: datetime) -> dict[str, Any]:
    return FsrsCard(due=now).to_dict()


def review(state: dict[str, Any], rating: int, now: datetime) -> tuple[dict[str, Any], datetime]:
    card = FsrsCard.from_dict(state)
    card, _ = _scheduler.review_card(card, Rating(rating), review_datetime=now)
    return card.to_dict(), card.due


def preview(state: dict[str, Any], now: datetime) -> dict[int, timedelta]:
    """How long until the next review for each possible rating."""
    return {rating: review(state, rating, now)[1] - now for rating in RATINGS}
