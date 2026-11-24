"""promo codes: extra Premium days handed out in person

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-24 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'promo_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=32), nullable=False, unique=True),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'promo_redemptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('promo_id', sa.Integer(), sa.ForeignKey('promo_codes.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'promo_id', name='uq_promo_redemptions_user_promo'),
    )
    op.create_index('ix_promo_redemptions_user_id', 'promo_redemptions', ['user_id'])
    op.create_index('ix_promo_redemptions_promo_id', 'promo_redemptions', ['promo_id'])


def downgrade() -> None:
    op.drop_index('ix_promo_redemptions_promo_id', table_name='promo_redemptions')
    op.drop_index('ix_promo_redemptions_user_id', table_name='promo_redemptions')
    op.drop_table('promo_redemptions')
    op.drop_table('promo_codes')
