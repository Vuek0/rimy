import pytest

from bot.ai.schemas import AIError
from bot.ai.service import AIService, SuggestedWord, build_ai
from bot.config import Settings

GOOD = '{"lemma": "finestra", "display": "la finestra", "senses": [{"translation": "окно"}]}'


class FakeText:
    def __init__(self, name, result=None, error=None):
        self.name, self.result, self.error, self.calls = name, result, error, 0
        self.last_messages = None

    async def complete(self, messages, json_mode=True):
        self.calls += 1
        self.last_messages = messages
        if self.error:
            raise self.error
        return self.result(messages) if callable(self.result) else self.result


class FakeVoice:
    def __init__(self, name, result="", error=None):
        self.name, self.result, self.error = name, result, error

    async def transcribe(self, audio, mime_type, hint, language=None):
        if self.error:
            raise self.error
        return self.result


async def test_falls_back_on_error_and_on_broken_json():
    down = FakeText("down", error=RuntimeError("503"))
    broken = FakeText("broken", result="not json")
    good = FakeText("good", result=GOOD)
    unused = FakeText("unused", result=GOOD)
    ai = AIService([down, broken, good, unused], [])
    analysis = await ai.analyze_text("finestra", "it", "ru")
    assert analysis.display == "la finestra"
    assert (down.calls, broken.calls, good.calls, unused.calls) == (1, 1, 1, 0)


async def test_word_from_a_reply_keeps_its_meaning_and_skips_suggestions():
    provider = FakeText(
        "ok",
        result='{"lemma": "dai", "is_valid": false, "suggestions": ["dare"], "senses": [{"translation": "давай!"}]}',
    )
    ai = AIService([provider], [])
    analysis = await ai.analyze_text("dai", "it", "ru", meaning="давай!", context="Dai, ce la fai!")
    assert analysis.suggestions == [] and analysis.is_valid
    prompt = provider.last_messages[-1]["content"]
    assert "давай!" in prompt and "Dai, ce la fai!" in prompt and "exactly ONE sense" in prompt
    plain = await ai.analyze_text("dai", "it", "ru")  # typed by hand: suggestions stay
    assert plain.suggestions == ["dare"]
    assert "exactly ONE sense" not in provider.last_messages[-1]["content"]


async def test_all_text_providers_fail():
    ai = AIService([FakeText("a", error=RuntimeError("x")), FakeText("b", result="")], [])
    with pytest.raises(AIError):
        await ai.analyze_text("casa", "it", "ru")


async def test_voice_uses_transcript_then_text_chain():
    ai = AIService(
        [FakeText("good", result=GOOD)],
        [FakeVoice("whisper", error=RuntimeError("down")), FakeVoice("backup", result="  la finestra. ")],
    )
    analysis = await ai.analyze_voice(b"ogg", "audio/ogg", "it", "ru")
    assert analysis.heard == "la finestra"
    assert analysis.senses[0].translation == "окно"


async def test_voice_silence_and_no_transcribers():
    text = FakeText("good", result=GOOD)
    silent = AIService([text], [FakeVoice("whisper", result="")])
    assert (await silent.analyze_voice(b"", "audio/ogg", "it", "ru")).heard == ""
    assert text.calls == 0
    with pytest.raises(AIError):
        await AIService([text], []).analyze_voice(b"", "audio/ogg", "it", "ru")


def test_build_ai_order_and_requires_a_key():
    base = dict(bot_token="t", owner_id=1, _env_file=None)
    ai = build_ai(Settings(**base, groq_api_key="g", gemini_api_key="m"))
    names = [p.name for p in ai.text_providers]
    assert names[0] == "groq:openai/gpt-oss-120b" and names[-1] == "gemini"
    assert [t.name for t in ai.transcribers] == ["groq:whisper", "gemini"]
    with pytest.raises(ValueError):
        build_ai(Settings(**base))


# --- routing & persona ---

from bot.persona.card import DEFAULT_CARD, MASCOT_NAME, PersonaCard  # noqa: E402


async def test_route_parses_and_rejects_unknown_intent():
    ai = AIService([FakeText("bad", result='{"intent": "dance"}'), FakeText("ok", result='{"intent": "word", "word": "gatto"}')], [])
    route = await ai.route("добавь слово gatto", "it", "ru")
    assert (route.intent, route.word) == ("word", "gatto")


async def test_persona_reply_sends_card_history_and_mode():
    provider = FakeText(
        "ok",
        result='{"reply": "Ciao! **Bravo**", "words": ['
        '{"word": "dai", "meaning": "давай!"}, {"word": "", "meaning": "x"}, "bravo"]}',
    )
    ai = AIService([provider], [])
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}]
    reply = await ai.persona_reply(DEFAULT_CARD, history, "как дела?", "it", "ru", practice=True)
    assert reply.text == "Ciao! **Bravo**"
    # new format with meanings, and plain strings from older/looser answers
    assert reply.words == [SuggestedWord("dai", "давай!"), SuggestedWord("bravo", "")]
    system, *rest = provider.last_messages
    assert system["role"] == "system" and MASCOT_NAME in system["content"] and "PRACTICE MODE" in system["content"]
    assert rest == [*history, {"role": "user", "content": "как дела?"}]


