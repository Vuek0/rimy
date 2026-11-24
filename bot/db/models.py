from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bot.utils import utcnow


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC (works the same in SQLite and Postgres), returns aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed, use UTC-aware datetimes")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    native_lang: Mapped[str] = mapped_column(String(8), default="ru")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent")
    active_deck_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    practice_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # What the persona learned about the user (stage C: memory)
    name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    gender: Mapped[str] = mapped_column(String(10), default="", server_default="")  # male / female / ""

    # Activity and reminders
    last_active_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    reminder_hours: Mapped[str] = mapped_column(String(50), default="12,20", server_default="12,20")  # local hours
    last_reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Profile from Telegram and acquisition: where the user came from (/start ref_<code>)
    first_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    username: Mapped[str] = mapped_column(String(64), default="", server_default="")
    ref: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # Picked the base language and the language to learn on /start
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # Premium (Telegram Stars subscription): active while premium_until is in the future
    premium_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    def is_premium(self, now: datetime) -> bool:
        return self.premium_until is not None and self.premium_until > now


class Usage(Base):
    """How many AI actions of a kind (word / voice / chat / check) a user made on a day (user's local date)."""

    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("user_id", "day", "kind", name="uq_usage_user_day_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    kind: Mapped[str] = mapped_column(String(10))
    count: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Base):
    """A successful Telegram Stars payment (kept for refunds and the admin report)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)  # Stars
    currency: Mapped[str] = mapped_column(String(8), default="XTR")
    payload: Mapped[str] = mapped_column(String(128), default="")
    charge_id: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Event(Base):
    """Product analytics kept in our own DB: the funnel and the lead count for reports."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(50), index=True)
    props: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class UserFact(Base):
    """Something the persona remembers about the user: "studies at a university", "loves pasta"…"""

    __tablename__ = "user_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fact: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChatMessage(Base):
    """Recent conversation with the persona, so it survives restarts and deploys."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Meta(Base):
    """Small key/value store for bot-wide state (e.g. when the last backup was sent)."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Deck(Base):
    __tablename__ = "decks"
    __table_args__ = (UniqueConstraint("user_id", "target_lang"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_lang: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id"), index=True)
    lemma: Mapped[str] = mapped_column(String(200), index=True)
    display: Mapped[str] = mapped_column(String(200))  # with article: «la finestra»
    reading: Mapped[str] = mapped_column(String(200), default="")  # romaji / pinyin, if useful
    pos: Mapped[str] = mapped_column(String(50), default="")
    translations: Mapped[list[str]] = mapped_column(JSON, default=list)
    example: Mapped[str] = mapped_column(Text, default="")
    example_translation: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Card(Base):
    """One review direction of a word: fwd = target→native, rev = native→target."""

    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), index=True)
    direction: Mapped[str] = mapped_column(String(3))
    due: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    fsrs: Mapped[dict[str, Any]] = mapped_column(JSON)  # fsrs.Card.to_dict()

    word: Mapped[Word] = relationship(lazy="joined")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Persona(Base):
    """A character the bot plays. Exactly one per user is active."""

    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(200), default="")
    card: Mapped[dict[str, Any]] = mapped_column(JSON)  # PersonaCard.model_dump()
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    avatar_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Telegram file_id
    avatar_credit: Mapped[str] = mapped_column(Text, default="", server_default="")  # HTML caption line
    art_tag: Mapped[str] = mapped_column(String(200), default="", server_default="")  # Danbooru character tag
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PersonaArt(Base):
    """Arts already sent to Telegram: reused by file_id instead of downloading again.

    The user can curate them in /stickers: `pinned` ones form "my set" for the emotion (then only they
    are used), `banned` ones are never sent again (the row stays so the art isn't downloaded again).
    Stickers the user forwarded have post_id "tg:<file_unique_id>:<emotion>".
    """

    __tablename__ = "persona_arts"
    # One row per emotion: the same art can be in "happy" and still unchosen in "proud".
    __table_args__ = (UniqueConstraint("persona_id", "emotion", "post_id", name="uq_persona_arts_emotion_post"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    emotion: Mapped[str] = mapped_column(String(20))
    post_id: Mapped[str] = mapped_column(String(80))
    file_id: Mapped[str] = mapped_column(String(200))
    credit: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TtsCache(Base):
    """Spoken audio already uploaded to Telegram: key = sha1(voice + rate + text) → voice message file_id."""

    __tablename__ = "tts_cache"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
