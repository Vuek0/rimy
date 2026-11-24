"""Answering review cards by text or voice."""

from types import SimpleNamespace

import pytest

from bot.ai.service import AIService, AnswerCheck
from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker
from bot.handlers import review
from bot.persona.card import DEFAULT_CARD
from bot.persona.memory import ChatMemory
from bot.utils import utcnow


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


class FakeMessage:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.chat = SimpleNamespace(id=1)
        self.bot = SimpleNamespace(edit_message_reply_markup=self._edit)

    async def _edit(self, **kwargs):
        self.edited.append(kwargs)

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs.get("reply_markup")))
        return SimpleNamespace(chat=self.chat, message_id=100 + len(self.sent))


class FakeAI:
    def __init__(self, check):
        self.check, self.calls = check, []

    async def check_answer(self, persona, question, expected, answer, voice, lang, target, native, gender=""):
        self.calls.append(dict(question=question, expected=expected, answer=answer, voice=voice, lang=lang))
        return self.check


async def _setup(repo):
    user, deck = await repo.ensure_user(1, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    await repo.add_word(deck.id, {"lemma": "finestra", "display": "la finestra", "translations": ["окно"]}, utcnow())
    return user, deck


async def test_shown_card_waits_and_correct_answer_suggests_good(repo):
    user, deck = await _setup(repo)
    persona_row = await repo.active_persona(user)
    memory, message = ChatMemory(), FakeMessage()
    await review.send_next_card(message, repo, user, deck, DEFAULT_CARD, persona_row, memory=memory)
    assert "Ответь текстом или голосом" in message.sent[0][0]
    card_id, chat_id, message_id = memory.waiting_answer(1)

    ai = FakeAI(AnswerCheck("correct", 3, "Bravissimo!"))
    assert await review.answer_card(message, "окно", False, ai, repo, user, deck, DEFAULT_CARD, memory)
    assert ai.calls[0]["expected"] == "окно" and ai.calls[0]["lang"] == "ru"  # forward card: answer in Russian
    text, keyboard = message.sent[-1]
    assert "✅ Верно!" in text and "Bravissimo!" in text and "Твой ответ: <b>окно</b>" in text
    grades = [b.text for row in keyboard.inline_keyboard[:2] for b in row]
    assert grades[2].startswith("👉 👍 Хорошо") and not grades[0].startswith("👉")
    assert message.edited[0]["message_id"] == message_id  # «show answer» button removed from the card
    assert memory.waiting_answer(1) is None


async def test_not_an_answer_falls_through(repo):
    user, deck = await _setup(repo)
    memory, message = ChatMemory(), FakeMessage()
    await review.send_next_card(message, repo, user, deck, DEFAULT_CARD, await repo.active_persona(user), memory=memory)
    ai = FakeAI(AnswerCheck("not_answer", 1, ""))
    assert not await review.answer_card(message, "а что значит allora?", False, ai, repo, user, deck, DEFAULT_CARD, memory)
    assert memory.waiting_answer(1) is not None  # still waiting for the real answer


async def test_voice_answer_and_nothing_waiting(repo):
    user, deck = await _setup(repo)
    memory, message = ChatMemory(), FakeMessage()
    ai = FakeAI(AnswerCheck("almost", 2, "Почти! Не забудь артикль."))
    assert not await review.answer_card(message, "окно", False, ai, repo, user, deck, DEFAULT_CARD, memory)  # nothing open
    await review.send_next_card(message, repo, user, deck, DEFAULT_CARD, await repo.active_persona(user), memory=memory)
    assert await review.answer_card(message, "finestra", True, ai, repo, user, deck, DEFAULT_CARD, memory)
    text, _ = message.sent[-1]
    assert "Ты сказал(а): <b>finestra</b>" in text and "🟡 Почти!" in text
    assert ai.calls[0]["voice"] is True


def test_waiting_expires():
    memory = ChatMemory()
    memory.await_answer(1, card_id=5, chat_id=1, message_id=9)
    assert memory.waiting_answer(1) == (5, 1, 9)
    assert memory.waiting_answer(1, window=0) is None
    memory.stop_waiting(1)
    assert memory.waiting_answer(1) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"verdict": "correct", "rating": 3, "comment": "Sì!"}', ("correct", 3)),
        ('{"verdict": "almost", "rating": "x"}', ("almost", 2)),  # bad rating → from the verdict
        ('{"verdict": "wrong", "rating": 9}', ("wrong", 4)),  # clamped to 1..4
    ],
)
async def test_check_answer_parsing(raw, expected):
    class Provider:
        name = "p"

        async def complete(self, messages, json_mode=True):
            return raw

    check = await AIService([Provider()], []).check_answer(DEFAULT_CARD, "q", "окно", "окно", False, "ru", "it", "ru")
    assert (check.verdict, check.rating) == expected
