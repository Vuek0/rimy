"""Stage C: long-term memory, mood, reminders and the daily backup."""

import gzip
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bot.ai.service import AIService, Nudge, PersonaReply
from bot.config import Settings
from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker, run_migrations
from bot.handlers.talk import remember_from_reply
from bot.jobs import scheduler as sched
from bot.jobs.backup import make_backup
from bot.middlewares import _remember_activity
from bot.persona.card import DEFAULT_CARD
from bot.persona.context import Snapshot, context_block, mood
from bot.persona.memory import ChatMemory

TZ = "Asia/Tashkent"  # UTC+5
UTC = timezone.utc


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


async def _user(repo):
    return await repo.ensure_user(1, native_lang="ru", timezone=TZ, target_lang="it")


# --- memory ---


async def test_facts_are_deduplicated_and_capped(repo):
    now = datetime.now(UTC)
    added = await repo.add_facts(1, ["Учится в универе", "учится в универе.", "Любит пасту", " "], now)
    assert added == ["Учится в универе", "Любит пасту"]
    assert await repo.add_facts(1, ["Любит пасту"], now) == []
    for i in range(5):
        await repo.add_facts(1, [f"факт {i}"], now, keep=4)
    assert await repo.facts(1) == ["факт 1", "факт 2", "факт 3", "факт 4"]  # oldest forgotten


async def test_chat_history_is_kept_and_trimmed(repo):
    now = datetime.now(UTC)
    for i in range(7):
        await repo.add_chat(1, "user" if i % 2 == 0 else "assistant", f"m{i}", now, keep=5)
    assert [m["content"] for m in await repo.recent_chat(1, 3)] == ["m4", "m5", "m6"]
    assert len(await repo.recent_chat(1, 100)) == 5
    await repo.clear_chat(1)
    assert await repo.recent_chat(1, 10) == []


async def test_meta(repo):
    assert await repo.meta_get("x") == ""
    await repo.meta_set("x", "1")
    await repo.meta_set("x", "2")
    assert await repo.meta_get("x") == "2"


async def test_reply_memory_fields_are_parsed():
    class Provider:
        name = "p"

        async def complete(self, messages, json_mode=True):
            return ('{"reply": "Piacere!", "remember": ["Учится на программиста", ""], '
                    '"user_name": "Мухаммад", "user_gender": "Male"}')

    reply = await AIService([Provider()], []).persona_reply(DEFAULT_CARD, [], "меня зовут Мухаммад", "it", "ru")
    assert reply.remember == ["Учится на программиста"]
    assert (reply.user_name, reply.user_gender) == ("Мухаммад", "male")


async def test_remember_from_reply_updates_user_and_db(repo):
    user, _ = await _user(repo)
    reply = PersonaReply("Piacere!", remember=["Учится на программиста"], user_name="Мухаммад", user_gender="male")
    await remember_from_reply(repo, user, "меня зовут Мухаммад", reply, datetime.now(UTC))
    assert (user.name, user.gender) == ("Мухаммад", "male")
    assert await repo.facts(1) == ["Учится на программиста"]
    assert [m["role"] for m in await repo.recent_chat(1, 10)] == ["user", "assistant"]


async def test_history_is_restored_after_a_restart(repo):
    user, _ = await _user(repo)
    await repo.add_chat(1, "assistant", "Hai provato il gelato?", datetime.now(UTC))
    memory = ChatMemory()  # a fresh process
    before = user.last_active_at
    await _remember_activity(repo, memory, user)
    assert memory.history(1) == [{"role": "assistant", "content": "Hai provato il gelato?"}]
    assert memory.previous_active(1) == before and user.last_active_at is not None
    assert not memory.in_conversation(1)  # loading old history doesn't open a "conversation"


# --- mood ---


def test_mood_follows_progress():
    assert "missed" in mood(Snapshot(days_away=3))
    assert "proud" in mood(Snapshot(streak=8))
    assert "cheerful" in mood(Snapshot(streak=3))
    assert "worried" in mood(Snapshot(due=25))
    assert "normal" in mood(Snapshot())
    block = context_block(Snapshot(name="Мухаммад", facts=["любит пасту"], hard_words=["finestra"], words=10))
    assert "name: Мухаммад" in block and "любит пасту" in block and "finestra" in block


# --- reminders ---


def _at(local_hour: int, minute: int = 0) -> datetime:
    """A UTC moment that is local_hour:minute in Tashkent (UTC+5)."""
    return datetime(2026, 11, 20, local_hour, minute, tzinfo=UTC) - timedelta(hours=5)


def _u(**kw):
    defaults = dict(timezone=TZ, reminder_hours="12,20", last_active_at=None, last_reminded_at=None)
    return SimpleNamespace(**{**defaults, **kw})