async def test_uzbek_learner_gets_uzbek_latin():
    # the case from the stand: an Uzbek learner of French got a Russian reply and Cyrillic meanings
    russian = FakeText("russian", result='{"reply": "Салют, Расул! Пять минут в день, и ты уже говоришь по-французски!", '
                                         '"words": [{"word": "aujourd\'hui", "meaning": "бугун"}]}')
    uzbek = FakeText("uzbek", result='{"reply": "Salut, Rasul! Kuniga besh daqiqa, sekin, lekin ishonchli 🦥", '
                                     '"words": [{"word": "Comment ça va", "meaning": "қалайсан"}]}')
    ai = AIService([russian, uzbek], [])
    reply = await ai.persona_reply(DEFAULT_CARD, [], "Salut, Rimy", "fr", "uz")
    assert reply.text.startswith("Salut, Rasul!") and reply.words == [SuggestedWord("Comment ça va", "qalaysan")]
    system = uzbek.last_messages[0]["content"]
    # an English card, but the catchphrases in the learner's language
    assert "Latin alphabet" in system and "Sekin, lekin ishonchli" in system and "Медленно" not in system
    assert "Slowly but surely" not in system and "good-natured sloth" in system

    # every model answers in Russian: one more insisting round, transliterated rather than an error
    russian_only = FakeText("r", result='{"reply": "Хорошо, давай!"}')
    stubborn = AIService([russian_only], [])
    assert (await stubborn.persona_reply(DEFAULT_CARD, [], "hi", "fr", "uz")).text == "Xorosho, davay!"
    assert russian_only.calls == 2 and "IMPORTANT" in russian_only.last_messages[-2]["content"]

    # the model copies the user's "Rimi": the name is always Rimy, with Uzbek suffixes too
    named = FakeText("n", result='{"reply": "Salom! Men Rimiman. Rimi bilan oson, Rimiga yoz. Primitive"}')
    assert (await AIService([named], []).persona_reply(DEFAULT_CARD, [], "Salut, Rimi", "fr", "uz")).text == \
        "Salom! Men Rimyman. Rimy bilan oson, Rimyga yoz. Primitive"

    # learners of Russian legitimately get Cyrillic words; Russian-speaking users are untouched
    keep = FakeText("keep", result='{"reply": "Bu so\'z: **окно**"}')
    assert (await AIService([keep], []).persona_reply(DEFAULT_CARD, [], "hi", "ru", "uz")).text == "Bu so'z: **окно**"
    ru = FakeText("ru", result='{"reply": "Привет!"}')
    assert (await AIService([ru], []).persona_reply(DEFAULT_CARD, [], "hi", "it", "ru")).text == "Привет!"


def test_uzbek_transliteration():
    from bot.ai.script import looks_russian, uz_to_latin

    assert uz_to_latin("Ўзбекистон, қалайсан? Ғалаба, Ҳа! Ёшлар, Шаҳар, ер, цирк") == \
        "O'zbekiston, qalaysan? G'alaba, Ha! Yoshlar, Shahar, yer, sirk"
    assert uz_to_latin("Comment ça va") == "Comment ça va"
    assert looks_russian("Привет! Как дела? Пять минут в день") and not looks_russian("Қалайсан, дўстим?")
    # a Cyrillic name in a Latin reply isn't a Russian reply; a Russian reply with French words is
    assert not looks_russian("Salut, Расул! Bugun qaysi so'zni yodlaymiz? Comment ça va?")
    assert looks_russian("Салют, Расул! Comment ça va aujourd'hui? Пять минут в день, и ты уже говоришь!")


async def test_persona_reply_empty_falls_back():
    ai = AIService([FakeText("empty", result='{"reply": ""}'), FakeText("ok", result='{"reply": "ok"}')], [])
    assert (await ai.persona_reply(DEFAULT_CARD, [], "hi", "it", "ru")).text == "ok"


CARD = DEFAULT_CARD.model_copy(update={"name": "Мегумин", "source": "KonoSuba"}).model_dump_json()


async def test_create_persona_uses_wiki_for_existing_characters(monkeypatch):
    calls = []

    async def fake_wiki(name_en, source, fandom_wiki="", fandom_page=""):
        calls.append((name_en, source, fandom_wiki))
        return "Megumin is obsessed with explosion magic."

    monkeypatch.setattr("bot.ai.service.character_info", fake_wiki)
    identify = '{"existing": true, "name": "Мегумин", "name_en": "Megumin", "source": "KonoSuba", "fandom_wiki": "konosuba", "wiki_page": "Megumin"}'

    def answer(messages):
        prompt = messages[-1]["content"]
        return identify if "Is this an existing character" in prompt else CARD

    provider = FakeText("ok", result=answer)
    card = await AIService([provider], []).create_persona("Мегумин из коносубы", "it", "ru")
    assert card.name == "Мегумин" and card.source == "KonoSuba"
    assert calls == [("Megumin", "KonoSuba", "konosuba")]
    assert "explosion magic" in provider.last_messages[-1]["content"]


async def test_bad_card_falls_back_to_next_provider():
    ai = AIService([FakeText("bad", result='{"name": ""}'), FakeText("ok", result=CARD)], [])
    card = await ai.revise_persona(DEFAULT_CARD, "дерзче", "it", "ru")
    assert isinstance(card, PersonaCard) and card.name == "Мегумин"
