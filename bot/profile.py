"""The bot's Telegram profile texts, in the user's Telegram language (ru / uz / en; ru is the default).

description: the "What can this bot do?" card in an empty chat (up to 512 characters).
short description: the bot's profile page and link previews (up to 120 characters).
Set at startup, only when they differ from what Telegram has (these methods are rate-limited).
"""

import logging

from aiogram import Bot

log = logging.getLogger(__name__)

DESCRIPTION = {
    "ru": (
        "Учи иностранные слова голосом 🦥\n\n"
        "Скажи слово в голосовом сообщении, и Рими сделает карточку: перевод, пример и произношение. "
        "Интервальные повторения напомнят слово прямо перед тем, как ты его забудешь.\n\n"
        "Английский, корейский, турецкий, немецкий и другие языки. Нажми «Начать»!"
    ),
    "uz": (
        "Chet tilidagi so'zlarni ovoz bilan o'rgan 🦥\n\n"
        "So'zni ovozli xabarda ayt, Rimi esa karta tayyorlaydi: tarjima, misol va talaffuz. "
        "Takrorlash tizimi so'zni unutishingdan sal oldin eslatadi.\n\n"
        "Ingliz, koreys, turk, nemis va boshqa tillar. «Boshlash» tugmasini bos!"
    ),
    "en": (
        "Learn foreign words by voice 🦥\n\n"
        "Say a word in a voice message and Rimi makes a flashcard: translation, example and pronunciation. "
        "Spaced repetition brings each word back right before you'd forget it.\n\n"
        "English, Korean, Turkish, German and more. Tap Start!"
    ),
}

SHORT_DESCRIPTION = {
    "ru": "Учи слова голосом: скажи слово, и Рими сделает карточку с переводом, примером и озвучкой 🦥",
    "uz": "So'zlarni ovoz bilan o'rgan: so'zni ayt, Rimi tarjima, misol va talaffuz bilan karta yasaydi 🦥",
    "en": "Learn words by voice: say a word and Rimi makes a card with translation, example and audio 🦥",
}
DEFAULT = "ru"


async def set_profile(bot: Bot) -> None:
    for lang in (None, *DESCRIPTION):  # None = the default for every other Telegram language
        texts = DESCRIPTION[lang or DEFAULT], SHORT_DESCRIPTION[lang or DEFAULT]
        code = lang or ""
        try:
            if (await bot.get_my_description(language_code=code)).description != texts[0]:
                await bot.set_my_description(description=texts[0], language_code=code)
            if (await bot.get_my_short_description(language_code=code)).short_description != texts[1]:
                await bot.set_my_short_description(short_description=texts[1], language_code=code)
        except Exception:  # noqa: BLE001 - a profile text is never a reason not to start the bot
            log.warning("could not update the bot description (%s)", code or "default", exc_info=True)
