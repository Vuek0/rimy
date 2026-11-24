"""AI providers. Every provider does one or both jobs:
- TextProvider.complete(messages, json_mode) -> reply text (a JSON string when json_mode)
  messages: [{"role": "system" | "user" | "assistant", "content": str}, ...]
- Transcriber.transcribe(audio, mime_type, hint) -> transcript
"""

import asyncio
import logging
from typing import Any, Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from openai import AsyncOpenAI

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 40
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

_AUDIO_EXT = {
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
}


Messages = list[dict[str, str]]


class TextProvider(Protocol):
    name: str

    async def complete(self, messages: Messages, json_mode: bool = True) -> str: ...


class Transcriber(Protocol):
    name: str

    async def transcribe(self, audio: bytes, mime_type: str, hint: str, language: str | None = None) -> str: ...


# --- OpenAI-compatible APIs: OpenAI itself, Groq, and most other providers ---


class OpenAICompatibleText:
    def __init__(self, name: str, client: AsyncOpenAI, model: str, extra: dict[str, Any] | None = None):
        self.name = name
        self.client = client
        self.model = model
        self.extra = extra or {}

    async def complete(self, messages: Messages, json_mode: bool = True) -> str:
        kwargs: dict[str, Any] = dict(self.extra)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self.client.chat.completions.create(model=self.model, messages=messages, **kwargs)
        return response.choices[0].message.content or ""


class OpenAICompatibleTranscriber:
    def __init__(self, name: str, client: AsyncOpenAI, model: str):
        self.name = name
        self.client = client
        self.model = model

    async def transcribe(self, audio: bytes, mime_type: str, hint: str, language: str | None = None) -> str:
        """language: ISO code when we know what's spoken - then Whisper doesn't have to guess."""
        ext = _AUDIO_EXT.get(mime_type, "ogg")
        extra = {"language": language} if language else {}
        result = await self.client.audio.transcriptions.create(
            model=self.model, file=(f"voice.{ext}", audio, mime_type), prompt=hint, **extra
        )
        return result.text or ""


def openai_client(api_key: str, base_url: str | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT_S, max_retries=1)


# --- Gemini: its own SDK; tries a chain of models because single models get overloaded ---

GEMINI_FALLBACK_CODES = {429, 500, 502, 503, 504}


class Gemini:
    def __init__(self, api_key: str, models: list[str], thinking_level: str = "low"):
        if not models:
            raise ValueError("at least one Gemini model is required")
        self.name = "gemini"
        self.client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_S * 1000)
        )
        self.models = models
        self.thinking_level = thinking_level

    def _config(self, mime_type: str, thinking: bool, system: str | None) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            response_mime_type=mime_type,
            temperature=0.2 if mime_type == "application/json" else 0.8,
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_level=self.thinking_level) if thinking else None,
        )

    async def _call(self, model: str, contents: list, mime_type: str, system: str | None) -> str:
        try:
            response = await self.client.aio.models.generate_content(
                model=model, contents=contents, config=self._config(mime_type, True, system)
            )
        except genai_errors.ClientError as exc:
            # Some models don't accept the thinking level: retry once with the model's default.
            if exc.code == 400 and "thinking" in str(exc).lower():
                response = await self.client.aio.models.generate_content(
                    model=model, contents=contents, config=self._config(mime_type, False, system)
                )
            else:
                raise
        return response.text or ""

    async def _generate(self, contents: list, mime_type: str, system: str | None = None) -> str:
        last_error: Exception | None = None
        for model in self.models:
            try:
                return await self._call(model, contents, mime_type, system)
            except genai_errors.APIError as exc:
                last_error = exc
                log.warning("Gemini %s failed: %s %s", model, exc.code, str(exc)[:200])
                if exc.code not in GEMINI_FALLBACK_CODES:
                    raise
            except Exception as exc:  # timeouts, network errors
                last_error = exc
                log.warning("Gemini %s request failed: %r", model, exc)
            await asyncio.sleep(0.5)
        raise RuntimeError(f"all Gemini models failed, last error: {last_error!r}")

    async def complete(self, messages: Messages, json_mode: bool = True) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
        contents = [
            types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
            for m in messages
            if m["role"] != "system"
        ]
        return await self._generate(contents, "application/json" if json_mode else "text/plain", system)

    async def transcribe(self, audio: bytes, mime_type: str, hint: str, language: str | None = None) -> str:
        languages = f"The speaker speaks the language with code «{language}». " if language else (
            f"The speaker may use any of the languages in this sample: «{hint}». "
        )
        instruction = (
            "Transcribe this audio exactly as spoken. " + languages
            + "Write the words in the language actually spoken - never translate. "
            "Return only the transcript, without quotes or comments. If nothing intelligible is said, return nothing."
        )
        text = await self._generate([types.Part.from_bytes(data=audio, mime_type=mime_type), instruction], "text/plain")
        return text.strip().strip('"«»')
