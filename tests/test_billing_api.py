"""Free-plan quotas, Premium, and the Mini App API (initData auth, words, review, isolation between users)."""

import hashlib
import io
import hmac
import json
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest

from bot.ai.schemas import WordAnalysis
from bot.ai.service import AnswerCheck
from bot.api.app import create_app
from bot.api.auth import AuthError, parse_init_data
from bot.billing import Billing
from bot.config import Settings
from bot.db.repo import Repo
from bot.db.session import init_db, make_engine, make_sessionmaker
from bot.utils import utcnow

TOKEN = "123456:TEST-token"


def init_data(user_id: int, token: str = TOKEN, auth_date: int | None = None, start_param: str = "") -> str:
    """initData exactly as Telegram signs it (HMAC-SHA256 with the key derived from the bot token)."""
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": f"User{user_id}"}, separators=(",", ":")),
    }
    if start_param:
        fields["start_param"] = start_param
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def settings(url: str = "sqlite+aiosqlite:///:memory:", **kw) -> Settings:
    return Settings(bot_token=TOKEN, owner_id=1, database_url=url, free_words_per_day=2, _env_file=None, **kw)


class FakeAI:
    async def analyze_text(self, text, target, native, meaning="", context=""):
        # senses as dicts, like the parsed AI JSON (the validator keeps only dict senses)
        return WordAnalysis(lemma=text, display=f"la {text}", senses=[{"translation": "окно", "example": "Apri la finestra."}])

    async def transcribe(self, audio, mime, target, native="ru", force=False):
        return "finestra"

    async def check_answer(self, *args, **kwargs):
        return AnswerCheck("correct", 3, "Bravo!")


class FakeBot:
    async def create_invoice_link(self, **kwargs):
        assert kwargs["currency"] == "XTR" and kwargs["subscription_period"] == 30 * 24 * 3600
        return "https://t.me/$invoice"

    async def get_user_profile_photos(self, user_id, limit=1):
        # user 50 has a photo (three sizes), everyone else hides it or has none
        sizes = [SimpleNamespace(file_id=f"photo-{n}") for n in ("s", "m", "x")] if user_id == 50 else []
        return SimpleNamespace(total_count=1 if sizes else 0, photos=[sizes] if sizes else [])

    async def download(self, file_id):
        assert file_id == "photo-m"  # the ~160px size, not the full one
        return io.BytesIO(b"\xff\xd8jpeg")


# --- quotas & premium ---


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        yield Repo(session)
    await engine.dispose()


