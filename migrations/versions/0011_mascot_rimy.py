"""the mascot is "Rimy" in every language (was «Рими»)

Existing users keep their mascot row: rename it and its card, so the bot and the AI use the new name.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25 12:00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD, NEW = "Рими", "Rimy"


def _rename(old: str, new: str) -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, card FROM personas WHERE name = :old"), {"old": old}).all()
    for persona_id, card in rows:
        data = json.loads(card) if isinstance(card, str) else dict(card or {})
        # the name is inside the card's texts too («Добродушный ленивец Рими…», greetings)
        data = json.loads(json.dumps(data, ensure_ascii=False).replace(old, new))
        conn.execute(
            sa.text("UPDATE personas SET name = :new, card = :card WHERE id = :id"),
            {"new": new, "card": json.dumps(data, ensure_ascii=False), "id": persona_id},
        )


def upgrade() -> None:
    _rename(OLD, NEW)


def downgrade() -> None:
    _rename(NEW, OLD)
