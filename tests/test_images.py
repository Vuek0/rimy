import io
from types import SimpleNamespace

import pytest
from PIL import Image

from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker
from bot.images import arts, booru
from bot.images.booru import Art, _danbooru_art, pick_tag, tag_candidates
from bot.images.sticker import square_box, to_sticker
from bot.persona.card import DEFAULT_CARD


def test_tag_candidates():
    assert tag_candidates("Satoru Gojo", "gojou_satoru") == ["gojou_satoru", "satoru_gojo", "gojo_satoru"]
    assert tag_candidates("Megumin") == ["megumin"]


def test_pick_tag_prefers_series_and_skips_other_series_and_aliases():
    found = [
        {"name": "rem_(re:zero)", "post_count": 9000},
        {"name": "rem_(kemono_friends)", "post_count": 50000},
        {"name": "rem_galleu", "post_count": 100},
    ]
    assert pick_tag(found, "Rem", "Re:Zero kara Hajimeru") == "rem_(re:zero)"
    horse = [{"name": "satoru_gojo_(racehorse)", "post_count": 30}]
    assert pick_tag(horse, "Satoru Gojo", "Jujutsu Kaisen") is None
    assert pick_tag([{"name": "gojou_satoru", "post_count": 0}], "Satoru Gojo", "") is None  # alias
    assert pick_tag([{"name": "megumin", "post_count": 11000}], "Megumin", "") == "megumin"


def _post(**overrides):
    post = {
        "id": 1, "large_file_url": "https://cdn/x.jpg", "file_ext": "jpg", "rating": "g", "is_banned": False,
        "tag_string": "megumin solo smile", "tag_string_artist": "some_artist", "source": "https://pixiv.net/1",
    }
    return {**post, **overrides}


def test_danbooru_filters():
    art = _danbooru_art(_post())
    assert art.post_id == "d1" and not art.is_ai and "solo" in art.tags
    assert art.credit == '🎨 <a href="https://pixiv.net/1">some artist</a>'
    assert _danbooru_art(_post(rating="s")) is None
    assert _danbooru_art(_post(file_ext="mp4")) is None
    assert _danbooru_art(_post(is_banned=True)) is None
    assert _danbooru_art(_post(tag_string="megumin ai-generated")).is_ai
    no_source = _danbooru_art(_post(source="", tag_string_artist=""))
    assert no_source.credit == '🎨 <a href="https://danbooru.donmai.us/posts/1">неизвестный автор</a>'


def test_caption_is_only_the_text_and_respects_telegram_limit():
    assert arts.caption("hi") == "hi"
    assert len(arts.caption("a" * 2000)) == 1024


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


MEGUMIN = DEFAULT_CARD.model_copy(update={"name": "Мегумин", "name_en": "Megumin", "source": "KonoSuba"})


async def _persona(repo, card=MEGUMIN):
    user, _ = await repo.ensure_user(1, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    return user, await repo.add_persona(user, card.model_dump())


async def test_resolve_tag_is_looked_up_once(repo, monkeypatch):
    calls = []

    async def fake_find(name, source, guess):
        calls.append(name)
        return None

    monkeypatch.setattr(booru, "find_character_tag", fake_find)
    _, persona = await _persona(repo)
    assert await arts.resolve_tag(persona, MEGUMIN) is None
    assert persona.art_tag == arts.NO_TAG
    assert await arts.resolve_tag(persona, MEGUMIN) is None
    assert calls == ["Megumin"]
    # original characters never trigger a search
    _, roxy = await _persona(repo, DEFAULT_CARD)
    assert await arts.resolve_tag(roxy, DEFAULT_CARD) is None and calls == ["Megumin"]


class FakeMessage:
    def __init__(self):
        self.photos = []
        self.stickers = []
        self.texts = []

    async def answer_photo(self, photo, caption=None, **kwargs):
        self.photos.append((photo, caption))
        file_id = photo if isinstance(photo, str) else f"photo-{len(self.photos)}"
        return SimpleNamespace(photo=[SimpleNamespace(file_id=file_id)])

    async def answer_sticker(self, sticker, **kwargs):
        self.stickers.append(sticker)
        file_id = sticker if isinstance(sticker, str) else f"sticker-{len(self.stickers)}"
        return SimpleNamespace(sticker=SimpleNamespace(file_id=file_id))

    async def answer(self, text, **kwargs):
        self.texts.append(text)


def _jpeg(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 80, 60)).save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def board(monkeypatch):
    """A fake image board with one art; returns a switch to make it empty."""
    art = Art(post_id="d7", image_url="u", page_url="p", artist="artist")
    state = {"arts": [art]}

    async def fake_search(tag, emotion=None, limit=40, solo_only=False):
        return list(state["arts"])

    async def fake_download_many(found, count):
        return [(a, _jpeg(600, 900)) for a in found[:count]]

    monkeypatch.setattr(booru, "search_arts", fake_search)
    monkeypatch.setattr(booru, "download_many", fake_download_many)
    return state


