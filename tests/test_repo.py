from datetime import timedelta

import pytest
from sqlalchemy import func, select

from bot import srs
from bot.db.models import Card, ReviewLog
from bot.db.repo import REVERSE_DELAY, Repo
from bot.db.session import make_engine, make_sessionmaker, init_db, run_migrations
from bot.utils import utcnow

DRAFT = {
    "lemma": "finestra",
    "display": "la finestra",
    "pos": "сущ., ж.р.",
    "translations": ["окно"],
    "example": "Apri la finestra.",
    "example_translation": "Открой окно.",
    "notes": "",
}


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


async def _setup(repo: Repo):
    return await repo.ensure_user(1, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")


async def test_ensure_user_is_idempotent(repo):
    user, deck = await _setup(repo)
    user2, deck2 = await _setup(repo)
    assert user is user2 and deck.id == deck2.id
    assert deck.target_lang == "it" and user.active_deck_id == deck.id


async def test_switch_language_keeps_separate_decks(repo):
    user, it_deck = await _setup(repo)
    es_deck = await repo.switch_language(user, "es")
    assert es_deck.id != it_deck.id
    assert (await repo.switch_language(user, "it")).id == it_deck.id


async def test_add_word_creates_two_cards_and_review_flow(repo):
    _, deck = await _setup(repo)
    now = utcnow()
    word = await repo.add_word(deck.id, DRAFT, now)
    cards = list(await repo.s.scalars(select(Card).where(Card.word_id == word.id)))
    assert sorted(c.direction for c in cards) == ["fwd", "rev"]

    # only the forward card is due now; the reverse one waits a day
    card = await repo.next_due_card(deck.id, now)
    assert card is not None and card.direction == "fwd" and card.word.display == "la finestra"
    assert await repo.count_due(deck.id, now) == 1

    state, due = srs.review(card.fsrs, 3, now)
    await repo.record_review(card, 3, state, due, now)
    assert await repo.last_review_at(card.id) == now
    # "Good" on a new card = short learning step: shown again soon, but not right after rating it
    assert await repo.next_due_card(deck.id, now, just_reviewed=card.id) is None
    assert (await repo.next_due_card(deck.id, now)).id == card.id  # learn-ahead for a fresh session
    assert await repo.next_due_at(deck.id) == min(due, now + REVERSE_DELAY)

    later = now + REVERSE_DELAY + timedelta(minutes=1)
    assert await repo.count_due(deck.id, later) == 2  # the reverse card has joined


async def test_duplicates_find_and_delete(repo):
    _, deck = await _setup(repo)
    now = utcnow()
    word = await repo.add_word(deck.id, DRAFT, now)
    assert [w.id for w in await repo.find_duplicates(deck.id, "Finestra ")] == [word.id]
    assert [w.id for w in await repo.find_words(deck.id, "LA FINESTRA")] == [word.id]

    card = await repo.next_due_card(deck.id, now)
    state, due = srs.review(card.fsrs, 1, now)
    await repo.record_review(card, 1, state, due, now)
    assert len(await repo.review_times(deck.id, now - timedelta(days=1))) == 1

    await repo.delete_word(word.id)
    assert await repo.count_words(deck.id) == 0
    assert await repo.s.scalar(select(func.count(Card.id))) == 0
    assert await repo.s.scalar(select(func.count(ReviewLog.id))) == 0


async def test_concurrent_first_updates_do_not_crash(tmp_path):
    """After a restart several updates from a new user are handled at the same time."""
    import asyncio

    url = f"sqlite+aiosqlite:///{(tmp_path / 'race.db').as_posix()}"
    await run_migrations(url)
    engine = make_engine(url)
    sm = make_sessionmaker(engine)

    async def handle_update():
        async with sm() as session:
            _, deck = await _setup(Repo(session))
            await session.commit()
            return deck.id

    deck_ids = await asyncio.gather(*(handle_update() for _ in range(5)))
    assert len(set(deck_ids)) == 1
    await engine.dispose()


async def test_migrations_create_schema(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'sub' / 'bot.db').as_posix()}"
    await run_migrations(url)
    await run_migrations(url)  # idempotent
    engine = make_engine(url)
    async with make_sessionmaker(engine)() as session:
        repo = Repo(session)
        _, deck = await _setup(repo)
        await repo.add_word(deck.id, DRAFT, utcnow())
        await session.commit()
        assert await repo.count_words(deck.id) == 1
    await engine.dispose()


def test_sqlite_folder_must_be_writable(tmp_path, monkeypatch):
    from bot.db import session

    session.check_sqlite_writable(f"sqlite+aiosqlite:///{(tmp_path / 'bot.db').as_posix()}")  # fine
    session.check_sqlite_writable("sqlite+aiosqlite:///:memory:")  # nothing to check

    def deny(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", deny)
    with pytest.raises(RuntimeError, match="chown -R 1000:1000"):
        session.check_sqlite_writable(f"sqlite+aiosqlite:///{(tmp_path / 'bot.db').as_posix()}")
