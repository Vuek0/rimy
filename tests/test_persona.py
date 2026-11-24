import pytest

from bot.ai.service import SuggestedWord
from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker
from bot.handlers.talk import add_word_buttons, looks_like_word, split_known, words_hint
from bot.persona.card import DEFAULT_CARD, MASCOT_NAME, PersonaCard, markdown_to_html, phrase, render_card
from bot.persona.memory import ChatMemory
from bot.persona.wiki import api_url, clean_anilist, clean_wikitext, pick_character


@pytest.mark.parametrize("text", ["casa", "la finestra", "fare colazione", "mangato", "кошка"])
def test_words(text):
    assert looks_like_word(text)


@pytest.mark.parametrize(
    "text",
    ["как сказать я опоздал", "объясни congiuntivo", "что значит allora?", "привет", "ciao", "в чём разница между essere и stare"],
)
def test_not_words(text):
    assert not looks_like_word(text)


def test_markdown_to_html_escapes_first():
    assert markdown_to_html("**ciao** <b>x</b> e *bello*") == "<b>ciao</b> &lt;b&gt;x&lt;/b&gt; e <i>bello</i>"
    assert markdown_to_html("2 * 3 * 4") == "2 * 3 * 4"


def test_card_tolerates_messy_ai_output():
    card = PersonaCard.model_validate(
        {"name": "Мегумин", "personality": "взрывная", "source": None, "catchphrases": ["Explosion!", "", None],
         "phrases": {"saved": ["ok", ""], "unknown_kind": ["x"]}}
    )
    assert card.source == "" and card.catchphrases == ["Explosion!"] and card.phrases.saved == ["ok"]
    assert card.title == "Мегумин"
    assert phrase(card, "wrong", ["fallback"]) == "fallback"
    assert "<b>Мегумин</b>" in render_card(card)
    assert MASCOT_NAME in render_card(DEFAULT_CARD)


def test_add_word_buttons_show_meaning_skip_too_long_and_mark_known():
    new = [SuggestedWord("dai", "давай!, ну же!"), SuggestedWord("x" * 70), SuggestedWord("gatto")]
    kb = add_word_buttons(new, [SuggestedWord("ciao", "привет")])
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert [b.callback_data for b in buttons] == ["aw:dai", "aw:gatto", "awknown"]
    assert buttons[0].text == "➕ dai - давай!, ну же!"
    assert buttons[1].text == "➕ gatto"
    assert buttons[2].text == "✅ ciao - уже в колоде"
    long = add_word_buttons([SuggestedWord("parola", "очень длинное значение " * 5)])
    assert len(long.inline_keyboard[0][0].text) <= 47 and long.inline_keyboard[0][0].text.endswith("…")
    assert add_word_buttons([]) is None
    assert "➕" in words_hint(["gatto"], ["ciao"])
    assert "уже есть" in words_hint([], ["ciao"])
    assert words_hint([], []) == ""


def test_memory_remembers_word_meanings_per_reply():
    memory = ChatMemory()
    memory.remember_words(10, 5, {"dai": "давай!"}, "Dai, ce la fai!")
    assert memory.word_hint(10, 5, "dai") == ("давай!", "Dai, ce la fai!")
    assert memory.word_hint(10, 5, "gatto") == ("", "")
    assert memory.word_hint(10, 6, "dai") == ("", "")  # another message / forgotten after restart


def test_memory_keeps_last_messages():
    memory = ChatMemory(max_messages=3)
    for i in range(5):
        memory.add(1, "user", str(i))
    assert [m["content"] for m in memory.history(1)] == ["2", "3", "4"]
    memory.clear(1)
    assert memory.history(1) == []


def test_wiki_helpers():
    assert api_url("konosuba") == "https://konosuba.fandom.com/api.php"
    assert api_url("Konosuba.fandom.com", "ru") == "https://konosuba.fandom.com/ru/api.php"
    assert api_url("evil.com/../x") is None
    raw = "== Personality ==\n'''Megumin''' is {{Nihongo|a|b}} an [[Arch Wizard|arch wizard]].<ref>x</ref> [[File:a.png|thumb]]"
    assert clean_wikitext(raw) == "Personality:\nMegumin is  an arch wizard."


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


async def test_persona_lifecycle(repo):
    user, _ = await repo.ensure_user(1, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    roxy = await repo.active_persona(user)
    assert roxy.name == MASCOT_NAME and roxy.is_active  # the mascot is everyone's default tutor
    assert (await repo.active_persona(user)).id == roxy.id  # not duplicated

    megumin = await repo.add_persona(user, {**DEFAULT_CARD.model_dump(), "name": "Мегумин", "source": "KonoSuba"})
    assert (await repo.active_persona(user)).id == megumin.id
    assert not roxy.is_active

    await repo.update_persona(megumin, {**megumin.card, "name": "Мегумин-сама"})
    assert megumin.name == "Мегумин-сама"

    assert await repo.delete_persona(user, megumin.id)
    assert (await repo.active_persona(user)).id == roxy.id  # falls back to the remaining one
    assert not await repo.delete_persona(user, roxy.id)  # the last persona stays


def test_anilist_helpers():
    text = "Megumin is a [Crimson Demon](https://anilist.co/x). __Loves__ explosions. ~!Secret spoiler!~"
    assert clean_anilist(text) == "Megumin is a Crimson Demon. Loves explosions."
    a = {"name": {"full": "A"}, "media": {"nodes": [{"title": {"romaji": "Other Show"}}]}}
    b = {"name": {"full": "B"}, "media": {"nodes": [{"title": {"english": "KONOSUBA -God's blessing-"}}]}}
    assert pick_character([a, b], "KonoSuba") is b
    assert pick_character([a, b], "") is a
    assert pick_character([], "x") is None


async def test_split_known_dedupes_and_checks_deck(repo):
    from bot.utils import utcnow

    user, deck = await repo.ensure_user(1, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    await repo.add_word(deck.id, {"lemma": "ciao", "display": "ciao", "translations": ["привет"]}, utcnow())
    await repo.add_word(deck.id, {"lemma": "finestra", "display": "la finestra", "translations": ["окно"]}, utcnow())
    words = [SuggestedWord(w) for w in ["Ciao", "come stai", "ciao", "la finestra", " "]]
    new, known = await split_known(repo, deck.id, words)
    assert [w.word for w in new] == ["come stai"]
    assert [w.word for w in known] == ["Ciao", "la finestra"]
