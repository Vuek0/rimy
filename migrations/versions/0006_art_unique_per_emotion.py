"""persona_arts: unique per (persona, emotion, post) instead of (persona, post)

The same art may fit several emotions; each emotion now keeps its own row (pinned/banned separately).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import bot.db.models

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table(unique_columns: list[str], name: str) -> sa.Table:
    """The full persona_arts definition. The old unique constraint has no name (can't be dropped by name
    on SQLite), so the table is recreated from this definition instead of being altered in place."""
    return sa.Table(
        "persona_arts",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("personas.id"), nullable=False),
        sa.Column("emotion", sa.String(length=20), nullable=False),
        sa.Column("post_id", sa.String(length=80), nullable=False),
        sa.Column("file_id", sa.String(length=200), nullable=False),
        sa.Column("credit", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("banned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", bot.db.models.UTCDateTime(), nullable=False),
        sa.UniqueConstraint(*unique_columns, name=name),
        sa.Index("ix_persona_arts_persona_id", "persona_id"),
    )


def upgrade() -> None:
    new = _table(["persona_id", "emotion", "post_id"], "uq_persona_arts_emotion_post")
    with op.batch_alter_table("persona_arts", recreate="always", copy_from=new):
        pass


def downgrade() -> None:
    old = _table(["persona_id", "post_id"], "uq_persona_arts_post")
    with op.batch_alter_table("persona_arts", recreate="always", copy_from=old):
        pass
