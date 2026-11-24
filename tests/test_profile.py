"""The bot's profile texts fit Telegram's limits and are only re-sent when they changed."""

from types import SimpleNamespace

from bot.profile import DESCRIPTION, SHORT_DESCRIPTION, set_profile


def test_texts_fit_telegram_limits():
    assert set(DESCRIPTION) == set(SHORT_DESCRIPTION) == {"ru", "uz", "en"}
    for lang in DESCRIPTION:
        assert len(DESCRIPTION[lang]) <= 512 and len(SHORT_DESCRIPTION[lang]) <= 120
        assert "—" not in DESCRIPTION[lang] + SHORT_DESCRIPTION[lang]  # no long dashes in our texts


class FakeBot:
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
        self.sets = 0

    async def get_my_description(self, language_code=""):
        return SimpleNamespace(description=self.store.get(("d", language_code), ""))

    async def get_my_short_description(self, language_code=""):
        return SimpleNamespace(short_description=self.store.get(("s", language_code), ""))

    async def set_my_description(self, description, language_code=""):
        self.store[("d", language_code)] = description
        self.sets += 1

    async def set_my_short_description(self, short_description, language_code=""):
        self.store[("s", language_code)] = short_description
        self.sets += 1


async def test_set_profile_only_when_changed():
    bot = FakeBot()
    await set_profile(bot)
    assert bot.sets == 8  # default + ru/uz/en, two texts each
    assert bot.store[("d", "")] == DESCRIPTION["ru"] and bot.store[("s", "uz")] == SHORT_DESCRIPTION["uz"]
    await set_profile(bot)
    assert bot.sets == 8  # nothing changed: no calls (they are rate-limited)