async def test_photo_reaction_downloads_then_reuses_cache(repo, board, monkeypatch):
    monkeypatch.setattr(arts, "STYLE", "photo")
    _, persona = await _persona(repo)
    persona.art_tag = "megumin"
    message = FakeMessage()

    assert await arts.send_reaction(message, repo, persona, MEGUMIN, "review_done", "Bravo!")
    cached = await repo.cached_arts(persona.id, "happy")
    assert [(c.post_id, c.file_id) for c in cached] == [("d7", "photo-1")]
    assert message.photos[0][1] == "Bravo!"  # nothing under the picture but the text

    board["arts"] = []  # nothing new on the board → the cached picture is reused by file_id
    assert await arts.send_reaction(message, repo, persona, MEGUMIN, "review_done", "Again", force=True)
    assert message.photos[1][0] == "photo-1"


async def test_sticker_reaction_sends_sticker_then_text_and_caches_separately(repo, board, monkeypatch):
    monkeypatch.setattr(arts, "STYLE", "sticker")
    _, persona = await _persona(repo)
    persona.art_tag = "megumin"
    message = FakeMessage()

    assert await arts.send_reaction(message, repo, persona, MEGUMIN, "review_done", "Bravo!")
    sent = message.stickers[0]
    assert sent.filename == "d7.webp"
    with Image.open(io.BytesIO(sent.data)) as image:
        assert image.format == "WEBP" and image.size == (512, 512)
    assert message.texts == ["Bravo!"] and message.photos == []
    assert [c.file_id for c in await repo.cached_arts(persona.id, "st:happy")] == ["sticker-1"]
    assert await repo.cached_arts(persona.id, "happy") == []  # photo cache untouched

    board["arts"] = []
    assert await arts.send_reaction(message, repo, persona, MEGUMIN, "wrong", force=True) is False  # no sad arts yet
    assert await arts.send_reaction(message, repo, persona, MEGUMIN, "correct", force=True)
    assert message.stickers[-1] == "sticker-1" and message.texts == ["Bravo!"]  # no text → no extra message


def test_square_box_keeps_the_top_of_tall_arts():
    assert square_box(600, 900) == (0, 72, 600, 672)  # 8% below the top edge
    assert square_box(600, 620) == (0, 20, 600, 620)  # never past the bottom
    assert square_box(900, 600) == (150, 0, 750, 600)  # wide: centered
    assert square_box(500, 500) == (0, 0, 500, 500)


def test_to_sticker():
    with Image.open(io.BytesIO(to_sticker(_jpeg(850, 1200)))) as image:
        assert image.size == (512, 512) and image.format == "WEBP"
    assert to_sticker(b"not an image") is None


async def _empty():
    return []


async def test_reaction_skipped_by_chance_and_without_tag(repo):
    _, persona = await _persona(repo, DEFAULT_CARD)
    message = FakeMessage()
    assert not await arts.send_reaction(message, repo, persona, DEFAULT_CARD, "review_done")
    assert not await arts.send_reaction(message, repo, persona, DEFAULT_CARD, "unknown_event")
    assert message.photos == []


async def test_delete_persona_removes_its_arts(repo):
    user, persona = await _persona(repo)
    await repo.add_persona(user, DEFAULT_CARD.model_dump(), activate=False)  # the last persona can't be deleted
    await repo.add_art(persona.id, "happy", "d1", "f1", "")
    await repo.add_art(persona.id, "happy", "d1", "f1", "")  # duplicate is ignored
    assert len(await repo.cached_arts(persona.id, "happy")) == 1
    await repo.set_avatar(persona, "f1", "🎨 x")
    assert persona.avatar_file_id == "f1"
    assert await repo.delete_persona(user, persona.id)
    assert await repo.cached_arts(persona.id, "happy") == []


