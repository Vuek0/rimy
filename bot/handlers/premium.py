"""Premium: a monthly Telegram Stars subscription (XTR), bought in the chat or from the Mini App.

Telegram requires Stars for digital goods sold in bots and Mini Apps, so no payment provider token is needed.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery

from bot import menu, promo
from bot.billing import PREMIUM_PAYLOAD, Billing
from bot.config import Settings
from bot.db.models import User
from bot.utils import esc, utcnow

log = logging.getLogger(__name__)
router = Router(name="premium")

SUBSCRIPTION_SECONDS = 30 * 24 * 3600  # Telegram allows only 30-day Star subscriptions

PREMIUM_TEXT = (
    "⭐ <b>Premium</b>\n\n"
    "• Без лимита на AI-слова, голосовые и разговоры с маскотом\n"
    "• AI-проверка ответов в повторении без ограничений\n"
    "• Все языки сразу\n\n"
    "Повторение карточек всегда бесплатно.\n"
    "🎁 Есть промокод? <code>/promo КОД</code>"
)


async def premium_invoice_link(bot: Bot, settings: Settings) -> str:
    """A subscription invoice: the bot sends it as a button, the Mini App opens it with openInvoice()."""
    return await bot.create_invoice_link(
        title="Premium на 30 дней",
        description="Без лимитов на AI-слова, голос и практику с маскотом",
        payload=PREMIUM_PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice(label="Premium", amount=settings.premium_price_stars)],
        subscription_period=SUBSCRIPTION_SECONDS,
    )


def usage_lines(quotas) -> str:
    names = {"word": "AI-слова", "voice": "голосовые", "chat": "сообщения маскоту", "check": "AI-проверки"}
    return "\n".join(f"• {names[q.kind]}: {q.used} из {q.limit}" for q in quotas)


@router.message(Command("premium"))
@router.message(menu.button(menu.PREMIUM))
async def cmd_premium(message: Message, bot: Bot, user: User, billing: Billing, settings: Settings) -> None:
    now = utcnow()
    await billing.track(user.id, "paywall_view", now, source="bot")
    if user.is_premium(now):
        assert user.premium_until is not None
        until = user.premium_until.strftime("%d.%m.%Y")
        await message.answer(f"{PREMIUM_TEXT}\n\n✅ У тебя Premium до <b>{until}</b>. Спасибо! 💛")
        return
    link = await premium_invoice_link(bot, settings)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"⭐ Подписаться за {settings.premium_price_stars} Stars / мес", url=link)
    ]])
    used = usage_lines(await billing.quotas(user, now))
    await message.answer(f"{PREMIUM_TEXT}\n\n<b>Сегодня на бесплатном тарифе:</b>\n{used}", reply_markup=keyboard)


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    if query.invoice_payload != PREMIUM_PAYLOAD or query.currency != "XTR":
        await query.answer(ok=False, error_message="Неизвестный товар, попробуй ещё раз через /premium")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(message: Message, user: User, billing: Billing) -> None:
    payment = message.successful_payment
    assert payment is not None
    bonus = await promo.pending_days(billing.s, user)  # promo codes entered before paying
    until = await billing.grant_premium(
        user, utcnow(), payment.telegram_payment_charge_id, payment.total_amount, payment.invoice_payload
    )
    log.info("premium bought by %s, %d %s", user.id, payment.total_amount, payment.currency)
    gift = f"\n🎁 Промокод: +{bonus} дн. в подарок!" if bonus else ""
    await message.answer(
        f"🎉 Premium активирован до <b>{esc(until.strftime('%d.%m.%Y'))}</b>!{gift}\n"
        "Теперь никаких лимитов - присылай слова сколько хочешь 🦥"
    )


@router.message(Command("promo"))
async def cmd_promo(message: Message, command: CommandObject, user: User, billing: Billing) -> None:
    """/promo CODE - a code from the Rimy team: extra Premium days on top of a paid subscription."""
    code = (command.args or "").strip()
    if not code:
        await message.answer(
            "🎁 Есть промокод от команды Rimy? Пришли его так:\n<code>/promo КОД</code>\n\n"
            "Промокод добавляет дни к Premium: если подписки ещё нет, он подождёт до оплаты."
        )
        return
    result = await promo.redeem(billing.s, user, code, utcnow())
    await message.answer(esc(promo.message(result, user.native_lang)))
