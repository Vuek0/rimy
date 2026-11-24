from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot import srs
from bot.db.models import (
    Card,
    ChatMessage,
    Deck,
    Meta,
    Persona,
    PersonaArt,
    ReviewLog,
    TtsCache,
    User,
    UserFact,
    Word,
)
from bot.langs import get_lang
from bot.persona.card import DEFAULT_CARD

# The reverse card (native → target) becomes due later, so you don't see both sides of a new word back to back.
REVERSE_DELAY = timedelta(days=1)
# Like Anki's "learn ahead": cards due within this window are shown when nothing else is due.
LEARN_AHEAD = timedelta(minutes=20)

MAX_FACTS = 40  # facts about the user the persona keeps
LEGACY_DEFAULTS = {"Рокси", "Попи"}  # names of earlier default tutors, replaced by the mascot
MAX_CHAT = 200  # chat messages kept in the DB (the prompt uses only the last few)

DRAFT_FIELDS = ("lemma", "display", "reading", "pos", "translations", "example", "example_translation", "notes")


class Repo:
    def __init__(self, session: AsyncSession):
        self.s = session

    # --- users & decks ---

    async def ensure_user(
        self, tg_id: int, *, native_lang: str, timezone: str, target_lang: str
    ) -> tuple[User, Deck]:
        user = await self.s.get(User, tg_id)
        if user is None:
            # Several updates can arrive at once (e.g. after a restart): if another one created
            # the user first, the savepoint rolls back and we just load that row.
            await self._insert_ignoring_conflict(User(id=tg_id, native_lang=native_lang, timezone=timezone))
            user = await self.s.get(User, tg_id, populate_existing=True)
            assert user is not None
        deck = await self.s.get(Deck, user.active_deck_id) if user.active_deck_id else None
        if deck is None:
            deck = await self.switch_language(user, target_lang)
        return user, deck

    async def switch_language(self, user: User, lang: str) -> Deck:
        query = select(Deck).where(Deck.user_id == user.id, Deck.target_lang == lang)
        deck = await self.s.scalar(query)
        if deck is None:
            await self._insert_ignoring_conflict(Deck(user_id=user.id, target_lang=lang, name=get_lang(lang).name_ru))
            deck = await self.s.scalar(query)
            assert deck is not None
        user.active_deck_id = deck.id
        return deck

    # --- personas ---

    async def active_persona(self, user: User) -> Persona:
        """The persona the bot plays for this user; creates the default one (the mascot) on first use."""
        persona = await self.s.scalar(
            select(Persona).where(Persona.user_id == user.id, Persona.is_active.is_(True)).limit(1)
        )
        if persona is None:
            persona = await self.s.scalar(select(Persona).where(Persona.user_id == user.id).order_by(Persona.id).limit(1))
            if persona is None:
                persona = await self.add_persona(user, DEFAULT_CARD.model_dump(), activate=False)
            persona.is_active = True
            await self.s.flush()
        if persona.name in LEGACY_DEFAULTS:  # an earlier default tutor: becomes today's mascot
            await self.update_persona(persona, DEFAULT_CARD.model_dump())
        return persona

    async def add_persona(self, user: User, card: dict[str, Any], activate: bool = True) -> Persona:
        persona = Persona(user_id=user.id, name=card["name"][:100], source=(card.get("source") or "")[:200], card=card)
        self.s.add(persona)
        await self.s.flush()
        if activate:
            await self.activate_persona(user, persona.id)
        return persona

    async def list_personas(self, user: User) -> list[Persona]:
        return list(await self.s.scalars(select(Persona).where(Persona.user_id == user.id).order_by(Persona.id)))

    async def get_persona(self, user: User, persona_id: int) -> Persona | None:
        persona = await self.s.get(Persona, persona_id)
        return persona if persona is not None and persona.user_id == user.id else None

    async def activate_persona(self, user: User, persona_id: int) -> Persona | None:
        persona = await self.get_persona(user, persona_id)
        if persona is None:
            return None
        for other in await self.list_personas(user):
            other.is_active = other.id == persona_id
        await self.s.flush()
        return persona

    async def update_persona(self, persona: Persona, card: dict[str, Any]) -> None:
        persona.card = card
        persona.name = card["name"][:100]
        persona.source = (card.get("source") or "")[:200]
        await self.s.flush()

    async def delete_persona(self, user: User, persona_id: int) -> bool:
        """Delete a persona; the last one can't be deleted (the bot always plays someone)."""
        personas = await self.list_personas(user)
        target = next((p for p in personas if p.id == persona_id), None)
        if target is None or len(personas) == 1:
            return False
        was_active = target.is_active
        await self.s.execute(delete(PersonaArt).where(PersonaArt.persona_id == persona_id))
        await self.s.delete(target)
        await self.s.flush()
        if was_active:
            await self.active_persona(user)
        return True

    # --- persona arts ---

    async def set_avatar(self, persona: Persona, file_id: str | None, credit: str = "") -> None:
        persona.avatar_file_id = file_id
        persona.avatar_credit = credit
        await self.s.flush()

    async def cached_arts(self, persona_id: int, emotion: str) -> list[PersonaArt]:
        """Usable pictures for an emotion (banned ones excluded)."""
        rows = await self.s.scalars(
            select(PersonaArt)
            .where(PersonaArt.persona_id == persona_id, PersonaArt.emotion == emotion, PersonaArt.banned.is_(False))
            .order_by(PersonaArt.id)
        )
        return list(rows)

    async def known_post_ids(self, persona_id: int, emotion: str) -> set[str]:
        """All arts ever saved for the emotion, banned included: never download those again."""
        rows = await self.s.scalars(
            select(PersonaArt.post_id).where(PersonaArt.persona_id == persona_id, PersonaArt.emotion == emotion)
        )
        return set(rows)

    async def delete_art(self, art_id: int) -> None:
        await self.s.execute(delete(PersonaArt).where(PersonaArt.id == art_id))

    async def add_art(
        self, persona_id: int, emotion: str, post_id: str, file_id: str, credit: str, pinned: bool = False
    ) -> PersonaArt:
        """Save a picture for an emotion (or update it if it's already saved for that emotion). Returns the row."""
        same = select(PersonaArt).where(
            PersonaArt.persona_id == persona_id, PersonaArt.emotion == emotion, PersonaArt.post_id == post_id
        )
        art = await self.s.scalar(same)
        if art is None:
            await self._insert_ignoring_conflict(PersonaArt(
                persona_id=persona_id, emotion=emotion, post_id=post_id, file_id=file_id, credit=credit, pinned=pinned
            ))
            art = await self.s.scalar(same)
        else:
            art.file_id, art.banned = file_id, False
            art.pinned = art.pinned or pinned
            await self.s.flush()
        assert art is not None
        return art

    async def get_art(self, user: User, art_id: int) -> PersonaArt | None:
        """An art of one of this user's personas."""
        art = await self.s.get(PersonaArt, art_id)
        if art is None or await self.get_persona(user, art.persona_id) is None:
            return None
        return art

    # --- pronunciation cache ---

    async def tts_get(self, key: str) -> str | None:
        row = await self.s.get(TtsCache, key)
        return row.file_id if row else None

    async def tts_put(self, key: str, file_id: str) -> None:
        row = await self.s.get(TtsCache, key)
        if row is None:
            await self._insert_ignoring_conflict(TtsCache(key=key, file_id=file_id))
        else:
            row.file_id = file_id
            await self.s.flush()

    async def tts_forget(self, key: str) -> None:
        await self.s.execute(delete(TtsCache).where(TtsCache.key == key))

    async def word_of_user(self, user: User, word_id: int) -> Word | None:
        """A word from any of this user's decks (None for someone else's)."""
        word = await self.s.get(Word, word_id)
        if word is None:
            return None
        deck = await self.s.get(Deck, word.deck_id)
        return word if deck is not None and deck.user_id == user.id else None

    # --- memory: facts about the user and chat history ---

    async def facts(self, user_id: int) -> list[str]:
        rows = await self.s.scalars(select(UserFact.fact).where(UserFact.user_id == user_id).order_by(UserFact.id))
        return list(rows)

    async def add_facts(self, user_id: int, facts: list[str], now: datetime, keep: int = MAX_FACTS) -> list[str]:
        """Remember new facts (skipping ones already known); oldest are forgotten beyond `keep`. Returns added."""
        known = {_key(f) for f in await self.facts(user_id)}
        added = []
        for fact in facts:
            fact = fact.strip()[:300]
            if fact and _key(fact) not in known:
                known.add(_key(fact))
                self.s.add(UserFact(user_id=user_id, fact=fact, created_at=now))
                added.append(fact)
        await self.s.flush()
        ids = list(await self.s.scalars(
            select(UserFact.id).where(UserFact.user_id == user_id).order_by(UserFact.id.desc()).offset(keep)
        ))
        if ids:
            await self.s.execute(delete(UserFact).where(UserFact.id.in_(ids)))
        return added

    async def forget_facts(self, user_id: int) -> None:
        await self.s.execute(delete(UserFact).where(UserFact.user_id == user_id))

    async def add_chat(self, user_id: int, role: str, content: str, now: datetime, keep: int = MAX_CHAT) -> None:
        self.s.add(ChatMessage(user_id=user_id, role=role, content=content, created_at=now))
        await self.s.flush()
        ids = list(await self.s.scalars(
            select(ChatMessage.id).where(ChatMessage.user_id == user_id).order_by(ChatMessage.id.desc()).offset(keep)
        ))
        if ids:
            await self.s.execute(delete(ChatMessage).where(ChatMessage.id.in_(ids)))

    async def recent_chat(self, user_id: int, limit: int) -> list[dict[str, str]]:
        rows = list(await self.s.scalars(
            select(ChatMessage).where(ChatMessage.user_id == user_id).order_by(ChatMessage.id.desc()).limit(limit)
        ))
        return [{"role": m.role, "content": m.content} for m in reversed(rows)]

    async def clear_chat(self, user_id: int) -> None:
        await self.s.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))

    # --- activity, reminders, bot-wide state ---

    async def all_users(self) -> list[User]:
        return list(await self.s.scalars(select(User)))

    async def count_users(self) -> int:
        return await self.s.scalar(select(func.count(User.id))) or 0

    async def deck_of_user(self, user: User, deck_id: int) -> Deck | None:
        deck = await self.s.get(Deck, deck_id)
        return deck if deck is not None and deck.user_id == user.id else None

    async def card_of_deck(self, deck_id: int, card_id: int) -> Card | None:
        """A card, only if it belongs to this deck (API callers can't reach other users' cards)."""
        card = await self.s.get(Card, card_id)
        return card if card is not None and card.word.deck_id == deck_id else None

    async def meta_get(self, key: str) -> str:
        row = await self.s.get(Meta, key)
        return row.value if row else ""

    async def meta_set(self, key: str, value: str) -> None:
        row = await self.s.get(Meta, key)
        if row is None:
            self.s.add(Meta(key=key, value=value))
        else:
            row.value = value
        await self.s.flush()

    async def hard_words(self, deck_id: int, since: datetime, limit: int = 5) -> list[str]:
        """Words forgotten most often lately ("Снова" in reviews)."""
        stmt = (
            select(Word.display, func.count(ReviewLog.id).label("misses"))
            .join(Card, ReviewLog.card_id == Card.id)
            .join(Word, Card.word_id == Word.id)
            .where(Word.deck_id == deck_id, ReviewLog.rating == 1, ReviewLog.reviewed_at >= since)
            .group_by(Word.id, Word.display)
            .order_by(func.count(ReviewLog.id).desc())
            .limit(limit)
        )
        return [row.display for row in await self.s.execute(stmt)]

    async def _insert_ignoring_conflict(self, obj: object) -> None:
        try:
            async with self.s.begin_nested():
                self.s.add(obj)
        except IntegrityError:
            pass

    # --- words ---

    async def add_word(self, deck_id: int, draft: dict[str, Any], now: datetime) -> Word:
        word = Word(deck_id=deck_id, created_at=now, **{k: draft.get(k) or _empty(k) for k in DRAFT_FIELDS})
        self.s.add(word)
        await self.s.flush()
        for direction, due in (("fwd", now), ("rev", now + REVERSE_DELAY)):
            self.s.add(Card(word_id=word.id, direction=direction, due=due, fsrs=srs.new_card_state(now)))
        await self.s.flush()
        return word

    async def find_duplicates(self, deck_id: int, lemma: str) -> list[Word]:
        rows = await self.s.scalars(
            select(Word).where(Word.deck_id == deck_id, func.lower(Word.lemma) == lemma.strip().lower())
        )
        return list(rows)

    async def find_words(self, deck_id: int, query: str) -> list[Word]:
        q = query.strip().lower()
        rows = await self.s.scalars(
            select(Word)
            .where(Word.deck_id == deck_id, or_(func.lower(Word.lemma) == q, func.lower(Word.display) == q))
            .order_by(Word.created_at)
        )
        return list(rows)

    async def count_words_since(self, deck_id: int, since: datetime) -> int:
        stmt = select(func.count(Word.id)).where(Word.deck_id == deck_id, Word.created_at >= since)
        return await self.s.scalar(stmt) or 0

    async def previous_word_at(self, deck_id: int, word_id: int) -> datetime | None:
        """When the word added before this one was saved."""
        stmt = (
            select(Word.created_at)
            .where(Word.deck_id == deck_id, Word.id != word_id)
            .order_by(Word.created_at.desc())
            .limit(1)
        )
        return await self.s.scalar(stmt)

    async def get_word(self, word_id: int) -> Word | None:
        return await self.s.get(Word, word_id)

    async def list_words(self, deck_id: int, limit: int = 50) -> list[Word]:
        rows = await self.s.scalars(
            select(Word).where(Word.deck_id == deck_id).order_by(Word.created_at.desc(), Word.id.desc()).limit(limit)
        )
        return list(rows)

    async def count_words(self, deck_id: int) -> int:
        return await self.s.scalar(select(func.count(Word.id)).where(Word.deck_id == deck_id)) or 0

    async def delete_word(self, word_id: int) -> None:
        card_ids = select(Card.id).where(Card.word_id == word_id)
        await self.s.execute(delete(ReviewLog).where(ReviewLog.card_id.in_(card_ids)))
        await self.s.execute(delete(Card).where(Card.word_id == word_id))
        await self.s.execute(delete(Word).where(Word.id == word_id))

    # --- cards & reviews ---

    def _deck_cards(self, deck_id: int):
        return select(Card).join(Word, Card.word_id == Word.id).where(Word.deck_id == deck_id)

    async def next_due_card(self, deck_id: int, now: datetime, just_reviewed: int | None = None) -> Card | None:
        """Next card to show. The card that was just rated is not shown again ahead of time."""
        ahead = Card.due <= now + LEARN_AHEAD
        if just_reviewed is not None:
            ahead = ahead & ((Card.id != just_reviewed) | (Card.due <= now))
        stmt = self._deck_cards(deck_id).where(ahead).order_by(Card.due, Card.id).limit(1)
        return await self.s.scalar(stmt)

    async def count_due(self, deck_id: int, now: datetime) -> int:
        stmt = (
            select(func.count(Card.id))
            .join(Word, Card.word_id == Word.id)
            .where(Word.deck_id == deck_id, Card.due <= now)
        )
        return await self.s.scalar(stmt) or 0

    async def next_due_at(self, deck_id: int) -> datetime | None:
        stmt = (
            select(Card.due)
            .join(Word, Card.word_id == Word.id)
            .where(Word.deck_id == deck_id)
            .order_by(Card.due)
            .limit(1)
        )
        return await self.s.scalar(stmt)

    async def get_card(self, card_id: int) -> Card | None:
        return await self.s.get(Card, card_id)

    async def last_review_at(self, card_id: int) -> datetime | None:
        return await self.s.scalar(
            select(ReviewLog.reviewed_at)
            .where(ReviewLog.card_id == card_id)
            .order_by(ReviewLog.reviewed_at.desc())
            .limit(1)
        )

    async def record_review(
        self, card: Card, rating: int, new_state: dict[str, Any], new_due: datetime, now: datetime
    ) -> None:
        card.fsrs = new_state
        card.due = new_due
        self.s.add(ReviewLog(card_id=card.id, rating=rating, reviewed_at=now))
        await self.s.flush()

    async def review_times(self, deck_id: int, since: datetime) -> list[datetime]:
        stmt = (
            select(ReviewLog.reviewed_at)
            .join(Card, ReviewLog.card_id == Card.id)
            .join(Word, Card.word_id == Word.id)
            .where(Word.deck_id == deck_id, ReviewLog.reviewed_at >= since)
        )
        return list(await self.s.scalars(stmt))


def _empty(field: str) -> Any:
    return [] if field == "translations" else ""


def _key(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".!")