def test_slots():
    assert sched.parse_hours("20, 12,x,25") == [12, 20]
    assert sched.current_slot(_u(), _at(11, 59)) is None
    assert sched.current_slot(_u(), _at(12, 0)) == _at(12)
    assert sched.current_slot(_u(), _at(13, 30)) == _at(12)
    assert sched.current_slot(_u(), _at(15)) is None  # too late for 12:00, too early for 20:00
    assert sched.current_slot(_u(), _at(21)) == _at(20)


def test_decide():
    now = _at(20)
    assert sched.decide(_u(last_active_at=now - timedelta(hours=1)), now, due=10, reviewed_today=0) is None
    assert sched.decide(_u(last_active_at=now - timedelta(days=2)), now, due=0, reviewed_today=0).kind == "miss_you"
    assert sched.decide(_u(last_active_at=now - timedelta(hours=5)), now, due=4, reviewed_today=0).kind == "review"
    assert sched.decide(_u(last_active_at=now - timedelta(hours=5)), now, due=4, reviewed_today=3) is None
    assert sched.decide(_u(), now, due=0, reviewed_today=0) is None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(("text", text, kwargs.get("reply_markup")))

    async def send_sticker(self, chat_id, sticker, **kwargs):
        self.sent.append(("sticker", sticker, None))
        return SimpleNamespace(sticker=SimpleNamespace(file_id="s"))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.sent.append(("photo", photo, None))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="p")])

    async def send_document(self, chat_id, document, **kwargs):
        self.sent.append(("document", document, kwargs.get("caption")))


class FakeAI:
    def __init__(self):
        self.kinds = []

    async def nudge(self, card, kind, target, native, context=""):
        self.kinds.append(kind)
        return Nudge(f"[{kind}] скучаю 🥺", "sad")


def _settings(url="sqlite+aiosqlite:///:memory:"):
    return Settings(bot_token="t", owner_id=1, timezone=TZ, database_url=url, _env_file=None)


async def test_miss_you_reminder_once_per_slot(repo):
    user, deck = await _user(repo)
    await repo.add_word(deck.id, {"lemma": "casa", "translations": ["дом"]}, _at(8) - timedelta(days=3))
    user.last_active_at = _at(9) - timedelta(days=2)
    bot, ai = FakeBot(), FakeAI()
    s = sched.Scheduler(bot, None, ai, _settings())

    assert not await s.maybe_remind(repo, user, _at(10))  # no slot at 10:00
    assert await s.maybe_remind(repo, user, _at(12, 5))
    assert ai.kinds == ["miss_you"]
    text = [m for m in bot.sent if m[0] == "text"][-1]
    # both directions of the word are due after 3 days; the count goes on its own paragraph
    assert "скучаю" in text[1] and "\n\n📚 Карточек к повторению: <b>2</b>" in text[1] and text[2] is not None
    assert not await s.maybe_remind(repo, user, _at(12, 40))  # same slot: no second message
    assert await s.maybe_remind(repo, user, _at(20, 1))  # still away: the evening slot misses you again


async def test_no_reminder_right_after_activity(repo):
    user, deck = await _user(repo)
    await repo.add_word(deck.id, {"lemma": "casa", "translations": ["дом"]}, _at(8))
    user.last_active_at = _at(11, 30)
    s = sched.Scheduler(FakeBot(), None, FakeAI(), _settings())
    assert not await s.maybe_remind(repo, user, _at(12, 5))
    assert user.last_reminded_at == _at(12, 5)  # the slot is used up, no retry 5 minutes later


async def test_backup_once_a_day(repo, tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'bot.db').as_posix()}"
    await run_migrations(url)
    raw = gzip.decompress(await make_backup(url))
    restored = tmp_path / "restored.db"
    restored.write_bytes(raw)
    tables = {r[0] for r in sqlite3.connect(restored).execute("select name from sqlite_master where type='table'")}
    assert {"words", "cards", "personas", "user_facts"} <= tables
    assert await make_backup("postgresql+asyncpg://x/y") is None

    bot = FakeBot()
    s = sched.Scheduler(bot, None, FakeAI(), _settings(url))
    assert not await s.maybe_backup(repo, _at(2))  # before 03:00
    assert await s.maybe_backup(repo, _at(3, 10))
    doc = [m for m in bot.sent if m[0] == "document"]
    # the whole DB holds every user's data: it goes to the admins (owner_id=1) only
    assert len(doc) == 1 and doc[0][1].filename == "rimy-2026-11-20.db.gz" and "Пользователей" in doc[0][2]
    assert not await s.maybe_backup(repo, _at(15))  # already done today
