import json
import re

from pydantic import BaseModel, ValidationError, field_validator


class AIError(Exception):
    pass


class Sense(BaseModel):
    translation: str
    example: str = ""
    example_translation: str = ""
    note: str = ""


class WordAnalysis(BaseModel):
    heard: str = ""  # transcript, for voice input
    is_valid: bool = True
    lemma: str = ""
    display: str = ""
    reading: str = ""
    pos: str = ""
    senses: list[Sense] = []
    suggestions: list[str] = []
    notes: str = ""
    issues: list[str] = []
    user_translation: str = ""  # "macchina - машина": the learner's own translation, used instead of ours

    @field_validator("user_translation", mode="before")
    @classmethod
    def _text(cls, value: object) -> object:
        return str(value or "").strip()

    @field_validator("suggestions", "issues", mode="before")
    @classmethod
    def _drop_empty(cls, value: object) -> object:
        if isinstance(value, list):
            return [str(v).strip() for v in value if v and str(v).strip()]
        return value

    @field_validator("senses", mode="before")
    @classmethod
    def _drop_empty_senses(cls, value: object) -> object:
        if isinstance(value, list):
            return [s for s in value if isinstance(s, dict) and str(s.get("translation") or "").strip()]
        return value


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_json_object(raw: str) -> dict:
    """Model output → dict. Tolerates ```json fences and a one-element list around the object."""
    text = (raw or "").strip()
    if match := _FENCE.match(text):
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError(f"bad AI response: {exc}") from exc
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise AIError(f"expected a JSON object, got {type(data).__name__}")
    return data


def parse_analysis(raw: str) -> WordAnalysis:
    try:
        return WordAnalysis.model_validate(parse_json_object(raw))
    except ValidationError as exc:
        raise AIError(f"bad AI response: {exc}") from exc
