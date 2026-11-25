"""REST API for the Telegram Mini App. Runs in the same process (and event loop) as the bot.

Every request carries `Authorization: tma <initData>`; the user is the one Telegram signed for.
The API reuses the bot's AI service, repository, quotas and SRS, so the chat and the app share one deck.
"""

import hmac
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultPhoto
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot import achievements, cards, promo, srs
from bot.ai.schemas import AIError, WordAnalysis
from bot.ai.service import AIService
from bot.api.auth import AuthError, parse_init_data
from bot.audio import tts
from bot.billing import Billing, Quota
from bot.config import Settings
from bot.admin_users import user_profile, users_list
from bot.dashboard import dashboard
from bot.db.models import Card, Deck, User, Word
from bot.db.repo import Repo
from bot.handlers.premium import premium_invoice_link
from bot.handlers.review import expected_answer
from bot.handlers.talk import looks_like_word
from bot.langs import BASE_LANGS, LANGS, card_question, learnable
from bot.persona.card import PersonaCard
from bot.persona.context import snapshot
from bot.utils import format_interval, utcnow

log = logging.getLogger(__name__)

MAX_TEXT = 120
MAX_AUDIO_BYTES = 2_000_000  # ~30 s of speech
TTS_CACHE_SIZE = 300
AVATAR_TTL = 3600  # seconds: a changed Telegram photo shows up within an hour
AVATAR_CACHE_SIZE = 500
CARD_CACHE_SIZE = 100


# --- request / response models ---


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class DraftIn(BaseModel):
    lemma: str = Field(min_length=1, max_length=200)
    display: str = Field(default="", max_length=200)
    reading: str = Field(default="", max_length=200)
    pos: str = Field(default="", max_length=50)
    translations: list[str] = Field(min_length=1, max_length=10)
    example: str = Field(default="", max_length=500)
    example_translation: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=500)


class LangIn(BaseModel):
    code: str


class RateIn(BaseModel):
    rating: int = Field(ge=1, le=4)


class AnalyzeIn(TextIn):
    # a word picked from Rimy's answer: the meaning it had there and the answer itself (one sense, that one)
    meaning: str = Field(default="", max_length=200)
    context: str = Field(default="", max_length=2000)


