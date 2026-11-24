"""Server-side texts the Mini App shows follow the learner's base language (ru / uz / en)."""

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


def test_limit_and_promo_messages():
    billing = Billing(None, settings())  # type: ignore[arg-type]  # limit_message doesn't touch the session
    quota = Quota("voice", 20, 20)
    assert "ovozli" in billing.limit_message(quota, "uz") and "voice" in billing.limit_message(quota, "en")
    assert "голосовые" in billing.limit_message(quota)
    result = promo.PromoResult("pending", 30)
    assert "+30 kun" in promo.message(result, "uz") and "+30 days" in promo.message(result, "en")
