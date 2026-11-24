"""REST API for the Telegram Mini App. Runs in the same process (and event loop) as the bot.

Every request carries `Authorization: tma <initData>`; the user is the one Telegram signed for.
The API reuses the bot's AI service, repository, quotas and SRS, so the chat and the app share one deck.
"""

import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from aiogram import Bot
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot import srs
from bot.ai.schemas import AIError, WordAnalysis
from bot.ai.service import AIService
from bot.api.auth import AuthError, parse_init_data
from bot.audio import tts
from bot.billing import Billing, Quota
from bot.config import Settings
from bot.dashboard import dashboard
from bot.db.models import Card, Deck, User, Word
from bot.db.repo import Repo
from bot.handlers.premium import premium_invoice_link
from bot.handlers.review import expected_answer
from bot.langs import BASE_LANGS, LANGS, get_lang, learnable
from bot.persona.card import PersonaCard
from bot.persona.context import snapshot
from bot.utils import format_interval, utcnow

log = logging.getLogger(__name__)

MAX_TEXT = 120
MAX_AUDIO_BYTES = 2_000_000  # ~30 s of speech
TTS_CACHE_SIZE = 300


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
        question = "Как переводится?"
    else:
        prompt, prompt_lang = "; ".join(word.translations), user.native_lang
        question = f"Как будет {get_lang(deck.target_lang).adverb_ru}?"
    return {
        "id": card.id,
        "direction": card.direction,
        "prompt": prompt,
        "prompt_lang": prompt_lang,
        "question": question,
        "word": word_json(word),
        "intervals": {str(r): format_interval(intervals[r]) for r in (1, 2, 3, 4)},
    }


def quota_error(billing: Billing, quota: Quota) -> HTTPException:
    return HTTPException(status_code=402, detail={"code": "limit", "kind": quota.kind, "message": billing.limit_message(quota)})


def create_app(
    settings: Settings, sessionmaker: async_sessionmaker, ai: AIService, bot: Bot, static_dir: Path | None = None
) -> FastAPI:
    app = FastAPI(title="Rimy API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    tts_cache: OrderedDict[str, bytes] = OrderedDict()

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
                {"code": l.code, "name": l.english if c.user.native_lang == "en" else l.name_ru, "flag": l.flag}
                for l in learnable(c.user.native_lang)
            ],
            "base_langs": [{"code": code, "name": label} for code, label in BASE_LANGS.items()],
            "premium": c.user.is_premium(now),
            "premium_until": c.user.premium_until.isoformat() if c.user.premium_until else None,
            "price_stars": settings.premium_price_stars,
            "quotas": {q.kind: q.to_dict() for q in await c.billing.quotas(c.user, now)},
            "stats": {"words": snap.words, "due": snap.due, "reviewed_today": snap.reviewed_today, "streak": snap.streak},
            "mascot": c.persona.name,
            "is_admin": settings.is_admin(c.user.id),
        }

    @app.get("/api/admin/dashboard")
    async def admin_dashboard(c: C, days: int = 14) -> dict[str, Any]:
        """The team's live dashboard: only for ADMIN_IDS (it shows everyone's numbers)."""
        if not settings.is_admin(c.user.id):
            raise HTTPException(403, "admins only")
        return await dashboard(c.repo.s, utcnow(), settings.timezone, max(1, min(days, 90)))

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

    async def analyze(c: Ctx, text: str, count: bool = True) -> dict[str, Any]:
        """count=False: the action was already counted (a voice word counts only as "voice")."""
        if count:
            quota = await c.billing.try_consume(c.user, "word", utcnow())
            if quota.refused:
                raise quota_error(c.billing, quota)
        try:
            analysis = await ai.analyze_text(text, c.deck.target_lang, c.user.native_lang)
        except AIError as exc:
            log.exception("analysis failed")
            raise HTTPException(503, "AI is busy, try again") from exc
        return await analysis_json(c, analysis, text)

    async def analysis_json(c: Ctx, analysis: WordAnalysis, original: str) -> dict[str, Any]:
        lemma = analysis.lemma or original
        duplicates = await c.repo.find_duplicates(c.deck.id, lemma)
        return {
            **analysis.model_dump(),
            "lemma": lemma,
            "display": analysis.display or lemma,
            "duplicates": [word_json(w) for w in duplicates],
        }

    @app.post("/api/words/analyze")
    async def analyze_text(body: TextIn, c: C) -> dict[str, Any]:
        return await analyze(c, body.text.strip())

    @app.post("/api/words/analyze-voice")
    async def analyze_voice(c: C, audio: UploadFile = File(...)) -> dict[str, Any]:
        """Voice input from the app's mic button: speech → text → the same card analysis."""
        data = await audio.read()
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio is empty or longer than ~30 seconds")
        quota = await c.billing.try_consume(c.user, "voice", utcnow())
        if quota.refused:
            raise quota_error(c.billing, quota)
        try:
            heard = await ai.transcribe(data, audio.content_type or "audio/webm", c.deck.target_lang, c.user.native_lang)
        except AIError as exc:
            log.exception("transcription failed")
            raise HTTPException(503, "speech recognition is busy, try again") from exc
        heard = heard.rstrip("?").strip()[:MAX_TEXT]
        if not heard:
            raise HTTPException(422, "Не расслышал, попробуй ещё раз")
        return {**(await analyze(c, heard, count=False)), "heard": heard}  # after the spread: analysis has heard=""

    @app.post("/api/words")
    async def save_word(body: DraftIn, c: C) -> dict[str, Any]:
        now = utcnow()
        draft = body.model_dump()
        draft["display"] = draft["display"] or draft["lemma"]
        word = await c.repo.add_word(c.deck.id, draft, now)
        await c.billing.track_once(c.user.id, "first_word", now, source="app")
        await c.billing.track(c.user.id, "word_saved", now, source="app", lang=c.deck.target_lang)
        return word_json(word)

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
            return {"card": None, "due": 0, "next_in": format_interval(next_at - now) if next_at else None}
        return {"card": card_json(card, c.deck, c.user), "due": due}

    async def check(c: Ctx, card: Card, answer: str, voice: bool) -> dict[str, Any]:
        quota = await c.billing.try_consume(c.user, "check", utcnow())
        if quota.refused:
            return {"verdict": "unknown", "rating": None, "comment": c.billing.limit_message(quota), "answer": answer}
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
            raise HTTPException(422, "Не расслышал, попробуй ещё раз")
        return await check(c, card, heard, True)

    @app.post("/api/review/{card_id}/rate")
    async def rate(card_id: int, body: RateIn, c: C) -> dict[str, Any]:
        card = await own_card(c, card_id)
        now = utcnow()
        new_state, due = srs.review(card.fsrs, body.rating, now)
        await c.repo.record_review(card, body.rating, new_state, due, now)
        await c.billing.track_once(c.user.id, "first_review", now, source="app")
        return {"next_in": format_interval(due - now)}

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
        return {"link": await premium_invoice_link(bot, settings)}

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
