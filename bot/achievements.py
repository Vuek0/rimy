"""Achievements worth sharing: a streak or a vocabulary milestone → a card in the chat with an invite link.

Each milestone is celebrated once per learned language (an event `streak_<lang>_<n>` / `words_<lang>_<n>`).
The invite link carries the sharer's code (`?start=ref_friend_<base36 id>`), so the dashboard counts who came from friends.
"""

import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from bot import cards
from bot.billing import Billing
from bot.cards import CardSpec
from bot.db.models import Deck, User
from bot.db.repo import Repo
from bot.utils import compute_streak

log = logging.getLogger(__name__)

FRIEND_PREFIX = "friend_"  # ref codes of users invited by other users: ref_friend_<base36 id>
RECENT = 3  # a streak milestone is celebrated only right after it's reached (the lazy day can jump over one)
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def invite_code(user_id: int) -> str:
    n, out = user_id, ""
    while True:
        n, r = divmod(n, 36)
        out = _DIGITS[r] + out
        if n == 0:
            return FRIEND_PREFIX + out


async def invite_link(bot: Bot, user_id: int) -> str:
    me = await bot.me()  # cached by aiogram after the first call
    return f"https://t.me/{me.username}?start=ref_{invite_code(user_id)}"


def share_url(link: str, lang: str) -> str:
    """Telegram's own "share to a chat" dialog with a text and the invite link."""
    text = cards.SHARE_TEXT.get(lang, cards.SHARE_TEXT["ru"])
    return f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"


async def current_streak(repo: Repo, user: User, deck: Deck, now: datetime) -> int:
    tz = ZoneInfo(user.timezone)
    since = now - timedelta(days=400)
    times = await repo.review_times(deck.id, since) + await repo.word_times(deck.id, since)
    return compute_streak({t.astimezone(tz).date() for t in times}, now.astimezone(tz).date())


async def new_achievement(
    repo: Repo, billing: Billing, user: User, deck: Deck, now: datetime, word_saved: bool = False
) -> CardSpec | None:
    """The milestone just reached (and not celebrated yet), or None. Call after a review or a saved word."""
    lang = deck.target_lang
    if word_saved:
        total = await repo.count_words(deck.id)
        if total in cards.WORD_MILESTONES and await billing.track_once(user.id, f"words_{lang}_{total}", now):
            return CardSpec("words", total, user.native_lang, lang)
    streak = await current_streak(repo, user, deck, now)
    reached = [m for m in cards.STREAK_MILESTONES if m <= streak]
    if reached and streak - reached[-1] < RECENT:
        if await billing.track_once(user.id, f"streak_{lang}_{reached[-1]}", now):
            return CardSpec("streak", reached[-1], user.native_lang, lang)
    return None


async def send_card(bot: Bot, user_id: int, spec: CardSpec) -> None:
    """The card as a photo in the user's chat, with a "share with a friend" button."""
    link = await invite_link(bot, user_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=cards.SHARE_BUTTON.get(spec.lang, cards.SHARE_BUTTON["ru"]), url=share_url(link, spec.lang))]]
    )
    await bot.send_photo(
        user_id,
        BufferedInputFile(cards.render(spec), filename=f"rimy-{spec.kind}-{spec.n}.jpg"),
        caption=cards.caption(spec.kind, spec.n, spec.lang) + f"\n\n👉 {link}",
        reply_markup=keyboard,
    )


async def celebrate(
    bot: Bot, repo: Repo, billing: Billing, user: User, deck: Deck, now: datetime, word_saved: bool = False
) -> CardSpec | None:
    """Check for a new milestone and send its card. Never fails the action that triggered it."""
    try:
        spec = await new_achievement(repo, billing, user, deck, now, word_saved)
        if spec is not None:
            await send_card(bot, user.id, spec)
            await billing.track(user.id, "card_sent", now, kind=spec.kind, n=spec.n)
        return spec
    except Exception:  # noqa: BLE001 - a card is a bonus, not worth an error message
        log.exception("achievement card for %s failed", user.id)
        return None


# --- public card images (Telegram fetches them for shared messages and stories) ---


def card_signature(secret: str, spec: CardSpec) -> str:
    msg = f"{spec.kind}:{spec.n}:{spec.lang}:{spec.target}:{spec.fmt}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:20]


def card_path(secret: str, spec: CardSpec) -> str:
    return f"/api/card/{spec.kind}/{spec.n}/{spec.lang}/{spec.target}/{spec.fmt}/{card_signature(secret, spec)}.jpg"
