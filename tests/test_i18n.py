"""Server-side texts the Mini App shows follow the learner's base language (ru / uz / en)."""

import re
from datetime import timedelta

from bot import promo
from bot.billing import Billing, Quota
from bot.langs import card_question, get_lang
from bot.utils import format_interval
from tests.test_billing_api import settings


def test_intervals_and_questions():
    assert format_interval(timedelta(days=2)) == "2 дн"
    assert format_interval(timedelta(days=2), "uz") == "2 kun"
    assert format_interval(timedelta(hours=3), "en") == "3 h"
    assert card_question("fwd", "en", "uz") == "Qanday tarjima qilinadi?"
    assert card_question("rev", "ko", "uz") == "koreys tilida qanday bo'ladi?"
    assert card_question("rev", "it", "en") == "How do you say it in Italian?"
    assert card_question("rev", "it", "ru") == "Как будет по-итальянски?"
    assert get_lang("de").name("uz") == "nemis" and get_lang("de").name("en") == "German"


def test_chat_texts_exist_in_every_language():
    from bot.i18n import COMMANDS, TEXTS

    assert set(TEXTS["uz"]) == set(TEXTS["ru"]) == set(TEXTS["en"])
    for lang in ("uz", "en"):
        for key, value in TEXTS["ru"].items():
            # the same {placeholders}, so tr() never fails on a missing name
            fields = lambda v: sorted(set(re.findall(r"{(\w+)}", v if isinstance(v, str) else " ".join(v))))
            assert fields(TEXTS[lang][key]) == fields(value), (lang, key)
    assert [c for c, _ in COMMANDS["uz"]] == [c for c, _ in COMMANDS["ru"]] == [c for c, _ in COMMANDS["en"]]


def test_tr_follows_the_update_language():
    from bot.i18n import set_lang, tr
    from bot.persona.card import DEFAULT_CARD, phrase

    set_lang("uz")
    try:
        assert tr("rate.3") == "Yaxshi" and tr("review.left", n=4).startswith("<i>Qoldi: 4")
        assert phrase(DEFAULT_CARD, "saved", []) in __import__("bot.i18n").i18n.TEXTS["uz"]["saved"]
    finally:
        set_lang("ru")
    assert tr("rate.3") == "Хорошо"


def test_limit_and_promo_messages():
    billing = Billing(None, settings())  # type: ignore[arg-type]  # limit_message doesn't touch the session
    quota = Quota("voice", 20, 20)
    assert "ovozli" in billing.limit_message(quota, "uz") and "voice" in billing.limit_message(quota, "en")
    assert "голосовые" in billing.limit_message(quota)
    result = promo.PromoResult("pending", 30)
    assert "+30 kun" in promo.message(result, "uz") and "+30 days" in promo.message(result, "en")
