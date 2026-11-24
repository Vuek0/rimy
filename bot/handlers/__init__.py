from aiogram import Router

from bot.handlers import add_word, admin, common, premium, review, settings, speech, talk, words


def all_routers() -> list[Router]:
    # Order matters: add_word goes last among content routers because it catches any free text.
    # The tutor is the app's mascot for everyone: choosing anime personas (/persona) and searching
    # their art (/stickers) are no longer part of the product.
    return [
        common.router,
        admin.router,
        premium.router,
        review.router,
        words.router,
        settings.router,
        speech.router,
        talk.router,
        add_word.router,
        common.fallback_router,
    ]