async def test_original_persona_sends_its_avatar_as_a_sticker(repo, monkeypatch):
    monkeypatch.setattr(arts, "STYLE", "sticker")
    _, roxy = await _persona(repo, DEFAULT_CARD)
    message = FakeMessage()
    downloads = []

    async def download(file_id):
        downloads.append(file_id)
        return io.BytesIO(_jpeg(400, 700))

    message.bot = SimpleNamespace(download=download)

    # no avatar yet → nothing to send
    assert not await arts.send_reaction(message, repo, roxy, DEFAULT_CARD, "chat", force=True)

    await repo.set_avatar(roxy, "avatar-file-1", "")
    assert await arts.send_reaction(message, repo, roxy, DEFAULT_CARD, "chat", "Ciao!", force=True)
    with Image.open(io.BytesIO(message.stickers[0].data)) as image:
        assert image.size == (512, 512)
    assert message.texts == ["Ciao!"]

    # second time: the cached sticker, no new download
    assert await arts.send_reaction(message, repo, roxy, DEFAULT_CARD, "review_done", force=True)
    assert message.stickers[1] == "sticker-1" and downloads == ["avatar-file-1"]

    # review cards don't repeat the same avatar sticker
    assert not await arts.send_reaction(message, repo, roxy, DEFAULT_CARD, "correct", force=True)

    # a new avatar → a new sticker
    await repo.set_avatar(roxy, "avatar-file-2", "")
    assert await arts.send_reaction(message, repo, roxy, DEFAULT_CARD, "chat", force=True)
    assert downloads == ["avatar-file-1", "avatar-file-2"]


# --- file_ids from another bot (token changed, or a test bot sharing the DB) ---

from aiogram.exceptions import TelegramBadRequest  # noqa: E402

DEAD = "Bad Request: wrong file identifier/HTTP URL specified"


class PickyMessage(FakeMessage):
    """Rejects file_ids that this bot didn't upload."""

    def __init__(self, dead: set[str]):
        super().__init__()
        self.dead = dead

    async def answer_photo(self, photo, caption=None, **kwargs):
        if isinstance(photo, str) and photo in self.dead:
            raise TelegramBadRequest(method=None, message=DEAD)
        return await super().answer_photo(photo, caption, **kwargs)

    async def answer_sticker(self, sticker, **kwargs):
        if isinstance(sticker, str) and sticker in self.dead:
            raise TelegramBadRequest(method=None, message=DEAD)
        return await super().answer_sticker(sticker, **kwargs)

    async def answer(self, text, **kwargs):
        self.texts.append(text)


async def test_dead_avatar_falls_back_to_text_and_is_forgotten(repo):
    _, persona = await _persona(repo)
    await repo.set_avatar(persona, "other-bots-file", "")
    message = PickyMessage(dead={"other-bots-file"})
    await arts.answer_with_avatar(message, repo, persona, "Ciao!")
    assert message.texts == ["Ciao!"] and message.photos == []
    assert persona.avatar_file_id is None


async def test_dead_cached_sticker_is_dropped_and_replaced(repo, board, monkeypatch):
    monkeypatch.setattr(arts, "STYLE", "sticker")
    monkeypatch.setattr(arts, "REUSE_AFTER", 1)  # always try the cache first
    _, persona = await _persona(repo)
    persona.art_tag = "megumin"
    await repo.add_art(persona.id, "st:happy", "d1", "other-bots-sticker", "")
    message = PickyMessage(dead={"other-bots-sticker"})

    assert await arts.send_reaction(message, repo, persona, MEGUMIN, "review_done", force=True)
    cached = await repo.cached_arts(persona.id, "st:happy")
    assert [c.file_id for c in cached] == ["sticker-1"]  # the dead one is gone, a fresh one is cached


def test_other_bad_requests_are_not_mistaken_for_dead_files():
    assert arts.is_dead_file_id(TelegramBadRequest(method=None, message=DEAD))
    assert not arts.is_dead_file_id(TelegramBadRequest(method=None, message="Bad Request: message is too long"))
    assert not arts.is_dead_file_id(RuntimeError("file identifier"))


async def test_same_sticker_is_not_sent_twice_in_a_row(repo, board, monkeypatch):
    monkeypatch.setattr(arts, "STYLE", "sticker")
    monkeypatch.setattr(arts, "REUSE_AFTER", 1)  # always reuse the cache when possible
    _, persona = await _persona(repo)
    persona.art_tag = "megumin"
    await repo.add_art(persona.id, "st:happy", "d1", "f1", "")
    await repo.add_art(persona.id, "st:happy", "d2", "f2", "")
    message = FakeMessage()
    for _ in range(6):
        assert await arts.send_reaction(message, repo, persona, MEGUMIN, "review_done", force=True)
    sent = message.stickers
    assert all(a != b for a, b in zip(sent, sent[1:])), sent


# --- the user's own sticker sets (/stickers) ---

from bot.handlers.stickers import art_keyboard  # noqa: E402


