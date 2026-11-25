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


def test_uzbek_is_latin_and_the_mascot_is_rimy():
    from bot.ai import prompts
    from bot.i18n import TEXTS
    from bot.persona.card import DEFAULT_CARD, MASCOT_NAME

    # the AI is told to write Uzbek in Latin letters, in every prompt that names the language
    assert "Latin" in get_lang("uz").prompt and "Cyrillic" in get_lang("uz").prompt
    assert "Latin alphabet" in prompts.text_prompt("kitob", "en", "uz")
    assert "Latin alphabet" in prompts.persona_system_prompt("{}", "en", "uz", practice=False)
    assert get_lang("it").prompt == "Italian" and get_lang("uz").name("en") == "Uzbek"  # menus stay short
    assert "Salom" in prompts.transcription_hint("en", "uz")

    # one name in every language, never «Рими» / "Rimi"
    assert MASCOT_NAME == DEFAULT_CARD.name == "Rimy"
    everything = repr(TEXTS) + DEFAULT_CARD.model_dump_json()
    assert "Рими" not in everything and "Rimi" not in everything and everything.count("Rimy") > 10


async def test_migration_renames_the_mascot(tmp_path):
    import json

    from sqlalchemy import text

    from bot.db.session import make_engine, run_migrations

    url = f"sqlite+aiosqlite:///{(tmp_path / 'm.db').as_posix()}"
    engine = make_engine(url)
    await run_migrations(url)
    async with engine.begin() as conn:  # a mascot row saved before the rename
        await conn.execute(
            text("INSERT INTO personas (user_id, name, source, card, is_active, avatar_credit, art_tag, created_at) "
                 "VALUES (7, :n, '', :c, 1, '', '', '2026-01-01')"),
            {"n": "Рими", "c": json.dumps({"name": "Рими", "appearance": "Ленивец Рими"}, ensure_ascii=False)},
        )
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "migrations" / "versions" / "0011_mascot_rimy.py"
    spec = importlib.util.spec_from_file_location("mascot_rimy", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: _run_with_op(sync, migration.upgrade))
        name, card = (await conn.execute(text("SELECT name, card FROM personas"))).one()
    await engine.dispose()
    assert name == "Rimy" and json.loads(card) == {"name": "Rimy", "appearance": "Ленивец Rimy"}


def _run_with_op(sync_conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(sync_conn)):
        fn()


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
