import pytest

from bot.ai.prompts import text_prompt, transcription_hint
from bot.ai.schemas import AIError, parse_analysis


def test_plain_json():
    a = parse_analysis('{"lemma": "casa", "display": "la casa", "senses": [{"translation": "дом"}]}')
    assert a.lemma == "casa"
    assert a.display == "la casa"
    assert a.senses[0].translation == "дом"
    assert a.is_valid is True
    assert a.suggestions == []


def test_fenced_json_and_list_wrapper():
    a = parse_analysis('```json\n[{"lemma": "mangiare", "is_valid": true}]\n```')
    assert a.lemma == "mangiare"


def test_cleans_empty_items():
    a = parse_analysis(
        '{"suggestions": ["", "mangiare", null], "issues": [" "], '
        '"senses": [{"translation": ""}, {"translation": "есть"}, "junk"]}'
    )
    assert a.suggestions == ["mangiare"]
    assert a.issues == []
    assert [s.translation for s in a.senses] == ["есть"]


@pytest.mark.parametrize("raw", ["", "not json", "42", '{"senses": "oops"}'])
def test_garbage_raises(raw):
    with pytest.raises(AIError):
        parse_analysis(raw)


def test_prompts_mention_languages():
    p = text_prompt("casa", "it", "ru")
    assert "Italian" in p and "Russian" in p and '"casa"' in p
    hint = transcription_hint("it", "ru")
    assert "Привет" in hint and "Ciao" in hint
    assert transcription_hint("en", "en").count("Hello") == 1