async def test_my_set_wins_and_banned_never_come_back(repo, board, monkeypatch):
    monkeypatch.setattr(arts, "STYLE", "sticker")
    _, persona = await _persona(repo)
    persona.art_tag = "megumin"
    auto = await repo.add_art(persona.id, "st:happy", "d100", "auto-file", "")
    mine = await repo.add_art(persona.id, "st:happy", "tg:abc:happy", "my-file", "", pinned=True)
    message = FakeMessage()
    for _ in range(4):
        assert await arts.send_reaction(message, repo, persona, MEGUMIN, "review_done", force=True)
    assert set(message.stickers) == {"my-file"}  # only my set, even though another art is cached

    mine.pinned = False
    mine.banned = True  # 👎
    assert [a.id for a in await repo.cached_arts(persona.id, "st:happy")] == [auto.id]
    assert "tg:abc:happy" in await repo.known_post_ids(persona.id, "st:happy")
    board["arts"] = [Art(post_id="tg:abc:happy", image_url="u", page_url="p")]  # the banned one shows up again
    message = FakeMessage()
    for _ in range(3):
        await arts.send_reaction(message, repo, persona, MEGUMIN, "review_done", force=True)
    assert "my-file" not in message.stickers


async def test_forwarded_sticker_works_for_a_persona_without_arts(repo, monkeypatch):
    monkeypatch.setattr(arts, "STYLE", "sticker")
    _, roxy = await _persona(repo, DEFAULT_CARD)  # original character: no art tag, no avatar
    await repo.add_art(roxy.id, "st:sad", "tg:xyz:sad", "forwarded-file", "", pinned=True)
    message = FakeMessage()
    assert await arts.send_reaction(message, repo, roxy, DEFAULT_CARD, "wrong", force=True)
    assert message.stickers == ["forwarded-file"]


async def test_add_art_updates_and_ownership_is_checked(repo):
    user, persona = await _persona(repo)
    art = await repo.add_art(persona.id, "st:happy", "d1", "f1", "")
    art.banned = True
    again = await repo.add_art(persona.id, "st:happy", "d1", "f2", "", pinned=True)
    assert again.id == art.id and again.file_id == "f2" and again.pinned and not again.banned
    assert (await repo.get_art(user, art.id)).id == art.id
    stranger, _ = await repo.ensure_user(2, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    assert await repo.get_art(stranger, art.id) is None


def test_art_keyboard():
    art = SimpleNamespace(id=7, pinned=False)
    row = art_keyboard(art).inline_keyboard[0]
    assert [b.callback_data for b in row] == ["st:p:7", "st:b:7"] and row[0].text == "➕ В набор"
    art.pinned = True
    assert art_keyboard(art).inline_keyboard[0][0].text == "✅ В наборе"


# --- Danbooru blocked (403 from data-center IPs): Safebooru takes over ---

from bot.images.booru import parse_safebooru_tags  # noqa: E402

SAFEBOORU_XML = """<?xml version="1.0" encoding="UTF-8"?><tags type="array">
<tag type="0" count="15" name="roxy_migurdia_(cosplay)" ambiguous="false" id="1"/>
<tag type="4" count="1017" name="roxy_migurdia" ambiguous="false" id="2"/></tags>"""


def test_parse_safebooru_tags_keeps_characters_only():
    assert parse_safebooru_tags(SAFEBOORU_XML) == [{"name": "roxy_migurdia", "post_count": 1017}]


async def test_tag_lookup_falls_back_to_safebooru(monkeypatch):
    calls = []

    async def blocked(http, candidate):
        calls.append(("danbooru", candidate))
        raise RuntimeError("403 Forbidden")

    async def safebooru(http, candidate):
        calls.append(("safebooru", candidate))
        return parse_safebooru_tags(SAFEBOORU_XML)

    monkeypatch.setattr(booru, "_danbooru_tags", blocked)
    monkeypatch.setattr(booru, "_safebooru_tags", safebooru)
    assert await booru.find_character_tag("Roxy Migurdia", "Mushoku Tensei") == "roxy_migurdia"
    assert calls[:2] == [("danbooru", "roxy_migurdia"), ("safebooru", "roxy_migurdia")]


def test_danbooru_auth_is_optional():
    booru.configure("", "")
    assert booru._danbooru_auth is None
    booru.configure("me", "secret")
    assert booru._danbooru_auth.login == "me"
    booru.configure()  # back to anonymous for other tests


async def test_same_art_in_two_emotions_is_chosen_separately(repo):
    _, persona = await _persona(repo)
    happy = await repo.add_art(persona.id, "st:happy", "d42", "f-happy", "", pinned=True)
    proud = await repo.add_art(persona.id, "st:proud", "d42", "f-proud", "")
    assert happy.id != proud.id
    assert happy.pinned and not proud.pinned  # «✅ В наборе» only where it was chosen
    proud.pinned = True
    proud.banned = False
    happy.banned = True  # 👎 in one emotion doesn't touch the other
    assert [a.id for a in await repo.cached_arts(persona.id, "st:proud")] == [proud.id]
    assert await repo.cached_arts(persona.id, "st:happy") == []
