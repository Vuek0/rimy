import json
import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from bot.ai import prompts
from bot.ai.providers import (
    GROQ_BASE_URL,
    Gemini,
    Messages,
    OpenAICompatibleText,
    OpenAICompatibleTranscriber,
    TextProvider,
    Transcriber,
    openai_client,
)
from bot.ai.schemas import AIError, WordAnalysis, parse_analysis, parse_json_object
from bot.config import Settings
from bot.persona.card import PersonaCard
from bot.persona.wiki import character_info

log = logging.getLogger(__name__)

INTENTS = ("word", "question", "chat")


@dataclass
class Route:
    intent: str  # word | question | chat
    word: str = ""


@dataclass
class SuggestedWord:
    """A word from a persona reply, with what it means in that reply ("dai" → "давай!", not the verb "dare")."""

    word: str
    meaning: str = ""


def parse_suggested_words(raw: object, limit: int = 5) -> list[SuggestedWord]:
    words: list[SuggestedWord] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            word, meaning = str(item.get("word") or "").strip(), str(item.get("meaning") or "").strip()
        else:
            word, meaning = str(item or "").strip(), ""
        if word:
            words.append(SuggestedWord(word, meaning))
    return words[:limit]


@dataclass
class PersonaReply:
    text: str
    words: list["SuggestedWord"] = field(default_factory=list)
    emotion: str = "none"  # the feeling for a sticker: happy / excited / sad / surprised / proud
    sticker: bool = False  # the persona wants to send a sticker now (asked for one, or a big moment)
    remember: list[str] = field(default_factory=list)  # new long-term facts about the user
    user_name: str = ""
    user_gender: str = ""  # male / female / ""


@dataclass
class Nudge:
    """A message the persona sends on its own (reminder, "I miss you", backup)."""

    text: str
    emotion: str = "happy"


EMOTIONS = ("happy", "excited", "sad", "surprised", "proud")
VERDICTS = ("correct", "almost", "wrong", "not_answer")


@dataclass
class AnswerCheck:
    """How a typed/spoken answer to a review card went."""

    verdict: str  # correct / almost / wrong / not_answer
    rating: int  # suggested grade 1-4
    comment: str = ""


