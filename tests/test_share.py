"""Virality: the lazy streak's milestones, achievement cards with an invite link, sharing from the Mini App."""

from datetime import timedelta

import httpx
import pytest

from bot import achievements, cards
from bot.api.app import create_app
from bot.billing import Billing
from bot.cards import CardSpec
from bot.dashboard import dashboard
from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker
from bot.utils import utcnow
from tests.test_billing_api import TOKEN, FakeAI, FakeBot, init_data, settings


def auth(user_id: int, **kw) -> dict[str, str]:
    return {"Authorization": f"tma {init_data(user_id, **kw)}"}


@pytest.fixture
async def app_env(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'share.db').as_posix()}"
    engine = make_engine(url)
    await init_db(engine)
    bot = FakeBot()
    maker = make_sessionmaker(engine)
    app = create_app(settings(url, webapp_url="https://rimy.test"), maker, FakeAI(), bot)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, bot, maker
    await engine.dispose()


def test_cards_render_in_every_language():
    for spec in (CardSpec("streak", 7, "ru", "it"), CardSpec("words", 25, "uz", "en"), CardSpec("streak", 1, "en", "ko", "story")):
        data = cards.render(spec)
        assert data[:2] == b"\xff\xd8" and len(data) > 10_000  # a real JPEG
    assert cards.caption("streak", 3, "ru").startswith("🔥 <b>3 дня подряд!")
    assert "5 слов" in cards.caption("words", 5, "ru") and "21 day" in cards.caption("streak", 21, "en")
    assert achievements.invite_code(36) == "friend_10"


async def test_word_milestone_card_with_invite_link(app_env):
    client, bot, _ = app_env
    for i in range(4):
        res = (await client.post("/api/words", json={"lemma": f"w{i}", "translations": ["t"]}, headers=auth(60))).json()
        assert res["achievement"] is None
    res = (await client.post("/api/words", json={"lemma": "w4", "translations": ["t"]}, headers=auth(60))).json()
    assert res["achievement"] == {"kind": "words", "n": 5}
    chat_id, photo, kwargs = bot.photos[-1]
    assert chat_id == 60 and photo[:2] == b"\xff\xd8"
    assert "ref_friend_" in kwargs["caption"] and "t.me/share/url" in kwargs["reply_markup"].inline_keyboard[0][0].url
    # celebrated once: deleting and re-adding the 5th word doesn't send it again
    words = (await client.get("/api/words", headers=auth(60))).json()["words"]
    await client.delete(f"/api/words/{words[0]['id']}", headers=auth(60))
    res = (await client.post("/api/words", json={"lemma": "w5", "translations": ["t"]}, headers=auth(60))).json()
    assert res["achievement"] is None and len(bot.photos) == 1


async def test_share_from_the_mini_app(app_env):
    client, bot, _ = app_env
    assert (await client.get("/api/share", headers=auth(70))).status_code == 409  # nothing yet
    await client.post("/api/words", json={"lemma": "gatto", "translations": ["кот"]}, headers=auth(70))
    info = (await client.get("/api/share", headers=auth(70))).json()
    assert info["kind"] == "words" and info["n"] == 1 and info["prepared_id"] == "prep-1"
    assert info["link"].startswith("https://t.me/rimy_ai_bot?start=ref_friend_")
    assert info["image_url"].startswith("https://rimy.test/api/card/words/1/ru/") and "/story/" in info["story_url"]
    assert bot.prepared[0]["result"].photo_url == info["image_url"]

    # the public image Telegram fetches: only signed cards are rendered
    path = info["image_url"].removeprefix("https://rimy.test")
    image = await client.get(path)
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert (await client.get(path.replace("/words/1/", "/words/999/"))).status_code == 404

    assert (await client.post("/api/share/send", headers=auth(70))).json() == {"ok": True}
    assert bot.photos[-1][0] == 70


async def test_streak_milestone_and_friends_in_the_dashboard(app_env):
    client, bot, maker = app_env
    await client.get("/api/me", headers=auth(80))
    async with maker() as s:
        repo = Repo(s)
        user, deck = await repo.ensure_user(80, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
        now = utcnow()
        for days_ago in (0, 2, 3):  # yesterday is the lazy rest day: a 4-day streak, the 3-day card
            await repo.add_word(deck.id, {"lemma": f"x{days_ago}", "display": "", "translations": ["t"]}, now - timedelta(days=days_ago))
        billing = Billing(s, settings())
        spec = await achievements.new_achievement(repo, billing, user, deck, now)
        assert spec == CardSpec("streak", 3, "ru", "it")
        assert await achievements.new_achievement(repo, billing, user, deck, now) is None  # once
        await s.commit()

    # a friend comes through the invite link
    await client.get("/api/me", headers=auth(81, start_param=f"ref_{achievements.invite_code(80)}"))
    await client.get("/api/me", headers=auth(82, start_param="ref_festival"))  # a stand code starting with "f"
    async with maker() as s:
        data = await dashboard(s, utcnow(), "Asia/Tashkent", 7)
    assert data["virality"] == {"invited": 1, "sharers": 1, "k": round(1 / 3, 2)}
    assert {r["ref"]: r["users"] for r in data["refs"]} == {"друзья по приглашениям": 1, "festival": 1}
