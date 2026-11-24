"""When the persona sends a sticker: never on questions, sometimes in small talk, on word milestones."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from bot.ai.service import AIService, PersonaReply
from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker
from bot.handlers import talk
from bot.handlers.add_word import word_milestone
from bot.persona.card import DEFAULT_CARD
from bot.persona.memory import ChatMemory
from bot.utils import utcnow

TZ = "Asia/Tashkent"


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


async def _add(repo, deck, n, at):
    word = None
    for i in range(n):
        word = await repo.add_word(deck.id, {"lemma": f"w{i}-{at.timestamp()}", "translations": ["x"]}, at)
    return word


async def test_milestones(repo):
    _, deck = await repo.ensure_user(1, native_lang="ru", timezone=TZ, target_lang="it")
    now = utcnow()

    first = await _add(repo, deck, 1, now)
    assert await word_milestone(repo, deck.id, first.id, TZ, now) is None  # first word: nothing special

    old = now - timedelta(days=5)
    await repo.s.execute(  # pretend the first word was saved 5 days ago
        type(first).__table__.update().where(type(first).__table__.c.id == first.id).values(created_at=old)
    )
    comeback = await _add(repo, deck, 1, now)
    assert "С возвращением" in await word_milestone(repo, deck.id, comeback.id, TZ, now)

    today = await _add(repo, deck, 8, now)  # 9 today + 1 old = 10 total, 9 today
    assert await word_milestone(repo, deck.id, today.id, TZ, now) is None
    tenth = await _add(repo, deck, 1, now)  # 10th today
    assert "10 новых слов за сегодня" in await word_milestone(repo, deck.id, tenth.id, TZ, now)

    last = await _add(repo, deck, 14, now)  # 25 in total
    assert "25" in await word_milestone(repo, deck.id, last.id, TZ, now)


class FakeProvider:
    name = "fake"

    def __init__(self, raw):
        self.raw = raw

    async def complete(self, messages, json_mode=True):
        return self.raw


@pytest.mark.parametrize(
    "raw, emotion",
    [
        ('{"reply": "Wow!", "emotion": "Surprised"}', "surprised"),
        ('{"reply": "ok", "emotion": "angry"}', "none"),  # unknown → none
        ('{"reply": "ok"}', "none"),
    ],
)
async def test_reply_emotion_parsing(raw, emotion):
    reply = await AIService([FakeProvider(raw)], []).persona_reply(DEFAULT_CARD, [], "hi", "it", "ru")
    assert reply.emotion == emotion


class FakeStatus:
    chat = SimpleNamespace(id=1)
    message_id = 100

    async def edit_text(self, *args, **kwargs):
        pass


@pytest.mark.parametrize(
    "small_talk, emotion, expected",
    [(True, "happy", ["happy"]), (False, "happy", []), (True, "none", [])],
)
async def test_sticker_only_in_small_talk_with_emotion(repo, monkeypatch, small_talk, emotion, expected):
    user, deck = await repo.ensure_user(1, native_lang="ru", timezone=TZ, target_lang="it")
    persona_row = await repo.active_persona(user)
    sent = []

    async def fake_reaction(message, repo_, row, card, event, text_html="", force=False, emotion=None):
        sent.append(emotion)
        return True

    async def fake_reply(*args, **kwargs):
        return PersonaReply("Ciao!", [], emotion)

    monkeypatch.setattr(talk.arts, "send_reaction", fake_reaction)
    ai = SimpleNamespace(persona_reply=fake_reply)
    await talk.answer_as_persona(
        FakeStatus(), "hi", ai, repo, ChatMemory(), user, deck, DEFAULT_CARD,
        persona_row=persona_row, small_talk=small_talk,
    )
    assert sent == expected


# --- conversation: answering the persona ---

from bot.ai.prompts import route_prompt  # noqa: E402
from bot.ai.service import Route  # noqa: E402
from bot.handlers import add_word  # noqa: E402


def test_memory_conversation_window():
    memory = ChatMemory()
    assert not memory.in_conversation(1) and memory.last_reply(1) == ""
    memory.add(1, "user", "hi")
    assert not memory.in_conversation(1)  # only the persona's replies open a conversation
    memory.add(1, "assistant", "Hai provato il gelato?")
    assert memory.in_conversation(1) and memory.last_reply(1) == "Hai provato il gelato?"
    assert not memory.in_conversation(1, window=0)
    memory.end_conversation(1)
    assert not memory.in_conversation(1) and memory.history(1)  # history kept


def test_route_prompt_shows_previous_message():
    assert "middle of a conversation" not in route_prompt("gelato!", "it", "ru")
    prompt = route_prompt("gelato!", "it", "ru", previous="Hai provato il gelato?")
    assert "Hai provato il gelato?" in prompt and '"chat"' in prompt


def _message(reply_to=None):
    return SimpleNamespace(reply_to_message=reply_to)


def test_replied_text_only_for_bot_messages():
    bot_msg = SimpleNamespace(from_user=SimpleNamespace(is_bot=True), text=" Ciao! ", caption=None)
    photo = SimpleNamespace(from_user=SimpleNamespace(is_bot=True), text=None, caption="Bravo!")
    own = SimpleNamespace(from_user=SimpleNamespace(is_bot=False), text="mine", caption=None)
    assert add_word.replied_text(_message(bot_msg)) == "Ciao!"
    assert add_word.replied_text(_message(photo)) == "Bravo!"
    assert add_word.replied_text(_message(own)) == ""
    assert add_word.replied_text(_message()) == ""


def test_mentioned_matches_rendered_text_against_markdown():
    history = [{"role": "assistant", "content": "Wow, **che bello**! Hai provato il gelato?"}]
    assert talk._mentioned("Wow, che bello! Hai provato il gelato?", history)
    assert not talk._mentioned("Something else entirely", history)


class Recorder:
    def __init__(self, intent="chat", word=""):
        self.routes, self.chats, self.words = [], [], []
        self.intent, self.word = intent, word

    async def route(self, text, target, native, previous=""):
        self.routes.append((text, previous))
        return Route(self.intent, self.word)


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()

    async def fake_answer(status, text, *args, replied="", **kwargs):
        rec.chats.append((text, replied))

    async def fake_analyze(status, word, *args, **kwargs):
        rec.words.append(word)

    monkeypatch.setattr(add_word, "answer_as_persona", fake_answer)
    monkeypatch.setattr(add_word, "analyze_and_handle", fake_analyze)
    return rec


async def _dispatch(rec, repo, memory, text, replied=""):
    user, deck = await repo.ensure_user(1, native_lang="ru", timezone=TZ, target_lang="it")
    await add_word.dispatch(
        FakeStatus(), text, None, rec, repo, user, deck, DEFAULT_CARD, None, memory, replied=replied
    )


async def test_short_answer_in_conversation_goes_to_the_persona(repo, recorder):
    memory = ChatMemory()
    await _dispatch(recorder, repo, memory, "gelato")  # no conversation: quick path, it's a word
    assert recorder.words == ["gelato"] and recorder.routes == []

    memory.add(1, "assistant", "Hai provato il gelato?")
    await _dispatch(recorder, repo, memory, "да, ел!")  # 2 words, but an answer
    assert recorder.routes[-1] == ("да, ел!", "Hai provato il gelato?")
    assert recorder.chats == [("да, ел!", "")]


async def test_telegram_reply_is_conversation_even_after_restart(repo, recorder):
    await _dispatch(recorder, repo, ChatMemory(), "sì", replied="Hai provato il gelato?")
    assert recorder.routes == [("sì", "Hai provato il gelato?")]
    assert recorder.chats == [("sì", "Hai provato il gelato?")]


async def test_explicit_word_ends_the_conversation(repo, recorder):
    memory = ChatMemory()
    memory.add(1, "assistant", "Hai provato il gelato?")
    recorder.intent, recorder.word = "word", "gelato"
    await _dispatch(recorder, repo, memory, "добавь gelato")
    assert recorder.words == ["gelato"] and not memory.in_conversation(1)
    await _dispatch(recorder, repo, memory, "gatto")  # back to the quick path
    assert recorder.words == ["gelato", "gatto"] and len(recorder.routes) == 1


@pytest.mark.parametrize(
    "raw, sticker",
    [('{"reply": "ok", "sticker": true}', True), ('{"reply": "ok", "sticker": "true"}', True),
     ('{"reply": "ok", "sticker": false}', False), ('{"reply": "ok"}', False)],
)
async def test_sticker_flag_parsing(raw, sticker):
    reply = await AIService([FakeProvider(raw)], []).persona_reply(DEFAULT_CARD, [], "hi", "it", "ru")
    assert reply.sticker is sticker


async def test_asked_for_sticker_is_always_sent(repo, monkeypatch):
    user, deck = await repo.ensure_user(1, native_lang="ru", timezone=TZ, target_lang="it")
    persona_row = await repo.active_persona(user)
    calls = []

    async def fake_reaction(message, repo_, row, card, event, text_html="", force=False, emotion=None):
        calls.append((emotion, force))
        return True

    async def fake_reply(*args, **kwargs):
        return PersonaReply("Ecco! 😉", [], "none", sticker=True)

    monkeypatch.setattr(talk.arts, "send_reaction", fake_reaction)
    await talk.answer_as_persona(
        FakeStatus(), "скинь стикер", SimpleNamespace(persona_reply=fake_reply), repo, ChatMemory(),
        user, deck, DEFAULT_CARD, persona_row=persona_row, small_talk=False,
    )
    assert calls == [("happy", True)]


def test_persona_prompt_has_grammatical_gender_rules():
    from bot.ai.prompts import persona_system_prompt

    female = persona_system_prompt("{}", "it", "ru", False, "female")
    assert "я рада" in female and "я рад»" not in female
    assert "я рад»" in persona_system_prompt("{}", "it", "ru", False, "male")
    unknown = persona_system_prompt("{}", "it", "ru", False, "")
    assert "consistent" in unknown and "gender-neutral" in unknown  # the user's gender rule is always there
