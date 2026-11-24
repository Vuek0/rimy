from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    # Admins (comma-separated Telegram ids) get /backup, /admin and the daily backup. OWNER_ID still works.
    owner_id: int = 0
    admin_ids: str = ""

    # Telegram Mini App: public HTTPS URL of the web app (empty = no Mini App button) and the API server.
    webapp_url: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # Free plan: AI actions per day. Premium has no limits.
    free_words_per_day: int = 10
    free_voice_per_day: int = 5
    free_chat_per_day: int = 15
    free_checks_per_day: int = 30
    # Premium: a 30-day Telegram Stars subscription
    premium_price_stars: int = 123  # ≈ 30 000 sum for the buyer
    premium_days: int = 30
    # AI providers: any subset works; the chain is Groq → OpenAI → Gemini (see bot/ai/service.py).
    # Model lists are comma-separated: the first model is tried first, the next ones if it fails.
    groq_api_key: str = ""
    groq_models: str = "openai/gpt-oss-120b,qwen/qwen3.8-27b"
    groq_reasoning_effort: str = "medium"
    groq_transcribe_model: str = "whisper-large-v3-turbo"

    openai_api_key: str = ""
    openai_model: str = "gpt-6-luna"
    openai_transcribe_model: str = "gpt-4o-mini-transcribe"

    gemini_api_key: str = ""
    gemini_models: str = "gemini-3.8-flash,gemini-3.5-flash-lite,gemini-3.5-flash"
    gemini_thinking_level: str = "low"

    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    timezone: str = "Asia/Tashkent"
    native_lang: str = "ru"
    default_target_lang: str = "it"

    # Optional Danbooru account for character art (danbooru.donmai.us → My Account → API Key)
    danbooru_login: str = ""
    danbooru_api_key: str = ""

    # How the persona's reaction pictures look: "sticker" (small, 512px) or "photo" (full picture)
    reaction_style: Literal["sticker", "photo"] = "sticker"

    @property
    def admins(self) -> set[int]:
        ids = {int(part) for part in self.admin_ids.split(",") if part.strip().lstrip("-").isdigit()}
        return ids | ({self.owner_id} if self.owner_id else set())

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins

    def limit(self, kind: str) -> int:
        return {
            "word": self.free_words_per_day,
            "voice": self.free_voice_per_day,
            "chat": self.free_chat_per_day,
            "check": self.free_checks_per_day,
        }[kind]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
