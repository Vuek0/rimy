from bot.handlers import all_routers
from bot.handlers.add_word import make_draft
from bot.ai.schemas import parse_analysis
from bot.texts import render_word


def test_handlers_import_and_routers_unique():
    import bot.__main__  # noqa: F401  (entry point imports cleanly)

    names = [r.name for r in all_routers()]
    assert len(names) == len(set(names))


def test_make_draft_and_render():
    analysis = parse_analysis(
        '{"lemma": "finestra", "display": "la finestra", "pos": "сущ., ж.р.", '
        '"senses": [{"translation": "окно", "example": "Apri la finestra.", "example_translation": "Открой окно."},'
        ' {"translation": "окошко"}], "notes": "<ж.р.>"}'
    )
    draft = make_draft(analysis, analysis.senses, "finestra")
    assert draft["translations"] == ["окно", "окошко"]
    assert draft["example"] == "Apri la finestra."
    html = render_word(draft)
    assert "<b>la finestra</b>" in html and "&lt;ж.р.&gt;" in html

    fallback = make_draft(parse_analysis("{}"), [], "parola")
    assert fallback["lemma"] == fallback["display"] == "parola" and fallback["translations"] == []