class ExplainIn(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    translation: str = Field(default="", max_length=200)


class PromoIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


class PromoCreateIn(BaseModel):
    days: int = Field(ge=1, le=365)
    max_uses: int = Field(default=0, ge=0, le=100_000)
    code: str = Field(default="", max_length=32)


class PromoActiveIn(BaseModel):
    active: bool


class EventIn(BaseModel):
    name: str = Field(pattern=r"^[a-z_]{2,40}$")
    props: dict[str, Any] = {}


# --- per-request context ---


@dataclass
class Ctx:
    repo: Repo
    billing: Billing
    user: User
    deck: Deck
    persona: PersonaCard


def word_json(word: Word) -> dict[str, Any]:
    return {
        "id": word.id,
        "lemma": word.lemma,
        "display": word.display,
        "reading": word.reading,
        "pos": word.pos,
        "translations": word.translations,
        "example": word.example,
        "example_translation": word.example_translation,
        "notes": word.notes,
        "created_at": word.created_at.isoformat(),
    }


def card_json(card: Card, deck: Deck, user: User) -> dict[str, Any]:
    word = card.word
    now = utcnow()
    intervals = srs.preview(card.fsrs, now)
    if card.direction == "fwd":
        prompt, prompt_lang = word.display, deck.target_lang
    else:
        prompt, prompt_lang = "; ".join(word.translations), user.native_lang
    return {
        "id": card.id,
        "direction": card.direction,
        "prompt": prompt,
        "prompt_lang": prompt_lang,
        "question": card_question(card.direction, deck.target_lang, user.native_lang),
        "word": word_json(word),
        "intervals": {str(r): format_interval(intervals[r], user.native_lang) for r in (1, 2, 3, 4)},
    }


NOT_HEARD = {"ru": "Не расслышал, попробуй ещё раз", "uz": "Eshitmadim, yana bir bor urinib ko'r", "en": "Didn't catch that, try again"}


def quota_error(billing: Billing, quota: Quota, lang: str) -> HTTPException:
    return HTTPException(
        status_code=402, detail={"code": "limit", "kind": quota.kind, "message": billing.limit_message(quota, lang)}
    )


def create_app(
    settings: Settings, sessionmaker: async_sessionmaker, ai: AIService, bot: Bot, static_dir: Path | None = None
) -> FastAPI:
    app = FastAPI(title="Rimy API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    tts_cache: OrderedDict[str, bytes] = OrderedDict()
    avatar_cache: OrderedDict[int, tuple[float, bytes]] = OrderedDict()  # user id → (fetched at, jpeg or b"")
    card_cache: OrderedDict[cards.CardSpec, bytes] = OrderedDict()  # rendered share cards

    async def ctx(authorization: Annotated[str, Header()] = "") -> AsyncIterator[Ctx]:
        scheme, _, init_data = authorization.partition(" ")
        if scheme.lower() != "tma" or not init_data:
            raise HTTPException(401, "missing Telegram initData")
        try:
            identity = parse_init_data(settings.bot_token, init_data, utcnow())
        except AuthError as exc:
            raise HTTPException(401, str(exc)) from exc
        async with sessionmaker() as session:
            repo = Repo(session)
            user, deck = await repo.ensure_user(
                identity.id, native_lang=settings.native_lang, timezone=settings.timezone,
                target_lang=settings.default_target_lang,
            )
            user.first_name, user.username = identity.first_name[:100], identity.username[:64]
            if identity.start_param.startswith("ref_") and not user.ref:
                user.ref = identity.start_param[4:][:64]
            user.last_active_at = utcnow()
            persona = PersonaCard.model_validate((await repo.active_persona(user)).card)
            yield Ctx(repo, Billing(session, settings), user, deck, persona)
            await session.commit()

    C = Annotated[Ctx, Depends(ctx)]

    # --- profile ---

    @app.get("/api/me")
    async def me(c: C) -> dict[str, Any]:
        now = utcnow()
        snap = await snapshot(c.repo, c.user, c.deck, now, None)
        return {
            "id": c.user.id,
            "first_name": c.user.first_name,
            "native_lang": c.user.native_lang,
            "lang": c.deck.target_lang,
            "langs": [
                {"code": l.code, "name": l.name(c.user.native_lang), "flag": l.flag}
                for l in learnable(c.user.native_lang)
            ],
            "base_langs": [{"code": code, "name": label} for code, label in BASE_LANGS.items()],
            "premium": c.user.is_premium(now),
            "premium_until": c.user.premium_until.isoformat() if c.user.premium_until else None,
            "price_stars": settings.premium_price_stars,
            "quotas": {q.kind: q.to_dict() for q in await c.billing.quotas(c.user, now)},
            "stats": {"words": snap.words, "due": snap.due, "reviewed_today": snap.reviewed_today, "streak": snap.streak},
            "mascot": c.persona.name,  # "Rimy" in every language
            "is_admin": settings.is_admin(c.user.id),
            "promo_pending_days": await promo.pending_days(c.repo.s, c.user),
        }

    async def avatar_response(user_id: int) -> Response:
        """A Telegram profile photo, fetched by the bot (the bot token never reaches the browser).
        404 when there is none or the user's privacy settings hide it: the app shows the initial instead."""
        now = time.monotonic()
        cached = avatar_cache.get(user_id)
        if cached is None or now - cached[0] > AVATAR_TTL:
            data = b""
            try:
                photos = await bot.get_user_profile_photos(user_id, limit=1)
                if photos.total_count:
                    smallest_good = photos.photos[0][min(1, len(photos.photos[0]) - 1)]  # ~160px is plenty
                    buffer = await bot.download(smallest_good.file_id)
                    data = buffer.read() if buffer else b""
            except Exception:  # noqa: BLE001 - no avatar is not an error worth failing the profile for
                log.warning("avatar for %s is unavailable", user_id, exc_info=True)
            cached = (now, data)
            avatar_cache[user_id] = cached
            while len(avatar_cache) > AVATAR_CACHE_SIZE:
                avatar_cache.popitem(last=False)
        if not cached[1]:
            raise HTTPException(404, "no avatar")
        return Response(cached[1], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/avatar")
    async def avatar(c: C) -> Response:
        return await avatar_response(c.user.id)

    @app.post("/api/promo")
    async def redeem_promo(body: PromoIn, c: C) -> dict[str, Any]:
        result = await promo.redeem(c.repo.s, c.user, body.code, utcnow())
        return {
            "status": result.status,
            "ok": result.status in ("applied", "pending", "already"),
            "message": promo.message(result, c.user.native_lang),
            "days": result.days,
        }

    # --- sharing progress (cards with an invite link) ---

    async def progress_spec(c: Ctx, fmt: str = "post") -> cards.CardSpec | None:
        """What to show off: the streak if there is one, otherwise the number of words."""
        now = utcnow()
        streak = await achievements.current_streak(c.repo, c.user, c.deck, now)
        if streak >= 2:
            return cards.CardSpec("streak", streak, c.user.native_lang, c.deck.target_lang, fmt)
        words = await c.repo.count_words(c.deck.id)
        if words > 0:
            return cards.CardSpec("words", words, c.user.native_lang, c.deck.target_lang, fmt)
        return None

    def public_url(spec: cards.CardSpec) -> str:
        return settings.webapp_url.rstrip("/") + achievements.card_path(settings.bot_token, spec)

    @app.get("/api/share")
    async def share_info(c: C) -> dict[str, Any]:
        """The Mini App's share sheet: the card, the invite link and (if Telegram allows) a prepared message
        that the app sends with Telegram's own chat picker (WebApp.shareMessage)."""
        spec = await progress_spec(c)
        if spec is None:
            raise HTTPException(409, "nothing to share yet")
        link = await achievements.invite_link(bot, c.user.id)
        text = cards.SHARE_TEXT.get(spec.lang, cards.SHARE_TEXT["ru"])
        prepared_id = None
        if settings.webapp_url:
            try:
                prepared = await bot.save_prepared_inline_message(
                    user_id=c.user.id,
                    result=InlineQueryResultPhoto(
                        id=f"{spec.kind}-{spec.n}-{c.user.id}",
                        photo_url=public_url(spec),
                        thumbnail_url=public_url(spec),
                        caption=f"{text} {link}",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🦥 Rimy", url=link)]]),
                    ),
                    allow_user_chats=True, allow_group_chats=True, allow_channel_chats=True,
                )
                prepared_id = prepared.id
            except Exception:  # noqa: BLE001 - the app falls back to sending the card into the chat
                log.warning("prepared share message failed", exc_info=True)
        story = cards.CardSpec(spec.kind, spec.n, spec.lang, spec.target, "story")
        return {
            "kind": spec.kind,
            "n": spec.n,
            "link": link,
            "text": text,
            "image_url": public_url(spec) if settings.webapp_url else None,
            "story_url": public_url(story) if settings.webapp_url else None,
            "prepared_id": prepared_id,
        }

    @app.post("/api/share/send")
    async def share_send(c: C) -> dict[str, bool]:
        """Fallback: the card goes into the chat with the bot, the user forwards it from there."""
        spec = await progress_spec(c)
        if spec is None:
            raise HTTPException(409, "nothing to share yet")
        await achievements.send_card(bot, c.user.id, spec)
        await c.billing.track(c.user.id, "shared", utcnow(), via="chat_card", kind=spec.kind)
        return {"ok": True}

    @app.get("/api/card/{kind}/{n}/{lang}/{target}/{fmt}/{signature}.jpg")
    async def card_image(kind: str, n: int, lang: str, target: str, fmt: str, signature: str) -> Response:
        """Public (Telegram fetches it for shared messages and stories), but only for cards we signed."""
        spec = cards.CardSpec(kind, n, lang, target, fmt)
        expected = achievements.card_signature(settings.bot_token, spec)
        if kind not in ("streak", "words") or fmt not in cards.SIZES or not hmac.compare_digest(signature, expected):
            raise HTTPException(404, "no such card")
        data = card_cache.get(spec)
        if data is None:
            data = cards.render(spec)
            card_cache[spec] = data
            while len(card_cache) > CARD_CACHE_SIZE:
                card_cache.popitem(last=False)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

    # --- admin (ADMIN_IDS only) ---

    def admin_only(c: Ctx) -> None:
        if not settings.is_admin(c.user.id):
            raise HTTPException(403, "admins only")

    @app.get("/api/admin/dashboard")
    async def admin_dashboard(c: C, days: int = 14) -> dict[str, Any]:
        """The team's live dashboard (it shows everyone's numbers)."""
        admin_only(c)
        return await dashboard(c.repo.s, utcnow(), settings.timezone, max(1, min(days, 90)))

    @app.get("/api/admin/users")
    async def admin_users(c: C, q: str = "", offset: int = 0) -> dict[str, Any]:
        admin_only(c)
        return await users_list(c.repo.s, utcnow(), q[:64], offset)

    @app.get("/api/admin/users/{user_id}")
    async def admin_user(user_id: int, c: C) -> dict[str, Any]:
        admin_only(c)
        profile = await user_profile(c.repo.s, user_id, utcnow())
        if profile is None:
            raise HTTPException(404, "no such user")
        return profile

    @app.get("/api/admin/users/{user_id}/avatar")
    async def admin_user_avatar(user_id: int, c: C) -> Response:
        admin_only(c)
        return await avatar_response(user_id)

    @app.get("/api/admin/promos")
    async def list_promos(c: C) -> dict[str, Any]:
        admin_only(c)
        return {"promos": await promo.overview(c.repo.s)}

    @app.post("/api/admin/promos")
    async def create_promo(body: PromoCreateIn, c: C) -> dict[str, Any]:
        admin_only(c)
        try:
            created = await promo.create(c.repo.s, utcnow(), body.days, body.max_uses, body.code)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"code": created.code, "id": created.id}

    @app.post("/api/admin/promos/{promo_id}")
    async def toggle_promo(promo_id: int, body: PromoActiveIn, c: C) -> dict[str, bool]:
        admin_only(c)
        if await promo.set_active(c.repo.s, promo_id, body.active) is None:
            raise HTTPException(404, "no such promo code")
        return {"active": body.active}

    @app.post("/api/lang")
    async def set_lang(body: LangIn, c: C) -> dict[str, Any]:
        """The language to learn (its own deck)."""
        if body.code not in LANGS or body.code == c.user.native_lang:
            raise HTTPException(400, "unknown language")
        deck = await c.repo.switch_language(c.user, body.code)
        c.user.onboarded = True
        return {"lang": deck.target_lang}

    @app.post("/api/base")
    async def set_base(body: LangIn, c: C) -> dict[str, Any]:
        """The base language: translations, explanations and the mascot's replies come in it."""
        if body.code not in BASE_LANGS:
            raise HTTPException(400, "unknown base language")
        c.user.native_lang = body.code
        if c.deck.target_lang == body.code:  # can't learn the base language itself: switch to another one
            fallback = "en" if body.code != "en" else "it"
            await c.repo.switch_language(c.user, fallback)
        return {"native_lang": body.code}

    @app.post("/api/events")
    async def event(body: EventIn, c: C) -> dict[str, bool]:
        """Client-side analytics: app_open, paywall_view…"""
        if body.name == "app_open":
            await c.billing.track_once(c.user.id, "app_open", utcnow())
        else:
            await c.billing.track(c.user.id, body.name, utcnow(), source="app", **body.props)
        return {"ok": True}

    # --- adding words ---

    async def answer(c: Ctx, text: str, counted: bool) -> dict[str, Any]:
        """A question instead of a word ("what's the difference between ser and estar?"): Rimy answers,
        like in the chat. A typed question counts as a chat message; a spoken one already counted as voice."""
        if not counted:
            quota = await c.billing.try_consume(c.user, "chat", utcnow())
            if quota.refused:
                raise quota_error(c.billing, quota, c.user.native_lang)
        try:
            reply = await ai.persona_reply(c.persona, [], text, c.deck.target_lang, c.user.native_lang)
        except AIError as exc:
            log.exception("answer failed")
            raise HTTPException(503, "AI is busy, try again") from exc
        await c.billing.track(c.user.id, "app_question", utcnow())
        return {
            "kind": "answer",
            "question": text,
            "answer": reply.text,
            "answer_words": [{"word": w.word, "meaning": w.meaning} for w in reply.words],
        }

    async def analyze(c: Ctx, text: str, count: bool = True, meaning: str = "", context: str = "") -> dict[str, Any]:
        """count=False: the action was already counted (a voice word counts only as "voice").
        Not just a word (a question, a sentence)? The same intent routing as the chat decides.
        meaning/context: a word from Rimy's answer, analysed with the meaning it had there."""
        if not (meaning or context) and not looks_like_word(text):
            try:
                route = await ai.route(text, c.deck.target_lang, c.user.native_lang)
            except AIError:
                route = None  # can't tell: treat it as a word, as before
            if route is not None and route.intent != "word":
                return await answer(c, text, counted=not count)
            if route is not None and route.word:
                text = route.word
        text = text.rstrip("?").strip() or text
        if count:
            quota = await c.billing.try_consume(c.user, "word", utcnow())
            if quota.refused:
                raise quota_error(c.billing, quota, c.user.native_lang)
        try:
            analysis = await ai.analyze_text(text, c.deck.target_lang, c.user.native_lang, meaning, context)
        except AIError as exc:
            log.exception("analysis failed")
            raise HTTPException(503, "AI is busy, try again") from exc
        return await analysis_json(c, analysis, text)

    async def analysis_json(c: Ctx, analysis: WordAnalysis, original: str) -> dict[str, Any]:
        lemma = analysis.lemma or original
        duplicates = await c.repo.find_duplicates(c.deck.id, lemma)
        return {
            **analysis.model_dump(),
            "kind": "word",
            "lemma": lemma,
            "display": analysis.display or lemma,
            "duplicates": [word_json(w) for w in duplicates],
        }

    @app.post("/api/words/analyze")
    async def analyze_text(body: AnalyzeIn, c: C) -> dict[str, Any]:
        return await analyze(c, body.text.strip(), meaning=body.meaning.strip(), context=body.context.strip())

    @app.post("/api/words/analyze-voice")
    async def analyze_voice(c: C, audio: UploadFile = File(...)) -> dict[str, Any]:
        """Voice input from the app's mic button: speech → text → the same card analysis."""
        data = await audio.read()
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio is empty or longer than ~30 seconds")
        quota = await c.billing.try_consume(c.user, "voice", utcnow())
        if quota.refused:
            raise quota_error(c.billing, quota, c.user.native_lang)
        try:
            heard = await ai.transcribe(data, audio.content_type or "audio/webm", c.deck.target_lang, c.user.native_lang)
        except AIError as exc:
            log.exception("transcription failed")
            raise HTTPException(503, "speech recognition is busy, try again") from exc
        heard = heard.strip()[:MAX_TEXT]  # keep a "?": a spoken question is answered, not made a card
        if not heard.rstrip("?").strip():
            raise HTTPException(422, NOT_HEARD.get(c.user.native_lang, NOT_HEARD["ru"]))
        return {**(await analyze(c, heard, count=False)), "heard": heard}  # after the spread: analysis has heard=""

    @app.post("/api/words/explain")
    async def explain_word(body: ExplainIn, c: C) -> dict[str, str]:
        """The "Explain" button on a word card: a short explanation by Rimy (counts as a chat message)."""
        quota = await c.billing.try_consume(c.user, "chat", utcnow())
        if quota.refused:
            raise quota_error(c.billing, quota, c.user.native_lang)
        try:
            text = await ai.explain(c.persona, body.word, body.translation, c.deck.target_lang, c.user.native_lang)
        except AIError as exc:
            log.exception("explanation failed")
            raise HTTPException(503, "AI is busy, try again") from exc
        await c.billing.track(c.user.id, "word_explained", utcnow())
        return {"text": text}

    @app.post("/api/words")
    async def save_word(body: DraftIn, c: C) -> dict[str, Any]:
        now = utcnow()
        draft = body.model_dump()
        draft["display"] = draft["display"] or draft["lemma"]
        word = await c.repo.add_word(c.deck.id, draft, now)
        await c.billing.track_once(c.user.id, "first_word", now, source="app")
        await c.billing.track(c.user.id, "word_saved", now, source="app", lang=c.deck.target_lang)
        spec = await achievements.celebrate(bot, c.repo, c.billing, c.user, c.deck, now, word_saved=True)
        return {**word_json(word), "achievement": spec and {"kind": spec.kind, "n": spec.n}}

    @app.get("/api/words")
    async def list_words(c: C, limit: int = 200) -> dict[str, Any]:
        words = await c.repo.list_words(c.deck.id, limit=min(limit, 500))
        return {"words": [word_json(w) for w in words], "total": await c.repo.count_words(c.deck.id)}

    @app.delete("/api/words/{word_id}")
    async def delete_word(word_id: int, c: C) -> dict[str, bool]:
        word = await c.repo.word_of_user(c.user, word_id)
        if word is None:
            raise HTTPException(404, "no such word")
        await c.repo.delete_word(word.id)
        return {"ok": True}

    # --- review ---

    async def own_card(c: Ctx, card_id: int) -> Card:
        card = await c.repo.card_of_deck(c.deck.id, card_id)
        if card is None:
            raise HTTPException(404, "no such card")
        return card

    @app.get("/api/review/next")
    async def next_card(c: C, after: int | None = None) -> dict[str, Any]:
        now = utcnow()
        card = await c.repo.next_due_card(c.deck.id, now, after)
        due = await c.repo.count_due(c.deck.id, now)
        if card is None:
            next_at = await c.repo.next_due_at(c.deck.id)
            return {"card": None, "due": 0, "next_in": format_interval(next_at - now, c.user.native_lang) if next_at else None}
        return {"card": card_json(card, c.deck, c.user), "due": due}

    async def check(c: Ctx, card: Card, answer: str, voice: bool) -> dict[str, Any]:
        quota = await c.billing.try_consume(c.user, "check", utcnow())
        if quota.refused:
            return {"verdict": "unknown", "rating": None, "comment": c.billing.limit_message(quota, c.user.native_lang), "answer": answer}
        question, expected, lang = expected_answer(card, c.deck, c.user)
        try:
            result = await ai.check_answer(
                c.persona, question, expected, answer, voice, lang, c.deck.target_lang, c.user.native_lang, c.user.gender
            )
        except AIError:
            return {"verdict": "unknown", "rating": None, "comment": "", "answer": answer}
        return {"verdict": result.verdict, "rating": result.rating, "comment": result.comment, "answer": answer}

    @app.post("/api/review/{card_id}/answer")
    async def answer_text(card_id: int, body: TextIn, c: C) -> dict[str, Any]:
        return await check(c, await own_card(c, card_id), body.text.strip(), False)

    @app.post("/api/review/{card_id}/answer-voice")
    async def answer_voice(card_id: int, c: C, audio: UploadFile = File(...)) -> dict[str, Any]:
        card = await own_card(c, card_id)
        data = await audio.read()
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio is empty or too long")
        lang = c.user.native_lang if card.direction == "fwd" else c.deck.target_lang
        other = c.deck.target_lang if lang == c.user.native_lang else c.user.native_lang
        try:
            heard = await ai.transcribe(data, audio.content_type or "audio/webm", lang, other, force=True)
        except AIError as exc:
            raise HTTPException(503, "speech recognition is busy, try again") from exc
        if not heard:
            raise HTTPException(422, NOT_HEARD.get(c.user.native_lang, NOT_HEARD["ru"]))
        return await check(c, card, heard, True)

    @app.post("/api/review/{card_id}/rate")
    async def rate(card_id: int, body: RateIn, c: C) -> dict[str, Any]:
        card = await own_card(c, card_id)
        now = utcnow()
        new_state, due = srs.review(card.fsrs, body.rating, now)
        await c.repo.record_review(card, body.rating, new_state, due, now)
        await c.billing.track_once(c.user.id, "first_review", now, source="app")
        spec = await achievements.celebrate(bot, c.repo, c.billing, c.user, c.deck, now)
        return {
            "next_in": format_interval(due - now, c.user.native_lang),
            "achievement": spec and {"kind": spec.kind, "n": spec.n},
        }

    # --- pronunciation ---

    @app.get("/api/tts/{word_id}")
    async def speak(word_id: int, c: C, part: str = "word") -> Response:
        word = await c.repo.word_of_user(c.user, word_id)
        if word is None:
            raise HTTPException(404, "no such word")
        text = word.example if part == "example" else word.display
        deck = await c.repo.s.get(Deck, word.deck_id)
        voice = tts.voice_for(deck.target_lang if deck else c.deck.target_lang, c.persona.gender)
        if not text or voice is None:
            raise HTTPException(404, "nothing to say")
        key = tts.cache_key(voice, text)
        if (audio := tts_cache.get(key)) is None:
            audio = await tts.synthesize(text, voice)
            if audio is None:
                raise HTTPException(503, "speech service is unavailable")
            tts_cache[key] = audio
            while len(tts_cache) > TTS_CACHE_SIZE:
                tts_cache.popitem(last=False)
        tts_cache.move_to_end(key)
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})

    # --- premium ---

    @app.post("/api/premium/invoice")
    async def invoice(c: C) -> dict[str, str]:
        await c.billing.track(c.user.id, "paywall_view", utcnow(), source="app")
        return {"link": await premium_invoice_link(bot, settings, c.user.native_lang)}

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="webapp")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> Response:
        log.exception("API error on %s", request.url.path)
        return Response('{"detail":"internal error"}', status_code=500, media_type="application/json")

    return app