class AIService:
    """Tries providers in order; if one fails (down, rate-limited, broken JSON) the next one answers."""

    def __init__(self, text_providers: list[TextProvider], transcribers: list[Transcriber]):
        if not text_providers:
            raise ValueError("no AI provider configured: set GROQ_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY")
        self.text_providers = text_providers
        self.transcribers = transcribers

    async def _ask(self, messages: Messages, parse):
        """Send to providers in order until one returns something `parse` accepts."""
        failures = []
        for i, provider in enumerate(self.text_providers):
            try:
                result = parse(await provider.complete(messages, json_mode=True))
            except Exception as exc:
                log.warning("text provider %s failed: %r", provider.name, exc)
                failures.append(f"{provider.name}: {exc!r}"[:300])
                continue
            # Which model answered: a fallback (i > 0) explains a sudden drop in answer quality.
            (log.warning if i else log.info)("answered by %s%s", provider.name, " (fallback)" if i else "")
            return result
        raise AIError("all text providers failed: " + " | ".join(failures))

    # --- words ---

    async def analyze_text(
        self, text: str, target: str, native: str, meaning: str = "", context: str = ""
    ) -> WordAnalysis:
        """meaning/context: the word was picked from a persona reply → save it with that meaning."""
        prompt = prompts.text_prompt(text, target, native, meaning, context)
        analysis = await self._ask(_user(prompt), parse_analysis)
        if meaning or context:
            # The word came from our own reply, spelled right and with a known meaning:
            # no "did you mean dare?" questions, just the card.
            analysis.suggestions = []
            analysis.is_valid = True
        return analysis

    async def route(self, text: str, target: str, native: str, previous: str = "") -> Route:
        """previous: the persona's last message, when the user may be answering it."""
        def parse(raw: str) -> Route:
            data = parse_json_object(raw)
            intent = str(data.get("intent", "")).strip().lower()
            if intent not in INTENTS:
                raise AIError(f"unknown intent {intent!r}")
            return Route(intent, str(data.get("word") or "").strip())

        return await self._ask(_user(prompts.route_prompt(text, target, native, previous)), parse)

    # --- voice ---

    async def transcribe(
        self, audio: bytes, mime_type: str, target: str, native: str = "ru", force: bool = False
    ) -> str:
        """target is the expected language. force=True when it's certain (practice mode, a card's answer):
        then recognition doesn't guess - short phrases with an accent were heard as the wrong language."""
        hint = prompts.transcription_hint(target, native)
        language = target if force else None
        failures = []
        for transcriber in self.transcribers:
            try:
                text = await transcriber.transcribe(audio, mime_type, hint, language)
                # Speech-to-text likes to add punctuation: "La finestra." → "La finestra"
                return text.strip().rstrip(".!…").strip()
            except Exception as exc:
                log.warning("transcriber %s failed: %r", transcriber.name, exc)
                failures.append(f"{transcriber.name}: {exc!r}"[:300])
        raise AIError("all transcribers failed: " + (" | ".join(failures) or "none configured"))

    async def analyze_voice(self, audio: bytes, mime_type: str, target: str, native: str) -> WordAnalysis:
        heard = (await self.transcribe(audio, mime_type, target, native)).rstrip("?").strip()
        if not heard:
            return WordAnalysis(heard="")
        analysis = await self.analyze_text(heard, target, native)
        analysis.heard = heard
        return analysis

    # --- persona ---

    async def identify_character(self, request: str) -> dict:
        """Is this an existing character? → {existing, name, name_en, source, danbooru_tag, ...}"""
        return await self._ask(_user(prompts.persona_identify_prompt(request)), parse_json_object)

    async def create_persona(self, request: str, target: str, native: str) -> PersonaCard:
        identified = await self.identify_character(request)
        wiki = ""
        if identified.get("existing"):
            wiki = await character_info(
                str(identified.get("name_en") or identified.get("wiki_page") or ""),
                str(identified.get("source") or ""),
                str(identified.get("fandom_wiki") or ""),
                str(identified.get("wiki_page") or ""),
            )
        log.info("persona %r identified as %s, wiki: %d chars", request, identified, len(wiki))
        prompt = prompts.persona_card_prompt(request, json.dumps(identified, ensure_ascii=False), wiki, target, native)
        card = await self._ask(_user(prompt), _parse_card)
        if identified.get("existing"):
            card.name_en = str(identified.get("name_en") or "")
            card.booru_tag = str(identified.get("danbooru_tag") or "")
        return card

    async def revise_persona(self, card: PersonaCard, instruction: str, target: str, native: str) -> PersonaCard:
        prompt = prompts.persona_revise_prompt(
            card.model_dump_json(exclude={"name_en", "booru_tag"}), instruction, target, native
        )
        revised = await self._ask(_user(prompt), _parse_card)
        revised.name_en, revised.booru_tag = card.name_en, card.booru_tag  # identity stays the same
        return revised

    async def persona_reply(
        self,
        card: PersonaCard,
        history: Messages,
        text: str,
        target: str,
        native: str,
        practice: bool = False,
        context: str = "",
    ) -> PersonaReply:
        """context: memory about the user, learning progress and mood (bot/persona/context.py)."""
        card_json = card.model_dump_json(exclude={"phrases"})
        system = prompts.persona_system_prompt(card_json, target, native, practice, card.gender, context)
        messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": text}]

        def parse(raw: str) -> PersonaReply:
            data = parse_json_object(raw)
            reply = str(data.get("reply") or "").strip()
            if not reply:
                raise AIError("empty reply")
            emotion = str(data.get("emotion") or "none").strip().lower()
            words = parse_suggested_words(data.get("words"))
            sticker = data.get("sticker") is True or str(data.get("sticker")).lower() == "true"
            remember = [str(f).strip() for f in data.get("remember") or [] if str(f).strip()][:5]
            gender = str(data.get("user_gender") or "").strip().lower()
            return PersonaReply(
                reply, words, emotion if emotion in EMOTIONS else "none", sticker,
                remember=remember,
                user_name=str(data.get("user_name") or "").strip()[:100],
                user_gender=gender if gender in ("male", "female") else "",
            )

        return await self._ask(messages, parse)

    async def check_answer(
        self, persona: PersonaCard, question: str, expected: str, answer: str, voice: bool,
        answer_lang: str, target: str, native: str, user_gender: str = "",
    ) -> AnswerCheck:
        style = persona.speech_style or persona.personality
        prompt = prompts.answer_check_prompt(
            question, expected, answer, voice, answer_lang, target, native, f"{persona.name}: {style}"[:300],
            user_gender,
        )

        def parse(raw: str) -> AnswerCheck:
            data = parse_json_object(raw)
            verdict = str(data.get("verdict") or "").strip().lower()
            if verdict not in VERDICTS:
                raise AIError(f"unknown verdict {verdict!r}")
            try:
                rating = min(4, max(1, int(data.get("rating") or 0)))
            except (TypeError, ValueError):
                rating = {"correct": 3, "almost": 2}.get(verdict, 1)
            return AnswerCheck(verdict, rating, str(data.get("comment") or "").strip())

        return await self._ask(_user(prompt), parse)

    async def nudge(self, card: PersonaCard, kind: str, target: str, native: str, context: str = "") -> Nudge:
        """A short in-character message the persona sends by itself: kind = review / miss_you / backup."""
        card_json = card.model_dump_json(exclude={"phrases"})
        prompt = prompts.nudge_prompt(card_json, target, native, card.gender, kind, context)

        def parse(raw: str) -> Nudge:
            data = parse_json_object(raw)
            text = str(data.get("text") or "").strip()
            if not text:
                raise AIError("empty nudge")
            emotion = str(data.get("emotion") or "happy").strip().lower()
            return Nudge(text, emotion if emotion in EMOTIONS else "happy")

        return await self._ask(_user(prompt), parse)


