from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.audio import tts
from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker
from bot.handlers.speech import speech_buttons
from bot.utils import utcnow


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


def test_voice_follows_persona_gender():
    assert tts.voice_for("it", "female") == "it-IT-ElsaNeural"
    assert tts.voice_for("it", "male") == "it-IT-DiegoNeural"
    assert tts.voice_for("it", "") == "it-IT-ElsaNeural"
    assert tts.voice_for("xx") is None
    assert tts.cache_key("v", "ciao") != tts.cache_key("v", "Ciao")


class FakeMessage:
    def __init__(self, dead=()):
        self.voices, self.dead = [], set(dead)

    async def answer_voice(self, voice, **kwargs):
        if isinstance(voice, str) and voice in self.dead:
            raise TelegramBadRequest(method=None, message="Bad Request: wrong file identifier")
        self.voices.append(voice)
        return SimpleNamespace(voice=SimpleNamespace(file_id=f"voice-{len(self.voices)}"))


async def test_speech_is_synthesized_once_then_cached(repo, monkeypatch):
    calls = []

    async def fake_synth(text, voice):
        calls.append((text, voice))
        return b"mp3"

    monkeypatch.setattr(tts, "synthesize", fake_synth)
    message = FakeMessage()
    assert await tts.send_speech(message, repo, "la finestra", "it", "female")
    assert await tts.send_speech(message, repo, "la finestra", "it", "female")
    assert calls == [("la finestra", "it-IT-ElsaNeural")]
    assert message.voices[1] == "voice-1"  # second time: by file_id

    # a dead file_id (another bot token) → synthesized again
    dead = FakeMessage(dead={"voice-1"})
    assert await tts.send_speech(dead, repo, "la finestra", "it", "female")
    assert len(calls) == 2


async def test_unavailable_tts_and_unknown_language(repo, monkeypatch):
    async def down(text, voice):
        return None

    monkeypatch.setattr(tts, "synthesize", down)
    assert not await tts.send_speech(FakeMessage(), repo, "ciao", "it")
    assert not await tts.send_speech(FakeMessage(), repo, "ciao", "xx")
    assert not await tts.send_speech(FakeMessage(), repo, "  ", "it")


async def test_word_ownership_and_buttons(repo):
    user, deck = await repo.ensure_user(1, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    word = await repo.add_word(deck.id, {"lemma": "casa", "display": "la casa", "translations": ["дом"],
                                         "example": "La casa è grande."}, utcnow())
    stranger, _ = await repo.ensure_user(2, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    assert (await repo.word_of_user(user, word.id)).id == word.id
    assert await repo.word_of_user(stranger, word.id) is None
    assert [b.callback_data for b in speech_buttons(word)] == [f"tts:w:{word.id}", f"tts:e:{word.id}"]
    word.example = ""
    assert len(speech_buttons(word)) == 1
