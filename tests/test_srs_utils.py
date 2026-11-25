from datetime import date, timedelta

from bot import srs
from bot.utils import compute_streak, format_interval, utcnow


def test_review_moves_due_forward_and_ratings_are_ordered():
    now = utcnow()
    state = srs.new_card_state(now)
    intervals = srs.preview(state, now)
    assert intervals[1] <= intervals[2] <= intervals[3] <= intervals[4]
    new_state, due = srs.review(state, 3, now)
    assert due > now
    assert new_state["last_review"] is not None


def test_good_twice_grows_interval():
    now = utcnow()
    state, due1 = srs.review(srs.new_card_state(now), 3, now)
    state, due2 = srs.review(state, 3, due1)
    state, due3 = srs.review(state, 3, due2)
    assert (due3 - due2) > (due2 - due1)


def test_format_interval():
    assert format_interval(timedelta(seconds=10)) == "<1 мин"
    assert format_interval(timedelta(minutes=10)) == "10 мин"
    assert format_interval(timedelta(hours=5)) == "5 ч"
    assert format_interval(timedelta(days=3)) == "3 дн"
    assert format_interval(timedelta(days=60)) == "2 мес"
    assert format_interval(timedelta(days=45)) == "1.5 мес"
    assert format_interval(timedelta(days=730)) == "2 г"


def test_streak():
    today = date(2026, 11, 19)
    d = lambda n: today - timedelta(days=n)  # noqa: E731
    assert compute_streak(set(), today) == 0
    assert compute_streak({d(0), d(1), d(2)}, today) == 3
    assert compute_streak({d(1), d(2)}, today) == 2  # today not done yet — streak still alive
    # the lazy streak: one missed day a week is a rest day, it keeps (and counts in) the chain
    assert compute_streak({d(0), d(2)}, today) == 3
    assert compute_streak({d(0), d(1), d(3), d(4)}, today) == 5
    assert compute_streak({d(2), d(3)}, today) == 3  # rested yesterday, today isn't over yet
    assert compute_streak({d(0), d(3)}, today) == 1  # two missed days in a row break it
    assert compute_streak({d(0), d(2), d(4)}, today) == 3  # a second rest within a week breaks it
    assert compute_streak({d(0), d(2), d(3), d(4), d(5), d(6), d(7), d(8), d(10)}, today) == 11  # 8 days apart: ok
    assert compute_streak({d(3), d(4)}, today) == 0
