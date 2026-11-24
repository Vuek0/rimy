"""Pronunciation: text → speech with Microsoft Edge neural voices (free), sent as a Telegram voice message.

Telegram voice messages accept MP3, so no conversion (and no ffmpeg) is needed.
Every phrase is synthesized once; afterwards its Telegram file_id is reused.
"""

import asyncio
import hashlib
import logging

import edge_tts
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, Message

from bot.db.repo import Repo

log = logging.getLogger(__name__)

RATE = "-10%"  # a little slower than natural speech: easier to catch every sound
TIMEOUT = 25
MAX_CHARS = 300

# language → (female voice, male voice)
VOICES = {
    "it": ("it-IT-ElsaNeural", "it-IT-DiegoNeural"),
    "en": ("en-GB-SoniaNeural", "en-GB-RyanNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-RemyMultilingualNeural"),
    "de": ("de-DE-TanjaNeural", "de-DE-ChristophNeural"),
    "pt": ("pt-PT-RaquelNeural", "pt-PT-DuarteNeural"),
    "ja": ("ja-JP-NanamiNeural", "ja-JP-KeitaNeural"),
    "ko": ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural"),
    "zh": ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"),
    "tr": ("tr-TR-EmelNeural", "tr-TR-AhmetNeural"),
    "ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
    "uz": ("uz-UZ-MadinaNeural", "uz-UZ-SardorNeural"),
}


def voice_for(lang: str, gender: str = "") -> str | None:
    """The persona's voice: male personas get the male voice, everyone else the female one."""
    pair = VOICES.get(lang)
    if pair is None:
        return None
    return pair[1] if gender.strip().lower() == "male" else pair[0]


def cache_key(voice: str, text: str) -> str:
    return hashlib.sha1(f"{voice}|{RATE}|{text}".encode()).hexdigest()


async def synthesize(text: str, voice: str) -> bytes | None:
    """MP3 bytes, or None if the TTS service is unavailable. Never raises."""
    try:
        communicate = edge_tts.Communicate(text[:MAX_CHARS], voice, rate=RATE)

        async def collect() -> bytes:
            return b"".join([chunk["data"] async for chunk in communicate.stream() if chunk["type"] == "audio"])

        data = await asyncio.wait_for(collect(), TIMEOUT)
        return data or None
    except Exception as exc:
        log.warning("TTS failed (%s): %r", voice, exc)
        return None


async def send_speech(message: Message, repo: Repo, text: str, lang: str, gender: str = "") -> bool:
    """Say `text` as a voice message. False if it couldn't be produced."""
    text = text.strip()
    voice = voice_for(lang, gender)
    if not text or voice is None:
        return False
    key = cache_key(voice, text)
    if file_id := await repo.tts_get(key):
        try:
            await message.answer_voice(file_id)
            return True
        except TelegramBadRequest:  # a file_id from another bot token: make it again
            await repo.tts_forget(key)
    data = await synthesize(text, voice)
    if data is None:
        return False
    sent = await message.answer_voice(BufferedInputFile(data, filename="speech.mp3"))
    if sent.voice:
        await repo.tts_put(key, sent.voice.file_id)
    return True