async def test_free_limit_then_premium_removes_it(repo):
    user, _ = await repo.ensure_user(7, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
    billing, now = Billing(repo.s, settings()), utcnow()
    assert not (await billing.try_consume(user, "word", now)).refused
    assert (await billing.try_consume(user, "word", now)).left == 0
    assert (await billing.try_consume(user, "word", now)).refused  # 3rd word of the day: refused
    assert (await billing.quota(user, "word", now)).used == 2  # the refused one is not counted
    assert not (await billing.try_consume(user, "word", now + timedelta(days=1))).refused  # a new day

    until = await billing.grant_premium(user, now, "charge-1", 250, "premium_30d")
    assert until - now == timedelta(days=30) and user.is_premium(now)
    assert await billing.grant_premium(user, now, "charge-1", 250, "premium_30d") == until  # duplicate update
    assert not (await billing.try_consume(user, "word", now)).refused  # unlimited now
    report = await billing.report(now - timedelta(days=1))
    assert report["stars"] == 250 and report["funnel"]["limit_reached"] == 1


# --- initData ---


def test_init_data_signature_and_age():
    now = utcnow()
    assert parse_init_data(TOKEN, init_data(42, start_param="ref_stand1"), now).start_param == "ref_stand1"
    with pytest.raises(AuthError):
        parse_init_data(TOKEN, init_data(42, token="999:other-bot"), now)  # signed by another bot
    with pytest.raises(AuthError):
        parse_init_data(TOKEN, init_data(42, auth_date=int(time.time()) - 3 * 86400), now)  # too old


# --- API ---


@pytest.fixture
async def client(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}"
    engine = make_engine(url)
    await init_db(engine)
    app = create_app(settings(url), make_sessionmaker(engine), FakeAI(), FakeBot())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


def auth(user_id: int, **kw) -> dict[str, str]:
    return {"Authorization": f"tma {init_data(user_id, **kw)}"}


async def test_base_and_target_language(client):
    assert (await client.post("/api/base", json={"code": "uz"}, headers=auth(20))).status_code == 200
    me = (await client.get("/api/me", headers=auth(20))).json()
    assert me["native_lang"] == "uz" and "uz" not in {l["code"] for l in me["langs"]}
    assert (await client.post("/api/lang", json={"code": "uz"}, headers=auth(20))).status_code == 400  # not the base
    await client.post("/api/lang", json={"code": "ko"}, headers=auth(20))
    await client.post("/api/base", json={"code": "en"}, headers=auth(20))
    assert (await client.get("/api/me", headers=auth(20))).json()["lang"] == "ko"  # the deck is kept
    await client.post("/api/lang", json={"code": "ru"}, headers=auth(20))
    await client.post("/api/base", json={"code": "ru"}, headers=auth(20))  # base = the learned language
    assert (await client.get("/api/me", headers=auth(20))).json()["lang"] == "en"  # moved to another deck
    assert (await client.post("/api/base", json={"code": "xx"}, headers=auth(20))).status_code == 400


async def test_admin_dashboard(client):
    # user 30 starts from a QR ref link, adds a word and reviews it
    await client.get("/api/me", headers=auth(30, start_param="ref_stand"))
    await client.post("/api/events", json={"name": "app_open"}, headers=auth(30))
    await client.post("/api/words/analyze", json={"text": "finestra"}, headers=auth(30))
    await client.post("/api/words", json={"lemma": "finestra", "translations": ["окно"]}, headers=auth(30))
    card = (await client.get("/api/review/next", headers=auth(30))).json()["card"]
    await client.post(f"/api/review/{card['id']}/rate", json={"rating": 3}, headers=auth(30))

    me = (await client.get("/api/me", headers=auth(30))).json()
    assert me["is_admin"] is False
    assert (await client.get("/api/admin/dashboard", headers=auth(30))).status_code == 403  # not for users

    admin = auth(1)  # owner_id=1 in the test settings
    assert (await client.get("/api/me", headers=admin)).json()["is_admin"] is True
    data = (await client.get("/api/admin/dashboard?days=7", headers=admin)).json()
    totals = data["totals"]
    assert totals["users"] == 2 and totals["words"] == 1 and totals["reviews"] == 1 and totals["active_today"] >= 1
    assert len(data["series"]["new_users"]) == 7 and data["series"]["new_users"][-1]["value"] == 2
    assert data["series"]["words"][-1]["value"] == 1 and data["series"]["reviews"][-1]["value"] == 1
    assert data["series"]["ai"][-1]["value"] == 1
    funnel = {step["key"]: step["users"] for step in data["funnel"]}
    assert funnel["first_word"] == 1 and funnel["first_review"] == 1 and funnel["app_open"] == 1
    assert data["refs"] == [{"ref": "stand", "users": 1}]
    assert {row["kind"]: row["count"] for row in data["ai_today"]}["word"] == 1


async def test_avatar_from_telegram(client):
    res = await client.get("/api/avatar", headers=auth(50))
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg" and res.content.startswith(b"\xff\xd8")
    assert (await client.get("/api/avatar", headers=auth(51))).status_code == 404  # no photo: the app shows the initial
    assert (await client.get("/api/avatar")).status_code == 401


async def test_api_requires_telegram_auth(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me", headers={"Authorization": f"tma {init_data(5, token='1:x')}"})).status_code == 401


async def test_add_review_and_limits(client):
    me = (await client.get("/api/me", headers=auth(10, start_param="ref_stand1"))).json()
    assert me["stats"]["words"] == 0 and me["quotas"]["word"]["limit"] == 2

    analysis = (await client.post("/api/words/analyze", json={"text": "finestra"}, headers=auth(10))).json()
    assert analysis["display"] == "la finestra" and analysis["senses"][0]["translation"] == "окно"
    draft = {"lemma": "finestra", "display": "la finestra", "translations": ["окно"]}
    word = (await client.post("/api/words", json=draft, headers=auth(10))).json()

    nxt = (await client.get("/api/review/next", headers=auth(10))).json()
    card = nxt["card"]
    assert card["prompt"] == "la finestra" and card["word"]["id"] == word["id"]
    check = (await client.post(f"/api/review/{card['id']}/answer", json={"text": "окно"}, headers=auth(10))).json()
    assert check["verdict"] == "correct" and check["rating"] == 3
    assert (await client.post(f"/api/review/{card['id']}/rate", json={"rating": 3}, headers=auth(10))).status_code == 200

    # another user can't see or grade someone else's cards and words
    assert (await client.post(f"/api/review/{card['id']}/rate", json={"rating": 1}, headers=auth(11))).status_code == 404
    assert (await client.delete(f"/api/words/{word['id']}", headers=auth(11))).status_code == 404
    assert (await client.get("/api/words", headers=auth(11))).json()["total"] == 0

    # free plan: 2 AI words a day → the 3rd is a 402 with the paywall message
    assert (await client.post("/api/words/analyze", json={"text": "casa"}, headers=auth(10))).status_code == 200
    limited = await client.post("/api/words/analyze", json={"text": "gatto"}, headers=auth(10))
    assert limited.status_code == 402 and limited.json()["detail"]["kind"] == "word"

    # a voice word counts only as "voice": it still works when the text words are used up
    voice = await client.post("/api/words/analyze-voice", files={"audio": ("v.webm", b"x", "audio/webm")}, headers=auth(10))
    assert voice.status_code == 200 and voice.json()["heard"] == "finestra"
    quotas = (await client.get("/api/me", headers=auth(10))).json()["quotas"]
    assert quotas["voice"]["used"] == 1 and quotas["word"]["used"] == 2

    assert (await client.post("/api/premium/invoice", headers=auth(10))).json()["link"].startswith("https://t.me/")