def _user(prompt: str) -> Messages:
    return [{"role": "user", "content": prompt}]


def _parse_card(raw: str) -> PersonaCard:
    try:
        card = PersonaCard.model_validate(parse_json_object(raw))
    except ValidationError as exc:
        raise AIError(f"bad persona card: {exc}") from exc
    if not card.name.strip() or not card.personality.strip():
        raise AIError("persona card without name or personality")
    return card


def build_ai(settings: Settings) -> AIService:
    """Order: Groq (free, fast) → OpenAI (paid, if a key is set) → Gemini (free, often overloaded)."""
    text: list[TextProvider] = []
    voice: list[Transcriber] = []

    if settings.groq_api_key:
        groq = openai_client(settings.groq_api_key, GROQ_BASE_URL)
        for model in _split(settings.groq_models):
            extra = {"reasoning_effort": settings.groq_reasoning_effort} if model.startswith("openai/gpt-oss") else {}
            text.append(OpenAICompatibleText(f"groq:{model}", groq, model, extra))
        voice.append(OpenAICompatibleTranscriber("groq:whisper", groq, settings.groq_transcribe_model))

    if settings.openai_api_key:
        oai = openai_client(settings.openai_api_key)
        text.append(OpenAICompatibleText(f"openai:{settings.openai_model}", oai, settings.openai_model))
        voice.append(OpenAICompatibleTranscriber("openai:transcribe", oai, settings.openai_transcribe_model))

    if settings.gemini_api_key:
        gemini = Gemini(settings.gemini_api_key, _split(settings.gemini_models), settings.gemini_thinking_level)
        text.append(gemini)
        voice.append(gemini)

    log.info("AI chain - text: %s; voice: %s", [p.name for p in text], [t.name for t in voice])
    return AIService(text, voice)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
